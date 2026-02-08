/**
 * Unified Chat Tab Component
 * ==========================
 * Single pane for all AI interactions - single model chat OR council deliberation.
 *
 * Design System Applied:
 * - Labels: 12px/600/0.06em/uppercase
 * - Elevation: Base→Surface→Raised→Elevated
 * - Accent: Camel limited to 2-3 uses (active states, primary actions)
 * - Energy: Gradients, shadows, glows on interactive elements
 * - Density: Tight for controls, standard for messages
 */

import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useChatModels,
  useSendChatMessage,
  getDefaultModel,
  formatCost
} from '../../hooks/useChat'
import {
  usePresets,
  useStreamQuery,
  useSaveAsNote,
  useConversations,
  useConversation,
  useDeleteConversation,
  renderPrompt
} from '../../hooks/useCouncil'
import { useCreateNote } from '../../hooks/useApi'
import { API_BASE } from '../../config'
import useReaderStore from '../../stores/useReaderStore'
import PresetEditor from './PresetEditor'

// Provider display info for Council
const PROVIDER_DISPLAY = {
  anthropic: { name: 'Claude', color: '#d4a574' },
  openai: { name: 'GPT', color: '#10a37f' },
  openrouter: { name: 'Gemini', color: '#4285f4' },
}

// Human-readable nouns for source types (used in prompt {source_type} variable)
const SOURCE_TYPE_NOUNS = {
  document: 'this document',
  web: 'this article',
  thread: 'this thread',
  media: 'this transcript',
}

// Analyze mode configurations
const ANALYZE_MODES = [
  {
    id: 'comprehensive',
    name: 'Comprehensive',
    description: 'Full theoretical analysis pipeline',
    requiresInput: false,
  },
  {
    id: 'reverse',
    name: 'Reverse',
    description: 'Assumption excavation from claims backward',
    requiresInput: false,
  },
  {
    id: 'directed',
    name: 'Directed',
    description: 'Analysis shaped by your deployment context',
    requiresInput: true,
  },
]

// Reverse-mode Analyze prompt (separate from the comprehensive prompt)
const ANALYZE_REVERSE_PROMPT = `You are analyzing {source_type}. Your goal is to work BACKWARD from the text's conclusions to excavate its hidden foundations.

## Your Task

### 1. Conclusion Identification
What are the text's landing points — its final claims, recommendations, or implications? List 3-5 key conclusions.

### 2. Dependency Tracing
For each conclusion, trace backward:
- **Conclusion**: [State it]
- **Depends on**: [What intermediate claim must be true for this to hold?]
- **Which depends on**: [What prior assumption or evidence supports THAT?]
- **Which depends on**: [Continue until you hit bedrock — an axiom, value, or empirical claim taken as given]

### 3. Assumption Excavation
What did you find at the bottom of each chain? Categorize:
- **Empirical assumptions**: Claims about how the world works (testable)
- **Normative assumptions**: Claims about what matters or what's good (value-laden)
- **Methodological assumptions**: Claims about how to know things (epistemological)
- **Definitional assumptions**: Terms used in specific ways that smuggle in commitments

### 4. Vulnerability Mapping
Which assumptions are:
- **Most load-bearing**: If wrong, the most conclusions collapse
- **Most contestable**: Reasonable people would disagree
- **Most hidden**: The text doesn't acknowledge or defend them
- **Most interesting**: Challenging them would open productive new lines of inquiry

## Guidelines
- Work backward, not forward — start from conclusions and dig
- The most interesting findings are assumptions the author doesn't know they're making
- Distinguish between assumptions the text argues for and assumptions it smuggles in
- An assumption being hidden doesn't make it wrong — note when hidden assumptions are actually well-supported

---

TEXT TO ANALYZE:

{context}`

// Directed-mode preamble (wraps the comprehensive prompt)
const ANALYZE_DIRECTED_PREAMBLE = `DEPLOYMENT CONTEXT: The reader intends to use insights from this text in the following context: {deployment_context}

Given this deployment context, weight your theoretical analysis toward frameworks, tensions, and questions most relevant to this application. Still be comprehensive, but prioritize what's actionable for this context.

`

/**
 * Simple markdown renderer for chat messages
 * Handles: bold, italic, code, code blocks, lists, headers
 */
