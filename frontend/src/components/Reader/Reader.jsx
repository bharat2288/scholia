import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useResizable, ResizeHandle } from '../../hooks/useResizable'
import useDeviceLayout from '../../hooks/useDeviceLayout'
import Drawer from '../common/Drawer'
import {
  useSourceContent,
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
// Global reference to YouTube player for timestamp seeking
let youtubePlayerRef = null

// Highlight colors with their display values
// Colors chosen to be visible on dark backgrounds with good contrast
// Higher opacity (0.5) for better visibility on dark theme
const HIGHLIGHT_COLORS = {
  yellow: { name: 'Yellow', bg: 'rgba(250, 204, 21, 0.5)', border: 'rgb(250, 204, 21)', meaning: 'Important' },
  blue: { name: 'Blue', bg: 'rgba(96, 165, 250, 0.5)', border: 'rgb(96, 165, 250)', meaning: 'Definition' },
  green: { name: 'Green', bg: 'rgba(74, 222, 128, 0.5)', border: 'rgb(74, 222, 128)', meaning: 'Evidence' },
  pink: { name: 'Pink', bg: 'rgba(244, 114, 182, 0.5)', border: 'rgb(244, 114, 182)', meaning: 'Question' },
}

const DEFAULT_HIGHLIGHT_COLOR = 'yellow'

/**
 * Strip markdown formatting from section titles.
 * Headings are already styled, so inline formatting is redundant.
 */
function cleanSectionTitle(title) {
  if (!title) return ''
  return title
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')  // [text](url) → text
    .replace(/\*\*(.+?)\*\*/g, '$1')          // **bold** → bold
    .replace(/\*([^*]+)\*/g, '$1')            // *italic* → italic
    .replace(/`([^`]+)`/g, '$1')              // `code` → code
    .trim()
}

/**
 * Convert a section title to a URL-friendly slug for anchor linking.
 * Handles titles that contain markdown links like "[Introduction](#introduction)"
 */
function slugify(title) {
  if (!title) return ''

  // First, extract text from any markdown links [text](url)
  // e.g., "[Introduction](#introduction)" → "Introduction"
  let text = title.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')

  // Convert to lowercase, replace spaces/underscores with hyphens
  // Remove anything that's not alphanumeric or hyphen
  return text
    .toLowerCase()
    .trim()
    .replace(/[\s_]+/g, '-')      // spaces/underscores → hyphens
    .replace(/[^\w-]/g, '')       // remove special chars
    .replace(/-+/g, '-')          // collapse multiple hyphens
    .replace(/^-|-$/g, '')        // trim leading/trailing hyphens
}

/**
 * Scroll to a section by anchor slug (e.g., "#introduction")
 * Tries multiple matching strategies
 */
function scrollToAnchor(anchor) {
  if (!anchor || !anchor.startsWith('#')) return false

  const slug = anchor.slice(1) // remove #

  // Strategy 1: Direct ID match (some docs might use exact IDs)
  let element = document.getElementById(slug)

  // Strategy 2: Look for section with matching data-slug
  if (!element) {
    element = document.querySelector(`[data-slug="${slug}"]`)
  }

  // Strategy 3: Fuzzy match - find section whose slug contains or is contained by target
  if (!element) {
    const sections = document.querySelectorAll('[data-slug]')
    for (const section of sections) {
      const sectionSlug = section.getAttribute('data-slug')
      if (sectionSlug.includes(slug) || slug.includes(sectionSlug)) {
        element = section
        break
      }
    }
  }

  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    // Brief highlight effect
    element.classList.add('anchor-highlight')
    setTimeout(() => element.classList.remove('anchor-highlight'), 2000)
    return true
  }

  return false
}

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
        stroke="#d4a574"
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
    setTabletSidebarVisible,
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
            onClick={() => setTabletSidebarVisible(true)}
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


/**
 * Copy icon component for reuse
 */
function CopyIcon({ className = "w-4 h-4" }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  )
}


/**
 * YouTube Player component
 * Embeds YouTube video with IFrame API for timestamp seeking
 */
function YouTubePlayer({ videoId, title }) {
  const containerRef = useRef(null)
  const playerRef = useRef(null)
  const { autoScrollEnabled, setAutoScrollEnabled } = useReaderStore()
  const wrapperRef = useRef(null)
  const pollIntervalRef = useRef(null)
  const [isReady, setIsReady] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const [isSticky, setIsSticky] = useState(false)
  // Sticky player width as percentage of container (user-resizable via drag handle)
  const [stickyWidthPct, setStickyWidthPct] = useState(
    () => parseInt(localStorage.getItem('scholia-player-width') || '55')
  )
  const [isResizing, setIsResizing] = useState(false)
  const widthRef = useRef(stickyWidthPct)
  const { setPlaybackTime, setVideoPlaying } = useReaderStore()

  useEffect(() => {
    if (!videoId) return

    if (!window.YT) {
      const tag = document.createElement('script')
      tag.src = 'https://www.youtube.com/iframe_api'
      const firstScriptTag = document.getElementsByTagName('script')[0]
      firstScriptTag.parentNode.insertBefore(tag, firstScriptTag)
    }

    const initPlayer = () => {
      if (!containerRef.current) return
      playerRef.current = new window.YT.Player(containerRef.current, {
        videoId: videoId,
        width: '100%',
        height: '100%',
        playerVars: { autoplay: 0, modestbranding: 1, rel: 0, origin: window.location.origin },
        events: {
          onReady: () => {
            setIsReady(true)
            youtubePlayerRef = playerRef.current
          },
          onStateChange: (event) => {
            // YT.PlayerState: 1=PLAYING, 2=PAUSED, 0=ENDED, 3=BUFFERING
            const playing = event.data === 1
            setVideoPlaying(playing)

            if (playing) {
              // Start 250ms polling for current time
              if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
              pollIntervalRef.current = setInterval(() => {
                if (playerRef.current?.getCurrentTime) {
                  setPlaybackTime(playerRef.current.getCurrentTime())
                }
              }, 100)
            } else {
              // Stop polling when not playing
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current)
                pollIntervalRef.current = null
              }
            }
          },
        },
      })
    }

    if (window.YT && window.YT.Player) initPlayer()
    else window.onYouTubeIframeAPIReady = initPlayer

    return () => {
      youtubePlayerRef = null
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
      if (playerRef.current?.destroy) playerRef.current.destroy()
    }
  }, [videoId])

  const seekTo = useCallback((seconds) => {
    if (playerRef.current?.seekTo) {
      playerRef.current.seekTo(seconds, true)
      playerRef.current.playVideo()
      if (isMinimized) setIsMinimized(false)
    }
  }, [isMinimized])

  useEffect(() => {
    if (isReady && playerRef.current) {
      youtubePlayerRef = { seekTo, player: playerRef.current }
      window.__scholiaYouTubePlayer = youtubePlayerRef
    }
    return () => { window.__scholiaYouTubePlayer = null }
  }, [isReady, seekTo])

  // Detect sticky state via scroll listener on <main>
  // Used only for visual changes (shadow, smaller width) — CSS sticky handles positioning
  useEffect(() => {
    if (!wrapperRef.current || isMinimized) return

    const scrollContainer = wrapperRef.current.closest('main')
    if (!scrollContainer) return

    const handleScroll = () => {
      const wrapper = wrapperRef.current
      if (!wrapper) return
      const rect = wrapper.getBoundingClientRect()
      // Sticky kicks in when wrapper's top reaches the sticky offset (52px)
      setIsSticky(rect.top <= 56)
    }

    scrollContainer.addEventListener('scroll', handleScroll)
    return () => scrollContainer.removeEventListener('scroll', handleScroll)
  }, [isMinimized])

  // Resize drag — adjusts sticky width percentage
  // Right-aligned player: width = distance from cursor to right edge of wrapper
  // Dragging left = wider, dragging right = narrower
  useEffect(() => {
    if (!isResizing) return

    // Lock cursor + disable text selection for the whole document during drag
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handleMouseMove = (e) => {
      const wrapper = wrapperRef.current
      if (!wrapper) return
      const rect = wrapper.getBoundingClientRect()
      // Centered player: width = 2 × distance from cursor to center
      const centerX = rect.left + rect.width / 2
      const pct = Math.max(30, Math.min(98, (Math.abs(e.clientX - centerX) * 2 / rect.width) * 100))
      const rounded = Math.round(pct)
      widthRef.current = rounded
      setStickyWidthPct(rounded)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      localStorage.setItem('scholia-player-width', String(widthRef.current))
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  if (!videoId) return null

  return (
    <div
      ref={wrapperRef}
      className="mb-6 sticky top-[52px] z-20 relative"
    >
      <div
        id="youtube-player-container"
        className={`
          rounded-lg overflow-hidden border border-subtle bg-surface
          ${isResizing ? '' : 'transition-all duration-300 ease-out'}
          ${isMinimized ? 'h-12' : ''}
          ${isSticky && !isMinimized ? 'mx-auto shadow-xl border-camel/20' : ''}
        `}
        style={isSticky && !isMinimized ? { width: `${stickyWidthPct}%` } : {}}
      >
        {/* Header bar */}
        <div className="flex items-center justify-between px-3 py-2 bg-raised/50 border-b border-subtle">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[#ff0000] text-sm">▶</span>
            <span className="text-xs text-secondary truncate">{title || 'Video'}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAutoScrollEnabled(!autoScrollEnabled)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${autoScrollEnabled ? 'bg-camel/20 text-camel' : 'bg-elevated text-muted hover:text-secondary'}`}
              title={autoScrollEnabled ? 'Auto-scroll on — click to disable' : 'Auto-scroll off — click to enable'}
            >
              {autoScrollEnabled ? 'Sync' : 'Sync'}
            </button>
            <button
              onClick={() => setIsMinimized(!isMinimized)}
              className="text-muted hover:text-secondary transition-colors p-1"
              title={isMinimized ? 'Expand video' : 'Minimize video'}
            >
              {isMinimized ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              )}
            </button>
            <a
              href={`https://youtube.com/watch?v=${videoId}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted hover:text-secondary transition-colors p-1"
              title="Open on YouTube"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        </div>

        {/* Video container — 16:9 aspect ratio */}
        {!isMinimized && (
          <div className="relative w-full" style={{ paddingBottom: '56.25%' }}>
            <div ref={containerRef} className="absolute inset-0" />
            {/* Transparent shield: blocks iframe from stealing mouse events during resize drag */}
            {isResizing && <div className="absolute inset-0 z-10" />}
            {!isReady && (
              <div className="absolute inset-0 flex items-center justify-center bg-base">
                <span className="text-muted text-sm">Loading video...</span>
              </div>
            )}
          </div>
        )}

      </div>

      {/* Bilateral resize handles — centered player expands/contracts symmetrically */}
      {isSticky && !isMinimized && (
        <>
          <div
            onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }}
            className="absolute top-0 bottom-0 w-3 -ml-1.5 cursor-col-resize z-30 group flex items-center"
            style={{ left: `${(100 - stickyWidthPct) / 2}%` }}
            title="Drag to resize"
          >
            <div className="w-1 h-10 rounded-full bg-muted/20 group-hover:bg-camel/50 transition-colors" />
          </div>
          <div
            onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }}
            className="absolute top-0 bottom-0 w-3 -ml-1.5 cursor-col-resize z-30 group flex items-center"
            style={{ left: `${(100 + stickyWidthPct) / 2}%` }}
            title="Drag to resize"
          >
            <div className="w-1 h-10 rounded-full bg-muted/20 group-hover:bg-camel/50 transition-colors" />
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Seek YouTube video to specified time.
 * Called by timestamp badges in both transcript and analysis content.
 */
function seekYouTubeVideo(seconds) {
  if (youtubePlayerRef?.seekTo) {
    youtubePlayerRef.seekTo(seconds)
  } else if (youtubePlayerRef?.player?.seekTo) {
    youtubePlayerRef.player.seekTo(seconds, true)
    youtubePlayerRef.player.playVideo()
  }

  // Update playback time immediately so the active cue highlights
  const store = useReaderStore.getState()
  store.setPlaybackTime(seconds)

  // Scroll to the matching cue after a brief delay for DOM update
  setTimeout(() => {
    const el = document.querySelector('[data-cue-active="true"]')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      // Flash animation
      el.classList.add('cue-flash')
      setTimeout(() => el.classList.remove('cue-flash'), 1000)
    }
  }, 50)
}

/**
 * Analysis Section
 * Renders a single analysis block (Summary, Key Claims) through the segment pipeline.
 * Same typography and features as transcript content: section headers with copy buttons,
 * proper lists, blockquotes, code blocks, and [TIMESTAMP] clickable backlinks.
 */
function AnalysisSection({ analysis }) {
  const [copiedSection, setCopiedSection] = useState(null)

  const segments = useMemo(
    () => parseAnalysisIntoSegments(analysis.content),
    [analysis.content]
  )

  const emptyHighlights = useMemo(() => [], [])
  const emptyHighlightMap = useMemo(() => new Map(), [])

  // Copy all text from a section header through to the next same-level header
  const copySectionText = useCallback((sectionIndex) => {
    const startSegment = segments[sectionIndex]
    if (!startSegment || startSegment.type !== 'section') return

    const sectionLevel = startSegment.level
    let text = startSegment.title + '\n\n'

    for (let i = sectionIndex + 1; i < segments.length; i++) {
      const seg = segments[i]
      if (seg.type === 'section' && seg.level <= sectionLevel) break
      if (seg.text) text += seg.text + '\n\n'
      else if (seg.type === 'section') text += seg.title + '\n\n'
    }

    navigator.clipboard.writeText(text.trim())
    setCopiedSection(sectionIndex)
    setTimeout(() => setCopiedSection(null), 1500)
  }, [segments])

  return (
    <div
      id={`analysis-${analysis.id}`}
      className="mb-8 bg-surface/50 border border-subtle rounded-lg p-6"
      style={{ fontFamily: "'Plus Jakarta Sans', -apple-system, sans-serif" }}
    >
      <div className="flex items-center gap-2 mb-4">
        <svg className="w-4 h-4 text-camel" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        <h2 className="text-lg font-display text-primary m-0">{analysis.display_name}</h2>
        {analysis.model && (
          <span className="text-xs text-muted ml-auto">{analysis.model}</span>
        )}
      </div>
      {segments.map((segment, i) => (
        <Segment
          key={i}
          segment={segment}
          segmentIndex={i}
          highlights={emptyHighlights}
          highlightMap={emptyHighlightMap}
          onCopySection={copySectionText}
          isCopied={copiedSection === i}
        />
      ))}
    </div>
  )
}


/**
 * Reading Content
 * Renders document text with offset tracking for reliable highlight selection
 *
 * KEY DESIGN: Every text span has a data-offset attribute with its position
 * in the original document. This allows us to map DOM selections back to
 * character offsets WITHOUT searching/matching text (which caused crashes).
 */
function ReadingContent({ content, sections, figures, highlights, sourceId, analyses }) {
  const [copiedSection, setCopiedSection] = useState(null)
  const activeCueRef = useRef(null)
  const userScrolledRef = useRef(false)
  const lastAutoScrollCueRef = useRef(-1)
  const { fontSize, transcriptCues, activeCueIndex, isVideoPlaying, autoScrollEnabled } = useReaderStore()

  // Active cue offset range for highlighting
  const activeCue = activeCueIndex >= 0 && activeCueIndex < transcriptCues.length
    ? transcriptCues[activeCueIndex]
    : null

  // Auto-scroll to active cue when video is playing
  useEffect(() => {
    if (!isVideoPlaying || !autoScrollEnabled || !activeCue || activeCueIndex === lastAutoScrollCueRef.current) return
    lastAutoScrollCueRef.current = activeCueIndex

    // Find the element with the active cue data attribute
    const el = document.querySelector('[data-cue-active="true"]')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [activeCueIndex, isVideoPlaying, autoScrollEnabled])

  // Pre-process content into segments with offset tracking
  const segments = useMemo(() => {
    return parseContentIntoSegments(content, sections, figures, sourceId)
  }, [content, sections, figures, sourceId])

  // Group highlights by their position for efficient lookup
  const highlightMap = useMemo(() => {
    const map = new Map()
    for (const h of highlights) {
      // Store highlight with its range
      for (let i = h.start_offset; i < h.end_offset; i++) {
        if (!map.has(i)) map.set(i, [])
        map.get(i).push(h)
      }
    }
    return map
  }, [highlights])

  // Extract text for a section (from section start to next section of same/higher level)
  const copySectionText = useCallback((sectionIndex) => {
    const startSegment = segments[sectionIndex]
    if (!startSegment || startSegment.type !== 'section') return

    const sectionLevel = startSegment.level
    let text = startSegment.title + '\n\n'

    // Collect text until next section of same or higher level
    for (let i = sectionIndex + 1; i < segments.length; i++) {
      const seg = segments[i]
      if (seg.type === 'section' && seg.level <= sectionLevel) break

      if (seg.type === 'paragraph') {
        // Clean up the text (remove markdown artifacts)
        text += cleanTextForCopy(seg.text) + '\n\n'
      } else if (seg.type === 'section') {
        text += seg.title + '\n\n'
      } else if (seg.type === 'caption') {
        text += seg.text + '\n\n'
      } else if (seg.type === 'math') {
        text += seg.text + '\n\n'
      }
    }

    navigator.clipboard.writeText(text.trim())
    setCopiedSection(sectionIndex)
    setTimeout(() => setCopiedSection(null), 1500)
  }, [segments])

  return (
    <div
      className="prose prose-invert max-w-none"
      style={{ fontSize: `${fontSize}px`, lineHeight: 1.7 }}
    >
      {/* Analysis blocks rendered above transcript — full segment pipeline */}
      {analyses?.length > 0 && (
        <div className="mb-12">
          {analyses.map((a) => (
            <AnalysisSection key={a.id} analysis={a} />
          ))}
          <div className="border-b border-subtle" />
        </div>
      )}

      {segments.map((segment, i) => (
        <Segment
          key={i}
          segment={segment}
          segmentIndex={i}
          highlights={highlights}
          highlightMap={highlightMap}
          onCopySection={copySectionText}
          isCopied={copiedSection === i}
          sourceId={sourceId}
          activeCue={activeCue}
        />
      ))}
    </div>
  )
}

/**
 * Clean text for copying - remove markdown/HTML artifacts
 */
function cleanTextForCopy(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')  // Remove bold markers
    .replace(/\*([^*]+)\*/g, '$1')     // Remove italic markers
    .replace(/<sup>(.*?)<\/sup>/g, '$1')  // Remove sup tags
    .replace(/<sub>(.*?)<\/sub>/g, '$1')  // Remove sub tags
    .replace(/\$([^$]+)\$/g, '$1')     // Remove inline math markers
}


/**
 * Parse content into segments with offset information
 */
function parseContentIntoSegments(content, sections, figures, sourceId) {
  const paragraphs = content.split('\n\n')
  const segments = []
  let offset = 0
  let figureIndex = 0

  for (const para of paragraphs) {
    if (!para.trim()) {
      offset += para.length + 2
      continue
    }

    const segment = {
      type: 'paragraph',
      text: para,
      offset: offset,
      length: para.length
    }

    // Detect special segment types
    if (para.includes('[SECTION]')) {
      const match = para.match(/\[SECTION\]\s*(#{1,6})\s*(.+)/)
      if (match) {
        segment.type = 'section'
        segment.level = match[1].length
        segment.title = match[2].trim()
        segment.sectionId = sections.find(s => s.title === segment.title)?.id
      }
    } else if (para.includes('[TITLE]')) {
      segment.type = 'title'
    } else if (para.includes('[PAGE')) {
      // Support both old format [PAGE n] and new format [PAGE pdf=n doc=m]
      const newMatch = para.match(/\[PAGE\s+pdf=(\d+)\s+doc=([^\]]*)\]/)
      const oldMatch = para.match(/\[PAGE\s+(\d+)\]/)

      if (newMatch) {
        segment.type = 'page'
        segment.pdfPage = newMatch[1]
        segment.docPage = newMatch[2].trim() || null // doc page from header/footer
        // Display doc page if available, otherwise pdf page
        segment.pageNum = segment.docPage || segment.pdfPage
      } else if (oldMatch) {
        segment.type = 'page'
        segment.pageNum = oldMatch[1]
        segment.pdfPage = oldMatch[1]
        segment.docPage = null
      }
    } else if (para.includes('[FIGURE')) {
      segment.type = 'figure'
      segment.sourceId = sourceId  // Needed for constructing figure URLs
      // Check for web figure format: [FIGURE filename.jpg]
      const webFigureMatch = para.match(/\[FIGURE\s+([^\]]+)\]/)
      if (webFigureMatch) {
        // Web source figure with filename
        segment.figureFilename = webFigureMatch[1].trim()
        segment.isWebFigure = true
      } else {
        // dots-ocr figure (index-based)
        segment.figureIndex = figureIndex
        segment.figure = figures[figureIndex]
        segment.isWebFigure = false
        figureIndex++
      }
    } else if (para.includes('[TABLE]') || para.includes('<table')) {
      segment.type = 'table'
      // Match table tags with or without attributes
      const tableMatch = para.match(/<table[^>]*>[\s\S]*?<\/table>/i)
      if (tableMatch) segment.tableHtml = tableMatch[0]
    } else if (para.includes('[CAPTION]')) {
      segment.type = 'caption'
      segment.text = para.replace('[CAPTION]', '').trim()
    } else if (para.trim().startsWith('$$')) {
      segment.type = 'math'
      segment.text = para.replace(/\$\$/g, '').trim()
    } else if (para.trim().startsWith('```')) {
      // Fenced code block
      segment.type = 'code'
      const codeMatch = para.match(/^```(\w*)\n?([\s\S]*?)```$/m)
      if (codeMatch) {
        segment.language = codeMatch[1] || ''
        segment.text = codeMatch[2].trim()
      } else {
        segment.text = para.replace(/```/g, '').trim()
      }
    } else if (para.trim().startsWith('>')) {
      // Blockquote — preserve original for offset mapping
      segment.type = 'blockquote'
      segment.originalText = para
      segment.text = para.split('\n').map(line => line.replace(/^>\s?/, '')).join('\n')
    } else if (para.includes('[TIMESTAMP')) {
      // Video timestamp marker - may have transcript text following it
      const match = para.match(/\[TIMESTAMP\s+([^\]]+)\]/)
      if (match) {
        segment.type = 'timestamp'
        segment.time = match[1].trim()
        // Parse time to seconds for future video linking
        const timeParts = segment.time.split(':').map(Number)
        if (timeParts.length === 3) {
          segment.seconds = timeParts[0] * 3600 + timeParts[1] * 60 + timeParts[2]
        } else if (timeParts.length === 2) {
          segment.seconds = timeParts[0] * 60 + timeParts[1]
        } else {
          segment.seconds = timeParts[0] || 0
        }
        // Extract text after the timestamp marker
        const textAfter = para.replace(/\[TIMESTAMP\s+[^\]]+\]\n?/, '').trim()
        if (textAfter) {
          segment.text = textAfter
          // Compute offset to the actual text content (skip timestamp marker)
          const textIdx = para.indexOf(textAfter)
          segment.textOffset = segment.offset + (textIdx >= 0 ? textIdx : 0)
        }
      }
    }

    segments.push(segment)
    offset += para.length + 2 // +2 for \n\n
  }

  return segments
}


/**
 * Parse standard markdown (from LLM analysis output) into segments.
 * Handles headers, paragraphs, lists, blockquotes, code blocks, and horizontal rules.
 * Unlike parseContentIntoSegments (which expects [SECTION]/[TIMESTAMP] markers),
 * this handles standard markdown syntax.
 */
function parseAnalysisIntoSegments(content) {
  if (!content) return []

  const segments = []
  const lines = content.split('\n')
  let i = 0
  let offset = 0

  while (i < lines.length) {
    const line = lines[i]

    // Skip empty lines
    if (!line.trim()) {
      offset += line.length + 1
      i++
      continue
    }

    // Code block (``` ... ```)
    if (line.startsWith('```')) {
      const language = line.slice(3).trim()
      const codeLines = []
      const blockStart = offset
      offset += line.length + 1
      i++
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i])
        offset += lines[i].length + 1
        i++
      }
      if (i < lines.length) {
        offset += lines[i].length + 1
        i++ // skip closing ```
      }
      segments.push({
        type: 'code',
        language,
        text: codeLines.join('\n'),
        offset: blockStart,
        length: offset - blockStart,
      })
      continue
    }

    // Headers (# to ######)
    const headerMatch = line.match(/^(#{1,6})\s+(.+)/)
    if (headerMatch) {
      segments.push({
        type: 'section',
        level: headerMatch[1].length,
        title: headerMatch[2].trim(),
        offset,
        length: line.length,
      })
      offset += line.length + 1
      i++
      continue
    }

    // Horizontal rule (---, ***, ___)
    if (line.trim().match(/^[-*_]{3,}$/)) {
      segments.push({ type: 'hr', offset, length: line.length })
      offset += line.length + 1
      i++
      continue
    }

    // Blockquote (collect consecutive > lines)
    if (line.startsWith('>')) {
      const quoteLines = []
      const blockStart = offset
      while (i < lines.length && lines[i].startsWith('>')) {
        quoteLines.push(lines[i])
        offset += lines[i].length + 1
        i++
      }
      const originalText = quoteLines.join('\n')
      segments.push({
        type: 'blockquote',
        originalText,
        text: quoteLines.map(l => l.replace(/^>\s?/, '')).join('\n'),
        offset: blockStart,
        length: offset - blockStart,
      })
      continue
    }

    // Unordered list (- or * followed by space)
    if (line.match(/^[-*]\s/)) {
      const listLines = []
      const blockStart = offset
      while (i < lines.length && (lines[i].match(/^[-*]\s/) || lines[i].match(/^\s{2,}\S/))) {
        listLines.push(lines[i])
        offset += lines[i].length + 1
        i++
      }
      segments.push({
        type: 'list',
        ordered: false,
        items: listLines.map(l => l.replace(/^[-*]\s+/, '').replace(/^\s{2,}/, '')),
        text: listLines.join('\n'),
        offset: blockStart,
        length: offset - blockStart,
      })
      continue
    }

    // Ordered list (1. 2. etc.)
    if (line.match(/^\d+\.\s/)) {
      const listLines = []
      const blockStart = offset
      while (i < lines.length && (lines[i].match(/^\d+\.\s/) || lines[i].match(/^\s{2,}\S/))) {
        listLines.push(lines[i])
        offset += lines[i].length + 1
        i++
      }
      segments.push({
        type: 'list',
        ordered: true,
        items: listLines.map(l => l.replace(/^\d+\.\s+/, '').replace(/^\s{2,}/, '')),
        text: listLines.join('\n'),
        offset: blockStart,
        length: offset - blockStart,
      })
      continue
    }

    // Regular paragraph (collect lines until empty line or special block)
    const paraLines = []
    const blockStart = offset
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].match(/^#{1,6}\s/) &&
      !lines[i].trim().match(/^[-*_]{3,}$/) &&
      !lines[i].startsWith('>') &&
      !lines[i].startsWith('```') &&
      !(lines[i].match(/^[-*]\s/) && !paraLines.length) &&
      !(lines[i].match(/^\d+\.\s/) && !paraLines.length)
    ) {
      paraLines.push(lines[i])
      offset += lines[i].length + 1
      i++
    }
    if (paraLines.length > 0) {
      segments.push({
        type: 'paragraph',
        text: paraLines.join('\n'),
        offset: blockStart,
        length: offset - blockStart,
      })
    }
  }

  return segments
}


