/**
 * Council API Hooks
 * =================
 * React Query hooks for the LLM Council API.
 *
 * Provides:
 * - Presets management (list, create, update, delete, duplicate)
 * - Model availability checking
 * - Single and council queries
 * - SSE streaming for council deliberation
 * - Conversation persistence
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, useCallback, useRef, useEffect } from 'react'
import { API_BASE } from '../config'

/**
 * Fetch helper with error handling
 */
async function apiFetch(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`

  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `API error: ${response.status}`)
  }

  return response.json()
}

// ============================================================
// Presets
// ============================================================

/**
 * Fetch presets, optionally filtered by source type.
 * @param {string|null} sourceType - Filter presets for this source type (null = all)
 */
export function usePresets(sourceType = null) {
  const params = sourceType ? `?source_type=${sourceType}` : ''
  return useQuery({
    queryKey: ['council', 'presets', sourceType],
    queryFn: () => apiFetch(`/council/presets${params}`),
  })
}

/**
 * Create a new preset
 */
export function useCreatePreset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (preset) => apiFetch('/council/presets', {
      method: 'POST',
      body: JSON.stringify(preset),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['council', 'presets'] })
    },
  })
}

/**
 * Update a preset
 */
export function useUpdatePreset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, ...updates }) => apiFetch(`/council/presets/${id}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['council', 'presets'] })
    },
  })
}

/**
 * Delete a preset
 */
export function useDeletePreset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => apiFetch(`/council/presets/${id}`, {
      method: 'DELETE',
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['council', 'presets'] })
    },
  })
}

/**
 * Duplicate a preset
 */
export function useDuplicatePreset() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, name }) => {
      const params = name ? `?name=${encodeURIComponent(name)}` : ''
      return apiFetch(`/council/presets/${id}/duplicate${params}`, {
        method: 'POST',
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['council', 'presets'] })
    },
  })
}

// ============================================================
// Models
// ============================================================

/**
 * Fetch available models
 */
export function useModels() {
  return useQuery({
    queryKey: ['council', 'models'],
    queryFn: () => apiFetch('/council/models'),
    staleTime: 60000, // Models don't change often
  })
}

// ============================================================
// Queries
// ============================================================

/**
 * Send a council query (non-streaming)
 */
export function useSendQuery() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (query) => apiFetch('/council/query', {
      method: 'POST',
      body: JSON.stringify(query),
    }),
    onSuccess: (data) => {
      // Invalidate conversations if a new one was created
      if (data.conversation_id) {
        queryClient.invalidateQueries({ queryKey: ['council', 'conversations'] })
      }
    },
  })
}

/**
 * Stream a council deliberation via SSE
 *
 * Returns state and controls for streaming:
 * - isStreaming: whether stream is active
 * - events: array of received events
 * - result: final result when complete
 * - error: any error that occurred
 * - startStream: function to begin streaming
 * - stopStream: function to abort streaming
 *
 * @example
 * const { isStreaming, events, result, startStream } = useStreamQuery()
 *
 * startStream({
 *   context: "selected text...",
 *   query: "Summarize this",
 *   sourceId: "abc123"
 * })
 */
