import { defineConfig } from "astro/config";
import node from "@astrojs/node";

// SSR everything in v1. No `getStaticPaths` pre-rendering — covered in
// docs/plans/2026-05-11-soundings-v1-phase-2-plan.md as a Phase 6 polish
// task. Standalone Node adapter so `node ./dist/server/entry.mjs` boots
// the production server.
export default defineConfig({
  output: "server",
  adapter: node({ mode: "standalone" }),
  server: {
    host: "0.0.0.0",
    port: 4321,
  },
});
