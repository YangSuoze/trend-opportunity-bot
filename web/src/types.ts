export interface OpportunityScoring {
  demand: number
  urgency: number
  distribution: number
  feasibility: number
  monetization: number
  defensibility: number
  total: number
}

export interface OpportunityCard {
  source: string
  source_title: string
  source_url: string
  source_fingerprint: string
  target_user: string
  trigger: string
  pain: string
  existing_alternatives: string
  solution: string
  pricing_reason: string
  validation_7d: string
  success_signal: string
  zh_summary: string
  zh_analysis: string
  scoring: OpportunityScoring
  generated_at?: string
}

export interface SignalRecord {
  source: string
  title: string
  url: string
  description: string
  tags: string[]
  metrics: Record<string, unknown>
  captured_at?: string
  fingerprint: string
}

export interface ParseResult<T> {
  records: T[]
  warnings: string[]
  lineCount: number
}
