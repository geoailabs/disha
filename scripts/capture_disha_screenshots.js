const { app, BrowserWindow, ipcMain, protocol, net } = require('electron')
const path = require('path')
const fs = require('fs')

const outDir = path.resolve(__dirname, '../assets/screenshots')
fs.mkdirSync(outDir, { recursive: true })
const sampleWorkspace = '/tmp/disha_sample_workspace'

app.whenReady().then(async () => {
  protocol.handle('localfile', (request) => {
    return net.fetch(request.url.replace(/^localfile:/, 'file:'))
  })

  ipcMain.handle('get-last-workspace', () => sampleWorkspace)
  ipcMain.handle('set-last-workspace', () => {})
  ipcMain.handle('get-api-key', () => 'sk-proj-DEMO-KEY-FOR-SETUP-GUIDE-xxxx')
  ipcMain.handle('set-api-key', () => true)
  ipcMain.handle('get-key-status', () => ({ openai: true, google_maps: false }))
  ipcMain.handle('get-google-maps-key', () => '')
  ipcMain.handle('set-google-maps-key', () => true)
  ipcMain.handle('get-gee-key', () => '')
  ipcMain.handle('set-gee-key', () => true)
  ipcMain.handle('get-models', () => [
    { id: 'gpt-4o', name: 'GPT-4o', provider: 'openai', locked: false },
    { id: 'o3-mini', name: 'o3-mini', provider: 'openai', locked: false },
  ])
  ipcMain.handle('get-current-model', () => 'gpt-4o')
  ipcMain.handle('switch-model', () => true)
  ipcMain.handle('read-directory', (_e, dir) => {
    try {
      const target = dir || sampleWorkspace
      const entries = fs.readdirSync(target, { withFileTypes: true })
      return entries
        .filter(e => !e.name.startsWith('.'))
        .map(e => ({
          name: e.name,
          path: path.join(target, e.name),
          isDirectory: e.isDirectory()
        }))
    } catch {
      return []
    }
  })
  ipcMain.handle('read-file', (_e, filePath) => {
    try {
      return fs.readFileSync(filePath, 'utf-8')
    } catch {
      return null
    }
  })
  ipcMain.handle('write-file', () => true)

  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    show: true,
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload: path.resolve(__dirname, '../apps/desktop/out/preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  const htmlPath = path.resolve(__dirname, '../apps/desktop/out/renderer/index.html')
  await win.loadFile(htmlPath)

  console.log('Waiting for workspace to load...')
  await new Promise(r => setTimeout(r, 4000))

  // Dismiss diagnostics if any
  await win.webContents.executeJavaScript(`
    try {
      const closeBtn = document.querySelector('.diag-close-btn')
      if (closeBtn) closeBtn.click()
    } catch (e) {}
  `)
  await new Promise(r => setTimeout(r, 1500))

  // Capture Main Workspace (with key set, so API drawer is clean/collapsed)
  const imgMain = await win.webContents.capturePage()
  fs.writeFileSync(path.join(outDir, '02_main_workspace_clean.png'), imgMain.toPNG())
  console.log('Saved 02_main_workspace_clean.png')

  // Switch to Layers Tab
  await win.webContents.executeJavaScript(`
    try {
      const tabs = Array.from(document.querySelectorAll('.tab'))
      const layersTab = tabs.find(t => t.innerText.includes('Layers'))
      if (layersTab) layersTab.click()
    } catch (e) {
      console.error(e)
    }
  `)
  await new Promise(r => setTimeout(r, 1500))

  const imgLayers = await win.webContents.capturePage()
  fs.writeFileSync(path.join(outDir, '04_layers_tab.png'), imgLayers.toPNG())
  console.log('Saved 04_layers_tab.png')

  // Switch to Export Tab
  await win.webContents.executeJavaScript(`
    try {
      const tabs = Array.from(document.querySelectorAll('.tab'))
      const exportTab = tabs.find(t => t.innerText.includes('Export'))
      if (exportTab) exportTab.click()
    } catch (e) {
      console.error(e)
    }
  `)
  await new Promise(r => setTimeout(r, 1500))

  const imgExport = await win.webContents.capturePage()
  fs.writeFileSync(path.join(outDir, '05_export_tab.png'), imgExport.toPNG())
  console.log('Saved 05_export_tab.png')

  console.log('Done capturing tabs!')
  win.close()
  app.quit()
})
