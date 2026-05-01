"""Recipe YAML IO and validation for backend processing configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from sciview.data.models import ProcessingRecipe


def validate_recipe(recipe: ProcessingRecipe) -> None:
    """Validate a ProcessingRecipe and raise ValueError for invalid fields."""

    if not recipe.name.strip():
        raise ValueError("Recipe name is required")
    if not recipe.operation.strip():
        raise ValueError("Recipe operation is required")

    outputs = recipe.outputs
    if outputs and not isinstance(outputs, dict):
        raise ValueError("Recipe outputs must be a mapping")

    formats = outputs.get("formats")
    if formats is not None:
        if not isinstance(formats, list) or not all(isinstance(item, str) for item in formats):
            raise ValueError("Recipe output formats must be a list of strings")


def load_recipe(path: str | Path) -> ProcessingRecipe:
    """Load a recipe YAML file into a validated ProcessingRecipe."""

    recipe_path = Path(path)
    payload = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    recipe = ProcessingRecipe.from_dict(payload)
    validate_recipe(recipe)
    return recipe


def save_recipe(recipe: ProcessingRecipe, path: str | Path) -> None:
    """Persist a validated ProcessingRecipe to YAML."""

    validate_recipe(recipe)
    recipe_path = Path(path)
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text(
        yaml.safe_dump(recipe.to_dict(), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )