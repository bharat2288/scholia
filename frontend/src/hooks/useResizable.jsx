/**
 * useResizable Hook
 * =================
 * Custom hook for resizable pane widths with localStorage persistence.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

const STORAGE_KEY = 'scholia-reader-widths'

const DEFAULT_WIDTHS = {
  toc: 240,
  sidebar: 320,
}

const CONSTRAINTS = {
  toc: { min: 180, max: 350 },
  sidebar: { min: 280, max: 900 },  // Increased to match expanded mode
}

/**
 * Hook for managing resizable pane widths
 * @returns {{ tocWidth, sidebarWidth, handleTocResize, handleSidebarResize, isResizing }}
 */
export function useResizable() {
  const [widths, setWidths] = useState(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const parsed = JSON.parse(stored)
        return { ...DEFAULT_WIDTHS, ...parsed }
      }
    } catch (e) {
      console.warn('Failed to load saved widths:', e)
    }
    return DEFAULT_WIDTHS
  })

  const [isResizing, setIsResizing] = useState(false)
  const resizeRef = useRef({ pane: null, startX: 0, startWidth: 0 })

  // Save to localStorage when widths change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(widths))
    } catch (e) {
      console.warn('Failed to save widths:', e)
    }
  }, [widths])

  // Shared resize logic for both mouse and touch
  const applyResize = useCallback((clientX) => {
    if (!resizeRef.current.pane) return

    const { pane, startX, startWidth } = resizeRef.current
    const delta = clientX - startX
    const constraints = CONSTRAINTS[pane]

    let newWidth
    if (pane === 'toc') {
      newWidth = Math.min(Math.max(startWidth + delta, constraints.min), constraints.max)
    } else {
      newWidth = Math.min(Math.max(startWidth - delta, constraints.min), constraints.max)
    }

    setWidths(prev => ({ ...prev, [pane]: newWidth }))
  }, [])

  const handleMouseMove = useCallback((e) => applyResize(e.clientX), [applyResize])
  const handleTouchMove = useCallback((e) => {
    if (e.touches.length === 1) applyResize(e.touches[0].clientX)
  }, [applyResize])

  const stopResize = useCallback(() => {
    resizeRef.current.pane = null
    setIsResizing(false)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  // Set up global listeners when resizing starts (mouse + touch)
  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', stopResize)
      document.addEventListener('touchmove', handleTouchMove, { passive: true })
      document.addEventListener('touchend', stopResize)
      document.addEventListener('touchcancel', stopResize)
      return () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', stopResize)
        document.removeEventListener('touchmove', handleTouchMove)
        document.removeEventListener('touchend', stopResize)
        document.removeEventListener('touchcancel', stopResize)
      }
    }
  }, [isResizing, handleMouseMove, handleTouchMove, stopResize])

  // Start resize — works with both mouse and touch events
  const startResize = useCallback((pane, clientX, currentWidth) => {
    resizeRef.current = { pane, startX: clientX, startWidth: currentWidth }
    setIsResizing(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [])

  const handleTocResize = useCallback((e) => {
    e.preventDefault()
    const x = e.touches ? e.touches[0].clientX : e.clientX
    startResize('toc', x, widths.toc)
  }, [widths.toc, startResize])

  const handleSidebarResize = useCallback((e) => {
    e.preventDefault()
    const x = e.touches ? e.touches[0].clientX : e.clientX
    startResize('sidebar', x, widths.sidebar)
  }, [widths.sidebar, startResize])

  return {
    tocWidth: widths.toc,
    sidebarWidth: widths.sidebar,
    handleTocResize,
    handleSidebarResize,
    isResizing,
  }
}

/**
 * ResizeHandle Component
 * A draggable divider between panes
 */
export function ResizeHandle({ onMouseDown, position = 'right' }) {
  return (
    <div
      onMouseDown={onMouseDown}
      onTouchStart={onMouseDown}
      className={`
        group relative w-1 flex-shrink-0 cursor-col-resize
        bg-subtle/50 hover:bg-camel/30 active:bg-camel/50
        transition-colors duration-150
        touch-none
      `}
    >
      {/* Hit area — wider on touch devices for easier grabbing */}
      <div className={`
        absolute inset-y-0 -inset-x-2 sm:-inset-x-0
      `} />
      {/* Visual indicator */}
      <div className={`
        absolute top-1/2 -translate-y-1/2
        ${position === 'right' ? '-right-0.5' : '-left-0.5'}
        w-1 h-12 rounded-full
        bg-transparent group-hover:bg-camel/50 group-active:bg-camel
        transition-all duration-150
      `} />
    </div>
  )
}
