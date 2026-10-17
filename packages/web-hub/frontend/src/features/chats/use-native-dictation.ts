import { useCallback, useEffect, useRef, useState } from "react";

import {
  getVoiceDictationStatus,
  startVoiceDictation,
  stopVoiceDictation,
} from "@/features/chats/api";

export type DictationPhase = "idle" | "starting" | "recording" | "stopping";

interface NativeDictationOptions {
  disabled: boolean;
  onError: (message: string) => void;
  onText: (text: string) => void;
  text: string;
}

export function useNativeDictation({ disabled, onError, onText, text }: NativeDictationOptions) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [phase, setPhase] = useState<DictationPhase>("idle");
  const [windowId, setWindowId] = useState("");
  const phaseRef = useRef<DictationPhase>("idle");
  const startedAtRef = useRef(0);
  const textRef = useRef(text);
  const onErrorRef = useRef(onError);
  const onTextRef = useRef(onText);
  const requestActiveRef = useRef(false);

  useEffect(() => { phaseRef.current = phase; }, [phase]);
  useEffect(() => { textRef.current = text; }, [text]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);
  useEffect(() => { onTextRef.current = onText; }, [onText]);

  const reset = useCallback(() => {
    phaseRef.current = "idle";
    setPhase("idle");
    setElapsedSeconds(0);
    setWindowId("");
    startedAtRef.current = 0;
    requestActiveRef.current = false;
  }, []);

  const stop = useCallback(async () => {
    if (phaseRef.current === "idle" || phaseRef.current === "stopping") return;
    phaseRef.current = "stopping";
    setPhase("stopping");
    try {
      const result = await stopVoiceDictation();
      if (typeof result.text === "string") onTextRef.current(result.text);
    } catch (error) {
      onErrorRef.current(error instanceof Error ? error.message : String(error));
    } finally {
      reset();
    }
  }, [reset]);

  const start = useCallback(async () => {
    if (disabled || phaseRef.current !== "idle") return;
    phaseRef.current = "starting";
    setPhase("starting");
    onErrorRef.current("");
    try {
      const result = await startVoiceDictation(textRef.current);
      if (!result.success || !result.isRecording) {
        throw new Error(result.error || "Anti-Gravity hat die Aufnahme nicht gestartet.");
      }
      if (typeof result.text === "string") onTextRef.current(result.text);
      setWindowId(result.window?.window_id || "AG-Diktat");
      startedAtRef.current = Date.now();
      phaseRef.current = "recording";
      setPhase("recording");
    } catch (error) {
      onErrorRef.current(error instanceof Error ? error.message : String(error));
      reset();
    }
  }, [disabled, reset]);

  const toggle = useCallback(async () => {
    if (phaseRef.current === "idle") await start();
    else await stop();
  }, [start, stop]);

  useEffect(() => {
    if (phase !== "recording") return;
    const poll = async () => {
      if (requestActiveRef.current || phaseRef.current !== "recording") return;
      requestActiveRef.current = true;
      try {
        const result = await getVoiceDictationStatus();
        if (typeof result.text === "string") onTextRef.current(result.text);
        if (result.window?.window_id) setWindowId(result.window.window_id);
        if (!result.isRecording) reset();
      } catch (error) {
        onErrorRef.current(error instanceof Error ? error.message : String(error));
        reset();
      } finally {
        requestActiveRef.current = false;
      }
    };
    void poll();
    const pollTimer = window.setInterval(() => void poll(), 700);
    const clockTimer = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAtRef.current) / 1_000)));
    }, 1_000);
    return () => {
      window.clearInterval(pollTimer);
      window.clearInterval(clockTimer);
    };
  }, [phase, reset]);

  useEffect(() => {
    if (disabled && phaseRef.current !== "idle") void stop();
  }, [disabled, stop]);

  useEffect(() => () => {
    if (phaseRef.current !== "idle") void stopVoiceDictation().catch(() => undefined);
  }, []);

  return { elapsedSeconds, phase, start, stop, toggle, windowId };
}
