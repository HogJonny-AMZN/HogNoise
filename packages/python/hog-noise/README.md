# hog-noise

Procedural noise for Python: Perlin, OpenSimplex2, cellular and domain warp; the FastNoiseLite and FastNoiseSIMD
algorithms, checked against the originals. numpy is the only runtime dependency.

```python
import numpy as np
from hog_noise import NoiseParams, NoiseType, FractalType, make_sampler

params = NoiseParams(seed=1337, frequency=0.01, noise_type=NoiseType.OPEN_SIMPLEX2, fractal_type=FractalType.FBM)
sampler, _ = make_sampler(params)
xs = np.linspace(0, 100, 5, dtype=np.float32)
values = sampler.sample_points(xs, np.zeros_like(xs), xs, np.empty(5, np.float32))
```

This is the package's own page. The project's story, what is shipped and what is wanted, the comparisons against the
original libraries and the noise gallery are in the repository:
[github.com/HogJonny-AMZN/HogNoise](https://github.com/HogJonny-AMZN/HogNoise).
Any port of the noise can check itself against the same vectors: `python -m hog_noise.conformance vectors --rendering numpy`.

MIT licensed. [NOTICE](NOTICE) carries the licences of FastNoiseLite and FastNoiseSIMD, whose algorithms this ports.
