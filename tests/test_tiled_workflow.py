"""Connect, find a scan, and load detector data without a live service."""

import builtins
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from sciview.interfaces.services.image_service import ImageService
from sciview.sources import tiled_client, tiled_source


@pytest.fixture
def service(monkeypatch):
    tiled_client._load_tiled.cache_clear()
    monkeypatch.setattr(tiled_client, "TILED_AVAILABLE", True)
    monkeypatch.setattr(tiled_client, "TILED_IMPORT_ERROR", None)
    for name in ("from_context", "from_uri", "Context", "Key", "httpx"):
        monkeypatch.setattr(tiled_client, name, getattr(tiled_client, name, None), raising=False)
    monkeypatch.setattr(tiled_source, "tiled_manager", tiled_client.TiledClientManager())
    monkeypatch.setattr(tiled_client, "TILED_PROFILES", {
        "test": {"uri": "https://example.invalid", "path": []},
    })
    yield ImageService()
    tiled_client._load_tiled.cache_clear()


def test_connect_find_scan_and_load_detector_image(service, monkeypatch):
    source = np.arange(12, dtype=np.uint16).reshape(1, 3, 4)
    start = {"uid": "run-42", "scan_id": 42, "sample_name": "sample", "detectors": ["detector"]}

    class Run(dict):
        metadata = {"start": start, "stop": {"exit_status": "success"}}

    run = Run(detector=source)
    run.start = start

    class Catalog(dict):
        metadata = {}
        context = SimpleNamespace(username="test user")

        def search(self, query):
            return SimpleNamespace(values=lambda: SimpleNamespace(last=lambda: run))

    catalog = Catalog({"run-42": run})
    client_module = ModuleType("tiled.client")
    client_module.from_uri = lambda uri: catalog
    client_module.from_context = lambda *args, **kwargs: catalog
    context_module = ModuleType("tiled.client.context")
    context_module.Context = object
    queries_module = ModuleType("tiled.queries")
    queries_module.Key = lambda name: name
    for name, module in (
        ("tiled", ModuleType("tiled")),
        ("tiled.client", client_module),
        ("tiled.client.context", context_module),
        ("tiled.queries", queries_module),
        ("httpx", ModuleType("httpx")),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    auth = service.tiled_authenticate("test", interactive_fallback=False)
    assert auth.authenticated
    assert auth.username == "test user"
    results = service.tiled_search_by_scan_ids(profile_name="test", start_scan_id=42)
    assert [(scan.scan_id, scan.uid, scan.sample_name) for scan in results.scans] == [
        (42, "run-42", "sample"),
    ]
    scan = results.scans[0]
    image = service.tiled_load_array(
        profile_name="test", scan_id=scan.scan_id, uid=scan.uid, detector=scan.detectors[0],
    )
    np.testing.assert_array_equal(image, source[0])
    assert image.dtype == source.dtype
    np.testing.assert_array_equal(source, np.arange(12, dtype=np.uint16).reshape(1, 3, 4))


def test_connect_reports_unavailable_dependencies_without_blocking_local_data(
    service, monkeypatch, tmp_path,
):
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name.startswith("tiled"):
            raise ImportError("Tiled client dependency unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    auth = service.tiled_authenticate("test", interactive_fallback=False)
    assert not auth.authenticated
    assert "Tiled client dependency unavailable" in auth.error

    source = np.arange(6, dtype=np.float32).reshape(2, 3)
    path = tmp_path / "image.tif"
    from PIL import Image

    Image.fromarray(source).save(path)
    images = service.scan_local_directory(tmp_path)
    assert len(images) == 1
    np.testing.assert_array_equal(service.load_array(images[0]), source)
