import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiBase,
  findPlace,
  getPlaceProfile,
  postConsent,
  postFeedback,
} from "../src/lib/api";

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(response: object, init: ResponseInit = { status: 200 }) {
  const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), init));
  vi.stubGlobal("fetch", spy);
  return spy;
}

describe("apiBase()", () => {
  it("falls back to localhost when env is unset", () => {
    expect(apiBase()).toMatch(/localhost:8000/);
  });
});

describe("findPlace", () => {
  it("POSTs to /v1/tools/find_place with the right body and credentials", async () => {
    const spy = mockFetch({ matches: [], sources: [] });

    await findPlace("Stockton");

    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/tools/find_place");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body as string)).toEqual({ query: "Stockton" });
  });

  it("attaches nl_question when supplied", async () => {
    const spy = mockFetch({ matches: [] });
    await findPlace("Stockton", { nlQuestion: "what is the population?" });
    const init = spy.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      query: "Stockton",
      nl_question: "what is the population?",
    });
  });

  it("throws on non-2xx", async () => {
    mockFetch({}, { status: 500, statusText: "boom" });
    await expect(findPlace("x")).rejects.toThrow(/500/);
  });
});

describe("getPlaceProfile", () => {
  it("posts the canonical body to /v1/tools/get_place_profile", async () => {
    const spy = mockFetch({
      place: { id: "ltla24:E06000004", name: "Stockton-on-Tees", type: "ltla24" },
      indicators: [],
    });
    await getPlaceProfile("ltla24:E06000004", ["population"]);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/tools/get_place_profile");
    expect(JSON.parse(init.body as string)).toEqual({
      place_id: "ltla24:E06000004",
      include: ["population"],
    });
  });
});

describe("postConsent", () => {
  it("posts the consent payload with optional sector", async () => {
    const spy = mockFetch({
      session_id: "00000000-0000-0000-0000-000000000000",
      consent_level: "full",
      consent_version: "v1.0",
      asker_sector: "charity",
      schema_version: "v1",
    });
    await postConsent("full", { askerSector: "charity" });
    const init = spy.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      consent_level: "full",
      asker_sector: "charity",
    });
  });
});

describe("postFeedback", () => {
  it("posts the marked_useful payload", async () => {
    const spy = mockFetch({ ok: true });
    await postFeedback("00000000-0000-0000-0000-000000000000", true);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/capture/feedback");
    expect(JSON.parse(init.body as string)).toEqual({
      question_record_id: "00000000-0000-0000-0000-000000000000",
      marked_useful: true,
    });
  });
});
