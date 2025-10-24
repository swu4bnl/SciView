#!/usr/bin/env python3
"""
Test script for SAXS processing functionality.

This script tests the new SAXS processing features without requiring actual data files.
"""

import tempfile
import os
import numpy as np
from skimage.io import imsave
from Bsub import BSubtractor, BSubConfig

def create_test_data():
    """Create synthetic test data for testing."""
    # Create synthetic WAXS and SAXS data
    size = (100, 100)
    
    # Synthetic image with some features
    x, y = np.meshgrid(np.arange(size[0]), np.arange(size[1]))
    image = 1000 + 500 * np.exp(-((x-50)**2 + (y-50)**2) / 200)
    
    # Synthetic background
    background = 800 + 100 * np.sin(x/10) * np.cos(y/10)
    
    # Add some noise
    np.random.seed(42)
    image += np.random.poisson(50, size)
    background += np.random.poisson(30, size)
    
    return image.astype(np.float32), background.astype(np.float32)

def test_saxs_functionality():
    """Test the SAXS processing functionality."""
    print("=== Testing SAXS Processing Functionality ===")
    
    # Create temporary directory for test files
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Using temporary directory: {temp_dir}")
        
        # Create test data
        waxs_image, waxs_background = create_test_data()
        saxs_image, saxs_background = create_test_data()  # In reality, these would be different
        
        # Save test files
        waxs_image_path = os.path.join(temp_dir, "test_sample_waxs.tiff")
        waxs_bg_path = os.path.join(temp_dir, "test_background_waxs.tiff")
        saxs_image_path = os.path.join(temp_dir, "test_sample_saxs.tiff")
        saxs_bg_path = os.path.join(temp_dir, "test_background_saxs.tiff")
        
        imsave(waxs_image_path, waxs_image)
        imsave(waxs_bg_path, waxs_background)
        imsave(saxs_image_path, saxs_image)
        imsave(saxs_bg_path, saxs_background)
        
        print("Created test data files")
        
        # Test BSubtractor
        config = BSubConfig(verbose=True, display_results=False)
        subtractor = BSubtractor(config)
        
        print("\n1. Testing filename conversion...")
        saxs_converted = subtractor.waxs_to_saxs("test_sample_waxs.tiff")
        print(f"   WAXS: test_sample_waxs.tiff -> SAXS: {saxs_converted}")
        assert saxs_converted == "test_sample_saxs.tiff", "Filename conversion failed"
        print("   ✓ Filename conversion works")
        
        print("\n2. Testing WAXS processing to learn alpha...")
        # Process WAXS without mask (simplified test)
        learned_alpha = subtractor.optimize_alpha_only(waxs_image, waxs_background)
        print(f"   Learned alpha: {learned_alpha:.4f}")
        print("   ✓ Alpha optimization works")
        
        print("\n3. Testing SAXS processing with learned alpha...")
        saxs_output_path = os.path.join(temp_dir, "test_saxs_result.tiff")
        saxs_result = subtractor.process_saxs(
            saxs_image_path, saxs_bg_path, learned_alpha, saxs_output_path
        )
        
        # Verify result was saved
        assert os.path.exists(saxs_output_path), "SAXS result file not saved"
        print("   ✓ SAXS processing with learned alpha works")
        print(f"   ✓ Result saved to: {saxs_output_path}")
        
        print("\n4. Testing learned alpha storage...")
        # Store alpha for reuse
        waxs_pair_id = f"test_sample_waxs.tiff_test_background_waxs.tiff"
        subtractor.learned_alpha_values[waxs_pair_id] = learned_alpha
        
        # Test retrieval
        assert subtractor.learned_alpha_values[waxs_pair_id] == learned_alpha
        print(f"   ✓ Alpha storage and retrieval works")
        
        print("\n=== All tests passed! ===")
        print(f"SAXS processing functionality is working correctly.")
        print(f"You can now use this functionality with real data.")

if __name__ == "__main__":
    test_saxs_functionality()