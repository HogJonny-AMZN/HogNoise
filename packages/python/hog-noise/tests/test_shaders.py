"""
HogNoise: the emitted shaders, their manifest and the tables a host binds.
Package: packages/python/hog-noise/tests/test_shaders
"""

import numpy as np

from hog_noise import tables


def test_the_binding_table_is_the_four_tables_in_order():
    t = tables.binding_table()
    assert t.dtype == np.float32 and t.shape == (2048,)
    parts = [tables.GRADIENTS_2D, tables.GRADIENTS_3D, tables.RAND_VECS_2D, tables.RAND_VECS_3D]
    assert np.array_equal(t, np.concatenate(parts))
