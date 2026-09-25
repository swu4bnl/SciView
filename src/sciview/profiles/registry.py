"""Catalog registration, independent of optional scientific backend imports."""
from sciview.profiles.cms_profile import TILED_PROFILES as CMS_PROFILES

TILED_PROFILES = dict(CMS_PROFILES)
TILED_PROFILES["smi_migration"] = {
    "description": "SMI (12-ID)",
    "uri": "https://tiled.nsls2.bnl.gov",
    "path": ["smi", "migration"],
    "requires_login": True,
    "lazy_frames": True,
    "default_detectors": {"pil2M_image": "SAXS", "pil900KW_image": "WAXS"},
    "data_access_path": ["primary", "{detector}"],
    "search": {
        "required_fields": {"cycle": "start.cycle", "proposal_id": "start.data_session"},
        "optional_fields": {},
        "defaults": {},
        "summary_fields": {
            "filename": ["start.sample_name", "start.filename"],
            "measure_type": ["start.plan_name"],
        },
    },
}


def get_default_tiled_settings():
    import os
    name = os.environ.get("SCIVIEW_PROFILE", next(iter(CMS_PROFILES)))
    if name not in TILED_PROFILES:
        name = next(iter(CMS_PROFILES))
    return name, next(iter(TILED_PROFILES[name]["default_detectors"]), None)
