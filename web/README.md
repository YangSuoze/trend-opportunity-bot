# Trend Opportunity Viewer (web)

A local-only React + TypeScript UI to view `trend-opportunity-bot` outputs.

## Run

```bash
cd web
pnpm install
pnpm dev
```

Then open the dev URL (usually http://localhost:5173).

## Use
- Load `opportunities.jsonl` (required)
- Optionally load `signals.jsonl` and `report.md`
- Use filters (source/min score/keyword) and click a row for details

## Notes
Browsers cannot tail local files. If `trendbot analyze` is still running and appending to the JSONL, click **Reload** to re-read the selected file.
