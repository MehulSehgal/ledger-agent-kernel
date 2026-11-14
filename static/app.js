const byId = (id) => document.getElementById(id);
const terminalStates = new Set(["done", "error", "cancelled"]);
const eventNames = [
  "step", "model_call", "claim", "budget", "failover", "approval_request",
  "approval_result", "blocked", "result", "error",
];
const stateLabels = {
  idle: "Idle",
  running: "Running",
  "waiting for approval": "Waiting for approval",
  done: "Done",
  error: "Error",
  cancelled: "Cancelled",
};

let mode = "brief";
let runId = null;
let eventSource = null;
let fallbackTimer = null;
let pollTimer = null;
let lastSequence = 0;
let totalUsed = 0;
let budgetCap = 12000;
let usdTotal = 0;
let priceUnverified = false;
let blockedCount = 0;
let activeApproval = null;
let approvalQueue = [];
let approvalTimer = null;
let previousFocus = null;
let activeSidePanel = null;
let sidePanelPreviousFocus = null;
let briefResult = null;
let requestPending = false;
const timelineRows = new Map();
const modelCalls = [];

function setRunState(state) {
  const badge = byId("run-state");
  badge.textContent = stateLabels[state] || state;
  badge.className = `state-badge state-${state.replaceAll(" ", "-")}`;
  byId("cancel-run").disabled = !runId || terminalStates.has(state);
  byId("start-run").disabled = requestPending ||
    (Boolean(runId) && !terminalStates.has(state));
}

function setMode(nextMode) {
  mode = nextMode;
  const briefSelected = mode === "brief";
  byId("brief-tab").setAttribute("aria-selected", String(briefSelected));
  byId("fix-tab").setAttribute("aria-selected", String(!briefSelected));
  byId("brief-tab").tabIndex = briefSelected ? 0 : -1;
  byId("fix-tab").tabIndex = briefSelected ? -1 : 0;
  byId("brief-tab").classList.toggle("is-active", briefSelected);
  byId("fix-tab").classList.toggle("is-active", !briefSelected);
  byId("brief-fields").hidden = !briefSelected;
  byId("fix-fields").hidden = briefSelected;
  byId("start-run").textContent = briefSelected ? "Start brief" : "Start fix";
  byId("token-budget").value = briefSelected ? "12000" : "6000";
}

function createElement(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function resetRunView() {
  closeStream();
  stopPolling();
  runId = null;
  setRunState("idle");
  timelineRows.clear();
  modelCalls.length = 0;
  approvalQueue = [];
  activeApproval = null;
  lastSequence = 0;
  totalUsed = 0;
  usdTotal = 0;
  priceUnverified = false;
  blockedCount = 0;
  briefResult = null;
  byId("timeline-empty")?.remove();
  byId("timeline").replaceChildren();
  byId("brief-result").hidden = true;
  byId("brief-actions").hidden = true;
  byId("brief-bullets").replaceChildren();
  byId("open-question-list").replaceChildren();
  byId("brief-sources").replaceChildren();
  byId("copy-feedback").textContent = "";
  byId("blocked-list").replaceChildren();
  byId("blocked-panel").hidden = true;
  byId("blocked-count").hidden = true;
  byId("failover-banner").hidden = true;
  byId("run-id").textContent = "";
  byId("call-list").replaceChildren(createElement("li", "muted", "No calls yet"));
  byId("price-warning").hidden = true;
  byId("live-usd").textContent = "—";
  byId("savings-row").hidden = true;
  byId("savings-row").classList.remove("savings-negative");
  updateMeter(0, Number(byId("token-budget").value) || budgetCap);
  closeSidePanel();
  closeApprovalDrawer();
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value) || 0);
}

function formatUsd(value) {
  return `$${Number(value).toFixed(6)}`;
}

function updateMeter(used, cap) {
  totalUsed = Math.max(0, Number(used) || 0);
  budgetCap = Math.max(1, Number(cap) || 1);
  const percent = Math.min(100, totalUsed / budgetCap * 100);
  byId("token-total").textContent = formatNumber(totalUsed);
  byId("budget-used").textContent = formatNumber(totalUsed);
  byId("budget-cap").textContent = formatNumber(budgetCap);
  byId("meter-fill").style.width = `${percent}%`;
  byId("meter-track").setAttribute("aria-valuemax", String(budgetCap));
  byId("meter-track").setAttribute("aria-valuenow", String(totalUsed));
}

function setPriceWarning() {
  byId("price-warning").hidden = !priceUnverified;
}

function updateCost(eventCost) {
  if (typeof eventCost === "number" && Number.isFinite(eventCost)) {
    usdTotal += eventCost;
    byId("live-usd").textContent = formatUsd(usdTotal);
  } else {
    priceUnverified = true;
    setPriceWarning();
  }
}

function addTimelineRow(key, { title, detail = "", icon = "·", status = "", tier = null,
  model = "", tokens = "", duration = "—", className = "" }) {
  let row = timelineRows.get(key);
  if (!row) {
    const item = createElement("li", `timeline-item ${className}`.trim());
    const marker = createElement("span", `event-icon ${status}`, icon);
    marker.setAttribute("aria-hidden", "true");
    const content = createElement("div", "timeline-content");
    const top = createElement("div", "timeline-top");
    const heading = createElement("h3", "event-title", title);
    const durationNode = createElement("span", "event-duration", duration);
    top.append(heading);
    if (tier) {
      const badge = createElement("span", `tier-badge tier-${tier}`, tier);
      badge.setAttribute("aria-label", `${tier} model tier`);
      top.append(badge);
    }
    top.append(durationNode);
    const detailNode = createElement("p", "event-detail", detail);
    content.append(top, detailNode);
    item.append(marker, content);
    byId("timeline").append(item);
    row = { item, marker, heading, detailNode, durationNode, content, top };
    timelineRows.set(key, row);
  } else {
    row.heading.textContent = title;
    row.marker.className = `event-icon ${status}`;
    row.marker.textContent = icon;
    row.durationNode.textContent = duration;
    row.detailNode.textContent = detail;
    const badge = row.top.querySelector(".tier-badge");
    if (tier && !badge) {
      const tierBadge = createElement("span", `tier-badge tier-${tier}`, tier);
      tierBadge.setAttribute("aria-label", `${tier} model tier`);
      row.top.insertBefore(tierBadge, row.durationNode);
    } else if (tier && badge) {
      badge.className = `tier-badge tier-${tier}`;
      badge.textContent = tier;
    }
  }
  if (model || tokens) {
    let meta = row.content.querySelector(".event-model");
    if (!meta) {
      meta = createElement("p", "event-model");
      row.content.append(meta);
    }
    meta.textContent = [model, tokens ? `${formatNumber(tokens)} tokens` : ""]
      .filter(Boolean).join(" · ");
  }
  return row;
}

