"""Display-only frame naming and waterfall offsets; independent of Qt."""
import numpy as np


def frame_label(index, signal="frame", columns=None):
    prefix = f"Frame {index}"
    values = (columns or {}).get(signal)
    if signal == "frame" or values is None or index >= len(values):
        return prefix
    value = values[index]
    if isinstance(value, bytes): value = value.decode("utf-8", errors="replace")
    if isinstance(value, (float, np.floating)):
        value = f"{value:.6g}" if np.isfinite(value) else "unavailable"
    units = {"energy_energy": " eV", "fn:eV": " eV", "incident_angle_deg": "°",
             "waxs_arc": "°", "fn:ai": "°"}
    return f"{prefix} · {signal}={value}{units.get(signal, '')}"


def waterfall_values(q, intensities, *, power=0, spacing=.05, logarithmic=True):
    """Offsets affect presentation only. Log spacing is in decades per trace."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        scaled = np.asarray(intensities, dtype=float) * np.asarray(q, dtype=float)[None, :]**power
        if logarithmic:
            # Shift in log space without constructing potentially overflowing
            # intensities; caller plots these values with a log-labelled axis.
            return np.where(scaled > 0, np.log10(scaled), np.nan) + np.arange(len(scaled))[:, None]*spacing
        finite = scaled[np.isfinite(scaled)]
        span = float(np.ptp(np.percentile(finite, [2, 98]))) if finite.size else 1.
        return scaled + np.arange(len(scaled))[:, None] * spacing * max(span, 1e-30)
