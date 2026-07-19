/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_YUIZAKI_API_ORIGIN?: string
  readonly VITE_YUIZAKI_CONTROL_ORIGIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
