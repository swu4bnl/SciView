"""Beamline-neutral helpers for browsing Tiled data sources.

The GUI layer should use this module through ``ImageService`` instead of
reaching into Tiled client objects directly.  Search helpers keep data access
lazy: they inspect metadata and do not call array ``read()`` until an image is
explicitly loaded.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from sciview.data.models import ImageRef
from utils.tiled_client import tiled_manager


@dataclass(slots=True)
class TiledAuthState:
    """Current authentication/connection state for one configured profile."""

    profile_name: str
    authenticated: bool
    username: str | None = None
    error: str | None = None


@dataclass(slots=True)
class TiledScanSummary:
    """Metadata-only summary for one Tiled run."""

    uid: str
    scan_id: int | None
    filename: str = ""
    scan_type: str = ""
    measure_type: str = ""
    sample_name: str = ""
    sample_savename: str = ""
    proposal_id: str = ""
    cycle: str = ""
    experiment_alias: str = ""
    username: str = ""
    detectors: list[str] = field(default_factory=list)
    time: float | None = None
    exit_status: str = ""
    n_steps: int | str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TiledSearchResult:
    """Result payload for a metadata-only scan search."""

    scans: list[TiledScanSummary]
    scanned_ids: int
    total_count: int = 0
    scan_id_min: int | None = None
    scan_id_max: int | None = None
    query_description: str = ""


def tiled_is_available() -> bool:
    return tiled_manager.is_available()


def tiled_import_error() -> str | None:
    return tiled_manager.get_import_error()


def tiled_default_profile() -> str | None:
    profile, _detector = tiled_manager.get_default_settings()
    return profile


def tiled_catalogs() -> list[dict[str, str]]:
    catalogs: list[dict[str, str]] = []
    for profile_name, profile in tiled_manager.get_profiles().items():
        path = "/".join(profile.get("path", [])) or "/"
        catalogs.append(
            {
                "profile_name": profile_name,
                "catalog_label": path,
                "description": str(profile.get("description", "")),
            }
        )
    return catalogs


def _profile(profile_name: str) -> dict[str, Any]:
    return dict(tiled_manager.get_profiles().get(profile_name, {}))


def _search_config(profile_name: str) -> dict[str, Any]:
    return dict(_profile(profile_name).get("search", {}))


def tiled_auth_state(profile_name: str | None = None) -> TiledAuthState:
    profile_name = profile_name or tiled_default_profile() or ""
    if not tiled_is_available():
        return TiledAuthState(profile_name, False, error=tiled_import_error())

    client = tiled_manager._clients.get(profile_name)
    if client is None:
        return TiledAuthState(profile_name, False)

    username = None
    try:
        username = getattr(getattr(client, "context", None), "username", None)
    except Exception:
        username = None
    return TiledAuthState(profile_name, True, username=username)


def tiled_authenticate(
    profile_name: str | None = None,
    *,
    username: str | None = None,
    password: str | None = None,
    interactive_fallback: bool = True,
) -> TiledAuthState:
    """Create or refresh a cached Tiled client.

    The current project dependency uses Tiled's interactive ``client.login()``
    flow, so username/password are accepted for future API compatibility but
    are not passed through here.
    """

    del username, password, interactive_fallback
    profile_name = profile_name or tiled_default_profile() or ""
    if not tiled_is_available():
        return TiledAuthState(profile_name, False, error=tiled_import_error())

    tiled_manager._clients.pop(profile_name, None)
    client = tiled_manager.get_or_create_client(profile_name)
    if client is None:
        return TiledAuthState(profile_name, False, error=f"Could not connect to {profile_name}")
    return tiled_auth_state(profile_name)


def _metadata(run: Any) -> dict[str, Any]:
    try:
        md = run.metadata
    except Exception:
        return {}
    try:
        return dict(md)
    except Exception:
        return md if isinstance(md, dict) else {}


def _start_stop(run: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    md = _metadata(run)
    start = md.get("start", {})
    stop = md.get("stop", {})
    return (start if isinstance(start, dict) else {}, stop if isinstance(stop, dict) else {})


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_nested(mapping: dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    current: Any = mapping
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _first_metadata_value(metadata: dict[str, Any], paths: list[str], default: Any = "") -> Any:
    for path in paths:
        value = _get_nested(metadata, path)
        if value not in (None, ""):
            return value
    return default


def _detector_field_choices(detectors: list[Any], profile_name: str | None) -> list[str]:
    profile_detectors: list[str] = []
    if profile_name is not None:
        profile_detectors = list(_profile(profile_name).get("default_detectors", {}).keys())

    raw_detectors = [str(det) for det in detectors if str(det)]
    if not raw_detectors:
        return profile_detectors

    choices: list[str] = []
    for detector in raw_detectors:
        candidates = [detector]
        if not detector.endswith("_image"):
            candidates.append(f"{detector}_image")
        candidates.extend(
            configured
            for configured in profile_detectors
            if configured == detector or configured.startswith(f"{detector}_")
        )
        preferred = next((candidate for candidate in candidates if candidate in profile_detectors), candidates[0])
        if preferred not in choices:
            choices.append(preferred)
    return choices


def _summary_from_run(
    run: Any,
    fallback_scan_id: int | None = None,
    profile_name: str | None = None,
) -> TiledScanSummary:
    md = _metadata(run)
    start, stop = _start_stop(run)
    detectors = start.get("detectors", [])
    if isinstance(detectors, str):
        detectors = [detectors]
    if not isinstance(detectors, list):
        detectors = []

    num_events = stop.get("num_events", {})
    if isinstance(num_events, dict):
        n_steps = num_events.get("primary")
    else:
        n_steps = num_events

    summary_fields = {}
    if profile_name is not None:
        summary_fields = dict(_search_config(profile_name).get("summary_fields", {}))

    proposal_id = _first_metadata_value(
        md,
        summary_fields.get(
            "proposal_id",
            ["start.proposal.proposal_id", "start.proposal_id", "start.data_session", "start.institution"],
        ),
    )
    sample_savename = _first_metadata_value(
        md,
        summary_fields.get("sample_savename", ["start.sample_savename", "start.sample_save_name"]),
    )
    filename = _first_metadata_value(
        md,
        summary_fields.get(
            "filename",
            ["start.filename", "start.file_name", "start.sample_filename", "start.sample_savename"],
        ),
    )
    measure_type = str(
        _first_metadata_value(
            md,
            summary_fields.get("measure_type", ["start.measure_type", "start.measurement_type"]),
        )
        or ""
    )
    scan_type = str(start.get("plan_name", start.get("scan_type", measure_type)) or "")
    uid = str(start.get("uid") or getattr(run, "key", "") or "")
    scan_id = _as_int(start.get("scan_id"))
    return TiledScanSummary(
        uid=uid,
        scan_id=scan_id if scan_id is not None else fallback_scan_id,
        filename=str(filename),
        scan_type=scan_type,
        measure_type=measure_type,
        sample_name=str(start.get("sample_name", start.get("sample", start.get("Sample", ""))) or ""),
        sample_savename=str(sample_savename or ""),
        proposal_id=str(proposal_id),
        cycle=str(_first_metadata_value(md, summary_fields.get("cycle", ["start.cycle"])) or ""),
        experiment_alias=str(
            _first_metadata_value(
                md,
                summary_fields.get(
                    "experiment_alias",
                    ["start.experiment_alias_directory", "start.experiment_alias", "start.project_name"],
                ),
            )
            or ""
        ),
        username=str(start.get("operator", start.get("username", start.get("user", ""))) or ""),
        detectors=_detector_field_choices(detectors, profile_name),
        time=start.get("time"),
        exit_status=str(stop.get("exit_status", "") or ""),
        n_steps=n_steps,
        metadata={"start": start, "stop": stop},
    )


def _run_for_scan_id(profile_name: str, scan_id: int) -> Any | None:
    uid = tiled_manager.scanid_to_uid(scan_id, profile_name)
    catalog = tiled_manager.get_or_load_catalog(profile_name)
    if catalog is None:
        return None
    if uid:
        try:
            return catalog[uid]
        except Exception:
            pass
    try:
        return catalog[scan_id]
    except Exception:
        return None


def _pattern_matches(value: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    value = value or ""
    if pattern.startswith("re:"):
        try:
            return re.search(pattern[3:], value) is not None
        except re.error:
            return False
    if any(char in pattern for char in "*?[]"):
        return fnmatch.fnmatchcase(value.lower(), pattern.lower())
    return pattern.lower() in value.lower()


def _eq_query(key: str, value: str):
    from tiled.queries import Eq

    return Eq(key, value)


def _search_eq(node: Any, key: str, value: str) -> Any:
    if value in (None, ""):
        return node
    return node.search(_eq_query(key, str(value)))


def _apply_remote_filters(node: Any, filters: dict[str, Any], remote_fields: dict[str, str]) -> Any:
    for name, key in remote_fields.items():
        value = filters.get(name)
        if value in (None, ""):
            continue
        node = _search_eq(node, key, str(value))
    return node


def _iter_runs(node: Any) -> list[Any]:
    if node is None:
        return []
    try:
        values = node.values()
        return list(values)
    except Exception:
        pass
    try:
        return [run for _key, run in node.items()]
    except Exception:
        pass
    try:
        return list(node)
    except Exception:
        return []


def _result_from_scans(
    scans: list[TiledScanSummary],
    *,
    scanned_ids: int,
    query_description: str = "",
) -> TiledSearchResult:
    scan_ids = [scan.scan_id for scan in scans if scan.scan_id is not None]
    return TiledSearchResult(
        scans=scans,
        scanned_ids=scanned_ids,
        total_count=len(scans),
        scan_id_min=min(scan_ids) if scan_ids else None,
        scan_id_max=max(scan_ids) if scan_ids else None,
        query_description=query_description,
    )


def tiled_search_by_filters(
    *,
    profile_name: str,
    filters: dict[str, Any],
    use_profile_defaults: bool = True,
) -> TiledSearchResult:
    """Search a Tiled catalog using profile-configured metadata fields.

    ``filters`` is intentionally generic so beamline-specific keys can live in
    the profile config. Keys mapped in ``required_fields`` or
    ``optional_fields`` become Tiled ``Eq`` queries; keys mapped in
    ``local_filters`` are applied to metadata summaries with substring, glob,
    or ``re:`` matching.
    """

    catalog = tiled_manager.get_or_load_catalog(profile_name)
    if catalog is None:
        raise RuntimeError(f"Could not load Tiled catalog for profile: {profile_name}")

    config = _search_config(profile_name)
    defaults = dict(config.get("defaults", {})) if use_profile_defaults else {}
    effective_filters = {**defaults, **{k: v for k, v in filters.items() if v not in (None, "")}}

    required_fields = dict(config.get("required_fields", {}))
    optional_fields = dict(config.get("optional_fields", {}))
    remote_fields = {**required_fields, **optional_fields}
    local_filters = dict(config.get("local_filters", {}))

    node = _apply_remote_filters(catalog, effective_filters, remote_fields)

    try:
        available_count = len(node)
    except Exception:
        available_count = 0

    scans = [_summary_from_run(run, profile_name=profile_name) for run in _iter_runs(node)]
    for filter_name, paths in local_filters.items():
        pattern = effective_filters.get(filter_name)
        if not pattern:
            continue
        scans = [
            scan
            for scan in scans
            if _pattern_matches(str(_first_metadata_value(scan.metadata, list(paths))), str(pattern))
        ]

    scans.sort(key=lambda item: item.scan_id if item.scan_id is not None else -1)
    query_description = ", ".join(f"{key}={value}" for key, value in effective_filters.items())
    return _result_from_scans(scans, scanned_ids=available_count, query_description=query_description)


def tiled_run_metadata(profile_name: str, scan_id: int) -> dict[str, Any]:
    run = _run_for_scan_id(profile_name, scan_id)
    return _metadata(run) if run is not None else {}


def tiled_load_array(profile_name: str, scan_id: int, detector: str, uid: str | None = None) -> np.ndarray:
    if uid:
        array, metadata = tiled_manager._load_image_by_uid(uid, detector, profile_name)
    else:
        array, metadata = tiled_manager.load_image_data(scan_id, detector, profile_name)
    if array is None:
        raise RuntimeError(metadata.get("error", f"Could not load scan {scan_id}"))
    arr = np.asarray(array)
    while arr.ndim > 2 and arr.shape[0] == 1:
        arr = arr[0]
    return arr


def tiled_load_ref(profile_name: str, scan_id: int, detector: str, uid: str | None = None) -> ImageRef:
    source_uri = tiled_manager.create_pseudo_path(scan_id, detector, profile_name)
    metadata = {
        "profile_name": profile_name,
        "scan_id": scan_id,
        "detector": detector,
        "uid": uid,
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }
    return ImageRef(source_uri=source_uri, source_type="tiled", metadata=metadata)
