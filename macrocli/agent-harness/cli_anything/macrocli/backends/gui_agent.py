"""GUIAgentBackend — execute a macro step by letting a vision model
(Gemini or Claude) look at the screen and decide what to do.

This backend is used for steps that cannot be expressed as fixed
coordinates or hotkeys because the interface state is unpredictable.
The macro author provides:
  - description:           what needs to be accomplished in this step
  - end_state_description: text description of the desired end state
  - end_state_snapshot:    screenshot of the desired end state (taken
                           by the macro author at recording time)

At runtime the backend:
  1. Takes a screenshot of the current screen
  2. Sends current screenshot + end_state_snapshot + description to the model
  3. Model returns the next action (click x,y / type text / hotkey)
  4. Executes the action
  5. Takes another screenshot
  6. Asks model: "have we reached the end state?"
  7. Loops until end state reached or max_steps exceeded

Supported models:
  - gemini-1.5-flash (default, fastest)
  - gemini-1.5-pro
  - gemini-2.0-flash

Example YAML step:

    - id: select_png_format
      backend: gui_agent
      action: instruct
      params:
        description: >
          The export dialog is open. Find the Format dropdown and
          select PNG. Then ensure Resolution shows 300.
        end_state_description: >
          Format dropdown shows PNG, Resolution input shows 300.
        end_state_snapshot: snapshots/step_003_end_state.png
        max_steps: 8
        model: gemini-1.5-flash
        api_key: ${GEMINI_API_KEY}
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional

from cli_anything.macrocli.backends.base import Backend, BackendContext, StepResult
from cli_anything.macrocli.core.macro_model import MacroStep, substitute

# ── Strict action space prompt ────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a GUI automation agent. You will be shown:
1. A screenshot of the CURRENT screen state
2. A screenshot of the TARGET end state
3. A description of what needs to be accomplished

Your job is to figure out what single action to take next to move
from the current state toward the target state.

OUTPUT FORMAT: Respond with ONLY a JSON object, one of:

  {"action": "click", "x": <int>, "y": <int>, "button": "left"}
  {"action": "double_click", "x": <int>, "y": <int>}
  {"action": "right_click", "x": <int>, "y": <int>}
  {"action": "type", "text": "<string>"}
  {"action": "hotkey", "keys": "<key1+key2+...>"}
  {"action": "scroll", "x": <int>, "y": <int>, "dy": <int>}
  {"action": "done"}

Use {"action": "done"} ONLY when the current state matches the target state.

RULES:
- Output RAW JSON ONLY. No markdown, no explanation.
- Use pixel coordinates from the CURRENT screenshot.
- Prefer clicking on visible labeled controls over guessing coordinates.
- If the target state is already achieved, output {"action": "done"}.
- Never output any action not listed above.
"""

_CHECK_PROMPT = """\
Compare these two screenshots:
1. CURRENT state
2. TARGET end state

Has the current state reached the target end state?
Answer with ONLY: {"reached": true} or {"reached": false, "reason": "<brief reason>"}
"""


# ── Image helpers ─────────────────────────────────────────────────────────────

def _screenshot_b64() -> str:
    """Take a screenshot and return as base64 PNG string."""
    try:
        import mss
        from PIL import Image
        import io
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        raise ImportError("mss and Pillow required: pip install mss Pillow")


def _file_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ── Action executor ───────────────────────────────────────────────────────────

def _execute_action(action_dict: dict, context: BackendContext) -> None:
    """Execute a single action returned by the model."""
    from cli_anything.macrocli.backends.visual_anchor import (
        _mouse_click, _mouse_drag, _require_pynput
    )

    action = action_dict.get("action", "")

    if action == "click":
        x, y = int(action_dict["x"]), int(action_dict["y"])
        _mouse_click(x, y, button=action_dict.get("button", "left"))

    elif action == "double_click":
        x, y = int(action_dict["x"]), int(action_dict["y"])
        _mouse_click(x, y, double=True)

    elif action == "right_click":
        x, y = int(action_dict["x"]), int(action_dict["y"])
        _mouse_click(x, y, button="right")

    elif action == "type":
        text = action_dict.get("text", "")
        _, keyboard_mod = _require_pynput()
        ctrl = keyboard_mod.Controller()
        for char in text:
            ctrl.press(char)
            ctrl.release(char)
            time.sleep(0.03)

    elif action == "hotkey":
        keys_str = action_dict.get("keys", "")
        _, keyboard_mod = _require_pynput()
        Key = keyboard_mod.Key
        ctrl = keyboard_mod.Controller()
        _KEY_MAP = {
            "ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt,
            "enter": Key.enter, "tab": Key.tab, "esc": Key.esc,
            "escape": Key.esc, "space": Key.space, "backspace": Key.backspace,
        }
        keys = [_KEY_MAP.get(k.lower(), k) for k in keys_str.split("+")]
        for k in keys:
            ctrl.press(k)
        for k in reversed(keys):
            ctrl.release(k)

    elif action == "scroll":
        x, y = int(action_dict["x"]), int(action_dict["y"])
        dy = int(action_dict.get("dy", -3))
        mouse_mod, _ = _require_pynput()
        ctrl = mouse_mod.Controller()
        ctrl.position = (x, y)
        ctrl.scroll(0, dy)

    elif action == "done":
        pass  # caller checks for done

    else:
        raise ValueError(f"GUIAgentBackend: unknown action '{action}'")


# ── Backend ───────────────────────────────────────────────────────────────────

