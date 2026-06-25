import { describe, expect, it } from "vitest";

// dom-polyfill side-effect runs first so Plot has a document to mutate.
import "../src/lib/dom-polyfill";

import { PALETTE, renderSparkline } from "../src/lib/chart";

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
    const svg = renderSparkline([
      { period: "2020", value: 100 },
      { period: "2021", value: 120 },
      { period: "2022", value: 110 },
      { period: "2023", value: 130 },
      { period: "2024", value: 145 },
    ]);

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
