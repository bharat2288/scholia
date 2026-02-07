import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useRawText, useUpdateRawText, usePreviewSections } from '../../hooks/useApi'
import { API_BASE } from '../../config'

/**
 * Section Editor
 * ==============
 * Three-pane editor for fixing OCR errors in extracted text:
 * - Left: PDF viewer (reference)
 * - Center: Raw text editor with syntax highlighting
 * - Right: Live preview (section structure) + Issues panel
 *
 * Common fixes:
 * 1. Missing [SECTION] markers → text renders as body instead of heading
 * 2. Missing # after [SECTION] → marker present but no heading level
 * 3. Duplicate text → OCR grabbed same content twice
 *
 * Smart features:
 * - Detects [SECTION] without heading level (highlighted orange)
 * - Detects potential headings via heuristics
 * - Click-to-jump to issues
 * - Ctrl+1-6 to set heading level on current line
 */

/**
 * Detect structure issues in the content
 */
function detectStructureIssues(content) {
  if (!content) return { missingLevels: [], potentialHeadings: [] }

  const lines = content.split('\n')
  const missingLevels = []
  const potentialHeadings = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    // Check for [SECTION] without # level
    if (trimmed.startsWith('[SECTION]') && !trimmed.match(/\[SECTION\]\s*#{1,6}/)) {
      const title = trimmed.replace('[SECTION]', '').trim()
      missingLevels.push({
        type: 'missing_level',
        lineNumber: i + 1,
        lineIndex: i,
        text: title || '(empty)',
        raw: line
      })
      continue
    }

    // Skip lines that are already sections, pages, figures, etc.
    if (trimmed.startsWith('[')) continue

    // Skip empty or very short lines
    if (trimmed.length < 4 || trimmed.length > 80) continue

    // Skip lines that look like body text (end with sentence punctuation)
    if (/[.,:;]$/.test(trimmed)) continue

    // Heuristics for potential headings
    const nextLine = lines[i + 1]?.trim() || ''
    const prevLine = lines[i - 1]?.trim() || ''

    // Check if surrounded by empty lines or follows a page marker
    const afterBlank = prevLine === '' || prevLine.startsWith('[PAGE')
    const beforeBlank = nextLine === '' || nextLine.startsWith('[')

    // Common heading patterns
    const isNumberedSection = /^(\d+\.|\d+\)|\([a-z]\)|[ivxIVX]+\.|[A-Z]\.)\s/.test(trimmed)
    const isCommonHeading = /^(abstract|introduction|background|methods?|methodology|results?|discussion|conclusion|conclusions|references|bibliography|appendix|acknowledgements?|summary|overview|chapter|section|part|preface|foreword|table of contents|list of|index)/i.test(trimmed)
    const isAllCaps = trimmed === trimmed.toUpperCase() && /[A-Z]/.test(trimmed) && trimmed.length > 3

    // Title case detection (most words start with capital)
    const words = trimmed.split(/\s+/).filter(w => w.length > 2)
    const capitalizedWords = words.filter(w => /^[A-Z]/.test(w))
    const isTitleCase = words.length >= 2 && capitalizedWords.length / words.length > 0.6

    // Score the likelihood
    let score = 0
    if (afterBlank) score += 2
    if (beforeBlank) score += 1
    if (isNumberedSection) score += 3
    if (isCommonHeading) score += 4
    if (isAllCaps) score += 3
    if (isTitleCase && trimmed.length < 60) score += 2

    if (score >= 3) {
      potentialHeadings.push({
        type: 'potential_heading',
        lineNumber: i + 1,
        lineIndex: i,
        text: trimmed,
        raw: line,
        score,
        reason: [
          isCommonHeading && 'common heading word',
          isAllCaps && 'ALL CAPS',
          isNumberedSection && 'numbered',
          isTitleCase && 'Title Case',
          afterBlank && 'after blank line'
        ].filter(Boolean).join(', ')
      })
    }
  }

  return { missingLevels, potentialHeadings }
}

/**
 * Apply a fix to the content at a specific line
 */
