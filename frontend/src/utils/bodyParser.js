/**
 * Parse body text into sub-tasks, regular lines, and completion comments.
 *
 * Sub-tasks: lines starting with [ ], [], or [x]
 * Regular lines: any other non-empty lines before the --- separator
 * Completion comments: lines after the --- separator
 *
 * Both `[ ]` and `[]` (no space) are treated as incomplete subtasks.
 * `[x]` marks a completed subtask.
 *
 * @param {string} body - The body text to parse
 * @returns {{ subTasks: Array<{text: string, completed: boolean}>, otherLines: string[], completionComments: string[] }}
 */
export function parseBodyContent(body) {
  if (!body) return { subTasks: [], otherLines: [], completionComments: [] }

  const lines = body.split('\n')
  const subTasks = []
  const otherLines = []
  const completionComments = []
  let reachedSeparator = false

  for (const line of lines) {
    const trimmed = line.trim()

    if (trimmed === '---') {
      reachedSeparator = true
      continue
    }

    if (reachedSeparator) {
      if (trimmed) completionComments.push(trimmed)
    } else if (trimmed.startsWith('[x]')) {
      subTasks.push({ text: trimmed.slice(3).trim(), completed: true })
    } else if (trimmed.startsWith('[ ]')) {
      subTasks.push({ text: trimmed.slice(3).trim(), completed: false })
    } else if (trimmed.startsWith('[]')) {
      subTasks.push({ text: trimmed.slice(2).trim(), completed: false })
    } else if (trimmed) {
      otherLines.push(trimmed)
    }
  }

  return { subTasks, otherLines, completionComments }
}
