from __future__ import annotations

from pathlib import Path

import typer

from .config import load_settings
from .pipeline.orchestrator import FactoryPipeline
from .subtitles.preview import render_subtitle_preview

app = typer.Typer(add_completion=False, no_args_is_help=True)
DEFAULT_PROJECT_ROOT = Path.cwd()
PROJECT_ROOT_OPTION = typer.Option(DEFAULT_PROJECT_ROOT, "--project-root")
OUTPUT_PATH_OPTION = typer.Option(None, "--output-path")
GAMEPLAY_PATH_OPTION = typer.Option(None, "--gameplay-path")


def _build_pipeline(project_root: Path) -> FactoryPipeline:
    settings = load_settings(
        project_root / "configs" / "factory.local.yaml",
        project_root / "configs" / "accounts.local.yaml",
        project_root=project_root,
        env_path=project_root / "configs" / ".env",
    )
    return FactoryPipeline(settings)


@app.command()
def cycle(project_root: Path = PROJECT_ROOT_OPTION) -> None:
    result = _build_pipeline(project_root).run_cycle()
    typer.echo(f"cycle_complete discovered={result.discovered_jobs} processed={result.processed_jobs} scheduled={result.scheduled_jobs}")


@app.command()
def regenerate(project_root: Path = PROJECT_ROOT_OPTION) -> None:
    result = _build_pipeline(project_root).regenerate_batch()
    typer.echo(
        f"regenerate_complete discovered={result.discovered_jobs} processed={result.processed_jobs} scheduled={result.scheduled_jobs}"
    )


@app.command()
def publish_due(project_root: Path = PROJECT_ROOT_OPTION) -> None:
    published = _build_pipeline(project_root).publish_due()
    typer.echo(f"publish_complete published={published}")


@app.command("preview-subtitles")
def preview_subtitles(
    project_root: Path = PROJECT_ROOT_OPTION,
    output_path: Path | None = OUTPUT_PATH_OPTION,
    gameplay_path: Path | None = GAMEPLAY_PATH_OPTION,
) -> None:
    settings = load_settings(
        project_root / "configs" / "factory.local.yaml",
        project_root / "configs" / "accounts.local.yaml",
        project_root=project_root,
        env_path=project_root / "configs" / ".env",
    )
    resolved_output = output_path or (project_root / "artifacts" / "subtitle-preview.mp4")
    preview_path = render_subtitle_preview(
        settings,
        output_path=resolved_output,
        gameplay_path=gameplay_path,
    )
    typer.echo(f"preview_complete output={preview_path}")


if __name__ == "__main__":
    app()
