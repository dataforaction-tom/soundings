/// <reference path="../.astro/types.d.ts" />

interface ImportMetaEnv {
  readonly SOUNDINGS_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
