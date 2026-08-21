"""
Tab modules for SciAnalysis GUI.

All tab classes are loaded lazily — imported only when first accessed.
This keeps matplotlib and other heavy dependencies out of the startup
critical path.
"""

_TAB_MODULES = {
    "CalibrationApp":   "calibration_tab",
    "ImageBrowserApp":  "image_browser_tab",
    "MaskApp":          "mask_tab",
    "ReductionTab":     "reduction_tab",
    "TransformTab":     "transform_tab",
    "BatchTab":         "batch_tab",
    "TiledBrowserTab":  "tiled_browser_tab",
    "ProtocolPreviewTab": "protocol_preview_tab",
    "InfoTab":          "info_tab",
    "BaseImageTab":     "base_image_tab",
}


def __getattr__(name):
    module_name = _TAB_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    mod = importlib.import_module(f".{module_name}", package=__name__)
    globals()[name] = getattr(mod, name)  # cache for subsequent accesses
    return globals()[name]