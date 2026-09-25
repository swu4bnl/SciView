"""Metadata-relative SMI calibration and lossless user-mask composition.

The native viewer always uses raw array coordinates (x=column, y=row). WAXS
calibration parameters refer to the backend's transposed three-panel image.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path

import numpy as np

AGB_Q1 = 2 * np.pi / 5.8380  # nm^-1; AgB d001 = 58.380 Angstrom


def detector_kind(field):
    return {"pil2M_image": "saxs", "pil900KW_image": "waxs"}.get(field)


def exclusion_polygons(excluded):
    """Exact integer-pixel raster to rectangles, merging identical adjacent runs.

    Half-pixel edges keep every integer pixel center inside exactly its intended
    region. Holes and single pixels survive; no contour simplification is used.
    """
    excluded = np.asarray(excluded, dtype=bool)
    if excluded.ndim != 2: raise ValueError("Expected a 2D user exclusion mask")
    active, rectangles = {}, []
    for row in range(excluded.shape[0] + 1):
        line = excluded[row] if row < len(excluded) else np.zeros(excluded.shape[1], bool)
        edges = np.diff(np.r_[False, line, False].astype(np.int8))
        runs = set(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))
        for run in list(active):
            if run not in runs:
                first = active.pop(run)
                x0, x1 = run[0] - .5, run[1] - .5
                rectangles.append([[x0, first-.5], [x1, first-.5], [x1, row-.5], [x0, row-.5]])
        for run in runs: active.setdefault(run, row)
    return rectangles


def compose_mask_spec(base, excluded, detector):
    """Preserve the original scientific JSON, adding only user static regions."""
    spec = deepcopy(base)
    shape = tuple(np.asarray(excluded).shape)
    if spec.get("image_shape") is not None and tuple(spec["image_shape"]) != shape:
        raise ValueError(f"Mask detector shape {shape} differs from specification {spec['image_shape']}")
    polygons = exclusion_polygons(excluded)
    nested = "static_regions" in spec or "beamstops" in spec or detector == "saxs"
    regions = spec.setdefault("static_regions", {}) if nested else spec
    for i, polygon in enumerate(polygons):
        name = f"sciview_user_{i}"
        while name in regions: name += "_"
        regions[name] = polygon
    return spec


def load_mask_spec(detector, path=""):
    from smi_tiled.defaults import resolve_mask_path
    resolved = Path(path) if path else resolve_mask_path(None, detector=detector)
    return json.loads(Path(resolved).read_text())


@dataclass(frozen=True)
class GeometrySnapshot:
    uid: str
    detector: str
    shape: tuple
    frame: int
    row: float                 # backend center coordinates
    col: float
    distance_mm: float         # effective backend distance, not raw motor reading
    energy_ev: float
    pixel_mm: float
    arc: float
    bsx: float
    bsx_ref: float
    base_deltas: tuple         # default row/col/distance additive corrections
    metadata: dict
    saxs_geometry: object = None

    def corrected(self, delta):
        dr, dc, dd = delta
        return replace(self, row=self.row+dr, col=self.col+dc, distance_mm=self.distance_mm+dd)

    @property
    def center_xy_raw(self):
        return (self.row, self.col + .08*self.arc) if self.detector == "waxs" else (self.col, self.row)


def resolve_geometry(run, ref, shape, scalars):
    from dataclasses import asdict
    from smi_tiled import resolve_saxs_geometry, resolve_waxs_geometry
    from smi_tiled.defaults import LOADER_DEFAULTS
    from smi_tiled.integrator import WAXSCalibration
    detector = detector_kind(ref.detector)
    if detector is None: raise ValueError("Calibration applies to SAXS/WAXS detector images")
    if ref.stream != "primary":
        raise ValueError("Metadata-resolved calibration/masks currently require primary; raw browsing supports other streams")
    def scalar(name, default):
        values = scalars.get(name)
        if values is None or ref.index >= len(values): return default
        try:
            value = float(values[ref.index])
            return value if np.isfinite(value) else default
        except (ValueError, TypeError): return default
    geo = (resolve_saxs_geometry if detector == "saxs" else resolve_waxs_geometry)(run)
    arc = scalar("waxs_arc", 0.)
    bsx = scalar("waxs_bsx", 0.)
    bsx_ref = bsx - (-4.39)*arc
    arcs, bsxs = scalars.get("waxs_arc"), scalars.get("waxs_bsx")
    if arcs is not None and bsxs is not None and len(arcs) == len(bsxs) and len(arcs)>1:
        if np.isfinite(arcs).all() and np.isfinite(bsxs).all() and np.ptp(arcs)>.5:
            bsx_ref = float(bsxs[0] - np.polyfit(arcs, bsxs, 1)[0]*arcs[0])
    metadata = asdict(geo)
    metadata["selected_frame_scalars"] = {k: scalar(k, None) for k in (
        "energy_energy", "pil2M_motor_x", "pil2M_motor_y", "pil2M_motor_z", "piezo_z", "waxs_arc", "waxs_bsx")}
    # SAXS backend currently resolves one geometry for a run; show exactly that
    # reference rather than pretending its per-frame geometry is implemented.
    energy = scalar("energy_energy", geo.energy_ev) if detector == "waxs" else geo.energy_ev
    if detector == "saxs":
        distance = geo.dist_m*1000
        deltas = (LOADER_DEFAULTS.saxs_row_delta_px, LOADER_DEFAULTS.saxs_col_delta_px, LOADER_DEFAULTS.saxs_distance_delta_mm)
        metadata["scope"] = "Run-reference geometry resolved by smi-tiled (not a per-frame SAXS geometry)"
    else:
        distance = WAXSCalibration().sample_distance_mm
        deltas = (LOADER_DEFAULTS.waxs_row_delta_px, LOADER_DEFAULTS.waxs_col_delta_px, 0.)
        metadata["effective_distance_source"] = "WAXS calibrated backend default; metadata motor distance is informational"
    return GeometrySnapshot(ref.uid, detector, tuple(shape), ref.index,
        geo.beam_center_row_px, geo.beam_center_col_px, distance, energy, .172,
        arc, bsx, bsx_ref, deltas, metadata, geo if detector == "saxs" else None)


def q_map(snapshot):
    """Use smi-tiled's folded WAXS model; exact flat SAXS scattering relation."""
    wavelength = 1239.84198 / snapshot.energy_ev  # nm
    if snapshot.detector == "waxs":
        from smi_tiled.integrator import WAXSCalibration, MultiPanelArcDetector
        cal = WAXSCalibration(energy_kev=snapshot.energy_ev/1000, sample_distance_mm=snapshot.distance_mm,
                              beam_center_row=snapshot.row, beam_center_col=snapshot.col, beam_col_per_arc_deg=.08)
        detector = MultiPanelArcDetector(snapshot.shape[::-1], cal.make_panel_specs(), wavelength,
            pixel_size_mm=snapshot.pixel_mm, sample_distance_mm=snapshot.distance_mm,
            beam_center_px=cal.beam_center_at_angle(snapshot.arc))
        return detector.qmap(snapshot.arc)["qabs"].values.T
    rows, cols = np.indices(snapshot.shape)
    radius = np.hypot(rows-snapshot.row, cols-snapshot.col)*snapshot.pixel_mm
    return 4*np.pi/wavelength * np.sin(.5*np.arctan2(radius, snapshot.distance_mm))


