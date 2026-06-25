"""The NiceGUI dashboard: chat, controls, live graph and iteration log.

``create_app(controller, db, config)`` registers the single page and returns nothing;
``main.py`` wires the singletons and starts the server. All long work (Ollama chat,
iterations) runs off the UI thread; the page polls shared state on a timer.
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime

from nicegui import run, ui

from core.config import Config
from core.db import Database
from core.loop import LoopController
from core import scheduler
from .charts import build_figure

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def create_app(controller: LoopController, db: Database, config: Config) -> None:
    _install_globals(controller, db, config)

    @ui.page("/")
    def index() -> None:  # noqa: C901 - a dashboard is inherently a big layout
        ui.colors(primary="#0ea5e9")
        state: dict = {"show_suites": False}

        # ---------------- header / status bar ----------------
        with ui.header().classes("items-center justify-between bg-slate-800"):
            ui.label("🛠️  Self-Improving Local AI Agent").classes("text-lg font-bold")
            status_chips = ui.row().classes("items-center gap-3")

        # ---------------- tabs ----------------
        with ui.tabs().classes("w-full") as tabs:
            tab_dash = ui.tab("Dashboard", icon="insights")
            tab_chat = ui.tab("Chat", icon="chat")
            tab_ctrl = ui.tab("Controls", icon="tune")
            tab_log = ui.tab("Iteration log", icon="history")

        with ui.tab_panels(tabs, value=tab_dash).classes("w-full"):
            # ===================== DASHBOARD =====================
            with ui.tab_panel(tab_dash):
                with ui.row().classes("w-full gap-4"):
                    score_card = _stat_card("Aggregate score", "—")
                    base_card = _stat_card("Baseline (bar to beat)", "—")
                    runs_card = _stat_card("Benchmark runs", "—")
                    sess_card = _stat_card("Session budget", "—")
                with ui.row().classes("items-center gap-4 mt-2"):
                    ui.button("Run one iteration", icon="play_arrow",
                              on_click=lambda: _run_iter()).props("color=primary")
                    ui.button("KILL SWITCH", icon="dangerous",
                              on_click=lambda: _kill()).props("color=red")
                    suite_toggle = ui.switch("Per-suite breakdown",
                                             on_change=lambda e: _toggle_suites(e.value))
                phase_label = ui.label("").classes("text-sm text-slate-500")
                plot = ui.plotly(build_figure(db)).classes("w-full")

            # ===================== CHAT =====================
            with ui.tab_panel(tab_chat):
                ui.label("Chat with the local model (Ollama). Fully local — no cloud.")\
                    .classes("text-sm text-slate-500")
                chat_banner = ui.markdown("").classes(
                    "w-full text-sm px-3 py-2 rounded")
                chat_box = ui.column().classes(
                    "w-full gap-2 p-3 bg-slate-50 rounded").style("min-height:50vh")
                _render_chat(chat_box, db)
                with ui.row().classes("w-full items-center gap-2"):
                    chat_input = ui.input(placeholder="Ask something…")\
                        .props("outlined").classes("flex-grow")
                    ui.button(icon="send",
                              on_click=lambda: _send_chat(chat_box, chat_input))

            # ===================== CONTROLS =====================
            with ui.tab_panel(tab_ctrl):
                _build_controls(controller, db, config)

            # ===================== LOG =====================
            with ui.tab_panel(tab_log):
                log_table = ui.table(
                    columns=[
                        {"name": "created_at", "label": "Time", "field": "created_at", "align": "left"},
                        {"name": "target", "label": "Target", "field": "target"},
                        {"name": "source", "label": "By", "field": "source"},
                        {"name": "description", "label": "Change", "field": "description", "align": "left"},
                        {"name": "score_delta", "label": "Δ score", "field": "score_delta"},
                        {"name": "status", "label": "Result", "field": "status"},
                        {"name": "reason", "label": "Reason", "field": "reason", "align": "left"},
                    ],
                    rows=[], row_key="id",
                ).classes("w-full")
                ui.label("Commits (one-click rollback)").classes("font-bold mt-4")
                commits_box = ui.column().classes("w-full gap-1")

        # ---------------- handlers ----------------
        def _run_iter() -> None:
            res = controller.request_iteration(manual=True)
            if res.get("status") == "locked":
                ui.notify("Locked — outside the authorized window. Open one in Controls.",
                          type="warning")
            elif res.get("status") == "busy":
                ui.notify("An iteration is already running.", type="warning")
            else:
                ui.notify("Iteration started.", type="positive")

        def _kill() -> None:
            controller.kill()
            ui.notify("Kill switch engaged — reverting uncommitted work.", type="negative")

        def _toggle_suites(value: bool) -> None:
            state["show_suites"] = value
            plot.update_figure(build_figure(db, value))

        # ---------------- periodic refresh ----------------
        async def refresh() -> None:
            # status_snapshot() touches git + Ollama; run it off the event loop.
            snap = await run.io_bound(controller.status_snapshot)
            _render_status(status_chips, snap)
            score_card.value.text = f"{snap['latest_score']:.2f}" if snap["latest_score"] is not None else "—"
            base_card.value.text = f"{snap['baseline_score']:.2f}" if snap["baseline_score"] is not None else "—"
            runs_card.value.text = str(snap["run_count"])
            s = snap["session"]
            sess_card.value.text = (
                f"{s['iterations_used']}/{s['max_iterations']} iters" if s["active"] else "idle"
            )
            phase_label.text = f"{snap['status'].upper()}  ·  {snap['message']}"
            plot.update_figure(build_figure(db, state["show_suites"]))
            log_table.rows = _format_log(db.recent_iterations(60))
            _render_commits(commits_box, controller, db)
            if snap["ollama_up"]:
                chat_banner.content = f"🟢 Connected to Ollama · model **{snap['model']}**"
                chat_banner.classes(replace="w-full text-sm px-3 py-2 rounded bg-green-50")
            else:
                chat_banner.content = (
                    "🔴 **Ollama not detected** — chat is offline. Install it from "
                    "[ollama.com/download](https://ollama.com/download), run "
                    f"`ollama pull {snap['model']}`, then type below (no restart needed). "
                    "Everything else works without it."
                )
                chat_banner.classes(replace="w-full text-sm px-3 py-2 rounded bg-red-50")

        ui.timer(0.1, refresh, once=True)   # first paint, awaited on the event loop
        ui.timer(2.5, refresh)              # then keep it live


# --------------------------------------------------------------------------- #
# small building blocks
# --------------------------------------------------------------------------- #
def _stat_card(title: str, value: str):
    with ui.card().classes("p-3 min-w-44"):
        ui.label(title).classes("text-xs text-slate-500 uppercase")
        val = ui.label(value).classes("text-2xl font-bold")
    card = type("Card", (), {})()
    card.value = val
    return card


def _render_status(container, snap: dict) -> None:
    container.clear()
    with container:
        if snap["authorized"]:
            _chip("AUTHORIZED", "green", "lock_open")
        else:
            nxt = snap.get("next_window")
            _chip(f"LOCKED{' · next ' + nxt if nxt else ''}", "red", "lock")
        if snap["auto_run"]:
            _chip("auto-run ON", "blue", "autorenew")
        _chip("Ollama up" if snap["ollama_up"] else "Ollama down",
              "green" if snap["ollama_up"] else "grey", "smart_toy")
        _chip(snap["model"], "slate", "memory")
        _chip(f"{snap['branch']}@{snap['head']}", "slate", "commit")
        if not snap["tree_clean"]:
            _chip("tree dirty", "orange", "warning")


def _chip(text: str, color: str, icon: str) -> None:
    with ui.element("div").classes(
        f"flex items-center gap-1 px-2 py-1 rounded text-xs bg-{color}-600 text-white"
    ):
        ui.icon(icon).classes("text-sm")
        ui.label(text)


def _format_log(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        delta = r.get("score_delta")
        flag = " ⚑" if r.get("flagged") else ""
        out.append({
            "id": r["id"],
            "created_at": (r["created_at"] or "")[:19].replace("T", " "),
            "target": r.get("target") or "",
            "source": r.get("source") or "",
            "description": (r.get("description") or "") + flag,
            "score_delta": f"{delta:+.2f}" if isinstance(delta, (int, float)) else "—",
            "status": (r.get("status") or "").upper(),
            "reason": r.get("reason") or "",
        })
    return out


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
def _render_chat(box, db: Database) -> None:
    box.clear()
    with box:
        for m in db.chat_history():
            _bubble(m["role"], m["content"])


def _bubble(role: str, content: str):
    mine = role == "user"
    with ui.row().classes("w-full " + ("justify-end" if mine else "justify-start")):
        bubble = ui.markdown(content).classes(
            "px-3 py-2 rounded-lg max-w-3xl "
            + ("bg-sky-100" if mine else "bg-white border")
        )
    return bubble


def _send_chat(box, chat_input) -> None:
    text = (chat_input.value or "").strip()
    if not text:
        return
    chat_input.value = ""
    db: Database = _GLOBALS["db"]
    controller: LoopController = _GLOBALS["controller"]

    db.add_chat("user", text)
    with box:
        _bubble("user", text)
        live = _bubble("assistant", "_…thinking…_")

    q: "queue.Queue[str | None]" = queue.Queue()

    def worker() -> None:
        client = controller._client()
        history = [{"role": m["role"], "content": m["content"]} for m in db.chat_history()]
        acc = ""
        for chunk in client.chat_stream(history):
            acc += chunk
            q.put(chunk)
        q.put(None)
        db.add_chat("assistant", acc)

    threading.Thread(target=worker, daemon=True).start()

    buf = {"text": ""}
    timer_holder: dict = {}

    def flush() -> None:
        try:
            while True:
                c = q.get_nowait()
                if c is None:
                    timer_holder["t"].deactivate()
                    return
                buf["text"] += c
                live.content = buf["text"]
        except queue.Empty:
            pass

    timer_holder["t"] = ui.timer(0.1, flush)


# --------------------------------------------------------------------------- #
# controls
# --------------------------------------------------------------------------- #
def _build_controls(controller: LoopController, db: Database, config: Config) -> None:
    with ui.card().classes("w-full"):
        ui.label("Run mode").classes("font-bold")
        with ui.row().classes("items-center gap-4"):
            auto = ui.switch("Auto-run inside authorized windows",
                             value=bool(config.get("auto_run")))
            auto.on_value_change(lambda e: config.set("auto_run", bool(e.value)))

    with ui.card().classes("w-full"):
        ui.label("Local model (Ollama)").classes("font-bold")
        with ui.row().classes("items-center gap-3"):
            model = ui.input("Model", value=str(config.get("ollama_model"))).props("outlined dense")
            model.on_value_change(lambda e: config.set("ollama_model", e.value))
            url = ui.input("Ollama URL", value=str(config.get("ollama_url")))\
                .props("outlined dense").classes("w-72")
            url.on_value_change(lambda e: config.set("ollama_url", e.value))
            strat = ui.select(["auto", "llm", "heuristic"], label="Improver strategy",
                              value=str(config.get("improver_strategy"))).props("outlined dense")
            strat.on_value_change(lambda e: config.set("improver_strategy", e.value))

    with ui.card().classes("w-full"):
        ui.label("Session budget (does not roll past a window)").classes("font-bold")
        with ui.row().classes("items-center gap-4"):
            mi = ui.number("Max iterations", value=int(config.get("budget_max_iterations")),
                           min=1, max=1000, format="%d").props("outlined dense")
            mi.on_value_change(lambda e: config.set("budget_max_iterations", int(e.value or 1)))
            mm = ui.number("Max minutes", value=int(config.get("budget_max_minutes")),
                           min=1, max=1440, format="%d").props("outlined dense")
            mm.on_value_change(lambda e: config.set("budget_max_minutes", int(e.value or 1)))

    with ui.card().classes("w-full"):
        ui.label("Authorized windows").classes("font-bold")
        windows_box = ui.column().classes("w-full gap-1")

        def redraw_windows() -> None:
            windows_box.clear()
            wins = config.get("authorized_windows") or []
            with windows_box:
                if not wins:
                    ui.label("No windows — the loop is permanently locked.")\
                        .classes("text-sm text-red-500")
                for i, w in enumerate(wins):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(_window_text(w)).classes("text-sm")
                        ui.button(icon="delete", on_click=lambda _, idx=i: remove_window(idx))\
                            .props("flat dense color=red")

        def remove_window(idx: int) -> None:
            wins = list(config.get("authorized_windows") or [])
            if 0 <= idx < len(wins):
                wins.pop(idx)
                config.set("authorized_windows", wins)
            redraw_windows()

        def add_now(minutes: int) -> None:
            wins = list(config.get("authorized_windows") or [])
            wins.append(scheduler.authorize_now_window(minutes))
            config.set("authorized_windows", wins)
            redraw_windows()
            ui.notify(f"Authorized a {minutes}-minute window starting now.", type="positive")

        ui.separator()
        with ui.row().classes("items-center gap-2"):
            ui.label("Add weekly window:").classes("text-sm")
            days = ui.select({i: WEEKDAYS[i] for i in range(7)}, multiple=True,
                             value=[0, 1, 2, 3, 4], label="Days").props("outlined dense").classes("w-56")
            start = ui.input("Start", value="22:00").props("outlined dense").classes("w-24")
            end = ui.input("End", value="24:00").props("outlined dense").classes("w-24")

            def add_weekly() -> None:
                wins = list(config.get("authorized_windows") or [])
                wins.append({"type": "weekly", "days": list(days.value or []),
                             "start": start.value, "end": end.value})
                config.set("authorized_windows", wins)
                redraw_windows()
                ui.notify("Weekly window added.", type="positive")

            ui.button("Add", icon="add", on_click=add_weekly).props("dense")
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.button("Authorize 60 min now", icon="lock_clock",
                      on_click=lambda: add_now(60)).props("outline dense")
            ui.button("Authorize 120 min now", icon="lock_clock",
                      on_click=lambda: add_now(120)).props("outline dense")
        redraw_windows()


def _window_text(w: dict) -> str:
    if w.get("type") == "once":
        return f"📅 once · {w.get('date')} · {w.get('start')}–{w.get('end')}"
    days = ", ".join(WEEKDAYS[d] for d in w.get("days", []))
    return f"🔁 weekly · {days or '(no days)'} · {w.get('start')}–{w.get('end')}"


# --------------------------------------------------------------------------- #
# commits / rollback
# --------------------------------------------------------------------------- #
def _render_commits(box, controller: LoopController, db: Database) -> None:
    box.clear()
    with box:
        try:
            commits = controller.git.log(15)
        except Exception:  # noqa: BLE001
            ui.label("(git log unavailable)")
            return
        for c in commits:
            with ui.row().classes("items-center gap-2 w-full"):
                ui.label(c.short).classes("font-mono text-xs text-slate-500")
                ui.label(c.subject).classes("text-sm flex-grow truncate")
                ui.button("Rollback", icon="undo",
                          on_click=lambda _, h=c.hash: _do_rollback(controller, h))\
                    .props("flat dense color=orange")


def _do_rollback(controller: LoopController, commit: str) -> None:
    res = controller.rollback_to(commit)
    if res.get("ok"):
        ui.notify(f"Rolled back to {res['commit']} (re-baselined at {res['aggregate']:.2f}).",
                  type="positive")
    else:
        ui.notify(f"Rollback failed: {res.get('error')}", type="negative")


# Module-level handle to the singletons (set by create_app) so nested callbacks
# that can't close over them (e.g. chat) can still reach them.
_GLOBALS: dict = {}


def _install_globals(controller, db, config) -> None:
    _GLOBALS.update(controller=controller, db=db, config=config)
