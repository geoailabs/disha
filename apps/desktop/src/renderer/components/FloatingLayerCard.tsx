import React, { useState, useRef, useEffect } from 'react'
import {
  GeoJSONLayer,
  MapBookmark,
  BoundaryGeometry,
  SelectedFeatureEntry,
  ScenarioDraft,
} from '../types'
import { Scenario } from './ScenarioPanel'
import BookmarkPanel from './BookmarkPanel'
import ScenarioPanel from './ScenarioPanel'
import ScenarioBuilderPanel from './ScenarioBuilderPanel'
import ExportPanel from './ExportPanel'
import FileTree from './FileTree'
import './FloatingLayerCard.css'
import * as turf from '@turf/turf'
import layersIcon from '../assets/icons/layers_icons.png'
import filesIcon from '../assets/icons/files_icon.png'
import scenariosIcon from '../assets/icons/scenarios_icon.png'
import exportIcon from '../assets/icons/export_icon.png'

const calculateLayerArea = (layer: GeoJSONLayer): string | null => {
  try {
    const features = layer.data?.features
    if (!features || features.length === 0) return null
    let totalAreaSqM = 0
    let hasPolygons = false
    for (const f of features) {
      const gType = f.geometry?.type
      if (gType === 'Polygon' || gType === 'MultiPolygon') {
        hasPolygons = true
        totalAreaSqM += turf.area(f)
      }
    }
    if (!hasPolygons || totalAreaSqM <= 0) return null
    if (totalAreaSqM >= 1_000_000) {
      const sqKm = totalAreaSqM / 1_000_000
      return `${sqKm >= 100 ? sqKm.toFixed(1) : sqKm.toFixed(2)} km²`
    } else if (totalAreaSqM >= 10_000) {
      const ha = totalAreaSqM / 10_000
      return `${ha.toFixed(2)} ha`
    } else {
      return `${Math.round(totalAreaSqM).toLocaleString()} m²`
    }
  } catch {
    return null
  }
}

export type FloatingTab = 'layers' | 'files' | 'bookmarks' | 'scenarios' | 'export'

interface FloatingLayerCardProps {
  layers: GeoJSONLayer[]
  selectedLayerIds: string[]
  activeTab?: FloatingTab
  onTabChange?: (tab: FloatingTab) => void
  isOpen?: boolean
  onClose?: () => void
  onSelectFeature?: (feature: any, layer: GeoJSONLayer) => void
  onHoverFeature?: (entry: SelectedFeatureEntry | null) => void
  onToggleLayer: (id: string) => void
  onRemoveLayer: (id: string) => void
  onZoomToLayer: (id: string) => void
  onStyleLayer: (id: string) => void
  onAttributesLayer: (id: string) => void
  onRenameLayer: (id: string, newName: string) => void
  onReorderLayers?: (layers: GeoJSONLayer[]) => void
  onExportLayerFile?: (layerId: string, format: string) => void

  // Bookmarks
  bookmarks: MapBookmark[]
  onGoToBookmark: (bm: MapBookmark) => void
  onRemoveBookmark: (id: string) => void
  onSaveCurrentBookmark: () => void

  // Scenarios
  scenarios: Scenario[]
  activeScenarioId: string | null
  onActivateScenario: (id: string | null) => void
  onCreateScenario: (name: string, description: string) => void
  onDeleteScenario: (id: string) => void
  onRenameScenario: (id: string, name: string) => void
  onAddLayerToScenario: (scenarioId: string, layerId: string) => void
  onRemoveLayerFromScenario: (scenarioId: string, layerId: string) => void
  mapBounds?: { south: number; west: number; north: number; east: number } | null
  onOpenArtifacts?: () => void
  scenarioDraft?: ScenarioDraft | null
  onScenarioDraftClear?: () => void
  onScenariosCreated?: (scenarios: Array<{ name: string; description?: string }>) => void

  // Export
  workspacePath?: string | null
  onOpenWorkspace?: () => void
  onCloseWorkspace?: () => void
  onExportMapPng?: () => void
  onExportMapJpeg?: () => void
  onExportPdf?: () => void
  onExportClippedRegion?: (name: string) => void
  onPreviewBoundary?: (geom: BoundaryGeometry | null) => void
  onSaveByRegion?: (name: string, geom: BoundaryGeometry) => void
  onSavePngToArtifact?: (title: string) => void
  onSaveJpgToArtifact?: (title: string) => void
  onSavePdfToArtifact?: (title: string) => void
  onSuggestExportTitle?: () => string

  // File Tree
  onFileClick?: (path: string) => void
  onImportSpatialFiles?: () => void
  fileTreeRevision?: number