function renderMarkdown(text) {
  if (!text) return null

  const lines = text.split('\n')
  const elements = []
  let inCodeBlock = false
  let codeBlockContent = []
  let codeBlockLang = ''

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    // Code block start/end
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        // End code block
        elements.push(
          <pre key={`code-${i}`} className="bg-base rounded p-2 my-2 overflow-x-auto text-[12px] font-mono text-secondary">
            <code>{codeBlockContent.join('\n')}</code>
          </pre>
        )
        codeBlockContent = []
        inCodeBlock = false
      } else {
        // Start code block
        inCodeBlock = true
        codeBlockLang = line.slice(3).trim()
      }
      continue
    }

    if (inCodeBlock) {
      codeBlockContent.push(line)
      continue
    }

    // Headers
    if (line.startsWith('### ')) {
      elements.push(<h4 key={i} className="font-semibold text-primary mt-3 mb-1">{line.slice(4)}</h4>)
      continue
    }
    if (line.startsWith('## ')) {
      elements.push(<h3 key={i} className="font-semibold text-primary mt-3 mb-1">{line.slice(3)}</h3>)
      continue
    }
    if (line.startsWith('# ')) {
      elements.push(<h2 key={i} className="font-bold text-primary mt-3 mb-1">{line.slice(2)}</h2>)
      continue
    }

    // List items
    if (line.match(/^[\-\*]\s/)) {
      elements.push(
        <div key={i} className="flex gap-2 my-0.5">
          <span className="text-muted">•</span>
          <span>{renderInlineMarkdown(line.slice(2))}</span>
        </div>
      )
      continue
    }

    // Numbered list items
    if (line.match(/^\d+\.\s/)) {
      const num = line.match(/^(\d+)\./)[1]
      elements.push(
        <div key={i} className="flex gap-2 my-0.5">
          <span className="text-muted w-4">{num}.</span>
          <span>{renderInlineMarkdown(line.replace(/^\d+\.\s/, ''))}</span>
        </div>
      )
      continue
    }

    // Empty line
    if (line.trim() === '') {
      elements.push(<div key={i} className="h-2" />)
      continue
    }

    // Regular paragraph
    elements.push(<p key={i} className="my-0.5">{renderInlineMarkdown(line)}</p>)
  }

  return elements
}

/**
 * Render inline markdown (bold, italic, code)
 */
