"""Lazy Bluesky/Tiled frame access. No detector reads during discovery/search."""
from collections import OrderedDict
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import urlencode

import numpy as np

from sciview.sources.tiled_source import TiledSearchResult, _summary_from_run


@dataclass(frozen=True)
class FrameRef:
    profile: str
    uid: str
    stream: str
    detector: str
    index: int

    @property
    def uri(self):
        return "tiled-frame://" + self.profile + "/" + self.uid + "?" + urlencode({
            "stream": self.stream, "detector": self.detector, "frame": self.index})


@dataclass
class FrameSequence:
    profile: str
    uid: str
    stream: str
    fields: dict
    scalars: dict
    streams: list

    def count(self, detector):
        shape = self.fields[detector]
        return int(np.prod(shape[:-2])) if len(shape) > 2 else 1

    def axes(self, detector):
        n = self.count(detector)
        return {k: v for k, v in self.scalars.items()
                if len(v) == n and np.issubdtype(v.dtype, np.number)}

    def order(self, detector, axis="frame"):
        values = self.axes(detector).get(axis)
        if values is None:
            return np.arange(self.count(detector))
        # Stable ties preserve repeated energies; NaNs remain available at end.
        return np.argsort(values, kind="stable")


def normalize_scalars(data, derive=None):
    """Decode and order scalars only; image storage remains acquisition-ordered."""
    columns = {}
    for key, values in data.items():
        a = np.asarray(values)
        if a.ndim != 1:
            continue
        if a.dtype.kind in "OSU":
            a = np.array([v.decode("utf-8", errors="replace") if isinstance(v, bytes) else v for v in a])
        columns[str(key)] = a
    order = None
    for key in ("seq_num", "time"):
        a = columns.get(key)
        if a is not None and np.issubdtype(a.dtype, np.number) and np.isfinite(a).all():
            order = np.argsort(a, kind="stable")
            break
    if order is not None:
        columns = {k: v[order] if len(v) == len(order) else v for k, v in columns.items()}
    if derive is not None and columns:
        import pandas as pd
        df = derive(pd.DataFrame({k: pd.Series(v) for k, v in columns.items()}))
        columns.update({str(k): df[k].to_numpy() for k in df if str(k).startswith("fn:")})
    return columns


def _without_empty_sort(node):
    # Narrow workaround for containers returned with sorting=[['', 1]].
    if getattr(node, "_sorting_params", {}).get("sort") == "":
        node._sorting_params = {}
        node._reversed_sorting_params = {}
    return node


def filtered_catalog(catalog, filters):
    """Apply identical exact scope to pages, counts and dropdown facets."""
    from tiled.queries import Eq, Contains, Comparison, In
    node = _without_empty_sort(catalog)
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if key == "scan_min":
            query = Comparison("ge", "start.scan_id", int(value))
        elif key == "scan_max":
            query = Comparison("le", "start.scan_id", int(value))
        elif key == "data_sessions":
            query = In("start.data_session", list(value))
        elif key == "start.sample_name":
            query = Contains(key, str(value))
        else:
            query = Eq(key, value)
        node = _without_empty_sort(node.search(query))
    return node


def search_page(catalog, profile, filters, offset=0, limit=25):
    """SMI metadata page in reverse catalog order, preserving all query params."""
    node = filtered_catalog(catalog, filters)
    http = node.context.http_client
    url = node.item["links"]["search"]
    query_params = dict(getattr(node, "_queries_as_params", {}))
    response = http.get(url, params={**query_params, "page[limit]": 0, "fields": "count"})
    response.raise_for_status()
    total = int(response.json().get("meta", {}).get("count", 0))
    scans = []
    if offset < total:
        response = http.get(url, params={**query_params, "fields": "metadata",
            "page[offset]": max(0, total - offset - limit), "page[limit]": min(limit, total - offset)})
        response.raise_for_status()
        for item in reversed(response.json().get("data", [])):
            attributes = item.get("attributes", {})
            run = SimpleNamespace(metadata=attributes.get("metadata", {}), key=item.get("id", ""))
            scans.append(_summary_from_run(run, profile_name=profile))
    return TiledSearchResult(scans, total, total_count=total)


class TiledFrameSource:
    """Worker-owned lazy source with byte-bounded frames and bounded descriptors."""
    def __init__(self, catalog, profile, derive=None, max_bytes=64 * 1024**2):
        self.catalog = _without_empty_sort(catalog)
        self.profile = profile
        self.derive = derive
        self.max_bytes = max_bytes
        self._frames = OrderedDict()
        self._sequences = OrderedDict()
        self._nodes = {}

    def describe(self, uid, stream=None):
        run = self.catalog[uid]
        streams = sorted((str(k) for k in run.keys() if k != "baseline"), key=lambda k: (k != "primary", k))
        if not streams:
            raise ValueError("Run contains no data streams")
        stream = stream if stream in streams else streams[0]
        key = (uid, stream)
        if key in self._sequences:
            self._sequences.move_to_end(key)
            return self._sequences[key]
        node = run[stream]
        base = getattr(node, "base", None)
        container = base if base is not None else node
        # Older catalogs expose arrays under stream/data.
        if "data" in container:
            container = container["data"]
        fields, scalars, nodes = {}, {}, {}
        for name, child in container.items():
            structure = child.structure() if hasattr(child, "structure") else None
            shape = getattr(structure, "shape", None)
            if shape is not None:
                shape = tuple(shape)
                if len(shape) >= 2:
                    # Only explicit image fields or >=3-D arrays are images.
                    if str(name).endswith("_image") or len(shape) >= 3:
                        if len(shape) > 3 and any(s != 1 for s in shape[1:-2]):
                            raise ValueError(f"{name}: non-singleton extra axes {shape}; explicit exposure/panel mapping required")
                        fields[str(name)] = shape
                        nodes[str(name)] = child
                elif len(shape) == 1:
                    scalars[str(name)] = np.asarray(child.read())
            elif str(name) == "internal" or type(child).__name__ == "DataFrameClient":
                df = child.read()  # scalar table only, never the stream dataset
                scalars.update({str(k): np.asarray(df[k]) for k in df.columns})
        result = FrameSequence(self.profile, uid, stream, fields,
                               normalize_scalars(scalars, self.derive), streams)
        self._sequences[key] = result
        self._nodes[key] = nodes
        while len(self._sequences) > 8:
            old, _ = self._sequences.popitem(last=False)
            self._nodes.pop(old, None)
        return result

    def read_frame(self, ref):
        if ref.profile != self.profile:
            raise ValueError("Frame belongs to a different source profile")
        if ref in self._frames:
            self._frames.move_to_end(ref)
            return self._frames[ref]
        sequence = self._sequences.get((ref.uid, ref.stream))
        if sequence is None:
            sequence = self.describe(ref.uid, ref.stream)
        if not 0 <= ref.index < sequence.count(ref.detector):
            raise IndexError(ref.index)
        shape = sequence.fields[ref.detector]
        node = self._nodes[(ref.uid, ref.stream)][ref.detector]
        index = tuple(int(i) for i in np.unravel_index(ref.index, shape[:-2])) if len(shape) > 2 else ()
        selected = node[index + (slice(None), slice(None))]
        array = np.asarray(selected.read() if hasattr(selected, "read") else selected)
        if array.ndim != 2:
            raise ValueError(f"Expected one detector frame, got {array.shape}")
        self._frames[ref] = array
        while sum(a.nbytes for a in self._frames.values()) > self.max_bytes:
            self._frames.popitem(last=False)
        return array
