import { Link, useLocation } from 'react-router-dom'
import useDeviceLayout from '../../hooks/useDeviceLayout'

/**
 * Fixed bottom navigation bar for mobile devices.
 * Three tabs: Library, Knowledge, Research.
 * Only rendered when layout === 'mobile'.
 */
export default function MobileNavBar() {
  const layout = useDeviceLayout()
  const location = useLocation()

  // Only show on mobile, and not inside Reader (has its own chrome)
  if (layout !== 'mobile') return null
  if (location.pathname.startsWith('/read/')) return null
  if (location.pathname.startsWith('/edit/')) return null

  const tabs = [
    {
      to: '/',
      label: 'Library',
      match: location.pathname === '/' || location.pathname === '/processor',
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
        </svg>
      )
    },
    {
      to: '/knowledge',
      label: 'Knowledge',
      match: location.pathname.startsWith('/knowledge') || location.pathname.startsWith('/gluon'),
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      )
    },
    {
      to: '/research',
      label: 'Research',
      match: location.pathname.startsWith('/research'),
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      )
    }
  ]

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-40 bg-surface border-t border-subtle h-14 flex items-center justify-around safe-area-bottom">
      {tabs.map((tab) => (
        <Link
          key={tab.to}
          to={tab.to}
          className={`flex flex-col items-center justify-center gap-0.5 flex-1 h-full transition-colors ${
            tab.match
              ? 'text-camel'
              : 'text-muted hover:text-secondary'
          }`}
        >
          {tab.icon}
          <span className="text-[10px] font-medium">{tab.label}</span>
        </Link>
      ))}
    </nav>
  )
}
