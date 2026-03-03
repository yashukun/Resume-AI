import httpx, time, json

B = "http://host.docker.internal:11434"
M = "llama3.2:3b"

R = "# John Smith\njohn@email.com|555-123-4567\n## Summary\nSr SWE 5+yrs Python AWS distributed systems.\n## Skills\nPython,JS,Go,AWS,Docker,K8s,PostgreSQL,Redis,React\n## Experience\n### Sr SWE|TechCorp|2022-Present\n-Led microservices migration 60% faster deploys\n-Built 2M events/day pipeline with Kafka\n### SWE|StartupXYZ|2019-2021\n-REST APIs 500K DAU with FastAPI\n-CI/CD with GitHub Actions\n## Education\nBS CS MIT 2019\n## Certs\nAWS SA, CKA"

J = "Senior Backend Engineer FinTech Corp. Required: Python AWS PostgreSQL Docker K8s REST APIs. Preferred: Go, Terraform, Kafka. Responsibilities: scalable microservices, CI/CD, mentoring. 5+ years needed."

SP = 'Resume parser. Return ONLY valid JSON: {"name":"","email":"","phone":"","summary":"","skills":[],"experience":[{"title":"","company":"","dates":"","description":[]}],"education":[{"degree":"","institution":"","year":""}],"certifications":[]}'

JP = 'JD analyzer. Return ONLY valid JSON: {"job_title":"","required_skills":[],"preferred_skills":[],"keywords":[],"seniority_level":""}'


def call(name, sys_p, user, jm=False, cx=None, pr=None):
    p = {
        "model": M,
        "messages": [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.1},
        "keep_alive": "30m",
    }
    if jm:
        p["format"] = "json"
    if cx:
        p["options"]["num_ctx"] = cx
    if pr:
        p["options"]["num_predict"] = pr

    t0 = time.time()
    r = httpx.post(f"{B}/api/chat", json=p, timeout=120)
    elapsed = time.time() - t0
    ct = r.json().get("message", {}).get("content", "")

    valid = False
    try:
        i = ct.index("{")
        j = ct.rindex("}") + 1
        json.loads(ct[i:j])
        valid = True
    except Exception:
        pass

    print(f"{name:45s} | {elapsed:5.1f}s | {len(ct):5d}ch | ok={valid}")
    return elapsed


print("=" * 70)
print(f"Model: {M}")
print("=" * 70)

t1 = call("Resume (json_mode+ctx8k+pred4k)", SP, "Parse:\n" + R, jm=True, cx=8192, pr=4096)
t2 = call("JD (json_mode+ctx4k+pred2k)", JP, "Parse:\n" + J, jm=True, cx=4096, pr=2048)

print("=" * 70)
print(f"Resume: {t1:.1f}s | JD: {t2:.1f}s | Total: {t1+t2:.1f}s")
