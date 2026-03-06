import type { OpportunityCard, OpportunityScoring, ParseResult, SignalRecord } from './types'

interface ParsedLine {
  lineNumber: number
  value: unknown
}

interface ParseJsonlOutput {
  lines: ParsedLine[]
  warnings: string[]
}

function parseJsonl(text: string): ParseJsonlOutput {
  const lines = text.split(/\r?\n/)
  const parsed: ParsedLine[] = []
  const warnings: string[] = []

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (!trimmed) return
    try {
      parsed.push({ lineNumber: index + 1, value: JSON.parse(trimmed) })
    } catch {
      warnings.push(`Line ${index + 1}: invalid JSON`)
    }
  })

  return { lines: parsed, warnings }
}

function asRecord(value: unknown, lineNumber: number): Record<string, unknown> {
  if (value === null || value === undefined || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`Line ${lineNumber}: expected a JSON object`)
  }
  return value as Record<string, unknown>
}

function readRequiredString(record: Record<string, unknown>, key: string, lineNumber: number): string {
  const value = record[key]
  if (typeof value !== 'string') {
    throw new Error(`Line ${lineNumber}: "${key}" must be a string`)
  }
  const cleaned = value.trim()
  if (!cleaned) throw new Error(`Line ${lineNumber}: "${key}" cannot be empty`)
  return cleaned
}

function readOptionalString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  if (typeof value !== 'string') return ''
  return value.trim()
}

function readOptionalTimestamp(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key]
  if (typeof value !== 'string') return undefined
  const cleaned = value.trim()
  return cleaned || undefined
}

function toNumber(raw: unknown, label: string, lineNumber: number): number {
  const value = typeof raw === 'number' ? raw : Number(raw)
  if (!Number.isFinite(value)) {
    throw new Error(`Line ${lineNumber}: "${label}" must be numeric`)
  }
  return value
}

function parseScoreDimension(scoring: Record<string, unknown>, key: keyof OpportunityScoring, lineNumber: number): number {
  const numeric = toNumber(scoring[key], `scoring.${String(key)}`, lineNumber)
  if (!Number.isInteger(numeric) || numeric < 0 || numeric > 5) {
    throw new Error(`Line ${lineNumber}: "scoring.${String(key)}" must be an integer between 0 and 5`)
  }
  return numeric
}

function parseScoring(value: unknown, lineNumber: number): OpportunityScoring {
  const scoring = asRecord(value, lineNumber)
  const demand = parseScoreDimension(scoring, 'demand', lineNumber)
  const urgency = parseScoreDimension(scoring, 'urgency', lineNumber)
  const distribution = parseScoreDimension(scoring, 'distribution', lineNumber)
  const feasibility = parseScoreDimension(scoring, 'feasibility', lineNumber)
  const monetization = parseScoreDimension(scoring, 'monetization', lineNumber)
  const defensibility = parseScoreDimension(scoring, 'defensibility', lineNumber)
  const computedTotal = demand + urgency + distribution + feasibility + monetization + defensibility
  const totalRaw = scoring.total
  const parsedTotal = totalRaw === undefined ? computedTotal : toNumber(totalRaw, 'scoring.total', lineNumber)
  const total = Number.isInteger(parsedTotal) ? parsedTotal : Math.round(parsedTotal)

  return { demand, urgency, distribution, feasibility, monetization, defensibility, total }
}

function parseOpportunity(value: unknown, lineNumber: number): OpportunityCard {
  const record = asRecord(value, lineNumber)

  return {
    source: readRequiredString(record, 'source', lineNumber),
    source_title: readRequiredString(record, 'source_title', lineNumber),
    source_url: readRequiredString(record, 'source_url', lineNumber),
    source_fingerprint: readOptionalString(record, 'source_fingerprint'),
    target_user: readRequiredString(record, 'target_user', lineNumber),
    trigger: readRequiredString(record, 'trigger', lineNumber),
    pain: readRequiredString(record, 'pain', lineNumber),
    existing_alternatives: readRequiredString(record, 'existing_alternatives', lineNumber),
    solution: readRequiredString(record, 'solution', lineNumber),
    pricing_reason: readRequiredString(record, 'pricing_reason', lineNumber),
    validation_7d: readRequiredString(record, 'validation_7d', lineNumber),
    success_signal: readRequiredString(record, 'success_signal', lineNumber),
    zh_summary: readOptionalString(record, 'zh_summary'),
    zh_analysis: readOptionalString(record, 'zh_analysis'),
    scoring: parseScoring(record.scoring, lineNumber),
    generated_at: readOptionalTimestamp(record, 'generated_at'),
  }
}

function parseSignal(value: unknown, lineNumber: number): SignalRecord {
  const record = asRecord(value, lineNumber)
  const rawTags = record.tags
  const rawMetrics = record.metrics

  return {
    source: readRequiredString(record, 'source', lineNumber),
    title: readRequiredString(record, 'title', lineNumber),
    url: readRequiredString(record, 'url', lineNumber),
    description: readOptionalString(record, 'description'),
    tags: Array.isArray(rawTags) ? rawTags.map((tag) => String(tag).trim()).filter(Boolean) : [],
    metrics: rawMetrics && typeof rawMetrics === 'object' && !Array.isArray(rawMetrics) ? (rawMetrics as Record<string, unknown>) : {},
    captured_at: readOptionalTimestamp(record, 'captured_at'),
    fingerprint: readOptionalString(record, 'fingerprint'),
  }
}

function parseWithWarnings<T>(text: string, parser: (value: unknown, lineNumber: number) => T): ParseResult<T> {
  const jsonl = parseJsonl(text)
  const records: T[] = []
  const warnings: string[] = [...jsonl.warnings]

  jsonl.lines.forEach((line) => {
    try {
      records.push(parser(line.value, line.lineNumber))
    } catch (error) {
      warnings.push(error instanceof Error ? error.message : `Line ${line.lineNumber}: parse failed`)
    }
  })

  return { records, warnings, lineCount: jsonl.lines.length + jsonl.warnings.length }
}

export function parseOpportunitiesJsonl(text: string): ParseResult<OpportunityCard> {
  return parseWithWarnings(text, parseOpportunity)
}

export function parseSignalsJsonl(text: string): ParseResult<SignalRecord> {
  return parseWithWarnings(text, parseSignal)
}
