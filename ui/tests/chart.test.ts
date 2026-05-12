import { describe, expect, it } from "vitest";

// dom-polyfill side-effect runs first so Plot has a document to mutate.
import "../src/lib/dom-polyfill";

import { renderSparkline } from "../src/lib/chart";

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
    // Plot's `dot` mark emits one <circle> per point; the line + dot pair
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
