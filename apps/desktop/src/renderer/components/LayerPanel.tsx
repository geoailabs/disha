import { useEffect, useMemo, useState, useRef } from 'react'
import type { Feature } from 'geojson'
import { GeoJSONLayer, LayerStyleSpec, SelectedFeatureEntry } from '../types'
import SymbologyPanel from './SymbologyPanel'
import AttributeTable from './AttributeTable'
import ErrorBoundary from './ErrorBoundary'
import './LayerPanel.css'

interface LayerPanelProps {
  layers: GeoJSONLayer[]
  selectedLayerIds: Set<string>
  onSelectedLayerIdsChange: React.Dispatch<React.SetStateAction<Set<string>>>
  selectedFeatures?: SelectedFeatureEntry[]
  onSelectFeature?: (entry: SelectedFeatureEntry | null, shiftKey: boolean) => void
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onZoomTo: (id: string) => void
  onStyle?: (id: string) => void
  activeStyleId?: string | null
  onAttributes?: (id: string) => void
  activeAttrId?: string | null
  onRename?: (id: string, name: string) => void
  onGroupWith?: (sourceId: string, targetId: string) => void
  onGroupMulti?: (ids: string[], customGroupName?: string) => void
  onUngroup?: (id: string) => void
  onUngroupGroup?: (groupId: string) => void
  onToggleGroup?: (groupId: string, visible: boolean) => void
  onRenameGroup?: (groupId: string, name: string) => void
  // Props to drive the popups inside LayerPanel
  onStyleChange?: (layerId: string, styleSpec: LayerStyleSpec) => void
  onUpdateLayer?: (layerId: string, updates: Partial<GeoJSONLayer>) => void
  onAttributesChange?: (layerId: string, data: any) => void
  onReorderLayers?: (layers: GeoJSONLayer[]) => void
  onMoveLayerOrGroup?: (sourceId: string, targetId: string, position: 'before' | 'after' | 'inside') => void
}

export interface TreeGroupNode {
  type: 'group'
  id: string
  name: string
  depth: number
  children: TreeNode[]
}

export interface TreeLayerNode {
  type: 'layer'
  id: string
  depth: number
  layer: GeoJSONLayer
}

export type TreeNode = TreeGroupNode | TreeLayerNode

