import { describe, expect, it } from "vitest";
import { parseSSEStream, type AskEvent } from "../src/lib/answer_stream";

describe("parseSSEStream", () => {
  it("parses a status event", () => {
    const raw = 'data: {"type":"status","message":"Looking up place…"}\n\n';
    const events = parseSSEStream(raw);
    expect(events).toEqual([
      { type: "status", message: "Looking up place…" },
    ]);
  });

  it("parses a block event", () => {
    const raw =
      'data: {"type":"block","block":{"type":"text","text":"Hello"}}\n\n';
    const events = parseSSEStream(raw);
    expect(events).toHaveLength(1);
    expect(events[0]!.type).toBe("block");
    const block = (events[0] as Extract<AskEvent, { type: "block" }>).block;
    expect(block.type).toBe("text");
    expect(block.text).toBe("Hello");
  });

  it("parses a done event", () => {
    const raw = 'data: {"type":"done"}\n\n';
    const events = parseSSEStream(raw);
    expect(events).toEqual([{ type: "done" }]);
  });

  it("parses an error event", () => {
    const raw =
      'data: {"type":"error","message":"Place not found"}\n\n';
    const events = parseSSEStream(raw);
    expect(events).toEqual([{ type: "error", message: "Place not found" }]);
  });

  it("handles multiple events in one stream", () => {
    const raw = [
      'data: {"type":"status","message":"Thinking…"}',
      "",
      'data: {"type":"block","block":{"type":"text","text":"Answer"}}',
      "",
      'data: {"type":"sources","sources":[{"source_id":"ons","source_label":"ONS"}]}',
      "",
      'data: {"type":"done"}',
      "",
    ].join("\n");
    const events = parseSSEStream(raw);
    expect(events).toHaveLength(4);
    expect(events[0]).toEqual({ type: "status", message: "Thinking…" });
    expect(events[1]!.type).toBe("block");
    expect(events[2]!.type).toBe("sources");
    expect(events[3]).toEqual({ type: "done" });
  });

  it("skips empty lines and non-data lines", () => {
    const raw = [
      ": this is a comment",
      "",
      'data: {"type":"done"}',
      "",
      "event: ping",
      "id: 42",
      "",
    ].join("\n");
    const events = parseSSEStream(raw);
    expect(events).toEqual([{ type: "done" }]);
  });

  it("skips malformed JSON data lines", () => {
    const raw = [
      "data: {not valid json",
      "",
      'data: {"type":"done"}',
      "",
    ].join("\n");
    const events = parseSSEStream(raw);
    expect(events).toEqual([{ type: "done" }]);
  });
});
