import { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Artifact, SourceEntry } from '../types'
import './ArtifactsPanel.css'

const API_BASE = 'http://localhost:8765/api/artifacts'

const getSlug = (node: any): string => {
  if (!node) return ''
  if (typeof node === 'string') {
    return node
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/(^-|-$)/g, '')
  }
  if (Array.isArray(node)) {
    return node.map(getSlug).join('-').replace(/-+/g, '-').replace(/(^-|-$)/g, '')
  }
  if (node.props && node.props.children) {
    return getSlug(node.props.children)
  }
  return ''
}

const headingComponents = {
  h1: ({ children, ...props }: any) => <h1 id={getSlug(children)} {...props}>{children}</h1>,
  h2: ({ children, ...props }: any) => <h2 id={getSlug(children)} {...props}>{children}</h2>,
  h3: ({ children, ...props }: any) => <h3 id={getSlug(children)} {...props}>{children}</h3>,
  h4: ({ children, ...props }: any) => <h4 id={getSlug(children)} {...props}>{children}</h4>,
  h5: ({ children, ...props }: any) => <h5 id={getSlug(children)} {...props}>{children}</h5>,
  h6: ({ children, ...props }: any) => <h6 id={getSlug(children)} {...props}>{children}</h6>,
}

const getCategoryIcon = (_category: string = ''): string => {
  return ''
}

const DEFAULT_SOURCE_URLS: Record<string, string> = {
  'air quality': 'https://open-meteo.com/en/docs/air-quality-api',
  'cams': 'https://open-meteo.com/en/docs/air-quality-api',
  'pm2.5': 'https://open-meteo.com/en/docs/air-quality-api',
  'pm10': 'https://open-meteo.com/en/docs/air-quality-api',
  'aqi': 'https://open-meteo.com/en/docs/air-quality-api',
  'weather': 'https://open-meteo.com/en/docs',
  'climate': 'https://open-meteo.com/en/docs',
  'forecast': 'https://open-meteo.com/en/docs',
  'worldpop': 'https://hub.worldpop.org',
  'population': 'https://hub.worldpop.org',
  'demographic': 'https://hub.worldpop.org',
  'openstreetmap': 'https://www.openstreetmap.org',
  'osm': 'https://www.openstreetmap.org',
  'overpass': 'https://wiki.openstreetmap.org/wiki/Overpass_API',
  'dynamic world': 'https://dynamicworld.app',
  'sentinel': 'https://earthengine.google.com',
  'earth engine': 'https://earthengine.google.com',
  'places': 'https://developers.google.com/maps/documentation/places/web-service',
  'overture': 'https://overturemaps.org',
  'osrm': 'https://project-osrm.org',
  'route': 'https://project-osrm.org',
  'routing': 'https://project-osrm.org',
  'isochrone': 'https://project-osrm.org',
  'datameet': 'http://projects.datameet.org/maps',
  'solar': 'https://developers.google.com/maps/documentation/solar',
  'geodesic': 'https://proj.org/operations/geodesic.html',
  'wgs84': 'https://proj.org/operations/geodesic.html',
  'pyproj': 'https://proj.org/operations/geodesic.html',
  'zoning': 'https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf',
  'master plan': 'https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf',
  'urdpfi': 'https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf',
  'land budget': 'https://mohua.gov.in/upload/uploadfiles/files/URDPFI_Guidelines_Vol_I(2).pdf',
  'emissions': 'https://www.eea.europa.eu/publications/emep-eea-guidebook-2019',
  'gtfs': 'https://gtfs.org',
  'mcda': 'https://en.wikipedia.org/wiki/Analytic_hierarchy_process',
}

function resolveSourceUrl(s: Partial<SourceEntry>): string {
  if (s.url && s.url.startsWith('http')) return s.url
  const text = `${s.name || ''} ${s.provider || ''} ${s.category || ''}`.toLowerCase()
  for (const [kw, url] of Object.entries(DEFAULT_SOURCE_URLS)) {
    if (text.includes(kw)) return url
  }
  return ''
}

