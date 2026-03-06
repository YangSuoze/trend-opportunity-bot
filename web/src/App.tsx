import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import './App.css'
import { parseOpportunitiesJsonl, parseSignalsJsonl } from './parsers'
import type { OpportunityCard, OpportunityScoring, SignalRecord } from './types'
import { useFileText } from './useFileText'

const DEFAULT_API_BASE = import.meta.env.VITE_TRENDBOT_API_BASE ?? 'http://127.0.0.1:8000'
const SNAP_LOCK_MS = 340
const DRAG_START_THRESHOLD_PX = 6
const DRAG_CLICK_SUPPRESS_MS = 140

type ViewMode = 'api' | 'file'
type JobKind = 'collect' | 'analyze' | 'report'
type JobStatus = 'queued' | 'running' | 'done' | 'error'
type EventType = 'progress' | 'card' | 'done' | 'error' | 'system'
type ScoreDimensionKey = Exclude<keyof OpportunityScoring, 'total'>

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

interface FeedDragState {
  pointerId: number
  startY: number
  startScrollTop: number
  moved: boolean
}

const SCORE_DIMENSIONS: Array<{ key: ScoreDimensionKey; label: string; color: string }> = [
  { key: 'demand', label: 'Demand', color: '#FF2442' },
  { key: 'urgency', label: 'Urgency', color: '#ff4f66' },
  { key: 'distribution', label: 'Distribution', color: '#ff6f80' },
  { key: 'feasibility', label: 'Feasibility', color: '#ff8b9a' },
  { key: 'monetization', label: 'Monetization', color: '#f6a6b1' },
  { key: 'defensibility', label: 'Defensibility', color: '#f3bfc6' },
]

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

function isInteractiveTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false

  return Boolean(
    target.closest(
      'a,button,input,select,textarea,label,summary,[role="button"],[data-feed-no-drag="true"]',
    ),
  )
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

function polarToCartesian(cx: number, cy: number, radius: number, angle: number) {
  const radians = (angle * Math.PI) / 180
  return {
    x: cx + radius * Math.cos(radians),
    y: cy + radius * Math.sin(radians),
  }
}

function describeArc(cx: number, cy: number, radius: number, start: number, end: number) {
  const sweep = end - start
  if (sweep <= 0.01) return ''

  const startPoint = polarToCartesian(cx, cy, radius, start)
  const endPoint = polarToCartesian(cx, cy, radius, end)
  const largeArcFlag = sweep > 180 ? 1 : 0

  return `M ${startPoint.x.toFixed(3)} ${startPoint.y.toFixed(3)} A ${radius} ${radius} 0 ${largeArcFlag} 1 ${endPoint.x.toFixed(3)} ${endPoint.y.toFixed(3)}`
}

function extractNumericProgress(raw: string): number | null {
  const value = raw.trim()
  if (!value) return null

  const percentMatch = value.match(/(\d+(?:\.\d+)?)\s*%/)
  if (percentMatch) {
    return clamp(Number(percentMatch[1]) / 100, 0, 1)
  }

  const fractionMatch = value.match(/(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)/)
  if (fractionMatch) {
    const numerator = Number(fractionMatch[1])
    const denominator = Number(fractionMatch[2])
    if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
      return clamp(numerator / denominator, 0, 1)
    }
  }

  const numericMatch = value.match(/\d+(?:\.\d+)?/)
  if (!numericMatch) return null

  const numeric = Number(numericMatch[0])
  if (!Number.isFinite(numeric)) return null
  if (numeric <= 1) return clamp(numeric, 0, 1)
  if (numeric <= 5) return clamp(numeric / 5, 0, 1)
  if (numeric <= 10) return clamp(numeric / 10, 0, 1)
  if (numeric <= 30) return clamp(numeric / 30, 0, 1)
  if (numeric <= 100) return clamp(numeric / 100, 0, 1)

  return null
}

function fallbackBlockCount(value: string, blockCount: number) {
  const text = normalize(value)
  if (!text) return 0

  let hash = 0
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) >>> 0
  }

  if (blockCount < 3) return blockCount
  return (hash % (blockCount - 1)) + 2
}

function cardKey(card: OpportunityCard, index: number) {
  return card.source_fingerprint || card.source_url || `${card.source}-${card.solution}-${index}`
}

