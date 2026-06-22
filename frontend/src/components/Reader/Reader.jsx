import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useResizable, ResizeHandle } from '../../hooks/useResizable'
import useDeviceLayout from '../../hooks/useDeviceLayout'
import Drawer from '../common/Drawer'
import {
  useSourceContent,
  useMeshbookFacet,
  useHighlights,
  useCreateHighlight,
  useDeleteHighlight,
  useSourceNotes,
  useCreateNote,
  useUpdateNote,
  useDeleteNote,
  useBacklinks,
  useUpdateReadingPosition
} from '../../hooks/useApi'
import useReaderStore from '../../stores/useReaderStore'
import MetadataEditModal from '../common/MetadataEditModal'
import SimpleChatTab from './SimpleChatTab'
import { API_BASE } from '../../config'
import AutocompleteTextarea from '../common/AutocompleteTextarea'
import YouTubePlayer from './YouTubePlayer'
import ReadingContent from './ReadingContent'
import { HIGHLIGHT_COLORS, DEFAULT_HIGHLIGHT_COLOR, cleanSectionTitle, CopyIcon } from './readerUtils'

// Hand-drawn squiggle underline element for Reader title
function SquiggleSVG({ className = "" }) {
  return (
    <svg
      className={className}
      width="80"
      height="12"
      viewBox="0 0 80 12"
      fill="none"
      style={{ opacity: 0.4 }}
    >
      <path
        d="M2 6 Q 10 2, 18 6 T 34 6 T 50 6 T 66 6 T 78 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  )
}

/**
 * Font size slider for reader content
 */
function FontSizeSlider() {
  const { fontSize, setFontSize } = useReaderStore()

  return (
    <div className="flex items-center gap-2 text-muted">
      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
      </svg>
      <input
        type="range"
        min="12"
        max="24"
        value={fontSize}
        onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
        className="w-20 h-1 bg-subtle rounded-lg appearance-none cursor-pointer accent-camel"
        title={`Font size: ${fontSize}px`}
      />
      <span className="text-xs w-6">{fontSize}</span>
    </div>
  )
}

/**
 * Reader View
 * ===========
 * Three-pane layout for reading documents:
 * - Left: Table of Contents
 * - Center: Reading content with highlights
 * - Right: Highlights list
 *
 * IMPORTANT: Highlights use character OFFSETS, not text matching.
 * This avoids performance issues and crashes with large documents.
 */

export default function Reader() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const initialConversationId = searchParams.get('conversation') || null

  const { data, isLoading, error } = useSourceContent(id)
  const { data: highlights = [], refetch: refetchHighlights } = useHighlights(id)
  const createHighlight = useCreateHighlight()
  const deleteHighlight = useDeleteHighlight()
  const updateReadingPosition = useUpdateReadingPosition()

  const contentRef = useRef(null)
  const [figures, setFigures] = useState([])
  const [selection, setSelection] = useState(null)
  const [popupPosition, setPopupPosition] = useState(null)
  const [positionRestored, setPositionRestored] = useState(false)
  const [isChatExpanded, setIsChatExpanded] = useState(false)
  const saveTimeoutRef = useRef(null)
  const scrollSpyRef = useRef(false) // true when scroll spy triggered the section change
  const scrollAnchorRef = useRef(null) // pins reading position across tablet sidebar width changes

  // Mobile layout
  const layout = useDeviceLayout()
  const [tocDrawerOpen, setTocDrawerOpen] = useState(false)
  const [sidebarDrawerOpen, setSidebarDrawerOpen] = useState(false)

  // Tablet sidebar visibility (persisted)
  const [tabletSidebarVisible, setTabletSidebarVisible] = useState(() => {
    try {
      const stored = localStorage.getItem('scholia-tablet-sidebar')
      return stored ? JSON.parse(stored) : false
    } catch (e) {
      return false
    }
  })

  // Persist tablet sidebar preference
  useEffect(() => {
    try {
      localStorage.setItem('scholia-tablet-sidebar', JSON.stringify(tabletSidebarVisible))
    } catch (e) {}
  }, [tabletSidebarVisible])

  // Resizable pane widths
  const { tocWidth, sidebarWidth, handleTocResize, handleSidebarResize, isResizing } = useResizable()

  const {
    setDocument,
    setSections,
    setContent,
    currentSectionId,
    setCurrentSection,
    setTranscriptCues,
    reset
  } = useReaderStore()

  // Load document data into store
  useEffect(() => {
    if (data) {
      setDocument({
        id: data.id,
        title: data.title,
        author: data.author,
        year: data.year,
        original_path: data.original_path
      })
      setSections(data.sections || [])
      setContent(data.content || '')

      // Store transcript cues for video sync (if media source with cues)
      if (data.transcript_cues?.length) {
        setTranscriptCues(data.transcript_cues)
      }

      // Restore reading position if available, otherwise go to first section
      if (data.reading_position?.section_id) {
        setCurrentSection(data.reading_position.section_id)
        // Defer scroll restoration to after render
        setTimeout(() => {
          if (contentRef.current && data.reading_position.scroll_offset) {
            contentRef.current.scrollTop = data.reading_position.scroll_offset
          }
          setPositionRestored(true)
        }, 100)
      } else if (data.sections?.length > 0 && !currentSectionId) {
        setCurrentSection(data.sections[0].id)
        setPositionRestored(true)
      } else {
        setPositionRestored(true)
      }
    }
    return () => {
      reset()
      setPositionRestored(false)
    }
  }, [data])

  // Fetch figures metadata
  useEffect(() => {
    if (id) {
      fetch(`${API_BASE}/reading/${id}/figures`)
        .then(res => res.json())
        .then(data => setFigures(data.figures || []))
        .catch(() => setFigures([]))
    }
  }, [id])

  // Scroll to section when selected via ToC click (skip scroll-spy and initial restore)
  useEffect(() => {
    if (scrollSpyRef.current) {
      scrollSpyRef.current = false
      return
    }
    if (currentSectionId && positionRestored) {
      const element = document.getElementById(`section-${currentSectionId}`)
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }, [currentSectionId])

  // Save reading position on scroll (debounced)
  useEffect(() => {
    if (!positionRestored || !contentRef.current || !id) return

    const handleScroll = () => {
      // Clear any pending save
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }

      // Debounce: save after 500ms of no scrolling
      saveTimeoutRef.current = setTimeout(() => {
        const scrollOffset = contentRef.current?.scrollTop || 0
        updateReadingPosition.mutate({
          sourceId: id,
          position: {
            section_id: currentSectionId,
            scroll_offset: scrollOffset
          }
        })
      }, 500)
    }

    const container = contentRef.current
    container.addEventListener('scroll', handleScroll)

    return () => {
      container.removeEventListener('scroll', handleScroll)
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }
    }
  }, [positionRestored, id, currentSectionId, updateReadingPosition])

  // Scroll spy: update active ToC section as user reads
  useEffect(() => {
    if (!positionRestored || !contentRef.current || !data?.sections?.length) return

    const container = contentRef.current
    let ticking = false

    const updateActiveSection = () => {
      ticking = false
      const containerRect = container.getBoundingClientRect()
      const offset = 120 // pixels from top — section header considered "active" once past this line

      let activeId = null
      for (const section of data.sections) {
        const el = document.getElementById(`section-${section.id}`)
        if (!el) continue
        const top = el.getBoundingClientRect().top - containerRect.top
        if (top <= offset) {
          activeId = section.id
        }
      }

      if (activeId && activeId !== useReaderStore.getState().currentSectionId) {
        scrollSpyRef.current = true
        setCurrentSection(activeId)
      }
    }

    const handleScrollSpy = () => {
      if (!ticking) {
        requestAnimationFrame(updateActiveSection)
        ticking = true
      }
    }

    container.addEventListener('scroll', handleScrollSpy, { passive: true })
    return () => container.removeEventListener('scroll', handleScrollSpy)
  }, [positionRestored, data?.sections, setCurrentSection])

  /**
   * Handle text selection - extract OFFSETS from data attributes
   * This is the key to avoiding text-matching performance issues
   */
  const handleMouseUp = useCallback(() => {
    const sel = window.getSelection()
    if (!sel || sel.isCollapsed) {
      setSelection(null)
      setPopupPosition(null)
      return
    }

    const selectedText = sel.toString().trim()
    if (selectedText.length < 3) {
      setSelection(null)
      setPopupPosition(null)
      return
    }

    // Get selection range
    const range = sel.getRangeAt(0)

    // Find the start and end offsets from our data-offset attributes
    const startOffset = getOffsetFromNode(range.startContainer, range.startOffset)
    const endOffset = getOffsetFromNode(range.endContainer, range.endOffset)

    if (startOffset === null || endOffset === null) {
      console.log('Could not determine offsets from selection')
      setSelection(null)
      setPopupPosition(null)
      return
    }

    // Get position for popup
    const rect = range.getBoundingClientRect()

    setSelection({
      text: selectedText,
      startOffset: Math.min(startOffset, endOffset),
      endOffset: Math.max(startOffset, endOffset)
    })

    setPopupPosition({
      top: rect.bottom + 8,
      left: rect.left + rect.width / 2
    })
  }, [])

  /**
   * Handle touch selection — 100ms delay to let browser finalize selection.
   * Clamps popup position to viewport bounds for mobile.
   */
  const handleTouchEnd = useCallback(() => {
    setTimeout(() => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed) return

      const selectedText = sel.toString().trim()
      if (selectedText.length < 3) return

      const range = sel.getRangeAt(0)
      const startOffset = getOffsetFromNode(range.startContainer, range.startOffset)
      const endOffset = getOffsetFromNode(range.endContainer, range.endOffset)

      if (startOffset === null || endOffset === null) return

      const rect = range.getBoundingClientRect()
      const vw = window.innerWidth

      setSelection({
        text: selectedText,
        startOffset: Math.min(startOffset, endOffset),
        endOffset: Math.max(startOffset, endOffset)
      })

      // Position above selection on mobile so it doesn't get clipped by keyboard/bottom
      const popupHeight = 48
      const above = rect.top - popupHeight - 8
      const below = rect.bottom + 8

      setPopupPosition({
        top: above > 10 ? above : Math.min(below, window.innerHeight - 60),
        left: Math.max(30, Math.min(rect.left + rect.width / 2, vw - 30))
      })
    }, 100)
  }, [])

  /**
   * Get character offset from a DOM node and text offset
   * Walks up to find the nearest element with data-offset
   */
  function getOffsetFromNode(node, textOffset) {
    // Walk up to find element with data-offset
    let current = node
    while (current && current !== contentRef.current) {
      if (current.nodeType === Node.ELEMENT_NODE) {
        const offset = current.getAttribute?.('data-offset')
        if (offset !== null && offset !== undefined) {
          // Found an element with offset data
          // Calculate actual offset by adding text position within this element
          const baseOffset = parseInt(offset, 10)

          // Count characters before our position within this element
          const charsBeforeInElement = countCharsBeforeNode(current, node, textOffset)
          return baseOffset + charsBeforeInElement
        }
      }
      current = current.parentNode
    }
    return null
  }

  /**
   * Count characters before a given node/offset within a parent element
   */
  function countCharsBeforeNode(parent, targetNode, targetOffset) {
    let count = 0
    const walker = document.createTreeWalker(parent, NodeFilter.SHOW_TEXT, null, false)

    let node
    while ((node = walker.nextNode())) {
      if (node === targetNode) {
        return count + targetOffset
      }
      count += node.textContent.length
    }
    return count + targetOffset
  }

  // Handle creating highlight
  const handleCreateHighlight = async (color) => {
    if (!selection) return

    try {
      await createHighlight.mutateAsync({
        source_id: id,
        start_offset: selection.startOffset,
        end_offset: selection.endOffset,
        color: color,
        content: selection.text
      })

      window.getSelection()?.removeAllRanges()
      setSelection(null)
      setPopupPosition(null)
      refetchHighlights()
    } catch (err) {
      console.error('Failed to create highlight:', err)
      alert('Failed to create highlight: ' + err.message)
    }
  }

  // Handle deleting highlight
  const handleDeleteHighlight = async (highlightId) => {
    try {
      await deleteHighlight.mutateAsync({ id: highlightId, sourceId: id })
      refetchHighlights()
    } catch (err) {
      console.error('Failed to delete highlight:', err)
    }
  }

  // Scroll to highlight in content
  const scrollToHighlight = (highlight) => {
    const element = document.querySelector(`[data-highlight-id="${highlight.id}"]`)
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      element.classList.add('highlight-flash')
      setTimeout(() => element.classList.remove('highlight-flash'), 1000)
    }
  }

  // Record the top-most visible text element so the reading position can be
  // restored after the tablet sidebar toggle reflows the column (it changes
  // the reading pane width, which would otherwise drop you elsewhere).
  const captureScrollAnchor = () => {
    const container = contentRef.current
    if (!container) return null
    const rect = container.getBoundingClientRect()
    const x = rect.left + rect.width / 2
    // Probe a few points below the sticky header until one lands on a tracked span.
    for (const dy of [70, 110, 160, 220, 300]) {
      let el = document.elementFromPoint(x, rect.top + dy)
      while (el && el !== container && el.getAttribute?.('data-offset') == null) {
        el = el.parentElement
      }
      if (el && el !== container && el.getAttribute?.('data-offset') != null) {
        return { el, delta: el.getBoundingClientRect().top - rect.top }
      }
    }
    return null
  }

  // Capture the anchor synchronously (old layout still in DOM) before flipping.
  const setTabletSidebarAnchored = useCallback((next) => {
    scrollAnchorRef.current = captureScrollAnchor()
    setTabletSidebarVisible(next)
  }, [])

  // After the width transition, keep the captured element pinned to its prior
  // screen position. Runs per animation frame for the transition's duration so
  // the restore is smooth rather than a jump at the end.
  useEffect(() => {
    if (layout !== 'tablet') return
    const anchor = scrollAnchorRef.current
    scrollAnchorRef.current = null // mount runs this with a null anchor → no-op
    if (!anchor) return
    const container = contentRef.current
    if (!container) return

    // Cancel any in-flight smooth scroll (e.g. from a "Find" jump) so our
    // per-frame scrollTop writes win deterministically instead of fighting it.
    const prevBehavior = container.style.scrollBehavior
    container.style.scrollBehavior = 'auto'
    container.scrollTo({ top: container.scrollTop })

    let raf
    let cancelled = false
    // A user wheel/touch during the window means they want to read elsewhere —
    // stop pinning. (Our own scrollTop writes fire 'scroll' but not these.)
    const onUserScroll = () => { cancelled = true }
    container.addEventListener('wheel', onUserScroll, { passive: true, once: true })
    container.addEventListener('touchmove', onUserScroll, { passive: true, once: true })

    const finish = () => {
      container.style.scrollBehavior = prevBehavior
      container.removeEventListener('wheel', onUserScroll)
      container.removeEventListener('touchmove', onUserScroll)
    }

    const start = performance.now()
    const DURATION = 340 // slightly longer than the 300ms CSS width transition
    const tick = () => {
      if (cancelled || !anchor.el?.isConnected) { finish(); return }
      const containerTop = container.getBoundingClientRect().top
      const correction = (anchor.el.getBoundingClientRect().top - containerTop) - anchor.delta
      // Skip sub-pixel churn; corrections can legitimately be large (deep in a
      // long doc the column rewrap shifts everything above the anchor).
      if (Number.isFinite(correction) && Math.abs(correction) > 0.5) {
        container.scrollTop += correction
      }
      if (performance.now() - start < DURATION) {
        raf = requestAnimationFrame(tick)
      } else {
        finish()
      }
    }
    raf = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(raf)
      finish()
    }
  }, [tabletSidebarVisible, layout])

  // Close popup when clicking outside (but preserve selection if clicking in sidebar for chat)
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (popupPosition && !e.target.closest('.highlight-popup')) {
        // Close the popup
        setPopupPosition(null)
        // Only clear selection if clicking in the main content area, not the sidebar
        if (!e.target.closest('aside')) {
          setSelection(null)
        }
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [popupPosition])

  // Suppress native context menu in reading pane on mobile/tablet
  // so the Scholia highlight popup is the only selection UI
  useEffect(() => {
    if (layout === 'desktop' || !contentRef.current) return

    const suppress = (e) => {
      // Only suppress when there's a text selection (let normal taps through)
      const sel = window.getSelection()
      if (sel && !sel.isCollapsed) {
        e.preventDefault()
      }
    }

    const el = contentRef.current
    el.addEventListener('contextmenu', suppress)
    return () => el.removeEventListener('contextmenu', suppress)
  }, [layout])

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

  // -- Shared sub-elements used by all layouts --

  // Desktop: floating popup near selection
  const highlightPopup = popupPosition && selection && (
    <div
      className="highlight-popup fixed z-50 bg-surface border border-subtle rounded-lg shadow-2xl p-1.5 flex items-center gap-1"
      style={{
        top: popupPosition.top,
        left: popupPosition.left,
        transform: 'translateX(-50%)',
        boxShadow: '0 4px 20px rgba(0,0,0,0.5)'
      }}
    >
      <button
        onClick={() => handleCreateHighlight(DEFAULT_HIGHLIGHT_COLOR)}
        className="px-3 py-1.5 rounded-md text-xs font-medium bg-raised hover:bg-elevated text-secondary hover:text-primary transition-all border border-transparent hover:border-camel/30"
        title="Quick highlight (Yellow)"
      >
        Highlight
      </button>
      <div className="w-px h-6 bg-raised mx-0.5" />
      {Object.entries(HIGHLIGHT_COLORS).map(([color, info]) => (
        <button
          key={color}
          onClick={() => handleCreateHighlight(color)}
          className={`w-6 h-6 rounded-full transition-all hover:scale-125 ${color === DEFAULT_HIGHLIGHT_COLOR ? 'ring-2 ring-offset-1 ring-offset-surface ring-camel/50' : ''}`}
          style={{ backgroundColor: info.border }}
          title={`${info.name} - ${info.meaning}`}
        />
      ))}
      <div className="w-px h-6 bg-raised mx-0.5" />
      <button
        onClick={() => {
          navigator.clipboard.writeText(selection.text)
          setSelection(null)
          setPopupPosition(null)
          window.getSelection()?.removeAllRanges()
        }}
        className="w-7 h-7 rounded-md flex items-center justify-center bg-raised hover:bg-elevated text-muted hover:text-primary transition-all"
        title="Copy text"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
      </button>
    </div>
  )

  // Mobile/Tablet: fixed bottom highlight bar that coexists with native selection UI
  const mobileHighlightBar = selection && (
    <div className="highlight-popup fixed bottom-0 left-0 right-0 z-50 bg-surface border-t border-subtle shadow-[0_-4px_20px_rgba(0,0,0,0.5)] safe-area-bottom animate-slide-up">
      {/* Selected text preview */}
      <div className="px-4 pt-3 pb-1">
        <p className="text-xs text-muted truncate">
          "{selection.text.slice(0, 80)}{selection.text.length > 80 ? '...' : ''}"
        </p>
      </div>
      {/* Action buttons */}
      <div className="px-4 pb-3 pt-1 flex items-center gap-3">
        {/* Color circles */}
        {Object.entries(HIGHLIGHT_COLORS).map(([color, info]) => (
          <button
            key={color}
            onClick={() => handleCreateHighlight(color)}
            className={`w-10 h-10 rounded-full transition-all active:scale-90 ${
              color === DEFAULT_HIGHLIGHT_COLOR
                ? 'ring-2 ring-offset-2 ring-offset-surface ring-camel/50'
                : ''
            }`}
            style={{ backgroundColor: info.border }}
            aria-label={`${info.name} - ${info.meaning}`}
          />
        ))}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Copy button */}
        <button
          onClick={() => {
            navigator.clipboard.writeText(selection.text)
            setSelection(null)
            setPopupPosition(null)
            window.getSelection()?.removeAllRanges()
          }}
          className="w-10 h-10 rounded-lg flex items-center justify-center bg-raised text-secondary active:bg-elevated transition-all"
          aria-label="Copy text"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
        </button>

        {/* Dismiss */}
        <button
          onClick={() => {
            setSelection(null)
            setPopupPosition(null)
            window.getSelection()?.removeAllRanges()
          }}
          className="w-10 h-10 rounded-lg flex items-center justify-center bg-raised text-muted active:bg-elevated transition-all"
          aria-label="Dismiss"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )

  const documentBody = (
    <>
      <header className="mb-8 pb-6 border-b border-subtle">
        <h1 className={`font-display text-primary mb-1 ${layout === 'mobile' ? 'text-2xl' : 'text-4xl'}`}>{data?.title}</h1>
        <SquiggleSVG className="mb-2" />
        {data?.author && (
          <p className="text-secondary">
            {data.author}{data.year && ` (${data.year})`}
          </p>
        )}
      </header>

      {data?.source_type === 'media' && data?.video_id && (
        <YouTubePlayer videoId={data.video_id} title={data.title} />
      )}

      <ReadingContent
        content={data?.content || ''}
        sections={data?.sections || []}
        figures={figures}
        highlights={highlights}
        sourceId={id}
        analyses={data?.analyses || []}
      />
    </>
  )

  const sidebarProps = {
    sourceId: id,
    documentData: data,
    highlights,
    onHighlightClick: scrollToHighlight,
    onHighlightDelete: handleDeleteHighlight,
    content: data?.content || '',
    selection,
    isChatExpanded,
    setIsChatExpanded,
    tabletSidebarVisible,
    setTabletSidebarVisible: setTabletSidebarAnchored,
    layout,
    initialConversationId
  }

  const tocProps = {
    sections: data?.sections || [],
    currentSectionId,
    onSectionClick: (sectionId) => {
      setCurrentSection(sectionId)
      if (layout === 'mobile') setTocDrawerOpen(false)
    },
    analyses: data?.analyses || [],
  }

  // =============================================
  // MOBILE LAYOUT: single pane + drawers
  // =============================================
  if (layout === 'mobile') {
    return (
      <div className="h-screen bg-base flex flex-col">
        {/* Compact sticky header with safe area top for notch/status bar */}
        <div className="sticky top-0 z-30 bg-base/95 backdrop-blur-sm border-b border-subtle/50 px-4 py-2 flex items-center justify-between gap-2 safe-area-top">
          {/* Hamburger → ToC drawer */}
          <button
            onClick={() => setTocDrawerOpen(true)}
            className="p-2 text-secondary hover:text-primary transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
            title="Table of Contents"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          {/* Truncated title */}
          <Link to="/" className="flex-1 min-w-0">
            <span className="text-sm text-secondary truncate block">{data?.title}</span>
          </Link>

          {/* Sidebar button → bottom sheet */}
          <button
            onClick={() => setSidebarDrawerOpen(true)}
            className="p-2 text-secondary hover:text-primary transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
            title="Annotations & Chat"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
          </button>
        </div>

        {/* Full-screen content pane */}
        <main
          ref={contentRef}
          className="flex-1 overflow-auto relative"
          onMouseUp={handleMouseUp}
          onTouchEnd={handleTouchEnd}
        >
          <div className="max-w-3xl mx-auto px-4 py-6">
            {documentBody}
          </div>
        </main>

        {/* Bottom highlight bar — coexists with native selection UI */}
        {mobileHighlightBar}

        {/* ToC drawer (left) */}
        <Drawer isOpen={tocDrawerOpen} onClose={() => setTocDrawerOpen(false)} position="left">
          <TocPane {...tocProps} />
        </Drawer>

        {/* Sidebar drawer (bottom sheet) */}
        <Drawer isOpen={sidebarDrawerOpen} onClose={() => setSidebarDrawerOpen(false)} position="bottom">
          <ReaderSidebar {...sidebarProps} />
        </Drawer>
      </div>
    )
  }

  // =============================================
  // TABLET LAYOUT: full-width reading with toggleable sidebar
  // =============================================
  if (layout === 'tablet') {
    return (
      <div className="h-screen bg-base flex">
        {/* Reading pane - full width when sidebar hidden */}
        <main
          ref={contentRef}
          className={`h-full overflow-auto relative transition-all duration-300 ${
            tabletSidebarVisible ? 'flex-[65]' : 'flex-1'
          }`}
          onMouseUp={handleMouseUp}
          onTouchEnd={handleTouchEnd}
        >
          {/* Sticky nav with ToC hamburger and sidebar toggle */}
          <div className="sticky top-0 z-10 bg-base/95 backdrop-blur-sm border-b border-subtle/50">
            <div className={`mx-auto px-6 py-3 flex items-center justify-between transition-all duration-300 ${
              tabletSidebarVisible ? 'max-w-2xl' : 'max-w-4xl'
            }`}>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setTocDrawerOpen(true)}
                  className="p-1.5 text-muted hover:text-secondary transition-colors"
                  title="Table of Contents"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                </button>
                <Link to="/" className="text-muted hover:text-secondary text-sm flex items-center gap-1 transition-colors">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                  Library
                </Link>
              </div>
              <div className="flex items-center gap-4">
                <FontSizeSlider />
                <span className="text-xs text-muted truncate max-w-[200px]">{data?.title}</span>
              </div>
            </div>
          </div>

          {/* Reading content - wider max-width and padding when sidebar hidden */}
          <div className={`mx-auto py-8 transition-all duration-300 ${
            tabletSidebarVisible
              ? 'max-w-2xl px-6'    // Narrower when sidebar visible
              : 'max-w-4xl px-12'   // Wider with generous padding when full-width
          }`}>
            {documentBody}
          </div>
        </main>

        {/* Bottom highlight bar for tablet touch */}
        {mobileHighlightBar}

        {/* Floating toggle button - only visible when sidebar is hidden */}
        {!tabletSidebarVisible && (
          <button
            onClick={() => setTabletSidebarAnchored(true)}
            className="fixed right-4 bottom-20 z-20 p-3 bg-raised border border-subtle rounded-full shadow-lg text-secondary hover:text-primary hover:bg-surface transition-all"
            title="Show annotations & chat"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}

        {/* Sidebar - slide in from right, hidden by default */}
        <div
          className={`h-full border-l border-subtle transition-all duration-300 ${
            tabletSidebarVisible ? 'flex-[35] opacity-100' : 'w-0 opacity-0 overflow-hidden'
          }`}
        >
          {tabletSidebarVisible && <ReaderSidebar {...sidebarProps} />}
        </div>

        {/* ToC drawer (left) */}
        <Drawer isOpen={tocDrawerOpen} onClose={() => setTocDrawerOpen(false)} position="left">
          <TocPane {...tocProps} />
        </Drawer>
      </div>
    )
  }

  // =============================================
  // DESKTOP LAYOUT: unchanged three-pane
  // =============================================
  return (
    <div className={`h-screen bg-base flex ${isResizing ? 'select-none' : ''}`}>
      {/* ToC Pane - always visible */}
      <div style={{ width: tocWidth }} className="flex-shrink-0 h-full">
        <TocPane {...tocProps} />
      </div>

      {/* Resize Handle: ToC ↔ Content - hidden when chat expanded */}
      {!isChatExpanded && (
        <ResizeHandle onMouseDown={handleTocResize} position="right" />
      )}

      {/* Reading Pane - shrinks to ~30% when chat expanded (chat gets ~70%) */}
      <main
        ref={contentRef}
        className={`h-full overflow-auto relative transition-all duration-300 ${
          isChatExpanded ? 'flex-[3] min-w-[200px]' : 'flex-1'
        }`}
        onMouseUp={handleMouseUp}
      >
              {/* Sticky navigation bar */}
              <div className="sticky top-0 z-10 bg-base/95 backdrop-blur-sm border-b border-subtle/50">
                <div className="max-w-3xl mx-auto px-8 py-3 flex items-center justify-between">
                  <Link to="/" className="text-muted hover:text-secondary text-sm flex items-center gap-1 transition-colors">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Library
                  </Link>
                  <div className="flex items-center gap-4">
                    <FontSizeSlider />
                    <span className="text-xs text-muted truncate max-w-xs">{data?.title}</span>
                  </div>
                </div>
              </div>

              <div className="max-w-3xl mx-auto px-8 py-8">
                {documentBody}
              </div>

              {highlightPopup}
        </main>

      {/* Resize Handle: Content ↔ Sidebar - hidden when chat expanded */}
      {!isChatExpanded && (
        <ResizeHandle onMouseDown={handleSidebarResize} position="left" />
      )}

      {/* Sidebar - expands to ~70% when chat expanded */}
      <div
        style={isChatExpanded ? {} : { width: sidebarWidth }}
        className={`h-full ${isChatExpanded ? 'flex-[7]' : 'flex-shrink-0'}`}
      >
        <ReaderSidebar {...sidebarProps} />
      </div>
    </div>
  )
}


