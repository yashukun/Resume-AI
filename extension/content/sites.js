// Per-site JD extractors. Each entry: match(url), extract(document).
// "jd_text" is required; title/company are best-effort (backend backfills).

(function () {
  function text(el) {
    return el ? (el.innerText || el.textContent || "").trim() : "";
  }

  function firstText(doc, selectors) {
    for (const sel of selectors) {
      const el = doc.querySelector(sel);
      const t = text(el);
      if (t) return t;
    }
    return null;
  }

  function firstBlock(doc, selectors, minLen = 100) {
    for (const sel of selectors) {
      const el = doc.querySelector(sel);
      const t = text(el);
      if (t && t.length >= minLen) return t;
    }
    return null;
  }

  /** Click "See more" / expand truncated JD blocks (LinkedIn, etc.). */
  function expandTruncatedDescription(doc) {
    const clickTargets = [
      ".jobs-description__footer-button",
      "[data-tracking-control-name='public_jobs_show-more-html-btn']",
      "button.show-more-less-html__button",
      ".jobs-box__html-content button",
      ".show-more-less-html button",
    ];
    for (const sel of clickTargets) {
      const btn = doc.querySelector(sel);
      if (btn && !btn.disabled) {
        btn.click();
        return;
      }
    }
    const spans = doc.querySelectorAll(
      ".jobs-description span, .jobs-description-content__text span, #job-details span"
    );
    for (const span of spans) {
      if (span.children.length === 0 && /^more$/i.test(span.textContent.trim())) {
        const parent = span.closest("button, span[role='button'], .show-more-less-html");
        (parent || span.parentElement)?.click();
        return;
      }
    }
  }

  const JD_KEYWORDS =
    /\b(job description|responsibilities|requirements|qualifications|what you.?ll do|about the role|we are looking for)\b/i;

  function scoreJdBlock(txt) {
    if (!txt || txt.length < 120) return 0;
    let score = Math.min(txt.length, 8000) / 80;
    if (JD_KEYWORDS.test(txt)) score += 400;
    if (txt.length > 400 && txt.length < 25000) score += 100;
    return score;
  }

  function largestJdLikeBlock(doc) {
    const roots = doc.querySelectorAll(
      "main, article, [role='main'], section, div[class*='description'], div[id*='description']"
    );
    let best = null;
    let bestScore = 0;
    for (const el of roots) {
      if (el.querySelector("main, article")) continue;
      const t = text(el);
      const s = scoreJdBlock(t);
      if (s > bestScore) {
        bestScore = s;
        best = t;
      }
    }
    return bestScore > 50 ? best : null;
  }

  const SITES = [
    {
      name: "linkedin",
      match: (url) => /linkedin\.com\/jobs/.test(url),
      extract: (doc) => {
        expandTruncatedDescription(doc);
        const title = firstText(doc, [
          ".job-details-jobs-unified-top-card__job-title",
          ".jobs-unified-top-card__job-title",
          "h1.t-24",
          "h2.t-24",
          "[class*='job-title'] h1",
          "h1",
        ]);
        const company = firstText(doc, [
          ".job-details-jobs-unified-top-card__company-name a",
          ".jobs-unified-top-card__company-name a",
          ".jobs-unified-top-card__company-name",
          "[class*='top-card'] [class*='company-name']",
        ]);
        const jd_text = firstBlock(
          doc,
          [
            ".jobs-description__content .jobs-box__html-content",
            ".show-more-less-html__markup",
            ".jobs-description-content__text",
            ".jobs-description__content",
            "article.jobs-description__container",
            ".jobs-description",
            "#job-details",
            "[class*='description'] > section > div",
            ".core-section-container__content",
          ],
          80
        );
        if (!jd_text) return null;
        return { title, company, jd_text };
      },
    },

    {
      name: "greenhouse",
      match: (url) => /greenhouse\.io\/.+\/jobs\//.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(doc, ["#content", ".content", "#app"], 100);
        if (!jd_text) return null;
        return {
          title: firstText(doc, ["h1.app-title", "h1"]),
          company: (firstText(doc, [".company-name"]) || "").replace(/^at\s+/i, "").trim() || null,
          jd_text,
        };
      },
    },

    {
      name: "lever",
      match: (url) => /(?:jobs\.)?lever\.co\/[^/]+\/[^/?#]+/.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(
          doc,
          [".section.page-centered.posting-page", ".content-wrapper", ".posting-page"],
          100
        );
        if (!jd_text) return null;
        const tabTitle = doc.title || "";
        const companyGuess = tabTitle.includes(" - ") ? tabTitle.split(" - ")[0].trim() : null;
        return {
          title: firstText(doc, [".posting-headline h2", ".posting-headline"]),
          company: companyGuess,
          jd_text,
        };
      },
    },

    {
      name: "indeed",
      match: (url) => /indeed\.com\/(viewjob|jobs|pagead)/.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(
          doc,
          ["#jobDescriptionText", "[id*='jobDescription']", ".jobsearch-JobComponent-description"],
          100
        );
        if (!jd_text) return null;
        return {
          title: firstText(doc, [
            "h1.jobsearch-JobInfoHeader-title",
            "[data-testid='jobsearch-JobInfoHeader-title']",
            "h1",
          ]),
          company: firstText(doc, [
            "[data-testid='inlineHeader-companyName'] a",
            "[data-company-name='true']",
            ".jobsearch-InlineCompanyRating a",
          ]),
          jd_text,
        };
      },
    },

    {
      name: "ashby",
      match: (url) => /jobs\.ashbyhq\.com\//.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(
          doc,
          ["[class*='JobDescription']", "[class*='job-description']", "main", "article"],
          100
        );
        if (!jd_text) return null;
        return {
          title: firstText(doc, ["h1", "[class*='JobTitle']"]),
          company: firstText(doc, ["[class*='CompanyName']", "header a"]),
          jd_text,
        };
      },
    },

    {
      name: "workday",
      match: (url) => /myworkdayjobs\.com\//.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(
          doc,
          [
            "[data-automation-id='jobPostingDescription']",
            "[data-automation-id='jobPostingDetails']",
            "[class*='jobDescription']",
            "main",
          ],
          100
        );
        if (!jd_text) return null;
        return {
          title: firstText(doc, [
            "[data-automation-id='jobPostingHeader'] h2",
            "h2[data-automation-id='jobPostingHeader']",
            "h1",
          ]),
          company: firstText(doc, ["[data-automation-id='company']"]),
          jd_text,
        };
      },
    },

    {
      name: "glassdoor",
      match: (url) => /glassdoor\.com\/(Job|job-listing)/i.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(
          doc,
          ["[class*='JobDescription']", "[class*='jobDescription']", "#JobDescription", "main"],
          100
        );
        if (!jd_text) return null;
        return {
          title: firstText(doc, ["[data-test='job-title']", "h1"]),
          company: firstText(doc, ["[data-test='employer-name']", "[class*='employerName']"]),
          jd_text,
        };
      },
    },

    {
      name: "smartrecruiters",
      match: (url) => /jobs\.smartrecruiters\.com\//.test(url),
      extract: (doc) => {
        const jd_text = firstBlock(doc, ["[class*='job-description']", ".job-section", "main"], 100);
        if (!jd_text) return null;
        return {
          title: firstText(doc, ["h1", ".job-title"]),
          company: firstText(doc, [".company-name", "header h2"]),
          jd_text,
        };
      },
    },

    {
      name: "generic",
      match: () => true,
      extract: (doc) => {
        const jd_text = largestJdLikeBlock(doc);
        if (!jd_text || jd_text.length < 200) return null;
        return {
          title: (doc.title || "").split("|")[0].split(" - ")[0].trim() || null,
          company: null,
          jd_text: jd_text.slice(0, 30000),
        };
      },
    },
  ];

  self.RESUME_AI_SITES = SITES;
  self.RESUME_AI_HELPERS = {
    expandTruncatedDescription,
    scoreJdBlock,
  };
})();