export default function LayerPanel({
  layers,
  selectedLayerIds,
  onSelectedLayerIdsChange,
  selectedFeatures,
  onSelectFeature,
  onToggle,
  onRemove,
  onZoomTo,
  onStyle,
  activeStyleId,
  onAttributes,
  activeAttrId,
  onRename,
  onGroupWith,
  onGroupMulti,
  onUngroup,
  onUngroupGroup,
  onToggleGroup,
  onRenameGroup,
  onStyleChange,
  onUpdateLayer,
  onAttributesChange,
  onReorderLayers,
  onMoveLayerOrGroup,
}: LayerPanelProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  const [menu, setMenu] = useState<{ id: string; type: 'layer' | 'group'; x: number; y: number; selectedIds: Set<string> } | null>(null)
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  // drag-and-drop state
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [draggedType, setDraggedType] = useState<'layer' | 'group' | null>(null)
  const [dragOverId, setDragOverId] = useState<string | null>(null)
  const [dropPosition, setDropPosition] = useState<'before' | 'after' | 'inside' | null>(null)

  // Clear selection when clicking anywhere outside the panel
  useEffect(() => {
    const handleOutsideMouseDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onSelectedLayerIdsChange(new Set())
      }
    }
    document.addEventListener('mousedown', handleOutsideMouseDown)
    return () => document.removeEventListener('mousedown', handleOutsideMouseDown)
  }, [onSelectedLayerIdsChange])

  // Clear style popup when clicking outside the swatch or the popup itself
  useEffect(() => {
    if (!activeStyleId) return
    const handleOutsideClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (
        !target.closest('.layer-color.active') &&
        !target.closest('.layer-popup-container')
      ) {
        onStyle?.(null)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [activeStyleId, onStyle])

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('keydown', close)
    }
  }, [menu])

  // Helper functions for recursively resolving group layers
  const getGroupLayersRecursively = (node: TreeGroupNode): GeoJSONLayer[] => {
    const result: GeoJSONLayer[] = []
    const traverse = (n: TreeNode) => {
      if (n.type === 'layer') {
        result.push(n.layer)
      } else {
        n.children.forEach(traverse)
      }
    }
    node.children.forEach(traverse)
    return result
  }

  const getGroupPathKey = (node: TreeGroupNode): string => {
    const sample = layers.find((l) => l.groupPathIds?.includes(node.id) || l.groupId === node.id)
    if (sample) {
      const ids = sample.groupPathIds || (sample.groupId ? [sample.groupId] : [])
      const idx = ids.indexOf(node.id)
      if (idx !== -1) {
        return ids.slice(0, idx + 1).join('/')
      }
    }
    return node.id
  }

  const onToggleGroupPath = (node: TreeGroupNode, visible: boolean) => {
    const childLayers = getGroupLayersRecursively(node)
    childLayers.forEach((l) => {
      if (l.visible !== visible) {
        onToggle(l.id)
      }
    })
  }

  const onRenameGroupPath = (node: TreeGroupNode, name: string) => {
    if (name.trim()) {
      onRenameGroup?.(node.id, name.trim())
    }
  }

  // Build the tree dynamically from layers
  const tree = useMemo(() => {
    const root: TreeNode[] = []
    layers.forEach((layer) => {
      let ids: string[] = []
      let names: string[] = []
      
      if (layer.groupPathIds && layer.groupPathIds.length > 0) {
        ids = layer.groupPathIds
        names = layer.groupPathNames || layer.groupPathIds.map(() => 'Group')
      } else if (layer.groupId) {
        ids = [layer.groupId]
        names = [layer.groupName || 'Group']
      }
      
      if (ids.length === 0) {
        root.push({
          type: 'layer',
          id: layer.id,
          depth: 0,
          layer,
        })
        return
      }
      
      let currentChildren = root
      for (let i = 0; i < ids.length; i++) {
        const gId = ids[i]
        const gName = names[i] || 'Group'
        
        let groupNode = currentChildren.find((node) => node.type === 'group' && node.id === gId) as TreeGroupNode
        if (!groupNode) {
          groupNode = {
            type: 'group',
            id: gId,
            name: gName,
            depth: i,
            children: [],
          }
          currentChildren.push(groupNode)
        }
        currentChildren = groupNode.children
      }
      
      currentChildren.push({
        type: 'layer',
        id: layer.id,
        depth: ids.length,
        layer,
      })
    })
    return root
  }, [layers])

  const menuLayer = useMemo(
    () => (menu && menu.type === 'layer' ? layers.find((l) => l.id === menu.id) : null),
    [menu, layers],
  )

  const menuGroupNode = useMemo(() => {
    if (!menu || menu.type !== 'group') return null
    let found: TreeGroupNode | null = null
    const traverse = (node: TreeNode) => {
      if (node.type === 'group') {
        if (node.id === menu.id) {
          found = node
        } else {
          node.children.forEach(traverse)
        }
      }
    }
    tree.forEach(traverse)
    return found
  }, [menu, tree])

  // Context menu group targets
  const groupTargets = useMemo(() => {
    if (!menuLayer) return []
    const pathsMap = new Map<string, string>()
    layers.forEach((l) => {
      const ids = l.groupPathIds || (l.groupId ? [l.groupId] : [])
      const names = l.groupPathNames || (l.groupName ? [l.groupName] : [])
      for (let i = 0; i < ids.length; i++) {
        const subPath = ids.slice(0, i + 1).join('/')
        const subName = names.slice(0, i + 1).join(' > ')
        pathsMap.set(subPath, subName)
      }
    })
    
    const groupTargetsList = Array.from(pathsMap.entries()).map(([pathKey, fullName]) => {
      const parts = pathKey.split('/')
      const leafId = parts[parts.length - 1]
      return {
        id: leafId,
        name: '',
        groupName: fullName,
      }
    })
    
    const rawLayers = layers
      .filter((l) => l.id !== menuLayer.id && !(l.groupPathIds && l.groupPathIds.length > 0) && !l.groupId)
      .map((l) => ({ id: l.id, name: l.name, groupName: '' }))
      
    return [...groupTargetsList, ...rawLayers]
  }, [menuLayer, layers])

  // Context Menu triggers
  const handleContextMenu = (layerId: string, e: React.MouseEvent) => {
    e.preventDefault()
    onSelectedLayerIdsChange((prev) => {
      const next = new Set(prev)
      next.add(layerId)
      setMenu({ id: layerId, type: 'layer', x: e.clientX, y: e.clientY, selectedIds: next })
      return next
    })
  }

  const handleGroupContextMenu = (groupId: string, e: React.MouseEvent) => {
    e.preventDefault()
    setMenu({ id: groupId, type: 'group', x: e.clientX, y: e.clientY, selectedIds: new Set() })
  }

  // Drag and Drop handlers
  const handleDragStart = (id: string, e: React.DragEvent) => {
    setDraggedId(id)
    setDraggedType('layer')
    e.dataTransfer.setData('text/plain', id)
  }

  const handleDragStartGroup = (id: string, e: React.DragEvent) => {
    setDraggedId(id)
    setDraggedType('group')
    e.dataTransfer.setData('text/plain', id)
  }

  const handleDragOver = (id: string, e: React.DragEvent) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    const pos = relativeY < rect.height / 2 ? 'before' : 'after'
    setDragOverId(id)
    setDropPosition(pos)
  }

  const handleDragOverGroup = (id: string, e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    if (relativeY < rect.height * 0.25) {
      setDragOverId(id)
      setDropPosition('before')
    } else if (relativeY > rect.height * 0.75) {
      setDragOverId(id)
      setDropPosition('after')
    } else {
      setDragOverId(id)
      setDropPosition('inside')
    }
  }

  const handleDragEnd = () => {
    setDraggedId(null)
    setDraggedType(null)
    setDragOverId(null)
    setDropPosition(null)
  }

  const handleDrop = (targetId: string, e: React.DragEvent) => {
    e.preventDefault()
    if (!draggedId) return
    onMoveLayerOrGroup?.(draggedId, targetId, dropPosition || 'after')
    handleDragEnd()
  }

  const getSwatchStyle = (l: GeoJSONLayer): React.CSSProperties => {
    if (l.styleSpec?.mode === 'categorized' && l.styleSpec.categories) {
      const colors = l.styleSpec.categories.map((c) => c.color).filter(Boolean)
      if (colors.length > 0) {
        const displayColors = colors.slice(0, 4)
        if (displayColors.length === 1) return { background: displayColors[0] }
        return { background: `linear-gradient(135deg, ${displayColors.join(', ')})` }
      }
    }
    if (l.geeSpec?.vis_params?.palette) {
      const palette = l.geeSpec.vis_params.palette
      if (Array.isArray(palette)) {
        const cssColors = palette.map((c: string) => c.startsWith('#') ? c : `#${c}`)
        return { background: `linear-gradient(135deg, ${cssColors.join(', ')})` }
      }
    }
    if (l.geeSpec || l.wmsSpec) {
      return { background: 'linear-gradient(135deg, #3b82f6, #10b981, #ef4444)' }
    }
    // Vector layers styling fallback
    if (l.styleSpec?.mode === 'graduated' && l.styleSpec.rampColors) {
      const colors = l.styleSpec.rampColors.filter(Boolean)
      if (colors.length > 0) {
        const displayColors = colors.slice(0, 4)
        if (displayColors.length === 1) return { background: displayColors[0] }
        return { background: `linear-gradient(135deg, ${displayColors.join(', ')})` }
      }
    }
    return { background: l.fillColor || l.lineColor || l.color }
  }

  // Selection handler — Cmd/Ctrl or Shift for multi-select, plain click = single select (toggle if already sole)
  const handleSelect = (layerId: string, e: React.MouseEvent) => {
    const isMulti = e.shiftKey || e.ctrlKey || e.metaKey
    const targetLayer = layers.find((l) => l.id === layerId)
    if (targetLayer && onSelectFeature) {
      const layerFeatures = targetLayer.data?.features || []
      const fullFeature = {
        type: 'Feature' as const,
        geometry:
          layerFeatures.length > 1
            ? {
                type: 'MultiPolygon' as const,
                coordinates: layerFeatures.map((f: any) => f.geometry?.coordinates).filter(Boolean),
              }
            : layerFeatures[0]?.geometry || { type: 'Point' as const, coordinates: [0, 0] },
        properties: {
          ...(layerFeatures[0]?.properties || {}),
          layer_name: targetLayer.name,
          total_feature_count: layerFeatures.length,
        },
      }
      onSelectFeature({ feature: fullFeature as any, layerId: targetLayer.id, layerName: targetLayer.name }, isMulti)
    }

    onSelectedLayerIdsChange((prev) => {
      const next = new Set(prev)
      if (e.ctrlKey || e.metaKey) {
        if (next.has(layerId)) next.delete(layerId)
        else next.add(layerId)
      } else if (e.shiftKey && prev.size > 0) {
        const lastSelected = Array.from(prev).pop()!
        const idx1 = layers.findIndex((l) => l.id === lastSelected)
        const idx2 = layers.findIndex((l) => l.id === layerId)
        if (idx1 !== -1 && idx2 !== -1) {
          const start = Math.min(idx1, idx2)
          const end = Math.max(idx1, idx2)
          for (let i = start; i <= end; i++) {
            next.add(layers[i].id)
          }
        }
      } else {
        // Plain click: if this layer is already the sole selection, deselect; otherwise select only it
        if (next.size === 1 && next.has(layerId)) {
          next.clear()
        } else {
          next.clear()
          next.add(layerId)
        }
      }
      return next
    })
  }

  const renderLayer = (layer: GeoJSONLayer, index: number, total: number, grouped = false) => {
    return (
      <LayerItemRow
        key={layer.id}
        layer={layer}
        grouped={grouped}
        activeStyleId={activeStyleId}
        activeAttrId={activeAttrId}
        onToggle={onToggle}
        onRemove={onRemove}
        onZoomTo={onZoomTo}
        onStyle={onStyle}
        onAttributes={onAttributes}
        onRename={onRename}
        onStyleChange={onStyleChange}
        onUpdateLayer={onUpdateLayer}
        onAttributesChange={onAttributesChange}
        onContextMenu={(e) => handleContextMenu(layer.id, e)}
        getSwatchStyle={getSwatchStyle}
        isSelected={selectedLayerIds.has(layer.id)}
        dragOverId={dragOverId}
        dropPosition={dropPosition === 'inside' ? null : dropPosition}
        onSelect={handleSelect}
        onDragStart={handleDragStart}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onDragEnd={handleDragEnd}
        selectedFeatures={selectedFeatures}
        onSelectFeature={onSelectFeature}
      />
    )
  }

  const renderNode = (node: TreeNode) => {
    if (node.type === 'layer') {
      return (
        <div key={node.id} className="nested-layer-item">
          {renderLayer(node.layer, 0, 1, node.depth > 0)}
        </div>
      )
    }
    
    const pathKey = getGroupPathKey(node)
    const collapsed = collapsedGroups.has(pathKey)
    const childLayers = getGroupLayersRecursively(node)
    const allVisible = childLayers.every((layer) => layer.visible)
    const isGroupSelected = childLayers.length > 0 && childLayers.every((l) => selectedLayerIds.has(l.id))

    return (
      <div key={node.id} className="layer-group">
        <div
          className={`layer-group-header ${isGroupSelected ? 'selected' : ''} ${!allVisible ? 'hidden' : ''} ${dragOverId === node.id ? `drag-over-${dropPosition}` : ''}`}
          draggable={true}
          onDragStart={(e) => handleDragStartGroup(node.id, e)}
          onDragOver={(e) => handleDragOverGroup(node.id, e)}
          onDragEnd={handleDragEnd}
          onDrop={(e) => handleDrop(node.id, e)}
          onContextMenu={(e) => handleGroupContextMenu(node.id, e)}
          onClick={(e) => {
            const target = e.target as HTMLElement
            if (target.closest('button') || target.closest('input')) {
              return
            }
            onSelectedLayerIdsChange((prev) => {
              const next = new Set(prev)
              const groupLayerIds = childLayers.map((l) => l.id)
              const allSelected = groupLayerIds.every((id) => next.has(id))
              if (allSelected) {
                groupLayerIds.forEach((id) => next.delete(id))
              } else {
                groupLayerIds.forEach((id) => next.add(id))
              }
              return next
            })
          }}
        >
          <button
            className="layer-group-toggle"
            onClick={() => {
              setCollapsedGroups((prev) => {
                const next = new Set(prev)
                if (next.has(pathKey)) next.delete(pathKey)
                else next.add(pathKey)
                return next
              })
            }}
            title={collapsed ? 'Expand group' : 'Collapse group'}
            style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
          >
            {collapsed ? (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="9 18 15 12 9 6"></polyline>
              </svg>
            ) : (
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            )}
          </button>
          
          <button
            className="layer-visibility"
            onClick={() => onToggleGroupPath(node, !allVisible)}
            title={allVisible ? 'Hide group' : 'Show group'}
            style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
          >
            {allVisible ? (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                <circle cx="12" cy="12" r="3"></circle>
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 12c2-4 5-6 10-6s8 2 10 6"></path>
                <path d="M6 15.5l-1.5 2"></path>
                <path d="M12 17v2"></path>
                <path d="M18 15.5l1.5 2"></path>
              </svg>
            )}
          </button>
          
          {editingGroupId === node.id ? (
            <input
              type="text"
              className="layer-group-name-input"
              defaultValue={node.name}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const val = (e.target as HTMLInputElement).value
                  onRenameGroupPath(node, val)
                  setEditingGroupId(null)
                }
              }}
              onBlur={(e) => {
                const val = (e.target as HTMLInputElement).value
                onRenameGroupPath(node, val)
                setEditingGroupId(null)
              }}
              autoFocus
              title="Rename group"
            />
          ) : (
            <span
              className="layer-group-name"
              title={node.name}
              onDoubleClick={(e) => {
                e.stopPropagation()
                setEditingGroupId(node.id)
              }}
            >
              {node.name}
            </span>
          )}
          
          <span className="layer-count">{childLayers.length}</span>
          
          <button
            className="layer-remove"
            onClick={(e) => {
              e.stopPropagation()
              childLayers.forEach((l) => onRemove?.(l.id))
              onSelectedLayerIdsChange(new Set())
            }}
            title="Remove group and layers"
            style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        
        {!collapsed && (
          <div className="layer-group-children">
            {node.children.map((child) => renderNode(child))}
          </div>
        )}
      </div>
    )
  }

  if (layers.length === 0) {
    return (
      <div className="layer-panel-empty">
        <p>No layers loaded</p>
        <p className="hint">Click a .geojson file in Files to add a layer</p>
      </div>
    )
  }

  return (
    <div
      ref={panelRef}
      className="layer-panel"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault()
        if (draggedId) {
          onMoveLayerOrGroup?.(draggedId, '', 'after')
          handleDragEnd()
        }
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onSelectedLayerIdsChange(new Set())
      }}
    >
      {tree.map((node) => renderNode(node))}

      {menu && (() => {
        if (menu.type === 'group' && menuGroupNode) {
          const childLayers = getGroupLayersRecursively(menuGroupNode)
          const allVisible = childLayers.every((layer) => layer.visible)
          return (
            <div
              className="layer-context-menu"
              style={{ left: menu.x, top: menu.y }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="layer-context-title">
                Group: {menuGroupNode.name}
              </div>
              <button
                type="button"
                onClick={() => {
                  onToggleGroupPath(menuGroupNode!, !allVisible)
                  setMenu(null)
                }}
              >
                {allVisible ? 'Hide Group' : 'Show Group'}
              </button>
              <button
                type="button"
                onClick={() => {
                  onUngroupGroup?.(menuGroupNode!.id)
                  setMenu(null)
                  onSelectedLayerIdsChange(new Set())
                }}
              >
                Ungroup all layers
              </button>
              <button
                type="button"
                onClick={() => {
                  const childIds = childLayers.map((c) => c.id)
                  onGroupMulti?.(childIds, 'New Subgroup')
                  setMenu(null)
                }}
              >
                Create Subgroup
              </button>
              <div className="layer-context-divider" />
              <button
                type="button"
                style={{ color: 'var(--danger)' }}
                onClick={() => {
                  childLayers.forEach((l) => onRemove?.(l.id))
                  setMenu(null)
                  onSelectedLayerIdsChange(new Set())
                }}
              >
                Delete group & layers
              </button>
            </div>
          )
        }

        if (menu.type === 'layer' && menuLayer) {
          const menuSelectedIds = menu.selectedIds ?? new Set([menu.id])
          const isMulti = menuSelectedIds.size > 1
          const selectedInGroup = Array.from(menuSelectedIds).filter(
            (id) => {
              const l = layers.find((layer) => layer.id === id)
              return l && (l.groupPathIds?.length || l.groupId)
            }
          )
          const featCount = menuLayer.data?.features?.length ?? 0
          
          return (
            <div
              className="layer-context-menu"
              style={{ left: menu.x, top: menu.y }}
              onClick={(e) => e.stopPropagation()}
            >
              {isMulti ? (
                <>
                  <div className="layer-context-title">
                    {menuSelectedIds.size} layers selected
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onGroupMulti?.(Array.from(menuSelectedIds))
                      setMenu(null)
                      onSelectedLayerIdsChange(new Set())
                    }}
                  >
                    Group these layers
                  </button>
                  {selectedInGroup.length > 0 && (
                    <>
                      <div className="layer-context-divider" />
                      <button
                        type="button"
                        onClick={() => {
                          selectedInGroup.forEach((id) => onUngroup?.(id))
                          setMenu(null)
                          onSelectedLayerIdsChange(new Set())
                        }}
                      >
                        {selectedInGroup.length === menuSelectedIds.size
                          ? 'Ungroup all selected'
                          : `Ungroup ${selectedInGroup.length} grouped layer${selectedInGroup.length > 1 ? 's' : ''}`}
                      </button>
                    </>
                  )}
                </>
              ) : (
                <>
                  <div className="layer-context-title">
                    Feature Count: {featCount}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onToggle(menuLayer.id)
                      setMenu(null)
                    }}
                  >
                    {menuLayer.visible ? 'Hide Layer' : 'Show Layer'}
                  </button>
                  {featCount > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        onZoomTo(menuLayer.id)
                        setMenu(null)
                      }}
                    >
                      Zoom to Layer
                    </button>
                  )}
                  {onStyle && (!menuLayer.wmsSpec && !menuLayer.geeSpec || menuLayer.rasterOverlaySpec) && (
                    <button
                      type="button"
                      onClick={() => {
                        onStyle(menuLayer.id)
                        setMenu(null)
                      }}
                    >
                      Adjust Symbology
                    </button>
                  )}
                  {onAttributes && !menuLayer.wmsSpec && !menuLayer.geeSpec && featCount > 0 && (
                    <button
                      type="button"
                      onClick={() => {
                        onAttributes(menuLayer.id)
                        setMenu(null)
                      }}
                    >
                      Edit Attribute Table
                    </button>
                  )}
                  <button
                    type="button"
                    style={{ color: 'var(--danger)' }}
                    onClick={() => {
                      onRemove(menuLayer.id)
                      setMenu(null)
                      onSelectedLayerIdsChange(new Set())
                    }}
                  >
                    Delete Layer
                  </button>

                  <div className="layer-context-divider" />
                  <div className="layer-context-title">Group Actions</div>
                  {groupTargets.length === 0 ? (
                    <div className="layer-context-empty">No other groups</div>
                  ) : (
                    groupTargets.map((target) => (
                      <button
                        key={target.id}
                        type="button"
                        onClick={() => {
                          onMoveLayerOrGroup?.(menuLayer.id, target.id, 'inside')
                          setMenu(null)
                        }}
                      >
                        Move to: {target.groupName || target.name}
                      </button>
                    ))
                  )}
                  {(menuLayer.groupPathIds?.length || menuLayer.groupId) && (
                    <button
                      type="button"
                      onClick={() => {
                        onUngroup?.(menuLayer.id)
                        setMenu(null)
                      }}
                    >
                      Ungroup Layer
                    </button>
                  )}
                </>
              )}
            </div>
          )
        }
        return null
      })()}
    </div>
  )
}