/**
 * Reader Sidebar with tabs: Annotations (unified), Chat, Info
 */
function ReaderSidebar({ sourceId, documentData, highlights, onHighlightClick, onHighlightDelete, content, selection, isChatExpanded, setIsChatExpanded, tabletSidebarVisible, setTabletSidebarVisible, layout, initialConversationId }) {
  // Auto-switch to Chat tab when deep linking to a conversation
  const [activeTab, setActiveTab] = useState(initialConversationId ? 'chat' : 'annotations')
  const [copiedAll, setCopiedAll] = useState(false)
  const [showMetadataModal, setShowMetadataModal] = useState(false)

  // Fetch notes for this document
  const { data: notes = [], refetch: refetchNotes } = useSourceNotes(sourceId)
  const createNote = useCreateNote()
  const updateNote = useUpdateNote()
  const deleteNote = useDeleteNote()

  // Copy all document text (cleaned)
  const copyAllText = () => {
    const cleanedText = content
      .replace(/\[SECTION\]\s*#{1,6}\s*/g, '')
      .replace(/\[TITLE\]/g, '')
      .replace(/\[PAGE\s+(?:pdf=\d+\s+doc=[^\]]*|\d+)\]/g, '')
      .replace(/\[FIGURE\]/g, '[Figure]')
      .replace(/\[TABLE\]/g, '[Table]')
      .replace(/\[CAPTION\]/g, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/<sup>(.*?)<\/sup>/g, '$1')
      .replace(/<sub>(.*?)<\/sub>/g, '$1')
      .replace(/<table[^>]*>[\s\S]*?<\/table>/gi, '[Table]')
      .replace(/\$\$[\s\S]*?\$\$/g, '[Equation]')
      .replace(/\$([^$]+)\$/g, '$1')
      .replace(/\n{3,}/g, '\n\n')
      .trim()

    navigator.clipboard.writeText(cleanedText)
    setCopiedAll(true)
    setTimeout(() => setCopiedAll(false), 1500)
  }

  // Count total annotations (highlights + standalone notes)
  const standaloneNoteCount = notes.filter(n => !n.parent_gluon_id).length
  const totalAnnotations = highlights.length + standaloneNoteCount

  const tabs = [
    { id: 'annotations', label: 'Annotations', count: totalAnnotations },
    { id: 'chat', label: 'Chat', count: null },
    { id: 'info', label: 'Info', count: null },
  ]

  return (
    <aside className="h-full w-full bg-surface border-l border-subtle flex flex-col">
      {/* Tab bar with expand/collapse button */}
      <div className="flex border-b border-subtle">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`
              flex-1 px-3 py-3 text-xs font-medium transition-colors
              ${activeTab === tab.id
                ? 'text-camel border-b-2 border-camel bg-raised/30'
                : 'text-muted hover:text-secondary'
              }
            `}
          >
            {tab.label}
            {tab.count !== null && (
              <span className="ml-1 text-muted">({tab.count})</span>
            )}
          </button>
        ))}

        {/* Expand/collapse button - behavior depends on layout */}
        <button
          onClick={() => {
            if (layout === 'tablet') {
              setTabletSidebarVisible(!tabletSidebarVisible)
            } else {
              // Desktop: expand/collapse sidebar
              setIsChatExpanded(!isChatExpanded)
            }
          }}
          className="px-3 py-3 text-muted hover:text-secondary transition-colors border-l border-subtle"
          title={
            layout === 'tablet'
              ? (tabletSidebarVisible ? 'Hide sidebar' : 'Show sidebar')
              : (isChatExpanded ? 'Collapse sidebar' : 'Expand sidebar')
          }
        >
          {(layout === 'tablet' ? tabletSidebarVisible : isChatExpanded) ? (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          )}
        </button>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto p-4">
        {activeTab === 'annotations' && (
          <AnnotationsPanel
            sourceId={sourceId}
            highlights={highlights}
            notes={notes}
            onHighlightClick={onHighlightClick}
            onHighlightDelete={onHighlightDelete}
            createNote={createNote}
            updateNote={updateNote}
            deleteNote={deleteNote}
            refetchNotes={refetchNotes}
          />
        )}

        {activeTab === 'chat' && (
          <SimpleChatTab
            sourceId={sourceId}
            documentData={documentData}
            selection={selection}
            content={content}
            isExpanded={isChatExpanded}
            setIsExpanded={setIsChatExpanded}
            initialConversationId={initialConversationId}
          />
        )}

        {activeTab === 'info' && (
          <InfoPanel
            documentData={documentData}
            sourceId={sourceId}
            copyAllText={copyAllText}
            copiedAll={copiedAll}
            onEditMetadata={() => setShowMetadataModal(true)}
          />
        )}
      </div>

      {/* Metadata Edit Modal */}
      {showMetadataModal && (
        <MetadataEditModal
          sourceId={sourceId}
          sourceType={documentData?.source_type || 'document'}
          documentData={documentData}
          onClose={() => setShowMetadataModal(false)}
        />
      )}
    </aside>
  )
}


