import { useEffect } from 'react'
import { Capacitor } from '@capacitor/core'
import { SplashScreen } from '@capacitor/splash-screen'
import { StatusBar, Style } from '@capacitor/status-bar'
import { App as CapApp } from '@capacitor/app'
import { Keyboard } from '@capacitor/keyboard'
import { Haptics, ImpactStyle } from '@capacitor/haptics'
import { Dialog } from '@capacitor/dialog'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ChatProvider } from './context/ChatContext'
import { AuthPage } from './pages/AuthPage'
import ChatPage from './pages/ChatPage'
import './styles/globals.css'

function NativeInit() {
  const isNative = Capacitor.isNativePlatform()

  useEffect(() => {
    if (isNative) {
      StatusBar.setStyle({ style: Style.Dark })
      StatusBar.setBackgroundColor({ color: '#0f0f1a' })

      SplashScreen.hide({ fadeOutDuration: 300 })

      CapApp.addListener('backButton', () => {
        CapApp.exitApp()
      })

      Keyboard.addListener('keyboardWillShow', () => {
        document.body.classList.add('keyboard-open')
      })
      Keyboard.addListener('keyboardWillHide', () => {
        document.body.classList.remove('keyboard-open')
      })
    }

    return () => {
      if (isNative) {
        CapApp.removeAllListeners()
        Keyboard.removeAllListeners()
      }
    }
  }, [isNative])

  return null
}

window.hapticTap = async () => {
  try {
    await Haptics.impact({ style: ImpactStyle.Light })
  } catch {}
}

window.hapticHeavy = async () => {
  try {
    await Haptics.impact({ style: ImpactStyle.Heavy })
  } catch {}
}

window.nativeAlert = async (title: string, message: string) => {
  if (Capacitor.isNativePlatform()) {
    await Dialog.alert({ title, message })
  } else {
    window.alert(message)
  }
}

window.nativeConfirm = async (title: string, message: string): Promise<boolean> => {
  if (Capacitor.isNativePlatform()) {
    const { value } = await Dialog.confirm({ title, message })
    return value
  }
  return window.confirm(message)
}

function AppContent() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', background: 'var(--bg-primary)' }}>
        <div className="typing-indicator"><span></span><span></span><span></span></div>
      </div>
    )
  }

  if (!user) {
    return <AuthPage />
  }

  return (
    <ChatProvider>
      <ChatPage />
    </ChatProvider>
  )
}

function App() {
  return (
    <AuthProvider>
      <NativeInit />
      <AppContent />
    </AuthProvider>
  )
}

export default App