function applyFix(content, lineIndex, fixType, level = 2) {
  const lines = content.split('\n')
  const line = lines[lineIndex]

  if (fixType === 'add_level') {
    // Add heading level to existing [SECTION]
    lines[lineIndex] = line.replace(
      /\[SECTION\]\s*/,
      `[SECTION] ${'#'.repeat(level)} `
    )
  } else if (fixType === 'make_section') {
    // Convert line to a section
    const trimmed = line.trim()
    const indent = line.match(/^\s*/)[0]
    lines[lineIndex] = `${indent}[SECTION] ${'#'.repeat(level)} ${trimmed}`
  }

  return lines.join('\n')
}

export default function SectionEditor() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useRawText(id)
  const updateRawText = useUpdateRawText()
  const previewSections = usePreviewSections()

  // Editor state
  const [content, setContent] = useState('')
  const [isDirty, setIsDirty] = useState(false)
  const [previewData, setPreviewData] = useState(null)
  const [saveStatus, setSaveStatus] = useState(null) // 'saving', 'saved', 'error'
  const [pdfUrl, setPdfUrl] = useState(null)

  // Structure issues detection
  const [issues, setIssues] = useState({ missingLevels: [], potentialHeadings: [] })
  const [showIssues, setShowIssues] = useState(true)

  // Panel sizing (percentages)
  const [leftPanelWidth, setLeftPanelWidth] = useState(25)
  const [rightPanelWidth, setRightPanelWidth] = useState(30)

  // Refs for resizing and editor
  const containerRef = useRef(null)
  const isResizing = useRef(null)
  const textareaRef = useRef(null)

  // Initialize content when data loads
  useEffect(() => {
    if (data?.content) {
      setContent(data.content)
      setIsDirty(false)

      // Set initial preview
      setPreviewData({
        sections_count: data.sections?.length || 0,
        sections: data.sections || []
      })

      // Build PDF URL if original_path exists
      if (data.original_path) {
        setPdfUrl(`${API_BASE}/reading/${id}/pdf`)
      }
    }
  }, [data, id])

  // Debounced preview update
  useEffect(() => {
    if (!isDirty || !content) return

    const timer = setTimeout(async () => {
      try {
        const result = await previewSections.mutateAsync({
          sourceId: id,
          content: content
        })
        setPreviewData(result)
      } catch (err) {
        console.error('Preview failed:', err)
      }
    }, 500) // 500ms debounce

    return () => clearTimeout(timer)
  }, [content, isDirty, id])

  // Detect structure issues (debounced)
  useEffect(() => {
    if (!content) return

    const timer = setTimeout(() => {
      const detected = detectStructureIssues(content)
      setIssues(detected)
    }, 300)

    return () => clearTimeout(timer)
  }, [content])

  // Handle content changes
  const handleContentChange = useCallback((e) => {
    setContent(e.target.value)
    setIsDirty(true)
    setSaveStatus(null)
  }, [])

  // Jump to a specific line in the editor
  const jumpToLine = useCallback((lineIndex) => {
    if (!textareaRef.current) return

    const lines = content.split('\n')
    let charIndex = 0
    for (let i = 0; i < lineIndex; i++) {
      charIndex += lines[i].length + 1 // +1 for newline
    }

    textareaRef.current.focus()
    textareaRef.current.setSelectionRange(charIndex, charIndex + lines[lineIndex].length)

    // Scroll to make the line visible
    const lineHeight = 24 // approximate
    textareaRef.current.scrollTop = Math.max(0, lineIndex * lineHeight - 100)
  }, [content])

  // Apply a fix to an issue
  const handleQuickFix = useCallback((issue, level = 2) => {
    const fixType = issue.type === 'missing_level' ? 'add_level' : 'make_section'
    const newContent = applyFix(content, issue.lineIndex, fixType, level)
    setContent(newContent)
    setIsDirty(true)
    setSaveStatus(null)
  }, [content])

  // Save changes
  const handleSave = useCallback(async () => {
    if (!isDirty) return

    setSaveStatus('saving')
    try {
      await updateRawText.mutateAsync({
        sourceId: id,
        content: content
      })
      setIsDirty(false)
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus(null), 2000)
    } catch (err) {
      console.error('Save failed:', err)
      setSaveStatus('error')
    }
  }, [id, content, isDirty, updateRawText])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+S to save
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        handleSave()
        return
      }

      // Ctrl+1-6 to set heading level on current line
      if ((e.ctrlKey || e.metaKey) && e.key >= '1' && e.key <= '6') {
        e.preventDefault()
        const level = parseInt(e.key)

        if (!textareaRef.current) return

        const textarea = textareaRef.current
        const cursorPos = textarea.selectionStart
        const lines = content.split('\n')

        // Find which line the cursor is on
        let charCount = 0
        let lineIndex = 0
        for (let i = 0; i < lines.length; i++) {
          if (charCount + lines[i].length >= cursorPos) {
            lineIndex = i
            break
          }
          charCount += lines[i].length + 1
        }

        const line = lines[lineIndex]
        const trimmed = line.trim()

        // Determine what kind of fix to apply
        let newContent
        if (trimmed.startsWith('[SECTION]')) {
          // Already a section - update the level
          if (trimmed.match(/\[SECTION\]\s*#{1,6}/)) {
            // Has a level - replace it
            lines[lineIndex] = line.replace(
              /\[SECTION\]\s*#{1,6}\s*/,
              `[SECTION] ${'#'.repeat(level)} `
            )
          } else {
            // Missing level - add it
            lines[lineIndex] = line.replace(
              /\[SECTION\]\s*/,
              `[SECTION] ${'#'.repeat(level)} `
            )
          }
          newContent = lines.join('\n')
        } else if (trimmed && !trimmed.startsWith('[')) {
          // Regular text - convert to section
          const indent = line.match(/^\s*/)[0]
          lines[lineIndex] = `${indent}[SECTION] ${'#'.repeat(level)} ${trimmed}`
          newContent = lines.join('\n')
        }

        if (newContent) {
          setContent(newContent)
          setIsDirty(true)
          setSaveStatus(null)
        }
        return
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleSave])

  // Panel resize handlers
  const startResize = useCallback((panel) => (e) => {
    e.preventDefault()
    isResizing.current = panel
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', stopResize)
  }, [])

  const handleMouseMove = useCallback((e) => {
    if (!isResizing.current || !containerRef.current) return

    const containerRect = containerRef.current.getBoundingClientRect()
    const containerWidth = containerRect.width
    const mouseX = e.clientX - containerRect.left
    const percentage = (mouseX / containerWidth) * 100

    if (isResizing.current === 'left') {
      // Resize left panel
      const newWidth = Math.min(Math.max(percentage, 15), 50)
      setLeftPanelWidth(newWidth)
    } else if (isResizing.current === 'right') {
      // Resize right panel
      const newWidth = Math.min(Math.max(100 - percentage, 15), 50)
      setRightPanelWidth(newWidth)
    }
  }, [])

  const stopResize = useCallback(() => {
    isResizing.current = null
    document.removeEventListener('mousemove', handleMouseMove)
    document.removeEventListener('mouseup', stopResize)
  }, [handleMouseMove])

  // Calculate center panel width
  const centerPanelWidth = 100 - leftPanelWidth - rightPanelWidth

  if (isLoading) {
    return (
      <div className="min-h-screen bg-base flex items-center justify-center">
        <p className="text-secondary">Loading document...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-base flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">Failed to load document</p>
          <Link to="/" className="text-camel hover:underline">← Back to library</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-base flex flex-col">
      {/* Header */}
      <header className="bg-surface border-b border-subtle px-4 py-3 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-4">
          <Link
            to={`/read/${id}`}
            className="text-muted hover:text-secondary text-sm flex items-center gap-1"
          >
            ← Back to Reader
          </Link>
          <div className="w-px h-5 bg-elevated" />
          <h1 className="font-display text-xl text-primary">{data?.title || 'Section Editor'}</h1>
        </div>

        <div className="flex items-center gap-3">
          {/* Status indicator */}
          {isDirty && (
            <span className="text-xs text-terra">Unsaved changes</span>
          )}
          {saveStatus === 'saving' && (
            <span className="text-xs text-secondary">Saving...</span>
          )}
          {saveStatus === 'saved' && (
            <span className="text-xs text-green-400">Saved!</span>
          )}
          {saveStatus === 'error' && (
            <span className="text-xs text-red-400">Save failed</span>
          )}

          {/* Save button */}
          <button
            onClick={handleSave}
            disabled={!isDirty || saveStatus === 'saving'}
            className={`
              px-4 py-1.5 rounded-md text-sm font-medium transition-all
              ${isDirty
                ? 'bg-gradient-to-r from-camel to-terra text-base hover:shadow-lg hover:shadow-camel/30'
                : 'bg-raised text-muted cursor-not-allowed'
              }
            `}
          >
            Save (Ctrl+S)
          </button>
        </div>
      </header>

      {/* Three-pane layout */}
      <div
        ref={containerRef}
        className="flex-1 flex overflow-hidden"
        style={{ height: 'calc(100vh - 57px)' }}
      >
        {/* Left: PDF Viewer */}
        <div
          className="bg-surface border-r border-subtle flex flex-col overflow-hidden"
          style={{ width: `${leftPanelWidth}%` }}
        >
          <div className="px-3 py-2 border-b border-subtle flex items-center justify-between">
            <span className="label text-camel text-xs">Original PDF</span>
            {data?.original_path && (
              <button
                onClick={async () => {
                  try {
                    await fetch(`${API_BASE}/reading/${id}/open-original`, { method: 'POST' })
                  } catch (err) {
                    console.error('Failed to open PDF:', err)
                  }
                }}
                className="text-xs text-muted hover:text-camel transition-colors"
              >
                Open External
              </button>
            )}
          </div>
          <div className="flex-1 overflow-hidden">
            {pdfUrl ? (
              <iframe
                src={pdfUrl}
                className="w-full h-full border-0"
                title="PDF Preview"
              />
            ) : (
              <div className="flex items-center justify-center h-full text-muted text-sm">
                No PDF available
              </div>
            )}
          </div>
        </div>

        {/* Left resize handle */}
        <div
          onMouseDown={startResize('left')}
          className="w-1 bg-elevated hover:bg-camel/50 cursor-col-resize transition-colors flex-shrink-0"
        />

        {/* Center: Raw Text Editor */}
        <div
          className="flex flex-col overflow-hidden"
          style={{ width: `${centerPanelWidth}%` }}
        >
          <div className="px-3 py-2 border-b border-subtle flex items-center justify-between bg-surface">
            <span className="label text-camel text-xs">Raw Text</span>
            <span className="text-xs text-muted">
              {content.length.toLocaleString()} chars
            </span>
          </div>
          <RawTextEditor
            content={content}
            onChange={handleContentChange}
            textareaRef={textareaRef}
          />
        </div>

        {/* Right resize handle */}
        <div
          onMouseDown={startResize('right')}
          className="w-1 bg-elevated hover:bg-camel/50 cursor-col-resize transition-colors flex-shrink-0"
        />

        {/* Right: Issues + Section Preview */}
        <div
          className="bg-surface border-l border-subtle flex flex-col overflow-hidden"
          style={{ width: `${rightPanelWidth}%` }}
        >
          {/* Issues Panel */}
          <IssuesPanel
            issues={issues}
            showIssues={showIssues}
            onToggle={() => setShowIssues(!showIssues)}
            onJumpTo={jumpToLine}
            onQuickFix={handleQuickFix}
          />

          {/* Section Preview */}
          <div className="flex-1 flex flex-col overflow-hidden border-t border-subtle">
            <div className="px-3 py-2 border-b border-subtle flex items-center justify-between">
              <span className="label text-camel text-xs">Section Preview</span>
              <span className="text-xs text-muted">
                {previewData?.sections_count || 0} sections
              </span>
            </div>
            <SectionPreview
              sections={previewData?.sections || []}
              content={content}
            />
          </div>
        </div>
      </div>
    </div>
  )
}


