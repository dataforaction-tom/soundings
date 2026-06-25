import { describe, expect, it } from "vitest";

import "../src/lib/dom-polyfill";

import { renderIncomeBuckets, renderRegistrationTrend } from "../src/lib/chart";
import type { IncomeBucket, RegistrationCohort } from "../src/lib/types";

const BUCKETS: IncomeBucket[] = [
  { label: "£0–10k", lower: 0, upper: 10_000, count: 12 },
  { label: "£10–50k", lower: 10_000, upper: 50_000, count: 34 },
  { label: "£50–100k", lower: 50_000, upper: 100_000, count: 21 },
  { label: "£100k+", lower: 100_000, upper: null, count: 8 },
];

const COHORTS: RegistrationCohort[] = [
  { year: 2019, registered: 10, removed: 2, net: 8 },
  { year: 2020, registered: 15, removed: 3, net: 12 },
  { year: 2021, registered: 20, removed: 5, net: 15 },
  { year: 2022, registered: 18, removed: 4, net: 14 },
];

describe("renderIncomeBuckets", () => {
  it("returns an SVG string", () => {
    const svg = renderIncomeBuckets(BUCKETS);
    expect(svg).toContain("<svg");
    expect(svg).toContain("</svg>");
  });

  it("returns an empty string for no buckets", () => {
    expect(renderIncomeBuckets([])).toBe("");
  });
});

describe("renderIncomeBuckets — responsive sizing", () => {
  it("defaults to the fixed width (480) when no containerWidth", () => {
    const svg = renderIncomeBuckets(BUCKETS);
    expect(svg).toContain('width="480"');
  });

  it("scales to containerWidth when provided", () => {
    const svg = renderIncomeBuckets(BUCKETS, { containerWidth: 320 });
    expect(svg).toContain('width="320"');
  });
});

describe("renderRegistrationTrend", () => {
  it("returns an SVG string", () => {
    const svg = renderRegistrationTrend(COHORTS);
    expect(svg).toContain("<svg");
    expect(svg).toContain("</svg>");
  });

  it("returns an empty string for no cohorts", () => {
    expect(renderRegistrationTrend([])).toBe("");
  });
});

describe("renderRegistrationTrend — responsive sizing", () => {
  it("defaults to the fixed width (480) when no containerWidth", () => {
    const svg = renderRegistrationTrend(COHORTS);
    expect(svg).toContain('width="480"');
  });

  it("scales to containerWidth when provided", () => {
    const svg = renderRegistrationTrend(COHORTS, { containerWidth: 360 });
    expect(svg).toContain('width="360"');
  });
});
