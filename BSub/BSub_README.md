
# Adaptive Background Subtraction for X-ray Scattering Data

This module provides background subtraction for X-ray scattering experiments (SAXS/WAXS). It uses optimization algorithms to determine background subtraction coefficients and spatial alignment parameters.

## Features

- Automatic parameter tuning: Optimizes background scaling coefficient (alpha) and spatial alignment (x/y shift)
- Multiple optimization metrics: Variance minimization and correlation-based optimization
- Preprocessing options: Gradient and Laplacian edge enhancement
- Mask handling: Supports PNG, TIFF, RGB/RGBA formats
- Output: 32-bit float TIFF files
- Batch processing: Handles large datasets
- Error handling and logging
- Legacy function support for compatibility

## Usage

### Basic Usage

```python
from Bsub import BSubtractor, BSubConfig

config = BSubConfig(
    optimization_mode='gradient',
    max_y_shift=5,
    max_x_shift=5,
    save_results=True
)
subtractor = BSubtractor(config)
mask = subtractor.load_mask('kapton_mask.png')
# Load image and background as numpy arrays
alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(image, background, mask, align_x=True, align_y=True)
result = subtractor.subtract_background(image, background, alpha, x_shift, y_shift)
subtractor.save_result(result, 'output.tiff', alpha, x_shift, y_shift)
subtractor.visualize_results(image, result, mask, alpha, x_shift, y_shift)
```

### Batch Processing

See `BSub_batch.py` for an example of batch processing using a pairing list CSV.

### Legacy Interface

The module maintains compatibility with previous workflows:

```python
from Bsub import bsub_kapton
bsub_kapton(
    file_info=dataframe,
    directory='data_path',
    kapton_mask_path='mask.png',
    mode='gradient',
    save=1
)
```

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `optimization_mode` | str | 'gradient' | Preprocessing mode: 'None', 'gradient', 'laplace' |
| `max_y_shift` | int | 5 | Maximum pixels for y-axis alignment |
| `max_x_shift` | int | 5 | Maximum pixels for x-axis alignment |
| `alpha_bounds` | tuple | (0.0, 10.0) | Bounds for alpha optimization |
| `initial_alpha` | float | 1.0 | Starting guess for alpha |
| `save_results` | bool | True | Whether to save output files |
| `display_results` | bool | True | Whether to show visualizations |
| `process_single_image` | bool | False | Process only first image (snap mode) |

### Optimization Modes

- `'None'`: Direct intensity optimization
- `'gradient'`: Edge-enhanced optimization
- `'laplace'`: Curvature-enhanced optimization

## File Organization

```
BSub/
├── Bsub.py                # Main module
├── BSub_batch.py          # Batch processing script
├── BackgroundSubtraction_README.md  # This file
├── Pilatus800_Kapton_mask.png       # Example mask
├── pairing_list.csv       # Example pairing list
└── testing/               # Test and example scripts
```

## Best Practices

- Design masks to cover background-dominated regions
- Use similar conditions for background images
- Choose optimization mode based on background structure
- Validate alpha and shift values for reasonableness
- Inspect results visually

## Troubleshooting

- High alpha values: Check background scaling and mask
- Large shifts: Check alignment and detector stability
- Poor optimization: Try different mode or mask
- Artifacts: Check mask and detector

## Extensions

You can extend the module by adding custom optimization metrics or preprocessing methods.

## Citation

If you use this code in your research, please cite:

```
Adaptive Background Subtraction for X-ray Scattering Data
Implementation by NSLS-II/CMS, 2025
```
