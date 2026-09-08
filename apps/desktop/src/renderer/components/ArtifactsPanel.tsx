import { useState, useEffect, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import { Artifact } from '../types'
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
  onComposeMapFigure?: (title: string, options?: { noTitleBand?: boolean }) => HTMLCanvasElement | null
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

      const figure = onComposeMapFigure?.(fullArtifact?.title || 'Map Snapshot', { noTitleBand: true })
      let mapImageBase64 = ''
      if (figure) {
        mapImageBase64 = figure.toDataURL('image/png')
      }

      const formData = new FormData()
      formData.append('map_image_base64', mapImageBase64)

      const url = `${API_BASE}/${artId}/export?format=${targetFmt}${workspacePath ? `&workspace=${encodeURIComponent(workspacePath)}` : ''}`
      const res = await fetch(url, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) throw new Error('Export failed')

      const blob = await res.blob()
      const downloadUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      const safeTitle = (fullArtifact?.title || 'export').replace(/[^a-z0-9-_]/gi, '_')
      a.download = `${safeTitle}.${targetFmt}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(downloadUrl)
    } catch (err) {
      console.error('Failed to export artifact with map figure:', err)
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
    // When no workspace is open, clear immediately without hitting the API.
    // This prevents the race where getUrl() changes (workspace removed from URL)
    // and a global fetch repopulates the list just after setArtifacts([]) cleared it.
    if (!workspacePath) {
      setArtifacts([])
      setSelectedId(null)
      setFullArtifact(null)
      setEditingContent(false)
      return
    }
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
            <>
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
                  }}
                >
                  {content}
                </ReactMarkdown>
              </div>
              <div className="artifact-actions">
                <button
                  className="edit-btn"
                  onClick={() => { setEditContentValue(content); setEditingContent(true) }}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M12 20h9"></path>
                    <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path>
                  </svg>
                  Edit
                </button>
                <button
                  className="download-btn docx-btn"
                  onClick={() => handleExportWithMap(id, 'docx')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  Word (.docx)
                </button>
                <button
                  className="download-btn pdf-btn"
                  onClick={() => handleExportWithMap(id, 'pdf')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                  PDF
                </button>
                <button
                  className="download-btn html-btn"
                  onClick={() => handleExportWithMap(id, 'html')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <polyline points="16 18 22 12 16 6"></polyline>
                    <polyline points="8 6 2 12 8 18"></polyline>
                  </svg>
                  HTML
                </button>
                <button
                  className="download-btn xlsx-btn"
                  onClick={() => handleExportWithMap(id, 'xlsx')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 4 }}>
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="3" y1="9" x2="21" y2="9"></line>
                    <line x1="9" y1="21" x2="9" y2="9"></line>
                  </svg>
                  Excel (.xlsx)
                </button>
                <button
                  className="download-btn txt-btn"
                  onClick={() => handleExportWithMap(id, 'txt')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  TXT
                </button>
                <button
                  className="download-btn png-btn"
                  onClick={() => handleExportWithMap(id, 'png')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  PNG Image
                </button>
                <button
                  className="download-btn jpg-btn"
                  onClick={() => handleExportWithMap(id, 'jpg')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  JPEG Image
                </button>
                <button
                  className="download-btn json-btn"
                  onClick={() => handleExportWithMap(id, 'json')}
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  JSON
                </button>
                <a
                  className="download-btn markdown-btn"
                  href={getUrl(`/${id}/download`)}
                  download
                  style={{ display: 'inline-flex', alignItems: 'center' }}
                >
                  Markdown
                </a>
              </div>

            </>
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
            <>
              {tableData ? (
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
              )}
              <div className="artifact-actions">
                <button
                  className="edit-btn"
                  onClick={() => { setEditContentValue(content); setEditingContent(true) }}
                >
                  Edit
                </button>
                <a
                  className="download-btn"
                  href={getUrl(`/${id}/download`)}
                  download
                >
                  Download
                </a>
              </div>
            </>
          )}
          <span className="artifact-date">{new Date(artifact.created_at).toLocaleDateString()}</span>
        </div>
      )
    }

    const isImageFormat = ['image', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(fmt.toLowerCase()) || 
                          Boolean(artifact.file_path && /\.(png|jpe?g|webp|gif|svg)$/i.test(artifact.file_path))

    if (isImageFormat) {
      const downloadUrl = getUrl(`/${id}/download`)
      const fileExt = artifact.file_path
        ? artifact.file_path.split('.').pop()?.toLowerCase() || 'png'
        : (fmt === 'jpg' || fmt === 'jpeg' ? 'jpg' : (fmt === 'image' ? 'png' : fmt.toLowerCase()))
      const isJpg = fileExt === 'jpg' || fileExt === 'jpeg' || fmt.toLowerCase() === 'jpg' || fmt.toLowerCase() === 'jpeg'
      const displayFmt = isJpg ? 'JPEG' : (fileExt || fmt || 'PNG').toUpperCase()
      return (
        <div className="artifact-detail">
          <img
             className="artifact-image-thumb"
             src={downloadUrl}
             alt={aTitle}
             onClick={() => window.open(downloadUrl, '_blank')}
          />
          <div className="artifact-actions">
            <a className="download-btn" href={downloadUrl} download={`${aTitle.replace(/[^a-z0-9-_]/gi, '_')}.${isJpg ? 'jpg' : fileExt}`}>
              Download {displayFmt}
            </a>
          </div>
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
          <div className="artifact-actions">
            <button
              className="add-to-map-btn"
              onClick={() => {
                try {
                  const geojson = JSON.parse(fullArtifact!.content)
                  onAddToMap(geojson, fullArtifact!.title)
                } catch {
                  console.error('Invalid GeoJSON content')
                }
              }}
            >
              Add to map
            </button>
            <a className="download-btn" href={getUrl(`/${id}/download`)} download>
              Download
            </a>
          </div>
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
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
        <div className="artifact-actions" style={{ marginTop: 16, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {artifact.file_path && (
            <a
              className="download-btn"
              href={getUrl(`/${id}/download`)}
              download
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 14px', fontSize: '0.85rem', fontWeight: 600, borderRadius: 6, background: '#1e40af', color: '#ffffff', textDecoration: 'none' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              Download {fmt.toUpperCase()} File
            </a>
          )}
          <button
            className="download-btn pdf-btn"
            onClick={() => handleExportWithMap(id, 'pdf')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 14px', fontSize: '0.85rem', fontWeight: 600, borderRadius: 6, background: '#3b82f6', color: '#ffffff', border: 'none', cursor: 'pointer' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Export PDF
          </button>
          <button
            className="download-btn docx-btn"
            onClick={() => handleExportWithMap(id, 'docx')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 14px', fontSize: '0.85rem', fontWeight: 600, borderRadius: 6, background: '#2563eb', color: '#ffffff', border: 'none', cursor: 'pointer' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
              <polyline points="14 2 14 8 20 8"></polyline>
              <line x1="16" y1="13" x2="8" y2="13"></line>
              <line x1="16" y1="17" x2="8" y2="17"></line>
            </svg>
            Export Word (.docx)
          </button>
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
                <h2 className="artifacts-detail-title">{fullArtifact.title}</h2>
                <span className="artifacts-detail-badge">
                  {fullArtifact.file_path && /\.(jpe?g|jpg)$/i.test(fullArtifact.file_path)
                    ? 'JPEG'
                    : fullArtifact.format === 'jpg' || fullArtifact.format === 'jpeg'
                    ? 'JPEG'
                    : (fullArtifact.format ?? fullArtifact.artifact_type ?? 'PNG').toUpperCase()}
                </span>
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
