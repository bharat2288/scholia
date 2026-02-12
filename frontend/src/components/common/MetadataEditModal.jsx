/**
 * MetadataEditModal
 * =================
 * Adaptive modal for editing source metadata.
 * Shows type-appropriate fields based on source_type.
 *
 * Features:
 * - Adaptive fields by source type (document, web, thread, media)
 * - Read-only engagement metrics (views, likes, retweets)
 * - DOI/ISBN fetch for documents
 * - AI suggest for all types
 */

import { useState, useMemo, useCallback } from 'react'
import { useUpdateSource, useLookupDOI, useLookupISBN, useSuggestMetadata, useFindOrCreateTags, useFindOrCreatePeople } from '../../hooks/useApi'
import PersonInput from './PersonInput'
import TagInput from './TagInput'
import SiteNameInput from './SiteNameInput'

/**
 * Generate array of years from current year back to 1800
 */
const generateYears = () => {
  const currentYear = new Date().getFullYear()
  return Array.from({ length: currentYear - 1799 }, (_, i) => currentYear - i)
}

const YEARS = generateYears()

/**
 * Field definitions with metadata
 */
const FIELD_DEFINITIONS = {
  // Universal fields
  title: { label: 'Title', type: 'text', placeholder: 'Source title' },
  author: { label: 'Author(s)', type: 'author', placeholder: 'Author names' },
  year: { label: 'Year', type: 'year' },

  // Document fields
  journal: { label: 'Journal/Conference', type: 'text', placeholder: 'Journal name' },
  volume: { label: 'Volume', type: 'text', placeholder: 'Vol.' },
  issue: { label: 'Issue', type: 'text', placeholder: 'No.' },
  pages: { label: 'Pages', type: 'text', placeholder: 'e.g., 1-15' },
  publisher: { label: 'Publisher', type: 'text', placeholder: 'Publisher name' },
  editors: { label: 'Editor(s)', type: 'person', placeholder: 'Type editor name...' },
  edition: { label: 'Edition', type: 'text', placeholder: 'e.g., 2nd' },
  series: { label: 'Series', type: 'text', placeholder: 'Book series' },
  doi: { label: 'DOI', type: 'fetch', fetchType: 'doi', placeholder: '10.xxxx/xxxxx' },
  isbn: { label: 'ISBN', type: 'fetch', fetchType: 'isbn', placeholder: '978-...' },
  issn: { label: 'ISSN', type: 'text', placeholder: 'ISSN' },
  abstract: { label: 'Abstract', type: 'textarea', rows: 4, placeholder: 'Document abstract...' },
  keywords: { label: 'Tags', type: 'tags', placeholder: 'Type tag...' },

  // Web fields
  sitename: { label: 'Site Name', type: 'sitename', placeholder: 'e.g., Medium, Substack' },
  url: { label: 'URL', type: 'text', placeholder: 'https://...' },

  // Tweet fields
  author_handle: { label: 'Handle', type: 'text', readOnly: true },
  tweet_id: { label: 'Tweet ID', type: 'text', readOnly: true },
  thread_length: { label: 'Tweets', type: 'text', readOnly: true },
  likes: { label: 'Likes', type: 'number', readOnly: true },
  retweets: { label: 'Retweets', type: 'number', readOnly: true },
  replies: { label: 'Replies', type: 'number', readOnly: true },

  // Video fields
  channel: { label: 'Channel', type: 'text', placeholder: 'Channel name' },
  platform: { label: 'Platform', type: 'text', readOnly: true },
  video_id: { label: 'Video ID', type: 'text', readOnly: true },
  duration_formatted: { label: 'Duration', type: 'text', readOnly: true },
  view_count: { label: 'Views', type: 'number', readOnly: true },
  like_count: { label: 'Likes', type: 'number', readOnly: true },
  description: { label: 'Description', type: 'textarea', rows: 3, placeholder: 'Video description' },
}

/**
 * Section configuration by source type
 */
