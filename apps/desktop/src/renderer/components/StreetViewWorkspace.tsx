import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Geometry } from 'geojson'
import './StreetViewWorkspace.css'

export interface StreetViewTarget {
  lng: number
  lat: number
  label?: string
}

export interface RoadInspectionTarget {
  geometry: Geometry
  name?: string
}

interface StreetViewMeta {
  found: boolean
  pano_id?: string | null
  lat?: number | null
  lon?: number | null
  date?: string | null
  heading?: number | null
  address?: string | null
  access_token?: string
  error?: string
  is_pano?: boolean | null
}

interface RoadSamplePoint {
  id: string
  distance_m: number
  lat: number
  lng: number
}

interface StreetViewArtifactResult {
  found: boolean
  metadata?: StreetViewMeta
  artifact?: {
    id: number
    title: string
    meta: string | null
  }
  artifact_id?: number
  download_url?: string
  error?: string
}

interface GalleryItem {
  point: RoadSamplePoint
  status: 'pending' | 'loading' | 'done' | 'missing' | 'error'
  selected: boolean
  artifactId?: number
  imageUrl?: string
  address?: string | null
  captureDate?: string | null
  notes: string
  error?: string
}

interface StreetViewWorkspaceProps {
  target: StreetViewTarget | null
  roadTarget: RoadInspectionTarget | null
  onArtifactsChanged?: () => void
  onClose?: () => void
  layout?: 'split' | 'full'
  onLayoutChange?: (layout: 'split' | 'full') => void
  onYawChange?: (bearing: number) => void
  onLocationChange?: (loc: { lat: number; lng: number }) => void
  workspacePath: string | null
}

const API = 'http://localhost:8765/api/streetview'
const ARTIFACT_API = 'http://localhost:8765/api/artifacts'

function coordinateLabel(lat?: number | null, lng?: number | null): string {
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return 'Unknown coordinates'
  return `${Number(lat).toFixed(5)}, ${Number(lng).toFixed(5)}`
}

function captionFromMeta(meta: StreetViewMeta | null): string {
  const address = meta?.address || 'Street View location'
  const coords = coordinateLabel(meta?.lat, meta?.lon)
  const date = meta?.date ? `, captured ${meta.date}` : ''
  return `${address} (${coords})${date}.`
}

