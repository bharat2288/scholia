import { useEffect, useRef } from 'react'

/**
 * Reusable Drawer / Bottom Sheet
 *
 * position='left'   — slides in from the left (ToC drawer)
 * position='bottom' — slides up from the bottom (sidebar sheet)
 *
 * Features:
 * - Fixed overlay with backdrop
 * - CSS transform transition (300ms)
 * - Click-outside to close
 * - Body scroll lock while open
 * - Bottom sheet: max 85vh with drag handle indicator
 */
export default function Drawer({ isOpen, onClose, position = 'left', children }) {
  const drawerRef = useRef(null)

  // Lock body scroll when open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [isOpen])

  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return
    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [isOpen, onClose])

  const isLeft = position === 'left'

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className={`fixed inset-0 z-40 bg-black/60 transition-opacity duration-300 ${
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />

      {/* Drawer panel */}
      <div
        ref={drawerRef}
        className={`fixed z-50 bg-surface transition-transform duration-300 ease-out ${
          isLeft
            ? 'top-0 left-0 h-full w-[85vw] max-w-sm border-r border-subtle shadow-2xl'
            : 'bottom-0 left-0 right-0 max-h-[85vh] rounded-t-2xl border-t border-subtle shadow-2xl'
        } ${
          isOpen
            ? 'translate-x-0 translate-y-0'
            : isLeft
              ? '-translate-x-full'
              : 'translate-y-full'
        }`}
      >
        {/* Bottom sheet drag handle */}
        {!isLeft && (
          <div className="flex justify-center py-3">
            <div className="w-10 h-1 rounded-full bg-muted" />
          </div>
        )}

        {/* Content */}
        <div className={`overflow-auto ${isLeft ? 'h-full' : 'max-h-[calc(85vh-2rem)]'}`}>
          {children}
        </div>
      </div>
    </>
  )
}
