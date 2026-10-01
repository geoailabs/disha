const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const backendDir = __dirname;
const isWin = process.platform === 'win32';
const venvPy = isWin
  ? path.join(backendDir, '.buildenv', 'Scripts', 'python.exe')
  : path.join(backendDir, '.buildenv', 'bin', 'python');

const py = fs.existsSync(venvPy) ? venvPy : 'python';

function repairMacSqliteBundle() {
  if (process.platform !== 'darwin') return;

  const internalDir = path.join(backendDir, 'dist', 'backend', '_internal');
  const bundledSqlite = path.join(internalDir, 'libsqlite3.0.dylib');
  if (!fs.existsSync(bundledSqlite) && !fs.lstatSync(bundledSqlite, { throwIfNoEntry: false })) return;

  let sqliteSource = '';
  try {
    sqliteSource = execFileSync(py, ['-c', [
      'import sys, pathlib',
      'candidates = [pathlib.Path(sys.base_prefix) / "lib" / "libsqlite3.0.dylib", pathlib.Path(sys.prefix) / "lib" / "libsqlite3.0.dylib"]',
      'print(next((str(p) for p in candidates if p.exists()), ""))',
    ].join(';')], { encoding: 'utf8' }).trim();
  } catch (err) {
    console.warn('[backend] could not locate Python SQLite dylib:', err.message);
    return;
  }

  if (!sqliteSource || !fs.existsSync(sqliteSource)) {
    console.warn('[backend] Python SQLite dylib was not found; leaving bundle unchanged');
    return;
  }

  try {
    fs.rmSync(bundledSqlite, { force: true });
    fs.copyFileSync(sqliteSource, bundledSqlite);
    fs.chmodSync(bundledSqlite, 0o755);
    console.log(`[backend] repaired bundled SQLite library from ${sqliteSource}`);
  } catch (err) {
    console.warn('[backend] failed to repair bundled SQLite library:', err.message);
  }
}

const child = spawn(py, ['-m', 'PyInstaller', 'backend.spec', '--noconfirm'], {
  cwd: backendDir,
  stdio: 'inherit'
});

child.on('exit', (code) => {
  if (code === 0) repairMacSqliteBundle();
  process.exit(code || 0);
});
