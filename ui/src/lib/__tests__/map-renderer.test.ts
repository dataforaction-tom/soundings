import { describe, it, expect } from "vitest";
import { colourDomain } from "../map-renderer";

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
