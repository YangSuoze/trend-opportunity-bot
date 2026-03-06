# Trend Opportunity Viewer (web)

A local React + TypeScript UI to view and run `trend-opportunity-bot` workflows.

## Run

```bash
# terminal 1 (from repo root)
trendbot serve --port 8000

# terminal 2
cd web
pnpm install
pnpm dev
```

Then open the dev URL (usually http://localhost:5173).

## Use
- API mode is default: run `Collect`, `Analyze`, `Report` from the left run panel.
- Local file mode keeps the existing file picker flow for `opportunities.jsonl`, `signals.jsonl`, and `report.md`.
- Use left-side filters (`source`, `min score`, `keyword`) to narrow cards.
- The main area is now a vertical card feed with one-card snap scrolling:
  - Mouse wheel / trackpad snaps to the next or previous card.
  - Keyboard navigation in feed: `ArrowUp`, `ArrowDown`, `PageUp`, `PageDown`, `Home`, `End`.

## Dashboard Style Notes
- Xiaohongshu creator dashboard visual language: white canvas, clean spacing, and card-first structure.
- Accent color is fixed to brand red `#FF2442`; Bauhaus yellow/blue blocks are removed.
- Surfaces use large rounded corners and soft layered shadows instead of hard borders.
- Mode switching follows a segmented-control pattern with a muted track and elevated active segment.
- Data modules are tuned for dashboard readability:
  - Inline donut chart for six scoring dimensions.
  - Progress bars and qualitative signal blocks with red gradient fill and soft tracks.
- Opportunity cards remain information-dense but lightweight:
  - Big total score, `zh_summary`, source badge + source title link.
  - Expand/collapse detail area for `trigger`, `pain`, `alternatives`, `pricing_reason`, `zh_analysis`.

## Notes
- API mode auto-refreshes opportunities/report after each finished job.
- Local file mode still cannot tail files; click **Reload** to re-read selected files.
