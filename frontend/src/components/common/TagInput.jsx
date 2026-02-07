/**
 * TagInput
 * ========
 * Multi-tag input with autocomplete from existing tag gluons.
 * Links sources to tag gluons (same tags used in notes via ##hashtag).
 *
 * Features:
 * - Type to search existing tag gluons
 * - Semicolon (;) or Tab confirms current entry
 * - Tags displayed as removable chips
 * - "Create new tag" option when no match
 * - Stores both display string and gluon IDs
 */

import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { useTagsSearch, useCreateTag } from '../../hooks/useApi'

/**
 * Parse tag string into array of tag objects
 * @param {string} tagString - Semicolon-separated tag names
 * @param {string} gluonIdsJson - JSON array of gluon IDs (may be null)
 * @returns {Array<{name: string, gluonId: string|null}>}
 */
function parseTags(tagString, gluonIdsJson) {
  if (!tagString) return []

  // Support both semicolon and comma for backwards compatibility
  const names = tagString.split(/[;,]/).map(n => n.trim()).filter(Boolean)
  let gluonIds = []

  try {
    if (gluonIdsJson) {
      gluonIds = JSON.parse(gluonIdsJson)
    }
  } catch (e) {
    // Invalid JSON, ignore
  }

  return names.map((name, i) => ({
    name,
    gluonId: gluonIds[i] || null
  }))
}

/**
 * Serialize tags back to string and JSON
 * @param {Array<{name: string, gluonId: string|null}>} tags
 * @returns {{tagString: string, gluonIdsJson: string}}
 */
function serializeTags(tags) {
  // Use semicolon as delimiter (consistent with authors/editors)
  const tagString = tags.map(t => t.name).join('; ')
  const gluonIds = tags.map(t => t.gluonId).filter(Boolean)
  const gluonIdsJson = gluonIds.length > 0 ? JSON.stringify(gluonIds) : null
  return { tagString, gluonIdsJson }
}

/**
 * TagInput component for keyword fields
 * @param {string} value - Current tag string (comma-separated)
 * @param {string} gluonIds - JSON string of gluon IDs
 * @param {function} onChange - Callback with new tag string
 * @param {function} onGluonIdsChange - Callback with new gluon IDs JSON
 * @param {string} label - Field label (default: "Keywords")
 * @param {string} placeholder - Input placeholder
 */