interface LayerItemRowProps {
  layer: GeoJSONLayer
  grouped: boolean
  activeStyleId: string | null
  activeAttrId: string | null
  onToggle: (id: string) => void
  onRemove: (id: string) => void
  onZoomTo: (id: string) => void
  onStyle?: (id: string) => void
  onAttributes?: (id: string) => void
  onRename?: (id: string, name: string) => void
  onStyleChange?: (layerId: string, styleSpec: LayerStyleSpec) => void
  onUpdateLayer?: (layerId: string, updates: Partial<GeoJSONLayer>) => void
  onAttributesChange?: (layerId: string, data: any) => void
  onContextMenu: (e: React.MouseEvent) => void
  getSwatchStyle: (l: GeoJSONLayer) => React.CSSProperties

  // selection & drag-and-drop
  isSelected: boolean
  dragOverId: string | null
  dropPosition: 'before' | 'after' | null
  onSelect: (id: string, e: React.MouseEvent) => void
  onDragStart: (id: string, e: React.DragEvent) => void
  onDragOver: (id: string, e: React.DragEvent) => void
  onDrop: (id: string, e: React.DragEvent) => void
  onDragEnd: () => void
  selectedFeatures?: SelectedFeatureEntry[]
  onSelectFeature?: (entry: SelectedFeatureEntry | null, shiftKey: boolean) => void
}

