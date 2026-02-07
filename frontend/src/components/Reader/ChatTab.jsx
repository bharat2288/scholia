/**
 * Chat Tab Component
 * ==================
 * AI-powered analysis panel for the Reader sidebar.
 *
 * Features:
 * - Model selection (single model or council mode)
 * - Preset analysis prompts with customization
 * - Context awareness (selection, section, full document)
 * - Streaming responses with progress indicators
 * - Conversation persistence
 * - Save analysis as notes
 */

import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import {
  usePresets,
  useModels,
  useSendQuery,
  useStreamQuery,
  useSaveAsNote,
  renderPrompt,
  formatCost
} from '../../hooks/useCouncil'
import PresetEditor from './PresetEditor'

// Provider display info
const PROVIDER_DISPLAY = {
  anthropic: { name: 'Claude', color: '#d4a574', icon: '🧠' },
  openai: { name: 'GPT-5', color: '#10a37f', icon: '⚡' },
  openrouter: { name: 'Gemini', color: '#4285f4', icon: '💎' },
}

/**
 * Chat Tab - AI analysis panel
 */
export default function ChatTab({
  sourceId,
  documentData,
  selection,  // { text, startOffset, endOffset } or null
  content     // Full document content
}) {
  // State
  const [mode, setMode] = useState('single') // 'single' | 'council'
  const [selectedModel, setSelectedModel] = useState('anthropic')
  const [selectedPresetId, setSelectedPresetId] = useState('summary')
  const [customQuery, setCustomQuery] = useState('')
  const [contextType, setContextType] = useState('selection') // 'selection' | 'section' | 'full'
  const [messages, setMessages] = useState([])
  const [showPresetEditor, setShowPresetEditor] = useState(false)

  const messagesEndRef = useRef(null)

  // API hooks
  const { data: presets = [], isLoading: presetsLoading } = usePresets()
  const { data: models = [], isLoading: modelsLoading } = useModels()
  const sendQuery = useSendQuery()
  const { isStreaming, events, result, error, startStream, stopStream } = useStreamQuery()
  const saveAsNote = useSaveAsNote()

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, events])

  // Update messages when streaming completes
  useEffect(() => {
    if (result && !isStreaming) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.synthesis || result.content,
        mode,
        perspectives: result.perspectives,
        usage: result.usage,
        timestamp: result.timestamp
      }])
    }
  }, [result, isStreaming])

  // Get selected preset
  const selectedPreset = useMemo(() => {
    return presets.find(p => p.id === selectedPresetId)
  }, [presets, selectedPresetId])

  // Get context text based on context type
  const getContextText = useCallback(() => {
    if (contextType === 'selection' && selection?.text) {
      return selection.text
    }
    if (contextType === 'full') {
      // Truncate to ~10k chars for full document
      const maxChars = 10000
      if (content.length > maxChars) {
        return content.slice(0, maxChars) + '\n\n[Truncated...]'
      }
      return content
    }
    // Default to selection if available, otherwise show hint
    return selection?.text || ''
  }, [contextType, selection, content])

  // Get context for sending
  const contextText = getContextText()

  // Check if we can send a query
  const canSend = useMemo(() => {
    if (isStreaming || sendQuery.isPending) return false
    if (!contextText) return false
    if (mode === 'single' && !selectedModel) return false
    return true
  }, [isStreaming, sendQuery.isPending, contextText, mode, selectedModel])

  // Handle sending query
  const handleSend = async () => {
    if (!canSend) return

    // Build query from preset or custom input
    let query = customQuery.trim()
    if (!query && selectedPreset) {
      query = renderPrompt(selectedPreset.prompt, {
        context: contextText,
        source_title: documentData?.title,
        author: documentData?.author
      })
    }
    if (!query) return

    // Add user message
    setMessages(prev => [...prev, {
      role: 'user',
      content: customQuery || selectedPreset?.name || 'Analysis',
      presetId: selectedPresetId,
      contextType,
      contextLength: contextText.length
    }])

    setCustomQuery('')

    if (mode === 'council') {
      // Use streaming for council mode
      startStream({
        context: contextText,
        query,
        sourceId,
        presetId: selectedPresetId,
        contextType
      })
    } else {
      // Use regular query for single mode
      try {
        const response = await sendQuery.mutateAsync({
          context: contextText,
          query,
          mode: 'single',
          model: selectedModel,
          context_type: contextType,
          source_id: sourceId,
          preset_id: selectedPresetId
        })

        setMessages(prev => [...prev, {
          role: 'assistant',
          content: response.content,
          mode: 'single',
          model: selectedModel,
          usage: response.usage,
          messageId: response.message_id,
          conversationId: response.conversation_id,
          timestamp: response.timestamp
        }])
      } catch (err) {
        setMessages(prev => [...prev, {
          role: 'error',
          content: err.message
        }])
      }
    }
  }

  // Handle save as note
  const handleSaveAsNote = async (messageId) => {
    try {
      await saveAsNote.mutateAsync({ messageId, sourceId })
      // Show success feedback (could add toast)
    } catch (err) {
      console.error('Failed to save as note:', err)
    }
  }

  // Available models for dropdown
  const availableModels = models.filter(m => m.available)

  return (
    <div className="flex flex-col h-full">
      {/* Mode and Model Selection */}
      <div className="space-y-3 mb-4 pb-4 border-b border-subtle">
        {/* Mode Toggle */}
        <div className="flex gap-2">
          <button
            onClick={() => setMode('single')}
            className={`
              flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-all
              ${mode === 'single'
                ? 'bg-camel/20 text-camel border border-camel/30'
                : 'bg-raised text-muted hover:text-secondary border border-transparent'
              }
            `}
          >
            Single Model
          </button>
          <button
            onClick={() => setMode('council')}
            className={`
              flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-all
              ${mode === 'council'
                ? 'bg-terra/20 text-terra border border-terra/30'
                : 'bg-raised text-muted hover:text-secondary border border-transparent'
              }
            `}
          >
            Council
          </button>
        </div>

        {/* Model Selection (single mode only) */}
        {mode === 'single' && (
          <div>
            <label className="label text-camel text-xs mb-1 block">Model</label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="w-full px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary focus:outline-none focus:border-camel"
            >
              {availableModels.length === 0 ? (
                <option value="">No models available</option>
              ) : (
                availableModels.map(m => (
                  <option key={m.id} value={m.id}>
                    {PROVIDER_DISPLAY[m.id]?.icon} {m.name}
                  </option>
                ))
              )}
            </select>
            {availableModels.length === 0 && (
              <p className="text-xs text-muted mt-1">Configure API keys to enable models</p>
            )}
          </div>
        )}

        {/* Council Mode Info */}
        {mode === 'council' && (
          <div className="text-xs text-muted bg-raised/50 p-2 rounded">
            <p className="font-medium text-secondary mb-1">Council Mode</p>
            <p>All 3 models deliberate, then Claude synthesizes.</p>
            <p className="text-terra mt-1">~$0.50 per query</p>
          </div>
        )}

        {/* Preset Selection */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="label text-camel text-xs">Analysis Type</label>
            <button
              onClick={() => setShowPresetEditor(true)}
              className="text-xs text-muted hover:text-camel transition-colors"
            >
              Edit Presets...
            </button>
          </div>
          <select
            value={selectedPresetId}
            onChange={(e) => setSelectedPresetId(e.target.value)}
            className="w-full px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary focus:outline-none focus:border-camel"
          >
            {presets.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {selectedPreset?.description && (
            <p className="text-xs text-muted mt-1">{selectedPreset.description}</p>
          )}
        </div>

        {/* Context Type */}
        <div>
          <label className="label text-camel text-xs mb-1 block">Context</label>
          <div className="flex gap-1">
            <button
              onClick={() => setContextType('selection')}
              disabled={!selection?.text}
              className={`
                flex-1 px-2 py-1.5 rounded text-xs transition-all
                ${contextType === 'selection'
                  ? 'bg-camel/20 text-camel'
                  : 'bg-raised text-muted hover:text-secondary'
                }
                ${!selection?.text ? 'opacity-50 cursor-not-allowed' : ''}
              `}
            >
              Selection
            </button>
            <button
              onClick={() => setContextType('full')}
              className={`
                flex-1 px-2 py-1.5 rounded text-xs transition-all
                ${contextType === 'full'
                  ? 'bg-camel/20 text-camel'
                  : 'bg-raised text-muted hover:text-secondary'
                }
              `}
            >
              Full Doc
            </button>
          </div>
          {contextType === 'selection' && selection?.text && (
            <p className="text-xs text-muted mt-1 truncate">
              "{selection.text.slice(0, 50)}..."
            </p>
          )}
          {contextType === 'selection' && !selection?.text && (
            <p className="text-xs text-muted mt-1">Select text in the document</p>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-auto space-y-3 mb-4">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center text-muted text-sm py-8">
            <p>Select text and choose an analysis type</p>
            <p className="text-xs mt-2">or ask a custom question below</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            onSaveAsNote={handleSaveAsNote}
            saveAsNote={saveAsNote}
          />
        ))}

        {/* Streaming Progress */}
        {isStreaming && (
          <StreamingProgress events={events} />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-subtle pt-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={customQuery}
            onChange={(e) => setCustomQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && canSend) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder={selectedPreset ? `Or ask a custom question...` : 'Ask about this document...'}
            className="flex-1 px-3 py-2 bg-base border border-subtle rounded-lg text-sm text-secondary placeholder-muted focus:outline-none focus:border-camel"
          />
          <button
            onClick={handleSend}
            disabled={!canSend}
            className={`
              px-4 py-2 rounded-lg text-sm font-medium transition-all
              ${canSend
                ? 'bg-camel/20 text-camel hover:bg-camel/30 border border-camel/30'
                : 'bg-raised text-muted cursor-not-allowed border border-transparent'
              }
            `}
          >
            {isStreaming || sendQuery.isPending ? (
              <span className="flex items-center gap-1">
                <Spinner className="w-4 h-4" />
              </span>
            ) : (
              'Send'
            )}
          </button>
        </div>
        {!contextText && (
          <p className="text-xs text-terra mt-1">Select text in the document first</p>
        )}
      </div>

      {/* Preset Editor Modal */}
      {showPresetEditor && (
        <PresetEditor
          onClose={() => setShowPresetEditor(false)}
          documentData={documentData}
        />
      )}
    </div>
  )
}


/**
 * Message Bubble Component
 */
function MessageBubble({ message, onSaveAsNote, saveAsNote }) {
  const [showPerspectives, setShowPerspectives] = useState(false)

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-camel/10 border border-camel/20 rounded-lg px-3 py-2">
          <p className="text-sm text-secondary">{message.content}</p>
          {message.contextLength && (
            <p className="text-xs text-muted mt-1">
              {message.contextType === 'full' ? 'Full document' : 'Selection'} ({message.contextLength} chars)
            </p>
          )}
        </div>
      </div>
    )
  }

  if (message.role === 'error') {
    return (
      <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
        <p className="text-sm text-red-400">{message.content}</p>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="bg-surface border border-subtle rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-raised/30 border-b border-subtle">
        <div className="flex items-center gap-2">
          {message.mode === 'council' ? (
            <span className="text-xs font-medium text-terra">Council Synthesis</span>
          ) : (
            <span className="text-xs font-medium text-secondary">
              {PROVIDER_DISPLAY[message.model]?.icon} {PROVIDER_DISPLAY[message.model]?.name || message.model}
            </span>
          )}
        </div>
        {message.usage && (
          <span className="text-xs text-muted">
            {formatCost(message.usage.totals?.cost_usd || message.usage.cost_usd)}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="px-3 py-2">
        <div className="text-sm text-secondary whitespace-pre-wrap">
          {message.content}
        </div>
      </div>

      {/* Council Perspectives Toggle */}
      {message.perspectives && message.perspectives.length > 0 && (
        <div className="border-t border-subtle">
          <button
            onClick={() => setShowPerspectives(!showPerspectives)}
            className="w-full px-3 py-2 text-xs text-muted hover:text-secondary flex items-center gap-2 transition-colors"
          >
            <span>{showPerspectives ? '▼' : '▶'}</span>
            <span>Individual Perspectives ({message.perspectives.filter(p => p.success).length}/3)</span>
          </button>

          {showPerspectives && (
            <div className="px-3 pb-3 space-y-2">
              {message.perspectives.map((p, i) => (
                <div key={i} className="bg-raised/50 rounded p-2">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-medium" style={{ color: PROVIDER_DISPLAY[p.provider]?.color }}>
                      {PROVIDER_DISPLAY[p.provider]?.icon} {PROVIDER_DISPLAY[p.provider]?.name}
                    </span>
                    {!p.success && (
                      <span className="text-xs text-red-400">(failed)</span>
                    )}
                  </div>
                  {p.success && p.content && (
                    <p className="text-xs text-muted line-clamp-4">{p.content}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-subtle">
        <button
          onClick={() => navigator.clipboard.writeText(message.content)}
          className="text-xs text-muted hover:text-secondary transition-colors"
        >
          Copy
        </button>
        {message.messageId && (
          <button
            onClick={() => onSaveAsNote(message.messageId)}
            disabled={saveAsNote.isPending}
            className="text-xs text-muted hover:text-camel transition-colors"
          >
            {saveAsNote.isPending ? 'Saving...' : 'Save as Note'}
          </button>
        )}
      </div>
    </div>
  )
}


/**
 * Streaming Progress Component
 */
function StreamingProgress({ events }) {
  // Track model states
  const modelStates = useMemo(() => {
    const states = {
      anthropic: { started: false, complete: false, content: null },
      openai: { started: false, complete: false, content: null },
      openrouter: { started: false, complete: false, content: null },
    }

    for (const event of events) {
      if (event.event === 'model_start') {
        states[event.data.provider] = { ...states[event.data.provider], started: true }
      }
      if (event.event === 'model_complete') {
        states[event.data.provider] = {
          ...states[event.data.provider],
          complete: true,
          content: event.data.content,
          success: event.data.success
        }
      }
    }

    return states
  }, [events])

  // Check synthesis state
  const synthesisStarted = events.some(e => e.event === 'synthesis_start')
  const synthesisComplete = events.find(e => e.event === 'synthesis_complete')

  return (
    <div className="bg-surface border border-subtle rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-raised/30 border-b border-subtle">
        <span className="text-xs font-medium text-terra">Council Deliberating...</span>
      </div>

      <div className="p-3 space-y-2">
        {/* Model Progress Indicators */}
        <div className="flex gap-2">
          {Object.entries(modelStates).map(([provider, state]) => (
            <div
              key={provider}
              className={`
                flex-1 px-2 py-1.5 rounded text-center text-xs transition-all
                ${state.complete
                  ? state.success
                    ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                    : 'bg-red-500/10 text-red-400 border border-red-500/20'
                  : state.started
                    ? 'bg-raised animate-pulse border border-subtle'
                    : 'bg-raised/50 text-muted border border-transparent'
                }
              `}
            >
              {PROVIDER_DISPLAY[provider]?.icon} {PROVIDER_DISPLAY[provider]?.name}
              {state.complete && (
                <span className="ml-1">{state.success ? '✓' : '✗'}</span>
              )}
            </div>
          ))}
        </div>

        {/* Synthesis Progress */}
        {synthesisStarted && !synthesisComplete && (
          <div className="flex items-center gap-2 text-xs text-muted">
            <Spinner className="w-3 h-3" />
            <span>Chairman synthesizing perspectives...</span>
          </div>
        )}
      </div>
    </div>
  )
}


/**
 * Spinner Component
 */
function Spinner({ className = "w-4 h-4" }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  )
}
