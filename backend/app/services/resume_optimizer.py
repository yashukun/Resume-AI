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

from typing import Dict, Any, List, Optional
from copy import deepcopy
import asyncio
import logging
import json
import time

from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)

# ── LLM Prompts ──────────────────────────────────────────────────────

OPTIMIZE_SUMMARY_PROMPT = """You are an expert career coach. Rewrite the candidate's professional summary to target the given job description.

RULES:
- Keep it 3-5 sentences MAX
- Start with the candidate's strongest relevant qualification
- Weave in the most important keywords from the JD naturally
- Do NOT fabricate years of experience or skills the candidate doesn't have
- Maintain the candidate's voice / tone
- Return ONLY the rewritten summary text, nothing else"""

OPTIMIZE_EXPERIENCE_PROMPT = """You are an expert resume writer. Rewrite the experience bullet points to better target the job description while staying truthful.

RULES:
- Preserve the SAME facts — company, role, dates are UNCHANGED
- Rewrite bullet points to highlight relevance to the job
- Start each bullet with a strong action verb
- Include metrics / numbers where the original has them (do NOT invent metrics)
- Weave relevant keywords from the JD naturally into the bullets
- Each bullet should be 1 line, max ~20 words
- Keep the SAME number of bullets (do not add or remove)
- Return ONLY valid JSON array of objects:
[
  {
    "title": "original title",
    "company": "original company",
    "dates": "original dates",
    "description": ["bullet 1", "bullet 2"]
  }
]
Return ONLY the JSON array, no markdown, no extra text."""

