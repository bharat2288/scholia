/**
 * PersonInput
 * ===========
 * Multi-person input with autocomplete from Person gluons.
 * Used for Authors, Editors, or any person-type metadata field.
 *
 * Features:
 * - Type to search existing Person gluons
 * - Semicolon (;) or Tab confirms current entry
 * - People displayed as removable chips
 * - "Create new person" option when no match
 * - Stores both display string and gluon IDs
 */

import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import { usePeopleSearch, useCreatePerson } from '../../hooks/useApi'

/**
 * Parse person string into array of person objects
 * @param {string} personString - Semicolon-separated names
 * @param {string} gluonIdsJson - JSON array of gluon IDs (may be null)
 * @returns {Array<{name: string, gluonId: string|null}>}
 */
function parsePersons(personString, gluonIdsJson) {
  if (!personString) return []

  const names = personString.split(';').map(n => n.trim()).filter(Boolean)
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
 * Serialize persons back to string and JSON
 * @param {Array<{name: string, gluonId: string|null}>} persons
 * @returns {{personString: string, gluonIdsJson: string}}
 */
function serializePersons(persons) {
  const personString = persons.map(a => a.name).join('; ')
  const gluonIds = persons.map(a => a.gluonId).filter(Boolean)
  const gluonIdsJson = gluonIds.length > 0 ? JSON.stringify(gluonIds) : null
  return { personString, gluonIdsJson }
}

/**
 * PersonInput component for author/editor fields
 * @param {string} value - Current person string (semicolon-separated)
 * @param {string} gluonIds - JSON string of gluon IDs
 * @param {function} onChange - Callback with new person string
 * @param {function} onGluonIdsChange - Callback with new gluon IDs JSON
 * @param {string} label - Field label (default: "Person(s)")
 * @param {string} placeholder - Input placeholder
 */
export default function PersonInput({
  value,
  gluonIds,
  onChange,
  onGluonIdsChange,
  label = "Person(s)",
  placeholder = "Type name..."
}) {
  const inputRef = useRef(null)
  const dropdownRef = useRef(null)

  // Internal state for persons
  const [persons, setPersons] = useState(() => parsePersons(value, gluonIds))
  const [inputValue, setInputValue] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [isCreating, setIsCreating] = useState(false)
  const [linkingIndex, setLinkingIndex] = useState(null) // Index of person being linked

  // Track last synced value to detect external changes
  const lastSyncedValue = useRef(value)

  // Sync from parent when value changes externally (e.g., AI suggestion)
  useEffect(() => {
    if (value !== lastSyncedValue.current) {
      setPersons(parsePersons(value, gluonIds))
      lastSyncedValue.current = value
    }
  }, [value, gluonIds])

  // Search for people (for autocomplete)
  const { data: searchResults = [] } = usePeopleSearch(inputValue)
  // Search for people to link existing persons
  const linkSearchQuery = linkingIndex !== null ? persons[linkingIndex]?.name : ''
  const { data: linkSearchResults = [] } = usePeopleSearch(linkSearchQuery)
  const createPerson = useCreatePerson()

  // Filter out already-added persons from suggestions
  const suggestions = useMemo(() => {
    const addedNames = new Set(persons.map(a => a.name.toLowerCase()))
    return searchResults.filter(p => !addedNames.has(p.name.toLowerCase()))
  }, [searchResults, persons])

  // Helper to update persons and sync to parent
  const updatePersons = useCallback((newPersons) => {
    setPersons(newPersons)
    const { personString, gluonIdsJson } = serializePersons(newPersons)
    lastSyncedValue.current = personString  // Mark as synced to prevent loop
    onChange(personString)
    onGluonIdsChange(gluonIdsJson)
  }, [onChange, onGluonIdsChange])

  // Add a person (from suggestion or new)
  const addPerson = async (name, gluonId = null) => {
    // Skip if already added
    if (persons.some(a => a.name.toLowerCase() === name.toLowerCase())) {
      setInputValue('')
      setShowDropdown(false)
      return
    }

    let finalGluonId = gluonId

    // If no gluonId, create new person
    if (!finalGluonId && name.trim()) {
      setIsCreating(true)
      try {
        const person = await createPerson.mutateAsync(name.trim())
        finalGluonId = person.id
      } catch (err) {
        console.error('Failed to create person:', err)
      }
      setIsCreating(false)
    }

    updatePersons([...persons, { name: name.trim(), gluonId: finalGluonId }])
    setInputValue('')
    setShowDropdown(false)
    setSelectedIndex(0)

    // Refocus input
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  // Remove a person
  const removePerson = (index) => {
    updatePersons(persons.filter((_, i) => i !== index))
    setLinkingIndex(null)
  }

  // Link an existing unlinked person to a Person gluon
  const linkPerson = async (index, gluonId = null) => {
    const person = persons[index]
    if (!person) return

    let finalGluonId = gluonId

    // If no gluonId provided, create new person
    if (!finalGluonId) {
      setIsCreating(true)
      try {
        const created = await createPerson.mutateAsync(person.name)
        finalGluonId = created.id
      } catch (err) {
        console.error('Failed to create person:', err)
      }
      setIsCreating(false)
    }

    // Update the person with the gluon link
    updatePersons(persons.map((a, i) =>
      i === index ? { ...a, gluonId: finalGluonId } : a
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
        // Check if there's a matching suggestion
        const match = suggestions.find(s => s.name.toLowerCase() === name.toLowerCase())
        addPerson(name, match?.id || null)
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
      // Tab or Enter with text but no dropdown = confirm as new person
      if ((e.key === 'Tab' || e.key === 'Enter') && inputValue.trim()) {
        e.preventDefault()
        const match = suggestions.find(s => s.name.toLowerCase() === inputValue.toLowerCase())
        addPerson(inputValue.trim(), match?.id || null)
        return
      }
      // Backspace with empty input = remove last person
      if (e.key === 'Backspace' && !inputValue && persons.length > 0) {
        removePerson(persons.length - 1)
        return
      }
      return
    }

    const maxIndex = suggestions.length // +0 for "Create new" option at end

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
          // Select existing suggestion
          const selected = suggestions[selectedIndex]
          addPerson(selected.name, selected.id)
        } else {
          // Create new (last option)
          addPerson(inputValue.trim(), null)
        }
        break
      case 'Escape':
        setShowDropdown(false)
        break
    }
  }

  // Close dropdown and link popup on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      // Close autocomplete dropdown
      if (dropdownRef.current && !dropdownRef.current.contains(e.target) &&
          inputRef.current && !inputRef.current.contains(e.target)) {
        setShowDropdown(false)
      }
      // Close link popup if clicking outside the entire component
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
        {/* Person chips */}
        {persons.map((person, i) => (
          <span
            key={i}
            className={`
              inline-flex items-center gap-1 px-2 py-0.5 rounded text-sm relative
              ${person.gluonId ? 'bg-raised text-secondary' : 'bg-raised/50 text-tertiary border border-dashed border-subtle'}
            `}
          >
            {person.name}
            {person.gluonId ? (
              <span className="w-1.5 h-1.5 rounded-full bg-camel/50" title="Linked to Person gluon" />
            ) : (
              <button
                type="button"
                onClick={() => setLinkingIndex(linkingIndex === i ? null : i)}
                className="text-camel/60 hover:text-camel ml-0.5"
                title="Link to Person gluon"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </button>
            )}
            <button
              type="button"
              onClick={() => removePerson(i)}
              className="text-muted hover:text-primary ml-0.5"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>

            {/* Link popup for unlinked persons */}
            {linkingIndex === i && !person.gluonId && (
              <div className="absolute top-full left-0 mt-1 z-50 bg-surface border border-subtle rounded-lg shadow-xl p-2 min-w-[200px]">
                <p className="text-xs text-muted mb-2">Link &ldquo;{person.name}&rdquo; to:</p>
                <button
                  type="button"
                  onClick={() => linkPerson(i, null)}
                  className="w-full px-2 py-1.5 text-left text-sm text-camel hover:bg-raised rounded transition-colors"
                  disabled={isCreating}
                >
                  {isCreating ? 'Creating...' : 'Create new Person'}
                </button>
                {/* Show matching existing people */}
                {linkSearchResults.slice(0, 3).map(p => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => linkPerson(i, p.id)}
                    className="w-full px-2 py-1.5 text-left text-sm text-secondary hover:bg-raised rounded transition-colors flex items-center gap-2"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-camel/40" />
                    {p.name}
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
          placeholder={persons.length === 0 ? placeholder : "Add another..."}
          className="flex-1 min-w-[120px] bg-transparent text-sm text-primary placeholder:text-muted outline-none"
          disabled={isCreating}
        />
      </div>

      {/* Helper text */}
      <p className="text-xs text-tertiary mt-1">
        Press ; or Tab to add. Dashed border = not linked (click link icon to connect).
      </p>

      {/* Dropdown */}
      {showDropdown && (suggestions.length > 0 || inputValue.trim()) && (
        <div
          ref={dropdownRef}
          className="absolute z-50 mt-1 w-full bg-surface border border-subtle rounded-lg shadow-xl max-h-48 overflow-auto"
        >
          {/* Existing suggestions */}
          {suggestions.map((p, i) => (
            <button
              key={p.id}
              type="button"
              onMouseDown={(e) => { e.preventDefault(); addPerson(p.name, p.id) }}
              className={`
                w-full px-3 py-2 text-left text-sm transition-colors flex items-center gap-2
                ${i === selectedIndex ? 'bg-raised text-primary' : 'text-secondary hover:bg-raised/50'}
              `}
            >
              <span className="w-2 h-2 rounded-full bg-camel/40" />
              <span>{p.name}</span>
            </button>
          ))}

          {/* Create new option */}
          {inputValue.trim() && (
            <button
              type="button"
              onMouseDown={(e) => { e.preventDefault(); addPerson(inputValue.trim(), null) }}
              className={`
                w-full px-3 py-2 text-left text-sm transition-colors
                ${selectedIndex === suggestions.length ? 'bg-raised' : 'hover:bg-raised/50'}
              `}
            >
              <span className="text-camel">Create &ldquo;{inputValue.trim()}&rdquo;</span>
              <span className="text-muted text-xs ml-2">(new person)</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}
