/**
 * Preset Editor Modal
 * ===================
 * Modal for managing analysis presets.
 *
 * Features:
 * - List all presets (system and user)
 * - Create new presets
 * - Edit user presets
 * - Duplicate system presets (to customize)
 * - Delete user presets
 * - Preview rendered prompts
 */

import { useState, useMemo } from 'react'
import {
  usePresets,
  useCreatePreset,
  useUpdatePreset,
  useDeletePreset,
  useDuplicatePreset,
  renderPrompt
} from '../../hooks/useCouncil'

/**
 * Preset Editor Modal
 */
export default function PresetEditor({ onClose, documentData }) {
  const { data: presets = [], isLoading } = usePresets()
  const createPreset = useCreatePreset()
  const updatePreset = useUpdatePreset()
  const deletePreset = useDeletePreset()
  const duplicatePreset = useDuplicatePreset()

  const [selectedPresetId, setSelectedPresetId] = useState(null)
  const [isCreating, setIsCreating] = useState(false)
  const [showPreview, setShowPreview] = useState(false)

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    prompt: '',
    model: 'default',
    max_tokens: 2500,
    show_as_quick_action: false
  })

  // Get selected preset
  const selectedPreset = useMemo(() => {
    return presets.find(p => p.id === selectedPresetId)
  }, [presets, selectedPresetId])

  // Separate system and user presets
  const systemPresets = presets.filter(p => p.is_system)
  const userPresets = presets.filter(p => !p.is_system)

  // Load preset into form
  const loadPresetToForm = (preset) => {
    setFormData({
      name: preset.name,
      description: preset.description || '',
      prompt: preset.prompt,
      model: preset.model,
      max_tokens: preset.max_tokens,
      show_as_quick_action: preset.show_as_quick_action || false
    })
  }

  // Handle selecting a preset
  const handleSelectPreset = (preset) => {
    setSelectedPresetId(preset.id)
    setIsCreating(false)
    loadPresetToForm(preset)
  }

  // Handle creating new
  const handleNewPreset = () => {
    setSelectedPresetId(null)
    setIsCreating(true)
    setFormData({
      name: 'New Analysis',
      description: '',
      prompt: `Analyze the following text:

{context}

Provide insights on the key points and arguments.`,
      model: 'default',
      max_tokens: 2500,
      show_as_quick_action: false
    })
  }

  // Handle duplicate
  const handleDuplicate = async (preset) => {
    try {
      const result = await duplicatePreset.mutateAsync({
        id: preset.id,
        name: `${preset.name} (Copy)`
      })
      // Select the new preset
      setSelectedPresetId(result.id)
      setIsCreating(false)
      loadPresetToForm(result)
    } catch (err) {
      console.error('Failed to duplicate preset:', err)
    }
  }

  // Handle save
  const handleSave = async () => {
    if (!formData.name.trim() || !formData.prompt.trim()) return

    try {
      if (isCreating) {
        const result = await createPreset.mutateAsync(formData)
        setSelectedPresetId(result.id)
        setIsCreating(false)
      } else if (selectedPresetId) {
        if (selectedPreset?.is_system) {
          // For system presets, only update show_as_quick_action
          await updatePreset.mutateAsync({
            id: selectedPresetId,
            show_as_quick_action: formData.show_as_quick_action
          })
        } else {
          // For user presets, update everything
          await updatePreset.mutateAsync({
            id: selectedPresetId,
            ...formData
          })
        }
      }
    } catch (err) {
      console.error('Failed to save preset:', err)
    }
  }

  // Handle delete
  const handleDelete = async () => {
    if (!selectedPresetId || selectedPreset?.is_system) return

    if (!confirm('Delete this preset? This cannot be undone.')) return

    try {
      await deletePreset.mutateAsync(selectedPresetId)
      setSelectedPresetId(null)
      setFormData({
        name: '',
        description: '',
        prompt: '',
        model: 'default',
        max_tokens: 2500,
        show_as_quick_action: false
      })
    } catch (err) {
      console.error('Failed to delete preset:', err)
    }
  }

  // Preview rendered prompt
  const previewPrompt = useMemo(() => {
    return renderPrompt(formData.prompt, {
      context: '[Your selected text will appear here]',
      source_title: documentData?.title || 'Document Title',
      author: documentData?.author || 'Author Name'
    })
  }, [formData.prompt, documentData])

  const isSaving = createPreset.isPending || updatePreset.isPending
  const isDeleting = deletePreset.isPending
  const isDuplicating = duplicatePreset.isPending
  // For system presets, can save if quick action toggle changed
  // For user presets, can save if name and prompt are filled
  const quickActionChanged = selectedPreset && formData.show_as_quick_action !== selectedPreset.show_as_quick_action
  const canSave = selectedPreset?.is_system
    ? quickActionChanged
    : (formData.name.trim() && formData.prompt.trim())
  const canDelete = selectedPresetId && !selectedPreset?.is_system && !isCreating

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-surface border border-subtle rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-subtle">
          <h2 className="font-display text-xl text-primary">Analysis Presets</h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-secondary transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 flex min-h-0">
          {/* Preset List */}
          <div className="w-64 border-r border-subtle flex flex-col">
            <div className="p-3 border-b border-subtle">
              <button
                onClick={handleNewPreset}
                className="w-full px-3 py-2 bg-camel/20 text-camel rounded-lg text-sm font-medium hover:bg-camel/30 transition-colors"
              >
                + New Preset
              </button>
            </div>

            <div className="flex-1 overflow-auto">
              {/* System Presets */}
              {systemPresets.length > 0 && (
                <div className="p-2">
                  <p className="label text-muted text-xs px-2 mb-1">System Presets</p>
                  {systemPresets.map(p => (
                    <PresetListItem
                      key={p.id}
                      preset={p}
                      isSelected={p.id === selectedPresetId}
                      onSelect={() => handleSelectPreset(p)}
                      onDuplicate={() => handleDuplicate(p)}
                      isDuplicating={isDuplicating}
                    />
                  ))}
                </div>
              )}

              {/* User Presets */}
              {userPresets.length > 0 && (
                <div className="p-2 border-t border-subtle">
                  <p className="label text-muted text-xs px-2 mb-1">Your Presets</p>
                  {userPresets.map(p => (
                    <PresetListItem
                      key={p.id}
                      preset={p}
                      isSelected={p.id === selectedPresetId}
                      onSelect={() => handleSelectPreset(p)}
                      onDuplicate={() => handleDuplicate(p)}
                      isDuplicating={isDuplicating}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Edit Form */}
          <div className="flex-1 flex flex-col min-w-0">
            {(selectedPresetId || isCreating) ? (
              <>
                <div className="flex-1 overflow-auto p-6 space-y-4">
                  {/* System preset notice */}
                  {selectedPreset?.is_system && (
                    <div className="bg-raised/50 border border-subtle rounded-lg p-3 text-sm">
                      <p className="text-secondary">
                        This is a system preset and cannot be edited.
                      </p>
                      <button
                        onClick={() => handleDuplicate(selectedPreset)}
                        disabled={isDuplicating}
                        className="mt-2 text-camel hover:text-camel/80 text-sm"
                      >
                        {isDuplicating ? 'Duplicating...' : 'Duplicate to customize →'}
                      </button>
                    </div>
                  )}

                  {/* Name */}
                  <div>
                    <label className="label text-camel text-xs mb-1 block">Name</label>
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      disabled={selectedPreset?.is_system}
                      className="w-full px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary focus:outline-none focus:border-camel disabled:opacity-50"
                      placeholder="Analysis name"
                    />
                  </div>

                  {/* Description */}
                  <div>
                    <label className="label text-camel text-xs mb-1 block">Description</label>
                    <input
                      type="text"
                      value={formData.description}
                      onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                      disabled={selectedPreset?.is_system}
                      className="w-full px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary focus:outline-none focus:border-camel disabled:opacity-50"
                      placeholder="Brief description of what this analysis does"
                    />
                  </div>

                  {/* Prompt */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="label text-camel text-xs">Prompt Template</label>
                      <button
                        onClick={() => setShowPreview(!showPreview)}
                        className="text-xs text-muted hover:text-secondary transition-colors"
                      >
                        {showPreview ? 'Hide Preview' : 'Show Preview'}
                      </button>
                    </div>
                    <textarea
                      value={formData.prompt}
                      onChange={(e) => setFormData({ ...formData, prompt: e.target.value })}
                      disabled={selectedPreset?.is_system}
                      rows={8}
                      className="w-full px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary font-mono focus:outline-none focus:border-camel disabled:opacity-50 resize-none"
                      placeholder="Your analysis prompt..."
                    />
                    <p className="text-xs text-muted mt-1">
                      Variables: <code className="bg-raised px-1 rounded">{'{context}'}</code>,{' '}
                      <code className="bg-raised px-1 rounded">{'{source_title}'}</code>,{' '}
                      <code className="bg-raised px-1 rounded">{'{author}'}</code>
                    </p>
                  </div>

                  {/* Preview */}
                  {showPreview && (
                    <div className="bg-raised/50 border border-subtle rounded-lg p-3">
                      <p className="label text-muted text-xs mb-2">Rendered Preview</p>
                      <pre className="text-xs text-secondary whitespace-pre-wrap font-mono">
                        {previewPrompt}
                      </pre>
                    </div>
                  )}

                  {/* Max Tokens */}
                  <div>
                    <label className="label text-camel text-xs mb-1 block">Max Response Length</label>
                    <input
                      type="number"
                      value={formData.max_tokens}
                      onChange={(e) => setFormData({ ...formData, max_tokens: parseInt(e.target.value) || 2500 })}
                      disabled={selectedPreset?.is_system}
                      min={100}
                      max={8000}
                      className="w-32 px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary focus:outline-none focus:border-camel disabled:opacity-50"
                    />
                    <span className="text-xs text-muted ml-2">tokens (100-8000)</span>
                  </div>

                  {/* Quick Action Toggle - editable even for system presets */}
                  <div className="flex items-center justify-between py-3 px-4 bg-raised/30 rounded-lg">
                    <div>
                      <label className="text-sm text-secondary font-medium">Show as Quick Action</label>
                      <p className="text-xs text-muted mt-0.5">
                        Display as a one-click button in the chat interface
                      </p>
                    </div>
                    <button
                      onClick={() => setFormData({ ...formData, show_as_quick_action: !formData.show_as_quick_action })}
                      className={`
                        relative w-10 h-5 rounded-full transition-all duration-200 cursor-pointer
                        ${formData.show_as_quick_action
                          ? 'bg-camel shadow-[0_0_8px_rgba(212,165,116,0.4)]'
                          : 'bg-elevated'
                        }
                      `}
                    >
                      <span
                        className={`
                          absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-md
                          transition-transform duration-200
                          ${formData.show_as_quick_action ? 'translate-x-5' : 'translate-x-0'}
                        `}
                      />
                    </button>
                  </div>
                </div>

                {/* Form Actions */}
                <div className="flex items-center justify-between px-6 py-4 border-t border-subtle bg-raised/30">
                  <div>
                    {canDelete && (
                      <button
                        onClick={handleDelete}
                        disabled={isDeleting}
                        className="px-3 py-2 text-sm text-red-400 hover:text-red-300 transition-colors"
                      >
                        {isDeleting ? 'Deleting...' : 'Delete'}
                      </button>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={onClose}
                      className="px-4 py-2 bg-raised text-secondary rounded-lg text-sm hover:text-primary transition-colors"
                    >
                      Cancel
                    </button>
                    {(canSave || isCreating || !selectedPreset?.is_system) && (
                      <button
                        onClick={handleSave}
                        disabled={!canSave || isSaving}
                        className="px-4 py-2 bg-camel/20 text-camel rounded-lg text-sm font-medium hover:bg-camel/30 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {isSaving ? 'Saving...' : isCreating ? 'Create' : selectedPreset?.is_system ? 'Save Preference' : 'Save Changes'}
                      </button>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted text-sm">
                Select a preset to edit, or create a new one
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}


/**
 * Preset List Item
 */
function PresetListItem({ preset, isSelected, onSelect, onDuplicate, isDuplicating }) {
  return (
    <button
      onClick={onSelect}
      className={`
        w-full text-left px-3 py-2 rounded-lg text-sm transition-all group
        ${isSelected
          ? 'bg-raised border-l-2 border-camel text-primary'
          : 'text-secondary hover:bg-raised/50 border-l-2 border-transparent'
        }
      `}
    >
      <div className="flex items-center justify-between">
        <span className="truncate">{preset.name}</span>
        <div className="flex items-center gap-1">
          {preset.is_system && (
            <span className="text-xs text-muted" title="System preset">🔒</span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onDuplicate() }}
            disabled={isDuplicating}
            className="opacity-0 group-hover:opacity-100 text-xs text-muted hover:text-secondary transition-all p-1"
            title="Duplicate"
          >
            📋
          </button>
        </div>
      </div>
    </button>
  )
}
