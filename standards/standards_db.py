# Standard diffraction Q positions for common materials (in 1/Angstrom)
# Add more materials as needed

# References:
# 1. AgBh: https://gisaxs.com/index.php/Material:Silver_behenate
# 2. CeO2: https://gisaxs.com/index.php/Material:Cerium_oxide
# 3. LaB6: https://gisaxs.com/index.php/Material:Lanthanum_boride
# 4. Sucrose: https://gisaxs.com/index.php/Material:Sucrose
# 5. Al: https://www.tedpella.com/technote_html/619%20TN.pdf
# 6. Au: https://periodictable.com/Properties/A/LatticeConstants.al.html
# 7. Si: https://periodictable.com/Properties/A/LatticeConstants.al.html


STANDARDS = {
    "AgBh": [0.1076, 0.2152, 0.3228, 0.4304, 0.5380, 0.6456, 0.7532, 0.8608, 0.9684, 1.076, 1.184, 1.369, 1.387],
    "CeO2": [2.015, 2.326, 3.288, 3.854, 4.025, 4.647],
    "Al":   [2.689, 3.103, 4.388, 5.138, 5.374, 6.206, 6.741, 6.938, 7.597],
    "Au":   [2.669, 3.088, 4.364, 5.116, 5.342, 6.170, 6.726, 6.904, 7.558],
    "Si":   [2.004, 3.272, 3.837, 4.629, 5.042, 5.666, 6.012, 6.547, 6.840, 7.300],
    "LaB6": [1.51148927, 2.1359, 2.6160, 3.0207, 3.3772, 3.6995, 4.2719, 4.5310, 4.7761, 5.0092, 5.232],
    "Sucrose": [0.5933, 0.8289, 0.9054, 0.9336, 1.10000],
}
