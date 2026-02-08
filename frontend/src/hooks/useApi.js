/**
 * API Hooks
 * =========
 * React Query hooks for API interactions.
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
// Sources (Documents, Web clips, etc.)
// ============================================================

/**
 * Fetch all sources in library
 */
export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: () => apiFetch('/sources?limit=1000'),
  })
}

// Backward compatibility alias
export const useDocuments = useSources

/**
 * Fetch a single source by ID
 */
export function useSource(id) {
  return useQuery({
    queryKey: ['sources', id],
    queryFn: () => apiFetch(`/sources/${id}`),
    enabled: !!id,
  })
}

// Backward compatibility alias
export const useDocument = useSource

/**
 * Import a new source (PDF/EPUB)
 */
export function useImportSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (file) => {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${API_BASE}/sources/import`, {
        method: 'POST',
        body: formData,
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || 'Import failed')
      }

      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}

// Backward compatibility alias
export const useImportDocument = useImportSource

/**
 * Update source metadata
 */
export function useUpdateSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, updates }) => apiFetch(`/sources/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    }),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      queryClient.invalidateQueries({ queryKey: ['sources', id] })
      queryClient.invalidateQueries({ queryKey: ['reading', id] })
    },
  })
}

// Backward compatibility alias
export const useUpdateDocument = useUpdateSource

/**
 * Get gluon stats for a source (highlight/note counts)
 * Used to show warning before delete
 */
export function useSourceGluonStats(sourceId) {
  return useQuery({
    queryKey: ['sources', sourceId, 'gluon-stats'],
    queryFn: () => apiFetch(`/sources/${sourceId}/gluon-stats`),
    enabled: !!sourceId,
  })
}

// Backward compatibility alias
export const useDocumentGluonStats = useSourceGluonStats

/**
 * Delete a source
 * @param {Object} options
 * @param {string} options.id - Source ID to delete
 * @param {boolean} options.keepGluons - If true, highlights/notes become orphans
 * @param {boolean} options.deleteLocalFiles - If true, delete local files for non-document sources
 */
export function useDeleteSource() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, keepGluons = false, deleteLocalFiles = false }) => {
      const params = new URLSearchParams({
        keep_gluons: keepGluons.toString(),
        delete_local_files: deleteLocalFiles.toString()
      })
      return apiFetch(`/sources/${id}?${params}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      queryClient.invalidateQueries({ queryKey: ['highlights'] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })
}

// Backward compatibility alias
export const useDeleteDocument = useDeleteSource

/**
 * Refresh library - scan sources folder for new/updated sources
 * Non-destructive: only imports new sources, upgrades extraction methods
 */
export function useRefreshSources() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => apiFetch('/sources/refresh', { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}

// Backward compatibility alias
export const useRefreshDocuments = useRefreshSources

/**
 * Clip a URL and add as web source
 * @param {Object} options
 * @param {string} options.url - URL to clip
 * @param {string} [options.title] - Optional title override
 */
export function useClipUrl() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ url, title }) => apiFetch('/sources/clip-url', {
      method: 'POST',
      body: JSON.stringify({ url, title }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}

/**
 * Clip a tweet/thread from Twitter/X
 * @param {Object} options
 * @param {string} options.url - Tweet URL (twitter.com or x.com)
 */
export function useClipTweet() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ url }) => apiFetch('/sources/clip-tweet', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}

/**
 * Clip a video transcript from YouTube (or other platforms)
 * @param {Object} options
 * @param {string} options.url - Video URL (youtube.com, youtu.be, vimeo.com)
 */
export function useClipVideo() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ url }) => apiFetch('/sources/clip-video', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}

// ============================================================
// Reading
// ============================================================

/**
 * Fetch source content for reading
 */
export function useSourceContent(id) {
  return useQuery({
    queryKey: ['reading', id],
    queryFn: () => apiFetch(`/reading/${id}`),
    enabled: !!id,
  })
}

// Backward compatibility alias
export const useDocumentContent = useSourceContent

/**
 * Update reading position
 */
export function useUpdateReadingPosition() {
  return useMutation({
    mutationFn: ({ sourceId, position }) => apiFetch(`/reading/${sourceId}/position`, {
      method: 'PUT',
      body: JSON.stringify(position),
    }),
  })
}

// ============================================================
// Highlights
// ============================================================

/**
 * Fetch highlights for a source
 */
export function useHighlights(sourceId) {
  return useQuery({
    queryKey: ['highlights', sourceId],
    queryFn: () => apiFetch(`/highlights?source_id=${sourceId}`),
    enabled: !!sourceId,
  })
}

/**
 * Create a new highlight
 */
export function useCreateHighlight() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (highlight) => apiFetch('/highlights', {
      method: 'POST',
      body: JSON.stringify(highlight),
    }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['highlights', variables.source_id] })
    },
  })
}

/**
 * Update a highlight
 */
export function useUpdateHighlight() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, updates, sourceId }) => apiFetch(`/highlights/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(updates),
    }),
    onSuccess: (_, { sourceId }) => {
      queryClient.invalidateQueries({ queryKey: ['highlights', sourceId] })
    },
  })
}

