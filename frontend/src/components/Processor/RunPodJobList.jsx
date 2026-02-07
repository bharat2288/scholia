import { useState } from 'react'
import { Link } from 'react-router-dom'
import { API_BASE } from '../../config'
import './RunPodJobList.css'

function RunPodJobList({ jobs, onRefresh, onJobsChange, onConfigure }) {
  const [downloading, setDownloading] = useState({})
  const [downloadProgress, setDownloadProgress] = useState({})
  const [finalizing, setFinalizing] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const handleRefresh = async () => {
    setSyncing(true)
    try {
      // Just refresh the livestatus - no sync needed with new flow
      onRefresh?.()
    } catch (err) {
      console.error('Refresh error:', err)
    } finally {
      setSyncing(false)
    }
  }

  const handleDownload = async (job) => {
    // Use folder_name for download, not job_id
    const folderName = job.folder_name
    if (!folderName) {
      console.error('No folder_name for job:', job)
      return
    }

    setDownloading(prev => ({ ...prev, [job.job_id]: true }))
    setDownloadProgress(prev => ({
      ...prev,
      [job.job_id]: { step: 'Starting...', progress: 0, detail: '' }
    }))

    try {
      // Use SSE for streaming progress
      const eventSource = new EventSource(
        `${API_BASE}/runpod/download-stream/${encodeURIComponent(folderName)}`
      )

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          setDownloadProgress(prev => ({
            ...prev,
            [job.job_id]: {
              step: data.step,
              progress: data.progress,
              detail: data.detail
            }
          }))

          if (data.status === 'complete') {
            eventSource.close()
            setDownloading(prev => ({ ...prev, [job.job_id]: false }))
            setDownloadProgress(prev => {
              const next = { ...prev }
              delete next[job.job_id]
              return next
            })
            onRefresh?.()
          } else if (data.status === 'error') {
            eventSource.close()
            console.error('Download failed:', data.detail)
            setDownloadProgress(prev => ({
              ...prev,
              [job.job_id]: {
                step: 'Error',
                progress: 0,
                detail: data.detail,
                error: true
              }
            }))
            // Keep error visible for 5 seconds
            setTimeout(() => {
              setDownloading(prev => ({ ...prev, [job.job_id]: false }))
              setDownloadProgress(prev => {
                const next = { ...prev }
                delete next[job.job_id]
                return next
              })
            }, 5000)
          }
        } catch (err) {
          console.error('Error parsing SSE data:', err)
        }
      }

      eventSource.onerror = (err) => {
        console.error('SSE error:', err)
        eventSource.close()
        setDownloading(prev => ({ ...prev, [job.job_id]: false }))
        setDownloadProgress(prev => {
          const next = { ...prev }
          delete next[job.job_id]
          return next
        })
      }

    } catch (err) {
      console.error('Download error:', err)
      setDownloading(prev => ({ ...prev, [job.job_id]: false }))
      setDownloadProgress(prev => {
        const next = { ...prev }
        delete next[job.job_id]
        return next
      })
    }
  }

  const handleFinalizeAll = async () => {
    const downloadedJobs = jobs.filter(j => j.status === 'downloaded')
    if (downloadedJobs.length === 0) return

    setFinalizing(true)

    try {
      const res = await fetch(`${API_BASE}/runpod/finalize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: downloadedJobs.map(j => j.job_id) })
      })
      const data = await res.json()

      if (data.finalized?.length > 0) {
        onRefresh?.()
      }
    } catch (err) {
      console.error('Finalize error:', err)
    } finally {
      setFinalizing(false)
    }
  }

  const handleDelete = async (jobId) => {
    try {
      await fetch(`${API_BASE}/runpod/jobs/${jobId}`, {
        method: 'DELETE'
      })
      onRefresh?.()
    } catch (err) {
      console.error('Delete error:', err)
    }
  }

  // Status display helpers
  const getStatusDisplay = (job) => {
    switch (job.status) {
      case 'uploaded':
        return { label: 'Uploaded', class: 'status--pending' }
      case 'processing':
        return {
          label: job.total_pages > 0
            ? `Processing ${job.current_page}/${job.total_pages}`
            : 'Processing...',
          class: 'status--processing'
        }
      case 'complete_on_pod':
        return { label: 'Ready to download', class: 'status--ready' }
      case 'downloaded':
        return { label: 'Downloaded', class: 'status--downloaded' }
      case 'finalized':
        return { label: 'Complete', class: 'status--complete' }
      case 'error':
        return { label: 'Error', class: 'status--error' }
      default:
        return { label: job.status, class: '' }
    }
  }

  // Show empty state with sync option instead of hiding completely
  const isEmpty = !jobs || jobs.length === 0

  const downloadedCount = isEmpty ? 0 : jobs.filter(j => j.status === 'downloaded').length
  const readyToDownload = isEmpty ? 0 : jobs.filter(j => j.status === 'complete_on_pod').length

  return (
    <div className="runpod-job-list">
      <div className="runpod-header">
        <h3 className="runpod-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            <polyline points="7.5 4.21 12 6.81 16.5 4.21" />
            <polyline points="7.5 19.79 7.5 14.6 3 12" />
            <polyline points="21 12 16.5 14.6 16.5 19.79" />
            <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
            <line x1="12" y1="22.08" x2="12" y2="12" />
          </svg>
          RunPod Jobs
        </h3>
        <div className="runpod-header-actions">
          {readyToDownload > 0 && (
            <span className="badge badge--ready">{readyToDownload} ready</span>
          )}
          <button
            className="btn-sync"
            onClick={handleRefresh}
            disabled={syncing}
            title="Refresh status from pod"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={syncing ? 'spinning' : ''}
            >
              <path d="M21 2v6h-6" />
              <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
              <path d="M3 22v-6h6" />
              <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
            </svg>
            {syncing ? 'Refreshing...' : 'Refresh'}
          </button>
          <Link
            to="/processor/volume"
            className="btn-browse"
            title="Browse Network Volume"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
          </Link>
          <button
            className="btn-configure"
            onClick={onConfigure}
            title="Configure RunPod - manage pods, view status"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </button>
        </div>
      </div>

      {isEmpty ? (
        <div className="runpod-empty">
          <p className="runpod-empty-text">
            No jobs running or completed on pod. Click <strong>Refresh</strong> to check status.
          </p>
        </div>
      ) : (
        <div className="runpod-jobs">
          {jobs.map(job => {
            const status = getStatusDisplay(job)
            const isDownloading = downloading[job.job_id]

            return (
              <div key={job.job_id} className="runpod-job">
                <div className="job-info">
                  <span className="job-filename">{job.filename}</span>
                  <span className={`job-status ${status.class}`}>
                    {status.label}
                  </span>
                </div>

                {/* Download progress bar */}
                {downloadProgress[job.job_id] && (
                  <div className={`download-progress ${downloadProgress[job.job_id].error ? 'download-progress--error' : ''}`}>
                    <div className="download-progress-header">
                      <span className="download-step">{downloadProgress[job.job_id].step}</span>
                      <span className="download-percent">{downloadProgress[job.job_id].progress}%</span>
                    </div>
                    <div className="download-progress-bar">
                      <div
                        className="download-progress-fill"
                        style={{ width: `${downloadProgress[job.job_id].progress}%` }}
                      />
                    </div>
                    {downloadProgress[job.job_id].detail && (
                      <span className="download-detail">{downloadProgress[job.job_id].detail}</span>
                    )}
                  </div>
                )}

                <div className="job-actions">
                  {job.status === 'complete_on_pod' && !downloadProgress[job.job_id] && (
                    <button
                      className="btn-action btn-download"
                      onClick={() => handleDownload(job)}
                      disabled={isDownloading}
                    >
                      {isDownloading ? 'Starting...' : 'Download'}
                    </button>
                  )}

                  {job.status === 'finalized' && (
                    <span className="job-complete-badge">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </span>
                  )}

                  {job.status === 'error' && (
                    <span className="job-error" title={job.error}>
                      {job.error?.slice(0, 50)}
                    </span>
                  )}

                  {/* Only show delete for DB-tracked jobs (downloaded/finalized) */}
                  {(job.status === 'downloaded' || job.status === 'finalized') && (
                    <button
                      className="btn-action btn-delete"
                      onClick={() => handleDelete(job.job_id)}
                      title="Remove job record"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <line x1="18" y1="6" x2="6" y2="18" />
                        <line x1="6" y1="6" x2="18" y2="18" />
                      </svg>
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {downloadedCount > 0 && (
        <div className="runpod-footer">
          <button
            className="btn-finalize"
            onClick={handleFinalizeAll}
            disabled={finalizing}
          >
            {finalizing
              ? 'Finalizing...'
              : `Finalize ${downloadedCount} Downloaded Document${downloadedCount !== 1 ? 's' : ''}`
            }
          </button>
          <span className="finalize-hint">
            Runs text extraction and figure cropping
          </span>
        </div>
      )}
    </div>
  )
}

export default RunPodJobList
