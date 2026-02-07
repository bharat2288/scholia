import { useState, useCallback } from 'react'
import './DropZone.css'

function DropZone({ onFilesAdded }) {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = useCallback((e) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)

    const files = Array.from(e.dataTransfer.files).filter(
      file => file.type === 'application/pdf'
    )

    if (files.length > 0) {
      onFilesAdded(files)
    }
  }, [onFilesAdded])

  const handleFileSelect = useCallback((e) => {
    const files = Array.from(e.target.files)
    if (files.length > 0) {
      onFilesAdded(files)
    }
    // Reset input so same file can be selected again
    e.target.value = ''
  }, [onFilesAdded])

  return (
    <div
      className={`dropzone ${isDragging ? 'dropzone--active' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="dropzone-content">
        <div className="dropzone-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="12" y1="18" x2="12" y2="12" />
            <line x1="9" y1="15" x2="12" y2="12" />
            <line x1="15" y1="15" x2="12" y2="12" />
          </svg>
        </div>
        <p className="dropzone-text">
          Drop PDF files here
        </p>
        <p className="dropzone-subtext">
          or <label className="dropzone-browse">
            browse
            <input
              type="file"
              accept=".pdf"
              multiple
              onChange={handleFileSelect}
              hidden
            />
          </label>
        </p>
      </div>
    </div>
  )
}

export default DropZone
