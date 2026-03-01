import { useState } from 'react'
import { useSourceGluonStats } from '../../hooks/useApi'

/**
 * Delete Source Modal
 * ===================
 * Shows gluon counts and asks user whether to keep or discard annotations.
 * For non-document sources (web, thread, media), also asks about local file deletion.
 */
export default function DeleteSourceModal({ sourceId, sourceTitle, onConfirm, onCancel }) {
  const { data: stats, isLoading } = useSourceGluonStats(sourceId)
  const [deleteLocalFiles, setDeleteLocalFiles] = useState(false)

  const hasAnnotations = stats && (stats.highlight_count > 0 || stats.note_count > 0)
  const hasLocalFolder = stats?.has_local_folder

  // Handler that passes both keepGluons and deleteLocalFiles
  const handleConfirm = (keepGluons) => {
    onConfirm(keepGluons, deleteLocalFiles)
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-surface border border-raised rounded-xl p-6 max-w-md w-full shadow-2xl">
        <h2 className="font-display text-2xl text-primary mb-4">Delete Source</h2>

        <p className="text-secondary mb-4 line-clamp-2">
          {sourceTitle}
        </p>

        {isLoading ? (
          <p className="text-muted mb-6">Checking annotations...</p>
        ) : hasAnnotations ? (
          <div className="bg-raised rounded-lg p-4 mb-4">
            <p className="text-secondary mb-2">
              This source has annotations:
            </p>
            <ul className="text-sm text-tertiary space-y-1">
              {stats.highlight_count > 0 && (
                <li className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-yellow-400/30"></span>
                  {stats.highlight_count} highlight{stats.highlight_count !== 1 ? 's' : ''}
                </li>
              )}
              {stats.note_count > 0 && (
                <li className="flex items-center gap-2">
                  <span className="w-3 h-3 rounded bg-blue-400/30"></span>
                  {stats.note_count} note{stats.note_count !== 1 ? 's' : ''}
                </li>
              )}
            </ul>
          </div>
        ) : (
          <p className="text-muted mb-4">
            This source has no annotations.
          </p>
        )}

        {/* Local files deletion option — shown when source has a local folder */}
        {hasLocalFolder && (
          <label className="flex items-start gap-3 p-3 bg-raised rounded-lg mb-4 cursor-pointer hover:bg-elevated transition-colors">
            <input
              type="checkbox"
              checked={deleteLocalFiles}
              onChange={(e) => setDeleteLocalFiles(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-subtle bg-base text-red-500 focus:ring-red-500 focus:ring-offset-0"
            />
            <div className="flex-1">
              <span className="text-secondary text-sm font-medium">
                Also delete local files
              </span>
              <p className="text-muted text-xs mt-1">
                Remove the folder containing extracted text and any downloaded media
              </p>
              {stats.local_folder_path && (
                <p className="text-muted text-xs mt-1 font-mono truncate" title={stats.local_folder_path}>
                  {stats.local_folder_path.split(/[/\\]/).slice(-2).join('/')}
                </p>
              )}
            </div>
          </label>
        )}

        <div className="flex flex-col gap-2">
          {hasAnnotations ? (
            <>
              <button
                onClick={() => handleConfirm(false)}
                className="w-full py-2.5 px-4 bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded-lg transition-colors text-sm font-medium"
              >
                Delete source and all annotations
                {deleteLocalFiles && ' + local files'}
              </button>
              <button
                onClick={() => handleConfirm(true)}
                className="w-full py-2.5 px-4 bg-raised hover:bg-elevated text-secondary rounded-lg transition-colors text-sm"
              >
                Delete source, keep annotations as orphans
                {deleteLocalFiles && ' + delete local files'}
              </button>
            </>
          ) : (
            <button
              onClick={() => handleConfirm(false)}
              className="w-full py-2.5 px-4 bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded-lg transition-colors text-sm font-medium"
            >
              Delete source{deleteLocalFiles && ' + local files'}
            </button>
          )}
          <button
            onClick={onCancel}
            className="w-full py-2.5 px-4 text-muted hover:text-secondary rounded-lg transition-colors text-sm"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
