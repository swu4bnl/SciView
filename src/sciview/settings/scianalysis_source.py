"""Resolve which SciAnalysis source SciView should use."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


SciAnalysisSourceMode = Literal["auto", "pixi", "local", "custom"]


@dataclass(frozen=True, slots=True)
class SciAnalysisSourceConfig:
    """Resolved SciAnalysis source selection."""

    mode: SciAnalysisSourceMode
    root: Path | None
    import_path: Path | None
    description: str


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_mode(value: str | None) -> SciAnalysisSourceMode:
    mode = (value or "auto").strip().lower()
    if mode not in {"auto", "pixi", "local", "custom"}:
        return "auto"
    return mode  # type: ignore[return-value]


def _resolve_checkout_root(candidate: str | Path | None) -> Path | None:
    if candidate is None:
        return None

    path = Path(candidate).expanduser()
    if not path.exists():
        return None

    if (path / "SciAnalysis").is_dir():
        return path.resolve()

    if path.name == "SciAnalysis" and (path / "XSAnalysis").is_dir():
        return path.resolve().parent

    return None


def resolve_scianalysis_source(
    mode: str | None = None,
    source_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> SciAnalysisSourceConfig:
    """Resolve the desired SciAnalysis source from env/config."""

    selected_mode = _normalize_mode(mode or os.getenv("SCIVIEW_SCIANALYSIS_SOURCE"))
    configured_path = source_path if source_path is not None else os.getenv("SCIVIEW_SCIANALYSIS_PATH", "").strip()
    workspace = Path(workspace_root).resolve() if workspace_root is not None else _workspace_root()

    def make_config(resolved_mode: SciAnalysisSourceMode, root: Path | None) -> SciAnalysisSourceConfig:
        import_path = root.parent if root is not None else None
        description = {
            "pixi": "Pixi-managed SciAnalysis package",
            "local": "Local SciAnalysis checkout",
            "custom": "Custom SciAnalysis checkout",
            "auto": "Auto-selected SciAnalysis source",
        }[resolved_mode]
        return SciAnalysisSourceConfig(mode=resolved_mode, root=root, import_path=import_path, description=description)

    if selected_mode == "pixi":
        return make_config("pixi", None)

    if selected_mode == "custom":
        root = _resolve_checkout_root(configured_path)
        return make_config("custom", root)

    if selected_mode == "local":
        root = _resolve_checkout_root(configured_path) if configured_path else _resolve_checkout_root(workspace / "external" / "SciAnalysis")
        return make_config("local", root)

    # auto
    root = _resolve_checkout_root(configured_path)
    if root is not None:
        return make_config("custom", root)

    root = _resolve_checkout_root(workspace / "external" / "SciAnalysis")
    if root is not None:
        return make_config("local", root)

    return make_config("pixi", None)


def prepare_scianalysis_source(config: SciAnalysisSourceConfig) -> None:
    """Add the selected SciAnalysis checkout to sys.path when needed."""

    if config.import_path is None:
        return

    import_path = str(config.import_path)
    if import_path not in sys.path:
        sys.path.insert(0, import_path)
