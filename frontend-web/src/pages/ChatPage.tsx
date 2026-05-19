import { Browser } from '@capacitor/browser'
import { Capacitor } from '@capacitor/core'
import { BookOpen, Code, Download, Image as ImageIcon, Key, Menu, Moon, Search, Sun, Wand2, X, Wifi, WifiOff, RefreshCw, Server, Globe } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, ChatResponse, getBackendURL } from '../api/client'
import { ChatInput } from '../components/ChatInput'
import { ChatMessage } from '../components/ChatMessage'
import { Sidebar } from '../components/Sidebar'
import { useChat } from '../context/ChatContext'
import '../styles/App.css'
import { Message } from '../types/index'

function isImageGenQuery(query: string): { isImage: boolean; style?: string } {
  const q = query.toLowerCase().trim()
  if (!q || q.length < 5) return { isImage: false }
  const triggerPattern = /^(create|generate|make|draw|design|paint|sketch|render|produce|imagine|craft|build|compose)\b/
  const mediaKeywords = /\b(image|picture|art|illustration|drawing|photo|poster|banner|logo|design|wallpaper|background|meme|cartoon|painting|sketch|portrait|flyer|graphic|visual|cover|thumbnail|infographic|icon|artwork|sticker|tattoo|mural|collage|character|scene|landscape|screenshot|diagram|chart|graph|map|animation|logo|sunset|sunrise|mountain|ocean|beach|forest|city|house|building|animal|cat|dog|bird|flower|tree|nature|fantasy|scifi|abstract|pattern|texture|concept|space|galaxy|cyberpunk|vaporwave|anime|realistic|cartoonish|watercolor|oil|digital|3d|render)\b/
  const simpleImagePattern = /^(a |an |the )?(picture|photo|image|drawing|illustration|painting|artwork|sketch|portrait|landscape|poster|logo|meme|cartoon|wallpaper)\s+(of|with|showing|featuring|in)\b/
  if ((triggerPattern.test(q) && mediaKeywords.test(q)) || simpleImagePattern.test(q)) {
    const styleMatch = q.match(/\b(in|as|with|using)\s+(\w+\s*\w*)\s*(style|theme|aesthetic)?\b/i)
    return { isImage: true, style: styleMatch ? styleMatch[2].trim() : undefined }
  }
  return { isImage: false }
}

function isQRCodeQuery(query: string): { isQRCode: boolean; data?: string } {
  const q = query.toLowerCase().trim()
  if (!q) return { isQRCode: false }
  const hasQRKeyword = /qr\s*code|qrcode|quick\s*response\s*code/i.test(q)
  if (!hasQRKeyword) return { isQRCode: false }
  let data = ''
  const urlMatch = q.match(/(?:for|with\s*data|containing|that\s+says?|for\s+this\s+url|encode|:\s*)\s*(https?:\/\/[^\s,;]+)/i)
  if (urlMatch) data = urlMatch[1].trim()
  else {
    const textMatch = q.match(/(?:for|with\s*data|containing|that\s+says?|:\s*)\s*(.+)$/i)
    if (textMatch) data = textMatch[1].trim().replace(/\.$/, '')
  }
  if (!data) data = 'https://apexai.app'
  return { isQRCode: true, data }
}

function isValidImageData(data: string): boolean {
  if (!data) return false
  if (data.startsWith('data:image/')) {
    const comma = data.indexOf(',')
    return comma !== -1 && data.length > 200
  }
  return data.startsWith('http://') || data.startsWith('https://')
}

type Suggestion = { query: string; title: string; desc: string; icon: string }

