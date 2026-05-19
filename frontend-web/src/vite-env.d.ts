/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  hapticTap: () => Promise<void>
  hapticHeavy: () => Promise<void>
  nativeAlert: (title: string, message: string) => Promise<void>
  nativeConfirm: (title: string, message: string) => Promise<boolean>
}