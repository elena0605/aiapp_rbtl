'use client'

import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, ExternalLink, Youtube } from 'lucide-react'

export interface RetrievalTraceStep {
  step: number
  title: string
  detail: string
}

export interface RetrievalTrace {
  steps?: RetrievalTraceStep[]
  params?: Record<string, unknown>
  warnings?: string[]
  research_notes?: string[]
}

interface MediaRetrievalViewProps {
  results: any[]
  routeType?: string
  toolName?: string
  toolInputs?: Record<string, any>
  retrievalTrace?: RetrievalTrace
  researchNotes?: string[]
  dedupedByInfluencer?: boolean
  stage1?: {
    results?: any[]
    results_preview?: any[]
    retriever_name?: string
    deduped_by_influencer?: boolean
  }
  candidateCounts?: Record<string, number>
}

function formatPlatforms(platforms?: string[]): string {
  if (!platforms || platforms.length === 0) return 'Unknown'
  const normalized = platforms.map((p) => p.toLowerCase())
  if (normalized.includes('youtube') && normalized.includes('tiktok')) {
    return 'YouTube + TikTok'
  }
  return platforms.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(', ')
}

function signalEvidenceLabel(signal?: string): string {
  switch (signal) {
    case 'comment_summary':
      return 'Comment-section summary'
    case 'content':
      return 'Video content excerpt'
    case 'topic':
    default:
      return 'Audience discussion topics'
  }
}

function formatScore(value: unknown): string {
  if (value == null || value === '') return '—'
  const num = Number(value)
  return Number.isFinite(num) ? num.toFixed(2) : String(value)
}

function rankingLabel(row: any): string {
  return row.ranking_label || 'Relevance'
}

function rankingValue(row: any): string {
  return formatScore(row.ranking_value ?? row.relevance ?? row.score)
}

function matchedTopics(row: any): string[] {
  return row.matched_topics || row.sample_topics || []
}

function ScoreBreakdown({ breakdown }: { breakdown?: Record<string, unknown> }) {
  if (!breakdown || Object.keys(breakdown).length === 0) return null
  const labels: Record<string, string> = {
    best_topic_strength: 'Topic strength',
    log_comments: 'log(1 + comments)',
    engagement_score: 'Engagement score',
    comment_count: 'Comments',
    total_comment_count: 'Total comments',
    max_video_engagement: 'Max video engagement',
    score: 'Similarity',
    relevance: 'Relevance',
    fused_score: 'Fused RRF',
    content_rrf: 'Content RRF rank',
    summary_rrf: 'Comment-summary RRF rank',
    topic_rrf: 'Topic RRF rank',
  }
  return (
    <div className="mb-3 rounded-lg border border-slate-200/70 bg-white/80 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
        Score breakdown
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {Object.entries(breakdown).map(([key, val]) =>
          val != null ? (
            <div key={key} className="contents">
              <dt className="text-gray-400">{labels[key] || key.replace(/_/g, ' ')}</dt>
              <dd className="text-gray-800 font-mono">{formatScore(val)}</dd>
            </div>
          ) : null
        )}
      </dl>
    </div>
  )
}

function TopicMatchDetails({ details }: { details?: Array<{ topic: string; weight?: number; score?: number }> }) {
  if (!details?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {details.map((item) => (
        <span
          key={item.topic}
          className="inline-flex items-center rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100 px-2.5 py-0.5 text-xs font-medium"
          title={
            item.weight != null || item.score != null
              ? `weight=${item.weight ?? '—'}, similarity=${item.score ?? '—'}`
              : undefined
          }
        >
          {item.topic}
          {item.weight != null && (
            <span className="ml-1 text-indigo-500 font-normal">w={formatScore(item.weight)}</span>
          )}
        </span>
      ))}
    </div>
  )
}

function evidenceText(row: any, signal?: string): string {
  if (row.evidence_snippet) return String(row.evidence_snippet)
  if (signal === 'comment_summary' && row.comment_summary_description) {
    return String(row.comment_summary_description)
  }
  if (signal === 'content') {
    return (
      row.video_description ||
      row.thumbnail_description ||
      row.video_title ||
      row.title ||
      ''
    )
  }
  return ''
}

function TopicChips({ topics }: { topics: string[] }) {
  if (!topics.length) {
    return <span className="text-xs text-gray-400 italic">No topics recorded</span>
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {topics.map((topic) => (
        <span
          key={topic}
          className="inline-flex items-center rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100 px-2.5 py-0.5 text-xs font-medium"
        >
          {topic}
        </span>
      ))}
    </div>
  )
}

