// Client behaviour for the AskBox component.
//
// Each example chip fills the question input and submits the form, teaching
// the user what kinds of questions work (the model infers intent from the
// text — there is no explicit mode).
//
// `.ask-box` IS the form element, so init operates on it directly.

export function initAskBox(form: HTMLFormElement): void {
  const chips = form.querySelectorAll<HTMLButtonElement>(".example-chip");
  const qInput = form.querySelector<HTMLInputElement>("input[name='q']");
  if (!qInput) return;

  for (const chip of chips) {
    chip.addEventListener("click", () => {
      qInput.value = chip.dataset.example ?? "";
      form.requestSubmit();
    });
  }
}

export function initAllAskBoxes(root: ParentNode = document): void {
  root
    .querySelectorAll<HTMLFormElement>(".ask-box")
    .forEach(initAskBox);
}

initAllAskBoxes();
