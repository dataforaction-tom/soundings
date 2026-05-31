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
  // Directionality from catalogue.indicator.higher_is — drives the UI's
  // good/bad framing on the benchmark badge.
  higher_is?: "better" | "worse" | "neutral" | null;
  // Percentile of this value against peer places of the same type,
  // excluding self. Populated when the indicator's peer universe is
  // loaded in data.indicator_value.
  benchmark_percentile?: number | null;
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

// compare_places (spec §4.4 / Phase 3 Block G) ------------------------------

export type ComparisonBasis = "percentile" | "rank" | "absolute" | "rate";

export interface ComparisonValue {
  place_id: string;
  value: number | null;
  rank?: number | null;
  percentile?: number | null;
}

export interface Comparison {
  indicator: string;
  unit: string;
  period: string;
  values: ComparisonValue[];
  source: SourceRef;
  methodology_note?: string | null;
  caveats: string[];
}

export interface ComparePlacesResponse {
  results: Comparison[];
  sources?: SourceRef[];
  caveats?: string[];
  partial?: boolean;
}

// get_trend (spec §4.5 / Phase 3 Block H) -----------------------------------

export interface TrendPoint {
  period: string;
  value: number | null;
  revised?: boolean;
}

export interface Trend {
  place_id: string;
  indicator: string;
  unit: string;
  points: TrendPoint[];
  source: SourceRef;
  breaks_in_series?: string[];
}

export interface GetTrendResponse {
  trend: Trend | null;
  sources?: SourceRef[];
  caveats?: string[];
  partial?: boolean;
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

// find_organisations_in_place (spec §4.6 / Phase 4 Block D) ------------------------

export interface GrantRef {
  funder: string;
  amount: number;
  currency: string;
  date: string;
  purpose: string | null;
  source: SourceRef;
}

export interface OrganisationRef {
  id: string;
  name: string;
  classification: string[];
  registered_address_place_id: string | null;
  operates_in_place_ids: string[];
  recent_grants: GrantRef[];
  source: SourceRef;
  methodology_note: string | null;
}

export interface FindOrganisationsInPlaceResponse {
  organisations: OrganisationRef[];
  sources: SourceRef[];
  caveats: string[];
  partial: boolean;
}
