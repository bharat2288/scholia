import { create } from 'zustand'

/**
 * Reader Store
 * ============
 * Global state for the document reader.
 *
 * Manages:
 * - Current document and sections
 * - Reading position
 * - Highlights
 * - Selection state for new highlights
 * - Font size preference
 */

// Load font size from localStorage
const getStoredFontSize = () => {
  try {
    const stored = localStorage.getItem('scholia-reader-fontsize')
    if (stored) {
      const size = parseInt(stored, 10)
      if (size >= 12 && size <= 24) return size
    }
  } catch (e) {}
  return 16 // default
}

const useReaderStore = create((set, get) => ({
  // Current document
  document: null,
  sections: [],
  content: '',           // Full extracted text
  isLoading: false,
  error: null,

  // Reading position
  currentSectionId: null,
  scrollPosition: 0,

  // Highlights for current document
  highlights: [],

  // Selection state (for creating new highlights)
  selection: null,       // { start, end, text }
  highlightMenuOpen: false,
  highlightMenuPosition: { x: 0, y: 0 },

  // Sidebar state
  sidebarTab: 'highlights',  // 'highlights', 'notes', 'backlinks'

  // Font size (persisted)
  fontSize: getStoredFontSize(),

  // Actions
  setDocument: (document) => set({ document }),

  setSections: (sections) => set({ sections }),

  setContent: (content) => set({ content }),

  setLoading: (isLoading) => set({ isLoading }),

  setError: (error) => set({ error }),

  // Navigation
  setCurrentSection: (sectionId) => set({ currentSectionId: sectionId }),

  setScrollPosition: (position) => set({ scrollPosition: position }),

  goToNextSection: () => {
    const { sections, currentSectionId } = get()
    const currentIndex = sections.findIndex(s => s.id === currentSectionId)
    if (currentIndex < sections.length - 1) {
      set({ currentSectionId: sections[currentIndex + 1].id })
    }
  },

  goToPrevSection: () => {
    const { sections, currentSectionId } = get()
    const currentIndex = sections.findIndex(s => s.id === currentSectionId)
    if (currentIndex > 0) {
      set({ currentSectionId: sections[currentIndex - 1].id })
    }
  },

  // Highlights
  setHighlights: (highlights) => set({ highlights }),

  addHighlight: (highlight) => set((state) => ({
    highlights: [...state.highlights, highlight]
  })),

  removeHighlight: (id) => set((state) => ({
    highlights: state.highlights.filter(h => h.id !== id)
  })),

  updateHighlight: (id, updates) => set((state) => ({
    highlights: state.highlights.map(h =>
      h.id === id ? { ...h, ...updates } : h
    )
  })),

  // Selection handling
  setSelection: (selection) => set({ selection }),

  openHighlightMenu: (position) => set({
    highlightMenuOpen: true,
    highlightMenuPosition: position
  }),

  closeHighlightMenu: () => set({
    highlightMenuOpen: false,
    selection: null
  }),

  // Sidebar
  setSidebarTab: (tab) => set({ sidebarTab: tab }),

  // Font size
  setFontSize: (size) => {
    const clamped = Math.max(12, Math.min(24, size))
    try {
      localStorage.setItem('scholia-reader-fontsize', clamped.toString())
    } catch (e) {}
    set({ fontSize: clamped })
  },

  // Reset state when leaving reader
  reset: () => set({
    document: null,
    sections: [],
    content: '',
    highlights: [],
    selection: null,
    highlightMenuOpen: false,
    currentSectionId: null,
    scrollPosition: 0,
  }),

  // Get highlights for a specific section
  getHighlightsForSection: (sectionId) => {
    return get().highlights.filter(h => h.section_id === sectionId)
  },

  // Get all highlights sorted by position
  getSortedHighlights: () => {
    return [...get().highlights].sort((a, b) => a.start_offset - b.start_offset)
  },
}))

export default useReaderStore