/**
 * Delete a highlight
 */
export function useDeleteHighlight() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, sourceId }) => apiFetch(`/highlights/${id}`, { method: 'DELETE' }),
    onSuccess: (_, { sourceId }) => {
      queryClient.invalidateQueries({ queryKey: ['highlights', sourceId] })
    },
  })
}

// ============================================================
// Gluons (Notes, Tags, References)
// ============================================================

/**
 * Fetch notes for a source
 */
export function useSourceNotes(sourceId) {
  return useQuery({
    queryKey: ['notes', sourceId],
    queryFn: () => apiFetch(`/gluons?source_id=${sourceId}&type=note`),
    enabled: !!sourceId,
  })
}

// Backward compatibility alias
export const useDocumentNotes = useSourceNotes

/**
 * Fetch all notes system-wide (for Knowledge view)
 */
export function useAllNotes() {
  return useQuery({
    queryKey: ['notes', 'all'],
    queryFn: () => apiFetch('/gluons?type=note'),
  })
}

/**
 * Fetch all highlights system-wide (for Knowledge view)
 */
export function useAllHighlights() {
  return useQuery({
    queryKey: ['highlights', 'all'],
    queryFn: () => apiFetch('/highlights'),
  })
}

/**
 * Fetch a single gluon with all its links
 * (Aliased as useRem for backward compatibility)
 */
export function useGluon(gluonId) {
  return useQuery({
    queryKey: ['gluons', gluonId],
    queryFn: () => apiFetch(`/gluons/${gluonId}`),
    enabled: !!gluonId,
  })
}

// Backward compatibility alias
export const useRem = useGluon

/**
 * Fetch all tags
 */
export function useTags() {
  return useQuery({
    queryKey: ['tags'],
    queryFn: () => apiFetch('/gluons/tags'),
  })
}

/**
 * Search tags (for keyword autocomplete)
 * Returns tags matching the query with usage counts
 */
export function useTagsSearch(query) {
  return useQuery({
    queryKey: ['tags', 'search', query],
    queryFn: () => apiFetch(`/gluons/tags?q=${encodeURIComponent(query)}`),
    enabled: query?.length >= 1,
  })
}

/**
 * Create a new tag gluon
 */
export function useCreateTag() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (name) => apiFetch('/gluons/tags', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })
}

/**
 * Search gluons (for autocomplete)
 * Optionally filter by type: 'note', 'tag', 'highlight'
 */
export function useGluonSearch(query, type = null) {
  const typeParam = type ? `&type=${type}` : ''
  return useQuery({
    queryKey: ['gluons', 'search', query, type],
    queryFn: () => apiFetch(`/gluons/search?q=${encodeURIComponent(query)}${typeParam}`),
    enabled: query?.length >= 2,
  })
}

// Backward compatibility alias
export const useRemSearch = useGluonSearch

/**
 * Find gluon by exact content (for [[ref]] navigation)
 * Returns { id, found } - use found to check if gluon exists
 */
export async function findGluonByContent(content) {
  return apiFetch(`/gluons/by-content?content=${encodeURIComponent(content)}`)
}

/**
 * Create a new note
 */
export function useCreateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (note) => apiFetch('/gluons/notes', {
      method: 'POST',
      body: JSON.stringify(note),
    }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['notes', variables.source_id] })
      queryClient.invalidateQueries({ queryKey: ['notes', 'all'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      // If attached to a parent gluon, invalidate its query so notes array updates
      if (variables.parent_gluon_id) {
        queryClient.invalidateQueries({ queryKey: ['gluons', variables.parent_gluon_id] })
      }
    },
  })
}

/**
 * Update a note/gluon
 */
export function useUpdateNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, content, sourceId }) => apiFetch(`/gluons/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ content }),
    }),
    onSuccess: (_, { id, sourceId }) => {
      // Invalidate the specific gluon query (for Gluon view)
      queryClient.invalidateQueries({ queryKey: ['gluons', id] })
      // Invalidate source-specific notes
      queryClient.invalidateQueries({ queryKey: ['notes', sourceId] })
      queryClient.invalidateQueries({ queryKey: ['notes', 'all'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })
}

/**
 * Delete a note/gluon
 */
export function useDeleteNote() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id) => apiFetch(`/gluons/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })
}

/**
 * Delete a gluon (note or tag) with optional force flag for tags with associations
 * Returns special error structure for 409 (has associations)
 */
export function useDeleteGluon() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, force = false }) => {
      const url = force ? `/gluons/${id}?force=true` : `/gluons/${id}`
      const response = await fetch(`${API_BASE}${url}`, { method: 'DELETE' })

      if (!response.ok) {
        const error = await response.json()
        // Enhance error with status code for special handling
        const enrichedError = new Error(error.detail?.message || error.detail || 'Delete failed')
        enrichedError.status = response.status
        enrichedError.detail = error.detail
        throw enrichedError
      }

      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      queryClient.invalidateQueries({ queryKey: ['gluons'] })
    },
  })
}

/**
 * Get backlinks for a gluon
 */
