from __future__ import annotations

from pathlib import Path

import typer

from .config import load_settings
from .pipeline.orchestrator import FactoryPipeline

app = typer.Typer(add_completion=False, no_args_is_help=True)
DEFAULT_PROJECT_ROOT = Path.cwd()
PROJECT_ROOT_OPTION = typer.Option(DEFAULT_PROJECT_ROOT, "--project-root")


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


if __name__ == "__main__":
    app()
