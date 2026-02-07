import { useState } from 'react'

/**
 * ToolCallFeed
 * ============
 * Shows tool calls as they execute in real-time.
 * Expandable to show input/output details.
 */
export default function ToolCallFeed({ toolCalls = [] }) {
  const [expandedId, setExpandedId] = useState(null)

  if (toolCalls.length === 0) return null

  // Group by status for better visualization
  const running = toolCalls.filter(tc => tc.status === 'running')
  const completed = toolCalls.filter(tc => tc.status !== 'running')

  return (
    <div className="p-3 rounded-lg bg-raised/30 border border-subtle/30">
      <div className="flex items-center gap-2 mb-2">
        <svg className="w-4 h-4 text-camel" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <span className="text-xs font-semibold uppercase tracking-wider text-camel">
          Tool Calls
        </span>
        <span className="text-xs text-muted">
          ({toolCalls.length} total)
        </span>
      </div>

      <div className="space-y-1 max-h-60 overflow-y-auto">
        {/* Currently running */}
        {running.map((tc) => (
          <ToolCallRow
            key={tc.id}
            toolCall={tc}
            isExpanded={expandedId === tc.id}
            onToggle={() => setExpandedId(expandedId === tc.id ? null : tc.id)}
          />
        ))}

        {/* Completed (most recent first, limited) */}
        {completed.slice(-10).reverse().map((tc) => (
          <ToolCallRow
            key={tc.id}
            toolCall={tc}
            isExpanded={expandedId === tc.id}
            onToggle={() => setExpandedId(expandedId === tc.id ? null : tc.id)}
          />
        ))}

        {/* Show count if more than displayed */}
        {completed.length > 10 && (
          <div className="text-xs text-muted text-center py-1">
            + {completed.length - 10} earlier tool calls
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * ToolCallRow
 * ===========
 * Single tool call with expand/collapse.
 */
function ToolCallRow({ toolCall, isExpanded, onToggle }) {
  const { name, input, status, preview, startTime, endTime } = toolCall

  // Calculate duration if complete
  const duration = endTime && startTime ? endTime - startTime : null

  // Status indicator colors
  const statusColors = {
    running: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
    success: 'text-green-400 bg-green-400/10 border-green-400/30',
    error: 'text-terra bg-terra/10 border-terra/30'
  }

  // Tool name formatting
  const formatToolName = (name) => {
    return name
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase())
  }

  // Tool category icons
  const getToolIcon = (name) => {
    if (name.includes('search') || name.includes('find')) return '🔍'
    if (name.includes('read') || name.includes('peek')) return '📖'
    if (name.includes('library')) return '📚'
    if (name.includes('session')) return '📋'
    if (name.includes('toc') || name.includes('section')) return '📑'
    if (name.includes('highlight') || name.includes('note')) return '✏️'
    if (name.includes('store') || name.includes('recall')) return '💾'
    if (name.includes('summarize') || name.includes('extract')) return '🧠'
    return '⚙️'
  }

  return (
    <div className={`rounded border ${statusColors[status]}`}>
      {/* Header row */}
      <div
        onClick={onToggle}
        className="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-white/5 transition-colors"
      >
        {/* Status indicator */}
        {status === 'running' ? (
          <svg className="w-3 h-3 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        ) : status === 'success' ? (
          <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        )}

        {/* Tool icon and name */}
        <span className="text-xs">{getToolIcon(name)}</span>
        <span className="text-xs font-mono font-medium flex-1 truncate">
          {formatToolName(name)}
        </span>

        {/* Duration */}
        {duration && (
          <span className="text-xs text-muted font-mono">
            {duration}ms
          </span>
        )}

        {/* Expand indicator */}
        <svg
          className={`w-3 h-3 text-muted transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-2 pb-2 space-y-2 border-t border-subtle/20">
          {/* Input */}
          {input && Object.keys(input).length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
                Input
              </div>
              <pre className="text-xs font-mono text-secondary bg-base/50 rounded p-2 overflow-x-auto">
                {JSON.stringify(input, null, 2)}
              </pre>
            </div>
          )}

          {/* Preview */}
          {preview && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
                Result
              </div>
              <div className="text-xs text-secondary bg-base/50 rounded p-2 break-words">
                {preview}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
