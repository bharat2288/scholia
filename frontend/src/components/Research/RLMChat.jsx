import { useState, useRef, useEffect } from 'react'
import { useSessionMessages, useRLMStream, useSaveSessionMessage } from '../../hooks/useRLM'
import { useRLMV2Stream } from '../../hooks/useRLMV2'
import useReaderStore from '../../stores/useReaderStore'
import useResearchStore from '../../stores/useResearchStore'
import ToolCallFeed from './ToolCallFeed'
import CodeBlockFeed from './CodeBlockFeed'
import EvidenceTrace from './EvidenceTrace'
import { MarkdownContent } from '../../utils/markdown'
import { formatCost, useChatModels } from '../../hooks/useChat'

/**
 * RLMChat
 * =======
 * Chat interface with RLM streaming and tool call visibility.
 * Supports two modes:
 * - Tool Use (v1): Claude calls tools, results enter context
 * - Code (v2): LLM writes Python, documents stay outside context
 */
export default function RLMChat({ sessionId }) {
  const [input, setInput] = useState('')
  const inputRef = useRef(null)
  const messagesEndRef = useRef(null)
  const { data: messages = [], isLoading: messagesLoading } = useSessionMessages(sessionId)
  const saveMessage = useSaveSessionMessage()

  // Both streaming hooks (only one active at a time)
  const v1Stream = useRLMStream()
  const v2Stream = useRLMV2Stream()

  const { fontSize, setFontSize } = useReaderStore()
  const { maxTokens, setMaxTokens, rlmMode, setRlmMode, rlmModels, setRlmModel } = useResearchStore()
  const { data: chatModels = [] } = useChatModels()

  // Determine active stream based on mode
  const isV2 = rlmMode === 'code'
  const activeStream = isV2 ? v2Stream : v1Stream
  const { isStreaming, result, error } = activeStream

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, v1Stream.toolCalls, v2Stream.codeBlocks, result])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [sessionId])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || isStreaming) return

    activeStream.reset()

    if (isV2) {
      v2Stream.startStream({
        sessionId,
        query: input.trim(),
        orchestratorModel: rlmModels.orchestrator,
        subModel: rlmModels.sub,
        synthesisModel: rlmModels.synthesis,
        maxTokens,
      })
    } else {
      v1Stream.startStream({
        sessionId,
        query: input.trim(),
        maxTokens,
      })
    }
    setInput('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {/* Controls bar */}
        <div className="sticky top-0 z-10 bg-base/95 backdrop-blur-sm border-b border-subtle/30">
          {/* Row 1: mode, tokens, font size */}
          <div className="max-w-3xl mx-auto px-6 pt-2 pb-1.5 flex items-center justify-end gap-6">
            {/* Mode selector */}
            <div className="flex items-center gap-2 text-muted">
              <select
                value={rlmMode}
                onChange={(e) => setRlmMode(e.target.value)}
                disabled={isStreaming}
                className="text-xs bg-surface border border-subtle/50 rounded px-2 py-1 text-secondary focus:outline-none focus:border-camel/50 disabled:opacity-50"
                title="Research engine mode"
              >
                <option value="tool-use">Tool Use</option>
                <option value="code">RLM (Code)</option>
              </select>
            </div>
            {/* Max tokens selector */}
            <div className="flex items-center gap-2 text-muted">
              <span className="text-xs">Tokens</span>
              <select
                value={maxTokens}
                onChange={(e) => setMaxTokens(parseInt(e.target.value, 10))}
                className="text-xs bg-surface border border-subtle/50 rounded px-2 py-1 text-secondary focus:outline-none focus:border-camel/50"
                title="Max response length"
              >
                <option value={4096}>4K</option>
                <option value={8192}>8K</option>
                <option value={12288}>12K</option>
                <option value={16384}>16K</option>
                <option value={32000}>32K</option>
              </select>
            </div>
            {/* Font size control */}
            <div className="flex items-center gap-2 text-muted">
              <span className="text-xs">A</span>
              <input
                type="range"
                min="12"
                max="24"
                value={fontSize}
                onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
                className="w-20 h-1 bg-subtle rounded-lg appearance-none cursor-pointer accent-camel"
                title={`Font size: ${fontSize}px`}
              />
              <span className="text-xs w-6">{fontSize}</span>
            </div>
          </div>
          {/* Row 2: RLM model selectors — only in code mode */}
          {isV2 && (
            <div className="max-w-3xl mx-auto px-6 pb-2 flex items-center justify-end">
              <RLMModelSelectors
                models={chatModels}
                rlmModels={rlmModels}
                setRlmModel={setRlmModel}
                disabled={isStreaming}
              />
            </div>
          )}
        </div>

        <div className="max-w-3xl mx-auto px-6 py-4 space-y-4">
          {messagesLoading ? (
            <div className="text-center text-tertiary py-8">Loading messages...</div>
          ) : messages.length === 0 && !isStreaming && !result ? (
            <EmptyChat />
          ) : (
            <>
              {/* Existing messages */}
              {messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  fontSize={fontSize}
                  onSaveAsNote={saveMessage.mutate}
                  isSaving={saveMessage.isPending}
                />
              ))}

              {/* Streaming state */}
              {isStreaming && (
                isV2 ? (
                  <StreamingStateV2
                    codeBlocks={v2Stream.codeBlocks}
                    currentIteration={v2Stream.currentIteration}
                    isSynthesizing={v2Stream.isSynthesizing}
                    synthesisModel={v2Stream.synthesisModel}
                    onStop={v2Stream.stopStream}
                  />
                ) : (
                  <StreamingState
                    toolCalls={v1Stream.toolCalls}
                    currentIteration={v1Stream.currentIteration}
                    onStop={v1Stream.stopStream}
                  />
                )
              )}

              {/* Streaming result (before saved to DB) */}
              {result && !isStreaming && !messages.some(m => m.id === result.message_id) && (
                <MessageBubble
                  message={buildResultMessage(result, isV2)}
                  fontSize={fontSize}
                  isNew
                  onSaveAsNote={saveMessage.mutate}
                  isSaving={saveMessage.isPending}
                />
              )}

              {/* Error state */}
              {error && (
                <div className="p-4 rounded-lg bg-terra/10 border border-terra/30 text-terra">
                  <div className="font-medium">Error</div>
                  <div className="text-sm mt-1">{error.message}</div>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 border-t border-subtle/30 bg-surface/20">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto px-6 py-4">
          <div className="relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value)
                // Auto-resize: reset height then set to scrollHeight
                e.target.style.height = 'auto'
                e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px'
              }}
              onKeyDown={handleKeyDown}
              placeholder="Ask a research question..."
              rows={2}
              disabled={isStreaming}
              className="w-full px-4 py-3 pr-12 text-sm bg-base border border-subtle/50 rounded-lg text-primary placeholder-muted resize-none focus:outline-none focus:border-camel/50 disabled:opacity-50"
              style={{ minHeight: '64px', maxHeight: '200px', overflow: 'auto' }}
            />
            <button
              type="submit"
              disabled={!input.trim() || isStreaming}
              className="absolute right-2 bottom-2 p-2 text-camel hover:text-camel/80 disabled:text-muted disabled:cursor-not-allowed transition-colors"
            >
              {isStreaming ? (
                <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </div>
          <div className="mt-2 text-xs text-muted flex items-center justify-between">
            <span>
              Press Enter to send, Shift+Enter for new line
              {isV2 && <span className="ml-2 text-camel/60">| RLM Code mode</span>}
            </span>
            {isStreaming && (
              <button
                type="button"
                onClick={activeStream.stopStream}
                className="text-terra hover:text-terra/80"
              >
                Stop generating
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}

/**
 * Build a message object from a streaming result for display.
 */
function buildResultMessage(result, isV2) {
  if (isV2) {
    const usage = result.usage?.total || {}
    return {
      id: result.message_id,
      role: 'assistant',
      content: result.content,
      usage: {
        input_tokens: usage.input_tokens,
        output_tokens: usage.output_tokens,
        cost_usd: usage.cost_usd,
      },
      context_snapshot: {
        type: 'rlm-v2',
        iterations: result.iterations,
        sub_llm_calls: result.sub_llm_calls,
        orchestrator_cost: result.usage?.orchestrator?.cost_usd,
        sub_llm_cost: result.usage?.sub_llm?.cost_usd,
        synthesis_cost: result.usage?.synthesis?.cost_usd,
        synthesis_model: result.usage?.synthesis?.model,
        raw_findings: result.raw_findings,
        stored_evidence: result.stored_evidence,
        doc_reads: result.doc_reads,
        codeBlocks: result.codeBlocks,
      }
    }
  }

  // V1 tool-use format
  return {
    id: result.message_id,
    role: 'assistant',
    content: result.content,
    usage: result.usage,
    context_snapshot: {
      type: 'rlm',
      tool_calls: result.tool_calls,
      iterations: result.iterations
    }
  }
}

/**
 * EmptyChat
 */
function EmptyChat() {
  return (
    <div className="text-center py-12">
      <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-surface flex items-center justify-center">
        <svg className="w-8 h-8 text-camel/50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
        </svg>
      </div>
      <h3 className="text-lg font-medium text-secondary mb-2">Start Researching</h3>
      <p className="text-sm text-tertiary max-w-md mx-auto">
        Ask questions about your sources. The AI will search, read, and analyze documents to provide grounded answers with citations.
      </p>
      <div className="mt-6 grid gap-2 max-w-md mx-auto">
        <SuggestedQuery text="What are the main arguments in these sources?" />
        <SuggestedQuery text="Find passages that discuss methodology" />
        <SuggestedQuery text="Compare how different authors approach this topic" />
      </div>
    </div>
  )
}

function SuggestedQuery({ text }) {
  return (
    <div className="px-4 py-2 text-sm text-tertiary bg-surface/50 rounded-lg border border-subtle/30 hover:border-camel/30 hover:text-secondary cursor-pointer transition-colors">
      "{text}"
    </div>
  )
}

/**
 * RLMModelSelectors
 * =================
 * Three compact dropdowns for orchestrator / sub / synthesis model tiers.
 * Filters available models by tier_hints from the API.
 */
function RLMModelSelectors({ models, rlmModels, setRlmModel, disabled }) {
  const selectClass = "text-xs bg-surface border border-subtle/50 rounded px-1.5 py-1 text-secondary focus:outline-none focus:border-camel/50 disabled:opacity-50"

  // Format pricing for option label: "$0.15/$0.60"
  const priceLabel = (m) => {
    const i = m.pricing?.input ?? 0
    const o = m.pricing?.output ?? 0
    return `$${i < 1 ? i.toFixed(2) : i}/${o < 1 ? o.toFixed(2) : o}`
  }

  const tiers = [
    { key: 'orchestrator', label: 'ORCH', hint: 'orchestrator', title: 'Orchestrator: writes code to explore documents' },
    { key: 'sub', label: 'SUB', hint: 'sub', title: 'Sub-LLM: cheap reasoning on passages' },
    { key: 'synthesis', label: 'SYNTH', hint: 'synthesis', title: 'Synthesis: polished final answer' },
  ]

  return (
    <div className="flex items-center flex-wrap gap-x-3 gap-y-1">
      {tiers.map(({ key, label, hint, title }) => {
        const filtered = models.filter(m => m.available && m.tier_hints?.includes(hint))
        return (
          <div key={key} className="flex items-center gap-1 text-muted">
            <span className="text-[10px] font-semibold tracking-wider opacity-50">{label}</span>
            <select
              value={rlmModels[key]}
              onChange={(e) => setRlmModel(key, e.target.value)}
              disabled={disabled}
              className={selectClass}
              title={title}
            >
              {filtered.map(m => (
                <option key={m.id} value={m.id}>
                  {m.name} ({priceLabel(m)})
                </option>
              ))}
            </select>
          </div>
        )
      })}
    </div>
  )
}

/**
 * MessageBubble
 * =============
 * Renders a single chat message. Handles both v1 (rlm) and v2 (rlm-v2) metadata.
 */
function MessageBubble({ message, fontSize = 16, isNew = false, onSaveAsNote, isSaving }) {
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'
  const snapshotType = message.context_snapshot?.type
  const isRLM = snapshotType === 'rlm'
  const isRLMV2 = snapshotType === 'rlm-v2'

  // Resolve cost from flat (v1) or nested (v2) usage structure
  const costUsd = message.usage?.cost_usd ?? message.usage?.total?.cost_usd ?? 0

  const handleSave = () => {
    if (message.id && onSaveAsNote) {
      onSaveAsNote(message.id)
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for older browsers
      const textarea = document.createElement('textarea')
      textarea.value = message.content
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`
          max-w-[85%] px-4 py-3 rounded-lg
          ${isUser
            ? 'bg-camel/20 border border-camel/30'
            : 'bg-surface border border-subtle/30'
          }
          ${isNew ? 'animate-fade-in' : ''}
        `}
      >
        {/* RLM v1 metadata badge */}
        {isRLM && !isUser && (
          <div className="mb-2 flex items-center gap-2 text-xs text-muted">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <span>{message.context_snapshot.tool_calls} tool calls</span>
            <span className="text-muted/50">/</span>
            <span>{message.context_snapshot.iterations} iterations</span>
            {costUsd > 0 && (
              <>
                <span className="text-muted/50">/</span>
                <span className="text-camel">{formatCost(costUsd)}</span>
              </>
            )}
          </div>
        )}

        {/* RLM v2 metadata badge */}
        {isRLMV2 && !isUser && (
          <div className="mb-2 flex items-center gap-2 text-xs text-muted">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
            <span className="text-blue-400 font-medium">RLM</span>
            <span>{message.context_snapshot.iterations} iter</span>
            <span className="text-muted/50">/</span>
            <span>{message.context_snapshot.sub_llm_calls} sub-queries</span>
            {message.context_snapshot.synthesis_model && (
              <>
                <span className="text-muted/50">/</span>
                <span className="text-purple-400">{message.context_snapshot.synthesis_model} synthesis</span>
              </>
            )}
            {costUsd > 0 && (
              <>
                <span className="text-muted/50">/</span>
                <span className="text-camel">{formatCost(costUsd)}</span>
              </>
            )}
          </div>
        )}

        {/* Message content */}
        <div
          className={`${isUser ? 'text-primary' : 'text-secondary'}`}
          style={{ fontSize: `${fontSize}px`, lineHeight: 1.6 }}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <MarkdownContent content={message.content} inheritFontSize />
          )}
        </div>

        {/* Evidence Trace for RLM-v2 messages */}
        {isRLMV2 && message.context_snapshot?.raw_findings && (
          <EvidenceTrace
            rawFindings={message.context_snapshot.raw_findings}
            storedEvidence={message.context_snapshot.stored_evidence}
            docReads={message.context_snapshot.doc_reads}
            iterations={message.context_snapshot.iterations}
            codeBlocks={message.context_snapshot.codeBlocks}
          />
        )}

        {/* Actions for assistant messages */}
        {!isUser && message.id && (
          <div className="mt-3 pt-2 border-t border-subtle/30 flex items-center gap-3">
            <button
              onClick={handleCopy}
              className="text-xs text-muted hover:text-camel transition-colors"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="text-xs text-muted hover:text-camel transition-colors disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : 'Save as Note'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * StreamingState (V1 - Tool Use)
 */
function StreamingState({ toolCalls, currentIteration, onStop }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-sm text-tertiary">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span>Researching... (iteration {currentIteration})</span>
        </div>
      </div>

      {toolCalls.length > 0 && (
        <ToolCallFeed toolCalls={toolCalls} />
      )}
    </div>
  )
}

/**
 * StreamingStateV2 (V2 - Code Execution)
 */
function StreamingStateV2({ codeBlocks, currentIteration, isSynthesizing, synthesisModel, onStop }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-sm text-tertiary">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          {isSynthesizing ? (
            <span className="text-purple-400">
              Synthesizing with {synthesisModel || 'Opus'}...
            </span>
          ) : (
            <span>
              Exploring documents... (iteration {currentIteration})
            </span>
          )}
          {!isSynthesizing && codeBlocks.length > 0 && (
            <span className="text-muted">
              | {codeBlocks.length} blocks
              {codeBlocks.reduce((sum, b) => sum + (b.subLlmCount || 0), 0) > 0 &&
                ` | ${codeBlocks.reduce((sum, b) => sum + (b.subLlmCount || 0), 0)} sub-queries`
              }
            </span>
          )}
        </div>
      </div>

      {codeBlocks.length > 0 && (
        <CodeBlockFeed codeBlocks={codeBlocks} />
      )}
    </div>
  )
}