function durationLabel(startedAt, finishedAt) {
  if (!startedAt || !finishedAt) return "—";
  const ms = Math.max(0, new Date(finishedAt).getTime() - new Date(startedAt).getTime());
  if (!Number.isFinite(ms)) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function handleStep(data, timestamp) {
  const key = `step:${data.id || data.title}:${data.title || ""}`;
  const prior = timelineRows.get(key);
  const startedAt = prior?.startedAt || (data.status === "running" ? timestamp : null);
  const finishedAt = data.status === "running" ? null : timestamp;
  const icon = data.status === "ok" ? "✓" : data.status === "fail" ? "!" :
    data.status === "skipped" ? "–" : "";
  const row = addTimelineRow(key, {
    title: data.title || data.id || "Step",
    detail: data.detail || "",
    icon,
    status: data.status || "running",
    duration: durationLabel(startedAt, finishedAt),
  });
  row.startedAt = startedAt;
  row.finishedAt = finishedAt;
}

function handleModelCall(data, sequence) {
  const tokensIn = Number(data.tokens_in) || 0;
  const tokensOut = Number(data.tokens_out) || 0;
  const tokens = tokensIn + tokensOut;
  const key = `model:${sequence}`;
  addTimelineRow(key, {
    title: data.label || "Model call",
    detail: `${formatNumber(tokensIn)} in · ${formatNumber(tokensOut)} out`,
    icon: "•",
    status: "ok",
    tier: data.tier || "local",
    model: data.model || "",
    tokens,
  });
  modelCalls.push({
    label: data.label || "Model call",
    tier: data.tier || "local",
    model: data.model || "",
    tokens,
    cost: typeof data.usd === "number" ? data.usd : null,
  });
  updateCallList();
  updateCost(data.usd);
}

function updateCallList(receiptCalls = null) {
  const calls = Array.isArray(receiptCalls) ? receiptCalls : modelCalls;
  const list = byId("call-list");
  list.replaceChildren();
  if (!calls.length) {
    list.append(createElement("li", "muted", "No calls yet"));
    return;
  }
  for (const call of calls) {
    const item = createElement("li", "call-row");
    const label = createElement("span", "call-name", call.label || "Model call");
    const tokens = call.tokens ?? ((Number(call.in) || 0) + (Number(call.out) || 0));
    const cost = typeof call.usd === "number" ? call.usd : call.cost;
    const amount = createElement("span", "call-cost",
      `${formatNumber(tokens)} tok${typeof cost === "number" ? ` · ${formatUsd(cost)}` : ""}`);
    const model = createElement(
      "span",
      `call-model tier-${call.tier || "local"}`,
      `${call.model || "offline"} · ${call.tier || "local"}`,
    );
    item.append(label, amount, model);
    list.append(item);
  }
}

function handleClaim(data, sequence) {
  const accepted = data.status === "verified";
  addTimelineRow(`claim:${sequence}`, {
    title: accepted ? `Verified claim ${data.id || ""}` : `Rejected claim ${data.id || ""}`,
    detail: data.text || data.reason || "",
    icon: accepted ? "✓" : "!",
    status: accepted ? "ok" : "fail",
    className: accepted ? "claim-row" : "claim-row",
  });
}

const checkLabels = {
  fetched: "Source was fetched",
  date_in_window: "Source date is in the 30-day window",
  quote_found: "Quote appears in source text",
  numbers_match: "Claim numbers match the quote",
  supported: "Claim is supported by its quote",
};

function appendHighlightedQuote(container, sourceText, quote) {
  const source = String(sourceText || "");
  const target = String(quote || "");
  const index = source.toLocaleLowerCase().indexOf(target.toLocaleLowerCase());
  container.replaceChildren();
  if (!target || index < 0) {
    container.textContent = source || "Source text unavailable.";
    return;
  }
  container.append(document.createTextNode(source.slice(0, index)));
  const mark = createElement("mark", "", source.slice(index, index + target.length));
  container.append(mark, document.createTextNode(source.slice(index + target.length)));
}

function renderEvidenceChecks(checks = {}) {
  const list = byId("evidence-checks");
  list.replaceChildren();
  for (const [key, label] of Object.entries(checkLabels)) {
    const passed = checks[key] === true;
    const row = createElement("li", `verification-check ${passed ? "pass" : "fail"}`);
    row.append(
      createElement("strong", "", passed ? "✓" : "✗"),
      createElement("span", "", label),
    );
    list.append(row);
  }
}

function safeWebUrl(value) {
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") &&
      !isReservedExampleHost(url.hostname) ? url.href : null;
  } catch {
    return null;
  }
}

function isReservedExampleHost(host) {
  const hostname = String(host || "").toLowerCase().replace(/\.$/, "");
  return ["example.com", "example.org", "example.net", "example.test", "example.invalid"]
    .some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
}

function isReservedExampleUrl(value) {
  try {
    return isReservedExampleHost(new URL(value).hostname);
  } catch {
    return false;
  }
}

