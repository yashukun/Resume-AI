import asyncio
import httpx
from typing import Dict, Any, Optional, List
from app.core.config import settings
import logging
import json
import time

logger = logging.getLogger(__name__)


class ResumeExtractionError(Exception):
    """Raised when AI resume extraction fails — triggers Celery retry."""
    pass


class PreflightError(Exception):
    """
    Raised when the LLM environment isn't usable (Ollama unreachable,
    required model not pulled, etc.).

    These are NOT transient — retrying with the same broken environment
    is wasted time and floods logs. Celery tasks should catch this and
    fail the job immediately with a user-facing message instead of
    looping through the retry schedule.
    """
    pass


def _smart_truncate(text: str, max_chars: int, anchor_terms=None) -> str:
    """
    Truncate `text` to `max_chars`, but keep BOTH ends intact and trim
    the middle. A resume's most important info is in the header (name,
    contact, summary, skills) AND the most recent experience (top of
    chronological list). The middle of a long resume is the least
    critical for ATS / matching.

    Falls back to head-only truncation if the input is short or the
    anchor terms aren't found.

    Args:
        text: The full input text
        max_chars: Hard cap on output length
        anchor_terms: Optional list of strings — if found near the end,
                      we preserve a window around them (useful for keeping
                      "Required Skills" / "Responsibilities" in a JD)
    """
    if not text or len(text) <= max_chars:
        return text

    head_budget = int(max_chars * 0.65)  # 65 % from the top
    tail_budget = max_chars - head_budget - 50  # 50 chars for the joiner
    head = text[:head_budget]
    tail = text[-tail_budget:] if tail_budget > 0 else ""

    # If anchor terms are provided, try to align the tail window so it
    # starts on the earliest anchor occurrence near the end.
    if anchor_terms and tail_budget > 0:
        search_start = max(head_budget, len(text) - tail_budget * 2)
        earliest = len(text)
        for term in anchor_terms:
            idx = text.lower().find(term.lower(), search_start)
            if idx != -1 and idx < earliest:
                earliest = idx
        if earliest < len(text):
            anchored_tail = text[earliest: earliest + tail_budget]
            if anchored_tail:
                tail = anchored_tail

    return f"{head}\n\n[... middle section truncated for length ...]\n\n{tail}"


# Event-loop-aware HTTP client — each new event-loop (= each Celery task) gets
# a fresh client, preventing asyncio transport corruption in forked workers.
_http_client: Optional[httpx.AsyncClient] = None
_client_loop_id: Optional[int] = None

# Semaphore that throttles concurrent LLM calls. Configurable so the
# pipeline can run a few sections in parallel when Ollama is started
# with OLLAMA_NUM_PARALLEL>=2 (and the host has VRAM headroom). Setting
# this above what Ollama can actually serve just queues internally —
# tune both together.
_ollama_semaphore: Optional[asyncio.Semaphore] = None
_semaphore_loop_id: Optional[int] = None


def _get_semaphore() -> asyncio.Semaphore:
    """Get or create a semaphore bound to the current event loop."""
    global _ollama_semaphore, _semaphore_loop_id
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = None
    if _ollama_semaphore is None or _semaphore_loop_id != loop_id:
        _ollama_semaphore = asyncio.Semaphore(
            max(1, settings.ollama_parallel)
        )
        _semaphore_loop_id = loop_id
    return _ollama_semaphore


def _get_client() -> httpx.AsyncClient:
    """Get or create an httpx client bound to the current event loop.

    Celery prefork workers each create a new event loop per task (via run_async).
    Reusing an httpx.AsyncClient from a closed loop corrupts asyncio transports,
    so we detect the current loop and recreate the client when it changes.
    """
    global _http_client, _client_loop_id
    try:
        loop_id = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_id = None

    if _http_client is None or _http_client.is_closed or _client_loop_id != loop_id:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(900.0, connect=30.0),
            limits=httpx.Limits(max_connections=10,
                                max_keepalive_connections=5),
        )
        _client_loop_id = loop_id
    return _http_client