const FIELD_CONFIG = {
  document: {
    sections: [
      { title: 'Core Information', fields: ['title', 'author', 'year'] },
      { title: 'Publication', fields: ['journal', 'publisher'] },
      { title: null, fields: ['volume', 'issue', 'pages'] },
      { title: 'Book Details', fields: ['editors', 'edition', 'series'] },
      { title: 'Identifiers', fields: ['doi', 'isbn'] },
      { title: null, fields: ['issn', 'url'] },
      { title: 'Description', fields: ['abstract'] },
      { title: null, fields: ['keywords'] },
    ],
    showAISuggest: true,
    showDOIFetch: true,
    showISBNFetch: true,
  },
  web: {
    sections: [
      { title: 'Core Information', fields: ['title', 'author', 'year'] },
      { title: 'Source', fields: ['sitename', 'url'] },
      { title: 'Description', fields: ['abstract'] },
      { title: null, fields: ['keywords'] },
    ],
    showAISuggest: true,
    showDOIFetch: false,
    showISBNFetch: false,
  },
  thread: {
    sections: [
      { title: 'Thread Info', fields: ['title', 'author', 'author_handle'] },
      { title: 'Details', fields: ['tweet_id', 'thread_length'] },
      { title: 'Engagement', fields: ['likes', 'retweets', 'replies'] },
      { title: 'Tags', fields: ['keywords'] },
    ],
    showAISuggest: true,
    showDOIFetch: false,
    showISBNFetch: false,
  },
  tweet: {
    sections: [
      { title: 'Tweet Info', fields: ['title', 'author', 'author_handle'] },
      { title: 'Details', fields: ['tweet_id'] },
      { title: 'Engagement', fields: ['likes', 'retweets', 'replies'] },
      { title: 'Tags', fields: ['keywords'] },
    ],
    showAISuggest: true,
    showDOIFetch: false,
    showISBNFetch: false,
  },
  media: {
    sections: [
      { title: 'Video Info', fields: ['title', 'channel', 'year'] },
      { title: 'Platform', fields: ['platform', 'video_id', 'duration_formatted'] },
      { title: 'Engagement', fields: ['view_count', 'like_count'] },
      { title: 'Description', fields: ['description'] },
      { title: 'Tags', fields: ['keywords'] },
    ],
    showAISuggest: true,
    showDOIFetch: false,
    showISBNFetch: false,
  },
}

/**
 * Format large numbers with commas
 */
function formatNumber(num) {
  if (num === null || num === undefined) return ''
  return num.toLocaleString()
}

/**
 * Input field component
 */
function Field({ label, type = 'text', placeholder, className = '', value, onChange, readOnly = false }) {
  const baseClasses = "w-full bg-base border border-subtle rounded px-3 py-1.5 text-sm text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]"
  const readOnlyClasses = readOnly ? "bg-elevated/50 text-secondary cursor-not-allowed" : ""

  return (
    <div className={className}>
      <label className="block text-xs text-muted mb-1">{label}</label>
      <input
        type={type === 'number' ? 'text' : type}
        value={type === 'number' && value ? formatNumber(value) : (value || '')}
        onChange={onChange}
        placeholder={placeholder}
        readOnly={readOnly}
        disabled={readOnly}
        className={`${baseClasses} ${readOnlyClasses}`}
      />
    </div>
  )
}

/**
 * Textarea field component
 */
function TextareaField({ label, placeholder, value, onChange, rows = 3, readOnly = false }) {
  const baseClasses = "w-full bg-base border border-subtle rounded px-3 py-2 text-sm text-primary placeholder:text-muted focus:border-camel focus:outline-none resize-none shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]"
  const readOnlyClasses = readOnly ? "bg-elevated/50 text-secondary cursor-not-allowed" : ""

  return (
    <div>
      <label className="block text-xs text-muted mb-1">{label}</label>
      <textarea
        value={value || ''}
        onChange={onChange}
        rows={rows}
        placeholder={placeholder}
        readOnly={readOnly}
        disabled={readOnly}
        className={`${baseClasses} ${readOnlyClasses}`}
      />
    </div>
  )
}

/**
 * Field with fetch button (for DOI/ISBN)
 */
function FieldWithFetch({ label, placeholder, value, onChange, onFetch, isLoading }) {
  return (
    <div>
      <label className="block text-xs text-muted mb-1">{label}</label>
      <div className="flex gap-2">
        <input
          type="text"
          value={value || ''}
          onChange={onChange}
          placeholder={placeholder}
          className="flex-1 bg-base border border-subtle rounded px-3 py-1.5 text-sm text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]"
        />
        <button
          type="button"
          onClick={onFetch}
          disabled={!value?.trim() || isLoading}
          className="px-3 py-1.5 text-xs bg-raised hover:bg-camel/20 text-camel rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
        >
          {isLoading ? '...' : 'Fetch'}
        </button>
      </div>
    </div>
  )
}

