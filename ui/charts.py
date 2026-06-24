"""Plotly figure builders for the improvement graph.

Kept separate from the NiceGUI layout so the charting logic is easy to test on its
own (it only needs a ``Database``). The x-axis is the benchmark-run sequence; each
point is one recorded run (baseline, kept, or reverted).
"""
from __future__ import annotations

from collections import defaultdict

import plotly.graph_objects as go

from core.db import Database

_LABEL_COLOR = {"baseline": "#3b82f6", "kept": "#22c55e", "reverted": "#ef4444"}


def build_figure(db: Database, show_suites: bool = False) -> go.Figure:
    runs = db.runs_for_graph()
    fig = go.Figure()

    if not runs:
        fig.update_layout(
            title="No benchmark runs yet — run an iteration to populate the graph.",
            height=420, template="plotly_white",
        )
        return fig

    xs = list(range(1, len(runs) + 1))
    run_index = {r["id"]: i + 1 for i, r in enumerate(runs)}
    aggregates = [r["aggregate"] for r in runs]
    hover = [
        f"run {x}<br>{r['label']}<br>commit {r['commit_hash']}<br>agg {r['aggregate']:.2f}"
        for x, r in zip(xs, runs)
    ]

    # Main aggregate trace.
    fig.add_trace(go.Scatter(
        x=xs, y=aggregates, mode="lines+markers", name="aggregate",
        line=dict(color="#0ea5e9", width=2),
        marker=dict(size=9, color=[_LABEL_COLOR.get(r["label"], "#64748b") for r in runs]),
        text=hover, hoverinfo="text",
    ))

    # Reverted iterations get a distinct red ✕ overlay so failures stand out.
    rev_x = [x for x, r in zip(xs, runs) if r["label"] == "reverted"]
    rev_y = [a for a, r in zip(aggregates, runs) if r["label"] == "reverted"]
    if rev_x:
        fig.add_trace(go.Scatter(
            x=rev_x, y=rev_y, mode="markers", name="reverted",
            marker=dict(symbol="x", size=13, color="#ef4444", line=dict(width=2)),
        ))

    # Per-suite breakdown (averaged score per suite per run).
    if show_suites:
        by_run_suite: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in db.task_scores_for_runs():
            by_run_suite[row["run_id"]][row["suite"]].append(row["score"])
        suites = sorted({r["suite"] for r in db.task_scores_for_runs()})
        for suite in suites:
            ys = []
            for r in runs:
                vals = by_run_suite.get(r["id"], {}).get(suite)
                ys.append(round(sum(vals) / len(vals), 2) if vals else None)
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines+markers", name=f"suite: {suite}",
                line=dict(width=1, dash="dot"), connectgaps=True,
            ))

    fig.update_layout(
        title="Self-benchmark aggregate score over iterations",
        xaxis_title="benchmark run #", yaxis_title="score (0–100)",
        yaxis=dict(range=[0, 105]), height=440, template="plotly_white",
        legend=dict(orientation="h", y=-0.2), margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig
