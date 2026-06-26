import { describe, it, expect } from "vitest";

// Do NOT mock dom-polyfill — Observable Plot needs the linkedom DOM it installs.
// happy-dom alone doesn't provide document.documentElement in the way Plot expects.
import "../dom-polyfill";
import { PALETTE, renderDistributionChart, renderCompositionChart, renderScatterPlot } from "../chart";

// ---------------------------------------------------------------------------
// renderDistributionChart
// ---------------------------------------------------------------------------

describe("renderDistributionChart", () => {
  it("returns empty string for empty peer_values", () => {
    const result = renderDistributionChart(
      { peer_values: [], focal_value: null, unit: "people", caption: null },
      {},
    );
    expect(result).toBe("");
  });

  it("returns an SVG string for valid input", () => {
    const result = renderDistributionChart(
      {
        peer_values: [100, 200, 300, 400, 500, 150, 250],
        focal_value: 250,
        unit: "people",
        caption: "Test distribution",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("</svg>");
    expect(result.length).toBeGreaterThan(100);
  });

  it("renders histogram bars (rectY + binX)", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
        focal_value: 50,
        unit: "score",
        caption: null,
      },
      {},
    );
    // Plot.rectY with Plot.binX emits <rect> elements for histogram bars.
    const rectCount = (result.match(/<rect/g) ?? []).length;
    expect(rectCount).toBeGreaterThanOrEqual(1);
  });

  it("marks the focal value with a green ruleX line", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      {},
    );
    // The focal rule uses the accent green from PALETTE[0] (#4a7c59).
    expect(result).toContain("#4a7c59");
  });

  it("renders without a focal rule when focal_value is null", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: null,
        unit: "score",
        caption: null,
      },
      {},
    );
    expect(result).toContain("<svg");
  });

  it("includes accessibility <title> and <desc>", () => {
    const result = renderDistributionChart(
      {
        peer_values: [1, 2, 3, 4, 5],
        focal_value: 3,
        unit: "score",
        caption: "Test",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("</title>");
    expect(result).toContain("<desc>");
    expect(result).toContain("</desc>");
  });

  it("respects containerWidth", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      { containerWidth: 600 },
    );
    expect(result).toContain('width="600"');
  });
});

// ---------------------------------------------------------------------------
// renderCompositionChart
// ---------------------------------------------------------------------------

describe("renderCompositionChart", () => {
  it("returns empty string for empty segments", () => {
    const result = renderCompositionChart(
      { title: "Test", segments: [], caption: null },
      {},
    );
    expect(result).toBe("");
  });

  it("returns an SVG string for valid segments", () => {
    const result = renderCompositionChart(
      {
        title: "Income distribution",
        segments: [
          { label: "Under £10k", value: 412 },
          { label: "£10k-£100k", value: 301 },
          { label: "£100k-£1m", value: 198 },
        ],
        caption: "Charity income bands",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("</svg>");
    expect(result.length).toBeGreaterThan(100);
  });

  it("emits one donut path per segment", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [
          { label: "A", value: 50 },
          { label: "B", value: 30 },
          { label: "C", value: 20 },
        ],
        caption: null,
      },
      {},
    );
    // Donut slices are drawn as <path> elements (SVG arc commands).
    const pathCount = (result.match(/<path/g) ?? []).length;
    expect(pathCount).toBeGreaterThanOrEqual(3);
  });

  it("uses PALETTE colours when no explicit colour provided", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50 }, { label: "B", value: 50 }],
        caption: null,
      },
      {},
    );
    // PALETTE[0] is the accent green used for the first segment.
    expect(result).toContain(PALETTE[0]);
  });

  it("respects an explicit segment colour override", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50, colour: "#ff0000" }],
        caption: null,
      },
      {},
    );
    expect(result).toContain("#ff0000");
  });

  it("includes accessibility <title> and <desc>", () => {
    const result = renderCompositionChart(
      {
        title: "Age structure",
        segments: [{ label: "Under 18", value: 22.5 }],
        caption: "Population by age band",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("</title>");
    expect(result).toContain("<desc>");
    expect(result).toContain("</desc>");
  });

  it("respects containerWidth", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50 }, { label: "B", value: 50 }],
        caption: null,
      },
      { containerWidth: 500 },
    );
    expect(result).toContain('width="500"');
  });
});

// ---------------------------------------------------------------------------
// renderScatterPlot
// ---------------------------------------------------------------------------

describe("renderScatterPlot", () => {
  it("returns empty string for empty points", () => {
    const result = renderScatterPlot(
      {
        points: [],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    expect(result).toBe("");
  });

  it("returns an SVG string for valid points", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:B", x_value: 30, y_value: 75, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy (years)",
        caption: "Deprivation vs life expectancy",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("</svg>");
    expect(result.length).toBeGreaterThan(100);
  });

  it("emits one circle per point (peer + focal)", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:B", x_value: 30, y_value: 75, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    // Plot.dot emits one <circle> per point: 2 peers + 1 focal = 3.
    const circleCount = (result.match(/<circle/g) ?? []).length;
    expect(circleCount).toBe(3);
  });

  it("uses navy for peer dots and green for the focal dot", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    // Navy for peers.
    expect(result).toContain("#1a2f4e");
    // Accent green for focal dot.
    expect(result).toContain("#4a7c59");
  });

  it("includes accessibility <title> and <desc>", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: "Test caption",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("</title>");
    expect(result).toContain("<desc>");
    expect(result).toContain("</desc>");
  });

  it("respects containerWidth", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      { containerWidth: 600 },
    );
    expect(result).toContain('width="600"');
  });
});
