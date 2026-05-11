// TypeScript mirror of `server/soundings/contracts/*` and the tool /
// capture endpoint response shapes. Kept in sync by hand per ADR-0005.
// If you change a Pydantic model server-side, update this file in the
// same commit.

export type ConsentLevel = "full" | "minimal" | "none";

export type AskerSector =
  | "charity"
  | "funder"
  | "researcher"
  | "commissioner"
  | "public"
  | "other";

export type CacheStatus = "live" | "cached" | "stale";

export type Confidence = "official" | "modelled" | "experimental";

export interface SourceRef {
  source_id: string;
  source_label: string;
  publisher: string;
  publisher_url: string;
  dataset_url: string;
  retrieved_at: string;
  cache_status: CacheStatus;
  licence: string;
}

export interface IndicatorValue {
  place_id: string;
  indicator: string;
  value: number | null;
  unit: string;
  period: string;
  source: SourceRef;
  methodology_note?: string | null;
  caveats: string[];
  confidence: Confidence;
}

export interface PlaceMatch {
  id: string;
  name: string;
  type: string;
  parent_ids: string[];
  confidence: number;
}

export interface FindPlaceResponse {
  matches: PlaceMatch[];
  sources?: SourceRef[];
}

export interface GetIndicatorsResponse {
  results: IndicatorValue[];
}

export interface PlaceProfile {
  place: {
    id: string;
    name: string;
    type: string;
  };
  indicators: IndicatorValue[];
}

export interface ConsentResponse {
  session_id: string;
  consent_level: ConsentLevel;
  consent_version: string;
  asker_sector: AskerSector | null;
  schema_version: "v1";
}

export interface FeedbackResponse {
  ok: true;
}
