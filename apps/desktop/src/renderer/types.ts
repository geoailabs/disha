import type { Feature, FeatureCollection, Geometry, Polygon, MultiPolygon } from 'geojson'

/** A single entry in the multi-select feature selection. */
export type SelectedFeatureEntry = { layerId: string; feature: Feature }

export interface GeoJSONLayer {
  id: string
  name: string
  filePath: string
  visible: boolean
  groupId?: string
  groupName?: string
  groupPathIds?: string[]
  groupPathNames?: string[]
  data: FeatureCollection
  color: string
  fillColor?: string
  lineColor?: string
  lineWidth?: number
  lineDasharray?: number[]
  opacity?: number
  styleSpec?: LayerStyleSpec
  wmsSpec?: { url: string; layer_name: string }
  geeSpec?: { url: string; dataset?: string; vis_params?: any }
  rasterOverlaySpec?: { url: string; corners: [number, number][] }
}

// ── Data-driven symbology + labels ──
//
// A serializable description of how a layer should be styled. Lives on the
// layer (and in project.json). MapView translates it into MapLibre paint
// expressions; Legend renders it; the `style_layer` action and SymbologyPanel
// both write it.

export type ClassificationMethod = 'equal-interval' | 'quantile'

/** Text labels drawn on the map from a feature property. */
export interface LabelSpec {
  enabled?: boolean
  property?: string
  size?: number       // px, default 12
  color?: string      // default '#1f2937'
  haloColor?: string  // default '#ffffff'
  minZoom?: number     // default 10
}

export interface LayerStyleSpec {
  mode: 'simple' | 'categorized' | 'graduated'
  /** Property driving the color. Required for categorized/graduated. */
  property?: string
  // categorized — ordered so the legend is deterministic
  categories?: Array<{ value: string; color: string }>
  otherColor?: string
  // graduated (choropleth) — `rampColors` length === breaks.length + 1
  breaks?: number[]
  rampColors?: string[]
  classification?: ClassificationMethod
  rampName?: string
  // shared
  opacity?: number
  label?: LabelSpec
  fillColor?: string
  strokeColor?: string
  lineWidth?: number
}

export interface MapViewState {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
}

/** Saved map extent + view for quick navigation */
export interface MapBookmark {
  id: string
  name: string
  south: number
  west: number
  north: number
  east: number
  zoom: number
}

export interface ZonePreset {
  code: string
  label: string
  color: string
  description: string
}

export const DEFAULT_ZONE_PRESETS: ZonePreset[] = [
  { code: 'R1', label: 'Residential (low)', color: '#fef08a', description: 'Low-density residential' },
  { code: 'R2', label: 'Residential (med)', color: '#facc15', description: 'Medium-density residential' },
  { code: 'C1', label: 'Commercial', color: '#fca5a5', description: 'Retail / office commercial' },
  { code: 'I1', label: 'Industrial', color: '#c4b5fd', description: 'Industrial / logistics' },
  { code: 'G', label: 'Greenspace', color: '#86efac', description: 'Parks, agriculture, open space' },
  { code: 'MX', label: 'Mixed use', color: '#fdba74', description: 'Mixed residential-commercial' },
  { code: 'INST', label: 'Institutional', color: '#93c5fd', description: 'Schools, hospitals, civic' },
]

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
  research?: {
    phase: 'idle' | 'running' | 'done'
    steps: string[]
    reasoning: string
    markdown: string
    citations: Array<{ url: string; title: string }>
  }
  attachments?: Array<{ fileName: string; filePath: string; mimeType: string }>
}

export interface Conversation {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
}

// ── Map action contract ──
//
// One variant per backend action tool. The backend sends `{type, action, payload}`
// over the WebSocket; the renderer treats `{type: action, payload}` as a MapAction.
// Adding a new action means: (1) add a variant here, (2) add a case in
// App.tsx:handleMapAction, (3) add a case in MapView.tsx's action switch.

