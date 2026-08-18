import { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import 'highlight.js/styles/github-dark.css'
import {
  ChatMessage,
  Conversation,
  MapContext,
  MapAction,
  ChatErrorMessage,
} from '../types'
import type { DocumentImage } from './DocumentView'
import appIcon from '../assets/icon.png'
import { IMAGE_EXTS, MIME_MAP, rasterizePdfPage } from '../lib/pdf-raster'
import './ChatPanel.css'

const SUGGESTION_POOL: string[] = [
  // GIS / spatial analysis
  "What's the total area of my polygons in hectares?",
  'Buffer the selected layer by 200 meters',
  'Compute the centroid of each polygon',
  // OSM data fetching
  'Find all hospitals within 2 km of the current view',
  'Show me schools and parks in this area',
  // Boundaries
  'Fetch the administrative boundary for this city',
  // Routing
  'Get a driving route between these two points',
  // Weather / climate
  "What's the historical rainfall here?",
  // Demographics
  'Pull population density for this region',
  // Zoning / planning workflows
  'Apply mixed-use zoning to the polygons in the south-east',
  'Highlight all R1 zones',
  // Web search
  'Search the web for transit-oriented development guidelines',
  // Document mode
  'Summarize the planning document I just opened',
]

function pickSuggestions(n: number): string[] {
  const shuffled = [...SUGGESTION_POOL].sort(() => Math.random() - 0.5)
  return shuffled.slice(0, Math.max(1, Math.min(n, shuffled.length)))
}

const BACKEND_WS = 'ws://localhost:8765/api/chat/ws'

// ── ResearchBubble ────────────────────────────────────────────────────────────

type ResearchPhase = 'idle' | 'running' | 'done'

interface ResearchBubbleProps {
  phase: 'running' | 'done'
  steps: string[]
  reasoning: string
  markdown: string
  citations: Array<{url: string; title: string}>
  expanded: boolean
  onToggleExpand: () => void
  onDownloadMd: () => void
  onDownloadPdf: () => void
}

function ResearchBubble({
  phase,
  steps,
  reasoning,
  markdown,
  citations,
  expanded,
  onToggleExpand,
  onDownloadMd,
  onDownloadPdf,
}: ResearchBubbleProps) {
  const stepsRef = useRef<HTMLDivElement>(null)
  const liveRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (stepsRef.current) {
      stepsRef.current.scrollTop = stepsRef.current.scrollHeight
    }
  }, [steps.length])

  // Keep the live report view pinned to the bottom as tokens stream in.
  useEffect(() => {
    if (phase === 'running' && liveRef.current) {
      liveRef.current.scrollTop = liveRef.current.scrollHeight
    }
  }, [markdown, reasoning, phase])

  return (
    <div className="research-bubble">
      <div className="research-bubble-header">
        {phase === 'running' ? (
          <>
            <span className="research-icon spinning">⟳</span>
            <span className="research-title">Deep Research</span>
            {steps.length > 0 && (
              <span className="research-count">{steps.length} searches</span>
            )}
          </>
        ) : (
          <>
            <span className="research-icon done">✓</span>
            <span className="research-title">Deep Research Complete</span>
            <span className="research-count">
              {steps.length} {steps.length === 1 ? 'search' : 'searches'}
            </span>
          </>
        )}
      </div>

      {steps.length > 0 && (
        <div className="research-steps" ref={stepsRef}>
          {steps.map((step, i) => {
            const isLast = i === steps.length - 1
            const isDone = phase === 'done' || !isLast
            const generic = /^web search #\d+$/.test(step)
            return (
              <div key={i} className={`research-step ${isDone ? 'done' : 'active'}`}>
                <span className="step-icon">{isDone ? '✓' : '⟳'}</span>
                <span className="step-text">
                  {generic ? 'Searching the web…' : `Searching: ${step}`}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Live view — reasoning + the report being written, streamed in. */}
      {phase === 'running' && (reasoning || markdown) && (
        <div className="research-live" ref={liveRef}>
          {reasoning && !markdown && (
            <p className="research-thinking">{reasoning}</p>
          )}
          {markdown && (
            <div className="research-full-report streaming">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={headingComponents}
              >
                {markdown}
              </ReactMarkdown>
            </div>
          )}
        </div>
      )}

      {/* Nothing has streamed back yet — reassure the user it's working. */}
      {phase === 'running' && steps.length === 0 && !reasoning && !markdown && (
        <p className="research-thinking">
          Planning the research — searching the web and gathering sources. This can take a few minutes.
        </p>
      )}

      {phase === 'done' && markdown && (
        <div className="research-report">
          <div className="research-actions">
            <button className="research-toggle" onClick={onToggleExpand}>
              {expanded ? '▲ Hide full report' : '▼ View full report'}
            </button>
            <button className="research-dl-btn" onClick={onDownloadMd}>Download .md</button>
            <button className="research-dl-btn pdf" onClick={onDownloadPdf}>Download PDF</button>
          </div>

          {expanded && (
            <div className="research-full-report">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={headingComponents}
              >
                {markdown}
              </ReactMarkdown>
            </div>
          )}

          {citations.length > 0 && (
            <div className="research-citations">
              <span className="citations-label">Sources:</span>
              {citations.map((c, i) => (
                <a key={i} href={c.url} target="_blank" rel="noreferrer" className="citation-link">
                  {c.title || c.url}
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface ChatPanelProps {
  conversations: Conversation[]
  activeConversation: Conversation | null
  onCreateConversation: () => void
  onSelectConversation: (id: string) => void
  onDeleteConversation: (id: string) => void
  onMessagesChange: (messages: ChatMessage[]) => void
  onRenameConversation?: (id: string, title: string) => void
  mapContext: MapContext
  onMapAction: (action: MapAction) => void
  documentImage?: DocumentImage | null
  injectedMessage?: { text: string; nonce: number } | null
  onComposeMapFigure?: (title: string) => HTMLCanvasElement | null
}

function CodePre({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) {
  const preRef = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState(false)

  return (
    <div className="code-block">
      <div className="code-block-header">
        <button
          className="code-copy-btn"
          onClick={() => {
            navigator.clipboard.writeText(preRef.current?.textContent || '')
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
          }}
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre ref={preRef} {...props}>
        {children}
      </pre>
    </div>
  )
}

const getSlug = (node: any): string => {
  if (!node) return ''
  if (typeof node === 'string') {
    return node
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9\s-]/g, '')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/(^-|-$)/g, '')
  }
  if (Array.isArray(node)) {
    return node.map(getSlug).join('-').replace(/-+/g, '-').replace(/(^-|-$)/g, '')
  }
  if (node.props && node.props.children) {
    return getSlug(node.props.children)
  }
  return ''
}

const headingComponents = {
  h1: ({ children, ...props }: any) => <h1 id={getSlug(children)} {...props}>{children}</h1>,
  h2: ({ children, ...props }: any) => <h2 id={getSlug(children)} {...props}>{children}</h2>,
  h3: ({ children, ...props }: any) => <h3 id={getSlug(children)} {...props}>{children}</h3>,
  h4: ({ children, ...props }: any) => <h4 id={getSlug(children)} {...props}>{children}</h4>,
  h5: ({ children, ...props }: any) => <h5 id={getSlug(children)} {...props}>{children}</h5>,
  h6: ({ children, ...props }: any) => <h6 id={getSlug(children)} {...props}>{children}</h6>,
}

interface ClarifyingQuestion {
  question: string
  options: string[]
  is_multi_select: boolean
}

export interface ChatPanelHandle {
  stopStreaming: () => void
  resetHistory: () => void
}

const ChatPanel = forwardRef<ChatPanelHandle, ChatPanelProps>(({
  conversations,
  activeConversation,
  onCreateConversation,
  onSelectConversation,
  onDeleteConversation,
  onMessagesChange,
  onRenameConversation,
  mapContext,
  onMapAction,
  documentImage,
  injectedMessage,
  onComposeMapFigure,
}, ref) => {
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [toolStatus, setToolStatus] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [availableModels, setAvailableModels] = useState<ModelInfo[]>([])
  const [currentModel, setCurrentModel] = useState<string>('')
  const [isSwitchingModel, setIsSwitchingModel] = useState(false)
  const [chatError, setChatError] = useState<ChatErrorMessage | null>(null)
  const [suggestions, setSuggestions] = useState<string[]>(() => pickSuggestions(3))

  // Attachments State
  const [attachments, setAttachments] = useState<Array<{
    base64: string
    mimeType: string
    fileName: string
    filePath?: string
  }>>([])
  const [attachmentLoading, setAttachmentLoading] = useState(false)
  const [attachmentError, setAttachmentError] = useState<string | null>(null)

  // API Key State
  const [apiKey, setApiKey] = useState('')
  const [showApiKeyInput, setShowApiKeyInput] = useState(false)
  const [isSavingKey, setIsSavingKey] = useState(false)
  const [keyError, setKeyError] = useState<string | null>(null)
  const [keySuccess, setKeySuccess] = useState(false)
  const [isKeyLoaded, setIsKeyLoaded] = useState(false)
  const [hasEnvApiKey, setHasEnvApiKey] = useState(false)

  // Conversation renaming state
  const [editingConversationId, setEditingConversationId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const clickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Google Maps API Key State
  const [googleKey, setGoogleKey] = useState('')
  const [hasEnvGoogleKey, setHasEnvGoogleKey] = useState(false)
  const [isSavingGoogleKey, setIsSavingGoogleKey] = useState(false)
  const [googleKeyError, setGoogleKeyError] = useState<string | null>(null)
  const [googleKeySuccess, setGoogleKeySuccess] = useState(false)

  // GEE Service Account Key State
  const [geeKey, setGeeKey] = useState('')
  const [isSavingGeeKey, setIsSavingGeeKey] = useState(false)
  const [geeKeyError, setGeeKeyError] = useState<string | null>(null)
  const [geeKeySuccess, setGeeKeySuccess] = useState(false)

  // Deep research state
  const [researchPhase, setResearchPhase] = useState<ResearchPhase>('idle')
  const [researchSteps, setResearchSteps] = useState<string[]>([])
  const [researchMarkdown, setResearchMarkdown] = useState('')
  const [researchCitations, setResearchCitations] = useState<Array<{url: string; title: string}>>([])
  const [researchExpanded, setResearchExpanded] = useState(false)
  const [researchReasoning, setResearchReasoning] = useState('')
  const reportMdRef = useRef('')
  const headerContainerRef = useRef<HTMLDivElement>(null)

  // Interactive Clarifying Questions state
  const [activeQuestion, setActiveQuestion] = useState<ClarifyingQuestion | null>(null)
  const [selectedOptions, setSelectedOptions] = useState<string[]>([])
  const historyBtnRef = useRef<HTMLButtonElement>(null)
  const historyListRef = useRef<HTMLDivElement>(null)

  // Close history list when clicking outside
  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (
        showHistory &&
        historyListRef.current &&
        !historyListRef.current.contains(e.target as Node) &&
        historyBtnRef.current &&
        !historyBtnRef.current.contains(e.target as Node)
      ) {
        setShowHistory(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [showHistory])


  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pendingInputRef = useRef<string | null>(null)
  // Tracks the in-flight assistant message: its accumulator and the
  // message-list snapshot the stream is being appended to. The WS handler
  // is attached once and dispatches into this slot, so back-to-back sends
  // never cross-contaminate each other.
  const inFlightRef = useRef<{
    base: ChatMessage[]
    accum: string
    timestamp: number
    research?: {
      phase: 'idle' | 'running' | 'done'
      steps: string[]
      reasoning: string
      markdown: string
      citations: Array<{ url: string; title: string }>
    }
  } | null>(null)
  // Whether the current WS connection has already received the history
  // replay payload. Reset whenever we open a fresh connection.
  const historySentRef = useRef(false)

  const messages = activeConversation?.messages ?? []
  const hasOpenAIKey = apiKey.trim().length > 0 || hasEnvApiKey
  const hasGoogleMapsKey = googleKey.trim().length > 0 || hasEnvGoogleKey
  const onMessagesChangeRef = useRef(onMessagesChange)
  onMessagesChangeRef.current = onMessagesChange
  const onMapActionRef = useRef(onMapAction)
  onMapActionRef.current = onMapAction

  useEffect(() => {
    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const loadKeys = async (attempt = 0) => {
      let storedApiKey = ''
      let storedGoogleKey = ''
      let envOpenAI = false
      let envGoogle = false
      let envStatusLoaded = false

      try {
        storedApiKey = await window.electronAPI.getAPIKey()
      } catch (err) {
        console.error('Failed to load API key from secure storage:', err)
      }

      try {
        storedGoogleKey = await window.electronAPI.getGoogleMapsKey()
      } catch (err) {
        console.error('Failed to load Google Maps API key:', err)
      }

      try {
        const status = await window.electronAPI.getKeyStatus()
        envOpenAI = envOpenAI || !!status.openai
        envGoogle = envGoogle || !!status.google_maps
      } catch (err) {
        console.error('Failed to detect Electron environment API keys:', err)
      }

      try {
        const res = await fetch('http://localhost:8765/api/chat/key-status')
        const status = await res.json()
        envOpenAI = envOpenAI || !!status.openai
        envGoogle = envGoogle || !!status.google_maps
        envStatusLoaded = true
      } catch (err) {
        console.error('Failed to detect backend environment API keys:', err)
      }

      if (!cancelled) {
        setApiKey(storedApiKey || '')
        setGoogleKey(storedGoogleKey || '')
        setHasEnvApiKey(envOpenAI)
        setHasEnvGoogleKey(envGoogle)
        setIsKeyLoaded(true)
        setShowApiKeyInput(!(storedApiKey || envOpenAI))
      }

      if (!cancelled && !storedApiKey && !envStatusLoaded && attempt < 20) {
        retryTimer = setTimeout(() => loadKeys(attempt + 1), 500)
      }
    }

    loadKeys()

    window.electronAPI.getGEEKey()
      .then((key) => {
        if (!cancelled) setGeeKey(key || '')
      })
      .catch((err) => {
        console.error('Failed to load GEE credentials:', err)
      })

    return () => {
      cancelled = true
      if (retryTimer) clearTimeout(retryTimer)
    }
  }, [])

  useEffect(() => {
    if (activeConversation && pendingInputRef.current) {
      const pending = pendingInputRef.current
      pendingInputRef.current = null
      setInput(pending)
      setTimeout(() => {
        setInput('')
        sendMessageDirect(pending)
      }, 0)
    }
  }, [activeConversation?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (
        showApiKeyInput &&
        !target.closest('.api-settings-btn') &&
        !target.closest('.api-key-config-bar')
      ) {
        setShowApiKeyInput(false)
      }
      if (
        showHistory &&
        !target.closest('.chat-header-action-btn') &&
        !target.closest('.chat-history-list')
      ) {
        setShowHistory(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [showApiKeyInput, showHistory])

  const lastInjectedNonceRef = useRef<number>(0)

  useEffect(() => {
    if (!injectedMessage) return
    if (injectedMessage.nonce === lastInjectedNonceRef.current) return
    lastInjectedNonceRef.current = injectedMessage.nonce
    if (isStreaming) return
    if (!activeConversation) {
      // No conversation yet — stash it; the activeConversation effect will send.
      pendingInputRef.current = injectedMessage.text
      onCreateConversation()
      return
    }
    sendMessageDirect(injectedMessage.text)
  }, [injectedMessage]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    Promise.all([
      window.electronAPI.getModels(),
      window.electronAPI.getCurrentModel(),
    ]).then(([models, model]) => {
      setAvailableModels(models)
      setCurrentModel(model)
    }).catch(() => { /* not in Electron context */ })
  }, [])

  const scrollToBottom = useCallback((): void => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(scrollToBottom, [messages, scrollToBottom])

  const handleWsMessage = useCallback((event: MessageEvent) => {
    let data: {
      type?: string
      content?: string
      tool?: string
      action?: string
      payload?: unknown
      code?: string
      message?: string
      query?: string
      delta?: string
      markdown?: string
      citations?: Array<{url: string; title: string}>
    }
    try {
      data = JSON.parse(event.data)
    } catch {
      return
    }
    if (data.type === 'stream') {
      const slot = inFlightRef.current
      if (!slot) return
      slot.accum += data.content || ''
      onMessagesChangeRef.current([
        ...slot.base,
        { role: 'assistant', content: slot.accum, timestamp: slot.timestamp },
      ])
    } else if (data.type === 'tool_use') {
      setToolStatus(`Using ${data.tool}...`)
    } else if (data.type === 'action' && data.action) {
      onMapActionRef.current({
        type: data.action,
        payload: (data.payload || {}) as never,
      } as MapAction)
    } else if (data.type === 'error') {
      const msg = String(data.message || 'Unknown error')
      const lower = msg.toLowerCase()
      // Suppress noisy concurrency recv error when the user stops the run.
      if (lower.includes('cannot call recv') || lower.includes('another coroutine is already') || lower.includes('recv while')) {
        // Ignore this error as it originates from a cancelled/closed connection.
      } else {
        setChatError({
          code: String(data.code || 'unknown'),
          message: msg,
        })
      }
      // Treat error as terminal for the in-flight stream so the user can
      // send the next message; an `end` frame may or may not follow.
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    } else if (data.type === 'research_start') {
      const slot = inFlightRef.current
      if (slot) {
        slot.research = {
          phase: 'running',
          steps: [],
          reasoning: '',
          markdown: '',
          citations: []
        }
        onMessagesChangeRef.current([
          ...slot.base,
          { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
        ])
      }
      setToolStatus('Deep Research in progress…')
    } else if (data.type === 'research_step') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const q = data.query ?? ''
        if (q) {
          slot.research.steps = [...slot.research.steps, q]
          onMessagesChangeRef.current([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        }
      }
    } else if (data.type === 'research_reasoning_delta') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const d = data.delta ?? ''
        if (d) {
          slot.research.reasoning += d
          onMessagesChangeRef.current([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        }
      }
    } else if (data.type === 'research_text_delta') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const d = data.delta ?? ''
        if (d) {
          slot.research.markdown += d
          onMessagesChangeRef.current([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        }
      }
      setToolStatus(null)
    } else if (data.type === 'research_heartbeat') {
      // keep-alive ping — no UI update needed
    } else if (data.type === 'research_report') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        const md = data.markdown ?? ''
        slot.research.markdown = md
        slot.research.citations = data.citations || []
        slot.research.phase = 'done'
        onMessagesChangeRef.current([
          ...slot.base,
          { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
        ])
      }
      setToolStatus(null)
    } else if (data.type === 'research_done') {
      const slot = inFlightRef.current
      if (slot && slot.research) {
        slot.research.phase = 'done'
        onMessagesChangeRef.current([
          ...slot.base,
          { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
        ])
      }
      setToolStatus(null)
    } else if (data.type === 'ask_question') {
      setActiveQuestion({
        question: data.question || '',
        options: (data.options as string[]) || [],
        is_multi_select: !!data.is_multi_select
      })
      setSelectedOptions([])
    } else if (data.type === 'end') {
      setIsStreaming(false)
      setToolStatus(null)
      inFlightRef.current = null
    }
  }, [])

  const connectWebSocket = useCallback((): Promise<WebSocket> => {
    return new Promise((resolve, reject) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        resolve(wsRef.current)
        return
      }
      const ws = new WebSocket(BACKEND_WS)
      historySentRef.current = false
      ws.addEventListener('message', handleWsMessage)
      ws.addEventListener('open', () => {
        wsRef.current = ws
        resolve(ws)
      })
      ws.addEventListener('error', () =>
        reject(new Error('WebSocket connection failed')),
      )
      ws.addEventListener('close', () => {
        wsRef.current = null
        historySentRef.current = false
        setIsStreaming(false)
        setToolStatus(null)
        inFlightRef.current = null
        setActiveQuestion(null)
      })
    })
  }, [handleWsMessage])

  const handleStopStreaming = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }))
    }
    const slot = inFlightRef.current
    if (slot) {
      if (slot.research) {
        if (slot.research.markdown || slot.research.steps.length > 0) {
          slot.research.phase = 'done'
          onMessagesChange([
            ...slot.base,
            { role: 'assistant', content: '', timestamp: slot.timestamp, research: { ...slot.research } }
          ])
        } else {
          onMessagesChange(slot.base)
        }
      } else if (slot.accum) {
        onMessagesChange([
          ...slot.base,
          { role: 'assistant', content: slot.accum, timestamp: slot.timestamp },
        ])
      } else {
        onMessagesChange(slot.base)
      }
    }
    setIsStreaming(false)
    setToolStatus(null)
    inFlightRef.current = null
    setActiveQuestion(null)
  }, [onMessagesChange])

  useImperativeHandle(ref, () => ({
    stopStreaming: () => {
      handleStopStreaming()
    },
    resetHistory: () => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'reset_history' }))
      }
    }
  }), [handleStopStreaming])

  const downloadResearchMd = useCallback((md: string) => {
    if (!md) return
    const blob = new Blob([md], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `urban-planning-report-${Date.now()}.md`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 150)
  }, [])

  const downloadResearchPdf = useCallback(async (md: string) => {
    if (!md) return
    const { jsPDF } = await import('jspdf')
    const doc = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' })
    const pageWidth = doc.internal.pageSize.getWidth()
    const pageHeight = doc.internal.pageSize.getHeight()
    const margin = 48
    const maxLineWidth = pageWidth - margin * 2
    let y = margin

    const checkY = (needed: number) => {
      if (y + needed > pageHeight - margin) {
        doc.addPage()
        y = margin
      }
    }

    // Strip inline markdown to plain text for jsPDF's core fonts:
    // **bold**/__bold__ → bold, *italic*, `code`, [text](url) → text (url),
    // and leftover emphasis/escape markers.
    const stripInline = (s: string): string =>
      s
        .replace(/!\[[^\]]*\]\([^)]*\)/g, '')            // images → drop
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1 ($2)')  // links → text (url)
        .replace(/`([^`]+)`/g, '$1')                      // inline code
        .replace(/(\*\*|__)(.*?)\1/g, '$2')               // bold
        .replace(/(\*|_)(.*?)\1/g, '$2')                  // italic
        .replace(/~~(.*?)~~/g, '$2')                       // strikethrough
        .replace(/\\([\\`*_{}[\]()#+\-.!])/g, '$1')        // escaped chars

    const writeWrapped = (text: string, size: number, style: 'normal' | 'bold' | 'italic', lh: number, indent = 0) => {
      doc.setFontSize(size); doc.setFont('helvetica', style)
      const wrapped = doc.splitTextToSize(text, maxLineWidth - indent) as string[]
      for (const wl of wrapped) {
        checkY(lh); doc.text(wl, margin + indent, y); y += lh
      }
    }

    const lines = md.split('\n')
    let mapInserted = false
    const hasHeader = lines.some((l) => l.trimStart().startsWith('# '))

    const insertMap = () => {
      if (mapInserted || !onComposeMapFigure) return
      const figure = onComposeMapFigure(activeConversation?.title || 'Project Map')
      if (!figure) return
      try {
        const img = figure.toDataURL('image/png')
        const aspect = figure.height > 0 ? figure.width / figure.height : 1.6
        const drawW = maxLineWidth
        const drawH = drawW / aspect

        checkY(drawH + 34)
        doc.addImage(img, 'PNG', margin, y, drawW, drawH)
        y += drawH + 12

        // Compile dynamic caption showing active conversation title and visible layers
        const visibleLayers = (mapContext.layers || [])
          .filter((l) => l.visible)
          .map((l) => l.name)
        const conversationTitle = activeConversation?.title || 'Urban Project'
        const layersPart = visibleLayers.length > 0
          ? ` showing active layers: ${visibleLayers.join(', ')}`
          : ' with no active layers'
        const caption = `Figure 1: Composed Map for "${conversationTitle}"${layersPart}.`

        writeWrapped(caption, 9, 'italic', 12)
        y += 16
      } catch (err) {
        console.error('Failed to add map image to PDF:', err)
      }
      mapInserted = true
    }

    if (!hasHeader) {
      insertMap()
    }

    for (let i = 0; i < lines.length; i++) {
      const raw = lines[i].replace(/\s+$/, '')
      const line = raw.trimStart()

      // Markdown table → render as a bordered grid of cells.
      const isTableRow = /^\|.*\|$/.test(line)
      if (isTableRow) {
        const rows: string[][] = []
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          const cells = lines[i].trim().replace(/^\||\|$/g, '').split('|').map((c) => stripInline(c.trim()))
          // Skip the |---|---| separator row.
          if (!cells.every((c) => /^:?-{2,}:?$/.test(c) || c === '')) rows.push(cells)
          i++
        }
        i-- // step back; outer loop will advance
        if (rows.length) {
          const cols = Math.max(...rows.map((r) => r.length))
          const colW = (maxLineWidth) / cols
          doc.setFontSize(9)
          for (let r = 0; r < rows.length; r++) {
            const isHeader = r === 0
            doc.setFont('helvetica', isHeader ? 'bold' : 'normal')
            // Measure tallest cell in the row for height.
            const cellLines = rows[r].map((c) => doc.splitTextToSize(c, colW - 8) as string[])
            const rowH = Math.max(14, ...cellLines.map((cl) => cl.length * 11 + 6))
            checkY(rowH)
            for (let c = 0; c < cols; c++) {
              const x = margin + c * colW
              doc.setDrawColor(200); doc.rect(x, y, colW, rowH)
              const cl = cellLines[c] || ['']
              cl.forEach((t, li) => doc.text(t, x + 4, y + 12 + li * 11))
            }
            y += rowH
          }
          y += 6
        }
        continue
      }

      if (line.startsWith('### ')) {
        y += 6; writeWrapped(stripInline(line.slice(4)), 13, 'bold', 17)
      } else if (line.startsWith('## ')) {
        y += 8; writeWrapped(stripInline(line.slice(3)), 16, 'bold', 21)
      } else if (line.startsWith('# ')) {
        y += 8; writeWrapped(stripInline(line.slice(2)), 20, 'bold', 27)
        y += 12
        insertMap()
      } else if (/^>\s?/.test(line)) {
        writeWrapped(stripInline(line.replace(/^>\s?/, '')), 11, 'italic', 14, 16)
      } else if (/^(\s*)([-*+])\s+/.test(raw)) {
        const depth = (raw.match(/^\s*/)?.[0].length ?? 0) >= 2 ? 16 : 0
        writeWrapped('• ' + stripInline(line.replace(/^[-*+]\s+/, '')), 11, 'normal', 14, 12 + depth)
      } else if (/^\d+\.\s+/.test(line)) {
        writeWrapped(stripInline(line), 11, 'normal', 14, 12)
      } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
        checkY(12); doc.setDrawColor(220); doc.line(margin, y, pageWidth - margin, y); y += 12
      } else if (line === '') {
        y += 8
      } else {
        writeWrapped(stripInline(line), 11, 'normal', 14)
      }
    }
    doc.save(`urban-planning-report-${Date.now()}.pdf`)
  }, [onComposeMapFigure, activeConversation, mapContext])

  useEffect(() => {
    setResearchPhase('idle')
    setResearchSteps([])
    setResearchMarkdown('')
    setResearchCitations([])
    setResearchExpanded(false)
    setResearchReasoning('')
    reportMdRef.current = ''
    setActiveQuestion(null)
  }, [activeConversation?.id])

  useEffect(() => {
    if (wsRef.current) {
      const ws = wsRef.current
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
      wsRef.current = null
    }
    historySentRef.current = false
  }, [mapContext.workspace, activeConversation?.id])

  /** Convert raw API error strings/objects into a short, friendly sentence. */
  const friendlyKeyError = (raw: string): string => {
    // OpenAI returns something like: "Error code: 401 - {'error': {'message': '...', 'code': 'invalid_api_key'}}"
    // Try to extract just the inner message.
    try {
      const jsonMatch = raw.match(/\{.*\}/s)
      if (jsonMatch) {
        // Replace single quotes with double quotes for JSON.parse
        const obj = JSON.parse(jsonMatch[0].replace(/'/g, '"'))
        const msg: string =
          obj?.error?.message ||
          obj?.message ||
          raw
        if (msg.includes('Incorrect API key')) return '❌ Incorrect API key — double-check your key at platform.openai.com/account/api-keys'
        if (msg.includes('exceeded') || msg.includes('quota')) return '⚠️ Quota exceeded — check your billing at platform.openai.com/account/billing'
        if (msg.includes('deactivated') || msg.includes('disabled')) return '🚫 This key has been deactivated by OpenAI'
        return `❌ ${msg.split('.')[0]}.`
      }
    } catch { /* fall through */ }
    if (raw.toLowerCase().includes('invalid')) return '❌ Invalid API key — please verify and try again'
    if (raw.toLowerCase().includes('quota') || raw.toLowerCase().includes('exceeded')) return '⚠️ Quota exceeded — check your billing'
    return raw
  }

  const validateAndSaveKey = async (keyToSave: string): Promise<boolean> => {
    setIsSavingKey(true)
    setKeyError(null)
    setKeySuccess(false)
    try {
      const res = await fetch('http://localhost:8765/api/chat/validate-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: keyToSave }),
      })
      const data = await res.json()
      if (data.valid) {
        const ok = await window.electronAPI.setAPIKey(keyToSave)
        if (ok) {
          setApiKey(keyToSave)
          setChatError(null)
          setIsSavingKey(false)
          setKeySuccess(true)
          setTimeout(() => {
            setKeySuccess(false)
            setShowApiKeyInput(false)
          }, 1800)
          return true
        } else {
          setKeyError('Failed to save key securely to system keychain.')
        }
      } else {
        setKeyError(friendlyKeyError(data.error || 'Invalid API Key. Please verify and try again.'))
      }
    } catch (err) {
      setKeyError('Could not reach verification server. Make sure the backend is running.')
    }
    setIsSavingKey(false)
    return false
  }

  const clearApiKey = async () => {
    const ok = await window.electronAPI.setAPIKey('')
    if (ok) {
      setApiKey('')
      setShowApiKeyInput(!hasEnvApiKey)
      setChatError(null)
    }
  }

  const saveGoogleKey = async (keyToSave: string): Promise<boolean> => {
    setIsSavingGoogleKey(true)
    setGoogleKeyError(null)
    try {
      const ok = await window.electronAPI.setGoogleMapsKey(keyToSave)
      if (ok) {
        setGoogleKey(keyToSave)
        setIsSavingGoogleKey(false)
        setGoogleKeySuccess(true)
        setTimeout(() => setGoogleKeySuccess(false), 2000)
        return true
      } else {
        setGoogleKeyError('Failed to save key securely to system keychain.')
      }
    } catch (err) {
      setGoogleKeyError('Failed to save key.')
    }
    setIsSavingGoogleKey(false)
    return false
  }

  const clearGoogleKey = async () => {
    const ok = await window.electronAPI.setGoogleMapsKey('')
    if (ok) {
      setGoogleKey('')
    }
  }

  const saveGeeKey = async (keyToSave: string): Promise<boolean> => {
    setIsSavingGeeKey(true)
    setGeeKeyError(null)
    try {
      // 1. Validate structure first if not empty
      if (keyToSave.trim()) {
        try {
          const parsed = JSON.parse(keyToSave)
          if (!parsed || parsed.type !== 'service_account') {
            throw new Error("JSON must have type: 'service_account'")
          }
        } catch (e: any) {
          setGeeKeyError(`Invalid GEE Service Account JSON: ${e.message}`)
          setIsSavingGeeKey(false)
          return false
        }
      }

      // 2. Save locally encrypted in main process
      const ok = await window.electronAPI.setGEEKey(keyToSave)
      if (ok) {
        setGeeKey(keyToSave)
        
        // 3. Sync to Python backend process dynamically
        const workspacePath = mapContext.workspace
        const wsParam = workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''
        const response = await fetch(`http://localhost:8765/api/gee/credentials${wsParam}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ credentials: keyToSave }),
        })
        
        if (response.ok) {
          setIsSavingGeeKey(false)
          setGeeKeySuccess(true)
          setTimeout(() => setGeeKeySuccess(false), 2000)
          return true
        } else {
          const errData = await response.json()
          setGeeKeyError(errData.detail || 'Failed to initialize GEE on the backend with these credentials.')
        }
      } else {
        setGeeKeyError('Failed to save key securely to system keychain.')
      }
    } catch (err: any) {
      setGeeKeyError(err.message || 'Failed to save key.')
    }
    setIsSavingGeeKey(false)
    return false
  }

  const clearGeeKey = async () => {
    setGeeKeyError(null)
    try {
      const ok = await window.electronAPI.setGEEKey('')
      if (ok) {
        setGeeKey('')
        const workspacePath = mapContext.workspace
        const wsParam = workspacePath ? `?workspace=${encodeURIComponent(workspacePath)}` : ''
        await fetch(`http://localhost:8765/api/gee/credentials${wsParam}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ credentials: '' }),
        })
      }
    } catch (err: any) {
      console.error('Failed to clear GEE credentials:', err)
    }
  }

  const importGeeJsonFile = async () => {
    setGeeKeyError(null)
    try {
      const chosen = await window.electronAPI.openFile({
        filters: [{ name: 'JSON credentials', extensions: ['json'] }]
      })
      if (!chosen) return
      
      const fileContent = await window.electronAPI.readFile(chosen)
      if (fileContent) {
        // Validate JSON
        try {
          const parsed = JSON.parse(fileContent)
          if (parsed && parsed.type === 'service_account') {
            const formatted = JSON.stringify(parsed, null, 2)
            setGeeKey(formatted)
            // Force textarea update
            const el = document.getElementById('gee-key-input-element') as HTMLTextAreaElement
            if (el) el.value = formatted
          } else {
            setGeeKeyError("Selected file is not a valid Google Service Account (missing type='service_account')")
          }
        } catch {
          setGeeKeyError('Selected file is not a valid JSON file.')
        }
      }
    } catch (err: any) {
      setGeeKeyError('Failed to import JSON file.')
    }
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  const handleAttachClick = async () => {
    setAttachmentError(null)
    setAttachmentLoading(true)
    try {
      const chosen = await window.electronAPI.openFile({
        filters: [
          { name: 'Images & PDFs', extensions: [...IMAGE_EXTS, 'pdf'] },
          { name: 'Images', extensions: IMAGE_EXTS },
          { name: 'PDF', extensions: ['pdf'] },
        ],
      })
      if (!chosen) {
        setAttachmentLoading(false)
        return
      }

      const name = chosen.split(/[/\\]/).pop() || chosen
      const ext = name.split('.').pop()?.toLowerCase() || ''

      let newAttachment: { base64: string; mimeType: string; fileName: string; filePath: string } | null = null

      if (IMAGE_EXTS.includes(ext)) {
        const base64 = await window.electronAPI.readFileBase64(chosen)
        if (base64) {
          newAttachment = {
            base64,
            mimeType: MIME_MAP[ext] || 'image/png',
            fileName: name,
            filePath: chosen,
          }
        }
      } else if (ext === 'pdf') {
        const out = await rasterizePdfPage(chosen, 1)
        if (out) {
          newAttachment = {
            base64: out.base64,
            mimeType: 'image/png', // OpenAI vision needs an image
            fileName: name,
            filePath: chosen,
          }
        } else {
          setAttachmentError('Could not render the PDF page.')
        }
      } else {
        setAttachmentError('Unsupported file type.')
      }

      if (newAttachment) {
        setAttachments((prev) => [...prev, newAttachment!])
      }
    } catch (e) {
      setAttachmentError(`Failed to attach file: ${(e as Error).message}`)
    } finally {
      setAttachmentLoading(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (activeQuestion) return

    const files = e.dataTransfer.files
    if (!files || files.length === 0) return

    setAttachmentError(null)
    setAttachmentLoading(true)

    try {
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        const path = (file as any).path || ''
        if (!path) continue

        const name = file.name
        const ext = name.split('.').pop()?.toLowerCase() || ''

        let newAttachment: { base64: string; mimeType: string; fileName: string; filePath: string } | null = null

        if (IMAGE_EXTS.includes(ext)) {
          const base64 = await window.electronAPI.readFileBase64(path)
          if (base64) {
            newAttachment = {
              base64,
              mimeType: MIME_MAP[ext] || 'image/png',
              fileName: name,
              filePath: path,
            }
          }
        } else if (ext === 'pdf') {
          const out = await rasterizePdfPage(path, 1)
          if (out) {
            newAttachment = {
              base64: out.base64,
              mimeType: 'image/png',
              fileName: name,
              filePath: path,
            }
          } else {
            setAttachmentError('Could not render the PDF page.')
          }
        }

        if (newAttachment) {
          setAttachments((prev) => [...prev, newAttachment!])
        }
      }
    } catch (e) {
      setAttachmentError(`Failed to process dropped file: ${(e as Error).message}`)
    } finally {
      setAttachmentLoading(false)
    }
  }

  const sendMessageDirect = async (text: string): Promise<void> => {
    if ((!text.trim() && attachments.length === 0) || isStreaming || !activeConversation) return

    const userMessage: ChatMessage = {
      role: 'user',
      content: text.trim() || (attachments.length > 0 ? `[Attached ${attachments[0].fileName}]` : ''),
      timestamp: Date.now(),
      attachments: attachments.map((att) => ({
        fileName: att.fileName,
        filePath: att.filePath || '',
        mimeType: att.mimeType,
      })),
    }
    const updated: ChatMessage[] = [...messages, userMessage]
    const placeholderTs = Date.now() + 1
    onMessagesChange([
      ...updated,
      { role: 'assistant', content: '', timestamp: placeholderTs },
    ])
    setIsStreaming(true)
    setToolStatus(null)
    setChatError(null)

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    try {
      const ws = await connectWebSocket()
      inFlightRef.current = {
        base: updated,
        accum: '',
        timestamp: placeholderTs,
      }

      // First payload on a fresh connection ships the conversation history
      // so the backend can rebuild the OpenAI message list. Subsequent
      // payloads on the same connection carry only the new user message.
      // Document mode now bridges to the live map: send map_context too so
      // the model can fly_to / add markers / run GIS tools while looking at
      // the document. Backend accepts both fields in either mode.
      const payload: Record<string, unknown> = {
        content: userMessage.content,
        map_context: mapContext,
        api_key: apiKey,
        google_maps_api_key: googleKey,
        image: documentImage
          ? {
              base64: documentImage.base64,
              mime_type: documentImage.mimeType,
              file_path: documentImage.filePath,
              file_name: documentImage.fileName,
            }
          : undefined,
        chat_attachments: attachments.map((att) => ({
          base64: att.base64,
          mime_type: att.mimeType,
          file_name: att.fileName,
          file_path: att.filePath || '',
        })),
      }
      if (!historySentRef.current && messages.length > 0) {
        payload.history = messages.map((m) => ({
          role: m.role,
          content: m.content,
        }))
      }
      historySentRef.current = true

      setAttachments([]) // Clear attachments on send
      ws.send(JSON.stringify(payload))
    } catch {
      setChatError({
        code: 'connection',
        message: 'Could not reach the backend. Is the server running on :8765?',
      })
      onMessagesChange(updated)
      setIsStreaming(false)
      inFlightRef.current = null
    }
  }


  const sendMessage = async (): Promise<void> => {
    if ((!input.trim() && attachments.length === 0) || isStreaming) return

    if (!hasOpenAIKey) {
      setShowApiKeyInput(true)
      setChatError({
        code: 'auth',
        message: 'An OpenAI API Key is required. Please configure your key in the settings panel above.',
      })
      return
    }

    if (!activeConversation) {
      pendingInputRef.current = input.trim() || (attachments.length > 0 ? `[Attached ${attachments[0].fileName}]` : '')
      setInput('')
      onCreateConversation()
      return
    }

    const text = input.trim()
    setInput('')
    await sendMessageDirect(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    const el = e.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 150) + 'px'
  }

  const handleSelectOption = (option: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'question_response',
        response: option
      }))
    }
    setActiveQuestion(null)
  }

  const handleToggleOption = (option: string) => {
    setSelectedOptions(prev =>
      prev.includes(option)
        ? prev.filter(o => o !== option)
        : [...prev, option]
    )
  }

  const handleSubmitMultiSelect = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'question_response',
        response: selectedOptions
      }))
    }
    setActiveQuestion(null)
  }

  const handleNewChat = () => {
    wsRef.current?.close()
    wsRef.current = null
    setChatError(null)
    setSuggestions(pickSuggestions(3))
    onCreateConversation()
    setShowHistory(false)
    setActiveQuestion(null)
  }

  const handleModelChange = async (modelId: string) => {
    if (modelId === currentModel || isSwitchingModel) return
    setIsSwitchingModel(true)
    try {
      const result = await window.electronAPI.switchModel(modelId)
      setCurrentModel(modelId)
      // Close the WS so the next message picks up the new model
      wsRef.current?.close()
      wsRef.current = null
      if (result.requiresManualRestart) {
        setToolStatus('Model updated — restart the app to apply')
        setTimeout(() => setToolStatus(null), 4000)
      }
    } finally {
      setIsSwitchingModel(false)
    }
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts)
    const now = new Date()
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000)
    if (diffDays === 0) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return d.toLocaleDateString([], { weekday: 'short' })
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }

  return (
    <div
      ref={headerContainerRef}
      className="chat-panel"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* ── Chat header ── */}
      <div className="chat-header">
        {editingConversationId === activeConversation?.id && !showHistory ? (
          <input
            type="text"
            className="chat-header-rename-input"
            value={editingTitle}
            onChange={(e) => setEditingTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                if (activeConversation) {
                  onRenameConversation?.(activeConversation.id, editingTitle.trim() || 'New chat')
                }
                setEditingConversationId(null)
              } else if (e.key === 'Escape') {
                setEditingConversationId(null)
              }
            }}
            onBlur={() => {
              if (activeConversation) {
                onRenameConversation?.(activeConversation.id, editingTitle.trim() || 'New chat')
              }
              setEditingConversationId(null)
            }}
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span
            className="chat-header-title"
            onDoubleClick={() => {
              if (activeConversation) {
                setEditingConversationId(activeConversation.id)
                setEditingTitle(activeConversation.title)
              }
            }}
            title="Double-click to rename chat"
          >
            {activeConversation?.title || 'Urban Planning Assistant'}
          </span>
        )}
        <div className="chat-header-actions">
          <button
            ref={historyBtnRef}
            className={`chat-header-action-btn ${showHistory ? 'active' : ''}`}
            onClick={() => {
              setShowHistory(!showHistory);
              setShowApiKeyInput(false);
            }}
            title="View chat history"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          </button>
          
          <button
            className="chat-header-action-btn"
            onClick={handleNewChat}
            title="Start a new chat"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── API Key Configuration Bar ── */}
      {isKeyLoaded && (
        <div className="api-key-config-bar">
          <div className="api-key-status-row">
            <div className="api-key-status-header">
              <div className="api-key-status-indicators">
                {hasOpenAIKey ? (
                  <div className="api-key-status success">
                    <span className="api-key-indicator green">●</span>
                    <span className="api-key-label">
                      OpenAI API Key active{!apiKey.trim() && hasEnvApiKey ? ' (env)' : ''}
                    </span>
                  </div>
                ) : (
                  <div className="api-key-status warning">
                    <span className="api-key-indicator yellow">●</span>
                    <span className="api-key-label">OpenAI API Key required</span>
                  </div>
                )}

                {hasGoogleMapsKey ? (
                  <div className="api-key-status success">
                    <span className="api-key-indicator green">●</span>
                    <span className="api-key-label">
                      Google Maps Key active{!googleKey.trim() && hasEnvGoogleKey ? ' (env)' : ''}
                    </span>
                  </div>
                ) : (
                  <div className="api-key-status info">
                    <span className="api-key-indicator gray">●</span>
                    <span className="api-key-label">Google Maps Key inactive (OSM fallback)</span>
                  </div>
                )}

                {geeKey ? (
                  <div className="api-key-status success">
                    <span className="api-key-indicator green">●</span>
                    <span className="api-key-label">GEE Credentials active</span>
                  </div>
                ) : (
                  <div className="api-key-status info">
                    <span className="api-key-indicator gray">●</span>
                    <span className="api-key-label">GEE Credentials inactive</span>
                  </div>
                )}
              </div>

              {/* API Settings toggle — gear outline with API text inside */}
              <button
                className={`api-settings-btn ${showApiKeyInput ? 'active' : ''}`}
                onClick={() => {
                  setShowApiKeyInput(!showApiKeyInput);
                  setShowHistory(false);
                }}
                title="API Key Settings"
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" strokeLinecap="round" strokeLinejoin="round">
                  {/* Gear outline (outer boundary only, inner circle removed) */}
                  <path
                    d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"
                    stroke="currentColor"
                    strokeWidth="2"
                  />
                  {/* API text inside gear (larger font and re-centered) */}
                  <text
                    x="12.2"
                    y="14.2"
                    textAnchor="middle"
                    fontSize="6.2"
                    fontWeight="800"
                    fontFamily="Inter, system-ui, sans-serif"
                    fill="currentColor"
                    stroke="none"
                    letterSpacing="0.1"
                  >API</text>
                </svg>
              </button>
            </div>
          </div>

          {showApiKeyInput && (
            <div className="settings-drawer-container">
              {/* OpenAI Key Section */}
              <div className="setting-field-group">
                <label htmlFor="api-key-input-element" className="setting-field-label">OpenAI API Key (Required)</label>
                <div className="api-key-input-wrapper">
                  <input
                    key={apiKey}
                    type="password"
                    className="api-key-input-field"
                    defaultValue={apiKey}
                    id="api-key-input-element"
                    placeholder="sk-proj-..."
                    disabled={isSavingKey}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const el = document.getElementById('api-key-input-element') as HTMLInputElement
                        if (el) validateAndSaveKey(el.value)
                      }
                    }}
                  />
                  <button
                    className={`api-key-save-btn ${keySuccess ? 'success' : ''}`}
                    onClick={() => {
                      const el = document.getElementById('api-key-input-element') as HTMLInputElement
                      if (el) validateAndSaveKey(el.value)
                    }}
                    disabled={isSavingKey}
                  >
                    {isSavingKey ? 'Saving...' : keySuccess ? 'Saved! ✓' : 'Save'}
                  </button>
                  {apiKey && (
                    <button
                      className="api-key-clear-btn"
                      onClick={clearApiKey}
                      disabled={isSavingKey}
                    >
                      Clear
                    </button>
                  )}
                </div>
                {keyError && (
                  <div className="api-key-error-msg">
                    <span className="api-key-error-icon">⚠</span>
                    <span>{keyError}</span>
                  </div>
                )}
              </div>

              {/* Google Maps Key Section */}
              <div className="setting-field-group">
                <label htmlFor="google-key-input-element" className="setting-field-label">Google Maps API Key (Optional)</label>
                <div className="api-key-input-wrapper">
                  <input
                    key={googleKey}
                    type="password"
                    className="api-key-input-field"
                    defaultValue={googleKey}
                    id="google-key-input-element"
                    placeholder="AIzaSy..."
                    disabled={isSavingGoogleKey}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const el = document.getElementById('google-key-input-element') as HTMLInputElement
                        if (el) saveGoogleKey(el.value)
                      }
                    }}
                  />
                  <button
                    className={`api-key-save-btn ${googleKeySuccess ? 'success' : ''}`}
                    onClick={() => {
                      const el = document.getElementById('google-key-input-element') as HTMLInputElement
                      if (el) saveGoogleKey(el.value)
                    }}
                    disabled={isSavingGoogleKey}
                  >
                    {isSavingGoogleKey ? 'Saving...' : googleKeySuccess ? 'Saved! ✓' : 'Save'}
                  </button>
                  {googleKey && (
                    <button
                      className="api-key-clear-btn"
                      onClick={clearGoogleKey}
                      disabled={isSavingGoogleKey}
                    >
                      Clear
                    </button>
                  )}
                </div>
                {googleKeyError && (
                  <div className="api-key-error-msg">
                    <span className="api-key-error-icon">⚠</span>
                    <span>{googleKeyError}</span>
                  </div>
                )}
              </div>

              {/* Google Earth Engine Credentials Section */}
              <div className="setting-field-group" style={{ marginTop: '12px', borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <label htmlFor="gee-key-input-element" className="setting-field-label" style={{ margin: 0 }}>
                    Google Earth Engine Service Account Credentials (Optional)
                  </label>
                  <button
                    className="import-json-btn"
                    onClick={importGeeJsonFile}
                    style={{
                      background: 'var(--accent, #3b82f6)',
                      color: '#ffffff',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '3px 8px',
                      fontSize: '11px',
                      cursor: 'pointer',
                      fontWeight: 600,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                    Import JSON File
                  </button>
                </div>
                <div className="gee-key-input-container" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <textarea
                    key={geeKey}
                    id="gee-key-input-element"
                    className="api-key-input-field"
                    defaultValue={geeKey}
                    placeholder='{ "type": "service_account", ... }'
                    disabled={isSavingGeeKey}
                    style={{
                      width: '100%',
                      height: '80px',
                      fontFamily: 'monospace',
                      fontSize: '11px',
                      resize: 'vertical',
                      backgroundColor: 'var(--bg-card, #1d1e2c)',
                      border: '1px solid var(--border, #3a3f58)',
                      borderRadius: '4px',
                      padding: '8px',
                      color: 'var(--text-primary, #ffffff)'
                    }}
                  />
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      className={`api-key-save-btn ${geeKeySuccess ? 'success' : ''}`}
                      onClick={() => {
                        const el = document.getElementById('gee-key-input-element') as HTMLTextAreaElement
                        if (el) saveGeeKey(el.value)
                      }}
                      disabled={isSavingGeeKey}
                      style={{ flex: 1 }}
                    >
                      {isSavingGeeKey ? 'Verifying & Saving...' : geeKeySuccess ? 'Saved! ✓' : 'Save GEE Credentials'}
                    </button>
                    {geeKey && (
                      <button
                        className="api-key-clear-btn"
                        onClick={clearGeeKey}
                        disabled={isSavingGeeKey}
                      >
                        Clear
                      </button>
                    )}
                  </div>
                </div>
                {geeKeyError && (
                  <div className="api-key-error-msg" style={{ marginTop: '6px' }}>
                    <span className="api-key-error-icon">⚠</span>
                    <span>{geeKeyError}</span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Conversation history dropdown ── */}
      {showHistory && (
        <div ref={historyListRef} className="chat-history-list">
          {conversations.length === 0 ? (
            <div className="chat-history-empty">No conversations yet</div>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`chat-history-item ${conv.id === activeConversation?.id ? 'active' : ''}`}
                onClick={() => {
                  if (editingConversationId === conv.id) return
                  if (clickTimerRef.current) clearTimeout(clickTimerRef.current)
                  clickTimerRef.current = setTimeout(() => {
                    onSelectConversation(conv.id)
                    setShowHistory(false)
                    wsRef.current?.close()
                    wsRef.current = null
                  }, 220)
                }}
                onDoubleClick={(e) => {
                  e.stopPropagation()
                  if (clickTimerRef.current) {
                    clearTimeout(clickTimerRef.current)
                    clickTimerRef.current = null
                  }
                  setEditingConversationId(conv.id)
                  setEditingTitle(conv.title)
                }}
                title="Double-click to rename"
              >
                <div className="chat-history-item-content">
                  {editingConversationId === conv.id ? (
                    <input
                      type="text"
                      className="chat-history-rename-input"
                      value={editingTitle}
                      onChange={(e) => setEditingTitle(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          onRenameConversation?.(conv.id, editingTitle.trim() || 'New chat')
                          setEditingConversationId(null)
                        } else if (e.key === 'Escape') {
                          setEditingConversationId(null)
                        }
                      }}
                      onBlur={() => {
                        onRenameConversation?.(conv.id, editingTitle.trim() || 'New chat')
                        setEditingConversationId(null)
                      }}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                      onDoubleClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <span className="chat-history-item-title">{conv.title}</span>
                  )}
                  <span className="chat-history-item-meta">
                    {conv.messages.length} msg{conv.messages.length !== 1 ? 's' : ''} &middot;{' '}
                    {formatTime(conv.createdAt)}
                  </span>
                </div>
                <button
                  className="chat-history-delete"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (clickTimerRef.current) {
                      clearTimeout(clickTimerRef.current)
                      clickTimerRef.current = null
                    }
                    onDeleteConversation(conv.id)
                  }}
                  title="Delete conversation"
                >
                  &times;
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {/* ── Error banner ── */}
      {chatError && (
        <div className={`chat-error chat-error-${chatError.code}`} role="alert">
          <div className="chat-error-content-wrapper">
            <span className="chat-error-code">{chatError.code}</span>
            <span className="chat-error-msg">{chatError.message}</span>
            {(chatError.code === 'auth' || chatError.code === 'rate_limit') && (
              <div className="chat-error-inline-form">
                <input
                  type="password"
                  className="chat-error-inline-input"
                  id="chat-error-inline-input-element"
                  placeholder="Enter new API key (sk-proj-...)"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      const el = document.getElementById('chat-error-inline-input-element') as HTMLInputElement
                      if (el) validateAndSaveKey(el.value)
                    }
                  }}
                />
                <button
                  className="chat-error-inline-save-btn"
                  onClick={() => {
                    const el = document.getElementById('chat-error-inline-input-element') as HTMLInputElement
                    if (el) validateAndSaveKey(el.value)
                  }}
                >
                  Save
                </button>
              </div>
            )}
          </div>
          <button
            className="chat-error-dismiss"
            onClick={() => setChatError(null)}
            aria-label="Dismiss"
          >
            &times;
          </button>
        </div>
      )}

      {/* ── Messages area ── */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-logo">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
                <path
                  d="M5 3L19 12L12.5 13.5L9 20L5 3Z"
                  fill="#4ecca3"
                  stroke="#1a9e7e"
                  strokeWidth="1.5"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <p className="chat-empty-title">Urban Planning Assistant</p>
            <p className="chat-empty-hint">
              Ask about zoning, land use, transportation, or spatial analysis. I can see your map
              layers and help with planning decisions.
            </p>
            <div className="chat-empty-suggestions">
              {suggestions.map((s) => (
                <span key={s} className="suggestion" onClick={() => setInput(s)}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => {
          // Don't render placeholder/empty assistant turns unless they contain inline research metadata
          if (msg.role === 'assistant' && !msg.content.trim() && !msg.research) return null
          return (
            <div key={i} className={`chat-msg ${msg.role}`}>
              <div className="chat-msg-role">{msg.role === 'user' ? 'You' : 'Assistant'}</div>
              <div className="chat-msg-body">
                {msg.research ? (
                  <ResearchBubble
                    phase={msg.research.phase}
                    steps={msg.research.steps}
                    reasoning={msg.research.reasoning}
                    markdown={msg.research.markdown}
                    citations={msg.research.citations}
                    expanded={researchExpanded}
                    onToggleExpand={() => setResearchExpanded((v) => !v)}
                    onDownloadMd={() => downloadResearchMd(msg.research?.markdown || '')}
                    onDownloadPdf={() => downloadResearchPdf(msg.research?.markdown || '')}
                  />
                ) : msg.role === 'assistant' ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeHighlight]}
                    components={{
                      pre: CodePre,
                      ...headingComponents
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                ) : (
                  <p>{msg.content}</p>
                )}
                {msg.attachments && msg.attachments.length > 0 && (
                  <div className="chat-msg-attachments">
                    {msg.attachments.map((att, idx) => (
                      <div key={idx} className="chat-msg-attachment-item" title={att.filePath}>
                        <span className="attachment-icon">
                          {att.mimeType?.startsWith('image/') ? '🖼️' : '📄'}
                        </span>
                        <span className="attachment-name">{att.fileName}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {activeQuestion && (
          <div className="chat-question-lockbox">
            <div className="chat-question-header">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: '4px' }}>
                <circle cx="12" cy="12" r="10" />
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              Clarifying Question
            </div>
            <p className="chat-question-text">{activeQuestion.question}</p>
            
            {activeQuestion.is_multi_select ? (
              <div className="chat-question-checkboxes">
                {activeQuestion.options.map((opt, idx) => (
                  <label key={idx} className="chat-question-checkbox-label">
                    <input
                      type="checkbox"
                      className="chat-question-checkbox"
                      checked={selectedOptions.includes(opt)}
                      onChange={() => handleToggleOption(opt)}
                    />
                    {opt}
                  </label>
                ))}
                <button
                  className="chat-question-submit-btn"
                  onClick={handleSubmitMultiSelect}
                  disabled={selectedOptions.length === 0}
                >
                  Submit Answer
                </button>
              </div>
            ) : (
              <div className="chat-question-buttons">
                {activeQuestion.options.map((opt, idx) => (
                  <button
                    key={idx}
                    className="chat-question-opt-btn"
                    onClick={() => handleSelectOption(opt)}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {/* Tool status + streaming dots are hidden while a research run is active on the screen */}
        {toolStatus && messages[messages.length - 1]?.research?.phase !== 'running' && (
          <div className="chat-tool-status">
            <span className="tool-dot" />
            {toolStatus}
          </div>
        )}
        {isStreaming && !toolStatus && messages[messages.length - 1]?.research?.phase !== 'running' && (
          <div className="chat-streaming">
            <span className="streaming-dot" />
            <span className="streaming-dot" />
            <span className="streaming-dot" />
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Input area ── */}
      <div className="chat-input-area">
        {attachmentError && (
          <div className="chat-attachment-error">
            <span className="error-icon">⚠</span>
            <span className="error-text">{attachmentError}</span>
            <button
              type="button"
              className="chat-attachment-error-close"
              onClick={() => setAttachmentError(null)}
            >
              &times;
            </button>
          </div>
        )}

        {attachmentLoading && (
          <div className="chat-attachment-loading">
            <span className="spinning-icon">⟳</span>
            <span>Processing attachment...</span>
          </div>
        )}

        {attachments.length > 0 && (
          <div className="chat-attachments-container">
            {attachments.map((att, idx) => (
              <div key={idx} className="chat-attachment-chip" title={att.filePath}>
                {att.mimeType.startsWith('image/') ? (
                  <img
                    src={`data:${att.mimeType};base64,${att.base64}`}
                    className="chat-attachment-thumbnail"
                    alt={att.fileName}
                  />
                ) : (
                  <span className="chat-attachment-icon">📄</span>
                )}
                <span className="chat-attachment-name">{att.fileName}</span>
                <button
                  type="button"
                  className="chat-attachment-remove"
                  onClick={() => removeAttachment(idx)}
                  title="Remove attachment"
                >
                  &times;
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="chat-input-row">
          <button
            type="button"
            className="chat-attach-btn"
            onClick={handleAttachClick}
            disabled={!hasOpenAIKey || !!activeQuestion}
            title="Attach image or PDF"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            className="chat-input"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={
              !hasOpenAIKey
                ? 'Please configure your OpenAI API Key above to start...'
                : activeQuestion
                ? 'Please answer the clarifying question to continue...'
                : activeConversation
                ? 'Ask anything about your project...'
                : 'Start a new conversation...'
            }
            disabled={!hasOpenAIKey || !!activeQuestion}
            rows={1}
          />
          {isStreaming ? (
            <button
              className="chat-stop-btn"
              onClick={handleStopStreaming}
              title="Stop generating"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <rect x="4" y="4" width="8" height="8" rx="1" fill="currentColor" />
              </svg>
            </button>
          ) : (
            <button
              className="chat-send-btn"
              onClick={sendMessage}
              disabled={(!input.trim() && attachments.length === 0) || !!activeQuestion}
              title="Send (Enter)"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M2.5 8H13.5M13.5 8L8.5 3M13.5 8L8.5 13"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          )}
        </div>
        <div className="chat-input-footer">
          {availableModels.length > 0 && (
            <select
              className="model-selector"
              value={currentModel}
              onChange={(e) => handleModelChange(e.target.value)}
              disabled={isSwitchingModel || isStreaming}
              title="Switch model"
            >
              {availableModels.map((m) => (
                <option key={m.id} value={m.id} disabled={m.locked}>
                  {m.locked ? '🔒 ' : ''}{m.name}
                </option>
              ))}
            </select>
          )}

          {isSwitchingModel ? (
            <span className="chat-hint-text">Switching model...</span>
          ) : (
            <span className="chat-hint-text">Enter to send, Shift+Enter for newline</span>
          )}
        </div>
      </div>
    </div>
  )
})

export default ChatPanel
