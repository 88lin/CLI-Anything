"""Macro recorder — record GUI interactions and generate macro YAML.

Usage:
    cli-anything-macrocli macro record my_workflow

What it does:
  1. Starts listening for mouse clicks and keyboard events (pynput)
  2. On each click: captures a small screenshot region around the click
     point and saves it as a template image
  3. On each hotkey / type event: records the keystroke
  4. When the user presses Ctrl+Alt+S (or sends SIGINT): stops recording
     and writes a macro YAML file

The generated macro uses the `visual_anchor` backend for click steps
(template images, not hardcoded coordinates) so it is robust to window
movement and minor layout changes.

Output layout:
    <macro_name>.yaml
    <macro_name>_templates/
        step_001_click.png
        step_002_click.png
        ...
"""

from __future__ import annotations

import os
import sys
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML required: pip install PyYAML")


# ── Step data classes ─────────────────────────────────────────────────────────

@dataclass
class RecordedStep:
    index: int
    kind: str           # click | type | hotkey | scroll
    # click fields
    x: int = 0
    y: int = 0
    button: str = "left"
    double: bool = False
    template_path: str = ""   # relative path to saved template png
    # type fields
    text: str = ""
    # hotkey fields
    keys: str = ""
    # scroll fields
    dx: int = 0
    dy: int = 0
    # timing
    timestamp: float = field(default_factory=time.time)

    def to_step_dict(self) -> dict:
        """Convert to a macro YAML step dict."""
        if self.kind == "click":
            params: dict = {
                "template": self.template_path,
                "confidence": 0.85,
                "timeout_ms": 5000,
            }
            if self.button != "left":
                params["button"] = self.button
            if self.double:
                params["double"] = True
            return {
                "id": f"step_{self.index:03d}_click",
                "backend": "visual_anchor",
                "action": "click_image",
                "params": params,
                "on_failure": "fail",
            }
        elif self.kind == "type":
            return {
                "id": f"step_{self.index:03d}_type",
                "backend": "visual_anchor",
                "action": "type_text",
                "params": {"text": self.text},
                "on_failure": "fail",
            }
        elif self.kind == "hotkey":
            return {
                "id": f"step_{self.index:03d}_hotkey",
                "backend": "visual_anchor",
                "action": "hotkey",
                "params": {"keys": self.keys},
                "on_failure": "fail",
            }
        elif self.kind == "scroll":
            return {
                "id": f"step_{self.index:03d}_scroll",
                "backend": "visual_anchor",
                "action": "scroll",
                "params": {
                    "template": self.template_path or "",
                    "dx": self.dx,
                    "dy": self.dy,
                },
                "on_failure": "fail",
            }
        return {}


# ── Template capture ──────────────────────────────────────────────────────────

_TEMPLATE_PADDING = 30   # pixels around click point to capture


def _capture_template(x: int, y: int, output_path: str) -> bool:
    """Capture a small region around (x, y) and save as PNG template."""
    try:
        import mss
        from PIL import Image

        pad = _TEMPLATE_PADDING
        region = {
            "left": max(0, x - pad),
            "top": max(0, y - pad),
            "width": pad * 2,
            "height": pad * 2,
        }
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with mss.mss() as sct:
            raw = sct.grab(region)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            img.save(output_path)
        return True
    except Exception as e:
        print(f"[recorder] Warning: could not capture template: {e}", file=sys.stderr)
        return False


# ── Key accumulation helper ───────────────────────────────────────────────────

_MODIFIER_KEYS = frozenset([
    "ctrl_l", "ctrl_r", "shift", "shift_r", "alt_l", "alt_r",
    "alt_gr", "cmd", "cmd_r", "super_l", "super_r",
])

_KEY_NAME_MAP = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift_r": "shift",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd_r": "cmd",
    "super_l": "super", "super_r": "super",
}


