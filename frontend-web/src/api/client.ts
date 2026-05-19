import axios, { AxiosInstance } from 'axios'

export interface ChatRequest {
  query: string
  session_id?: string
  context?: Record<string, any>
  messages?: Array<{ role: string; content: string }>
  web_search_enabled?: boolean
  model?: string
}

export interface ChatResponse {
  content: string
  type: string
  sources: Array<{ title: string; url?: string }>
  analysis?: Record<string, any>
  session_id: string
  image_url?: string
  image_base64?: string
  video_url?: string
  audio_url?: string
}

export interface ImageGenerateRequest {
  prompt: string
  style?: string
}

export interface ImageGenerateResponse {
  image_base64?: string
  image_url?: string
  error?: string
  prompt: string
  type: string
}

export interface VideoGenerateResponse {
  video_url?: string
  error?: string
  prompt: string
  type: string
}

export interface AudioGenerateResponse {
  audio_url?: string
  audio_base64?: string
  error?: string
  prompt: string
  type: string
}

export interface Model {
  name: string
  type: string
  size?: string
}

export interface Status {
  status: string
  ollama_connected: boolean
  voice_available: boolean
  models: string[]
}

export interface ConversationData {
  id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface MessageData {
  id: string
  conversation_id: string
  user_id: string
  role: string
  content: string
  type: string
  sources?: any
  analysis?: any
  label?: string
  image?: string
  media_url?: string
  video_url?: string
  audio_url?: string
  created_at: string
}

let _authToken: string | null = null

export function setAuthToken(token: string | null) {
  _authToken = token
}

export function getAuthToken(): string | null {
  return _authToken
}

const BACKEND_URL_KEY = 'apex_backend_url'
const ENV_API_URL = (import.meta.env.VITE_API_URL as string) || ''

function getStoredBaseURL(): string {
  try {
    const stored = localStorage.getItem(BACKEND_URL_KEY)
    if (stored) return stored
  } catch {}
  return ENV_API_URL || ''
}

export function setBackendURL(url: string) {
  try {
    localStorage.setItem(BACKEND_URL_KEY, url)
  } catch {}
}

export function getBackendURL(): string {
  return getStoredBaseURL()
}

class ApiClient {
  private client: AxiosInstance

  constructor(baseURL: string = getStoredBaseURL()) {
    this.client = axios.create({
      baseURL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    })

    this.client.interceptors.request.use(config => {
      if (_authToken) {
        config.headers.Authorization = `Bearer ${_authToken}`
      }
      return config
    })

    this.client.interceptors.response.use(
      response => response,
      error => {
        console.error('API Error:', error.response?.data || error.message)
        throw error
      }
    )
  }

  private getBase(): string {
    return this.client.defaults.baseURL || ''
  }

  updateBaseURL(url: string) {
    this.client.defaults.baseURL = url
    setBackendURL(url)
  }

  async get(path: string) {
    return this.client.get(path)
  }

  async chat(request: ChatRequest): Promise<ChatResponse> {
    const response = await this.client.post<ChatResponse>(`${this.getBase()}/api/chat`, request, {
      timeout: 120000,
    })
    return response.data
  }

  async chatStream(request: ChatRequest): Promise<ReadableStream<Uint8Array>> {
    const response = await this.client.post(`${this.getBase()}/api/chat/stream`, request, {
      responseType: 'stream',
    })
    return response.data
  }

  async generateImage(request: ImageGenerateRequest): Promise<ImageGenerateResponse> {
    const response = await this.client.post<ImageGenerateResponse>(`${this.getBase()}/api/image/generate`, request)
    return response.data
  }

  async generateQRCode(request: { data: string; size?: number }): Promise<ImageGenerateResponse> {
    const response = await this.client.post<ImageGenerateResponse>(`${this.getBase()}/api/image/qr-code`, request)
    return response.data
  }