function openEvidence(sourceNumber, evidence, checks) {
  if (!briefResult) return;
  const source = (briefResult.sources || []).find((item) => item.n === sourceNumber);
  if (!source) return;
  byId("evidence-title").textContent = source.title || `Source ${source.n}`;
  const urlNode = byId("evidence-url");
  urlNode.replaceChildren();
  const safeUrl = safeWebUrl(source.url);
  if (safeUrl) {
    const link = createElement("a", "", source.url);
    link.href = safeUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    urlNode.append(link);
  } else if (isReservedExampleUrl(source.url)) {
    urlNode.textContent = "Offline replay source (no live article URL)";
  } else {
    urlNode.textContent = source.url || "Unavailable";
  }
  byId("evidence-date").textContent = source.date || "Date unavailable";
  byId("evidence-kind").textContent = source.source_kind || "Unknown";
  const hasClaimEvidence = Boolean(evidence);
  byId("evidence-quote-section").hidden = !hasClaimEvidence;
  byId("evidence-checks-section").hidden = !hasClaimEvidence;
  if (hasClaimEvidence) {
    const quote = evidence.quote || "";
    byId("evidence-quote").textContent = quote || "No quote was supplied.";
    appendHighlightedQuote(byId("evidence-source-text"), source.text, quote);
    renderEvidenceChecks(checks || evidence.checks || {});
  } else {
    byId("evidence-source-text").textContent = source.text || "Source text unavailable.";
    byId("evidence-checks").replaceChildren();
  }
  openSidePanel("evidence-overlay", "evidence-panel", "close-evidence");
}

function renderRejectedClaims(result) {
  const audit = result.audit || {};
  const rejected = [
    ...(audit.rejected_claims || []),
    ...(audit.rejected_bullets || []).map((item) => ({
      claim: item.text,
      reason: item.reason,
    })),
  ];
  byId("rejected-count").textContent = String(rejected.length);
  const groups = new Map();
  for (const item of rejected) {
    const reason = item.reason || "Unspecified";
    if (!groups.has(reason)) groups.set(reason, []);
    groups.get(reason).push(item);
  }
  const container = byId("rejected-groups");
  container.replaceChildren();
  if (!groups.size) {
    container.append(createElement("p", "rejected-empty", "No claims were rejected."));
    return;
  }
  for (const [reason, items] of [...groups.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const section = createElement("section", "rejected-group");
    section.append(createElement("h3", "", `${reason} (${items.length})`));
    const list = createElement("ul");
    for (const item of items) {
      const row = createElement("li", "rejected-claim");
      if (item.label === "red-team test claim") {
        row.append(createElement("span", "red-team-label", "Red-team test claim"));
      }
      row.append(createElement("p", "", item.claim || item.text || "Claim text unavailable."));
      list.append(row);
    }
    section.append(list);
    container.append(section);
  }
}

function renderBriefResult(result) {
  briefResult = result;
  const bullets = Array.isArray(result.bullets) ? result.bullets : [];
  const list = byId("brief-bullets");
  list.replaceChildren();
  byId("brief-result-heading").textContent =
    [result.company, result.meeting].filter(Boolean).join(" · ") || "Brief";
  byId("brief-result").hidden = false;
  byId("brief-empty").hidden = bullets.length > 0;
  if (!bullets.length) {
    byId("brief-empty").textContent = Number(result.audit?.accepted) === 0
      ? "No claim passed verification, so the strong model was never called."
      : "No synthesized bullet passed verification.";
  }
  list.hidden = bullets.length === 0;
  for (const [index, bullet] of bullets.entries()) {
    const item = createElement("li", "brief-bullet");
    const text = createElement("p", "brief-bullet-text", bullet.text || "");
    item.append(text);
    const citations = createElement("span", "bullet-citations");
    for (const sourceNumber of bullet.cites || []) {
      const footnote = createElement("button", "source-footnote", `[${sourceNumber}]`);
      footnote.type = "button";
      footnote.dataset.sourceNumber = String(sourceNumber);
      footnote.dataset.bulletIndex = String(index);
      footnote.setAttribute("aria-label", `Open source ${sourceNumber} evidence`);
      citations.append(footnote);
    }
    text.append(citations);
    const checks = bullet.checks || {};
    const passed = Object.values(checks).filter((value) => value === true).length;
    const chip = createElement("button", "verification-chip", `✓ Verified · ${passed}/${Object.keys(checkLabels).length} checks`);
    chip.type = "button";
    chip.dataset.bulletIndex = String(index);
    chip.dataset.openEvidence = "true";
    chip.setAttribute("aria-label", `Open verification evidence, ${passed} of ${Object.keys(checkLabels).length} checks passed`);
    item.append(chip);
    list.append(item);
  }

  const questionList = byId("open-question-list");
  questionList.replaceChildren();
  for (const question of result.open_questions || []) {
    const item = createElement("li", "open-question");
    const text = String(question);
    const match = text.match(/^inference(?:\s+\[[^\]]+\])?:\s*(.*)$/i);
    item.append(
      createElement("span", "inference-tag", "Inference"),
      createElement("em", "", match ? match[1] : text),
    );
    questionList.append(item);
  }
  byId("open-questions").hidden = questionList.childElementCount === 0;

  const sourcesList = byId("brief-sources");
  sourcesList.replaceChildren();
  for (const source of result.sources || []) {
    const item = createElement("li");
    const safeUrl = safeWebUrl(source.url);
    if (safeUrl) {
      const link = createElement("a", "", source.title || source.url || `Source ${source.n}`);
      link.href = safeUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
    } else {
      const preview = createElement(
        "button",
        "source-preview",
        source.title || source.url || `Source ${source.n}`,
      );
      preview.type = "button";
      preview.dataset.sourceNumber = String(source.n);
      preview.setAttribute("aria-label", `View source details for ${source.title || `source ${source.n}`}`);
      item.append(preview);
    }
    item.append(document.createTextNode(` — ${source.date || "date unavailable"} · ${source.source_kind || "source"}`));
    sourcesList.append(item);
  }
  byId("brief-source-section").hidden = sourcesList.childElementCount === 0;
  renderRejectedClaims(result);
  byId("brief-actions").hidden = false;
}

