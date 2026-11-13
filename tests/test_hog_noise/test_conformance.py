"""
HogNoise: the conformance harness, on small vectors built here and on the committed ones.
Package: tests/test_hog_noise/test_conformance
"""

import numpy as np
import pytest

from hog_noise import conformance
from hog_noise.conformance import Bound


def test_a_plain_bound_is_the_same_at_every_point():
    allowed = Bound(1e-3).per_point(0.01, (np.array([0.0, 5000.0], np.float32),))
    assert allowed.tolist() == [1e-3, 1e-3]


def test_a_coordinate_scaled_bound_grows_with_each_points_own_magnitude():
    xs = np.array([10.0, -1000.0, 0.0], np.float32)
    ys = np.array([0.0, 0.0, 300.0], np.float32)
    allowed = Bound(2.0, coordinate_scaled=True).per_point(0.01, (xs, ys))
    assert allowed.tolist() == pytest.approx([2.0, 20.0, 6.0])  # max(1, max|axis| * f) per point


def test_a_negative_bound_is_refused():
    with pytest.raises(ValueError):
        Bound(-1e-6)


def test_the_normalised_difference_at_a_zero_bound_is_zero_or_infinity_never_nan():
    ratio = conformance.normalised_difference(np.array([0.0, 1e-9]), np.array([0.0, 0.0]))
    assert ratio.tolist() == [0.0, float("inf")]
    assert conformance.normalised_difference(np.array([5e-4]), np.array([1e-3])).tolist() == [0.5]
