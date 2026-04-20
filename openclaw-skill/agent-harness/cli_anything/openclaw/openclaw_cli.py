#!/usr/bin/env python3
"""OpenClaw CLI — agent-callable interface for the Macro System.

This CLI is the L6 "Unified CLI Entry" in the OpenClaw Macro System.
It provides a stable, machine-readable interface for AI agents and
power users to invoke macros without touching the GUI.

Usage (one-shot):
    cli-anything-openclaw macro run export_file --param output=/tmp/out.png --json
    cli-anything-openclaw macro list --json
    cli-anything-openclaw macro info export_file --json

Usage (REPL):
    cli-anything-openclaw          # enters interactive REPL
    cli-anything-openclaw repl
"""

import sys
import os
import json
import click
from typing import Optional

from cli_anything.openclaw.core.registry import MacroRegistry
from cli_anything.openclaw.core.runtime import MacroRuntime
from cli_anything.openclaw.core.session import ExecutionSession

# ── Global state ─────────────────────────────────────────────────────────────

_json_output = False
_repl_mode = False
_dry_run = False

_session: Optional[ExecutionSession] = None
_runtime: Optional[MacroRuntime] = None


def get_runtime() -> MacroRuntime:
    global _runtime, _session
    if _runtime is None:
        _session = _session or ExecutionSession()
        _runtime = MacroRuntime(session=_session)
    return _runtime


def get_session() -> ExecutionSession:
    global _session
    if _session is None:
        _session = ExecutionSession()
    return _session


# ── Output helpers ────────────────────────────────────────────────────────────

def output(data, message: str = ""):
    """Print result: JSON in --json mode, human-readable otherwise."""
    if _json_output:
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if message:
            click.echo(message)
        _print_value(data)


def _print_value(val, indent: int = 0):
    prefix = "  " * indent
    if isinstance(val, dict):
        for k, v in val.items():
            if isinstance(v, (dict, list)):
                click.echo(f"{prefix}{k}:")
                _print_value(v, indent + 1)
            else:
                click.echo(f"{prefix}{k}: {v}")
    elif isinstance(val, list):
        for i, item in enumerate(val):
            if isinstance(item, dict):
                click.echo(f"{prefix}[{i}]")
                _print_value(item, indent + 1)
            else:
                click.echo(f"{prefix}- {item}")
    else:
        click.echo(f"{prefix}{val}")


