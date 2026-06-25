# Ai-Improve

## Daily Interest Trading Projection

An adjustable, dependency-free graph that projects trading account growth from
**daily compound interest**.

### Defaults
- **Starting amount:** $2,660
- **Investment percentage:** 99% (the share of the balance traded each day)
- **Time period:** 6 months
- **Daily interest rate:** 1% (adjustable)

### Usage
Open `index.html` in any modern browser — no build step, no internet, no
dependencies. Drag the sliders (or type into the number fields) to adjust:

- Starting amount
- Investment percentage
- Daily interest rate
- Time period (months)
- Trade weekdays only (~21 days/month) vs. every calendar day (30 days/month)
- Linear or logarithmic Y axis

The chart and the summary stats (final balance, total profit, ROI, effective
daily/monthly growth) update live. Hover the chart for the projected balance on
any day.

### The model
Each trading day, the invested portion earns the daily rate while the
un-invested portion stays flat, so the balance grows by a fixed factor per day:

```
g = 1 + (investment% / 100) × (daily rate / 100)
balance(day i) = starting amount × g^i
```

With the defaults (2,660 · 99% · 1%/day · 180 days) that projects to about
**$15,667** — a ~489% return.

> Projection tool only. This is a mathematical model of constant compounding,
> not a prediction of real market returns, and not financial advice.

### Files
- `index.html` — markup and controls
- `styles.css` — styling
- `projection.js` — projection math and the canvas chart
