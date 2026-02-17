import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
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
import AutocompleteTextarea from '../common/AutocompleteTextarea'

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
  const createEntry = useCreateJournalEntry()
  const queryClient = useQueryClient()

  // Derive category and is_task from ##tags in content at submit time
  const deriveCategory = (text) => {
    const tagMatches = text.match(/##(\w+)/g)
    const tags = tagMatches ? tagMatches.map(t => t.slice(2).toLowerCase()) : []
    const priority = ['task', 'idea', 'social', 'admin', 'inbox']
    const category = tags.find(t => priority.includes(t)) || tags[0] || 'inbox'
    return { category, isTask: category === 'task' }
  }

  const handleSubmit = async () => {
    if (!content.trim()) return
    const { category, isTask } = deriveCategory(content)

    try {
      await createEntry.mutateAsync({
        content: content.trim(),
        body: body.trim() || null,
        category,
        is_task: isTask,
      })
      await queryClient.refetchQueries({ queryKey: ['journal'] })
      setContent('')
      setBody('')
      onClose()
    } catch (err) {
      console.error('Failed to create journal entry:', err)
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); handleSubmit() }} className="bg-surface border border-subtle rounded-lg p-4 mb-6">
      {/* Content input with [[ref]] and ##tag autocomplete */}
      <AutocompleteTextarea
        value={content}
        onChange={setContent}
        onSubmit={handleSubmit}
        onCancel={onClose}
        placeholder="What's on your mind?  Use ##tag to categorize, [[name]] to reference"
        autoFocus
        inputMode="input"
        className="mb-3"
      />

      {/* Details textarea with autocomplete */}
      <AutocompleteTextarea
        value={body}
        onChange={setBody}
        onCancel={onClose}
        placeholder="Details (optional, one per line)..."
        rows={2}
        inputMode="textarea"
        className="mb-3"
      />

      {/* Submit row */}
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted">
          <span className="text-pink-400">##task</span> <span className="text-pink-400">##idea</span> <span className="text-pink-400">##social</span> — or any custom tag
        </p>
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
              tagMap={tagMap}
            />
          )
        })}
      </div>
    </div>
  )
}


function CategorySection({ category, tagId, entries, tagMap }) {
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
          <JournalEntryRow key={entry.id} entry={entry} primaryCategory={category} tagMap={tagMap} />
        ))}
      </div>
    </div>
  )
}


const COLLAPSE_THRESHOLD = 2

/**
 * Parse body text into sub-tasks, regular lines, and completion comments.
 *
 * Sub-tasks: lines starting with [ ] or [x]
 * Regular lines: any other non-empty lines before the --- separator
 * Completion comments: lines after the --- separator
 *
 * @returns {object} { subTasks: [{text, completed}], otherLines: [string], completionComments: [string] }
 */
function parseBodyContent(body) {
  if (!body) return { subTasks: [], otherLines: [], completionComments: [] }

  const lines = body.split('\n')
  const subTasks = []
  const otherLines = []
  const completionComments = []
  let reachedSeparator = false

  for (const line of lines) {
    const trimmed = line.trim()

    if (trimmed === '---') {
      reachedSeparator = true
      continue
    }

    if (reachedSeparator) {
      if (trimmed) completionComments.push(trimmed)
    } else if (trimmed.startsWith('[ ]')) {
      subTasks.push({ text: trimmed.slice(3).trim(), completed: false })
    } else if (trimmed.startsWith('[x]')) {
      subTasks.push({ text: trimmed.slice(3).trim(), completed: true })
    } else if (trimmed) {
      otherLines.push(trimmed)
    }
  }

  return { subTasks, otherLines, completionComments }
}

