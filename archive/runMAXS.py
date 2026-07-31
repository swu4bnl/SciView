#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Imports
########################################

import sys, os
import time
import fnmatch
#SciAnalysis_PATH='/home/kyager/current/code/SciAnalysis/main/'
SciAnalysis_PATH='/nsls2/data/cms/legacy/xf11bm/software/SciAnalysis/'
SciAnalysis_PATH in sys.path or sys.path.append(SciAnalysis_PATH)

import glob
from SciAnalysis import tools
from SciAnalysis.XSAnalysis.Data import *
from SciAnalysis.XSAnalysis import Protocols

import matplotlib.pyplot as plt
cmap_vge = plt.get_cmap('viridis')


# Define some custom analysis routines
########################################


# Experimental parameters
########################################

# Experimental parameters (loaded from YAML config)
########################################
import yaml
with open('caliMS.yaml', 'r') as f:
    cfg = yaml.safe_load(f)

from SciAnalysis.XSAnalysis.DataRQconv import *
calibration = CalibrationRQconv(wavelength_A=cfg["wavelength_A"])
calibration.set_image_size(cfg["image_size"][0], height=cfg["image_size"][1])
calibration.set_pixel_size(pixel_size_um=cfg["pixel_size_um"])
calibration.set_angles(det_orient=0, det_tilt=0.0, det_phi=0, incident_angle=0., sample_normal=0.) #tilt = 1.5 as of 2025/06
calibration.set_beam_position(cfg["beam_position"][0], cfg["beam_position"][1])
calibration.set_distance(cfg["distance"])

mask = Mask("./combined_mask_MAXS.png")


# Files to analyze
########################################
# source_dir = '../maxs/raw/'
source_dir = '../maxs/stitched/'
output_dir = os.path.dirname(source_dir.rstrip('/')) + '/analysis/'

pattern = '*' 

# Turn on to keep watching for new files/folders during experiment.
MONITOR_MODE = False
MONITOR_INTERVAL_S = 10

infiles = glob.glob(os.path.join(source_dir, pattern+'.tiff'))
infiles.sort()

source_folders = [d for d in glob.glob(source_dir, recursive=True) if os.path.isdir(d)]
infiles = []
for folder in source_folders:
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.is_file() and fnmatch.fnmatch(entry.name, pattern + '.tiff'):
                infiles.append(entry.path)
infiles.sort()


# Analysis to perform
########################################

load_args = { 'calibration' : calibration, 
             'mask' : mask,
            #  'mask' : None,
             #'rot180' : False,
             #'flip' : True, # PSCCD
             }
run_args = { 'verbosity' : 3,
            }

with open('reduction_recipe_MAXS.yaml', 'r') as f:
    reduction_cfg = yaml.safe_load(f)

q_bounds = reduction_cfg.get('q_bounds', {})

# Fallbacks preserve the previous behavior if a field is missing in reduction_recipe.yaml.
q_min = q_bounds.get('q_min', reduction_cfg.get('q_min', 0))
q_max = q_bounds.get('q_max', reduction_cfg.get('q_max', 4))
qx_min = q_bounds.get('qx_min', -2.7)
qx_max = q_bounds.get('qx_max', 2.7)
qz_min = q_bounds.get('qz_min', -0.2)
qz_max = q_bounds.get('qz_max', 3)
angle_start_deg = reduction_cfg.get('angle_start_deg', 0)
angle_end_deg = reduction_cfg.get('angle_end_deg', 180)

process = Protocols.ProcessorXS(load_args=load_args, run_args=run_args)

# Examples:
#protocols = [ Protocols.circular_average_q2I(plot_range=[0, 0.2, 0, None]) ]
#protocols = [ Protocols.linecut_angle(q0=0.01687, dq=0.00455*1.5, show_region=False) ]
#protocols = [ Protocols.q_image(blur=1.0, bins_relative=0.5, plot_range=[-0.1, 3.0, 0, 3.0], _xticks=[0, 1.0, 2.0, 3.0], ztrim=[0.2, 0.01]) ]
#protocols = [ Protocols.qr_image(blur=1.0, bins_relative=0.5, plot_range=[-0.1, 3.0, 0, 3.0], _xticks=[0, 1.0, 2.0, 3.0], zmin=1010., ztrim=[None, 0.01]) ]
#protocols = [ Protocols.qr_image(blur=None, bins_relative=0.8, plot_range=[-0.1, 3.0, 0, 3.0], _xticks=[0, 1.0, 2.0, 3.0], ztrim=[0.38, 0.002], dezing_fill=True) ]
#protocols = [ Protocols.q_phi_image(bins_relative=0.25, plot_range=[0, 3.0, 0, +90]) ]

