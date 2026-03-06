# trend-opportunity-bot

Production-ready Python CLI to collect trend signals and generate ranked opportunity cards.

## Features
- Collectors
- GitHub GraphQL repository search with custom/default queries
- Hacker News Firebase ingestion (`top`, `new`, `show`) with GitHub URL extraction
- Optional Product Hunt GraphQL ingestion (today posts when token exists)
- Optional Reddit OAuth ingestion from configured subreddits
- Optional DEV.to ingestion from configured tags via official REST API
- Optional Substack RSS ingestion from configured feed URLs
- Normalize and deduplicate into unified `Signal` schema with stable fingerprint
- Analyze top signals via OpenAI-compatible Chat Completions
- Generate markdown report sorted by total score

## Requirements
- Python `>=3.11`

## Environment
Create `.env` from template:

```bash
cp .env.example .env
```

Supported variables:
- `OPENAI_BASE_URL` (OpenAI-compatible base URL)
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (default: `qwen3-max`)
- `GITHUB_TOKEN` (optional but required for GitHub GraphQL collector)
- `PRODUCTHUNT_TOKEN` (optional)
- `REDDIT_CLIENT_ID` (optional, required with `REDDIT_CLIENT_SECRET` for Reddit collector)
- `REDDIT_CLIENT_SECRET` (optional)
- `REDDIT_USER_AGENT` (optional, recommended by Reddit API rules)
- `REDDIT_SUBREDDITS` (optional comma-separated list, enables Reddit collector)
- `DEVTO_TAGS` (optional comma-separated list, enables DEV.to collector)
- `SUBSTACK_FEEDS` (optional comma-separated RSS feed URLs, enables Substack collector)

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

For development:

```bash
pip install -e .[dev]
```

## Usage
Manual commands only (no cron in this repository).

Collect:

```bash
trendbot collect --window 24h --out artifacts/signals.jsonl
```

Collect with custom GitHub query + mode:

```bash
trendbot collect \
  --window 48h \
  --out artifacts/signals.jsonl \
  --github-query "rag orchestration agent" \
  --github-query "python eval framework" \
  --github-language python \
  --hn-mode top \
  --limit 40
```

Collect with optional Reddit + DEV.to + Substack sources:

```bash
trendbot collect \
  --window 48h \
  --out artifacts/signals.jsonl \
  --reddit-subreddit SideProject \
  --reddit-subreddit startups \
  --devto-tag saas \
  --devto-tag buildinpublic \
  --substack-feed https://www.lennysnewsletter.com/feed \
  --limit 40
```

Analyze:

```bash
trendbot analyze --in artifacts/signals.jsonl --out artifacts/opportunities.jsonl --top 30
```

Report:

```bash
trendbot report --in artifacts/opportunities.jsonl --out artifacts/report.md
```

## Data Schemas
`Signal` fields:
- `source`
- `title`
- `url`
- `description`
- `tags: list[str]`
- `metrics: dict`
- `captured_at` (ISO datetime)
- `fingerprint` (sha256 of normalized url + normalized title)

Opportunity card fields:
- `target_user`
- `trigger`
- `pain`
- `existing_alternatives`
- `solution`
- `pricing_reason`
- `validation_7d`
- `success_signal`
- `scoring` with 6 dimensions (`0-5`) + `total`

## Quality
- Unit tests mock `httpx` and do not require network
- Ruff linting
- GitHub Actions CI runs lint + tests
