/**
 * Eval Dashboard
 * ==============
 * Internal dev tool for viewing experiment results.
 * Single-page with expandable experiment cards.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useExperiments, useExperimentDetail } from '../../hooks/useEval'

const STATUS_COLORS = {
  completed: 'bg-green-500/20 text-green-400',
  running: 'bg-yellow-500/20 text-yellow-400',
  pending: 'bg-white/10 text-white/50',
  failed: 'bg-red-500/20 text-red-400',
}

/** Format a number as percentage (0-100%) */
function pct(val) {
  if (val == null) return '—'
  return `${(val * 100).toFixed(0)}%`
}

/** Format a score (1-5 scale) */
function score(val) {
  if (val == null) return '—'
  return val.toFixed(2)
}

/** Tiny 4px bar for fidelity percentages */
function FidelityBar({ value }) {
  if (value == null) return null
  const width = Math.min(value * 100, 100)
  return (
    <div className="w-16 h-1 bg-camel/20 rounded-full mt-0.5">
      <div
        className="h-full bg-camel rounded-full"
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

/** 5-dot indicator for judge scores (1-5) */
function ScoreDots({ value }) {
  if (value == null) return null
  const filled = Math.round(value)
  return (
    <div className="flex gap-0.5 mt-0.5">
      {[1, 2, 3, 4, 5].map(i => (
        <div
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${
            i <= filled ? 'bg-camel' : 'bg-white/10'
          }`}
        />
      ))}
    </div>
  )
}

/** Compute rankings from configs, judgments, fidelity */
function Rankings({ configs, judgments, fidelity }) {
  const parts = []

  // Best quality (highest mean judge score)
  if (judgments.length > 0) {
    const best = [...judgments].sort((a, b) => (b.mean ?? 0) - (a.mean ?? 0))[0]
    if (best.mean != null) {
      parts.push(`Best quality: ${best.config_name} (${best.mean.toFixed(2)})`)
    }
  }

  // Best fidelity (highest composite)
  if (fidelity.length > 0) {
    const best = [...fidelity].sort((a, b) => (b.composite ?? 0) - (a.composite ?? 0))[0]
    if (best.composite != null) {
      parts.push(`Best fidelity: ${best.config_name} (${pct(best.composite)})`)
    }
  }

  // Cheapest
  if (configs.length > 0) {
    const cheapest = [...configs]
      .filter(c => c.avg_cost != null)
      .sort((a, b) => a.avg_cost - b.avg_cost)[0]
    if (cheapest) {
      parts.push(`Cheapest: ${cheapest.name} ($${cheapest.avg_cost.toFixed(2)})`)
    }
  }

  if (parts.length === 0) return null
  return (
    <div className="text-xs text-white/40 mt-3 flex flex-wrap gap-x-4 gap-y-1">
      {parts.map((p, i) => <span key={i}>{p}</span>)}
    </div>
  )
}

/** Expanded detail for a single experiment */
function ExperimentDetail({ id }) {
  const { data, isLoading, error } = useExperimentDetail(id)

  if (isLoading) return <div className="text-white/30 text-sm py-4">Loading...</div>
  if (error) return <div className="text-red-400 text-sm py-4">Error: {error.message}</div>
  if (!data) return null

  const { configs, judgments, fidelity } = data

  return (
    <div className="mt-3 space-y-4">
      {/* Config Summary */}
      <section>
        <h4 className="label mb-2">Config Summary</h4>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-white/40 text-xs uppercase tracking-wider">
                <th className="text-left py-1 pr-4">Config</th>
                <th className="text-left py-1 pr-4">Orchestrator</th>
                <th className="text-right py-1 pr-4">Runs</th>
                <th className="text-right py-1 pr-4">Avg Cost</th>
                <th className="text-right py-1 pr-4">Avg Iters</th>
                <th className="text-right py-1 pr-4">Avg Sub</th>
                <th className="text-right py-1">Avg Dur</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {configs.map((c, i) => (
                <tr key={c.name} className={i % 2 === 1 ? 'bg-white/[0.02]' : ''}>
                  <td className="py-1 pr-4 text-white/80">{c.name}</td>
                  <td className="py-1 pr-4 text-white/50">{c.orchestrator_model}</td>
                  <td className="text-right py-1 pr-4">{c.completed}/{c.run_count}</td>
                  <td className="text-right py-1 pr-4">{c.avg_cost != null ? `$${c.avg_cost.toFixed(2)}` : '—'}</td>
                  <td className="text-right py-1 pr-4">{c.avg_iterations ?? '—'}</td>
                  <td className="text-right py-1 pr-4">{c.avg_sub_llm ?? '—'}</td>
                  <td className="text-right py-1">{c.avg_duration != null ? `${c.avg_duration}s` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Score Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* LLM Judge Scores */}
        <section className="bg-raised/50 rounded-lg p-3">
          <h4 className="label mb-2">LLM Judge (1–5)</h4>
          {judgments.length === 0 ? (
            <p className="text-white/30 text-xs">No judgments yet. Run: python -m eval judge {id}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-white/40 text-xs uppercase tracking-wider">
                  <th className="text-left py-1 pr-3">Config</th>
                  <th className="text-right py-1 pr-3">Comp</th>
                  <th className="text-right py-1 pr-3">Coher</th>
                  <th className="text-right py-1 pr-3">Relev</th>
                  <th className="text-right py-1 pr-3">Qual</th>
                  <th className="text-right py-1">Mean</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {judgments.map((j, i) => (
                  <tr key={j.config_name} className={i % 2 === 1 ? 'bg-white/[0.02]' : ''}>
                    <td className="py-1 pr-3 text-white/80">{j.config_name}</td>
                    <td className="text-right py-1 pr-3">
                      <div>{score(j.avg_completeness)}</div>
                      <ScoreDots value={j.avg_completeness} />
                    </td>
                    <td className="text-right py-1 pr-3">
                      <div>{score(j.avg_coherence)}</div>
                      <ScoreDots value={j.avg_coherence} />
                    </td>
                    <td className="text-right py-1 pr-3">
                      <div>{score(j.avg_relevance)}</div>
                      <ScoreDots value={j.avg_relevance} />
                    </td>
                    <td className="text-right py-1 pr-3">
                      <div>{score(j.avg_scholarly_quality)}</div>
                      <ScoreDots value={j.avg_scholarly_quality} />
                    </td>
                    <td className="text-right py-1 font-semibold text-camel">
                      <div>{score(j.mean)}</div>
                      <ScoreDots value={j.mean} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Fidelity Checks */}
        <section className="bg-raised/50 rounded-lg p-3">
          <h4 className="label mb-2">Fidelity (0–100%)</h4>
          {fidelity.length === 0 ? (
            <p className="text-white/30 text-xs">No fidelity checks yet. Run: python -m eval fidelity {id}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-white/40 text-xs uppercase tracking-wider">
                  <th className="text-left py-1 pr-3">Config</th>
                  <th className="text-right py-1 pr-3">Quote</th>
                  <th className="text-right py-1 pr-3">Page</th>
                  <th className="text-right py-1 pr-3">Attr</th>
                  <th className="text-right py-1 pr-3">Synth</th>
                  <th className="text-right py-1 pr-3">Comp</th>
                  <th className="text-right py-1">N</th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {fidelity.map((f, i) => (
                  <tr key={f.config_name} className={i % 2 === 1 ? 'bg-white/[0.02]' : ''}>
                    <td className="py-1 pr-3 text-white/80">{f.config_name}</td>
                    <td className="text-right py-1 pr-3">
                      <div>{pct(f.avg_quote)}</div>
                      <FidelityBar value={f.avg_quote} />
                    </td>
                    <td className="text-right py-1 pr-3">
                      <div>{pct(f.avg_page)}</div>
                      <FidelityBar value={f.avg_page} />
                    </td>
                    <td className="text-right py-1 pr-3">
                      <div>{pct(f.avg_attribution)}</div>
                      <FidelityBar value={f.avg_attribution} />
                    </td>
                    <td className="text-right py-1 pr-3">
                      <div>{pct(f.avg_synthesis)}</div>
                      <FidelityBar value={f.avg_synthesis} />
                    </td>
                    <td className="text-right py-1 pr-3 font-semibold text-camel">
                      <div>{pct(f.composite)}</div>
                      <FidelityBar value={f.composite} />
                    </td>
                    <td className="text-right py-1 text-white/40">{f.check_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      {/* Rankings */}
      <Rankings configs={configs} judgments={judgments} fidelity={fidelity} />
    </div>
  )
}

/** Single experiment card (collapsed or expanded) */
function ExperimentCard({ exp, isExpanded, onToggle }) {
  return (
    <div
      className={`bg-surface border rounded-lg transition-colors ${
        isExpanded ? 'border-camel/30' : 'border-white/5 hover:border-white/10'
      }`}
    >
      {/* Collapsed row — always visible */}
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex items-center gap-4 cursor-pointer"
      >
        <span className="font-mono text-white/40 text-sm w-10 shrink-0">
          [{String(exp.id).padStart(3, '0')}]
        </span>
        <span className="text-white/90 font-medium flex-1 truncate">
          {exp.name}
        </span>
        <span className={`text-xs rounded-full px-2 py-0.5 ${STATUS_COLORS[exp.status] || STATUS_COLORS.pending}`}>
          {exp.status}
        </span>
        <span className="text-sm text-white/50 font-mono w-24 text-right shrink-0">
          {exp.completed_count}/{exp.run_count} runs
        </span>
        <span className="text-sm text-white/50 font-mono w-32 text-right shrink-0">
          ${exp.total_cost_usd.toFixed(2)} / ${exp.max_cost_usd.toFixed(2)}
        </span>
        <svg
          className={`w-4 h-4 text-white/30 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Expanded detail */}
      {isExpanded && (
        <div className="px-4 pb-4 border-t border-white/5">
          {exp.description && (
            <p className="text-white/40 text-sm mt-2 mb-1">{exp.description}</p>
          )}
          <ExperimentDetail id={exp.id} />
        </div>
      )}
    </div>
  )
}

export default function EvalDashboard() {
  const navigate = useNavigate()
  const { data: experiments, isLoading, error } = useExperiments()
  const [expandedId, setExpandedId] = useState(null)

  return (
    <div className="min-h-screen bg-base text-white">
      <div className="max-w-6xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <button
            onClick={() => navigate('/')}
            className="text-white/40 hover:text-white/70 transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h1 className="text-xl font-semibold tracking-tight">Eval Dashboard</h1>
        </div>

        {/* Content */}
        {isLoading && (
          <div className="text-white/30">Loading experiments...</div>
        )}
        {error && (
          <div className="text-red-400">
            Failed to load experiments: {error.message}
          </div>
        )}
        {experiments && experiments.length === 0 && (
          <div className="text-white/30">
            No experiments found. Run one with: python -m eval run &lt;yaml&gt;
          </div>
        )}
        {experiments && experiments.length > 0 && (
          <div className="space-y-2">
            {experiments.map(exp => (
              <ExperimentCard
                key={exp.id}
                exp={exp}
                isExpanded={expandedId === exp.id}
                onToggle={() => setExpandedId(expandedId === exp.id ? null : exp.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
