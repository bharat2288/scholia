/**
 * AddSourceModal
 * ==============
 * Tabbed modal for adding sources: Clip URL or Import Note.
 * URL tab auto-detects type (web, tweet, video).
 * Note tab handles markdown file upload with AI metadata suggestions.
 */

import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { useClipUrl, useClipTweet, useClipVideo, useTriageRepo, useClipRepo, usePreviewNote, useImportNote, useFindOrCreateTags, useFindOrCreatePeople, useAnalysisTypes } from '../../hooks/useApi'
import { useChatModels } from '../../hooks/useChat'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../../config'
import TagInput from './TagInput'
import PersonInput from './PersonInput'
import { MarkdownContent } from '../../utils/markdown'

// URL type detection patterns
const URL_PATTERNS = {
  tweet: /(?:twitter\.com|x\.com)\/[^/]+\/status\/\d+/i,
  video: /(?:youtube\.com\/watch|youtu\.be\/|vimeo\.com\/\d+)/i,
  repo: /github\.com\/[^/]+\/[^/]+/i,
}

function detectUrlType(url) {
  if (!url) return null
  if (URL_PATTERNS.tweet.test(url)) return 'tweet'
  if (URL_PATTERNS.video.test(url)) return 'video'
  if (URL_PATTERNS.repo.test(url)) return 'repo'
  if (url.match(/^https?:\/\//i) || url.includes('.')) return 'web'
  return null
}

// Type-specific UI configuration
const TYPE_CONFIG = {
  tweet: {
    icon: (
      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
      </svg>
    ),
    label: 'Tweet/Thread',
    color: 'text-[#1d9bf0]',
    bgColor: 'bg-[#1d9bf0]/10',
    description: 'Full tweet content with formatting and media',
  },
  video: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
    label: 'Video',
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    description: 'Full transcript with timestamps from YouTube',
  },
  repo: {
    icon: (
      <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 16 16">
        <path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"/>
      </svg>
    ),
    label: 'GitHub Repo',
    color: 'text-[#f0f6fc]',
    bgColor: 'bg-[#f0f6fc]/10',
    description: 'Analyze repository and import selected files',
  },
  web: {
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
      </svg>
    ),
    label: 'Web Page',
    color: 'text-camel',
    bgColor: 'bg-camel/10',
    description: 'Article, blog post, or any web page',
  },
}


// =============================================================================
// Clip URL Tab
// =============================================================================

