
import os
import csv
import re
from typing import List, Tuple

# --- Step 1: Generate file name pairing list ---

# Detector configs
DETECTOR_CONFIGS = {
    'saxs': {
        'shape': (1475, 1679),
        'mask_name': 'Dectris/Pilatus2M_gaps-mask.png',
        'raw_subdir': 'saxs/raw',
        'file_pattern': '*pos1*.tiff',
        'pos2_pattern': '{{prefix}}*pos2*{{num}}*.tiff',
    },
    'waxs': {
        'shape': (981, 1043),
        'mask_name': 'Dectris/Pilatus800k_gaps-mask.png',
        'raw_subdir': 'waxs/raw',
        'file_pattern': '*pos1*.tiff',
        'pos2_pattern': '{{prefix}}*pos2*{{num}}*.tiff',
    },
}




def ensure_pairing_list(folder: str, csv_path: str, force_regenerate: bool = True) -> None:
    """
    Ensure the pairing list CSV exists. If not, generate it.
    Args:
        folder: Path to the folder containing images.
        csv_path: Path to the pairing list CSV file.
        force_regenerate: If True, regenerate even if file exists.
    """
    """
    Ensure the pairing list CSV exists. If not, generate it.
    Args:
        folder: Path to the folder containing images.
        csv_path: Path to the pairing list CSV file.
    """
    if not os.path.isfile(csv_path) or force_regenerate:
        if force_regenerate and os.path.isfile(csv_path):
            print(f"Force regenerating pairing list {csv_path}...")
        else:
            print(f"Pairing list {csv_path} not found. Generating...")
        generate_pairing_list(folder, csv_path)
    else:
        print(f"Pairing list {csv_path} found.")


def generate_pairing_list(folder: str, output_csv: str, mode: str = 'saxs', scan_offset: int = 1) -> List[Tuple[str, str]]:
    """
    Scan the folder and generate a list of image file pairs to be stitched.
    The result is saved as a CSV file with two columns: image1, image2.
    Args:
        folder: Path to the folder containing images.
        output_csv: Path to output CSV file.
        mode: Detector mode ('saxs' or 'waxs').
        scan_offset: Offset to add to pos1 scan id to get pos2 scan id (default 1).
    Returns:
        List of (image1, image2) pairs.
    """
    import glob
    config = DETECTOR_CONFIGS[mode]
    # Only store relative paths in CSV for portability
    source_dir = os.path.join(folder, config['raw_subdir'])
    if not os.path.isdir(source_dir):
        source_dir = folder
    
    # Get all pos1 and pos2 files
    pos1_files = glob.glob(os.path.join(source_dir, config['file_pattern']))
    pos2_files = glob.glob(os.path.join(source_dir, config['file_pattern'].replace('pos1', 'pos2')))
    pos1_files.sort()
    pos2_files.sort()
    
    pairs = []
    
    import re
    def extract_motor_positions(filename):
        """
        Extract sample prefix and motor positions from filename using regex.
        Returns:
            sample_prefix (str): Everything before _pos1/_pos2
            motor_positions (dict): Extracted motor positions (x, y, th, etc.)
        """
        # Find sample prefix (everything before _pos1 or _pos2)
        m = re.match(r'(.+?)_pos[12]', filename)
        sample_prefix = m.group(1) if m else filename

        # Extract all motor positions (x, y, th, etc.)
        motor_positions = {}
        # Find all patterns like x0.000, y-0.000, th0.050, etc.
        for match in re.finditer(r'([a-zA-Z]+)(-?\d+\.\d+)', filename):
            axis = match.group(1)
            try:
                value = float(match.group(2))
                motor_positions[axis] = value
            except Exception:
                pass
        return sample_prefix, motor_positions
    
    # Create lookup dictionary for pos2 files by sample and motor positions
    pos2_lookup = {}
    for pos2_file in pos2_files:
        pos2_filename = os.path.basename(pos2_file)
        sample_prefix, motor_pos = extract_motor_positions(pos2_filename)
        
        # Create key from sample and motor positions
        key = (sample_prefix, motor_pos.get('x', 0), motor_pos.get('th', 0))
        pos2_lookup[key] = pos2_filename
    
    # Match each pos1 file with corresponding pos2 file
    for pos1_file in pos1_files:
        pos1_filename = os.path.basename(pos1_file)
        sample_prefix, motor_pos = extract_motor_positions(pos1_filename)
        
        # Look for exact match in motor positions
        key = (sample_prefix, motor_pos.get('x', 0), motor_pos.get('th', 0))
        if key in pos2_lookup:
            pairs.append((pos1_filename, pos2_lookup[key]))
            print(f"Matched {pos1_filename} with {pos2_lookup[key]}")
        else:
            # If no exact match, try to find pos2 with same sample but different motor positions
            # This handles cases where pos2 might have slightly different motor positions
            sample_matches = [(k, v) for k, v in pos2_lookup.items() if k[0] == sample_prefix]
            if sample_matches:
                # Take the first match for this sample
                matched_pos2 = sample_matches[0][1]
                pairs.append((pos1_filename, matched_pos2))
                print(f"Approximate match: {pos1_filename} with {matched_pos2}")
            else:
                print(f"Warning: No pos2 match found for {pos1_filename}")
    
    # Write results to CSV
    with open(output_csv, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['image1', 'image2'])
        writer.writerows(pairs)
    
    print(f"Generated {len(pairs)} image pairs in {output_csv}")
    return pairs

