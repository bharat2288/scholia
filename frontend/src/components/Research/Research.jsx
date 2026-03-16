import { useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import useResearchStore from '../../stores/useResearchStore'
import { useSessions, useSession } from '../../hooks/useRLM'
import useDeviceLayout from '../../hooks/useDeviceLayout'
import Drawer from '../common/Drawer'
import SessionList from './SessionList'
import SessionWorkspace from './SessionWorkspace'
import SourcesPanelVertical from './SourcesPanelVertical'

/**
 * Hand-drawn quill/scroll element for Research title
 */
function ScrollSVG({ className = "" }) {
  return (
    <svg
      className={className}
      width="40"
      height="40"
      viewBox="0 0 40 40"
      fill="none"
      style={{ opacity: 0.45 }}
    >
      {/* Scroll body */}
      <path
        d="M8 8 Q6 8, 6 12 L6 32 Q6 36, 10 36 L30 36 Q34 36, 34 32 L34 12 Q34 8, 30 8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      {/* Scroll top curl */}
      <path
        d="M8 8 Q8 4, 12 4 L28 4 Q32 4, 32 8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      {/* Text lines */}
      <path d="M12 14 L28 14" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      <path d="M12 20 L24 20" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      <path d="M12 26 L26 26" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
    </svg>
  )
}

/**
 * Research View
 * =============
 * Multi-source research sessions with RLM chat.
 * Responsive: mobile single-pane, tablet toggleable sidebar, desktop two-panel.
 */
export default function Research() {
  const layout = useDeviceLayout()
  const { activeSessionId, setActiveSession, widths, setWidth } = useResearchStore()
  const { data: sessions = [], isLoading: sessionsLoading } = useSessions()
  const { data: activeSession } = useSession(activeSessionId)

  // Mobile: drawer for session list
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false)

  // Tablet: toggleable session list sidebar
  const [tabletSidebarVisible, setTabletSidebarVisible] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('scholia-research-sessions') || 'false')
    } catch { return false }
  })

  const toggleTabletSidebar = useCallback(() => {
    setTabletSidebarVisible(prev => {
      const next = !prev
      localStorage.setItem('scholia-research-sessions', JSON.stringify(next))
      return next
    })
  }, [])

  // Desktop: resize handling for session list panel
  const [isResizing, setIsResizing] = useState(false)

  const handleResizeStart = useCallback((e) => {
    e.preventDefault()
    setIsResizing(true)
    const startX = e.clientX
    const startWidth = widths.sessions

    const handleMove = (moveEvent) => {
      const delta = moveEvent.clientX - startX
      const newWidth = Math.min(Math.max(startWidth + delta, 200), 400)
      setWidth('sessions', newWidth)
    }

    const handleUp = () => {
      setIsResizing(false)
      document.removeEventListener('mousemove', handleMove)
      document.removeEventListener('mouseup', handleUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    document.addEventListener('mousemove', handleMove)
    document.addEventListener('mouseup', handleUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [widths.sessions, setWidth])

  // When selecting a session on mobile, close the drawer
  const handleSelectSession = useCallback((sessionId) => {
    setActiveSession(sessionId)
    if (layout === 'mobile') {
      setMobileDrawerOpen(false)
    }
  }, [setActiveSession, layout])

  // Shared session list + sources panel content
  const sessionListContent = (
    <>
      <SessionList
        sessions={sessions}
        isLoading={sessionsLoading}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
      />
      {activeSessionId && activeSession && (
        <SourcesPanelVertical
          sessionId={activeSessionId}
          sources={activeSession.sources || []}
        />
      )}
    </>
  )

  return (
    <div className="h-screen bg-base flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-subtle/50 bg-surface/50 backdrop-blur-sm">
        <div className="px-4 py-3 sm:px-6 sm:py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Mobile: hamburger to open session list drawer */}
            {layout === 'mobile' && (
              <button
                onClick={() => setMobileDrawerOpen(true)}
                className="text-secondary hover:text-primary transition-colors p-1 -ml-1"
                title="Sessions"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
            )}
            <Link
              to="/"
              className="text-secondary hover:text-primary transition-colors"
              title="Back to Library"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </Link>
            <ScrollSVG className="mr-1 hidden sm:block" />
            <h1 className="font-display text-xl sm:text-2xl text-primary tracking-tight">
              Research Sessions
            </h1>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-sm text-tertiary hidden sm:inline">
              {sessions.length} session{sessions.length !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
      </header>

      {/* Mobile: session list drawer (overlay, doesn't affect layout) */}
      {layout === 'mobile' && (
        <Drawer
          isOpen={mobileDrawerOpen}
          onClose={() => setMobileDrawerOpen(false)}
          position="left"
        >
          {sessionListContent}
        </Drawer>
      )}

      {/* Main content — sidebar varies by layout, workspace never unmounts */}
      <div className="flex-1 flex overflow-hidden">
        {/* Desktop: sidebar + resize handle */}
        {layout === 'desktop' && (
          <>
            <div
              className="flex-shrink-0 border-r border-subtle/50 overflow-hidden flex flex-col"
              style={{ width: widths.sessions }}
            >
              {sessionListContent}
            </div>
            <div
              onMouseDown={handleResizeStart}
              className={`
                group relative w-1 flex-shrink-0 cursor-col-resize
                bg-subtle/50 hover:bg-camel/30 active:bg-camel/50
                transition-colors duration-150
                ${isResizing ? 'bg-camel/50' : ''}
              `}
            >
              <div className="absolute top-1/2 -translate-y-1/2 -right-0.5 w-1 h-12 rounded-full bg-transparent group-hover:bg-camel/50 group-active:bg-camel transition-all duration-150" />
            </div>
          </>
        )}

        {/* Tablet: toggleable sidebar */}
        {layout === 'tablet' && tabletSidebarVisible && (
          <div className="flex-shrink-0 border-r border-subtle/50 overflow-hidden flex flex-col"
            style={{ width: '35%' }}
          >
            {sessionListContent}
          </div>
        )}

        {/* Workspace — rendered once, stable across layout changes */}
        <div className={`flex-1 overflow-hidden ${layout === 'mobile' ? 'pb-16' : ''}`}>
          {activeSessionId ? (
            <SessionWorkspace
              session={activeSession}
              sessionId={activeSessionId}
            />
          ) : (
            layout === 'mobile'
              ? <MobileEmptyState onOpenSessions={() => setMobileDrawerOpen(true)} />
              : <EmptyState />
          )}
        </div>

        {/* Tablet: floating toggle when sidebar hidden */}
        {layout === 'tablet' && !tabletSidebarVisible && (
          <button
            onClick={toggleTabletSidebar}
            className="fixed bottom-20 right-4 z-30 w-11 h-11 rounded-full
                       bg-surface border border-subtle shadow-lg
                       flex items-center justify-center
                       text-tertiary hover:text-camel hover:border-camel/40 transition-all"
            title="Show sessions"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
            </svg>
          </button>
        )}

        {/* Tablet: chevron toggle when sidebar visible */}
        {layout === 'tablet' && tabletSidebarVisible && (
          <button
            onClick={toggleTabletSidebar}
            className="absolute left-[35%] top-1/2 -translate-y-1/2 z-30
                       w-5 h-10 -ml-2.5 rounded-r-md
                       bg-surface border border-l-0 border-subtle
                       flex items-center justify-center
                       text-muted hover:text-camel transition-colors"
            title="Hide sessions"
          >
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Empty state when no session is selected
 */
function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center max-w-md px-6">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-surface flex items-center justify-center">
          <svg className="w-8 h-8 text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
        </div>
        <h3 className="text-lg font-medium text-secondary mb-2">No Session Selected</h3>
        <p className="text-sm text-tertiary">
          Select a session from the list or create a new one to start researching with AI-powered tools.
        </p>
      </div>
    </div>
  )
}

/**
 * Mobile empty state — prompts to open the session drawer
 */
function MobileEmptyState({ onOpenSessions }) {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center max-w-sm px-6">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-surface flex items-center justify-center">
          <svg className="w-8 h-8 text-tertiary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
        </div>
        <h3 className="text-lg font-medium text-secondary mb-2">No Session Selected</h3>
        <p className="text-sm text-tertiary mb-4">
          Open sessions to select or create a research session.
        </p>
        <button
          onClick={onOpenSessions}
          className="px-4 py-2 bg-camel/20 text-camel rounded-lg text-sm font-medium
                     hover:bg-camel/30 transition-colors"
        >
          Open Sessions
        </button>
      </div>
    </div>
  )
}
