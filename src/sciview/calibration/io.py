"""Calibration read/write helpers used by interfaces and scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(slots=True)
class CalibrationIOPayload:
    """Serializable calibration payload for YAML persistence."""

    wavelength_A: float
    image_size: list[int]
    pixel_size_um: float
    beam_position: list[float]
    distance: float
    energy_eV: float

    def to_dict(self) -> dict[str, float | list[float] | list[int]]:
        return {
            "wavelength_A": self.wavelength_A,
            "image_size": self.image_size,
            "pixel_size_um": self.pixel_size_um,
            "beam_position": self.beam_position,
            "distance": self.distance,
        }


def build_calibration_payload(
    *,
    wavelength_A: float,
    pixel_size_um: float,
    beam_position: tuple[float, float] | list[float],
    distance_m: float,
    image_size: tuple[int, int] | list[int],
    hc_over_e_eV_A: float,
) -> CalibrationIOPayload:
    """Build a normalized calibration payload from UI or backend values."""

    energy_eV = hc_over_e_eV_A / wavelength_A if wavelength_A > 0 else 0.0
    return CalibrationIOPayload(
        wavelength_A=float(wavelength_A),
        image_size=[int(image_size[0]), int(image_size[1])],
        pixel_size_um=float(pixel_size_um),
        beam_position=[float(beam_position[0]), float(beam_position[1])],
        distance=float(distance_m),
        energy_eV=float(energy_eV),
    )


def write_calibration_yaml(payload: CalibrationIOPayload, output_path: str | Path) -> Path:
    """Write calibration YAML to disk and return the resolved output path."""

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    header = (
        f"wavelength_A: {payload.wavelength_A}  # X-ray wavelength in Angstroms ({payload.energy_eV} eV)\n"
        f"image_size: {payload.image_size}  # [horizontal, vertical] in pixels\n"
        f"pixel_size_um: {payload.pixel_size_um}  # pixel size in microns\n"
        f"beam_position: {payload.beam_position}  # beam position in pixels\n"
        f"distance: {payload.distance}  # sample to detector distance in meters\n"
    )

    target.write_text(header, encoding="utf-8")

    # Validate parseability of generated file for downstream consumers.
    yaml.safe_load(target.read_text(encoding="utf-8"))
    return target
