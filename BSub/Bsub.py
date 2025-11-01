"""
Adaptive Background Subtraction Module for X-ray Scattering Data

This module provides state-of-the-art adaptive background subtraction capabilities
for X-ray scattering experiments (SAXS/WAXS). The implementation uses optimization
algorithms to determine optimal background subtraction coefficients and spatial
alignment parameters to minimize background signal in user-defined regions of interest.

Author: Siyu Wu (NSLS-II/CMS)
Refactored for improved organization and documentation
Date: October 2025

Example usage (CLI):
--------------------
    python Bsub.py image.tiff background.tiff mask.png -o result.tiff --mode gradient --align-x --align-y --display --save

Example usage (import):
----------------------
    from Bsub import BSubtractor, BSubConfig
    config = BSubConfig(optimization_mode='gradient')
    subtractor = BSubtractor(config)
    image = ... # np.ndarray
    background = ... # np.ndarray
    mask = subtractor.load_mask('mask.png')
    alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(image, background, mask)
    result = subtractor.subtract_background(image, background, alpha, x_shift, y_shift)
    subtractor.save_result(result, 'result.tiff', alpha, x_shift, y_shift)
    subtractor.visualize_results(image, result, mask, alpha, x_shift, y_shift)

Batch processing examples:
-------------------------
1. Subtract all images in a folder using one background:

    import os
    from Bsub import BSubtractor, BSubConfig
    config = BSubConfig()
    subtractor = BSubtractor(config)
    mask = subtractor.load_mask('mask.png')
    background = imread('background.tiff')
    input_folder = 'images/'
    output_folder = 'results/'
    os.makedirs(output_folder, exist_ok=True)
    for fname in os.listdir(input_folder):
        if fname.endswith('.tiff'):
            image = imread(os.path.join(input_folder, fname))
            alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(image, background, mask)
            result = subtractor.subtract_background(image, background, alpha, x_shift, y_shift)
            out_path = os.path.join(output_folder, f"{os.path.splitext(fname)[0]}_bsub.tiff")
            subtractor.save_result(result, out_path, alpha, x_shift, y_shift)

2. Subtract each image with a different background using a pairing list (CSV):

    import os
    import csv
    from Bsub import BSubtractor, BSubConfig
    config = BSubConfig()
    subtractor = BSubtractor(config)
    mask = subtractor.load_mask('mask.png')
    input_folder = 'images/'
    output_folder = 'results/'
    os.makedirs(output_folder, exist_ok=True)
    with open('pairing_list.csv', 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            image = imread(os.path.join(input_folder, row['image']))
            background = imread(os.path.join(input_folder, row['background']))
            alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(image, background, mask)
            result = subtractor.subtract_background(image, background, alpha, x_shift, y_shift)
            out_path = os.path.join(output_folder, f"{os.path.splitext(row['image'])[0]}_bsub.tiff")
            subtractor.save_result(result, out_path, alpha, x_shift, y_shift)
"""

import os
import csv
import numpy as np
import matplotlib.pyplot as plt
from scipy import optimize, ndimage
from scipy.stats import pearsonr
from skimage.io import imread
from skimage.color import rgba2rgb, rgb2gray
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, Any, Union
import logging
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class BSubConfig:
    """Configuration parameters for adaptive background subtraction."""
    
    # Optimization parameters
    optimization_mode: str = 'None'  # 'None', 'gradient', 'laplace'
    max_y_shift: int = 5  # Maximum y-axis shift for alignment
    max_x_shift: int = 5  # Maximum x-axis shift for alignment
    alpha_bounds: Tuple[float, float] = (0.0, 10.0)  # Bounds for alpha optimization
    initial_alpha: float = 1.0  # Initial guess for alpha
    
    # Output parameters
    verbose: bool = True
    save_results: bool = True
    display_results: bool = True
    process_single_image: bool = False  # Snap mode
    
    # File handling
    output_suffix: str = '_bsub'
    output_format: str = 'tiff'
    
    # SAXS processing
    process_saxs: bool = False


