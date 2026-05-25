"""
Resume Optimization Service
============================
Takes original parsed resume JSON + parsed JD + ATS result
and produces a NEW optimized resume JSON — original is NEVER modified.

Approach:
- Skills reordering (matched-first) and gap insertion  → pure logic, no LLM
- Experience bullet enhancement with JD keywords        → LLM
- Summary tailoring for the target role                  → LLM
- Projects relevance sorting                             → pure logic
"""

from typing import Dict, Any, List, Optional, Tuple
from copy import deepcopy
import asyncio
import logging
import json
import re
import time

from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)

# ── Hallucination verifier ───────────────────────────────────────────
# A KNOWN_TECH_TERMS list of common technology terms used to detect
# tech that appears in a rewrite but not in the original bullet.
# We keep this conservative — only flag terms that are clearly tools
# / frameworks / platforms. Generic words like "API" or "database"
# are intentionally NOT in this list.
_KNOWN_TECH_TERMS = {
    # Languages
    "python", "java", "javascript", "typescript", "go", "golang", "rust",
    "c++", "c#", "ruby", "php", "kotlin", "swift", "scala", "r", "perl",
    # Frontend
    "react", "vue", "angular", "svelte", "nextjs", "next.js", "nuxt",
    "tailwind", "redux", "mui",
    # Backend
    "django", "flask", "fastapi", "express", "spring", "rails", "laravel",
    "nestjs", "gin", "fiber",
    # Data / ML
    "pandas", "numpy", "pytorch", "tensorflow", "sklearn", "scikit-learn",
    "keras", "spark", "hadoop", "airflow", "dbt", "snowflake", "databricks",
    # Databases
    "postgres", "postgresql", "mysql", "mongodb", "redis", "cassandra",
    "dynamodb", "elasticsearch", "sqlite", "clickhouse", "kafka", "rabbitmq",
    # Cloud / infra
    "aws", "azure", "gcp", "kubernetes", "k8s", "docker", "terraform",
    "ansible", "jenkins", "circleci", "github actions", "gitlab",
    "ec2", "s3", "lambda", "rds", "fargate", "eks", "cloudfront",
    # Misc
    "graphql", "grpc", "websocket", "websockets", "stripe", "twilio",
    "datadog", "sentry", "prometheus", "grafana", "splunk",
}

# Matches a number with optional %, k, K, M, B suffix, or "$" prefix.
# Catches "50K", "30%", "$1.2M", "200ms", "99.9%", "5x" etc.
# Captures the numeric value and an optional suffix separately so we
# can normalize "50K" → 50000 and recognize it as the same as "50,000".
_NUMBER_RE = re.compile(
    r"\$?(\d[\d,\.]*)\s*(%|k|m|b|x|ms|s|gb|mb|tb)?\b",
    re.IGNORECASE,
)

_SUFFIX_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
}


def _canonical_number(raw_digits: str, suffix: str) -> str:
    """
    Convert a raw number + suffix into a canonical string so that
    different formats of the same value compare equal:
        "50K", "50,000", "50000"  → "50000"
        "1.2M"                    → "1200000"
        "30%"                     → "30%"  (percent kept as-is)
        "200ms"                   → "200ms"
    """
    digits = raw_digits.replace(",", "")
    suffix = (suffix or "").lower()

    # K/M/B → multiply the digit value
    if suffix in _SUFFIX_MULTIPLIERS:
        try:
            val = float(digits) * _SUFFIX_MULTIPLIERS[suffix]
            return str(int(val))
        except ValueError:
            return digits + suffix

    # Percent, ms, gb etc. — keep digits + suffix verbatim (units matter)
    return digits + suffix


def _extract_numbers(text: str) -> set:
    """Pull all numeric tokens from text, normalized so format variations
    of the same value compare equal."""
    return {
        _canonical_number(m.group(1), m.group(2) or "")
        for m in _NUMBER_RE.finditer(text or "")
    }


def _extract_tech_mentions(text: str) -> set:
    """Find any KNOWN_TECH_TERMS that appear in text."""
    text_lower = (text or "").lower()
    found = set()
    for term in _KNOWN_TECH_TERMS:
        # Use word-boundary matching for short terms to avoid false positives
        # e.g. don't match "go" inside "google"
        if len(term) <= 3:
            if re.search(rf"\b{re.escape(term)}\b", text_lower):
                found.add(term)
        else:
            if term in text_lower:
                found.add(term)
    return found


def _bullet_has_hallucination(
    original: str, rewritten: str,
) -> Tuple[bool, List[str]]:
    """
    Return (is_hallucinated, reasons).

    A rewrite is considered hallucinated if it contains:
      • A specific number (50K, 30%, $1.2M, 99.9%) NOT in the original
      • A specific technology NOT in the original

    We deliberately do NOT flag added action verbs, adjectives, or
    rephrasing — the whole point of optimization is rewording.
    """
    reasons: List[str] = []

    new_numbers = _extract_numbers(rewritten) - _extract_numbers(original)
    if new_numbers:
        reasons.append(f"invented numbers: {sorted(new_numbers)}")

    new_tech = _extract_tech_mentions(rewritten) - _extract_tech_mentions(original)
    if new_tech:
        reasons.append(f"invented tech: {sorted(new_tech)}")

    return (len(reasons) > 0, reasons)

