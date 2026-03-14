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


def test_cli_preview_subtitles_renders_preview(monkeypatch, tmp_path: Path) -> None:
    preview_path = tmp_path / "preview.mp4"

    def fake_load_settings(factory_config_path: Path, accounts_config_path: Path | None = None, **kwargs):
        return object()

    def fake_render(settings, *, output_path: Path, gameplay_path: Path | None = None) -> Path:
        assert output_path == preview_path
        assert gameplay_path is None
        output_path.write_bytes(b"preview")
        return output_path

    monkeypatch.setattr("tictoc_factory.cli.load_settings", fake_load_settings)
    monkeypatch.setattr("tictoc_factory.cli.render_subtitle_preview", fake_render)

    result = runner.invoke(
        app,
        ["preview-subtitles", "--project-root", str(tmp_path), "--output-path", str(preview_path)],
    )

    assert result.exit_code == 0
    assert f"preview_complete output={preview_path}" in result.stdout
