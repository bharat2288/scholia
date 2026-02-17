import { useState, useEffect } from 'react'

const BREAKPOINTS = {
  mobile: 640,   // <640px (folded phone, small screens)
  tablet: 1024,  // 640-1024px (unfolded foldable, tablets)
  // desktop: >1024px
}

function getLayout(width) {
  if (width < BREAKPOINTS.mobile) return 'mobile'
  if (width < BREAKPOINTS.tablet) return 'tablet'
  return 'desktop'
}

/**
 * Detect device layout based on viewport width.
 * Returns 'mobile' | 'tablet' | 'desktop'.
 *
 * Handles foldable devices (Honor Magic V5) by reactively
 * responding to resize events with 150ms debounce.
 */
export default function useDeviceLayout() {
  const [layout, setLayout] = useState(() => getLayout(window.innerWidth))

  useEffect(() => {
    let timeoutId = null

    const handleResize = () => {
      if (timeoutId) clearTimeout(timeoutId)
      timeoutId = setTimeout(() => {
        setLayout(getLayout(window.innerWidth))
      }, 150)
    }

    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [])

  return layout
}
