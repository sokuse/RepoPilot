/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ENABLE_DEVELOPER_LAB?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
