"""Canonical scientific labels for reduction and reciprocal-space plots."""

from __future__ import annotations


RECIPROCAL_ANGSTROM = "Å⁻¹"
DEGREES = "°"
INTENSITY = "Intensity (a.u.)"


_REDUCTION_LABELS = {
    "circular_average": (f"q ({RECIPROCAL_ANGSTROM})", "I(q) (a.u.)"),
    "sector_average": (f"q ({RECIPROCAL_ANGSTROM})", "I(q) (a.u.)"),
    "linecut_q": (f"q ({RECIPROCAL_ANGSTROM})", "I(q) (a.u.)"),
    "linecut_angle": (f"χ ({DEGREES})", "I(χ) (a.u.)"),
}

_TRANSFORM_LABELS = {
    "q_image": (f"q_x ({RECIPROCAL_ANGSTROM})", f"q_z ({RECIPROCAL_ANGSTROM})"),
    "q_phi_image": (f"q ({RECIPROCAL_ANGSTROM})", f"φ ({DEGREES})"),
    "qr_qz_image": (f"q_r ({RECIPROCAL_ANGSTROM})", f"q_z ({RECIPROCAL_ANGSTROM})"),
}

_PLOT_TITLES = {
    "circular_average": "Circular Average",
    "sector_average": "Sector Average",
    "linecut_q": "Line Cut I(q)",
    "linecut_angle": "Azimuthal Line Cut I(χ)",
    "q_image": "q_x-q_z Intensity Map",
    "q_phi_image": "q-φ Intensity Map",
    "qr_qz_image": "q_r-q_z Intensity Map",
}


def reduction_axis_labels(operation: str, *, calibrated: bool = True) -> tuple[str, str]:
    if calibrated and operation in _REDUCTION_LABELS:
        return _REDUCTION_LABELS[operation]
    if operation == "linecut_angle":
        return f"χ ({DEGREES})", "I(χ) (a.u.)"
    return "Detector radius (px)", INTENSITY


def transform_axis_labels(operation: str) -> tuple[str, str]:
    return _TRANSFORM_LABELS.get(operation, ("x", "y"))


def scientific_plot_title(operation: str) -> str:
    return _PLOT_TITLES.get(operation, operation.replace("_", " ").title())
