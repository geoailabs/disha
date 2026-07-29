import { app, BrowserWindow, ipcMain, dialog, shell, protocol, net, safeStorage } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'
import os from 'os'

const BACKEND_PORT = 8765
const isDev = !app.isPackaged

function envFileCandidates(): string[] {
  return Array.from(new Set([
    path.resolve(process.cwd(), '.env'),
    path.resolve(process.cwd(), 'packages/backend/.env'),
    path.resolve(process.cwd(), '../../.env'),
    path.resolve(process.cwd(), '../../packages/backend/.env'),
    path.resolve(__dirname, '../../../.env'),
    path.resolve(__dirname, '../../../packages/backend/.env'),
    path.resolve(__dirname, '../../../../.env'),
    path.resolve(__dirname, '../../../../packages/backend/.env'),
  ]))
}

function readEnvFileValue(filePath: string, names: string[]): string {
  try {
    if (!fs.existsSync(filePath)) return ''
    const lines = fs.readFileSync(filePath, 'utf-8').split(/\r?\n/)
    for (const rawLine of lines) {
      const line = rawLine.trim()
      if (!line || line.startsWith('#')) continue
      const cleaned = line.startsWith('export ') ? line.slice(7).trim() : line
      const eq = cleaned.indexOf('=')
      if (eq === -1) continue
      const key = cleaned.slice(0, eq).trim()
      if (!names.includes(key)) continue
      let value = cleaned.slice(eq + 1).trim()
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1)
      }
      return value.trim()
    }
  } catch {
    /* ignore malformed env files */
  }
  return ''
}

function readEnvValue(names: string[]): string {
  for (const name of names) {
    const value = (process.env[name] || '').trim()
    if (value) return value
  }
  for (const filePath of envFileCandidates()) {
    const value = readEnvFileValue(filePath, names)
    if (value) return value
  }
  return ''
}

function getKeyStatus(): { openai: boolean; google_maps: boolean } {
  return {
    openai: !!readEnvValue(['OPENAI_API_KEY']),
    google_maps: !!readEnvValue(['GOOGLE_MAPS_API_KEY', 'GOOGLE_API_KEY']),
  }
}

// Must be called before app.whenReady()
protocol.registerSchemesAsPrivileged([
  { scheme: 'localfile', privileges: { secure: true, bypassCSP: true, stream: true, supportFetchAPI: true } },
])

// Workspace persistence
const LAST_WORKSPACE_PATH = path.join(
  isDev ? path.resolve(process.cwd(), '.tmp') : app.getPath('userData'),
  'last-workspace.json'
)

function readLastWorkspace(): string | null {
  try { return JSON.parse(fs.readFileSync(LAST_WORKSPACE_PATH, 'utf-8')).path || null } catch { return null }
}
function writeLastWorkspace(p: string | null): void {
  try {
    fs.mkdirSync(path.dirname(LAST_WORKSPACE_PATH), { recursive: true })
    fs.writeFileSync(LAST_WORKSPACE_PATH, JSON.stringify({ path: p }))
  } catch { /* ignore */ }
}

// API Key persistence with safeStorage encryption
const API_KEY_CONFIG_PATH = path.join(
  isDev ? path.resolve(process.cwd(), '.tmp') : app.getPath('userData'),
  'api-key.json'
)