function parseSourcesFromMarkdown(content: string = ''): SourceEntry[] {
  if (!content) return []
  const headingMatch = content.match(/^#+\s+(?:data\s+sources\s*(?:&|and)\s*methodology|data\s+sources|sources\s*(?:&|and)\s*methodology|methodology\s*(?:&|and)\s*sources|sources|references)\b/im)
  if (!headingMatch || headingMatch.index === undefined) return []

  const sectionText = content.slice(headingMatch.index + headingMatch[0].length).split(/^#+\s+/m)[0]
  const tableLines = sectionText.split('\n').map(l => l.trim()).filter(l => l.startsWith('|'))
  if (tableLines.length >= 3) {
    const headers = tableLines[0].replace(/^\||\|$/g, '').split('|').map(h => h.trim().toLowerCase())
    const nameIdx = headers.findIndex(h => h.includes('source') || h.includes('tool') || h.includes('dataset') || h.includes('name'))
    const catIdx = headers.findIndex(h => h.includes('category') || h.includes('type') || h.includes('domain'))
    const provIdx = headers.findIndex(h => h.includes('provider') || h.includes('endpoint') || h.includes('origin'))
    const scopeIdx = headers.findIndex(h => h.includes('scope') || h.includes('query') || h.includes('extent') || h.includes('parameter'))
    const tsIdx = headers.findIndex(h => h.includes('date') || h.includes('time') || h.includes('timestamp'))
    const basisIdx = headers.findIndex(h => h.includes('basis') || h.includes('assumption') || h.includes('formula') || h.includes('norm'))
    const urlIdx = headers.findIndex(h => h.includes('url') || h.includes('link') || h.includes('href'))

    if (nameIdx !== -1) {
      const results: SourceEntry[] = []
      for (const line of tableLines.slice(2)) {
        const rawCells = line.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
        if (rawCells[nameIdx] && !rawCells[nameIdx].startsWith('---')) {
          let nameVal = rawCells[nameIdx]
          let urlVal = ''

          const nameLinkMatch = nameVal.match(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/)
          if (nameLinkMatch) {
            nameVal = nameLinkMatch[1]
            urlVal = nameLinkMatch[2]
          }
          nameVal = nameVal.replace(/[*`]/g, '').trim()

          let provVal = provIdx !== -1 && rawCells[provIdx] ? rawCells[provIdx] : ''
          const provLinkMatch = provVal.match(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/)
          if (provLinkMatch) {
            provVal = provLinkMatch[1]
            if (!urlVal) urlVal = provLinkMatch[2]
          }
          provVal = provVal.replace(/[*`]/g, '').trim()

          const catVal = catIdx !== -1 && rawCells[catIdx] ? rawCells[catIdx].replace(/[*`]/g, '').trim() : 'Data Source'
          const scopeVal = scopeIdx !== -1 && rawCells[scopeIdx] ? rawCells[scopeIdx].replace(/[*`]/g, '').trim() : ''
          const tsVal = tsIdx !== -1 && rawCells[tsIdx] ? rawCells[tsIdx].replace(/[*`]/g, '').trim() : ''
          const basisVal = basisIdx !== -1 && rawCells[basisIdx] ? rawCells[basisIdx].replace(/[*`]/g, '').trim() : ''

          if (urlIdx !== -1 && rawCells[urlIdx]) {
            const rawUrl = rawCells[urlIdx].replace(/[<>*`]/g, '').trim()
            if (rawUrl.startsWith('http')) urlVal = rawUrl
          }

          const entry: SourceEntry = {
            name: nameVal,
            category: catVal,
            provider: provVal,
            query_scope: scopeVal,
            timestamp: tsVal,
            basis_or_assumptions: basisVal,
            url: urlVal || resolveSourceUrl({ name: nameVal, provider: provVal, category: catVal }),
          }
          results.push(entry)
        }
      }
      if (results.length > 0) return results
    }
  }

  // Bullet parser fallback
  const bullets = sectionText.match(/^\s*[-*]\s+\*\*([^*]+)\*\*[:\s]*(.*)/gm)
  if (bullets) {
    return bullets.map(b => {
      const m = b.match(/^\s*[-*]\s+\*\*([^*]+)\*\*[:\s]*(.*)/)
      let nameVal = m ? m[1].trim() : 'Source'
      let urlVal = ''
      const linkMatch = nameVal.match(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/)
      if (linkMatch) {
        nameVal = linkMatch[1]
        urlVal = linkMatch[2]
      }
      nameVal = nameVal.replace(/[*`]/g, '').trim()
      const descVal = m ? m[2].trim() : ''
      return {
        name: nameVal,
        category: 'Data Source',
        basis_or_assumptions: descVal,
        url: urlVal || resolveSourceUrl({ name: nameVal, basis_or_assumptions: descVal }),
      }
    })
  }

  return []
}

function inferSourcesFromText(title: string = '', content: string = ''): SourceEntry[] {
  const full = `${title} ${content}`.toLowerCase()
  const inferred: SourceEntry[] = []

  if (full.includes('pm2.5') || full.includes('pm10') || full.includes('aqi') || full.includes('air quality')) {
    inferred.push({
      name: 'Open-Meteo Air Quality Index',
      category: 'Environmental & Air Quality',
      provider: 'Copernicus CAMS / Open-Meteo API',
      query_scope: 'Atmospheric sensors & dispersion grid',
      timestamp: 'Recorded observation',
      basis_or_assumptions: 'Copernicus Atmosphere Monitoring Service (CAMS) atmospheric dispersion models for PM2.5, PM10, and AQI.',
      url: 'https://open-meteo.com/en/docs/air-quality-api',
    })
  }

  if (full.includes('weather') || full.includes('forecast') || full.includes('temperature') || full.includes('precipitation') || full.includes('humidity')) {
    inferred.push({
      name: 'Open-Meteo Weather Forecast',
      category: 'Meteorological & Climate',
      provider: 'Open-Meteo Weather API',
      query_scope: 'Numerical weather prediction grid',
      timestamp: 'Recorded forecast',
      basis_or_assumptions: 'High-resolution numerical weather prediction models (ECMWF, GFS, ICON) providing multi-day meteorological forecasts.',
      url: 'https://open-meteo.com/en/docs',
    })
  }

  if (full.includes('worldpop') || full.includes('population') || full.includes('demographic') || full.includes('density')) {
    inferred.push({
      name: 'WorldPop 100m Population Count',
      category: 'Raster Demographics',
      provider: 'WorldPop (hub.worldpop.org)',
      query_scope: 'Study area perimeter',
      timestamp: 'UN-Adjusted 2025',
      basis_or_assumptions: '100m building-constrained raster population grid aggregated within study boundary.',
      url: 'https://hub.worldpop.org',
    })
  }

  if (full.includes('osm') || full.includes('openstreetmap') || full.includes('amenit') || full.includes('school') || full.includes('boundary')) {
    inferred.push({
      name: 'OpenStreetMap Vector Features',
      category: 'Geospatial Vector',
      provider: 'OpenStreetMap (Overpass API)',
      query_scope: 'Study area administrative extent',
      timestamp: 'OSM Current',
      basis_or_assumptions: 'Topological vector features and administrative boundary hierarchy from OpenStreetMap.',
      url: 'https://www.openstreetmap.org',
    })
  }

  if (full.includes('built-up') || full.includes('land use') || full.includes('sentinel') || full.includes('ndvi')) {
    inferred.push({
      name: 'Satellite Land Use & Land Cover (LULC)',
      category: 'Earth Observation & Remote Sensing',
      provider: 'Dynamic World / Sentinel-2 (10m)',
      query_scope: 'Multi-spectral satellite extent',
      timestamp: 'Sentinel-2 composite',
      basis_or_assumptions: '10-meter deep learning near-real-time satellite land cover classification.',
      url: 'https://dynamicworld.app',
    })
  }

  if (full.includes('route') || full.includes('corridor') || full.includes('isochrone') || full.includes('catchment')) {
    inferred.push({
      name: 'OSRM Multimodal Network Routing',
      category: 'Mobility & Transportation',
      provider: 'OSRM (Open Source Routing Machine)',
      query_scope: 'Road network graph',
      timestamp: 'Topological network',
      basis_or_assumptions: 'Dijkstra shortest path algorithm evaluated over topological road network.',
      url: 'https://project-osrm.org',
    })
  }

  return inferred
}

export function getResolvedSources(artifact: Artifact | null): SourceEntry[] {
  if (!artifact) return []
  let sources: SourceEntry[] = []
  if (artifact.meta) {
    try {
      const parsed = typeof artifact.meta === 'string' ? JSON.parse(artifact.meta) : artifact.meta
      if (Array.isArray(parsed.sources) && parsed.sources.length > 0) {
        sources = parsed.sources
      }
    } catch {
      /* ignore */
    }
  }

  // Fallback to markdown parse if not in meta
  if (sources.length === 0 && artifact.content) {
    sources = parseSourcesFromMarkdown(artifact.content)
  }

  // Fallback to text inference if still empty
  if (sources.length === 0 && artifact.content) {
    sources = inferSourcesFromText(artifact.title, artifact.content)
  }

  // Ensure all sources have their URLs resolved
  return sources.map((s) => ({
    ...s,
    url: resolveSourceUrl(s),
  }))
}

export interface SupportedFormatOption {
  fmt: string
  badge: string
  label: string
  description?: string
  category?: 'Documents & Reports' | 'Data & Spreadsheets' | 'Media & Source'
}

export function getSupportedFormats(art: Artifact | null): SupportedFormatOption[] {
  if (!art) return []
  const rawFmt = (art.format || '').toLowerCase()
  const rawType = (art.artifact_type || '').toLowerCase()
  const filePath = (art.file_path || '').toLowerCase()

  const isImg = ['image', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(rawFmt) ||
                Boolean(art.file_path && /\.(png|jpe?g|webp|gif|svg)$/i.test(art.file_path))

  // 1. Image artifacts
  if (isImg) {
    const isJpg = rawFmt === 'jpg' || rawFmt === 'jpeg' || /\.(jpe?g|jpg)$/i.test(filePath)
    return [
      { fmt: isJpg ? 'jpg' : 'png', badge: isJpg ? 'JPEG' : 'PNG', label: isJpg ? 'JPEG Image (.jpg)' : 'PNG Image (.png)', description: isJpg ? 'Compressed raster graphic' : 'Lossless raster graphic', category: 'Media & Source' },
      { fmt: isJpg ? 'png' : 'jpg', badge: isJpg ? 'PNG' : 'JPEG', label: isJpg ? 'PNG Image (.png)' : 'JPEG Image (.jpg)', description: isJpg ? 'Lossless raster graphic' : 'Compressed raster graphic', category: 'Media & Source' },
      { fmt: 'original', badge: 'RAW', label: 'Original Image', description: 'Direct image file download', category: 'Media & Source' },
    ]
  }

  // 2. Spatial GeoJSON artifacts
  if (rawFmt === 'geojson') {
    return [
      // Data & Spreadsheets
      { fmt: 'geojson', badge: 'GEOJSON', label: 'GeoJSON Dataset (.geojson)', description: 'Spatial vector features with geometry', category: 'Data & Spreadsheets' },
      { fmt: 'json', badge: 'JSON', label: 'JSON Data (.json)', description: 'Standard GeoJSON dataset object', category: 'Data & Spreadsheets' },
      // Documents & Reports
      { fmt: 'docx', badge: 'DOCX', label: 'Word Document (.docx)', description: 'Spatial summary report with map snapshot', category: 'Documents & Reports' },
      { fmt: 'pdf', badge: 'PDF', label: 'PDF Document (.pdf)', description: 'Printable map report with feature table', category: 'Documents & Reports' },
      { fmt: 'html', badge: 'HTML', label: 'HTML Web Page (.html)', description: 'Interactive standalone web export', category: 'Documents & Reports' },
      // Media & Source
      { fmt: 'png', badge: 'PNG', label: 'PNG Map Image (.png)', description: 'Lossless raster map snapshot', category: 'Media & Source' },
      { fmt: 'jpg', badge: 'JPEG', label: 'JPEG Map Image (.jpg)', description: 'Compressed raster map snapshot', category: 'Media & Source' },
      { fmt: 'txt', badge: 'TXT', label: 'Plain Text (.txt)', description: 'Raw geometry and feature attributes', category: 'Media & Source' },
    ]
  }

  // 3. Tabular data artifacts
  if (rawFmt === 'table' || rawType === 'table') {
    return [
      // Data & Spreadsheets
      { fmt: 'csv', badge: 'CSV', label: 'CSV Spreadsheet (.csv)', description: 'Comma-separated tabular dataset', category: 'Data & Spreadsheets' },
      { fmt: 'xlsx', badge: 'XLSX', label: 'Excel Workbook (.xlsx)', description: 'Formatted Microsoft Excel workbook', category: 'Data & Spreadsheets' },
      { fmt: 'json', badge: 'JSON', label: 'JSON Data (.json)', description: 'Structured JSON records array', category: 'Data & Spreadsheets' },
      // Documents & Reports
      { fmt: 'docx', badge: 'DOCX', label: 'Word Document (.docx)', description: 'Word report with formatted table', category: 'Documents & Reports' },
      { fmt: 'pdf', badge: 'PDF', label: 'PDF Document (.pdf)', description: 'Printable document with styled table', category: 'Documents & Reports' },
      { fmt: 'html', badge: 'HTML', label: 'HTML Web Page (.html)', description: 'Styled standalone web table', category: 'Documents & Reports' },
      // Media & Source
      { fmt: 'txt', badge: 'TXT', label: 'Plain Text (.txt)', description: 'ASCII aligned tabular text', category: 'Media & Source' },
      { fmt: 'md', badge: 'MD', label: 'Markdown Table (.md)', description: 'Raw Markdown table syntax', category: 'Media & Source' },
    ]
  }

  // 4. Word Document artifacts / reports / PDFs / generic markdown
  return [
    // Documents & Reports
    { fmt: 'docx', badge: 'DOCX', label: 'Word Document (.docx)', description: 'Formatted Microsoft Word report', category: 'Documents & Reports' },
    { fmt: 'pdf', badge: 'PDF', label: 'PDF Document (.pdf)', description: 'Printable high-resolution document', category: 'Documents & Reports' },
    { fmt: 'html', badge: 'HTML', label: 'HTML Web Page (.html)', description: 'Styled standalone web document', category: 'Documents & Reports' },
    // Data & Spreadsheets
    { fmt: 'xlsx', badge: 'XLSX', label: 'Excel Workbook (.xlsx)', description: 'Extracted metrics & structured tables', category: 'Data & Spreadsheets' },
    { fmt: 'json', badge: 'JSON', label: 'JSON Data (.json)', description: 'Structured document object & metadata', category: 'Data & Spreadsheets' },
    // Media & Source
    { fmt: 'png', badge: 'PNG', label: 'PNG Image (.png)', description: 'High-res visual report snapshot', category: 'Media & Source' },
    { fmt: 'jpg', badge: 'JPEG', label: 'JPEG Image (.jpg)', description: 'Compressed visual snapshot', category: 'Media & Source' },
    { fmt: 'txt', badge: 'TXT', label: 'Plain Text (.txt)', description: 'Clean unformatted plain text', category: 'Media & Source' },
    { fmt: 'md', badge: 'MD', label: 'Markdown Source (.md)', description: 'Raw Markdown syntax file', category: 'Media & Source' },
  ]
}

/** Preview-only artifact returned by GET /api/artifacts (truncated content) */
interface ArtifactPreview extends Omit<Artifact, 'content'> {
  preview: string
}

interface ArtifactsPanelProps {
  workspacePath?: string
  revision?: number
  selectedArtifactId?: number | null
  onSelectArtifactId?: (id: number | null) => void
  onAddToMap: (geojson: object, name: string) => void
  onComposeMapFigure?: (title: string, options?: { noTitleBand?: boolean }) => Promise<HTMLCanvasElement | null> | HTMLCanvasElement | null
  onFitBounds?: (bounds: { west: number; south: number; east: number; north: number }, padding?: number) => void
  showSidebar?: boolean
  sidebarWidth?: number
  onLeftResizeStart?: (e: React.MouseEvent) => void
}

export default function ArtifactsPanel({
  workspacePath,
  revision,
  selectedArtifactId,
  onSelectArtifactId,
  onAddToMap,
  onComposeMapFigure,
  onFitBounds,
  showSidebar = true,
  sidebarWidth = 260,
  onLeftResizeStart,
}: ArtifactsPanelProps) {
  const [artifacts, setArtifacts] = useState<ArtifactPreview[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(selectedArtifactId ?? null)
  const [fullArtifact, setFullArtifact] = useState<Artifact | null>(null)
  const [loadingFull, setLoadingFull] = useState(false)
  const resolvedSources = fullArtifact ? getResolvedSources(fullArtifact) : []

  // Sync external selectedArtifactId changes into selectedId state
  useEffect(() => {
    if (selectedArtifactId !== undefined && selectedArtifactId !== null) {
      setSelectedId(selectedArtifactId)
    }
  }, [selectedArtifactId])

  const containerRef = useRef<HTMLDivElement>(null)
  const [isWide, setIsWide] = useState(false)

  const draggedArtIdRef = useRef<number | null>(null)
  const [dragOverArtId, setDragOverArtId] = useState<number | null>(null)
  const [dropArtPosition, setDropArtPosition] = useState<'before' | 'after' | null>(null)
  const [editingArtId, setEditingArtId] = useState<number | null>(null)

  const handleArtDragStart = (id: number, e: React.DragEvent) => {
    draggedArtIdRef.current = id
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(id))
  }

  const handleArtDragOver = (id: number, e: React.DragEvent) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    const pos = relativeY < rect.height / 2 ? 'before' : 'after'
    setDragOverArtId(id)
    setDropArtPosition(pos)
  }

  const handleArtDragEnd = () => {
    draggedArtIdRef.current = null
    setDragOverArtId(null)
    setDropArtPosition(null)
  }

  const getUrl = useCallback((path: string = '') => {
    const base = `${API_BASE}${path}`
    if (workspacePath) {
      const sep = base.includes('?') ? '&' : '?'
      return `${base}${sep}workspace=${encodeURIComponent(workspacePath)}`
    }
    return base
  }, [workspacePath])

  const handleArtDrop = (targetId: number, e: React.DragEvent) => {
    e.preventDefault()
    const draggedIdStr = e.dataTransfer.getData('text/plain')
    const draggedId = draggedArtIdRef.current !== null ? draggedArtIdRef.current : (draggedIdStr ? Number(draggedIdStr) : null)
    if (draggedId === null || draggedId === targetId) return

    const draggedArt = artifacts.find((a) => a.id === draggedId)
    if (!draggedArt) return

    const remainingArts = artifacts.filter((a) => a.id !== draggedId)
    let insertIndex = remainingArts.findIndex((a) => a.id === targetId)
    if (insertIndex !== -1) {
      if (dropArtPosition === 'after') {
        insertIndex += 1
      }
      const newArts = [
        ...remainingArts.slice(0, insertIndex),
        draggedArt,
        ...remainingArts.slice(insertIndex),
      ]
      setArtifacts(newArts)
      
      const ids = newArts.map((a) => a.id)
      fetch(getUrl('/reorder'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order: ids }),
      }).catch(err => console.error('Failed to sync artifact order:', err))
    }
    handleArtDragEnd()
  }

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; art: ArtifactPreview } | null>(null)
  const [copiedNotification, setCopiedNotification] = useState<string | null>(null)

  // Close context menu on outside click
  useEffect(() => {
    const handleClick = () => setContextMenu(null)
    window.addEventListener('click', handleClick)
    return () => window.removeEventListener('click', handleClick)
  }, [])

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text)
    setCopiedNotification(label)
    setTimeout(() => setCopiedNotification(null), 2000)
    setContextMenu(null)
  }

  const handleItemContextMenu = (e: React.MouseEvent, art: ArtifactPreview) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ x: e.clientX, y: e.clientY, art })
  }

  const extractBbox = (art: Artifact | null): { west: number; south: number; east: number; north: number } | null => {
    if (!art) return null
    if (art.meta) {
      try {
        const parsed = JSON.parse(art.meta)
        if (Array.isArray(parsed.bbox) && parsed.bbox.length === 4) {
          return { west: parsed.bbox[0], south: parsed.bbox[1], east: parsed.bbox[2], north: parsed.bbox[3] }
        }
      } catch {}
    }
    if (art.content) {
      const trimmed = art.content.trim()
      if (trimmed.startsWith('{')) {
        try {
          const parsedGeoJSON = JSON.parse(trimmed)
          const b = turf.bbox(parsedGeoJSON)
          if (b && b.length === 4 && isFinite(b[0])) {
            return { west: b[0], south: b[1], east: b[2], north: b[3] }
          }
        } catch {}
      }
      const m1 = art.content.match(/W\s*([0-9.-]+),\s*S\s*([0-9.-]+),\s*E\s*([0-9.-]+),\s*N\s*([0-9.-]+)/i)
      if (m1) {
        return { west: parseFloat(m1[1]), south: parseFloat(m1[2]), east: parseFloat(m1[3]), north: parseFloat(m1[4]) }
      }
      const m2 = art.content.match(/\[([0-9.-]+),\s*([0-9.-]+),\s*([0-9.-]+),\s*([0-9.-]+)\]/)
      if (m2) {
        return { west: parseFloat(m2[1]), south: parseFloat(m2[2]), east: parseFloat(m2[3]), north: parseFloat(m2[4]) }
      }
    }
    return null
  }

  const handleExportWithMap = async (artId: number, targetFmt: string) => {
    try {
      const bbox = extractBbox(fullArtifact)
      if (bbox && onFitBounds) {
        onFitBounds(bbox, 90)
        // Give MapLibre a short frame tick to apply fitBounds
        await new Promise((r) => setTimeout(r, 120))
      }

      let mapImageBase64 = ''
      try {
        const figure = onComposeMapFigure
          ? await onComposeMapFigure(fullArtifact?.title || 'Map Snapshot', { noTitleBand: true })
          : null
        if (figure && typeof (figure as any).toDataURL === 'function') {
          mapImageBase64 = (figure as any).toDataURL('image/png')
        }
      } catch (figErr) {
        console.warn('Map figure could not be composed for export:', figErr)
      }

      const formData = new FormData()
      formData.append('map_image_base64', mapImageBase64)

      const url = `${API_BASE}/${artId}/export?format=${targetFmt}${workspacePath ? `&workspace=${encodeURIComponent(workspacePath)}` : ''}`
      const res = await fetch(url, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) throw new Error(`Export failed with HTTP ${res.status}`)

      const blob = await res.blob()
      const downloadUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      const safeTitle = (fullArtifact?.title || 'export').replace(/[^a-z0-9-_]/gi, '_')
      const ext = targetFmt === 'markdown' ? 'md' : targetFmt
      a.download = `${safeTitle}.${ext}`
      document.body.appendChild(a)
      a.click()
      setTimeout(() => {
        try {
          document.body.removeChild(a)
          URL.revokeObjectURL(downloadUrl)
        } catch {}
      }, 60000)
    } catch (err) {
      console.error('Failed to export artifact with map figure:', err)
      throw err
    }
  }

  // Download & Sources menu dropdown state
  const [isDownloadMenuOpen, setIsDownloadMenuOpen] = useState(false)
  const [isSourcesMenuOpen, setIsSourcesMenuOpen] = useState(false)
  const [downloadingFmt, setDownloadingFmt] = useState<string | null>(null)
  const downloadDropdownRef = useRef<HTMLDivElement>(null)
  const sourcesDropdownRef = useRef<HTMLDivElement>(null)

  // Close menus on outside click or Escape
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (downloadDropdownRef.current && !downloadDropdownRef.current.contains(target)) {
        setIsDownloadMenuOpen(false)
      }
      if (sourcesDropdownRef.current && !sourcesDropdownRef.current.contains(target)) {
        setIsSourcesMenuOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsDownloadMenuOpen(false)
        setIsSourcesMenuOpen(false)
      }
    }
    if (isDownloadMenuOpen || isSourcesMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      window.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isDownloadMenuOpen, isSourcesMenuOpen])

  // Reset dropdowns when selection changes
  useEffect(() => {
    setIsDownloadMenuOpen(false)
    setIsSourcesMenuOpen(false)
    setDownloadingFmt(null)
  }, [selectedId])

  const handleDownloadFormat = async (targetFmt: string) => {
    if (!fullArtifact) return
    setIsDownloadMenuOpen(false)
    setDownloadingFmt(targetFmt)

    const artId = fullArtifact.id
    const safeTitle = (fullArtifact.title || 'artifact').replace(/[^a-z0-9-_]/gi, '_')
    const rawFmt = (fullArtifact.format || '').toLowerCase()
    const rawType = (fullArtifact.artifact_type || '').toLowerCase()
    const filePath = (fullArtifact.file_path || '').toLowerCase()

    try {
      // 1. Direct file download: DOCX pre-compiled file on disk
      if (targetFmt === 'docx' && fullArtifact.file_path && filePath.endsWith('.docx')) {
        const downloadUrl = getUrl(`/${artId}/download`)
        const a = document.createElement('a')
        a.href = downloadUrl
        a.setAttribute('download', `${safeTitle}.docx`)
        document.body.appendChild(a)
        a.click()
        setTimeout(() => {
          try {
            document.body.removeChild(a)
          } catch {}
        }, 1500)
        setCopiedNotification('Downloaded Word Document (.docx)!')
        setTimeout(() => setCopiedNotification(null), 2500)
        return
      }

      // 2. Direct table CSV download
      if ((rawFmt === 'table' || rawType === 'table') && targetFmt === 'csv') {
        const downloadUrl = getUrl(`/${artId}/download`)
        const a = document.createElement('a')
        a.href = downloadUrl
        a.setAttribute('download', `${safeTitle}.csv`)
        document.body.appendChild(a)
        a.click()
        setTimeout(() => {
          try {
            document.body.removeChild(a)
          } catch {}
        }, 1500)
        setCopiedNotification('Downloaded CSV Spreadsheet!')
        setTimeout(() => setCopiedNotification(null), 2500)
        return
      }

      // 3. Direct GeoJSON download
      if (rawFmt === 'geojson' && targetFmt === 'geojson') {
        const downloadUrl = getUrl(`/${artId}/download`)
        const a = document.createElement('a')
        a.href = downloadUrl
        a.setAttribute('download', `${safeTitle}.geojson`)
        document.body.appendChild(a)
        a.click()
        setTimeout(() => {
          try {
            document.body.removeChild(a)
          } catch {}
        }, 1500)
        setCopiedNotification('Downloaded GeoJSON!')
        setTimeout(() => setCopiedNotification(null), 2500)
        return
      }

      // 4. Image direct download
      const isImg = ['image', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(rawFmt) ||
                    Boolean(fullArtifact.file_path && /\.(png|jpe?g|webp|gif|svg)$/i.test(fullArtifact.file_path))

      if (isImg && (targetFmt === 'jpg' || targetFmt === 'jpeg' || targetFmt === 'png' || targetFmt === 'original')) {
        const downloadUrl = getUrl(`/${artId}/download`)
        const a = document.createElement('a')
        a.href = downloadUrl
        const ext = targetFmt === 'original' ? (fullArtifact.file_path?.split('.').pop() || 'png') : targetFmt
        a.setAttribute('download', `${safeTitle}.${ext}`)
        document.body.appendChild(a)
        a.click()
        setTimeout(() => {
          try {
            document.body.removeChild(a)
          } catch {}
        }, 1500)
        setCopiedNotification(`Downloaded ${ext.toUpperCase()} Image!`)
        setTimeout(() => setCopiedNotification(null), 2500)
        return
      }

      // 5. Raw Markdown download
      if (targetFmt === 'md' || targetFmt === 'markdown') {
        const downloadUrl = getUrl(`/${artId}/download`)
        const a = document.createElement('a')
        a.href = downloadUrl
        a.setAttribute('download', `${safeTitle}.md`)
        document.body.appendChild(a)
        a.click()
        setTimeout(() => {
          try {
            document.body.removeChild(a)
          } catch {}
        }, 1500)
        setCopiedNotification('Downloaded Markdown (.md)!')
        setTimeout(() => setCopiedNotification(null), 2500)
        return
      }

      // 6. Multi-format export pipeline (PDF, DOCX generation, etc.)
      await handleExportWithMap(artId, targetFmt)
      setCopiedNotification(`Downloaded ${targetFmt.toUpperCase()}!`)
      setTimeout(() => setCopiedNotification(null), 2500)
    } catch (err) {
      console.error(`Download failed for format ${targetFmt}:`, err)
    } finally {
      setDownloadingFmt(null)
    }
  }

  useEffect(() => {
    if (!containerRef.current) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setIsWide(entry.contentRect.width >= 580)
      }
    })
    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  // Create-form state
  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [artifactType, setArtifactType] = useState('note')
  const [format, setFormat] = useState<'markdown' | 'table' | 'geojson'>('markdown')

  // Edit state
  const [editingContent, setEditingContent] = useState(false)
  const [editContentValue, setEditContentValue] = useState('')

  const fetchArtifacts = useCallback(async () => {
    // With no workspace selected, load the global artifact store. Chat-created
    // reports can exist there and must remain openable from their artifact chip.
    try {
      const res = await fetch(getUrl())
      if (res.ok) {
        const data = await res.json()
        setArtifacts(data)
      }
    } catch {
      /* backend may not be available */
    }
  }, [getUrl, workspacePath])

  useEffect(() => {
    fetchArtifacts()
  }, [fetchArtifacts])

  useEffect(() => {
    if (revision !== undefined && revision > 0) fetchArtifacts()
  }, [revision, fetchArtifacts])

  // Fetch full artifact when selection changes
  useEffect(() => {
    if (selectedId === null) {
      setFullArtifact(null)
      setEditingContent(false)
      return
    }
    const controller = new AbortController()
    setLoadingFull(true)
    fetch(getUrl(`/${selectedId}`), { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Artifact | null) => {
        if (data) setFullArtifact(data)
        setLoadingFull(false)
        setEditingContent(false)
      })
      .catch(() => setLoadingFull(false))
    return () => controller.abort()
  }, [selectedId, getUrl])

  const createArtifact = async (): Promise<void> => {
    if (!title.trim()) return
    try {
      const res = await fetch(getUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, artifact_type: artifactType, format }),
      })
      if (res.ok) {
        setTitle('')
        setContent('')
        setShowForm(false)
        fetchArtifacts()
      }
    } catch {
      /* backend may not be available */
    }
  }

  const deleteArtifact = async (id: number): Promise<void> => {
    try {
      await fetch(getUrl(`/${id}`), { method: 'DELETE' })
      if (selectedId === id) setSelectedId(null)
      fetchArtifacts()
    } catch {
      /* backend may not be available */
    }
  }

  const saveTitle = async (id: number, newTitle: string): Promise<void> => {
    if (!newTitle.trim()) return
    try {
      await fetch(getUrl(`/${id}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle }),
      })
      fetchArtifacts()
      if (fullArtifact && fullArtifact.id === id) {
        setFullArtifact((prev) => (prev ? { ...prev, title: newTitle } : null))
      }
    } catch {
      /* backend may not be available */
    }
  }

  const saveContent = async (): Promise<void> => {
    if (!fullArtifact) return
    try {
      await fetch(getUrl(`/${fullArtifact.id}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContentValue }),
      })
      setEditingContent(false)
      setFullArtifact((prev) => (prev ? { ...prev, content: editContentValue } : null))
      fetchArtifacts()
    } catch {
      /* backend may not be available */
    }
  }

  const handleToggleSelect = (id: number): void => {
    const next = selectedId === id ? null : id
    setSelectedId(next)
    onSelectArtifactId?.(next)
  }



  // ── Format-aware detail renderer ──

  const renderDetail = (artifact: Artifact): React.ReactNode => {
    const { id, title: aTitle, format: fmt, content, meta } = artifact

    if (fmt === 'markdown') {
      return (
        <div className="artifact-detail">
          {editingContent ? (
            <>
              <textarea
                className="artifact-edit-area"
                value={editContentValue}
                onChange={(e) => setEditContentValue(e.target.value)}
              />
              <div className="artifact-actions">
                <button className="save-btn" onClick={saveContent}>Save</button>
                <button className="cancel-btn" onClick={() => setEditingContent(false)}>Cancel</button>
              </div>
            </>
          ) : (
            <div className="artifact-detail-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={{
                  ...headingComponents,
                  img: ({ src, alt, ...props }) => {
                    let resolvedSrc = src || ''
                    if (
                      resolvedSrc.startsWith('artifacts_store/') ||
                      resolvedSrc.startsWith('artifacts_store\\') ||
                      resolvedSrc.startsWith('artifacts_store')
                    ) {
                      const filename = resolvedSrc.replace(/\\/g, '/').split('/').pop() || ''
                      const idMatch = filename.match(/^(\d+)\./)
                      if (idMatch) {
                        resolvedSrc = `${API_BASE}/${idMatch[1]}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
                      }
                    } else if (!resolvedSrc.startsWith('http://') && !resolvedSrc.startsWith('https://') && !resolvedSrc.startsWith('data:')) {
                      const numMatch = resolvedSrc.match(/^(\d+)(\.\w+)?$/)
                      if (numMatch) {
                        resolvedSrc = `${API_BASE}/${numMatch[1]}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
                      } else {
                        const target = (resolvedSrc || alt || '').trim().toLowerCase()
                        const found = artifacts.find((a) => {
                          const atitle = (a.title || '').trim().toLowerCase()
                          if (!atitle) return false
                          return (
                            atitle === target ||
                            (alt && atitle === alt.trim().toLowerCase()) ||
                            (target.length > 2 && atitle.includes(target)) ||
                            (alt && alt.length > 2 && atitle.includes(alt.trim().toLowerCase())) ||
                            (target.length > 2 && target.includes(atitle)) ||
                            (alt && alt.length > 2 && alt.trim().toLowerCase().includes(atitle))
                          )
                        })
                        if (found) {
                          resolvedSrc = `${API_BASE}/${found.id}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
                        }
                      }
                    }
                    return (
                      <div className="figure-container" style={{ textAlign: 'center', margin: '16px 0' }}>
                        <img
                          src={resolvedSrc}
                          alt={alt || 'Figure'}
                          className="map-img"
                          style={{ maxWidth: '100%', height: 'auto', borderRadius: 8, border: '1px solid #334155' }}
                          {...props}
                        />
                        {alt && <p className="caption" style={{ fontSize: '0.85rem', color: '#94a3b8', fontStyle: 'italic', marginTop: 6 }}>Figure: {alt}</p>}
                      </div>
                    )
                  },
                  a: ({ href, children, ...props }) => (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="artifact-markdown-link"
                      onClick={(e) => {
                        if (href && (window as any).electronAPI?.openExternal) {
                          e.preventDefault()
                          ;(window as any).electronAPI.openExternal(href)
                        }
                      }}
                      {...props}
                    >
                      {children}
                    </a>
                  ),
                }}
              >
                {content}
              </ReactMarkdown>
            </div>
          )}
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    if (fmt === 'table') {
      let tableData: { columns: string[]; rows: unknown[][] } | null = null
      try {
        tableData = JSON.parse(content)
      } catch {
        /* malformed content */
      }

      return (
        <div className="artifact-detail">
          {editingContent ? (
            <>
              <textarea
                className="artifact-edit-area"
                value={editContentValue}
                onChange={(e) => setEditContentValue(e.target.value)}
              />
              <div className="artifact-actions">
                <button className="save-btn" onClick={saveContent}>Save</button>
                <button className="cancel-btn" onClick={() => setEditingContent(false)}>Cancel</button>
              </div>
            </>
          ) : (
            tableData ? (
              <div className="artifact-table-wrapper">
                <table className="artifact-table">
                  <thead>
                    <tr>
                      {tableData.columns.map((col, i) => (
                        <th key={i}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td key={ci}>{String(cell ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="artifact-geojson-summary">Invalid table data</p>
            )
          )}
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    const isImageFormat = ['image', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(fmt.toLowerCase()) || 
                          Boolean(artifact.file_path && /\.(png|jpe?g|webp|gif|svg)$/i.test(artifact.file_path))

    if (isImageFormat) {
      const downloadUrl = getUrl(`/${id}/download`)
      return (
        <div className="artifact-detail">
          <img
             className="artifact-image-thumb"
             src={downloadUrl}
             alt={aTitle}
             onClick={() => window.open(downloadUrl, '_blank')}
          />
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    if (fmt === 'geojson') {
      let featureCount: number | null = null
      let bbox: string | null = null
      if (meta) {
        try {
          const parsed = JSON.parse(meta)
          featureCount = parsed.feature_count ?? null
          bbox = parsed.bbox ? JSON.stringify(parsed.bbox) : null
        } catch {
          /* ignore */
        }
      }
      return (
        <div className="artifact-detail">
          <p className="artifact-geojson-summary">
            {featureCount !== null ? `${featureCount} feature(s)` : 'GeoJSON'}
            {bbox ? ` · bbox: ${bbox}` : ''}
          </p>
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }
    // PDF, DOCX, HTML, XLSX, TXT, JSON and fallback formats
    return (
      <div className="artifact-detail">
        <div className="artifact-detail-markdown">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{
              ...headingComponents,
              img: ({ src, alt, ...props }) => {
                let resolvedSrc = src || ''
                if (
                  resolvedSrc.startsWith('artifacts_store/') ||
                  resolvedSrc.startsWith('artifacts_store\\') ||
                  resolvedSrc.startsWith('artifacts_store')
                ) {
                  const filename = resolvedSrc.replace(/\\/g, '/').split('/').pop() || ''
                  const idMatch = filename.match(/^(\d+)\./)
                  if (idMatch) {
                    resolvedSrc = `${API_BASE}/${idMatch[1]}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
                  }
                } else if (!resolvedSrc.startsWith('http://') && !resolvedSrc.startsWith('https://') && !resolvedSrc.startsWith('data:')) {
                  const numMatch = resolvedSrc.match(/^(\d+)(\.\w+)?$/)
                  if (numMatch) {
                    resolvedSrc = `${API_BASE}/${numMatch[1]}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
                  } else {
                    const target = (resolvedSrc || alt || '').trim().toLowerCase()
                    const found = artifacts.find((a) => {
                      const atitle = (a.title || '').trim().toLowerCase()
                      if (!atitle) return false
                      return (
                        atitle === target ||
                        (alt && atitle === alt.trim().toLowerCase()) ||
                        (target.length > 2 && atitle.includes(target)) ||
                        (alt && alt.length > 2 && atitle.includes(alt.trim().toLowerCase())) ||
                        (target.length > 2 && target.includes(atitle)) ||
                        (alt && alt.length > 2 && alt.trim().toLowerCase().includes(atitle))
                      )
                    })
                    if (found) {
                      resolvedSrc = `${API_BASE}/${found.id}/download${workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''}`
                    }
                  }
                }
                return (
                  <div className="figure-container" style={{ textAlign: 'center', margin: '16px 0' }}>
                    <img
                      src={resolvedSrc}
                      alt={alt || 'Figure'}
                      className="map-img"
                      style={{ maxWidth: '100%', height: 'auto', borderRadius: 8, border: '1px solid #334155' }}
                      {...props}
                    />
                    {alt && <p className="caption" style={{ fontSize: '0.85rem', color: '#94a3b8', fontStyle: 'italic', marginTop: 6 }}>Figure: {alt}</p>}
                  </div>
                )
              },
              a: ({ href, children, ...props }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="artifact-markdown-link"
                  onClick={(e) => {
                    if (href && (window as any).electronAPI?.openExternal) {
                      e.preventDefault()
                      ;(window as any).electronAPI.openExternal(href)
                    }
                  }}
                  {...props}
                >
                  {children}
                </a>
              ),
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
        <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
      </div>
    )
  }

  const shouldShowSidebar = showSidebar || !isWide

  return (
    <div ref={containerRef} className={`artifacts-panel ${isWide ? 'wide' : ''}`}>
      {shouldShowSidebar && (
        <div className="artifacts-sidebar" style={isWide ? { width: sidebarWidth, flex: `0 0 ${sidebarWidth}px` } : undefined}>
          <div className="artifacts-toolbar">
            <button className="new-artifact-btn" onClick={() => setShowForm(!showForm)}>
              {showForm ? 'Cancel' : '+ New Artifact'}
            </button>
            <button className="refresh-btn" onClick={fetchArtifacts} style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
            </button>
          </div>

          {showForm && (
            <div className="artifact-form">
              <input
                className="artifact-input"
                placeholder="Title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <select
                className="artifact-select"
                value={artifactType}
                onChange={(e) => setArtifactType(e.target.value)}
              >
                <option value="note">Note</option>
                <option value="analysis">Analysis</option>
                <option value="report">Report</option>
                <option value="sketch">Sketch</option>
              </select>
              <select
                className="artifact-select"
                value={format}
                onChange={(e) => setFormat(e.target.value as any)}
              >
                <option value="pdf">PDF Document</option>
                <option value="docx">Word Document (.docx)</option>
                <option value="markdown">Markdown</option>
                <option value="png">PNG Image</option>
                <option value="jpeg">JPEG Image</option>
                <option value="html">HTML Report</option>
                <option value="xlsx">Excel Sheet (.xlsx)</option>
                <option value="table">Table (CSV/JSON)</option>
                <option value="geojson">GeoJSON</option>
                <option value="json">JSON</option>
                <option value="txt">Plain Text</option>
              </select>
              <textarea
                className="artifact-textarea"
                placeholder="Content..."
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={4}
              />
              <button className="save-btn" onClick={createArtifact}>
                Save
              </button>
            </div>
          )}

          <div className="artifacts-list">
            {artifacts.length === 0 && !showForm && (
              <div className="artifacts-empty">
                <div className="empty-icon-container-sm">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="16" y1="13" x2="8" y2="13"></line>
                    <line x1="16" y1="17" x2="8" y2="17"></line>
                    <polyline points="10 9 9 9 8 9"></polyline>
                  </svg>
                </div>
                <p className="title">No artifacts yet</p>
                <p className="hint">Save notes, analyses, and reports here.</p>
              </div>
            )}
            {artifacts.map((a) => {
              const fmtRaw = (a.format || a.artifact_type || 'note').toLowerCase()
              let badge = fmtRaw.toUpperCase()
              if (fmtRaw === 'jpg' || fmtRaw === 'jpeg') badge = 'JPEG'
              else if (fmtRaw === 'png') badge = 'PNG'
              else if (fmtRaw === 'markdown' || fmtRaw === 'md') badge = 'MD'
              else if (fmtRaw === 'geojson') badge = 'GEOJSON'
              else if (fmtRaw === 'docx') badge = 'DOCX'
              else if (fmtRaw === 'pdf') badge = 'PDF'
              else if (fmtRaw === 'table') badge = 'TABLE'
              else if (fmtRaw === 'xlsx') badge = 'EXCEL'

              return (
                <div
                  key={a.id}
                  className={`artifact-item ${selectedId === a.id ? 'selected' : ''} ${dragOverArtId === a.id ? `drag-over-${dropArtPosition}` : ''}`}
                  onClick={() => handleToggleSelect(a.id)}
                  onContextMenu={(e) => handleItemContextMenu(e, a)}
                  draggable={true}
                  onDragStart={(e) => handleArtDragStart(a.id, e)}
                  onDragOver={(e) => handleArtDragOver(a.id, e)}
                  onDrop={(e) => handleArtDrop(a.id, e)}
                  onDragEnd={handleArtDragEnd}
                  style={{ cursor: 'grab' }}
                >
                  <div className="artifact-item-header">
                    <span className="artifact-type-badge">{badge}</span>
                  {editingArtId === a.id ? (
                    <input
                      type="text"
                      className="artifact-title-input"
                      value={a.title}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        const val = e.target.value
                        setArtifacts((prev) =>
                          prev.map((art) => (art.id === a.id ? { ...art, title: val } : art)),
                        )
                      }}
                      onBlur={() => {
                        saveTitle(a.id, a.title)
                        setEditingArtId(null)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          (e.target as HTMLInputElement).blur()
                        }
                      }}
                      autoFocus
                      title="Rename artifact"
                    />
                  ) : (
                    <span
                      className="artifact-title-span"
                      title={a.title}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        setEditingArtId(a.id)
                      }}
                    >
                      {a.title}
                    </span>
                  )}
                  <button
                    className="delete-btn"
                    title="Delete"
                    onClick={(e) => {
                      e.stopPropagation()
                      deleteArtifact(a.id)
                    }}
                  >
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                </div>
                {!isWide && selectedId === a.id && (
                  loadingFull ? (
                    <div className="artifact-detail">
                      <p className="artifact-geojson-summary">Loading…</p>
                    </div>
                  ) : fullArtifact && fullArtifact.id === a.id ? (
                    renderDetail(fullArtifact)
                  ) : null
                )}
              </div>
            )})}
          </div>
        </div>
      )}

      {shouldShowSidebar && isWide && onLeftResizeStart && (
        <div className="resize-handle" onMouseDown={onLeftResizeStart} />
      )}

      {isWide && (
        <div className="artifacts-detail-pane">
          {selectedId === null ? (
            <div className="artifacts-empty-detail">
              <div className="artifacts-empty-detail-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="16" y1="13" x2="8" y2="13"></line>
                  <line x1="16" y1="17" x2="8" y2="17"></line>
                  <polyline points="10 9 9 9 8 9"></polyline>
                </svg>
              </div>
              <p className="artifacts-empty-detail-title">Select an artifact to view its contents</p>
              <p className="artifacts-empty-detail-hint">View reports, maps, analyses, and tables in full page width.</p>
            </div>
          ) : loadingFull ? (
            <div className="artifacts-detail-loading" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="spinning" style={{ marginRight: 6 }}>
                <path d="M23 4v6h-6"></path>
                <path d="M1 20v-6h6"></path>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
              Loading artifact contents...
            </div>
          ) : fullArtifact && fullArtifact.id === selectedId ? (
            <div className="artifacts-detail-content">
              <div className="artifacts-detail-header">
                <h2 className="artifacts-detail-title" title={fullArtifact.title}>{fullArtifact.title}</h2>
                <div className="artifacts-detail-header-actions">
                  <span className="artifacts-detail-badge">
                    {fullArtifact.file_path && /\.(jpe?g|jpg)$/i.test(fullArtifact.file_path)
                      ? 'JPEG'
                      : fullArtifact.format === 'jpg' || fullArtifact.format === 'jpeg'
                      ? 'JPEG'
                      : (fullArtifact.format ?? fullArtifact.artifact_type ?? 'PNG').toUpperCase()}
                  </span>

                  {/* Edit button in header */}
                  {!editingContent &&
                    (fullArtifact.format === 'markdown' ||
                      fullArtifact.format === 'table' ||
                      !fullArtifact.format ||
                      fullArtifact.artifact_type === 'note' ||
                      fullArtifact.artifact_type === 'report') && (
                      <button
                        className="artifact-header-action-btn edit-header-btn"
                        onClick={() => {
                          setEditContentValue(fullArtifact.content)
                          setEditingContent(true)
                        }}
                        title="Edit artifact content"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M12 20h9"></path>
                          <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                        </svg>
                        <span>Edit</span>
                      </button>
                    )}

                  {/* Add to map button for GeoJSON */}
                  {fullArtifact.format === 'geojson' && (
                    <button
                      className="artifact-header-action-btn add-to-map-header-btn"
                      onClick={() => {
                        try {
                          const geojson = JSON.parse(fullArtifact.content)
                          onAddToMap(geojson, fullArtifact.title)
                        } catch {
                          console.error('Invalid GeoJSON content')
                        }
                      }}
                      title="Add GeoJSON layers to interactive map"
                    >
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                        <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
                        <line x1="8" y1="2" x2="8" y2="18" />
                        <line x1="16" y1="6" x2="16" y2="22" />
                      </svg>
                      <span>Add to map</span>
                    </button>
                  )}

                  {/* Sources dropdown button */}
                  {resolvedSources.length > 0 && (
                    <div className="artifact-sources-dropdown-container" ref={sourcesDropdownRef}>
                      <button
                        className={`artifact-header-sources-btn ${isSourcesMenuOpen ? 'active' : ''}`}
                        onClick={() => {
                          setIsSourcesMenuOpen((prev) => !prev)
                          setIsDownloadMenuOpen(false)
                        }}
                        title="View data sources and analytical provenance"
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path>
                          <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path>
                        </svg>
                        <span>Sources</span>
                        <span className="sources-header-badge">{resolvedSources.length}</span>
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          style={{
                            transform: isSourcesMenuOpen ? 'rotate(180deg)' : 'none',
                            transition: 'transform 0.15s ease',
                            opacity: 0.8,
                          }}
                        >
                          <polyline points="6 9 12 15 18 9"></polyline>
                        </svg>
                      </button>

                      {isSourcesMenuOpen && (
                        <div className="artifact-sources-menu">
                          <div className="artifact-sources-menu-header">
                            <div className="sources-menu-header-title">
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                              </svg>
                              <span>Data Sources & Provenance</span>
                            </div>
                            <span className="sources-menu-count">{resolvedSources.length} {resolvedSources.length === 1 ? 'Source' : 'Sources'}</span>
                          </div>
                          <div className="artifact-sources-menu-list">
                            {resolvedSources.map((s, idx) => (
                              <div key={idx} className="artifact-source-card-item">
                                <div className="source-card-top">
                                  <span className="source-card-category">{s.category || 'Data Source'}</span>
                                  <span className="source-card-name" title={s.name}>{s.name}</span>
                                  {s.url && (
                                    <a
                                      href={s.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="source-card-link-btn"
                                      title={`Open documentation for ${s.name}`}
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <span>View Docs</span>
                                      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                                        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                        <polyline points="15 3 21 3 21 9"></polyline>
                                        <line x1="10" y1="14" x2="21" y2="3"></line>
                                      </svg>
                                    </a>
                                  )}
                                </div>
                                {s.provider && (
                                  <div className="source-card-field">
                                    <span className="source-card-label">Provider:</span>
                                    <span className="source-card-value">{s.provider}</span>
                                  </div>
                                )}
                                {s.query_scope && (
                                  <div className="source-card-field">
                                    <span className="source-card-label">Scope:</span>
                                    <span className="source-card-value">{s.query_scope}</span>
                                  </div>
                                )}
                                {s.basis_or_assumptions && (
                                  <div className="source-card-field">
                                    <span className="source-card-label">Basis:</span>
                                    <span className="source-card-value">{s.basis_or_assumptions}</span>
                                  </div>
                                )}
                                {s.timestamp && (
                                  <div className="source-card-field">
                                    <span className="source-card-label">Date/Time:</span>
                                    <span className="source-card-value">{s.timestamp}</span>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Download dropdown */}
                  <div className="artifact-download-dropdown-container" ref={downloadDropdownRef}>
                    <button
                      className={`artifact-header-download-btn ${isDownloadMenuOpen ? 'active' : ''}`}
                      onClick={() => {
                        setIsDownloadMenuOpen((prev) => !prev)
                        setIsSourcesMenuOpen(false)
                      }}
                      disabled={Boolean(downloadingFmt)}
                      title="Download artifact in supported formats"
                    >
                      {downloadingFmt ? (
                        <>
                          <svg className="spinning" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <path d="M23 4v6h-6"></path>
                            <path d="M1 20v-6h6"></path>
                            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
                          </svg>
                          <span>Exporting...</span>
                        </>
                      ) : (
                        <>
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                            <polyline points="7 10 12 15 17 10"></polyline>
                            <line x1="12" y1="15" x2="12" y2="3"></line>
                          </svg>
                          <span>Download</span>
                          <svg
                            width="10"
                            height="10"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.5"
                            style={{
                              transform: isDownloadMenuOpen ? 'rotate(180deg)' : 'none',
                              transition: 'transform 0.15s ease',
                              opacity: 0.8,
                            }}
                          >
                            <polyline points="6 9 12 15 18 9"></polyline>
                          </svg>
                        </>
                      )}
                    </button>

                    {isDownloadMenuOpen && (
                      <div className="artifact-download-menu">
                        {(() => {
                          const supportedFormats = getSupportedFormats(fullArtifact)
                          const categories = Array.from(new Set(supportedFormats.map((f) => f.category || 'Supported Formats')))
                          return categories.map((category) => (
                            <div key={category} className="artifact-download-menu-section">
                              <div className="artifact-download-menu-header">{category}</div>
                              {supportedFormats
                                .filter((f) => (f.category || 'Supported Formats') === category)
                                .map((opt) => (
                                  <button
                                    key={opt.fmt}
                                    className="artifact-download-menu-item"
                                    onClick={() => handleDownloadFormat(opt.fmt)}
                                  >
                                    <span className="format-badge-mini">{opt.badge}</span>
                                    <div className="format-info">
                                      <span className="format-label">{opt.label}</span>
                                      {opt.description && <span className="format-desc">{opt.description}</span>}
                                    </div>
                                    <svg className="download-arrow" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                      <polyline points="7 10 12 15 17 10"></polyline>
                                      <line x1="12" y1="15" x2="12" y2="3"></line>
                                    </svg>
                                  </button>
                                ))}
                            </div>
                          ))
                        })()}
                      </div>
                    )}
                  </div>
                </div>
              </div>
              {renderDetail(fullArtifact)}
            </div>
          ) : null}
        </div>
      )}

      {/* Context Menu Popup Dialog */}
      {contextMenu && (
        <div
          className="artifact-context-menu"
          style={{ top: contextMenu.y, left: contextMenu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          <div
            className="context-menu-item"
            onClick={() => {
              setEditingArtId(contextMenu.art.id)
              setContextMenu(null)
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 20h9"></path>
              <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
            </svg>
            Rename...
            <span className="context-menu-shortcut">F2</span>
          </div>

          <div className="context-menu-divider" />

          <div
            className="context-menu-item"
            onClick={() => copyToClipboard(contextMenu.art.title, 'Title copied!')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            Copy Name / Title
          </div>

          <div
            className="context-menu-item"
            onClick={() => copyToClipboard(String(contextMenu.art.id), 'ID copied!')}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="4" y1="9" x2="20" y2="9"></line>
              <line x1="4" y1="15" x2="20" y2="15"></line>
              <line x1="10" y1="3" x2="8" y2="21"></line>
              <line x1="16" y1="3" x2="14" y2="21"></line>
            </svg>
            Copy Artifact ID (e.g. {contextMenu.art.id})
          </div>

          <div
            className="context-menu-item"
            onClick={() => {
              const ext = contextMenu.art.file_path ? contextMenu.art.file_path.split('.').pop() : (contextMenu.art.format || 'docx')
              copyToClipboard(`artifacts_store/${contextMenu.art.id}.${ext}`, 'Relative path copied!')
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path>
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>
            </svg>
            Copy Relative Path
            <span className="context-menu-shortcut">Ctrl+Shift+C</span>
          </div>

          <div
            className="context-menu-item"
            onClick={() => {
              const fullPath = contextMenu.art.file_path || `${workspacePath || ''}/artifacts_store/${contextMenu.art.id}.${contextMenu.art.format || 'docx'}`
              copyToClipboard(fullPath, 'Full path copied!')
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
            Copy Path
            <span className="context-menu-shortcut">Shift+Alt+C</span>
          </div>

          <div className="context-menu-divider" />

          <div
            className="context-menu-item danger"
            onClick={() => {
              deleteArtifact(contextMenu.art.id)
              setContextMenu(null)
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
            Delete
            <span className="context-menu-shortcut">Del</span>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {copiedNotification && (
        <div className="artifact-toast-notification">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
          {copiedNotification}
        </div>
      )}
    </div>
  )
}
