import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from 'react'
import maplibregl from 'maplibre-gl'
import type { DataDrivenPropertyValueSpecification, ExpressionSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import * as turf from '@turf/turf'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { GeoJSONLayer, MapViewState, MapAction, BASEMAPS, SelectedFeatureEntry } from '../types'
import './MapView.css'

interface NominatimSearchResult {
  display_name: string
  lat: string
  lon: string
  hasStreetView?: boolean
}

export type MapViewHandle = {
  getCanvas: () => HTMLCanvasElement | null
  resize: () => void
  fitBboxAndSnapshot: (bboxTarget?: any, padding?: number, layersToShow?: string[]) => HTMLCanvasElement | null
}

// Helper to check if a polygon/multipolygon geometry intersects the viewport bounds
function doesPolygonIntersectViewport(geom: any, bounds: { west: number; south: number; east: number; north: number }): boolean {
  // 1. Bounding box check
  const bbox = turf.bbox(geom);
  if (bbox[2] < bounds.west || bbox[0] > bounds.east || bbox[3] < bounds.south || bbox[1] > bounds.north) {
    return false;
  }

  // 2. Center check (if viewport is inside a huge polygon)
  const centerPt = turf.point([(bounds.west + bounds.east) / 2, (bounds.south + bounds.north) / 2]);
  try {
    if (turf.booleanPointInPolygon(centerPt, geom)) {
      return true;
    }
  } catch {
    // ignore
  }

  // 3. Coordinate check
  const coords = geom.type === 'Polygon' ? geom.coordinates : geom.type === 'MultiPolygon' ? geom.coordinates.flat(1) : [];
  for (const ring of coords) {
    for (const pt of ring) {
      if (pt[0] >= bounds.west && pt[0] <= bounds.east && pt[1] >= bounds.south && pt[1] <= bounds.north) {
        return true;
      }
    }
  }

  // 4. Fallback intersection check
  try {
    const viewportPoly = turf.bboxPolygon([bounds.west, bounds.south, bounds.east, bounds.north]);
    const intersection = turf.intersect(turf.featureCollection([turf.feature(geom), viewportPoly]));
    if (intersection) return true;
  } catch {
    // ignore
  }

  return false;
}

// Helper to find the best real-world coordinate [lng, lat] for off-screen indicator targets
function getTargetPointForGeometry(geom: Geometry, mapCenter: [number, number]): [number, number] | null {
  const centerPoint = turf.point(mapCenter);

  if (geom.type === 'Point') {
    return geom.coordinates as [number, number];
  }

  if (geom.type === 'MultiPoint') {
    let closestCoord: [number, number] | null = null;
    let minDist = Infinity;
    for (const coord of geom.coordinates) {
      const dist = turf.distance(turf.point(coord), centerPoint);
      if (dist < minDist) {
        minDist = dist;
        closestCoord = coord as [number, number];
      }
    }
    return closestCoord;
  }

  if (geom.type === 'LineString') {
    try {
      const nearest = turf.nearestPointOnLine(geom as any, centerPoint);
      return nearest.geometry.coordinates as [number, number];
    } catch {
      const centroid = turf.centroid(geom as any);
      return centroid.geometry.coordinates as [number, number];
    }
  }

  if (geom.type === 'MultiLineString') {
    try {
      let closestPoint: [number, number] | null = null;
      let minDist = Infinity;
      for (const coords of geom.coordinates) {
        const line = turf.lineString(coords);
        const nearest = turf.nearestPointOnLine(line, centerPoint);
        const dist = turf.distance(nearest, centerPoint);
        if (dist < minDist) {
          minDist = dist;
          closestPoint = nearest.geometry.coordinates as [number, number];
        }
      }
      return closestPoint;
    } catch {
      const centroid = turf.centroid(geom as any);
      return centroid.geometry.coordinates as [number, number];
    }
  }

  if (geom.type === 'Polygon') {
    try {
      const boundaryLine = turf.lineString(geom.coordinates[0]);
      const nearest = turf.nearestPointOnLine(boundaryLine, centerPoint);
      return nearest.geometry.coordinates as [number, number];
    } catch {
      const centroid = turf.centroid(geom as any);
      return centroid.geometry.coordinates as [number, number];
    }
  }

  if (geom.type === 'MultiPolygon') {
    try {
      let largestPolyCoords = geom.coordinates[0];
      let maxArea = -1;
      for (const polyCoords of geom.coordinates) {
        const poly = turf.polygon(polyCoords);
        const area = turf.area(poly);
        if (area > maxArea) {
          maxArea = area;
          largestPolyCoords = polyCoords;
        }
      }
      const largestPoly = turf.polygon(largestPolyCoords);
      const centroid = turf.centroid(largestPoly);
      return centroid.geometry.coordinates as [number, number];
    } catch {
      const centroid = turf.centroid(geom as any);
      return centroid.geometry.coordinates as [number, number];
    }
  }

  return null;
}

// Labels are the most expensive layer type. Above this feature count we skip
// the symbol layer entirely to keep the map responsive.
const LABEL_FEATURE_CAP = 3000

// ── Data-driven paint expressions ──
//
// Translate a layer's styleSpec into a MapLibre color expression. Always wrap
// in coalesce(get(fillColor|strokeColor), <expr>) so a per-feature color
// override still wins over categorized/graduated styling.

type ColorExpr = DataDrivenPropertyValueSpecification<string>

function categorizedExpr(spec: NonNullable<GeoJSONLayer['styleSpec']>, fallback: string): unknown {
  const match: unknown[] = ['match', ['to-string', ['get', spec.property!]]]
  for (const c of spec.categories!) match.push(c.value, c.color)
  match.push(spec.otherColor || fallback) // default for unmatched values
  return match
}

function graduatedExpr(spec: NonNullable<GeoJSONLayer['styleSpec']>, fallback: string): unknown {
  const colors = spec.rampColors!
  const step: unknown[] = ['step', ['to-number', ['get', spec.property!], 0], colors[0]]
  spec.breaks!.forEach((b, i) => step.push(b, colors[i + 1] ?? colors[colors.length - 1]))
  return step
}

function dataDrivenColor(
  spec: GeoJSONLayer['styleSpec'],
  overrideProp: 'fillColor' | 'strokeColor',
  scalar: string,
): ColorExpr {
  if (spec && spec.mode === 'categorized' && spec.property && spec.categories?.length) {
    return ['coalesce', ['get', overrideProp], categorizedExpr(spec, scalar)] as ColorExpr
  }
  if (
    spec && spec.mode === 'graduated' && spec.property &&
    spec.breaks?.length && spec.rampColors?.length
  ) {
    return ['coalesce', ['get', overrideProp], graduatedExpr(spec, scalar)] as ColorExpr
  }
  return ['coalesce', ['get', overrideProp], scalar] as ColorExpr
}

function fillColorExpression(layer: GeoJSONLayer): ColorExpr {
  return dataDrivenColor(layer.styleSpec, 'fillColor', layer.styleSpec?.fillColor ?? layer.fillColor ?? layer.color)
}

function lineColorExpression(layer: GeoJSONLayer): ColorExpr {
  return dataDrivenColor(layer.styleSpec, 'strokeColor', layer.styleSpec?.strokeColor ?? layer.lineColor ?? layer.color)
}

function fillOpacityValue(layer: GeoJSONLayer): number {
  return layer.styleSpec?.opacity ?? layer.opacity ?? 0.3
}

function labelsActive(layer: GeoJSONLayer): boolean {
  const l = layer.styleSpec?.label
  return Boolean(
    l?.enabled && l.property &&
    (layer.data?.features?.length ?? 0) <= LABEL_FEATURE_CAP,
  )
}

/** text-field value for a layer's label symbol layer ('' = nothing drawn). */
function labelField(layer: GeoJSONLayer): ExpressionSpecification | string {
  const l = layer.styleSpec?.label
  return labelsActive(layer) ? (['get', l!.property] as ExpressionSpecification) : ''
}

// Property keys that look like a human-readable title, in preference order.
const POPUP_TITLE_KEYS = ['label', 'name', 'title', 'display_name']
// Internal bookkeeping props that should never surface in a hover popup.
const POPUP_HIDDEN_KEYS = new Set([
  'label', 'name', 'title', 'display_name', 'description',
  'source', 'source_layer', 'fillColor', 'strokeColor',
  'type', 'types',
])

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * Build popup HTML for any feature's properties. Returns '' when there's
 * nothing worth showing. Shared by every layer so AI markers, AI-drawn
 * shapes, and user-drawn shapes all get a hover popup for free.
 */
function popupHtmlForProps(props: Record<string, unknown> | null): string {
  if (!props) return ''
  const titleKey = POPUP_TITLE_KEYS.find((k) => props[k] != null && String(props[k]).trim() !== '')
  const title = titleKey ? String(props[titleKey]).trim() : ''
  const description =
    props.description != null && String(props.description).trim() !== ''
      ? String(props.description).trim()
      : ''
  // Remaining attributes (e.g. zone_code, population) shown as key: value rows.
  const rows = Object.entries(props)
    .filter(([k, v]) => !POPUP_HIDDEN_KEYS.has(k) && v != null && String(v).trim() !== '')
    .slice(0, 8)
    .map(([k, v]) => `<div class="mv-popup-row"><span>${escapeHtml(k)}</span>: ${escapeHtml(v)}</div>`)
    .join('')

  if (!title && !description && !rows) return ''
  return (
    (title ? `<div class="mv-popup-title">${escapeHtml(title)}</div>` : '') +
    (description ? `<div class="mv-popup-desc">${escapeHtml(description)}</div>` : '') +
    rows
  )
}

interface MapViewProps {
  layers: GeoJSONLayer[]
  selectedLayerIds?: Set<string>
  basemap: string
  initialState: MapViewState
  mapActions: MapAction[]
  onMapMove: (state: MapViewState) => void
  onBoundsChange?: (b: { west: number; south: number; east: number; north: number }) => void
  onBasemapChange: (basemap: string) => void
  onActionsProcessed: () => void
  onLayerStyleChange?: (
    layerName: string,
    style: { fillColor?: string; lineColor?: string; opacity?: number },
  ) => void
  onAddMarker?: (lng: number, lat: number) => void
  onOpenStreetView?: (lng: number, lat: number) => void
  onInspectRoad?: (feature: Feature) => void
  onAskChat?: (lng: number, lat: number) => void
  onContextualQuery?: (feature: any, lngLat: { lng: number; lat: number }) => void
  /** A user finished drawing a shape. Coordinates are [lng,lat]; for 'point'
   *  the array holds a single pair, for 'line'/'polygon' the full vertex list
   *  (polygon ring is not yet closed). */
  onDrawComplete?: (type: 'point' | 'line' | 'polygon', coordinates: number[][]) => void
  streetViewDetail: boolean
  onStreetViewDetailChange: (active: boolean) => void
  streetViewActive: boolean
  streetViewLocation: { lat: number; lng: number } | null
  streetViewBearing: number
  isMiniMap: boolean
  onStreetViewLayoutChange?: (layout: 'split' | 'full') => void
  onUndo?: () => void
  onRedo?: () => void
  canUndo?: boolean
  canRedo?: boolean
  selectedFeatures?: SelectedFeatureEntry[]
  onSelectFeature?: (entry: SelectedFeatureEntry | null, shiftKey: boolean) => void
}

type DrawMode = 'point' | 'line' | 'polygon' | null

const MapView = forwardRef<MapViewHandle, MapViewProps>(function MapView(
  {
    layers,
    selectedLayerIds = new Set(),
    basemap,
    initialState,
    mapActions,
    onMapMove,
    onBoundsChange,
    onBasemapChange,
    onActionsProcessed,
    onLayerStyleChange,
    onAddMarker,
    onOpenStreetView,
    onInspectRoad,
    onAskChat,
    onContextualQuery,
    onDrawComplete,
    streetViewDetail,
    onStreetViewDetailChange,
    streetViewActive,
    streetViewLocation,
    streetViewBearing,
    isMiniMap,
    onStreetViewLayoutChange,
    onUndo,
    onRedo,
    canUndo = false,
    canRedo = false,
    selectedFeatures = [],
    onSelectFeature,
  },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [zoomTooLow, setZoomTooLow] = useState(false)
  // Each off-screen indicator: position on edge + angle + the entry it refers to
  type IndicatorPos = { x: number; y: number; angle: number; entry: SelectedFeatureEntry }
  const [indicatorPositions, setIndicatorPositions] = useState<IndicatorPos[]>([])
  const mapRef = useRef<maplibregl.Map | null>(null)
  const onBoundsChangeRef = useRef(onBoundsChange)
  onBoundsChangeRef.current = onBoundsChange
  const onLayerStyleChangeRef = useRef(onLayerStyleChange)
  onLayerStyleChangeRef.current = onLayerStyleChange
  const onAddMarkerRef = useRef(onAddMarker)
  onAddMarkerRef.current = onAddMarker
  const onOpenStreetViewRef = useRef(onOpenStreetView)
  onOpenStreetViewRef.current = onOpenStreetView
  const onInspectRoadRef = useRef(onInspectRoad)
  onInspectRoadRef.current = onInspectRoad
  const onAskChatRef = useRef(onAskChat)
  onAskChatRef.current = onAskChat
  const onContextualQueryRef = useRef(onContextualQuery)
  onContextualQueryRef.current = onContextualQuery
  const onDrawCompleteRef = useRef(onDrawComplete)
  onDrawCompleteRef.current = onDrawComplete
  const drawModeRef = useRef<DrawMode>(null)
  const drawVerticesRef = useRef<number[][]>([])
  const drawVerticesHistoryRef = useRef<number[][][]>([])
  const drawRedoHistoryRef = useRef<number[][][]>([])
  const ownLayerIds = useRef(new Set<string>())
  const layersRef = useRef(layers)
  layersRef.current = layers
  const renderLayerIds = useCallback((): string[] => {
    const map = mapRef.current
    if (!map) return []
    const ids: string[] = []
    for (const baseId of ownLayerIds.current) {
      for (const suffix of ['-fill', '-line', '-circle']) {
        if (map.getLayer(`${baseId}${suffix}`)) ids.push(`${baseId}${suffix}`)
      }
    }
    return ids
  }, [])
  const hoverPopupRef = useRef<maplibregl.Popup | null>(null)
  // Per-source revision token: setData() is only called when layer.data changes.
  const layerRevisionRef = useRef(new Map<string, FeatureCollection>())
  const initBasemapRef = useRef(basemap)
  const basemapPanelRef = useRef<HTMLDivElement>(null)
  const basemapButtonRef = useRef<HTMLButtonElement>(null)

  const [mapReady, setMapReady] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NominatimSearchResult[]>([])
  const [showSearch, setShowSearch] = useState(false)
  const [showBasemaps, setShowBasemaps] = useState(false)
  const [ctxMenu, setCtxMenu] = useState<{
    x: number
    y: number
    lng: number
    lat: number
    feature?: Feature
  } | null>(null)
  const [drawMode, setDrawMode] = useState<DrawMode>(null)
  const [drawCount, setDrawCount] = useState(0) // vertices placed in the current draft


  // ── Initialize map ──

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const { tiles, attribution } = BASEMAPS[initBasemapRef.current] || BASEMAPS.street

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        // Glyphs are required for any symbol/text layer (feature labels).
        // demotiles serves free PBF font ranges with no API key, matching the
        // keyless raster-tile approach. Offline → labels just don't draw.
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
        sources: {
          basemap: { type: 'raster', tiles, tileSize: 256, attribution },
        },
        layers: [
          { id: 'basemap', type: 'raster', source: 'basemap', minzoom: 0, maxzoom: 19 },
        ],
      },
      center: initialState.center,
      zoom: initialState.zoom,
      bearing: initialState.bearing || 0,
      pitch: initialState.pitch || 0,
      preserveDrawingBuffer: true,
      canvasContextAttributes: { preserveDrawingBuffer: true },
    })

    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.addControl(new maplibregl.ScaleControl(), 'bottom-left')

    map.on('moveend', () => {
      onMapMove({
        center: [map.getCenter().lng, map.getCenter().lat],
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      })
      const b = map.getBounds()
      onBoundsChangeRef.current?.({
        west: b.getWest(),
        south: b.getSouth(),
        east: b.getEast(),
        north: b.getNorth(),
      })
    })

    map.on('contextmenu', (e) => {
      e.preventDefault?.()
      const ids = renderLayerIds()
      const feats = ids.length ? map.queryRenderedFeatures(e.point, { layers: ids }) : []
      const feature = feats[0]
        ? {
            type: 'Feature' as const,
            geometry: JSON.parse(JSON.stringify(feats[0].geometry)) as Geometry,
            properties: { ...(feats[0].properties || {}) },
          }
        : undefined
      setCtxMenu({ x: e.point.x, y: e.point.y, lng: e.lngLat.lng, lat: e.lngLat.lat, feature })
    })
    map.on('movestart', () => setCtxMenu(null))

    mapRef.current = map

    map.on('load', () => {
      // Initialize drawing source and layers
      map.addSource('streetview-coverage', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      })
      map.addLayer({
        id: 'streetview-coverage-layer',
        type: 'line',
        source: 'streetview-coverage',
        layout: {
          'line-join': 'round',
          'line-cap': 'round'
        },
        paint: {
          'line-color': '#00b4d8', // Cyan coverage
          'line-width': 4.5,
          'line-opacity': 0.75
        }
      })
      map.addSource('selected-feature-highlight', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.addLayer({
        id: 'selected-feature-highlight-fill',
        type: 'fill',
        source: 'selected-feature-highlight',
        filter: ['any', ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'MultiPolygon']],
        paint: {
          'fill-color': '#f59e0b',
          'fill-opacity': 0.15,
        },
      })
      map.addLayer({
        id: 'selected-feature-highlight-line',
        type: 'line',
        source: 'selected-feature-highlight',
        filter: ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'MultiPolygon']],
        paint: {
          'line-color': '#f59e0b',
          'line-width': 4.0,
          'line-opacity': 0.85,
        },
      })
      map.addLayer({
        id: 'selected-feature-highlight-circle',
        type: 'circle',
        source: 'selected-feature-highlight',
        filter: ['any', ['==', ['geometry-type'], 'Point'], ['==', ['geometry-type'], 'MultiPoint']],
        paint: {
          'circle-radius': 8,
          'circle-color': '#f59e0b',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
          'circle-opacity': 0.9,
        },
      })
      // ── Edge-glow source: selected polygons that intersect the viewport ──
      // Opacity is driven by a requestAnimationFrame loop — paint starts at 0.
      map.addSource('selected-feature-edge-glow', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.addLayer({
        id: 'selected-feature-edge-glow-line',
        type: 'line',
        source: 'selected-feature-edge-glow',
        filter: ['any', ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'MultiPolygon']],
        paint: {
          'line-color': '#f59e0b',
          'line-width': 5,
          'line-opacity': 0,  // animated by rAF
          'line-blur': 1,
        },
      })
      setMapReady(true)
    })

    return () => {
      setMapReady(false)
      layerRevisionRef.current.clear()
      map.remove()
      mapRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    getCanvas: () => mapRef.current?.getCanvas() ?? null,
    resize: () => mapRef.current?.resize(),
    zoomOutMargin: (delta = 0.75) => {
      if (mapRef.current) {
        mapRef.current.zoomTo(mapRef.current.getZoom() - delta, { animate: false })
      }
    },
    fitBboxAndSnapshot: (bboxTarget?: any, padding = 100, layersToShow?: string[]) => {
      const map = mapRef.current
      if (!map) return null

      const origCenter = map.getCenter()
      const origZoom = map.getZoom()
      const origBearing = map.getBearing()
      const origPitch = map.getPitch()

      // Save original layout visibility for layers when filtering
      const savedVisibility: Array<{ layerId: string; visibility: string }> = []
      const sublayerSuffixes = ['-fill', '-outline', '-line', '-circle', '-label', '-raster']

      if (layersToShow && layersToShow.length > 0) {
        const normalizedFilter = layersToShow.map((s) => s.toLowerCase().trim())
        for (const layer of layersRef.current) {
          const layerNameLower = layer.name.toLowerCase()
          const layerIdLower = layer.id.toLowerCase()
          const isMatch = normalizedFilter.some(
            (f) => layerNameLower.includes(f) || f.includes(layerNameLower) || layerIdLower === f,
          )
          for (const suffix of sublayerSuffixes) {
            const sublayerId = `${layer.id}${suffix}`
            if (map.getLayer(sublayerId)) {
              const currVis = (map.getLayoutProperty(sublayerId, 'visibility') as string) || 'visible'
              savedVisibility.push({ layerId: sublayerId, visibility: currVis })
              map.setLayoutProperty(sublayerId, 'visibility', isMatch ? 'visible' : 'none')
            }
          }
        }
      }

      let boundsToFit: [[number, number], [number, number]] | null = null

      if (bboxTarget) {
        if (Array.isArray(bboxTarget) && bboxTarget.length === 4) {
          boundsToFit = [[bboxTarget[0], bboxTarget[1]], [bboxTarget[2], bboxTarget[3]]]
        } else if (typeof bboxTarget === 'object' && bboxTarget.west !== undefined) {
          boundsToFit = [[bboxTarget.west, bboxTarget.south], [bboxTarget.east, bboxTarget.north]]
        }
      }

      if (!boundsToFit && layersRef.current.length > 0) {
        let combinedBbox: [number, number, number, number] | null = null
        const targetLayers = layersToShow && layersToShow.length > 0
          ? layersRef.current.filter((layer) => {
              const n = layer.name.toLowerCase()
              const id = layer.id.toLowerCase()
              return layersToShow.some((f) => n.includes(f.toLowerCase()) || f.toLowerCase().includes(n) || id === f.toLowerCase())
            })
          : layersRef.current.filter((layer) => layer.visible)

        for (const layer of (targetLayers.length > 0 ? targetLayers : layersRef.current)) {
          if (layer.data) {
            try {
              const b = turf.bbox(layer.data)
              if (b && b.length === 4 && isFinite(b[0])) {
                if (!combinedBbox) {
                  combinedBbox = [b[0], b[1], b[2], b[3]]
                } else {
                  combinedBbox[0] = Math.min(combinedBbox[0], b[0])
                  combinedBbox[1] = Math.min(combinedBbox[1], b[1])
                  combinedBbox[2] = Math.max(combinedBbox[2], b[2])
                  combinedBbox[3] = Math.max(combinedBbox[3], b[3])
                }
              }
            } catch {}
          }
        }
        if (combinedBbox) {
          boundsToFit = [[combinedBbox[0], combinedBbox[1]], [combinedBbox[2], combinedBbox[3]]]
        }
      }

      if (boundsToFit) {
        const w = boundsToFit[0][0]
        const s = boundsToFit[0][1]
        const e = boundsToFit[1][0]
        const n = boundsToFit[1][1]

        const lngSpan = Math.max(e - w, 0.01)
        const latSpan = Math.max(n - s, 0.01)

        // Expand coordinates by 20% margin on all 4 sides so feature fits completely inside canvas
        const padWest = w - lngSpan * 0.20
        const padEast = e + lngSpan * 0.20
        const padSouth = s - latSpan * 0.20
        const padNorth = n + latSpan * 0.20

        map.fitBounds([[padWest, padSouth], [padEast, padNorth]], { padding: Math.max(padding, 80), animate: false })
      } else {
        map.zoomTo(origZoom - 0.8, { animate: false })
      }

      // Synchronously render the fitted camera scene to the WebGL canvas
      if ((map as any)._render) {
        (map as any)._render()
      }

      const canvas = map.getCanvas()

      // Restore camera view and layer visibility asynchronously after snapshot has been collected
      setTimeout(() => {
        if (mapRef.current) {
          for (const item of savedVisibility) {
            if (mapRef.current.getLayer(item.layerId)) {
              mapRef.current.setLayoutProperty(item.layerId, 'visibility', item.visibility)
            }
          }
          mapRef.current.jumpTo({ center: origCenter, zoom: origZoom, bearing: origBearing, pitch: origPitch })
        }
      }, 150)

      return canvas
    },
  }), [])

  // ── Sync GeoJSON layers ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const desiredIds = new Set(layers.map((l) => l.id))

    for (const id of ownLayerIds.current) {
      if (!desiredIds.has(id)) {
        for (const suffix of ['-fill', '-outline', '-line', '-circle', '-label', '-raster']) {
          if (map.getLayer(`${id}${suffix}`)) map.removeLayer(`${id}${suffix}`)
        }
        if (map.getSource(id)) map.removeSource(id)
        ownLayerIds.current.delete(id)
        layerRevisionRef.current.delete(id)
      }
    }

    for (const layer of layers) {
      const fillOpacity = layer.opacity ?? 0.3
      const hasSelection = selectedLayerIds && selectedLayerIds.size > 0
      const isSelected = !hasSelection || selectedLayerIds.has(layer.id)
      const opacityMultiplier = isSelected ? 1.0 : 0.35

      if (!map.getSource(layer.id)) {
        if (layer.wmsSpec) {
          const { url, layer_name } = layer.wmsSpec
          const sep = url.includes('?') ? '&' : '?'
          const wmsUrl = `${url}${sep}service=WMS&request=GetMap&layers=${encodeURIComponent(layer_name)}&styles=&format=image/png&transparent=true&version=1.1.1&height=256&width=256&srs=EPSG:3857&bbox={bbox-epsg-3857}`
          
          map.addSource(layer.id, {
            type: 'raster',
            tiles: [wmsUrl],
            tileSize: 256,
          })
          map.addLayer({
            id: `${layer.id}-raster`,
            type: 'raster',
            source: layer.id,
            layout: { visibility: layer.visible ? 'visible' : 'none' },
            paint: { 'raster-opacity': (layer.opacity ?? 1.0) * opacityMultiplier },
          })
          ownLayerIds.current.add(layer.id)
        } else if (layer.geeSpec) {
          const { url } = layer.geeSpec
          map.addSource(layer.id, {
            type: 'raster',
            tiles: [url],
            tileSize: 256,
          })
          map.addLayer({
            id: `${layer.id}-raster`,
            type: 'raster',
            source: layer.id,
            layout: { visibility: layer.visible ? 'visible' : 'none' },
            paint: { 'raster-opacity': (layer.opacity ?? 1.0) * opacityMultiplier },
          })
          ownLayerIds.current.add(layer.id)
        } else if (layer.rasterOverlaySpec) {
          const { url, corners } = layer.rasterOverlaySpec
          const valid = corners && corners.every(
            (c) =>
              Array.isArray(c) &&
              c.length >= 2 &&
              typeof c[0] === 'number' &&
              typeof c[1] === 'number' &&
              isFinite(c[0]) &&
              isFinite(c[1]) &&
              c[0] >= -180 &&
              c[0] <= 180 &&
              c[1] >= -90 &&
              c[1] <= 90
          )
          if (valid) {
            const fileUrl = url.startsWith('localfile://') ? url : `localfile://${url}`
            map.addSource(layer.id, {
              type: 'image',
              url: fileUrl,
              coordinates: corners as [[number, number], [number, number], [number, number], [number, number]],
            })
            map.addLayer({
              id: `${layer.id}-raster`,
              type: 'raster',
              source: layer.id,
              layout: { visibility: layer.visible ? 'visible' : 'none' },
              paint: { 'raster-opacity': (layer.opacity ?? 0.8) * opacityMultiplier },
            })
            ownLayerIds.current.add(layer.id)
          } else {
            console.error('Invalid corners for raster source:', corners)
          }
        } else {
          map.addSource(layer.id, { type: 'geojson', data: layer.data })
          ownLayerIds.current.add(layer.id)
          layerRevisionRef.current.set(layer.id, layer.data)

        map.addLayer({
          id: `${layer.id}-fill`,
          type: 'fill',
          source: layer.id,
          filter: [
            'any',
            ['==', ['geometry-type'], 'Polygon'],
            ['==', ['geometry-type'], 'MultiPolygon'],
          ],
          paint: {
            'fill-color': fillColorExpression(layer),
            'fill-opacity': ['*', ['coalesce', ['get', 'fillOpacity'], fillOpacity], opacityMultiplier] as DataDrivenPropertyValueSpecification<number>,
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        map.addLayer({
          id: `${layer.id}-outline`,
          type: 'line',
          source: layer.id,
          filter: [
            'any',
            ['==', ['geometry-type'], 'Polygon'],
            ['==', ['geometry-type'], 'MultiPolygon'],
          ],
          paint: {
            'line-color': lineColorExpression(layer),
            'line-width': layer.styleSpec?.lineWidth ?? layer.lineWidth ?? 2,
            'line-opacity': (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier,
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        map.addLayer({
          id: `${layer.id}-line`,
          type: 'line',
          source: layer.id,
          filter: [
            'any',
            ['==', ['geometry-type'], 'LineString'],
            ['==', ['geometry-type'], 'MultiLineString'],
          ],
          paint: {
            'line-color': lineColorExpression(layer),
            'line-width': ['coalesce', ['get', 'lineWidth'], layer.styleSpec?.lineWidth ?? layer.lineWidth ?? 2] as DataDrivenPropertyValueSpecification<number>,
            'line-opacity': (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier,
            ...(layer.lineDasharray ? { 'line-dasharray': layer.lineDasharray } : {}),
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        map.addLayer({
          id: `${layer.id}-circle`,
          type: 'circle',
          source: layer.id,
          filter: [
            'all',
            [
              'any',
              ['==', ['geometry-type'], 'Point'],
              ['==', ['geometry-type'], 'MultiPoint'],
            ],
            ['!=', ['get', 'role'], 'label'],
          ],
          paint: {
            'circle-color': fillColorExpression(layer),
            'circle-radius': 6,
            'circle-opacity': (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier,
            'circle-stroke-color': lineColorExpression(layer),
            'circle-stroke-width': layer.styleSpec?.lineWidth ?? layer.lineWidth ?? 1.5,
            'circle-stroke-opacity': (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier,
          },
          layout: { visibility: layer.visible ? 'visible' : 'none' },
        })

        // Text labels (symbol layer). Requires the glyphs URL on the style.
        // minzoom keeps low-zoom views uncluttered; collision detection
        // (text-allow-overlap:false + text-optional) drops labels that don't fit.
        const labelSpec = layer.styleSpec?.label
        map.addLayer({
          id: `${layer.id}-label`,
          type: 'symbol',
          source: layer.id,
          minzoom: labelSpec?.minZoom ?? 10,
          layout: {
            'text-field': labelField(layer),
            // Must be a stack the glyphs endpoint actually serves. demotiles
            // provides 'Noto Sans Regular' (NOT 'Open Sans Regular' → 404).
            'text-font': ['Noto Sans Regular'],
            'text-size': labelSpec?.size ?? 12,
            'text-anchor': 'center',
            'text-allow-overlap': false,
            'text-optional': true,
            visibility: layer.visible && labelsActive(layer) ? 'visible' : 'none',
          },
          paint: {
            'text-color': labelSpec?.color ?? '#1f2937',
            'text-halo-color': labelSpec?.haloColor ?? '#ffffff',
            'text-halo-width': 1.2,
            'text-opacity': opacityMultiplier,
          },
        })

        if (layer.data?.features?.[0]?.properties?.source !== 'user_draw') {
          try {
            const bbox = turf.bbox(layer.data) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              map.fitBounds(bbox, { padding: 60, maxZoom: 16, duration: 1000, bearing: map.getBearing(), pitch: map.getPitch() })
            }
          } catch {
            /* ignore invalid bbox */
          }
        }
      }
      } else {
        // Existing source — sync data + visibility + style overrides.
        if (layer.wmsSpec || layer.geeSpec) {
          const vis = layer.visible ? 'visible' : 'none'
          if (map.getLayer(`${layer.id}-raster`)) {
            map.setLayoutProperty(`${layer.id}-raster`, 'visibility', vis)
            map.setPaintProperty(`${layer.id}-raster`, 'raster-opacity', (layer.opacity ?? 1.0) * opacityMultiplier)
          }
        } else if (layer.rasterOverlaySpec) {
          const vis = layer.visible ? 'visible' : 'none'
          if (map.getLayer(`${layer.id}-raster`)) {
            map.setLayoutProperty(`${layer.id}-raster`, 'visibility', vis)
            map.setPaintProperty(`${layer.id}-raster`, 'raster-opacity', (layer.opacity ?? 0.8) * opacityMultiplier)
          }
          const src = map.getSource(layer.id) as maplibregl.ImageSource
          if (src && src.setCoordinates && layer.rasterOverlaySpec.corners) {
            const valid = layer.rasterOverlaySpec.corners.every(
              (c) =>
                Array.isArray(c) &&
                c.length >= 2 &&
                typeof c[0] === 'number' &&
                typeof c[1] === 'number' &&
                isFinite(c[0]) &&
                isFinite(c[1]) &&
                c[0] >= -180 &&
                c[0] <= 180 &&
                c[1] >= -90 &&
                c[1] <= 90
            )
            if (valid) {
              src.setCoordinates(layer.rasterOverlaySpec.corners as [[number, number], [number, number], [number, number], [number, number]])
            } else {
              console.error('Invalid corners for setCoordinates:', layer.rasterOverlaySpec.corners)
            }
          }
        } else {
          const previous = layerRevisionRef.current.get(layer.id)
          if (previous !== layer.data) {
            const src = map.getSource(layer.id) as maplibregl.GeoJSONSource
            src.setData(layer.data)
            layerRevisionRef.current.set(layer.id, layer.data)
          }
          const vis = layer.visible ? 'visible' : 'none'
          for (const suffix of ['-fill', '-outline', '-line', '-circle']) {
            if (map.getLayer(`${layer.id}${suffix}`)) {
              map.setLayoutProperty(`${layer.id}${suffix}`, 'visibility', vis)
            }
          }
          if (map.getLayer(`${layer.id}-fill`)) {
            map.setPaintProperty(`${layer.id}-fill`, 'fill-color', fillColorExpression(layer))
            map.setPaintProperty(
              `${layer.id}-fill`, 'fill-opacity',
              ['*', ['coalesce', ['get', 'fillOpacity'], fillOpacity], opacityMultiplier] as DataDrivenPropertyValueSpecification<number>,
            )
          }
          if (map.getLayer(`${layer.id}-outline`)) {
            map.setPaintProperty(`${layer.id}-outline`, 'line-color', lineColorExpression(layer))
            map.setPaintProperty(`${layer.id}-outline`, 'line-opacity', (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier)
            map.setPaintProperty(`${layer.id}-outline`, 'line-width', layer.styleSpec?.lineWidth ?? layer.lineWidth ?? 2)
          }
          if (map.getLayer(`${layer.id}-line`)) {
            map.setPaintProperty(`${layer.id}-line`, 'line-color', lineColorExpression(layer))
            map.setPaintProperty(`${layer.id}-line`, 'line-opacity', (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier)
            map.setPaintProperty(
              `${layer.id}-line`, 'line-width',
              ['coalesce', ['get', 'lineWidth'], layer.styleSpec?.lineWidth ?? layer.lineWidth ?? 2] as DataDrivenPropertyValueSpecification<number>,
            )
            if (layer.lineDasharray) {
              map.setPaintProperty(`${layer.id}-line`, 'line-dasharray', layer.lineDasharray)
            }
          }
          if (map.getLayer(`${layer.id}-circle`)) {
            map.setPaintProperty(`${layer.id}-circle`, 'circle-color', fillColorExpression(layer))
            map.setPaintProperty(`${layer.id}-circle`, 'circle-opacity', (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier)
            map.setPaintProperty(`${layer.id}-circle`, 'circle-stroke-color', lineColorExpression(layer))
            map.setPaintProperty(`${layer.id}-circle`, 'circle-stroke-width', layer.styleSpec?.lineWidth ?? layer.lineWidth ?? 1.5)
            map.setPaintProperty(`${layer.id}-circle`, 'circle-stroke-opacity', (layer.styleSpec?.opacity ?? layer.opacity ?? 0.8) * opacityMultiplier)
          }
          // Labels: re-apply field/size/color and visibility (gated by enabled +
          // feature cap, AND the layer's own visibility).
          if (map.getLayer(`${layer.id}-label`)) {
            const labelSpec = layer.styleSpec?.label
            map.setLayerZoomRange(`${layer.id}-label`, labelSpec?.minZoom ?? 10, 24)
            map.setLayoutProperty(`${layer.id}-label`, 'text-field', labelField(layer))
            map.setLayoutProperty(`${layer.id}-label`, 'text-size', labelSpec?.size ?? 12)
            map.setLayoutProperty(
              `${layer.id}-label`, 'visibility',
              layer.visible && labelsActive(layer) ? 'visible' : 'none',
            )
            map.setPaintProperty(`${layer.id}-label`, 'text-color', labelSpec?.color ?? '#1f2937')
            map.setPaintProperty(`${layer.id}-label`, 'text-halo-color', labelSpec?.haloColor ?? '#ffffff')
            map.setPaintProperty(`${layer.id}-label`, 'text-opacity', opacityMultiplier)
          }
        }
      }
    }

    // Sync rendering order in MapLibre to match the layers array order
    const style = map.getStyle()
    if (style && style.layers) {
      const ownSubLayerIds = new Set(
        layers.flatMap((l) => [
          `${l.id}-raster`,
          `${l.id}-fill`,
          `${l.id}-outline`,
          `${l.id}-line`,
          `${l.id}-circle`,
          `${l.id}-label`
        ])
      )
      const boundaryLayer = style.layers.find(
        (ly) => ly.id !== 'basemap' && !ownSubLayerIds.has(ly.id)
      )
      const boundaryId = boundaryLayer ? boundaryLayer.id : undefined

      for (const layer of layers) {
        for (const suffix of ['-raster', '-fill', '-outline', '-line', '-circle', '-label']) {
          const subId = `${layer.id}${suffix}`
          if (map.getLayer(subId)) {
            map.moveLayer(subId, boundaryId)
          }
        }
      }
    }
  }, [layers, mapReady, selectedLayerIds])

  // ── Sync selected feature highlight source ──
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const source = map.getSource('selected-feature-highlight') as maplibregl.GeoJSONSource
    if (!source) return

    source.setData({
      type: 'FeatureCollection',
      features: selectedFeatures.map((e) => e.feature),
    })
  }, [selectedFeatures, mapReady])

  // ── Calculate and monitor off-screen indicators (one per selected feature) ──
  //
  // For polygons that *intersect* the viewport we skip the badge and instead
  // drive a pulsing amber edge-glow via requestAnimationFrame (see rAF effect).
  const updateOffScreenIndicators = useCallback(() => {
    const map = mapRef.current
    if (!map || !mapReady) {
      setIndicatorPositions([])
      return
    }
    if (!selectedFeatures.length) {
      setIndicatorPositions([])
      return
    }

    const bounds = map.getBounds()
    const canvas = map.getCanvas()
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    const mapCenter = [map.getCenter().lng, map.getCenter().lat] as [number, number]
    const centerScreen = map.project(new maplibregl.LngLat(mapCenter[0], mapCenter[1]))
    const padding = 24

    const nextPositions: Array<{ x: number; y: number; angle: number; entry: SelectedFeatureEntry }> = []

    for (const entry of selectedFeatures) {
      const geom = entry.feature.geometry
      if (!geom) continue

      // Polygon/MultiPolygon that intersects viewport → no badge (edge glow instead)
      if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
        const b = {
          west: bounds.getWest(),
          south: bounds.getSouth(),
          east: bounds.getEast(),
          north: bounds.getNorth(),
        }
        if (doesPolygonIntersectViewport(geom, b)) continue
      }

      const targetLngLat = getTargetPointForGeometry(geom, mapCenter)
      if (!targetLngLat) continue

      const isInsideViewport = bounds.contains(new maplibregl.LngLat(targetLngLat[0], targetLngLat[1]))
      if (isInsideViewport) continue

      const targetScreen = map.project(new maplibregl.LngLat(targetLngLat[0], targetLngLat[1]))

      const cx = centerScreen.x
      const cy = centerScreen.y
      const tx = targetScreen.x
      const ty = targetScreen.y
      const dx = tx - cx
      const dy = ty - cy

      if (dx === 0 && dy === 0) continue

      // Find intersection of center→target ray with padded viewport boundary
      let t = 1.0

      if (tx < padding) {
        const tl = (padding - cx) / (tx - cx)
        if (tl > 0 && tl < t) t = tl
      } else if (tx > width - padding) {
        const tr = (width - padding - cx) / (tx - cx)
        if (tr > 0 && tr < t) t = tr
      }
      if (ty < padding) {
        const tt = (padding - cy) / (ty - cy)
        if (tt > 0 && tt < t) t = tt
      } else if (ty > height - padding) {
        const tb = (height - padding - cy) / (ty - cy)
        if (tb > 0 && tb < t) t = tb
      }

      if (t < 1.0) {
        nextPositions.push({
          x: cx + t * (tx - cx),
          y: cy + t * (ty - cy),
          angle: Math.atan2(dy, dx),
          entry,
        })
      }
    }

    setIndicatorPositions(nextPositions)
  }, [mapReady, selectedFeatures])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    updateOffScreenIndicators()

    map.on('move', updateOffScreenIndicators)
    map.on('zoom', updateOffScreenIndicators)
    map.on('resize', updateOffScreenIndicators)

    return () => {
      map.off('move', updateOffScreenIndicators)
      map.off('zoom', updateOffScreenIndicators)
      map.off('resize', updateOffScreenIndicators)
    }
  }, [mapReady, selectedFeatures, updateOffScreenIndicators])

  // ── Edge-glow pulse rAF for intersecting-viewport polygons ──
  //
  // Polygons that are partially visible get a pulsing amber outline instead of
  // a badge. We drive the opacity via requestAnimationFrame because MapLibre
  // paint properties must be set imperatively.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    // Find the intersecting polygons
    const bounds = map.getBounds()
    const b = {
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
    }
    const intersecting = selectedFeatures.filter((e) => {
      const g = e.feature.geometry
      return (g.type === 'Polygon' || g.type === 'MultiPolygon') && doesPolygonIntersectViewport(g, b)
    })

    // Update the glow source
    const glowSource = map.getSource('selected-feature-edge-glow') as maplibregl.GeoJSONSource | undefined
    if (glowSource) {
      glowSource.setData({
        type: 'FeatureCollection',
        features: intersecting.map((e) => e.feature),
      })
    }

    if (!intersecting.length) return

    let rafId = 0
    const startTime = performance.now()
    const animate = (now: number) => {
      const t = (now - startTime) / 1000  // seconds
      // Oscillate between 0.35 and 0.9
      const opacity = 0.35 + 0.55 * (0.5 + 0.5 * Math.sin(t * Math.PI * 1.5))
      try {
        if (map.getLayer('selected-feature-edge-glow-line')) {
          map.setPaintProperty('selected-feature-edge-glow-line', 'line-opacity', opacity)
        }
      } catch { /* map may have been removed */ }
      rafId = requestAnimationFrame(animate)
    }
    rafId = requestAnimationFrame(animate)

    return () => cancelAnimationFrame(rafId)
  }, [mapReady, selectedFeatures])

  const handleIndicatorClick = (entry: SelectedFeatureEntry) => {
    const map = mapRef.current
    if (!map || !entry?.feature?.geometry) return

    const geom = entry.feature.geometry
    if (geom.type === 'Point') {
      map.flyTo({
        center: geom.coordinates as [number, number],
        zoom: Math.max(map.getZoom(), 15),
        duration: 1500,
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      })
    } else {
      try {
        const bbox = turf.bbox(geom) as [number, number, number, number]
        if (bbox.every((v) => isFinite(v))) {
          map.fitBounds(bbox, { padding: 80, maxZoom: 16, duration: 1500, bearing: map.getBearing(), pitch: map.getPitch() })
        }
      } catch {
        const centroid = turf.centroid(geom as any)
        map.flyTo({
          center: centroid.geometry.coordinates as [number, number],
          zoom: Math.max(map.getZoom(), 15),
          duration: 1500,
          bearing: map.getBearing(),
          pitch: map.getPitch(),
        })
      }
    }
  }

  // ── Basemap switching ──

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    if (basemap === initBasemapRef.current && map.getSource('basemap')) return

    const { tiles, attribution } = BASEMAPS[basemap] || BASEMAPS.street

    if (map.getLayer('basemap')) map.removeLayer('basemap')
    if (map.getSource('basemap')) map.removeSource('basemap')

    map.addSource('basemap', {
      type: 'raster',
      tiles,
      tileSize: 256,
      attribution,
    })

    map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap', minzoom: 0, maxzoom: 19 })

    const styleLayers = map.getStyle()?.layers
    if (styleLayers && styleLayers.length > 1 && styleLayers[styleLayers.length - 1]?.id === 'basemap') {
      const firstNonBasemap = styleLayers.find((l) => l.id !== 'basemap')
      if (firstNonBasemap) {
        map.moveLayer('basemap', firstNonBasemap.id)
      }
    }

    initBasemapRef.current = basemap
  }, [basemap, mapReady])

  useImperativeHandle(
    ref,
    () => ({
      getCanvas: () => mapRef.current?.getCanvas() ?? null,
      resize: () => mapRef.current?.resize(),
    }),
    [mapReady],
  )

  // ── Sync Pegman marker ──
  const pegmanMarkerRef = useRef<maplibregl.Marker | null>(null)

  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    if (streetViewActive && streetViewLocation) {
      if (!pegmanMarkerRef.current) {
        const el = document.createElement('div')
        el.className = 'pegman-marker'
        el.innerHTML = `
          <div class="pegman-cone"></div>
          <div class="pegman-icon"></div>
        `
        pegmanMarkerRef.current = new maplibregl.Marker({ element: el })
          .setLngLat([streetViewLocation.lng, streetViewLocation.lat])
          .addTo(map)
      } else {
        pegmanMarkerRef.current.setLngLat([streetViewLocation.lng, streetViewLocation.lat])
      }

      const coneEl = pegmanMarkerRef.current.getElement().querySelector('.pegman-cone') as HTMLElement | null
      if (coneEl) {
        coneEl.style.transform = `rotate(${streetViewBearing}deg)`
      }
    } else {
      if (pegmanMarkerRef.current) {
        pegmanMarkerRef.current.remove()
        pegmanMarkerRef.current = null
      }
    }
  }, [streetViewActive, streetViewLocation, streetViewBearing, mapReady])

  useEffect(() => {
    return () => {
      if (pegmanMarkerRef.current) {
        pegmanMarkerRef.current.remove()
        pegmanMarkerRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (
        basemapPanelRef.current &&
        !basemapPanelRef.current.contains(e.target as Node) &&
        (!basemapButtonRef.current || !basemapButtonRef.current.contains(e.target as Node))
      ) {
        setShowBasemaps(false)
      }
    }
    window.addEventListener('click', handleOutsideClick, true)
    return () => {
      window.removeEventListener('click', handleOutsideClick, true)
    }
  }, [])

  // ── Fetch dynamic OSM coverage lines ──
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const fetchCoverage = async () => {
      if (!streetViewDetail) {
        const src = map.getSource('streetview-coverage') as maplibregl.GeoJSONSource | undefined
        if (src) src.setData({ type: 'FeatureCollection', features: [] })
        setZoomTooLow(false)
        return
      }

      const zoom = map.getZoom()
      if (zoom < 13) {
        setZoomTooLow(true)
        const src = map.getSource('streetview-coverage') as maplibregl.GeoJSONSource | undefined
        if (src) src.setData({ type: 'FeatureCollection', features: [] })
        return
      }
      setZoomTooLow(false)

      const bounds = map.getBounds()
      const s = bounds.getSouth()
      const w = bounds.getWest()
      const n = bounds.getNorth()
      const e = bounds.getEast()

      try {
        const res = await fetch(`http://localhost:8765/api/streetview/coverage?s=${s}&w=${w}&n=${n}&e=${e}`)
        const geojson = await res.json()
        const src = map.getSource('streetview-coverage') as maplibregl.GeoJSONSource | undefined
        if (src) src.setData(geojson)
      } catch (err) {
        console.error('Failed to fetch Street View coverage:', err)
      }
    }

    if (streetViewDetail) {
      fetchCoverage()
      map.on('moveend', fetchCoverage)
    } else {
      const src = map.getSource('streetview-coverage') as maplibregl.GeoJSONSource | undefined
      if (src) src.setData({ type: 'FeatureCollection', features: [] })
      setZoomTooLow(false)
    }

    return () => {
      map.off('moveend', fetchCoverage)
    }
  }, [streetViewDetail, mapReady])

  // ── Map actions (all AI-driven actions) ──

  useEffect(() => {
    if (mapActions.length === 0 || !mapRef.current || !mapReady) return
    const map = mapRef.current

    for (const action of mapActions) {
      const { type, payload } = action

      switch (type) {
        case 'fly_to': {
          const { lng, lat, zoom } = payload
          if (
            typeof lng === 'number' &&
            typeof lat === 'number' &&
            isFinite(lng) &&
            isFinite(lat) &&
            lng >= -180 &&
            lng <= 180 &&
            lat >= -90 &&
            lat <= 90
          ) {
            map.flyTo({
              center: [lng, lat],
              zoom: zoom || 15,
              duration: 2000,
              bearing: map.getBearing(),
              pitch: map.getPitch(),
            })
          } else {
            console.error('Invalid coordinates for fly_to:', payload)
          }
          break
        }

        case 'fit_bounds': {
          const { west, south, east, north } = payload
          if (
            typeof west === 'number' &&
            typeof south === 'number' &&
            typeof east === 'number' &&
            typeof north === 'number' &&
            isFinite(west) &&
            isFinite(south) &&
            isFinite(east) &&
            isFinite(north) &&
            west >= -180 &&
            west <= 180 &&
            east >= -180 &&
            east <= 180 &&
            south >= -90 &&
            south <= 90 &&
            north >= -90 &&
            north <= 90
          ) {
            map.fitBounds(
              [
                [west, south],
                [east, north],
              ],
              { padding: 60, duration: 1500, bearing: map.getBearing(), pitch: map.getPitch() },
            )
          } else {
            console.error('Invalid bounds for fit_bounds:', payload)
          }
          break
        }

        case 'add_raster_overlay': {
          const { corners } = payload
          if (Array.isArray(corners) && corners.length > 0) {
            const valid = corners.every(
              (c) =>
                Array.isArray(c) &&
                c.length >= 2 &&
                typeof c[0] === 'number' &&
                typeof c[1] === 'number' &&
                isFinite(c[0]) &&
                isFinite(c[1]) &&
                c[0] >= -180 &&
                c[0] <= 180 &&
                c[1] >= -90 &&
                c[1] <= 90
            )
            if (valid) {
              const lngs = corners.map((c) => c[0])
              const lats = corners.map((c) => c[1])
              map.fitBounds(
                [
                  [Math.min(...lngs), Math.min(...lats)],
                  [Math.max(...lngs), Math.max(...lats)],
                ],
                { padding: 60, duration: 1500, bearing: map.getBearing(), pitch: map.getPitch() },
              )
            } else {
              console.error('Invalid corners for add_raster_overlay:', corners)
            }
          }
          break
        }

        case 'set_view':
          map.jumpTo({
            center: payload.center,
            zoom: payload.zoom,
            bearing: payload.bearing !== undefined ? payload.bearing : map.getBearing(),
            pitch: payload.pitch !== undefined ? payload.pitch : map.getPitch(),
          })
          break

        // add_marker / add_markers / clear_markers / draw_line / draw_polygon /
        // draw_circle are intercepted in App.tsx and routed through upsertLayer
        // so the data lives in React state and survives reload. MapView no
        // longer handles them directly.

        case 'highlight_features': {
          const { layer_name, property_name, property_value } = payload
          const target = layers.find(
            (l) => l.name.toLowerCase() === layer_name?.toLowerCase(),
          )
          if (!target) break

          const filtered = (target.data.features || []).filter(
            (f: Feature) =>
              String(f.properties?.[property_name]) === String(property_value),
          )
          if (filtered.length === 0) break

          const hlId = 'highlight-temp'
          for (const suffix of ['-fill', '-line', '-circle']) {
            if (map.getLayer(`${hlId}${suffix}`)) map.removeLayer(`${hlId}${suffix}`)
          }
          if (map.getSource(hlId)) map.removeSource(hlId)

          map.addSource(hlId, {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: filtered },
          })
          map.addLayer({
            id: `${hlId}-fill`,
            type: 'fill',
            source: hlId,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Polygon'],
              ['==', ['geometry-type'], 'MultiPolygon'],
            ],
            paint: { 'fill-color': '#ffff00', 'fill-opacity': 0.5 },
          })
          map.addLayer({
            id: `${hlId}-line`,
            type: 'line',
            source: hlId,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Polygon'],
              ['==', ['geometry-type'], 'MultiPolygon'],
              ['==', ['geometry-type'], 'LineString'],
              ['==', ['geometry-type'], 'MultiLineString'],
            ],
            paint: { 'line-color': '#ffff00', 'line-width': 3 },
          })
          map.addLayer({
            id: `${hlId}-circle`,
            type: 'circle',
            source: hlId,
            filter: [
              'any',
              ['==', ['geometry-type'], 'Point'],
              ['==', ['geometry-type'], 'MultiPoint'],
            ],
            paint: {
              'circle-color': '#ffff00',
              'circle-radius': 9,
              'circle-stroke-color': '#000000',
              'circle-stroke-width': 2,
            },
          })

          try {
            const bbox = turf.bbox({
              type: 'FeatureCollection',
              features: filtered,
            }) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              map.fitBounds(bbox, { padding: 60, maxZoom: 16, duration: 1000, bearing: map.getBearing(), pitch: map.getPitch() })
            }
          } catch {
            /* ignore */
          }
          setTimeout(() => {
            if (!mapRef.current) return
            const m = mapRef.current
            for (const suffix of ['-fill', '-line', '-circle']) {
              if (m.getLayer(`${hlId}${suffix}`)) m.removeLayer(`${hlId}${suffix}`)
            }
            if (m.getSource(hlId)) m.removeSource(hlId)
          }, 10000)
          break
        }

        case 'set_layer_style': {
          // Style changes belong in React state so they survive a project
          // reload. App.tsx persists fillColor/lineColor/opacity onto the
          // layer and the layer-sync effect re-applies on the next render.
          onLayerStyleChangeRef.current?.(payload.layer_name, {
            fillColor: payload.fill_color,
            lineColor: payload.line_color,
            opacity: payload.opacity,
          })
          break
        }

        default:
          break
      }
    }

    onActionsProcessed()
  }, [mapActions, mapReady, layers]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Context menu dismissal (Escape / outside click) ──

  useEffect(() => {
    if (!ctxMenu) return
    const close = () => setCtxMenu(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setCtxMenu(null) }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', onKey)
    }
  }, [ctxMenu])

  // ── Drawing tool ──
  //
  // A dedicated `__draw__` source + layers hold the in-progress draft. It is
  // NOT in `layers`, so the layer-sync effect never touches it. On finish the
  // geometry is handed to onDrawComplete, which promotes it to a real layer.

  const DRAW_SRC = '__draw__'

  const featurePointCoordinates = (feature: { geometry?: Geometry | null }): number[] | null => {
    const geometry = feature.geometry
    if (geometry?.type !== 'Point') return null
    const coords = geometry.coordinates
    return Number.isFinite(coords[0]) && Number.isFinite(coords[1]) ? coords : null
  }

  const isRoadFeature = (feature?: Feature | null): boolean => {
    const type = feature?.geometry?.type
    return type === 'LineString' || type === 'MultiLineString'
  }

  const redrawDraft = useCallback(() => {
    const map = mapRef.current
    if (!map) return
    const src = map.getSource(DRAW_SRC) as maplibregl.GeoJSONSource | undefined
    if (!src) return
    const verts = drawVerticesRef.current
    const mode = drawModeRef.current
    const features: Feature[] = []
    // Vertices as points.
    for (const v of verts) {
      features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: v }, properties: {} })
    }
    // Draft line / polygon outline.
    if (mode === 'line' && verts.length >= 2) {
      features.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: verts }, properties: {} })
    } else if (mode === 'polygon' && verts.length >= 2) {
      const ring = verts.length >= 3 ? [...verts, verts[0]] : verts
      features.push({
        type: 'Feature',
        geometry: verts.length >= 3
          ? { type: 'Polygon', coordinates: [ring] }
          : { type: 'LineString', coordinates: verts },
        properties: {},
      })
    }
    src.setData({ type: 'FeatureCollection', features })
  }, [])

  const finishDraw = useCallback(() => {
    const mode = drawModeRef.current
    const verts = drawVerticesRef.current
    if (!mode) return
    const min = mode === 'point' ? 1 : mode === 'line' ? 2 : 3
    if (verts.length >= min) {
      onDrawCompleteRef.current?.(mode, verts)
    }
    drawModeRef.current = null
    drawVerticesRef.current = []
    drawVerticesHistoryRef.current = []
    drawRedoHistoryRef.current = []
    setDrawMode(null)
    setDrawCount(0)
    redrawDraft()
    const map = mapRef.current
    if (map) { map.getCanvas().style.cursor = ''; map.doubleClickZoom.enable() }
  }, [redrawDraft])

  const cancelDraw = useCallback(() => {
    drawModeRef.current = null
    drawVerticesRef.current = []
    drawVerticesHistoryRef.current = []
    drawRedoHistoryRef.current = []
    setDrawMode(null)
    setDrawCount(0)
    redrawDraft()
    const map = mapRef.current
    if (map) { map.getCanvas().style.cursor = ''; map.doubleClickZoom.enable() }
  }, [redrawDraft])

  const startDraw = useCallback((mode: Exclude<DrawMode, null>) => {
    // Toggle off if the same tool is reselected.
    if (drawModeRef.current === mode) { cancelDraw(); return }
    drawModeRef.current = mode
    drawVerticesRef.current = []
    drawVerticesHistoryRef.current = []
    drawRedoHistoryRef.current = []
    setDrawMode(mode)
    setDrawCount(0)
    redrawDraft()
    const map = mapRef.current
    if (map) {
      map.getCanvas().style.cursor = 'crosshair'
      // Stop dblclick (used to finish a shape) from also zooming the map.
      map.doubleClickZoom.disable()
    }
  }, [cancelDraw, redrawDraft])

  const handleDrawUndo = useCallback(() => {
    if (drawVerticesHistoryRef.current.length === 0) return
    const prev = drawVerticesHistoryRef.current.pop()!
    drawRedoHistoryRef.current.push([...drawVerticesRef.current])
    drawVerticesRef.current = prev
    setDrawCount(prev.length)
    redrawDraft()
  }, [redrawDraft])

  const handleDrawRedo = useCallback(() => {
    if (drawRedoHistoryRef.current.length === 0) return
    const next = drawRedoHistoryRef.current.pop()!
    drawVerticesHistoryRef.current.push([...drawVerticesRef.current])
    drawVerticesRef.current = next
    setDrawCount(next.length)
    redrawDraft()
  }, [redrawDraft])

  // Set up the draft source/layers + bind draw event handlers once the map is
  // ready. Handlers read drawMode/vertices from refs, so they never go stale.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    if (!map.getSource(DRAW_SRC)) {
      map.addSource(DRAW_SRC, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({
        id: '__draw__-fill', type: 'fill', source: DRAW_SRC,
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: { 'fill-color': '#2563eb', 'fill-opacity': 0.15 },
      })
      map.addLayer({
        id: '__draw__-line', type: 'line', source: DRAW_SRC,
        filter: ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'Polygon']],
        paint: { 'line-color': '#2563eb', 'line-width': 2.5 },
      })
      map.addLayer({
        id: '__draw__-vertex', type: 'circle', source: DRAW_SRC,
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-radius': 5, 'circle-color': '#ffffff',
          'circle-stroke-color': '#2563eb', 'circle-stroke-width': 2,
        },
      })
    }

    // ── WMS GetFeatureInfo helper ──
    // All requests go through the backend proxy at /api/wms/featureinfo to
    // avoid CORS restrictions imposed by external WMS servers.
    const fireWmsGetFeatureInfo = async (e: maplibregl.MapMouseEvent) => {
      const wmsLayers = layersRef.current.filter((l) => l.wmsSpec && l.visible)
      if (!wmsLayers.length) return false

      const size = map.getContainer().getBoundingClientRect()
      const w = Math.round(size.width)
      const h = Math.round(size.height)
      const { x, y } = e.point
      const bounds = map.getBounds()
      // WMS 1.1.1 bbox order: west,south,east,north (EPSG:4326)
      const bbox = [
        bounds.getWest(), bounds.getSouth(),
        bounds.getEast(), bounds.getNorth(),
      ].join(',')

      // Show loading cursor while waiting for the server
      map.getCanvas().style.cursor = 'wait'

      const results: Array<{ name: string; html: string }> = []

      await Promise.all(
        wmsLayers.map(async (layer) => {
          const { url, layer_name } = layer.wmsSpec!

          // Detect WMS version: some servers embed their version in the URL
          // (e.g. ?VERSION=1.3.0). Default to 1.1.1 which is universally supported.
          const detectedVersion =
            /VERSION=1\.3\.0/i.test(url) ? '1.3.0' : '1.1.1'

          const proxyUrl =
            `http://localhost:8765/api/wms/featureinfo` +
            `?url=${encodeURIComponent(url)}` +
            `&layer_name=${encodeURIComponent(layer_name)}` +
            `&bbox=${encodeURIComponent(bbox)}` +
            `&width=${w}&height=${h}` +
            `&x=${Math.round(x)}&y=${Math.round(y)}` +
            `&version=${detectedVersion}` +
            `&feature_count=5`

          try {
            const res = await fetch(proxyUrl)
            if (!res.ok) return
            const json = await res.json()
            const feats: any[] = json?.features ?? []
            if (!feats.length) return

            const html = feats
              .slice(0, 3)
              .map((f) => popupHtmlForProps(f.properties ?? {}))
              .filter(Boolean)
              .join('<hr class="mv-popup-divider">')

            if (html) results.push({ name: layer.name, html })
          } catch {
            /* backend unreachable or layer has no data at this point */
          }
        }),
      )

      // Restore cursor regardless of result
      map.getCanvas().style.cursor = ''

      if (!results.length) return false

      const combined = results
        .map((r) =>
          `<div class="mv-popup-title">${escapeHtml(r.name)}</div>${r.html}`,
        )
        .join('<hr class="mv-popup-divider">')

      new maplibregl.Popup({
        closeButton: true,
        closeOnClick: false,
        offset: 12,
        className: 'mv-hover-popup mv-wms-popup',
        maxWidth: '320px',
      })
        .setLngLat(e.lngLat)
        .setHTML(combined)
        .addTo(map)

      return true
    }

    const onClick = (e: maplibregl.MapMouseEvent) => {
      const mode = drawModeRef.current
      if (!mode) {
        if (streetViewDetail) {
          const bbox: [maplibregl.PointLike, maplibregl.PointLike] = [
            [e.point.x - 8, e.point.y - 8],
            [e.point.x + 8, e.point.y + 8]
          ]
          const features = map.queryRenderedFeatures(bbox, { layers: ['streetview-coverage-layer'] })
          if (features.length > 0) {
            onOpenStreetViewRef.current?.(e.lngLat.lng, e.lngLat.lat)
            return
          }
        }
        // Contextual query handling
        if (e.originalEvent?.ctrlKey || e.originalEvent?.metaKey) {
          const ids = renderLayerIds()
          if (!ids.length) return
          const feats = map.queryRenderedFeatures(e.point, { layers: ids })
          if (feats.length > 0) {
            const feat = feats[0]
            onContextualQueryRef.current?.(feat, e.lngLat)

            // Visual feedback: Highlight the clicked feature in cyan
            const hlId = 'highlight-temp'
            for (const suffix of ['-fill', '-line', '-circle']) {
              if (map.getLayer(`${hlId}${suffix}`)) map.removeLayer(`${hlId}${suffix}`)
            }
            if (map.getSource(hlId)) map.removeSource(hlId)

            map.addSource(hlId, {
              type: 'geojson',
              data: { type: 'FeatureCollection', features: [feat] },
            })
            map.addLayer({
              id: `${hlId}-fill`,
              type: 'fill',
              source: hlId,
              filter: ['any', ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'MultiPolygon']],
              paint: { 'fill-color': '#06b6d4', 'fill-opacity': 0.35 },
            })
            map.addLayer({
              id: `${hlId}-line`,
              type: 'line',
              source: hlId,
              filter: ['any', ['==', ['geometry-type'], 'LineString'], ['==', ['geometry-type'], 'Polygon'], ['==', ['geometry-type'], 'MultiPolygon']],
              paint: { 'line-color': '#06b6d4', 'line-width': 4 },
            })
            map.addLayer({
              id: `${hlId}-circle`,
              type: 'circle',
              source: hlId,
              filter: ['==', ['geometry-type'], 'Point'],
              paint: {
                'circle-radius': 8,
                'circle-color': '#06b6d4',
                'circle-stroke-color': '#ffffff',
                'circle-stroke-width': 2,
              },
            })
          }
        } else {
          // Fire WMS GetFeatureInfo first; if it returns data, skip the rest.
          fireWmsGetFeatureInfo(e)

          // Clear visual feedback if clicked elsewhere without ctrl/meta key
          const hlId = 'highlight-temp'
          for (const suffix of ['-fill', '-line', '-circle']) {
            if (map.getLayer(`${hlId}${suffix}`)) map.removeLayer(`${hlId}${suffix}`)
          }
          if (map.getSource(hlId)) map.removeSource(hlId)

          // Plain/Shift click: select or toggle feature for off-screen indicator
          const ids = renderLayerIds()
          if (ids.length) {
            const box = 5
            const queryTarget: [maplibregl.PointLike, maplibregl.PointLike] = [
              [e.point.x - box, e.point.y - box],
              [e.point.x + box, e.point.y + box],
            ]
            const feats = map.queryRenderedFeatures(queryTarget, { layers: ids })
            if (feats.length > 0) {
              const feat = feats[0]
              // Find which layer this feature belongs to
              const matchingLayer = layersRef.current.find((l) => {
                for (const suffix of ['-fill', '-outline', '-line', '-circle']) {
                  if (feat.layer?.id === `${l.id}${suffix}`) return true
                }
                return false
              })
              if (matchingLayer) {
                const layerFeatures: Feature[] = matchingLayer.data?.features || []
                let fullFeature: Feature

                if (layerFeatures.length > 1) {
                  const geoms = layerFeatures.map((f) => f.geometry).filter(Boolean)
                  let combinedGeometry: Geometry
                  if (geoms.every((g) => g.type === 'Polygon')) {
                    combinedGeometry = {
                      type: 'MultiPolygon',
                      coordinates: geoms.map((g: any) => g.coordinates),
                    }
                  } else if (geoms.every((g) => g.type === 'Point')) {
                    combinedGeometry = {
                      type: 'MultiPoint',
                      coordinates: geoms.map((g: any) => g.coordinates),
                    }
                  } else if (geoms.every((g) => g.type === 'LineString')) {
                    combinedGeometry = {
                      type: 'MultiLineString',
                      coordinates: geoms.map((g: any) => g.coordinates),
                    }
                  } else {
                    combinedGeometry = JSON.parse(JSON.stringify(feat.geometry))
                  }

                  const firstProps = layerFeatures[0]?.properties || {}
                  const clickedProps = feat.properties || {}
                  const mergedProps = {
                    ...firstProps,
                    ...clickedProps,
                    layer_name: matchingLayer.name,
                    total_feature_count: layerFeatures.length,
                  }

                  fullFeature = {
                    type: 'Feature',
                    geometry: combinedGeometry,
                    properties: mergedProps,
                  }
                } else {
                  fullFeature = {
                    type: 'Feature',
                    geometry: JSON.parse(JSON.stringify(feat.geometry)),
                    properties: { ...(feat.properties || {}), layer_name: matchingLayer.name },
                  }
                }

                onSelectFeature?.(
                  { feature: fullFeature, layerId: matchingLayer.id, layerName: matchingLayer.name },
                  e.originalEvent.shiftKey,
                )
              } else if (!e.originalEvent.shiftKey) {
                onSelectFeature?.(null, false)
              }
            } else if (!e.originalEvent.shiftKey) {
              onSelectFeature?.(null, false)
            }
          } else if (!e.originalEvent.shiftKey) {
            onSelectFeature?.(null, false)
          }
        }
        return
      }
      const pt = [e.lngLat.lng, e.lngLat.lat]
      if (mode === 'point') {
        drawVerticesRef.current = [pt]
        finishDraw()
        return
      }
      drawVerticesHistoryRef.current.push([...drawVerticesRef.current])
      drawRedoHistoryRef.current = []
      drawVerticesRef.current = [...drawVerticesRef.current, pt]
      setDrawCount(drawVerticesRef.current.length)
      redrawDraft()
    }
    const onDblClick = (e: maplibregl.MapMouseEvent) => {
      if (!drawModeRef.current || drawModeRef.current === 'point') return
      e.preventDefault()
      finishDraw()
    }

    map.on('click', onClick)
    map.on('dblclick', onDblClick)
    return () => {
      map.off('click', onClick)
      map.off('dblclick', onDblClick)
    }
  }, [mapReady, finishDraw, redrawDraft, streetViewDetail])

  // ── Hover popups ──
  // Any feature in one of our layers (AI markers, AI-drawn shapes, user-drawn
  // shapes, loaded GeoJSON) shows a popup on hover built from its properties.
  // Bound once; the handler reads the live layer set from ownLayerIds.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return

    const hidePopup = () => {
      hoverPopupRef.current?.remove()
      hoverPopupRef.current = null
      map.getCanvas().style.cursor = ''
    }

    const onMouseMove = (e: maplibregl.MapMouseEvent) => {
      // Drawing takes over the cursor and clicks; don't fight it.
      if (drawModeRef.current) return hidePopup()

      // If any visible WMS layer is present show crosshair to hint GetFeatureInfo
      const hasVisibleWms = layersRef.current.some((l) => l.wmsSpec && l.visible)
      if (hasVisibleWms && !hoverPopupRef.current) {
        map.getCanvas().style.cursor = 'crosshair'
      }

      const ids = renderLayerIds()
      if (!ids.length) {
        if (!hasVisibleWms) hidePopup()
        return
      }
      const feats = map.queryRenderedFeatures(e.point, { layers: ids })
      const html = feats.length ? popupHtmlForProps(feats[0].properties) : ''
      if (!html) {
        if (!hasVisibleWms) hidePopup()
        return
      }

      map.getCanvas().style.cursor = 'pointer'
      if (!hoverPopupRef.current) {
        hoverPopupRef.current = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 12,
          className: 'mv-hover-popup',
        }).addTo(map)
      }
      hoverPopupRef.current.setLngLat(e.lngLat).setHTML(html)
    }

    map.on('mousemove', onMouseMove)
    map.on('mouseout', hidePopup)
    return () => {
      map.off('mousemove', onMouseMove)
      map.off('mouseout', hidePopup)
      hidePopup()
    }
  }, [mapReady])


  // Keyboard: Enter finishes, Escape cancels, Backspace removes last vertex.
  useEffect(() => {
    if (!drawMode) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Enter') { e.preventDefault(); finishDraw() }
      else if (e.key === 'Escape') { e.preventDefault(); cancelDraw() }
      else if (e.key === 'Backspace') {
        e.preventDefault()
        handleDrawUndo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawMode, finishDraw, cancelDraw, handleDrawUndo])

  // Keyboard: Escape clears feature selection (when not in draw mode)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !drawModeRef.current) {
        onSelectFeature?.(null, false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onSelectFeature])

  // ── Geocoding search ──

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      // Proxy through the backend — browsers can't set the User-Agent that
      // Nominatim's usage policy requires.
      const googleKey = await window.electronAPI.getGoogleMapsKey()
      const headers: Record<string, string> = {}
      if (googleKey) {
        headers['x-google-maps-key'] = googleKey
      }
      const resp = await fetch(
        `http://localhost:8765/api/geocode?query=${encodeURIComponent(searchQuery)}&limit=5`,
        { headers }
      )
      const data = await resp.json()
      const results: NominatimSearchResult[] = (data?.results || [])
        .filter((r: { lat: number | null; lon: number | null }) => r.lat != null && r.lon != null)
        .map((r: { display_name: string; lat: number; lon: number }) => ({
          display_name: r.display_name,
          lat: String(r.lat),
          lon: String(r.lon),
        }))

      // Check Street View availability (radius=150m) concurrently for each result
      const resultsWithSv = await Promise.all(
        results.map(async (r) => {
          try {
            const metaResp = await fetch(
              `http://localhost:8765/api/streetview/meta?lat=${parseFloat(r.lat)}&lng=${parseFloat(r.lon)}&radius=150`
            )
            if (metaResp.ok) {
              const meta = await metaResp.json()
              return { ...r, hasStreetView: !!meta.found }
            }
          } catch (e) {
            console.error('Failed to fetch street view metadata:', e)
          }
          return { ...r, hasStreetView: false }
        })
      )

      setSearchResults(resultsWithSv)
    } catch {
      setSearchResults([])
    }
  }

  const flyToResult = (result: NominatimSearchResult) => {
    const map = mapRef.current
    if (!map) return
    map.flyTo({
      center: [parseFloat(result.lon), parseFloat(result.lat)],
      zoom: 15,
      duration: 2000,
      bearing: map.getBearing(),
      pitch: map.getPitch(),
    })
    setSearchResults([])
    setShowSearch(false)
    setSearchQuery('')
  }

  return (
    <div className={`map-view ${isMiniMap ? 'is-mini-map' : ''}`}>
      <div ref={containerRef} className="map-container" />

      {/* ── Off-screen Feature Indicators (one per off-screen selected feature) ── */}
      {!isMiniMap && indicatorPositions.map((ind, idx) => {
        const { feature } = ind.entry
        const label =
          feature.properties?.label ||
          feature.properties?.name ||
          feature.properties?.title ||
          feature.geometry?.type ||
          'Feature'
        return (
          <button
            key={idx}
            className="offscreen-indicator-badge"
            style={{ left: ind.x, top: ind.y }}
            onClick={() => handleIndicatorClick(ind.entry)}
            title={`Click to fly to: ${label}`}
          >
            <span
              className="offscreen-indicator-arrow"
              style={{ transform: `rotate(${ind.angle}rad)` }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </span>
            <span className="offscreen-indicator-text">{label}</span>
          </button>
        )
      })}

      {/* ── Toolbar ── */}
      <div className="map-toolbar">
        <button
          className={`toolbar-btn ${showSearch ? 'active' : ''}`}
          onClick={() => {
            setShowSearch(!showSearch)
            setShowBasemaps(false)
          }}
          title="Search"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </button>

        <div className="toolbar-divider" />

        <button
          className={`toolbar-btn ${drawMode === 'point' ? 'active' : ''}`}
          onClick={() => startDraw('point')}
          title="Draw point"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
        </button>
        <button
          className={`toolbar-btn ${drawMode === 'line' ? 'active' : ''}`}
          onClick={() => startDraw('line')}
          title="Draw line"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="4" y1="20" x2="20" y2="4" />
          </svg>
        </button>
        <button
          className={`toolbar-btn ${drawMode === 'polygon' ? 'active' : ''}`}
          onClick={() => startDraw('polygon')}
          title="Draw polygon"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="12 2 22 8.5 18 19.5 6 19.5 2 8.5" />
          </svg>
        </button>

        <div className="toolbar-spacer" />

        <button
          className="toolbar-btn"
          onClick={onUndo}
          disabled={!canUndo}
          title="Undo (Ctrl+Z)"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 7v6h6" />
            <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" />
          </svg>
        </button>
        <button
          className="toolbar-btn"
          onClick={onRedo}
          disabled={!canRedo}
          title="Redo (Ctrl+Y)"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 7v6h-6" />
            <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3l3 2.7" />
          </svg>
        </button>

        <div className="toolbar-divider" />

        <button
          ref={basemapButtonRef}
          className={`toolbar-btn ${showBasemaps ? 'active' : ''}`}
          onClick={() => {
            setShowBasemaps(!showBasemaps)
            setShowSearch(false)
          }}
          title="Basemaps"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" />
            <line x1="9" y1="3" x2="9" y2="18" />
            <line x1="15" y1="6" x2="15" y2="21" />
          </svg>
        </button>
      </div>

      {/* ── Draw helper bar ── */}
      {drawMode && (
        <div className={`draw-bar ${showSearch ? 'has-search' : ''}`}>
          <span className="draw-icon" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', opacity: 0.85 }}>
            {drawMode === 'point' ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
            ) : drawMode === 'line' ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="4" y1="20" x2="20" y2="4" />
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="12 2 22 8.5 18 19.5 6 19.5 2 8.5" />
              </svg>
            )}
          </span>
          <span className="draw-hint">
            {drawMode === 'point' ? (
              'Click the map to place a point.'
            ) : (
              <>
                <div>Click to add vertices ({drawCount}).</div>
                <div style={{ opacity: 0.7, fontSize: '11px' }}>
                  Double-click or Enter to finish, Esc to cancel.
                </div>
              </>
            )}
          </span>
          {drawMode !== 'point' && (
            <button
              className="draw-finish"
              onClick={finishDraw}
              disabled={drawCount < (drawMode === 'line' ? 2 : 3)}
            >
              Finish
            </button>
          )}
          <button className="draw-cancel" onClick={cancelDraw}>Cancel</button>
        </div>
      )}

      {/* ── Search panel ── */}
      {showSearch && (
        <div className="search-panel">
          <div className="search-input-row">
            <input
              className="search-input"
              placeholder="Search for a place..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              autoFocus
            />
            <button className="search-go" onClick={handleSearch}>
              Go
            </button>
          </div>
          {searchResults.length > 0 && (
            <div className="search-results">
              {searchResults.map((r, i) => (
                <div key={i} className="search-result" onClick={() => flyToResult(r)}>
                  <span>{r.display_name}</span>
                  {r.hasStreetView && (
                    <button
                      className="search-result-action"
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpenStreetViewRef.current?.(parseFloat(r.lon), parseFloat(r.lat))
                        flyToResult(r)
                      }}
                    >
                      Street View
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Basemap switcher ── */}
      {showBasemaps && (
        <div ref={basemapPanelRef} className="basemap-panel-redesigned">
          
          
          <div className="basemap-section">
            <div className="section-title">Map type</div>
            <div className="map-type-grid">
              <button
                className={`map-type-card ${basemap === 'street' ? 'active' : ''}`}
                onClick={() => onBasemapChange('street')}
              >
                <div className="map-type-thumb default-thumb"></div>
                <span>Default</span>
              </button>
              <button
                className={`map-type-card ${basemap === 'satellite' ? 'active' : ''}`}
                onClick={() => onBasemapChange('satellite')}
              >
                <div className="map-type-thumb satellite-thumb"></div>
                <span>Satellite</span>
              </button>
              <button
                className={`map-type-card ${basemap === 'terrain' ? 'active' : ''}`}
                onClick={() => onBasemapChange('terrain')}
              >
                <div className="map-type-thumb terrain-thumb"></div>
                <span>Terrain</span>
              </button>
            </div>
            
            <div className="other-types-row">
              {Object.entries(BASEMAPS)
                .filter(([key]) => !['street', 'satellite', 'terrain'].includes(key))
                .map(([key, info]) => (
                  <button
                    key={key}
                    className={`other-type-btn ${basemap === key ? 'active' : ''}`}
                    onClick={() => onBasemapChange(key)}
                  >
                    {info.name}
                  </button>
                ))
              }
            </div>
          </div>

          <div className="basemap-section">
            <div className="section-title">Map details</div>
            <div className="map-details-grid">
              <button
                className={`detail-toggle-btn ${streetViewDetail ? 'active' : ''}`}
                onClick={() => onStreetViewDetailChange(!streetViewDetail)}
              >
                <div className="detail-toggle-icon streetview-icon-bg">
                  <div className="pegman-mini-icon"></div>
                </div>
                <span>Street View</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {isMiniMap && (
        <button
          className="minimap-split-toggle"
          onClick={() => onStreetViewLayoutChange?.('split')}
          title="Split screen"
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
            <path d="M4 4h8V2H4a2 2 0 00-2 2v8h2V4zm16 16h-8v2h8a2 2 0 002-2v-8h-2v8z"/>
          </svg>
        </button>
      )}

      {/* ── Right-click context menu ── */}
      {ctxMenu && (
        <>
          <div
            className="map-context-dot"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
          />
          <div
            className="map-context-menu"
            style={{ left: ctxMenu.x, top: ctxMenu.y }}
            onClick={(e) => e.stopPropagation()}
          >
          <button
            className="ctx-item"
            onClick={() => { onAddMarkerRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            📍 Add marker here
          </button>
          {streetViewDetail && (
            <button
              className="ctx-item"
              onClick={() => { onOpenStreetViewRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
            >
              🛣 Street View
            </button>
          )}
          {streetViewDetail && isRoadFeature(ctxMenu.feature) && (
            <button
              className="ctx-item"
              onClick={() => { onInspectRoadRef.current?.(ctxMenu.feature!); setCtxMenu(null) }}
            >
              Inspect Road
            </button>
          )}
          <button
            className="ctx-item"
            onClick={() => { onAskChatRef.current?.(ctxMenu.lng, ctxMenu.lat); setCtxMenu(null) }}
          >
            💬 Ask chat about this place
          </button>
        </div>
        </>
      )}

      {/* ── Street View Legend Card ── */}
      {streetViewDetail && (
        <div className="streetview-legend-card">
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-line" />
              <span className="legend-text">Street View Coverage</span>
            </div>
            <div className="legend-hint">
              {zoomTooLow ? 'Zoom in to view coverage lines' : 'Click highlighted areas to view 360° imagery'}
            </div>
          </div>
        </div>
      )}

    </div>
  )
})

export default MapView
