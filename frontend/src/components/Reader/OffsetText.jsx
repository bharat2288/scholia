/**
 * Render text with character offset tracking and highlight/cue overlay.
 * Uses a marker-based system to split text at highlight and active-cue boundaries,
 * rendering each slice with combined styling.
 */
import { useMemo } from 'react'
import { HIGHLIGHT_COLORS } from './readerUtils'
import { seekYouTubeVideo } from './YouTubePlayer'
import FormattedSpan from './FormattedSpan'

/**
 * Render text with character offset tracking.
 * Each span has data-offset for selection mapping.
 */
export default function OffsetText({ text, baseOffset, highlights, activeCue }) {
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