function ScoreDonut({ scoring }: { scoring: OpportunityScoring }) {
  const segmentAngle = 360 / SCORE_DIMENSIONS.length
  const gap = 8

  return (
    <svg className="scoreDonut" viewBox="0 0 120 120" role="img" aria-label={`score ${scoring.total} out of 30`}>
      {SCORE_DIMENSIONS.map((dimension, index) => {
        const rawValue = Number(scoring[dimension.key] ?? 0)
        const value = clamp(rawValue, 0, 5)
        const segmentStart = -90 + index * segmentAngle + gap / 2
        const segmentEnd = -90 + (index + 1) * segmentAngle - gap / 2
        const valueEnd = segmentStart + (segmentEnd - segmentStart) * (value / 5)
        const trackPath = describeArc(60, 60, 40, segmentStart, segmentEnd)
        const valuePath = describeArc(60, 60, 40, segmentStart, valueEnd)

        return (
          <g key={dimension.key}>
            {trackPath ? <path className="donutTrack" d={trackPath} /> : null}
            {valuePath ? <path className="donutValue" d={valuePath} style={{ stroke: dimension.color }} /> : null}
          </g>
        )
      })}
      <circle className="donutCore" cx="60" cy="60" r="24" />
      <text className="donutTotal" x="60" y="57" textAnchor="middle">
        {scoring.total}
      </text>
      <text className="donutTotalSub" x="60" y="71" textAnchor="middle">
        / 30
      </text>
    </svg>
  )
}

