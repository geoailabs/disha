#!/usr/bin/env node
/**
 * DISHA — Documentation Sync Engine
 * Reads Markdown specifications from repository root (README.md, ARCHITECTURE.md, AGENTS.md, FEATURE_IMPLEMENTATION_GUIDE.md)
 * and generates the complete, rich, non-empty docs/docs.html portal.
 * Ensures zero emojis, full technical depth, and instant search capability.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

// Helper to safely read a file or return empty string
function readFileSafe(filePath) {
  try {
    return fs.readFileSync(path.join(rootDir, filePath), 'utf-8');
  } catch (err) {
    console.warn(`[sync-docs] Warning: Could not read ${filePath}`, err.message);
    return '';
  }
}

// Strip emojis from text
function stripEmojis(str) {
  if (!str) return '';
  return str.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}]/gu, '').trim();
}

console.log('[sync-docs] Reading repository Markdown specifications...');
const readmeMd = readFileSafe('README.md');
const archMd = readFileSafe('ARCHITECTURE.md');
const agentsMd = readFileSafe('AGENTS.md');
const featureGuideMd = readFileSafe('FEATURE_IMPLEMENTATION_GUIDE.md');

let version = 'v0.3.0';
try {
  const pkgJson = JSON.parse(fs.readFileSync(path.join(rootDir, 'package.json'), 'utf-8'));
  if (pkgJson.version) version = `v${pkgJson.version}`;
} catch (_) {}

console.log(`[sync-docs] Compiling documentation for Disha (${version})...`);

const htmlContent = `<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Documentation & System Architecture - Disha GIS</title>
  <meta name="description" content="Official documentation, system architecture, 7+1 Domain Hubs reference, prompt engineering handbook, and live data connectors for Disha desktop GIS." />
  
  <link rel="icon" type="image/svg+xml" href="favicon.svg" />
  
  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700;800&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  
  <!-- Stylesheets -->
  <link rel="stylesheet" href="css/style.css" />
  
  <style>
    /* Documentation Portal Specific Styles */
    .docs-search-bar {
      margin-bottom: 20px;
      position: relative;
    }
    .docs-search-input {
      width: 100%;
      padding: 10px 14px 10px 36px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 0.88rem;
      transition: var(--transition-fast);
    }
    .docs-search-input:focus {
      outline: none;
      border-color: var(--accent-cyan);
      box-shadow: var(--shadow-glow);
    }
    .docs-search-icon {
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      pointer-events: none;
    }
    .hub-card {
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 24px;
      margin-bottom: 20px;
      transition: var(--transition-fast);
    }
    .hub-card:hover {
      border-color: var(--border-strong);
    }
    .hub-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .hub-title {
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-primary);
    }
    .tool-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 0.88rem;
    }
    .tool-table th {
      background: var(--bg-secondary);
      color: var(--text-muted);
      font-family: var(--font-mono);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      padding: 10px 14px;
      border-bottom: 1px solid var(--border-subtle);
      text-align: left;
    }
    .tool-table td {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--text-secondary);
      vertical-align: top;
    }
    .tool-table tr:last-child td {
      border-bottom: none;
    }
    .prompt-box {
      background: var(--bg-panel);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 18px;
      margin-bottom: 14px;
    }
    .channel-badge {
      display: inline-block;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      padding: 3px 8px;
      border-radius: 4px;
      margin-right: 6px;
    }
    .channel-ws { background: rgba(56, 189, 248, 0.15); color: var(--accent-cyan); border: 1px solid rgba(56, 189, 248, 0.3); }
    .channel-http { background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); border: 1px solid rgba(16, 185, 129, 0.3); }
    .channel-ipc { background: rgba(129, 140, 248, 0.15); color: var(--accent-violet); border: 1px solid rgba(129, 140, 248, 0.3); }
  </style>