function CollapsibleBody({ lines, subTasks, onToggleSubTask }) {
  const [expanded, setExpanded] = useState(false)
  const totalItems = subTasks.length + lines.length
  const canCollapse = totalItems > COLLAPSE_THRESHOLD

  // Calculate how many of each type to show when collapsed
  const visibleSubTasks = canCollapse && !expanded
    ? subTasks.slice(0, Math.min(COLLAPSE_THRESHOLD, subTasks.length))
    : subTasks
  const remainingSlots = canCollapse && !expanded
    ? Math.max(0, COLLAPSE_THRESHOLD - visibleSubTasks.length)
    : lines.length
  const visibleLines = lines.slice(0, remainingSlots)

  const hiddenCount = totalItems - (visibleSubTasks.length + visibleLines.length)

  return (
    <ul className="mt-1 space-y-0.5 pl-3">
      {/* Sub-task checkboxes */}
      {visibleSubTasks.map((st, i) => (
        <li key={`subtask-${i}`} className="text-xs text-tertiary flex items-start gap-1.5">
          <input
            type="checkbox"
            checked={st.completed}
            onChange={(e) => {
              e.stopPropagation()
              onToggleSubTask(i)
            }}
            className="mt-0.5 w-3 h-3 rounded border border-muted cursor-pointer hover:border-camel transition-colors"
          />
          <span className={st.completed ? 'line-through text-muted' : ''}>{st.text}</span>
        </li>
      ))}

      {/* Regular lines */}
      {visibleLines.map((line, i) => (
        <li key={`line-${i}`} className="text-xs text-tertiary flex items-start gap-1.5">
          <span className="text-muted mt-0.5">–</span>
          <span>{line}</span>
        </li>
      ))}

      {canCollapse && (
        <li className="text-xs">
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            className="text-muted hover:text-camel transition-colors flex items-center gap-1"
          >
            <svg
              className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
            {expanded ? 'Show less' : `${hiddenCount} more...`}
          </button>
        </li>
      )}
    </ul>
  )
}


