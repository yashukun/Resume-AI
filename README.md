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
| AI       | Ollama — `llama3.2:8b`, `qwen2.5-coder:7b` |

## Getting Started

**Prerequisites:** Docker & Docker Compose

```bash
# Start everything
docker-compose up -d

# Pull AI models (first run only)
docker exec -it resume_ai_ollama ollama pull llama3.2:8b
docker exec -it resume_ai_ollama ollama pull qwen2.5-coder:7b
```

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

## License

MIT