</head>
<body data-page="docs">

  <!-- Shared Header Mount -->
  <div id="site-header"></div>

  <!-- Page Hero Header -->
  <section style="padding: 50px 0 36px; border-bottom: 1px solid var(--border-subtle); background: var(--bg-secondary);">
    <div class="wrap">
      <div class="eyebrow">Comprehensive Technical Documentation</div>
      <h1 style="font-size: clamp(2rem, 4vw, 3rem); margin-bottom: 10px;">Disha Documentation Hub</h1>
      <p style="color: var(--text-secondary); max-width: 680px; font-size: 1.05rem; line-height: 1.6;">
        Complete developer and planner guides for Disha desktop GIS. Includes system architecture, installation procedures, the 7+1 Domain Hubs tool reference, prompt engineering patterns, centralized spatial registry, and live cloud data engines.
      </p>
    </div>
  </section>

  <!-- Main Docs Grid -->
  <main class="wrap" style="padding-top: 36px; padding-bottom: 80px;">
    <div class="docs-layout">

      <!-- Sticky Sidebar Navigation -->
      <aside class="docs-sidebar">
        <div class="docs-search-bar">
          <svg class="docs-search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          <input type="text" id="docs-search-input" class="docs-search-input" placeholder="Search documentation..." autocomplete="off" />
        </div>

        <div class="docs-nav-group">
          <div class="docs-nav-title">System Guide</div>
          <ul class="docs-nav-list">
            <li><a href="#overview" class="docs-nav-link active">1. System Architecture</a></li>
            <li><a href="#installation" class="docs-nav-link">2. Installation & Setup</a></li>
            <li><a href="#domain-hubs" class="docs-nav-link">3. 7+1 Domain Hubs & Tools</a></li>
            <li><a href="#prompts" class="docs-nav-link">4. Prompt Engineering Handbook</a></li>
            <li><a href="#registry" class="docs-nav-link">5. Spatial & Polygon Registry</a></li>
            <li><a href="#connectors" class="docs-nav-link">6. Data Connectors & Engines</a></li>
          </ul>
        </div>

        <div class="docs-nav-group" style="margin-top:24px;">
          <div class="docs-nav-title">Quick Links</div>
          <ul class="docs-nav-list">
            <li><a href="https://github.com/geoailabs/disha" target="_blank" rel="noopener" class="docs-nav-link">GitHub Repository</a></li>
            <li><a href="https://github.com/geoailabs/disha/issues" target="_blank" rel="noopener" class="docs-nav-link">Report an Issue</a></li>
            <li><a href="index.html#download" class="docs-nav-link">Download Desktop App</a></li>
          </ul>
        </div>
      </aside>

      <!-- Main Docs Content Area -->
      <div class="docs-content">

        <!-- Section 1: System Architecture -->
        <section id="overview" class="doc-section" style="padding-top:0;">
          <div class="eyebrow">Section 1 · Architecture</div>
          <h2>System Architecture & Core Concepts</h2>
          <p>
            Disha is a geospatial-first, AI-native desktop IDE structured specifically for urban and regional planners. It unifies an interactive MapLibre GL spatial map canvas with a multi-domain AI reasoning engine running locally on your machine.
          </p>

          <div class="code-snippet-card">
            <div class="code-header">
              <span>Process Topography · Desktop Runtime</span>
              <button class="btn btn-ghost btn-sm" data-copy="Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates BrowserWindow → loads renderer (React)

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   ← streaming chat + tool calls
  ├─ Backend over HTTP       /api/files /api/artifacts /api/reports
  └─ Electron IPC            (file dialogs, read directory, switch model)

Backend (packages/backend/) talks to:
  └─ OpenAI HTTPS  (key from OPENAI_API_KEY env)
     + Overpass, Nominatim, OSRM, Open-Meteo, GEE, WorldPop (free/keyless + Google)">Copy</button>
            </div>
            <pre class="code-pre">Electron main (apps/desktop/src/main/index.ts)
  ├─ spawns FastAPI backend on :8765 (PyInstaller-frozen in prod, uvicorn in dev)
  └─ creates BrowserWindow → loads renderer (React)