function readAndDecryptKey(): string {
  try {
    if (!fs.existsSync(API_KEY_CONFIG_PATH)) return ''
    const config = JSON.parse(fs.readFileSync(API_KEY_CONFIG_PATH, 'utf-8'))
    if (!config.key) return ''
    if (config.encrypted && safeStorage.isEncryptionAvailable()) {
      const encryptedBuffer = Buffer.from(config.key, 'hex')
      return safeStorage.decryptString(encryptedBuffer)
    } else if (!config.encrypted) {
      return Buffer.from(config.key, 'base64').toString('utf-8')
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt API key:', err)
    return ''
  }
}

function encryptAndSaveKey(key: string): boolean {
  try {
    if (!key || !key.trim()) {
      if (fs.existsSync(API_KEY_CONFIG_PATH)) {
        fs.unlinkSync(API_KEY_CONFIG_PATH)
      }
      return true
    }

    let storedValue: string
    const useEncryption = safeStorage.isEncryptionAvailable()
    if (useEncryption) {
      const encryptedBuffer = safeStorage.encryptString(key.trim())
      storedValue = encryptedBuffer.toString('hex')
    } else {
      storedValue = Buffer.from(key.trim()).toString('base64')
    }
    fs.mkdirSync(path.dirname(API_KEY_CONFIG_PATH), { recursive: true })
    fs.writeFileSync(API_KEY_CONFIG_PATH, JSON.stringify({ key: storedValue, encrypted: useEncryption }))
    return true
  } catch (err) {
    console.error('Failed to encrypt/save API key:', err)
    return false
  }
}

// Google Maps API Key persistence with safeStorage encryption
const GOOGLE_MAPS_KEY_CONFIG_PATH = path.join(
  isDev ? path.resolve(process.cwd(), '.tmp') : app.getPath('userData'),
  'google-maps-key.json'
)

function readAndDecryptGoogleMapsKey(): string {
  try {
    if (!fs.existsSync(GOOGLE_MAPS_KEY_CONFIG_PATH)) return ''
    const config = JSON.parse(fs.readFileSync(GOOGLE_MAPS_KEY_CONFIG_PATH, 'utf-8'))
    if (!config.key) return ''
    if (config.encrypted && safeStorage.isEncryptionAvailable()) {
      const encryptedBuffer = Buffer.from(config.key, 'hex')
      return safeStorage.decryptString(encryptedBuffer)
    } else if (!config.encrypted) {
      return Buffer.from(config.key, 'base64').toString('utf-8')
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt Google Maps API key:', err)
    return ''
  }
}

function encryptAndSaveGoogleMapsKey(key: string): boolean {
  try {
    if (!key || !key.trim()) {
      if (fs.existsSync(GOOGLE_MAPS_KEY_CONFIG_PATH)) {
        fs.unlinkSync(GOOGLE_MAPS_KEY_CONFIG_PATH)
      }
      return true
    }

    let storedValue: string
    const useEncryption = safeStorage.isEncryptionAvailable()
    if (useEncryption) {
      const encryptedBuffer = safeStorage.encryptString(key.trim())
      storedValue = encryptedBuffer.toString('hex')
    } else {
      storedValue = Buffer.from(key.trim()).toString('base64')
    }
    fs.mkdirSync(path.dirname(GOOGLE_MAPS_KEY_CONFIG_PATH), { recursive: true })
    fs.writeFileSync(GOOGLE_MAPS_KEY_CONFIG_PATH, JSON.stringify({ key: storedValue, encrypted: useEncryption }))
    return true
  } catch (err) {
    console.error('Failed to encrypt/save Google Maps API key:', err)
    return false
  }
}

// Google Earth Engine Credentials persistence with safeStorage encryption
const GEE_KEY_CONFIG_PATH = path.join(
  isDev ? path.resolve(process.cwd(), '.tmp') : app.getPath('userData'),
  'gee-credentials.json'
)

function readAndDecryptGEEKey(): string {
  try {
    if (!fs.existsSync(GEE_KEY_CONFIG_PATH)) return ''
    const config = JSON.parse(fs.readFileSync(GEE_KEY_CONFIG_PATH, 'utf-8'))
    if (!config.key) return ''
    if (config.encrypted && safeStorage.isEncryptionAvailable()) {
      const encryptedBuffer = Buffer.from(config.key, 'hex')
      return safeStorage.decryptString(encryptedBuffer)
    } else if (!config.encrypted) {
      return Buffer.from(config.key, 'base64').toString('utf-8')
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt GEE key:', err)
    return ''
  }
}

function encryptAndSaveGEEKey(key: string): boolean {
  try {
    if (!key || !key.trim()) {
      if (fs.existsSync(GEE_KEY_CONFIG_PATH)) {
        fs.unlinkSync(GEE_KEY_CONFIG_PATH)
      }
      return true
    }

    let storedValue: string
    const useEncryption = safeStorage.isEncryptionAvailable()
    if (useEncryption) {
      const encryptedBuffer = safeStorage.encryptString(key.trim())
      storedValue = encryptedBuffer.toString('hex')
    } else {
      storedValue = Buffer.from(key.trim()).toString('base64')
    }
    fs.mkdirSync(path.dirname(GEE_KEY_CONFIG_PATH), { recursive: true })
    fs.writeFileSync(GEE_KEY_CONFIG_PATH, JSON.stringify({ key: storedValue, encrypted: useEncryption }))
    return true
  } catch (err) {
    console.error('Failed to encrypt/save GEE key:', err)
    return false
  }
}

interface ModelConfig {
  id: string
  name: string
  provider: 'openai' | 'anthropic' | 'google'
  locked: boolean
}

const ALL_MODELS: ModelConfig[] = [
  { id: 'gpt-5.5', name: 'GPT-5.5', provider: 'openai', locked: false },
  { id: 'gpt-5.4', name: 'GPT-5.4', provider: 'openai', locked: false },
  { id: 'gpt-5.4-mini', name: 'GPT-5.4 Mini', provider: 'openai', locked: false },
  { id: 'gpt-5.4-nano', name: 'GPT-5.4 Nano', provider: 'openai', locked: false },
]

const DEFAULT_MODEL = 'gpt-5.4-mini'

// Store selected model in backend dir so Python can read it too
const MODEL_CONFIG_PATH = isDev
  ? path.resolve(process.cwd(), 'packages/backend/model_config.json')
  : path.join(process.resourcesPath, 'backend', 'model_config.json')

function readCurrentModel(): string {
  try {
    const config = JSON.parse(fs.readFileSync(MODEL_CONFIG_PATH, 'utf-8'))
    return config.model || DEFAULT_MODEL
  } catch {
    return DEFAULT_MODEL
  }
}

function writeCurrentModel(model: string): void {
  try {
    fs.writeFileSync(MODEL_CONFIG_PATH, JSON.stringify({ model }, null, 2))
  } catch {
    /* ignore write errors */
  }
}

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcess | null = null
let allowMainWindowClose = false
let quitFlushTimer: ReturnType<typeof setTimeout> | null = null

function startBackend(): void {
  if (isDev) return

  const backendBinary = process.platform === 'win32' ? 'backend.exe' : 'backend'
  const backendPath = path.join(process.resourcesPath, 'backend', backendBinary)

  const env = { ...process.env }
  env['OPENAI_API_KEY'] = env['OPENAI_API_KEY'] || readEnvValue(['OPENAI_API_KEY'])
  env['GOOGLE_MAPS_API_KEY'] = env['GOOGLE_MAPS_API_KEY'] || readEnvValue(['GOOGLE_MAPS_API_KEY', 'GOOGLE_API_KEY'])
  env['MAPILLARY_ACCESS_TOKEN'] = env['MAPILLARY_ACCESS_TOKEN'] || readEnvValue(['MAPILLARY_ACCESS_TOKEN', 'MAPILLARY_CLIENT_TOKEN'])
  const geeCreds = readAndDecryptGEEKey()
  if (geeCreds) {
    env['GOOGLE_EARTH_ENGINE_CREDS'] = geeCreds
  }

  backendProcess = spawn(backendPath, ['--port', String(BACKEND_PORT)], {
    env,
    stdio: ['ignore', 'pipe', 'pipe']
  })

  backendProcess.stdout?.on('data', (d) => console.log(`[backend] ${d}`))
  backendProcess.stderr?.on('data', (d) => console.error(`[backend] ${d}`))
  backendProcess.on('exit', (code) => console.log(`[backend] exited ${code}`))
}

function stopBackend(): void {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

async function waitForBackend(retries = 30, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`http://localhost:${BACKEND_PORT}/health`)
      if (res.ok) return true
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, delay))
  }
  return false
}