function briefAsMarkdown(result) {
  const lines = [`# ${result.company || "Brief"}`];
  if (result.meeting) lines.push("", `Meeting: ${result.meeting}`);
  lines.push("");
  const bullets = Array.isArray(result.bullets) ? result.bullets : [];
  if (!bullets.length) {
    lines.push("No claim passed verification, so the strong model was never called.");
  } else {
    for (const bullet of bullets) {
      const citations = (bullet.cites || []).map((number) => `[${number}]`).join("");
      lines.push(`- ${bullet.text || ""}${citations ? ` ${citations}` : ""}`);
    }
  }
  if (result.sources?.length) {
    lines.push("", "## Sources");
    for (const source of result.sources) {
      lines.push(`${source.n}. ${source.title || source.url} — ${source.date || "date unavailable"} — ${source.url}`);
    }
  }
  if (result.open_questions?.length) {
    lines.push("", "## Inferences");
    for (const question of result.open_questions) {
      lines.push(`- *${String(question).replace(/^inference(?:\s+\[[^\]]+\])?:\s*/i, "")}*`);
    }
  }
  return lines.join("\n");
}

async function copyBriefMarkdown() {
  if (!briefResult) return;
  const markdown = briefAsMarkdown(briefResult);
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(markdown);
    byId("copy-feedback").textContent = "Brief copied as Markdown.";
  } catch {
    const textarea = createElement("textarea");
    textarea.value = markdown;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.append(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    textarea.remove();
    byId("copy-feedback").textContent = copied
      ? "Brief copied as Markdown."
      : "Clipboard access is unavailable in this browser.";
  }
}

function openSidePanel(overlayId, panelId, closeButtonId) {
  closeSidePanel();
  sidePanelPreviousFocus = document.activeElement;
  activeSidePanel = { overlayId, panelId, closeButtonId };
  byId(overlayId).hidden = false;
  byId(closeButtonId).focus();
}

function closeSidePanel() {
  if (!activeSidePanel) return;
  byId(activeSidePanel.overlayId).hidden = true;
  activeSidePanel = null;
  if (sidePanelPreviousFocus?.isConnected) sidePanelPreviousFocus.focus();
  sidePanelPreviousFocus = null;
}

