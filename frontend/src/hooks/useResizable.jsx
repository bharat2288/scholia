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

  // Handle mouse move during resize
  const handleMouseMove = useCallback((e) => {
    if (!resizeRef.current.pane) return

    const { pane, startX, startWidth } = resizeRef.current
    const delta = e.clientX - startX
    const constraints = CONSTRAINTS[pane]

    let newWidth
    if (pane === 'toc') {
      // ToC: dragging right increases width
      newWidth = Math.min(Math.max(startWidth + delta, constraints.min), constraints.max)
    } else {
      // Sidebar: dragging left increases width
      newWidth = Math.min(Math.max(startWidth - delta, constraints.min), constraints.max)
    }

    setWidths(prev => ({ ...prev, [pane]: newWidth }))
  }, [])

  // Handle mouse up to stop resizing
  const handleMouseUp = useCallback(() => {
    resizeRef.current.pane = null
    setIsResizing(false)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  // Set up global listeners when resizing starts
  useEffect(() => {
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
      return () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [isResizing, handleMouseMove, handleMouseUp])

  // Start resize for ToC
  const handleTocResize = useCallback((e) => {
    e.preventDefault()
    resizeRef.current = { pane: 'toc', startX: e.clientX, startWidth: widths.toc }
    setIsResizing(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [widths.toc])

  // Start resize for Sidebar
  const handleSidebarResize = useCallback((e) => {
    e.preventDefault()
    resizeRef.current = { pane: 'sidebar', startX: e.clientX, startWidth: widths.sidebar }
    setIsResizing(true)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [widths.sidebar])

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
      className={`
        group relative w-1 flex-shrink-0 cursor-col-resize
        bg-subtle/50 hover:bg-camel/30 active:bg-camel/50
        transition-colors duration-150
      `}
    >
      {/* Visual indicator on hover */}
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
