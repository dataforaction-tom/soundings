// Side-effect-only module: install a minimal DOM on `globalThis` so
// `@observablehq/plot` can run inside Node SSR.
//
// `Plot.plot()` internally calls `document.createElement`,
// `document.createElementNS`, etc. — Node has no native `document`.
// `linkedom` ships a spec-shaped DOM that satisfies Plot's needs without
// bringing the weight of jsdom. Every chart component imports this file
// *before* it imports Plot.
//
// Idempotent — re-importing this module does nothing on subsequent loads.

import { parseHTML } from "linkedom";

interface PolyfillGlobals {
  document?: unknown;
  DocumentFragment?: unknown;
  HTMLElement?: unknown;
  Element?: unknown;
  SVGElement?: unknown;
  Node?: unknown;
  Text?: unknown;
  navigator?: unknown;
}

const target = globalThis as PolyfillGlobals;

if (target.document === undefined) {
  const dom = parseHTML("<!doctype html><html><body></body></html>");
  target.document = dom.document;
  target.DocumentFragment = dom.DocumentFragment;
  target.HTMLElement = dom.HTMLElement;
  target.Element = dom.Element;
  target.SVGElement = dom.SVGElement;
  target.Node = dom.Node;
  target.Text = dom.Text;
  target.navigator = dom.navigator;
}
