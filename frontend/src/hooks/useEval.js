/**
 * Eval Dashboard Hooks
 * ====================
 * React Query hooks for eval experiment data.
 */

import { useQuery } from '@tanstack/react-query'
import { apiFetch } from '../utils/api'

/** Fetch all experiments with summary stats */
export function useExperiments() {
  return useQuery({
    queryKey: ['eval', 'experiments'],
    queryFn: () => apiFetch('/eval/experiments'),
  })
}

/** Fetch full detail for a single experiment (configs, judgments, fidelity) */
export function useExperimentDetail(id) {
  return useQuery({
    queryKey: ['eval', 'experiments', id],
    queryFn: () => apiFetch(`/eval/experiments/${id}`),
    enabled: !!id,
  })
}
