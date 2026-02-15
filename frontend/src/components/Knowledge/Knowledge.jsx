import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAllNotes, useAllHighlights, useTags, useGluonSearch, useDeleteNote, useAllPeople, useDeleteGluon } from '../../hooks/useApi'
import { useAllConversations, useDeleteConversation } from '../../hooks/useCouncil'
import { MarkdownPreview, useRefNavigation } from '../../utils/markdown'
import JournalPanel from './JournalPanel'

/**
 * Knowledge View
 * ==============
 * System-wide view for browsing all notes, tags, and searching across gluons.
 * Separate from the Reader - this is for cross-document knowledge exploration.
 */

// Hand-drawn spark element for Knowledge view
function SparkSVG({ className = "" }) {
  return (
    <svg
      className={className}
      width="44"
      height="44"
      viewBox="0 0 48 48"
      fill="none"
      style={{ opacity: 0.45 }}
    >
      <path d="M24 8 L24 40 M8 24 L40 24 M12 12 L36 36 M36 12 L12 36" stroke="#d4a574" strokeWidth="2" strokeLinecap="round"/>
      <circle cx="24" cy="24" r="3" fill="#d4a574"/>
    </svg>
  )
}

export default function Knowledge() {
  const [searchParams, setSearchParams] = useSearchParams()
  const initialQuery = searchParams.get('q') || ''
  const initialTab = searchParams.get('tab') || 'notes'

  const [activeTab, setActiveTabState] = useState(initialTab)
  const [searchQuery, setSearchQuery] = useState(initialQuery)
  const [selectedTag, setSelectedTag] = useState(null)

  // Sync tab to URL so back-navigation preserves it
  const setActiveTab = (tab) => {
    setActiveTabState(tab)
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (tab === 'notes') {
        next.delete('tab')
      } else {
        next.set('tab', tab)
      }
      return next
    }, { replace: true })
  }

  // Update search when URL query changes (e.g., navigating from a [[ref]] click)
  useEffect(() => {
    const q = searchParams.get('q')
    if (q && q !== searchQuery) {
      setSearchQuery(q)
    }
  }, [searchParams])

  return (
    <div className="min-h-screen bg-base">
      {/* Header */}
      <header className="border-b border-raised bg-surface">
        <div className="max-w-6xl mx-auto px-8 py-6">
          {/* Top row: back link + title + search */}
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-6">
              <Link to="/" className="text-tertiary hover:text-secondary transition-colors text-sm">
                ← Library
              </Link>
              <div className="relative">
                <h1 className="font-display text-4xl text-primary">
                  Knowledge
                </h1>
                {/* Hand-drawn spark positioned to the right of title */}
                <SparkSVG className="absolute -top-2 -right-12" />
              </div>
            </div>

            {/* Search bar */}
            <div className="flex-1 max-w-md ml-8">
              <input
                type="text"
                placeholder="Search notes and tags..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full px-4 py-2 bg-base border border-subtle rounded-lg
                           text-primary placeholder:text-muted
                           focus:outline-none focus:border-camel
                           shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
              />
            </div>
          </div>

          {/* Tabs */}
          <div className="flex gap-1">
            <TabButton
              active={activeTab === 'notes'}
              onClick={() => { setActiveTab('notes'); setSelectedTag(null); }}
            >
              Notes
            </TabButton>
            <TabButton
              active={activeTab === 'highlights'}
              onClick={() => setActiveTab('highlights')}
            >
              Highlights
            </TabButton>
            <TabButton
              active={activeTab === 'tags'}
              onClick={() => setActiveTab('tags')}
            >
              Tags
            </TabButton>
            <TabButton
              active={activeTab === 'people'}
              onClick={() => setActiveTab('people')}
            >
              People
            </TabButton>
            <TabButton
              active={activeTab === 'journal'}
              onClick={() => setActiveTab('journal')}
            >
              Journal
            </TabButton>
            <TabButton
              active={activeTab === 'chats'}
              onClick={() => setActiveTab('chats')}
            >
              Chats
            </TabButton>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-8 py-8">
        {activeTab === 'notes' && (
          <NotesPanel
            searchQuery={searchQuery}
            selectedTag={selectedTag}
            onTagClick={(tag) => { setSelectedTag(tag); setActiveTab('notes'); }}
          />
        )}
        {activeTab === 'highlights' && (
          <HighlightsPanel searchQuery={searchQuery} />
        )}
        {activeTab === 'tags' && (
          <TagsPanel
            searchQuery={searchQuery}
            onTagClick={(tag) => { setSelectedTag(tag); setActiveTab('notes'); }}
          />
        )}
        {activeTab === 'people' && (
          <PeoplePanel searchQuery={searchQuery} />
        )}
        {activeTab === 'journal' && (
          <JournalPanel searchQuery={searchQuery} />
        )}
        {activeTab === 'chats' && (
          <ChatsPanel searchQuery={searchQuery} />
        )}
      </main>
    </div>
  )
}


