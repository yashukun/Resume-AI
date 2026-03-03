"""
Deterministic ATS (Applicant Tracking System) Scoring Engine.

Scores a parsed resume against a parsed job description using pure
keyword / skill matching — no LLM calls required.

Score breakdown (0-100):
  • Keyword match   40 pts — JD keywords found in resume full text
  • Skills match    25 pts — Required + preferred skills overlap
  • Experience      15 pts — Title / responsibility alignment
  • Sections        10 pts — Completeness (summary, skills, experience, education)
  • Education       10 pts — Degree presence
"""

from __future__ import annotations

import re
import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────

_STOP_WORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "this", "that",
    "these", "those", "i", "we", "you", "he", "she", "it", "they", "them",
    "my", "our", "your", "his", "her", "its", "their", "what", "which",
    "who", "whom", "how", "when", "where", "why", "not", "no", "nor",
    "as", "if", "so", "than", "too", "very", "just", "about", "up", "out",
    "from", "into", "over", "after", "before", "between", "under", "above",
    "such", "each", "every", "all", "any", "both", "few", "more", "most",
    "other", "some", "also", "etc", "e.g", "i.e", "vs",
}

_WORD_RE = re.compile(r"[a-zA-Z0-9#+.\-/]+")


def _tokenize(text: str) -> List[str]:
    """Lowercase tokenize, keeping tech-relevant chars like #, +, ."""
    return [w.lower().strip(".-/") for w in _WORD_RE.findall(text) if len(w) > 1]


def _to_lower_set(items: List[str]) -> Set[str]:
    return {s.lower().strip() for s in items if s and s.strip()}


def _fuzzy_in(needle: str, haystack: str, threshold: float = 0.85) -> bool:
    """Check if *needle* appears in *haystack* (exact substring first, then fuzzy)."""
    needle_l = needle.lower()
    haystack_l = haystack.lower()

    # 1) Exact substring
    if needle_l in haystack_l:
        return True

    # 2) Word-level containment (e.g. "react" in "react.js" or "reactjs")
    needle_no_punct = re.sub(r"[^a-z0-9]", "", needle_l)
    if len(needle_no_punct) >= 3 and needle_no_punct in re.sub(r"[^a-z0-9]", "", haystack_l):
        return True

    # 3) Token-level fuzzy — check against each haystack token window
    h_tokens = _tokenize(haystack)
    n_len = len(needle_l.split())
    for i in range(len(h_tokens) - n_len + 1):
        window = " ".join(h_tokens[i: i + n_len])
        if SequenceMatcher(None, needle_l, window).ratio() >= threshold:
            return True

    return False


def _build_resume_text(resume: Dict[str, Any]) -> str:
    """Concatenate all resume text into one searchable string."""
    parts: List[str] = []

    for field in ("name", "summary", "location"):
        if resume.get(field):
            parts.append(str(resume[field]))

    for skill in resume.get("skills") or []:
        parts.append(str(skill))

    for exp in resume.get("experience") or []:
        parts.append(exp.get("title") or "")
        parts.append(exp.get("company") or "")
        for bullet in exp.get("description") or []:
            parts.append(str(bullet))

    for edu in resume.get("education") or []:
        parts.append(edu.get("degree") or "")
        parts.append(edu.get("institution") or "")

    for cert in resume.get("certifications") or []:
        parts.append(str(cert))

    for proj in resume.get("projects") or []:
        parts.append(proj.get("name") or "")
        parts.append(proj.get("description") or "")
        for b in proj.get("bullets") or []:
            parts.append(str(b))
        for t in proj.get("technologies") or []:
            parts.append(str(t))

    return " ".join(parts)


# ── Main engine ──────────────────────────────────────────────────────────

