import { app, BrowserWindow, ipcMain, dialog, shell, protocol, net, safeStorage, Menu } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'
import os from 'os'

app.setName('Disha')

const BACKEND_PORT = 8765
const BACKEND_HOST = '127.0.0.1'
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

function getConfigCandidates(filename: string): string[] {
  const paths: string[] = []
  if (isDev) {
    paths.push(
      path.resolve(__dirname, '../../.tmp', filename),
      path.resolve(__dirname, '../../../../.tmp', filename),
      path.resolve(process.cwd(), '.tmp', filename),
      path.resolve(process.cwd(), 'apps/desktop/.tmp', filename),
    )
  }
  try {
    paths.push(path.join(app.getPath('userData'), filename))
  } catch {}
  try {
    const appData = app.getPath('appData')
    paths.push(path.join(appData, 'Disha', filename))
    paths.push(path.join(appData, '@disha', 'desktop', filename))
    paths.push(path.join(appData, 'disha', filename))
  } catch {}
  return Array.from(new Set(paths))
}

function getPrimaryConfigPath(filename: string): string {
  if (isDev) {
    return path.resolve(__dirname, '../../.tmp', filename)
  }
  return path.join(app.getPath('userData'), filename)
}

function getKeyStatus(): { openai: boolean; google_maps: boolean; gee: boolean; mapillary: boolean } {
  const openaiKey = normalizeApiKey(readEnvValue(['OPENAI_API_KEY'])) || readAndDecryptKey()
  const googleKey = normalizeApiKey(readEnvValue(['GOOGLE_MAPS_API_KEY', 'GOOGLE_API_KEY'])) || readAndDecryptGoogleMapsKey()
  const geeKey = normalizeGEEKey(readEnvValue(['GOOGLE_EARTH_ENGINE_CREDS', 'GEE_CREDENTIALS'])) || readAndDecryptGEEKey()
  const mapillaryKey = normalizeApiKey(readEnvValue(['MAPILLARY_ACCESS_TOKEN', 'MAPILLARY_CLIENT_TOKEN'])) || readAndDecryptMapillaryKey()
  return {
    openai: Boolean(openaiKey && openaiKey.length >= 8),
    google_maps: Boolean(googleKey && googleKey.length >= 8),
    gee: Boolean(geeKey && geeKey.includes('service_account')),
    mapillary: Boolean(mapillaryKey && mapillaryKey.length >= 8),
  }
}

// Must be called before app.whenReady()
protocol.registerSchemesAsPrivileged([
  { scheme: 'localfile', privileges: { secure: true, bypassCSP: true, stream: true, supportFetchAPI: true } },
])

// Workspace persistence
function readLastWorkspace(): string | null {
  try {
    for (const p of getConfigCandidates('last-workspace.json')) {
      if (fs.existsSync(p)) {
        const val = JSON.parse(fs.readFileSync(p, 'utf-8')).path
        if (val) return val
      }
    }
    return null
  } catch { return null }
}

function writeLastWorkspace(p: string | null): void {
  try {
    const primary = getPrimaryConfigPath('last-workspace.json')
    fs.mkdirSync(path.dirname(primary), { recursive: true })
    fs.writeFileSync(primary, JSON.stringify({ path: p }))
    if (isDev) {
      const rootTmp = path.resolve(__dirname, '../../../../.tmp', 'last-workspace.json')
      if (rootTmp !== primary) {
        try {
          fs.mkdirSync(path.dirname(rootTmp), { recursive: true })
          fs.writeFileSync(rootTmp, JSON.stringify({ path: p }))
        } catch { /* ignore */ }
      }
    }
  } catch { /* ignore */ }
}

function getSystemDefaultDishaFolder(): string {
  try {
    const documentsDir = app.getPath('documents')
    return path.join(documentsDir, 'Disha')
  } catch {
    return path.join(os.homedir(), 'Documents', 'Disha')
  }
}

function readDefaultWorkspace(): string | null {
  try {
    for (const p of getConfigCandidates('default-workspace.json')) {
      if (fs.existsSync(p)) {
        const val = JSON.parse(fs.readFileSync(p, 'utf-8')).path
        if (val) return val
      }
    }
    return null
  } catch { return null }
}

