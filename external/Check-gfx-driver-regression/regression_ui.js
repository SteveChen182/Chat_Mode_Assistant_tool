/**
 * GFX/GOP Driver Regression UI
 * ================================
 * Portable JavaScript module for GFX/GOP driver regression checking UI.
 * Extracted from sidepanel.js — can be included in any web page that integrates
 * with the regression checker HTTP server.
 *
 * Required globals (must be defined by the host page before this script runs):
 *   BRIDGE_BASE_URL   - e.g. "http://127.0.0.1:8775"
 *   t(key)            - i18n lookup function
 *   tFormat(key,vars) - i18n with variable substitution
 *   setStatus(m,text) - status bar update
 *   activeHsdId       - current HSD ID string
 *   isSending         - boolean lock
 *   addSystemMessage(text)       - add plain text message to chat
 *   addMessage(role, content)    - add a message to chat
 *   addHtmlMessage(html)         - add HTML message to chat, returns element
 *
 * Exported functions (for use in the host page):
 *   checkGfxRegression()   - trigger GFX regression check
 *   checkGopRegression()   - trigger GOP regression check
 */

// ── Version input overlay ─────────────────────────────────────────────────────

function showVersionInputOverlay(failVersion, passVersion, opts = {}) {
  return new Promise((resolve) => {
    const overlay    = document.getElementById("versionInputOverlay");
    const failEl     = document.getElementById("versionFailInput");
    const passEl     = document.getElementById("versionPassInput");
    const errorEl    = document.getElementById("versionInputError");
    const confirmBtn = document.getElementById("versionInputConfirmBtn");
    const cancelBtn  = document.getElementById("versionInputCancelBtn");
    const titleEl    = document.getElementById("versionInputTitle");
    const msgEl2     = document.getElementById("versionInputMsg");

    titleEl.textContent = opts.title || "Driver Version";
    msgEl2.textContent  = opts.msg   || "版本無法從 HSD 自動讀取，請手動填寫：";
    failEl.placeholder  = opts.failPlaceholder || "e.g. 101.6651 or 32.0.101.6651";
    passEl.placeholder  = opts.passPlaceholder || "e.g. 101.6650 or 32.0.101.6650";
    const failLabelEl = document.getElementById("versionFailLabel");
    const passLabelEl = document.getElementById("versionPassLabel");
    if (failLabelEl) failLabelEl.textContent = opts.failLabel || "❌ Fail Driver Version";
    if (passLabelEl) passLabelEl.textContent = opts.passLabel || "✅ Last Passing Version";

    failEl.value = failVersion || "";
    passEl.value = passVersion || "";
    errorEl.style.display = "none";
    errorEl.textContent   = "";
    confirmBtn.disabled   = false;
    overlay.classList.add("show");
    (failEl.value ? passEl : failEl).focus();

    function cleanup() {
      overlay.classList.remove("show");
      confirmBtn.replaceWith(confirmBtn.cloneNode(true));
      cancelBtn.replaceWith(cancelBtn.cloneNode(true));
    }

    document.getElementById("versionInputCancelBtn").addEventListener("click", () => {
      cleanup();
      resolve(null);
    }, { once: true });

    document.getElementById("versionInputConfirmBtn").addEventListener("click", () => {
      const fv = failEl.value.trim();
      const pv = passEl.value.trim();
      if (!fv && !pv) {
        errorEl.textContent   = "請至少填寫一個版本號";
        errorEl.style.display = "block";
        return;
      }
      cleanup();
      resolve({ fail: fv, pass: pv });
    }, { once: true });
  });
}

// ── QB login overlay ──────────────────────────────────────────────────────────

async function _doQbSearch(failVersion, passVersion, fixVersion, buildType, foundInVersion, gopPlatform) {
  const isGopBuild = buildType === "gop";
  _setRegProgress(50, t(isGopBuild ? "qbGopProgressSearch" : "qbProgressSearch"));
  setStatus("loading", t("qbSearching"));
  const pctTimer = setTimeout(() => _setRegProgress(75), 6000);
  try {
    const buildResp = await fetch(`${BRIDGE_BASE_URL}/qb-builds`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fail_version: failVersion,
        pass_version: passVersion,
        fix_version: fixVersion || "",
        found_in_version: foundInVersion || "",
        build_type: buildType || "gfx",
        gop_platform: gopPlatform || "",
      }),
    });
    clearTimeout(pctTimer);
    const buildData = await buildResp.json();
    _setRegProgress(90, t("qbProgressDone"));
    return buildData;
  } catch (err) {
    clearTimeout(pctTimer);
    return null;
  }
}