# --- Step 2: Stitch image pairs ---


# --- Mask loading utility ---
def load_masks(mask_folder=None, mask_name=None, shape=None, detector='saxs'):
    """
    Load and return mask1_data and mask2_new as float64 arrays, normalized to 0/1.
    Args:
        mask_folder: Directory containing mask image.
        mask_name: Filename of mask image.
        shape: (width, height) tuple for output masks.
        detector: Detector mode ('saxs' or 'waxs').
    Returns:
        mask1_data, mask2_new: Tuple of numpy arrays.
    Raises:
        FileNotFoundError: If mask image is not found.
    """
    """
    Load and return mask1_data and mask2_new as float64 arrays, normalized to 0/1.
    Args:
        mask_folder: Directory containing mask image.
        mask_name: Filename of mask image.
        shape: (width, height) tuple for output masks.
    Returns:
        mask1_data, mask2_new: Tuple of numpy arrays.
    Raises:
        FileNotFoundError: If mask image is not found.
    """
    from PIL import Image
    import numpy as np
    if mask_folder is None:
        mask_folder = '/nsls2/data/cms/legacy/xf11bm/software/SciAnalysis/SciAnalysis/XSAnalysis/masks/'
    # Use detector config if mask_name or shape not provided
    config = DETECTOR_CONFIGS.get(detector, DETECTOR_CONFIGS['saxs'])
    if mask_name is None:
        mask_name = config['mask_name']
    if shape is None:
        shape = config['shape']
    mask_path = os.path.join(mask_folder, mask_name)
    if not os.path.isfile(mask_path):
        raise FileNotFoundError(f"Mask file not found: {mask_path}")
    mask1 = Image.open(mask_path).convert('I')
    mask1_data = np.copy(np.asarray(mask1)).astype(np.float64)
    if mask1_data.max() == 0:
        raise ValueError("Mask1 is all zeros!")
    mask1_data = mask1_data / np.max(mask1_data)
    # Ensure binary mask (0 or 1)
    mask1_data = (mask1_data > 0.5).astype(float)

    mask_black = Image.new('L', shape, 'black')
    mask2_new = Image.new('I', shape, 'white')
    # Use detector shape for cropping
    mask2_cut = mask1.crop((0, 30, shape[0], shape[1]))
    mask2_new.paste(mask2_cut)
    mask2_black = mask_black.crop((0, shape[1] - 30, shape[0], shape[1]))
    mask2_new.paste(mask2_black, [0, shape[1] - 30])
    mask2_new = np.copy(np.asarray(mask2_new)).astype(np.float64)
    if mask2_new.max() == 0:
        raise ValueError("Mask2 is all zeros!")
    mask2_new = mask2_new / np.max(mask1_data)
    # Ensure binary mask (0 or 1)
    mask2_new = (mask2_new > 0.5).astype(float)
    return mask1_data, mask2_new

