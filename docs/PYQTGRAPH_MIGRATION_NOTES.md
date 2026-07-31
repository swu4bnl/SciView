# PyQtGraph Image Viewer Migration Notes

## Initial Inventory

- `tabs/base_image_tab.py` creates the shared detector-image canvas with `FigureCanvas`, `NavigationToolbar`, `plt.subplots`, `ax_raw`, `fig_raw`, and `canvas_raw`; it owns image display settings, image normalization, log limits, view preservation, display hooks, reset behavior, and cursor-value reporting.
- `tabs/calibration_tab.py` inherits the shared raw-image canvas, connects Matplotlib mouse events, draws beam-center points and calibration rings on `ax_raw`, and keeps its derived Q-space plots on a separate Matplotlib canvas.
- `tabs/image_browser_tab.py` inherits the shared raw-image canvas and directly clears/texts/titles `ax_raw` for loading and empty states.
- `tabs/mask_tab.py` aliases `ax_image = ax_raw` and `canvas_image = canvas_raw`, connects Matplotlib mouse events, and draws mask overlays through display hooks and `imshow`.
- `tabs/reduction_tab.py` keeps reduction curves on Matplotlib and uses display hooks to draw ROI/sector overlays on the inherited detector image axes.
- `tabs/protocol_preview_tab.py` creates Matplotlib preview thumbnails with `imshow`; these are image displays but separate from the shared central detector viewer.
- `tabs/transform_tab.py` uses Matplotlib for derived transform images and should be evaluated separately from the interactive detector-image canvas.
- `src/sciview/interfaces/stable_qt/tools/mask_drawing_tools.py` expects Matplotlib mouse-event fields: `inaxes`, `xdata`, and `ydata`.
- `src/sciview/interfaces/stable_qt/utils/reduction_overlay.py` returns Matplotlib artists for mask/ROI overlays on detector axes.

## Baseline

- `rg` was unavailable in the current PowerShell environment, so the inventory used workspace text search.
- `pytest` and `python` were unavailable on PATH.
- `pixi run pytest` completed with no output under the current quiet pytest configuration.
- The most recent recorded manual launch command was `./Launch-SciView-win64.cmd`, exit code `0`, before this migration slice.