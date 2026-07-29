import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  selectWorkspace: () => ipcRenderer.invoke('select-workspace'),
  readDirectory: (dirPath: string) => ipcRenderer.invoke('read-directory', dirPath),
  readFile: (filePath: string) => ipcRenderer.invoke('read-file', filePath),
  writeFile: (filePath: string, content: string) =>
    ipcRenderer.invoke('write-file', filePath, content),
  onAppBeforeQuit: (handler: () => void | Promise<void>) => {
    ipcRenderer.removeAllListeners('app-before-quit')
    ipcRenderer.on('app-before-quit', async () => {
      try { await handler() } finally { ipcRenderer.send('app-quit-flush-done') }
    })
  },
  getLastWorkspace: () => ipcRenderer.invoke('get-last-workspace'),
  setLastWorkspace: (p: string | null) => ipcRenderer.invoke('set-last-workspace', p),
  openFile: (opts: { filters?: { name: string; extensions: string[] }[] }) =>
    ipcRenderer.invoke('open-file', opts),
  readFileBase64: (filePath: string) => ipcRenderer.invoke('read-file-base64', filePath),
  getModels: () => ipcRenderer.invoke('get-models'),
  getCurrentModel: () => ipcRenderer.invoke('get-current-model'),
  switchModel: (model: string) => ipcRenderer.invoke('switch-model', model),
  importSpatialFiles: (workspacePath: string) => ipcRenderer.invoke('import-spatial-files', workspacePath),
  getAPIKey: () => ipcRenderer.invoke('get-api-key'),
  setAPIKey: (key: string) => ipcRenderer.invoke('set-api-key', key),
  getKeyStatus: () => ipcRenderer.invoke('get-key-status'),
  getGoogleMapsKey: () => ipcRenderer.invoke('get-google-maps-key'),
  setGoogleMapsKey: (key: string) => ipcRenderer.invoke('set-google-maps-key', key),
  getGEEKey: () => ipcRenderer.invoke('get-gee-key'),
  setGEEKey: (key: string) => ipcRenderer.invoke('set-gee-key', key),
  savePDF: (htmlContent: string, defaultName: string) => ipcRenderer.invoke('save-pdf', htmlContent, defaultName),
  onFullscreenChange: (handler: (isFullscreen: boolean) => void) => {
    ipcRenderer.removeAllListeners('fullscreen-change')
    ipcRenderer.on('fullscreen-change', (_event, value: boolean) => handler(value))
  },
})
