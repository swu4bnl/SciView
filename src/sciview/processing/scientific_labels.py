"""Canonical scientific labels for reduction and reciprocal-space plots."""

from __future__ import annotations


RECIPROCAL_ANGSTROM = r"$\mathrm{\AA}^{-1}$"
DEGREES = r"$^\circ$"
INTENSITY = r"Intensity (a.u.)"


_REDUCTION_LABELS = {
    "circular_average": (rf"$q$ ({RECIPROCAL_ANGSTROM})", r"$I(q)$ (a.u.)"),
    "sector_average": (rf"$q$ ({RECIPROCAL_ANGSTROM})", r"$I(q)$ (a.u.)"),
    "linecut_q": (rf"$q$ ({RECIPROCAL_ANGSTROM})", r"$I(q)$ (a.u.)"),
    "linecut_angle": (rf"$\chi$ ({DEGREES})", r"$I(\chi)$ (a.u.)"),
}

_TRANSFORM_LABELS = {
    "q_image": (rf"$q_x$ ({RECIPROCAL_ANGSTROM})", rf"$q_z$ ({RECIPROCAL_ANGSTROM})"),
    "q_phi_image": (rf"$q$ ({RECIPROCAL_ANGSTROM})", rf"$\phi$ ({DEGREES})"),
    "qr_qz_image": (rf"$q_r$ ({RECIPROCAL_ANGSTROM})", rf"$q_z$ ({RECIPROCAL_ANGSTROM})"),
}

_PLOT_TITLES = {
    "circular_average": "Circular Average",
    "sector_average": "Sector Average",
    "linecut_q": r"Line Cut $I(q)$",
    "linecut_angle": r"Azimuthal Line Cut $I(\chi)$",
    "q_image": r"$q_x$-$q_z$ Intensity Map",
    "q_phi_image": r"$q$-$\phi$ Intensity Map",
    "qr_qz_image": r"$q_r$-$q_z$ Intensity Map",
}


def reduction_axis_labels(operation: str, *, calibrated: bool = True) -> tuple[str, str]:
    if calibrated and operation in _REDUCTION_LABELS:
        return _REDUCTION_LABELS[operation]
    if operation == "linecut_angle":
        return rf"$\chi$ ({DEGREES})", r"$I(\chi)$ (a.u.)"
    return "Detector radius (px)", INTENSITY


def transform_axis_labels(operation: str) -> tuple[str, str]:
    return _TRANSFORM_LABELS.get(operation, ("x", "y"))


def scientific_plot_title(operation: str) -> str:
    return _PLOT_TITLES.get(operation, operation.replace("_", " ").title())
