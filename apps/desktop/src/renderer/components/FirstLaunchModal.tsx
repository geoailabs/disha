import React, { useState } from 'react'
import './FirstLaunchModal.css'

interface FirstLaunchModalProps {
  defaultPath: string
  onConfirm: (chosenPath: string) => void
}

export const FirstLaunchModal: React.FC<FirstLaunchModalProps> = ({ defaultPath, onConfirm }) => {
  const [folderPath, setFolderPath] = useState<string>(defaultPath)
  const [isSelecting, setIsSelecting] = useState(false)

  const handleBrowse = async () => {
    try {
      setIsSelecting(true)
      const selected = await window.electronAPI.selectFolder('Select Disha Library Folder')
      if (selected) {
        setFolderPath(selected)
      }
    } catch (err) {
      console.warn('Failed to select folder:', err)
    } finally {
      setIsSelecting(false)
    }
  }

  const handleContinue = () => {
    if (folderPath.trim()) {
      onConfirm(folderPath.trim())
    }
  }

  return (
    <div className="flm-overlay">
      <div className="flm-card">
        <div className="flm-header">
          <div className="flm-kicker">Welcome to Disha</div>
          <h2 className="flm-title">Choose Your Disha Library</h2>
          <p className="flm-subtitle">
            Disha auto-saves your maps, spatial layers, scenarios, and AI analysis automatically.
            Choose where your projects and spatial files should live:
          </p>
        </div>

        <div className="flm-path-box">
          <div className="flm-path-label">Library Storage Path</div>
          <div className="flm-path-row">
            <input
              type="text"
              className="flm-path-input"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              title={folderPath}
              placeholder="e.g. /Users/name/Documents/Disha"
            />
            <button
              type="button"
              className="flm-browse-btn"
              onClick={handleBrowse}
              disabled={isSelecting}
            >
              {isSelecting ? 'Selecting…' : 'Change Folder…'}
            </button>
          </div>
        </div>

        <div className="flm-hint">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          <span>You can still open client folders or external GIS workspaces anytime via File → Open Workspace.</span>
        </div>

        <div className="flm-footer">
          <button
            type="button"
            className="flm-continue-btn"
            onClick={handleContinue}
            disabled={!folderPath.trim()}
          >
            Get Started →
          </button>
        </div>
      </div>
    </div>
  )
}
