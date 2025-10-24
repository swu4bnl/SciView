import os
import csv
from skimage.io import imread
from Bsub import BSubtractor, BSubConfig

# Configuration
config = BSubConfig(verbose=True)
subtractor = BSubtractor(config)

# Directories  
waxs_dir = 'waxs/raw'
saxs_dir = 'saxs/raw'
waxs_output_dir = 'waxs/bsub'
saxs_output_dir = 'saxs/bsub'

# Create output directories
os.makedirs(waxs_output_dir, exist_ok=True)
os.makedirs(saxs_output_dir, exist_ok=True)

# Load mask (adjust path as needed)
mask_path = 'Pilatus800_Kapton_mask.png'  # Update this path
if not os.path.exists(mask_path):
    print(f"Warning: Mask file {mask_path} not found. Please update the path.")
    mask = None
else:
    mask = subtractor.load_mask(mask_path)

# Process WAXS data and learn alpha values
processed_count = 0
alpha_values = {}  # Store alpha for each image pair

print("Processing WAXS data to learn alpha values...")
with open('pairing_list.csv', 'r') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        waxs_image_path = os.path.join(waxs_dir, row['image'])
        waxs_background_path = os.path.join(waxs_dir, row['background'])
        
        # Check if WAXS files exist
        if not (os.path.exists(waxs_image_path) and os.path.exists(waxs_background_path)):
            print(f"WAXS files not found: {row['image']} or {row['background']}")
            continue
            
        try:
            # Load WAXS images
            waxs_image = imread(waxs_image_path)
            waxs_background = imread(waxs_background_path)
            
            # Optimize alpha for WAXS
            if mask is not None:
                alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(waxs_image, waxs_background, mask)
            else:
                # Fallback: use simple optimization without mask
                alpha = subtractor.optimize_alpha_only(waxs_image, waxs_background)
                x_shift, y_shift = 0, 0
            
            # Apply background subtraction
            waxs_result = subtractor.subtract_background(waxs_image, waxs_background, alpha, x_shift, y_shift)
            
            # Save WAXS result
            waxs_output_filename = row['image']
            waxs_output_path = os.path.join(waxs_output_dir, waxs_output_filename)
            subtractor.save_result(waxs_result, waxs_output_path, alpha, x_shift, y_shift)
            
            # Store alpha for SAXS processing
            alpha_values[row['image']] = alpha
            
            # Process corresponding SAXS data using learned alpha
            saxs_image_filename = subtractor.waxs_to_saxs(row['image'])
            saxs_background_filename = subtractor.waxs_to_saxs(row['background'])
            saxs_image_path = os.path.join(saxs_dir, saxs_image_filename)
            saxs_background_path = os.path.join(saxs_dir, saxs_background_filename)
            
            # Check if SAXS files exist
            if os.path.exists(saxs_image_path) and os.path.exists(saxs_background_path):
                # Process SAXS with learned alpha
                saxs_output_filename = saxs_image_filename
                saxs_output_path = os.path.join(saxs_output_dir, saxs_output_filename)
                
                saxs_result = subtractor.process_saxs(
                    saxs_image_path, saxs_background_path, alpha, saxs_output_path
                )
                
                print(f"Processed {processed_count + 1}: WAXS α={alpha:.3f}, SAXS processed")
            else:
                print(f"Processed {processed_count + 1}: WAXS α={alpha:.3f}, SAXS files not found")
            
            processed_count += 1
            
            # Progress update every 50 images
            if processed_count % 50 == 0:
                print(f"Progress: {processed_count} image pairs processed")
                
        except Exception as e:
            print(f"Error processing {row['image']}: {e}")
            continue

print(f"\nBatch processing completed!")
print(f"Total processed: {processed_count} image pairs")
print(f"Learned alpha values: {len(alpha_values)}")
print(f"WAXS results saved to: {waxs_output_dir}")
print(f"SAXS results saved to: {saxs_output_dir}")

# Print some statistics
if alpha_values:
    alpha_list = list(alpha_values.values())
    print(f"\nAlpha statistics:")
    print(f"  Mean: {sum(alpha_list)/len(alpha_list):.4f}")
    print(f"  Min: {min(alpha_list):.4f}")
    print(f"  Max: {max(alpha_list):.4f}")