import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useRawText, useUpdateRawText, usePreviewSections, useRevertRawText } from '../../hooks/useApi'
import { API_BASE } from '../../config'
import CodeMirror from '@uiw/react-codemirror'
import { EditorView, ViewPlugin, Decoration, keymap } from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'

// ─── CodeMirror 6: Theme ────────────────────────────────────────────────────

const scholiaEditorTheme = EditorView.theme({
  '&': {
    backgroundColor: '#0c0f0d',
    color: '#a8a8a8',
    height: '100%',
  },
  '.cm-content': {
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
    fontSize: '14px',
    lineHeight: '1.625',
    padding: '16px',
    caretColor: '#d4a574',
  },
  '&.cm-focused .cm-cursor': {
    borderLeftColor: '#d4a574',
    borderLeftWidth: '2px',
  },
  '.cm-gutters': {
    backgroundColor: '#1a1d1b',
    color: '#585858',
    borderRight: '1px solid #323832',
  },
  '.cm-activeLineGutter': {
    backgroundColor: '#252a27',
  },
  '.cm-activeLine': {
    backgroundColor: 'rgba(212, 165, 116, 0.05)',
  },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
    backgroundColor: 'rgba(212, 165, 116, 0.15) !important',
  },
  '.cm-scroller': {
    overflow: 'auto',
  },
  // Marker highlight styles
  '.cm-marker-section': { color: '#4ade80' },
  '.cm-marker-level': { color: '#60a5fa' },
  '.cm-marker-title': { color: '#fafafa', fontWeight: '500' },
  '.cm-marker-section-warn': { color: '#fb923c', backgroundColor: 'rgba(251, 146, 60, 0.1)' },
  '.cm-marker-title-warn': { color: '#fb923c' },
  '.cm-marker-page': { color: '#585858' },
  '.cm-marker-figure': { color: '#a78bfa' },
  '.cm-marker-doc-title': { color: '#facc15' },
  '.cm-marker-footnote': { color: '#8b5cf6' },
}, { dark: true })

// ─── CodeMirror 6: Syntax Decorations ───────────────────────────────────────

const markerDeco = {
  section: Decoration.mark({ class: 'cm-marker-section' }),
  level: Decoration.mark({ class: 'cm-marker-level' }),
  title: Decoration.mark({ class: 'cm-marker-title' }),
  sectionWarn: Decoration.mark({ class: 'cm-marker-section-warn' }),
  titleWarn: Decoration.mark({ class: 'cm-marker-title-warn' }),
  page: Decoration.mark({ class: 'cm-marker-page' }),
  figure: Decoration.mark({ class: 'cm-marker-figure' }),
  docTitle: Decoration.mark({ class: 'cm-marker-doc-title' }),
  footnote: Decoration.mark({ class: 'cm-marker-footnote' }),
}

function buildMarkerDecorations(view) {
  const builder = new RangeSetBuilder()

  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to;) {
      const line = view.state.doc.lineAt(pos)
      const text = line.text
      const lf = line.from

      // [SECTION] ## Title (proper section with heading level)
      const sectionMatch = text.match(/^(\s*)(\[SECTION\])(\s*)(#{1,6})(\s+)(.*)$/)
      if (sectionMatch) {
        const [, indent, marker, sp1, hashes, sp2, title] = sectionMatch
        let o = lf + indent.length
        builder.add(o, o + marker.length, markerDeco.section)
        o += marker.length + sp1.length
        builder.add(o, o + hashes.length, markerDeco.level)
        o += hashes.length + sp2.length
        if (title) builder.add(o, o + title.length, markerDeco.title)
        pos = line.to + 1
        continue
      }

      // [SECTION] without # heading level (warning highlight)
      if (/^\s*\[SECTION\]/.test(text) && !/\[SECTION\]\s*#{1,6}/.test(text)) {
        const markerIdx = text.indexOf('[SECTION]')
        builder.add(lf + markerIdx, lf + markerIdx + 9, markerDeco.sectionWarn)
        const rest = text.slice(markerIdx + 9).trimStart()
        if (rest) {
          const restStart = text.indexOf(rest, markerIdx + 9)
          builder.add(lf + restStart, lf + restStart + rest.length, markerDeco.titleWarn)
        }
        pos = line.to + 1
        continue
      }

      // [PAGE ...] markers
      const pageMatch = text.match(/\[PAGE\s+(?:pdf=\d+\s+doc=[^\]]*|\d+)\]/)
      if (pageMatch) {
        const idx = text.indexOf(pageMatch[0])
        builder.add(lf + idx, lf + idx + pageMatch[0].length, markerDeco.page)
        pos = line.to + 1
        continue
      }

      // Single-tag markers
      const tagPatterns = [
        { tag: '[FIGURE]', d: markerDeco.figure },
        { tag: '[TABLE]', d: markerDeco.figure },
        { tag: '[CAPTION]', d: markerDeco.figure },
        { tag: '[TITLE]', d: markerDeco.docTitle },
        { tag: '[FOOTNOTE]', d: markerDeco.footnote },
      ]
      for (const { tag, d } of tagPatterns) {
        const idx = text.indexOf(tag)
        if (idx !== -1) {
          builder.add(lf + idx, lf + idx + tag.length, d)
          break
        }
      }

      pos = line.to + 1
    }
  }

  return builder.finish()
}