class OptimizationMetrics:
    """Class containing different optimization metrics for background subtraction."""
    
    @staticmethod
    def calculate_variance(image: np.ndarray, mask: np.ndarray, mode: str = 'None') -> float:
        """
        Calculate variance in the masked region with optional image preprocessing.
        
        Args:
            image: Input image array
            mask: Binary mask array (True for regions of interest)
            mode: Preprocessing mode ('None', 'gradient', 'laplace')
            
        Returns:
            Variance value in the masked region
        """
        processed_image = OptimizationMetrics._preprocess_image(image, mode)
        masked_area = processed_image[mask]
        return np.var(masked_area)
    
    @staticmethod
    def calculate_correlation(image: np.ndarray, reference: np.ndarray, 
                            mask: np.ndarray, mode: str = 'None') -> float:
        """
        Calculate correlation between image and reference in the masked region.
        
        Args:
            image: Input image array
            reference: Reference image array
            mask: Binary mask array
            mode: Preprocessing mode
            
        Returns:
            Absolute correlation coefficient (0-1)
        """
        processed_image = OptimizationMetrics._preprocess_image(image, mode)
        processed_ref = OptimizationMetrics._preprocess_image(reference, mode)
        
        # Extract masked regions and remove NaNs
        image_masked = processed_image[mask]
        ref_masked = processed_ref[mask]
        
        valid_pixels = ~(np.isnan(image_masked) | np.isnan(ref_masked))
        image_clean = image_masked[valid_pixels]
        ref_clean = ref_masked[valid_pixels]
        
        if len(image_clean) < 2:
            logger.warning("Insufficient valid pixels for correlation calculation")
            return 0.0
        
        try:
            correlation_matrix = np.corrcoef(image_clean, ref_clean)
            correlation = correlation_matrix[0, 1]
            return abs(correlation) if not np.isnan(correlation) else 0.0
        except Exception as e:
            logger.warning(f"Correlation calculation failed: {e}")
            return 0.0
    
    @staticmethod
    def _preprocess_image(image: np.ndarray, mode: str) -> np.ndarray:
        """
        Preprocess image based on the specified mode.
        
        Args:
            image: Input image
            mode: Preprocessing mode
            
        Returns:
            Preprocessed image
        """
        if mode == 'laplace':
            return ndimage.laplace(image)
        elif mode == 'gradient':
            grad_x, grad_y = np.gradient(image)
            return np.abs(grad_x) + np.abs(grad_y)
        else:  # mode == 'None'
            return image


