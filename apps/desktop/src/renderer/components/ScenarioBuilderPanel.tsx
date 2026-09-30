import { useState, useEffect } from 'react'
import type { ScenarioDraft } from '../types'
import './ScenarioBuilderPanel.css'

const API = 'http://localhost:8765/api/scenarios'
const ARTIFACTS_API = 'http://localhost:8765/api/artifacts'

interface Bbox {
  south: number
  west: number
  north: number
  east: number
}

interface BaselineMetrics {
  area_km2?: number
  road_density_km_per_km2?: number | null
  transit_coverage_pct?: number | null
  green_space_pct?: number | null
  walkability_km_per_km2?: number | null
  fetch_errors?: string[]
  data_source?: string
  gis_layer_evidence?: {
    layer_evidence?: Array<{ layer: string; feature_count: number; categories: string[] }>
  }
}

interface GenerationResult {
  scenario_count: number
  scenarios: string[]
  report_markdown: string
  recommended?: string
}

interface CompareResult {
  recommended_scenario: string
  ranking: string[]
  comparison_table_markdown: string
  scoring_method: string
  disclaimer: string
  note: string
}

interface ApprovedScenario {
  name: string
  description: string
}

const DEFAULT_SCENARIO_TYPES = [
  'Baseline (Business as Usual)',
  'Compact Growth',
  'Transit-Oriented Development',
  'Green Corridor',
]

const FOCUS_AREAS = [
  { value: 'mixed',       label: 'Mixed (All Domains)' },
  { value: 'mobility',    label: 'Mobility & Transit' },
  { value: 'land_use',    label: 'Land Use & Zoning' },
  { value: 'environment', label: 'Environment & Green' },
  { value: 'zoning',      label: 'Zoning Regulations' },
]

const DEFAULT_CRITERIA = [
  'Sustainability', 'Infrastructure Cost', 'Mobility',
  'Equity', 'Economic Growth', 'Resilience',
]

interface ScenarioBuilderPanelProps {
  /** Current map bounds to pre-fill the bbox for area analysis */
  mapBounds?: { south: number; west: number; north: number; east: number } | null
  /** Called when a report is saved to Artifacts so the panel can navigate there */
  onOpenArtifacts?: () => void
  workspacePath?: string | null
  scenarioDraft?: ScenarioDraft | null
  onScenarioDraftClear?: () => void
  onScenariosCreated?: (scenarios: Array<{ name: string; description?: string }>) => void
}