# ── Resume extraction prompt ─────────────────────────────────────────
RESUME_EXTRACTION_SYSTEM_PROMPT = """You are a resume parser. Extract info into this EXACT flat JSON format:

{
  "name": "Full Name",
  "email": "email@example.com",
  "phone": "+1-234-567-8901",
  "linkedin": "https://linkedin.com/in/...",
  "github": "https://github.com/...",
  "portfolio": "https://...",
  "location": "City, State",
  "summary": "Professional summary paragraph as-is from the resume",
  "skills": ["Python", "React", "AWS", "Docker"],
  "experience": [
    {
      "title": "Software Engineer",
      "company": "Company Inc.",
      "dates": "Jan 2022 - Present",
      "description": ["Led migration of monolith to microservices, reducing deploy time by 60%", "Built real-time pipeline processing 2M events/day"]
    }
  ],
  "education": [
    {
      "degree": "B.S. Computer Science",
      "institution": "University Name",
      "year": "2022"
    }
  ],
  "certifications": ["AWS Solutions Architect", "CKA"],
  "projects": [
    {
      "name": "Project Name",
      "description": "Brief description",
      "technologies": ["React", "Node.js"],
      "bullets": ["Concrete achievement or technical detail"],
      "link": "https://github.com/..."
    }
  ],
  "extracted_links": {"linkedin": ["url"], "github": ["url"], "portfolio": ["url"], "other": ["url"]}
}

RULES:
- Return ONLY valid JSON, no other text or markdown
- Use null for any missing field, [] for missing arrays
- "skills" must be a FLAT array of individual skill strings (split comma-separated lists)
- "experience" entries MUST have title, company, dates, description (array of bullet strings)
- "education" entries MUST have degree, institution, year (year = graduation year or date range)
- "certifications" is a flat string array
- "summary" is the actual professional summary / objective paragraph from the resume as-is
- PRE-EXTRACTED LINKS are provided after the resume — use them directly for linkedin, github, portfolio fields. Do NOT guess or hallucinate URLs.
- For experience description: extract ONLY specific achievements with measurable results. Drop generic filler like "Responsible for...".
- For projects: capture what was built, the tech used, and scale/impact.
- Preserve the candidate's actual content faithfully — do NOT rewrite or embellish."""

# ── Job description extraction prompt ────────────────────────────────
JD_EXTRACTION_SYSTEM_PROMPT = """You are a job description analyzer. Extract info into this EXACT JSON format:

{
  "job_title": "Senior Software Engineer",
  "company_name": "Company Inc.",
  "industry": "FinTech",
  "seniority_level": "Senior",
  "required_skills": ["Python", "AWS", "SQL"],
  "preferred_skills": ["Kubernetes", "Terraform"],
  "responsibilities": ["Design and build scalable APIs", "Mentor junior engineers"],
  "keywords": ["microservices", "CI/CD", "agile", "REST API", "distributed systems"]
}

RULES:
- Return ONLY valid JSON, no other text or markdown
- "required_skills" = skills listed as required / must-have / minimum qualifications
- "preferred_skills" = nice-to-have / preferred / bonus skills
- "keywords" = the MOST IMPORTANT ATS terms: technical buzzwords, tools, frameworks, methodologies, domain terms that an ATS would scan for. Include items from required_skills and preferred_skills too. This is the most critical field.
- "seniority_level" = one of: Intern, Junior, Mid, Senior, Staff, Principal, Lead, Manager, Director, VP, C-Level, or null
- Use null for any field you cannot determine, [] for missing arrays
- Be thorough with keywords — extract every technical term, tool, framework, methodology, and domain keyword from the description"""


