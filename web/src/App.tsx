import { useEffect, useMemo, useState } from 'react'
import './App.css'
import type { OpportunityCard } from './types'
import { parseOpportunitiesJsonl, parseSignalsJsonl } from './parsers'
import { applyTheme, readTheme, writeTheme, type Theme } from './theme'
import { useFileText } from './useFileText'

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n))
}

function uniq(values: string[]) {
  return Array.from(new Set(values))
}

function normalize(s: string) {
  return s.trim().toLowerCase()
}

function linkLabel(url: string) {
  try {
    const u = new URL(url)
    return u.hostname.replace(/^www\./, '')
  } catch {
    return 'link'
  }
}

export default function App() {
  const opportunitiesFile = useFileText()
  const signalsFile = useFileText()
  const reportFile = useFileText()

  const opportunitiesText = opportunitiesFile.loaded?.text ?? ''
  const signalsText = signalsFile.loaded?.text ?? ''

  const [theme, setTheme] = useState<Theme>(() => readTheme())

  const [sourceFilter, setSourceFilter] = useState<string>('')
  const [minScore, setMinScore] = useState<number>(0)
  const [keyword, setKeyword] = useState<string>('')
  const [selected, setSelected] = useState<OpportunityCard | null>(null)

  useEffect(() => {
    applyTheme(theme)
    writeTheme(theme)
  }, [theme])

  const opportunitiesParse = useMemo(() => {
    if (!opportunitiesText) return null
    return parseOpportunitiesJsonl(opportunitiesText)
  }, [opportunitiesText])

  const signalsParse = useMemo(() => {
    if (!signalsText) return null
    return parseSignalsJsonl(signalsText)
  }, [signalsText])

  const reportText = reportFile.loaded?.text ?? ''

  const opportunities = useMemo(() => {
    const rows = opportunitiesParse?.records ?? []
    return [...rows].sort((a, b) => b.scoring.total - a.scoring.total)
  }, [opportunitiesParse?.records])

  const sources = useMemo(() => {
    return uniq(opportunities.map((o) => o.source)).sort()
  }, [opportunities])

  const filtered = useMemo(() => {
    const k = normalize(keyword)
    return opportunities.filter((o) => {
      if (sourceFilter && o.source !== sourceFilter) return false
      if (o.scoring.total < minScore) return false
      if (!k) return true

      const hay = normalize(
        [o.solution, o.source_title, o.zh_summary, o.zh_analysis].filter(Boolean).join(' \n '),
      )
      return hay.includes(k)
    })
  }, [keyword, minScore, opportunities, sourceFilter])

  const stats = useMemo(() => {
    const total = opportunities.length
    const shown = filtered.length
    const max = opportunities[0]?.scoring.total ?? 0
    return { total, shown, max }
  }, [filtered.length, opportunities])

  const onPick = async (kind: 'opps' | 'signals' | 'report', file: File) => {
    if (kind === 'opps') await opportunitiesFile.load(file)
    if (kind === 'signals') await signalsFile.load(file)
    if (kind === 'report') await reportFile.load(file)
  }

  const reloadAll = async () => {
    await opportunitiesFile.reload()
    await signalsFile.reload()
    await reportFile.reload()
  }

  const themeLabel = theme === 'dark' ? 'Dark' : 'Light'

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand">
          <h1>Trend Opportunity Viewer</h1>
          <div className="sub">Load JSONL outputs and explore ranked opportunity cards (local-only, no backend).</div>
        </div>
        <div className="pills">
          <span className="pill pillRed">cards: <b>{stats.total}</b></span>
          <span className="pill pillYellow">shown: <b>{stats.shown}</b></span>
          <span className="pill pillBlue">max score: <b>{stats.max}</b></span>
          <button className="btn btnBlue" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{themeLabel}</button>
        </div>
      </div>

      <div className="mainLayout">
        <div className="controlsColumn">
          <div className="card filesCard">
            <div className="sectionTitle sectionTitleRed">
              <h2>Files</h2>
              <div className="hint">Browser can't tail local files; use Reload to re-read.</div>
            </div>

            <div className="row">
              <div className="field">
                <label>opportunities.jsonl (required)</label>
                <input
                  type="file"
                  accept=".jsonl,.txt,application/json"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) void onPick('opps', f)
                  }}
                />
                <div className="small">
                  {opportunitiesFile.loaded ? (
                    <span className="badge">{opportunitiesFile.loaded.name} • {opportunitiesFile.loaded.size} bytes</span>
                  ) : (
                    <span className="warn">not loaded</span>
                  )}
                  {opportunitiesFile.error ? <span className="warn"> • {opportunitiesFile.error}</span> : null}
                </div>
              </div>

              <div className="field">
                <label>signals.jsonl (optional)</label>
                <input
                  type="file"
                  accept=".jsonl,.txt,application/json"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) void onPick('signals', f)
                  }}
                />
                <div className="small">
                  {signalsFile.loaded ? (
                    <span className="badge">{signalsFile.loaded.name}</span>
                  ) : (
                    <span className="badge">not loaded</span>
                  )}
                  {signalsFile.error ? <span className="warn"> • {signalsFile.error}</span> : null}
                </div>
              </div>

              <div className="field">
                <label>report.md (optional)</label>
                <input
                  type="file"
                  accept=".md,.txt,text/markdown"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) void onPick('report', f)
                  }}
                />
                <div className="small">
                  {reportFile.loaded ? (
                    <span className="badge">{reportFile.loaded.name}</span>
                  ) : (
                    <span className="badge">not loaded</span>
                  )}
                  {reportFile.error ? <span className="warn"> • {reportFile.error}</span> : null}
                </div>
              </div>

              <button
                className="btn btnRed"
                onClick={() => void reloadAll()}
                disabled={!opportunitiesFile.file && !signalsFile.file && !reportFile.file}
              >
                Reload
              </button>
            </div>

            {opportunitiesParse?.warnings?.length ? (
              <div className="small warn parseWarn">
                Parsed with warnings ({opportunitiesParse.warnings.length}): {opportunitiesParse.warnings.slice(0, 3).join(' • ')}
              </div>
            ) : null}

            <div className="footer">
              Tip: while running <code>trendbot analyze</code>, keep generating <code>opportunities.jsonl</code>, then click Reload here to
              refresh.
            </div>
          </div>

          <div className="card filtersCard">
            <div className="sectionTitle sectionTitleBlue">
              <h2>Filters</h2>
              <div className="hint">Search covers solution/source_title/zh_summary/zh_analysis</div>
            </div>
            <div className="row">
              <div className="field">
                <label>Source</label>
                <select value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)}>
                  <option value="">All</option>
                  {sources.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>Min score</label>
                <input
                  type="number"
                  value={minScore}
                  min={0}
                  max={30}
                  onChange={(e) => setMinScore(clamp(Number(e.target.value), 0, 30))}
                />
                <input
                  type="range"
                  value={minScore}
                  min={0}
                  max={30}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                />
              </div>
              <div className="field fieldWide">
                <label>Keyword</label>
                <input type="text" placeholder="e.g. RAG / 价格 / developer" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
              </div>
              <button className="btn btnYellow" onClick={() => { setSourceFilter(''); setMinScore(0); setKeyword('') }}>Reset</button>
            </div>

            {reportText ? (
              <div className="auxSection reportSection">
                <div className="sectionTitle sectionTitleGray">
                  <h2>Report.md (preview)</h2>
                  <div className="hint">Loaded, not parsed.</div>
                </div>
                <div className="tableWrap tableWrapInset">
                  <div className="small reportPreview">
                    {reportText.slice(0, 1200)}
                    {reportText.length > 1200 ? '\n\n…' : ''}
                  </div>
                </div>
              </div>
            ) : null}

            {signalsParse?.records?.length ? (
              <div className="auxSection signalsSection">
                <div className="sectionTitle sectionTitleYellow">
                  <h2>Signals</h2>
                  <div className="hint">{signalsParse.records.length} loaded</div>
                </div>
                <div className="small">Signals are currently not joined to cards; used only for optional context.</div>
              </div>
            ) : null}
          </div>
        </div>

        <div className="tableColumn">
          <div className="card tableCard">
            <div className="sectionTitle sectionTitleYellow">
              <h2>Opportunity Cards</h2>
              <div className="hint">Click a row to open details.</div>
            </div>

            <div className="tableWrap">
              <table>
                <thead>
                  <tr>
                    <th className="thScore">Total</th>
                    <th>Solution</th>
                    <th className="thTarget">Target user</th>
                    <th className="thSource">Source</th>
                    <th>Source title</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((o) => (
                    <tr key={o.source_fingerprint || o.source_url} onClick={() => setSelected(o)}>
                      <td className="score">{o.scoring.total}</td>
                      <td>{o.solution}</td>
                      <td>{o.target_user}</td>
                      <td><span className="badge">{o.source}</span></td>
                      <td>
                        <a href={o.source_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                          {o.source_title}
                        </a>
                        <span className="small sourceHost">({linkLabel(o.source_url)})</span>
                      </td>
                    </tr>
                  ))}
                  {!filtered.length ? (
                    <tr>
                      <td colSpan={5} className="small emptyState">
                        No results. Load opportunities.jsonl or relax filters.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      {selected ? (
        <div className="modalOverlay" role="dialog" aria-modal="true" onClick={() => setSelected(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h3>{selected.solution}</h3>
                <div className="small modalMeta">
                  <span className="badge">{selected.source}</span> • score <b>{selected.scoring.total}</b> •{' '}
                  <a href={selected.source_url} target="_blank" rel="noreferrer">{selected.source_title}</a>
                </div>
              </div>
              <button className="btn btnRed" onClick={() => setSelected(null)}>Close</button>
            </div>

            <div className="kv">
              <div className="k">zh_summary</div>
              <div className="v">{selected.zh_summary || '—'}</div>
              <div className="k">zh_analysis</div>
              <div className="v">{selected.zh_analysis || '—'}</div>
            </div>

            <div className="kv">
              <div className="k">target_user</div>
              <div className="v">{selected.target_user}</div>
              <div className="k">trigger</div>
              <div className="v">{selected.trigger}</div>
            </div>

            <div className="kv">
              <div className="k">pain</div>
              <div className="v">{selected.pain}</div>
              <div className="k">existing_alternatives</div>
              <div className="v">{selected.existing_alternatives}</div>
            </div>

            <div className="kv">
              <div className="k">pricing_reason</div>
              <div className="v">{selected.pricing_reason}</div>
              <div className="k">validation_7d</div>
              <div className="v">{selected.validation_7d}</div>
              <div className="k">success_signal</div>
              <div className="v">{selected.success_signal}</div>
            </div>

            <div className="footer">
              Browser local-file mode: choose files again if your OS blocks re-reading; Reload usually works.
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
