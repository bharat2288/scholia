import { useState, useEffect } from 'react'
import { API_BASE } from '../../config'
import './RunPodConfigModal.css'

function RunPodConfigModal({ isOpen, onClose, onConfigured }) {
  const [activeTab, setActiveTab] = useState('status')

  // API config state
  const [apiConfig, setApiConfig] = useState({
    hasApiKey: false,
    configured: false,
    networkVolumeId: '',
    volumeInfo: null
  })

  // SSH config state (for manual connection)
  const [sshConfig, setSshConfig] = useState({
    host: '',
    port: '',
    pod_id: '',
    ssh_key_path: ''
  })

  // Pods state
  const [pods, setPods] = useState([])
  const [podsLoading, setPodsLoading] = useState(false)
  const [coordinatorStatus, setCoordinatorStatus] = useState({}) // { podId: { running, pid, checking, starting } }

  // Volume status
  const [volumeStatus, setVolumeStatus] = useState(null)

  // UI state
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState(null)

  // Launch config
  const [launchConfig, setLaunchConfig] = useState({
    count: 1,
    gpuType: 'NVIDIA A40',
    autoStartCoordinator: true
  })

  // Load config on open
  useEffect(() => {
    if (isOpen) {
      loadApiConfig()
      loadSshConfig()
      loadPods()
    }
  }, [isOpen])

  const loadApiConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/runpod/api-config`)
      const data = await res.json()
      setApiConfig({
        hasApiKey: data.has_api_key,
        configured: data.configured,
        networkVolumeId: data.network_volume_id || '',
        volumeInfo: data.volume_info
      })
    } catch (err) {
      console.error('Failed to load API config:', err)
    }
  }

  const loadSshConfig = async () => {
    try {
      const res = await fetch(`${API_BASE}/runpod/config`)
      const data = await res.json()
      if (data.configured) {
        setSshConfig({
          host: data.host || '',
          port: data.port?.toString() || '',
          pod_id: data.pod_id || '',
          ssh_key_path: data.ssh_key_path || ''
        })
      }
    } catch (err) {
      console.error('Failed to load SSH config:', err)
    }
  }

  const loadPods = async () => {
    setPodsLoading(true)
    try {
      const res = await fetch(`${API_BASE}/runpod/pods`)
      if (res.ok) {
        const data = await res.json()
        const podList = data.pods || []
        setPods(podList)

        // Check coordinator status for running pods with SSH
        for (const pod of podList) {
          if (pod.status === 'RUNNING' && pod.ssh_host && pod.ssh_port) {
            checkCoordinatorStatus(pod)
          }
        }
      }
    } catch (err) {
      console.error('Failed to load pods:', err)
    } finally {
      setPodsLoading(false)
    }
  }

  const checkCoordinatorStatus = async (pod) => {
    setCoordinatorStatus(prev => ({
      ...prev,
      [pod.pod_id]: { ...prev[pod.pod_id], checking: true }
    }))

    try {
      const res = await fetch(`${API_BASE}/runpod/coordinator/status?ssh_host=${pod.ssh_host}&ssh_port=${pod.ssh_port}`)
      const data = await res.json()
      setCoordinatorStatus(prev => ({
        ...prev,
        [pod.pod_id]: { running: data.running, pid: data.pid, checking: false, starting: false }
      }))
    } catch (err) {
      console.error('Failed to check coordinator status:', err)
      setCoordinatorStatus(prev => ({
        ...prev,
        [pod.pod_id]: { running: false, checking: false, error: err.message }
      }))
    }
  }

  const handleStartCoordinator = async (pod) => {
    setCoordinatorStatus(prev => ({
      ...prev,
      [pod.pod_id]: { ...prev[pod.pod_id], starting: true }
    }))

    try {
      const res = await fetch(`${API_BASE}/runpod/coordinator/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssh_host: pod.ssh_host, ssh_port: pod.ssh_port })
      })
      const data = await res.json()

      if (data.status === 'started' || data.status === 'already_running') {
        setCoordinatorStatus(prev => ({
          ...prev,
          [pod.pod_id]: { running: true, pid: data.pid, starting: false }
        }))
      } else {
        setError(`Failed to start coordinator on ${pod.name}: ${data.error || 'Unknown error'}`)
        setCoordinatorStatus(prev => ({
          ...prev,
          [pod.pod_id]: { running: false, starting: false }
        }))
      }
    } catch (err) {
      setError(`Failed to start coordinator: ${err.message}`)
      setCoordinatorStatus(prev => ({
        ...prev,
        [pod.pod_id]: { running: false, starting: false }
      }))
    }
  }

  const handleStopCoordinator = async (pod) => {
    setCoordinatorStatus(prev => ({
      ...prev,
      [pod.pod_id]: { ...prev[pod.pod_id], starting: true }
    }))

    try {
      const res = await fetch(`${API_BASE}/runpod/coordinator/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssh_host: pod.ssh_host, ssh_port: pod.ssh_port })
      })
      const data = await res.json()

      setCoordinatorStatus(prev => ({
        ...prev,
        [pod.pod_id]: { running: false, pid: null, starting: false }
      }))
    } catch (err) {
      setError(`Failed to stop coordinator: ${err.message}`)
      setCoordinatorStatus(prev => ({
        ...prev,
        [pod.pod_id]: { ...prev[pod.pod_id], starting: false }
      }))
    }
  }

  const handleStartAllCoordinators = async () => {
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/runpod/coordinator/start-all`, { method: 'POST' })
      const data = await res.json()

      // Update status for each pod
      for (const result of data.results || []) {
        setCoordinatorStatus(prev => ({
          ...prev,
          [result.pod_id]: {
            running: result.status === 'started' || result.status === 'already_running',
            pid: result.pid,
            starting: false
          }
        }))
      }

      // Show errors if any
      const failures = (data.results || []).filter(r => r.status === 'failed')
      if (failures.length > 0) {
        setError(`Failed to start on ${failures.length} pod(s)`)
      }
    } catch (err) {
      setError(`Failed to start coordinators: ${err.message}`)
    }
  }

  const loadVolumeStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/runpod/volume/status`)
      if (res.ok) {
        const data = await res.json()
        setVolumeStatus(data)
      }
    } catch (err) {
      console.error('Failed to load volume status:', err)
    }
  }

  const handleTestApi = async () => {
    setTesting(true)
    setTestResult(null)
    setError(null)

    try {
      const res = await fetch(`${API_BASE}/runpod/api-test`, { method: 'POST' })
      const result = await res.json()
      setTestResult(result)

      if (result.success) {
        loadPods()
        onConfigured?.()
      }
    } catch (err) {
      setError(err.message)
      setTestResult({ success: false, error: err.message })
    } finally {
      setTesting(false)
    }
  }

  const handleSaveSshConfig = async () => {
    if (!sshConfig.host || !sshConfig.port) {
      setError('Host and port are required')
      return
    }

    setSaving(true)
    setError(null)

    try {
      const res = await fetch(`${API_BASE}/runpod/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: sshConfig.host,
          port: parseInt(sshConfig.port),
          pod_id: sshConfig.pod_id || null,
          ssh_key_path: sshConfig.ssh_key_path || null
        })
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to save config')
      }

      onConfigured?.()
      loadVolumeStatus()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleLaunchPods = async () => {
    setLaunching(true)
    setError(null)

    try {
      const res = await fetch(`${API_BASE}/runpod/pods/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          count: launchConfig.count,
          gpu_type: launchConfig.gpuType,
          auto_start_coordinator: launchConfig.autoStartCoordinator
        })
      })

      const result = await res.json()

      if (result.errors?.length > 0) {
        setError(result.errors.join(', '))
      }

      if (result.launched > 0) {
        loadPods()

        // If auto-start is enabled, wait and then start coordinators
        if (launchConfig.autoStartCoordinator) {
          // Poll for pods to be ready, then start coordinators
          setTimeout(async () => {
            await pollAndStartCoordinators(result.pods.map(p => p.pod_id))
          }, 5000) // Initial delay before polling
        }
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLaunching(false)
    }
  }

  const pollAndStartCoordinators = async (podIds, attempts = 0) => {
    if (attempts > 12) { // Max ~60 seconds of polling
      console.log('Gave up waiting for pods to be ready')
      return
    }

    // Refresh pods list
    const res = await fetch(`${API_BASE}/runpod/pods`)
    if (!res.ok) return

    const data = await res.json()
    const newPods = data.pods || []
    setPods(newPods)

    // Check which of our launched pods are ready
    const readyPods = newPods.filter(
      p => podIds.includes(p.pod_id) && p.status === 'RUNNING' && p.ssh_host && p.ssh_port
    )

    if (readyPods.length === 0) {
      // None ready yet, poll again
      setTimeout(() => pollAndStartCoordinators(podIds, attempts + 1), 5000)
      return
    }

    // Start coordinators on ready pods
    for (const pod of readyPods) {
      await handleStartCoordinator(pod)
    }

    // Check if more pods still starting
    const stillStarting = newPods.filter(
      p => podIds.includes(p.pod_id) && (p.status === 'STARTING' || p.status === 'CREATED')
    )

    if (stillStarting.length > 0) {
      // Keep polling for remaining pods
      setTimeout(() => pollAndStartCoordinators(
        stillStarting.map(p => p.pod_id),
        attempts + 1
      ), 5000)
    }
  }

  const handleTerminatePod = async (podId) => {
    try {
      const res = await fetch(`${API_BASE}/runpod/pods/${podId}`, {
        method: 'DELETE'
      })

      if (res.ok) {
        loadPods()
      } else {
        const err = await res.json()
        setError(err.detail || 'Failed to terminate pod')
      }
    } catch (err) {
      setError(err.message)
    }
  }

  const handleTerminateAll = async () => {
    if (!confirm('Terminate all pods? This cannot be undone.')) return

    try {
      const res = await fetch(`${API_BASE}/runpod/pods`, {
        method: 'DELETE'
      })

      if (res.ok) {
        loadPods()
      } else {
        const err = await res.json()
        setError(err.detail || 'Failed to terminate pods')
      }
    } catch (err) {
      setError(err.message)
    }
  }

  const handleConnectToPod = async (pod) => {
    if (pod.ssh_host && pod.ssh_port) {
      // Save directly to backend (don't rely on state update timing)
      setSaving(true)
      setError(null)

      try {
        const res = await fetch(`${API_BASE}/runpod/config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            host: pod.ssh_host,
            port: pod.ssh_port,
            pod_id: pod.pod_id,
            ssh_key_path: sshConfig.ssh_key_path || null
          })
        })

        if (!res.ok) {
          const err = await res.json()
          throw new Error(err.detail || 'Failed to save config')
        }

        // Update local state to match
        setSshConfig({
          host: pod.ssh_host,
          port: pod.ssh_port.toString(),
          pod_id: pod.pod_id,
          ssh_key_path: sshConfig.ssh_key_path
        })

        onConfigured?.()
        loadVolumeStatus()
      } catch (err) {
        setError(err.message)
      } finally {
        setSaving(false)
      }
    }
  }

  const runningPods = pods.filter(p => p.status === 'RUNNING')
  const startingPods = pods.filter(p => p.status === 'STARTING' || p.status === 'CREATED')

  if (!isOpen) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="runpod-config-modal runpod-config-modal--wide" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>RunPod Cloud</h2>
          <button className="modal-close" onClick={onClose}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="modal-tabs">
          <button
            className={`modal-tab ${activeTab === 'status' ? 'modal-tab--active' : ''}`}
            onClick={() => setActiveTab('status')}
          >
            Status
          </button>
          <button
            className={`modal-tab ${activeTab === 'pods' ? 'modal-tab--active' : ''}`}
            onClick={() => { setActiveTab('pods'); loadPods() }}
          >
            Pods ({runningPods.length})
          </button>
          <button
            className={`modal-tab ${activeTab === 'ssh' ? 'modal-tab--active' : ''}`}
            onClick={() => setActiveTab('ssh')}
          >
            SSH Config
          </button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="error-message">{error}</div>
          )}

          {/* Status Tab */}
          {activeTab === 'status' && (
            <div className="status-tab">
              {/* API Key Status */}
              <div className="status-section">
                <span className="label label--muted">API Connection</span>
                <div className="status-card">
                  {apiConfig.hasApiKey ? (
                    <div className="status-row status-row--success">
                      <span className="status-icon">&#10003;</span>
                      <span>API Key configured (from .env)</span>
                    </div>
                  ) : (
                    <div className="status-row status-row--warning">
                      <span className="status-icon">!</span>
                      <span>RUNPOD_API_KEY not found in .env</span>
                    </div>
                  )}

                  {apiConfig.volumeInfo && (
                    <div className="status-row">
                      <span className="status-label">Volume:</span>
                      <span>{apiConfig.volumeInfo.name} ({apiConfig.volumeInfo.size_gb}GB)</span>
                    </div>
                  )}

                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={handleTestApi}
                    disabled={testing || !apiConfig.hasApiKey}
                  >
                    {testing ? 'Testing...' : 'Test Connection'}
                  </button>
                </div>

                {testResult && (
                  <div className={`test-result ${testResult.success ? 'success' : 'error'}`}>
                    {testResult.success ? (
                      <>
                        <span className="status-icon">&#10003;</span>
                        <span>{testResult.message}</span>
                      </>
                    ) : (
                      <>
                        <span className="status-icon">&#10007;</span>
                        <span>{testResult.error || 'Connection failed'}</span>
                      </>
                    )}
                  </div>
                )}
              </div>

              {/* Active Pods Summary */}
              <div className="status-section">
                <span className="label label--muted">Active Pods</span>
                <div className="status-card">
                  {podsLoading ? (
                    <div className="loading-text">Loading...</div>
                  ) : runningPods.length > 0 ? (
                    <>
                      <div className="pods-summary">
                        <span className="pods-count">{runningPods.length}</span>
                        <span className="pods-label">running</span>
                        {startingPods.length > 0 && (
                          <span className="pods-starting">+{startingPods.length} starting</span>
                        )}
                      </div>
                      <div className="pods-cost">
                        Est. ${(runningPods.reduce((sum, p) => sum + (p.cost_per_hr || 0), 0)).toFixed(2)}/hr
                      </div>
                    </>
                  ) : (
                    <div className="no-pods-message">
                      No pods running. Launch pods in the Pods tab to start processing.
                    </div>
                  )}
                </div>
              </div>

              {/* Volume Status */}
              {volumeStatus && (
                <div className="status-section">
                  <span className="label label--muted">Volume Status</span>
                  <div className="status-card">
                    <div className="volume-counts">
                      <div className="volume-count">
                        <span className="count-value">{volumeStatus.input_files?.length || 0}</span>
                        <span className="count-label">Queued</span>
                      </div>
                      <div className="volume-count">
                        <span className="count-value">{volumeStatus.processing_files?.length || 0}</span>
                        <span className="count-label">Processing</span>
                      </div>
                      <div className="volume-count">
                        <span className="count-value">{volumeStatus.output_folders?.length || 0}</span>
                        <span className="count-label">Complete</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Pods Tab */}
          {activeTab === 'pods' && (
            <div className="pods-tab">
              {/* Launch Section */}
              <div className="launch-section">
                <span className="label label--accent">Launch Pods</span>
                <div className="launch-controls">
                  <div className="launch-row">
                    <div className="form-group form-group--inline">
                      <label>Count</label>
                      <select
                        value={launchConfig.count}
                        onChange={e => setLaunchConfig({ ...launchConfig, count: parseInt(e.target.value) })}
                      >
                        {[1, 2, 3, 4, 5].map(n => (
                          <option key={n} value={n}>{n} pod{n > 1 ? 's' : ''}</option>
                        ))}
                      </select>
                    </div>
                    <div className="form-group form-group--inline">
                      <label>GPU</label>
                      <select
                        value={launchConfig.gpuType}
                        onChange={e => setLaunchConfig({ ...launchConfig, gpuType: e.target.value })}
                      >
                        <option value="NVIDIA A40">A40 (~$0.39/hr)</option>
                        <option value="NVIDIA GeForce RTX 4090">RTX 4090 (~$0.44/hr)</option>
                        <option value="NVIDIA RTX A5000">RTX A5000 (~$0.29/hr)</option>
                      </select>
                    </div>
                    <button
                      className="btn btn-primary"
                      onClick={handleLaunchPods}
                      disabled={launching || !apiConfig.hasApiKey}
                    >
                      {launching ? 'Launching...' : 'Launch'}
                    </button>
                  </div>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={launchConfig.autoStartCoordinator}
                      onChange={e => setLaunchConfig({ ...launchConfig, autoStartCoordinator: e.target.checked })}
                    />
                    <span>Auto-start coordinator when pods are ready</span>
                  </label>
                </div>
              </div>

              {/* Running Pods */}
              <div className="pods-section">
                <div className="section-header">
                  <span className="label label--muted">Running Pods</span>
                  <div className="section-header-actions">
                    {runningPods.length > 0 && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={handleStartAllCoordinators}
                        title="Start coordinator on all pods"
                      >
                        Start All Coordinators
                      </button>
                    )}
                    {pods.length > 0 && (
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={handleTerminateAll}
                      >
                        Terminate All
                      </button>
                    )}
                  </div>
                </div>

                {podsLoading ? (
                  <div className="loading-text">Loading pods...</div>
                ) : pods.length === 0 ? (
                  <div className="empty-pods">
                    <p>No pods running</p>
                  </div>
                ) : (
                  <div className="pods-list">
                    {pods.map(pod => {
                      const coordStatus = coordinatorStatus[pod.pod_id] || {}
                      return (
                        <div key={pod.pod_id} className={`pod-card pod-card--${pod.status?.toLowerCase()}`}>
                          <div className="pod-info">
                            <span className="pod-name">{pod.name}</span>
                            <div className="pod-status-row">
                              <span className={`pod-status pod-status--${pod.status?.toLowerCase()}`}>
                                {pod.status}
                              </span>
                              {pod.status === 'RUNNING' && pod.ssh_host && (
                                <span className={`coordinator-status coordinator-status--${coordStatus.running ? 'running' : 'stopped'}`}>
                                  {coordStatus.checking ? (
                                    'Checking...'
                                  ) : coordStatus.running ? (
                                    <>● Coordinator</>
                                  ) : (
                                    <>○ Idle</>
                                  )}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="pod-details">
                            <span className="pod-gpu">{pod.gpu_type}</span>
                            {pod.cost_per_hr && (
                              <span className="pod-cost">${pod.cost_per_hr.toFixed(2)}/hr</span>
                            )}
                          </div>
                          <div className="pod-actions">
                            {pod.status === 'RUNNING' && pod.ssh_host && pod.ssh_port && (
                              coordStatus.running ? (
                                <button
                                  className="btn btn-secondary btn-sm"
                                  onClick={() => handleStopCoordinator(pod)}
                                  disabled={coordStatus.starting}
                                  title="Stop coordinator"
                                >
                                  {coordStatus.starting ? '...' : 'Stop'}
                                </button>
                              ) : (
                                <button
                                  className="btn btn-primary btn-sm"
                                  onClick={() => handleStartCoordinator(pod)}
                                  disabled={coordStatus.starting || coordStatus.checking}
                                  title="Start coordinator"
                                >
                                  {coordStatus.starting ? '...' : 'Start'}
                                </button>
                              )
                            )}
                            <button
                              className="btn btn-danger btn-sm"
                              onClick={() => handleTerminatePod(pod.pod_id)}
                            >
                              Terminate
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* SSH Config Tab */}
          {activeTab === 'ssh' && (
            <div className="ssh-tab">
              <p className="modal-description">
                Manual SSH configuration. Usually auto-configured when you connect to a pod.
              </p>

              <div className="form-group">
                <label>Host IP</label>
                <input
                  type="text"
                  value={sshConfig.host}
                  onChange={e => setSshConfig({ ...sshConfig, host: e.target.value })}
                  placeholder="69.30.85.10"
                />
              </div>

              <div className="form-group">
                <label>SSH Port</label>
                <input
                  type="number"
                  value={sshConfig.port}
                  onChange={e => setSshConfig({ ...sshConfig, port: e.target.value })}
                  placeholder="22017"
                />
              </div>

              <div className="form-group">
                <label>Pod ID <span className="optional">(optional)</span></label>
                <input
                  type="text"
                  value={sshConfig.pod_id}
                  onChange={e => setSshConfig({ ...sshConfig, pod_id: e.target.value })}
                  placeholder="k3daex483c5emk"
                />
              </div>

              <div className="form-group">
                <label>SSH Key Path <span className="optional">(optional)</span></label>
                <input
                  type="text"
                  value={sshConfig.ssh_key_path}
                  onChange={e => setSshConfig({ ...sshConfig, ssh_key_path: e.target.value })}
                  placeholder="~/.ssh/id_ed25519"
                />
                <span className="hint">Leave blank for default (~/.ssh/id_ed25519)</span>
              </div>

              <button
                className="btn btn-primary"
                onClick={handleSaveSshConfig}
                disabled={saving || !sshConfig.host || !sshConfig.port}
              >
                {saving ? 'Saving...' : 'Save SSH Config'}
              </button>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default RunPodConfigModal
