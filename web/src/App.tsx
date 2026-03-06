import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { parseOpportunitiesJsonl, parseSignalsJsonl } from './parsers'
import { applyTheme, readTheme, writeTheme, type Theme } from './theme'
import type { OpportunityCard, SignalRecord } from './types'
import { useFileText } from './useFileText'

const DEFAULT_API_BASE = import.meta.env.VITE_TRENDBOT_API_BASE ?? 'http://127.0.0.1:8000'

type ViewMode = 'api' | 'file'
type JobKind = 'collect' | 'analyze' | 'report'
type JobStatus = 'queued' | 'running' | 'done' | 'error'

type EventType = 'progress' | 'card' | 'done' | 'error' | 'system'

interface ApiStatusPayload {
  version: string
  artifacts: {
    signals: string
    opportunities: string
    report: string
  }
}

interface JobState {
  id: string
  kind: JobKind
  status: JobStatus
}

interface JobLogEntry {
  type: EventType
  message: string
}

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

function totalScore(card: OpportunityCard) {
  const value = Number(card.scoring?.total ?? 0)
  return Number.isFinite(value) ? value : 0
}

function parseSseData(raw: string): Record<string, unknown> {
  try {
    const value = JSON.parse(raw)
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>
    }
  } catch {
    return {}
  }
  return {}
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

async function postJson<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.text()
}

