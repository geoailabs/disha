import { useMemo, useState } from 'react'
import type { Feature } from 'geojson'
import { GeoJSONLayer, LayerStyleSpec, ClassificationMethod } from '../types'
import {
  COLOR_RAMPS,
  DEFAULT_RAMP,
  buildCategories,
  computeBreaks,
  rampColorsForClasses,
} from '../lib/classify'
import ColorPickerPopover from './ColorPickerPopover'
import './SymbologyPanel.css'

interface SymbologyPanelProps {
  layer: GeoJSONLayer
  onChange: (layerId: string, styleSpec: LayerStyleSpec) => void
  onClose: () => void
  onUpdateLayer?: (layerId: string, updates: Partial<GeoJSONLayer>) => void
}

const SEQUENTIAL_RAMPS = ['YlOrRd', 'Blues', 'Greens', 'Purples', 'Reds']

function hexToHsl(hex: string): { h: number; s: number; l: number } {
  hex = hex.replace(/^\s*#|\s*$/g, '');
  if (hex.length === 3) {
    hex = hex.replace(/(.)/g, '$1$1');
  }
  const r = parseInt(hex.substr(0, 2), 16) / 255;
  const g = parseInt(hex.substr(2, 2), 16) / 255;
  const b = parseInt(hex.substr(4, 2), 16) / 255;

  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0, l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h /= 6;
  }
  return { h: h * 360, s: s * 100, l: l * 100 };
}