# ── LLM Prompts ──────────────────────────────────────────────────────

OPTIMIZE_SUMMARY_PROMPT = """You are an expert career coach. Rewrite a professional summary for a specific TARGET ROLE described in the user's ROLE-FIT BRIEF, WITHOUT fabricating credentials.

═══════════════════════════════════════════════════════════════════
HOW TO REASON (internal, do not output):
═══════════════════════════════════════════════════════════════════
STEP 1 — Read the ROLE-FIT BRIEF: identify the TARGET ROLE, the
         candidate's matched strengths, and what's missing.
STEP 2 — Read the ORIGINAL summary: extract the candidate's actual
         years of experience, domains, tech, and tone.
STEP 3 — Bridge the two: write a summary framed FOR the target role,
         using only facts present in the original (or visible in the
         brief's "WHAT THE CANDIDATE OFFERS" list). Surface MISSING
         keywords ONLY where the original truthfully supports them.

═══════════════════════════════════════════════════════════════════
HARD RULES:
═══════════════════════════════════════════════════════════════════
1. 3-5 sentences. No more.
2. Open with a line that naturally aligns the candidate to the
   TARGET ROLE (e.g. "Backend engineer with 6 years..." for a
   Backend Engineer role). Do NOT just paste the role title in.
3. Use ONLY skills/experience the original summary or brief supports.
   If unsure, leave it out.
4. NEVER invent years of experience. If the original says "3 years
   in Python", do NOT write "5+ years". If unspecified, omit numbers.
5. NEVER invent job titles, companies, or domains the candidate
   hasn't worked in. ("FinTech background" only if it's true.)
6. Weave 2-4 of the brief's MATCHED or truthfully-surfaceable MISSING
   keywords naturally — don't keyword-stuff.
7. Keep the candidate's voice (first-person vs third-person — match
   the original).
8. Return ONLY the rewritten summary text. No preamble, no markdown.

═══════════════════════════════════════════════════════════════════
EXAMPLE:
═══════════════════════════════════════════════════════════════════
ROLE-FIT BRIEF (excerpt):
  TARGET ROLE: Senior Backend Engineer (Senior) at Acme — FinTech
  CANDIDATE OFFERS — matched skills: Python, PostgreSQL, REST APIs
  ROLE REQUIRES — required: Python, AWS, Distributed Systems, REST APIs
  MISSING — required: AWS, Distributed Systems; keywords: microservices, CI/CD

ORIGINAL summary:
  "Software engineer with 6 years building backend services in Python
   and Go. Comfortable with cloud infrastructure and high-throughput
   systems. Passionate about clean architecture."

GOOD rewrite (aligns to role, surfaces 'distributed systems' truthfully,
omits AWS since original only says 'cloud infrastructure' generically):
  "Backend engineer with 6 years building production Python services
   and high-throughput distributed systems. Comfortable architecting
   cloud-native REST APIs and pragmatic about clean, testable design.
   Excited to bring depth in scalable backend engineering to a senior
   FinTech role."

BAD rewrite (invented years):
  "Senior backend engineer with 8+ years of Python and AWS expertise..."

BAD rewrite (invented tech — original says 'cloud' not 'AWS', no K8s):
  "Backend engineer with 6 years building Python services on AWS
   with Kubernetes orchestration..."   # AWS specific + K8s not in original"""

