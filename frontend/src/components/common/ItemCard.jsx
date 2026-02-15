/**
 * Shared UI Components for Scholia
 * =================================
 * Standardized patterns for cards, type indicators, and tag chips.
 * Ensures visual consistency across Library, Knowledge, Gluon, and Reader views.
 */

import { Link } from 'react-router-dom'

// =============================================================================
// TYPE INDICATOR
// =============================================================================
// Refined type badge with minimal SVG icons + colored labels (no emoji)

const typeConfig = {
  highlight: {
    color: 'yellow',
    label: 'Highlight',
    Icon: HighlightIcon,
  },
  note: {
    color: 'blue',
    label: 'Note',
    Icon: NoteIcon,
  },
  tag: {
    color: 'pink',
    label: 'Tag',
    Icon: TagIcon,
  },
  journal_entry: {
    color: 'green',
    label: 'Journal',
    Icon: JournalIcon,
  },
}

const colorClasses = {
  yellow: {
    bg: 'bg-yellow-500/10',
    border: 'border-yellow-500/30',
    text: 'text-yellow-400',
  },
  blue: {
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    text: 'text-blue-400',
  },
  pink: {
    bg: 'bg-pink-500/10',
    border: 'border-pink-500/30',
    text: 'text-pink-400',
  },
  green: {
    bg: 'bg-green-500/10',
    border: 'border-green-500/30',
    text: 'text-green-400',
  },
}

export function TypeIndicator({ type }) {
  const config = typeConfig[type]
  if (!config) return null

  const colors = colorClasses[config.color]
  const Icon = config.Icon

  return (
    <span className={`
      inline-flex items-center gap-1.5 px-2 py-1 rounded
      border ${colors.border} ${colors.bg}
    `}>
      <Icon className={`w-3.5 h-3.5 ${colors.text}`} />
      <span className={`text-xs ${colors.text} uppercase tracking-wide font-medium`}>
        {config.label}
      </span>
    </span>
  )
}

// =============================================================================
// SVG ICONS (minimal line-art style)
// =============================================================================

function HighlightIcon({ className = "" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 113 3L7 19l-4 1 1-4L16.5 3.5z" />
    </svg>
  )
}

function NoteIcon({ className = "" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14,2 14,8 20,8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  )
}

function TagIcon({ className = "" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="4" y1="9" x2="20" y2="9" />
      <line x1="4" y1="15" x2="20" y2="15" />
      <line x1="10" y1="3" x2="8" y2="21" />
      <line x1="16" y1="3" x2="14" y2="21" />
    </svg>
  )
}

function JournalIcon({ className = "" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  )
}

// =============================================================================
// TAG CHIP
// =============================================================================
// Filled tag chips - confident accent color with contrasting text
// No borders, no faint outlines - committed design choices

export function TagChip({
  tag,
  size = 'sm', // 'sm' for inline, 'md' for standalone (Tags panel)
  showCount = false,
  onClick,
  to, // If provided, renders as Link
}) {
  // Size-specific classes
  const sizeClasses = {
    sm: 'px-2.5 py-0.5 text-xs gap-1.5',
    md: 'px-3 py-1 text-sm gap-2',
  }

  // Filled terracotta with dark text - confident, no borders
  const baseClasses = `
    inline-flex items-center rounded-full
    bg-terra text-base font-medium
    hover:bg-terra/90
    transition-colors cursor-pointer
    ${sizeClasses[size]}
  `

  const tagName = typeof tag === 'string' ? tag : tag.content || tag.name

  const content = (
    <>
      <span>{tagName}</span>
      {showCount && tag.usage_count !== undefined && (
        <span className="text-xs opacity-80 bg-black/20 px-1.5 py-0.5 rounded-full">
          {tag.usage_count}
        </span>
      )}
    </>
  )

  if (to) {
    return (
      <Link to={to} className={baseClasses} onClick={onClick}>
        {content}
      </Link>
    )
  }

  return (
    <button type="button" className={baseClasses} onClick={onClick}>
      {content}
    </button>
  )
}

// =============================================================================
// REF CHIP
// =============================================================================
// Standardized [[reference]] styling

export function RefChip({ content, onClick, to }) {
  const baseClasses = `
    inline text-blue-400 bg-blue-400/10 px-1 rounded
    hover:bg-blue-400/20 transition-colors cursor-pointer
  `

  if (to) {
    return (
      <Link to={to} className={baseClasses} onClick={onClick}>
        {content}
      </Link>
    )
  }

  return (
    <button type="button" className={baseClasses} onClick={onClick}>
      {content}
    </button>
  )
}

// =============================================================================
// HIGHLIGHT DOT
// =============================================================================
// Color indicator for highlights in lists

const highlightColorMap = {
  yellow: 'bg-yellow-400',
  blue: 'bg-blue-400',
  green: 'bg-green-400',
  pink: 'bg-pink-400',
}

export function HighlightDot({ color, size = 'sm' }) {
  const sizeClasses = {
    sm: 'w-2 h-2',
    md: 'w-3 h-3',
  }

  return (
    <span
      className={`
        ${sizeClasses[size]} rounded-full flex-shrink-0
        ${highlightColorMap[color] || 'bg-yellow-400'}
      `}
    />
  )
}

// =============================================================================
// CARD STYLE CONSTANTS (for consistent className usage)
// =============================================================================

export const cardStyles = {
  // Base card with hover energy
  base: `
    group bg-surface rounded-lg p-4
    border border-transparent
    hover:border-camel/40
    hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)]
    transition-all duration-200
    shadow-lg cursor-pointer
  `,

  // Selected state addition
  selected: 'border-l-[3px] border-l-camel',

  // Unselected (for when selection state matters)
  unselected: 'border-l-[3px] border-l-transparent',
}