async function showQbLoginOverlay(failVersion, passVersion, fixVersion, buildType, foundInVersion, gopPlatform) {
  // If already authenticated, skip the login form entirely
  try {
    const authResp = await fetch(`${BRIDGE_BASE_URL}/qb-check-auth`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const authData = await authResp.json();
    if (authData.logged_in) {
      return await _doQbSearch(failVersion, passVersion, fixVersion, buildType, foundInVersion, gopPlatform);
    }
  } catch (e) {
    // fall through to show login form
  }

  return new Promise((resolve) => {
    const overlay = document.getElementById("qbLoginOverlay");
    const titleEl = document.getElementById("qbLoginTitle");
    const msgEl = document.getElementById("qbLoginMsg");
    const userEl = document.getElementById("qbUsername");
    const passEl = document.getElementById("qbPassword");
    const errorEl = document.getElementById("qbLoginError");
    const continueBtn = document.getElementById("qbContinueBtn");
    const cancelBtn = document.getElementById("qbCancelBtn");

    titleEl.textContent = t("qbLoginTitle");
    msgEl.textContent = t("qbLoginMsg");
    continueBtn.textContent = t("qbContinueBtn");
    cancelBtn.textContent = t("qbCancelBtn");
    userEl.value = "";
    passEl.value = "";
    errorEl.style.display = "none";
    errorEl.textContent = "";
    continueBtn.disabled = false;
    overlay.classList.add("show");
    userEl.focus();

    function cleanup() {
      overlay.classList.remove("show");
      const oldContinue = document.getElementById("qbContinueBtn");
      const oldCancel = document.getElementById("qbCancelBtn");
      if (oldContinue) oldContinue.replaceWith(oldContinue.cloneNode(true));
      if (oldCancel) oldCancel.replaceWith(oldCancel.cloneNode(true));
    }

    const liveCancel = document.getElementById("qbCancelBtn");
    const liveContinue = document.getElementById("qbContinueBtn");

    liveCancel.addEventListener("click", () => {
      cleanup();
      resolve(null);
    }, { once: true });

    liveContinue.addEventListener("click", async () => {
      const username = userEl.value.trim();
      const password = passEl.value;
      if (!username || !password) {
        errorEl.textContent = "Please enter both username and password";
        errorEl.style.display = "block";
        return;
      }
      continueBtn.disabled = true;
      errorEl.style.display = "none";

      const progressContainer = document.getElementById("qbProgressContainer");
      const progressBar = document.getElementById("qbProgressBar");
      const progressText = document.getElementById("qbProgressText");

      progressContainer.classList.add("show");
      progressBar.classList.remove("indeterminate");
      progressBar.style.width = "20%";
      progressText.textContent = t("qbProgressLogin");
      setStatus("loading", t("qbLoggingIn"));

      try {
        const loginResp = await fetch(`${BRIDGE_BASE_URL}/qb-login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        });
        const loginData = await loginResp.json();
        if (!loginData.ok) {
          errorEl.textContent = loginData.error || "Login failed";
          errorEl.style.display = "block";
          continueBtn.disabled = false;
          progressContainer.classList.remove("show");
          progressBar.style.width = "0%";
          return;
        }

        cleanup();
        progressContainer.classList.remove("show");
        progressBar.style.width = "0%";

        resolve(await _doQbSearch(failVersion, passVersion, fixVersion, buildType, foundInVersion, gopPlatform));
      } catch (err) {
        cleanup();
        progressContainer.classList.remove("show");
        progressBar.style.width = "0%";
        resolve(null);
      }
    });
  });
}

// ── QB build data formatting ──────────────────────────────────────────────────

function formatQbBuilds(qbData, failVersion, passVersion, fixVersion, foundInVersion) {
  if (!qbData || !qbData.ok) return [];
  const lines = [];
  const failBuilds = qbData.fail_builds || [];
  const passBuilds = qbData.pass_builds || [];
  const fixBuilds = qbData.fix_builds || [];
  const foundInBuilds = qbData.found_in_builds || [];

  function pushBuild(b, version, role) {
    const ci = b.ci_master || "N/A";
    const bver = b.version || "";
    const wwMatch = bver.match(/_(\d+ww\d+)/i);
    const workWeek = wwMatch ? wwMatch[1] : "";
    const prMatch = bver.match(/revenue-pr-(\d+)$/);
    const revenuePr = prMatch ? prMatch[1] : "";
    const entry = { version, build: bver, ci_master: ci, role, build_id: b.build_id || "", ci_build_id: b.ci_build_id || "", work_week: workWeek, revenue_pr: revenuePr };
    if (b.cherry_pick_from) entry.cherry_pick_from = b.cherry_pick_from;
    if (b.is_bugcheck) entry.is_bugcheck = true;
    lines.push(entry);
  }

  if (passBuilds.length > 0) passBuilds.forEach((b) => pushBuild(b, passVersion, "Pass"));
  if (failBuilds.length > 0) failBuilds.forEach((b) => pushBuild(b, failVersion, "Fail"));
  if (foundInBuilds.length > 0) foundInBuilds.forEach((b) => pushBuild(b, foundInVersion || "N/A", "Fail"));
  if (fixBuilds.length > 0) fixBuilds.forEach((b) => pushBuild(b, fixVersion, "Fix"));

  return lines;
}

// ── Regression result table HTML ──────────────────────────────────────────────

function buildRegressionTable(data, qbData, buildType) {
  const failV = data.driver_version_fail || "N/A";
  const passV = data.last_passing_bkc || "N/A";
  const fixedV = data.fixed_in_version || "";
  const foundInV = data.found_in_version || "";
  const isReg = data.is_regression || "Unknown";
  const isGop = buildType === "gop";
  const titleKey = isGop ? "gopRegressionTitle" : "regressionTitle";
  const qbGfxUrl = "https://ubit-gfx.intel.com/dashboard/7931";
  const qbGopUrl = "https://ubit-gfx.intel.com/dashboard/8078";
  const qbUrl = (qbData && qbData.quickbuild_url) || (isGop ? qbGopUrl : qbGfxUrl);

  const esc = (s) => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const css =
    `<style>` +
    `.reg-tbl{border-collapse:collapse;width:100%;font-size:12px;margin:6px 0}` +
    `.reg-tbl th,.reg-tbl td{border:1px solid #d1d5db;padding:5px 8px;text-align:left}` +
    `.reg-tbl th{background:#f3f4f6;font-weight:700;white-space:nowrap}` +
    `.reg-tbl .pass{color:#16a34a;font-weight:600}` +
    `.reg-tbl .fail{color:#dc2626;font-weight:600}` +
    `.reg-tbl .label{color:#6b7280;font-weight:600;white-space:nowrap}` +
    `.reg-tbl a{color:#2563eb;text-decoration:underline}` +
    `</style>`;

  let html = css;
  html += `<div style="font-size:14px;font-weight:700;margin-bottom:4px">${esc(t(titleKey))}</div>`;

  html += `<table class="reg-tbl">`;
  html += `<tr><td class="label">HSD</td><td>${esc(data.hsd_id)}</td></tr>`;
  if (data.title) html += `<tr><td class="label">Title</td><td>${esc(data.title)}</td></tr>`;
  if (data.status) html += `<tr><td class="label">Status</td><td>${esc(data.status)}</td></tr>`;
  if (data.component) html += `<tr><td class="label">Component</td><td>${esc(data.component)}</td></tr>`;
  if (isGop && data.gop_platform) html += `<tr><td class="label">GOP Platform</td><td><strong>${esc(data.gop_platform)}</strong></td></tr>`;
  html += `<tr><td class="label">Is Regression</td><td><strong>${esc(isReg)}</strong></td></tr>`;
  const failSrc = data.driver_version_fail_source ? ` <span style="font-size:10px;color:#9ca3af">(from: ${esc(data.driver_version_fail_source)})</span>` : "";
  const versionLabel = isGop ? "GOP Version" : "Driver Version";
  html += `<tr><td class="label">Fail ${versionLabel}</td><td class="fail">${esc(failV)}${failSrc}</td></tr>`;
  if (foundInV) html += `<tr><td class="label">Found In Version (Fail)</td><td class="fail">${esc(foundInV)}</td></tr>`;
  html += `<tr><td class="label">Last Passing BKC (Pass)</td><td class="pass">${esc(passV)}</td></tr>`;
  if (fixedV) html += `<tr><td class="label">Fixed In Version</td><td>${esc(fixedV)}</td></tr>`;
  html += `</table>`;

  if (qbData && qbData.ok) {
    const qbRows = formatQbBuilds(qbData, failV, passV, fixedV, foundInV);
    if (qbRows.length > 0) {
      html += `<div style="font-size:13px;font-weight:700;margin:8px 0 4px">QuickBuild ${isGop ? "GOP" : "prod-hini-releases"}</div>`;
      html += `<table class="reg-tbl">`;
      html += `<tr><th></th><th>${isGop ? "GOP Version" : "Driver Version"}</th><th>${isGop ? "GOP CI Build" : "CI-Master"}</th><th>Build Version</th></tr>`;
      for (const r of qbRows) {
        const cls = r.role === "Pass" ? "pass" : r.role === "Fix" ? "pass" : "fail";
        const cpNote = r.cherry_pick_from ? `<br><span style="font-size:10px;color:#6b7280">(cherry-pick from ${esc(r.cherry_pick_from)})</span>` : "";
        const bcNote = r.is_bugcheck ? `<br><span style="font-size:10px;color:#b45309;font-weight:600">⚠ Bugcheck Driver</span>` : "";
        const sameCI = qbRows.filter(x => x.ci_master === r.ci_master).length > 1;
        const prNote = sameCI && r.revenue_pr ? `<br><span style="font-size:10px;color:#6b7280">revenue-pr-${esc(r.revenue_pr)}</span>` : "";
        html += `<tr>`;
        html += `<td class="${cls}">${esc(r.role)}</td>`;
        html += `<td>${esc(r.version)}</td>`;
        if (isGop) {
          const ciUrl = r.ci_build_id ? `https://ubit-gfx.intel.com/build/${esc(r.ci_build_id)}` : "";
          const ciLabel = ciUrl
            ? `<a href="${ciUrl}" target="_blank"><strong>${esc(r.ci_master)}</strong></a>`
            : `<strong>${esc(r.ci_master)}</strong>`;
          html += `<td>${ciLabel}${cpNote}${bcNote}${prNote}</td>`;
          const prodUrl = r.build_id ? `https://ubit-gfx.intel.com/build/${esc(r.build_id)}` : "";
          const prodLabel = esc(r.build);
          html += `<td style="font-size:11px;word-break:break-all">${prodUrl ? `<a href="${prodUrl}" target="_blank">${prodLabel}</a>` : prodLabel}</td>`;
        } else {
          const ciUrl = r.ci_build_id ? `https://ubit-gfx.intel.com/build/${esc(r.ci_build_id)}` : "";
          const ciLabel = ciUrl
            ? `<a href="${ciUrl}" target="_blank"><strong>${esc(r.ci_master)}</strong></a>`
            : `<strong>${esc(r.ci_master)}</strong>`;
          html += `<td>${ciLabel}${cpNote}${bcNote}${prNote}</td>`;
          const buildUrl = r.build_id ? `https://ubit-gfx.intel.com/build/${esc(r.build_id)}` : "";
          const buildLabel = esc(r.build);
          const commitsBtn = r.build_id
            ? `<br><button class="qb-commits-btn" data-build-id="${esc(r.build_id)}" style="margin-top:4px;font-size:10px;padding:2px 6px;cursor:pointer;border:1px solid #d1d5db;border-radius:4px;background:#f9fafb;color:#374151">Show Commits</button><div class="qb-commits-result" data-build-id="${esc(r.build_id)}" style="display:none;margin-top:4px"></div>`
            : "";
          html += `<td style="font-size:11px;word-break:break-all">${buildUrl ? `<a href="${buildUrl}" target="_blank">${buildLabel}</a>` : buildLabel}${commitsBtn}</td>`;
        }
        html += `</tr>`;
      }
      html += `</table>`;
    } else {
      html += `<div style="color:#6b7280;font-size:12px;margin-top:6px">No matching builds found</div>`;
    }
    if (qbData && qbData._debug && qbData._debug.length > 0) {
      const hasEmptyCiMaster = qbRows && qbRows.some(r => !r.ci_master || r.ci_master === "N/A");
      const noBuilds = !qbRows || qbRows.length === 0;
      if (noBuilds || hasEmptyCiMaster) {
        const dbgJson = JSON.stringify(qbData._debug, null, 2);
        html += `<details style="margin:4px 0;font-size:11px;color:#6b7280"><summary>🔍 QB Debug (${qbData._debug.length} entries)</summary><pre style="background:#f9f9f9;padding:4px;white-space:pre-wrap;max-height:400px;overflow:auto">${esc(dbgJson)}</pre></details>`;
      }
    }
    if (qbUrl) {
      html += `<div style="font-size:11px;margin-top:4px">`;
      html += `<a href="https://ubit-gfx.intel.com/dashboard/7931" target="_blank">Open GFX Driver QuickBuild</a>`;
      html += ` &nbsp;|&nbsp; `;
      html += `<a href="https://ubit-gfx.intel.com/dashboard/8078" target="_blank">Open GOP QuickBuild</a>`;
      html += `</div>`;
    }
  }

  html += `<div style="margin-top:8px"><button class="reg-reenter-versions-btn" style="font-size:11px;padding:4px 10px;cursor:pointer;border:1px solid #9ca3af;border-radius:4px;background:#f9fafb;color:#374151">✏️ Re-enter Pass/Fail Versions</button></div>`;

  return html;
}

// ── Shared HTML message helper ────────────────────────────────────────────────

function addHtmlMessage(html) {
  const box = document.getElementById("messages");
  const empty = box.querySelector(".empty-state");
  if (empty) empty.remove();
  const el = document.createElement("div");
  el.className = "message assistant";
  el.innerHTML = html;
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
  return el;
}

// ── Regression progress bar ───────────────────────────────────────────────────

function _setRegProgress(pct, text) {
  const container = document.getElementById("regressionProgressContainer");
  const bar = document.getElementById("regressionProgressBar");
  const label = document.getElementById("regressionProgressText");
  const pctEl = document.getElementById("regressionProgressPct");
  if (pct < 0) {
    container.classList.remove("show");
    bar.style.width = "0%";
    bar.classList.remove("indeterminate");
    return;
  }
  container.classList.add("show");
  bar.classList.remove("indeterminate");
  bar.style.width = pct + "%";
  pctEl.textContent = pct + "%";
  if (text) label.textContent = text;
}

// ── Public entry points ───────────────────────────────────────────────────────

async function checkGfxRegression() {
  await _checkRegression("gfx");
}

async function checkGopRegression() {
  await _checkRegression("gop");
}

// ── Re-enter versions button binding ─────────────────────────────────────────

function _bindReenterVersionsBtn(msgEl, data, fixV, foundInV, buildType) {
  const btn = msgEl.querySelector(".reg-reenter-versions-btn");
  if (!btn) return;
  const isGopType = buildType === "gop";
  btn.addEventListener("click", async () => {
    const opts = isGopType
      ? { title: "GOP Version", msg: "Re-enter the Pass/Fail GOP version:", failLabel: "❌ Fail GOP Version", passLabel: "✅ Last Passing Version", failPlaceholder: "e.g. 60 or 26.0.60", passPlaceholder: "e.g. 60 or 26.0.60" }
      : { title: "Driver Version", msg: "Re-enter the Pass/Fail driver version:", failPlaceholder: "e.g. 101.6651", passPlaceholder: "e.g. 101.6650" };
    const newVersions = await showVersionInputOverlay(
      data.driver_version_fail || "",
      data.last_passing_bkc || "",
      opts
    );
    if (!newVersions) return;
    if (newVersions.fail) data.driver_version_fail = newVersions.fail;
    if (newVersions.pass) data.last_passing_bkc = newVersions.pass;
    const failV2 = data.driver_version_fail || "";
    const passV2 = data.last_passing_bkc || "";
    btn.disabled = true;
    btn.textContent = "⏳ Searching\u2026";
    try {
      // ── Check driver history for exact version match (same HSD first, then cross-HSD) ──
      const histList = await _historyListForHsd(activeHsdId, buildType);
      let histMatch = (histList.records || []).find(rec =>
        rec.hsd_data?.driver_version_fail === failV2 &&
        rec.hsd_data?.last_passing_bkc === passV2
      );
      if (!histMatch) {
        // Cross-HSD: any record with matching fail/pass versions
        const allHist = await _historyListAll(buildType);
        histMatch = (allHist.records || []).find(rec =>
          rec.hsd_data?.driver_version_fail === failV2 &&
          rec.hsd_data?.last_passing_bkc === passV2
        );
      }
      if (histMatch) {
        msgEl.innerHTML = buildRegressionTable(data, histMatch.qb_data, buildType);
        // Save under current HSD so next Re-enter hits the same-HSD path
        const newRecId = await _historySave(activeHsdId, buildType, data, histMatch.qb_data);
        if (histMatch.qb_data && !histMatch.qb_data._from_cache)
          _buildCacheSave(buildType, histMatch.qb_data);
        _addCacheBanner(msgEl, activeHsdId, buildType, newRecId || histMatch.record_id,
          () => _checkRegression(buildType, true));
        _bindQbCommitsButtons();
        _bindReenterVersionsBtn(msgEl, data, fixV, foundInV, buildType);
        return;
      }

      // ── Check per-version build cache first (same as _checkRegression) ──────
      let newQbData;
      const versionsNeeded2 = [failV2, passV2, fixV, foundInV].filter(Boolean);
      const cacheHit2 = await _buildCacheLookup(versionsNeeded2, buildType);
      const assembled2 = _assembleQbFromCache(failV2, passV2, fixV, foundInV, cacheHit2.found || {});
      if (assembled2) {
        newQbData = assembled2;
      } else {
        newQbData = await showQbLoginOverlay(failV2, passV2, fixV, buildType, foundInV, data.gop_platform || "");
      }
      msgEl.innerHTML = buildRegressionTable(data, newQbData && newQbData.ok ? newQbData : null, buildType);
      if (newQbData && newQbData.ok) {
        _historySave(activeHsdId, buildType, data, newQbData);
        if (!newQbData._from_cache) _buildCacheSave(buildType, newQbData);
      }
      _bindQbCommitsButtons();
      _bindReenterVersionsBtn(msgEl, data, fixV, foundInV, buildType);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "✏️ Re-enter Pass/Fail Versions";
    } finally {
      _setRegProgress(-1);
    }
  }, { once: true });
}

// ── Show Commits button binding (GFX) ─────────────────────────────────────────

function _bindQbCommitsButtons() {
  document.querySelectorAll(".qb-commits-btn").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      const buildId = btn.dataset.buildId;
      const resultDiv = document.querySelector(`.qb-commits-result[data-build-id="${buildId}"]`);
      if (!resultDiv) return;

      if (resultDiv.style.display !== "none") {
        resultDiv.style.display = "none";
        btn.textContent = "Show Commits";
        return;
      }

      btn.disabled = true;
      btn.textContent = "Loading…";
      try {
        const resp = await fetch(`${BRIDGE_BASE_URL}/qb-commits`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ build_id: buildId }),
        });
        const data = await resp.json();
        const lcLink = data._list_changes_url ? `<div style="margin-top:4px"><a href="${data._list_changes_url}" target="_blank" style="font-size:10px;color:#2563eb">View Changes on QB ↗</a></div>` : "";
        if (data.ok && data.commits && data.commits.length > 0) {
          const esc = (s) => String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
          let tbl = `<table style="font-size:10px;border-collapse:collapse;width:100%;margin-top:4px">`;
          tbl += `<tr style="background:#f3f4f6"><th style="padding:2px 5px;text-align:left;border:1px solid #e5e7eb">Rev</th><th style="padding:2px 5px;text-align:left;border:1px solid #e5e7eb">Author</th><th style="padding:2px 5px;text-align:left;border:1px solid #e5e7eb">Date</th><th style="padding:2px 5px;text-align:left;border:1px solid #e5e7eb">Message</th></tr>`;
          for (const c of data.commits) {
            tbl += `<tr>`;
            tbl += `<td style="padding:2px 5px;border:1px solid #e5e7eb;white-space:nowrap;font-family:monospace">${esc(c.rev.slice(0, 10))}</td>`;
            tbl += `<td style="padding:2px 5px;border:1px solid #e5e7eb;white-space:nowrap">${esc(c.author)}</td>`;
            tbl += `<td style="padding:2px 5px;border:1px solid #e5e7eb;white-space:nowrap">${esc(c.date)}</td>`;
            tbl += `<td style="padding:2px 5px;border:1px solid #e5e7eb">${esc(c.comment)}</td>`;
            tbl += `</tr>`;
          }
          tbl += `</table>`;
          resultDiv.innerHTML = tbl + lcLink;
        } else {
          resultDiv.innerHTML = lcLink;
        }
        resultDiv.style.display = "block";
        btn.textContent = "Hide Commits";
      } catch (err) {
        resultDiv.style.display = "none";
        btn.textContent = "Show Commits";
      }
      btn.disabled = false;
    });
  });
}

// ── Driver History helpers ────────────────────────────────────────────────────

async function _historyListForHsd(hsdId, buildType) {
  try {
    const r = await fetch(
      `${BRIDGE_BASE_URL}/driver-history?hsd_id=${encodeURIComponent(hsdId)}&build_type=${encodeURIComponent(buildType)}&list=1`
    );
    return await r.json();   // {ok, records: [...]}
  } catch { return { ok: false, records: [] }; }
}

async function _historyListAll(buildType) {
  try {
    const r = await fetch(
      `${BRIDGE_BASE_URL}/driver-history?build_type=${encodeURIComponent(buildType)}`
    );
    return await r.json();   // {ok, records: [...]}
  } catch { return { ok: false, records: [] }; }
}

async function _historyLookup(hsdId, buildType) {
  try {
    const r = await fetch(
      `${BRIDGE_BASE_URL}/driver-history?hsd_id=${encodeURIComponent(hsdId)}&build_type=${encodeURIComponent(buildType)}`
    );
    return await r.json();
  } catch { return { ok: false }; }
}

async function _historySave(hsdId, buildType, hsdData, qbData) {
  try {
    const r = await fetch(`${BRIDGE_BASE_URL}/driver-history`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hsd_id: hsdId, build_type: buildType,
                             hsd_data: hsdData, qb_data: qbData }),
    });
    const d = await r.json();
    return d.record_id || null;
  } catch { return null; }
}