function writeDefaultWorkspace(p: string): void {
  try {
    const primary = getPrimaryConfigPath('default-workspace.json')
    fs.mkdirSync(path.dirname(primary), { recursive: true })
    fs.writeFileSync(primary, JSON.stringify({ path: p }))
    fs.mkdirSync(p, { recursive: true })
    if (isDev) {
      const rootTmp = path.resolve(__dirname, '../../../../.tmp', 'default-workspace.json')
      if (rootTmp !== primary) {
        try {
          fs.mkdirSync(path.dirname(rootTmp), { recursive: true })
          fs.writeFileSync(rootTmp, JSON.stringify({ path: p }))
        } catch { /* ignore */ }
      }
    }
  } catch { /* ignore */ }
}

// Key format and ASCII printable validation helpers
function normalizeApiKey(k: unknown): string {
  if (typeof k !== 'string') return ''
  let s = k.trim()
  // Strip shell export statements or env prefixes
  s = s.replace(/^(?:export\s+)?(?:OPENAI_API_KEY|GOOGLE_MAPS_API_KEY|GOOGLE_API_KEY|MAPILLARY_ACCESS_TOKEN|MAPILLARY_CLIENT_TOKEN)\s*=\s*/i, '')
  // Strip 'Bearer ' if user pasted curl auth header
  s = s.replace(/^Bearer\s+/i, '')
  // Strip surrounding quotes
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'")) || (s.startsWith('`') && s.endsWith('`'))) {
    s = s.slice(1, -1).trim()
  }
  // Filter to valid ASCII printable characters (32 to 126)
  s = s.replace(/[^\x20-\x7E]/g, '').trim()
  // Ignore placeholder dummy values
  if (['your_api_key_here', 'your_key_here', 'your_key', 'sk-...', 'aizasy...', 'enter new api key', 'enter your api key'].includes(s.toLowerCase())) {
    return ''
  }
  return s
}

function normalizeGEEKey(k: unknown): string {
  if (typeof k !== 'string') return ''
  let s = k.trim()
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    if (s.startsWith('"{') || s.startsWith("'{")) {
      s = s.slice(1, -1).trim()
    }
  }
  s = s.replace(/[^\x20-\x7E\r\n\t]/g, '').trim()
  return s
}

function isValidOpenAIKey(k: unknown): k is string {
  const norm = normalizeApiKey(k)
  return Boolean(norm.length >= 8)
}

function isValidGoogleMapsKey(k: unknown): k is string {
  const norm = normalizeApiKey(k)
  return Boolean(norm.length >= 8)
}

function isValidGEEKey(k: unknown): k is string {
  const norm = normalizeGEEKey(k)
  return Boolean(
    norm.includes('service_account') &&
    norm.includes('private_key')
  )
}

function isValidMapillaryKey(k: unknown): k is string {
  const norm = normalizeApiKey(k)
  return Boolean(norm.length >= 8)
}

