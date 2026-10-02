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
  if (!fs.existsSync(internalDir)) return;

  const bundledSqlite = path.join(internalDir, 'libsqlite3.0.dylib');
  const bundledSqliteAlt = path.join(internalDir, 'libsqlite3.dylib');
  const fionaSqlite = path.join(internalDir, 'fiona', '.dylibs', 'libsqlite3.0.dylib');

  function removeIfBrokenOrExists(targetPath) {
    try {
      const stat = fs.lstatSync(targetPath, { throwIfNoEntry: false });
      if (stat) {
        if (stat.isSymbolicLink()) {
          fs.unlinkSync(targetPath);
        } else {
          fs.rmSync(targetPath, { force: true, recursive: true });
        }
      }
    } catch (e) {}
  }

  let sqliteSource = '';
  try {
    sqliteSource = execFileSync(py, ['-c', [
      'import sys, pathlib, ctypes, subprocess',
      'candidates = [',
      '  pathlib.Path(sys.base_prefix) / "lib" / "libsqlite3.0.dylib",',
      '  pathlib.Path(sys.base_prefix) / "lib" / "libsqlite3.dylib",',
      '  pathlib.Path(sys.prefix) / "lib" / "libsqlite3.0.dylib",',
      '  pathlib.Path(sys.prefix) / "lib" / "libsqlite3.dylib",',
      '  pathlib.Path("/opt/homebrew/opt/sqlite/lib/libsqlite3.0.dylib"),',
      '  pathlib.Path("/opt/homebrew/opt/sqlite/lib/libsqlite3.dylib"),',
      '  pathlib.Path("/usr/local/opt/sqlite/lib/libsqlite3.0.dylib"),',
      '  pathlib.Path("/usr/local/opt/sqlite/lib/libsqlite3.dylib"),',
      ']',
      'try:',
      '  brew_p = subprocess.check_output(["brew", "--prefix", "sqlite"], text=True, stderr=subprocess.DEVNULL).strip()',
      '  if brew_p: candidates.extend([pathlib.Path(brew_p) / "lib" / "libsqlite3.0.dylib", pathlib.Path(brew_p) / "lib" / "libsqlite3.dylib"])',
      'except Exception: pass',
      'found = ""',
      'for c in candidates:',
      '  if c.exists():',
      '    r = c.resolve()',
      '    if r.exists():',
      '      try:',
      '        lib = ctypes.cdll.LoadLibrary(str(r))',
      '        if hasattr(lib, "sqlite3_deserialize"):',
      '          found = str(r); break',
      '      except Exception: pass',
      'print(found)',
    ].join('\n')], { encoding: 'utf8' }).trim();
  } catch (err) {
    console.warn('[backend] could not query Python SQLite candidates:', err.message);
  }

  if (sqliteSource && fs.existsSync(sqliteSource)) {
    try {
      removeIfBrokenOrExists(bundledSqlite);
      fs.copyFileSync(sqliteSource, bundledSqlite);
      fs.chmodSync(bundledSqlite, 0o755);

      removeIfBrokenOrExists(bundledSqliteAlt);
      fs.copyFileSync(sqliteSource, bundledSqliteAlt);
      fs.chmodSync(bundledSqliteAlt, 0o755);

      if (fs.existsSync(path.dirname(fionaSqlite))) {
        removeIfBrokenOrExists(fionaSqlite);
        fs.copyFileSync(sqliteSource, fionaSqlite);
        fs.chmodSync(fionaSqlite, 0o755);
      }
      console.log(`[backend] repaired bundled SQLite library from ${sqliteSource}`);
    } catch (err) {
      console.warn('[backend] failed to repair bundled SQLite library:', err.message);
    }
  } else {
    // If not found, ensure any broken dangling symlinks are removed to prevent ENOENT during packaging
    const stat = fs.lstatSync(bundledSqlite, { throwIfNoEntry: false });
    if (stat && stat.isSymbolicLink() && !fs.existsSync(bundledSqlite)) {
      removeIfBrokenOrExists(bundledSqlite);
    }
    const statAlt = fs.lstatSync(bundledSqliteAlt, { throwIfNoEntry: false });
    if (statAlt && statAlt.isSymbolicLink() && !fs.existsSync(bundledSqliteAlt)) {
      removeIfBrokenOrExists(bundledSqliteAlt);
    }
    console.warn('[backend] Python SQLite dylib was not found; ensured no broken symlinks remain');
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
