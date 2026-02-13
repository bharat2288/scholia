/**
 * RLM-v2 Streaming Hook
 * =====================
 * SSE streaming for the code-execution RLM engine.
 *
 * Three-tier architecture:
 * - Orchestrator (Sonnet): writes Python code to explore documents
 * - Sub-LLM (Haiku): independent semantic reasoning on passages
 * - Synthesis (Opus): polished final answer from collected findings
 *
 * Events from /rlm-v2/stream:
 * - start: {query}
 * - thinking: {iteration}
 * - code_block: {code, iteration}
 * - exec_result: {stdout, stderr, error, duration_ms}
 * - sub_llm_done: {count, duration_ms}
 * - synthesizing: {model}
 * - complete: {content, iterations, sub_llm_calls, usage}
 * - error: {error}
 * - saved: {message_id}
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE } from '../config'

export function useRLMV2Stream() {
  const [isStreaming, setIsStreaming] = useState(false)
  const [isSynthesizing, setIsSynthesizing] = useState(false)
  const [codeBlocks, setCodeBlocks] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [currentIteration, setCurrentIteration] = useState(0)
  const [synthesisModel, setSynthesisModel] = useState(null)
  const eventSourceRef = useRef(null)
  const completedRef = useRef(false)
  const queryClient = useQueryClient()

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [])

  const startStream = useCallback(({
    sessionId,
    query,
    orchestratorModel = 'claude-sonnet',
    subModel = 'claude-haiku',
    synthesisModel: synthModel = 'claude-opus',
    maxIterations = 20,
    maxTokens = 4096
  }) => {
    // Reset state
    setIsStreaming(true)
    setIsSynthesizing(false)
    setCodeBlocks([])
    setResult(null)
    setError(null)
    setCurrentIteration(0)
    setSynthesisModel(null)
    completedRef.current = false

    const params = new URLSearchParams({
      query,
      orchestrator_model: orchestratorModel,
      sub_model: subModel,
      synthesis_model: synthModel,
      max_iterations: maxIterations.toString(),
      max_tokens: maxTokens.toString()
    })

    const url = `${API_BASE}/sessions/${sessionId}/rlm-v2/stream?${params.toString()}`
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    const eventTypes = ['start', 'thinking', 'code_block', 'exec_result', 'sub_llm_done', 'synthesizing', 'complete', 'error', 'saved']
    eventTypes.forEach(eventType => {
      eventSource.addEventListener(eventType, (e) => {
        try {
          const data = JSON.parse(e.data)

          switch (eventType) {
            case 'thinking':
              setCurrentIteration(data.iteration)
              break

            case 'code_block':
              setCodeBlocks(prev => [...prev, {
                code: data.code,
                iteration: data.iteration,
                stdout: null,
                stderr: null,
                error: null,
                duration_ms: null,
                subLlmCount: 0,
                status: 'running'
              }])
              break

            case 'sub_llm_done':
              setCodeBlocks(prev => {
                const updated = [...prev]
                if (updated.length > 0) {
                  const last = updated[updated.length - 1]
                  updated[updated.length - 1] = {
                    ...last,
                    subLlmCount: data.count,
                  }
                }
                return updated
              })
              break

            case 'exec_result':
              setCodeBlocks(prev => {
                const updated = [...prev]
                if (updated.length > 0) {
                  const last = updated[updated.length - 1]
                  updated[updated.length - 1] = {
                    ...last,
                    stdout: data.stdout || null,
                    stderr: data.stderr || null,
                    error: data.error || null,
                    duration_ms: data.duration_ms,
                    status: data.error ? 'error' : 'success'
                  }
                }
                return updated
              })
              break

            case 'synthesizing':
              setIsSynthesizing(true)
              setSynthesisModel(data.model)
              break

            case 'complete':
              setIsSynthesizing(false)
              setResult(data)
              break

            case 'error':
              completedRef.current = true
              setIsSynthesizing(false)
              setError(new Error(data.error))
              setIsStreaming(false)
              eventSource.close()
              eventSourceRef.current = null
              break

            case 'saved':
              completedRef.current = true
              setResult(prev => prev ? { ...prev, message_id: data.message_id } : data)
              setIsStreaming(false)
              eventSource.close()
              eventSourceRef.current = null
              queryClient.invalidateQueries({ queryKey: ['sessions'] })
              break
          }
        } catch (err) {
          console.error(`Failed to parse ${eventType} event:`, err)
        }
      })
    })

    eventSource.onerror = () => {
      if (completedRef.current) return
      setError(new Error('Stream connection failed'))
      setIsStreaming(false)
      setIsSynthesizing(false)
      eventSource.close()
      eventSourceRef.current = null
    }
  }, [queryClient])

  const stopStream = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    setIsStreaming(false)
    setIsSynthesizing(false)
  }, [])

  const reset = useCallback(() => {
    setCodeBlocks([])
    setResult(null)
    setError(null)
    setCurrentIteration(0)
    setIsSynthesizing(false)
    setSynthesisModel(null)
  }, [])

  return {
    isStreaming,
    isSynthesizing,
    synthesisModel,
    codeBlocks,
    result,
    error,
    currentIteration,
    startStream,
    stopStream,
    reset
  }
}
