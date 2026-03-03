import httpx
import asyncio
import time
import json

SYSTEM_PROMPT = """You are a resume parser. Extract info as JSON:
{
  "name": "Full Name",
  "contact": {"email": "...", "phone": "..."},
  "sections": [{"title": "Skills", "content": ["skill1", "skill2"]}]
}
Only return valid JSON, no other text."""

async def test():
    resume_text = """YASH AGARWAL
+91 8770357485 | yash@gmail.com | LinkedIn | Github

PROFESSIONAL SUMMARY
Python Developer with 3 years experience

SKILLS
Python, Django, FastAPI, PostgreSQL, Docker

EXPERIENCE
Software Developer at TechCorp
2022 - Present
- Built REST APIs using FastAPI
- Deployed apps with Docker

EDUCATION
Bachelor of Computer Applications
ITM University 2024
"""
    
    payload = {
        "model": "llama3.2:3b",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Parse this resume:\n\n{resume_text}"}
        ],
        "stream": False,
        "options": {"temperature": 0.1}
    }
    
    async with httpx.AsyncClient() as client:
        print("Sending resume extraction request...")
        start = time.time()
        resp = await client.post("http://ollama:11434/api/chat", json=payload, timeout=300)
        elapsed = time.time() - start
        print(f"Completed in {elapsed:.1f}s")
        print("Status:", resp.status_code)
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        print("Response:")
        print(content)

if __name__ == "__main__":
    asyncio.run(test())