function CreatorCard({ row, rank, signal }: { row: any; rank: number; signal?: string }) {
  const name = row.influencer_name || row.creator || 'Unknown creator'
  const rankLabel = rankingLabel(row)
  const rankVal = rankingValue(row)
  const videoCount = row.video_count ?? '—'
  const topics: string[] = matchedTopics(row)
  const topicDetails = row.matched_topic_details as Array<{ topic: string; weight?: number; score?: number }> | undefined
  const platforms = formatPlatforms(row.platforms)
  const why = row.why_retrieved
  const videos: any[] = row.sample_videos || []
  const accounts: any[] = row.accounts || []
  const evidenceLabel = signalEvidenceLabel(signal)
  const showTopics = topics.length > 0 || (topicDetails && topicDetails.length > 0)

  return (
    <div className="rounded-xl border border-gray-100 bg-gradient-to-br from-white to-slate-50/80 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-0.5">
            #{rank}
          </div>
          <h4 className="text-base font-semibold text-gray-900">{name}</h4>
        </div>
        <div className="text-right text-xs text-gray-500 shrink-0">
          <div>
            {rankLabel}: <span className="font-semibold text-gray-800">{rankVal}</span>
          </div>
          <div>
            Videos: <span className="font-semibold text-gray-800">{videoCount}</span>
          </div>
          <div className="mt-0.5">{platforms}</div>
        </div>
      </div>

      {showTopics && (
        <div className="mb-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
            {evidenceLabel}
          </div>
          {topicDetails && topicDetails.length > 0 ? (
            <TopicMatchDetails details={topicDetails} />
          ) : (
            <TopicChips topics={topics} />
          )}
        </div>
      )}

      <ScoreBreakdown breakdown={row.score_breakdown} />

      {videos.length > 0 && (
        <div className="mb-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
            {signal === 'topic' ? 'Example evidence' : `Matching videos (${evidenceLabel.toLowerCase()})`}
          </div>
          <ul className="space-y-2">
            {videos.map((v, idx) => {
              const snippet = evidenceText(v, signal)
              return (
                <li key={v.video_id || v.url || idx} className="text-sm text-gray-700">
                  {v.url ? (
                    <a
                      href={v.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-start gap-1 text-indigo-600 hover:text-indigo-800 hover:underline font-medium"
                    >
                      <span>&ldquo;{v.title || 'Video'}&rdquo;</span>
                      <ExternalLink size={12} className="shrink-0 mt-0.5" />
                    </a>
                  ) : (
                    <span className="font-medium">&ldquo;{v.title || 'Video'}&rdquo;</span>
                  )}
                  {snippet && (
                    <p className="mt-1 text-xs text-gray-500">{snippet}</p>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {accounts.length > 1 && (
        <div className="mb-3 text-xs text-gray-500">
          Accounts:{' '}
          {accounts
            .map((a) => `${a.platform}${a.creator ? `: ${a.creator}` : ''}`)
            .join(' · ')}
        </div>
      )}

      {why && (
        <div className="rounded-lg bg-slate-100/70 border border-slate-200/60 px-3 py-2 text-xs text-gray-600">
          <span className="font-semibold text-gray-700">Why retrieved: </span>
          {why}
        </div>
      )}
    </div>
  )
}

function VideoCard({ row, rank, signal }: { row: any; rank: number; signal?: string }) {
  const title = row.title || row.video_title || 'Untitled video'
  const creator = row.creator || 'Unknown creator'
  const rankLabel = rankingLabel(row)
  const rankVal = rankingValue(row)
  const platform = row.platform
    ? row.platform.charAt(0).toUpperCase() + row.platform.slice(1)
    : 'Unknown'
  const snippet = evidenceText(row, signal)
  const evidenceLabel = signalEvidenceLabel(signal)
  const topics = matchedTopics(row)
  const topicDetails = row.matched_topic_details as Array<{ topic: string; weight?: number; score?: number }> | undefined

  return (
    <div className="rounded-xl border border-gray-100 bg-gradient-to-br from-white to-slate-50/80 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-500 mb-0.5">
            #{rank}
          </div>
          {row.url ? (
            <a
              href={row.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-start gap-1 text-base font-semibold text-indigo-700 hover:text-indigo-900 hover:underline"
            >
              <span>&ldquo;{title}&rdquo;</span>
              <ExternalLink size={14} className="shrink-0 mt-1" />
            </a>
          ) : (
            <h4 className="text-base font-semibold text-gray-900">&ldquo;{title}&rdquo;</h4>
          )}
          <p className="text-sm text-gray-600 mt-1">by {creator}</p>
        </div>
        <div className="text-right text-xs text-gray-500 shrink-0">
          <div>
            {rankLabel}: <span className="font-semibold text-gray-800">{rankVal}</span>
          </div>
          <div className="mt-0.5">{platform}</div>
        </div>
      </div>

      {(topics.length > 0 || (topicDetails && topicDetails.length > 0)) && (
        <div className="mb-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
            Matching comment topics
          </div>
          {topicDetails && topicDetails.length > 0 ? (
            <TopicMatchDetails details={topicDetails} />
          ) : (
            <TopicChips topics={topics} />
          )}
        </div>
      )}

      <ScoreBreakdown breakdown={row.score_breakdown} />

      {snippet && signal !== 'topic' && (
        <div className="mb-3">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">
            {evidenceLabel}
          </div>
          <p className="text-sm text-gray-700 leading-relaxed">{snippet}</p>
        </div>
      )}

      {row.matched_signals && Array.isArray(row.matched_signals) && row.matched_signals.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {row.matched_signals.map((s: string) => (
            <span
              key={s}
              className="rounded-full bg-violet-50 text-violet-700 border border-violet-100 px-2 py-0.5 text-[10px] font-medium"
            >
              {s.replace(/_/g, ' ')}
            </span>
          ))}
        </div>
      )}

      {row.why_retrieved && (
        <div className="rounded-lg bg-slate-100/70 border border-slate-200/60 px-3 py-2 text-xs text-gray-600">
          <span className="font-semibold text-gray-700">Why retrieved: </span>
          {row.why_retrieved}
        </div>
      )}
    </div>
  )
}

function CollapsibleResultsSection({
  title,
  children,
  defaultOpen = false,
}: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="rounded-xl border border-gray-100 bg-white/60 overflow-hidden shadow-sm">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left text-sm font-semibold text-gray-800 hover:bg-slate-50/80 transition-colors"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={16} className="text-gray-500" /> : <ChevronRight size={16} className="text-gray-500" />}
        {title}
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 border-t border-gray-100 space-y-3">
          {children}
        </div>
      )}
    </div>
  )
}

function CountResultView({ row, defaultMinScore }: { row: any; defaultMinScore?: number }) {
  const count = row.count ?? 0
  const samples = row.sample || []
  const minScore = row.min_score ?? defaultMinScore ?? 0.7
  return (
    <>
      <div className="rounded-xl border border-gray-100 bg-gradient-to-br from-white to-slate-50/80 p-4 shadow-sm">
        <div className="text-3xl font-bold text-indigo-600 mb-1">{count}</div>
        <div className="text-sm text-gray-600 mb-3">
          matches above similarity {Number(minScore).toFixed(2)}
        </div>
        {row.explanation?.summary && (
          <p className="text-xs text-gray-500 mb-3">{row.explanation.summary}</p>
        )}
        {samples.length > 0 && (
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
              Sample matches
            </div>
            <ul className="space-y-1 text-sm text-gray-700">
              {samples.map((s: any, idx: number) => (
                <li key={idx}>
                  {s.creator || s.title || JSON.stringify(s)}
                  {s.video_count != null && (
                    <span className="text-gray-400"> · {s.video_count} videos</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </>
  )
}

function TracePanel({
  trace,
  toolName,
  toolInputs,
  researchNotes,
}: {
  trace?: RetrievalTrace
  toolName?: string
  toolInputs?: Record<string, any>
  researchNotes?: string[]
}) {
  const [open, setOpen] = useState(false)
  const [paramsOpen, setParamsOpen] = useState(false)
  const steps = trace?.steps || []
  const notes = researchNotes || trace?.research_notes || []
  const params = trace?.params || {}
  const warnings = trace?.warnings || []
  const degradedScan = Boolean(params.degraded_scan)

  if (!steps.length && !notes.length && !toolName) return null

  return (
    <div className="rounded-xl border border-slate-200/80 bg-slate-50/50 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-700 hover:bg-slate-100/80 transition-colors"
      >
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        How this answer was generated
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-slate-200/60">
          {(degradedScan || warnings.length > 0) && (
            <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 leading-relaxed">
              <span className="font-semibold">Degraded scan — </span>
              {warnings[0] ||
                'Index size lookup failed. Only a small topic sample was searched; results may be incomplete. Retry the query.'}
            </div>
          )}
          {toolName && (
            <div className="pt-3 flex flex-wrap gap-2 text-[11px]">
              <span className="rounded-full bg-white border border-slate-200 px-2.5 py-1 text-slate-600">
                Retriever: {toolName}
              </span>
              {toolInputs?.theme && (
                <span className="rounded-full bg-white border border-slate-200 px-2.5 py-1 text-slate-600">
                  Theme: {toolInputs.theme}
                </span>
              )}
              {toolInputs?.signal && (
                <span className="rounded-full bg-white border border-slate-200 px-2.5 py-1 text-slate-600">
                  Signal: {String(toolInputs.signal).replace(/_/g, ' ')}
                </span>
              )}
            </div>
          )}

          {steps.length > 0 && (
            <ol className="space-y-3">
              {steps.map((s) => (
                <li key={s.step} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold">
                    {s.step}
                  </span>
                  <div>
                    <div className="text-sm font-medium text-gray-800">{s.title}</div>
                    <div className="text-xs text-gray-600 mt-0.5 leading-relaxed">{s.detail}</div>
                  </div>
                </li>
              ))}
            </ol>
          )}

          {Object.keys(params).length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setParamsOpen(!paramsOpen)}
                className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1"
              >
                {paramsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                Retrieval parameters
              </button>
              {paramsOpen && (
                <>
                  {params.ranking_method && (
                    <p className="mt-2 text-xs text-gray-600 leading-relaxed rounded-lg bg-white border border-slate-200 px-3 py-2">
                      <span className="font-semibold text-gray-700">Ranking method: </span>
                      {String(params.ranking_method)}
                    </p>
                  )}
                  <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  {Object.entries(params).map(([key, val]) => (
                    <div key={key} className="contents">
                      <dt className="text-gray-400 capitalize">{key.replace(/_/g, ' ')}</dt>
                      <dd
                        className={`font-mono truncate ${
                          key === 'degraded_scan' && val ? 'text-amber-700 font-semibold' : 'text-gray-700'
                        }`}
                      >
                        {String(val)}
                      </dd>
                    </div>
                  ))}
                  </dl>
                </>
              )}
            </div>
          )}

          {notes.length > 0 && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-2">
                Research notes
              </div>
              <ul className="space-y-1 text-xs text-gray-600 list-disc list-inside">
                {notes.map((note, idx) => (
                  <li key={idx}>{note}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function isVideoResult(results: any[]): boolean {
  if (!results.length) return false
  const first = results[0]
  if (first.count != null && first.count_field != null) return false
  return !!(
    first.video_id ||
    (first.title && (first.url || first.score != null || first.relevance != null) && !first.accounts && !first.influencer_name)
  )
}

function isCountResult(results: any[]): boolean {
  return results.length > 0 && results[0]?.count != null && results[0]?.count_field != null
}

function isCreatorResult(results: any[]): boolean {
  if (!results.length || isVideoResult(results) || isCountResult(results)) return false
  const first = results[0]
  return !!(first.influencer_name || first.accounts || (first.creator && first.relevance != null && first.video_count != null))
}

function Stage2ResultsBody({
  results,
  signal,
  defaultMinScore,
}: {
  results: any[]
  signal?: string
  defaultMinScore?: number
}) {
  if (isCountResult(results)) {
    return (
      <>
        {results.map((row, idx) => (
          <CountResultView key={idx} row={row} defaultMinScore={defaultMinScore} />
        ))}
      </>
    )
  }
  if (isVideoResult(results)) {
    return (
      <>
        {results.map((row, idx) => (
          <VideoCard key={row.video_id || row.url || idx} row={row} rank={idx + 1} signal={signal} />
        ))}
      </>
    )
  }
  if (isCreatorResult(results)) {
    return (
      <>
        {results.map((row, idx) => (
          <CreatorCard key={row.channel_id || row.creator || idx} row={row} rank={idx + 1} signal={signal} />
        ))}
      </>
    )
  }
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-4 text-sm text-gray-700 space-y-2">
      {results.map((row, idx) => (
        <div key={idx} className="border-b border-gray-50 last:border-0 pb-2 last:pb-0">
          {Object.entries(row).map(([key, val]) => (
            <div key={key} className="flex gap-2 text-xs">
              <span className="text-gray-400 capitalize shrink-0">{key.replace(/_/g, ' ')}:</span>
              <span className="text-gray-800 break-all">
                {typeof val === 'object' ? JSON.stringify(val) : String(val ?? '—')}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

export default function MediaRetrievalView({
  results,
  routeType,
  toolName,
  toolInputs,
  retrievalTrace,
  researchNotes,
  dedupedByInfluencer,
  stage1,
  candidateCounts,
}: MediaRetrievalViewProps) {
  const isHybrid = routeType === 'hybrid_media'
  const stage1Results = stage1?.results || stage1?.results_preview || []
  const deduped = dedupedByInfluencer ?? stage1?.deduped_by_influencer
  const signal = toolInputs?.signal as string | undefined
  const defaultMinScore =
    typeof toolInputs?.min_score === 'number'
      ? toolInputs.min_score
      : typeof retrievalTrace?.params?.min_score === 'number'
        ? retrievalTrace.params.min_score
        : undefined

  if (!isHybrid && (!results || results.length === 0)) {
    return (
      <div className="mt-3 text-sm text-gray-500 italic rounded-xl border border-dashed border-gray-200 p-4">
        No media retrieval results to display.
      </div>
    )
  }

  const headerLabel = isHybrid ? 'Hybrid media results' : 'Media retrieval results'

  return (
    <div className="mt-4 space-y-4">
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-indigo-500">
        <Youtube size={14} />
        {headerLabel}
        {deduped && (
          <span className="normal-case font-normal text-gray-400">
            · merged via Influencer
          </span>
        )}
      </div>

      {isHybrid && candidateCounts && Object.keys(candidateCounts).length > 0 && (
        <div className="flex flex-wrap gap-2 text-[11px]">
          {Object.entries(candidateCounts).map(([kind, count]) =>
            count ? (
              <span
                key={kind}
                className="rounded-full bg-amber-50 border border-amber-100 text-amber-800 px-2.5 py-1"
              >
                Stage 1 seeds: {count} {kind.replace(/_/g, ' ')}
              </span>
            ) : null
          )}
        </div>
      )}

      <TracePanel
        trace={retrievalTrace}
        toolName={toolName}
        toolInputs={toolInputs}
        researchNotes={researchNotes}
      />

      {isHybrid ? (
        <>
          {stage1Results.length > 0 && (
            <CollapsibleResultsSection
              title={`Stage 1 — Semantic candidates (${stage1Results.length})`}
            >
              {isCreatorResult(stage1Results) ? (
                stage1Results.map((row, idx) => (
                  <CreatorCard
                    key={row.channel_id || row.creator || idx}
                    row={row}
                    rank={idx + 1}
                    signal={signal}
                  />
                ))
              ) : isVideoResult(stage1Results) ? (
                stage1Results.map((row, idx) => (
                  <VideoCard
                    key={row.video_id || row.url || idx}
                    row={row}
                    rank={idx + 1}
                    signal={signal}
                  />
                ))
              ) : (
                <Stage2ResultsBody
                  results={stage1Results}
                  signal={signal}
                  defaultMinScore={defaultMinScore}
                />
              )}
            </CollapsibleResultsSection>
          )}
          {results && results.length > 0 ? (
            <CollapsibleResultsSection
              title={`Stage 2 — Structural filter results (${results.length})`}
            >
              <Stage2ResultsBody
                results={results}
                signal={signal}
                defaultMinScore={defaultMinScore}
              />
            </CollapsibleResultsSection>
          ) : (
            <div className="text-sm text-gray-500 italic px-1">
              Stage 2 returned no rows after applying the structural filter.
            </div>
          )}
        </>
      ) : isCountResult(results) ? (
        <CollapsibleResultsSection title={`Count results (${results.length})`}>
          {results.map((row, idx) => (
            <CountResultView key={idx} row={row} defaultMinScore={defaultMinScore} />
          ))}
        </CollapsibleResultsSection>
      ) : isVideoResult(results) ? (
        <CollapsibleResultsSection title={`Top matching videos (${results.length})`}>
          {results.map((row, idx) => (
            <VideoCard key={row.video_id || row.url || idx} row={row} rank={idx + 1} signal={signal} />
          ))}
        </CollapsibleResultsSection>
      ) : isCreatorResult(results) ? (
        <CollapsibleResultsSection title={`Top matching creators (${results.length})`}>
          {results.map((row, idx) => (
            <CreatorCard key={row.channel_id || row.creator || idx} row={row} rank={idx + 1} signal={signal} />
          ))}
        </CollapsibleResultsSection>
      ) : (
        <div className="rounded-xl border border-gray-100 p-4 text-sm text-gray-600">
          {results.length} result row(s). Expand trace above for retrieval details.
        </div>
      )}
    </div>
  )
}
