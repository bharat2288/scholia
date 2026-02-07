import { useState } from 'react'
import { useUpdateSession } from '../../hooks/useRLM'
import RLMChat from './RLMChat'

/**
 * SessionWorkspace
 * ================
 * Main workspace for an active research session.
 * Sources are now in the left panel; this just shows header + chat.
 */
export default function SessionWorkspace({ session, sessionId }) {
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const updateSession = useUpdateSession()

  if (!session) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-tertiary">Loading session...</div>
      </div>
    )
  }

  const handleStartEdit = () => {
    setEditTitle(session.title)
    setIsEditing(true)
  }

  const handleSaveTitle = async () => {
    if (editTitle.trim() && editTitle !== session.title) {
      try {
        await updateSession.mutateAsync({ id: sessionId, title: editTitle.trim() })
      } catch (err) {
        console.error('Failed to update title:', err)
      }
    }
    setIsEditing(false)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleSaveTitle()
    } else if (e.key === 'Escape') {
      setIsEditing(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Session header */}
      <div className="flex-shrink-0 px-6 py-4 border-b border-subtle/30 bg-surface/20">
        {isEditing ? (
          <input
            type="text"
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={handleSaveTitle}
            onKeyDown={handleKeyDown}
            autoFocus
            className="text-lg font-medium text-primary bg-transparent border-b border-camel/50 outline-none w-full"
          />
        ) : (
          <h2
            onClick={handleStartEdit}
            className="text-lg font-medium text-primary cursor-pointer hover:text-camel transition-colors"
            title="Click to rename"
          >
            {session.title}
          </h2>
        )}
        {session.description && (
          <p className="mt-1 text-sm text-tertiary">{session.description}</p>
        )}
      </div>

      {/* RLM Chat */}
      <div className="flex-1 overflow-hidden">
        <RLMChat sessionId={sessionId} />
      </div>
    </div>
  )
}
