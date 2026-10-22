import numpy as np
import pytest

from sciview.core.image_collection import (
    ComparisonDisplay,
    ComparisonMode,
    ImageCollection,
    ImageReference,
    compare_image_arrays,
)


def test_collection_keeps_order_and_pinned_reference_when_selection_changes():
    collection = ImageCollection()
    first = ImageReference(path="a.tif", filename="a.tif")
    second = ImageReference(path="b.tif", filename="b.tif")

    collection.add(first)
    collection.add(second)
    assert collection.current_reference is second
    assert collection.pin_current()
    assert collection.pinned_reference is second

    assert collection.select(0)
    assert collection.current_reference is first
    assert collection.pinned_reference is second


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (ComparisonMode.OPACITY, np.array([[2.0, 3.0], [4.0, 5.0]])),
        (ComparisonMode.ADD, np.array([[4.0, 6.0], [8.0, 10.0]])),
        (ComparisonMode.SPLIT, np.array([[1.0, 4.0], [3.0, 6.0]])),
        (ComparisonMode.DIFFERENCE, np.array([[-2.0, -2.0], [-2.0, -2.0]])),
    ],
)
def test_compare_image_arrays(mode, expected):
    reference = np.array([[1.0, 2.0], [3.0, 4.0]])
    current = reference + 2.0

    assert np.array_equal(
        compare_image_arrays(reference, current, mode),
        expected,
    )


@pytest.mark.parametrize(
    ("reference", "current"),
    [
        (np.zeros((2, 2)), np.zeros((2, 3))),
        (np.zeros((2, 2, 3)), np.zeros((2, 2, 3))),
        (np.full((2, 2), "x"), np.full((2, 2), "y")),
        (np.ones((2, 2), dtype=complex), np.ones((2, 2), dtype=complex)),
    ],
)
@pytest.mark.parametrize(
    "mode",
    [
        ComparisonMode.OPACITY,
        ComparisonMode.ADD,
        ComparisonMode.SPLIT,
        ComparisonMode.DIFFERENCE,
    ],
)
def test_numerical_comparison_rejects_incompatible_images(reference, current, mode):
    with pytest.raises(ValueError):
        compare_image_arrays(reference, current, mode)


def test_split_position_and_opacity_are_bounded():
    collection = ImageCollection()

    with pytest.raises(ValueError):
        collection.set_opacity(1.1)
    with pytest.raises(ValueError):
        collection.set_split_fraction(-0.1)


def test_comparison_display_validation():
    collection = ImageCollection()

    collection.set_comparison_display(
        ComparisonMode.ADD,
        ComparisonDisplay("viridis", "log", (1, 10)),
    )
    assert collection.comparison_displays[ComparisonMode.ADD].levels == (1.0, 10.0)
    collection.set_comparison_display(
        ComparisonMode.DIFFERENCE,
        ComparisonDisplay("coolwarm", "linear", (-2.0, 2.0)),
    )

    invalid = [
        (ComparisonMode.SPLIT, ComparisonDisplay("viridis")),
        (ComparisonMode.ADD, ComparisonDisplay("viridis", levels=(2.0, 1.0))),
        (ComparisonMode.ADD, ComparisonDisplay("viridis", levels=(0.0, float("inf")))),
        (ComparisonMode.DIFFERENCE, ComparisonDisplay("coolwarm", "log", (-1.0, 1.0))),
        (ComparisonMode.DIFFERENCE, ComparisonDisplay("coolwarm", levels=(-1.0, 2.0))),
    ]
    for mode, display in invalid:
        with pytest.raises(ValueError):
            collection.set_comparison_display(mode, display)


def test_add_mode_uses_selected_image_percentage():
    reference = np.array([[2.0, 4.0]])
    current = np.array([[8.0, 10.0]])

    result = compare_image_arrays(
        reference,
        current,
        ComparisonMode.ADD,
        current_weight=0.25,
    )

    np.testing.assert_array_equal(result, np.array([[4.0, 6.5]]))


def test_difference_subtracts_selected_image_percentage():
    collection = ImageCollection()
    collection.set_subtract_b_percentage(25)
    result = compare_image_arrays(
        np.array([[2.0, 4.0]]),
        np.array([[8.0, 10.0]]),
        ComparisonMode.DIFFERENCE,
        current_weight=collection.subtract_b_percentage / 100,
    )

    np.testing.assert_array_equal(result, np.array([[0.0, 1.5]]))
    with pytest.raises(ValueError):
        collection.set_subtract_b_percentage(101)


def test_add_percentage_is_bounded_integer():
    collection = ImageCollection()

    collection.set_add_b_percentage(35)
    assert collection.add_b_percentage == 35
    for value in (-1, 101, 25.5, True):
        with pytest.raises(ValueError):
            collection.set_add_b_percentage(value)

    with pytest.raises(ValueError):
        compare_image_arrays(
            np.ones((1, 1)),
            np.ones((1, 1)),
            ComparisonMode.ADD,
            current_weight=1.1,
        )
