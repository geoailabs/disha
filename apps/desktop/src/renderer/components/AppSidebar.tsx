import React from 'react'
import './AppSidebar.css'
import layersIcon from '../assets/icons/layers_icons.png'
import filesIcon from '../assets/icons/files_icon.png'
import zonesIcon from '../assets/icons/zones_icon.png'
import scenariosIcon from '../assets/icons/scenarios_icon.png'
import exportIcon from '../assets/icons/export_icon.png'
import streetViewIcon from '../assets/streetview.png'

export type AppNavMode = 'map' | 'streetview' | 'artifacts' | 'document'
export type WorkspaceCategory = 'layers' | 'files' | 'zones' | 'scenarios' | 'export'

interface AppSidebarProps {
  currentMode: AppNavMode
  onModeChange: (mode: AppNavNavChange) => void
  isCollapsed: boolean
  onToggleCollapse: () => void
  workspacePath: string | null
  onOpenWorkspace: () => void
  onCloseWorkspace: () => void
  onOpenDiagnostics: () => void
  isChatOpen: boolean
  onToggleChat: () => void
  unreadCount?: number

  // Workspace Categories
  activeCategory?: WorkspaceCategory | null
  onCategoryClick?: (category: WorkspaceCategory) => void
  isCategoryPanelOpen?: boolean
  layerCount?: number
  scenarioCount?: number
}

type AppNavNavChange = 'map' | 'streetview' | 'artifacts' | 'document'

