import { useState } from 'react'
import { GeoJSONLayer } from '../types'
import './ScenarioPanel.css'

export interface Scenario {
  id: string
  name: string
  description: string
  createdAt: number
  /** IDs of layers that are part of this scenario (others hidden when active) */
  layerIds: string[]
  /** Snapshot of layer visibility overrides keyed by layerId */
  layerVisibility: Record<string, boolean>
}

interface ScenarioPanelProps {
  scenarios: Scenario[]
  activeScenarioId: string | null
  layers: GeoJSONLayer[]
  onCreateScenario: (name: string, description: string) => void
  onActivate: (id: string | null) => void
  onDelete: (id: string) => void
  onRename: (id: string, name: string) => void
  onAddLayer: (scenarioId: string, layerId: string) => void
  onRemoveLayer: (scenarioId: string, layerId: string) => void
}

export default function ScenarioPanel({
  scenarios,
  activeScenarioId,
  layers,
  onCreateScenario,
  onActivate,
  onDelete,
  onRename,
  onAddLayer,
  onRemoveLayer,
}: ScenarioPanelProps) {
  const [showForm, setShowForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const handleCreate = () => {
    if (!newName.trim()) return
    onCreateScenario(newName.trim(), newDesc.trim())
    setNewName('')
    setNewDesc('')
    setShowForm(false)
  }

  return (
    <div className="scenario-panel">
      <div className="scenario-toolbar">
        <span className="scenario-title">Planning Scenarios</span>
        <button className="scenario-new-btn" onClick={() => setShowForm(v => !v)} style={{ display: 'inline-flex', alignItems: 'center' }}>
          {showForm ? (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          ) : (
            <>
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              New
            </>
          )}
        </button>
      </div>

      {showForm && (
        <div className="scenario-form">
          <input
            className="scenario-input"
            placeholder="Scenario name (e.g. Baseline 2026)"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
          />
          <textarea
            className="scenario-textarea"
            placeholder="Brief description (optional)"
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            rows={2}
          />
          <div className="scenario-form-actions">
            <button className="scenario-save-btn" onClick={handleCreate}>Create</button>
            <button className="scenario-cancel-btn" onClick={() => setShowForm(false)}>Cancel</button>
          </div>
        </div>
      )}

      {scenarios.length === 0 && !showForm && (
        <div className="scenario-empty">
          <div className="scenario-empty-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <p className="scenario-empty-title">No scenarios yet</p>
          <p className="scenario-empty-sub">
            Create scenarios to branch layer states, test zoning variations, and compare planning alternatives.
          </p>
          <button className="scenario-empty-btn" onClick={() => setShowForm(true)}>
            + Create Scenario
          </button>
        </div>
      )}

      {activeScenarioId && (
        <div className="scenario-active-bar">
          <span className="scenario-active-dot" />
          Active: <strong>{scenarios.find(s => s.id === activeScenarioId)?.name || ''}</strong>
          <button className="scenario-clear-btn" onClick={() => onActivate(null)}>
            Reset to All
          </button>
        </div>
      )}

      <div className="scenario-list">
        {scenarios.map(scenario => {
          const isActive = scenario.id === activeScenarioId
          const isExpanded = expandedId === scenario.id

          return (
            <div key={scenario.id} className={`scenario-card ${isActive ? 'active' : ''}`}>
              <div className="scenario-card-header">
                <button
                  className="scenario-expand-btn"
                  onClick={() => setExpandedId(isExpanded ? null : scenario.id)}
                  title="Expand"
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  {isExpanded ? (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                  ) : (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="9 18 15 12 9 6"></polyline>
                    </svg>
                  )}
                </button>

                {editingId === scenario.id ? (
                  <input
                    className="scenario-edit-input"
                    value={editName}
                    onChange={e => setEditName(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') { onRename(scenario.id, editName); setEditingId(null) }
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    autoFocus
                  />
                ) : (
                  <span
                    className="scenario-name"
                    onDoubleClick={() => { setEditingId(scenario.id); setEditName(scenario.name) }}
                    title="Double-click to rename"
                  >
                    {scenario.name}
                  </span>
                )}

                <div className="scenario-card-actions">
                  <button
                    className={`scenario-activate-btn ${isActive ? 'deactivate' : ''}`}
                    onClick={() => onActivate(isActive ? null : scenario.id)}
                    title={isActive ? 'Deactivate' : 'Activate this scenario'}
                    style={{ display: 'inline-flex', alignItems: 'center' }}
                  >
                    {isActive ? (
                      <>
                        <svg width="8" height="8" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                          <circle cx="12" cy="12" r="10"></circle>
                        </svg>
                        Active
                      </>
                    ) : (
                      <>
                        <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                          <circle cx="12" cy="12" r="10"></circle>
                        </svg>
                        Activate
                      </>
                    )}
                  </button>
                  <button
                    className="scenario-delete-btn"
                    onClick={() => onDelete(scenario.id)}
                    title="Delete scenario"
                    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                </div>
              </div>

              {scenario.description && (
                <p className="scenario-description">{scenario.description}</p>
              )}

              {isExpanded && (
                <div className="scenario-layers">
                  <p className="scenario-layers-title">
                    Layers in this scenario ({scenario.layerIds.length})
                  </p>
                  {layers.map(layer => {
                    const included = scenario.layerIds.includes(layer.id)
                    return (
                      <div key={layer.id} className="scenario-layer-row">
                        <span
                          className="scenario-layer-dot"
                          style={{ background: layer.color }}
                        />
                        <span className="scenario-layer-name">{layer.name}</span>
                        <button
                          className={`scenario-layer-toggle ${included ? 'remove' : 'add'}`}
                          onClick={() =>
                            included
                              ? onRemoveLayer(scenario.id, layer.id)
                              : onAddLayer(scenario.id, layer.id)
                          }
                          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                        >
                          {included ? (
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                              <line x1="5" y1="12" x2="19" y2="12"></line>
                            </svg>
                          ) : (
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                              <line x1="12" y1="5" x2="12" y2="19"></line>
                              <line x1="5" y1="12" x2="19" y2="12"></line>
                            </svg>
                          )}
                        </button>
                      </div>
                    )
                  })}
                  {layers.length === 0 && (
                    <p className="scenario-no-layers">No layers loaded yet.</p>
                  )}
                </div>
              )}

              <span className="scenario-date">
                {new Date(scenario.createdAt).toLocaleDateString()}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