function trapSidePanelFocus(event) {
  if (!activeSidePanel) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeSidePanel();
    return;
  }
  if (event.key !== "Tab") return;
  const panel = byId(activeSidePanel.panelId);
  const focusable = [...panel.querySelectorAll("button:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])")];
  if (!focusable.length) {
    event.preventDefault();
    panel.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function evidenceForBullet(bullet, sourceNumber) {
  const evidence = bullet.evidence || [];
  return evidence.find((item) => item.source_n === sourceNumber) || evidence[0] || null;
}

function handleFailover(data) {
  const banner = byId("failover-banner");
  const reason = String(data.reason || "failover");
  const simulated = reason.toLowerCase().includes("simulated");
  const displayReason = reason.replace(/\s*\(simulated\)/i, "");
  banner.textContent = `Switched from ${data.from || "unknown"} to ${data.to || "unknown"} (${displayReason})${simulated ? " — simulated" : ""}`;
  banner.hidden = false;
}

function handleBlocked(data) {
  blockedCount += 1;
  byId("blocked-count").textContent = `${blockedCount} blocked`;
  byId("blocked-count").hidden = false;
  byId("blocked-inline-count").textContent = String(blockedCount);
  byId("blocked-panel").hidden = false;
  const item = createElement("li");
  item.append(
    createElement("strong", "", data.kind || "Action"),
    document.createTextNode(` — ${data.reason || "Blocked by policy"} `),
    createElement("span", "blocked-source", `(${data.source || "policy"})`),
  );
  byId("blocked-list").append(item);
}

function handleResult(result) {
  const receipt = result.receipt;
  if (receipt) {
    updateMeter(receipt.tokens, receipt.cap);
    if (typeof receipt.usd === "number") {
      usdTotal = receipt.usd;
      byId("live-usd").textContent = formatUsd(usdTotal);
    }
    priceUnverified = receipt.prices_verified === false || receipt.usd === null;
    setPriceWarning();
    updateCallList(receipt.calls);
  }
  if (result.mode === "brief") {
    renderBriefResult(result);
  } else {
    byId("brief-result").hidden = true;
    byId("brief-actions").hidden = true;
  }
  showMeasuredSavings(result, receipt);
  closeSidePanel();
  closeApprovalDrawer();
  setRunState("done");
  closeStream();
  stopPolling();
}

function showMeasuredSavings(result, receipt) {
  const baseline = result.baseline_measurement;
  if (!baseline || baseline.measured !== true || !receipt) return;
  const row = byId("savings-row");
  const value = byId("savings-value");
  if (typeof baseline.tokens === "number" && Number.isFinite(baseline.tokens)) {
    const saved = baseline.tokens - receipt.tokens;
    value.textContent = `${saved >= 0 ? "" : "−"}${formatNumber(Math.abs(saved))} tokens`;
    row.classList.toggle("savings-negative", saved < 0);
    row.hidden = false;
  } else if (
    typeof baseline.usd === "number" && Number.isFinite(baseline.usd) &&
    typeof receipt.usd === "number" && Number.isFinite(receipt.usd)
  ) {
    const saved = baseline.usd - receipt.usd;
    value.textContent = `${saved >= 0 ? "" : "−"}${formatUsd(Math.abs(saved))}`;
    row.classList.toggle("savings-negative", saved < 0);
    row.hidden = false;
  }
}

function parseEvent(event) {
  let envelope;
  try {
    envelope = JSON.parse(event.data);
  } catch {
    return;
  }
  if (!envelope || typeof envelope !== "object") return;
  const sequence = Number(envelope.seq) || Number(event.lastEventId) || 0;
  if (sequence && sequence <= lastSequence) return;
  if (sequence) lastSequence = sequence;
  const type = envelope.type || event.type;
  const data = envelope.data || {};
  const timestamp = envelope.ts || new Date().toISOString();
  if (type === "step") handleStep(data, timestamp);
  else if (type === "model_call") handleModelCall(data, sequence || Date.now());
  else if (type === "claim") handleClaim(data, sequence || Date.now());
  else if (type === "budget") updateMeter(data.used, data.cap);
  else if (type === "failover") handleFailover(data);
  else if (type === "approval_request") queueApproval(data);
  else if (type === "approval_result") handleApprovalResult(data);
  else if (type === "blocked") handleBlocked(data);
  else if (type === "result") handleResult(data);
  else if (type === "error") {
    closeApprovalDrawer();
    addTimelineRow(`run-error:${sequence}`, {
      title: "Run error",
      detail: data.message || "The run failed.",
      icon: "!",
      status: "fail",
    });
    setRunState("error");
    closeStream();
    stopPolling();
  }
}

function startStream(id) {
  closeStream();
  stopPolling();
  const stream = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`);
  eventSource = stream;
  // Keep the same EventSource alive so native retries include Last-Event-ID.
  stream.addEventListener("open", () => {
    if (fallbackTimer) clearTimeout(fallbackTimer);
    fallbackTimer = null;
    stopPolling();
  });
  for (const name of eventNames) {
    if (name === "error") continue;
    stream.addEventListener(name, parseEvent);
  }
  stream.addEventListener("error", (event) => {
    if (typeof event.data === "string") {
      parseEvent(event);
      return;
    }
    setRunState(activeApproval ? "waiting for approval" : "running");
    if (!fallbackTimer) {
      fallbackTimer = setTimeout(() => {
        fallbackTimer = null;
        if (eventSource === stream && !terminalStates.has(byId("run-state").textContent.toLowerCase())) {
          startPolling(id);
        }
      }, 8000);
    }
  });
}

function closeStream() {
  if (eventSource) eventSource.close();
  eventSource = null;
  if (fallbackTimer) clearTimeout(fallbackTimer);
  fallbackTimer = null;
}

function startPolling(id) {
  if (pollTimer) return;
  const poll = async () => {
    if (!runId || runId !== id) return stopPolling();
    try {
      const response = await fetch(`/api/runs/${encodeURIComponent(id)}`);
      if (!response.ok) throw new Error(`Run status request failed (${response.status})`);
      const status = await response.json();
      if (status.status === "completed") {
        closeApprovalDrawer();
        setRunState("done");
        closeStream();
        return stopPolling();
      }
      if (status.status === "failed") {
        closeApprovalDrawer();
        setRunState("error");
        closeStream();
        return stopPolling();
      }
      if (status.status === "cancelled") {
        closeApprovalDrawer();
        setRunState("cancelled");
        closeStream();
        return stopPolling();
      }
      if (activeApproval) setRunState("waiting for approval");
      else setRunState("running");
    } catch (error) {
      addTimelineRow("connection", {
        title: "Reconnecting",
        detail: error.message || "Run status is temporarily unavailable.",
        icon: "…",
        status: "running",
      });
    }
  };
  poll();
  pollTimer = setInterval(poll, 2500);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

function queueApproval(data) {
  if (!data || !data.hash) return;
  if (activeApproval?.data.hash === data.hash ||
      approvalQueue.some((item) => item.hash === data.hash)) return;
  approvalQueue.push(data);
  if (!activeApproval) showNextApproval();
}

function approvalCommand(data) {
  const payload = data.payload || {};
  const target = payload.target;
  const details = payload.details || {};
  if (typeof payload.query === "string") return `Network query:\n${payload.query}`;
  if (Array.isArray(target)) {
    const command = target.map((part) => {
      const text = String(part);
      return /^[A-Za-z0-9_./:=+-]+$/.test(text) ? text : JSON.stringify(text);
    }).join(" ");
    const selector = details.selector ? ` ${details.selector}` : "";
    return `${command}${selector}${details.cwd ? `\nWorking directory: ${details.cwd}` : ""}`;
  }
  if (typeof target === "string") return target;
  return "";
}

function appendDiff(pre, diff) {
  for (const line of String(diff).split("\n")) {
    const span = createElement("span");
    if (line.startsWith("+") && !line.startsWith("+++")) span.className = "diff-line-add";
    if (line.startsWith("-") && !line.startsWith("---")) span.className = "diff-line-remove";
    span.textContent = `${line}\n`;
    pre.append(span);
  }
}

function showApprovalDetail(data) {
  const detail = byId("approval-detail");
  detail.replaceChildren();
  const payload = data.payload || {};
  const diff = payload.details?.diff || payload.diff;
  if (typeof diff === "string") {
    const pre = createElement("pre");
    appendDiff(pre, diff);
    detail.append(pre);
    return;
  }
  const command = approvalCommand(data);
  const pre = createElement("pre", "", command ||
    "Details are redacted for this confidential action. Review the hash before deciding.");
  detail.append(pre);
}

function showNextApproval() {
  const data = approvalQueue.shift();
  if (!data) {
    activeApproval = null;
    closeApprovalDrawer();
    if (runId && !terminalStates.has(byId("run-state").textContent.toLowerCase())) {
      setRunState("running");
    }
    return;
  }
  activeApproval = { data, deadline: Date.now() + 300000, busy: false };
  previousFocus = document.activeElement;
  byId("approval-kind").textContent = data.kind || "Approval";
  byId("approval-kind").className = `kind-chip kind-${String(data.kind || "").toLowerCase()}`;
  byId("approval-title").textContent = data.summary || "Approval required";
  byId("approval-description").textContent =
    "Review this exact action. Approval does not authorize any other action hash.";
  byId("approval-hash").textContent = String(data.hash).slice(0, 12);
  byId("approval-hash").title = data.hash;
  byId("approval-feedback").textContent = "";
  showApprovalDetail(data);
  byId("approval-overlay").hidden = false;
  setRunState("waiting for approval");
  byId("deny-approval").disabled = false;
  byId("approve-run").disabled = false;
  byId("approve-once").disabled = false;
  byId("deny-approval").focus();
  updateCountdown();
  approvalTimer = setInterval(updateCountdown, 1000);
}

function updateCountdown() {
  if (!activeApproval) return;
  const seconds = Math.max(0, Math.ceil((activeApproval.deadline - Date.now()) / 1000));
  const minutes = Math.floor(seconds / 60);
  byId("approval-countdown").textContent =
    `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  if (seconds === 0 && !activeApproval.busy) submitApproval("denied", false, true);
}

async function submitApproval(decision, once, timedOut = false) {
  if (!activeApproval || activeApproval.busy || !runId) return;
  const approval = activeApproval;
  approval.busy = true;
  setApprovalButtonsDisabled(true);
  byId("approval-feedback").textContent = timedOut ? "Time expired; denying action…" : "Submitting decision…";
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hash: approval.data.hash, decision, once }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `Approval failed (${response.status})`);
    if (activeApproval?.data.hash === approval.data.hash) {
      if (approvalTimer) clearInterval(approvalTimer);
      approvalTimer = null;
      activeApproval = null;
      byId("approval-overlay").hidden = true;
      restoreApprovalFocus();
      announceDecision(approval.data.kind, decision);
      showNextApproval();
    }
  } catch (error) {
    if (activeApproval?.data.hash === approval.data.hash) {
      activeApproval.busy = false;
      setApprovalButtonsDisabled(false);
      byId("approval-feedback").textContent =
        `${error.message || "Could not submit approval."} ${timedOut ? "Retrying deny shortly." : ""}`;
      if (timedOut) {
        setTimeout(() => {
          if (activeApproval?.data.hash === approval.data.hash) {
            submitApproval("denied", false, true);
          }
        }, 1000);
      }
    }
  }
}

