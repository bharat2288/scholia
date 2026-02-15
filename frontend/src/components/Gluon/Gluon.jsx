import { useState, useEffect, useRef, useCallback } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useRem, useCreateNote, useDeleteGluon, useUpdateNote, useRenameGluon, useMergeGluon } from '../../hooks/useApi'
import { TypeIndicator } from '../common/ItemCard'
import { MarkdownContent, useRefNavigation } from '../../utils/markdown'

/**
 * Gluon Page
 * ==========
 * Dedicated view for a single gluon (note, highlight, tag, etc.)
 * Shows the gluon's content and all its connections:
 * - Backlinks (what references this gluon)
 * - Outgoing refs (what this gluon references)
 * - Tags on this gluon
 * - Child notes (for highlights)
 */

// Hand-drawn node/connection element for Gluon view
function NodeSVG({ className = "" }) {
  return (
    <svg
      className={className}
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      style={{ opacity: 0.4 }}
    >
      {/* Central node */}
      <circle cx="24" cy="24" r="6" stroke="#d4a574" strokeWidth="2" fill="none"/>
      {/* Connection lines radiating out */}
      <path d="M24 18 L24 6" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M24 30 L24 42" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M18 24 L6 24" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M30 24 L42 24" stroke="#d4a574" strokeWidth="1.5" strokeLinecap="round"/>
      {/* Small nodes at ends */}
      <circle cx="24" cy="6" r="2" fill="#d4a574"/>
      <circle cx="24" cy="42" r="2" fill="#d4a574"/>
      <circle cx="6" cy="24" r="2" fill="#d4a574"/>
      <circle cx="42" cy="24" r="2" fill="#d4a574"/>
    </svg>
  )
}

// GluonContent now uses shared MarkdownContent - see import

// TypeBadge now imported from common/ItemCard as TypeIndicator