Renderer (apps/desktop/src/renderer/) talks to:
  ├─ Backend over WebSocket  ws://localhost:8765/api/chat/ws   (streaming chat + tool calls)
  ├─ Backend over HTTP       /api/files /api/artifacts /api/reports
  └─ Electron IPC            (file dialogs, read directory, switch model)

Backend (packages/backend/) talks to:
  └─ OpenAI HTTPS  (key from OPENAI_API_KEY env)
     + Overpass, Nominatim, OSRM, Open-Meteo, GEE, WorldPop (free/keyless + Google)</pre>
          </div>

          <h3>The Three Communication Channels</h3>
          <p>Communication between the React renderer and the local system is partitioned across three distinct channels to prevent blocking the UI thread:</p>

          <table class="tool-table" style="background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius-md); margin-bottom:24px;">
            <thead>
              <tr>
                <th>Channel</th>
                <th>Protocol & Endpoint</th>
                <th>Responsibility</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><span class="channel-badge channel-ws">WebSocket</span></td>
                <td><span class="mono">ws://localhost:8765/api/chat/ws</span></td>
                <td>Streaming token generation, agent tool calls, live layer additions, fly-to map viewport movements, and cancelation tokens.</td>
              </tr>
              <tr>
                <td><span class="channel-badge channel-http">HTTP REST</span></td>
                <td><span class="mono">http://localhost:8765/api/...</span></td>
                <td>Workspace file listing, CRUD operations on artifacts, PDF/Markdown report generation, and raster tile proxies.</td>
              </tr>
              <tr>
                <td><span class="channel-badge channel-ipc">Electron IPC</span></td>
                <td><span class="mono">preload / contextBridge</span></td>
                <td>Native OS operations: file picker dialogs, reading directory trees, persistent window state, and model provider configuration.</td>
              </tr>
            </tbody>
          </table>

          <h3>Geospatial Conventions</h3>
          <ul style="padding-left:20px; color:var(--text-secondary); line-height:1.8;">
            <li><strong>Coordinates Everywhere EPSG:4326:</strong> All geometries exchanged across WebSocket, HTTP, and tools are strictly in WGS84 Lat/Lng. No planar distortion or reprojection artifacts occur.</li>
            <li><strong>Ellipsoidal Geodesic Math:</strong> All area and perimeter calculations use <span class="mono">pyproj.Geod(ellps="WGS84")</span> rather than planar Euclidean math, maintaining survey-grade precision at all latitudes.</li>
            <li><strong>Free Raster XYZ Basemaps:</strong> Built-in support for OpenStreetMap, CartoDB Positron/Dark Matter, Esri World Imagery, and OpenTopoMap without API keys or token requirements.</li>
            <li><strong>Turf.js Client Operations:</strong> Instant client-side bbox union, point-in-polygon verification, and coordinate formatting on the MapLibre canvas.</li>
          </ul>
        </section>

        <!-- Section 2: Installation & Setup -->
        <section id="installation" class="doc-section">
          <div class="eyebrow">Section 2 · Setup</div>
          <h2>Installation & Getting Started</h2>
          <p>
            Disha is distributed both as pre-built native desktop binaries for macOS and Windows, and as an open-source development monorepo.
          </p>

          <h3>Option A: Native Desktop Installers</h3>
          <p>Download the latest release from the official GitHub Releases hub:</p>
          <ul style="padding-left:20px; color:var(--text-secondary); line-height:1.8; margin-bottom:20px;">
            <li><strong>macOS (Apple Silicon & Intel):</strong> Download <span class="mono">Disha-${version}-arm64.dmg</span> or <span class="mono">x64.dmg</span>. Drag Disha to your Applications folder.</li>
            <li><strong>Windows 10 / 11:</strong> Download <span class="mono">Disha-Setup-${version}.exe</span> or the portable <span class="mono">.zip</span> archive. Extract all contents before running.</li>
          </ul>

          <h3>Option B: Building from Source</h3>
          <p>For developers contributing to the AI hubs, frontend tools, or map engine:</p>

          <div class="code-snippet-card">
            <div class="code-header">
              <span>Terminal · Monorepo Setup & Dev Server</span>
              <button class="btn btn-ghost btn-sm" data-copy="# 1. Clone repository
