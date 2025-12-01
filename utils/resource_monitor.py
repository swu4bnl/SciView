"""
Resource Monitor Module

Provides utilities for monitoring CPU and memory usage of the application.
Used for displaying performance metrics in the UI for debugging and optimization.
"""

import os
import psutil
from typing import Dict, Tuple


class ResourceMonitor:
    """Monitor CPU and memory usage of the current process"""
    
    def __init__(self):
        """Initialize the resource monitor"""
        try:
            self.process = psutil.Process(os.getpid())
            self.available = True
        except Exception as e:
            print(f"Warning: psutil not available for resource monitoring: {e}")
            self.available = False
    
    def get_memory_usage(self) -> Dict[str, str]:
        """
        Get current memory usage of the application.
        
        Returns:
            Dict with keys 'current' and 'percent' containing formatted strings.
            Returns empty dict if monitoring unavailable.
        """
        if not self.available:
            return {}
        
        try:
            mem_info = self.process.memory_info()
            # Memory in bytes, convert to MB
            mem_mb = mem_info.rss / (1024 * 1024)
            
            # Percentage of total system memory
            mem_percent = self.process.memory_percent()
            
            return {
                'current': f"{mem_mb:.1f} MB",
                'percent': f"{mem_percent:.1f}%"
            }
        except Exception as e:
            print(f"Error getting memory usage: {e}")
            return {}
    
    def get_cpu_usage(self, interval: float = 0.1) -> str:
        """
        Get current CPU usage percentage of the application.
        
        Args:
            interval: Time interval in seconds for measurement. Default 0.1s.
        
        Returns:
            Formatted string with CPU percentage, or empty string if unavailable.
        """
        if not self.available:
            return ""
        
        try:
            # Get CPU percent over the specified interval
            cpu_percent = self.process.cpu_percent(interval=interval)
            return f"{cpu_percent:.1f}%"
        except Exception as e:
            print(f"Error getting CPU usage: {e}")
            return ""
    
    def get_resource_info(self) -> Tuple[str, str]:
        """
        Get combined resource usage info in a compact format.
        
        Returns:
            Tuple of (cpu_str, memory_str) suitable for display in status bar.
            Example: ("12.5%", "142.3 MB")
        """
        cpu_str = self.get_cpu_usage()
        mem_info = self.get_memory_usage()
        mem_str = mem_info.get('current', 'N/A')
        
        return (cpu_str, mem_str)
    
    def get_resource_status(self) -> str:
        """
        Get formatted resource usage string for status bar display.
        
        Returns:
            Formatted string like "CPU: 12.5% | Mem: 142.3 MB (8.5%)"
            or empty string if monitoring unavailable.
        """
        if not self.available:
            return ""
        
        try:
            cpu_str = self.get_cpu_usage()
            mem_info = self.get_memory_usage()
            
            if cpu_str and mem_info:
                return f"CPU: {cpu_str} | Mem: {mem_info['current']} ({mem_info['percent']})"
            return ""
        except Exception as e:
            print(f"Error getting resource status: {e}")
            return ""


# Global resource monitor instance
_resource_monitor = None


def get_resource_monitor() -> ResourceMonitor:
    """Get or create the global resource monitor instance"""
    global _resource_monitor
    if _resource_monitor is None:
        _resource_monitor = ResourceMonitor()
    return _resource_monitor
