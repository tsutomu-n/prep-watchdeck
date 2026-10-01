import type { CDPSession, Locator, Page } from "@playwright/test";

export type BrowserImeEvent = {
  type: string;
  data: string | null;
  isTrusted: boolean;
  isComposing: boolean | null;
  inputType: string | null;
  value: string;
  selectionStart: number | null;
  selectionEnd: number | null;
};

type ObservedInput = (HTMLInputElement | HTMLTextAreaElement) & {
  __browserImeEvents?: BrowserImeEvent[];
};

// Exercise Chromium's editing pipeline. This does not exercise an OS IME,
// candidate window, physical keyboard, or mobile software keyboard.
// Chrome 153 reports trusted preedit/input events but untrusted compositionend
// for CDP commit/cancel; retain each flag in the evidence without rewriting it.
export async function browserIme(page: Page, input: Locator) {
  const session: CDPSession = await page.context().newCDPSession(page);
  await input.evaluate((element) => {
    const target = element as ObservedInput;
    target.__browserImeEvents = [];
    for (const type of ["compositionstart", "compositionupdate", "compositionend", "beforeinput", "input"]) {
      target.addEventListener(type, (event) => {
        const inputEvent = event as InputEvent;
        target.__browserImeEvents!.push({
          type: event.type,
          data: inputEvent.data ?? null,
          isTrusted: event.isTrusted,
          isComposing: typeof inputEvent.isComposing === "boolean" ? inputEvent.isComposing : null,
          inputType: inputEvent.inputType ?? null,
          value: target.value,
          selectionStart: target.selectionStart,
          selectionEnd: target.selectionEnd
        });
      });
    }
  });

  return {
    async compose(text: string) {
      await session.send("Input.imeSetComposition", {
        text, selectionStart: text.length, selectionEnd: text.length
      });
    },
    async commit(text: string) {
      await session.send("Input.insertText", { text });
    },
    async cancel() {
      await session.send("Input.imeSetComposition", {
        text: "", selectionStart: 0, selectionEnd: 0
      });
    },
    async events(): Promise<BrowserImeEvent[]> {
      return await input.evaluate((element) => (element as ObservedInput).__browserImeEvents ?? []);
    },
    async close() {
      await session.detach();
    }
  };
}
