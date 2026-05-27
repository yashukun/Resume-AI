// Background service worker — device id, per-tab JD state, job polling, proactive scan.

const STORAGE_KEYS = {
  DEVICE_ID: "resume_ai_device_id",
  BACKEND_URL: "resume_ai_backend_url",
  JOBS: "resume_ai_jobs",
  DETECTED: "resume_ai_detected",
};

const DEFAULT_BACKEND = "http://localhost:8000";

const JOB_URL_RE =
  /linkedin\.com\/jobs|greenhouse\.io\/.+\/jobs\/|lever\.co\/[^/]+\/[^/?#]+|indeed\.com\/(viewjob|jobs|pagead)|jobs\.ashbyhq\.com|myworkdayjobs\.com|glassdoor\.com\/(Job|job-listing)|smartrecruiters\.com/i;

chrome.runtime.onInstalled.addListener(async () => {
  const { [STORAGE_KEYS.DEVICE_ID]: existing } = await chrome.storage.local.get(
    STORAGE_KEYS.DEVICE_ID
  );
  if (!existing) {
    await chrome.storage.local.set({
      [STORAGE_KEYS.DEVICE_ID]: crypto.randomUUID(),
    });
  }
  const { [STORAGE_KEYS.BACKEND_URL]: url } = await chrome.storage.local.get(
    STORAGE_KEYS.BACKEND_URL
  );
  if (!url) {
    await chrome.storage.local.set({
      [STORAGE_KEYS.BACKEND_URL]: DEFAULT_BACKEND,
    });
  }
});

// Proactively re-extract when user lands on a job posting URL.
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab?.url) return;
  if (!JOB_URL_RE.test(tab.url)) {
    if (changeInfo.status === "complete") clearBadgeIfNoJd(tabId);
    return;
  }
  requestExtract(tabId, false);
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (tab.url && JOB_URL_RE.test(tab.url)) requestExtract(tabId, false);
  } catch (_) {}
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg.type !== "string") return false;

  (async () => {
    try {
      switch (msg.type) {
        case "JD_DETECTED": {
          const tabId = sender.tab?.id ?? msg.tabId;
          if (tabId == null) return sendResponse({ ok: false });
          await stashDetected(tabId, msg.payload);
          await setBadge(tabId, "✓", "#10b981");
          sendResponse({ ok: true });
          break;
        }

        case "GET_TAB_STATE": {
          sendResponse(await getTabState(msg.tabId));
          break;
        }

        case "REQUEST_EXTRACT": {
          const result = await requestExtract(msg.tabId, true);
          sendResponse(result);
          break;
        }

        case "START_OPTIMIZATION": {
          sendResponse(await startOptimization(msg.tabId, msg.payload));
          break;
        }

        case "POLL_JOB": {
          sendResponse(await pollJob(msg.tabId));
          break;
        }

        default:
          sendResponse({ ok: false, error: "unknown_message" });
      }
    } catch (e) {
      console.error("[Resume AI] message handler error", e);
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true;
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const { [STORAGE_KEYS.DETECTED]: detected = {} } =
    await chrome.storage.local.get(STORAGE_KEYS.DETECTED);
  const { [STORAGE_KEYS.JOBS]: jobs = {} } = await chrome.storage.local.get(
    STORAGE_KEYS.JOBS
  );
  delete detected[tabId];
  delete jobs[tabId];
  await chrome.storage.local.set({
    [STORAGE_KEYS.DETECTED]: detected,
    [STORAGE_KEYS.JOBS]: jobs,
  });
});

async function requestExtract(tabId, fromPopup) {
  try {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "EXTRACT_NOW" });
    if (resp?.extracted) {
      await stashDetected(tabId, resp.extracted);
      await setBadge(tabId, "✓", "#10b981");
      return { ok: true, extracted: resp.extracted };
    }
    if (fromPopup) await setBadge(tabId, "", "#64748b");
    return { ok: true, extracted: null };
  } catch (_) {
    if (fromPopup) {
      const injected = await injectFallbackExtract(tabId);
      if (injected) {
        await stashDetected(tabId, injected);
        await setBadge(tabId, "✓", "#10b981");
        return { ok: true, extracted: injected };
      }
    }
    return { ok: true, extracted: null };
  }
}

async function injectFallbackExtract(tabId) {
  try {
    const [{ result } = {}] = await chrome.scripting.executeScript({
      target: { tabId },
      func: scrapeGenericJd,
    });
    if (result?.jd_text?.length >= 100) return result;
  } catch (e) {
    console.warn("[Resume AI] fallback inject failed", e);
  }
  return null;
}

function scrapeGenericJd() {
  const kw =
    /\b(job description|responsibilities|requirements|qualifications|what you.?ll do)\b/i;
  const nodes = document.querySelectorAll(
    "main, article, [role='main'], section, div"
  );
  let best = "";
  let bestScore = 0;
  for (const el of nodes) {
    if (el.querySelector("main, article")) continue;
    const txt = (el.innerText || "").trim();
    let score = Math.min(txt.length, 8000) / 80;
    if (kw.test(txt)) score += 400;
    if (score > bestScore) {
      bestScore = score;
      best = txt;
    }
  }
  if (!best || best.length < 200) return null;
  return {
    title: document.title.split("|")[0].split(" - ")[0].trim() || null,
    company: null,
    jd_text: best.slice(0, 30000),
    jd_url: location.href,
    site: "fallback",
  };
}

