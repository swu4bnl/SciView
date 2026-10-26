"""Local image discovery and lossless calculated-image export."""

import os

import numpy as np
import pytest
from PIL import Image

from sciview.interfaces.services.image_service import ImageService
from sciview.sources.filesystem_source import list_folder


def test_list_folder_filters_sorts_and_separates_subfolders(tmp_path):
    for name in ("b_scan.TIFF", "a_scan.tif", "c_scan.tif", "notes.txt"):
        (tmp_path / name).touch()
    (tmp_path / "Zeta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "decoy.tif").mkdir()

    listing = list_folder(tmp_path, patterns=("*.tif", "*.tiff"))

    assert listing.file_names == ("a_scan.tif", "b_scan.TIFF", "c_scan.tif")
    assert listing.subfolder_names == ("alpha", "decoy.tif", "Zeta")
    assert listing.files[0] == tmp_path / "a_scan.tif"

    assert list_folder(
        tmp_path, patterns=("*.tif*",), name_filter="SCAN", descending=True
    ).file_names == ("c_scan.tif", "b_scan.TIFF", "a_scan.tif")
    assert list_folder(
        tmp_path, patterns=("*.tif*",), name_filter="[ab]_*"
    ).file_names == ("a_scan.tif", "b_scan.TIFF")


def test_list_folder_sorts_by_modification_time(tmp_path):
    for name, mtime in (("late.tif", 300), ("early.tif", 100), ("middle.tif", 200)):
        path = tmp_path / name
        path.touch()
        os.utime(path, (0, mtime))

    assert list_folder(tmp_path, patterns=("*.tif",), sort_by="mtime").file_names == (
        "early.tif",
        "middle.tif",
        "late.tif",
    )
    assert list_folder(
        tmp_path, patterns=("*.tif",), sort_by="mtime", descending=True
    ).file_names == ("late.tif", "middle.tif", "early.tif")


def test_save_array_writes_float_tiff_with_negative_values_and_description(tmp_path):
    data = np.array([[-1.5, 0.0], [2.25, 1e6]])

    saved = ImageService().save_array(tmp_path / "calc.tif", data, description="A - B")

    with Image.open(saved) as image:
        np.testing.assert_array_equal(np.asarray(image), data.astype(np.float32))
        assert image.tag_v2[270] == "A - B"


@pytest.mark.parametrize(
    ("name", "data"),
    [("calc.png", np.zeros((2, 2))), ("calc.tiff", np.zeros((2, 2, 3)))],
)
def test_save_array_rejects_non_tiff_or_non_2d(tmp_path, name, data):
    with pytest.raises(ValueError):
        ImageService().save_array(tmp_path / name, data)
    assert not (tmp_path / name).exists()