export function useStreamQuery() {
  const [isStreaming, setIsStreaming] = useState(false)
  const [events, setEvents] = useState([])
  const [result, setResult] = useState(null)
  const [messageId, setMessageId] = useState(null)  // Track message ID separately for immediate access
  const [error, setError] = useState(null)
  const eventSourceRef = useRef(null)
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
    context,
    query,
    sourceId = null,
    conversationId = null,
    presetId = null,
    contextType = 'selection'
  }) => {
    // Reset state
    setIsStreaming(true)
    setEvents([])
    setResult(null)
    setMessageId(null)
    setError(null)

    // Build URL with query params
    const params = new URLSearchParams({
      context,
      query,
      context_type: contextType
    })
    if (sourceId) params.append('source_id', sourceId)
    if (conversationId) params.append('conversation_id', conversationId)
    if (presetId) params.append('preset_id', presetId)

    const url = `${API_BASE}/council/query/stream?${params.toString()}`

    // Create EventSource
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    // Handle events
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        setEvents(prev => [...prev, { event: e.type || 'message', data }])
      } catch (err) {
        console.error('Failed to parse SSE data:', err)
      }
    }

    // Named event handlers
    const eventTypes = ['start', 'model_start', 'model_complete', 'synthesis_start', 'synthesis_complete', 'complete', 'saved']
    eventTypes.forEach(eventType => {
      eventSource.addEventListener(eventType, (e) => {
        try {
          const data = JSON.parse(e.data)
          setEvents(prev => [...prev, { event: eventType, data }])

          // Handle completion
          if (eventType === 'complete') {
            setResult(data)
          }

          // Handle saved event (final with IDs) - merge message_id into result
          if (eventType === 'saved') {
            setMessageId(data.message_id)
            setResult(prev => prev ? { ...prev, message_id: data.message_id, conversation_id: data.conversation_id } : data)
            setIsStreaming(false)
            eventSource.close()
            eventSourceRef.current = null
            // Invalidate conversations
            queryClient.invalidateQueries({ queryKey: ['council', 'conversations'] })
          }
        } catch (err) {
          console.error(`Failed to parse ${eventType} event:`, err)
        }
      })
    })

    eventSource.onerror = (e) => {
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

  return {
    isStreaming,
    events,
    result,
    messageId,
    error,
    startStream,
    stopStream
  }
}

// ============================================================
// Conversations
// ============================================================

/**
 * Fetch conversations for a source
 */
export function useConversations(sourceId) {
  return useQuery({
    queryKey: ['council', 'conversations', sourceId],
    queryFn: () => apiFetch(`/council/conversations?source_id=${sourceId}`),
    enabled: !!sourceId,
  })
}

/**
 * Fetch ALL conversations across all sources (for Knowledge view)
 */
export function useAllConversations() {
  return useQuery({
    queryKey: ['council', 'conversations', 'all'],
    queryFn: () => apiFetch('/council/conversations'),
  })
}

/**
 * Fetch a single conversation with messages
 */
export function useConversation(conversationId) {
  return useQuery({
    queryKey: ['council', 'conversation', conversationId],
    queryFn: () => apiFetch(`/council/conversations/${conversationId}`),
    enabled: !!conversationId,
  })
}

/**
 * Delete a conversation
 */
export function useDeleteConversation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => apiFetch(`/council/conversations/${id}`, {
      method: 'DELETE',
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['council', 'conversations'] })
    },
  })
}

// ============================================================
// Save as Note
// ============================================================

/**
 * Save a council message as a note
 */
export function useSaveAsNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ messageId, sourceId }) => {
      const params = sourceId ? `?source_id=${sourceId}` : ''
      return apiFetch(`/council/messages/${messageId}/save${params}`, {
        method: 'POST',
      })
    },
    onSuccess: (data) => {
      // Invalidate notes for the source
      if (data.source_id) {
        queryClient.invalidateQueries({ queryKey: ['notes', data.source_id] })
      }
      queryClient.invalidateQueries({ queryKey: ['notes', 'all'] })
    },
  })
}

// ============================================================
// Utility Functions
// ============================================================

/**
 * Render a preset prompt with context variables
 * @param {string} prompt - The prompt template
 * @param {Object} variables - Variables to substitute: { context, source_title, author, selection, source_type }
 * @returns {string} - Rendered prompt
 */
export function renderPrompt(prompt, variables = {}) {
  let rendered = prompt

  // Replace variables
  if (variables.context) {
    rendered = rendered.replace(/\{context\}/g, variables.context)
    rendered = rendered.replace(/\{selection\}/g, variables.context) // alias
  }
  if (variables.source_title) {
    rendered = rendered.replace(/\{source_title\}/g, variables.source_title)
  }
  if (variables.author) {
    rendered = rendered.replace(/\{author\}/g, variables.author)
  }
  if (variables.source_type) {
    rendered = rendered.replace(/\{source_type\}/g, variables.source_type)
  }

  return rendered
}

/**
 * Format cost for display
 * @param {number} cost - Cost in USD
 * @returns {string} - Formatted string like "$0.0012" or "< $0.01"
 */
export function formatCost(cost) {
  if (!cost || cost === 0) return '$0.00'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  return `$${cost.toFixed(2)}`
}

