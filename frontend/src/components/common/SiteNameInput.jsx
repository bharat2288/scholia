/**
 * SiteNameInput
 * =============
 * Single-value autocomplete for site names (web sources).
 * Suggests from existing site names, allows new entries.
 *
 * Features:
 * - Type to search existing site names
 * - Shows usage count for each suggestion
 * - Enter/Tab confirms selection
 * - Allows free-form entry (not linked to gluons)
 */

import { useState, useRef, useEffect, useMemo } from 'react'
import { useSitenames } from '../../hooks/useApi'

/**
 * SiteNameInput component
 * @param {string} value - Current site name value
 * @param {function} onChange - Callback with new value
 * @param {string} label - Field label
 * @param {string} placeholder - Input placeholder
 */
export default function SiteNameInput({
  value,
  onChange,
  label = "Site Name",
  placeholder = "e.g., Medium, Substack"
}) {
  const inputRef = useRef(null)
  const dropdownRef = useRef(null)

  const [inputValue, setInputValue] = useState(value || '')
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)

  // Fetch all sitenames for autocomplete
  const { data: sitenamesData } = useSitenames()
  const sitenames = sitenamesData?.sitenames || []

  // Sync from parent when value changes externally
  useEffect(() => {
    setInputValue(value || '')
  }, [value])

  // Filter suggestions based on input
  const suggestions = useMemo(() => {
    if (!inputValue.trim()) return sitenames.slice(0, 8) // Show top 8 when empty
    const query = inputValue.toLowerCase()
    return sitenames.filter(s =>
      s.name.toLowerCase().includes(query)
    ).slice(0, 8)
  }, [sitenames, inputValue])

  // Check if current input exactly matches a suggestion
  const exactMatch = useMemo(() => {
    return sitenames.find(s => s.name.toLowerCase() === inputValue.toLowerCase())
  }, [sitenames, inputValue])

  // Handle input changes
  const handleInputChange = (e) => {
    const val = e.target.value
    setInputValue(val)
    setShowDropdown(true)
    setSelectedIndex(0)
    onChange(val)
  }

  // Handle selection from dropdown
  const handleSelect = (name) => {
    setInputValue(name)
    onChange(name)
    setShowDropdown(false)
    inputRef.current?.blur()
  }

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (!showDropdown || suggestions.length === 0) {
      if (e.key === 'Enter') {
        e.preventDefault()
        setShowDropdown(false)
      }
      return
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, suggestions.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
        break
      case 'Enter':
      case 'Tab':
        e.preventDefault()
        if (suggestions[selectedIndex]) {
          handleSelect(suggestions[selectedIndex].name)
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
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="relative">
      <label className="block text-xs text-muted mb-1">{label}</label>

      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        onFocus={() => setShowDropdown(true)}
        placeholder={placeholder}
        className="w-full bg-base border border-subtle rounded px-3 py-1.5 text-sm text-primary placeholder:text-muted focus:border-camel focus:outline-none shadow-[inset_0_1px_2px_rgba(0,0,0,0.15)]"
      />

      {/* Dropdown */}
      {showDropdown && suggestions.length > 0 && (
        <div
          ref={dropdownRef}
          className="absolute z-50 mt-1 w-full bg-surface border border-subtle rounded-lg shadow-xl max-h-48 overflow-auto"
        >
          {suggestions.map((s, i) => (
            <button
              key={s.name}
              type="button"
              onMouseDown={(e) => { e.preventDefault(); handleSelect(s.name) }}
              className={`
                w-full px-3 py-2 text-left text-sm transition-colors flex items-center justify-between
                ${i === selectedIndex ? 'bg-raised text-primary' : 'text-secondary hover:bg-raised/50'}
              `}
            >
              <span>{s.name}</span>
              <span className="text-xs text-muted">({s.usage_count})</span>
            </button>
          ))}

          {/* Show "new" indicator if input doesn't match any existing */}
          {inputValue.trim() && !exactMatch && (
            <div className="px-3 py-1.5 text-xs text-tertiary border-t border-subtle">
              Press Enter to use &ldquo;{inputValue}&rdquo;
            </div>
          )}
        </div>
      )}
    </div>
  )
}