const markerHighlighter = ViewPlugin.fromClass(class {
  constructor(view) {
    this.decorations = buildMarkerDecorations(view)
  }
  update(update) {
    if (update.docChanged || update.viewportChanged) {
      this.decorations = buildMarkerDecorations(update.view)
    }
  }
}, {
  decorations: v => v.decorations,
})

// ─── CodeMirror 6: Heading Keymap (Ctrl+1-6) ───────────────────────────────

function headingKeymapExtension() {
  return keymap.of([1, 2, 3, 4, 5, 6].map(level => ({
    key: `Ctrl-${level}`,
    run: (view) => {
      const pos = view.state.selection.main.head
      const line = view.state.doc.lineAt(pos)
      const text = line.text
      const trimmed = text.trim()

      let newText
      if (trimmed.startsWith('[SECTION]')) {
        if (/\[SECTION\]\s*#{1,6}/.test(trimmed)) {
          newText = text.replace(/\[SECTION\]\s*#{1,6}\s*/, `[SECTION] ${'#'.repeat(level)} `)
        } else {
          newText = text.replace(/\[SECTION\]\s*/, `[SECTION] ${'#'.repeat(level)} `)
        }
      } else if (trimmed && !trimmed.startsWith('[')) {
        const indent = text.match(/^\s*/)[0]
        newText = `${indent}[SECTION] ${'#'.repeat(level)} ${trimmed}`
      }

      if (newText !== undefined) {
        view.dispatch({
          changes: { from: line.from, to: line.to, insert: newText },
        })
      }
      return true
    },
  })))
}

// ─── Helpers ────────────────────────────────────────────────────────────────

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
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useRawText(id)
  const updateRawText = useUpdateRawText()
  const revertRawText = useRevertRawText()
  const previewSections = usePreviewSections()

  // Editor state
  const [content, setContent] = useState('')
  const [isDirty, setIsDirty] = useState(false)
  const [previewData, setPreviewData] = useState(null)
  const [saveStatus, setSaveStatus] = useState(null) // 'saving', 'saved', 'error'
  const [pdfUrl, setPdfUrl] = useState(null)

  // PDF page sync
  const [currentPdfPage, setCurrentPdfPage] = useState(null)

  // Structure issues detection
  const [issues, setIssues] = useState({ missingLevels: [], potentialHeadings: [] })
  const [showIssues, setShowIssues] = useState(true)

  // Panel sizing (percentages)
  const [leftPanelWidth, setLeftPanelWidth] = useState(25)
  const [rightPanelWidth, setRightPanelWidth] = useState(30)

  // Refs for resizing and editor
  const containerRef = useRef(null)
  const isResizing = useRef(null)
  const editorViewRef = useRef(null)
  const iframeRef = useRef(null)

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

  // Handle content changes (CM6 onChange gives plain string, not event)
  const handleContentChange = useCallback((value) => {
    setContent(value)
    setIsDirty(true)
    setSaveStatus(null)
  }, [])

  // Jump to a specific line in the editor (via CM6 dispatch)
  const jumpToLine = useCallback((lineIndex) => {
    const view = editorViewRef.current
    if (!view) return

    const lineNum = lineIndex + 1 // CM6 lines are 1-indexed
    if (lineNum < 1 || lineNum > view.state.doc.lines) return

    const line = view.state.doc.line(lineNum)
    view.dispatch({
      selection: { anchor: line.from, head: line.to },
      effects: EditorView.scrollIntoView(line.from, { y: 'center' }),
    })
    view.focus()
  }, [])

  // Jump to a specific character offset (via CM6 dispatch + centered scroll).
  // Double-dispatch: CM6 virtual rendering estimates heights for off-screen lines.
  // First scroll gets close, triggering actual render of that region.
  // Second scroll (after layout) lands precisely.
  const jumpToOffset = useCallback((charOffset) => {
    const view = editorViewRef.current
    if (!view) return

    const safeOffset = Math.min(charOffset, view.state.doc.length)
    view.dispatch({
      selection: { anchor: safeOffset },
      effects: EditorView.scrollIntoView(safeOffset, { y: 'center' }),
    })
    // Re-scroll after CM6 has rendered the target region and measured real heights
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        view.dispatch({
          effects: EditorView.scrollIntoView(safeOffset, { y: 'center' }),
        })
        view.focus()
      })
    })
  }, [])

  // ─── PDF page sync: parse [PAGE pdf=N] markers → offset-to-page map ────────
  const pageMap = useMemo(() => {
    if (!content) return []
    const markers = []
    const regex = /\[PAGE\s+pdf=(\d+)(?:\s+doc=[^\]]*)?\]/g
    let match
    while ((match = regex.exec(content)) !== null) {
      markers.push({ offset: match.index, pdfPage: parseInt(match[1], 10) })
    }
    return markers
  }, [content])

  // Cursor position → current PDF page lookup
  const handleCursorActivity = useCallback((pos) => {
    if (pageMap.length === 0) return
    let page = null
    for (let i = pageMap.length - 1; i >= 0; i--) {
      if (pageMap[i].offset <= pos) {
        page = pageMap[i].pdfPage
        break
      }
    }
    if (page !== null) {
      setCurrentPdfPage(prev => prev === page ? prev : page)
    }
  }, [pageMap])

  // Navigate PDF iframe to current page (click-to-sync, avoids constant reloads)
  const syncPdfToPage = useCallback(() => {
    if (!iframeRef.current || !pdfUrl || !currentPdfPage) return
    iframeRef.current.src = `${pdfUrl}#page=${currentPdfPage}`
  }, [pdfUrl, currentPdfPage])

  // Auto-jump to offset from URL param (e.g. /edit/:id?offset=1234)
  const hasJumped = useRef(false)
  useEffect(() => {
    const offsetParam = searchParams.get('offset')
    if (!offsetParam || !content || !editorViewRef.current || hasJumped.current) return

    const offset = parseInt(offsetParam, 10)
    if (isNaN(offset)) return

    hasJumped.current = true
    // Delay to ensure CM6 has processed the document and initial layout
    const timer = setTimeout(() => jumpToOffset(offset), 400)
    return () => clearTimeout(timer)
  }, [content, searchParams, jumpToOffset])

  // Apply a fix to an issue (via CM6 dispatch for proper undo support)
  const handleQuickFix = useCallback((issue, level = 2) => {
    const view = editorViewRef.current
    if (!view) return

    const lineNum = issue.lineNumber // 1-indexed, matches CM6
    if (lineNum < 1 || lineNum > view.state.doc.lines) return

    const line = view.state.doc.line(lineNum)
    const text = line.text
    const trimmed = text.trim()

    let newText
    if (issue.type === 'missing_level') {
      newText = text.replace(/\[SECTION\]\s*/, `[SECTION] ${'#'.repeat(level)} `)
    } else {
      const indent = text.match(/^\s*/)[0]
      newText = `${indent}[SECTION] ${'#'.repeat(level)} ${trimmed}`
    }

    if (newText !== undefined) {
      view.dispatch({
        changes: { from: line.from, to: line.to, insert: newText },
      })
    }
  }, [])

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

  // Revert to last saved version (undo last save)
  const handleRevert = useCallback(async () => {
    if (!window.confirm('Revert to the previous saved version? This cannot be undone.')) return

    setSaveStatus('saving')
    try {
      const result = await revertRawText.mutateAsync(id)
      // Refetch to get restored content
      const refreshed = await refetch()
      if (refreshed.data?.content) {
        setContent(refreshed.data.content)
        setIsDirty(false)
      }
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus(null), 2000)
    } catch (err) {
      console.error('Revert failed:', err)
      setSaveStatus('error')
    }
  }, [id, revertRawText, refetch])

  // Keyboard shortcuts (Ctrl+1-6 handled by CM6 keymap extension)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault()
        handleSave()
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

          {/* Revert button */}
          <button
            onClick={handleRevert}
            disabled={saveStatus === 'saving'}
            className="px-3 py-1.5 rounded-md text-sm font-medium bg-raised text-secondary hover:text-primary hover:bg-elevated border border-elevated transition-all"
            title="Revert to previous saved version"
          >
            Revert
          </button>

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
            <div className="flex items-center gap-2">
              <span className="label text-camel text-xs">Original PDF</span>
              {currentPdfPage && (
                <button
                  onClick={syncPdfToPage}
                  className="text-xs text-muted hover:text-camel transition-colors px-1.5 py-0.5 rounded bg-base hover:bg-raised border border-elevated"
                  title="Sync PDF to editor cursor position"
                >
                  p.{currentPdfPage} ↗
                </button>
              )}
            </div>
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
                ref={iframeRef}
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
            editorViewRef={editorViewRef}
            onCursorActivity={handleCursorActivity}
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
              onJumpTo={jumpToOffset}
            />
          </div>
        </div>
      </div>
    </div>
  )
}


