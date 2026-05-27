# Resume AI Browser Extension

Automatically detects job descriptions on hiring sites, sends them to your local Resume AI backend, and returns an optimized DOCX with one click.

## Install (dev / unpacked)

1. Start the backend (default `http://localhost:8000`). Change the URL in the popup → ⚙ if needed.
2. Chrome → `chrome://extensions` → **Developer mode** → **Load unpacked** → select this `extension/` folder.
3. Pin **Resume AI** to the toolbar.

## Usage

1. Open a job posting on a supported site (see below). The toolbar badge shows **✓** when a JD is detected — no button click required.
2. Click the extension icon. The popup **scans the page automatically** and shows the role title, company, and a preview.
3. Pick a parsed resume (or upload one).
4. Click **Optimize for this role**. Badge shows **⋯** while running; **↓** when done.
5. Download the DOCX or open the job page to apply.

## Supported sites (auto-detect)

| Site | URLs |
|------|------|
| LinkedIn | `linkedin.com/jobs/*` (view, search drawer, collections) |
| Greenhouse | `*.greenhouse.io/.../jobs/...` |
| Lever | `jobs.lever.co` and `*.lever.co/<co>/<id>` |
| Indeed | `indeed.com/viewjob`, `/jobs`, `/pagead` |
| Ashby | `jobs.ashbyhq.com` |
| Workday | `*.myworkdayjobs.com` |
| Glassdoor | Job listing pages |
| SmartRecruiters | `jobs.smartrecruiters.com` |
| Other | Generic heuristic on any page when you use **Scan again** |

Detection runs in the content script on page load (with retries for SPAs), again when the URL changes, and whenever you open the popup.

## Identity

No accounts. A `device_id` UUID is generated on install and sent as `X-Device-Id`. Extension uploads are scoped to that device.

Reset: extension service worker console → `await chrome.storage.local.clear()` → reload extension.

## Permissions

| Permission | Why |
|------------|-----|
| `storage` | device_id, backend URL, per-tab JD/job state |
| `tabs` | Re-scan when switching tabs |
| `activeTab` + `scripting` | Fallback JD scrape on unsupported pages |
| `downloads` | Save optimized DOCX |
| `alarms` | Poll job status while service worker sleeps |
| `host_permissions` | Auto-extract on job sites + reach backend |
