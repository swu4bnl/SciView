"""Shared interface services used by GUI frontends."""

from .image_service import ImageService
from .workspace_controller import WorkspaceController

__all__ = ["WorkspaceController", "ImageService"]