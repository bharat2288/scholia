/**
 * Shared Markdown Renderer
 * ========================
 * Renders markdown content with support for:
 * - Headers (#, ##, ###)
 * - Bold (**text** or __text__)
 * - Italic (*text* or _text_)
 * - Inline code (`code`)
 * - Code blocks (```)
 * - Lists (- or *)
 * - Numbered lists (1., 2., etc.)
 * - [[refs]] as clickable links
 * - ##tags stripped (shown separately)
 */

import { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Hook to get the ref navigation function
 */
export function useRefNavigation() {
  const navigate = useNavigate()

  return useCallback(async (refContent) => {
    try {
      const { findGluonByContent } = await import('../hooks/useApi')
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
  }, [navigate])
}

/**
 * Render inline elements: bold, italic, code, [[refs]]
 */
export function renderInlineElements(text, navigateToRef, keyPrefix = '') {
  if (!text) return text

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
    // Check for [TIMESTAMP HH:MM:SS] — clickable link that seeks YouTube player
    if (text.slice(i, i + 11) === '[TIMESTAMP ') {
      const endTs = text.indexOf(']', i + 11)
      if (endTs !== -1) {
        const tsValue = text.slice(i + 11, endTs).trim()  // "HH:MM:SS" or "MM:SS"
        const parts = tsValue.split(':').map(Number)
        let totalSeconds = 0
        if (parts.length === 3) totalSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        else if (parts.length === 2) totalSeconds = parts[0] * 60 + parts[1]

        flushBuffer()
        elements.push(
          <button
            key={`${keyPrefix}-ts-${key++}`}
            onClick={(e) => {
              e.stopPropagation()
              // Seek YouTube player via global ref (set in Reader's YouTubePlayer)
              if (window.__scholiaYouTubePlayer?.seekTo) {
                window.__scholiaYouTubePlayer.seekTo(totalSeconds, true)
              }
            }}
            className="text-camel bg-camel/10 px-1.5 py-0.5 rounded text-xs font-mono hover:bg-camel/20 transition-colors cursor-pointer"
            title={`Jump to ${tsValue}`}
          >
            {tsValue}
          </button>
        )
        i = endTs + 1
        continue
      }
    }

    // Check for [[ref]]
    if (text.slice(i, i + 2) === '[[') {
      const endRef = text.indexOf(']]', i + 2)
      if (endRef !== -1) {
        flushBuffer()
        const refContent = text.slice(i + 2, endRef)
        elements.push(
          <span
            key={`${keyPrefix}-ref-${key++}`}
            onClick={(e) => { e.stopPropagation(); navigateToRef(refContent); }}
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
}

/**
 * Full markdown renderer component
 * Use for gluon view and full note display
 *
 * @param {string} content - Markdown content to render
 * @param {string} className - Additional CSS classes
 * @param {function} navigateToRef - Function to handle [[ref]] clicks
 * @param {boolean} inheritFontSize - If true, uses 'inherit' for font sizes (for zoom control)
 */
export function MarkdownContent({ content, className = "", navigateToRef, inheritFontSize = false }) {
  const renderedContent = useMemo(() => {
    if (!content) return null

    // Strip ##tags from content
    const textWithoutTags = content.replace(/\s*##\w+/g, '').trim()

    const lines = textWithoutTags.split('\n')
    const elements = []
    let inCodeBlock = false
    let codeBlockContent = []
    let key = 0

    // Font size classes - when inheritFontSize is true, we don't set explicit sizes
    const textClass = inheritFontSize ? '' : 'text-sm'
    const codeClass = inheritFontSize ? 'text-[0.75em]' : 'text-[11px]'

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i]

      // Code block start/end
      if (line.startsWith('```')) {
        if (inCodeBlock) {
          elements.push(
            <pre key={`code-${key++}`} className={`bg-base rounded p-2 my-2 overflow-x-auto ${codeClass} font-mono text-secondary`}>
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
        elements.push(<h4 key={key++} className={`font-semibold text-primary mt-2 mb-1 ${textClass}`}>{renderInlineElements(h3Match[1], navigateToRef, `h4-${i}`)}</h4>)
        continue
      }
      const h2Match = line.match(/^##\s*(.+)/)
      if (h2Match) {
        elements.push(<h3 key={key++} className={`font-semibold text-primary mt-2 mb-1 ${textClass}`}>{renderInlineElements(h2Match[1], navigateToRef, `h3-${i}`)}</h3>)
        continue
      }
      const h1Match = line.match(/^#\s*(.+)/)
      if (h1Match) {
        elements.push(<h2 key={key++} className="font-bold text-primary mt-2 mb-1">{renderInlineElements(h1Match[1], navigateToRef, `h2-${i}`)}</h2>)
        continue
      }

      // List items
      if (line.match(/^[\-\*]\s/)) {
        elements.push(
          <div key={key++} className="flex gap-2 my-0.5">
            <span className="text-muted">•</span>
            <span className={textClass}>{renderInlineElements(line.slice(2), navigateToRef, `li-${i}`)}</span>
          </div>
        )
        continue
      }

      // Numbered list items
      if (line.match(/^\d+\.\s/)) {
        const num = line.match(/^(\d+)\./)[1]
        elements.push(
          <div key={key++} className="flex gap-2 my-0.5">
            <span className={`text-muted w-4 ${textClass}`}>{num}.</span>
            <span className={textClass}>{renderInlineElements(line.replace(/^\d+\.\s/, ''), navigateToRef, `ol-${i}`)}</span>
          </div>
        )
        continue
      }

      // Blockquote lines — collect consecutive > lines into one block
      if (line.match(/^>\s?/)) {
        const quoteLines = []
        let j = i
        while (j < lines.length && lines[j].match(/^>\s?/)) {
          quoteLines.push(lines[j].replace(/^>\s?/, ''))
          j++
        }
        elements.push(
          <blockquote
            key={key++}
            className="border-l-2 border-camel/40 pl-4 my-2 italic text-secondary/80"
          >
            {quoteLines.map((ql, qi) => (
              <p key={qi} className={`${textClass} my-0.5`}>
                {renderInlineElements(ql, navigateToRef, `bq-${i}-${qi}`)}
              </p>
            ))}
          </blockquote>
        )
        i = j - 1  // -1 because the for loop will increment
        continue
      }

      // Horizontal rule (---, ***, ___)
      if (line.trim().match(/^[-*_]{3,}$/)) {
        elements.push(<hr key={key++} className="border-subtle my-4" />)
        continue
      }

      // Empty line
      if (line.trim() === '') {
        elements.push(<div key={key++} className="h-2" />)
        continue
      }

      // Regular paragraph
      elements.push(<p key={key++} className={`${textClass} text-secondary my-0.5`}>{renderInlineElements(line, navigateToRef, `p-${i}`)}</p>)
    }

    return elements
  }, [content, navigateToRef, inheritFontSize])

  return (
    <div className={`text-secondary leading-relaxed ${className}`}>
      {renderedContent}
    </div>
  )
}

/**
 * Preview markdown renderer (for list views)
 * Shows truncated content with basic inline formatting
 */
export function MarkdownPreview({ content, maxLength = 200, className = "", navigateToRef }) {
  const previewContent = useMemo(() => {
    if (!content) return null

    // Strip ##tags and code blocks for preview
    let text = content
      .replace(/\s*##\w+/g, '')
      .replace(/```[\s\S]*?```/g, '[code]')
      .replace(/^#{1,3}\s*/gm, '')  // Remove header markers
      .trim()

    // Truncate
    if (text.length > maxLength) {
      text = text.slice(0, maxLength) + '...'
    }

    return renderInlineElements(text, navigateToRef, 'preview')
  }, [content, maxLength, navigateToRef])

  return (
    <span className={className || 'text-secondary'}>
      {previewContent}
    </span>
  )
}