def generated_masks(snapshot, base, *, shadow=True, aperture=True):
    """Return separate raw-coordinate static and generated exclusions."""
    from smi_tiled.integrator import (polygons_to_mask, make_saxs_mask_from_dict,
        make_waxs_mask_callable_from_dict, make_saxs_large_area_masks)
    if "static_regions" in base or "beamstops" in base:
        static = base.get("static_regions", {})
    else:
        static = {k: v for k, v in base.items() if k != "beamstop" and k != "image_shape"}
    static_valid = polygons_to_mask(snapshot.shape, list(static.values()))
    if snapshot.detector == "waxs":
        valid = make_waxs_mask_callable_from_dict(base, snapshot.bsx_ref)(snapshot.shape, snapshot.arc, snapshot.bsx).T
    else:
        geo = snapshot.saxs_geometry
        valid = make_saxs_mask_from_dict(snapshot.shape, base, geo.active_beamstop, geo.beamstop_pos_mm,
                                        (snapshot.row, snapshot.col))
        large, _, _ = make_saxs_large_area_masks(snapshot.shape, q_map(snapshot), [snapshot.arc],
            beam_center_col_px=snapshot.col, waxs_shadow={"enabled": shadow},
            aperture={"enabled": aperture, "agbh_ring_order": 5, "q_margin_fraction": .01})
        valid = valid & np.asarray(large[0])
    return ~static_valid, (~valid & static_valid)


