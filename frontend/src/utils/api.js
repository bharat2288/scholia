/**
 * Shared API Utilities
 * ====================
 * Common fetch helper and formatting functions used across hook files.
 */

import { API_BASE } from '../config'

/**
 * Fetch helper with error handling.
 * Wraps fetch() with JSON content-type, error extraction, and base URL.
 */
export async function apiFetch(endpoint, options = {}) {
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

/**
 * Format cost for display
 * @param {number} cost - Cost in USD
 * @returns {string} - Formatted string like "$0.0012" or "$0.01"
 */
export function formatCost(cost) {
  if (!cost || cost === 0) return '$0.00'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  return `$${cost.toFixed(2)}`
}