// API Key persistence with safeStorage encryption
function readAndDecryptKey(): string {
  try {
    for (const configPath of getConfigCandidates('api-key.json')) {
      if (!fs.existsSync(configPath)) continue
      try {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        if (!config || typeof config !== 'object') continue

        // 1. Try safeStorage if marked encrypted
        if (config.encrypted && config.key && safeStorage.isEncryptionAvailable()) {
          try {
            const encryptedBuffer = Buffer.from(config.key, 'hex')
            const decrypted = safeStorage.decryptString(encryptedBuffer)
            if (isValidOpenAIKey(decrypted)) return decrypted.trim()
          } catch (decryptErr) {
            console.warn('safeStorage.decryptString failed for OpenAI key:', decryptErr)
          }
        }

        // 2. Try explicit fallback if present
        if (config.fallback && typeof config.fallback === 'string') {
          try {
            const decrypted = Buffer.from(config.fallback, 'base64').toString('utf-8')
            if (isValidOpenAIKey(decrypted)) {
              // Self-heal safeStorage with current environment
              try {
                if (safeStorage.isEncryptionAvailable()) {
                  const encryptedBuffer = safeStorage.encryptString(decrypted.trim())
                  fs.writeFileSync(configPath, JSON.stringify({
                    key: encryptedBuffer.toString('hex'),
                    encrypted: true,
                    fallback: config.fallback,
                  }))
                }
              } catch {}
              return decrypted.trim()
            }
          } catch {}
        }

        // 3. Try legacy base64 or plaintext ONLY if not marked encrypted
        if (!config.encrypted && config.key && typeof config.key === 'string') {
          try {
            const decrypted = Buffer.from(config.key, 'base64').toString('utf-8')
            if (isValidOpenAIKey(decrypted)) return decrypted.trim()
          } catch {}
          if (isValidOpenAIKey(config.key)) return config.key.trim()
        }
      } catch {
        continue
      }
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt API key:', err)
    return ''
  }
}

function encryptAndSaveKey(key: string): boolean {
  try {
    const cleanKey = (key || '').trim().replace(/[^\x20-\x7E]/g, '')
    const primary = getPrimaryConfigPath('api-key.json')
    if (!cleanKey) {
      for (const p of getConfigCandidates('api-key.json')) {
        if (fs.existsSync(p)) {
          try { fs.unlinkSync(p) } catch { /* ignore */ }
        }
      }
      delete process.env['OPENAI_API_KEY']
      return true
    }

    let storedValue: string
    let useEncryption = false
    try {
      if (safeStorage.isEncryptionAvailable()) {
        const encryptedBuffer = safeStorage.encryptString(cleanKey)
        storedValue = encryptedBuffer.toString('hex')
        useEncryption = true
      } else {
        storedValue = Buffer.from(cleanKey).toString('base64')
      }
    } catch {
      storedValue = Buffer.from(cleanKey).toString('base64')
      useEncryption = false
    }

    const fallback = Buffer.from(cleanKey).toString('base64')
    const data = JSON.stringify({
      key: storedValue,
      encrypted: useEncryption,
      fallback: fallback,
    })
    fs.mkdirSync(path.dirname(primary), { recursive: true })
    fs.writeFileSync(primary, data)
    if (isDev) {
      const rootTmp = path.resolve(__dirname, '../../../../.tmp', 'api-key.json')
      if (rootTmp !== primary) {
        try {
          fs.mkdirSync(path.dirname(rootTmp), { recursive: true })
          fs.writeFileSync(rootTmp, data)
        } catch { /* ignore */ }
      }
    }
    process.env['OPENAI_API_KEY'] = cleanKey
    return true
  } catch (err) {
    console.error('Failed to encrypt/save API key:', err)
    return false
  }
}

// Google Maps API Key persistence with safeStorage encryption
function readAndDecryptGoogleMapsKey(): string {
  try {
    for (const configPath of getConfigCandidates('google-maps-key.json')) {
      if (!fs.existsSync(configPath)) continue
      try {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        if (!config || typeof config !== 'object') continue

        // 1. Try safeStorage if marked encrypted
        if (config.encrypted && config.key && safeStorage.isEncryptionAvailable()) {
          try {
            const encryptedBuffer = Buffer.from(config.key, 'hex')
            const decrypted = safeStorage.decryptString(encryptedBuffer)
            if (isValidGoogleMapsKey(decrypted)) return decrypted.trim()
          } catch (decryptErr) {
            console.warn('safeStorage.decryptString failed for Google Maps:', decryptErr)
          }
        }

        // 2. Try explicit fallback if present
        if (config.fallback && typeof config.fallback === 'string') {
          try {
            const decrypted = Buffer.from(config.fallback, 'base64').toString('utf-8')
            if (isValidGoogleMapsKey(decrypted)) {
              // Self-heal safeStorage with current environment
              try {
                if (safeStorage.isEncryptionAvailable()) {
                  const encryptedBuffer = safeStorage.encryptString(decrypted.trim())
                  fs.writeFileSync(configPath, JSON.stringify({
                    key: encryptedBuffer.toString('hex'),
                    encrypted: true,
                    fallback: config.fallback,
                  }))
                }
              } catch {}
              return decrypted.trim()
            }
          } catch {}
        }

        // 3. Try legacy base64 or plaintext ONLY if not marked encrypted
        if (!config.encrypted && config.key && typeof config.key === 'string') {
          try {
            const decrypted = Buffer.from(config.key, 'base64').toString('utf-8')
            if (isValidGoogleMapsKey(decrypted)) return decrypted.trim()
          } catch {}
          if (isValidGoogleMapsKey(config.key)) return config.key.trim()
        }
      } catch {
        continue
      }
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt Google Maps API key:', err)
    return ''
  }
}

function encryptAndSaveGoogleMapsKey(key: string): boolean {
  try {
    const cleanKey = (key || '').trim().replace(/[^\x20-\x7E]/g, '')
    const primary = getPrimaryConfigPath('google-maps-key.json')
    if (!cleanKey) {
      for (const p of getConfigCandidates('google-maps-key.json')) {
        if (fs.existsSync(p)) {
          try { fs.unlinkSync(p) } catch { /* ignore */ }
        }
      }
      delete process.env['GOOGLE_MAPS_API_KEY']
      return true
    }

    let storedValue: string
    let useEncryption = false
    try {
      if (safeStorage.isEncryptionAvailable()) {
        const encryptedBuffer = safeStorage.encryptString(cleanKey)
        storedValue = encryptedBuffer.toString('hex')
        useEncryption = true
      } else {
        storedValue = Buffer.from(cleanKey).toString('base64')
      }
    } catch {
      storedValue = Buffer.from(cleanKey).toString('base64')
      useEncryption = false
    }

    const fallback = Buffer.from(cleanKey).toString('base64')
    const data = JSON.stringify({
      key: storedValue,
      encrypted: useEncryption,
      fallback: fallback,
    })
    fs.mkdirSync(path.dirname(primary), { recursive: true })
    fs.writeFileSync(primary, data)
    if (isDev) {
      const rootTmp = path.resolve(__dirname, '../../../../.tmp', 'google-maps-key.json')
      if (rootTmp !== primary) {
        try {
          fs.mkdirSync(path.dirname(rootTmp), { recursive: true })
          fs.writeFileSync(rootTmp, data)
        } catch { /* ignore */ }
      }
    }
    process.env['GOOGLE_MAPS_API_KEY'] = cleanKey
    return true
  } catch (err) {
    console.error('Failed to encrypt/save Google Maps API key:', err)
    return false
  }
}

// Google Earth Engine Credentials persistence with safeStorage encryption
function readAndDecryptGEEKey(): string {
  try {
    for (const configPath of getConfigCandidates('gee-credentials.json')) {
      if (!fs.existsSync(configPath)) continue
      try {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        if (!config || typeof config !== 'object') continue

        // 1. Try safeStorage if marked encrypted
        if (config.encrypted && config.key && safeStorage.isEncryptionAvailable()) {
          try {
            const encryptedBuffer = Buffer.from(config.key, 'hex')
            const decrypted = safeStorage.decryptString(encryptedBuffer)
            if (isValidGEEKey(decrypted)) return decrypted.trim()
          } catch (decryptErr) {
            console.warn('safeStorage.decryptString failed for GEE:', decryptErr)
          }
        }

        // 2. Try explicit fallback if present
        if (config.fallback && typeof config.fallback === 'string') {
          try {
            const decrypted = Buffer.from(config.fallback, 'base64').toString('utf-8')
            if (isValidGEEKey(decrypted)) {
              // Self-heal safeStorage with current environment
              try {
                if (safeStorage.isEncryptionAvailable()) {
                  const encryptedBuffer = safeStorage.encryptString(decrypted.trim())
                  fs.writeFileSync(configPath, JSON.stringify({
                    key: encryptedBuffer.toString('hex'),
                    encrypted: true,
                    fallback: config.fallback,
                  }))
                }
              } catch {}
              return decrypted.trim()
            }
          } catch {}
        }

        // 3. Try legacy base64 or plaintext ONLY if not marked encrypted
        if (!config.encrypted && config.key && typeof config.key === 'string') {
          try {
            const decrypted = Buffer.from(config.key, 'base64').toString('utf-8')
            if (isValidGEEKey(decrypted)) return decrypted.trim()
          } catch {}
          if (isValidGEEKey(config.key)) return config.key.trim()
        }
      } catch {
        continue
      }
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt GEE key:', err)
    return ''
  }
}

function encryptAndSaveGEEKey(key: string): boolean {
  try {
    const cleanKey = (key || '').trim().replace(/[^\x20-\x7E\r\n\t]/g, '')
    const primary = getPrimaryConfigPath('gee-credentials.json')
    if (!cleanKey) {
      for (const p of getConfigCandidates('gee-credentials.json')) {
        if (fs.existsSync(p)) {
          try { fs.unlinkSync(p) } catch { /* ignore */ }
        }
      }
      delete process.env['GOOGLE_EARTH_ENGINE_CREDS']
      return true
    }

    let storedValue: string
    let useEncryption = false
    try {
      if (safeStorage.isEncryptionAvailable()) {
        const encryptedBuffer = safeStorage.encryptString(cleanKey)
        storedValue = encryptedBuffer.toString('hex')
        useEncryption = true
      } else {
        storedValue = Buffer.from(cleanKey).toString('base64')
      }
    } catch {
      storedValue = Buffer.from(cleanKey).toString('base64')
      useEncryption = false
    }

    const fallback = Buffer.from(cleanKey).toString('base64')
    const data = JSON.stringify({
      key: storedValue,
      encrypted: useEncryption,
      fallback: fallback,
    })
    fs.mkdirSync(path.dirname(primary), { recursive: true })
    fs.writeFileSync(primary, data)
    if (isDev) {
      const rootTmp = path.resolve(__dirname, '../../../../.tmp', 'gee-credentials.json')
      if (rootTmp !== primary) {
        try {
          fs.mkdirSync(path.dirname(rootTmp), { recursive: true })
          fs.writeFileSync(rootTmp, data)
        } catch { /* ignore */ }
      }
    }
    process.env['GOOGLE_EARTH_ENGINE_CREDS'] = cleanKey
    return true
  } catch (err) {
    console.error('Failed to encrypt/save GEE key:', err)
    return false
  }
}

// Mapillary Access Token persistence with safeStorage encryption
function readAndDecryptMapillaryKey(): string {
  try {
    for (const configPath of getConfigCandidates('mapillary-token.json')) {
      if (!fs.existsSync(configPath)) continue
      try {
        const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'))
        if (!config || typeof config !== 'object') continue

        // 1. Try safeStorage if marked encrypted
        if (config.encrypted && config.key && safeStorage.isEncryptionAvailable()) {
          try {
            const encryptedBuffer = Buffer.from(config.key, 'hex')
            const decrypted = safeStorage.decryptString(encryptedBuffer)
            if (isValidMapillaryKey(decrypted)) return normalizeApiKey(decrypted)
          } catch (decryptErr) {
            console.warn('safeStorage.decryptString failed for Mapillary:', decryptErr)
          }
        }

        // 2. Try explicit fallback if present
        if (config.fallback && typeof config.fallback === 'string') {
          try {
            const decrypted = Buffer.from(config.fallback, 'base64').toString('utf-8')
            if (isValidMapillaryKey(decrypted)) {
              return normalizeApiKey(decrypted)
            }
          } catch {}
        }

        // 3. Try legacy base64 or plaintext ONLY if not marked encrypted
        if (!config.encrypted && config.key && typeof config.key === 'string') {
          try {
            const decrypted = Buffer.from(config.key, 'base64').toString('utf-8')
            if (isValidMapillaryKey(decrypted)) return normalizeApiKey(decrypted)
          } catch {}
          if (isValidMapillaryKey(config.key)) return normalizeApiKey(config.key)
        }
      } catch {
        continue
      }
    }
    return ''
  } catch (err) {
    console.error('Failed to read/decrypt Mapillary token:', err)
    return ''
  }
}

function encryptAndSaveMapillaryKey(key: string): boolean {
  try {
    const cleanKey = normalizeApiKey(key)
    const primary = getPrimaryConfigPath('mapillary-token.json')
    if (!cleanKey) {
      for (const p of getConfigCandidates('mapillary-token.json')) {
        if (fs.existsSync(p)) {
          try { fs.unlinkSync(p) } catch { /* ignore */ }
        }
      }
      delete process.env['MAPILLARY_ACCESS_TOKEN']
      return true
    }

    let storedValue: string
    let useEncryption = false
    try {
      if (safeStorage.isEncryptionAvailable()) {
        const encryptedBuffer = safeStorage.encryptString(cleanKey)
        storedValue = encryptedBuffer.toString('hex')
        useEncryption = true
      } else {
        storedValue = Buffer.from(cleanKey).toString('base64')
      }
    } catch {
      storedValue = Buffer.from(cleanKey).toString('base64')
      useEncryption = false
    }

    const fallback = Buffer.from(cleanKey).toString('base64')
    const data = JSON.stringify({
      key: storedValue,
      encrypted: useEncryption,
      fallback: fallback,
    })
    fs.mkdirSync(path.dirname(primary), { recursive: true })
    fs.writeFileSync(primary, data)
    if (isDev) {
      const rootTmp = path.resolve(__dirname, '../../../../.tmp', 'mapillary-token.json')
      if (rootTmp !== primary) {
        try {
          fs.mkdirSync(path.dirname(rootTmp), { recursive: true })
          fs.writeFileSync(rootTmp, data)
        } catch { /* ignore */ }
      }
    }
    process.env['MAPILLARY_ACCESS_TOKEN'] = cleanKey
    return true
  } catch (err) {
    console.error('Failed to encrypt/save Mapillary token:', err)
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
let isQuitting = false
let hasFlushedQuitState = false
let quitFlushTimer: ReturnType<typeof setTimeout> | null = null

async function startBackend(): Promise<void> {
  // Reuse a backend started manually or by another app instance.
  try {
    const response = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/health`)
    if (response.ok) {
      console.log(`[backend] already running on port ${BACKEND_PORT}`)
      return
    }
  } catch {
    /* start the backend below */
  }

  let command: string
  let args: string[]
  let cwd: string | undefined

  if (isDev) {
    const backendCandidates = [
      path.resolve(process.cwd(), 'packages/backend'),
      path.resolve(app.getAppPath(), '../../packages/backend'),
      path.resolve(__dirname, '../../../../packages/backend'),
      path.resolve(__dirname, '../../../packages/backend'),
    ]
    const backendDir = backendCandidates.find((candidate) => fs.existsSync(path.join(candidate, 'main.py')))

    if (!backendDir) {
      console.error('[backend] could not find packages/backend/main.py')
      return
    }

    const venvPython = process.platform === 'win32'
      ? path.join(backendDir, '.buildenv', 'Scripts', 'python.exe')
      : path.join(backendDir, '.buildenv', 'bin', 'python')
    command = fs.existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3')
    args = ['-m', 'uvicorn', 'main:app', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT)]
    cwd = backendDir
  } else {
    const backendBinary = process.platform === 'win32' ? 'backend.exe' : 'backend'
    command = path.join(process.resourcesPath, 'backend', backendBinary)
    args = ['--host', BACKEND_HOST, '--port', String(BACKEND_PORT)]
    if (!fs.existsSync(command)) {
      console.error(`[backend] bundled executable not found at ${command}. Build the packaged app with 'pnpm run build:backend' first.`)
      return
    }
    cwd = path.join(process.resourcesPath, 'backend')
    // Preserve launchability when an archive/extraction step drops the Unix
    // executable bit from the bundled PyInstaller binary.
    if (process.platform !== 'win32') {
      try {
        fs.chmodSync(command, 0o755)
      } catch (err) {
        console.error('[backend] could not mark bundled executable as runnable', err)
      }
    }
  }

  const env = { ...process.env }
  const storedOpenAI = readAndDecryptKey()
  const storedGoogle = readAndDecryptGoogleMapsKey()
  const storedMapillary = readAndDecryptMapillaryKey()
  env['OPENAI_API_KEY'] = env['OPENAI_API_KEY'] || readEnvValue(['OPENAI_API_KEY']) || storedOpenAI
  env['GOOGLE_MAPS_API_KEY'] = env['GOOGLE_MAPS_API_KEY'] || readEnvValue(['GOOGLE_MAPS_API_KEY', 'GOOGLE_API_KEY']) || storedGoogle
  env['MAPILLARY_ACCESS_TOKEN'] = env['MAPILLARY_ACCESS_TOKEN'] || readEnvValue(['MAPILLARY_ACCESS_TOKEN', 'MAPILLARY_CLIENT_TOKEN']) || storedMapillary
  const geeCreds = readAndDecryptGEEKey()
  if (geeCreds) {
    env['GOOGLE_EARTH_ENGINE_CREDS'] = geeCreds
  }

  backendProcess = spawn(command, args, {
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe']
  })

  backendProcess.stdout?.on('data', (d) => console.log(`[backend] ${d}`))
  backendProcess.stderr?.on('data', (d) => console.error(`[backend] ${d}`))
  backendProcess.on('error', (err) => console.error(`[backend] failed to start with ${command}:`, err))
  backendProcess.on('exit', (code) => console.log(`[backend] exited ${code}`))
}

function stopBackend(): void {
  if (backendProcess) {
    backendProcess.kill()
    backendProcess = null
  }
}

async function waitForBackend(retries = 60, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`http://${BACKEND_HOST}:${BACKEND_PORT}/health`)
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
ipcMain.handle('get-default-disha-folder', () => getSystemDefaultDishaFolder())
ipcMain.handle('get-default-workspace', () => readDefaultWorkspace())
ipcMain.handle('set-default-workspace', (_e, p: string) => {
  writeDefaultWorkspace(p)
  writeLastWorkspace(p)
  return p
})
ipcMain.handle('select-folder', async (_e, title?: string) => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    properties: ['openDirectory', 'createDirectory'],
    title: title || 'Select Folder',
  })
  if (result.canceled || result.filePaths.length === 0) return null
  return result.filePaths[0]
})
ipcMain.handle('show-item-in-folder', (_e, filePath: string) => {
  if (filePath && fs.existsSync(filePath)) {
    shell.showItemInFolder(filePath)
    return true
  }
  return false
})
ipcMain.handle('show-save-dialog', async (_e, opts: { defaultPath?: string; filters?: { name: string; extensions: string[] }[] }) => {
  const result = await dialog.showSaveDialog(mainWindow!, {
    defaultPath: opts?.defaultPath,
    filters: opts?.filters,
  })
  return result.canceled ? null : result.filePath ?? null
})
ipcMain.handle('get-api-key', () => readAndDecryptKey())
ipcMain.handle('set-api-key', (_e, key: string) => {
  const ok = encryptAndSaveKey(key)
  if (ok && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('api-keys-updated')
  }
  return ok
})
ipcMain.handle('get-key-status', () => getKeyStatus())
ipcMain.handle('get-google-maps-key', () => readAndDecryptGoogleMapsKey())
ipcMain.handle('set-google-maps-key', (_e, key: string) => {
  const ok = encryptAndSaveGoogleMapsKey(key)
  if (ok && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('api-keys-updated')
  }
  return ok
})
ipcMain.handle('get-gee-key', () => readAndDecryptGEEKey())
ipcMain.handle('set-gee-key', (_e, key: string) => {
  const ok = encryptAndSaveGEEKey(key)
  if (ok && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('api-keys-updated')
  }
  return ok
})
ipcMain.handle('get-mapillary-key', () => readAndDecryptMapillaryKey())
ipcMain.handle('set-mapillary-key', (_e, key: string) => {
  const ok = encryptAndSaveMapillaryKey(key)
  if (ok && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('api-keys-updated')
  }
  return ok
})

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

// Window control handlers for MenuBar
ipcMain.handle('window-minimize', () => mainWindow?.minimize())
ipcMain.handle('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize()
  else mainWindow?.maximize()
})
ipcMain.handle('window-close', () => mainWindow?.close())
ipcMain.handle('app-quit', () => {
  isQuitting = true
  app.quit()
})
ipcMain.handle('window-reload', () => mainWindow?.webContents.reload())
ipcMain.handle('window-toggle-fullscreen', () => {
  if (mainWindow) mainWindow.setFullScreen(!mainWindow.isFullScreen())
})

function setupApplicationMenu(): void {
  const isMac = process.platform === 'darwin'

  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: 'about' as const },
              { type: 'separator' as const },
              {
                label: 'Preferences...',
                accelerator: 'CmdOrCtrl+,',
                click: () => {
                  if (mainWindow && !mainWindow.isDestroyed()) {
                    mainWindow.webContents.send('open-preferences')
                  }
                }
              },
              { type: 'separator' as const },
              { role: 'services' as const },
              { type: 'separator' as const },
              { role: 'hide' as const },
              { role: 'hideOthers' as const },
              { role: 'unhide' as const },
              { type: 'separator' as const },
              {
                label: 'Quit Disha',
                accelerator: 'CommandOrControl+Q',
                click: () => {
                  isQuitting = true
                  app.quit()
                }
              }
            ]
          }
        ]
      : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'Open Workspace...',
          accelerator: 'CmdOrCtrl+O',
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.send('menu-open-workspace')
            }
          }
        },
        { type: 'separator' as const },
        isMac
          ? { role: 'close' as const }
          : {
              label: 'Quit',
              accelerator: 'CmdOrCtrl+Q',
              click: () => {
                isQuitting = true
                app.quit()
              }
            }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' as const },
        { role: 'redo' as const },
        { type: 'separator' as const },
        { role: 'cut' as const },
        { role: 'copy' as const },
        { role: 'paste' as const },
        { role: 'selectAll' as const }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' as const },
        { role: 'forceReload' as const },
        { role: 'toggleDevTools' as const },
        { type: 'separator' as const },
        { role: 'resetZoom' as const },
        { role: 'zoomIn' as const },
        { role: 'zoomOut' as const },
        { type: 'separator' as const },
        { role: 'togglefullscreen' as const }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' as const },
        { role: 'zoom' as const },
        ...(isMac
          ? [
              { type: 'separator' as const },
              { role: 'front' as const },
              { type: 'separator' as const },
              { role: 'window' as const }
            ]
          : [{ role: 'close' as const }])
      ]
    }
  ]

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#1e1e2e',
    icon: path.join(__dirname, '../renderer/assets/icon.png'),
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

    // When the application itself is quitting, before-quit coordinates the flush
    if (isQuitting) {
      if (!hasFlushedQuitState) {
        e.preventDefault()
      }
      return
    }

    // Normal window close (e.g. red close button)
    e.preventDefault()
    if (quitFlushTimer) clearTimeout(quitFlushTimer)
    quitFlushTimer = setTimeout(() => {
      quitFlushTimer = null
      allowMainWindowClose = true
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close()
      allowMainWindowClose = false
    }, 3000)

    try {
      mainWindow.webContents.send('app-before-quit')
    } catch {
      allowMainWindowClose = true
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close()
      allowMainWindowClose = false
    }
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
  if (isQuitting) {
    hasFlushedQuitState = true
    allowMainWindowClose = true
    app.quit()
  } else {
    allowMainWindowClose = true
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.close()
    }
    allowMainWindowClose = false
  }
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

