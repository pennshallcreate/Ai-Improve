// ---------------------------------------------------------------------------
// Rodeo Trader
// A trader who moonlights as a rodeo hand: real buy/sell trading, plus a
// bull/bear timing bonus round where a lasso throw earns (or saves) cash.
// Character look (skin tone + headwear) is a purely cosmetic, opt-in choice
// with zero effect on gameplay.
// ---------------------------------------------------------------------------

const SKIN_TONES = [
  { id: "default", modifier: "", label: "Default" },
  { id: "light", modifier: "\u{1F3FB}", label: "Light" },
  { id: "medium-light", modifier: "\u{1F3FC}", label: "Medium-light" },
  { id: "medium", modifier: "\u{1F3FD}", label: "Medium" },
  { id: "medium-dark", modifier: "\u{1F3FE}", label: "Medium-dark" },
  { id: "dark", modifier: "\u{1F3FF}", label: "Dark" },
];

// Each headwear option maps to a base emoji that supports Fitzpatrick skin
// tone modifiers. Purely cosmetic — none of these change gameplay.
const HEADWEAR_OPTIONS = [
  { id: "cowboy", label: "Cowboy Hat", base: "\u{1F920}" }, // 🤠
  { id: "kippah", label: "Kippah", base: "\u{1F9D1}", accessory: "kippah" }, // 🧑 + drawn accessory
  { id: "hijab", label: "Hijab", base: "\u{1F9D5}" }, // 🧕
  { id: "turban", label: "Turban", base: "\u{1F473}" }, // 👳
  { id: "none", label: "No Headwear", base: "\u{1F9D1}" }, // 🧑
];

const STARTING_CASH = 1000;
const MAX_DAYS = 60;
const DAY_MS = 1000;
const BASE_VOLATILITY = 1.6;
const CHART_POINTS = 80;

const BULL_BONUS = 75;
const BEAR_PENALTY = 40;
const BEAR_DODGE_BONUS = 10;
const EVENT_DURATION_MS = 2400;
const EVENT_MIN_GAP_DAYS = 5;
const EVENT_CHANCE_PER_DAY = 0.35;

const canvas = document.getElementById("game-canvas");
const ctx = canvas.getContext("2d");

let state = null;
let character = { name: "Trader", tone: SKIN_TONES[0], headwear: HEADWEAR_OPTIONS[0] };

// ---------------------------------------------------------------------------
// Character customization screen
// ---------------------------------------------------------------------------

function spriteString(tone, headwear) {
  return headwear.base + tone.modifier;
}

function buildTonePicker() {
  const row = document.getElementById("tone-picker");
  row.innerHTML = "";
  SKIN_TONES.forEach((tone) => {
    const btn = document.createElement("button");
    btn.className = "option-btn" + (tone.id === character.tone.id ? " selected" : "");
    btn.type = "button";
    const swatch = document.createElement("span");
    swatch.className = "tone-swatch";
    swatch.style.background = toneColor(tone.id);
    btn.appendChild(swatch);
    btn.appendChild(document.createTextNode(tone.label));
    btn.addEventListener("click", () => {
      character.tone = tone;
      buildTonePicker();
      updatePreview();
    });
    row.appendChild(btn);
  });
}

function toneColor(id) {
  return {
    default: "#f2c063",
    light: "#f5d7b8",
    "medium-light": "#e0b088",
    medium: "#c88b5f",
    "medium-dark": "#8d5a34",
    dark: "#5c3a20",
  }[id];
}

function buildHeadwearPicker() {
  const row = document.getElementById("headwear-picker");
  row.innerHTML = "";
  HEADWEAR_OPTIONS.forEach((hw) => {
    const btn = document.createElement("button");
    btn.className = "option-btn" + (hw.id === character.headwear.id ? " selected" : "");
    btn.type = "button";
    btn.textContent = `${spriteString(character.tone, hw)} ${hw.label}`;
    btn.addEventListener("click", () => {
      character.headwear = hw;
      buildHeadwearPicker();
      updatePreview();
    });
    row.appendChild(btn);
  });
}

function updatePreview() {
  document.getElementById("sprite-preview").textContent = spriteString(character.tone, character.headwear);
  buildHeadwearPicker();
}

document.getElementById("trader-name").addEventListener("input", (e) => {
  character.name = e.target.value.trim() || "Trader";
});

document.getElementById("start-btn").addEventListener("click", () => {
  showScreen("game-screen");
  startGame();
});