function setApprovalButtonsDisabled(disabled) {
  byId("deny-approval").disabled = disabled;
  byId("approve-run").disabled = disabled;
  byId("approve-once").disabled = disabled;
}

function announceDecision(kind, decision) {
  const row = createElement("li", "approval-event", `${kind} ${decision}`);
  byId("timeline").append(row);
}

function handleApprovalResult(data) {
  if (activeApproval?.data.hash === data.hash) {
    if (approvalTimer) clearInterval(approvalTimer);
    approvalTimer = null;
    activeApproval = null;
    byId("approval-overlay").hidden = true;
    restoreApprovalFocus();
    showNextApproval();
  }
  if (data.decision === "denied" && !activeApproval) setRunState("running");
}

function closeApprovalDrawer() {
  if (approvalTimer) clearInterval(approvalTimer);
  approvalTimer = null;
  activeApproval = null;
  approvalQueue = [];
  if (byId("approval-overlay")) byId("approval-overlay").hidden = true;
  restoreApprovalFocus();
}

function restoreApprovalFocus() {
  if (previousFocus?.isConnected) previousFocus.focus();
  previousFocus = null;
}

async function startRun(event) {
  event.preventDefault();
  if (runId && !terminalStates.has(byId("run-state").textContent.toLowerCase())) return;
  resetRunView();
  const cap = Number(byId("token-budget").value);
  if (!Number.isInteger(cap) || cap < 100 || cap > 1000000) {
    addTimelineRow("form-error", {
      title: "Invalid token budget",
      detail: "Choose a whole number between 100 and 1,000,000.",
      icon: "!",
      status: "fail",
    });
    return;
  }
  const confidential = byId("confidential").checked;
  const params = mode === "brief"
    ? {
        company: byId("company").value.trim(),
        meeting: byId("meeting").value,
        meeting_at: byId("meeting").value || null,
        cap,
        confidential,
      }
    : {
        repo_path: byId("repo-path").value.trim(),
        task: byId("task").value.trim() || null,
        test_cmd: ["python", "-m", "pytest"],
        cap,
        confidential,
      };
  if (mode === "brief" && (!params.company || !params.meeting)) {
    addTimelineRow("form-error", {
      title: "Missing brief details",
      detail: "Enter a company or person and a meeting date and time.",
      icon: "!",
      status: "fail",
    });
    return;
  }
  if (mode === "fix" && !params.repo_path) {
    addTimelineRow("form-error", {
      title: "Missing repository path",
      detail: "Enter a repository path that is inside LEDGER_ALLOWED_ROOTS.",
      icon: "!",
      status: "fail",
    });
    return;
  }
  const userId = byId("user-id").value.trim() || "default";
  requestPending = true;
  byId("start-run").disabled = true;
  setRunState("running");
  addTimelineRow("starting", {
    title: "Creating run",
    detail: "Submitting request to Ledger…",
    icon: "",
    status: "running",
  });
  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Ledger-User": userId,
      },
      body: JSON.stringify({ mode, params, confidential }),
    });
    const result = await response.json();
    if (!response.ok) {
      const message = Array.isArray(result.detail)
        ? result.detail.map((item) => item.msg).join("; ")
        : result.detail || `Run request failed (${response.status})`;
      throw new Error(message);
    }
    runId = result.run_id;
    byId("run-id").textContent = `Run ${runId}`;
    updateMeter(0, cap);
    byId("cancel-run").disabled = false;
    addTimelineRow("starting", {
      title: "Run created",
      detail: `Run ${runId}`,
      icon: "✓",
      status: "ok",
    });
    startStream(runId);
  } catch (error) {
    runId = null;
    setRunState("error");
    addTimelineRow("start-error", {
      title: "Could not start run",
      detail: error.message || "Request failed.",
      icon: "!",
      status: "fail",
    });
  } finally {
    requestPending = false;
    setRunState(byId("run-state").textContent.toLowerCase());
  }
}

async function cancelRun() {
  if (!runId || terminalStates.has(byId("run-state").textContent.toLowerCase())) return;
  byId("cancel-run").disabled = true;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not cancel run.");
    closeApprovalDrawer();
    const state = result.status === "cancelled" ? "cancelled"
      : result.status === "completed" ? "done"
        : result.status === "failed" ? "error" : "running";
    setRunState(state);
    closeStream();
    stopPolling();
  } catch (error) {
    byId("cancel-run").disabled = false;
    addTimelineRow(`cancel-error:${Date.now()}`, {
      title: "Cancel failed",
      detail: error.message || "Could not cancel run.",
      icon: "!",
      status: "fail",
    });
  }
}

