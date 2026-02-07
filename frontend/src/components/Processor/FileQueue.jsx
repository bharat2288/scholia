import FileCard from './FileCard'
import './FileQueue.css'

function FileQueue({ files, onTierChange, onProcess, onCancel, onRemove, runpodConfigured, onConfigureRunPod }) {
  return (
    <div className="file-queue">
      {files.map(file => (
        <FileCard
          key={file.id}
          file={file}
          onTierChange={onTierChange}
          onProcess={onProcess}
          onCancel={onCancel}
          onRemove={onRemove}
          runpodConfigured={runpodConfigured}
          onConfigureRunPod={onConfigureRunPod}
        />
      ))}
    </div>
  )
}

export default FileQueue
