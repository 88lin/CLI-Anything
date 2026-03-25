"""End-to-end tests for cli-anything-godot.

These tests require Godot 4.x to be installed and on PATH.
They are automatically skipped when the binary is not available.
Run explicitly with: pytest -m e2e
"""

import json

import pytest
from click.testing import CliRunner

from cli_anything.godot.godot_cli import cli
from cli_anything.godot.utils.godot_backend import is_available


_godot_missing = not is_available()
skip_no_godot = pytest.mark.skipif(
    _godot_missing, reason="Godot binary not found on PATH"
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def e2e_project(tmp_path):
    """Create a real Godot project for E2E tests."""
    runner = CliRunner()
    runner.invoke(cli, ["project", "create", str(tmp_path / "e2e_game"), "--name", "E2E Game"])
    return tmp_path / "e2e_game"


@skip_no_godot
class TestE2EEngineVersion:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--json", "engine", "version"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "version" in data

    def test_status(self, runner):
        result = runner.invoke(cli, ["--json", "engine", "status"])
        data = json.loads(result.output)
        assert data["available"] is True


@skip_no_godot
class TestE2EProject:
    def test_create_and_info(self, runner, tmp_path):
        project_dir = tmp_path / "test_game"
        result = runner.invoke(cli, [
            "--json", "project", "create", str(project_dir), "--name", "Test Game"
        ])
        data = json.loads(result.output)
        assert data["status"] == "ok"

        result = runner.invoke(cli, ["--json", "-p", str(project_dir), "project", "info"])
        data = json.loads(result.output)
        assert data["name"] == "Test Game"

    def test_reimport(self, runner, e2e_project):
        result = runner.invoke(cli, ["--json", "-p", str(e2e_project), "project", "reimport"])
        data = json.loads(result.output)
        assert "status" in data


@skip_no_godot
class TestE2EScene:
    def test_create_and_read(self, runner, e2e_project):
        result = runner.invoke(cli, [
            "--json", "-p", str(e2e_project),
            "scene", "create", "scenes/TestScene.tscn",
            "--root-type", "Node2D",
        ])
        data = json.loads(result.output)
        assert data["status"] == "ok"

        result = runner.invoke(cli, [
            "--json", "-p", str(e2e_project),
            "scene", "read", "scenes/TestScene.tscn",
        ])
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert len(data["nodes"]) >= 1

    def test_add_node_and_verify(self, runner, e2e_project):
        runner.invoke(cli, [
            "-p", str(e2e_project),
            "scene", "create", "scenes/NodeTest.tscn",
        ])
        result = runner.invoke(cli, [
            "--json", "-p", str(e2e_project),
            "scene", "add-node", "scenes/NodeTest.tscn",
            "--name", "Sprite", "--type", "Sprite2D",
        ])
        data = json.loads(result.output)
        assert data["status"] == "ok"

        result = runner.invoke(cli, [
            "--json", "-p", str(e2e_project),
            "scene", "read", "scenes/NodeTest.tscn",
        ])
        data = json.loads(result.output)
        node_names = [n.get("name") for n in data["nodes"]]
        assert "Sprite" in node_names


@skip_no_godot
class TestE2EScript:
    def test_run_script(self, runner, e2e_project):
        script_path = e2e_project / "tool_test.gd"
        script_path.write_text(
            'extends SceneTree\n\n'
            'func _init():\n'
            '\tprint("Hello from CLI-Anything!")\n'
            '\tquit()\n',
            encoding="utf-8",
        )
        result = runner.invoke(cli, [
            "--json", "-p", str(e2e_project),
            "script", "run", "tool_test.gd",
        ])
        data = json.loads(result.output)
        assert "status" in data
        if data["status"] == "ok":
            assert "Hello from CLI-Anything!" in data.get("stdout", "")

    def test_inline_script(self, runner, e2e_project):
        result = runner.invoke(cli, [
            "--json", "-p", str(e2e_project),
            "script", "inline", 'print("inline test")',
        ])
        data = json.loads(result.output)
        assert "status" in data
