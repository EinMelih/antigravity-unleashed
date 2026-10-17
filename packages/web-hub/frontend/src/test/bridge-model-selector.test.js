// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

const bridgeSource = readFileSync(path.resolve(process.cwd(), "../src/bridge.js"), "utf8");

function makeVisible(element) {
  Object.defineProperty(element, "offsetParent", {
    configurable: true,
    value: document.body,
  });
  element.getBoundingClientRect = () => ({
    bottom: 32,
    height: 24,
    left: 0,
    right: 160,
    toJSON: () => ({}),
    top: 8,
    width: 160,
    x: 0,
    y: 8,
  });
}

describe("Anti-Gravity bridge model selection", () => {
  afterEach(() => {
    document.body.replaceChildren();
    delete window.__agBridge;
  });

  it("activates a role button model option and verifies the selected label", async () => {
    const selector = document.createElement("button");
    selector.setAttribute("aria-label", "Select model, current: Gemini 3.6 Flash (High)");
    makeVisible(selector);

    const option = document.createElement("div");
    option.setAttribute("role", "button");
    option.tabIndex = 0;
    option.textContent = "Claude Sonnet 4.6 (Thinking)";
    makeVisible(option);
    option.addEventListener("click", () => {
      selector.setAttribute("aria-label", "Select model, current: Claude Sonnet 4.6 (Thinking)");
    });

    document.body.append(selector, option);
    window.eval(bridgeSource);

    await expect(window.__agBridge.selectModel("Claude Sonnet 4.6 (Thinking)")).resolves.toBe(true);
    expect(selector).toHaveAttribute(
      "aria-label",
      "Select model, current: Claude Sonnet 4.6 (Thinking)",
    );
  });

  it("opens a grouped Gemini effort menu before selecting Medium", async () => {
    const selector = document.createElement("button");
    selector.dataset.testid = "model-selector-trigger";
    selector.setAttribute("aria-label", "Select model, current: Gemini 3.6 Flash High");
    makeVisible(selector);

    const groupItem = document.createElement("div");
    groupItem.setAttribute("role", "menuitem");
    makeVisible(groupItem);
    const groupLabel = document.createElement("span");
    groupLabel.dataset.testid = "model-selector-effort-group";
    groupLabel.dataset.modelBase = "Gemini 3.6 Flash";
    groupLabel.textContent = "Gemini 3.6 Flash High";
    groupItem.append(groupLabel);

    groupItem.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" || document.querySelector("[data-effort='medium']")) return;
      const option = document.createElement("div");
      option.setAttribute("role", "menuitemradio");
      makeVisible(option);
      const optionLabel = document.createElement("span");
      optionLabel.dataset.testid = "model-selector-effort-option";
      optionLabel.dataset.effort = "medium";
      optionLabel.textContent = "Medium";
      makeVisible(optionLabel);
      option.append(optionLabel);
      option.addEventListener("click", () => {
        selector.setAttribute("aria-label", "Select model, current: Gemini 3.6 Flash Medium");
      });
      document.body.append(option);
    });

    document.body.append(selector, groupItem);
    window.eval(bridgeSource);

    await expect(window.__agBridge.selectModel("Gemini 3.6 Flash (Medium)")).resolves.toBe(true);
    expect(selector).toHaveAttribute(
      "aria-label",
      "Select model, current: Gemini 3.6 Flash Medium",
    );
  });
});
