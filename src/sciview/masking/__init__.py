"""Mask read/write helpers for SciView."""

from .io import coerce_mask_to_bool, export_mask_file, load_mask_file

# operations.py requires scipy — import lazily to keep the package importable without it.
def __getattr__(name):
    _ops = ("close_mask_holes", "dilate_mask", "erode_mask", "sobel_edge_mask", "watershed_fill_mask")
    if name in _ops:
        from . import operations as _m
        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
	"load_mask_file",
	"export_mask_file",
	"erode_mask",
	"dilate_mask",
	"close_mask_holes",
	"sobel_edge_mask",
	"watershed_fill_mask",
]