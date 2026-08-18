import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import * as turf from '@turf/turf'
import type { Feature, FeatureCollection, Geometry, Polygon, MultiPolygon } from 'geojson'
import MapView, { type MapViewHandle } from './components/MapView'
import FileTree from './components/FileTree'
import ChatPanel, { type ChatPanelHandle } from './components/ChatPanel'
import StreetViewWorkspace, {
  type RoadInspectionTarget,
  type StreetViewTarget,
} from './components/StreetViewWorkspace'
import ArtifactsPanel from './components/ArtifactsPanel'
import LayerPanel from './components/LayerPanel'
import SymbologyPanel from './components/SymbologyPanel'
import AttributeTable from './components/AttributeTable'
import Legend from './components/Legend'
import BookmarkPanel from './components/BookmarkPanel'
import ExportPanel from './components/ExportPanel'
import ZoningPanel from './components/ZoningPanel'
import ScenarioPanel, { type Scenario } from './components/ScenarioPanel'
import ScenarioBuilderPanel from './components/ScenarioBuilderPanel'

import DocumentView, { type DocumentImage, type OpenDocument } from './components/DocumentView'
import ErrorBoundary from './components/ErrorBoundary'
import DiagnosticsPanel from './components/DiagnosticsPanel'
import appIcon from './assets/icon.png'
import {
  GeoJSONLayer,
  MapViewState,
  Conversation,
  MapAction,
  MapContext,
  ProjectData,
  LAYER_COLORS,
  BASEMAPS,
  MapBookmark,
  BoundaryGeometry,
  LayerGeometryData,
  LayerStyleSpec,
  SelectedFeatureEntry,
} from './types'
import {
  computeBreaks,
  buildCategories,
  rampColorsForClasses,
  DEFAULT_RAMP,
} from './lib/classify'
import { composeFigure } from './lib/compose-figure'
import { buildLegendEntries } from './lib/legend-data'

type LeftTab = 'files' | 'layers' | 'bookmarks' | 'export' | 'zoning' | 'scenarios'
type AppMode = 'map' | 'document' | 'artifacts'

function genId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

type MarkerInput = {
  lat: number
  lng: number
  label?: string
  color?: string
  description?: string
}

function markerFeature(marker: MarkerInput): Feature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [marker.lng, marker.lat] },
    properties: {
      label: marker.label || '',
      ...(marker.description ? { description: marker.description } : {}),
      ...(marker.color ? { fillColor: marker.color, strokeColor: marker.color } : {}),
      source: 'ai_marker',
    },
  }
}

function pointFeatureName(feature: Feature, fallback: string): string {
  const props = feature.properties || {}
  for (const key of ['label', 'name', 'title', 'display_name', 'address', 'id']) {
    const value = props[key]
    if (value != null && String(value).trim()) return String(value).trim()
  }
  return fallback
}

function isPointOnlyCollection(data: FeatureCollection): boolean {
  const features = data.features || []
  return features.length > 1 && features.every((feature) => {
    const coords = feature.geometry?.type === 'Point' ? feature.geometry.coordinates : null
    return Array.isArray(coords) && Number.isFinite(coords[0]) && Number.isFinite(coords[1])
  })
}

function extractLineEndpoints(features: Feature[]): { start_point?: [number, number]; end_point?: [number, number] } {
  for (const f of features) {
    const g = f.geometry
    if (g && (g.type === 'LineString' || g.type === 'MultiLineString') && 'coordinates' in g) {
      const coords = g.coordinates
      if (g.type === 'LineString' && Array.isArray(coords) && coords.length >= 2) {
        const start = coords[0] as [number, number]
        const end = coords[coords.length - 1] as [number, number]
        if (Array.isArray(start) && start.length >= 2 && Array.isArray(end) && end.length >= 2) {
          return { start_point: start, end_point: end }
        }
      } else if (g.type === 'MultiLineString' && Array.isArray(coords) && coords.length > 0) {
        const firstLine = coords[0]
        const lastLine = coords[coords.length - 1]
        if (Array.isArray(firstLine) && firstLine.length >= 2 && Array.isArray(lastLine) && lastLine.length >= 2) {
          const start = firstLine[0] as [number, number]
          const end = lastLine[lastLine.length - 1] as [number, number]
          if (Array.isArray(start) && start.length >= 2 && Array.isArray(end) && end.length >= 2) {
            return { start_point: start, end_point: end }
          }
        }
      }
    }
  }
  return {}
}


function compactLayerGroups(layers: GeoJSONLayer[]): GeoJSONLayer[] {
  const counts = new Map<string, number>()
  layers.forEach((layer) => {
    if (layer.groupId) counts.set(layer.groupId, (counts.get(layer.groupId) || 0) + 1)
  })
  return layers.map((layer) => {
    if (!layer.groupId || (counts.get(layer.groupId) || 0) > 1) return layer
    const { groupId: _groupId, groupName: _groupName, ...rest } = layer
    return rest
  })
}

function layerHasAiMarkers(layer: GeoJSONLayer): boolean {
  return (layer.data?.features || []).some((feature) => feature.properties?.source === 'ai_marker')
}

function formatDistance(km: number): string {
  if (!Number.isFinite(km)) return 'unknown'
  if (km < 1) return `${Math.round(km * 1000)} m`
  return `${km.toFixed(km >= 10 ? 1 : 2)} km`
}

function routeLabelCoordinate(coordinates: number[][], distanceKm?: number): number[] {
  if (coordinates.length === 0) return [0, 0]
  if (coordinates.length === 1) return coordinates[0]
  if (distanceKm && distanceKm > 0) {
    try {
      return turf.along(turf.lineString(coordinates), distanceKm / 2, { units: 'kilometers' })
        .geometry.coordinates
    } catch {
      // Fall through to the middle vertex when Turf rejects malformed input.
    }
  }
  return coordinates[Math.floor(coordinates.length / 2)]
}

/** Fetch a routed path through one or more waypoints via OSRM.
 * Accepts any number of [lng, lat] waypoints (minimum 2).
 * For multi-waypoint routes, segments are resolved independently and
 * stitched together so the final coordinates form one continuous line.
 */
async function fetchOsrmRoute(waypoints: number[][]) {
  if (waypoints.length < 2) throw new Error('Need at least 2 waypoints')

  // Build coordinate string: "lng1,lat1;lng2,lat2;..."
  const coordStr = waypoints.map((p) => `${p[0]},${p[1]}`).join(';')
  const url =
    `https://router.project-osrm.org/route/v1/car/${coordStr}` +
    '?overview=full&geometries=geojson&steps=false'

  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`OSRM route failed: ${resp.status}`)
  const data = await resp.json()
  const route = data?.routes?.[0]
  const routeCoords = route?.geometry?.coordinates
  if (data?.code !== 'Ok' || !Array.isArray(routeCoords) || routeCoords.length < 2) {
    throw new Error(data?.message || 'No route found')
  }
  return {
    coordinates: routeCoords as number[][],
    distanceKm: Number(route.distance || 0) / 1000,
    durationMinutes: Number(route.duration || 0) / 60,
  }
}

