/**
 * Reading Content and Analysis Section components.
 * ReadingContent is the main reading view that renders document text with
 * offset tracking for reliable highlight selection. AnalysisSection renders
 * LLM analysis blocks through the same segment pipeline.
 */
import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import useReaderStore from '../../stores/useReaderStore'
import { cleanTextForCopy } from './readerUtils'
import { parseContentIntoSegments, parseAnalysisIntoSegments } from './Segment'
import Segment from './Segment'

/**
 * Analysis Section
 * Renders a single analysis block (Summary, Key Claims) through the segment pipeline.
 * Same typography and features as transcript content: section headers with copy buttons,
 * proper lists, blockquotes, code blocks, and [TIMESTAMP] clickable backlinks.
 */
export function AnalysisSection({ analysis }) {
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
export default function ReadingContent({ content, sections, figures, highlights, sourceId, analyses, searchMatches, currentMatchStart }) {
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
          searchMatches={searchMatches}
          currentMatchStart={currentMatchStart}
        />
      ))}
    </div>
  )
}