def fit_ring_points(snapshot, points, expected_q=None, *, fit_distance=False):
    """Fit center corrections (and known-q distance) with other geometry fixed.

    Unknown-q fits include the common ring q as a nuisance parameter. Picked
    points can be from an arc; ill-conditioned fits are rejected explicitly.
    """
    from scipy.optimize import least_squares
    from scipy.ndimage import map_coordinates
    points = np.asarray(points, dtype=float)
    if len(points) < 5 or points.shape[1:] != (2,) or not np.isfinite(points).all():
        raise ValueError("Pick at least five well-spaced ring points for refinement")
    if expected_q is not None:
        expected_q = np.asarray(expected_q, dtype=float)
        if expected_q.ndim > 1 or (expected_q.ndim == 1 and len(expected_q) != len(points)):
            raise ValueError("Expected q must be a scalar or one value per ring point")
        if not np.isfinite(expected_q).all() or np.any(expected_q <= 0):
            raise ValueError("Expected ring q must be finite and positive")
    if fit_distance and expected_q is None:
        raise ValueError("A known q (or AgB order) is required to fit distance")
    if np.any(points[:, 0]<0) or np.any(points[:, 0]>=snapshot.shape[1]) or np.any(points[:, 1]<0) or np.any(points[:, 1]>=snapshot.shape[0]):
        raise ValueError("Ring points must lie inside this detector frame")
    def samples(delta):
        s = snapshot.corrected(delta)
        if s.detector == "saxs":
            r = np.hypot(points[:, 0]-s.col, points[:, 1]-s.row)*s.pixel_mm
            return 4*np.pi/(1239.84198/s.energy_ev)*np.sin(.5*np.arctan2(r, s.distance_mm))
        return map_coordinates(q_map(s), [points[:, 1], points[:, 0]], order=1, mode="nearest")
    q0 = np.median(samples((0, 0, 0)))
    unknown = expected_q is None
    initial = [0., 0.] + ([0.] if fit_distance else []) + ([q0] if unknown else [])
    low = [-100., -100.] + ([-snapshot.distance_mm*.5] if fit_distance else []) + ([1e-8] if unknown else [])
    high = [100., 100.] + ([snapshot.distance_mm*.5] if fit_distance else []) + ([max(q0*3, 1.)] if unknown else [])
    def residual(p):
        delta = (p[0], p[1], p[2] if fit_distance else 0.)
        target = p[-1] if unknown else expected_q
        return samples(delta)-target
    fitted = least_squares(residual, initial, bounds=(low, high), loss="soft_l1", f_scale=max(q0*.001, 1e-5), x_scale="jac", max_nfev=100)
    if not fitted.success: raise ValueError("Ring fit did not converge")
    jac = fitted.jac / np.maximum(np.linalg.norm(fitted.jac, axis=0), 1e-30)
    condition = np.linalg.cond(jac)
    if condition > 1e4 or np.any(fitted.active_mask):
        raise ValueError("Ring coverage is insufficient or correction reached bounds; pick points over a wider arc")
    delta = (float(fitted.x[0]), float(fitted.x[1]), float(fitted.x[2]) if fit_distance else 0.)
    return dict(delta=delta, q=float(fitted.x[-1] if unknown else np.mean(expected_q)),
                rms=float(np.sqrt(np.mean(residual(fitted.x)**2))), condition=float(condition), n=len(points))


def refine_ring_pixels(image, snapshot, points, excluded=None, half_width=6):
    """Refine picked ring seeds to subpixel radial maxima in the raw image.

    The native circle pick/snap remains available; this adds intensity-weighted
    subpixel positions before the metadata-relative geometry fit.
    """
    from scipy.ndimage import map_coordinates
    q_values = q_map(snapshot)
    grad_y, grad_x = np.gradient(q_values)
    offsets = np.linspace(-half_width, half_width, half_width*4+1)
    refined = []
    for point in np.asarray(points, dtype=float):
        # The q-gradient follows the physical radial direction even across the
        # folded WAXS panels; a raw-image circle is not a valid WAXS model.
        vector = np.array([map_coordinates(g, [[point[1]], [point[0]]], order=1, mode="nearest")[0]
                           for g in (grad_x, grad_y)])
        direction = vector/max(np.linalg.norm(vector), 1e-12)
        positions = point[None, :] + offsets[:, None]*direction
        values = map_coordinates(np.asarray(image, dtype=float), [positions[:, 1], positions[:, 0]], order=1, mode="constant", cval=np.nan)
        if excluded is not None:
            bad = map_coordinates(np.asarray(excluded, dtype=float), [positions[:, 1], positions[:, 0]], order=0, mode="constant", cval=1)>0
            values[bad] = np.nan
        good = np.isfinite(values)
        if good.sum()<5: continue
        baseline = np.nanpercentile(values, 20)
        weights = np.where(good, np.maximum(values-baseline, 0), 0)
        peak = int(np.argmax(weights))
        if peak in (0, len(offsets)-1) or weights.sum()<=0: continue
        near = abs(np.arange(len(offsets))-peak)<=3
        weights = weights*near
        shift = float(np.sum(offsets*weights)/weights.sum())
        refined.append((point+direction*shift).tolist())
    if len(refined)<5: raise ValueError("Fewer than five ring seeds could be refined; move picks onto the ring or widen the search")
    return refined


def calibration_profiles(image, snapshot, excluded, bins=600):
    """SMI q coordinates with native-style radial/sector diagnostic profiles."""
    q = q_map(snapshot)
    rows, cols = np.indices(snapshot.shape)
    x, y = snapshot.center_xy_raw
    angles = np.degrees(np.arctan2(-(rows-y), cols-x))
    good = np.isfinite(image) & np.isfinite(q) & ~excluded
    if not good.any(): raise ValueError("No valid pixels for calibration profiles")
    edges = np.linspace(float(q[good].min()), float(q[good].max()), bins+1)
    curves = {}
    selections = {"Radial mean": good}
    for name, angle in (("Right pixel sector", 0), ("Left pixel sector", 180),
                        ("Upper pixel sector", 90), ("Lower pixel sector", -90)):
        distance = abs((angles-angle+180)%360-180)
        selections[name] = good & (distance <= 5)
    for name, selected in selections.items():
        total, _ = np.histogram(q[selected], edges, weights=np.asarray(image)[selected])
        count, _ = np.histogram(q[selected], edges)
        curves[name] = np.divide(total, count, out=np.full(bins, np.nan), where=count>0)
    return (edges[:-1]+edges[1:])/2, curves
