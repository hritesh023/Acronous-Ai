import { useState, useRef } from 'react'
import { Message } from '../types/index'
import { MarkdownRenderer } from './MarkdownRenderer'
import { Copy, Check, User, Download, Volume2, VolumeX, Film, RefreshCw, Wand2, Maximize2, Camera, QrCode } from 'lucide-react'
import '../styles/ChatMessage.css'

interface ChatMessageProps {
  message: Message
}

function MediaPlayer({ url, type }: { url: string; type: 'video' | 'audio' }) {
  const ref = useRef<HTMLVideoElement | HTMLAudioElement>(null)
  const [error, setError] = useState(false)

  if (error) {
    return (
      <div className="media-error">
        <span>Failed to load {type}. <a href={url} target="_blank" rel="noopener noreferrer">Open directly</a></span>
      </div>
    )
  }

  if (type === 'video') {
    return (
      <div className="message-video-wrapper">
        <video ref={ref as React.Ref<HTMLVideoElement>} src={url} controls className="message-video" onError={() => setError(true)} />
      </div>
    )
  }

  return (
    <div className="message-audio-wrapper">
      <audio ref={ref as React.Ref<HTMLAudioElement>} src={url} controls className="message-audio" onError={() => setError(true)} />
    </div>
  )
}

function isMediaUrl(str: string): 'image' | 'video' | 'audio' | null {
  if (!str) return null
  const imageExt = /\.(png|jpg|jpeg|gif|webp|bmp|svg)(\?.*)?$/i
  const videoExt = /\.(mp4|webm|ogg|mov|avi|mkv)(\?.*)?$/i
  const audioExt = /\.(mp3|wav|ogg|flac|aac|m4a|wma)(\?.*)?$/i
  if (imageExt.test(str)) return 'image'
  if (videoExt.test(str)) return 'video'
  if (audioExt.test(str)) return 'audio'
  if (str.startsWith('data:image/')) return 'image'
  if (str.startsWith('data:video/')) return 'video'
  if (str.startsWith('data:audio/')) return 'audio'
  return null
}

