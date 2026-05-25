# Performance & Async Bottlenecks — Ideas Parked for Later

Snapshot of the bottleneck analysis. Not yet implemented.

## The async illusion

Every `await` in the pipeline hides a blocking sync call — the event loop is effectively single-threaded.

| Location | "awaits" | Actually runs |
|---|---|---|
| `storage.py:51-59` | `upload_file()` | Sync `Minio.put_object` blocks |
| `storage.py:77-80` | `download_file()` | Sync `Minio.get_object` blocks |
| `resume_parser.py:189` | `_extract_from_pdf` | `pymupdf4llm.to_markdown()` CPU-bound sync |
| `resume_parser.py:229` | `_extract_from_docx` | `mammoth` + `BeautifulSoup` sync |
| `docx_generator.py:44` | `generate()` | python-docx sync, not wrapped |
| `pdf_converter.py:42` | `convert()` | `subprocess.run` blocks worker 5-15s |
| `database.py:32-38` | `get_task_session()` | New asyncpg engine per task (~50-200ms) |

Combined with Celery `--concurrency=1` in docker-compose.yaml:180 → **one resume at a time, end to end**.

## Bottleneck ranking by wall-time impact

1. **Ollama called 5× serially** (~80% of wall time). All gated by a global semaphore at `ai_service.py:253`. Mac Metal: ~5-15s each → 25-75s minimum. CPU Docker: 30-120s each → 2-10 min.
2. **Two Celery tasks with no concurrency benefit** — `process_resume` → `optimize_resume` split adds Redis hop + engine bootstrap, gains nothing at concurrency=1.
3. **Redundant health check per task** (`tasks.py:199`) — 200-1000ms wasted.
4. **ATS scored twice** (`tasks.py:221, 236`) — full re-tokenization, O(n·m) fuzzy match repeated.
5. **Oversized LLM context** — `num_ctx=8192, num_predict=4096` for resumes that fit in 2K. Bigger KV cache = slower.
6. **PDF conversion blocks the worker** — `subprocess.run(libreoffice)` ties up entire prefork worker for 5-15s.
7. **Frontend 1-3s polling** — adds DB load + perceived latency on completion.

## Fix tiers (ranked by ROI)

### Tier 1 — Biggest wins (50-70% cut)

- **A. Drop the LLM call for resume parsing.** Sections (Experience, Education, etc.) are headings — parse with regex + section detection over `pymupdf4llm` markdown. Contact already regex-extracted at `resume_parser.py:110-131`. Use LLM only as fallback. **Saves 10-60s.**
- **B. Parallelize independent work.** JD extraction does not depend on resume parsing. Run with `asyncio.gather`. Set `OLLAMA_NUM_PARALLEL=2`. **Saves 5-20s.**
- **C. Batch the three optimization calls into one.** Single prompt returns `{"summary", "experience", "projects"}`. Eliminates 2 semaphore waits + warmups. **Saves 5-15s.**
- **D. Merge the two Celery tasks.** No queue boundary needed. **Saves 1-3s + simpler errors.**

### Tier 2 — Make async actually async

- **E. Wrap blocking I/O with `asyncio.to_thread`** — MinIO, pymupdf4llm, mammoth, docx_generator, pdf_converter.
- **F. Switch Celery pool to gevent or threads + raise concurrency** — `--pool=gevent --concurrency=4`. With `OLLAMA_NUM_PARALLEL=2`, multiple resumes process simultaneously.
- **G. Replace per-task engine with a long-lived sync engine.** For Celery, sync `Session` with a real pool is faster than asyncio-in-celery.

### Tier 3 — Trim the fat

- **H. Reduce LLM token budgets:** resume extraction `num_ctx=4096, num_predict=2048`; JD extraction `num_predict=1024`; summary `num_predict=384`. Cache health_check with 60s TTL.
- **I. Compute resume_text once and share between ATS before/after.**
- **J. Run PDF conversion in thread pool** — or skip; generate PDF on-demand from download endpoint.
- **K. Frontend: polling → Server-Sent Events** (FastAPI `EventSourceResponse`).

### Tier 4 — Warmup & model selection

- **L.** Warm both models in `celery_app.py:46-71`, not just `ollama_model_fast`.
- **M.** Test whether `llama3.2:3b` alone is good enough for rewrites — eliminates model swap.

## Expected impact

| Change | Single-resume wall time |
|---|---|
| Today (Mac Metal) | ~60-120s |
| + Tier 1 | ~25-50s |
| + Tier 2 | same single-job latency, **N jobs in parallel** |
| + Tier 3 | ~20-40s |

## Suggested rollout order (each a self-contained PR)

1. Tier 1A+B+C — heuristic parser + parallel JD/parse + batched optimize prompt
2. Tier 2E+F — `asyncio.to_thread` wrappers + gevent pool
3. Tier 3 + 4 — token trims, SSE, PDF on-demand