/**
 * Unified Annotations Panel - combines highlights and notes in one view
 *
 * Structure:
 * - Filter chips at top (All | Highlights | Notes)
 * - Highlights section: sorted by document position, with attached notes inline
 * - Document Notes section: standalone notes sorted by creation time
 */
function AnnotationsPanel({
  sourceId,
  highlights,
  notes,
  onHighlightClick,
  onHighlightDelete,
  createNote,
  updateNote,
  deleteNote,
  refetchNotes
}) {
  const navigate = useNavigate()
  const [filter, setFilter] = useState('all') // 'all' | 'highlights' | 'notes'
  const [expandedIds, setExpandedIds] = useState(new Set())
  const [selectedHighlight, setSelectedHighlight] = useState(null)
  const [newNoteText, setNewNoteText] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editText, setEditText] = useState('')
  const [addingNoteToHighlight, setAddingNoteToHighlight] = useState(null) // highlight ID or null
  const [attachedNoteText, setAttachedNoteText] = useState('')

  // Separate attached notes (have parent_gluon_id) from standalone notes
  const { attachedNotes, standaloneNotes } = useMemo(() => {
    const attached = {}
    const standalone = []

    for (const note of notes) {
      if (note.parent_gluon_id) {
        if (!attached[note.parent_gluon_id]) {
          attached[note.parent_gluon_id] = []
        }
        attached[note.parent_gluon_id].push(note)
      } else {
        standalone.push(note)
      }
    }

    // Sort standalone notes by creation time (newest first)
    standalone.sort((a, b) => new Date(b.created_at) - new Date(a.created_at))

    return { attachedNotes: attached, standaloneNotes: standalone }
  }, [notes])

  // Sort highlights by position
  const sortedHighlights = useMemo(() => {
    return [...highlights].sort((a, b) => a.start_offset - b.start_offset)
  }, [highlights])

  const toggleExpand = (id) => {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleScrollTo = (h) => {
    if (selectedHighlight?.id === h.id) {
      setSelectedHighlight(null)
    } else {
      setSelectedHighlight(h)
    }
    onHighlightClick(h)
  }

  // Note handlers
  const handleCreateNote = async () => {
    if (!newNoteText.trim()) return
    try {
      await createNote.mutateAsync({
        content: newNoteText.trim(),
        source_id: sourceId
      })
      setNewNoteText('')
      refetchNotes()
    } catch (err) {
      console.error('Failed to create note:', err)
    }
  }

  // Create note attached to a highlight
  const handleCreateAttachedNote = async (highlightId) => {
    if (!attachedNoteText.trim()) return
    try {
      await createNote.mutateAsync({
        content: attachedNoteText.trim(),
        source_id: sourceId,
        parent_gluon_id: highlightId
      })
      setAttachedNoteText('')
      setAddingNoteToHighlight(null)
      refetchNotes()
    } catch (err) {
      console.error('Failed to create attached note:', err)
    }
  }

  const handleUpdateNote = async (noteId) => {
    if (!editText.trim()) return
    try {
      await updateNote.mutateAsync({
        id: noteId,
        content: editText.trim(),
        sourceId
      })
      setEditingId(null)
      setEditText('')
      refetchNotes()
    } catch (err) {
      console.error('Failed to update note:', err)
    }
  }

  const handleDeleteNote = async (noteId) => {
    try {
      await deleteNote.mutateAsync(noteId)
      refetchNotes()
    } catch (err) {
      console.error('Failed to delete note:', err)
    }
  }

  const startEditing = (note) => {
    setEditingId(note.id)
    setEditText(note.content)
  }

  const showHighlights = filter === 'all' || filter === 'highlights'
  const showNotes = filter === 'all' || filter === 'notes'

  const hasHighlights = highlights.length > 0
  const hasNotes = standaloneNotes.length > 0

  return (
    <div className="space-y-4">
      {/* Filter chips - at top to set viewing context */}
      <div className="flex gap-2">
        {['all', 'highlights', 'notes'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`
              px-3 py-1 rounded-full text-xs font-medium transition-colors
              ${filter === f
                ? 'bg-camel/20 text-camel'
                : 'bg-raised text-muted hover:text-secondary'
              }
            `}
          >
            {f === 'all' ? 'All' : f === 'highlights' ? `Highlights (${highlights.length})` : `Notes (${standaloneNotes.length})`}
          </button>
        ))}
      </div>

      {/* Note input - always visible for quick access */}
      <div className="space-y-2">
        <NoteEditor
          value={newNoteText}
          onChange={setNewNoteText}
          onSubmit={handleCreateNote}
          placeholder="Add a note... (type [[ for refs, ## for tags)"
          rows={2}
        />
        <div className="flex justify-between items-center">
          <span className="text-xs text-muted">Ctrl+Enter to save</span>
          <button
            onClick={handleCreateNote}
            disabled={!newNoteText.trim() || createNote.isPending}
            className="px-3 py-1 bg-camel/20 text-camel rounded text-xs font-medium hover:bg-camel/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {createNote.isPending ? 'Saving...' : 'Add Note'}
          </button>
        </div>
      </div>

      {/* Highlights section */}
      {showHighlights && (
        <div className="space-y-3">
          {hasHighlights && (
            <div className="flex items-center gap-2 text-xs text-muted uppercase tracking-wider font-semibold">
              <span>Highlights</span>
              <div className="flex-1 h-px bg-subtle" />
            </div>
          )}

          {!hasHighlights && filter === 'highlights' && (
            <p className="text-muted text-sm">Select text to create highlights</p>
          )}

          {sortedHighlights.map((h) => {
            const isExpanded = expandedIds.has(h.id)
            const isLong = h.content.length > 150
            const childNotes = attachedNotes[h.id] || []

            return (
              <div key={h.id}>
                <div
                  className={`
                    group p-3 bg-surface rounded-lg transition-all duration-200
                    border-l-[3px] border border-transparent
                    ${selectedHighlight?.id === h.id
                      ? 'border-l-camel bg-raised'
                      : 'border-l-transparent hover:border-subtle'
                    }
                  `}
                >
                  {/* Header with color dot and actions */}
                  <div className="flex items-start gap-2 mb-1">
                    <div
                      className="w-2 h-2 rounded-full flex-shrink-0 mt-1"
                      style={{ backgroundColor: HIGHLIGHT_COLORS[h.color]?.border || '#888' }}
                    />
                    <div className="flex-1" />
                    <div className="flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => {
                          setAddingNoteToHighlight(addingNoteToHighlight === h.id ? null : h.id)
                          setAttachedNoteText('')
                        }}
                        className={`text-[10px] transition-colors ${addingNoteToHighlight === h.id ? 'text-camel' : 'text-muted hover:text-camel'}`}
                        title="Add note to highlight"
                      >
                        +Note
                      </button>
                      <button
                        onClick={() => handleScrollTo(h)}
                        className="text-[10px] text-muted hover:text-secondary transition-colors"
                        title="Scroll to highlight"
                      >
                        Find
                      </button>
                      <button
                        onClick={() => navigate(`/gluon/${h.id}`)}
                        className="text-[10px] text-muted hover:text-camel transition-colors"
                        title="Open in gluon view"
                      >
                        Open
                      </button>
                      <button
                        onClick={() => onHighlightDelete(h.id)}
                        className="text-[10px] text-muted hover:text-red-400 transition-colors"
                        title="Delete highlight"
                      >
                        ×
                      </button>
                    </div>
                  </div>

                  {/* Content - truncated or expanded */}
                  <p className={`text-sm text-secondary leading-relaxed select-text ${!isExpanded && isLong ? 'line-clamp-3' : ''}`}>
                    {h.content}
                  </p>

                  {/* Expand/collapse toggle for long content */}
                  {isLong && (
                    <button
                      onClick={() => toggleExpand(h.id)}
                      className="mt-1.5 text-[10px] text-muted hover:text-camel transition-colors"
                    >
                      {isExpanded ? '▲ Collapse' : '▼ Expand'}
                    </button>
                  )}
                </div>

                {/* Inline add note input */}
                {addingNoteToHighlight === h.id && (
                  <div className="ml-4 mt-2 border-l-2 border-camel/40 pl-3">
                    <div className="p-2 bg-raised/50 rounded space-y-2">
                      <NoteEditor
                        value={attachedNoteText}
                        onChange={setAttachedNoteText}
                        onSubmit={() => handleCreateAttachedNote(h.id)}
                        onCancel={() => { setAddingNoteToHighlight(null); setAttachedNoteText('') }}
                        placeholder="Add a note about this highlight..."
                        rows={2}
                        autoFocus
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleCreateAttachedNote(h.id)}
                          disabled={!attachedNoteText.trim() || createNote.isPending}
                          className="px-2 py-1 bg-camel/20 text-camel rounded text-xs hover:bg-camel/30 disabled:opacity-50"
                        >
                          {createNote.isPending ? 'Saving...' : 'Add'}
                        </button>
                        <button
                          onClick={() => { setAddingNoteToHighlight(null); setAttachedNoteText('') }}
                          className="px-2 py-1 bg-raised text-muted rounded text-xs hover:text-secondary"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Attached notes - indented under the highlight */}
                {childNotes.length > 0 && (
                  <div className="ml-4 mt-2 space-y-2 border-l-2 border-camel/20 pl-3">
                    {childNotes.map((note) => (
                      <AttachedNoteCard
                        key={note.id}
                        note={note}
                        onEdit={() => startEditing(note)}
                        onDelete={() => handleDeleteNote(note.id)}
                        onOpen={() => navigate(`/gluon/${note.id}`)}
                        isEditing={editingId === note.id}
                        editText={editText}
                        setEditText={setEditText}
                        onSave={() => handleUpdateNote(note.id)}
                        onCancel={() => { setEditingId(null); setEditText('') }}
                      />
                    ))}
                  </div>
                )}

                {/* Show backlinks when selected */}
                {selectedHighlight?.id === h.id && (
                  <BacklinksPanel remId={h.id} />
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Document Notes section */}
      {showNotes && standaloneNotes.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-muted uppercase tracking-wider font-semibold">
            <span>Notes</span>
            <div className="flex-1 h-px bg-subtle" />
          </div>

          {/* Standalone notes list */}
          {standaloneNotes.map((note) => (
            <StandaloneNoteCard
              key={note.id}
              note={note}
              onEdit={() => startEditing(note)}
              onDelete={() => handleDeleteNote(note.id)}
              onOpen={() => navigate(`/gluon/${note.id}`)}
              isEditing={editingId === note.id}
              editText={editText}
              setEditText={setEditText}
              onSave={() => handleUpdateNote(note.id)}
              onCancel={() => { setEditingId(null); setEditText('') }}
              isExpanded={expandedIds.has(note.id)}
              onToggleExpand={() => toggleExpand(note.id)}
            />
          ))}
        </div>
      )}

      {/* Empty state when no content at all */}
      {!hasHighlights && !hasNotes && filter === 'all' && (
        <div className="text-center py-8 text-muted">
          <p className="text-sm">No annotations yet</p>
          <p className="text-xs mt-1">Select text to highlight, or add a note above</p>
        </div>
      )}
    </div>
  )
}

/**
 * Attached Note Card - shown indented under a highlight
 */
function AttachedNoteCard({ note, onEdit, onDelete, onOpen, isEditing, editText, setEditText, onSave, onCancel }) {
  if (isEditing) {
    return (
      <div className="p-2 bg-surface rounded border border-camel/20 space-y-2">
        <NoteEditor
          value={editText}
          onChange={setEditText}
          onSubmit={onSave}
          onCancel={onCancel}
          rows={2}
          autoFocus
        />
        <div className="flex gap-2">
          <button onClick={onSave} className="px-2 py-1 bg-camel/20 text-camel rounded text-xs hover:bg-camel/30">Save</button>
          <button onClick={onCancel} className="px-2 py-1 bg-raised text-muted rounded text-xs hover:text-secondary">Cancel</button>
        </div>
      </div>
    )
  }

  return (
    <div className="group p-2 bg-surface rounded border border-camel/20 hover:border-camel/40 transition-colors">
      <div className="select-text">
        <NoteContent content={note.content} tags={note.tags} />
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className="text-[10px] text-muted">{new Date(note.created_at).toLocaleDateString()}</span>
        <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={onOpen} className="text-[10px] text-muted hover:text-camel transition-colors">Open</button>
          <button onClick={onEdit} className="text-[10px] text-muted hover:text-secondary transition-colors">Edit</button>
          <button onClick={onDelete} className="text-[10px] text-muted hover:text-red-400 transition-colors">Delete</button>
        </div>
      </div>
    </div>
  )
}

/**
 * Standalone Note Card - shown in the Notes section
 */
function StandaloneNoteCard({ note, onEdit, onDelete, onOpen, isEditing, editText, setEditText, onSave, onCancel, isExpanded, onToggleExpand }) {
  const isLong = note.content.length > 200

  if (isEditing) {
    return (
      <div className="p-3 bg-surface rounded-lg border border-camel/15 space-y-2">
        <NoteEditor
          value={editText}
          onChange={setEditText}
          onSubmit={onSave}
          onCancel={onCancel}
          rows={3}
          autoFocus
        />
        <div className="flex gap-2">
          <button onClick={onSave} className="px-2 py-1 bg-camel/20 text-camel rounded text-xs hover:bg-camel/30">Save</button>
          <button onClick={onCancel} className="px-2 py-1 bg-raised text-muted rounded text-xs hover:text-secondary">Cancel</button>
        </div>
      </div>
    )
  }

  return (
    <div className="group p-3 bg-surface rounded-lg border border-camel/15 hover:border-camel/30 transition-all duration-200">
      <div className={`select-text ${!isExpanded && isLong ? 'line-clamp-4' : ''}`}>
        <NoteContent content={note.content} tags={note.tags} />
      </div>

      {isLong && (
        <button
          onClick={onToggleExpand}
          className="mt-1.5 text-[10px] text-muted hover:text-camel transition-colors"
        >
          {isExpanded ? '▲ Collapse' : '▼ Expand'}
        </button>
      )}

      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-muted">{new Date(note.created_at).toLocaleDateString()}</span>
        <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={onOpen} className="text-[10px] text-muted hover:text-camel transition-colors">Open</button>
          <button onClick={onEdit} className="text-[10px] text-muted hover:text-secondary transition-colors">Edit</button>
          <button onClick={onDelete} className="text-[10px] text-muted hover:text-red-400 transition-colors">Delete</button>
        </div>
      </div>
    </div>
  )
}


/**
 * Backlinks Panel - shows what references a given rem
 */
function BacklinksPanel({ remId }) {
  const { data: backlinks, isLoading } = useBacklinks(remId)

  if (isLoading) {
    return (
      <div className="mt-2 ml-5 p-2 bg-surface rounded border border-elevated">
        <p className="text-xs text-muted">Loading backlinks...</p>
      </div>
    )
  }

  if (!backlinks || backlinks.total === 0) {
    return (
      <div className="mt-2 ml-5 p-2 bg-surface rounded border border-elevated">
        <p className="text-xs text-muted">No backlinks yet</p>
      </div>
    )
  }

  return (
    <div className="mt-2 ml-5 p-2 bg-surface rounded border border-elevated">
      <p className="text-xs text-muted mb-2">
        {backlinks.total} backlink{backlinks.total !== 1 ? 's' : ''}
      </p>

      {/* References */}
      {backlinks.references?.length > 0 && (
        <div className="space-y-1">
          {backlinks.references.map((ref) => (
            <div key={ref.id} className="text-xs p-1.5 bg-raised rounded">
              <span className="text-blue-400">[[ref]]</span>
              <span className="text-secondary ml-1">{ref.content?.slice(0, 50)}...</span>
              {ref.source_title && (
                <span className="text-muted block mt-0.5">from: {ref.source_title}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Tagged by */}
      {backlinks.tagged_with?.length > 0 && (
        <div className="mt-2 space-y-1">
          <p className="text-xs text-muted">Tagged with this:</p>
          {backlinks.tagged_with.map((ref) => (
            <div key={ref.id} className="text-xs p-1.5 bg-raised rounded">
              <span className="text-secondary">{ref.content?.slice(0, 50)}...</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Note Editor with autocomplete for [[refs]] and ##tags
 * Thin wrapper around the shared AutocompleteTextarea component.
 */
function NoteEditor({ value, onChange, onSubmit, onCancel, placeholder, autoFocus = false, rows = 3 }) {
  return (
    <AutocompleteTextarea
      value={value}
      onChange={onChange}
      onSubmit={onSubmit}
      onCancel={onCancel}
      placeholder={placeholder}
      autoFocus={autoFocus}
      rows={rows}
      inputMode="textarea"
    />
  )
}


/**
 * Note Content - renders markdown, [[refs]] inline, and ##tags as chips
 * Supports: headers, bold, italic, code, code blocks, lists, [[refs]]
 */
function NoteContent({ content, tags = [] }) {
  const navigate = useNavigate()

  // Navigate to gluon by exact content match
  const navigateToRef = async (refContent) => {
    try {
      const { findGluonByContent } = await import('../../hooks/useApi')
      const result = await findGluonByContent(refContent)
      if (result.found && result.id) {
        navigate(`/gluon/${result.id}`)
      } else {
        navigate(`/knowledge?q=${encodeURIComponent(refContent)}`)
      }
    } catch (err) {
      console.error('Failed to resolve ref:', err)
      navigate(`/knowledge?q=${encodeURIComponent(refContent)}`)
    }
  }

  // Render inline elements: bold, italic, code, [[refs]]
  const renderInline = useCallback((text, keyPrefix = '') => {
    if (!text) return text

    // Process text character by character to handle overlapping patterns correctly
    const elements = []
    let i = 0
    let key = 0
    let buffer = ''

    const flushBuffer = () => {
      if (buffer) {
        elements.push(<span key={`${keyPrefix}-t-${key++}`}>{buffer}</span>)
        buffer = ''
      }
    }

    while (i < text.length) {
      // Check for [[ref]]
      if (text.slice(i, i + 2) === '[[') {
        const endRef = text.indexOf(']]', i + 2)
        if (endRef !== -1) {
          flushBuffer()
          const refContent = text.slice(i + 2, endRef)
          elements.push(
            <span
              key={`${keyPrefix}-ref-${key++}`}
              onClick={() => navigateToRef(refContent)}
              className="text-blue-400 bg-blue-400/10 px-1 rounded cursor-pointer hover:bg-blue-400/20"
            >
              {refContent}
            </span>
          )
          i = endRef + 2
          continue
        }
      }

      // Check for `code`
      if (text[i] === '`') {
        const endCode = text.indexOf('`', i + 1)
        if (endCode !== -1) {
          flushBuffer()
          elements.push(
            <code key={`${keyPrefix}-code-${key++}`} className="bg-base px-1 py-0.5 rounded text-[12px] font-mono text-camel">
              {text.slice(i + 1, endCode)}
            </code>
          )
          i = endCode + 1
          continue
        }
      }

      // Check for **bold**
      if (text.slice(i, i + 2) === '**') {
        const endBold = text.indexOf('**', i + 2)
        if (endBold !== -1) {
          flushBuffer()
          elements.push(<strong key={`${keyPrefix}-b-${key++}`}>{text.slice(i + 2, endBold)}</strong>)
          i = endBold + 2
          continue
        }
      }

      // Check for __bold__
      if (text.slice(i, i + 2) === '__') {
        const endBold = text.indexOf('__', i + 2)
        if (endBold !== -1) {
          flushBuffer()
          elements.push(<strong key={`${keyPrefix}-b-${key++}`}>{text.slice(i + 2, endBold)}</strong>)
          i = endBold + 2
          continue
        }
      }

      // Check for *italic* (but not **)
      if (text[i] === '*' && text[i + 1] !== '*') {
        const endItalic = text.indexOf('*', i + 1)
        if (endItalic !== -1 && text[endItalic - 1] !== '*') {
          flushBuffer()
          elements.push(<em key={`${keyPrefix}-i-${key++}`}>{text.slice(i + 1, endItalic)}</em>)
          i = endItalic + 1
          continue
        }
      }

      // Check for _italic_ (but not __)
      if (text[i] === '_' && text[i + 1] !== '_') {
        const endItalic = text.indexOf('_', i + 1)
        if (endItalic !== -1 && text[endItalic - 1] !== '_') {
          flushBuffer()
          elements.push(<em key={`${keyPrefix}-i-${key++}`}>{text.slice(i + 1, endItalic)}</em>)
          i = endItalic + 1
          continue
        }
      }

      // Regular character
      buffer += text[i]
      i++
    }

    flushBuffer()
    return elements.length === 0 ? text : elements.length === 1 ? elements[0] : elements
  }, [navigateToRef])

  // Render markdown content
  const renderedContent = useMemo(() => {
    // Strip ##tags from content
    const textWithoutTags = content.replace(/\s*##\w+/g, '').trim()

    const lines = textWithoutTags.split('\n')
    const elements = []
    let inCodeBlock = false
    let codeBlockContent = []
    let key = 0

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]

      // Code block start/end
      if (line.startsWith('```')) {
        if (inCodeBlock) {
          elements.push(
            <pre key={`code-${key++}`} className="bg-base rounded p-2 my-2 overflow-x-auto text-[11px] font-mono text-secondary">
              <code>{codeBlockContent.join('\n')}</code>
            </pre>
          )
          codeBlockContent = []
          inCodeBlock = false
        } else {
          inCodeBlock = true
        }
        continue
      }

      if (inCodeBlock) {
        codeBlockContent.push(line)
        continue
      }

      // Headers (with or without space after #)
      const h3Match = line.match(/^###\s*(.+)/)
      if (h3Match) {
        elements.push(<h4 key={key++} className="font-semibold text-primary mt-2 mb-1 text-sm">{renderInline(h3Match[1], `h4-${i}`)}</h4>)
        continue
      }
      const h2Match = line.match(/^##\s*(.+)/)
      if (h2Match) {
        elements.push(<h3 key={key++} className="font-semibold text-primary mt-2 mb-1 text-sm">{renderInline(h2Match[1], `h3-${i}`)}</h3>)
        continue
      }
      const h1Match = line.match(/^#\s*(.+)/)
      if (h1Match) {
        elements.push(<h2 key={key++} className="font-bold text-primary mt-2 mb-1">{renderInline(h1Match[1], `h2-${i}`)}</h2>)
        continue
      }

      // List items
      if (line.match(/^[\-\*]\s/)) {
        elements.push(
          <div key={key++} className="flex gap-2 my-0.5">
            <span className="text-muted">•</span>
            <span className="text-sm">{renderInline(line.slice(2), `li-${i}`)}</span>
          </div>
        )
        continue
      }

      // Numbered list items
      if (line.match(/^\d+\.\s/)) {
        const num = line.match(/^(\d+)\./)[1]
        elements.push(
          <div key={key++} className="flex gap-2 my-0.5">
            <span className="text-muted w-4 text-sm">{num}.</span>
            <span className="text-sm">{renderInline(line.replace(/^\d+\.\s/, ''), `ol-${i}`)}</span>
          </div>
        )
        continue
      }

      // Empty line
      if (line.trim() === '') {
        elements.push(<div key={key++} className="h-2" />)
        continue
      }

      // Regular paragraph
      elements.push(<p key={key++} className="text-sm text-secondary my-0.5">{renderInline(line, `p-${i}`)}</p>)
    }

    return elements
  }, [content, renderInline])

  // Tags from API
  const tagList = tags || []

  return (
    <div>
      {/* Rendered markdown content */}
      <div className="text-secondary leading-relaxed">{renderedContent}</div>

      {/* Tags as chips below */}
      {tagList.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {tagList.map((tag) => (
            <span
              key={tag.id}
              onClick={() => navigate(`/gluon/${tag.id}`)}
              className="px-2.5 py-0.5 text-xs bg-terra text-base font-medium rounded-full
                         cursor-pointer hover:bg-terra/90 transition-colors"
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}


/**
 * Info Panel - document actions and metadata
 */
function InfoPanel({ documentData, sourceId, copyAllText, copiedAll, onEditMetadata }) {
  const originalPath = documentData?.original_path
  const { data: meshbookResponse, error: meshbookError } = useMeshbookFacet(sourceId)
  const meshbookFacet = meshbookResponse?.available ? meshbookResponse.facet : null
  const meshbookFailureReason = meshbookResponse?.available === false ? meshbookResponse.reason : null
  const meshbookFailureStatusCode = meshbookResponse?.status_code ?? null
  const showMeshbookUnavailable = !meshbookFacet && (meshbookFailureReason || meshbookError)

  // Helper to format value for display (handles arrays of objects)
  const formatValue = (value) => {
    if (!value) return null
    if (Array.isArray(value)) {
      // Array of {id, content} objects - join content values
      return value.map(v => typeof v === 'object' ? v.content : v).join('; ')
    }
    return value
  }

  // Helper to render metadata field if it has a value
  const MetadataField = ({ label, value }) => {
    const displayText = formatValue(value)
    if (!displayText) return null

    // Check if value is a URL (for URL, DOI fields)
    const isUrl = label === 'URL' ||
      (typeof displayText === 'string' && (displayText.startsWith('http://') || displayText.startsWith('https://')))
    const isDoi = label === 'DOI'

    let displayValue
    if (isUrl) {
      displayValue = (
        <a
          href={displayText}
          target="_blank"
          rel="noopener noreferrer"
          className="text-camel hover:text-camel/80 hover:underline break-all"
        >
          {displayText}
        </a>
      )
    } else if (isDoi) {
      const doiUrl = displayText.startsWith('http') ? displayText : `https://doi.org/${displayText}`
      displayValue = (
        <a
          href={doiUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-camel hover:text-camel/80 hover:underline"
        >
          {displayText}
        </a>
      )
    } else {
      displayValue = <span className="text-secondary">{displayText}</span>
    }

    return (
      <div className="mb-2">
        <span className="text-muted text-xs">{label}: </span>
        <span className="text-xs">{displayValue}</span>
      </div>
    )
  }

  const formatTimestamp = (value) => {
    if (!value) return null

    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
      return value
    }

    return date.toLocaleString([], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    })
  }

  const MeshbookField = ({ label, value }) => {
    if (value === null || value === undefined || value === '') return null

    return (
      <div className="flex items-start justify-between gap-3">
        <span className="text-muted text-xs">{label}</span>
        <span className="text-xs text-secondary text-right">{value}</span>
      </div>
    )
  }

  const meshbookFallback = (() => {
    if (meshbookError) {
      return {
        label: 'Unavailable',
        description: 'Meshbook status could not be loaded from the Scholia backend.',
        badgeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
      }
    }
    switch (meshbookFailureReason) {
      case 'not_found':
        return {
          label: 'Not tracked',
          description: 'This source is not tracked in Meshbook yet.',
          badgeClass: 'bg-raised text-secondary border-elevated',
        }
      case 'offline':
        return {
          label: 'Offline',
          description: 'Meshbook is offline or unreachable right now.',
          badgeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        }
      case 'timeout':
        return {
          label: 'Timed out',
          description: 'Meshbook did not respond before the proxy timed out.',
          badgeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        }
      case 'upstream_error':
        return {
          label: 'Error',
          description: meshbookFailureStatusCode
            ? `Meshbook returned an error (HTTP ${meshbookFailureStatusCode}).`
            : 'Meshbook returned an upstream error.',
          badgeClass: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
        }
      default:
        return null
    }
  })()

  const meshbookStatusClass = meshbookFacet?.meshbook_status === 'ready'
    ? 'bg-green-500/15 text-green-300 border-green-500/30'
    : meshbookFacet?.meshbook_status === 'active'
      ? 'bg-camel/15 text-camel border-camel/30'
      : meshbookFacet
        ? 'bg-raised text-secondary border-elevated'
        : meshbookFallback?.badgeClass || 'bg-raised text-secondary border-elevated'

  return (
    <div className="space-y-4">
      {/* Document metadata display */}
      <div className="space-y-1">
        <div className="flex items-center justify-between mb-2">
          <p className="label text-camel text-xs">Metadata</p>
          <button
            onClick={onEditMetadata}
            className="text-xs text-muted hover:text-camel transition-colors"
          >
            Edit
          </button>
        </div>

        {/* Core fields */}
        <MetadataField label="Title" value={documentData?.title} />
        <MetadataField label="Author" value={documentData?.author} />
        <MetadataField label="Year" value={documentData?.year} />

        {/* BIBCITE fields */}
        <MetadataField label="Journal" value={documentData?.journal} />
        <MetadataField label="Volume" value={documentData?.volume} />
        <MetadataField label="Issue" value={documentData?.issue} />
        <MetadataField label="Pages" value={documentData?.pages} />
        <MetadataField label="DOI" value={documentData?.doi} />
        <MetadataField label="ISBN" value={documentData?.isbn} />
        <MetadataField label="ISSN" value={documentData?.issn} />
        <MetadataField label="URL" value={documentData?.url} />
        <MetadataField label="Editors" value={documentData?.editors} />
        <MetadataField label="Edition" value={documentData?.edition} />
        <MetadataField label="Series" value={documentData?.series} />

        {/* Abstract - shown truncated if long */}
        {documentData?.abstract && (
          <div className="mb-2">
            <span className="text-muted text-xs">Abstract: </span>
            <p className="text-secondary text-xs line-clamp-3">{documentData.abstract}</p>
          </div>
        )}

        {/* Keywords */}
        <MetadataField label="Keywords" value={documentData?.keywords} />
      </div>

      {(meshbookFacet || showMeshbookUnavailable) && (
        <div className="border border-subtle rounded-xl bg-raised/40 p-3 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="label text-camel text-xs">Meshbook</p>
              <p className="text-[11px] text-muted mt-1">
                Compiler status for this source.
              </p>
            </div>
            {(meshbookFacet?.meshbook_status_label || meshbookFallback?.label) && (
              <span className={`px-2 py-1 rounded-full border text-[11px] font-medium ${meshbookStatusClass}`}>
                {meshbookFacet?.meshbook_status_label || meshbookFallback?.label}
              </span>
            )}
          </div>

          {meshbookFacet ? (
            <>
              <div className="space-y-2">
                <MeshbookField label="Packet profile" value={meshbookFacet.packet_profile} />
                <MeshbookField label="Recommended action" value={meshbookFacet.recommended_action_label} />
                <MeshbookField label="Linked pages" value={meshbookFacet.linked_page_count} />
                <MeshbookField label="Last processed" value={formatTimestamp(meshbookFacet.last_processed_or_reviewed_at)} />
              </div>

              {meshbookFacet.open_in_meshbook_url && (
                <a
                  href={meshbookFacet.open_in_meshbook_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="w-full px-4 py-2 bg-base border border-elevated rounded-lg text-secondary hover:text-primary hover:border-camel transition-colors text-sm flex items-center justify-center gap-2"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                  Open in Meshbook
                </a>
              )}
            </>
          ) : (
            <p className="text-xs text-secondary">
              {meshbookFallback?.description || 'Meshbook status is unavailable right now.'}
            </p>
          )}
        </div>
      )}

      <div className="border-t border-subtle pt-4 space-y-2">
        {/* Copy All button */}
        <button
          onClick={copyAllText}
          className={`
            w-full px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2 transition-all
            ${copiedAll
              ? 'bg-green-500/20 text-green-400 border border-green-500/30'
              : 'bg-raised border border-elevated text-secondary hover:text-primary hover:border-camel'
            }
          `}
        >
          {copiedAll ? (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
              Copied!
            </>
          ) : (
            <>
              <CopyIcon className="w-4 h-4" />
              Copy All Text
            </>
          )}
        </button>

        {/* Open original button - for PDFs and web sources (not videos - they're embedded) */}
        {(originalPath || documentData?.url) && documentData?.source_type !== 'media' && (
          <button
            onClick={async () => {
              try {
                const res = await fetch(`${API_BASE}/reading/${sourceId}/open-original`, { method: 'POST' })
                if (!res.ok) {
                  const err = await res.json()
                  alert(err.detail || 'Failed to open source')
                }
              } catch (err) {
                alert('Failed to open source: ' + err.message)
              }
            }}
            className="w-full px-4 py-2 bg-raised border border-elevated rounded-lg text-secondary hover:text-primary hover:border-camel transition-colors text-sm flex items-center justify-center gap-2"
          >
            {documentData?.url ? (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
                Open Source URL
              </>
            ) : (
              'Open Original PDF'
            )}
          </button>
        )}

        {/* Open on YouTube button - for video sources */}
        {documentData?.source_type === 'media' && documentData?.video_id && (
          <a
            href={`https://youtube.com/watch?v=${documentData.video_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="w-full px-4 py-2 bg-raised border border-elevated rounded-lg text-secondary hover:text-primary hover:border-[#ff0000]/50 transition-colors text-sm flex items-center justify-center gap-2"
          >
            <svg className="w-4 h-4 text-[#ff0000]" fill="currentColor" viewBox="0 0 24 24">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
            </svg>
            Open on YouTube
          </a>
        )}

        {/* Edit Sections button */}
        <Link
          to={`/edit/${sourceId}`}
          className="w-full px-4 py-2 bg-raised border border-elevated rounded-lg text-secondary hover:text-primary hover:border-terra transition-colors text-sm flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
          Edit Sections
        </Link>
      </div>

      {/* Source path info */}
      {originalPath && (
        <div className="mt-4 pt-4 border-t border-subtle">
          <p className="label text-muted mb-2 text-xs">Source File</p>
          <p className="text-xs text-secondary break-all">{originalPath}</p>
        </div>
      )}
    </div>
  )
}


/**
 * Table of Contents Pane
 */
function TocPane({ sections, currentSectionId, onSectionClick, analyses }) {
  const activeRef = useRef(null)

  // Auto-scroll ToC to keep active section visible
  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [currentSectionId])

  return (
    <aside className="h-full w-full bg-surface border-r border-subtle overflow-auto">
      <div className="p-4">
        <p className="label text-camel mb-4">Contents</p>

        {/* Analysis entries — above transcript sections */}
        {analyses?.length > 0 && (
          <>
            <nav className="space-y-1 mb-3">
              {analyses.map((a) => (
                <button
                  key={a.id}
                  onClick={() => {
                    const el = document.getElementById(`analysis-${a.id}`)
                    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                  }}
                  className="w-full text-left px-3 py-2 rounded-md text-sm transition-colors text-secondary hover:text-primary hover:bg-raised/50 flex items-center gap-2"
                >
                  <svg className="w-3.5 h-3.5 text-camel flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  {a.display_name}
                </button>
              ))}
            </nav>
            <div className="border-b border-subtle mb-3" />
          </>
        )}

        {sections.length === 0 && !analyses?.length ? (
          <p className="text-muted text-sm">No sections found</p>
        ) : (
          <nav className="space-y-1">
            {sections.map((section) => (
              <button
                key={section.id}
                ref={section.id === currentSectionId ? activeRef : null}
                onClick={() => onSectionClick(section.id)}
                className={`
                  w-full text-left px-3 py-2 rounded-md text-sm transition-colors
                  ${section.id === currentSectionId
                    ? 'bg-raised text-camel border-l-2 border-camel'
                    : 'text-secondary hover:text-primary hover:bg-raised/50'
                  }
                  ${section.level === 3 ? 'pl-6 text-xs' : ''}
                  ${section.level === 1 ? 'font-medium' : ''}
                `}
              >
                {cleanSectionTitle(section.title)}
              </button>
            ))}
          </nav>
        )}
      </div>
    </aside>
  )
}