def handle_error(func):
    """Decorator: consistent error handling across commands."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyError as e:
            msg = str(e).strip("'\"")
            if _json_output:
                click.echo(json.dumps({"error": msg, "type": "not_found"}))
            else:
                click.echo(f"Error: {msg}", err=True)
            if not _repl_mode:
                sys.exit(1)
        except FileNotFoundError as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": "file_not_found"}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)
        except Exception as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)

    return wrapper


# ── Parameter parsing ─────────────────────────────────────────────────────────

def _parse_params(param_tuples: tuple) -> dict:
    """Convert --param key=value tuples to a dict."""
    result = {}
    for pair in param_tuples:
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k.strip()] = v.strip()
        else:
            click.echo(f"Warning: --param '{pair}' ignored (expected key=value format).", err=True)
    return result


# ── Main CLI group ────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.option("--json", "json_flag", is_flag=True, help="Machine-readable JSON output.")
@click.option("--dry-run", "dry_run_flag", is_flag=True,
              help="Simulate execution without side effects.")
@click.option("--session-id", default=None, help="Resume or create a named session.")
@click.pass_context
def cli(ctx, json_flag, dry_run_flag, session_id):
    """OpenClaw Macro System — run GUI workflows as CLI commands.

    \b
    Quick start:
      cli-anything-openclaw macro list
      cli-anything-openclaw macro info <name>
      cli-anything-openclaw macro run <name> --param key=value

    Enter interactive REPL by running without arguments.
    """
    global _json_output, _dry_run, _session

    _json_output = json_flag
    _dry_run = dry_run_flag

    if session_id:
        loaded = ExecutionSession.load(session_id)
        _session = loaded or ExecutionSession(session_id=session_id)

    ctx.ensure_object(dict)

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ── macro group ──────────────────────────────────────────────────────────────

@cli.group()
def macro():
    """Macro management and execution."""


@macro.command("run")
@click.argument("name")
@click.option("--param", "-p", multiple=True,
              help="Macro parameter in key=value format. Repeat for multiple.")
@handle_error
def macro_run(name, param):
    """Execute a macro by name.

    \b
    Example:
      macro run export_file --param output=/tmp/out.txt
      macro run export_file -p output=/tmp/out.txt -p format=plain --json
    """
    params = _parse_params(param)
    runtime = get_runtime()
    result = runtime.execute(name, params, dry_run=_dry_run)

    if _json_output:
        output(result.to_dict())
    else:
        if result.success:
            click.echo(f"✓ Macro '{name}' completed successfully.")
            if result.output:
                for k, v in result.output.items():
                    if not k.startswith("_"):
                        click.echo(f"  {k}: {v}")
        else:
            click.echo(f"✗ Macro '{name}' failed.", err=True)
            click.echo(f"  {result.error}", err=True)
        if result.telemetry:
            click.echo(
                f"  [{result.telemetry.get('duration_ms', 0):.0f}ms, "
                f"backends: {', '.join(result.telemetry.get('backends_used', []))}]"
            )
    if not result.success and not _repl_mode:
        sys.exit(1)


@macro.command("list")
@handle_error
def macro_list():
    """List all available macros."""
    runtime = get_runtime()
    macros = runtime.registry.list_all()

    if _json_output:
        output([{
            "name": m.name,
            "version": m.version,
            "description": m.description,
            "tags": m.tags,
            "parameters": list(m.parameters.keys()),
        } for m in macros])
    else:
        if not macros:
            click.echo("No macros found.")
            return
        click.echo(f"Available macros ({len(macros)}):\n")
        for m in macros:
            tags = f"  [{', '.join(m.tags)}]" if m.tags else ""
            click.echo(f"  {m.name:<30}  {m.description}{tags}")


@macro.command("info")
@click.argument("name")
@handle_error
def macro_info(name):
    """Show full details for a macro (schema, parameters, steps)."""
    runtime = get_runtime()
    m = runtime.registry.load(name)

    if _json_output:
        output(m.to_dict())
    else:
        click.echo(f"\nMacro: {m.name}  (v{m.version})")
        click.echo(f"  {m.description}\n")

        if m.parameters:
            click.echo("Parameters:")
            for pname, pspec in m.parameters.items():
                req = "(required)" if pspec.required else f"(default: {pspec.default!r})"
                click.echo(f"  --param {pname}=<{pspec.type}>  {req}")
                if pspec.description:
                    click.echo(f"           {pspec.description}")

        if m.preconditions:
            click.echo(f"\nPreconditions ({len(m.preconditions)}):")
            for c in m.preconditions:
                click.echo(f"  {c.type}: {c.args}")

        if m.steps:
            click.echo(f"\nSteps ({len(m.steps)}):")
            for s in m.steps:
                click.echo(f"  [{s.id}] backend={s.backend}  action={s.action}")

        if m.postconditions:
            click.echo(f"\nPostconditions ({len(m.postconditions)}):")
            for c in m.postconditions:
                click.echo(f"  {c.type}: {c.args}")

        if m.outputs:
            click.echo(f"\nOutputs:")
            for o in m.outputs:
                click.echo(f"  {o.name}: {o.path or o.value}")

        if m.agent_hints:
            click.echo(f"\nAgent hints: {m.agent_hints}")
        click.echo()


@macro.command("validate")
@click.argument("name", required=False)
@handle_error
def macro_validate(name):
    """Validate macro definition(s). Pass a name or omit to validate all."""
    runtime = get_runtime()

    if name:
        names = [name]
    else:
        names = runtime.registry.list_names()

    results = {}
    for n in names:
        errors = runtime.validate_macro(n)
        results[n] = errors

    if _json_output:
        output({n: {"valid": len(e) == 0, "errors": e} for n, e in results.items()})
    else:
        all_ok = True
        for n, errors in results.items():
            if errors:
                all_ok = False
                click.echo(f"✗ {n}:")
                for err in errors:
                    click.echo(f"    - {err}", err=True)
            else:
                click.echo(f"✓ {n}")
        if all_ok:
            click.echo("\nAll macros valid.")
        else:
            if not _repl_mode:
                sys.exit(1)


@macro.command("dry-run")
@click.argument("name")
@click.option("--param", "-p", multiple=True, help="Parameter in key=value format.")
@handle_error
def macro_dry_run(name, param):
    """Simulate macro execution without any side effects."""
    params = _parse_params(param)
    runtime = get_runtime()
    result = runtime.execute(name, params, dry_run=True)

    if _json_output:
        output(result.to_dict())
    else:
        click.echo(f"[dry-run] Macro '{name}'")
        if result.success:
            click.echo("  Would execute successfully.")
            click.echo(f"  Steps: {len(result.step_results)}")
        else:
            click.echo(f"  Would fail: {result.error}", err=True)


@macro.command("define")
@click.argument("name")
@click.option("--output", "-o", default=None, help="Write YAML to this file path.")
@handle_error
def macro_define(name, output):
    """Scaffold a new macro YAML definition."""
    import textwrap
    template = textwrap.dedent(f"""\
        name: {name}
        version: "1.0"
        description: "Describe what this macro does."
        tags: []

        parameters:
          # Add your parameters here
          # output:
          #   type: string
          #   required: true
          #   description: Output file path
          #   example: /tmp/result.txt

        preconditions:
          # Conditions that must be true before execution
          # - file_exists: /path/to/input
          # - process_running: my-app

        steps:
          - id: step_1
            backend: native_api   # or: file_transform, semantic_ui, gui_macro
            action: run_command
            params:
              command: [echo, "Hello from {name}"]
            timeout_ms: 30000
            on_failure: fail       # or: skip, continue

        postconditions:
          # Conditions verified after execution
          # - file_exists: ${{output}}

        outputs:
          # Named outputs the agent can use
          # - name: result_file
          #   path: ${{output}}

        agent_hints:
          danger_level: safe      # safe | moderate | dangerous
          side_effects: []
          reversible: true
    """)
    if output:
        from pathlib import Path
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(template, encoding="utf-8")
        if _json_output:
            click.echo(json.dumps({"created": str(p.resolve())}))
        else:
            click.echo(f"✓ Macro scaffold written to: {p.resolve()}")
    else:
        click.echo(template)


@macro.command("record")
@click.argument("name")
@click.option("--output-dir", "-d", default=".",
              help="Directory to write <name>.yaml and <name>_templates/.")
@click.option("--timeout", default=0, type=float,
              help="Auto-stop after N seconds (0 = wait for Ctrl+Alt+S).")
@handle_error
def macro_record(name, output_dir, timeout):
    """Record GUI interactions and generate a macro YAML.

    \b
    Start recording, perform your GUI workflow, then press Ctrl+Alt+S to stop.
    Each mouse click is saved with a screenshot template so the macro is
    robust to window position changes.

    Requires: pip install mss Pillow pynput
    """
    try:
        from cli_anything.openclaw.core.recorder import MacroRecorder
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    recorder = MacroRecorder(macro_name=name, output_dir=output_dir)

    if not _json_output:
        click.echo(f"Recording '{name}'. Press Ctrl+Alt+S to stop...")

    try:
        recorder.record(timeout_s=timeout if timeout > 0 else None)
        yaml_path = recorder.save()
    except Exception as e:
        if _json_output:
            output({"error": str(e), "success": False})
        else:
            click.echo(f"Error during recording: {e}", err=True)
        if not _repl_mode:
            sys.exit(1)
        return

    if _json_output:
        output({
            "success": True,
            "yaml_path": yaml_path,
            "steps": len(recorder._steps),
            "templates_dir": str(recorder.templates_dir),
        })
    else:
        click.echo(f"✓ Saved {len(recorder._steps)} steps to: {yaml_path}")
        click.echo(f"  Templates: {recorder.templates_dir}/")
        click.echo(
            "\n  Next: register the macro in macro_definitions/manifest.yaml\n"
            "  or run it directly with: macro run --macro-file " + yaml_path
        )


@macro.command("assist")
@click.argument("name")
@click.option("--goal", "-g", required=True,
              help="Natural language goal (what the macro should do).")
@click.option("--screenshot", default="current",
              help="'current' to take a screenshot now, or path to an image file.")
@click.option("--output", "-o", default=None,
              help="Output YAML file path (default: <name>.yaml).")
@click.option("--api-key", default=None, envvar="GEMINI_API_KEY",
              help="Gemini API key (or set GEMINI_API_KEY env var).")
@click.option("--model", default="gemini-1.5-flash",
              help="Gemini model name.")
@handle_error
def macro_assist(name, goal, screenshot, output, api_key, model):
    """Generate a macro YAML from a screenshot using Gemini Vision (optional).

    \b
    Takes a screenshot, sends it to Gemini with your goal, and generates
    a macro YAML. Steps that require visual templates will include
    instructions for which template images to capture.

    Requires: pip install google-generativeai mss Pillow

    \b
    Example:
      macro assist export_png \\
          --goal "Export the current diagram as PNG to /tmp/out.png" \\
          --api-key $GEMINI_API_KEY
    """
    try:
        from cli_anything.openclaw.core.gemini_assist import generate_macro
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not _json_output:
        click.echo(f"Sending screenshot to Gemini ({model})...")

    result = generate_macro(
        goal=goal,
        macro_name=name,
        screenshot_source=screenshot,
        api_key=api_key,
        model=model,
        output_path=output,
    )

    if _json_output:
        output(result)
    else:
        click.echo(f"✓ Generated {result['steps_count']} steps → {result['yaml_path']}")
        if result["warnings"]:
            for w in result["warnings"]:
                click.echo(f"  ⚠ {w}")
        if result.get("templates_to_capture"):
            click.echo("\n  Templates to capture (use 'macro capture-template'):")
            for t in result["templates_to_capture"]:
                click.echo(f"    {t['template_path']}: {t['description']}")


@macro.command("capture-template")
@click.argument("output_path")
@click.option("--x", type=int, required=True, help="Left edge of region.")
@click.option("--y", type=int, required=True, help="Top edge of region.")
@click.option("--width", type=int, required=True, help="Region width in pixels.")
@click.option("--height", type=int, required=True, help="Region height in pixels.")
@handle_error
def macro_capture_template(output_path, x, y, width, height):
    """Capture a screen region and save it as a template image.

    \b
    Use this to create the template PNG files that visual_anchor macros need.

    \b
    Example:
      macro capture-template templates/export_button.png \\
          --x 245 --y 110 --width 80 --height 30

    Requires: pip install mss Pillow
    """
    try:
        from cli_anything.openclaw.backends.visual_anchor import VisualAnchorBackend
        from cli_anything.openclaw.backends.base import BackendContext
        from cli_anything.openclaw.core.macro_model import MacroStep
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    va = VisualAnchorBackend()
    step = MacroStep(id="capture", backend="visual_anchor", action="capture_region",
                     params={"output": output_path, "x": x, "y": y,
                             "width": width, "height": height})
    ctx = BackendContext(params={})
    result = va.execute(step, {}, ctx)

    if _json_output:
        output(result.to_dict())
    else:
        if result.success:
            click.echo(f"✓ Template saved: {result.output.get('saved')}")
            click.echo(f"  Size: {result.output.get('file_size', 0)} bytes")
        else:
            click.echo(f"✗ {result.error}", err=True)
            if not _repl_mode:
                sys.exit(1)


# ── session group ─────────────────────────────────────────────────────────────

@cli.group()
def session():
    """Session management and run history."""


@session.command("status")
@handle_error
def session_status():
    """Show current session status and statistics."""
    sess = get_session()
    data = sess.status()
    output(data, "Session status:")


@session.command("history")
@click.option("--limit", default=10, show_default=True, help="Number of records to show.")
@handle_error
def session_history(limit):
    """Show recent macro execution history."""
    sess = get_session()
    records = sess.history(limit=limit)

    if _json_output:
        output([r.to_dict() for r in records])
    else:
        if not records:
            click.echo("No runs recorded in this session.")
            return
        click.echo(f"Recent runs ({len(records)}):\n")
        for r in records:
            status = "✓" if r.success else "✗"
            import datetime
            ts = datetime.datetime.fromtimestamp(r.timestamp).strftime("%H:%M:%S")
            click.echo(f"  {status} [{ts}] {r.macro_name}  ({r.duration_ms:.0f}ms)")
            if not r.success:
                click.echo(f"       Error: {r.error}", err=True)


@session.command("save")
@handle_error
def session_save():
    """Persist current session to disk."""
    sess = get_session()
    path = sess.save()
    output({"saved": path, "session_id": sess.session_id},
           f"Session saved: {path}")


@session.command("list")
@handle_error
def session_list():
    """List all saved sessions."""
    sessions = ExecutionSession.list_sessions()
    if _json_output:
        output(sessions)
    else:
        if not sessions:
            click.echo("No saved sessions.")
            return
        click.echo("Saved sessions:\n")
        for s in sessions:
            import datetime
            ts = datetime.datetime.fromtimestamp(s.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M:%S")
            click.echo(f"  {s['session_id']}  ({s['runs']} runs)  {ts}")


# ── backends command ──────────────────────────────────────────────────────────

@cli.command()
@handle_error
def backends():
    """Show available execution backends and their status."""
    runtime = get_runtime()
    data = runtime.routing.describe()
    if _json_output:
        output(data)
    else:
        click.echo("Execution backends:\n")
        for name, info in sorted(data.items(), key=lambda x: -x[1].get("priority", 0)):
            status = "✓" if info.get("available") else "✗"
            click.echo(
                f"  {status}  {name:<20}  priority={info.get('priority', '?'):<5}"
                f"  available={info.get('available')}"
            )


# ── repl command ──────────────────────────────────────────────────────────────

@cli.command()
@click.pass_context
def repl(ctx):
    """Enter the interactive REPL (default when no command given)."""
    global _repl_mode
    _repl_mode = True

    from cli_anything.openclaw.utils.repl_skin import ReplSkin
    skin = ReplSkin("openclaw", version="1.0.0")
    skin.print_banner()

    runtime = get_runtime()

    # Show quick summary on startup
    macros = runtime.registry.list_all()
    skin.info(f"{len(macros)} macros loaded. Type 'macro list' to see them.")
    skin.info("Type 'help' for commands, 'quit' to exit.\n")

    pt_session = skin.create_prompt_session()
    session_obj = get_session()

    while True:
        try:
            line = skin.get_input(
                pt_session,
                context=f"{session_obj.session_id[:12]}",
            )
        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break

        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            skin.print_goodbye()
            break
        if line.lower() in ("help", "?"):
            skin.help({
                "macro list":        "List all available macros",
                "macro info <name>": "Show macro schema",
                "macro run <name> [--param k=v ...]": "Execute a macro",
                "macro dry-run <name>": "Simulate without side effects",
                "macro validate [name]": "Validate macro definitions",
                "macro define <name>":   "Scaffold a new macro YAML",
                "session status":    "Show session statistics",
                "session history":   "Show recent runs",
                "backends":          "Show backend availability",
                "quit":              "Exit the REPL",
            })
            continue

        # Parse and dispatch via Click's standalone_mode=False
        import shlex
        try:
            args = shlex.split(line)
        except ValueError as e:
            skin.error(f"Parse error: {e}")
            continue

        try:
            ctx_obj = cli.make_context(
                "cli-anything-openclaw",
                args,
                standalone_mode=False,
                parent=ctx,
            )
            with ctx_obj:
                cli.invoke(ctx_obj)
        except SystemExit:
            pass
        except click.ClickException as e:
            skin.error(str(e))
        except Exception as e:
            skin.error(str(e))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
