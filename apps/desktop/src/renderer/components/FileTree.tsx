import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import './FileTree.css'

interface FileTreeProps {
  workspacePath: string | null
  onFileClick?: (entry: FileEntry) => void
  onImportClick?: () => void
  revision?: number
}

interface TreeNodeProps {
  entry: FileEntry
  depth: number
  onFileClick?: (entry: FileEntry) => void
  onContextMenu: (e: React.MouseEvent, entry: FileEntry) => void
}

function TreeNode({ entry, depth, onFileClick, onContextMenu }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const [children, setChildren] = useState<FileEntry[]>([])

  const toggle = async (): Promise<void> => {
    if (entry.isDirectory) {
      if (!expanded) {
        const items = await window.electronAPI.readDirectory(entry.path)
        const filtered = items.filter(
          (item) => !['project.json', 'google-maps-key.json', 'api-key.json', '.disha'].includes(item.name.toLowerCase())
        )
        setChildren(filtered)
      }
      setExpanded(!expanded)
    } else if (onFileClick) {
      onFileClick(entry)
    }
  }

  const lower = entry.name.toLowerCase()
  const isGeoJSON = !entry.isDirectory && (lower.endsWith('.geojson') || lower.endsWith('.json'))
  const isConvertible =
    !entry.isDirectory &&
    /\.(shp|gpkg|kml|kmz|gpx|csv)$/.test(lower)
  const isGeoFile = isGeoJSON || isConvertible

  return (
    <div className="tree-node">
      <div
        className={`tree-item ${entry.isDirectory ? 'directory' : 'file'} ${isGeoFile ? 'geojson' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={toggle}
        onContextMenu={(e) => onContextMenu(e, entry)}
        title={entry.path}
      >
        <span className="tree-icon">
          {entry.isDirectory ? (expanded ? '▾' : '▸') : isGeoFile ? '◈' : '·'}
        </span>
        <span className="tree-name">{entry.name}</span>
      </div>
      {expanded &&
        children.map((child) => (
          <TreeNode
            key={child.path}
            entry={child}
            depth={depth + 1}
            onFileClick={onFileClick}
            onContextMenu={onContextMenu}
          />
        ))}
    </div>
  )
}

export default function FileTree({ workspacePath, onFileClick, onImportClick, revision }: FileTreeProps) {
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [contextMenu, setContextMenu] = useState<{ entry: FileEntry; x: number; y: number } | null>(null)
  const [copiedNotice, setCopiedNotice] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.toLowerCase().includes('mac')
  const revealLabel = isMac ? 'Reveal in Finder' : 'Reveal in File Explorer'

  const loadDirectory = useCallback(async () => {
    if (!workspacePath) return
    try {
      const items = await window.electronAPI.readDirectory(workspacePath)
      const filtered = items.filter(
        (item) => !['project.json', 'google-maps-key.json', 'api-key.json', '.disha'].includes(item.name.toLowerCase())
      )
      setEntries(filtered)
    } catch (err) {
      console.warn('Failed to read workspace directory:', err)
    }
  }, [workspacePath])

  useEffect(() => {
    loadDirectory()
  }, [loadDirectory, revision])

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setContextMenu(null)
      }
    }
    if (contextMenu) {
      window.addEventListener('mousedown', handleOutsideClick)
    }
    return () => {
      window.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [contextMenu])

  const handleContextMenu = (e: React.MouseEvent, entry: FileEntry) => {
    e.preventDefault()
    e.stopPropagation()
    // Position menu clamping to window width/height
    const menuWidth = 180
    const menuHeight = 110
    const x = Math.min(e.clientX, window.innerWidth - menuWidth - 10)
    const y = Math.min(e.clientY, window.innerHeight - menuHeight - 10)
    setContextMenu({ entry, x, y })
  }

  const handleReveal = () => {
    if (contextMenu) {
      window.electronAPI.showItemInFolder(contextMenu.entry.path)
      setContextMenu(null)
    }
  }

  const handleLoadLayer = () => {
    if (contextMenu && onFileClick) {
      onFileClick(contextMenu.entry)
      setContextMenu(null)
    }
  }

  const handleCopyPath = () => {
    if (contextMenu) {
      navigator.clipboard.writeText(contextMenu.entry.path)
      setCopiedNotice(true)
      setTimeout(() => {
        setCopiedNotice(false)
        setContextMenu(null)
      }, 600)
    }
  }

  if (!workspacePath) {
    return (
      <div className="file-tree-empty">
        <p>No workspace open</p>
        <p className="hint">Set or open a Disha library folder above</p>
      </div>
    )
  }

  const isGeoFile = (entry: FileEntry) => {
    const lower = entry.name.toLowerCase()
    return !entry.isDirectory && (lower.endsWith('.geojson') || lower.endsWith('.json') || /\.(shp|gpkg|kml|kmz|gpx|csv)$/.test(lower))
  }

  return (
    <div className="file-tree-wrap">
      <div className="file-tree-header-container">
        <div className="file-tree-toolbar">
          <span
            className="file-tree-path"
            title={`${workspacePath} (Right-click to reveal)`}
            onContextMenu={(e) => handleContextMenu(e, { name: 'Workspace', path: workspacePath, isDirectory: true })}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ opacity: 0.75, flexShrink: 0 }}>
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            {workspacePath.includes('/') ? workspacePath.split('/').pop() : workspacePath.split('\\').pop()}
          </span>
          <div className="file-tree-actions">
            <button className="file-tree-import-btn" onClick={onImportClick} title="Import spatial files">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 2 }}>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              Import
            </button>
            <button className="file-tree-refresh" onClick={loadDirectory} title="Refresh file tree">
              ↻
            </button>
          </div>
        </div>
        <div className="file-formats-banner">
          Supported: KML, KMZ, SHP, GPKG, GPX, CSV, GeoJSON
        </div>
      </div>
      <div
        className="file-tree"
        onContextMenu={(e) => {
          if ((e.target as HTMLElement).classList.contains('file-tree')) {
            handleContextMenu(e, { name: 'Workspace', path: workspacePath, isDirectory: true })
          }
        }}
      >
        {entries.map((entry) => (
          <TreeNode
            key={entry.path}
            entry={entry}
            depth={0}
            onFileClick={onFileClick}
            onContextMenu={handleContextMenu}
          />
        ))}
        {entries.length === 0 && (
          <div className="file-tree-empty-inner">
            <p>No files in this folder yet.</p>
            <p className="hint">Click &quot;Import&quot; or drop spatial files here.</p>
          </div>
        )}
      </div>

      {/* Right-click Context Menu */}
      {contextMenu && createPortal(
        <div
          ref={menuRef}
          className="file-tree-context-menu"
          style={{ top: `${contextMenu.y}px`, left: `${contextMenu.x}px` }}
        >
          <div className="ft-cm-header" title={contextMenu.entry.name}>
            {contextMenu.entry.name}
          </div>
          <button type="button" className="ft-cm-item" onClick={handleReveal}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            <span>{revealLabel}</span>
          </button>

          {!contextMenu.entry.isDirectory && isGeoFile(contextMenu.entry) && (
            <button type="button" className="ft-cm-item" onClick={handleLoadLayer}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="12 2 2 7 12 12 22 7 12 2" />
                <polyline points="2 17 12 22 22 17" />
                <polyline points="2 12 12 17 22 12" />
              </svg>
              <span>Load as Map Layer</span>
            </button>
          )}

          <button type="button" className="ft-cm-item" onClick={handleCopyPath}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
            </svg>
            <span>{copiedNotice ? 'Copied!' : 'Copy Path'}</span>
          </button>
        </div>,
        document.body
      )}
    </div>
  )
}