OPTIMIZE_EXPERIENCE_BATCH_PROMPT = """You are an expert resume writer. Rewrite the bullets for ALL roles below so they target the TARGET ROLE in the user's ROLE-FIT BRIEF, WITHOUT fabricating anything.

═══════════════════════════════════════════════════════════════════
HOW TO REASON (internal, do not output):
═══════════════════════════════════════════════════════════════════
For EACH role independently:
STEP 1 — Read the ROLE-FIT BRIEF: TARGET ROLE, ROLE REQUIRES, MISSING.
STEP 2 — For each ORIGINAL bullet, extract its facts:
           • action  (verb)        • tech   (tools/languages mentioned)
           • object  (what)         • metric (numbers if present)
           • scope   (team, audience) • outcome (business effect)
STEP 3 — Re-template using ONLY those facts, framed for the TARGET
         ROLE. Stronger verb. Keep original metrics. Surface MISSING
         keywords only if THAT bullet's facts truthfully support them.

═══════════════════════════════════════════════════════════════════
HARD RULES:
═══════════════════════════════════════════════════════════════════
1. OUTPUT MUST be a JSON array with EXACTLY the same length as the
   input ROLES array, in the same order. roles[i] -> output[i].
2. Each inner array MUST contain EXACTLY one rewritten bullet per
   original bullet in that role, same count and order.
3. Use ONLY technologies/tools from THAT bullet's original. Do NOT
   borrow tech from another role or invent any. Keyword matching is
   not lying — keyword INVENTION is.
4. Use ONLY metrics from THAT bullet's original. Never invent
   percentages, user counts, dollar amounts, or team sizes.
5. Each bullet: 15-30 words. Start with a strong action verb.
6. Frame each bullet for the TARGET ROLE.
7. Return ONLY a JSON array of arrays of strings.
   No prose, no markdown, no object wrapper, no role metadata.

═══════════════════════════════════════════════════════════════════
EXAMPLE:
═══════════════════════════════════════════════════════════════════
ROLE-FIT BRIEF (excerpt):
  TARGET ROLE: Senior Backend Engineer at Acme
  ROLE REQUIRES: Python, AWS, REST APIs, microservices
  MISSING: AWS; keywords: microservices, CI/CD

INPUT ROLES:
[
  {
    "title": "Software Engineer", "company": "PayCo", "dates": "2022-Now",
    "bullets": ["Worked on payment service in Python, handled around 50k requests/day"]
  },
  {
    "title": "Junior Engineer", "company": "Startup", "dates": "2020-2022",
    "bullets": ["Helped migrate monolith to services with my team", "Wrote tests"]
  }
]

GOOD OUTPUT (array of arrays, same lengths/order):
[
  ["Built Python REST API for payment microservice handling 50K daily requests"],
  ["Collaborated on migrating monolithic backend to microservices alongside engineering team", "Authored unit and integration tests covering critical service paths"]
]

BAD OUTPUT (invented AWS on role 1 — not in original bullet):
[
  ["Built Python REST API on AWS handling 50K daily requests..."],
  ["..."]
]

BAD OUTPUT (wrong shape — array of role objects instead of array of arrays):
[
  {"title": "...", "bullets": ["..."]},
  {"title": "...", "bullets": ["..."]}
]

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════════
Return ONLY:
[
  ["bullet 1 for role 1", "bullet 2 for role 1"],
  ["bullet 1 for role 2", "bullet 2 for role 2", "bullet 3 for role 2"]
]"""

OPTIMIZE_PROJECTS_PROMPT = """You are an expert resume writer. Rewrite project descriptions so they target the TARGET ROLE described in the user's ROLE-FIT BRIEF, WITHOUT fabricating anything.

═══════════════════════════════════════════════════════════════════
HOW TO REASON (internal, do not output):
═══════════════════════════════════════════════════════════════════
STEP 1 — Read the ROLE-FIT BRIEF: note TARGET ROLE, ROLE REQUIRES,
         and what's MISSING.
STEP 2 — For each ORIGINAL project, note its existing tech stack
         and what it actually does.
STEP 3 — Bridge: reframe each project's description and bullets to
         emphasize what's relevant to the TARGET ROLE, using only
         the existing tech/scope. Surface MISSING keywords only
         where the project's actual content truthfully supports them.

═══════════════════════════════════════════════════════════════════
HARD RULES:
═══════════════════════════════════════════════════════════════════
1. Project name, tech stack, and link are FIXED — copy verbatim.
2. Do NOT add technologies that aren't in the original tech list,
   even if the brief lists them as missing.
3. Do NOT invent metrics (users, latency, throughput, $ saved).
4. Use the same number of bullets as the original. Keep them
   concrete and concise (15-30 words each).
5. The "description" field should be a 1-2 sentence summary of
   what the project DOES, framed to read like work relevant to the
   TARGET ROLE — without changing what was actually built.
6. Return ONLY a JSON array. No prose, no markdown.

═══════════════════════════════════════════════════════════════════
EXAMPLE:
═══════════════════════════════════════════════════════════════════
JD wants: "React, TypeScript, REST APIs, real-time features"

ORIGINAL project:
{
  "name": "Habit Tracker",
  "description": "Web app to track daily habits",
  "technologies": ["React", "Node.js", "MongoDB"],
  "bullets": ["Made the frontend with charts", "Hooked up a backend"],
  "link": "github.com/user/habit-tracker"
}

GOOD rewrite:
{
  "name": "Habit Tracker",
  "description": "React web app for tracking daily habits with interactive charts and persistent storage",
  "technologies": ["React", "Node.js", "MongoDB"],
  "bullets": [
    "Built React frontend with interactive habit-streak charts and responsive layout",
    "Implemented Node.js REST API persisting user habit data to MongoDB"
  ],
  "link": "github.com/user/habit-tracker"
}

BAD rewrite (invented TypeScript + real-time):
{
  "technologies": ["React", "TypeScript", "Node.js", "MongoDB", "WebSockets"],
  "bullets": ["Built real-time React/TS app with WebSocket updates..."]
}

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════════
Return ONLY this JSON array, in the same order as the input projects:
[
  {
    "name": "original name",
    "description": "rewritten description",
    "technologies": ["original", "tech"],
    "bullets": ["rewritten bullet"],
    "link": "original link or null"
  }
]"""


