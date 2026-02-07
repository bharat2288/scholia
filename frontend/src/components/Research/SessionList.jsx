import { useCreateSession, useDeleteSession } from '../../hooks/useRLM'

/**
 * SessionList
 * ===========
 * Left panel showing all research sessions.
 * Supports create, select, and delete.
 */
export default function SessionList({
  sessions = [],
  isLoading,
  activeSessionId,
  onSelectSession
}) {
  const createSession = useCreateSession()
  const deleteSession = useDeleteSession()

  const handleCreate = async () => {
    try {
      const session = await createSession.mutateAsync({
        title: `Untitled Session`
      })
      onSelectSession(session.id)
    } catch (err) {
      console.error('Failed to create session:', err)
    }
  }

  const handleDelete = async (e, sessionId) => {
    e.stopPropagation()
    if (!confirm('Delete this session? This cannot be undone.')) return

    try {
      await deleteSession.mutateAsync(sessionId)
      if (activeSessionId === sessionId) {
        onSelectSession(null)
      }
    } catch (err) {
      console.error('Failed to delete session:', err)
    }
  }

  return (
    <div className="flex-shrink-0 flex flex-col bg-surface/30 max-h-[50%]">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b border-subtle/30">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wider text-camel">
            Sessions
          </span>
          <button
            onClick={handleCreate}
            disabled={createSession.isPending}
            className="p-1.5 rounded-md text-tertiary hover:text-primary hover:bg-raised/50 disabled:opacity-50 transition-colors"
            title="New Session"
          >
            {createSession.isPending ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-tertiary text-sm">Loading...</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center text-tertiary text-sm">
            No sessions yet. Create one to get started.
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {sessions.map((session) => (
              <SessionCard
                key={session.id}
                session={session}
                isActive={session.id === activeSessionId}
                onClick={() => onSelectSession(session.id)}
                onDelete={(e) => handleDelete(e, session.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * SessionCard
 * ===========
 * Clickable card for a single session.
 */
function SessionCard({ session, isActive, onClick, onDelete }) {
  const sourceCount = session.source_count || 0
  const messageCount = session.message_count || 0

  // Format relative time
  const formatTime = (dateStr) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffHours < 24) return `${diffHours}h ago`
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div
      onClick={onClick}
      className={`
        group relative p-3 rounded-lg cursor-pointer transition-all duration-150
        ${isActive
          ? 'bg-raised border-l-2 border-l-camel'
          : 'hover:bg-raised/50 border-l-2 border-l-transparent hover:border-l-camel/40'
        }
      `}
    >
      {/* Title */}
      <h4 className={`text-sm font-medium truncate pr-6 ${isActive ? 'text-primary' : 'text-secondary'}`}>
        {session.title}
      </h4>

      {/* Meta */}
      <div className="mt-1 flex items-center gap-3 text-xs text-tertiary">
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {sourceCount}
        </span>
        <span className="flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
          </svg>
          {messageCount}
        </span>
        <span className="text-muted">{formatTime(session.updated_at)}</span>
      </div>

      {/* Delete button (shown on hover) */}
      <button
        onClick={onDelete}
        className="absolute top-2 right-2 p-1 rounded text-tertiary opacity-0 group-hover:opacity-100 hover:text-terra hover:bg-terra/10 transition-all"
        title="Delete session"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}
