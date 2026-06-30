import { describe, it, expect } from "vitest";
import {
  colourDomain,
  amenityLayerLabel,
  amenityLegendItems,
  hasFiniteValues,
  rankFractions,
} from "../map-renderer";
import { PALETTE } from "../chart";

describe("colourDomain", () => {
  it("returns [min, mid, max] from finite values", () => {
    expect(colourDomain([10, 20, 30])).toEqual([10, 20, 30]);
  });

  it("ignores null/undefined/NaN", () => {
    expect(colourDomain([5, null, 15, undefined, NaN])).toEqual([5, 10, 15]);
  });

  it("falls back to [0, 0.5, 1] when no finite values", () => {
    expect(colourDomain([null, undefined])).toEqual([0, 0.5, 1]);
  });

  it("handles a single value (min === max)", () => {
    expect(colourDomain([7])).toEqual([7, 7, 7]);
  });
});

describe("hasFiniteValues", () => {
  it("is false when no value is a finite number", () => {
    expect(hasFiniteValues([null, undefined, NaN])).toBe(false);
    expect(hasFiniteValues([])).toBe(false);
  });
  it("is true when at least one value is finite", () => {
    expect(hasFiniteValues([null, 3, undefined])).toBe(true);
  });
});

describe("rankFractions", () => {
  it("maps smallest→0 and largest→1, preserving order", () => {
    expect(rankFractions([10, 30, 20])).toEqual([0, 1, 0.5]);
  });
  it("returns null for non-finite entries and spreads the rest", () => {
    expect(rankFractions([5, null, 15, 25])).toEqual([0, null, 0.5, 1]);
  });
  it("gives a single finite value a mid rank", () => {
    expect(rankFractions([null, 42])).toEqual([null, 0.5]);
  });
  it("returns all-null when there are no finite values", () => {
    expect(rankFractions([null, undefined])).toEqual([null, null]);
  });
});

describe("amenityLayerLabel", () => {
  it("humanises an infrastructure count key", () => {
    expect(amenityLayerLabel("infrastructure.food_banks_count")).toBe("Food banks");
    expect(amenityLayerLabel("infrastructure.gp_practices_count")).toBe("Gp practices");
  });
});

describe("amenityLegendItems", () => {
  it("assigns one PALETTE colour per layer", () => {
    const items = amenityLegendItems([
      "infrastructure.food_banks_count",
      "infrastructure.schools_count",
    ]);
    expect(items).toEqual([
      { label: "Food banks", colour: PALETTE[0] },
      { label: "Schools", colour: PALETTE[1] },
    ]);
  });
});