async function clearBadgeIfNoJd(tabId) {
  const { [STORAGE_KEYS.DETECTED]: detected = {} } =
    await chrome.storage.local.get(STORAGE_KEYS.DETECTED);
  if (!detected[tabId]) {
    try {
      await chrome.action.setBadgeText({ tabId, text: "" });
    } catch (_) {}
  }
}

async function stashDetected(tabId, payload) {
  const { [STORAGE_KEYS.DETECTED]: detected = {} } =
    await chrome.storage.local.get(STORAGE_KEYS.DETECTED);
  detected[tabId] = {
    title: payload.title,
    company: payload.company,
    jd_text: payload.jd_text,
    jd_url: payload.jd_url,
    site: payload.site,
    detected_at: Date.now(),
  };
  await chrome.storage.local.set({ [STORAGE_KEYS.DETECTED]: detected });
}

async function getTabState(tabId) {
  const {
    [STORAGE_KEYS.DETECTED]: detected = {},
    [STORAGE_KEYS.JOBS]: jobs = {},
    [STORAGE_KEYS.DEVICE_ID]: deviceId,
    [STORAGE_KEYS.BACKEND_URL]: backendUrl = DEFAULT_BACKEND,
  } = await chrome.storage.local.get([
    STORAGE_KEYS.DETECTED,
    STORAGE_KEYS.JOBS,
    STORAGE_KEYS.DEVICE_ID,
    STORAGE_KEYS.BACKEND_URL,
  ]);
  return {
    detected: detected[tabId] || null,
    job: jobs[tabId] || null,
    deviceId,
    backendUrl,
  };
}

async function setBadge(tabId, text, color) {
  try {
    await chrome.action.setBadgeText({ tabId, text });
    if (color) await chrome.action.setBadgeBackgroundColor({ tabId, color });
  } catch (_) {}
}

async function startOptimization(tabId, { user_resume_id }) {
  const { detected, deviceId, backendUrl } = await getTabState(tabId);
  if (!detected?.jd_text) {
    return { ok: false, error: "No JD detected on this tab" };
  }

  const body = {
    user_resume_id,
    jd_text: detected.jd_text,
    jd_url: detected.jd_url,
    job_title: detected.title || undefined,
    company_name: detected.company || undefined,
  };

  const resp = await fetch(`${backendUrl}/api/v1/extension/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Device-Id": deviceId,
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const txt = await resp.text();
    return { ok: false, error: `Backend ${resp.status}: ${txt}` };
  }
  const data = await resp.json();
  await saveJob(tabId, {
    jobId: data.job_id,
    status: data.status,
    createdAt: Date.now(),
    company: detected.company,
    title: detected.title,
    jdUrl: detected.jd_url,
    reusedParse: data.reused_existing_parse,
  });
  await setBadge(tabId, "⋯", "#6366f1");
  pollJob(tabId);
  return { ok: true, jobId: data.job_id };
}

async function saveJob(tabId, partial) {
  const { [STORAGE_KEYS.JOBS]: jobs = {} } = await chrome.storage.local.get(
    STORAGE_KEYS.JOBS
  );
  jobs[tabId] = { ...(jobs[tabId] || {}), ...partial };
  await chrome.storage.local.set({ [STORAGE_KEYS.JOBS]: jobs });
}

async function pollJob(tabId) {
  const { job, deviceId, backendUrl } = await getTabState(tabId);
  if (!job?.jobId) return { ok: false, error: "no_job" };
  if (job.status === "completed" || job.status === "failed") {
    return { ok: true, job };
  }

  try {
    const resp = await fetch(
      `${backendUrl}/api/v1/upload/jobs/${job.jobId}/status`,
      { headers: { "X-Device-Id": deviceId } }
    );
    if (resp.ok) {
      const data = await resp.json();
      await saveJob(tabId, {
        status: data.status,
        progress_message: data.progress_message,
        error_message: data.error_message,
      });
      if (data.status === "completed") {
        await setBadge(tabId, "↓", "#10b981");
      } else if (data.status === "failed") {
        await setBadge(tabId, "!", "#ef4444");
      } else {
        await setBadge(tabId, "⋯", "#6366f1");
        chrome.alarms.create(`poll-${tabId}`, { delayInMinutes: 0.05 });
      }
    }
  } catch (e) {
    console.warn("[Resume AI] poll failed", e);
    chrome.alarms.create(`poll-${tabId}`, { delayInMinutes: 0.1 });
  }
  const refreshed = await getTabState(tabId);
  return { ok: true, job: refreshed.job };
}

chrome.alarms.onAlarm.addListener((alarm) => {
  const m = /^poll-(\d+)$/.exec(alarm.name);
  if (m) pollJob(Number(m[1]));
});