function trapApprovalFocus(event) {
  if (!activeApproval) return;
  if (event.key === "Escape") {
    event.preventDefault();
    byId("deny-approval").focus();
    byId("approval-feedback").textContent = "Escape does not approve; choose Deny or make an explicit decision.";
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = [...byId("approval-drawer").querySelectorAll("button:not(:disabled)")];
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

const workspaceTabs = [
  ["run-screen-tab", "run-screen"],
  ["redteam-tab", "redteam-screen"],
  ["benchmark-tab", "benchmark-screen"],
];

function setWorkspaceScreen(screenId) {
  for (const [tabId, panelId] of workspaceTabs) {
    const selected = panelId === screenId;
    const tab = byId(tabId);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    tab.classList.toggle("is-active", selected);
    byId(panelId).hidden = !selected;
  }
  if (screenId === "benchmark-screen") loadBenchmarkSummary();
}

function renderRedteamEvidence(scenario) {
  const details = createElement("details", "scenario-evidence");
  const events = Array.isArray(scenario.evidence) ? scenario.evidence : [];
  details.append(createElement("summary", "", `Evidence events (${events.length})`));
  const list = createElement("ul", "evidence-event-list");
  for (const event of events) {
    const data = event.data || {};
    const droppedSources = Array.isArray(data.audit?.pre_dropped)
      ? data.audit.pre_dropped.map((item) => `${item.reason}: ${item.title}`)
      : [];
    const description = [
      data.title,
      data.detail,
      data.reason,
      data.message,
      data.kind,
      data.source,
      data.status,
      ...droppedSources,
    ].filter((part) => typeof part === "string" && part.length);
    const item = createElement(
      "li",
      "",
      `${event.type || "event"}${description.length ? ` · ${description.join(" · ")}` : ""}`,
    );
    list.append(item);
  }
  if (!events.length) list.append(createElement("li", "muted", "No evidence events."));
  details.append(list);
  return details;
}

function renderRedteamResults(payload) {
  const results = byId("redteam-results");
  results.replaceChildren();
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  for (const scenario of scenarios) {
    const passed = scenario.passed === true;
    const item = createElement("li", `scenario-card ${passed ? "scenario-pass" : "scenario-fail"}`);
    const heading = createElement("div", "scenario-heading");
    heading.append(
      createElement("h2", "", scenario.name || scenario.id || "Unnamed scenario"),
      createElement("span", `scenario-status ${passed ? "is-pass" : "is-fail"}`, passed ? "PASS" : "FAIL"),
    );
    item.append(heading);
    const checks = createElement("ul", "scenario-checks");
    for (const [name, value] of Object.entries(scenario.checks || {})) {
      checks.append(createElement(
        "li",
        value === true ? "check-pass" : "check-fail",
        `${name.replaceAll("_", " ")}: ${value === true ? "pass" : "fail"}`,
      ));
    }
    item.append(checks, renderRedteamEvidence(scenario));
    results.append(item);
  }
  const passed = Number(payload.passed) || 0;
  const failed = Number(payload.failed) || 0;
  byId("redteam-status").textContent = `${passed} passed · ${failed} failed`;
}

async function runRedteam() {
  const button = byId("run-redteam");
  button.disabled = true;
  byId("redteam-status").textContent = "Running scenarios…";
  byId("redteam-results").replaceChildren();
  try {
    const response = await fetch("/api/redteam", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `Red-team request failed (${response.status})`);
    renderRedteamResults(payload);
  } catch (error) {
    byId("redteam-status").textContent = error.message || "Red-team run failed.";
  } finally {
    button.disabled = false;
  }
}

function svgElement(tag, attributes = {}, text = "") {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
  if (text) element.textContent = text;
  return element;
}

function benchmarkArms(summary) {
  const entries = Object.entries(summary.arms || {});
  return entries.sort(([left], [right]) => left.localeCompare(right));
}

function renderBenchmarkChart(container, arms, metric) {
  container.replaceChildren();
  if (!arms.length) return;
  const baseline = arms.find(([name]) => name === "baseline")?.[1];
  const costValues = arms
    .map(([, arm]) => arm.cost_per_verified_outcome)
    .filter((value) => typeof value === "number" && Number.isFinite(value));
  const maxCost = Math.max(0, ...costValues) || 1;
  const width = 760;
  const rowHeight = 38;
  const top = 18;
  const chartLeft = 205;
  const chartWidth = 340;
  const height = top + rowHeight * arms.length + 12;
  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": metric === "pass"
      ? "Pass rate by arm with 95 percent Wilson confidence intervals"
      : "Cost per verified outcome by arm",
  });

  arms.forEach(([name, arm], index) => {
    const y = top + index * rowHeight;
    const isPass = metric === "pass";
    const raw = isPass ? arm.pass_rate : arm.cost_per_verified_outcome;
    const value = typeof raw === "number" && Number.isFinite(raw) ? raw : null;
    const baselineRaw = isPass
      ? baseline?.pass_rate
      : baseline?.cost_per_verified_outcome;
    const hasBaseline = typeof baselineRaw === "number" && Number.isFinite(baselineRaw);
    const belowBaseline = value !== null && hasBaseline &&
      (isPass ? value < baselineRaw : value > baselineRaw);
    const color = belowBaseline ? "var(--no)" : "var(--ok)";

    svg.append(svgElement("text", {
      x: 0, y: y + 5, class: "chart-label",
    }, name));
    svg.append(svgElement("line", {
      x1: chartLeft, x2: chartLeft + chartWidth, y1: y, y2: y,
      class: "chart-track",
    }));

    if (value !== null) {
      const bounded = isPass ? Math.max(0, Math.min(1, value)) : Math.max(0, value / maxCost);
      const barWidth = bounded * chartWidth;
      svg.append(svgElement("rect", {
        x: chartLeft, y: y - 5, width: barWidth, height: 10, rx: 3,
        fill: color,
      }));
      if (isPass) {
        const interval = arm.pass_rate_ci95;
        if (Array.isArray(interval) && interval.length === 2 &&
            interval.every((entry) => typeof entry === "number" && Number.isFinite(entry))) {
          const low = chartLeft + Math.max(0, Math.min(1, interval[0])) * chartWidth;
          const high = chartLeft + Math.max(0, Math.min(1, interval[1])) * chartWidth;
          svg.append(svgElement("line", {
            x1: low, x2: high, y1: y, y2: y, stroke: "var(--ink)",
            "stroke-width": 2,
          }));
          for (const x of [low, high]) {
            svg.append(svgElement("line", {
              x1: x, x2: x, y1: y - 5, y2: y + 5, stroke: "var(--ink)",
              "stroke-width": 1,
            }));
          }
        }
      }
    }

    const valueText = value === null
      ? "not available"
      : isPass ? `${(value * 100).toFixed(1)}%` : formatUsd(value);
    let deltaText = "";
    if (value !== null && hasBaseline && name !== "baseline") {
      const delta = value - baselineRaw;
      deltaText = isPass
        ? `Δ ${delta < 0 ? "−" : "+"}${Math.abs(delta * 100).toFixed(1)} pp`
        : `Δ ${delta < 0 ? "−" : "+"}${formatUsd(Math.abs(delta))}`;
    }
    svg.append(svgElement("text", {
      x: chartLeft + chartWidth + 12,
      y: y + 4,
      class: belowBaseline ? "chart-value chart-below-baseline" : "chart-value",
    }, [valueText, deltaText].filter(Boolean).join(" · ")));
  });
  container.append(svg);
}