document.getElementById("restart-btn").addEventListener("click", () => {
  showScreen("start-screen");
});

function showScreen(id) {
  document.querySelectorAll(".screen").forEach((el) => el.classList.add("hidden"));
  document.getElementById(id).classList.remove("hidden");
}

buildTonePicker();
buildHeadwearPicker();
updatePreview();

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

function startGame() {
  state = {
    cash: STARTING_CASH,
    shares: 0,
    price: 50,
    priceHistory: [50],
    day: 0,
    lastEventDay: -EVENT_MIN_GAP_DAYS,
    event: null, // {type:'bull'|'bear', startTime, resolved, success}
    messages: [],
    lastDayTime: performance.now(),
    running: true,
  };
  document.getElementById("hud-name").textContent = character.name;
  requestAnimationFrame(loop);
}

function portfolioValue() {
  return state.cash + state.shares * state.price;
}

function addMessage(text, color) {
  state.messages.push({ text, color, life: 1400, createdAt: performance.now() });
}

// ---------------------------------------------------------------------------
// Trading actions
// ---------------------------------------------------------------------------

function buy() {
  if (!state || !state.running) return;
  const spend = state.cash * 0.25;
  if (spend < 1) return;
  state.cash -= spend;
  state.shares += spend / state.price;
  addMessage(`Bought $${spend.toFixed(0)} of stock`, "#7ee787");
}

function sell() {
  if (!state || !state.running) return;
  const sellShares = state.shares * 0.25;
  if (sellShares <= 0) return;
  const proceeds = sellShares * state.price;
  state.shares -= sellShares;
  state.cash += proceeds;
  addMessage(`Sold for $${proceeds.toFixed(0)}`, "#ffa657");
}

document.getElementById("buy-btn").addEventListener("click", buy);
document.getElementById("sell-btn").addEventListener("click", sell);

window.addEventListener("keydown", (e) => {
  if (!state || !state.running) return;
  if (e.code === "KeyB") buy();
  else if (e.code === "KeyS") sell();
  else if (e.code === "Space") {
    e.preventDefault();
    attemptLasso();
  }
});

function attemptLasso() {
  const ev = state.event;
  if (!ev || ev.resolved) return;
  const elapsed = performance.now() - ev.startTime;
  const progress = elapsed / EVENT_DURATION_MS;
  // Catch window: middle portion of the run, when the animal is near the player.
  if (progress >= 0.35 && progress <= 0.7) {
    ev.resolved = true;
    ev.success = true;
    if (ev.type === "bull") {
      state.cash += BULL_BONUS;
      addMessage(`Lassoed the bull! +$${BULL_BONUS}`, "#f2b134");
    } else {
      state.cash += BEAR_DODGE_BONUS;
      addMessage(`Shooed the bear away! +$${BEAR_DODGE_BONUS}`, "#f2b134");
    }
  }
}

// ---------------------------------------------------------------------------
// Simulation tick (once per "day")
// ---------------------------------------------------------------------------

function tick() {
  state.day += 1;

  const volatility = BASE_VOLATILITY + state.day * 0.02;
  const change = (Math.random() * 2 - 1) * volatility;
  state.price = Math.max(1, state.price + change);
  state.priceHistory.push(state.price);
  if (state.priceHistory.length > CHART_POINTS) state.priceHistory.shift();

  maybeSpawnEvent();

  if (state.day >= MAX_DAYS) {
    endGame();
  }
}

function maybeSpawnEvent() {
  if (state.event && !isEventFinished(state.event)) return;
  if (state.day - state.lastEventDay < EVENT_MIN_GAP_DAYS) return;
  if (Math.random() > EVENT_CHANCE_PER_DAY) return;

  state.lastEventDay = state.day;
  state.event = {
    type: Math.random() < 0.5 ? "bull" : "bear",
    startTime: performance.now(),
    resolved: false,
    success: false,
  };
}

function isEventFinished(ev) {
  return performance.now() - ev.startTime > EVENT_DURATION_MS + 200;
}

function resolveExpiredEvent() {
  const ev = state.event;
  if (!ev || ev.resolved) return;
  const elapsed = performance.now() - ev.startTime;
  if (elapsed <= EVENT_DURATION_MS) return;

  ev.resolved = true;
  if (ev.type === "bear") {
    state.cash = Math.max(0, state.cash - BEAR_PENALTY);
    addMessage(`The bear spooked your position! -$${BEAR_PENALTY}`, "#ff6b6b");
  } else {
    addMessage("The bull got away.", "#c9b58b");
  }
}

