// Compose a publication-ready map figure: takes the raw MapLibre WebGL canvas
// and paints a title band, scale bar, north arrow, legend, and attribution onto
// a fresh 2D canvas. Pure canvas drawing — no html2canvas, no new deps.
//
// The returned canvas is what every export path (PNG download, PDF, artifact)
// should capture, so decorations are guaranteed to be in the output (the live
// ScaleControl/NavigationControl are DOM overlays and never were).

import type { LegendEntry } from './legend-data'

export interface ComposeOptions {
  title: string
  /** Map center latitude — needed for the scale bar's ground resolution. */
  centerLat: number
  /** Map zoom level (fractional ok). */
  zoom: number
  /** Map bearing in degrees; the north arrow counter-rotates by this. */
  bearing?: number
  legend?: LegendEntry[]
  attribution?: string
  /** Subtitle line under the title (defaults to today's date). */
  subtitle?: string
  /** Omit outer title/footer bands for full-bleed map snapshot. */
  noTitleBand?: boolean
}

const PAD = 16
const TITLE_BAND = 56
const FOOTER_BAND = 24

// Web Mercator ground resolution (meters per CSS pixel) at a latitude/zoom.
function metersPerPixel(lat: number, zoom: number): number {
  return (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoom)
}

// Round a raw distance down to a "nice" 1/2/5 × 10ⁿ value for the scale bar.
function niceDistance(meters: number): number {
  const pow = Math.pow(10, Math.floor(Math.log10(meters)))
  const f = meters / pow
  const nice = f >= 5 ? 5 : f >= 2 ? 2 : 1
  return nice * pow
}

function formatDistance(meters: number): string {
  return meters >= 1000 ? `${meters / 1000} km` : `${meters} m`
}

function defaultDate(): string {
  return new Date().toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function composeFigure(
  source: HTMLCanvasElement,
  opts: ComposeOptions,
): HTMLCanvasElement {
  const dpr = window.devicePixelRatio || 1
  const tBand = opts.noTitleBand ? 0 : TITLE_BAND
  const fBand = opts.noTitleBand ? 0 : FOOTER_BAND

  const mapW = source.width / dpr
  const mapH = source.height / dpr
  const outW = mapW
  const outH = mapH + tBand + fBand

  const out = document.createElement('canvas')
  out.width = Math.round(outW * dpr)
  out.height = Math.round(outH * dpr)
  const ctx = out.getContext('2d')!
  ctx.scale(dpr, dpr)

  // Background.
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, outW, outH)

  // ── Title band ──
  if (!opts.noTitleBand) {
    ctx.fillStyle = '#111827'
    ctx.font = '600 20px system-ui, -apple-system, sans-serif'
    ctx.textBaseline = 'middle'
    ctx.fillText(opts.title || 'Map', PAD, TITLE_BAND / 2 - 6, outW - PAD * 2)
    ctx.fillStyle = '#6b7280'
    ctx.font = '12px system-ui, -apple-system, sans-serif'
    ctx.fillText(opts.subtitle || defaultDate(), PAD, TITLE_BAND / 2 + 14)
  }

  // ── Map image ──
  ctx.drawImage(source, 0, tBand, mapW, mapH)

  // Everything below is drawn over the map, within its rectangle.
  const mapTop = tBand
  const mapBottom = tBand + mapH

  // ── Scale bar (bottom-left) ──
  drawScaleBar(ctx, opts.centerLat, opts.zoom, PAD, mapBottom - PAD)

  // ── North arrow (top-right of map) ──
  drawNorthArrow(ctx, mapW - PAD - 18, mapTop + PAD + 18, opts.bearing || 0)

  // ── Legend (bottom-right of map) ──
  if (opts.legend && opts.legend.length > 0) {
    drawLegend(ctx, opts.legend, mapW - PAD, mapBottom - PAD)
  }

  // ── Footer / attribution ──
  if (!opts.noTitleBand) {
    ctx.fillStyle = '#6b7280'
    ctx.font = '10px system-ui, -apple-system, sans-serif'
    ctx.textBaseline = 'middle'
    const attribution = (opts.attribution || '').replace(/&copy;/g, '©').replace(/<[^>]+>/g, '')
    ctx.fillText(attribution, PAD, mapBottom + FOOTER_BAND / 2, outW - PAD * 2)
  }

  return out
}

