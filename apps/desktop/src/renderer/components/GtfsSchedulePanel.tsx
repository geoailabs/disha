import React, { useState, useMemo, useRef, useEffect } from 'react'
import type { GtfsRouteSchedule, GtfsStopSchedule } from '../types'
import './GtfsSchedulePanel.css'

interface GtfsSchedulePanelProps {
  schedules: GtfsRouteSchedule[]
  activeRouteId: string | null
  onSelectRoute: (routeId: string) => void
  onStopClick: (stop: GtfsStopSchedule) => void
  onClose: () => void
}

export const GtfsSchedulePanel: React.FC<GtfsSchedulePanelProps> = ({
  schedules,
  activeRouteId,
  onSelectRoute,
  onStopClick,
  onClose,
}) => {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [selectedStopIdx, setSelectedStopIdx] = useState<number>(0)
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const isDraggingRef = useRef(false)
  const dragStartRef = useRef<{ startX: number; startY: number; initX: number; initY: number }>({
    startX: 0,
    startY: 0,
    initX: 0,
    initY: 0,
  })
  const panelRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // Current active route
  const currentRoute = useMemo(() => {
    if (!schedules.length) return null
    if (activeRouteId) {
      const found = schedules.find((r) => r.route_id === activeRouteId)
      if (found) return found
    }
    return schedules[0]
  }, [schedules, activeRouteId])

  // Reset selected stop index when route changes
  useEffect(() => {
    setSelectedStopIdx(0)
    if (listRef.current) {
      listRef.current.scrollTop = 0
    }
  }, [currentRoute?.route_id])

  if (!currentRoute || !schedules.length) {
    return null
  }

  const stops = currentRoute.stops || []

  const handleStopSelect = (stop: GtfsStopSchedule, index: number) => {
    setSelectedStopIdx(index)
    onStopClick(stop)
  }

  const routeColor = currentRoute.color || '#2563EB'
  const routeBadge = currentRoute.badge || currentRoute.route_short_name || currentRoute.route_id
  const transitMode = currentRoute.route_type || 'Bus'

  // ── Drag Handlers ──
  const handleDragStart = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    const target = e.target as HTMLElement
    if (target.closest('button') || target.closest('select') || target.closest('input')) return

    const panel = panelRef.current
    if (!panel) return

    const rect = panel.getBoundingClientRect()
    isDraggingRef.current = true
    dragStartRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      initX: pos ? pos.x : rect.left,
      initY: pos ? pos.y : rect.top,
    }

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current) return
      const dx = moveEvent.clientX - dragStartRef.current.startX
      const dy = moveEvent.clientY - dragStartRef.current.startY
      const nextX = Math.max(12, Math.min(window.innerWidth - 360, dragStartRef.current.initX + dx))
      const nextY = Math.max(12, Math.min(window.innerHeight - 80, dragStartRef.current.initY + dy))
      setPos({ x: nextX, y: nextY })
    }

    const handleMouseUp = () => {
      isDraggingRef.current = false
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
  }

  // ── Collapsed State ──
  if (isCollapsed) {
    return (
      <div
        ref={panelRef}
        className="gtfs-panel-collapsed"
        style={pos ? { top: `${pos.y}px`, left: `${pos.x}px`, right: 'auto' } : undefined}
        onMouseDown={handleDragStart}
        onClick={() => setIsCollapsed(false)}
        title="Click to expand schedule"
      >
        <span className="gtfs-collapsed-badge" style={{ backgroundColor: routeColor }}>
          {routeBadge}
        </span>
        <div className="gtfs-collapsed-info">
          <span className="gtfs-collapsed-title">{currentRoute.title}</span>
          <span className="gtfs-collapsed-mode">{transitMode}</span>
        </div>
        <button
          type="button"
          className="gtfs-collapsed-btn"
          title="Expand"
          onClick={(e) => {
            e.stopPropagation()
            setIsCollapsed(false)
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <polyline points="15 3 21 3 21 9" />
            <polyline points="9 21 3 21 3 15" />
            <line x1="21" y1="3" x2="14" y2="10" />
            <line x1="3" y1="21" x2="10" y2="14" />
          </svg>
        </button>
        <button
          type="button"
          className="gtfs-collapsed-btn gtfs-collapsed-close"
          title="Close"
          onClick={(e) => {
            e.stopPropagation()
            onClose()
          }}
        >
          ✕
        </button>
      </div>
    )
  }

  return (
    <div
      ref={panelRef}
      className="gtfs-schedule-panel"
      style={pos ? { top: `${pos.y}px`, left: `${pos.x}px`, right: 'auto' } : undefined}
    >
      {/* ── Drag Handle ── */}
      <div className="gtfs-drag-area" onMouseDown={handleDragStart} title="Drag to move panel">
        <div className="gtfs-drag-handle" />
      </div>

      {/* ── Top Header Bar ── */}
      <div className="gtfs-panel-header" onMouseDown={handleDragStart}>
        <div className="gtfs-header-left">
          <span className="gtfs-route-badge" style={{ backgroundColor: routeColor }}>
            {routeBadge}
          </span>
          <div className="gtfs-header-titles">
            <h3 className="gtfs-route-title">
              {currentRoute.route_long_name || currentRoute.title}
            </h3>
            {currentRoute.headsign && (
              <span className="gtfs-route-headsign">
                {currentRoute.headsign.startsWith('to ') ? currentRoute.headsign : `to ${currentRoute.headsign}`}
              </span>
            )}
          </div>
        </div>

        <div className="gtfs-header-actions">
          <button
            type="button"
            className="gtfs-header-btn"
            title="Minimize"
            onClick={() => setIsCollapsed(true)}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polyline points="4 14 10 14 10 20" />
              <polyline points="20 10 14 10 14 4" />
              <line x1="14" y1="10" x2="21" y2="3" />
              <line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          </button>
          <button
            type="button"
            className="gtfs-header-btn gtfs-close-btn"
            title="Close"
            onClick={onClose}
          >
            ✕
          </button>
        </div>
      </div>

      {/* ── Route Selection Dropdown & Mode Section (Replaces the next-stop pill) ── */}
      <div className="gtfs-controls-section">
        {schedules.length > 1 && (
          <div className="gtfs-dropdown-row">
            <label htmlFor="gtfs-route-selector" className="gtfs-dropdown-label">
              Select Route
            </label>
            <div className="gtfs-select-wrapper">
              <select
                id="gtfs-route-selector"
                className="gtfs-route-dropdown"
                value={currentRoute.route_id}
                onChange={(e) => onSelectRoute(e.target.value)}
                title="Select transit route"
              >
                {schedules.map((r) => (
                  <option key={r.route_id} value={r.route_id}>
                    {r.badge || r.route_short_name || r.route_id} — {r.route_long_name || r.title}
                  </option>
                ))}
              </select>
              <span className="gtfs-select-chevron">▾</span>
            </div>
          </div>
        )}

        {/* Clean text metadata mentioning Mode (Bus, Subway, etc.), frequency, and agency */}
        <div className="gtfs-mode-schedule-bar">
          <span className="gtfs-mode-callout">
            <span className="gtfs-mode-dot" style={{ backgroundColor: routeColor }} />
            <strong>Mode:</strong> {transitMode}
          </span>
          <span className="gtfs-meta-sep">·</span>
          <span>{currentRoute.daily_trips} trips/day</span>
          {currentRoute.agency_name && (
            <>
              <span className="gtfs-meta-sep">·</span>
              <span title={currentRoute.agency_name}>
                {currentRoute.agency_name.replace('MTA New York City Transit', 'MTA NYCT')}
              </span>
            </>
          )}
          <span className="gtfs-meta-sep">·</span>
          <span className="gtfs-stops-total">{stops.length} stops</span>
        </div>
      </div>

      {/* ── Translucent Stops & Departure Times List (Opaque on Hover) ── */}
      <div className="gtfs-schedule-list-wrap">
        <div className="gtfs-schedule-stops" ref={listRef}>
          {stops.map((stop, idx) => {
            const isSelected = idx === selectedStopIdx
            return (
              <div
                key={`${stop.stop_id}-${idx}`}
                className={`gtfs-stop-row ${isSelected ? 'is-selected' : ''}`}
                onClick={() => handleStopSelect(stop, idx)}
                title={`Click to focus ${stop.stop_name} on map`}
              >
                <div className="gtfs-stop-left">
                  <div className="gtfs-stop-spine">
                    <span
                      className="gtfs-stop-bullet"
                      style={{
                        borderColor: routeColor,
                        backgroundColor: isSelected ? routeColor : 'transparent',
                      }}
                    />
                    {idx < stops.length - 1 && <span className="gtfs-spine-line" />}
                  </div>
                  <span className="gtfs-stop-label" title={stop.stop_name}>
                    {stop.stop_name}
                  </span>
                  {stop.is_transfer && (
                    <span className="gtfs-transfer-indicator">Transfer</span>
                  )}
                </div>

                <div className="gtfs-stop-right">
                  <span className="gtfs-stop-departure">
                    {stop.formatted_time || stop.departure_time || '—'}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