function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium transition-colors
        ${active
          ? 'text-camel border-b-2 border-camel'
          : 'text-tertiary hover:text-secondary border-b-2 border-transparent'
        }`}
    >
      {children}
    </button>
  )
}


function NotesPanel({ searchQuery, selectedTag, onTagClick }) {
  const navigate = useNavigate()
  const { data: notes, isLoading, error } = useAllNotes()
  const { data: searchResults } = useGluonSearch(searchQuery, 'note')
  const deleteNote = useDeleteNote()

  // Use search results if searching, otherwise all notes
  const displayNotes = searchQuery ? searchResults : notes

  // Filter by tag if selected (use note.tags from API, not content parsing)
  const filteredNotes = selectedTag && displayNotes
    ? displayNotes.filter(note =>
        note.tags?.some(tag => tag.name.toLowerCase() === selectedTag.toLowerCase())
      )
    : displayNotes

  if (isLoading) {
    return <div className="text-secondary">Loading notes...</div>
  }

  if (error) {
    return <div className="text-red-400">Error loading notes: {error.message}</div>
  }

  const notesList = filteredNotes || []

  return (
    <div>
      {/* Header with count and filter info */}
      <div className="flex items-center justify-between mb-4">
        <p className="label text-camel">
          {notesList.length} Note{notesList.length !== 1 ? 's' : ''}
          {selectedTag && (
            <span className="ml-2 normal-case tracking-normal font-normal text-tertiary">
              tagged with <span className="text-camel">#{selectedTag}</span>
              <button
                onClick={() => onTagClick(null)}
                className="ml-2 text-muted hover:text-secondary"
              >
                ✕
              </button>
            </span>
          )}
          {searchQuery && (
            <span className="ml-2 normal-case tracking-normal font-normal text-tertiary">
              matching "<span className="text-camel">{searchQuery}</span>"
            </span>
          )}
        </p>
      </div>

      {/* Notes list */}
      {notesList.length === 0 ? (
        <div className="text-muted text-center py-12">
          {searchQuery || selectedTag ? 'No matching notes found' : 'No notes yet. Create notes in the Reader.'}
        </div>
      ) : (
        <div className="space-y-3">
          {notesList.map(note => (
            <NoteCard
              key={note.id}
              note={note}
              onOpenNote={() => navigate(`/gluon/${note.id}`)}
              onNavigate={() => {
                if (note.source_id) {
                  navigate(`/read/${note.source_id}`)
                }
              }}
              onTagClick={onTagClick}
              onDelete={() => {
                if (confirm('Delete this note?')) {
                  deleteNote.mutate(note.id)
                }
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}


function NoteCard({ note, onNavigate, onTagClick, onDelete, onOpenNote }) {
  const tagList = note.tags || []
  const navigateToRef = useRefNavigation()

  return (
    <div
      onClick={onOpenNote}
      className="group bg-surface border border-transparent rounded-lg p-4 hover:border-camel/40 hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)] transition-all duration-200 shadow-lg cursor-pointer"
    >
      {/* Document source */}
      {note.source_title && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(); }}
          className="text-xs text-camel/70 hover:text-camel mb-2 flex items-center gap-1 transition-colors"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {note.source_title}
        </button>
      )}

      {/* Main row: content left, tags right */}
      <div className="flex items-start gap-4">
        {/* Note content - takes remaining space */}
        <div className="flex-1 text-secondary min-w-0">
          <MarkdownPreview content={note.content} maxLength={200} navigateToRef={navigateToRef} />
        </div>

        {/* Tags - right side, natural width, right-aligned */}
        {tagList.length > 0 && (
          <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
            {tagList.map((tag) => (
              <Link
                key={tag.id}
                to={`/gluon/${tag.id}`}
                onClick={(e) => e.stopPropagation()}
                className="px-2.5 py-0.5 text-xs bg-terra text-base font-medium rounded-full
                           hover:bg-terra/90 transition-colors whitespace-nowrap"
              >
                {tag.name}
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="mt-3 flex items-center justify-between text-xs text-muted">
        <span>{new Date(note.created_at).toLocaleDateString()}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="opacity-0 group-hover:opacity-100 text-muted hover:text-red-400 transition-all"
        >
          Delete
        </button>
      </div>
    </div>
  )
}


// NoteContent removed - now using MarkdownPreview from utils/markdown.jsx


// Highlight colors (matching Reader)
const HIGHLIGHT_COLORS = {
  yellow: { bg: 'bg-yellow-500/20', border: '#facc15' },
  blue: { bg: 'bg-blue-500/20', border: '#3b82f6' },
  green: { bg: 'bg-green-500/20', border: '#22c55e' },
  pink: { bg: 'bg-pink-500/20', border: '#ec4899' },
}

function HighlightsPanel({ searchQuery }) {
  const navigate = useNavigate()
  const { data: highlights, isLoading, error } = useAllHighlights()

  if (isLoading) {
    return <div className="text-secondary">Loading highlights...</div>
  }

  if (error) {
    return <div className="text-red-400">Error loading highlights: {error.message}</div>
  }

  // Filter by search
  const filteredHighlights = searchQuery
    ? (highlights || []).filter(h =>
        h.content?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        h.source_title?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : (highlights || [])

  // Sort by date (newest first)
  const sortedHighlights = [...filteredHighlights].sort(
    (a, b) => new Date(b.created_at) - new Date(a.created_at)
  )

  return (
    <div>
      <p className="label text-camel mb-4">
        {sortedHighlights.length} Highlight{sortedHighlights.length !== 1 ? 's' : ''}
      </p>

      {sortedHighlights.length === 0 ? (
        <div className="text-muted text-center py-12">
          {searchQuery ? 'No matching highlights found' : 'No highlights yet. Highlight text in the Reader.'}
        </div>
      ) : (
        <div className="space-y-3">
          {sortedHighlights.map(highlight => (
            <HighlightCard
              key={highlight.id}
              highlight={highlight}
              onNavigate={() => {
                if (highlight.source_id) {
                  navigate(`/read/${highlight.source_id}`)
                }
              }}
              onOpenHighlight={() => navigate(`/gluon/${highlight.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function HighlightCard({ highlight, onNavigate, onOpenHighlight }) {
  const colorConfig = HIGHLIGHT_COLORS[highlight.color] || HIGHLIGHT_COLORS.yellow

  return (
    <div
      onClick={onOpenHighlight}
      className="group bg-surface border border-transparent rounded-lg p-4 hover:border-camel/40 hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)] transition-all duration-200 shadow-lg cursor-pointer"
    >
      {/* Document source */}
      {highlight.source_title && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(); }}
          className="text-xs text-camel/70 hover:text-camel mb-2 flex items-center gap-1 transition-colors"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {highlight.source_title}
        </button>
      )}

      {/* Highlight content with color indicator */}
      <div className="flex items-start gap-3">
        <div
          className="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
          style={{ backgroundColor: colorConfig.border }}
        />
        <p className="text-secondary group-hover:text-primary transition-colors flex-1">
          {highlight.content}
        </p>
      </div>

      {/* Footer */}
      <div className="mt-3 flex items-center justify-between text-xs text-muted">
        <span>{new Date(highlight.created_at).toLocaleDateString()}</span>
      </div>
    </div>
  )
}