/**
 * Raw Text Editor — CodeMirror 6
 *
 * Replaces the previous textarea+pre overlay with CM6 for:
 * - Reliable scroll-to-offset (via dispatch + scrollIntoView)
 * - Virtual rendering (only visible lines in DOM)
 * - Native syntax highlighting via decorations
 * - Built-in undo/redo history
 */
function RawTextEditor({ content, onChange, editorViewRef, onCursorActivity }) {
  const extensions = useMemo(() => [
    markerHighlighter,
    headingKeymapExtension(),
    EditorView.lineWrapping,
    EditorView.contentAttributes.of({ spellcheck: 'false' }),
  ], [])

  const handleUpdate = useCallback((viewUpdate) => {
    if (viewUpdate.selectionSet && onCursorActivity) {
      const pos = viewUpdate.state.selection.main.head
      onCursorActivity(pos)
    }
  }, [onCursorActivity])

  return (
    <div className="flex-1 overflow-hidden">
      <CodeMirror
        value={content}
        onChange={onChange}
        theme={scholiaEditorTheme}
        extensions={extensions}
        basicSetup={{
          lineNumbers: true,
          highlightActiveLineGutter: true,
          highlightActiveLine: true,
          foldGutter: false,
          bracketMatching: false,
          closeBrackets: false,
          autocompletion: false,
          highlightSelectionMatches: true,
          indentOnInput: false,
        }}
        onCreateEditor={(view) => {
          if (editorViewRef) editorViewRef.current = view
        }}
        onUpdate={handleUpdate}
        style={{ height: '100%' }}
      />
    </div>
  )
}


/**
 * Section Preview - shows parsed section structure
 */
function SectionPreview({ sections, content, onJumpTo }) {
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
              onJumpTo={onJumpTo}
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
function SectionPreviewItem({ section, index, content, onJumpTo }) {
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
        p-2 rounded border transition-colors cursor-pointer
        hover:border-camel/50 hover:bg-surface
        ${section.level === 1 ? 'bg-raised border-camel/30' : 'bg-base border-elevated'}
      `}
      style={{ marginLeft: `${(section.level - 1) * 12}px` }}
      onClick={() => onJumpTo?.(startPos)}
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