class ResumeOptimizer:
    """
    Produces an optimized resume JSON from:
      - resume_data  (flat parsed resume)
      - jd_data      (parsed job description)
      - ats_result    (deterministic ATS scores + gaps)

    The original resume_data is NEVER mutated.
    """

    async def optimize(
        self,
        resume_data: Dict[str, Any],
        jd_data: Dict[str, Any],
        ats_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build a fully optimized resume JSON.

        Returns:
            {
                "name", "email", "phone", "linkedin", "github",
                "portfolio", "location",
                "summary": optimized,
                "skills": reordered + gap keywords appended,
                "experience": bullets rewritten,
                "education": unchanged,
                "certifications": unchanged,
                "projects": rewritten,
                "optimization_metadata": { ... }
            }
        """
        # Deep copy so original is untouched
        optimized = deepcopy(resume_data)

        # Skip the per-call health_check — the Celery task already ran
        # preflight() before getting here, so Ollama is known-up.

        # ── 1. Reorder skills (pure logic, NO fabrication) ───────────
        # Returns {skills: [...], gap_analysis: {...}}.
        # gap_analysis is kept SEPARATE — never injected into the resume.
        skills_result = self._optimize_skills(
            resume_data.get("skills", []),
            jd_data,
        )
        optimized["skills"] = skills_result["skills"]
        gap_analysis = skills_result["gap_analysis"]

        # ── Build the single ROLE-FIT BRIEF that every rewriter sees ─
        # This is the 3-step mental model the rewrites follow:
        #   1) What is the TARGET ROLE? (job title, seniority, company)
        #   2) What does the candidate ALREADY OFFER? (matched skills/kw)
        #   3) What does the role REQUIRE / what's MISSING?
        # Built once here so all three rewriters get the same context.
        brief = self._build_role_fit_brief(
            resume_data, jd_data, ats_result,
        )

        # ── 2-4. Run LLM optimizations IN PARALLEL ───────────────────
        # The three sections have no dependencies on each other (all
        # consume the same brief). With Ollama OLLAMA_NUM_PARALLEL>=2
        # and our semaphore matched, two requests run concurrently and
        # the third waits — wall-clock ≈ max(any 2) + the late starter,
        # vs sum(all 3) when sequential.
        t0 = time.monotonic()

        async def _timed(label: str, coro):
            stage_t0 = time.monotonic()
            logger.info(f"[opt] {label}: START")
            try:
                result = await coro
                logger.info(
                    f"[opt] {label}: DONE in "
                    f"{time.monotonic() - stage_t0:.1f}s"
                )
                return result
            except Exception as e:
                logger.error(
                    f"[opt] {label}: FAILED after "
                    f"{time.monotonic() - stage_t0:.1f}s — {e}"
                )
                raise

        async def _opt_summary() -> Optional[str]:
            if not resume_data.get("summary"):
                return None
            try:
                return await _timed(
                    "summary",
                    self._optimize_summary(resume_data["summary"], brief),
                )
            except Exception:
                return resume_data["summary"]

        async def _opt_experience() -> Optional[List[Dict]]:
            if not resume_data.get("experience"):
                return None
            try:
                return await _timed(
                    "experience",
                    self._optimize_experience(
                        resume_data["experience"], brief,
                    ),
                )
            except Exception:
                return resume_data["experience"]

        async def _opt_projects() -> Optional[List[Dict]]:
            if not resume_data.get("projects"):
                return None
            try:
                return await _timed(
                    "projects",
                    self._optimize_projects(resume_data["projects"], brief),
                )
            except Exception:
                return resume_data["projects"]

        summary_res, exp_res, proj_res = await asyncio.gather(
            _opt_summary(), _opt_experience(), _opt_projects(),
        )

        if summary_res is not None:
            optimized["summary"] = summary_res
        if exp_res is not None:
            optimized["experience"] = exp_res
        if proj_res is not None:
            optimized["projects"] = proj_res

        elapsed = time.monotonic() - t0
        logger.info(f"Parallel LLM optimization completed in {elapsed:.1f}s")

        # ── 5. Education & certifications stay unchanged ──────────────
        # (already deep-copied)

        # ── 6. Attach optimization metadata ───────────────────────────
        # gap_analysis lists skills the JD wants but the candidate doesn't
        # claim. Surface in the UI as suggestions — do NOT print into DOCX.
        optimized["optimization_metadata"] = {
            "target_job_title": jd_data.get("job_title"),
            "target_company": jd_data.get("company_name"),
            "ats_score_before": ats_result.get("overall_score"),
            "ai_enhanced": True,
            "gap_analysis": gap_analysis,
        }

        logger.info(
            f"Optimization complete — "
            f"skills (kept): {len(optimized['skills'])}, "
            f"gap (required missing): {len(gap_analysis['missing_required'])}"
        )
        return optimized

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _build_role_fit_brief(
        resume_data: Dict[str, Any],
        jd_data: Dict[str, Any],
        ats_result: Dict[str, Any],
        limit: int = 8,
    ) -> str:
        """
        Build the single ROLE-FIT BRIEF that all rewriters receive.

        This is the unified "lens" through which every LLM rewrite sees
        the optimization task. It encodes the three-step mental model:

          1. TARGET ROLE — who/what we're applying to (job title,
             seniority, company, domain)
          2. CANDIDATE OFFERS — what the candidate ALREADY has that
             aligns with this role (matched skills + matched keywords +
             dominant experience signals)
          3. ROLE REQUIRES — what the JD wants (required + preferred
             skills, key responsibilities, key keywords)
          4. MISSING — gaps to surface where the original content
             truthfully supports them (ATS gap analysis)

        Returns a multi-section text block ready to inline in a user
        message. Sections with no data are omitted so we don't waste
        context tokens.
        """
        sections: List[str] = []

        # ── 1. TARGET ROLE ──────────────────────────────────────────
        role_lines: List[str] = []
        title = jd_data.get("job_title") or "(unspecified)"
        seniority = jd_data.get("seniority_level")
        company = jd_data.get("company_name")
        industry = jd_data.get("industry")
        role_summary = title
        if seniority:
            role_summary = f"{title} ({seniority})"
        if company:
            role_summary += f" at {company}"
        if industry:
            role_summary += f" — {industry}"
        role_lines.append(f"Role: {role_summary}")
        sections.append("TARGET ROLE\n" + "\n".join(role_lines))

        # ── 2. CANDIDATE OFFERS (what the resume already has) ──────
        offers_lines: List[str] = []
        matched_skills = ats_result.get("matching_skills") or []
        matched_kw = ats_result.get("matching_keywords") or []
        if matched_skills:
            offers_lines.append(
                f"- Matched skills: {', '.join(matched_skills[:limit])}"
            )
        if matched_kw:
            offers_lines.append(
                f"- Matched keywords: {', '.join(matched_kw[:limit])}"
            )
        experience = resume_data.get("experience") or []
        if experience:
            recent = experience[0]
            recent_label = (
                f"{recent.get('title') or 'role'} at "
                f"{recent.get('company') or 'company'}"
            )
            offers_lines.append(
                f"- Experience: {len(experience)} role(s); most recent: "
                f"{recent_label}"
            )
        if offers_lines:
            sections.append(
                "WHAT THE CANDIDATE OFFERS (already truthful, lean on these)\n"
                + "\n".join(offers_lines)
            )

        # ── 3. ROLE REQUIRES (JD priorities) ────────────────────────
        req_lines: List[str] = []
        if jd_data.get("required_skills"):
            req_lines.append(
                f"- Required skills: {', '.join(jd_data['required_skills'][:limit])}"
            )
        if jd_data.get("preferred_skills"):
            req_lines.append(
                f"- Preferred skills: {', '.join(jd_data['preferred_skills'][:limit])}"
            )
        if jd_data.get("responsibilities"):
            req_lines.append("- Key responsibilities:")
            for r in jd_data["responsibilities"][:5]:
                req_lines.append(f"    • {r}")
        if jd_data.get("keywords"):
            req_lines.append(
                f"- Key keywords: {', '.join(jd_data['keywords'][:limit])}"
            )
        if req_lines:
            sections.append("WHAT THE ROLE REQUIRES\n" + "\n".join(req_lines))

        # ── 4. MISSING (gap analysis — surface where truthful) ─────
        missing_lines: List[str] = []
        missing_req = ats_result.get("missing_required_skills") or []
        missing_pref = ats_result.get("missing_preferred_skills") or []
        missing_kw = ats_result.get("missing_keywords") or []
        if missing_req:
            missing_lines.append(
                f"- Missing required skills: {', '.join(missing_req[:limit])}"
            )
        if missing_kw:
            req_lc = {r.lower() for r in missing_req}
            extra = [k for k in missing_kw if k.lower() not in req_lc]
            if extra:
                missing_lines.append(
                    f"- Missing JD keywords: {', '.join(extra[:limit])}"
                )
        if missing_pref:
            missing_lines.append(
                f"- Missing preferred skills: {', '.join(missing_pref[:limit])}"
            )
        if missing_lines:
            sections.append(
                "WHAT'S MISSING (surface ONLY where the original "
                "content truthfully supports it — NEVER invent)\n"
                + "\n".join(missing_lines)
            )

        # Join with a separator so the LLM visually parses each block
        sep = "\n" + ("─" * 60) + "\n"
        return sep.join(sections)

    @staticmethod
    def _optimize_skills(
        original_skills: List[str],
        jd_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Reorder the candidate's existing skills so JD-matched ones come first.

        IMPORTANT: We NEVER add skills the candidate didn't claim — that would
        fabricate credentials and break trust with recruiters. Missing skills
        are returned separately as a "gap_analysis" so the UI can present them
        as *suggestions for the candidate to manually confirm*, not as facts.

        Returns:
            {
              "skills": [str, ...]          # only the candidate's real skills, reordered
              "gap_analysis": {
                "missing_required": [...],  # required skills the candidate lacks
                "missing_preferred": [...], # preferred skills the candidate lacks
              }
            }
        """
        required = set(s.lower() for s in jd_data.get("required_skills", []))
        preferred = set(s.lower() for s in jd_data.get("preferred_skills", []))
        keywords = set(s.lower() for s in jd_data.get("keywords", []))
        jd_terms = required | preferred | keywords

        original_lower = {s.lower(): s for s in original_skills}

        # Partition into matched vs unmatched (preserve original casing)
        matched: List[str] = []
        unmatched: List[str] = []
        for skill in original_skills:
            if skill.lower() in jd_terms:
                matched.append(skill)
            else:
                unmatched.append(skill)

        # Reordered list — matched first, then the rest. No fabrication.
        reordered = matched + unmatched

        # Deduplicate while preserving order (case-insensitive)
        seen: set = set()
        deduped: List[str] = []
        for s in reordered:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        # Gap analysis — surfaced separately, NOT inserted into the resume
        missing_required = [
            s for s in jd_data.get("required_skills", [])
            if s.lower() not in original_lower
        ]
        missing_preferred = [
            s for s in jd_data.get("preferred_skills", [])
            if s.lower() not in original_lower
        ]

        return {
            "skills": deduped,
            "gap_analysis": {
                "missing_required": missing_required,
                "missing_preferred": missing_preferred,
            },
        }

    async def _optimize_summary(
        self,
        summary: str,
        brief: str,
    ) -> str:
        """Rewrite professional summary using the role-fit brief."""
        try:
            user_content = (
                f"ROLE-FIT BRIEF:\n{brief}\n\n"
                f"ORIGINAL SUMMARY:\n{summary}\n\n"
                "Rewrite the summary for the TARGET ROLE described in the "
                "brief. Open with a line that naturally aligns the candidate "
                "to that role. Surface MISSING keywords only where the "
                "original truthfully supports them."
            )
            messages = [
                {"role": "system", "content": OPTIMIZE_SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ]
            result = await ai_service.chat_completion(
                messages=messages,
                temperature=0.4,
                timeout=120.0,
                num_predict=1024,
                num_ctx=4096,
            )
            if result and len(result.strip()) > 20:
                rewritten = result.strip()
                # Hallucination guard — revert if the rewrite invented
                # numbers (e.g. "5+ years") or tech not in the original.
                hallucinated, reasons = _bullet_has_hallucination(
                    summary, rewritten,
                )
                if hallucinated:
                    logger.warning(
                        f"Summary hallucination guard tripped: {reasons}. "
                        f"Reverting to original summary."
                    )
                    return summary
                return rewritten
            logger.warning(
                "Summary optimization returned empty/short — keeping original")
            return summary
        except Exception as e:
            logger.error(f"Summary optimization failed: {e}")
            return summary

    async def _optimize_experience(
        self,
        experience: List[Dict],
        brief: str,
    ) -> List[Dict]:
        """
        Rewrite EVERY role's bullets in ONE LLM call.

        Why batched (was per-role): the previous per-role design re-sent
        the same ~1-2K-token brief N times and paid N× scheduling/HTTP
        overhead with no prefix-cache sharing. A 7B model handles a flat
        "array of arrays" response well, and the global hallucination
        guard in _verify_bullets keeps quality safe.

        Identity fields (title/company/dates) are never sent to the LLM
        as something it can change; they're stitched back from the
        original in the validation step.
        """
        if not experience:
            return experience

        t0 = time.monotonic()

        # Only what the LLM needs — no metadata it could mangle.
        roles_input = [
            {
                "title": r.get("title") or "(unspecified)",
                "company": r.get("company") or "(unspecified)",
                "dates": r.get("dates") or "(unspecified)",
                "bullets": r.get("description") or [],
            }
            for r in experience
        ]

        user_content = (
            f"ROLE-FIT BRIEF:\n{brief}\n\n"
            f"ROLES (rewrite ALL):\n{json.dumps(roles_input, indent=2)}\n\n"
            "Return a JSON array of arrays of strings — outer length "
            "= number of roles, inner length = number of bullets in that "
            "role, same order as input."
        )

        messages = [
            {"role": "system", "content": OPTIMIZE_EXPERIENCE_BATCH_PROMPT},
            {"role": "user", "content": user_content},
        ]

        # Budget: ~5 roles × ~5 bullets × ~40 tokens = ~1000 tokens out,
        # plus JSON array overhead. 2048 covers most real resumes.
        # num_ctx bumped a bit because the input now carries ALL roles.
        result = await ai_service.chat_completion(
            messages=messages,
            temperature=0.4,
            timeout=180.0,
            json_mode=True,
            num_predict=2048,
            num_ctx=6144,
        )

        parsed = self._parse_json_array(result)

        # Normalize parsed → List[List[str]]. Defensive: small models
        # sometimes return a flat list, or wrap each role as a dict.
        rewritten_per_role: List[List[str]] = []
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, list):
                    rewritten_per_role.append(
                        [str(b) for b in entry if b]
                    )
                elif isinstance(entry, dict):
                    bullets = (
                        entry.get("bullets")
                        or entry.get("description")
                        or entry.get("items")
                        or []
                    )
                    if isinstance(bullets, list):
                        rewritten_per_role.append(
                            [str(b) for b in bullets if b]
                        )
                    else:
                        rewritten_per_role.append([])
                else:
                    rewritten_per_role.append([])

        if len(rewritten_per_role) != len(experience):
            logger.warning(
                f"Experience length mismatch: input={len(experience)} "
                f"roles, LLM returned={len(rewritten_per_role)} arrays. "
                f"Missing roles will fall back to originals."
            )

        # Pair each role's rewritten bullets with its originals; revert
        # any hallucinated or missing entries to the original bullet.
        validated: List[Dict] = []
        total_kept = 0
        total_reverted = 0

        for i, original in enumerate(experience):
            original_bullets = original.get("description") or []
            role_label = (
                f"{original.get('title') or 'role'} @ "
                f"{original.get('company') or 'company'}"
            )
            rewritten_bullets = (
                rewritten_per_role[i]
                if i < len(rewritten_per_role)
                else []
            )

            safe_bullets = self._verify_bullets(
                original_bullets, rewritten_bullets, role_label=role_label,
            )
            for orig, new in zip(original_bullets, safe_bullets):
                if new != orig:
                    total_kept += 1
                else:
                    total_reverted += 1

            validated.append({
                # Identity fields ALWAYS come from the original
                "title": original.get("title"),
                "company": original.get("company"),
                "dates": original.get("dates"),
                "description": safe_bullets,
            })

        logger.info(
            f"Experience batch rewrite — {len(experience)} roles in 1 call, "
            f"{time.monotonic() - t0:.1f}s; bullets kept: {total_kept}, "
            f"reverted (empty or hallucinated): {total_reverted}"
        )
        return validated

    async def _optimize_projects(
        self,
        projects: List[Dict],
        brief: str,
    ) -> List[Dict]:
        """Rewrite project descriptions using the role-fit brief."""
        try:
            user_content = (
                f"ROLE-FIT BRIEF:\n{brief}\n\n"
                f"PROJECTS:\n{json.dumps(projects, indent=2)}\n\n"
                "Rewrite each project so its description and bullets are "
                "framed for the TARGET ROLE from the brief. Keep names, "
                "tech, and links unchanged."
            )
            messages = [
                {"role": "system", "content": OPTIMIZE_PROJECTS_PROMPT},
                {"role": "user", "content": user_content},
            ]
            # Typical resumes have 1–3 projects @ ~250 tokens of rewrite
            # each. 1500 leaves plenty of headroom while capping the worst
            # case. num_ctx 4096 fits brief + projects + prompt comfortably.
            result = await ai_service.chat_completion(
                messages=messages,
                temperature=0.4,
                timeout=180.0,
                json_mode=True,
                num_predict=1500,
                num_ctx=4096,
            )
            parsed = self._parse_json_array(result)
            if parsed and len(parsed) > 0:
                # Same length-safety contract as _optimize_experience:
                # iterate over the ORIGINAL projects list so we never drop
                # or invent project entries based on what the LLM returned.
                if len(parsed) != len(projects):
                    logger.warning(
                        f"Projects length mismatch: original={len(projects)}, "
                        f"LLM returned={len(parsed)}. Pairing positionally and "
                        f"falling back to original content for unmatched entries."
                    )

                validated = []
                for i, original in enumerate(projects):
                    original_bullets = original.get("bullets") or []
                    orig_desc = original.get("description") or ""
                    entry = parsed[i] if i < len(parsed) else None

                    # Type guard — same defensive handling as experience.
                    # Non-dict entries fall back to original (no rewrite).
                    if isinstance(entry, dict):
                        rewritten_bullets = entry.get("bullets") or []
                        new_desc = entry.get("description") or orig_desc
                    elif entry is None:
                        rewritten_bullets = []
                        new_desc = orig_desc
                    else:
                        logger.warning(
                            f"Project entry #{i} is not a dict "
                            f"(type={type(entry).__name__}) — keeping original"
                        )
                        rewritten_bullets = []
                        new_desc = orig_desc

                    # Verify project bullets too — same hallucination guard
                    safe_bullets = self._verify_bullets(
                        original_bullets, rewritten_bullets,
                        role_label=f"project {original.get('name')}",
                    )

                    # Verify description (single string) — wrap as 1-element list
                    safe_desc_list = self._verify_bullets(
                        [orig_desc], [new_desc],
                        role_label=f"project {original.get('name')} description",
                    )

                    validated.append({
                        # Identity fields ALWAYS from the original
                        "name": original.get("name"),
                        "technologies": original.get("technologies", []),
                        "link": original.get("link"),
                        # Verified content
                        "description": safe_desc_list[0] if safe_desc_list else orig_desc,
                        "bullets": safe_bullets,
                    })
                return validated
            logger.warning(
                "Projects optimization parse failed — keeping original")
            return projects
        except Exception as e:
            logger.error(f"Projects optimization failed: {e}")
            return projects

    @staticmethod
    def _verify_bullets(
        original_bullets: List[str],
        rewritten_bullets: List[str],
        role_label: str = "",
    ) -> List[str]:
        """
        Pair each rewritten bullet with its original and revert any rewrite
        that introduces invented numbers or invented technologies.

        This is a SAFETY NET — even if a prompt instruction is ignored,
        we never ship a fabricated claim. The original bullet is kept
        instead.

        Returns a list the same length as `original_bullets`. If the
        rewrite list is shorter, missing entries fall back to original.
        """
        safe: List[str] = []
        for i, orig in enumerate(original_bullets):
            orig_str = str(orig) if orig else ""
            new_str = (
                str(rewritten_bullets[i])
                if i < len(rewritten_bullets) and rewritten_bullets[i]
                else ""
            )
            if not new_str:
                safe.append(orig_str)
                continue

            hallucinated, reasons = _bullet_has_hallucination(orig_str, new_str)
            if hallucinated:
                logger.warning(
                    f"Hallucination guard tripped for {role_label or 'bullet'} "
                    f"#{i}: {reasons}. Reverting to original."
                )
                safe.append(orig_str)
            else:
                safe.append(new_str)
        return safe

    @staticmethod
    def _parse_json_array(text: str) -> Optional[List[Dict]]:
        """
        Parse a JSON array from potentially messy LLM output.

        Small LLMs (qwen2.5:7b on JSON mode) sometimes return:
          1) A proper array: [{...}, {...}]
          2) A single object: {...}                 → wrap into [obj]
          3) Concatenated objects: {...}{...}        → split, wrap into [obj, obj]
          4) An array wrapped in a key: {"items":[...]} or {"data":[...]}
          5) Markdown fences ```json ... ```         → strip
          6) Trailing prose/explanation after JSON   → trim to last valid bracket

        We try each strategy in order and return the first that parses.
        On failure we log the FIRST 400 chars of the raw output so the
        next debug session doesn't require digging through Ollama.
        """
        if not text:
            return None
        cleaned = text.strip()

        # Strategy 0 — strip markdown fences
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Strategy 1 — full array
        if "[" in cleaned and "]" in cleaned:
            try:
                start = cleaned.index("[")
                end = cleaned.rindex("]") + 1
                parsed = json.loads(cleaned[start:end])
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, json.JSONDecodeError):
                pass

        # Strategy 2 — single object → wrap as 1-element array
        if cleaned.startswith("{"):
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict):
                    # 2a — { "items": [...] } / { "data": [...] } / { "result": [...] }
                    for key in ("items", "data", "result", "results", "entries"):
                        if isinstance(obj.get(key), list):
                            logger.info(
                                f"_parse_json_array: unwrapped from key '{key}'"
                            )
                            return obj[key]
                    # 2b — a single role / project object
                    logger.info("_parse_json_array: wrapped single object as array")
                    return [obj]
            except (ValueError, json.JSONDecodeError):
                pass

        # Strategy 3 — concatenated objects {...}{...}{...} (no array brackets)
        # Use a brace-balanced scan to pull out each top-level object.
        if cleaned.count("{") >= 1 and "[" not in cleaned:
            objs: List[Dict] = []
            depth = 0
            buf: List[str] = []
            in_str = False
            esc = False
            for ch in cleaned:
                if esc:
                    buf.append(ch)
                    esc = False
                    continue
                if ch == "\\":
                    buf.append(ch)
                    esc = True
                    continue
                if ch == '"':
                    in_str = not in_str
                if not in_str:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                buf.append(ch)
                if depth == 0 and buf and "{" in "".join(buf):
                    candidate = "".join(buf).strip()
                    if candidate.startswith("{") and candidate.endswith("}"):
                        try:
                            objs.append(json.loads(candidate))
                        except json.JSONDecodeError:
                            pass
                        buf = []
            if objs:
                logger.info(
                    f"_parse_json_array: rebuilt {len(objs)} concatenated objects"
                )
                return objs

        # All strategies failed — log a snippet to make future debugging easy
        snippet = text[:400].replace("\n", "\\n")
        logger.warning(
            f"_parse_json_array: could not parse LLM output. "
            f"len={len(text)}, head=<<{snippet}>>"
        )
        return None


# Singleton
resume_optimizer = ResumeOptimizer()