export default function ScenarioBuilderPanel({ mapBounds, onOpenArtifacts, workspacePath, scenarioDraft, onScenarioDraftClear, onScenariosCreated }: ScenarioBuilderPanelProps) {
  // ── Mode toggle: Generate or Compare ──
  const [mode, setMode] = useState<'generate' | 'compare'>('generate')

  // ── Generate form ──
  const [context, setContext] = useState('')
  const [focusArea, setFocusArea] = useState('mixed')
  const [selectedTypes, setSelectedTypes] = useState<string[]>([...DEFAULT_SCENARIO_TYPES])
  const [customType, setCustomType] = useState('')
  const [showMetricToggles, setShowMetricToggles] = useState(false)
  const [metricToggles, setMetricToggles] = useState({
    road_density: true,
    transit_coverage: true,
    green_space: true,
    walkability: true,
  })

  // ── Area analysis state ──
  const [analyzing, setAnalyzing] = useState(false)
  const [baseline, setBaseline] = useState<BaselineMetrics | null>(null)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)

  // ── Generation state ──
  const [generating, setGenerating] = useState(false)
  const [genResult, setGenResult] = useState<GenerationResult | null>(null)
  const [genError, setGenError] = useState<string | null>(null)
  const [savedToArtifacts, setSavedToArtifacts] = useState(false)
  const [draftPlan, setDraftPlan] = useState<string[]>([])
  const [approvedScenarios, setApprovedScenarios] = useState<ApprovedScenario[]>([])
  const [buildingReport, setBuildingReport] = useState(false)
  const [buildError, setBuildError] = useState<string | null>(null)
  const [reportBuilt, setReportBuilt] = useState(false)

  // ── Compare form ──
  const [compareScenarios, setCompareScenarios] = useState<Array<{ name: string; description: string }>>([
    { name: 'Baseline (Business as Usual)', description: '' },
    { name: 'Transit-Oriented Development', description: '' },
  ])
  const [compareCriteria, setCompareCriteria] = useState<string[]>([...DEFAULT_CRITERIA])
  const [comparing, setComparing] = useState(false)
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null)
  const [compareError, setCompareError] = useState<string | null>(null)

  useEffect(() => {
    if (!scenarioDraft) return
    setMode('generate')
    setContext(scenarioDraft.context || '')
    setFocusArea(scenarioDraft.focus_area || 'mixed')
    setSelectedTypes((scenarioDraft.scenarios || []).map(s => s.name).filter(Boolean))
    setBaseline((scenarioDraft.baseline_metrics || null) as BaselineMetrics | null)
    setDraftPlan(scenarioDraft.plan || [])
    setApprovedScenarios((scenarioDraft.scenarios || []).map(s => ({ name: s.name, description: s.description || '' })))
    setCompareCriteria(scenarioDraft.criteria?.length ? scenarioDraft.criteria : [...DEFAULT_CRITERIA])
    setGenResult(null)
    setBuildError(null)
    setReportBuilt(false)
  }, [scenarioDraft])

  // ── Handlers ─────────────────────────────────────────────────────────────

  const toggleType = (t: string) => {
    setSelectedTypes(prev =>
      prev.includes(t) ? prev.filter(x => x !== t) : [...prev, t]
    )
  }

  const addCustomType = () => {
    const t = customType.trim()
    if (t && !selectedTypes.includes(t)) {
      setSelectedTypes(prev => [...prev, t])
    }
    setCustomType('')
  }

  const analyzeArea = async () => {
    if (!mapBounds) {
      setAnalyzeError('No map bounds available. Pan/zoom the map first.')
      return
    }
    setAnalyzing(true)
    setAnalyzeError(null)
    setBaseline(null)
    try {
      const res = await fetch(`${API}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          bbox: {
            south: mapBounds.south, west: mapBounds.west,
            north: mapBounds.north, east: mapBounds.east,
          },
          metric_toggles: metricToggles,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Analysis failed')
      setBaseline(data.baseline_metrics)
    } catch (e: any) {
      setAnalyzeError(e.message)
    } finally {
      setAnalyzing(false)
    }
  }

  const generate = async () => {
    if (!context.trim()) return
    setGenerating(true)
    setGenError(null)
    setGenResult(null)
    setSavedToArtifacts(false)
    try {
      const res = await fetch(`${API}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          context: context.trim(),
          focus_area: focusArea,
          scenario_types: selectedTypes.length ? selectedTypes : undefined,
          baseline_metrics: baseline ?? undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Generation failed')
      setGenResult(data)
      // Auto-save to artifacts
      await saveToArtifacts(data.report_markdown, `Planning Scenarios: ${context.trim().slice(0, 60)}`)
    } catch (e: any) {
      setGenError(e.message)
    } finally {
      setGenerating(false)
    }
  }

  const saveToArtifacts = async (markdown: string, title: string) => {
    try {
      const form = new FormData()
      form.append('title', title)
      form.append('artifact_type', 'report')
      form.append('format', 'markdown')
      form.append('content', markdown)
      if (workspacePath) {
        form.append('workspace', workspacePath)
      }
      const res = await fetch(`${ARTIFACTS_API}/upload`, { method: 'POST', body: form })
      if (res.ok) setSavedToArtifacts(true)
    } catch {
      // silently fail — user can still read the summary
    }
  }

  const compare = async () => {
    if (compareScenarios.length < 2) return
    setComparing(true)
    setCompareError(null)
    setCompareResult(null)
    try {
      const res = await fetch(`${API}/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenarios: compareScenarios.filter(s => s.name.trim()),
          criteria: compareCriteria,
          baseline_metrics: baseline ?? undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Comparison failed')
      setCompareResult(data)
      // Auto-save comparison table
      const md = `# Scenario Comparison\n\n${data.comparison_table_markdown}`
      await saveToArtifacts(md, 'Scenario Comparison Matrix')
    } catch (e: any) {
      setCompareError(e.message)
    } finally {
      setComparing(false)
    }
  }

  const buildApprovedReport = async () => {
    const scenarios = approvedScenarios.filter(s => s.name.trim())
    if (scenarios.length < 2) {
      setBuildError('Keep at least two scenarios to compare.')
      return
    }
    setBuildingReport(true)
    setBuildError(null)
    setReportBuilt(false)
    try {
      const res = await fetch(`${API}/build-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          context: context.trim(),
          bbox: scenarioDraft?.bbox || mapBounds || undefined,
          focus_area: focusArea,
          scenarios,
          criteria: compareCriteria,
          baseline_metrics: baseline || undefined,
          workspace: workspacePath || undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Report generation failed')
      setReportBuilt(true)
      onScenariosCreated?.(data.scenarios_data || scenarios)
      onScenarioDraftClear?.()
      onOpenArtifacts?.()
    } catch (e: any) {
      setBuildError(e.message || 'Report generation failed')
    } finally {
      setBuildingReport(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const availableCriteria = Array.from(new Set([...DEFAULT_CRITERIA, ...compareCriteria]))

  return (
    <div className="sb-panel">
      {/* Header */}
      <div className="sb-header">
        <span className="sb-title">{scenarioDraft ? 'Scenario review' : 'AI Scenario Builder'}</span>
        <div className="sb-mode-toggle">
          <button
            className={`sb-mode-btn ${mode === 'generate' ? 'active' : ''}`}
            onClick={() => setMode('generate')}
          >Generate</button>
          <button
            className={`sb-mode-btn ${mode === 'compare' ? 'active' : ''}`}
            onClick={() => setMode('compare')}
          >Compare</button>
        </div>
      </div>

      <div className={`sb-body ${scenarioDraft ? 'sb-review-mode' : ''}`}>

        {scenarioDraft && (
          <div className="sb-review-card">
            <div className="sb-review-kicker">AI planning proposal</div>
            <h3 className="sb-review-title">Review before building the report</h3>
            <p className="sb-review-context">{context}</p>
            <div className="sb-review-subtitle">Plan</div>
            <ol className="sb-review-plan">
              {draftPlan.map((step, i) => <li key={i}>{step}</li>)}
            </ol>
            <div className="sb-review-subtitle">Suggested scenarios</div>
            {scenarioDraft.preview_recommendation && (
              <div className="sb-preview-recommendation">
                <span>Preliminary best fit</span>
                <strong>{scenarioDraft.preview_recommendation}</strong>
                {scenarioDraft.preview_ranking && scenarioDraft.preview_ranking.length > 0 && (
                  <small>Ranking: {scenarioDraft.preview_ranking.join(' → ')}</small>
                )}
              </div>
            )}
            {scenarioDraft.preview_error && <div className="sb-disclaimer">Preliminary scoring will be completed when you accept the plan: {scenarioDraft.preview_error}</div>}
            <div className="sb-review-scenarios">
              {approvedScenarios.map((scenario, i) => (
                <div className="sb-review-scenario" key={`${scenario.name}-${i}`}>
                  <div className="sb-review-scenario-head">
                    <input
                      className="sb-input"
                      value={scenario.name}
                      aria-label={`Scenario ${i + 1} name`}
                      onChange={e => setApprovedScenarios(prev => prev.map((s, idx) => idx === i ? { ...s, name: e.target.value } : s))}
                    />
                    {approvedScenarios.length > 2 && (
                      <button className="sb-remove-type" onClick={() => setApprovedScenarios(prev => prev.filter((_, idx) => idx !== i))}>×</button>
                    )}
                  </div>
                  <textarea
                    className="sb-textarea sb-review-description"
                    rows={2}
                    value={scenario.description}
                    aria-label={`${scenario.name} description`}
                    onChange={e => setApprovedScenarios(prev => prev.map((s, idx) => idx === i ? { ...s, description: e.target.value } : s))}
                  />
                </div>
              ))}
            </div>
            <button
              className="sb-add-scenario-btn"
              onClick={() => setApprovedScenarios(prev => [...prev, { name: 'New scenario', description: '' }])}
            >+ Add scenario</button>

            <div className="sb-review-subtitle">Score against</div>
            <div className="sb-criteria-grid">
              {availableCriteria.map((c, i) => (
                <label key={`${c}-${i}`} className="sb-type-row sb-criterion-row">
                  <input
                    type="checkbox"
                    checked={compareCriteria.includes(c)}
                    onChange={() => setCompareCriteria(prev => prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c])}
                  />
                  {!DEFAULT_CRITERIA.includes(c) ? (
                    <input
                      className="sb-input sb-criterion-input"
                      value={c}
                      aria-label={`Criterion ${i + 1}`}
                      onChange={e => setCompareCriteria(prev => prev.map(item => item === c ? e.target.value : item))}
                    />
                  ) : <span>{c}</span>}
                </label>
              ))}
            </div>
            <button
              className="sb-add-scenario-btn sb-add-criterion-btn"
              onClick={() => setCompareCriteria(prev => [...prev, 'New criterion'])}
            >+ Add criterion</button>
            {baseline && <div className="sb-review-data-note">Baseline metrics loaded from the study area. CO₂ and emissions are included in the final assessment.</div>}
            {buildError && <div className="sb-error">{buildError}</div>}
            {reportBuilt && <div className="sb-success">Report created and opened in Artifacts.</div>}
            <button className="sb-approve-btn" onClick={buildApprovedReport} disabled={buildingReport || approvedScenarios.length < 2}>
              {buildingReport ? <><span className="sb-spinner" /> Building report…</> : <>✓ Accept plan &amp; build report</>}
            </button>
            <button className="sb-secondary-btn" onClick={onScenarioDraftClear}>Keep editing later</button>
          </div>
        )}

        {/* ── Area Analysis Bar (shared by both modes) ── */}
        <div className="sb-section">
          <div className="sb-section-header" onClick={() => setShowMetricToggles(v => !v)}>
            <span className="sb-section-label">Area Analysis</span>
            <span className="sb-chevron">{showMetricToggles ? '▲' : '▼'}</span>
          </div>

          {showMetricToggles && (
            <div className="sb-metric-toggles">
              {Object.entries(metricToggles).map(([key, val]) => (
                <label key={key} className="sb-toggle-row">
                  <input
                    type="checkbox"
                    checked={val}
                    onChange={() => setMetricToggles(prev => ({ ...prev, [key]: !prev[key] }))}
                  />
                  <span>{key.replace(/_/g, ' ')}</span>
                </label>
              ))}
            </div>
          )}

          <button
            className="sb-analyze-btn"
            onClick={analyzeArea}
            disabled={analyzing || !mapBounds}
            title={!mapBounds ? 'Pan/zoom the map to set bounds first' : 'Fetch real OSM data for current map view'}
          >
            {analyzing ? (
              <><span className="sb-spinner" /> Analysing…</>
            ) : (
              <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
                </svg>
                {baseline ? 'Re-analyse Area' : 'Analyse Current Map View'}
              </>
            )}
          </button>

          {analyzeError && <div className="sb-error">{analyzeError}</div>}

          {baseline && (
            <div className="sb-metrics-card">
              <div className="sb-metrics-header">
                <span className="sb-metrics-badge">OSM Real Data</span>
                <span className="sb-metrics-area">{baseline.area_km2} km²</span>
              </div>
              <div className="sb-metrics-grid">
                {baseline.road_density_km_per_km2 != null && (
                  <div className="sb-metric-item">
                    <span className="sb-metric-label">Road Density</span>
                    <span className="sb-metric-value">{baseline.road_density_km_per_km2} km/km²</span>
                  </div>
                )}
                {baseline.transit_coverage_pct != null && (
                  <div className="sb-metric-item">
                    <span className="sb-metric-label">Transit Coverage</span>
                    <span className="sb-metric-value">{baseline.transit_coverage_pct}%</span>
                  </div>
                )}
                {baseline.green_space_pct != null && (
                  <div className="sb-metric-item">
                    <span className="sb-metric-label">Green Space</span>
                    <span className="sb-metric-value">{baseline.green_space_pct}%</span>
                  </div>
                )}
                {baseline.walkability_km_per_km2 != null && (
                  <div className="sb-metric-item">
                    <span className="sb-metric-label">Walkability</span>
                    <span className="sb-metric-value">{baseline.walkability_km_per_km2} km/km²</span>
                  </div>
                )}
              </div>
              {baseline.fetch_errors && baseline.fetch_errors.length > 0 && (
                <div className="sb-metrics-warn">
                  Notice: {baseline.fetch_errors.length} metric(s) unavailable (OSM rate limit)
                </div>
              )}
              {baseline.gis_layer_evidence?.layer_evidence?.length ? (
                <div className="sb-review-data-note">
                  Active GIS evidence: {baseline.gis_layer_evidence.layer_evidence.length} mapped layer(s) included in scenario calibration.
                </div>
              ) : null}
            </div>
          )}
        </div>

        {/* ── GENERATE MODE ── */}
        {mode === 'generate' && (
          <>
            <div className="sb-section">
              <label className="sb-label">Study Area / Context</label>
              <textarea
                className="sb-textarea"
                rows={3}
                placeholder="e.g. Sector 17 Chandigarh mixed-use redevelopment focused on public space and transit"
                value={context}
                onChange={e => setContext(e.target.value)}
              />
            </div>

            <div className="sb-section">
              <label className="sb-label">Focus Area</label>
              <select className="sb-select" value={focusArea} onChange={e => setFocusArea(e.target.value)}>
                {FOCUS_AREAS.map(f => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
            </div>

            <div className="sb-section">
              <label className="sb-label">Scenario Types</label>
              <div className="sb-types-list">
                {DEFAULT_SCENARIO_TYPES.map(t => (
                  <label key={t} className="sb-type-row">
                    <input type="checkbox" checked={selectedTypes.includes(t)} onChange={() => toggleType(t)} />
                    <span>{t}</span>
                  </label>
                ))}
                {selectedTypes.filter(t => !DEFAULT_SCENARIO_TYPES.includes(t)).map(t => (
                  <label key={t} className="sb-type-row custom">
                    <input type="checkbox" checked onChange={() => toggleType(t)} />
                    <span>{t}</span>
                    <button className="sb-remove-type" onClick={() => toggleType(t)}>×</button>
                  </label>
                ))}
              </div>
              <div className="sb-custom-type-row">
                <input
                  className="sb-input"
                  placeholder="Add custom scenario type…"
                  value={customType}
                  onChange={e => setCustomType(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && addCustomType()}
                />
                <button className="sb-add-type-btn" onClick={addCustomType}>+</button>
              </div>
            </div>

            <button
              className="sb-generate-btn"
              onClick={generate}
              disabled={generating || !context.trim() || selectedTypes.length === 0}
            >
              {generating ? (
                <><span className="sb-spinner" /> Generating…</>
              ) : (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
                  </svg>
                  Generate Scenarios
                </>
              )}
            </button>

            {genError && <div className="sb-error">{genError}</div>}

            {genResult && (
              <div className="sb-result-card">
                <div className="sb-result-header">
                  <span className="sb-result-badge">
                    {genResult.scenario_count} scenarios generated
                  </span>
                  {savedToArtifacts ? (
                    <button className="sb-view-artifacts-btn" onClick={onOpenArtifacts}>
                      View in Artifacts →
                    </button>
                  ) : (
                    <span className="sb-saving-badge">Saving…</span>
                  )}
                </div>
                <div className="sb-result-scenarios">
                  {genResult.scenarios.map((s, i) => (
                    <div key={i} className="sb-result-scenario-chip">{s}</div>
                  ))}
                </div>
                {!baseline && (
                  <div className="sb-disclaimer">
                    Qualitative framework — Analyse Area first for data-anchored scores.
                  </div>
                )}
                {baseline && (
                  <div className="sb-disclaimer real-data">
                    Scenarios contextualised using real OSM data.
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* ── COMPARE MODE ── */}
        {mode === 'compare' && (
          <>
            <div className="sb-section">
              <label className="sb-label">Scenarios to Compare</label>
              {compareScenarios.map((sc, i) => (
                <div key={i} className="sb-compare-row">
                  <input
                    className="sb-input"
                    placeholder={`Scenario ${i + 1} name`}
                    value={sc.name}
                    onChange={e => setCompareScenarios(prev => prev.map((s, idx) => idx === i ? { ...s, name: e.target.value } : s))}
                  />
                  <input
                    className="sb-input"
                    placeholder="Brief description (optional)"
                    value={sc.description}
                    onChange={e => setCompareScenarios(prev => prev.map((s, idx) => idx === i ? { ...s, description: e.target.value } : s))}
                  />
                  {compareScenarios.length > 2 && (
                    <button className="sb-remove-type" onClick={() => setCompareScenarios(prev => prev.filter((_, idx) => idx !== i))}>×</button>
                  )}
                </div>
              ))}
              <button
                className="sb-add-scenario-btn"
                onClick={() => setCompareScenarios(prev => [...prev, { name: '', description: '' }])}
              >
                + Add Scenario
              </button>
            </div>

            <div className="sb-section">
              <label className="sb-label">Criteria</label>
              <div className="sb-criteria-grid">
                {DEFAULT_CRITERIA.map(c => (
                  <label key={c} className="sb-type-row">
                    <input
                      type="checkbox"
                      checked={compareCriteria.includes(c)}
                      onChange={() => setCompareCriteria(prev => prev.includes(c) ? prev.filter(x => x !== c) : [...prev, c])}
                    />
                    <span>{c}</span>
                  </label>
                ))}
              </div>
            </div>

            <button
              className="sb-generate-btn"
              onClick={compare}
              disabled={comparing || compareScenarios.filter(s => s.name.trim()).length < 2}
            >
              {comparing ? (
                <><span className="sb-spinner" /> Comparing…</>
              ) : (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
                    <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
                  </svg>
                  Compare Scenarios
                </>
              )}
            </button>

            {compareError && <div className="sb-error">{compareError}</div>}

            {compareResult && (
              <div className="sb-result-card">
                <div className="sb-result-header">
                  <span className="sb-result-badge recommended">
                    RECOMMENDED: {compareResult.recommended_scenario}
                  </span>
                  {savedToArtifacts && (
                    <button className="sb-view-artifacts-btn" onClick={onOpenArtifacts}>
                      View in Artifacts
                    </button>
                  )}
                </div>
                <div className="sb-ranking">
                  {compareResult.ranking.map((name, i) => (
                    <div key={i} className={`sb-ranking-row ${i === 0 ? 'top' : ''}`}>
                      <span className="sb-rank-num">#{i + 1}</span>
                      <span className="sb-rank-name">{name}</span>
                    </div>
                  ))}
                </div>
                <div className={`sb-disclaimer ${compareResult.scoring_method === 'real_data' ? 'real-data' : ''}`}>
                  {compareResult.disclaimer}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