class ATSEngine:
    """
    Deterministic ATS scorer.

    Usage:
        engine = ATSEngine()
        result = engine.score(resume_data, jd_data)
        # result is a dict with overall_score, breakdown, matched/missing keywords, tips
    """

    # Weight for each scoring dimension (must sum to 100)
    W_KEYWORDS = 40
    W_SKILLS = 25
    W_EXPERIENCE = 15
    W_SECTIONS = 10
    W_EDUCATION = 10

    def score(
        self,
        resume: Dict[str, Any],
        jd: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Score *resume* against *jd* and return a detailed breakdown.

        Args:
            resume: Flat resume dict (name, skills[], experience[], …)
            jd:     Parsed JD dict (keywords[], required_skills[], …)

        Returns:
            {
              overall_score: int,
              breakdown: {keyword_match: {score, max, details}, …},
              matching_keywords: [...],
              missing_keywords: [...],
              matching_skills: [...],
              missing_required_skills: [...],
              missing_preferred_skills: [...],
              tips: [str, …],
            }
        """
        resume_text = _build_resume_text(resume)
        resume_skills = _to_lower_set(resume.get("skills") or [])

        # ── 1. Keyword match (40 pts) ────────────────────────────────
        jd_keywords = jd.get("keywords") or []
        kw_matched, kw_missing = self._match_list_against_text(
            jd_keywords, resume_text)
        kw_score = round(self.W_KEYWORDS * len(kw_matched) /
                         max(len(jd_keywords), 1))

        # ── 2. Skills match (25 pts) ─────────────────────────────────
        required = _to_lower_set(jd.get("required_skills") or [])
        preferred = _to_lower_set(jd.get("preferred_skills") or [])

        req_matched, req_missing = self._match_skills(
            required, resume_skills, resume_text)
        pref_matched, pref_missing = self._match_skills(
            preferred, resume_skills, resume_text)

        # Required skills worth 70 % of skills weight, preferred 30 %
        req_ratio = len(req_matched) / max(len(required), 1)
        pref_ratio = len(pref_matched) / max(len(preferred), 1)
        skills_score = round(
            self.W_SKILLS * (0.7 * req_ratio + 0.3 * pref_ratio))

        # ── 3. Experience relevance (15 pts) ──────────────────────────
        exp_score, exp_details = self._score_experience(
            resume, jd, resume_text)

        # ── 4. Section completeness (10 pts) ─────────────────────────
        section_score, section_details = self._score_sections(resume)

        # ── 5. Education (10 pts) ─────────────────────────────────────
        edu_score, edu_details = self._score_education(resume)

        # ── Overall ──────────────────────────────────────────────────
        overall = kw_score + skills_score + exp_score + section_score + edu_score
        overall = min(overall, 100)

        # ── Tips ─────────────────────────────────────────────────────
        tips = self._generate_tips(
            kw_missing, req_missing, pref_missing,
            section_details, resume, jd,
        )

        result = {
            "overall_score": overall,
            "breakdown": {
                "keyword_match": {
                    "score": kw_score,
                    "max": self.W_KEYWORDS,
                    "matched": len(kw_matched),
                    "total": len(jd_keywords),
                },
                "skills_match": {
                    "score": skills_score,
                    "max": self.W_SKILLS,
                    "required_matched": len(req_matched),
                    "required_total": len(required),
                    "preferred_matched": len(pref_matched),
                    "preferred_total": len(preferred),
                },
                "experience_relevance": {
                    "score": exp_score,
                    "max": self.W_EXPERIENCE,
                    "details": exp_details,
                },
                "section_completeness": {
                    "score": section_score,
                    "max": self.W_SECTIONS,
                    "details": section_details,
                },
                "education": {
                    "score": edu_score,
                    "max": self.W_EDUCATION,
                    "details": edu_details,
                },
            },
            "matching_keywords": sorted(kw_matched),
            "missing_keywords": sorted(kw_missing),
            "matching_skills": sorted(req_matched | pref_matched),
            "missing_required_skills": sorted(req_missing),
            "missing_preferred_skills": sorted(pref_missing),
            "tips": tips,
        }

        logger.info(
            f"ATS score: {overall}/100  "
            f"(kw={kw_score}, skills={skills_score}, exp={exp_score}, "
            f"sec={section_score}, edu={edu_score})"
        )
        return result

    # ── Private scoring helpers ──────────────────────────────────────

    @staticmethod
    def _match_list_against_text(
        items: List[str], text: str,
    ) -> Tuple[Set[str], Set[str]]:
        """Return (matched, missing) sets for a list of keywords against full text."""
        matched: Set[str] = set()
        missing: Set[str] = set()
        for item in items:
            item_clean = item.strip()
            if not item_clean:
                continue
            if _fuzzy_in(item_clean, text):
                matched.add(item_clean.lower())
            else:
                missing.add(item_clean.lower())
        return matched, missing

    @staticmethod
    def _match_skills(
        required: Set[str],
        resume_skills: Set[str],
        resume_text: str,
    ) -> Tuple[Set[str], Set[str]]:
        """Match required/preferred skills against resume skills list + full text."""
        matched: Set[str] = set()
        missing: Set[str] = set()

        for skill in required:
            # Direct match in skill list
            if skill in resume_skills:
                matched.add(skill)
                continue
            # Fuzzy against skill list
            found = False
            for rs in resume_skills:
                if SequenceMatcher(None, skill, rs).ratio() >= 0.85:
                    matched.add(skill)
                    found = True
                    break
            if found:
                continue
            # Fallback: check entire resume text
            if _fuzzy_in(skill, resume_text):
                matched.add(skill)
            else:
                missing.add(skill)

        return matched, missing

    def _score_experience(
        self, resume: Dict, jd: Dict, resume_text: str,
    ) -> Tuple[int, str]:
        """Score experience relevance (0 – W_EXPERIENCE)."""
        experiences = resume.get("experience") or []
        if not experiences:
            return 0, "No experience section found"

        jd_title = (jd.get("job_title") or "").lower()
        responsibilities = jd.get("responsibilities") or []
        keywords = _to_lower_set(jd.get("keywords") or [])

        # a) Title alignment (6 pts)
        title_score = 0
        resume_titles = [
            (exp.get("title") or "").lower() for exp in experiences
        ]
        if jd_title:
            title_tokens = set(_tokenize(jd_title)) - _STOP_WORDS
            for rt in resume_titles:
                rt_tokens = set(_tokenize(rt))
                overlap = title_tokens & rt_tokens
                if overlap:
                    ratio = len(overlap) / max(len(title_tokens), 1)
                    title_score = max(title_score, ratio)
        title_pts = round(6 * title_score)

        # b) Responsibility keyword overlap (6 pts)
        resp_matched = 0
        exp_bullets_text = " ".join(
            " ".join(exp.get("description") or []) for exp in experiences
        ).lower()
        for resp in responsibilities:
            resp_tokens = set(_tokenize(resp)) - _STOP_WORDS
            # Check if at least half the meaningful words appear in bullets
            if resp_tokens:
                found = sum(1 for t in resp_tokens if t in exp_bullets_text)
                if found / len(resp_tokens) >= 0.4:
                    resp_matched += 1
        resp_ratio = resp_matched / max(len(responsibilities), 1)
        resp_pts = round(6 * resp_ratio)

        # c) Has multiple experiences (3 pts)
        depth_pts = min(len(experiences), 3)

        total = min(title_pts + resp_pts + depth_pts, self.W_EXPERIENCE)
        detail = (
            f"title_align={title_pts}/6, "
            f"resp_match={resp_pts}/6 ({resp_matched}/{len(responsibilities)}), "
            f"depth={depth_pts}/3"
        )
        return total, detail

    def _score_sections(self, resume: Dict) -> Tuple[int, Dict[str, bool]]:
        """Score section completeness (0 – W_SECTIONS)."""
        checks = {
            "has_summary": bool(resume.get("summary")),
            "has_skills": bool(resume.get("skills")),
            "has_experience": bool(resume.get("experience")),
            "has_education": bool(resume.get("education")),
            "has_contact_email": bool(resume.get("email")),
        }
        present = sum(checks.values())
        score = round(self.W_SECTIONS * present / len(checks))
        return score, checks

    def _score_education(self, resume: Dict) -> Tuple[int, str]:
        """Score education presence (0 – W_EDUCATION)."""
        education = resume.get("education") or []
        if not education:
            return 0, "No education section"

        score = 5  # Base for having education
        has_degree = any(e.get("degree") for e in education)
        has_institution = any(e.get("institution") for e in education)

        if has_degree:
            score += 3
        if has_institution:
            score += 2

        score = min(score, self.W_EDUCATION)
        detail = f"entries={len(education)}, degree={'yes' if has_degree else 'no'}, institution={'yes' if has_institution else 'no'}"
        return score, detail

    @staticmethod
    def _generate_tips(
        kw_missing: Set[str],
        req_missing: Set[str],
        pref_missing: Set[str],
        section_checks: Dict[str, bool],
        resume: Dict,
        jd: Dict,
    ) -> List[str]:
        """Generate actionable improvement tips."""
        tips: List[str] = []

        # Missing required skills
        if req_missing:
            skills_str = ", ".join(sorted(req_missing)[:8])
            tips.append(
                f"Add these required skills if you have them: {skills_str}"
            )

        # Missing keywords
        if kw_missing:
            # Only mention keywords that aren't already in req_missing
            extra_kw = kw_missing - req_missing
            if extra_kw:
                kw_str = ", ".join(sorted(extra_kw)[:8])
                tips.append(
                    f"Consider incorporating these JD keywords into your resume: {kw_str}"
                )

        # Missing preferred skills
        if pref_missing:
            pref_str = ", ".join(sorted(pref_missing)[:5])
            tips.append(
                f"Nice-to-have skills missing (add if applicable): {pref_str}"
            )

        # Section completeness
        if not section_checks.get("has_summary"):
            tips.append(
                "Add a Professional Summary section tailored to this role")
        if not section_checks.get("has_skills"):
            tips.append(
                "Add a dedicated Skills section with relevant technologies")
        if not section_checks.get("has_contact_email"):
            tips.append("Ensure your email address is clearly visible")

        # Experience depth
        experiences = resume.get("experience") or []
        for exp in experiences:
            bullets = exp.get("description") or []
            if len(bullets) < 2:
                tips.append(
                    f"Add more achievement bullets for your role at "
                    f"{exp.get('company', 'your company')} (aim for 3-5 per role)"
                )
                break  # One tip is enough

        # Certifications
        if not resume.get("certifications"):
            jd_text = " ".join(jd.get("keywords") or []).lower()
            if any(kw in jd_text for kw in ("certif", "aws", "azure", "gcp", "pmp", "scrum")):
                tips.append(
                    "Consider adding relevant certifications — the JD mentions them")

        return tips


# Singleton
ats_engine = ATSEngine()
