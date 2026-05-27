// Popup — auto-scans the active tab, renders JD + resume flow.

const STORAGE_KEYS = {
  DEVICE_ID: "resume_ai_device_id",
  BACKEND_URL: "resume_ai_backend_url",
};

const $ = (id) => document.getElementById(id);

let currentTabId = null;
let pollTimer = null;

let state = {
  detected: null,
  job: null,
  deviceId: null,
  backendUrl: null,
  resumes: [],
  selectedResumeId: null,
  scanning: true,
  backendOk: null,
};

document.addEventListener("DOMContentLoaded", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTabId = tab?.id;

  bindUiHandlers();
  showScanning(true);
  await refreshTabState();
  renderConnectionPill();
  await checkBackend();
  await autoDetect();
  await loadResumes();
  renderAll();

  if (state.job && !isTerminal(state.job.status)) {
    startPolling();
  }
});

function isTerminal(status) {
  return status === "completed" || status === "failed";
}

async function refreshTabState() {
  const resp = await chrome.runtime.sendMessage({
    type: "GET_TAB_STATE",
    tabId: currentTabId,
  });
  if (resp) {
    state.detected = resp.detected;
    state.job = resp.job;
    state.deviceId = resp.deviceId;
    state.backendUrl = resp.backendUrl;
  }
}

async function autoDetect() {
  showScanning(true);
  const hadJd = Boolean(state.detected?.jd_text);

  const extractResp = await chrome.runtime.sendMessage({
    type: "REQUEST_EXTRACT",
    tabId: currentTabId,
  });

  await refreshTabState();

  if (!state.detected?.jd_text && extractResp?.extracted) {
    state.detected = {
      title: extractResp.extracted.title,
      company: extractResp.extracted.company,
      jd_text: extractResp.extracted.jd_text,
      jd_url: extractResp.extracted.jd_url,
      site: extractResp.extracted.site,
    };
  }

  showScanning(false);

  if (!state.detected?.jd_text && !hadJd) {
    await new Promise((r) => setTimeout(r, 1200));
    await chrome.runtime.sendMessage({
      type: "REQUEST_EXTRACT",
      tabId: currentTabId,
    });
    await refreshTabState();
  }
}

async function checkBackend() {
  if (!state.backendUrl) {
    state.backendOk = false;
    return;
  }
  try {
    const resp = await fetch(`${state.backendUrl}/api/v1/health`, {
      method: "GET",
      signal: AbortSignal.timeout(3000),
    });
    state.backendOk = resp.ok;
  } catch (_) {
    try {
      const resp = await fetch(`${state.backendUrl}/api/v1/resumes`, {
        headers: { "X-Device-Id": state.deviceId || "" },
        signal: AbortSignal.timeout(3000),
      });
      state.backendOk = resp.status !== 0;
    } catch (e) {
      state.backendOk = false;
    }
  }
  renderConnectionPill();
}

async function loadResumes() {
  if (!state.backendUrl || !state.deviceId) return;
  try {
    const resp = await fetch(`${state.backendUrl}/api/v1/resumes`, {
      headers: { "X-Device-Id": state.deviceId },
    });
    state.resumes = resp.ok ? await resp.json() : [];
    if (!state.selectedResumeId && state.resumes.length) {
      const parsed = state.resumes.find((r) => r.is_parsed);
      state.selectedResumeId = (parsed || state.resumes[0]).id;
    }
    renderResumes();
    updateOptimizeEnabled();
  } catch (e) {
    console.warn("[Resume AI] resumes load failed", e);
    state.backendOk = false;
    renderConnectionPill();
  }
}

function showScanning(on) {
  state.scanning = on;
  $("jd-scanning").classList.toggle("hidden", !on);
  if (on) {
    $("jd-empty").classList.add("hidden");
    $("jd-detected").classList.add("hidden");
    setConnectionPill("scan", "Scanning");
  }
}

function renderConnectionPill() {
  if (state.scanning) return;
  if (state.backendOk === false) {
    setConnectionPill("error", "Offline");
  } else if (state.detected?.jd_text) {
    setConnectionPill("success", "JD ready");
  } else {
    setConnectionPill("muted", "No JD");
  }
}

function setConnectionPill(kind, label) {
  const el = $("connection-pill");
  el.textContent = label;
  el.className = "pill";
  if (kind === "success") el.classList.add("pill-success");
  else if (kind === "scan") el.classList.add("pill-scan");
  else if (kind === "error") el.classList.add("pill-error");
  else el.classList.add("pill-muted");
}

