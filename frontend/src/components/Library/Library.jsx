import { useEffect, useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useSources, useHealth, useDeleteSource, useSourceGluonStats, useRefreshSources, useBatchSuggestMetadata, useUpdateSource } from '../../hooks/useApi'
import useLibraryStore from '../../stores/useLibraryStore'
import MetadataEditModal from '../common/MetadataEditModal'
import AddSourceModal from '../common/AddSourceModal'

/**
 * Library View
 * ============
 * Main view showing all sources (documents, web clips, etc.) in the library.
 * Grid layout with source cards.
 */

// Hand-drawn constellation element for Library title
function ConstellationSVG({ className = "" }) {
  return (
    <svg
      className={className}
      width="44"
      height="44"
      viewBox="0 0 44 44"
      fill="none"
      style={{ opacity: 0.45 }}
    >
      <circle cx="22" cy="8" r="4" fill="#d4a574"/>
      <circle cx="8" cy="35" r="3.5" fill="#d4a574"/>
      <circle cx="36" cy="35" r="4" fill="#d4a574"/>
      <path d="M22 12 Q19 21, 11 32" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
      <path d="M22 12 Q25 21, 33 32" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
      <path d="M12 35 Q22 37, 32 35" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
    </svg>
  )
}


/**
 * Filter Bar
 * ==========
 * Toggle chips for filtering sources by type and annotations.
 * Additive filtering: off by default, click to enable.
 */

const TYPE_CONFIG = {
  document: { label: 'Documents', icon: '📄' },
  web: { label: 'Web', icon: '🌐' },
  thread: { label: 'Threads', icon: '𝕏' },
  tweet: { label: 'Tweets', icon: '𝕏' },
  media: { label: 'Videos', icon: '▶' }
}

function FilterBar({
  allSources,
  activeSourceTypes,
  toggleSourceType,
  showWithNotes,
  setShowWithNotes,
  showWithHighlights,
  setShowWithHighlights,
  showAISkipped,
  setShowAISkipped,
  showAIEnabled,
  setShowAIEnabled,
  activeKeywords,
  toggleKeyword,
  clearFilters
}) {
  // Count sources by type (from unfiltered data)
  const typeCounts = useMemo(() => {
    const counts = {}
    allSources.forEach(s => {
      const type = s.source_type || 'document'
      counts[type] = (counts[type] || 0) + 1
    })
    return counts
  }, [allSources])

  // Count sources with annotations and AI skip status
  const annotationCounts = useMemo(() => {
    let withNotes = 0
    let withHighlights = 0
    let aiSkipped = 0
    let aiEnabled = 0
    allSources.forEach(s => {
      if ((s.note_count || 0) > 0) withNotes++
      if ((s.highlight_count || 0) > 0) withHighlights++
      if (s.metadata_skip) {
        aiSkipped++
      } else {
        aiEnabled++
      }
    })
    return { withNotes, withHighlights, aiSkipped, aiEnabled }
  }, [allSources])

  // Collect all unique keywords across sources
  const allKeywords = useMemo(() => {
    const keywordMap = new Map()
    allSources.forEach(s => {
      (s.keywords || []).forEach(kw => {
        if (!keywordMap.has(kw.id)) {
          keywordMap.set(kw.id, { ...kw, count: 0 })
        }
        keywordMap.get(kw.id).count++
      })
    })
    // Sort by count descending
    return Array.from(keywordMap.values())
      .sort((a, b) => b.count - a.count)
      .slice(0, 10) // Show top 10 keywords
  }, [allSources])

  // Only show types that exist in the library
  const availableTypes = Object.entries(TYPE_CONFIG)
    .filter(([type]) => (typeCounts[type] || 0) > 0)

  const hasActiveFilters = activeSourceTypes.length > 0 || showWithNotes || showWithHighlights || showAISkipped || showAIEnabled || activeKeywords.length > 0

  // Don't render if no sources
  if (allSources.length === 0) return null

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mb-6 pb-4 border-b border-subtle">
      {/* Source type filters */}
      <div className="flex items-center gap-2">
        <span className="text-muted text-xs uppercase tracking-wider">Type</span>
        {availableTypes.map(([type, config]) => (
          <FilterChip
            key={type}
            active={activeSourceTypes.includes(type)}
            onClick={() => toggleSourceType(type)}
            icon={config.icon}
            label={config.label}
            count={typeCounts[type]}
          />
        ))}
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-subtle" />

      {/* Annotation filters */}
      <div className="flex items-center gap-2">
        <span className="text-muted text-xs uppercase tracking-wider">Show</span>
        <FilterChip
          active={showWithNotes}
          onClick={() => setShowWithNotes(!showWithNotes)}
          icon="📝"
          label="Has Notes"
          count={annotationCounts.withNotes}
          disabled={annotationCounts.withNotes === 0}
        />
        <FilterChip
          active={showWithHighlights}
          onClick={() => setShowWithHighlights(!showWithHighlights)}
          icon="🔖"
          label="Has Highlights"
          count={annotationCounts.withHighlights}
          disabled={annotationCounts.withHighlights === 0}
        />
        <FilterChip
          active={showAIEnabled}
          onClick={() => setShowAIEnabled(!showAIEnabled)}
          icon="✨"
          label="AI Enabled"
          count={annotationCounts.aiEnabled}
          disabled={annotationCounts.aiEnabled === 0}
        />
        <FilterChip
          active={showAISkipped}
          onClick={() => setShowAISkipped(!showAISkipped)}
          icon="🚫"
          label="AI Skipped"
          count={annotationCounts.aiSkipped}
          disabled={annotationCounts.aiSkipped === 0}
        />
      </div>

      {/* Tags filter section (if there are tags) */}
      {allKeywords.length > 0 && (
        <>
          <div className="w-px h-6 bg-subtle" />
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-muted text-xs uppercase tracking-wider">Tags</span>
            {allKeywords.map(kw => (
              <FilterChip
                key={kw.id}
                active={activeKeywords.includes(kw.id)}
                onClick={() => toggleKeyword(kw.id)}
                label={kw.content}
                count={kw.count}
              />
            ))}
          </div>
        </>
      )}

      {/* Clear filters */}
      {hasActiveFilters && (
        <button
          onClick={clearFilters}
          className="text-xs text-muted hover:text-secondary transition-colors ml-auto"
        >
          Clear filters
        </button>
      )}
    </div>
  )
}


