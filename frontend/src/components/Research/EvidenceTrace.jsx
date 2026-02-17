import { useState } from 'react'
import { MarkdownContent } from '../../utils/markdown'
import CodeBlockFeed from './CodeBlockFeed'

/**
 * EvidenceTrace
 * =============
 * Collapsible panel showing the evidence chain behind an RLM-v2 response.
 * Three tabs: Evidence (stored key-value pairs), Raw Findings (pre-synthesis),
 * and Exec Log (code blocks + stdout).
 */
export default function EvidenceTrace({
  rawFindings,
  storedEvidence,
  docReads = 0,
  iterations = 0,
  codeBlocks = []
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('evidence')

  const evidenceCount = storedEvidence ? Object.keys(storedEvidence).length : 0
  const hasEvidence = evidenceCount > 0
  const hasFindings = rawFindings && rawFindings !== 'No findings collected.'
  const hasCodeBlocks = codeBlocks.length > 0

  // Nothing to show
  if (!hasEvidence && !hasFindings && !hasCodeBlocks) return null

  return (
    <div className="mt-2 rounded-lg border border-subtle/30 bg-raised/20 overflow-hidden">
      {/* Header — always visible */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-surface/30 transition-colors"
      >
        <svg
          className={`w-3 h-3 text-muted transition-transform ${isOpen ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-semibold uppercase tracking-wider text-muted">
          Evidence Trace
        </span>
        <span className="text-muted/60">
          ({docReads} reads, {evidenceCount} stored, {iterations} iterations)
        </span>
      </button>

      {/* Expanded content */}
      {isOpen && (
        <div className="border-t border-subtle/20">
          {/* Tab bar */}
          <div className="flex border-b border-subtle/20">
            {hasEvidence && (
              <TabButton
                label="Evidence"
                count={evidenceCount}
                isActive={activeTab === 'evidence'}
                onClick={() => setActiveTab('evidence')}
              />
            )}
            {hasFindings && (
              <TabButton
                label="Raw Findings"
                isActive={activeTab === 'findings'}
                onClick={() => setActiveTab('findings')}
              />
            )}
            {hasCodeBlocks && (
              <TabButton
                label="Exec Log"
                count={codeBlocks.length}
                isActive={activeTab === 'exec'}
                onClick={() => setActiveTab('exec')}
              />
            )}
          </div>

          {/* Tab content */}
          <div className="max-h-96 overflow-y-auto">
            {activeTab === 'evidence' && hasEvidence && (
              <EvidenceTab evidence={storedEvidence} />
            )}
            {activeTab === 'findings' && hasFindings && (
              <FindingsTab rawFindings={rawFindings} />
            )}
            {activeTab === 'exec' && hasCodeBlocks && (
              <div className="p-3">
                <CodeBlockFeed codeBlocks={codeBlocks} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function TabButton({ label, count, isActive, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`
        px-3 py-2 text-xs font-medium transition-colors
        ${isActive
          ? 'text-camel border-b-2 border-camel'
          : 'text-muted hover:text-secondary'
        }
      `}
    >
      {label}
      {count != null && (
        <span className="ml-1 text-muted/60">({count})</span>
      )}
    </button>
  )
}

/**
 * EvidenceTab — stored key-value pairs from store() calls
 */
function EvidenceTab({ evidence }) {
  return (
    <div className="p-3 space-y-2">
      {Object.entries(evidence).map(([key, value]) => (
        <EvidenceCard key={key} storeKey={key} value={value} />
      ))}
    </div>
  )
}

function EvidenceCard({ storeKey, value }) {
  const [expanded, setExpanded] = useState(false)

  // Value could be a string, object, or array
  const isSimple = typeof value === 'string' || typeof value === 'number'
  const displayValue = isSimple ? String(value) : JSON.stringify(value, null, 2)
  const isLong = displayValue.length > 200

  return (
    <div className="rounded border border-subtle/30 bg-raised/30">
      <div
        onClick={() => isLong && setExpanded(!expanded)}
        className={`flex items-start gap-2 px-3 py-2 ${isLong ? 'cursor-pointer hover:bg-white/5' : ''}`}
      >
        <span className="text-xs font-mono text-camel/80 font-semibold flex-shrink-0 pt-0.5">
          {storeKey}
        </span>
        <pre className={`text-xs font-mono text-secondary/80 whitespace-pre-wrap flex-1 ${!expanded && isLong ? 'line-clamp-3' : ''}`}>
          {displayValue}
        </pre>
        {isLong && (
          <svg
            className={`w-3 h-3 text-muted flex-shrink-0 mt-1 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </div>
    </div>
  )
}

/**
 * FindingsTab — raw FINAL_ANSWER before synthesis
 */
function FindingsTab({ rawFindings }) {
  return (
    <div className="p-4">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-muted">
        Pre-synthesis findings (ground truth)
      </div>
      <div className="text-sm text-secondary/80 leading-relaxed">
        <MarkdownContent content={rawFindings} inheritFontSize />
      </div>
    </div>
  )
}
