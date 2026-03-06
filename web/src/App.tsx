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
import type { OpportunityCard, OpportunityScoring, SignalRecord } from './types'

const DEFAULT_API_BASE = import.meta.env.VITE_TRENDBOT_API_BASE ?? 'http://127.0.0.1:8000'
const SNAP_LOCK_MS = 340
const DRAG_START_THRESHOLD_PX = 6
const DRAG_CLICK_SUPPRESS_MS = 140

type ScoreDimensionKey = Exclude<keyof OpportunityScoring, 'total'>

interface ApiStatusPayload {
  version: string
  artifacts: {
    signals: string
    opportunities: string
    report: string
  }
}

interface FeedDragState {
  pointerId: number
  startY: number
  startScrollTop: number
  moved: boolean
}

interface OpportunityWithTimestamp {
  card: OpportunityCard
  timestamp: Date | null
}

const SCORE_DIMENSIONS: Array<{ key: ScoreDimensionKey; label: string; color: string }> = [
  { key: 'demand', label: 'Demand', color: '#ff2442' },
  { key: 'urgency', label: 'Urgency', color: '#ff4f66' },
  { key: 'distribution', label: 'Distribution', color: '#ff6f80' },
  { key: 'feasibility', label: 'Feasibility', color: '#ff8b9a' },
  { key: 'monetization', label: 'Monetization', color: '#f6a6b1' },
  { key: 'defensibility', label: 'Defensibility', color: '#f3bfc6' },
]

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n))
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

