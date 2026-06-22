/**
 * Render text with character offset tracking and highlight/cue/search overlay.
 * Uses a marker-based system to split text at highlight, active-cue, and
 * search-match boundaries, rendering each slice with combined styling.
 */
import { useMemo } from 'react'
import { HIGHLIGHT_COLORS } from './readerUtils'
import { seekYouTubeVideo } from './YouTubePlayer'
import FormattedSpan from './FormattedSpan'

const EMPTY = []

/**
 * Render text with character offset tracking.
 * Each span has data-offset for selection mapping.
 */
export default function OffsetText({ text, baseOffset, highlights, activeCue, searchMatches = EMPTY, currentMatchStart = -1 }) {
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

  // Search matches overlapping this text range (absolute offsets)
  const relevantMatches = useMemo(() => {
    if (!searchMatches.length) return EMPTY
    const textEnd = baseOffset + text.length
    return searchMatches.filter(m => m.start < textEnd && m.end > baseOffset)
  }, [searchMatches, baseOffset, text.length])

  // Range of the currently-focused match within this text span (for scroll/emphasis)
  const currentRange = useMemo(() => {
    if (currentMatchStart < 0) return null
    const m = relevantMatches.find(mm => mm.start === currentMatchStart)
    if (!m) return null
    return { start: Math.max(0, m.start - baseOffset), end: Math.min(text.length, m.end - baseOffset) }
  }, [relevantMatches, currentMatchStart, baseOffset, text.length])

  // If no overlays at all, render simple text with offset
  if (relevantHighlights.length === 0 && !cueRange && relevantMatches.length === 0) {
    return (
      <span data-offset={baseOffset}>
        <FormattedSpan text={text} baseOffset={baseOffset} />
      </span>
    )
  }

  // Build a list of "markers" (boundaries where styling changes)
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
  for (const m of relevantMatches) {
    const sStart = Math.max(0, m.start - baseOffset)
    const sEnd = Math.min(text.length, m.end - baseOffset)
    if (sStart >= text.length || sEnd <= 0) continue
    markers.push({ pos: sStart, type: 'sm-start' })
    markers.push({ pos: sEnd, type: 'sm-end' })
  }
  markers.sort((a, b) => a.pos - b.pos || (a.type.endsWith('start') ? -1 : 1))

  // Walk through text, splitting at marker boundaries
  const parts = []
  let currentPos = 0
  const activeHighlights = new Set()
  let cueActive = false
  let searchDepth = 0

  // Collect unique boundary positions
  const boundaries = [...new Set(markers.map(m => m.pos))].sort((a, b) => a - b)

  for (const boundary of boundaries) {
    // Render text from currentPos to this boundary with current styling
    if (boundary > currentPos) {
      const searchCurrent = !!currentRange && currentPos >= currentRange.start && boundary <= currentRange.end
      parts.push(renderStyledSpan(text, baseOffset, currentPos, boundary, activeHighlights, cueActive, cueRange, searchDepth > 0, searchCurrent, parts.length))
    }
    currentPos = boundary

    // Process all markers at this position
    for (const m of markers) {
      if (m.pos !== boundary) continue
      if (m.type === 'hl-start') activeHighlights.add(m.highlight)
      if (m.type === 'hl-end') activeHighlights.delete(m.highlight)
      if (m.type === 'cue-start') cueActive = true
      if (m.type === 'cue-end') cueActive = false
      if (m.type === 'sm-start') searchDepth++
      if (m.type === 'sm-end') searchDepth--
    }
  }

  // Remaining text after all markers
  if (currentPos < text.length) {
    parts.push(renderStyledSpan(text, baseOffset, currentPos, text.length, activeHighlights, cueActive, cueRange, searchDepth > 0, false, parts.length))
  }

  return <>{parts}</>
}

/** Render a text slice with combined highlight + cue + search styling */
function renderStyledSpan(text, baseOffset, start, end, activeHighlights, cueActive, cueRange, searchActive, searchCurrent, keyIndex) {
  const slice = text.slice(start, end)
  const offset = baseOffset + start
  const hl = activeHighlights.size > 0 ? [...activeHighlights][0] : null
  const color = hl ? (HIGHLIGHT_COLORS[hl.color] || HIGHLIGHT_COLORS.yellow) : null

  // Search-match styling stacks on top of whatever else is rendered
  const searchClass = searchActive
    ? (searchCurrent ? 'bg-amber-400/80 text-black rounded-sm' : 'bg-amber-300/40 rounded-sm')
    : ''
  const searchAttrs = searchActive
    ? { 'data-search-match': 'true', ...(searchCurrent && { 'data-search-current': 'true' }) }
    : null

  // Active cue with no highlight — clickable glowing span
  if (cueActive && !hl) {
    return (
      <span
        key={`cue-${keyIndex}`}
        data-offset={offset}
        {...searchAttrs}
        className={`bg-camel/15 text-primary rounded-sm transition-colors duration-75 cursor-pointer hover:bg-camel/25 ${searchClass}`}
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
        {...searchAttrs}
        className={`rounded px-0.5 transition-all ${cueActive ? 'ring-1 ring-camel/40' : ''} ${searchClass}`}
        style={{ backgroundColor: color.bg }}
      >
        <FormattedSpan text={slice} baseOffset={offset} />
      </mark>
    )
  }

  // Search match only (no highlight, no cue)
  if (searchActive) {
    return (
      <span key={`search-${keyIndex}`} data-offset={offset} {...searchAttrs} className={searchClass}>
        <FormattedSpan text={slice} baseOffset={offset} />
      </span>
    )
  }

  // Plain text
  return (
    <span key={`plain-${keyIndex}`} data-offset={offset}>
      <FormattedSpan text={slice} baseOffset={offset} />
    </span>
  )
}
