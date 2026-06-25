"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

async function refreshStats() {
  const s = await api("/api/stats");
  $("stat-docs").textContent = s.total_docs ?? 0;
  $("stat-labels").textContent = Object.keys(s.labels || {}).length;
  $("stat-vocab").textContent = s.vocab_size ?? 0;
}

// ---- Teach ----------------------------------------------------------
$("train-btn").onclick = async () => {
  const text = $("train-text").value.trim();
  const label = $("train-label").value.trim();
  if (!text || !label) {
    $("train-out").textContent = "Enter both example text and a label.";
    return;
  }
  const r = await api("/api/train", { text, label });
  $("train-out").textContent = r.error
    ? "Error: " + r.error
    : `Learned "${label}" (${r.tokens} words). Total examples: ${r.total_docs}.`;
  $("train-text").value = "";
  refreshStats();
};

// ---- Ask ------------------------------------------------------------
$("predict-btn").onclick = async () => {
  const text = $("predict-text").value.trim();
  if (!text) return;
  const r = await api("/api/predict", { text });
  if (r.error) { $("predict-out").textContent = "Error: " + r.error; return; }
  if (!r.label) { $("predict-out").textContent = r.message || "No prediction."; return; }
  $("predict-out").innerHTML =
    `<b>${esc(r.label)}</b> &middot; ${(r.confidence * 100).toFixed(1)}% confident` +
    r.scores.map((s) =>
      `<div class="bar"><span style="width:${(s.confidence * 100).toFixed(1)}%"></span></div>` +
      `<small>${esc(s.label)} — ${(s.confidence * 100).toFixed(1)}%</small>`).join("");
};

// ---- Internet -------------------------------------------------------
function renderResults(results) {
  if (!results.length) return "No results.";
  return results.map((r) =>
    `<div class="result"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>` +
    `<div>${esc(r.snippet || "")}</div>` +
    `<span class="src">${esc(r.source)}</span></div>`).join("");
}

$("search-btn").onclick = async () => {
  const query = $("web-query").value.trim();
  if (!query) return;
  $("web-out").textContent = "Searching…";
  const r = await api("/api/web/search", { query });
  $("web-out").innerHTML = r.error ? "Error: " + r.error : renderResults(r.results);
};

$("fetch-btn").onclick = async () => {
  const url = $("web-query").value.trim();
  if (!url) return;
  $("web-out").textContent = "Fetching…";
  const r = await api("/api/web/fetch", { url });
  $("web-out").innerHTML = r.error
    ? "Error: " + r.error
    : `<div class="result"><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.url)}</a>` +
      `<div>${esc(r.text)}</div></div>`;
};

$("learn-btn").onclick = async () => {
  const query = $("web-query").value.trim();
  if (!query) return;
  const label = $("learn-label").value.trim() || undefined;
  $("web-out").textContent = "Learning from the web…";
  const r = await api("/api/web/learn", { query, label });
  $("web-out").innerHTML = r.error
    ? "Error: " + r.error
    : `Learned <b>${esc(r.label)}</b> from ${r.used_results} web result(s). ` +
      `Trained: ${r.trained}, skipped: ${r.skipped}.`;
  refreshStats();
};

// ---- Reset ----------------------------------------------------------
$("reset-btn").onclick = async () => {
  if (!confirm("Erase everything the AI has learned?")) return;
  await api("/api/reset", {});
  $("train-out").textContent = $("predict-out").innerHTML = $("web-out").innerHTML = "";
  refreshStats();
};

refreshStats();