export const AppSidebar: React.FC<AppSidebarProps> = ({
  currentMode,
  onModeChange,
  isCollapsed,
  onToggleCollapse,
  workspacePath,
  onOpenWorkspace,
  onCloseWorkspace,
  onOpenDiagnostics,
  isChatOpen,
  onToggleChat,
  unreadCount,
  activeCategory = 'layers',
  onCategoryClick,
  isCategoryPanelOpen = true,
  layerCount = 0,
  scenarioCount = 0,
}) => {
  const workspaceName = workspacePath ? workspacePath.split(/[/\\]/).pop() || 'Workspace' : null

  return (
    <aside className={`app-sidebar ${isCollapsed ? 'collapsed' : 'expanded'}`}>
      {/* Sidebar Header (Expand / Collapse Button Only) */}
      <div className="sidebar-header">
        <button
          className="sidebar-collapse-btn"
          onClick={onToggleCollapse}
          title={isCollapsed ? 'Expand Sidebar' : 'Collapse Sidebar'}
        >
          {isCollapsed ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <polyline points="14 9 17 12 14 15" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
              <polyline points="15 9 12 12 15 15" />
            </svg>
          )}
        </button>
      </div>

      {/* Main Navigation Menu */}
      <nav className="sidebar-nav">
        {/* Workspace Categories Group */}
        <div className="sidebar-nav-group">
          {!isCollapsed && <div className="sidebar-group-title">WORKSPACE</div>}

          {/* Layers */}
          <button
            className={`sidebar-nav-item ${activeCategory === 'layers' && isCategoryPanelOpen ? 'active' : ''}`}
            onClick={() => onCategoryClick?.('layers')}
            title="Spatial Layers & Overlays"
          >
            <div className="sidebar-nav-icon">
              <span
                className="sidebar-mask-icon"
                style={{
                  WebkitMaskImage: `url("${layersIcon}")`,
                  maskImage: `url("${layersIcon}")`,
                }}
                aria-hidden="true"
              />
            </div>
            {!isCollapsed && (
              <div className="sidebar-nav-label-group">
                <span className="sidebar-nav-label">Layers</span>
                {layerCount > 0 && <span className="sidebar-pill-badge">{layerCount}</span>}
              </div>
            )}
          </button>

          {/* Files */}
          <button
            className={`sidebar-nav-item ${activeCategory === 'files' && isCategoryPanelOpen ? 'active' : ''}`}
            onClick={() => onCategoryClick?.('files')}
            title="Workspace Files & Data"
          >
            <div className="sidebar-nav-icon">
              <span
                className="sidebar-mask-icon"
                style={{
                  WebkitMaskImage: `url("${filesIcon}")`,
                  maskImage: `url("${filesIcon}")`,
                }}
                aria-hidden="true"
              />
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Files</span>}
          </button>

          {/* Zones */}
          <button
            className={`sidebar-nav-item ${activeCategory === 'zones' && isCategoryPanelOpen ? 'active' : ''}`}
            onClick={() => onCategoryClick?.('zones')}
            title="Urban Zoning & Land Use"
          >
            <div className="sidebar-nav-icon">
              <span
                className="sidebar-mask-icon"
                style={{
                  WebkitMaskImage: `url("${zonesIcon}")`,
                  maskImage: `url("${zonesIcon}")`,
                }}
                aria-hidden="true"
              />
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Zones</span>}
          </button>

          {/* Scenarios */}
          <button
            className={`sidebar-nav-item ${activeCategory === 'scenarios' && isCategoryPanelOpen ? 'active' : ''}`}
            onClick={() => onCategoryClick?.('scenarios')}
            title="Planning Scenarios & Simulations"
          >
            <div className="sidebar-nav-icon">
              <span
                className="sidebar-mask-icon"
                style={{
                  WebkitMaskImage: `url("${scenariosIcon}")`,
                  maskImage: `url("${scenariosIcon}")`,
                }}
                aria-hidden="true"
              />
            </div>
            {!isCollapsed && (
              <div className="sidebar-nav-label-group">
                <span className="sidebar-nav-label">Scenarios</span>
                {scenarioCount > 0 && <span className="sidebar-pill-badge">{scenarioCount}</span>}
              </div>
            )}
          </button>

          {/* Export */}
          <button
            className={`sidebar-nav-item ${activeCategory === 'export' && isCategoryPanelOpen ? 'active' : ''}`}
            onClick={() => onCategoryClick?.('export')}
            title="Export Maps, Reports & GeoData"
          >
            <div className="sidebar-nav-icon">
              <span
                className="sidebar-mask-icon"
                style={{
                  WebkitMaskImage: `url("${exportIcon}")`,
                  maskImage: `url("${exportIcon}")`,
                }}
                aria-hidden="true"
              />
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Export</span>}
          </button>
        </div>

        {/* Studio Views Group */}
        <div className="sidebar-nav-group">
          {!isCollapsed && <div className="sidebar-group-title">STUDIO VIEWS</div>}

          {/* Map Canvas */}
          <button
            className={`sidebar-nav-item ${currentMode === 'map' && (!isCategoryPanelOpen || activeCategory == null) ? 'active' : ''}`}
            onClick={() => onModeChange('map')}
            title="Interactive Map Canvas"
          >
            <div className="sidebar-nav-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
                <line x1="8" y1="2" x2="8" y2="18" />
                <line x1="16" y1="6" x2="16" y2="22" />
              </svg>
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Map Canvas</span>}
          </button>

          {/* Street View */}
          <button
            className={`sidebar-nav-item ${currentMode === 'streetview' ? 'active' : ''}`}
            onClick={() => onModeChange('streetview')}
            title="Street View & Inspection"
          >
            <div className="sidebar-nav-icon">
              <span
                className="sidebar-streetview-icon"
                style={{
                  WebkitMaskImage: `url("${streetViewIcon}")`,
                  maskImage: `url("${streetViewIcon}")`,
                }}
                aria-hidden="true"
              />
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Street View</span>}
          </button>

          {/* Artifacts & Reports */}
          <button
            className={`sidebar-nav-item ${currentMode === 'artifacts' ? 'active' : ''}`}
            onClick={() => onModeChange('artifacts')}
            title="Artifacts, Reports & Exports"
          >
            <div className="sidebar-nav-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Artifacts</span>}
          </button>

          {/* Documents & RAG */}
          <button
            className={`sidebar-nav-item ${currentMode === 'document' ? 'active' : ''}`}
            onClick={() => onModeChange('document')}
            title="Document Planning & RAG"
          >
            <div className="sidebar-nav-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
            </div>
            {!isCollapsed && <span className="sidebar-nav-label">Documents</span>}
          </button>
        </div>

        {/* AI Assistant */}
        <div className="sidebar-nav-group">
          {!isCollapsed && <div className="sidebar-group-title">AI COPILOT</div>}

          {/* Chat Panel Drawer Toggle */}
          <button
            className={`sidebar-nav-item ${isChatOpen ? 'active' : ''}`}
            onClick={onToggleChat}
            title={isChatOpen ? 'Close AI Chat' : 'Open AI Chat & History'}
          >
            <div className="sidebar-nav-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            {!isCollapsed && (
              <div className="sidebar-nav-label-group">
                <span className="sidebar-nav-label">Copilot</span>
                {unreadCount != null && unreadCount > 0 && (
                  <span className="sidebar-pill-badge">{unreadCount}</span>
                )}
              </div>
            )}
          </button>
        </div>
      </nav>

      {/* Sidebar Footer */}
      <div className="sidebar-footer">
        {/* Workspace directory indicator */}
        {workspaceName ? (
          <div className="sidebar-workspace-pill" title={`Active Project: ${workspacePath}`}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ flexShrink: 0 }}>
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            {!isCollapsed && (
              <span className="sidebar-workspace-text" onClick={onOpenWorkspace}>
                {workspaceName}
              </span>
            )}
            {!isCollapsed && (
              <button
                className="sidebar-workspace-close"
                onClick={(e) => {
                  e.stopPropagation()
                  onCloseWorkspace()
                }}
                title="Close Project"
              >
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            )}
          </div>
        ) : (
          <button className="sidebar-open-project-btn" onClick={onOpenWorkspace} title="Open Workspace Folder">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            {!isCollapsed && <span>Open Folder</span>}
          </button>
        )}

        {/* Diagnostics & Settings */}
        <button
          className="sidebar-nav-item sidebar-settings-btn"
          onClick={onOpenDiagnostics}
          title="System Diagnostics & API Keys"
        >
          <div className="sidebar-nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </div>
          {!isCollapsed && <span className="sidebar-nav-label">Settings</span>}
        </button>
      </div>
    </aside>
  )
}

export default AppSidebar
