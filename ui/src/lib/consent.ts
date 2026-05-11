// Helpers for reading the consent state from the cookie jar (SSR or
// document.cookie at runtime) and choosing what the banner highlights.

import type { AskerSector, ConsentLevel } from "./types";

export const CONSENT_LEVELS: readonly ConsentLevel[] = [
  "full",
  "minimal",
  "none",
] as const;

export const ASKER_SECTORS: readonly AskerSector[] = [
  "charity",
  "funder",
  "researcher",
  "commissioner",
  "public",
  "other",
] as const;

export const DEFAULT_CONSENT_LEVEL: ConsentLevel = "minimal";

export interface ConsentState {
  consentLevel: ConsentLevel;
  askerSector: AskerSector | null;
}

export function readConsentFromCookieString(
  cookieString: string | null | undefined,
): ConsentState {
  const cookies = parseCookieString(cookieString ?? "");
  return {
    consentLevel: parseLevel(cookies.get("soundings_consent")),
    askerSector: parseSector(cookies.get("soundings_sector")),
  };
}

function parseCookieString(input: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const pair of input.split(";")) {
    const trimmed = pair.trim();
    if (!trimmed) continue;
    const eq = trimmed.indexOf("=");
    if (eq < 0) continue;
    const name = trimmed.slice(0, eq);
    const value = decodeURIComponent(trimmed.slice(eq + 1));
    out.set(name, value);
  }
  return out;
}

function parseLevel(value: string | undefined): ConsentLevel {
  if (value && (CONSENT_LEVELS as readonly string[]).includes(value)) {
    return value as ConsentLevel;
  }
  return DEFAULT_CONSENT_LEVEL;
}

function parseSector(value: string | undefined): AskerSector | null {
  if (value && (ASKER_SECTORS as readonly string[]).includes(value)) {
    return value as AskerSector;
  }
  return null;
}
