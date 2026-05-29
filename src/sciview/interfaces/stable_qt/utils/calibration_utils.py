"""
Calibration utilities and helpers

This module provides utilities for calibration file handling,
parameter validation, and export functionality.
"""

import os
import yaml
from typing import Dict, Any, Optional
from datetime import datetime

from sciview.settings.app_settings import EXPORT_SETTINGS, PHYSICAL_CONSTANTS


class CalibrationManager:
    """Manager for calibration parameters and file operations"""
    
    def __init__(self):
        self.precision = EXPORT_SETTINGS['precision']
        self.hc_e = PHYSICAL_CONSTANTS['hc_over_e_eV_A']
    
    def wavelength_to_energy(self, wavelength_A: float) -> float:
        """Convert wavelength to energy"""
        return self.hc_e / wavelength_A if wavelength_A > 0 else 0.0
    
    def energy_to_wavelength(self, energy_eV: float) -> float:
        """Convert energy to wavelength"""
        return self.hc_e / energy_eV if energy_eV > 0 else 0.0
    
    def validate_calibration_params(self, params: Dict[str, Any]) -> Dict[str, str]:
        """
        Validate calibration parameters
        
        Args:
            params: Dictionary of calibration parameters
            
        Returns:
            dict: Dictionary of validation errors (empty if all valid)
        """
        errors = {}
        
        # Required parameters
        required = ['wavelength_A', 'distance_m', 'pixel_size_um', 'beam_position']
        for param in required:
            if param not in params:
                errors[param] = f"Missing required parameter: {param}"
                continue
            
            if param == 'beam_position':
                if not isinstance(params[param], (list, tuple)) or len(params[param]) != 2:
                    errors[param] = "Beam position must be [x, y] coordinates"
            else:
                try:
                    value = float(params[param])
                    if value <= 0:
                        errors[param] = f"{param} must be positive"
                except (ValueError, TypeError):
                    errors[param] = f"{param} must be a valid number"
        
        # Validate ranges
        if 'wavelength_A' in params and 'wavelength_A' not in errors:
            wl = float(params['wavelength_A'])
            if not 0.01 <= wl <= 10.0:
                errors['wavelength_A'] = "Wavelength must be between 0.01 and 10.0 Å"
        
        if 'distance_m' in params and 'distance_m' not in errors:
            dist = float(params['distance_m'])
            if not 0.01 <= dist <= 10.0:
                errors['distance_m'] = "Distance must be between 0.01 and 10.0 m"
        
        return errors
    
    def create_calibration_dict(self, 
                              wavelength_A: float,
                              beam_position: tuple,
                              distance_m: float,
                              pixel_size_um: float,
                              image_size: tuple = None,
                              angles: Dict[str, float] = None,
                              mask_info: Dict[str, str] = None) -> Dict[str, Any]:
        """
        Create a complete calibration dictionary
        
        Args:
            wavelength_A: X-ray wavelength in Angstroms
            beam_position: (x, y) beam center in pixels
            distance_m: Sample to detector distance in meters
            pixel_size_um: Pixel size in micrometers
            image_size: Optional (width, height) in pixels
            angles: Optional detector angles
            mask_info: Optional mask file information
            
        Returns:
            dict: Complete calibration parameters
        """
        energy_eV = self.wavelength_to_energy(wavelength_A)
        
        calib = {
            'wavelength_A': round(wavelength_A, self.precision['wavelength']),
            'energy_eV': round(energy_eV, self.precision['energy']),
            'pixel_size_um': round(pixel_size_um, self.precision['pixel_size']),
            'distance_m': round(distance_m, self.precision['distance']),
            'beam_position': [round(beam_position[0], self.precision['beam_position']),
                            round(beam_position[1], self.precision['beam_position'])],
            'timestamp': datetime.now().isoformat(),
            'software': 'SciAnalysis GUI'
        }
        
        if image_size:
            calib['image_size'] = list(image_size)
        
        if angles:
            calib['detector_angles'] = {
                'orient_deg': round(angles.get('orient', 0), self.precision['angles']),
                'tilt_deg': round(angles.get('tilt', 0), self.precision['angles']),
                'phi_deg': round(angles.get('phi', 0), self.precision['angles'])
            }
        
        if mask_info:
            calib['mask_info'] = mask_info
        
        return calib
    
    def export_to_yaml(self, calibration_dict: Dict[str, Any], output_path: str) -> bool:
        """
        Export calibration to YAML file
        
        Args:
            calibration_dict: Calibration parameters
            output_path: Output file path
            
        Returns:
            bool: True if export successful
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w') as f:
                # Add header comment
                f.write(f"# Calibration file generated by SciAnalysis GUI\\n")
                f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n")
                f.write(f"# Wavelength: {calibration_dict['wavelength_A']} Å "
                       f"({calibration_dict['energy_eV']:.1f} eV)\\n\\n")
                
                yaml.dump(calibration_dict, f, default_flow_style=False, sort_keys=False)
            
            return True
            
        except Exception as e:
            print(f"Error exporting calibration: {e}")
            return False
    
    def load_from_yaml(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Load calibration from YAML file
        
        Args:
            file_path: Path to calibration file
            
        Returns:
            dict or None: Calibration parameters if successful
        """
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)
            
            # Validate loaded data
            errors = self.validate_calibration_params(data)
            if errors:
                print(f"Validation errors in {file_path}: {errors}")
                return None
            
            return data
            
        except Exception as e:
            print(f"Error loading calibration: {e}")
            return None


def format_calibration_summary(calib_dict: Dict[str, Any]) -> str:
    """
    Create a human-readable summary of calibration parameters
    
    Args:
        calib_dict: Calibration dictionary
        
    Returns:
        str: Formatted summary
    """
    summary = []
    
    if 'wavelength_A' in calib_dict:
        wl = calib_dict['wavelength_A']
        energy = calib_dict.get('energy_eV', 0)
        summary.append(f"Wavelength: {wl:.4f} Å ({energy:.1f} eV)")
    
    if 'beam_position' in calib_dict:
        x, y = calib_dict['beam_position']
        summary.append(f"Beam Center: ({x:.2f}, {y:.2f}) pixels")
    
    if 'distance_m' in calib_dict:
        dist = calib_dict['distance_m']
        summary.append(f"Distance: {dist:.3f} m")
    
    if 'pixel_size_um' in calib_dict:
        pixel = calib_dict['pixel_size_um']
        summary.append(f"Pixel Size: {pixel:.1f} µm")
    
    if 'image_size' in calib_dict:
        w, h = calib_dict['image_size']
        summary.append(f"Image Size: {w} × {h} pixels")
    
    return "\\n".join(summary)


# Create global instance for easy access
calibration_manager = CalibrationManager()