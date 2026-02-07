import { useState, useRef, useEffect } from 'react'
import { useSessionMessages, useRLMStream, useSaveSessionMessage } from '../../hooks/useRLM'
import useReaderStore from '../../stores/useReaderStore'
import useResearchStore from '../../stores/useResearchStore'
import ToolCallFeed from './ToolCallFeed'
import { MarkdownContent } from '../../utils/markdown'

/**
 * RLMChat
 * =======
 * Chat interface with RLM streaming and tool call visibility.
 */
export default function RLMChat({ sessionId }) {
  const [input, setInput] = useState('')
  const inputRef = useRef(null)
  const messagesEndRef = useRef(null)
  const { data: messages = [], isLoading: messagesLoading } = useSessionMessages(sessionId)
  const {
    isStreaming,
    toolCalls,
    result,
    error,
    currentIteration,
    startStream,
    stopStream,
    reset
  } = useRLMStream()
  const saveMessage = useSaveSessionMessage()

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, toolCalls, result])

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [sessionId])

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || isStreaming) return

    reset()
    startStream({
      sessionId,
      query: input.trim(),
      maxTokens
    })
    setInput('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  const { fontSize, setFontSize } = useReaderStore()
  const { maxTokens, setMaxTokens } = useResearchStore()

  return (
    <div className="h-full flex flex-col">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {/* Controls bar */}
        <div className="sticky top-0 z-10 bg-base/95 backdrop-blur-sm border-b border-subtle/30">
          <div className="max-w-3xl mx-auto px-6 py-2 flex items-center justify-end gap-6">
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
                <StreamingState
                  toolCalls={toolCalls}
                  currentIteration={currentIteration}
                  onStop={stopStream}
                />
              )}

              {/* Streaming result (before saved to DB) */}
              {result && !isStreaming && (
                <MessageBubble
                  message={{
                    id: result.message_id,
                    role: 'assistant',
                    content: result.content,
                    context_snapshot: {
                      type: 'rlm',
                      tool_calls: result.tool_calls,
                      iterations: result.iterations
                    }
                  }}
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
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a research question..."
              rows={1}
              disabled={isStreaming}
              className="w-full px-4 py-3 pr-12 text-sm bg-base border border-subtle/50 rounded-lg text-primary placeholder-muted resize-none focus:outline-none focus:border-camel/50 disabled:opacity-50"
              style={{ minHeight: '48px', maxHeight: '200px' }}
            />
            <button
              type="submit"
              disabled={!input.trim() || isStreaming}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-camel hover:text-camel/80 disabled:text-muted disabled:cursor-not-allowed transition-colors"
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
            <span>Press Enter to send, Shift+Enter for new line</span>
            {isStreaming && (
              <button
                type="button"
                onClick={stopStream}
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
 * EmptyChat
 * =========
 * Shown when no messages exist yet.
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
 * MessageBubble
 * =============
 * Renders a single chat message.
 */
function MessageBubble({ message, fontSize = 16, isNew = false, onSaveAsNote, isSaving }) {
  const isUser = message.role === 'user'
  const isRLM = message.context_snapshot?.type === 'rlm'

  const handleSave = () => {
    if (message.id && onSaveAsNote) {
      onSaveAsNote(message.id)
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
        {/* RLM metadata badge */}
        {isRLM && !isUser && (
          <div className="mb-2 flex items-center gap-2 text-xs text-muted">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <span>{message.context_snapshot.tool_calls} tool calls</span>
            <span>•</span>
            <span>{message.context_snapshot.iterations} iterations</span>
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

        {/* Actions for assistant messages */}
        {!isUser && message.id && (
          <div className="mt-3 pt-2 border-t border-subtle/30 flex items-center gap-3">
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
 * StreamingState
 * ==============
 * Shows real-time progress during RLM execution.
 */
function StreamingState({ toolCalls, currentIteration, onStop }) {
  return (
    <div className="space-y-3">
      {/* Progress indicator */}
      <div className="flex items-center gap-3 text-sm text-tertiary">
        <div className="flex items-center gap-2">
          <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
          <span>Researching... (iteration {currentIteration})</span>
        </div>
      </div>

      {/* Tool calls feed */}
      {toolCalls.length > 0 && (
        <ToolCallFeed toolCalls={toolCalls} />
      )}
    </div>
  )
}
