import React, { useState, useEffect, useRef } from 'react'
import './MenuBar.css'

export interface MenuBarProps {
  workspacePath: string | null
  workspaceName?: string
  currentMode: 'map' | 'streetview' | 'artifacts' | 'document'
  onModeChange: (mode: 'map' | 'streetview' | 'artifacts' | 'document') => void
  onOpenWorkspace: () => void
  onCloseWorkspace: () => void
  onOpenDiagnostics: () => void
  isChatOpen: boolean
  onToggleChat: () => void
  isSidebarCollapsed: boolean
  onToggleSidebar: () => void
  canUndoZoom?: boolean
  canRedoZoom?: boolean
  onUndoZoom?: () => void
  onRedoZoom?: () => void
  onClearSelectedFeatures?: () => void
  onExportMapPng?: () => void
  onExportMapJpeg?: () => void
  onExportPdf?: () => void
  onImportSpatialFiles?: () => void
  onZoomIn?: () => void
  onZoomOut?: () => void
  onResetZoom?: () => void
}

interface MenuItemDef {
  label?: string
  shortcut?: string
  type?: 'item' | 'separator'
  danger?: boolean
  disabled?: boolean
  onClick?: () => void
}

export const MenuBar: React.FC<MenuBarProps> = ({
  workspacePath,
  workspaceName,
  currentMode,
  onModeChange,
  onOpenWorkspace,
  onCloseWorkspace,
  onOpenDiagnostics,
  isChatOpen,
  onToggleChat,
  isSidebarCollapsed,
  onToggleSidebar,
  canUndoZoom = false,
  canRedoZoom = false,
  onUndoZoom,
  onRedoZoom,
  onClearSelectedFeatures,
  onExportMapPng,
  onExportMapJpeg,
  onExportPdf,
  onImportSpatialFiles,
  onZoomIn,
  onZoomOut,
  onResetZoom,
}) => {
  const [activeMenu, setActiveMenu] = useState<string | null>(null)
  const [currentTime, setCurrentTime] = useState<string>(() => formatMacOSDate(new Date()))
  const [aboutModalOpen, setAboutModalOpen] = useState(false)
  const [wifiPopoverOpen, setWifiPopoverOpen] = useState(false)
  const menuBarRef = useRef<HTMLDivElement>(null)

  // Dynamic live clock matching macOS format: "Wed Apr 1  9:41 AM"
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(formatMacOSDate(new Date()))
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  // Close menus on outside click or Escape
  useEffect(() => {
    const handleMouseDown = (e: MouseEvent) => {
      if (!menuBarRef.current?.contains(e.target as Node)) {
        setActiveMenu(null)
        setWifiPopoverOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setActiveMenu(null)
        setWifiPopoverOpen(false)
        setAboutModalOpen(false)
      }
    }
    window.addEventListener('mousedown', handleMouseDown)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('mousedown', handleMouseDown)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  const handleMenuTrigger = (menuKey: string) => {
    setActiveMenu((prev) => (prev === menuKey ? null : menuKey))
    setWifiPopoverOpen(false)
  }

  const handleMenuHover = (menuKey: string) => {
    if (activeMenu !== null && activeMenu !== menuKey) {
      setActiveMenu(menuKey)
      setWifiPopoverOpen(false)
    }
  }

  const handleAction = (cb?: () => void) => {
    setActiveMenu(null)
    setWifiPopoverOpen(false)
    cb?.()
  }

  // Focus prompt bar input
  const handleFocusPrompt = () => {
    const input = document.querySelector('.prompt-input') as HTMLInputElement | null
    if (input) {
      input.focus()
    }
  }

  // Menu item definitions
  const menus: Record<string, MenuItemDef[]> = {
    apple: [
      { label: 'About Disha', onClick: () => setAboutModalOpen(true) },
      { label: 'System Settings / API Keys...', shortcut: '⌘,', onClick: onOpenDiagnostics },
      { label: 'Diagnostics & Telemetry', shortcut: '⌥⌘D', onClick: onOpenDiagnostics },
      { type: 'separator' },
      {
        label: 'Toggle Fullscreen',
        shortcut: '⌃⌘F',
        onClick: () => {
          if (window.electronAPI?.toggleFullscreen) {
            window.electronAPI.toggleFullscreen()
          } else if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen?.()
          } else {
            document.exitFullscreen?.()
          }
        },
      },
      {
        label: 'Force Reload Window',
        shortcut: '⌘R',
        onClick: () => {
          if (window.electronAPI?.reloadWindow) {
            window.electronAPI.reloadWindow()
          } else {
            window.location.reload()
          }
        },
      },
      { type: 'separator' },
      {
        label: 'Close Window',
        shortcut: '⌘W',
        danger: true,
        onClick: () => {
          if (window.electronAPI?.closeWindow) {
            window.electronAPI.closeWindow()
          } else {
            window.close()
          }
        },
      },
    ],
    disha: [
      { label: 'About Disha Spatial Studio', onClick: () => setAboutModalOpen(true) },
      { label: 'Preferences & AI Models...', shortcut: '⌘,', onClick: onOpenDiagnostics },
      { label: 'Check for Updates...', onClick: () => alert('Disha Spatial Studio is up to date (v0.1.6).') },
      { type: 'separator' },
      { label: isSidebarCollapsed ? 'Show Sidebar' : 'Hide Sidebar', shortcut: '⌘B', onClick: onToggleSidebar },
      { label: isChatOpen ? 'Close AI Assistant' : 'Open AI Assistant', shortcut: '⌘J', onClick: onToggleChat },
      { type: 'separator' },
      {
        label: 'Quit Disha',
        shortcut: '⌘Q',
        danger: true,
        onClick: () => {
          if (window.electronAPI?.closeWindow) {
            window.electronAPI.closeWindow()
          } else {
            window.close()
          }
        },
      },
    ],
    file: [
      { label: 'Open Workspace...', shortcut: '⌘O', onClick: onOpenWorkspace },
      { label: 'Import Spatial Data (GeoJSON, SHP)...', shortcut: '⌘I', onClick: onImportSpatialFiles },
      { type: 'separator' },
      { label: 'Export Map as PNG', shortcut: '⇧⌘P', onClick: onExportMapPng },
      { label: 'Export Map as JPEG', shortcut: '⇧⌘J', onClick: onExportMapJpeg },
      { label: 'Export PDF Map Report...', shortcut: '⇧⌘E', onClick: onExportPdf },
      { type: 'separator' },
      { label: 'Close Workspace', shortcut: '⇧⌘W', disabled: !workspacePath, onClick: onCloseWorkspace },
    ],
    edit: [
      { label: 'Undo Map View', shortcut: '⌘Z', disabled: !canUndoZoom, onClick: onUndoZoom },
      { label: 'Redo Map View', shortcut: '⇧⌘Z', disabled: !canRedoZoom, onClick: onRedoZoom },
      { type: 'separator' },
      { label: 'Cut', shortcut: '⌘X', disabled: true },
      { label: 'Copy', shortcut: '⌘C', disabled: true },
      {
        label: 'Clear Feature Selection',
        shortcut: 'Esc',
        onClick: onClearSelectedFeatures,
      },
    ],
    view: [
      {
        label: currentMode === 'map' ? '✓ Map Canvas' : '  Map Canvas',
        shortcut: '⌘1',
        onClick: () => onModeChange('map'),
      },
      {
        label: currentMode === 'streetview' ? '✓ 360° Street View' : '  360° Street View',
        shortcut: '⌘2',
        onClick: () => onModeChange('streetview'),
      },
      {
        label: currentMode === 'artifacts' ? '✓ Artifacts Gallery' : '  Artifacts Gallery',
        shortcut: '⌘3',
        onClick: () => onModeChange('artifacts'),
      },
      {
        label: currentMode === 'document' ? '✓ Document & Code' : '  Document & Code',
        shortcut: '⌘4',
        onClick: () => onModeChange('document'),
      },
      { type: 'separator' },
      { label: isSidebarCollapsed ? 'Show Sidebar' : 'Hide Sidebar', shortcut: '⌘B', onClick: onToggleSidebar },
      { label: isChatOpen ? 'Close AI Chat Drawer' : 'Open AI Chat Drawer', shortcut: '⌘J', onClick: onToggleChat },
      { type: 'separator' },
      { label: 'Zoom In', shortcut: '⌘+', onClick: onZoomIn },
      { label: 'Zoom Out', shortcut: '⌘-', onClick: onZoomOut },
      { label: 'Reset Map View', shortcut: '⌘0', onClick: onResetZoom },
    ],
    item: [
      { label: 'Import Spatial Layers...', shortcut: '⌘I', onClick: onImportSpatialFiles },
      { label: 'Clear Selected Features', shortcut: 'Esc', onClick: onClearSelectedFeatures },
      { type: 'separator' },
      { label: 'Open Diagnostics', onClick: onOpenDiagnostics },
      { label: 'Open AI Assistant', shortcut: '⌘J', onClick: onToggleChat },
    ],
    window: [
      {
        label: 'Minimize',
        shortcut: '⌘M',
        onClick: () => window.electronAPI?.minimizeWindow?.(),
      },
      {
        label: 'Zoom / Maximize',
        onClick: () => window.electronAPI?.maximizeWindow?.(),
      },
      { type: 'separator' },
      {
        label: 'Toggle Fullscreen',
        shortcut: '⌃⌘F',
        onClick: () => {
          if (window.electronAPI?.toggleFullscreen) {
            window.electronAPI.toggleFullscreen()
          } else if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen?.()
          } else {
            document.exitFullscreen?.()
          }
        },
      },
    ],
    help: [
      {
        label: 'Disha Documentation',
        onClick: () => window.open('https://github.com', '_blank'),
      },
      {
        label: 'Diagnostics & API Keys',
        shortcut: '⌥⌘D',
        onClick: onOpenDiagnostics,
      },
      {
        label: 'Keyboard Shortcuts Reference',
        onClick: () => alert('Shortcuts:\n⌘1: Map View\n⌘2: Street View\n⌘3: Artifacts\n⌘4: Documents\n⌘B: Toggle Sidebar\n⌘J: AI Chat\n⌘O: Open Workspace\nEsc: Clear Selection'),
      },
      { type: 'separator' },
      { label: 'About Disha Spatial Studio', onClick: () => setAboutModalOpen(true) },
    ],
  }

  return (
    <>
      <header className="macos-menu-bar" ref={menuBarRef}>
        {/* Left Section: Apple Logo + Menus */}
        <div className="menubar-left-group">
          {/*  Apple Menu */}
          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item apple-logo-item ${activeMenu === 'apple' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('apple')}
              onMouseEnter={() => handleMenuHover('apple')}
              title="Apple Menu"
            >
              <svg width="13" height="15" viewBox="0 0 170 170" fill="currentColor">
                <path d="M150.37 130.25c-2.45 5.66-5.35 10.87-8.71 15.66-4.58 6.53-8.33 11.05-11.22 13.56-4.48 4.12-9.28 6.23-14.42 6.35-3.69 0-8.14-1.05-13.32-3.18-5.19-2.12-9.97-3.17-14.34-3.17-4.58 0-9.49 1.05-14.75 3.17-5.26 2.13-9.5 3.24-12.74 3.35-4.35.13-9.16-1.9-14.42-6.08-3.69-3.04-7.69-7.85-12.01-14.42-6.19-9.45-10.93-20.15-14.22-32.08-3.29-11.93-4.94-23.01-4.94-33.24 0-14.34 3.73-26.06 11.19-35.16 7.46-9.1 16.59-13.78 27.39-14.04 4.8 0 10.14 1.25 16.03 3.76 5.89 2.51 9.87 3.82 11.94 3.93 1.85-.22 5.95-1.57 12.31-4.05 6.36-2.48 11.83-3.61 16.42-3.39 12.42.65 22.37 5.16 29.86 13.52-10.9 6.64-16.24 15.66-16.03 27.05.22 9.04 3.63 16.65 10.23 22.84 6.6 6.19 14.54 9.82 23.82 10.89-2.07 6.43-4.7 13.15-7.9 20.16zm-31.57-111.44c0 7.42-2.73 14.37-8.19 20.85-5.46 6.48-12.08 10.37-19.86 11.67-.33-1.09-.49-2.18-.49-3.27 0-7.2 2.91-14.28 8.73-21.24 5.82-6.96 12.56-10.74 20.22-11.34.11 1.09.17 2.21.17 3.33z"/>
              </svg>
            </button>
            {activeMenu === 'apple' && renderDropdown(menus.apple, handleAction)}
          </div>

          {/* App Name: Disha (Bold) */}
          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item menubar-app-name ${activeMenu === 'disha' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('disha')}
              onMouseEnter={() => handleMenuHover('disha')}
            >
              Disha
            </button>
            {activeMenu === 'disha' && renderDropdown(menus.disha, handleAction)}
          </div>

          {/* Standard Menus */}
          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item ${activeMenu === 'file' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('file')}
              onMouseEnter={() => handleMenuHover('file')}
            >
              File
            </button>
            {activeMenu === 'file' && renderDropdown(menus.file, handleAction)}
          </div>

          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item ${activeMenu === 'edit' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('edit')}
              onMouseEnter={() => handleMenuHover('edit')}
            >
              Edit
            </button>
            {activeMenu === 'edit' && renderDropdown(menus.edit, handleAction)}
          </div>

          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item ${activeMenu === 'view' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('view')}
              onMouseEnter={() => handleMenuHover('view')}
            >
              View
            </button>
            {activeMenu === 'view' && renderDropdown(menus.view, handleAction)}
          </div>

          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item ${activeMenu === 'item' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('item')}
              onMouseEnter={() => handleMenuHover('item')}
            >
              Item
            </button>
            {activeMenu === 'item' && renderDropdown(menus.item, handleAction)}
          </div>

          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item ${activeMenu === 'window' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('window')}
              onMouseEnter={() => handleMenuHover('window')}
            >
              Window
            </button>
            {activeMenu === 'window' && renderDropdown(menus.window, handleAction)}
          </div>

          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-item ${activeMenu === 'help' ? 'is-active' : ''}`}
              onClick={() => handleMenuTrigger('help')}
              onMouseEnter={() => handleMenuHover('help')}
            >
              Help
            </button>
            {activeMenu === 'help' && renderDropdown(menus.help, handleAction)}
          </div>
        </div>

        {/* Right Section: System Tray (Wi-Fi, Search, Control Center, Date & Time) */}
        <div className="menubar-right-group">
          {/* Wi-Fi Status Button */}
          <div className="menubar-item-wrapper">
            <button
              type="button"
              className={`menubar-tray-btn ${wifiPopoverOpen ? 'is-active' : ''}`}
              onClick={() => {
                setWifiPopoverOpen((v) => !v)
                setActiveMenu(null)
              }}
              title="Network & Backend Status"
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12.55a11 11 0 0 1 14.08 0" />
                <path d="M1.42 9a16 16 0 0 1 21.16 0" />
                <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                <line x1="12" y1="20" x2="12.01" y2="20" strokeWidth="3" />
              </svg>
            </button>
            {wifiPopoverOpen && (
              <div className="macos-glass-menu menubar-tray-popover">
                <div className="popover-status-header">
                  <span className="popover-status-dot is-online" />
                  <span className="popover-status-title">Network & Services</span>
                </div>
                <div className="popover-status-row">
                  <span>FastAPI Backend</span>
                  <span className="badge-online">Port 8765</span>
                </div>
                <div className="popover-status-row">
                  <span>MapLibre GL Engine</span>
                  <span className="badge-online">Active</span>
                </div>
                <div className="popover-status-row">
                  <span>Workspace</span>
                  <span className="popover-ws-label">{workspaceName || 'None'}</span>
                </div>
                <div className="macos-menu-divider" />
                <button
                  type="button"
                  className="macos-menu-item"
                  onClick={() => handleAction(onOpenDiagnostics)}
                >
                  <span>Network Diagnostics...</span>
                  <span className="macos-menu-shortcut">⌥⌘D</span>
                </button>
              </div>
            )}
          </div>

          {/* Search Button */}
          <button
            type="button"
            className="menubar-tray-btn"
            onClick={handleFocusPrompt}
            title="Focus Prompt & Search (Press / or click)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>

          {/* Control Center Toggle */}
          <button
            type="button"
            className="menubar-tray-btn"
            onClick={onOpenDiagnostics}
            title="Control Center & Preferences (⌘,)"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" />
              <circle cx="8" cy="6" r="2" fill="currentColor" />
              <circle cx="16" cy="12" r="2" fill="currentColor" />
              <circle cx="10" cy="18" r="2" fill="currentColor" />
            </svg>
          </button>

          {/* Date & Time */}
          <span className="menubar-clock-text" title="Local Date & Time">
            {currentTime}
          </span>
        </div>
      </header>

      {/* About Disha Modal Dialog */}
      {aboutModalOpen && (
        <div className="mundi-modal-backdrop" onClick={() => setAboutModalOpen(false)}>
          <div className="macos-about-card" onClick={(e) => e.stopPropagation()}>
            <div className="about-logo-wrapper">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
                <rect x="2" y="2" width="20" height="20" rx="6" fill="#0077b6" />
                <path d="M7 16L12 7L17 16" stroke="#caf0f8" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="12" cy="13.5" r="1.75" fill="#00b4d8" />
              </svg>
            </div>
            <h2 className="about-app-title">Disha Spatial Studio</h2>
            <p className="about-app-version">Version 0.1.6 (Developer Preview)</p>
            <p className="about-app-desc">
              AI-driven geospatial data intelligence, real-time spatial analysis, interactive 360° visualization, and map document generation.
            </p>
            <div className="about-info-grid">
              <div className="about-info-row">
                <span>Map Engine</span>
                <strong>MapLibre GL JS</strong>
              </div>
              <div className="about-info-row">
                <span>Backend Port</span>
                <strong>8765</strong>
              </div>
              <div className="about-info-row">
                <span>Active Workspace</span>
                <strong>{workspaceName || 'None'}</strong>
              </div>
            </div>
            <button
              type="button"
              className="about-close-btn"
              onClick={() => setAboutModalOpen(false)}
            >
              OK
            </button>
          </div>
        </div>
      )}
    </>
  )
}

function renderDropdown(items: MenuItemDef[], onAction: (cb?: () => void) => void) {
  return (
    <div className="macos-glass-menu menubar-dropdown">
      {items.map((item, idx) => {
        if (item.type === 'separator') {
          return <div key={idx} className="macos-menu-divider" />
        }
        return (
          <button
            key={idx}
            type="button"
            className={`macos-menu-item ${item.danger ? 'danger' : ''} ${item.disabled ? 'is-disabled' : ''}`}
            onClick={() => {
              if (!item.disabled) {
                onAction(item.onClick)
              }
            }}
            disabled={item.disabled}
          >
            <span className="macos-menu-label">{item.label}</span>
            {item.shortcut && <span className="macos-menu-shortcut">{item.shortcut}</span>}
          </button>
        )
      })}
    </div>
  )
}

function formatMacOSDate(date: Date): string {
  const weekday = date.toLocaleDateString('en-US', { weekday: 'short' })
  const month = date.toLocaleDateString('en-US', { month: 'short' })
  const day = date.getDate()
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return `${weekday} ${month} ${day}  ${time}`
}
