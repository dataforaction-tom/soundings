import { describe, expect, it } from "vitest";
import { domainOf, formatValue, prettyKey, formatContext, formatDirection } from "../src/lib/indicator_display";

describe("prettyKey", () => {
  it("renders a flat key with leading capital", () => {
    expect(prettyKey("population")).toBe("Population");
  });

  it("renders dotted keys as head + colon + dotted tail", () => {
    expect(prettyKey("population.total")).toBe("Population: total");
  });

  it("converts underscores to spaces in the tail", () => {
    expect(prettyKey("population.age_structure.over_65")).toBe(
      "Population: age structure · over 65",
    );
  });
});

describe("formatValue", () => {
  it("returns em-dash for null", () => {
    expect(formatValue(null)).toBe("—");
  });

  it("formats integers with locale separators", () => {
    expect(formatValue(206800)).toBe("206,800");
  });

  it("formats fractions without scientific notation", () => {
    const result = formatValue(0.12345);
    expect(result).not.toContain("e");
    expect(result).not.toContain("E");
    // Should be a readable decimal, not 0.123 (toPrecision(3) old behavior).
    expect(result).toBe("0.123");
  });

  it("formats very small numbers without scientific notation", () => {
    const result = formatValue(0.00000123);
    expect(result).not.toContain("e");
    expect(result).not.toContain("E");
  });
});

describe("formatContext", () => {
  it("formats percentile as pXX", () => {
    expect(formatContext(42, "percentile")).toBe("p42");
  });

  it("formats rank as #N", () => {
    expect(formatContext(150, "rank")).toBe("#150");
  });

  it("returns empty string for null values", () => {
    expect(formatContext(null, "percentile")).toBe("");
    expect(formatContext(null, "rank")).toBe("");
  });

  it("rounds percentile to nearest integer", () => {
    expect(formatContext(42.7, "percentile")).toBe("p43");
    expect(formatContext(42.3, "percentile")).toBe("p42");
  });
});

describe("formatDirection", () => {
  it("returns '↑' for higher_is_better", () => {
    expect(formatDirection("better")).toBe("↑");
  });

  it("returns '↓' for higher_is_worse", () => {
    expect(formatDirection("worse")).toBe("↓");
  });

  it("returns empty string for neutral or null", () => {
    expect(formatDirection("neutral")).toBe("");
    expect(formatDirection(null)).toBe("");
  });
});

describe("domainOf", () => {
  it("returns the prefix segment", () => {
    expect(domainOf("population.total")).toBe("population");
    expect(domainOf("deprivation.imd.score")).toBe("deprivation");
  });

  it("returns the whole key when no dot", () => {
    expect(domainOf("population")).toBe("population");
  });
});