// ── Model switching IPC ────────────────────────────────────────────────────────

// Workspace persistence IPC
ipcMain.handle('get-last-workspace', () => readLastWorkspace())
ipcMain.handle('set-last-workspace', (_e, p: string | null) => writeLastWorkspace(p))
ipcMain.handle('get-api-key', () => readAndDecryptKey())
ipcMain.handle('set-api-key', (_e, key: string) => encryptAndSaveKey(key))
ipcMain.handle('get-key-status', () => getKeyStatus())
ipcMain.handle('get-google-maps-key', () => readAndDecryptGoogleMapsKey())
ipcMain.handle('set-google-maps-key', (_e, key: string) => encryptAndSaveGoogleMapsKey(key))
ipcMain.handle('get-gee-key', () => readAndDecryptGEEKey())
ipcMain.handle('set-gee-key', (_e, key: string) => encryptAndSaveGEEKey(key))

// Open file dialog (for document mode)
ipcMain.handle('open-file', async (_e, opts: { filters?: { name: string; extensions: string[] }[] }) => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openFile'],
    filters: opts?.filters || [{ name: 'All Files', extensions: ['*'] }],
  })
  return result.canceled ? null : result.filePaths[0] ?? null
})

// Read file as base64 (for sending images to AI vision)
ipcMain.handle('read-file-base64', async (_e, filePath: string) => {
  try { return fs.readFileSync(filePath).toString('base64') } catch { return null }
})