def _key_to_str(key) -> str:
    """Convert a pynput Key or KeyCode to a string."""
    try:
        from pynput.keyboard import Key
        if isinstance(key, Key):
            name = key.name  # e.g. "ctrl_l", "shift", "f5"
            return _KEY_NAME_MAP.get(name, name)
        # KeyCode
        if hasattr(key, "char") and key.char:
            return key.char
        if hasattr(key, "vk") and key.vk:
            return f"vk{key.vk}"
    except Exception:
        pass
    return str(key)


# ── Recorder ─────────────────────────────────────────────────────────────────

class MacroRecorder:
    """Records mouse and keyboard events and converts them to macro steps."""

    STOP_HOTKEY = frozenset(["ctrl", "alt", "s"])   # Ctrl+Alt+S to stop

    def __init__(self, macro_name: str, output_dir: str = "."):
        self.macro_name = macro_name
        self.output_dir = Path(output_dir)
        self.templates_dir = self.output_dir / f"{macro_name}_templates"

        self._steps: list[RecordedStep] = []
        self._step_index = 0
        self._pressed_modifiers: set[str] = set()
        self._pending_chars: list[str] = []
        self._last_event_time = time.time()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Double-click detection
        self._last_click_pos: Optional[tuple[int, int]] = None
        self._last_click_time: float = 0.0
        self._DOUBLE_CLICK_MS = 400

    def _next_index(self) -> int:
        self._step_index += 1
        return self._step_index

    def _flush_pending_chars(self):
        """Accumulate consecutive character presses into a single type step."""
        if self._pending_chars:
            text = "".join(self._pending_chars)
            step = RecordedStep(
                index=self._next_index(),
                kind="type",
                text=text,
            )
            self._steps.append(step)
            self._pending_chars.clear()

    # ── Mouse callbacks ───────────────────────────────────────────────────────

    def on_click(self, x: int, y: int, button, pressed: bool):
        if not pressed:
            return  # only record press events

        with self._lock:
            self._flush_pending_chars()

            btn_str = button.name if hasattr(button, "name") else str(button)

            # Detect double click
            now = time.time()
            is_double = (
                self._last_click_pos == (x, y)
                and (now - self._last_click_time) * 1000 < self._DOUBLE_CLICK_MS
            )
            if is_double:
                # Upgrade last click step to double=True
                if self._steps and self._steps[-1].kind == "click":
                    self._steps[-1].double = True
                self._last_click_pos = None
                return

            self._last_click_pos = (x, y)
            self._last_click_time = now

            # Save template
            idx = self._next_index()
            template_file = str(
                self.templates_dir / f"step_{idx:03d}_click.png"
            )
            captured = _capture_template(x, y, template_file)

            step = RecordedStep(
                index=idx,
                kind="click",
                x=x,
                y=y,
                button=btn_str,
                template_path=template_file if captured else "",
            )
            self._steps.append(step)
            print(f"[recorder] click #{idx} at ({x},{y}) btn={btn_str}", flush=True)

    def on_scroll(self, x: int, y: int, dx: int, dy: int):
        with self._lock:
            self._flush_pending_chars()
            idx = self._next_index()
            # Capture template near scroll position
            template_file = str(
                self.templates_dir / f"step_{idx:03d}_scroll.png"
            )
            captured = _capture_template(x, y, template_file)

            step = RecordedStep(
                index=idx,
                kind="scroll",
                x=x, y=y,
                dx=dx, dy=dy,
                template_path=template_file if captured else "",
            )
            self._steps.append(step)

    # ── Keyboard callbacks ────────────────────────────────────────────────────

    def on_key_press(self, key):
        key_str = _key_to_str(key)

        # Check stop hotkey
        if key_str.lower() in ("ctrl", "alt"):
            self._pressed_modifiers.add(key_str.lower())
        elif key_str.lower() == "s" and self._pressed_modifiers >= {"ctrl", "alt"}:
            print("\n[recorder] Stop hotkey detected (Ctrl+Alt+S). Stopping...", flush=True)
            self._stop_event.set()
            return False  # stop listener

        if key_str in _MODIFIER_KEYS or _KEY_NAME_MAP.get(key_str, key_str) in _MODIFIER_KEYS:
            self._pressed_modifiers.add(_KEY_NAME_MAP.get(key_str, key_str))
            return

        # If modifiers are pressed, it's a hotkey combination
        active_mods = {_KEY_NAME_MAP.get(m, m) for m in self._pressed_modifiers}
        if active_mods:
            with self._lock:
                self._flush_pending_chars()
                combo = "+".join(sorted(active_mods) + [key_str])
                idx = self._next_index()
                step = RecordedStep(index=idx, kind="hotkey", keys=combo)
                self._steps.append(step)
                print(f"[recorder] hotkey #{idx}: {combo}", flush=True)
        else:
            # Regular character — accumulate
            if len(key_str) == 1:
                with self._lock:
                    self._pending_chars.append(key_str)
            else:
                # Special key alone (enter, tab, backspace, etc.)
                with self._lock:
                    self._flush_pending_chars()
                    idx = self._next_index()
                    step = RecordedStep(index=idx, kind="hotkey", keys=key_str)
                    self._steps.append(step)

    def on_key_release(self, key):
        key_str = _key_to_str(key)
        normalized = _KEY_NAME_MAP.get(key_str, key_str)
        self._pressed_modifiers.discard(normalized)

    # ── Main record loop ──────────────────────────────────────────────────────

    def record(self, timeout_s: Optional[float] = None) -> list[RecordedStep]:
        """Start recording. Blocks until Ctrl+Alt+S or timeout_s seconds."""
        try:
            from pynput import mouse as mouse_mod, keyboard as kb_mod
        except ImportError:
            raise ImportError(
                "pynput is required for recording.\n"
                "  pip install pynput"
            )

        self.templates_dir.mkdir(parents=True, exist_ok=True)

        print(
            f"[recorder] Recording '{self.macro_name}'. "
            "Press Ctrl+Alt+S to stop.",
            flush=True,
        )

        mouse_listener = mouse_mod.Listener(
            on_click=self.on_click,
            on_scroll=self.on_scroll,
        )
        kb_listener = kb_mod.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release,
        )

        mouse_listener.start()
        kb_listener.start()

        try:
            self._stop_event.wait(timeout=timeout_s)
        except KeyboardInterrupt:
            pass
        finally:
            mouse_listener.stop()
            kb_listener.stop()

        with self._lock:
            self._flush_pending_chars()

        print(f"[recorder] Recorded {len(self._steps)} steps.", flush=True)
        return self._steps

    # ── YAML output ───────────────────────────────────────────────────────────

    def to_yaml(self) -> str:
        """Generate macro YAML from recorded steps."""
        steps = [s.to_step_dict() for s in self._steps if s.to_step_dict()]

        macro = {
            "name": self.macro_name,
            "version": "1.0",
            "description": f"Recorded macro: {self.macro_name}",
            "tags": ["recorded", "visual_anchor"],
            "parameters": {},
            "preconditions": [],
            "steps": steps,
            "postconditions": [],
            "outputs": [],
            "agent_hints": {
                "danger_level": "moderate",
                "side_effects": ["gui_interaction"],
                "reversible": False,
                "recorded": True,
            },
        }
        return yaml.dump(macro, allow_unicode=True, sort_keys=False, default_flow_style=False)

    def save(self, output_path: Optional[str] = None) -> str:
        """Write the generated YAML to a file. Returns the path."""
        if output_path is None:
            output_path = str(self.output_dir / f"{self.macro_name}.yaml")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(self.to_yaml(), encoding="utf-8")
        print(f"[recorder] Saved macro to: {output_path}", flush=True)
        return output_path
