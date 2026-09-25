from types import SimpleNamespace

import numpy as np
import pytest

from sciview.sources.frame_source import FrameRef, TiledFrameSource, normalize_scalars, search_page


class Array:
    def __init__(self, data, reads, selected=False):
        self.data, self.reads, self.selected = data, reads, selected

    def structure(self):
        return SimpleNamespace(shape=self.data.shape)

    def __getitem__(self, key):
        assert all(type(i) is int or isinstance(i, slice) for i in key)
        self.reads.append(key)
        return Array(self.data[key], self.reads, True)

    def read(self):
        if self.data.ndim >= 2 and not self.selected:
            raise AssertionError("full detector read")
        return self.data


def test_lazy_discovery_frame_reads_and_stream_cache():
    reads = []
    images = np.arange(3*4*5).reshape(3, 4, 5)
    run = {s: {"pil2M_image": Array(images + shift, reads),
               "energy": Array(np.array([2500, 2400, 2400]), reads),
               "seq_num": Array(np.array([3, 1, 2]), reads)}
           for s, shift in (("primary", 0), ("arc20", 100))}
    source = TiledFrameSource({"uid": run}, "smi_migration")
    sequence = source.describe("uid")
    assert not reads
    np.testing.assert_array_equal(sequence.scalars["energy"], [2400, 2400, 2500])
    np.testing.assert_array_equal(sequence.order("pil2M_image", "energy"), [0, 1, 2])
    ref = FrameRef("smi_migration", "uid", "primary", "pil2M_image", 1)
    np.testing.assert_array_equal(source.read_frame(ref), images[1])
    assert source.read_frame(ref) is source.read_frame(ref)
    assert len(reads) == 1
    other = FrameRef("smi_migration", "uid", "arc20", "pil2M_image", 1)
    np.testing.assert_array_equal(source.read_frame(other), images[1] + 100)
    assert len(reads) == 2


def test_extra_exposure_axes_are_not_silently_mapped():
    source = TiledFrameSource({"u": {"primary": {"det_image": Array(np.zeros((3, 2, 4, 5)), [])}}}, "p")
    with pytest.raises(ValueError, match="mapping required"):
        source.describe("u")


def test_byte_decoding_and_stable_scalar_sort():
    data = normalize_scalars({"seq_num": [2, 1, 3], "name": [b"two", b"one", b"three"]})
    assert list(data["name"]) == ["one", "two", "three"]


def test_pagination_preserves_filters_and_ignores_wrong_data_count():
    requests = []
    class Node:
        _sorting_params = {"sort": ""}
        _queries_as_params = {}
        item = {"links": {"search": "https://example/search"}}

        def search(self, query):
            self._queries_as_params = {"filter[test]": "scoped"}
            return self

    class HTTP:
        def get(self, url, params):
            requests.append(params)
            data = ({"meta": {"count": 30}} if params["fields"] == "count" else
                    {"meta": {"count": 99999}, "data": [{"id": "u", "attributes": {
                        "metadata": {"start": {"uid": "u", "scan_id": 1}}}}]})
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
    node = Node(); node.context = SimpleNamespace(http_client=HTTP())
    result = search_page(node, "smi_migration", {"scan_min": 1, "scan_max": 100}, offset=25)
    assert result.total_count == 30
    assert all(r["filter[test]"] == "scoped" for r in requests)
    assert requests[1]["page[offset]"] == 0
    assert requests[1]["page[limit]"] == 5
    assert node._sorting_params == {}


def test_singleton_axes_and_byte_budget():
    reads = []
    images = np.arange(3*1*4*5).reshape(3, 1, 4, 5)
    source = TiledFrameSource({"u": {"primary": {"det_image": Array(images, reads)}}}, "p", max_bytes=160)
    source.describe("u")
    first = FrameRef("p", "u", "primary", "det_image", 0)
    second = FrameRef("p", "u", "primary", "det_image", 1)
    np.testing.assert_array_equal(source.read_frame(first), images[0, 0])
    source.read_frame(second)
    source.read_frame(first)
    assert len(reads) == 3  # first frame evicted rather than an unbounded stack
