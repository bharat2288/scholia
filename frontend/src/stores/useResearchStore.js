import { create } from 'zustand'

/**
 * Research Store
 * ==============
 * Global state for research sessions.
 *
 * Manages:
 * - Active session ID
 * - UI state (panel widths, etc.)
 */

const STORAGE_KEY = 'scholia-research-widths'

const DEFAULT_WIDTHS = {
  sessions: 320,
  sources: 240,
}

const useResearchStore = create((set, get) => ({
  // Active session
  activeSessionId: null,

  // Panel widths (persisted)
  widths: (() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        return { ...DEFAULT_WIDTHS, ...JSON.parse(stored) }
      }
    } catch (e) {
      console.warn('Failed to load saved widths:', e)
    }
    return DEFAULT_WIDTHS
  })(),

  // Sources panel collapsed state
  sourcesCollapsed: false,

  // RLM settings
  maxTokens: 12288,  // Max tokens for LLM responses (default: 12288)
  rlmMode: 'code',  // 'tool-use' (v1) or 'code' (v2)

  // Actions
  setActiveSession: (sessionId) => set({ activeSessionId: sessionId }),

  clearActiveSession: () => set({ activeSessionId: null }),

  setMaxTokens: (tokens) => set({ maxTokens: tokens }),

  setRlmMode: (mode) => set({ rlmMode: mode }),

  setWidth: (pane, width) => {
    const newWidths = { ...get().widths, [pane]: width }
    set({ widths: newWidths })
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newWidths))
    } catch (e) {
      console.warn('Failed to save widths:', e)
    }
  },

  toggleSourcesPanel: () => set((state) => ({
    sourcesCollapsed: !state.sourcesCollapsed
  })),
}))

export default useResearchStore
