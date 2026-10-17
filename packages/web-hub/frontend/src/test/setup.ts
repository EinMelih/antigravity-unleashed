import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

Object.defineProperty(window, "scrollTo", {
  configurable: true,
  value: () => undefined,
  writable: true,
});

Object.defineProperties(HTMLElement.prototype, {
  hasPointerCapture: {
    configurable: true,
    value: () => false,
  },
  releasePointerCapture: {
    configurable: true,
    value: () => undefined,
  },
  setPointerCapture: {
    configurable: true,
    value: () => undefined,
  },
});

Object.defineProperty(Element.prototype, "scrollIntoView", {
  configurable: true,
  value: () => undefined,
  writable: true,
});

afterEach(() => {
  cleanup();
});
