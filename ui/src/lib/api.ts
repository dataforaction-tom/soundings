// Thin HTTP client wrapping the Soundings /v1 surface.
//
// Reads `SOUNDINGS_API_BASE` from `import.meta.env` so the same code runs
// against Docker Compose (http://server:8000) and local dev
// (http://localhost:8000). `credentials: "include"` makes the session +
// consent cookies round-trip on UI ↔ API calls.

import type {
  ConsentLevel,
  ConsentResponse,
  FeedbackResponse,
  FindPlaceResponse,
  GetIndicatorsResponse,
  PlaceProfile,
} from "./types";

const DEFAULT_BASE = "http://localhost:8000";

export function apiBase(): string {
  const fromEnv = import.meta.env.SOUNDINGS_API_BASE;
  return fromEnv && fromEnv.length > 0 ? fromEnv : DEFAULT_BASE;
}

interface RequestOptions {
  cookieHeader?: string;
}

async function postJSON<T>(
  path: string,
  body: unknown,
  opts: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  // In SSR the browser cookie jar isn't available — the page must
  // forward Astro.cookies via this header. In the browser, leaving it
  // unset means the fetch uses the document's cookies thanks to
  // `credentials: include`.
  if (opts.cookieHeader) {
    headers["Cookie"] = opts.cookieHeader;
  }
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`${path} ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export async function findPlace(
  query: string,
  opts: { nlQuestion?: string; cookieHeader?: string } = {},
): Promise<FindPlaceResponse> {
  const body: Record<string, unknown> = { query };
  if (opts.nlQuestion) {
    body.nl_question = opts.nlQuestion;
  }
  return postJSON<FindPlaceResponse>("/v1/tools/find_place", body, {
    cookieHeader: opts.cookieHeader,
  });
}

export async function getPlaceProfile(
  placeId: string,
  include: string[] = ["population", "deprivation"],
  opts: { cookieHeader?: string } = {},
): Promise<PlaceProfile> {
  return postJSON<PlaceProfile>(
    "/v1/tools/get_place_profile",
    { place_id: placeId, include },
    opts,
  );
}

export async function getIndicators(
  placeId: string,
  indicators: string[],
  opts: { cookieHeader?: string } = {},
): Promise<GetIndicatorsResponse> {
  return postJSON<GetIndicatorsResponse>(
    "/v1/tools/get_indicators",
    { place_id: placeId, indicators },
    opts,
  );
}

export async function postConsent(
  consentLevel: ConsentLevel,
  opts: { askerSector?: string | null; cookieHeader?: string } = {},
): Promise<ConsentResponse> {
  const body: Record<string, unknown> = { consent_level: consentLevel };
  if (opts.askerSector !== undefined) {
    body.asker_sector = opts.askerSector;
  }
  return postJSON<ConsentResponse>("/v1/capture/consent", body, {
    cookieHeader: opts.cookieHeader,
  });
}

export async function postFeedback(
  questionRecordId: string,
  markedUseful: boolean,
  opts: { cookieHeader?: string } = {},
): Promise<FeedbackResponse> {
  return postJSON<FeedbackResponse>(
    "/v1/capture/feedback",
    { question_record_id: questionRecordId, marked_useful: markedUseful },
    opts,
  );
}