function drawScaleBar(
  ctx: CanvasRenderingContext2D,
  lat: number,
  zoom: number,
  x: number,
  y: number,
): void {
  const mpp = metersPerPixel(lat, zoom)
  if (!isFinite(mpp) || mpp <= 0) return
  const targetPx = 100 // aim for ~100px wide
  const meters = niceDistance(mpp * targetPx)
  const barPx = meters / mpp

  ctx.save()
  ctx.lineWidth = 3
  ctx.strokeStyle = '#111827'
  ctx.fillStyle = '#111827'
  // Bar with end ticks.
  ctx.beginPath()
  ctx.moveTo(x, y - 6)
  ctx.lineTo(x, y)
  ctx.lineTo(x + barPx, y)
  ctx.lineTo(x + barPx, y - 6)
  ctx.stroke()
  // Label with a halo for legibility over imagery.
  ctx.font = '600 11px system-ui, -apple-system, sans-serif'
  ctx.textBaseline = 'bottom'
  const label = formatDistance(meters)
  ctx.lineWidth = 3
  ctx.strokeStyle = '#ffffff'
  ctx.strokeText(label, x, y - 8)
  ctx.fillText(label, x, y - 8)
  ctx.restore()
}

function drawNorthArrow(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  bearing: number,
): void {
  ctx.save()
  ctx.translate(cx, cy)
  ctx.rotate((-bearing * Math.PI) / 180) // counter-rotate so N points to true north
  // Triangle pointer.
  ctx.beginPath()
  ctx.moveTo(0, -14)
  ctx.lineTo(7, 8)
  ctx.lineTo(0, 3)
  ctx.lineTo(-7, 8)
  ctx.closePath()
  ctx.fillStyle = '#111827'
  ctx.lineWidth = 2
  ctx.strokeStyle = '#ffffff'
  ctx.stroke()
  ctx.fill()
  // "N" label above.
  ctx.fillStyle = '#111827'
  ctx.font = '700 11px system-ui, -apple-system, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'bottom'
  ctx.lineWidth = 3
  ctx.strokeStyle = '#ffffff'
  ctx.strokeText('N', 0, -15)
  ctx.fillText('N', 0, -15)
  ctx.restore()
}

function drawLegend(
  ctx: CanvasRenderingContext2D,
  entries: LegendEntry[],
  rightX: number,
  bottomY: number,
): void {
  const rowH = 16
  const swatch = 11
  const padX = 10
  const padY = 8
  const titleH = 16

  ctx.font = '11px system-ui, -apple-system, sans-serif'
  // Measure width + height.
  let maxText = 0
  let totalRows = 0
  for (const e of entries) {
    ctx.font = '600 11px system-ui, -apple-system, sans-serif'
    maxText = Math.max(maxText, ctx.measureText(`${e.title}${e.property ? ' · ' + e.property : ''}`).width)
    ctx.font = '11px system-ui, -apple-system, sans-serif'
    for (const r of e.rows) {
      maxText = Math.max(maxText, swatch + 6 + ctx.measureText(r.label).width)
      totalRows++
    }
  }
  const boxW = Math.min(maxText + padX * 2, 260)
  const boxH = padY * 2 + entries.length * titleH + totalRows * rowH
  const boxX = rightX - boxW
  const boxY = bottomY - boxH

  // Card.
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.strokeStyle = 'rgba(0,0,0,0.15)'
  ctx.lineWidth = 1
  roundRect(ctx, boxX, boxY, boxW, boxH, 6)
  ctx.fill()
  ctx.stroke()

  let cy = boxY + padY
  ctx.textBaseline = 'top'
  for (const e of entries) {
    ctx.fillStyle = '#111827'
    ctx.font = '600 11px system-ui, -apple-system, sans-serif'
    const heading = `${e.title}${e.property ? ' · ' + e.property : ''}`
    ctx.fillText(heading, boxX + padX, cy, boxW - padX * 2)
    cy += titleH
    ctx.font = '11px system-ui, -apple-system, sans-serif'
    for (const r of e.rows) {
      ctx.fillStyle = r.color
      ctx.strokeStyle = 'rgba(0,0,0,0.15)'
      ctx.fillRect(boxX + padX, cy + 1, swatch, swatch)
      ctx.strokeRect(boxX + padX, cy + 1, swatch, swatch)
      ctx.fillStyle = '#1f2937'
      ctx.fillText(r.label, boxX + padX + swatch + 6, cy, boxW - padX * 2 - swatch - 6)
      cy += rowH
    }
  }
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + w, y, x + w, y + h, r)
  ctx.arcTo(x + w, y + h, x, y + h, r)
  ctx.arcTo(x, y + h, x, y, r)
  ctx.arcTo(x, y, x + w, y, r)
  ctx.closePath()
}
