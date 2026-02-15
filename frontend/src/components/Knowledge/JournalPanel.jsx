import { useState, useRef, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  useJournalEntries,
  useJournalCategories,
  useCreateJournalEntry,
  useUpdateJournalEntry,
  useToggleJournalComplete,
  useDeleteJournalEntry,
} from '../../hooks/useApi'
import { MarkdownPreview, useRefNavigation } from '../../utils/markdown'

/**
 * JournalPanel
 * ============
 * Daily journal view with entries grouped by date then category.
 * Tasks have checkboxes. Inline editing on click. Manual entry creation.
 */

const DEFAULT_CATEGORIES = ['task', 'idea', 'social', 'admin', 'inbox']

const CATEGORY_ICONS = {
  task: '☐',
  idea: '✦',
  social: '◉',
  admin: '⚙',
  inbox: '•',
}

function formatDateHeading(dateStr) {
  const date = new Date(dateStr + 'T00:00:00')
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  const dateOnly = new Date(date)
  dateOnly.setHours(0, 0, 0, 0)

  if (dateOnly.getTime() === today.getTime()) return 'Today'
  if (dateOnly.getTime() === yesterday.getTime()) return 'Yesterday'

  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  })
}

export default function JournalPanel({ searchQuery }) {
  const [categoryFilter, setCategoryFilter] = useState(null)
  const [isCreating, setIsCreating] = useState(false)

  const { data, isLoading, error } = useJournalEntries(30, categoryFilter)
  const { data: categories } = useJournalCategories()

  // Build filter chip list: "All" + dynamic categories from DB
  const filterChips = [{ key: null, label: 'All' }]
  if (categories) {
    for (const cat of categories) {
      filterChips.push({ key: cat.name, label: cat.name.charAt(0).toUpperCase() + cat.name.slice(1) })
    }
  } else {
    // Fallback before categories load
    for (const name of DEFAULT_CATEGORIES) {
      filterChips.push({ key: name, label: name.charAt(0).toUpperCase() + name.slice(1) })
    }
  }

  if (isLoading) {
    return <div className="text-secondary">Loading journal...</div>
  }

  if (error) {
    return <div className="text-red-400">Error loading journal: {error.message}</div>
  }

  const entries = data?.entries || {}
  const tagMap = data?.tag_map || {}

  const dateKeys = Object.keys(entries).sort().reverse()

  // Filter by search query (client-side on content + body)
  const filteredDates = searchQuery
    ? dateKeys.filter(date => {
        const cats = entries[date]
        return Object.values(cats).some(catEntries =>
          catEntries.some(e =>
            e.content?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            e.body?.toLowerCase().includes(searchQuery.toLowerCase())
          )
        )
      })
    : dateKeys

  // Count total entries
  let totalCount = 0
  for (const date of filteredDates) {
    for (const catEntries of Object.values(entries[date])) {
      totalCount += catEntries.length
    }
  }

  return (
    <div>
      {/* Header row: count + filters + new entry button */}
      <div className="flex items-center justify-between mb-6">
        <p className="label text-camel">
          {totalCount} Entr{totalCount !== 1 ? 'ies' : 'y'}
          {searchQuery && (
            <span className="ml-2 normal-case tracking-normal font-normal text-tertiary">
              matching "<span className="text-camel">{searchQuery}</span>"
            </span>
          )}
        </p>

        <button
          onClick={() => setIsCreating(!isCreating)}
          className="px-3 py-1.5 text-sm font-medium bg-camel text-base rounded-lg
                     hover:bg-camel/90 transition-colors"
        >
          + New Entry
        </button>
      </div>

      {/* Category filter chips (dynamic from DB) */}
      <div className="flex flex-wrap gap-1.5 mb-6">
        {filterChips.map(cat => (
          <button
            key={cat.key || 'all'}
            onClick={() => setCategoryFilter(cat.key)}
            className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
              categoryFilter === cat.key
                ? 'bg-camel/20 text-camel'
                : 'bg-raised text-tertiary hover:text-secondary'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* New entry form */}
      {isCreating && (
        <JournalEntryForm
          onClose={() => setIsCreating(false)}
        />
      )}

      {/* Date groups */}
      {filteredDates.length === 0 ? (
        <div className="text-muted text-center py-12">
          {searchQuery ? 'No matching journal entries' : 'No journal entries yet. Create one above.'}
        </div>
      ) : (
        <div className="space-y-8">
          {filteredDates.map(date => (
            <DateGroup
              key={date}
              date={date}
              categories={entries[date]}
              tagMap={tagMap}
              searchQuery={searchQuery}
            />
          ))}
        </div>
      )}
    </div>
  )
}


function JournalEntryForm({ onClose }) {
  const [content, setContent] = useState('')
  const [body, setBody] = useState('')
  const [category, setCategory] = useState('task')
  const [customTag, setCustomTag] = useState('')
  const [isTask, setIsTask] = useState(true)
  const createEntry = useCreateJournalEntry()
  const queryClient = useQueryClient()
  const inputRef = useRef(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Sync isTask with category
  const handleCategoryChange = (cat) => {
    setCategory(cat)
    setCustomTag('')
    setIsTask(cat === 'task')
  }

  const handleCustomTagSubmit = () => {
    const tag = customTag.trim().toLowerCase()
    if (tag) {
      setCategory(tag)
      setIsTask(tag === 'task')
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!content.trim()) return

    try {
      await createEntry.mutateAsync({
        content: content.trim(),
        body: body.trim() || null,
        category,
        is_task: isTask,
      })
      // Wait for refetch to complete before closing form
      await queryClient.refetchQueries({ queryKey: ['journal'] })
      setContent('')
      setBody('')
      onClose()
    } catch (err) {
      console.error('Failed to create journal entry:', err)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && e.target === inputRef.current) {
      e.preventDefault()
      handleSubmit(e)
    }
    if (e.key === 'Escape') {
      onClose()
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-surface border border-subtle rounded-lg p-4 mb-6">
      {/* Content input */}
      <input
        ref={inputRef}
        type="text"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="What's on your mind?"
        className="w-full px-3 py-2 bg-base border border-subtle rounded-lg
                   text-primary placeholder:text-muted
                   focus:outline-none focus:border-camel transition-colors mb-3"
      />

      {/* Details textarea (optional) */}
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
        placeholder="Details (optional, one per line)..."
        className="w-full px-3 py-2 bg-base border border-subtle rounded-lg
                   text-secondary placeholder:text-muted text-sm
                   focus:outline-none focus:border-camel transition-colors
                   resize-none mb-3"
        rows={2}
      />

      {/* Category selector: suggested chips + custom input */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 flex-wrap">
          {DEFAULT_CATEGORIES.map(cat => (
            <button
              key={cat}
              type="button"
              onClick={() => handleCategoryChange(cat)}
              className={`px-2.5 py-1 text-xs rounded-full transition-colors ${
                category === cat && !customTag
                  ? 'bg-camel/20 text-camel font-semibold'
                  : 'bg-raised text-muted hover:text-secondary'
              }`}
            >
              {cat.charAt(0).toUpperCase() + cat.slice(1)}
            </button>
          ))}
          <input
            type="text"
            value={customTag}
            onChange={(e) => {
              setCustomTag(e.target.value)
              const tag = e.target.value.trim().toLowerCase()
              if (tag) {
                setCategory(tag)
                setIsTask(tag === 'task')
              }
            }}
            onBlur={handleCustomTagSubmit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); handleCustomTagSubmit() }
              if (e.key === 'Escape') onClose()
            }}
            placeholder="custom..."
            className={`px-2.5 py-1 text-xs rounded-full bg-raised text-secondary
                       placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-camel
                       w-20 transition-all ${
                         customTag ? 'ring-1 ring-camel text-camel' : ''
                       }`}
          />
          {/* Show active custom tag as chip */}
          {category && !DEFAULT_CATEGORIES.includes(category) && (
            <span className="px-2.5 py-1 text-xs rounded-full bg-camel/20 text-camel font-semibold">
              {category}
            </span>
          )}
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-muted hover:text-secondary transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!content.trim() || createEntry.isPending}
            className="px-3 py-1.5 text-xs font-medium bg-camel text-base rounded-lg
                       hover:bg-camel/90 disabled:opacity-50 transition-colors"
          >
            {createEntry.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </form>
  )
}


function DateGroup({ date, categories, tagMap, searchQuery }) {
  // Sort categories in a fixed order
  const categoryOrder = ['task', 'idea', 'social', 'admin', 'inbox']
  const catKeys = Object.keys(categories).sort(
    (a, b) => categoryOrder.indexOf(a) - categoryOrder.indexOf(b)
  )

  return (
    <div>
      {/* Date heading — character moment */}
      <h2 className="font-display text-xl text-primary mb-4">
        {formatDateHeading(date)}
        <span className="text-muted text-sm font-sans ml-3">{date}</span>
      </h2>

      <div className="space-y-4 pl-1">
        {catKeys.map(cat => {
          let catEntries = categories[cat]

          // Client-side search filtering
          if (searchQuery) {
            catEntries = catEntries.filter(e =>
              e.content?.toLowerCase().includes(searchQuery.toLowerCase()) ||
              e.body?.toLowerCase().includes(searchQuery.toLowerCase())
            )
          }

          if (catEntries.length === 0) return null

          return (
            <CategorySection
              key={cat}
              category={cat}
              tagId={tagMap[cat]}
              entries={catEntries}
            />
          )
        })}
      </div>
    </div>
  )
}


function CategorySection({ category, tagId, entries }) {
  return (
    <div>
      {tagId ? (
        <Link to={`/gluon/${tagId}`} className="label text-camel mb-2 block hover:text-camel/80 transition-colors">
          {category}
        </Link>
      ) : (
        <p className="label text-camel mb-2">{category}</p>
      )}
      <div className="space-y-1">
        {entries.map(entry => (
          <JournalEntryRow key={entry.id} entry={entry} />
        ))}
      </div>
    </div>
  )
}


function JournalEntryRow({ entry }) {
  const navigate = useNavigate()
  const navigateToRef = useRefNavigation()
  const toggleComplete = useToggleJournalComplete()
  const deleteEntry = useDeleteJournalEntry()
  const updateEntry = useUpdateJournalEntry()

  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState(entry.content)
  const [editBody, setEditBody] = useState(entry.body || '')
  const editRef = useRef(null)
  const editContainerRef = useRef(null)

  const isTask = entry.completed !== null && entry.completed !== undefined
  const isCompleted = entry.completed === 1

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && editRef.current) {
      editRef.current.focus()
      editRef.current.selectionStart = editRef.current.value.length
    }
  }, [isEditing])

  const handleCheckbox = (e) => {
    e.stopPropagation()
    toggleComplete.mutate({ id: entry.id, completed: !isCompleted })
  }

  const handleSave = () => {
    const trimmed = editContent.trim()
    if (trimmed && (trimmed !== entry.content || editBody !== (entry.body || ''))) {
      updateEntry.mutate({
        id: entry.id,
        content: trimmed,
        body: editBody.trim() || null,
      })
    }
    setIsEditing(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault()
      handleSave()
    }
    if (e.key === 'Escape') {
      setEditContent(entry.content)
      setEditBody(entry.body || '')
      setIsEditing(false)
    }
  }

  const handleDelete = (e) => {
    e.stopPropagation()
    if (confirm('Delete this journal entry?')) {
      deleteEntry.mutate(entry.id)
    }
  }

  // Parse body into sub-bullets
  const bodyLines = entry.body
    ? entry.body.split('\n').filter(l => l.trim())
    : []

  return (
    <div className="group flex items-start gap-2 py-1.5 px-2 -mx-2 rounded-lg hover:bg-surface transition-colors">
      {/* Checkbox or bullet */}
      <div className="mt-0.5 flex-shrink-0 w-5">
        {isTask ? (
          <button
            onClick={handleCheckbox}
            className={`w-4 h-4 rounded border transition-colors flex items-center justify-center ${
              isCompleted
                ? 'bg-camel border-camel'
                : 'border-muted hover:border-camel'
            }`}
          >
            {isCompleted && (
              <svg className="w-3 h-3 text-base" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            )}
          </button>
        ) : (
          <span className="text-muted text-xs">{CATEGORY_ICONS[entry.tags?.[0]] || '•'}</span>
        )}
      </div>

      {/* Content area */}
      <div className="flex-1 min-w-0">
        {isEditing ? (
          <div
            ref={editContainerRef}
            onBlur={(e) => {
              // Only save when focus leaves the entire edit container
              // (not when moving between input and textarea within it)
              if (!editContainerRef.current?.contains(e.relatedTarget)) {
                setTimeout(handleSave, 150)
              }
            }}
          >
            <input
              ref={editRef}
              type="text"
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full px-2 py-1 bg-base border border-subtle rounded
                         text-sm text-primary focus:outline-none focus:border-camel"
            />
            <textarea
              value={editBody}
              onChange={(e) => setEditBody(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Details..."
              className="w-full px-2 py-1 mt-1 bg-base border border-subtle rounded
                         text-xs text-secondary focus:outline-none focus:border-camel resize-none"
              rows={2}
            />
          </div>
        ) : (
          <div
            onClick={() => setIsEditing(true)}
            className="cursor-text"
          >
            {/* Header/content */}
            <span className={`text-sm ${
              isCompleted ? 'line-through text-muted' : 'text-secondary'
            }`}>
              <MarkdownPreview content={entry.content} maxLength={300} navigateToRef={navigateToRef} />
            </span>

            {/* Sub-bullets from body */}
            {bodyLines.length > 0 && (
              <ul className="mt-1 space-y-0.5 pl-3">
                {bodyLines.map((line, i) => (
                  <li key={i} className="text-xs text-tertiary flex items-start gap-1.5">
                    <span className="text-muted mt-0.5">–</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            )}

            {/* Person ref chips */}
            {entry.person_refs?.length > 0 && (
              <div className="flex gap-1 mt-1">
                {entry.person_refs.map(person => (
                  <Link
                    key={person.id}
                    to={`/gluon/${person.id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="px-1.5 py-0.5 text-xs bg-camel/15 text-camel rounded
                               hover:bg-camel/25 transition-colors"
                  >
                    {person.name}
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Action buttons (hover-reveal) */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all flex-shrink-0 mt-0.5">
        <Link
          to={`/gluon/${entry.id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-muted hover:text-camel transition-colors"
          title="Open gluon"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </Link>
        <button
          onClick={handleDelete}
          className="text-muted hover:text-red-400 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