function renderAll() {
  const host = (state.backendUrl || "—").replace(/^https?:\/\//, "");
  $("backend-hint").textContent = host;
  $("device-id").textContent = (state.deviceId || "—").slice(0, 8) + "…";
  $("backend-url").value = state.backendUrl || "";

  renderSteps();
  renderJdCard();
  renderJobState();
  renderConnectionPill();
}

function renderSteps() {
  const hasJd = Boolean(state.detected?.jd_text);
  const hasResume = Boolean(state.selectedResumeId);
  const hasJob = Boolean(state.job);
  const done = state.job?.status === "completed";

  document.querySelectorAll(".step").forEach((el) => {
    const step = el.dataset.step;
    el.classList.remove("active", "done");
    if (step === "detect") {
      if (hasJd) el.classList.add("done");
      else if (!state.scanning) el.classList.add("active");
      else el.classList.add("active");
    } else if (step === "resume") {
      if (hasResume && hasJd) el.classList.add(hasJob ? "done" : "active");
      else if (hasJd) el.classList.add("active");
    } else if (step === "optimize") {
      if (done) el.classList.add("done");
      else if (hasJob && !isTerminal(state.job.status)) el.classList.add("active");
      else if (hasResume && hasJd) el.classList.add("active");
    }
  });
}

function renderJdCard() {
  if (state.scanning) return;

  const empty = $("jd-empty");
  const detected = $("jd-detected");
  const resumeSec = $("resume-section");
  const actionSec = $("action-section");

  if (state.detected?.jd_text) {
    empty.classList.add("hidden");
    detected.classList.remove("hidden");
    $("jd-title").textContent = state.detected.title || "Role detected";
    $("jd-company").textContent = state.detected.company || "Company not listed";
    $("jd-url").textContent = state.detected.jd_url || "";
    $("jd-preview").textContent = state.detected.jd_text.slice(0, 700);
    const site = state.detected.site || "auto";
    $("jd-site-badge").textContent = site;
    resumeSec.classList.remove("hidden");
    if (state.job?.status !== "completed") {
      actionSec.classList.remove("hidden");
    }
  } else {
    empty.classList.remove("hidden");
    detected.classList.add("hidden");
    resumeSec.classList.add("hidden");
    actionSec.classList.add("hidden");
  }
}

function renderResumes() {
  const list = $("resume-list");
  list.innerHTML = "";
  if (!state.resumes.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "Upload a PDF or DOCX — we'll parse it once, then reuse it for every role.";
    list.appendChild(p);
    return;
  }
  for (const r of state.resumes) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "resume-item";
    if (r.id === state.selectedResumeId) btn.classList.add("selected");
    const label = r.name || r.original_filename;
    btn.innerHTML = `
      <div class="grow">
        <div class="label">${escapeHtml(label)}</div>
        <div class="meta">${escapeHtml(r.original_filename)}</div>
      </div>
      <span class="badge ${r.is_parsed ? "parsed" : "parsing"}">
        ${r.is_parsed ? "Ready" : "Parsing"}
      </span>
    `;
    btn.addEventListener("click", () => {
      state.selectedResumeId = r.id;
      renderResumes();
      updateOptimizeEnabled();
      renderSteps();
    });
    list.appendChild(btn);
  }
}

function renderJobState() {
  const action = $("action-section");
  const result = $("result-section");
  const progressWrap = $("progress-wrap");
  const progressFill = $("progress-fill");
  const statusLine = $("status-line");
  const optBtn = $("optimize-btn");

  if (!state.job) {
    result.classList.add("hidden");
    progressWrap.classList.add("hidden");
    optBtn.textContent = "Optimize for this role";
    updateOptimizeEnabled();
    return;
  }

  if (state.job.status === "completed") {
    action.classList.add("hidden");
    result.classList.remove("hidden");
    $("result-sub").textContent = [
      state.job.title,
      state.job.company,
    ]
      .filter(Boolean)
      .join(" · ") || "Tailored DOCX is waiting for you.";
    return;
  }

  result.classList.add("hidden");
  action.classList.remove("hidden");
  progressWrap.classList.remove("hidden");

  if (state.job.status === "failed") {
    progressFill.classList.remove("indeterminate");
    progressFill.style.width = "100%";
    progressFill.style.background = "var(--danger)";
    optBtn.textContent = "Retry optimization";
    optBtn.disabled = false;
    statusLine.textContent = state.job.error_message || "Optimization failed";
    return;
  }

  progressFill.classList.add("indeterminate");
  progressFill.style.width = "";
  progressFill.style.background = "";
  optBtn.textContent = "Optimizing…";
  optBtn.disabled = true;
  statusLine.textContent = state.job.progress_message
    ? state.job.progress_message
    : `Status: ${state.job.status}`;
}