export type MapAction =
  | { type: 'fly_to'; payload: { lat: number; lng: number; zoom?: number } }
  | { type: 'fit_bounds'; payload: { south: number; west: number; north: number; east: number } }
  | { type: 'set_view'; payload: MapViewState }
  | {
      type: 'add_marker'
      payload: { lat: number; lng: number; label?: string; color?: string; description?: string }
    }
  | {
      type: 'add_markers'
      payload: {
        markers: Array<{
          lat: number
          lng: number
          label?: string
          color?: string
          description?: string
        }>
      }
    }
  | { type: 'clear_markers'; payload: Record<string, never> }
  | {
      type: 'draw_line'
      payload: { coordinates: number[][]; color?: string; width?: number; label?: string }
    }
  | {
      type: 'draw_polygon'
      payload: { coordinates: number[][]; color?: string; opacity?: number; label?: string }
    }
  | {
      type: 'draw_circle'
      payload: {
        center_lat: number
        center_lng: number
        radius_km: number
        color?: string
        label?: string
      }
    }
  | {
      type: 'add_geojson'
      payload: { geojson: FeatureCollection | Feature | Geometry; name: string; color?: string }
    }
  | {
      type: 'highlight_features'
      payload: { layer_name: string; property_name: string; property_value: string }
    }
  | {
      type: 'set_layer_style'
      payload: {
        layer_name: string
        fill_color?: string
        line_color?: string
        opacity?: number
      }
    }
  | {
      type: 'style_layer'
      payload: {
        layer_name: string
        mode: 'simple' | 'categorized' | 'graduated'
        property?: string
        classification?: ClassificationMethod
        classes?: number
        ramp?: string
        categories?: Array<{ value: string; color: string }>
        opacity?: number
        label_property?: string
        label_enabled?: boolean
        label_size?: number
        label_color?: string
      }
    }
  | { type: 'toggle_layer'; payload: { layer_name: string; visible: boolean } }
  | { type: 'remove_layer'; payload: { layer_name: string } }
  | {
      type: 'save_bookmark'
      payload: {
        name: string
        south?: number
        west?: number
        north?: number
        east?: number
        zoom?: number
      }
    }
  | { type: 'go_to_bookmark'; payload: { name: string } }
  | {
      type: 'export_region_clip'
      payload: {
        output_base_name: string
        south?: number
        west?: number
        north?: number
        east?: number
      }
    }
  | { type: 'refresh_artifacts'; payload: Record<string, never> }
  | { type: 'switch_basemap'; payload: { basemap: string } }
  | { type: 'add_wms_layer'; payload: { url: string; layer_name: string; title: string } }
  | { type: 'add_gee_layer'; payload: { url: string; dataset: string; vis_params: any; title: string } }
  | { type: 'add_geojson_file'; payload: { path: string; name: string; color?: string; styleSpec?: any } }
  | {
      type: 'add_scenarios'
      payload: {
        scenarios: Array<{
          name: string
          description?: string
          id?: string
          createdAt?: number
          layerIds?: string[]
          layerVisibility?: Record<string, boolean>
        }>
      }
    }
  | {
      type: 'add_raster_overlay'
      payload: {
        id: string
        name: string
        filePath: string
        corners: [number, number][]
      }
    }
  | {
      type: 'georeference_success'
      payload: {
        id: string
        name: string
        corners: [number, number][]
      }
    }
  | {
      type: 'draw_distance_measurement'
      payload: {
        /** Ordered waypoints as [lon, lat] pairs */
        points: number[][]
        direct_km: number
        route_coordinates?: number[][]
        route_km?: number
        duration_minutes?: number
        route_error?: string
      }
    }
export interface ChatErrorMessage {
  code: string
  message: string
}

export type MapActionType = MapAction['type']

export interface Artifact {
  id: number
  title: string
  content: string
  artifact_type: string
  format: 'markdown' | 'table' | 'image' | 'geojson'
  file_path: string | null
  meta: string | null   // JSON string
  created_at: string
  updated_at: string
}

export interface ProjectData {
  mapState: MapViewState
  layers: Array<{
    name: string
    /** Workspace-relative for new projects; absolute for legacy projects. */
    filePath: string
    visible: boolean
    groupId?: string
    groupName?: string
    color: string
    fillColor?: string
    lineColor?: string
    lineWidth?: number
    lineDasharray?: number[]
    opacity?: number
    styleSpec?: LayerStyleSpec
    wmsSpec?: { url: string; layer_name: string }
    geeSpec?: { url: string; dataset?: string; vis_params?: any }
  }>
  conversations: Conversation[]
  activeConversationId: string | null
  chatHistory?: ChatMessage[]
  basemap: string
  bookmarks?: MapBookmark[]
}

/** A small, lossy summary of a layer's geometry that can be sent to the LLM. */
export type LayerGeometryData =
  | { bbox: [number, number, number, number] }
  | Array<{ type?: Geometry['type']; coordinates?: unknown }>

export interface MapContext {
  workspace?: string
  activeScenario?: {
    name: string
    description: string
  }
  center: [number, number]
  zoom: number
  bounds?: { west: number; south: number; east: number; north: number }
  bookmarks: Array<{
    name: string
    south: number
    west: number
    north: number
    east: number
    zoom: number
  }>
  layers: Array<{
    name: string
    featureCount: number
    geometryTypes: string[]
    properties: string[]
    visible: boolean
    groupId?: string
    groupName?: string
    geometry_data?: LayerGeometryData
    features_data?: Array<Record<string, any>>
    style?: LayerStyleSummary
  }>
  basemap: string
  selected_features?: Array<{
    layerId: string
    layerName: string
    properties: Record<string, any>
    geometry?: any
  }>
}

/** Compact view of a layer's active styling, sent to the LLM so it can avoid
 *  re-issuing a style_layer call that matches what's already applied. */
export interface LayerStyleSummary {
  mode: 'simple' | 'categorized' | 'graduated'
  property?: string
  categoryCount?: number
  classes?: number
  ramp?: string
  labels: false | { property: string }
}

/** A boundary geometry — what comes out of Nominatim's `polygon_geojson=1` */
export type BoundaryGeometry = Polygon | MultiPolygon

export const LAYER_COLORS = [
  '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
  '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
]

export const BASEMAPS: Record<string, { name: string; tiles: string[]; attribution: string }> = {
  street: {
    name: 'Street',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenStreetMap contributors',
  },
  satellite: {
    name: 'Satellite',
    tiles: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: '&copy; Esri',
  },
  dark: {
    name: 'Dark',
    tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
    attribution: '&copy; CartoDB',
  },
  light: {
    name: 'Light',
    tiles: ['https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png'],
    attribution: '&copy; CartoDB',
  },
  terrain: {
    name: 'Terrain',
    tiles: ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenTopoMap',
  },
  topo: {
    name: 'Topo',
    tiles: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: '&copy; Esri',
  },
  humanitarian: {
    name: 'Humanitarian',
    tiles: ['https://tile.openstreetmap.fr/hot/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenStreetMap contributors',
  },
}
