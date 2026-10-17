"""Normalize only models actually reported by the native model selector."""

import re


def model_rows(native_rows):
    result = []
    seen = set()
    for row in native_rows:
        label = str(row.get("label", "")).strip()
        if not label:
            continue
        match = re.search(r"\s*(?:\((low|medium|high)\)|(low|medium|high))\s*$", label, re.I)
        effort = str(row.get("reasoning_effort") or ((match.group(1) or match.group(2)).lower() if match else ""))
        base = label[:match.start()].strip() if match else re.sub(r"\s*\(Thinking\)\s*$", "", label, flags=re.I)
        base_id = re.sub(r"[^a-z0-9.]+", "-", base.lower()).strip("-")
        model_id = base_id + ("-" + effort if effort else "")
        if model_id in seen:
            continue
        seen.add(model_id)
        owner = "google" if label.startswith("Gemini") else "anthropic" if label.startswith("Claude") else "openai" if label.startswith(("GPT", "o1", "o3")) else "native"
        result.append({"id": model_id, "object": "model", "created": 0, "owned_by": owner, "description": label, "native_name": label, "base_model_id": base_id, "reasoning_effort": effort or None, "thinking": bool(effort or re.search(r"thinking", label, re.I)), "source": "native"})
    return result


def resolve_model(rows, requested, reasoning_effort, current):
    if reasoning_effort is not None and reasoning_effort not in {"low", "medium", "high"}:
        raise ValueError("reasoning_effort must be one of the native low, medium or high values.")
    if requested is not None and not isinstance(requested, str):
        raise ValueError("model must be a string.")
    name = str(requested or current or "").strip()
    if name.lower() in {"default", "antigravity"}:
        name = current
    candidates = [row for row in rows if name.casefold() in {row['id'].casefold(), row['native_name'].casefold(), row['base_model_id'].casefold()}]
    if reasoning_effort:
        candidates = [row for row in candidates if row.get('reasoning_effort') == reasoning_effort]
    if len(candidates) > 1:
        exact = [row for row in candidates if row['native_name'].casefold() == current.casefold()]
        candidates = exact if exact else candidates
    if len(candidates) != 1:
        raise ValueError("Requested model/reasoning setting is unavailable or ambiguous in the API profile. Read GET /v1/models.")
    return candidates[0]