class AIService:
    """
    AI Service for Resume Optimization and ATS Analysis.

    This service integrates with Ollama to provide:
    1. AI Resume Optimization Engine - Enhances resume content based on JD
    2. ATS Formatting Engine - Analyzes and formats for ATS compatibility

    Current implementation is a foundation. Future enhancements:

    AI Resume Optimization Engine Ideas:
    - Keyword extraction from JD and resume matching
    - Experience bullet point enhancement with action verbs
    - Skills gap analysis and recommendations
    - Summary/objective tailoring for specific roles
    - Quantification suggestions (adding metrics to achievements)

    ATS Formatting Engine Ideas:
    - Keyword density analysis
    - Format compatibility check (avoid tables, graphics, etc.)
    - Section header standardization
    - Date format consistency
    - Contact info validation
    - Job title alignment with JD
    - Score calculation with breakdown
    """

    def __init__(self):
        self.base_url = settings.ollama_base_url
        self.coder_model = settings.ollama_model_coder
        self.general_model = settings.ollama_model_general
        self.fast_model = settings.ollama_model_fast

    async def health_check(self) -> bool:
        """Check if Ollama is available."""
        try:
            client = _get_client()
            response = await client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def list_models(self) -> List[str]:
        """List available models in Ollama."""
        try:
            client = _get_client()
            response = await client.get(f"{self.base_url}/api/tags", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.error(f"Error listing models: {e}")
        return []

    async def preflight(self, required_models: Optional[List[str]] = None) -> None:
        """
        Verify Ollama is reachable AND the required models are pulled
        BEFORE we start a long-running task.

        Raises:
            PreflightError: with a user-facing message that explains the
            exact fix (start Ollama / pull a model). Tasks should
            translate this into ``Job.error_message`` and skip retry.

        Why fail fast here:
            A single LLM call has a 20-minute httpx timeout, and the
            task retries 3× — so a missing dependency can leave a job
            stuck on "PARSING" for an hour before we even tell the user
            something is wrong. The preflight runs in <1 second and
            converts that into an immediate, actionable error.
        """
        required = required_models or [self.fast_model, self.general_model]

        # 1) Is Ollama reachable at all? Use a short timeout — if the
        # service is down, the OS returns Connection-Refused in <1ms.
        try:
            client = _get_client()
            response = await client.get(
                f"{self.base_url}/api/tags", timeout=3.0,
            )
        except Exception as e:
            raise PreflightError(
                f"Ollama is not reachable at {self.base_url}. "
                f"Start it on the host with `ollama serve` (Mac: "
                f"`brew services start ollama`) and try again. "
                f"Underlying error: {type(e).__name__}: {e}"
            ) from e

        if response.status_code != 200:
            raise PreflightError(
                f"Ollama responded with HTTP {response.status_code} at "
                f"{self.base_url}/api/tags. Expected 200. "
                f"Body: {response.text[:200]}"
            )

        # 2) Are the required models pulled? Match on prefix because
        # Ollama tags are returned as e.g. "llama3.2:3b" — exact match.
        available = {m["name"] for m in response.json().get("models", [])}
        missing = [m for m in required if m not in available]
        if missing:
            raise PreflightError(
                f"Ollama is running but these required models are not "
                f"pulled: {', '.join(missing)}. Run: "
                + " && ".join(f"`ollama pull {m}`" for m in missing)
            )

        logger.info(
            f"Preflight OK — Ollama up at {self.base_url}, "
            f"models available: {sorted(required)}"
        )

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.3,
        timeout: float = 180.0,
        json_mode: bool = False,
        num_predict: Optional[int] = None,
        num_ctx: Optional[int] = None,
    ) -> str:
        """
        Generate response using OpenAI-compatible chat completion format.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use (defaults to general model)
            temperature: Sampling temperature (lower = more deterministic)
            timeout: Request timeout in seconds
            json_mode: If True, use Ollama's constrained JSON decoding
                       (guarantees valid JSON output, ~2-3x faster)
            num_predict: Max tokens to generate (prevents runaway output)
            num_ctx: Context window size (smaller = faster KV cache)

        Returns:
            Generated text response
        """
        model = model or self.general_model

        options: Dict[str, Any] = {
            "temperature": temperature,
        }
        if num_predict is not None:
            options["num_predict"] = num_predict
        if num_ctx is not None:
            options["num_ctx"] = num_ctx

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": "30m",  # Keep model loaded in memory between calls
        }

        if json_mode:
            # Constrained decoding → valid JSON guaranteed
            payload["format"] = "json"

        try:
            sem = _get_semaphore()
            t0 = time.monotonic()
            logger.info(
                f"LLM request: model={model} json_mode={json_mode} "
                f"num_ctx={num_ctx} num_predict={num_predict}"
                f" (semaphore={'locked' if sem.locked() else 'free'})")
            async with sem:
                wait_time = time.monotonic() - t0
                # Always log wait time so we can distinguish "Ollama is
                # slow" from "our semaphore is holding us back".
                logger.info(
                    f"LLM semaphore acquired after {wait_time:.1f}s "
                    f"(model={model})"
                )
                t_send = time.monotonic()
                client = _get_client()
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                )
                inference_elapsed = time.monotonic() - t_send

            elapsed = time.monotonic() - t0
            if response.status_code == 200:
                data = response.json()
                content = data.get("message", {}).get("content", "")
                # Try to surface Ollama's own timings (eval_count /
                # eval_duration) so we can tell prefill from generation.
                eval_count = data.get("eval_count")
                eval_duration_s = (
                    (data.get("eval_duration") or 0) / 1e9
                )
                tok_per_s = (
                    eval_count / eval_duration_s
                    if eval_count and eval_duration_s
                    else None
                )
                logger.info(
                    f"LLM response: {len(content)} chars, "
                    f"inference={inference_elapsed:.1f}s, "
                    f"total={elapsed:.1f}s, "
                    f"tokens={eval_count}, "
                    f"speed={tok_per_s:.1f} t/s" if tok_per_s
                    else f"LLM response: {len(content)} chars, "
                         f"inference={inference_elapsed:.1f}s, "
                         f"total={elapsed:.1f}s (model={model})"
                )
                return content
            else:
                logger.error(
                    f"Ollama chat error ({elapsed:.1f}s): {response.text}")
                return ""
        except httpx.TimeoutException as e:
            elapsed = time.monotonic() - t0
            logger.error(
                f"LLM request TIMED OUT after {elapsed:.1f}s "
                f"(model={model}, timeout={timeout}s): {e}")
            return ""
        except Exception as e:
            logger.error(f"Error in chat completion (model={model}): {e}")
            return ""

    async def extract_resume_data(self, raw_text: str, pre_extracted: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Extract structured data from raw resume text using AI.

        Args:
            raw_text: Markdown-formatted text extracted from resume PDF/DOCX
            pre_extracted: Pre-extracted contact info (emails, phones, categorized links)

        Returns:
            Structured resume data in JSON format
        """
        logger.info(
            f"Starting AI extraction for resume ({len(raw_text)} chars)")

        # Build the user message with pre-extracted links appended
        user_content = f"Parse this resume:\n\n{raw_text}"

        if pre_extracted:
            user_content += "\n\n---\nPRE-EXTRACTED CONTACT INFO (use these directly, do NOT hallucinate URLs):\n"
            if pre_extracted.get("emails"):
                user_content += f"Emails: {', '.join(pre_extracted['emails'])}\n"
            if pre_extracted.get("phones"):
                user_content += f"Phones: {', '.join(pre_extracted['phones'])}\n"
            links = pre_extracted.get("links", {})
            for category, urls in links.items():
                user_content += f"{category.capitalize()}: {', '.join(urls)}\n"

        # Smart truncation — preserves both ends of the resume (header +
        # most recent experience), trims the middle. Better than naive
        # head-only truncation which silently drops the bottom roles.
        if len(user_content) > 8000:
            logger.info(
                f"Smart-truncating resume input from {len(user_content)} to 8000 chars")
            user_content = _smart_truncate(user_content, 8000)

        messages = [
            {"role": "system", "content": RESUME_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        response = await self.chat_completion(
            messages=messages,
            # Use fast (smaller) model for extraction
            model=self.fast_model,
            temperature=0.1,            # Low temp for consistent structured output
            # On CPU-only inference (Docker on Mac), each output token
            # costs ~100-500ms. The old (4096 predict, 8192 ctx) combo
            # could take 10+ minutes and timed out under Celery's limit.
            # 2048 output tokens is plenty for a resume JSON. 6144 ctx
            # comfortably fits our smart-truncated 8000-char input.
            timeout=1200.0,             # 20 min cap — well under Celery's 25 min soft limit
            json_mode=True,             # Constrained decoding → guaranteed valid JSON
            num_predict=2048,           # Cap output length (was 4096)
            num_ctx=6144,               # Smaller context = faster KV cache (was 8192)
        )

        logger.info(f"AI response received ({len(response)} chars)")

        # ── Empty response = hard failure (will trigger Celery retry) ─
        if not response or not response.strip():
            raise ResumeExtractionError(
                f"LLM returned empty response for resume extraction "
                f"({len(response)} chars). Likely timeout or Ollama contention."
            )

        # Parse JSON response
        try:
            # Clean response - remove markdown code blocks if present
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            # Find JSON object
            if "{" in cleaned:
                json_start = cleaned.index("{")
                json_end = cleaned.rindex("}") + 1
                json_str = cleaned[json_start:json_end]
                result = json.loads(json_str)
                normalized = self._normalize_resume_data(result)
                logger.info(
                    f"Successfully parsed AI response. Name: {normalized.get('name')}")
                return normalized
        except (ValueError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse AI resume extraction response: {e}")
            logger.error(f"Raw response: {response[:500]}...")

        # JSON parsing failed despite non-empty response — raise so task retries
        raise ResumeExtractionError(
            f"Failed to parse AI extraction response "
            f"({len(response)} chars): no valid JSON found"
        )

    @staticmethod
    def _normalize_resume_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise LLM output into a guaranteed flat schema.

        Handles both the new flat format AND the old sections-based format
        (in case the LLM still returns the old structure).
        """
        # ── Direct flat fields ────────────────────────────────────────
        out: Dict[str, Any] = {
            "name": data.get("name"),
            "email": data.get("email"),
            "phone": data.get("phone"),
            "linkedin": data.get("linkedin"),
            "github": data.get("github"),
            "portfolio": data.get("portfolio"),
            "location": data.get("location"),
            "summary": data.get("summary"),
            "skills": data.get("skills") or [],
            "experience": [],
            "education": [],
            "certifications": data.get("certifications") or [],
            "projects": data.get("projects") or [],
            "extracted_links": data.get("extracted_links") or {},
        }

        # ── Backfill from old "contact" object if present ─────────────
        contact = data.get("contact") or {}
        if not out["email"] and contact.get("email"):
            out["email"] = _first_str(contact["email"])
        if not out["phone"] and contact.get("phone"):
            out["phone"] = _first_str(contact["phone"])
        if not out["linkedin"] and contact.get("linkedin"):
            out["linkedin"] = _first_str(contact["linkedin"])
        if not out["github"] and contact.get("github"):
            out["github"] = _first_str(contact["github"])
        if not out["portfolio"] and contact.get("portfolio"):
            out["portfolio"] = _first_str(contact["portfolio"])
        if not out["location"] and contact.get("location"):
            out["location"] = _first_str(contact["location"])

        # ── Backfill from old "sections" array if present ─────────────
        for section in data.get("sections") or []:
            title = (section.get("title") or "").lower()
            content = section.get("content") or []
            items = section.get("items") or []

            if "summary" in title or "objective" in title:
                if not out["summary"] and content:
                    out["summary"] = content[0] if isinstance(
                        content[0], str) else str(content[0])

            elif "skill" in title:
                if not out["skills"] and content:
                    out["skills"] = content

            elif "experience" in title or "work" in title:
                if not out["experience"] and items:
                    for item in items:
                        out["experience"].append({
                            "title": item.get("role") or item.get("title"),
                            "company": item.get("company"),
                            "dates": item.get("duration") or item.get("dates"),
                            "description": item.get("bullets") or item.get("description") or [],
                        })

            elif "education" in title:
                if not out["education"] and items:
                    for item in items:
                        out["education"].append({
                            "degree": item.get("degree"),
                            "institution": item.get("institution"),
                            "year": item.get("duration") or item.get("year"),
                        })

            elif "certification" in title:
                if not out["certifications"] and content:
                    out["certifications"] = content

            elif "project" in title:
                if not out["projects"] and items:
                    out["projects"] = items

        # ── Normalize experience items ────────────────────────────────
        normalized_exp = []
        for exp in (data.get("experience") if data.get("experience") else out["experience"]):
            if isinstance(exp, dict):
                normalized_exp.append({
                    "title": exp.get("title") or exp.get("role"),
                    "company": exp.get("company"),
                    "dates": exp.get("dates") or exp.get("duration"),
                    "description": exp.get("description") or exp.get("bullets") or [],
                })
        if normalized_exp:
            out["experience"] = normalized_exp

        # ── Normalize education items ─────────────────────────────────
        normalized_edu = []
        for edu in (data.get("education") if data.get("education") else out["education"]):
            if isinstance(edu, dict):
                normalized_edu.append({
                    "degree": edu.get("degree"),
                    "institution": edu.get("institution"),
                    "year": edu.get("year") or edu.get("duration"),
                })
        if normalized_edu:
            out["education"] = normalized_edu

        # ── Flatten skills (split comma-separated strings) ────────────
        flat_skills: List[str] = []
        for s in out["skills"]:
            if isinstance(s, str):
                for part in s.split(","):
                    part = part.strip()
                    if part:
                        flat_skills.append(part)
            elif isinstance(s, list):
                flat_skills.extend(s)
        out["skills"] = flat_skills

        # ── Carry forward extra keys (extraction_error, raw_ai_response) ──
        for key in ("extraction_error", "raw_ai_response"):
            if key in data:
                out[key] = data[key]

        return out

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        """
        Generate text using Ollama.

        Args:
            prompt: The user prompt
            model: Model to use (defaults to general model)
            system_prompt: Optional system prompt
            temperature: Sampling temperature

        Returns:
            Generated text response
        """
        model = model or self.general_model

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
            "keep_alive": "30m",
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            sem = _get_semaphore()
            t0 = time.monotonic()
            async with sem:
                client = _get_client()
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=600.0,
                )
            elapsed = time.monotonic() - t0

            if response.status_code == 200:
                data = response.json()
                content = data.get("response", "")
                logger.info(
                    f"Generate response: {len(content)} chars in {elapsed:.1f}s")
                return content
            else:
                logger.error(f"Ollama generate error: {response.text}")
                return ""
        except Exception as e:
            logger.error(f"Error generating text: {e}")
            return ""

    # analyze_resume_for_ats removed — replaced by deterministic ATSEngine
    # (see app/services/ats_engine.py)

    async def optimize_resume_section(
        self,
        section_name: str,
        section_content: Any,
        job_description: str,
        instructions: Optional[str] = None,
    ) -> str:
        """
        Optimize a specific resume section.

        Args:
            section_name: Name of the section (summary, experience, etc.)
            section_content: Current content of the section
            job_description: Target job description
            instructions: Additional optimization instructions

        Returns:
            Optimized section content
        """
        system_prompt = f"""You are an expert resume writer specializing in ATS optimization.
        Your task is to optimize the {section_name} section of a resume.
        
        Guidelines:
        - Use strong action verbs
        - Include relevant keywords from the job description
        - Quantify achievements where possible
        - Keep it concise and impactful
        - Maintain truthfulness (don't fabricate information)
        """

        prompt = f"""
        JOB DESCRIPTION:
        {job_description}
        
        CURRENT {section_name.upper()}:
        {section_content}
        
        {instructions or ""}
        
        Please provide an optimized version of this {section_name} that better aligns with the job description.
        """

        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=self.general_model,
            temperature=0.5,
        )

    async def extract_job_requirements(
        self,
        job_description: str,
    ) -> Dict[str, Any]:
        """
        Extract structured data from a job description.

        Returns:
            {
                job_title, company_name, industry, seniority_level,
                required_skills[], preferred_skills[],
                responsibilities[], keywords[]
            }
        """
        # Smart-truncate long JDs — try to keep "Requirements", "Responsibilities",
        # and "Qualifications" sections in the tail, which are usually near the
        # bottom of long JDs and carry the most ATS-relevant terms.
        jd_input = job_description
        if len(jd_input) > 5000:
            logger.info(
                f"Smart-truncating JD input from {len(jd_input)} to 5000 chars")
            jd_input = _smart_truncate(
                jd_input, 5000,
                anchor_terms=[
                    "requirements", "qualifications", "responsibilities",
                    "must have", "required skills", "what you'll do",
                ],
            )

        messages = [
            {"role": "system", "content": JD_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Parse this job description:\n\n{jd_input}"},
        ]

        response = await self.chat_completion(
            messages=messages,
            model=self.fast_model,      # Fast model for extraction
            temperature=0.1,
            timeout=600.0,              # 10 min — JDs produce smaller output than resumes
            json_mode=True,             # Constrained JSON decoding
            num_predict=1024,           # JD output is small (skills + keywords list)
            num_ctx=4096,               # JDs are shorter, 4K context is fine
        )

        try:
            cleaned = response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            if "{" in cleaned:
                json_start = cleaned.index("{")
                json_end = cleaned.rindex("}") + 1
                result = json.loads(cleaned[json_start:json_end])
                return self._normalize_jd_data(result)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Could not parse job requirements response: {e}")

        return self._normalize_jd_data({})

    @staticmethod
    def _normalize_jd_data(data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure JD data always has every expected field."""
        return {
            "job_title": data.get("job_title"),
            "company_name": data.get("company_name"),
            "industry": data.get("industry"),
            "seniority_level": data.get("seniority_level"),
            "required_skills": data.get("required_skills") or [],
            "preferred_skills": data.get("preferred_skills") or [],
            "responsibilities": data.get("responsibilities") or [],
            "keywords": data.get("keywords") or [],
        }


# Singleton instance
ai_service = AIService()
