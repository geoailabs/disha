const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const backendDir = __dirname;
const isWin = process.platform === 'win32';
const venvPy = isWin
  ? path.join(backendDir, '.buildenv', 'Scripts', 'python.exe')
  : path.join(backendDir, '.buildenv', 'bin', 'python');

const py = fs.existsSync(venvPy) ? venvPy : 'python';
const child = spawn(py, ['-m', 'PyInstaller', 'backend.spec', '--noconfirm'], {
  cwd: backendDir,
  stdio: 'inherit'
});

child.on('exit', (code) => {
  process.exit(code || 0);
});
