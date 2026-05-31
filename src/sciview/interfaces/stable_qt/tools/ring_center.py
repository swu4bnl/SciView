"""
Ring Center Calculation Tools

This module provides algorithms for calculating beam center positions
from diffraction ring coordinates.
"""

import numpy as np
from typing import List, Tuple, Optional


class RingCenterCalculator:
    """Calculator for determining beam center from diffraction rings"""
    
    def __init__(self):
        self.tolerance = 1e-10
        # Accept noisier manual picks from GUI workflows.
        self.max_relative_radius_std = 0.20
        
    def calculate_center(self, points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float]]:
        """
        Calculate circle center and radius from multiple points using least squares fitting
        
        Args:
            points: List of (x, y) coordinate tuples (minimum 3 points)
            
        Returns:
            tuple: (center_x, center_y, radius) or None if calculation fails
            
        Raises:
            ValueError: If points are invalid or insufficient
        """
        if len(points) < 3:
            raise ValueError("At least three points required")
            
        # Validate points
        for i, (x, y) in enumerate(points):
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                raise ValueError(f"Point {i+1} coordinates must be numeric")
            if not (np.isfinite(x) and np.isfinite(y)):
                raise ValueError(f"Point {i+1} coordinates must be finite")
        
        # For 3 points, use exact analytical solution
        if len(points) == 3:
            return self._calculate_from_three_points_exact(points)
        
        # For >3 points, use least squares fitting
        return self._calculate_from_multiple_points_fit(points)
    
    def _calculate_from_three_points_exact(self, points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
        """Exact calculation for 3 points using circumcenter method"""
        (x1, y1), (x2, y2), (x3, y3) = points
        
        # Check if points are collinear using triangle area
        area = 0.5 * abs((x1*(y2-y3) + x2*(y3-y1) + x3*(y1-y2)))
        if area < self.tolerance:
            raise ValueError("Points are collinear - no unique circle exists")
        
        # Calculate circumcenter using determinant method
        d = 2 * (x1*(y2-y3) + x2*(y3-y1) + x3*(y1-y2))
        if abs(d) < self.tolerance:
            raise ValueError("Cannot calculate center - points are collinear")
        
        # Calculate center coordinates
        ux = ((x1*x1 + y1*y1)*(y2-y3) + (x2*x2 + y2*y2)*(y3-y1) + (x3*x3 + y3*y3)*(y1-y2)) / d
        uy = ((x1*x1 + y1*y1)*(x3-x2) + (x2*x2 + y2*y2)*(x1-x3) + (x3*x3 + y3*y3)*(x2-x1)) / d
        
        # Calculate radius
        radius = np.sqrt((x1-ux)**2 + (y1-uy)**2)
        
        return ux, uy, radius
    
    def _calculate_from_multiple_points_fit(self, points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
        """Least squares fitting for multiple points"""
        from scipy.optimize import minimize
        
        # Convert points to numpy arrays
        points_array = np.array(points)
        x_coords = points_array[:, 0]
        y_coords = points_array[:, 1]
        
        # Initial guess: centroid of points
        x0 = np.mean(x_coords)
        y0 = np.mean(y_coords)
        
        def objective(params):
            """Objective function: sum of squared deviations from circle"""
            cx, cy = params
            distances = np.sqrt((x_coords - cx)**2 + (y_coords - cy)**2)
            mean_radius = np.mean(distances)
            return np.sum((distances - mean_radius)**2)
        
        # Optimize center position
        result = minimize(objective, [x0, y0], method='BFGS')
        
        if not result.success:
            raise ValueError("Optimization failed to converge")
        
        # Calculate final center and radius
        cx, cy = result.x
        distances = np.sqrt((x_coords - cx)**2 + (y_coords - cy)**2)
        radius = np.mean(distances)
        
        # Verify fit quality
        std_radius = np.std(distances)
        relative_std = std_radius / radius if radius > 0 else float('inf')
        
        if relative_std > self.max_relative_radius_std:
            raise ValueError(f"Poor circle fit: radius variation {relative_std*100:.1f}%")
        
        return cx, cy, radius

    def calculate_from_three_points(self, points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float]]:
        """Legacy method - calls calculate_center for backward compatibility"""
        return self.calculate_center(points)
    
    def calculate_from_multiple_rings(self, ring_points: List[List[Tuple[float, float]]]) -> Tuple[float, float]:
        """
        Calculate beam center from multiple diffraction rings
        
        Args:
            ring_points: List of rings, each containing list of (x, y) points
            
        Returns:
            tuple: (center_x, center_y) - averaged from multiple rings
            
        Raises:
            ValueError: If insufficient data or calculation fails
        """
        if not ring_points:
            raise ValueError("At least one ring required")
        
        centers = []
        
        for i, ring in enumerate(ring_points):
            if len(ring) < 3:
                raise ValueError(f"Ring {i+1} must have at least 3 points")
            
            # Use first three points for each ring
            try:
                ux, uy, _ = self.calculate_from_three_points(ring[:3])
                centers.append((ux, uy))
            except ValueError as e:
                raise ValueError(f"Ring {i+1}: {str(e)}")
        
        # Calculate weighted average (equal weights for now)
        center_x = np.mean([c[0] for c in centers])
        center_y = np.mean([c[1] for c in centers])
        
        return center_x, center_y
    
    def validate_ring_quality(self, points: List[Tuple[float, float]], center: Tuple[float, float]) -> dict:
        """
        Assess the quality of a ring fit
        
        Args:
            points: List of (x, y) coordinates on the ring
            center: (center_x, center_y) of the circle
            
        Returns:
            dict: Quality metrics including std deviation, mean radius, etc.
        """
        if len(points) < 3:
            raise ValueError("At least 3 points required for quality assessment")
        
        cx, cy = center
        distances = [np.sqrt((x-cx)**2 + (y-cy)**2) for x, y in points]
        
        mean_radius = np.mean(distances)
        std_radius = np.std(distances)
        relative_std = std_radius / mean_radius if mean_radius > 0 else float('inf')
        
        return {
            'mean_radius': mean_radius,
            'std_radius': std_radius,
            'relative_std_percent': relative_std * 100,
            'min_radius': min(distances),
            'max_radius': max(distances),
            'radius_range': max(distances) - min(distances),
            'num_points': len(points),
            'quality_score': 1.0 / (1.0 + relative_std)  # Higher is better
        }


def calculate_ring_center(points: List[Tuple[float, float]]) -> Tuple[float, float, float]:
    """
    Convenience function for calculating ring center from multiple points
    
    Args:
        points: List of (x, y) coordinate tuples (minimum 3 points)
        
    Returns:
        tuple: (center_x, center_y, radius)
        
    Raises:
        ValueError: If calculation fails
    """
    calculator = RingCenterCalculator()
    return calculator.calculate_center(points)


def validate_coordinates(coords_text: List[str]) -> List[Tuple[float, float]]:
    """
    Validate and convert coordinate text inputs to numeric values
    
    Args:
        coords_text: List of coordinate strings in format ['x1,y1', 'x2,y2', ...]
        
    Returns:
        List of (x, y) tuples
        
    Raises:
        ValueError: If coordinates are invalid
    """
    points = []
    
    for i, coord_str in enumerate(coords_text):
        try:
            if ',' in coord_str:
                x_str, y_str = coord_str.split(',', 1)
            else:
                raise ValueError("Coordinates must be separated by comma")
                
            x = float(x_str.strip())
            y = float(y_str.strip())
            
            if not (np.isfinite(x) and np.isfinite(y)):
                raise ValueError("Coordinates must be finite numbers")
                
            points.append((x, y))
            
        except ValueError as e:
            raise ValueError(f"Point {i+1}: {str(e)}")
    
    return points