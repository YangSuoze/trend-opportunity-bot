# trend-opportunity-bot（中文）

一个“趋势信号 → 机会假设卡”的命令行工具：
- 采集：产品/代码/舆情相关的趋势信号（GitHub / Hacker News / 可选：Product Hunt / Reddit / DEV.to / Substack RSS）
- 归一化 + 去重：统一成 `Signal` 结构，输出 JSONL
- 分析：调用 OpenAI-compatible 模型（默认 `qwen3-max`）生成「机会假设卡」+ 6 维度打分
- 报告：输出按总分排序的 Markdown
- Web 前端：本地加载 `opportunities.jsonl` 展示、筛选、查看详情（无后端）

## 环境要求
- Python >= 3.11
- Node.js + pnpm（仅 Web 前端需要）

## 配置（.env）
复制模板并填写：

```bash
cp .env.example .env
```

关键变量：
- `OPENAI_BASE_URL`：OpenAI-compatible base url
- `OPENAI_API_KEY`
- `OPENAI_MODEL`：默认 `qwen3-max`
- `GITHUB_TOKEN`：建议配置（避免 GitHub 限流）

可选数据源：
- `PRODUCTHUNT_TOKEN`
- Reddit：`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` / `REDDIT_SUBREDDITS`
- DEV.to：`DEVTO_TAGS`
- Substack：`SUBSTACK_FEEDS`

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

开发依赖（ruff/pytest）：

```bash
pip install -e .[dev]
```

## 用法

### 1) 采集

```bash
trendbot collect --window 24h --out artifacts/signals.jsonl
```

### 2) 分析（带进度 + 实时写入）

```bash
trendbot analyze --in artifacts/signals.jsonl --out artifacts/opportunities.jsonl --top 30
```

说明：
- 会打印实时进度：`[i/N] analyzing ... (source=...)`
- **每分析完一个就 append 一行到输出 JSONL**（可 `tail -f` 观察）
- 默认 `--resume`：如果 out 已存在，会跳过已分析过的 `source_fingerprint`，避免重复
- 想从头生成：加 `--no-resume`

### 3) 生成报告

```bash
trendbot report --in artifacts/opportunities.jsonl --out artifacts/report.md
```

## Web 前端（本地查看 JSONL）
Web 前端目录在 `web/`，纯本地文件模式，无后端。

### 本地运行

```bash
cd web
pnpm install
pnpm dev
```

然后在浏览器里：
- 选择加载 `opportunities.jsonl`（必选）
- 可选加载 `signals.jsonl` / `report.md`

### 部署（静态站点）

#### 方式 A：Vercel（推荐）
1. 将本仓库导入 Vercel
2. Root Directory 选择 `web`
3. Build Command：`pnpm install && pnpm build`
4. Output Directory：`dist`

#### 方式 B：Netlify
- Base directory：`web`
- Build command：`pnpm install && pnpm build`
- Publish directory：`web/dist`

#### 方式 C：GitHub Pages
1. 本地构建：
   ```bash
   cd web
   pnpm install
   pnpm build
   ```
2. 将 `web/dist` 发布为 Pages（你可以用 gh-pages 分支或 GitHub Actions）

> 注意：前端通过文件选择器读取本地 JSONL，浏览器无法实时 tail 文件；如果 `trendbot analyze` 正在持续写入，点击页面的 **Reload** 重新读取即可。
