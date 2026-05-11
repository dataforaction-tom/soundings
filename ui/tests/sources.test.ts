import { describe, expect, it } from "vitest";
import { dedupeSources } from "../src/lib/sources";
import type { SourceRef } from "../src/lib/types";

function makeRef(overrides: Partial<SourceRef> = {}): SourceRef {
  return {
    source_id: "ons.census2021",
    source_label: "ONS Census 2021",
    publisher: "Office for National Statistics",
    publisher_url: "https://example.org",
    dataset_url: "https://example.org/dataset",
    retrieved_at: "2026-05-11T08:00:00Z",
    cache_status: "cached",
    licence: "OGL-UK-3.0",
    ...overrides,
  };
}

describe("dedupeSources", () => {
  it("keeps a single SourceRef untouched", () => {
    const out = dedupeSources([makeRef()]);
    expect(out).toHaveLength(1);
  });

  it("collapses two identical-minute refs to one", () => {
    const out = dedupeSources([
      makeRef({ retrieved_at: "2026-05-11T08:00:01Z" }),
      makeRef({ retrieved_at: "2026-05-11T08:00:59Z" }),
    ]);
    expect(out).toHaveLength(1);
  });

  it("keeps refs that differ on minute", () => {
    const out = dedupeSources([
      makeRef({ retrieved_at: "2026-05-11T08:00:00Z" }),
      makeRef({ retrieved_at: "2026-05-11T08:01:00Z" }),
    ]);
    expect(out).toHaveLength(2);
  });

  it("keeps refs that differ on source_id", () => {
    const out = dedupeSources([
      makeRef({ source_id: "ons.census2021" }),
      makeRef({ source_id: "ons.mid_year_estimates" }),
    ]);
    expect(out).toHaveLength(2);
  });

  it("returns an empty list for empty input", () => {
    expect(dedupeSources([])).toEqual([]);
  });
});
