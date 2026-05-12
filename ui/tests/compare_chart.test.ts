import { describe, expect, it } from "vitest";

import "../src/lib/dom-polyfill";

import { renderCompareBars } from "../src/lib/chart";
import type { Comparison } from "../src/lib/types";

function comparison(values: { place_id: string; value: number; percentile?: number }[]): Comparison {
  return {
    indicator: "test.indicator",
    unit: "value",
    period: "2024",
    values: values.map((v) => ({
      place_id: v.place_id,
      value: v.value,
      rank: null,
      percentile: v.percentile ?? null,
    })),
    source: {
      source_id: "test",
      source_label: "test",
      publisher: "test",
      publisher_url: "",
      dataset_url: "",
      retrieved_at: new Date().toISOString(),
      cache_status: "cached",
      licence: "CC0",
    },
    caveats: [],
  };
}

describe("renderCompareBars", () => {
  it("emits one rect per highlighted place", () => {
    const svg = renderCompareBars(
      comparison([
        { place_id: "ltla24:A", value: 100 },
        { place_id: "ltla24:B", value: 200 },
        { place_id: "ltla24:C", value: 150 },
      ]),
    );
    expect(svg).toContain("<svg");
    expect(svg).toContain("</svg>");
    // Plot.barY emits one <rect> per category.
    const rectCount = (svg.match(/<rect/g) ?? []).length;
    expect(rectCount).toBeGreaterThanOrEqual(3);
  });

  it("skips null values without dropping the SVG", () => {
    const svg = renderCompareBars({
      indicator: "test.indicator",
      unit: "value",
      period: "2024",
      values: [
        { place_id: "a", value: null, rank: null, percentile: null },
        { place_id: "b", value: 50, rank: null, percentile: null },
      ],
      source: {
        source_id: "test",
        source_label: "test",
        publisher: "test",
        publisher_url: "",
        dataset_url: "",
        retrieved_at: new Date().toISOString(),
        cache_status: "cached",
        licence: "CC0",
      },
      caveats: [],
    });
    expect(svg).toContain("<svg");
  });

  it("returns empty string when no values have data", () => {
    const svg = renderCompareBars({
      indicator: "test.indicator",
      unit: "value",
      period: "2024",
      values: [
        { place_id: "a", value: null, rank: null, percentile: null },
        { place_id: "b", value: null, rank: null, percentile: null },
      ],
      source: {
        source_id: "test",
        source_label: "test",
        publisher: "test",
        publisher_url: "",
        dataset_url: "",
        retrieved_at: new Date().toISOString(),
        cache_status: "cached",
        licence: "CC0",
      },
      caveats: [],
    });
    expect(svg).toBe("");
  });
});
