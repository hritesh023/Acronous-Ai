import { useCallback, useState, useRef, useEffect } from 'react'
import { Plus, Trash2, Moon, Sun, MessageSquare, Search, Code, BookOpen, LogOut, Download, Search as SearchIcon, X } from 'lucide-react'
import { useChat } from '../context/ChatContext'
import { useAuth } from '../context/AuthContext'
import { apiClient } from '../api/client'
import '../styles/Sidebar.css'

type Suggestion = { query: string; title: string; desc: string; icon: string }

const iconMap: Record<string, any> = { search: Search, code: Code, book: BookOpen }

export function Sidebar() {
  const { conversations, currentConversationId, createConversation, switchConversation, deleteConversation, uiState, toggleTheme } = useChat()
  const { user, signOut } = useAuth()
  const [showTopics, setShowTopics] = useState(false)
  const [topics, setTopics] = useState<Suggestion[]>([])
  const topicsRef = useRef<HTMLDivElement>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [showSearch, setShowSearch] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let cancelled = false
    ;(async function loadConfig() {
      for (let i = 0; i < 3; i++) {
        try {
          const cfg = await apiClient.getConfig()
          if (cancelled) return
          if (cfg?.suggestions) setTopics(cfg.suggestions)
          return
        } catch {
          if (i < 2) await new Promise(r => setTimeout(r, 1000))
        }
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (topicsRef.current && !topicsRef.current.contains(e.target as Node)) {
        setShowTopics(false)
      }
    }
    if (showTopics) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showTopics])

  useEffect(() => {
    if (showSearch && searchInputRef.current) {
      searchInputRef.current.focus()
    }
  }, [showSearch])

  const handleNewConversation = useCallback(async () => {
    await createConversation()
    setShowTopics(false)
  }, [createConversation])

  const handleTopicSelect = useCallback(async (query: string) => {
    const newId = await createConversation()
    setShowTopics(false)
    window.dispatchEvent(new CustomEvent('apex:send-message', { detail: { query, conversationId: newId } }))
  }, [createConversation])

  const handleDelete = useCallback((id: string) => {
    deleteConversation(id)
  }, [deleteConversation])

  const handleExport = useCallback(async (id: string) => {
    try {
      const token = localStorage.getItem('supabase.auth.token')
      const headers: Record<string, string> = {}
      if (token) {
        const parsed = JSON.parse(token)
        headers['Authorization'] = `Bearer ${parsed.access_token}`
      }
      const resp = await fetch(`/api/conversations/${id}/export?fmt=markdown`, { headers })
      const text = await resp.text()
      const blob = new Blob([text], { type: 'text/markdown' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `apex-conversation-${id.slice(0, 8)}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch {}
  }, [])

  const truncateTitle = (title: string, max = 28) => {
    return title.length > max ? title.substring(0, max) + '...' : title
  }

  const convEntries = Object.entries(conversations)
  const filteredEntries = searchQuery
    ? convEntries.filter(([_, conv]) =>
        conv.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : convEntries

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <div className="brand-icon">
            <img src="/logo.png" alt="Apex AI" width="20" height="20" style={{ borderRadius: 6 }} />
          </div>
          <span className="brand-text">Apex AI</span>
        </div>
        <div className="new-chat-wrapper" ref={topicsRef}>
          <button className="new-chat-button" onClick={handleNewConversation} title="New conversation">
            <Plus size={18} />
          </button>
          {showTopics && topics.length > 0 && (
            <div className="topic-popover">
              <div className="topic-popover-header">Start a conversation</div>
              <div className="topic-popover-grid">
                {topics.map((topic) => {
                  const Icon = iconMap[topic.icon] || MessageSquare
                  return (
                    <button key={topic.title} className="topic-card" onClick={() => handleTopicSelect(topic.query)}>
                      <Icon size={16} className="topic-card-icon" />
                      <span className="topic-card-label">{topic.title}</span>
                      <span className="topic-card-desc">{topic.desc}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="sidebar-search">
        {showSearch ? (
          <div className="search-input-wrapper">
            <SearchIcon size={14} className="search-input-icon" />
            <input
              ref={searchInputRef}
              type="text"
              className="search-input"
              placeholder="Search conversations..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onBlur={() => { if (!searchQuery) setShowSearch(false) }}
              onKeyDown={e => e.key === 'Escape' && (setShowSearch(false), setSearchQuery(''))}
            />
            {searchQuery && (
              <button className="search-clear-btn" onClick={() => (setSearchQuery(''), searchInputRef.current?.focus())}>
                <X size={14} />
              </button>
            )}
          </div>
        ) : (
          <button className="search-toggle-btn" onClick={() => setShowSearch(true)} title="Search conversations">
            <SearchIcon size={16} />
            <span>Search</span>
          </button>
        )}
      </div>

      <div className="conversations-section">
        <div className="section-label">Conversations</div>
        <div className="conversations-list">
          {filteredEntries.length === 0 ? (
            <div className="empty-state">{searchQuery ? 'No matching conversations' : 'No conversations yet'}</div>
          ) : (
            filteredEntries.map(([id, conv]) => (
              <div key={id} className={`conversation-item ${id === currentConversationId ? 'active' : ''}`}>
                <button
                  className="conversation-btn"
                  onClick={() => switchConversation(id)}
                  title={conv.title}
                >
                  <MessageSquare size={14} className="conv-icon" />
                  <span className="conv-title">{truncateTitle(conv.title)}</span>
                </button>
                <div className="conversation-actions">
                  <button
                    className="action-icon-btn"
                    onClick={(e) => { e.stopPropagation(); handleExport(id) }}
                    title="Export conversation"
                  >
                    <Download size={12} />
                  </button>
                  {id !== 'default' && (
                    <button
                      className="delete-button"
                      onClick={(e) => { e.stopPropagation(); handleDelete(id) }}
                      title="Delete conversation"
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="sidebar-user">
          <span className="sidebar-user-email" title={user?.email || ''}>{user?.email || ''}</span>
        </div>
        <button className="theme-toggle" onClick={toggleTheme} title="Toggle theme">
          {uiState.theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          <span>{uiState.theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>
        <button className="signout-button" onClick={signOut} title="Sign out">
          <LogOut size={16} />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  )
}