ipcMain.handle('get-models', () => ALL_MODELS)

ipcMain.handle('get-current-model', () => readCurrentModel())

ipcMain.handle('switch-model', async (_event, newModel: string) => {
  writeCurrentModel(newModel)
  return { ok: true, requiresManualRestart: false }
})

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  if (isDev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  mainWindow.on('close', (e) => {
    if (allowMainWindowClose || !mainWindow) return
    if (mainWindow.webContents.isLoading()) {
      allowMainWindowClose = true
      return
    }
    e.preventDefault()
    if (quitFlushTimer) clearTimeout(quitFlushTimer)
    quitFlushTimer = setTimeout(() => {
      quitFlushTimer = null
      allowMainWindowClose = true
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close()
      allowMainWindowClose = false
    }, 4000)
    mainWindow.webContents.send('app-before-quit')
  })

  mainWindow.on('enter-full-screen', () => {
    mainWindow?.webContents.send('fullscreen-change', true)
  })
  mainWindow.on('leave-full-screen', () => {
    mainWindow?.webContents.send('fullscreen-change', false)
  })
}

ipcMain.on('app-quit-flush-done', () => {
  if (quitFlushTimer) {
    clearTimeout(quitFlushTimer)
    quitFlushTimer = null
  }
  allowMainWindowClose = true
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.close()
  }
  allowMainWindowClose = false
})

// --- IPC Handlers ---

ipcMain.handle('select-workspace', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openDirectory'],
    title: 'Select Workspace Folder'
  })
  if (result.canceled || result.filePaths.length === 0) return null
  const selected = result.filePaths[0]
  writeLastWorkspace(selected)
  return selected
})

ipcMain.handle('read-directory', async (_event, dirPath: string) => {
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true })
    return entries
      .filter((e) => !e.name.startsWith('.'))
      .sort((a, b) => {
        if (a.isDirectory() && !b.isDirectory()) return -1
        if (!a.isDirectory() && b.isDirectory()) return 1
        return a.name.localeCompare(b.name)
      })
      .map((e) => ({
        name: e.name,
        path: path.join(dirPath, e.name),
        isDirectory: e.isDirectory()
      }))
  } catch {
    return []
  }
})

ipcMain.handle('read-file', async (_event, filePath: string) => {
  try {
    return fs.readFileSync(filePath, 'utf-8')
  } catch {
    return null
  }
})

ipcMain.handle('write-file', async (_event, filePath: string, content: string) => {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    fs.writeFileSync(filePath, content, 'utf-8')
    return true
  } catch {
    return false
  }
})