export function useBacklinks(gluonId) {
  return useQuery({
    queryKey: ['backlinks', gluonId],
    queryFn: () => apiFetch(`/gluons/${gluonId}/backlinks`),
    enabled: !!gluonId,
  })
}

/**
 * Create a link between gluons
 */
export function useCreateLink() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, targetId, linkType }) => apiFetch(`/gluons/${sourceId}/link`, {
      method: 'POST',
      body: JSON.stringify({ target_id: targetId, link_type: linkType }),
    }),
    onSuccess: (_, { sourceId, targetId }) => {
      queryClient.invalidateQueries({ queryKey: ['gluons', sourceId] })
      queryClient.invalidateQueries({ queryKey: ['backlinks', targetId] })
    },
  })
}

// ============================================================
// Search
// ============================================================

/**
 * Full-text search across documents and gluons
 */
export function useSearch(query) {
  return useQuery({
    queryKey: ['search', query],
    queryFn: () => apiFetch(`/search?q=${encodeURIComponent(query)}`),
    enabled: query?.length >= 2,
  })
}

// ============================================================
// Section Editor
// ============================================================

/**
 * Fetch raw text content for editing
 * Returns: content, content_path, original_path, sections
 */
export function useRawText(sourceId) {
  return useQuery({
    queryKey: ['sources', sourceId, 'raw'],
    queryFn: () => apiFetch(`/sources/${sourceId}/raw`),
    enabled: !!sourceId,
  })
}

/**
 * Save edited raw text and re-parse sections
 */
export function useUpdateRawText() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, content }) => apiFetch(`/sources/${sourceId}/raw`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
    onSuccess: (_, { sourceId }) => {
      // Invalidate related queries
      queryClient.invalidateQueries({ queryKey: ['sources', sourceId, 'raw'] })
      queryClient.invalidateQueries({ queryKey: ['reading', sourceId] })
      queryClient.invalidateQueries({ queryKey: ['sources', sourceId] })
      // Re-fetch highlights with updated offsets after edit
      queryClient.invalidateQueries({ queryKey: ['highlights', sourceId] })
    },
  })
}

/**
 * Preview sections without saving
 */
export function usePreviewSections() {
  return useMutation({
    mutationFn: ({ sourceId, content }) => apiFetch(`/sources/${sourceId}/preview-sections`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),
  })
}

// ============================================================
// Metadata Lookup
// ============================================================

/**
 * Lookup DOI metadata from Crossref
 */
export function useLookupDOI() {
  return useMutation({
    mutationFn: (doi) => apiFetch(`/metadata/lookup/doi/${encodeURIComponent(doi)}`),
  })
}

/**
 * Lookup ISBN metadata from Open Library
 */
export function useLookupISBN() {
  return useMutation({
    mutationFn: (isbn) => apiFetch(`/metadata/lookup/isbn/${encodeURIComponent(isbn)}`),
  })
}

/**
 * AI-powered metadata suggestion for a single source
 */
export function useSuggestMetadata() {
  return useMutation({
    mutationFn: (sourceId) => apiFetch(`/sources/${sourceId}/suggest-metadata`, {
      method: 'POST'
    }),
  })
}

/**
 * AI-powered batch metadata suggestion for multiple sources
 */
export function useBatchSuggestMetadata() {
  return useMutation({
    mutationFn: (sourceIds = null) => apiFetch('/sources/batch-suggest-metadata', {
      method: 'POST',
      body: JSON.stringify({
        source_ids: sourceIds ? sourceIds.map(id => String(id)) : null
      })
    }),
  })
}

// ============================================================
// People (Authors as Gluons)
// ============================================================

/**
 * Fetch all people gluons
 */
export function useAllPeople() {
  return useQuery({
    queryKey: ['people', 'all'],
    queryFn: () => apiFetch('/gluons/people'),
  })
}

/**
 * Fetch all unique site names (for web sources autocomplete)
 */
export function useSitenames() {
  return useQuery({
    queryKey: ['sitenames'],
    queryFn: () => apiFetch('/sources/sitenames/all'),
  })
}

/**
 * Search people gluons (authors/editors)
 */
export function usePeopleSearch(query) {
  return useQuery({
    queryKey: ['people', 'search', query],
    queryFn: () => apiFetch(`/gluons/people?q=${encodeURIComponent(query)}`),
    enabled: query?.length >= 1,
  })
}

/**
 * Create a new person gluon
 */
export function useCreatePerson() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (name) => apiFetch('/gluons/person', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })
}

/**
 * Find or create multiple tags at once (batch operation)
 * Used by AI suggest to create linked tags from plain text suggestions
 * @returns Array of {name, id} in same order as input
 */
export function useFindOrCreateTags() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (names) => apiFetch('/gluons/tags/batch', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })
}

/**
 * Find or create multiple people at once (batch operation)
 * Used by AI suggest to create linked authors/editors from plain text suggestions
 * @returns Array of {name, id} in same order as input
 */
export function useFindOrCreatePeople() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (names) => apiFetch('/gluons/people/batch', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['people'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })
}

// ============================================================
// Health
// ============================================================

/**
 * Check API health
 */
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => apiFetch('/health'),
    refetchInterval: 30000, // Check every 30 seconds
  })
}