async function _historyDelete(recordId, buildType) {
  try {
    await fetch(`${BRIDGE_BASE_URL}/driver-history/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ record_id: recordId, build_type: buildType }),
    });
  } catch { /* non-critical */ }
}

// ── Per-version build cache helpers ──────────────────────────────────────────

async function _buildCacheLookup(versions, buildType) {
  try {
    const r = await fetch(`${BRIDGE_BASE_URL}/build-cache/lookup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ versions, build_type: buildType }),
    });
    return await r.json();
  } catch { return { ok: false, found: {}, missing: versions }; }
}

async function _buildCacheSave(buildType, qbData) {
  const entries = [];
  for (const key of ["fail_build", "pass_build", "fix_build", "found_in_build"]) {
    const b = qbData?.[key];
    if (b && b.version) entries.push({ version: String(b.version), build_data: b });
  }
  if (!entries.length) return;
  try {
    await fetch(`${BRIDGE_BASE_URL}/build-cache/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ build_type: buildType, entries }),
    });
  } catch { /* non-critical */ }
}

function _assembleQbFromCache(failV, passV, fixV, foundInV, found) {
  if (failV && !found[failV]) return null;
  if (passV && !found[passV]) return null;
  return {
    ok: true,
    fail_build:     failV    && found[failV]    ? found[failV]    : null,
    pass_build:     passV    && found[passV]    ? found[passV]    : null,
    fix_build:      fixV     && found[fixV]     ? found[fixV]     : null,
    found_in_build: foundInV && found[foundInV] ? found[foundInV] : null,
    _from_cache: true,
  };
}

function _addCacheBanner(msgEl, hsdId, buildType, recordId, onRecheck) {
  const banner = document.createElement("div");
  banner.style.cssText =
    "display:flex;align-items:center;gap:8px;padding:5px 10px;" +
    "background:#fef9c3;border:1px solid #fde68a;border-radius:6px;" +
    "font-size:11.5px;color:#92400e;margin-bottom:4px;";
  banner.innerHTML =
    `<span>⚡ <strong>From cache</strong> · ${hsdId} (${buildType.toUpperCase()})</span>` +
    `<button style="margin-left:auto;padding:2px 8px;font-size:11px;` +
    `border:1px solid #d97706;border-radius:4px;background:#fffbeb;` +
    `cursor:pointer;">🔄 Re-check</button>` +
    `<button style="padding:2px 8px;font-size:11px;` +
    `border:1px solid #fca5a5;border-radius:4px;background:#fff;` +
    `color:#991b1b;cursor:pointer;">🗑 Remove</button>`;
  banner.querySelectorAll("button")[0].addEventListener("click", async () => {
    msgEl.remove(); banner.remove();
    await _historyDelete(recordId, buildType);
    onRecheck();
  });
  banner.querySelectorAll("button")[1].addEventListener("click", async () => {
    msgEl.remove(); banner.remove();
    await _historyDelete(recordId, buildType);
  });
  msgEl.parentNode.insertBefore(banner, msgEl);
}

// ── Main regression check flow ────────────────────────────────────────────────

async function _checkRegression(buildType, forceRefresh = false) {
  if (!activeHsdId || isSending) return;
  isSending = true;
  try {
    const isGop = buildType === "gop";

    // ── 1. HSD-level history cache (skip when forceRefresh) ─────────────────
    if (!forceRefresh) {
      _setRegProgress(5, "⚡ Checking driver history...");
      const hit = await _historyLookup(activeHsdId, buildType);
      if (hit.ok && hit.cached && hit.record) {
        const rec = hit.record;
        _setRegProgress(100, "Loaded from cache");
        const msgEl = addHtmlMessage(buildRegressionTable(rec.hsd_data, rec.qb_data, buildType));
        _addCacheBanner(msgEl, activeHsdId, buildType, rec.record_id || activeHsdId,
          () => _checkRegression(buildType, true));
        _bindQbCommitsButtons();
        const fixV = rec.hsd_data?.fixed_in_version || "";
        const foundInV = rec.hsd_data?.found_in_version || "";
        if (msgEl) _bindReenterVersionsBtn(msgEl, rec.hsd_data, fixV, foundInV, buildType);
        // Backfill per-version build cache so Re-enter can skip QB for these builds
        if (rec.qb_data && !rec.qb_data._from_cache) _buildCacheSave(buildType, rec.qb_data);
        setStatus("ready", t("ready"));
        return;
      }
    }

    _setRegProgress(0, t(isGop ? "regGopProgressHsd" : "regProgressHsd"));
    setStatus("loading", t(isGop ? "gopRegressionChecking" : "regressionChecking"));

    _setRegProgress(10, t(isGop ? "regGopProgressHsd" : "regProgressHsd"));
    const resp = await fetch(`${BRIDGE_BASE_URL}/regression-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hsd_id: activeHsdId, build_type: buildType }),
    });
    _setRegProgress(30);
    const data = await resp.json();

    if (!data.ok) {
      addSystemMessage(tFormat("regressionFail", { error: data.error || "Unknown" }));
      setStatus("error", tFormat("regressionFail", { error: data.error || "Unknown" }));
      return;
    }

    let failV = data.driver_version_fail || "";
    let passV = data.last_passing_bkc || "";
    const fixV = data.fixed_in_version || "";
    const foundInV = data.found_in_version || "";

    if (!failV || !passV) {
      _setRegProgress(33, "版本資訊不完整，請手動填寫...");
      const _verOpts = isGop
        ? { title: "GOP Version", failLabel: "❌ Fail GOP Version", passLabel: "✅ Last Passing Version", failPlaceholder: "e.g. 60 or 26.0.60", passPlaceholder: "e.g. 60 or 26.0.60" }
        : {};
      const manualVersions = await showVersionInputOverlay(failV, passV, _verOpts);
      if (manualVersions === null) {
        addHtmlMessage(buildRegressionTable(data, null, buildType));
        setStatus("ready", t("ready"));
        return;
      }
      if (manualVersions.fail) { failV = manualVersions.fail; data.driver_version_fail = failV; }
      if (manualVersions.pass) { passV = manualVersions.pass; data.last_passing_bkc = passV; }
    }

    let qbData = null;
    if (failV || passV || fixV || foundInV) {
      // ── 1. Cross-HSD History lookup by version (skip on forceRefresh) ────────
      if (!forceRefresh) {
        _setRegProgress(32, "⚡ Checking driver history by version...");
        const allHist = await _historyListAll(buildType);
        const versionMatch = (allHist.records || []).find(rec =>
          rec.hsd_data?.driver_version_fail === failV &&
          rec.hsd_data?.last_passing_bkc === passV
        );
        if (versionMatch) {
          _setRegProgress(90, "⚡ Result found in version history — skipping QB search");
          qbData = versionMatch.qb_data;
        }
      }

      if (!qbData) {
        // ── 2. Per-version build cache ────────────────────────────────────────
        const versionsNeeded = [failV, passV, fixV, foundInV].filter(Boolean);
        _setRegProgress(33, "⚡ Checking build version history...");
        const cacheHit = await _buildCacheLookup(versionsNeeded, buildType);
        const assembled = _assembleQbFromCache(failV, passV, fixV, foundInV, cacheHit.found || {});

        if (assembled) {
          _setRegProgress(90, "⚡ Build versions loaded from history — skipping QB search");
          qbData = assembled;
        } else {
          // ── 3. Fall back to full QB search ─────────────────────────────────
          _setRegProgress(35, t("regProgressQbLogin"));
          qbData = await showQbLoginOverlay(failV, passV, fixV, buildType, foundInV, data.gop_platform || "");
        }
      }
    }

    _setRegProgress(95, t("regProgressDone"));
    let msgEl;
    if (qbData && qbData.ok) {
      msgEl = addHtmlMessage(buildRegressionTable(data, qbData, buildType));
      _historySave(activeHsdId, buildType, data, qbData);
      if (!qbData._from_cache) _buildCacheSave(buildType, qbData);
    } else {
      msgEl = addHtmlMessage(buildRegressionTable(data, null, buildType));
      if (qbData === null && (failV || passV)) {
        const manualUrl = isGop ? "https://ubit-gfx.intel.com/dashboard/8078" : "https://ubit-gfx.intel.com/dashboard/7931";
        addMessage("assistant", `━━ CI-Master Lookup ━━\nPlease check QuickBuild manually:\n${manualUrl}`);
      }
    }

    _bindQbCommitsButtons();
    if (msgEl) _bindReenterVersionsBtn(msgEl, data, fixV, foundInV, buildType);

    setStatus("ready", t("ready"));
  } catch (err) {
    const msg = err.message || String(err);
    addSystemMessage(tFormat("regressionFail", { error: msg }));
    setStatus("error", tFormat("regressionFail", { error: msg }));
  } finally {
    isSending = false;
    _setRegProgress(-1);
  }
}

// ── Driver History Panel ──────────────────────────────────────────────────────

async function showDriverHistoryPanel() {
  const panel = document.getElementById("driver-history-panel");
  if (!panel) return;
  panel.style.display = "flex";
  const activeTab = panel.querySelector(".dh-tab.active");
  const buildType = activeTab ? activeTab.dataset.type : "gfx";
  await _renderHistoryList(buildType);
}

async function _renderHistoryList(buildType) {
  const listEl = document.getElementById("dh-list");
  if (!listEl) return;
  listEl.innerHTML = `<div style="padding:16px;color:#6b7280;font-size:13px;">Loading…</div>`;

  let records = [];
  try {
    const r = await fetch(
      `${BRIDGE_BASE_URL}/driver-history?build_type=${encodeURIComponent(buildType)}`
    );
    const d = await r.json();
    records = d.records || [];
  } catch {
    listEl.innerHTML = `<div style="padding:16px;color:#ef4444;">Failed to load history.</div>`;
    return;
  }

  if (!records.length) {
    listEl.innerHTML = `<div style="padding:16px;color:#6b7280;font-size:13px;">No ${buildType.toUpperCase()} history yet.</div>`;
    return;
  }

  listEl.innerHTML = "";
  for (const rec of records) {
    const hsd = rec.hsd_data || {};
    const failV = hsd.driver_version_fail || "—";
    const passV = hsd.last_passing_bkc || "—";
    const qbOk = rec.qb_data?.ok;
    const ts = rec.timestamp ? rec.timestamp.replace("T", " ") : "—";
    const row = document.createElement("div");
    row.style.cssText =
      "display:flex;align-items:flex-start;gap:10px;padding:10px 12px;" +
      "border-bottom:1px solid #e5e7eb;cursor:pointer;" +
      "transition:background 0.15s;";
    row.onmouseenter = () => row.style.background = "#f9fafb";
    row.onmouseleave = () => row.style.background = "";
    row.innerHTML =
      `<div style="flex:1;min-width:0;">` +
      `<div style="font-weight:600;font-size:13px;color:#111827;">HSD ${rec.hsd_id}</div>` +
      `<div style="font-size:11.5px;color:#6b7280;margin-top:2px;">` +
      `Fail: <b>${failV}</b> · Pass: <b>${passV}</b>` +
      `${qbOk ? ' · <span style="color:#16a34a;">✔ QB</span>' : ''}` +
      `</div>` +
      `<div style="font-size:10.5px;color:#9ca3af;margin-top:2px;">${ts}</div>` +
      `</div>` +
      `<div style="display:flex;flex-direction:column;gap:4px;">` +
      `<button class="dh-load-btn" data-hsdid="${rec.hsd_id}" style="` +
      `font-size:11px;padding:3px 8px;border:1px solid #3b82f6;` +
      `border-radius:4px;background:#eff6ff;color:#1d4ed8;cursor:pointer;">Load</button>` +
      `<button class="dh-del-btn" data-hsdid="${rec.hsd_id}" style="` +
      `font-size:11px;padding:3px 8px;border:1px solid #fca5a5;` +
      `border-radius:4px;background:#fff;color:#991b1b;cursor:pointer;">Delete</button>` +
      `</div>`;

    row.querySelector(".dh-load-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      document.getElementById("driver-history-panel").style.display = "none";
      const msgEl = addHtmlMessage(buildRegressionTable(rec.hsd_data, rec.qb_data, buildType));
      _addCacheBanner(msgEl, rec.hsd_id, buildType, rec.record_id, () => _checkRegression(buildType, true));
      _bindQbCommitsButtons();
    });

    row.querySelector(".dh-del-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      await _historyDelete(rec.record_id, buildType);
      row.remove();
      if (!listEl.children.length)
        listEl.innerHTML = `<div style="padding:16px;color:#6b7280;font-size:13px;">No ${buildType.toUpperCase()} history yet.</div>`;
    });

    listEl.appendChild(row);
  }
}

    const isReg = data.is_regression || "Unknown";

    let failV = data.driver_version_fail || "";
    let passV = data.last_passing_bkc || "";
    const fixV = data.fixed_in_version || "";
    const foundInV = data.found_in_version || "";

    if (!failV || !passV) {
      _setRegProgress(33, "版本資訊不完整，請手動填寫...");
      const _verOpts = isGop
        ? { title: "GOP Version", failLabel: "❌ Fail GOP Version", passLabel: "✅ Last Passing Version", failPlaceholder: "e.g. 60 or 26.0.60", passPlaceholder: "e.g. 60 or 26.0.60" }
        : {};
      const manualVersions = await showVersionInputOverlay(failV, passV, _verOpts);
      if (manualVersions === null) {
        _setRegProgress(100, t("regProgressDone"));
        addHtmlMessage(buildRegressionTable(data, null, buildType));
        await new Promise((r) => setTimeout(r, 600));
        _setRegProgress(-1);
        setStatus("ready", t("ready"));
        return;
      }
      if (manualVersions.fail) { failV = manualVersions.fail; data.driver_version_fail = failV; }
      if (manualVersions.pass) { passV = manualVersions.pass; data.last_passing_bkc = passV; }
    }

    let qbData = null;
    if (failV || passV || fixV || foundInV) {
      _setRegProgress(35, t("regProgressQbLogin"));
      qbData = await showQbLoginOverlay(failV, passV, fixV, buildType, foundInV, data.gop_platform || "");
      _setRegProgress(90);
    }

    _setRegProgress(95, t("regProgressDone"));
    let msgEl;
    if (qbData && qbData.ok) {
      msgEl = addHtmlMessage(buildRegressionTable(data, qbData, buildType));
    } else {
      msgEl = addHtmlMessage(buildRegressionTable(data, null, buildType));
      if (qbData === null && (failV || passV)) {
        const manualUrl = isGop ? "https://ubit-gfx.intel.com/dashboard/8078" : "https://ubit-gfx.intel.com/dashboard/7931";
        addMessage("assistant", `━━ CI-Master Lookup ━━\nPlease check QuickBuild manually:\n${manualUrl}`);
      }
    }

    _bindQbCommitsButtons();
    if (msgEl) {
      _bindReenterVersionsBtn(msgEl, data, fixV, foundInV, buildType);
    }

    _setRegProgress(100, t("regProgressDone"));
    await new Promise((r) => setTimeout(r, 600));
    _setRegProgress(-1);
    setStatus("ready", t("ready"));
  } catch (err) {
    _setRegProgress(-1);
    const msg = err.message || String(err);
    addSystemMessage(tFormat("regressionFail", { error: msg }));
    setStatus("error", tFormat("regressionFail", { error: msg }));
  }
}
