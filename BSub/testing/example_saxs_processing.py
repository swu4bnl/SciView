#!/usr/bin/env python3
"""
Example script demonstrating SAXS processing using alpha values learned from WAXS data.

This script shows how to:
1. Process WAXS data to learn optimal alpha values
2. Apply those alpha values to corresponding SAXS data
3. Save the results

Usage:
    python example_saxs_processing.py
"""

import os
from Bsub import BSubtractor, BSubConfig

def main():
    # Configure processing
    config = BSubConfig(
        verbose=True,
        display_results=False,  # Set to True if you want to see plots
        save_results=True
    )
    
    subtractor = BSubtractor(config)
    
    # Example file paths (update these to match your data)
    waxs_image = "waxs/raw/H2O_1_0.0s_Linkam23.5C_10.00s_2157487_000000_waxs.tiff"
    waxs_background = "waxs/raw/KaptonBGD_1_0.0s_Linkam21.5C_10.00s_2157722_000000_waxs.tiff"
    mask_path = "Pilatus800_Kapton_mask.xcf"
    
    # Check if files exist
    if not all(os.path.exists(f) for f in [waxs_image, waxs_background, mask_path]):
        print("Error: Required files not found. Please update file paths in the script.")
        print(f"Looking for:")
        print(f"  WAXS image: {waxs_image}")
        print(f"  WAXS background: {waxs_background}")
        print(f"  Mask: {mask_path}")
        return
    
    print("=== SAXS Processing Example ===")
    print()
    
    # Step 1: Process WAXS data to learn alpha
    print("Step 1: Processing WAXS data to learn optimal alpha...")
    
    try:
        # Load mask
        mask = subtractor.load_mask(mask_path)
        print(f"Loaded mask from: {mask_path}")
        
        # Process WAXS data
        waxs_result = subtractor.subtract_background(
            waxs_image, waxs_background, 
            output_path="waxs/analysis/example_waxs_result.tiff"
        )
        
        learned_alpha = waxs_result['alpha']
        print(f"Learned alpha from WAXS: {learned_alpha:.4f}")
        
    except Exception as e:
        print(f"Error processing WAXS data: {e}")
        return
    
    # Step 2: Convert filenames and process SAXS
    print("\nStep 2: Processing corresponding SAXS data...")
    
    try:
        # Convert WAXS filenames to SAXS filenames
        saxs_image = subtractor.waxs_to_saxs(waxs_image)
        saxs_background = subtractor.waxs_to_saxs(waxs_background)
        
        print(f"SAXS image: {saxs_image}")
        print(f"SAXS background: {saxs_background}")
        
        # Check if SAXS files exist
        if not (os.path.exists(saxs_image) and os.path.exists(saxs_background)):
            print("Warning: SAXS files not found. Cannot proceed with SAXS processing.")
            print("This is normal if you only have WAXS data or if SAXS files are in a different location.")
            return
        
        # Process SAXS using learned alpha
        saxs_result = subtractor.process_saxs(
            saxs_image, saxs_background, learned_alpha,
            output_path="saxs/analysis/example_saxs_result.tiff"
        )
        
        print(f"SAXS processing completed using alpha: {learned_alpha:.4f}")
        print("Results saved to saxs/analysis/")
        
    except Exception as e:
        print(f"Error processing SAXS data: {e}")
        return
    
    print("\n=== Processing Summary ===")
    print(f"WAXS processed with optimized alpha: {learned_alpha:.4f}")
    print(f"SAXS processed with same alpha: {learned_alpha:.4f}")
    print("Files saved to respective analysis directories.")

if __name__ == "__main__":
    main()