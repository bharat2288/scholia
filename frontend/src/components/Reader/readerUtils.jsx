/**
 * Shared utilities and constants for Reader components.
 * Extracted to avoid circular dependencies between Reader sub-modules.
 */

// Highlight colors with their display values
// Colors chosen to be visible on dark backgrounds with good contrast
// Higher opacity (0.5) for better visibility on dark theme
export const HIGHLIGHT_COLORS = {
  yellow: { name: 'Yellow', bg: 'rgba(250, 204, 21, 0.5)', border: 'rgb(250, 204, 21)', meaning: 'Important' },
  blue: { name: 'Blue', bg: 'rgba(96, 165, 250, 0.5)', border: 'rgb(96, 165, 250)', meaning: 'Definition' },
  green: { name: 'Green', bg: 'rgba(74, 222, 128, 0.5)', border: 'rgb(74, 222, 128)', meaning: 'Evidence' },
  pink: { name: 'Pink', bg: 'rgba(244, 114, 182, 0.5)', border: 'rgb(244, 114, 182)', meaning: 'Question' },
}

export const DEFAULT_HIGHLIGHT_COLOR = 'yellow'

/**
 * Strip markdown formatting from section titles.
 * Headings are already styled, so inline formatting is redundant.
 */
export function cleanSectionTitle(title) {
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
export function slugify(title) {
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
export function scrollToAnchor(anchor) {
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

/**
 * Clean text for copying - remove markdown/HTML artifacts
 */
export function cleanTextForCopy(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')  // Remove bold markers
    .replace(/\*([^*]+)\*/g, '$1')     // Remove italic markers
    .replace(/<sup>(.*?)<\/sup>/g, '$1')  // Remove sup tags
    .replace(/<sub>(.*?)<\/sub>/g, '$1')  // Remove sub tags
    .replace(/\$([^$]+)\$/g, '$1')     // Remove inline math markers
}

/**
 * Copy icon component for reuse
 */
export function CopyIcon({ className = "w-4 h-4" }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
    </svg>
  )
}