/**
 * Raw Text Editor with syntax highlighting for [SECTION] markers
 */
function RawTextEditor({ content, onChange, textareaRef }) {
  const highlightRef = useRef(null)

  // Sync scroll between textarea and highlight overlay
  const handleScroll = useCallback(() => {
    if (highlightRef.current && textareaRef.current) {
      highlightRef.current.scrollTop = textareaRef.current.scrollTop
      highlightRef.current.scrollLeft = textareaRef.current.scrollLeft
    }
  }, [])

  // Generate highlighted content
  const highlightedContent = useMemo(() => {
    return highlightSyntax(content)
  }, [content])

  return (
    <div className="flex-1 relative overflow-hidden">
      {/* Syntax highlight overlay (behind textarea) */}
      <pre
        ref={highlightRef}
        className="absolute inset-0 m-0 p-4 overflow-auto pointer-events-none font-mono text-sm leading-relaxed whitespace-pre-wrap break-words"
        style={{
          color: 'transparent',
          background: 'var(--bg-base)',
        }}
        dangerouslySetInnerHTML={{ __html: highlightedContent }}
      />

      {/* Editable textarea (transparent text, visible caret) */}
      <textarea
        ref={textareaRef}
        value={content}
        onChange={onChange}
        onScroll={handleScroll}
        className="absolute inset-0 w-full h-full p-4 font-mono text-sm leading-relaxed resize-none border-0 outline-none bg-transparent"
        style={{
          color: '#a8a8a8',
          caretColor: '#d4a574',
        }}
        spellCheck={false}
      />
    </div>
  )
}


