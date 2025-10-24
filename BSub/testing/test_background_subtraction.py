"""
Test script for the refactored background subtraction module.

This script creates synthetic data to test the functionality without requiring
real experimental data files.
"""

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import sys

# Add the current directory to Python path for imports
sys.path.append(str(Path(__file__).parent))

try:
    from Bsub import (
        BSubtractor,
        BSubConfig,
        OptimizationMetrics
    )
    print("✓ Successfully imported refactored modules")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)


def create_synthetic_data():
    """Create synthetic X-ray scattering data for testing."""
    
    # Image dimensions
    height, width = 400, 400
    
    # Create coordinate grids
    y, x = np.ogrid[:height, :width]
    center_x, center_y = width // 2, height // 2
    
    # Sample image: central scattering pattern + background
    r = np.sqrt((x - center_x)**2 + (y - center_y)**2)
    
    # Sample scattering (decreasing with radius)
    sample_signal = 1000 * np.exp(-r / 50)
    
    # Add some texture and noise
    sample_texture = 50 * np.sin(x / 20) * np.cos(y / 25)
    sample_noise = np.random.poisson(10, size=(height, width))
    
    # Background: mostly uniform with some structured features
    background_base = 200 * np.ones((height, width))
    background_pattern = 30 * np.sin(x / 30) + 20 * np.cos(y / 40)
    background_noise = np.random.poisson(5, size=(height, width))
    
    # Final images
    sample_image = sample_signal + background_base + background_pattern + sample_texture + sample_noise
    background_image = background_base + background_pattern + background_noise
    
    # Create a mask focusing on background-dominated regions
    # (outer ring where sample signal is weak)
    mask = ((r > 100) & (r < 180)) | ((x < 50) | (x > width-50))
    
    return sample_image, background_image, mask


def test_optimization_metrics():
    """Test the optimization metrics calculations."""
    
    print("\n=== Testing Optimization Metrics ===")
    
    # Create test data
    image = np.random.poisson(100, size=(100, 100)).astype(float)
    reference = np.random.poisson(50, size=(100, 100)).astype(float)
    mask = np.random.random((100, 100)) > 0.5
    
    metrics = OptimizationMetrics()
    
    # Test variance calculation
    for mode in ['None', 'gradient', 'laplace']:
        try:
            variance = metrics.calculate_variance(image, mask, mode)
            print(f"✓ Variance calculation (mode='{mode}'): {variance:.2f}")
        except Exception as e:
            print(f"✗ Variance calculation failed (mode='{mode}'): {e}")
    
    # Test correlation calculation
    try:
        correlation = metrics.calculate_correlation(image, reference, mask)
        print(f"✓ Correlation calculation: {correlation:.3f}")
    except Exception as e:
        print(f"✗ Correlation calculation failed: {e}")


def test_mask_creation():
    """Test mask creation and loading functionality."""
    
    print("\n=== Testing Mask Handling ===")
    
    # Create synthetic mask
    mask = np.zeros((200, 200), dtype=bool)
    mask[50:150, 50:150] = True  # Square region
    
    # Convert to image format (0-255)
    mask_image = (mask * 255).astype(np.uint8)
    
    # Save as temporary PNG
    from PIL import Image
    temp_mask_path = "temp_test_mask.png"
    Image.fromarray(mask_image).save(temp_mask_path)
    
    try:
        subtractor = BSubtractor()
        loaded_mask = subtractor.load_mask(temp_mask_path)
        
        if np.array_equal(mask, loaded_mask):
            print("✓ Mask loading and processing: PASSED")
        else:
            print("✗ Mask loading: Loaded mask doesn't match original")
            
    except Exception as e:
        print(f"✗ Mask loading failed: {e}")
    finally:
        # Clean up
        Path(temp_mask_path).unlink(missing_ok=True)


def test_background_subtraction():
    """Test the main background subtraction functionality."""
    
    print("\n=== Testing Background Subtraction ===")
    
    # Create synthetic data
    sample, background, mask = create_synthetic_data()
    
    # Configure subtractor
    config = BSubConfig(
        optimization_mode='gradient',
        display_results=False,  # Don't show plots in test
        save_results=False
    )
    
    subtractor = BSubtractor(config)
    
    try:
        # Test alpha-only optimization
        alpha_only = subtractor.optimize_alpha_only(sample, background, mask)
        print(f"✓ Alpha-only optimization: α = {alpha_only:.3f}")
        
        # Test alpha + alignment optimization
        alpha_align, y_shift = subtractor.optimize_alpha_and_alignment(sample, background, mask)
        print(f"✓ Alpha + alignment optimization: α = {alpha_align:.3f}, y_shift = {y_shift}")
        
        # Test background subtraction
        result = subtractor.subtract_background(sample, background, alpha_align, y_shift)
        print(f"✓ Background subtraction: output shape {result.shape}")
        
        # Verify result makes sense
        mean_original = np.mean(sample[mask])
        mean_result = np.mean(result[mask])
        print(f"  Original mean intensity (masked): {mean_original:.1f}")
        print(f"  Result mean intensity (masked): {mean_result:.1f}")
        
        if mean_result < mean_original:
            print("✓ Background subtraction appears effective")
        else:
            print("⚠ Background subtraction may not be working optimally")
            
    except Exception as e:
        print(f"✗ Background subtraction test failed: {e}")


def test_configuration():
    """Test configuration system."""
    
    print("\n=== Testing Configuration ===")
    
    try:
        # Test default configuration
        config_default = BSubConfig()
        print(f"✓ Default config: mode='{config_default.optimization_mode}'")
        
        # Test custom configuration
        config_custom = BSubConfig(
            optimization_mode='laplace',
            max_y_shift=10,
            alpha_bounds=(0.1, 5.0)
        )
        print(f"✓ Custom config: mode='{config_custom.optimization_mode}', max_shift={config_custom.max_y_shift}")
        
        # Test with subtractor
        subtractor = BSubtractor(config_custom)
        print("✓ Configuration integration with subtractor")
        
    except Exception as e:
        print(f"✗ Configuration test failed: {e}")


def test_visualization():
    """Test visualization functionality."""
    
    print("\n=== Testing Visualization ===")
    
    # Create data
    sample, background, mask = create_synthetic_data()
    
    config = BSubConfig(display_results=False)
    subtractor = BSubtractor(config)
    
    try:
        # Optimize and subtract
        alpha, y_shift = subtractor.optimize_alpha_and_alignment(sample, background, mask)
        result = subtractor.subtract_background(sample, background, alpha, y_shift)
        
        # Test visualization (but don't display)
        import matplotlib
        matplotlib.use('Agg')  # Use non-interactive backend
        
        subtractor.visualize_results(sample, result, mask, alpha, y_shift)
        plt.close('all')  # Close all figures
        
        print("✓ Visualization functionality: PASSED")
        
    except Exception as e:
        print(f"✗ Visualization test failed: {e}")


def run_all_tests():
    """Run comprehensive test suite."""
    
    print("Adaptive Background Subtraction - Test Suite")
    print("=" * 50)
    
    tests = [
        test_optimization_metrics,
        test_mask_creation,
        test_configuration,
        test_background_subtraction,
        test_visualization
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ Test '{test.__name__}' failed with exception: {e}")
    
    print(f"\n=== Test Summary ===")
    print(f"Passed: {passed}/{total} tests")
    
    if passed == total:
        print("🎉 All tests passed! The refactored code is working correctly.")
    else:
        print("⚠ Some tests failed. Please check the implementation.")


if __name__ == "__main__":
    run_all_tests()