def stitch_2images_custom(image1_path: str, image2_path: str, output_path: str, **kwargs):
    """
    Stitch two images using custom logic. Requires mask1_data and mask2_new as numpy arrays.
    Args:
        image1_path: Path to first image.
        image2_path: Path to second image.
        output_path: Path to save stitched image.
        mode: 'poisson' or 'simple'.
        mask1_data, mask2_new: Numpy arrays for masks.
    Returns:
        None. Writes stitched image to output_path.
    Raises:
        ValueError: If mask shapes do not match image shapes.
    """
    """
    Stitch two images using custom logic. Requires mask1_data and mask2_new as numpy arrays.
    Args:
        image1_path: Path to first image.
        image2_path: Path to second image.
        output_path: Path to save stitched image.
        mode: 'poisson' or 'simple'.
        mask1_data, mask2_new: Numpy arrays for masks.
    Returns:
        None. Writes stitched image to output_path.
    Raises:
        ValueError: If mask shapes do not match image shapes.
    """
    from PIL import Image
    import numpy as np
    mode = kwargs.get('mode', 'poisson')
    mask1_data = kwargs.get('mask1_data')
    mask2_new = kwargs.get('mask2_new')

    if mask1_data is None or mask2_new is None:
        raise ValueError('mask1_data and mask2_new must be provided as numpy arrays.')
    
    print(f"Stitching mode: {mode}")
    # print(f'mask1_data_nonzero: {np.sum(mask1_data > 0)}, mask2_new_nonzero: {np.sum(mask2_new > 0)}')
    # print(f'mask1_data_zero: {np.sum(mask1_data == 0)}, mask2_new_zero: {np.sum(mask2_new == 0)}')

    # Load first image
    img = Image.open(image1_path).convert('I')
    data = np.copy(np.asarray(img)).astype(np.float64)
    if mask1_data.shape != data.shape:
        raise ValueError(f"mask1_data shape {mask1_data.shape} does not match image shape {data.shape}")

    if image2_path:
        img2 = Image.open(image2_path).convert('I')
        data2 = np.copy(np.asarray(img2)).astype(np.float64)
        img2_new = Image.new('I', img.size)
        # Use detector shape for cropping (fix for SAXS/WAXS)
        det_shape = mask2_new.shape
        img2_cut = img2.crop((0, 30, det_shape[0], det_shape[1]))
        img2_new.paste(img2_cut)
        data2_data = np.copy(np.asarray(img2_new)).astype(np.float64)
        if mask2_new.shape != data2_data.shape:
            raise ValueError(f"mask2_new shape {mask2_new.shape} does not match image shape {data2_data.shape}")
    
        data1_new = data * mask1_data
        data2_new = data2_data * mask2_new
        count_map = (mask1_data + mask2_new).astype(int)
        overlap = (count_map == 2)

        # print(f'mask1_data_nonzero: {np.sum(mask1_data > 0)}, mask2_new_nonzero: {np.sum(mask2_new > 0)}')
        # print(f'mask1_data_zero: {np.sum(mask1_data == 0)}, mask2_new_zero: {np.sum(mask2_new == 0)}')

        # print(f'count_map_2:    {np.sum(count_map > 2)}')
        # print(f'count_map_one:        {np.sum(count_map == 1)}')
        # print(f'count_map_zero:       {np.sum(count_map == 0)}')

        # print(count_map)

        # print(f'overlap_nonzero: {np.sum(overlap)}')
        # print(f'overlap_zero:    {np.sum(~overlap)}')

        if mode == 'simple' or not np.any(overlap):
            # --- Simple average/merge ---
            denom = mask1_data + mask2_new
            denom[denom == 0] = 1  # avoid div0
            final_data = (data1_new + data2_new) / denom
        else:
            # --- Poisson-thinning fusion in overlap ---
            # User notes: Poisson thinning logic
            # 1) Estimate λ via differences (C cancels out)
            D = data1_new[overlap] - data2_new[overlap]
            lambda_hat = np.var(D) / 2.0
            # 2) Estimate C from mean of averages in overlap
            A = 0.5 * (data1_new[overlap] + data2_new[overlap])
            C_hat = np.mean(A) - lambda_hat
            C_hat = max(C_hat, 0.0)
            # Start with simple sum for final_data
            final_data = data1_new + data2_new
            # 3) Poisson-thinning fusion in overlap
            S = data1_new + data2_new - 2 * C_hat
            S = np.clip(S, 0, None).astype(int)
            if np.any(overlap):
                N_new = np.random.binomial(S[overlap], 0.5)
                final_data[overlap] = C_hat + N_new
            final_data[count_map < 1] = -2


    else:
        final_data = data * mask1_data
    final_data[np.isnan(final_data)] = -2
    final_img = Image.fromarray(final_data.astype(np.uint32))
    final_img.save(output_path)