/**
 * Year selector (dropdown or custom input)
 */
function YearField({ value, onChange }) {
  const [showCustom, setShowCustom] = useState(false)
  const yearInRange = value && YEARS.includes(parseInt(value, 10))

  const handleYearChange = (e) => {
    const val = e.target.value
    if (val === 'custom') {
      setShowCustom(true)
      onChange({ target: { value: '' } })
    } else {
      setShowCustom(false)
      onChange(e)
    }
  }

  if (showCustom || (value && !yearInRange)) {
    return (
      <div>
        <label className="block text-xs text-muted mb-1">Year</label>
        <div className="flex gap-2">
          <input
            type="number"
            value={value || ''}
            onChange={onChange}
            placeholder="e.g., 1750"
            className="flex-1 bg-base border border-subtle rounded px-3 py-1.5 text-sm text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]"
          />
          <button
            type="button"
            onClick={() => {
              setShowCustom(false)
              onChange({ target: { value: '' } })
            }}
            className="px-2 text-muted hover:text-primary"
            title="Use dropdown"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" />
            </svg>
          </button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <label className="block text-xs text-muted mb-1">Year</label>
      <select
        value={value || ''}
        onChange={handleYearChange}
        className="w-full bg-base border border-subtle rounded px-3 py-1.5 text-sm text-primary focus:border-camel focus:outline-none shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)] cursor-pointer"
      >
        <option value="">Select year...</option>
        {YEARS.map(y => (
          <option key={y} value={y}>{y}</option>
        ))}
        <option value="custom">Older (custom)...</option>
      </select>
    </div>
  )
}

/**
 * MetadataDiffPreview
 * Shows fetched metadata changes for user selection with inline editing
 */
function MetadataDiffPreview({ currentData, changes, onApply, onCancel }) {
  const [selectedFields, setSelectedFields] = useState(
    () => new Set(changes.map(([key]) => key))
  )

  const [editedValues, setEditedValues] = useState(() => {
    const initial = {}
    for (const [key, value] of changes) {
      initial[key] = value
    }
    return initial
  })

  const toggleField = (key) => {
    setSelectedFields(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const handleValueChange = (key, newValue) => {
    setEditedValues(prev => ({ ...prev, [key]: newValue }))
  }

  const handleApply = (selected) => {
    onApply(selected, editedValues)
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-[60] flex items-center justify-center p-4">
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-lg w-full shadow-2xl">
        <h3 className="font-display text-xl text-primary mb-2">Review Suggestions</h3>
        <p className="text-sm text-secondary mb-4">Select fields to update. Click a value to edit before applying.</p>

        <div className="space-y-2 max-h-64 overflow-auto pr-2">
          {changes.map(([key, originalValue]) => {
            const fieldDef = FIELD_DEFINITIONS[key] || { label: key }
            return (
              <div
                key={key}
                className="flex items-start gap-3 p-3 bg-raised rounded-lg hover:bg-elevated transition-colors"
              >
                <input
                  type="checkbox"
                  checked={selectedFields.has(key)}
                  onChange={() => toggleField(key)}
                  className="mt-1 rounded border-subtle bg-base text-camel focus:ring-camel cursor-pointer"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-muted uppercase tracking-wide mb-1">
                    {fieldDef.label}
                  </p>
                  {currentData[key] && (
                    <p className="text-sm text-red-400/80 line-through truncate mb-1">
                      {currentData[key]}
                    </p>
                  )}
                  {fieldDef.type === 'textarea' || key === 'abstract' ? (
                    <textarea
                      value={editedValues[key] || ''}
                      onChange={(e) => handleValueChange(key, e.target.value)}
                      rows={3}
                      className="w-full bg-base border border-green-700/50 rounded px-2 py-1 text-sm text-green-400 focus:border-green-500 focus:outline-none resize-none"
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <input
                      type="text"
                      value={editedValues[key] || ''}
                      onChange={(e) => handleValueChange(key, e.target.value)}
                      className="w-full bg-base border border-green-700/50 rounded px-2 py-1 text-sm text-green-400 focus:border-green-500 focus:outline-none"
                      onClick={(e) => e.stopPropagation()}
                    />
                  )}
                </div>
              </div>
            )
          })}
        </div>

        <div className="flex gap-3 mt-6">
          <button
            type="button"
            onClick={onCancel}
            className="flex-1 py-2.5 px-4 bg-raised hover:bg-elevated text-secondary rounded-lg transition-colors text-sm"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => handleApply(selectedFields)}
            disabled={selectedFields.size === 0}
            className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all disabled:opacity-50"
          >
            Apply {selectedFields.size} Field{selectedFields.size !== 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Render a single field based on its definition
 */
function RenderField({ fieldName, fieldDef, value, onChange, onFetch, isLoading, formData, setFormData }) {
  const handleChange = (e) => onChange(fieldName)(e)

  switch (fieldDef.type) {
    case 'author':
      return (
        <PersonInput
          value={value}
          gluonIds={formData.author_gluon_ids}
          onChange={(author) => setFormData(prev => ({ ...prev, author }))}
          onGluonIdsChange={(ids) => setFormData(prev => ({ ...prev, author_gluon_ids: ids }))}
          label="Author(s)"
          placeholder="Type author name..."
        />
      )

    case 'person':
      // Generic person field (for editors, etc.)
      // Map field name to gluon_ids field name
      // Special case: "editors" -> "editor_gluon_ids" (singular)
      const gluonIdsField = fieldName === 'editors' ? 'editor_gluon_ids' : `${fieldName}_gluon_ids`
      return (
        <PersonInput
          value={value}
          gluonIds={formData[gluonIdsField]}
          onChange={(val) => setFormData(prev => ({ ...prev, [fieldName]: val }))}
          onGluonIdsChange={(ids) => setFormData(prev => ({ ...prev, [gluonIdsField]: ids }))}
          label={fieldDef.label}
          placeholder={fieldDef.placeholder}
        />
      )

    case 'tags':
      // Tags field (for keywords)
      return (
        <TagInput
          value={value}
          gluonIds={formData.keyword_gluon_ids}
          onChange={(val) => setFormData(prev => ({ ...prev, [fieldName]: val }))}
          onGluonIdsChange={(ids) => setFormData(prev => ({ ...prev, keyword_gluon_ids: ids }))}
          label={fieldDef.label}
          placeholder={fieldDef.placeholder}
        />
      )

    case 'sitename':
      // Site name field with autocomplete (for web sources)
      return (
        <SiteNameInput
          value={value}
          onChange={(val) => setFormData(prev => ({ ...prev, [fieldName]: val }))}
          label={fieldDef.label}
          placeholder={fieldDef.placeholder}
        />
      )

    case 'year':
      return <YearField value={value} onChange={handleChange} />

    case 'fetch':
      return (
        <FieldWithFetch
          label={fieldDef.label}
          placeholder={fieldDef.placeholder}
          value={value}
          onChange={handleChange}
          onFetch={() => onFetch(fieldDef.fetchType)}
          isLoading={isLoading}
        />
      )

    case 'textarea':
      return (
        <TextareaField
          label={fieldDef.label}
          placeholder={fieldDef.placeholder}
          value={value}
          onChange={handleChange}
          rows={fieldDef.rows || 3}
          readOnly={fieldDef.readOnly}
        />
      )

    default:
      return (
        <Field
          label={fieldDef.label}
          type={fieldDef.type}
          placeholder={fieldDef.placeholder}
          value={value}
          onChange={handleChange}
          readOnly={fieldDef.readOnly}
        />
      )
  }
}

/**
 * Main MetadataEditModal component
 */
export default function MetadataEditModal({ sourceId, sourceType = 'document', documentData, onClose }) {
  const updateDocument = useUpdateSource()
  const lookupDOI = useLookupDOI()
  const lookupISBN = useLookupISBN()
  const suggestMetadata = useSuggestMetadata()
  const findOrCreateTags = useFindOrCreateTags()
  const findOrCreatePeople = useFindOrCreatePeople()

  // Get config for this source type (fallback to document)
  const config = FIELD_CONFIG[sourceType] || FIELD_CONFIG.document

  // Build initial form data with all possible fields
  const initialFormData = useMemo(() => ({
    // Universal
    title: documentData?.title || '',
    // Handle author - can be array of {id, content} objects (from get_source), string, or author_display
    author: (() => {
      const authors = documentData?.authors
      if (Array.isArray(authors) && authors.length > 0) {
        // Array of objects [{id, content}, ...] from get_source endpoint
        return authors.map(a => typeof a === 'object' ? a.content : a).join('; ')
      }
      return documentData?.author || documentData?.author_display || ''
    })(),
    // Build author_gluon_ids from authors array if available
    author_gluon_ids: (() => {
      const authors = documentData?.authors
      if (Array.isArray(authors) && authors.length > 0 && typeof authors[0] === 'object') {
        const ids = authors.map(a => a.id).filter(Boolean)
        return ids.length > 0 ? JSON.stringify(ids) : null
      }
      return documentData?.author_gluon_ids || null
    })(),
    year: documentData?.year ? String(documentData.year) : '',
    // Document
    journal: documentData?.journal || '',
    volume: documentData?.volume || '',
    issue: documentData?.issue || '',
    pages: documentData?.pages || '',
    publisher: documentData?.publisher || '',
    // Handle editors - can be array of {id, content} objects (from get_source), string, or metadata field
    editors: (() => {
      const eds = documentData?.editors
      if (Array.isArray(eds)) {
        // Map to string (empty array → empty string)
        return eds.map(e => typeof e === 'object' ? e.content : e).join('; ')
      }
      return eds || documentData?.metadata?.editors || ''
    })(),
    editor_gluon_ids: (() => {
      const eds = documentData?.editors
      if (Array.isArray(eds) && eds.length > 0 && typeof eds[0] === 'object') {
        const ids = eds.map(e => e.id).filter(Boolean)
        return ids.length > 0 ? JSON.stringify(ids) : null
      }
      return documentData?.editor_gluon_ids || null
    })(),
    edition: documentData?.edition || '',
    series: documentData?.series || '',
    doi: documentData?.doi || '',
    isbn: documentData?.isbn || '',
    issn: documentData?.issn || '',
    abstract: documentData?.abstract || '',
    // Handle keywords - can be array of {id, content} objects, array of strings, or semicolon string
    keywords: (() => {
      const kw = documentData?.keywords
      if (!kw) return ''
      if (Array.isArray(kw)) {
        // Array of objects [{id, content}, ...] or strings
        return kw.map(k => typeof k === 'object' ? k.content : k).join('; ')
      }
      return kw // Already a string
    })(),
    // Build keyword_gluon_ids from keywords array if available, otherwise use existing
    keyword_gluon_ids: (() => {
      const kw = documentData?.keywords
      if (Array.isArray(kw) && kw.length > 0 && typeof kw[0] === 'object') {
        // Extract IDs from [{id, content}, ...] array
        const ids = kw.map(k => k.id).filter(Boolean)
        return ids.length > 0 ? JSON.stringify(ids) : null
      }
      return documentData?.keyword_gluon_ids || null
    })(),
    url: documentData?.url || '',
    // Web
    sitename: documentData?.metadata?.sitename || '',
    // Tweet
    author_handle: documentData?.metadata?.author_handle || '',
    tweet_id: documentData?.metadata?.tweet_id || '',
    thread_length: documentData?.metadata?.thread_length || '',
    likes: documentData?.metadata?.likes || null,
    retweets: documentData?.metadata?.retweets || null,
    replies: documentData?.metadata?.replies || null,
    // Video
    channel: documentData?.metadata?.channel || documentData?.author || '',
    platform: documentData?.metadata?.platform || '',
    video_id: documentData?.metadata?.video_id || '',
    duration_formatted: documentData?.metadata?.duration_formatted || '',
    view_count: documentData?.metadata?.view_count || null,
    like_count: documentData?.metadata?.like_count || null,
    description: documentData?.metadata?.description || '',
    // AI suggestion skip flag
    metadata_skip: documentData?.metadata_skip || false,
  }), [sourceId])

  const [formData, setFormData] = useState(initialFormData)
  const [pendingMetadata, setPendingMetadata] = useState(null)
  const [fetchError, setFetchError] = useState(null)

  // Stable change handler
  const handleChange = useCallback((field) => (e) => {
    const value = e.target.value
    setFormData(prev => ({ ...prev, [field]: value }))
    setFetchError(null)
  }, [])

  // Fetch handler for DOI/ISBN
  const handleFetch = async (fetchType) => {
    setFetchError(null)

    try {
      let metadata
      if (fetchType === 'doi') {
        metadata = await lookupDOI.mutateAsync(formData.doi.trim())
      } else if (fetchType === 'isbn') {
        metadata = await lookupISBN.mutateAsync(formData.isbn.trim())
      }

      const changes = Object.entries(metadata).filter(([key, value]) => {
        if (!value) return false
        const current = formData[key]
        return String(value) !== String(current || '')
      })

      if (changes.length === 0) {
        setFetchError(`No additional metadata found for this ${fetchType.toUpperCase()}`)
        return
      }

      setPendingMetadata({ data: metadata, changes })
    } catch (err) {
      setFetchError(err.message || `${fetchType.toUpperCase()} not found`)
    }
  }

  // AI Suggest handler
  const handleAISuggest = async () => {
    setFetchError(null)
    try {
      const result = await suggestMetadata.mutateAsync(sourceId)

      if (!result.has_suggestions || result.suggestions.length === 0) {
        setFetchError('AI could not extract additional metadata with high confidence')
        return
      }

      const changes = result.suggestions.map(s => [s.field, s.value])
      const filteredChanges = changes.filter(([key, value]) => {
        const current = formData[key]
        return String(value || '') !== String(current || '')
      })

      if (filteredChanges.length === 0) {
        setFetchError('AI suggestions match current metadata')
        return
      }

      const metadata = {}
      for (const [key, value] of filteredChanges) {
        metadata[key] = value
      }

      setPendingMetadata({ data: metadata, changes: filteredChanges, isAI: true })
    } catch (err) {
      setFetchError(err.message || 'AI suggestion failed')
    }
  }

  // Apply selected fields from diff preview
  // For keywords/author/editors, automatically create gluons so they appear as LINKED
  const handleApplyMetadata = async (selectedFields, editedValues) => {
    if (!pendingMetadata) return

    const updates = { ...formData }

    for (const key of selectedFields) {
      const value = editedValues?.[key] ?? pendingMetadata.data[key]

      if (key === 'keywords' && value) {
        // Parse comma/semicolon separated keywords and create gluons
        const names = value.split(/[;,]/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const tagResults = await findOrCreateTags.mutateAsync(names)
            // Build both the display string and the gluon IDs
            updates.keywords = tagResults.map(t => t.name).join('; ')
            updates.keyword_gluon_ids = JSON.stringify(tagResults.map(t => t.id))
          } catch (err) {
            console.error('Failed to create tags:', err)
            // Fallback: just set the text without linking
            updates.keywords = String(value || '')
          }
        }
      } else if (key === 'author' && value) {
        // Parse semicolon-separated authors and create person gluons
        const names = value.split(/;/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const personResults = await findOrCreatePeople.mutateAsync(names)
            updates.author = personResults.map(p => p.name).join('; ')
            updates.author_gluon_ids = JSON.stringify(personResults.map(p => p.id))
          } catch (err) {
            console.error('Failed to create authors:', err)
            updates.author = String(value || '')
          }
        }
      } else if (key === 'editors' && value) {
        // Parse semicolon-separated editors and create person gluons
        const names = value.split(/;/).map(n => n.trim()).filter(Boolean)
        if (names.length > 0) {
          try {
            const personResults = await findOrCreatePeople.mutateAsync(names)
            updates.editors = personResults.map(p => p.name).join('; ')
            updates.editor_gluon_ids = JSON.stringify(personResults.map(p => p.id))
          } catch (err) {
            console.error('Failed to create editors:', err)
            updates.editors = String(value || '')
          }
        }
      } else {
        updates[key] = String(value || '')
      }
    }

    setFormData(updates)
    setPendingMetadata(null)
  }

  // Form submission
  const handleSubmit = async (e) => {
    e.preventDefault()

    const updates = {}
    Object.entries(formData).forEach(([key, value]) => {
      const originalValue = documentData?.[key] ?? documentData?.metadata?.[key]
      const newValue = typeof value === 'string' ? value.trim() : value

      // Special handling for boolean fields like metadata_skip
      if (key === 'metadata_skip') {
        const origBool = Boolean(originalValue)
        const newBool = Boolean(newValue)
        if (newBool !== origBool) {
          updates[key] = newBool ? 1 : 0  // SQLite uses 1/0 for booleans
        }
        return
      }

      if (String(newValue || '') !== String(originalValue || '')) {
        if (key === 'year') {
          updates[key] = newValue ? parseInt(newValue, 10) : null
        } else {
          updates[key] = newValue || null
        }
      }
    })

    // For threads/tweets: sync author to author_display so Library cards show the formatted name
    if ((sourceType === 'thread' || sourceType === 'tweet') && updates.author) {
      updates.author_display = updates.author
    }

    if (Object.keys(updates).length === 0) {
      onClose()
      return
    }

    try {
      await updateDocument.mutateAsync({ id: sourceId, updates })
      onClose()
    } catch (err) {
      console.error('Failed to update document:', err)
      alert('Failed to save changes: ' + err.message)
    }
  }

  // Determine grid columns based on field count
  const getGridClass = (fieldCount) => {
    if (fieldCount === 1) return 'grid-cols-1'
    if (fieldCount === 2) return 'grid-cols-2'
    return 'grid-cols-3'
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-2xl w-full shadow-2xl max-h-[90vh] overflow-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-display text-2xl text-primary">Edit Metadata</h2>
          <div className="flex items-center gap-2">
            {/* AI Suggest Button (all types) */}
            {config.showAISuggest && (
              <button
                type="button"
                onClick={handleAISuggest}
                disabled={suggestMetadata.isPending}
                className="p-2 rounded-lg bg-camel/10 hover:bg-camel/20 text-camel transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="AI Suggest Metadata"
              >
                {suggestMetadata.isPending ? (
                  <svg className="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                )}
              </button>
            )}
            {/* Close Button */}
            <button
              onClick={onClose}
              className="p-2 text-muted hover:text-primary transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Fetch error message */}
        {fetchError && (
          <div className="mb-4 p-3 bg-red-900/20 border border-red-800/50 rounded-lg text-red-400 text-sm">
            {fetchError}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Render sections based on source type config */}
          {config.sections.map((section, sectionIndex) => (
            <div key={sectionIndex} className="space-y-4">
              {section.title && (
                <p className="label text-camel text-xs">{section.title}</p>
              )}
              <div className={`grid gap-4 ${getGridClass(section.fields.length)}`}>
                {section.fields.map(fieldName => {
                  const fieldDef = FIELD_DEFINITIONS[fieldName]
                  if (!fieldDef) return null

                  return (
                    <RenderField
                      key={fieldName}
                      fieldName={fieldName}
                      fieldDef={fieldDef}
                      value={formData[fieldName]}
                      onChange={handleChange}
                      onFetch={handleFetch}
                      isLoading={lookupDOI.isPending || lookupISBN.isPending}
                      formData={formData}
                      setFormData={setFormData}
                    />
                  )
                })}
              </div>
            </div>
          ))}

          {/* AI Skip Toggle */}
          {config.showAISuggest && (
            <div className="pt-4 border-t border-subtle">
              <label className="flex items-center gap-3 cursor-pointer group">
                {/* Toggle Switch */}
                <button
                  type="button"
                  role="switch"
                  aria-checked={formData.metadata_skip || false}
                  onClick={() => setFormData(prev => ({ ...prev, metadata_skip: !prev.metadata_skip }))}
                  className={`
                    relative w-10 h-5 rounded-full transition-all duration-200
                    ${formData.metadata_skip
                      ? 'bg-gradient-to-r from-camel to-terra shadow-[0_0_8px_rgba(212,165,116,0.3)]'
                      : 'bg-elevated hover:bg-raised'
                    }
                  `}
                >
                  <span
                    className={`
                      absolute top-0.5 left-0.5 w-4 h-4 rounded-full transition-all duration-200
                      ${formData.metadata_skip
                        ? 'translate-x-5 bg-white shadow-md'
                        : 'translate-x-0 bg-muted'
                      }
                    `}
                  />
                </button>
                <div>
                  <span className="text-sm text-secondary group-hover:text-primary transition-colors">
                    Skip AI suggestions for this source
                  </span>
                  <p className="text-xs text-muted mt-0.5">
                    Exclude from batch AI metadata processing
                  </p>
                </div>
              </label>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-4 border-t border-subtle">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2.5 px-4 bg-raised hover:bg-elevated text-secondary rounded-lg transition-colors text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={updateDocument.isPending}
              className="flex-1 py-2.5 px-4 bg-gradient-to-r from-camel to-terra text-base font-medium rounded-lg hover:shadow-lg hover:shadow-camel/30 transition-all disabled:opacity-50"
            >
              {updateDocument.isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>

        {/* Diff Preview Modal */}
        {pendingMetadata && (
          <MetadataDiffPreview
            currentData={formData}
            changes={pendingMetadata.changes}
            onApply={handleApplyMetadata}
            onCancel={() => setPendingMetadata(null)}
          />
        )}
      </div>
    </div>
  )
}