export default function TagInput({
  value,
  gluonIds,
  onChange,
  onGluonIdsChange,
  label = "Tags",
  placeholder = "Type tag..."
}) {
  const inputRef = useRef(null)
  const dropdownRef = useRef(null)

  // Internal state for tags
  const [tags, setTags] = useState(() => parseTags(value, gluonIds))
  const [inputValue, setInputValue] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [isCreating, setIsCreating] = useState(false)
  const [linkingIndex, setLinkingIndex] = useState(null)

  // Track last synced value to detect external changes
  const lastSyncedValue = useRef(value)

  // Sync from parent when value changes externally
  useEffect(() => {
    if (value !== lastSyncedValue.current) {
      setTags(parseTags(value, gluonIds))
      lastSyncedValue.current = value
    }
  }, [value, gluonIds])

  // Search for tags (for autocomplete)
  const { data: searchResults = [] } = useTagsSearch(inputValue)
  // Search for tags to link existing unlinked tags
  const linkSearchQuery = linkingIndex !== null ? tags[linkingIndex]?.name : ''
  const { data: linkSearchResults = [] } = useTagsSearch(linkSearchQuery)
  const createTag = useCreateTag()

  // Filter out already-added tags from suggestions
  const suggestions = useMemo(() => {
    const addedNames = new Set(tags.map(t => t.name.toLowerCase()))
    return searchResults.filter(t => !addedNames.has(t.name.toLowerCase()))
  }, [searchResults, tags])

  // Helper to update tags and sync to parent
  const updateTags = useCallback((newTags) => {
    setTags(newTags)
    const { tagString, gluonIdsJson } = serializeTags(newTags)
    lastSyncedValue.current = tagString
    onChange(tagString)
    onGluonIdsChange(gluonIdsJson)
  }, [onChange, onGluonIdsChange])

  // Add a tag (from suggestion or new)
  const addTag = async (name, gluonId = null) => {
    // Skip if already added
    if (tags.some(t => t.name.toLowerCase() === name.toLowerCase())) {
      setInputValue('')
      setShowDropdown(false)
      return
    }

    let finalGluonId = gluonId

    // If no gluonId, create new tag
    if (!finalGluonId && name.trim()) {
      setIsCreating(true)
      try {
        const tag = await createTag.mutateAsync(name.trim())
        finalGluonId = tag.id
      } catch (err) {
        console.error('Failed to create tag:', err)
      }
      setIsCreating(false)
    }

    updateTags([...tags, { name: name.trim(), gluonId: finalGluonId }])
    setInputValue('')
    setShowDropdown(false)
    setSelectedIndex(0)

    // Refocus input
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  // Remove a tag
  const removeTag = (index) => {
    updateTags(tags.filter((_, i) => i !== index))
    setLinkingIndex(null)
  }

  // Link an existing unlinked tag to a Tag gluon
  const linkTag = async (index, gluonId = null) => {
    const tag = tags[index]
    if (!tag) return

    let finalGluonId = gluonId

    // If no gluonId provided, create new tag
    if (!finalGluonId) {
      setIsCreating(true)
      try {
        const created = await createTag.mutateAsync(tag.name)
        finalGluonId = created.id
      } catch (err) {
        console.error('Failed to create tag:', err)
      }
      setIsCreating(false)
    }

    // Update the tag with the gluon link
    updateTags(tags.map((t, i) =>
      i === index ? { ...t, gluonId: finalGluonId } : t
    ))
    setLinkingIndex(null)
  }

  // Handle input changes
  const handleInputChange = (e) => {
    const val = e.target.value

    // Check for semicolon (confirm current entry)
    if (val.includes(';')) {
      const name = val.replace(';', '').trim()
      if (name) {
        const match = suggestions.find(s => s.name.toLowerCase() === name.toLowerCase())
        addTag(name, match?.id || null)
      }
      return
    }

    setInputValue(val)
    setShowDropdown(val.length > 0)
    setSelectedIndex(0)
  }

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (!showDropdown) {
      if ((e.key === 'Tab' || e.key === 'Enter') && inputValue.trim()) {
        e.preventDefault()
        const match = suggestions.find(s => s.name.toLowerCase() === inputValue.toLowerCase())
        addTag(inputValue.trim(), match?.id || null)
        return
      }
      if (e.key === 'Backspace' && !inputValue && tags.length > 0) {
        removeTag(tags.length - 1)
        return
      }
      return
    }

    const maxIndex = suggestions.length

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, maxIndex))
        break
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
        break
      case 'Enter':
      case 'Tab':
        e.preventDefault()
        if (selectedIndex < suggestions.length) {
          const selected = suggestions[selectedIndex]
          addTag(selected.name, selected.id)
        } else {
          addTag(inputValue.trim(), null)
        }
        break
      case 'Escape':
        setShowDropdown(false)
        break
    }
  }

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target) &&
          inputRef.current && !inputRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
      if (linkingIndex !== null) {
        const container = inputRef.current?.closest('.relative')
        if (container && !container.contains(e.target)) {
          setLinkingIndex(null)
        }
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [linkingIndex])

  return (
    <div className="relative">
      <label className="block text-xs text-muted mb-1">{label}</label>

      {/* Input container with chips */}
      <div className="flex flex-wrap gap-1.5 p-2 bg-base border border-subtle rounded min-h-[38px] focus-within:border-camel transition-colors shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]">
        {/* Tag chips */}
        {tags.map((tag, i) => (
          <span
            key={i}
            className={`
              inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs relative
              ${tag.gluonId ? 'bg-terra/80 text-base' : 'bg-terra/30 text-tertiary border border-dashed border-terra/50'}
            `}
          >
            {tag.name}
            {tag.gluonId ? (
              <span className="w-1.5 h-1.5 rounded-full bg-green-400/70" title="Linked to tag gluon" />
            ) : (
              <button
                type="button"
                onClick={() => setLinkingIndex(linkingIndex === i ? null : i)}
                className="text-base/60 hover:text-base ml-0.5"
                title="Link to tag gluon"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </button>
            )}
            <button
              type="button"
              onClick={() => removeTag(i)}
              className="text-base/60 hover:text-base ml-0.5"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            {/* Link popup for unlinked tags */}
            {linkingIndex === i && !tag.gluonId && (
              <div className="absolute top-full left-0 mt-1 z-50 bg-surface border border-subtle rounded-lg shadow-xl p-2 min-w-[200px]">
                <p className="text-xs text-muted mb-2">Link &ldquo;{tag.name}&rdquo; to:</p>
                <button
                  type="button"
                  onClick={() => linkTag(i, null)}
                  className="w-full px-2 py-1.5 text-left text-sm text-terra hover:bg-raised rounded transition-colors"
                  disabled={isCreating}
                >
                  {isCreating ? 'Creating...' : 'Create new Tag'}
                </button>
                {linkSearchResults.slice(0, 3).map(t => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => linkTag(i, t.id)}
                    className="w-full px-2 py-1.5 text-left text-sm text-secondary hover:bg-raised rounded transition-colors flex items-center gap-2"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-terra/60" />
                    {t.name}
                  </button>
                ))}
              </div>
            )}
          </span>
        ))}

        {/* Text input */}
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={() => inputValue && setShowDropdown(true)}
          placeholder={tags.length === 0 ? placeholder : "Add another..."}
          className="flex-1 min-w-[120px] bg-transparent text-sm text-primary placeholder:text-muted outline-none"
          disabled={isCreating}
        />
      </div>

      {/* Helper text */}
      <p className="text-xs text-tertiary mt-1">
        Press ; or Tab to add. Dashed = not linked (click to connect).
      </p>

      {/* Dropdown */}
      {showDropdown && (suggestions.length > 0 || inputValue.trim()) && (
        <div
          ref={dropdownRef}
          className="absolute z-50 mt-1 w-full bg-surface border border-subtle rounded-lg shadow-xl max-h-48 overflow-auto"
        >
          {/* Existing suggestions */}
          {suggestions.map((t, i) => (
            <button
              key={t.id}
              type="button"
              onMouseDown={(e) => { e.preventDefault(); addTag(t.name, t.id) }}
              className={`
                w-full px-3 py-2 text-left text-sm transition-colors flex items-center gap-2
                ${i === selectedIndex ? 'bg-raised text-primary' : 'text-secondary hover:bg-raised/50'}
              `}
            >
              <span className="w-2 h-2 rounded-full bg-terra/60" />
              <span>{t.name}</span>
              {t.usage_count > 0 && (
                <span className="text-xs text-muted ml-auto">({t.usage_count})</span>
              )}
            </button>
          ))}

          {/* Create new option */}
          {inputValue.trim() && (
            <button
              type="button"
              onMouseDown={(e) => { e.preventDefault(); addTag(inputValue.trim(), null) }}
              className={`
                w-full px-3 py-2 text-left text-sm transition-colors
                ${selectedIndex === suggestions.length ? 'bg-raised' : 'hover:bg-raised/50'}
              `}
            >
              <span className="text-terra">Create &ldquo;{inputValue.trim()}&rdquo;</span>
              <span className="text-muted text-xs ml-2">(new tag)</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}
