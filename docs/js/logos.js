/**
 * DISHA — Vector SVG Logo Candidates & Brand Asset Generators
 */

const DISHA_LOGOS = {
  // Concept 1 (Recommended): Directional Compass & AI Spark
  compassSpark: {
    id: 'compass-spark',
    name: 'Directional Compass & AI Spark',
    tagline: 'Recommended — Direction ("Disha") compass needle fused with neural AI node & contour vector',
    category: 'Dynamic Vector',
    primaryColor: '#38BDF8',
    accentColor: '#10B981',
    svgIcon: `<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-svg">
      <defs>
        <linearGradient id="cs-grad1" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#38BDF8"/>
          <stop offset="100%" stop-color="#10B981"/>
        </linearGradient>
        <linearGradient id="cs-grad2" x1="56" y1="8" x2="8" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#818CF8"/>
          <stop offset="100%" stop-color="#38BDF8"/>
        </linearGradient>
        <filter id="cs-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur"/>
          <feComposite in="SourceGraphic" in2="blur" operator="over"/>
        </filter>
      </defs>
      <!-- Spatial Contour Ring -->
      <circle cx="32" cy="32" r="28" stroke="url(#cs-grad1)" stroke-width="2.5" stroke-dasharray="6 3" opacity="0.6"/>
      <circle cx="32" cy="32" r="21" stroke="#38BDF8" stroke-width="1.2" opacity="0.3"/>
      <!-- Compass Star Needles -->
      <path d="M32 6L38 26L58 32L38 38L32 58L26 38L6 32L26 26L32 6Z" fill="url(#cs-grad1)" filter="url(#cs-glow)"/>
      <path d="M32 14L36 28L50 32L36 36L32 50L28 36L14 32L28 28L32 14Z" fill="#080E1A" opacity="0.9"/>
      <!-- AI Neural Core Spark -->
      <circle cx="32" cy="32" r="5" fill="#38BDF8"/>
      <circle cx="32" cy="32" r="2.5" fill="#FFFFFF"/>
      <circle cx="48" cy="16" r="3" fill="#10B981"/>
      <line x1="36" y1="28" x2="48" y2="16" stroke="#10B981" stroke-width="1.5" stroke-dasharray="2 2"/>
    </svg>`,
    svgFull: `<svg viewBox="0 0 240 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-full-svg">
      <defs>
        <linearGradient id="csf-grad" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#38BDF8"/>
          <stop offset="100%" stop-color="#10B981"/>
        </linearGradient>
      </defs>
      <g transform="translate(4, 0)">
        <circle cx="32" cy="32" r="28" stroke="url(#csf-grad)" stroke-width="2" stroke-dasharray="5 3" opacity="0.6"/>
        <path d="M32 8L37 27L56 32L37 37L32 56L27 37L8 32L27 27L32 8Z" fill="url(#csf-grad)"/>
        <path d="M32 16L35 29L48 32L35 35L32 48L29 35L16 32L29 29L32 16Z" fill="#080E1A"/>
        <circle cx="32" cy="32" r="4.5" fill="#38BDF8"/>
        <circle cx="32" cy="32" r="2" fill="#FFFFFF"/>
      </g>
      <text x="76" y="40" font-family="'Space Grotesk', sans-serif" font-weight="800" font-size="28" fill="currentColor" letter-spacing="-0.02em">DISHA</text>
      <text x="168" y="28" font-family="'IBM Plex Mono', monospace" font-size="10" fill="#38BDF8" font-weight="600" letter-spacing="0.1em">GIS · AI</text>
    </svg>`
  },

  // Concept 2: Geometric Polygon 'D' Lettermark
  polygonD: {
    id: 'polygon-d',
    name: "Geometric Polygon 'D' Lettermark",
    tagline: 'Faceted GIS cadastral parcel polygon forming a dimensional "D"',
    category: 'Lettermark',
    primaryColor: '#38BDF8',
    accentColor: '#818CF8',
    svgIcon: `<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-svg">
      <defs>
        <linearGradient id="pd-grad1" x1="12" y1="8" x2="52" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#38BDF8"/>
          <stop offset="100%" stop-color="#818CF8"/>
        </linearGradient>
      </defs>
      <!-- Polygons forming D -->
      <polygon points="12,10 34,10 24,32 12,32" fill="#38BDF8" opacity="0.9"/>
      <polygon points="34,10 52,24 40,42 24,32" fill="url(#pd-grad1)"/>
      <polygon points="12,32 24,32 34,54 12,54" fill="#10B981" opacity="0.85"/>
      <polygon points="24,32 40,42 34,54" fill="#818CF8" opacity="0.95"/>
      <!-- Inner cutout -->
      <polygon points="24,24 34,24 30,36 22,36" fill="#080E1A"/>
      <!-- Coordinate Vertex Dots -->
      <circle cx="12" cy="10" r="2.5" fill="#FFFFFF"/>
      <circle cx="52" cy="24" r="2.5" fill="#FFFFFF"/>
      <circle cx="34" cy="54" r="2.5" fill="#FFFFFF"/>
      <circle cx="12" cy="54" r="2.5" fill="#FFFFFF"/>
    </svg>`,
    svgFull: `<svg viewBox="0 0 240 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-full-svg">
      <g transform="translate(6, 0)">
        <polygon points="12,10 34,10 24,32 12,32" fill="#38BDF8"/>
        <polygon points="34,10 50,24 38,42 24,32" fill="#818CF8"/>
        <polygon points="12,32 24,32 34,54 12,54" fill="#10B981"/>
        <polygon points="24,32 38,42 34,54" fill="#6366F1"/>
        <circle cx="12" cy="10" r="2" fill="#FFF"/>
        <circle cx="50" cy="24" r="2" fill="#FFF"/>
        <circle cx="34" cy="54" r="2" fill="#FFF"/>
      </g>
      <text x="76" y="40" font-family="'Space Grotesk', sans-serif" font-weight="800" font-size="28" fill="currentColor" letter-spacing="-0.02em">DISHA</text>
      <text x="168" y="28" font-family="'IBM Plex Mono', monospace" font-size="10" fill="#818CF8" font-weight="600" letter-spacing="0.1em">SPATIAL</text>
    </svg>`
  },

  // Concept 3: GIS Map Pin & Radar Pulse
  radarPin: {
    id: 'radar-pin',
    name: 'GIS Map Pin & Radar Pulse',
    tagline: 'Modern vector map pin with concentric radar pulse scanning waves',
    category: 'Spatial Glyph',
    primaryColor: '#10B981',
    accentColor: '#38BDF8',
    svgIcon: `<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-svg">
      <defs>
        <linearGradient id="rp-grad" x1="16" y1="8" x2="48" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#10B981"/>
          <stop offset="100%" stop-color="#38BDF8"/>
        </linearGradient>
      </defs>
      <!-- Radar Waves -->
      <path d="M14 26C14 16.0589 22.0589 8 32 8C41.9411 8 50 16.0589 50 26" stroke="#38BDF8" stroke-width="2" stroke-dasharray="3 3" opacity="0.5"/>
      <path d="M8 26C8 12.7452 18.7452 2 32 2C45.2548 2 56 12.7452 56 26" stroke="#10B981" stroke-width="1.5" opacity="0.3"/>
      <!-- Central Pin -->
      <path d="M32 58C32 58 48 38 48 26C48 17.1634 40.8366 10 32 10C23.1634 10 16 17.1634 16 26C16 38 32 58 32 58Z" fill="url(#rp-grad)"/>
      <circle cx="32" cy="26" r="6" fill="#080E1A"/>
      <circle cx="32" cy="26" r="3" fill="#FFFFFF"/>
    </svg>`,
    svgFull: `<svg viewBox="0 0 240 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-full-svg">
      <g transform="translate(6, 0)">
        <path d="M16 24C16 15 23 8 32 8C41 8 48 15 48 24" stroke="#38BDF8" stroke-width="1.5" stroke-dasharray="3 2" opacity="0.5"/>
        <path d="M32 56C32 56 46 38 46 26C46 18.268 39.732 12 32 12C24.268 12 18 18.268 18 26C18 38 32 56 32 56Z" fill="#10B981"/>
        <circle cx="32" cy="26" r="5" fill="#080E1A"/>
        <circle cx="32" cy="26" r="2.5" fill="#FFF"/>
      </g>
      <text x="76" y="40" font-family="'Space Grotesk', sans-serif" font-weight="800" font-size="28" fill="currentColor" letter-spacing="-0.02em">DISHA</text>
      <text x="168" y="28" font-family="'IBM Plex Mono', monospace" font-size="10" fill="#10B981" font-weight="600" letter-spacing="0.1em">GEOSPATIAL</text>
    </svg>`
  },

  // Concept 4: Classic Open Vector Arrow Emblem
  arrowEmblem: {
    id: 'arrow-emblem',
    name: 'Classic Open Vector Arrow Emblem',
    tagline: 'Bold open-source GIS glyph featuring a traversing spatial vector through a stylized "D"',
    category: 'Open Source Heritage',
    primaryColor: '#589632',
    accentColor: '#38BDF8',
    svgIcon: `<svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-svg">
      <defs>
        <linearGradient id="qa-grad" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#589632"/>
          <stop offset="50%" stop-color="#93C023"/>
          <stop offset="100%" stop-color="#38BDF8"/>
        </linearGradient>
      </defs>
      <!-- Outer D boundary -->
      <path d="M12 10H32C44.1503 10 54 19.8497 54 32C54 44.1503 44.1503 54 32 54H12V10Z" fill="url(#qa-grad)"/>
      <path d="M22 20H32C38.6274 20 44 25.3726 44 32C44 38.6274 38.6274 44 32 44H22V20Z" fill="#080E1A"/>
      <!-- Traversal Arrow -->
      <path d="M4 46L36 14L44 22L12 54L4 46Z" fill="#93C023"/>
      <polygon points="32,8 52,14 46,34" fill="#38BDF8"/>
    </svg>`,
    svgFull: `<svg viewBox="0 0 240 64" fill="none" xmlns="http://www.w3.org/2000/svg" class="disha-logo-full-svg">
      <g transform="translate(4, 0)">
        <path d="M12 10H32C44 10 52 19 52 32C52 45 44 54 32 54H12V10Z" fill="#589632"/>
        <path d="M20 18H32C39 18 44 24 44 32C44 40 39 46 32 46H20V18Z" fill="#080E1A"/>
        <polygon points="30,8 50,14 44,34" fill="#38BDF8"/>
        <path d="M6 46L34 18L40 24L12 52L6 46Z" fill="#93C023"/>
      </g>
      <text x="76" y="40" font-family="'Space Grotesk', sans-serif" font-weight="800" font-size="28" fill="currentColor" letter-spacing="-0.02em">DISHA</text>
      <text x="168" y="28" font-family="'IBM Plex Mono', monospace" font-size="10" fill="#93C023" font-weight="600" letter-spacing="0.1em">GEOSPATIAL</text>
    </svg>`
  }
};

/**
 * Helper to download SVG code as a file
 */
function downloadSvgAsset(svgString, filename) {
  const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const downloadLink = document.createElement('a');
  downloadLink.href = url;
  downloadLink.download = filename;
  document.body.appendChild(downloadLink);
  downloadLink.click();
  document.body.removeChild(downloadLink);
  URL.revokeObjectURL(url);
}
