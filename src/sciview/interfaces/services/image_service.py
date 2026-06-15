"""Image/data access service for GUI frontends."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from sciview.data.models import Dataset, ImageRef
from sciview.sources.filesystem_source import open_dataset, resolve_local_path, scan_directory
from sciview.sources import tiled_source


class ImageService:
    """Backend-backed service used by interface layers for image IO."""

    def scan_local_directory(self, directory: str | Path, *, recursive: bool = False) -> list[ImageRef]:
        return scan_directory(directory, recursive=recursive)

    def open_local_dataset(self, directory: str | Path, *, recursive: bool = False) -> Dataset:
        return open_dataset(directory, recursive=recursive)

    def load_array(self, image_ref: ImageRef) -> np.ndarray:
        path = resolve_local_path(image_ref)
        suffix = path.suffix.lower()
        if suffix == ".npy":
            return np.asarray(np.load(path))
        if suffix in {".tif", ".tiff", ".png", ".jpg", ".jpeg"}:
            with Image.open(path) as img:
                return np.asarray(img)

        raise ValueError(f"Unsupported image format for array load: {suffix}")

    def tiled_is_available(self) -> bool:
        return tiled_source.tiled_is_available()

    def tiled_import_error(self) -> str | None:
        return tiled_source.tiled_import_error()

    def tiled_catalogs(self) -> list[dict[str, str]]:
        return tiled_source.tiled_catalogs()

    def tiled_default_profile(self) -> str | None:
        return tiled_source.tiled_default_profile()

    def tiled_auth_state(self, profile_name: str | None = None) -> tiled_source.TiledAuthState:
        return tiled_source.tiled_auth_state(profile_name)

    def tiled_authenticate(
        self,
        profile_name: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        interactive_fallback: bool = True,
    ) -> tiled_source.TiledAuthState:
        return tiled_source.tiled_authenticate(
            profile_name,
            username=username,
            password=password,
            interactive_fallback=interactive_fallback,
        )

    def tiled_search_by_filters(
        self,
        *,
        profile_name: str,
        filters: dict,
        use_profile_defaults: bool = True,
    ) -> tiled_source.TiledSearchResult:
        return tiled_source.tiled_search_by_filters(
            profile_name=profile_name,
            filters=filters,
            use_profile_defaults=use_profile_defaults,
        )

    def tiled_run_metadata(self, profile_name: str, scan_id: int) -> dict:
        return tiled_source.tiled_run_metadata(profile_name, scan_id)

    def tiled_load_array(
        self,
        *,
        profile_name: str,
        scan_id: int,
        detector: str,
        uid: str | None = None,
        progress_callback=None,
        retry_callback=None,
    ) -> np.ndarray:
        return tiled_source.tiled_load_array(
            profile_name,
            scan_id,
            detector,
            uid=uid,
            progress_callback=progress_callback,
            retry_callback=retry_callback,
        )

    def tiled_load_ref(
        self,
        *,
        profile_name: str,
        scan_id: int,
        detector: str,
        uid: str | None = None,
    ) -> ImageRef:
        return tiled_source.tiled_load_ref(profile_name, scan_id, detector, uid=uid)
