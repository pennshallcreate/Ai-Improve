"use strict";

/* ============================================================
   Daily Interest Trading Projection
   ------------------------------------------------------------
   Model: each trading day you invest `investPct` of the current
   balance at a daily return of `rate`. The un-invested portion is
   untouched, so the balance grows by a factor of:

        g = 1 + (investPct/100) * (rate/100)

   per trading day, and balance[i] = start * g^i.
   ============================================================ */

const DEFAULTS = {
  start: 2660,
  invest: 99,
  rate: 1,
  months: 6,
  weekdaysOnly: false,
  logScale: false,
};

// Trading days per calendar month for each mode.
const DAYS_PER_MONTH = { calendar: 30, weekdays: 21 };

// ---- Element references -------------------------------------------------
const el = {
  startRange: document.getElementById("startRange"),
  startInput: document.getElementById("startInput"),
  investRange: document.getElementById("investRange"),
  investInput: document.getElementById("investInput"),
  rateRange: document.getElementById("rateRange"),
  rateInput: document.getElementById("rateInput"),
  monthsRange: document.getElementById("monthsRange"),
  monthsInput: document.getElementById("monthsInput"),
  weekdaysOnly: document.getElementById("weekdaysOnly"),
  logScale: document.getElementById("logScale"),
  resetBtn: document.getElementById("resetBtn"),
  stats: document.getElementById("stats"),
  canvas: document.getElementById("chart"),
  tooltip: document.getElementById("tooltip"),
};

const ctx = el.canvas.getContext("2d");

// Layout/state shared between draw and hover handlers.
let chartState = null;

// ---- Formatting helpers -------------------------------------------------
const fmtMoney = (n) =>
  "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });

