import { useEffect, useState } from 'react'
import { useBatchSuggestMetadata, useUpdateSource, useFindOrCreateTags, useFindOrCreatePeople } from '../../hooks/useApi'

/**
 * Batch Metadata Suggestion Modal
 * ===============================
 * AI-powered metadata extraction for multiple sources at once.
 * Shows results with confidence indicators and allows selective application.
 */
export default function BatchMetadataSuggestionModal({ sources, onClose, onSuccess }) {
  const batchSuggest = useBatchSuggestMetadata()
  const updateSource = useUpdateSource()
  const findOrCreateTags = useFindOrCreateTags()
  const findOrCreatePeople = useFindOrCreatePeople()
  const [results, setResults] = useState(null)
  const [skippedSources, setSkippedSources] = useState([])
  const [selectedSuggestions, setSelectedSuggestions] = useState({}) // { sourceId: { field: true/false } }
  const [editedValues, setEditedValues] = useState({}) // { sourceId: { field: "edited value" } }
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

  // Edit a suggestion value
  const editValue = (sourceId, field, newValue) => {
    setEditedValues(prev => ({
      ...prev,
      [sourceId]: {
        ...(prev[sourceId] || {}),
        [field]: newValue
      }
    }))
  }

  // Get the current value for a suggestion (edited or original)
  const getValue = (sourceId, field, originalValue) => {
    return editedValues[sourceId]?.[field] ?? originalValue
  }

  // Apply selected suggestions for a single source, creating gluons as needed
  const applyForSource = async (sourceId) => {
    const result = results.find(r => r.source_id === String(sourceId))
    if (!result) return

    const updates = {}
    for (const suggestion of result.suggestions) {
      if (!selectedSuggestions[sourceId]?.[suggestion.field]) continue
      const value = getValue(sourceId, suggestion.field, suggestion.value)

      if (suggestion.field === 'keywords' && value) {
        // Create tag gluons from semicolon/comma-separated keywords
        const names = value.split(/[;,]/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const tagResults = await findOrCreateTags.mutateAsync(names)
            updates.keywords = tagResults.map(t => t.name).join('; ')
            updates.keyword_gluon_ids = JSON.stringify(tagResults.map(t => t.id))
          } catch (err) {
            console.error('Failed to create tags:', err)
            updates.keywords = String(value)
          }
        }
      } else if (suggestion.field === 'author' && value) {
        // Create person gluons from semicolon-separated authors
        const names = value.split(/;/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const personResults = await findOrCreatePeople.mutateAsync(names)
            updates.author = personResults.map(p => p.name).join('; ')
            updates.author_gluon_ids = JSON.stringify(personResults.map(p => p.id))
          } catch (err) {
            console.error('Failed to create authors:', err)
            updates.author = String(value)
          }
        }
      } else if (suggestion.field === 'editors' && value) {
        // Create person gluons from semicolon-separated editors
        const names = value.split(/;/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const personResults = await findOrCreatePeople.mutateAsync(names)
            updates.editors = personResults.map(p => p.name).join('; ')
            updates.editor_gluon_ids = JSON.stringify(personResults.map(p => p.id))
          } catch (err) {
            console.error('Failed to create editors:', err)
            updates.editors = String(value)
          }
        }
      } else {
        updates[suggestion.field] = value
      }
    }

    if (Object.keys(updates).length > 0) {
      await updateSource.mutateAsync({ id: sourceId, updates })
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
                    editedValues={editedValues[result.source_id] || {}}
                    onEditValue={(field, val) => editValue(result.source_id, field, val)}
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
function SourceSuggestionCard({ result, sourceTitle, selections, onToggle, onApply, isApplying, editedValues = {}, onEditValue }) {
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
            editedValue={editedValues[suggestion.field]}
            onEditValue={(val) => onEditValue(suggestion.field, val)}
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
function SuggestionRow({ suggestion, selected, onToggle, editedValue, onEditValue }) {
  const { field, value, confidence, confidence_label } = suggestion
  const [isEditing, setIsEditing] = useState(false)
  const displayValue = editedValue ?? value
  const isModified = editedValue != null && editedValue !== value

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

  // Long-form fields get a textarea
  const isLongField = ['abstract', 'keywords'].includes(field)

  return (
    <div className="flex items-start gap-3 p-2 rounded hover:bg-elevated group">
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="mt-1 w-4 h-4 rounded border-subtle bg-base text-camel focus:ring-camel focus:ring-offset-0 cursor-pointer"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-xs text-muted uppercase tracking-wide">
            {fieldLabels[field] || field}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${style.bg} ${style.text}`}>
            {Math.round(confidence * 100)}%
          </span>
          {isModified && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-camel/20 text-camel">
              edited
            </span>
          )}
        </div>

        {isEditing ? (
          isLongField ? (
            <textarea
              autoFocus
              value={displayValue}
              onChange={(e) => onEditValue(e.target.value)}
              onBlur={() => setIsEditing(false)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setIsEditing(false)
              }}
              rows={3}
              className="w-full text-sm text-primary bg-base border border-camel/40 rounded px-2 py-1 focus:outline-none focus:border-camel resize-y"
            />
          ) : (
            <input
              autoFocus
              type="text"
              value={displayValue}
              onChange={(e) => onEditValue(e.target.value)}
              onBlur={() => setIsEditing(false)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === 'Escape') setIsEditing(false)
              }}
              className="w-full text-sm text-primary bg-base border border-camel/40 rounded px-2 py-1 focus:outline-none focus:border-camel"
            />
          )
        ) : (
          <p
            onClick={() => setIsEditing(true)}
            className={`text-sm cursor-text rounded px-1 -mx-1 transition-colors
              ${selected ? 'text-primary' : 'text-secondary'}
              hover:bg-base hover:ring-1 hover:ring-subtle
              ${isLongField ? '' : 'line-clamp-2'}
            `}
            title="Click to edit"
          >
            {displayValue}
          </p>
        )}
      </div>
    </div>
  )
}