function ClipUrlTab({ onClose, onSuccess }) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  const [successResult, setSuccessResult] = useState(null)

  // Repo triage state
  const [intent, setIntent] = useState('')
  const [triageResult, setTriageResult] = useState(null)
  const [selectedFiles, setSelectedFiles] = useState(new Set())
  const [showAllFiles, setShowAllFiles] = useState(false)

  // Video analysis state
  const [selectedAnalyses, setSelectedAnalyses] = useState(['summary', 'key_claims'])
  const [analysisModel, setAnalysisModel] = useState('codex-gpt-5.5')
  const [analysisProgress, setAnalysisProgress] = useState(null) // SSE events
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analysisDone, setAnalysisDone] = useState(false)
  const [triageMode, setTriageMode] = useState(false) // triage vs direct read
  const [triageContent, setTriageContent] = useState(null) // Key Claims markdown for triage popup
  const [isDismissing, setIsDismissing] = useState(false)
  const [runSummaryOnKeep, setRunSummaryOnKeep] = useState(true) // checkbox for Summary after triage Keep
  const eventSourceRef = useRef(null)

  const { data: analysisTypes } = useAnalysisTypes()
  const { data: chatModels } = useChatModels()
  const queryClient = useQueryClient()

  const clipUrl = useClipUrl()
  const clipTweet = useClipTweet()
  const clipVideo = useClipVideo()
  const triageRepo = useTriageRepo()
  const clipRepo = useClipRepo()

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [])

  const detectedType = useMemo(() => {
    let testUrl = url.trim()
    if (testUrl && !testUrl.match(/^https?:\/\//i)) {
      testUrl = 'https://' + testUrl
    }
    return detectUrlType(testUrl)
  }, [url])

  const typeConfig = detectedType ? TYPE_CONFIG[detectedType] : null
  const isLoading = clipUrl.isPending || clipTweet.isPending || clipVideo.isPending || triageRepo.isPending || clipRepo.isPending

  // Calculate selected files size
  const selectedSize = useMemo(() => {
    if (!triageResult) return 0
    const allFiles = [
      ...triageResult.recommended_files,
      ...(triageResult.file_tree || []).map(p => ({ path: p, size_bytes: 0 }))
    ]
    const sizeMap = {}
    for (const f of allFiles) sizeMap[f.path] = f.size_bytes || 0
    let total = 0
    for (const path of selectedFiles) total += sizeMap[path] || 0
    return total
  }, [selectedFiles, triageResult])

  // Start SSE stream for video analysis after clip
  // typesOverride: explicit list of types (used by Keep → Summary flow)
  const startAnalysisStream = useCallback((sourceId, isTriage = false, typesOverride = null) => {
    const typesToRun = typesOverride || (isTriage ? ['key_claims'] : selectedAnalyses)
    if (typesToRun.length === 0) return

    setIsAnalyzing(true)
    setAnalysisDone(false)
    setTriageContent(null)
    setAnalysisProgress({ stage: 'starting', message: isTriage ? 'Running Key Claims analysis...' : 'Starting analysis...' })

    const typesParam = typesToRun.join(',')
    const sseUrl = `${API_BASE}/sources/${sourceId}/analyze/stream?types=${typesParam}&model=${analysisModel}`

    const es = new EventSource(sseUrl)
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setAnalysisProgress(data)

        if (data.stage === 'complete') {
          es.close()
          eventSourceRef.current = null
          setIsAnalyzing(false)

          if (isTriage) {
            // Fetch the Key Claims content for the triage popup
            fetch(`${API_BASE}/sources/${sourceId}/analyses`)
              .then(r => { if (!r.ok) throw new Error(); return r.json() })
              .then(analyses => {
                const keyClaims = analyses.find(a => a.analysis_type === 'key_claims')
                setTriageContent(keyClaims?.content || 'No key claims generated.')
                setAnalysisDone(true)
              })
              .catch(() => {
                setTriageContent('Failed to load key claims.')
                setAnalysisDone(true)
              })
          } else {
            setAnalysisDone(true)
            // Invalidate caches for Reader and library
            queryClient.invalidateQueries({ queryKey: ['reading', sourceId] })
            queryClient.invalidateQueries({ queryKey: ['sources', sourceId, 'analyses'] })
            queryClient.invalidateQueries({ queryKey: ['sources'] })
          }
        }

        if (data.status === 'error') {
          setError(prev => prev ? `${prev}\n${data.message}` : data.message)
        }
      } catch (err) {
          if (err instanceof SyntaxError) return
          console.error('SSE message handling error:', err)
        }
    }

    es.onerror = () => {
      es.close()
      eventSourceRef.current = null
      setIsAnalyzing(false)
      setError('Analysis stream disconnected')
    }
  }, [selectedAnalyses, analysisModel, queryClient])

  // Shared clip logic — isTriage param used for video mode
  const handleClip = async (isTriage = false) => {
    setError(null)

    if (!url.trim()) {
      setError('Please enter a URL')
      return
    }

    let processedUrl = url.trim()
    if (!processedUrl.match(/^https?:\/\//i)) {
      processedUrl = 'https://' + processedUrl
    }

    const urlType = detectUrlType(processedUrl)

    // Repo: stage 1 triage
    if (urlType === 'repo' && !triageResult) {
      try {
        const result = await triageRepo.mutateAsync({
          url: processedUrl,
          intent: intent.trim() || undefined,
        })
        setTriageResult(result)
        setSelectedFiles(new Set(result.recommended_files.map(f => f.path)))
      } catch (err) {
        setError(err.message || 'Failed to analyze repository')
      }
      return
    }

    // Repo: stage 2 import
    if (urlType === 'repo' && triageResult) {
      try {
        const result = await clipRepo.mutateAsync({
          url: processedUrl,
          selected_files: [...selectedFiles],
          intent: intent.trim() || undefined,
          summary: triageResult.summary,
          interest_tags: triageResult.interest_tags,
        })
        onSuccess?.(result)
        onClose()
      } catch (err) {
        setError(err.message || 'Failed to import repository')
      }
      return
    }

    // Standard clip flow (tweet, video, web)
    try {
      let result
      if (urlType === 'tweet') {
        result = await clipTweet.mutateAsync({ url: processedUrl })
      } else if (urlType === 'video') {
        result = await clipVideo.mutateAsync({ url: processedUrl })
      } else {
        result = await clipUrl.mutateAsync({
          url: processedUrl,
          title: title.trim() || undefined
        })
      }
      // Video: start analysis stream (triage or full)
      if (urlType === 'video' && result?.id) {
        if (isTriage) {
          setSuccessResult(result)
          startAnalysisStream(result.id, true)
          return
        }
        if (selectedAnalyses.length > 0) {
          setSuccessResult(result)
          startAnalysisStream(result.id, false)
          return
        }
      }

      onSuccess?.(result)

      if (result?.warning) {
        setSuccessResult(result)
        setWarning(result.warning)
      } else {
        onClose()
      }
    } catch (err) {
      setError(err.message || `Failed to clip ${urlType || 'URL'}`)
    }
  }

  // Called by video buttons directly (bypasses form submit)
  const handleSubmitWithMode = (isTriage) => handleClip(isTriage)

  // Called by form submit (non-video types)
  const handleSubmit = (e) => {
    e.preventDefault()
    handleClip(false)
  }

  const handleDismissWarning = () => {
    setWarning(null)
    onClose()
  }

  const handleResetTriage = () => {
    setTriageResult(null)
    setSelectedFiles(new Set())
    setShowAllFiles(false)
    setError(null)
  }

  // Triage: Keep — source stays, optionally run Summary before closing
  const handleTriageKeep = () => {
    const sourceId = successResult?.id
    if (!sourceId) return

    if (runSummaryOnKeep) {
      // Switch out of triage mode so the standard completion UI shows after Summary
      setTriageMode(false)
      startAnalysisStream(sourceId, false, ['summary'])
    } else {
      // No Summary — close immediately
      queryClient.invalidateQueries({ queryKey: ['reading', sourceId] })
      queryClient.invalidateQueries({ queryKey: ['sources', sourceId, 'analyses'] })
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      onSuccess?.(successResult)
      onClose()
    }
  }

  // Triage: Dismiss — delete source + analyses
  const handleTriageDismiss = async () => {
    const sourceId = successResult?.id
    if (!sourceId) return
    setIsDismissing(true)
    try {
      const res = await fetch(`${API_BASE}/sources/${sourceId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Delete failed: ${res.status}`)
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to dismiss source')
      setIsDismissing(false)
    }
  }

  const toggleFile = (path) => {
    setSelectedFiles(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const selectAll = () => {
    if (!triageResult) return
    setSelectedFiles(new Set(triageResult.recommended_files.map(f => f.path)))
  }

  const deselectAll = () => setSelectedFiles(new Set())

  const toggleAnalysis = (type) => {
    setSelectedAnalyses(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    )
  }

  // Priority badge colors
  const priorityStyles = {
    high: 'bg-camel/20 text-camel',
    medium: 'bg-[#f0f6fc]/10 text-secondary',
    low: 'bg-elevated text-muted',
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* URL input (always visible) */}
      <div>
        <label className="label text-muted block mb-1.5">URL</label>
        <input
          type="text"
          value={url}
          onChange={(e) => { setUrl(e.target.value); if (triageResult) handleResetTriage() }}
          placeholder="Paste any URL — web page, tweet, video, GitHub repo..."
          className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
          disabled={isLoading}
          autoFocus
        />
      </div>

      {/* Type detection pill */}
      {detectedType && typeConfig && !triageResult && (
        <div className={`flex items-center gap-3 p-3 rounded-lg ${typeConfig.bgColor}`}>
          <span className={typeConfig.color}>{typeConfig.icon}</span>
          <div className="flex-1">
            <span className={`font-medium ${typeConfig.color}`}>{typeConfig.label}</span>
            <p className="text-xs text-secondary mt-0.5">{typeConfig.description}</p>
          </div>
        </div>
      )}

      {/* Video analysis picker */}
      {detectedType === 'video' && !isAnalyzing && !analysisDone && (
        <div className="space-y-3">
          {/* Analysis type checkboxes */}
          <div>
            <label className="label text-muted block mb-1.5">Analyses</label>
            <div className="space-y-1">
              {(analysisTypes || []).map(at => (
                <label
                  key={at.type}
                  className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-raised cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selectedAnalyses.includes(at.type)}
                    onChange={() => toggleAnalysis(at.type)}
                    className="accent-camel"
                  />
                  <div>
                    <span className="text-sm text-primary">{at.display_name}</span>
                    <p className="text-xs text-muted">{at.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Model dropdown */}
          {selectedAnalyses.length > 0 && chatModels?.length > 0 && (
            <div>
              <label className="label text-muted block mb-1.5">Model</label>
              <select
                value={analysisModel}
                onChange={(e) => setAnalysisModel(e.target.value)}
                className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
              >
                <option value="codex-gpt-5.5">
                  Codex GPT-5.5 — subscription
                </option>
                {chatModels.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.name} — ${m.pricing?.input ?? '?'}/M in, ${m.pricing?.output ?? '?'}/M out
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Cost note */}
          {selectedAnalyses.length > 0 && (
            <p className="text-xs text-muted">
              Codex uses your local subscription-backed CLI. API-priced models remain available as manual fallbacks.
            </p>
          )}
        </div>
      )}

      {/* Analysis progress (SSE streaming) */}
      {isAnalyzing && analysisProgress && (
        <div className="space-y-3">
          <div className="bg-raised rounded-lg p-3">
            <p className="text-sm text-primary mb-1 font-medium">
              Video clipped — running analyses...
            </p>
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 animate-spin text-camel flex-shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span className="text-sm text-secondary">{analysisProgress.message}</span>
            </div>
            {analysisProgress.total > 0 && (
              <div className="mt-2 h-1.5 bg-base rounded-full overflow-hidden">
                <div
                  className="h-full bg-camel rounded-full transition-all duration-300"
                  style={{ width: `${((analysisProgress.current || 0) / analysisProgress.total) * 100}%` }}
                />
              </div>
            )}
            {analysisProgress.cost_usd > 0 && (
              <p className="text-xs text-muted mt-1.5">
                Cost so far: ${analysisProgress.cost_usd.toFixed(4)}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Analysis complete — triage mode: show Key Claims popup */}
      {analysisDone && triageMode && triageContent && (
        <div className="space-y-4">
          <div
            className="bg-surface/50 border border-subtle rounded-lg p-5"
            style={{ fontFamily: "'Plus Jakarta Sans', -apple-system, sans-serif" }}
          >
            <div className="flex items-center gap-2 mb-4">
              <svg className="w-4 h-4 text-camel" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              <h3 className="text-primary font-display text-lg">Key Claims</h3>
              {analysisProgress?.total_cost_usd > 0 && (
                <span className="text-xs text-muted ml-auto">${analysisProgress.total_cost_usd.toFixed(4)}</span>
              )}
            </div>
            <div className="max-h-[50vh] overflow-y-auto pr-1">
              <MarkdownContent content={triageContent} inheritFontSize prose className="text-secondary" />
            </div>
          </div>
          <p className="text-xs text-muted text-center">Worth a deeper read?</p>
          <label className="flex items-center gap-2 justify-center cursor-pointer py-1">
            <input
              type="checkbox"
              checked={runSummaryOnKeep}
              onChange={(e) => setRunSummaryOnKeep(e.target.checked)}
              className="accent-camel w-3.5 h-3.5"
            />
            <span className="text-xs text-tertiary">Run Summary on keep</span>
          </label>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={handleTriageKeep}
              className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5"
            >
              Keep
            </button>
            <button
              type="button"
              onClick={handleTriageDismiss}
              disabled={isDismissing}
              className="flex-1 py-2.5 px-4 bg-raised border border-subtle text-secondary font-medium rounded-lg hover:bg-red-900/20 hover:border-red-800 hover:text-red-400 transition-all disabled:opacity-50"
            >
              {isDismissing ? 'Removing...' : 'Dismiss'}
            </button>
          </div>
        </div>
      )}

      {/* Analysis complete — direct mode: done */}
      {analysisDone && !triageMode && (
        <div className="bg-surface border border-subtle rounded-lg p-4 space-y-3">
          <div className="flex items-start gap-2">
            <svg className="w-5 h-5 text-green-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
            <div>
              <p className="text-primary text-sm font-medium">Video clipped and analyzed</p>
              {analysisProgress?.total_cost_usd > 0 && (
                <p className="text-muted text-xs mt-0.5">
                  Total cost: ${analysisProgress.total_cost_usd.toFixed(4)}
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-full py-2 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5"
          >
            Done
          </button>
        </div>
      )}

      {/* Web-only title field */}
      {detectedType === 'web' && (
        <div>
          <label className="label text-muted block mb-1.5">
            Title <span className="font-normal text-tertiary">(optional)</span>
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Auto-detected from page"
            className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
            disabled={isLoading}
          />
        </div>
      )}

      {/* Repo: stage 1 — intent field */}
      {detectedType === 'repo' && !triageResult && (
        <div>
          <label className="label text-muted block mb-1.5">
            Interest <span className="font-normal text-tertiary">(optional)</span>
          </label>
          <textarea
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            placeholder="What interests you about this repo? e.g. 'how they handle auth' or 'the data pipeline architecture'"
            rows={2}
            className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)] resize-none"
            disabled={isLoading}
          />
        </div>
      )}

      {/* Repo: stage 2 — triage results */}
      {triageResult && (
        <div className="space-y-3 max-h-[50vh] overflow-y-auto pr-1">
          {/* Repo metadata card */}
          <div className="bg-[#f0f6fc]/5 border border-[#f0f6fc]/10 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[#f0f6fc] font-medium">{triageResult.repo.full_name}</span>
              <span className="text-xs text-muted">
                {triageResult.repo.stars.toLocaleString()} stars
              </span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-elevated text-secondary">
                {triageResult.repo.language}
              </span>
            </div>
            {triageResult.repo.description && (
              <p className="text-xs text-secondary">{triageResult.repo.description}</p>
            )}
          </div>

          {/* LLM summary */}
          <p className="text-sm text-secondary">{triageResult.summary}</p>

          {/* Interest tags */}
          {triageResult.interest_tags?.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {triageResult.interest_tags.map(tag => (
                <span key={tag} className="text-xs px-2 py-0.5 rounded-full bg-camel/15 text-camel">
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* File selection controls */}
          <div className="flex items-center justify-between">
            <span className="label text-muted">
              {selectedFiles.size} file{selectedFiles.size !== 1 ? 's' : ''} selected
              {selectedSize > 0 && (
                <span className="font-normal text-tertiary ml-1">
                  (~{(selectedSize / 1024).toFixed(0)}KB)
                </span>
              )}
            </span>
            <div className="flex gap-2 text-xs">
              <button type="button" onClick={selectAll} className="text-camel hover:underline">
                Select all
              </button>
              <span className="text-muted">|</span>
              <button type="button" onClick={deselectAll} className="text-secondary hover:underline">
                Clear
              </button>
            </div>
          </div>

          {/* Size warning */}
          {selectedSize > 500_000 && (
            <div className="bg-camel/10 border border-camel/20 rounded-lg p-2">
              <p className="text-xs text-camel">
                Large import ({(selectedSize / 1024).toFixed(0)}KB). Consider selecting fewer files for faster processing.
              </p>
            </div>
          )}

          {/* Recommended files checklist */}
          <div className="space-y-1">
            {triageResult.recommended_files.map(file => (
              <label
                key={file.path}
                className="flex items-start gap-2 p-2 rounded-lg hover:bg-raised cursor-pointer group"
              >
                <input
                  type="checkbox"
                  checked={selectedFiles.has(file.path)}
                  onChange={() => toggleFile(file.path)}
                  className="mt-0.5 accent-camel"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-primary font-mono truncate">{file.path}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0 ${priorityStyles[file.priority] || priorityStyles.medium}`}>
                      {file.priority === 'high' ? 'key' : file.priority}
                    </span>
                  </div>
                  <p className="text-xs text-muted mt-0.5">{file.reason}</p>
                </div>
              </label>
            ))}
          </div>

          {/* Browse all files (collapsible) */}
          {triageResult.file_tree?.length > triageResult.recommended_files.length && (
            <div>
              <button
                type="button"
                onClick={() => setShowAllFiles(!showAllFiles)}
                className="text-xs text-secondary hover:text-primary flex items-center gap-1"
              >
                <svg className={`w-3 h-3 transition-transform ${showAllFiles ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                Browse all {triageResult.total_files} files
              </button>

              {showAllFiles && (
                <div className="mt-2 max-h-48 overflow-y-auto space-y-0.5 border border-subtle rounded-lg p-2">
                  {triageResult.file_tree
                    .filter(p => !triageResult.recommended_files.some(f => f.path === p))
                    .map(path => (
                      <label
                        key={path}
                        className="flex items-center gap-2 py-0.5 px-1 rounded hover:bg-raised cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedFiles.has(path)}
                          onChange={() => toggleFile(path)}
                          className="accent-camel"
                        />
                        <span className="text-xs text-secondary font-mono truncate">{path}</span>
                      </label>
                    ))}
                </div>
              )}
            </div>
          )}

          {/* Back button to re-triage */}
          <button
            type="button"
            onClick={handleResetTriage}
            className="text-xs text-muted hover:text-secondary"
          >
            &larr; Back to re-analyze
          </button>
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-3">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {warning && successResult && (
        <div className="bg-surface border border-subtle rounded-lg p-4 space-y-3">
          <div className="flex items-start gap-2">
            <svg className="w-4 h-4 text-muted flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div>
              <p className="text-secondary text-sm">Clipped successfully</p>
              <p className="text-muted text-xs mt-1">{warning}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleDismissWarning}
            className="w-full py-2 px-4 bg-raised hover:bg-elevated text-secondary rounded-lg transition-colors text-sm"
          >
            Done
          </button>
        </div>
      )}

      {isLoading && (
        <div className="bg-raised rounded-lg p-3">
          <p className="text-secondary text-sm flex items-center gap-2">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {triageRepo.isPending ? 'Analyzing repository...' :
             clipRepo.isPending ? 'Importing files...' :
             detectedType === 'tweet' ? 'Fetching tweet...' :
             detectedType === 'video' ? 'Fetching transcript...' :
             'Fetching and extracting content...'}
          </p>
        </div>
      )}

      {/* Action buttons — hidden during/after analysis */}
      {!isAnalyzing && !analysisDone && (
        <div className="flex gap-3 pt-2">
          {/* Video: two action buttons */}
          {detectedType === 'video' ? (
            <>
              <button
                type="button"
                onClick={() => { setTriageMode(false); handleSubmitWithMode(false) }}
                disabled={isLoading || !detectedType}
                className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-none"
              >
                {isLoading ? 'Clipping...' : selectedAnalyses.length > 0 ? 'Clip & Read' : 'Clip'}
              </button>
              <button
                type="button"
                onClick={() => { setTriageMode(true); handleSubmitWithMode(true) }}
                disabled={isLoading || !detectedType}
                className="flex-1 py-2.5 px-4 bg-raised border border-subtle text-secondary font-medium rounded-lg hover:bg-elevated hover:text-primary transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? 'Clipping...' : 'Clip & Triage'}
              </button>
            </>
          ) : (
            <button
              type="submit"
              disabled={isLoading || !detectedType || (triageResult && selectedFiles.size === 0)}
              className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-none"
            >
              {isLoading ? (triageRepo.isPending ? 'Analyzing...' : clipRepo.isPending ? 'Importing...' : 'Clipping...') :
               detectedType === 'repo' && !triageResult ? 'Analyze Repository' :
               triageResult ? `Import ${selectedFiles.size} File${selectedFiles.size !== 1 ? 's' : ''}` :
               'Clip'}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="px-4 py-2.5 text-muted hover:text-secondary rounded-lg transition-colors"
          >
            Cancel
          </button>
        </div>
      )}
    </form>
  )
}


// =============================================================================
// Import Note Tab
// =============================================================================

function ImportNoteTab({ onClose, onSuccess }) {
  const fileInputRef = useRef(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [error, setError] = useState(null)
  const [aiSuggest, setAiSuggest] = useState(false) // off by default

  // Form fields — same structure as MetadataEditModal
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')          // semicolon-separated display string
  const [authorGluonIds, setAuthorGluonIds] = useState('') // JSON string of IDs
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [description, setDescription] = useState('')
  const [keywords, setKeywords] = useState('')       // semicolon-separated display string
  const [keywordGluonIds, setKeywordGluonIds] = useState('') // JSON string of IDs
  const [wordCount, setWordCount] = useState(null)
  const [previewed, setPreviewed] = useState(false)

  const previewNote = usePreviewNote()
  const importNote = useImportNote()
  const findOrCreateTags = useFindOrCreateTags()
  const findOrCreatePeople = useFindOrCreatePeople()

  const isLoading = previewNote.isPending || importNote.isPending

  // Extract title from markdown content locally (no server call needed)
  const extractTitleLocally = (text, filename) => {
    const match = text.match(/^#{1,6}\s+(.+?)$/m)
    if (match) return match[1].trim()
    // Fallback to filename
    return filename.replace(/\.(md|markdown|txt)$/i, '').replace(/[-_]/g, ' ')
  }

  const handleFileSelect = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setSelectedFile(file)
    setError(null)
    setPreviewed(false)

    if (aiSuggest) {
      // Full preview with AI suggestions
      try {
        const result = await previewNote.mutateAsync(file)
        setTitle(result.title || '')
        setWordCount(result.word_count)
        await applyAiSuggestions(result.suggestions)
        setPreviewed(true)
      } catch (err) {
        setError(err.message || 'Failed to preview file')
      }
    } else {
      // Local-only preview: read file, extract title + word count
      try {
        const text = await file.text()
        setTitle(extractTitleLocally(text, file.name))
        setWordCount(text.split(/\s+/).length)
        setPreviewed(true)
      } catch (err) {
        setError('Failed to read file')
      }
    }
  }

  // Apply AI suggestions from preview response — creates gluon records
  const applyAiSuggestions = async (suggestions) => {
    if (!suggestions?.suggestions) return

    for (const s of suggestions.suggestions) {
      if (s.field === 'keywords' && s.value) {
        const names = s.value.split(/[;,]/).map(k => k.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const tagResults = await findOrCreateTags.mutateAsync(names)
            setKeywords(tagResults.map(t => t.name).join('; '))
            setKeywordGluonIds(JSON.stringify(tagResults.map(t => t.id)))
          } catch (err) {
            setKeywords(names.join('; '))
          }
        }
      }
      if (s.field === 'abstract' && s.value) {
        setDescription(s.value)
      }
      if (s.field === 'author' && s.value) {
        const names = s.value.split(/;/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const personResults = await findOrCreatePeople.mutateAsync(names)
            setAuthor(personResults.map(p => p.name).join('; '))
            setAuthorGluonIds(JSON.stringify(personResults.map(p => p.id)))
          } catch (err) {
            setAuthor(s.value)
          }
        }
      }
      if (s.field === 'year' && s.value) {
        setYear(s.value)
      }
    }
  }

  // Toggle AI suggest — if turning on with a file already selected, run suggestions
  const handleToggleAi = async () => {
    const newValue = !aiSuggest
    setAiSuggest(newValue)

    if (newValue && selectedFile && previewed) {
      // Run AI suggestions now
      setError(null)
      try {
        const result = await previewNote.mutateAsync(selectedFile)
        setTitle(prev => prev || result.title || '')
        setWordCount(result.word_count)
        await applyAiSuggestions(result.suggestions)
      } catch (err) {
        setError(err.message || 'Failed to get AI suggestions')
      }
    }
  }

  const handleImport = async () => {
    if (!selectedFile) return
    setError(null)

    try {
      const result = await importNote.mutateAsync({
        file: selectedFile,
        title: title.trim() || undefined,
        author: author.trim() || undefined,
        year: year.trim() || undefined,
        description: description.trim() || undefined,
        keywords: keywords.trim() || undefined,
        keyword_gluon_ids: keywordGluonIds || undefined,
        author_gluon_ids: authorGluonIds || undefined,
      })
      onSuccess?.(result)
      onClose()
    } catch (err) {
      setError(err.message || 'Failed to import note')
    }
  }

  return (
    <div className="space-y-4">
      {/* File picker */}
      <div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".md,.markdown,.txt"
          onChange={handleFileSelect}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isLoading}
          className="w-full py-6 border-2 border-dashed border-subtle rounded-lg hover:border-camel/50 transition-colors flex flex-col items-center gap-2 text-secondary hover:text-primary"
        >
          <svg className="w-8 h-8 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {selectedFile ? (
            <span className="text-sm">
              <span className="text-camel font-medium">{selectedFile.name}</span>
              {wordCount && <span className="text-muted ml-2">({wordCount.toLocaleString()} words)</span>}
            </span>
          ) : (
            <span className="text-sm text-muted">Choose a .md, .markdown, or .txt file</span>
          )}
        </button>
      </div>

      {/* AI suggestions toggle */}
      <div className="flex items-center justify-between">
        <label className="text-sm text-secondary flex items-center gap-2">
          <svg className="w-4 h-4 text-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
          AI suggestions
        </label>
        <button
          type="button"
          onClick={handleToggleAi}
          disabled={previewNote.isPending}
          className={`relative w-10 h-5 rounded-full transition-colors ${
            aiSuggest ? 'bg-camel' : 'bg-elevated'
          }`}
        >
          <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-primary shadow transition-transform ${
            aiSuggest ? 'translate-x-5' : ''
          }`} />
        </button>
      </div>

      {/* Preview loading */}
      {previewNote.isPending && (
        <div className="bg-raised rounded-lg p-3">
          <p className="text-secondary text-sm flex items-center gap-2">
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Analyzing file...
          </p>
        </div>
      )}

      {/* Metadata form (shown after preview) */}
      {previewed && (
        <>
          <div>
            <label className="label text-muted block mb-1.5">Title</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
              disabled={isLoading}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <PersonInput
                value={author}
                gluonIds={authorGluonIds}
                onChange={setAuthor}
                onGluonIdsChange={setAuthorGluonIds}
                label="Author(s)"
                placeholder="Type author name..."
              />
            </div>
            <div>
              <label className="label text-muted block mb-1.5">Year</label>
              <input
                type="text"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
                disabled={isLoading}
              />
            </div>
          </div>

          {/* Keywords — uses TagInput with autocomplete + gluon linking */}
          <TagInput
            value={keywords}
            gluonIds={keywordGluonIds}
            onChange={setKeywords}
            onGluonIdsChange={setKeywordGluonIds}
            label="Keywords"
            placeholder="Type to search tags..."
          />

          <div>
            <label className="label text-muted block mb-1.5">
              Description <span className="font-normal text-tertiary">(optional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Brief description of the note..."
              className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)] resize-none"
              disabled={isLoading}
            />
          </div>
        </>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-800 rounded-lg p-3">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={handleImport}
          disabled={isLoading || !previewed}
          className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-none"
        >
          {importNote.isPending ? 'Importing...' : 'Import'}
        </button>
        <button
          type="button"
          onClick={onClose}
          disabled={isLoading}
          className="px-4 py-2.5 text-muted hover:text-secondary rounded-lg transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}


// =============================================================================
// Main Modal
// =============================================================================

export default function AddSourceModal({ onClose, onSuccess }) {
  const [activeTab, setActiveTab] = useState('url') // 'url' | 'note'

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-md w-full shadow-2xl max-h-[calc(100vh-2rem)] overflow-y-auto">
        <h2 className="font-display text-2xl text-primary mb-4">Add Source</h2>

        {/* Tab switcher */}
        <div className="flex gap-1 p-1 bg-base rounded-lg mb-5">
          <button
            onClick={() => setActiveTab('url')}
            className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'url'
                ? 'bg-raised text-primary shadow-sm'
                : 'text-muted hover:text-secondary'
            }`}
          >
            Clip URL
          </button>
          <button
            onClick={() => setActiveTab('note')}
            className={`flex-1 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
              activeTab === 'note'
                ? 'bg-raised text-primary shadow-sm'
                : 'text-muted hover:text-secondary'
            }`}
          >
            Import Note
          </button>
        </div>

        {/* Tab content */}
        {activeTab === 'url' ? (
          <ClipUrlTab onClose={onClose} onSuccess={onSuccess} />
        ) : (
          <ImportNoteTab onClose={onClose} onSuccess={onSuccess} />
        )}

        {/* Help text */}
        <p className="text-xs text-muted mt-4">
          {activeTab === 'url'
            ? 'Supported: web pages, articles, tweets, threads, YouTube videos, GitHub repos.'
            : 'Supported: .md, .markdown, .txt files. Headings become navigable sections.'}
        </p>
      </div>
    </div>
  )
}
