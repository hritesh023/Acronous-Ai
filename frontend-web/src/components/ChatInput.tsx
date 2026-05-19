import { useRef, useState, useCallback, useEffect } from 'react'
import { Send, Sparkles, StopCircle, Pause, Play, Camera, Image, X, Scan, Languages, Eye, Search, Heart, FileText, ShoppingBag, Plus, Music, Video, Wand2, Mic, RefreshCw } from 'lucide-react'
import { File as FileIcon } from 'lucide-react'
import { useChat } from '../context/ChatContext'
import { apiClient } from '../api/client'
import { Message } from '../types/index'
import '../styles/ChatInput.css'

interface ChatInputProps {
  onSubmit: (message: string, attachment?: { file: File; dataUrl?: string }) => void
  isLoading: boolean
  placeholder?: string
}

const ICON_MAP: Record<string, any> = { eye: Eye, search: Search, scan: Scan, languages: Languages, heart: Heart, 'file-text': FileText, 'shopping-bag': ShoppingBag }
const DEFAULT_ANALYSIS_OPTIONS = [
  { id: 'analyze', label: 'Analyze', icon: 'eye', desc: 'General image analysis' },
]

interface AnalysisOption { id: string; label: string; icon: string; desc: string }

export function ChatInput({ onSubmit, isLoading, placeholder = 'Message Apex AI...' }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const onSubmitRef = useRef<typeof onSubmit>(onSubmit)
  onSubmitRef.current = onSubmit
  const [value, setValue] = useState('')
  const valueRef = useRef(value)
  valueRef.current = value
  const { addMessage, setError, currentConversationId, currentMessages, setIsLoading: setChatLoading } = useChat()
  const [analysisOptions, setAnalysisOptions] = useState<AnalysisOption[]>(DEFAULT_ANALYSIS_OPTIONS)
  const [selectedAnalysis, setSelectedAnalysis] = useState('analyze')

  useEffect(() => {
    apiClient.get('/image/analysis-options').then((r: any) => {
      if (r?.data?.options) setAnalysisOptions(r.data.options)
    }).catch(() => {})
  }, [])

  // Voice recording state
  const [isRecording, setIsRecording] = useState(false)
  const [recordingTime, setRecordingTime] = useState(0)
  const recognitionRef = useRef<any>(null)
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [isPaused, setIsPaused] = useState(false)
  const accumulatedTextRef = useRef('')
  const isPausedRef = useRef(false)

  // Pending attachment preview
  const [pendingPreview, setPendingPreview] = useState<string | null>(null)

  // Attachment menu state
  const [showAttachMenu, setShowAttachMenu] = useState(false)
  const attachRef = useRef<HTMLDivElement>(null)

  // Redesign state
  const [showRedesign, setShowRedesign] = useState(false)
  const [redesignFile, setRedesignFile] = useState<File | null>(null)
  const [redesignPreview, setRedesignPreview] = useState<string | null>(null)
  const [redesignPrompt, setRedesignPrompt] = useState('')
  const [isRedesigning, setIsRedesigning] = useState(false)
  const redesignInputRef = useRef<HTMLInputElement>(null)

  // Camera state
  const [showCamera, setShowCamera] = useState(false)
  const [, setCameraStream] = useState<MediaStream | null>(null)
  const [capturedImage, setCapturedImage] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const cameraStreamRef = useRef<MediaStream | null>(null)
  const facingModeRef = useRef<'user' | 'environment'>('environment')

  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleAttachFile = useCallback((accept: string) => {
    setShowAttachMenu(false)
    if (fileInputRef.current) {
      fileInputRef.current.accept = accept
      fileInputRef.current.click()
    }
  }, [])

  const pendingFileRef = useRef<{ file: File; dataUrl?: string } | null>(null)

  const handleFileSelected = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    const file = files[0]
    e.target.value = ''

    if (file.type.startsWith('image/')) {
      const reader = new FileReader()
      reader.onload = (ev) => {
        const dataUrl = ev.target?.result as string
        pendingFileRef.current = { file, dataUrl }
        setPendingPreview(dataUrl)
      }
      reader.readAsDataURL(file)
    } else {
      pendingFileRef.current = { file }
      setPendingPreview(null)
    }
  }, [])

  // Click outside for attach menu
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (attachRef.current && !attachRef.current.contains(e.target as Node)) {
        setShowAttachMenu(false)
      }
    }
    if (showAttachMenu) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showAttachMenu])

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px'
    }
  }, [])

  // === Voice Recording ===
  const stopRecording = useCallback(() => {
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current)
      recordingTimerRef.current = null
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop()
      recognitionRef.current = null
    }
    setIsRecording(false)
    setIsPaused(false)
    setRecordingTime(0)
    isPausedRef.current = false
  }, [])

  const pauseRecording = useCallback(() => {
    isPausedRef.current = true
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current)
      recordingTimerRef.current = null
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop()
      recognitionRef.current = null
    }
    setRecordingTime(0)
    setIsPaused(true)
  }, [])

  // (audio level monitoring removed; using SpeechRecognition API)

  const startRecording = useCallback(async (isResume = false) => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) {
      setError('Speech recognition is not supported in this browser. Try Chrome or Edge.')
      return
    }

    try {
      const recognition = new SpeechRecognition()
      recognition.continuous = true
      recognition.interimResults = true
      recognition.lang = 'en-US'

      recognition.onresult = (event: any) => {
        let newFinalText = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            newFinalText += event.results[i][0].transcript
          }
        }
        if (newFinalText) {
          accumulatedTextRef.current += newFinalText
          const currentVal = valueRef.current
          setValue(currentVal + newFinalText)
          if (textareaRef.current) {
            textareaRef.current.style.height = 'auto'
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px'
          }
        }
      }

      recognition.onerror = (event: any) => {
        if (event.error === 'not-allowed') {
          setError('Microphone access denied. Please allow microphone permissions.')
        } else if (event.error !== 'no-speech' && event.error !== 'aborted') {
          setError(`Speech recognition error: ${event.error}`)
        }
        if (!isPausedRef.current) {
          if (recordingTimerRef.current) {
            clearInterval(recordingTimerRef.current)
            recordingTimerRef.current = null
          }
          setIsRecording(false)
          setIsPaused(false)
          setRecordingTime(0)
        }
      }

      recognition.onend = () => {
        if (!isPausedRef.current) {
          if (recordingTimerRef.current) {
            clearInterval(recordingTimerRef.current)
            recordingTimerRef.current = null
          }
          setIsRecording(false)
          setRecordingTime(0)
        }
      }

      recognition.start()
      recognitionRef.current = recognition
      setIsRecording(true)
      setIsPaused(false)
      isPausedRef.current = false
      setRecordingTime(0)

      if (!isResume) {
        accumulatedTextRef.current = ''
      }

      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current)
      }
      recordingTimerRef.current = setInterval(() => {
        setRecordingTime((prev) => prev + 1)
      }, 1000)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'NotAllowedError') {
        setError('Microphone access denied. Please allow microphone permissions in your browser settings.')
      } else {
        setError('Could not start speech recognition. Please try again.')
      }
    }
  }, [setError])

  const handleVoiceClick = useCallback(() => {
    if (isRecording && !isPaused) {
      pauseRecording()
    } else if (isPaused) {
      startRecording(true)
    } else {
      startRecording(false)
    }
  }, [isRecording, isPaused, startRecording, pauseRecording])

  const handleSubmit = useCallback(() => {
    const currentValue = valueRef.current
    const trimmed = currentValue.trim()
    if (trimmed && !isLoading) {
      if (isRecording || isPaused) {
        stopRecording()
      }
      const attachment = pendingFileRef.current
      pendingFileRef.current = null
      setPendingPreview(null)
      onSubmit(trimmed, attachment || undefined)
      setValue('')
      accumulatedTextRef.current = ''
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto'
      }
    }
  }, [isLoading, onSubmit, isRecording, isPaused, stopRecording])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit]
  )

  // === Camera ===
  const stopCamera = useCallback(() => {
    const stream = cameraStreamRef.current
    if (stream) {
      stream.getTracks().forEach(t => t.stop())
    }
    cameraStreamRef.current = null
    setCameraStream(null)
    setCapturedImage(null)
    setShowCamera(false)
  }, [])

  useEffect(() => {
    return () => {
      stopCamera()
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current)
        recordingTimerRef.current = null
      }
      if (recognitionRef.current) {
        isPausedRef.current = false
        recognitionRef.current.stop()
        recognitionRef.current = null
      }
    }
  }, [stopCamera])

  const startCamera = useCallback(async (useFacingMode?: 'user' | 'environment') => {
    const fm = useFacingMode || facingModeRef.current
    try {
      let stream: MediaStream | null = null
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: fm, width: { ideal: 1920 }, height: { ideal: 1080 } },
        })
      } catch {
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 1280 }, height: { ideal: 720 } },
          })
        } catch {
          stream = await navigator.mediaDevices.getUserMedia({ video: true })
        }
      }
      cameraStreamRef.current = stream
      setCameraStream(stream)
      setCapturedImage(null)
      setSelectedAnalysis('analyze')
      setShowCamera(true)

      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream
        }
      }, 100)
    } catch (err) {
      setError('Camera access denied. Please allow camera permissions.')
    }
  }, [setError])

  // Listen for camera open event from ChatMessage
  useEffect(() => {
    const handler = () => startCamera()
    window.addEventListener('apex:open-camera', handler)
    return () => window.removeEventListener('apex:open-camera', handler)
  }, [startCamera])

  // Escape key to close camera
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showCamera) {
        stopCamera()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [showCamera, stopCamera])

  const handleImageClick = useCallback(() => {
    if (showCamera) {
      stopCamera()
    } else {
      startCamera()
    }
  }, [showCamera, startCamera, stopCamera])

  const capturePhoto = useCallback(() => {
    if (!videoRef.current || !canvasRef.current) return
    const video = videoRef.current
    const canvas = canvasRef.current
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/jpeg', 0.9)
    setCapturedImage(dataUrl)
  }, [])

  const retakePhoto = useCallback(() => {
    setCapturedImage(null)
  }, [])

  const toggleCamera = useCallback(async () => {
    const newFacingMode = facingModeRef.current === 'environment' ? 'user' : 'environment'
    facingModeRef.current = newFacingMode

    const stream = cameraStreamRef.current
    if (stream) {
      stream.getTracks().forEach(t => t.stop())
    }
    cameraStreamRef.current = null
    setCameraStream(null)
    setCapturedImage(null)

    await startCamera(newFacingMode)
  }, [startCamera])

  const handleRedesignSelect = useCallback(() => {
    setShowAttachMenu(false)
    if (redesignInputRef.current) {
      redesignInputRef.current.click()
    }
  }, [])

  const handleRedesignFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    const file = files[0]
    e.target.value = ''
    if (!file.type.startsWith('image/')) {
      setError('Please select an image file.')
      return
    }
    const reader = new FileReader()
    reader.onload = (ev) => {
      setRedesignPreview(ev.target?.result as string)
      setRedesignFile(file)
      setShowRedesign(true)
      setRedesignPrompt('')
    }
    reader.readAsDataURL(file)
  }, [setError])

  const handleRedesignSubmit = useCallback(async () => {
    if (!redesignFile || !redesignPrompt.trim()) return
    setIsRedesigning(true)
    try {
      addMessage({
        id: `redesign_${Date.now()}_user`,
        role: 'user',
        content: `Redesign this image: ${redesignPrompt.trim()}`,
        type: 'image',
        image: redesignPreview || undefined,
        timestamp: Date.now(),
      })
      const response = await apiClient.redesignImage(redesignFile, redesignPrompt.trim())
      const dataUrl = response.image_base64
        ? (response.image_base64.startsWith('data:')
          ? response.image_base64
          : `data:image/png;base64,${response.image_base64}`)
        : response.image_url || ''
      addMessage({
        id: `redesign_${Date.now()}_assistant`,
        role: 'assistant',
        content: `Redesigned: ${redesignPrompt.trim()}`,
        type: 'image_redesign',
        label: 'Redesigned',
        image: dataUrl,
        mediaUrl: dataUrl,
        timestamp: Date.now(),
      })
      setShowRedesign(false)
      setRedesignFile(null)
      setRedesignPreview(null)
      setRedesignPrompt('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Image redesign failed')
    } finally {
      setIsRedesigning(false)
    }
  }, [redesignFile, redesignPrompt, redesignPreview, addMessage, setError])

  const cancelRedesign = useCallback(() => {
    setShowRedesign(false)
    setRedesignFile(null)
    setRedesignPreview(null)
    setRedesignPrompt('')
  }, [])

  const submitPhoto = useCallback(async () => {
    if (!capturedImage) return
    stopCamera()

    const blob = await (await fetch(capturedImage)).blob()
    const file = new File([blob], `capture_${Date.now()}.jpg`, { type: 'image/jpeg' })

    try {
      setChatLoading(true)
      const analysisLabel = analysisOptions.find(o => o.id === selectedAnalysis)?.label || 'Analyze'
      addMessage({
        id: `cam_${Date.now()}_user`,
        role: 'user',
        content: `[${analysisLabel}: Camera capture]`,
        type: 'image',
        image: capturedImage,
        timestamp: Date.now(),
      })
      const history = currentMessages.map(msg => ({
        role: msg.role,
        content: msg.content,
      }))
      const response = await apiClient.analyzeImage(file, currentConversationId || undefined, history, selectedAnalysis)
      const assistantMsg: Message = {
        id: `msg_${Date.now()}_assistant`,
        role: 'assistant',
        content: response.content,
        type: response.type,
        sources: response.sources,
        analysis: response.analysis,
        timestamp: Date.now(),
      }
      if (response.image_url) {
        assistantMsg.image = response.image_url
      } else if ((response as any).image_base64) {
        const b64 = (response as any).image_base64 as string
        assistantMsg.image = b64.startsWith('data:') ? b64 : `data:image/png;base64,${b64}`
      }
      addMessage(assistantMsg)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Image analysis failed')
    } finally {
      setChatLoading(false)
    }
  }, [capturedImage, selectedAnalysis, stopCamera, addMessage, setChatLoading, setError, currentConversationId, currentMessages])

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
  }

    return (
    <>
      <div className={`chat-input-container ${isRecording ? 'is-recording' : ''}`}>
        {pendingPreview && (
          <div className="pending-attachment">
            <img src={pendingPreview} alt="Pending attachment" className="pending-attachment-img" />
            <button
              className="pending-attachment-remove"
              onClick={() => { pendingFileRef.current = null; setPendingPreview(null) }}
              title="Remove attachment"
            >
              <X size={14} />
            </button>
          </div>
        )}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={isRecording ? 'Recording... you can edit text while speaking' : placeholder}
          disabled={isLoading}
          className="chat-input"
          rows={1}
        />
        {isRecording && (
          <div className="recording-badge">
            <span className="recording-dot" />
            <span className="recording-time">{formatTime(recordingTime)}</span>
            <span className="recording-hint">{isPaused ? 'Paused' : 'Speak now...'}</span>
          </div>
        )}
        <div className="attach-wrapper" ref={attachRef}>
          <button
            onClick={() => setShowAttachMenu(!showAttachMenu)}
            disabled={isLoading || isRecording}
            className={`action-button ${showAttachMenu ? 'attach-active' : ''}`}
            title="Attach file"
          >
            <Plus size={18} />
          </button>
          {showAttachMenu && (
            <div className="attach-menu">
              <button className="attach-menu-item" onClick={() => handleAttachFile('image/*')}>
                <Image size={16} /> <span>Image</span>
              </button>
              <button className="attach-menu-item" onClick={handleRedesignSelect}>
                <Wand2 size={16} /> <span>Redesign</span>
              </button>
              <button className="attach-menu-item" onClick={() => handleAttachFile('audio/*')}>
                <Music size={16} /> <span>Audio</span>
              </button>
              <button className="attach-menu-item" onClick={() => handleAttachFile('video/*')}>
                <Video size={16} /> <span>Video</span>
              </button>
              <button className="attach-menu-item" onClick={() => handleAttachFile('*')}>
                <FileIcon size={16} /> <span>File</span>
              </button>
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            style={{ display: 'none' }}
            onChange={handleFileSelected}
          />
        </div>
        {isRecording || isPaused ? (
          <>
            <button
              onClick={handleVoiceClick}
              className={`action-button ${isRecording && !isPaused ? 'recording-active' : ''}`}
              title={isPaused ? 'Resume recording' : 'Pause recording'}
            >
              {isPaused ? <Play size={18} /> : <Pause size={18} />}
            </button>
            <button
              onClick={stopRecording}
              className="action-button stop-recording-btn"
              title="Stop recording"
            >
              <StopCircle size={18} />
            </button>
          </>
        ) : (
          <button
            onClick={handleVoiceClick}
            disabled={isLoading}
            className="action-button"
            title="Voice search"
          >
            <Mic size={18} />
          </button>
        )}
        <button
          onClick={handleImageClick}
          disabled={isLoading || isRecording}
          className={`action-button ${showCamera ? 'camera-active' : ''}`}
          title={showCamera ? 'Close camera' : 'Open camera'}
        >
          <Camera size={18} />
        </button>
        <button
          onClick={handleSubmit}
          disabled={isLoading || !value.trim()}
          className="send-button"
          title="Send message"
        >
          {isLoading ? <Sparkles size={18} className="sparkle-icon" /> : <Send size={18} />}
        </button>
      </div>

      {/* Camera Overlay */}
      {showCamera && (
        <div className="camera-overlay" onClick={stopCamera}>
          <div className="camera-container" onClick={e => e.stopPropagation()}>
            <div className="camera-header">
              <span className="camera-title">Camera Capture</span>
              <button className="camera-close-btn" onClick={stopCamera} title="Close camera">
                <X size={20} /><span style={{ fontSize: 13 }}>Close</span>
              </button>
            </div>

            {!capturedImage ? (
              <>
                <div className="camera-viewfinder">
                  <video ref={videoRef} autoPlay playsInline className="camera-video" />
                  <canvas ref={canvasRef} style={{ display: 'none' }} />
                  <button className="camera-flip-btn" onClick={toggleCamera} title="Switch camera">
                    <RefreshCw size={20} />
                  </button>
                </div>
                <div className="camera-footer">
                  <button className="camera-capture-btn" onClick={capturePhoto} title="Capture photo">
                    <Camera size={24} />
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="camera-preview">
                  <img src={capturedImage} alt="Captured" className="camera-preview-img" />
                </div>
                <div className="camera-analysis-options">
                  {analysisOptions.map((opt) => {
                    const Icon = ICON_MAP[opt.icon] || Eye
                    return (
                      <button
                        key={opt.id}
                        className={`analysis-option ${selectedAnalysis === opt.id ? 'selected' : ''}`}
                        onClick={() => setSelectedAnalysis(opt.id)}
                      >
                        <Icon size={16} />
                        <div className="analysis-option-text">
                          <span className="analysis-option-label">{opt.label}</span>
                          <span className="analysis-option-desc">{opt.desc}</span>
                        </div>
                      </button>
                    )
                  })}
                </div>
                <div className="camera-footer">
                  <button className="camera-retake-btn" onClick={retakePhoto} title="Retake">
                    <Image size={18} />
                    <span>Retake</span>
                  </button>
                  <button className="camera-use-btn" onClick={submitPhoto} title="Analyze">
                    <Scan size={18} />
                    <span>{analysisOptions.find(o => o.id === selectedAnalysis)?.label || 'Analyze'}</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Redesign Overlay */}
      <input
        ref={redesignInputRef}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={handleRedesignFile}
      />
      {showRedesign && redesignPreview && (
        <div className="camera-overlay">
          <div className="camera-container">
            <div className="camera-header">
              <span className="camera-title">Redesign Image</span>
              <button className="camera-close-btn" onClick={cancelRedesign} title="Cancel">
                <X size={20} />
              </button>
            </div>
            <div className="camera-preview">
              <img src={redesignPreview} alt="Original" className="camera-preview-img" />
            </div>
            <div className="redesign-input-area">
              <textarea
                className="redesign-textarea"
                placeholder="Describe how to redesign this image (e.g., 'make it look like a watercolor painting', 'apply cyberpunk neon style')"
                value={redesignPrompt}
                onChange={(e) => setRedesignPrompt(e.target.value)}
                rows={3}
                disabled={isRedesigning}
              />
            </div>
            <div className="camera-footer">
              <button className="camera-retake-btn" onClick={cancelRedesign}>
                <X size={18} />
                <span>Cancel</span>
              </button>
              <button
                className="camera-use-btn"
                onClick={handleRedesignSubmit}
                disabled={isRedesigning || !redesignPrompt.trim()}
              >
                {isRedesigning ? <Sparkles size={18} className="sparkle-icon" /> : <Wand2 size={18} />}
                <span>{isRedesigning ? 'Redesigning...' : 'Redesign'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