const fmtMoneyExact = (n) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function fmtAbbrev(n) {
  const abs = Math.abs(n);
  if (abs >= 1e9) return "$" + (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (abs >= 1e6) return "$" + (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (abs >= 1e3) return "$" + (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return "$" + n.toFixed(0);
}

const fmtPct = (n) =>
  n.toLocaleString("en-US", { maximumFractionDigits: 2 }) + "%";

// ---- Read current inputs ------------------------------------------------
function readState() {
  const start = Math.max(0, parseFloat(el.startInput.value) || 0);
  const invest = clamp(parseFloat(el.investInput.value) || 0, 0, 100);
  const rate = Math.max(0, parseFloat(el.rateInput.value) || 0);
  const months = clamp(Math.round(parseFloat(el.monthsInput.value) || 1), 1, 120);
  const weekdaysOnly = el.weekdaysOnly.checked;
  const logScale = el.logScale.checked;
  return { start, invest, rate, months, weekdaysOnly, logScale };
}

function clamp(v, min, max) {
  return Math.min(max, Math.max(min, v));
}

// ---- Build the projection series ---------------------------------------
function buildSeries(s) {
  const daysPerMonth = s.weekdaysOnly ? DAYS_PER_MONTH.weekdays : DAYS_PER_MONTH.calendar;
  const totalDays = Math.round(s.months * daysPerMonth);
  const g = 1 + (s.invest / 100) * (s.rate / 100); // daily growth factor

  const balances = new Array(totalDays + 1);
  let bal = s.start;
  balances[0] = bal;
  for (let i = 1; i <= totalDays; i++) {
    bal *= g;
    balances[i] = bal;
  }

  return { balances, totalDays, daysPerMonth, g };
}

// ---- Stats panel --------------------------------------------------------
function renderStats(s, series) {
  const final = series.balances[series.totalDays];
  const profit = final - s.start;
  const roi = s.start > 0 ? (profit / s.start) * 100 : 0;
  const monthlyMult = Math.pow(series.g, series.daysPerMonth);
  const dailyGrowthPct = (series.g - 1) * 100;

  const cards = [
    { label: "Final balance", value: fmtMoney(final), pos: true },
    { label: "Total profit", value: fmtMoney(profit), pos: profit >= 0 },
    { label: "Return on investment", value: fmtPct(roi), pos: roi >= 0 },
    { label: "Effective daily growth", value: fmtPct(dailyGrowthPct) },
    { label: "Effective monthly growth", value: fmtPct((monthlyMult - 1) * 100) },
    { label: "Trading days", value: String(series.totalDays) },
  ];

  el.stats.innerHTML = cards
    .map(
      (c) => `
      <div class="stat">
        <div class="stat__label">${c.label}</div>
        <div class="stat__value ${c.pos ? "pos" : ""}">${c.value}</div>
      </div>`
    )
    .join("");
}

// ---- Chart drawing ------------------------------------------------------
function drawChart(s, series) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = el.canvas.clientWidth || el.canvas.parentElement.clientWidth;
  const cssHeight = Math.max(300, Math.round(cssWidth * 0.5));

  el.canvas.width = Math.round(cssWidth * dpr);
  el.canvas.height = Math.round(cssHeight * dpr);
  el.canvas.style.height = cssHeight + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const pad = { top: 16, right: 18, bottom: 34, left: 64 };
  const plotW = cssWidth - pad.left - pad.right;
  const plotH = cssHeight - pad.top - pad.bottom;

  const balances = series.balances;
  const n = balances.length;
  const maxVal = balances[n - 1];
  const minVal = balances[0];

  // Y scale (linear or log)
  const useLog = s.logScale && minVal > 0;
  const yMinRaw = useLog ? minVal : 0;
  const yMaxRaw = maxVal <= yMinRaw ? yMinRaw + 1 : maxVal;

  const toY = (v) => {
    if (useLog) {
      const lo = Math.log10(yMinRaw);
      const hi = Math.log10(yMaxRaw);
      const t = (Math.log10(Math.max(v, 1e-9)) - lo) / (hi - lo || 1);
      return pad.top + plotH - t * plotH;
    }
    const t = (v - yMinRaw) / (yMaxRaw - yMinRaw || 1);
    return pad.top + plotH - t * plotH;
  };
  const toX = (i) => pad.left + (i / (n - 1 || 1)) * plotW;

  // ---- Grid + Y labels ----
  ctx.font = "11px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.textBaseline = "middle";
  ctx.strokeStyle = "#2c3845";
  ctx.fillStyle = "#8b9aa9";
  ctx.lineWidth = 1;

  const yTicks = computeYTicks(yMinRaw, yMaxRaw, useLog, 6);
  ctx.textAlign = "right";
  yTicks.forEach((v) => {
    const y = toY(v);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
    ctx.stroke();
    ctx.fillText(fmtAbbrev(v), pad.left - 8, y);
  });

  // ---- X labels (month markers) ----
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const monthStep = Math.ceil(s.months / 8) || 1;
  for (let m = 0; m <= s.months; m += monthStep) {
    const idx = Math.min(Math.round(m * series.daysPerMonth), n - 1);
    const x = toX(idx);
    ctx.fillStyle = "#8b9aa9";
    ctx.fillText(m === 0 ? "Start" : "Mo " + m, x, pad.top + plotH + 8);
  }

  // ---- Area fill under the line ----
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
  grad.addColorStop(0, "rgba(63, 185, 80, 0.28)");
  grad.addColorStop(1, "rgba(63, 185, 80, 0.0)");
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(balances[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(toX(i), toY(balances[i]));
  ctx.lineTo(toX(n - 1), pad.top + plotH);
  ctx.lineTo(toX(0), pad.top + plotH);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // ---- The line ----
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(balances[0]));
  for (let i = 1; i < n; i++) ctx.lineTo(toX(i), toY(balances[i]));
  ctx.strokeStyle = "#3fb950";
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.stroke();

  // ---- End marker ----
  ctx.beginPath();
  ctx.arc(toX(n - 1), toY(balances[n - 1]), 4, 0, Math.PI * 2);
  ctx.fillStyle = "#3fb950";
  ctx.fill();

  chartState = { toX, toY, n, balances, pad, plotW, plotH, cssWidth, cssHeight, daysPerMonth: series.daysPerMonth };
}

function computeYTicks(min, max, useLog, count) {
  const ticks = [];
  if (useLog) {
    const lo = Math.floor(Math.log10(min));
    const hi = Math.ceil(Math.log10(max));
    for (let p = lo; p <= hi; p++) ticks.push(Math.pow(10, p));
    return ticks.filter((v) => v >= min * 0.5 && v <= max * 1.5);
  }
  const step = niceNum((max - min) / count);
  for (let v = 0; v <= max + step * 0.5; v += step) ticks.push(v);
  return ticks;
}

function niceNum(range) {
  const exp = Math.floor(Math.log10(range || 1));
  const frac = range / Math.pow(10, exp);
  let nice;
  if (frac < 1.5) nice = 1;
  else if (frac < 3) nice = 2;
  else if (frac < 7) nice = 5;
  else nice = 10;
  return nice * Math.pow(10, exp);
}

// ---- Hover tooltip ------------------------------------------------------
function onMove(evt) {
  if (!chartState) return;
  const rect = el.canvas.getBoundingClientRect();
  const mx = evt.clientX - rect.left;
  const my = evt.clientY - rect.top;
  const { pad, plotW, n, toX, toY, balances, daysPerMonth } = chartState;

  if (mx < pad.left || mx > pad.left + plotW) {
    el.tooltip.hidden = true;
    return;
  }
  const t = (mx - pad.left) / (plotW || 1);
  const idx = clamp(Math.round(t * (n - 1)), 0, n - 1);
  const val = balances[idx];
  const month = (idx / daysPerMonth);

  el.tooltip.hidden = false;
  el.tooltip.innerHTML =
    `Day ${idx} &middot; Mo ${month.toFixed(1)}<br><strong>${fmtMoneyExact(val)}</strong>`;
  el.tooltip.style.left = toX(idx) + "px";
  el.tooltip.style.top = toY(val) + "px";

  // redraw + crosshair dot
  render();
  ctx.beginPath();
  ctx.arc(toX(idx), toY(val), 4, 0, Math.PI * 2);
  ctx.fillStyle = "#e6edf3";
  ctx.fill();
  ctx.strokeStyle = "#3fb950";
  ctx.lineWidth = 2;
  ctx.stroke();
  void my;
}

// ---- Master render ------------------------------------------------------
function render() {
  const s = readState();
  const series = buildSeries(s);
  renderStats(s, series);
  drawChart(s, series);
}

// ---- Input wiring -------------------------------------------------------
function link(rangeEl, numEl, onChange) {
  rangeEl.addEventListener("input", () => {
    numEl.value = rangeEl.value;
    onChange();
  });
  numEl.addEventListener("input", () => {
    rangeEl.value = numEl.value;
    onChange();
  });
}

link(el.startRange, el.startInput, render);
link(el.investRange, el.investInput, render);
link(el.rateRange, el.rateInput, render);
link(el.monthsRange, el.monthsInput, render);
el.weekdaysOnly.addEventListener("change", render);
el.logScale.addEventListener("change", render);

el.resetBtn.addEventListener("click", () => {
  el.startInput.value = el.startRange.value = DEFAULTS.start;
  el.investInput.value = el.investRange.value = DEFAULTS.invest;
  el.rateInput.value = el.rateRange.value = DEFAULTS.rate;
  el.monthsInput.value = el.monthsRange.value = DEFAULTS.months;
  el.weekdaysOnly.checked = DEFAULTS.weekdaysOnly;
  el.logScale.checked = DEFAULTS.logScale;
  render();
});

el.canvas.addEventListener("mousemove", onMove);
el.canvas.addEventListener("mouseleave", () => {
  el.tooltip.hidden = true;
  render();
});

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(render, 80);
});

// ---- Go ----
render();
