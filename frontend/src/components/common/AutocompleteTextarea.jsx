import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useGluonSearch, useTags } from '../../hooks/useApi'

/**
 * AutocompleteTextarea
 * ====================
 * Shared text input with [[ref]] and ##tag autocomplete.
 * Extracted from Reader.jsx NoteEditor for reuse in Journal forms.
 *
 * Props:
 *   value        - controlled text value
 *   onChange      - (newValue: string) => void
 *   onSubmit      - () => void — called on Ctrl+Enter (textarea) or Enter (input mode)
 *   onCancel      - () => void — called on Escape
 *   placeholder   - placeholder text
 *   autoFocus     - focus on mount
 *   rows          - initial textarea rows (ignored in input mode)
 *   className     - additional CSS classes on the outer wrapper
 *   inputMode     - 'textarea' (default) | 'input' — input uses single-line, Enter submits
 *   inputRef      - optional external ref to the underlying element
 */
export default function AutocompleteTextarea({
  value,
  onChange,
  onSubmit,
  onCancel,
  placeholder,
  autoFocus = false,
  rows = 3,
  className = '',
  inputMode = 'textarea',
  inputRef: externalRef,
}) {
  const internalRef = useRef(null)
  const elRef = externalRef || internalRef

  const [showAutocomplete, setShowAutocomplete] = useState(false)
  const [autocompleteType, setAutocompleteType] = useState(null) // 'ref' or 'tag'
  const [autocompleteQuery, setAutocompleteQuery] = useState('')
  const [autocompletePosition, setAutocompletePosition] = useState({ top: 0, left: 0 })
  const [selectedIndex, setSelectedIndex] = useState(0)

  // Auto-resize for textarea mode
  const adjustHeight = useCallback(() => {
    if (inputMode === 'textarea' && elRef.current) {
      elRef.current.style.height = 'auto'
      elRef.current.style.height = `${Math.min(Math.max(elRef.current.scrollHeight, 72), 192)}px`
    }
  }, [inputMode, elRef])

  useEffect(() => {
    adjustHeight()
  }, [value, adjustHeight])

  // Fetch search results for [[ref]] autocomplete
  const { data: searchResults = [] } = useGluonSearch(
    autocompleteType === 'ref' ? autocompleteQuery : null
  )
  const { data: allTags = [] } = useTags()

  // Filter tags for ##tag autocomplete
  const filteredTags = useMemo(() => {
    if (autocompleteType !== 'tag') return []
    const query = autocompleteQuery.toLowerCase()
    return allTags.filter(t => t.name.toLowerCase().includes(query)).slice(0, 8)
  }, [allTags, autocompleteQuery, autocompleteType])

  const suggestions = autocompleteType === 'ref' ? searchResults : filteredTags

  // Detect [[ and ## triggers as user types
  const handleChange = (e) => {
    const newValue = e.target.value
    onChange(newValue)

    const cursorPos = e.target.selectionStart
    const textBeforeCursor = newValue.slice(0, cursorPos)

    // Check for [[ trigger
    const refMatch = textBeforeCursor.match(/\[\[([^\]]*$)/)
    if (refMatch) {
      setAutocompleteType('ref')
      setAutocompleteQuery(refMatch[1])
      setShowAutocomplete(true)
      setSelectedIndex(0)
      updateAutocompletePosition(e.target)
      return
    }

    // Check for ## trigger
    const tagMatch = textBeforeCursor.match(/##(\w*$)/)
    if (tagMatch) {
      setAutocompleteType('tag')
      setAutocompleteQuery(tagMatch[1])
      setShowAutocomplete(true)
      setSelectedIndex(0)
      updateAutocompletePosition(e.target)
      return
    }

    // No trigger found
    setShowAutocomplete(false)
    setAutocompleteType(null)
    setAutocompleteQuery('')
  }

  const updateAutocompletePosition = (el) => {
    const rect = el.getBoundingClientRect()
    setAutocompletePosition({
      top: rect.bottom + 4,
      left: rect.left,
    })
  }

  // Replace trigger text with the selected suggestion
  const selectSuggestion = (suggestion) => {
    const cursorPos = elRef.current.selectionStart
    const textBeforeCursor = value.slice(0, cursorPos)
    const textAfterCursor = value.slice(cursorPos)

    let newText, newCursorPos

    if (autocompleteType === 'ref') {
      const beforeRef = textBeforeCursor.replace(/\[\[[^\]]*$/, '')
      const refText = suggestion.content || suggestion.id
      newText = beforeRef + `[[${refText}]]` + textAfterCursor
      newCursorPos = beforeRef.length + refText.length + 4
    } else if (autocompleteType === 'tag') {
      const beforeTag = textBeforeCursor.replace(/##\w*$/, '')
      const tagName = suggestion.name
      newText = beforeTag + `##${tagName}` + textAfterCursor
      newCursorPos = beforeTag.length + tagName.length + 2
    }

    onChange(newText)
    dismissAutocomplete()

    setTimeout(() => {
      elRef.current?.focus()
      elRef.current?.setSelectionRange(newCursorPos, newCursorPos)
    }, 0)
  }

  // Create new tag/ref from the typed query text
  const createFromQuery = () => {
    if (!autocompleteQuery) return

    const cursorPos = elRef.current.selectionStart
    const textBeforeCursor = value.slice(0, cursorPos)
    const textAfterCursor = value.slice(cursorPos)

    let newText, newCursorPos

    if (autocompleteType === 'ref') {
      const beforeRef = textBeforeCursor.replace(/\[\[[^\]]*$/, '')
      newText = beforeRef + `[[${autocompleteQuery}]]` + textAfterCursor
      newCursorPos = beforeRef.length + autocompleteQuery.length + 4
    } else if (autocompleteType === 'tag') {
      const beforeTag = textBeforeCursor.replace(/##\w*$/, '')
      const normalizedTag = autocompleteQuery.toLowerCase()
      newText = beforeTag + `##${normalizedTag}` + textAfterCursor
      newCursorPos = beforeTag.length + normalizedTag.length + 2
    }

    onChange(newText)
    dismissAutocomplete()

    setTimeout(() => {
      elRef.current?.focus()
      elRef.current?.setSelectionRange(newCursorPos, newCursorPos)
    }, 0)
  }

  const dismissAutocomplete = () => {
    setShowAutocomplete(false)
    setAutocompleteType(null)
    setAutocompleteQuery('')
  }

  // Keyboard navigation in autocomplete dropdown + submit/cancel shortcuts
  const handleKeyDown = (e) => {
    // Arrow nav inside autocomplete
    if (showAutocomplete && suggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(i => Math.min(i + 1, suggestions.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(i => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        selectSuggestion(suggestions[selectedIndex])
        return
      }
    }

    // Create new from query when no matches
    if (showAutocomplete && suggestions.length === 0 && autocompleteQuery.length > 0) {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        createFromQuery()
        return
      }
    }

    // Escape: dismiss autocomplete first, then cancel
    if (e.key === 'Escape') {
      if (showAutocomplete) {
        dismissAutocomplete()
        return
      }
      onCancel?.()
      return
    }

    // Submit shortcuts (only when autocomplete is NOT open)
    if (!showAutocomplete) {
      if (inputMode === 'input' && e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        onSubmit?.()
        return
      }
      if (inputMode === 'textarea' && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        onSubmit?.()
        return
      }
    }
  }

  const sharedClassName = `w-full px-3 py-2 bg-base border border-subtle rounded-lg
    text-secondary text-sm resize-none
    shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]
    focus:outline-none focus:border-camel transition-colors`

  const El = inputMode === 'input' ? 'input' : 'textarea'

  return (
    <div className={`relative ${className}`}>
      <El
        ref={elRef}
        {...(inputMode === 'input' ? { type: 'text' } : { rows })}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={() => setTimeout(() => setShowAutocomplete(false), 150)}
        placeholder={placeholder}
        className={sharedClassName}
        autoFocus={autoFocus}
      />

      {/* Autocomplete dropdown — matches */}
      {showAutocomplete && suggestions.length > 0 && (
        <div
          className="fixed z-50 bg-surface border border-subtle rounded-lg shadow-xl max-h-48 overflow-auto"
          style={{ top: autocompletePosition.top, left: autocompletePosition.left, minWidth: '200px', maxWidth: '300px' }}
        >
          {suggestions.map((s, i) => (
            <button
              key={s.id}
              onMouseDown={(e) => { e.preventDefault(); selectSuggestion(s) }}
              className={`w-full px-3 py-2 text-left text-sm transition-colors ${
                i === selectedIndex ? 'bg-raised text-primary' : 'text-secondary hover:bg-raised/50'
              }`}
            >
              {autocompleteType === 'ref' ? (
                <span className="truncate block">{s.content}</span>
              ) : (
                <span className="flex items-center gap-2">
                  <span className="text-pink-400">##</span>
                  <span>{s.name}</span>
                  <span className="text-muted text-xs ml-auto">({s.usage_count})</span>
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Create-new option when no matches */}
      {showAutocomplete && suggestions.length === 0 && autocompleteQuery.length > 0 && (
        <div
          className="fixed z-50 bg-surface border border-subtle rounded-lg shadow-xl overflow-hidden"
          style={{ top: autocompletePosition.top, left: autocompletePosition.left, minWidth: '200px' }}
        >
          <button
            onMouseDown={(e) => { e.preventDefault(); createFromQuery() }}
            className="w-full px-3 py-2 text-left text-sm bg-raised hover:bg-elevated transition-colors flex items-center justify-between gap-2"
          >
            <span>
              {autocompleteType === 'ref' ? (
                <span className="text-blue-400">Create [[{autocompleteQuery}]]</span>
              ) : (
                <span className="text-pink-400">Create ##{autocompleteQuery.toLowerCase()}</span>
              )}
            </span>
            <span className="text-xs text-muted">Ctrl+Enter</span>
          </button>
        </div>
      )}
    </div>
  )
}