function parseArtifactMeta(value: string | null): Record<string, unknown> {
  if (!value) return {}
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

export default function StreetViewWorkspace({
  target,
  roadTarget,
  onArtifactsChanged,
  onClose,
  layout,
  onLayoutChange,
  onYawChange,
  onLocationChange,
  workspacePath,
}: StreetViewWorkspaceProps) {
  const [meta, setMeta] = useState<StreetViewMeta | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [googleApiKey, setGoogleApiKey] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [lastArtifactId, setLastArtifactId] = useState<number | null>(null)
  const [reportStatus, setReportStatus] = useState<string | null>(null)
  const [intervalM, setIntervalM] = useState(30)
  const [gallery, setGallery] = useState<GalleryItem[]>([])
  const [galleryBusy, setGalleryBusy] = useState(false)
  const [galleryError, setGalleryError] = useState<string | null>(null)
  const [showInfo, setShowInfo] = useState(false)
  const [showActions, setShowActions] = useState(false)

  useEffect(() => {
    setShowInfo(false)
    setShowActions(false)
  }, [target, roadTarget])

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/token`)
      .then((r) => r.json())
      .then((data: { google_key?: string }) => {
        if (!cancelled) {
          setGoogleApiKey(data.google_key || '')
        }
      })
      .catch(() => {
        if (!cancelled) {
          setGoogleApiKey('')
        }
      })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      const targetEl = e.target as HTMLElement
      if (
        !targetEl.closest('.sv-overlay-button-group') &&
        !targetEl.closest('.sv-info-overlay-card') &&
        !targetEl.closest('.sv-actions-overlay-card')
      ) {
        setShowInfo(false)
        setShowActions(false)
      }
    }
    document.addEventListener('click', handleOutsideClick)
    return () => document.removeEventListener('click', handleOutsideClick)
  }, [])

  useEffect(() => {
    if (meta?.found && Number.isFinite(meta.lat) && Number.isFinite(meta.lon)) {
      onLocationChange?.({ lat: Number(meta.lat), lng: Number(meta.lon) })
    }
  }, [meta, onLocationChange])

  useEffect(() => {
    if (!target) {
      setMeta(null)
      setError(null)
      setLastArtifactId(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    setMeta(null)
    setLastArtifactId(null)
    fetch(`${API}/meta?lat=${target.lat}&lng=${target.lng}`)
      .then((r) => r.json())
      .then((d: StreetViewMeta) => { if (!cancelled) setMeta(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [target])

  const headers = useMemo(() => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' }
    return h
  }, [])

  const saveCurrentImage = useCallback(async (): Promise<StreetViewArtifactResult | null> => {
    if (!target) return null
    setSaving(true)
    setReportStatus(null)
    try {
      const resp = await fetch(`${API}/image`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          lat: target.lat,
          lng: target.lng,
          title: meta?.address || target.label || `Street View ${coordinateLabel(target.lat, target.lng)}`,
          workspace: workspacePath,
        }),
      })
      const data: StreetViewArtifactResult = await resp.json()
      if (!resp.ok || !data.found) {
        setReportStatus(data.error || 'No Street View image could be saved here.')
        return null
      }
      const id = data.artifact_id || data.artifact?.id || null
      setLastArtifactId(id)
      onArtifactsChanged?.()
      return data
    } catch (e) {
      setReportStatus(`Street View save failed: ${String(e)}`)
      return null
    } finally {
      setSaving(false)
    }
  }, [target, headers, meta, onArtifactsChanged, workspacePath])

  const downloadCurrentImage = useCallback(async () => {
    const result = await saveCurrentImage()
    const id = result?.artifact_id || result?.artifact?.id
    if (!id) return
    const a = document.createElement('a')
    a.href = `${ARTIFACT_API}/${id}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
    a.download = `street-view-${id}.jpg`
    a.click()
  }, [saveCurrentImage, workspacePath])

  const addImagesToReport = useCallback(async (images: Array<Record<string, unknown>>, title: string) => {
    if (!images.length) return
    setReportStatus(null)
    try {
      const resp = await fetch(`${API}/report`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ title, images, workspace: workspacePath }),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      setReportStatus('Added to an editable report artifact.')
      onArtifactsChanged?.()
    } catch (e) {
      setReportStatus(`Report insert failed: ${String(e)}`)
    }
  }, [headers, onArtifactsChanged, workspacePath])

  const addCurrentToReport = useCallback(async () => {
    let artifactId = lastArtifactId
    if (!artifactId) {
      const result = await saveCurrentImage()
      artifactId = result?.artifact_id || result?.artifact?.id || null
    }
    if (!artifactId) return
    await addImagesToReport(
      [{
        artifact_id: artifactId,
        lat: meta?.lat ?? target?.lat,
        lng: meta?.lon ?? target?.lng,
        address: meta?.address,
        capture_date: meta?.date,
        caption: captionFromMeta(meta),
      }],
      `Street View - ${meta?.address || target?.label || coordinateLabel(target?.lat, target?.lng)}`,
    )
  }, [addImagesToReport, lastArtifactId, meta, saveCurrentImage, target])

  const runRoadInspection = useCallback(async () => {
    if (!roadTarget) return
    setGalleryBusy(true)
    setGalleryError(null)
    setGallery([])
    setReportStatus(null)
    try {
      const sampleResp = await fetch(`${API}/road-inspection`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ geometry: roadTarget.geometry, interval_m: intervalM }),
      })
      const sampled: { points?: RoadSamplePoint[]; error?: string } = await sampleResp.json()
      if (!sampleResp.ok || !sampled.points?.length) {
        throw new Error(sampled.error || 'No sample points could be generated for this road.')
      }

      setGallery(sampled.points.map((point) => ({ point, status: 'pending', selected: false, notes: '' })))
      for (const point of sampled.points) {
        setGallery((prev) => prev.map((item) =>
          item.point.id === point.id ? { ...item, status: 'loading' } : item,
        ))
        try {
          const resp = await fetch(`${API}/image`, {
            method: 'POST',
            headers,
            body: JSON.stringify({
              lat: point.lat,
              lng: point.lng,
              title: `${roadTarget.name || 'Road inspection'} - ${Math.round(point.distance_m)} m`,
              workspace: workspacePath,
            }),
          })
          const data: StreetViewArtifactResult = await resp.json()
          if (!resp.ok || !data.found) {
            setGallery((prev) => prev.map((item) =>
              item.point.id === point.id ? { ...item, status: 'missing' } : item,
            ))
            continue
          }
          const artifactId = data.artifact_id || data.artifact?.id
          const parsedMeta = parseArtifactMeta(data.artifact?.meta || null)
          setGallery((prev) => prev.map((item) =>
            item.point.id === point.id
              ? {
                  ...item,
                  status: 'done',
                  selected: true,
                  artifactId,
                  imageUrl: artifactId ? `${ARTIFACT_API}/${artifactId}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}` : undefined,
                  address: data.metadata?.address || String(parsedMeta.address || '') || null,
                  captureDate: data.metadata?.date || String(parsedMeta.capture_date || '') || null,
                }
              : item,
          ))
          onArtifactsChanged?.()
        } catch (e) {
          setGallery((prev) => prev.map((item) =>
            item.point.id === point.id ? { ...item, status: 'error', error: String(e) } : item,
          ))
        }
      }
    } catch (e) {
      setGalleryError(String(e))
    } finally {
      setGalleryBusy(false)
    }
  }, [headers, intervalM, onArtifactsChanged, roadTarget, workspacePath])

  const updateGalleryNotes = useCallback(async (artifactId: number | undefined, notes: string) => {
    setGallery((prev) => prev.map((item) =>
      item.artifactId === artifactId ? { ...item, notes } : item,
    ))
    if (!artifactId) return
    const item = gallery.find((g) => g.artifactId === artifactId)
    const existing = item?.artifactId ? item : null
    try {
      const url = `${ARTIFACT_API}/${artifactId}${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
      const current = await fetch(url).then((r) => r.ok ? r.json() : null)
      const currentMeta = parseArtifactMeta(current?.meta || null)
      await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ meta: { ...currentMeta, planner_notes: notes } }),
      })
      if (existing) onArtifactsChanged?.()
    } catch {
      /* Keep notes in the gallery even if the artifact update fails. */
    }
  }, [gallery, onArtifactsChanged, workspacePath])

  const runRoadItem = useCallback(async (item: GalleryItem) => {
    setGallery((prev) => prev.map((g) => g.point.id === item.point.id ? { ...g, status: 'loading' } : g))
    try {
      // 1. Get metadata
      const resMeta = await fetch(`${API}/meta?lat=${item.point.lat}&lng=${item.point.lng}`, { headers })
      const mData: StreetViewMeta = await resMeta.json()
      if (!mData.found) {
        setGallery((prev) => prev.map((g) => g.point.id === item.point.id ? { ...g, status: 'missing' } : g))
        return
      }

      // 2. Save image artifact
      const resArt = await fetch(`${API}/image`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          lat: mData.lat,
          lng: mData.lon,
          zoom: 3,
          title: `Road Inspection Point ${Math.round(item.point.distance_m)}m`,
          notes: captionFromMeta(mData),
          workspace: workspacePath,
        }),
      })
      const aData: StreetViewArtifactResult = await resArt.json()
      if (aData.found && aData.artifact_id && aData.download_url) {
        setGallery((prev) => prev.map((g) => g.point.id === item.point.id ? {
          ...g,
          status: 'done',
          artifactId: aData.artifact_id,
          imageUrl: `http://localhost:8765${aData.download_url}${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`,
          address: mData.address,
          captureDate: mData.date,
        } : g))
        onArtifactsChanged?.()
      } else {
        setGallery((prev) => prev.map((g) => g.point.id === item.point.id ? { ...g, status: 'error', error: aData.error || 'Failed to save.' } : g))
      }
    } catch (e) {
      setGallery((prev) => prev.map((g) => g.point.id === item.point.id ? { ...g, status: 'error', error: String(e) } : g))
    }
  }, [headers, onArtifactsChanged, workspacePath])

  // Sequentially process gallery items to avoid rate limits
  useEffect(() => {
    const next = gallery.find((g) => g.status === 'pending')
    if (!next || galleryBusy) return
    setGalleryBusy(true)
    runRoadItem(next).finally(() => setGalleryBusy(false))
  }, [gallery, galleryBusy, runRoadItem])

  const addSelectedGalleryToReport = useCallback(async () => {
    const selected = gallery.filter((item) => item.status === 'done' && item.selected && item.artifactId)
    await addImagesToReport(
      selected.map((item, index) => ({
        artifact_id: item.artifactId,
        lat: item.point.lat,
        lng: item.point.lng,
        address: item.address,
        capture_date: item.captureDate,
        planner_notes: item.notes,
        caption: `Figure ${index + 1}. ${item.address || roadTarget?.name || 'Road inspection point'} at ${Math.round(item.point.distance_m)} m.`,
      })),
      `${roadTarget?.name || 'Road'} Selected Street View Inspection Points`,
    )
  }, [addImagesToReport, gallery, roadTarget])

  const addFullGalleryToReport = useCallback(async () => {
    const done = gallery.filter((item) => item.status === 'done' && item.artifactId)
    await addImagesToReport(
      done.map((item, index) => ({
        artifact_id: item.artifactId,
        lat: item.point.lat,
        lng: item.point.lng,
        address: item.address,
        capture_date: item.captureDate,
        planner_notes: item.notes,
        caption: `Figure ${index + 1}. ${item.address || roadTarget?.name || 'Road inspection point'} at ${Math.round(item.point.distance_m)} m.`,
      })),
      `${roadTarget?.name || 'Road'} Street View Inspection Session`,
    )
  }, [addImagesToReport, gallery, roadTarget])

  if (!target && !roadTarget) {
    return (
      <div className="sv-workspace sv-empty">
        <div className="sv-empty-title">Street View Workspace</div>
        <div className="sv-empty-text">
          Use the map Street View tool, right-click a location, select a marker, search for a place,
          or inspect a road layer.
        </div>
      </div>
    )
  }

  const doneCount = gallery.filter((item) => item.status === 'done').length
  const selectedDoneCount = gallery.filter((item) => item.selected && item.status === 'done').length
  const processedCount = gallery.filter((item) => item.status !== 'pending').length
  const galleryTotal = gallery.length

  return (
    <div className="sv-workspace">
      <div className="sv-panel-header">
        <div>
          <div className="sv-eyebrow">Street View</div>
          <div className="sv-heading">
            {meta?.address || target?.label || (target ? coordinateLabel(target.lat, target.lng) : roadTarget?.name || 'Road inspection')}
          </div>
        </div>
        <div className="sv-header-actions">
          {onLayoutChange && (
            <button
              className="sv-layout-toggle-btn"
              onClick={() => onLayoutChange(layout === 'full' ? 'split' : 'full')}
              title={layout === 'full' ? 'Split screen' : 'Full screen'}
            >
              {layout === 'full' ? (
                <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                  <path d="M4 4h8V2H4a2 2 0 00-2 2v8h2V4zm16 16h-8v2h8a2 2 0 002-2v-8h-2v8z"/>
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
                  <path d="M4 4h16v16H4V4zm2 2v12h12V6H6z"/>
                </svg>
              )}
            </button>
          )}
          {onClose && <button className="sv-icon-btn" onClick={onClose} title="Close Street View">✕</button>}
        </div>
      </div>

      {target && (
        <section className="sv-section">
          <div className="sv-viewer-shell">
            <iframe
              title="Google Street View Embed"
              className="sv-google-iframe"
              src={
                googleApiKey
                  ? `https://www.google.com/maps/embed/v1/streetview?key=${encodeURIComponent(googleApiKey)}&location=${target.lat},${target.lng}`
                  : `https://maps.google.com/maps?layer=c&cbll=${target.lat},${target.lng}&output=embed`
              }
              allowFullScreen
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
            />

            <div className="sv-overlay-top-right">
              <div className="sv-overlay-button-group">
                <button 
                  className={`sv-overlay-btn ${showInfo ? 'active' : ''}`}
                  onClick={() => {
                    setShowInfo(!showInfo)
                    setShowActions(false)
                  }}
                  title="Location Details"
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                </button>
                <button 
                  className={`sv-overlay-btn ${showActions ? 'active' : ''}`}
                  onClick={() => {
                    setShowActions(!showActions)
                    setShowInfo(false)
                  }}
                  title="Save Options"
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                    <polyline points="17 21 17 13 7 13 7 21" />
                    <polyline points="7 3 7 8 15 8" />
                  </svg>
                </button>
              </div>

              {showInfo && (
                <div className="sv-info-overlay-card">
                  <div className="sv-info-row">
                    <span className="sv-info-label">Coordinates</span>
                    <strong className="sv-info-val">{coordinateLabel(meta?.lat ?? target.lat, meta?.lon ?? target.lng)}</strong>
                  </div>
                  <div className="sv-info-row">
                    <span className="sv-info-label">Viewer</span>
                    <strong className="sv-info-val">Google Street View Embed</strong>
                  </div>
                  {meta?.date && (
                    <div className="sv-info-row">
                      <span className="sv-info-label">Image Date</span>
                      <strong className="sv-info-val">{meta.date}</strong>
                    </div>
                  )}
                </div>
              )}

              {showActions && (
                <div className="sv-actions-overlay-card">
                  <button className="sv-action-card-btn" onClick={downloadCurrentImage} disabled={saving}>
                    Download Image
                  </button>
                  <button className="sv-action-card-btn" onClick={saveCurrentImage} disabled={saving}>
                    Save to Artifacts
                  </button>
                  {lastArtifactId && <div className="sv-action-card-note">Saved as artifact #{lastArtifactId}.</div>}
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {roadTarget && (
        <section className="sv-section sv-road-section">
          <div className="sv-section-head">
            <div>
              <div className="sv-eyebrow">Road Inspection</div>
              <div className="sv-subheading">{roadTarget.name || 'Selected road'}</div>
            </div>
            <label className="sv-interval">
              <span>Interval</span>
              <input
                type="number"
                min={5}
                max={500}
                value={intervalM}
                onChange={(e) => setIntervalM(Number(e.target.value) || 30)}
              />
              <span>m</span>
            </label>
          </div>
          <div className="sv-actions">
            <button onClick={runRoadInspection} disabled={galleryBusy}>Inspect Road</button>
            <button onClick={addSelectedGalleryToReport} disabled={selectedDoneCount === 0}>Add Selected to Report</button>
            <button onClick={addFullGalleryToReport} disabled={doneCount === 0}>Add Session to Report</button>
          </div>
          {galleryTotal > 0 && (
            <div className="sv-progress">
              <div className="sv-progress-bar" style={{ width: `${Math.round((processedCount / galleryTotal) * 100)}%` }} />
              <span>{processedCount}/{galleryTotal} processed, {doneCount} saved</span>
            </div>
          )}
          {galleryError && <div className="sv-note sv-error">{galleryError}</div>}
          <div className="sv-gallery">
            {gallery.map((item) => (
              <article key={item.point.id} className="sv-gallery-item">
                {item.imageUrl ? (
                  <img src={item.imageUrl} alt={item.address || 'Street View'} />
                ) : (
                  <div className="sv-gallery-placeholder">{item.status}</div>
                )}
                <div className="sv-gallery-body">
                  <label className="sv-gallery-select">
                    <input
                      type="checkbox"
                      checked={item.selected}
                      disabled={item.status !== 'done'}
                      onChange={(e) => {
                        const selected = e.target.checked
                        setGallery((prev) => prev.map((g) =>
                          g.point.id === item.point.id ? { ...g, selected } : g,
                        ))
                      }}
                    />
                    <span>Include in report</span>
                  </label>
                  <strong>{item.address || `${Math.round(item.point.distance_m)} m`}</strong>
                  <span>{coordinateLabel(item.point.lat, item.point.lng)}</span>
                  <span>{item.captureDate || 'Capture date unavailable'}</span>
                  <textarea
                    placeholder="Planner notes"
                    value={item.notes}
                    onChange={(e) => updateGalleryNotes(item.artifactId, e.target.value)}
                    disabled={item.status !== 'done'}
                  />
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
