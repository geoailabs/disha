import React, { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import './ColorPickerPopover.css'

export interface ColorPickerPopoverProps {
  color: string
  onChange: (color: string) => void
  onClose: () => void
  anchorRect?: DOMRect | null
  position?: { x: number; y: number } | null
}

const PRESET_PALETTE = [
  '#ef4444', '#f97316', '#f59e0b', '#eab308',
  '#10b981', '#06b6d4', '#0ea5e9', '#3b82f6',
  '#6366f1', '#8b5cf6', '#a855f7', '#ec4899',
  '#f43f5e', '#64748b', '#ffffff', '#0f172a',
]

function hexToHsv(hex: string): { h: number; s: number; v: number } {
  let cleaned = hex.replace(/^#/, '').trim()
  if (cleaned.length === 3) {
    cleaned = cleaned.split('').map((c) => c + c).join('')
  }
  if (cleaned.length !== 6) {
    return { h: 210, s: 0.8, v: 0.9 }
  }
  const r = parseInt(cleaned.slice(0, 2), 16) / 255
  const g = parseInt(cleaned.slice(2, 4), 16) / 255
  const b = parseInt(cleaned.slice(4, 6), 16) / 255

  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min

  let h = 0
  const s = max === 0 ? 0 : d / max
  const v = max

  if (max !== min) {
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break
      case g: h = (b - r) / d + 2; break
      case b: h = (r - g) / d + 4; break
    }
    h /= 6
  }

  return { h: Math.round(h * 360), s, v }
}

function hsvToHex(h: number, s: number, v: number): string {
  const i = Math.floor((h / 60) % 6)
  const f = h / 60 - Math.floor(h / 60)
  const p = v * (1 - s)
  const q = v * (1 - f * s)
  const t = v * (1 - (1 - f) * s)

  let r = 0, g = 0, b = 0
  switch (i) {
    case 0: r = v; g = t; b = p; break
    case 1: r = q; g = v; b = p; break
    case 2: r = p; g = v; b = t; break
    case 3: r = p; g = q; b = v; break
    case 4: r = t; g = p; b = v; break
    case 5: r = v; g = p; b = q; break
  }

  const toHex = (n: number) => {
    const val = Math.round(n * 255)
    const clamped = Math.max(0, Math.min(255, val))
    return clamped.toString(16).padStart(2, '0')
  }

  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

export default function ColorPickerPopover({
  color,
  onChange,
  onClose,
  anchorRect,
  position,
}: ColorPickerPopoverProps) {
  const popoverRef = useRef<HTMLDivElement>(null)
  const satCanvasRef = useRef<HTMLDivElement>(null)
  const hueBarRef = useRef<HTMLDivElement>(null)

  const initialHsv = hexToHsv(color)
  const [hue, setHue] = useState<number>(initialHsv.h)
  const [sat, setSat] = useState<number>(initialHsv.s)
  const [val, setVal] = useState<number>(initialHsv.v)
  const [hexInput, setHexInput] = useState<string>(color.replace(/^#/, '').toUpperCase())

  // Keep hex input synchronized when HSV changes
  const updateColor = useCallback((h: number, s: number, v: number) => {
    setHue(h)
    setSat(s)
    setVal(v)
    const hex = hsvToHex(h, s, v)
    setHexInput(hex.replace(/^#/, '').toUpperCase())
    onChange(hex)
  }, [onChange])

  // Sync state if color prop changes externally
  useEffect(() => {
    const nextHsv = hexToHsv(color)
    setHue(nextHsv.h)
    setSat(nextHsv.s)
    setVal(nextHsv.v)
    setHexInput(color.replace(/^#/, '').toUpperCase())
  }, [color])

  // Outside click & Escape handlers
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('mousedown', handleOutsideClick, true)
    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('mousedown', handleOutsideClick, true)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  // 2D Saturation / Value Drag Handling
  const handleSatMouseDown = (e: React.MouseEvent) => {
    if (!satCanvasRef.current) return
    const rect = satCanvasRef.current.getBoundingClientRect()

    const onMove = (moveEvt: MouseEvent) => {
      const x = Math.max(0, Math.min(rect.width, moveEvt.clientX - rect.left))
      const y = Math.max(0, Math.min(rect.height, moveEvt.clientY - rect.top))
      const newSat = x / rect.width
      const newVal = 1 - (y / rect.height)
      updateColor(hue, newSat, newVal)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    onMove(e.nativeEvent)
  }

  // Hue Slider Drag Handling
  const handleHueMouseDown = (e: React.MouseEvent) => {
    if (!hueBarRef.current) return
    const rect = hueBarRef.current.getBoundingClientRect()

    const onMove = (moveEvt: MouseEvent) => {
      const x = Math.max(0, Math.min(rect.width, moveEvt.clientX - rect.left))
      const newHue = Math.round((x / rect.width) * 360) % 360
      updateColor(newHue, sat, val)
    }

    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    onMove(e.nativeEvent)
  }

  // Hex Text Change
  const handleHexChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value.replace(/[^0-9A-Fa-f]/g, '').slice(0, 6)
    setHexInput(raw.toUpperCase())
    if (raw.length === 6 || raw.length === 3) {
      const parsed = hexToHsv(`#${raw}`)
      setHue(parsed.h)
      setSat(parsed.s)
      setVal(parsed.v)
      onChange(`#${raw}`)
    }
  }

  // Eyedropper API
  const handleEyeDropper = async () => {
    if (typeof window !== 'undefined' && 'EyeDropper' in window) {
      try {
        const eyeDropper = new (window as any).EyeDropper()
        const result = await eyeDropper.open()
        if (result?.sRGBHex) {
          const parsed = hexToHsv(result.sRGBHex)
          updateColor(parsed.h, parsed.s, parsed.v)
        }
      } catch {
        // User cancelled eyedropper
      }
    }
  }

  // Compute Popover Position
  const popoverWidth = 248
  const popoverHeight = 245

  let top = 100
  let left = 100

  if (anchorRect) {
    left = Math.max(12, Math.min(window.innerWidth - popoverWidth - 14, anchorRect.left))
    if (anchorRect.bottom + popoverHeight + 10 <= window.innerHeight) {
      top = anchorRect.bottom + 6
    } else {
      top = Math.max(12, anchorRect.top - popoverHeight - 6)
    }
  } else if (position) {
    left = Math.max(12, Math.min(window.innerWidth - popoverWidth - 14, position.x))
    top = Math.max(12, Math.min(window.innerHeight - popoverHeight - 14, position.y))
  }

  const currentColorHex = hsvToHex(hue, sat, val)
  const pureHueHex = hsvToHex(hue, 1, 1)

  return createPortal(
    <div
      ref={popoverRef}
      className="disha-color-picker-popover"
      style={{ top, left }}
      onClick={(e) => e.stopPropagation()}
    >
      {/* 2D Saturation / Value Gradient Field */}
      <div
        ref={satCanvasRef}
        className="dcp-saturation-canvas"
        style={{ backgroundColor: pureHueHex }}
        onMouseDown={handleSatMouseDown}
      >
        <div className="dcp-saturation-white" />
        <div className="dcp-saturation-black" />
        <div
          className="dcp-canvas-handle"
          style={{
            left: `${sat * 100}%`,
            top: `${(1 - val) * 100}%`,
            backgroundColor: currentColorHex,
          }}
        />
      </div>

      {/* 1D Hue Bar */}
      <div
        ref={hueBarRef}
        className="dcp-hue-bar"
        onMouseDown={handleHueMouseDown}
      >
        <div
          className="dcp-hue-handle"
          style={{ left: `${(hue / 360) * 100}%` }}
        />
      </div>

      {/* Preset Swatches Grid */}
      <div className="dcp-presets-grid">
        {PRESET_PALETTE.map((preset) => {
          const isActive = currentColorHex.toLowerCase() === preset.toLowerCase()
          return (
            <button
              key={preset}
              type="button"
              className={`dcp-preset-btn ${isActive ? 'active' : ''}`}
              style={{ backgroundColor: preset }}
              onClick={() => {
                const parsed = hexToHsv(preset)
                updateColor(parsed.h, parsed.s, parsed.v)
              }}
              title={preset}
            />
          )
        })}
      </div>

      {/* Bottom Row: Eyedropper, Swatch, Hex Input */}
      <div className="dcp-bottom-controls">
        {typeof window !== 'undefined' && 'EyeDropper' in window && (
          <button
            type="button"
            className="dcp-eyedropper-btn"
            onClick={handleEyeDropper}
            title="Pick color from screen"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 2l4 4-9 9-4-1 1-4 8-8z" />
              <path d="M15 5l4 4" />
              <path d="M3 21l3-1-2-2-1 3z" />
            </svg>
          </button>
        )}

        <div
          className="dcp-current-swatch"
          style={{ backgroundColor: currentColorHex }}
        />

        <div className="dcp-hex-input-wrap">
          <span className="dcp-hex-prefix">#</span>
          <input
            type="text"
            className="dcp-hex-input"
            value={hexInput}
            onChange={handleHexChange}
            maxLength={6}
            placeholder="HEX"
            spellCheck={false}
          />
        </div>
      </div>
    </div>,
    document.body
  )
}
