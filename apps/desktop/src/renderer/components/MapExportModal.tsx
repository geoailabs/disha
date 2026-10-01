import React, { useState, useEffect } from 'react'
import './MapExportModal.css'

interface MapExportModalProps {
  isOpen: boolean
  onClose: () => void
  onExportMapPng: (title?: string, options?: { saveAs?: boolean }) => void
  onExportMapJpeg?: (title?: string, options?: { saveAs?: boolean }) => void
  onExportPdf: (title?: string, options?: { saveAs?: boolean }) => void
  onSavePngToArtifact?: (title: string) => void
  onSaveJpgToArtifact?: (title: string) => void
  onSavePdfToArtifact?: (title: string) => void
  onSuggestExportTitle: () => string
  layersCount: number
}

export const MapExportModal: React.FC<MapExportModalProps> = ({
  isOpen,
  onClose,
  onExportMapPng,
  onExportMapJpeg,
  onExportPdf,
  onSavePngToArtifact,
  onSaveJpgToArtifact,
  onSavePdfToArtifact,
  onSuggestExportTitle,
  layersCount,
}) => {
  const [title, setTitle] = useState('')
  const [savedSuccess, setSavedSuccess] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setTitle(onSuggestExportTitle() || 'Map Figure')
      setSavedSuccess(null)
    }
  }, [isOpen, onSuggestExportTitle])

  if (!isOpen) return null

  const handleDownload = (format: 'png' | 'jpg' | 'pdf', saveAs = false) => {
    const finalTitle = title.trim() || 'Map Figure'
    if (format === 'png') {
      onExportMapPng(finalTitle, { saveAs })
    } else if (format === 'jpg' && onExportMapJpeg) {
      onExportMapJpeg(finalTitle, { saveAs })
    } else if (format === 'pdf') {
      onExportPdf(finalTitle, { saveAs })
    }
    setSavedSuccess(`Exporting ${format.toUpperCase()}${saveAs ? ' (Save As)' : ''}...`)
    setTimeout(() => {
      onClose()
    }, 900)
  }

  const handleArtifactSave = (format: 'png' | 'jpg' | 'pdf') => {
    const finalTitle = title.trim() || 'Map Figure'
    if (format === 'png' && onSavePngToArtifact) {
      onSavePngToArtifact(finalTitle)
    } else if (format === 'jpg' && onSaveJpgToArtifact) {
      onSaveJpgToArtifact(finalTitle)
    } else if (format === 'pdf' && onSavePdfToArtifact) {
      onSavePdfToArtifact(finalTitle)
    }
    setSavedSuccess(`Saved to project artifacts!`)
    setTimeout(() => {
      onClose()
    }, 1200)
  }

  return (
    <div className="map-export-modal-backdrop" onClick={onClose}>
      <div className="map-export-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="mem-header">
          <div className="mem-title-group">
            <span className="mem-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
            </span>
            <div>
              <h3 className="mem-heading">Export Map Figure</h3>
              <p className="mem-subheading">
                Captures all {layersCount} visible layers with baked cartographic title, scale bar, north arrow, and legend.
              </p>
            </div>
          </div>
          <button type="button" className="mem-close-btn" onClick={onClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Figure Title Input */}
        <div className="mem-section">
          <label className="mem-label">Figure Title</label>
          <div className="mem-input-group">
            <input
              type="text"
              className="mem-input"
              placeholder="e.g. Master Plan Land Use & Corridors"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
            />
            <button
              type="button"
              className="mem-suggest-btn"
              onClick={() => setTitle(onSuggestExportTitle())}
              title="Suggest name from active layers"
            >
              Suggest
            </button>
          </div>
        </div>

        {/* Formats Grid */}
        <div className="mem-section">
          <label className="mem-label">Download to Disk</label>
          <div className="mem-actions-grid">
            <button
              type="button"
              className="mem-btn mem-btn-primary"
              onClick={() => handleDownload('png')}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              <span>Download PNG</span>
            </button>

            <button
              type="button"
              className="mem-btn"
              onClick={() => handleDownload('jpg')}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
              <span>Download JPEG</span>
            </button>

            <button
              type="button"
              className="mem-btn"
              onClick={() => handleDownload('pdf')}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
              <span>Landscape PDF</span>
            </button>

            <button
              type="button"
              className="mem-btn mem-btn-saveas"
              onClick={() => handleDownload('png', true)}
              title="Choose folder location on your computer"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                <polyline points="17 21 17 13 7 13 7 21" />
                <polyline points="7 3 7 8 15 8" />
              </svg>
              <span>Save As…</span>
            </button>
          </div>
        </div>

        {/* Save to Project Artifacts */}
        <div className="mem-section">
          <label className="mem-label">Save to Project Studio</label>
          <div className="mem-artifacts-row">
            <button
              type="button"
              className="mem-btn-subtle"
              onClick={() => handleArtifactSave('png')}
            >
              + Save as Artifact Sketch
            </button>
            <button
              type="button"
              className="mem-btn-subtle"
              onClick={() => handleArtifactSave('pdf')}
            >
              + Save as Artifact PDF
            </button>
          </div>
        </div>

        {savedSuccess && (
          <div className="mem-feedback">
            <span>✓ {savedSuccess}</span>
          </div>
        )}
      </div>
    </div>
  )
}
export default MapExportModal
