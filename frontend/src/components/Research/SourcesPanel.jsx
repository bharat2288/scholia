import { useState } from 'react'
import { useSources } from '../../hooks/useApi'
import { useAddSessionSource, useRemoveSessionSource } from '../../hooks/useRLM'

/**
 * SourcesPanel
 * ============
 * Horizontal panel showing sources in the session.
 * Supports adding from library and removing.
 */
export default function SourcesPanel({ sessionId, sources = [] }) {
  const [showAddModal, setShowAddModal] = useState(false)
  const removeSource = useRemoveSessionSource()

  const handleRemove = async (sourceId) => {
    try {
      await removeSource.mutateAsync({ sessionId, sourceId })
    } catch (err) {
      console.error('Failed to remove source:', err)
    }
  }

  return (
    <div className="flex-shrink-0 border-b border-subtle/30 bg-surface/10">
      <div className="px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-tertiary">
            Sources
          </span>

          {/* Source chips */}
          <div className="flex-1 flex items-center gap-2 overflow-x-auto">
            {sources.length === 0 ? (
              <span className="text-sm text-muted">No sources added yet</span>
            ) : (
              sources.map((source) => (
                <SourceChip
                  key={source.id}
                  source={source}
                  onRemove={() => handleRemove(source.id)}
                />
              ))
            )}
          </div>

          {/* Add button */}
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-camel bg-camel/10 border border-camel/30 rounded-md hover:bg-camel/20 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Source
          </button>
        </div>
      </div>

      {/* Add source modal */}
      {showAddModal && (
        <AddSourceModal
          sessionId={sessionId}
          existingSourceIds={sources.map(s => s.id)}
          onClose={() => setShowAddModal(false)}
        />
      )}
    </div>
  )
}

/**
 * SourceChip
 * ==========
 * Compact chip showing a source in the session.
 */
function SourceChip({ source, onRemove }) {
  const typeIcons = {
    document: '📄',
    web: '🌐',
    thread: '𝕏',
    video: '▶'
  }

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-raised/50 border border-subtle/30 rounded-full group">
      <span className="text-xs">{typeIcons[source.source_type] || '📄'}</span>
      <span className="text-sm text-secondary truncate max-w-[200px]">
        {source.title}
      </span>
      {source.year && (
        <span className="text-xs text-muted">({source.year})</span>
      )}
      <button
        onClick={onRemove}
        className="p-0.5 text-tertiary opacity-0 group-hover:opacity-100 hover:text-terra transition-all"
        title="Remove from session"
      >
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

/**
 * AddSourceModal
 * ==============
 * Modal for adding sources from the library to a session.
 */
function AddSourceModal({ sessionId, existingSourceIds = [], onClose }) {
  const { data: allSources = [], isLoading } = useSources()
  const [search, setSearch] = useState('')
  const addSource = useAddSessionSource()

  // Filter out already-added sources and apply search
  const availableSources = allSources.filter(source => {
    if (existingSourceIds.includes(source.id)) return false
    if (search) {
      const query = search.toLowerCase()
      return (
        source.title?.toLowerCase().includes(query) ||
        source.author_display?.toLowerCase().includes(query)
      )
    }
    return true
  })

  const handleAdd = async (sourceId) => {
    try {
      await addSource.mutateAsync({ sessionId, sourceId })
    } catch (err) {
      console.error('Failed to add source:', err)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-lg mx-4 bg-surface border border-subtle/50 rounded-lg shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-subtle/30">
          <h3 className="text-lg font-medium text-primary">Add Sources</h3>
          <button
            onClick={onClose}
            className="p-1 text-tertiary hover:text-primary transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Search */}
        <div className="px-6 py-3 border-b border-subtle/30">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search library..."
            autoFocus
            className="w-full px-3 py-2 text-sm bg-base border border-subtle/50 rounded-md text-primary placeholder-muted focus:outline-none focus:border-camel/50"
          />
        </div>

        {/* Source list */}
        <div className="max-h-80 overflow-y-auto">
          {isLoading ? (
            <div className="p-6 text-center text-tertiary">Loading...</div>
          ) : availableSources.length === 0 ? (
            <div className="p-6 text-center text-tertiary">
              {search ? 'No matching sources' : 'All sources already added'}
            </div>
          ) : (
            <div className="p-2">
              {availableSources.slice(0, 50).map((source) => (
                <div
                  key={source.id}
                  onClick={() => handleAdd(source.id)}
                  className="p-3 rounded-lg cursor-pointer hover:bg-raised/50 transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <h4 className="text-sm font-medium text-secondary truncate">
                        {source.title}
                      </h4>
                      <div className="mt-0.5 text-xs text-tertiary">
                        {source.author_display && <span>{source.author_display}</span>}
                        {source.year && <span> ({source.year})</span>}
                      </div>
                    </div>
                    <span className="ml-2 text-xs px-2 py-0.5 rounded bg-raised text-muted">
                      {source.source_type}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-subtle/30 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-secondary hover:text-primary transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  )
}
