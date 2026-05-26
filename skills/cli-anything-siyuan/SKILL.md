---
name: "cli-anything-siyuan"
description: >-
  Command-line interface for SiYuan (思源笔记) — manage notebooks, documents, blocks, and search content via SiYuan HTTP API. Designed for AI agents and power users who need to operate their knowledge base without the GUI.
---

# cli-anything-siyuan

Command-line interface for [SiYuan](https://github.com/siyuan-note/siyuan) (思源笔记), a local-first knowledge management system. Connects to a running SiYuan kernel via its REST API (`http://127.0.0.1:6806`).

## Installation

```bash
# Install from source
cd siyuan/agent-harness
pip install -e ".[repl]"
```

**Prerequisites:**
- Python 3.10+
- SiYuan must be running with HTTP API enabled (default port 6806)

## Usage

### Basic Commands

```bash
# Show help
cli-anything-siyuan --help

# Check connection status
cli-anything-siyuan status

# Start interactive REPL mode
cli-anything-siyuan

# Run with JSON output (for agent consumption)
cli-anything-siyuan --json notebook list
```

### REPL Mode

When invoked without a subcommand, the CLI enters an interactive REPL session with tab-completion:

```bash
cli-anything-siyuan
# siyuan ❯ notebook list
# siyuan ❯ search "keyword"
```

## Command Groups

### Notebook

Manage notebooks.

| Command | Description |
|---------|-------------|
| `list` | List all notebooks |
| `create <name>` | Create a notebook |
| `rename <id> <name>` | Rename a notebook |
| `remove <id>` | Delete a notebook (requires `--dangerous`) |
| `open <id>` | Open a notebook |

### Document

Manage documents within notebooks.

| Command | Description |
|---------|-------------|
| `create <notebook> <path>` | Create a document |
| `list <notebook> [path]` | List documents |
| `tree <notebook>` | Show document tree |
| `get <doc-id>` | Get document path and title |
| `rename <id> <title>` | Rename a document |
| `remove <id>` | Delete a document |

### Block

Content block operations.

| Command | Description |
|---------|-------------|
| `get <block-id>` | View block source |
| `children <block-id>` | View child blocks |
| `insert <data>` | Insert a block |
| `update <id> <data>` | Update a block |
| `delete <id>` | Delete a block |

### Search & Query

| Command | Description |
|---------|-------------|
| `search <query>` | Full-text search across all blocks |
| `sql <stmt>` | Run SQL queries against the SiYuan database |
| `export md <doc-id>` | Export a document as Markdown |
| `tag list` | List all tags |

### System

| Command | Description |
|---------|-------------|
| `status` | Check connection and version info |
| `version` | Show SiYuan kernel version |

## Configuration

Create `~/.siyuan-cli.json`:

```json
{
  "host": "127.0.0.1",
  "port": 6806,
  "token": "your-api-token"
}
```

API token can be found in SiYuan: Settings → About → API Token.

Alternatively, use environment variables: `SIYUAN_HOST`, `SIYUAN_PORT`, `SIYUAN_TOKEN`.

## Testing

```bash
# Install test dependencies
pip install -e ".[test]"

# Run unit tests (no external dependencies)
pytest cli_anything/siyuan/tests/test_core.py cli_anything/siyuan/tests/test_cli_commands.py -v

# Run all tests including E2E (requires running SiYuan)
pytest cli_anything/siyuan/tests/ -v
```

**33 tests** (18 unit + 15 CLI command tests + optional E2E tests against a live instance).

## Notes

- All destructive operations (`remove`, `delete`, `rename`) require `--dangerous` flag
- JSON output mode (`--json`) is available on all commands for machine consumption
- SiYuan must be running — the CLI does not start the kernel