class BSubtractor:
    """
    Background subtraction processor for X-ray scattering data.
    
    This class implements background subtraction with optimization of scaling factors (alpha)
    and spatial alignment (x/y shift). Supports mask-based region selection and multiple metrics.
    """
    
    def __init__(self, config: BSubConfig = None):
        """
        Initialize the BSubtractor with configuration parameters.
        Args:
            config: BSubConfig object. If None, uses default configuration.
        """
        self.config = config or BSubConfig()
        self.last_optimization_result = None
        self.processing_history = []
        self.learned_alpha_values = {}  # Store learned alpha values for reuse
        
    def load_mask(self, mask_path: Union[str, Path]) -> np.ndarray:
        """
        Load and process a mask image for background subtraction.
        Args:
            mask_path: Path to the mask image file
        Returns:
            Binary mask array (True for regions of interest)
        """
        mask_path = Path(mask_path)
        if not mask_path.exists():
            raise FileNotFoundError(f"Mask file not found: {mask_path}")

        try:
            mask_img = imread(str(mask_path))
            # Handle RGBA (4 channels)
            if mask_img.ndim == 3 and mask_img.shape[2] == 4:
                # Convert RGBA to RGB
                from skimage.color import rgba2rgb
                mask_img = rgba2rgb(mask_img)
            # Handle RGB (3 channels)
            if mask_img.ndim == 3 and mask_img.shape[2] == 3:
                from skimage.color import rgb2gray
                mask_gray = rgb2gray(mask_img)
            elif mask_img.ndim == 2:
                mask_gray = mask_img
            else:
                raise ValueError(f"Unsupported mask image shape: {mask_img.shape}")

            # Convert to binary mask (white regions = True)
            binary_mask = mask_gray > 0.5
            logger.info(f"Loaded mask with {np.sum(binary_mask)} active pixels "
                        f"({100 * np.sum(binary_mask) / binary_mask.size:.1f}% coverage)")
            return binary_mask
        except Exception as e:
            raise ValueError(f"Failed to process mask image: {e}")
    
    def optimize_alpha_only(self, image: np.ndarray, background: np.ndarray, 
                           mask: np.ndarray) -> float:
        """
        Optimize only the alpha coefficient for background subtraction.
        Args:
            image: Input image
            background: Background image
            mask: Binary mask for optimization region
        Returns:
            Optimal alpha coefficient
        """
        def objective(alpha):
            subtracted = mask * (image - alpha * background)
            return OptimizationMetrics.calculate_correlation(
                subtracted, background, mask, self.config.optimization_mode
            )
        
        result = optimize.minimize_scalar(
            objective,
            bounds=self.config.alpha_bounds,
            method='bounded'
        )
        
        if not result.success:
            logger.warning("Alpha optimization did not converge")
        
        return float(result.x)
    
    def optimize_alpha_and_alignment(self, image: np.ndarray, background: np.ndarray, 
                                   mask: np.ndarray, align_x: bool = False, 
                                   align_y: bool = False) -> Tuple[float, int, int]:
        """
        Optimize alpha coefficient and optionally x/y-axis alignment.
        Args:
            image: Input image
            background: Background image
            mask: Binary mask for optimization region
            align_x: Whether to optimize x-axis alignment
            align_y: Whether to optimize y-axis alignment
        Returns:
            Tuple of (optimal_alpha, optimal_x_shift, optimal_y_shift)
            If align_x/align_y is False, corresponding shift will be 0
        """
        best_xshift = 0
        best_yshift = 0
        
        # If neither axis alignment is requested, just optimize alpha
        if not align_x and not align_y:
            logger.info("No alignment optimization requested, optimizing alpha only")
            alpha = self.optimize_alpha_only(image, background, mask)
            return alpha, 0, 0
        
        # Step 1: Coarse alignment optimization
        best_variance = float('inf')
        
        # Define shift ranges based on what alignments are requested
        x_range = range(-self.config.max_x_shift, self.config.max_x_shift + 1) if align_x else [0]
        y_range = range(-self.config.max_y_shift, self.config.max_y_shift + 1) if align_y else [0]
        
        logger.info(f"Optimizing alignment - X: {align_x} (range: {len(x_range)} values), "
                   f"Y: {align_y} (range: {len(y_range)} values)")
        
        # Grid search over alignment parameters
        for xshift in x_range:
            for yshift in y_range:
                # Apply both x and y shifts
                aligned_bg = background
                if align_x and xshift != 0:
                    aligned_bg = np.roll(aligned_bg, xshift, axis=1)
                if align_y and yshift != 0:
                    aligned_bg = np.roll(aligned_bg, yshift, axis=0)
                
                # Test this alignment
                test_subtraction = mask * (image - self.config.initial_alpha * aligned_bg)
                variance = OptimizationMetrics.calculate_variance(
                    test_subtraction, mask, self.config.optimization_mode
                )
                
                if variance < best_variance:
                    best_variance = variance
                    best_xshift = xshift
                    best_yshift = yshift
        
        alignment_info = []
        if align_x:
            alignment_info.append(f"x_shift={best_xshift}")
        if align_y:
            alignment_info.append(f"y_shift={best_yshift}")
        
        logger.info(f"Optimal alignment determined: {', '.join(alignment_info)}")
        
        # Step 2: Fine-tune alpha with optimal alignment
        aligned_background = background
        if align_x and best_xshift != 0:
            aligned_background = np.roll(aligned_background, best_xshift, axis=1)
        if align_y and best_yshift != 0:
            aligned_background = np.roll(aligned_background, best_yshift, axis=0)
        
        def objective(alpha):
            subtracted = mask * (image - alpha * aligned_background)
            return OptimizationMetrics.calculate_correlation(
                subtracted, aligned_background, mask, self.config.optimization_mode
            )
        
        result = optimize.minimize_scalar(
            objective,
            bounds=self.config.alpha_bounds,
            method='bounded'
        )
        
        if not result.success:
            logger.warning("Alpha optimization with alignment did not converge")
        
        optimal_alpha = float(result.x)
        
        return optimal_alpha, best_xshift, best_yshift
    
    def subtract_background(self, image: np.ndarray, background: np.ndarray,
                          alpha: float, x_shift: int = 0, y_shift: int = 0) -> np.ndarray:
        """
        Perform background subtraction with given parameters.
        Args:
            image: Input image
            background: Background image
            alpha: Scaling coefficient
            x_shift: X-axis shift for alignment
            y_shift: Y-axis shift for alignment
        Returns:
            Background-subtracted image
        """
        aligned_background = background

        # Apply shifts if specified
        if x_shift != 0:
            aligned_background = np.roll(aligned_background, x_shift, axis=1)
        if y_shift != 0:
            aligned_background = np.roll(aligned_background, y_shift, axis=0)

        result = image - alpha * aligned_background
        # Clean-up: set negative values to -2
        result = np.where(result < 0, -2, result)
        return result
    
    def visualize_results(self, original: np.ndarray, subtracted: np.ndarray,
                         mask: np.ndarray, alpha: float, x_shift: int = 0, y_shift: int = 0):
        """
        Visualize the background subtraction results.
        Shows three images: original, background-subtracted, and masked region.
        Uses symmetric logarithmic color scale for better visualization.
        """
        import numpy as np
        import matplotlib.pyplot as plt
        from matplotlib.colors import SymLogNorm

        # Choose linthresh and vmin/vmax for visualization
        all_pixels = np.concatenate([
            original[~np.isnan(original)],
            subtracted[~np.isnan(subtracted)]
        ])
        linthresh = np.percentile(all_pixels, 50)  # median value
        vmin = -2
        vmax = np.percentile(all_pixels, 99)
        norm = SymLogNorm(linthresh=linthresh, vmin=vmin, vmax=vmax)

        fig, axes = plt.subplots(1, 3, figsize=(15, 5))

        # Original image
        im1 = axes[0].imshow(original, cmap='gray', norm=norm)
        axes[0].set_title('Original Image (SymLogNorm)')
        axes[0].axis('off')
        plt.colorbar(im1, ax=axes[0])

        # Background subtracted image
        shift_info = []
        if x_shift != 0:
            shift_info.append(f"x_shift={x_shift}")
        if y_shift != 0:
            shift_info.append(f"y_shift={y_shift}")
        shift_text = f", {', '.join(shift_info)}" if shift_info else ""
        im2 = axes[1].imshow(subtracted, cmap='gray', norm=norm)
        axes[1].set_title(f'Background Subtracted\n(α={alpha:.3f}{shift_text}, SymLogNorm)')
        axes[1].axis('off')
        plt.colorbar(im2, ax=axes[1])

        # Mask overlay
        masked_result = np.where(mask, subtracted, np.nan)
        im3 = axes[2].imshow(masked_result, cmap='gray', norm=norm)
        axes[2].set_title('Optimization Region (SymLogNorm)')
        axes[2].axis('off')
        plt.colorbar(im3, ax=axes[2])

        plt.tight_layout()
        plt.show()
    
    def save_result(self, image: np.ndarray, output_path: Union[str, Path],
                   alpha: float, x_shift: int = 0, y_shift: int = 0):
        """
        Save background-subtracted image with metadata in filename.
        Args:
            image: Background-subtracted image
            output_path: Output file path
            alpha: Alpha coefficient used
            x_shift: X-shift used
            y_shift: Y-shift used
        """
        output_path = Path(output_path)

        # Create output directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Compose filename: <stem>_bsubX.XXX.tif
        stem = output_path.stem
        suffix = output_path.suffix
        alpha_str = f"{alpha:.3f}"
        final_path = output_path.parent / f"{stem}_bsub{alpha_str}{suffix}"

        # Save as 32-bit float TIFF to preserve precision
        from skimage.io import imsave
        imsave(str(final_path), image.astype(np.float32))

        logger.info(f"Saved result to: {final_path}")

    def process_saxs(self, saxs_image_path, saxs_background_path, 
                     alpha, output_path=None):
        """
        Process SAXS data using a given alpha value.
        Args:
            saxs_image_path: Path to SAXS image file
            saxs_background_path: Path to SAXS background file
            alpha: Alpha value for background subtraction
            output_path: Path to save processed SAXS result (optional)
        Returns:
            np.ndarray: Background-subtracted SAXS image
        """
        if self.config.verbose:
            logger.info(f"Processing SAXS data with alpha {alpha:.4f}")
            logger.info(f"  Image: {os.path.basename(saxs_image_path)}")
            logger.info(f"  Background: {os.path.basename(saxs_background_path)}")
        
        # Load SAXS data
        saxs_image = imread(saxs_image_path)
        saxs_background = imread(saxs_background_path)

        # Apply background subtraction with alpha
        corrected_saxs = saxs_image - alpha * saxs_background
        
        # Save result if output path provided
        if output_path:
            self.save_result(corrected_saxs, output_path, alpha)
            if self.config.verbose:
                logger.info(f"Saved SAXS result to: {output_path}")
        
        return corrected_saxs

    def waxs_to_saxs(self, waxs_filename):
        """
        Convert WAXS filename to SAXS filename by replacing '_waxs' with '_saxs'.
        Args:
            waxs_filename: WAXS filename containing '_waxs'
        Returns:
            str: SAXS filename
        """
        return waxs_filename.replace('_waxs', '_saxs')


