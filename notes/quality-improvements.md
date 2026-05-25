# Resume Quality Improvements — Ideas Parked for Later

Snapshot of the quality analysis. Implementation tracked separately.

## Root causes (why output is currently weak)

1. **Fabricated skills land in the DOCX.** `resume_optimizer.py:247-248` concatenates `missing_required + missing_preferred` into the final skills list → JD skills the candidate doesn't have are printed as if they do.
2. **Summary prompt too thin** (`resume_optimizer.py:27-35`) — no structure, no target-title injection, no few-shot examples, temp 0.4 too high.
3. **Experience prompt fights quality** (`resume_optimizer.py:37-56`) — "same number of bullets", "max ~20 words", no XYZ structure, one bulk LLM call for all roles.
4. **Projects prompt is a near-copy** of experience — no JD-relevance ordering or filtering.
5. **Headings never change** (`docx_generator.py:72-106`) — hardcoded SUMMARY/SKILLS/EXPERIENCE…
6. **Section order never adapts** to seniority or JD priorities.
7. **Skills printed as one big blob** (`docx_generator.py:223`) — no category grouping.
8. **JD extraction shallow** (`ai_service.py:120-140`) — `seniority_level` extracted but unused; missing years, domain, scale, methodology, certs.
9. **LLM blind to ATS gap analysis** — optimizer doesn't get a list of missing keywords to surface where truthful.
10. **No verification loop** — score drop is logged but we ship anyway.
11. **ATS engine blind spots** (`ats_engine.py`) — fuzzy 0.85 too loose, equal keyword weighting, no bigram match, no alias map, no placement bonus.
12. **Job title not strategically placed** — should appear under the name or as opening of summary.
13. **No few-shot anchoring** in any prompt.

## Ideas grouped by priority

### Priority A — Stop the bleeding (truth/integrity)

- **A1.** Never inject unmatched JD skills into `optimized_skills`. Move to `gap_analysis` metadata only; surface in UI, never in DOCX.
- **A2.** Validate experience entries post-LLM. Preserve company/title/dates authoritatively (ignore LLM if they changed). Length mismatch → fall back to original.
- Same validation for projects (name/tech/link immutable).

### Priority B — Richer JD understanding

- **B1.** Expand JD extraction: years required, domain, scale signals, methodology, soft skills, certs. Use `seniority_level` downstream.
- **B2.** Weight keywords by source section (Requirements > Nice-to-have > About us).

### Priority C — Better rewrites (biggest quality lift)

- **C1.** Per-role experience rewrite, not bulk — one LLM call per role with full focus.
- **C2.** Pass ATS gap analysis into rewrite prompts: "These keywords missing — surface where truthful: [list]". Single biggest LLM-quality lever.
- **C3.** Few-shot examples (2-3 before/after) in summary + experience prompts.
- **C4.** Enforce XYZ structure: `[Strong action verb] [What] [How/scope/tech] [Quantified impact]`. Provide approved action-verb list.
- **C5.** Loosen bullet count/length: 3-6 per role, 20-35 words.
- **C6.** Open summary with the target job title.

### Priority D — Smart section adaptation

- **D1.** JD-aware section ORDER — early-career → Projects above Experience; senior → Experience first. Use seniority_level.
- **D2.** JD-aware HEADINGS — "Technical Stack" / "Engineering Toolkit" matching JD tone.
- **D3.** Drop weak sections — one stray certification when JD doesn't mention any → cut.
- **D4.** Group skills by category in DOCX (Languages / Frameworks / Cloud / Tools / Domain).

### Priority E — Quality verification loop

- **E1.** Self-scoring + retry. Score < target or delta negative → retry with prompt naming missed keywords. Cap 2 retries.
- **E2.** LLM-as-judge pass (optional): "Does this bullet support JD requirement X?" → drop bullets that fail.

### Priority F — ATS engine fixes

- **F1.** Tighten fuzzy threshold 0.85 → 0.92, or exact-substring + explicit alias map.
- **F2.** Alias/synonym map: React/React.js/ReactJS, AWS/Amazon Web Services, K8s/Kubernetes, Node/Node.js, JS/JavaScript, TS/TypeScript, …
- **F3.** Bigram + trigram matching so multi-word phrases match across non-contiguous bullets.
- **F4.** Weighted keyword scoring (required > preferred > nice-to-have).
- **F5.** Placement bonus — Summary > Skills > Experience > Projects.
- **F6.** "Target Role" line under name with JD title + top matched keywords.

### Priority G — Presentation polish

- **G1.** Action verb diversity check — avoid "Led/Developed" repetition.
- **G2.** Validate against external ATS simulator (Jobscan / Resume Worded) for ground-truth scoring.

## Suggested rollout order

1. **A** — fix integrity first (truth before quality)
2. **C (C2, C1, C3, C4)** — biggest quality lift
3. **B** — feeds C
4. **F** — measurable scoring
5. **E** — verification so we never regress
6. **D** — section adaptation
7. **G** — polish