/**
 * Syntax highlighting for extracted text format
 */
function highlightSyntax(text) {
  if (!text) return ''

  // Escape HTML
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Highlight [SECTION] markers with proper formatting (green)
  html = html.replace(
    /(\[SECTION\])\s*(#{1,6})\s*([^\n]+)/g,
    '<span style="color: #4ade80;">$1</span> <span style="color: #60a5fa;">$2</span> <span style="color: #fafafa; font-weight: 500;">$3</span>'
  )

  // Highlight [SECTION] markers WITHOUT # (warning - orange)
  html = html.replace(
    /(\[SECTION\])(?!\s*#)(\s*)([^\n]*)/g,
    '<span style="color: #fb923c; background: rgba(251, 146, 60, 0.1);">$1</span>$2<span style="color: #fb923c;">$3</span>'
  )

  // Highlight [PAGE] markers (muted) - supports both old and new format
  html = html.replace(
    /(\[PAGE\s+(?:pdf=\d+\s+doc=[^\]]*|\d+)\])/g,
    '<span style="color: #585858;">$1</span>'
  )

  // Highlight [FIGURE] markers (purple)
  html = html.replace(
    /(\[FIGURE\])/g,
    '<span style="color: #a78bfa;">$1</span>'
  )

  // Highlight [TABLE] markers (purple)
  html = html.replace(
    /(\[TABLE\])/g,
    '<span style="color: #a78bfa;">$1</span>'
  )

  // Highlight [CAPTION] markers (purple)
  html = html.replace(
    /(\[CAPTION\])/g,
    '<span style="color: #a78bfa;">$1</span>'
  )

  // Highlight [TITLE] markers (yellow)
  html = html.replace(
    /(\[TITLE\])/g,
    '<span style="color: #facc15;">$1</span>'
  )

  // Highlight [FOOTNOTE] markers (muted purple)
  html = html.replace(
    /(\[FOOTNOTE\])/g,
    '<span style="color: #8b5cf6;">$1</span>'
  )

  return html
}


/**
 * Section Preview - shows parsed section structure
 */
function SectionPreview({ sections, content }) {
  return (
    <div className="flex-1 overflow-auto p-4">
      {sections.length === 0 ? (
        <p className="text-muted text-sm text-center py-8">
          No sections found. Add [SECTION] ## markers to create sections.
        </p>
      ) : (
        <div className="space-y-2">
          {sections.map((section, i) => (
            <SectionPreviewItem
              key={i}
              section={section}
              index={i}
              content={content}
            />
          ))}
        </div>
      )}

      {/* Quick reference */}
      <div className="mt-8 p-3 bg-raised rounded-lg border border-elevated">
        <p className="label text-camel text-xs mb-2">Format Reference</p>
        <div className="space-y-1 text-xs font-mono">
          <p className="text-yellow-400">[TITLE] Document Title</p>
          <p className="text-green-400">[SECTION] ## Heading Level 2</p>
          <p className="text-green-400">[SECTION] ### Heading Level 3</p>
          <p className="text-muted">[PAGE pdf=42 doc=167]</p>
          <p className="text-purple-400">[FIGURE]</p>
          <p className="text-purple-400">[CAPTION] Figure description</p>
          <p className="text-purple-400">[TABLE]</p>
          <p className="text-violet-400">[FOOTNOTE] Footnote text</p>
        </div>
      </div>
    </div>
  )
}


/**
 * Individual section preview item
 */
function SectionPreviewItem({ section, index, content }) {
  // Extract a snippet of text after the section header
  const snippetLength = 100
  const startPos = section.start_offset || 0
  const endPos = section.end_offset || content.length

  // Get text after the header line
  const sectionText = content.slice(startPos, endPos)
  const lines = sectionText.split('\n')
  const textAfterHeader = lines.slice(1).join(' ').trim().slice(0, snippetLength)

  return (
    <div
      className={`
        p-2 rounded border transition-colors
        ${section.level === 1 ? 'bg-raised border-camel/30' : 'bg-base border-elevated'}
      `}
      style={{ marginLeft: `${(section.level - 1) * 12}px` }}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted font-mono">
          {'#'.repeat(section.level)}
        </span>
        <span className={`
          text-sm
          ${section.level === 1 ? 'font-medium text-primary' : 'text-secondary'}
        `}>
          {section.title}
        </span>
      </div>
      {textAfterHeader && (
        <p className="text-xs text-muted mt-1 line-clamp-2">
          {textAfterHeader}...
        </p>
      )}
    </div>
  )
}


/**
 * Issues Panel - shows detected structure issues with quick-fix actions
 */
function IssuesPanel({ issues, showIssues, onToggle, onJumpTo, onQuickFix }) {
  const [ignoredKeys, setIgnoredKeys] = useState(new Set())
  const [showIgnored, setShowIgnored] = useState(false)

  // Create unique keys for issues
  const getIssueKey = (issue) => `${issue.lineNumber}-${issue.text.slice(0, 20)}`

  // Filter active vs ignored issues
  const activeMissingLevels = issues.missingLevels.filter(i => !ignoredKeys.has(getIssueKey(i)))
  const activePotentialHeadings = issues.potentialHeadings.filter(i => !ignoredKeys.has(getIssueKey(i)))
  const ignoredIssues = [
    ...issues.missingLevels.filter(i => ignoredKeys.has(getIssueKey(i))),
    ...issues.potentialHeadings.filter(i => ignoredKeys.has(getIssueKey(i)))
  ]

  const totalActive = activeMissingLevels.length + activePotentialHeadings.length

  const handleIgnore = (issue) => {
    setIgnoredKeys(prev => new Set([...prev, getIssueKey(issue)]))
  }

  const handleRestore = (issue) => {
    setIgnoredKeys(prev => {
      const next = new Set(prev)
      next.delete(getIssueKey(issue))
      return next
    })
  }

  return (
    <div className="flex-shrink-0">
      {/* Header - always visible */}
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 border-b border-subtle flex items-center justify-between hover:bg-raised/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="label text-camel text-xs">Structure Issues</span>
          {totalActive > 0 && (
            <span className={`
              px-1.5 py-0.5 rounded text-[10px] font-medium
              ${activeMissingLevels.length > 0 ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'}
            `}>
              {totalActive}
            </span>
          )}
          {ignoredIssues.length > 0 && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-500/20 text-neutral-400">
              {ignoredIssues.length} ignored
            </span>
          )}
        </div>
        <svg
          className={`w-4 h-4 text-muted transition-transform ${showIssues ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Collapsible content */}
      {showIssues && (
        <div className="max-h-72 overflow-auto">
          {totalActive === 0 && ignoredIssues.length === 0 ? (
            <p className="px-3 py-4 text-xs text-green-400 text-center">
              ✓ No structure issues detected
            </p>
          ) : totalActive === 0 ? (
            <p className="px-3 py-4 text-xs text-muted text-center">
              All issues ignored
            </p>
          ) : (
            <div className="p-2 space-y-1">
              {/* Missing levels - more urgent */}
              {activeMissingLevels.map((issue, i) => (
                <IssueItem
                  key={`missing-${i}`}
                  issue={issue}
                  type="warning"
                  onJumpTo={onJumpTo}
                  onQuickFix={onQuickFix}
                  onIgnore={handleIgnore}
                />
              ))}

              {/* Potential headings - suggestions */}
              {activePotentialHeadings.map((issue, i) => (
                <IssueItem
                  key={`potential-${i}`}
                  issue={issue}
                  type="suggestion"
                  onJumpTo={onJumpTo}
                  onQuickFix={onQuickFix}
                  onIgnore={handleIgnore}
                />
              ))}
            </div>
          )}

          {/* Ignored issues section */}
          {ignoredIssues.length > 0 && (
            <div className="border-t border-subtle">
              <button
                onClick={() => setShowIgnored(!showIgnored)}
                className="w-full px-3 py-1.5 flex items-center justify-between text-[10px] text-muted hover:bg-raised/30"
              >
                <span>{ignoredIssues.length} ignored issue{ignoredIssues.length !== 1 ? 's' : ''}</span>
                <span>{showIgnored ? '▲' : '▼'}</span>
              </button>
              {showIgnored && (
                <div className="p-2 space-y-1 bg-base/30">
                  {ignoredIssues.map((issue, i) => (
                    <div
                      key={`ignored-${i}`}
                      className="p-2 rounded text-xs bg-neutral-500/10 border border-neutral-500/20 flex items-center justify-between gap-2"
                    >
                      <span className="text-muted truncate flex-1">
                        Line {issue.lineNumber}: {issue.text.slice(0, 30)}...
                      </span>
                      <button
                        onClick={() => handleRestore(issue)}
                        className="px-1.5 py-0.5 rounded text-[10px] bg-neutral-500/20 text-neutral-300 hover:bg-neutral-500/30"
                      >
                        Restore
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Keyboard shortcut hint */}
          <div className="px-3 py-2 border-t border-subtle bg-base/50">
            <p className="text-[10px] text-muted">
              <span className="text-secondary">Ctrl+1-6</span> Set heading level on current line
            </p>
          </div>
        </div>
      )}
    </div>
  )
}


/**
 * Individual issue item with quick-fix actions
 */
function IssueItem({ issue, type, onJumpTo, onQuickFix, onIgnore }) {
  const [showLevelPicker, setShowLevelPicker] = useState(false)

  return (
    <div
      className={`
        p-2 rounded text-xs border transition-colors
        ${type === 'warning'
          ? 'bg-orange-500/10 border-orange-500/20 hover:border-orange-500/40'
          : 'bg-blue-500/10 border-blue-500/20 hover:border-blue-500/40'
        }
      `}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          onClick={() => onJumpTo(issue.lineIndex)}
          className="flex-1 text-left hover:underline"
        >
          <span className="text-muted">Line {issue.lineNumber}:</span>{' '}
          <span className={type === 'warning' ? 'text-orange-300' : 'text-blue-300'}>
            {issue.text.slice(0, 40)}{issue.text.length > 40 ? '...' : ''}
          </span>
        </button>

        {/* Action buttons */}
        <div className="flex items-center gap-1">
          {/* Ignore button */}
          <button
            onClick={() => onIgnore(issue)}
            className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-500/20 text-neutral-400 hover:bg-neutral-500/30 transition-colors"
            title="Ignore this issue"
          >
            Ignore
          </button>

          {/* Quick fix button */}
          <div className="relative">
            <button
              onClick={() => setShowLevelPicker(!showLevelPicker)}
              className={`
                px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors
                ${type === 'warning'
                  ? 'bg-orange-500/20 text-orange-300 hover:bg-orange-500/30'
                  : 'bg-blue-500/20 text-blue-300 hover:bg-blue-500/30'
                }
              `}
            >
              Fix
            </button>

            {/* Level picker dropdown */}
            {showLevelPicker && (
              <div className="absolute right-0 top-full mt-1 bg-elevated border border-subtle rounded shadow-lg z-10">
                <div className="p-1 flex gap-0.5">
                  {[1, 2, 3, 4, 5, 6].map(level => (
                    <button
                      key={level}
                      onClick={() => {
                        onQuickFix(issue, level)
                        setShowLevelPicker(false)
                      }}
                      className="w-6 h-6 rounded text-xs font-mono hover:bg-camel/20 hover:text-camel transition-colors"
                      title={`Heading level ${level}`}
                    >
                      {level}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Reason for suggestion */}
      {issue.reason && (
        <p className="text-muted mt-1 text-[10px]">
          Detected: {issue.reason}
        </p>
      )}
    </div>
  )
}
