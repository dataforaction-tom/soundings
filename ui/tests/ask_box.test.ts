import { beforeEach, describe, expect, it, vi } from "vitest";
import { initAskBox } from "../src/scripts/ask_box";

function buildForm(): HTMLFormElement {
  document.body.innerHTML = `
    <form class="ask-box" method="get" action="/ask">
      <input type="text" name="q" />
      <button type="button" class="example-chip" data-example="Summarise this place">Summarise this place</button>
      <button type="button" class="example-chip" data-example="Where are the food banks?">Where are the food banks?</button>
    </form>`;
  return document.querySelector<HTMLFormElement>(".ask-box")!;
}

describe("initAskBox", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("fills the input and submits when a chip is clicked", () => {
    const form = buildForm();
    const submit = vi.fn();
    form.requestSubmit = submit;

    initAskBox(form);

    const chip = document.querySelectorAll<HTMLButtonElement>(".example-chip")[1]!;
    chip.click();

    const input = form.querySelector<HTMLInputElement>("input[name='q']")!;
    expect(input.value).toBe("Where are the food banks?");
    expect(submit).toHaveBeenCalledOnce();
  });

  it("does not throw when there is no question input", () => {
    document.body.innerHTML = `<form class="ask-box"></form>`;
    const form = document.querySelector<HTMLFormElement>(".ask-box")!;
    expect(() => initAskBox(form)).not.toThrow();
  });
});