class GUIAgentBackend(Backend):
    """Execute GUI steps using a vision model (Gemini) to decide actions."""

    name = "gui_agent"
    priority = 60  # between semantic_ui(50) and file_transform(70)

    def execute(
        self, step: MacroStep, params: dict, context: BackendContext
    ) -> StepResult:
        t0 = time.time()
        p = substitute(step.params, params)

        if context.dry_run:
            return StepResult(
                success=True,
                output={"dry_run": True, "action": step.action},
                backend_used=self.name,
                duration_ms=(time.time() - t0) * 1000,
            )

        if step.action != "instruct":
            return StepResult(
                success=False,
                error=f"GUIAgentBackend: unknown action '{step.action}'. "
                      "Only 'instruct' is supported.",
                backend_used=self.name,
                duration_ms=(time.time() - t0) * 1000,
            )

        return self._instruct(p, context, t0)

    def is_available(self) -> bool:
        try:
            import google.generativeai  # noqa: F401
            import mss  # noqa: F401
            return True
        except ImportError:
            return False

    def _instruct(
        self, p: dict, context: BackendContext, t0: float
    ) -> StepResult:
        description: str = p.get("description", "")
        end_state_desc: str = p.get("end_state_description", "")
        snapshot_path: str = p.get("end_state_snapshot", "")
        max_steps: int = int(p.get("max_steps", 8))
        model_name: str = p.get("model", "gemini-1.5-flash")
        api_key: str = p.get("api_key", os.environ.get("GEMINI_API_KEY", ""))

        if not api_key:
            return StepResult(
                success=False,
                error="GUIAgentBackend: api_key required. "
                      "Pass via params or set GEMINI_API_KEY env var.",
                backend_used=self.name,
                duration_ms=(time.time() - t0) * 1000,
            )

        try:
            import google.generativeai as genai
        except ImportError:
            return StepResult(
                success=False,
                error="google-generativeai required: pip install google-generativeai",
                backend_used=self.name,
                duration_ms=(time.time() - t0) * 1000,
            )

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=_SYSTEM_PROMPT,
        )

        # Load end state snapshot if provided
        end_state_b64: Optional[str] = None
        if snapshot_path and Path(snapshot_path).is_file():
            end_state_b64 = _file_to_b64(snapshot_path)

        actions_taken = []
        reached = False

        for step_num in range(max_steps):
            # Take current screenshot
            current_b64 = _screenshot_b64()

            # Build prompt parts
            parts = []

            # Current state
            parts.append(f"CURRENT STATE (step {step_num + 1}/{max_steps}):")
            parts.append({
                "mime_type": "image/png",
                "data": current_b64,
            })

            # Target state
            if end_state_b64:
                parts.append("TARGET END STATE:")
                parts.append({
                    "mime_type": "image/png",
                    "data": end_state_b64,
                })

            # Task description
            task = f"TASK: {description}"
            if end_state_desc:
                task += f"\nEND STATE: {end_state_desc}"
            parts.append(task)
            parts.append("What single action should I take next? Output JSON only.")

            # Ask model
            try:
                response = model.generate_content(parts)
                raw = response.text.strip()
            except Exception as exc:
                return StepResult(
                    success=False,
                    error=f"GUIAgentBackend: model error at step {step_num+1}: {exc}",
                    backend_used=self.name,
                    duration_ms=(time.time() - t0) * 1000,
                )

            # Strip markdown fences
            if raw.startswith("```"):
                raw = "\n".join(
                    l for l in raw.split("\n") if not l.startswith("```")
                ).strip()

            # Parse action
            try:
                action_dict = json.loads(raw)
            except json.JSONDecodeError:
                return StepResult(
                    success=False,
                    error=f"GUIAgentBackend: invalid JSON from model: {raw[:200]}",
                    backend_used=self.name,
                    duration_ms=(time.time() - t0) * 1000,
                )

            action_name = action_dict.get("action", "")
            actions_taken.append(action_dict)

            if action_name == "done":
                reached = True
                break

            # Execute action
            try:
                _execute_action(action_dict, context)
            except Exception as exc:
                return StepResult(
                    success=False,
                    error=f"GUIAgentBackend: action execution failed: {exc}",
                    backend_used=self.name,
                    duration_ms=(time.time() - t0) * 1000,
                )

            time.sleep(0.5)  # wait for UI to respond

            # After executing, check if end state reached
            if end_state_b64 and step_num < max_steps - 1:
                current_b64 = _screenshot_b64()
                check_model = genai.GenerativeModel(model_name=model_name)
                check_parts = [
                    _CHECK_PROMPT,
                    "CURRENT:", {"mime_type": "image/png", "data": current_b64},
                    "TARGET:", {"mime_type": "image/png", "data": end_state_b64},
                ]
                try:
                    check_resp = check_model.generate_content(check_parts)
                    check_raw = check_resp.text.strip()
                    if check_raw.startswith("```"):
                        check_raw = "\n".join(
                            l for l in check_raw.split("\n")
                            if not l.startswith("```")
                        ).strip()
                    check_dict = json.loads(check_raw)
                    if check_dict.get("reached"):
                        reached = True
                        break
                except Exception:
                    pass  # continue if check fails

        return StepResult(
            success=reached or len(actions_taken) > 0,
            output={
                "reached_end_state": reached,
                "steps_taken": len(actions_taken),
                "actions": actions_taken,
            },
            backend_used=self.name,
            duration_ms=(time.time() - t0) * 1000,
        )