  // Status & Navigation
  projectName?: string
  onRenameProject?: (title: string) => void
  isConnected?: boolean
  canUndoZoom?: boolean
  canRedoZoom?: boolean
  onUndoZoom?: () => void
  onRedoZoom?: () => void
}

export const FloatingLayerCard: React.FC<FloatingLayerCardProps> = ({
  layers,
  selectedLayerIds,
  activeTab: activeTabProp,
  onTabChange: onTabChangeProp,
  isOpen = true,
  onClose,
  onHoverFeature,
  onToggleLayer,
  onRemoveLayer,
  onZoomToLayer,
  onStyleLayer,
  onAttributesLayer,
  onRenameLayer,
  onExportLayerFile,
  bookmarks,
  onGoToBookmark,
  onRemoveBookmark,
  onSaveCurrentBookmark,
  scenarios,
  activeScenarioId,
  onActivateScenario,
  onCreateScenario,
  onDeleteScenario,
  onRenameScenario,
  onAddLayerToScenario,
  onRemoveLayerFromScenario,
  mapBounds,
  onOpenArtifacts,
  scenarioDraft,
  onScenarioDraftClear,
  onScenariosCreated,
  workspacePath,
  onOpenWorkspace,
  onCloseWorkspace,
  onExportMapPng,
  onExportMapJpeg,
  onExportPdf,
  onExportClippedRegion,
  onPreviewBoundary,
  onSaveByRegion,
  onSavePngToArtifact,
  onSaveJpgToArtifact,
  onSavePdfToArtifact,
  onSuggestExportTitle,
  onFileClick,
  onImportSpatialFiles,
  fileTreeRevision = 0,
  projectName = 'Disha Map',
  onRenameProject,
  isConnected = true,
  canUndoZoom = false,
  canRedoZoom = false,
  onUndoZoom,
  onRedoZoom,
}) => {
  const [internalTab, setInternalTab] = useState<FloatingTab>('layers')
  const activeTab = activeTabProp ?? internalTab
  const setActiveTab = (tab: FloatingTab) => {
    setInternalTab(tab)
    onTabChangeProp?.(tab)
  }
  const [contextMenu, setContextMenu] = useState<{
    layerId: string
    x: number
    y: number
  } | null>(null)
  const [isWorkspaceMenuOpen, setIsWorkspaceMenuOpen] = useState(false)
  const [hoveredLayerTooltip, setHoveredLayerTooltip] = useState<{
    name: string
    area: string | null
    x: number
    y: number
  } | null>(null)
  const workspaceMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (workspaceMenuRef.current && !workspaceMenuRef.current.contains(e.target as Node)) {
        setIsWorkspaceMenuOpen(false)
      }
      setContextMenu(null)
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setContextMenu(null)
      }
    }
    document.addEventListener('click', handleClickOutside)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('click', handleClickOutside)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  const handleContextMenu = (e: React.MouseEvent, layerId: string) => {
    e.preventDefault()
    e.stopPropagation()
    if (onHoverFeature) {
      onHoverFeature(layerId)
    }
    setContextMenu({
      layerId,
      x: e.clientX,
      y: e.clientY,
    })
  }

  if (isOpen === false) return null

  const categoryMeta: Record<string, { label: string; icon: string; count?: number }> = {
    layers: { label: 'Layers', icon: layersIcon, count: layers.length },
    files: { label: 'Workspace Files', icon: filesIcon },
    scenarios: { label: 'Scenarios', icon: scenariosIcon, count: scenarios.length },
    export: { label: 'Export Map', icon: exportIcon },
    bookmarks: { label: 'Bookmarks', icon: layersIcon, count: bookmarks.length },
  }

  return (
    <div className="floating-layer-card left-category-pane">
      {/* Dedicated Floating Category Pane Header */}
      <div className="flc-header">
        <div className="flc-category-title-group">
          <span
            className="flc-category-icon"
            style={{
              WebkitMaskImage: `url("${categoryMeta[activeTab]?.icon || layersIcon}")`,
              maskImage: `url("${categoryMeta[activeTab]?.icon || layersIcon}")`,
            }}
          />
          <h2 className="flc-category-heading">{categoryMeta[activeTab]?.label || 'Layers'}</h2>
          {categoryMeta[activeTab]?.count !== undefined && (
            <span className="flc-header-badge">{categoryMeta[activeTab].count}</span>
          )}
        </div>

        <div className="flc-header-actions">
          {activeTab === 'layers' && bookmarks.length > 0 && (
            <button
              type="button"
              className="flc-header-action-btn"
              onClick={() => setActiveTab('bookmarks')}
              title="View bookmarks"
            >
              <span>Marks</span>
              <span className="flc-tab-badge" style={{ marginLeft: 4 }}>{bookmarks.length}</span>
            </button>
          )}

          {activeTab === 'bookmarks' && (
            <button
              type="button"
              className="flc-header-action-btn"
              onClick={() => setActiveTab('layers')}
              title="Back to layers"
            >
              <span>Layers</span>
            </button>
          )}

          {onClose && (
            <button
              type="button"
              className="flc-icon-btn flc-close-btn"
              onClick={onClose}
              title="Close pane"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Card Content Area */}
          <div className="flc-content">
            {activeTab === 'layers' && (
              <div className="flc-layers-list">
                {layers.length === 0 ? (
                  <div className="flc-empty-state">
                    <p className="flc-empty-title">No spatial layers</p>
                    <p className="flc-empty-hint">Drop GeoJSON or Shapefiles, or click <strong>+ Data</strong></p>
                  </div>
                ) : (
                  layers.map((layer) => {
                    const isVisible = layer.visible !== false
                    const featureCount = layer.data?.features?.length ?? 0
                    const isRaster = Boolean(layer.wmsSpec || layer.geeSpec || layer.rasterOverlaySpec)
                    const countBadge = isRaster ? 'Raster' : `${featureCount}`
                    const swatchColor = layer.color || '#00b4d8'

                    return (
                      <div
                        key={layer.id}
                        className={`flc-layer-item ${selectedLayerIds.includes(layer.id) ? 'is-selected' : ''}`}
                        onClick={() => onHoverFeature && onHoverFeature(layer.id)}
                        onContextMenu={(e) => handleContextMenu(e, layer.id)}
                        onMouseEnter={(e) => {
                          const area = calculateLayerArea(layer)
                          setHoveredLayerTooltip({
                            name: layer.name,
                            area,
                            x: e.clientX,
                            y: e.clientY,
                          })
                        }}
                        onMouseMove={(e) => {
                          setHoveredLayerTooltip((prev) =>
                            prev ? { ...prev, x: e.clientX, y: e.clientY } : null
                          )
                        }}
                        onMouseLeave={() => {
                          setHoveredLayerTooltip(null)
                        }}
                      >
                        {/* Drag Handle */}
                        <span className="flc-drag-handle" title="Drag to reorder">
                          <svg width="8" height="14" viewBox="0 0 8 14" fill="currentColor">
                            <circle cx="2" cy="2" r="1.5" />
                            <circle cx="6" cy="2" r="1.5" />
                            <circle cx="2" cy="7" r="1.5" />
                            <circle cx="6" cy="7" r="1.5" />
                            <circle cx="2" cy="12" r="1.5" />
                            <circle cx="6" cy="12" r="1.5" />
                          </svg>
                        </span>

                        {/* Visibility Eye Toggle */}
                        <button
                          className={`flc-eye-btn ${!isVisible ? 'is-off' : ''}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            onToggleLayer(layer.id)
                          }}
                          title={isVisible ? 'Hide layer' : 'Show layer'}
                        >
                          {isVisible ? (
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                              <circle cx="12" cy="12" r="3" />
                            </svg>
                          ) : (
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                              <line x1="1" y1="1" x2="23" y2="23" />
                            </svg>
                          )}
                        </button>

                        {/* Legend Color Swatch */}
                        <span
                          className="flc-layer-swatch"
                          style={{ backgroundColor: swatchColor }}
                          title={`Layer color: ${swatchColor}`}
                        />

                        {/* Layer Name */}
                        <div className="flc-layer-name-wrap" title={layer.name}>
                          <span className={`flc-layer-name ${!isVisible ? 'is-hidden' : ''}`}>
                            {layer.name}
                          </span>
                        </div>

                        {/* Feature Count / Type */}
                        <span className="flc-layer-badge">{countBadge}</span>
                      </div>
                    )
                  })
                )}
              </div>
            )}

            {activeTab === 'files' && (
              <div className="flc-tab-view">
                <FileTree
                  workspacePath={workspacePath}
                  onFileClick={onFileClick || (() => {})}
                  onImportClick={onImportSpatialFiles}
                  revision={fileTreeRevision}
                />
              </div>
            )}

            {activeTab === 'bookmarks' && (
              <div className="flc-tab-view">
                <BookmarkPanel
                  bookmarks={bookmarks}
                  onGoTo={onGoToBookmark}
                  onRemove={onRemoveBookmark}
                  onSaveCurrent={onSaveCurrentBookmark}
                />
              </div>
            )}


            {activeTab === 'scenarios' && (
              <div className="flc-tab-view flc-scenarios-tab">
                <div className="flc-scenario-section flc-scenario-builder-section">
                  <ScenarioBuilderPanel
                    mapBounds={mapBounds}
                    onOpenArtifacts={onOpenArtifacts}
                    workspacePath={workspacePath}
                    scenarioDraft={scenarioDraft}
                    onScenarioDraftClear={onScenarioDraftClear}
                    onScenariosCreated={onScenariosCreated}
                  />
                </div>
                <div className="flc-scenario-section flc-scenario-list-section">
                  <ScenarioPanel
                    scenarios={scenarios}
                    activeScenarioId={activeScenarioId}
                    layers={layers}
                    onCreateScenario={onCreateScenario}
                    onActivate={onActivateScenario}
                    onDelete={onDeleteScenario}
                    onRename={onRenameScenario}
                    onAddLayer={onAddLayerToScenario}
                    onRemoveLayer={onRemoveLayerFromScenario}
                  />
                </div>
              </div>
            )}

            {activeTab === 'export' && (
              <div className="flc-tab-view">
                <ExportPanel
                  layers={layers}
                  workspacePath={workspacePath}
                  onExportMapPng={onExportMapPng}
                  onExportMapJpeg={onExportMapJpeg}
                  onExportLayer={onExportLayerFile || (() => {})}
                  onExportPdf={onExportPdf}
                  onExportClippedRegion={onExportClippedRegion}
                  onPreviewBoundary={onPreviewBoundary}
                  onSaveByRegion={onSaveByRegion}
                  onSavePngToArtifact={onSavePngToArtifact}
                  onSaveJpgToArtifact={onSaveJpgToArtifact}
                  onSavePdfToArtifact={onSavePdfToArtifact}
                  onSuggestExportTitle={onSuggestExportTitle}
                />
              </div>
            )}
          </div>

      {hoveredLayerTooltip && (
        <div
          className="flc-cursor-tooltip"
          style={{
            left: Math.min(window.innerWidth - 180, hoveredLayerTooltip.x + 14),
            top: Math.min(window.innerHeight - 45, hoveredLayerTooltip.y + 12),
          }}
        >
          <span className="flc-tooltip-name">{hoveredLayerTooltip.name}</span>
          {hoveredLayerTooltip.area && (
            <span className="flc-tooltip-area">{hoveredLayerTooltip.area}</span>
          )}
        </div>
      )}

      {/* Floating Context Menu on Right Click */}
      {contextMenu && (() => {
        const menuLayer = layers.find((l) => l.id === contextMenu.layerId)
        if (!menuLayer) return null
        const isRaster = Boolean(menuLayer.type === 'raster' || (menuLayer as any).isRaster || menuLayer.wmsSpec || menuLayer.geeSpec || menuLayer.rasterOverlaySpec)

        const menuWidth = 190
        const menuHeight = 220
        const posX = Math.max(10, Math.min(contextMenu.x, window.innerWidth - menuWidth - 10))
        const posY = Math.max(10, Math.min(contextMenu.y, window.innerHeight - menuHeight - 10))

        return (
          <div
            className="flc-floating-context-menu"
            style={{ top: posY, left: posX }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flc-context-header">
              <span className="flc-context-layer-name" title={menuLayer.name}>{menuLayer.name}</span>
            </div>
            <button
              className="flc-dropdown-item"
              onClick={() => {
                onZoomToLayer(menuLayer.id)
                setContextMenu(null)
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
                <line x1="11" y1="8" x2="11" y2="14" />
                <line x1="8" y1="11" x2="14" y2="11" />
              </svg>
              <span>Zoom to Layer</span>
            </button>
            {!isRaster && (
              <button
                className="flc-dropdown-item"
                onClick={() => {
                  onAttributesLayer(menuLayer.id)
                  setContextMenu(null)
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                </svg>
                <span>View Attributes</span>
              </button>
            )}
            <button
              className="flc-dropdown-item"
              onClick={() => {
                onStyleLayer(menuLayer.id)
                setContextMenu(null)
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />
                <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
                <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />
                <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
                <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
              </svg>
              <span>Symbology & Style</span>
            </button>
            {onExportLayerFile && !isRaster && (
              <button
                className="flc-dropdown-item"
                onClick={() => {
                  onExportLayerFile(menuLayer.id, 'geojson')
                  setContextMenu(null)
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                <span>Export GeoJSON</span>
              </button>
            )}
            <div className="flc-dropdown-divider" />
            <button
              className="flc-dropdown-item item-danger"
              onClick={() => {
                onRemoveLayer(menuLayer.id)
                setContextMenu(null)
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
              <span>Delete Layer</span>
            </button>
          </div>
        )
      })()}
    </div>
  )
}
