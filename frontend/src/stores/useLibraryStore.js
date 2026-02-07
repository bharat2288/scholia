import { create } from 'zustand'

/**
 * Library Store
 * =============
 * Global state for the document library.
 *
 * Manages:
 * - List of documents
 * - Filter/sort state
 * - Import status
 */

const useLibraryStore = create((set, get) => ({
  // Documents list
  documents: [],
  isLoading: false,
  error: null,

  // Filters - additive (off by default, click to enable)
  activeSourceTypes: [],  // empty = show all, otherwise show only these types
  showWithNotes: false,
  showWithHighlights: false,
  showAISkipped: false,   // show sources with metadata_skip = true
  showAIEnabled: false,   // show sources with metadata_skip = false/null
  activeKeywords: [],     // keyword gluon IDs to filter by

  // View mode
  viewMode: 'grid',       // 'grid' or 'row'

  // Legacy filters (keeping for compatibility)
  filterType: null,      // 'book', 'article', 'chapter' or null for all
  filterTag: null,       // Tag ID to filter by
  sortBy: 'recent',      // 'recent', 'updated_at', 'title', 'author', 'year', 'annotated'
  sortOrder: 'desc',     // 'asc' or 'desc'

  // Search
  searchQuery: '',

  // Import state
  importProgress: null,  // { filename, status, progress }

  // Actions
  setDocuments: (documents) => set({ documents }),

  setLoading: (isLoading) => set({ isLoading }),

  setError: (error) => set({ error }),

  setFilter: (filterType) => set({ filterType }),

  setSearch: (searchQuery) => set({ searchQuery }),

  setSortBy: (sortBy) => {
    // Default direction: alphabetical fields start ascending, everything else descending
    const ascByDefault = ['title', 'author']
    const defaultOrder = ascByDefault.includes(sortBy) ? 'asc' : 'desc'
    set({ sortBy, sortOrder: defaultOrder })
  },

  toggleSortOrder: () => set((state) => ({
    sortOrder: state.sortOrder === 'asc' ? 'desc' : 'asc'
  })),

  setImportProgress: (importProgress) => set({ importProgress }),

  // New filter actions
  toggleSourceType: (type) => set((state) => {
    const current = state.activeSourceTypes
    if (current.includes(type)) {
      return { activeSourceTypes: current.filter(t => t !== type) }
    } else {
      return { activeSourceTypes: [...current, type] }
    }
  }),

  setShowWithNotes: (val) => set({ showWithNotes: val }),

  setShowWithHighlights: (val) => set({ showWithHighlights: val }),

  setShowAISkipped: (val) => set({ showAISkipped: val, showAIEnabled: val ? false : get().showAIEnabled }),

  setShowAIEnabled: (val) => set({ showAIEnabled: val, showAISkipped: val ? false : get().showAISkipped }),

  toggleKeyword: (keywordId) => set((state) => {
    const current = state.activeKeywords
    if (current.includes(keywordId)) {
      return { activeKeywords: current.filter(k => k !== keywordId) }
    } else {
      return { activeKeywords: [...current, keywordId] }
    }
  }),

  setViewMode: (mode) => set({ viewMode: mode }),

  clearFilters: () => set({
    activeSourceTypes: [],
    showWithNotes: false,
    showWithHighlights: false,
    showAISkipped: false,
    showAIEnabled: false,
    activeKeywords: [],
    searchQuery: ''
  }),

  // Computed: filtered and sorted documents
  getFilteredDocuments: () => {
    const {
      documents, filterType, filterTag, searchQuery, sortBy, sortOrder,
      activeSourceTypes, showWithNotes, showWithHighlights, showAISkipped, showAIEnabled, activeKeywords
    } = get()

    let filtered = [...documents]

    // Apply source type filter (additive - empty means show all)
    if (activeSourceTypes.length > 0) {
      filtered = filtered.filter(doc =>
        activeSourceTypes.includes(doc.source_type || 'document')
      )
    }

    // Apply annotation filters (AND logic)
    if (showWithNotes) {
      filtered = filtered.filter(doc => (doc.note_count || 0) > 0)
    }
    if (showWithHighlights) {
      filtered = filtered.filter(doc => (doc.highlight_count || 0) > 0)
    }
    // Apply AI skip filters (metadata_skip is stored as 1/0 in SQLite)
    // These are mutually exclusive
    if (showAISkipped) {
      filtered = filtered.filter(doc => doc.metadata_skip)
    } else if (showAIEnabled) {
      filtered = filtered.filter(doc => !doc.metadata_skip)
    }

    // Apply keyword filter (OR logic - show if has any of the active keywords)
    if (activeKeywords.length > 0) {
      filtered = filtered.filter(doc => {
        const docKeywordIds = (doc.keywords || []).map(k => k.id)
        return activeKeywords.some(kwId => docKeywordIds.includes(kwId))
      })
    }

    // Legacy type filter
    if (filterType) {
      filtered = filtered.filter(doc => doc.doc_type === filterType)
    }

    // Apply search (also search keywords)
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(doc => {
        // Check title and author
        if (doc.title?.toLowerCase().includes(query)) return true
        if (doc.author?.toLowerCase().includes(query)) return true
        if (doc.author_display?.toLowerCase().includes(query)) return true
        // Check keywords
        const keywords = doc.keywords || []
        return keywords.some(kw => kw.content?.toLowerCase().includes(query))
      })
    }

    // Sort — single source of truth for all sorting logic.
    // Each field extracts a value; nulls always sort to the bottom.
    filtered.sort((a, b) => {
      let aVal, bVal
      const isAsc = sortOrder === 'asc'

      switch (sortBy) {
        case 'title':
          aVal = a.title || ''
          bVal = b.title || ''
          break
        case 'author':
          aVal = a.author_display || ''
          bVal = b.author_display || ''
          break
        case 'year':
          aVal = a.year || null
          bVal = b.year || null
          break
        case 'updated_at':
          aVal = a.updated_at || ''
          bVal = b.updated_at || ''
          break
        case 'annotated':
          aVal = (a.note_count || 0) + (a.highlight_count || 0)
          bVal = (b.note_count || 0) + (b.highlight_count || 0)
          break
        case 'recent':
        default:
          aVal = a.created_at || ''
          bVal = b.created_at || ''
          break
      }

      // Push nulls/empty to bottom regardless of direction
      const aEmpty = aVal === null || aVal === ''
      const bEmpty = bVal === null || bVal === ''
      if (aEmpty && bEmpty) return 0
      if (aEmpty) return 1
      if (bEmpty) return -1

      // Compare
      let result
      if (typeof aVal === 'string') {
        result = aVal.localeCompare(bVal, undefined, { sensitivity: 'base' })
      } else {
        result = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
      }

      return isAsc ? result : -result
    })

    return filtered
  },

  // Add a new document (after import)
  addDocument: (document) => set((state) => ({
    documents: [document, ...state.documents]
  })),

  // Remove a document
  removeDocument: (id) => set((state) => ({
    documents: state.documents.filter(doc => doc.id !== id)
  })),

  // Update a document
  updateDocument: (id, updates) => set((state) => ({
    documents: state.documents.map(doc =>
      doc.id === id ? { ...doc, ...updates } : doc
    )
  })),
}))

export default useLibraryStore
