import React, { createContext, useContext, useReducer, useCallback, useEffect, useRef } from 'react'
import { Message, Conversation, UIState } from '../types/index'
import { apiClient, setAuthToken, getAuthToken } from '../api/client'
import { useAuth } from './AuthContext'

interface ChatContextType {
  conversations: Record<string, Conversation>
  currentConversationId: string
  currentMessages: Message[]
  uiState: UIState
  addMessage: (message: Message, convId?: string) => void
  createConversation: () => Promise<string>
  switchConversation: (id: string) => void
  deleteConversation: (id: string) => void
  setShowImageStudio: (show: boolean) => void
  setShowVoiceInput: (show: boolean) => void
  setIsLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  toggleTheme: () => void
  syncFromBackend: () => Promise<void>
}

const ChatContext = createContext<ChatContextType | undefined>(undefined)

interface State {
  conversations: Record<string, Conversation>
  currentConversationId: string
  uiState: UIState
}

type Action =
  | { type: 'ADD_MESSAGE'; payload: Message }
  | { type: 'CREATE_CONVERSATION'; payload: string }
  | { type: 'SWITCH_CONVERSATION'; payload: string }
  | { type: 'DELETE_CONVERSATION'; payload: string }
  | { type: 'SET_CONVERSATIONS'; payload: Record<string, Conversation> }
  | { type: 'SET_CURRENT'; payload: string }
  | { type: 'UPDATE_CONVERSATION_ID'; payload: { oldId: string; newId: string } }
  | { type: 'SET_SHOW_IMAGE_STUDIO'; payload: boolean }
  | { type: 'SET_SHOW_VOICE_INPUT'; payload: boolean }
  | { type: 'SET_IS_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'TOGGLE_THEME' }

function getInitialTheme(): 'light' | 'dark' {
  try {
    const saved = localStorage.getItem('theme')
    if (saved === 'light' || saved === 'dark') return saved
  } catch {}
  return 'dark'
}

const initialState: State = {
  conversations: {
    default: {
      id: 'default',
      title: 'New Conversation',
      messages: [],
      createdAt: Date.now(),
    },
  },
  currentConversationId: 'default',
  uiState: {
    showImageStudio: false,
    showVoiceInput: false,
    isLoading: false,
    error: null,
    theme: getInitialTheme(),
  },
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'SET_CONVERSATIONS':
      return { ...state, conversations: action.payload }

    case 'SET_CURRENT':
      return { ...state, currentConversationId: action.payload }

    case 'ADD_MESSAGE': {
      const convId = state.currentConversationId
      const conv = state.conversations[convId]
      if (!conv) return state
      const isFirstUserMessage = conv.messages.length === 0 && action.payload.role === 'user'
      const title = isFirstUserMessage
        ? action.payload.content.length > 40
          ? action.payload.content.substring(0, 40) + '...'
          : action.payload.content
        : conv.title
      return {
        ...state,
        conversations: {
          ...state.conversations,
          [convId]: { ...conv, title, messages: [...conv.messages, action.payload] },
        },
      }
    }

    case 'CREATE_CONVERSATION':
      return {
        ...state,
        conversations: {
          ...state.conversations,
          [action.payload]: { id: action.payload, title: 'New Conversation', messages: [], createdAt: Date.now() },
        },
        currentConversationId: action.payload,
      }

    case 'SWITCH_CONVERSATION':
      return { ...state, currentConversationId: action.payload }

    case 'UPDATE_CONVERSATION_ID': {
      const { oldId, newId } = action.payload
      const conv = state.conversations[oldId]
      if (!conv) return state
      const { [oldId]: _, ...rest } = state.conversations
      return {
        ...state,
        conversations: {
          ...rest,
          [newId]: { ...conv, id: newId },
        },
        currentConversationId: newId,
      }
    }

    case 'DELETE_CONVERSATION': {
      const { [action.payload]: _, ...rest } = state.conversations
      const keys = Object.keys(rest)
      const newCurrent = state.currentConversationId === action.payload
        ? (keys.includes('default') ? 'default' : keys[0] || 'default')
        : state.currentConversationId
      return { ...state, conversations: rest, currentConversationId: newCurrent }
    }

    case 'SET_SHOW_IMAGE_STUDIO':
      return { ...state, uiState: { ...state.uiState, showImageStudio: action.payload } }
    case 'SET_SHOW_VOICE_INPUT':
      return { ...state, uiState: { ...state.uiState, showVoiceInput: action.payload } }
    case 'SET_IS_LOADING':
      return { ...state, uiState: { ...state.uiState, isLoading: action.payload } }
    case 'SET_ERROR':
      return { ...state, uiState: { ...state.uiState, error: action.payload } }

    case 'TOGGLE_THEME': {
      const newTheme = state.uiState.theme === 'dark' ? 'light' : 'dark'
      try { localStorage.setItem('theme', newTheme) } catch {}
      return { ...state, uiState: { ...state.uiState, theme: newTheme } }
    }

    default:
      return state
  }
}

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const { session } = useAuth()
  const stateRef = useRef(state)
  stateRef.current = state

  useEffect(() => {
    if (session?.access_token) {
      setAuthToken(session.access_token)
      syncFromBackend()
    } else {
      setAuthToken(null)
    }
  }, [session])

  const syncFromBackend = useCallback(async () => {
    try {
      const convs = await apiClient.listConversations()
      if (!convs || convs.length === 0) return

      const mapped: Record<string, Conversation> = {}
      for (const c of convs) {
        const msgs = await apiClient.listMessages(c.id)
        mapped[c.id] = {
          id: c.id,
          title: c.title,
          messages: msgs.map(m => ({
            id: m.id,
            role: m.role as 'user' | 'assistant',
            content: m.content,
            type: m.type,
            label: m.label || undefined,
            image: m.image || undefined,
            mediaUrl: m.media_url || undefined,
            videoUrl: m.video_url || undefined,
            audioUrl: m.audio_url || undefined,
            sources: m.sources ? (typeof m.sources === 'string' ? JSON.parse(m.sources) : m.sources) : undefined,
            analysis: m.analysis ? (typeof m.analysis === 'string' ? JSON.parse(m.analysis) : m.analysis) : undefined,
            timestamp: new Date(m.created_at).getTime(),
          })),
          createdAt: new Date(c.created_at).getTime(),
        }
      }
      if (Object.keys(mapped).length > 0 && !mapped['default']) {
        dispatch({ type: 'SET_CONVERSATIONS', payload: mapped })
        const firstKey = Object.keys(mapped)[0]
        dispatch({ type: 'SET_CURRENT', payload: firstKey })
      }
    } catch (err) {
      console.error('Failed to sync conversations:', err)
    }
  }, [])

  const addMessage = useCallback(async (message: Message, convId?: string) => {
    dispatch({ type: 'ADD_MESSAGE', payload: message })
    const currentId = convId || stateRef.current.currentConversationId
    if (getAuthToken()) {
      try {
        await apiClient.addMessage(
          currentId,
          message.role,
          message.content,
          message.type,
          message.sources ? JSON.stringify(message.sources) : undefined,
          message.label,
          message.image,
          message.mediaUrl,
          message.videoUrl,
          message.audioUrl
        )
      } catch (err) {
        console.error('Failed to save message:', err)
      }
    }
  }, [])

  const createConversation = useCallback(async () => {
    const localId = `conv_${Date.now()}`
    dispatch({ type: 'CREATE_CONVERSATION', payload: localId })
    if (getAuthToken()) {
      try {
        const created = await apiClient.createConversation()
        if (created?.id && created.id !== localId) {
          dispatch({ type: 'UPDATE_CONVERSATION_ID', payload: { oldId: localId, newId: created.id } })
          return created.id
        }
      } catch (err) {
        console.error('Failed to create conversation on backend:', err)
      }
    }
    return localId
  }, [])

  const switchConversation = useCallback((id: string) => {
    dispatch({ type: 'SWITCH_CONVERSATION', payload: id })
  }, [])

  const deleteConversation = useCallback(async (id: string) => {
    dispatch({ type: 'DELETE_CONVERSATION', payload: id })
    if (getAuthToken()) {
      try {
        await apiClient.deleteConversation(id)
      } catch (err) {
        console.error('Failed to delete conversation:', err)
      }
    }
  }, [])

  const setShowImageStudio = useCallback((show: boolean) => {
    dispatch({ type: 'SET_SHOW_IMAGE_STUDIO', payload: show })
  }, [])
  const setShowVoiceInput = useCallback((show: boolean) => {
    dispatch({ type: 'SET_SHOW_VOICE_INPUT', payload: show })
  }, [])
  const setIsLoading = useCallback((loading: boolean) => {
    dispatch({ type: 'SET_IS_LOADING', payload: loading })
  }, [])
  const setError = useCallback((error: string | null) => {
    dispatch({ type: 'SET_ERROR', payload: error })
  }, [])
  const toggleTheme = useCallback(() => {
    dispatch({ type: 'TOGGLE_THEME' })
  }, [])

  const currentMessages = state.conversations[state.currentConversationId]?.messages || []

  const value: ChatContextType = {
    conversations: state.conversations,
    currentConversationId: state.currentConversationId,
    currentMessages,
    uiState: state.uiState,
    addMessage,
    createConversation,
    switchConversation,
    deleteConversation,
    setShowImageStudio,
    setShowVoiceInput,
    setIsLoading,
    setError,
    toggleTheme,
    syncFromBackend,
  }

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat() {
  const context = useContext(ChatContext)
  if (!context) throw new Error('useChat must be used within ChatProvider')
  return context
}