function hslToHex(h: number, s: number, l: number): string {
  s /= 100;
  l /= 100;
  let c = (1 - Math.abs(2 * l - 1)) * s;
  let x = c * (1 - Math.abs((h / 60) % 2 - 1));
  let m = l - c / 2;
  let r = 0, g = 0, b = 0;

  if (0 <= h && h < 60) { r = c; g = x; b = 0; }
  else if (60 <= h && h < 120) { r = x; g = c; b = 0; }
  else if (120 <= h && h < 180) { r = 0; g = c; b = x; }
  else if (180 <= h && h < 240) { r = 0; g = x; b = c; }
  else if (240 <= h && h < 300) { r = x; g = 0; b = c; }
  else if (300 <= h && h <= 360) { r = c; g = 0; b = x; }

  const toHex = (v: number) => {
    const hex = Math.round((v + m) * 255).toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  };
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// Collect the union of property keys, and which of them are numeric, across a
// feature sample. Sampling keeps this cheap on large layers.
function inspectProperties(features: Feature[]): { all: string[]; numeric: Set<string> } {
  const all = new Set<string>()
  const numericVotes = new Map<string, { num: number; total: number }>()
  const sample = features.slice(0, 500)
  for (const f of sample) {
    const props = f.properties || {}
    for (const [k, v] of Object.entries(props)) {
      all.add(k)
      const rec = numericVotes.get(k) || { num: 0, total: 0 }
      rec.total += 1
      if (typeof v === 'number' || (v !== '' && v != null && Number.isFinite(Number(v)))) rec.num += 1
      numericVotes.set(k, rec)
    }
  }
  const numeric = new Set<string>()
  for (const [k, rec] of numericVotes) {
    if (rec.total > 0 && rec.num / rec.total >= 0.8) numeric.add(k)
  }
  return { all: [...all], numeric }
}

export default function SymbologyPanel({ layer, onChange, onClose, onUpdateLayer }: SymbologyPanelProps) {
  const features = layer.data?.features || []
  const { all: allProps, numeric: numericProps } = useMemo(
    () => inspectProperties(features),
    [features],
  )

  const spec: LayerStyleSpec = layer.styleSpec ?? { mode: 'simple' }
  const emit = (next: LayerStyleSpec) => onChange(layer.id, next)

  // Georeferenced raster overlay alignment UI branch
  if (layer.rasterOverlaySpec) {
    const { url, corners } = layer.rasterOverlaySpec

    // Calculate centroid
    const centroid = corners.reduce(
      (acc, c) => [acc[0] + c[0], acc[1] + c[1]],
      [0, 0]
    ).map((v) => v / 4) as [number, number]

    const handleOpacityChange = (val: number) => {
      onUpdateLayer?.(layer.id, { opacity: val })
    }

    const STEP = 0.0001 // ~10m delta in geographic degrees

    const handleNudge = (dx: number, dy: number) => {
      const nextCorners = corners.map((c) => [c[0] + dx, c[1] + dy] as [number, number])
      onUpdateLayer?.(layer.id, {
        rasterOverlaySpec: { url, corners: nextCorners }
      })
    }

    const handleScale = (factor: number) => {
      const nextCorners = corners.map((c) => [
        centroid[0] + (c[0] - centroid[0]) * factor,
        centroid[1] + (c[1] - centroid[1]) * factor
      ] as [number, number])
      onUpdateLayer?.(layer.id, {
        rasterOverlaySpec: { url, corners: nextCorners }
      })
    }

    const handleRotate = (angleDegrees: number) => {
      const rad = (angleDegrees * Math.PI) / 180
      const cos = Math.cos(rad)
      const sin = Math.sin(rad)
      const nextCorners = corners.map((c) => {
        const dx = c[0] - centroid[0]
        const dy = c[1] - centroid[1]
        const rx = dx * cos - dy * sin
        const ry = dx * sin + dy * cos
        return [centroid[0] + rx, centroid[1] + ry] as [number, number]
      })
      onUpdateLayer?.(layer.id, {
        rasterOverlaySpec: { url, corners: nextCorners }
      })
    }

    const handleCoordChange = (index: number, field: 'lng' | 'lat', value: string) => {
      const num = parseFloat(value)
      if (isNaN(num)) return
      const nextCorners = corners.map((c, idx) => {
        if (idx !== index) return c
        return field === 'lng' ? [num, c[1]] : [c[0], num]
      }) as [number, number][]
      onUpdateLayer?.(layer.id, {
        rasterOverlaySpec: { url, corners: nextCorners }
      })
    }

    const labels = ['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left']

    return (
      <div className="symbology-panel">
        <div className="sym-header">
          <span className="sym-title" title={layer.name}>
            {layer.name}
          </span>
        </div>

        {/* Opacity slider */}
        <div className="sym-row">
          <label className="sym-label">Opacity</label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={layer.opacity ?? 0.8}
            onChange={(e) => handleOpacityChange(parseFloat(e.target.value))}
            style={{ flex: 1 }}
          />
          <span style={{ minWidth: '32px', textAlign: 'right' }}>
            {Math.round((layer.opacity ?? 0.8) * 100)}%
          </span>
        </div>

        {/* Alignment controls */}
        <div className="sym-section-title">Manual Alignment</div>
        <div className="sym-align-grid">
          <button className="sym-nudge-btn" onClick={() => handleRotate(-0.5)} title="Rotate Counter-Clockwise">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
          </button>
          <button className="sym-nudge-btn" onClick={() => handleNudge(0, STEP)} title="Nudge Up">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="18 15 12 9 6 15"></polyline>
            </svg>
          </button>
          <button className="sym-nudge-btn" onClick={() => handleRotate(0.5)} title="Rotate Clockwise">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M21 12a9 9 0 1 1-9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
          </button>

          <button className="sym-nudge-btn" onClick={() => handleNudge(-STEP, 0)} title="Nudge Left">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="15 18 9 12 15 6"></polyline>
            </svg>
          </button>
          <div style={{ color: 'var(--text-muted)', fontSize: '11px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            Nudge
          </div>
          <button className="sym-nudge-btn" onClick={() => handleNudge(STEP, 0)} title="Nudge Right">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="9 18 15 12 9 6"></polyline>
            </svg>
          </button>

          <button className="sym-nudge-btn" onClick={() => handleScale(0.99)} title="Scale Down">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
          <button className="sym-nudge-btn" onClick={() => handleNudge(0, -STEP)} title="Nudge Down">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          <button className="sym-nudge-btn" onClick={() => handleScale(1.01)} title="Scale Up">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
        </div>

        {/* Corner coordinates view */}
        <div className="sym-section-title">Corners (Lng, Lat)</div>
        <div className="sym-coord-inputs">
          {corners.map((c, idx) => (
            <div key={idx} className="sym-coord-row">
              <span className="sym-coord-row-title">{labels[idx]}</span>
              <div className="sym-coord-row-inputs">
                <div className="sym-coord-field">
                  <span>Lng:</span>
                  <input
                    type="number"
                    step="0.000001"
                    className="sym-coord-input"
                    value={c[0]}
                    onChange={(e) => handleCoordChange(idx, 'lng', e.target.value)}
                  />
                </div>
                <div className="sym-coord-field">
                  <span>Lat:</span>
                  <input
                    type="number"
                    step="0.000001"
                    className="sym-coord-input"
                    value={c[1]}
                    onChange={(e) => handleCoordChange(idx, 'lat', e.target.value)}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const [activePicker, setActivePicker] = useState<{
    type: 'base' | 'text' | 'halo' | 'cat'
    catValue?: string
    anchorRect: DOMRect | null
    color: string
  } | null>(null)

  // ── Helpers for base color tint updates ──
  const applyBaseColorToCategorized = (baseColor: string, currentSpec: LayerStyleSpec) => {
    if (!currentSpec.categories || currentSpec.categories.length === 0) return currentSpec
    const nextCategories = currentSpec.categories.map((c, i) => {
      if (currentSpec.categories!.length === 1) {
        return { ...c, color: baseColor }
      }
      const { h, s, l } = hexToHsl(baseColor)
      const n = currentSpec.categories!.length
      const stepH = (h + (i * (360 / n))) % 360
      const stepL = Math.max(40, Math.min(70, l))
      const color = hslToHex(stepH, s, stepL)
      return { ...c, color }
    })
    return { ...currentSpec, categories: nextCategories }
  }

  const applyBaseColorToGraduated = (baseColor: string, currentSpec: LayerStyleSpec) => {
    if (!currentSpec.breaks || currentSpec.breaks.length === 0) return currentSpec
    const { h, s } = hexToHsl(baseColor)
    const n = currentSpec.breaks.length + 1
    // Step lightness from light (85%) to dark (25%)
    const rampColors = Array.from({ length: n }, (_, i) => {
      const stepL = 85 - (i * (60 / (n - 1)))
      return hslToHex(h, s, stepL)
    })
    return { ...currentSpec, rampColors }
  }

  const handleBaseColorChange = (color: string) => {
    // 1. Update global layer color values
    onUpdateLayer?.(layer.id, { color, fillColor: color, lineColor: color })

    // 2. Adjust specification accordingly depending on active styling mode
    if (spec.mode === 'simple') {
      emit({ ...spec, fillColor: color, strokeColor: color })
    } else if (spec.mode === 'categorized') {
      emit(applyBaseColorToCategorized(color, spec))
    } else if (spec.mode === 'graduated') {
      emit(applyBaseColorToGraduated(color, spec))
    }
  }

  // ── Mode ──
  const setMode = (mode: LayerStyleSpec['mode']) => {
    if (mode === 'simple') {
      emit({ mode: 'simple', opacity: spec.opacity, label: spec.label })
      return
    }
    if (mode === 'categorized') {
      const prop = spec.property && allProps.includes(spec.property) ? spec.property : allProps[0]
      recomputeCategorized(prop, spec.rampName || 'category')
      return
    }
    // graduated
    const numProp = spec.property && numericProps.has(spec.property)
      ? spec.property
      : [...numericProps][0]
    recomputeGraduated(numProp, spec.rampName || DEFAULT_RAMP, spec.breaks ? spec.breaks.length + 1 : 5, spec.classification || 'quantile')
  }

  // ── Categorized ──
  const recomputeCategorized = (property: string | undefined, rampName: string) => {
    if (!property) { emit({ ...spec, mode: 'categorized' }); return }
    const values = features.map((f) => String(f.properties?.[property] ?? ''))
    const baseCats = buildCategories(values, property, rampName)
    const seedColor = layer.color || '#3b82f6'
    const n = baseCats.length
    const categories = baseCats.map((c, i) => {
      if (baseCats.length === 1) {
        return { ...c, color: seedColor }
      }
      const { h, s, l } = hexToHsl(seedColor)
      const stepH = (h + (i * (360 / n))) % 360
      const stepL = Math.max(40, Math.min(70, l))
      return { ...c, color: hslToHex(stepH, s, stepL) }
    })
    emit({
      ...spec,
      mode: 'categorized',
      property,
      categories,
      otherColor: layer.color,
      rampName,
      breaks: undefined,
      rampColors: undefined,
    })
  }

  const setCategoryColor = (value: string, color: string) => {
    if (!spec.categories) return
    emit({
      ...spec,
      categories: spec.categories.map((c) => (c.value === value ? { ...c, color } : c)),
    })
    if (spec.categories.length === 1) {
      onUpdateLayer?.(layer.id, { color, fillColor: color, lineColor: color })
    }
  }

  // ── Graduated ──
  const recomputeGraduated = (
    property: string | undefined,
    rampName: string,
    classes: number,
    method: ClassificationMethod,
  ) => {
    if (!property) { emit({ ...spec, mode: 'graduated' }); return }
    const nums = features
      .map((f) => Number(f.properties?.[property]))
      .filter((n) => Number.isFinite(n))
    const breaks = computeBreaks(nums, classes, method)
    const seedColor = layer.color || '#3b82f6'
    const { h, s } = hexToHsl(seedColor)
    const n = breaks.length + 1
    const rampColors = Array.from({ length: n }, (_, i) => {
      const stepL = 85 - (i * (60 / (n - 1)))
      return hslToHex(h, s, stepL)
    })
    emit({
      ...spec,
      mode: 'graduated',
      property,
      breaks,
      rampColors,
      classification: method,
      rampName,
      categories: undefined,
    })
  }

  // ── Labels ──
  const setLabel = (patch: Partial<NonNullable<LayerStyleSpec['label']>>) => {
    const cur = spec.label ?? { enabled: false, property: allProps[0] || '' }
    emit({ ...spec, label: { ...cur, ...patch } })
  }

  return (
    <div className="symbology-panel">
      <div className="sym-header">
        <span className="sym-title">Symbology</span>
        
        <div className="sym-header-right">
          {spec.label?.enabled && (
            <div className="sym-header-select-wrapper">
              <span className="sym-select-icon">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="4" y1="9" x2="20" y2="9"></line>
                  <line x1="4" y1="15" x2="20" y2="15"></line>
                  <line x1="10" y1="3" x2="8" y2="21"></line>
                  <line x1="16" y1="3" x2="14" y2="21"></line>
                </svg>
              </span>
              <select
                className="sym-select sym-header-select"
                value={spec.label.property || ''}
                onChange={(e) => setLabel({ property: e.target.value })}
                title="Select label field"
              >
                {allProps.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
          )}
          
          <label className="sym-checkbox-label sym-header-checkbox">
            <input
              type="checkbox"
              checked={!!spec.label?.enabled}
              onChange={(e) => setLabel({ enabled: e.target.checked, property: spec.label?.property || allProps[0] || '' })}
            />
            <span className="custom-checkbox">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" style={{ display: spec.label?.enabled ? 'block' : 'none' }}>
                <polyline points="20 6 9 17 4 12"></polyline>
              </svg>
            </span>
            <span className="sym-checkbox-text">Labels</span>
          </label>
        </div>
      </div>

      {spec.label?.enabled && (
        <div className="sym-label-details" style={{ marginTop: '4px', marginBottom: '8px', padding: '8px', background: 'var(--bg-hover, #2e3047)', borderRadius: '6px', display: 'flex', flexDirection: 'column', gap: '8px', border: '1px solid var(--border, #3a3f58)' }}>
          <div className="sym-row" style={{ margin: 0, padding: 0, height: 'auto', border: 'none' }}>
            <label className="sym-label" style={{ fontSize: '11px' }}>Text Size</label>
            <input
              type="range"
              min="8"
              max="24"
              step="1"
              value={spec.label.size ?? 12}
              onChange={(e) => setLabel({ size: parseInt(e.target.value) })}
              style={{ flex: 1, height: '4px', cursor: 'pointer' }}
            />
            <span style={{ minWidth: '24px', textAlign: 'right', fontSize: '11px', color: 'var(--text-primary)' }}>
              {spec.label.size ?? 12}px
            </span>
          </div>
          <div className="sym-row" style={{ margin: 0, padding: 0, height: 'auto', border: 'none', justifyContent: 'flex-start', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <label className="sym-label" style={{ fontSize: '11px', margin: 0 }}>Text Color</label>
              <button
                type="button"
                className="sym-color-swatch-btn"
                style={{ backgroundColor: spec.label.color ?? '#1f2937' }}
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect()
                  setActivePicker({
                    type: 'text',
                    color: spec.label?.color ?? '#1f2937',
                    anchorRect: rect,
                  })
                }}
                title="Choose text color"
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <label className="sym-label" style={{ fontSize: '11px', margin: 0 }}>Halo Color</label>
              <button
                type="button"
                className="sym-color-swatch-btn"
                style={{ backgroundColor: spec.label.haloColor ?? '#ffffff' }}
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect()
                  setActivePicker({
                    type: 'halo',
                    color: spec.label?.haloColor ?? '#ffffff',
                    anchorRect: rect,
                  })
                }}
                title="Choose halo color"
              />
            </div>
          </div>
        </div>
      )}

      {/* Mode Selector */}
      <div className="sym-row">
        <label className="sym-label">Color by</label>
        <div className="sym-select-wrapper">
          <span className="sym-select-icon">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="12" cy="12" r="4"/>
            </svg>
          </span>
          <select
            className="sym-select"
            value={spec.mode}
            onChange={(e) => setMode(e.target.value as LayerStyleSpec['mode'])}
          >
            <option value="simple">Single Color</option>
            <option value="categorized">Category</option>
            <option value="graduated">Graduated</option>
          </select>
        </div>
      </div>

      {/* Categorized controls */}
      {spec.mode === 'categorized' && (
        <>
          <div className="sym-row">
            <label className="sym-label">Property</label>
            <div className="sym-select-wrapper">
              <span className="sym-select-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="4" y1="9" x2="20" y2="9"></line>
                  <line x1="4" y1="15" x2="20" y2="15"></line>
                  <line x1="10" y1="3" x2="8" y2="21"></line>
                  <line x1="16" y1="3" x2="14" y2="21"></line>
                </svg>
              </span>
              <select
                className="sym-select"
                value={spec.property || ''}
                onChange={(e) => recomputeCategorized(e.target.value, spec.rampName || 'category')}
              >
                {allProps.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
          </div>
          <div className="sym-categories">
            {(spec.categories || []).map((c) => (
              <div key={c.value} className="sym-cat">
                <button
                  type="button"
                  className="sym-cat-swatch-btn"
                  title="Change colour"
                  style={{ background: c.color }}
                  onClick={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect()
                    setActivePicker({
                      type: 'cat',
                      catValue: c.value,
                      color: c.color,
                      anchorRect: rect,
                    })
                  }}
                />
                <span className="sym-cat-value" title={c.value}>{c.value || '(empty)'}</span>
              </div>
            ))}
            {(spec.categories?.length ?? 0) === 0 && (
              <p className="sym-hint">No values found for this property.</p>
            )}
          </div>
        </>
      )}

      {/* Graduated controls */}
      {spec.mode === 'graduated' && (
        <>
          <div className="sym-row">
            <label className="sym-label">Property</label>
            <div className="sym-select-wrapper">
              <span className="sym-select-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="4" y1="9" x2="20" y2="9"></line>
                  <line x1="4" y1="15" x2="20" y2="15"></line>
                  <line x1="10" y1="3" x2="8" y2="21"></line>
                  <line x1="16" y1="3" x2="14" y2="21"></line>
                </svg>
              </span>
              <select
                className="sym-select"
                value={spec.property || ''}
                onChange={(e) =>
                  recomputeGraduated(
                    e.target.value, spec.rampName || DEFAULT_RAMP,
                    spec.breaks ? spec.breaks.length + 1 : 5,
                    spec.classification || 'quantile',
                  )
                }
              >
                {[...numericProps].map((p) => <option key={p} value={p}>{p}</option>)}
                {numericProps.size === 0 && <option value="">(no numeric properties)</option>}
              </select>
            </div>
          </div>
          <div className="sym-row">
            <label className="sym-label">Method</label>
            <div className="sym-select-wrapper">
              <span className="sym-select-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
              </span>
              <select
                className="sym-select"
                value={spec.classification || 'quantile'}
                onChange={(e) =>
                  recomputeGraduated(
                    spec.property, spec.rampName || DEFAULT_RAMP,
                    spec.breaks ? spec.breaks.length + 1 : 5,
                    e.target.value as ClassificationMethod,
                  )
                }
              >
                <option value="quantile">Quantile</option>
                <option value="equal-interval">Equal interval</option>
              </select>
            </div>
          </div>
          <div className="sym-row">
            <label className="sym-label">Classes</label>
            <div className="sym-select-wrapper">
              <span className="sym-select-icon">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
                </svg>
              </span>
              <select
                className="sym-select"
                value={spec.breaks ? spec.breaks.length + 1 : 5}
                onChange={(e) =>
                  recomputeGraduated(
                    spec.property, spec.rampName || DEFAULT_RAMP,
                    Number(e.target.value), spec.classification || 'quantile',
                  )
                }
              >
                {[3, 4, 5, 6, 7].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          </div>
        </>
      )}
      {/* Opacity & Stroke Controls (Vector Styling) */}
      <div className="sym-section-title" style={{ marginTop: '12px', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>Styling Options</div>
      
      {/* Opacity slider */}
      <div className="sym-row">
        <label className="sym-label">Opacity</label>
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={spec.opacity ?? layer.opacity ?? 0.8}
          onChange={(e) => emit({ ...spec, opacity: parseFloat(e.target.value) })}
          style={{ flex: 1, cursor: 'pointer' }}
        />
        <span style={{ minWidth: '32px', textAlign: 'right', fontSize: '11px' }}>
          {Math.round((spec.opacity ?? layer.opacity ?? 0.8) * 100)}%
        </span>
      </div>

      {/* Stroke Width slider */}
      <div className="sym-row">
        <label className="sym-label">Stroke Width</label>
        <input
          type="range"
          min="0"
          max="10"
          step="0.5"
          value={spec.lineWidth ?? layer.lineWidth ?? 2}
          onChange={(e) => emit({ ...spec, lineWidth: parseFloat(e.target.value) })}
          style={{ flex: 1, cursor: 'pointer' }}
        />
        <span style={{ minWidth: '32px', textAlign: 'right', fontSize: '11px' }}>
          {spec.lineWidth ?? layer.lineWidth ?? 2}px
        </span>
      </div>
      {/* Base Color & Preset Tint Swatches - ALWAYS VISIBLE in 1 single row */}
      <div className="sym-base-color-row" style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
        <div className="sym-preset-row" style={{ display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'nowrap' }}>
          {[
            '#ef4444', '#f97316', '#f59e0b', '#10b981', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899'
          ].map((hex) => {
            const activeColor = layer.color || layer.fillColor || layer.lineColor || '#3b82f6';
            const isActive = activeColor.toLowerCase() === hex.toLowerCase();
            return (
              <button
                key={hex}
                type="button"
                className={`sym-preset-dot ${isActive ? 'active' : ''}`}
                style={{
                  background: hex,
                  width: '12px',
                  height: '12px',
                  borderRadius: '50%',
                  border: isActive ? '1.5px solid var(--text-primary)' : 'none',
                  cursor: 'pointer',
                  padding: 0,
                  boxSizing: 'border-box',
                  outline: isActive ? '1px solid var(--accent)' : 'none'
                }}
                onClick={() => handleBaseColorChange(hex)}
                title={hex}
              />
            );
          })}
        </div>
        <button
          type="button"
          className="sym-color-picker-wrapper"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const curColor = layer.color || layer.fillColor || layer.lineColor || '#3b82f6'
            setActivePicker({
              type: 'base',
              color: curColor,
              anchorRect: rect,
            })
          }}
          title="Custom Color"
        >
          <span
            className="sym-color-picker-dot"
            style={{ backgroundColor: layer.color || layer.fillColor || layer.lineColor || '#3b82f6' }}
          />
          <span className="sym-color-picker-label">
            Custom
          </span>
        </button>
      </div>

      {activePicker && (
        <ColorPickerPopover
          color={activePicker.color}
          anchorRect={activePicker.anchorRect}
          onChange={(newColor) => {
            if (activePicker.type === 'base') {
              handleBaseColorChange(newColor)
            } else if (activePicker.type === 'text') {
              setLabel({ color: newColor })
            } else if (activePicker.type === 'halo') {
              setLabel({ haloColor: newColor })
            } else if (activePicker.type === 'cat' && activePicker.catValue !== undefined) {
              setCategoryColor(activePicker.catValue, newColor)
            }
          }}
          onClose={() => setActivePicker(null)}
        />
      )}
    </div>
  );
}
