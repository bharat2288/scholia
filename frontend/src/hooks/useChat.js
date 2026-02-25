/**
 * Chat API Hooks
 * ==============
 * React Query hooks for the simple single-model chat API.
 *
 * Provides:
 * - Model availability checking
 * - Send chat messages
 * - Conversation listing and retrieval
 * - Conversation deletion
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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
// Models
// ============================================================

/**
 * Fetch available chat models
 */
export function useChatModels() {
  return useQuery({
    queryKey: ['chat', 'models'],
    queryFn: () => apiFetch('/chat/models'),
    staleTime: 60000, // Models don't change often
  })
}

/**
 * Get the default model from the models list
 */
export function getDefaultModel(models) {
  if (!models || models.length === 0) return null
  const defaultModel = models.find(m => m.default && m.available)
  if (defaultModel) return defaultModel.id
  // Fall back to first available model
  const firstAvailable = models.find(m => m.available)
  return firstAvailable?.id || null
}

// ============================================================
// Chat Messages
// ============================================================

/**
 * Send a chat message
 *
 * This is a stateless API - you send the full conversation history
 * with each request. The backend persists messages for retrieval
 * but doesn't maintain state between requests.
 *
 * @example
 * const sendMessage = useSendChatMessage()
 *
 * sendMessage.mutate({
 *   model_id: 'claude-sonnet',
 *   messages: [
 *     { role: 'user', content: 'Hello' },
 *   ],
 *   context: 'Document text...',
 *   source_id: 'abc123'
 * })
 */
export function useSendChatMessage() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request) => apiFetch('/chat/message', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
    onSuccess: (data) => {
      // Invalidate conversations if a new one was created
      if (data.conversation_id) {
        queryClient.invalidateQueries({ queryKey: ['chat', 'conversations'] })
      }
    },
  })
}

// ============================================================
// Conversations
// ============================================================

/**
 * Fetch conversations for a source
 */
export function useChatConversations(sourceId) {
  return useQuery({
    queryKey: ['chat', 'conversations', sourceId],
    queryFn: () => apiFetch(`/chat/conversations/${sourceId}`),
    enabled: !!sourceId,
  })
}

/**
 * Fetch a single conversation with messages
 */
export function useChatConversation(conversationId) {
  return useQuery({
    queryKey: ['chat', 'conversation', conversationId],
    queryFn: () => apiFetch(`/chat/conversation/${conversationId}`),
    enabled: !!conversationId,
  })
}

/**
 * Delete a conversation
 */
export function useDeleteChatConversation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => apiFetch(`/chat/conversation/${id}`, {
      method: 'DELETE',
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    },
  })
}

// ============================================================
// Utility Functions
// ============================================================

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

