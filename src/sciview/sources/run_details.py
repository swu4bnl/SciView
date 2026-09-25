"""Metadata and scalar inspection for Bluesky/Tiled runs, without image reads."""
import numpy as np
from sciview.sources.frame_source import normalize_scalars


def stream_container(run, stream):
    node = run[stream]
    base = getattr(node, "base", None)
    return base if base is not None else node


def read_scalar_columns(run, stream, derive=None):
    """Read scalar tables/1D fields only; never call stream.read()."""
    columns = {}
    def visit(container):
        for name, child in container.items():
            if name == "config": continue
            if name == "data":
                visit(child)
                continue
            structure = child.structure() if hasattr(child, "structure") else None
            shape = getattr(structure, "shape", None)
            if shape is not None:
                if len(shape) <= 1:
                    columns[str(name)] = np.atleast_1d(child.read())
            elif name == "internal" or type(child).__name__ == "DataFrameClient":
                table = child.read()
                columns.update({str(k): np.asarray(table[k]) for k in table.columns})
    visit(stream_container(run, stream))
    return normalize_scalars(columns, derive)


def read_configuration(run, stream):
    """Configuration metadata/scalars; array payloads are described, not read."""
    container = stream_container(run, stream)
    metadata = dict(getattr(run[stream], "metadata", {}) or {})
    configuration = metadata.get("configuration", {})
    if "config" not in container:
        node = run[stream]
        if "config" not in node: return configuration
        container = node
    def inspect(node, depth=0):
        if depth > 8: return "(nested configuration)"
        result = {"metadata": dict(getattr(node, "metadata", {}) or {})}
        structure = node.structure() if hasattr(node, "structure") else None
        shape = getattr(structure, "shape", None)
        if shape is not None:
            if len(shape) <= 1 and int(np.prod(shape)) <= 10000:
                result["values"] = np.asarray(node.read()).tolist()
            else:
                result["shape"] = list(shape)
            return result
        if type(node).__name__ == "DataFrameClient":
            result["columns"] = list(getattr(structure, "columns", []))
            return result
        if hasattr(node, "items"):
            result["children"] = {str(k): inspect(v, depth+1) for k, v in node.items()}
        return result
    return {"configuration": configuration, "config_nodes": inspect(container["config"])}


def scalar_points(columns, x_name, y_name, z_name=None):
    """Finite samples and original row IDs; never reshape/average duplicate cells."""
    names = [x_name, y_name] + ([z_name] if z_name else [])
    arrays = [np.asarray(columns[name], dtype=float) for name in names]
    if len({len(a) for a in arrays}) != 1:
        raise ValueError("Selected scalar columns have different lengths")
    finite = np.logical_and.reduce([np.isfinite(a) for a in arrays])
    return [a[finite] for a in arrays], np.flatnonzero(finite)
