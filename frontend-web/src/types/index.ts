export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  type: string
  label?: string
  image?: string
  videoUrl?: string
  audioUrl?: string
  mediaUrl?: string
  sources?: Array<{ title: string; url?: string }>
  analysis?: Record<string, any>
  timestamp: number
}

export interface Conversation {
  id: string
  title: string
  messages: Message[]
  createdAt: number
}

export interface UIState {
  showImageStudio: boolean
  showVoiceInput: boolean
  isLoading: boolean
  error: string | null
  theme: 'light' | 'dark'
}