  async redesignImage(file: File, prompt: string): Promise<ImageGenerateResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('prompt', prompt)
    const response = await this.client.post<ImageGenerateResponse>(`${this.getBase()}/api/image/redesign`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async analyzeImage(file: File, sessionId?: string, messages?: Array<{ role: string; content: string }>, analysisType?: string): Promise<ChatResponse> {
    const formData = new FormData()
    formData.append('file', file)
    if (sessionId) formData.append('session_id', sessionId)
    if (messages) formData.append('messages', JSON.stringify(messages))
    if (analysisType) formData.append('analysis_type', analysisType)
    const response = await this.client.post<ChatResponse>(`${this.getBase()}/api/image/analyze`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  }

  async webSearch(query: string, maxResults: number = 5): Promise<{ results: Array<{ title: string; link: string; snippet: string }>; formatted: string }> {
    const response = await this.client.post(`${this.getBase()}/api/tools/search`, { query, max_results: maxResults })
    return response.data
  }

  async executeCode(code: string, language: string = 'python'): Promise<{ output: string; error?: string; exit_code: number }> {
    const response = await this.client.post(`${this.getBase()}/api/tools/execute`, { code, language })
    return response.data
  }

  async processDocument(file: File): Promise<{ text: string; type: string; filename: string; total_chars?: number }> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await this.client.post(`${this.getBase()}/api/tools/process-document`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    return response.data
  }

  async transcribeAudio(file: File): Promise<{ text: string; type: string }> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await this.client.post(`${this.getBase()}/api/voice/transcribe`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    return response.data
  }

  async generateVideo(request: { prompt: string; style?: string }): Promise<VideoGenerateResponse> {
    const response = await this.client.post<VideoGenerateResponse>(`${this.getBase()}/api/video/generate`, request, {
      timeout: 300000,
    })
    return response.data
  }

  async generateAudio(request: { prompt: string; voice?: string }): Promise<AudioGenerateResponse> {
    const response = await this.client.post<AudioGenerateResponse>(`${this.getBase()}/api/audio/generate`, request, {
      timeout: 300000,
    })
    return response.data
  }

  async listModels(): Promise<Model[]> {
    const response = await this.client.get<Model[]>(`${this.getBase()}/api/models/list`)
    return response.data
  }

  async getStatus(): Promise<Status> {
    const response = await this.client.get<Status>(`${this.getBase()}/api/status`)
    return response.data
  }

  async healthCheck(): Promise<{ status: string }> {
    const response = await this.client.get(`${this.getBase()}/health`)
    return response.data
  }

  async getConfig(): Promise<{ configured: boolean; chat: boolean; image_generation: boolean; voice: boolean; image_analysis: boolean; tools?: { web_search: boolean; code_execution: boolean; document_processing: boolean; tts: boolean }; suggestions: Array<{ query: string; title: string; desc: string; icon: string }> }> {
    const response = await this.client.get(`${this.getBase()}/api/config`)
    return response.data
  }

  async getMe(): Promise<any> {
    const response = await this.client.get(`${this.getBase()}/api/auth/me`)
    return response.data
  }

  async listConversations(): Promise<ConversationData[]> {
    const response = await this.client.get<ConversationData[]>(`${this.getBase()}/api/conversations`)
    return response.data
  }

  async createConversation(title: string = 'New Conversation'): Promise<ConversationData> {
    const response = await this.client.post<ConversationData>(`${this.getBase()}/api/conversations`, { title })
    return response.data
  }

  async deleteConversation(convId: string): Promise<void> {
    await this.client.delete(`${this.getBase()}/api/conversations/${convId}`)
  }

  async updateConversation(convId: string, title: string): Promise<ConversationData> {
    const response = await this.client.put<ConversationData>(`${this.getBase()}/api/conversations/${convId}`, { title })
    return response.data
  }

  async listMessages(convId: string): Promise<MessageData[]> {
    const response = await this.client.get<MessageData[]>(`${this.getBase()}/api/conversations/${convId}/messages`)
    return response.data
  }

  async addMessage(convId: string, role: string, content: string, msgType: string = 'text', sources?: string, label?: string, image?: string, mediaUrl?: string, videoUrl?: string, audioUrl?: string): Promise<MessageData> {
    const response = await this.client.post<MessageData>(`${this.getBase()}/api/conversations/${convId}/messages`, { role, content, msg_type: msgType, sources, label, image, media_url: mediaUrl, video_url: videoUrl, audio_url: audioUrl })
    return response.data
  }

  async syncConversations(conversations: Array<{ id: string; title: string; messages: Array<{ role: string; content: string; type?: string; label?: string; image?: string; media_url?: string; video_url?: string; audio_url?: string }> }>): Promise<any> {
    const response = await this.client.post(`${this.getBase()}/api/conversations/sync`, conversations)
    return response.data
  }

  async updateLLMConfig(config: { provider?: string; api_key?: string; model?: string; api_url?: string }): Promise<any> {
    const response = await this.client.post(`${this.getBase()}/api/config/llm`, config)
    return response.data
  }

  async getLLMConfig(): Promise<any> {
    const response = await this.client.get(`${this.getBase()}/api/config/llm`)
    return response.data
  }

  async testConnection(url: string): Promise<boolean> {
    try {
      const base = url.replace(/\/+$/, '')
      const resp = await axios.get(`${base}/health`, { timeout: 5000 })
      return resp.status === 200
    } catch {
      return false
    }
  }
}

export const apiClient = new ApiClient()
