import React, { useState, useEffect, useRef, useCallback } from 'react'
import type { TimelineSpec } from '../types'
import './TimelineBar.css'

interface TimelineBarProps {
  spec: TimelineSpec
  onStepChange: (step: string) => Promise<void> | void
  onUpdateSpec: (updated: Partial<TimelineSpec>) => void
  onClose: () => void
  isLoading?: boolean
}

export const TimelineBar: React.FC<TimelineBarProps> = ({
  spec,
  onStepChange,
  onUpdateSpec,
  onClose,
  isLoading = false,
}) => {
  const [isPlaying, setIsPlaying] = useState<boolean>(spec.isPlaying ?? false)
  const [isEditing, setIsEditing] = useState<boolean>(false)
  const [editStart, setEditStart] = useState<string>(String(spec.start))
  const [editEnd, setEditEnd] = useState<string>(String(spec.end))
  const [editUnit, setEditUnit] = useState<string>(spec.stepUnit || 'year')
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(spec.playbackSpeed || 1500)

  const trackRef = useRef<HTMLDivElement>(null)
  const isDraggingRef = useRef<boolean>(false)

  const steps = spec.steps && spec.steps.length > 0 ? spec.steps : [String(spec.start), String(spec.end)]
  const currentStep = String(spec.current || steps[0])
  const currentIndex = Math.max(0, steps.indexOf(currentStep) !== -1 ? steps.indexOf(currentStep) : 0)

  // Sync edit fields when spec changes externally
  useEffect(() => {
    setEditStart(String(spec.start))
    setEditEnd(String(spec.end))
    setEditUnit(spec.stepUnit || 'year')
    if (spec.playbackSpeed) setPlaybackSpeed(spec.playbackSpeed)
  }, [spec.start, spec.end, spec.stepUnit, spec.playbackSpeed])

  // Autoplay loop
  useEffect(() => {
    if (!isPlaying || steps.length <= 1) return

    const timer = setInterval(() => {
      const nextIdx = (currentIndex + 1) % steps.length
      const nextStep = steps[nextIdx]
      onStepChange(nextStep)
    }, playbackSpeed)

    return () => clearInterval(timer)
  }, [isPlaying, currentIndex, steps, playbackSpeed, onStepChange])

  // Calculate percentage along the track
  const pct = steps.length > 1 ? (currentIndex / (steps.length - 1)) * 100 : 50

  const handleStepSelect = useCallback((step: string) => {
    if (step !== currentStep) {
      onStepChange(step)
    }
  }, [currentStep, onStepChange])

  const handlePrevStep = () => {
    const prevIdx = Math.max(0, currentIndex - 1)
    onStepChange(steps[prevIdx])
  }

  const handleNextStep = () => {
    const nextIdx = Math.min(steps.length - 1, currentIndex + 1)
    onStepChange(steps[nextIdx])
  }

  // Handle click or drag on the track
  const updateFromPosition = (clientX: number) => {
    if (!trackRef.current || steps.length <= 1) return
    const rect = trackRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width))
    const ratio = x / rect.width
    const targetIdx = Math.round(ratio * (steps.length - 1))
    const clampedIdx = Math.max(0, Math.min(targetIdx, steps.length - 1))
    const selected = steps[clampedIdx]
    if (selected !== currentStep) {
      onStepChange(selected)
    }
  }

  const handleTrackMouseDown = (e: React.MouseEvent) => {
    isDraggingRef.current = true
    updateFromPosition(e.clientX)

    const handleMouseMove = (moveEvt: MouseEvent) => {
      if (isDraggingRef.current) {
        updateFromPosition(moveEvt.clientX)
      }
    }

    const handleMouseUp = () => {
      isDraggingRef.current = false
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
  }

  // Handle Edit Apply
  const handleApplyEdit = (e: React.FormEvent) => {
    e.preventDefault()
    const s = editStart.trim()
    const en = editEnd.trim()

    let newSteps: string[] = []
    const sNum = parseInt(s, 10)
    const eNum = parseInt(en, 10)

    if (!isNaN(sNum) && !isNaN(eNum) && s.length === 4 && en.length === 4) {
      // Annual sequence
      const startYr = Math.min(sNum, eNum)
      const endYr = Math.max(sNum, eNum)
      for (let y = startYr; y <= endYr; y++) {
        newSteps.push(String(y))
      }
    } else if (s.includes(',') || en.includes(',')) {
      newSteps = (s + ',' + en)
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean)
    } else {
      newSteps = [s, en]
    }

    if (newSteps.length === 0) {
      newSteps = [s, en]
    }

    const newCurrent = newSteps.includes(currentStep) ? currentStep : newSteps[0]

    onUpdateSpec({
      start: s,
      end: en,
      stepUnit: editUnit as any,
      steps: newSteps,
      current: newCurrent,
      playbackSpeed,
    })

    if (newCurrent !== currentStep) {
      onStepChange(newCurrent)
    }

    setIsEditing(false)
  }

  // Determine whether to display every tick label or thin them if many
  const shouldShowLabel = (idx: number, total: number) => {
    if (total <= 7) return true
    if (idx === 0 || idx === total - 1) return true
    if (total <= 12) return idx % 2 === 0
    return idx % Math.ceil(total / 6) === 0
  }

  return (
    <div className="timeline-bar-wrapper">
      {/* Inline Range Editor Popover */}
      {isEditing && (
        <div className="timeline-edit-popover">
          <div className="timeline-edit-header">
            <span>Edit Temporal Range</span>
            <button
              type="button"
              className="timeline-edit-close"
              onClick={() => setIsEditing(false)}
            >
              ✕
            </button>
          </div>
          <form onSubmit={handleApplyEdit} className="timeline-edit-form">
            <div className="timeline-edit-row">
              <label>
                Start
                <input
                  type="text"
                  value={editStart}
                  onChange={(e) => setEditStart(e.target.value)}
                  placeholder="2018 or 10 PM"
                  autoFocus
                />
              </label>
              <label>
                End
                <input
                  type="text"
                  value={editEnd}
                  onChange={(e) => setEditEnd(e.target.value)}
                  placeholder="2024 or 2 AM"
                />
              </label>
            </div>
            <div className="timeline-edit-row">
              <label>
                Unit
                <select
                  value={editUnit}
                  onChange={(e) => setEditUnit(e.target.value)}
                >
                  <option value="year">Years</option>
                  <option value="month">Months</option>
                  <option value="day">Days</option>
                  <option value="hour">Hours</option>
                  <option value="custom">Custom</option>
                </select>
              </label>
              <label>
                Speed
                <select
                  value={playbackSpeed}
                  onChange={(e) => setPlaybackSpeed(Number(e.target.value))}
                >
                  <option value={3000}>0.5x (Slow)</option>
                  <option value={1500}>1.0x (Normal)</option>
                  <option value={750}>2.0x (Fast)</option>
                </select>
              </label>
            </div>
            <div className="timeline-edit-actions">
              <button
                type="button"
                className="timeline-btn-cancel"
                onClick={() => setIsEditing(false)}
              >
                Cancel
              </button>
              <button type="submit" className="timeline-btn-apply">
                Apply Range
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Main Glassmorphic Pill */}
      <div className={`timeline-pill ${isLoading ? 'is-loading' : ''}`}>
        {/* Play/Pause Button */}
        <button
          type="button"
          className="timeline-btn timeline-play-btn"
          onClick={() => setIsPlaying(!isPlaying)}
          title={isPlaying ? 'Pause playback' : 'Play timeline'}
        >
          {isPlaying ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="5" y="4" width="4" height="16" rx="1" />
              <rect x="15" y="4" width="4" height="16" rx="1" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="6,3 20,12 6,21" />
            </svg>
          )}
        </button>

        {/* Step Prev */}
        <button
          type="button"
          className="timeline-btn timeline-step-btn"
          onClick={handlePrevStep}
          disabled={currentIndex <= 0}
          title="Previous time step"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="19,20 9,12 19,4" />
            <rect x="5" y="4" width="2" height="16" />
          </svg>
        </button>

        {/* Step Next */}
        <button
          type="button"
          className="timeline-btn timeline-step-btn"
          onClick={handleNextStep}
          disabled={currentIndex >= steps.length - 1}
          title="Next time step"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5,4 15,12 5,20" />
            <rect x="17" y="4" width="2" height="16" />
          </svg>
        </button>

        {/* Track with Ticks & Scrubber Needle */}
        <div
          className="timeline-track-container"
          ref={trackRef}
          onMouseDown={handleTrackMouseDown}
        >
          {/* Subtle horizontal track line */}
          <div className="timeline-track-line" />

          {/* Step ticks and labels */}
          <div className="timeline-ticks">
            {steps.map((st, i) => {
              const tickPct = (i / (steps.length - 1)) * 100
              const isSelected = i === currentIndex
              const showText = shouldShowLabel(i, steps.length)

              return (
                <div
                  key={`${st}-${i}`}
                  className={`timeline-tick-node ${isSelected ? 'is-selected' : ''}`}
                  style={{ left: `${tickPct}%` }}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleStepSelect(st)
                  }}
                >
                  <div className="timeline-tick-notch" />
                  {showText && (
                    <span className="timeline-tick-label">{st}</span>
                  )}
                </div>
              )
            })}
          </div>

          {/* Scrubber Needle with Inverted Triangle Thumb & Active Label */}
          <div
            className="timeline-needle"
            style={{ left: `${pct}%` }}
          >
            {/* Active tooltip / label above needle */}
            <div className="timeline-needle-badge">
              <span className="timeline-needle-text">
                {currentIndex === steps.length - 1 ? 'Now' : currentStep}
              </span>
              <div className="timeline-needle-arrow" />
            </div>

            {/* Vertical needle line */}
            <div className="timeline-needle-stem" />
          </div>
        </div>

        {/* Dataset / Title Badge with Tooltip */}
        <div className="timeline-title-badge" title={spec.title}>
          {spec.title}
        </div>

        {/* Edit Button */}
        <button
          type="button"
          className={`timeline-btn timeline-edit-btn ${isEditing ? 'is-active' : ''}`}
          onClick={() => setIsEditing(!isEditing)}
          title="Edit timeline range & speed"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
          </svg>
        </button>

        {/* Loading Spinner */}
        {isLoading && (
          <div className="timeline-spinner" title="Loading Earth Engine layer...">
            <div className="timeline-spinner-dot" />
          </div>
        )}

        {/* Close Button */}
        <button
          type="button"
          className="timeline-btn timeline-close-btn"
          onClick={onClose}
          title="Close timeline"
        >
          ✕
        </button>
      </div>
    </div>
  )
}

export default TimelineBar
