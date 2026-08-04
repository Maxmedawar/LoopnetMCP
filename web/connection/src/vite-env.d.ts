/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
  readonly VITE_MCP_ORIGIN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