function App() {
  const [appMode, setAppMode] = useState<AppMode>('map')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const [transitionStatus, setTransitionStatus] = useState('Saving workspace...')
  const [documentImage, setDocumentImage] = useState<DocumentImage | null>(null)
  const [openDocs, setOpenDocs] = useState<OpenDocument[]>([])
  const [activeDocId, setActiveDocId] = useState<string | null>(null)
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [activeLeftTab, setActiveLeftTab] = useState<LeftTab>('files')
  const [stylingLayerId, setStylingLayerId] = useState<string | null>(null)
  const [attrLayerId, setAttrLayerId] = useState<string | null>(null)
  const [convertingFile, setConvertingFile] = useState<string | null>(null)
  const [convertError, setConvertError] = useState<string | null>(null)
  const [fileTreeRevision, setFileTreeRevision] = useState(0)
  const [selectedLayerIds, setSelectedLayerIds] = useState<Set<string>>(new Set())
  const [selectedFeatures, setSelectedFeatures] = useState<SelectedFeatureEntry[]>([])
  const [showDiagnostics, setShowDiagnostics] = useState(false)

  useEffect(() => {
    if (window.electronAPI && typeof window.electronAPI.getKeyStatus === 'function') {
      window.electronAPI.getKeyStatus()
        .then((status) => {
          if (!status || !status.openai || !status.google_maps) {
            setShowDiagnostics(true)
          }
        })
        .catch((err) => console.error('Failed to get key status on mount:', err))
    }
  }, [])

  // Multi-select handler. Shift+click toggles; plain click replaces.
  const handleSelectFeature = useCallback(
    (entry: SelectedFeatureEntry | null, shiftKey: boolean) => {
      if (!entry) {
        // null = clear all (plain click on empty map or Escape)
        setSelectedFeatures([])
        return
      }
      if (!shiftKey) {
        setSelectedFeatures([entry])
        return
      }
      // Shift+click: toggle by geometry identity
      setSelectedFeatures((prev) => {
        const idx = prev.findIndex(
          (e) =>
            e.layerId === entry.layerId &&
            JSON.stringify(e.feature.geometry) === JSON.stringify(entry.feature.geometry),
        )
        return idx === -1 ? [...prev, entry] : prev.filter((_, i) => i !== idx)
      })
    },
    [],
  )


  const [layers, setLayers] = useState<GeoJSONLayer[]>([])
  const [mapViewState, setMapViewState] = useState<MapViewState>({
    center: [76.7794, 30.7333],
    zoom: 13,
    bearing: 0,
    pitch: 0,
  })
  const [basemap, setBasemap] = useState('street')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null)
  const [mapActions, setMapActions] = useState<MapAction[]>([])
  const [streetViewTarget, setStreetViewTarget] = useState<StreetViewTarget | null>(null)
  const [roadInspectionTarget, setRoadInspectionTarget] = useState<RoadInspectionTarget | null>(null)
  const [streetViewDetail, setStreetViewDetail] = useState(false)
  const [streetViewActive, setStreetViewActive] = useState(false)
  const [streetViewLocation, setStreetViewLocation] = useState<{ lat: number; lng: number } | null>(null)
  const [streetViewBearing, setStreetViewBearing] = useState(0)
  const [streetViewLayout, setStreetViewLayout] = useState<'split' | 'full'>('split')
  const [splitHeight, setSplitHeight] = useState(400)
  const isDraggingSplitRef = useRef(false)
  const [injectedMessage, setInjectedMessage] = useState<{ text: string; nonce: number } | null>(null)
  const [bookmarks, setBookmarks] = useState<MapBookmark[]>([])
  const [mapBounds, setMapBounds] = useState<{
    west: number
    south: number
    east: number
    north: number
  } | null>(null)
  const [artifactsRevision, setArtifactsRevision] = useState(0)
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null)

  // Undo/Redo stack states
  const [pastHistory, setPastHistory] = useState<{ layers: GeoJSONLayer[]; bookmarks: MapBookmark[] }[]>([])
  const [futureHistory, setFutureHistory] = useState<{ layers: GeoJSONLayer[]; bookmarks: MapBookmark[] }[]>([])
  const isUndoRedoRef = useRef(false)
  const lastStateRef = useRef<{ layers: GeoJSONLayer[]; bookmarks: MapBookmark[] }>({ layers: [], bookmarks: [] })

  useEffect(() => {
    if (lastStateRef.current.layers.length === 0 && lastStateRef.current.bookmarks.length === 0) {
      lastStateRef.current = { layers, bookmarks }
      return
    }

    if (isUndoRedoRef.current) {
      isUndoRedoRef.current = false
      lastStateRef.current = { layers, bookmarks }
      return
    }

    const layersDiff = JSON.stringify(layers) !== JSON.stringify(lastStateRef.current.layers)
    const bookmarksDiff = JSON.stringify(bookmarks) !== JSON.stringify(lastStateRef.current.bookmarks)

    if (layersDiff || bookmarksDiff) {
      setPastHistory((prev) => [...prev, lastStateRef.current])
      setFutureHistory([]) // Clear redo stack on new action
      lastStateRef.current = { layers, bookmarks }
    }
  }, [layers, bookmarks])

  const handleGlobalUndo = useCallback(() => {
    if (pastHistory.length === 0) return
    const prev = pastHistory[pastHistory.length - 1]
    setPastHistory((p) => p.slice(0, -1))
    setFutureHistory((f) => [...f, { layers, bookmarks }])
    isUndoRedoRef.current = true
    setLayers(prev.layers)
    setBookmarks(prev.bookmarks)
  }, [pastHistory, layers, bookmarks])

  const handleGlobalRedo = useCallback(() => {
    if (futureHistory.length === 0) return
    const next = futureHistory[futureHistory.length - 1]
    setFutureHistory((f) => f.slice(0, -1))
    setPastHistory((p) => [...p, { layers, bookmarks }])
    isUndoRedoRef.current = true
    setLayers(next.layers)
    setBookmarks(next.bookmarks)
  }, [futureHistory, layers, bookmarks])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return
      }

      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        handleGlobalUndo()
      } else if (
        ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'z') ||
        ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y')
      ) {
        e.preventDefault()
        handleGlobalRedo()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleGlobalUndo, handleGlobalRedo])

  const mapViewRef = useRef<MapViewHandle>(null)
  const bookmarksRef = useRef<MapBookmark[]>([])
  const mapBoundsRef = useRef<typeof mapBounds>(null)
  const saveProjectRef = useRef<(force?: boolean) => Promise<void>>(async () => { })
  // Lets the export handlers (defined before suggestExportTitle) read its
  // latest value without a forward-reference dependency.
  const suggestExportTitleRef = useRef<() => string>(() => 'Map')

  const colorIndexRef = useRef(0)
  const aiShapeNameCounterRef = useRef(0)
  const aiMarkerCounterRef = useRef(0)
  const aiMarkersGroupIdRef = useRef(`group-ai-markers-${genId()}`)
  const userShapeCounterRef = useRef(0)
  const isLoadingRef = useRef(false)
  const leftPanelRef = useRef<HTMLElement>(null)

  // Deselect active layer when clicking outside the left panel
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (!leftPanelRef.current) return
      if (!leftPanelRef.current.contains(e.target as Node)) {
        if (stylingLayerId) setStylingLayerId(null)
        if (attrLayerId) setAttrLayerId(null)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [stylingLayerId, attrLayerId])
  const isSavingRef = useRef(false)
  // Mutex that blocks all debounced auto-saves during workspace transitions
  // (close or switch). Without this, resetWorkspaceState() clears state while
  // workspacePath is still non-null, causing the auto-save to write empty data
  // back to project.json / documents.json and corrupt the workspace.
  const isClosingRef = useRef(false)
  const chatPanelRef = useRef<ChatPanelHandle>(null)
  const savedDocIdsRef = useRef<Set<string>>(new Set()) // Tracks document images already persisted to disk
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveDocsTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dirtyLayerIdsRef = useRef<Set<string>>(new Set())
  const AI_MARKERS_LAYER = 'AI Markers'

  useEffect(() => { bookmarksRef.current = bookmarks }, [bookmarks])
  useEffect(() => { mapBoundsRef.current = mapBounds }, [mapBounds])

  // ── Resizable panels ──

  const [leftWidth, setLeftWidth] = useState(260)
  const [rightWidth, setRightWidth] = useState(380)

  // Caching refs for sidebar toggle restore widths
  const lastLeftWidthRef = useRef(260)
  const lastRightWidthRef = useRef(380)

  const [showArtifactsSidebar, setShowArtifactsSidebar] = useState(true)
  const [showDocumentSidebar, setShowDocumentSidebar] = useState(true)

  const onResizeStart = useCallback(
    (side: 'left' | 'right') => (e: React.MouseEvent) => {
      e.preventDefault()
      const startX = e.clientX
      const startW = side === 'left' ? leftWidth : rightWidth

      document.body.classList.add('resizing')

      const onMove = (ev: MouseEvent) => {
        const delta = ev.clientX - startX
        if (side === 'left') {
          const w = Math.max(180, Math.min(500, startW + delta))
          setLeftWidth(w)
          lastLeftWidthRef.current = w
        } else {
          const w = Math.max(280, Math.min(600, startW - delta))
          setRightWidth(w)
          lastRightWidthRef.current = w
        }
      }

      const onUp = () => {
        document.body.classList.remove('resizing')
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [leftWidth, rightWidth],
  )

  const toggleLeft = useCallback(() => {
    if (leftWidth > 0) {
      setLeftWidth(0)
    } else {
      setLeftWidth(lastLeftWidthRef.current)
    }
  }, [leftWidth])

  const toggleRight = useCallback(() => {
    if (rightWidth > 0) {
      setRightWidth(0)
    } else {
      setRightWidth(lastRightWidthRef.current)
    }
  }, [rightWidth])

  // ── Workspace ──

  // Auto-restore last workspace on startup
  useEffect(() => {
    window.electronAPI.getLastWorkspace().then((last) => {
      if (last) setWorkspacePath(last)
    }).catch(() => { })
  }, [])

  const resetWorkspaceState = useCallback(() => {
    setActiveLeftTab('files')
    setStylingLayerId(null)
    setAttrLayerId(null)
    setConvertingFile(null)
    setConvertError(null)
    setLayers([])
    setSelectedLayerIds(new Set())
    setSelectedFeatures([])
    setMapViewState({ center: [76.7794, 30.7333], zoom: 13, bearing: 0, pitch: 0 })
    setBasemap('street')
    setConversations([])
    setActiveConversationId(null)
    setMapActions([])
    setStreetViewTarget(null)
    setRoadInspectionTarget(null)
    setStreetViewActive(false)
    setStreetViewLocation(null)
    setStreetViewBearing(0)
    setStreetViewDetail(false)
    setStreetViewLayout('split')
    setInjectedMessage(null)
    setBookmarks([])
    setMapBounds(null)
    setArtifactsRevision(0)
    setScenarios([])
    setActiveScenarioId(null)
    setOpenDocs([])
    setActiveDocId(null)
    setDocumentImage(null)
    setPastHistory([])
    setFutureHistory([])
    lastStateRef.current = { layers: [], bookmarks: [] }
    savedDocIdsRef.current.clear() // Clear cache on close
  }, [])

  // ── Split screen row dragging handle ──
  const handleSplitDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isDraggingSplitRef.current = true
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
  }, [])

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingSplitRef.current) return
      const mapStackEl = document.querySelector('.map-stack')
      if (mapStackEl) {
        const rect = mapStackEl.getBoundingClientRect()
        const relativeY = e.clientY - rect.top
        const newHeight = Math.max(150, Math.min(rect.height - 150, relativeY))
        setSplitHeight(newHeight)
        mapViewRef.current?.resize()
      }
    }

    const handleMouseUp = () => {
      if (isDraggingSplitRef.current) {
        isDraggingSplitRef.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        mapViewRef.current?.resize()
      }
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  const saveDocumentsToWorkspace = useCallback(async (
    wsPath: string,
    docs: OpenDocument[],
    activeId: string | null
  ) => {
    try {
      const documentsDir = `${wsPath}/.disha/documents`
      const metadata = docs.map((d) => ({
        id: d.id,
        filePath: d.filePath,
        fileName: d.fileName,
        isPdf: d.isPdf,
        pdfPage: d.pdfPage,
        pdfTotalPages: d.pdfTotalPages,
      }))
      const metaDataStr = JSON.stringify({ openDocs: metadata, activeDocId: activeId }, null, 2)

      const writePromises: Promise<boolean>[] = [
        window.electronAPI.writeFile(`${documentsDir}/documents.json`, metaDataStr)
      ]

      for (const d of docs) {
        if (d.documentImage && d.documentImage.base64) {
          if (savedDocIdsRef.current.has(d.id)) {
            continue // Giant base64 content already written, skip I/O!
          }
          const docFile = `${documentsDir}/${d.id}.json`
          const imgData = JSON.stringify(d.documentImage, null, 2)
          writePromises.push(window.electronAPI.writeFile(docFile, imgData).then((ok) => {
            if (ok) savedDocIdsRef.current.add(d.id)
            return ok
          }))
        }
      }

      await Promise.all(writePromises)
    } catch (e) {
      console.error('Failed to save documents:', e)
    }
  }, [])

  const loadDocumentsFromWorkspace = useCallback(async (wsPath: string) => {
    try {
      const metaContent = await window.electronAPI.readFile(`${wsPath}/.disha/documents/documents.json`)
      if (!metaContent) {
        setOpenDocs([])
        setActiveDocId(null)
        setDocumentImage(null)
        return
      }
      const { openDocs: loadedMeta, activeDocId: loadedActiveId } = JSON.parse(metaContent)

      const docs: OpenDocument[] = loadedMeta.map((d: any) => ({
        ...d,
        displayUrl: `localfile://${d.filePath.split('/').map(encodeURIComponent).join('/')}`,
        documentImage: null
      }))

      // Populate cache with loaded documents
      savedDocIdsRef.current.clear()
      loadedMeta.forEach((d: any) => savedDocIdsRef.current.add(d.id))

      if (loadedActiveId) {
        const activeImgContent = await window.electronAPI.readFile(`${wsPath}/.disha/documents/${loadedActiveId}.json`)
        if (activeImgContent) {
          try {
            const imgObj = JSON.parse(activeImgContent)
            const activeIndex = docs.findIndex(d => d.id === loadedActiveId)
            if (activeIndex !== -1) {
              docs[activeIndex].documentImage = imgObj
              setDocumentImage(imgObj)
            }
          } catch (e) {
            console.error('Failed to parse active document image:', e)
          }
        }
      }

      setOpenDocs(docs)
      setActiveDocId(loadedActiveId)
    } catch (e) {
      console.error('Failed to load documents:', e)
      setOpenDocs([])
      setActiveDocId(null)
      setDocumentImage(null)
    }
  }, [])

  const [isSavingDocs, setIsSavingDocs] = useState(false)

  const saveDocuments = useCallback(async () => {
    if (!workspacePath) return
    setIsSavingDocs(true)
    await saveDocumentsToWorkspace(workspacePath, openDocs, activeDocId)
    setIsSavingDocs(false)
  }, [workspacePath, openDocs, activeDocId, saveDocumentsToWorkspace])

  useEffect(() => {
    if (!workspacePath || isLoadingRef.current || isSavingDocs || isClosingRef.current) return
    if (saveDocsTimeoutRef.current) clearTimeout(saveDocsTimeoutRef.current)
    saveDocsTimeoutRef.current = setTimeout(saveDocuments, 800)
    return () => {
      if (saveDocsTimeoutRef.current) clearTimeout(saveDocsTimeoutRef.current)
    }
  }, [workspacePath, openDocs, activeDocId, saveDocuments])

  const handleSelectWorkspace = async (): Promise<void> => {
    const selected = await window.electronAPI.selectWorkspace()
    if (!selected) return

    const oldWorkspaceName = workspacePath?.split('/').pop() ?? 'workspace'
    setTransitionStatus(`Saving ${oldWorkspaceName}...`)
    setIsTransitioning(true)

    // Cancel any pending debounced saves
    if (saveTimeoutRef.current) { clearTimeout(saveTimeoutRef.current); saveTimeoutRef.current = null }
    if (saveDocsTimeoutRef.current) { clearTimeout(saveDocsTimeoutRef.current); saveDocsTimeoutRef.current = null }

    // Block auto-save effects BEFORE we reset state. Without this guard,
    // resetWorkspaceState() clears layers/conversations while workspacePath is
    // still the old path, and the debounced auto-save fires and corrupts
    // the old workspace's project.json with empty data.
    isClosingRef.current = true

    // Stop any in-flight task + clear temp artifacts on backend using the old path
    chatPanelRef.current?.stopStreaming()
    if (workspacePath) {
      fetch(`http://localhost:8765/api/artifacts/clear_temp?workspace=${encodeURIComponent(workspacePath)}`, { method: 'POST' }).catch(() => { })
    }

    // Save current workspace first (save-first-then-clear)
    if (workspacePath) {
      try { await saveProjectRef.current(true) } catch { /* non-fatal */ }
      try { await saveDocumentsToWorkspace(workspacePath, openDocs, activeDocId) } catch { /* non-fatal */ }
    }

    // Now safely clear all state and point to the new workspace
    resetWorkspaceState()
    setWorkspacePath(selected)

    // Backend: clear chat session history
    chatPanelRef.current?.resetHistory()

    window.electronAPI.setLastWorkspace(selected).catch(() => { })

    // Release the guard after a tick so the loadProject useEffect sees the
    // new workspacePath and runs cleanly (isClosingRef=false).
    setTimeout(() => {
      isClosingRef.current = false
      setIsTransitioning(false)
    }, 100)
  }

  const handleCloseWorkspace = useCallback(async (): Promise<void> => {
    const oldWorkspaceName = workspacePath?.split('/').pop() ?? 'workspace'
    setTransitionStatus(`Saving ${oldWorkspaceName}...`)
    setIsTransitioning(true)

    // Cancel any pending debounced saves
    if (saveTimeoutRef.current) { clearTimeout(saveTimeoutRef.current); saveTimeoutRef.current = null }
    if (saveDocsTimeoutRef.current) { clearTimeout(saveDocsTimeoutRef.current); saveDocsTimeoutRef.current = null }

    // Block auto-save effects BEFORE we reset state (same race-condition guard
    // as handleSelectWorkspace — see isClosingRef comment above).
    isClosingRef.current = true

    // Stop any in-flight task + clear temp artifacts on backend using the old path
    chatPanelRef.current?.stopStreaming()
    if (workspacePath) {
      fetch(`http://localhost:8765/api/artifacts/clear_temp?workspace=${encodeURIComponent(workspacePath)}`, { method: 'POST' }).catch(() => { })
    }

    // Save current workspace first (save-first-then-clear, per user requirement)
    if (workspacePath) {
      try { await saveProjectRef.current(true) } catch { /* non-fatal */ }
      try { await saveDocumentsToWorkspace(workspacePath, openDocs, activeDocId) } catch { /* non-fatal */ }
    }

    // Now safely clear all state
    setWorkspacePath(null)
    resetWorkspaceState()

    // Backend: clear chat session history
    chatPanelRef.current?.resetHistory()

    window.electronAPI.setLastWorkspace(null).catch(() => { })

    // Release the guard after a tick so subsequent interactions work normally
    setTimeout(() => {
      isClosingRef.current = false
      setIsTransitioning(false)
    }, 100)
  }, [workspacePath, resetWorkspaceState, openDocs, activeDocId, saveDocumentsToWorkspace])

  // ── Layer management ──

  const addLayer = useCallback(
    async (name: string, filePath: string, customColor?: string, customStyleSpec?: any) => {
      if (layers.find((l) => l.filePath === filePath)) {
        setActiveLeftTab('layers')
        return
      }
      const content = await window.electronAPI.readFile(filePath)
      if (!content) return
      try {
        const raw = JSON.parse(content)
        const validTypes = [
          'FeatureCollection', 'Feature', 'Point', 'MultiPoint',
          'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon',
          'GeometryCollection'
        ]
        if (!raw || typeof raw !== 'object' || !validTypes.includes(raw.type)) {
          console.warn('Selected JSON is not a valid GeoJSON layer.')
          return
        }
        const data =
          raw.type === 'FeatureCollection'
            ? raw
            : raw.type === 'Feature'
              ? { type: 'FeatureCollection', features: [raw] }
              : {
                type: 'FeatureCollection',
                features: [{ type: 'Feature', geometry: raw, properties: {} }],
              }

        const color = customColor || LAYER_COLORS[colorIndexRef.current % LAYER_COLORS.length]
        if (!customColor) colorIndexRef.current++

        const isAiMarkers = name.toLowerCase() === AI_MARKERS_LAYER.toLowerCase()
        const isStops = name.toLowerCase().includes('stops') || name.toLowerCase().includes('waypoints') || name.toLowerCase().includes('markers')
        const finalStyleSpec = customStyleSpec || ((isAiMarkers || isStops) ? {
          mode: 'simple' as const,
          label: {
            enabled: true,
            property: 'label',
            size: 12,
            color: '#1e1e2e',
            haloColor: '#ffffff',
            minZoom: 0,
          }
        } : undefined)

        const layer: GeoJSONLayer = {
          id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          name,
          filePath,
          visible: true,
          data,
          color,
          styleSpec: finalStyleSpec,
        }
        setLayers((prev) => [...prev, layer])
        setActiveLeftTab('layers')
      } catch (e) {
        console.error('Invalid GeoJSON:', e)
      }
    },
    [layers],
  )

  const removeLayer = useCallback((id: string) => {
    setLayers((prev) => compactLayerGroups(prev.filter((l) => l.id !== id)))
  }, [])

  const toggleLayer = useCallback((id: string) => {
    setLayers((prev) => {
      const next = prev.map((l) => (l.id === id ? { ...l, visible: !l.visible } : l))
      const targetLayer = prev.find((l) => l.id === id)
      if (targetLayer) {
        const nextVisible = !targetLayer.visible
        setActiveScenarioId((activeId) => {
          if (activeId) {
            setScenarios((prevScenarios) =>
              prevScenarios.map((s) =>
                s.id === activeId
                  ? {
                    ...s,
                    layerVisibility: {
                      ...s.layerVisibility,
                      [id]: nextVisible,
                    },
                  }
                  : s
              )
            )
          }
          return activeId
        })
      }
      return next
    })
  }, [])

  const matchesGroup = (l: GeoJSONLayer, groupId: string) => {
    if (l.groupPathIds?.includes(groupId)) return true
    if (l.groupId === groupId) return true
    return false
  }

  const toggleLayerGroup = useCallback((groupId: string, visible: boolean) => {
    setLayers((prev) => {
      const next = prev.map((l) => (matchesGroup(l, groupId) ? { ...l, visible } : l))
      setActiveScenarioId((activeId) => {
        if (activeId) {
          setScenarios((prevScenarios) =>
            prevScenarios.map((s) => {
              if (s.id === activeId) {
                const updatedVis = { ...s.layerVisibility }
                prev.forEach((l) => {
                  if (matchesGroup(l, groupId)) {
                    updatedVis[l.id] = visible
                  }
                })
                return { ...s, layerVisibility: updatedVis }
              }
              return s
            })
          )
        }
        return activeId
      })
      return next
    })
  }, [])

  const renameLayer = useCallback((id: string, name: string) => {
    setLayers((prev) => prev.map((l) => (l.id === id ? { ...l, name } : l)))
  }, [])

  const renameGroup = useCallback((groupId: string, newGroupName: string) => {
    setLayers((prev) => prev.map((l) => {
      let updated = false
      let nextIds = l.groupPathIds ? [...l.groupPathIds] : (l.groupId ? [l.groupId] : [])
      let nextNames = l.groupPathNames ? [...l.groupPathNames] : (l.groupName ? [l.groupName] : [])

      const idx = nextIds.indexOf(groupId)
      if (idx !== -1) {
        nextNames[idx] = newGroupName
        updated = true
      }

      if (l.groupId === groupId) {
        return {
          ...l,
          groupName: newGroupName,
          groupPathIds: nextIds,
          groupPathNames: nextNames,
        }
      }
      if (updated) {
        return {
          ...l,
          groupPathIds: nextIds,
          groupPathNames: nextNames,
        }
      }
      return l
    }))
  }, [])

  const groupLayersMulti = useCallback((ids: string[], customGroupName?: string) => {
    if (ids.length < 1) return
    setLayers((prev) => {
      const newGroupId = `group-${genId()}`
      const firstName = prev.find((l) => l.id === ids[0])?.name ?? 'Layer'
      const newGroupName = customGroupName || `${firstName} Group`

      // Find a common parent path if they already share one
      const firstLayer = prev.find((l) => ids.includes(l.id))
      let commonIds: string[] = []
      let commonNames: string[] = []
      if (firstLayer) {
        commonIds = firstLayer.groupPathIds ? [...firstLayer.groupPathIds] : (firstLayer.groupId ? [firstLayer.groupId] : [])
        commonNames = firstLayer.groupPathNames ? [...firstLayer.groupPathNames] : (firstLayer.groupName ? [firstLayer.groupName] : [])
      }

      return prev.map((layer) => {
        if (!ids.includes(layer.id)) return layer

        const finalIds = [...commonIds, newGroupId]
        const finalNames = [...commonNames, newGroupName]

        return {
          ...layer,
          groupId: newGroupId,
          groupName: newGroupName,
          groupPathIds: finalIds,
          groupPathNames: finalNames,
        }
      })
    })
  }, [])

  const groupLayers = useCallback((sourceId: string, targetId: string) => {
    groupLayersMulti([sourceId, targetId])
  }, [groupLayersMulti])

  const ungroupLayer = useCallback((id: string) => {
    setLayers((prev) => {
      return prev.map((l) => {
        if (l.id !== id) return l

        let ids = l.groupPathIds ? [...l.groupPathIds] : (l.groupId ? [l.groupId] : [])
        let names = l.groupPathNames ? [...l.groupPathNames] : (l.groupName ? [l.groupName] : [])

        if (ids.length > 0) {
          ids.pop()
          names.pop()
        }

        return {
          ...l,
          groupId: ids.length > 0 ? ids[ids.length - 1] : undefined,
          groupName: names.length > 0 ? names[names.length - 1] : undefined,
          groupPathIds: ids.length > 0 ? ids : undefined,
          groupPathNames: names.length > 0 ? names : undefined,
        }
      })
    })
  }, [])

  const ungroupGroup = useCallback((groupId: string) => {
    setLayers((prev) => {
      return prev.map((l) => {
        let ids = l.groupPathIds ? [...l.groupPathIds] : (l.groupId ? [l.groupId] : [])
        let names = l.groupPathNames ? [...l.groupPathNames] : (l.groupName ? [l.groupName] : [])

        const idx = ids.indexOf(groupId)
        if (idx !== -1) {
          ids.splice(idx, 1)
          names.splice(idx, 1)
        }

        return {
          ...l,
          groupId: ids.length > 0 ? ids[ids.length - 1] : undefined,
          groupName: names.length > 0 ? names[names.length - 1] : undefined,
          groupPathIds: ids.length > 0 ? ids : undefined,
          groupPathNames: names.length > 0 ? names : undefined,
        }
      })
    })
  }, [])

  const moveLayerOrGroup = useCallback((sourceId: string, targetId: string, position: 'before' | 'after' | 'inside') => {
    setLayers((prev) => {
      const isSourceGroup = prev.some((l) => l.groupPathIds?.includes(sourceId) || l.groupId === sourceId)
      const sourceLayer = prev.find((l) => l.id === sourceId)

      let sourceLayerIds: string[] = []
      if (isSourceGroup) {
        sourceLayerIds = prev.filter((l) => l.groupPathIds?.includes(sourceId) || l.groupId === sourceId).map((l) => l.id)
      } else if (sourceLayer) {
        sourceLayerIds = [sourceId]
      }

      if (sourceLayerIds.length === 0) return prev

      const isTargetGroup = prev.some((l) => l.groupPathIds?.includes(targetId) || l.groupId === targetId)
      const targetLayer = prev.find((l) => l.id === targetId)

      let newPathIds: string[] = []
      let newPathNames: string[] = []

      if (position === 'inside') {
        const firstTargetInGroup = prev.find((l) => l.groupPathIds?.includes(targetId) || l.groupId === targetId)
        if (firstTargetInGroup) {
          let tIds = firstTargetInGroup.groupPathIds ? [...firstTargetInGroup.groupPathIds] : (firstTargetInGroup.groupId ? [firstTargetInGroup.groupId] : [])
          let tNames = firstTargetInGroup.groupPathNames ? [...firstTargetInGroup.groupPathNames] : (firstTargetInGroup.groupName ? [firstTargetInGroup.groupName] : [])

          const idx = tIds.indexOf(targetId)
          if (idx !== -1) {
            newPathIds = tIds.slice(0, idx + 1)
            newPathNames = tNames.slice(0, idx + 1)
          } else {
            newPathIds = [targetId]
            newPathNames = [firstTargetInGroup.groupName || 'Group']
          }
        }
      } else {
        if (isTargetGroup) {
          const firstTargetInGroup = prev.find((l) => l.groupPathIds?.includes(targetId) || l.groupId === targetId)
          if (firstTargetInGroup) {
            let tIds = firstTargetInGroup.groupPathIds ? [...firstTargetInGroup.groupPathIds] : (firstTargetInGroup.groupId ? [firstTargetInGroup.groupId] : [])
            let tNames = firstTargetInGroup.groupPathNames ? [...firstTargetInGroup.groupPathNames] : (firstTargetInGroup.groupName ? [firstTargetInGroup.groupName] : [])

            const idx = tIds.indexOf(targetId)
            if (idx !== -1) {
              newPathIds = tIds.slice(0, idx)
              newPathNames = tNames.slice(0, idx)
            }
          }
        } else if (targetLayer) {
          let tIds = targetLayer.groupPathIds ? [...targetLayer.groupPathIds] : (targetLayer.groupId ? [targetLayer.groupId] : [])
          let tNames = targetLayer.groupPathNames ? [...targetLayer.groupPathNames] : (targetLayer.groupName ? [targetLayer.groupName] : [])
          newPathIds = tIds
          newPathNames = tNames
        }
      }

      const updatedMovedLayers = prev.filter((l) => sourceLayerIds.includes(l.id)).map((l) => {
        let relativeIds: string[] = []
        let relativeNames: string[] = []
        if (isSourceGroup) {
          let sIds = l.groupPathIds ? [...l.groupPathIds] : (l.groupId ? [l.groupId] : [])
          let sNames = l.groupPathNames ? [...l.groupPathNames] : (l.groupName ? [l.groupName] : [])
          const idx = sIds.indexOf(sourceId)
          if (idx !== -1) {
            relativeIds = sIds.slice(idx)
            relativeNames = sNames.slice(idx)
          }
        }

        const finalIds = [...newPathIds, ...relativeIds]
        const finalNames = [...newPathNames, ...relativeNames]

        return {
          ...l,
          groupId: finalIds.length > 0 ? finalIds[finalIds.length - 1] : undefined,
          groupName: finalNames.length > 0 ? finalNames[finalNames.length - 1] : undefined,
          groupPathIds: finalIds.length > 0 ? finalIds : undefined,
          groupPathNames: finalNames.length > 0 ? finalNames : undefined,
        }
      })

      const remainingLayers = prev.filter((l) => !sourceLayerIds.includes(l.id))

      let insertIndex = -1
      if (position === 'inside') {
        const lastChild = [...remainingLayers].reverse().find((l) => l.groupPathIds?.includes(targetId) || l.groupId === targetId)
        if (lastChild) {
          insertIndex = remainingLayers.indexOf(lastChild) + 1
        } else {
          insertIndex = remainingLayers.length
        }
      } else {
        if (isTargetGroup) {
          const groupLayers = remainingLayers.filter((l) => l.groupPathIds?.includes(targetId) || l.groupId === targetId)
          if (groupLayers.length > 0) {
            insertIndex = position === 'before'
              ? remainingLayers.indexOf(groupLayers[0])
              : remainingLayers.indexOf(groupLayers[groupLayers.length - 1]) + 1
          } else {
            insertIndex = remainingLayers.length
          }
        } else {
          insertIndex = remainingLayers.findIndex((l) => l.id === targetId)
          if (insertIndex !== -1 && position === 'after') {
            insertIndex += 1
          }
        }
      }

      if (insertIndex === -1) {
        insertIndex = remainingLayers.length
      }

      return [
        ...remainingLayers.slice(0, insertIndex),
        ...updatedMovedLayers,
        ...remainingLayers.slice(insertIndex),
      ]
    })
  }, [])

  const zoomToLayer = useCallback((id: string) => {
    const layer = layers.find((l) => l.id === id)
    if (!layer) return
    // WMS/GEE raster layers have no GeoJSON data to compute a bbox from.
    // Fall back to the current visible map bounds so the button still does
    // something useful (e.g., zooms back if user panned away).
    if (layer.wmsSpec || layer.geeSpec) {
      const b = mapBoundsRef.current
      if (b) {
        setMapActions((prev) => [
          ...prev,
          { type: 'fit_bounds', payload: { west: b.west, south: b.south, east: b.east, north: b.north } },
        ])
      }
      return
    }
    if (!layer.data) return
    try {
      const bbox = turf.bbox(layer.data) as [number, number, number, number]
      if (bbox.every((v) => isFinite(v))) {
        setMapActions((prev) => [
          ...prev,
          { type: 'fit_bounds', payload: { west: bbox[0], south: bbox[1], east: bbox[2], north: bbox[3] } },
        ])
      }
    } catch { /* ignore invalid geometry */ }
  }, [layers])

  // Convert a non-GeoJSON vector file (shapefile/GPKG/KML/KMZ/GPX/CSV) to a
  // workspace-local .geojson via the backend, then load it as a layer. Requires
  // an open workspace (the backend writes the converted file inside it).
  const convertAndAddLayer = useCallback(
    async (entry: FileEntry) => {
      if (!workspacePath) {
        setConvertError('Open a workspace folder before importing this file type.')
        return
      }
      setConvertingFile(entry.name)
      setConvertError(null)
      try {
        const resp = await fetch('http://localhost:8765/api/files/convert', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: entry.path, workspace: workspacePath }),
        })
        const data = await resp.json()
        if (data.error) {
          setConvertError(`${entry.name}: ${data.error}`)
          return
        }
        if (data.path) {
          await addLayer(data.name || entry.name, data.path)
        }
      } catch {
        setConvertError(`Could not reach the backend to convert ${entry.name}.`)
      } finally {
        setConvertingFile(null)
      }
    },
    [workspacePath, addLayer],
  )

  const handleFileClick = useCallback(
    (entry: FileEntry) => {
      const lower = entry.name.toLowerCase()
      if (lower.endsWith('.geojson') || lower.endsWith('.json')) {
        addLayer(entry.name.replace(/\.(geojson|json)$/i, ''), entry.path)
      } else if (/\.(shp|gpkg|kml|kmz|gpx|csv)$/.test(lower)) {
        void convertAndAddLayer(entry)
      }
    },
    [addLayer, convertAndAddLayer],
  )

  const handleImportSpatialFiles = useCallback(async () => {
    if (!workspacePath) {
      setConvertError('Open a workspace folder before importing files.')
      return
    }
    setConvertError(null)
    try {
      const paths = await window.electronAPI.importSpatialFiles(workspacePath)
      if (!paths || paths.length === 0) return

      for (const fp of paths) {
        const lower = fp.toLowerCase()
        const filename = fp.split(/[/\\]/).pop() || 'file'

        if (lower.endsWith('.geojson') || lower.endsWith('.json')) {
          const name = filename.replace(/\.(geojson|json)$/i, '')
          await addLayer(name, fp)
        } else if (/\.(shp|gpkg|kml|kmz|gpx|csv)$/.test(lower)) {
          setConvertingFile(filename)
          try {
            const resp = await fetch('http://localhost:8765/api/files/convert', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: fp, workspace: workspacePath }),
            })
            const data = await resp.json()
            if (data.error) {
              setConvertError(`${filename}: ${data.error}`)
            } else if (data.path) {
              await addLayer(data.name || filename, data.path)
            }
          } catch (e) {
            setConvertError(`Could not reach the backend to convert ${filename}.`)
          } finally {
            setConvertingFile(null)
          }
        }
      }
      setFileTreeRevision((prev) => prev + 1)
    } catch (err) {
      setConvertError(`Import failed: ${err}`)
    }
  }, [workspacePath, addLayer])


  // ── Admin boundary save ──

  const handlePreviewBoundary = useCallback((geom: BoundaryGeometry | null) => {
    if (geom) {
      const previewFC: FeatureCollection = {
        type: 'FeatureCollection',
        features: [{ type: 'Feature', geometry: geom, properties: {} }],
      }
      setMapActions((prev) => [
        ...prev,
        {
          type: 'add_geojson',
          payload: {
            geojson: previewFC,
            name: '__boundary_preview__',
            color: '#f59e0b',
          },
        },
      ])
    } else {
      setMapActions((prev) => [
        ...prev,
        { type: 'remove_layer', payload: { layer_name: '__boundary_preview__' } },
      ])
    }
  }, [])

  const handleSaveByRegion = useCallback(async (displayName: string, boundaryGeom: BoundaryGeometry) => {
    if (!workspacePath || layers.length === 0) return
    const boundary: Feature<BoundaryGeometry> = { type: 'Feature', geometry: boundaryGeom, properties: {} }
    const allClipped: Feature[] = []
    for (const layer of layers) {
      for (const f of layer.data?.features || []) {
        const t = f.geometry?.type
        try {
          if (t === 'Polygon' || t === 'MultiPolygon') {
            const clipped = turf.intersect(
              turf.featureCollection([
                f as Feature<Polygon | MultiPolygon>,
                boundary as Feature<Polygon | MultiPolygon>,
              ]),
            )
            if (clipped) {
              allClipped.push({
                ...clipped,
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          } else if (t === 'Point') {
            if (
              turf.booleanPointInPolygon(
                f as Feature<import('geojson').Point>,
                boundary as Feature<Polygon | MultiPolygon>,
              )
            ) {
              allClipped.push({
                ...f,
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          } else if (t === 'MultiPoint') {
            const coords = (f.geometry as import('geojson').MultiPoint).coordinates
            const inside = coords.filter((c) =>
              turf.booleanPointInPolygon(turf.point(c), boundary as Feature<Polygon | MultiPolygon>),
            )
            if (inside.length) {
              allClipped.push({
                type: 'Feature',
                geometry: { type: 'MultiPoint', coordinates: inside },
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          } else if (t === 'LineString' || t === 'MultiLineString') {
            if (
              turf.booleanIntersects(
                f as Feature,
                boundary as Feature<Polygon | MultiPolygon>,
              )
            ) {
              allClipped.push({
                ...f,
                properties: { ...(f.properties || {}), source_layer: layer.name },
              })
            }
          }
        } catch {
          /* skip invalid geometry */
        }
      }
    }
    const safeName = displayName.replace(/[^a-z0-9-_]/gi, '_').slice(0, 40) || 'region'
    const filePath = `${workspacePath}/${safeName}.geojson`
    await window.electronAPI.writeFile(
      filePath,
      JSON.stringify({ type: 'FeatureCollection', features: allClipped }, null, 2),
    )
    addLayer(safeName, filePath)
    setActiveLeftTab('layers')
    setMapActions((prev) => [
      ...prev,
      { type: 'remove_layer', payload: { layer_name: '__boundary_preview__' } },
    ])
  }, [workspacePath, layers, addLayer])

  const handleBookmarkGoTo = useCallback((b: MapBookmark) => {
    setMapActions((prev) => [
      ...prev,
      {
        type: 'fit_bounds',
        payload: { south: b.south, west: b.west, north: b.north, east: b.east },
      },
    ])
  }, [])

  const handleBookmarkSaveCurrent = useCallback(
    (name: string) => {
      const bounds = mapBoundsRef.current
      if (!bounds) return
      setBookmarks((prev) => [
        ...prev,
        {
          id: genId(),
          name,
          ...bounds,
          zoom: mapViewState.zoom,
        },
      ])
      setActiveLeftTab('bookmarks')
    },
    [mapViewState.zoom],
  )

  // Compose a decorated figure (title block, scale bar, north arrow, legend,
  // attribution) from the live map canvas + current view state. Single source
  // for all four export paths so decorations are always baked into the output.
  const composeMapFigure = useCallback(
    (title: string): HTMLCanvasElement | null => {
      const canvas = mapViewRef.current?.getCanvas()
      if (!canvas) return null
      return composeFigure(canvas, {
        title: title || 'Map',
        centerLat: mapViewState.center[1],
        zoom: mapViewState.zoom,
        bearing: mapViewState.bearing,
        legend: buildLegendEntries(layers),
        attribution: BASEMAPS[basemap]?.attribution || '',
      })
    },
    [mapViewState, layers, basemap],
  )

  // Fit a composed canvas onto a landscape A4 PDF page, full-bleed minus margin.
  const composedToPdf = useCallback(async (figure: HTMLCanvasElement) => {
    const { jsPDF } = await import('jspdf')
    const pdf = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' })
    const img = figure.toDataURL('image/png')
    const pageW = pdf.internal.pageSize.getWidth()
    const pageH = pdf.internal.pageSize.getHeight()
    const margin = 24
    const maxW = pageW - margin * 2
    const maxH = pageH - margin * 2
    const aspect = figure.height > 0 ? figure.width / figure.height : maxW / maxH
    let drawW = maxW
    let drawH = drawW / aspect
    if (drawH > maxH) { drawH = maxH; drawW = drawH * aspect }
    const drawX = (pageW - drawW) / 2
    const drawY = (pageH - drawH) / 2
    pdf.addImage(img, 'PNG', drawX, drawY, drawW, drawH)
    return pdf
  }, [])

  const handleExportMapPng = useCallback((title?: string) => {
    const figure = composeMapFigure(title || suggestExportTitleRef.current())
    if (!figure) return
    figure.toBlob((blob) => {
      if (!blob) return
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `map-${Date.now()}.png`
      a.click()
      URL.revokeObjectURL(a.href)
    })
  }, [composeMapFigure])

  const handleExportPdf = useCallback(async (title?: string) => {
    const figure = composeMapFigure(title || suggestExportTitleRef.current())
    if (!figure) return
    const pdf = await composedToPdf(figure)
    pdf.save(`map-report-${Date.now()}.pdf`)
  }, [composeMapFigure, composedToPdf])

  const handleSavePngToArtifact = useCallback(async (title: string) => {
    const figure = composeMapFigure(title)
    if (!figure) return
    figure.toBlob(async (blob) => {
      if (!blob) return
      const form = new FormData()
      form.append('title', title)
      form.append('artifact_type', 'sketch')
      form.append('format', 'image')
      form.append('content', '')
      form.append('file', blob, `${title.replace(/[^a-z0-9-_]/gi, '_')}.png`)
      if (workspacePath) {
        form.append('workspace', workspacePath)
      }
      try {
        await fetch('http://localhost:8765/api/artifacts/upload', { method: 'POST', body: form })
        setArtifactsRevision((n) => n + 1)
      } catch {
        /* backend unavailable */
      }
    })
  }, [composeMapFigure, workspacePath])

  const handleSavePdfToArtifact = useCallback(async (title: string) => {
    const figure = composeMapFigure(title)
    if (!figure) return
    const pdf = await composedToPdf(figure)
    const pdfBytes = pdf.output('arraybuffer')
    const blob = new Blob([pdfBytes], { type: 'application/pdf' })
    const form = new FormData()
    form.append('title', title)
    form.append('artifact_type', 'sketch')
    form.append('format', 'image')
    form.append('content', '')
    form.append('file', blob, `${title.replace(/[^a-z0-9-_]/gi, '_')}.pdf`)
    if (workspacePath) {
      form.append('workspace', workspacePath)
    }
    try {
      await fetch('http://localhost:8765/api/artifacts/upload', { method: 'POST', body: form })
      setArtifactsRevision((n) => n + 1)
    } catch {
      /* backend unavailable */
    }
  }, [composeMapFigure, composedToPdf, workspacePath])

  const suggestExportTitle = useCallback((): string => {
    const topLayer = layers.length > 0 ? layers[layers.length - 1].name : null
    const date = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
    return topLayer ? `${topLayer} — ${date}` : `Map export — ${date}`
  }, [layers])

  suggestExportTitleRef.current = suggestExportTitle

  const handleExportLayerFile = useCallback((layerId: string) => {
    const layer = layers.find((l) => l.id === layerId)
    if (!layer?.data) return
    const blob = new Blob([JSON.stringify(layer.data, null, 2)], { type: 'application/geo+json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${layer.name.replace(/[^a-z0-9-_]/gi, '_') || 'layer'}.geojson`
    a.click()
    URL.revokeObjectURL(a.href)
  }, [layers])

  // ── Shared helper: upsert a named GeoJSON layer ──

  const clipLayersToBboxAndSave = useCallback(
    async (
      outputBaseName: string,
      bboxExplicit?: { south: number; west: number; north: number; east: number },
    ) => {
      const b =
        bboxExplicit?.south != null
          ? bboxExplicit
          : mapBoundsRef.current
      if (!workspacePath || !b || !layers.length) return
      const bbox: [number, number, number, number] = [b.west, b.south, b.east, b.north]
      const allFeatures: Feature[] = []
      for (const layer of layers) {
        for (const f of layer.data?.features || []) {
          try {
            const clipped = turf.bboxClip(f as Feature<Polygon | MultiPolygon>, bbox)
            if (!clipped?.geometry) continue
            allFeatures.push({
              type: 'Feature',
              geometry: clipped.geometry,
              properties: { ...(f.properties || {}), source_layer: layer.name },
            })
          } catch {
            /* skip */
          }
        }
      }
      const base = (outputBaseName || 'clipped').replace(/[^a-z0-9-_]/gi, '_') || 'clipped'
      const path = `${workspacePath}/${base}.geojson`
      await window.electronAPI.writeFile(
        path,
        JSON.stringify({ type: 'FeatureCollection', features: allFeatures }, null, 2),
      )
      addLayer(base, path)
      setActiveLeftTab('layers')
    },
    [layers, workspacePath, addLayer],
  )

  const upsertLayer = useCallback((layerName: string, data: FeatureCollection, color?: string, styleSpec?: any) => {
    const layerColor = color || LAYER_COLORS[colorIndexRef.current % LAYER_COLORS.length]
    if (!color) colorIndexRef.current++

    const isAiMarkers = layerName.toLowerCase() === AI_MARKERS_LAYER.toLowerCase()
    const isStops = layerName.toLowerCase().includes('stops') || layerName.toLowerCase().includes('waypoints') || layerName.toLowerCase().includes('markers')
    const finalStyleSpec = styleSpec || ((isAiMarkers || isStops) ? {
      mode: 'simple' as const,
      label: {
        enabled: true,
        property: 'label',
        size: 12,
        color: '#1e1e2e',
        haloColor: '#ffffff',
        minZoom: 0,
      }
    } : undefined)

    setLayers((prev) => {
      const newLayer = {
        id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        name: layerName,
        filePath: '',
        visible: true,
        data,
        color: layerColor,
        styleSpec: finalStyleSpec,
      }
      const existingIdx = prev.findIndex(
        (l) => l.name.toLowerCase() === layerName.toLowerCase(),
      )
      if (existingIdx >= 0) {
        const updated = [...prev]
        updated[existingIdx] = { ...newLayer, id: prev[existingIdx].id }
        return updated
      }
      return [...prev, newLayer]
    })
    setActiveLeftTab('layers')
  }, [])

  const addAiMarkersToGroup = useCallback((markers: MarkerInput[]) => {
    const features = markers
      .filter((m) => Number.isFinite(m.lat) && Number.isFinite(m.lng))
      .map(markerFeature)
    if (!features.length) return

    setLayers((prev) => {
      const groupId =
        prev.find((layer) => layer.groupName === AI_MARKERS_LAYER)?.groupId ||
        aiMarkersGroupIdRef.current
      const nextLayers: GeoJSONLayer[] = features.map((feature, idx) => {
        aiMarkerCounterRef.current += 1
        const color =
          String(feature.properties?.fillColor || '') ||
          LAYER_COLORS[(colorIndexRef.current + idx) % LAYER_COLORS.length]
        const label = String(feature.properties?.label || '').trim()
        return {
          id: `layer-${genId()}`,
          name: label || `Marker ${aiMarkerCounterRef.current}`,
          filePath: '',
          visible: true,
          groupId,
          groupName: AI_MARKERS_LAYER,
          data: { type: 'FeatureCollection', features: [feature] },
          color,
        }
      })
      colorIndexRef.current += nextLayers.length
      return [...prev, ...nextLayers]
    })
    setActiveLeftTab('layers')
  }, [])

  const addGroupedPointFeaturesToLayers = useCallback((
    groupName: string,
    data: FeatureCollection,
    color?: string,
  ) => {
    const features = (data.features || []).filter((feature) => feature.geometry?.type === 'Point')
    if (!features.length) return

    const groupId = `group-points-${genId()}`
    const nextLayers: GeoJSONLayer[] = features.map((feature, idx) => {
      const featureColor =
        String(feature.properties?.fillColor || feature.properties?.strokeColor || '') ||
        color ||
        LAYER_COLORS[(colorIndexRef.current + idx) % LAYER_COLORS.length]
      return {
        id: `layer-${genId()}`,
        name: pointFeatureName(feature, `${groupName} ${idx + 1}`),
        filePath: '',
        visible: true,
        groupId,
        groupName,
        data: { type: 'FeatureCollection', features: [feature] },
        color: featureColor,
      }
    })
    colorIndexRef.current += nextLayers.length
    setLayers((prev) => [...prev, ...nextLayers])
    setActiveLeftTab('layers')
  }, [])

  const handleLayerStyleChange = useCallback(
    (
      layerName: string,
      style: { fillColor?: string; lineColor?: string; opacity?: number },
    ) => {
      setLayers((prev) =>
        prev.map((l) =>
          l.name.toLowerCase() === layerName.toLowerCase()
            ? {
              ...l,
              ...(style.fillColor !== undefined ? { fillColor: style.fillColor } : {}),
              ...(style.lineColor !== undefined ? { lineColor: style.lineColor } : {}),
              ...(style.opacity !== undefined ? { opacity: style.opacity } : {}),
            }
            : l,
        ),
      )
    },
    [],
  )

  // Build a LayerStyleSpec from a `style_layer` action payload, reading the
  // layer's feature values to compute category palettes / numeric breaks.
  // Shared by the AI action path and (indirectly) the manual SymbologyPanel.
  const buildStyleSpec = useCallback(
    (
      layer: GeoJSONLayer,
      p: Extract<MapAction, { type: 'style_layer' }>['payload'],
    ): LayerStyleSpec => {
      const feats = layer.data?.features || []
      // Carry forward existing labels unless the payload changes them.
      const prevLabel = layer.styleSpec?.label
      const spec: LayerStyleSpec = {
        mode: p.mode,
        opacity: p.opacity ?? layer.styleSpec?.opacity,
        label: prevLabel,
      }

      if (p.mode === 'categorized' && p.property) {
        const values = feats.map((f) => String(f.properties?.[p.property!] ?? ''))
        spec.property = p.property
        spec.categories = p.categories?.length
          ? p.categories
          : buildCategories(values, p.property, p.ramp || 'category')
        spec.otherColor = layer.color
        spec.rampName = p.ramp || 'category'
      } else if (p.mode === 'graduated' && p.property) {
        const nums = feats
          .map((f) => Number(f.properties?.[p.property!]))
          .filter((n) => Number.isFinite(n))
        const classes = Math.max(2, Math.min(p.classes ?? 5, 9))
        const method = p.classification || 'quantile'
        const breaks = computeBreaks(nums, classes, method)
        const rampName = p.ramp || DEFAULT_RAMP
        spec.property = p.property
        spec.breaks = breaks
        // rampColors length must equal breaks.length + 1 (one color per bucket).
        spec.rampColors = rampColorsForClasses(rampName, breaks.length + 1)
        spec.classification = method
        spec.rampName = rampName
      }

      // Label changes (independent of color mode).
      if (p.label_property !== undefined || p.label_enabled !== undefined ||
        p.label_size !== undefined || p.label_color !== undefined) {
        const property = p.label_property ?? prevLabel?.property ?? ''
        spec.label = {
          enabled: p.label_enabled ?? (p.label_property ? true : prevLabel?.enabled ?? false),
          property,
          size: p.label_size ?? prevLabel?.size,
          color: p.label_color ?? prevLabel?.color,
          haloColor: prevLabel?.haloColor,
        }
      }

      return spec
    },
    [],
  )

  // Direct UI path: SymbologyPanel writes a fully-formed styleSpec onto a layer.
  const handleSymbologyChange = useCallback((layerId: string, styleSpec: LayerStyleSpec) => {
    setLayers((prev) => prev.map((l) => (l.id === layerId ? { ...l, styleSpec } : l)))
  }, [])

  const stylingLayer = useMemo(
    () => layers.find((l) => l.id === stylingLayerId) ?? null,
    [layers, stylingLayerId],
  )

  // ── Manual drawing → real layer ──
  // A user finished drawing in MapView. Promote the geometry to a layer (so it
  // persists, appears in mapContext, and can be styled), then open the
  // attribute editor so they can tag it (e.g. set zone_code) before styling.
  const handleDrawComplete = useCallback(
    (type: 'point' | 'line' | 'polygon', coordinates: number[][]) => {
      // ── Line drawing: generate 2 layers: direct straight line + OSRM driving route ──
      if (type === 'line' && coordinates.length >= 2) {
        const labelStyle: LayerStyleSpec = {
          mode: 'simple',
          label: {
            enabled: true,
            property: 'label',
            size: 13,
            color: '#111827',
            haloColor: '#ffffff',
            minZoom: 0,
          },
        }

        userShapeCounterRef.current += 1
        const measureNo = userShapeCounterRef.current

        const straightKm = turf.length(turf.lineString(coordinates), { units: 'kilometers' })
        const straightLabel = `Direct: ${formatDistance(straightKm)}`
        const directLayerId = `layer-${genId()}`
        const directName = `Direct Distance ${measureNo}`

        // Layer 1: Direct straight-line layer joining the dots
        const directLayer: GeoJSONLayer = {
          id: directLayerId,
          name: directName,
          filePath: '',
          visible: true,
          color: '#2563eb',
          lineColor: '#2563eb',
          lineWidth: 2.5,
          lineDasharray: [2, 2],
          data: {
            type: 'FeatureCollection',
            features: [
              {
                type: 'Feature',
                geometry: { type: 'LineString', coordinates },
                properties: {
                  name: directName,
                  source: 'user_draw',
                  kind: 'direct_distance',
                  distance_km: Number(straightKm.toFixed(4)),
                  distance: straightLabel,
                },
              },
              ...coordinates.map((pt, i) => ({
                type: 'Feature' as const,
                geometry: { type: 'Point' as const, coordinates: pt },
                properties: { name: i === 0 ? 'Start' : i === coordinates.length - 1 ? 'End' : `WP ${i}`, source: 'user_draw', role: 'endpoint' },
              })),
              {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: routeLabelCoordinate(coordinates, straightKm) },
                properties: { label: straightLabel, source: 'user_draw', role: 'label' },
              },
            ],
          },
          styleSpec: labelStyle,
        }

        // Add the direct layer immediately
        setLayers((prev) => [...prev, directLayer])
        setActiveLeftTab('layers')
        setAttrLayerId(null)

        // Layer 2: Fetch OSRM driving route and append as a second layer
        void fetchOsrmRoute(coordinates)
          .then((route) => {
            const routeLabel = `Route: ${formatDistance(route.distanceKm)} · ${route.durationMinutes >= 60 ? `${(route.durationMinutes / 60).toFixed(1)} hr` : `${Math.round(route.durationMinutes)} min`}`
            const routeName = `Route ${measureNo}`
            const routeLayerId = `layer-${genId()}`
            const midCoord = routeLabelCoordinate(route.coordinates, route.distanceKm)
            const routedLayer: GeoJSONLayer = {
              id: routeLayerId,
              name: routeName,
              filePath: '',
              visible: true,
              color: '#dc2626',
              lineColor: '#dc2626',
              lineWidth: 4,
              data: {
                type: 'FeatureCollection',
                features: [
                  {
                    type: 'Feature',
                    geometry: { type: 'LineString', coordinates: route.coordinates },
                    properties: {
                      name: routeName,
                      source: 'user_draw',
                      kind: 'routed_line',
                      distance_km: Number(route.distanceKm.toFixed(4)),
                      duration_minutes: Number(route.durationMinutes.toFixed(1)),
                      distance: routeLabel,
                    },
                  },
                  {
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: midCoord },
                    properties: { label: routeLabel, source: 'user_draw', role: 'label' },
                  },
                ],
              },
              styleSpec: {
                ...labelStyle,
                label: { ...labelStyle.label!, color: '#7f1d1d' },
              },
            }
            setLayers((prev) => [...prev, routedLayer])
          })
          .catch((err) => {
            console.warn('OSRM route lookup failed, direct line retained:', err)
          })
        return
      }

      let geometry: Geometry
      if (type === 'point') {
        geometry = { type: 'Point', coordinates: coordinates[0] }
      } else if (type === 'line') {
        geometry = { type: 'LineString', coordinates }
      } else {
        const ring =
          coordinates[0][0] !== coordinates[coordinates.length - 1][0] ||
            coordinates[0][1] !== coordinates[coordinates.length - 1][1]
            ? [...coordinates, coordinates[0]]
            : coordinates
        geometry = { type: 'Polygon', coordinates: [ring] }
      }
      userShapeCounterRef.current += 1
      const label = type === 'point' ? 'Point' : type === 'line' ? 'Line' : 'Polygon'
      const name = `Drawn ${label} ${userShapeCounterRef.current}`
      const id = `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
      const color = LAYER_COLORS[colorIndexRef.current % LAYER_COLORS.length]
      colorIndexRef.current++
      const layer: GeoJSONLayer = {
        id,
        name,
        filePath: '',
        visible: true,
        color,
        data: {
          type: 'FeatureCollection',
          features: [{ type: 'Feature', geometry, properties: { name, source: 'user_draw' } }],
        },
      }
      setLayers((prev) => [...prev, layer])
      setActiveLeftTab('layers')
      setAttrLayerId(id) // open the attribute editor on the new layer
    },
    [],
  )

  // Attribute editor writes an edited FeatureCollection back onto a layer.
  const handleAttributesChange = useCallback((layerId: string, data: FeatureCollection) => {
    dirtyLayerIdsRef.current.add(layerId)
    setLayers((prev) => prev.map((l) => (l.id === layerId ? { ...l, data } : l)))
  }, [])

  const attrLayer = useMemo(
    () => layers.find((l) => l.id === attrLayerId) ?? null,
    [layers, attrLayerId],
  )

  const displayLayersCount = useMemo(
    () => layers.length,
    [layers],
  )

  // ── Map action handler (intercepts layer ops, queues the rest) ──

  const handleMapAction = useCallback((action: MapAction) => {
    if (action.type === 'switch_basemap') {
      const bm = String(action.payload.basemap || '').toLowerCase()
      if (BASEMAPS[bm]) {
        setBasemap(bm)
      }
      return
    }
    if (action.type === 'georeference_success') {
      setAppMode('map')
      return
    }
    if (action.type === 'style_layer') {
      const p = action.payload
      setLayers((prev) =>
        prev.map((l) =>
          l.name.toLowerCase() === p.layer_name?.toLowerCase()
            ? { ...l, styleSpec: buildStyleSpec(l, p) }
            : l,
        ),
      )
      setActiveLeftTab('layers')
      return
    }
    if (action.type === 'save_bookmark') {
      const { name, south, west, north, east, zoom } = action.payload
      const bounds =
        south != null && west != null && north != null && east != null
          ? { south, west, north, east }
          : mapBoundsRef.current
      if (!name || !bounds) return
      setBookmarks((prev) => [
        ...prev,
        {
          id: genId(),
          name: String(name),
          south: bounds.south,
          west: bounds.west,
          north: bounds.north,
          east: bounds.east,
          zoom: zoom != null ? Number(zoom) : mapViewState.zoom,
        },
      ])
      setActiveLeftTab('bookmarks')
      return
    }
    if (action.type === 'go_to_bookmark') {
      const raw = String(action.payload.name || '').toLowerCase()
      const bm = bookmarksRef.current.find(
        (x) =>
          x.name.toLowerCase().includes(raw) || raw.includes(x.name.toLowerCase()),
      )
      if (bm) {
        setMapActions((prev) => [
          ...prev,
          {
            type: 'fit_bounds',
            payload: {
              south: bm.south,
              west: bm.west,
              north: bm.north,
              east: bm.east,
            },
          },
        ])
      }
      return
    }
    if (action.type === 'export_region_clip') {
      const { output_base_name, south, west, north, east } = action.payload
      const explicit =
        south != null && west != null && north != null && east != null
          ? { south: Number(south), west: Number(west), north: Number(north), east: Number(east) }
          : undefined
      void clipLayersToBboxAndSave(String(output_base_name || 'clipped'), explicit)
      return
    }
    if (action.type === 'add_wms_layer') {
      const { url, layer_name, title } = action.payload
      // Deduplicate: if this exact WMS url+layer is already loaded, just make
      // it visible instead of adding a second copy.
      const existing = layers.find(
        (l) => l.wmsSpec && l.wmsSpec.url === url && l.wmsSpec.layer_name === layer_name,
      )
      if (existing) {
        setLayers((prev) =>
          prev.map((l) => (l.id === existing.id ? { ...l, visible: true } : l)),
        )
        setActiveLeftTab('layers')
        return
      }
      const id = `wms-${Date.now()}`
      const newLayer: GeoJSONLayer = {
        id,
        name: title || layer_name,
        filePath: '',
        visible: true,
        data: { type: 'FeatureCollection', features: [] },
        color: '#06b6d4',
        wmsSpec: { url, layer_name }
      }
      setLayers((prev) => [...prev, newLayer])
      setActiveLeftTab('layers')
      return
    }
    if (action.type === 'add_gee_layer') {
      const { url, dataset, vis_params, title } = action.payload
      // Deduplicate by dataset name. GEE tile tokens expire after ~24h, so if
      // the same dataset is re-added we update the URL (refresh token) and
      // make the layer visible rather than creating a duplicate entry.
      const existing = layers.find(
        (l) => l.geeSpec && l.geeSpec.dataset === dataset,
      )
      if (existing) {
        setLayers((prev) =>
          prev.map((l) =>
            l.id === existing.id
              ? { ...l, visible: true, geeSpec: { url, dataset, vis_params } }
              : l,
          ),
        )
        setActiveLeftTab('layers')
        return
      }
      const id = `gee-${Date.now()}`
      const newLayer: GeoJSONLayer = {
        id,
        name: title || dataset,
        filePath: '',
        visible: true,
        data: { type: 'FeatureCollection', features: [] },
        color: '#89b4fa',
        geeSpec: { url, dataset, vis_params }
      }
      setLayers((prev) => [...prev, newLayer])
      setActiveLeftTab('layers')
      return
    }
    if (action.type === 'add_geojson_file') {
      const { path, name, color, styleSpec } = action.payload
      void addLayer(name, path, color, styleSpec)
      return
    }
    if (action.type === 'add_geojson') {
      const { geojson, name, color } = action.payload
      setAppMode('map') // Auto-switch to Map view
      const geometryTypes = ['Point', 'MultiPoint', 'LineString', 'MultiLineString', 'Polygon', 'MultiPolygon', 'GeometryCollection']
      const data: FeatureCollection =
        geojson && 'type' in geojson && geojson.type === 'FeatureCollection'
          ? (geojson as FeatureCollection)
          : geojson && 'type' in geojson && geojson.type === 'Feature'
            ? { type: 'FeatureCollection', features: [geojson as Feature] }
            : geojson && 'type' in geojson && geometryTypes.includes(geojson.type as string)
              ? { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: geojson as Geometry, properties: {} }] }
              : { type: 'FeatureCollection', features: [] }
      const layerName = name || 'AI Layer'
      if (isPointOnlyCollection(data)) {
        addGroupedPointFeaturesToLayers(layerName, data, color)
      } else {
        upsertLayer(layerName, data, color)
      }
      return
    }
    if (action.type === 'toggle_layer') {
      setLayers((prev) =>
        prev.map((l) =>
          l.name.toLowerCase() === action.payload.layer_name?.toLowerCase()
            ? { ...l, visible: !!action.payload.visible }
            : l,
        ),
      )
      return
    }
    if (action.type === 'remove_layer') {
      setLayers((prev) =>
        prev.filter(
          (l) => l.name.toLowerCase() !== action.payload.layer_name?.toLowerCase(),
        ),
      )
      return
    }
    if (action.type === 'refresh_artifacts') {
      setArtifactsRevision((n) => n + 1)
      setAppMode('artifacts')
      return
    }
    // AI-placed pins become separate one-point layers inside the persistent
    if (action.type === 'add_marker') {
      addAiMarkersToGroup([action.payload])
      return
    }
    if (action.type === 'add_markers') {
      const list = Array.isArray(action.payload?.markers) ? action.payload.markers : []
      addAiMarkersToGroup(list)
      return
    }
    if (action.type === 'clear_markers') {
      setLayers((prev) =>
        compactLayerGroups(prev.filter((l) =>
          l.name.toLowerCase() !== AI_MARKERS_LAYER.toLowerCase() && !layerHasAiMarkers(l),
        )),
      )
      return
    }
    if (action.type === 'draw_distance_measurement') {
      const { points, direct_km, route_coordinates, route_km, duration_minutes } = action.payload
      if (!Array.isArray(points) || points.length < 2) return

      const labelStyle: LayerStyleSpec = {
        mode: 'simple',
        label: { enabled: true, property: 'label', size: 13, color: '#111827', haloColor: '#ffffff', minZoom: 0 },
      }

      userShapeCounterRef.current += 1
      const measureNo = userShapeCounterRef.current
      const directLabel = `Direct: ${formatDistance(direct_km)}`
      const directName = `Direct Distance ${measureNo}`

      const directFeatures: Feature[] = [
        {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: points },
          properties: {
            name: directName, source: 'user_measure', kind: 'direct_distance',
            distance_km: Number(direct_km.toFixed(4)), distance: directLabel,
          },
        },
        // Endpoint markers
        ...points.map((pt, i) => ({
          type: 'Feature' as const,
          geometry: { type: 'Point' as const, coordinates: pt },
          properties: { name: i === 0 ? 'Start' : i === points.length - 1 ? 'End' : `WP ${i}`, source: 'user_measure', role: 'endpoint' },
        })),
        {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: routeLabelCoordinate(points, direct_km) },
          properties: { label: directLabel, source: 'user_measure', role: 'label' },
        },
      ]

      const directLayer: GeoJSONLayer = {
        id: `layer-${genId()}`, name: directName, filePath: '', visible: true,
        color: '#2563eb', lineColor: '#2563eb', lineWidth: 2.5, lineDasharray: [2, 2],
        data: { type: 'FeatureCollection', features: directFeatures }, styleSpec: labelStyle,
      }

      setLayers((prev) => [...prev, directLayer])
      setActiveLeftTab('layers')

      // Add route layer if OSRM data was returned
      if (Array.isArray(route_coordinates) && route_coordinates.length >= 2 && route_km != null) {
        const routeLabel = `Route: ${formatDistance(route_km)}${duration_minutes != null ? ` (~${duration_minutes.toFixed(0)} min)` : ''}`
        const routeName = `Route Distance ${measureNo}`
        const routeLayer: GeoJSONLayer = {
          id: `layer-${genId()}`, name: routeName, filePath: '', visible: true,
          color: '#dc2626', lineColor: '#dc2626', lineWidth: 4,
          data: {
            type: 'FeatureCollection',
            features: [
              {
                type: 'Feature',
                geometry: { type: 'LineString', coordinates: route_coordinates },
                properties: {
                  name: routeName, source: 'user_measure', kind: 'route_distance',
                  distance_km: Number(route_km.toFixed(4)),
                  duration_minutes: duration_minutes != null ? Number(duration_minutes.toFixed(1)) : null,
                  distance: routeLabel,
                },
              },
              {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: routeLabelCoordinate(route_coordinates, route_km) },
                properties: { label: routeLabel, source: 'user_measure', role: 'label' },
              },
            ],
          },
          styleSpec: labelStyle,
        }
        setLayers((prev) => [...prev, routeLayer])
      }
      return
    }
    // Promote AI-drawn shapes to real layers so they appear in mapContext on
    // the next turn. Without this they live only in the MapView ref and the
    // assistant can't see them again.
    if (action.type === 'draw_line') {
      const { coordinates, label, color } = action.payload
      if (Array.isArray(coordinates) && coordinates.length >= 2) {
        aiShapeNameCounterRef.current += 1
        const name = label || `AI Line ${aiShapeNameCounterRef.current}`
        upsertLayer(
          name,
          {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              geometry: { type: 'LineString', coordinates },
              properties: { label: label || '', source: 'ai_draw' },
            }],
          },
          color,
        )
      }
      return
    }
    if (action.type === 'draw_polygon') {
      const { coordinates, label, color } = action.payload
      const raw = Array.isArray(coordinates) ? coordinates : []
      if (raw.length >= 3) {
        const ring =
          raw[0][0] !== raw[raw.length - 1][0] || raw[0][1] !== raw[raw.length - 1][1]
            ? [...raw, raw[0]]
            : raw
        aiShapeNameCounterRef.current += 1
        const name = label || `AI Polygon ${aiShapeNameCounterRef.current}`
        upsertLayer(
          name,
          {
            type: 'FeatureCollection',
            features: [{
              type: 'Feature',
              geometry: { type: 'Polygon', coordinates: [ring] },
              properties: { label: label || '', source: 'ai_draw' },
            }],
          },
          color,
        )
      }
      return
    }
    if (action.type === 'draw_circle') {
      const { center_lng, center_lat, radius_km, label, color } = action.payload
      if (radius_km > 0) {
        const circle = turf.circle([center_lng, center_lat], radius_km, {
          units: 'kilometers',
          steps: 64,
        })
        circle.properties = {
          label: label || '',
          source: 'ai_draw',
          center_lng,
          center_lat,
          radius_km,
        }
        aiShapeNameCounterRef.current += 1
        const name = label || `AI Circle ${aiShapeNameCounterRef.current}`
        upsertLayer(
          name,
          { type: 'FeatureCollection', features: [circle] },
          color,
        )
      }
      return
    }
    if (action.type === 'add_scenarios') {
      const list = Array.isArray(action.payload.scenarios) ? action.payload.scenarios : []
      setScenarios((prev) => {
        const newScenarios = list.map((s: any) => ({
          id: s.id || `scenario-${Math.random().toString(36).substring(2, 9)}`,
          name: String(s.name || 'Scenario'),
          description: String(s.description || ''),
          createdAt: Number(s.createdAt || Date.now()),
          layerIds: Array.isArray(s.layerIds) ? s.layerIds : layers.map(l => l.id),
          layerVisibility: typeof s.layerVisibility === 'object' && s.layerVisibility ? s.layerVisibility : Object.fromEntries(layers.map(l => [l.id, l.visible])),
        }))
        // Filter out any existing scenarios with the same name to avoid duplicates
        const filteredPrev = prev.filter(p => !newScenarios.some(n => n.name === p.name))
        return [...filteredPrev, ...newScenarios]
      })
      setActiveLeftTab('scenarios')
      return
    }
    if (action.type === 'add_raster_overlay') {
      const { id, name, filePath, corners } = action.payload
      setLayers((prev) => {
        const existing = prev.find((l) => l.id === id)
        if (existing) {
          return prev.map((l) =>
            l.id === id
              ? { ...l, visible: true, rasterOverlaySpec: { url: filePath, corners } }
              : l,
          )
        } else {
          return [
            ...prev,
            {
              id,
              name,
              filePath,
              visible: true,
              data: { type: 'FeatureCollection', features: [] },
              color: '#10b981',
              rasterOverlaySpec: { url: filePath, corners },
              opacity: 0.8,
            },
          ]
        }
      })
      setActiveLeftTab('layers')
      setMapActions((prev) => [...prev, action])
      return
    }
    setMapActions((prev) => [...prev, action])
  }, [
    upsertLayer,
    clipLayersToBboxAndSave,
    addAiMarkersToGroup,
    addGroupedPointFeaturesToLayers,
    mapViewState.zoom,
    buildStyleSpec,
  ])

  // ── Right-click map actions ──

  const handleRightClickAddMarker = useCallback(
    (lng: number, lat: number) => {
      // Place immediately with a coordinate label, then upgrade to the
      // reverse-geocoded address when it resolves. Never block the pin.
      addAiMarkersToGroup([{ lng, lat, label: `${lat.toFixed(5)}, ${lng.toFixed(5)}` }])
      window.electronAPI.getGoogleMapsKey().then((googleKey) => {
        const headers: Record<string, string> = {}
        if (googleKey) {
          headers['x-google-maps-key'] = googleKey
        }
        fetch(`http://localhost:8765/api/geocode/reverse?lat=${lat}&lng=${lng}`, { headers })
          .then((r) => r.json())
          .then((d: { display_name?: string | null }) => {
            if (!d?.display_name) return
            setLayers((prev) =>
              prev.map((l) => {
                const feature = l.data?.features?.[0]
                const g = feature?.geometry
                if (
                  feature?.properties?.source !== 'ai_marker' ||
                  g?.type !== 'Point' ||
                  g.coordinates[0] !== lng ||
                  g.coordinates[1] !== lat
                ) {
                  return l
                }
                dirtyLayerIdsRef.current.add(l.id)
                return {
                  ...l,
                  name: d.display_name || l.name,
                  data: {
                    type: 'FeatureCollection',
                    features: [{
                      ...feature,
                      properties: { ...feature.properties, label: d.display_name },
                    }],
                  } as FeatureCollection,
                }
              }),
            )
          })
          .catch(() => { /* keep coordinate label */ })
      }).catch(() => { /* keep coordinate label */ })
    },
    [addAiMarkersToGroup],
  )

  const handleStreetViewDetailChange = useCallback((val: boolean) => {
    setStreetViewDetail(val)
    if (!val) {
      setStreetViewActive(false)
      setStreetViewTarget(null)
      setStreetViewLocation(null)
      setRoadInspectionTarget(null)
    }
  }, [])

  const handleRightClickStreetView = useCallback((lng: number, lat: number) => {
    setStreetViewTarget({ lng, lat })
    setStreetViewActive(true)
    setStreetViewDetail(true)
  }, [])

  const handleInspectRoad = useCallback((feature: Feature) => {
    const geometry = feature.geometry
    if (!geometry || (geometry.type !== 'LineString' && geometry.type !== 'MultiLineString')) return
    const props = feature.properties || {}
    const nameKey = ['name', 'title', 'label', 'Name', 'Label', 'road', 'street'].find(
      (k) => props[k] != null && String(props[k]).trim() !== '',
    )
    setRoadInspectionTarget({
      geometry,
      name: nameKey ? String(props[nameKey]).trim() : 'Selected road',
    })
    setStreetViewActive(true)
  }, [])

  const handleRightClickAskChat = useCallback(
    (lng: number, lat: number) => {
      const text =
        `Tell me everything you can about this location (${lat.toFixed(5)}, ${lng.toFixed(5)}): ` +
        `the address/neighborhood, nearby amenities, demographics, weather, and any notable features. Use your tools.`
      setInjectedMessage((prev) => ({ text, nonce: (prev?.nonce || 0) + 1 }))
    },
    [],
  )

  const handleContextualQuery = useCallback(
    (feature: Feature, lngLat: { lng: number; lat: number }) => {
      const props = feature.properties || {}
      const titleKey = ['name', 'title', 'label', 'Name', 'Label'].find((k) => props[k] != null && String(props[k]).trim() !== '')
      const title = titleKey ? String(props[titleKey]).trim() : ''
      const propsList = Object.entries(props)
        .filter(([k]) => k !== 'layerName' && k !== 'groupId' && k !== 'groupName' && k !== 'fillColor' && k !== 'lineColor')
        .map(([k, v]) => `  - **${k}**: ${v}`)
        .join('\n')

      let text = `Tell me about this feature`
      if (title) text += ` named "${title}"`
      text += ` at location (${lngLat.lat.toFixed(5)}, ${lngLat.lng.toFixed(5)}):\n`
      if (propsList) {
        text += `\nProperties:\n${propsList}\n`
      }
      text += `\nWhat can you analyze about this based on surrounding data? Use your tools.`
      setInjectedMessage((prev) => ({ text, nonce: (prev?.nonce || 0) + 1 }))
    },
    [],
  )

  // ── Map context for AI ──

  const mapContext: MapContext = useMemo(
    () => ({
      workspace: workspacePath || undefined,
      activeScenario: activeScenarioId
        ? {
          name: scenarios.find((s) => s.id === activeScenarioId)?.name || '',
          description: scenarios.find((s) => s.id === activeScenarioId)?.description || '',
        }
        : undefined,
      center: mapViewState.center,
      zoom: mapViewState.zoom,
      bounds: mapBounds
        ? { west: mapBounds.west, south: mapBounds.south, east: mapBounds.east, north: mapBounds.north }
        : undefined,
      bookmarks: bookmarks.map((b) => ({
        name: b.name, south: b.south, west: b.west, north: b.north, east: b.east, zoom: b.zoom,
      })),
      layers: layers.map((l) => {
        const features: Feature[] = l.data?.features || []
        const featureCount = features.length
        const geometryTypes = [
          ...new Set(
            features.map((f) => f.geometry?.type).filter((t): t is NonNullable<typeof t> => Boolean(t)),
          ),
        ]
        const properties = [
          ...new Set(
            features.flatMap((f) => Object.keys(f.properties || {})),
          ),
        ].slice(0, 20)

        // Include actual coordinates for small layers (≤5 features) so the
        // LLM can compute centroids, buffers, intersections, etc.
        let geometry_data: LayerGeometryData | undefined = undefined
        const totalCoords = features.reduce((sum: number, f) => {
          const g = f.geometry
          if (!g || !('coordinates' in g)) return sum
          const c = g.coordinates
          if (g.type === 'Point') return sum + 1
          if (g.type === 'LineString' && Array.isArray(c)) return sum + c.length
          if (g.type === 'Polygon' && Array.isArray(c)) return sum + ((c[0] as unknown[])?.length || 0)
          if (g.type === 'MultiPolygon' && Array.isArray(c))
            return sum + (c as unknown[][][]).reduce((s, p) => s + (p[0]?.length || 0), 0)
          return sum + 10
        }, 0)

        if (featureCount <= 5 && totalCoords <= 1000) {
          geometry_data = features.map((f) => ({
            type: f.geometry?.type,
            coordinates: f.geometry && 'coordinates' in f.geometry ? f.geometry.coordinates : undefined,
          }))
        } else {
          try {
            const bbox = turf.bbox(l.data) as [number, number, number, number]
            if (bbox.every((v) => isFinite(v))) {
              geometry_data = { bbox }
            }
          } catch { /* ignore */ }
        }

        const s = l.styleSpec
        const style = s
          ? {
            mode: s.mode,
            property: s.property,
            categoryCount: s.categories?.length,
            classes: s.breaks ? s.breaks.length + 1 : undefined,
            ramp: s.rampName,
            labels: (s.label?.enabled
              ? { property: s.label.property }
              : false) as false | { property: string },
          }
          : { mode: 'simple' as const, labels: false as const }

        const features_data = featureCount <= 100
          ? features.map((f) => f.properties || {})
          : undefined

        const endpoints = extractLineEndpoints(features)

        return {
          name: l.name,
          filePath: l.filePath,
          featureCount,
          geometryTypes,
          properties,
          visible: l.visible,
          // Layer type helps the LLM know this is a raster (no features to query)
          layerType: l.wmsSpec ? 'wms' : l.geeSpec ? 'gee' : 'vector',
          ...(l.wmsSpec ? { wmsUrl: l.wmsSpec.url, wmsLayerName: l.wmsSpec.layer_name } : {}),
          ...(l.geeSpec ? { geeDataset: l.geeSpec.dataset } : {}),
          ...(l.groupId !== undefined ? { groupId: l.groupId } : {}),
          ...(l.groupName !== undefined ? { groupName: l.groupName } : {}),
          ...(geometry_data ? { geometry_data } : {}),
          ...(features_data ? { features_data } : {}),
          ...endpoints,
          style,
        }

      }),
      basemap,
    }),
    [workspacePath, mapViewState, mapBounds, bookmarks, layers, basemap, activeScenarioId, scenarios],
  )

  // ── Conversation helpers ──

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  )

  const handleCreateConversation = useCallback(() => {
    const id = genId()
    const conv: Conversation = { id, title: 'New chat', messages: [], createdAt: Date.now() }
    setConversations((prev) => [conv, ...prev])
    setActiveConversationId(id)
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setActiveConversationId(id)
  }, [])

  const handleDeleteConversation = useCallback(
    (id: string) => {
      setConversations((prev) => prev.filter((c) => c.id !== id))
      if (activeConversationId === id) {
        setActiveConversationId(null)
      }
    },
    [activeConversationId],
  )

  const handleConversationMessagesChange = useCallback(
    (messages: import('./types').ChatMessage[]) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== activeConversationId) return c
          const title =
            c.title === 'New chat' && messages.length > 0
              ? (messages.find((m) => m.role === 'user')?.content.slice(0, 60) || 'New chat')
              : c.title
          return { ...c, messages, title }
        }),
      )
    },
    [activeConversationId],
  )

  const handleRenameConversation = useCallback((id: string, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c))
    )
  }, [])

  // ── Project persistence ──

  const saveProject = useCallback(
    async (force = false) => {
      if (!workspacePath) return
      if (!force && isLoadingRef.current) return
      isSavingRef.current = true
      try {
        const wsPrefix = workspacePath.endsWith('/') ? workspacePath : `${workspacePath}/`
        const toRelative = (fp: string): string =>
          fp.startsWith(wsPrefix) ? fp.slice(wsPrefix.length) : fp

        // Save all dirty or new layers concurrently
        const writePromises = layers.map(async (l) => {
          const isAiMarkers = l.name.toLowerCase() === AI_MARKERS_LAYER.toLowerCase()
          const isDirty = dirtyLayerIdsRef.current.has(l.id)
          const needsWrite = !l.filePath?.trim() || isAiMarkers || isDirty

          if (!needsWrite) {
            return l
          }

          let fp = l.filePath
          if (isAiMarkers) {
            fp = `${workspacePath}/ai_markers.geojson`
          } else if (!fp?.trim()) {
            fp = `${workspacePath}/.disha/layers/${l.id}.geojson`
          }

          const ok = await window.electronAPI.writeFile(fp, JSON.stringify(l.data, null, 2))
          if (!ok) {
            console.error('Failed to persist layer:', l.name)
            return l
          }
          dirtyLayerIdsRef.current.delete(l.id)
          return { ...l, filePath: fp }
        })

        const resolvedLayers = await Promise.all(writePromises)
        const materializedAny = resolvedLayers.some((l, idx) => l.filePath !== layers[idx].filePath)

        if (materializedAny) {
          setLayers(resolvedLayers)
        }

        const projectData: ProjectData = {
          mapState: mapViewState,
          layers: resolvedLayers.map((l) => ({
            name: l.name,
            filePath: toRelative(l.filePath),
            visible: l.visible,
            ...(l.groupId !== undefined ? { groupId: l.groupId } : {}),
            ...(l.groupName !== undefined ? { groupName: l.groupName } : {}),
            ...(l.groupPathIds !== undefined ? { groupPathIds: l.groupPathIds } : {}),
            ...(l.groupPathNames !== undefined ? { groupPathNames: l.groupPathNames } : {}),
            color: l.color,
            ...(l.fillColor !== undefined ? { fillColor: l.fillColor } : {}),
            ...(l.lineColor !== undefined ? { lineColor: l.lineColor } : {}),
            ...(l.lineWidth !== undefined ? { lineWidth: l.lineWidth } : {}),
            ...(l.lineDasharray !== undefined ? { lineDasharray: l.lineDasharray } : {}),
            ...(l.opacity !== undefined ? { opacity: l.opacity } : {}),
            ...(l.styleSpec !== undefined ? { styleSpec: l.styleSpec } : {}),
            ...(l.wmsSpec !== undefined ? { wmsSpec: l.wmsSpec } : {}),
            ...(l.geeSpec !== undefined ? { geeSpec: l.geeSpec } : {}),
          })),
          conversations,
          activeConversationId,
          basemap,
          bookmarks,
        }
        const wrote = await window.electronAPI.writeFile(
          `${workspacePath}/project.json`,
          JSON.stringify(projectData, null, 2),
        )
        if (!wrote) console.error('Failed to save project.json (check workspace permissions)')
      } finally {
        isSavingRef.current = false
      }
    },
    [workspacePath, mapViewState, layers, conversations, activeConversationId, basemap, bookmarks],
  )

  saveProjectRef.current = saveProject

  const loadProject = useCallback(async () => {
    if (!workspacePath) return
    isLoadingRef.current = true
    setBookmarks([])
    try {
      const content = await window.electronAPI.readFile(`${workspacePath}/project.json`)
      if (!content) {
        setLayers([])
        setSelectedLayerIds(new Set())
        setSelectedFeatures([])
        setConversations([])
        setActiveConversationId(null)
        setBookmarks([])
        setOpenDocs([])
        setActiveDocId(null)
        setDocumentImage(null)
        // Use the same 500ms guard as the normal path so that the auto-save
        // effect can't fire before React has flushed the empty-state updates.
        setTimeout(() => { isLoadingRef.current = false }, 500)
        return
      }
      const data: ProjectData = JSON.parse(content)
      setSelectedLayerIds(new Set())
      setSelectedFeatures([])
      if (data.mapState) {
        setMapViewState(data.mapState)
        setMapActions([{ type: 'set_view', payload: data.mapState }])
      }
      if (data.basemap) setBasemap(data.basemap)
      if (data.bookmarks && data.bookmarks.length > 0) {
        setBookmarks(data.bookmarks)
      } else {
        setBookmarks([])
      }

      if (data.conversations && data.conversations.length > 0) {
        setConversations(data.conversations)
        setActiveConversationId(data.activeConversationId ?? data.conversations[0].id)
      } else if (data.chatHistory && data.chatHistory.length > 0) {
        const migrated: Conversation = {
          id: genId(),
          title: data.chatHistory.find((m) => m.role === 'user')?.content.slice(0, 60) || 'Imported chat',
          messages: data.chatHistory,
          createdAt: data.chatHistory[0]?.timestamp || Date.now(),
        }
        setConversations([migrated])
        setActiveConversationId(migrated.id)
      } else {
        setConversations([])
        setActiveConversationId(null)
      }

      await loadDocumentsFromWorkspace(workspacePath)

      if (data.layers) {
        const loadedLayers: GeoJSONLayer[] = []
        const wsPrefix = workspacePath.endsWith('/') ? workspacePath : `${workspacePath}/`
        for (const info of data.layers) {
          const isWmsOrGee = !!info.wmsSpec || !!info.geeSpec
          if (!isWmsOrGee && !info.filePath?.trim()) {
            console.warn('Skipping layer with no file path (re-add from chat or disk):', info.name)
            continue
          }
          if (isWmsOrGee) {
            const gpIds = info.groupPathIds || (info.groupId ? [info.groupId] : undefined)
            const gpNames = info.groupPathNames || (info.groupName ? [info.groupName] : (info.groupId ? ['Group'] : undefined))
            loadedLayers.push({
              id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
              name: info.name,
              filePath: '',
              visible: info.visible,
              ...(info.groupId !== undefined ? { groupId: info.groupId } : {}),
              ...(info.groupName !== undefined ? { groupName: info.groupName } : {}),
              ...(gpIds !== undefined ? { groupPathIds: gpIds } : {}),
              ...(gpNames !== undefined ? { groupPathNames: gpNames } : {}),
              data: { type: 'FeatureCollection', features: [] },
              color: info.color,
              ...(info.fillColor !== undefined ? { fillColor: info.fillColor } : {}),
              ...(info.lineColor !== undefined ? { lineColor: info.lineColor } : {}),
              ...(info.lineWidth !== undefined ? { lineWidth: info.lineWidth } : {}),
              ...(info.lineDasharray !== undefined ? { lineDasharray: info.lineDasharray } : {}),
              ...(info.opacity !== undefined ? { opacity: info.opacity } : {}),
              styleSpec: info.styleSpec,
              wmsSpec: info.wmsSpec,
              geeSpec: info.geeSpec,
            })
            continue
          }
          // Resolve relative paths against the current workspace so the
          // project survives a workspace-folder move. Absolute paths from
          // older project.json files keep working.
          const fp = info.filePath || ''
          const resolved = fp.startsWith('/')
            ? fp
            : `${wsPrefix}${fp}`
          const fileContent = await window.electronAPI.readFile(resolved)
          if (!fileContent) {
            console.warn('Layer file missing:', info.name, resolved)
            continue
          }
          try {
            const raw = JSON.parse(fileContent)
            const geojson =
              raw.type === 'FeatureCollection'
                ? raw
                : raw.type === 'Feature'
                  ? { type: 'FeatureCollection', features: [raw] }
                  : {
                    type: 'FeatureCollection',
                    features: [{ type: 'Feature', geometry: raw, properties: {} }],
                  }
            const isAiMarkers = info.name.toLowerCase() === AI_MARKERS_LAYER.toLowerCase()
            const defaultStyleSpec = isAiMarkers ? {
              mode: 'simple' as const,
              label: {
                enabled: true,
                property: 'label',
                size: 12,
                color: '#1e1e2e',
                haloColor: '#ffffff',
                minZoom: 0,
              }
            } : undefined

            const finalStyleSpec = info.styleSpec !== undefined
              ? (isAiMarkers ? {
                ...defaultStyleSpec,
                ...info.styleSpec,
                label: {
                  ...defaultStyleSpec?.label,
                  ...info.styleSpec?.label,
                }
              } : info.styleSpec)
              : defaultStyleSpec

            const gpIds = info.groupPathIds || (info.groupId ? [info.groupId] : undefined)
            const gpNames = info.groupPathNames || (info.groupName ? [info.groupName] : (info.groupId ? ['Group'] : undefined))
            loadedLayers.push({
              id: `layer-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
              name: info.name,
              filePath: resolved,
              visible: info.visible,
              ...(info.groupId !== undefined ? { groupId: info.groupId } : {}),
              ...(info.groupName !== undefined ? { groupName: info.groupName } : {}),
              ...(gpIds !== undefined ? { groupPathIds: gpIds } : {}),
              ...(gpNames !== undefined ? { groupPathNames: gpNames } : {}),
              data: geojson,
              color: info.color,
              ...(info.fillColor !== undefined ? { fillColor: info.fillColor } : {}),
              ...(info.lineColor !== undefined ? { lineColor: info.lineColor } : {}),
              ...(info.lineWidth !== undefined ? { lineWidth: info.lineWidth } : {}),
              ...(info.lineDasharray !== undefined ? { lineDasharray: info.lineDasharray } : {}),
              ...(info.opacity !== undefined ? { opacity: info.opacity } : {}),
              styleSpec: finalStyleSpec,
            })
          } catch {
            /* skip invalid files */
          }
        }
        setLayers(loadedLayers)
        setSelectedLayerIds(new Set())
        setSelectedFeatures([])
        colorIndexRef.current = loadedLayers.length
      } else {
        setLayers([])
        setSelectedLayerIds(new Set())
        setSelectedFeatures([])
      }
    } catch (e) {
      console.error('Failed to load project:', e)
    }
    setTimeout(() => {
      isLoadingRef.current = false
    }, 500)
  }, [workspacePath])

  useEffect(() => {
    if (workspacePath) loadProject()
  }, [workspacePath, loadProject])

  useEffect(() => {
    if (!workspacePath || isLoadingRef.current || isSavingRef.current || isClosingRef.current) return
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => void saveProject(), 800)
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    }
  }, [workspacePath, mapViewState, layers, conversations, activeConversationId, basemap, bookmarks, saveProject])

  useEffect(() => {
    window.electronAPI.onAppBeforeQuit(async () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
        saveTimeoutRef.current = null
      }
      if (saveDocsTimeoutRef.current) {
        clearTimeout(saveDocsTimeoutRef.current)
        saveDocsTimeoutRef.current = null
      }
      await Promise.all([
        saveProjectRef.current(true),
        saveDocuments()
      ])
    })
  }, [saveDocuments])

  // Track macOS fullscreen state so the traffic-light drag spacer can
  // collapse when there are no buttons to clear.
  useEffect(() => {
    window.electronAPI.onFullscreenChange((fs) => setIsFullscreen(fs))
  }, [])

  const workspaceLabel = workspacePath ? workspacePath.split('/').pop() : 'Open Workspace'
  const workspaceName = workspacePath
    ? (workspacePath.includes('/') ? workspacePath.split('/').pop() : workspacePath.split('\\').pop())
    : ''

  return (
    <div className="app">
      <header className="titlebar">
        <div className="titlebar-left">
          {/* Traffic-light drag spacer: collapses in fullscreen where buttons are hidden */}
          <div className="titlebar-drag" style={{ width: isFullscreen ? 0 : undefined }} />
          <div className="titlebar-brand">
            <img src={appIcon} className="titlebar-logo" alt="Disha Logo" />
            <span className="titlebar-text">Disha</span>
          </div>
          <div className="workspace-container">
            <button
              className="workspace-btn"
              onClick={handleSelectWorkspace}
              disabled={isTransitioning}
            >
              {isTransitioning ? (
                <>
                  <span className="titlebar-spinner" /> Saving...
                </>
              ) : (
                workspaceLabel
              )}
            </button>
            {workspacePath && !isTransitioning && (
              <button
                className="workspace-close-mini-btn"
                onClick={handleCloseWorkspace}
                title="Close workspace"
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            )}
          </div>
        </div>

        <div className="titlebar-center">
          <div className="mode-switcher">
            <button
              className={`mode-btn ${appMode === 'map' ? 'active' : ''}`}
              onClick={() => setAppMode('map')}
            >
              Map
            </button>
            <button
              className={`mode-btn ${appMode === 'document' ? 'active' : ''}`}
              onClick={() => setAppMode('document')}
            >
              Document
            </button>
            <button
              className={`mode-btn ${appMode === 'artifacts' ? 'active' : ''}`}
              onClick={() => setAppMode('artifacts')}
            >
              Artifacts
            </button>
          </div>
        </div>

        <div className="titlebar-right">
          <div className="sidebar-toggles">
            {(appMode === 'map' || appMode === 'artifacts' || appMode === 'document') && (
              <button
                className={`sidebar-toggle-btn ${(appMode === 'map'
                    ? leftWidth > 0
                    : appMode === 'document'
                      ? showDocumentSidebar
                      : showArtifactsSidebar)
                    ? 'active'
                    : ''
                  }`}
                title={
                  (appMode === 'map'
                    ? leftWidth > 0
                    : appMode === 'document'
                      ? showDocumentSidebar
                      : showArtifactsSidebar)
                    ? "Hide Left Sidebar"
                    : "Show Left Sidebar"
                }
                onClick={
                  appMode === 'map'
                    ? toggleLeft
                    : appMode === 'document'
                      ? () => setShowDocumentSidebar(!showDocumentSidebar)
                      : () => setShowArtifactsSidebar(!showArtifactsSidebar)
                }
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <rect x="2" y="2" width="12" height="12" rx="1.5" />
                  <line x1="6" y1="2" x2="6" y2="14" />
                  <path
                    d="M2 2h4v12H2z"
                    fill="currentColor"
                    fillOpacity={
                      (appMode === 'map'
                        ? leftWidth > 0
                        : appMode === 'document'
                          ? showDocumentSidebar
                          : showArtifactsSidebar)
                        ? 0.3
                        : 0
                    }
                  />
                </svg>
              </button>
            )}
            <button
              className={`sidebar-toggle-btn ${rightWidth > 0 ? 'active' : ''}`}
              title={rightWidth > 0 ? "Hide Right Sidebar" : "Show Right Sidebar"}
              onClick={toggleRight}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="2" y="2" width="12" height="12" rx="1.5" />
                <line x1="10" y1="2" x2="10" y2="14" />
                <path d="M10 2h4v12h-4z" fill="currentColor" fillOpacity={rightWidth > 0 ? 0.3 : 0} />
              </svg>
            </button>
            <button
              className="sidebar-toggle-btn"
              title="System Diagnostics & API Keys"
              onClick={() => setShowDiagnostics(true)}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 16v-4" />
                <path d="M12 8h.01" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      <div className="layout">
        {/* Left panel — map mode only */}
        {appMode !== 'map' || leftWidth === 0 ? null : (
          <aside ref={leftPanelRef} className="panel left-panel" style={{ width: leftWidth }}>
            <div className="tab-bar tab-bar-scroll">
              <button
                className={`tab ${activeLeftTab === 'files' ? 'active' : ''}`}
                onClick={() => setActiveLeftTab('files')}
              >
                Files
              </button>
              <button
                className={`tab ${activeLeftTab === 'layers' ? 'active' : ''}`}
                onClick={() => setActiveLeftTab('layers')}
              >
                Layers
                {displayLayersCount > 0 && <span className="tab-badge">{displayLayersCount}</span>}
              </button>

              <button
                className={`tab ${activeLeftTab === 'bookmarks' ? 'active' : ''}`}
                onClick={() => setActiveLeftTab('bookmarks')}
              >
                Marks
                {bookmarks.length > 0 && <span className="tab-badge">{bookmarks.length}</span>}
              </button>
              <button
                className={`tab ${activeLeftTab === 'export' ? 'active' : ''}`}
                onClick={() => setActiveLeftTab('export')}
              >
                Export
              </button>
              <button
                className={`tab ${activeLeftTab === 'zoning' ? 'active' : ''}`}
                onClick={() => setActiveLeftTab('zoning')}
              >
                Zones
              </button>
              <button
                className={`tab ${activeLeftTab === 'scenarios' ? 'active' : ''}`}
                onClick={() => setActiveLeftTab('scenarios')}
              >
                Scenarios
                {scenarios.length > 0 && <span className="tab-badge">{scenarios.length}</span>}
              </button>
            </div>
            {activeLeftTab === 'files' && (
              <>
                {convertingFile && (
                  <div className="import-status">Importing {convertingFile}…</div>
                )}
                {convertError && (
                  <div className="import-status import-error" onClick={() => setConvertError(null)}>
                    {convertError}
                  </div>
                )}
                <FileTree
                  workspacePath={workspacePath}
                  onFileClick={handleFileClick}
                  onImportClick={handleImportSpatialFiles}
                  revision={fileTreeRevision}
                />
              </>
            )}
            {activeLeftTab === 'layers' && (
              <>
                <LayerPanel
                  layers={layers}
                  selectedLayerIds={selectedLayerIds}
                  onSelectedLayerIdsChange={setSelectedLayerIds}
                  selectedFeatures={selectedFeatures}
                  onSelectFeature={handleSelectFeature}
                  onToggle={toggleLayer}
                  onRemove={removeLayer}
                  onZoomTo={zoomToLayer}
                  onStyle={(id) => {
                    // Raster layers (WMS/GEE) have no vector symbology — block the panel unless it's a raster overlay.
                    const layer = layers.find((l) => l.id === id)
                    if ((layer?.wmsSpec || layer?.geeSpec) && !layer?.rasterOverlaySpec) return
                    setStylingLayerId((cur) => (cur === id ? null : id))
                    setAttrLayerId(null)
                  }}
                  activeStyleId={stylingLayerId}
                  onAttributes={(id) => { setAttrLayerId((cur) => (cur === id ? null : id)); setStylingLayerId(null) }}
                  activeAttrId={attrLayerId}
                  onRename={renameLayer}
                  onGroupWith={groupLayers}
                  onGroupMulti={groupLayersMulti}
                  onUngroup={ungroupLayer}
                  onUngroupGroup={ungroupGroup}
                  onToggleGroup={toggleLayerGroup}
                  onRenameGroup={renameGroup}
                  onStyleChange={handleSymbologyChange}
                  onUpdateLayer={(layerId, updates) => {
                    setLayers((prev) => prev.map((l) => (l.id === layerId ? { ...l, ...updates } : l)))
                  }}
                  onAttributesChange={handleAttributesChange}
                  onReorderLayers={setLayers}
                  onMoveLayerOrGroup={moveLayerOrGroup}
                />
              </>
            )}

            {activeLeftTab === 'bookmarks' && (
              <BookmarkPanel
                bookmarks={bookmarks}
                onGoTo={handleBookmarkGoTo}
                onRemove={(id) => setBookmarks((prev) => prev.filter((b) => b.id !== id))}
                onSaveCurrent={handleBookmarkSaveCurrent}
              />
            )}
            {activeLeftTab === 'export' && (
              <ExportPanel
                layers={layers}
                workspacePath={workspacePath}
                onExportMapPng={handleExportMapPng}
                onExportLayer={handleExportLayerFile}
                onExportPdf={handleExportPdf}
                onExportClippedRegion={(name) => void clipLayersToBboxAndSave(name)}
                onPreviewBoundary={handlePreviewBoundary}
                onSaveByRegion={handleSaveByRegion}
                onSavePngToArtifact={handleSavePngToArtifact}
                onSavePdfToArtifact={handleSavePdfToArtifact}
                onSuggestExportTitle={suggestExportTitle}
              />
            )}
            {activeLeftTab === 'zoning' && <ZoningPanel />}
            {activeLeftTab === 'scenarios' && (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                {/* AI Scenario Builder — top section */}
                <div style={{ flex: '0 0 auto', maxHeight: '55%', overflowY: 'auto', borderBottom: '2px solid var(--border)' }}>
                  <ScenarioBuilderPanel
                    mapBounds={mapBounds}
                    onOpenArtifacts={() => setAppMode('artifacts')}
                    workspacePath={workspacePath}
                  />
                </div>
                {/* Manual scenario manager — bottom section */}
                <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
                  <ScenarioPanel
                    scenarios={scenarios}
                    activeScenarioId={activeScenarioId}
                    layers={layers}
                    onCreateScenario={(name, description) => {
                      const id = `scenario-${genId()}`
                      setScenarios(prev => [...prev, {
                        id, name, description,
                        createdAt: Date.now(),
                        layerIds: layers.map(l => l.id),
                        layerVisibility: Object.fromEntries(layers.map(l => [l.id, l.visible]))
                      }])
                    }}
                    onActivate={(id) => {
                      setActiveScenarioId(id)
                      if (!id) {
                        setLayers(prev => prev.map(l => ({ ...l, visible: true })))
                      } else {
                        const scenario = scenarios.find(s => s.id === id)
                        if (scenario) {
                          setLayers(prev => prev.map(l => ({
                            ...l,
                            visible: scenario.layerIds.includes(l.id)
                              ? (scenario.layerVisibility[l.id] ?? true)
                              : false
                          })))
                        }
                      }
                    }}
                    onDelete={(id) => {
                      setScenarios(prev => prev.filter(s => s.id !== id))
                      if (activeScenarioId === id) setActiveScenarioId(null)
                    }}
                    onRename={(id, name) => setScenarios(prev =>
                      prev.map(s => s.id === id ? { ...s, name } : s)
                    )}
                    onAddLayer={(scenarioId, layerId) => setScenarios(prev =>
                      prev.map(s => s.id === scenarioId
                        ? { ...s, layerIds: s.layerIds.includes(layerId) ? s.layerIds : [...s.layerIds, layerId] }
                        : s
                      )
                    )}
                    onRemoveLayer={(scenarioId, layerId) => setScenarios(prev =>
                      prev.map(s => s.id === scenarioId
                        ? { ...s, layerIds: s.layerIds.filter(id => id !== layerId) }
                        : s
                      )
                    )}
                  />
                </div>
              </div>
            )}
          </aside>
        )}

        {/* Left resize handle — map mode only */}
        {appMode === 'map' && leftWidth > 0 && <div className="resize-handle" onMouseDown={onResizeStart('left')} />}

        {/* Center */}
        <main className="center-panel">
          <div
            className={`map-stack ${streetViewActive && streetViewLayout === 'full' ? 'is-full-sv' : ''}`}
            style={{
              display: appMode === 'map' ? 'flex' : 'none',
              flexDirection: 'column',
            }}
          >
            {!workspacePath && (
              <div className="workspace-hint-banner">
                Open a workspace folder (title bar) to save the map and export. Layers from chat still
                appear, but they will not persist until a folder is open.
              </div>
            )}

            {streetViewActive && (
              <div
                style={{
                  height: streetViewLayout === 'split' ? `${splitHeight}px` : '100%',
                  width: '100%',
                  display: 'flex',
                  minHeight: 0,
                }}
              >
                <ErrorBoundary label="Street View Workspace">
                  <StreetViewWorkspace
                    target={streetViewTarget}
                    roadTarget={roadInspectionTarget}
                    onArtifactsChanged={() => setArtifactsRevision((n) => n + 1)}
                    onClose={() => {
                      setStreetViewTarget(null)
                      setRoadInspectionTarget(null)
                      setStreetViewActive(false)
                      setStreetViewLocation(null)
                    }}
                    layout={streetViewLayout}
                    onLayoutChange={setStreetViewLayout}
                    onYawChange={setStreetViewBearing}
                    onLocationChange={setStreetViewLocation}
                    workspacePath={workspacePath}
                  />
                </ErrorBoundary>
              </div>
            )}

            {streetViewActive && streetViewLayout === 'split' && (
              <div
                className="split-resize-handle-horiz"
                onMouseDown={handleSplitDragStart}
              />
            )}

            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                minHeight: 0,
                position: streetViewActive && streetViewLayout === 'full' ? 'absolute' : 'relative',
              }}
              className={streetViewActive && streetViewLayout === 'full' ? 'mini-map-floating' : ''}
            >
              <ErrorBoundary label="Map">
                <MapView
                  ref={mapViewRef}
                  layers={layers}
                  selectedLayerIds={selectedLayerIds}
                  selectedFeatures={selectedFeatures}
                  onSelectFeature={handleSelectFeature}
                  basemap={basemap}
                  initialState={mapViewState}
                  mapActions={mapActions}
                  onMapMove={setMapViewState}
                  onBoundsChange={setMapBounds}
                  onBasemapChange={setBasemap}
                  onActionsProcessed={() => setMapActions([])}
                  onLayerStyleChange={handleLayerStyleChange}
                  onAddMarker={handleRightClickAddMarker}
                  onOpenStreetView={handleRightClickStreetView}
                  onInspectRoad={handleInspectRoad}
                  onAskChat={handleRightClickAskChat}
                  onContextualQuery={handleContextualQuery}
                  onDrawComplete={handleDrawComplete}
                  streetViewDetail={streetViewDetail}
                  onStreetViewDetailChange={handleStreetViewDetailChange}
                  streetViewActive={streetViewActive}
                  streetViewLocation={streetViewLocation}
                  streetViewBearing={streetViewBearing}
                  isMiniMap={streetViewActive && streetViewLayout === 'full'}
                  onStreetViewLayoutChange={setStreetViewLayout}
                  onUndo={handleGlobalUndo}
                  onRedo={handleGlobalRedo}
                  canUndo={pastHistory.length > 0}
                  canRedo={futureHistory.length > 0}
                />
              </ErrorBoundary>
            </div>
            <Legend layers={layers} />
          </div>

          <div style={{ display: appMode === 'document' ? 'flex' : 'none', flex: 1, flexDirection: 'column', height: '100%', minHeight: 0 }}>
            <ErrorBoundary label="Document">
              <DocumentView
                openDocs={openDocs}
                setOpenDocs={setOpenDocs}
                activeDocId={activeDocId}
                setActiveDocId={setActiveDocId}
                onImageChange={setDocumentImage}
                showSidebar={showDocumentSidebar}
                sidebarWidth={leftWidth}
                onLeftResizeStart={onResizeStart('left')}
                workspacePath={workspacePath}
              />
            </ErrorBoundary>
          </div>

          <div style={{ display: appMode === 'artifacts' ? 'flex' : 'none', flex: 1, flexDirection: 'column', height: '100%', minHeight: 0 }}>
            <ErrorBoundary label="Artifacts">
              <ArtifactsPanel
                workspacePath={workspacePath ?? undefined}
                revision={artifactsRevision}
                showSidebar={showArtifactsSidebar}
                sidebarWidth={leftWidth}
                onLeftResizeStart={onResizeStart('left')}
                onAddToMap={(geojson, name) => {
                  setMapActions((prev) => [
                    ...prev,
                    { type: 'add_geojson', payload: { geojson: geojson as FeatureCollection, name } },
                  ])
                  setAppMode('map') // Auto-switch to map view
                }}
              />
            </ErrorBoundary>
          </div>
        </main>

        {/* Right resize handle */}
        {rightWidth > 0 && <div className="resize-handle" onMouseDown={onResizeStart('right')} />}

        {/* Right panel */}
        {rightWidth > 0 && (
          <aside className="panel right-panel" style={{ width: rightWidth }}>
            <ErrorBoundary label="Chat">
              <ChatPanel
                ref={chatPanelRef}
                conversations={conversations}
                activeConversation={activeConversation}
                onCreateConversation={handleCreateConversation}
                onSelectConversation={handleSelectConversation}
                onDeleteConversation={handleDeleteConversation}
                onMessagesChange={handleConversationMessagesChange}
                onRenameConversation={handleRenameConversation}
                mapContext={mapContext}
                onMapAction={handleMapAction}
                documentImage={appMode === 'document' ? documentImage : null}
                injectedMessage={injectedMessage}
                onComposeMapFigure={composeMapFigure}
              />
            </ErrorBoundary>
          </aside>
        )}
      </div>
      {isTransitioning && (
        <div className="workspace-transition-overlay">
          <div className="workspace-transition-card">
            <p className="workspace-transition-name">{workspacePath?.split('/').pop()}</p>
            <div className="workspace-transition-spinner" />
            <p className="workspace-transition-status">{transitionStatus}</p>
          </div>
        </div>
      )}
      {showDiagnostics && (
        <DiagnosticsPanel
          onClose={() => setShowDiagnostics(false)}
          workspacePath={workspacePath}
        />
      )}
    </div>
  )
}

export default App
