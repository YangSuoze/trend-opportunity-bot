# Trend Opportunity Viewer (web)

A local React + TypeScript UI focused on **today's API results** for `trend-opportunity-bot`.

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
- UI is API-only now.
- Mode switching (API/file), left-side config forms, and run panels are removed.
- The page auto-fetches artifacts on startup and shows only local-today data.
- A compact header shows `Last updated` and a manual `Refresh` button.

## Today's Filtering Rules
- Signals:
  - Use `captured_at` when present.
  - If `captured_at` is missing/invalid, treat that signal as today.
- Opportunities:
  - Use `generated_at` when present.
  - If missing/invalid, fallback to matching source artifact timestamp from signals (`source_fingerprint`, then `source_url`).
  - If still unavailable, treat that opportunity as today.

All comparisons use **local time** day boundaries.

## Auto Refresh Schedule
- Startup: fetches API artifacts immediately.
- Morning open: before 09:00 local time, startup fetch ensures the page has a daily pre-09:00 refresh.
- Long-running tab: schedules an automatic refresh at 09:00 local time, then repeats daily at 09:00.

## Interaction
- Main area remains a one-card-at-a-time vertical feed.
- Snap interaction is preserved:
  - Mouse wheel / trackpad snaps to previous/next card.
  - Drag/swipe is supported on desktop and mobile.
  - Keyboard navigation: `ArrowUp`, `ArrowDown`, `PageUp`, `PageDown`, `Home`, `End`.

## Mobile
- Layout is single-column and responsive.
- Tap targets are enlarged for touch usage.