function SignalMeter({ label, value }: { label: string; value: string }) {
  const ratio = extractNumericProgress(value)
  const maxBlocks = 6
  const filledBlocks = ratio === null ? fallbackBlockCount(value, maxBlocks) : Math.round(ratio * maxBlocks)

  return (
    <div className="signalMeter">
      <div className="signalMeterTop">
        <span>{label}</span>
        {ratio === null ? <b>text signal</b> : <b>{Math.round(ratio * 100)}%</b>}
      </div>

      {ratio === null ? (
        <div className="signalBlocks" role="img" aria-label={`${label} qualitative intensity`}>
          {Array.from({ length: maxBlocks }, (_, i) => (
            <span key={`${label}-${i}`} className={i < filledBlocks ? 'isOn' : undefined} />
          ))}
        </div>
      ) : (
        <div className="signalTrack" role="img" aria-label={`${label} ${Math.round(ratio * 100)} percent`}>
          <span style={{ width: `${ratio <= 0 ? 0 : Math.max(ratio * 100, 8)}%` }} />
        </div>
      )}

      <p>{value || '—'}</p>
    </div>
  )
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
  const [activeIndex, setActiveIndex] = useState(0)
  const [isDraggingFeed, setIsDraggingFeed] = useState(false)

  const eventSourceRef = useRef<EventSource | null>(null)
  const feedRef = useRef<HTMLDivElement | null>(null)
  const activeIndexRef = useRef(0)
  const wheelLockRef = useRef(false)
  const feedDragRef = useRef<FeedDragState | null>(null)
  const suppressFeedClickUntilRef = useRef(0)

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

  const getFeedCards = useCallback(() => {
    const container = feedRef.current
    if (!container) return [] as HTMLDivElement[]
    return Array.from(container.querySelectorAll<HTMLDivElement>('[data-feed-card="true"]'))
  }, [])

  const scrollToCard = useCallback(
    (index: number, behavior: ScrollBehavior = 'smooth') => {
      const container = feedRef.current
      if (!container) return

      const cards = getFeedCards()
      if (!cards.length) return

      const next = clamp(index, 0, cards.length - 1)
      const target = cards[next]
      container.scrollTo({ top: Math.max(target.offsetTop - 12, 0), behavior })
      activeIndexRef.current = next
      setActiveIndex(next)
    },
    [getFeedCards],
  )

  const onFeedKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (!filtered.length) return

      if (event.key === 'ArrowDown' || event.key === 'PageDown') {
        event.preventDefault()
        scrollToCard(activeIndexRef.current + 1)
      }

      if (event.key === 'ArrowUp' || event.key === 'PageUp') {
        event.preventDefault()
        scrollToCard(activeIndexRef.current - 1)
      }

      if (event.key === 'Home') {
        event.preventDefault()
        scrollToCard(0)
      }

      if (event.key === 'End') {
        event.preventDefault()
        scrollToCard(filtered.length - 1)
      }
    },
    [filtered.length, scrollToCard],
  )

  const findNearestCardIndex = useCallback(() => {
    const container = feedRef.current
    if (!container) return -1

    const cards = getFeedCards()
    if (!cards.length) return -1

    const anchor = container.scrollTop + container.clientHeight * 0.45
    let nearestIndex = 0
    let nearestDistance = Number.POSITIVE_INFINITY

    cards.forEach((card, index) => {
      const distance = Math.abs(card.offsetTop - anchor)
      if (distance < nearestDistance) {
        nearestDistance = distance
        nearestIndex = index
      }
    })

    return nearestIndex
  }, [getFeedCards])

  const onFeedPointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary) return
    if (event.pointerType === 'mouse' && event.button !== 0) return
    if (isInteractiveTarget(event.target)) return

    const container = feedRef.current
    if (!container) return

    feedDragRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startScrollTop: container.scrollTop,
      moved: false,
    }
    event.currentTarget.setPointerCapture(event.pointerId)
    setIsDraggingFeed(true)
  }, [])

  const onFeedPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = feedDragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return

    const container = feedRef.current
    if (!container) return

    const deltaY = event.clientY - drag.startY
    if (!drag.moved && Math.abs(deltaY) >= DRAG_START_THRESHOLD_PX) {
      drag.moved = true
    }

    if (!drag.moved) return

    event.preventDefault()
    container.scrollTop = drag.startScrollTop - deltaY
  }, [])

  const onFeedPointerRelease = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const drag = feedDragRef.current
      if (!drag || drag.pointerId !== event.pointerId) return

      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }

      if (drag.moved) {
        suppressFeedClickUntilRef.current = window.performance.now() + DRAG_CLICK_SUPPRESS_MS
        const nearestIndex = findNearestCardIndex()
        if (nearestIndex >= 0) {
          scrollToCard(nearestIndex)
        }
      }

      feedDragRef.current = null
      setIsDraggingFeed(false)
    },
    [findNearestCardIndex, scrollToCard],
  )

  const onFeedClickCapture = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (window.performance.now() <= suppressFeedClickUntilRef.current) {
      event.preventDefault()
      event.stopPropagation()
    }
  }, [])

  useEffect(() => {
    activeIndexRef.current = activeIndex
  }, [activeIndex])

  useEffect(() => {
    if (!filtered.length) {
      setActiveIndex(0)
      activeIndexRef.current = 0
      return
    }

    const next = clamp(activeIndexRef.current, 0, filtered.length - 1)
    if (next !== activeIndexRef.current) {
      activeIndexRef.current = next
      setActiveIndex(next)
    }
  }, [filtered.length])

  useEffect(() => {
    const container = feedRef.current
    if (!container) return

    let frame = 0
    const onScroll = () => {
      if (frame) return
      frame = window.requestAnimationFrame(() => {
        frame = 0

        const nearestIndex = findNearestCardIndex()
        if (nearestIndex < 0) return

        if (nearestIndex !== activeIndexRef.current) {
          activeIndexRef.current = nearestIndex
          setActiveIndex(nearestIndex)
        }
      })
    }

    container.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      container.removeEventListener('scroll', onScroll)
      if (frame) window.cancelAnimationFrame(frame)
    }
  }, [filtered.length, findNearestCardIndex])

  useEffect(() => {
    const container = feedRef.current
    if (!container) return

    const onWheel = (event: WheelEvent) => {
      if (filtered.length < 2) return
      if (Math.abs(event.deltaY) < 5) return

      event.preventDefault()
      if (wheelLockRef.current) return

      const direction = event.deltaY > 0 ? 1 : -1
      const nextIndex = clamp(activeIndexRef.current + direction, 0, filtered.length - 1)
      if (nextIndex === activeIndexRef.current) return

      wheelLockRef.current = true
      scrollToCard(nextIndex)
      window.setTimeout(() => {
        wheelLockRef.current = false
      }, SNAP_LOCK_MS)
    }

    container.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      container.removeEventListener('wheel', onWheel)
    }
  }, [filtered.length, scrollToCard])

  const resetFilters = () => {
    setSourceFilter('')
    setMinScore(0)
    setKeyword('')
    setActiveIndex(0)
    activeIndexRef.current = 0
    if (feedRef.current) {
      feedRef.current.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }

  return (
    <div className="dashboardShell">
      <header className="topBar cardSurface">
        <div className="brandBlock">
          <p className="brandLabel">Trend Opportunity Dashboard</p>
          <h1>Opportunity Intelligence Feed</h1>
          <p>
            Clean card-based workflow for API jobs and local file review. Scroll one card at a
            time to inspect opportunities with compact scoring visuals.
          </p>
        </div>
        <div className="topStats" aria-label="dashboard stats">
          <div className="statCard">
            <span>Cards</span>
            <strong>{stats.total}</strong>
          </div>
          <div className="statCard">
            <span>Shown</span>
            <strong>{stats.shown}</strong>
          </div>
          <div className="statCard">
            <span>Max Score</span>
            <strong>{stats.max}</strong>
          </div>
          <div className="statCard">
            <span>Signals</span>
            <strong>{signalsCount}</strong>
          </div>
        </div>
      </header>

      <div className="dashboardLayout">
        <aside className="leftRail">
          <section className="cardSurface controlCard">
            <div className="cardHeading">
              <h2>Mode</h2>
              <p>Switch between API backend and local files.</p>
            </div>
            <div className="modeToggle">
              <button
                type="button"
                className={`btn ${mode === 'api' ? 'btnPrimary' : 'btnSecondary'}`}
                onClick={() => setMode('api')}
              >
                API mode
              </button>
              <button
                type="button"
                className={`btn ${mode === 'file' ? 'btnPrimary' : 'btnSecondary'}`}
                onClick={() => setMode('file')}
              >
                File mode
              </button>
            </div>
            <p className="metaLine">API base: {apiBase}</p>
          </section>

          {mode === 'api' ? (
            <section className="cardSurface controlCard">
              <div className="cardHeading">
                <h2>Run Pipeline</h2>
                <p>Launch collect/analyze/report and stream live events.</p>
              </div>

              <div className="fieldGrid">
                <label className="fieldGroup">
                  <span>Collect window</span>
                  <input
                    type="text"
                    value={collectWindow}
                    onChange={(event) => setCollectWindow(event.target.value)}
                    placeholder="24h"
                  />
                </label>

                <label className="fieldGroup">
                  <span>Collect limit</span>
                  <input
                    type="number"
                    value={collectLimit}
                    min={1}
                    max={500}
                    onChange={(event) =>
                      setCollectLimit(clamp(Number(event.target.value) || 1, 1, 500))
                    }
                  />
                </label>

                <label className="fieldGroup">
                  <span>Analyze top</span>
                  <input
                    type="number"
                    value={analyzeTop}
                    min={1}
                    max={500}
                    onChange={(event) =>
                      setAnalyzeTop(clamp(Number(event.target.value) || 1, 1, 500))
                    }
                  />
                </label>

                <label className="fieldGroup checkboxGroup" htmlFor="resumeToggle">
                  <span>Analyze resume</span>
                  <div className="checkboxRow">
                    <input
                      id="resumeToggle"
                      type="checkbox"
                      checked={analyzeResume}
                      onChange={(event) => setAnalyzeResume(event.target.checked)}
                    />
                    <p>Skip already analyzed fingerprints.</p>
                  </div>
                </label>
              </div>

              <div className="buttonRow">
                <button
                  type="button"
                  className="btn btnPrimary"
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
                  type="button"
                  className="btn btnSecondary"
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
                  type="button"
                  className="btn btnSecondary"
                  onClick={() => void startJob('report', {})}
                  disabled={isJobBusy}
                >
                  Report
                </button>
                <button
                  type="button"
                  className="btn btnSecondary"
                  onClick={() => void refreshApiArtifacts()}
                  disabled={isApiLoading || isJobBusy}
                >
                  Refresh API
                </button>
              </div>

              {apiStatus ? (
                <p className="metaLine">
                  API v{apiStatus.version} • signals: {apiStatus.artifacts.signals} • opportunities:{' '}
                  {apiStatus.artifacts.opportunities}
                </p>
              ) : null}

              {apiError ? <p className="warnText">API error: {apiError}</p> : null}
              {jobError ? <p className="warnText">Job error: {jobError}</p> : null}

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

              <p className="metaLine">
                Active job:{' '}
                <span className="statusBadge">
                  {activeJob ? `${activeJob.kind} • ${activeJob.status}` : 'none'}
                </span>
              </p>
            </section>
          ) : (
            <section className="cardSurface controlCard">
              <div className="cardHeading">
                <h2>Files</h2>
                <p>Pick local artifacts and reload to re-read updates.</p>
              </div>

              <div className="fieldGrid">
                <label className="fieldGroup">
                  <span>opportunities.jsonl (required)</span>
                  <input
                    type="file"
                    accept=".jsonl,.txt,application/json"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void onPick('opps', file)
                    }}
                  />
                  <p className="fileMeta">
                    {opportunitiesFile.loaded
                      ? `${opportunitiesFile.loaded.name} • ${opportunitiesFile.loaded.size} bytes`
                      : 'not loaded'}
                    {opportunitiesFile.error ? ` • ${opportunitiesFile.error}` : ''}
                  </p>
                </label>

                <label className="fieldGroup">
                  <span>signals.jsonl (optional)</span>
                  <input
                    type="file"
                    accept=".jsonl,.txt,application/json"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void onPick('signals', file)
                    }}
                  />
                  <p className="fileMeta">
                    {signalsFile.loaded ? signalsFile.loaded.name : 'not loaded'}
                    {signalsFile.error ? ` • ${signalsFile.error}` : ''}
                  </p>
                </label>

                <label className="fieldGroup">
                  <span>report.md (optional)</span>
                  <input
                    type="file"
                    accept=".md,.txt,text/markdown"
                    onChange={(event) => {
                      const file = event.target.files?.[0]
                      if (file) void onPick('report', file)
                    }}
                  />
                  <p className="fileMeta">
                    {reportFile.loaded ? reportFile.loaded.name : 'not loaded'}
                    {reportFile.error ? ` • ${reportFile.error}` : ''}
                  </p>
                </label>
              </div>

              <div className="buttonRow buttonRowSingle">
                <button
                  type="button"
                  className="btn btnPrimary"
                  onClick={() => void reloadFiles()}
                  disabled={!opportunitiesFile.file && !signalsFile.file && !reportFile.file}
                >
                  Reload
                </button>
              </div>

              {opportunitiesParse?.warnings?.length ? (
                <p className="warnText">
                  Parsed with warnings ({opportunitiesParse.warnings.length}):{' '}
                  {opportunitiesParse.warnings.slice(0, 3).join(' • ')}
                </p>
              ) : null}

              <p className="metaLine">
                Tip: run <code>trendbot analyze</code>, keep generating <code>opportunities.jsonl</code>,
                then reload in this panel.
              </p>
            </section>
          )}

          <section className="cardSurface controlCard">
            <div className="cardHeading">
              <h2>Filters</h2>
              <p>Source, score threshold, and keyword matching.</p>
            </div>

            <div className="fieldGrid">
              <label className="fieldGroup">
                <span>Source</span>
                <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
                  <option value="">All</option>
                  {sources.map((source) => (
                    <option key={source} value={source}>
                      {source}
                    </option>
                  ))}
                </select>
              </label>

              <label className="fieldGroup">
                <span>Min score</span>
                <input
                  type="number"
                  value={minScore}
                  min={0}
                  max={30}
                  onChange={(event) => setMinScore(clamp(Number(event.target.value) || 0, 0, 30))}
                />
                <input
                  type="range"
                  value={minScore}
                  min={0}
                  max={30}
                  onChange={(event) => setMinScore(Number(event.target.value))}
                />
              </label>

              <label className="fieldGroup">
                <span>Keyword</span>
                <input
                  type="text"
                  value={keyword}
                  onChange={(event) => setKeyword(event.target.value)}
                  placeholder="RAG / 价格 / developer"
                />
              </label>
            </div>

            <div className="buttonRow buttonRowSingle">
              <button type="button" className="btn btnSecondary" onClick={resetFilters}>
                Reset filters
              </button>
            </div>

            {reportText ? (
              <div className="subPanel">
                <h3>Report preview</h3>
                <pre>{reportText.slice(0, 1200)}{reportText.length > 1200 ? '\n\n…' : ''}</pre>
              </div>
            ) : null}

            {signalsCount ? (
              <div className="subPanel">
                <h3>Signals</h3>
                <p>{signalsCount} loaded. Signals are currently not joined directly to each card.</p>
              </div>
            ) : null}
          </section>
        </aside>

        <main className="feedColumn">
          <section className="cardSurface feedPanel">
            <div className="cardHeading cardHeadingRow">
              <div>
                <h2>Opportunity Card Feed</h2>
                <p>Wheel snap, drag/swipe, and keyboard controls for quick card scanning.</p>
              </div>
              <span className="statusBadge">
                {filtered.length ? `${activeIndex + 1} / ${filtered.length}` : '0 / 0'}
              </span>
            </div>

            <div
              ref={feedRef}
              className={`feedViewport ${isDraggingFeed ? 'isDragging' : ''}`}
              tabIndex={0}
              onKeyDown={onFeedKeyDown}
              onPointerDown={onFeedPointerDown}
              onPointerMove={onFeedPointerMove}
              onPointerUp={onFeedPointerRelease}
              onPointerCancel={onFeedPointerRelease}
              onClickCapture={onFeedClickCapture}
              aria-label="Opportunity cards feed"
            >
              {filtered.length ? (
                filtered.map((opportunity, index) => {
                  const score = totalScore(opportunity)

                  return (
                    <article
                      key={cardKey(opportunity, index)}
                      className={`feedCard ${index === activeIndex ? 'isActive' : ''}`}
                      data-feed-card="true"
                    >
                      <div className="feedCardTop">
                        <div>
                          <h3>{opportunity.solution}</h3>
                          <p>{opportunity.zh_summary || '暂无摘要'}</p>
                        </div>
                        <div className="scoreStack" aria-label={`total score ${score}`}>
                          <span>Total score</span>
                          <strong>{score}</strong>
                          <small>/ 30</small>
                        </div>
                      </div>

                      <div className="sourceLine">
                        <span className="sourceBadge">{opportunity.source}</span>
                        <a href={opportunity.source_url} target="_blank" rel="noreferrer">
                          {opportunity.source_title}
                        </a>
                        <span className="sourceHost">({linkLabel(opportunity.source_url)})</span>
                      </div>

                      <div className="vizGrid">
                        <div className="vizCard">
                          <h4>Scoring</h4>
                          <div className="donutRow">
                            <ScoreDonut scoring={opportunity.scoring} />
                            <div className="dimensionList" role="list">
                              {SCORE_DIMENSIONS.map((dimension) => {
                                const value = clamp(Number(opportunity.scoring?.[dimension.key] ?? 0), 0, 5)
                                return (
                                  <div key={dimension.key} className="dimensionItem" role="listitem">
                                    <span>{dimension.label}</span>
                                    <div className="dimensionTrack">
                                      <span
                                        style={{
                                          width: `${(value / 5) * 100}%`,
                                          backgroundColor: dimension.color,
                                        }}
                                      />
                                    </div>
                                    <b>{value}/5</b>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        </div>

                        <div className="vizCard">
                          <h4>Validation signals</h4>
                          <SignalMeter label="validation_7d" value={opportunity.validation_7d} />
                          <SignalMeter label="success_signal" value={opportunity.success_signal} />
                        </div>
                      </div>

                      <details className="detailsPanel">
                        <summary>Expand full details</summary>
                        <div className="detailsGrid">
                          <div>
                            <h5>target_user</h5>
                            <p>{opportunity.target_user || '—'}</p>
                          </div>
                          <div>
                            <h5>trigger</h5>
                            <p>{opportunity.trigger || '—'}</p>
                          </div>
                          <div>
                            <h5>pain</h5>
                            <p>{opportunity.pain || '—'}</p>
                          </div>
                          <div>
                            <h5>alternatives</h5>
                            <p>{opportunity.existing_alternatives || '—'}</p>
                          </div>
                          <div>
                            <h5>pricing_reason</h5>
                            <p>{opportunity.pricing_reason || '—'}</p>
                          </div>
                          <div>
                            <h5>zh_analysis</h5>
                            <p>{opportunity.zh_analysis || '—'}</p>
                          </div>
                        </div>
                      </details>
                    </article>
                  )
                })
              ) : (
                <div className="emptyFeed" data-feed-card="true">
                  {mode === 'api'
                    ? 'No results yet. Run Collect/Analyze from the left panel.'
                    : 'No results. Load opportunities.jsonl or relax filters.'}
                </div>
              )}
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}