function renderInlineMarkdown(text) {
  if (!text) return text

  // Split by inline code first
  const parts = text.split(/(`[^`]+`)/)

  return parts.map((part, i) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={i} className="bg-base px-1 py-0.5 rounded text-[12px] font-mono text-camel">
          {part.slice(1, -1)}
        </code>
      )
    }

    // Handle bold and italic
    let result = part
    const elements = []
    let lastIndex = 0

    // Bold: **text** or __text__
    const boldRegex = /(\*\*|__)(.*?)\1/g
    let match

    while ((match = boldRegex.exec(part)) !== null) {
      if (match.index > lastIndex) {
        elements.push(renderItalic(part.slice(lastIndex, match.index), `pre-${i}-${lastIndex}`))
      }
      elements.push(<strong key={`bold-${i}-${match.index}`}>{match[2]}</strong>)
      lastIndex = match.index + match[0].length
    }

    if (elements.length > 0) {
      if (lastIndex < part.length) {
        elements.push(renderItalic(part.slice(lastIndex), `post-${i}-${lastIndex}`))
      }
      return <span key={i}>{elements}</span>
    }

    return renderItalic(part, i)
  })
}

/**
 * Render italic text
 */
function renderItalic(text, key) {
  if (!text) return text

  const italicRegex = /(\*|_)(.*?)\1/g
  const parts = []
  let lastIndex = 0
  let match

  while ((match = italicRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    parts.push(<em key={`italic-${key}-${match.index}`}>{match[2]}</em>)
    lastIndex = match.index + match[0].length
  }

  if (parts.length > 0) {
    if (lastIndex < text.length) {
      parts.push(text.slice(lastIndex))
    }
    return <span key={key}>{parts}</span>
  }

  return text
}

/**
 * Unified Chat Tab
 */
export default function SimpleChatTab({
  sourceId,
  documentData,
  selection,
  content,
  isExpanded = false,
  setIsExpanded,
  initialConversationId = null,
}) {
  // State
  const [messages, setMessages] = useState([])
  const [inputText, setInputText] = useState('')
  const [selectedModelId, setSelectedModelId] = useState(null)
  const [maxTokens, setMaxTokens] = useState(12288)
  const [selectedPresetId, setSelectedPresetId] = useState(null)
  const [contexts, setContexts] = useState([]) // Array of { id, text, type: 'selection'|'full' }
  const [useFullDocument, setUseFullDocument] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const [gluonId, setGluonId] = useState(null)
  const [showPresetEditor, setShowPresetEditor] = useState(false)
  const [lastSelectionId, setLastSelectionId] = useState(null) // Track last selection to avoid duplicates
  const [showMorePresets, setShowMorePresets] = useState(false) // Expandable non-quick-action presets
  const [showAnalyzeModes, setShowAnalyzeModes] = useState(false) // Analyze mode selector
  const [directedContext, setDirectedContext] = useState('') // Deployment context for directed analyze
  const [showHistory, setShowHistory] = useState(false) // Conversation history panel

  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  // Font size from reader store (shared with document view)
  const { fontSize, setFontSize } = useReaderStore()

  // Derive source type from document data
  const sourceType = documentData?.source_type || 'document'
  const sourceTypeNoun = SOURCE_TYPE_NOUNS[sourceType] || 'this document'

  // API hooks
  const { data: models = [] } = useChatModels()
  const { data: presets = [] } = usePresets(sourceType)
  const sendMessage = useSendChatMessage()
  const { isStreaming, events, result, messageId: councilMessageId, startStream } = useStreamQuery()
  const saveAsNote = useSaveAsNote()

  // Conversation history hooks
  const { data: conversations = [] } = useConversations(sourceId)
  const deleteConversation = useDeleteConversation()

  const isCouncilMode = selectedModelId === 'council'

  // Initialize default model
  useEffect(() => {
    if (models.length > 0 && !selectedModelId) {
      const defaultId = getDefaultModel(models)
      if (defaultId) setSelectedModelId(defaultId)
    }
  }, [models, selectedModelId])

  // Add new selection to contexts (instead of replacing)
  useEffect(() => {
    if (!useFullDocument && selection?.text) {
      // Create a unique ID based on text content to avoid duplicates
      const selectionId = selection.text.slice(0, 50)
      if (selectionId !== lastSelectionId) {
        setLastSelectionId(selectionId)
        setContexts(prev => [...prev, {
          id: Date.now(),
          text: selection.text,
          type: 'selection'
        }])
      }
    }
  }, [selection, useFullDocument, lastSelectionId])

  // Handle full document toggle
  useEffect(() => {
    if (useFullDocument && content) {
      const maxChars = 15000
      const fullDocText = content.length > maxChars
        ? content.slice(0, maxChars) + '\n\n[Truncated...]'
        : content
      // Check if full doc context already exists
      setContexts(prev => {
        const hasFullDoc = prev.some(c => c.type === 'full')
        if (hasFullDoc) return prev
        return [...prev, { id: Date.now(), text: fullDocText, type: 'full' }]
      })
    }
  }, [useFullDocument, content])

  // Build combined context text for API
  const combinedContext = useMemo(() => {
    if (contexts.length === 0) return ''
    if (contexts.length === 1) return contexts[0].text
    return contexts.map((c, i) => `[Context ${i + 1}]\n${c.text}`).join('\n\n---\n\n')
  }, [contexts])

  // Remove a single context item
  const removeContext = useCallback((id) => {
    setContexts(prev => {
      const item = prev.find(c => c.id === id)
      if (item?.type === 'full') {
        setUseFullDocument(false)
      }
      return prev.filter(c => c.id !== id)
    })
  }, [])

  // Clear all contexts
  const clearAllContexts = useCallback(() => {
    setContexts([])
    setUseFullDocument(false)
    setLastSelectionId(null)
  }, [])

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, events])

  // Handle council stream completion
  useEffect(() => {
    if (result && !isStreaming) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.synthesis || result.content,
        mode: 'council',
        perspectives: result.perspectives,
        usage: result.usage,
        timestamp: result.timestamp,
        messageId: result.message_id || councilMessageId  // Include for Save as Note
      }])
    }
  }, [result, isStreaming, councilMessageId])

  // Auto-resize textarea
  const adjustTextareaHeight = useCallback(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      const scrollHeight = textarea.scrollHeight
      textarea.style.height = `${Math.min(Math.max(scrollHeight, 72), 192)}px`
    }
  }, [])

  useEffect(() => {
    adjustTextareaHeight()
  }, [inputText, adjustTextareaHeight])

  // Model options with Council
  const modelOptions = useMemo(() => {
    const available = models.filter(m => m.available)
    return [
      ...available,
      { id: 'council', name: 'Council', description: '3 models deliberate' }
    ]
  }, [models])

  const selectedPreset = presets.find(p => p.id === selectedPresetId)

  const canSend = useMemo(() => {
    if (sendMessage.isPending || isStreaming) return false
    if (!inputText.trim() && !selectedPresetId) return false
    if (!selectedModelId) return false
    return true
  }, [sendMessage.isPending, isStreaming, inputText, selectedPresetId, selectedModelId])

  // Send message
  const handleSend = async () => {
    if (!canSend) return

    let query = inputText.trim()
    if (!query && selectedPreset) {
      // Use full-doc prompt variant if available and full document mode is on
      const promptToUse = (useFullDocument && selectedPreset.prompt_full_doc)
        ? selectedPreset.prompt_full_doc
        : selectedPreset.prompt
      query = renderPrompt(promptToUse, {
        context: combinedContext,
        source_title: documentData?.title,
        author: documentData?.author,
        source_type: sourceTypeNoun,
      })
    }
    if (!query) return

    const userMessage = inputText.trim() || selectedPreset?.name || 'Query'
    setInputText('')

    setMessages(prev => [...prev, {
      role: 'user',
      content: userMessage,
      contextSnippet: combinedContext ? combinedContext.slice(0, 80) : null,
      contextType: useFullDocument ? 'full' : (combinedContext ? 'selection' : null),
      timestamp: new Date().toISOString()
    }])

    if (isCouncilMode) {
      startStream({
        context: combinedContext,
        query,
        sourceId,
        presetId: selectedPresetId,
        contextType: useFullDocument ? 'full' : 'selection'
      })
    } else {
      const apiMessages = [...messages, { role: 'user', content: query }].map(m => ({
        role: m.role,
        content: m.content
      }))

      try {
        const response = await sendMessage.mutateAsync({
          model_id: selectedModelId,
          messages: apiMessages,
          context: combinedContext,
          context_type: useFullDocument ? 'full' : 'selection',
          source_id: sourceId,
          source_type: sourceType,
          conversation_id: conversationId,
          max_tokens: maxTokens,
        })

        if (response.conversation_id) setConversationId(response.conversation_id)
        if (response.gluon_id) setGluonId(response.gluon_id)

        setMessages(prev => [...prev, {
          role: 'assistant',
          content: response.content,
          mode: 'single',
          model_id: response.model_id,
          usage: response.usage,
          messageId: response.message_id,
          timestamp: response.timestamp
        }])
      } catch (err) {
        setMessages(prev => [...prev, {
          role: 'error',
          content: err.message,
          timestamp: new Date().toISOString()
        }])
      }
    }
  }

  // Quick actions - presets marked as show_as_quick_action
  const quickActions = useMemo(() => {
    return presets.filter(p => p.show_as_quick_action)
  }, [presets])

  // Non-quick-action presets (shown in expandable "More" section)
  const morePresets = useMemo(() => {
    return presets.filter(p => !p.show_as_quick_action)
  }, [presets])

  // Quick action handler - inserts prompt text into textarea for editing
  // For Analyze preset, shows mode selector instead of immediately populating
  const handleQuickAction = (presetId) => {
    const preset = presets.find(p => p.id === presetId)
    if (!preset) return

    // Special handling for Analyze — show mode selector
    if (presetId === 'analyze') {
      setShowAnalyzeModes(true)
      setSelectedPresetId(presetId)
      return
    }

    // Use full-doc prompt variant if available and full document mode is on
    const promptToUse = (useFullDocument && preset.prompt_full_doc)
      ? preset.prompt_full_doc
      : preset.prompt

    const query = renderPrompt(promptToUse, {
      context: combinedContext || '[Select text to provide context]',
      source_title: documentData?.title,
      author: documentData?.author,
      source_type: sourceTypeNoun,
    })

    setInputText(query)
    setSelectedPresetId(presetId)

    // Focus the textarea so user can edit
    setTimeout(() => {
      textareaRef.current?.focus()
    }, 0)
  }

  // Handle Analyze mode selection
  const handleAnalyzeMode = (modeId) => {
    const preset = presets.find(p => p.id === 'analyze')
    if (!preset) return

    let prompt
    if (modeId === 'reverse') {
      prompt = ANALYZE_REVERSE_PROMPT
    } else if (modeId === 'directed') {
      if (!directedContext.trim()) {
        // Keep modal open, user needs to enter context
        return
      }
      prompt = ANALYZE_DIRECTED_PREAMBLE.replace('{deployment_context}', directedContext.trim()) + preset.prompt
    } else {
      // Comprehensive — use the default analyze prompt
      prompt = preset.prompt
    }

    const query = renderPrompt(prompt, {
      context: combinedContext || '[Select text to provide context]',
      source_title: documentData?.title,
      author: documentData?.author,
      source_type: sourceTypeNoun,
    })

    setInputText(query)
    setShowAnalyzeModes(false)
    setDirectedContext('')

    setTimeout(() => {
      textareaRef.current?.focus()
    }, 0)
  }

  const handleNewChat = () => {
    setMessages([])
    setInputText('')
    setConversationId(null)
    setGluonId(null)
    setSelectedPresetId(null)
    setShowAnalyzeModes(false)
    setDirectedContext('')
    clearAllContexts()
  }

  // Load a past conversation by fetching its messages
  const loadConversation = useCallback(async (convId) => {
    try {
      const response = await fetch(`${API_BASE}/council/conversations/${convId}`)
      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || `Failed to load conversation: ${response.status}`)
      }
      const data = await response.json()
      setMessages(data.messages.map(m => ({
        role: m.role,
        content: m.content,
        mode: m.mode,
        model_id: m.model,
        usage: m.usage,
        messageId: m.id,
        timestamp: m.created_at,
        perspectives: m.perspectives,
      })))
      setConversationId(convId)
      setShowHistory(false)
    } catch (err) {
      setMessages([{
        role: 'error',
        content: err.message,
        timestamp: new Date().toISOString()
      }])
    }
  }, [])

  // Auto-load initial conversation (from deep link)
  useEffect(() => {
    if (initialConversationId && !conversationId) {
      loadConversation(initialConversationId)
    }
  }, [initialConversationId, conversationId, loadConversation])

  const handleSaveAsNote = async (messageId) => {
    try {
      await saveAsNote.mutateAsync({ messageId, sourceId })
    } catch (err) {
      console.error('Failed to save as note:', err)
    }
  }

  const navigate = useNavigate()

  return (
    <div className={`flex flex-col h-full ${isExpanded ? 'p-6' : 'p-4'}`}>
      {/* Header: tight density */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          {/* Document context when expanded */}
          {isExpanded && documentData?.title && (
            <span className="text-[11px] text-muted truncate max-w-md">
              {documentData.title}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {/* Font size slider */}
          <div className="flex items-center gap-1.5 text-muted">
            <span className="text-[10px]">A</span>
            <input
              type="range"
              min="12"
              max="20"
              value={fontSize}
              onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
              className="w-14 h-1 bg-subtle rounded-lg appearance-none cursor-pointer accent-camel"
              title={`Font size: ${fontSize}px`}
            />
            <span className="text-[10px] w-4">{fontSize}</span>
          </div>
          {/* View Note button (auto-saved gluon) */}
          {gluonId && (
            <button
              onClick={() => navigate(`/gluon/${gluonId}`)}
              className="px-2 py-1 text-[10px] font-medium text-muted bg-raised/50 hover:bg-raised hover:text-camel rounded transition-all"
              title="View auto-saved chat note"
            >
              View Note
            </button>
          )}
          <button
            onClick={() => setShowPresetEditor(true)}
            className="px-2 py-1 text-[10px] font-medium text-secondary bg-raised hover:bg-elevated hover:text-primary rounded transition-all"
          >
            Edit Presets
          </button>
          {messages.length > 0 && (
            <button
              onClick={handleNewChat}
              className="px-2 py-1 text-[10px] font-medium text-muted bg-raised/50 hover:bg-raised hover:text-secondary rounded transition-all"
            >
              New Chat
            </button>
          )}
        </div>
      </div>

      {/* Conversation History */}
      {conversations.length > 0 && (
        <ConversationSelector
          conversations={conversations}
          activeConversationId={conversationId}
          showHistory={showHistory}
          onToggle={() => setShowHistory(prev => !prev)}
          onSelect={loadConversation}
          onNewChat={handleNewChat}
          onDelete={(id) => {
            deleteConversation.mutate(id)
            if (conversationId === id) handleNewChat()
          }}
        />
      )}

      {/* Controls Section: tight density */}
      <div className="space-y-3 mb-4">
        {/* Context Toggle */}
        <div className="flex items-center justify-between py-2 px-3 bg-raised/30 rounded-md">
          <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-tertiary">
            Full Document
          </span>
          <button
            onClick={() => setUseFullDocument(!useFullDocument)}
            className={`
              relative w-10 h-5 rounded-full transition-all duration-200
              ${useFullDocument
                ? 'bg-camel shadow-[0_0_8px_rgba(212,165,116,0.4)]'
                : 'bg-elevated'
              }
            `}
          >
            <span
              className={`
                absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-md
                transition-transform duration-200
                ${useFullDocument ? 'translate-x-5' : 'translate-x-0'}
              `}
            />
          </button>
        </div>

        {/* Context Display - Multiple Selections */}
        {contexts.length > 0 && (
          <div className="p-3 bg-base rounded-md border border-subtle">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold tracking-[0.08em] uppercase text-camel">
                Context ({contexts.length})
              </span>
              {contexts.length > 1 && (
                <button
                  onClick={clearAllContexts}
                  className="text-muted hover:text-secondary text-[10px]"
                >
                  Clear All
                </button>
              )}
            </div>
            <div className="space-y-1.5 max-h-32 overflow-auto">
              {contexts.map((ctx) => (
                <div
                  key={ctx.id}
                  className="flex items-start gap-2 p-2 bg-raised/50 rounded group"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className={`text-[9px] font-semibold uppercase tracking-wider ${
                        ctx.type === 'full' ? 'text-terra' : 'text-muted'
                      }`}>
                        {ctx.type === 'full' ? 'Full Doc' : 'Selection'}
                      </span>
                      <span className="text-[9px] text-muted/50">
                        {ctx.text.length.toLocaleString()} chars
                      </span>
                    </div>
                    <p className="text-[10px] text-muted leading-relaxed line-clamp-1">
                      {ctx.text.slice(0, 80)}{ctx.text.length > 80 ? '...' : ''}
                    </p>
                  </div>
                  <button
                    onClick={() => removeContext(ctx.id)}
                    className="text-muted hover:text-red-400 text-xs leading-none opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted/50 mt-2">
              Total: {combinedContext.length.toLocaleString()} chars
            </p>
          </div>
        )}

        {/* Quick Actions - from presets with show_as_quick_action */}
        {quickActions.length > 0 && (
          <div>
            <label className="block text-[11px] font-semibold tracking-[0.08em] uppercase text-tertiary mb-2 text-center">
              Quick Actions
            </label>
            <div className="flex flex-wrap gap-1.5 justify-center">
              {quickActions.map(preset => (
                <button
                  key={preset.id}
                  onClick={() => handleQuickAction(preset.id)}
                  disabled={isStreaming || sendMessage.isPending}
                  title={preset.description}
                  className={`
                    px-2.5 py-1.5 rounded text-[11px] font-medium transition-all
                    ${!isStreaming && !sendMessage.isPending
                      ? 'bg-raised text-secondary hover:bg-elevated hover:text-primary hover:shadow-md'
                      : 'bg-raised/40 text-muted/50 cursor-not-allowed'
                    }
                  `}
                >
                  {preset.name}
                </button>
              ))}
              {/* More toggle */}
              {morePresets.length > 0 && (
                <button
                  onClick={() => setShowMorePresets(prev => !prev)}
                  title={showMorePresets ? 'Hide more presets' : `${morePresets.length} more presets`}
                  className="px-2 py-1.5 rounded text-[11px] font-medium transition-all
                             text-muted hover:text-secondary hover:bg-raised/60"
                >
                  {showMorePresets ? '−' : '⋯'}
                </button>
              )}
            </div>
            {/* Expanded non-quick-action presets */}
            {showMorePresets && morePresets.length > 0 && (
              <div className="flex flex-wrap gap-1.5 justify-center mt-2 pt-2 border-t border-subtle/30">
                {morePresets.map(preset => (
                  <button
                    key={preset.id}
                    onClick={() => handleQuickAction(preset.id)}
                    disabled={isStreaming || sendMessage.isPending}
                    title={preset.description}
                    className={`
                      px-2.5 py-1.5 rounded text-[11px] font-medium transition-all
                      ${!isStreaming && !sendMessage.isPending
                        ? 'bg-raised/50 text-muted hover:bg-elevated hover:text-secondary hover:shadow-md'
                        : 'bg-raised/20 text-muted/40 cursor-not-allowed'
                      }
                    `}
                  >
                    {preset.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Analyze Mode Selector */}
      {showAnalyzeModes && (
        <div className="mb-4 p-3 bg-surface rounded-lg border border-subtle shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <label className="text-[11px] font-semibold tracking-[0.08em] uppercase text-camel">
              Analyze Mode
            </label>
            <button
              onClick={() => { setShowAnalyzeModes(false); setDirectedContext('') }}
              className="text-muted hover:text-secondary text-xs"
            >
              Cancel
            </button>
          </div>
          <div className="space-y-2">
            {ANALYZE_MODES.map(mode => (
              <div key={mode.id}>
                <button
                  onClick={() => !mode.requiresInput && handleAnalyzeMode(mode.id)}
                  className={`
                    w-full text-left px-3 py-2 rounded transition-all
                    ${mode.requiresInput
                      ? 'bg-raised/30 cursor-default'
                      : 'bg-raised hover:bg-elevated hover:shadow-md cursor-pointer'
                    }
                  `}
                >
                  <span className="text-[12px] font-medium text-secondary">{mode.name}</span>
                  <span className="text-[10px] text-muted ml-2">{mode.description}</span>
                </button>
                {mode.requiresInput && (
                  <div className="mt-1.5 flex gap-2">
                    <input
                      type="text"
                      value={directedContext}
                      onChange={(e) => setDirectedContext(e.target.value)}
                      placeholder="e.g., 'designing a curriculum for...' or 'writing a policy brief on...'"
                      className="flex-1 px-2 py-1.5 bg-base border border-subtle rounded text-[11px] text-secondary
                                 placeholder-muted/50 focus:outline-none focus:ring-1 focus:ring-camel/50"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && directedContext.trim()) {
                          handleAnalyzeMode('directed')
                        }
                      }}
                    />
                    <button
                      onClick={() => handleAnalyzeMode('directed')}
                      disabled={!directedContext.trim()}
                      className={`
                        px-3 py-1.5 rounded text-[11px] font-medium transition-all
                        ${directedContext.trim()
                          ? 'bg-camel/80 text-base hover:bg-camel'
                          : 'bg-raised text-muted cursor-not-allowed'
                        }
                      `}
                    >
                      Go
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Messages: standard density, independently scrollable */}
      <div className="flex-1 min-h-0 overflow-auto space-y-3 mb-4 -mx-1 px-1">
        {messages.length === 0 && !isStreaming && (
          <div className="text-center py-8">
            <p className="text-sm text-muted">Ask about this document</p>
            <p className="text-[11px] text-muted/60 mt-1">Select text or enable full document mode</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            models={models}
            onSaveAsNote={handleSaveAsNote}
            saveAsNote={saveAsNote}
            sourceId={sourceId}
            fontSize={fontSize}
          />
        ))}

        {isStreaming && <StreamingProgress events={events} />}

        {sendMessage.isPending && !isCouncilMode && (
          <div className="flex items-center gap-2 text-muted text-sm py-2">
            <Spinner className="w-4 h-4" />
            <span>Thinking...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="pt-3 border-t border-subtle">
        <textarea
          ref={textareaRef}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && canSend) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder={combinedContext ? 'Ask about this passage...' : 'Type your question...'}
          className="w-full px-3 py-2.5 bg-base border border-subtle rounded-md text-sm text-secondary
                     placeholder-muted/60 resize-none
                     focus:outline-none focus:ring-1 focus:ring-camel/50 focus:border-camel
                     shadow-[inset_0_1px_2px_rgba(0,0,0,0.3)]"
          style={{ minHeight: '72px' }}
        />

        <div className="flex items-center justify-between mt-2">
          {/* Model Selector */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <select
                value={selectedModelId || ''}
                onChange={(e) => setSelectedModelId(e.target.value)}
                className="px-3 py-2 bg-base border border-subtle rounded-md text-sm text-secondary
                           focus:outline-none focus:ring-1 focus:ring-camel/50 focus:border-camel
                           shadow-[inset_0_1px_2px_rgba(0,0,0,0.3)]"
              >
                {modelOptions.map(m => (
                  <option key={m.id} value={m.id}>
                    {m.id === 'council' ? '⚡ ' : ''}{m.name}
                  </option>
                ))}
              </select>
              <select
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value, 10))}
                className="px-2 py-2 bg-base border border-subtle rounded-md text-xs text-muted
                           focus:outline-none focus:ring-1 focus:ring-camel/50 focus:border-camel
                           shadow-[inset_0_1px_2px_rgba(0,0,0,0.3)]"
                title="Max response length"
              >
                <option value={4096}>4K</option>
                <option value={8192}>8K</option>
                <option value={12288}>12K</option>
                <option value={16384}>16K</option>
                <option value={32000}>32K</option>
              </select>
              {isCouncilMode && (
                <span className="text-[10px] text-terra">~$0.50</span>
              )}
            </div>
            {isCouncilMode && (
              <span className="text-[10px] text-muted">
                Claude Opus 4.5 • GPT-5.2 • Gemini 3 Pro
              </span>
            )}
          </div>

          <button
            onClick={handleSend}
            disabled={!canSend}
            className={`
              px-4 py-2 rounded-md text-sm font-medium transition-all
              ${canSend
                ? `bg-gradient-to-b from-camel/90 to-camel text-base
                   shadow-[0_2px_8px_rgba(212,165,116,0.3)]
                   hover:shadow-[0_4px_12px_rgba(212,165,116,0.4)]
                   hover:from-camel hover:to-camel/90
                   active:shadow-[0_1px_4px_rgba(212,165,116,0.3)]`
                : 'bg-raised text-muted cursor-not-allowed'
              }
            `}
          >
            {isStreaming || sendMessage.isPending ? (
              <Spinner className="w-4 h-4" />
            ) : (
              'Send'
            )}
          </button>
        </div>
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
 * Conversation Selector — collapsible list of past conversations for this source
 */
function ConversationSelector({ conversations, activeConversationId, showHistory, onToggle, onSelect, onNewChat, onDelete }) {
  // Format relative time
  const relativeTime = (dateStr) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now - date
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

    if (diffDays === 0) return 'Today'
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays}d ago`
    return date.toLocaleDateString()
  }

  return (
    <div className="mb-3">
      {/* Header bar — always visible */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2 bg-raised/30 rounded-md hover:bg-raised/50 transition-colors"
      >
        <span className="text-[11px] font-semibold tracking-[0.08em] uppercase text-tertiary">
          Conversations ({conversations.length})
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onNewChat() }}
            className="text-[10px] text-muted hover:text-camel transition-colors"
          >
            + New
          </button>
          <span className="text-muted text-xs">{showHistory ? '▲' : '▼'}</span>
        </div>
      </button>

      {/* Expanded conversation list */}
      {showHistory && (
        <div className="mt-1.5 space-y-1 max-h-48 overflow-auto">
          {conversations.map((conv) => {
            const isActive = conv.id === activeConversationId
            return (
              <div
                key={conv.id}
                onClick={() => onSelect(conv.id)}
                className={`
                  group flex items-start gap-2 px-3 py-2 rounded cursor-pointer transition-all
                  ${isActive
                    ? 'bg-raised border-l-2 border-camel'
                    : 'bg-raised/20 hover:bg-raised/50 border-l-2 border-transparent'
                  }
                `}
              >
                <div className="flex-1 min-w-0">
                  <p className={`text-[11px] truncate ${isActive ? 'text-primary' : 'text-secondary'}`}>
                    {conv.first_message_preview || conv.title || `Chat ${conv.id}`}
                  </p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[9px] text-muted">{conv.message_count} msgs</span>
                    <span className="text-[9px] text-muted/50">{relativeTime(conv.updated_at)}</span>
                  </div>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(conv.id)
                  }}
                  className="text-muted hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity mt-0.5"
                >
                  ×
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}


/**
 * Message Bubble
 */
function MessageBubble({ message, models, onSaveAsNote, saveAsNote, sourceId, fontSize = 14 }) {
  const [showPerspectives, setShowPerspectives] = useState(false)
  const model = models?.find(m => m.id === message.model_id)

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-raised/60 rounded-lg px-3 py-2">
          <p className="text-secondary" style={{ fontSize: `${fontSize}px`, lineHeight: 1.5 }}>{message.content}</p>
          {message.contextSnippet && (
            <p className="text-[10px] text-muted mt-1.5 truncate">
              "{message.contextSnippet}..."
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

  const isCouncil = message.mode === 'council'

  return (
    <div className="bg-surface rounded-lg overflow-hidden shadow-lg">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-raised/20 border-b border-subtle/50">
        <span className="text-[11px] font-medium text-secondary">
          {isCouncil ? (
            <span className="text-terra">Council Synthesis</span>
          ) : (
            model?.name || message.model_id
          )}
        </span>
        {message.usage && (
          <div className="flex items-center gap-2">
            {/* Cache status indicator */}
            {message.usage.cache_read_tokens > 0 ? (
              <span className="text-[9px] text-green-500/80" title={`Cache HIT: ${message.usage.cache_read_tokens.toLocaleString()} tokens from cache`}>
                cache hit
              </span>
            ) : message.usage.cache_creation_tokens > 0 ? (
              <span className="text-[9px] text-muted" title={`Cache created: ${message.usage.cache_creation_tokens.toLocaleString()} tokens cached for next call`}>
                cached
              </span>
            ) : null}
            <span className="text-[10px] text-muted">
              {formatCost(message.usage.totals?.cost_usd || message.usage.cost_usd)}
            </span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="px-3 py-3">
        <div className="text-secondary leading-relaxed" style={{ fontSize: `${fontSize}px` }}>
          {renderMarkdown(message.content)}
        </div>
      </div>

      {/* Perspectives Toggle */}
      {isCouncil && message.perspectives?.length > 0 && (
        <PerspectivesPanel
          perspectives={message.perspectives}
          showPerspectives={showPerspectives}
          setShowPerspectives={setShowPerspectives}
          sourceId={sourceId}
        />
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 px-3 py-2 border-t border-subtle/50">
        <button
          onClick={() => navigator.clipboard.writeText(message.content)}
          className="text-[11px] text-muted hover:text-secondary transition-colors"
        >
          Copy
        </button>
        {message.messageId && (
          <button
            onClick={() => onSaveAsNote(message.messageId)}
            disabled={saveAsNote?.isPending}
            className="text-[11px] text-muted hover:text-camel transition-colors"
          >
            {saveAsNote?.isPending ? 'Saving...' : 'Save as Note'}
          </button>
        )}
      </div>
    </div>
  )
}


/**
 * Streaming Progress
 */
function StreamingProgress({ events }) {
  const modelStates = useMemo(() => {
    const states = {
      anthropic: { started: false, complete: false, success: false },
      openai: { started: false, complete: false, success: false },
      openrouter: { started: false, complete: false, success: false },
    }

    for (const event of events) {
      if (event.event === 'model_start') {
        states[event.data.provider] = { ...states[event.data.provider], started: true }
      }
      if (event.event === 'model_complete') {
        states[event.data.provider] = {
          ...states[event.data.provider],
          complete: true,
          success: event.data.success
        }
      }
    }

    return states
  }, [events])

  const synthesisStarted = events.some(e => e.event === 'synthesis_start')

  return (
    <div className="bg-surface rounded-lg overflow-hidden shadow-lg">
      <div className="px-3 py-2 bg-raised/20 border-b border-subtle/50">
        <span className="text-[11px] font-medium text-terra">Council Deliberating</span>
      </div>

      <div className="p-3 space-y-2">
        <div className="flex gap-2">
          {Object.entries(modelStates).map(([provider, state]) => (
            <div
              key={provider}
              className={`
                flex-1 px-2 py-1.5 rounded text-center text-[10px] font-medium transition-all
                ${state.complete
                  ? state.success
                    ? 'bg-green-500/10 text-green-400'
                    : 'bg-red-500/10 text-red-400'
                  : state.started
                    ? 'bg-raised animate-pulse text-secondary'
                    : 'bg-raised/30 text-muted'
                }
              `}
            >
              {PROVIDER_DISPLAY[provider]?.name}
              {state.complete && (
                <span className="ml-1">{state.success ? '✓' : '✗'}</span>
              )}
            </div>
          ))}
        </div>

        {synthesisStarted && (
          <div className="flex items-center gap-2 text-[11px] text-muted">
            <Spinner className="w-3 h-3" />
            <span>Synthesizing...</span>
          </div>
        )}
      </div>
    </div>
  )
}


/**
 * Spinner
 */
function Spinner({ className = "w-4 h-4" }) {
  return (
    <svg className={`animate-spin ${className}`} fill="none" viewBox="0 0 24 24">
      <circle
        className="opacity-25"
        cx="12" cy="12" r="10"
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


/**
 * Perspectives Panel - Expandable view of individual model responses
 */
function PerspectivesPanel({ perspectives, showPerspectives, setShowPerspectives, sourceId }) {
  const createNote = useCreateNote()
  const [expandedPerspective, setExpandedPerspective] = useState(null)
  const [savingPerspective, setSavingPerspective] = useState(null)

  const handleSavePerspective = async (perspective) => {
    if (!sourceId) return

    setSavingPerspective(perspective.provider)
    try {
      const providerName = PROVIDER_DISPLAY[perspective.provider]?.name || perspective.provider
      const noteContent = `[${providerName} Analysis]\n\n${perspective.content}`

      await createNote.mutateAsync({
        source_id: sourceId,
        content: noteContent
      })
    } catch (err) {
      console.error('Failed to save perspective as note:', err)
    } finally {
      setSavingPerspective(null)
    }
  }

  return (
    <div className="border-t border-subtle/50">
      {/* Toggle Header */}
      <button
        onClick={() => setShowPerspectives(!showPerspectives)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-raised/30 transition-colors"
      >
        <span className="text-[11px] font-semibold tracking-[0.06em] uppercase text-muted">
          Individual Perspectives ({perspectives.length})
        </span>
        <span className="text-muted text-xs">
          {showPerspectives ? '▲' : '▼'}
        </span>
      </button>

      {/* Expanded Perspectives */}
      {showPerspectives && (
        <div className="px-3 pb-3 space-y-2">
          {perspectives.map((p) => {
            const display = PROVIDER_DISPLAY[p.provider] || { name: p.provider, color: '#888' }
            const isExpanded = expandedPerspective === p.provider
            const isSaving = savingPerspective === p.provider

            return (
              <div
                key={p.provider}
                className="bg-base rounded-lg overflow-hidden border border-subtle/30"
              >
                {/* Perspective Header */}
                <div
                  className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-raised/20 transition-colors"
                  onClick={() => setExpandedPerspective(isExpanded ? null : p.provider)}
                >
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: display.color }}
                    />
                    <span className="text-[11px] font-semibold text-secondary">
                      {display.name}
                    </span>
                    {p.usage?.cost_usd && (
                      <span className="text-[9px] text-muted">
                        {formatCost(p.usage.cost_usd)}
                      </span>
                    )}
                  </div>
                  <span className="text-muted text-[10px]">
                    {isExpanded ? 'Collapse' : 'Expand'}
                  </span>
                </div>

                {/* Perspective Content */}
                <div className={`px-3 pb-3 ${isExpanded ? '' : 'max-h-24 overflow-hidden'}`}>
                  <div className={`text-[12px] text-secondary/80 leading-relaxed ${!isExpanded ? 'line-clamp-3' : ''}`}>
                    {isExpanded ? renderMarkdown(p.content) : p.content}
                  </div>

                  {/* Fade overlay when collapsed */}
                  {!isExpanded && (
                    <div className="h-8 -mt-8 bg-gradient-to-t from-base to-transparent relative z-10" />
                  )}
                </div>

                {/* Actions (only when expanded) */}
                {isExpanded && (
                  <div className="flex items-center gap-3 px-3 py-2 border-t border-subtle/30 bg-raised/10">
                    <button
                      onClick={() => navigator.clipboard.writeText(p.content)}
                      className="text-[10px] text-muted hover:text-secondary transition-colors"
                    >
                      Copy
                    </button>
                    {sourceId && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleSavePerspective(p)
                        }}
                        disabled={isSaving}
                        className="text-[10px] text-muted hover:text-camel transition-colors"
                      >
                        {isSaving ? 'Saving...' : 'Save as Note'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
