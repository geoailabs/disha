import { useState, useRef, useEffect } from 'react'
import './DocumentView.css'
import { IMAGE_EXTS, MIME_MAP, rasterizePdfPage } from '../lib/pdf-raster'

export interface DocumentImage {
  base64: string
  mimeType: string
  fileName: string
  filePath?: string
  /** For multi-page sources, the page number that was rasterized (1-indexed). */
  page?: number
  /** For multi-page sources, the total number of pages. */
  totalPages?: number
}

export interface OpenDocument {
  id: string
  filePath: string
  fileName: string
  displayUrl: string
  isPdf: boolean
  pdfPage: number
  pdfTotalPages: number
  documentImage: DocumentImage | null
}

interface DocumentViewProps {
  openDocs: OpenDocument[]
  setOpenDocs: React.Dispatch<React.SetStateAction<OpenDocument[]>>
  activeDocId: string | null
  setActiveDocId: (id: string | null) => void
  onImageChange: (img: DocumentImage | null) => void
  showSidebar?: boolean
  sidebarWidth?: number
  onLeftResizeStart?: (e: React.MouseEvent) => void
  workspacePath: string | null
}

function toLocalFileUrl(absPath: string): string {
  const encoded = absPath.split('/').map((seg) => encodeURIComponent(seg)).join('/')
  return `localfile://${encoded}`
}

