import React, { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { SelectedFeatureEntry } from '../types'
import './FloatingPromptBar.css'

interface FloatingPromptBarProps {
  onSendMessage: (text: string) => void
  isStreaming?: boolean
  streamingStatus?: string
  lastAssistantMessage?: string | null
  lastAssistantTimestamp?: number | null
  lastUserMessage?: string | null
  selectedFeatures?: SelectedFeatureEntry[]
  onClearSelectedFeatures?: () => void
  isChatDrawerOpen?: boolean
  onToggleChatDrawer?: () => void
  activeActionText?: string | null
  onCancelActiveAction?: () => void
  errorMessage?: string | null
  onDismissError?: () => void
}

export const FloatingPromptBar: React.FC<FloatingPromptBarProps> = ({
  onSendMessage,
  isStreaming = false,
  streamingStatus,
  lastAssistantMessage,
  lastAssistantTimestamp,
  lastUserMessage,
  selectedFeatures = [],
  onClearSelectedFeatures,
  isChatDrawerOpen = false,
  onToggleChatDrawer,
  activeActionText,
  onCancelActiveAction,
  errorMessage,
  onDismissError,
}) => {
  const [input, setInput] = useState('')
  const [bubbleExpanded, setBubbleExpanded] = useState(false)
  const [bubbleVisible, setBubbleVisible] = useState(true)
  const [bubbleFading, setBubbleFading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const isHoveredRef = useRef(false)
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearTimers = () => {
    if (fadeTimerRef.current) {
      clearTimeout(fadeTimerRef.current)
      fadeTimerRef.current = null
    }
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }

  // 10-second timer to slowly fade the assistant response
  const startFadeCountdown = () => {
    clearTimers()
    setBubbleFading(false)
    setBubbleVisible(true)

    // After 10s, initiate the slow fade
    fadeTimerRef.current = setTimeout(() => {
      if (isHoveredRef.current) return
      setBubbleFading(true)
      // Allow 1.2s smooth CSS transition to finish before unmounting from DOM
      hideTimerRef.current = setTimeout(() => {
        setBubbleVisible(false)
        setBubbleFading(false)
      }, 1200)
    }, 10000)
  }

  useEffect(() => {
    // Keep visible while streaming or performing an action or showing an error
    if (isStreaming || Boolean(activeActionText) || Boolean(errorMessage)) {
      clearTimers()
      setBubbleVisible(true)
      setBubbleFading(false)
      return
    }

    if (lastAssistantMessage) {
      startFadeCountdown()
    } else {
      clearTimers()
      setBubbleVisible(false)
      setBubbleFading(false)
    }

    return () => clearTimers()
  }, [lastAssistantTimestamp, lastAssistantMessage, isStreaming, activeActionText, errorMessage])

  const handleMouseEnter = () => {
    isHoveredRef.current = true
    clearTimers()
    setBubbleFading(false)
    setBubbleVisible(true)
  }

  const handleMouseLeave = () => {
    isHoveredRef.current = false
    if (!isStreaming && !activeActionText && !errorMessage && lastAssistantMessage) {
      startFadeCountdown()
    }
  }

  const handleBubbleClick = (e: React.MouseEvent) => {
    // Don't open drawer if user was selecting/copying text
    const selection = window.getSelection()?.toString()
    if (selection && selection.length > 0) return

    // Only open the full drawer if the user didn't click an interactive control
    const target = e.target as HTMLElement
    if (target.closest('button') || target.closest('a') || target.closest('input')) {
      return
    }
    onToggleChatDrawer?.()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleSubmit = () => {
    const trimmed = input.trim()
    if (!trimmed || isStreaming) return
    onSendMessage(trimmed)
    setInput('')
  }

  const hasSelectedFeatures = selectedFeatures.length > 0
  const selectedFeatureName = hasSelectedFeatures
    ? selectedFeatures[0]?.feature?.properties?.name ||
      selectedFeatures[0]?.feature?.properties?.title ||
      selectedFeatures[0]?.layerName ||
      'Feature'
    : null

  const showBubble =
    Boolean(errorMessage) ||
    Boolean(activeActionText) ||
    isStreaming ||
    (Boolean(lastAssistantMessage) && !isChatDrawerOpen && bubbleVisible)

  // When full chat drawer is open on the right, hide the bottom prompt bar to eliminate redundancy
  if (isChatDrawerOpen) return null

  return (
    <div className="floating-prompt-container">
      {/* Floating Assistant Bubble Above Prompt */}
      {showBubble && (
        <div
          className={`floating-assistant-bubble ${bubbleExpanded ? 'is-expanded' : ''} ${bubbleFading ? 'is-fading' : ''} ${errorMessage ? 'has-error' : ''}`}
          onClick={handleBubbleClick}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
          title={lastAssistantMessage ? 'Click to open conversation in side chat' : undefined}
        >
          <div className="bubble-header-actions">
            {lastAssistantMessage && !errorMessage && !isStreaming && (
              <button
                className="bubble-action-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  setBubbleExpanded((v) => !v)
                }}
                title={bubbleExpanded ? 'Contract' : 'Expand'}
              >
                {bubbleExpanded ? (
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="4 14 10 14 10 20" />
                    <polyline points="20 10 14 10 14 4" />
                  </svg>
                ) : (
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                )}
              </button>
            )}
            {onToggleChatDrawer && (
              <button
                className="bubble-action-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggleChatDrawer()
                }}
                title="Open full conversation history"
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </button>
            )}
          </div>

          {errorMessage ? (
            <div className="bubble-error-row">
              <span className="bubble-error-text">{errorMessage}</span>
              {onDismissError && (
                <button
                  className="bubble-dismiss-btn"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDismissError()
                  }}
                >
                  Dismiss
                </button>
              )}
            </div>
          ) : activeActionText || isStreaming ? (
            <div className="bubble-action-row">
              <div className="bubble-spinner-indicator">
                <span className="bubble-spinner-dot" />
                <span className="bubble-action-label">
                  {streamingStatus || activeActionText || 'Analyzing map data...'}
                </span>
              </div>
              {onCancelActiveAction && (
                <button
                  className="bubble-cancel-btn"
                  onClick={(e) => {
                    e.stopPropagation()
                    onCancelActiveAction()
                  }}
                >
                  Cancel
                </button>
              )}
            </div>
          ) : lastAssistantMessage ? (
            <div className="bubble-markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{lastAssistantMessage}</ReactMarkdown>
            </div>
          ) : null}
        </div>
      )}

      {/* Floating Prompt Bar */}
      <div className="floating-prompt-bar">
        {hasSelectedFeatures && (
          <div
            className="prompt-feature-chip"
            onClick={onClearSelectedFeatures}
            title="Feature selected for context — click to deselect"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <circle cx="12" cy="12" r="10" />
              <line x1="22" y1="12" x2="18" y2="12" />
              <line x1="6" y1="12" x2="2" y2="12" />
              <line x1="12" y1="6" x2="12" y2="2" />
              <line x1="12" y1="22" x2="12" y2="18" />
            </svg>
            <span className="chip-name">{selectedFeatureName}</span>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="chip-close">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </div>
        )}

        <input
          ref={inputRef}
          type="text"
          className="prompt-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={lastUserMsgPlaceholder(lastUserMessage, hasSelectedFeatures)}
          disabled={isStreaming}
        />

        <button
          className={`prompt-send-btn ${input.trim() ? 'can-send' : ''}`}
          onClick={handleSubmit}
          disabled={!input.trim() || isStreaming}
          title="Send query"
        >
          {isStreaming ? (
            <div className="prompt-send-spinner" />
          ) : (
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          )}
        </button>

        {onToggleChatDrawer && (
          <button
            className={`prompt-drawer-toggle ${isChatDrawerOpen ? 'is-active' : ''}`}
            onClick={onToggleChatDrawer}
            title="Open conversation drawer"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}

function lastUserMsgPlaceholder(lastMsg: string | null | undefined, hasFeature: boolean): string {
  if (hasFeature) return 'Inspect or query selected feature...'
  if (lastMsg) return `Query map or press Enter (e.g. "${lastMsg.slice(0, 32)}...")`
  return 'Type in for Disha to analyze, map, or calculate...'
}
