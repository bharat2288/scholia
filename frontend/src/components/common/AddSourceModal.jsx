/**
 * AddSourceModal
 * ==============
 * Tabbed modal for adding sources: Clip URL or Import Note.
 * URL tab auto-detects type (web, tweet, video).
 * Note tab handles markdown file upload with AI metadata suggestions.
 */

import { useState, useMemo, useRef } from 'react'
import { useClipUrl, useClipTweet, useClipVideo, usePreviewNote, useImportNote, useFindOrCreateTags, useFindOrCreatePeople } from '../../hooks/useApi'
import TagInput from './TagInput'
import PersonInput from './PersonInput'

// URL type detection patterns
const URL_PATTERNS = {
  tweet: /(?:twitter\.com|x\.com)\/[^/]+\/status\/\d+/i,
  video: /(?:youtube\.com\/watch|youtu\.be\/|vimeo\.com\/\d+)/i,
}

function detectUrlType(url) {
  if (!url) return null
  if (URL_PATTERNS.tweet.test(url)) return 'tweet'
  if (URL_PATTERNS.video.test(url)) return 'video'
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


// =============================================================================
// Clip URL Tab
// =============================================================================

function ClipUrlTab({ onClose, onSuccess }) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [error, setError] = useState(null)
  const [warning, setWarning] = useState(null)
  const [successResult, setSuccessResult] = useState(null)

  const clipUrl = useClipUrl()
  const clipTweet = useClipTweet()
  const clipVideo = useClipVideo()

  const detectedType = useMemo(() => {
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

    if (!url.trim()) {
      setError('Please enter a URL')
      return
    }

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

  const handleDismissWarning = () => {
    setWarning(null)
    onClose()
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
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

      {detectedType && typeConfig && (
        <div className={`flex items-center gap-3 p-3 rounded-lg ${typeConfig.bgColor}`}>
          <span className={typeConfig.color}>{typeConfig.icon}</span>
          <div className="flex-1">
            <span className={`font-medium ${typeConfig.color}`}>{typeConfig.label}</span>
            <p className="text-xs text-secondary mt-0.5">{typeConfig.description}</p>
          </div>
        </div>
      )}

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
            {detectedType === 'tweet' ? 'Fetching tweet...' : detectedType === 'video' ? 'Fetching transcript...' : 'Fetching and extracting content...'}
          </p>
        </div>
      )}

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
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-md w-full shadow-2xl">
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
            ? 'Supported: web pages, articles, tweets, threads, YouTube videos.'
            : 'Supported: .md, .markdown, .txt files. Headings become navigable sections.'}
        </p>
      </div>
    </div>
  )
}
