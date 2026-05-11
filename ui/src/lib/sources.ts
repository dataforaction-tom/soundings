import type { SourceRef } from "./types";

// Dedupe by (source_id + retrieved_at minute) per design §4 so the UI
// cites once per source even when a tool invoked an adapter multiple
// times during the request.
export function dedupeSources(sources: SourceRef[]): SourceRef[] {
  const seen = new Map<string, SourceRef>();
  for (const ref of sources) {
    const minute = ref.retrieved_at.slice(0, 16); // 'YYYY-MM-DDTHH:MM'
    const key = `${ref.source_id}|${minute}`;
    if (!seen.has(key)) {
      seen.set(key, ref);
    }
  }
  return [...seen.values()];
}