async function loadBenchmarkSummary() {
  const button = byId("refresh-benchmark");
  button.disabled = true;
  byId("benchmark-empty").hidden = true;
  byId("benchmark-error").hidden = true;
  byId("benchmark-content").hidden = true;
  try {
    const response = await fetch("/api/bench/summary");
    if (response.status === 404) {
      byId("benchmark-empty").hidden = false;
      return;
    }
    const summary = await response.json();
    if (!response.ok) throw new Error(summary.detail || `Benchmark request failed (${response.status})`);
    const arms = benchmarkArms(summary);
    if (!arms.length) {
      byId("benchmark-empty").hidden = false;
      return;
    }
    renderBenchmarkChart(byId("cost-chart"), arms, "cost");
    renderBenchmarkChart(byId("pass-chart"), arms, "pass");
    byId("benchmark-content").hidden = false;
  } catch (error) {
    byId("benchmark-error").textContent = error.message || "Could not load benchmark summary.";
    byId("benchmark-error").hidden = false;
  } finally {
    button.disabled = false;
  }
}

function activateWorkspaceTab(tab) {
  if (tab.key === "ArrowLeft" || tab.key === "ArrowRight") {
    tab.preventDefault();
    const current = workspaceTabs.findIndex(([tabId]) => byId(tabId) === tab.target);
    const direction = tab.key === "ArrowRight" ? 1 : -1;
    const next = workspaceTabs[(current + direction + workspaceTabs.length) % workspaceTabs.length];
    byId(next[0]).focus();
    byId(next[0]).click();
  }
}

for (const [tabId, panelId] of workspaceTabs) {
  byId(tabId).addEventListener("click", () => setWorkspaceScreen(panelId));
  byId(tabId).addEventListener("keydown", activateWorkspaceTab);
}
byId("run-redteam").addEventListener("click", runRedteam);
byId("refresh-benchmark").addEventListener("click", loadBenchmarkSummary);
byId("brief-tab").addEventListener("click", () => setMode("brief"));
byId("fix-tab").addEventListener("click", () => setMode("fix"));
byId("brief-sources").addEventListener("click", (event) => {
  const preview = event.target.closest("button.source-preview");
  if (!preview) return;
  openEvidence(Number(preview.dataset.sourceNumber), null, null);
});
for (const tab of [byId("brief-tab"), byId("fix-tab")]) {
  tab.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = tab === byId("brief-tab") ? byId("fix-tab") : byId("brief-tab");
    next.focus();
    next.click();
  });
}
byId("run-form").addEventListener("submit", startRun);
byId("cancel-run").addEventListener("click", cancelRun);
byId("brief-bullets").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-bullet-index]");
  if (!button || !briefResult) return;
  const bullet = briefResult.bullets[Number(button.dataset.bulletIndex)];
  if (!bullet) return;
  const evidence = evidenceForBullet(
    bullet,
    Number(button.dataset.sourceNumber || bullet.evidence?.[0]?.source_n),
  );
  const sourceNumber = Number(button.dataset.sourceNumber || evidence?.source_n);
  if (!Number.isFinite(sourceNumber)) return;
  openEvidence(
    sourceNumber,
    evidence,
    button.dataset.openEvidence ? bullet.checks : evidence?.checks,
  );
});
byId("show-rejected").addEventListener("click", () => {
  openSidePanel("rejected-overlay", "rejected-panel", "close-rejected");
});
byId("close-evidence").addEventListener("click", closeSidePanel);
byId("close-rejected").addEventListener("click", closeSidePanel);
for (const overlayId of ["evidence-overlay", "rejected-overlay"]) {
  byId(overlayId).addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeSidePanel();
  });
}
byId("copy-markdown").addEventListener("click", copyBriefMarkdown);
byId("print-brief").addEventListener("click", () => window.print());
document.addEventListener("keydown", trapSidePanelFocus);
byId("deny-approval").addEventListener("click", () => submitApproval("denied", false));
byId("approve-once").addEventListener("click", () => submitApproval("approved", true));
byId("approve-run").addEventListener("click", () => submitApproval("approved", false));
byId("approval-drawer").addEventListener("keydown", trapApprovalFocus);
document.addEventListener("focusin", (event) => {
  if (activeApproval && !byId("approval-drawer").contains(event.target)) {
    byId("deny-approval").focus();
  }
});

const now = new Date();
now.setMinutes(now.getMinutes() + 60 - now.getMinutes() % 60, 0, 0);
byId("meeting").value = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
  .toISOString().slice(0, 16);
updateMeter(0, 12000);
setRunState("idle");
fetch("/api/status")
  .then((response) => response.json())
  .then((status) => {
    byId("service-status").textContent = status.bifrost || status.tavily
      ? `Live · ${[status.bifrost && "Bifrost", status.tavily && "Tavily"].filter(Boolean).join(" + ")}`
      : "Offline replay";
  })
  .catch(() => { byId("service-status").textContent = "Backend unavailable"; });
