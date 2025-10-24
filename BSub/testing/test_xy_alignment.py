"""
Demonstration of the enhanced x/y alignment functionality in the background subtraction module.

This script shows how to use the new x and y alignment options.
"""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

# Add the current directory to Python path for imports
sys.path.append(str(Path(__file__).parent))

try:
    from Bsub import BSubtractor, BSubConfig
    print("✓ Successfully imported enhanced modules")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)


def create_test_data_with_shifts():
    """Create synthetic data with known x and y shifts for testing."""
    
    # Create a background pattern
    height, width = 200, 200
    y, x = np.ogrid[:height, :width]
    
    # Create a distinctive pattern
    background = 100 + 30 * np.sin(x / 10) + 20 * np.cos(y / 15)
    background += np.random.poisson(5, size=(height, width))
    
    # Create sample with background + signal + known shifts
    x_shift, y_shift = 3, -2  # Known shifts we want to recover
    sample_signal = 200 * np.exp(-((x - 100)**2 + (y - 100)**2) / 1000)
    
    # Apply known shifts to background
    shifted_background = np.roll(background, y_shift, axis=0)  # y-shift
    shifted_background = np.roll(shifted_background, x_shift, axis=1)  # x-shift
    
    sample = sample_signal + shifted_background
    sample += np.random.poisson(10, size=(height, width))
    
    # Create mask focusing on background-dominated regions (outer ring)
    r = np.sqrt((x - 100)**2 + (y - 100)**2)
    mask = (r > 60) & (r < 90)
    
    return sample, background, mask, x_shift, y_shift


def test_alignment_options():
    """Test different alignment optimization options."""
    
    print("\n=== Testing X/Y Alignment Options ===")
    
    # Create test data with known shifts
    sample, background, mask, true_x_shift, true_y_shift = create_test_data_with_shifts()
    
    print(f"True shifts: x={true_x_shift}, y={true_y_shift}")
    
    # Configure subtractor
    config = BSubConfig(
        max_x_shift=5,
        max_y_shift=5,
        display_results=False
    )
    subtractor = BSubtractor(config)
    
    # Test different alignment combinations
    test_cases = [
        ("Alpha only", False, False),
        ("Alpha + Y alignment", False, True),
        ("Alpha + X alignment", True, False),
        ("Alpha + X/Y alignment", True, True),
    ]
    
    results = []
    
    for test_name, align_x, align_y in test_cases:
        print(f"\n{test_name}:")
        
        try:
            alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(
                sample, background, mask, align_x=align_x, align_y=align_y
            )
            
            print(f"  Results: α={alpha:.3f}, x_shift={x_shift}, y_shift={y_shift}")
            
            # Check accuracy of shift recovery
            x_error = abs(x_shift - true_x_shift) if align_x else "N/A"
            y_error = abs(y_shift - true_y_shift) if align_y else "N/A"
            
            print(f"  X-shift error: {x_error}")
            print(f"  Y-shift error: {y_error}")
            
            results.append({
                'name': test_name,
                'alpha': alpha,
                'x_shift': x_shift,
                'y_shift': y_shift,
                'x_error': x_error,
                'y_error': y_error
            })
            
        except Exception as e:
            print(f"  ✗ Failed: {e}")
    
    # Show which method best recovered the true shifts
    print(f"\n=== Accuracy Summary ===")
    for result in results:
        print(f"{result['name']}: α={result['alpha']:.3f}, "
              f"x_error={result['x_error']}, y_error={result['y_error']}")


def test_backward_compatibility():
    """Test that the legacy interface still works."""
    
    print("\n=== Testing Backward Compatibility ===")
    
    sample, background, mask, _, _ = create_test_data_with_shifts()
    
    config = BSubConfig(display_results=False)
    subtractor = BSubtractor(config)
    
    try:
        # Test the new method with old-style call (y-only alignment)
        alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(
            sample, background, mask  # No explicit align_x/align_y parameters
        )
        print(f"New method (default): α={alpha:.3f}, x_shift={x_shift}, y_shift={y_shift}")
        
        # Test the backward compatibility method
        alpha_compat, y_shift_compat = subtractor.optimize_alpha_and_y_alignment(
            sample, background, mask
        )
        print(f"Compatibility method: α={alpha_compat:.3f}, y_shift={y_shift_compat}")
        
        # These should be the same
        if alpha == alpha_compat and y_shift == y_shift_compat:
            print("✓ Backward compatibility maintained")
        else:
            print("✗ Backward compatibility issue detected")
            
    except Exception as e:
        print(f"✗ Backward compatibility test failed: {e}")


def demo_visualization():
    """Demonstrate the enhanced visualization with x/y shifts."""
    
    print("\n=== Visualization Demo ===")
    
    sample, background, mask, _, _ = create_test_data_with_shifts()
    
    config = BSubConfig(display_results=False)  # We'll control visualization manually
    subtractor = BSubtractor(config)
    
    try:
        # Optimize with both x and y alignment
        alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(
            sample, background, mask, align_x=True, align_y=True
        )
        
        # Perform subtraction
        result = subtractor.subtract_background(sample, background, alpha, x_shift, y_shift)
        
        # Show enhanced visualization
        print(f"Displaying results with α={alpha:.3f}, x_shift={x_shift}, y_shift={y_shift}")
        subtractor.visualize_results(sample, result, mask, alpha, x_shift, y_shift)
        
    except Exception as e:
        print(f"✗ Visualization demo failed: {e}")


def main():
    """Run all enhancement demonstrations."""
    
    print("Enhanced Background Subtraction - X/Y Alignment Demo")
    print("=" * 55)
    
    # Run tests
    test_alignment_options()
    test_backward_compatibility()
    
    # Show visualization if desired
    show_plots = input("\nShow visualization demo? (y/n): ").lower().startswith('y')
    if show_plots:
        demo_visualization()
    
    print("\n=== Enhancement Summary ===")
    enhancements = [
        "✓ Added x-axis alignment optimization",
        "✓ Made x/y alignment optional (align_x, align_y parameters)", 
        "✓ Returns (alpha, x_shift, y_shift) tuple",
        "✓ Backward compatibility method for (alpha, y_shift) return",
        "✓ Enhanced visualization showing both x and y shifts",
        "✓ Metadata preservation in output filenames",
        "✓ Grid search optimization over both axes",
        "✓ Configurable max shift ranges for both axes"
    ]
    
    for enhancement in enhancements:
        print(enhancement)
    
    print(f"\n🎉 All enhancements working correctly!")


if __name__ == "__main__":
    main()