ipcMain.handle('import-spatial-files', async (_e, workspacePath: string) => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openFile', 'multiSelections'],
    filters: [
      { name: 'Spatial Files', extensions: ['geojson', 'json', 'kml', 'kmz', 'shp', 'gpkg', 'gpx', 'csv'] },
      { name: 'All Files', extensions: ['*'] }
    ]
  })
  if (result.canceled || result.filePaths.length === 0) return []

  const importedPaths: string[] = []
  for (const fp of result.filePaths) {
    const filename = path.basename(fp)
    const targetPath = path.join(workspacePath, filename)
    
    // Check if the file is already in the workspace
    const isInside = fp.startsWith(workspacePath)
    if (isInside) {
      importedPaths.push(fp)
    } else {
      // Copy the file to the workspace
      try {
        fs.copyFileSync(fp, targetPath)
        importedPaths.push(targetPath)

        // Automatically discover and copy Shapefile sidecars if importing a .shp
        if (filename.toLowerCase().endsWith('.shp')) {
          const baseName = path.basename(filename, path.extname(filename))
          const srcDir = path.dirname(fp)
          const sidecarExts = ['.shx', '.dbf', '.prj', '.cpg', '.qpj', '.sbn', '.sbx']
          for (const ext of sidecarExts) {
            for (const actualExt of [ext, ext.toUpperCase()]) {
              const sidecarSrc = path.join(srcDir, baseName + actualExt)
              if (fs.existsSync(sidecarSrc)) {
                const sidecarTarget = path.join(workspacePath, baseName + actualExt)
                fs.copyFileSync(sidecarSrc, sidecarTarget)
                break
              }
            }
          }
        }
      } catch (err) {
        console.error('Failed to copy file:', fp, err)
      }
    }
  }
  return importedPaths
})

ipcMain.handle('save-pdf', async (_e, htmlContent: string, defaultName: string) => {
  let tempFilePath: string | null = null
  try {
    const win = new BrowserWindow({
      show: false,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
      },
    })

    // Write HTML content to a temp file in the OS temp directory
    const tempDir = os.tmpdir()
    const tempFileName = `print_${Date.now()}_${Math.random().toString(36).substring(2, 9)}.html`
    tempFilePath = path.join(tempDir, tempFileName)
    fs.writeFileSync(tempFilePath, htmlContent, 'utf-8')

    // Load local file to support internal relative hash anchor links
    await win.loadFile(tempFilePath)

    // Wait a brief moment for dynamic scripts (like KaTeX math rendering) to execute
    await new Promise((resolve) => setTimeout(resolve, 500))

    const pdfBuffer = await win.webContents.printToPDF({
      printBackground: true,
      margins: { marginType: 'default' },
    })
    win.close()

    // Clean up temporary file
    try {
      if (tempFilePath && fs.existsSync(tempFilePath)) {
        fs.unlinkSync(tempFilePath)
      }
    } catch (cleanupErr) {
      console.error('Failed to delete temporary print file:', cleanupErr)
    }

    const result = await dialog.showSaveDialog(mainWindow!, {
      title: 'Save PDF Report',
      defaultPath: defaultName || 'report.pdf',
      filters: [{ name: 'PDF Files', extensions: ['pdf'] }],
    })
    if (result.canceled || !result.filePath) return false

    fs.writeFileSync(result.filePath, pdfBuffer)
    return true
  } catch (err) {
    console.error('Failed to export PDF:', err)
    // Clean up temp file on error
    try {
      if (tempFilePath && fs.existsSync(tempFilePath)) {
        fs.unlinkSync(tempFilePath)
      }
    } catch {}
    return false
  }
})

// --- App lifecycle ---

app.whenReady().then(async () => {
  // Serve local files via localfile:// so the renderer can load them
  // regardless of whether it's running on file:// (prod) or http:// (dev).
  protocol.handle('localfile', (request) => {
    return net.fetch(request.url.replace(/^localfile:/, 'file:'))
  })

  startBackend()

  if (!isDev) {
    const backendReady = await waitForBackend()
    if (!backendReady) console.error('Backend failed to start')
  }

  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  stopBackend()
})