function ChatPage() {
  const { currentMessages, addMessage, createConversation, setIsLoading, setError, uiState, currentConversationId, toggleTheme, conversations } = useChat()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const currentMessagesRef = useRef(currentMessages)
  currentMessagesRef.current = currentMessages
  const currentConvIdRef = useRef(currentConversationId)
  currentConvIdRef.current = currentConversationId
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [configured, setConfigured] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 768)
  const sidebarRef = useRef<HTMLDivElement>(null)
  const [redesignFromMessage, setRedesignFromMessage] = useState<{ imageUrl: string; prompt: string } | null>(null)
  const [redesignPromptText, setRedesignPromptText] = useState('')
  const [maximizedImage, setMaximizedImage] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const ENV_API_URL = (import.meta.env.VITE_API_URL as string) || ''
  const [backendUrlInput, setBackendUrlInput] = useState(getBackendURL() || ENV_API_URL || 'http://192.168.1.40:8000')
  const [connectionStatus, setConnectionStatus] = useState<'checking' | 'connected' | 'disconnected'>('checking')
  const [connectionTesting, setConnectionTesting] = useState(false)
  const [cloudApiKey, setCloudApiKey] = useState('')
  const [cloudProvider, setCloudProvider] = useState('openai')
  const [cloudApiUrl, setCloudApiUrl] = useState('')
  const [cloudModel, setCloudModel] = useState('')
  const [cloudConfigSaving, setCloudConfigSaving] = useState(false)
  const [cloudConfigStatus, setCloudConfigStatus] = useState('')

  useEffect(() => {
    let cancelled = false
      ; (async function loadConfig() {
        for (let i = 0; i < 3; i++) {
          try {
            const cfg = await apiClient.getConfig()
            if (cancelled) return
            if (cfg?.suggestions) setSuggestions(cfg.suggestions.filter((s: Suggestion) => s.query))
            if (cfg?.configured !== undefined) setConfigured(cfg.configured)
            return
          } catch {
            if (i < 2) await new Promise(r => setTimeout(r, 1000))
          }
        }
      })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const check = async () => {
      setConnectionStatus('checking')
      const url = getBackendURL()
      if (url) {
        const ok = await apiClient.testConnection(url)
        setConnectionStatus(ok ? 'connected' : 'disconnected')
      } else {
        try {
          await apiClient.healthCheck()
          setConnectionStatus('connected')
        } catch {
          setConnectionStatus('disconnected')
        }
      }
    }
    check()
    const interval = setInterval(check, 15000)
    return () => clearInterval(interval)
  }, [])

  const handleTestConnection = async () => {
    setConnectionTesting(true)
    setConnectionStatus('checking')
    const ok = await apiClient.testConnection(backendUrlInput)
    if (ok) {
      apiClient.updateBaseURL(backendUrlInput)
      setConnectionStatus('connected')
    } else {
      setConnectionStatus('disconnected')
    }
    setConnectionTesting(false)
  }

  const handleSaveUrl = () => {
    const url = backendUrlInput.replace(/\/+$/, '')
    setBackendUrlInput(url)
    apiClient.updateBaseURL(url)
    handleTestConnection()
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', uiState.theme)
  }, [uiState.theme])

  useEffect(() => {
    if (sidebarRef.current) {
      sidebarRef.current.classList.toggle('open', sidebarOpen)
    }
  }, [sidebarOpen])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [currentMessages, uiState.isLoading])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSidebarOpen(prev => !prev)
      }
      if (e.key === 'Escape') {
        if (sidebarOpen) setSidebarOpen(false)
        if (redesignFromMessage) { setRedesignFromMessage(null); setRedesignPromptText('') }
        if (maximizedImage) setMaximizedImage(null)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [sidebarOpen, redesignFromMessage, maximizedImage])

  const handleSendMessage = useCallback(async (query: string, attachment?: { file: File; dataUrl?: string }) => {
    if (currentConvIdRef.current === 'default' || !conversations[currentConvIdRef.current]) {
      const newId = await createConversation()
      currentConvIdRef.current = newId
    }

    const currentConvId = currentConvIdRef.current

    if (attachment?.file && attachment?.dataUrl) {
      addMessage({
        id: `attach_${Date.now()}_user`,
        role: 'user',
        content: `[Attached image: ${attachment.file.name}]`,
        type: 'image',
        image: attachment.dataUrl,
        timestamp: Date.now(),
      }, currentConvId)
    }

    addMessage({
      id: `msg_${Date.now()}_user`,
      role: 'user',
      content: query,
      type: 'text',
      timestamp: Date.now(),
    }, currentConvId)

    setIsLoading(true)
    setError(null)

    const fullHistory = currentMessagesRef.current.map(msg => ({
      role: msg.role,
      content: msg.content,
    }))
    const sessionId = currentConvId || 'default'

    try {
      const genQuery = query.replace(/^Regenerate:\s*/i, '')

      // QR Code
      const qrQuery = isQRCodeQuery(genQuery)
      if (qrQuery.isQRCode && qrQuery.data) {
        try {
          const qrRes = await apiClient.generateQRCode({ data: qrQuery.data })
          const imageBase64 = qrRes.image_base64 || ''
          const imageUrl = qrRes.image_url || ''
          const displaySrc = imageBase64 || imageUrl
          if (displaySrc) {
            addMessage({
              id: `msg_${Date.now()}_assistant`,
              role: 'assistant',
              content: `QR Code generated for: ${qrQuery.data}`,
              type: 'qr_code',
              label: 'QR Code Generated',
              image: displaySrc,
              mediaUrl: imageUrl || undefined,
              timestamp: Date.now(),
            }, currentConvId)
            setIsLoading(false)
            return
          }
          throw new Error('No QR code data returned')
        } catch (err) {
          addMessage({
            id: `msg_${Date.now()}_assistant`,
            role: 'assistant',
            content: `I couldn't generate that QR code. ${err instanceof Error ? err.message : 'Service unavailable.'}`,
            type: 'text',
            timestamp: Date.now(),
          }, currentConvId)
          setIsLoading(false)
          return
        }
      }

      // Image generation
      const imgQuery = isImageGenQuery(genQuery)
      if (imgQuery.isImage) {
        try {
          const imgRes = await apiClient.generateImage({ prompt: genQuery, style: imgQuery.style })
          const imageUrl = imgRes.image_url || ''
          const imageBase64 = imgRes.image_base64
            ? (imgRes.image_base64.startsWith('data:')
              ? imgRes.image_base64
              : `data:image/png;base64,${imgRes.image_base64}`)
            : ''
          const displaySrc = imageBase64 || imageUrl
          if (displaySrc && isValidImageData(displaySrc)) {
            addMessage({
              id: `msg_${Date.now()}_assistant`,
              role: 'assistant',
              content: imgRes.prompt || query,
              type: 'image_generated',
              label: 'Image Generated',
              image: displaySrc,
              mediaUrl: imageUrl || undefined,
              timestamp: Date.now(),
            }, currentConvId)
            setIsLoading(false)
            return
          }
          throw new Error('No valid image data')
        } catch (err) {
          addMessage({
            id: `msg_${Date.now()}_assistant`,
            role: 'assistant',
            content: `I couldn't generate that image. ${err instanceof Error ? err.message : 'Service unavailable.'} Try a different prompt.`,
            type: 'text',
            timestamp: Date.now(),
          }, currentConvId)
          setIsLoading(false)
          return
        }
      }

      // Image attachment analysis
      if (attachment?.file && attachment?.dataUrl) {
        const response = await apiClient.analyzeImage(attachment.file, sessionId === 'default' ? undefined : sessionId, fullHistory)
        const msg: Message = {
          id: `msg_${Date.now()}_assistant`,
          role: 'assistant',
          content: response.content || '',
          type: response.type || 'chat',
          sources: response.sources || [],
          analysis: response.analysis,
          timestamp: Date.now(),
        }
        if (response.image_url) msg.image = response.image_url
        addMessage(msg, currentConvId)
        setIsLoading(false)
        return
      }

      // Chat
      const response: ChatResponse = await apiClient.chat({
        query,
        session_id: sessionId,
        messages: fullHistory,
      })

      const msg: Message = {
        id: `msg_${Date.now()}_assistant`,
        role: 'assistant',
        content: response.content || '',
        type: response.type || 'chat',
        label: response.type ? response.type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) : 'Chat',
        sources: response.sources || [],
        analysis: response.analysis,
        timestamp: Date.now(),
      }

      if (response.type === 'image_generated') {
        const imageUrl = response.image_url || ''
        const imageBase64 = response.image_base64
          ? (response.image_base64.startsWith('data:')
            ? response.image_base64
            : `data:image/png;base64,${response.image_base64}`)
          : ''
        const displaySrc = imageBase64 || imageUrl
        if (displaySrc) { msg.image = displaySrc; msg.mediaUrl = imageUrl || undefined }
      }

      if (response.video_url) msg.videoUrl = response.video_url
      if (response.audio_url) msg.audioUrl = response.audio_url

      addMessage(msg, currentConvId)
    } catch (err: any) {
      const isConnectionError = err?.code === 'ECONNREFUSED' || err?.message?.includes('ECONNREFUSED') || err?.message?.includes('Network Error') || !err?.response
      const backendMsg = err?.response?.data?.detail
      if (isConnectionError) {
        addMessage({
          id: `msg_${Date.now()}_assistant`,
          role: 'assistant',
          content: 'Unable to connect to Apex AI server. Please ensure the backend is running on port 8000.',
          type: 'text',
          timestamp: Date.now(),
        }, currentConvId)
        setError(null)
      } else {
        addMessage({
          id: `msg_${Date.now()}_assistant`,
          role: 'assistant',
          content: `I'm sorry, I encountered an error: ${backendMsg || (err instanceof Error ? err.message : 'Failed to get response')}`,
          type: 'text',
          timestamp: Date.now(),
        }, currentConvId)
        setError(null)
      }
    } finally {
      setIsLoading(false)
    }
  }, [addMessage, setIsLoading, setError, createConversation, conversations])

  const handleSendMessageRef = useRef(handleSendMessage)
  handleSendMessageRef.current = handleSendMessage

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.query) {
        if (detail.conversationId) currentConvIdRef.current = detail.conversationId
        handleSendMessageRef.current(detail.query)
      }
    }
    window.addEventListener('apex:send-message', handler)
    return () => window.removeEventListener('apex:send-message', handler)
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.imageUrl) setRedesignFromMessage({ imageUrl: detail.imageUrl, prompt: detail.prompt || '' })
    }
    window.addEventListener('apex:redesign-image', handler)
    return () => window.removeEventListener('apex:redesign-image', handler)
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail?.imageUrl) setMaximizedImage(detail.imageUrl)
    }
    window.addEventListener('apex:maximize-image', handler)
    return () => window.removeEventListener('apex:maximize-image', handler)
  }, [])

  const handleRedesignFromImage = useCallback(async (prompt: string) => {
    if (!redesignFromMessage) return
    try {
      setIsLoading(true)
      let blob: Blob
      try {
        const resp = await fetch(redesignFromMessage.imageUrl)
        blob = await resp.blob()
      } catch {
        const base64Data = redesignFromMessage.imageUrl.includes('base64,')
          ? redesignFromMessage.imageUrl.split('base64,')[1]
          : null
        if (base64Data) {
          const byteChars = atob(base64Data)
          const byteArr = new Uint8Array(byteChars.length)
          for (let i = 0; i < byteChars.length; i++) byteArr[i] = byteChars.charCodeAt(i)
          blob = new Blob([byteArr], { type: 'image/jpeg' })
        } else {
          throw new Error('Could not load the original image.')
        }
      }
      const file = new File([blob], `redesign_${Date.now()}.jpg`, { type: blob.type || 'image/jpeg' })
      addMessage({
        id: `redesign_${Date.now()}_user`,
        role: 'user',
        content: `Redesign this image: ${prompt}`,
        type: 'image',
        image: redesignFromMessage.imageUrl,
        timestamp: Date.now(),
      })
      const response = await apiClient.redesignImage(file, prompt)
      const dataUrl = response.image_base64
        ? (response.image_base64.startsWith('data:')
          ? response.image_base64
          : `data:image/png;base64,${response.image_base64}`)
        : response.image_url || ''
      addMessage({
        id: `redesign_${Date.now()}_assistant`,
        role: 'assistant',
        content: `Redesigned: ${prompt}`,
        type: 'image_redesign',
        label: 'Redesigned',
        image: dataUrl,
        mediaUrl: dataUrl,
        timestamp: Date.now(),
      })
      setRedesignFromMessage(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Redesign failed')
    } finally {
      setIsLoading(false)
    }
  }, [redesignFromMessage, addMessage, setIsLoading, setError])

  const iconMap: Record<string, any> = { book: BookOpen, code: Code, search: Search, image: ImageIcon }

  const openPermissionSettings = useCallback(async (permission: 'camera' | 'microphone') => {
    if (Capacitor.isNativePlatform()) {
      try {
        const androidUrl = `intent://settings#Intent;action=android.settings.APPLICATION_DETAILS_SETTINGS;package=com.apexai.app;end`
        const iosUrl = 'app-settings:'
        await Browser.open({ url: Capacitor.getPlatform() === 'android' ? androidUrl : iosUrl })
      } catch (err) {
        window.alert('Unable to open the device settings. Please open the app settings manually.')
      }
      return
    }

    const browserUrl = permission === 'camera'
      ? 'chrome://settings/content/camera'
      : 'chrome://settings/content/microphone'

    try {
      window.open(browserUrl, '_blank')
    } catch {
      window.alert(`Please open your browser settings and allow ${permission} permissions for Apex AI.`)
    }
  }, [])

  return (
    <div className="app-layout">
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}
      <div ref={sidebarRef} className={`sidebar-wrapper ${sidebarOpen ? 'open' : ''}`}>
        <Sidebar />
      </div>

      <main className="main-content">
        <div className="main-header">
          <button className="theme-toggle-main" onClick={() => { setSidebarOpen(prev => !prev); window.hapticTap?.() }} title="Menu (Ctrl+K)">
            <Menu size={18} />
          </button>
          <div style={{ flex: 1 }} />
          <button className="theme-toggle-main" onClick={() => { setSettingsOpen(true); window.hapticTap?.() }} title="Open settings">
            {connectionStatus === 'connected' ? <Wifi size={16} color="#22c55e" /> : connectionStatus === 'checking' ? <RefreshCw size={16} className="sparkle-icon" /> : <WifiOff size={16} color="#ef4444" />}
          </button>
          <button className="theme-toggle-main" onClick={() => { toggleTheme(); window.hapticTap?.() }} title="Toggle theme">
            {uiState.theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
        </div>

        {currentMessages.length === 0 ? (
          <div className="welcome-section">
            <div className="welcome-content">
              <div className="welcome-logo">
                <img src="/logo.png" alt="Apex AI" width="52" height="52" style={{ borderRadius: 14 }} />
              </div>
              <h1>{configured ? 'How can I help you today?' : 'Welcome to Apex AI'}</h1>
              <p className="welcome-subtitle">{configured ? 'Ask me anything, I\'m here to assist' : 'Configure your API key in backend/.env to get started'}</p>
              {suggestions.length > 0 && (
                <div className="welcome-grid">
                  {suggestions.map((s) => {
                    const Icon = iconMap[s.icon] || Search
                    return (
                      <button key={s.title} type="button" className="welcome-card" onClick={() => handleSendMessage(s.query)}>
                        <span className="welcome-icon"><Icon size={20} /></span>
                        <span className="welcome-title">{s.title}</span>
                        <span className="welcome-desc">{s.desc}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="messages-container">
            {currentMessages.map((msg) => (
              <ChatMessage key={msg.id} message={msg} />
            ))}
            {uiState.isLoading && (
              <div className="loading-indicator">
                <div className="typing-indicator"><span></span><span></span><span></span></div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}

        <div className="main-footer">
          <ChatInput onSubmit={handleSendMessage} isLoading={uiState.isLoading} />
        </div>
      </main>

      {uiState.error && (
        <div className="error-toast">
          <span>{uiState.error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss">x</button>
        </div>
      )}

      {redesignFromMessage && (
        <div className="camera-overlay" onClick={() => { setRedesignFromMessage(null); setRedesignPromptText('') }}>
          <div className="camera-container" onClick={e => e.stopPropagation()}>
            <div className="camera-header">
              <span className="camera-title">Redesign Image</span>
              <button className="camera-close-btn" onClick={() => { setRedesignFromMessage(null); setRedesignPromptText('') }} title="Cancel"><X size={20} /></button>
            </div>
            <div className="camera-preview">
              <img src={redesignFromMessage.imageUrl} alt="Original" className="camera-preview-img" />
            </div>
            <div className="redesign-input-area">
              <textarea
                className="redesign-textarea"
                placeholder="Describe how to redesign this image"
                value={redesignPromptText}
                onChange={e => setRedesignPromptText(e.target.value)}
                rows={3}
              />
            </div>
            <div className="camera-footer">
              <button className="camera-retake-btn" onClick={() => { setRedesignFromMessage(null); setRedesignPromptText('') }}><X size={18} /><span>Cancel</span></button>
              <button className="camera-use-btn" onClick={() => { if (redesignPromptText.trim()) { handleRedesignFromImage(redesignPromptText.trim()); setRedesignPromptText('') } }}><Wand2 size={18} /><span>Redesign</span></button>
            </div>
          </div>
        </div>
      )}

      {maximizedImage && (
        <div className="image-maximize-overlay" onClick={() => setMaximizedImage(null)}>
          <div className="image-maximize-header">
            <a href={maximizedImage} download className="image-maximize-download" onClick={e => e.stopPropagation()} title="Download"><Download size={20} /></a>
            <button className="image-maximize-close" onClick={() => setMaximizedImage(null)} title="Close"><X size={24} /></button>
          </div>
          <img src={maximizedImage} alt="Full size" className="image-maximize-img" onClick={e => e.stopPropagation()} />
        </div>
      )}

      {settingsOpen && (
        <div className="settings-overlay" onClick={() => setSettingsOpen(false)}>
          <div className="settings-panel" onClick={e => e.stopPropagation()}>
            <div className="settings-header">
              <div>
                <h2>Settings</h2>
                <p>Configure backend connection and app permissions for Apex AI.</p>
              </div>
              <button className="settings-close-btn" onClick={() => setSettingsOpen(false)} title="Close settings"><X size={20} /></button>
            </div>

            <div className="settings-section">
              <h3><Globe size={16} /> Cloud LLM (24/7 Mode)</h3>
              <p className="settings-desc">Configure a cloud AI provider so the backend works without Ollama.</p>
              <select className="settings-url-input" style={{ marginBottom: 8 }} value={cloudProvider} onChange={e => setCloudProvider(e.target.value)}>
                <option value="openai">OpenAI (GPT-4o, GPT-4o-mini)</option>
                <option value="groq">Groq (Llama 3, Mixtral - Free)</option>
                <option value="together">Together AI (Mistral, Llama)</option>
                <option value="anthropic">Anthropic (Claude)</option>
              </select>
              <div className="settings-url-row" style={{ marginBottom: 8 }}>
                <input type="password" className="settings-url-input" value={cloudApiKey} onChange={e => setCloudApiKey(e.target.value)} placeholder="API Key (e.g. sk-...)" />
              </div>
              <div className="settings-url-row" style={{ marginBottom: 8 }}>
                <input type="text" className="settings-url-input" value={cloudApiUrl} onChange={e => setCloudApiUrl(e.target.value)} placeholder="Custom API URL (optional)" />
              </div>
              <div className="settings-url-row" style={{ marginBottom: 8 }}>
                <input type="text" className="settings-url-input" value={cloudModel} onChange={e => setCloudModel(e.target.value)} placeholder="Model name (optional, e.g. gpt-4o-mini)" />
              </div>
              <button className="settings-btn" onClick={async () => {
                setCloudConfigSaving(true)
                setCloudConfigStatus('')
                try {
                  await apiClient.updateLLMConfig({ provider: cloudProvider, api_key: cloudApiKey, model: cloudModel, api_url: cloudApiUrl })
                  setCloudConfigStatus('ok')
                  setTimeout(() => setCloudConfigStatus(''), 3000)
                } catch {
                  setCloudConfigStatus('err')
                  setTimeout(() => setCloudConfigStatus(''), 3000)
                }
                setCloudConfigSaving(false)
              }} disabled={cloudConfigSaving || !cloudApiKey.trim()}>
                {cloudConfigSaving ? <RefreshCw size={16} className="sparkle-icon" /> : <Key size={16} />}
                <span>Save Cloud Config</span>
              </button>
              {cloudConfigStatus === 'ok' && <span className="status-badge status-ok" style={{ marginTop: 8, display: 'inline-flex' }}><Wifi size={14} /> Cloud LLM configured</span>}
              {cloudConfigStatus === 'err' && <span className="status-badge status-err" style={{ marginTop: 8, display: 'inline-flex' }}><WifiOff size={14} /> Failed to configure</span>}
              <p className="settings-note">Groq offers a free tier (llama-3.1-8b-instant). OpenAI requires a paid API key. Once configured, the backend uses this provider instead of local Ollama.</p>
            </div>

            <div className="settings-section">
              <h3><Server size={16} /> Backend Server</h3>
              <div className="settings-url-row">
                <input
                  type="text"
                  className="settings-url-input"
                  value={backendUrlInput}
                  onChange={e => setBackendUrlInput(e.target.value)}
                  placeholder="http://192.168.1.40:8000"
                  onKeyDown={e => e.key === 'Enter' && handleSaveUrl()}
                />
                <button className="settings-btn settings-btn-sm" onClick={handleSaveUrl} disabled={connectionTesting || !backendUrlInput.trim()}>
                  {connectionTesting ? <RefreshCw size={16} className="sparkle-icon" /> : <RefreshCw size={16} />}
                  <span>Save & Test</span>
                </button>
              </div>
              <div className="settings-status">
                {connectionStatus === 'connected' && <span className="status-badge status-ok"><Wifi size={14} /> Connected</span>}
                {connectionStatus === 'disconnected' && <span className="status-badge status-err"><WifiOff size={14} /> Disconnected</span>}
                {connectionStatus === 'checking' && <span className="status-badge status-check"><RefreshCw size={14} className="sparkle-icon" /> Checking...</span>}
              </div>
              <p className="settings-note">Enter the public URL of your deployed backend (e.g., https://apex-ai.up.railway.app) or local IP for development. With Cloud LLM configured above, the backend can run 24/7 on Railway, Render, or Fly.io.</p>
            </div>

            <div className="settings-section">
              <h3>App Permissions</h3>
              <p className="settings-desc">Open your device settings to allow Camera and Microphone access.</p>
              <div className="settings-actions">
                <button className="settings-btn" onClick={() => openPermissionSettings('camera')}>Camera permissions</button>
                <button className="settings-btn" onClick={() => openPermissionSettings('microphone')}>Microphone permissions</button>
              </div>
              <p className="settings-note">On Android, this opens the app permission screen. On browser/web, it opens the browser permission settings where supported.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ChatPage
