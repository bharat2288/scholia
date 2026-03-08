/**
 * YouTube Player component and seek utilities.
 * Embeds YouTube video with IFrame API for timestamp seeking,
 * sticky positioning, bilateral resize handles.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import useReaderStore from '../../stores/useReaderStore'

// Global reference to YouTube player for timestamp seeking
let youtubePlayerRef = null

/**
 * YouTube Player component
 * Embeds YouTube video with IFrame API for timestamp seeking
 */
export default function YouTubePlayer({ videoId, title }) {
  const containerRef = useRef(null)
  const playerRef = useRef(null)
  const { autoScrollEnabled, setAutoScrollEnabled } = useReaderStore()
  const wrapperRef = useRef(null)
  const pollIntervalRef = useRef(null)
  const [isReady, setIsReady] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const [isSticky, setIsSticky] = useState(false)
  // Sticky player width as percentage of container (user-resizable via drag handle)
  const [stickyWidthPct, setStickyWidthPct] = useState(
    () => parseInt(localStorage.getItem('scholia-player-width') || '55')
  )
  const [isResizing, setIsResizing] = useState(false)
  const widthRef = useRef(stickyWidthPct)
  const { setPlaybackTime, setVideoPlaying } = useReaderStore()

  useEffect(() => {
    if (!videoId) return

    if (!window.YT) {
      const tag = document.createElement('script')
      tag.src = 'https://www.youtube.com/iframe_api'
      const firstScriptTag = document.getElementsByTagName('script')[0]
      firstScriptTag.parentNode.insertBefore(tag, firstScriptTag)
    }

    const initPlayer = () => {
      if (!containerRef.current) return
      playerRef.current = new window.YT.Player(containerRef.current, {
        videoId: videoId,
        width: '100%',
        height: '100%',
        playerVars: { autoplay: 0, modestbranding: 1, rel: 0, origin: window.location.origin },
        events: {
          onReady: () => {
            setIsReady(true)
            youtubePlayerRef = playerRef.current
          },
          onStateChange: (event) => {
            // YT.PlayerState: 1=PLAYING, 2=PAUSED, 0=ENDED, 3=BUFFERING
            const playing = event.data === 1
            setVideoPlaying(playing)

            if (playing) {
              // Start 100ms polling for current time
              if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
              pollIntervalRef.current = setInterval(() => {
                if (playerRef.current?.getCurrentTime) {
                  setPlaybackTime(playerRef.current.getCurrentTime())
                }
              }, 100)
            } else {
              // Stop polling when not playing
              if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current)
                pollIntervalRef.current = null
              }
            }
          },
        },
      })
    }

    if (window.YT && window.YT.Player) initPlayer()
    else window.onYouTubeIframeAPIReady = initPlayer

    return () => {
      youtubePlayerRef = null
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
      if (playerRef.current?.destroy) playerRef.current.destroy()
    }
  }, [videoId, setPlaybackTime, setVideoPlaying])

  const seekTo = useCallback((seconds) => {
    if (playerRef.current?.seekTo) {
      playerRef.current.seekTo(seconds, true)
      playerRef.current.playVideo()
      if (isMinimized) setIsMinimized(false)
    }
  }, [isMinimized])

  useEffect(() => {
    if (isReady && playerRef.current) {
      youtubePlayerRef = { seekTo, player: playerRef.current }
      window.__scholiaYouTubePlayer = youtubePlayerRef
    }
    return () => { window.__scholiaYouTubePlayer = null }
  }, [isReady, seekTo])

  // Detect sticky state via scroll listener on <main>
  // Used only for visual changes (shadow, smaller width) — CSS sticky handles positioning
  useEffect(() => {
    if (!wrapperRef.current || isMinimized) return

    const scrollContainer = wrapperRef.current.closest('main')
    if (!scrollContainer) return

    const handleScroll = () => {
      const wrapper = wrapperRef.current
      if (!wrapper) return
      const rect = wrapper.getBoundingClientRect()
      // Sticky kicks in when wrapper's top reaches the sticky offset (52px)
      setIsSticky(rect.top <= 56)
    }

    scrollContainer.addEventListener('scroll', handleScroll)
    return () => scrollContainer.removeEventListener('scroll', handleScroll)
  }, [isMinimized])

  // Resize drag — adjusts sticky width percentage
  // Right-aligned player: width = distance from cursor to right edge of wrapper
  // Dragging left = wider, dragging right = narrower
  useEffect(() => {
    if (!isResizing) return

    // Lock cursor + disable text selection for the whole document during drag
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const handleMouseMove = (e) => {
      const wrapper = wrapperRef.current
      if (!wrapper) return
      const rect = wrapper.getBoundingClientRect()
      // Centered player: width = 2 × distance from cursor to center
      const centerX = rect.left + rect.width / 2
      const pct = Math.max(30, Math.min(98, (Math.abs(e.clientX - centerX) * 2 / rect.width) * 100))
      const rounded = Math.round(pct)
      widthRef.current = rounded
      setStickyWidthPct(rounded)
    }

    const handleMouseUp = () => {
      setIsResizing(false)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      localStorage.setItem('scholia-player-width', String(widthRef.current))
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizing])

  if (!videoId) return null

  return (
    <div
      ref={wrapperRef}
      className="mb-6 sticky top-[52px] z-20 relative"
    >
      <div
        id="youtube-player-container"
        className={`
          rounded-lg overflow-hidden border border-subtle bg-surface
          ${isResizing ? '' : 'transition-all duration-300 ease-out'}
          ${isMinimized ? 'h-12' : ''}
          ${isSticky && !isMinimized ? 'mx-auto shadow-xl border-camel/20' : ''}
        `}
        style={isSticky && !isMinimized ? { width: `${stickyWidthPct}%` } : {}}
      >
        {/* Header bar */}
        <div className="flex items-center justify-between px-3 py-2 bg-raised/50 border-b border-subtle">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[#ff0000] text-sm">▶</span>
            <span className="text-xs text-secondary truncate">{title || 'Video'}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setAutoScrollEnabled(!autoScrollEnabled)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${autoScrollEnabled ? 'bg-camel/20 text-camel' : 'bg-elevated text-muted hover:text-secondary'}`}
              title={autoScrollEnabled ? 'Auto-scroll on — click to disable' : 'Auto-scroll off — click to enable'}
            >
              {autoScrollEnabled ? 'Sync' : 'Sync'}
            </button>
            <button
              onClick={() => setIsMinimized(!isMinimized)}
              className="text-muted hover:text-secondary transition-colors p-1"
              title={isMinimized ? 'Expand video' : 'Minimize video'}
            >
              {isMinimized ? (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              )}
            </button>
            <a
              href={`https://youtube.com/watch?v=${videoId}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted hover:text-secondary transition-colors p-1"
              title="Open on YouTube"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        </div>

        {/* Video container — 16:9 aspect ratio */}
        {!isMinimized && (
          <div className="relative w-full" style={{ paddingBottom: '56.25%' }}>
            <div ref={containerRef} className="absolute inset-0" />
            {/* Transparent shield: blocks iframe from stealing mouse events during resize drag */}
            {isResizing && <div className="absolute inset-0 z-10" />}
            {!isReady && (
              <div className="absolute inset-0 flex items-center justify-center bg-base">
                <span className="text-muted text-sm">Loading video...</span>
              </div>
            )}
          </div>
        )}

      </div>

      {/* Bilateral resize handles — centered player expands/contracts symmetrically */}
      {isSticky && !isMinimized && (
        <>
          <div
            onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }}
            className="absolute top-0 bottom-0 w-3 -ml-1.5 cursor-col-resize z-30 group flex items-center"
            style={{ left: `${(100 - stickyWidthPct) / 2}%` }}
            title="Drag to resize"
          >
            <div className="w-1 h-10 rounded-full bg-muted/20 group-hover:bg-camel/50 transition-colors" />
          </div>
          <div
            onMouseDown={(e) => { e.preventDefault(); setIsResizing(true) }}
            className="absolute top-0 bottom-0 w-3 -ml-1.5 cursor-col-resize z-30 group flex items-center"
            style={{ left: `${(100 + stickyWidthPct) / 2}%` }}
            title="Drag to resize"
          >
            <div className="w-1 h-10 rounded-full bg-muted/20 group-hover:bg-camel/50 transition-colors" />
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Seek YouTube video to specified time.
 * Called by timestamp badges in both transcript and analysis content.
 */
export function seekYouTubeVideo(seconds) {
  if (youtubePlayerRef?.seekTo) {
    youtubePlayerRef.seekTo(seconds)
  } else if (youtubePlayerRef?.player?.seekTo) {
    youtubePlayerRef.player.seekTo(seconds, true)
    youtubePlayerRef.player.playVideo()
  }

  // Update playback time immediately so the active cue highlights
  const store = useReaderStore.getState()
  store.setPlaybackTime(seconds)

  // Scroll to the matching cue after a brief delay for DOM update
  setTimeout(() => {
    const el = document.querySelector('[data-cue-active="true"]')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      // Flash animation
      el.classList.add('cue-flash')
      setTimeout(() => el.classList.remove('cue-flash'), 1000)
    }
  }, 50)
}
