import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import './FileCard.css'

const TIERS = [
  { id: 'quick', label: 'Quick', desc: 'Text-only (~2s)' },
  { id: 'dots-ocr', label: 'dots-ocr', desc: 'Scanned, equations' },
  { id: 'runpod', label: 'RunPod', desc: 'Cloud GPU (batch)', isRemote: true }
]

function FileCard({ file, onTierChange, onProcess, onCancel, onRemove, onEpubOverride, runpodConfigured, onConfigureRunPod }) {
  const { id, name, status, assessment, selectedTier, result, error, progress, startTime, queuePosition, fileType } = file
  const isEpub = fileType === 'epub'
  const [elapsed, setElapsed] = useState(0)
  const [showAnnotationWarning, setShowAnnotationWarning] = useState(false)

  // Timer for elapsed time during processing
  useEffect(() => {
    let interval
    if (status === 'processing' && startTime) {
      interval = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startTime) / 1000))
      }, 1000)
    } else {
      setElapsed(0)
    }
    return () => clearInterval(interval)
  }, [status, startTime])

  // Format time estimate
  const formatTime = (seconds) => {
    if (seconds < 60) return `~${Math.round(seconds)}s`
    return `~${Math.round(seconds / 60)}m`
  }

  // Format elapsed time (mm:ss)
  const formatElapsed = (seconds) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Get estimated time for selected tier
  const estimatedTime = assessment?.time_estimates?.[selectedTier] || 0

  return (
    <div className={`file-card file-card--${status}`}>
      <div className="file-card-header">
        <div className="file-info">
          <span className="file-name">{name}</span>
          {assessment && (
            <span className="file-pages">
              {isEpub
                ? `${assessment.chapter_count || 0} chapter${assessment.chapter_count !== 1 ? 's' : ''}`
                : `${assessment.page_count} page${assessment.page_count !== 1 ? 's' : ''}`
              }
            </span>
          )}
        </div>

        <button
          className="file-remove"
          onClick={() => onRemove(id)}
          aria-label="Remove file"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>

      {status === 'assessing' && (
        <div className="file-card-body">
          <div className="status-message">
            <span className="spinner"></span>
            Analyzing document...
          </div>
        </div>
      )}

      {status === 'ready' && assessment && isEpub && (
        <div className="file-card-body">
          {/* EPUB metadata preview */}
          <div className="epub-metadata">
            <span className="label label--accent">EPUB</span>
            <div className="epub-fields">
              <div className="epub-field">
                <span className="epub-field-label">Title</span>
                <input
                  className="epub-field-input"
                  defaultValue={assessment.metadata?.title || ''}
                  onChange={(e) => onEpubOverride?.(id, 'title', e.target.value)}
                />
              </div>
              <div className="epub-field">
                <span className="epub-field-label">Author</span>
                <input
                  className="epub-field-input"
                  defaultValue={assessment.metadata?.author || ''}
                  onChange={(e) => onEpubOverride?.(id, 'author', e.target.value)}
                />
              </div>
              <div className="epub-field-row">
                <div className="epub-field">
                  <span className="epub-field-label">Year</span>
                  <input
                    className="epub-field-input"
                    type="number"
                    defaultValue={assessment.metadata?.year || ''}
                    onChange={(e) => onEpubOverride?.(id, 'year', e.target.value)}
                  />
                </div>
                <div className="epub-stats">
                  <span>{assessment.chapter_count} chapter{assessment.chapter_count !== 1 ? 's' : ''}</span>
                  <span className="epub-stats-sep">&middot;</span>
                  <span>{assessment.image_count} image{assessment.image_count !== 1 ? 's' : ''}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Existing extraction warning */}
          {assessment.existing_extractions?.match_type && (
            <div className={`existing-warning existing-warning--${assessment.existing_extractions.match_type}`}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" /><polyline points="16 10 10 16 8 14" />
              </svg>
              <span>
                {assessment.existing_extractions.match_type === 'exact'
                  ? <>Exact duplicate: <strong>{assessment.existing_extractions.matched_title}</strong></>
                  : assessment.existing_extractions.match_type === 'fuzzy'
                  ? <>Similar document: <strong>{assessment.existing_extractions.matched_title}</strong></>
                  : <>Already imported</>
                }
              </span>
            </div>
          )}

          <button
            className="btn-primary process-btn"
            onClick={() => onProcess(id)}
          >
            Import EPUB
          </button>
        </div>
      )}

      {status === 'ready' && assessment && !isEpub && (
        <div className="file-card-body">
          {/* Existing extraction warning - shows match type */}
          {assessment.existing_extractions?.match_type && (
            <div className={`existing-warning existing-warning--${assessment.existing_extractions.match_type}`}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                {assessment.existing_extractions.match_type === 'exact' ? (
                  // Checkmark for exact match
                  <><circle cx="12" cy="12" r="10" /><polyline points="16 10 10 16 8 14" /></>
                ) : (
                  // Warning triangle for fuzzy/folder match
                  <><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>
                )}
              </svg>
              <span>
                {assessment.existing_extractions.match_type === 'exact' && (
                  <>Exact duplicate found: <strong>{assessment.existing_extractions.matched_title}</strong></>
                )}
                {assessment.existing_extractions.match_type === 'fuzzy' && (
                  <>Similar document found: <strong>{assessment.existing_extractions.matched_title}</strong></>
                )}
                {assessment.existing_extractions.match_type === 'folder' && assessment.existing_extractions.existing_methods?.length > 0 && (
                  <>Already processed with {assessment.existing_extractions.existing_methods.join(' & ')}</>
                )}
              </span>
            </div>
          )}

          <div className="tier-selection">
            <span className="label label--muted">Extraction Method</span>
            <div className="tier-options">
              {TIERS.map(tier => {
                const alreadyExtracted = assessment.existing_extractions?.existing_methods?.includes(tier.id)
                const isRunPod = tier.isRemote

                // Handle RunPod tier specially
                if (isRunPod) {
                  return (
                    <button
                      key={tier.id}
                      className={`tier-btn tier-btn--remote ${selectedTier === tier.id ? 'tier-btn--selected' : ''} ${!runpodConfigured ? 'tier-btn--unconfigured' : ''}`}
                      onClick={() => {
                        if (!runpodConfigured) {
                          onConfigureRunPod?.()
                        } else {
                          onTierChange(id, tier.id)
                        }
                      }}
                    >
                      <span className="tier-label">{tier.label}</span>
                      <span className="tier-time">
                        {runpodConfigured ? 'Remote' : 'Configure'}
                      </span>
                      <span className="tier-badge tier-badge--remote">Cloud</span>
                    </button>
                  )
                }

                return (
                  <button
                    key={tier.id}
                    className={`tier-btn ${selectedTier === tier.id ? 'tier-btn--selected' : ''} ${assessment.recommendation === tier.id ? 'tier-btn--recommended' : ''} ${alreadyExtracted ? 'tier-btn--exists' : ''}`}
                    onClick={() => onTierChange(id, tier.id)}
                  >
                    <span className="tier-label">{tier.label}</span>
                    <span className="tier-time">
                      {formatTime(assessment.time_estimates[tier.id])}
                    </span>
                    {alreadyExtracted ? (
                      <span className="tier-badge tier-badge--exists">Exists</span>
                    ) : assessment.recommendation === tier.id ? (
                      <span className="tier-badge">Recommended</span>
                    ) : null}
                  </button>
                )
              })}
            </div>
          </div>

          {assessment.reason && (
            <p className="assessment-reason">{assessment.reason}</p>
          )}

          {/* Annotation warning - shown when doc has highlights/notes */}
          {assessment.existing_extractions?.annotation_count > 0 && (
            <div className="annotation-warning">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              <span>
                {assessment.existing_extractions.annotation_count} annotation{assessment.existing_extractions.annotation_count !== 1 ? 's' : ''} may break if text changes
              </span>
            </div>
          )}

          {/* Annotation confirmation dialog */}
          {showAnnotationWarning && (
            <div className="annotation-confirm">
              <p className="annotation-confirm-text">
                This document has <strong>{assessment.existing_extractions?.annotation_count}</strong> highlight{assessment.existing_extractions?.annotation_count !== 1 ? 's' : ''}/note{assessment.existing_extractions?.annotation_count !== 1 ? 's' : ''}.
                Reprocessing may break their positions if the extracted text changes.
              </p>
              <div className="annotation-confirm-actions">
                <button
                  className="btn-danger"
                  onClick={() => {
                    setShowAnnotationWarning(false)
                    onProcess(id)
                  }}
                >
                  Reprocess Anyway
                </button>
                <button
                  className="btn-secondary"
                  onClick={() => setShowAnnotationWarning(false)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {!showAnnotationWarning && (
            <button
              className="btn-primary process-btn"
              onClick={() => {
                // Show warning if doc has annotations
                if (assessment.existing_extractions?.annotation_count > 0) {
                  setShowAnnotationWarning(true)
                } else {
                  onProcess(id)
                }
              }}
            >
              {assessment.existing_extractions?.existing_methods?.includes(selectedTier)
                ? 'Reprocess'
                : 'Process'
              }
            </button>
          )}
        </div>
      )}

      {(status === 'queued' || status === 'starting') && (
        <div className="file-card-body">
          <div className="queued-status">
            <div className="queue-info">
              <span className="queue-icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </span>
              <span className="queue-text">
                {queuePosition === 1
                  ? 'Next in GPU queue'
                  : queuePosition > 1
                  ? `Position ${queuePosition} in GPU queue`
                  : 'Queued for processing...'
                }
              </span>
            </div>
            <p className="queue-note">
              Jobs run one at a time to prevent GPU memory issues
            </p>
            <button
              className="btn-cancel"
              onClick={() => onCancel(id)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {status === 'processing' && (
        <div className="file-card-body">
          <div className="processing-status">
            <div className="progress-info">
              <span className="spinner"></span>
              <span className="progress-text">
                {progress?.stage === 'loading model'
                  ? 'Loading model (first time only)...'
                  : progress?.stage === 'extracting'
                  ? `Processing with ${selectedTier}...`
                  : progress?.stage === 'formatting'
                  ? 'Formatting output...'
                  : `Processing with ${selectedTier}...`
                }
              </span>
            </div>

            <div className="progress-bar-container">
              {/* percent = -1 means indeterminate (extraction in progress) */}
              {progress?.percent === -1 ? (
                <div className="progress-bar-indeterminate" />
              ) : (
                <div
                  className="progress-bar-fill"
                  style={{ width: `${progress?.percent || 0}%` }}
                />
              )}
            </div>

            <div className="progress-footer">
              <div className="progress-times">
                <span className="progress-elapsed">{formatElapsed(elapsed)}</span>
                {estimatedTime > 0 && (
                  <span className="progress-estimate">/ {formatTime(estimatedTime)}</span>
                )}
              </div>
              <span className="progress-percent">
                {progress?.percent === -1 ? '...' : `${progress?.percent || 0}%`}
              </span>
              <button
                className="btn-cancel"
                onClick={() => onCancel(id)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {status === 'complete' && result && (
        <div className="file-card-body file-card-body--success">
          <div className="success-icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          </div>
          <div className="success-info">
            <span className="success-text">Complete</span>
            <span className="output-filename">{result.folder_name}</span>
          </div>
          <Link to="/" className="btn-library">
            View in Library
          </Link>
        </div>
      )}

      {status === 'error' && (
        <div className="file-card-body file-card-body--error">
          <div className="error-message">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            {error || 'An error occurred'}
          </div>
        </div>
      )}
    </div>
  )
}

export default FileCard