def stitch_from_pairing_csv(folder: str, csv_path: str, output_folder: str, **kwargs):
    """
    Iterate through the pairing list and stitch images using stitch_2images_custom.
    Args:
        folder: Path to the folder containing images.
        csv_path: Path to the pairing list CSV file.
        output_folder: Output folder for stitched images.
        kwargs: Additional arguments for stitching.
    """
    """
    Iterate through the pairing list and stitch images using stitch_2images_custom.
    """
    with open(csv_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            image1 = os.path.join(folder, row['image1'])
            image2 = os.path.join(folder, row['image2'])
            # Output filename: replace 'pos1' with 'stitched' in the first image's filename
            src_name = row['image1']
            if 'pos1' in src_name:
                out_name = src_name.replace('pos1', 'stitched')
            else:
                out_name = f'stitched_{src_name}'
            output_path = os.path.join(output_folder, out_name)
            stitch_2images_custom(image1, image2, output_path, **kwargs)

# --- Optional: Expose as CLI or importable functions ---
if __name__ == "__main__":
    import argparse
    import numpy as np
    from PIL import Image

    parser = argparse.ArgumentParser(
        description="Batch stitch image pairs from a folder. Images are read from saxs/raw/ and output to saxs/stitched/ under the given folder."
    )
    parser.add_argument('folder', nargs='?', default=os.getcwd(), help='Base experiment folder (containing saxs/raw/)')
    parser.add_argument('-l', '--csv', default='../pairing_list.csv', help='CSV file to store/read image pairs (relative to raw folder)')
    parser.add_argument('-o', '--output', default=None, help='Output folder for stitched images (default: <mode>/stitched/)')
    parser.add_argument('-d', '--detector', default='saxs', choices=['saxs', 'waxs'], help='Detector/data type: saxs (default) or waxs')
    parser.add_argument('-s', '--scan-offset', type=int, default=1, help='Offset to add to pos1 scan id to get pos2 scan id (default: 1)')
    parser.add_argument('-m', '--mode', default='simple', choices=['simple', 'poisson'], help='Stitching mode: simple (default) or poisson')
    parser.add_argument('-g', '--debug', action='store_true', help='Enable debug output')
    parser.add_argument('-n', '--snap', action='store_true', default=False, help='Process only the first image pair in the list (snap mode, default: off)')
    parser.add_argument('-C', '--overwrite-csv', action='store_true', default=False, help='Overwrite pairing list CSV if exists')
    parser.add_argument('-I', '--overwrite-img', action='store_true', default=True, help='Overwrite stitched images if exist')
    args = parser.parse_args()

    base_dir = os.path.abspath(args.folder)
    config = DETECTOR_CONFIGS[args.detector]
    source_dir = os.path.join(base_dir, config['raw_subdir'])
    output_dir = args.output if args.output else os.path.join(base_dir, config['raw_subdir'].replace('raw', 'stitched'))
    os.makedirs(output_dir, exist_ok=True)
    csv_abs = os.path.abspath(args.csv) if os.path.isabs(args.csv) else os.path.join(source_dir, args.csv)

    # Logic: if CSV exists and not overwrite-csv, use it. Otherwise, generate new one.
    if not os.path.isfile(csv_abs) or args.overwrite_csv:
        print(f"Generating pairing list at {csv_abs} (overwrite_csv={args.overwrite_csv})...")
        generate_pairing_list(base_dir, csv_abs, mode=args.detector, scan_offset=args.scan_offset)
    else:
        print(f"Using existing pairing list at {csv_abs}.")

    try:
        mask1_data, mask2_new = load_masks(mask_name=config['mask_name'], shape=config['shape'])
    except Exception as e:
        print(f"Error loading masks: {e}")
        exit(1)

    with open(csv_abs, 'r') as csvfile:
        import csv as pycsv
        reader = pycsv.DictReader(csvfile)
        for idx, row in enumerate(reader):
            if args.snap and idx > 0:
                break
            image1 = os.path.join(source_dir, row['image1'])
            image2 = os.path.join(source_dir, row['image2'])
            src_name = row['image1']
            if 'pos1' in src_name:
                out_name = src_name.replace('pos1', 'stitched')
            else:
                out_name = f'stitched_{src_name}'
            output_path = os.path.join(output_dir, out_name)
            # Only stitch if output doesn't exist or --overwrite-img is set
            if not os.path.isfile(output_path) or args.overwrite_img:
                print(f"Stitching {image1} + {image2} -> {output_path}")
                try:
                    stitch_2images_custom(
                        image1, image2, output_path,
                        mask1_data=mask1_data, mask2_new=mask2_new, mode=args.mode
                    )
                except Exception as e:
                    print(f"Error stitching {image1} + {image2}: {e}")
            else:
                print(f"Skipping {output_path} (exists, use --overwrite-img to overwrite)")



# --- USAGE NOTES ---
# To generate a pairing list and stitch images:
#   python stitch_2M_ygaps.py /path/to/experiment --generate
#   python stitch_2M_ygaps.py /path/to/experiment
#
# By default, images are read from saxs/raw/ and output to saxs/stitched/ under the given folder.
# The mask logic matches the original notebook. Use --generate to refresh the pairing list.
#
# To use Poisson fusion mode, call stitch_2images_custom(..., mode='poisson') in your own script.
