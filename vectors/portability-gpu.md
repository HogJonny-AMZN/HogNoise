# The wgpu rung against the hog set, per feature

Written by `hog-noise-measure-gpu derive`.

| Feature | Apple Paravirtual device (Metal) on ci-macos | llvmpipe (LLVM 21.1.8, 256 bits) (Vulkan) on ci-ubuntu | Microsoft Basic Render Driver (D3D12) on ci-windows | Microsoft Basic Render Driver (D3D12) on local | NVIDIA GeForce RTX 5090 (D3D12) on local | NVIDIA GeForce RTX 5090/PCIe/SSE2 (OpenGL) on local | NVIDIA GeForce RTX 5090 (Vulkan) on local |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fnl/cellular_euclidean_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fnl/cellular_euclidean_distance | 8.94e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fnl/cellular_euclidean_distance2 | 7.92e-08 | 6.60e-08 | 6.60e-08 | 6.60e-08 | 7.45e-08 | 7.45e-08 | 7.45e-08 |
| fnl/cellular_euclidean_distance2add | 6.60e-08 | 7.45e-08 | 7.45e-08 | 7.45e-08 | 7.45e-08 | 7.45e-08 | 7.45e-08 |
| fnl/cellular_euclidean_distance2div | 1.79e-07 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 1.04e-07 | 1.04e-07 | 1.06e-07 |
| fnl/cellular_euclidean_distance2mul | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fnl/cellular_euclidean_distance2sub | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.06e-07 | 1.06e-07 | 1.06e-07 |
| fnl/cellular_euclideansq_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fnl/cellular_euclideansq_distance | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fnl/cellular_euclideansq_distance2 | 8.94e-08 | 1.45e-07 | 1.45e-07 | 1.45e-07 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fnl/cellular_euclideansq_distance2add | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fnl/cellular_euclideansq_distance2div | 1.49e-07 | 1.90e-07 | 1.90e-07 | 1.90e-07 | 1.49e-07 | 1.49e-07 | 1.58e-07 |
| fnl/cellular_euclideansq_distance2mul | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fnl/cellular_euclideansq_distance2sub | 1.06e-07 | 1.58e-07 | 1.85e-07 | 1.85e-07 | 1.06e-07 | 1.06e-07 | 1.06e-07 |
| fnl/cellular_fbm | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 |
| fnl/cellular_hybrid_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fnl/cellular_hybrid_distance | 2.98e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 |
| fnl/cellular_hybrid_distance2 | 2.38e-07 | 2.38e-07 | 2.38e-07 | 2.38e-07 | 2.38e-07 | 2.38e-07 | 2.38e-07 |
| fnl/cellular_hybrid_distance2add | 1.32e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 |
| fnl/cellular_hybrid_distance2div | 1.63e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.52e-07 | 1.52e-07 | 1.52e-07 |
| fnl/cellular_hybrid_distance2mul | 3.58e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 | 2.68e-07 |
| fnl/cellular_hybrid_distance2sub | 3.12e-07 | 3.12e-07 | 3.12e-07 | 3.12e-07 | 3.12e-07 | 3.12e-07 | 3.12e-07 |
| fnl/cellular_manhattan_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fnl/cellular_manhattan_distance | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fnl/cellular_manhattan_distance2 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 1.34e-07 |
| fnl/cellular_manhattan_distance2add | 9.69e-08 | 9.69e-08 | 9.69e-08 | 9.69e-08 | 9.69e-08 | 9.69e-08 | 9.69e-08 |
| fnl/cellular_manhattan_distance2div | 1.13e-07 | 1.08e-07 | 1.08e-07 | 1.08e-07 | 1.13e-07 | 1.13e-07 | 1.06e-07 |
| fnl/cellular_manhattan_distance2mul | 7.19e-08 | 1.06e-07 | 1.06e-07 | 1.06e-07 | 6.72e-08 | 6.72e-08 | 6.72e-08 |
| fnl/cellular_manhattan_distance2sub | 1.23e-07 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 1.23e-07 | 1.23e-07 | 1.23e-07 |
| fnl/cellular_none | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fnl/cellular_pingpong | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.58e-07 |
| fnl/cellular_ridged | 1.49e-07 | 1.49e-07 | 1.49e-07 | 1.49e-07 | 1.19e-07 | 1.49e-07 | 1.19e-07 |
| fnl/cubic_fbm | 3.73e-08 | 5.96e-08 | 5.68e-08 | 5.68e-08 | 5.96e-08 | 5.96e-08 | 4.10e-08 |
| fnl/cubic_none | 5.28e-08 | 8.94e-08 | 9.18e-08 | 9.18e-08 | 1.19e-07 | 1.19e-07 | 8.94e-08 |
| fnl/cubic_pingpong | 3.28e-07 | 2.98e-07 | 3.20e-07 | 3.20e-07 | 3.20e-07 | 3.20e-07 | 2.38e-07 |
| fnl/cubic_ridged | 1.19e-07 | 1.19e-07 | 1.58e-07 | 1.58e-07 | 1.79e-07 | 1.19e-07 | 1.19e-07 |
| fnl/genasgrid_opensimplex2_fbm_scales_0.7_1.0_1.3 | 6.05e-04, 0.0027 flipped | 5.85e-04, 0.0022 flipped | 5.85e-04, 0.0022 flipped | 5.85e-04, 0.0022 flipped | 6.05e-04, 0.0028 flipped | 6.05e-04, 0.0028 flipped | 6.05e-04, 0.0028 flipped |
| fnl/perlin_fbm | 1.47e-07 | 2.11e-07 | 2.11e-07 | 2.11e-07 | 1.47e-07 | 1.47e-07 | 1.47e-07 |
| fnl/perlin_none | 2.91e-07 | 4.77e-07 | 3.87e-07 | 3.87e-07 | 2.91e-07 | 2.91e-07 | 2.91e-07 |
| fnl/perlin_none_improve_xy | 4.52e-07 | 4.77e-07 | 4.77e-07 | 4.77e-07 | 3.70e-07 | 3.87e-07 | 3.87e-07 |
| fnl/perlin_none_improve_xz | 4.49e-07 | 9.64e-07 | 9.64e-07 | 9.64e-07 | 2.90e-07 | 2.90e-07 | 2.90e-07 |
| fnl/perlin_pingpong | 6.11e-07 | 7.00e-07 | 7.00e-07 | 7.00e-07 | 6.11e-07 | 6.11e-07 | 6.11e-07 |
| fnl/perlin_ridged | 2.84e-07 | 3.58e-07 | 3.43e-07 | 3.43e-07 | 2.84e-07 | 2.84e-07 | 2.84e-07 |
| fnl/simplex_fbm | 5.54e-06 | 1.29e-06 | 1.29e-06 | 1.29e-06 | 5.54e-06 | 5.54e-06 | 5.54e-06 |
| fnl/simplex_fbm_weighted0.5 | 2.34e-06 | 1.10e-06 | 1.10e-06 | 1.10e-06 | 2.34e-06 | 2.34e-06 | 2.34e-06 |
| fnl/simplex_none | 1.22e-06 | 1.40e-06 | 1.40e-06 | 1.40e-06 | 1.22e-06 | 1.22e-06 | 1.22e-06 |
| fnl/simplex_none_improve_xy | 5.58e-07 | 7.75e-07 | 7.75e-07 | 7.75e-07 | 5.11e-07 | 5.36e-07 | 5.14e-07 |
| fnl/simplex_none_improve_xz | 5.53e-07 | 9.22e-06 | 7.75e-07 | 7.75e-07 | 5.53e-07 | 5.53e-07 | 5.66e-07 |
| fnl/simplex_pingpong | 2.23e-05 | 5.14e-06 | 5.14e-06 | 5.14e-06 | 2.23e-05 | 2.23e-05 | 2.23e-05 |
| fnl/simplex_ridged | 1.13e-05 | 2.57e-06 | 2.57e-06 | 2.57e-06 | 1.13e-05 | 1.13e-05 | 1.13e-05 |
| fnl/simplex_smooth_fbm | 9.18e-07 | 9.20e-07 | 9.20e-07 | 9.20e-07 | 9.18e-07 | 9.18e-07 | 9.18e-07 |
| fnl/simplex_smooth_none | 6.64e-07 | 8.32e-07 | 8.32e-07 | 8.32e-07 | 6.54e-07 | 6.62e-07 | 6.64e-07 |
| fnl/simplex_smooth_pingpong | 3.53e-06 | 3.77e-06 | 3.77e-06 | 3.77e-06 | 3.54e-06 | 3.53e-06 | 3.53e-06 |
| fnl/simplex_smooth_ridged | 1.76e-06 | 1.89e-06 | 1.89e-06 | 1.89e-06 | 1.77e-06 | 1.77e-06 | 1.77e-06 |
| fnl/value_fbm | 8.72e-08 | 7.92e-08 | 7.92e-08 | 7.92e-08 | 8.72e-08 | 8.72e-08 | 8.72e-08 |
| fnl/value_none | 1.06e-07 | 1.58e-07 | 1.58e-07 | 1.58e-07 | 1.06e-07 | 1.06e-07 | 1.06e-07 |
| fnl/value_pingpong | 3.17e-07 | 4.49e-07 | 4.49e-07 | 4.49e-07 | 3.17e-07 | 3.17e-07 | 3.28e-07 |
| fnl/value_ridged | 1.23e-07 | 1.96e-07 | 1.96e-07 | 1.96e-07 | 1.23e-07 | 1.23e-07 | 1.23e-07 |
| fnl/warp_basicgrid_domain_warp_independent | 2.37e-05 | 2.37e-05 | 2.37e-05 | 2.37e-05 | 2.40e-05 | 2.37e-05 | 2.37e-05 |
| fnl/warp_basicgrid_domain_warp_progressive | 2.35e-05 | 2.35e-05 | 2.35e-05 | 2.35e-05 | 2.38e-05 | 2.35e-05 | 2.35e-05 |
| fnl/warp_basicgrid_none | 1.20e-05 | 1.20e-05 | 1.20e-05 | 1.20e-05 | 1.19e-05 | 1.20e-05 | 1.20e-05 |
| fnl/warp_opensimplex2_domain_warp_independent | 3.52e-05 | 3.83e-05 | 3.83e-05 | 3.83e-05 | 2.80e-05 | 3.52e-05 | 3.52e-05 |
| fnl/warp_opensimplex2_domain_warp_progressive | 3.66e-05 | 5.07e-05 | 5.07e-05 | 5.07e-05 | 3.55e-05 | 3.29e-05 | 3.29e-05 |
| fnl/warp_opensimplex2_none | 1.54e-05 | 1.86e-05 | 1.86e-05 | 1.86e-05 | 1.54e-05 | 1.54e-05 | 1.54e-05 |
| fnl/warp_opensimplex2reduced_domain_warp_independent | 2.44e-05 | 2.38e-05 | 2.38e-05 | 2.38e-05 | 2.44e-05 | 2.44e-05 | 2.44e-05 |
| fnl/warp_opensimplex2reduced_domain_warp_progressive | 6.01e-05 | 6.01e-05 | 6.01e-05 | 6.01e-05 | 3.29e-05 | 6.01e-05 | 6.01e-05 |
| fnl/warp_opensimplex2reduced_none | 1.19e-05 | 1.19e-05 | 1.19e-05 | 1.19e-05 | 1.19e-05 | 1.19e-05 | 1.19e-05 |
| fns/cellular_euclidean_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fns/cellular_euclidean_distance | 5.96e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 | 8.94e-08 |
| fns/cellular_euclidean_distance2 | 1.04e-07 | 6.60e-08 | 6.60e-08 | 6.60e-08 | 6.60e-08 | 6.60e-08 | 6.60e-08 |
| fns/cellular_euclidean_distance2add | 8.94e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 7.92e-08 | 7.92e-08 | 7.92e-08 |
| fns/cellular_euclidean_distance2cave | 2.17e-07 | 2.15e-07 | 2.15e-07 | 2.15e-07 | 2.17e-07 | 2.17e-07 | 2.17e-07 |
| fns/cellular_euclidean_distance2div | 1.98e-07 | 1.93e-07 | 1.93e-07 | 1.93e-07 | 1.77e-07 | 1.77e-07 | 1.65e-07 |
| fns/cellular_euclidean_distance2mul | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fns/cellular_euclidean_distance2sub | 1.06e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 |
| fns/cellular_euclidean_noiselookup | 6.45e-07, 0.0002 flipped | 3.58e-07, 0.0000 flipped | 3.83e-07, 0.0000 flipped | 3.83e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped |
| fns/cellular_manhattan_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fns/cellular_manhattan_distance | 5.96e-08 | 1.34e-07 | 1.34e-07 | 1.34e-07 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fns/cellular_manhattan_distance2 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 |
| fns/cellular_manhattan_distance2add | 1.04e-07 | 6.71e-08 | 6.71e-08 | 6.71e-08 | 1.04e-07 | 1.04e-07 | 1.04e-07 |
| fns/cellular_manhattan_distance2cave | 2.00e-07 | 1.99e-07 | 1.99e-07 | 1.99e-07 | 2.00e-07 | 2.00e-07 | 2.00e-07 |
| fns/cellular_manhattan_distance2div | 1.38e-07 | 1.83e-07 | 1.83e-07 | 1.83e-07 | 1.38e-07 | 1.38e-07 | 1.26e-07 |
| fns/cellular_manhattan_distance2mul | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fns/cellular_manhattan_distance2sub | 1.19e-07 | 2.38e-07 | 2.38e-07 | 2.38e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 |
| fns/cellular_manhattan_noiselookup | 6.45e-07, 0.0002 flipped | 3.58e-07, 0.0000 flipped | 3.83e-07, 0.0000 flipped | 3.83e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped |
| fns/cellular_natural_cellvalue | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
| fns/cellular_natural_distance | 1.19e-07 | 1.49e-07 | 1.49e-07 | 1.49e-07 | 1.19e-07 | 1.19e-07 | 1.19e-07 |
| fns/cellular_natural_distance2 | 1.52e-07 | 1.52e-07 | 1.52e-07 | 1.52e-07 | 1.52e-07 | 1.52e-07 | 1.52e-07 |
| fns/cellular_natural_distance2add | 5.96e-08 | 6.72e-08 | 6.72e-08 | 6.72e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fns/cellular_natural_distance2cave | 4.59e-07 | 4.58e-07 | 4.58e-07 | 4.58e-07 | 4.59e-07 | 4.59e-07 | 4.58e-07 |
| fns/cellular_natural_distance2div | 3.17e-07 | 3.69e-07 | 3.69e-07 | 3.69e-07 | 3.17e-07 | 3.17e-07 | 3.09e-07 |
| fns/cellular_natural_distance2mul | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 | 5.96e-08 |
| fns/cellular_natural_distance2sub | 1.79e-07 | 2.38e-07 | 2.38e-07 | 2.38e-07 | 1.56e-07 | 1.56e-07 | 1.79e-07 |
| fns/cellular_natural_noiselookup | 6.45e-07, 0.0002 flipped | 3.58e-07, 0.0000 flipped | 3.83e-07, 0.0000 flipped | 3.83e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped | 3.58e-07, 0.0000 flipped |
| fns/cubic_billow | 1.19e-07 | 1.19e-07 | 1.58e-07 | 1.58e-07 | 1.79e-07 | 1.19e-07 | 1.19e-07 |
| fns/cubic_none | 5.28e-08 | 8.94e-08 | 9.18e-08 | 9.18e-08 | 1.19e-07 | 1.19e-07 | 8.94e-08 |
| fns/cubic_rigidmulti | 7.26e-08 | 1.05e-07 | 9.69e-08 | 9.69e-08 | 9.69e-08 | 9.69e-08 | 1.19e-07 |
| fns/genasgrid_simplex_fbm_scales_0.7_1.0_1.3 | 5.12e-04, 0.0021 flipped | 4.40e-04, 0.0018 flipped | 4.40e-04, 0.0018 flipped | 4.40e-04, 0.0018 flipped | 4.40e-04, 0.0020 flipped | 4.40e-04, 0.0020 flipped | 4.40e-04, 0.0020 flipped |
| fns/genasgrid_simplex_fbm_scales_1.0_0.5_2.0 | 1.16e-03, 0.0057 flipped | 1.16e-03, 0.0062 flipped | 1.16e-03, 0.0062 flipped | 1.16e-03, 0.0062 flipped | 1.16e-03, 0.0054 flipped | 1.16e-03, 0.0054 flipped | 1.16e-03, 0.0054 flipped |
| fns/genasgrid_simplex_fbm_scales_1.0_1.0_1.0 | 2.26e-03, 0.0038 flipped | 1.26e-03, 0.0025 flipped | 1.26e-03, 0.0025 flipped | 1.26e-03, 0.0025 flipped | 1.26e-03, 0.0026 flipped | 1.26e-03, 0.0026 flipped | 1.26e-03, 0.0026 flipped |
| fns/perlin_billow | 2.84e-07 | 3.58e-07 | 3.43e-07 | 3.43e-07 | 2.84e-07 | 2.84e-07 | 2.84e-07 |
| fns/perlin_none | 2.91e-07 | 4.77e-07 | 3.87e-07 | 3.87e-07 | 2.91e-07 | 2.91e-07 | 2.91e-07 |
| fns/perlin_rigidmulti | 2.56e-07 | 6.07e-07 | 5.25e-07 | 5.25e-07 | 2.56e-07 | 2.56e-07 | 2.56e-07 |
| fns/simplex_billow | 1.13e-05 | 5.15e-06 | 5.15e-06 | 5.15e-06 | 1.13e-05 | 1.13e-05 | 1.13e-05 |
| fns/simplex_fbm | 8.60e-07 | 2.52e-06 | 2.52e-06 | 2.52e-06 | 8.60e-07 | 8.59e-07 | 8.60e-07 |
| fns/simplex_fbm_perturb_gradient | 1.08e-06 | 2.64e-06 | 2.64e-06 | 2.64e-06 | 1.11e-06 | 1.08e-06 | 1.08e-06 |
| fns/simplex_fbm_perturb_gradient_normalise | 1.32e-07 | 1.44e-07 | 1.44e-07 | 1.44e-07 | 1.44e-07 | 1.33e-07 | 1.33e-07 |
| fns/simplex_fbm_perturb_gradientfractal | 1.02e-06 | 1.34e-06 | 1.34e-06 | 1.34e-06 | 1.02e-06 | 1.02e-06 | 1.02e-06 |
| fns/simplex_fbm_perturb_gradientfractal_normalise | 1.56e-07 | 1.53e-07 | 1.53e-07 | 1.53e-07 | 1.59e-07 | 1.56e-07 | 1.56e-07 |
| fns/simplex_fbm_perturb_normalise | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 | 1.79e-07 |
| fns/simplex_none | 4.72e-07 | 4.77e-07 | 4.77e-07 | 4.77e-07 | 4.77e-07 | 4.72e-07 | 4.77e-07 |
| fns/simplex_rigidmulti | 1.81e-06 | 4.73e-06 | 4.73e-06 | 4.73e-06 | 1.81e-06 | 1.81e-06 | 1.81e-06 |
| fns/value_billow | 1.23e-07 | 1.96e-07 | 1.96e-07 | 1.96e-07 | 1.23e-07 | 1.23e-07 | 1.23e-07 |
| fns/value_none | 1.06e-07 | 1.58e-07 | 1.58e-07 | 1.58e-07 | 1.06e-07 | 1.06e-07 | 1.06e-07 |
| fns/value_rigidmulti | 2.11e-07 | 2.11e-07 | 2.11e-07 | 2.11e-07 | 2.11e-07 | 2.11e-07 | 2.11e-07 |
| fns/whitenoise_none | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped | 0.00e+00, 0.0000 flipped |