// Gluon card for displaying linked gluons (notes, highlights, journal entries)
function GluonCard({ gluon, showType = true }) {
  const navigate = useNavigate()

  const handleDocumentClick = (e) => {
    e.stopPropagation()
    if (gluon.source_id) {
      navigate(`/read/${gluon.source_id}`)
    }
  }

  const isJournal = gluon.type === 'journal_entry'
  const isTask = isJournal && gluon.completed !== null && gluon.completed !== undefined
  const isCompleted = gluon.completed === 1

  // Parse body into sub-bullets for journal entries
  const bodyLines = isJournal && gluon.body
    ? gluon.body.split('\n').filter(l => l.trim())
    : []

  return (
    <button
      onClick={() => navigate(`/gluon/${gluon.id}`)}
      className="w-full text-left p-4 bg-surface border border-transparent rounded-lg
                 hover:border-camel/40 hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)]
                 transition-all duration-200 shadow-lg group"
    >
      <div className="flex items-start gap-3">
        {showType && <TypeIndicator type={gluon.type} />}
        <div className="flex-1 min-w-0">
          {/* Content — strikethrough for completed tasks */}
          <p className={`group-hover:text-primary transition-colors ${
            isCompleted ? 'line-through text-muted' : 'text-secondary'
          } ${isJournal ? '' : 'truncate'}`}>
            {isTask && (
              <span className={`inline-block w-3.5 h-3.5 mr-1.5 rounded border align-text-bottom ${
                isCompleted ? 'bg-camel border-camel' : 'border-muted'
              }`} />
            )}
            {gluon.content || <span className="text-muted italic">Empty</span>}
          </p>

          {/* Journal entry body sub-bullets */}
          {bodyLines.length > 0 && (
            <ul className="mt-1 space-y-0.5 pl-1">
              {bodyLines.map((line, i) => (
                <li key={i} className="text-xs text-tertiary flex items-start gap-1.5">
                  <span className="text-muted mt-0.5">–</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          )}

          {gluon.source_title && gluon.source_id && (
            <span
              onClick={handleDocumentClick}
              className="text-xs text-camel/70 hover:text-camel mt-1 flex items-center gap-1 transition-colors cursor-pointer"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {gluon.source_title}
            </span>
          )}
        </div>
      </div>
    </button>
  )
}

// Section component for grouping related items
function Section({ title, count, children, emptyMessage }) {
  if (count === 0) {
    return (
      <div className="mb-8">
        <h2 className="label text-camel mb-3">{title}</h2>
        <p className="text-muted text-sm">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className="mb-8">
      <h2 className="label text-camel mb-3">
        {title} <span className="text-muted">({count})</span>
      </h2>
      <div className="space-y-2">
        {children}
      </div>
    </div>
  )
}

// SourceCard for displaying linked sources (author_of, editor_of)
function SourceCard({ source, role }) {
  const navigate = useNavigate()

  return (
    <button
      onClick={() => navigate(`/read/${source.id}`)}
      className="w-full text-left p-4 bg-surface border border-transparent rounded-lg
                 hover:border-camel/40 hover:-translate-y-0.5 hover:shadow-[0_8px_20px_rgba(212,165,116,0.08)]
                 transition-all duration-200 shadow-lg group"
    >
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-md bg-raised flex items-center justify-center shrink-0">
          <svg className="w-4 h-4 text-camel" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-secondary group-hover:text-primary transition-colors line-clamp-2">
            {source.title}
          </p>
          <div className="flex items-center gap-2 mt-1">
            {source.year && (
              <span className="text-xs text-muted">{source.year}</span>
            )}
            {source.author_display && (
              <span className="text-xs text-tertiary truncate">{source.author_display}</span>
            )}
          </div>
        </div>
      </div>
    </button>
  )
}

export default function Gluon() {
  const { id } = useParams()
  const navigate = useNavigate()
  const navigateToRef = useRefNavigation()
  const { data: gluon, isLoading, error } = useRem(id)
  const createNote = useCreateNote()
  const deleteGluon = useDeleteGluon()
  const updateNote = useUpdateNote()
  const renameGluon = useRenameGluon()
  const mergeGluon = useMergeGluon()

  const [isAddingNote, setIsAddingNote] = useState(false)
  const [newNoteContent, setNewNoteContent] = useState('')
  const [deleteState, setDeleteState] = useState('idle') // 'idle' | 'confirm' | 'warning'
  const [associationCount, setAssociationCount] = useState(0)
  const [mergeConflict, setMergeConflict] = useState(null) // 409 conflict data from rename

  // Inline editing state
  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const textareaRef = useRef(null)
  const isSavingRef = useRef(false) // Prevent double-save

  // Refs to always have latest values in blur handler (avoids stale closure)
  const editContentRef = useRef(editContent)
  const gluonRef = useRef(gluon)
  editContentRef.current = editContent
  gluonRef.current = gluon

  // Sync edit content when gluon loads or changes
  useEffect(() => {
    if (gluon && !isEditing) {
      setEditContent(gluon.content || '')
    }
  }, [gluon, isEditing])

  // Auto-focus and position cursor when entering edit mode
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus()
      textareaRef.current.selectionStart = textareaRef.current.value.length
    }
  }, [isEditing])

  // Save edit - uses refs to always get fresh values
  // Tags and persons route through the rename endpoint; notes use the regular update
  const handleSaveEdit = useCallback(() => {
    // Prevent double-saves
    if (isSavingRef.current) return

    // Get latest values from refs
    const currentGluon = gluonRef.current
    const currentContent = editContentRef.current

    if (!currentGluon) return

    const trimmed = currentContent.trim()
    const originalContent = currentGluon.content || ''

    // Only save if content actually changed
    if (trimmed !== originalContent) {
      isSavingRef.current = true

      if (trimmed === '') {
        // Empty content = prompt delete (use setTimeout to avoid blur issues with confirm)
        setTimeout(() => {
          if (confirm('Delete this gluon? (Content is empty)')) {
            deleteGluon.mutateAsync({ id, force: true }).then(() => {
              isSavingRef.current = false
              navigate('/knowledge')
            }).catch(() => {
              isSavingRef.current = false
            })
          } else {
            setEditContent(originalContent)
            isSavingRef.current = false
          }
        }, 0)
      } else {
        // Determine if this gluon is renameable (tag or person)
        const isPerson = currentGluon.tags?.some(t => t.content === 'person')
        const isRenameable = currentGluon.type === 'tag' || isPerson

        if (isRenameable) {
          // Use rename endpoint — handles conflict detection + 409 merge flow
          renameGluon.mutateAsync({ id, name: trimmed })
            .then(() => {
              isSavingRef.current = false
            })
            .catch((err) => {
              if (err.status === 409 && err.detail?.target) {
                // Name conflict — show merge confirmation modal
                setMergeConflict(err.detail)
              } else {
                console.error('Rename failed:', err)
              }
              isSavingRef.current = false
            })
        } else {
          // Regular note update
          updateNote.mutate(
            { id, content: trimmed, sourceId: currentGluon.source_id },
            {
              onSettled: () => {
                isSavingRef.current = false
              }
            }
          )
        }
      }
    }
    setIsEditing(false)
  }, [id, deleteGluon, updateNote, renameGluon, navigate])

  // Keyboard handling for edit mode
  const handleEditKeyDown = (e) => {
    if (e.key === 'Escape') {
      // Cancel edit
      setEditContent(gluon?.content || '')
      setIsEditing(false)
    } else if (e.key === 'Backspace' && editContent === '') {
      // Delete on backspace when empty
      e.preventDefault()
      if (confirm('Delete this gluon?')) {
        deleteGluon.mutateAsync({ id, force: true }).then(() => navigate('/knowledge'))
      }
    }
    // Note: We don't intercept Enter here - let it create newlines naturally
    // Save happens on blur
  }

  const handleAddNote = async () => {
    if (!newNoteContent.trim()) return

    try {
      await createNote.mutateAsync({
        content: newNoteContent,
        parent_gluon_id: id,
        source_id: gluon.source_id, // Also link to the same document
      })
      setNewNoteContent('')
      setIsAddingNote(false)
    } catch (err) {
      console.error('Failed to add note:', err)
    }
  }

  const handleDelete = async (force = false) => {
    try {
      await deleteGluon.mutateAsync({ id, force })
      navigate('/knowledge')
    } catch (err) {
      // Check if it's a 409 (has associations)
      if (err.status === 409 && err.detail?.association_count) {
        setAssociationCount(err.detail.association_count)
        setDeleteState('warning')
      } else {
        console.error('Delete failed:', err)
        alert('Failed to delete: ' + err.message)
      }
    }
  }

  const initiateDelete = () => {
    setDeleteState('confirm')
  }

  const cancelDelete = () => {
    setDeleteState('idle')
    setAssociationCount(0)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-base flex items-center justify-center">
        <p className="text-secondary">Loading...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-base flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">Error: {error.message}</p>
          <button
            onClick={() => navigate(-1)}
            className="text-camel hover:text-camel/80 transition-colors"
          >
            ← Go back
          </button>
        </div>
      </div>
    )
  }

  if (!gluon) {
    return (
      <div className="min-h-screen bg-base flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted mb-4">Gluon not found</p>
          <button
            onClick={() => navigate(-1)}
            className="text-camel hover:text-camel/80 transition-colors"
          >
            ← Go back
          </button>
        </div>
      </div>
    )
  }

  // Separate backlinks by link_type (how they link TO this gluon)
  // For tags: show everything that's tagged with this tag (link_type === 'tag')
  // For non-tags: show things that reference this gluon (link_type === 'reference')
  const taggedWith = gluon.backlinks?.filter(b => b.link_type === 'tag') || []
  const referencedBy = gluon.backlinks?.filter(b => b.link_type === 'reference') || []

  return (
    <div className="min-h-screen bg-base">
      {/* Header */}
      <header className="border-b border-raised bg-surface">
        <div className="max-w-4xl mx-auto px-8 py-6">
          <div className="flex items-center justify-between mb-4">
            <button
              onClick={() => navigate(-1)}
              className="text-tertiary hover:text-secondary transition-colors text-sm"
            >
              ← Back
            </button>
            <Link
              to="/knowledge"
              className="text-tertiary hover:text-secondary transition-colors text-sm"
            >
              Knowledge
            </Link>
          </div>

          <div className="flex items-start gap-4">
            <div className="relative flex-1">
              <div className="flex items-center gap-3 mb-2">
                <TypeIndicator type={gluon.type} />
                <span className="text-xs text-muted">
                  {new Date(gluon.created_at).toLocaleDateString()}
                </span>

                {/* Delete button - show for tags and notes */}
                {(gluon.type === 'tag' || gluon.type === 'note') && deleteState === 'idle' && (
                  <button
                    onClick={initiateDelete}
                    className="ml-auto text-xs text-muted hover:text-red-400 transition-colors"
                  >
                    Delete
                  </button>
                )}

                {/* Confirm deletion */}
                {deleteState === 'confirm' && (
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-xs text-muted">Delete this {gluon.type}?</span>
                    <button
                      onClick={() => handleDelete(false)}
                      disabled={deleteGluon.isPending}
                      className="text-xs px-2 py-1 bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors disabled:opacity-50"
                    >
                      {deleteGluon.isPending ? '...' : 'Yes'}
                    </button>
                    <button
                      onClick={cancelDelete}
                      className="text-xs text-muted hover:text-secondary transition-colors"
                    >
                      No
                    </button>
                  </div>
                )}

                {/* Warning: tag has associations */}
                {deleteState === 'warning' && (
                  <div className="ml-auto flex items-center gap-2">
                    <span className="text-xs text-yellow-400">
                      ⚠ {associationCount} item{associationCount > 1 ? 's' : ''} tagged with this
                    </span>
                    <button
                      onClick={() => handleDelete(true)}
                      disabled={deleteGluon.isPending}
                      className="text-xs px-2 py-1 bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors disabled:opacity-50"
                    >
                      {deleteGluon.isPending ? '...' : 'Delete anyway'}
                    </button>
                    <button
                      onClick={cancelDelete}
                      className="text-xs text-muted hover:text-secondary transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>

              {/* Document source - show for highlights and notes */}
              {gluon.source_title && gluon.source_id && (
                <Link
                  to={`/read/${gluon.source_id}`}
                  className="text-xs text-camel/70 hover:text-camel mb-3 flex items-center gap-1 transition-colors"
                >
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  {gluon.source_title}
                </Link>
              )}

              {/* Main content - inline editable for notes and tags, read-only for highlights */}
              <div className="relative">
                {gluon.type === 'highlight' ? (
                  // Highlights are read-only (extracted text from documents)
                  <p className="text-xl text-primary leading-relaxed">
                    {gluon.content || <span className="text-muted italic">Empty highlight</span>}
                  </p>
                ) : isEditing ? (
                  // Edit mode: textarea (styled differently for tags vs notes)
                  <div className="relative">
                    <textarea
                      ref={textareaRef}
                      value={editContent}
                      onChange={(e) => setEditContent(e.target.value)}
                      onBlur={(e) => {
                        // Small delay to let any click events fire first
                        // This helps when clicking buttons/links near the textarea
                        setTimeout(handleSaveEdit, 10)
                      }}
                      onKeyDown={handleEditKeyDown}
                      className={`
                        w-full text-primary leading-relaxed bg-raised/20
                        border border-subtle rounded-lg p-3 resize-none outline-none
                        focus:border-camel/50 focus:bg-raised/30 transition-colors
                        ${gluon.type === 'tag' ? 'font-display text-3xl' : 'text-sm'}
                      `}
                      rows={gluon.type === 'tag' ? 1 : Math.max(3, editContent.split('\n').length + 1)}
                      placeholder={gluon.type === 'tag' ? "Tag name..." : "Type your note..."}
                    />
                    <p className="text-xs text-muted mt-2">
                      Click outside to save · Esc to cancel
                    </p>
                  </div>
                ) : (
                  // Display mode: click to edit (notes and tags only)
                  <div
                    onClick={() => setIsEditing(true)}
                    className="cursor-text hover:bg-raised/30 -m-3 p-3 rounded-lg transition-colors group"
                    title="Click to edit"
                  >
                    {gluon.type === 'tag' ? (
                      // Tags display as large title
                      <h1 className="font-display text-4xl text-primary">
                        {gluon.content || <span className="text-muted italic">Click to add content...</span>}
                      </h1>
                    ) : (
                      // Notes display as markdown with parsed refs
                      <div className="text-primary leading-relaxed">
                        {gluon.content ? (
                          <MarkdownContent
                            content={gluon.content}
                            navigateToRef={navigateToRef}
                          />
                        ) : (
                          <span className="text-muted italic text-sm">Click to add content...</span>
                        )}
                      </div>
                    )}
                    <span className="text-xs text-muted opacity-0 group-hover:opacity-100 transition-opacity mt-1 block">
                      Click to edit
                    </span>
                  </div>
                )}

                {/* Hand-drawn decoration */}
                <NodeSVG className="absolute -top-4 -right-16 hidden lg:block" />
              </div>

              {/* Tags on this gluon */}
              {gluon.tags && gluon.tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-4">
                  {gluon.tags.map(tag => (
                    <Link
                      key={tag.id}
                      to={`/gluon/${tag.id}`}
                      className="px-2.5 py-0.5 text-xs bg-terra text-base font-medium rounded-full
                                 hover:bg-terra/90 transition-colors"
                    >
                      {tag.content}
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-4xl mx-auto px-8 py-8">

        {/* Attached To: show parent gluon if this note is attached to a highlight */}
        {gluon.parent_gluon && (
          <Section
            title="Attached To"
            count={1}
            emptyMessage=""
          >
            <GluonCard gluon={gluon.parent_gluon} />
          </Section>
        )}

        {/* For tags: show what's tagged with this */}
        {gluon.type === 'tag' && (
          <Section
            title="Tagged With"
            count={taggedWith.length}
            emptyMessage="Nothing tagged with this yet."
          >
            {taggedWith.map(item => (
              <GluonCard key={item.id} gluon={item} />
            ))}
          </Section>
        )}

        {/* Author of: show sources where this person is an author */}
        {gluon.author_of && gluon.author_of.length > 0 && (
          <Section
            title="Author Of"
            count={gluon.author_of.length}
            emptyMessage=""
          >
            {gluon.author_of.map(source => (
              <SourceCard key={source.id} source={source} role="author" />
            ))}
          </Section>
        )}

        {/* Editor of: show sources where this person is an editor */}
        {gluon.editor_of && gluon.editor_of.length > 0 && (
          <Section
            title="Editor Of"
            count={gluon.editor_of.length}
            emptyMessage=""
          >
            {gluon.editor_of.map(source => (
              <SourceCard key={source.id} source={source} role="editor" />
            ))}
          </Section>
        )}

        {/* Tagged sources: show source documents that carry this tag */}
        {gluon.tag_of && gluon.tag_of.length > 0 && (
          <Section
            title="Source Documents"
            count={gluon.tag_of.length}
            emptyMessage=""
          >
            {gluon.tag_of.map(source => (
              <SourceCard key={source.id} source={source} role="tag" />
            ))}
          </Section>
        )}

        {/* Backlinks / References */}
        {gluon.type !== 'tag' && (
          <Section
            title="Referenced By"
            count={gluon.backlinks?.length || 0}
            emptyMessage="No other gluons reference this yet."
          >
            {gluon.backlinks?.map(item => (
              <GluonCard key={item.id} gluon={item} />
            ))}
          </Section>
        )}

        {/* Outgoing references */}
        {gluon.outgoing_refs && gluon.outgoing_refs.length > 0 && (
          <Section
            title="References"
            count={gluon.outgoing_refs.length}
            emptyMessage=""
          >
            {gluon.outgoing_refs.map(item => (
              <GluonCard key={item.id} gluon={item} />
            ))}
          </Section>
        )}

        {/* Child notes (for highlights) */}
        {gluon.notes && gluon.notes.length > 0 && (
          <Section
            title="Notes"
            count={gluon.notes.length}
            emptyMessage=""
          >
            {gluon.notes.map(note => (
              <GluonCard key={note.id} gluon={note} showType={false} />
            ))}
          </Section>
        )}

        {/* Add note section */}
        <div className="mt-8 pt-8 border-t border-raised">
          {isAddingNote ? (
            <div className="space-y-3">
              <textarea
                value={newNoteContent}
                onChange={(e) => setNewNoteContent(e.target.value)}
                placeholder="Write a note about this gluon..."
                className="w-full px-4 py-3 bg-base border border-subtle rounded-lg
                           text-secondary placeholder:text-muted resize-none
                           focus:outline-none focus:border-camel transition-colors"
                rows={3}
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  onClick={handleAddNote}
                  disabled={!newNoteContent.trim() || createNote.isPending}
                  className="px-4 py-2 bg-camel text-base rounded-lg font-medium
                             hover:bg-camel/90 disabled:opacity-50 disabled:cursor-not-allowed
                             transition-colors"
                >
                  {createNote.isPending ? 'Saving...' : 'Save Note'}
                </button>
                <button
                  onClick={() => { setIsAddingNote(false); setNewNoteContent('') }}
                  className="px-4 py-2 text-muted hover:text-secondary transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setIsAddingNote(true)}
              className="text-camel hover:text-camel/80 transition-colors text-sm"
            >
              + Add a note about this gluon
            </button>
          )}
        </div>

        {/* Document link if applicable */}
        {gluon.source_id && (
          <div className="mt-8 pt-8 border-t border-raised">
            <p className="text-xs text-muted mb-2">Source Document</p>
            <Link
              to={`/read/${gluon.source_id}`}
              className="text-camel hover:text-camel/80 transition-colors"
            >
              Open in Reader →
            </Link>
          </div>
        )}
      </main>

      {/* Merge confirmation modal — shown when rename finds a name conflict */}
      {mergeConflict && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="bg-surface border border-raised rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
            <h3 className="text-lg font-medium text-primary mb-4">Merge Gluons?</h3>
            <p className="text-secondary text-sm mb-4">
              A {gluon.type === 'tag' ? 'tag' : 'person'} named
              <span className="text-primary font-medium"> "{mergeConflict.target.content}"</span> already exists.
              Merge <span className="text-primary font-medium">"{gluon.content}"</span> into it?
            </p>

            <div className="bg-base rounded-lg p-3 mb-4 text-sm text-tertiary space-y-1">
              {mergeConflict.merge_preview.source_links > 0 && (
                <p>{mergeConflict.merge_preview.source_links} source link{mergeConflict.merge_preview.source_links !== 1 ? 's' : ''} will be transferred</p>
              )}
              {mergeConflict.merge_preview.note_links > 0 && (
                <p>{mergeConflict.merge_preview.note_links} note link{mergeConflict.merge_preview.note_links !== 1 ? 's' : ''} will be transferred</p>
              )}
              {mergeConflict.merge_preview.child_notes > 0 && (
                <p>{mergeConflict.merge_preview.child_notes} child note{mergeConflict.merge_preview.child_notes !== 1 ? 's' : ''} will be re-parented</p>
              )}
              {mergeConflict.merge_preview.duplicate_links > 0 && (
                <p>{mergeConflict.merge_preview.duplicate_links} duplicate link{mergeConflict.merge_preview.duplicate_links !== 1 ? 's' : ''} will be removed</p>
              )}
              {mergeConflict.merge_preview.source_links === 0 &&
               mergeConflict.merge_preview.note_links === 0 &&
               mergeConflict.merge_preview.child_notes === 0 && (
                <p className="text-muted">No links to transfer — the gluon will simply be deleted.</p>
              )}
            </div>

            <div className="flex gap-2 justify-end">
              <button
                onClick={() => {
                  setMergeConflict(null)
                  setEditContent(gluon.content || '')
                }}
                className="px-4 py-2 text-muted hover:text-secondary transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const targetId = mergeConflict.target.id
                  mergeGluon.mutateAsync({ id, targetId })
                    .then(() => {
                      setMergeConflict(null)
                      navigate(`/gluon/${targetId}`)
                    })
                    .catch((err) => {
                      console.error('Merge failed:', err)
                    })
                }}
                disabled={mergeGluon.isPending}
                className="px-4 py-2 bg-camel text-base rounded-lg font-medium
                           hover:bg-camel/90 disabled:opacity-50 transition-colors"
              >
                {mergeGluon.isPending ? 'Merging...' : 'Merge'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
