/**
 * Render text with inline markdown/HTML formatting.
 * When baseOffset is provided, each sub-element gets data-offset pointing to
 * its position in the raw text. This is critical for accurate highlight offset
 * calculation — without it, formatting markers (*, **, <sup>, etc.) that are
 * consumed during rendering cause DOM character counts to diverge from raw
 * text positions.
 */
import { seekYouTubeVideo } from './YouTubePlayer'
import { scrollToAnchor } from './readerUtils'

export default function FormattedSpan({ text, baseOffset }) {
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