function LayerItemRow({
  layer,
  grouped,
  activeStyleId,
  activeAttrId,
  onToggle,
  onRemove,
  onZoomTo,
  onStyle,
  onAttributes,
  onRename,
  onStyleChange,
  onUpdateLayer,
  onAttributesChange,
  onContextMenu,
  getSwatchStyle,
  isSelected,
  dragOverId,
  dropPosition,
  onSelect,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  selectedFeatures,
  onSelectFeature,
}: LayerItemRowProps) {
  const isStyleActive = activeStyleId === layer.id
  const isAttrActive = activeAttrId === layer.id
  const [showAbove, setShowAbove] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const rowRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isStyleActive || isAttrActive) {
      const el = rowRef.current
      if (el) {
        const container = el.closest('.layer-panel')
        if (container) {
          const rect = el.getBoundingClientRect()
          const containerRect = container.getBoundingClientRect()
          const spaceBelow = containerRect.bottom - rect.bottom
          // If less than 300px space remains below this row inside the scrollable container, pop UP
          setShowAbove(spaceBelow < 300)
        }
      }
    }
  }, [isStyleActive, isAttrActive])

  useEffect(() => {
    if (!isStyleActive && !isAttrActive) return
    const handleOutsideClick = (e: MouseEvent) => {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) {
        if (isStyleActive) onStyle?.(layer.id)
        if (isAttrActive) onAttributes?.(layer.id)
      }
    }
    window.addEventListener('click', handleOutsideClick, true)
    return () => {
      window.removeEventListener('click', handleOutsideClick, true)
    }
  }, [isStyleActive, isAttrActive, layer.id, onStyle, onAttributes])

  return (
    <div
      ref={rowRef}
      className={`layer-item ${grouped ? 'grouped' : ''} ${!layer.visible ? 'hidden' : ''} ${isSelected ? 'selected' : ''} ${dragOverId === layer.id ? `drag-over-${dropPosition}` : ''}`}
      style={{ position: 'relative', cursor: 'grab' }}
      onContextMenu={onContextMenu}
      draggable={true}
      onDragStart={(e) => onDragStart(layer.id, e)}
      onDragOver={(e) => onDragOver(layer.id, e)}
      onDrop={(e) => onDrop(layer.id, e)}
      onDragEnd={onDragEnd}
      onClick={(e) => {
        const target = e.target as HTMLElement
        if (target.closest('button') || target.closest('.layer-color') || target.closest('input')) {
          return
        }
        onSelect(layer.id, e)
      }}
    >
      <button
        className="layer-visibility"
        onClick={() => onToggle(layer.id)}
        title={layer.visible ? 'Hide layer' : 'Show layer'}
        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
      >
        {layer.visible ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 12c2-4 5-6 10-6s8 2 10 6"></path>
            <path d="M6 15.5l-1.5 2"></path>
            <path d="M12 17v2"></path>
            <path d="M18 15.5l1.5 2"></path>
          </svg>
        )}
      </button>
      <span
        className={`layer-color ${onStyle && (!layer.wmsSpec && !layer.geeSpec || layer.rasterOverlaySpec) ? 'clickable' : ''} ${activeStyleId === layer.id ? 'active' : ''}`}
        style={getSwatchStyle(layer)}
        onClick={() => { if (!layer.wmsSpec && !layer.geeSpec || layer.rasterOverlaySpec) onStyle?.(layer.id) }}
        title={layer.rasterOverlaySpec ? 'Raster overlay alignment & opacity' : (layer.wmsSpec || layer.geeSpec ? 'Raster layer — no symbology' : 'Symbology & labels')}
      />

      {isEditing && onRename ? (
        <input
          type="text"
          className="layer-name-input"
          value={layer.name}
          onChange={(e) => onRename(layer.id, e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              setIsEditing(false)
            }
          }}
          onBlur={() => setIsEditing(false)}
          autoFocus
          title="Rename layer"
        />
      ) : (
        <span
          className="layer-name"
          title={layer.name}
          onDoubleClick={(e) => {
            e.stopPropagation()
            setIsEditing(true)
          }}
        >
          {layer.name}
        </span>
      )}
      {!layer.wmsSpec && !layer.geeSpec && (
        <span className="layer-count">{layer.data?.features?.length ?? 0}</span>
      )}
      {onAttributes && !layer.wmsSpec && !layer.geeSpec && (layer.data?.features?.length || 0) > 0 && (
        <button
          className={`layer-style ${activeAttrId === layer.id ? 'active' : ''}`}
          onClick={() => onAttributes(layer.id)}
          title="Edit attributes"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 20h9"></path>
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
          </svg>
        </button>
      )}
      {!layer.wmsSpec && !layer.geeSpec && (layer.data?.features?.length || 0) > 0 && (
        <button
          className="layer-zoom"
          onClick={() => onZoomTo(layer.id)}
          title="Zoom to layer"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <circle cx="12" cy="12" r="3" />
            <line x1="12" y1="1" x2="12" y2="3" />
            <line x1="12" y1="21" x2="12" y2="23" />
            <line x1="1" y1="12" x2="3" y2="12" />
            <line x1="21" y1="12" x2="23" y2="12" />
          </svg>
        </button>
      )}

      <button
        className="layer-remove"
        onClick={() => onRemove(layer.id)}
        title="Remove layer"
        style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      </button>

      {isStyleActive && onStyleChange && (
        <div className={`layer-popup-container layer-symbology-popup ${showAbove ? 'popup-above' : 'popup-below'}`}>
          <SymbologyPanel
            layer={layer}
            onChange={onStyleChange}
            onClose={() => onStyle?.(layer.id)}
            onUpdateLayer={onUpdateLayer}
          />
        </div>
      )}

      {isAttrActive && onAttributesChange && (
        <div className={`layer-popup-container layer-attributes-popup ${showAbove ? 'popup-above' : 'popup-below'}`}>
          <ErrorBoundary label="Attribute Table">
            <AttributeTable
              layer={layer}
              onChange={onAttributesChange}
              onClose={() => onAttributes?.(layer.id)}
              selectedFeatures={selectedFeatures || []}
              onSelectFeature={onSelectFeature || (() => {})}
            />
          </ErrorBoundary>
        </div>
      )}
    </div>
  )
}