/**
 * Filter Chip
 * ===========
 * Toggle button for filter options.
 */
function FilterChip({ active, onClick, icon, label, count, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        px-3 py-1.5 rounded-full text-sm font-medium
        border transition-all duration-150
        flex items-center gap-1.5
        ${disabled
          ? 'opacity-40 cursor-not-allowed border-subtle text-muted'
          : active
            ? 'bg-camel/20 text-camel border-camel/40 shadow-sm'
            : 'bg-transparent text-tertiary border-subtle hover:border-camel/30 hover:text-secondary'
        }
      `}
    >
      {icon && <span>{icon}</span>}
      <span>{label}</span>
      {count !== undefined && (
        <span className={`text-xs ${active ? 'text-camel/70' : 'text-muted'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

export default function Library() {
  const { data, isLoading, error, refetch } = useSources()
  const { data: health } = useHealth()
  const deleteSource = useDeleteSource()
  const refreshSources = useRefreshSources()
  const {
    setDocuments, getFilteredDocuments, searchQuery, setSearch,
    activeSourceTypes, toggleSourceType,
    showWithNotes, setShowWithNotes,
    showWithHighlights, setShowWithHighlights,
    showAISkipped, setShowAISkipped,
    showAIEnabled, setShowAIEnabled,
    activeKeywords, toggleKeyword,
    viewMode, setViewMode,
    clearFilters,
    sortBy, setSortBy,
    sortOrder, toggleSortOrder
  } = useLibraryStore()
  const [deleteModal, setDeleteModal] = useState(null) // { id, title } when open
  const [editingSource, setEditingSource] = useState(null) // Source being edited
  const [refreshResult, setRefreshResult] = useState(null) // Show result after refresh
  const [showClipModal, setShowClipModal] = useState(false) // Unified clip modal
  const [showBatchMetadataModal, setShowBatchMetadataModal] = useState(false) // Batch AI metadata modal

  // Sync fetched sources to store
  useEffect(() => {
    if (data?.value) {
      setDocuments(data.value)
    } else if (Array.isArray(data)) {
      setDocuments(data)
    }
  }, [data, setDocuments])

  // Store handles both filtering AND sorting — single source of truth
  const sources = getFilteredDocuments()
  const isConnected = health?.status === 'ok'

  const handleDeleteRequest = (id, title) => {
    setDeleteModal({ id, title })
  }

  const handleDeleteConfirm = (keepGluons, deleteLocalFiles = false) => {
    if (deleteModal) {
      deleteSource.mutate({ id: deleteModal.id, keepGluons, deleteLocalFiles })
      setDeleteModal(null)
    }
  }

  const handleRefresh = () => {
    setRefreshResult(null)
    refreshSources.mutate(undefined, {
      onSuccess: (data) => {
        setRefreshResult(data)
        // Auto-hide after 5 seconds
        setTimeout(() => setRefreshResult(null), 5000)
      },
      onError: (error) => {
        setRefreshResult({ error: error.message })
        setTimeout(() => setRefreshResult(null), 5000)
      }
    })
  }

  // Quick toggle for AI skip status
  const updateSource = useUpdateSource()
  const handleToggleAISkip = (sourceId, currentValue) => {
    updateSource.mutate({
      id: sourceId,
      updates: { metadata_skip: currentValue ? 0 : 1 }
    }, {
      onSuccess: () => refetch()
    })
  }

  return (
    <div className="min-h-screen bg-base">
      {/* Header */}
      <header className="border-b border-raised px-8 py-6">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="relative">
            <h1 className="font-display text-5xl text-primary mb-1">
              Scholia
            </h1>
            {/* Hand-drawn constellation positioned to the right of title */}
            <ConstellationSVG className="absolute -top-3 -right-12" />
            <p className="text-secondary">
              Your research library
            </p>
          </div>

          {/* Search and Actions */}
          <div className="flex items-center gap-4">
            <input
              type="text"
              placeholder="Search sources..."
              value={searchQuery}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-base border border-subtle rounded-lg px-4 py-2 text-primary placeholder:text-muted focus:border-camel focus:outline-none w-64 shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
            />
            {/* Icon-only action buttons */}
            <button
              onClick={handleRefresh}
              disabled={refreshSources.isPending}
              className="p-2 bg-surface border border-subtle rounded-lg text-muted hover:text-secondary hover:border-subtle transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title="Refresh library"
            >
              <svg
                className={`w-5 h-5 ${refreshSources.isPending ? 'animate-spin' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
            <button
              onClick={() => setShowBatchMetadataModal(true)}
              disabled={sources.length === 0}
              className="p-2 bg-surface border border-subtle rounded-lg text-purple-400/70 hover:text-purple-400 hover:border-purple-400/30 hover:bg-purple-400/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              title="AI metadata suggestions"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </button>
            <button
              onClick={() => setShowClipModal(true)}
              className="p-2 bg-surface border border-subtle rounded-lg text-blue-400/70 hover:text-blue-400 hover:border-blue-400/30 hover:bg-blue-400/10 transition-all"
              title="Clip URL"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              </svg>
            </button>
            <Link
              to="/processor"
              className="p-2 bg-gradient-to-r from-camel to-terra rounded-lg text-base hover:shadow-lg hover:shadow-camel/30 transition-all hover:-translate-y-0.5"
              title="Import sources"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
            </Link>

            {/* Divider */}
            <div className="w-px h-6 bg-subtle" />

            {/* Word chip navigation */}
            <Link
              to="/knowledge"
              className="px-3 py-1.5 text-sm bg-surface border border-subtle rounded-lg text-secondary hover:text-primary hover:border-camel/50 transition-colors"
            >
              Knowledge
            </Link>
            <Link
              to="/research"
              className="px-3 py-1.5 text-sm bg-surface border border-subtle rounded-lg text-secondary hover:text-primary hover:border-camel/50 transition-colors"
            >
              Research
            </Link>
          </div>
        </div>
      </header>

      {/* Refresh Result Toast */}
      {refreshResult && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg border ${
          refreshResult.error
            ? 'bg-red-900/90 border-red-700 text-red-200'
            : 'bg-surface border-camel/50 text-primary'
        }`}>
          {refreshResult.error ? (
            <p>Refresh failed: {refreshResult.error}</p>
          ) : (
            <div className="flex flex-col gap-1">
              <p className="font-medium text-camel">Library refreshed</p>
              <p className="text-sm text-secondary">
                {refreshResult.imported_count > 0 && `${refreshResult.imported_count} imported`}
                {refreshResult.imported_count > 0 && refreshResult.updated_count > 0 && ', '}
                {refreshResult.updated_count > 0 && `${refreshResult.updated_count} upgraded`}
                {refreshResult.imported_count === 0 && refreshResult.updated_count === 0 && 'No new sources found'}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-6xl mx-auto px-8 py-8">
        {/* Filter Bar */}
        <FilterBar
          allSources={data?.value || data || []}
          activeSourceTypes={activeSourceTypes}
          toggleSourceType={toggleSourceType}
          showWithNotes={showWithNotes}
          setShowWithNotes={setShowWithNotes}
          showWithHighlights={showWithHighlights}
          setShowWithHighlights={setShowWithHighlights}
          showAISkipped={showAISkipped}
          setShowAISkipped={setShowAISkipped}
          showAIEnabled={showAIEnabled}
          setShowAIEnabled={setShowAIEnabled}
          activeKeywords={activeKeywords}
          toggleKeyword={toggleKeyword}
          clearFilters={clearFilters}
        />

        {/* Stats, Sort, and View Toggle */}
        <div className="flex items-center justify-between mb-6">
          <p className="label text-camel">
            {sources.length} Source{sources.length !== 1 ? 's' : ''}
            {(activeSourceTypes.length > 0 || showWithNotes || showWithHighlights || showAISkipped || showAIEnabled || activeKeywords.length > 0) && (
              <span className="text-muted font-normal ml-2">
                (filtered from {(data?.value || data || []).length})
              </span>
            )}
          </p>
          <div className="flex items-center gap-4">
            {/* View toggle */}
            <div className="flex items-center gap-1 bg-raised rounded-lg p-0.5">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded transition-all ${
                  viewMode === 'grid'
                    ? 'bg-surface text-camel shadow-sm'
                    : 'text-muted hover:text-secondary'
                }`}
                title="Grid view"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
                </svg>
              </button>
              <button
                onClick={() => setViewMode('row')}
                className={`p-1.5 rounded transition-all ${
                  viewMode === 'row'
                    ? 'bg-surface text-camel shadow-sm'
                    : 'text-muted hover:text-secondary'
                }`}
                title="Row view"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
            </div>

            {/* Sort dropdown + direction toggle */}
            <div className="flex items-center gap-1.5">
              <span className="text-muted text-sm">Sort:</span>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="bg-base border border-subtle rounded px-2 py-1 text-sm text-secondary focus:border-camel focus:outline-none cursor-pointer"
              >
                <option value="recent">Recently Added</option>
                <option value="updated_at">Recently Modified</option>
                <option value="title">Title</option>
                <option value="author">Author</option>
                <option value="year">Year</option>
                <option value="annotated">Most Annotated</option>
              </select>
              <button
                onClick={toggleSortOrder}
                className="p-1.5 rounded text-muted hover:text-secondary transition-all"
                title={sortOrder === 'asc' ? 'Ascending — click to reverse' : 'Descending — click to reverse'}
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  {sortOrder === 'asc' ? (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                  ) : (
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  )}
                </svg>
              </button>
            </div>
          </div>
        </div>

        {/* Loading State */}
        {isLoading && (
          <div className="text-center py-12">
            <p className="text-secondary">Loading library...</p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-900/20 border border-red-800 rounded-lg p-4 mb-6">
            <p className="text-red-400">Failed to load sources: {error.message}</p>
          </div>
        )}

        {/* Empty State */}
        {!isLoading && sources.length === 0 && (
          <div className="bg-surface rounded-lg p-12 text-center border border-subtle shadow-lg">
            <p className="text-secondary mb-2">No sources yet</p>
            <p className="text-muted text-sm">
              Import documents from Processor or drop files here
            </p>
          </div>
        )}

        {/* Source Grid or Row View */}
        {sources.length > 0 && viewMode === 'grid' && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sources.map((source) => (
              <SourceCard
                key={source.id}
                source={source}
                onDeleteRequest={handleDeleteRequest}
                onEditRequest={setEditingSource}
                onKeywordClick={toggleKeyword}
                onToggleAISkip={handleToggleAISkip}
                activeKeywords={activeKeywords}
              />
            ))}
          </div>
        )}

        {/* Row View */}
        {sources.length > 0 && viewMode === 'row' && (
          <div className="flex flex-col gap-2">
            {sources.map((source) => (
              <SourceRow
                key={source.id}
                source={source}
                onDeleteRequest={handleDeleteRequest}
                onEditRequest={setEditingSource}
                onKeywordClick={toggleKeyword}
                onToggleAISkip={handleToggleAISkip}
                activeKeywords={activeKeywords}
              />
            ))}
          </div>
        )}
      </main>

      {/* Delete Confirmation Modal */}
      {deleteModal && (
        <DeleteSourceModal
          sourceId={deleteModal.id}
          sourceTitle={deleteModal.title}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setDeleteModal(null)}
        />
      )}

      {/* Metadata Edit Modal */}
      {editingSource && (
        <MetadataEditModal
          key={editingSource.id}
          sourceId={editingSource.id}
          sourceType={editingSource.source_type || 'document'}
          documentData={{
            ...editingSource,
            // Map author_display to author for the form
            author: editingSource.author_display || editingSource.author || '',
            // Flatten metadata fields to top level
            ...(editingSource.metadata || {}),
          }}
          onClose={() => {
            setEditingSource(null)
            refetch() // Refresh source list to show updated metadata
          }}
        />
      )}

      {/* Unified Clip Modal */}
      {showClipModal && (
        <AddSourceModal
          onClose={() => setShowClipModal(false)}
          onSuccess={() => refetch()}
        />
      )}

      {/* Batch Metadata Suggestion Modal */}
      {showBatchMetadataModal && (
        <BatchMetadataSuggestionModal
          sources={sources}
          onClose={() => setShowBatchMetadataModal(false)}
          onSuccess={() => refetch()}
        />
      )}

      {/* Status Bar */}
      <footer className="fixed bottom-0 left-0 right-0 bg-surface border-t border-subtle px-4 py-2">
        <div className="max-w-6xl mx-auto flex justify-between items-center text-sm">
          <span className="text-muted">
            Backend:{' '}
            <span className={isConnected ? 'text-green-500' : 'text-red-500'}>
              ●
            </span>{' '}
            {isConnected ? 'Connected' : 'Disconnected'}
          </span>
          <span className="text-tertiary">
            Scholia v0.1.0
          </span>
        </div>
      </footer>
    </div>
  )
}


/**
 * Source Type Chip
 * ================
 * Subtle colored chip using design system colors (camel/terra accents, elevation scale)
 */
const SOURCE_TYPE_STYLES = {
  document: {
    label: 'Document',
    bg: 'bg-elevated',
    text: 'text-secondary'
  },
  web: {
    label: 'Web',
    bg: 'bg-[#d4a574]/20',  // camel at 20%
    text: 'text-[#d4a574]'
  },
  thread: {
    label: '𝕏 Thread',
    bg: 'bg-[#1d9bf0]/20',  // Twitter/X blue at 20%
    text: 'text-[#1d9bf0]'
  },
  tweet: {
    label: '𝕏 Tweet',
    bg: 'bg-[#1d9bf0]/20',  // Twitter/X blue at 20%
    text: 'text-[#1d9bf0]'
  },
  media: {
    label: '▶ Video',
    bg: 'bg-[#ff0000]/20',   // YouTube red at 20%
    text: 'text-[#ff0000]'
  },
  default: {
    label: 'Source',
    bg: 'bg-elevated',
    text: 'text-muted'
  }
}

function SourceTypeChip({ type }) {
  const style = SOURCE_TYPE_STYLES[type] || SOURCE_TYPE_STYLES.default
  const label = style.label || type || 'Source'

  return (
    <span className={`
      inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider
      ${style.bg} ${style.text}
    `}>
      {label}
    </span>
  )
}


/**
 * Keyword Chip
 * ============
 * Small clickable chip for displaying keywords on source cards.
 */
function KeywordChip({ keyword, isActive, onClick }) {
  const handleClick = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onClick(keyword.id)
  }

  return (
    <button
      onClick={handleClick}
      className={`
        px-2 py-0.5 rounded text-[10px] font-medium transition-all
        ${isActive
          ? 'bg-camel/30 text-camel border border-camel/50'
          : 'bg-camel/10 text-camel/60 hover:bg-camel/20 hover:text-camel/80 border border-camel/15'
        }
      `}
      title={`Filter by: ${keyword.content}`}
    >
      {keyword.content}
    </button>
  )
}


/**
 * Source Card
 * ===========
 * Card displaying a single source (document, web clip, etc.) in the library grid.
 */
function SourceCard({ source, onDeleteRequest, onEditRequest, onKeywordClick, onToggleAISkip, activeKeywords = [] }) {
  const { title, author_display, year, source_type, keywords = [], metadata_skip, authors = [] } = source

  const handleDelete = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onDeleteRequest(source.id, title)
  }

  const handleEdit = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onEditRequest(source)
  }

  const handleAISkipToggle = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onToggleAISkip(source.id, metadata_skip)
  }

  // Show max 3 keywords on card
  const displayKeywords = keywords.slice(0, 3)
  const hasMoreKeywords = keywords.length > 3

  return (
    <div className="group relative bg-surface rounded-lg p-5 border border-transparent shadow-lg hover:border-camel/40 hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)] transition-all duration-200">
      {/* Action buttons */}
      <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {/* AI Skip toggle */}
        <button
          onClick={handleAISkipToggle}
          className={`p-1.5 rounded transition-all ${
            metadata_skip
              ? 'text-purple-400 bg-purple-400/10 hover:bg-purple-400/20'
              : 'text-muted hover:text-purple-400 hover:bg-purple-400/10'
          }`}
          title={metadata_skip ? 'AI suggestions disabled - click to enable' : 'AI suggestions enabled - click to disable'}
        >
          {metadata_skip ? (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          )}
        </button>
        {/* Edit button */}
        <button
          onClick={handleEdit}
          className="p-1.5 rounded transition-all text-muted hover:text-camel hover:bg-camel/10"
          title="Edit metadata"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
        </button>
        {/* Delete button */}
        <button
          onClick={handleDelete}
          className="p-1.5 rounded transition-all text-muted hover:text-red-400 hover:bg-red-900/30"
          title="Delete source"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </div>

      <Link to={`/read/${source.id}`} className="block">
        {/* Type chip + year */}
        <div className="flex items-center justify-between mb-3 pr-8">
          <SourceTypeChip type={source_type} />
          {year && (
            <span className="text-tertiary text-sm">{year}</span>
          )}
        </div>

        {/* Title */}
        <h3 className="text-primary font-medium mb-2 group-hover:text-camel transition-colors line-clamp-2">
          {title}
        </h3>

        {/* Author - linked authors are clickable */}
        {(authors.length > 0 || author_display) && (
          <p className="text-secondary text-sm line-clamp-1 mb-2">
            {authors.length > 0 ? (
              authors.map((author, idx) => (
                <span key={author.id}>
                  {idx > 0 && '; '}
                  <Link
                    to={`/gluon/${author.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="text-camel/80 hover:text-camel hover:underline transition-colors"
                  >
                    {author.content}
                  </Link>
                </span>
              ))
            ) : (
              author_display
            )}
          </p>
        )}

        {/* Keywords */}
        {displayKeywords.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 mt-2">
            {displayKeywords.map(kw => (
              <KeywordChip
                key={kw.id}
                keyword={kw}
                isActive={activeKeywords.includes(kw.id)}
                onClick={onKeywordClick}
              />
            ))}
            {hasMoreKeywords && (
              <span className="text-[10px] text-muted">+{keywords.length - 3}</span>
            )}
          </div>
        )}
      </Link>
    </div>
  )
}


