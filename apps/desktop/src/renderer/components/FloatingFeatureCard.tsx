import React, { useState } from 'react'
import { SelectedFeatureEntry } from '../types'
import './FloatingFeatureCard.css'

interface FloatingFeatureCardProps {
  selectedFeatures: SelectedFeatureEntry[]
  onClear: () => void
  onZoomTo: (entry: SelectedFeatureEntry) => void
  onExport?: (feature: any) => void
  onDeselectIndex?: (index: number) => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export const FloatingFeatureCard: React.FC<FloatingFeatureCardProps> = ({
  selectedFeatures,
  onClear,
  onZoomTo,
  onExport,
  onMouseEnter,
  onMouseLeave,
}) => {
  const [activeIdx, setActiveIdx] = useState(0)

  if (selectedFeatures.length === 0) return null

  const current = selectedFeatures[Math.min(activeIdx, selectedFeatures.length - 1)]
  const props = current.feature?.properties || {}
  const title = props.name || props.layer_name || props.title || current.layerName || 'Selected Feature'
  const entries = Object.entries(props).filter(([k]) => k !== 'source')

  return (
    <div
      className="floating-feature-card"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="ffc-header">
        <div className="ffc-title-group">
          <span className="ffc-icon">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="10" />
              <line x1="22" y1="12" x2="18" y2="12" />
              <line x1="6" y1="12" x2="2" y2="12" />
              <line x1="12" y1="6" x2="12" y2="2" />
              <line x1="12" y1="22" x2="12" y2="18" />
            </svg>
          </span>
          <div className="ffc-titles">
            <span className="ffc-name" title={String(title)}>{String(title)}</span>
            <span className="ffc-layer">{current.layerName || 'Layer Feature'}</span>
          </div>
        </div>

        <div className="ffc-actions">
          {selectedFeatures.length > 1 && (
            <div className="ffc-nav">
              <button
                className="ffc-nav-btn"
                disabled={activeIdx === 0}
                onClick={() => setActiveIdx((i) => Math.max(0, i - 1))}
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <span className="ffc-nav-count">
                {activeIdx + 1}/{selectedFeatures.length}
              </span>
              <button
                className="ffc-nav-btn"
                disabled={activeIdx === selectedFeatures.length - 1}
                onClick={() => setActiveIdx((i) => Math.min(selectedFeatures.length - 1, i + 1))}
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            </div>
          )}

          {onExport && (
            <button
              className="ffc-btn"
              onClick={() => onExport(current.feature)}
              title="Export feature as GeoJSON"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
            </button>
          )}

          <button
            className="ffc-btn"
            onClick={() => onZoomTo(current)}
            title="Zoom to feature"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
              <line x1="11" y1="8" x2="11" y2="14" />
              <line x1="8" y1="11" x2="14" y2="11" />
            </svg>
          </button>

          <button
            className="ffc-btn ffc-close"
            onClick={onClear}
            title="Deselect feature"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="ffc-body">
        {entries.length === 0 ? (
          <p className="ffc-empty">No properties attached to this feature.</p>
        ) : (
          <table className="ffc-table">
            <thead>
              <tr>
                <th>Attribute</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([key, val]) => (
                <tr key={key}>
                  <td className="ffc-key" title={key}>{key}</td>
                  <td className="ffc-val" title={String(val)}>{String(val ?? 'null')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
