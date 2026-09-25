"""Scoped metadata facets; never enumerate runs or read detector arrays."""
from datetime import date
from time import monotonic

import httpx

from sciview.sources.frame_source import filtered_catalog

API = "https://api.nsls2.bnl.gov/v1"


def cycle_choices():
    # Keep known/current cycles available even if the facility API is offline.
    year = max(2026, date.today().year)
    cycles = {f"{y}-{c}" for y in range(2014, year + 1) for c in (1, 2, 3)}
    try:
        response = httpx.get(f"{API}/facility/nsls2/cycles", timeout=5)
        response.raise_for_status()
        cycles.update(response.json().get("cycles", []))
    except httpx.HTTPError:
        pass
    return sorted(cycles, reverse=True)


class SmiFacets:
    """Worker-owned five-minute cache. Authentication changes create a new one."""
    def __init__(self, catalog):
        self.catalog = catalog
        self._cache = {}

    def _cached(self, key, fetch):
        found = self._cache.get(key)
        if found is not None and monotonic() - found[0] < 300:
            return found[1]
        result = fetch()
        self._cache[key] = (monotonic(), result)
        return result

    def cycle_filter(self, cycle):
        if not cycle:
            return {}
        if cycle != "commissioning":
            return {"start.cycle": cycle}
        def fetch():
            response = httpx.get(f"{API}/proposals/commissioning", params={"beamline": "SMI"}, timeout=5)
            response.raise_for_status()
            return [f"pass-{p}" for p in response.json()["commissioning_proposals"]]
        # An empty list deliberately matches nothing, never an unfiltered catalog.
        return {"data_sessions": self._cached("commissioning", fetch)}

    def distinct(self, field, filters):
        key = (field, tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in sorted(filters.items())))
        def fetch():
            node = filtered_catalog(self.catalog, filters)
            url = node.item["links"]["self"].replace("/metadata/", "/distinct/", 1)
            response = node.context.http_client.get(url, params={
                **getattr(node, "_queries_as_params", {}), "metadata": field, "counts": "true",
            }, timeout=12)
            response.raise_for_status()
            return [entry for entry in response.json().get("metadata", {}).get(field, [])
                    if entry.get("value") not in (None, "")]
        return self._cached(key, fetch)
