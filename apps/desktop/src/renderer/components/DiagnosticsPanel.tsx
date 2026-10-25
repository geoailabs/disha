import { useEffect, useState, useCallback } from 'react'
import './DiagnosticsPanel.css'

interface DiagnosticStatus {
  status: 'valid' | 'invalid' | 'online' | 'offline' | 'degraded' | 'missing' | 'configured' | 'checking'
  message: string
}

interface DiagnosticsData {
  openai_api_key: DiagnosticStatus
  google_maps_api_key: DiagnosticStatus
  overpass_api: DiagnosticStatus
  nominatim_api: DiagnosticStatus
  osrm_api: DiagnosticStatus
  open_meteo: DiagnosticStatus
  libraries: DiagnosticStatus
  workspace: DiagnosticStatus
}

interface DiagnosticsPanelProps {
  onClose: () => void
  workspacePath: string | null
}

export default function DiagnosticsPanel({ onClose, workspacePath }: DiagnosticsPanelProps) {
  const [data, setData] = useState<DiagnosticsData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // API Key Inputs
  const [openaiInput, setOpenaiInput] = useState('')
  const [googleInput, setGoogleInput] = useState('')
  const [geeInput, setGeeInput] = useState('')
  const [mapillaryInput, setMapillaryInput] = useState('')
  const [showOpenai, setShowOpenai] = useState(false)
  const [showGoogle, setShowGoogle] = useState(false)
  const [showMapillary, setShowMapillary] = useState(false)
  const [saveStatus, setSaveStatus] = useState<string | null>(null)

  const normalizeKey = (k: string, prefixRegex?: RegExp) => {
    let s = (k || '').trim()
    if (prefixRegex) s = s.replace(prefixRegex, '')
    s = s.replace(/^Bearer\s+/i, '')
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'")) || (s.startsWith('`') && s.endsWith('`'))) {
      s = s.slice(1, -1).trim()
    }
    return s.replace(/[^\x20-\x7E]/g, '').trim()
  }

  const runChecks = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      let storedOpenAI = openaiInput.trim()
      let storedGoogle = googleInput.trim()
      if (!storedOpenAI && window.electronAPI) {
        storedOpenAI = (await window.electronAPI.getAPIKey()) || ''
      }
      if (!storedGoogle && window.electronAPI) {
        storedGoogle = (await window.electronAPI.getGoogleMapsKey()) || ''
      }

      const params = new URLSearchParams()
      if (workspacePath) params.set('workspace_path', workspacePath)
      if (storedOpenAI) params.set('openai_api_key', storedOpenAI)
      if (storedGoogle) params.set('google_maps_api_key', storedGoogle)

      const queryStr = params.toString()
      const url = `http://localhost:8765/api/diagnostics${queryStr ? `?${queryStr}` : ''}`
      const resp = await fetch(url)
      if (!resp.ok) throw new Error(`HTTP error ${resp.status}`)
      const json = await resp.json()
      setData(json)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [workspacePath, openaiInput, googleInput])

  useEffect(() => {
    // Load initial stored keys from Electron secure storage
    if (window.electronAPI) {
      Promise.all([
        window.electronAPI.getAPIKey().catch(() => ''),
        window.electronAPI.getGoogleMapsKey().catch(() => ''),
        window.electronAPI.getGEEKey().catch(() => ''),
        window.electronAPI.getMapillaryKey ? window.electronAPI.getMapillaryKey().catch(() => '') : Promise.resolve('')
      ]).then(([oKey, gKey, geeKey, mKey]) => {
        const cleanO = normalizeKey(oKey || '', /^(?:export\s+)?(?:OPENAI_API_KEY)\s*=\s*/i)
        const cleanG = normalizeKey(gKey || '', /^(?:export\s+)?(?:GOOGLE_MAPS_API_KEY|GOOGLE_API_KEY)\s*=\s*/i)
        const cleanGee = (geeKey || '').trim().replace(/[^\x20-\x7E\r\n\t]/g, '')
        const cleanM = normalizeKey(mKey || '', /^(?:export\s+)?(?:MAPILLARY_ACCESS_TOKEN|MAPILLARY_CLIENT_TOKEN)\s*=\s*/i)
        if (cleanO) setOpenaiInput(cleanO)
        if (cleanG) setGoogleInput(cleanG)
        if (cleanGee) setGeeInput(cleanGee)
        if (cleanM) setMapillaryInput(cleanM)
        runChecks()
      })
    } else {
      runChecks()
    }
  }, [])

  const handleImportGeeFile = async () => {
    if (!window.electronAPI?.openFile) return
    try {
      const filePath = await window.electronAPI.openFile({
        filters: [{ name: 'JSON Files', extensions: ['json'] }]
      })
      if (!filePath) return
      const content = await window.electronAPI.readFile(filePath)
      if (content) {
        try {
          const parsed = JSON.parse(content)
          if (parsed && typeof parsed === 'object') {
            setGeeInput(JSON.stringify(parsed, null, 2))
          }
        } catch {
          setGeeInput(content)
        }
      }
    } catch (err) {
      console.warn('Failed to import GEE file:', err)
    }
  }

  const handleSaveKeys = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveStatus('Saving keys...')
    const cleanO = normalizeKey(openaiInput, /^(?:export\s+)?(?:OPENAI_API_KEY)\s*=\s*/i)
    const cleanG = normalizeKey(googleInput, /^(?:export\s+)?(?:GOOGLE_MAPS_API_KEY|GOOGLE_API_KEY)\s*=\s*/i)
    const cleanGee = (geeInput || '').trim().replace(/[^\x20-\x7E\r\n\t]/g, '')
    const cleanM = normalizeKey(mapillaryInput, /^(?:export\s+)?(?:MAPILLARY_ACCESS_TOKEN|MAPILLARY_CLIENT_TOKEN)\s*=\s*/i)

    setOpenaiInput(cleanO)
    setGoogleInput(cleanG)
    setGeeInput(cleanGee)
    setMapillaryInput(cleanM)

    try {
      if (window.electronAPI) {
        await window.electronAPI.setAPIKey(cleanO)
        await window.electronAPI.setGoogleMapsKey(cleanG)
        await window.electronAPI.setGEEKey(cleanGee)
        if (window.electronAPI.setMapillaryKey) {
          await window.electronAPI.setMapillaryKey(cleanM)
        }

        // Immediately sync keys to the running Python backend process
        try {
          await fetch('http://localhost:8765/api/chat/sync-keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              openai_api_key: cleanO,
              google_maps_api_key: cleanG,
              gee_credentials: cleanGee,
              mapillary_token: cleanM,
            }),
          })
        } catch (syncErr) {
          console.warn('Could not sync keys to backend:', syncErr)
        }

        // Broadcast to ChatPanel and other components
        window.dispatchEvent(
          new CustomEvent('disha-api-keys-updated', {
            detail: { openai: cleanO, google: cleanG, gee: cleanGee, mapillary: cleanM },
          })
        )

        setSaveStatus('Keys saved successfully! Re-running checks...')
        setTimeout(() => setSaveStatus(null), 3000)
        // Trigger check run
        await runChecks()
      } else {
        setSaveStatus('Electron API is not available.')
      }
    } catch (err) {
      setSaveStatus(`Failed to save keys: ${err}`)
    }
  }

  const getStatusIcon = (status?: string) => {
    switch (status) {
      case 'valid':
      case 'online':
        return <span className="diag-badge pass">PASS</span>
      case 'missing':
        return <span className="diag-badge warn">ACTION REQUIRED</span>
      case 'degraded':
      case 'configured':
        return <span className="diag-badge warn">DEGRADED</span>
      case 'invalid':
      case 'offline':
        return <span className="diag-badge fail">FAIL</span>
      default:
        return <span className="diag-badge checking">CHECKING</span>
    }
  }

  return (
    <div className="diag-modal-overlay">
      <div className="diag-modal-card">
        <header className="diag-header">
          <h2>System Diagnostics & Setup</h2>
          <button className="diag-close-btn" onClick={onClose} title="Close Diagnostics">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </header>

        <main className="diag-body">
          <p className="diag-intro">
            This dashboard checks reachability of all necessary APIs, libraries, and keys. Configure any missing credentials below.
          </p>

          <section className="diag-section">
            <h3>Diagnostic Health Checks</h3>
            {loading && <div className="diag-status">Running checks...</div>}
            {error && <div className="diag-status diag-error">Connection to backend failed: {error}</div>}
            
            {data && (
              <div className="diag-grid">
                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>OpenAI API Connection</strong>
                    {getStatusIcon(data.openai_api_key.status)}
                  </div>
                  <span className="diag-item-desc">{data.openai_api_key.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>Google Maps Street View API</strong>
                    {getStatusIcon(data.google_maps_api_key.status)}
                  </div>
                  <span className="diag-item-desc">{data.google_maps_api_key.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>OSM Overpass API</strong>
                    {getStatusIcon(data.overpass_api.status)}
                  </div>
                  <span className="diag-item-desc">{data.overpass_api.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>Nominatim Geocoder API</strong>
                    {getStatusIcon(data.nominatim_api.status)}
                  </div>
                  <span className="diag-item-desc">{data.nominatim_api.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>OSRM Routing Server</strong>
                    {getStatusIcon(data.osrm_api.status)}
                  </div>
                  <span className="diag-item-desc">{data.osrm_api.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>Open-Meteo Weather Forecast</strong>
                    {getStatusIcon(data.open_meteo.status)}
                  </div>
                  <span className="diag-item-desc">{data.open_meteo.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>Required Python GIS Libraries</strong>
                    {getStatusIcon(data.libraries.status)}
                  </div>
                  <span className="diag-item-desc">{data.libraries.message}</span>
                </div>

                <div className="diag-item">
                  <div className="diag-item-header">
                    <strong>Workspace Write Access</strong>
                    {getStatusIcon(data.workspace.status)}
                  </div>
                  <span className="diag-item-desc">{data.workspace.message}</span>
                </div>
              </div>
            )}
            <button className="diag-retry-btn" onClick={runChecks} disabled={loading}>
              Run Checks again
            </button>
          </section>

          <section className="diag-section credentials-form">
            <h3>API Keys & Credentials Setup</h3>
            <form onSubmit={handleSaveKeys}>
              <div className="form-group">
                <label htmlFor="openai_key">OpenAI API Key (Required for AI Chat & Reasoning)</label>
                <div className="input-row">
                  <input
                    type={showOpenai ? 'text' : 'password'}
                    id="openai_key"
                    placeholder="sk-proj-..."
                    value={openaiInput}
                    onChange={(e) => setOpenaiInput(e.target.value)}
                    autoComplete="off"
                    spellCheck="false"
                  />
                  <button
                    type="button"
                    className="input-toggle-btn"
                    onClick={() => setShowOpenai((v) => !v)}
                  >
                    {showOpenai ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="google_key">Google Maps API Key (Optional — for Street View & Places)</label>
                <div className="input-row">
                  <input
                    type={showGoogle ? 'text' : 'password'}
                    id="google_key"
                    placeholder="AIzaSy..."
                    value={googleInput}
                    onChange={(e) => setGoogleInput(e.target.value)}
                    autoComplete="off"
                    spellCheck="false"
                  />
                  <button
                    type="button"
                    className="input-toggle-btn"
                    onClick={() => setShowGoogle((v) => !v)}
                  >
                    {showGoogle ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>

              <div className="form-group">
                <div className="label-row">
                  <label htmlFor="gee_key">Google Earth Engine Service Account JSON (Optional — for Satellite & LULC)</label>
                  <button
                    type="button"
                    className="import-json-btn"
                    onClick={handleImportGeeFile}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                    Import JSON File
                  </button>
                </div>
                <textarea
                  id="gee_key"
                  placeholder='{ "type": "service_account", "project_id": "...", "private_key": "..." }'
                  value={geeInput}
                  onChange={(e) => setGeeInput(e.target.value)}
                  autoComplete="off"
                  spellCheck="false"
                />
              </div>

              <div className="form-group">
                <label htmlFor="mapillary_key">Mapillary Access Token (Optional — for Community Street View Imagery)</label>
                <div className="input-row">
                  <input
                    type={showMapillary ? 'text' : 'password'}
                    id="mapillary_key"
                    placeholder="MLY|..."
                    value={mapillaryInput}
                    onChange={(e) => setMapillaryInput(e.target.value)}
                    autoComplete="off"
                    spellCheck="false"
                  />
                  <button
                    type="button"
                    className="input-toggle-btn"
                    onClick={() => setShowMapillary((v) => !v)}
                  >
                    {showMapillary ? 'Hide' : 'Show'}
                  </button>
                </div>
              </div>

              <div className="form-actions">
                <button type="submit" className="diag-save-btn">
                  Save All Credentials
                </button>
              </div>

              {saveStatus && <p className="form-status-msg">{saveStatus}</p>}
            </form>
          </section>
        </main>
      </div>
    </div>
  )
}
