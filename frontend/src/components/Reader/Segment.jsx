/**
 * Segment rendering and content parsing for Reader.
 *
 * Segments are typed blocks (section, paragraph, timestamp, figure, code, etc.)
 * parsed from raw document content. This module handles both parsing raw text
 * into segments and rendering each segment type.
 */
import { Link } from 'react-router-dom'
import DOMPurify from 'dompurify'
import { API_BASE } from '../../config'
import { slugify, cleanSectionTitle, CopyIcon } from './readerUtils'
import { seekYouTubeVideo } from './YouTubePlayer'
import OffsetText from './OffsetText'
import FormattedSpan from './FormattedSpan'

/**
 * Parse content into segments with offset information.
 * Handles document-specific markers: [SECTION], [TIMESTAMP], [FIGURE], [PAGE], etc.
 */
export function parseContentIntoSegments(content, sections, figures, sourceId) {
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
export function parseAnalysisIntoSegments(content) {
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
export default function Segment({ segment, segmentIndex, highlights, highlightMap, onCopySection, isCopied, sourceId, activeCue, searchMatches, currentMatchStart }) {
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
      return (
        <div className="my-8 flex items-center justify-center gap-4 text-muted select-none">
          <div className="flex-1 h-px bg-elevated max-w-[100px]" />
          <span
            className="text-xs font-mono opacity-60"
            title={segment.docPage && segment.pdfPage !== segment.docPage
              ? `Page ${segment.docPage} (PDF page ${segment.pdfPage})`
              : `Page ${segment.pdfPage}`}
          >
            {segment.pageNum}
          </span>
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
                searchMatches={searchMatches}
                currentMatchStart={currentMatchStart}
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
            dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(segment.tableHtml) }}
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
                <OffsetText text={cleanLine} baseOffset={textOffset} highlights={highlights} searchMatches={searchMatches} currentMatchStart={currentMatchStart} />
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
              searchMatches={searchMatches}
              currentMatchStart={currentMatchStart}
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