OPTIMIZE_PROJECTS_PROMPT = """You are an expert resume writer. Rewrite the project descriptions to better target the job description while staying truthful.

RULES:
- Preserve the SAME project names and tech stacks
- Rewrite descriptions/bullets to highlight relevance to the JD
- Weave relevant keywords naturally
- Return ONLY valid JSON array of objects:
[
  {
    "name": "original name",
    "description": "rewritten description",
    "technologies": ["original", "tech"],
    "bullets": ["rewritten bullet"],
    "link": "original link or null"
  }
]
Return ONLY the JSON array, no markdown, no extra text."""


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

        # Collect JD context for LLM calls
        jd_text = self._build_jd_context(jd_data)

        # Check LLM availability once
        ai_available = await ai_service.health_check()

        # ── 1. Reorder & enhance skills (pure logic) ─────────────────
        optimized["skills"] = self._optimize_skills(
            resume_data.get("skills", []),
            jd_data,
            ats_result,
        )

        # ── 2-4. Run LLM optimizations IN PARALLEL ───────────────────
        # (summary + experience + projects concurrently → ~3x faster)
        if ai_available:
            t0 = time.monotonic()
            optimized_count = 0

            # Run LLM calls SEQUENTIALLY — Ollama processes one at a time,
            # so parallel requests just queue up and risk timeouts.
            if resume_data.get("summary"):
                try:
                    optimized["summary"] = await self._optimize_summary(
                        resume_data["summary"], jd_text)
                    optimized_count += 1
                    logger.info("Summary optimized")
                except Exception as e:
                    logger.error(f"Summary optimization failed: {e}")

            if resume_data.get("experience"):
                try:
                    optimized["experience"] = await self._optimize_experience(
                        resume_data["experience"], jd_text)
                    optimized_count += 1
                    logger.info("Experience optimized")
                except Exception as e:
                    logger.error(f"Experience optimization failed: {e}")

            if resume_data.get("projects"):
                try:
                    optimized["projects"] = await self._optimize_projects(
                        resume_data["projects"], jd_text)
                    optimized_count += 1
                    logger.info("Projects optimized")
                except Exception as e:
                    logger.error(f"Projects optimization failed: {e}")

            elapsed = time.monotonic() - t0
            logger.info(
                f"Sequential LLM optimization: {optimized_count} sections in {elapsed:.1f}s")

        # ── 5. Education & certifications stay unchanged ──────────────
        # (already deep-copied)

        # ── 6. Attach optimization metadata ───────────────────────────
        optimized["optimization_metadata"] = {
            "target_job_title": jd_data.get("job_title"),
            "target_company": jd_data.get("company_name"),
            "ats_score_before": ats_result.get("overall_score"),
            "skills_added": list(
                set(optimized["skills"]) - set(resume_data.get("skills", []))
            ),
            "ai_enhanced": ai_available,
        }

        logger.info(
            f"Optimization complete — "
            f"skills: {len(resume_data.get('skills', []))} → {len(optimized['skills'])}, "
            f"ai_enhanced={ai_available}"
        )
        return optimized

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _build_jd_context(jd_data: Dict[str, Any]) -> str:
        """Build a concise JD summary for LLM prompts."""
        parts = []
        if jd_data.get("job_title"):
            parts.append(f"Job Title: {jd_data['job_title']}")
        if jd_data.get("company_name"):
            parts.append(f"Company: {jd_data['company_name']}")
        if jd_data.get("required_skills"):
            parts.append(
                f"Required Skills: {', '.join(jd_data['required_skills'])}")
        if jd_data.get("preferred_skills"):
            parts.append(
                f"Preferred Skills: {', '.join(jd_data['preferred_skills'])}")
        if jd_data.get("responsibilities"):
            parts.append("Responsibilities:\n" + "\n".join(
                f"- {r}" for r in jd_data["responsibilities"]
            ))
        if jd_data.get("keywords"):
            parts.append(f"Keywords: {', '.join(jd_data['keywords'])}")
        return "\n".join(parts)

    @staticmethod
    def _optimize_skills(
        original_skills: List[str],
        jd_data: Dict[str, Any],
        ats_result: Dict[str, Any],
    ) -> List[str]:
        """
        Reorder skills so JD-matched ones come first,
        then append missing required/preferred skills the candidate
        should consider adding.
        """
        required = set(s.lower() for s in jd_data.get("required_skills", []))
        preferred = set(s.lower() for s in jd_data.get("preferred_skills", []))
        keywords = set(s.lower() for s in jd_data.get("keywords", []))
        jd_terms = required | preferred | keywords

        original_lower = {s.lower(): s for s in original_skills}

        # Partition into matched vs unmatched (preserve original casing)
        matched = []
        unmatched = []
        for skill in original_skills:
            if skill.lower() in jd_terms:
                matched.append(skill)
            else:
                unmatched.append(skill)

        # Identify missing skills from JD that candidate might add
        # Only add required_skills that are genuinely missing
        missing_required = [
            s for s in jd_data.get("required_skills", [])
            if s.lower() not in original_lower
        ]
        missing_preferred = [
            s for s in jd_data.get("preferred_skills", [])
            if s.lower() not in original_lower
        ]

        # Build final list: matched first → unmatched → missing required → missing preferred
        result = matched + unmatched + missing_required + missing_preferred

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for s in result:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(s)

        return deduped

    async def _optimize_summary(self, summary: str, jd_text: str) -> str:
        """Rewrite professional summary with LLM."""
        try:
            messages = [
                {"role": "system", "content": OPTIMIZE_SUMMARY_PROMPT},
                {"role": "user", "content": (
                    f"JOB DESCRIPTION:\n{jd_text}\n\n"
                    f"ORIGINAL SUMMARY:\n{summary}\n\n"
                    f"Rewrite the summary for this job:"
                )},
            ]
            result = await ai_service.chat_completion(
                messages=messages,
                temperature=0.4,
                timeout=120.0,
                num_predict=1024,
                num_ctx=4096,
            )
            if result and len(result.strip()) > 20:
                return result.strip()
            logger.warning(
                "Summary optimization returned empty/short — keeping original")
            return summary
        except Exception as e:
            logger.error(f"Summary optimization failed: {e}")
            return summary

    async def _optimize_experience(
        self, experience: List[Dict], jd_text: str
    ) -> List[Dict]:
        """Rewrite experience bullets with LLM."""
        try:
            messages = [
                {"role": "system", "content": OPTIMIZE_EXPERIENCE_PROMPT},
                {"role": "user", "content": (
                    f"JOB DESCRIPTION:\n{jd_text}\n\n"
                    f"EXPERIENCE:\n{json.dumps(experience, indent=2)}\n\n"
                    f"Rewrite the experience to target this job:"
                )},
            ]
            result = await ai_service.chat_completion(
                messages=messages,
                temperature=0.4,
                timeout=180.0,
                json_mode=True,
                num_predict=4096,
                num_ctx=8192,
            )
            parsed = self._parse_json_array(result)
            if parsed and len(parsed) > 0:
                # Validate structure — each entry needs title, company, dates, description
                validated = []
                for i, entry in enumerate(parsed):
                    original = experience[i] if i < len(experience) else {}
                    validated.append({
                        "title": entry.get("title") or original.get("title"),
                        "company": entry.get("company") or original.get("company"),
                        "dates": entry.get("dates") or original.get("dates"),
                        "description": entry.get("description") or original.get("description", []),
                    })
                return validated
            logger.warning(
                "Experience optimization parse failed — keeping original")
            return experience
        except Exception as e:
            logger.error(f"Experience optimization failed: {e}")
            return experience

    async def _optimize_projects(
        self, projects: List[Dict], jd_text: str
    ) -> List[Dict]:
        """Rewrite project descriptions with LLM."""
        try:
            messages = [
                {"role": "system", "content": OPTIMIZE_PROJECTS_PROMPT},
                {"role": "user", "content": (
                    f"JOB DESCRIPTION:\n{jd_text}\n\n"
                    f"PROJECTS:\n{json.dumps(projects, indent=2)}\n\n"
                    f"Rewrite the projects to target this job:"
                )},
            ]
            result = await ai_service.chat_completion(
                messages=messages,
                temperature=0.4,
                timeout=180.0,
                json_mode=True,
                num_predict=4096,
                num_ctx=8192,
            )
            parsed = self._parse_json_array(result)
            if parsed and len(parsed) > 0:
                validated = []
                for i, entry in enumerate(parsed):
                    original = projects[i] if i < len(projects) else {}
                    validated.append({
                        "name": entry.get("name") or original.get("name"),
                        "description": entry.get("description") or original.get("description"),
                        "technologies": entry.get("technologies") or original.get("technologies", []),
                        "bullets": entry.get("bullets") or original.get("bullets", []),
                        "link": entry.get("link") or original.get("link"),
                    })
                return validated
            logger.warning(
                "Projects optimization parse failed — keeping original")
            return projects
        except Exception as e:
            logger.error(f"Projects optimization failed: {e}")
            return projects

    @staticmethod
    def _parse_json_array(text: str) -> Optional[List[Dict]]:
        """Parse a JSON array from potentially messy LLM output."""
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        # Find JSON array
        try:
            if "[" in cleaned:
                start = cleaned.index("[")
                end = cleaned.rindex("]") + 1
                return json.loads(cleaned[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to parse JSON array from LLM: {e}")
        return None


# Singleton
resume_optimizer = ResumeOptimizer()
