from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tictoc_factory.cli import app
from tictoc_factory.pipeline.orchestrator import PipelineRunResult

runner = CliRunner()


class FakePipeline:
    def run_cycle(self) -> PipelineRunResult:
        return PipelineRunResult(discovered_jobs=2, processed_jobs=1, scheduled_jobs=3)

    def regenerate_batch(self) -> PipelineRunResult:
        return PipelineRunResult(discovered_jobs=4, processed_jobs=4, scheduled_jobs=4)

    def publish_due(self) -> int:
        return 2


def test_cli_cycle_emits_pipeline_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("tictoc_factory.cli._build_pipeline", lambda project_root: FakePipeline())

    result = runner.invoke(app, ["cycle", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "cycle_complete discovered=2 processed=1 scheduled=3" in result.stdout


def test_cli_regenerate_emits_pipeline_summary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("tictoc_factory.cli._build_pipeline", lambda project_root: FakePipeline())

    result = runner.invoke(app, ["regenerate", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "regenerate_complete discovered=4 processed=4 scheduled=4" in result.stdout


def test_cli_publish_due_emits_publish_count(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("tictoc_factory.cli._build_pipeline", lambda project_root: FakePipeline())

    result = runner.invoke(app, ["publish-due", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "publish_complete published=2" in result.stdout
