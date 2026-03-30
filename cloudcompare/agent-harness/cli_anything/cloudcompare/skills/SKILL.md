---
name: "cli-anything-cloudcompare"
description: "Command-line interface for Cloudcompare - Agent-friendly command-line harness for [CloudCompare](https://cloudcompare.org) — the open-source 3..."
---

# cli-anything-cloudcompare

Agent-friendly command-line harness for [CloudCompare](https://cloudcompare.org) — the open-source 3D point cloud and mesh processing software.

## Installation

This CLI is installed as part of the cli-anything-cloudcompare package:

```bash
pip install cli-anything-cloudcompare
```

**Prerequisites:**
- Python 3.10+
- Cloudcompare must be installed on your system

## Usage

### Basic Commands

```bash
# Show help
cli-anything-cloudcompare --help

# Start interactive REPL mode
cli-anything-cloudcompare

# Create a new project
cli-anything-cloudcompare project new -o project.json

# Run with JSON output (for agent consumption)
cli-anything-cloudcompare --project project.json --json project info
```

## Examples

### Create a New Project

Create a new cloudcompare project file.

```bash
cli-anything-cloudcompare project new -o myproject.json
# Or with JSON output for programmatic use
cli-anything-cloudcompare --json project new -o myproject.json
```

### Interactive REPL Session

Start an interactive session with undo support.

```bash
cli-anything-cloudcompare
# Enter commands interactively
# Use 'help' to see available commands
# Use 'session undo' to revert the last operation
```

## For AI Agents

When using this CLI programmatically:

1. **Always use `--json` flag** for parseable output
2. **Check return codes** - 0 for success, non-zero for errors
3. **Parse stderr** for error messages on failure
4. **Use absolute paths** for all file operations
5. **Verify outputs exist** after export operations

## Version

1.0.0