function parseIsoTimestamp(value?: string) {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function toLocalDayKey(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function dayKeyToDate(dayKey: string) {
  const [year, month, day] = dayKey.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function isSameLocalDay(date: Date, dayKey: string) {
  return toLocalDayKey(date) === dayKey
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

function resolveOpportunityTimestamp(
  opportunity: OpportunityCard,
  byFingerprint: Map<string, Date>,
  byUrl: Map<string, Date>,
) {
  const generatedAt = parseIsoTimestamp(opportunity.generated_at)
  if (generatedAt) return generatedAt

  if (opportunity.source_fingerprint) {
    const sourceTimestamp = byFingerprint.get(opportunity.source_fingerprint)
    if (sourceTimestamp) return sourceTimestamp
  }

  if (opportunity.source_url) {
    const sourceTimestamp = byUrl.get(opportunity.source_url)
    if (sourceTimestamp) return sourceTimestamp
  }

  return null
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

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.text()
}

export default function App() {
  const apiBase = DEFAULT_API_BASE

  const [apiStatus, setApiStatus] = useState<ApiStatusPayload | null>(null)
  const [apiOpportunities, setApiOpportunities] = useState<OpportunityCard[]>([])
  const [apiSignals, setApiSignals] = useState<SignalRecord[]>([])
  const [apiError, setApiError] = useState('')
  const [isApiLoading, setIsApiLoading] = useState(false)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null)

  const [todayKey, setTodayKey] = useState(() => toLocalDayKey(new Date()))
  const [activeIndex, setActiveIndex] = useState(0)
  const [isDraggingFeed, setIsDraggingFeed] = useState(false)

  const feedRef = useRef<HTMLDivElement | null>(null)
  const activeIndexRef = useRef(0)
  const wheelLockRef = useRef(false)
  const feedDragRef = useRef<FeedDragState | null>(null)
  const suppressFeedClickUntilRef = useRef(0)

  const refreshApiArtifacts = useCallback(async () => {
    setIsApiLoading(true)
    setApiError('')

    try {
      const [statusPayload, signalsPayload, opportunitiesPayload] = await Promise.all([
        fetchJson<ApiStatusPayload>(`${apiBase}/api/status`),
        fetchJson<SignalRecord[]>(`${apiBase}/api/artifacts/signals`),
        fetchJson<OpportunityCard[]>(`${apiBase}/api/artifacts/opportunities`),
      ])

      // Trigger report endpoint fetch as part of startup/refresh artifact sync.
      void fetchText(`${apiBase}/api/artifacts/report`).catch(() => '')

      setApiStatus(statusPayload)
      setApiSignals(Array.isArray(signalsPayload) ? signalsPayload : [])
      setApiOpportunities(Array.isArray(opportunitiesPayload) ? opportunitiesPayload : [])
      setLastUpdatedAt(new Date())
      setTodayKey(toLocalDayKey(new Date()))
    } catch (error) {
      setApiError(error instanceof Error ? error.message : String(error))
    } finally {
      setIsApiLoading(false)
    }
  }, [apiBase])

  useEffect(() => {
    void refreshApiArtifacts()
  }, [refreshApiArtifacts])

  useEffect(() => {
    let timeoutId = 0
    let cancelled = false

    const scheduleNextNineAmRefresh = () => {
      if (cancelled) return

      const now = new Date()
      const next = new Date(now)
      next.setHours(9, 0, 0, 0)

      if (next <= now) {
        next.setDate(next.getDate() + 1)
      }

      const delay = Math.max(next.getTime() - now.getTime(), 1000)
      timeoutId = window.setTimeout(() => {
        void refreshApiArtifacts().finally(() => {
          scheduleNextNineAmRefresh()
        })
      }, delay)
    }

    scheduleNextNineAmRefresh()

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [refreshApiArtifacts])

  useEffect(() => {
    let timeoutId = 0
    let cancelled = false

    const scheduleMidnightTick = () => {
      if (cancelled) return

      const now = new Date()
      const nextMidnight = new Date(now)
      nextMidnight.setHours(24, 0, 0, 0)

      const delay = Math.max(nextMidnight.getTime() - now.getTime() + 1000, 1000)
      timeoutId = window.setTimeout(() => {
        setTodayKey(toLocalDayKey(new Date()))
        scheduleMidnightTick()
      }, delay)
    }

    scheduleMidnightTick()

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [])

  const signalTimestampLookup = useMemo(() => {
    const byFingerprint = new Map<string, Date>()
    const byUrl = new Map<string, Date>()

    apiSignals.forEach((signal) => {
      const timestamp = parseIsoTimestamp(signal.captured_at)
      if (!timestamp) return

      if (signal.fingerprint) {
        byFingerprint.set(signal.fingerprint, timestamp)
      }

      if (signal.url) {
        byUrl.set(signal.url, timestamp)
      }
    })

    return { byFingerprint, byUrl }
  }, [apiSignals])

  const todaySignals = useMemo(() => {
    return apiSignals.filter((signal) => {
      const timestamp = parseIsoTimestamp(signal.captured_at)
      return !timestamp || isSameLocalDay(timestamp, todayKey)
    })
  }, [apiSignals, todayKey])

  const todayOpportunities = useMemo<OpportunityWithTimestamp[]>(() => {
    return apiOpportunities
      .map((card) => {
        const timestamp = resolveOpportunityTimestamp(
          card,
          signalTimestampLookup.byFingerprint,
          signalTimestampLookup.byUrl,
        )
        return { card, timestamp }
      })
      .filter((entry) => !entry.timestamp || isSameLocalDay(entry.timestamp, todayKey))
      .sort((a, b) => totalScore(b.card) - totalScore(a.card))
  }, [apiOpportunities, signalTimestampLookup, todayKey])

  const signalSourceSummary = useMemo(() => {
    const bySource = new Map<string, number>()

    todaySignals.forEach((signal) => {
      bySource.set(signal.source, (bySource.get(signal.source) ?? 0) + 1)
    })

    return Array.from(bySource.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
  }, [todaySignals])

  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }), [])
  const dateTimeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }),
    [],
  )

  const todayLabel = dateFormatter.format(dayKeyToDate(todayKey))
  const lastUpdatedLabel = lastUpdatedAt ? dateTimeFormatter.format(lastUpdatedAt) : 'Not yet synced'

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
      if (!todayOpportunities.length) return

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
        scrollToCard(todayOpportunities.length - 1)
      }
    },
    [scrollToCard, todayOpportunities.length],
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
    if (!todayOpportunities.length) {
      setActiveIndex(0)
      activeIndexRef.current = 0
      return
    }

    const next = clamp(activeIndexRef.current, 0, todayOpportunities.length - 1)
    if (next !== activeIndexRef.current) {
      activeIndexRef.current = next
      setActiveIndex(next)
    }
  }, [todayOpportunities.length])

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
  }, [todayOpportunities.length, findNearestCardIndex])

  useEffect(() => {
    const container = feedRef.current
    if (!container) return

    const onWheel = (event: WheelEvent) => {
      if (todayOpportunities.length < 2) return
      if (Math.abs(event.deltaY) < 5) return

      event.preventDefault()
      if (wheelLockRef.current) return

      const direction = event.deltaY > 0 ? 1 : -1
      const nextIndex = clamp(activeIndexRef.current + direction, 0, todayOpportunities.length - 1)
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
  }, [scrollToCard, todayOpportunities.length])

  return (
    <div className="todayShell">
      <header className="cardSurface todayHeader">
        <div className="titleBlock">
          <p className="titleEyebrow">Trend Opportunity Dashboard</p>
          <h1>Today&apos;s Results</h1>
          <p>
            Showing opportunities and signals for <strong>{todayLabel}</strong> in local time.
          </p>
        </div>

        <div className="headerControls">
          <p className="lastUpdated">
            Last updated: <span>{lastUpdatedLabel}</span>
            {apiStatus ? <small>API v{apiStatus.version}</small> : null}
          </p>
          <button
            type="button"
            className="btn btnSecondary"
            onClick={() => void refreshApiArtifacts()}
            disabled={isApiLoading}
          >
            {isApiLoading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </header>

      {apiError ? <p className="warnText">API error: {apiError}</p> : null}

      <main className="feedColumn">
        <section className="cardSurface feedPanel">
          <div className="cardHeading cardHeadingRow">
            <div>
              <h2>Opportunity Card Feed</h2>
              <p>
                {todayOpportunities.length} opportunities • {todaySignals.length} signals captured today.
              </p>
            </div>
            <span className="statusBadge">
              {todayOpportunities.length ? `${activeIndex + 1} / ${todayOpportunities.length}` : '0 / 0'}
            </span>
          </div>

          <div className="signalSummary" aria-label="today signal source summary">
            {signalSourceSummary.length ? (
              signalSourceSummary.map(([source, count]) => (
                <span key={source} className="signalChip">
                  {source}
                  <b>{count}</b>
                </span>
              ))
            ) : (
              <span className="signalHint">No signal source counts for today yet.</span>
            )}
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
            {todayOpportunities.length ? (
              todayOpportunities.map(({ card: opportunity, timestamp }, index) => {
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

                    <p className="cardMetaTime">
                      {timestamp
                        ? `Generated ${dateTimeFormatter.format(timestamp)}`
                        : 'Generated today (fallback to local day)'}
                    </p>

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
                {isApiLoading
                  ? 'Loading today\'s opportunities...'
                  : `No opportunities for ${todayLabel} yet. This view only shows local-today results.`}
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}
