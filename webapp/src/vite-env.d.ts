/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MAX_BRIDGE_URL?: string;
  readonly VITE_DEMO_LOGIN?: string;
  readonly VITE_USE_MOCKS?: string;
  readonly VITE_MAX_BOT_USERNAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
