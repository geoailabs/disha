import React, { useState } from 'react'
import type { BoundaryGeometry } from '../types'
import './SpatialClipModal.css'

interface NominatimResult {
  place_id: number
  display_name: string
  type: string
  osm_type: string
  geojson: {
    type: string
    coordinates: any
  }
}

interface SpatialClipModalProps {
  isOpen: boolean
  onClose: () => void
  layersCount: number
  onExportClippedRegion: (name: string) => void
  onPreviewBoundary: (geom: BoundaryGeometry | null) => void
  onSaveByRegion: (displayName: string, boundaryGeom: BoundaryGeometry) => void
}

export const SpatialClipModal: React.FC<SpatialClipModalProps> = ({
  isOpen,
  onClose,
  layersCount,
  onExportClippedRegion,
  onPreviewBoundary,
  onSaveByRegion,
}) => {
  const [activeMode, setActiveMode] = useState<'extent' | 'boundary'>('extent')
  const [extentName, setExtentName] = useState('clipped-study-area')
  const [regionQuery, setRegionQuery] = useState('')
  const [regionResults, setRegionResults] = useState<NominatimResult[]>([])
  const [selectedRegion, setSelectedRegion] = useState<NominatimResult | null>(null)
  const [regionSearching, setRegionSearching] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)

  if (!isOpen) return null

  const handleExtentSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const name = extentName.trim() || 'clipped-study-area'
    onExportClippedRegion(name)
    setFeedback(`Clipped ${layersCount} layers to current map viewport!`)
    setTimeout(() => {
      onClose()
      setFeedback(null)
    }, 1000)
  }

  const searchRegion = async () => {
    if (!regionQuery.trim()) return
    setRegionSearching(true)
    setRegionResults([])
    setSelectedRegion(null)
    onPreviewBoundary(null)
    try {
      const resp = await fetch(
        `http://localhost:8765/api/geocode?query=${encodeURIComponent(regionQuery)}&polygon_geojson=1&limit=6`
      )
      const json = await resp.json()
      const results: NominatimResult[] = json.results || []
      const polygons = results.filter(
        (r) => r.geojson && ['Polygon', 'MultiPolygon'].includes(r.geojson.type)
      )
      setRegionResults(polygons)
    } catch {
      setRegionResults([])
    } finally {
      setRegionSearching(false)
    }
  }

  const selectRegion = (r: NominatimResult) => {
    setSelectedRegion(r)
    if (r.geojson.type === 'Polygon' || r.geojson.type === 'MultiPolygon') {
      onPreviewBoundary(r.geojson as BoundaryGeometry)
    }
  }

  const clearRegion = () => {
    setSelectedRegion(null)
    setRegionResults([])
    setRegionQuery('')
    onPreviewBoundary(null)
  }

  const handleSaveBoundary = () => {
    if (!selectedRegion) return
    if (selectedRegion.geojson.type !== 'Polygon' && selectedRegion.geojson.type !== 'MultiPolygon') return
    const cleanName = regionQuery.replace(/[^a-z0-9-_ ]/gi, '').trim() || 'region'
    onSaveByRegion(cleanName, selectedRegion.geojson as BoundaryGeometry)
    setFeedback(`Clipped ${layersCount} layers to boundary of ${selectedRegion.display_name.slice(0, 30)}!`)
    setTimeout(() => {
      onClose()
      setFeedback(null)
    }, 1000)
  }

  return (
    <div className="spatial-clip-modal-backdrop" onClick={onClose}>
      <div className="spatial-clip-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="scm-header">
          <div className="scm-title-group">
            <span className="scm-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <circle cx="6" cy="6" r="3" />
                <circle cx="6" cy="18" r="3" />
                <line x1="20" y1="4" x2="8.12" y2="15.88" />
                <line x1="14.47" y1="14.48" x2="20" y2="20" />
                <line x1="8.12" y1="8.12" x2="12" y2="12" />
              </svg>
            </span>
            <div>
              <h3 className="scm-heading">Clip Spatial Layers</h3>
              <p className="scm-subheading">
                Filter and extract all {layersCount} vector layers to a specific geographic study area.
              </p>
            </div>
          </div>
          <button type="button" className="scm-close-btn" onClick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Mode Selector */}
        <div className="scm-mode-tabs">
          <button
            type="button"
            className={`scm-mode-btn ${activeMode === 'extent' ? 'active' : ''}`}
            onClick={() => { setActiveMode('extent'); clearRegion() }}
          >
            Current Map Viewport
          </button>
          <button
            type="button"
            className={`scm-mode-btn ${activeMode === 'boundary' ? 'active' : ''}`}
            onClick={() => setActiveMode('boundary')}
          >
            City / Admin Boundary
          </button>
        </div>

        {/* Extent Clip Mode */}
        {activeMode === 'extent' && (
          <form className="scm-section" onSubmit={handleExtentSubmit}>
            <label className="scm-label">Output Layer Base Name</label>
            <input
              type="text"
              className="scm-input"
              placeholder="e.g. downtown_study_area"
              value={extentName}
              onChange={(e) => setExtentName(e.target.value)}
              disabled={layersCount === 0}
              autoFocus
            />
            <p className="scm-hint">
              Spatially clips all features outside your current map camera view and adds the result as a new clipped layer in your library.
            </p>
            <button
              type="submit"
              className="scm-btn scm-btn-primary"
              disabled={layersCount === 0}
            >
              Clip to Visible Extent
            </button>
          </form>
        )}

        {/* Admin Boundary Clip Mode */}
        {activeMode === 'boundary' && (
          <div className="scm-section">
            <label className="scm-label">Search Administrative Boundary</label>
            <div className="scm-search-row">
              <input
                type="text"
                className="scm-input"
                placeholder="e.g. Mumbai, Manhattan, Bangalore"
                value={regionQuery}
                onChange={(e) => setRegionQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && searchRegion()}
                autoFocus
              />
              <button
                type="button"
                className="scm-search-btn"
                onClick={searchRegion}
                disabled={regionSearching || !regionQuery.trim()}
              >
                {regionSearching ? '...' : 'Search'}
              </button>
            </div>

            {regionResults.length > 0 && !selectedRegion && (
              <ul className="scm-results-list">
                {regionResults.map((r, i) => (
                  <li key={i}>
                    <button
                      type="button"
                      className="scm-result-item"
                      onClick={() => selectRegion(r)}
                      title={`${r.type} · ${r.osm_type}`}
                    >
                      <span className="scm-result-badge">{r.type || 'boundary'}</span>
                      <span className="scm-result-name">{r.display_name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {selectedRegion && (
              <div className="scm-selected-region">
                <div className="scm-sr-info">
                  <span className="scm-sr-label">Selected Boundary:</span>
                  <span className="scm-sr-name" title={selectedRegion.display_name}>
                    {selectedRegion.display_name.slice(0, 60)}…
                  </span>
                </div>
                <div className="scm-sr-actions">
                  <button
                    type="button"
                    className="scm-btn scm-btn-primary"
                    disabled={layersCount === 0}
                    onClick={handleSaveBoundary}
                  >
                    Clip Layers to Boundary
                  </button>
                  <button
                    type="button"
                    className="scm-btn scm-btn-secondary"
                    onClick={clearRegion}
                  >
                    Clear
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {feedback && (
          <div className="scm-feedback">
            <span>✓ {feedback}</span>
          </div>
        )}
      </div>
    </div>
  )
}
export default SpatialClipModal