ipcMain.handle('write-binary-file', async (_event, filePath: string, base64Content: string) => {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true })
    const buf = Buffer.from(base64Content, 'base64')
    fs.writeFileSync(filePath, buf)
    return true
  } catch {
    return false
  }
})

ipcMain.handle('import-spatial-files', async (_e, workspacePath: string) => {
  const targetWs = workspacePath || readDefaultWorkspace() || getSystemDefaultDishaFolder()
  try { fs.mkdirSync(targetWs, { recursive: true }) } catch { /* ignore */ }
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
    const targetPath = path.join(targetWs, filename)
    
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
  // On macOS in production, prompt to move to /Applications if launched from Downloads or another folder
  if (!isDev && process.platform === 'darwin') {
    try {
      if (!app.isInApplicationsFolder()) {
        const moved = app.moveToApplicationsFolder({
          conflictHandler: () => true
        })
        if (moved) {
          // The app was moved to /Applications and relaunched; terminate this instance early.
          return
        }
      }
    } catch (err) {
      console.warn('Could not move app to Applications folder:', err)
    }
  }

  // Serve local files via localfile:// so the renderer can load them
  // regardless of whether it's running on file:// (prod) or http:// (dev).
  protocol.handle('localfile', (request) => {
    return net.fetch(request.url.replace(/^localfile:/, 'file:'))
  })

  await startBackend()
  const backendReady = await waitForBackend()
  if (!backendReady) console.error('Backend failed to start')

  setupApplicationMenu()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      allowMainWindowClose = false
      hasFlushedQuitState = false
      isQuitting = false
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin' || isQuitting) {
    stopBackend()
    app.quit()
  }
})

app.on('before-quit', (e) => {
  isQuitting = true

  if (!hasFlushedQuitState && mainWindow && !mainWindow.isDestroyed() && !mainWindow.webContents.isLoading()) {
    e.preventDefault()

    if (quitFlushTimer) clearTimeout(quitFlushTimer)
    quitFlushTimer = setTimeout(() => {
      quitFlushTimer = null
      hasFlushedQuitState = true
      allowMainWindowClose = true
      app.quit()
    }, 3000)

    try {
      mainWindow.webContents.send('app-before-quit')
    } catch {
      hasFlushedQuitState = true
      allowMainWindowClose = true
      app.quit()
    }
    return
  }

  stopBackend()
})