/**
 * Render a single segment
 */
function Segment({ segment, segmentIndex, highlights, highlightMap, onCopySection, isCopied, sourceId, activeCue }) {
  switch (segment.type) {
    case 'title':
      return null

    case 'section': {
      const Tag = segment.level === 1 ? 'h2' : segment.level === 2 ? 'h3' : 'h4'
      const sectionSlug = slugify(segment.title)
      const cleanTitle = cleanSectionTitle(segment.title)
      return (
        <Tag
          id={segment.sectionId ? `section-${segment.sectionId}` : sectionSlug}
          data-slug={sectionSlug}
          className={`
            group flex items-center gap-2 transition-colors duration-500
            ${segment.level === 1 ? 'text-2xl font-display mt-12 mb-6' : ''}
            ${segment.level === 2 ? 'text-xl font-semibold mt-10 mb-4' : ''}
            ${segment.level >= 3 ? 'text-lg font-medium mt-8 mb-3' : ''}
            text-primary
          `}
        >
          <span className="flex-1">{cleanTitle}</span>
          <button
            onClick={(e) => { e.preventDefault(); onCopySection(segmentIndex) }}
            className={`
              flex-shrink-0 p-1.5 rounded-md transition-all
              ${isCopied
                ? 'bg-green-500/20 text-green-400'
                : 'opacity-0 group-hover:opacity-100 bg-raised hover:bg-elevated text-muted hover:text-secondary'
              }
            `}
            title="Copy section text"
          >
            {isCopied ? (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <CopyIcon className="w-4 h-4" />
            )}
          </button>
        </Tag>
      )
    }

    case 'page':
      // Show doc page with PDF position in tooltip, or just PDF page if no doc page
      const pageDisplay = segment.pageNum
      const pageTitle = segment.docPage && segment.pdfPage !== segment.docPage
        ? `Page ${segment.docPage} (PDF page ${segment.pdfPage})`
        : `Page ${segment.pdfPage}`
      return (
        <div className="my-8 flex items-center justify-center gap-4 text-muted select-none">
          <div className="flex-1 h-px bg-elevated max-w-[100px]" />
          <span className="text-xs font-mono opacity-60" title={pageTitle}>{pageDisplay}</span>
          <div className="flex-1 h-px bg-elevated max-w-[100px]" />
        </div>
      )

    case 'timestamp': {
      // Video timestamp marker with transcript text - clickable to seek video
      // Check if the active cue falls within this segment's text range
      const tsBaseOffset = segment.textOffset || segment.offset
      const tsEndOffset = tsBaseOffset + (segment.text?.length || 0)
      const isCueActive = activeCue &&
        activeCue.start_offset < tsEndOffset &&
        activeCue.end_offset > tsBaseOffset

      return (
        <div
          className={`mt-6 transition-colors duration-100 ${isCueActive ? 'rounded-md bg-camel/8' : ''}`}
          data-cue-active={isCueActive ? 'true' : undefined}
        >
          <div className="mb-2 flex items-center gap-2 select-none">
            <button
              onClick={() => seekYouTubeVideo(segment.seconds)}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono transition-colors cursor-pointer ${
                isCueActive
                  ? 'bg-camel/20 text-camel ring-1 ring-camel/30'
                  : 'bg-[#ff0000]/10 text-[#ff0000]/80 hover:bg-[#ff0000]/20 hover:text-[#ff0000]'
              }`}
              title={`Jump to ${segment.time} in video`}
              data-seconds={segment.seconds}
            >
              <span className="text-[10px]">{isCueActive ? '●' : '▶'}</span>
              {segment.time}
            </button>
          </div>
          {segment.text && (
            <p className="text-secondary leading-relaxed mb-4">
              <OffsetText
                text={segment.text}
                baseOffset={tsBaseOffset}
                highlights={highlights}
                activeCue={activeCue}
              />
            </p>
          )}
        </div>
      )
    }

    case 'figure':
      // Web figures have filename, dots-ocr figures have index-based lookup
      if (segment.isWebFigure && segment.figureFilename) {
        // Web source figure - construct URL from filename
        const webFigureUrl = `${API_BASE}/reading/${segment.sourceId}/web-figure/${segment.figureFilename}`
        return (
          <figure className="my-8">
            <div className="bg-raised rounded-lg border border-elevated overflow-hidden">
              <img
                src={webFigureUrl}
                alt={`Figure`}
                className="w-full h-auto"
                loading="lazy"
                onError={(e) => {
                  e.target.style.display = 'none'
                  e.target.nextSibling?.classList?.remove('hidden')
                }}
              />
              <div className="hidden p-4 text-center text-muted text-sm">
                [Image not available]
              </div>
            </div>
          </figure>
        )
      } else if (segment.figure) {
        // dots-ocr figure with pre-fetched metadata
        return (
          <figure className="my-8">
            <div className="bg-raised rounded-lg border border-elevated overflow-hidden">
              <img
                src={`${API_BASE}${segment.figure.url}`}
                alt={segment.figure.caption || `Figure ${segment.figureIndex + 1}`}
                className="w-full h-auto"
                loading="lazy"
              />
            </div>
            {segment.figure.caption && (
              <figcaption className="mt-2 text-sm text-secondary italic text-center">
                {segment.figure.caption}
              </figcaption>
            )}
          </figure>
        )
      }
      return (
        <div className="my-6 p-4 bg-raised rounded-lg border border-elevated text-center">
          <p className="text-muted text-sm">[Figure]</p>
        </div>
      )

    case 'table':
      if (segment.tableHtml) {
        return (
          <div
            className="my-6 overflow-x-auto prose"
            dangerouslySetInnerHTML={{ __html: segment.tableHtml }}
          />
        )
      }
      return (
        <div className="my-6 p-4 bg-raised rounded-lg border border-elevated text-center">
          <p className="text-muted text-sm">[Table]</p>
        </div>
      )

    case 'caption':
      return (
        <p className="text-sm text-secondary italic text-center -mt-4 mb-6">
          {segment.text}
        </p>
      )

    case 'math':
      return (
        <div className="my-6 text-center font-mono text-sm bg-raised/50 py-4 px-6 rounded overflow-x-auto">
          {segment.text}
        </div>
      )

    case 'code':
      return (
        <div className="my-6 rounded-lg overflow-hidden border border-elevated">
          {segment.language && (
            <div className="bg-elevated/50 px-4 py-1.5 text-xs text-muted font-mono border-b border-elevated">
              {segment.language}
            </div>
          )}
          <pre className="bg-raised/50 p-4 overflow-x-auto">
            <code className="text-sm font-mono text-secondary whitespace-pre">
              {segment.text}
            </code>
          </pre>
        </div>
      )

    case 'blockquote': {
      // Render per-line with correct offsets accounting for '> ' prefix stripping
      const originalLines = (segment.originalText || segment.text).split('\n')
      let lineOffset = segment.offset
      return (
        <blockquote className="my-6 pl-4 border-l-2 border-camel/50 text-secondary italic">
          {originalLines.map((line, i) => {
            const cleanLine = line.replace(/^>\s?/, '')
            const prefixLen = line.length - cleanLine.length
            const textOffset = lineOffset + prefixLen
            lineOffset += line.length + 1  // +1 for \n
            if (!cleanLine) return <br key={i} />
            return (
              <span key={i}>
                <OffsetText text={cleanLine} baseOffset={textOffset} highlights={highlights} />
                {i < originalLines.length - 1 && <br />}
              </span>
            )
          })}
        </blockquote>
      )
    }

    case 'list':
      return (
        <div className="my-4 space-y-1.5 ml-1">
          {(segment.items || []).map((item, idx) => (
            <div key={idx} className="flex gap-3">
              <span className="text-muted flex-shrink-0 mt-0.5 w-4 text-right">
                {segment.ordered ? `${idx + 1}.` : '•'}
              </span>
              <span className="text-secondary leading-relaxed">
                <FormattedSpan text={item} baseOffset={segment.offset} />
              </span>
            </div>
          ))}
        </div>
      )

    case 'hr':
      return (
        <div className="my-8 flex items-center justify-center gap-4">
          <div className="flex-1 h-px bg-elevated max-w-full" />
        </div>
      )

    default:
      // Regular paragraph - render with offset tracking and highlights
      // whitespace-pre-line preserves \n in analysis content (bold labels on separate lines)
      return (
        <div className="group/edit relative mb-4">
          <p className="text-secondary leading-relaxed whitespace-pre-line">
            <OffsetText
              text={segment.text}
              baseOffset={segment.offset}
              highlights={highlights}
            />
          </p>
          {sourceId && (
            <Link
              to={`/edit/${sourceId}?offset=${segment.offset}`}
              className="absolute -left-8 top-0.5 opacity-0 group-hover/edit:opacity-100 p-1 rounded text-muted hover:text-camel transition-opacity"
              title="Edit at this point"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </Link>
          )}
        </div>
      )
  }
}


/**
 * Render text with character offset tracking
 * Each span has data-offset for selection mapping
 */
function OffsetText({ text, baseOffset, highlights, activeCue }) {
  // Find highlights that overlap this text range
  const relevantHighlights = useMemo(() => {
    const textEnd = baseOffset + text.length
    return highlights.filter(h => h.start_offset < textEnd && h.end_offset > baseOffset)
      .sort((a, b) => a.start_offset - b.start_offset)
  }, [highlights, baseOffset, text.length])

  // Compute active cue range relative to this text span
  const cueRange = useMemo(() => {
    if (!activeCue) return null
    const textEnd = baseOffset + text.length
    if (activeCue.start_offset >= textEnd || activeCue.end_offset <= baseOffset) return null
    return {
      start: Math.max(0, activeCue.start_offset - baseOffset),
      end: Math.min(text.length, activeCue.end_offset - baseOffset),
      seconds: activeCue.start_time,
    }
  }, [activeCue, baseOffset, text.length])

  // If no highlights and no active cue, render simple text with offset
  if (relevantHighlights.length === 0 && !cueRange) {
    return (
      <span data-offset={baseOffset}>
        <FormattedSpan text={text} baseOffset={baseOffset} />
      </span>
    )
  }

  // Build a list of "markers" (boundaries where styling changes)
  // Each marker: { pos, type: 'hl-start'|'hl-end'|'cue-start'|'cue-end', data }
  const markers = []
  for (const h of relevantHighlights) {
    const hlStart = Math.max(0, h.start_offset - baseOffset)
    const hlEnd = Math.min(text.length, h.end_offset - baseOffset)
    if (hlStart >= text.length || hlEnd <= 0) continue
    markers.push({ pos: hlStart, type: 'hl-start', highlight: h })
    markers.push({ pos: hlEnd, type: 'hl-end', highlight: h })
  }
  if (cueRange) {
    markers.push({ pos: cueRange.start, type: 'cue-start' })
    markers.push({ pos: cueRange.end, type: 'cue-end' })
  }
  markers.sort((a, b) => a.pos - b.pos || (a.type.endsWith('start') ? -1 : 1))

  // Walk through text, splitting at marker boundaries
  const parts = []
  let currentPos = 0
  const activeHighlights = new Set()
  let cueActive = false

  // Collect unique boundary positions
  const boundaries = [...new Set(markers.map(m => m.pos))].sort((a, b) => a - b)

  for (const boundary of boundaries) {
    // Render text from currentPos to this boundary with current styling
    if (boundary > currentPos) {
      parts.push(renderStyledSpan(text, baseOffset, currentPos, boundary, activeHighlights, cueActive, cueRange, parts.length))
    }
    currentPos = boundary

    // Process all markers at this position
    for (const m of markers) {
      if (m.pos !== boundary) continue
      if (m.type === 'hl-start') activeHighlights.add(m.highlight)
      if (m.type === 'hl-end') activeHighlights.delete(m.highlight)
      if (m.type === 'cue-start') cueActive = true
      if (m.type === 'cue-end') cueActive = false
    }
  }

  // Remaining text after all markers
  if (currentPos < text.length) {
    parts.push(renderStyledSpan(text, baseOffset, currentPos, text.length, activeHighlights, cueActive, cueRange, parts.length))
  }

  return <>{parts}</>
}

/** Render a text slice with combined highlight + cue styling */
function renderStyledSpan(text, baseOffset, start, end, activeHighlights, cueActive, cueRange, keyIndex) {
  const slice = text.slice(start, end)
  const offset = baseOffset + start
  const hl = activeHighlights.size > 0 ? [...activeHighlights][0] : null
  const color = hl ? (HIGHLIGHT_COLORS[hl.color] || HIGHLIGHT_COLORS.yellow) : null

  // Active cue with no highlight — clickable glowing span
  if (cueActive && !hl) {
    return (
      <span
        key={`cue-${keyIndex}`}
        data-offset={offset}
        className="bg-camel/15 text-primary rounded-sm transition-colors duration-75 cursor-pointer hover:bg-camel/25"
        onClick={(e) => { e.stopPropagation(); seekYouTubeVideo(cueRange.seconds) }}
        title="Click to seek video"
      >
        <FormattedSpan text={slice} baseOffset={offset} />
      </span>
    )
  }

  // Highlight (with or without cue)
  if (hl) {
    return (
      <mark
        key={hl.id + '-' + keyIndex}
        data-offset={offset}
        data-highlight-id={hl.id}
        className={`rounded px-0.5 transition-all ${cueActive ? 'ring-1 ring-camel/40' : ''}`}
        style={{ backgroundColor: color.bg }}
      >
        <FormattedSpan text={slice} baseOffset={offset} />
      </mark>
    )
  }

  // Plain text
  return (
    <span key={`plain-${keyIndex}`} data-offset={offset}>
      <FormattedSpan text={slice} baseOffset={offset} />
    </span>
  )
}


/**
 * Simple text formatting (bold, italic, etc.)
 * Stripped down version that doesn't interfere with offset tracking
 */
/**
 * Render text with inline markdown/HTML formatting.
 * When baseOffset is provided, each sub-element gets data-offset pointing to
 * its position in the raw text. This is critical for accurate highlight offset
 * calculation — without it, formatting markers (*, **, <sup>, etc.) that are
 * consumed during rendering cause DOM character counts to diverge from raw
 * text positions.
 */
function FormattedSpan({ text, baseOffset }) {
  if (!text) return null

  // Multi-line text: process each line separately so regex patterns (which use . that
  // doesn't match \n) can find **bold**, [TIMESTAMP], etc. on every line
  if (text.includes('\n')) {
    const lines = text.split('\n')
    let lineOffset = 0
    return <>{lines.map((line, i) => {
      const offset = baseOffset !== undefined ? baseOffset + lineOffset : undefined
      lineOffset += line.length + 1 // +1 for the \n
      if (i === 0) return <FormattedSpan key={i} text={line} baseOffset={offset} />
      return <span key={i}>{'\n'}<FormattedSpan text={line} baseOffset={offset} /></span>
    })}</>
  }

  // Quick check if any formatting needed
  if (!text.includes('**') && !text.includes('*') && !text.includes('<') && !text.includes('$') && !text.includes('`') && !text.includes('[')) {
    return text
  }

  // Process markdown and HTML formatting, tracking raw text position
  const parts = []
  let remaining = text
  let rawOffset = 0 // position in raw text relative to start of `text`
  let key = 0
  const track = baseOffset !== undefined

  while (remaining.length > 0) {
    // Bold **text**
    const boldMatch = remaining.match(/^(.*?)\*\*(.+?)\*\*/)
    if (boldMatch) {
      if (boldMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{boldMatch[1]}</span>)
        rawOffset += boldMatch[1].length
      }
      rawOffset += 2 // skip opening **
      parts.push(<strong key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })} className="font-semibold text-primary">{boldMatch[2]}</strong>)
      rawOffset += boldMatch[2].length
      rawOffset += 2 // skip closing **
      remaining = remaining.slice(boldMatch[0].length)
      continue
    }

    // Italic *text*
    const italicMatch = remaining.match(/^(.*?)\*([^*]+)\*/)
    if (italicMatch && !italicMatch[1].endsWith('*')) {
      if (italicMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{italicMatch[1]}</span>)
        rawOffset += italicMatch[1].length
      }
      rawOffset += 1 // skip opening *
      parts.push(<em key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })} className="italic">{italicMatch[2]}</em>)
      rawOffset += italicMatch[2].length
      rawOffset += 1 // skip closing *
      remaining = remaining.slice(italicMatch[0].length)
      continue
    }

    // Superscript <sup>
    const supMatch = remaining.match(/^(.*?)<sup>(.*?)<\/sup>/s)
    if (supMatch) {
      if (supMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{supMatch[1]}</span>)
        rawOffset += supMatch[1].length
      }
      rawOffset += 5 // skip <sup>
      parts.push(<sup key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })} className="text-xs">{supMatch[2]}</sup>)
      rawOffset += supMatch[2].length
      rawOffset += 6 // skip </sup>
      remaining = remaining.slice(supMatch[0].length)
      continue
    }

    // Subscript <sub>
    const subMatch = remaining.match(/^(.*?)<sub>(.*?)<\/sub>/s)
    if (subMatch) {
      if (subMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{subMatch[1]}</span>)
        rawOffset += subMatch[1].length
      }
      rawOffset += 5 // skip <sub>
      parts.push(<sub key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })} className="text-xs">{subMatch[2]}</sub>)
      rawOffset += subMatch[2].length
      rawOffset += 6 // skip </sub>
      remaining = remaining.slice(subMatch[0].length)
      continue
    }

    // Inline math $...$
    const mathMatch = remaining.match(/^(.*?)\$([^$]+)\$/)
    if (mathMatch && !mathMatch[1].endsWith('$')) {
      if (mathMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{mathMatch[1]}</span>)
        rawOffset += mathMatch[1].length
      }
      rawOffset += 1 // skip opening $
      parts.push(<code key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })} className="font-mono text-sm bg-raised/30 px-1 rounded">{mathMatch[2]}</code>)
      rawOffset += mathMatch[2].length
      rawOffset += 1 // skip closing $
      remaining = remaining.slice(mathMatch[0].length)
      continue
    }

    // Inline code `text`
    const codeMatch = remaining.match(/^(.*?)`([^`]+)`/)
    if (codeMatch) {
      if (codeMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{codeMatch[1]}</span>)
        rawOffset += codeMatch[1].length
      }
      rawOffset += 1 // skip opening `
      parts.push(<code key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })} className="font-mono text-sm bg-raised/50 px-1.5 py-0.5 rounded text-camel/90">{codeMatch[2]}</code>)
      rawOffset += codeMatch[2].length
      rawOffset += 1 // skip closing `
      remaining = remaining.slice(codeMatch[0].length)
      continue
    }

    // [TIMESTAMP HH:MM:SS] — clickable button to seek YouTube player
    const tsMatch = remaining.match(/^(.*?)\[TIMESTAMP\s+([^\]]+)\]/)
    if (tsMatch) {
      if (tsMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{tsMatch[1]}</span>)
        rawOffset += tsMatch[1].length
      }
      const tsValue = tsMatch[2].trim()
      const tsParts = tsValue.split(':').map(Number)
      let totalSeconds = 0
      if (tsParts.length === 3) totalSeconds = tsParts[0] * 3600 + tsParts[1] * 60 + tsParts[2]
      else if (tsParts.length === 2) totalSeconds = tsParts[0] * 60 + tsParts[1]

      const fullTokenLen = tsMatch[0].length - tsMatch[1].length
      parts.push(
        <button
          key={key++}
          onClick={(e) => { e.stopPropagation(); seekYouTubeVideo(totalSeconds) }}
          className="text-camel bg-camel/10 px-1.5 py-0.5 rounded text-xs font-mono hover:bg-camel/20 transition-colors cursor-pointer"
          title={`Jump to ${tsValue}`}
          {...(track && { 'data-offset': baseOffset + rawOffset })}
        >
          {tsValue}
        </button>
      )
      rawOffset += fullTokenLen
      remaining = remaining.slice(tsMatch[0].length)
      continue
    }

    // Markdown links [text](url)
    const linkMatch = remaining.match(/^(.*?)\[([^\]]+)\]\(([^)]+)\)/)
    if (linkMatch) {
      if (linkMatch[1]) {
        parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{linkMatch[1]}</span>)
        rawOffset += linkMatch[1].length
      }
      rawOffset += 1 // skip [
      const linkText = linkMatch[2]
      // Strip optional markdown title: url "title" → url
      const rawLinkUrl = linkMatch[3]
      const linkUrl = rawLinkUrl.replace(/\s+"[^"]*"$/, '')
      const linkOffset = track ? baseOffset + rawOffset : undefined

      // Categorize link types
      const isExternal = linkUrl.startsWith('http://') || linkUrl.startsWith('https://') || linkUrl.startsWith('mailto:')
      const isAnchor = linkUrl.startsWith('#')
      const isRelative = !isExternal && !isAnchor

      if (isExternal) {
        parts.push(
          <a
            key={key++}
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-camel hover:text-camel/80 underline underline-offset-2 decoration-camel/40 hover:decoration-camel/70 transition-colors"
            {...(linkOffset !== undefined && { 'data-offset': linkOffset })}
          >
            {linkText}
          </a>
        )
      } else if (isAnchor) {
        parts.push(
          <a
            key={key++}
            href={linkUrl}
            onClick={(e) => {
              e.preventDefault()
              scrollToAnchor(linkUrl)
            }}
            className="text-camel hover:text-camel/80 underline underline-offset-2 decoration-camel/40 hover:decoration-camel/70 transition-colors cursor-pointer"
            {...(linkOffset !== undefined && { 'data-offset': linkOffset })}
          >
            {linkText}
          </a>
        )
      } else if (isRelative) {
        parts.push(
          <span
            key={key++}
            className="text-camel/60 cursor-default"
            title={`Link to: ${linkUrl} (external document)`}
            {...(linkOffset !== undefined && { 'data-offset': linkOffset })}
          >
            {linkText}
          </span>
        )
      }
      rawOffset += linkText.length
      rawOffset += 2 // skip ](
      rawOffset += rawLinkUrl.length // use raw length (includes title) for offset tracking
      rawOffset += 1 // skip )
      remaining = remaining.slice(linkMatch[0].length)
      continue
    }

    // No more patterns — render remaining plain text
    parts.push(<span key={key++} {...(track && { 'data-offset': baseOffset + rawOffset })}>{remaining}</span>)
    break
  }

  return <>{parts}</>
}