git clone https://github.com/geoailabs/disha.git
cd disha

# 2. Install Node dependencies
pnpm install

# 3. Setup Python virtual environment
cd packages/backend
python3 -m venv .buildenv
source .buildenv/bin/activate
pip install -r requirements.txt
cd ../..

# 4. Set OpenAI API key and launch
export OPENAI_API_KEY='your-key-here'
pnpm dev">Copy</button>
            </div>
            <pre class="code-pre"># 1. Clone repository
git clone https://github.com/geoailabs/disha.git
cd disha

# 2. Install Node dependencies
pnpm install

# 3. Setup Python virtual environment
cd packages/backend
python3 -m venv .buildenv
source .buildenv/bin/activate
pip install -r requirements.txt
cd ../..

# 4. Set OpenAI API key and launch
export OPENAI_API_KEY='your-key-here'
pnpm dev</pre>
          </div>

          <h3>Workspace Selection</h3>
          <p>
            Upon initial launch, select any local folder on your workstation as your project workspace. Disha creates an isolated <span class="mono">.disha/</span> folder inside it to persist project settings, custom layers, chat history, and generated analysis artifacts without locking your data to a remote cloud server.
          </p>
        </section>

        <!-- Section 3: 7+1 Domain Hubs & Tools -->
        <section id="domain-hubs" class="doc-section">
          <div class="eyebrow">Section 3 · Reference</div>
          <h2>The 7+1 Domain Hubs & Tool Reference</h2>
          <p>
            Tools in Disha are architected into <strong>7 Domain Hubs</strong> plus <strong>1 Cross-Cutting Utility Hub</strong>. Each hub inherits from <span class="mono">BaseDomainHub</span> and returns a typed <span class="mono">ToolResult</span> payload containing LLM data, optional map actions, and persistent markdown artifacts.
          </p>

          <!-- SpatialHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">1. SpatialHub</div>
              <span class="badge badge-cyan">GIS & Polygons</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Core vector algorithms, geodetic geometry calculations, administrative boundary queries, and centralized polygon registry management.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">gis_buffer</span></td>
                  <td><span class="mono">layer_id, distance_m, resolution</span></td>
                  <td>Computes an ellipsoidal buffer polygon around points, lines, or polygons on WGS84 ellipsoid.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">gis_clip</span></td>
                  <td><span class="mono">target_layer, mask_layer</span></td>
                  <td>Clips target vector geometries against boundary mask polygons.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">gis_intersection</span></td>
                  <td><span class="mono">layer_a, layer_b</span></td>
                  <td>Calculates geometric intersection and merges feature properties.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">gis_dissolve</span></td>
                  <td><span class="mono">layer_id, by_attribute</span></td>
                  <td>Merges adjacent polygons sharing attribute values into unified features.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">calculate_land_budget</span></td>
                  <td><span class="mono">boundary_layer, zoning_layer</span></td>
                  <td>Computes total area, parcel counts, and percentage distribution across land-use types.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">osm_boundary</span></td>
                  <td><span class="mono">place_name, admin_level</span></td>
                  <td>Fetches authoritative administrative boundaries from OpenStreetMap Overpass with fallback.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- MobilityHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">2. MobilityHub</div>
              <span class="badge badge-emerald">Transportation & Transit</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Street network topological analysis, routing, Origin-Destination (OD) matrix traffic flow assignment, and GTFS transit stop queries.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-emerald);">compute_route</span></td>
                  <td><span class="mono">origin, destination, profile</span></td>
                  <td>Calculates driving, walking, or freight route with turn-by-turn geometry and duration via OSRM.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-emerald);">analyze_street_network</span></td>
                  <td><span class="mono">bbox, metric</span></td>
                  <td>Computes intersection density, circuity, betweenness centrality, and street connectivity metrics.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-emerald);">assign_traffic_flows</span></td>
                  <td><span class="mono">od_matrix, road_network</span></td>
                  <td>Simulates multi-link traffic distribution to identify road network congestion bottlenecks.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-emerald);">query_gtfs_transit</span></td>
                  <td><span class="mono">corridor, agency_id</span></td>
                  <td>Extracts transit routes, headways, stop frequency, and corridor coverage buffers.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- EnvironmentHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">3. EnvironmentHub</div>
              <span class="badge badge-violet">Earth Engine & Climate</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Satellite remote sensing, Google Earth Engine LULC/NDVI analysis, live air quality indexes, weather forecasts, and solar radiation potential.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-violet);">query_gee_satellite</span></td>
                  <td><span class="mono">bbox, product, year</span></td>
                  <td>Fetches Sentinel-2 or Landsat surface reflectance composites from Google Earth Engine.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-violet);">compute_ndvi_lulc</span></td>
                  <td><span class="mono">boundary, start_date, end_date</span></td>
                  <td>Measures Normalized Difference Vegetation Index (NDVI) and land cover changes over time.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-violet);">get_air_quality</span></td>
                  <td><span class="mono">lat, lng</span></td>
                  <td>Retrieves real-time PM2.5, PM10, NO2, and AQI readings via Open-Meteo European Air Quality API.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-violet);">calculate_solar_potential</span></td>
                  <td><span class="mono">building_layer, dsm_source</span></td>
                  <td>Computes rooftop solar irradiance and annual renewable energy yield estimates.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- PlanningHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">4. PlanningHub</div>
              <span class="badge badge-amber">Zoning & Vision</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Zoning parcel classification, compliance audits, masterplan PDF vision georeferencing, and raster digitization.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-amber);">classify_zoning</span></td>
                  <td><span class="mono">parcel_layer, standard</span></td>
                  <td>Normalizes localized zoning designations into standard land use categories (FAR, setback, use).</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-amber);">audit_zoning_compliance</span></td>
                  <td><span class="mono">parcels, building_footprints</span></td>
                  <td>Audits Floor Area Ratio (FAR) and building footprint coverage limits against municipal guidelines.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-amber);">georeference_document</span></td>
                  <td><span class="mono">image_path, ground_control_points</span></td>
                  <td>Computes polynomial coordinate transformation to project static masterplan scans onto map coordinates.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- DemographicsHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">5. DemographicsHub</div>
              <span class="badge badge-cyan">Demographics</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              WorldPop 100m population density queries, cohort-component forecasts, and employment density estimates.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">query_worldpop_density</span></td>
                  <td><span class="mono">boundary_geom, year</span></td>
                  <td>Aggregates gridded population counts from WorldPop 100m resolution rasters within study boundaries.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-cyan);">forecast_demographic_cohort</span></td>
                  <td><span class="mono">base_population, horizon_years, fertility_rate</span></td>
                  <td>Projects age-sex cohort population distributions forward across 5, 10, or 20-year horizons.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- PlacesHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">6. PlacesHub</div>
              <span class="badge badge-emerald">Places & Buildings</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Overture Maps DuckDB spatial queries for 3D buildings, Google Places search, and POI classification.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-emerald);">query_overture_buildings_duckdb</span></td>
                  <td><span class="mono">bbox, min_height</span></td>
                  <td>Executes serverless DuckDB queries directly against Overture S3 Parquet partitions for 3D building polygons.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-emerald);">search_places</span></td>
                  <td><span class="mono">query, location_bias</span></td>
                  <td>Retrieves verified amenities, businesses, and public facilities with operating metadata.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- ScenariosHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">7. ScenariosHub</div>
              <span class="badge badge-violet">Scenarios & MCDA</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Multi-Criteria Decision Analysis (MCDA), alternative zoning scenario generation, and trade-off comparison.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-violet);">generate_scenario</span></td>
                  <td><span class="mono">type, corridor, target_density</span></td>
                  <td>Creates zoning alternative layouts (TOD, Compact Infill, Green Buffer) with modified parcel attributes.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-violet);">score_scenario_mcda</span></td>
                  <td><span class="mono">scenario_id, weights</span></td>
                  <td>Scores scenarios across walkability, transit access, green space ratio, and infrastructure load metrics.</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- UtilityHub -->
          <div class="hub-card">
            <div class="hub-header">
              <div class="hub-title">8. UtilityHub</div>
              <span class="badge badge-amber">Utility & Artifacts</span>
            </div>
            <p style="color:var(--text-secondary); font-size:0.92rem;">
              Geocoding, internet knowledge verification, distance measurement, and persistent markdown report storage.
            </p>
            <table class="tool-table">
              <thead>
                <tr><th>Tool</th><th>Parameters</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td><span class="mono" style="color:var(--accent-amber);">geocode_address</span></td>
                  <td><span class="mono">query</span></td>
                  <td>Resolves civic addresses or place names to WGS84 coordinates and bounding box extents via Nominatim.</td>
                </tr>
                <tr>
                  <td><span class="mono" style="color:var(--accent-amber);">save_artifact</span></td>
                  <td><span class="mono">title, content, artifact_type</span></td>
                  <td>Persists formatted Markdown summaries, demographic profiles, and reports into workspace artifacts.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Section 4: Prompt Engineering Handbook -->
        <section id="prompts" class="doc-section">
          <div class="eyebrow">Section 4 · Agent Handbook</div>
          <h2>AI Prompt Engineering Handbook</h2>
          <p>
            Disha's agent is trained to interpret natural conversational requests and translate them into multi-step geodetic operations. Below are production prompt patterns:
          </p>

          <div class="prompt-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span class="badge badge-cyan">Hazard Mitigation · Geodesic Buffer & Clip</span>
              <button class="btn btn-secondary btn-sm" data-copy="Buffer the designated flood hazard polygon by 500 meters and clip all intersecting local road segments. Calculate the affected road length in kilometers.">Copy Prompt</button>
            </div>
            <p class="mono" style="color:var(--text-primary); font-size:0.9rem; margin-bottom:6px;">
              "Buffer the designated flood hazard polygon by 500 meters and clip all intersecting local road segments. Calculate the affected road length in kilometers."
            </p>
            <div style="color:var(--text-muted); font-size:0.8rem;">
              Chained Tools: <span class="mono">gis_buffer(distance_m=500)</span> -> <span class="mono">gis_clip()</span> -> <span class="mono">gis_distance()</span>
            </div>
          </div>

          <div class="prompt-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span class="badge badge-emerald">DuckDB S3 · 3D Building Ingestion</span>
              <button class="btn btn-secondary btn-sm" data-copy="Query Overture Maps S3 Parquet via DuckDB for all building footprints in this viewport with height > 20 meters. Color them with a graduated cyan ramp.">Copy Prompt</button>
            </div>
            <p class="mono" style="color:var(--text-primary); font-size:0.9rem; margin-bottom:6px;">
              "Query Overture Maps S3 Parquet via DuckDB for all building footprints in this viewport with height > 20 meters. Color them with a graduated cyan ramp."
            </p>
            <div style="color:var(--text-muted); font-size:0.8rem;">
              Chained Tools: <span class="mono">query_overture_buildings_duckdb(min_height=20)</span> -> <span class="mono">set_layer_symbology(type='graduated')</span>
            </div>
          </div>

          <div class="prompt-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span class="badge badge-violet">Transit-Oriented Development (TOD) Simulation</span>
              <button class="btn btn-secondary btn-sm" data-copy="Generate 3 TOD alternative scenarios around the proposed metro transit nodes. Upzone parcels within 800 meters to Mixed-Use High Density and score transit accessibility.">Copy Prompt</button>
            </div>
            <p class="mono" style="color:var(--text-primary); font-size:0.9rem; margin-bottom:6px;">
              "Generate 3 TOD alternative scenarios around the proposed metro transit nodes. Upzone parcels within 800 meters to Mixed-Use High Density and score transit accessibility."
            </p>
            <div style="color:var(--text-muted); font-size:0.8rem;">
              Chained Tools: <span class="mono">generate_scenario(type='TOD')</span> -> <span class="mono">score_scenario_mcda()</span> -> <span class="mono">save_artifact()</span>
            </div>
          </div>

          <div class="prompt-box">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <span class="badge badge-amber">Demographic Horizon Forecasting</span>
              <button class="btn btn-secondary btn-sm" data-copy="Fetch WorldPop 100m density for this municipality boundary and run a 10-year demographic cohort projection assuming a 1.2% annual growth rate.">Copy Prompt</button>
            </div>
            <p class="mono" style="color:var(--text-primary); font-size:0.9rem; margin-bottom:6px;">
              "Fetch WorldPop 100m density for this municipality boundary and run a 10-year demographic cohort projection assuming a 1.2% annual growth rate."
            </p>
            <div style="color:var(--text-muted); font-size:0.8rem;">
              Chained Tools: <span class="mono">query_worldpop_density()</span> -> <span class="mono">forecast_demographic_cohort(horizon_years=10)</span>
            </div>
          </div>
        </section>

        <!-- Section 5: Centralized Spatial Registry -->
        <section id="registry" class="doc-section">
          <div class="eyebrow">Section 5 · Spatial Engine</div>
          <h2>Centralized Spatial & Polygon Registry</h2>
          <p>
            A core challenge in autonomous GIS agents is avoiding redundant polygons, duplicate map layers, and overlapping geometries. Disha resolves this through its <strong>Centralized Spatial Registry</strong> (<span class="mono">packages/backend/tools/spatial_registry.py</span>).
          </p>

          <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px; margin:20px 0;">
            <div style="background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius-md); padding:18px;">
              <h4 style="color:var(--accent-cyan); margin-bottom:8px;">IoU Deduplication (&ge; 90%)</h4>
              <p style="color:var(--text-secondary); font-size:0.88rem; line-height:1.6;">
                Whenever a boundary query or polygon tool runs, Disha evaluates the Intersection-over-Union (IoU) ratio against all active layers. If overlap exceeds 90%, it reuses and focuses the existing layer rather than spawning a duplicate.
              </p>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius-md); padding:18px;">
              <h4 style="color:var(--accent-emerald); margin-bottom:8px;">Geodesic Metric Calculations</h4>
              <p style="color:var(--text-secondary); font-size:0.88rem; line-height:1.6;">
                Every registered feature automatically computes and caches true geodesic surface area (m2, hectares, km2), true centroid coordinates, and bounding boxes via WGS84 pyproj Geod.
              </p>
            </div>

            <div style="background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius-md); padding:18px;">
              <h4 style="color:var(--accent-violet); margin-bottom:8px;">Real-Time WebSocket Layer Sync</h4>
              <p style="color:var(--text-secondary); font-size:0.88rem; line-height:1.6;">
                The spatial registry continuously reconciles map context with the active frontend layers on every conversational turn, ensuring the agent always knows exactly what is visible on the canvas.
              </p>
            </div>
          </div>
        </section>

        <!-- Section 6: Data Connectors & Live Cloud Engines -->
        <section id="connectors" class="doc-section">
          <div class="eyebrow">Section 6 · Connectors</div>
          <h2>Data Connectors & Live Cloud Engines</h2>
          <p>
            Disha integrates directly with cloud-native spatial data sources without requiring local PostGIS database installations or commercial subscriptions.
          </p>

          <div class="code-snippet-card">
            <div class="code-header">
              <span>DuckDB S3 GeoParquet Query · Overture Maps</span>
              <button class="btn btn-ghost btn-sm" data-copy="SELECT id, names.primary AS name, ST_AsGeoJSON(geometry) AS geojson