const TAG_SORT_OPTIONS = [
  { key: 'usage', label: 'Most Used' },
  { key: 'az', label: 'A → Z' },
  { key: 'za', label: 'Z → A' },
]

function sortTags(tags, sortKey) {
  return [...tags].sort((a, b) => {
    if (sortKey === 'az') return (a.name || '').localeCompare(b.name || '')
    if (sortKey === 'za') return (b.name || '').localeCompare(a.name || '')
    return (b.usage_count || 0) - (a.usage_count || 0)
  })
}

function TagsPanel({ searchQuery, onTagClick }) {
  const { data: tags, isLoading, error } = useTags()
  const [sortBy, setSortBy] = useState('usage')

  if (isLoading) {
    return <div className="text-secondary">Loading tags...</div>
  }

  if (error) {
    return <div className="text-red-400">Error loading tags: {error.message}</div>
  }

  // Filter by search (API returns 'name', not 'content')
  const filteredTags = searchQuery
    ? (tags || []).filter(tag =>
        tag.name?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : (tags || [])

  const sortedTags = sortTags(filteredTags, sortBy)

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="label text-camel">
          {sortedTags.length} Tag{sortedTags.length !== 1 ? 's' : ''}
        </p>
        <div className="flex gap-1">
          {TAG_SORT_OPTIONS.map(opt => (
            <button
              key={opt.key}
              onClick={() => setSortBy(opt.key)}
              className={`px-2 py-0.5 text-xs rounded transition-colors ${
                sortBy === opt.key
                  ? 'bg-camel/20 text-camel font-semibold'
                  : 'text-muted hover:text-secondary'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {sortedTags.length === 0 ? (
        <div className="text-muted text-center py-12">
          {searchQuery ? 'No matching tags found' : 'No tags yet. Add ##tags to your notes.'}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {sortedTags.map(tag => (
            <Link
              key={tag.id}
              to={`/gluon/${tag.id}`}
              className="inline-flex items-center gap-2 px-3 py-1 text-sm rounded-full
                         bg-terra text-base font-medium
                         hover:bg-terra/90 transition-colors"
            >
              <span>{tag.name}</span>
              <span className="text-xs opacity-80 bg-black/20 px-1.5 py-0.5 rounded-full">
                {tag.usage_count || 0}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}


function PeoplePanel({ searchQuery }) {
  const navigate = useNavigate()
  const { data: people, isLoading, error } = useAllPeople()
  const deleteGluon = useDeleteGluon()

  if (isLoading) {
    return <div className="text-secondary">Loading people...</div>
  }

  if (error) {
    return <div className="text-red-400">Error loading people: {error.message}</div>
  }

  // Filter by search
  const filteredPeople = searchQuery
    ? (people || []).filter(person =>
        person.name?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : (people || [])

  // Sort alphabetically
  const sortedPeople = [...filteredPeople].sort((a, b) =>
    (a.name || '').localeCompare(b.name || '')
  )

  const handleDelete = async (person, e) => {
    e.preventDefault()
    e.stopPropagation()
    if (confirm(`Delete "${person.name}"? This will unlink them from any documents.`)) {
      try {
        await deleteGluon.mutateAsync({ id: person.id, force: true })
      } catch (err) {
        alert('Failed to delete: ' + err.message)
      }
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <p className="label text-camel">
          {sortedPeople.length} {sortedPeople.length === 1 ? 'Person' : 'People'}
        </p>
        <p className="text-xs text-tertiary">
          People are authors/editors linked to documents
        </p>
      </div>

      {sortedPeople.length === 0 ? (
        <div className="text-muted text-center py-12">
          {searchQuery
            ? 'No matching people found'
            : 'No people yet. Add authors in document metadata to create Person entries.'
          }
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {sortedPeople.map(person => (
            <div
              key={person.id}
              onClick={() => navigate(`/gluon/${person.id}`)}
              className="group relative bg-surface border border-transparent rounded-lg p-4
                         hover:border-camel/40 hover:-translate-y-0.5
                         hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)]
                         transition-all duration-200 shadow-lg cursor-pointer"
            >
              {/* Delete button */}
              <button
                onClick={(e) => handleDelete(person, e)}
                className="absolute top-2 right-2 p-1 rounded transition-all
                           text-muted hover:text-red-400 hover:bg-red-900/30
                           opacity-0 group-hover:opacity-100"
                title="Delete person"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>

              {/* Person icon */}
              <div className="w-10 h-10 rounded-full bg-camel/20 flex items-center justify-center mb-3">
                <svg className="w-5 h-5 text-camel" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>

              {/* Name */}
              <p className="text-primary font-medium group-hover:text-camel transition-colors truncate">
                {person.name}
              </p>

              {/* Date */}
              <p className="text-xs text-muted mt-1">
                Added {new Date(person.created_at).toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


function ChatsPanel({ searchQuery }) {
  const navigate = useNavigate()
  const { data: conversations, isLoading, error } = useAllConversations()
  const deleteConversation = useDeleteConversation()

  if (isLoading) {
    return <div className="text-secondary">Loading conversations...</div>
  }

  if (error) {
    return <div className="text-red-400">Error loading conversations: {error.message}</div>
  }

  // Filter by search query against preview text and source title
  const filtered = searchQuery
    ? (conversations || []).filter(c =>
        c.first_message_preview?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.source_title?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.source_author?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : (conversations || [])

  // Format relative time
  const relativeTime = (dateStr) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now - date
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return 'Today'
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays}d ago`
    if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`
    return date.toLocaleDateString()
  }

  return (
    <div>
      <p className="label text-camel mb-4">
        {filtered.length} Conversation{filtered.length !== 1 ? 's' : ''}
        {searchQuery && (
          <span className="ml-2 normal-case tracking-normal font-normal text-tertiary">
            matching "<span className="text-camel">{searchQuery}</span>"
          </span>
        )}
      </p>

      {filtered.length === 0 ? (
        <div className="text-muted text-center py-12">
          {searchQuery ? 'No matching conversations found' : 'No conversations yet. Start chatting with documents in the Reader.'}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map(conv => (
            <div
              key={conv.id}
              onClick={() => navigate(`/read/${conv.source_id}?conversation=${conv.id}`)}
              className="group bg-surface border border-transparent rounded-lg p-4 hover:border-camel/40 hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)] transition-all duration-200 shadow-lg cursor-pointer"
            >
              {/* Source info — clicking this opens the source document */}
              {conv.source_title && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    navigate(`/read/${conv.source_id}`)
                  }}
                  className="flex items-center gap-1 text-xs text-camel/70 hover:text-camel mb-2 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  <span className="truncate">{conv.source_title}</span>
                  {conv.source_author && (
                    <span className="text-muted"> — {conv.source_author}</span>
                  )}
                </button>
              )}

              {/* Preview */}
              <p className="text-secondary text-sm leading-relaxed line-clamp-2">
                {conv.first_message_preview || conv.title || `Conversation ${conv.id}`}
              </p>

              {/* Footer */}
              <div className="mt-3 flex items-center justify-between text-xs text-muted">
                <div className="flex items-center gap-3">
                  <span>{conv.message_count} message{conv.message_count !== 1 ? 's' : ''}</span>
                  <span>{relativeTime(conv.updated_at)}</span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (confirm('Delete this conversation?')) {
                      deleteConversation.mutate(conv.id)
                    }
                  }}
                  className="opacity-0 group-hover:opacity-100 text-muted hover:text-red-400 transition-all"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
