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
  const [saveStatus, setSaveStatus] = useState<string | null>(null)

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
        window.electronAPI.getGoogleMapsKey().catch(() => '')
      ]).then(([oKey, gKey]) => {
        if (oKey) setOpenaiInput(oKey)
        if (gKey) setGoogleInput(gKey)
        runChecks()
      })
    } else {
      runChecks()
    }
  }, [])

  const handleSaveKeys = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaveStatus('Saving keys...')
    try {
      if (window.electronAPI) {
        await window.electronAPI.setAPIKey(openaiInput.trim())
        await window.electronAPI.setGoogleMapsKey(googleInput.trim())
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
        return <span className="diag-badge pass">✔ PASS</span>
      case 'missing':
        return <span className="diag-badge warn">⚠ ACTION REQUIRED</span>
      case 'degraded':
      case 'configured':
        return <span className="diag-badge warn">⚡ DEGRADED</span>
      case 'invalid':
      case 'offline':
        return <span className="diag-badge fail">✖ FAIL</span>
      default:
        return <span className="diag-badge checking">⏱ CHECKING</span>
    }
  }

  return (
    <div className="diag-modal-overlay">
      <div className="diag-modal-card">
        <header className="diag-header">
          <h2>System Diagnostics & Setup</h2>
          <button className="diag-close-btn" onClick={onClose}>✕</button>
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
                  <div className="diag-meta">
                    <strong>OpenAI API Connection</strong>
                    <span>{data.openai_api_key.message}</span>
                  </div>
                  {getStatusIcon(data.openai_api_key.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>Google Maps Street View API</strong>
                    <span>{data.google_maps_api_key.message}</span>
                  </div>
                  {getStatusIcon(data.google_maps_api_key.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>OSM Overpass API</strong>
                    <span>{data.overpass_api.message}</span>
                  </div>
                  {getStatusIcon(data.overpass_api.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>Nominatim Geocoder API</strong>
                    <span>{data.nominatim_api.message}</span>
                  </div>
                  {getStatusIcon(data.nominatim_api.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>OSRM Routing Server</strong>
                    <span>{data.osrm_api.message}</span>
                  </div>
                  {getStatusIcon(data.osrm_api.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>Open-Meteo Weather Forecast</strong>
                    <span>{data.open_meteo.message}</span>
                  </div>
                  {getStatusIcon(data.open_meteo.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>Required Python GIS Libraries</strong>
                    <span>{data.libraries.message}</span>
                  </div>
                  {getStatusIcon(data.libraries.status)}
                </div>

                <div className="diag-item">
                  <div className="diag-meta">
                    <strong>Workspace Write Access</strong>
                    <span>{data.workspace.message}</span>
                  </div>
                  {getStatusIcon(data.workspace.status)}
                </div>
              </div>
            )}
            <button className="diag-retry-btn" onClick={runChecks} disabled={loading}>
              Run Checks again
            </button>
          </section>

          <section className="diag-section credentials-form">
            <h3>API Keys Setup</h3>
            <form onSubmit={handleSaveKeys}>
              <div className="form-group">
                <label htmlFor="openai_key">OpenAI API Key</label>
                <input
                  type="password"
                  id="openai_key"
                  placeholder="sk-proj-..."
                  value={openaiInput}
                  onChange={(e) => setOpenaiInput(e.target.value)}
                />
              </div>

              <div className="form-group">
                <label htmlFor="google_key">Google Maps API Key</label>
                <input
                  type="password"
                  id="google_key"
                  placeholder="AIzaSy..."
                  value={googleInput}
                  onChange={(e) => setGoogleInput(e.target.value)}
                />
              </div>

              <div className="form-actions">
                <button type="submit" className="diag-save-btn">
                  Save Credentials
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
