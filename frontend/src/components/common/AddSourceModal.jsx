/**
 * AddSourceModal
 * ==============
 * Unified modal for adding any source by URL.
 * Automatically detects URL type (web, tweet, video) and routes accordingly.
 */

import { useState, useMemo } from 'react'
import { useClipUrl, useClipTweet, useClipVideo } from '../../hooks/useApi'

// URL type detection patterns
const URL_PATTERNS = {
  tweet: /(?:twitter\.com|x\.com)\/[^/]+\/status\/\d+/i,
  video: /(?:youtube\.com\/watch|youtu\.be\/|vimeo\.com\/\d+)/i,
}

function detectUrlType(url) {
  if (!url) return null
  if (URL_PATTERNS.tweet.test(url)) return 'tweet'
  if (URL_PATTERNS.video.test(url)) return 'video'
  // Default to web for any other URL
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

export default function AddSourceModal({ onClose, onSuccess }) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  const [successResult, setSuccessResult] = useState(null)

  const clipUrl = useClipUrl()
  const clipTweet = useClipTweet()
  const clipVideo = useClipVideo()

  // Detect URL type as user types
  const detectedType = useMemo(() => {
    // Add https:// for detection if missing
    let testUrl = url.trim()
    if (testUrl && !testUrl.match(/^https?:\/\//i)) {
      testUrl = 'https://' + testUrl
    }
    return detectUrlType(testUrl)
  }, [url])

  const typeConfig = detectedType ? TYPE_CONFIG[detectedType] : null
  const isLoading = clipUrl.isPending || clipTweet.isPending || clipVideo.isPending

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)

    // Basic URL validation
    if (!url.trim()) {
      setError('Please enter a URL')
      return
    }

    // Add https:// if no protocol
    let processedUrl = url.trim()
    if (!processedUrl.match(/^https?:\/\//i)) {
      processedUrl = 'https://' + processedUrl
    }

    const urlType = detectUrlType(processedUrl)

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
      onSuccess?.(result)

      // If result has a warning, show it before closing
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

  // Handle dismissing the warning and closing
  const handleDismissWarning = () => {
    setWarning(null)
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-md w-full shadow-2xl">
        <h2 className="font-display text-2xl text-primary mb-4">Clip URL</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* URL Input */}
          <div>
            <label className="label text-muted block mb-1.5">URL</label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Paste any URL — web page, tweet, video..."
              className="w-full bg-base border border-subtle rounded-lg px-4 py-2.5 text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
              disabled={isLoading}
              autoFocus
            />
          </div>

          {/* Detected Type Indicator */}
          {detectedType && typeConfig && (
            <div className={`flex items-center gap-3 p-3 rounded-lg ${typeConfig.bgColor}`}>
              <span className={typeConfig.color}>{typeConfig.icon}</span>
              <div className="flex-1">
                <span className={`font-medium ${typeConfig.color}`}>{typeConfig.label}</span>
                <p className="text-xs text-secondary mt-0.5">{typeConfig.description}</p>
              </div>
            </div>
          )}

          {/* Title Override (only for web) */}
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

          {/* Error Message */}
          {error && (
            <div className="bg-red-900/20 border border-red-800 rounded-lg p-3">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}

          {/* Info Note (shown after successful clip with note) */}
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

          {/* Loading Message */}
          {isLoading && (
            <div className="bg-raised rounded-lg p-3">
              <p className="text-secondary text-sm flex items-center gap-2">
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {detectedType === 'tweet' ? 'Fetching tweet...' : detectedType === 'video' ? 'Fetching transcript...' : 'Fetching and extracting content...'}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              type="submit"
              disabled={isLoading || !detectedType}
              className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-none"
            >
              {isLoading ? 'Clipping...' : 'Clip'}
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
        </form>

        {/* Help text */}
        <p className="text-xs text-muted mt-4">
          Supported: web pages, articles, tweets, threads, YouTube videos.
        </p>
      </div>
    </div>
  )
}