/**
 * Source Row
 * ==========
 * Row displaying a single source in list/detail view.
 */
function SourceRow({ source, onDeleteRequest, onEditRequest, onKeywordClick, onToggleAISkip, activeKeywords = [] }) {
  const { title, author_display, year, source_type, keywords = [], note_count = 0, highlight_count = 0, metadata_skip, authors = [] } = source

  const handleDelete = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onDeleteRequest(source.id, title)
  }

  const handleEdit = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onEditRequest(source)
  }

  const handleAISkipToggle = (e) => {
    e.preventDefault()
    e.stopPropagation()
    onToggleAISkip(source.id, metadata_skip)
  }

  return (
    <div className="group flex items-center gap-4 bg-surface rounded-lg px-4 py-3 border border-transparent hover:border-camel/40 transition-all">
      {/* Type chip */}
      <div className="flex-shrink-0 w-20">
        <SourceTypeChip type={source_type} />
      </div>

      {/* Title and Author */}
      <div className="flex-1 min-w-0">
        <Link to={`/read/${source.id}`}>
          <h3 className="text-primary font-medium group-hover:text-camel transition-colors truncate">
            {title}
          </h3>
        </Link>
        {(authors.length > 0 || author_display) && (
          <p className="text-secondary text-sm truncate">
            {authors.length > 0 ? (
              authors.map((author, idx) => (
                <span key={author.id}>
                  {idx > 0 && '; '}
                  <Link
                    to={`/gluon/${author.id}`}
                    className="text-camel/80 hover:text-camel hover:underline transition-colors"
                  >
                    {author.content}
                  </Link>
                </span>
              ))
            ) : (
              author_display
            )}
          </p>
        )}
      </div>

      {/* Keywords */}
      <div className="flex-shrink-0 flex flex-wrap gap-1 max-w-xs">
        {keywords.slice(0, 4).map(kw => (
          <KeywordChip
            key={kw.id}
            keyword={kw}
            isActive={activeKeywords.includes(kw.id)}
            onClick={onKeywordClick}
          />
        ))}
        {keywords.length > 4 && (
          <span className="text-[10px] text-muted self-center">+{keywords.length - 4}</span>
        )}
      </div>

      {/* Year */}
      <div className="flex-shrink-0 w-12 text-right">
        {year && (
          <span className="text-tertiary text-sm">{year}</span>
        )}
      </div>

      {/* Annotation counts */}
      <div className="flex-shrink-0 flex items-center gap-2 w-20 justify-end">
        {highlight_count > 0 && (
          <span className="text-xs text-yellow-400/70" title={`${highlight_count} highlights`}>
            🔖 {highlight_count}
          </span>
        )}
        {note_count > 0 && (
          <span className="text-xs text-blue-400/70" title={`${note_count} notes`}>
            📝 {note_count}
          </span>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex-shrink-0 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {/* AI Skip toggle */}
        <button
          onClick={handleAISkipToggle}
          className={`p-1.5 rounded transition-all ${
            metadata_skip
              ? 'text-purple-400 bg-purple-400/10 hover:bg-purple-400/20'
              : 'text-muted hover:text-purple-400 hover:bg-purple-400/10'
          }`}
          title={metadata_skip ? 'AI suggestions disabled - click to enable' : 'AI suggestions enabled - click to disable'}
        >
          {metadata_skip ? (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
          )}
        </button>
        <button
          onClick={handleEdit}
          className="p-1.5 rounded transition-all text-muted hover:text-camel hover:bg-camel/10"
          title="Edit metadata"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
          </svg>
        </button>
        <button
          onClick={handleDelete}
          className="p-1.5 rounded transition-all text-muted hover:text-red-400 hover:bg-red-900/30"
          title="Delete source"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </div>
    </div>
  )
}


/**
 * Delete Source Modal
 * ===================
 * Shows gluon counts and asks user whether to keep or discard annotations.
 * For non-document sources (web, thread, media), also asks about local file deletion.
 */
function DeleteSourceModal({ sourceId, sourceTitle, onConfirm, onCancel }) {
  const { data: stats, isLoading } = useSourceGluonStats(sourceId)
  const [deleteLocalFiles, setDeleteLocalFiles] = useState(false)

  const hasAnnotations = stats && (stats.highlight_count > 0 || stats.note_count > 0)
  const isNonDocument = stats?.source_type && stats.source_type !== 'document'
  const hasLocalFolder = stats?.has_local_folder

  // Handler that passes both keepGluons and deleteLocalFiles
  const handleConfirm = (keepGluons) => {
    onConfirm(keepGluons, deleteLocalFiles)
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-md w-full shadow-2xl">
        <h2 className="font-display text-2xl text-primary mb-4">Delete Source</h2>

        <p className="text-secondary mb-4 line-clamp-2">
          {sourceTitle}
        </p>

        {isLoading ? (
          <p className="text-muted mb-6">Checking annotations...</p>
        ) : hasAnnotations ? (
          <div className="bg-raised rounded-lg p-4 mb-4">
            <p className="text-secondary mb-2">
              This source has annotations:
            </p>
            <ul className="text-sm text-tertiary space-y-1">
              {stats.highlight_count > 0 && (
                <li className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-yellow-400/30"></span>
                  {stats.highlight_count} highlight{stats.highlight_count !== 1 ? 's' : ''}
                </li>
              )}
              {stats.note_count > 0 && (
                <li className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-blue-400/30"></span>
                  {stats.note_count} note{stats.note_count !== 1 ? 's' : ''}
                </li>
              )}
            </ul>
          </div>
        ) : (
          <p className="text-muted mb-4">
            This source has no annotations.
          </p>
        )}

        {/* Local files deletion option for non-document sources */}
        {isNonDocument && hasLocalFolder && (
          <label className="flex items-start gap-3 p-3 bg-raised rounded-lg mb-4 cursor-pointer hover:bg-elevated transition-colors">
            <input
              type="checkbox"
              checked={deleteLocalFiles}
              onChange={(e) => setDeleteLocalFiles(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-subtle bg-base text-red-500 focus:ring-red-500 focus:ring-offset-0"
            />
            <div className="flex-1">
              <span className="text-secondary text-sm font-medium">
                Also delete local files
              </span>
              <p className="text-muted text-xs mt-1">
                Remove the folder containing extracted text and any downloaded media
              </p>
              {stats.local_folder_path && (
                <p className="text-muted text-xs mt-1 font-mono truncate" title={stats.local_folder_path}>
                  {stats.local_folder_path.split(/[/\\]/).slice(-2).join('/')}
                </p>
              )}
            </div>
          </label>
        )}

        <div className="flex flex-col gap-2">
          {hasAnnotations ? (
            <>
              <button
                onClick={() => handleConfirm(false)}
                className="w-full py-2.5 px-4 bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded-lg transition-colors text-sm font-medium"
              >
                Delete source and all annotations
                {deleteLocalFiles && ' + local files'}
              </button>
              <button
                onClick={() => handleConfirm(true)}
                className="w-full py-2.5 px-4 bg-raised hover:bg-elevated text-secondary rounded-lg transition-colors text-sm"
              >
                Delete source, keep annotations as orphans
                {deleteLocalFiles && ' + delete local files'}
              </button>
            </>
          ) : (
            <button
              onClick={() => handleConfirm(false)}
              className="w-full py-2.5 px-4 bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded-lg transition-colors text-sm font-medium"
            >
              Delete source{deleteLocalFiles && ' + local files'}
            </button>
          )}
          <button
            onClick={onCancel}
            className="w-full py-2.5 px-4 text-muted hover:text-secondary rounded-lg transition-colors text-sm"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}


/**
 * Batch Metadata Suggestion Modal
 * ===============================
 * AI-powered metadata extraction for multiple sources at once.
 * Shows results with confidence indicators and allows selective application.
 */
function BatchMetadataSuggestionModal({ sources, onClose, onSuccess }) {
  const batchSuggest = useBatchSuggestMetadata()
  const updateSource = useUpdateSource()
  const [results, setResults] = useState(null)
  const [skippedSources, setSkippedSources] = useState([])
  const [selectedSuggestions, setSelectedSuggestions] = useState({}) // { sourceId: { field: true/false } }
  const [applyingAll, setApplyingAll] = useState(false)

  // Start fetching suggestions when modal opens
  useEffect(() => {
    const sourceIds = sources.map(s => s.id)
    batchSuggest.mutate(sourceIds, {
      onSuccess: (data) => {
        setResults(data.results || [])
        setSkippedSources(data.skipped_sources || [])
        // Pre-select all high-confidence suggestions
        const initialSelections = {}
        for (const result of (data.results || [])) {
          if (result.has_suggestions) {
            initialSelections[result.source_id] = {}
            for (const suggestion of result.suggestions) {
              // Pre-select high and medium confidence
              initialSelections[result.source_id][suggestion.field] = suggestion.confidence >= 0.8
            }
          }
        }
        setSelectedSuggestions(initialSelections)
      }
    })
  }, [])

  // Toggle a single suggestion
  const toggleSuggestion = (sourceId, field) => {
    setSelectedSuggestions(prev => ({
      ...prev,
      [sourceId]: {
        ...(prev[sourceId] || {}),
        [field]: !(prev[sourceId]?.[field])
      }
    }))
  }

  // Apply selected suggestions for a single source
  const applyForSource = async (sourceId) => {
    const result = results.find(r => r.source_id === String(sourceId))
    if (!result) return

    const updates = {}
    for (const suggestion of result.suggestions) {
      if (selectedSuggestions[sourceId]?.[suggestion.field]) {
        updates[suggestion.field] = suggestion.value
      }
    }

    if (Object.keys(updates).length > 0) {
      await updateSource.mutateAsync({ id: sourceId, updates })
      // Mark as applied by removing from results
      setResults(prev => prev.map(r =>
        r.source_id === String(sourceId)
          ? { ...r, applied: true }
          : r
      ))
    }
  }

  // Apply all selected suggestions
  const applyAll = async () => {
    setApplyingAll(true)
    for (const result of results) {
      if (result.has_suggestions && !result.applied) {
        await applyForSource(result.source_id)
      }
    }
    setApplyingAll(false)
    onSuccess?.()
  }

  // Get source title by ID
  const getSourceTitle = (sourceId) => {
    const source = sources.find(s => String(s.id) === String(sourceId))
    return source?.title || `Source #${sourceId}`
  }

  // Count total selected suggestions
  const countSelectedSuggestions = () => {
    let count = 0
    for (const sourceId of Object.keys(selectedSuggestions)) {
      for (const field of Object.keys(selectedSuggestions[sourceId] || {})) {
        if (selectedSuggestions[sourceId][field]) count++
      }
    }
    return count
  }

  // Count sources with suggestions
  const sourcesWithSuggestions = results?.filter(r => r.has_suggestions && !r.applied).length || 0

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-raised rounded-xl max-w-3xl w-full max-h-[80vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="px-6 py-4 border-b border-raised flex items-center justify-between">
          <div>
            <h2 className="font-display text-2xl text-primary">AI Metadata Suggestions</h2>
            <p className="text-sm text-secondary mt-1">
              Review and apply AI-extracted metadata for your sources
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-muted hover:text-secondary transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Loading State */}
          {batchSuggest.isPending && (
            <div className="flex flex-col items-center justify-center py-12">
              <div className="w-8 h-8 border-2 border-camel border-t-transparent rounded-full animate-spin mb-4"></div>
              <p className="text-secondary">Analyzing {sources.length} source{sources.length !== 1 ? 's' : ''}...</p>
              <p className="text-muted text-sm mt-1">This may take a moment</p>
            </div>
          )}

          {/* Error State */}
          {batchSuggest.isError && (
            <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
              <p className="text-red-400">Failed to get suggestions: {batchSuggest.error?.message}</p>
              <button
                onClick={() => batchSuggest.mutate(sources.map(s => s.id))}
                className="mt-3 px-3 py-1.5 text-sm bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded-lg transition-colors"
              >
                Retry
              </button>
            </div>
          )}

          {/* Results */}
          {results && (
            <div className="space-y-4">
              {/* Skipped sources summary */}
              {skippedSources.length > 0 && (
                <div className="bg-green-900/20 border border-green-800/50 rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <svg className="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span className="text-green-400 font-medium">
                      {skippedSources.length} source{skippedSources.length !== 1 ? 's' : ''} skipped
                    </span>
                  </div>
                  <p className="text-green-300/70 text-sm mb-2">
                    Previous suggestions were already applied to these sources:
                  </p>
                  <ul className="text-green-300/60 text-xs space-y-0.5 max-h-24 overflow-y-auto">
                    {skippedSources.map(s => (
                      <li key={s.source_id} className="truncate">
                        {s.title}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {results.length === 0 && skippedSources.length === 0 ? (
                <p className="text-muted text-center py-8">No sources to analyze</p>
              ) : results.length === 0 && skippedSources.length > 0 ? (
                <div className="text-center py-8">
                  <p className="text-secondary">All sources already processed</p>
                  <p className="text-muted text-sm mt-1">
                    Previous AI suggestions have been applied to all sources
                  </p>
                </div>
              ) : results.every(r => !r.has_suggestions) ? (
                <div className="text-center py-8">
                  <p className="text-secondary">No new metadata suggestions found</p>
                  <p className="text-muted text-sm mt-1">
                    AI couldn't extract additional metadata with high confidence
                  </p>
                </div>
              ) : (
                results.map((result) => (
                  <SourceSuggestionCard
                    key={result.source_id}
                    result={result}
                    sourceTitle={getSourceTitle(result.source_id)}
                    selections={selectedSuggestions[result.source_id] || {}}
                    onToggle={(field) => toggleSuggestion(result.source_id, field)}
                    onApply={() => applyForSource(result.source_id)}
                    isApplying={updateSource.isPending}
                  />
                ))
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-raised flex items-center justify-between bg-raised/50">
          <div className="text-sm text-secondary">
            {results && (
              <>
                {sourcesWithSuggestions} source{sourcesWithSuggestions !== 1 ? 's' : ''} with suggestions
                {skippedSources.length > 0 && (
                  <span className="text-green-400/70 ml-2">
                    ({skippedSources.length} skipped)
                  </span>
                )}
                {countSelectedSuggestions() > 0 && (
                  <span className="text-camel ml-2">
                    · {countSelectedSuggestions()} selected
                  </span>
                )}
              </>
            )}
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-secondary hover:text-primary transition-colors"
            >
              Close
            </button>
            {sourcesWithSuggestions > 0 && (
              <button
                onClick={applyAll}
                disabled={applyingAll || countSelectedSuggestions() === 0}
                className="px-4 py-2 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {applyingAll ? 'Applying...' : 'Apply All Selected'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}


/**
 * Source Suggestion Card
 * ======================
 * Shows AI suggestions for a single source with checkboxes to select/deselect.
 */
function SourceSuggestionCard({ result, sourceTitle, selections, onToggle, onApply, isApplying }) {
  if (!result.has_suggestions) {
    return null // Don't render sources without suggestions
  }

  if (result.applied) {
    return (
      <div className="bg-raised rounded-lg p-4 opacity-60">
        <div className="flex items-center gap-2">
          <svg className="w-5 h-5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          <span className="text-secondary line-clamp-1">{sourceTitle}</span>
          <span className="text-green-500 text-sm ml-auto">Applied</span>
        </div>
      </div>
    )
  }

  const selectedCount = Object.values(selections).filter(Boolean).length

  return (
    <div className="bg-raised rounded-lg p-4">
      {/* Source Header */}
      <div className="flex items-start justify-between mb-3">
        <h3 className="text-primary font-medium line-clamp-2 flex-1 pr-4">
          {sourceTitle}
        </h3>
        <button
          onClick={onApply}
          disabled={isApplying || selectedCount === 0}
          className="px-3 py-1 text-xs bg-camel/20 text-camel rounded hover:bg-camel/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
        >
          Apply ({selectedCount})
        </button>
      </div>

      {/* Suggestions */}
      <div className="space-y-2">
        {result.suggestions.map((suggestion) => (
          <SuggestionRow
            key={suggestion.field}
            suggestion={suggestion}
            selected={selections[suggestion.field] || false}
            onToggle={() => onToggle(suggestion.field)}
          />
        ))}
      </div>

      {/* Previously suggested indicator */}
      {result.previously_suggested && result.empty_fields?.length > 0 && (
        <div className="mt-3 pt-3 border-t border-elevated">
          <span className="text-xs text-yellow-400/70">
            Previously suggested — still missing: {result.empty_fields.join(', ')}
          </span>
        </div>
      )}

      {/* DOI/ISBN found indicators */}
      {(result.doi_found || result.isbn_found) && (
        <div className="mt-3 pt-3 border-t border-elevated flex gap-3">
          {result.doi_found && (
            <span className="text-xs text-camel">
              DOI found: {result.doi_found}
            </span>
          )}
          {result.isbn_found && (
            <span className="text-xs text-terra">
              ISBN found: {result.isbn_found}
            </span>
          )}
        </div>
      )}
    </div>
  )
}


/**
 * Suggestion Row
 * ==============
 * A single metadata field suggestion with confidence indicator.
 */
function SuggestionRow({ suggestion, selected, onToggle }) {
  const { field, value, confidence, confidence_label } = suggestion

  // Confidence colors
  const confidenceStyles = {
    high: { bg: 'bg-green-500/20', text: 'text-green-400', label: 'High' },
    medium: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: 'Medium' },
    low: { bg: 'bg-red-500/20', text: 'text-red-400', label: 'Low' }
  }
  const style = confidenceStyles[confidence_label] || confidenceStyles.medium

  // Field display names
  const fieldLabels = {
    title: 'Title',
    author: 'Authors',
    year: 'Year',
    journal: 'Journal',
    volume: 'Volume',
    issue: 'Issue',
    pages: 'Pages',
    publisher: 'Publisher',
    editors: 'Editors',
    edition: 'Edition',
    series: 'Series',
    doi: 'DOI',
    isbn: 'ISBN',
    issn: 'ISSN',
    abstract: 'Abstract',
    keywords: 'Keywords',
    url: 'URL'
  }

  return (
    <label className="flex items-start gap-3 p-2 rounded hover:bg-elevated cursor-pointer group">
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="mt-1 w-4 h-4 rounded border-subtle bg-base text-camel focus:ring-camel focus:ring-offset-0"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs text-muted uppercase tracking-wide">
            {fieldLabels[field] || field}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${style.bg} ${style.text}`}>
            {Math.round(confidence * 100)}%
          </span>
        </div>
        <p className={`text-sm ${selected ? 'text-primary' : 'text-secondary'} line-clamp-2`}>
          {value}
        </p>
      </div>
    </label>
  )
}
