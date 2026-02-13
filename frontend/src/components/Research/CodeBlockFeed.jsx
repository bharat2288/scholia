import { useState } from 'react'

/**
 * CodeBlockFeed
 * =============
 * Shows code execution blocks from the RLM-v2 engine in real-time.
 * Each block shows: code, stdout, stderr, duration, sub-LLM calls.
 */
export default function CodeBlockFeed({ codeBlocks = [] }) {
  const [expandedIdx, setExpandedIdx] = useState(null)

  if (codeBlocks.length === 0) return null

  // Group by iteration
  const iterations = {}
  for (const block of codeBlocks) {
    const iter = block.iteration || 1
    if (!iterations[iter]) iterations[iter] = []
    iterations[iter].push(block)
  }

  return (
    <div className="p-3 rounded-lg bg-raised/30 border border-subtle/30 space-y-3">
      <div className="flex items-center gap-2">
        <svg className="w-4 h-4 text-camel" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
        <span className="text-xs font-semibold uppercase tracking-wider text-camel">
          Code Execution
        </span>
        <span className="text-xs text-muted">
          ({codeBlocks.length} blocks)
        </span>
      </div>

      <div className="space-y-2 max-h-80 overflow-y-auto">
        {Object.entries(iterations).map(([iter, blocks]) => (
          <div key={iter}>
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
              Iteration {iter}
            </div>
            {blocks.map((block, i) => {
              const globalIdx = codeBlocks.indexOf(block)
              return (
                <CodeBlockRow
                  key={globalIdx}
                  block={block}
                  isExpanded={expandedIdx === globalIdx}
                  onToggle={() => setExpandedIdx(expandedIdx === globalIdx ? null : globalIdx)}
                />
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * CodeBlockRow
 * ============
 * Single code execution block with expand/collapse.
 */
function CodeBlockRow({ block, isExpanded, onToggle }) {
  const { code, stdout, stderr, error, duration_ms, subLlmCount, status } = block

  // Status colors
  const statusStyles = {
    running: 'text-blue-400 bg-blue-400/10 border-blue-400/30',
    success: 'text-green-400 bg-green-400/10 border-green-400/30',
    error: 'text-terra bg-terra/10 border-terra/30'
  }

  // Code preview (first line or first 60 chars)
  const codePreview = code.split('\n')[0].slice(0, 80) + (code.length > 80 ? '...' : '')

  return (
    <div className={`rounded border ${statusStyles[status] || statusStyles.running}`}>
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

        {/* Code preview */}
        <code className="text-xs font-mono flex-1 truncate opacity-80">
          {codePreview}
        </code>

        {/* Sub-LLM badge */}
        {subLlmCount > 0 && (
          <span className="text-[10px] bg-camel/20 text-camel px-1.5 py-0.5 rounded font-mono">
            {subLlmCount} sub-LLM
          </span>
        )}

        {/* Duration */}
        {duration_ms != null && (
          <span className="text-xs text-muted font-mono">
            {duration_ms > 1000 ? `${(duration_ms / 1000).toFixed(1)}s` : `${duration_ms}ms`}
          </span>
        )}

        {/* Expand indicator */}
        <svg
          className={`w-3 h-3 text-muted transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-2 pb-2 space-y-2 border-t border-subtle/20">
          {/* Full code */}
          <div className="mt-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
              Code
            </div>
            <pre className="text-xs font-mono text-secondary bg-base/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
              {code}
            </pre>
          </div>

          {/* Stdout */}
          {stdout && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
                Output
              </div>
              <pre className="text-xs font-mono text-green-400/80 bg-base/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {stdout}
              </pre>
            </div>
          )}

          {/* Stderr / Error */}
          {(stderr || error) && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-terra/80 mb-1">
                {error ? 'Error' : 'Stderr'}
              </div>
              <pre className="text-xs font-mono text-terra/80 bg-terra/5 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {error || stderr}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