function endGame() {
  state.running = false;
  const finalValue = portfolioValue();
  const profit = finalValue - STARTING_CASH;
  showScreen("end-screen");
  document.getElementById("end-title").textContent =
    profit >= 0 ? "Nice ride!" : "Rough round in the arena.";
  document.getElementById("end-summary").textContent =
    `${character.name} finished with $${finalValue.toFixed(2)} ` +
    `(started with $${STARTING_CASH.toFixed(2)}).\n` +
    (profit >= 0
      ? `That's a profit of $${profit.toFixed(2)}!`
      : `That's a loss of $${Math.abs(profit).toFixed(2)}.`);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const CHART_TOP = 15;
const CHART_HEIGHT = 250;
const ARENA_TOP = 290;
const ARENA_HEIGHT = 140;
const PLAYER_X = 110;

function render() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawChart();
  drawArena();
  drawMessages();
}

function drawChart() {
  const hist = state.priceHistory;
  const min = Math.min(...hist);
  const max = Math.max(...hist, min + 1);

  ctx.strokeStyle = "#2a2013";
  ctx.strokeRect(0, CHART_TOP, canvas.width, CHART_HEIGHT);

  ctx.beginPath();
  hist.forEach((p, i) => {
    const x = (i / (CHART_POINTS - 1)) * canvas.width;
    const y = CHART_TOP + CHART_HEIGHT - ((p - min) / (max - min)) * (CHART_HEIGHT - 20) - 10;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  const trendingUp = hist[hist.length - 1] >= hist[Math.max(0, hist.length - 2)];
  ctx.strokeStyle = trendingUp ? "#7ee787" : "#ff6b6b";
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.lineWidth = 1;
}

function drawArena() {
  ctx.fillStyle = "#3b2a17";
  ctx.fillRect(0, ARENA_TOP, canvas.width, ARENA_HEIGHT);

  // catch zone marker
  ctx.fillStyle = "rgba(242, 177, 52, 0.15)";
  ctx.fillRect(PLAYER_X - 40, ARENA_TOP, 140, ARENA_HEIGHT);

  // player sprite
  ctx.font = "48px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(spriteString(character.tone, character.headwear), PLAYER_X, ARENA_TOP + ARENA_HEIGHT - 20);
  ctx.font = "20px sans-serif";
  ctx.fillStyle = "#f5e9d8";
  ctx.fillText(character.name, PLAYER_X, ARENA_TOP + ARENA_HEIGHT + 5);

  const ev = state.event;
  if (ev) {
    resolveExpiredEvent();
    const elapsed = performance.now() - ev.startTime;
    const progress = Math.min(1, elapsed / EVENT_DURATION_MS);
    const x = canvas.width + 60 - progress * (canvas.width + 160);

    ctx.font = "44px sans-serif";
    ctx.fillStyle = "#000";
    ctx.fillText(ev.type === "bull" ? "\u{1F402}" : "\u{1F43B}", x, ARENA_TOP + ARENA_HEIGHT - 22);

    if (!ev.resolved) {
      ctx.font = "16px sans-serif";
      ctx.fillStyle = "#f2b134";
      ctx.fillText("Press SPACE!", canvas.width / 2, ARENA_TOP - 8);
    }
  }
}

function drawMessages() {
  const now = performance.now();
  state.messages = state.messages.filter((m) => now - m.createdAt < m.life);
  ctx.textAlign = "center";
  ctx.font = "18px sans-serif";
  state.messages.forEach((m, i) => {
    const age = (now - m.createdAt) / m.life;
    ctx.globalAlpha = 1 - age;
    ctx.fillStyle = m.color;
    ctx.fillText(m.text, canvas.width / 2, 40 + i * 22);
  });
  ctx.globalAlpha = 1;
}

function updateHud() {
  document.getElementById("hud-day").textContent = `${state.day}/${MAX_DAYS}`;
  document.getElementById("hud-price").textContent = `$${state.price.toFixed(2)}`;
  document.getElementById("hud-cash").textContent = `$${state.cash.toFixed(2)}`;
  document.getElementById("hud-shares").textContent = state.shares.toFixed(2);
  document.getElementById("hud-portfolio").textContent = `$${portfolioValue().toFixed(2)}`;
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

function loop(now) {
  if (!state || !state.running) return;

  if (now - state.lastDayTime >= DAY_MS) {
    state.lastDayTime = now;
    tick();
  }

  updateHud();
  render();

  requestAnimationFrame(loop);
}