function JournalEntryRow({ entry, primaryCategory, tagMap = {} }) {
  const navigateToRef = useRefNavigation()
  const toggleComplete = useToggleJournalComplete()
  const deleteEntry = useDeleteJournalEntry()
  const updateEntry = useUpdateJournalEntry()
  const queryClient = useQueryClient()

  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [editBody, setEditBody] = useState('')
  const [showCompletionInput, setShowCompletionInput] = useState(false)
  const [completionNote, setCompletionNote] = useState('')
  const editRef = useRef(null)
  const editContainerRef = useRef(null)

  const isTask = entry.completed !== null && entry.completed !== undefined
  const isCompleted = entry.completed === 1

  // Parse body content
  const { subTasks, otherLines, completionComments } = parseBodyContent(entry.body)
  const completedSubTasks = subTasks.filter(st => st.completed).length

  // Focus input when entering edit mode
  useEffect(() => {
    if (isEditing && editRef.current) {
      editRef.current.focus()
      editRef.current.selectionStart = editRef.current.value.length
    }
  }, [isEditing])

  const handleCheckbox = (e) => {
    e.stopPropagation()

    if (!isCompleted && isTask) {
      // About to mark complete — show completion note input
      setShowCompletionInput(true)
    } else {
      // Unchecking — just toggle
      toggleComplete.mutate({ id: entry.id, completed: !isCompleted })
    }
  }

  const handleSaveCompletion = async () => {
    // Append completion comment to body with separator if note provided
    const timestamp = new Date().toISOString().split('T')[0]
    const separator = '\n\n---\n'
    const comment = completionNote.trim()
      ? `Completed ${timestamp}: ${completionNote.trim()}`
      : `Completed ${timestamp}`
    const newBody = (entry.body || '') + separator + comment

    try {
      await updateEntry.mutateAsync({
        id: entry.id,
        body: newBody
      })
      await toggleComplete.mutateAsync({ id: entry.id, completed: true })
      await queryClient.refetchQueries({ queryKey: ['journal'] })

      setShowCompletionInput(false)
      setCompletionNote('')
    } catch (err) {
      console.error('Failed to save completion:', err)
    }
  }

  const handleToggleSubTask = async (index) => {
    // Toggle the sub-task at the given index
    const updatedSubTasks = [...subTasks]
    updatedSubTasks[index].completed = !updatedSubTasks[index].completed

    // Reconstruct body with updated sub-tasks
    const subTaskLines = updatedSubTasks.map(st =>
      `[${st.completed ? 'x' : ' '}] ${st.text}`
    )
    const bodyParts = [...subTaskLines, ...otherLines]

    // Preserve completion comments if they exist
    if (completionComments.length > 0) {
      bodyParts.push('', '---', ...completionComments)
    }

    const newBody = bodyParts.join('\n')

    try {
      await updateEntry.mutateAsync({
        id: entry.id,
        body: newBody
      })
      await queryClient.refetchQueries({ queryKey: ['journal'] })
    } catch (err) {
      console.error('Failed to toggle sub-task:', err)
    }
  }

  const handleSave = () => {
    const trimmed = editContent.trim()
    if (!trimmed) { setIsEditing(false); return }
    // Always send update — tags may have changed even if text looks "same"
    updateEntry.mutate({
      id: entry.id,
      content: trimmed,
      body: editBody.trim() || null,
    })
    setIsEditing(false)
  }

  const handleDelete = (e) => {
    e.stopPropagation()
    if (confirm('Delete this journal entry?')) {
      deleteEntry.mutate(entry.id)
    }
  }

  // Tags other than the primary grouping category
  const secondaryTags = entry.tags?.filter(t => t !== primaryCategory) || []

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
            <AutocompleteTextarea
              value={editContent}
              onChange={setEditContent}
              onSubmit={handleSave}
              onCancel={() => setIsEditing(false)}
              inputMode="input"
              autoFocus
              inputRef={editRef}
            />
            <AutocompleteTextarea
              value={editBody}
              onChange={setEditBody}
              onCancel={() => setIsEditing(false)}
              placeholder="Details..."
              rows={2}
              inputMode="textarea"
              className="mt-1"
            />
          </div>
        ) : (
          <div
            onClick={() => {
              // Inject existing tags as ##tag if not already in content text
              let content = entry.content || ''
              const existingInline = (content.match(/##(\w+)/g) || []).map(t => t.slice(2).toLowerCase())
              const missingTags = (entry.tags || []).filter(t => !existingInline.includes(t.toLowerCase()))
              if (missingTags.length > 0) {
                content = content + ' ' + missingTags.map(t => `##${t}`).join(' ')
              }
              setEditContent(content)
              setEditBody(entry.body || '')
              setIsEditing(true)
            }}
            className="cursor-text"
          >
            {/* Header/content with progress badge */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-sm ${
                isCompleted ? 'line-through text-muted' : 'text-secondary'
              }`}>
                <MarkdownPreview content={entry.content} maxLength={300} navigateToRef={navigateToRef} />
              </span>

              {/* Sub-task progress badge */}
              {isTask && subTasks.length > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] font-medium rounded
                               bg-camel/10 text-camel/60 border border-camel/15">
                  {completedSubTasks}/{subTasks.length}
                </span>
              )}
            </div>

            {/* Sub-tasks and regular lines (collapsible when >2 total items) */}
            {(subTasks.length > 0 || otherLines.length > 0) && (
              <CollapsibleBody
                lines={otherLines}
                subTasks={subTasks}
                onToggleSubTask={handleToggleSubTask}
              />
            )}

            {/* Completion comments (always visible when present) */}
            {completionComments.length > 0 && (
              <div className="mt-2 pt-2 border-t border-subtle">
                {completionComments.map((comment, i) => (
                  <p key={i} className="text-xs text-muted italic">
                    {comment}
                  </p>
                ))}
              </div>
            )}

            {/* Completion note input (shown when marking task complete) */}
            {showCompletionInput && (
              <div className="mt-2 pt-2 border-t border-subtle" onClick={(e) => e.stopPropagation()}>
                <input
                  type="text"
                  value={completionNote}
                  onChange={(e) => setCompletionNote(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      handleSaveCompletion()
                    } else if (e.key === 'Escape') {
                      setShowCompletionInput(false)
                      setCompletionNote('')
                    }
                  }}
                  placeholder="Add completion note (optional)..."
                  autoFocus
                  className="w-full px-2 py-1 text-xs bg-base border border-subtle rounded
                             focus:outline-none focus:border-camel transition-colors"
                />
                <div className="flex gap-2 mt-1">
                  <button
                    onClick={handleSaveCompletion}
                    className="px-2 py-1 text-xs font-medium bg-camel text-base rounded
                               hover:bg-camel/90 transition-colors"
                  >
                    Complete
                  </button>
                  <button
                    onClick={() => {
                      setShowCompletionInput(false)
                      setCompletionNote('')
                    }}
                    className="px-2 py-1 text-xs text-muted hover:text-secondary transition-colors"
                  >
                    Skip
                  </button>
                </div>
              </div>
            )}

          </div>
        )}
      </div>

      {/* Secondary tag badges — right-aligned, matching Library KeywordChip style */}
      {!isEditing && secondaryTags.length > 0 && (
        <div className="flex flex-wrap gap-1 flex-shrink-0 items-start mt-0.5">
          {secondaryTags.map(tag => (
            tagMap[tag] ? (
              <Link
                key={tag}
                to={`/gluon/${tagMap[tag]}`}
                onClick={(e) => e.stopPropagation()}
                className="px-2 py-0.5 rounded text-[10px] font-medium transition-all
                           bg-camel/10 text-camel/60 border border-camel/15
                           hover:bg-camel/20 hover:text-camel/80"
              >
                {tag}
              </Link>
            ) : (
              <span
                key={tag}
                className="px-2 py-0.5 rounded text-[10px] font-medium
                           bg-camel/10 text-camel/60 border border-camel/15"
              >
                {tag}
              </span>
            )
          ))}
        </div>
      )}

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
