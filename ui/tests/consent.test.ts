import { describe, expect, it } from "vitest";
import {
  ASKER_SECTORS,
  CONSENT_LEVELS,
  DEFAULT_CONSENT_LEVEL,
  readConsentFromCookieString,
} from "../src/lib/consent";

describe("readConsentFromCookieString", () => {
  it("returns the default when no cookies are set", () => {
    expect(readConsentFromCookieString(null)).toEqual({
      consentLevel: DEFAULT_CONSENT_LEVEL,
      askerSector: null,
    });
  });

  it("reads a valid consent + sector pair", () => {
    const state = readConsentFromCookieString(
      "soundings_consent=full; soundings_sector=charity; soundings_session=abc",
    );
    expect(state.consentLevel).toBe("full");
    expect(state.askerSector).toBe("charity");
  });

  it("falls back to default for unknown consent values", () => {
    const state = readConsentFromCookieString("soundings_consent=partial");
    expect(state.consentLevel).toBe(DEFAULT_CONSENT_LEVEL);
  });

  it("clears unknown sector values to null", () => {
    const state = readConsentFromCookieString(
      "soundings_consent=full; soundings_sector=philanthropist",
    );
    expect(state.askerSector).toBeNull();
  });
});

describe("consent vocabularies", () => {
  it("matches the server-side vocabularies", () => {
    expect(CONSENT_LEVELS).toEqual(["full", "minimal", "none"]);
    expect(ASKER_SECTORS).toEqual([
      "charity",
      "funder",
      "researcher",
      "commissioner",
      "public",
      "other",
    ]);
  });
});
