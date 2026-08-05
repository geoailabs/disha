const path = require('path')
const fs = require('fs')
const { spawnSync } = require('child_process')

const BACKEND_DIR = path.resolve(__dirname, '..', '..')
const VENV_DIR = path.join(BACKEND_DIR, '.buildenv')

function getPytestExec() {
  const isWin = process.platform === 'win32'
  const venvPytest = isWin
    ? path.join(VENV_DIR, 'Scripts', 'pytest.exe')
    : path.join(VENV_DIR, 'bin', 'pytest')

  if (fs.existsSync(venvPytest)) {
    return { cmd: venvPytest, args: ['tests/'] }
  }

  const venvPy = isWin
    ? path.join(VENV_DIR, 'Scripts', 'python.exe')
    : path.join(VENV_DIR, 'bin', 'python')

  const py = fs.existsSync(venvPy) ? venvPy : 'python'
  return { cmd: py, args: ['-m', 'pytest', 'tests/'] }
}

function runUnitTests() {
  console.log('\x1b[34m[Test] Running backend pytest functional test suite...\x1b[0m')
  const { cmd, args } = getPytestExec()

  const result = spawnSync(cmd, args, {
    stdio: 'inherit',
    cwd: BACKEND_DIR,
  })

  if (result.status !== 0) {
    console.error('\x1b[31m[Test] Unit & functional tests failed!\x1b[0m')
    process.exit(result.status || 1)
  }

  console.log('\x1b[32m[Test] All unit & functional tests passed successfully!\x1b[0m')
}

if (require.main === module) {
  runUnitTests()
}

module.exports = { runUnitTests }