import { describe, expect, it } from "vitest";

// dom-polyfill side-effect runs first so Plot has a document to mutate.
import "../src/lib/dom-polyfill";

import { PALETTE, renderSparkline } from "../src/lib/chart";

const POINTS = [
  { period: "2020", value: 100 },
  { period: "2021", value: 120 },
  { period: "2022", value: 110 },
  { period: "2023", value: 130 },
  { period: "2024", value: 145 },
];

describe("PALETTE", () => {
  it("exports a 6-colour Good Ship palette", () => {
    expect(PALETTE).toBeInstanceOf(Array);
    expect(PALETTE).toHaveLength(6);
  });

  it("contains the aligned CSS-variable colours in order", () => {
    expect(PALETTE).toEqual([
      "#4a7c59", // green  (--color-accent)
      "#1a2f4e", // navy   (--color-primary)
      "#8b6f47", // brown
      "#6b7280", // gray   (--color-muted)
      "#9c6644", // rust
      "#365314", // dark green
    ]);
  });
});

describe("renderSparkline", () => {
  it("returns an SVG string with one shape per data point", () => {
    const svg = renderSparkline(POINTS);

    expect(svg).toContain("<svg");
    expect(svg).toContain("</svg>");
    // Plot's `dot` Mark emits one <circle> per point; the line + dot pair
    // is the canonical sparkline shape. Count circles as the data signal.
    const circleCount = (svg.match(/<circle/g) ?? []).length;
    expect(circleCount).toBe(5);
  });

  it("ignores null values (revised gaps) without throwing", () => {
    const svg = renderSparkline([
      { period: "2020", value: 100 },
      { period: "2021", value: null },
      { period: "2022", value: 110 },
    ]);
    expect(svg).toContain("<svg");
    // Only two non-null points → two circles.
    const circleCount = (svg.match(/<circle/g) ?? []).length;
    expect(circleCount).toBe(2);
  });

  it("returns an empty string for an empty series", () => {
    expect(renderSparkline([])).toBe("");
  });
});

describe("renderSparkline — responsive sizing", () => {
  it("defaults to the fixed width (240) when no containerWidth", () => {
    const svg = renderSparkline(POINTS);
    // Plot emits width as an attribute on the root <svg>.
    expect(svg).toContain('width="240"');
  });

  it("scales to containerWidth when provided", () => {
    const svg = renderSparkline(POINTS, { containerWidth: 400 });
    expect(svg).toContain('width="400"');
  });

  it("containerWidth does not alter height", () => {
    const svg = renderSparkline(POINTS, { containerWidth: 400 });
    expect(svg).toContain('height="64"');
  });
});
