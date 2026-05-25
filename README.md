# Resume AI

AI-powered resume optimizer that scores your resume against job descriptions and suggests improvements for ATS compatibility — all running locally with Ollama.

## Features

- Upload PDF/DOCX resumes and paste a job description
- ATS compatibility scoring with actionable feedback
- AI-driven keyword matching, bullet point enhancement, and skills gap analysis
- Async processing via Celery — upload and check back when ready
- Dark mode UI

## Tech Stack

| Layer    | Tech                                       |
| -------- | ------------------------------------------ |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS   |
| Backend  | FastAPI (Python)                           |
| Database | PostgreSQL                                 |
| Queue    | Celery + Redis                             |
| Storage  | MinIO (S3-compatible)                      |
| AI       | Ollama — `llama3.2:3b`, `qwen2.5:7b`       |

## Getting Started

**Prerequisites:** Docker & Docker Compose, and Ollama installed natively on your host.

> **Why native Ollama instead of containerized?** Docker on macOS has no
> Metal/GPU access. CPU-only inference in a container is 10-30× slower
> than running Ollama natively — slow enough that requests time out. We
> run all infra in Docker and Ollama on the host for the best of both.
> If you're on Linux with NVIDIA GPUs and want a fully containerized
> setup, the in-Docker Ollama services are commented in `docker-compose.yaml`.

### 1. Install and start Ollama on your host

```bash
# Mac
brew install ollama
ollama serve &                  # leaves the daemon running on :11434

# Pull the models we use (one-time, ~6.7 GB total)
ollama pull llama3.2:3b         # fast structured extraction
ollama pull qwen2.5:7b          # richer optimization
```

(Linux: `curl -fsSL https://ollama.com/install.sh | sh`, then the same `pull` commands.)

### 2. Start the rest of the stack in Docker

```bash
docker-compose up -d
```

The backend and Celery worker reach the host Ollama via
`host.docker.internal:11434` (resolved automatically on Mac/Windows and
via `extra_hosts: host-gateway` on Linux).

| Service       | URL                        |
| ------------- | -------------------------- |
| App           | http://localhost:3000      |
| API           | http://localhost:8000      |
| API Docs      | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001      |

## Local Development

```bash
# Backend
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Celery worker (separate terminal)
celery -A app.workers.celery_app worker --loglevel=info

# Frontend
cd frontend && npm install && npm run dev
```

## API

```
POST   /api/v1/upload/resume              Upload resume + job description
GET    /api/v1/upload/jobs/{job_id}/status  Check processing status
GET    /api/v1/upload/jobs/{job_id}/resume  Get parsed/optimized resume
```

## Project Structure

```
backend/
  app/
    api/        Routes
    core/       Config & DB
    models/     SQLAlchemy models
    services/   Parsing, AI, ATS engine
    workers/    Celery tasks
frontend/
  src/
    components/ React components
    services/   API client
    hooks/      Custom hooks
```

## Troubleshooting

```bash
docker-compose logs backend          # Backend logs
docker-compose logs celery_worker    # Worker logs
docker-compose down -v               # Full reset (deletes data)
```

**Jobs stuck in "parsing" or "optimizing" for many minutes**
1. Confirm host Ollama is running: `curl -s http://localhost:11434/api/tags`
2. From inside a container, confirm it can reach the host:
   `docker exec resume_ai_backend python -c "import httpx; print(httpx.get('http://host.docker.internal:11434/api/tags').status_code)"`
3. Check model load: `ollama ps` (on the host, not in Docker)
4. If you've changed Ollama config, restart the worker:
   `docker compose restart celery_worker`

## License

MIT