function DownloadButton({ url, label }: { url: string; label: string }) {
  return (
    <a href={url} download className="media-download-btn" title={`Download ${label}`}>
      <Download size={14} />
      <span>Download</span>
    </a>
  )
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [imgLoaded, setImgLoaded] = useState(false)

  const handleMaximize = (url: string) => {
    const event = new CustomEvent('apex:maximize-image', {
      detail: { imageUrl: url },
    })
    window.dispatchEvent(event)
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
    }
  }

  const renderMedia = () => {
    const mediaType = isMediaUrl(message.content)

    if (message.videoUrl || mediaType === 'video') {
      return (
        <>
          <MediaPlayer url={message.videoUrl || message.content} type="video" />
          <DownloadButton url={message.videoUrl || message.content} label="Video" />
        </>
      )
    }

    if (message.audioUrl || mediaType === 'audio') {
      return (
        <>
          <MediaPlayer url={message.audioUrl || message.content} type="audio" />
          <DownloadButton url={message.audioUrl || message.content} label="Audio" />
        </>
      )
    }

    if (message.image) {
      const isBase64 = message.image.startsWith('data:')
      const fallbackUrl = message.mediaUrl
      const displayUrl = message.image
      return (
        <div className="message-image-wrapper">
          {imgError ? (
            fallbackUrl && fallbackUrl !== displayUrl ? (
              <img
                src={fallbackUrl}
                alt="Content"
                className="message-image"
                crossOrigin="anonymous"
                onClick={() => handleMaximize(fallbackUrl)}
                style={{ cursor: 'pointer' }}
                onError={() => setImgError(true)}
              />
            ) : (
              <div className="image-error-fallback">
                <span>Image could not be displayed</span>
                {fallbackUrl && <a href={fallbackUrl} target="_blank" rel="noopener noreferrer" className="image-retry-btn">Open directly</a>}
                <button className="image-retry-btn" onClick={() => setImgError(false)}>
                  <RefreshCw size={14} />
                  <span>Retry</span>
                </button>
              </div>
            )
          ) : (
            <img
              src={displayUrl}
              alt="Content"
              className="message-image"
              crossOrigin={isBase64 ? undefined : 'anonymous'}
              onClick={() => handleMaximize(fallbackUrl || displayUrl)}
              style={{ cursor: 'pointer' }}
              onLoad={() => setImgLoaded(true)}
              onError={() => { if (!imgLoaded) setImgError(true) }}
            />
          )}
          {!imgError && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4, alignItems: 'center' }}>
              <button
                className="image-regenerate-btn"
                onClick={() => handleMaximize(fallbackUrl || displayUrl)}
                title="View full size"
              >
                <Maximize2 size={14} />
                <span>Full size</span>
              </button>
              {!isUser && (
                <>
                  {(message.type === 'image_generated' || message.type === 'image_redesign' || message.type === 'qr_code') && (
                    <button
                      className="image-regenerate-btn"
                      onClick={() => {
                        const event = new CustomEvent('apex:send-message', {
                          detail: { query: `Regenerate: ${message.content}` },
                        })
                        window.dispatchEvent(event)
                      }}
                      title="Regenerate"
                    >
                      <RefreshCw size={14} />
                      <span>Regenerate</span>
                    </button>
                  )}
                  <button
                    className="image-regenerate-btn"
                    onClick={() => {
                      const event = new CustomEvent('apex:redesign-image', {
                        detail: { imageUrl: fallbackUrl || displayUrl, prompt: message.content },
                      })
                      window.dispatchEvent(event)
                    }}
                    title="Redesign this image"
                  >
                    <Wand2 size={14} />
                    <span>Redesign</span>
                  </button>
                </>
              )}
              {isUser && (
                <>
                  <button
                    className="image-regenerate-btn"
                    onClick={() => {
                      window.dispatchEvent(new CustomEvent('apex:open-camera'))
                    }}
                    title="Open camera for image analysis"
                  >
                    <Camera size={14} />
                    <span>Analyze</span>
                  </button>
                  <button
                    className="image-regenerate-btn"
                    onClick={() => {
                      const event = new CustomEvent('apex:redesign-image', {
                        detail: { imageUrl: fallbackUrl || displayUrl, prompt: message.content },
                      })
                      window.dispatchEvent(event)
                    }}
                    title="Redesign this image"
                  >
                    <Wand2 size={14} />
                    <span>Redesign</span>
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )
    }

    if (mediaType === 'image') {
      return (
        <div className="message-image-wrapper">
          {imgError ? (
            <div className="image-error-fallback">
              <span>Image could not be displayed</span>
              <button
                className="image-retry-btn"
                onClick={() => setImgError(false)}
              >
                <RefreshCw size={14} />
                <span>Retry</span>
              </button>
            </div>
          ) : (
            <img
              src={message.content}
              alt="Generated content"
              className="message-image"
              onClick={() => handleMaximize(message.content)}
              style={{ cursor: 'pointer' }}
              onLoad={() => setImgLoaded(true)}
              onError={() => { if (!imgLoaded) setImgError(true) }}
            />
          )}
        </div>
      )
    }

    if (isUser) {
      return <div className="message-content">{message.content}</div>
    }

    return <MarkdownRenderer content={message.content} />
  }

  const getBadgeIcon = () => {
    if (message.type === 'image_generated') return null
    if (message.type === 'video_generated') return <Film size={12} />
    if (message.type === 'audio_generated') return <Volume2 size={12} />
    if (message.type === 'qr_code') return <QrCode size={12} />
    return null
  }

  return (
    <div className={`chat-message chat-message-${message.role}`}>
      {!isUser && (
        <div className="message-avatar assistant-avatar">
          <img src="/logo.png" alt="Apex" width="18" height="18" style={{ borderRadius: 999 }} />
        </div>
      )}

      <div className="message-bubble">
        {message.label && !isUser && (
          <span className="message-badge">
            {getBadgeIcon()}
            {message.label}
          </span>
        )}

        {renderMedia()}

        {!isUser && (
          <>
            <button
              className={`copy-button ${speaking ? 'speaking' : ''}`}
              onClick={() => {
                if (speaking) {
                  window.speechSynthesis.cancel()
                  setSpeaking(false)
                } else {
                  const utterance = new SpeechSynthesisUtterance(message.content.replace(/[#*`\[\]()>|~_\-]/g, ''))
                  utterance.rate = 1.0
                  utterance.pitch = 1.0
                  utterance.onend = () => setSpeaking(false)
                  utterance.onerror = () => setSpeaking(false)
                  window.speechSynthesis.cancel()
                  window.speechSynthesis.speak(utterance)
                  setSpeaking(true)
                }
              }}
              title={speaking ? 'Stop' : 'Read aloud'}
            >
              {speaking ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
            <button
              className={`copy-button ${copied ? 'copied' : ''}`}
              onClick={handleCopy}
              title={copied ? 'Copied!' : 'Copy message'}
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </>
        )}

        {message.sources && message.sources.length > 0 && !isUser && (
          <details className="message-sources">
            <summary>Sources ({message.sources.length})</summary>
            <ul>
              {message.sources.map((source, idx) => (
                <li key={idx}>
                  {source.url ? (
                    <a href={source.url} target="_blank" rel="noopener noreferrer">
                      {source.title}
                    </a>
                  ) : (
                    source.title
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      {isUser && (
        <div className="message-avatar user-avatar">
          <User size={18} />
        </div>
      )}
    </div>
  )
}
