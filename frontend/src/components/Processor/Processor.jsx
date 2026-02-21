import { useState, useCallback, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import DropZone from './DropZone'
import FileQueue from './FileQueue'
import RunPodConfigModal from './RunPodConfigModal'
import RunPodJobList from './RunPodJobList'
import { API_BASE } from '../../config'
import './Processor.css'
const STORAGE_KEY = 'scholia-processor-jobs'
const RUNPOD_POLL_INTERVAL = 120000 // 2 minutes

function Processor() {
  const [files, setFiles] = useState([])
  const pollIntervalsRef = useRef({})
  const initialLoadDone = useRef(false)
  const queryClient = useQueryClient()

  // RunPod state
  const [runpodConfigured, setRunpodConfigured] = useState(false)
  const [runpodJobs, setRunpodJobs] = useState([])
  const [runpodSummary, setRunpodSummary] = useState(null)
  const [showConfigModal, setShowConfigModal] = useState(false)
  const runpodPollRef = useRef(null)

  // Toast state
  const [toast, setToast] = useState(null)
  const toastTimeoutRef = useRef(null)

  const showToast = useCallback((message, type = 'info') => {
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current)
    }
    setToast({ message, type })
    toastTimeoutRef.current = setTimeout(() => setToast(null), 3000)
  }, [])

  // Poll for processing status
  const pollStatus = useCallback((fileId, tempId) => {
    if (pollIntervalsRef.current[tempId]) {
      return pollIntervalsRef.current[tempId]
    }

    const pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/processor/status/${tempId}`)
        if (!response.ok) {
          clearInterval(pollInterval)
          delete pollIntervalsRef.current[tempId]
          return
        }

        const status = await response.json()

        setFiles(prev => prev.map(f => {
          if (f.id !== fileId) return f

          if (status.status === 'complete') {
            clearInterval(pollInterval)
            delete pollIntervalsRef.current[tempId]
            // Invalidate documents query so Library view updates
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            return {
              ...f,
              status: 'complete',
              result: {
                output_filename: status.output_filename,
                folder_name: status.folder_name
              },
              progress: null,
              startTime: null,
              queuePosition: null
            }
          } else if (status.status === 'error') {
            clearInterval(pollInterval)
            delete pollIntervalsRef.current[tempId]
            return {
              ...f,
              status: 'error',
              error: status.error,
              progress: null,
              startTime: null,
              queuePosition: null
            }
          } else if (status.status === 'cancelled') {
            clearInterval(pollInterval)
            delete pollIntervalsRef.current[tempId]
            return {
              ...f,
              status: 'ready',
              progress: null,
              startTime: null,
              queuePosition: null
            }
          } else if (status.status === 'queued') {
            return {
              ...f,
              status: 'queued',
              queuePosition: status.queue_position,
              progress: null
            }
          } else {
            return {
              ...f,
              status: 'processing',
              queuePosition: status.queue_position,
              progress: {
                percent: status.percent,
                currentPage: status.current_page,
                totalPages: status.total_pages,
                stage: status.stage
              },
              startTime: f.status === 'queued' ? Date.now() : f.startTime
            }
          }
        }))
      } catch (err) {
        console.error('Status poll error:', err)
      }
    }, 500)

    pollIntervalsRef.current[tempId] = pollInterval
    return pollInterval
  }, [queryClient])

  // Restore jobs on mount (active + completed for session history)
  useEffect(() => {
    if (initialLoadDone.current) return
    initialLoadDone.current = true

    const restoreJobs = async () => {
      const savedJobs = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}')
      const restoredFiles = []

      // First, restore completed jobs from localStorage (session history)
      for (const [jobId, savedJob] of Object.entries(savedJobs)) {
        if (savedJob.status === 'complete') {
          restoredFiles.push({
            id: savedJob.id,
            file: null,
            name: savedJob.name,
            status: 'complete',
            assessment: savedJob.assessment,
            selectedTier: savedJob.selectedTier,
            result: savedJob.result,
            error: null,
            progress: null,
            queuePosition: null,
            startTime: null
          })
        }
      }

      // Then, try to reconnect to active jobs on the backend
      try {
        const healthCheck = await fetch(`${API_BASE}/`)
        if (!healthCheck.ok) {
          if (restoredFiles.length > 0) {
            setFiles(restoredFiles)
          }
          return
        }

        const response = await fetch(`${API_BASE}/processor/queue`)
        if (!response.ok) {
          if (restoredFiles.length > 0) {
            setFiles(restoredFiles)
          }
          return
        }

        const allStatus = await response.json()

        for (const [tempId, status] of Object.entries(allStatus)) {
          if (!['processing', 'queued'].includes(status.status)) continue

          // Find saved job by temp_id in assessment (may not exist if browser was closed)
          const savedJob = Object.values(savedJobs).find(
            j => j.assessment?.temp_id === tempId
          )

          // Create entry using backend data, fall back to savedJob if available
          const fileEntry = {
            id: savedJob?.id || crypto.randomUUID(),
            file: null,
            name: savedJob?.name || status.filename || `Job ${tempId}`,
            status: status.status,
            assessment: savedJob?.assessment || {
              temp_id: tempId,
              total_pages: status.total_pages,
              filename: status.filename
            },
            selectedTier: savedJob?.selectedTier || status.tier || 'marker',
            result: null,
            error: null,
            progress: status.status === 'processing' ? {
              percent: status.percent,
              currentPage: status.current_page,
              totalPages: status.total_pages,
              stage: status.stage
            } : null,
            queuePosition: status.queue_position,
            startTime: savedJob?.startTime || null
          }

          restoredFiles.push(fileEntry)
          pollStatus(fileEntry.id, tempId)
        }

        if (restoredFiles.length > 0) {
          setFiles(restoredFiles)
          const activeCount = restoredFiles.filter(f => ['processing', 'queued'].includes(f.status)).length
          const completedCount = restoredFiles.filter(f => f.status === 'complete').length
          console.log(`Restored ${activeCount} active job(s), ${completedCount} completed job(s)`)
        }
      } catch (err) {
        console.log('Could not reconnect to backend:', err.message)
        // Still show completed jobs even if backend is down
        if (restoredFiles.length > 0) {
          setFiles(restoredFiles)
        }
      }
    }

    restoreJobs()
  }, [pollStatus])

  // Save jobs to localStorage (active + completed for session history)
  useEffect(() => {
    const jobsToSave = {}
    for (const file of files) {
      // Save active jobs (for reconnection) and completed jobs (for session history)
      if (['processing', 'queued', 'starting', 'complete'].includes(file.status)) {
        jobsToSave[file.id] = {
          id: file.id,
          name: file.name,
          status: file.status,
          assessment: file.assessment,
          selectedTier: file.selectedTier,
          startTime: file.startTime,
          result: file.result,
          error: file.error
        }
      }
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(jobsToSave))
  }, [files])

  // Check RunPod config on mount and fetch livestatus immediately if configured
  useEffect(() => {
    const init = async () => {
      try {
        const configRes = await fetch(`${API_BASE}/runpod/config`)
        const configData = await configRes.json()

        if (configData.configured) {
          setRunpodConfigured(true)
          // Fetch livestatus immediately (real-time status from pod)
          // fetchRunpodJobs will be called once runpodConfigured is true
        }
      } catch (err) {
        console.log('RunPod init failed:', err.message)
      }
    }
    init()
  }, [])

  // Poll RunPod livestatus (real-time status from pod, not local DB)
  const fetchRunpodJobs = useCallback(async () => {
    if (!runpodConfigured) return

    try {
      const res = await fetch(`${API_BASE}/runpod/livestatus`)
      const data = await res.json()

      if (data.status === 'ok') {
        // Transform livestatus format to job-like objects for the UI
        const jobs = []

        // Add processing jobs
        for (const proc of (data.processing || [])) {
          jobs.push({
            job_id: `proc-${proc.pod_id}-${proc.pdf_name}`,
            filename: proc.pdf_name,
            status: proc.status === 'failed' ? 'error' : 'processing',
            current_page: proc.current_page,
            total_pages: proc.total_pages,
            folder_name: null,
            error: proc.status === 'failed' ? 'Processing stalled' : null
          })
        }

        // Add ready_to_download jobs (v3: in /archive/ with PDF + folder)
        for (const ready of (data.ready_to_download || [])) {
          jobs.push({
            job_id: `ready-${ready.folder}`,
            filename: ready.pdf_name || ready.folder,
            status: 'complete_on_pod',
            current_page: ready.page_count,
            total_pages: ready.page_count,
            folder_name: ready.folder,
            error: ready.warning || null
          })
        }

        // Also show legacy_completed if any (need migration)
        for (const legacy of (data.legacy_completed || [])) {
          jobs.push({
            job_id: `legacy-${legacy.folder}`,
            filename: legacy.folder,
            status: 'complete_on_pod',
            current_page: legacy.page_count,
            total_pages: legacy.page_count,
            folder_name: legacy.folder,
            error: 'Legacy: in /output/, needs v3 coordinator'
          })
        }

        // Backwards compat: also check old 'completed' field (v2 livestatus)
        for (const comp of (data.completed || [])) {
          // Only add if not already in ready_to_download
          const alreadyAdded = jobs.some(j => j.folder_name === comp.folder)
          if (!alreadyAdded) {
            jobs.push({
              job_id: `complete-${comp.folder}`,
              filename: comp.folder,
              status: 'complete_on_pod',
              current_page: comp.page_count,
              total_pages: comp.page_count,
              folder_name: comp.folder,
              error: null
            })
          }
        }

        setRunpodJobs(jobs)

        // Also store summary for display
        setRunpodSummary(data.summary || null)
      } else {
        console.warn('Livestatus not available:', data.error)
      }
    } catch (err) {
      console.error('RunPod livestatus poll failed:', err)
    }
  }, [runpodConfigured])

  // Start/stop RunPod polling based on config status
  useEffect(() => {
    if (runpodConfigured) {
      // Initial fetch
      fetchRunpodJobs()

      // Poll every 2 minutes
      runpodPollRef.current = setInterval(fetchRunpodJobs, RUNPOD_POLL_INTERVAL)
    }

    return () => {
      if (runpodPollRef.current) {
        clearInterval(runpodPollRef.current)
      }
    }
  }, [runpodConfigured]) // Note: don't include fetchRunpodJobs to avoid infinite loop

  // Detect file type from file object
  const getFileType = useCallback((file) => {
    if (file.type === 'application/epub+zip' || file.name.toLowerCase().endsWith('.epub')) {
      return 'epub'
    }
    return 'pdf'
  }, [])

  // Handle files dropped or selected
  const handleFilesAdded = useCallback(async (newFiles) => {
    const fileEntries = newFiles.map(file => ({
      id: crypto.randomUUID(),
      file,
      name: file.name,
      fileType: getFileType(file),
      status: 'assessing',
      assessment: null,
      selectedTier: null,
      result: null,
      error: null
    }))

    setFiles(prev => [...prev, ...fileEntries])

    for (const entry of fileEntries) {
      try {
        const formData = new FormData()
        formData.append('file', entry.file)

        // Use different endpoint for EPUB vs PDF
        const assessUrl = entry.fileType === 'epub'
          ? `${API_BASE}/processor/assess-epub`
          : `${API_BASE}/processor/assess`

        const response = await fetch(assessUrl, {
          method: 'POST',
          body: formData
        })

        if (!response.ok) {
          throw new Error('Assessment failed')
        }

        const assessment = await response.json()

        setFiles(prev => prev.map(f =>
          f.id === entry.id
            ? {
                ...f,
                status: 'ready',
                assessment,
                // EPUBs don't need tier selection
                selectedTier: entry.fileType === 'epub' ? 'epub' : assessment.recommendation
              }
            : f
        ))
      } catch (err) {
        setFiles(prev => prev.map(f =>
          f.id === entry.id
            ? { ...f, status: 'error', error: err.message }
            : f
        ))
      }
    }
  }, [getFileType])

  // Handle tier selection change
  const handleTierChange = useCallback((fileId, tier) => {
    setFiles(prev => prev.map(f =>
      f.id === fileId ? { ...f, selectedTier: tier } : f
    ))
  }, [])

  // Handle process button click
  const handleProcess = useCallback(async (fileId) => {
    const file = files.find(f => f.id === fileId)
    if (!file || !file.assessment) return

    // Handle RunPod tier differently
    if (file.selectedTier === 'runpod') {
      if (!runpodConfigured) {
        setShowConfigModal(true)
        return
      }

      setFiles(prev => prev.map(f =>
        f.id === fileId ? { ...f, status: 'starting', progress: { percent: 0, stage: 'uploading to RunPod' } } : f
      ))

      try {
        // Re-read the file from the assessment temp location
        const formData = new FormData()
        // We need to get the file from the backend's temp storage
        // The file object might not be available anymore, so we'll use the temp_id
        const uploadRes = await fetch(`${API_BASE}/runpod/upload?temp_id=${file.assessment.temp_id}`, {
          method: 'POST'
        })

        if (!uploadRes.ok) {
          // Fallback: if temp_id upload doesn't work, try with the original file
          if (file.file) {
            formData.append('file', file.file)
            const fallbackRes = await fetch(`${API_BASE}/runpod/upload`, {
              method: 'POST',
              body: formData
            })
            if (!fallbackRes.ok) {
              throw new Error('Upload to RunPod failed')
            }
          } else {
            throw new Error('Upload to RunPod failed')
          }
        }

        // Remove from local queue, job is now tracked in RunPod jobs
        setFiles(prev => prev.filter(f => f.id !== fileId))
        // Refresh RunPod jobs
        fetchRunpodJobs()

      } catch (err) {
        setFiles(prev => prev.map(f =>
          f.id === fileId
            ? { ...f, status: 'error', error: err.message }
            : f
        ))
      }
      return
    }

    // EPUB processing — fast, no GPU queue needed
    if (file.fileType === 'epub') {
      setFiles(prev => prev.map(f =>
        f.id === fileId ? { ...f, status: 'processing', progress: { percent: 50, stage: 'extracting' } } : f
      ))

      try {
        const params = new URLSearchParams({ temp_id: file.assessment.temp_id })
        // Pass metadata overrides if the user edited them
        if (file.epubOverrides?.title) params.set('title', file.epubOverrides.title)
        if (file.epubOverrides?.author) params.set('author', file.epubOverrides.author)
        if (file.epubOverrides?.year) params.set('year', file.epubOverrides.year)

        const response = await fetch(`${API_BASE}/processor/process-epub?${params}`, {
          method: 'POST'
        })

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}))
          throw new Error(errData.detail || 'EPUB processing failed')
        }

        const result = await response.json()

        // Invalidate documents query so Library view updates
        queryClient.invalidateQueries({ queryKey: ['documents'] })

        setFiles(prev => prev.map(f =>
          f.id === fileId
            ? {
                ...f,
                status: 'complete',
                result: { folder_name: result.folder_name, source_id: result.source_id },
                progress: null
              }
            : f
        ))
      } catch (err) {
        setFiles(prev => prev.map(f =>
          f.id === fileId
            ? { ...f, status: 'error', error: err.message, progress: null }
            : f
        ))
      }
      return
    }

    // Normal PDF local processing
    setFiles(prev => prev.map(f =>
      f.id === fileId ? { ...f, status: 'starting', progress: { percent: 0, stage: 'starting' } } : f
    ))

    try {
      const response = await fetch(`${API_BASE}/processor/process?temp_id=${file.assessment.temp_id}&tier=${file.selectedTier}`, {
        method: 'POST'
      })

      if (!response.ok) {
        throw new Error('Processing failed')
      }

      const result = await response.json()

      if (result.status === 'queued') {
        setFiles(prev => prev.map(f =>
          f.id === fileId
            ? { ...f, status: 'queued', queuePosition: result.queue_position, progress: null }
            : f
        ))
      } else {
        setFiles(prev => prev.map(f =>
          f.id === fileId
            ? { ...f, status: 'processing', queuePosition: 0, progress: { percent: 0, stage: 'starting' }, startTime: Date.now() }
            : f
        ))
      }

      pollStatus(fileId, file.assessment.temp_id)

    } catch (err) {
      setFiles(prev => prev.map(f =>
        f.id === fileId
          ? { ...f, status: 'error', error: err.message }
          : f
      ))
    }
  }, [files, pollStatus, runpodConfigured, fetchRunpodJobs, queryClient])

  // Handle cancel button click
  const handleCancel = useCallback(async (fileId) => {
    const file = files.find(f => f.id === fileId)
    if (!file || !file.assessment) return

    const fileName = file.name

    // Immediately update UI to show cancelling state, then ready
    setFiles(prev => prev.map(f =>
      f.id === fileId
        ? { ...f, status: 'ready', progress: null, startTime: null, queuePosition: null }
        : f
    ))

    // Stop polling for this job
    const tempId = file.assessment.temp_id
    if (pollIntervalsRef.current[tempId]) {
      clearInterval(pollIntervalsRef.current[tempId])
      delete pollIntervalsRef.current[tempId]
    }

    // Show toast immediately
    showToast(`Cancelled: ${fileName}`, 'info')

    try {
      const response = await fetch(`${API_BASE}/processor/cancel/${tempId}`, {
        method: 'POST'
      })
      if (response.ok) {
        console.log(`Job ${tempId} cancelled`)
      }
    } catch (err) {
      console.error('Cancel error:', err)
    }
  }, [files, showToast])

  // Handle EPUB metadata override from editable fields
  const handleEpubOverride = useCallback((fileId, field, value) => {
    setFiles(prev => prev.map(f =>
      f.id === fileId
        ? { ...f, epubOverrides: { ...f.epubOverrides, [field]: value } }
        : f
    ))
  }, [])

  // Handle process all ready files
  const handleProcessAll = useCallback(() => {
    const readyFiles = files.filter(f => f.status === 'ready')
    readyFiles.forEach(f => handleProcess(f.id))
  }, [files, handleProcess])

  // Handle remove file from queue
  const handleRemove = useCallback((fileId) => {
    setFiles(prev => prev.filter(f => f.id !== fileId))
  }, [])

  const readyCount = files.filter(f => f.status === 'ready').length

  return (
    <div className="processor-page">
      {/* Toast notification */}
      {toast && (
        <div className={`processor-toast processor-toast--${toast.type}`}>
          {toast.message}
        </div>
      )}

      <header className="processor-header">
        <Link to="/" className="back-link">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          Library
        </Link>
        <h1 className="processor-title">
          Lit Processor
          {/* Hand-drawn stacked pages element */}
          <svg
            className="hand-drawn-pages"
            width="44"
            height="44"
            viewBox="0 0 44 44"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            {/* Back page - slightly rotated */}
            <path
              d="M10 8 L32 6 L34 34 L12 36 Z"
              stroke="#d4a574"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
            {/* Middle page */}
            <path
              d="M8 10 L30 10 L30 38 L8 38 Z"
              stroke="#d4a574"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
            {/* Front page with fold */}
            <path
              d="M6 12 L28 12 L28 40 L6 40 Z"
              stroke="#cd8264"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
            {/* Page lines - hand-drawn wavy */}
            <path d="M10 20 Q14 19, 18 20 Q22 21, 24 20" stroke="#d4a574" strokeWidth="1" strokeLinecap="round" fill="none" opacity="0.7"/>
            <path d="M10 26 Q15 27, 20 26 Q23 25, 24 26" stroke="#d4a574" strokeWidth="1" strokeLinecap="round" fill="none" opacity="0.7"/>
            <path d="M10 32 Q13 31, 16 32" stroke="#d4a574" strokeWidth="1" strokeLinecap="round" fill="none" opacity="0.7"/>
          </svg>
        </h1>
        <p className="processor-subtitle">PDF &amp; EPUB extraction for academic literature</p>
      </header>

      <main className="processor-main">
        <DropZone onFilesAdded={handleFilesAdded} />

        {/* RunPod Jobs Section - show when configured (even if no jobs yet) */}
        {runpodConfigured && (
          <RunPodJobList
            jobs={runpodJobs}
            onRefresh={fetchRunpodJobs}
            onConfigure={() => setShowConfigModal(true)}
          />
        )}

        {files.length > 0 && (
          <section className="queue-section">
            <div className="queue-header">
              <span className="label label--accent">Processing Queue</span>
              <div className="queue-actions">
                {!runpodConfigured && (
                  <button
                    className="btn-secondary btn-configure"
                    onClick={() => setShowConfigModal(true)}
                  >
                    Configure RunPod
                  </button>
                )}
                {readyCount > 1 && (
                  <button
                    className="btn-primary"
                    onClick={handleProcessAll}
                  >
                    Process All ({readyCount})
                  </button>
                )}
              </div>
            </div>

            <FileQueue
              files={files}
              onTierChange={handleTierChange}
              onProcess={handleProcess}
              onCancel={handleCancel}
              onRemove={handleRemove}
              onEpubOverride={handleEpubOverride}
              runpodConfigured={runpodConfigured}
              onConfigureRunPod={() => setShowConfigModal(true)}
            />
          </section>
        )}
      </main>

      {/* RunPod Config Modal */}
      <RunPodConfigModal
        isOpen={showConfigModal}
        onClose={() => setShowConfigModal(false)}
        onConfigured={() => {
          setRunpodConfigured(true)
          fetchRunpodJobs()
        }}
      />
    </div>
  )
}

export default Processor
