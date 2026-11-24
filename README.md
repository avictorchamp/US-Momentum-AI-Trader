# US Momentum AI Trader — MVP

Dashboard with live scan API, local portfolio tracker, risk calculator and paper journal. Paper trading only.

## Pages
- Overview and sample market regime
- Momentum scanner with search and status filters
- Risk monitor and deterministic position-size calculator
- Paper trade journal (browser-local demo record)

## Deploy
Render Static Site:
- Build command: `echo "Static site ready"`
- Publish directory: `.`
- Branch: `main`

## Important
Scanner uses Market API data (may be delayed or incomplete). Portfolio and paper journal use local browser storage and are not synced/backed up. Market regime automation and broker execution are not connected. Paper trading only; do not use as automatic real-money advice.