export default function App() {
  const opportunitiesFile = useFileText()
  const signalsFile = useFileText()
  const reportFile = useFileText()

  const opportunitiesText = opportunitiesFile.loaded?.text ?? ''
  const signalsText = signalsFile.loaded?.text ?? ''

  const [theme, setTheme] = useState<Theme>(() => readTheme())
  const [mode, setMode] = useState<ViewMode>('api')
  const [apiBase] = useState(DEFAULT_API_BASE)

  const [apiStatus, setApiStatus] = useState<ApiStatusPayload | null>(null)
  const [apiOpportunities, setApiOpportunities] = useState<OpportunityCard[]>([])
  const [apiSignals, setApiSignals] = useState<SignalRecord[]>([])
  const [apiReport, setApiReport] = useState<string>('')
  const [apiError, setApiError] = useState<string>('')
  const [isApiLoading, setIsApiLoading] = useState(false)

  const [collectWindow, setCollectWindow] = useState('24h')
  const [collectLimit, setCollectLimit] = useState(30)
  const [analyzeTop, setAnalyzeTop] = useState(30)
  const [analyzeResume, setAnalyzeResume] = useState(true)

  const [activeJob, setActiveJob] = useState<JobState | null>(null)
  const [jobEvents, setJobEvents] = useState<JobLogEntry[]>([])
  const [jobError, setJobError] = useState('')
  const [isSubmittingJob, setIsSubmittingJob] = useState(false)

  const [sourceFilter, setSourceFilter] = useState<string>('')
  const [minScore, setMinScore] = useState<number>(0)
  const [keyword, setKeyword] = useState<string>('')
  const [selected, setSelected] = useState<OpportunityCard | null>(null)

  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    applyTheme(theme)
    writeTheme(theme)
  }, [theme])

  const closeEventStream = useCallback(() => {
    eventSourceRef.current?.close()
    eventSourceRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      closeEventStream()
    }
  }, [closeEventStream])

  const appendJobEvent = useCallback((entry: JobLogEntry) => {
    setJobEvents((current) => {
      const next = [...current, entry]
      return next.length > 120 ? next.slice(next.length - 120) : next
    })
  }, [])

  const refreshApiArtifacts = useCallback(async () => {
    setIsApiLoading(true)
    setApiError('')
    try {
      const [statusPayload, signalsPayload, opportunitiesPayload, reportPayload] = await Promise.all([
        fetchJson<ApiStatusPayload>(`${apiBase}/api/status`),
        fetchJson<SignalRecord[]>(`${apiBase}/api/artifacts/signals`),
        fetchJson<OpportunityCard[]>(`${apiBase}/api/artifacts/opportunities`),
        fetchText(`${apiBase}/api/artifacts/report`),
      ])

      setApiStatus(statusPayload)
      setApiSignals(Array.isArray(signalsPayload) ? signalsPayload : [])
      setApiOpportunities(Array.isArray(opportunitiesPayload) ? opportunitiesPayload : [])
      setApiReport(reportPayload)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error))
    } finally {
      setIsApiLoading(false)
    }
  }, [apiBase])

  useEffect(() => {
    if (mode !== 'api') return
    void refreshApiArtifacts()
  }, [mode, refreshApiArtifacts])

  const finalizeJob = useCallback(
    async (jobId: string) => {
      try {
        const snapshot = await fetchJson<{ status: JobStatus; error?: string }>(`${apiBase}/api/jobs/${jobId}`)
        setActiveJob((current) => {
          if (!current || current.id !== jobId) return current
          return { ...current, status: snapshot.status }
        })
        if (snapshot.status === 'error' && snapshot.error) {
          setJobError(snapshot.error)
        }
      } catch {
        setJobError('Failed to fetch final job status.')
      }

      closeEventStream()
      if (mode === 'api') {
        await refreshApiArtifacts()
      }
    },
    [apiBase, closeEventStream, mode, refreshApiArtifacts],
  )

  const connectJobStream = useCallback(
    (job: JobState) => {
      closeEventStream()
      const source = new EventSource(`${apiBase}/api/jobs/${job.id}/events`)
      eventSourceRef.current = source

      source.addEventListener('progress', (event) => {
        const data = parseSseData((event as MessageEvent<string>).data)
        const i = Number(data.i ?? 0)
        const total = Number(data.total ?? 0)
        const title = String(data.title ?? '')
        const sourceName = String(data.source ?? '')
        appendJobEvent({
          type: 'progress',
          message: `[${i}/${total}] ${title} (source=${sourceName})`,
        })
      })

      source.addEventListener('card', (event) => {
        const data = parseSseData((event as MessageEvent<string>).data)
        const cardPayload = data.card
        const card =
          cardPayload && typeof cardPayload === 'object' && !Array.isArray(cardPayload)
            ? (cardPayload as Partial<OpportunityCard>)
            : null

        appendJobEvent({
          type: 'card',
          message: card ? `new card: ${card.solution ?? 'untitled card'}` : 'new card received',
        })
      })

      source.addEventListener('done', (event) => {
        const data = parseSseData((event as MessageEvent<string>).data)
        const counts = data.counts ? JSON.stringify(data.counts) : '{}'
        appendJobEvent({ type: 'done', message: `done: ${counts}` })
        void finalizeJob(job.id)
      })

      source.addEventListener('error', (event) => {
        const maybeData = (event as MessageEvent<string>).data
        if (typeof maybeData === 'string' && maybeData.trim()) {
          const data = parseSseData(maybeData)
          const message = String(data.message ?? 'job error')
          appendJobEvent({ type: 'error', message })
          return
        }

        if (source.readyState === EventSource.CLOSED) {
          appendJobEvent({ type: 'system', message: 'job stream closed' })
          void finalizeJob(job.id)
        }
      })
    },
    [apiBase, appendJobEvent, closeEventStream, finalizeJob],
  )

  const startJob = useCallback(
    async (kind: JobKind, body: Record<string, unknown>) => {
      if (mode !== 'api') return

      setJobError('')
      setJobEvents([])
      setIsSubmittingJob(true)

      try {
        const payload = await postJson<{ jobId: string }>(`${apiBase}/api/${kind}`, body)
        const nextJob: JobState = { id: payload.jobId, kind, status: 'running' }
        setActiveJob(nextJob)
        appendJobEvent({ type: 'system', message: `started ${kind} job ${payload.jobId}` })
        connectJobStream(nextJob)
      } catch (error) {
        setJobError(error instanceof Error ? error.message : String(error))
      } finally {
        setIsSubmittingJob(false)
      }
    },
    [apiBase, appendJobEvent, connectJobStream, mode],
  )

  const opportunitiesParse = useMemo(() => {
    if (mode !== 'file' || !opportunitiesText) return null
    return parseOpportunitiesJsonl(opportunitiesText)
  }, [mode, opportunitiesText])

  const signalsParse = useMemo(() => {
    if (mode !== 'file' || !signalsText) return null
    return parseSignalsJsonl(signalsText)
  }, [mode, signalsText])

  const reportText = mode === 'api' ? apiReport : reportFile.loaded?.text ?? ''

  const opportunities = useMemo(() => {
    const rows = mode === 'api' ? apiOpportunities : opportunitiesParse?.records ?? []
    return [...rows].sort((a, b) => totalScore(b) - totalScore(a))
  }, [apiOpportunities, mode, opportunitiesParse?.records])

  const sources = useMemo(() => {
    return uniq(opportunities.map((o) => o.source)).sort()
  }, [opportunities])

  const filtered = useMemo(() => {
    const k = normalize(keyword)
    return opportunities.filter((o) => {
      if (sourceFilter && o.source !== sourceFilter) return false
      if (totalScore(o) < minScore) return false
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
    const max = opportunities[0] ? totalScore(opportunities[0]) : 0
    return { total, shown, max }
  }, [filtered.length, opportunities])

  const isJobBusy =
    isSubmittingJob ||
    (activeJob ? activeJob.status === 'running' || activeJob.status === 'queued' : false)

  const signalsCount = mode === 'api' ? apiSignals.length : signalsParse?.records.length ?? 0

  const onPick = async (kind: 'opps' | 'signals' | 'report', file: File) => {
    if (kind === 'opps') await opportunitiesFile.load(file)
    if (kind === 'signals') await signalsFile.load(file)
    if (kind === 'report') await reportFile.load(file)
  }

  const reloadFiles = async () => {
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
          <div className="sub">
            API mode is default (local server at 127.0.0.1). Switch to local file mode to
            use browser file pickers.
          </div>
        </div>
        <div className="pills">
          <span className="pill pillRed">
            cards: <b>{stats.total}</b>
          </span>
          <span className="pill pillYellow">
            shown: <b>{stats.shown}</b>
          </span>
          <span className="pill pillBlue">
            max score: <b>{stats.max}</b>
          </span>
          <button
            className="btn btnBlue"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          >
            {themeLabel}
          </button>
        </div>
      </div>

      <div className="mainLayout">
        <div className="controlsColumn">
          <div className="card modeCard">
            <div className="sectionTitle sectionTitleBlue">
              <h2>Mode</h2>
              <div className="hint">switch between API and file workflows</div>
            </div>
            <div className="modeToggle">
              <button
                className={`btn ${mode === 'api' ? 'btnBlue' : 'btnGhost'}`}
                onClick={() => setMode('api')}
              >
                API mode
              </button>
              <button
                className={`btn ${mode === 'file' ? 'btnYellow' : 'btnGhost'}`}
                onClick={() => setMode('file')}
              >
                Local file mode
              </button>
            </div>
            <div className="small apiMeta">API base: {apiBase}</div>
          </div>

          {mode === 'api' ? (
            <div className="card runCard">
              <div className="sectionTitle sectionTitleRed">
                <h2>Run</h2>
                <div className="hint">run collect/analyze/report with live SSE progress</div>
              </div>

              <div className="row runInputs">
                <div className="field">
                  <label>collect window</label>
                  <input
                    type="text"
                    value={collectWindow}
                    onChange={(e) => setCollectWindow(e.target.value)}
                    placeholder="24h"
                  />
                </div>

                <div className="field">
                  <label>collect limit</label>
                  <input
                    type="number"
                    value={collectLimit}
                    min={1}
                    max={500}
                    onChange={(e) => setCollectLimit(clamp(Number(e.target.value) || 1, 1, 500))}
                  />
                </div>

                <div className="field">
                  <label>analyze top</label>
                  <input
                    type="number"
                    value={analyzeTop}
                    min={1}
                    max={500}
                    onChange={(e) => setAnalyzeTop(clamp(Number(e.target.value) || 1, 1, 500))}
                  />
                </div>

                <div className="field checkboxField">
                  <label htmlFor="resumeToggle">analyze resume</label>
                  <div className="checkboxRow">
                    <input
                      id="resumeToggle"
                      type="checkbox"
                      checked={analyzeResume}
                      onChange={(e) => setAnalyzeResume(e.target.checked)}
                    />
                    <span className="small">skip already analyzed fingerprints</span>
                  </div>
                </div>

                <div className="runButtons">
                  <button
                    className="btn btnRed"
                    onClick={() =>
                      void startJob('collect', {
                        window: collectWindow.trim() || '24h',
                        limit: clamp(collectLimit, 1, 500),
                      })
                    }
                    disabled={isJobBusy}
                  >
                    Collect
                  </button>
                  <button
                    className="btn btnYellow"
                    onClick={() =>
                      void startJob('analyze', {
                        top: clamp(analyzeTop, 1, 500),
                        resume: analyzeResume,
                      })
                    }
                    disabled={isJobBusy}
                  >
                    Analyze
                  </button>
                  <button
                    className="btn btnBlue"
                    onClick={() => void startJob('report', {})}
                    disabled={isJobBusy}
                  >
                    Report
                  </button>
                  <button
                    className="btn btnGhost"
                    onClick={() => void refreshApiArtifacts()}
                    disabled={isApiLoading || isJobBusy}
                  >
                    Refresh API
                  </button>
                </div>
              </div>

              {apiStatus ? (
                <div className="small apiMeta">
                  API v{apiStatus.version} • signals: {apiStatus.artifacts.signals} • opportunities:{' '}
                  {apiStatus.artifacts.opportunities}
                </div>
              ) : null}

              {apiError ? <div className="small warn apiWarn">API error: {apiError}</div> : null}
              {jobError ? <div className="small warn apiWarn">job error: {jobError}</div> : null}

              <div className="eventLog" role="log" aria-live="polite">
                {jobEvents.length ? (
                  jobEvents.map((entry, index) => (
                    <div key={`${entry.type}-${index}`} className="eventLine" data-type={entry.type}>
                      {entry.message}
                    </div>
                  ))
                ) : (
                  <div className="eventLine" data-type="system">
                    No job events yet.
                  </div>
                )}
              </div>

              <div className="footer">
                Active job:{' '}
                {activeJob ? (
                  <span className="badge">
                    {activeJob.kind} • {activeJob.status}
                  </span>
                ) : (
                  <span className="badge">none</span>
                )}
              </div>
            </div>
          ) : (
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
                      <span className="badge">
                        {opportunitiesFile.loaded.name} • {opportunitiesFile.loaded.size} bytes
                      </span>
                    ) : (
                      <span className="warn">not loaded</span>
                    )}
                    {opportunitiesFile.error ? (
                      <span className="warn"> • {opportunitiesFile.error}</span>
                    ) : null}
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
                  onClick={() => void reloadFiles()}
                  disabled={!opportunitiesFile.file && !signalsFile.file && !reportFile.file}
                >
                  Reload
                </button>
              </div>

              {opportunitiesParse?.warnings?.length ? (
                <div className="small warn parseWarn">
                  Parsed with warnings ({opportunitiesParse.warnings.length}):{' '}
                  {opportunitiesParse.warnings.slice(0, 3).join(' • ')}
                </div>
              ) : null}

              <div className="footer">
                Tip: while running <code>trendbot analyze</code>, keep generating{' '}
                <code>opportunities.jsonl</code>, then click Reload here to refresh.
              </div>
            </div>
          )}

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
                <input
                  type="text"
                  placeholder="e.g. RAG / 价格 / developer"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                />
              </div>
              <button
                className="btn btnYellow"
                onClick={() => {
                  setSourceFilter('')
                  setMinScore(0)
                  setKeyword('')
                }}
              >
                Reset
              </button>
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

            {signalsCount ? (
              <div className="auxSection signalsSection">
                <div className="sectionTitle sectionTitleYellow">
                  <h2>Signals</h2>
                  <div className="hint">{signalsCount} loaded</div>
                </div>
                <div className="small">
                  Signals are currently not joined to cards; used only for optional context.
                </div>
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
                      <td className="score">{totalScore(o)}</td>
                      <td>{o.solution}</td>
                      <td>{o.target_user}</td>
                      <td>
                        <span className="badge">{o.source}</span>
                      </td>
                      <td>
                        <a
                          href={o.source_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {o.source_title}
                        </a>
                        <span className="small sourceHost">({linkLabel(o.source_url)})</span>
                      </td>
                    </tr>
                  ))}
                  {!filtered.length ? (
                    <tr>
                      <td colSpan={5} className="small emptyState">
                        {mode === 'api'
                          ? 'No results yet. Run Collect/Analyze from the Run panel.'
                          : 'No results. Load opportunities.jsonl or relax filters.'}
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
        <div
          className="modalOverlay"
          role="dialog"
          aria-modal="true"
          onClick={() => setSelected(null)}
        >
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modalHeader">
              <div>
                <h3>{selected.solution}</h3>
                <div className="small modalMeta">
                  <span className="badge">{selected.source}</span> • score{' '}
                  <b>{totalScore(selected)}</b> •{' '}
                  <a href={selected.source_url} target="_blank" rel="noreferrer">
                    {selected.source_title}
                  </a>
                </div>
              </div>
              <button className="btn btnRed" onClick={() => setSelected(null)}>
                Close
              </button>
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
              {mode === 'api'
                ? 'API mode: opportunities and report are loaded from the local trendbot server.'
                : 'Browser local-file mode: choose files again if your OS blocks re-reading; Reload usually works.'}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
