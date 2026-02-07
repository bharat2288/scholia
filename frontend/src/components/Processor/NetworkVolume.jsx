import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE } from '../../config'
import './NetworkVolume.css'
const POLL_INTERVAL = 30000 // 30 seconds

function NetworkVolume() {
  const [volumeData, setVolumeData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [expandedFolders, setExpandedFolders] = useState({})
  const [folderContents, setFolderContents] = useState({})
  const [loadingFolders, setLoadingFolders] = useState({})

  const fetchVolumeStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/runpod/volume/browse`)
      const data = await res.json()

      if (data.error) {
        setError(data.error)
      } else {
        setVolumeData(data)
        setError(null)
      }
      setLastUpdated(new Date())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial fetch and polling
  useEffect(() => {
    fetchVolumeStatus()
    const interval = setInterval(fetchVolumeStatus, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [fetchVolumeStatus])

  const toggleFolder = async (folderPath) => {
    const isExpanded = expandedFolders[folderPath]

    if (isExpanded) {
      // Collapse
      setExpandedFolders(prev => ({ ...prev, [folderPath]: false }))
    } else {
      // Expand - fetch contents if not already loaded
      setExpandedFolders(prev => ({ ...prev, [folderPath]: true }))

      if (!folderContents[folderPath]) {
        setLoadingFolders(prev => ({ ...prev, [folderPath]: true }))
        try {
          const res = await fetch(`${API_BASE}/runpod/volume/browse?path=${encodeURIComponent(folderPath)}`)
          const data = await res.json()
          setFolderContents(prev => ({ ...prev, [folderPath]: data }))
        } catch (err) {
          console.error('Failed to load folder:', err)
        } finally {
          setLoadingFolders(prev => ({ ...prev, [folderPath]: false }))
        }
      }
    }
  }

  const formatSize = (bytes) => {
    if (!bytes) return '-'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return '-'
    const date = new Date(dateStr)
    return date.toLocaleString()
  }

  const getFolderIcon = (name, isExpanded) => {
    // Special icons for known folders
    const specialFolders = {
      'input': '📥',
      'output': '📤',
      'archive': '📦',
      'downloaded': '✅',
      'processing': '⚙️',
      'logs': '📋',
      'scripts': '📜',
      'dots_ocr_repo': '🔧'
    }

    if (specialFolders[name]) return specialFolders[name]
    return isExpanded ? '📂' : '📁'
  }

  const renderFolderContents = (contents, depth = 1) => {
    if (!contents || !contents.items) return null

    return (
      <div className="folder-contents" style={{ marginLeft: `${depth * 20}px` }}>
        {contents.items.map((item, idx) => (
          <div key={`${item.name}-${idx}`} className={`volume-item volume-item--${item.type}`}>
            {item.type === 'directory' ? (
              <>
                <div
                  className="item-row item-row--clickable"
                  onClick={() => toggleFolder(item.path)}
                >
                  <span className="item-icon">
                    {loadingFolders[item.path] ? '⏳' : getFolderIcon(item.name, expandedFolders[item.path])}
                  </span>
                  <span className="item-name">{item.name}/</span>
                  <span className="item-count">{item.count !== undefined ? `(${item.count} items)` : ''}</span>
                </div>
                {expandedFolders[item.path] && folderContents[item.path] && (
                  renderFolderContents(folderContents[item.path], depth + 1)
                )}
              </>
            ) : (
              <div className="item-row">
                <span className="item-icon">
                  {item.name.endsWith('.pdf') ? '📄' :
                   item.name.endsWith('.json') ? '📋' :
                   item.name.endsWith('.log') ? '📝' :
                   item.name.endsWith('.py') ? '🐍' :
                   item.name.endsWith('.md') ? '📝' :
                   item.name.endsWith('.txt') ? '📝' :
                   item.name.endsWith('.lock') ? '🔒' :
                   '📄'}
                </span>
                <span className="item-name">{item.name}</span>
                <span className="item-size">{formatSize(item.size)}</span>
                <span className="item-modified">{formatDate(item.modified)}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="network-volume-page">
      <header className="volume-header">
        <Link to="/processor" className="back-link">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Processor
        </Link>
        <h1 className="volume-title">
          Network Volume Browser
          <svg className="volume-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            <polyline points="7.5 4.21 12 6.81 16.5 4.21" />
            <polyline points="7.5 19.79 7.5 14.6 3 12" />
            <polyline points="21 12 16.5 14.6 16.5 19.79" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
        </h1>
        <div className="volume-actions">
          <button
            className="btn-refresh"
            onClick={fetchVolumeStatus}
            disabled={loading}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={loading ? 'spinning' : ''}
            >
              <path d="M21 2v6h-6" />
              <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
              <path d="M3 22v-6h6" />
              <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
            </svg>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
          {lastUpdated && (
            <span className="last-updated">
              Updated: {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
      </header>

      <main className="volume-main">
        {error && (
          <div className="volume-error">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            {error}
          </div>
        )}

        {loading && !volumeData && (
          <div className="volume-loading">
            <div className="loading-spinner"></div>
            <p>Connecting to RunPod...</p>
          </div>
        )}

        {volumeData && (
          <div className="volume-content">
            {/* Summary stats */}
            {volumeData.summary && (
              <div className="volume-summary">
                <div className="summary-card">
                  <span className="summary-icon">📥</span>
                  <span className="summary-label">Input</span>
                  <span className="summary-value">{volumeData.summary.input_count || 0}</span>
                </div>
                <div className="summary-card">
                  <span className="summary-icon">⚙️</span>
                  <span className="summary-label">Processing</span>
                  <span className="summary-value">{volumeData.summary.processing_count || 0}</span>
                </div>
                <div className="summary-card">
                  <span className="summary-icon">📤</span>
                  <span className="summary-label">Output</span>
                  <span className="summary-value">{volumeData.summary.output_count || 0}</span>
                </div>
                <div className="summary-card">
                  <span className="summary-icon">📦</span>
                  <span className="summary-label">Archive</span>
                  <span className="summary-value">{volumeData.summary.archive_count || 0}</span>
                </div>
                <div className="summary-card">
                  <span className="summary-icon">✅</span>
                  <span className="summary-label">Downloaded</span>
                  <span className="summary-value">{volumeData.summary.downloaded_count || 0}</span>
                </div>
              </div>
            )}

            {/* Folder tree */}
            <div className="volume-tree">
              <div className="tree-header">
                <span className="label label--accent">/workspace</span>
              </div>
              {volumeData.folders && volumeData.folders.map((folder, idx) => (
                <div key={`${folder.name}-${idx}`} className="volume-folder">
                  <div
                    className="folder-row folder-row--clickable"
                    onClick={() => toggleFolder(folder.path)}
                  >
                    <span className="folder-icon">
                      {loadingFolders[folder.path] ? '⏳' : getFolderIcon(folder.name, expandedFolders[folder.path])}
                    </span>
                    <span className="folder-name">{folder.name}/</span>
                    <span className="folder-count">
                      {folder.count !== undefined ? `${folder.count} items` : ''}
                    </span>
                    <span className="folder-size">{formatSize(folder.total_size)}</span>
                  </div>
                  {expandedFolders[folder.path] && folderContents[folder.path] && (
                    renderFolderContents(folderContents[folder.path])
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default NetworkVolume
