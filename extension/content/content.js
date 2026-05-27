// Content script — auto-detects JDs on job pages (SPAs included).

(function () {
  const SITES = self.RESUME_AI_SITES || [];
  const { expandTruncatedDescription } = self.RESUME_AI_HELPERS || {};

  let lastFingerprint = null;
  let extractAttempts = 0;
  const MAX_ATTEMPTS = 8;
  const RETRY_MS = [0, 400, 900, 1800, 3000, 5000, 8000, 12000];

  function extract() {
    const url = window.location.href;
    if (expandTruncatedDescription) expandTruncatedDescription(document);

    for (const site of SITES) {
      if (!site.match(url)) continue;
      try {
        const result = site.extract(document);
        if (result?.jd_text?.length >= 80) {
          return {
            ...result,
            jd_url: url,
            site: site.name,
            jd_text: result.jd_text.slice(0, 30000),
          };
        }
      } catch (e) {
        console.warn(`[Resume AI] ${site.name} extractor failed:`, e);
      }
    }
    return null;
  }

  function fingerprint(data) {
    const head = (data.jd_text || "").slice(0, 200);
    return `${data.jd_url}::${data.title || ""}::${head.length}::${head}`;
  }

  function maybeSend(force = false) {
    const extracted = extract();
    if (!extracted) return false;

    const fp = fingerprint(extracted);
    if (!force && fp === lastFingerprint) return true;

    lastFingerprint = fp;
    chrome.runtime
      .sendMessage({ type: "JD_DETECTED", payload: extracted })
      .catch(() => {});
    return true;
  }

  function scheduleRetries() {
    for (let i = 0; i < MAX_ATTEMPTS && i < RETRY_MS.length; i++) {
      const delay = RETRY_MS[i];
      setTimeout(() => {
        extractAttempts++;
        const ok = maybeSend(false);
        if (ok && extractAttempts >= 2) {
          // Found JD — fewer future retries needed
        }
      }, delay);
    }
  }

  scheduleRetries();

  let debounce = null;
  const observer = new MutationObserver(() => {
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(() => maybeSend(false), 500);
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener("DOMContentLoaded", () => {
      observer.observe(document.body, { childList: true, subtree: true });
    });
  }

  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      lastFingerprint = null;
      extractAttempts = 0;
      scheduleRetries();
    }
  }, 1000);

  window.addEventListener("popstate", () => {
    lastFingerprint = null;
    setTimeout(() => maybeSend(true), 600);
  });

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type === "EXTRACT_NOW") {
      lastFingerprint = null;
      if (expandTruncatedDescription) expandTruncatedDescription(document);
      const extracted = extract();
      if (extracted) {
        lastFingerprint = fingerprint(extracted);
        chrome.runtime
          .sendMessage({ type: "JD_DETECTED", payload: extracted })
          .catch(() => {});
      }
      sendResponse({ extracted, scanning: false });
    }
    return true;
  });
})();
