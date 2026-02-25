/**
 * RLM API Hooks
 * =============
 * React Query hooks for Research Sessions and RLM streaming.
 *
 * Provides:
 * - Sessions CRUD (list, create, update, delete)
 * - Session sources management
 * - RLM streaming with tool call visibility
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useCallback, useRef, useEffect } from 'react'
import { API_BASE } from '../config'
import { apiFetch } from '../utils/api'

// ============================================================
// Sessions
// ============================================================

/**
 * Fetch all research sessions
 */
export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: () => apiFetch('/sessions'),
  })
}

/**
 * Fetch a single session with sources
 */
export function useSession(sessionId) {
  return useQuery({
    queryKey: ['sessions', sessionId],
    queryFn: () => apiFetch(`/sessions/${sessionId}`),
    enabled: !!sessionId,
  })
}

/**
 * Create a new session
 */
export function useCreateSession() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data) => apiFetch('/sessions', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}

/**
 * Update a session
 */
export function useUpdateSession() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, ...updates }) => apiFetch(`/sessions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['sessions', data.id] })
    },
  })
}

/**
 * Delete a session
 */
export function useDeleteSession() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => apiFetch(`/sessions/${id}`, {
      method: 'DELETE',
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
}

// ============================================================
// Session Sources
// ============================================================

/**
 * Add a source to a session
 */
export function useAddSessionSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sessionId, sourceId, contextType = 'full' }) =>
      apiFetch(`/sessions/${sessionId}/sources`, {
        method: 'POST',
        body: JSON.stringify({ source_id: sourceId, context_type: contextType }),
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['sessions', variables.sessionId] })
    },
  })
}

/**
 * Remove a source from a session
 */
export function useRemoveSessionSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sessionId, sourceId }) =>
      apiFetch(`/sessions/${sessionId}/sources/${sourceId}`, {
        method: 'DELETE',
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['sessions', variables.sessionId] })
    },
  })
}

// ============================================================
// Session Messages
// ============================================================

/**
 * Fetch message history for a session
 */
export function useSessionMessages(sessionId) {
  return useQuery({
    queryKey: ['sessions', sessionId, 'messages'],
    queryFn: () => apiFetch(`/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
  })
}

/**
 * Save a session message as a note
 */
export function useSaveSessionMessage() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (messageId) => apiFetch(`/sessions/messages/${messageId}/save`, {
      method: 'POST',
    }),
    onSuccess: () => {
      // Invalidate notes queries so they refresh
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['gluons'] })
    },
  })
}

// ============================================================
// RLM Streaming
// ============================================================

/**
 * Stream an RLM query with tool call visibility via SSE
 *
 * Returns state and controls for streaming:
 * - isStreaming: whether stream is active
 * - events: array of received events (tool calls, etc.)
 * - result: final result when complete
 * - error: any error that occurred
 * - toolCalls: current tool calls in progress
 * - startStream: function to begin streaming
 * - stopStream: function to abort streaming
 *
 * Events:
 * - start: {query} - Query begins
 * - iteration_start: {iteration} - New loop iteration
 * - tool_start: {id, name, input} - Tool execution begins
 * - tool_complete: {id, name, success, preview} - Tool finished
 * - complete: {content, tool_calls, iterations, usage} - Final answer
 * - error: {error} - Failure
 * - saved: {message_id} - Message persisted to database
 */
export function useRLMStream() {
  const [isStreaming, setIsStreaming] = useState(false)
  const [events, setEvents] = useState([])
  const [toolCalls, setToolCalls] = useState([]) // Active tool calls with status
  const [result, setResult] = useState(null)
  const [messageId, setMessageId] = useState(null)
  const [error, setError] = useState(null)
  const [currentIteration, setCurrentIteration] = useState(0)
  const eventSourceRef = useRef(null)
  const completedRef = useRef(false) // Track if stream completed successfully
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
    modelId = 'claude-opus',
    maxIterations = 20,
    maxTokens = 8192
  }) => {
    // Reset state
    setIsStreaming(true)
    setEvents([])
    setToolCalls([])
    setResult(null)
    setMessageId(null)
    setError(null)
    setCurrentIteration(0)
    completedRef.current = false

    // Build URL with query params
    const params = new URLSearchParams({
      query,
      model_id: modelId,
      max_iterations: maxIterations.toString(),
      max_tokens: maxTokens.toString()
    })

    const url = `${API_BASE}/sessions/${sessionId}/rlm/stream?${params.toString()}`

    // Create EventSource
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    // Named event handlers
    const eventTypes = ['start', 'iteration_start', 'tool_start', 'tool_complete', 'complete', 'error', 'saved']
    eventTypes.forEach(eventType => {
      eventSource.addEventListener(eventType, (e) => {
        try {
          const data = JSON.parse(e.data)
          setEvents(prev => [...prev, { event: eventType, data, timestamp: Date.now() }])

          switch (eventType) {
            case 'iteration_start':
              setCurrentIteration(data.iteration)
              break

            case 'tool_start':
              setToolCalls(prev => [...prev, {
                id: data.id,
                name: data.name,
                input: data.input,
                status: 'running',
                startTime: Date.now()
              }])
              break

            case 'tool_complete':
              setToolCalls(prev => prev.map(tc =>
                tc.id === data.id
                  ? { ...tc, status: data.success ? 'success' : 'error', preview: data.preview, endTime: Date.now() }
                  : tc
              ))
              break

            case 'complete':
              setResult(data)
              break

            case 'error':
              completedRef.current = true // Mark as done (with error)
              setError(new Error(data.error))
              setIsStreaming(false)
              eventSource.close()
              eventSourceRef.current = null
              break

            case 'saved':
              completedRef.current = true // Mark as successfully completed
              setMessageId(data.message_id)
              setResult(prev => prev ? { ...prev, message_id: data.message_id } : data)
              setIsStreaming(false)
              eventSource.close()
              eventSourceRef.current = null
              // Invalidate messages
              queryClient.invalidateQueries({ queryKey: ['sessions'] })
              break
          }
        } catch (err) {
          console.error(`Failed to parse ${eventType} event:`, err)
        }
      })
    })

    eventSource.onerror = (e) => {
      // Only treat as error if we haven't completed successfully
      // EventSource fires onerror when connection closes, even after normal completion
      if (completedRef.current) {
        return // Ignore - stream completed successfully
      }
      console.error('SSE error:', e)
      setError(new Error('Stream connection failed'))
      setIsStreaming(false)
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
  }, [])

  const reset = useCallback(() => {
    setEvents([])
    setToolCalls([])
    setResult(null)
    setMessageId(null)
    setError(null)
    setCurrentIteration(0)
  }, [])

  return {
    isStreaming,
    events,
    toolCalls,
    result,
    messageId,
    error,
    currentIteration,
    startStream,
    stopStream,
    reset
  }
}