export default function DocumentView({
  openDocs,
  setOpenDocs,
  activeDocId,
  setActiveDocId,
  onImageChange,
  showSidebar = true,
  sidebarWidth = 260,
  onLeftResizeStart,
  workspacePath,
}: DocumentViewProps) {
  const [loading, setLoading] = useState(false)
  const [pdfRasterError, setPdfRasterError] = useState<string | null>(null)

  const activeDoc = openDocs.find((d) => d.id === activeDocId) || null

  const [indexedDocs, setIndexedDocs] = useState<Record<string, boolean>>({})
  const [indexingDocId, setIndexingDocId] = useState<string | null>(null)
  const [ragError, setRagError] = useState<string | null>(null)

  const loadDocImage = async (doc: OpenDocument): Promise<DocumentImage | null> => {
    const ext = doc.filePath.split('.').pop()?.toLowerCase() || ''
    const pdf = ext === 'pdf'
    try {
      if (IMAGE_EXTS.includes(ext)) {
        const base64 = await window.electronAPI.readFileBase64(doc.filePath)
        if (base64) {
          return { base64, mimeType: MIME_MAP[ext] || 'image/png', fileName: doc.fileName, filePath: doc.filePath }
        }
      } else if (pdf) {
        const out = await rasterizePdfPage(doc.filePath, doc.pdfPage || 1)
        if (out) {
          return {
            base64: out.base64,
            mimeType: 'image/png',
            fileName: doc.fileName,
            filePath: doc.filePath,
            page: doc.pdfPage || 1,
            totalPages: out.totalPages,
          }
        }
      }
    } catch (e) {
      console.error('Failed to load doc image:', e)
    }
    return null
  }

  const checkRagStatus = async (doc: OpenDocument) => {
    if (!workspacePath) return
    try {
      const response = await fetch(
        `http://localhost:8765/api/rag/status?file_path=${encodeURIComponent(
          doc.filePath
        )}&workspace=${encodeURIComponent(workspacePath)}`
      )
      if (response.ok) {
        const data = await response.json()
        setIndexedDocs((prev) => ({ ...prev, [doc.id]: data.indexed }))
      }
    } catch (e) {
      console.error('Failed to fetch RAG status:', e)
    }
  }

  const indexDocument = async (doc: OpenDocument) => {
    if (!workspacePath) return
    setIndexingDocId(doc.id)
    setRagError(null)
    try {
      const apiKey = await window.electronAPI.getAPIKey()
      const response = await fetch(`http://localhost:8765/api/rag/index`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_path: doc.filePath,
          workspace: workspacePath,
          api_key: apiKey
        })
      })
      if (response.ok) {
        setIndexedDocs((prev) => ({ ...prev, [doc.id]: true }))
      } else {
        const errData = await response.json()
        setRagError(errData.detail || 'Failed to index document.')
      }
    } catch (e: any) {
      setRagError(e.message || 'Indexing failed.')
    } finally {
      setIndexingDocId(null)
    }
  }

  useEffect(() => {
    if (activeDoc) {
      checkRagStatus(activeDoc)
    }
  }, [activeDocId, workspacePath])

  useEffect(() => {
    if (activeDocId && openDocs.length > 0) {
      const doc = openDocs.find((d) => d.id === activeDocId)
      if (doc) {
        if (!doc.documentImage && !loading) {
          setLoading(true)
          setPdfRasterError(null)
          loadDocImage(doc).then((img) => {
            if (img) {
              setOpenDocs((prev) =>
                prev.map((d) => (d.id === activeDocId ? { ...d, documentImage: img } : d))
              )
              onImageChange(img)
            } else {
              setPdfRasterError('Failed to load document content.')
            }
            setLoading(false)
          })
        } else if (doc.documentImage) {
          onImageChange(doc.documentImage)
        }
      }
    } else {
      onImageChange(null)
    }
  }, [activeDocId, openDocs])

  const draggedDocIdRef = useRef<string | null>(null)
  const [dragOverDocId, setDragOverDocId] = useState<string | null>(null)
  const [dropDocPosition, setDropDocPosition] = useState<'before' | 'after' | null>(null)
  const [editingDocId, setEditingDocId] = useState<string | null>(null)

  const handleDocDragStart = (id: string, e: React.DragEvent) => {
    draggedDocIdRef.current = id
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', id)
  }

  const handleDocDragOver = (id: string, e: React.DragEvent) => {
    e.preventDefault()
    const rect = e.currentTarget.getBoundingClientRect()
    const relativeY = e.clientY - rect.top
    const pos = relativeY < rect.height / 2 ? 'before' : 'after'
    setDragOverDocId(id)
    setDropDocPosition(pos)
  }

  const handleDocDragEnd = () => {
    draggedDocIdRef.current = null
    setDragOverDocId(null)
    setDropDocPosition(null)
  }

  const handleDocDrop = (targetId: string, e: React.DragEvent) => {
    e.preventDefault()
    const draggedId = draggedDocIdRef.current || e.dataTransfer.getData('text/plain')
    if (!draggedId || draggedId === targetId) return

    const draggedDoc = openDocs.find((d) => d.id === draggedId)
    if (!draggedDoc) return

    const remainingDocs = openDocs.filter((d) => d.id !== draggedId)
    let insertIndex = remainingDocs.findIndex((d) => d.id === targetId)
    if (insertIndex !== -1) {
      if (dropDocPosition === 'after') {
        insertIndex += 1
      }
      const newDocs = [
        ...remainingDocs.slice(0, insertIndex),
        draggedDoc,
        ...remainingDocs.slice(insertIndex),
      ]
      setOpenDocs(newDocs)
    }
    handleDocDragEnd()
  }

  const openFile = async () => {
    const chosen = await window.electronAPI.openFile({
      filters: [
        { name: 'Maps & Documents', extensions: [...IMAGE_EXTS, 'pdf'] },
        { name: 'Images', extensions: IMAGE_EXTS },
        { name: 'PDF', extensions: ['pdf'] },
      ],
    })
    if (!chosen) return

    const name = chosen.split('/').pop() || chosen
    const ext = name.split('.').pop()?.toLowerCase() || ''
    const pdf = ext === 'pdf'
    const id = Math.random().toString(36).substring(2, 9)

    const newDoc: OpenDocument = {
      id,
      filePath: chosen,
      fileName: name,
      displayUrl: toLocalFileUrl(chosen),
      isPdf: pdf,
      pdfPage: 1,
      pdfTotalPages: 1,
      documentImage: null,
    }

    setLoading(true)
    setPdfRasterError(null)

    try {
      if (IMAGE_EXTS.includes(ext)) {
        const base64 = await window.electronAPI.readFileBase64(chosen)
        if (base64) {
          newDoc.documentImage = { base64, mimeType: MIME_MAP[ext] || 'image/png', fileName: name, filePath: chosen }
        }
      } else if (pdf) {
        const out = await rasterizePdfPage(chosen, 1)
        if (out) {
          newDoc.pdfTotalPages = out.totalPages
          newDoc.documentImage = {
            base64: out.base64,
            mimeType: 'image/png',
            fileName: name,
            filePath: chosen,
            page: 1,
            totalPages: out.totalPages,
          }
        } else {
          setPdfRasterError('Could not read the PDF.')
        }
      }

      setOpenDocs((prev) => [...prev, newDoc])
      setActiveDocId(id)
      onImageChange(newDoc.documentImage)
    } catch (e) {
      setPdfRasterError(`Failed to load document: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  const switchPdfPage = async (delta: number) => {
    if (!activeDoc || !activeDoc.isPdf || loading) return
    const next = Math.max(1, Math.min(activeDoc.pdfPage + delta, activeDoc.pdfTotalPages))
    if (next === activeDoc.pdfPage) return

    setLoading(true)
    setPdfRasterError(null)
    try {
      const out = await rasterizePdfPage(activeDoc.filePath, next)
      if (!out) {
        setPdfRasterError('Could not read the PDF.')
        return
      }

      const updatedDoc: OpenDocument = {
        ...activeDoc,
        pdfPage: next,
        pdfTotalPages: out.totalPages,
        documentImage: {
          base64: out.base64,
          mimeType: 'image/png',
          fileName: activeDoc.fileName,
          filePath: activeDoc.filePath,
          page: next,
          totalPages: out.totalPages,
        }
      }

      setOpenDocs((prev) => prev.map((d) => (d.id === activeDoc.id ? updatedDoc : d)))
      onImageChange(updatedDoc.documentImage)
    } catch (e) {
      setPdfRasterError(`PDF page change failed: ${(e as Error).message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleSelectDoc = (id: string) => {
    setActiveDocId(id)
    setPdfRasterError(null)
  }

  const handleCloseDoc = (id: string) => {
    const nextDocs = openDocs.filter((d) => d.id !== id)
    setOpenDocs(nextDocs)
    if (activeDocId === id) {
      const nextActiveId = nextDocs.length > 0 ? nextDocs[0].id : null
      setActiveDocId(nextActiveId)
    }
    setPdfRasterError(null)
  }

  /* Resize is handled by the global panel resize handle in App.tsx */

  return (
    <div className="doc-view">
      {/* ── Document List Sidebar (always visible) ── */}
      {showSidebar && (
        <div className="doc-sidebar" style={{ width: sidebarWidth, flex: `0 0 ${sidebarWidth}px` }}>
          <div className="doc-sidebar-toolbar">
            <button className="doc-sidebar-add-btn" onClick={openFile} title="Open document">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 6 }}>
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              Open File
            </button>
          </div>

          <div
            className="doc-sidebar-list"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              const draggedId = draggedDocIdRef.current || e.dataTransfer.getData('text/plain')
              if (!draggedId) return
              const draggedDoc = openDocs.find((d) => d.id === draggedId)
              if (!draggedDoc) return
              const remainingDocs = openDocs.filter((d) => d.id !== draggedId)
              const newDocs = [...remainingDocs, draggedDoc]
              setOpenDocs(newDocs)
              handleDocDragEnd()
            }}
          >
            {openDocs.length === 0 ? (
              <div className="doc-sidebar-empty">
                <div className="empty-icon-container-sm">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                  </svg>
                </div>
                <p className="title">No documents open</p>
                <p className="hint">Open a map image or PDF to analyze.</p>
              </div>
            ) : (
              openDocs.map((doc) => (
                <div
                  key={doc.id}
                  className={`doc-sidebar-item ${doc.id === activeDocId ? 'active' : ''} ${dragOverDocId === doc.id ? `drag-over-${dropDocPosition}` : ''}`}
                  onClick={() => handleSelectDoc(doc.id)}
                  draggable={true}
                  onDragStart={(e) => handleDocDragStart(doc.id, e)}
                  onDragOver={(e) => handleDocDragOver(doc.id, e)}
                  onDrop={(e) => handleDocDrop(doc.id, e)}
                  onDragEnd={handleDocDragEnd}
                  style={{ cursor: 'grab' }}
                >
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="doc-sidebar-item-icon">
                    {doc.isPdf ? (
                      <>
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                        <polyline points="14 2 14 8 20 8"></polyline>
                      </>
                    ) : (
                      <>
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <circle cx="8.5" cy="8.5" r="1.5"></circle>
                        <polyline points="21 15 16 10 5 21"></polyline>
                      </>
                    )}
                  </svg>
                  {editingDocId === doc.id ? (
                    <input
                      type="text"
                      className="doc-title-input"
                      value={doc.fileName}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        const val = e.target.value
                        setOpenDocs((prev) =>
                          prev.map((d) => (d.id === doc.id ? { ...d, fileName: val } : d)),
                        )
                      }}
                      onBlur={() => setEditingDocId(null)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          setEditingDocId(null)
                        }
                      }}
                      autoFocus
                    />
                  ) : (
                    <span
                      className="doc-sidebar-item-name"
                      title={doc.filePath}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        setEditingDocId(doc.id)
                      }}
                    >
                      {doc.fileName}
                    </span>
                  )}
                  <button
                    className="doc-sidebar-item-close"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCloseDoc(doc.id)
                    }}
                    title="Close document"
                    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
                  >
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                </div>
              ))
            )}
          </div>

          {/* AI Active Page Preview section at the bottom of the sidebar */}
          {activeDoc && (
            <div className="doc-sidebar-ai-preview" style={{ padding: '12px', borderTop: '1px solid var(--border, #3a3f58)', background: 'var(--bg-secondary, #141521)', flexShrink: 0 }}>
              <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary, #b3b9d1)', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ display: 'inline-block', width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'var(--accent, #3b82f6)' }}></span>
                AI Active Page Preview
              </div>
              {activeDoc.documentImage ? (
                <div style={{ position: 'relative', border: '1px solid var(--border, #3a3f58)', borderRadius: '4px', overflow: 'hidden', backgroundColor: '#000000', display: 'flex', justifyContent: 'center', alignItems: 'center', height: '140px' }}>
                  <img
                    src={`data:${activeDoc.documentImage.mimeType};base64,${activeDoc.documentImage.base64}`}
                    alt="AI Preview"
                    style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
                  />
                  {activeDoc.isPdf && (
                    <div style={{ position: 'absolute', bottom: '6px', right: '6px', background: 'rgba(0,0,0,0.75)', color: '#ffffff', fontSize: '9px', padding: '2px 6px', borderRadius: '3px', fontWeight: 600 }}>
                      Page {activeDoc.pdfPage} of {activeDoc.pdfTotalPages}
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ fontSize: '11px', color: 'var(--text-muted, #7e84a3)', textAlign: 'center', padding: '16px', border: '1px dashed var(--border, #3a3f58)', borderRadius: '4px' }}>
                  No preview generated
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {showSidebar && onLeftResizeStart && (
        <div className="resize-handle" onMouseDown={onLeftResizeStart} />
      )}

      {/* ── Detail Pane ── */}
      <div className="doc-detail-pane">
        {activeDoc === null ? (
          <div className="doc-empty-detail">
            <div className="doc-empty-detail-icon">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
                <path d="M9 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8l4 4v4" />
                <path d="M9 20h9a2 2 0 0 0 2-2v-7" />
                <rect x="9" y="14" width="8" height="6" rx="1" />
              </svg>
            </div>
            <p className="doc-empty-detail-title">No document open</p>
            <p className="doc-empty-detail-hint">
              Open a map image or PDF to analyse it with the AI assistant.
            </p>
          </div>
        ) : (
          <>
            <div className="doc-toolbar">
              <span className="doc-filename" title={activeDoc.filePath}>
                {activeDoc.fileName}
              </span>
              {activeDoc.isPdf && (
                <span className="doc-pdf-note">
                  PDF — AI sees page {activeDoc.pdfPage} of {activeDoc.pdfTotalPages}
                </span>
              )}
              {activeDoc.isPdf && activeDoc.pdfTotalPages > 1 && (
                <span className="doc-pdf-pager">
                  <button
                    className="doc-pdf-pager-btn"
                    onClick={() => switchPdfPage(-1)}
                    disabled={loading || activeDoc.pdfPage <= 1}
                    title="Previous page"
                  >
                    ‹
                  </button>
                  <span className="doc-pdf-pager-label">
                    {activeDoc.pdfPage} / {activeDoc.pdfTotalPages}
                  </span>
                  <button
                    className="doc-pdf-pager-btn"
                    onClick={() => switchPdfPage(1)}
                    disabled={loading || activeDoc.pdfPage >= activeDoc.pdfTotalPages}
                    title="Next page"
                  >
                    ›
                  </button>
                </span>
              )}
              {loading && <span className="doc-loading-inline">Rendering…</span>}
              {pdfRasterError && <span className="doc-loading-inline doc-error">{pdfRasterError}</span>}

              {/* RAG Indexing Widget */}
              <span className="doc-rag-widget" style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px', marginRight: '8px' }}>
                {indexedDocs[activeDoc.id] ? (
                  <span style={{ color: '#10b981', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981' }}></span>
                    Indexed for AI Chat
                  </span>
                ) : indexingDocId === activeDoc.id ? (
                  <span style={{ color: '#eab308', fontSize: '11px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                    <svg className="rag-spinner" style={{ width: '12px', height: '12px' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <circle cx="12" cy="12" r="10" stroke="var(--border)" strokeDasharray="32"></circle>
                    </svg>
                    Indexing document...
                  </span>
                ) : (
                  <button
                    onClick={() => indexDocument(activeDoc)}
                    style={{
                      background: 'var(--accent, #3b82f6)',
                      color: '#ffffff',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '3px 8px',
                      fontSize: '11px',
                      cursor: 'pointer',
                      fontWeight: 600
                    }}
                  >
                    Index Document for AI Chat
                  </button>
                )}
                {ragError && (
                  <span style={{ color: 'var(--peach-fuzz, #ffd6ba)', fontSize: '11px' }} title={ragError}>
                    Ingestion failed
                  </span>
                )}
              </span>
            </div>

            <div className="doc-content">
              {activeDoc.displayUrl && (
                activeDoc.isPdf ? (
                  <iframe src={activeDoc.displayUrl} className="doc-pdf" title={activeDoc.fileName} />
                ) : (
                  <img src={activeDoc.displayUrl} alt={activeDoc.fileName} className="doc-img" />
                )
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
