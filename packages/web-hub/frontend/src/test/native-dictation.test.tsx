// @vitest-environment jsdom

import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { useNativeDictation } from "@/features/chats/use-native-dictation";

const mocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
}));

vi.mock("@/features/chats/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/chats/api")>()),
  getVoiceDictationStatus: mocks.getStatus,
  startVoiceDictation: mocks.start,
  stopVoiceDictation: mocks.stop,
}));

function DictationHarness() {
  const [error, setError] = useState("");
  const [text, setText] = useState("Vorhanden");
  const dictation = useNativeDictation({
    disabled: false,
    onError: setError,
    onText: setText,
    text,
  });

  return (
    <div>
      <button type="button" onClick={() => void dictation.toggle()}>Toggle</button>
      <output data-testid="phase">{dictation.phase}</output>
      <output data-testid="text">{text}</output>
      <output data-testid="window">{dictation.windowId}</output>
      <output data-testid="error">{error}</output>
    </div>
  );
}

describe("native Anti-Gravity dictation", () => {
  it("starts, streams native text and stops cleanly", async () => {
    mocks.start.mockResolvedValue({
      isRecording: true,
      success: true,
      text: "Hallo",
      window: { window_id: "AG-04" },
    });
    mocks.getStatus.mockResolvedValue({
      isRecording: true,
      success: true,
      text: "Hallo Welt",
      window: { window_id: "AG-04" },
    });
    mocks.stop.mockResolvedValue({
      isRecording: false,
      success: true,
      text: "Hallo Welt",
      window: { window_id: "AG-04" },
    });

    const user = userEvent.setup();
    render(<DictationHarness />);

    await user.click(screen.getByRole("button", { name: "Toggle" }));
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("recording"));
    await waitFor(() => expect(screen.getByTestId("text")).toHaveTextContent("Hallo Welt"));
    expect(screen.getByTestId("window")).toHaveTextContent("AG-04");

    await user.click(screen.getByRole("button", { name: "Toggle" }));
    await waitFor(() => expect(screen.getByTestId("phase")).toHaveTextContent("idle"));
    expect(mocks.start).toHaveBeenCalledWith("Vorhanden");
    expect(mocks.stop).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("error")).toBeEmptyDOMElement();
  });
});
