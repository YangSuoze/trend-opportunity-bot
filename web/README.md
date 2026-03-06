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
- API mode is default: run `Collect`, `Analyze`, `Report` from the Run panel
- Local file mode keeps the existing file picker flow
- Use filters (source/min score/keyword) and click a row for details

## Notes
- API mode auto-refreshes opportunities/report after each finished job.
- Local file mode still cannot tail files; click **Reload** to re-read selected files.

## Bauhaus UI redesign decisions
- Primary palette is strict Bauhaus: `#E94B3C` (red), `#F2C94C` (yellow), `#2F80ED` (blue), plus black/white/gray neutrals.
- Typography uses Montserrat (loaded from Google Fonts in `index.html`) with geometric sans fallbacks in `src/index.css`.
- Layout is asymmetrical but balanced: a fixed-width controls column on the left and a flexible table workspace on the right.
- Header composition uses geometric blocks and an offset baseline line to establish industrial visual hierarchy.
- Surfaces are hard-edged with thick strokes, square corners, and offset hard shadows for buttons/cards/pills.
- Tables and separators use bold gridlines to reinforce form-follows-function readability.
- Status indicators are rendered as high-contrast color blocks (pills, badges, section labels).
- Background uses CSS-only subtle geometry: faint grid plus sparse circle/triangle motifs.
- Accessibility: high-contrast text/background pairings and explicit `:focus-visible` outlines on interactive elements.
