import json

import pytest

from doko_operations import source_lifecycle_cli as lifecycle
from doko_operations.cli import main


@pytest.mark.parametrize("command", [["data", "impact"], ["data", "source", "retire"]])
def test_help(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main([*command, "--help"])
    assert exc.value.code == 0
    assert "--source-asset-id" in capsys.readouterr().out


def test_missing_source_subcommand_shows_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["data", "source"])
    assert exc.value.code == 0
    assert "retire" in capsys.readouterr().out


def test_retirement_requires_arguments(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["data", "source", "retire"])
    assert exc.value.code == 2
    assert "required" in capsys.readouterr().err


def test_impact_requires_source_for_retention_preview(tmp_path, capsys):
    assert (
        main(["data", "impact", "--repository-root", str(tmp_path), "--retention-state", "retired"])
        == 2
    )
    assert "requires --source-asset-id" in capsys.readouterr().err


@pytest.mark.parametrize("json_output", [False, True])
def test_impact_dispatch_and_output(monkeypatch, tmp_path, capsys, json_output):
    report = {
        "source_asset_id": "s",
        "retention_state": "active",
        "artifact_counts": {"x": 1},
        "task_impacts": [],
        "affected_artifacts": [],
    }
    calls = []

    def analyze(root, source, **kwargs):
        calls.append((root, source, kwargs))
        return report

    monkeypatch.setattr(lifecycle, "analyze_source_impact", analyze)
    args = ["data", "impact", "--repository-root", str(tmp_path), "--source-asset-id", "s"]
    assert main(args + (["--json"] if json_output else [])) == 0
    output = capsys.readouterr().out
    assert calls[0][1] == "s"
    assert json.loads(output) == report if json_output else "source: s (active)" in output


@pytest.mark.parametrize("json_output", [False, True])
def test_retirement_dispatch_and_output(monkeypatch, tmp_path, capsys, json_output):
    result = {
        "source_state": {"source_asset_id": "s", "retention_state": "retired", "version": 1},
        "stale_receipt": {"receipt_id": "r"},
    }
    calls = []

    def retire(root, source, **kwargs):
        calls.append((source, kwargs))
        return result

    monkeypatch.setattr(lifecycle, "retire_source", retire)
    args = [
        "data",
        "source",
        "retire",
        "--repository-root",
        str(tmp_path),
        "--source-asset-id",
        "s",
        "--retention-state",
        "retired",
        "--operator",
        "o",
        "--reason",
        "r",
    ]
    assert main(args + (["--json"] if json_output else [])) == 0
    output = capsys.readouterr().out
    assert calls[0][0] == "s" and calls[0][1]["operator"] == "o"
    assert json.loads(output) == result if json_output else "stale receipt: r" in output


def test_impact_failure(monkeypatch, tmp_path, capsys):
    def fail(*args, **kwargs):
        raise lifecycle.SourceImpactError("cannot inspect")

    monkeypatch.setattr(lifecycle, "analyze_repository_impacts", fail)
    assert main(["data", "impact", "--repository-root", str(tmp_path)]) == 2
    assert "error: cannot inspect" in capsys.readouterr().err


def test_retirement_failure(monkeypatch, tmp_path, capsys):
    def fail(*args, **kwargs):
        raise OSError("cannot write")

    monkeypatch.setattr(lifecycle, "retire_source", fail)
    assert (
        main(
            [
                "data",
                "source",
                "retire",
                "--repository-root",
                str(tmp_path),
                "--source-asset-id",
                "s",
                "--retention-state",
                "retired",
                "--operator",
                "o",
                "--reason",
                "r",
            ]
        )
        == 2
    )
    assert "error: cannot write" in capsys.readouterr().err
