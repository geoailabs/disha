const http = require('http')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')

const TEST_PORT = 8766
const RETRIES = 40
const DELAY_MS = 500

function getBackendBinaryPath() {
  const isWin = process.platform === 'win32'
  const binaryName = isWin ? 'backend.exe' : 'backend'
  return path.resolve(__dirname, '..', '..', 'dist', 'backend', binaryName)
}

function checkHealth(port) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/health`, (res) => {
      let data = ''
      res.on('data', (chunk) => (data += chunk))
      res.on('end', () => {
        if (res.statusCode === 200) {
          try {
            const parsed = JSON.parse(data)
            resolve(parsed.status === 'ok')
          } catch {
            resolve(true)
          }
        } else {
          resolve(false)
        }
      })
    })
    req.on('error', () => resolve(false))
    req.end()
  })
}

async function smokeTestBackend() {
  const binaryPath = getBackendBinaryPath()
  console.log(`\x1b[34m[Smoke Test] Launching compiled Python binary on port ${TEST_PORT}...\x1b[0m`)
  console.log(`\x1b[90mBinary path: ${binaryPath}\x1b[0m`)

  if (!fs.existsSync(binaryPath)) {
    console.error(`\x1b[31m[Smoke Test] FAILED: Binary does not exist at ${binaryPath}. Did you run build:backend?\x1b[0m`)
    process.exit(1)
  }

  const child = spawn(binaryPath, ['--port', String(TEST_PORT)], {
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1', OPENAI_API_KEY: process.env.OPENAI_API_KEY || 'test_key' },
  })

  let outputLog = ''
  child.stdout.on('data', (d) => (outputLog += d.toString()))
  child.stderr.on('data', (d) => (outputLog += d.toString()))

  let isHealthy = false
  for (let i = 0; i < RETRIES; i++) {
    await new Promise((r) => setTimeout(r, DELAY_MS))
    if (await checkHealth(TEST_PORT)) {
      isHealthy = true
      break
    }
  }

  // Gracefully terminate child process
  child.kill('SIGTERM')
  setTimeout(() => {
    if (!child.killed) child.kill('SIGKILL')
  }, 1000)

  if (isHealthy) {
    console.log('\x1b[32m[Smoke Test] PASSED: Frozen Python backend booted and responded to /health cleanly!\x1b[0m')
  } else {
    console.error('\x1b[31m[Smoke Test] FAILED: Compiled backend failed to start or respond on port ' + TEST_PORT + '\x1b[0m')
    console.error('\x1b[33m--- Backend Output Logs ---\x1b[0m')
    console.error(outputLog || '(No output recorded)')
    console.error('\x1b[33m---------------------------\x1b[0m')
    process.exit(1)
  }
}

if (require.main === module) {
  smokeTestBackend()
}

module.exports = { smokeTestBackend }