protocols = [
    Protocols.q_phi_image(bins_relative=0.5, plot_range=[q_min, q_max, angle_start_deg, angle_end_deg],save_results=['npz', 'png']),
    # Protocols.calibration_check(show=False, AgBH=True, q0=1.369*0.25, dq=0.002, num_rings=10, ztrim=[0.2, 0.01], dpi=300) ,
    # Protocols.thumbnails(crop=None, blur=0, resize=1, cmap=cmap_vge, ztrim=[0.06, 0.001], zmin=0.0) , # PSCCD
    Protocols.q_image(blur=0.0, plot_range=[qx_min, qx_max, qz_min, qz_max], colorbar=True, save_results=['npz','png']) ,
    Protocols.circular_average(ylog=True, plot_range=[q_min, q_max, 0, None],  gridlines=True) ,
    Protocols.qr_image(blur=0.0, bins_relative=0.5, plot_range=[qx_min, qx_max, qz_min, qz_max], _xticks=[0, 1.0, 2.0, 3.0], ztrim=[0.05, 0.01], save_results=['npz', 'png']) ,
    # Protocols.sector_average(name='vertical', angle=90, dangle=20, ylog=True, plot_range=[0.2, 5.0, None, None], save_results = [ 'plots','txt']) ,
    # Protocols.sector_average(name='horizontal', angle=0, dangle=20, ylog=True, plot_range=[0.2, 5.0, None, None], save_results = [ 'plots','txt']) ,    
    # Protocols.circular_average(ylog=True, plot_range=[1, 2, 0, None],  gridlines=True) ,
    # Protocols.thumbnails(name= '1393961', crop=None, blur=0, resize=1, cmap=cmap_vge, ztrim=[0.06, 0.001], zmin=0.0) , # PSCCD
    Protocols.thumbnails(crop=None, resize=1, blur=0.0,  cmap=cmap_vge, ztrim=[0.05, 0.001]) , # Pilatus800k
    ]
    



# Run
########################################
print('Processing {} infiles...'.format(len(infiles)))
def process_files(file_list):
    files_by_folder = {}
    for f in file_list:
        folder = os.path.dirname(f)
        files_by_folder.setdefault(folder, []).append(f)

    for folder, folder_files in files_by_folder.items():
        if '/raw/' in folder:
            folder_output_dir = folder.replace('/raw/', '/analysis/')
        elif '/stitched/' in folder:
            folder_output_dir = folder.replace('/stitched/', '/analysis/')
        elif folder.endswith('/raw'):
            folder_output_dir = folder[:-len('/raw')] + '/analysis'
        elif folder.endswith('/stitched'):
            folder_output_dir = folder[:-len('/stitched')] + '/analysis'
        else:
            folder_output_dir = output_dir

        os.makedirs(folder_output_dir, exist_ok=True)
        process.run(folder_files, protocols, output_dir=folder_output_dir, force=True)

process_files(infiles)


# Loop
########################################
if MONITOR_MODE:
    print('Monitoring is ON. Waiting for new files...')
    seen_files = set(infiles)
    folder_mtime_ns = {}
    for folder in [d for d in glob.glob(source_dir, recursive=True) if os.path.isdir(d)]:
        try:
            folder_mtime_ns[folder] = os.stat(folder).st_mtime_ns
        except OSError:
            continue

    while True:
        new_files = []
        current_folders = [d for d in glob.glob(source_dir, recursive=True) if os.path.isdir(d)]

        for folder in current_folders:
            try:
                current_mtime_ns = os.stat(folder).st_mtime_ns
            except OSError:
                continue

            previous_mtime_ns = folder_mtime_ns.get(folder)
            if previous_mtime_ns is not None and current_mtime_ns <= previous_mtime_ns:
                continue

            folder_mtime_ns[folder] = current_mtime_ns
            with os.scandir(folder) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    if not fnmatch.fnmatch(entry.name, pattern + '.tiff'):
                        continue
                    if entry.path in seen_files:
                        continue
                    seen_files.add(entry.path)
                    new_files.append(entry.path)

        new_files.sort()
        if new_files:
            print('Found {} new infiles...'.format(len(new_files)))
            process_files(new_files)
        time.sleep(MONITOR_INTERVAL_S)