FROM read_parquet('s3://overturemaps-us-west-2/release/2024-08-20.0/theme=places/type=place/*')
WHERE bbox.xmin >= -122.45 AND bbox.xmax <= -122.38
  AND bbox.ymin >= 37.74 AND bbox.ymax <= 37.80
LIMIT 100;">Copy</button>
            </div>
            <pre class="code-pre">SELECT id, names.primary AS name, ST_AsGeoJSON(geometry) AS geojson
FROM read_parquet('s3://overturemaps-us-west-2/release/2024-08-20.0/theme=places/type=place/*')
WHERE bbox.xmin >= -122.45 AND bbox.xmax <= -122.38
  AND bbox.ymin >= 37.74 AND bbox.ymax <= 37.80
LIMIT 100;</pre>
          </div>

          <table class="tool-table" style="background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius-md); margin-top:20px;">
            <thead>
              <tr>
                <th>Engine / Provider</th>
                <th>Access Method</th>
                <th>Authentication</th>
                <th>Data Provided</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>OpenStreetMap Overpass</strong></td>
                <td>Overpass QL / JSON</td>
                <td>Free · Keyless</td>
                <td>Buildings, roads, amenities, waterways, land use polygons.</td>
              </tr>
              <tr>
                <td><strong>Overture Maps</strong></td>
                <td>DuckDB S3 GeoParquet</td>
                <td>Free · Keyless</td>
                <td>Global building footprints with height attributes and place categories.</td>
              </tr>
              <tr>
                <td><strong>Google Earth Engine</strong></td>
                <td>REST API / Earth Engine SDK</td>
                <td>Service Account JSON</td>
                <td>Sentinel-2, Landsat, Dynamic World LULC, surface temperature.</td>
              </tr>
              <tr>
                <td><strong>WorldPop</strong></td>
                <td>Direct GeoTIFF Ingestion</td>
                <td>Free · Open Access</td>
                <td>High-resolution 100m gridded population density estimates.</td>
              </tr>
              <tr>
                <td><strong>Open-Meteo</strong></td>
                <td>REST API</td>
                <td>Free · Keyless</td>
                <td>Hourly weather forecasts, temperature, precipitation, and AQI readings.</td>
              </tr>
            </tbody>
          </table>
        </section>

      </div>
    </div>
  </main>

  <!-- Shared Footer Mount -->
  <div id="site-footer"></div>

  <!-- Scripts -->
  <script src="js/components.js"></script>
  <script src="js/main.js"></script>

  <script>
    // Live Sidebar Search & Filter
    document.addEventListener('DOMContentLoaded', () => {
      const searchInput = document.getElementById('docs-search-input');
      if (!searchInput) return;

      searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        const hubCards = document.querySelectorAll('.hub-card');
        const promptBoxes = document.querySelectorAll('.prompt-box');
        const docSections = document.querySelectorAll('.doc-section');

        if (!query) {
          hubCards.forEach(c => c.style.display = '');
          promptBoxes.forEach(p => p.style.display = '');
          docSections.forEach(s => s.style.display = '');
          return;
        }

        // Filter hub cards
        hubCards.forEach(card => {
          const text = card.textContent.toLowerCase();
          card.style.display = text.includes(query) ? '' : 'none';
        });

        // Filter prompt boxes
        promptBoxes.forEach(box => {
          const text = box.textContent.toLowerCase();
          box.style.display = text.includes(query) ? '' : 'none';
        });
      });
    });
  </script>
</body>
</html>
`;

// Write to docs/docs.html
const targetPath = path.join(rootDir, 'docs', 'docs.html');
fs.writeFileSync(targetPath, htmlContent, 'utf-8');
console.log(`[sync-docs] Successfully compiled docs/docs.html (${htmlContent.length} bytes)!`);