function updateOptimizeEnabled() {
  const optBtn = $("optimize-btn");
  if (!optBtn) return;
  const selected = state.resumes.find((r) => r.id === state.selectedResumeId);
  const canStart =
    state.detected?.jd_text &&
    state.selectedResumeId &&
    selected?.is_parsed !== false &&
    state.backendOk !== false &&
    (!state.job || isTerminal(state.job.status));
  optBtn.disabled = !canStart;
}

function bindUiHandlers() {
  $("settings-toggle").addEventListener("click", () => {
    $("settings").classList.toggle("hidden");
  });

  $("save-settings").addEventListener("click", async () => {
    const url = $("backend-url").value.trim().replace(/\/$/, "");
    if (!url) return;
    await chrome.storage.local.set({ [STORAGE_KEYS.BACKEND_URL]: url });
    state.backendUrl = url;
    await checkBackend();
    await loadResumes();
    renderAll();
  });

  $("detect-now").addEventListener("click", async () => {
    showScanning(true);
    await chrome.runtime.sendMessage({
      type: "REQUEST_EXTRACT",
      tabId: currentTabId,
    });
    await refreshTabState();
    showScanning(false);
    renderAll();
  });

  $("refresh-resumes").addEventListener("click", loadResumes);

  $("optimize-btn").addEventListener("click", async () => {
    if (!state.selectedResumeId) return;
    $("optimize-btn").disabled = true;
    $("progress-wrap").classList.remove("hidden");
    $("status-line").textContent = "Queueing optimization…";

    const resp = await chrome.runtime.sendMessage({
      type: "START_OPTIMIZATION",
      tabId: currentTabId,
      payload: { user_resume_id: state.selectedResumeId },
    });

    if (!resp?.ok) {
      $("status-line").textContent = resp?.error || "Failed to start";
      $("optimize-btn").disabled = false;
      return;
    }
    await refreshTabState();
    renderAll();
    startPolling();
  });

  $("upload-resume").addEventListener("click", async () => {
    const file = $("resume-file").files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    const btn = $("upload-resume");
    btn.disabled = true;
    btn.textContent = "Uploading…";
    try {
      const resp = await fetch(`${state.backendUrl}/api/v1/resumes`, {
        method: "POST",
        headers: { "X-Device-Id": state.deviceId },
        body: fd,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const row = await resp.json();
      state.selectedResumeId = row.id;
      await loadResumes();
      renderSteps();
    } catch (e) {
      $("status-line").textContent = "Upload failed: " + e.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Upload & parse";
    }
  });

  $("download-btn").addEventListener("click", async () => {
    if (!state.job?.jobId) return;
    const url = `${state.backendUrl}/api/v1/upload/jobs/${state.job.jobId}/download?format=docx`;
    await chrome.downloads.download({
      url,
      filename: suggestFilename(state.job, "docx"),
      headers: [{ name: "X-Device-Id", value: state.deviceId }],
    });
  });

  $("apply-btn").addEventListener("click", () => {
    if (state.job?.jdUrl) chrome.tabs.create({ url: state.job.jdUrl });
  });

  $("new-job-btn").addEventListener("click", async () => {
    const { resume_ai_jobs: jobs = {} } = await chrome.storage.local.get(
      "resume_ai_jobs"
    );
    delete jobs[currentTabId];
    await chrome.storage.local.set({ resume_ai_jobs: jobs });
    state.job = null;
    renderAll();
  });
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const fresh = await chrome.runtime.sendMessage({
      type: "POLL_JOB",
      tabId: currentTabId,
    });
    if (fresh?.job) {
      state.job = fresh.job;
      renderAll();
      if (isTerminal(fresh.job.status)) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }
  }, 2000);
}

function suggestFilename(job, ext) {
  const company = (job.company || "Resume").replace(/[^\w-]+/g, "_");
  return `optimized_${company}.${ext}`;
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}