def check_mask_alignment(background_path: str, mask_path: str, 
                        data_loader_class=None) -> None:
    """
    Utility function to visualize mask alignment with background image.
    
    Args:
        background_path: Path to background image
        mask_path: Path to mask image
        data_loader_class: Optional data loader class (e.g., Data2DScattering)
    """
    # Load background image
    if data_loader_class:
        data = data_loader_class()
        data.load(background_path)
        background = data.data
    else:
        background = imread(background_path)
    
    # Load and process mask
    subtractor = BSubtractor()
    mask = subtractor.load_mask(mask_path)
    
    # Create masked overlay
    masked_background = np.where(mask, background, np.nan)
    
    # Visualize
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    axes[0].imshow(background, cmap='gray')
    axes[0].set_title('Background Image')
    axes[0].axis('off')
    
    axes[1].imshow(mask, cmap='gray')
    axes[1].set_title('Mask')
    axes[1].axis('off')
    
    axes[2].imshow(masked_background, cmap='gray', vmin=-2)
    axes[2].set_title('Masked Background\n(Check Alignment)')
    axes[2].axis('off')
    
    plt.tight_layout()
    plt.show()


# Legacy function wrapper for backward compatibility
def bsub_kapton(file_info, directory, bgd_index=-1, kapton_mask_path=None, 
                   mode='gradient', save=0, draw=1, snap=1, SAXS=0, **kwargs):
    """
    Legacy wrapper function for backward compatibility.
    
    This function maintains the original interface while using the new
    BSubtractor class internally.
    """
    logger.warning("Using legacy function. Consider migrating to BSubtractor class.")
    
    # Convert legacy parameters to new config
    config = BSubConfig(
        optimization_mode=mode,
        save_results=bool(save),
        display_results=bool(draw),
        process_single_image=bool(snap),
        process_saxs=bool(SAXS)
    )
    
    subtractor = BSubtractor(config)
    
    # Load background image
    bgd_filename = file_info.iloc[bgd_index].Filename
    bgd_path = os.path.join(directory, bgd_filename)
    
    try:
        from SciAnalysis.Data import Data2DScattering
        data = Data2DScattering()
        data.load(bgd_path)
        background = data.data
    except ImportError:
        logger.error("Data2DScattering not available. Using skimage imread.")
        background = imread(bgd_path)
    
    # Load mask
    if not kapton_mask_path:
        raise ValueError("Kapton mask path is required.")
    
    mask = subtractor.load_mask(kapton_mask_path)
    
    # Process images
    for index, row in file_info.iterrows():
        filename = row['Filename']
        filepath = os.path.join(directory, filename)
        
        # Load image
        try:
            data = Data2DScattering()
            data.load(filepath)
            image = data.data
        except:
            image = imread(filepath)
        
        # Optimize parameters
        alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(image, background, mask)
        logger.info(f"Optimization results: alpha={alpha:.3f}, x_shift={x_shift}, y_shift={y_shift}")
        
        # Perform subtraction
        result = subtractor.subtract_background(image, background, alpha, x_shift, y_shift)
        
        # Save results
        if config.save_results:
            output_dir = Path(directory) / 'bsub'
            output_path = output_dir / f"{Path(filename).stem}{config.output_suffix}.tiff"
            subtractor.save_result(result, output_path, alpha, x_shift, y_shift)
        
        # Display results
        if config.display_results:
            subtractor.visualize_results(image, result, mask, alpha, x_shift, y_shift)
        
        # Handle SAXS processing if requested
        if config.process_saxs:
            # Convert WAXS filename to SAXS filename
            saxs_filename = subtractor.waxs_to_saxs(filename)
            saxs_filepath = os.path.join(directory, saxs_filename)
            
            # Convert background filename to SAXS
            saxs_bgd_filename = subtractor.waxs_to_saxs(bgd_filename)
            saxs_bgd_path = os.path.join(directory, saxs_bgd_filename)
            
            # Check if SAXS files exist
            if os.path.exists(saxs_filepath) and os.path.exists(saxs_bgd_path):
                # Process SAXS using the alpha learned from WAXS
                if config.save_results:
                    saxs_output_dir = Path(directory) / 'bsub_saxs'
                    saxs_output_path = saxs_output_dir / f"{Path(saxs_filename).stem}{config.output_suffix}.tiff"
                else:
                    saxs_output_path = None
                
                saxs_result = subtractor.process_saxs(
                    saxs_filepath, saxs_bgd_path, alpha, saxs_output_path
                )
                
                logger.info(f"SAXS processing completed for {saxs_filename} using alpha={alpha:.3f}")
            else:
                logger.warning(f"SAXS files not found: {saxs_filename} or {saxs_bgd_filename}")
        
        if config.process_single_image:
            break



