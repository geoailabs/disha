import { useMemo, useState } from 'react'
import type { Feature, FeatureCollection } from 'geojson'
import { GeoJSONLayer, SelectedFeatureEntry } from '../types'
import './AttributeTable.css'

interface AttributeTableProps {
  layer: GeoJSONLayer
  onChange: (layerId: string, data: FeatureCollection) => void
  onClose: () => void
  selectedFeatures: SelectedFeatureEntry[]
  onSelectFeature: (entry: SelectedFeatureEntry | null, shiftKey: boolean) => void
  onExportFeatures?: (features: Feature[], options?: { saveAs?: boolean; promoteToLayer?: boolean; layerName?: string }) => void
}

// Properties that drive rendering/labels — editable, but we surface them; the
// internal source tag is hidden from the grid.
const HIDDEN_PROPS = new Set(['source'])

function columnsOf(features: Feature[]): string[] {
  const cols = new Set<string>()
  for (const f of features) {
    for (const k of Object.keys(f.properties || {})) {
      if (!HIDDEN_PROPS.has(k)) cols.add(k)
    }
  }
  return [...cols]
}

export default function AttributeTable({
  layer,
  onChange,
  onClose,
  selectedFeatures,
  onSelectFeature,
  onExportFeatures,
}: AttributeTableProps) {
  const features = useMemo(() => layer.data?.features || [], [layer.data])
  const columns = useMemo(() => columnsOf(features), [features])
  const [newCol, setNewCol] = useState('')

  const commit = (nextFeatures: Feature[]) => {
    onChange(layer.id, { type: 'FeatureCollection', features: nextFeatures })
  }

  const setCell = (rowIdx: number, col: string, value: string) => {
    commit(
      features.map((f, i) =>
        i === rowIdx ? { ...f, properties: { ...(f.properties || {}), [col]: value } } : f,
      ),
    )
  }

  const addColumn = () => {
    const name = newCol.trim()
    if (!name || columns.includes(name)) return
    commit(
      features.map((f) => ({ ...f, properties: { ...(f.properties || {}), [name]: '' } })),
    )
    setNewCol('')
  }

  const deleteColumn = (col: string) => {
    commit(
      features.map((f) => {
        const props = { ...(f.properties || {}) }
        delete props[col]
        return { ...f, properties: props }
      }),
    )
  }

  const deleteRow = (rowIdx: number) => {
    commit(features.filter((_, i) => i !== rowIdx))
  }

  const selectedEntries = useMemo(
    () => selectedFeatures.filter((e) => e.layerId === layer.id),
    [selectedFeatures, layer.id],
  )
  const selectedCount = selectedEntries.length

  if (features.length === 0) {
    return (
      <div className="attr-table">
        <div className="attr-header">
          <div className="attr-title-group">
            <span className="attr-title">Attributes: {layer.name}</span>
            <span className="attr-count-badge">0 features</span>
          </div>
          {onClose && (
            <button className="attr-close-btn" onClick={onClose} title="Close attribute table">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
        <p className="attr-empty">This layer has no features.</p>
      </div>
    )
  }

  return (
    <div className="attr-table">
      <div className="attr-header">
        <div className="attr-title-group">
          <span className="attr-title">Attributes: {layer.name}</span>
          <span className="attr-count-badge">
            {features.length} {features.length === 1 ? 'feature' : 'features'}
            {selectedCount > 0 ? ` (${selectedCount} selected)` : ''}
          </span>
        </div>
        <div className="attr-header-actions">
          {selectedCount > 0 && onExportFeatures && (
            <button
              type="button"
              className="attr-btn attr-header-btn attr-export-btn"
              onClick={() => {
                const targetFeatures = selectedEntries.map((e) => e.feature).filter(Boolean)
                onExportFeatures(targetFeatures, { saveAs: false })
              }}
              title="Export selected features as GeoJSON"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 4 }}>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Export Selected ({selectedCount})
            </button>
          )}
          <div className="attr-header-addcol">
            <input
              className="attr-input attr-header-input"
              placeholder="New column (e.g. zone_code)"
              value={newCol}
              onChange={(e) => setNewCol(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && addColumn()}
            />
            <button className="attr-btn attr-header-btn" onClick={addColumn} disabled={!newCol.trim()}>
              + Add
            </button>
          </div>
          {onClose && (
            <button className="attr-close-btn" onClick={onClose} title="Close attribute table">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="attr-scroll">
        <table>
          <thead>
            <tr>
              <th className="attr-rownum">#</th>
              {columns.map((c) => (
                <th key={c}>
                  <div className="attr-th-content">
                    <span className="attr-colname" title={c}>{c}</span>
                    <button
                      className="attr-coldel"
                      onClick={() => deleteColumn(c)}
                      title={`Delete column "${c}"`}
                    >
                      ×
                    </button>
                  </div>
                </th>
              ))}
              <th className="attr-rowdel-h" />
            </tr>
          </thead>
          <tbody>
            {features.map((f, rowIdx) => {
              const isSelected = selectedFeatures.some(
                (e) =>
                  e.layerId === layer.id &&
                  (e.feature.id === f.id ||
                    (e.feature.properties?.name && e.feature.properties.name === f.properties?.name) ||
                    JSON.stringify(e.feature.geometry) === JSON.stringify(f.geometry)),
              )

              return (
                <tr
                  key={rowIdx}
                  className={`attr-row-tr ${isSelected ? 'selected' : ''}`}
                  onClick={(e) => {
                    const target = e.target as HTMLElement
                    if (target.closest('button') || target.closest('input')) return
                    onSelectFeature({ feature: f, layerId: layer.id }, e.shiftKey)
                  }}
                >
                  <td className="attr-rownum">{rowIdx + 1}</td>
                  {columns.map((c) => (
                    <td key={c}>
                      <input
                        className="attr-cell"
                        value={String(f.properties?.[c] ?? '')}
                        onChange={(e) => setCell(rowIdx, c, e.target.value)}
                      />
                    </td>
                  ))}
                  <td>
                    <button
                      className="attr-rowdel"
                      onClick={() => deleteRow(rowIdx)}
                      title="Delete feature"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                      </svg>
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="attr-footer-info">
        <span>{columns.length} columns • {features.length} features</span>
        {selectedCount > 0 && <span className="attr-footer-selected">{selectedCount} selected</span>}
      </div>
    </div>
  )
}