# --- Optional: Expose as CLI or importable functions ---
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Adaptive background subtraction for X-ray scattering data."
    )
    parser.add_argument('image', help='Path to input image')
    parser.add_argument('background', help='Path to background image')
    parser.add_argument('mask', help='Path to mask image')
    parser.add_argument('-o', '--output', default=None, help='Output path for result (default: <image>_bsub.tiff)')
    parser.add_argument('-m', '--mode', default='None', choices=['None', 'gradient', 'laplace'], help='Optimization mode (default: gradient)')
    parser.add_argument('-x', '--align-x', action='store_true', default=False,help='Optimize x alignment (default: False)')
    parser.add_argument('-y', '--align-y', action='store_true', default=False, help='Optimize y alignment (default: False)')
    parser.add_argument('-d', '--display', action='store_true', default=True, help='Display results (default: True)')
    parser.add_argument('-s', '--save', action='store_true', default=True, help='Save results (default: True)')
    parser.add_argument('--max-x-shift', type=int, default=5, help='Maximum x shift (default: 5)')
    parser.add_argument('--max-y-shift', type=int, default=5, help='Maximum y shift (default: 5)')
    parser.add_argument('--alpha-min', type=float, default=0.0, help='Minimum alpha (default: 0.0)')
    parser.add_argument('--alpha-max', type=float, default=10.0, help='Maximum alpha (default: 10.0)')
    parser.add_argument('--saxs', action='store_true', default=False, help='Also process corresponding SAXS data using learned alpha')
    args = parser.parse_args()

    # Prepare config
    config = BSubConfig(
        optimization_mode=args.mode,
        max_x_shift=args.max_x_shift,
        max_y_shift=args.max_y_shift,
        alpha_bounds=(args.alpha_min, args.alpha_max),
        save_results=args.save,
        display_results=args.display
    )

    # Output path logic
    output_path = args.output
    if output_path is None:
        stem, ext = os.path.splitext(os.path.basename(args.image))
        output_path = f"{stem}.tiff"

    # Run workflow
    subtractor = BSubtractor(config)
    image = imread(args.image)
    background = imread(args.background)
    mask = subtractor.load_mask(args.mask)
    alpha, x_shift, y_shift = subtractor.optimize_alpha_and_alignment(
        image, background, mask, align_x=args.align_x, align_y=args.align_y
    )
    logger.info(f"Optimization Done: alpha={alpha:.3f}, x_shift={x_shift}, y_shift={y_shift}")
    result = subtractor.subtract_background(image, background, alpha, x_shift, y_shift)
    if args.display:
        subtractor.visualize_results(image, result, mask, alpha, x_shift, y_shift)
    if args.save:
        subtractor.save_result(result, output_path, alpha, x_shift, y_shift)
    
    # Process SAXS data if requested
    if args.saxs:
        try:
            saxs_image_path = subtractor.waxs_to_saxs(args.image)
            saxs_background_path = subtractor.waxs_to_saxs(args.background)
            saxs_output_path = subtractor.waxs_to_saxs(output_path)
            
            if os.path.exists(saxs_image_path) and os.path.exists(saxs_background_path):
                logger.info(f"Processing SAXS data with learned alpha: {alpha:.3f}")
                saxs_result = subtractor.process_saxs(
                    saxs_image_path, saxs_background_path, alpha, 
                    saxs_output_path if args.save else None
                )
                logger.info("SAXS processing completed")
            else:
                logger.warning("SAXS files not found - skipping SAXS processing")
        except Exception as e:
            logger.error(f"Error processing SAXS data: {e}")

# Maintain backward compatibility
def check_mask(file_info, directory, bgd_index=-1, kapton_mask_path=None, **kwargs):
    """Legacy function for checking mask alignment."""
    bgd_filename = file_info.iloc[bgd_index].Filename
    bgd_path = os.path.join(directory, bgd_filename)
    check_mask_alignment(bgd_path, kapton_mask_path)