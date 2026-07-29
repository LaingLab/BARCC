#    BARCC (Brain Atlas Regional Cell Counter) is a software that performs automatic cell counting 
#    of microscopy images and assists in the automation of image workup. 
#    Copyright (C) <2025>  <George Taylor>

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

#!/usr/bin/env python3
import fitz
import tkinter as tk
from tkinter import filedialog as fd, ttk, messagebox, simpledialog, Toplevel
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageEnhance
import numpy as np
import copy
from skimage import filters, morphology, measure, util, feature, segmentation, color, restoration, exposure
from skimage.morphology import closing, disk
from scipy.ndimage import distance_transform_edt
from scipy import ndimage as ndi
from dataclasses import dataclass
import enum
import math
import csv

import pandas as pd
import os
import io
import logging
import yaml
import sys
import json
from datetime import datetime
import platform
import subprocess
import webbrowser
import zipfile
from io import BytesIO

# Windows taskbar branding: must run *before* the first Tk() window is created.
# Without an explicit AppUserModelID, Windows groups BARCC under the host process
# (python.exe / Jupyter) and shows that host's icon instead of barcc_icon.ico.
_BARCC_APP_USER_MODEL_ID = "LaingLab.BARCC.RegionalIFAnalyzer"


def _configure_windows_app_identity():
    """Tell Windows this process is BARCC, not Python/Jupyter (taskbar icon + grouping)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _BARCC_APP_USER_MODEL_ID
        )
    except Exception:
        pass


# Configure logging
logging.basicConfig(
    level=logging.INFO,       # For normal operations and major steps
    # level=logging.WARNING,    # For recoverable errors
    # level=logging.DEBUG,        # For detailed operational information
    # level=logging.ERROR,      # For critical issues
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define configuration dataclasses and enums
@dataclass
class CellDetectionConfig:
    # Detection strategy
    detection_method: str = "blob"          # "blob" (blob_log) or "watershed" (old method)

    # --- Legacy Watershed parameters (kept for fallback) ---
    threshold_method: str = "otsu" 
    manual_threshold: float = 0.5
    adaptive_block_size: int = 101
    local_radius: int = 15
    min_cell_size: int = 20
    max_cell_size: int = 100
    circularity_threshold: float = 0.7
    min_peak_distance: int = 5
    peak_min_intensity: float = 0.1
    watershed_compactness: float = 0.0

    # --- Blob Detection (blob_log) parameters ---
    blob_min_sigma: float = 2.0
    blob_max_sigma: float = 10.0
    blob_num_sigma: int = 12
    blob_threshold: float = 0.08
    blob_overlap: float = 0.5
    blob_min_area: int = 15          # post-filter
    blob_max_area: int = 300
    blob_min_circularity: float = 0.6

@dataclass
class PreprocessingConfig:
    background_method: str = "tophat"  # Changed to tophat as default
    # Background correction methods
    disk_radius: int = 15        # Reduced radius for efficiency
    # Noise reduction
    denoise_method: str = "gaussian"
    bg_gaussian_sigma: float = 1.0
    nr_gaussian_sigma: float = 1.0
    median_kernel: int = 3
    bilateral_sigma_color: float = 0.1
    bilateral_sigma_space: float = 1.0
    # Contrast enhancement
    contrast_method: str = "stretch"
    clahe_kernel: int = 8
    clahe_clip_limit: float = 2.0
    gamma: float = 1.0
    # Signal enhancement
    enhance_method: str = "unsharp mask"
    unsharp_radius: float = 1.0
    unsharp_amount: float = 2.0

# beginning fleshing these out
class BrainImage:
    def __init__(self):
        self.original_image = None
        self.scaled_image = None
        self.background_image = None
        self.cell_mask = None
        self.regions = None
        self.paint = None
 

class CellMask:
    def __init__(self):
        self.combined_mask = None
        self.auto_mask = None
        self.add_mask = None
        self.remove_mask = None


class ImageProcessor:
    def __init__(self):
        self.cell_config = CellDetectionConfig()
        self.preprocess_config = PreprocessingConfig()
        self.load_config()

    def load_config(self):
        """Load configuration from file if it exists"""
        config_path = "barcc_config.yaml"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                try:
                    config = yaml.safe_load(f)
                    if 'cell_detection' in config:
                        cell_config = config['cell_detection']
                        
                        for key, value in cell_config.items():
                            if hasattr(self.cell_config, key):
                                setattr(self.cell_config, key, value)
                               
                    if 'preprocessing' in config:
                        for key, value in config['preprocessing'].items():
                            if hasattr(self.preprocess_config, key):
                                setattr(self.preprocess_config, key, value)
                except Exception as e:
                    logger.error(f"Failed to load config: {e}", exc_info=True)

    def save_config(self):
        """Save current configuration to file"""
        try:
            # Convert enum to string before saving
            cell_config_dict = self.cell_config.__dict__.copy()
            
            config = {
                'cell_detection': cell_config_dict,
                'preprocessing': self.preprocess_config.__dict__
            }
            with open("barcc_config.yaml", 'w') as f:
                yaml.dump(config, f)
        except Exception as e:
            logger.error(f"Failed to save config: {e}", exc_info=True)

    def preprocess_image(self, image):
        """Apply preprocessing steps based on configuration"""
        logger.debug("Starting image preprocessing")
        img = np.array(image).astype(float) / 255.0
        
        try:
            # Background correction
            if self.preprocess_config.background_method == "tophat":
                logger.debug("Applying white tophat transform")
                from skimage.morphology import white_tophat, disk # not a fan of this
                selem = disk(self.preprocess_config.disk_radius)  # Using a smaller fixed radius for efficiency
                img = white_tophat(img, selem)
                logger.debug("White tophat transform completed successfully")
            elif self.preprocess_config.background_method == "gaussian":
                logger.debug("Using gaussian background subtraction")
                # Simple background estimation using gaussian blur
                from scipy.ndimage import gaussian_filter # not a fan of this
                background = gaussian_filter(img, sigma=self.preprocess_config.bg_gaussian_sigma)
                img = img - background
                img = np.clip(img, 0, 1)  # Normalize to [0,1] range
            else:
                logger.error("No valid background correction method, use either 'tophat' or 'gaussian'")
                logger.debug("Skipping background correction")
                pass  # No background correction
        except Exception as e:
            logger.error(f"Error in background correction: {str(e)}")
            # Fall back to no background correction
            logger.info("Falling back to no background correction")
            pass

        # Noise reduction
        if self.preprocess_config.denoise_method == "gaussian":
            logger.debug("Applying Gaussian noise reduction")
            img = filters.gaussian(img, sigma=self.preprocess_config.nr_gaussian_sigma)
        elif self.preprocess_config.denoise_method == "median":
            logger.debug("Applying median noise reduction")
            img = filters.median(img, footprint=disk(self.preprocess_config.median_kernel))
        elif self.preprocess_config.denoise_method == "bilateral":
            logger.debug("Applying bilateral noise reduction")
            img = restoration.denoise_bilateral(
                img,
                sigma_color=self.preprocess_config.bilateral_sigma_color,
                sigma_spatial=self.preprocess_config.bilateral_sigma_space
            )
        else:
            logger.error("No valid noise reduction, use either 'median', 'gaussian', or 'bilateral'")
            pass

        # Contrast enhancement
        if self.preprocess_config.contrast_method == "stretch":
            logger.debug("Applying contrast stretching")
            img = exposure.rescale_intensity(img)
        elif self.preprocess_config.contrast_method == "clahe":
            logger.debug("Applying CLAHE")
            img = exposure.equalize_adapthist(
                img,
                kernel_size=self.preprocess_config.clahe_kernel,
                clip_limit=self.preprocess_config.clahe_clip_limit
            )
        elif self.preprocess_config.contrast_method == "gamma":
            logger.debug("Applying gamma correction")
            img = exposure.adjust_gamma(img, self.preprocess_config.gamma)
        else:
            logger.error("No valid contrast enhancement, use either 'stretch', 'clahe', or 'gamma'")
            pass

        # Signal enhancement
        if self.preprocess_config.enhance_method == "unsharp mask":
            logger.debug("Applying unsharp mask")
            img = filters.unsharp_mask(
                img,
                radius=self.preprocess_config.unsharp_radius,
                amount=self.preprocess_config.unsharp_amount
            )
        else:
            logger.error("No valid signal enhancement, use 'unsharp mask'")
            pass

        return img

    def detect_cells(self, image):
        """Detect cells using current configuration.
        Supports two strategies:
          - "blob": Uses skimage.feature.blob_log (recommended for fluorescent spots)
          - "watershed": Legacy threshold + watershed method
        """
        logger.debug(f"Starting cell detection with method: {self.cell_config.detection_method}")

        # Preprocess the image
        img = self.preprocess_image(image)

        if self.cell_config.detection_method == "blob":
            return self._detect_cells_blob(img)
        else:
            return self._detect_cells_watershed(img)

    def _detect_cells_blob(self, img: np.ndarray):
        """Modern blob detection using Laplacian of Gaussian.
        Much more robust for variably bright fluorescent cells.
        """
        cfg = self.cell_config

        # Run blob_log - finds bright blobs across scales
        blobs = feature.blob_log(
            img,
            min_sigma=cfg.blob_min_sigma,
            max_sigma=cfg.blob_max_sigma,
            num_sigma=cfg.blob_num_sigma,
            threshold=cfg.blob_threshold,
            overlap=cfg.blob_overlap,
            log_scale=False
        )

        # Convert to labels image
        labels = np.zeros(img.shape, dtype=int)
        cell_id = 1

        for y, x, sigma in blobs:
            # Estimate radius from sigma (blob_log sigma ≈ radius / sqrt(2))
            radius = int(sigma * 1.8) + 1
            area = int(np.pi * radius * radius)

            # Post-filter by size and rough circularity
            if not (cfg.blob_min_area <= area <= cfg.blob_max_area):
                continue

            # Draw a filled disk as the cell region (simple but effective)
            rr, cc = np.ogrid[:img.shape[0], :img.shape[1]]
            mask = (rr - y) ** 2 + (cc - x) ** 2 <= radius ** 2

            # Only label if not already claimed (avoid heavy overlap)
            free_space = labels[mask] == 0
            if free_space.sum() > (mask.sum() * 0.6):  # mostly free
                labels[mask] = cell_id
                cell_id += 1

        return img, labels

    def _detect_cells_watershed(self, img: np.ndarray):
        """Legacy detection method (kept for compatibility)."""
        cfg = self.cell_config

        # Thresholding
        if cfg.threshold_method == "otsu":
            thresh = filters.threshold_otsu(img)
        elif cfg.threshold_method == "adaptive":
            thresh = filters.threshold_local(img, block_size=cfg.adaptive_block_size)
        elif cfg.threshold_method == "local":
            thresh = filters.threshold_local(
                img, block_size=cfg.local_radius * 2 + 1, method='gaussian'
            )
        elif cfg.threshold_method == "manual":
            thresh = cfg.manual_threshold
        else:
            thresh = 0

        binary = img > thresh

        # Size and shape filtering
        labeled = measure.label(binary)
        props = measure.regionprops(labeled)

        mask = np.zeros_like(binary)
        for prop in props:
            if (cfg.min_cell_size <= prop.area <= cfg.max_cell_size and
                    prop.perimeter ** 2 / (4 * np.pi * prop.area) <= 1 / cfg.circularity_threshold):
                mask[tuple(prop.coords.T)] = True

        # Watershed
        distance = distance_transform_edt(mask)
        coords = feature.peak_local_max(
            distance,
            min_distance=cfg.min_peak_distance,
            threshold_abs=cfg.peak_min_intensity,
            exclude_border=True
        )

        markers = np.zeros_like(distance, dtype=bool)
        markers[tuple(coords.T)] = True
        markers = measure.label(markers)

        labels = segmentation.watershed(
            -distance,
            markers,
            mask=mask,
            compactness=cfg.watershed_compactness
        )

        return img, labels

# This is old so we should drop it to prevent obscurity
def binary_mask_cell_count(background_pil, processor=None):
    """Enhanced cell detection using ImageProcessor class.
    If processor is provided, use its current config (important for live Mask Settings + Autotune).
    """
    if processor is None:
        processor = ImageProcessor()
    img, labels = processor.detect_cells(background_pil)
    return img, labels > 0
    

def split_stacked_tiff(file_path):
# Inputs a stacked tiff file and produces a subfolder in the same directory with 
# the unstacked tiffs

    if os.path.isfile(file_path) == False:
        logger.warning('File does not exist, Exiting')
        return

    abs_path = os.path.abspath(file_path)
    img = Image.open(abs_path)
    num_of_tiffs = img.n_frames

    if num_of_tiffs < 1:
        logger.warning('No Tiff Found, Exiting')
        return
    if num_of_tiffs < 2:
        logger.warning('Tiff Not Stacked // No Stacked Tiff Found, Exiting')
        return
    # absolute path without file extention (.tiff)
    full_file_name, ext = os.path.splitext(abs_path) 
    # file name without extention
    file_name = os.path.basename(full_file_name)
    # absolute path of save directory
    save_dir = full_file_name + '_split_imgs'

    if os.path.isdir(save_dir):
        logger.error('Save directory already exists, Exiting')
        return

    os.mkdir(save_dir)

    for i in range (num_of_tiffs):
        try:
            img.seek(i)
            save_name = file_name + f'_ch{i}.tiff'
            full_save_name = os.path.join(save_dir, save_name)
            img.save(full_save_name)
        except EOFError: #end of file error
            logger.debug('Number of splits caused an error, Exiting')
            return



class PDFViewer:
    def __init__(self):
        logger.info("Initializing PDFViewer")
        # AppUserModelID before Tk so the taskbar does not inherit Jupyter/python branding
        _configure_windows_app_identity()
        self.root = tk.Tk()
        self.master = self.root
        self.master.title('Regional IF Analyzer')
        self.master.geometry('%dx%d' % (self.master.winfo_screenwidth(), self.master.winfo_screenheight()))
        self.master.resizable(True, True)
        self.master.rowconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=0)
        self.master.columnconfigure(0, weight=1)

        # App logo (antibody + fluorophore) for title bar and Windows taskbar
        self._set_app_icon()
        # Re-apply after the HWND exists / is mapped (first paint is when taskbar picks icon)
        try:
            self.master.after_idle(self._set_app_icon)
            self.master.after(200, self._set_app_icon)
            self.master.after(800, self._set_app_icon)
        except Exception:
            pass

        # Subsystems
        self.pdf_handler = PDFHandler()
        self.state_manager = StateManager()
        self.image_processor = ImageProcessor()

        # App state
        self.path = None
        self.doc = None
        self.current_page = 0
        self.num_pages = 0
        self.zoom = 1.0
        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}

        # Per-region atlas editing (new feature for adjusting individual atlas region shapes)
        self.selected_zone_id = None
        self.selected_page = None
        # For Allen (and multi-blob zones): only the connected component under the click
        # is highlighted — avoids lighting up both mirrored hemispheres when IDs are shared.
        self.selected_zone_component = None  # optional bool ndarray same shape as mask

        # Undo/state
        self.undo_stack = self.state_manager.undo_stack

        # Paint variables
        self.brush_size = tk.IntVar(value=4.0)
        self.DEFAULT_COLOR = 'black'

        # Grouped paint strokes: each continuous mouse-down to mouse-up is one "structural boundary"
        self._paint_group_counter = 0
        self.current_paint_group = None
        self.named_paint_groups = {}   # group_tag (e.g. 'paintgroup_5') -> name
        self.paint_group_data = {}     # durable: group_tag -> list of {'coords': [x1,y1,...], 'width': w}  (survives show_page/delete("all"))

        # For painted regions that have been named: store the boundary outline so that
        # edge/border deformation can refit the visible black drawn line to the new mask shape.
        self.painted_zone_outlines = {}  # zid -> {'points': [(x,y), ...] in model space, 'width': int }

        # Crop / edit variables
        self.crop_mode = False
        self.crop_mode_var = tk.BooleanVar(value=False)
        self.crop_rect = None          # primary outline canvas id (legacy name)
        self.crop_ui_ids = []          # all crop overlay canvas ids
        self.crop_box = None           # (left, top, right, bottom) canvas coords when set
        self.crop_pending = False      # selection drawn; waiting for move / apply
        self._crop_interaction = None  # None | 'draw' | 'move'
        self._crop_draw_anchor = None  # (x, y) canvas start of rubber-band
        self._crop_move_origin = None  # (x, y) canvas pointer at move start
        self._crop_box_at_move_start = None
        self.start_x = None
        self.start_y = None

        self.edit_mode = False
        self.edit_mode_var = tk.BooleanVar(value=False)
        self.img_x = 0
        self.img_y = 0
        self.drag_start_x = None
        self.drag_start_y = None

        # Mask editing state
        self.editing_mask = False
        self.mask_edit_add = True  # True = add cells, False = remove cells
        self.splitting_cells = False  # True = Split Cell click mode
        self.current_mask = None   # reference to the current mask being edited
        self.auto_mask = None
        self.showing_auto_mask = False

        # Measure Tune (interactive sample-based blob parameter estimation)
        self.measure_tune_active = False
        self.measure_tune_phase = None  # 'cells' | 'background'
        self.measure_tune_cell_points = []  # list of (x, y) in image coords
        self.measure_tune_bg_points = []
        self.measure_tune_cell_feats = []
        self.measure_tune_bg_feats = []
        self.measure_tune_markers = []  # canvas item ids for sample markers
        self.measure_tune_status_var = None
        self.measure_tune_detail_var = None
        self.measure_tune_status_window = None
        self.measure_tune_settings_geometry = None
        self._measure_tune_img = None
        self._measure_tune_scale = 1.0

        # View zoom (separate from PDF render zoom)
        self.view_scale = 1.0
        self.min_scale = 0.2
        self.max_scale = 8.0

        # Display options
        self.show_zone_labels_var = tk.BooleanVar(value=False)
        self.zone_counts_window = None
        self.show_zone_intensity_labels_var = tk.BooleanVar(value=False)
        self.zone_intensity_window = None
        self.last_intensity_df = None  # region intensity table for on-canvas labels
        # Last options used for axon/PNN intensity correction (remembered in-session)
        self._intensity_corr_prefs = {
            "use_bg": False,
            "bg_percentile": 10.0,
            "use_norm": False,
            "norm_path": "",
        }

        # Transparent menu / window mode
        self.transparent_mode = tk.BooleanVar(value=False)
        self.transparent_windows = []  # popups that should follow transparent mode

        # Atlas ribbon visibility and state (must be created before _build_gui so View menu can reference it)
        self.show_atlas_ribbon = tk.BooleanVar(value=True)
        self.atlas_ribbon_expanded = False
        self.border_mode_var = tk.BooleanVar(value=False)
        self.region_move_mode = tk.BooleanVar(value=False)
        self.region_translate_active = False
        self.count_button_packed = False
        self.count_button = None
        self.region_translate_zid = None
        self.region_translate_start_mx = 0.0
        self.region_translate_start_my = 0.0
        self.region_translate_original_mask = None
        self.region_list_id_map = {}

        # Paint mode indicator (updated in start_paint / stop_paint and similar)
        self.paint_status_var = tk.StringVar(value="Paint: off")

        # Persistent paint layer (this is the key to zoom-safe painting)
        self.paint_layer = None  # RGBA PIL Image, created when background is loaded

        # Manual edit masks
        self.manual_add_mask = None
        self.manual_remove_mask = None

        # Background (TIFF) image
        self.background_image = None
        self.original_background = None
        self.bg_photo_id = None
        self.atlas_filetype = None
        self.allen_zone_meta = {}  # page -> {local_zid: Allen structure metadata}
        self.allen_nissl_reference = None  # pure Nissl PIL for 30% reference strip
        self.allen_nissl_photo = None  # PhotoImage keep-alive
        self.allen_borders_pure = None  # pure black structure borders (re-composited after fills)

        # TIFF filename
        self.tiff_filename = None
        self.tiff_dir = None

        # File browser
        self.current_tiff_directory = None
        self.tiff_file_list = []   # list of full paths (source TIFFs only)
        self.current_tiff_path = None  # full path of the TIFF currently open in the viewer
        self._tree_path_to_iid = {}  # normalized path -> tree iid (for highlight)

        # Last DF for counts
        self.last_df = None
        self.last_cell_mask = None  # for flattened save including masked cells
        # When True, Count Cells / Show Mask reuse auto_mask (loaded or locked) without re-detecting
        self.cell_mask_locked = False
        self.cell_mask_source_path = None
        # Ground-truth vs random null distribution (cyan overlay; GT stays red)
        self.random_cell_mask = None
        self.random_cell_labels = None  # int32 label map (1..N matched pairs)
        self.random_cell_mask_meta = None  # dict: n_cells, stratified, seed, etc.
        # Perineuronal (PNN) shells: outer disk area = 2× cell area, minus cell body
        self.perineuronal_mask = None           # bool union (GT cells)
        self.perineuronal_labels = None         # int32 label map (GT cell id)
        self.perineuronal_cells = None          # list of cell records
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None
        self.perineuronal_area_factor = 2.0

        # Brightness
        self.brightness = 0.0
        self._brightness_after_id = None  # debounce handle for slider
        # Cache: display-sized background *without* brightness (keyed by scale + image id)
        self._bg_display_base_cache = None  # (key, PIL.Image)

        # Mouse state tracking
        self.current_state = None

        # Init windows (not needed, init windows when spawned)
#       self.brush_win = None

        # Build GUI
        self._build_gui()
        self.init_keybinds()

        self._update_paint_indicator()
        # Restore last working folder (Phase A file browser)
        try:
            self._restore_ui_prefs()
        except Exception as e:
            logger.warning(f"Could not restore UI prefs: {e}")

        self.root.mainloop()

    def init_keybinds(self):
        # Keyboard shortcuts
        self.master.bind('<q>', self.quit)
        self.master.bind('<Control-z>', self._undo_event)
        self.master.bind('<Control-s>', self.save_flattened_image)
        self.master.bind('<Return>', self._commit_painted_border_refit)
        self.master.bind('<KP_Enter>', self._commit_painted_border_refit)
        self.master.bind('<Escape>', self._on_escape_key)
        # File browser navigation (Phase A)
        self.master.bind('<Control-Left>', self._nav_previous_image_event)
        self.master.bind('<Control-Right>', self._nav_next_image_event)
        self.master.bind('<Control-Shift-Right>', self._nav_next_uncounted_event)

        # Bind click event for highlighting
        self.output.bind("<Button-1>", self.highlight_region)

    def _set_app_icon(self):
        """Set the Regional IF Analyzer logo on the window and Windows taskbar.

        Uses Application/assets/barcc_icon.ico (taskbar) plus multi-size PNG
        PhotoImages via iconphoto. Keeps strong references so Tk does not GC the
        icon (a common reason the taskbar falls back to the default Tk feather).

        On Windows, also sets AppUserModelID and WM_SETICON on the top-level HWND
        so the taskbar does not keep the Jupyter/python host icon.
        """
        self._app_icons = []  # strong refs for PhotoImage
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            assets = os.path.join(base, "assets")
            ico_path = os.path.abspath(os.path.join(assets, "barcc_icon.ico"))
            png_path = os.path.abspath(os.path.join(assets, "barcc_icon.png"))

            # Re-assert process identity (safe if already set; helps late launches)
            _configure_windows_app_identity()

            # Windows: .ico is the most reliable for the taskbar / Alt-Tab
            if os.path.isfile(ico_path):
                try:
                    # default= applies to this and future Toplevels
                    self.master.iconbitmap(default=ico_path)
                except Exception:
                    try:
                        self.master.iconbitmap(ico_path)
                    except Exception as e:
                        logger.debug(f"iconbitmap failed: {e}")
                # Force taskbar / Alt-Tab icon via Win32 (Tk alone often leaves host icon)
                self._apply_windows_taskbar_icon(ico_path)

            # Cross-platform / title-bar: multi-resolution PhotoImages
            icon_photos = []
            if os.path.isfile(png_path):
                try:
                    pil = Image.open(png_path).convert("RGBA")
                    for sz in (16, 24, 32, 48, 64):
                        resized = pil.resize((sz, sz), Image.LANCZOS)
                        icon_photos.append(ImageTk.PhotoImage(resized))
                except Exception as e:
                    logger.debug(f"icon PNG load failed: {e}")

            if not icon_photos:
                # Fallback: draw antibody + fluorophore in-memory (same motif)
                icon_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(icon_img)
                draw.ellipse((2, 2, 61, 61), fill=(18, 28, 48, 255))
                draw.line((32, 20, 32, 36), fill=(240, 248, 255, 255), width=4)
                draw.line((32, 36, 16, 56), fill=(240, 248, 255, 255), width=4)
                draw.line((32, 36, 48, 56), fill=(240, 248, 255, 255), width=4)
                draw.ellipse((22, 6, 42, 26), fill=(57, 255, 20, 255), outline=(20, 160, 40, 255))
                for sz in (16, 32, 48):
                    icon_photos.append(
                        ImageTk.PhotoImage(icon_img.resize((sz, sz), Image.LANCZOS))
                    )

            if icon_photos:
                self._app_icons = icon_photos
                try:
                    self.master.iconphoto(True, *icon_photos)
                except TypeError:
                    # Older Tk: single image only
                    self.master.iconphoto(True, icon_photos[0])
                except Exception as e:
                    logger.debug(f"iconphoto failed: {e}")
        except Exception as e:
            logger.warning(f"Could not set application icon: {e}")

    def _apply_windows_taskbar_icon(self, ico_path):
        """Load barcc_icon.ico onto the real top-level HWND (Windows taskbar / Alt-Tab)."""
        if sys.platform != "win32" or not ico_path or not os.path.isfile(ico_path):
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            # Ensure window handle exists
            try:
                self.master.update_idletasks()
            except Exception:
                pass

            hwnd = int(self.master.winfo_id())
            # Tk often reports a child frame; climb to the top-level window
            GA_ROOT = 2
            try:
                root = user32.GetAncestor(hwnd, GA_ROOT)
                if root:
                    hwnd = int(root)
            except Exception:
                try:
                    parent = user32.GetParent(hwnd)
                    if parent:
                        hwnd = int(parent)
                except Exception:
                    pass

            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            # LoadImageW needs a unicode path
            ico_w = os.path.abspath(ico_path)

            LoadImageW = user32.LoadImageW
            LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            LoadImageW.restype = wintypes.HANDLE

            hicon_big = LoadImageW(
                None, ico_w, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
            hicon_small = LoadImageW(None, ico_w, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if not hicon_big and not hicon_small:
                # Fallback: system metrics sizes
                try:
                    cx = user32.GetSystemMetrics(11)  # SM_CXICON
                    cy = user32.GetSystemMetrics(12)  # SM_CYICON
                    hicon_big = LoadImageW(
                        None, ico_w, IMAGE_ICON, cx, cy, LR_LOADFROMFILE
                    )
                except Exception:
                    pass
            if not hicon_big and not hicon_small:
                return

            SendMessageW = user32.SendMessageW
            if hicon_small:
                SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hicon_big:
                SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
            # Prevent GC of HICONs while the app runs
            self._win_hicons = [h for h in (hicon_small, hicon_big) if h]
        except Exception as e:
            logger.debug(f"WM_SETICON taskbar icon failed: {e}")

    def quit(self, _):
        self.root.destroy()

    def disable_event(self):
        pass

    def _build_gui(self):
        # Menu
        self.menu = tk.Menu(self.master)
        self.master.config(menu=self.menu)

        # Create File menu dropdown 
        filemenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="Split Tiff", command=self.split_tiff)
        filemenu.add_command(label="Import Tiff", command=self.import_tiff)
        filemenu.add_command(label="Import Paint", command=self.open_paint)
        filemenu.add_command(label="Save Atlas Schematic…", command=self.save_atlas_schematic)
        filemenu.add_command(label="Load Atlas Schematic…", command=self.load_atlas_schematic)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_separator()
        filemenu.add_command(label="Previous Image", command=self.previous_image, accelerator="Ctrl+Left")
        filemenu.add_command(label="Next Image", command=self.next_image, accelerator="Ctrl+Right")
        filemenu.add_command(label="Next Uncounted", command=self.next_uncounted_image, accelerator="Ctrl+Shift+Right")
        filemenu.add_command(label="Next Channel…", command=self.next_channel)
        filemenu.add_command(label="Clear Canvas", command=self.clear_canvas_session)
        filemenu.add_separator()
        filemenu.add_command(label="User Manual", command=self.open_user_manual)
        filemenu.add_command(label="Exit", command=self.master.destroy)

        # Create Edit menu dropdown
        editmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Edit", menu=editmenu)
        editmenu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        editmenu.add_separator()
        # Add save paint command and create toplevels with widgets
        editmenu.add_command(label="Brightness", command=self.show_brightness_settings)
        editmenu.add_command(label="Save Picture", command=self.save_flattened_image)
        # editmenu.add_command(label="Save Paint", command=print("Save Paint", file=sys.stderr))

        # Create Atlas menu dropdown
        atlasmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Atlas", menu=atlasmenu)
        atlasmenu.add_command(label="Import Atlas (PDF)", command=self.import_atlas)
        atlasmenu.add_command(label="Import Allen Atlas…", command=self.open_allen_atlas_browser)
        atlasmenu.add_command(
            label="Download Full Allen Atlas…",
            command=self.download_full_allen_atlas,
        )
        atlasmenu.add_separator()
        atlasmenu.add_checkbutton(label="Crop", variable=self.crop_mode_var, command=self.toggle_crop_mode)
        atlasmenu.add_checkbutton(label="Move", variable=self.edit_mode_var, command=self.toggle_edit_mode)
        atlasmenu.add_command(label="Rotate", command=self.show_rotate_settings)
        atlasmenu.add_command(label="Scale", command=self.show_scale_settings)
        atlasmenu.add_command(label="Fit Atlas to Image", command=self.fit_atlas_to_image)
        atlasmenu.add_separator()
        atlasmenu.add_command(label="Save Atlas Schematic…", command=self.save_atlas_schematic)
        atlasmenu.add_command(label="Load Atlas Schematic…", command=self.load_atlas_schematic)
        atlasmenu.add_command(label="Clear Atlas", command=self.clear_atlas)

        # Per-region transforms for individually selected atlas zones (new in this update)
        atlasmenu.add_separator()
        atlasmenu.add_command(label="Select Region", command=self.select_region)
        atlasmenu.add_command(label="Deselect Region", command=self.deselect_region)
        atlasmenu.add_command(label="Rotate Selected Region", command=self.show_rotate_selected_dialog)
        atlasmenu.add_command(label="Scale Selected Region", command=self.show_scale_selected_dialog)

        # Paint tools as a section under Atlas (no top-level Paint menu)
        atlasmenu.add_separator()
        paintmenu = tk.Menu(atlasmenu, tearoff=0)
        atlasmenu.add_cascade(label="Paint", menu=paintmenu)
        paintmenu.add_command(label="Start Paint", command=self.start_paint)
        paintmenu.add_command(label="Stop Paint", command=self.stop_paint)
        paintmenu.add_command(label="Pen", command=self.use_pen)
        paintmenu.add_command(label="Eraser", command=self.use_eraser)
        paintmenu.add_command(label="Brushsize", command=self.show_brush_settings)
        paintmenu.add_separator()
        paintmenu.add_command(label="Load Paint", command=self.load_paint)
        paintmenu.add_command(label="Save Paint Layer", command=self.save_paint_layer)

        # Cell menu (formerly Mask) — mask edit tools + counting subcategory
        cellmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Cell", menu=cellmenu)
        cellmenu.add_command(label="Show Mask", command=self.show_cell_mask_threshold)
        cellmenu.add_command(label="Show Mask Settings", command=self.show_mask_settings)
        cellmenu.add_command(label="Add Cell", command=self.start_add_cells)
        cellmenu.add_command(label="Remove Cell", command=self.start_remove_cells)
        cellmenu.add_command(label="Split Cell", command=self.start_split_cell)
        cellmenu.add_command(label="Finish Mask Edit", command=self.stop_mask_edit)
        cellmenu.add_separator()
        cellmenu.add_command(label="Save Cell Mask…", command=self.save_cell_mask)
        cellmenu.add_command(label="Load Cell Mask…", command=self.load_cell_mask)
        cellmenu.add_command(
            label="Generate Random Cell Mask…",
            command=self.generate_random_cell_mask,
        )
        cellmenu.add_command(
            label="Show GT + Random Masks",
            command=self.show_ground_truth_and_random_masks,
        )
        cellmenu.add_command(
            label="Clear Random Cell Mask",
            command=self.clear_random_cell_mask,
        )
        cellmenu.add_separator()
        # Former top-level "Cell" items as a subcategory
        cell_count_menu = tk.Menu(cellmenu, tearoff=0)
        cellmenu.add_cascade(label="Counting", menu=cell_count_menu)
        cell_count_menu.add_command(label="Count Cells", command=self.count_cells)
        cell_count_menu.add_checkbutton(
            label="Show Zone Labels & Counts",
            variable=self.show_zone_labels_var,
            command=self._toggle_zone_labels_counts,
        )

        # Axons and Nets — region intensity / network analyses
        axonsmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Axons and Nets", menu=axonsmenu)
        axonsmenu.add_command(
            label="Measure Region Intensities…",
            command=self.measure_region_intensities,
        )
        axonsmenu.add_command(
            label="Counterstain Normalization Measurement…",
            command=self.measure_counterstain_normalization,
        )
        axonsmenu.add_checkbutton(
            label="Show Labels and Intensities",
            variable=self.show_zone_intensity_labels_var,
            command=self._toggle_zone_labels_intensities,
        )
        axonsmenu.add_separator()
        axonsmenu.add_command(
            label="Draw Perineuronal Masks",
            command=self.draw_perineuronal_masks,
        )
        axonsmenu.add_command(
            label="Measure Perineuronal Intensity…",
            command=self.measure_perineuronal_intensity,
        )
        axonsmenu.add_command(
            label="Show Perineuronal Masks",
            command=self.show_perineuronal_masks,
        )
        axonsmenu.add_command(
            label="Clear Perineuronal Masks",
            command=self.clear_perineuronal_masks,
        )

        # Create View menu dropdown
        viewmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="View", menu=viewmenu)

        def toggle_transparent_mode():
            # Main window always stays fully opaque
            self.master.attributes('-alpha', 1.0)

            # Update all currently open popups
            alpha = 0.3 if self.transparent_mode.get() else 1.0
            for w in self.transparent_windows[:]:
                try:
                    w.attributes('-alpha', alpha)
                except Exception:
                    if w in self.transparent_windows:
                        self.transparent_windows.remove(w)

        viewmenu.add_checkbutton(
            label="Transparent Mode (70%)",
            variable=self.transparent_mode,
            command=toggle_transparent_mode
        )

        viewmenu.add_separator()
        viewmenu.add_checkbutton(
            label="Show Atlas Manager Ribbon",
            variable=self.show_atlas_ribbon,
            command=self._toggle_atlas_ribbon_visibility
        )


        # Add highlight regions button to manually enable this

        # This works as a labeling scheme, but how do I have it update?
        # self.menu.add_command(label="Pen: "+str(self.draw_type.get()))

        # Main layout: Horizontal PanedWindow (File Browser | Image Viewer)
        self.main_paned = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        self.main_paned.grid(row=0, column=0, sticky='nsew')
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

        # --- Left File Browser Pane ---
        self.file_browser_frame = ttk.Frame(self.main_paned, width=240)
        self._build_file_browser(self.file_browser_frame)
        self.main_paned.add(self.file_browser_frame, weight=0)

        # --- Right Content Area (existing viewer) ---
        self.top_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.top_frame, weight=1)

        self.top_frame.rowconfigure(0, weight=0)  # ribbon row (collapsible Atlas Manager)
        self.top_frame.rowconfigure(1, weight=1)  # canvas viewer
        self.top_frame.rowconfigure(2, weight=0)  # horizontal scrollbar
        self.top_frame.columnconfigure(0, weight=1)

        # Atlas Manager ribbon (dropdown/expandable panel for selected region + manip options + border drag)
        self._build_atlas_ribbon(self.top_frame)
        self.atlas_ribbon.grid(row=0, column=0, columnspan=2, sticky='ew', padx=2, pady=1)
        self._update_ribbon_selection()

        # Respect initial visibility from View menu var (default shown)
        if not self.show_atlas_ribbon.get():
            self.atlas_ribbon.grid_remove()

        # Scrollbars and canvas (viewer area shifted down to make room for ribbon)
        self.scrolly = ttk.Scrollbar(self.top_frame, orient=tk.VERTICAL)
        self.scrolly.grid(row=1, column=1, sticky='ns')
        self.scrollx = ttk.Scrollbar(self.top_frame, orient=tk.HORIZONTAL)
        self.scrollx.grid(row=2, column=0, sticky='ew')

        self.output = tk.Canvas(self.top_frame, bg='#ECE8F3')
        self.output.configure(yscrollcommand=self.scrolly.set, xscrollcommand=self.scrollx.set)
        self.output.grid(row=1, column=0, sticky='nsew')
        self.scrolly.configure(command=self.output.yview)
        self.scrollx.configure(command=self.output.xview)

        # Enable mouse wheel zoom
        self._bind_mousewheel()

        # Alt + drag panning
        self._pan_start_x = None
        self._pan_start_y = None
        self.output.bind("<Alt-ButtonPress-1>", self._start_pan)
        self.output.bind("<Alt-B1-Motion>", self._do_pan)
        self.output.bind("<Alt-ButtonRelease-1>", self._end_pan)

        # Interactive border drag support for selected atlas regions (pull only the dragged side)
        # These are additive so they coexist with other mode-specific bindings
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self.output.bind("<ButtonRelease-1>", self._end_border_drag, add=True)
        self.output.bind("<Motion>", self._update_cursor_for_atlas_border, add=True)
        self.border_drag_active = False
        self.border_drag_original_mask = None
        self.border_drag_centroid = (0.0, 0.0)
        self.border_drag_unit = (0.0, 1.0)
        self.border_drag_start_mouse = (0.0, 0.0)
        self.border_drag_zone = None

        # Edge editing state for precise local boundary pulling (new)
        self.edge_grab_active = False
        self.active_edge = None
        self.edge_closest_idx = 0
        self.edge_window = 30
        self.edge_start_idx = 0
        self.edge_end_idx = 0
        self.original_full_contour_for_edit = None
        self.current_edited_contour = None
        self.edge_highlight_item = None

        # Persistent selected edge for toggle (click to select/illuminate red, click again to deselect)
        self.selected_edge_full_contour = None
        self.selected_edge_start_idx = 0
        self.selected_edge_end_idx = 0
        self.selected_edge_closest = 0
        self._edge_pending_deselect = False
        self.edge_drag_start_pos = (0.0, 0.0)

    # End of UI, beginning of functions

    def split_tiff(self):
        path = fd.askopenfilename(filetypes=[("TIFF files", "*.tif *.tiff")])
        if path:
            split_stacked_tiff(path)

    def _update_paint_indicator(self):
        """Update the paint mode indicator label (in ribbon header) and window title."""
        base_title = "Regional IF Analyzer"
        if getattr(self, 'current_state', None) == 'paint':
            self.paint_status_var.set("🎨 PAINT ON")
            if hasattr(self, 'paint_status_label') and self.paint_status_label:
                try:
                    self.paint_status_label.configure(foreground="red", font=("Helvetica", 8, "bold"))
                except Exception:
                    pass
            try:
                self.master.title(base_title + " — 🎨 PAINT MODE")
            except Exception:
                pass
        else:
            self.paint_status_var.set("Paint: off")
            if hasattr(self, 'paint_status_label') and self.paint_status_label:
                try:
                    self.paint_status_label.configure(foreground="gray", font=("Helvetica", 8))
                except Exception:
                    pass
            try:
                self.master.title(base_title)
            except Exception:
                pass

    def start_paint(self):
        if self.current_state == 'paint':
            return
        self.current_state = 'paint'
        self.region_move_mode.set(False)
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        # Ensure paint_layer exists for visual baking (image-sized when a TIFF is loaded)
        if self.paint_layer is None:
            size = None
            if self.original_background is not None:
                size = self.original_background.size
            elif self.background_image is not None:
                size = self.background_image.size
            if size is not None:
                self.paint_layer = Image.new("RGBA", size, (0, 0, 0, 0))
        # Ensure zone mask exists / is ready to receive painted regions (merge into atlas mask)
        try:
            self._ensure_zone_mask_for_paint()
        except Exception as e:
            logger.debug(f"ensure zone mask on start_paint: {e}")
        self.show_brush_settings()
        self.old_x = None
        self.old_y = None
        self.current_paint_group = None
        self.color = self.DEFAULT_COLOR
        self.active_button = None
        self.use_pen()
        self.output.unbind('<Button-1>')
        self.output.bind('<Button-1>', self.paint)
        self.output.bind('<B1-Motion>', self.paint)
        self.output.bind('<ButtonRelease-1>', self.reset)
        # Right-click to name a painted region (comparable to atlas region labeling)
        self.output.bind('<Button-3>', self.name_painted_region)
        self.draw_type = 'drag'
        self.master.bind('<s>', self.reset_toggle)
        # Do not add "Pen: drag" to the top menu bar (it used to accumulate every Start Paint).
        # Clean up any leftover entries from older sessions still in this process.
        self._remove_paint_pen_menu_item()

        self._update_paint_indicator()

    def stop_paint(self):
        self.save_state()  # Snapshot the state with open paint groups/names before we auto-default, convert, bake and clear
        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>') 
        self.output.unbind('<Button-1>')
        self.output.unbind('<Button-3>')
        self.output.bind('<Button-1>', self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self._remove_paint_pen_menu_item()
        self.current_state = None
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None

        # Auto-assign default names to any painted strokes/groups that the user didn't explicitly name
        # This ensures the spreadsheet always gets populated with Painted Regions when using the paint tool.
        paint_items = self.output.find_withtag('paint')
        all_current_groups = set()
        for item in paint_items:
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    all_current_groups.add(tag)

        # Also include groups recorded in durable storage (in case show_page() wiped the transient 'paint' canvas items).
        # Retirement (pop + dtag inside convert/force) ensures already-committed groups are no longer present here.
        for gtag in list(self.paint_group_data.keys()):
            if gtag.startswith('paintgroup_'):
                all_current_groups.add(gtag)

        for group_tag in all_current_groups:
            if group_tag not in self.named_paint_groups:
                self.named_paint_groups[group_tag] = None  # will get default name in convert

        # Convert (named + auto-defaulted) paint groups to proper zones (for cell counting)
        self._convert_named_paints_to_zones()

        # Hardening for "named immediately then Count/Stop": if any groups remain in durable data
        # (e.g. name-time collection edge or dtag timing), re-add them to named (preserve user name)
        # and convert a second time before we clear. This ensures zones are populated even if first
        # pass missed strokes due to transient vector state.
        if self.named_paint_groups or self.paint_group_data:
            for gtag in list(self.paint_group_data.keys()):
                if gtag.startswith('paintgroup_') and gtag not in self.named_paint_groups:
                    # preserve a user-provided name if it was set before a prior failed convert
                    self.named_paint_groups[gtag] = self.named_paint_groups.get(gtag)
            if self.named_paint_groups:
                self._convert_named_paints_to_zones()

        # Now that the user has finished painting, bake everything into the paint_layer
        # and clean up the temporary canvas items. This is when labeling is "finalized".
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()

        self.output.delete('paint')   # Remove all temporary paint strokes from canvas
        self.save_paint()
        self.named_paint_groups.clear()
        self.paint_group_data.clear()
        self.current_paint_group = None
        self.show_page()

        self._update_paint_indicator()

        # Refresh ribbon so any auto-default "Painted Region N" names from Stop Paint appear immediately in the list
        self._update_ribbon_selection()

    def save_paint(self):
        """Save canvas paint strokes to an image without using postscript.

        Falls back to copying from the persistent paint_layer if no temporary
        canvas items are present (common after zoom or show_page).
        """
        paint_items = self.output.find_withtag('paint')
        
        # Fallback: if no temporary items, use whatever is already baked in paint_layer
        if not paint_items:
            if self.paint_layer is not None:
                self.img = self.paint_layer.copy()
                self.photo = ImageTk.PhotoImage(self.img)
                self.atlas_filetype = 'img'
                logger.debug("Used persistent paint_layer for save_paint (no canvas items)")
            else:
                logger.debug("No paint strokes to save")
            return

        # Get coordinates of entire painting area (the active vector strokes)
        try:
            bbox = self.output.bbox('paint')
            if bbox is None:
                logger.debug("No paint bbox found")
                return
            x1, y1, x2, y2 = bbox
        except Exception:
            logger.debug("Failed to get paint bbox")
            return
        # Modify coords so painting stays in the same place after conversion
        # This forces the bbox to start at the upper left corner of the canvas
        # This keeps the tiff and painting aligned even when importing the saved painting
        x1 = 0
        y1 = 0
        
        # Create a new transparent image
        # Keep original bbox so we can adjust coordinates relative to it
        bx1, by1, bx2, by2 = x1, y1, x2, y2
        img = Image.new('RGBA', (int(bx2 - bx1), int(by2 - by1)), (0, 0, 0, 0))

        # Draw each paint stroke onto the image
        draw = ImageDraw.Draw(img)

        for line in self.output.find_withtag('paint'):
            coords = self.output.coords(line)
            if not coords:
                continue

            if len(coords) != 4:
                logger.error("Wrong number of coordinates")

            # Convert canvas coords into point tuples for PIL
            points = []
            for i in range(0, len(coords), 2):
                x = coords[i]
                y = coords[i+1] 
                points.append((x, y))

            width = self.output.itemcget(line, 'width')
            try:
                width = int(float(width))
            except Exception:
                width = 1
            radius = math.floor(width / 2)
            fill = self.output.itemcget(line, 'fill')

            # Draw lines as points for roundness to fill jagged edges
            for (px, py) in points:
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)

            # Draw lines as lines for fast-drawn lines
            draw.line(points, fill=fill, width=width, joint="curve")

            
        
        # Set as current image
        self.img = img
        self.photo = ImageTk.PhotoImage(img)
        self.atlas_filetype = 'img'
        
        # Clear the canvas drawings
        self.output.delete('paint')
        
        logger.debug("Paint strokes saved to image successfully")

    def _commit_live_paint_strokes(self):
        """Commit any in-progress canvas paint strokes into the persistent paint_layer."""
        try:
            paint_items = self.output.find_withtag('paint')
            if paint_items:
                self._commit_canvas_paint_to_layer()
                self.output.delete('paint')
        except Exception:
            pass

    def _write_paint_bundle(self, save_path, layer, page):
        """Write a .barccpaint zip (strokes + zones + manifest) to save_path."""
        with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            bio = BytesIO()
            layer.save(bio, format='PNG')
            zf.writestr('strokes.png', bio.getvalue())
            if page in self.mask_images and self.mask_images[page] is not None:
                bio2 = BytesIO()
                self.mask_images[page].save(bio2, format='PNG')
                zf.writestr('zones.png', bio2.getvalue())
            manifest = {
                "format_version": 1,
                "type": "paint_with_regions",
                "saved_background_size": list(layer.size),
                "zone_names": self.zone_names.get(page, {}),
                "painted_zone_outlines": getattr(self, 'painted_zone_outlines', {}),
            }
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    def _save_paint_layer_to_dir(self, target_dir, base_name, unique=True, show_messages=True):
        """Save paint layer/bundle into target_dir.

        Returns the saved file path, or None if there was nothing to save / on failure.
        When unique=False, overwrites the canonical name (used by Count Cells auto-export).
        """
        if not target_dir or not os.path.isdir(target_dir):
            return None

        self._commit_live_paint_strokes()

        layer = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
        if layer is None:
            logger.debug("No painting to save")
            return None

        page = self.current_page
        has_labeled_regions = bool(
            self.zone_names.get(page, {}) or
            getattr(self, 'painted_zone_outlines', {})
        )

        # Skip empty transparent paint layers when there are no named/painted regions
        if not has_labeled_regions:
            try:
                arr = np.array(layer)
                if arr.ndim == 3 and arr.shape[2] >= 4 and not arr[:, :, 3].any():
                    logger.debug("Paint layer is empty; skipping save")
                    return None
            except Exception:
                pass

        try:
            if has_labeled_regions:
                if unique:
                    save_path = self._get_unique_paint_bundle_path(target_dir, base_name)
                else:
                    save_path = os.path.join(target_dir, f"{base_name}_paint_with_regions.barccpaint")
                self._write_paint_bundle(save_path, layer, page)
                logger.info(f"Saved paint bundle with regions to: {save_path}")
                if show_messages:
                    messagebox.showinfo("Paint + Regions Saved", f"Paint file with labeled regions saved to:\n{save_path}")
                return save_path
            else:
                if unique:
                    save_path = self._get_unique_paint_path(target_dir, base_name)
                else:
                    save_path = os.path.join(target_dir, f"{base_name}_paint.png")
                layer.save(save_path)
                logger.info(f"Auto-saved paint to: {save_path}")
                if show_messages:
                    messagebox.showinfo("Paint Saved", f"Paint layer saved to:\n{save_path}")
                return save_path
        except Exception as e:
            logger.error(f"Failed to save paint layer: {e}")
            if show_messages:
                messagebox.showerror("Save Error", f"Failed to save paint:\n{e}")
            return None

    def save_paint_layer(self):
        """Auto-save the current paint layer into <image_folder>/output/paint/.

        After saving, the File Browser list is refreshed so artifacts appear under the TIFF.
        """
        base_name = self.tiff_filename or "untitled"

        # Prefer image dir / browser folder → always write under its output/paint/ subfolder
        base_dir = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            base_dir = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            base_dir = self.current_tiff_directory

        if base_dir:
            target_dir = self._get_output_directory(base_dir, feature="paint")
            if not target_dir:
                messagebox.showerror("Save Error", "Could not create the output folder for paint save.")
                return
            path = self._save_paint_layer_to_dir(target_dir, base_name, unique=True, show_messages=True)
            if path and hasattr(self, 'tiff_tree') and self.current_tiff_directory:
                self.refresh_tiff_file_list()
            return

        # Fallback: no working directory → traditional save dialog
        self._commit_live_paint_strokes()
        layer = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
        if layer is None:
            logger.debug("No painting to save")
            return

        save_path = fd.asksaveasfilename(
            title="Save Paint Layer",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("BARCC Paint", "*.barccpaint")],
            initialfile=f"{base_name}_paint.png"
        )
        if not save_path:
            return
        try:
            page = self.current_page
            has_labeled_regions = bool(
                self.zone_names.get(page, {}) or
                getattr(self, 'painted_zone_outlines', {})
            )
            if has_labeled_regions:
                bundle_path = save_path
                if not bundle_path.lower().endswith('.barccpaint'):
                    bundle_path = os.path.splitext(save_path)[0] + '.barccpaint'
                self._write_paint_bundle(bundle_path, layer, page)
                messagebox.showinfo("Paint + Regions Saved", f"Paint file with labeled regions saved to:\n{bundle_path}")
            else:
                layer.save(save_path)
                messagebox.showinfo("Image Saved", f"Paint saved to: {save_path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save the paint image:\n{e}")

    def _get_unique_paint_path(self, directory, base_name):
        """Return a unique path like 'image_paint.png', 'image_paint (2).png', etc."""
        candidate = os.path.join(directory, f"{base_name}_paint.png")
        if not os.path.exists(candidate):
            return candidate

        counter = 2
        while True:
            candidate = os.path.join(directory, f"{base_name}_paint ({counter}).png")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _get_unique_paint_bundle_path(self, directory, base_name):
        """Return a unique path for a paint + regions bundle."""
        candidate = os.path.join(directory, f"{base_name}_paint_with_regions.barccpaint")
        if not os.path.exists(candidate):
            return candidate

        counter = 2
        while True:
            candidate = os.path.join(directory, f"{base_name}_paint_with_regions ({counter}).barccpaint")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def open_paint(self):
        """Load a paint layer (.png). Defaults to <folder>/output/paint/ when present."""
        initial_dir = self._preferred_open_dir(feature="paint")

        logger.info("Opening file dialog for paint selection")
        self.save_state()
        path = fd.askopenfilename(
            title="Load Paint",
            initialdir=initial_dir,
            filetypes=[
                ("BARCC Cropped Atlas", "*.catlas"),
                ("Legacy BARCC Atlas", "*.atlas"),
                ("BARCC Paint + Regions", "*.barccpaint"),
                ("PNG files", "*.png"),
                ("All files", "*.*")
            ]
        )
        if path:
            logger.info(f"Opening paint file: {path}")
            self.path = path
            if path.lower().endswith(('.catlas', '.atlas')):
                try:
                    self._load_atlas_file(path)
                except Exception as e:
                    messagebox.showerror("Load Error", f"Failed to load cropped atlas:\n{e}")
            elif path.lower().endswith('.barccpaint'):
                self._load_barccpaint_bundle(path)
            else:
                self.img = Image.open(path)
                clear_preprocess_cache()

                loaded_rgba = self.img.convert('RGBA') if self.img.mode != 'RGBA' else self.img
                self.paint_layer = loaded_rgba
                self.atlas_filetype = 'img'

                self.show_page()

                # Legacy sidecar support (plain PNG + _regions.json + _zones.png)
                try:
                    loaded_base = os.path.splitext(os.path.basename(path))[0]
                    load_dir = os.path.dirname(path) or "."
                    regions_json = os.path.join(load_dir, loaded_base + "_regions.json")
                    zones_png = os.path.join(load_dir, loaded_base + "_zones.png")

                    restored = False
                    page = self.current_page

                    if os.path.exists(regions_json):
                        with open(regions_json, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        names = data.get("zone_names", {})
                        if names:
                            names = {int(k): v for k, v in names.items()}
                            if page not in self.zone_names:
                                self.zone_names[page] = {}
                            self.zone_names[page].update(names)
                            restored = True
                        outlines = data.get("painted_zone_outlines", {})
                        if outlines:
                            outlines = {int(k): v for k, v in outlines.items()}
                            self.painted_zone_outlines.update(outlines)
                            restored = True

                    if os.path.exists(zones_png):
                        zone_mask = Image.open(zones_png).convert('L')
                        try:
                            if zone_mask.mode != 'L':
                                zone_mask = zone_mask.convert('L')
                            zarr = np.array(zone_mask).astype(np.uint8)
                            zone_mask = Image.fromarray(zarr, mode='L')
                        except Exception:
                            pass
                        self.mask_images[page] = zone_mask
                        restored = True

                    if restored:
                        if hasattr(self, '_update_ribbon_selection'):
                            self._update_ribbon_selection()
                        if hasattr(self, '_rebuild_page_overlays'):
                            try:
                                self._rebuild_page_overlays(page)
                            except Exception:
                                pass
                        self.show_page()
                        logger.info(f"Restored from legacy sidecars for {path}")
                except Exception as e:
                    logger.debug(f"No legacy sidecars: {e}")

    def load_paint(self):
        """Load a paint layer from the current working directory shown in the left File Browser.
        This is the recommended entry point from Atlas > Paint.
        """
        self.open_paint()

    def _load_barccpaint_bundle(self, path):
        """Load a .barccpaint bundle (strokes.png + zones.png + manifest with names).
        Restores both the visual painted boundaries and the labeled regions (names + shapes)
        into the Atlas Manager at the correct location relative to the current background.
        """
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                manifest = json.loads(zf.read('manifest.json').decode('utf-8'))

                # Visual strokes (black drawn boundaries)
                strokes = Image.open(BytesIO(zf.read('strokes.png')))
                self.paint_layer = strokes.convert('RGBA') if strokes.mode != 'RGBA' else strokes
                self.img = self.paint_layer.copy()
                self.atlas_filetype = 'img'

                # Match strokes layer size to current background (handles window resize / refit between save/load)
                if self.original_background is not None:
                    target = self.original_background.size
                    if self.paint_layer.size != target:
                        try:
                            self.paint_layer = self.paint_layer.resize(target, Image.NEAREST)
                            self.img = self.paint_layer.copy()
                        except Exception:
                            pass
                self.photo = ImageTk.PhotoImage(self.img)

                page = self.current_page

                # Zone mask (filled labeled region shapes)
                if 'zones.png' in zf.namelist():
                    zones = Image.open(BytesIO(zf.read('zones.png'))).convert('L')
                    # If background size differs, resize to match (nearest for mask ids)
                    if self.original_background is not None:
                        if zones.size != self.original_background.size:
                            zones = zones.resize(self.original_background.size, Image.NEAREST)
                    # Ensure clean uint8 label mask (prevents any dtype surprises downstream)
                    try:
                        if not isinstance(zones, Image.Image):
                            zones = Image.fromarray(np.asarray(zones).astype(np.uint8))
                        if zones.mode != 'L':
                            zones = zones.convert('L')
                        zarr = np.array(zones).astype(np.uint8)
                        zones = Image.fromarray(zarr, mode='L')
                    except Exception:
                        pass
                    self.mask_images[page] = zones

                # Names and outlines
                # json turns int keys into str; normalize back to int so sorted() and 'in' checks
                # with uint8 zids from masks don't trigger ufunc 'less' during comparisons.
                names = manifest.get('zone_names', {})
                if names:
                    names = {int(k): v for k, v in names.items()}
                    if page not in self.zone_names:
                        self.zone_names[page] = {}
                    self.zone_names[page].update(names)

                outlines = manifest.get('painted_zone_outlines', {})
                if outlines:
                    outlines = {int(k): v for k, v in outlines.items()}
                    self.painted_zone_outlines.update(outlines)

                # Make sure the zone counter for this page is high enough for any loaded zone ids
                # (prevents ID collisions on future naming, complements the ensure in ribbon populate).
                if page in self.zone_names and self.zone_names[page]:
                    try:
                        max_loaded = max((int(k) for k in self.zone_names[page].keys()), default=0)
                        if page not in self.zone_counters:
                            self.zone_counters[page] = 0
                        if self.zone_counters[page] < max_loaded:
                            self.zone_counters[page] = max_loaded
                    except Exception:
                        pass

                # Reset placement so everything lines up in background pixel space
                self.img_x = 0
                self.img_y = 0

                self.show_page()

                if hasattr(self, '_update_ribbon_selection'):
                    self._update_ribbon_selection()
                if hasattr(self, '_rebuild_page_overlays'):
                    try:
                        self._rebuild_page_overlays(page)
                    except Exception:
                        pass

            messagebox.showinfo("Paint Loaded", f"Loaded paint + labeled regions from:\n{path}")
            logger.info(f"Loaded barccpaint bundle: {path}")
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load paint bundle:\n{e}")
            logger.error(f"Failed to load barccpaint bundle {path}: {e}")

    # ------------------------------------------------------------------
    # .catlas schematic — cropped/labeled atlas + paint + Atlas Manager
    # (legacy .atlas files still load). Label on DAPI, apply to other channels.
    # ------------------------------------------------------------------

    def _atlas_schematic_has_content(self):
        """True if there is atlas drawing, zone mask/names, or paint worth saving."""
        page = self.current_page if self.current_page is not None else 0
        if self.zone_names.get(page):
            return True
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                if int(np.array(self.mask_images[page]).max()) > 0:
                    return True
            except Exception:
                return True
        if page in self.base_page_images and self.base_page_images[page] is not None:
            return True
        if getattr(self, "allen_borders_pure", None) is not None:
            return True
        if getattr(self, "painted_zone_outlines", None):
            return True
        if getattr(self, "paint_group_data", None):
            return True
        if getattr(self, "paint_layer", None) is not None:
            try:
                arr = np.array(self.paint_layer)
                if arr.ndim == 3 and arr.shape[2] >= 4 and arr[:, :, 3].any():
                    return True
            except Exception:
                pass
        return False

    def _serialize_zone_names(self, names):
        """JSON-safe zone_names: string keys, string values."""
        out = {}
        for k, v in (names or {}).items():
            try:
                out[str(int(k))] = str(v) if v is not None else f"Zone {k}"
            except Exception:
                out[str(k)] = str(v)
        return out

    def _serialize_painted_outlines(self, outlines):
        out = {}
        for k, v in (outlines or {}).items():
            try:
                key = str(int(k))
            except Exception:
                key = str(k)
            if isinstance(v, dict):
                pts = v.get("points") or []
                serial_pts = []
                for p in pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        serial_pts.append([float(p[0]), float(p[1])])
                    else:
                        serial_pts.append(p)
                out[key] = {
                    "points": serial_pts,
                    "width": int(v.get("width", 3) or 3),
                }
            else:
                out[key] = v
        return out

    def _serialize_paint_group_data(self, data):
        """Deep-copy paint_group_data into plain JSON types."""
        out = {}
        for gtag, recs in (data or {}).items():
            rows = []
            for rec in recs or []:
                if not isinstance(rec, dict):
                    continue
                row = {}
                mp = rec.get("model_points")
                if mp is not None:
                    row["model_points"] = [float(x) for x in mp]
                coords = rec.get("coords")
                if coords is not None:
                    row["coords"] = [float(x) for x in coords]
                if "width" in rec:
                    try:
                        row["width"] = int(rec["width"])
                    except Exception:
                        row["width"] = 3
                if "space" in rec:
                    row["space"] = str(rec["space"])
                rows.append(row)
            out[str(gtag)] = rows
        return out

    def _serialize_allen_zone_meta(self, meta_by_page):
        out = {}
        for page, meta in (meta_by_page or {}).items():
            page_out = {}
            for zid, m in (meta or {}).items():
                try:
                    key = str(int(zid))
                except Exception:
                    key = str(zid)
                if isinstance(m, dict):
                    page_out[key] = {
                        str(kk): (vv if isinstance(vv, (str, int, float, bool, type(None))) else str(vv))
                        for kk, vv in m.items()
                    }
                else:
                    page_out[key] = m
            out[str(int(page) if str(page).isdigit() else page)] = page_out
        return out

    def _png_bytes(self, pil_img, mode=None):
        img = pil_img
        if mode and img.mode != mode:
            img = img.convert(mode)
        bio = BytesIO()
        # compress_level kept default; optimize off for speed on large masks
        img.save(bio, format="PNG")
        return bio.getvalue()

    def _catlas_read_png(self, zf, names, member, mode=None):
        """Read a PNG member from a .catlas/.atlas zip; force full decode."""
        if member not in names:
            return None
        img = Image.open(BytesIO(zf.read(member)))
        img.load()  # force decode before zip closes / buffer dies
        if mode:
            img = img.convert(mode)
        else:
            img = img.copy()
        return img

    def _scale_catlas_layers_to_background(
        self,
        *,
        zones,
        base_atlas,
        borders_pure,
        page_overlay,
        paint_strokes,
        img_x,
        img_y,
        saved_bg,
        cur_bg_size,
        atlas_filetype,
        painted_outlines=None,
        paint_group_data=None,
    ):
        """Scale atlas + paint + placement to match the current TIFF size.

        Origin of the previous right-shift bug
        --------------------------------------
        Placement uses model-space ``img_x`` / ``img_y`` (native atlas/TIFF pixels).
        When the in-memory TIFF size changed between save and load (viewer fit scale
        depends on window size), we scaled only ``img_x`` and the paint layer when
        the atlas was *not* the same size as the background (typical after Crop).
        Offsets moved but the atlas rasters stayed at the old resolution → a small
        horizontal/vertical drift (often read as a right shift).

        Fix: whenever the background size changes, scale *every* atlas-model layer
        (mask, base, borders, overlay, stroke geometry) by the same sx/sy as the
        background, together with img_x/img_y and paint.
        """
        if (
            not cur_bg_size
            or not saved_bg
            or len(saved_bg) != 2
            or len(cur_bg_size) != 2
        ):
            return (
                zones,
                base_atlas,
                borders_pure,
                page_overlay,
                paint_strokes,
                img_x,
                img_y,
                painted_outlines,
                paint_group_data,
                False,
                1.0,
                1.0,
            )

        sw, sh = float(saved_bg[0]), float(saved_bg[1])
        tw, th = float(cur_bg_size[0]), float(cur_bg_size[1])
        if sw < 1 or sh < 1:
            return (
                zones,
                base_atlas,
                borders_pure,
                page_overlay,
                paint_strokes,
                img_x,
                img_y,
                painted_outlines,
                paint_group_data,
                False,
                1.0,
                1.0,
            )

        # Treat near-equal sizes as a match (avoid floating noise / 1px jitter)
        if abs(sw - tw) < 1.5 and abs(sh - th) < 1.5:
            return (
                zones,
                base_atlas,
                borders_pure,
                page_overlay,
                paint_strokes,
                img_x,
                img_y,
                painted_outlines,
                paint_group_data,
                False,
                1.0,
                1.0,
            )

        sx = tw / sw
        sy = th / sh
        # Prefer a single uniform scale when aspect is preserved (viewer fit is uniform)
        if abs(sx - sy) < 1e-4:
            s = sx
            sx = sy = s

        is_allen = atlas_filetype == "allen"
        rgba_resample = Image.NEAREST if is_allen else Image.BILINEAR

        def _scale_rgba(im):
            if im is None:
                return None
            nw = max(1, int(round(im.width * sx)))
            nh = max(1, int(round(im.height * sy)))
            if (nw, nh) == im.size:
                return im
            return im.resize((nw, nh), rgba_resample)

        def _scale_mask(im):
            if im is None:
                return None
            nw = max(1, int(round(im.width * sx)))
            nh = max(1, int(round(im.height * sy)))
            if (nw, nh) == im.size:
                return im
            return im.resize((nw, nh), Image.NEAREST)

        zones = _scale_mask(zones)
        base_atlas = _scale_rgba(base_atlas)
        borders_pure = _scale_rgba(borders_pure)
        page_overlay = _scale_rgba(page_overlay)

        if paint_strokes is not None:
            # Paint is background-native; target exact current bg size
            target = (max(1, int(round(tw))), max(1, int(round(th))))
            if paint_strokes.size != target:
                paint_strokes = paint_strokes.resize(target, Image.NEAREST)

        img_x = float(img_x) * sx
        img_y = float(img_y) * sy

        # Scale painted outline points (atlas model space)
        if painted_outlines:
            scaled_out = {}
            for zid, rec in painted_outlines.items():
                if not isinstance(rec, dict):
                    scaled_out[zid] = rec
                    continue
                pts = []
                for p in rec.get("points") or []:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        pts.append((float(p[0]) * sx, float(p[1]) * sy))
                scaled_out[zid] = {
                    "points": pts,
                    "width": max(1, int(round(int(rec.get("width", 3) or 3) * max(sx, sy)))),
                }
            painted_outlines = scaled_out

        # Scale durable paint group model points
        if paint_group_data:
            scaled_pg = {}
            for gtag, recs in paint_group_data.items():
                new_recs = []
                for rec in recs or []:
                    if not isinstance(rec, dict):
                        continue
                    row = dict(rec)
                    for key in ("model_points", "coords"):
                        if key in row and row[key] is not None:
                            vals = list(row[key])
                            scaled_vals = []
                            for i, v in enumerate(vals):
                                # even index = x, odd = y
                                scaled_vals.append(float(v) * (sx if i % 2 == 0 else sy))
                            row[key] = scaled_vals
                    if "width" in row:
                        try:
                            row["width"] = max(
                                1, int(round(int(row["width"]) * max(sx, sy)))
                            )
                        except Exception:
                            pass
                    new_recs.append(row)
                scaled_pg[gtag] = new_recs
            paint_group_data = scaled_pg

        logger.info(
            f".catlas scale-to-bg: bg {saved_bg} → {cur_bg_size} "
            f"sx={sx:.6f} sy={sy:.6f} offset→({img_x:.3f},{img_y:.3f})"
        )
        return (
            zones,
            base_atlas,
            borders_pure,
            page_overlay,
            paint_strokes,
            img_x,
            img_y,
            painted_outlines,
            paint_group_data,
            True,
            sx,
            sy,
        )

    def _write_atlas_file(self, save_path):
        """Write a lossless .catlas zip: zones, drawings, paint, placement, names.

        Package layout:
          manifest.json
          zones.png              zone ID mask (atlas model space, L)
          base_atlas.png         structure borders / base schematic (RGBA)
          borders_pure.png       Allen pure black borders (RGBA, optional)
          page_overlay.png       current page overlay (RGBA, optional)
          paint_strokes.png      paint_layer in background image space (RGBA, optional)
          nissl_ref.png          Allen Nissl reference strip (RGBA, optional)
        """
        page = self.current_page if self.current_page is not None else 0

        self._commit_live_paint_strokes()
        try:
            if getattr(self, "named_paint_groups", None) or getattr(self, "paint_group_data", None):
                for gtag in list(self.paint_group_data.keys()):
                    if gtag.startswith("paintgroup_") and gtag not in self.named_paint_groups:
                        self.named_paint_groups[gtag] = self.named_paint_groups.get(gtag)
                if self.named_paint_groups:
                    self._convert_named_paints_to_zones()
        except Exception as e:
            logger.debug(f"catlas save: paint→zone finalize skipped: {e}")

        bg_size = None
        if self.original_background is not None:
            bg_size = [int(self.original_background.size[0]), int(self.original_background.size[1])]
        elif self.background_image is not None:
            bg_size = [int(self.background_image.size[0]), int(self.background_image.size[1])]

        atlas_size = None
        if page in self.base_page_images and self.base_page_images[page] is not None:
            atlas_size = [
                int(self.base_page_images[page].size[0]),
                int(self.base_page_images[page].size[1]),
            ]
        elif page in self.mask_images and self.mask_images[page] is not None:
            atlas_size = [
                int(self.mask_images[page].size[0]),
                int(self.mask_images[page].size[1]),
            ]

        zone_names = self.zone_names.get(page, {}) or {}
        zone_counter = int(self.zone_counters.get(page, 0) or 0)
        try:
            if zone_names:
                zone_counter = max(zone_counter, max(int(k) for k in zone_names.keys()))
        except Exception:
            pass
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                zone_counter = max(zone_counter, int(np.array(self.mask_images[page]).max()))
            except Exception:
                pass

        # Store placement in model pixels (same units as atlas rasters / TIFF).
        # Round tiny float noise so reloads don't introduce sub-pixel drift.
        raw_x = float(getattr(self, "img_x", 0) or 0)
        raw_y = float(getattr(self, "img_y", 0) or 0)
        if abs(raw_x - round(raw_x)) < 1e-3:
            raw_x = float(round(raw_x))
        if abs(raw_y - round(raw_y)) < 1e-3:
            raw_y = float(round(raw_y))

        manifest = {
            "format_version": 2,
            "type": "barcc_catlas",
            "created": datetime.now().isoformat(timespec="seconds"),
            "atlas_filetype": getattr(self, "atlas_filetype", None),
            "page": int(page),
            "img_x": raw_x,
            "img_y": raw_y,
            "placement_units": "model_pixels",
            "source_background_size": bg_size,
            "atlas_size": atlas_size,
            "zone_names": self._serialize_zone_names(zone_names),
            "zone_counter": zone_counter,
            "painted_zone_outlines": self._serialize_painted_outlines(
                getattr(self, "painted_zone_outlines", {}) or {}
            ),
            "paint_group_data": self._serialize_paint_group_data(
                getattr(self, "paint_group_data", {}) or {}
            ),
            "named_paint_groups": {
                str(k): (None if v is None else str(v))
                for k, v in (getattr(self, "named_paint_groups", {}) or {}).items()
            },
            "allen_zone_meta": self._serialize_allen_zone_meta(
                getattr(self, "allen_zone_meta", {}) or {}
            ),
            "atlas_source_path": getattr(self, "path", None)
            if isinstance(getattr(self, "path", None), str)
            else None,
            "source_tiff_name": getattr(self, "tiff_filename", None),
            "source_tiff_path": getattr(self, "current_tiff_path", None),
            "description": (
                "BARCC cropped atlas schematic (.catlas): structure drawings, "
                "painted regions, zone mask, and Atlas Manager names. Apply onto "
                "other channels of the same section without re-labeling."
            ),
        }

        with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            if page in self.mask_images and self.mask_images[page] is not None:
                m = self.mask_images[page]
                if m.mode != "L":
                    m = m.convert("L")
                try:
                    m = Image.fromarray(np.array(m).astype(np.uint8), mode="L")
                except Exception:
                    pass
                zf.writestr("zones.png", self._png_bytes(m, "L"))

            if page in self.base_page_images and self.base_page_images[page] is not None:
                base = self.base_page_images[page]
                if base.mode != "RGBA":
                    base = base.convert("RGBA")
                zf.writestr("base_atlas.png", self._png_bytes(base, "RGBA"))

            pure = getattr(self, "allen_borders_pure", None)
            if pure is not None:
                if pure.mode != "RGBA":
                    pure = pure.convert("RGBA")
                zf.writestr("borders_pure.png", self._png_bytes(pure, "RGBA"))

            if page in self.page_images and self.page_images[page] is not None:
                ov = self.page_images[page]
                if ov.mode != "RGBA":
                    ov = ov.convert("RGBA")
                zf.writestr("page_overlay.png", self._png_bytes(ov, "RGBA"))

            if getattr(self, "paint_layer", None) is not None:
                pl = self.paint_layer
                try:
                    arr = np.array(pl)
                    has_paint = arr.ndim == 3 and arr.shape[2] >= 4 and bool(arr[:, :, 3].any())
                except Exception:
                    has_paint = True
                if has_paint:
                    if pl.mode != "RGBA":
                        pl = pl.convert("RGBA")
                    zf.writestr("paint_strokes.png", self._png_bytes(pl, "RGBA"))

            nissl = getattr(self, "allen_nissl_reference", None)
            if nissl is not None:
                if nissl.mode != "RGBA":
                    nissl = nissl.convert("RGBA")
                zf.writestr("nissl_ref.png", self._png_bytes(nissl, "RGBA"))

        return manifest

    def _get_unique_atlas_path(self, directory, base_name):
        """Return a unique path like 'image.catlas', 'image (2).catlas', etc."""
        candidate = os.path.join(directory, f"{base_name}.catlas")
        if not os.path.exists(candidate):
            return candidate
        counter = 2
        while True:
            candidate = os.path.join(directory, f"{base_name} ({counter}).catlas")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def save_atlas_schematic(self):
        """Save the full labeled atlas + paint schematic as a lossless .catlas file.

        Includes: zone mask, all Atlas Manager structure names, remaining atlas
        region drawings (borders), painted regions/strokes, and placement
        (img_x/img_y). Intended workflow: label on DAPI/counterstain, save, then
        Load Atlas Schematic onto other channels of the same section.
        """
        if not self._atlas_schematic_has_content():
            messagebox.showwarning(
                "Nothing to Save",
                "No atlas drawings, labeled regions, or paint to save.\n\n"
                "Load an atlas and/or paint & name regions first.",
            )
            return

        base_name = self.tiff_filename or "atlas_schematic"
        stem = base_name
        for suffix in ("_ch0", "_ch1", "_ch2", "_ch3", "_c0", "_c1", "_c2", "_c3",
                       "-ch0", "-ch1", "-ch2", "-ch3"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        default_name = f"{stem}_atlas"

        initial_dir = None
        base_dir = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            base_dir = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            base_dir = self.current_tiff_directory
        if base_dir:
            out = self._get_output_directory(base_dir, feature="atlas")
            initial_dir = out if out else base_dir

        save_path = fd.asksaveasfilename(
            title="Save Cropped Atlas (.catlas)",
            defaultextension=".catlas",
            filetypes=[
                ("BARCC Cropped Atlas", "*.catlas"),
                ("Legacy BARCC Atlas", "*.atlas"),
                ("All files", "*.*"),
            ],
            initialdir=initial_dir,
            initialfile=f"{default_name}.catlas",
        )
        if not save_path:
            return
        low = save_path.lower()
        if not (low.endswith(".catlas") or low.endswith(".atlas")):
            save_path = save_path + ".catlas"

        try:
            manifest = self._write_atlas_file(save_path)
            n_zones = len(manifest.get("zone_names") or {})
            logger.info(f"Saved .catlas schematic: {save_path} ({n_zones} named zones)")
            messagebox.showinfo(
                "Cropped Atlas Saved",
                f"Saved cropped atlas schematic (.catlas):\n{save_path}\n\n"
                f"Named regions: {n_zones}\n"
                f"Placement: offset ({manifest.get('img_x', 0):.1f}, {manifest.get('img_y', 0):.1f})\n"
                f"Atlas size: {manifest.get('atlas_size')}\n"
                f"Background size: {manifest.get('source_background_size')}\n\n"
                "Load via Atlas → Load Atlas Schematic… onto other channels.",
            )
            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.refresh_tiff_file_list()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to save .catlas: {e}", exc_info=True)
            messagebox.showerror("Save Error", f"Failed to save cropped atlas:\n{e}")

    def load_atlas_schematic(self):
        """Load a .catlas (or legacy .atlas) schematic onto the current image.

        Preserves the currently loaded TIFF background so you can apply a
        DAPI-labeled schematic to other fluorescence channels.
        """
        initial_dir = self._preferred_open_dir(feature="atlas")

        path = fd.askopenfilename(
            title="Load Cropped Atlas (.catlas)",
            initialdir=initial_dir,
            filetypes=[
                ("BARCC Cropped Atlas", "*.catlas"),
                ("Legacy BARCC Atlas", "*.atlas"),
                ("BARCC Paint + Regions", "*.barccpaint"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        if path.lower().endswith(".barccpaint"):
            self._load_barccpaint_bundle(path)
            return

        try:
            self._load_atlas_file(path)
        except Exception as e:
            logger.error(f"Failed to load .catlas: {e}", exc_info=True)
            messagebox.showerror("Load Error", f"Failed to load cropped atlas:\n{e}")

    def _load_atlas_file(self, path):
        """Restore a .catlas / legacy .atlas package (keeps current TIFF if present)."""
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                raise ValueError("Invalid .catlas/.atlas file: missing manifest.json")

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            ftype = manifest.get("type")
            if ftype not in ("barcc_catlas", "barcc_atlas", "paint_with_regions", None):
                logger.warning(f".catlas type={ftype!r}; attempting restore")

            zones = self._catlas_read_png(zf, names, "zones.png", "L")
            base_atlas = self._catlas_read_png(zf, names, "base_atlas.png", "RGBA")
            borders_pure = self._catlas_read_png(zf, names, "borders_pure.png", "RGBA")
            page_overlay = self._catlas_read_png(zf, names, "page_overlay.png", "RGBA")
            paint_strokes = self._catlas_read_png(zf, names, "paint_strokes.png", "RGBA")
            nissl_ref = self._catlas_read_png(zf, names, "nissl_ref.png", "RGBA")

        page = int(manifest.get("page", 0) or 0)
        saved_bg = manifest.get("source_background_size")
        img_x = float(manifest.get("img_x", 0) or 0)
        img_y = float(manifest.get("img_y", 0) or 0)
        atlas_filetype = manifest.get("atlas_filetype")

        cur_bg = None
        if self.original_background is not None:
            cur_bg = self.original_background
        elif self.background_image is not None:
            cur_bg = self.background_image
        cur_bg_size = list(cur_bg.size) if cur_bg is not None else None

        # Deserialize outlines / paint groups before scale (may scale points)
        outlines_raw = manifest.get("painted_zone_outlines") or {}
        painted_outlines = {}
        for k, v in outlines_raw.items():
            try:
                zid = int(k)
            except Exception:
                continue
            if isinstance(v, dict):
                pts = []
                for p in v.get("points") or []:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        pts.append((float(p[0]), float(p[1])))
                painted_outlines[zid] = {
                    "points": pts,
                    "width": int(v.get("width", 3) or 3),
                }

        pgd_raw = manifest.get("paint_group_data") or {}
        paint_group_data = {str(gtag): list(recs or []) for gtag, recs in pgd_raw.items()}

        (
            zones,
            base_atlas,
            borders_pure,
            page_overlay,
            paint_strokes,
            img_x,
            img_y,
            painted_outlines,
            paint_group_data,
            did_scale,
            sx_bg,
            sy_bg,
        ) = self._scale_catlas_layers_to_background(
            zones=zones,
            base_atlas=base_atlas,
            borders_pure=borders_pure,
            page_overlay=page_overlay,
            paint_strokes=paint_strokes,
            img_x=img_x,
            img_y=img_y,
            saved_bg=saved_bg,
            cur_bg_size=cur_bg_size,
            atlas_filetype=atlas_filetype,
            painted_outlines=painted_outlines,
            paint_group_data=paint_group_data,
        )

        self.save_state()
        clear_preprocess_cache()

        # Fresh view scale so placement math matches model pixels * 1.0
        self.view_scale = 1.0

        self.current_page = page
        if atlas_filetype:
            self.atlas_filetype = atlas_filetype
        elif base_atlas is not None or borders_pure is not None:
            self.atlas_filetype = "allen" if borders_pure is not None else "pdf"
        elif zones is not None:
            if not self.atlas_filetype:
                self.atlas_filetype = "img"

        if base_atlas is not None:
            self.base_page_images[page] = base_atlas
            self.page_images[page] = (
                page_overlay if page_overlay is not None else base_atlas.copy()
            )
            self.img = self.base_page_images[page].copy()
        elif page_overlay is not None:
            self.base_page_images[page] = page_overlay.copy()
            self.page_images[page] = page_overlay
            self.img = page_overlay.copy()
        elif zones is not None and self.atlas_filetype in ("img", None):
            tw, th = zones.size
            empty = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
            self.base_page_images[page] = empty
            self.page_images[page] = empty.copy()

        if borders_pure is not None:
            self.allen_borders_pure = borders_pure
        elif atlas_filetype == "allen" and base_atlas is not None:
            self.allen_borders_pure = base_atlas.copy()

        if nissl_ref is not None:
            self.allen_nissl_reference = nissl_ref

        if zones is not None:
            try:
                zarr = np.array(zones).astype(np.uint8)
                zones = Image.fromarray(zarr, mode="L")
            except Exception:
                if zones.mode != "L":
                    zones = zones.convert("L")
            self.mask_images[page] = zones

        names = manifest.get("zone_names") or {}
        if names:
            names = {int(k): v for k, v in names.items()}
            self.zone_names[page] = names
        else:
            self.zone_names.setdefault(page, {})

        zc = int(manifest.get("zone_counter", 0) or 0)
        if self.zone_names.get(page):
            try:
                zc = max(zc, max(int(k) for k in self.zone_names[page].keys()))
            except Exception:
                pass
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                zc = max(zc, int(np.array(self.mask_images[page]).max()))
            except Exception:
                pass
        self.zone_counters[page] = zc

        self.painted_zone_outlines = painted_outlines or {}
        self.paint_group_data = paint_group_data or {}

        npg = manifest.get("named_paint_groups") or {}
        self.named_paint_groups = {}
        for gtag, nm in npg.items():
            self.named_paint_groups[str(gtag)] = nm

        meta = manifest.get("allen_zone_meta") or {}
        if meta:
            restored_meta = {}
            for pkey, pmeta in meta.items():
                try:
                    p_int = int(pkey)
                except Exception:
                    p_int = pkey
                inner = {}
                for zid, m in (pmeta or {}).items():
                    try:
                        inner[int(zid)] = m
                    except Exception:
                        inner[zid] = m
                restored_meta[p_int] = inner
            self.allen_zone_meta = restored_meta

        if paint_strokes is not None:
            self.paint_layer = paint_strokes
        elif cur_bg is not None:
            self.paint_layer = Image.new("RGBA", cur_bg.size, (0, 0, 0, 0))
        else:
            self.paint_layer = None

        # Placement in model pixels (display = img_* * view_scale)
        self.img_x = float(img_x)
        self.img_y = float(img_y)

        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        try:
            self._clear_edge_highlight()
        except Exception:
            pass
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        if hasattr(self, "region_move_mode"):
            self.region_move_mode.set(False)

        try:
            if page in self.base_page_images:
                self._rebuild_page_overlays(page)
        except Exception as e:
            logger.debug(f"rebuild overlays after .catlas load: {e}")

        self.show_page()
        if hasattr(self, "_update_ribbon_selection"):
            self._update_ribbon_selection()

        n_zones = len(self.zone_names.get(page, {}) or {})
        bg_note = (
            f"Applied onto current image {tuple(cur_bg_size)}"
            if cur_bg_size
            else "No TIFF loaded — schematic only (import a TIFF to count)"
        )
        size_note = ""
        if did_scale:
            size_note = (
                f"\nRescaled with background {tuple(saved_bg)} → {tuple(cur_bg_size)} "
                f"(sx={sx_bg:.4f}, sy={sy_bg:.4f}) so placement stays registered."
            )
        messagebox.showinfo(
            "Cropped Atlas Loaded",
            f"Loaded cropped atlas from:\n{path}\n\n"
            f"Named regions (Atlas Manager): {n_zones}\n"
            f"Atlas type: {self.atlas_filetype or 'n/a'}\n"
            f"Placement: ({self.img_x:.1f}, {self.img_y:.1f})\n"
            f"{bg_note}{size_note}\n\n"
            "Use Count Cells to quantify on this channel with the same regions.",
        )
        logger.info(
            f"Loaded .catlas {path}: zones={n_zones} filetype={self.atlas_filetype} "
            f"offset=({self.img_x},{self.img_y}) bg={cur_bg_size} scaled={did_scale}"
        )

    def use_pen(self):
        # self.activate_button("Pen")
        self.output.bind('<B1-Motion>', self.paint)

    def use_eraser(self):
        # self.activate_button("Eraser", eraser_mode=True)
        self.output.bind('<B1-Motion>', self.erase)

    def activate_button(self, some_button, eraser_mode=False):
        self.active_button = some_button
        self.eraser_on = eraser_mode

    def paint(self, event):
        """Draw freehand using the pen.

        Model space is atlas-native when an atlas is loaded (so strokes register into
        the atlas zone mask for Count Cells), otherwise background-image space.
        """
        self.line_width = self.brush_size.get()
        paint_color = self.color

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_paint_model(cx, cy)

        # Start of a new continuous stroke?
        if self.old_x is None and self.old_y is None:
            self.save_state()  # Snapshot before this new stroke so Undo can remove it
            self._paint_group_counter += 1
            self.current_paint_group = f"paintgroup_{self._paint_group_counter}"
            self.old_x = ix
            self.old_y = iy
            return  # nothing to draw on first point

        prev_ix = self.old_x
        prev_iy = self.old_y

        prev_cx, prev_cy = self._paint_model_to_canvas(prev_ix, prev_iy)
        curr_cx, curr_cy = self._paint_model_to_canvas(ix, iy)

        tags = ('paint', self.current_paint_group)
        self.output.create_line(
            (prev_cx, prev_cy, curr_cx, curr_cy),
            width=self.line_width,
            fill=paint_color,
            capstyle=tk.ROUND,
            smooth=tk.TRUE,
            splinesteps=36,
            tags=tags
        )

        # Durable geometry in paint/zone model space (atlas or image)
        if self.current_paint_group:
            if self.current_paint_group not in self.paint_group_data:
                self.paint_group_data[self.current_paint_group] = []
            self.paint_group_data[self.current_paint_group].append({
                'model_points': [prev_ix, prev_iy, ix, iy],
                'width': self.line_width,
                'space': 'atlas' if self._paint_uses_atlas_space() else 'image',
            })

        self.old_x = ix
        self.old_y = iy

        self.output.config(scrollregion=self.output.bbox(tk.ALL))
    
    def erase(self, event):
        if len(self.output.find_withtag('paint')) == 0:
            return
        x = event.x
        y = event.y
        brush = self.brush_size.get()
        # find all paint within brush size of mouse
        for item in self.output.find_overlapping(x-brush, y-brush, x+brush, y+brush):
            # evaluate all tags the item has
            for tag in self.output.gettags(item):
                if tag != 'paint':
                    continue # use continue to ensure all tags are checked, paint doesnt need to be the first
                objectToBeDeleted = item
                self.output.delete(objectToBeDeleted)

    def reset_toggle(self, event):
        """Toggle pen stroke mode (drag vs segment) with the 's' key. No menu label."""
        if self.draw_type == 'drag':
            self.output.unbind('<ButtonRelease-1>')
            self.draw_type = 'segment'
        elif self.draw_type == 'segment':
            self.output.bind('<ButtonRelease-1>', self.reset)
            self.draw_type = 'drag'
            self.reset(event)
        else:
            print('error', file=sys.stderr)
        logger.debug(f"Pen mode: {self.draw_type}")

    def reset(self, event):
        self.old_x, self.old_y = None, None
        self.current_paint_group = None  # End the current continuous stroke group

        # Commit the just-finished stroke to the persistent paint_layer for zoom safety.
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()

        # Delete the temporary items now that they are committed.
        # This prevents them from being scaled on zoom (which caused duplication/displacement)
        # and from surviving show_page / scroll. Naming uses durable data + spatial lookup
        # as fallback (see name_painted_region).
        self.output.delete('paint')

        # Ensure scrollregion covers the committed paint strokes.
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

        # Redraw to make the newly committed stroke visible in the paint_layer image.
        # Without this, the stroke would only appear after the next show_page (e.g. Stop Paint or zoom).
        self.show_page()
        self._update_ribbon_selection()

    def name_painted_region(self, event):
        """Right-click on a paint stroke to name the entire connected boundary.

        All line segments belonging to the same continuous stroke (mouse-down to mouse-up)
        are treated as one structural region and colored yellow together.

        Fixed to use proper canvas coordinates so labeling works after zoom.
        """
        # Note: We intentionally do *not* call save_state here for paint naming.
        # The drawing stroke was already snapshotted at the start of the group.
        # This keeps "create painted region (draw + name)" undoable as a unit for the visual paint + banner entry.

        # Convert to canvas coordinates (critical after zoom + scrolling)
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)

        # Tolerance in screen pixels; keep it reasonable even after zoom
        tolerance = 12
        candidates = self.output.find_overlapping(cx - tolerance, cy - tolerance,
                                                  cx + tolerance, cy + tolerance)

        paint_items = [item for item in candidates if 'paint' in self.output.gettags(item)]

        has_canvas_items = len(paint_items) > 0
        group_tag = None
        clicked_item = None
        tags = []

        if has_canvas_items:
            clicked_item = paint_items[0]
            tags = self.output.gettags(clicked_item)

            # Find which group this segment belongs to
            for t in tags:
                if t.startswith('paintgroup_'):
                    group_tag = t
                    break

            if not group_tag:
                # Very old strokes without group tags - treat as singleton
                group_tag = 'paintgroup_legacy'
                self.output.addtag_withtag(group_tag, clicked_item)

            # Get ALL segments that belong to this connected stroke
            all_segments = self.output.find_withtag(group_tag)
            if not all_segments:
                return

            # Color the entire connected boundary yellow (selection for renaming)
            for item in all_segments:
                self.output.itemconfig(item, fill='#ffcc00')
        else:
            # Fallback for after zoom/scroll/show_page when temporary canvas items have been cleaned.
            # Use durable paint_group_data + spatial hit test in paint model space.
            ix, iy = self._canvas_to_paint_model(cx, cy)
            tolerance_model = tolerance / max(self.view_scale, 0.01)
            for gtag, data_list in list(self.paint_group_data.items()):
                if not gtag.startswith('paintgroup_'):
                    continue
                for rec in data_list or []:
                    mps = rec.get('model_points', [])
                    for j in range(0, len(mps), 2):
                        mx = mps[j]
                        my = mps[j+1]
                        if abs(mx - ix) <= tolerance_model and abs(my - iy) <= tolerance_model:
                            group_tag = gtag
                            break
                    if group_tag:
                        break
                if group_tag:
                    break

            if not group_tag:
                return

            # No canvas items to color yellow or find segments from.
            # We'll still set the name and commit for zones/counting.
            all_segments = []  # no visual items to manipulate

        if not group_tag:
            return

        current_name = self.named_paint_groups.get(group_tag, "")
        prompt = "Enter a name for this painted region:"
        if current_name:
            prompt = f"Rename painted region (current: {current_name}):"

        name = simpledialog.askstring("Painted Region Name", prompt, initialvalue=current_name)
        if name is None:
            return

        name = name.strip()
        if not name:
            if group_tag in self.named_paint_groups:
                del self.named_paint_groups[group_tag]
            if has_canvas_items:
                for item in all_segments:
                    self.output.itemconfig(item, fill=self.DEFAULT_COLOR)
            return

        self.named_paint_groups[group_tag] = name

        # Immediately commit this named group to the zone mask / zone_names.
        # This guarantees that "naming the zones immediately after drawing" makes them
        # defined for Count Cells even if the user never clicks Stop Paint and even if
        # later show_page() calls delete the transient canvas vectors.
        self._convert_named_paints_to_zones()

        # Extra defensive untag and yellow only if we have canvas items.
        # Only dtag the group_tag if convert retired it (success); if still present in named,
        # the collection inside convert failed to find strokes -- leave the tag so Stop/Count
        # force paths or later converts can still discover the items via find_withtag.
        if has_canvas_items:
            if group_tag not in self.named_paint_groups:
                for item in all_segments:
                    try:
                        self.output.dtag(item, group_tag)
                    except Exception:
                        pass

            # Keep the whole group yellow to show it's a named structural boundary
            for item in all_segments:
                self.output.itemconfig(item, fill='#ffcc00')

        logger.info(f"Named paint group {group_tag} as '{name}' ({len(all_segments)} segments)")

        # Immediately refresh the canvas (so new zone mask is visible) and the Atlas Manager ribbon list
        # so the newly named painted region appears in "Labeled Regions" without requiring another action.
        self.show_page()
        self._update_ribbon_selection()

    def _commit_canvas_paint_to_layer(self):
        """Rasterize current 'paint' tagged canvas items into the persistent self.paint_layer.
        This makes painting survive zoom, show_page calls, etc.
        """
        if self.paint_layer is None:
            return

        paint_items = self.output.find_withtag('paint')
        if not paint_items:
            return

        draw = ImageDraw.Draw(self.paint_layer)

        # Group items by their paintgroup tag to process each continuous stroke once
        # This avoids drawing ears/caps at every segment vertex and prevents over-drawing.
        groups = {}
        for line in paint_items:
            group_tag = None
            for t in self.output.gettags(line):
                if t.startswith('paintgroup_'):
                    group_tag = t
                    break
            if group_tag is None:
                # This line item no longer has a group_tag (it was dtag'ed after naming).
                # It is a finalized named stroke. Skip it for re-baking in this commit
                # (to avoid duplicating it from scaled coords on zoom).
                continue
            if group_tag not in groups:
                groups[group_tag] = []
            groups[group_tag].append(line)

        for group_tag, items in groups.items():
            # Collect full ordered points for the stroke, preferring durable model data
            points = []
            width = 3
            fill = self.DEFAULT_COLOR  # fallback

            if group_tag in self.paint_group_data and self.paint_group_data[group_tag]:
                for rec in self.paint_group_data[group_tag]:
                    mp = rec.get('model_points', [])
                    for j in range(0, len(mp), 2):
                        # paint_layer is always image-space (drawn at canvas 0,0)
                        ax, ay = int(mp[j]), int(mp[j + 1])
                        ix, iy = self._paint_model_to_image(ax, ay)
                        points.append((ix, iy))
                    if 'width' in rec:
                        width = rec['width']
            else:
                # Fallback: collect from current canvas items (in the order found, may not be perfect)
                for line in items:
                    coords = self.output.coords(line)
                    if not coords or len(coords) < 4:
                        continue
                    for i in range(0, len(coords), 2):
                        cx = coords[i]
                        cy = coords[i + 1]
                        # Canvas → image space for paint_layer
                        ix = int(cx / self.view_scale) if self.view_scale else int(cx)
                        iy = int(cy / self.view_scale) if self.view_scale else int(cy)
                        points.append((ix, iy))
                    w = self.output.itemcget(line, 'width')
                    try:
                        width = max(width, int(float(w)))
                    except Exception:
                        pass
                    fill = self.output.itemcget(line, 'fill')

            if len(points) < 2:
                continue

            # Dedup consecutive identical points
            deduped = [points[0]]
            for p in points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            points = deduped

            if len(points) < 2:
                continue

            radius = max(1, width // 2)
            # Round caps ONLY at the true start and end of the entire stroke
            if points:
                px, py = points[0]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
                px, py = points[-1]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
            draw.line(points, fill=fill, width=width, joint="curve")

    def _rebuild_paint_layer_from_data(self):
        """Force the persistent paint_layer to exactly match the groups currently present
        in self.paint_group_data (the durable source of truth for painted regions).

        This is called after undo restores an older paint_group_data (and possibly an
        older paint_layer snapshot) so that the *visible* baked strokes on the image
        are removed when the corresponding drawn/named region is undone.
        It re-rasterizes only the strokes that are still active in the restored history.

        Selected region boundaries (Atlas Manager selection) are drawn in yellow;
        all other region outlines stay black.
        """
        data = getattr(self, 'paint_group_data', None) or {}
        # Determine target size (prefer the original background so strokes stay registered to the image)
        size = None
        if getattr(self, 'original_background', None) is not None:
            size = self.original_background.size
        elif getattr(self, 'background_image', None) is not None:
            size = self.background_image.size
        elif getattr(self, 'paint_layer', None) is not None:
            size = self.paint_layer.size
        else:
            return

        fresh = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(fresh)
        default_color = getattr(self, 'DEFAULT_COLOR', 'black')
        selected_color = 'yellow'

        # Which zone (if any) is the Atlas Manager selection on this page
        page = getattr(self, 'current_page', None)
        selected_zid = None
        if (
            page is not None
            and getattr(self, 'selected_zone_id', None) is not None
            and getattr(self, 'selected_page', None) == page
        ):
            try:
                selected_zid = int(self.selected_zone_id)
            except Exception:
                selected_zid = None

        for group_tag, recs in list(data.items()):
            if not group_tag.startswith('paintgroup_') or not recs:
                continue
            points = []
            width = 3
            for rec in (recs or []):
                mp = rec.get('model_points') or rec.get('coords') or []
                if mp and len(mp) >= 2:
                    for j in range(0, len(mp), 2):
                        try:
                            ax, ay = int(mp[j]), int(mp[j + 1])
                            # paint_layer is image-space; convert from atlas model if needed
                            ix, iy = self._paint_model_to_image(ax, ay)
                            points.append((ix, iy))
                        except Exception:
                            pass
                w = rec.get('width')
                if w:
                    try:
                        width = max(width, int(w))
                    except Exception:
                        pass
            if len(points) < 2:
                continue
            # Dedup
            deduped = [points[0]]
            for p in points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            points = deduped
            if len(points) < 2:
                continue
            radius = max(1, width // 2)
            # Caps at true start/end
            if points:
                px, py = points[0]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=default_color)
                px, py = points[-1]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=default_color)
            draw.line(points, fill=default_color, width=width, joint="curve")

        # Also draw refittable boundaries for named painted zones (so edge/border deformation
        # updates the visible outline to match the new zone shape).
        # Selected zone → yellow boundary; others → black.
        drawn_selected_outline = False
        if page is not None:
            zone_names_page = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
            # Normalize name keys to int for membership tests
            try:
                zone_name_ids = {int(k) for k in zone_names_page.keys()}
            except Exception:
                zone_name_ids = set(zone_names_page.keys())

            for zid, outline in list(getattr(self, 'painted_zone_outlines', {}).items()):
                try:
                    zid_int = int(zid)
                except Exception:
                    zid_int = zid
                if zid_int not in zone_name_ids and zid not in zone_names_page:
                    continue
                points = outline.get('points', [])
                w = outline.get('width', 3)
                if len(points) < 2:
                    continue
                # Dedup
                deduped = [points[0]]
                for p in points[1:]:
                    if p != deduped[-1]:
                        deduped.append(p)
                points = deduped
                if len(points) < 2:
                    continue

                is_selected = selected_zid is not None and zid_int == selected_zid
                color = selected_color if is_selected else default_color
                line_w = int(w) + 1 if is_selected else int(w)
                line_w = max(2, line_w)
                if is_selected:
                    drawn_selected_outline = True

                radius = max(1, line_w // 2)
                if points:
                    px, py = points[0]
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
                    px, py = points[-1]
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
                draw.line(points, fill=color, width=line_w, joint="curve")

            # Atlas / mask-only regions may have no painted outline: draw mask contour in yellow when selected.
            # Skip for Allen — mask lives in atlas overlay space (img_x/y/scale/rotate), not paint-layer
            # image space; drawing here misregisters the yellow outline. Allen selection uses orange
            # fill + yellow border on the atlas layer in _rebuild_page_overlays instead.
            if (
                selected_zid is not None
                and not drawn_selected_outline
                and getattr(self, "atlas_filetype", None) != "allen"
            ):
                self._draw_zone_contour_on_layer(
                    draw, page, selected_zid, color=selected_color, width=3, size=size
                )

        self.paint_layer = fresh

        # Keep self.img in sync for 'img' filetype code paths (load_page_image etc.)
        if hasattr(self, 'img'):
            try:
                self.img = fresh.copy()
            except Exception:
                self.img = fresh

    def _draw_zone_contour_on_layer(self, draw, page, zid, color='yellow', width=3, size=None):
        """Draw the outer contour of mask zone zid onto a PIL Draw context (model coords)."""
        if page not in getattr(self, 'mask_images', {}) or self.mask_images.get(page) is None:
            return
        try:
            m = np.array(self.mask_images[page])
            if m.ndim > 2:
                m = m.squeeze()
            zid = int(zid)
            binr = (m == zid).astype(float)
            if not binr.any():
                return
            # If mask size differs from paint layer size, scale contour points
            mh, mw = binr.shape[:2]
            sx = sy = 1.0
            if size is not None and size[0] > 0 and size[1] > 0:
                sx = float(size[0]) / float(mw)
                sy = float(size[1]) / float(mh)
            contours = measure.find_contours(binr, 0.5)
            if not contours:
                return
            # Longest contour = outer boundary
            contour = max(contours, key=len)
            points = []
            for y, x in contour:
                points.append((int(round(x * sx)), int(round(y * sy))))
            if len(points) < 2:
                return
            # Close the loop for a continuous outline
            if points[0] != points[-1]:
                points.append(points[0])
            line_w = max(2, int(width))
            radius = max(1, line_w // 2)
            px, py = points[0]
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
            draw.line(points, fill=color, width=line_w, joint="curve")
        except Exception as e:
            logger.debug(f"Could not draw zone contour for zid={zid}: {e}")

    def _refresh_selection_boundary_visual(self):
        """Rebuild paint outlines so the selected region boundary is yellow, others black.

        Safe to call after select/deselect from Atlas Manager or canvas.
        """
        try:
            # Need a size for paint_layer even when no paint strokes exist yet
            if self.paint_layer is None:
                size = None
                if getattr(self, 'original_background', None) is not None:
                    size = self.original_background.size
                elif getattr(self, 'background_image', None) is not None:
                    size = self.background_image.size
                if size is not None:
                    self.paint_layer = Image.new('RGBA', size, (0, 0, 0, 0))
            self._rebuild_paint_layer_from_data()
        except Exception as e:
            logger.debug(f"Selection boundary visual refresh failed: {e}")

    def _convert_named_paints_to_zones(self):
        """Convert named paint *groups* (connected strokes) into zone entries.

        Each named group (one continuous drawing action) gets a single zone_id,
        so the entire structural boundary is treated as one region for cell counting.

        When an atlas is loaded, zones are merged into the existing atlas mask
        (atlas model coordinates) so painted regions appear alongside atlas regions
        in the Atlas Manager and Count Cells.
        """
        if not self.named_paint_groups:
            return

        if self.current_page is None:
            self.current_page = 0

        mask_img, draw = self._ensure_zone_mask_for_paint()
        page = self.current_page

        for group_tag, name in list(self.named_paint_groups.items()):
            # Collect strokes from durable data first (stable model coords preferred), else live canvas.
            strokes = []
            if group_tag in self.paint_group_data:
                for rec in (self.paint_group_data.get(group_tag) or []):
                    mp = rec.get('model_points') or []
                    w = rec.get('width', 3)
                    if mp and len(mp) >= 2:
                        strokes.append((mp, w, True))
                    else:
                        c = rec.get('coords') or []
                        if c and len(c) >= 2:
                            strokes.append((c, w, False))
            for item_id in (self.output.find_withtag(group_tag) or []):
                try:
                    coords = self.output.coords(item_id) or []
                    if coords and len(coords) >= 4:
                        w = self.output.itemcget(item_id, 'width')
                        try:
                            w = int(float(w))
                        except Exception:
                            w = 3
                        strokes.append((coords, w, False))
                except Exception:
                    pass
            if not strokes and group_tag in self.named_paint_groups:
                for item_id in (self.output.find_withtag('paint') or []):
                    try:
                        coords = self.output.coords(item_id) or []
                        if coords and len(coords) >= 4:
                            w = self.output.itemcget(item_id, 'width')
                            try:
                                w = int(float(w))
                            except Exception:
                                w = 3
                            strokes.append((coords, w, False))
                    except Exception:
                        pass
            if not strokes:
                logger.warning(f"Paint group {group_tag} had no strokes to convert")
                continue

            self.zone_counters[page] += 1
            zone_id = self.zone_counters[page]

            if name is None or not str(name).strip():
                clean_name = f"Painted Region {zone_id}"
            else:
                clean_name = str(name).strip() or f"Painted Region {zone_id}"

            self.zone_names[page][zone_id] = clean_name

            group_model_points = []
            group_width = 3
            for coords, width, is_model in strokes:
                try:
                    if not coords or len(coords) < 4:
                        continue
                    for i in range(0, len(coords), 2):
                        if is_model:
                            ix = int(coords[i])
                            iy = int(coords[i + 1])
                        else:
                            cx = coords[i]
                            cy = coords[i + 1]
                            ix, iy = self._canvas_to_paint_model(cx, cy)
                        group_model_points.append((ix, iy))
                    group_width = max(group_width, width)
                except Exception as e:
                    logger.error(f"Failed to rasterize segment in group {group_tag}: {e}")

            if len(group_model_points) >= 2:
                deduped = [group_model_points[0]]
                for p in group_model_points[1:]:
                    if p != deduped[-1]:
                        deduped.append(p)
                group_model_points = deduped

                if len(group_model_points) >= 2:
                    radius = max(1, group_width // 2)
                    if group_model_points:
                        px, py = group_model_points[0]
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                        px, py = group_model_points[-1]
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                    draw.line(group_model_points, fill=zone_id, width=group_width, joint="curve")

            if group_model_points:
                try:
                    minx = min(p[0] for p in group_model_points)
                    maxx = max(p[0] for p in group_model_points)
                    miny = min(p[1] for p in group_model_points)
                    maxy = max(p[1] for p in group_model_points)
                    cx_seed = (minx + maxx) // 2
                    cy_seed = (miny + maxy) // 2
                    for dx, dy in [(0, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (5, 0), (-5, 0), (0, 5), (0, -5)]:
                        sx = cx_seed + dx
                        sy = cy_seed + dy
                        if 0 <= sx < mask_img.width and 0 <= sy < mask_img.height:
                            if mask_img.getpixel((sx, sy)) == 0:
                                draw.floodfill((sx, sy), fill=zone_id, thresh=0)
                                break
                except Exception:
                    pass

            try:
                m = np.array(mask_img)
                zone_pixels = (m == zone_id)
                if zone_pixels.any():
                    filled = ndi.binary_fill_holes(zone_pixels)
                    # Never overwrite existing atlas / other painted zones
                    m[(filled) & (m == 0)] = zone_id
                    mask_img = Image.fromarray(m.astype(np.uint8), mode="L")
                    draw = ImageDraw.Draw(mask_img)
            except Exception as e:
                logger.debug(f"binary_fill_holes for zone {zone_id} skipped: {e}")

            n_pix = int(np.sum(np.array(mask_img) == zone_id))
            logger.info(
                f"Converted paint '{clean_name}' ({group_tag}) → zone {zone_id} "
                f"({n_pix} px, mask {mask_img.size}, atlas={self._paint_uses_atlas_space()})"
            )

            if zone_id not in self.painted_zone_outlines:
                self.painted_zone_outlines[zone_id] = {
                    'points': list(group_model_points),
                    'width': group_width
                }

            self.named_paint_groups.pop(group_tag, None)
            self.paint_group_data.pop(group_tag, None)
            for item_id in self.output.find_withtag(group_tag):
                try:
                    self.output.dtag(item_id, group_tag)
                except Exception:
                    pass

        self.mask_images[page] = mask_img

    def _force_paint_strokes_to_zones(self, paint_items):
        """
        Last-resort fallback: If the user has painted strokes on the canvas
        but they didn't get turned into zones (e.g. no right-click naming happened),
        convert whatever paint is still present into default "Painted Region" zones
        so that Count Cells produces a useful spreadsheet.
        """
        if not paint_items and not self.paint_group_data:
            return

        mask_img, draw = self._ensure_zone_mask_for_paint()
        page = self.current_page

        # Group remaining paint items by their group tag if present, otherwise treat all as one group
        groups = {}
        for item in paint_items or []:
            group_tag = None
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    group_tag = tag
                    break
            if group_tag is None:
                group_tag = 'unnamed_paint_group'
            if group_tag not in groups:
                groups[group_tag] = []
            groups[group_tag].append(item)

        for gtag in list(self.paint_group_data.keys()):
            if gtag not in groups:
                groups[gtag] = []

        for group_tag, items in groups.items():
            self.zone_counters[page] += 1
            zone_id = self.zone_counters[page]

            default_name = f"Painted Region {zone_id}"
            self.zone_names[page][zone_id] = default_name

            for item_id in items:
                try:
                    coords = self.output.coords(item_id)
                    if not coords or len(coords) < 4:
                        continue

                    width = self.output.itemcget(item_id, 'width')
                    try:
                        width = int(float(width))
                    except Exception:
                        width = 3

                    points = []
                    for i in range(0, len(coords), 2):
                        cx = coords[i]
                        cy = coords[i + 1]
                        ix, iy = self._canvas_to_paint_model(cx, cy)
                        points.append((ix, iy))

                    if len(points) < 2:
                        continue

                    radius = max(1, width // 2)
                    for px, py in points:
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                    draw.line(points, fill=zone_id, width=width, joint="curve")

                except Exception as e:
                    logger.error(f"Failed to force-convert paint item to zone: {e}")

            # If this group had no live canvas items (wiped), draw from durable recorded data (prefer model points)
            durable_points_for_flood = []
            if group_tag in self.paint_group_data:
                for rec in self.paint_group_data.get(group_tag, []):
                    try:
                        mp = rec.get('model_points')
                        width = rec.get('width', 3)
                        coords = mp if (mp and len(mp) >= 4) else rec.get('coords', [])
                        is_model = bool(mp and len(mp) >= 4)
                        if not coords or len(coords) < 4:
                            continue
                        points = []
                        for i in range(0, len(coords), 2):
                            if is_model:
                                ix = int(coords[i])
                                iy = int(coords[i + 1])
                            else:
                                cx = coords[i]
                                cy = coords[i + 1]
                                ix, iy = self._canvas_to_paint_model(cx, cy)
                            points.append((ix, iy))
                            durable_points_for_flood.append((ix, iy))
                        if len(points) < 2:
                            continue
                        radius = max(1, width // 2)
                        for px, py in points:
                            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                        draw.line(points, fill=zone_id, width=width, joint="curve")
                    except Exception as e:
                        logger.error(f"Failed to force-convert durable paint data for {group_tag}: {e}")

            # Fill interior for durable-only (unnamed) groups as well
            if durable_points_for_flood:
                try:
                    minx = min(p[0] for p in durable_points_for_flood)
                    maxx = max(p[0] for p in durable_points_for_flood)
                    miny = min(p[1] for p in durable_points_for_flood)
                    maxy = max(p[1] for p in durable_points_for_flood)
                    cx_seed = (minx + maxx) // 2
                    cy_seed = (miny + maxy) // 2
                    for dx, dy in [(0,0), (2,0), (-2,0), (0,2), (0,-2)]:
                        sx = cx_seed + dx
                        sy = cy_seed + dy
                        if 0 <= sx < mask_img.width and 0 <= sy < mask_img.height:
                            if mask_img.getpixel((sx, sy)) == 0:
                                draw.floodfill((sx, sy), fill=zone_id, thresh=0)
                                break
                except Exception:
                    pass

            # Strong binary_fill_holes for force path (unnamed strokes auto-named at Count Cells time)
            try:
                m = np.array(mask_img)
                zone_pixels = (m == zone_id)
                if zone_pixels.any():
                    filled = ndi.binary_fill_holes(zone_pixels)
                    m[(filled) & (m == 0)] = zone_id
                    mask_img = Image.fromarray(m.astype(np.uint8))
                    draw = ImageDraw.Draw(mask_img)
            except Exception as e:
                logger.debug(f"binary_fill_holes (force) for zone {zone_id} skipped: {e}")

            logger.info(f"Force-converted paint group '{group_tag}' → zone {zone_id} ('{default_name}')")

            # Retire after processing (prevents re-counting the same strokes as extra zones)
            self.named_paint_groups.pop(group_tag, None)
            self.paint_group_data.pop(group_tag, None)
            for item_id in self.output.find_withtag(group_tag):
                try:
                    self.output.dtag(item_id, group_tag)
                except Exception:
                    pass

        self.mask_images[self.current_page] = mask_img

    def show_brush_settings(self): # This is the layout to be applied to all other spawned windows
        brush_win = None
        window = brush_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Brush Settings")
        tk.Label(window, text="Brush Size: ").grid(row=2, column=0)
        choose_size_button = tk.Scale(window, from_=1, to=10, orient=tk.HORIZONTAL, variable=self.brush_size)
        choose_size_button.grid(row=2, column=1, padx=5, pady=5)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)

    def show_scale_settings(self):
        scale_win = None
        window = scale_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Scale Settings")
        # Scale controls
        scale_label = ttk.Label(window, text="Scale:")
        scale_label.grid(row=0, column=0, columnspan=2)
        self.scale_entry = ttk.Entry(window, width=10)
        self.scale_entry.grid(row=0, column=2, padx=5, pady=5)
        # Resize buttons
        ttk.Button(window, text="Resize", command=self.resize_custom).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(window, text="Resize X", command=self.resize_x).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(window, text="Resize Y", command=self.resize_y).grid(row=1, column=2, padx=5, pady=5)
        ttk.Button(
            window,
            text="Fit to image",
            command=lambda: (self.fit_atlas_to_image(), window.destroy()),
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=8)
        ttk.Label(
            window,
            text="Fit to image: resize atlas (or cropped atlas) to the loaded\n"
                 "TIFF size and align both top-left corners.",
            font=("Helvetica", 8),
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 6))
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def show_rotate_settings(self):
        rotate_win = None
        window = rotate_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Rotate Settings")
        rotation_label = ttk.Label(window, text="Rotate (degrees):")
        rotation_label.grid(row=0, column=0)
        self.rotation_entry = ttk.Entry(window, width=10)
        self.rotation_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(window, text="Rotate", command=self.rotate_custom).grid(row=0, column=2, padx=5, pady=5)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def show_brightness_settings(self):
        brightness_win = None
        window = brightness_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing; the Close button worked but X did not.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Brightness Settings")
        brightness_label = ttk.Label(window, text="Brightness:")
        brightness_label.grid(row=0, column=0)
        brightness_slider = ttk.Scale(
            window, from_=-100, to=400, orient=tk.HORIZONTAL, command=self.update_brightness
        )
        brightness_slider.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        brightness_slider.set(getattr(self, "brightness", 0.0) or 0.0)
        window.columnconfigure(1, weight=1)
        ttk.Label(
            window,
            text="Adjusts the loaded image only (not the atlas).",
            font=("Helvetica", 8),
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=5)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)

    def show_mask_settings(self, restore_geometry=None):
        mask_settings_win = None
        window = mask_settings_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button to close the dialog properly
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Mask Settings")

        if restore_geometry:
            window.geometry(restore_geometry)

        # Configure grid layout
        window.columnconfigure(0, weight=1)
        window.columnconfigure(1, weight=1)

        def save_settings():
            self.image_processor.save_config()

        def load_settings():
            geom = window.geometry()
            self.image_processor.load_config()
            window.destroy()  # Reopen to refresh values
            self.show_mask_settings(restore_geometry=geom)

        # --- Autotune helpers ---
        def _apply_autotune_and_refresh(adjust_func):
            geom = window.geometry()
            adjust_func()
            window.destroy()
            self.show_mask_settings(restore_geometry=geom)
            # Automatically refresh the mask visualization using the new autotuned settings
            self.show_cell_mask_threshold(calculate=True)

        def autotune_more_cells():
            cfg = self.image_processor.cell_config
            if cfg.detection_method == "blob":
                cfg.blob_threshold = max(0.01, round(cfg.blob_threshold - 0.025, 3))
                cfg.blob_min_sigma = max(1.0, round(cfg.blob_min_sigma - 0.4, 1))
                cfg.blob_min_area = max(5, cfg.blob_min_area - 5)
            else:
                cfg.min_cell_size = max(5, cfg.min_cell_size - 6)
                cfg.peak_min_intensity = max(0.01, round(cfg.peak_min_intensity - 0.06, 2))
                cfg.circularity_threshold = max(0.25, round(cfg.circularity_threshold - 0.06, 2))
                cfg.min_peak_distance = max(2, cfg.min_peak_distance - 1)
            _apply_autotune_and_refresh(lambda: None)

        def autotune_less_cells():
            cfg = self.image_processor.cell_config
            if cfg.detection_method == "blob":
                cfg.blob_threshold = min(0.9, round(cfg.blob_threshold + 0.03, 3))
                cfg.blob_min_area += 8
            else:
                cfg.min_cell_size += 6
                cfg.peak_min_intensity = min(0.95, round(cfg.peak_min_intensity + 0.06, 2))
                cfg.circularity_threshold = min(0.95, round(cfg.circularity_threshold + 0.06, 2))
                cfg.min_peak_distance += 1
            _apply_autotune_and_refresh(lambda: None)

        def autotune_bigger_cells():
            cfg = self.image_processor.cell_config
            cfg.min_cell_size += 8
            cfg.max_cell_size += 25
            cfg.circularity_threshold = min(0.92, round(cfg.circularity_threshold + 0.04, 2))
            cfg.watershed_compactness = min(0.8, round(cfg.watershed_compactness + 0.15, 2))
            _apply_autotune_and_refresh(lambda: None)

        def autotune_smaller_cells():
            cfg = self.image_processor.cell_config
            cfg.min_cell_size = max(5, cfg.min_cell_size - 8)
            cfg.max_cell_size = max(20, cfg.max_cell_size - 20)
            cfg.circularity_threshold = max(0.3, round(cfg.circularity_threshold - 0.04, 2))
            _apply_autotune_and_refresh(lambda: None)

        def autotune_brighter_cells():
            cfg = self.image_processor.cell_config
            cfg.peak_min_intensity = min(0.95, round(cfg.peak_min_intensity + 0.10, 2))
            cfg.circularity_threshold = min(0.9, round(cfg.circularity_threshold + 0.03, 2))
            _apply_autotune_and_refresh(lambda: None)

        def autotune_dimmer_cells():
            cfg = self.image_processor.cell_config
            if cfg.detection_method == "blob":
                cfg.blob_threshold = max(0.005, round(cfg.blob_threshold - 0.04, 3))
                cfg.blob_min_sigma = max(1.0, round(cfg.blob_min_sigma - 0.5, 1))
                cfg.blob_min_area = max(5, cfg.blob_min_area - 4)
            else:
                cfg.peak_min_intensity = max(0.01, round(cfg.peak_min_intensity - 0.10, 2))
                cfg.min_cell_size = max(5, cfg.min_cell_size - 3)
            _apply_autotune_and_refresh(lambda: None)


        def generate_setting(frame, attr, value, row, config):
                ttk.Label(frame, text=f"{attr.replace('_', ' ').title()}:").grid(row=row, column=0, sticky='ew', padx=5, pady=2)
                
                entry = ttk.Entry(frame)
                entry.insert(0, str(value))
                entry.grid(row=row, column=1, sticky='ew', padx=5, pady=2)
                
                setter = create_setter(entry, config, attr)
                entry.bind("<FocusOut>", setter)
                entry.bind("<Return>", setter)

        def generate_option_frames():
            # Preprocess image
            # keyword:grid_alignment
            self.bg_tophat_frame = ttk.LabelFrame(bg_frame, text='Tophat')
            self.bg_gaussian_frame = ttk.LabelFrame(bg_frame, text='Background Gaussian')
            self.nr_gaussian_frame = ttk.LabelFrame(nr_frame, text='Noise Reduction Gaussian')
            self.nr_median_frame = ttk.LabelFrame(nr_frame, text='Median')
            self.nr_bilateral_frame = ttk.LabelFrame(nr_frame, text='Bilateral')
            self.ce_stretch_frame = ttk.LabelFrame(ce_frame, text='Stretch')
            self.ce_clahe_frame = ttk.LabelFrame(ce_frame, text='Clahe')
            self.ce_gamma_frame = ttk.LabelFrame(ce_frame, text='Gamma')
            self.se_unsharp_frame = ttk.LabelFrame(se_frame, text='Unsharp Mask')
            bg_tophat_options = ['disk_radius']
            bg_gaussian_options = ['bg_gaussian_sigma']
            nr_gaussian_options = ['nr_gaussian_sigma']
            nr_median_options = ['median_kernel']
            nr_bilateral_options = ['bilateral_sigma_color', 'bilateral_sigma_space']
            ce_stretch_options = [] # None
            ce_clahe_options = ['clahe_kernel', 'clahe_clip_limit']
            ce_gamma_options = ['gamma']
            se_unsharp_options = ['unsharp_radius', 'unsharp_amount']


            preprocess_options = [  bg_tophat_options,
                                    bg_gaussian_options,
                                    nr_gaussian_options,
                                    nr_median_options,
                                    nr_bilateral_options,
                                    ce_stretch_options,
                                    ce_clahe_options,
                                    ce_gamma_options,
                                    se_unsharp_options 
                                ]
            preprocess_frames = [   self.bg_tophat_frame,
                                    self.bg_gaussian_frame,
                                    self.nr_gaussian_frame,
                                    self.nr_median_frame,
                                    self.nr_bilateral_frame,
                                    self.ce_stretch_frame,
                                    self.ce_clahe_frame,
                                    self.ce_gamma_frame,
                                    self.se_unsharp_frame
                                ]


            row = 0
            for i in range(0, len(preprocess_options)):
                for attr in preprocess_options[i]:
                    frame = preprocess_frames[i]
                    config = self.image_processor.preprocess_config
                    value = getattr(config, attr)
                    generate_setting(frame, attr, value, row, config)
                    row += 1


            # Cell Detection
            self.tm_otsu_frame = ttk.LabelFrame(tm_frame, text='Otsu')
            self.tm_adaptive_frame = ttk.LabelFrame(tm_frame, text='Adaptive')
            self.tm_local_frame = ttk.LabelFrame(tm_frame, text='Local')
            self.tm_manual_frame = ttk.LabelFrame(tm_frame, text='Manual')
            self.other_circularity_frame = ttk.LabelFrame(option_frame, text='Circularity')
            self.other_watershed_frame = ttk.LabelFrame(option_frame, text='Watershed')
            self.blob_frame = ttk.LabelFrame(option_frame, text='Blob Detection (Recommended)')

            # Quick method switcher
            method_frame = ttk.Frame(option_frame)
            ttk.Label(method_frame, text="Detection Method:").pack(side='left', padx=5)
            self.detection_method_var = tk.StringVar(value=self.image_processor.cell_config.detection_method)
            ttk.Radiobutton(method_frame, text="Blob (new)", variable=self.detection_method_var, value="blob",
                            command=lambda: setattr(self.image_processor.cell_config, 'detection_method', 'blob')).pack(side='left')
            ttk.Radiobutton(method_frame, text="Watershed (old)", variable=self.detection_method_var, value="watershed",
                            command=lambda: setattr(self.image_processor.cell_config, 'detection_method', 'watershed')).pack(side='left')
            method_frame.grid(row=3, column=0, sticky='w', pady=8)

            tm_otsu_options = [] # None
            tm_adaptive_options = ['adaptive_block_size']
            tm_local_options = ['local_radius']
            tm_manual_options = ['manual_threshold']
            other_circularity_options = ['min_cell_size', 'max_cell_size', 'circularity_threshold']
            other_watershed_options = ['min_peak_distance', 'peak_min_intensity', 'watershed_compactness']
            blob_options = ['blob_min_sigma', 'blob_max_sigma', 'blob_num_sigma',
                            'blob_threshold', 'blob_overlap', 'blob_min_area',
                            'blob_max_area', 'blob_min_circularity']

            cell_detect_options = [ tm_otsu_options,
                                    tm_adaptive_options,
                                    tm_local_options,
                                    tm_manual_options,
                                    other_circularity_options,
                                    other_watershed_options,
                                    blob_options
                                  ]

            cell_detect_frames = [  self.tm_otsu_frame,
                                    self.tm_adaptive_frame,
                                    self.tm_local_frame,
                                    self.tm_manual_frame,
                                    self.other_circularity_frame,
                                    self.other_watershed_frame,
                                    self.blob_frame
                                 ]

            for i in range(0, len(cell_detect_options)):
                for attr in cell_detect_options[i]:
                    frame = cell_detect_frames[i]
                    config = self.image_processor.cell_config
                    value = getattr(config, attr)
                    generate_setting(frame, attr, value, row, config)
                    row += 1

            # Static: do not change with radiobutton, so they can be shown now
            self.other_circularity_frame.grid(row=0, column=0, sticky='news')
            self.other_watershed_frame.grid(row=1, column=0, sticky='news')
            self.blob_frame.grid(row=2, column=0, sticky='news')

        def create_setter(entry_widget, config_obj, attr_name):
            def setter(*args):
                val = entry_widget.get()
                try:
                    current_type = type(getattr(config_obj, attr_name))
                    if current_type == int:
                        val = int(val)
                    elif current_type == float:
                        val = float(val)
                    elif current_type == str:
                        val = str(val)
                    setattr(config_obj, attr_name, val)
                    logger.debug(f"Successfully set {attr_name} to {val}")
                except ValueError as e:
                    logger.error(f"Invalid input for {attr_name}: {e}")
                    messagebox.showerror("Invalid Input", 
                                       f"Please enter a valid {current_type.__name__} for {attr_name}.")
            return setter

        def hide_children(input_frame):
            for child in input_frame.winfo_children():
                child.grid_forget()

        def on_radio_button_change(*args):
            # keyword:grid_alignment
            preprocess_config = self.image_processor.preprocess_config
            hide_children(bg_frame) # Background Correction
            match self.bg_correction_type.get():
                case 'tophat':
                    self.bg_tophat_frame.grid(sticky='we')
                case 'gaussian':
                    self.bg_gaussian_frame.grid(sticky='ew')
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(nr_frame) # Noise Reduction
            match self.noise_reduction_type.get():
                case 'gaussian':
                    self.nr_gaussian_frame.grid(sticky='ew')
                case 'median':
                    self.nr_median_frame.grid(sticky='ew')
                case 'bilateral':
                    self.nr_bilateral_frame.grid(sticky='ew')
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(ce_frame) # Contrast Enhancement
            match self.contrast_enhance_type.get():
                case 'stretch':
                    self.ce_stretch_frame.grid(sticky='ew')
                case 'clahe':
                    self.ce_clahe_frame.grid(sticky='ew')
                case 'gamma':
                    self.ce_gamma_frame.grid(sticky='ew')
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(se_frame) # Signal Enhancement
            match self.signal_enhance_type.get():
                case 'unsharp mask':
                    self.se_unsharp_frame.grid(sticky='ew') 
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(tm_frame) # Thresholding Method
            match self.threshold_type.get():
                case 'otsu':
                    self.tm_otsu_frame.grid(sticky='ew') 
                case 'adaptive':
                    self.tm_adaptive_frame.grid(sticky='ew') 
                case 'local':
                    self.tm_local_frame.grid(sticky='ew') 
                case 'manual':
                    self.tm_manual_frame.grid(sticky='ew') 
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)

        # Control buttons at the top
        control_frame = ttk.Frame(window)
        control_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        ttk.Button(control_frame, text="Save", command=save_settings).grid(row=0, column=0, padx=5)
        ttk.Button(control_frame, text="Load", command=load_settings).grid(row=0, column=1, padx=5)
        ttk.Button(control_frame, text="Show Mask", command=self.show_cell_mask_threshold).grid(row=0, column=2, padx=5)

        # Autotune panel (second row in control_frame)
        ttk.Label(control_frame, text="Autotune:").grid(row=1, column=0, padx=(5, 8), pady=(6, 2), sticky='w')
        auto_btns = ttk.Frame(control_frame)
        auto_btns.grid(row=1, column=1, columnspan=3, pady=(6, 2), sticky='w')

        ttk.Button(auto_btns, text="More cells", width=12, command=autotune_more_cells).grid(row=0, column=0, padx=2, pady=1)
        ttk.Button(auto_btns, text="Less cells", width=12, command=autotune_less_cells).grid(row=0, column=1, padx=2, pady=1)
        ttk.Button(auto_btns, text="Bigger cells", width=12, command=autotune_bigger_cells).grid(row=0, column=2, padx=2, pady=1)
        ttk.Button(auto_btns, text="Smaller cells", width=12, command=autotune_smaller_cells).grid(row=1, column=0, padx=2, pady=1)
        ttk.Button(auto_btns, text="Brighter cells", width=12, command=autotune_brighter_cells).grid(row=1, column=1, padx=2, pady=1)
        ttk.Button(auto_btns, text="Dimmer cells", width=12, command=autotune_dimmer_cells).grid(row=1, column=2, padx=2, pady=1)

        # Smart Suggest + Measure Tune (informed blob tuning from user-picked samples)
        suggest_frame = ttk.Frame(control_frame)
        suggest_frame.grid(row=1, column=4, padx=(15, 5), pady=(6, 2), sticky='w')
        ttk.Button(
            suggest_frame,
            text="Smart Suggest (Pre-tuning smart settings)",
            command=self._show_smart_suggest_dialog,
        ).pack(anchor='w')
        ttk.Button(
            suggest_frame,
            text="Measure Tune",
            command=lambda: self.start_measure_tune(mask_settings_window=window),
        ).pack(anchor='w', pady=(4, 0))

        # Presets row
        ttk.Label(control_frame, text="Presets:").grid(row=2, column=0, padx=(5, 8), pady=(8, 2), sticky='w')
        preset_frame = ttk.Frame(control_frame)
        preset_frame.grid(row=2, column=1, columnspan=3, pady=(8, 2), sticky='w')

        self.preset_combo = ttk.Combobox(preset_frame, width=25, state="readonly")
        self.preset_combo.grid(row=0, column=0, padx=2)

        def refresh_preset_list():
            presets = self.load_presets()
            self.preset_combo['values'] = list(presets.keys())
            if presets:
                self.preset_combo.set(list(presets.keys())[0])

        def do_load_preset():
            name = self.preset_combo.get()
            if name and self.load_preset(name):
                window.destroy()
                self.show_mask_settings()

        def do_save_preset():
            self.save_current_as_preset()
            refresh_preset_list()

        def do_delete_preset():
            name = self.preset_combo.get()
            if name:
                self.delete_preset(name)
                refresh_preset_list()

        ttk.Button(preset_frame, text="Load", width=8, command=do_load_preset).grid(row=0, column=1, padx=2)
        ttk.Button(preset_frame, text="Save As", width=8, command=do_save_preset).grid(row=0, column=2, padx=2)
        ttk.Button(preset_frame, text="Delete", width=8, command=do_delete_preset).grid(row=0, column=3, padx=2)

        refresh_preset_list()

        # Export / Import config files (portable settings)
        export_import_frame = ttk.Frame(control_frame)
        export_import_frame.grid(row=3, column=0, columnspan=4, pady=(6, 2), sticky='w')

        ttk.Label(export_import_frame, text="Config Files:").grid(row=0, column=0, padx=(5, 8))
        ttk.Button(export_import_frame, text="Export...", width=10,
                   command=self.export_detection_settings).grid(row=0, column=1, padx=2)
        ttk.Button(export_import_frame, text="Import...", width=10,
                   command=lambda: [self.import_detection_settings(), window.destroy()]).grid(row=0, column=2, padx=2)

        # Create frame for radiobuttons and their options
        radio_frame = ttk.Frame(window)
        radio_frame.grid(row=1, column=0, sticky='nwes', padx=5, pady=5)
        # Create frame for rightmost options
        option_frame = ttk.Frame(window)
        option_frame.grid(row=1, column=1, sticky='nwes', padx=5, pady=5)

        # Create options frames aligned with radiobuttons, keyword:grid_alignment
        bg_frame = ttk.Frame(radio_frame)
        bg_frame.grid(row=0, column=1, sticky='news', padx=5, pady=0)
        nr_frame = ttk.Frame(radio_frame)
        nr_frame.grid(row=1, column=1, sticky='news', padx=5, pady=0)
        ce_frame = ttk.Frame(radio_frame)
        ce_frame.grid(row=2, column=1, sticky='news', padx=5, pady=0)
        se_frame = ttk.Frame(radio_frame)
        se_frame.grid(row=3, column=1, sticky='news', padx=5, pady=0)
        tm_frame = ttk.Frame(radio_frame)
        tm_frame.grid(row=4, column=1, sticky='news', padx=5, pady=0)

        # Initialize settings frames
        generate_option_frames()

        # Create radio buttons
            # Create variables
        self.bg_correction_type = tk.StringVar()
        self.noise_reduction_type = tk.StringVar()
        self.contrast_enhance_type = tk.StringVar()
        self.signal_enhance_type = tk.StringVar()
        self.threshold_type = tk.StringVar()

        # Background Correction
        bg_correction_frame = ttk.LabelFrame(radio_frame, text='Background Correction')
        bg_correction_frame.grid(row=0, column=0, sticky='new')
        bg_correction_types = {'Tophat'     : 0, 
                               'Gaussian'   : 1,
                               'None'       : 2
                               }
        self.bg_correction_type.set(self.image_processor.preprocess_config.background_method) # Sets default
        self.bg_correction_type.trace_add('write', on_radio_button_change)
        bg_setter = create_setter(self.bg_correction_type, self.image_processor.preprocess_config, 'background_method')
        self.bg_correction_type.trace_add('write', bg_setter)
        for (text, row) in bg_correction_types.items():
            button = tk.Radiobutton(bg_correction_frame, 
                                    text=text, 
                                    variable=self.bg_correction_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Noise Reduction
        noise_reduction_frame = ttk.LabelFrame(radio_frame, text='Noise Reduction')
        noise_reduction_frame.grid(row=1, column=0, sticky='news')
        noise_reduction_types = {'Gaussian' : 0, 
                                 'Median'   : 1,
                                 'Bilateral': 2,
                                 'None'     : 3
                                }
        self.noise_reduction_type.set(self.image_processor.preprocess_config.denoise_method) # Sets default
        self.noise_reduction_type.trace_add('write', on_radio_button_change)
        nr_setter = create_setter(self.noise_reduction_type, self.image_processor.preprocess_config, 'denoise_method')
        self.noise_reduction_type.trace_add('write', nr_setter)
        for (text, row) in noise_reduction_types.items():
            button = tk.Radiobutton(noise_reduction_frame, 
                                    text=text, 
                                    variable=self.noise_reduction_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Contrast Enhancement 
        contrast_enhance_frame = ttk.LabelFrame(radio_frame, text='Contrast Enhancement')
        contrast_enhance_frame.grid(row=2, column=0, sticky='news')
        contrast_enhance_types = {'Stretch' : 0, 
                                  'Clahe'   : 1,
                                  'Gamma'   : 2,
                                  'None'    : 3
                                }
        self.contrast_enhance_type.set(self.image_processor.preprocess_config.contrast_method) # Sets default
        self.contrast_enhance_type.trace_add('write', on_radio_button_change)
        ce_setter = create_setter(self.contrast_enhance_type, self.image_processor.preprocess_config, 'contrast_method')
        self.contrast_enhance_type.trace_add('write', ce_setter)
        for (text, row) in contrast_enhance_types.items():
            button = tk.Radiobutton(contrast_enhance_frame, 
                                    text=text, 
                                    variable=self.contrast_enhance_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Signal Enhancement 
        signal_enhance_frame = ttk.LabelFrame(radio_frame, text='Signal Enhancement')
        signal_enhance_frame.grid(row=3, column=0, sticky='news')
        signal_enhance_types = {'Unsharp Mask' : 0, 
                                'None'         : 1
                                }
        self.signal_enhance_type.set(self.image_processor.preprocess_config.enhance_method) # Sets default
        self.signal_enhance_type.trace_add('write', on_radio_button_change)
        se_setter = create_setter(self.signal_enhance_type, self.image_processor.preprocess_config, 'enhance_method')
        self.signal_enhance_type.trace_add('write', se_setter)
        for (text, row) in signal_enhance_types.items():
            button = tk.Radiobutton(signal_enhance_frame, 
                                    text=text, 
                                    variable=self.signal_enhance_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Threshold
        threshold_frame = ttk.LabelFrame(radio_frame, text='Threshold Method')
        threshold_frame.grid(row=4, column=0, sticky='news')
        threshold_types = {'Otsu'     : 0, 
                           'Adaptive'   : 1,
                           'Local'       : 2,
                           'Manual'       : 3
                           }
        self.threshold_type.set(self.image_processor.cell_config.threshold_method) # Sets default
        self.threshold_type.trace_add('write', on_radio_button_change)
        tm_setter = create_setter(self.threshold_type, self.image_processor.cell_config, 'threshold_method')
        self.threshold_type.trace_add('write', tm_setter)
        for (text, row) in threshold_types.items():
            button = tk.Radiobutton(threshold_frame, 
                                    text=text, 
                                    variable=self.threshold_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        on_radio_button_change() # To show initial settings


        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)


    def start_add_cells(self):
        """Begin drawing to add cells to the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.splitting_cells = False
        self.show_brush_settings()
        self.start_mask_edit(add=True)

    def start_remove_cells(self):
        """Begin drawing to remove cells from the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.splitting_cells = False
        self.show_brush_settings()
        self.start_mask_edit(add=False)

    def start_split_cell(self):
        """Enable Split Cell mode: click a merged mask blob to split it into two cells.

        Uses distance-transform peaks (and intensity fallbacks) to place two markers,
        then watershed to find the most probable separation, and records the cut in
        the manual remove mask so Count Cells treats them as two objects.
        """
        if self.original_background is None and self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        # Ensure we have a current cell mask displayed
        try:
            self.show_cell_mask_threshold(calculate=True)
        except Exception as e:
            logger.error(f"Could not prepare mask for Split Cell: {e}")
            messagebox.showerror("Split Cell", f"Could not build the cell mask:\n{e}")
            return

        self.splitting_cells = True
        self.editing_mask = True
        self.mask_edit_add = False
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None

        base_size = self.original_background.size
        if self.manual_remove_mask is None:
            self.manual_remove_mask = Image.new('L', base_size, 0)
        # Keep remove mask size in sync with the image
        if self.manual_remove_mask.size != base_size:
            self.manual_remove_mask = self.manual_remove_mask.resize(base_size, Image.NEAREST)
        self.current_mask = self.manual_remove_mask

        # Click-only interaction (no brush drag)
        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.unbind("<Button-2>")
        self.output.unbind("<B2-Motion>")
        self.output.unbind("<ButtonRelease-2>")
        self.output.unbind("<Button-3>")
        self.output.unbind("<B3-Motion>")
        self.output.unbind("<ButtonRelease-3>")
        self.output.bind("<Button-1>", self.split_cell_at_click)

        logger.info("Started Split Cell mode")
        messagebox.showinfo(
            "Split Cell",
            "Click on a single masked cell (red blob) that should be two cells.\n\n"
            "BARCC will split it into the two most probable cell blobs.\n"
            "Use Finish Mask Edit when done, then Count Cells.",
        )

    def start_mask_edit(self, add=True):
        """Enable mask editing mode"""
        self.editing_mask = True
        self.splitting_cells = False
        self.mask_edit_add = add
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.output.unbind("<Button-1>")
        self.output.bind("<Button-1>", self.edit_mask_draw)
        self.output.bind("<B1-Motion>", self.edit_mask_draw)
        self.output.bind("<ButtonRelease-1>", lambda event : self.show_cell_mask_threshold(event, calculate=False))
        # Right click erases
        self.output.bind("<Button-2>", lambda event : self.edit_mask_draw(event, eraser=True))
        self.output.bind("<B2-Motion>", lambda event : self.edit_mask_draw(event, eraser=True))
        self.output.bind("<ButtonRelease-2>", lambda event : self.show_cell_mask_threshold(event, calculate=False))
        # Increases compatibility for more OSs
        self.output.bind("<Button-3>", lambda event : self.edit_mask_draw(event, eraser=True))
        self.output.bind("<B3-Motion>", lambda event : self.edit_mask_draw(event, eraser=True))
        self.output.bind("<ButtonRelease-3>", lambda event : self.show_cell_mask_threshold(event, calculate=False))

        # Initialize the correct mask depending on edit mode
        base_size = self.original_background.size

        if add:
            if self.manual_add_mask is None:
                self.manual_add_mask = Image.new('L', base_size, 0)
            self.current_mask = self.manual_add_mask
        else:
            if self.manual_remove_mask is None:
                self.manual_remove_mask = Image.new('L', base_size, 0)
            self.current_mask = self.manual_remove_mask
        logger.info(f"Started mask edit mode: {'add' if add else 'remove'} cells")



    def edit_mask_draw(self, event, eraser=False):
        """Draw directly on the binary mask. Coordinates respect current zoom level."""
        if not self.editing_mask or self.current_mask is None:
            return
        if getattr(self, 'splitting_cells', False):
            return

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        x, y = self._canvas_to_image(cx, cy)   # convert to native image space
        r = int(self.brush_size.get())

        draw = ImageDraw.Draw(self.current_mask)
        if eraser == False:
            color = 255
        else:
            color = 0
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

        # --- Visualization fix ---
        mask_arr = np.array(self.current_mask)
        # Make RGB overlay for display
        overlay_rgba = np.zeros((*mask_arr.shape, 4), dtype=np.uint8)
        overlay_rgba[mask_arr > 0] = [255, 0, 0, 255]  # Red overlay where mask is drawn
        overlay_img = Image.fromarray(overlay_rgba)

        self.show_page(mask=overlay_img)

    def _get_combined_cell_mask(self):
        """Return the current boolean cell mask (auto | add) & ~remove, or None."""
        if self.original_background is None:
            return None
        background = self.original_background.convert('L')
        base_size = background.size
        h, w = np.array(background).shape[:2]

        auto_mask = getattr(self, 'auto_mask', None)
        if auto_mask is None or isinstance(auto_mask, bool):
            _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
            auto_mask = np.asarray(auto_labels, dtype=bool).squeeze()
            self.auto_mask = auto_mask
        else:
            auto_mask = np.asarray(auto_mask, dtype=bool).squeeze()

        if auto_mask.shape[0] != h or auto_mask.shape[1] != w:
            auto_mask = np.array(
                Image.fromarray(auto_mask.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)
            ) > 0
            self.auto_mask = auto_mask

        add_mask = np.zeros(auto_mask.shape, dtype=bool)
        remove_mask = np.zeros(auto_mask.shape, dtype=bool)
        if self.manual_add_mask is not None:
            add_arr = np.array(self.manual_add_mask.resize((w, h), Image.NEAREST))
            if add_arr.ndim > 2:
                add_arr = add_arr.squeeze()
            add_mask = add_arr > 0
        if self.manual_remove_mask is not None:
            rem_arr = np.array(self.manual_remove_mask.resize((w, h), Image.NEAREST))
            if rem_arr.ndim > 2:
                rem_arr = rem_arr.squeeze()
            remove_mask = rem_arr > 0

        return (auto_mask | add_mask) & ~remove_mask

    def _bool_mask_to_l_image(self, mask_bool):
        """Boolean ndarray → PIL L image (0/255)."""
        m = np.asarray(mask_bool, dtype=bool).squeeze()
        return Image.fromarray((m.astype(np.uint8) * 255), mode="L")

    def _l_image_to_bool_mask(self, img, target_hw=None):
        """PIL/L path image → boolean mask; optional resize to (h, w)."""
        if not isinstance(img, Image.Image):
            img = Image.fromarray(np.asarray(img))
        if img.mode != "L":
            img = img.convert("L")
        if target_hw is not None:
            th, tw = int(target_hw[0]), int(target_hw[1])
            if img.size != (tw, th):
                img = img.resize((tw, th), Image.NEAREST)
        return np.array(img) > 0

    def _ensure_cell_mask_for_save(self):
        """Build combined cell mask for export without forcing a full redetect if one exists.

        Returns (combined_bool, auto_bool, add_pil_or_None, remove_pil_or_None, size_wh)
        or (None, ...) if no image.
        """
        if self.original_background is None and self.background_image is None:
            return None, None, None, None, None
        bg = self.original_background or self.background_image
        w, h = bg.size

        combined = None
        if getattr(self, "last_cell_mask", None) is not None:
            try:
                combined = np.asarray(self.last_cell_mask, dtype=bool).squeeze()
                if combined.ndim == 2 and (
                    combined.shape[0] != h or combined.shape[1] != w
                ):
                    combined = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(combined), (h, w)
                    )
            except Exception:
                combined = None

        if combined is None:
            combined = self._get_combined_cell_mask()
        if combined is None:
            return None, None, None, None, None

        combined = np.asarray(combined, dtype=bool).squeeze()
        if combined.shape[0] != h or combined.shape[1] != w:
            combined = self._l_image_to_bool_mask(
                self._bool_mask_to_l_image(combined), (h, w)
            )

        auto = getattr(self, "auto_mask", None)
        if auto is not None and not isinstance(auto, bool):
            auto = np.asarray(auto, dtype=bool).squeeze()
            if auto.shape[0] != h or auto.shape[1] != w:
                auto = self._l_image_to_bool_mask(
                    self._bool_mask_to_l_image(auto), (h, w)
                )
        else:
            # Bake combined into auto for a clean portable mask
            auto = combined.copy()

        add_pil = None
        rem_pil = None
        if self.manual_add_mask is not None:
            try:
                add_pil = self.manual_add_mask.convert("L")
                if add_pil.size != (w, h):
                    add_pil = add_pil.resize((w, h), Image.NEAREST)
            except Exception:
                add_pil = None
        if self.manual_remove_mask is not None:
            try:
                rem_pil = self.manual_remove_mask.convert("L")
                if rem_pil.size != (w, h):
                    rem_pil = rem_pil.resize((w, h), Image.NEAREST)
            except Exception:
                rem_pil = None

        return combined, auto, add_pil, rem_pil, (w, h)

    def save_cell_mask(self):
        """Save the current cell detection mask for reuse on another channel.

        Writes a portable ``.barccmask`` package (combined + optional layers) and a
        plain ``_cellmask.png`` under ``output/cell_masks/``. Load on another channel
        of the same section size to skip re-detection for Count Cells.
        """
        try:
            combined, auto, add_pil, rem_pil, size_wh = self._ensure_cell_mask_for_save()
            if combined is None:
                messagebox.showwarning(
                    "Save Cell Mask",
                    "No cell mask is available.\n\n"
                    "Run Cell → Show Mask (or detect cells) on this channel first.",
                )
                return
            if not np.any(combined):
                if not messagebox.askyesno(
                    "Empty Mask",
                    "The current cell mask has no detected cells.\n\n"
                    "Save anyway?",
                ):
                    return

            base_name = self.tiff_filename
            tiff_dir = self.tiff_dir or self.current_tiff_directory
            if not base_name and getattr(self, "current_tiff_path", None):
                base_name = os.path.splitext(os.path.basename(self.current_tiff_path))[0]
                if not tiff_dir:
                    tiff_dir = os.path.dirname(self.current_tiff_path)
            if not base_name:
                base_name = "cells"

            out_dir = self._get_output_directory(tiff_dir, feature="cell_masks") if tiff_dir else None
            initial_dir = out_dir or tiff_dir
            # Prefer a channel-neutral name so the same file is natural across ch0/ch1
            stem = base_name
            for suffix in (
                "_ch0", "_ch1", "_ch2", "_ch3", "_c0", "_c1", "_c2", "_c3",
                "-ch0", "-ch1", "-ch2", "-ch3",
            ):
                if stem.lower().endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            default_name = f"{stem}_cellmask.barccmask"

            save_path = fd.asksaveasfilename(
                title="Save Cell Mask",
                defaultextension=".barccmask",
                filetypes=[
                    ("BARCC Cell Mask", "*.barccmask"),
                    ("PNG mask", "*.png"),
                    ("All files", "*.*"),
                ],
                initialdir=initial_dir,
                initialfile=default_name,
            )
            if not save_path:
                return

            w, h = size_wh
            combined_img = self._bool_mask_to_l_image(combined)
            auto_img = self._bool_mask_to_l_image(auto)

            saved = []
            low = save_path.lower()
            if low.endswith(".png"):
                combined_img.save(save_path)
                saved.append(save_path)
            else:
                if not low.endswith(".barccmask"):
                    save_path = save_path + ".barccmask"
                manifest = {
                    "format_version": 1,
                    "type": "barcc_cellmask",
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "source_tiff_name": self.tiff_filename,
                    "source_tiff_path": getattr(self, "current_tiff_path", None),
                    "mask_size": [int(w), int(h)],
                    "pixel_value": "255=cell, 0=background",
                    "description": (
                        "Portable cell detection mask. Load on another channel of the "
                        "same section to reuse detections for Count Cells."
                    ),
                    "locked_on_load": True,
                }
                with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                    bio = BytesIO()
                    combined_img.save(bio, format="PNG")
                    zf.writestr("combined.png", bio.getvalue())
                    bio = BytesIO()
                    auto_img.save(bio, format="PNG")
                    zf.writestr("auto.png", bio.getvalue())
                    if add_pil is not None:
                        bio = BytesIO()
                        add_pil.save(bio, format="PNG")
                        zf.writestr("manual_add.png", bio.getvalue())
                    if rem_pil is not None:
                        bio = BytesIO()
                        rem_pil.save(bio, format="PNG")
                        zf.writestr("manual_remove.png", bio.getvalue())
                saved.append(save_path)

                # Also write a plain PNG next to it for easy inspection / legacy load
                try:
                    png_side = os.path.splitext(save_path)[0] + ".png"
                    combined_img.save(png_side)
                    saved.append(png_side)
                except Exception as e:
                    logger.debug(f"Side PNG cell mask save skipped: {e}")

            # Keep session mask in sync
            self.auto_mask = auto
            self.last_cell_mask = combined
            self.cell_mask_locked = True
            self.cell_mask_source_path = save_path

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            messagebox.showinfo(
                "Cell Mask Saved",
                "Cell mask saved for cross-channel use:\n\n"
                + "\n".join(saved)
                + "\n\nOn another channel: File → Next Channel… (keep atlas),\n"
                "then Cell → Load Cell Mask… and Count Cells\n"
                "(detection will not re-run while the loaded mask is locked).\n"
                "Cell → Show Mask re-detects and unlocks if you need a new mask.",
            )
            logger.info(f"Cell mask saved: {saved}")
        except Exception as e:
            logger.error(f"save_cell_mask failed: {e}", exc_info=True)
            messagebox.showerror("Save Cell Mask", f"Failed to save cell mask:\n{e}")

    def load_cell_mask(self):
        """Load a previously saved cell mask onto the current channel.

        Applies the mask to auto_mask / last_cell_mask (resized if needed) so
        Count Cells uses it without re-running detection.
        """
        try:
            if self.original_background is None and self.background_image is None:
                messagebox.showwarning(
                    "Load Cell Mask",
                    "Load a TIFF image first, then load the cell mask.",
                )
                return

            initial_dir = self._preferred_open_dir(feature="cell_masks")

            path = fd.askopenfilename(
                title="Load Cell Mask",
                initialdir=initial_dir,
                filetypes=[
                    ("BARCC Cell Mask", "*.barccmask"),
                    ("PNG / TIFF mask", "*.png *.tif *.tiff"),
                    ("All files", "*.*"),
                ],
            )
            if not path:
                return

            bg = self.original_background or self.background_image
            tw, th = bg.size  # PIL width, height
            target_hw = (th, tw)

            combined = None
            auto = None
            add_img = None
            rem_img = None
            src_size = None

            low = path.lower()
            if low.endswith(".barccmask"):
                with zipfile.ZipFile(path, "r") as zf:
                    names = set(zf.namelist())
                    if "manifest.json" in names:
                        try:
                            manifest = json.loads(
                                zf.read("manifest.json").decode("utf-8")
                            )
                            sz = manifest.get("mask_size")
                            if sz and len(sz) == 2:
                                src_size = (int(sz[0]), int(sz[1]))
                        except Exception:
                            pass

                    def _read_member(member):
                        if member not in names:
                            return None
                        im = Image.open(BytesIO(zf.read(member)))
                        im.load()
                        return im.convert("L")

                    comb_im = _read_member("combined.png")
                    auto_im = _read_member("auto.png")
                    add_img = _read_member("manual_add.png")
                    rem_img = _read_member("manual_remove.png")
                    if comb_im is None and auto_im is None:
                        raise ValueError(
                            "Invalid .barccmask: missing combined.png / auto.png"
                        )
                    if comb_im is not None:
                        combined = self._l_image_to_bool_mask(comb_im, target_hw)
                    if auto_im is not None:
                        auto = self._l_image_to_bool_mask(auto_im, target_hw)
                    if add_img is not None and add_img.size != (tw, th):
                        add_img = add_img.resize((tw, th), Image.NEAREST)
                    if rem_img is not None and rem_img.size != (tw, th):
                        rem_img = rem_img.resize((tw, th), Image.NEAREST)
            else:
                im = Image.open(path)
                im.load()
                # If RGB overlay (e.g. _masked.tif with red rings), use non-black / high red
                if im.mode in ("RGB", "RGBA"):
                    arr = np.array(im.convert("RGBA"))
                    # Prefer alpha or bright red-ish pixels; fallback: any non-near-black
                    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
                    mask_bool = (r > 40) & (r >= g) & (r >= b) & (a > 10)
                    if not mask_bool.any():
                        gray = np.array(im.convert("L"))
                        mask_bool = gray > 0
                    combined = mask_bool
                    if combined.shape[0] != th or combined.shape[1] != tw:
                        combined = self._l_image_to_bool_mask(
                            self._bool_mask_to_l_image(combined), target_hw
                        )
                else:
                    combined = self._l_image_to_bool_mask(im.convert("L"), target_hw)
                auto = combined.copy()

            if combined is None and auto is not None:
                combined = auto.copy()
            if auto is None and combined is not None:
                auto = combined.copy()
            if combined is None:
                raise ValueError("Could not read a usable cell mask from the file.")

            # If package had separate layers but no combined, rebuild
            if add_img is not None or rem_img is not None:
                add_b = (
                    np.array(add_img) > 0
                    if add_img is not None
                    else np.zeros_like(auto, dtype=bool)
                )
                rem_b = (
                    np.array(rem_img) > 0
                    if rem_img is not None
                    else np.zeros_like(auto, dtype=bool)
                )
                if add_b.shape != auto.shape:
                    add_b = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(add_b), target_hw
                    )
                if rem_b.shape != auto.shape:
                    rem_b = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(rem_b), target_hw
                    )
                combined = (auto | add_b) & ~rem_b
                self.manual_add_mask = (
                    add_img if add_img is not None else Image.new("L", (tw, th), 0)
                )
                self.manual_remove_mask = (
                    rem_img if rem_img is not None else Image.new("L", (tw, th), 0)
                )
            else:
                # Baked combined only — clear manual layers so count matches file
                self.manual_add_mask = None
                self.manual_remove_mask = None

            self.auto_mask = auto
            self.last_cell_mask = combined
            self.cell_mask_locked = True
            self.cell_mask_source_path = path

            n_pix = int(np.sum(combined))
            size_note = ""
            if src_size and list(src_size) != [tw, th]:
                size_note = (
                    f"\nResized from {src_size[0]}×{src_size[1]} → {tw}×{th} (nearest)."
                )

            # Show overlay without re-detecting
            self.show_cell_mask_threshold(calculate=False)

            messagebox.showinfo(
                "Cell Mask Loaded",
                f"Loaded cell mask from:\n{path}\n\n"
                f"Cell pixels: {n_pix}\n"
                f"Size: {tw}×{th}{size_note}\n\n"
                "Mask is locked for Count Cells (no re-detection).\n"
                "Use Cell → Show Mask to re-detect and unlock if needed.",
            )
            logger.info(
                f"Cell mask loaded from {path}: pixels={n_pix} size={tw}x{th} locked=True"
            )
        except Exception as e:
            logger.error(f"load_cell_mask failed: {e}", exc_info=True)
            messagebox.showerror("Load Cell Mask", f"Failed to load cell mask:\n{e}")

    def _get_ground_truth_cell_mask(self):
        """Ground-truth cell mask for null distributions (loaded or detected)."""
        if getattr(self, "last_cell_mask", None) is not None:
            m = np.asarray(self.last_cell_mask, dtype=bool).squeeze()
            if m.ndim == 2 and m.any():
                return m
        return self._get_combined_cell_mask()

    def _extract_cell_instances(self, gt_bool):
        """Label ground-truth blobs → matched-pair records with exact footprints.

        Each cell includes pixel offsets relative to an integer centroid so a
        random placement can stamp an identical shape (same area/pixel count).
        """
        gt = np.asarray(gt_bool, dtype=bool).squeeze()
        if gt.ndim != 2 or not gt.any():
            return []
        labels = measure.label(gt, connectivity=2)
        props = measure.regionprops(labels)
        cells = []
        for p in props:
            if p.area < 1:
                continue
            r, c = p.centroid
            radius = max(1.0, float(np.sqrt(p.area / np.pi)))
            cri, cci = int(round(r)), int(round(c))
            ys, xs = np.where(labels == p.label)
            # Integer offsets preserve exact area when the full footprint fits
            offs_r = (ys.astype(np.int32) - cri).astype(np.int32)
            offs_c = (xs.astype(np.int32) - cci).astype(np.int32)
            cells.append(
                {
                    "label": int(p.label),
                    "row": float(r),
                    "col": float(c),
                    "crow": cri,
                    "ccol": cci,
                    "area": int(p.area),
                    "radius": radius,
                    "offs_r": offs_r,
                    "offs_c": offs_c,
                    "min_dr": int(offs_r.min()) if offs_r.size else 0,
                    "max_dr": int(offs_r.max()) if offs_r.size else 0,
                    "min_dc": int(offs_c.min()) if offs_c.size else 0,
                    "max_dc": int(offs_c.max()) if offs_c.size else 0,
                }
            )
        return cells

    def _draw_disk_cells(self, shape_hw, placements, radii):
        """Rasterize circular cells at (row, col) with given radii → boolean mask."""
        h, w = int(shape_hw[0]), int(shape_hw[1])
        out = np.zeros((h, w), dtype=bool)
        for (r, c), rad in zip(placements, radii):
            rad = max(1.0, float(rad))
            rr = int(round(r))
            cc = int(round(c))
            r0 = max(0, int(np.floor(rr - rad - 1)))
            r1 = min(h, int(np.ceil(rr + rad + 2)))
            c0 = max(0, int(np.floor(cc - rad - 1)))
            c1 = min(w, int(np.ceil(cc + rad + 2)))
            if r1 <= r0 or c1 <= c0:
                continue
            ys = np.arange(r0, r1)[:, None]
            xs = np.arange(c0, c1)[None, :]
            disk = (ys - rr) ** 2 + (xs - cc) ** 2 <= rad ** 2
            out[r0:r1, c0:c1] |= disk
        return out

    def _stamp_cell_footprint(self, out_mask, cell, center_rc, require_full=False):
        """Stamp a cell's exact GT footprint at a new center. Returns pixels written.

        If ``require_full`` is True, only stamps when every footprint pixel fits
        in-bounds (exact area match); returns 0 otherwise.
        """
        h, w = out_mask.shape[:2]
        nr = int(round(center_rc[0]))
        nc = int(round(center_rc[1]))
        offs_r = cell["offs_r"]
        offs_c = cell["offs_c"]
        if offs_r is None or len(offs_r) == 0:
            return 0
        rs = offs_r + nr
        cs = offs_c + nc
        valid = (rs >= 0) & (rs < h) & (cs >= 0) & (cs < w)
        n_valid = int(np.sum(valid))
        if n_valid == 0:
            return 0
        if require_full and n_valid < int(cell["area"]):
            return 0
        out_mask[rs[valid], cs[valid]] = True
        return n_valid

    def _stamp_cell_footprint_labeled(
        self, out_labels, cell, center_rc, label_id, require_full=True, only_empty=True
    ):
        """Stamp footprint with a unique label id (prevents fragment over-counting).

        Returns pixels written, or 0 on failure.
        """
        h, w = out_labels.shape[:2]
        nr = int(round(center_rc[0]))
        nc = int(round(center_rc[1]))
        offs_r = cell["offs_r"]
        offs_c = cell["offs_c"]
        if offs_r is None or len(offs_r) == 0:
            return 0
        rs = offs_r.astype(np.int32) + nr
        cs = offs_c.astype(np.int32) + nc
        valid = (rs >= 0) & (rs < h) & (cs >= 0) & (cs < w)
        n_valid = int(np.sum(valid))
        if n_valid == 0:
            return 0
        if require_full and n_valid != int(cell["area"]):
            return 0
        rs_v = rs[valid]
        cs_v = cs[valid]
        if only_empty:
            empty = out_labels[rs_v, cs_v] == 0
            if require_full and int(np.sum(empty)) != int(cell["area"]):
                # Would collide / partial — reject so we try another center
                return 0
            if not np.any(empty):
                return 0
            out_labels[rs_v[empty], cs_v[empty]] = int(label_id)
            return int(np.sum(empty))
        out_labels[rs_v, cs_v] = int(label_id)
        return n_valid

    def _sample_random_centers_in_region(self, region_bool, n, rng, min_sep=None):
        """Sample n (row, col) centers inside a boolean region (with light anti-overlap)."""
        coords = np.column_stack(np.where(region_bool))  # (N, 2) row, col
        if coords.shape[0] == 0 or n <= 0:
            return []
        if n >= coords.shape[0]:
            idx = rng.choice(coords.shape[0], size=n, replace=True)
            return [(float(coords[i, 0]), float(coords[i, 1])) for i in idx]

        chosen = []
        order = rng.permutation(coords.shape[0])
        min_sep = float(min_sep) if min_sep is not None else 0.0
        min_sep2 = min_sep * min_sep
        for i in order:
            if len(chosen) >= n:
                break
            r, c = float(coords[i, 0]), float(coords[i, 1])
            if min_sep2 > 0 and chosen:
                ok = True
                for cr, cc in chosen:
                    if (r - cr) ** 2 + (c - cc) ** 2 < min_sep2:
                        ok = False
                        break
                if not ok:
                    continue
            chosen.append((r, c))

        if len(chosen) < n:
            remaining = n - len(chosen)
            used = set((int(round(r)), int(round(c))) for r, c in chosen)
            for i in order:
                if remaining <= 0:
                    break
                r, c = int(coords[i, 0]), int(coords[i, 1])
                if (r, c) in used:
                    continue
                chosen.append((float(r), float(c)))
                used.add((r, c))
                remaining -= 1
        if len(chosen) < n:
            extra = n - len(chosen)
            idx = rng.choice(coords.shape[0], size=extra, replace=True)
            for i in idx:
                chosen.append((float(coords[i, 0]), float(coords[i, 1])))
        return chosen[:n]

    def _candidate_centers_for_cell(self, cell, placeable, h, w, max_candidates=8000):
        """Boolean mask of centers where the full footprint fits in-bounds and
        the center lies in ``placeable`` (region/tissue)."""
        min_r = max(0, -int(cell["min_dr"]))
        max_r = min(h - 1, h - 1 - int(cell["max_dr"]))
        min_c = max(0, -int(cell["min_dc"]))
        max_c = min(w - 1, w - 1 - int(cell["max_dc"]))
        fit = np.zeros((h, w), dtype=bool)
        if max_r >= min_r and max_c >= min_c:
            fit[min_r : max_r + 1, min_c : max_c + 1] = True
        if placeable is not None:
            cand = fit & placeable
        else:
            cand = fit
        return cand

    def _sample_center_for_matched_cell(
        self, cell, placeable, h, w, rng, occupied=None, min_sep=None, max_tries=400
    ):
        """Pick a random center for a full in-bounds stamp inside placeable."""
        cand_mask = self._candidate_centers_for_cell(cell, placeable, h, w)
        coords = np.column_stack(np.where(cand_mask))
        if coords.shape[0] == 0:
            # Relax: any full-fit center in image
            cand_mask = self._candidate_centers_for_cell(cell, None, h, w)
            coords = np.column_stack(np.where(cand_mask))
        if coords.shape[0] == 0:
            return None

        min_sep = float(min_sep) if min_sep is not None else 0.0
        min_sep2 = min_sep * min_sep
        n = coords.shape[0]
        # Sample without building huge permutations when n is large
        if n > max_tries * 4:
            picks = rng.choice(n, size=min(max_tries * 3, n), replace=False)
        else:
            picks = rng.permutation(n)

        for j, i in enumerate(picks):
            if j >= max_tries * 3:
                break
            r, c = float(coords[i, 0]), float(coords[i, 1])
            if occupied and min_sep2 > 0:
                ok = True
                for cr, cc in occupied:
                    if (r - cr) ** 2 + (c - cc) ** 2 < min_sep2:
                        ok = False
                        break
                if not ok:
                    continue
            return (r, c)
        # Fallback: ignore separation
        i = int(picks[0])
        return (float(coords[i, 0]), float(coords[i, 1]))

    def generate_random_cell_mask(self):
        """Build a null cell mask via region-aware matched pairs to the GT mask.

        For each true cell, place **exactly one** random cell with the **identical
        footprint** (same shape and pixel area) at a new XY. Uses a **labeled**
        stamp map so clipping cannot invent extra connected components.

        If a zone atlas / .catlas is loaded, pairing is **region-specific**: each
        GT cell is assigned to the zone of its centroid and placed only inside
        that same zone (matched size + matched region count).
        """
        try:
            if self.original_background is None and self.background_image is None:
                messagebox.showwarning(
                    "Random Cell Mask",
                    "Load a TIFF image first.",
                )
                return

            gt = self._get_ground_truth_cell_mask()
            if gt is None or not np.any(gt):
                messagebox.showwarning(
                    "Random Cell Mask",
                    "No ground-truth cell mask is available.\n\n"
                    "Load a cell mask (Cell → Load Cell Mask…) or run Show Mask / Count Cells first.",
                )
                return

            bg = self.original_background or self.background_image
            tw, th = bg.size
            if gt.shape[0] != th or gt.shape[1] != tw:
                gt = self._l_image_to_bool_mask(
                    self._bool_mask_to_l_image(gt), (th, tw)
                )

            cells = self._extract_cell_instances(gt)
            if not cells:
                messagebox.showwarning(
                    "Random Cell Mask",
                    "Could not identify individual cells in the ground-truth mask.",
                )
                return

            n_gt = len(cells)
            seed_str = simpledialog.askstring(
                "Random Cell Mask",
                f"Ground-truth cells: {n_gt}\n"
                f"Strategy: region-matched pairs (1 random cell per true cell,\n"
                f"same size/shape, new XY; same atlas region when .catlas is loaded).\n\n"
                "Optional random seed (integer). Leave blank for a new draw:",
                parent=self.master,
            )
            if seed_str is None:
                return
            seed_str = seed_str.strip()
            if seed_str == "":
                seed = int(np.random.randint(0, 2**31 - 1))
            else:
                try:
                    seed = int(seed_str)
                except Exception:
                    messagebox.showerror(
                        "Random Cell Mask",
                        "Seed must be an integer (or blank).",
                    )
                    return
            rng = np.random.default_rng(seed)

            # Region mask for stratification
            page = self.current_page if self.current_page is not None else 0
            zone_mask = None
            stratified = False
            if page in self.mask_images and self.mask_images[page] is not None:
                try:
                    zone_mask, _, _ = self._zone_mask_registered_to_background(
                        self.mask_images[page], th, tw
                    )
                    if zone_mask is not None and int(np.max(zone_mask)) > 0:
                        stratified = True
                except Exception as e:
                    logger.debug(f"Zone register for random mask: {e}")
                    zone_mask = None
                    stratified = False

            try:
                gray = self._pil_to_gray_float(bg)
                thr = float(np.percentile(gray, 5))
                tissue = gray > thr
                if int(tissue.sum()) < n_gt * 10:
                    tissue = np.ones((th, tw), dtype=bool)
            except Exception:
                tissue = np.ones((th, tw), dtype=bool)

            # Group cells by zone of GT centroid (region-specific matched pairs)
            by_zone = {}  # zid -> list of cells
            for cell in cells:
                if stratified and zone_mask is not None:
                    r0 = min(max(int(round(cell["row"])), 0), th - 1)
                    c0 = min(max(int(round(cell["col"])), 0), tw - 1)
                    zid = int(zone_mask[r0, c0])
                else:
                    zid = 0
                cell = dict(cell)
                cell["zone_id"] = zid
                by_zone.setdefault(zid, []).append(cell)

            # Labeled map: exactly one id per successfully placed matched cell
            random_labels = np.zeros((th, tw), dtype=np.int32)
            occupied_centers = []
            placed = 0
            n_full_area = 0
            n_failed = 0
            total_gt_area = sum(int(c["area"]) for c in cells)
            next_id = 1
            per_zone_counts = {}  # zid -> (gt_n, placed_n)

            for zid in sorted(by_zone.keys()):
                zone_cells = by_zone[zid]
                if stratified and zone_mask is not None and zid > 0:
                    placeable = zone_mask == int(zid)
                elif stratified and zone_mask is not None and zid == 0:
                    placeable = (zone_mask == 0) | tissue
                    if not placeable.any():
                        placeable = tissue
                else:
                    placeable = tissue

                zone_placed = 0
                # Shuffle order within zone only (keeps per-zone multiset of sizes)
                order = rng.permutation(len(zone_cells))
                for j in order:
                    cell = zone_cells[int(j)]
                    min_sep = max(2.0, float(cell["radius"]) * 1.15)
                    success = False
                    # Several attempts: full stamp, empty space, in-region
                    for attempt in range(60):
                        use_sep = min_sep if attempt < 40 else 0.0
                        center = self._sample_center_for_matched_cell(
                            cell,
                            placeable,
                            th,
                            tw,
                            rng,
                            occupied=occupied_centers,
                            min_sep=use_sep,
                        )
                        if center is None:
                            break
                        # Prefer full-area non-overlapping stamp
                        n_pix = self._stamp_cell_footprint_labeled(
                            random_labels,
                            cell,
                            center,
                            next_id,
                            require_full=True,
                            only_empty=True,
                        )
                        if n_pix == int(cell["area"]):
                            occupied_centers.append(center)
                            placed += 1
                            zone_placed += 1
                            n_full_area += 1
                            next_id += 1
                            success = True
                            break
                    if not success:
                        # Last resort: full stamp allowing overlap on empty only, no sep
                        for attempt in range(40):
                            center = self._sample_center_for_matched_cell(
                                cell,
                                placeable,
                                th,
                                tw,
                                rng,
                                occupied=None,
                                min_sep=0.0,
                            )
                            if center is None:
                                break
                            n_pix = self._stamp_cell_footprint_labeled(
                                random_labels,
                                cell,
                                center,
                                next_id,
                                require_full=True,
                                only_empty=False,
                            )
                            if n_pix == int(cell["area"]):
                                occupied_centers.append(center)
                                placed += 1
                                zone_placed += 1
                                n_full_area += 1
                                next_id += 1
                                success = True
                                break
                    if not success:
                        n_failed += 1
                        logger.debug(
                            f"Matched pair failed for cell area={cell['area']} "
                            f"zone={zid}"
                        )

                per_zone_counts[int(zid)] = (len(zone_cells), zone_placed)

            random_mask = random_labels > 0
            # Component count must equal number of unique labels used
            n_rand = int(random_labels.max()) if random_mask.any() else 0
            # Safety: if boolean connectivity somehow differs, re-count labels
            n_unique = len(np.unique(random_labels)) - (1 if 0 in random_labels else 0)
            n_rand = n_unique

            self.random_cell_mask = random_mask
            self.random_cell_labels = random_labels  # keep for diagnostics / PNN
            self.random_perineuronal_mask = None
            self.random_perineuronal_labels = None
            self.random_perineuronal_cells = None

            # Per-zone summary string
            zone_lines = []
            if stratified:
                for zid in sorted(per_zone_counts.keys()):
                    gt_n, pl_n = per_zone_counts[zid]
                    zname = (
                        (self.zone_names.get(page, {}) or {}).get(zid, f"Zone {zid}")
                        if zid > 0
                        else "Outside regions"
                    )
                    zone_lines.append(f"  {zname}: GT {gt_n} → random {pl_n}")

            self.random_cell_mask_meta = {
                "n_ground_truth": n_gt,
                "n_random_components": n_rand,
                "n_placed": placed,
                "n_failed": n_failed,
                "matched_pairs": True,
                "strategy": "matched_pair_exact_footprint_labeled_region",
                "total_gt_area_px": total_gt_area,
                "total_random_area_px": int(random_mask.sum()),
                "stamps_full_area": n_full_area,
                "stratified": stratified,
                "per_zone_gt_placed": {
                    str(k): {"gt": v[0], "placed": v[1]}
                    for k, v in per_zone_counts.items()
                },
                "seed": seed,
                "atlas_zones_used": (
                    int(np.max(zone_mask))
                    if stratified and zone_mask is not None
                    else 0
                ),
            }

            self.show_ground_truth_and_random_masks()

            zone_txt = ("\n".join(zone_lines) + "\n") if zone_lines else ""
            warn = ""
            if n_rand != n_gt or placed != n_gt:
                warn = (
                    f"\nNote: placed {placed}/{n_gt} matched cells "
                    f"({n_failed} could not be placed without clipping/collision).\n"
                )
            save_it = messagebox.askyesno(
                "Random Cell Mask Generated",
                f"Region-matched pair random null created.\n\n"
                f"Ground-truth cells: {n_gt}\n"
                f"Random cells placed: {placed} (labeled components: {n_rand})\n"
                f"GT total area: {total_gt_area} px\n"
                f"Random total area: {int(random_mask.sum())} px\n"
                f"Full-size stamps: {n_full_area}\n"
                f"Stratified by atlas region: {'Yes' if stratified else 'No'}\n"
                f"{zone_txt}"
                f"Random seed: {seed}\n"
                f"{warn}\n"
                f"Each random cell is the same shape/size as one true cell "
                f"(1:1 pair), placed at a new XY"
                f"{' inside the same atlas region' if stratified else ''}.\n"
                f"Display: red = ground truth, cyan = random.\n\n"
                f"Save the random mask to disk?",
            )
            if save_it:
                self._save_random_cell_mask_file()

            logger.info(
                f"Random cell mask (region matched pairs): gt={n_gt} placed={placed} "
                f"components={n_rand} gt_area={total_gt_area} "
                f"rand_area={int(random_mask.sum())} failed={n_failed} "
                f"stratified={stratified} zones={per_zone_counts} seed={seed}"
            )
        except Exception as e:
            logger.error(f"generate_random_cell_mask failed: {e}", exc_info=True)
            messagebox.showerror(
                "Random Cell Mask",
                f"Failed to generate random cell mask:\n{e}",
            )

    def show_ground_truth_and_random_masks(self):
        """Overlay ground-truth (red) and random null (cyan) cell masks."""
        if self.original_background is None and self.background_image is None:
            messagebox.showwarning("Show Masks", "Load a TIFF image first.")
            return

        gt = self._get_ground_truth_cell_mask()
        rand = getattr(self, "random_cell_mask", None)
        if gt is None and rand is None:
            messagebox.showinfo(
                "Show Masks",
                "No ground-truth or random cell mask is available.\n\n"
                "Load/detect a cell mask, then Generate Random Cell Mask…",
            )
            return

        target_size = (self.original_background or self.background_image).size
        # Start transparent
        composite = Image.new("RGBA", target_size, (0, 0, 0, 0))

        if gt is not None and np.any(gt):
            red = self._cell_detection_ring_overlay(
                gt, size=target_size, color=(255, 0, 0), alpha=230, thickness=2
            )
            composite = Image.alpha_composite(composite, red.convert("RGBA"))

        if rand is not None and np.any(rand):
            cyan = self._cell_detection_ring_overlay(
                rand, size=target_size, color=(0, 220, 255), alpha=220, thickness=2
            )
            composite = Image.alpha_composite(composite, cyan.convert("RGBA"))

        self.show_page(mask=composite)
        self.showing_auto_mask = True

        meta = getattr(self, "random_cell_mask_meta", None) or {}
        if meta:
            logger.info(
                f"Showing GT+random masks: gt_cells={meta.get('n_ground_truth')} "
                f"random={meta.get('n_placed')} stratified={meta.get('stratified')}"
            )

    def clear_random_cell_mask(self):
        """Remove the random null mask overlay."""
        self.random_cell_mask = None
        self.random_cell_mask_meta = None
        # Random PNN shells are derived from random cells — clear them too
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None
        try:
            if self.auto_mask is not None:
                self.show_cell_mask_threshold(calculate=False)
            else:
                self.show_page()
        except Exception:
            self.show_page()
        messagebox.showinfo("Random Cell Mask", "Random cell mask cleared.")

    # ------------------------------------------------------------------
    # Perineuronal (PNN) shells — ring between cell boundary and 2× cell area
    # ------------------------------------------------------------------

    def _build_perineuronal_shells(self, cell_bool, area_factor=2.0):
        """Build perineuronal shells for each labeled cell.

        Outer disk area = ``area_factor × cell_area`` (default 2.0 = 200%).
        Shell = outer disk minus the cell body (and other cell bodies).

        Returns
        -------
        union : bool (H,W)
        labels : int32 (H,W) — cell label id in shell pixels (0 = background)
        records : list of dicts with cell_id, area, shell_area, centroid, radius, outer_radius
        """
        cell_bool = np.asarray(cell_bool, dtype=bool).squeeze()
        if cell_bool.ndim != 2 or not cell_bool.any():
            return None, None, []

        h, w = cell_bool.shape
        cell_labels = measure.label(cell_bool, connectivity=2)
        props = measure.regionprops(cell_labels)
        shell_labels = np.zeros((h, w), dtype=np.int32)
        records = []

        for p in props:
            if p.area < 1:
                continue
            lab = int(p.label)
            area = int(p.area)
            r_eq = max(1.0, float(np.sqrt(area / np.pi)))
            # Outer radius so π R² = area_factor * A
            r_out = max(r_eq + 0.5, float(np.sqrt(float(area_factor) * area / np.pi)))
            rr, cc = p.centroid
            rr_i, cc_i = int(round(rr)), int(round(cc))

            r0 = max(0, int(np.floor(rr_i - r_out - 1)))
            r1 = min(h, int(np.ceil(rr_i + r_out + 2)))
            c0 = max(0, int(np.floor(cc_i - r_out - 1)))
            c1 = min(w, int(np.ceil(cc_i + r_out + 2)))
            if r1 <= r0 or c1 <= c0:
                continue

            ys = np.arange(r0, r1)[:, None]
            xs = np.arange(c0, c1)[None, :]
            outer = (ys - rr_i) ** 2 + (xs - cc_i) ** 2 <= r_out ** 2
            # Extracellular ring: outside all cell bodies
            local_cells = cell_bool[r0:r1, c0:c1]
            shell = outer & ~local_cells
            # Only write into unoccupied shell labels (first cell wins on overlap)
            dest = shell_labels[r0:r1, c0:c1]
            write = shell & (dest == 0)
            dest[write] = lab
            shell_labels[r0:r1, c0:c1] = dest

            shell_area = int(np.sum(shell_labels == lab))
            records.append(
                {
                    "cell_id": lab,
                    "area": area,
                    "shell_area": shell_area,
                    "row": float(rr),
                    "col": float(cc),
                    "radius": r_eq,
                    "outer_radius": r_out,
                }
            )

        union = shell_labels > 0
        return union, shell_labels, records

    def draw_perineuronal_masks(self):
        """Create perineuronal shells for GT cells (and random cells if present).

        Shell = disk with area 200% of the cell (2×), minus the cell body mask.
        """
        try:
            if self.original_background is None and self.background_image is None:
                messagebox.showwarning(
                    "Perineuronal Masks",
                    "Load a TIFF image first.",
                )
                return

            bg = self.original_background or self.background_image
            tw, th = bg.size
            factor = float(getattr(self, "perineuronal_area_factor", 2.0) or 2.0)

            gt = self._get_ground_truth_cell_mask()
            if gt is None or not np.any(gt):
                messagebox.showwarning(
                    "Perineuronal Masks",
                    "No ground-truth cell mask is available.\n\n"
                    "Load a cell mask or run Cell → Show Mask / Count Cells first.",
                )
                return

            if gt.shape[0] != th or gt.shape[1] != tw:
                gt = self._l_image_to_bool_mask(
                    self._bool_mask_to_l_image(gt), (th, tw)
                )

            progress = self._show_busy_dialog("Perineuronal Masks")
            try:
                progress.set_progress(20, "Building GT perineuronal shells…")
                union, labels, records = self._build_perineuronal_shells(
                    gt, area_factor=factor
                )
                self.perineuronal_mask = union
                self.perineuronal_labels = labels
                self.perineuronal_cells = records

                n_rand = 0
                rand = getattr(self, "random_cell_mask", None)
                if rand is not None and np.any(rand):
                    progress.set_progress(55, "Building random perineuronal shells…")
                    rmask = np.asarray(rand, dtype=bool).squeeze()
                    if rmask.shape[0] != th or rmask.shape[1] != tw:
                        rmask = self._l_image_to_bool_mask(
                            self._bool_mask_to_l_image(rmask), (th, tw)
                        )
                    ru, rl, rr = self._build_perineuronal_shells(
                        rmask, area_factor=factor
                    )
                    self.random_perineuronal_mask = ru
                    self.random_perineuronal_labels = rl
                    self.random_perineuronal_cells = rr
                    n_rand = len(rr or [])
                else:
                    self.random_perineuronal_mask = None
                    self.random_perineuronal_labels = None
                    self.random_perineuronal_cells = None

                progress.set_progress(90, "Displaying…")
                self.show_perineuronal_masks()
            finally:
                if progress and not getattr(progress, "closed", False):
                    progress.close()

            n_gt = len(self.perineuronal_cells or [])
            msg = (
                f"Perineuronal masks drawn (outer area = {factor:.0%} of cell area).\n\n"
                f"True cells with shells: {n_gt}\n"
            )
            if n_rand:
                msg += f"Random cells with shells: {n_rand}\n"
            else:
                msg += (
                    "No random cell mask present — only true-cell shells drawn.\n"
                    "(Generate Random Cell Mask first if you need a null distribution.)\n"
                )
            msg += (
                "\nDisplay: magenta = true PNN shells, yellow = random PNN shells\n"
                "(cell bodies remain red / cyan).\n\n"
                "Use Axons and Nets → Measure Perineuronal Intensity… next."
            )
            messagebox.showinfo("Perineuronal Masks", msg)
            logger.info(
                f"Perineuronal masks: gt_cells={n_gt} random_cells={n_rand} "
                f"area_factor={factor}"
            )
        except Exception as e:
            logger.error(f"draw_perineuronal_masks failed: {e}", exc_info=True)
            messagebox.showerror(
                "Perineuronal Masks",
                f"Failed to draw perineuronal masks:\n{e}",
            )

    def show_perineuronal_masks(self):
        """Overlay cell masks + perineuronal shells (true magenta, random yellow)."""
        if self.original_background is None and self.background_image is None:
            messagebox.showwarning("Perineuronal Masks", "Load a TIFF image first.")
            return

        target_size = (self.original_background or self.background_image).size
        composite = Image.new("RGBA", target_size, (0, 0, 0, 0))

        # GT cells (red)
        gt = self._get_ground_truth_cell_mask()
        if gt is not None and np.any(gt):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    gt, size=target_size, color=(255, 0, 0), alpha=200, thickness=2
                ).convert("RGBA"),
            )

        # GT PNN shells (magenta)
        pnn = getattr(self, "perineuronal_mask", None)
        if pnn is not None and np.any(pnn):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    pnn, size=target_size, color=(255, 0, 200), alpha=180, thickness=1
                ).convert("RGBA"),
            )

        # Random cells (cyan)
        rand = getattr(self, "random_cell_mask", None)
        if rand is not None and np.any(rand):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    rand, size=target_size, color=(0, 220, 255), alpha=200, thickness=2
                ).convert("RGBA"),
            )

        # Random PNN shells (yellow)
        rpnn = getattr(self, "random_perineuronal_mask", None)
        if rpnn is not None and np.any(rpnn):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    rpnn, size=target_size, color=(255, 220, 0), alpha=180, thickness=1
                ).convert("RGBA"),
            )

        if not np.any(np.array(composite)[..., 3]):
            messagebox.showinfo(
                "Perineuronal Masks",
                "Nothing to show.\n\nDraw perineuronal masks (and/or load cell masks) first.",
            )
            return

        self.show_page(mask=composite)
        self.showing_auto_mask = True

    def clear_perineuronal_masks(self):
        """Clear all perineuronal shell masks."""
        self.perineuronal_mask = None
        self.perineuronal_labels = None
        self.perineuronal_cells = None
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None
        try:
            if getattr(self, "random_cell_mask", None) is not None:
                self.show_ground_truth_and_random_masks()
            elif self.auto_mask is not None:
                self.show_cell_mask_threshold(calculate=False)
            else:
                self.show_page()
        except Exception:
            self.show_page()
        messagebox.showinfo("Perineuronal Masks", "Perineuronal masks cleared.")

    def _sem(self, values):
        """Standard error of the mean; NaN if fewer than 2 samples."""
        vals = np.asarray(values, dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        n = vals.size
        if n < 1:
            return np.nan
        if n == 1:
            return 0.0
        return float(np.std(vals, ddof=1) / np.sqrt(n))

    def _sem_median(self, values):
        """Asymptotic SEM of the median under normality: 1.2533 × SEM_mean."""
        sm = self._sem(values)
        if sm is None or (isinstance(sm, float) and np.isnan(sm)):
            return np.nan
        return float(1.253314 * sm)

    def _zone_id_at_point(self, row, col, zone_mask, zone_names):
        """Return (zone_id, zone_name) for a pixel; (0, 'Outside') if none."""
        if zone_mask is None:
            return 0, "Outside"
        h, w = zone_mask.shape[:2]
        r = int(round(row))
        c = int(round(col))
        if r < 0 or c < 0 or r >= h or c >= w:
            return 0, "Outside"
        zid = int(zone_mask[r, c])
        if zid <= 0:
            return 0, "Outside"
        name = zone_names.get(zid, zone_names.get(int(zid), f"Zone {zid}"))
        return zid, str(name)

    def _measure_pnn_per_cell(self, gray, shell_labels, cell_records, zone_mask, zone_names):
        """Per-cell perineuronal intensity rows."""
        rows = []
        if shell_labels is None or not cell_records:
            return rows
        for rec in cell_records:
            lab = int(rec["cell_id"])
            pix = gray[shell_labels == lab]
            if pix.size == 0:
                inten = np.nan
            else:
                inten = float(np.mean(pix))
            zid, zname = self._zone_id_at_point(
                rec["row"], rec["col"], zone_mask, zone_names
            )
            rows.append(
                {
                    "Cell_ID": lab,
                    "Zone_ID": zid,
                    "Zone": zname,
                    "Cell_Area": int(rec.get("area", 0)),
                    "Shell_Area": int(rec.get("shell_area", 0) or 0),
                    "Perineuronal_Intensity": inten,
                    "Centroid_X": float(rec.get("col", 0)),
                    "Centroid_Y": float(rec.get("row", 0)),
                    "Outer_Radius": float(rec.get("outer_radius", 0) or 0),
                }
            )
        return rows

    def measure_perineuronal_intensity(self):
        """Measure intensity in perineuronal shells; export structure + per-cell tables.

        Spreadsheets written under ``output/pnn/``:
          - ``{base}_pnn_by_structure.xlsx`` — one row per atlas structure with
            mean/SEM and median/SEM for true (and random if present) PNN intensity
          - ``{base}_pnn_cells_true.xlsx`` — one row per true cell (area + PNN intensity)
          - ``{base}_pnn_cells_random.xlsx`` — same for random cells (if drawn)
        """
        try:
            # Auto-draw shells if missing but cell masks exist
            need_draw = self.perineuronal_labels is None or not (
                self.perineuronal_cells
            )
            if need_draw:
                gt = self._get_ground_truth_cell_mask()
                if gt is None or not np.any(gt):
                    messagebox.showwarning(
                        "Perineuronal Intensity",
                        "No cell mask available.\n\n"
                        "Load/detect cells, then Axons and Nets → Draw Perineuronal Masks.",
                    )
                    return
                if not messagebox.askyesno(
                    "Perineuronal Intensity",
                    "Perineuronal masks have not been drawn yet.\n\n"
                    "Draw them now (2× cell area shells) and measure?",
                ):
                    return
                self.draw_perineuronal_masks()
                if self.perineuronal_labels is None:
                    return

            bg = self.original_background or self.background_image
            if bg is None:
                messagebox.showwarning(
                    "Perineuronal Intensity",
                    "Load a TIFF image first.",
                )
                return

            gray = self._pil_to_gray_float(bg)
            th, tw = gray.shape[:2]
            page = self.current_page if self.current_page is not None else 0
            zone_names = dict(self.zone_names.get(page, {}) or {})
            zone_mask = None
            if page in self.mask_images and self.mask_images[page] is not None:
                try:
                    zone_mask, _, _ = self._zone_mask_registered_to_background(
                        self.mask_images[page], th, tw
                    )
                except Exception:
                    zone_mask = None

            # Per-cell tables
            true_rows = self._measure_pnn_per_cell(
                gray,
                self.perineuronal_labels,
                self.perineuronal_cells or [],
                zone_mask,
                zone_names,
            )
            rand_rows = []
            if (
                getattr(self, "random_perineuronal_labels", None) is not None
                and getattr(self, "random_perineuronal_cells", None)
            ):
                rand_rows = self._measure_pnn_per_cell(
                    gray,
                    self.random_perineuronal_labels,
                    self.random_perineuronal_cells,
                    zone_mask,
                    zone_names,
                )

            if not true_rows and not rand_rows:
                messagebox.showwarning(
                    "Perineuronal Intensity",
                    "No perineuronal shell pixels found to measure.",
                )
                return

            # Aggregate by structure
            def _agg(rows, prefix):
                """prefix e.g. True / Random → columns True_Mean, True_SEM_Mean, ..."""
                by_zone = {}
                for r in rows:
                    key = (int(r["Zone_ID"]), str(r["Zone"]))
                    by_zone.setdefault(key, []).append(r["Perineuronal_Intensity"])
                out = {}
                for key, vals in by_zone.items():
                    v = [x for x in vals if x is not None and np.isfinite(x)]
                    n = len(v)
                    mean_v = float(np.mean(v)) if n else np.nan
                    med_v = float(np.median(v)) if n else np.nan
                    out[key] = {
                        f"{prefix}_N_Cells": n,
                        f"{prefix}_Mean": mean_v,
                        f"{prefix}_SEM_Mean": self._sem(v),
                        f"{prefix}_Median": med_v,
                        f"{prefix}_SEM_Median": self._sem_median(v),
                    }
                return out

            true_agg = _agg(true_rows, "True")
            rand_agg = _agg(rand_rows, "Random") if rand_rows else {}

            # All zone keys from both + named atlas zones
            keys = set(true_agg.keys()) | set(rand_agg.keys())
            for zid, zname in zone_names.items():
                try:
                    keys.add((int(zid), str(zname)))
                except Exception:
                    pass
            if not keys and true_rows:
                keys = set(true_agg.keys())

            struct_rows = []
            for zid, zname in sorted(keys, key=lambda k: (k[0] == 0, k[0], k[1])):
                row = {"Zone_ID": zid, "Zone": zname}
                row.update(
                    true_agg.get(
                        (zid, zname),
                        {
                            "True_N_Cells": 0,
                            "True_Mean": np.nan,
                            "True_SEM_Mean": np.nan,
                            "True_Median": np.nan,
                            "True_SEM_Median": np.nan,
                        },
                    )
                )
                # Match by Zone_ID if name slightly differs
                if (zid, zname) not in true_agg and zid:
                    for (zid2, zname2), data in true_agg.items():
                        if zid2 == zid:
                            row.update(data)
                            break
                if rand_rows:
                    if (zid, zname) in rand_agg:
                        row.update(rand_agg[(zid, zname)])
                    else:
                        matched = False
                        for (zid2, zname2), data in rand_agg.items():
                            if zid2 == zid:
                                row.update(data)
                                matched = True
                                break
                        if not matched:
                            row.update(
                                {
                                    "Random_N_Cells": 0,
                                    "Random_Mean": np.nan,
                                    "Random_SEM_Mean": np.nan,
                                    "Random_Median": np.nan,
                                    "Random_SEM_Median": np.nan,
                                }
                            )
                struct_rows.append(row)

            df_struct = pd.DataFrame(struct_rows)
            df_true = pd.DataFrame(true_rows) if true_rows else pd.DataFrame()
            df_rand = pd.DataFrame(rand_rows) if rand_rows else pd.DataFrame()

            base_name, tiff_dir, out_dir = self._intensity_output_basename_and_dir(
                feature="pnn"
            )
            saved = []

            def _write_df(df, path_xlsx, sheet, csv_fallback):
                if df is None or df.empty:
                    return None
                for engine in ("openpyxl", "xlsxwriter"):
                    try:
                        with pd.ExcelWriter(path_xlsx, engine=engine) as writer:
                            df.to_excel(writer, sheet_name=sheet, index=False)
                        return path_xlsx
                    except Exception as e:
                        logger.warning(f"PNN Excel {engine}: {e}")
                try:
                    df.to_csv(csv_fallback, index=False)
                    return csv_fallback
                except Exception as e:
                    logger.error(f"PNN CSV failed: {e}")
                    return None

            if out_dir:
                p_struct = os.path.join(out_dir, f"{base_name}_pnn_by_structure.xlsx")
                p_true = os.path.join(out_dir, f"{base_name}_pnn_cells_true.xlsx")
                p_rand = os.path.join(out_dir, f"{base_name}_pnn_cells_random.xlsx")
                s1 = _write_df(
                    df_struct,
                    p_struct,
                    "PNN by Structure",
                    os.path.join(out_dir, f"{base_name}_pnn_by_structure.csv"),
                )
                s2 = _write_df(
                    df_true,
                    p_true,
                    "PNN Cells True",
                    os.path.join(out_dir, f"{base_name}_pnn_cells_true.csv"),
                )
                s3 = None
                if not df_rand.empty:
                    s3 = _write_df(
                        df_rand,
                        p_rand,
                        "PNN Cells Random",
                        os.path.join(out_dir, f"{base_name}_pnn_cells_random.csv"),
                    )
                for p in (s1, s2, s3):
                    if p:
                        saved.append(p)
            else:
                # Manual folder
                path = fd.asksaveasfilename(
                    title="Save PNN by-structure table",
                    defaultextension=".xlsx",
                    filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
                    initialfile=f"{base_name}_pnn_by_structure.xlsx",
                )
                if path:
                    if path.lower().endswith(".csv"):
                        df_struct.to_csv(path, index=False)
                        saved.append(path)
                    else:
                        if not path.lower().endswith(".xlsx"):
                            path += ".xlsx"
                        s1 = _write_df(df_struct, path, "PNN by Structure", path.replace(".xlsx", ".csv"))
                        if s1:
                            saved.append(s1)
                        parent = os.path.dirname(path)
                        if not df_true.empty:
                            s2 = _write_df(
                                df_true,
                                os.path.join(parent, f"{base_name}_pnn_cells_true.xlsx"),
                                "PNN Cells True",
                                os.path.join(parent, f"{base_name}_pnn_cells_true.csv"),
                            )
                            if s2:
                                saved.append(s2)
                        if not df_rand.empty:
                            s3 = _write_df(
                                df_rand,
                                os.path.join(parent, f"{base_name}_pnn_cells_random.xlsx"),
                                "PNN Cells Random",
                                os.path.join(parent, f"{base_name}_pnn_cells_random.csv"),
                            )
                            if s3:
                                saved.append(s3)

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            if saved:
                dest = out_dir or os.path.dirname(saved[0])
                messagebox.showinfo(
                    "Perineuronal Intensity Saved",
                    f"True cells measured: {len(true_rows)}\n"
                    f"Random cells measured: {len(rand_rows)}\n"
                    f"Structures in summary: {len(struct_rows)}\n\n"
                    f"Saved under:\n{dest}\n\n"
                    + "\n".join(saved)
                    + "\n\nBy-structure columns: True/Random Mean, SEM_Mean, "
                    "Median, SEM_Median.\n"
                    "Per-cell files: Cell_Area + Perineuronal_Intensity.",
                )
                logger.info(f"PNN intensity export: {saved}")
            else:
                messagebox.showwarning(
                    "Export Failed",
                    "Measured intensities but could not write spreadsheets.\n"
                    "Check folder permissions / install openpyxl.",
                )
        except Exception as e:
            logger.error(f"measure_perineuronal_intensity failed: {e}", exc_info=True)
            messagebox.showerror(
                "Perineuronal Intensity",
                f"Failed to measure perineuronal intensity:\n{e}",
            )

    def _save_random_cell_mask_file(self):
        """Write random null mask to output/cell_masks/ as PNG + JSON sidecar."""
        rand = getattr(self, "random_cell_mask", None)
        if rand is None or not np.any(rand):
            messagebox.showwarning("Save Random Mask", "No random cell mask to save.")
            return
        base_name = self.tiff_filename or "cells"
        tiff_dir = self.tiff_dir or self.current_tiff_directory
        out_dir = self._get_output_directory(tiff_dir, feature="cell_masks") if tiff_dir else None
        if not out_dir:
            path = fd.asksaveasfilename(
                title="Save Random Cell Mask",
                defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("All files", "*.*")],
                initialfile=f"{base_name}_random_cellmask.png",
            )
            if not path:
                return
            self._bool_mask_to_l_image(rand).save(path)
            messagebox.showinfo("Random Mask Saved", f"Saved:\n{path}")
            return

        png_path = os.path.join(out_dir, f"{base_name}_random_cellmask.png")
        self._bool_mask_to_l_image(rand).save(png_path)

        # Sidecar JSON with meta + optional per-region counts
        meta = dict(getattr(self, "random_cell_mask_meta", None) or {})
        meta["saved_at"] = datetime.now().isoformat(timespec="seconds")
        meta["source_tiff"] = self.tiff_filename
        json_path = os.path.join(out_dir, f"{base_name}_random_cellmask.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logger.debug(f"Random mask JSON save failed: {e}")
            json_path = None

        if hasattr(self, "tiff_tree") and self.current_tiff_directory:
            try:
                self.master.after(300, self.refresh_tiff_file_list)
            except Exception:
                pass

        msg = f"Saved:\n{png_path}"
        if json_path:
            msg += f"\n{json_path}"
        messagebox.showinfo("Random Mask Saved", msg)
        logger.info(f"Random cell mask saved: {png_path}")

    def _find_two_probable_cell_centers(self, blob, intensity):
        """Find two seed points inside a binary blob for the most probable two-cell split.

        Preference order:
          1. Top two distance-transform peaks (centers of mass of thickness)
          2. Top two intensity peaks inside the blob
          3. Geometric: max-distance pixel + farthest other blob pixel
        Returns array shape (2, 2) of (row, col), or None if the blob is too small.
        """
        blob = np.asarray(blob, dtype=bool)
        if blob.sum() < 6:
            return None

        distance = distance_transform_edt(blob)
        # min_distance scales with blob size so the two peaks stay distinct
        area = int(blob.sum())
        min_dist = max(2, int(np.sqrt(area) / 6.0))

        coords = None
        try:
            coords = feature.peak_local_max(
                distance,
                min_distance=min_dist,
                labels=blob.astype(np.int32),
                num_peaks=2,
            )
        except TypeError:
            try:
                coords = feature.peak_local_max(distance, min_distance=min_dist, num_peaks=2)
                if coords is not None and len(coords):
                    coords = np.array([c for c in coords if blob[c[0], c[1]]])
            except Exception:
                coords = None
        except Exception:
            coords = None

        if coords is not None and len(coords) >= 2:
            return np.asarray(coords[:2], dtype=int)

        # Intensity peaks (brighter spots are more probable cell centers)
        inten = np.asarray(intensity, dtype=np.float64).copy()
        if inten.shape != blob.shape:
            try:
                inten = np.array(
                    Image.fromarray(
                        ((inten - inten.min()) / (inten.max() - inten.min() + 1e-8) * 255).astype(np.uint8)
                    ).resize((blob.shape[1], blob.shape[0]), Image.BILINEAR)
                ).astype(np.float64)
            except Exception:
                inten = distance
        inten = inten.astype(np.float64)
        inten[~blob] = 0
        try:
            coords = feature.peak_local_max(
                inten,
                min_distance=min_dist,
                labels=blob.astype(np.int32),
                num_peaks=2,
            )
        except Exception:
            coords = None
        if coords is not None and len(coords) >= 2:
            return np.asarray(coords[:2], dtype=int)

        # Geometric fallback: thickest point + farthest point in the blob
        flat = np.argmax(distance)
        y1, x1 = np.unravel_index(int(flat), distance.shape)
        if not blob[y1, x1]:
            ys, xs = np.where(blob)
            if len(ys) < 2:
                return None
            y1, x1 = int(ys[0]), int(xs[0])
        ys, xs = np.where(blob)
        d2 = (ys.astype(np.float64) - y1) ** 2 + (xs.astype(np.float64) - x1) ** 2
        i2 = int(np.argmax(d2))
        if d2[i2] < 1:
            return None
        return np.array([[y1, x1], [int(ys[i2]), int(xs[i2])]], dtype=int)

    def split_cell_at_click(self, event):
        """Click handler: split the masked cell under the cursor into two blobs."""
        if not getattr(self, 'splitting_cells', False):
            return
        if self.original_background is None:
            messagebox.showerror("Split Cell", "No image loaded.")
            return

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_image(cx, cy)
        x, y = int(round(ix)), int(round(iy))

        combined = self._get_combined_cell_mask()
        if combined is None:
            messagebox.showerror("Split Cell", "Could not build the cell mask.")
            return

        h, w = combined.shape
        if x < 0 or y < 0 or x >= w or y >= h:
            messagebox.showinfo("Split Cell", "Click inside the image.")
            return
        if not combined[y, x]:
            messagebox.showinfo(
                "Split Cell",
                "Click on a red masked cell. The click landed outside the cell mask.",
            )
            return

        # Connected component under the click = the single "masked cell" to split
        labels_cc = measure.label(combined, connectivity=2)
        target_id = int(labels_cc[y, x])
        if target_id == 0:
            messagebox.showinfo("Split Cell", "No cell found under the click.")
            return
        blob = labels_cc == target_id
        blob_area = int(blob.sum())
        if blob_area < 8:
            messagebox.showinfo(
                "Split Cell",
                "That cell is too small to split meaningfully.",
            )
            return

        # Preprocessed intensity for probabilistic centers (same pipeline as detection)
        try:
            bg = self.original_background.convert('L')
            intensity = self.image_processor.preprocess_image(bg)
            intensity = np.asarray(intensity, dtype=np.float64)
            if intensity.shape != blob.shape:
                intensity = np.array(
                    Image.fromarray(
                        ((intensity - intensity.min()) /
                         (intensity.max() - intensity.min() + 1e-8) * 255).astype(np.uint8)
                    ).resize((w, h), Image.BILINEAR),
                    dtype=np.float64,
                )
        except Exception:
            intensity = distance_transform_edt(blob).astype(np.float64)

        centers = self._find_two_probable_cell_centers(blob, intensity)
        if centers is None or len(centers) < 2:
            messagebox.showinfo(
                "Split Cell",
                "Could not find two probable cell centers inside that blob.",
            )
            return

        # Watershed with exactly two markers → two most probable blobs
        markers = np.zeros(blob.shape, dtype=np.int32)
        markers[int(centers[0, 0]), int(centers[0, 1])] = 1
        markers[int(centers[1, 0]), int(centers[1, 1])] = 2

        distance = distance_transform_edt(blob)
        try:
            # watershed_line=True leaves the ridge as 0 → natural split for labeling
            split_labels = segmentation.watershed(
                -distance, markers, mask=blob, watershed_line=True
            )
        except TypeError:
            split_labels = segmentation.watershed(-distance, markers, mask=blob)
            # Manually mark inter-label boundary as cut if watershed_line unsupported
            cut = np.zeros_like(blob, dtype=bool)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                shifted = np.roll(split_labels, shift=dy, axis=0)
                shifted = np.roll(shifted, shift=dx, axis=1)
                cut |= (
                    (split_labels > 0)
                    & (shifted > 0)
                    & (split_labels != shifted)
                )
            # Apply cut into labels as 0
            split_labels = split_labels.copy()
            split_labels[cut] = 0

        # Pixels that belonged to the blob but are no longer labeled = the cut ridge
        cut_pixels = blob & (split_labels == 0)
        if not cut_pixels.any():
            # Force a thin cut between the two seeds along the gradient of distance
            # by dilating the watershed ridge once from inter-label neighbors
            lab = split_labels.copy()
            if lab.max() < 2:
                messagebox.showinfo(
                    "Split Cell",
                    "Watershed could not separate two regions. Try Remove Cell to cut manually.",
                )
                return
            cut = np.zeros_like(blob, dtype=bool)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                shifted = np.roll(lab, shift=dy, axis=0)
                shifted = np.roll(shifted, shift=dx, axis=1)
                cut |= (lab > 0) & (shifted > 0) & (lab != shifted) & blob
            cut_pixels = cut

        if not cut_pixels.any():
            messagebox.showinfo(
                "Split Cell",
                "Could not create a separation line between the two blobs.",
            )
            return

        # Verify we actually get two components after the cut
        after = blob.copy()
        after[cut_pixels] = False
        n_after = measure.label(after, connectivity=2).max()
        if n_after < 2:
            # Widen the cut slightly (1-pixel dilation of the ridge, still inside blob)
            cut_pixels = ndi.binary_dilation(cut_pixels, iterations=1) & blob
            after = blob.copy()
            after[cut_pixels] = False
            n_after = measure.label(after, connectivity=2).max()
        if n_after < 2:
            messagebox.showinfo(
                "Split Cell",
                "Split did not produce two separate cells. The shape may not be a double cell.",
            )
            return

        # Persist the cut via manual remove mask (survives re-detect + Count Cells)
        self.save_state()
        base_size = self.original_background.size
        if self.manual_remove_mask is None:
            self.manual_remove_mask = Image.new('L', base_size, 0)
        if self.manual_remove_mask.size != base_size:
            self.manual_remove_mask = self.manual_remove_mask.resize(base_size, Image.NEAREST)

        rem = np.array(self.manual_remove_mask)
        if rem.ndim > 2:
            rem = rem.squeeze()
        if rem.shape != cut_pixels.shape:
            cut_img = Image.fromarray(cut_pixels.astype(np.uint8) * 255).resize(
                self.manual_remove_mask.size, Image.NEAREST
            )
            cut_pixels_r = np.array(cut_img) > 0
            rem[cut_pixels_r] = 255
        else:
            rem[cut_pixels] = 255
        self.manual_remove_mask = Image.fromarray(rem.astype(np.uint8), mode='L')
        self.current_mask = self.manual_remove_mask

        # Keep auto_mask in sync for immediate redisplay without full redetect:
        # do not modify auto_mask permanently; remove_mask is the source of truth.
        logger.info(
            f"Split cell at ({x},{y}): area={blob_area}, cut_pixels={int(cut_pixels.sum())}, "
            f"components_after={n_after}"
        )

        # Refresh overlay (use cached auto_mask)
        self.show_cell_mask_threshold(calculate=False)

    def stop_mask_edit(self, event=None):
        """Exit mask editing mode (add / remove / split)."""
        if not self.editing_mask and not getattr(self, 'splitting_cells', False):
            return
        self.editing_mask = False
        self.splitting_cells = False
        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.unbind("<Button-2>")
        self.output.unbind("<B2-Motion>")
        self.output.unbind("<ButtonRelease-2>")
        self.output.unbind("<Button-3>")
        self.output.unbind("<B3-Motion>")
        self.output.unbind("<ButtonRelease-3>")
        self.output.bind("<Button-1>", self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        logger.info("Stopped mask edit mode")
        messagebox.showinfo("Mask Editing", "Mask edits applied. You can now re-count cells.")

    # ==================================================================
    # SHARED ANALYSIS HELPERS (Smart Suggest + Measure Tune)
    # ==================================================================

    def _get_detection_float_image(self):
        """Return the float image used by blob detection (preprocess only).

        Critical for Measure Tune: LoG thresholds must be measured on the *same*
        intensity scale that feature.blob_log sees at runtime — not a separate
        percentile-stretched analysis image.
        """
        if self.original_background is None:
            return None
        bg_pil = self.original_background.convert('L')
        img = self.image_processor.preprocess_image(bg_pil)
        img = np.asarray(img, dtype=np.float64)
        if img.size == 0:
            return None
        if np.nanmax(img) > 1.5:
            img = img / 255.0
        img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
        img = np.clip(img, 0.0, None)
        return img

    def _get_preprocessed_analysis_image(self, max_side=1400, for_detection_match=False):
        """Return (img_float_01, scale_xy) for analysis.

        for_detection_match=True: same intensities as blob detection (no p1–p99 stretch).
        for_detection_match=False: robust stretch (better for Smart Suggest peak finding).

        Large images may be downsampled; scale maps analysis coords → original
        (multiply analysis x,y by scale).
        """
        if self.original_background is None:
            return None, 1.0

        if for_detection_match:
            img = self._get_detection_float_image()
            if img is None:
                return None, 1.0
            img = np.asarray(img, dtype=np.float64).copy()
        else:
            bg_pil = self.original_background.convert('L')
            img = self.image_processor.preprocess_image(bg_pil)
            img = np.asarray(img, dtype=np.float64)
            if img.size == 0:
                return None, 1.0
            if np.nanmax(img) > 1.5:
                img = img / 255.0
            p1, p99 = np.percentile(img, 1), np.percentile(img, 99)
            if p99 <= p1:
                p1, p99 = float(np.min(img)), float(np.max(img) + 1e-8)
            img = np.clip((img - p1) / (p99 - p1 + 1e-8), 0.0, 1.0)

        h, w = img.shape[:2]
        m = max(h, w)
        scale = 1.0
        if m > max_side:
            scale = m / float(max_side)
            new_w = max(32, int(round(w / scale)))
            new_h = max(32, int(round(h / scale)))
            # preserve float range when resizing
            mx = float(np.max(img)) if np.max(img) > 0 else 1.0
            img_u8 = np.clip(img / mx * 255.0, 0, 255).astype(np.uint8)
            img = np.array(
                Image.fromarray(img_u8).resize((new_w, new_h), Image.BILINEAR),
                dtype=np.float64,
            ) / 255.0 * mx
        return img, scale

    def _log_scale_space_max(self, img, min_sigma=1.0, max_sigma=15.0, num_sigma=12,
                             progress_cb=None, progress_start=0, progress_end=100):
        """Multi-scale LoG max projection (skimage blob_log normalization).

        Returns log_max (HxW), best_sigma (HxW), sigmas (1d).
        progress_cb(percent, message) is optional for UI busy indicators.
        """
        from scipy.ndimage import gaussian_laplace
        img = np.asarray(img, dtype=np.float64)
        h, w = img.shape
        if max_sigma <= min_sigma:
            max_sigma = min_sigma + 1.0
        num_sigma = int(max(3, num_sigma))
        sigmas = np.linspace(float(min_sigma), float(max_sigma), num_sigma)
        log_max = np.full((h, w), -np.inf, dtype=np.float64)
        best_sigma = np.full((h, w), sigmas[0], dtype=np.float64)
        n = len(sigmas)
        for i, s in enumerate(sigmas):
            resp = -gaussian_laplace(img, sigma=float(s)) * (float(s) ** 2)
            better = resp > log_max
            log_max[better] = resp[better]
            best_sigma[better] = float(s)
            if progress_cb is not None:
                frac = (i + 1) / float(n)
                pct = progress_start + (progress_end - progress_start) * frac
                progress_cb(pct, f"LoG scale space ({i + 1}/{n})…")
        log_max[~np.isfinite(log_max)] = 0.0
        return log_max, best_sigma, sigmas

    def _find_log_peaks(self, log_max, best_sigma, min_distance=3, threshold=None, max_peaks=5000):
        """Local maxima of LoG max-projection (candidate cell centers)."""
        if threshold is None:
            thr = float(np.percentile(log_max, 92))
            thr = max(thr, float(np.median(log_max) + 2.5 * np.std(log_max)))
            threshold = thr
        try:
            coords = feature.peak_local_max(
                log_max,
                min_distance=int(max(1, min_distance)),
                threshold_abs=float(threshold),
                exclude_border=True,
                num_peaks=int(max_peaks),
            )
        except TypeError:
            coords = feature.peak_local_max(
                log_max,
                min_distance=int(max(1, min_distance)),
                threshold_abs=float(threshold),
            )
            if coords is not None and len(coords) > max_peaks:
                vals = log_max[coords[:, 0], coords[:, 1]]
                order = np.argsort(vals)[::-1][:max_peaks]
                coords = coords[order]
        if coords is None or len(coords) == 0:
            return np.zeros((0, 2), dtype=int), np.zeros(0), np.zeros(0)
        coords = np.asarray(coords, dtype=int)
        vals = log_max[coords[:, 0], coords[:, 1]]
        sigs = best_sigma[coords[:, 0], coords[:, 1]]
        return coords, vals, sigs

    def _count_mask_objects(self, mask):
        """Connected-component count + area/circularity stats for a binary mask."""
        mask = np.asarray(mask, dtype=bool)
        empty = {
            "n": 0, "areas": np.array([]), "radii": np.array([]),
            "circularities": np.array([]), "median_area": 0.0, "median_radius": 0.0,
        }
        if mask.ndim != 2 or not mask.any():
            return empty
        lab = measure.label(mask, connectivity=2)
        props = measure.regionprops(lab)
        areas, radii, circs = [], [], []
        for p in props:
            a = float(p.area)
            if a < 2:
                continue
            areas.append(a)
            radii.append(float(np.sqrt(a / np.pi)))
            per = float(p.perimeter) if p.perimeter > 0 else 1.0
            c = float(4.0 * np.pi * a / (per * per + 1e-8))
            circs.append(min(1.5, c))
        areas = np.asarray(areas, dtype=float)
        radii = np.asarray(radii, dtype=float)
        circs = np.asarray(circs, dtype=float)
        return {
            "n": int(len(areas)),
            "areas": areas,
            "radii": radii,
            "circularities": circs,
            "median_area": float(np.median(areas)) if len(areas) else 0.0,
            "median_radius": float(np.median(radii)) if len(radii) else 0.0,
        }

    def _estimate_radius_at_point(self, img, y, x, max_r=60):
        """Estimate cell radius via refined peak + radial half-max profile."""
        h, w = img.shape
        y = int(np.clip(y, 0, h - 1))
        x = int(np.clip(x, 0, w - 1))

        win = 7
        y0, y1 = max(0, y - win), min(h, y + win + 1)
        x0, x1 = max(0, x - win), min(w, x + win + 1)
        patch = img[y0:y1, x0:x1]
        if patch.size == 0:
            return 5.0, float(img[y, x]), y, x
        ly, lx = np.unravel_index(int(np.argmax(patch)), patch.shape)
        y, x = y0 + int(ly), x0 + int(lx)
        peak = float(img[y, x])

        pad = min(max_r, 24)
        loc = img[max(0, y - pad):min(h, y + pad + 1), max(0, x - pad):min(w, x + pad + 1)]
        floor = float(np.percentile(loc, 15)) if loc.size else 0.0
        thresh = floor + 0.5 * max(1e-6, peak - floor)

        r_limit = int(min(max_r, h // 3, w // 3, max(10, max_r)))
        radii = np.arange(1, r_limit + 1, dtype=float)
        profile = []
        for r in radii:
            n_ang = max(16, int(r * 4))
            angs = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
            vals = []
            for a in angs:
                yy = int(round(y + r * np.sin(a)))
                xx = int(round(x + r * np.cos(a)))
                if 0 <= yy < h and 0 <= xx < w:
                    vals.append(float(img[yy, xx]))
            profile.append(np.mean(vals) if vals else floor)

        profile = np.asarray(profile, dtype=float)
        below = np.where(profile < thresh)[0]
        if len(below):
            found_r = float(radii[below[0]])
        else:
            d = np.diff(profile, prepend=profile[0])
            found_r = float(radii[int(np.argmin(d))]) if len(d) else 5.0

        found_r = float(np.clip(found_r, 2.0, float(r_limit)))
        return found_r, peak, y, x

    def _log_response_at(self, img, y, x, sigma):
        """Scale-normalized LoG response at a point (local 3x3 max)."""
        from scipy.ndimage import gaussian_laplace
        try:
            log_img = -gaussian_laplace(img, sigma=float(sigma)) * (float(sigma) ** 2)
            h, w = log_img.shape
            y = int(np.clip(y, 0, h - 1))
            x = int(np.clip(x, 0, w - 1))
            y0, y1 = max(0, y - 1), min(h, y + 2)
            x0, x1 = max(0, x - 1), min(w, x + 2)
            return float(np.max(log_img[y0:y1, x0:x1]))
        except Exception:
            yy = int(np.clip(y, 0, img.shape[0] - 1))
            xx = int(np.clip(x, 0, img.shape[1] - 1))
            return float(img[yy, xx])

    def _best_sigma_at_point(self, img, y, x, sigma_candidates):
        """Sigma maximizing LoG response at the point."""
        best_s, best_r = float(sigma_candidates[0]), -1e18
        for s in sigma_candidates:
            r = self._log_response_at(img, y, x, s)
            if r > best_r:
                best_r, best_s = r, float(s)
        return float(best_s), float(best_r)

    def _measure_point_features(self, img, x, y, probe_sigmas=None):
        """Feature vector for a click: radius, sigma, LoG, intensity, SNR, area."""
        h, w = img.shape
        r, peak, yy, xx = self._estimate_radius_at_point(img, y, x)
        if probe_sigmas is None:
            s0 = max(1.0, r / 1.8)
            probe_sigmas = np.unique(np.round(np.linspace(max(0.8, s0 * 0.4), s0 * 2.2, 16), 2))
        s_best, log_r = self._best_sigma_at_point(img, yy, xx, probe_sigmas)
        sigma = 0.5 * max(1.0, r / 1.8) + 0.5 * s_best

        pad = int(max(8, min(40, r * 3)))
        y0, y1 = max(0, yy - pad), min(h, yy + pad + 1)
        x0, x1 = max(0, xx - pad), min(w, xx + pad + 1)
        loc = img[y0:y1, x0:x1]
        floor = float(np.percentile(loc, 20)) if loc.size else 0.0
        noise = float(np.std(loc)) if loc.size > 4 else 0.05
        snr = (peak - floor) / (noise + 1e-6)

        thr = floor + 0.4 * max(1e-6, peak - floor)
        local_bin = loc >= thr
        cy_l, cx_l = yy - y0, xx - x0
        if local_bin.any() and 0 <= cy_l < local_bin.shape[0] and 0 <= cx_l < local_bin.shape[1]:
            lab = measure.label(local_bin, connectivity=2)
            cid = lab[cy_l, cx_l]
            area = float(np.sum(lab == cid)) if cid > 0 else float(np.pi * r * r)
        else:
            area = float(np.pi * r * r)

        return {
            "x": int(xx), "y": int(yy),
            "radius": float(r),
            "sigma": float(sigma),
            "log_response": float(log_r),
            "peak": float(peak),
            "snr": float(snr),
            "area": float(max(3.0, area)),
            "floor": float(floor),
        }

    def _calibrate_blob_threshold(self, cell_logs, bg_logs, recall_bias=True):
        """Choose LoG threshold separating cell vs non-cell sample responses.

        Strongly biased toward *recall* (catching all sample cells, and dimmer
        cells like them). Previous scoring was too aggressive and undercounted.
        """
        cell_logs = np.asarray(cell_logs, dtype=float)
        bg_logs = np.asarray(bg_logs, dtype=float)
        if cell_logs.size == 0:
            return 0.05

        c_min = float(np.min(cell_logs))
        c_med = float(np.median(cell_logs))
        b_max = float(np.max(bg_logs)) if bg_logs.size else 0.0
        b_p90 = float(np.percentile(bg_logs, 90)) if bg_logs.size else 0.0

        # Primary strategy: sit well below the weakest sample cell, just above background.
        # Dimmer-than-sample cells need headroom → use a low fraction of c_min.
        if c_min > b_max and (c_min - b_max) > 1e-9:
            # Only 15–25% of the way from bg to weakest cell (was ~40% before → too high)
            thr = b_max + 0.18 * (c_min - b_max)
            # Never higher than 45% of weakest cell LoG
            thr = min(thr, c_min * 0.45)
        elif c_min > b_p90:
            thr = b_p90 + 0.12 * (c_min - b_p90)
            thr = min(thr, c_min * 0.4)
        else:
            # Overlap / noisy samples: go well below median cell response
            thr = min(c_min * 0.35, c_med * 0.25)

        # Optional search that *requires* all sample cells to pass (recall first)
        if recall_bias and cell_logs.size:
            candidates = np.unique(np.concatenate([
                [thr, c_min * 0.25, c_min * 0.35, c_min * 0.45, c_min * 0.55,
                 c_med * 0.2, c_med * 0.3, max(1e-6, b_max * 1.05), max(1e-6, b_p90 * 1.1)],
                np.linspace(max(1e-6, b_max * 0.5), max(c_min, c_med) * 0.8, 25),
            ]))
            candidates = candidates[np.isfinite(candidates) & (candidates > 0)]
            best_thr, best_score = thr, -1e18
            for t in candidates:
                cell_hit = float(np.mean(cell_logs >= t))
                bg_hit = float(np.mean(bg_logs >= t)) if bg_logs.size else 0.0
                if cell_hit < 1.0:
                    # Heavily penalize missing even one sample cell
                    score = 3.0 * cell_hit - 1.0 * bg_hit - 2.0
                else:
                    # All samples kept: prefer lower false positives, but still
                    # prefer lower thresholds slightly (more room for dim cells)
                    score = 3.0 - 0.8 * bg_hit - 0.15 * (t / (c_med + 1e-8))
                if score > best_score:
                    best_score, best_thr = score, float(t)
            thr = best_thr

        # Map large absolute LoG magnitudes into blob_log's typical operating range
        scale_ref = max(float(np.percentile(np.abs(cell_logs), 75)), 1e-6)
        if thr > 0.5:
            thr = thr / scale_ref * 0.08
        # Prefer sensitive defaults (skimage default is 0.2; we aim lower)
        thr = float(np.clip(thr, 0.008, 0.25))
        return thr

    def _derive_blob_settings_from_features(self, cell_feats, bg_feats, cell_pts=None):
        """Turn measured sample features into a coherent blob settings dict.

        Biased toward higher recall so Measure Tune does not systematically undercount.
        """
        if not cell_feats:
            return None

        sigmas = np.array([f["sigma"] for f in cell_feats], dtype=float)
        radii = np.array([f["radius"] for f in cell_feats], dtype=float)
        # Prefer geometric disk area from radius (local flood-fill area often overestimates)
        geo_areas = np.pi * (radii ** 2)
        flood_areas = np.array([f["area"] for f in cell_feats], dtype=float)
        # Use the smaller of geometric vs flood so min_area is not inflated
        areas = np.minimum(geo_areas, flood_areas)
        cell_logs = np.array([f["log_response"] for f in cell_feats], dtype=float)
        bg_logs = np.array([f["log_response"] for f in bg_feats], dtype=float) if bg_feats else np.array([0.0])
        cell_snr = np.array([f["snr"] for f in cell_feats], dtype=float)

        s_lo = float(np.min(sigmas))
        s_hi = float(np.max(sigmas))
        # Wide sigma range so slightly smaller/larger cells still match
        blob_min_sigma = max(0.6, round(s_lo * 0.50, 2))
        blob_max_sigma = max(blob_min_sigma + 1.5, round(s_hi * 1.80, 2))
        blob_max_sigma = min(50.0, blob_max_sigma)
        span = blob_max_sigma - blob_min_sigma
        blob_num_sigma = int(np.clip(int(round(span * 2.8)) + 10, 12, 32))

        blob_threshold = self._calibrate_blob_threshold(cell_logs, bg_logs, recall_bias=True)

        med_snr = float(np.median(cell_snr)) if cell_snr.size else 3.0
        # Low SNR → more sensitive (lower threshold)
        if med_snr < 3.0:
            blob_threshold = max(0.008, round(blob_threshold * 0.75, 4))

        # min area from smallest sample, with generous headroom for smaller real cells
        a_min = float(np.min(areas)) if areas.size else 15.0
        a_max = float(np.max(areas)) if areas.size else 300.0
        blob_min_area = int(max(3, round(a_min * 0.25)))
        blob_max_area = int(max(blob_min_area + 20, round(a_max * 2.5)))
        blob_max_area = int(min(100000, blob_max_area))

        blob_overlap = 0.55  # slightly more permissive default
        pts = cell_pts if cell_pts is not None else [(f["x"], f["y"]) for f in cell_feats]
        if len(pts) >= 2:
            P = np.asarray(pts, dtype=float)
            nn = []
            for i in range(len(P)):
                d = np.sqrt(np.sum((P - P[i]) ** 2, axis=1))
                d[i] = np.inf
                nn.append(np.min(d))
            med_nn = float(np.median(nn))
            med_r = float(np.median(radii))
            if med_r > 0:
                if med_nn < 2.5 * med_r:
                    blob_overlap = 0.75
                elif med_nn < 3.5 * med_r:
                    blob_overlap = 0.65
                elif med_nn > 7 * med_r:
                    blob_overlap = 0.4

        # Note: circularity is not applied in the current blob drawing path, but keep mild
        blob_min_circularity = 0.4

        cell_keep = float(np.mean(cell_logs >= blob_threshold)) if cell_logs.size else 0.0
        bg_keep = float(np.mean(bg_logs >= blob_threshold)) if bg_logs.size else 0.0

        return {
            "detection_method": "blob",
            "blob_min_sigma": blob_min_sigma,
            "blob_max_sigma": blob_max_sigma,
            "blob_num_sigma": blob_num_sigma,
            "blob_threshold": float(blob_threshold),
            "blob_overlap": float(blob_overlap),
            "blob_min_area": blob_min_area,
            "blob_max_area": blob_max_area,
            "blob_min_circularity": float(blob_min_circularity),
            "min_cell_size": max(3, blob_min_area),
            "max_cell_size": max(blob_min_area + 10, blob_max_area),
            "_diagnostics": {
                "cell_radii": radii.tolist(),
                "cell_sigmas": sigmas.tolist(),
                "cell_logs": cell_logs.tolist(),
                "bg_logs": bg_logs.tolist(),
                "cell_keep_frac": cell_keep,
                "bg_keep_frac": bg_keep,
                "median_snr": med_snr,
            },
        }

    def _blob_log_sample_recovery(self, img, cell_xy, settings, max_match_factor=1.5):
        """Fraction of sample cell clicks that have a blob_log hit nearby.

        Uses the real skimage blob_log path (same as detection).
        cell_xy: list of (x, y) in the *same* coordinate system as img.
        """
        if img is None or not cell_xy:
            return 0.0, 0
        try:
            blobs = feature.blob_log(
                img,
                min_sigma=float(settings["blob_min_sigma"]),
                max_sigma=float(settings["blob_max_sigma"]),
                num_sigma=int(settings["blob_num_sigma"]),
                threshold=float(settings["blob_threshold"]),
                overlap=float(settings.get("blob_overlap", 0.5)),
                log_scale=False,
            )
        except Exception as e:
            logger.debug(f"blob_log recovery check failed: {e}")
            return 0.0, 0

        if blobs is None or len(blobs) == 0:
            return 0.0, 0

        recovered = 0
        min_area = int(settings.get("blob_min_area", 0))
        max_area = int(settings.get("blob_max_area", 10**9))
        for (x, y) in cell_xy:
            hit = False
            for by, bx, sig in blobs:
                radius = float(sig) * 1.8
                area = int(np.pi * radius * radius)
                if area < min_area or area > max_area:
                    continue
                max_dist = max(radius * max_match_factor, 6.0)
                if (float(by) - float(y)) ** 2 + (float(bx) - float(x)) ** 2 <= max_dist ** 2:
                    hit = True
                    break
            if hit:
                recovered += 1
        return recovered / float(len(cell_xy)), len(blobs)

    def _retune_threshold_for_sample_recovery(self, img, cell_xy, settings, min_recovery=1.0):
        """Lower blob_threshold until sample cells are recovered by real blob_log.

        This is the main fix for Measure Tune undercounting: LoG-at-point scores
        alone do not guarantee blob_log will detect those cells.
        """
        thr0 = float(settings["blob_threshold"])
        recovery, nblobs = self._blob_log_sample_recovery(img, cell_xy, settings)
        settings["_diagnostics"]["blob_log_recovery_before"] = recovery
        settings["_diagnostics"]["blob_log_n_before"] = nblobs

        if recovery >= min_recovery:
            settings["_diagnostics"]["blob_log_recovery"] = recovery
            settings["_diagnostics"]["blob_log_n"] = nblobs
            return settings

        # Try progressively lower thresholds
        best = dict(settings)
        best_rec = recovery
        for factor in (0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.12, 0.08):
            t = max(0.005, thr0 * factor)
            trial = dict(settings)
            trial["blob_threshold"] = t
            rec, nb = self._blob_log_sample_recovery(img, cell_xy, trial)
            if rec > best_rec or (rec >= min_recovery and t < best["blob_threshold"]):
                best = trial
                best_rec = rec
                best["_diagnostics"] = dict(settings.get("_diagnostics") or {})
                best["_diagnostics"]["blob_log_recovery"] = rec
                best["_diagnostics"]["blob_log_n"] = nb
                best["_diagnostics"]["blob_threshold_retuned_from"] = thr0
            if rec >= min_recovery:
                break

        # If still missing samples, also relax min_area once
        if best_rec < min_recovery:
            trial = dict(best)
            trial["blob_min_area"] = max(3, int(best["blob_min_area"] * 0.5))
            trial["blob_threshold"] = max(0.005, float(best["blob_threshold"]) * 0.7)
            rec, nb = self._blob_log_sample_recovery(img, cell_xy, trial)
            if rec >= best_rec:
                best = trial
                best["_diagnostics"] = dict(settings.get("_diagnostics") or {})
                best["_diagnostics"]["blob_log_recovery"] = rec
                best["_diagnostics"]["blob_log_n"] = nb
                best["_diagnostics"]["relaxed_min_area"] = True

        return best

    def _apply_blob_settings_dict(self, settings):
        """Apply a settings dict onto cell_config (ignores keys starting with _)."""
        cfg = self.image_processor.cell_config
        for k, v in settings.items():
            if k.startswith("_"):
                continue
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    # ==================================================================
    # MEASURE TUNE — sample 5 cells + 5 non-cells → informed blob settings
    # ==================================================================

    def start_measure_tune(self, mask_settings_window=None):
        """Interactive Measure Tune: pick 5 cells + 5 non-cells, derive blob params."""
        if self.original_background is None and self.background_image is None:
            messagebox.showerror("Measure Tune", "Please import a TIFF image first.")
            return

        if getattr(self, 'splitting_cells', False) or getattr(self, 'editing_mask', False):
            self.splitting_cells = False
            self.editing_mask = False

        self.measure_tune_settings_geometry = None
        if mask_settings_window is not None:
            try:
                self.measure_tune_settings_geometry = mask_settings_window.geometry()
                mask_settings_window.destroy()
            except Exception:
                pass

        try:
            # Match detection intensities (no p1–p99 stretch). Mild downsample only if huge.
            img, scale = self._get_preprocessed_analysis_image(
                max_side=2200, for_detection_match=True
            )
            if img is None:
                raise RuntimeError("No image")
            self._measure_tune_img = img
            self._measure_tune_scale = scale
        except Exception as e:
            messagebox.showerror("Measure Tune", f"Could not prepare image for analysis:\n{e}")
            return

        self.measure_tune_active = True
        self.measure_tune_phase = 'cells'
        self.measure_tune_cell_points = []
        self.measure_tune_bg_points = []
        self.measure_tune_cell_feats = []
        self.measure_tune_bg_feats = []
        self._clear_measure_tune_markers()

        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.bind("<Button-1>", self._measure_tune_click)
        self.master.bind("<Escape>", self._cancel_measure_tune)

        self._open_measure_tune_status_window()
        self._update_measure_tune_status()
        try:
            self.show_page()
        except Exception:
            pass

        messagebox.showinfo(
            "Measure Tune",
            "How to use Measure Tune:\n\n"
            "1. Click the CENTER of 5 real cells (spots you want counted).\n"
            "2. Then click 5 NON-cell areas (background, fibers, debris).\n\n"
            "Tips:\n"
            "• Prefer typical cells, not only the brightest outliers.\n"
            "• For non-cells, include the brightest confusing junk.\n"
            "• Use Undo last if you mis-click.\n"
            "• Esc cancels without changing settings.\n\n"
            "BARCC measures size, brightness, and LoG response at each click\n"
            "and sets blob parameters so cells pass and non-cells fail.",
        )

    def _open_measure_tune_status_window(self):
        try:
            if self.measure_tune_status_window is not None and self.measure_tune_status_window.winfo_exists():
                self.measure_tune_status_window.destroy()
        except Exception:
            pass

        win = Toplevel(self.master)
        self.measure_tune_status_window = win
        win.title("Measure Tune")
        win.attributes('-topmost', 'true')
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._cancel_measure_tune)
        self._register_transparent_window(win)

        self.measure_tune_status_var = tk.StringVar(value="Click CELL 1 of 5")
        ttk.Label(win, textvariable=self.measure_tune_status_var, font=("Helvetica", 11, "bold")).pack(
            padx=16, pady=(12, 4)
        )
        self.measure_tune_detail_var = tk.StringVar(value="Green = cells · Red = non-cells")
        ttk.Label(
            win, textvariable=self.measure_tune_detail_var, font=("Helvetica", 8), justify=tk.CENTER
        ).pack(padx=16, pady=(0, 6))

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=(0, 10))
        ttk.Button(btn_row, text="Undo last", command=self._measure_tune_undo_last, width=12).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_row, text="Cancel", command=self._cancel_measure_tune, width=10).pack(
            side=tk.LEFT, padx=4
        )

        try:
            win.update_idletasks()
            mx = self.master.winfo_rootx() + max(40, self.master.winfo_width() - 300)
            my = self.master.winfo_rooty() + 80
            win.geometry(f"+{mx}+{my}")
        except Exception:
            pass

    def _update_measure_tune_status(self):
        if not getattr(self, 'measure_tune_status_var', None):
            return
        if self.measure_tune_phase == 'cells':
            n = len(self.measure_tune_cell_points)
            self.measure_tune_status_var.set(f"Click CELL {n + 1} of 5")
            last = ""
            if self.measure_tune_cell_feats:
                f = self.measure_tune_cell_feats[-1]
                last = f"Last cell: r≈{f['radius']:.1f}px  SNR={f['snr']:.1f}  LoG={f['log_response']:.4f}"
            self.measure_tune_detail_var.set(last or "Click near the center of each cell")
        elif self.measure_tune_phase == 'background':
            n = len(self.measure_tune_bg_points)
            self.measure_tune_status_var.set(f"Click NON-CELL {n + 1} of 5")
            last = ""
            if self.measure_tune_bg_feats:
                f = self.measure_tune_bg_feats[-1]
                last = f"Last non-cell: peak={f['peak']:.3f}  LoG={f['log_response']:.4f}"
            self.measure_tune_detail_var.set(last or "Click background / junk / fibers")
        else:
            self.measure_tune_status_var.set("Done")

    def _clear_measure_tune_markers(self):
        for item in getattr(self, 'measure_tune_markers', []) or []:
            try:
                self.output.delete(item)
            except Exception:
                pass
        self.measure_tune_markers = []

    def _draw_measure_tune_marker(self, ix, iy, kind='cell', index=None):
        try:
            cx, cy = self._image_to_canvas(ix, iy)
            r = 9
            color = '#00cc44' if kind == 'cell' else '#e02020'
            oval = self.output.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=color, width=2, tags=('measure_tune_marker',),
            )
            cross1 = self.output.create_line(
                cx - 5, cy, cx + 5, cy, fill=color, width=2, tags=('measure_tune_marker',),
            )
            cross2 = self.output.create_line(
                cx, cy - 5, cx, cy + 5, fill=color, width=2, tags=('measure_tune_marker',),
            )
            self.measure_tune_markers.extend([oval, cross1, cross2])
            if index is not None:
                txt = self.output.create_text(
                    cx + 12, cy - 12, text=str(index), fill=color,
                    font=("Helvetica", 9, "bold"), tags=('measure_tune_marker',),
                )
                self.measure_tune_markers.append(txt)
        except Exception as e:
            logger.debug(f"Measure tune marker draw failed: {e}")

    def _orig_to_analysis_xy(self, x, y):
        scale = float(getattr(self, '_measure_tune_scale', 1.0) or 1.0)
        return x / scale, y / scale

    def _measure_tune_click(self, event):
        if not getattr(self, 'measure_tune_active', False):
            return

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_image(cx, cy)

        if self.original_background is not None:
            w, h = self.original_background.size
        else:
            w, h = self.background_image.size
        x, y = int(round(ix)), int(round(iy))
        if x < 0 or y < 0 or x >= w or y >= h:
            return

        img = getattr(self, '_measure_tune_img', None)
        if img is None:
            return
        ax, ay = self._orig_to_analysis_xy(x, y)

        try:
            feat = self._measure_point_features(img, ax, ay)
            scale = float(getattr(self, '_measure_tune_scale', 1.0) or 1.0)
            feat["x_orig"] = int(round(feat["x"] * scale))
            feat["y_orig"] = int(round(feat["y"] * scale))
            feat["radius"] = float(feat["radius"] * scale)
            feat["sigma"] = float(feat["sigma"] * scale)
            feat["area"] = float(feat["area"] * (scale ** 2))
        except Exception as e:
            logger.warning(f"Measure tune sample failed: {e}")
            messagebox.showwarning("Measure Tune", f"Could not measure that point:\n{e}")
            return

        if self.measure_tune_phase == 'cells':
            self.measure_tune_cell_points.append((feat["x_orig"], feat["y_orig"]))
            self.measure_tune_cell_feats.append(feat)
            self._draw_measure_tune_marker(
                feat["x_orig"], feat["y_orig"], kind='cell',
                index=len(self.measure_tune_cell_points),
            )
            if len(self.measure_tune_cell_points) >= 5:
                self.measure_tune_phase = 'background'
                messagebox.showinfo(
                    "Measure Tune",
                    "Cell samples complete (5/5).\n\n"
                    "Now click 5 NON-cell regions.\n"
                    "Include the brightest confusing background if possible.",
                )
        elif self.measure_tune_phase == 'background':
            self.measure_tune_bg_points.append((feat["x_orig"], feat["y_orig"]))
            self.measure_tune_bg_feats.append(feat)
            self._draw_measure_tune_marker(
                feat["x_orig"], feat["y_orig"], kind='bg',
                index=len(self.measure_tune_bg_points),
            )
            if len(self.measure_tune_bg_points) >= 5:
                self._finish_measure_tune()
                return

        self._update_measure_tune_status()

    def _measure_tune_undo_last(self):
        if not getattr(self, 'measure_tune_active', False):
            return
        if self.measure_tune_phase == 'background' and self.measure_tune_bg_points:
            self.measure_tune_bg_points.pop()
            if self.measure_tune_bg_feats:
                self.measure_tune_bg_feats.pop()
        elif self.measure_tune_phase == 'background' and not self.measure_tune_bg_points:
            if self.measure_tune_cell_points:
                self.measure_tune_phase = 'cells'
                self.measure_tune_cell_points.pop()
                if self.measure_tune_cell_feats:
                    self.measure_tune_cell_feats.pop()
        elif self.measure_tune_phase == 'cells' and self.measure_tune_cell_points:
            self.measure_tune_cell_points.pop()
            if self.measure_tune_cell_feats:
                self.measure_tune_cell_feats.pop()

        self._clear_measure_tune_markers()
        for i, (x, y) in enumerate(self.measure_tune_cell_points, 1):
            self._draw_measure_tune_marker(x, y, kind='cell', index=i)
        for i, (x, y) in enumerate(self.measure_tune_bg_points, 1):
            self._draw_measure_tune_marker(x, y, kind='bg', index=i)
        self._update_measure_tune_status()

    def _cancel_measure_tune(self, event=None):
        if not getattr(self, 'measure_tune_active', False):
            return "break" if event else None
        self._cleanup_measure_tune_ui()
        messagebox.showinfo("Measure Tune", "Cancelled. Blob settings were not changed.")
        try:
            self.show_mask_settings(restore_geometry=self.measure_tune_settings_geometry)
        except Exception:
            pass
        return "break" if event else None

    def _cleanup_measure_tune_ui(self):
        self.measure_tune_active = False
        self.measure_tune_phase = None
        try:
            self.master.unbind("<Escape>")
        except Exception:
            pass
        try:
            self.output.unbind("<Button-1>")
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        except Exception:
            pass
        self._clear_measure_tune_markers()
        try:
            if self.measure_tune_status_window is not None and self.measure_tune_status_window.winfo_exists():
                self.measure_tune_status_window.destroy()
        except Exception:
            pass
        self.measure_tune_status_window = None
        self._measure_tune_img = None

    def _finish_measure_tune(self):
        """Derive and apply blob settings from collected samples."""
        cell_feats = list(getattr(self, 'measure_tune_cell_feats', []) or [])
        bg_feats = list(getattr(self, 'measure_tune_bg_feats', []) or [])
        cell_pts = list(self.measure_tune_cell_points)
        self._cleanup_measure_tune_ui()

        if len(cell_feats) < 5 or len(bg_feats) < 5:
            messagebox.showwarning("Measure Tune", "Not enough samples collected.")
            try:
                self.show_mask_settings(restore_geometry=self.measure_tune_settings_geometry)
            except Exception:
                pass
            return

        settings = self._derive_blob_settings_from_features(cell_feats, bg_feats, cell_pts=cell_pts)
        if not settings:
            messagebox.showerror("Measure Tune", "Failed to derive settings from samples.")
            return

        # Second-pass: remeasure LoG on detection-matched image + verify with real blob_log
        try:
            img, scale = self._get_preprocessed_analysis_image(
                max_side=2200, for_detection_match=True
            )
            if img is not None:
                smin = max(0.5, settings["blob_min_sigma"] / scale)
                smax = max(smin + 0.5, settings["blob_max_sigma"] / scale)
                probe = np.unique(np.round(np.linspace(smin, smax, 16), 2))
                cell_logs2, bg_logs2 = [], []
                for f in cell_feats:
                    ax, ay = f["x_orig"] / scale, f["y_orig"] / scale
                    _, lr = self._best_sigma_at_point(img, ay, ax, probe)
                    cell_logs2.append(lr)
                for f in bg_feats:
                    ax, ay = f["x_orig"] / scale, f["y_orig"] / scale
                    _, lr = self._best_sigma_at_point(img, ay, ax, probe)
                    bg_logs2.append(lr)

                thr2 = self._calibrate_blob_threshold(cell_logs2, bg_logs2, recall_bias=True)
                settings["blob_threshold"] = thr2
                # Sigma already in original px; when measuring on downsampled img, detection
                # uses full-res image so keep original-space sigma from features.
                settings["_diagnostics"]["cell_logs"] = cell_logs2
                settings["_diagnostics"]["bg_logs"] = bg_logs2
                settings["_diagnostics"]["cell_keep_frac"] = float(
                    np.mean(np.array(cell_logs2) >= settings["blob_threshold"])
                )
                settings["_diagnostics"]["bg_keep_frac"] = float(
                    np.mean(np.array(bg_logs2) >= settings["blob_threshold"])
                )

                # Critical: retune with actual blob_log so sample cells are recovered.
                # Use full-resolution detection image + original coordinates.
                det_img = self._get_detection_float_image()
                cell_xy = [(f["x_orig"], f["y_orig"]) for f in cell_feats]
                # blob_log expects (row, col) internally; we pass xy and convert in recovery
                # Recovery uses (x,y) as col,row — convert list to (x,y) and match as (bx,by)=(col,row)
                if det_img is not None:
                    # settings sigma/area are in original pixels; det_img is full res — good
                    settings = self._retune_threshold_for_sample_recovery(
                        det_img, cell_xy, settings, min_recovery=1.0
                    )
        except Exception as e:
            logger.warning(f"Measure tune second-pass calibration issue: {e}", exc_info=True)

        self._apply_blob_settings_dict(settings)
        diag = settings.get("_diagnostics", {})

        logger.info(
            "Measure Tune applied: sigma=[%.2f, %.2f] n=%d thr=%.4f area=[%d, %d] "
            "cell_keep=%.0f%% bg_keep=%.0f%% blob_recovery=%.0f%%",
            settings["blob_min_sigma"], settings["blob_max_sigma"], settings["blob_num_sigma"],
            settings["blob_threshold"], settings["blob_min_area"], settings["blob_max_area"],
            100 * diag.get("cell_keep_frac", 0), 100 * diag.get("bg_keep_frac", 0),
            100 * diag.get("blob_log_recovery", diag.get("cell_keep_frac", 0)),
        )

        radii = diag.get("cell_radii") or [f["radius"] for f in cell_feats]
        rec = diag.get("blob_log_recovery")
        rec_txt = f"{100 * rec:.0f}%" if rec is not None else "n/a"
        summary = (
            "Measure Tune complete — blob settings updated (recall-biased).\n\n"
            f"Sigma range: {settings['blob_min_sigma']} – {settings['blob_max_sigma']}  "
            f"({settings['blob_num_sigma']} steps)\n"
            f"Threshold: {settings['blob_threshold']}\n"
            f"Area range: {settings['blob_min_area']} – {settings['blob_max_area']} px\n"
            f"Overlap: {settings['blob_overlap']}\n\n"
            f"Sample cell radii (px): " + ", ".join(f"{r:.1f}" for r in radii) + "\n"
            f"Validation:\n"
            f"  Sample cells recovered by blob_log: {rec_txt}\n"
            f"  LoG threshold keeps sample cells: {100 * diag.get('cell_keep_frac', 0):.0f}%\n"
            f"  Non-cells above threshold: {100 * diag.get('bg_keep_frac', 0):.0f}%\n"
            f"  Median cell SNR: {diag.get('median_snr', 0):.1f}\n\n"
            "Mask will refresh and Mask Settings will reopen."
        )
        messagebox.showinfo("Measure Tune Results", summary)

        try:
            self.show_cell_mask_threshold(calculate=True)
        except Exception as e:
            logger.warning(f"Measure Tune mask refresh failed: {e}")
        try:
            self.show_mask_settings(restore_geometry=self.measure_tune_settings_geometry)
        except Exception:
            pass

    # ==================================================================
    # SMART SUGGEST — multi-scale LoG analysis of the whole image
    # ==================================================================

    def _analyze_current_detection(self, progress=None):
        """Analyze image + current detection; propose coordinated blob settings.

        Improvements:
        - Counts real objects (connected components), not mask pixels
        - Multi-scale LoG peak discovery for natural cell scale / density
        - Detects under- and over-detection relative to LoG evidence
        - Suggests coherent parameter groups

        progress: optional busy dialog with .set_progress(percent, message)
        """
        def _prog(pct, msg=None):
            if progress is None:
                return
            try:
                progress.set_progress(pct, msg)
            except Exception:
                pass

        if self.original_background is None:
            return None

        cfg = self.image_processor.cell_config
        pcfg = self.image_processor.preprocess_config

        _prog(5, "Preparing preprocessed image…")
        img, scale = self._get_preprocessed_analysis_image(max_side=1200)
        if img is None:
            return None
        h, w = img.shape
        mp = (h * w) / 1_000_000.0
        orig_mp = (self.original_background.size[0] * self.original_background.size[1]) / 1e6

        _prog(15, "Running current cell detection…")
        try:
            bg = self.original_background.convert('L')
            _, auto_labels = binary_mask_cell_count(bg, processor=self.image_processor)
            current_mask = np.asarray(auto_labels, dtype=bool).squeeze()
        except Exception as e:
            logger.error(f"Analysis failed during detection: {e}")
            return None

        _prog(35, "Measuring detected objects…")
        obj = self._count_mask_objects(current_mask)
        n_det = obj["n"]
        density = n_det / max(orig_mp, 1e-6)

        smin = max(0.8, float(cfg.blob_min_sigma) / scale * 0.7)
        smax = max(smin + 1.0, float(cfg.blob_max_sigma) / scale * 1.2)
        smax = min(smax, 25.0)
        _prog(40, "Building multi-scale LoG…")
        log_max, best_sigma, _sigmas = self._log_scale_space_max(
            img, min_sigma=smin, max_sigma=smax, num_sigma=12,
            progress_cb=_prog, progress_start=40, progress_end=75,
        )

        _prog(78, "Finding LoG peaks…")
        log_bg = float(np.median(log_max))
        log_mad = float(np.median(np.abs(log_max - log_bg))) + 1e-8
        peak_thr_strict = log_bg + 6.0 * 1.4826 * log_mad
        peak_thr_loose = log_bg + 3.5 * 1.4826 * log_mad

        typ_r_an = max(2.0, (obj["median_radius"] / scale) if obj["median_radius"] > 0 else 4.0)
        min_dist = max(2, int(typ_r_an * 0.8))

        coords_s, vals_s, sigs_s = self._find_log_peaks(
            log_max, best_sigma, min_distance=min_dist, threshold=peak_thr_strict, max_peaks=4000
        )
        coords_l, vals_l, _sigs_l = self._find_log_peaks(
            log_max, best_sigma, min_distance=min_dist, threshold=peak_thr_loose, max_peaks=6000
        )
        n_peaks_strict = len(coords_s)
        n_peaks_loose = len(coords_l)

        if n_peaks_strict > 0:
            cy, cx = coords_s[:, 0], coords_s[:, 1]
            cell_int = img[cy, cx]
            flat = log_max.ravel()
            thr_bg = float(np.percentile(flat, 40))
            bg_idx = np.where(flat <= thr_bg)[0]
            if len(bg_idx) > 2000:
                bg_idx = np.random.choice(bg_idx, 2000, replace=False)
            bg_vals = img.ravel()[bg_idx] if len(bg_idx) else np.array([0.0])
            mean_cell = float(np.mean(cell_int))
            mean_bg = float(np.mean(bg_vals))
            contrast = mean_cell - mean_bg
            snr = contrast / (float(np.std(bg_vals)) + 1e-6)
        else:
            contrast = snr = 0.0

        if n_peaks_strict > 0:
            peak_sigmas_orig = sigs_s * scale
            peak_radii_orig = peak_sigmas_orig * 1.8
            peak_areas = np.pi * (peak_radii_orig ** 2)
            prop_min_sigma = max(0.8, float(np.percentile(peak_sigmas_orig, 10)) * 0.75)
            prop_max_sigma = max(prop_min_sigma + 1.0, float(np.percentile(peak_sigmas_orig, 90)) * 1.4)
            prop_min_area = int(max(4, round(float(np.percentile(peak_areas, 10)) * 0.5)))
            prop_max_area = int(max(prop_min_area + 12, round(float(np.percentile(peak_areas, 90)) * 1.8)))
        elif obj["n"] > 0:
            prop_min_sigma = max(0.8, obj["median_radius"] / 1.8 * 0.6)
            prop_max_sigma = max(prop_min_sigma + 1.0, obj["median_radius"] / 1.8 * 1.8)
            prop_min_area = int(max(4, round(obj["median_area"] * 0.4)))
            prop_max_area = int(max(prop_min_area + 12, round(obj["median_area"] * 2.5)))
        else:
            prop_min_sigma, prop_max_sigma = 1.5, 8.0
            prop_min_area, prop_max_area = 12, 400

        prop_min_sigma = round(float(prop_min_sigma), 2)
        prop_max_sigma = round(float(min(40.0, prop_max_sigma)), 2)
        prop_num_sigma = int(np.clip(int(round((prop_max_sigma - prop_min_sigma) * 2.2)) + 8, 10, 28))

        _prog(85, "Estimating recommended parameters…")
        if n_peaks_strict > 0:
            weak_cell = float(np.percentile(vals_s, 15))
            if n_peaks_loose > n_peaks_strict:
                noise_like = float(np.percentile(vals_l, 30))
            else:
                noise_like = float(np.percentile(log_max, 80))
            if weak_cell > noise_like:
                prop_thr = noise_like + 0.3 * (weak_cell - noise_like)
            else:
                prop_thr = weak_cell * 0.75
            if prop_thr > 0.6:
                prop_thr = prop_thr / (float(np.percentile(vals_s, 75)) + 1e-8) * 0.12
            prop_thr = float(np.clip(round(prop_thr, 4), 0.005, 0.4))
        else:
            prop_thr = max(0.03, min(0.2, float(cfg.blob_threshold)))

        _prog(92, "Building suggestions…")
        suggestions = []

        if cfg.detection_method != "blob":
            suggestions.append({
                "param": "detection_method",
                "current": cfg.detection_method,
                "suggested": "blob",
                "reason": "Blob (LoG) is better suited to round fluorescent cells than watershed for most IF images.",
                "priority": 1,
            })

        peaks_orig_est = n_peaks_strict * (orig_mp / max(mp, 1e-6))
        if peaks_orig_est > max(30, n_det * 1.8) and n_det < peaks_orig_est * 0.6:
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": min(cfg.blob_threshold, prop_thr),
                "reason": (
                    f"Under-detection likely: ~{int(peaks_orig_est)} strong LoG peaks vs "
                    f"{n_det} counted objects. Lower threshold to catch more true cells."
                ),
                "priority": 2,
            })
            if cfg.blob_min_area > prop_min_area * 1.3:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": prop_min_area,
                    "reason": "Minimum area may be excluding real smaller cells seen by LoG analysis.",
                    "priority": 3,
                })

        tiny_frac = 0.0
        if obj["n"] > 0 and len(obj["areas"]):
            tiny_frac = float(np.mean(obj["areas"] < max(8, prop_min_area * 0.5)))
        if density > 1200 or (n_det > 800 and tiny_frac > 0.35):
            new_thr = max(cfg.blob_threshold, min(0.4, max(prop_thr, cfg.blob_threshold + 0.03)))
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": round(float(new_thr), 4),
                "reason": (
                    f"Over-detection likely ({n_det} objects, {density:.0f}/MP, "
                    f"{100 * tiny_frac:.0f}% very small). Raising threshold reduces noise."
                ),
                "priority": 2,
            })
            if tiny_frac > 0.25:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": max(cfg.blob_min_area, prop_min_area),
                    "reason": "Many tiny components look like noise — raise min area to filter them.",
                    "priority": 3,
                })

        if n_peaks_strict >= 8:
            if cfg.blob_min_sigma > prop_min_sigma * 1.4 or cfg.blob_max_sigma < prop_max_sigma * 0.7:
                suggestions.append({
                    "param": "blob_min_sigma",
                    "current": cfg.blob_min_sigma,
                    "suggested": prop_min_sigma,
                    "reason": (
                        f"Cell scale from LoG peaks suggests sigma ≈ "
                        f"{prop_min_sigma}–{prop_max_sigma} (now {cfg.blob_min_sigma}–{cfg.blob_max_sigma})."
                    ),
                    "priority": 2,
                })
                suggestions.append({
                    "param": "blob_max_sigma",
                    "current": cfg.blob_max_sigma,
                    "suggested": prop_max_sigma,
                    "reason": "Expand/contract max sigma to match the measured cell size range.",
                    "priority": 2,
                })
                suggestions.append({
                    "param": "blob_num_sigma",
                    "current": cfg.blob_num_sigma,
                    "suggested": prop_num_sigma,
                    "reason": "Match number of LoG scales to the recommended sigma span.",
                    "priority": 4,
                })

        if n_peaks_strict >= 8 or obj["n"] >= 10:
            if abs(cfg.blob_min_area - prop_min_area) / max(prop_min_area, 1) > 0.4:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": prop_min_area,
                    "reason": f"Suggested min area from measured sizes ≈ {prop_min_area} px.",
                    "priority": 3,
                })
            if abs(cfg.blob_max_area - prop_max_area) / max(prop_max_area, 1) > 0.4:
                suggestions.append({
                    "param": "blob_max_area",
                    "current": cfg.blob_max_area,
                    "suggested": prop_max_area,
                    "reason": f"Suggested max area from measured sizes ≈ {prop_max_area} px.",
                    "priority": 3,
                })

        if snr > 0 and snr < 2.5:
            suggestions.append({
                "param": "preprocess_nr_gaussian",
                "current": pcfg.nr_gaussian_sigma,
                "suggested": min(2.5, round(pcfg.nr_gaussian_sigma + 0.5, 1)),
                "reason": f"Low cell/background SNR ({snr:.1f}). Mild extra smoothing can stabilize LoG peaks.",
                "priority": 3,
            })
            if getattr(pcfg, 'denoise_method', None) in (None, "none", ""):
                suggestions.append({
                    "param": "preprocess_denoise_method",
                    "current": pcfg.denoise_method,
                    "suggested": "gaussian",
                    "reason": "Enable Gaussian denoising for low-SNR immunofluorescence images.",
                    "priority": 3,
                })

        if cfg.blob_min_circularity > 0.75 and obj["n"] > 0:
            med_c = float(np.median(obj["circularities"])) if len(obj["circularities"]) else 1.0
            if med_c < cfg.blob_min_circularity:
                suggestions.append({
                    "param": "blob_min_circularity",
                    "current": cfg.blob_min_circularity,
                    "suggested": max(0.4, round(med_c * 0.85, 2)),
                    "reason": (
                        f"Detected objects have median circularity {med_c:.2f}, below your "
                        f"threshold {cfg.blob_min_circularity}. Loosen to keep real cells."
                    ),
                    "priority": 3,
                })

        if n_det < 15 and n_peaks_loose < 20 and snr < 2:
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": max(0.01, round(min(cfg.blob_threshold, prop_thr) * 0.7, 4)),
                "reason": (
                    "Very few peaks and detections with low SNR — try a more sensitive threshold, "
                    "or use Measure Tune and click example cells."
                ),
                "priority": 2,
            })

        by_param = {}
        for s in suggestions:
            p = s["param"]
            if p not in by_param or s.get("priority", 9) < by_param[p].get("priority", 9):
                by_param[p] = s
        suggestions = sorted(by_param.values(), key=lambda s: s.get("priority", 9))

        recommended_preset = {
            "detection_method": "blob",
            "blob_min_sigma": prop_min_sigma,
            "blob_max_sigma": prop_max_sigma,
            "blob_num_sigma": prop_num_sigma,
            "blob_threshold": prop_thr,
            "blob_min_area": prop_min_area,
            "blob_max_area": prop_max_area,
            "blob_overlap": 0.5,
        }

        _prog(98, "Finishing analysis…")
        return {
            "num_detections": n_det,
            "detection_density": round(density, 1),
            "log_peaks_strict": n_peaks_strict,
            "log_peaks_loose": n_peaks_loose,
            "contrast": round(contrast, 3),
            "snr": round(snr, 2),
            "median_object_area": round(obj["median_area"], 1),
            "median_object_radius": round(obj["median_radius"], 1),
            "suggested_sigma": (prop_min_sigma, prop_max_sigma),
            "suggested_threshold": prop_thr,
            "suggestions": suggestions,
            "recommended_preset": recommended_preset,
        }

    def _show_smart_suggest_dialog(self):
        """Show Smart Suggest analysis with optional apply + live mask refresh."""
        if self.original_background is None and self.background_image is None:
            messagebox.showerror(
                "Analysis Failed",
                "Could not analyze the current image. Please load an image first.",
            )
            return

        # Visible progress so the UI does not look frozen during LoG analysis
        progress = None
        analysis = None
        try:
            try:
                self.master.config(cursor="watch")
            except Exception:
                pass
            progress = self._show_busy_dialog("Smart Suggest")
            progress.set_progress(2, "Starting analysis…")
            try:
                # Force an immediate paint so the bar appears before heavy work
                if progress.window and progress.window.winfo_exists():
                    progress.window.update()
            except Exception:
                pass

            analysis = self._analyze_current_detection(progress=progress)

            if progress and not getattr(progress, 'closed', False):
                progress.set_progress(100, "Done")
        except Exception as e:
            logger.error(f"Smart Suggest failed: {e}", exc_info=True)
            analysis = None
            try:
                messagebox.showerror("Smart Suggest Failed", f"Analysis failed:\n{e}")
            except Exception:
                pass
        finally:
            try:
                self.master.config(cursor="")
            except Exception:
                pass
            if progress is not None and not getattr(progress, 'closed', False):
                try:
                    progress.close()
                except Exception:
                    pass

        if analysis is None:
            messagebox.showerror(
                "Analysis Failed",
                "Could not analyze the current image. Please load an image first.",
            )
            return

        suggestions = analysis["suggestions"]

        dialog = Toplevel(self.master)
        dialog.title("Smart Suggest")
        dialog.geometry("680x560")
        dialog.attributes('-topmost', 'true')
        self._register_transparent_window(dialog)

        ttk.Label(
            dialog,
            text="Smart Suggest — local LoG image analysis",
            font=("Helvetica", 11, "bold"),
        ).pack(pady=(10, 4))

        info = (
            f"Objects: {analysis['num_detections']}   |   "
            f"Density: {analysis['detection_density']}/MP   |   "
            f"LoG peaks: {analysis['log_peaks_strict']} strict / {analysis['log_peaks_loose']} loose\n"
            f"SNR: {analysis['snr']}   |   Contrast: {analysis['contrast']}   |   "
            f"Median size: r≈{analysis['median_object_radius']}px  area≈{analysis['median_object_area']}px\n"
            f"Suggested sigma: {analysis['suggested_sigma'][0]}–{analysis['suggested_sigma'][1]}   "
            f"threshold≈{analysis['suggested_threshold']}"
        )
        ttk.Label(dialog, text=info, justify=tk.LEFT).pack(pady=4, padx=12)

        if not suggestions:
            ttk.Label(
                dialog,
                text=(
                    "No strong changes suggested — current settings look reasonable for this image.\n"
                    "If results still look wrong, try Measure Tune and click example cells."
                ),
                justify=tk.CENTER,
            ).pack(pady=20, padx=12)
            ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
            return

        canvas = tk.Canvas(dialog, highlightthickness=0, height=300)
        scroll = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=canvas.yview)
        suggestions_frame = ttk.Frame(canvas)
        suggestions_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=suggestions_frame, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill='both', expand=True, padx=(10, 0), pady=8)
        scroll.pack(side=tk.RIGHT, fill='y', pady=8, padx=(0, 10))

        suggestion_vars = []
        for suggestion in suggestions:
            var = tk.BooleanVar(value=True)
            suggestion_vars.append((suggestion, var))
            frame = ttk.Frame(suggestions_frame, relief='groove', borderwidth=1)
            frame.pack(fill='x', pady=3, padx=4)
            ttk.Checkbutton(frame, variable=var).pack(side='left', padx=6, pady=4)
            text = f"{suggestion['param']}:  {suggestion['current']}  →  {suggestion['suggested']}"
            ttk.Label(frame, text=text, font=("Helvetica", 10, "bold")).pack(anchor='w', padx=8, pady=(4, 0))
            ttk.Label(frame, text=suggestion['reason'], wraplength=560).pack(anchor='w', padx=8, pady=(0, 6))

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)

        def apply_suggestion(sugg):
            cfg = self.image_processor.cell_config
            pcfg = self.image_processor.preprocess_config
            param = sugg['param']
            value = sugg['suggested']
            if param == "detection_method":
                cfg.detection_method = value
            elif param == "preprocess_nr_gaussian":
                pcfg.nr_gaussian_sigma = float(value)
            elif param == "preprocess_denoise_method":
                pcfg.denoise_method = value
            elif hasattr(cfg, param):
                setattr(cfg, param, value)

        def apply_checked():
            applied = 0
            for sugg, var in suggestion_vars:
                if var.get():
                    apply_suggestion(sugg)
                    applied += 1
            dialog.destroy()
            if applied > 0:
                try:
                    self.show_cell_mask_threshold(calculate=True)
                except Exception:
                    pass
                messagebox.showinfo(
                    "Smart Suggest",
                    f"Applied {applied} change(s) and refreshed the mask.",
                )

        def apply_all():
            for sugg, _var in suggestion_vars:
                apply_suggestion(sugg)
            dialog.destroy()
            try:
                self.show_cell_mask_threshold(calculate=True)
            except Exception:
                pass
            messagebox.showinfo("Smart Suggest", "Applied all suggestions and refreshed the mask.")

        def apply_recommended_preset():
            preset = analysis.get("recommended_preset") or {}
            self._apply_blob_settings_dict(preset)
            dialog.destroy()
            try:
                self.show_cell_mask_threshold(calculate=True)
            except Exception:
                pass
            messagebox.showinfo(
                "Smart Suggest",
                "Applied the full LoG-based recommended preset and refreshed the mask.\n\n"
                f"sigma {preset.get('blob_min_sigma')}–{preset.get('blob_max_sigma')}, "
                f"thr={preset.get('blob_threshold')}, "
                f"area {preset.get('blob_min_area')}–{preset.get('blob_max_area')}",
            )

        ttk.Button(
            button_frame, text="Apply Checked + Refresh Mask", command=apply_checked, width=28
        ).pack(side='left', padx=3)
        ttk.Button(button_frame, text="Apply All", command=apply_all, width=12).pack(side='left', padx=3)
        ttk.Button(
            button_frame, text="Apply Full Preset", command=apply_recommended_preset, width=16
        ).pack(side='left', padx=3)
        ttk.Button(button_frame, text="Close", command=dialog.destroy, width=10).pack(side='right', padx=3)

    def _register_transparent_window(self, window):
        """Register a popup window so it follows the Transparent Mode setting."""
        if window not in self.transparent_windows:
            self.transparent_windows.append(window)

        # Apply current transparency state
        alpha = 0.3 if self.transparent_mode.get() else 1.0
        window.attributes('-alpha', alpha)

        # Best-effort cleanup when the window is closed
        def cleanup(event=None):
            if window in self.transparent_windows:
                self.transparent_windows.remove(window)
        window.bind("<Destroy>", cleanup, add="+")




    def update_brightness(self, value):
        """Slider callback — debounced; does not full-redraw atlas every tick."""
        self.brightness = float(value)
        # Cancel pending redraw so rapid slider motion only paints once
        aid = getattr(self, "_brightness_after_id", None)
        if aid is not None:
            try:
                self.master.after_cancel(aid)
            except Exception:
                pass
            self._brightness_after_id = None
        # ~50ms feels responsive without hammering full-res enhance + show_page
        self._brightness_after_id = self.master.after(50, self._apply_brightness_display)

    def _invalidate_bg_display_cache(self):
        """Drop cached display-sized background (call on load/zoom/image change)."""
        self._bg_display_base_cache = None

    def _bg_display_cache_key(self):
        base = (
            self.original_background
            if self.original_background is not None
            else self.background_image
        )
        if base is None:
            return None
        return (id(base), base.size, round(float(self.view_scale), 5))

    def _get_bg_display_base(self):
        """Resized background for current view_scale, *without* brightness applied.

        Cached so the brightness slider only re-runs a cheap enhance on a small image
        instead of re-enhancing the full-resolution TIFF and redrawing the atlas.
        """
        key = self._bg_display_cache_key()
        if key is None:
            return None
        cached = getattr(self, "_bg_display_base_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]

        base = (
            self.original_background
            if self.original_background is not None
            else self.background_image
        )
        scale = float(self.view_scale) if self.view_scale else 1.0
        img = base
        if scale != 1.0:
            nw = max(1, int(img.width * scale))
            nh = max(1, int(img.height * scale))
            img = img.resize((nw, nh), Image.BILINEAR)
        # Work in RGB for Brightness enhance speed when no alpha needed for display base
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        self._bg_display_base_cache = (key, img)
        return img

    def _apply_brightness_display(self):
        """Fast path: update only the background PhotoImage (no full show_page)."""
        self._brightness_after_id = None
        try:
            base = self._get_bg_display_base()
            if base is None:
                return
            bg_display = self.adjust_image(base)
            self.background_photo = ImageTk.PhotoImage(bg_display)
            # Prefer in-place canvas update if the bg item still exists
            item = getattr(self, "bg_photo_id", None)
            if item is not None:
                try:
                    self.output.itemconfigure(item, image=self.background_photo)
                    return
                except Exception:
                    pass
            # Fallback: full redraw if canvas was rebuilt
            self.show_page()
        except Exception as e:
            logger.debug(f"Fast brightness update failed, falling back to show_page: {e}")
            try:
                self.show_page()
            except Exception:
                pass

    def adjust_image(self, img):
        """Apply current brightness factor. No-op when factor ≈ 1 for speed."""
        factor = 1.0 + (float(getattr(self, "brightness", 0.0)) / 100.0)
        if abs(factor - 1.0) < 1e-4:
            return img
        enhancer = ImageEnhance.Brightness(img)
        return enhancer.enhance(factor)

    def open_user_manual(self):
        """Open the PDF user manual in the system's default viewer (cross-platform)."""
        # The manual lives in the repository root, one level above the Application/ directory
        manual_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "BARCC_User_Manual.pdf")
        )

        if not os.path.exists(manual_path):
            messagebox.showerror(
                "Manual Not Found",
                f"Could not find the user manual at:\n{manual_path}"
            )
            return

        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(manual_path)
            elif system == "Darwin":  # macOS
                subprocess.call(["open", manual_path])
            else:  # Linux and other Unix-like systems
                subprocess.call(["xdg-open", manual_path])
        except Exception as e:
            # Final fallback using the standard library (works on most systems)
            try:
                webbrowser.open(f"file://{manual_path}")
            except Exception as e2:
                messagebox.showerror(
                    "Error Opening Manual",
                    f"Could not open the user manual.\n\n"
                    f"Primary error: {e}\n"
                    f"Fallback error: {e2}"
                )

    # --- Configuration Presets System ---

    def _get_presets_path(self):
        presets_dir = os.path.join(os.path.expanduser("~"), ".barc")
        os.makedirs(presets_dir, exist_ok=True)
        return os.path.join(presets_dir, "presets.json")

    # ------------------------------------------------------------------
    # Export / Import Detection Settings (Portable Config Files)
    # ------------------------------------------------------------------

    def _collect_mask_generation_metadata(self, extra=None):
        """Build a full metadata dict of parameters used to generate the cell mask.

        Includes cell detection, preprocessing, source image info, and optional
        extras (e.g. output paths written during Count Cells).
        """
        cfg = self.image_processor.cell_config
        pcfg = self.image_processor.preprocess_config

        zone_names = {}
        try:
            page = self.current_page
            raw = self.zone_names.get(page, {}) or {}
            zone_names = {str(k): v for k, v in raw.items()}
        except Exception:
            zone_names = {}

        has_manual_add = self.manual_add_mask is not None
        has_manual_remove = self.manual_remove_mask is not None

        meta = {
            "format_version": 1,
            "barcc_version": "8.08.000",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "purpose": "Parameters used to generate the cell mask and regional counts",
            "source": {
                "tiff_filename": self.tiff_filename,
                "tiff_dir": self.tiff_dir,
                "tiff_path": (
                    os.path.join(self.tiff_dir, self.tiff_filename + ".tif")
                    if self.tiff_dir and self.tiff_filename
                    else getattr(self, "current_tiff_path", None)
                ),
                "image_size": (
                    list(self.original_background.size)
                    if getattr(self, "original_background", None) is not None
                    else None
                ),
            },
            "detection_method": cfg.detection_method,
            "cell_detection": dict(cfg.__dict__),
            "preprocessing": dict(pcfg.__dict__),
            "manual_mask_edits": {
                "manual_add_cells": bool(has_manual_add),
                "manual_remove_cells": bool(has_manual_remove),
            },
            "regions": {
                "page": self.current_page,
                "zone_names": zone_names,
                "zone_count": len(zone_names),
            },
            "display": {
                "brightness": getattr(self, "brightness", 0.0),
            },
        }
        if extra:
            meta["outputs"] = extra
        return meta

    def _save_mask_metadata_file(self, out_dir, base_name, extra=None):
        """Write {base_name}_metadata.json into out_dir. Returns path or None."""
        if not out_dir or not base_name:
            return None
        try:
            meta = self._collect_mask_generation_metadata(extra=extra)
            path = os.path.join(out_dir, f"{base_name}_metadata.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, default=str)
            logger.info(f"Mask metadata saved: {path}")
            return path
        except Exception as e:
            logger.error(f"Failed to save mask metadata: {e}")
            return None

    def _binary_mask_to_boundary_ring(self, binary_mask, thickness=2):
        """Convert a filled binary mask into open 'donut' rings (boundary only).

        Each connected component becomes a hollow outline so the underlying image
        remains visible in the blob interior. thickness is ring width in pixels.
        """
        binary = np.asarray(binary_mask)
        if binary.ndim > 2:
            binary = binary.squeeze()
        binary = binary > 0
        if binary.ndim != 2 or not binary.any():
            return np.zeros_like(binary, dtype=bool)

        thickness = int(max(1, thickness))
        try:
            # Label so each blob gets its own closed boundary
            labels = measure.label(binary, connectivity=2)
            # Inner boundaries of labeled regions (open hole in middle)
            ring = segmentation.find_boundaries(labels, mode='inner', background=0)
            if thickness > 1:
                # Thicken the outline slightly for visibility
                ring = morphology.binary_dilation(ring, footprint=disk(thickness - 1))
            # Tiny objects that vanish under inner boundary: fall back to outer boundary
            covered = measure.label(ring, connectivity=2)
            for zid in range(1, labels.max() + 1):
                blob = labels == zid
                if not np.any(ring & blob):
                    ring |= segmentation.find_boundaries(blob.astype(np.uint8), mode='outer')
            return ring.astype(bool)
        except Exception as e:
            logger.debug(f"Boundary ring fallback: {e}")
            # Morphological gradient fallback
            try:
                eroded = morphology.binary_erosion(binary, footprint=disk(thickness))
                ring = binary & ~eroded
                if not ring.any():
                    ring = segmentation.find_boundaries(binary.astype(np.uint8), mode='inner')
                return ring.astype(bool)
            except Exception:
                return binary  # last resort: solid (still visible)

    def _cell_detection_ring_overlay(self, binary_mask, size=None, color=(255, 0, 0), alpha=220, thickness=2):
        """Build an RGBA PIL image with only red donut rings for detected cells.

        size: optional (width, height) to resize the ring mask into.
        """
        ring = self._binary_mask_to_boundary_ring(binary_mask, thickness=thickness)
        if size is not None and (ring.shape[0] != size[1] or ring.shape[1] != size[0]):
            ring_img = Image.fromarray((ring.astype(np.uint8) * 255), mode='L')
            ring_img = ring_img.resize(size, Image.NEAREST)
            ring = np.array(ring_img) > 0
        h, w = ring.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[ring, 0] = color[0]
        rgba[ring, 1] = color[1]
        rgba[ring, 2] = color[2]
        rgba[ring, 3] = alpha
        return Image.fromarray(rgba, 'RGBA')

    def _export_cell_centroids_csv(self, cell_mask, out_dir, base_name):
        """Save one row per detected cell with centroid x, y and pixel area.

        Columns: x, y, area
          - x, y: centroid in image coordinates (x = column, y = row), float pixels
          - area: total pixel count of the connected component

        Writes: <out_dir>/{base_name}_cell_centroids.csv
        Returns path or None.
        """
        if not out_dir or not base_name or cell_mask is None:
            return None

        mask = np.asarray(cell_mask)
        if mask.ndim > 2:
            mask = mask.squeeze()
        binary = mask > 0
        if binary.ndim != 2 or not binary.any():
            # Still write a header-only file so the export is predictable
            path = os.path.join(out_dir, f"{base_name}_cell_centroids.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["x", "y", "area"])
            logger.info(f"Cell centroids CSV (empty): {path}")
            return path

        labels = measure.label(binary, connectivity=2)
        props = measure.regionprops(labels)

        rows = []
        for prop in props:
            # skimage: centroid is (row, col) → y, x
            y, x = prop.centroid
            area = int(prop.area)
            if area <= 0:
                continue
            rows.append({
                "x": float(x),
                "y": float(y),
                "area": area,
            })

        # Stable order: top-to-bottom, then left-to-right
        rows.sort(key=lambda r: (r["y"], r["x"]))

        path = os.path.join(out_dir, f"{base_name}_cell_centroids.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["x", "y", "area"])
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Cell centroids CSV saved ({len(rows)} cells): {path}")
        return path

    def export_detection_settings(self):
        """Export current cell detection + preprocessing settings to a user-chosen JSON file."""
        try:
            default_name = f"barcc_settings_{datetime.now().strftime('%Y%m%d_%H%M')}.json"

            file_path = fd.asksaveasfilename(
                title="Export Detection Settings",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=default_name
            )

            if not file_path:
                return

            config_data = self._collect_mask_generation_metadata()
            # Keep portable settings export compatible with import_detection_settings
            config_data = {
                "version": config_data.get("barcc_version", "8.08.000"),
                "detection_method": self.image_processor.cell_config.detection_method,
                "cell_detection": self.image_processor.cell_config.__dict__.copy(),
                "preprocessing": self.image_processor.preprocess_config.__dict__.copy(),
            }

            with open(file_path, "w") as f:
                json.dump(config_data, f, indent=2)

            messagebox.showinfo("Export Successful", f"Settings exported to:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export settings:\n{e}")

    def import_detection_settings(self):
        """Load cell detection + preprocessing settings from a user-chosen JSON file."""
        try:
            file_path = fd.askopenfilename(
                title="Import Detection Settings",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )

            if not file_path:
                return

            with open(file_path, "r") as f:
                data = json.load(f)

            # Apply detection method if present
            if "detection_method" in data:
                self.image_processor.cell_config.detection_method = data["detection_method"]

            # Apply cell detection config
            for key, value in data.get("cell_detection", {}).items():
                if hasattr(self.image_processor.cell_config, key):
                    setattr(self.image_processor.cell_config, key, value)

            # Apply preprocessing config
            for key, value in data.get("preprocessing", {}).items():
                if hasattr(self.image_processor.preprocess_config, key):
                    setattr(self.image_processor.preprocess_config, key, value)

            messagebox.showinfo("Import Successful", "Settings imported successfully.\n\nThe Mask Settings dialog will now close so the new values can be applied.")
            # Close the current Mask Settings window so the user sees the effect when they reopen it
            # We use a small delay + destroy pattern inside the dialog context later

        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not load settings file:\n{e}")

    def load_presets(self):
        path = self._get_presets_path()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_presets(self, presets_dict):
        path = self._get_presets_path()
        try:
            with open(path, "w") as f:
                json.dump(presets_dict, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save presets: {e}")

    def save_current_as_preset(self, name=None):
        if name is None:
            name = simpledialog.askstring("Save Preset", "Enter preset name:")
            if not name:
                return

        presets = self.load_presets()

        preset_data = {
            "cell_detection": self.image_processor.cell_config.__dict__.copy(),
            "preprocessing": self.image_processor.preprocess_config.__dict__.copy(),
        }
        presets[name] = preset_data
        self.save_presets(presets)
        messagebox.showinfo("Preset Saved", f"Preset '{name}' saved successfully.")

    def load_preset(self, name):
        presets = self.load_presets()
        if name not in presets:
            messagebox.showerror("Error", f"Preset '{name}' not found.")
            return False

        data = presets[name]
        try:
            for key, value in data.get("cell_detection", {}).items():
                if hasattr(self.image_processor.cell_config, key):
                    setattr(self.image_processor.cell_config, key, value)

            for key, value in data.get("preprocessing", {}).items():
                if hasattr(self.image_processor.preprocess_config, key):
                    setattr(self.image_processor.preprocess_config, key, value)

            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load preset: {e}")
            return False

    def delete_preset(self, name):
        presets = self.load_presets()
        if name in presets:
            del presets[name]
            self.save_presets(presets)
            messagebox.showinfo("Preset Deleted", f"Preset '{name}' deleted.")
        else:
            messagebox.showerror("Error", f"Preset '{name}' not found.")

    def _show_busy_dialog(self, title="Working"):
        """Create a progress dialog with a determinate loading bar.
        Returns an object with .set_progress(percent, message) and .close() methods.
        The dialog is hardened so that the user closing it (X button) will never
        cause the rest of the operation (or the whole app) to crash.
        """
        class ProgressDialog:
            def __init__(self, parent, title):
                self.window = Toplevel(parent)
                self.window.title(title)
                self.window.attributes('-topmost', True)
                self.window.resizable(False, False)
                self.closed = False

                # Strongly disable the close button / Alt+F4 etc.
                self.window.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

                self.label = ttk.Label(self.window, text="Initializing...")
                self.label.pack(padx=20, pady=(15, 5))

                self.progress = ttk.Progressbar(
                    self.window, 
                    orient='horizontal', 
                    length=280, 
                    mode='determinate',
                    maximum=100
                )
                self.progress.pack(padx=20, pady=(0, 15))

                self.window.update_idletasks()

            def _on_close_attempt(self):
                """User tried to close the dialog early. Mark as closed so all future
                calls to set_progress/close are no-ops and cannot raise."""
                self.closed = True
                self._safe_destroy()

            def _safe_destroy(self):
                try:
                    if self.window and self.window.winfo_exists():
                        self.window.destroy()
                except Exception:
                    pass

            def set_progress(self, percent, message=None):
                if getattr(self, 'closed', False):
                    return
                try:
                    self.progress['value'] = max(0, min(100, percent))
                    if message:
                        self.label.config(text=message)
                    if self.window and self.window.winfo_exists():
                        # update() paints the bar; update_idletasks alone can leave a frozen look
                        self.window.update_idletasks()
                        self.window.update()
                except Exception:
                    # Window was closed externally or became invalid — treat as closed forever
                    self.closed = True

            def close(self):
                if getattr(self, 'closed', False):
                    return
                self.closed = True
                self._safe_destroy()

        dialog = ProgressDialog(self.master, title)
        self._register_transparent_window(dialog.window)
        return dialog

    def save_state(self):
        self.state_manager.save_state(self)

    def undo(self, event=None):
        """Undo the last user action. Can be called repeatedly."""
        self.state_manager.undo(self)

    def _undo_event(self, event=None):
        """Keyboard handler (Ctrl+Z)."""
        self.undo(event)

    # ------------------------------------------------------------------
    # ZOOM FEATURE
    # ------------------------------------------------------------------
    def _bind_mousewheel(self):
        """Bind mouse wheel for zoom (cross-platform)."""
        self.output.bind("<MouseWheel>", self._on_mousewheel)      # Windows
        self.output.bind("<Button-4>", self._on_mousewheel)        # Linux scroll up
        self.output.bind("<Button-5>", self._on_mousewheel)        # Linux scroll down

    def _on_mousewheel(self, event):
        """Handle mouse wheel zoom centered on mouse position."""
        # Determine direction and factor
        if event.num == 4 or event.delta > 0:
            factor = 1.15  # zoom in
        else:
            factor = 1 / 1.15  # zoom out

        self._apply_zoom(factor, event)

    def _apply_zoom(self, factor, event=None):
        """Apply zoom factor, keeping alignment of all layers."""
        new_scale = self.view_scale * factor
        if new_scale < self.min_scale or new_scale > self.max_scale:
            return

        # Get zoom center in canvas coordinates
        if event is not None:
            cx = self.output.canvasx(event.x)
            cy = self.output.canvasy(event.y)
        else:
            # Fallback to center of visible area
            cx = self.output.canvasx(self.output.winfo_width() / 2)
            cy = self.output.canvasy(self.output.winfo_height() / 2)

        # Scale all paint strokes around the mouse point (this keeps them aligned with image content)
        # Note: because we delete finished strokes' items on mouse-up (in reset), the only
        # 'paint' items here should be the current in-progress stroke (rare during wheel).
        self.output.scale('paint', cx, cy, factor, factor)

        # Bake the (live) stroke and remove temporary items so show_page redraws cleanly
        # from the paint_layer (authoritative, model-space) without scaled vectors causing
        # duplication or displacement in future commits or saves.
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()
        self.output.delete('paint')

        # img_x/img_y are *model-space* offsets (same units as the TIFF / atlas
        # native pixels). Do NOT re-project them around the mouse — that moved the
        # atlas relative to the background (always drawn from model origin).
        # Only view_scale changes; both layers scale the same way and stay locked.
        old_scale = self.view_scale
        self.view_scale = new_scale
        self._invalidate_bg_display_cache()

        # Redraw, but preserve any active mask overlay so it doesn't disappear on zoom
        if self.editing_mask and self.current_mask is not None:
            # Regenerate red overlay for manual mask editing mode
            mask_arr = np.array(self.current_mask)
            overlay_rgba = np.zeros((*mask_arr.shape, 4), dtype=np.uint8)
            overlay_rgba[mask_arr > 0] = [255, 0, 0, 255]
            overlay_img = Image.fromarray(overlay_rgba)
            self.show_page(mask=overlay_img)
        elif getattr(self, 'showing_auto_mask', False):
            # Preserve the "Show Mask" / cell detection mask view
            self.show_cell_mask_threshold(calculate=False)
        else:
            self.show_page()

        # Update scroll region
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

        # Keep the model point under the cursor roughly fixed via canvas scan pan
        try:
            if old_scale > 0:
                mx = cx / old_scale
                my = cy / old_scale
                # After zoom, that model point sits at (mx*new_scale, my*new_scale)
                new_cx = mx * new_scale
                new_cy = my * new_scale
                self.output.scan_mark(int(round(new_cx)), int(round(new_cy)))
                self.output.scan_dragto(int(round(cx)), int(round(cy)), gain=1)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Alt + Drag Panning
    # ------------------------------------------------------------------
    def _start_pan(self, event):
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._pan_start_scrollx = self.output.xview()[0]
        self._pan_start_scrolly = self.output.yview()[0]
        self.output.config(cursor="fleur")

    def _do_pan(self, event):
        if self._pan_start_x is None:
            return
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y

        # Convert pixel delta to scroll fraction
        total_width = self.output.winfo_width()
        total_height = self.output.winfo_height()

        if total_width > 0:
            new_x = self._pan_start_scrollx - (dx / total_width)
            self.output.xview_moveto(new_x)
        if total_height > 0:
            new_y = self._pan_start_scrolly - (dy / total_height)
            self.output.yview_moveto(new_y)

    def _end_pan(self, event):
        self._pan_start_x = None
        self._pan_start_y = None
        self.output.config(cursor="")

    # ------------------------------------------------------------------
    # Coordinate conversion helpers (critical for correct drawing after zoom)
    # ------------------------------------------------------------------
    def _canvas_to_image(self, cx, cy):
        """Convert canvas coordinates to image (model) coordinates."""
        if self.view_scale == 0:
            return int(cx), int(cy)
        return int(cx / self.view_scale), int(cy / self.view_scale)

    def _image_to_canvas(self, ix, iy):
        """Convert image (model) coordinates to canvas coordinates for display."""
        return ix * self.view_scale, iy * self.view_scale

    def _paint_uses_atlas_space(self):
        """Paint zones share the atlas mask coordinate system when an atlas is loaded."""
        return getattr(self, "atlas_filetype", None) in ("pdf", "allen")

    def _canvas_to_paint_model(self, cx, cy):
        """Canvas → paint/zone model space (atlas model if atlas loaded, else image)."""
        if self._paint_uses_atlas_space():
            mx, my = self._canvas_to_atlas(cx, cy)
            return int(round(mx)), int(round(my))
        return self._canvas_to_image(cx, cy)

    def _paint_model_to_canvas(self, ix, iy):
        """Paint/zone model → canvas (inverse of _canvas_to_paint_model)."""
        s = float(self.view_scale) if self.view_scale else 1.0
        if self._paint_uses_atlas_space():
            return (float(ix) + float(self.img_x)) * s, (float(iy) + float(self.img_y)) * s
        return self._image_to_canvas(ix, iy)

    def _paint_model_to_image(self, ix, iy):
        """Paint model → background image pixels (for paint_layer baking at 0,0)."""
        if self._paint_uses_atlas_space():
            return int(round(float(ix) + float(self.img_x))), int(round(float(iy) + float(self.img_y)))
        return int(ix), int(iy)

    def _ensure_zone_mask_for_paint(self):
        """Return (mask_img L-mode, draw) sized for the active coordinate system.

        With an atlas loaded, keep/merge into the existing atlas zone mask so painted
        regions join Allen/PDF zones for Count Cells. Without atlas, use image size.
        """
        page = self.current_page
        if page is None:
            self.current_page = 0
            page = 0

        if page not in self.zone_counters:
            self.zone_counters[page] = 0
        if page not in self.zone_names:
            self.zone_names[page] = {}

        # Seed counter above any existing mask / name ids
        max_id = int(self.zone_counters.get(page, 0) or 0)
        for zid in self.zone_names.get(page, {}).keys():
            try:
                max_id = max(max_id, int(zid))
            except Exception:
                pass
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                m0 = np.array(self.mask_images[page])
                if m0.size:
                    max_id = max(max_id, int(m0.max()))
            except Exception:
                pass
        self.zone_counters[page] = max_id

        if page in self.mask_images and self.mask_images[page] is not None:
            mask_img = self.mask_images[page].copy()
            if mask_img.mode != "L":
                mask_img = mask_img.convert("L")
            return mask_img, ImageDraw.Draw(mask_img)

        # Create empty mask
        if self._paint_uses_atlas_space() and page in self.base_page_images and self.base_page_images[page] is not None:
            target_size = self.base_page_images[page].size
        elif self.original_background is not None:
            target_size = self.original_background.size
        elif self.background_image is not None:
            target_size = self.background_image.size
        else:
            try:
                target_size = (max(64, self.output.winfo_width()), max(64, self.output.winfo_height()))
            except Exception:
                target_size = (1024, 1024)

        mask_img = Image.new("L", target_size, 0)
        self.mask_images[page] = mask_img.copy()
        return mask_img, ImageDraw.Draw(mask_img)

    def _canvas_to_zone_model(self, cx, cy):
        """Map canvas coordinates to the model/pixel space used by the zone mask for the
        currently relevant layer (paint or atlas).

        - Painted regions (and baked 'img'/'png' layers) store their masks in background/image
          pixel space (no img_x/y offset). Use _canvas_to_image semantics.
        - Atlas (pdf) regions use the rendered page's model space (with img_x/y placement offset).

        This allows edge grab, border drag, and per-region translate/deform to work
        correctly and consistently for painted regions exactly like atlas regions.
        """
        if getattr(self, 'atlas_filetype', None) in ('pdf', 'allen'):
            # PDF and Allen plates are placed with img_x/img_y (atlas model space)
            return self._canvas_to_atlas(cx, cy)
        else:
            # Paint zones live in the main image/background pixel coordinate space
            ix, iy = self._canvas_to_image(cx, cy)
            return float(ix), float(iy)

    def _rebuild_paint_vectors(self):
        """Rebuild temporary 'paint' canvas items from paint_group_data for naming support.
        Called after show_page/zoom to restore vectors at current scale so right-click
        can find them and turn yellow. Uses model_points converted to current canvas coords.
        """
        if not self.paint_group_data:
            return
        # Clean any existing
        self.output.delete('paint')
        for group_tag, data_list in self.paint_group_data.items():
            if not data_list or not group_tag.startswith('paintgroup_'):
                continue
            # Collect full points in order
            points = []
            width = 3
            fill = self.DEFAULT_COLOR
            if group_tag in self.named_paint_groups and self.named_paint_groups[group_tag]:
                fill = '#ffcc00'
            for rec in data_list:
                mp = rec.get('model_points', [])
                for j in range(0, len(mp), 2):
                    ix = mp[j]
                    iy = mp[j + 1]
                    cx, cy = self._image_to_canvas(ix, iy)
                    points.append((cx, cy))
                w = rec.get('width', width)
                try:
                    width = max(width, int(float(w)))
                except:
                    pass
            if len(points) < 2:
                continue
            # dedup consecutive
            deduped = [points[0]]
            for p in points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            points = deduped
            if len(points) < 2:
                continue
            # flatten for create_line
            flat_coords = [c for p in points for c in p]
            self.output.create_line(
                flat_coords,
                width=width,
                fill=fill,
                capstyle=tk.ROUND,
                smooth=tk.TRUE,
                splinesteps=36,
                tags=('paint', group_tag)
            )

    def load_page_image(self):
        if self.atlas_filetype: 
            if self.current_page not in self.page_images:
                if self.atlas_filetype == 'pdf':
                    img = self.pdf_handler.render_page(self.current_page, self.zoom)
                    logger.debug(f"Creating new page image: mode={img.mode}, size={img.size}")
                    # Store clean base (no yellow tints) for per-region editing + rebuilds
                    self.base_page_images[self.current_page] = img.copy()
                    self.page_images[self.current_page] = img  # will be rebuilt with overlays when zones exist
                    # Only for true multi-page atlas (PDF): initialize per-page zone/mask state.
                    # Do NOT reset for 'img' (baked paint from Stop/Count) or 'png' (loaded paint layer):
                    # those would clobber zones/masks that _convert_named_paints_to_zones just
                    # registered from the user's right-click named paint regions (and the first
                    # stop_paint's show_page would otherwise wipe the first named region's data
                    # before count_cells could use it).
                    self.mask_images[self.current_page] = Image.new('L', (img.width, img.height), 0)
                    self.zone_counters[self.current_page] = 0
                    self.zone_names[self.current_page] = {}
                elif self.atlas_filetype == 'allen':
                    # Allen plates are pre-installed by _load_allen_plate_data (base + masks + names).
                    # Never wipe zone_names / mask_images here.
                    img = getattr(self, 'img', None)
                    if img is None:
                        img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                    if self.current_page not in self.base_page_images:
                        self.base_page_images[self.current_page] = img.copy()
                    self.page_images[self.current_page] = img
                else:
                    # 'img' or 'png' etc.: just cache the image content for display/layers.
                    # Paint-defined zones (from name_painted_region + convert, or count ensure)
                    # and mask_images must be preserved; the count_cells guard and convert
                    # paths are responsible for them.
                    img = self.img
                    logger.debug(f"Creating new page image: mode={img.mode}, size={img.size}")
                    if self.current_page not in self.base_page_images:
                        self.base_page_images[self.current_page] = img.copy()
                    self.page_images[self.current_page] = img
                    # Intentionally no reset of mask_images / zone_names / zone_counters here.
            
            current_img = self.page_images[self.current_page]
            logger.debug(f"Loaded page image: mode={current_img.mode}, size={current_img.size}")
            return current_img

        # No atlas_filetype (e.g. after reset or pure TIFF/paint start) or page not populated:
        # return/provide a safe blank so show_page doesn't crash on KeyError.
        if self.current_page not in self.page_images:
            if getattr(self, 'img', None) is not None:
                img = self.img
                if self.current_page not in getattr(self, 'base_page_images', {}):
                    self.base_page_images[self.current_page] = img.copy()
                self.page_images[self.current_page] = img
            else:
                img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                self.page_images[self.current_page] = img
        current_img = self.page_images[self.current_page]
        logger.debug(f"Loaded page image: mode={current_img.mode}, size={current_img.size}")
        return current_img

    def show_page(self, mask=None):
        if mask is None:
            self.showing_auto_mask = False

        # Deselect region transform target if we've switched pages
        if self.selected_page is not None and self.selected_page != self.current_page:
            self.selected_zone_id = None
            self.selected_page = None
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self.original_full_contour_for_edit = None
            self._edge_pending_deselect = False
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.region_move_mode.set(False)
            self.crop_mode = False
            self.crop_mode_var.set(False)
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self.edit_mode = False
            self.edit_mode_var.set(False)

        self._update_ribbon_selection()

        # Keep any active red edge highlight in the correct screen position after pan/zoom/page change
        if getattr(self, 'active_edge', None) is not None:
            self._update_edge_highlight()

        img = self.load_page_image() or Image.new('RGBA', (1, 1), (0, 0, 0, 0))

        self.output.delete("all")

        scale = self.view_scale

        # Allen Nissl reference strip: 30% of main image size, placed above y=0
        self._draw_allen_nissl_reference(scale)

        if self.background_image:
            # Resize first (cached), then brightness — never enhance full-res TIFF every frame
            base_bg = self._get_bg_display_base()
            if base_bg is None:
                base_bg = (
                    self.original_background
                    if self.original_background is not None
                    else self.background_image
                )
                if scale != 1.0:
                    base_bg = base_bg.resize(
                        (max(1, int(base_bg.width * scale)), max(1, int(base_bg.height * scale))),
                        Image.BILINEAR,
                    )
            bg_display = self.adjust_image(base_bg)

            self.background_photo = ImageTk.PhotoImage(bg_display)
            self.bg_photo_id = self.output.create_image(0, 0,
                                                       image=self.background_photo,
                                                       anchor='nw',
                                                       tag='image')

            # === Draw persistent paint layer (this fixes the "paint disappears on zoom" bug) ===
            if self.paint_layer is not None:
                paint_display = self.paint_layer
                if scale != 1.0:
                    pw = max(1, int(paint_display.width * scale))
                    ph = max(1, int(paint_display.height * scale))
                    paint_display = paint_display.resize((pw, ph), Image.BILINEAR)
                self.paint_photo = ImageTk.PhotoImage(paint_display)
                self.paint_photo_id = self.output.create_image(0, 0,
                                                               image=self.paint_photo,
                                                               anchor='nw',
                                                               tag='paint_layer')

            if mask is not None:
                mask_display = mask
                if scale != 1.0:
                    mw = max(1, int(mask_display.width * scale))
                    mh = max(1, int(mask_display.height * scale))
                    mask_display = mask_display.resize((mw, mh), Image.NEAREST)
                self.mask_photo = ImageTk.PhotoImage(mask_display)
                offset_x = bg_display.width + 10
                self.bg_mask_photo_id = self.output.create_image(offset_x, 0,
                                                                image=self.background_photo,
                                                                anchor='nw',
                                                                tag='image')
                self.mask_photo_id = self.output.create_image(0, 0,
                                                             image=self.mask_photo,
                                                             anchor='nw',
                                                             tag='mask')

        # Scale and place the atlas overlay at the (already scaled) self.img_x / self.img_y
        # Guard: if atlas is the paint content (set by save_paint in stop_paint etc.) and we have
        # a background + paint_layer, skip drawing it here to avoid duplicating the painted
        # regions (paint_layer is at 0,0; atlas would be at img_x/img_y which may be offset after zoom).
        skip_atlas = False
        if self.atlas_filetype == 'img' and self.background_image is not None and self.paint_layer is not None:
            skip_atlas = True

        if not skip_atlas:
            atlas_display = img
            if scale != 1.0:
                aw = max(1, int(img.width * scale))
                ah = max(1, int(img.height * scale))
                # BILINEAR blurs 1px borders; use NEAREST for Allen structure outlines
                resample = Image.NEAREST if self.atlas_filetype == 'allen' else Image.BILINEAR
                atlas_display = img.resize((aw, ah), resample)

            self.photo = ImageTk.PhotoImage(atlas_display)
            # img_x/img_y are model-space offsets (native image/atlas pixels);
            # convert to canvas by multiplying view_scale so zoom keeps atlas
            # locked to the background (also drawn from model origin * scale).
            display_img_x = float(self.img_x) * float(scale)
            display_img_y = float(self.img_y) * float(scale)

            self.output.create_image(display_img_x, display_img_y,
                                   image=self.photo,
                                   anchor='nw',
                                   tag='atlas')

        # Label placement base: atlas overlay offset (or 0 when mask is image-sized)
        try:
            label_base_x = float(self.img_x) * float(scale)
            label_base_y = float(self.img_y) * float(scale)
        except Exception:
            label_base_x, label_base_y = 0.0, 0.0

        # --- Draw Zone Labels and Counts on the main image ---
        if self.show_zone_labels_var.get() and self.last_df is not None and self.current_page in self.mask_images:
            try:
                mask = np.array(self.mask_images[self.current_page])
                mask_h, mask_w = mask.shape
                zone_data = self.last_df.set_index('Zone')['Cell_Count'].to_dict() if 'Zone' in self.last_df.columns else {}

                label_offset_x = label_base_x
                label_offset_y = label_base_y
                if self.background_image is not None:
                    bg_w, bg_h = self.background_image.size
                    if abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5:
                        label_offset_x = 0
                        label_offset_y = 0

                for zone_name, count in zone_data.items():
                    zone_id = None
                    for zid, zname in self.zone_names.get(self.current_page, {}).items():
                        if zname == zone_name:
                            zone_id = zid
                            break

                    if zone_id is None:
                        continue

                    coords = np.where(mask == zone_id)
                    if len(coords[0]) == 0:
                        continue

                    cy = int(np.mean(coords[0]))
                    cx = int(np.mean(coords[1]))
                    screen_x = cx * scale + label_offset_x
                    screen_y = cy * scale + label_offset_y

                    label_text = f"{zone_name}\n({count})"
                    self.output.create_text(
                        screen_x, screen_y, text=label_text, fill="yellow",
                        font=("Helvetica", 10, "bold"), anchor="center",
                        tags="zone_label",
                    )
            except Exception as e:
                logger.warning(f"Failed to draw zone labels: {e}")

        # --- Draw Zone Labels and Mean Intensities (Axons and Nets) ---
        if (
            self.show_zone_intensity_labels_var.get()
            and getattr(self, "last_intensity_df", None) is not None
            and self.current_page in self.mask_images
        ):
            try:
                mask = np.array(self.mask_images[self.current_page])
                mask_h, mask_w = mask.shape
                idf = self.last_intensity_df
                if "Zone" in idf.columns and "Mean_Intensity" in idf.columns:
                    intensity_map = {}
                    for _, row in idf.iterrows():
                        intensity_map[str(row["Zone"])] = row["Mean_Intensity"]

                    label_offset_x = label_base_x
                    label_offset_y = label_base_y
                    if self.background_image is not None:
                        bg_w, bg_h = self.background_image.size
                        if abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5:
                            label_offset_x = 0
                            label_offset_y = 0

                    # Slight vertical offset when both count and intensity labels are on
                    y_nudge = 18 if self.show_zone_labels_var.get() else 0

                    for zone_name, mean_i in intensity_map.items():
                        zone_id = None
                        for zid, zname in self.zone_names.get(self.current_page, {}).items():
                            if zname == zone_name:
                                zone_id = zid
                                break
                        if zone_id is None:
                            continue
                        coords = np.where(mask == zone_id)
                        if len(coords[0]) == 0:
                            continue
                        cy = int(np.mean(coords[0]))
                        cx = int(np.mean(coords[1]))
                        screen_x = cx * scale + label_offset_x
                        screen_y = cy * scale + label_offset_y + y_nudge
                        if mean_i is None or (isinstance(mean_i, float) and np.isnan(mean_i)):
                            i_txt = "—"
                        else:
                            i_txt = f"{float(mean_i):.1f}"
                        label_text = f"{zone_name}\n(I={i_txt})"
                        self.output.create_text(
                            screen_x, screen_y, text=label_text, fill="#7FDBFF",
                            font=("Helvetica", 10, "bold"), anchor="center",
                            tags="zone_intensity_label",
                        )
            except Exception as e:
                logger.warning(f"Failed to draw intensity labels: {e}")

        # Update scroll region
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

        # Rebuild vector paint items from durable data if present.
        # This ensures right-click naming (yellow highlight) works even after
        # show_page or zoom has cleaned the items. Uses current scale.
        if self.paint_group_data:
            self._rebuild_paint_vectors()

        # Re-draw any persistent selected edge highlight (red) after delete("all").
        # Keeps the illumination visible after pan/zoom/show_page while an edge is selected.
        if getattr(self, 'selected_edge_full_contour', None) is not None and not getattr(self, 'edge_grab_active', False):
            if getattr(self, 'active_edge', None) is not None:
                self._draw_edge_highlight(self.active_edge)
            else:
                self._draw_edge_highlight()

        # Re-draw crop selection outline if user is still adjusting it
        if getattr(self, "crop_mode", False) and getattr(self, "crop_pending", False) and getattr(
            self, "crop_box", None
        ):
            try:
                self._draw_crop_outline()
            except Exception:
                pass


    def img_white_to_transparent(self, img):
        img_array = np.array(img)
        white_mask = np.all(img_array[:, :, :3] >= 250, axis=-1)
        img_array[white_mask, 3] = 0
        img = Image.fromarray(img_array)
        return img

    def _canvas_to_atlas(self, canvas_x, canvas_y):
        """Convert canvas coordinates to atlas model/native coordinates.

        ``img_x`` / ``img_y`` are model-space offsets (same units as atlas pixels).
        Display position is ``(img_x * view_scale, img_y * view_scale)``.
        """
        if self.view_scale <= 0:
            return 0.0, 0.0
        model_x = (float(canvas_x) / self.view_scale) - float(self.img_x)
        model_y = (float(canvas_y) / self.view_scale) - float(self.img_y)
        return model_x, model_y

    def _rebuild_page_overlays(self, page=None):
        """Rebuild page_images[page] by taking the clean base and applying yellow (or orange for selected)
        tint overlays based on the current mask labels. This enables clean per-region edits without
        losing the underlying atlas artwork.

        For Allen structure-border atlases: apply light fills first, then re-composite pure
        black borders on top so fills never hide the drawing (PDF-like).
        """
        if page is None:
            page = self.current_page
        if page not in self.base_page_images:
            # Fallback: promote current page image as base (for legacy 'img' atlas cases)
            if page in self.page_images:
                self.base_page_images[page] = self.page_images[page].copy()
            else:
                return
        base = self.base_page_images[page].convert('RGBA').copy()
        is_allen = getattr(self, 'atlas_filetype', None) == 'allen'

        if page in self.mask_images and self.mask_images[page] is not None:
            m = np.array(self.mask_images[page])
            if m.shape[0] != base.size[1] or m.shape[1] != base.size[0]:
                m = np.array(self.mask_images[page].resize(base.size, Image.NEAREST))

            # Build a separate fill layer so we don't erase black borders baked into base.
            # Allen: hollow by default (borders only); fill only the actively selected zone.
            # PDF/painted: keep light yellow on named zones; orange for selected.
            fill = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
            for zid in np.unique(m):
                if zid == 0:
                    continue
                reg = (m == zid)
                is_selected = (
                    self.selected_zone_id is not None
                    and self.selected_page == page
                    and int(zid) == int(self.selected_zone_id)
                )
                if is_allen:
                    if is_selected:
                        # Prefer clicked connected component (one hemisphere) over whole zone ID
                        reg_sel = self._selected_component_mask(m, int(zid))
                        fill[reg_sel, :3] = [255, 140, 0]  # orange selected
                        fill[reg_sel, 3] = 70
                    # else: leave transparent (hollow outlines only)
                else:
                    if is_selected:
                        fill[reg, :3] = [255, 140, 0]
                        fill[reg, 3] = 50
                    else:
                        fill[reg, :3] = [255, 255, 0]
                        fill[reg, 3] = 18

            if is_allen:
                # Always re-compose pure black borders; optional selected fill underneath.
                # Yellow outline is drawn *on the atlas layer* so it stays registered under
                # Move/Scale/Rotate (paint-layer contours used image coords and misaligned).
                borders = getattr(self, 'allen_borders_pure', None)
                if borders is None:
                    borders = base
                elif borders.size != base.size:
                    borders = borders.resize(base.size, Image.NEAREST)
                if np.any(fill[..., 3] > 0):
                    fill_img = Image.fromarray(fill, 'RGBA')
                    composed = Image.alpha_composite(
                        Image.new('RGBA', base.size, (0, 0, 0, 0)), fill_img
                    )
                    composed = Image.alpha_composite(composed, borders.convert('RGBA'))
                else:
                    composed = borders.convert('RGBA')

                # Selected zone: yellow edge pixels only (no polyline/curve — avoids diamond chords)
                if (
                    self.selected_zone_id is not None
                    and self.selected_page == page
                ):
                    try:
                        zid_sel = int(self.selected_zone_id)
                        binr = self._selected_component_mask(m, zid_sel)
                        if binr.any():
                            try:
                                from skimage.segmentation import find_boundaries
                                yedge = find_boundaries(binr.astype(np.uint8), mode="outer")
                            except Exception:
                                er = morphology.binary_erosion(binr, morphology.disk(1))
                                yedge = binr & ~er
                            comp_arr = np.array(composed)
                            # thicken by 1px for visibility
                            try:
                                yedge = morphology.binary_dilation(yedge, morphology.disk(1))
                            except Exception:
                                pass
                            comp_arr[yedge, 0] = 255
                            comp_arr[yedge, 1] = 255
                            comp_arr[yedge, 2] = 0
                            comp_arr[yedge, 3] = 255
                            composed = Image.fromarray(comp_arr, "RGBA")
                    except Exception as e:
                        logger.debug(f"Allen selection contour failed: {e}")

                self.page_images[page] = composed
                return

            if np.any(fill[..., 3] > 0):
                fill_img = Image.fromarray(fill, 'RGBA')
                composed = Image.alpha_composite(base, fill_img)
                self.page_images[page] = composed
                return

        self.page_images[page] = base

    def import_atlas(self):
        logger.info("Opening file dialog for atlas selection")
        self.save_state()
        path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf"), ("PDF files", "*.ai")])
        if path:
            logger.info(f"Opening atlas file: {path}")
            self.path = path
            self.doc, self.num_pages = self.pdf_handler.open_pdf(self.path)
            self.atlas_filetype = 'pdf'
            self.allen_zone_meta = {}
            self.allen_nissl_reference = None
            self.allen_nissl_photo = None
            self.zoom = 1.0
            self.view_scale = 1.0
            self.img_x = 0
            self.img_y = 0
            self.current_page = 0
            self.page_images = {}
            self.mask_images = {}
            self.base_page_images = {}
            self.zone_counters = {}
            self.zone_names = {}
            self.selected_zone_id = None
            self.selected_page = None
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.original_full_contour_for_edit = None
            self.selected_edge_full_contour = None
            self._edge_pending_deselect = False
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.region_move_mode.set(False)
            self.crop_mode = False
            self.crop_mode_var.set(False)
            self.edit_mode = False
            self.edit_mode_var.set(False)
            self.named_paint_groups.clear()
            self.paint_group_data.clear()
            self.painted_zone_outlines.clear()
            clear_preprocess_cache()
            self.show_page()

    # ------------------------------------------------------------------
    # Allen Mouse Reference Atlas (Phase 1 + 2)
    # ------------------------------------------------------------------

    def download_full_allen_atlas(self):
        """Pre-download all annotated Allen plates into the local cache (~/.barc/allen_cache).

        Subsequent Import Allen Atlas / plate loads read from this folder when present.
        """
        try:
            from allen_atlas import (
                ALLEN_ATLASES,
                cache_dir,
                check_api_reachable,
                download_full_atlas,
                plate_cache_status,
            )
        except ImportError as e:
            messagebox.showerror(
                "Allen Atlas",
                f"Could not import allen_atlas module:\n{e}\n\n"
                "Ensure allen_atlas.py is next to barcc.py.",
            )
            return

        win = Toplevel(self.master)
        win.title("Download Full Allen Atlas")
        win.geometry("520x360")
        win.attributes("-topmost", "true")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._register_transparent_window(win)

        plane_var = tk.StringVar(value="coronal")
        ds_var = tk.StringVar(value="3 (default)")
        status_var = tk.StringVar(value="")
        progress_var = tk.DoubleVar(value=0.0)
        cancel_flag = {"cancel": False}

        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text="Download all annotated Allen plates to a local folder.\n"
                 "Loads after this will use the cache (no re-download).",
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(frm)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Plane:").pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="Coronal (P56, ~132 plates)", variable=plane_var, value="coronal").pack(
            side=tk.LEFT, padx=6
        )
        ttk.Radiobutton(row, text="Sagittal (P56, ~21 plates)", variable=plane_var, value="sagittal").pack(
            side=tk.LEFT, padx=6
        )

        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Nissl quality (downsample):").pack(side=tk.LEFT)
        ds_box = ttk.Combobox(
            row2,
            width=14,
            state="readonly",
            textvariable=ds_var,
            values=["2 (high)", "3 (default)", "4 (fast)", "5 (preview)"],
        )
        ds_box.pack(side=tk.LEFT, padx=6)

        cache_label = ttk.Label(frm, text=f"Cache folder:\n{cache_dir()}", wraplength=480, justify=tk.LEFT)
        cache_label.pack(anchor="w", pady=8)

        status_lbl = ttk.Label(frm, textvariable=status_var, wraplength=480, justify=tk.LEFT)
        status_lbl.pack(anchor="w", pady=4)
        pbar = ttk.Progressbar(frm, variable=progress_var, maximum=100, mode="determinate")
        pbar.pack(fill="x", pady=6)

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=8)

        def _ds():
            try:
                return int((ds_var.get() or "3").split()[0])
            except Exception:
                return 3

        def refresh_status(*_a):
            try:
                st = plate_cache_status(plane_var.get(), downsample=_ds())
                status_var.set(
                    f"{ALLEN_ATLASES[plane_var.get()]['name']}: "
                    f"{st['complete']}/{st['total']} plates fully cached "
                    f"(Nissl {st['nissl_cached']}, SVG {st['svg_cached']})"
                )
            except Exception as e:
                status_var.set(f"Could not read cache status: {e}")

        def start_download():
            ok, msg = check_api_reachable(timeout=20)
            if not ok:
                messagebox.showerror(
                    "Allen Atlas",
                    "Cannot reach the Allen Brain Atlas API.\n\n"
                    f"{msg}\n\n"
                    f"Already-cached files still work from:\n{cache_dir()}",
                    parent=win,
                )
                return
            cancel_flag["cancel"] = False
            start_btn.configure(state=tk.DISABLED)
            close_btn.configure(state=tk.DISABLED)
            progress_var.set(0)
            key = plane_var.get()
            ds = _ds()

            def on_progress(done, total, plate, message):
                if cancel_flag["cancel"]:
                    raise RuntimeError("Cancelled by user")
                pct = 100.0 * done / max(total, 1)
                progress_var.set(pct)
                status_var.set(message)
                win.update_idletasks()

            try:
                summary = download_full_atlas(
                    atlas_key=key,
                    downsample=ds,
                    include_nissl=True,
                    include_svg=True,
                    progress_callback=on_progress,
                    force=False,
                )
                err_n = len(summary.get("errors") or [])
                progress_var.set(100)
                status_var.set(
                    f"Done. Nissl downloaded: {summary['downloaded_nissl']}, "
                    f"SVG downloaded: {summary['downloaded_svg']}, "
                    f"errors: {err_n}\nSaved under:\n{summary['cache_dir']}"
                )
                messagebox.showinfo(
                    "Allen Atlas Download",
                    f"Cached {ALLEN_ATLASES[key]['name']} plates.\n\n"
                    f"Nissl newly downloaded: {summary['downloaded_nissl']}\n"
                    f"SVG newly downloaded: {summary['downloaded_svg']}\n"
                    f"Already present (skipped): {summary['skipped_existing']}\n"
                    f"Errors: {err_n}\n\n"
                    f"Folder:\n{summary['cache_dir']}\n\n"
                    "Import Allen Atlas will use these files automatically.",
                    parent=win,
                )
            except Exception as e:
                if "Cancelled" in str(e):
                    status_var.set("Download cancelled.")
                else:
                    logger.error(f"Full atlas download failed: {e}", exc_info=True)
                    messagebox.showerror("Allen Atlas", f"Download failed:\n{e}", parent=win)
                    status_var.set(f"Failed: {e}")
            finally:
                start_btn.configure(state=tk.NORMAL)
                close_btn.configure(state=tk.NORMAL)
                refresh_status()

        start_btn = ttk.Button(btn_row, text="Download", command=start_download)
        start_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Refresh status", command=refresh_status).pack(side=tk.LEFT, padx=2)
        close_btn = ttk.Button(btn_row, text="Close", command=win.destroy)
        close_btn.pack(side=tk.RIGHT, padx=2)

        plane_var.trace_add("write", refresh_status)
        ds_var.trace_add("write", refresh_status)
        refresh_status()

    def open_allen_atlas_browser(self):
        """Open the Allen Mouse Atlas plate browser (Phase 1 + 2)."""
        try:
            from allen_atlas import (
                ALLEN_ATLASES,
                check_api_reachable,
                list_annotated_plates,
                load_plate,
                plate_display_label,
            )
        except ImportError as e:
            messagebox.showerror(
                "Allen Atlas",
                f"Could not import allen_atlas module:\n{e}\n\n"
                "Ensure allen_atlas.py is next to barcc.py.",
            )
            return

        ok, msg = check_api_reachable(timeout=20)
        # Allow offline if cache has plates (user may have pre-downloaded)
        if not ok:
            try:
                from allen_atlas import plate_cache_status, cache_dir
                st = plate_cache_status("coronal", downsample=3)
                if st.get("svg_cached", 0) > 0:
                    messagebox.showwarning(
                        "Allen Atlas",
                        "Allen API not reachable, but local cache has plates.\n"
                        "Browser will use cached SVGs/images where available.\n\n"
                        f"{msg}\n\nCache: {cache_dir()}",
                    )
                else:
                    messagebox.showerror(
                        "Allen Atlas",
                        "Cannot reach the Allen Brain Atlas API and no local cache found.\n\n"
                        f"{msg}\n\n"
                        "Use Atlas → Download Full Allen Atlas… while online,\n"
                        f"or check your network.\n\nCache folder: {cache_dir()}",
                    )
                    return
            except Exception:
                messagebox.showerror(
                    "Allen Atlas",
                    "Cannot reach the Allen Brain Atlas API.\n\n"
                    f"{msg}\n\n"
                    "Check your network connection and try again.\n"
                    "Cached plates (if any) live under ~/.barc/allen_cache/",
                )
                return

        win = Toplevel(self.master)
        win.title("Allen Mouse Reference Atlas")
        win.geometry("720x560")
        win.attributes("-topmost", "true")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._register_transparent_window(win)

        status_var = tk.StringVar(value="Loading plate list…")
        preview_label = ttk.Label(win, text="Preview will appear here", anchor="center")
        listbox = None
        plates_holder = {"plates": [], "atlas_key": "coronal"}
        downsample_var = tk.IntVar(value=3)
        plane_var = tk.StringVar(value="coronal")
        search_var = tk.StringVar(value="")

        # --- layout ---
        top = ttk.Frame(win, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Plane:").pack(side=tk.LEFT)
        ttk.Radiobutton(top, text="Coronal (P56)", variable=plane_var, value="coronal").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Radiobutton(top, text="Sagittal (P56)", variable=plane_var, value="sagittal").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Label(top, text="  Quality (downsample):").pack(side=tk.LEFT, padx=(12, 2))
        ds_box = ttk.Combobox(
            top, width=4, state="readonly",
            values=["2 (high)", "3 (default)", "4 (fast)", "5 (preview)"],
        )
        ds_box.set("3 (default)")
        ds_box.pack(side=tk.LEFT)

        top2 = ttk.Frame(win, padding=(6, 0, 6, 0))
        top2.pack(fill="x")
        ttk.Label(
            top2,
            text="Coronal plates: open the stitch editor to Reflect the half-drawing and "
                 "manually move/rotate halves before loading into BARCC.",
            wraplength=680,
            font=("Helvetica", 8),
        ).pack(side=tk.LEFT)

        mid = ttk.Frame(win, padding=6)
        mid.pack(fill="both", expand=True)
        left = ttk.Frame(mid)
        left.pack(side=tk.LEFT, fill="both", expand=True)
        right = ttk.Frame(mid, width=280)
        right.pack(side=tk.RIGHT, fill="y", padx=(8, 0))

        ttk.Label(left, text="Search structures (filters plates with match after load tip):").pack(anchor="w")
        search_entry = ttk.Entry(left, textvariable=search_var)
        search_entry.pack(fill="x", pady=(0, 4))

        ttk.Label(left, text="Annotated plates:").pack(anchor="w")
        lb_frame = ttk.Frame(left)
        lb_frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(lb_frame, exportselection=False, height=18)
        sb = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=sb.set)
        listbox.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")

        preview_label.pack(in_=right, fill="both", expand=True, pady=4)
        ttk.Label(right, textvariable=status_var, wraplength=260).pack(anchor="w", pady=4)

        btn_row = ttk.Frame(win, padding=6)
        btn_row.pack(fill="x")

        preview_photo_holder = {"photo": None, "plate_data": None}

        def _ds_value():
            s = ds_box.get() or "3"
            try:
                return int(s.split()[0])
            except Exception:
                return 3

        def refresh_list(*_args):
            key = plane_var.get()
            status_var.set(f"Fetching {ALLEN_ATLASES[key]['name']} plate list…")
            win.update_idletasks()
            try:
                plates = list_annotated_plates(key)
            except Exception as e:
                status_var.set(f"Error: {e}")
                messagebox.showerror("Allen Atlas", f"Could not list plates:\n{e}", parent=win)
                return
            plates_holder["plates"] = plates
            plates_holder["atlas_key"] = key
            listbox.delete(0, tk.END)
            q = (search_var.get() or "").strip().lower()
            shown = 0
            for p in plates:
                lab = plate_display_label(p)
                # Search filters by section/label text only at list time;
                # structure search applied after optional local name cache is not available per-plate
                if q and q not in lab.lower() and q not in str(p.section_number):
                    continue
                listbox.insert(tk.END, lab)
                shown += 1
            status_var.set(
                f"{ALLEN_ATLASES[key]['name']}: {shown} plates shown "
                f"({len(plates)} annotated total). Select a plate, then Load."
            )
            if shown:
                listbox.selection_set(0)
                listbox.see(0)

        def current_plate():
            sel = listbox.curselection()
            if not sel:
                return None
            lab = listbox.get(sel[0])
            # match by label
            for p in plates_holder["plates"]:
                if plate_display_label(p) == lab:
                    return p
            # fallback by index in full list
            try:
                idx = int(lab.split()[0].lstrip("#")) - 1
                return plates_holder["plates"][idx]
            except Exception:
                return None

        def preview_selected(*_args):
            p = current_plate()
            if p is None:
                return
            status_var.set(f"Downloading preview for section {p.section_number}…")
            win.update_idletasks()
            try:
                ds = max(4, _ds_value())  # faster preview
                data = load_plate(p, downsample=ds, mirror_hemispheres=False)
                preview_photo_holder["plate_data"] = data
                # Nissl with borders overlaid
                img = data.nissl_rgba.convert("RGBA").copy()
                if data.borders_rgba is not None:
                    try:
                        b = data.borders_rgba.convert("RGBA")
                        if b.size != img.size:
                            b = b.resize(img.size, Image.NEAREST)
                        img = Image.alpha_composite(img, b)
                    except Exception:
                        pass
                img.thumbnail((260, 320), Image.BILINEAR)
                photo = ImageTk.PhotoImage(img)
                preview_photo_holder["photo"] = photo
                preview_label.configure(image=photo, text="")
                n_zones = len(data.zone_names)
                status_var.set(
                    f"{plate_display_label(p)}\n"
                    f"Structures on plate: {n_zones}\n"
                    f"Allen drawing (right hemi typical)\n"
                    f"Use “Open stitch editor” to Reflect &\n"
                    f"manually align halves, then load."
                )
            except Exception as e:
                logger.error(f"Allen preview failed: {e}", exc_info=True)
                status_var.set(f"Preview failed: {e}")
                preview_label.configure(image="", text="(preview failed)")

        def open_stitch_editor():
            p = current_plate()
            if p is None:
                messagebox.showinfo("Allen Atlas", "Select a plate first.", parent=win)
                return
            status_var.set("Loading plate into stitch editor…")
            win.update_idletasks()
            progress = None
            try:
                progress = self._show_busy_dialog("Allen Atlas")
                progress.set_progress(15, "Downloading Nissl + structures…")
                ds = _ds_value()
                from allen_atlas import load_plate_for_stitch_editor
                session = load_plate_for_stitch_editor(p, downsample=ds)
                progress.set_progress(100, "Opening editor…")
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                    progress = None
                self.open_allen_stitch_editor(session, parent=win)
            except Exception as e:
                logger.error(f"Allen stitch editor open failed: {e}", exc_info=True)
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                messagebox.showerror("Allen Atlas", f"Failed to open stitch editor:\n{e}", parent=win)
                status_var.set(f"Failed: {e}")

        def load_as_drawn():
            """Load unilateral drawing without stitch editor (sagittal / quick path)."""
            p = current_plate()
            if p is None:
                messagebox.showinfo("Allen Atlas", "Select a plate first.", parent=win)
                return
            status_var.set("Loading plate into BARCC…")
            win.update_idletasks()
            progress = None
            try:
                progress = self._show_busy_dialog("Allen Atlas")
                progress.set_progress(10, "Downloading plate…")
                data = load_plate(p, downsample=_ds_value(), mirror_hemispheres=False)
                progress.set_progress(70, "Installing atlas layers…")
                self._load_allen_plate_data(data)
                progress.set_progress(100, "Done")
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                win.destroy()
                messagebox.showinfo(
                    "Allen Atlas Loaded",
                    f"Loaded {plate_display_label(p)} as drawn (no reflect).\n\n"
                    f"Structures: {len(data.zone_names)}\n"
                    "Use Atlas → Move / Rotate / Scale / Crop to align.",
                )
            except Exception as e:
                logger.error(f"Allen load failed: {e}", exc_info=True)
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                messagebox.showerror("Allen Atlas", f"Failed to load plate:\n{e}", parent=win)

        def _on_plane_change(*_args):
            refresh_list()

        listbox.bind("<<ListboxSelect>>", lambda e: None)
        listbox.bind("<Double-Button-1>", lambda e: open_stitch_editor())
        ttk.Button(btn_row, text="Refresh list", command=refresh_list).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Preview", command=preview_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Open stitch editor…", command=open_stitch_editor).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(btn_row, text="Load as drawn", command=load_as_drawn).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Close", command=win.destroy).pack(side=tk.RIGHT, padx=2)

        plane_var.trace_add("write", _on_plane_change)
        # initial list
        win.after(50, refresh_list)

    def _draw_allen_nissl_reference(self, scale=1.0):
        """Draw pure Allen Nissl as a fixed reference strip above the main image (30% size).

        Not part of the movable atlas layer — orientation reference only.
        """
        nissl = getattr(self, "allen_nissl_reference", None)
        if nissl is None:
            self.allen_nissl_photo = None
            return
        try:
            # Size relative to the main experimental image if present, else atlas/nissl itself
            if self.background_image is not None:
                ref_w = self.background_image.size[0]
                ref_h = self.background_image.size[1]
            elif self.original_background is not None:
                ref_w, ref_h = self.original_background.size
            else:
                ref_w, ref_h = nissl.size

            target_w = max(40, int(ref_w * 0.30 * scale))
            target_h = max(40, int(ref_h * 0.30 * scale))
            # Preserve Nissl aspect ratio inside the 30% box
            nw, nh = nissl.size
            fit = min(target_w / float(nw), target_h / float(nh))
            disp_w = max(1, int(nw * fit))
            disp_h = max(1, int(nh * fit))
            nissl_disp = nissl.resize((disp_w, disp_h), Image.BILINEAR)

            self.allen_nissl_photo = ImageTk.PhotoImage(nissl_disp)
            # Place just above the main image (negative y); main image stays at y=0
            gap = 12
            y0 = -disp_h - gap
            self.output.create_image(
                0, y0, image=self.allen_nissl_photo, anchor="nw", tags=("allen_nissl_ref",)
            )
            # Caption
            self.output.create_text(
                4, y0 - 2,
                text="Allen Nissl reference (30%) — not movable; use black borders for alignment",
                anchor="sw",
                fill="#444444",
                font=("Helvetica", 8),
                tags=("allen_nissl_ref",),
            )
        except Exception as e:
            logger.debug(f"Allen Nissl reference draw failed: {e}")
            self.allen_nissl_photo = None

    def open_allen_stitch_editor(self, session, parent=None):
        """Semi-automated hemisphere stitch: Nissl + Reflect + move/rotate halves.

        User adjusts left/right border layers against the Nissl photo, then loads
        the composed structure borders into BARCC.
        """
        try:
            from allen_atlas import (
                reflect_right_to_left,
                compose_stitch_preview,
                commit_stitch_session,
                plate_display_label,
            )
        except ImportError as e:
            messagebox.showerror("Allen Atlas", f"Could not import stitch helpers:\n{e}")
            return

        parent_win = parent if parent is not None else self.master
        ed = Toplevel(parent_win)
        ed.title(f"Allen stitch editor — {plate_display_label(session.plate)}")
        ed.geometry("1100x780")
        ed.attributes("-topmost", "true")
        ed.protocol("WM_DELETE_WINDOW", ed.destroy)
        self._register_transparent_window(ed)

        # --- state ---
        tool_var = tk.StringVar(value="move")  # move | rotate
        target_var = tk.StringVar(value="left")  # left | right | both
        status_var = tk.StringVar(
            value="Nissl shown. Click Reflect to create the left half, then Move/Rotate to stitch."
        )
        step_move = tk.DoubleVar(value=2.0)
        step_rot = tk.DoubleVar(value=0.5)
        view_scale = {"s": 1.0}
        drag = {"active": False, "x0": 0, "y0": 0, "mode": None}
        photos = {"img": None}

        # --- toolbar ---
        tb = ttk.Frame(ed, padding=6)
        tb.pack(fill="x")

        def do_reflect():
            try:
                reflect_right_to_left(session)
                target_var.set("left")
                status_var.set(
                    "Left half created (blue). Select Left/Right/Both and Move or Rotate to align "
                    "with the Nissl, then Load into BARCC."
                )
                redraw()
            except Exception as e:
                logger.error(f"Reflect failed: {e}", exc_info=True)
                messagebox.showerror("Reflect", str(e), parent=ed)

        def do_reset_transforms():
            session.right_dx = session.right_dy = session.right_angle = 0.0
            session.left_dx = session.left_dy = session.left_angle = 0.0
            status_var.set("Transforms reset.")
            redraw()

        def do_clear_left():
            session.mask_left = None
            session.border_left = None
            session.left_dx = session.left_dy = session.left_angle = 0.0
            status_var.set("Left half cleared.")
            redraw()

        ttk.Button(tb, text="Reflect → left half", command=do_reflect).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Clear left", command=do_clear_left).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Reset moves", command=do_reset_transforms).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill="y", padx=8)

        ttk.Label(tb, text="Edit:").pack(side=tk.LEFT)
        for lab, val in (("Left", "left"), ("Right", "right"), ("Both", "both")):
            ttk.Radiobutton(tb, text=lab, variable=target_var, value=val).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill="y", padx=8)
        ttk.Label(tb, text="Tool:").pack(side=tk.LEFT)
        ttk.Radiobutton(tb, text="Move", variable=tool_var, value="move").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(tb, text="Rotate", variable=tool_var, value="rotate").pack(side=tk.LEFT, padx=2)

        # --- nudge controls ---
        nudge = ttk.Frame(ed, padding=(6, 0, 6, 4))
        nudge.pack(fill="x")
        ttk.Label(nudge, text="Nudge step (px):").pack(side=tk.LEFT)
        ttk.Spinbox(nudge, from_=0.5, to=50, increment=0.5, width=6, textvariable=step_move).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Label(nudge, text="  Rotate step (°):").pack(side=tk.LEFT)
        ttk.Spinbox(nudge, from_=0.1, to=15, increment=0.1, width=6, textvariable=step_rot).pack(
            side=tk.LEFT, padx=2
        )

        def _apply_delta(ddx=0.0, ddy=0.0, dang=0.0):
            t = target_var.get()
            if t in ("left", "both"):
                if session.mask_left is None:
                    if t == "left":
                        status_var.set("No left half yet — click Reflect first.")
                        return
                else:
                    session.left_dx += ddx
                    session.left_dy += ddy
                    session.left_angle += dang
            if t in ("right", "both"):
                session.right_dx += ddx
                session.right_dy += ddy
                session.right_angle += dang
            redraw()

        nf = ttk.Frame(nudge)
        nf.pack(side=tk.LEFT, padx=12)
        ttk.Button(nf, text="↑", width=3, command=lambda: _apply_delta(ddy=-step_move.get())).grid(
            row=0, column=1
        )
        ttk.Button(nf, text="←", width=3, command=lambda: _apply_delta(ddx=-step_move.get())).grid(
            row=1, column=0
        )
        ttk.Button(nf, text="→", width=3, command=lambda: _apply_delta(ddx=step_move.get())).grid(
            row=1, column=2
        )
        ttk.Button(nf, text="↓", width=3, command=lambda: _apply_delta(ddy=step_move.get())).grid(
            row=2, column=1
        )
        ttk.Button(
            nudge, text="↺", width=3, command=lambda: _apply_delta(dang=step_rot.get())
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            nudge, text="↻", width=3, command=lambda: _apply_delta(dang=-step_rot.get())
        ).pack(side=tk.LEFT, padx=2)

        # --- canvas ---
        canvas_frame = ttk.Frame(ed)
        canvas_frame.pack(fill="both", expand=True, padx=6, pady=4)
        canvas = tk.Canvas(canvas_frame, bg="#222", highlightthickness=0)
        hsb = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)
        vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill="y")
        hsb.pack(side=tk.BOTTOM, fill="x")
        canvas.pack(side=tk.LEFT, fill="both", expand=True)

        def redraw(*_a):
            try:
                preview = compose_stitch_preview(session)
            except Exception as e:
                status_var.set(f"Preview error: {e}")
                return
            # Fit to canvas while allowing zoom
            cw = max(canvas.winfo_width(), 200)
            ch = max(canvas.winfo_height(), 200)
            pw, ph = preview.size
            fit = min(cw / pw, ch / ph, 1.0) * view_scale["s"]
            fit = max(0.15, min(fit, 4.0))
            disp_w = max(1, int(pw * fit))
            disp_h = max(1, int(ph * fit))
            disp = preview.resize((disp_w, disp_h), Image.BILINEAR)
            photos["img"] = ImageTk.PhotoImage(disp)
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=photos["img"], tags=("preview",))
            canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
            # store scale for drag conversion
            drag["scale"] = fit
            tinfo = (
                f"Right Δ=({session.right_dx:.1f},{session.right_dy:.1f}) "
                f"∠{session.right_angle:.2f}°"
            )
            if session.mask_left is not None:
                tinfo += (
                    f"  |  Left Δ=({session.left_dx:.1f},{session.left_dy:.1f}) "
                    f"∠{session.left_angle:.2f}°"
                )
            else:
                tinfo += "  |  Left: (not reflected)"
            # keep user status if set, append transform
            base = status_var.get().split("  ||  ")[0]
            status_var.set(f"{base}  ||  {tinfo}")

        def on_press(event):
            drag["active"] = True
            drag["x0"] = canvas.canvasx(event.x)
            drag["y0"] = canvas.canvasy(event.y)
            drag["mode"] = tool_var.get()
            drag["r0"] = (
                session.right_dx, session.right_dy, session.right_angle,
                session.left_dx, session.left_dy, session.left_angle,
            )

        def on_drag(event):
            if not drag.get("active"):
                return
            sc = drag.get("scale") or 1.0
            x = canvas.canvasx(event.x)
            y = canvas.canvasy(event.y)
            dx = (x - drag["x0"]) / sc
            dy = (y - drag["y0"]) / sc
            r0 = drag["r0"]
            t = target_var.get()
            mode = drag.get("mode") or "move"
            if mode == "move":
                if t in ("right", "both"):
                    session.right_dx = r0[0] + dx
                    session.right_dy = r0[1] + dy
                if t in ("left", "both") and session.mask_left is not None:
                    session.left_dx = r0[3] + dx
                    session.left_dy = r0[4] + dy
            else:
                # rotate: horizontal drag → degrees
                dang = dx * 0.15
                if t in ("right", "both"):
                    session.right_angle = r0[2] + dang
                if t in ("left", "both") and session.mask_left is not None:
                    session.left_angle = r0[5] + dang
            redraw()

        def on_release(event):
            drag["active"] = False

        def on_wheel(event):
            # zoom
            delta = getattr(event, "delta", 0) or 0
            if delta > 0 or getattr(event, "num", None) == 4:
                view_scale["s"] = min(4.0, view_scale["s"] * 1.1)
            else:
                view_scale["s"] = max(0.2, view_scale["s"] / 1.1)
            redraw()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        canvas.bind("<MouseWheel>", on_wheel)
        canvas.bind("<Button-4>", on_wheel)
        canvas.bind("<Button-5>", on_wheel)

        # --- bottom ---
        bot = ttk.Frame(ed, padding=6)
        bot.pack(fill="x")
        ttk.Label(bot, textvariable=status_var, wraplength=900).pack(side=tk.LEFT, fill="x", expand=True)

        def load_into_barcc():
            try:
                data = commit_stitch_session(session)
                self._load_allen_plate_data(data)
                ed.destroy()
                # close parent browser if still open
                try:
                    if parent is not None and parent.winfo_exists():
                        parent.destroy()
                except Exception:
                    pass
                hemi = (
                    "bilateral (reflected + manually aligned)\n"
                    if data.mirrored
                    else "as drawn\n"
                )
                messagebox.showinfo(
                    "Allen Atlas Loaded",
                    f"Loaded {plate_display_label(session.plate)}\n\n"
                    f"Structures: {len(data.zone_names)}\n"
                    f"Hemispheres: {hemi}"
                    "Movable atlas: structure borders only\n"
                    "Nissl reference: 30% above your image\n\n"
                    "Use Atlas → Move / Rotate / Scale / Crop to align with your TIFF.",
                )
            except Exception as e:
                logger.error(f"Commit stitch failed: {e}", exc_info=True)
                messagebox.showerror("Load into BARCC", str(e), parent=ed)

        ttk.Button(bot, text="Load into BARCC", command=load_into_barcc).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bot, text="Cancel", command=ed.destroy).pack(side=tk.RIGHT, padx=2)

        ed.after(80, redraw)
        ed.bind("<Configure>", lambda e: None)
        # redraw when first mapped
        def _first_draw(_e=None):
            redraw()
            canvas.unbind("<Map>")
        canvas.bind("<Map>", _first_draw)

    def _load_allen_plate_data(self, plate_data):
        """Install an AllenPlateData object as the current atlas (Phase 1+2).

        Movable atlas layer = structure borders only (transparent; PDF-like).
        Nissl is stored separately as a small reference strip above the main image.
        mask_images / zone_names hold Allen structure IDs and names for counting.
        """
        self.save_state()
        clear_preprocess_cache()

        # Borders-only atlas (what Move / Scale / Crop / Rotate act on)
        borders = plate_data.borders_rgba.convert("RGBA")
        mask = plate_data.mask_l
        if mask.size != borders.size:
            mask = mask.resize(borders.size, Image.NEAREST)

        # Pure Nissl for the 30% reference strip above the image (own size is fine)
        self.allen_nissl_reference = plate_data.nissl_rgba.convert("RGBA")
        # Keep a pure border layer to re-composite after yellow fills (so borders stay visible)
        self.allen_borders_pure = borders.copy()

        # Reset atlas / paint state similar to import_atlas, then install Allen layers
        self.path = f"allen://{plate_data.plate.image_id}"
        self.doc = None
        self.num_pages = 1
        self.atlas_filetype = "allen"
        self.zoom = 1.0
        self.view_scale = 1.0
        self.img_x = 0
        self.img_y = 0
        self.current_page = 0

        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.allen_zone_meta = {0: dict(plate_data.zone_meta)}  # page -> meta

        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        self.crop_mode = False
        self.crop_mode_var.set(False)
        self.edit_mode = False
        self.edit_mode_var.set(False)
        self.named_paint_groups.clear()
        self.paint_group_data.clear()
        self.painted_zone_outlines.clear()

        page = 0
        # Atlas layer = structure borders only (no Nissl underlay) — full SVG drawing
        self.base_page_images[page] = borders.copy()
        self.page_images[page] = borders.copy()
        self.mask_images[page] = mask.convert("L")
        self.zone_names[page] = {int(k): v for k, v in plate_data.zone_names.items()}
        # Ensure L/R hemisphere tags are visible as _l / _r in Atlas Manager + counts
        self._ensure_hemisphere_zone_suffixes(page)
        max_zid = max(self.zone_names[page].keys()) if self.zone_names[page] else 0
        self.zone_counters[page] = int(max_zid)

        self.img = borders.copy()
        # Do not put Allen borders on paint_layer — they live in the atlas overlay only
        self.paint_layer = None
        if self.original_background is not None:
            self.paint_layer = Image.new("RGBA", self.original_background.size, (0, 0, 0, 0))

        # Hollow borders by default; orange fill only when user selects a region
        self._rebuild_page_overlays(page)
        self.show_page()
        self._update_ribbon_selection()
        logger.info(
            f"Allen plate loaded (borders-only atlas + Nissl ref): id={plate_data.plate.image_id} "
            f"zones={len(self.zone_names[page])} atlas_size={borders.size} "
            f"nissl_size={self.allen_nissl_reference.size} mirrored={getattr(plate_data, 'mirrored', False)}"
        )

    def _ensure_hemisphere_zone_suffixes(self, page=None):
        """Normalize zone labels so hemispheres use ``_l`` / ``_r`` suffixes.

        Converts older ``(L)``/``(R)`` tags and applies meta.hemisphere when present
        so Atlas Manager and Count Cells clearly distinguish sides after Reflect.
        """
        if page is None:
            page = self.current_page
        names = self.zone_names.get(page) or {}
        if not names:
            return
        meta_page = {}
        try:
            meta_page = (getattr(self, "allen_zone_meta", None) or {}).get(page) or {}
        except Exception:
            meta_page = {}

        def _has_hemi_tag(s):
            s = str(s)
            low = s.lower()
            return (
                low.endswith("_l")
                or low.endswith("_r")
                or " (l)" in low
                or " (r)" in low
                or "_l:" in low
                or "_r:" in low
            )

        updated = {}
        for zid, label in names.items():
            zid = int(zid)
            label = str(label)
            meta = meta_page.get(zid) or meta_page.get(str(zid)) or {}
            hemi = str(meta.get("hemisphere") or "").strip().lower()
            if hemi in ("l", "left"):
                hemi = "l"
            elif hemi in ("r", "right"):
                hemi = "r"
            else:
                hemi = ""

            # Prefer explicit meta hemisphere; else detect legacy tags
            if not hemi:
                low = label.lower()
                if low.endswith(" (l)") or low.endswith("_l") or "_l:" in low or low.endswith(" (left)"):
                    hemi = "l"
                elif low.endswith(" (r)") or low.endswith("_r") or "_r:" in low or low.endswith(" (right)"):
                    hemi = "r"

            if not hemi:
                updated[zid] = label
                continue

            # Rebuild with canonical _l / _r via allen helper if available
            try:
                from allen_atlas import _format_hemisphere_zone_name
                updated[zid] = _format_hemisphere_zone_name(label, meta, hemi)
            except Exception:
                # Fallback: append _l/_r to acronym head
                base = label
                for tag in (" (L)", " (R)", " (l)", " (r)", "_L", "_R", "_l", "_r"):
                    if base.endswith(tag):
                        base = base[: -len(tag)]
                if ":" in base:
                    head, tail = base.split(":", 1)
                    head = head.strip()
                    if head.lower().endswith("_l") or head.lower().endswith("_r"):
                        head = head[:-2]
                    updated[zid] = f"{head}_{hemi}: {tail.strip()}"
                else:
                    head = base.strip()
                    if head.lower().endswith("_l") or head.lower().endswith("_r"):
                        head = head[:-2]
                    updated[zid] = f"{head}_{hemi}"

            # Keep meta display in sync
            if zid in meta_page or str(zid) in meta_page:
                key = zid if zid in meta_page else str(zid)
                try:
                    meta_page[key] = dict(meta_page[key])
                    meta_page[key]["hemisphere"] = hemi
                    meta_page[key]["display"] = updated[zid]
                except Exception:
                    pass

        self.zone_names[page] = updated
        if meta_page and hasattr(self, "allen_zone_meta"):
            self.allen_zone_meta[page] = meta_page

    def _compute_tiff_fit_scale(self, img_w, img_h):
        """Scale factor to fit a TIFF into the viewer without loading full resolution blindly."""
        ww = self.output.winfo_width()
        wh = self.output.winfo_height()
        if ww <= 1 or wh <= 1:
            # Canvas not laid out yet (common at startup) — estimate from window size.
            ww = max(self.master.winfo_width() - 280, 800)
            wh = max(self.master.winfo_height() - 120, 600)
        return min(ww / img_w, wh / img_h, 1.0)

    def _resize_tiff_for_viewer(self, bg_RGBA):
        """Return a display-sized RGBA copy suitable for in-memory processing."""
        bw, bh = bg_RGBA.size
        scale = self._compute_tiff_fit_scale(bw, bh)
        new_size = (max(1, int(bw * scale)), max(1, int(bh * scale)))
        if new_size == (bw, bh):
            return bg_RGBA.copy()
        return bg_RGBA.resize(new_size, Image.BILINEAR)

    def import_tiff(self):
        """Import a TIFF as a new session (atlas overlay is cleared).

        To keep the atlas when switching fluorescence channels, use
        File → Next Channel… / Atlas Manager → Next Channel… instead.
        """
        logger.info("Opening file dialog for TIFF selection")
        tiff_path = fd.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
        if tiff_path:
            # Shared loader; preserve_atlas=False clears ghost atlas + zones fully
            self._load_tiff_file(tiff_path, preserve_atlas=False)

    # ------------------------------------------------------------------
    # File Browser (Left Pane) - Directory TIFF selector + work tracker
    # Phase A: multi-state status, current highlight, last folder,
    #          progress summary, Next/Prev/Next Uncounted navigation
    # ------------------------------------------------------------------

    def _get_ui_prefs_path(self):
        """Path for lightweight UI prefs (last folder, etc.) under ~/.barc/."""
        prefs_dir = os.path.join(os.path.expanduser("~"), ".barc")
        try:
            os.makedirs(prefs_dir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(prefs_dir, "ui_prefs.json")

    def _save_ui_prefs(self):
        """Persist last working folder for restore on next launch."""
        try:
            prefs = {}
            path = self._get_ui_prefs_path()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        prefs = json.load(f) or {}
                except Exception:
                    prefs = {}
            if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
                prefs["last_tiff_directory"] = self.current_tiff_directory
            if getattr(self, "current_tiff_path", None) and os.path.isfile(self.current_tiff_path):
                prefs["last_tiff_path"] = self.current_tiff_path
            with open(path, "w", encoding="utf-8") as f:
                json.dump(prefs, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save UI prefs: {e}")

    def _restore_ui_prefs(self):
        """Restore last working folder into the File Browser (if still valid)."""
        try:
            path = self._get_ui_prefs_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                prefs = json.load(f) or {}
            directory = prefs.get("last_tiff_directory")
            if directory and os.path.isdir(directory):
                self.current_tiff_directory = directory
                if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
                    self.folder_label.config(text=directory)
                self.refresh_tiff_file_list()
                if hasattr(self, "file_browser_frame"):
                    self.file_browser_frame.after(50, self._update_folder_label_wraplength)
                last_path = prefs.get("last_tiff_path")
                if last_path and os.path.isfile(last_path):
                    self.current_tiff_path = last_path
                    self._highlight_current_tiff_in_tree()
        except Exception as e:
            logger.debug(f"Failed to restore UI prefs: {e}")

    def select_tiff_directory(self):
        """Let user choose a folder containing TIFF images."""
        initial = None
        if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            initial = self.current_tiff_directory
        directory = fd.askdirectory(title="Select folder containing TIFF images", initialdir=initial)
        if directory:
            self.current_tiff_directory = directory
            self.folder_label.config(text=directory)
            self.refresh_tiff_file_list()
            self._save_ui_prefs()
            # Force wraplength update after the text is set
            self.file_browser_frame.after(50, self._update_folder_label_wraplength)

    def _is_source_tiff_name(self, filename):
        """True if filename is a source TIFF (exclude BARCC product derivatives)."""
        lower = filename.lower()
        if not lower.endswith((".tif", ".tiff")):
            return False
        base = os.path.splitext(filename)[0].lower()
        for suffix in ("_masked", "_flattened"):
            if base.endswith(suffix):
                return False
        return True

    def _norm_path(self, path):
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(path))

    # Feature subfolders under <image_dir>/output/
    OUTPUT_FEATURES = (
        "counts",       # Count Cells: xlsx, masked.tif, centroids, metadata
        "intensities",  # region intensity + counterstain norm
        "pnn",          # perineuronal by-structure + per-cell tables
        "atlas",        # .catlas schematics
        "cell_masks",   # .barccmask, cellmask png, random cell masks
        "paint",        # paint layers / .barccpaint
        "flattened",    # flattened composites
    )

    def _get_output_directory(self, base_dir=None, feature=None, create=True):
        """Return <image_dir>/output[/<feature>], optionally creating it.

        Feature organizes exports by analysis type, e.g.:
          output/counts/, output/intensities/, output/pnn/, output/atlas/,
          output/cell_masks/, output/paint/, output/flattened/

        ``feature=None`` returns the root ``output/`` folder.
        Set ``create=False`` for open/browse dialogs so empty feature folders
        are not created merely by loading.
        """
        base = base_dir or self.tiff_dir or self.current_tiff_directory
        if not base:
            return None
        try:
            if not os.path.isdir(base):
                return None
            out = os.path.join(base, "output")
            if feature:
                # Normalize / sanitize feature name
                feat = str(feature).strip().strip("/\\").replace("..", "")
                if feat:
                    out = os.path.join(out, feat)
            if create:
                os.makedirs(out, exist_ok=True)
            elif not os.path.isdir(out):
                return None
            return out
        except Exception as e:
            logger.warning(f"Could not create/resolve output directory under {base}: {e}")
            return None

    def _preferred_open_dir(self, feature=None):
        """Best initialdir for open dialogs: output/<feature>/ if present, else output/, else image folder."""
        base = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            base = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            base = self.current_tiff_directory
        if not base:
            return None
        if feature:
            feat = self._get_output_directory(base, feature=feature, create=False)
            if feat and os.path.isdir(feat):
                return feat
        root = self._get_output_directory(base, feature=None, create=False)
        if root and os.path.isdir(root):
            return root
        return base

    def _artifact_search_dirs(self, tiff_dir):
        """Directories to search for BARCC exports.

        Order: each output/<feature>/, then flat output/ (legacy), then image folder.
        """
        dirs = []
        if not tiff_dir:
            return dirs
        out = os.path.join(tiff_dir, "output")
        if os.path.isdir(out):
            for feat in self.OUTPUT_FEATURES:
                feat_dir = os.path.join(out, feat)
                if os.path.isdir(feat_dir):
                    dirs.append(feat_dir)
            # Any other subfolders under output/ (future features)
            try:
                for name in sorted(os.listdir(out)):
                    p = os.path.join(out, name)
                    if os.path.isdir(p) and p not in dirs:
                        dirs.append(p)
            except Exception:
                pass
            # Legacy flat files still in output/
            dirs.append(out)
        if os.path.isdir(tiff_dir):
            dirs.append(tiff_dir)
        return dirs

    def _artifact_rel_prefix(self, search_dir, tiff_dir):
        """Display prefix for File Browser children, e.g. output/counts/."""
        try:
            rel = os.path.relpath(search_dir, tiff_dir)
            if rel in (".", ""):
                return ""
            return rel.replace("\\", "/") + "/"
        except Exception:
            base = os.path.basename(search_dir).lower()
            if base == "output":
                return "output/"
            parent = os.path.basename(os.path.dirname(search_dir)).lower()
            if parent == "output":
                return f"output/{base}/"
            return ""

    def _counted_result_candidates(self, base_name):
        """All known count export filenames for a TIFF stem (Count Cells + autosave)."""
        return [
            f"{base_name}.xlsx",
            f"{base_name}.csv",
            f"{base_name}_counted.xlsx",
            f"{base_name}_counted.csv",
            f"{base_name} - counted.xlsx",
            f"{base_name} - counted.csv",
            f"{base_name}_cells.xlsx",
            f"{base_name}_cells.csv",
            f"{base_name}_counts.xlsx",
            f"{base_name}_counts.csv",
        ]

    def _get_image_work_status(self, tiff_path, dir_files=None):
        """Return multi-state work status for a source TIFF.

        Looks in <folder>/output/<feature>/ first, then flat output/, then the
        image folder (legacy sidecars).
        Status labels (priority): Done (counted+masked) > Count > Paint > —

        counted_files / paint_files / masked_files entries are display labels
        (e.g. "output/counts/name.xlsx") for the File Browser tree children.
        """
        empty = {
            "counted": False,
            "painted": False,
            "masked": False,
            "status_label": "—",
            "counted_files": [],
            "paint_files": [],
            "masked_files": [],
            "flattened_files": [],
            "cell_centroid_files": [],
            "intensity_files": [],
        }
        if not tiff_path:
            return empty

        directory = os.path.dirname(tiff_path)
        base_name = os.path.splitext(os.path.basename(tiff_path))[0]
        base_l = base_name.lower()

        counted_files = []
        paint_files = []
        masked_files = []
        flattened_files = []
        metadata_files = []
        cell_centroid_files = []
        intensity_files = []
        seen = set()  # avoid listing the same basename twice (output + legacy)

        for search_dir in self._artifact_search_dirs(directory):
            rel_prefix = self._artifact_rel_prefix(search_dir, directory)
            try:
                listing = os.listdir(search_dir)
            except Exception:
                continue
            files_lower_map = {f.lower(): f for f in listing}

            for cand in self._counted_result_candidates(base_name):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    counted_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for f in listing:
                fl = f.lower()
                if fl.startswith(base_l + "_paint") and (fl.endswith(".png") or fl.endswith(".barccpaint")):
                    if fl not in seen:
                        paint_files.append(rel_prefix + f)
                        seen.add(fl)

            for cand in (f"{base_name}_masked.tif", f"{base_name}_masked.tiff"):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    masked_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (f"{base_name}_flattened.tif", f"{base_name}_flattened.tiff"):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    flattened_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (f"{base_name}_metadata.json", f"{base_name}_metadata.txt"):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    metadata_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (f"{base_name}_cell_centroids.csv",):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    cell_centroid_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (
                f"{base_name}_intensities.xlsx",
                f"{base_name}_intensities.csv",
                f"{base_name}_region_intensity.xlsx",
                f"{base_name}_region_intensity.csv",
                f"{base_name}_intensities_parameters.csv",
                f"{base_name}_counterstain_norm.xlsx",
                f"{base_name}_counterstain_norm.csv",
                f"{base_name}_pnn_by_structure.xlsx",
                f"{base_name}_pnn_by_structure.csv",
                f"{base_name}_pnn_cells_true.xlsx",
                f"{base_name}_pnn_cells_true.csv",
                f"{base_name}_pnn_cells_random.xlsx",
                f"{base_name}_pnn_cells_random.csv",
            ):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    intensity_files.append(rel_prefix + real)
                    seen.add(real.lower())

            # Cell masks + atlas schematics (per-channel name and stem without _chN)
            mask_candidates = [
                f"{base_name}_cellmask.barccmask",
                f"{base_name}_cellmask.png",
                f"{base_name}_random_cellmask.png",
                f"{base_name}_random_cellmask.json",
                f"{base_name}_atlas.catlas",
                f"{base_name}_atlas.atlas",
                f"{base_name}.catlas",
                f"{base_name}.atlas",
            ]
            stem = base_name
            for suffix in (
                "_ch0", "_ch1", "_ch2", "_ch3", "_c0", "_c1", "_c2", "_c3",
                "-ch0", "-ch1", "-ch2", "-ch3",
            ):
                if stem.lower().endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            if stem != base_name:
                mask_candidates.extend(
                    [
                        f"{stem}_cellmask.barccmask",
                        f"{stem}_cellmask.png",
                        f"{stem}_random_cellmask.png",
                        f"{stem}_random_cellmask.json",
                        f"{stem}_atlas.catlas",
                        f"{stem}_atlas.atlas",
                        f"{stem}.catlas",
                        f"{stem}.atlas",
                    ]
                )
            for cand in mask_candidates:
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    intensity_files.append(rel_prefix + real)  # show under TIFF children
                    seen.add(real.lower())

        counted = len(counted_files) > 0
        painted = len(paint_files) > 0
        masked = len(masked_files) > 0

        if counted and masked:
            label = "Done"
        elif counted:
            label = "Count"
        elif painted:
            label = "Paint"
        else:
            label = "—"

        return {
            "counted": counted,
            "painted": painted,
            "masked": masked,
            "status_label": label,
            "counted_files": counted_files,
            "paint_files": paint_files,
            "masked_files": masked_files,
            "flattened_files": flattened_files,
            "metadata_files": metadata_files,
            "cell_centroid_files": cell_centroid_files,
            "intensity_files": intensity_files,
        }

    def refresh_tiff_file_list(self):
        """Scan the current directory for source TIFFs and update the Treeview.

        Shows multi-state status (Done / Count / Paint / —) and child artifacts.
        Highlights the currently open TIFF when present.
        """
        if not self.current_tiff_directory or not os.path.isdir(self.current_tiff_directory):
            self._update_folder_progress_summary(0, 0, 0)
            return

        self.tiff_file_list = []
        self._tree_iid_to_path = {}
        self._tree_path_to_iid = {}

        try:
            files = os.listdir(self.current_tiff_directory)
            tiff_files = [f for f in files if self._is_source_tiff_name(f)]
            tiff_files.sort(key=str.lower)

            self.tiff_file_list = [os.path.join(self.current_tiff_directory, f) for f in tiff_files]

            counted_n = 0
            painted_n = 0

            if hasattr(self, "tiff_tree"):
                for item in self.tiff_tree.get_children():
                    self.tiff_tree.delete(item)

                for full_path in self.tiff_file_list:
                    filename = os.path.basename(full_path)
                    status = self._get_image_work_status(full_path)
                    if status["counted"]:
                        counted_n += 1
                    if status["painted"]:
                        painted_n += 1

                    tags = ()
                    if status["status_label"] == "Done":
                        tags = ("status_done",)
                    elif status["status_label"] == "Count":
                        tags = ("status_count",)
                    elif status["status_label"] == "Paint":
                        tags = ("status_paint",)

                    iid = self.tiff_tree.insert(
                        "",
                        "end",
                        text=filename,
                        values=(status["status_label"],),
                        tags=tags,
                        open=False,
                    )
                    self._tree_iid_to_path[iid] = full_path
                    self._tree_path_to_iid[self._norm_path(full_path)] = iid

                    for cand in status["counted_files"]:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status["paint_files"]:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status["masked_files"]:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("flattened_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("metadata_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("cell_centroid_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("intensity_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))

            total = len(self.tiff_file_list)
            self._update_folder_progress_summary(counted_n, painted_n, total)
            self._highlight_current_tiff_in_tree()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to read directory:\n{e}")

    def _update_folder_progress_summary(self, counted_n, painted_n, total):
        """Update the progress line: Counted x/y · Painted z · Remaining r."""
        if not hasattr(self, "progress_summary_var"):
            return
        if total <= 0:
            self.progress_summary_var.set("No images in folder")
            return
        remaining = max(0, total - counted_n)
        self.progress_summary_var.set(
            f"Counted {counted_n}/{total}  ·  Painted {painted_n}  ·  Remaining {remaining}"
        )

    def _update_folder_label_wraplength(self, event=None):
        """Dynamically set wraplength based on the current width of the file browser pane."""
        if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
            width = self.folder_label.winfo_width()
            if width > 50:
                new_wrap = max(60, width - 8)
                self.folder_label.configure(wraplength=new_wrap)

    def _has_matching_csv(self, tiff_path):
        """Check if a results file matching this TIFF exists (legacy API)."""
        return self._get_image_work_status(tiff_path).get("counted", False)

    def _highlight_current_tiff_in_tree(self):
        """Select and tag the currently open TIFF row; clear prior current tag."""
        if not hasattr(self, "tiff_tree"):
            return

        for iid in self.tiff_tree.get_children(""):
            tags = list(self.tiff_tree.item(iid, "tags") or ())
            if "current" in tags:
                tags = [t for t in tags if t != "current"]
                self.tiff_tree.item(iid, tags=tuple(tags))

        path = getattr(self, "current_tiff_path", None)
        if not path:
            if hasattr(self, "current_file_var"):
                self.current_file_var.set("")
            return

        if hasattr(self, "current_file_var"):
            self.current_file_var.set(f"Open: {os.path.basename(path)}")

        iid = getattr(self, "_tree_path_to_iid", {}).get(self._norm_path(path))
        if not iid:
            return

        tags = list(self.tiff_tree.item(iid, "tags") or ())
        if "current" not in tags:
            tags.append("current")
        self.tiff_tree.item(iid, tags=tuple(tags))
        try:
            self.tiff_tree.selection_set(iid)
            self.tiff_tree.focus(iid)
            self.tiff_tree.see(iid)
        except Exception:
            pass

    def _sync_file_browser_to_path(self, tiff_path):
        """Ensure File Browser shows the folder of tiff_path and highlights it."""
        if not tiff_path:
            return
        directory = os.path.dirname(tiff_path)
        if directory and os.path.isdir(directory):
            if self.current_tiff_directory != directory:
                self.current_tiff_directory = directory
                if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
                    self.folder_label.config(text=directory)
                self.refresh_tiff_file_list()
            self.current_tiff_path = tiff_path
            self._highlight_current_tiff_in_tree()
            self._save_ui_prefs()
        else:
            self.current_tiff_path = tiff_path

    def load_tiff_from_list(self, event=None):
        """Load the TIFF file that was double-clicked in the file browser Treeview.
        Child items (generated .xlsx or saved paint files/bundles) are ignored for loading.
        """
        if not hasattr(self, 'tiff_tree'):
            return

        selection = self.tiff_tree.selection()
        if not selection:
            return

        iid = selection[0]

        parent_iid = self.tiff_tree.parent(iid)
        if parent_iid:
            # Child item — filename lives in tree text (Phase A); fall back to values
            child_name = self.tiff_tree.item(iid, "text") or ""
            if not child_name:
                values = self.tiff_tree.item(iid, "values") or []
                child_name = values[0] if values else ""
            cl = child_name.lower()
            if (cl.endswith('.barccpaint') or cl.endswith('.png')) and '_paint' in cl:
                # Load the associated TIFF first if not already the current one
                if parent_iid in self._tree_iid_to_path:
                    parent_tiff_path = self._tree_iid_to_path[parent_iid]
                    # Load the background if it's not the current or to ensure
                    if not self.tiff_filename or self.tiff_filename not in os.path.basename(parent_tiff_path):
                        self._load_tiff_file(parent_tiff_path)
                    # Resolve paint path (supports "output/paint/foo.barccpaint" labels)
                    paint_name = child_name.replace("\\", "/")
                    parent_dir = os.path.dirname(parent_tiff_path)
                    basename = os.path.basename(paint_name)
                    if paint_name.lower().startswith("output/"):
                        paint_full_path = os.path.join(parent_dir, paint_name.replace("/", os.sep))
                    else:
                        paint_full_path = None
                        for search_dir in self._artifact_search_dirs(parent_dir):
                            cand = os.path.join(search_dir, basename)
                            if os.path.exists(cand):
                                paint_full_path = cand
                                break
                        if not paint_full_path:
                            paint_full_path = os.path.join(parent_dir, basename)
                    if paint_full_path.lower().endswith('.barccpaint'):
                        self._load_barccpaint_bundle(paint_full_path)
                    else:
                        # plain paint png (legacy)
                        self.img = Image.open(paint_full_path)
                        clear_preprocess_cache()
                        loaded_rgba = self.img.convert('RGBA') if self.img.mode != 'RGBA' else self.img
                        self.paint_layer = loaded_rgba
                        self.atlas_filetype = 'img'
                        self.show_page()
                        # try legacy sidecars relative to this paint file
                        try:
                            pbase = os.path.splitext(os.path.basename(paint_full_path))[0]
                            pdir = os.path.dirname(paint_full_path)
                            rj = os.path.join(pdir, pbase + "_regions.json")
                            zp = os.path.join(pdir, pbase + "_zones.png")
                            page = self.current_page
                            restored = False
                            if os.path.exists(rj):
                                with open(rj, "r", encoding="utf-8") as f:
                                    d = json.load(f)
                                nm = d.get("zone_names", {})
                                if nm:
                                    nm = {int(k): v for k, v in nm.items()}
                                    if page not in self.zone_names: self.zone_names[page] = {}
                                    self.zone_names[page].update(nm)
                                    restored = True
                                ol = d.get("painted_zone_outlines", {})
                                if ol:
                                    ol = {int(k): v for k, v in ol.items()}
                                    self.painted_zone_outlines.update(ol)
                                    restored = True
                            if os.path.exists(zp):
                                zm = Image.open(zp).convert('L')
                                try:
                                    if zm.mode != 'L':
                                        zm = zm.convert('L')
                                    zarr = np.array(zm).astype(np.uint8)
                                    zm = Image.fromarray(zarr, mode='L')
                                except Exception:
                                    pass
                                self.mask_images[page] = zm
                                restored = True
                            if restored:
                                if hasattr(self, '_update_ribbon_selection'):
                                    self._update_ribbon_selection()
                                if hasattr(self, '_rebuild_page_overlays'):
                                    try:
                                        self._rebuild_page_overlays(page)
                                    except:
                                        pass
                                self.show_page()
                        except:
                            pass
                return
            else:
                # other child, ignore
                return

        if iid in self._tree_iid_to_path:
            full_path = self._tree_iid_to_path[iid]
            self._load_tiff_file(full_path)

    def _build_file_browser(self, parent):
        """Builds the left-side file manager pane with multi-state status and progress."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        # Header: folder select + path
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))

        ttk.Button(header, text="Select Folder", command=self.select_tiff_directory).pack(fill='x')

        self.folder_label = ttk.Label(header, text="No folder selected", anchor='w', justify=tk.LEFT)
        self.folder_label.pack(fill='x', pady=(4, 0))

        # Dynamically adjust wraplength when the pane is resized
        header.bind("<Configure>", self._update_folder_label_wraplength)

        # Initial wraplength update after layout settles
        parent.after(150, self._update_folder_label_wraplength)

        # Progress summary (Counted n/N · Painted · Remaining)
        self.progress_summary_var = tk.StringVar(value="No folder selected")
        self.progress_summary_label = ttk.Label(
            parent,
            textvariable=self.progress_summary_var,
            anchor='w',
            justify=tk.LEFT,
            font=("Helvetica", 8),
            foreground="#333333",
        )
        self.progress_summary_label.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 2))

        # Currently open file line
        self.current_file_var = tk.StringVar(value="")
        self.current_file_label = ttk.Label(
            parent,
            textvariable=self.current_file_var,
            anchor='w',
            justify=tk.LEFT,
            font=("Helvetica", 8, "bold"),
            foreground="#0055aa",
        )
        self.current_file_label.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 2))

        # File list: tree column = Image name; status column = Done/Count/Paint/—
        columns = ("status",)
        self.tiff_tree = ttk.Treeview(parent, columns=columns, show="tree headings", selectmode="browse")
        self.tiff_tree.column("#0", width=150, minwidth=80, stretch=True, anchor="w")
        self.tiff_tree.heading("#0", text="Image", anchor="w")
        self.tiff_tree.column("status", width=52, minwidth=44, stretch=False, anchor="center")
        self.tiff_tree.heading("status", text="Status")

        try:
            self.tiff_tree.tag_configure("current", background="#cce5ff")
            self.tiff_tree.tag_configure("status_done", foreground="#0a7a0a")
            self.tiff_tree.tag_configure("status_count", foreground="#0066aa")
            self.tiff_tree.tag_configure("status_paint", foreground="#b36b00")
            self.tiff_tree.tag_configure("child", foreground="#555555")
        except Exception:
            pass

        self.tiff_tree.grid(row=3, column=0, sticky='nsew', padx=4, pady=2)
        self.tiff_tree.bind("<Double-Button-1>", self.load_tiff_from_list)
        self.tiff_tree.bind("<Return>", self.load_tiff_from_list)

        # Store mapping from iid to full path
        self._tree_iid_to_path = {}
        self._tree_path_to_iid = {}

        # Navigation row
        nav = ttk.Frame(parent)
        nav.grid(row=4, column=0, sticky='ew', padx=4, pady=(2, 0))
        nav.columnconfigure(0, weight=1)
        nav.columnconfigure(1, weight=1)
        nav.columnconfigure(2, weight=1)
        ttk.Button(nav, text="◀ Prev", width=8, command=self.previous_image).grid(
            row=0, column=0, sticky='ew', padx=(0, 2)
        )
        ttk.Button(nav, text="Next ▶", width=8, command=self.next_image).grid(
            row=0, column=1, sticky='ew', padx=2
        )
        ttk.Button(nav, text="Next uncounted", width=12, command=self.next_uncounted_image).grid(
            row=0, column=2, sticky='ew', padx=(2, 0)
        )

        # Next Channel: switch TIFF while keeping atlas schematic + Atlas Manager regions
        ttk.Button(
            parent,
            text="Next Channel… (keep atlas)",
            command=self.next_channel,
        ).grid(row=5, column=0, sticky='ew', padx=4, pady=(4, 0))

        # Refresh button
        ttk.Button(parent, text="Refresh", command=self.refresh_tiff_file_list).grid(
            row=6, column=0, sticky='ew', padx=4, pady=(4, 4)
        )

    def _clear_atlas_state(self, *, clear_paint=True, refresh_ui=False):
        """Remove atlas drawings, zone mask/names, and related manager state.

        Does not touch the loaded TIFF background. Used by Clear Atlas and by
        normal image loads that should not leave a ghost overlay.
        """
        self.atlas_filetype = None
        self.page_images = {}
        self.base_page_images = {}
        self.mask_images = {}
        self.zone_names = {}
        self.zone_counters = {}
        self.allen_zone_meta = {}
        self.allen_borders_pure = None
        self.allen_nissl_reference = None
        self.allen_nissl_photo = None
        self.img = None
        # Placement only meaningful with an atlas
        self.img_x = 0
        self.img_y = 0

        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        try:
            self._clear_edge_highlight()
        except Exception:
            pass
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        if hasattr(self, "region_move_mode"):
            self.region_move_mode.set(False)

        self.named_paint_groups = {}
        self.paint_group_data = {}
        self.painted_zone_outlines = {}
        self.current_paint_group = None
        if clear_paint:
            if self.original_background is not None:
                self.paint_layer = Image.new(
                    "RGBA", self.original_background.size, (0, 0, 0, 0)
                )
            else:
                self.paint_layer = None

        # PDF/Allen document path for atlas only (keep TIFF path separate)
        if isinstance(getattr(self, "path", None), str) and (
            str(self.path).lower().endswith(".pdf")
            or str(self.path).startswith("allen://")
        ):
            self.path = None
            self.doc = None

        if refresh_ui:
            try:
                clear_preprocess_cache()
            except Exception:
                pass
            try:
                self.show_page()
            except Exception:
                pass
            try:
                self._update_ribbon_selection()
            except Exception:
                pass
            try:
                self._refresh_zone_counts_table()
            except Exception:
                pass

    def clear_atlas(self):
        """Atlas Manager / menu: clear the atlas overlay and all labeled regions."""
        has_atlas = bool(
            getattr(self, "atlas_filetype", None)
            or self.base_page_images
            or self.page_images
            or any(bool(v) for v in (self.zone_names or {}).values())
            or bool(getattr(self, "painted_zone_outlines", None))
            or bool(getattr(self, "allen_borders_pure", None))
        )
        if not has_atlas:
            for m in (self.mask_images or {}).values():
                if m is None:
                    continue
                try:
                    if int(np.array(m).max()) > 0:
                        has_atlas = True
                        break
                except Exception:
                    has_atlas = True
                    break
        if not has_atlas:
            messagebox.showinfo("Clear Atlas", "There is no atlas or labeled regions to clear.")
            return
        if not messagebox.askyesno(
            "Clear Atlas",
            "Remove the atlas drawing, all structures in the Atlas Manager, "
            "zone masks, and painted region outlines?\n\n"
            "The loaded TIFF image will be kept.\n"
            "This cannot be undone after the next action (Undo may still reverse if used immediately).",
        ):
            return
        try:
            self.save_state()
        except Exception:
            pass
        self._clear_atlas_state(clear_paint=True, refresh_ui=True)
        logger.info("Atlas cleared by user (Clear Atlas)")
        messagebox.showinfo(
            "Atlas Cleared",
            "Atlas overlay and all labeled regions were removed.\n"
            "The TIFF image remains loaded.",
        )

    def next_channel(self):
        """Pick a new TIFF (e.g. next fluorescence channel) while keeping the atlas.

        Preserves atlas drawings, zone mask, Atlas Manager names, painted regions,
        and placement (img_x/img_y). Only the background image and per-image cell
        masks/counts are replaced.
        """
        initial_dir = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            initial_dir = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            initial_dir = self.current_tiff_directory

        path = fd.askopenfilename(
            title="Next Channel — select image (atlas is kept)",
            initialdir=initial_dir,
            filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")],
        )
        if not path:
            return

        # Autosave counts/paint for the channel we are leaving
        try:
            self._autosave_before_image_switch()
        except Exception as e:
            logger.debug(f"Autosave before next channel: {e}")

        ok = self._load_tiff_file(path, preserve_atlas=True)
        if ok:
            n_zones = 0
            page = self.current_page if self.current_page is not None else 0
            try:
                n_zones = len(self.zone_names.get(page, {}) or {})
            except Exception:
                pass
            logger.info(
                f"Next Channel loaded {path} with atlas preserved "
                f"(zones={n_zones}, filetype={self.atlas_filetype})"
            )

    def _load_tiff_file(self, tiff_path, preserve_atlas=False):
        """Core TIFF loading logic (shared between manual import and file browser).

        preserve_atlas=True (Next Channel): keep drawings, zone mask, names,
        paint outlines, and placement so the same schematic applies to another
        channel without reloading the atlas (avoids double overlays).
        """
        if not tiff_path or not os.path.exists(tiff_path):
            messagebox.showerror("Error", "Selected file does not exist.")
            return False

        logger.info(
            f"Loading TIFF: {tiff_path} (preserve_atlas={preserve_atlas})"
        )

        # Snapshot atlas state before any resets when preserving
        saved_atlas = None
        if preserve_atlas:
            saved_atlas = {
                "atlas_filetype": getattr(self, "atlas_filetype", None),
                "page_images": dict(self.page_images or {}),
                "base_page_images": dict(self.base_page_images or {}),
                "mask_images": dict(self.mask_images or {}),
                "zone_names": {p: dict(n) for p, n in (self.zone_names or {}).items()},
                "zone_counters": dict(self.zone_counters or {}),
                "allen_zone_meta": getattr(self, "allen_zone_meta", {}) or {},
                "allen_borders_pure": getattr(self, "allen_borders_pure", None),
                "allen_nissl_reference": getattr(self, "allen_nissl_reference", None),
                "img_x": float(getattr(self, "img_x", 0) or 0),
                "img_y": float(getattr(self, "img_y", 0) or 0),
                "img": getattr(self, "img", None),
                "path": getattr(self, "path", None),
                "doc": getattr(self, "doc", None),
                "num_pages": getattr(self, "num_pages", 0),
                "current_page": getattr(self, "current_page", 0),
                "painted_zone_outlines": copy.deepcopy(
                    getattr(self, "painted_zone_outlines", {}) or {}
                ),
                "paint_group_data": copy.deepcopy(
                    getattr(self, "paint_group_data", {}) or {}
                ),
                "named_paint_groups": dict(
                    getattr(self, "named_paint_groups", {}) or {}
                ),
                "paint_layer": (
                    self.paint_layer.copy()
                    if getattr(self, "paint_layer", None) is not None
                    else None
                ),
                "old_bg_size": (
                    list(self.original_background.size)
                    if self.original_background is not None
                    else (
                        list(self.background_image.size)
                        if self.background_image is not None
                        else None
                    )
                ),
            }

        if self.current_page is None:
            self.current_page = 0

        if not preserve_atlas:
            # Full clear including ghost atlas drawings (prevents double overlay on reload)
            self._clear_atlas_state(clear_paint=True, refresh_ui=False)
            self.view_scale = 1.0
            self.last_cell_mask = None
        else:
            # Per-image analysis only; atlas kept via snapshot restore after load
            self.view_scale = 1.0
            self.last_cell_mask = None
            self.selected_zone_id = None
            self.selected_page = None
            self.selected_zone_component = None
            try:
                self._clear_edge_highlight()
            except Exception:
                pass
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.original_full_contour_for_edit = None
            self.selected_edge_full_contour = None
            self._edge_pending_deselect = False
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            if hasattr(self, "region_move_mode"):
                self.region_move_mode.set(False)

        self.crop_mode = False
        self.crop_mode_var.set(False)
        self.edit_mode = False
        self.edit_mode_var.set(False)

        # Clear cell masks on every image switch (re-load via Load Cell Mask if needed)
        self.manual_add_mask = None
        self.manual_remove_mask = None
        self.editing_mask = False
        self.current_mask = None
        self.auto_mask = None
        self.showing_auto_mask = False
        self.last_df = None
        self.last_cell_mask = None
        self.cell_mask_locked = False
        self.cell_mask_source_path = None
        self.random_cell_mask = None
        self.random_cell_labels = None
        self.random_cell_mask_meta = None
        self.perineuronal_mask = None
        self.perineuronal_labels = None
        self.perineuronal_cells = None
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None

        self.tiff_dir = os.path.dirname(tiff_path)
        self.tiff_filename = os.path.splitext(os.path.basename(tiff_path))[0]

        try:
            bg = Image.open(tiff_path)
            array = np.array(bg)

            if array.ndim == 2 or (array.ndim == 3 and array.shape[2] == 1):
                array = np.squeeze(array)
                array_norm = (array - array.min()) / (array.max() - array.min() + 1e-8) * 255
                bg_RGBA = Image.fromarray(array_norm.astype(np.uint8)).convert('RGBA')
            elif array.max() <= 1.0:
                array = (array * 255).astype(np.uint8)
                bg_RGBA = Image.fromarray(array).convert('RGBA')
            else:
                bg_RGBA = bg.convert('RGBA')

            self.background_image = self._resize_tiff_for_viewer(bg_RGBA)
            self.original_background = self.background_image.copy()
            self._invalidate_bg_display_cache()

            if preserve_atlas and saved_atlas is not None:
                # Restore full atlas schematic
                self.atlas_filetype = saved_atlas["atlas_filetype"]
                self.page_images = saved_atlas["page_images"]
                self.base_page_images = saved_atlas["base_page_images"]
                self.mask_images = saved_atlas["mask_images"]
                self.zone_names = saved_atlas["zone_names"]
                self.zone_counters = saved_atlas["zone_counters"]
                self.allen_zone_meta = saved_atlas["allen_zone_meta"]
                self.allen_borders_pure = saved_atlas["allen_borders_pure"]
                self.allen_nissl_reference = saved_atlas["allen_nissl_reference"]
                self.img_x = saved_atlas["img_x"]
                self.img_y = saved_atlas["img_y"]
                self.img = saved_atlas["img"]
                self.path = saved_atlas["path"]
                self.doc = saved_atlas["doc"]
                self.num_pages = saved_atlas["num_pages"]
                if saved_atlas["current_page"] is not None:
                    self.current_page = saved_atlas["current_page"]
                self.painted_zone_outlines = saved_atlas["painted_zone_outlines"]
                self.paint_group_data = saved_atlas["paint_group_data"]
                self.named_paint_groups = saved_atlas["named_paint_groups"]

                # Paint layer: keep if same size; scale if channel dims differ
                pl = saved_atlas["paint_layer"]
                new_size = self.original_background.size
                old_size = saved_atlas["old_bg_size"]
                if pl is not None:
                    if list(pl.size) == list(new_size):
                        self.paint_layer = pl
                    else:
                        try:
                            self.paint_layer = pl.resize(new_size, Image.NEAREST)
                            logger.info(
                                f"Next Channel: scaled paint_layer {pl.size} → {new_size}"
                            )
                        except Exception:
                            self.paint_layer = Image.new("RGBA", new_size, (0, 0, 0, 0))
                else:
                    self.paint_layer = Image.new("RGBA", new_size, (0, 0, 0, 0))

                # If background size changed and atlas was 1:1 with old bg, scale atlas too
                if (
                    old_size
                    and list(old_size) != list(new_size)
                    and self.current_page in self.base_page_images
                    and self.base_page_images[self.current_page] is not None
                ):
                    base = self.base_page_images[self.current_page]
                    if list(base.size) == list(old_size):
                        page = self.current_page
                        is_allen = getattr(self, "atlas_filetype", None) == "allen"
                        resample = Image.NEAREST if is_allen else Image.BILINEAR
                        target = tuple(int(s) for s in new_size)
                        sx = new_size[0] / float(old_size[0])
                        sy = new_size[1] / float(old_size[1])
                        self.base_page_images[page] = base.resize(target, resample)
                        if page in self.page_images and self.page_images[page] is not None:
                            self.page_images[page] = self.page_images[page].resize(
                                target, resample
                            )
                        if page in self.mask_images and self.mask_images[page] is not None:
                            self.mask_images[page] = self.mask_images[page].resize(
                                target, Image.NEAREST
                            )
                        pure = getattr(self, "allen_borders_pure", None)
                        if pure is not None:
                            self.allen_borders_pure = pure.resize(target, Image.NEAREST)
                        self.img_x = float(self.img_x) * sx
                        self.img_y = float(self.img_y) * sy
                        if self.img is not None:
                            try:
                                self.img = self.base_page_images[page].copy()
                            except Exception:
                                pass
                        logger.info(
                            f"Next Channel: scaled atlas with background "
                            f"{old_size} → {new_size}"
                        )
            else:
                self.paint_layer = Image.new(
                    "RGBA", self.original_background.size, (0, 0, 0, 0)
                )

            self.current_tiff_path = tiff_path

            # Rebuild overlays so fills/borders match preserved mask
            if preserve_atlas:
                try:
                    page = self.current_page if self.current_page is not None else 0
                    if page in self.base_page_images:
                        self._rebuild_page_overlays(page)
                except Exception as e:
                    logger.debug(f"rebuild overlays after next channel: {e}")

            self.show_page()
            self._refresh_zone_counts_table()
            if preserve_atlas and self.show_zone_intensity_labels_var.get():
                try:
                    self.last_intensity_df = None  # recompute for new channel
                    self._refresh_zone_intensity_table()
                    self.show_page()
                except Exception:
                    pass
            else:
                self.last_intensity_df = None
                if not preserve_atlas:
                    try:
                        self._close_zone_intensity_window()
                        self.show_zone_intensity_labels_var.set(False)
                    except Exception:
                        pass
            try:
                self._update_ribbon_selection()
            except Exception:
                pass

            # Keep left File Browser folder + highlight aligned with loaded image
            self._sync_file_browser_to_path(tiff_path)

            # New document — clear undo (masks/images sizes may differ)
            try:
                self.state_manager.undo_stack.clear()
            except Exception:
                self.state_manager.undo_stack = []

            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load TIFF:\n{e}")
            logger.error(f"Failed to load TIFF {tiff_path}: {e}")
            return False

    def _compose_flattened_image(self):
        """Build RGB composite: TIFF + zone fills + atlas + paint + cell rings.

        Zone fills use ``_zone_mask_registered_to_background`` so atlas-sized masks
        are placed at ``img_x``/``img_y`` (same as on-screen and Count Cells). Stretching
        a model-space mask to full TIFF size misaligned yellow fills vs atlas borders.
        """
        base_img = getattr(self, "original_background", None) or getattr(
            self, "background_image", None
        )
        if (
            base_img is None
            or not hasattr(base_img, "size")
            or base_img.size[0] <= 0
            or base_img.size[1] <= 0
        ):
            return None

        bg_w, bg_h = base_img.size
        composite = base_img.convert("RGBA")

        # Integer model-space offsets (same units as atlas / page_images placement)
        paste_x = int(round(float(self.img_x))) if self.img_x is not None else 0
        paste_y = int(round(float(self.img_y))) if self.img_y is not None else 0

        try:
            # Explicit zone fill so regions are visible (Allen is often borders-only on screen).
            # Must register to background space — never stretch atlas masks to full image size.
            page = self.current_page
            if page in getattr(self, "mask_images", {}) and self.mask_images.get(page) is not None:
                try:
                    m, _mw, _mh = self._zone_mask_registered_to_background(
                        self.mask_images[page], bg_h, bg_w
                    )
                    zone_tint = np.zeros((bg_h, bg_w, 4), dtype=np.uint8)
                    for zid in np.unique(m):
                        if int(zid) == 0:
                            continue
                        reg = m == zid
                        zone_tint[reg, :3] = [255, 255, 0]  # yellow
                        zone_tint[reg, 3] = 55
                    if np.any(zone_tint[..., 3] > 0):
                        zone_img = Image.fromarray(zone_tint, "RGBA")
                        composite = Image.alpha_composite(composite, zone_img)
                except Exception as e:
                    logger.debug(f"Could not apply zone mask fill: {e}")

            # Atlas drawings / page overlay at model-space placement
            if page in getattr(self, "page_images", {}):
                at_img = self.page_images[page]
                if at_img is not None:
                    if at_img.mode != "RGBA":
                        at_img = at_img.convert("RGBA")
                    # Atlas is model-sized; paste at offset. If it already matches the
                    # full background (paint-as-atlas / fit-to-image), paste at 0,0 when
                    # sizes match — still correct when paste_x/y are 0 after Fit.
                    aw, ah = at_img.size
                    if abs(aw - bg_w) < 5 and abs(ah - bg_h) < 5 and abs(paste_x) < 2 and abs(paste_y) < 2:
                        if (aw, ah) != (bg_w, bg_h):
                            at_img = at_img.resize((bg_w, bg_h), Image.NEAREST)
                        composite.paste(at_img, (0, 0), at_img)
                    else:
                        composite.paste(at_img, (paste_x, paste_y), at_img)

            # Paint layer is baked into background pixel space (origin 0,0)
            if getattr(self, "paint_layer", None) is not None:
                pl = self.paint_layer
                if pl.mode != "RGBA":
                    pl = pl.convert("RGBA")
                if pl.size != (bg_w, bg_h):
                    # Prefer top-left paste of native paint; only resize when nearly full-frame
                    pw, ph = pl.size
                    if abs(pw - bg_w) < 5 and abs(ph - bg_h) < 5:
                        pl = pl.resize((bg_w, bg_h), Image.NEAREST)
                        composite.paste(pl, (0, 0), pl)
                    else:
                        composite.paste(pl, (0, 0), pl)
                else:
                    composite.paste(pl, (0, 0), pl)

            # Cell detections as open red donut rings
            if getattr(self, "last_cell_mask", None) is not None:
                try:
                    cell_mask = np.asarray(self.last_cell_mask).squeeze()
                    if cell_mask.ndim != 2:
                        if cell_mask.size > 0:
                            cell_mask = cell_mask.reshape(cell_mask.shape[0], -1)
                        else:
                            cell_mask = np.zeros((bg_h, bg_w), dtype=bool)
                    cell_mask = cell_mask > 0
                    ring_overlay = self._cell_detection_ring_overlay(
                        cell_mask,
                        size=(bg_w, bg_h),
                        color=(255, 0, 0),
                        alpha=200,
                        thickness=2,
                    )
                    composite = Image.alpha_composite(composite, ring_overlay)
                except Exception as e:
                    logger.debug(f"Could not overlay cell mask rings: {e}")
        except Exception as e:
            logger.debug(f"Could not apply overlays in flattened compose (base only): {e}")

        return composite.convert("RGB")

    def save_flattened_image(self, event=None):
        logger.info("Attempting to save flattened image")
        final = self._compose_flattened_image()
        if final is None:
            logger.warning("Save flattened image failed: No valid background image")
            messagebox.showerror("Error", "Please load a valid TIFF image first.")
            return

        # Default filename: original image name + _flattened + .tif
        default_name = "flattened.tif"
        if getattr(self, "tiff_filename", None):
            default_name = f"{self.tiff_filename}_flattened.tif"

        # Default into <image_dir>/output/flattened/ when available
        base_for_out = getattr(self, "tiff_dir", None) or getattr(
            self, "current_tiff_directory", None
        )
        out_dir = (
            self._get_output_directory(base_for_out, feature="flattened")
            if base_for_out
            else None
        )
        initialdir = out_dir or base_for_out or "."
        save_path = fd.asksaveasfilename(
            title="Save Flattened Image",
            initialdir=initialdir,
            initialfile=default_name,
            defaultextension=".tif",
            filetypes=[
                ("TIFF files", "*.tif *.tiff"),
                ("JPEG files", "*.jpg"),
                ("All files", "*.*"),
            ],
        )
        if save_path:
            try:
                # Do not pass compression='tiff_deflate' — it can segfault on some Windows Pillow + libtiff builds.
                final.save(save_path)
                messagebox.showinfo(
                    "Image Saved",
                    f"Flattened image (TIFF + regions + atlas + cells) saved to:\n{save_path}",
                )
            except Exception as e:
                logger.error(f"Failed to save flattened: {e}")
                messagebox.showerror("Save Error", f"Could not save the image:\n{e}")

    def autosave_flattened_image(self, filename):
        final = self._compose_flattened_image()
        if final is None:
            return
        try:
            # Do not pass compression='tiff_deflate' — it can segfault on some Windows Pillow + libtiff builds.
            final.save(filename)
        except Exception as e:
            logger.error(f"Autosave flattened failed: {e}")

    def toggle_crop_mode(self):
        self.save_state()
        self.crop_mode = not self.crop_mode
        self.crop_mode_var.set(self.crop_mode)
        if self.crop_mode:
            self.region_move_mode.set(False)
            self.border_mode_var.set(False)
            if getattr(self, "edit_mode", False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.region_translate_active = False
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self._clear_crop_ui()
            self.output.bind("<Button-1>", self.crop_start)
            self.output.bind("<B1-Motion>", self.crop_drag)
            self.output.bind("<ButtonRelease-1>", self.crop_end)
            self.output.bind("<Double-Button-1>", self._crop_double_click_apply)
            self.output.config(cursor="crosshair")
            self._set_crop_status(
                "Crop: drag to outline · drag box to move · Enter/double-click to apply · Esc to clear"
            )
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")
            self.output.unbind("<ButtonRelease-1>")
            try:
                self.output.unbind("<Double-Button-1>")
            except Exception:
                pass
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.output.config(cursor="")
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self._clear_crop_ui()
            self._set_crop_status(None)

    def _set_crop_status(self, text):
        """Show crop instructions in the window title while crop mode is active."""
        base = "Regional IF Analyzer"
        try:
            if getattr(self, "current_state", None) == "paint":
                # paint indicator owns the title
                return
            if text:
                self.master.title(f"{base} — {text}")
            else:
                cur = self.master.title() or base
                if "Crop:" in cur:
                    self.master.title(base)
        except Exception:
            pass

    def _clear_crop_ui(self):
        """Remove crop outline / shade overlays from the canvas."""
        ids = list(getattr(self, "crop_ui_ids", None) or [])
        if self.crop_rect is not None and self.crop_rect not in ids:
            ids.append(self.crop_rect)
        for iid in ids:
            try:
                self.output.delete(iid)
            except Exception:
                pass
        try:
            self.output.delete("crop_ui")
        except Exception:
            pass
        self.crop_ui_ids = []
        self.crop_rect = None

    def _normalize_crop_box(self, x1, y1, x2, y2):
        left, right = (x1, x2) if x1 <= x2 else (x2, x1)
        top, bottom = (y1, y2) if y1 <= y2 else (y2, y1)
        return float(left), float(top), float(right), float(bottom)

    def _point_in_crop_box(self, x, y, margin=0.0):
        if not self.crop_box:
            return False
        left, top, right, bottom = self.crop_box
        return (left - margin) <= x <= (right + margin) and (top - margin) <= y <= (
            bottom + margin
        )

    def _draw_crop_outline(self):
        """Draw a clear crop frame: dim outside, dual outline, move hint."""
        self._clear_crop_ui()
        if not self.crop_box:
            return
        left, top, right, bottom = self.crop_box
        if right - left < 1 or bottom - top < 1:
            return

        # Canvas extent for outside dimming
        try:
            bb = self.output.bbox("all")
        except Exception:
            bb = None
        if bb:
            cx0, cy0, cx1, cy1 = bb
        else:
            cx0, cy0 = 0, 0
            cx1 = max(int(self.output.winfo_width()), int(right) + 50)
            cy1 = max(int(self.output.winfo_height()), int(bottom) + 50)
        # Expand a bit so shade covers empty margins
        pad = 4000
        cx0, cy0 = min(cx0, left) - pad, min(cy0, top) - pad
        cx1, cy1 = max(cx1, right) + pad, max(cy1, bottom) + pad

        ids = []
        # Four shade panels outside the crop window (stipple ≈ semi-transparent)
        shade_kw = dict(fill="#000000", stipple="gray50", outline="", tags="crop_ui")
        # Top
        if top > cy0:
            ids.append(
                self.output.create_rectangle(cx0, cy0, cx1, top, **shade_kw)
            )
        # Bottom
        if bottom < cy1:
            ids.append(
                self.output.create_rectangle(cx0, bottom, cx1, cy1, **shade_kw)
            )
        # Left (between top/bottom of crop)
        if left > cx0:
            ids.append(
                self.output.create_rectangle(cx0, top, left, bottom, **shade_kw)
            )
        # Right
        if right < cx1:
            ids.append(
                self.output.create_rectangle(right, top, cx1, bottom, **shade_kw)
            )

        # High-contrast outline: white underlay + solid red crop frame
        ids.append(
            self.output.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline="#ffffff",
                width=5,
                tags="crop_ui",
            )
        )
        self.crop_rect = self.output.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#ff1a1a",
            width=3,
            dash=(),
            tags="crop_ui",
        )
        ids.append(self.crop_rect)

        # Corner ticks for a clear “window” look
        tick = max(8.0, min(24.0, 0.08 * min(right - left, bottom - top)))
        tick_kw = dict(fill="#ff1a1a", width=3, tags="crop_ui")
        for x, y, dx, dy in (
            (left, top, tick, 0),
            (left, top, 0, tick),
            (right, top, -tick, 0),
            (right, top, 0, tick),
            (left, bottom, tick, 0),
            (left, bottom, 0, -tick),
            (right, bottom, -tick, 0),
            (right, bottom, 0, -tick),
        ):
            ids.append(self.output.create_line(x, y, x + dx, y + dy, **tick_kw))

        # Instruction label just above the box
        label = "Crop window — drag to move · Enter to apply · Esc clear · click outside to re-draw"
        if self.crop_pending:
            # Shadow first, then light text on top
            ids.append(
                self.output.create_text(
                    (left + right) / 2.0 + 1,
                    top - 13,
                    text=label,
                    fill="#000000",
                    font=("Helvetica", 10, "bold"),
                    anchor="s",
                    tags="crop_ui",
                )
            )
            ids.append(
                self.output.create_text(
                    (left + right) / 2.0,
                    top - 14,
                    text=label,
                    fill="#ffdddd",
                    font=("Helvetica", 10, "bold"),
                    anchor="s",
                    tags="crop_ui",
                )
            )

        self.crop_ui_ids = ids
        try:
            self.output.tag_raise("crop_ui")
        except Exception:
            pass

    def _brain_image_aspect_ratio(self):
        """Width/height of the loaded brain-slice TIFF (for locked crop aspect).

        Returns None if no image is loaded.
        """
        bg = None
        if getattr(self, "original_background", None) is not None:
            bg = self.original_background
        elif getattr(self, "background_image", None) is not None:
            bg = self.background_image
        if bg is None:
            return None
        w, h = bg.size
        if w < 1 or h < 1:
            return None
        return float(w) / float(h)

    def _lock_crop_corner_to_image_aspect(self, start_x, start_y, cur_x, cur_y):
        """Return (end_x, end_y) so the crop rect matches the brain-image aspect ratio.

        Anchor is (start_x, start_y); the free corner is adjusted toward (cur_x, cur_y)
        while enforcing W/H = image aspect. If no image is loaded, returns the raw corner.
        """
        ar = self._brain_image_aspect_ratio()
        if ar is None or ar <= 0:
            return cur_x, cur_y

        dx = cur_x - start_x
        dy = cur_y - start_y
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return cur_x, cur_y

        # Choose width- or height-driven sizing so the rubber-band grows toward the cursor
        # while keeping aspect = image W/H.
        if abs(dy) < 1e-6 or abs(dx) >= abs(dy) * ar:
            # Width-driven
            w = abs(dx) if abs(dx) >= 1e-6 else abs(dy) * ar
            h = w / ar
        else:
            # Height-driven
            h = abs(dy)
            w = h * ar

        # Preserve drag direction (which quadrant)
        sx = 1.0 if dx >= 0 else -1.0
        sy = 1.0 if dy >= 0 else -1.0
        # If user only moved on one axis, still expand with positive sense on the other
        if abs(dx) < 1e-6:
            sx = 1.0
        if abs(dy) < 1e-6:
            sy = 1.0

        end_x = start_x + sx * w
        end_y = start_y + sy * h
        return end_x, end_y

    def crop_start(self, event):
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        self.start_x = cx
        self.start_y = cy

        # Pending selection: drag inside to move; click outside to re-draw
        if self.crop_pending and self.crop_box and self._point_in_crop_box(cx, cy):
            self._crop_interaction = "move"
            self._crop_move_origin = (cx, cy)
            self._crop_box_at_move_start = tuple(self.crop_box)
            self.output.config(cursor="fleur")
            return

        # Start a new rubber-band draw
        self._crop_interaction = "draw"
        self.crop_pending = False
        self._crop_draw_anchor = (cx, cy)
        self.crop_box = (cx, cy, cx, cy)
        self.output.config(cursor="crosshair")
        self._draw_crop_outline()

    def crop_drag(self, event):
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mode = getattr(self, "_crop_interaction", None)

        if mode == "move" and self._crop_box_at_move_start and self._crop_move_origin:
            ox, oy = self._crop_move_origin
            dx = cx - ox
            dy = cy - oy
            l0, t0, r0, b0 = self._crop_box_at_move_start
            self.crop_box = (l0 + dx, t0 + dy, r0 + dx, b0 + dy)
            self._draw_crop_outline()
            return

        if mode == "draw" and self._crop_draw_anchor is not None:
            ax, ay = self._crop_draw_anchor
            end_x, end_y = self._lock_crop_corner_to_image_aspect(ax, ay, cx, cy)
            self.crop_box = self._normalize_crop_box(ax, ay, end_x, end_y)
            self.start_x, self.start_y = ax, ay
            self._draw_crop_outline()

    def crop_end(self, event):
        """Finish draw or move — keep outlined selection pending (do not crop yet)."""
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mode = getattr(self, "_crop_interaction", None)
        self._crop_interaction = None
        self.output.config(cursor="crosshair" if self.crop_mode else "")

        if mode == "move":
            # Box already updated during drag; stay pending
            if self.crop_box:
                self.crop_pending = True
                self._draw_crop_outline()
                self._set_crop_status(
                    "Crop: drag box to move · Enter/double-click to apply · Esc to clear · click outside to re-draw"
                )
            self._crop_move_origin = None
            self._crop_box_at_move_start = None
            return

        if mode != "draw" or self._crop_draw_anchor is None:
            return

        ax, ay = self._crop_draw_anchor
        end_x, end_y = self._lock_crop_corner_to_image_aspect(ax, ay, cx, cy)
        left, top, right, bottom = self._normalize_crop_box(ax, ay, end_x, end_y)
        self._crop_draw_anchor = None

        # Too small → clear (click without drag)
        if (right - left) < 8 or (bottom - top) < 8:
            self.crop_pending = False
            self.crop_box = None
            self._clear_crop_ui()
            self._set_crop_status(
                "Crop: drag to outline · drag box to move · Enter/double-click to apply · Esc to clear"
            )
            return

        self.crop_box = (left, top, right, bottom)
        self.crop_pending = True
        self._draw_crop_outline()
        self._set_crop_status(
            "Crop: drag box to move · Enter/double-click to apply · Esc to clear · click outside to re-draw"
        )

    def _crop_double_click_apply(self, event=None):
        if self.crop_mode and self.crop_pending and self.crop_box:
            self._apply_pending_crop()
            return "break"

    def _on_escape_key(self, event=None):
        """Escape clears a pending crop selection; otherwise no-op."""
        if getattr(self, "crop_mode", False) and (
            getattr(self, "crop_pending", False) or self.crop_box
        ):
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self._clear_crop_ui()
            self._set_crop_status(
                "Crop: drag to outline · drag box to move · Enter/double-click to apply · Esc to clear"
            )
            return "break"
        return None

    def _apply_pending_crop(self):
        """Apply the pending canvas crop box to atlas rasters (same as former crop_end)."""
        if not self.crop_box:
            return
        left_c, top_c, right_c, bottom_c = self.crop_box
        page = self.current_page

        # Convert canvas-space crop rectangle → atlas *native* (model) coordinates.
        mx1, my1 = self._canvas_to_atlas(left_c, top_c)
        mx2, my2 = self._canvas_to_atlas(right_c, bottom_c)
        mleft = min(mx1, mx2)
        mtop = min(my1, my2)
        mright = max(mx1, mx2)
        mbottom = max(my1, my2)

        # Canvas TL of the selection — used to re-place the cropped layer
        cleft = min(left_c, right_c)
        ctop = min(top_c, bottom_c)

        # Reference size from the clean base (or current page image)
        if page in self.base_page_images and self.base_page_images[page] is not None:
            ref_w, ref_h = self.base_page_images[page].size
        else:
            img0 = self.load_page_image()
            if img0 is None:
                self.crop_pending = False
                self.crop_box = None
                self._clear_crop_ui()
                self.show_page()
                self.toggle_crop_mode()
                return
            ref_w, ref_h = img0.size

        # Inclusive-exclusive crop box in integer model pixels (true crop, not resize)
        left = int(np.floor(mleft))
        top = int(np.floor(mtop))
        right = int(np.ceil(mright))
        bottom = int(np.ceil(mbottom))
        left = max(0, min(left, ref_w))
        top = max(0, min(top, ref_h))
        right = max(left, min(right, ref_w))
        bottom = max(top, min(bottom, ref_h))
        if right - left < 2 or bottom - top < 2:
            messagebox.showinfo(
                "Crop",
                "Crop window is empty or outside the atlas.\n"
                "Drag a selection over the atlas, move it if needed, then press Enter.",
            )
            return

        box = (left, top, right, bottom)
        logger.info(
            f"Atlas crop model box={box} (native {ref_w}x{ref_h}) "
            f"canvas TL=({cleft:.1f},{ctop:.1f}) view_scale={self.view_scale}"
        )

        def _crop_rgba(im):
            if im is None:
                return None
            if im.size != (ref_w, ref_h):
                im = im.resize((ref_w, ref_h), Image.NEAREST)
            out = im.crop(box)
            if out.mode == "RGBA":
                out = self.img_white_to_transparent(out)
            return out

        # --- Crop every atlas raster with the *same* box (must stay aligned) ---
        if page in self.base_page_images and self.base_page_images[page] is not None:
            self.base_page_images[page] = _crop_rgba(self.base_page_images[page])

        if page in self.page_images and self.page_images[page] is not None:
            self.page_images[page] = _crop_rgba(self.page_images[page])
        else:
            img = self.load_page_image()
            if img is not None:
                self.page_images[page] = _crop_rgba(img)

        if page in self.mask_images and self.mask_images[page] is not None:
            mimg = self.mask_images[page]
            if mimg.size != (ref_w, ref_h):
                mimg = mimg.resize((ref_w, ref_h), Image.NEAREST)
            self.mask_images[page] = mimg.crop(box)

        # Critical for Allen: pure border layer must crop with the atlas
        pure = getattr(self, "allen_borders_pure", None)
        if pure is not None and getattr(self, "atlas_filetype", None) == "allen":
            if pure.size != (ref_w, ref_h):
                pure = pure.resize((ref_w, ref_h), Image.NEAREST)
            self.allen_borders_pure = pure.crop(box)
            if self.allen_borders_pure.mode != "RGBA":
                self.allen_borders_pure = self.allen_borders_pure.convert("RGBA")

        if getattr(self, "img", None) is not None and page in self.base_page_images:
            try:
                self.img = self.base_page_images[page].copy()
            except Exception:
                pass

        self._cleanup_loose_borders_after_crop(page)

        # Rebase placement in *model* space so (0,0) of the crop sits where the
        # selection TL was on screen (display = img_* * view_scale).
        vs = self.view_scale if self.view_scale else 1.0
        self.img_x = float(cleft) / vs
        self.img_y = float(ctop) / vs

        # Clear pending crop UI before show_page
        self.crop_pending = False
        self.crop_box = None
        self._clear_crop_ui()

        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        self.region_move_mode.set(False)

        self.show_page()
        if self.crop_mode:
            self.toggle_crop_mode()
        if getattr(self, "count_button", None) is not None and not getattr(
            self, "count_button_packed", False
        ):
            try:
                self.count_button.pack(side=tk.LEFT, padx=10, pady=10)
                self.count_button_packed = True
            except Exception:
                pass

    def _cleanup_loose_borders_after_crop(self, page):
        """After crop: remove orphan structure fragments and borders that don't outline a zone.

        Crop often leaves:
          - tiny mask slivers / disconnected pieces of a zone cut by the crop edge
          - free border ink that is not the boundary of any remaining filled zone

        For border-only atlases (Allen), prune weak *connected components* (not just
        whole zone IDs) and rebuild border strokes from surviving mask edges only —
        without curve-joint drawing (which created diagonal “diamond” chords).
        """
        if page not in self.mask_images or self.mask_images[page] is None:
            self._prune_border_ink_without_mask(page)
            return

        try:
            mask_img = self.mask_images[page]
            m = np.array(mask_img)
            if m.ndim > 2:
                m = m.squeeze()
            h, w = m.shape[:2]
            if h < 2 or w < 2:
                return

            # Per-component minimum (stricter than whole-zone so crop shards die)
            min_area = max(40, int(0.00035 * h * w))
            min_area = min(min_area, 800)

            cleaned = np.zeros_like(m)
            kept_cc = 0
            removed_cc = 0
            removed_edge = 0
            for zid in np.unique(m):
                zid = int(zid)
                if zid == 0:
                    continue
                region = m == zid
                # Split each zone into connected pieces — a large structure can still
                # leave a tiny disconnected scrap after crop (top-left fragment case).
                try:
                    labeled = measure.label(region, connectivity=2)
                except Exception:
                    labeled = region.astype(np.int32)
                nlab = int(labeled.max()) if labeled is not None else 0
                if nlab == 0:
                    continue
                for lab in range(1, nlab + 1):
                    comp = labeled == lab
                    area = int(comp.sum())
                    if area < min_area:
                        removed_cc += 1
                        continue
                    # Incomplete after crop: component meets the crop/image frame, so
                    # part of the structure (and its closed boundary) was cut away.
                    # Example: filled wedge flush with the bottom of the crop.
                    if self._mask_component_cut_by_frame(comp):
                        removed_edge += 1
                        removed_cc += 1
                        continue
                    # Reject thin edge-only shards (no body after light open)
                    try:
                        opened = morphology.binary_opening(comp, morphology.disk(1))
                        if int(opened.sum()) < max(12, min_area // 4):
                            removed_cc += 1
                            continue
                    except Exception:
                        pass
                    cleaned[comp] = zid
                    kept_cc += 1

            self.mask_images[page] = Image.fromarray(cleaned.astype(np.uint8), mode="L")

            # Drop empty zone names from Atlas Manager (and clear selection if removed)
            if page in self.zone_names:
                present = {int(z) for z in np.unique(cleaned) if int(z) > 0}
                for zid in list(self.zone_names[page].keys()):
                    if int(zid) not in present:
                        del self.zone_names[page][zid]
            if (
                getattr(self, "selected_zone_id", None) is not None
                and getattr(self, "selected_page", None) == page
            ):
                try:
                    if int(self.selected_zone_id) not in {
                        int(z) for z in np.unique(cleaned) if int(z) > 0
                    }:
                        self.selected_zone_id = None
                        self.selected_page = None
                        self.selected_zone_component = None
                except Exception:
                    pass

            # Rebuild borders from cleaned mask edges ONLY (pixel edges — no polylines).
            # Never keep pre-crop border ink: it can include construction lines / fragments.
            borders = self._borders_from_structure_mask(cleaned)
            is_allen = getattr(self, "atlas_filetype", None) == "allen"
            is_border_atlas = is_allen or self._looks_like_border_only_atlas(
                self.base_page_images.get(page)
            )
            if borders is not None and is_border_atlas:
                self.base_page_images[page] = borders.copy()
                self.page_images[page] = borders.copy()
                if is_allen or getattr(self, "allen_borders_pure", None) is not None:
                    self.allen_borders_pure = borders.copy()
                if getattr(self, "img", None) is not None:
                    self.img = borders.copy()
            elif borders is not None:
                self._filter_base_to_mask_edges(page, cleaned, borders)

            logger.info(
                f"Post-crop structure cleanup page={page}: kept_cc={kept_cc} "
                f"removed_cc={removed_cc} (cut_by_frame={removed_edge}) min_area={min_area}"
            )
            # Refresh Atlas Manager list so deleted zones disappear immediately
            try:
                if hasattr(self, "_update_ribbon_selection"):
                    self._update_ribbon_selection()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Post-crop loose-border cleanup failed: {e}", exc_info=True)

    def _mask_component_cut_by_frame(self, comp: np.ndarray) -> bool:
        """True if a connected mask component is truncated by the crop/image border.

        A structure that only *grazes* the frame with a couple of pixels is kept;
        a real cut (flat edge flush with the crop, as in incomplete boundary fills)
        has substantial contact with the frame.
        """
        if comp is None or not np.any(comp):
            return False
        h, w = comp.shape[:2]
        if h < 2 or w < 2:
            return True
        top = int(np.sum(comp[0, :]))
        bot = int(np.sum(comp[-1, :]))
        left = int(np.sum(comp[:, 0]))
        right = int(np.sum(comp[:, -1]))
        # Avoid double-counting corners in perimeter contact
        contact = top + bot + left + right
        if contact <= 0:
            return False
        area = int(comp.sum())
        # Contact along the longest side of the bbox is a strong "cut face" signal
        ys, xs = np.where(comp)
        bw = int(xs.max() - xs.min() + 1)
        bh = int(ys.max() - ys.min() + 1)
        max_side = max(bw, bh, 1)
        # Truncated if:
        #  - many pixels on the frame, or
        #  - a large fraction of the component sits on the frame, or
        #  - contact spans a large fraction of the component's bbox side (flat cut)
        if contact >= max(8, int(0.02 * area)):
            return True
        if contact >= max(6, int(0.25 * max_side)):
            return True
        if contact / float(area) >= 0.04:
            return True
        return False

    def _borders_from_structure_mask(self, mask_arr: np.ndarray) -> Image.Image:
        """Build black structure outlines from filled zone masks.

        Uses morphological / segmentation boundaries only — never ``ImageDraw.line``
        polylines. Polyline/curve drawing was connecting contour vertices with long
        chords across interiors (the diamond/X artifact after crop).
        """
        h, w = mask_arr.shape[:2]
        edge = np.zeros((h, w), dtype=bool)

        # Prefer skimage find_boundaries (outer edges of each label)
        try:
            from skimage.segmentation import find_boundaries
            # Treat 0 as background; each positive label gets its outer boundary
            if np.any(mask_arr > 0):
                edge = find_boundaries(mask_arr, mode="outer", background=0)
        except Exception:
            edge = np.zeros((h, w), dtype=bool)

        # Fallback / supplement: per-zone morphological gradient (region XOR erode)
        if not edge.any():
            for zid in np.unique(mask_arr):
                zid = int(zid)
                if zid == 0:
                    continue
                region = mask_arr == zid
                try:
                    er = morphology.binary_erosion(region, morphology.disk(1))
                    edge |= region & ~er
                except Exception:
                    # 4-neighbour edge approx
                    up = np.zeros_like(region)
                    down = np.zeros_like(region)
                    left = np.zeros_like(region)
                    right = np.zeros_like(region)
                    up[1:, :] = region[:-1, :]
                    down[:-1, :] = region[1:, :]
                    left[:, 1:] = region[:, :-1]
                    right[:, :-1] = region[:, 1:]
                    edge |= region & ~(up & down & left & right)

        # Drop isolated edge speckles (loose fragments)
        try:
            labeled = measure.label(edge, connectivity=2)
            min_edge = max(12, int(0.00015 * h * w))
            for lab in range(1, int(labeled.max()) + 1):
                comp = labeled == lab
                if int(comp.sum()) < min_edge:
                    edge[comp] = False
        except Exception:
            pass

        out = np.zeros((h, w, 4), dtype=np.uint8)
        out[edge, 0] = 0
        out[edge, 1] = 0
        out[edge, 2] = 0
        out[edge, 3] = 255
        return Image.fromarray(out, "RGBA")

    def _looks_like_border_only_atlas(self, base_img) -> bool:
        """True if base is mostly transparent with dark stroke ink (Allen-style)."""
        if base_img is None:
            return False
        try:
            arr = np.asarray(base_img.convert("RGBA"))
            alpha = arr[..., 3] > 20
            if not alpha.any():
                return True
            ink = arr[alpha]
            # Near-black strokes
            dark = (ink[:, 0] < 40) & (ink[:, 1] < 40) & (ink[:, 2] < 40)
            return float(dark.mean()) > 0.7 and float(alpha.mean()) < 0.35
        except Exception:
            return False

    def _filter_base_to_mask_edges(self, page, mask_arr, edge_borders):
        """For PDF bases: clear border-like ink that is not near a structure edge."""
        if page not in self.base_page_images or self.base_page_images[page] is None:
            return
        try:
            base = self.base_page_images[page].convert("RGBA")
            ba = np.array(base)
            edge = np.array(edge_borders)
            edge_ink = edge[..., 3] > 0 if edge.ndim == 3 else edge > 0
            # Dilate structure edges slightly so anti-aliased strokes survive
            try:
                edge_ink = morphology.binary_dilation(edge_ink, morphology.disk(2))
            except Exception:
                pass
            # Transparent or non-dark pixels always kept; dark stroke only kept on edges
            alpha = ba[..., 3] > 20
            dark = (
                (ba[..., 0] < 45)
                & (ba[..., 1] < 45)
                & (ba[..., 2] < 45)
                & alpha
            )
            loose = dark & ~edge_ink
            ba[loose, 3] = 0
            self.base_page_images[page] = Image.fromarray(ba, "RGBA")
            if page in self.page_images:
                self.page_images[page] = self.base_page_images[page].copy()
        except Exception as e:
            logger.debug(f"PDF base edge filter skipped: {e}")

    def _prune_border_ink_without_mask(self, page):
        """If there is no mask, drop tiny disconnected dark strokes on transparent base."""
        if page not in self.base_page_images or self.base_page_images[page] is None:
            return
        if not self._looks_like_border_only_atlas(self.base_page_images[page]):
            return
        try:
            ba = np.array(self.base_page_images[page].convert("RGBA"))
            ink = (
                (ba[..., 3] > 20)
                & (ba[..., 0] < 45)
                & (ba[..., 1] < 45)
                & (ba[..., 2] < 45)
            )
            labeled, n = measure.label(ink, connectivity=2, return_num=True)
            min_area = max(15, int(0.0001 * ink.size))
            for i in range(1, n + 1):
                comp = labeled == i
                if int(comp.sum()) < min_area:
                    ba[comp, 3] = 0
            self.base_page_images[page] = Image.fromarray(ba, "RGBA")
            if page in self.page_images:
                self.page_images[page] = self.base_page_images[page].copy()
            if getattr(self, "allen_borders_pure", None) is not None:
                self.allen_borders_pure = self.base_page_images[page].copy()
        except Exception as e:
            logger.debug(f"Border-only prune skipped: {e}")

    def toggle_edit_mode(self):
        self.save_state()
        self.edit_mode = not self.edit_mode
        self.edit_mode_var.set(self.edit_mode)
        if self.edit_mode:
            self.region_move_mode.set(False)
            self.border_mode_var.set(False)
            if getattr(self, 'crop_mode', False):
                self.crop_mode = False
                self.crop_mode_var.set(False)
                self.crop_pending = False
                self.crop_box = None
                self._crop_interaction = None
                self._clear_crop_ui()
                self._set_crop_status(None)
                try:
                    self.output.unbind("<Double-Button-1>")
                except Exception:
                    pass
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                self.output.config(cursor="")
            self.region_translate_active = False
            self.output.bind("<Button-1>", self.drag_start)
            self.output.bind("<B1-Motion>", self.drag_move)
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)

    def drag_start(self, event):
        # Give priority to per-region features (Move Selected Region checkbox or border/edge grab)
        # even if the global "Move" (edit_mode) binding is active. This prevents "move selected"
        # or edge grab from moving the whole atlas layer like the global drag does.
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_atlas(cx, cy)
        if self.region_move_mode.get() and self.selected_zone_id is not None and getattr(self, 'selected_page', None) == self.current_page:
            if not self._is_near_selected_border(mx, my, screen_tol=8):
                self._start_region_translate(mx, my)
                return
        if (getattr(self, 'border_mode_var', None) and self.border_mode_var.get() and
                self.selected_zone_id is not None and getattr(self, 'selected_page', None) == self.current_page):
            if self._is_near_selected_border(mx, my, screen_tol=8) or \
               (getattr(self, 'selected_edge_full_contour', None) is not None and self._is_click_on_selected_edge(mx, my, screen_tol=10)):
                self._try_start_border_drag(event)
                return
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag_move(self, event):
        # Delegate to per-region translate or edge grab logic if active (see drag_start priority).
        if getattr(self, 'region_translate_active', False):
            mx, my = self._canvas_to_atlas(self.output.canvasx(event.x), self.output.canvasy(event.y))
            dx = mx - self.region_translate_start_mx
            dy = my - self.region_translate_start_my
            if self.region_translate_original_mask is not None:
                self.mask_images[self.current_page] = self.region_translate_original_mask.copy()
                self._apply_region_translation(dx, dy)
                self._refresh_atlas_layer()
            return
        if getattr(self, 'edge_grab_active', False) or getattr(self, '_edge_pending_deselect', False):
            self._handle_border_drag_motion(event)
            return
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        # Convert screen drag to model-space offset (img_x/y are native pixels)
        vs = self.view_scale if self.view_scale else 1.0
        self.img_x += dx / vs
        self.img_y += dy / vs
        self.show_page()
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def _transform_allen_borders_pure(self, *, rotate_deg=None, scale_xy=None, expand_rotate=True):
        """Keep allen_borders_pure in sync with base/mask on rotate/scale (same size always)."""
        pure = getattr(self, "allen_borders_pure", None)
        if pure is None or getattr(self, "atlas_filetype", None) != "allen":
            return
        if rotate_deg is not None:
            pure = pure.rotate(
                rotate_deg, expand=expand_rotate, resample=Image.NEAREST, fillcolor=(0, 0, 0, 0)
            )
        if scale_xy is not None:
            sx, sy = scale_xy
            nw = max(1, int(pure.width * sx))
            nh = max(1, int(pure.height * sy))
            pure = pure.resize((nw, nh), Image.NEAREST)
        self.allen_borders_pure = pure.convert("RGBA") if pure.mode != "RGBA" else pure

    def rotate_custom(self):
        self.save_state()
        try:
            degrees = float(self.rotation_entry.get())
            page = self.current_page
            # Transform the clean base (the atlas artwork) and the zone mask
            if page in self.base_page_images:
                base = self.base_page_images[page]
                rotated_base = base.rotate(degrees, expand=True)
                self.base_page_images[page] = rotated_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                rotated_mask = mask_img.rotate(degrees, expand=True, resample=Image.NEAREST)
                self.mask_images[page] = rotated_mask
            self._transform_allen_borders_pure(rotate_deg=degrees, expand_rotate=True)
            clear_preprocess_cache()
            self._rebuild_page_overlays(page)
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for rotation degrees.")

    def fit_atlas_to_image(self):
        """Resize the atlas (or remaining cropped atlas) to match the loaded TIFF size.

        Aligns the top-left of the atlas with the top-left of the background image
        (img_x = img_y = 0). Scales base, page overlay, zone mask, and Allen pure
        borders together so they stay registered.
        """
        if not self.atlas_filetype:
            messagebox.showwarning("No Atlas", "Load an atlas first (Atlas → Import…).")
            return

        # Target = loaded experimental image (prefer full-res original)
        bg = None
        if getattr(self, "original_background", None) is not None:
            bg = self.original_background
        elif getattr(self, "background_image", None) is not None:
            bg = self.background_image
        if bg is None:
            messagebox.showwarning(
                "No Image",
                "Load a TIFF/image first so the atlas can be fit to its size.",
            )
            return

        page = self.current_page
        if page not in self.base_page_images or self.base_page_images[page] is None:
            # Fall back to current page image as base
            img = self.load_page_image()
            if img is None:
                messagebox.showwarning("No Atlas", "No atlas page image is available to scale.")
                return
            self.base_page_images[page] = img.copy()

        base = self.base_page_images[page]
        tw, th = bg.size
        aw, ah = base.size
        if tw < 2 or th < 2 or aw < 2 or ah < 2:
            messagebox.showerror("Fit to image", "Image or atlas size is invalid.")
            return

        self.save_state()
        target = (int(tw), int(th))
        sx = tw / float(aw)
        sy = th / float(ah)
        logger.info(
            f"Fit atlas to image: atlas {aw}x{ah} → image {tw}x{th} "
            f"(sx={sx:.4f}, sy={sy:.4f})"
        )

        # Base / overlay: bilinear for smooth outlines on PDF; NEAREST for Allen borders
        is_allen = getattr(self, "atlas_filetype", None) == "allen"
        base_resample = Image.NEAREST if is_allen else Image.BILINEAR
        self.base_page_images[page] = base.resize(target, base_resample)

        if page in self.page_images and self.page_images[page] is not None:
            self.page_images[page] = self.page_images[page].resize(target, base_resample)

        if page in self.mask_images and self.mask_images[page] is not None:
            self.mask_images[page] = self.mask_images[page].resize(target, Image.NEAREST)

        pure = getattr(self, "allen_borders_pure", None)
        if pure is not None and is_allen:
            self.allen_borders_pure = pure.resize(target, Image.NEAREST)
            if self.allen_borders_pure.mode != "RGBA":
                self.allen_borders_pure = self.allen_borders_pure.convert("RGBA")

        if getattr(self, "img", None) is not None:
            try:
                self.img = self.base_page_images[page].copy()
            except Exception:
                pass

        # Top-left of atlas = top-left of background image (drawn at 0,0)
        self.img_x = 0
        self.img_y = 0

        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        self.region_move_mode.set(False)
        self.show_page()
        messagebox.showinfo(
            "Fit to image",
            f"Atlas resized to {tw}×{th} px to match the loaded image.\n"
            f"Top-left corners aligned.",
        )

    def resize_custom(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            page = self.current_page
            if page in self.base_page_images:
                base = self.base_page_images[page]
                new_size = (int(base.width * scale), int(base.height * scale))
                resized_base = base.resize(new_size, Image.BILINEAR)
                self.base_page_images[page] = resized_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                new_size = (int(mask_img.width * scale), int(mask_img.height * scale))
                resized_mask = mask_img.resize(new_size, Image.NEAREST)
                self.mask_images[page] = resized_mask
            self._transform_allen_borders_pure(scale_xy=(scale, scale))
            clear_preprocess_cache()
            self._rebuild_page_overlays(page)
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def resize_x(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            page = self.current_page
            if page in self.base_page_images:
                base = self.base_page_images[page]
                new_size = (int(base.width * scale), base.height)
                resized_base = base.resize(new_size, Image.BILINEAR)
                self.base_page_images[page] = resized_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                new_size = (int(mask_img.width * scale), mask_img.height)
                resized_mask = mask_img.resize(new_size, Image.NEAREST)
                self.mask_images[page] = resized_mask
            self._transform_allen_borders_pure(scale_xy=(scale, 1.0))
            self._rebuild_page_overlays(page)
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def resize_y(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            page = self.current_page
            if page in self.base_page_images:
                base = self.base_page_images[page]
                new_size = (base.width, int(base.height * scale))
                resized_base = base.resize(new_size, Image.BILINEAR)
                self.base_page_images[page] = resized_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                new_size = (mask_img.width, int(mask_img.height * scale))
                resized_mask = mask_img.resize(new_size, Image.NEAREST)
                self.mask_images[page] = resized_mask
            self._transform_allen_borders_pure(scale_xy=(1.0, scale))
            self._rebuild_page_overlays(page)
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    # ------------------------------------------------------------------
    # NEW: Per-region select + rotate/scale for individual atlas zones
    # ------------------------------------------------------------------

    def select_region(self):
        """Prompt user to click a named atlas region to select it for individual shape adjustment."""
        if not self.atlas_filetype:
            messagebox.showwarning("No Atlas", "Load an atlas first (Atlas > Import Atlas).")
            return
        self.save_state()
        messagebox.showinfo(
            "Select Region",
            "Click inside a yellow/orange named region on the atlas to select it.\n"
            "Then use 'Rotate Selected Region' or 'Scale Selected Region' from the Atlas menu."
        )
        # One-shot picker
        self.output.bind("<Button-1>", self._pick_and_select_region)

    def _selected_component_mask(self, m, zid):
        """Boolean mask for the selected connected component of zid (or whole zid)."""
        comp = getattr(self, "selected_zone_component", None)
        if (
            comp is not None
            and isinstance(comp, np.ndarray)
            and comp.shape[:2] == m.shape[:2]
        ):
            return comp.astype(bool)
        return m == int(zid)

    def _set_zone_selection(self, page, zid, atlas_x=None, atlas_y=None):
        """Set selected zone; if atlas_x/y given, limit highlight to that connected component."""
        self.selected_zone_id = int(zid)
        self.selected_page = page
        self.selected_zone_component = None
        if atlas_x is None or atlas_y is None:
            return
        try:
            if page not in self.mask_images or self.mask_images[page] is None:
                return
            m = np.array(self.mask_images[page])
            if m.ndim > 2:
                m = m.squeeze()
            x, y = int(round(atlas_x)), int(round(atlas_y))
            if not (0 <= y < m.shape[0] and 0 <= x < m.shape[1]):
                return
            if int(m[y, x]) != int(zid):
                return
            from scipy import ndimage as _ndi
            labeled, nlab = _ndi.label(m == int(zid))
            if nlab < 1:
                return
            cid = int(labeled[y, x])
            if cid == 0:
                return
            self.selected_zone_component = labeled == cid
        except Exception as e:
            logger.debug(f"Component selection failed: {e}")
            self.selected_zone_component = None

    def deselect_region(self):
        """Clear current region selection (fill tint + boundary color back to default)."""
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        if self.selected_zone_id is not None:
            self.selected_zone_id = None
            self.selected_page = None
            self.selected_zone_component = None
            if self.current_page in self.base_page_images:
                self._rebuild_page_overlays(self.current_page)
            # Boundary back to black for all regions
            self._refresh_selection_boundary_visual()
            self.show_page()
            self._update_ribbon_selection()

    def _pick_and_select_region(self, event):
        """Temporarily bound click handler to pick a zone from the mask under cursor."""
        logger.debug(f"Region pick click at canvas ({event.x}, {event.y})")
        try:
            canvas_x = self.output.canvasx(event.x)
            canvas_y = self.output.canvasy(event.y)
            mx, my = self._canvas_to_atlas(canvas_x, canvas_y)
            x, y = int(mx), int(my)

            if self.current_page not in self.mask_images:
                messagebox.showwarning("No Regions", "No zone mask for current atlas page.")
                return

            mask_img = self.mask_images[self.current_page]
            w, h = mask_img.size
            if x < 0 or y < 0 or x >= w or y >= h:
                messagebox.showinfo("Click Outside", "Click inside the atlas overlay area.")
                return

            m = np.array(mask_img)
            if 0 <= y < m.shape[0] and 0 <= x < m.shape[1]:
                zid = int(m[y, x])
            else:
                zid = 0

            if zid == 0:
                messagebox.showwarning("No Region", "Clicked on background / unlabeled area. Click inside a named (yellow) region.")
                return

            # Ensure any mask-claimed zone (even if it lacked a name entry) gets a default and
            # will appear in the Atlas Manager labeled list.
            self._ensure_zone_has_name(self.current_page, zid)

            self._set_zone_selection(self.current_page, zid, atlas_x=x, atlas_y=y)
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self._edge_pending_deselect = False
            self.region_move_mode.set(False)
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            zname = self.zone_names.get(self.current_page, {}).get(zid, f"Zone {zid}")
            messagebox.showinfo("Selected", f"Region '{zname}' (ID {zid}) is now selected for transform.\n\nUse Atlas menu Rotate/Scale Selected Region or drag its border (if enabled in ribbon).")
            # Orange fill + yellow boundary
            self._rebuild_page_overlays(self.current_page)
            self._refresh_selection_boundary_visual()
            self.show_page()
            self._update_ribbon_selection()
        finally:
            # Restore normal left-click behavior (name/highlight regions)
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)

    def _has_selected_region(self):
        if self.selected_zone_id is None or self.selected_page is None:
            return False
        if self.selected_page != self.current_page:
            messagebox.showwarning("Page Mismatch", "The selected region is on a different atlas page. Please re-select on the current page.")
            self.selected_zone_id = None
            self.selected_page = None
            return False
        return True

    def _ensure_zone_has_name(self, page, zid):
        """If a positive zone id appears in the mask but has no friendly name in zone_names,
        auto-register a default name so it shows up in the Labeled Regions manager and
        canvas clicks on it will autoselect instead of re-prompting for a name.
        Also bumps the zone counter so future new names don't collide with existing ids.
        """
        zid = int(zid)
        if zid <= 0:
            return
        if page not in self.zone_names:
            self.zone_names[page] = {}
        if zid not in self.zone_names[page]:
            default_name = f"Region {zid}"
            self.zone_names[page][zid] = default_name
            logger.debug(f"Auto-registered default name for orphan zone {zid} on page {page}")
        if page not in self.zone_counters:
            self.zone_counters[page] = 0
        if self.zone_counters[page] < zid:
            self.zone_counters[page] = zid

    def _apply_transform_to_region(self, page, zone_id, angle_deg=0.0, scale_x=1.0, scale_y=1.0):
        """Rotate (around centroid) and/or scale the shape of a single zone in the label mask.
        The underlying base atlas image is left unchanged (lines stay for reference); only the
        zone's yellow area (for viz) and the mask pixels (for counting) are adjusted.
        Centroid of the region is kept approximately in place.
        """
        if page not in self.mask_images or zone_id is None:
            return False
        mask_img = self.mask_images[page]
        m = np.array(mask_img)
        if zone_id not in m:
            return False

        region = (m == zone_id)
        if not region.any():
            return False

        ys, xs = np.where(region)
        cy = float(np.mean(ys))
        cx = float(np.mean(xs))

        # Compute tight bbox + pad
        miny, maxy = int(ys.min()), int(ys.max())
        minx, maxx = int(xs.min()), int(xs.max())
        pad = 4
        miny = max(0, miny - pad)
        minx = max(0, minx - pad)
        maxy = min(m.shape[0] - 1, maxy + pad)
        maxx = min(m.shape[1] - 1, maxx + pad)

        region_crop = region[miny:maxy+1, minx:maxx+1].astype(np.uint8) * 255
        bin_img = Image.fromarray(region_crop, mode='L')

        # Rotate around the crop center (approximates; we correct with centroid later)
        if abs(angle_deg) > 0.0001:
            bin_img = bin_img.rotate(angle_deg, resample=Image.NEAREST, expand=True)

        # Scale (post-rotate)
        if abs(scale_x - 1.0) > 0.0001 or abs(scale_y - 1.0) > 0.0001:
            nw = max(1, int(bin_img.width * scale_x))
            nh = max(1, int(bin_img.height * scale_y))
            bin_img = bin_img.resize((nw, nh), Image.NEAREST)

        new_bin = np.array(bin_img) > 127
        if not new_bin.any():
            return False

        new_ys, new_xs = np.where(new_bin)
        new_cy_loc = float(np.mean(new_ys))
        new_cx_loc = float(np.mean(new_xs))

        # Position the patch so its new centroid lands on the original world centroid
        paste_x = int(round(cx - new_cx_loc))
        paste_y = int(round(cy - new_cy_loc))

        # Build new mask: clear old zone pixels, paste transformed
        new_m = m.copy()
        new_m[region] = 0

        nh, nw = new_bin.shape
        y1 = max(0, paste_y)
        x1 = max(0, paste_x)
        y2 = min(new_m.shape[0], paste_y + nh)
        x2 = min(new_m.shape[1], paste_x + nw)

        if y2 > y1 and x2 > x1:
            sub = new_bin[(y1 - paste_y):(y2 - paste_y), (x1 - paste_x):(x2 - paste_x)]
            new_m[y1:y2, x1:x2][sub] = zone_id

        self.mask_images[page] = Image.fromarray(new_m.astype(np.uint8), mode='L')
        clear_preprocess_cache()

        # Update visuals from base + new mask (selected will be orange if still selected)
        self._rebuild_page_overlays(page)
        return True

    def _apply_border_pull(self, pull_amount):
        """One-sided border pull: only the side being dragged moves (the pulled "cap" of the region).
        The opposite side stays fixed. This stretches/deforms the region from the contact edge.
        pull_amount is the signed offset along the precomputed unit normal (positive = outward).
        """
        page = self.current_page
        zid = self.border_drag_zone
        if page not in self.mask_images or zid is None:
            return False

        orig = np.array(self.mask_images[page])
        region = (orig == zid)
        if not region.any():
            return False

        ys, xs = np.where(region)
        cx, cy = self.border_drag_centroid
        ux, uy = self.border_drag_unit

        new_mask = orig.copy()
        new_mask[region] = 0

        for y, x in zip(ys, xs):
            vx = x - cx
            vy = y - cy
            side = vx * ux + vy * uy
            if side > 0:
                # This point is on the pulled side -> shift it
                nx = x + pull_amount * ux
                ny = y + pull_amount * uy
            else:
                nx = x
                ny = y

            ix = int(round(nx))
            iy = int(round(ny))
            if 0 <= iy < new_mask.shape[0] and 0 <= ix < new_mask.shape[1]:
                new_mask[iy, ix] = zid

        # Fill gaps and make the deformed region solid (important for counting)
        try:
            bin_zone = (new_mask == zid)
            # A little dilation helps connect the sampled points after rounding/shifting
            thickened = ndi.binary_dilation(bin_zone, iterations=1)
            filled = ndi.binary_fill_holes(thickened)
            # Only fill holes that belong to this zone, protect other zones
            new_mask[filled & (new_mask == 0)] = zid
            other_zones = (orig != 0) & (orig != zid)
            new_mask[other_zones] = orig[other_zones]
        except Exception:
            # Fallback: at least the sampled points are set
            pass

        self.mask_images[page] = Image.fromarray(new_mask.astype(np.uint8), mode='L')
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        return True

    def show_rotate_selected_dialog(self):
        if not self._has_selected_region():
            messagebox.showwarning("No Region Selected", "Use 'Atlas > Select Region' then click a named region first.")
            return
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)
        window.title("Rotate Selected Region")
        rotation_label = ttk.Label(window, text="Degrees:")
        rotation_label.grid(row=0, column=0)
        self.region_rotation_entry = ttk.Entry(window, width=10)
        self.region_rotation_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(window, text="Rotate", command=self.rotate_selected_region).grid(row=0, column=2, padx=5, pady=5)
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def rotate_selected_region(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_rotation_entry', None)
            degrees = float(entry.get()) if entry else 0.0
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=degrees, scale_x=1.0, scale_y=1.0):
                self.show_page()
                self._update_ribbon_selection()
            else:
                messagebox.showerror("Transform Failed", "Could not rotate the selected region.")
        except Exception as e:
            messagebox.showerror("Error", f"Enter a valid number. {e}")

    def show_scale_selected_dialog(self):
        if not self._has_selected_region():
            messagebox.showwarning("No Region Selected", "Use 'Atlas > Select Region' then click a named region first.")
            return
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)
        window.title("Scale Selected Region")
        scale_label = ttk.Label(window, text="Scale factor:")
        scale_label.grid(row=0, column=0)
        self.region_scale_entry = ttk.Entry(window, width=10)
        self.region_scale_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(window, text="Resize", command=self.scale_selected_uniform).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(window, text="Resize X", command=self.scale_selected_x).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(window, text="Resize Y", command=self.scale_selected_y).grid(row=1, column=2, padx=5, pady=5)
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def scale_selected_uniform(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_scale_entry', None)
            s = float(entry.get()) if entry else 1.0
            if s <= 0:
                raise ValueError("Scale > 0")
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=s, scale_y=s):
                self.show_page()
                self._update_ribbon_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid scale: {e}")

    def scale_selected_x(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_scale_entry', None)
            s = float(entry.get()) if entry else 1.0
            if s <= 0:
                raise ValueError("Scale > 0")
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=s, scale_y=1.0):
                self.show_page()
                self._update_ribbon_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid scale: {e}")

    def scale_selected_y(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_scale_entry', None)
            s = float(entry.get()) if entry else 1.0
            if s <= 0:
                raise ValueError("Scale > 0")
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=1.0, scale_y=s):
                self.show_page()
                self._update_ribbon_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid scale: {e}")

    # --- Atlas Manager Ribbon UI ---
    def _build_atlas_ribbon(self, parent):
        """Builds a collapsible 'ribbon' / panel for Atlas region management.
        Header always visible with toggle arrow and current selection summary.
        Expanded content shows: selected region info, global tools (Crop/Move + quick global adjust),
        per-region translate/edge, quick selected-region adjust, labeled regions list, border drag toggle.
        """
        self.atlas_ribbon = ttk.Frame(parent, relief=tk.GROOVE, borderwidth=1)

        # Header row (always shown)
        header = ttk.Frame(self.atlas_ribbon)
        header.pack(fill='x', padx=2, pady=1)

        self.ribbon_arrow_var = tk.StringVar(value="▶")
        self.ribbon_toggle = ttk.Button(
            header, textvariable=self.ribbon_arrow_var, width=3,
            command=self._toggle_atlas_ribbon
        )
        self.ribbon_toggle.pack(side=tk.LEFT, padx=(2, 4))

        ttk.Label(header, text="Atlas Manager", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT)

        self.ribbon_selected_var = tk.StringVar(value="No region selected")
        ttk.Label(header, textvariable=self.ribbon_selected_var, foreground="#0066cc").pack(side=tk.LEFT, padx=8)

        # Paint mode indicator (visible in the ribbon header)
        self.paint_status_label = ttk.Label(header, textvariable=self.paint_status_var, foreground="gray", font=("Helvetica", 8))
        self.paint_status_label.pack(side=tk.LEFT, padx=8)

        # Prominent Undo button (works for paint, atlas edits, mask edits, etc.)
        # Placed in the always-visible ribbon header so it's easy to reach.
        ttk.Button(header, text="↶ Undo", command=self.undo, width=7).pack(side=tk.RIGHT, padx=4)

        # Expandable content
        self.ribbon_content = ttk.Frame(self.atlas_ribbon)

        # Selection info
        sel_frame = ttk.Frame(self.ribbon_content)
        sel_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(sel_frame, text="Selected Region:").pack(side=tk.LEFT)
        self.ribbon_sel_name_var = tk.StringVar(value="None")
        name_lbl = ttk.Label(sel_frame, textvariable=self.ribbon_sel_name_var, width=28, relief="sunken", padding=2)
        name_lbl.pack(side=tk.LEFT, padx=4)
        ttk.Button(sel_frame, text="Select Region", command=self.select_region, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(sel_frame, text="Deselect", command=self.deselect_region, width=8).pack(side=tk.LEFT)

        # Global atlas tools (Crop / Move for whole overlay alignment) - now checkboxes so user can see active state
        global_frame = ttk.Frame(self.ribbon_content)
        global_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(global_frame, text="Global:").pack(side=tk.LEFT)
        ttk.Checkbutton(global_frame, text="Crop", variable=self.crop_mode_var, command=self.toggle_crop_mode, width=7).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_frame, text="Apply Crop", command=self._apply_pending_crop, width=10).pack(side=tk.LEFT, padx=1)
        ttk.Checkbutton(global_frame, text="Move", variable=self.edit_mode_var, command=self.toggle_edit_mode, width=7).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_frame, text="Clear Atlas", command=self.clear_atlas, width=11).pack(side=tk.LEFT, padx=6)
        ttk.Button(global_frame, text="Next Channel…", command=self.next_channel, width=13).pack(side=tk.LEFT, padx=2)

        # Global quick adjust (mirrors the selected-region quick adjust below)
        global_manip_frame = ttk.Frame(self.ribbon_content)
        global_manip_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(global_manip_frame, text="Global Quick Adjust:").pack(side=tk.LEFT)
        ttk.Button(global_manip_frame, text="Rot +5°", command=lambda: self._quick_rotate_global(5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Rot -5°", command=lambda: self._quick_rotate_global(-5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Scale +5%", command=lambda: self._quick_scale_global(1.05), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Scale -5%", command=lambda: self._quick_scale_global(0.95), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Dialogs...", command=self.show_rotate_settings, width=9).pack(side=tk.LEFT, padx=4)

        # Move selected region (translate only this zone's area in the mask; underlying atlas stays fixed)
        move_frame = ttk.Frame(self.ribbon_content)
        move_frame.pack(fill='x', padx=4, pady=2)
        ttk.Checkbutton(move_frame, text="Move Selected Region (click+drag inside orange to translate it)", variable=self.region_move_mode, command=self._on_region_move_mode_toggled).pack(anchor='w')

        # Quick manip for selected region
        manip_frame = ttk.Frame(self.ribbon_content)
        manip_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(manip_frame, text="Selected Region Quick Adjust:").pack(side=tk.LEFT)
        ttk.Button(manip_frame, text="Rot +5°", command=lambda: self._quick_rotate_selected(5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Rot -5°", command=lambda: self._quick_rotate_selected(-5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Scale +5%", command=lambda: self._quick_scale_selected(1.05), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Scale -5%", command=lambda: self._quick_scale_selected(0.95), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Dialogs...", command=self._show_region_dialogs, width=9).pack(side=tk.LEFT, padx=4)

        # Selectable list of all labeled regions for current page
        list_frame = ttk.Frame(self.ribbon_content)
        list_frame.pack(fill='both', expand=True, padx=4, pady=2)
        ttk.Label(
            list_frame,
            text="Labeled Regions (current page) — click to select; right-click for Rename / Delete:",
        ).pack(anchor='w')
        lb_container = ttk.Frame(list_frame)
        lb_container.pack(fill='both', expand=True)
        self.region_listbox = tk.Listbox(lb_container, height=5, exportselection=False)
        self.region_listbox.pack(side=tk.LEFT, fill='both', expand=True)
        lb_scroll = ttk.Scrollbar(lb_container, orient=tk.VERTICAL, command=self.region_listbox.yview)
        lb_scroll.pack(side=tk.RIGHT, fill='y')
        self.region_listbox.configure(yscrollcommand=lb_scroll.set)
        self.region_listbox.bind('<<ListboxSelect>>', self._on_region_list_select)
        # Right-click context menu: Rename / Delete
        self.region_listbox.bind('<Button-3>', self._on_region_list_right_click)
        # macOS often uses Button-2 for secondary click
        self.region_listbox.bind('<Button-2>', self._on_region_list_right_click)
        self.region_listbox.bind('<Control-Button-1>', self._on_region_list_right_click)

        self._region_list_context_menu = tk.Menu(self.region_listbox, tearoff=0)
        self._region_list_context_menu.add_command(
            label="Rename", command=self._context_rename_region
        )
        self._region_list_context_menu.add_command(
            label="Delete", command=self._context_delete_region
        )
        self._context_menu_zone_id = None

        # Border drag help / toggle  (edge expand/shrink for selected region)
        border_frame = ttk.Frame(self.ribbon_content)
        border_frame.pack(fill='x', padx=4, pady=(2, 4))
        ttk.Checkbutton(border_frame, text="Border drag resize enabled (when region selected)", variable=self.border_mode_var, command=self._on_border_mode_toggled).pack(side=tk.LEFT)
        ttk.Label(border_frame, text="  Drag near the edges of the orange/yellow region to expand or shrink it from its center. Press Enter to commit the expanded shape and refit the black boundary (for painted regions).", font=("Helvetica", 8, "italic")).pack(side=tk.LEFT)

        # Start collapsed (value comes from __init__)

    def _toggle_atlas_ribbon(self):
        if getattr(self, 'atlas_ribbon_expanded', False):
            self.ribbon_content.pack_forget()
            self.ribbon_arrow_var.set("▶")
            self.atlas_ribbon_expanded = False
        else:
            self.ribbon_content.pack(fill='x', padx=2, pady=1)
            self.ribbon_arrow_var.set("▼")
            self.atlas_ribbon_expanded = True
            self._update_ribbon_selection()  # ensure list and selection are up to date when expanding content

    def _toggle_atlas_ribbon_visibility(self):
        """Called from View menu checkbutton to show or hide the entire Atlas Manager ribbon."""
        if self.show_atlas_ribbon.get():
            try:
                self.atlas_ribbon.grid(row=0, column=0, columnspan=2, sticky='ew', padx=2, pady=1)
                self._update_ribbon_selection()
            except Exception:
                pass
        else:
            try:
                self.atlas_ribbon.grid_remove()
            except Exception:
                pass

    def _on_region_move_mode_toggled(self):
        if self.region_move_mode.get():
            # If global layer Move (edit_mode) is active, its binding overrides <Button-1>,
            # so exit it to let highlight_region see the clicks (delegation in drag_* also helps).
            if getattr(self, 'edit_mode', False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                self.output.bind("<ButtonRelease-1>", self._end_border_drag, add=True)
            if getattr(self, 'crop_mode', False):
                self.crop_mode = False
                self.crop_mode_var.set(False)
                self.crop_pending = False
                self.crop_box = None
                self._crop_interaction = None
                self._clear_crop_ui()
                self._set_crop_status(None)
                try:
                    self.output.unbind("<Double-Button-1>")
                except Exception:
                    pass
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.border_drag_active = False
            self.output.config(cursor="")
        else:
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.border_drag_active = False
            self.output.config(cursor="")

    def _on_border_mode_toggled(self):
        """Called when the border drag (edge expand/shrink) checkbox is toggled.
        Enforces mutual exclusion with global move/crop: enabling edge deselects globals.
        """
        if self.border_mode_var.get():
            # Deselect global modes so user can tell edge expand is active (and avoid binding conflicts)
            if getattr(self, 'edit_mode', False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                self.output.bind("<ButtonRelease-1>", self._end_border_drag, add=True)
            if getattr(self, 'crop_mode', False):
                self.crop_mode = False
                self.crop_mode_var.set(False)
                self.crop_pending = False
                self.crop_box = None
                self._crop_interaction = None
                self._clear_crop_ui()
                self._set_crop_status(None)
                try:
                    self.output.unbind("<Double-Button-1>")
                except Exception:
                    pass
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            # also ensure region translate not conflicting
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.border_drag_active = False
            self.output.config(cursor="")
        # when turning border drag off, no need to force globals on

    def _update_ribbon_selection(self):
        """Refresh the ribbon labels with current selection state."""
        if not hasattr(self, 'ribbon_sel_name_var'):
            return
        if self.selected_zone_id is not None and self.selected_page == self.current_page:
            zname = self.zone_names.get(self.current_page, {}).get(self.selected_zone_id, f"Zone{self.selected_zone_id}")
            display = f"{zname} (#{self.selected_zone_id})"
            self.ribbon_sel_name_var.set(display)
            self.ribbon_selected_var.set(f"Selected: {zname}")
        else:
            self.ribbon_sel_name_var.set("None")
            self.ribbon_selected_var.set("No region selected")

        # Refresh the full list of labeled regions and sync selection highlight in list
        self._populate_region_list()

    def _populate_region_list(self):
        """Populate (or refresh) the listbox with all labeled regions for the current atlas page.
        Also tries to highlight the currently selected one in the list.
        """
        if not hasattr(self, 'region_listbox') or self.region_listbox is None:
            return
        self.region_listbox.delete(0, tk.END)
        self.region_list_id_map = {}
        page = self.current_page
        raw_names = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
        # Normalize keys to int (json manifests, snapshots etc use str keys). Prevents
        # 'uid not in names' false positives and ufunc 'less' in sorted when mixing with np.uint8 from mask.
        names = {int(k): v for k, v in raw_names.items()} if raw_names else {}
        if names:
            if page not in self.zone_names:
                self.zone_names[page] = {}
            self.zone_names[page].update(names)
        # Discover any zones present in the mask but missing from zone_names (orphans from
        # paint force, undo, or legacy data) and auto-register defaults so they appear in
        # the manager and can be autoselected on canvas clicks.
        if page in self.mask_images:
            try:
                m = np.array(self.mask_images[page])
                for zid in np.unique(m):
                    if zid > 0:
                        iz = int(zid)
                        if iz not in names:
                            self._ensure_zone_has_name(page, iz)
                names = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
                names = {int(k): v for k, v in names.items()} if names else {}
            except Exception:
                pass
        # Force int keys for stable sort + display (defensive vs json str keys or np scalars)
        try:
            sorted_items = sorted((int(k), v) for k, v in names.items())
        except Exception:
            sorted_items = sorted(names.items())
        for i, (zid, zname) in enumerate(sorted_items):
            display = f"{zname} (ID={zid})"
            self.region_listbox.insert(tk.END, display)
            self.region_list_id_map[i] = zid

        # If we have a current selection for this page, highlight it in the list
        if (self.selected_zone_id is not None and
                getattr(self, 'selected_page', None) == page):
            for i, zid in list(self.region_list_id_map.items()):
                if zid == self.selected_zone_id:
                    self.region_listbox.selection_clear(0, tk.END)
                    self.region_listbox.selection_set(i)
                    self.region_listbox.see(i)
                    break
            else:
                self.region_listbox.selection_clear(0, tk.END)

    def _on_region_list_select(self, event=None):
        """User clicked a region in the Atlas Manager list -> make it the transform target."""
        if not hasattr(self, 'region_listbox') or self.region_listbox is None:
            return
        sel = self.region_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if not hasattr(self, 'region_list_id_map'):
            self.region_list_id_map = {}
        zid = self.region_list_id_map.get(idx)
        if zid is None:
            return
        self._select_zone_for_edit(zid)

    def _select_zone_for_edit(self, zid):
        """Select a zone id as the current Atlas Manager edit target and refresh visuals."""
        if zid is None:
            return
        zid = int(zid)
        # List selection: whole zone id (already side-specific after bilateral remap)
        self._set_zone_selection(self.current_page, zid, atlas_x=None, atlas_y=None)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        # Update visual: orange fill tint + yellow boundary (was black)
        if self.current_page in self.base_page_images:
            self._rebuild_page_overlays(self.current_page)
        self._refresh_selection_boundary_visual()
        self.show_page()
        self._update_ribbon_selection()  # will re-sync everything including list highlight

    def _on_region_list_right_click(self, event):
        """Right-click on a labeled region in the Atlas Manager list → context menu."""
        if not hasattr(self, 'region_listbox') or self.region_listbox is None:
            return
        try:
            idx = self.region_listbox.nearest(event.y)
        except Exception:
            return
        if idx is None or idx < 0 or idx >= self.region_listbox.size():
            return

        # Select the row under the cursor so Rename/Delete target is clear
        self.region_listbox.selection_clear(0, tk.END)
        self.region_listbox.selection_set(idx)
        self.region_listbox.activate(idx)
        self.region_listbox.focus_set()

        zid = getattr(self, 'region_list_id_map', {}).get(idx)
        if zid is None:
            return
        self._context_menu_zone_id = int(zid)
        # Also make it the active selection for editing (orange tint)
        try:
            self._select_zone_for_edit(zid)
        except Exception:
            pass

        menu = getattr(self, '_region_list_context_menu', None)
        if menu is None:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _context_rename_region(self):
        """Context menu: Rename the region that was right-clicked."""
        zid = getattr(self, '_context_menu_zone_id', None)
        if zid is None:
            # Fall back to current list selection
            sel = self.region_listbox.curselection() if hasattr(self, 'region_listbox') else ()
            if sel:
                zid = self.region_list_id_map.get(sel[0])
        if zid is None:
            messagebox.showinfo("Rename Region", "Right-click a labeled region in the list first.")
            return
        self.rename_labeled_region(int(zid))

    def _context_delete_region(self):
        """Context menu: Delete the region that was right-clicked."""
        zid = getattr(self, '_context_menu_zone_id', None)
        if zid is None:
            sel = self.region_listbox.curselection() if hasattr(self, 'region_listbox') else ()
            if sel:
                zid = self.region_list_id_map.get(sel[0])
        if zid is None:
            messagebox.showinfo("Delete Region", "Right-click a labeled region in the list first.")
            return
        self.delete_labeled_region(int(zid))

    def rename_labeled_region(self, zid=None):
        """Prompt for a new name for the given zone (or currently selected region)."""
        page = self.current_page
        if zid is None:
            zid = self.selected_zone_id
        if zid is None:
            messagebox.showinfo("Rename Region", "No region selected.")
            return False
        zid = int(zid)
        names = self.zone_names.get(page, {}) or {}
        # Normalize keys
        names_norm = {int(k): v for k, v in names.items()}
        if zid not in names_norm:
            messagebox.showwarning("Rename Region", f"Region ID {zid} is not in the labeled list.")
            return False

        current_name = names_norm.get(zid, f"Region {zid}")
        new_name = simpledialog.askstring(
            "Rename Region",
            f"New name for region (ID={zid}):",
            initialvalue=str(current_name),
            parent=self.master,
        )
        if new_name is None:
            return False  # cancelled
        new_name = str(new_name).strip()
        if not new_name:
            messagebox.showwarning("Rename Region", "Name cannot be empty.")
            return False
        if new_name == current_name:
            return True

        self.save_state()
        if page not in self.zone_names:
            self.zone_names[page] = {}
        # Keep int keys for consistency
        self.zone_names[page] = {int(k): v for k, v in self.zone_names[page].items()}
        self.zone_names[page][zid] = new_name
        logger.info(f"Renamed region {zid}: '{current_name}' → '{new_name}'")

        if self.selected_zone_id == zid:
            self.selected_page = page
        self._update_ribbon_selection()
        self.show_page()
        return True

    def delete_labeled_region(self, zid=None, confirm=True):
        """Remove a labeled region from zone names, mask, and painted outlines.

        Undoable via save_state. Returns True if deleted.
        """
        page = self.current_page
        if zid is None:
            zid = self.selected_zone_id
        if zid is None:
            messagebox.showinfo("Delete Region", "No region selected.")
            return False
        zid = int(zid)
        names = {int(k): v for k, v in (self.zone_names.get(page, {}) or {}).items()}
        current_name = names.get(zid, f"Region {zid}")

        if confirm:
            ok = messagebox.askyesno(
                "Delete Region",
                f"Delete labeled region '{current_name}' (ID={zid})?\n\n"
                "This removes its name and counting zone from the mask.\n"
                "You can Undo (Ctrl+Z) if needed.",
                parent=self.master,
            )
            if not ok:
                return False

        self.save_state()

        # Remove name
        if page in self.zone_names:
            self.zone_names[page] = {int(k): v for k, v in self.zone_names[page].items()}
            self.zone_names[page].pop(zid, None)

        # Clear zone pixels from the mask
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                m = np.array(self.mask_images[page])
                m[m == zid] = 0
                self.mask_images[page] = Image.fromarray(m.astype(np.uint8), mode='L')
            except Exception as e:
                logger.warning(f"Could not clear mask pixels for zone {zid}: {e}")

        # Remove painted outline for this zone and rebuild black paint layer
        if hasattr(self, 'painted_zone_outlines') and self.painted_zone_outlines:
            try:
                # Keys may be int or str
                self.painted_zone_outlines.pop(zid, None)
                self.painted_zone_outlines.pop(str(zid), None)
            except Exception:
                pass
            try:
                self._rebuild_paint_layer_from_data()
            except Exception as e:
                logger.debug(f"Paint layer rebuild after delete: {e}")

        # Clear selection if we deleted the selected zone
        if self.selected_zone_id is not None and int(self.selected_zone_id) == zid:
            self.selected_zone_id = None
            self.selected_page = None
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self.region_move_mode.set(False)
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None

        self._context_menu_zone_id = None
        clear_preprocess_cache()

        try:
            if page in self.base_page_images or page in self.mask_images:
                self._rebuild_page_overlays(page)
        except Exception:
            pass
        self.show_page()
        self._update_ribbon_selection()
        logger.info(f"Deleted labeled region '{current_name}' (ID={zid}) on page {page}")
        return True

    def _quick_rotate_selected(self, degrees):
        if not self._has_selected_region():
            return
        self.save_state()
        page = self.selected_page
        zid = self.selected_zone_id
        if self._apply_transform_to_region(page, zid, angle_deg=degrees, scale_x=1.0, scale_y=1.0):
            self._update_ribbon_selection()
            self.show_page()

    def _quick_scale_selected(self, factor):
        if not self._has_selected_region():
            return
        self.save_state()
        page = self.selected_page
        zid = self.selected_zone_id
        if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=factor, scale_y=factor):
            self._update_ribbon_selection()
            self.show_page()

    def _show_region_dialogs(self):
        self.show_rotate_selected_dialog()

    def _quick_rotate_global(self, degrees):
        """Apply small rotation to the entire current atlas page (global, affects base + all masks)."""
        self.save_state()
        page = self.current_page
        # Transform the clean base (the atlas artwork) and the zone mask
        if page in self.base_page_images:
            base = self.base_page_images[page]
            rotated_base = base.rotate(degrees, expand=True)
            self.base_page_images[page] = rotated_base
        if page in self.mask_images:
            mask_img = self.mask_images[page]
            rotated_mask = mask_img.rotate(degrees, expand=True, resample=Image.NEAREST)
            self.mask_images[page] = rotated_mask
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self.show_page()

    def _quick_scale_global(self, factor):
        """Apply small uniform scale to the entire current atlas page (global, affects base + all masks)."""
        self.save_state()
        page = self.current_page
        if page in self.base_page_images:
            base = self.base_page_images[page]
            new_size = (int(base.width * factor), int(base.height * factor))
            resized_base = base.resize(new_size, Image.BILINEAR)
            self.base_page_images[page] = resized_base
        if page in self.mask_images:
            mask_img = self.mask_images[page]
            new_size = (int(mask_img.width * factor), int(mask_img.height * factor))
            resized_mask = mask_img.resize(new_size, Image.NEAREST)
            self.mask_images[page] = resized_mask
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self.show_page()

    # --- Border drag (expand/shrink selected region by grabbing its edge) ---
    def _update_cursor_for_atlas_border(self, event):
        """Change cursor when hovering near the border of the selected region (if border mode on)."""
        if not getattr(self, 'border_mode_var', None) or not self.border_mode_var.get():
            self.output.config(cursor="")
            return
        if not self.selected_zone_id or self.selected_page != self.current_page:
            self.output.config(cursor="")
            return
        if self.crop_mode or self.edit_mode or getattr(self, 'current_state', None) == 'paint':
            self.output.config(cursor="")
            return
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)
        if self._is_near_selected_border(mx, my, screen_tol=8):
            self.output.config(cursor="sizing")  # or "cross" / "fleur"
        else:
            self.output.config(cursor="")

    def _try_start_border_drag(self, event):
        """Click near edge of a named region: ensure the zone is the active one (orange fill),
        illuminate the local edge in red (persistent, toggle by re-click), prepare for grab/pull of only that edge.
        """
        if not getattr(self, 'border_mode_var', None) or not self.border_mode_var.get():
            return False
        if self.crop_mode or self.edit_mode or getattr(self, 'current_state', None) == 'paint':
            return False
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)

        # Priority: if we already have a selected/illuminated edge (red line), and click is on/near it,
        # treat as intent to grab that specific edge (re-center or start drag). This makes "grab the red line" reliable.
        if self.selected_edge_full_contour is not None and self._is_click_on_selected_edge(mx, my, screen_tol=10):
            # re-center on this click pos for precise "click a position"
            self._pick_local_edge(mx, my)
            self.edge_grab_start_mouse = (mx, my)
            self.edge_drag_start_pos = (mx, my)
            self._edge_pending_deselect = True
            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = True
            return True

        # Otherwise, find which named zone the click landed on (for initial edge illumination)
        page = self.current_page
        if page not in self.mask_images:
            return False
        m = np.array(self.mask_images[page])
        if not (0 <= int(my) < m.shape[0] and 0 <= int(mx) < m.shape[1]):
            return False
        clicked_zid = int(m[int(my), int(mx)])
        if clicked_zid == 0:
            # Forgiving hit-test for edge grabs: if click landed just outside the mask (zid=0)
            # but is near the border of the *currently selected* zone, treat as edge-grab intent
            # for that zone. This makes illuminating/grabbing the edge (or the red line) more
            # reliable, even if the exact integer pixel sample is outside the raster region.
            if (getattr(self, 'selected_zone_id', None) and
                    getattr(self, 'selected_page', None) == page and
                    self._is_near_selected_border(mx, my, screen_tol=8)):
                clicked_zid = self.selected_zone_id
            else:
                return False

        # Any positive label under cursor means the area is already claimed by a region.
        # Ensure it has a name entry (auto default if orphan) so it participates in the
        # labeled regions manager and future clicks autoselect instead of naming.
        self._ensure_zone_has_name(page, clicked_zid)

        # Make sure this zone is the active selected (orange fill + yellow boundary).
        # Re-set when click is on a different connected component of the same zid (e.g. L vs R mirror).
        need_reselect = (
            self.selected_zone_id != clicked_zid
            or getattr(self, 'selected_page', None) != page
        )
        if not need_reselect and getattr(self, 'selected_zone_component', None) is not None:
            try:
                comp = self.selected_zone_component
                iy, ix = int(my), int(mx)
                if (
                    isinstance(comp, np.ndarray)
                    and 0 <= iy < comp.shape[0]
                    and 0 <= ix < comp.shape[1]
                    and not bool(comp[iy, ix])
                ):
                    need_reselect = True  # same structure ID, other hemisphere blob
            except Exception:
                pass
        if need_reselect:
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self._set_zone_selection(page, clicked_zid, atlas_x=mx, atlas_y=my)
            self._rebuild_page_overlays(page)
            self._refresh_selection_boundary_visual()
            self.show_page()  # orange fill + yellow boundary visible immediately
            self._update_ribbon_selection()

        # Is the click on the border of the (now active) zone?
        if not self._is_near_selected_border(mx, my, screen_tol=8):
            # Interior click on the selected zone: if Move Selected Region mode, start translate
            if self.region_move_mode.get() and self.selected_zone_id == clicked_zid:
                self._start_region_translate(mx, my)
                return True
            # Claimed region (interior click on mask>0) -> autoselect in labeled regions manager
            # (we ensured a name above). Prevents the name dialog for already-labeled areas.
            return True  # always prevent falling through to name prompt for claimed zones


        # Edge click on the active zone: toggle deselect or select new edge for editing
        if self.selected_edge_full_contour is not None and self._is_click_on_selected_edge(mx, my, screen_tol=10):
            # Click on the currently illuminated edge at a specific position:
            # re-center the editable segment on *this* click point (so "click a position" chooses where to pull from),
            # update the red to the new local, then prepare for drag or deselect.
            self._pick_local_edge(mx, my)  # re-computes around the click pos, redraws red centered here
            self.edge_grab_start_mouse = (mx, my)
            self.edge_drag_start_pos = (mx, my)
            self._edge_pending_deselect = True
            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = True  # so motion handler proceeds to edge logic
            return True

        # Select/illuminate this local edge (red, persistent) and prepare for drag
        self._pick_local_edge(mx, my)
        self.edge_grab_start_mouse = (mx, my)
        self.edge_drag_start_pos = (mx, my)
        self.edge_grab_active = True
        self.border_drag_active = True  # activate the combined motion handler
        self._edge_pending_deselect = False
        self.save_state()
        return True

    def _pick_local_edge(self, mx, my):
        """Compute the local boundary segment around the click for the selected zone and draw it in red on the canvas."""
        self._clear_edge_highlight()
        self.active_edge = None
        self.current_edited_contour = None

        page = self.current_page
        zid = self.selected_zone_id
        if page not in self.mask_images:
            return
        m = np.array(self.mask_images[page])
        binr = (m == zid).astype(float)
        contours = measure.find_contours(binr, 0.5)
        if not contours:
            return
        # Main (longest) contour
        contour = max(contours, key=len)
        self.original_full_contour_for_edit = contour.copy()
        self.selected_edge_full_contour = contour.copy()

        # Closest point on contour
        dists = np.hypot(contour[:, 1] - mx, contour[:, 0] - my)
        cidx = int(np.argmin(dists))
        self.edge_closest_idx = cidx
        self.selected_edge_closest = cidx
        self.edge_window = 30
        n = len(contour)

        # Local window around the click (may wrap)
        start = (cidx - self.edge_window) % n
        end = (cidx + self.edge_window) % n
        if start < end:
            edge_pts = contour[start:end + 1].copy()
            self.edge_start_idx = start
            self.edge_end_idx = end
            self.selected_edge_start_idx = start
            self.selected_edge_end_idx = end
        else:
            edge_pts = np.vstack((contour[start:], contour[:end + 1])).copy()
            self.edge_start_idx = start
            self.edge_end_idx = end
            self.selected_edge_start_idx = start
            self.selected_edge_end_idx = end

        self.active_edge = edge_pts
        self._draw_edge_highlight(edge_pts)

    def _is_click_on_selected_edge(self, mx, my, screen_tol=10):
        """Return True if the click (in model coords) is close to the currently selected (illuminated) edge.
        screen_tol is the hit radius in screen pixels; converted to model using current view_scale.
        """
        if self.selected_edge_full_contour is None:
            return False
        # Prefer the active local segment if available
        if self.active_edge is not None and len(self.active_edge) > 0:
            edge = self.active_edge
        else:
            start = getattr(self, 'selected_edge_start_idx', 0)
            end = getattr(self, 'selected_edge_end_idx', 0)
            full = self.selected_edge_full_contour
            if start < end:
                edge = full[start:end+1]
            else:
                edge = np.vstack((full[start:], full[:end+1]))
        if len(edge) == 0:
            return False
        dists = np.hypot(edge[:,1] - mx, edge[:,0] - my)
        scale = max(getattr(self, 'view_scale', 1.0), 0.01)
        model_tol = screen_tol / scale
        return np.min(dists) < model_tol

    def _moved_enough_for_drag(self, event, threshold=5):
        """Return True if mouse has moved enough from the drag start to treat as a drag (not a click)."""
        if not hasattr(self, 'edge_drag_start_pos'):
            return False
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)
        dx = mx - self.edge_drag_start_pos[0]
        dy = my - self.edge_drag_start_pos[1]
        return math.hypot(dx, dy) > threshold

    def _draw_edge_highlight(self, edge_pts=None):
        self._clear_edge_highlight()
        if edge_pts is None:
            edge_pts = getattr(self, 'active_edge', None)
        if edge_pts is None or len(edge_pts) < 2:
            return
        scale = getattr(self, 'view_scale', 1.0)
        ox = float(getattr(self, 'img_x', 0)) * scale
        oy = float(getattr(self, 'img_y', 0)) * scale
        flat = []
        for y, x in edge_pts:
            sx = x * scale + ox
            sy = y * scale + oy
            flat.append(sx)
            flat.append(sy)
        if len(flat) > 2:
            try:
                item = self.output.create_line(flat, fill='red', width=4, capstyle=tk.ROUND, joinstyle=tk.ROUND, tag='edge_highlight')
                self.edge_highlight_item = item
                try:
                    self.output.tag_raise(item)
                except Exception:
                    pass
            except Exception:
                pass

    def _update_edge_highlight(self, edge_pts=None):
        if edge_pts is not None:
            self.active_edge = edge_pts
        if not hasattr(self, 'edge_highlight_item') or self.edge_highlight_item is None:
            self._draw_edge_highlight(edge_pts)
            return
        if edge_pts is None:
            edge_pts = getattr(self, 'active_edge', None)
        if edge_pts is None or len(edge_pts) < 2:
            return
        scale = getattr(self, 'view_scale', 1.0)
        ox = float(getattr(self, 'img_x', 0)) * scale
        oy = float(getattr(self, 'img_y', 0)) * scale
        flat = []
        for y, x in edge_pts:
            sx = x * scale + ox
            sy = y * scale + oy
            flat.append(sx)
            flat.append(sy)
        try:
            self.output.coords(self.edge_highlight_item, *flat)
        except Exception:
            self._draw_edge_highlight(edge_pts)

    def _clear_edge_highlight(self):
        if hasattr(self, 'edge_highlight_item') and self.edge_highlight_item:
            try:
                self.output.delete(self.edge_highlight_item)
            except Exception:
                pass
        self.edge_highlight_item = None
        try:
            self.output.delete('edge_highlight')
        except Exception:
            pass

    def _start_region_translate(self, mx, my):
        """Begin translating the selected region (only its mask pixels move; atlas base stays fixed)."""
        page = self.current_page
        zid = self.selected_zone_id
        if page not in self.mask_images or zid is None:
            return
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.region_translate_active = True
        self.region_translate_zid = zid
        self.region_translate_start_mx = mx
        self.region_translate_start_my = my
        self.region_translate_original_mask = self.mask_images[page].copy()
        self.border_drag_active = True  # so the motion handler runs the translate logic
        self.save_state()
        self.output.config(cursor="fleur")
        # Optional: brief hint
        # messagebox.showinfo("Region Translate", "Dragging will move only the selected region's area.", parent=self.master)  # avoid spam

    def _apply_region_translation(self, dx, dy):
        """Shift all pixels of the current translate zid by the (rounded) dx,dy from the snapshot."""
        page = self.current_page
        zid = self.region_translate_zid
        if page not in self.mask_images or zid is None or self.region_translate_original_mask is None:
            return
        mask = np.array(self.region_translate_original_mask)
        region = (mask == zid)
        if not np.any(region):
            return
        ys, xs = np.where(region)
        new_ys = ys + int(round(dy))
        new_xs = xs + int(round(dx))
        mask[region] = 0
        h, w = mask.shape
        valid = (new_ys >= 0) & (new_ys < h) & (new_xs >= 0) & (new_xs < w)
        mask[new_ys[valid], new_xs[valid]] = zid
        self.mask_images[page] = Image.fromarray(mask.astype(np.uint8), mode='L')
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)

    def _rasterize_contour_to_zone(self, contour, zid):
        """Replace the zone zid in the current page mask by filling the (modified) contour as a polygon."""
        if contour is None or len(contour) < 3:
            return
        page = self.current_page
        orig = np.array(self.mask_images[page])
        h, w = orig.shape
        fill_img = Image.new('L', (w, h), 0)
        dr = ImageDraw.Draw(fill_img)
        # contour is [[y, x], ...] -> PIL wants [(x, y), ...]
        pts = [(int(round(x)), int(round(y))) for y, x in contour]
        if len(pts) >= 3:
            dr.polygon(pts, fill=zid)
        new_zone = np.array(fill_img)
        current = orig.copy()
        current[current == zid] = 0
        current[new_zone == zid] = zid
        self.mask_images[page] = Image.fromarray(current.astype(np.uint8), mode='L')
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)

    def _refresh_atlas_layer(self):
        """Lightweight refresh of only the 'atlas' tagged image item.
        Used for live preview during edge drag so the yellow region shape updates as you pull the red edge.
        Must be called after _rasterize + _rebuild_page_overlays.
        """
        self.output.delete('atlas')
        page = self.current_page
        if page not in self.page_images:
            return
        img = self.page_images[page]
        scale = getattr(self, 'view_scale', 1.0)
        atlas_display = img
        if scale != 1.0:
            aw = max(1, int(img.width * scale))
            ah = max(1, int(img.height * scale))
            atlas_display = img.resize((aw, ah), Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(atlas_display)
        display_img_x = float(getattr(self, 'img_x', 0)) * float(scale)
        display_img_y = float(getattr(self, 'img_y', 0)) * float(scale)
        self.output.create_image(display_img_x, display_img_y,
                               image=self.photo,
                               anchor='nw',
                               tag='atlas')
        # Ensure the red edge highlight (if any) stays on top of the refreshed atlas image
        try:
            self.output.tag_raise('edge_highlight')
        except Exception:
            pass

    def _is_near_selected_border(self, model_x, model_y, screen_tol=8):
        """Return True if (model_x, model_y) is inside or near the border of the selected zone.
        screen_tol is desired hit radius in screen pixels (converted using view_scale).
        """
        page = self.current_page
        zid = self.selected_zone_id
        if page not in self.mask_images:
            return False
        m = np.array(self.mask_images[page])
        if not (0 <= int(model_y) < m.shape[0] and 0 <= int(model_x) < m.shape[1]):
            return False
        region = (m == zid)
        if not region.any():
            return False
        scale = max(getattr(self, 'view_scale', 1.0), 0.01)
        model_tol = screen_tol / scale
        # Use distance to the complement (outside the region) to detect border vicinity
        # Points inside near the edge have small distance to outside.
        try:
            from scipy.ndimage import distance_transform_edt
            # dist to nearest outside pixel
            outside_dist = distance_transform_edt(region)
            # Also consider if the point itself is on the region
            if region[int(model_y), int(model_x)]:
                d = outside_dist[int(model_y), int(model_x)]
                return d <= model_tol
            else:
                # if just outside, also allow if close
                # invert
                inside_dist = distance_transform_edt(~region)
                d = inside_dist[int(model_y), int(model_x)]
                return d <= model_tol
        except Exception:
            # Fallback: simple bbox check + on region
            ys, xs = np.where(region)
            if len(ys) == 0:
                return False
            miny, maxy, minx, maxx = ys.min(), ys.max(), xs.min(), xs.max()
            return (miny - model_tol <= model_y <= maxy + model_tol) and (minx - model_tol <= model_x <= maxx + model_tol) and region[int(model_y), int(model_x)]

    def _handle_border_drag_motion(self, event):
        if not getattr(self, 'border_drag_active', False):
            return
        if not self.border_mode_var.get() and not getattr(self, 'region_translate_active', False):
            return
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)

        # --- New precise edge editing: live update only the red edge line ---
        if getattr(self, '_edge_pending_deselect', False) or getattr(self, 'edge_grab_active', False):
            if not getattr(self, 'edge_grab_active', False):
                # First motion after mousedown on selected edge: decide if it's a drag
                if self._moved_enough_for_drag(event):
                    self.edge_grab_active = True
                    self.border_drag_active = True
                    self._edge_pending_deselect = False
            if getattr(self, 'edge_grab_active', False):
                if hasattr(self, 'original_full_contour_for_edit') and self.original_full_contour_for_edit is not None:
                    full = self.original_full_contour_for_edit.copy()
                    n = len(full)
                    cidx = getattr(self, 'edge_closest_idx', 0)
                    wnd = getattr(self, 'edge_window', 30)
                    dx = mx - self.edge_grab_start_mouse[0]
                    dy = my - self.edge_grab_start_mouse[1]
                    for j in range(-wnd, wnd + 1):
                        ii = (cidx + j) % n
                        ww = max(0.0, 1.0 - abs(j) / float(wnd + 1))
                        full[ii, 0] += dy * ww  # y
                        full[ii, 1] += dx * ww  # x
                    self.current_edited_contour = full
                    self.selected_edge_full_contour = full  # keep in sync for commit
                    # extract local for red highlight
                    if self.edge_start_idx < self.edge_end_idx:
                        local = full[self.edge_start_idx : self.edge_end_idx + 1]
                    else:
                        local = np.vstack((full[self.edge_start_idx:], full[:self.edge_end_idx + 1]))
                    self.active_edge = local
                    self._update_edge_highlight(local)

                    # Live update the region shape (the yellow/orange fill) as you pull the red edge.
                    # This fulfills "click a position to expand it or shrink it, and the shape of the region should adjust accordingly".
                    if self.selected_edge_full_contour is not None:
                        self._rasterize_contour_to_zone(self.selected_edge_full_contour, self.selected_zone_id)
                        self._refresh_atlas_layer()
            return

        # Region translate (move only the selected zone's pixels in the mask; atlas image/lines stay fixed)
        if getattr(self, 'region_translate_active', False):
            mx, my = self._canvas_to_zone_model(self.output.canvasx(event.x), self.output.canvasy(event.y))
            dx = mx - self.region_translate_start_mx
            dy = my - self.region_translate_start_my
            if self.region_translate_original_mask is not None:
                # restore snapshot then apply total offset (live)
                self.mask_images[self.current_page] = self.region_translate_original_mask.copy()
                self._apply_region_translation(dx, dy)
                self._refresh_atlas_layer()
            return

        # Fallback / legacy one-sided (kept for compatibility but not primary now)
        start_mx, start_my = getattr(self, 'border_drag_start_mouse', (0, 0))
        dx = mx - start_mx
        dy = my - start_my
        ux, uy = getattr(self, 'border_drag_unit', (0.0, 1.0))
        pull_amount = dx * ux + dy * uy
        page = self.current_page
        zid = getattr(self, 'border_drag_zone', None)
        if page in self.mask_images and getattr(self, 'border_drag_original_mask', None) is not None and zid is not None:
            self.mask_images[page] = self.border_drag_original_mask.copy()
            self._apply_border_pull(pull_amount)
            self.show_page()
            if hasattr(self, '_update_ribbon_selection'):
                self._update_ribbon_selection()

    def _end_border_drag(self, event):
        if getattr(self, '_edge_pending_deselect', False):
            # It was a short click on the already illuminated edge → toggle deselect (highlight disappears)
            self._clear_edge_highlight()
            self.selected_edge_full_contour = None
            self.active_edge = None
            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = False
            self._edge_pending_deselect = False
            self.current_edited_contour = None
            self.original_full_contour_for_edit = None
            return

        if getattr(self, 'edge_grab_active', False):
            did_edit = False
            if getattr(self, 'current_edited_contour', None) is not None and self.selected_edge_full_contour is not None:
                self._rasterize_contour_to_zone(self.selected_edge_full_contour, self.selected_zone_id)
                did_edit = True

            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = False
            self._edge_pending_deselect = False

            if hasattr(self, '_update_ribbon_selection'):
                self._update_ribbon_selection()

            if did_edit:
                # Only call show_page (which deletes all) when we actually changed the mask.
                # Then re-draw red after.
                self.show_page()
                if self.selected_edge_full_contour is not None:
                    start = getattr(self, 'selected_edge_start_idx', 0)
                    end = getattr(self, 'selected_edge_end_idx', 0)
                    if start < end:
                        local = self.selected_edge_full_contour[start:end+1]
                    else:
                        local = np.vstack((self.selected_edge_full_contour[start:], self.selected_edge_full_contour[:end+1]))
                    self.active_edge = local
                    self._draw_edge_highlight(local)
            # For pure select click (no edit), the red was drawn on mousedown and we avoid show_page
            # so it doesn't disappear on release.

            self.output.config(cursor="")
            return

        if getattr(self, 'region_translate_active', False):
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.region_translate_start_mx = 0
            self.region_translate_start_my = 0
            self.border_drag_active = False
            self.output.config(cursor="")
            if hasattr(self, '_update_ribbon_selection'):
                self._update_ribbon_selection()
            self.show_page()
            return

        if not getattr(self, 'border_drag_active', False):
            return
        self.border_drag_active = False
        self.border_drag_original_mask = None
        self.border_drag_start_mouse = (0.0, 0.0)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        if hasattr(self, '_update_ribbon_selection'):
            self._update_ribbon_selection()
        self.show_page()
        self.output.config(cursor="")

    def _commit_painted_border_refit(self, event=None):
        """Enter/Return: apply pending crop if active, else commit painted border refit.

        For crop: applies the outlined crop window after the user has drawn/moved it.
        For paint: commits the current mask shape (yellow expansion) by refitting the
        black drawn boundary (updating painted_zone_outlines from the live mask contour).
        """
        if getattr(self, "crop_mode", False) and getattr(self, "crop_pending", False):
            self._apply_pending_crop()
            return "break"

        zid = getattr(self, 'selected_zone_id', None)
        if not zid or zid not in getattr(self, 'painted_zone_outlines', {}):
            return
        page = self.current_page
        if page not in self.mask_images:
            return

        # Snapshot before committing the visual refit so this step is undoable independently
        self.save_state()
        m = np.array(self.mask_images[page])
        binr = (m == zid).astype(float)
        contours = measure.find_contours(binr, 0.5)
        if not contours:
            return
        new_contour = max(contours, key=len)
        new_points = [(int(round(x)), int(round(y))) for y, x in new_contour]
        self.painted_zone_outlines[zid]['points'] = new_points
        try:
            self._rebuild_paint_layer_from_data()
        except Exception:
            pass
        self.show_page()
        # Clean up any lingering edge highlight/red segment after commit
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        if hasattr(self, '_update_ribbon_selection'):
            self._update_ribbon_selection()

    def highlight_region(self, event):
        logger.debug(f"Highlighting region at ({event.x}, {event.y})")
        self.save_state()

        # Intercept for border drag resize if a region is selected and border mode is active
        if self._try_start_border_drag(event):
            return

        if not self.atlas_filetype or self.crop_mode or self.edit_mode:
            logger.debug("Highlight region aborted: atlas_filetype=%s, crop_mode=%s, edit_mode=%s", 
                      self.atlas_filetype, self.crop_mode, self.edit_mode)
            return

        canvas_x = self.output.canvasx(event.x)
        canvas_y = self.output.canvasy(event.y)
        mx, my = self._canvas_to_atlas(canvas_x, canvas_y)
        x, y = int(mx), int(my)  # convert to atlas model (native) coordinates, respecting view_scale

        img = self.load_page_image()
        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            logger.debug("Click outside image boundaries")
            return

        barrier_img = preprocess_for_highlighting(self.current_page, img, self.atlas_filetype)
        try:
            seed_value = barrier_img.getpixel((x, y))
            logger.debug(f"Seed value at click point: {seed_value}")
            if seed_value != 255:
                logger.debug("Clicked on a barrier")
                return  # clicked a barrier
        except Exception as e:
            logger.error(f"Error getting pixel value: {e}")
            return

        # If clicking inside an already-labeled region (mask zid>0), auto-select it in the
        # labeled regions manager instead of re-prompting for a name that may already exist.
        # The helper ensures a default name if the mask label was an orphan (so it appears
        # in the manager list and satisfies "autoselect from the labeled regions manager").
        if self.current_page in self.mask_images:
            m = np.array(self.mask_images[self.current_page])
            if 0 <= y < m.shape[0] and 0 <= x < m.shape[1]:
                zid = int(m[y, x])
                if zid == 0:
                    # Forgiving: click just outside (zid=0 at exact pixel) but near the border
                    # of the currently selected zone -> autoselect it instead of showing the
                    # name dialog. This prevents unwanted "name region" prompts when trying to
                    # grab the edge of an already-labeled/selected region.
                    if (getattr(self, 'selected_zone_id', None) and
                            getattr(self, 'selected_page', None) == self.current_page and
                            self._is_near_selected_border(mx, my, screen_tol=8)):
                        zid = self.selected_zone_id
                if zid > 0:
                    self._ensure_zone_has_name(self.current_page, zid)
                    if self.selected_zone_id != zid or getattr(self, 'selected_page', None) != self.current_page:
                        self.selected_zone_id = zid
                        self.selected_page = self.current_page
                        self._clear_edge_highlight()
                        self.edge_grab_active = False
                        self.active_edge = None
                        self.current_edited_contour = None
                        self.selected_edge_full_contour = None
                        self._edge_pending_deselect = False
                        self.region_move_mode.set(False)
                        self.region_translate_active = False
                        self.region_translate_original_mask = None
                        self.region_translate_zid = None
                        self._rebuild_page_overlays(self.current_page)
                        self._refresh_selection_boundary_visual()
                        self.show_page()
                        self._update_ribbon_selection()
                    return

        name = simpledialog.askstring("Region Name", "Enter a name for this region:")
        if name == None:
            return

        self.zone_counters[self.current_page] += 1
        zone_id = self.zone_counters[self.current_page]

        name = name.strip() 
        self.zone_names[self.current_page][zone_id] = name

        barrier_copy = barrier_img.copy()
        ImageDraw.floodfill(barrier_copy, (x, y), zone_id, thresh=0)
        filled = np.array(barrier_copy)
        mask = (filled == zone_id)

        mask_img = self.mask_images[self.current_page]
        mask_array = np.array(mask_img)
        mask_array[mask] = zone_id
        self.mask_images[self.current_page] = Image.fromarray(mask_array)

        # New zone created -> clear any previous edge edit state
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None

        # Rebuild display from clean base + current zones (including the newly named one).
        # This also handles any previously baked yellows from old code paths.
        self._rebuild_page_overlays(self.current_page)
        self.show_page()
        self._update_ribbon_selection()

    def _toggle_zone_labels_counts(self):
        """Show or hide the zone labels & counts table for the current file."""
        if self.show_zone_labels_var.get():
            self._open_zone_counts_window()
        else:
            self._close_zone_counts_window()
        self.show_page()

    def _toggle_zone_labels_intensities(self):
        """Show or hide region labels + mean intensities (Axons and Nets)."""
        if self.show_zone_intensity_labels_var.get():
            df, note = self._get_zone_intensities_dataframe()
            if df is None or df.empty:
                self.show_zone_intensity_labels_var.set(False)
                messagebox.showinfo(
                    "No Regions",
                    "No regions are defined for this image.\n\n"
                    "Load an atlas or paint named regions first.",
                )
                return
            self.last_intensity_df = df
            self._open_zone_intensity_window()
        else:
            self._close_zone_intensity_window()
        self.show_page()

    def _pil_to_gray_float(self, bg):
        """Convert a PIL image to float64 grayscale luminance (no display brightness)."""
        bg_arr = np.asarray(bg)
        if bg_arr.ndim == 3:
            return (
                0.2989 * bg_arr[..., 0].astype(np.float64)
                + 0.5870 * bg_arr[..., 1].astype(np.float64)
                + 0.1140 * bg_arr[..., 2].astype(np.float64)
            )
        return bg_arr.astype(np.float64).squeeze()

    def _zone_mask_registered_to_background(self, mask_img, bg_h, bg_w):
        """Place atlas/zone mask into background image coordinates.

        Returns (mask_on_bg uint8, original_mask_w, original_mask_h).
        """
        m = np.array(mask_img)
        if m.ndim > 2:
            m = m.squeeze()
        mh, mw = m.shape[:2]
        if abs(mw - bg_w) < 5 and abs(mh - bg_h) < 5:
            if (mw, mh) != (bg_w, bg_h):
                m = np.array(
                    Image.fromarray(m.astype(np.uint8), mode="L").resize(
                        (bg_w, bg_h), Image.NEAREST
                    )
                )
            return m.astype(np.uint8), mw, mh

        ox = int(round(float(getattr(self, "img_x", 0) or 0)))
        oy = int(round(float(getattr(self, "img_y", 0) or 0)))
        mask_on_bg = np.zeros((bg_h, bg_w), dtype=np.uint8)
        x0 = max(0, ox)
        y0 = max(0, oy)
        x1 = min(bg_w, ox + mw)
        y1 = min(bg_h, oy + mh)
        sx0 = x0 - ox
        sy0 = y0 - oy
        sx1 = sx0 + (x1 - x0)
        sy1 = sy0 + (y1 - y0)
        if x1 > x0 and y1 > y0:
            mask_on_bg[y0:y1, x0:x1] = m[sy0:sy1, sx0:sx1]
        return mask_on_bg, mw, mh

    def _resolve_norm_factor(self, zid, name, normalization_lookup):
        """Look up counterstain normalization factor by Zone_ID then Zone name."""
        if not normalization_lookup:
            return np.nan
        by_id = normalization_lookup.get("by_id") or {}
        by_name = normalization_lookup.get("by_name") or {}
        if int(zid) in by_id:
            return float(by_id[int(zid)])
        if str(zid) in by_id:
            try:
                return float(by_id[str(zid)])
            except Exception:
                pass
        if name in by_name:
            return float(by_name[name])
        # case-insensitive name match
        name_l = str(name).strip().lower()
        for k, v in by_name.items():
            if str(k).strip().lower() == name_l:
                return float(v)
        return np.nan

    def _compute_region_intensities_df(
        self,
        bg_percentile=None,
        normalization_lookup=None,
        mode="signal",
    ):
        """Compute per-region intensity stats on the current TIFF + zone mask.

        Parameters
        ----------
        bg_percentile : float or None
            If set (0–100), subtract the Xth percentile of intensities *within each
            region* from that region's pixels before computing stats
            (background subtraction).
        normalization_lookup : dict or None
            ``{"by_id": {zid: factor}, "by_name": {name: factor}}`` from a
            Counterstain Normalization Measurement export. Final mean is divided
            by the factor (axon/PNN ÷ counterstain).
        mode : str
            ``"signal"`` (default axon/PNN measure) or ``"counterstain_norm"``
            (writes Normalization_Factor = raw mean intensity).

        Returns (df, meta_dict) or (None, error_message).
        """
        page = self.current_page
        if page not in self.mask_images or self.mask_images[page] is None:
            return None, "No region mask is available."

        bg = None
        if getattr(self, "original_background", None) is not None:
            bg = self.original_background
        elif getattr(self, "background_image", None) is not None:
            bg = self.background_image
        if bg is None:
            return None, "No image is loaded."

        mask_img = self.mask_images[page]
        zone_names = dict(self.zone_names.get(page, {}) or {})

        gray = self._pil_to_gray_float(bg)
        bg_h, bg_w = gray.shape[:2]
        mask_on_bg, mw, mh = self._zone_mask_registered_to_background(mask_img, bg_h, bg_w)

        zids = set()
        for z in zone_names.keys():
            try:
                zids.add(int(z))
            except Exception:
                pass
        for z in np.unique(mask_on_bg):
            if int(z) > 0:
                zids.add(int(z))
                zone_names.setdefault(int(z), f"Zone {int(z)}")

        if not zids:
            return None, "No labeled regions found in the current mask."

        use_bg = bg_percentile is not None
        if use_bg:
            try:
                bg_percentile = float(bg_percentile)
            except Exception:
                return None, "Background percentile must be a number."
            if not (0.0 <= bg_percentile <= 100.0):
                return None, "Background percentile must be between 0 and 100."

        use_norm = bool(normalization_lookup) and mode != "counterstain_norm"
        rows = []
        for zid in sorted(zids):
            reg = mask_on_bg == int(zid)
            area = int(reg.sum())
            name = zone_names.get(zid, zone_names.get(int(zid), f"Zone {zid}"))
            empty = {
                "Zone_ID": int(zid),
                "Zone": name,
                "Region_Area": 0,
                # Explicit pre / post correction (always present in export)
                "Pre_Correction_Mean": np.nan,
                "Pre_Correction_Median": np.nan,
                "Post_Correction_Mean": np.nan,
                "Post_Correction_Median": np.nan,
                # Aliases used elsewhere (labels, legacy loaders)
                "Mean_Intensity_Raw": np.nan,
                "Median_Intensity_Raw": np.nan,
                "Mean_Intensity": np.nan,
                "Median_Intensity": np.nan,
                "Background_Level": np.nan,
                "Mean_Intensity_BGsub": np.nan,
                "Median_Intensity_BGsub": np.nan,
                "Normalization_Factor": np.nan,
                "Mean_Intensity_Normalized": np.nan,
                "Median_Intensity_Normalized": np.nan,
                "Sum_Intensity": np.nan,
                "Std_Intensity": np.nan,
                "Min_Intensity": np.nan,
                "Max_Intensity": np.nan,
            }
            if area <= 0:
                rows.append(empty)
                continue

            vals = gray[reg].astype(np.float64)
            raw_mean = float(np.mean(vals))
            raw_median = float(np.median(vals))
            bg_level = np.nan
            work = vals
            if use_bg:
                bg_level = float(np.percentile(vals, bg_percentile))
                work = vals - bg_level

            mean_bg = float(np.mean(work))
            median_bg = float(np.median(work))
            sum_bg = float(np.sum(work))
            std_bg = float(np.std(work))
            min_bg = float(np.min(work))
            max_bg = float(np.max(work))

            factor = np.nan
            mean_post = mean_bg
            median_post = median_bg
            sum_out = sum_bg
            if mode == "counterstain_norm":
                # Factor used later to normalize axon/PNN: divide by counterstain mean
                factor = raw_mean if raw_mean > 0 else np.nan
                mean_post = raw_mean
                median_post = raw_median
            elif use_norm:
                factor = self._resolve_norm_factor(zid, name, normalization_lookup)
                if factor is not None and not (isinstance(factor, float) and np.isnan(factor)):
                    try:
                        f = float(factor)
                        factor = f
                        if f > 1e-12:
                            mean_post = mean_bg / f
                            median_post = median_bg / f
                            sum_out = float(np.sum(work / f))
                        else:
                            mean_post = np.nan
                            median_post = np.nan
                            sum_out = np.nan
                    except Exception:
                        mean_post = np.nan
                        median_post = np.nan
                        sum_out = np.nan
                else:
                    factor = np.nan
                    mean_post = np.nan
                    median_post = np.nan
                    sum_out = np.nan
            # else: no norm — post is after optional BG only (mean_bg / median_bg)

            # If neither correction was requested, post == pre
            if mode != "counterstain_norm" and not use_bg and not use_norm:
                mean_post = raw_mean
                median_post = raw_median
                sum_out = float(np.sum(vals))
                std_bg = float(np.std(vals))
                min_bg = float(np.min(vals))
                max_bg = float(np.max(vals))

            rows.append(
                {
                    "Zone_ID": int(zid),
                    "Zone": name,
                    "Region_Area": area,
                    # Pre-correction = raw regional intensities (no BG / no norm)
                    "Pre_Correction_Mean": raw_mean,
                    "Pre_Correction_Median": raw_median,
                    # Post-correction = after optional BG subtract and/or counterstain norm
                    "Post_Correction_Mean": mean_post,
                    "Post_Correction_Median": median_post,
                    # Aliases
                    "Mean_Intensity_Raw": raw_mean,
                    "Median_Intensity_Raw": raw_median,
                    "Mean_Intensity": mean_post,  # labels / primary = post
                    "Median_Intensity": median_post,
                    "Background_Level": bg_level if use_bg else np.nan,
                    "Mean_Intensity_BGsub": mean_bg if use_bg else np.nan,
                    "Median_Intensity_BGsub": median_bg if use_bg else np.nan,
                    "Normalization_Factor": factor if (use_norm or mode == "counterstain_norm") else np.nan,
                    "Mean_Intensity_Normalized": mean_post if use_norm else np.nan,
                    "Median_Intensity_Normalized": median_post if use_norm else np.nan,
                    "Sum_Intensity": sum_out,
                    "Std_Intensity": std_bg,
                    "Min_Intensity": min_bg,
                    "Max_Intensity": max_bg,
                }
            )

        df = pd.DataFrame(rows)
        meta = {
            "bg_w": bg_w,
            "bg_h": bg_h,
            "mw": mw,
            "mh": mh,
            "page": page,
            "n_regions": len(rows),
            "mode": mode,
            "background_subtraction": bool(use_bg),
            "bg_percentile": float(bg_percentile) if use_bg else None,
            "counterstain_normalization": bool(use_norm),
            "normalization_file": (
                (normalization_lookup or {}).get("source_path") if use_norm else None
            ),
        }
        return df, meta

    def _get_zone_intensities_dataframe(self):
        """Return (DataFrame, source_note) for intensity labels / table."""
        df, meta_or_err = self._compute_region_intensities_df()
        if df is None:
            return None, str(meta_or_err or "")
        self.last_intensity_df = df
        return df.copy(), "Measured on current image (grayscale, no display brightness)"

    def _format_intensity_export_df(self, df):
        """Column order for intensity / counterstain exports.

        Pre_Correction_* = raw (before BG subtract / counterstain norm).
        Post_Correction_* = after all selected corrections (or equal to pre if none).
        """
        if df is None or df.empty:
            return df
        # Ensure pre/post columns exist even for older in-memory frames
        if "Pre_Correction_Mean" not in df.columns and "Mean_Intensity_Raw" in df.columns:
            df = df.copy()
            df["Pre_Correction_Mean"] = df["Mean_Intensity_Raw"]
            df["Pre_Correction_Median"] = df.get(
                "Median_Intensity_Raw", df.get("Median_Intensity")
            )
        if "Post_Correction_Mean" not in df.columns and "Mean_Intensity" in df.columns:
            df = df.copy() if "Pre_Correction_Mean" in df.columns else df
            if "Post_Correction_Mean" not in df.columns:
                df = df.copy()
            df["Post_Correction_Mean"] = df["Mean_Intensity"]
            df["Post_Correction_Median"] = df.get("Median_Intensity", np.nan)

        preferred = [
            "Zone",
            "Zone_ID",
            "Region_Area",
            "Pre_Correction_Mean",
            "Pre_Correction_Median",
            "Post_Correction_Mean",
            "Post_Correction_Median",
            "Background_Level",
            "Normalization_Factor",
            "Mean_Intensity_BGsub",
            "Median_Intensity_BGsub",
            "Mean_Intensity_Normalized",
            "Median_Intensity_Normalized",
            # Legacy aliases (same values as pre/post)
            "Mean_Intensity_Raw",
            "Median_Intensity_Raw",
            "Mean_Intensity",
            "Median_Intensity",
            "Sum_Intensity",
            "Std_Intensity",
            "Min_Intensity",
            "Max_Intensity",
        ]
        cols = [c for c in preferred if c in df.columns]
        cols += [c for c in df.columns if c not in cols]
        out = df[cols].copy()
        for c in out.columns:
            if c in ("Zone",):
                continue
            try:
                if c == "Zone_ID":
                    out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
                else:
                    out[c] = pd.to_numeric(out[c], errors="coerce")
            except Exception:
                pass
        return out

    def _build_intensity_parameter_sheet(self, meta):
        """Detection-Parameters-style sheet for intensity exports (mirrors Count Cells)."""
        meta = meta if isinstance(meta, dict) else {}
        rows = [
            {"Category": "Source", "Parameter": "Image", "Value": str(self.tiff_filename or "")},
            {
                "Category": "Source",
                "Parameter": "TIFF_Path",
                "Value": str(getattr(self, "current_tiff_path", "") or ""),
            },
            {
                "Category": "Source",
                "Parameter": "Image_Size",
                "Value": f"{meta.get('bg_w', '?')}x{meta.get('bg_h', '?')}",
            },
            {
                "Category": "Mask",
                "Parameter": "Mask_Size",
                "Value": f"{meta.get('mw', '?')}x{meta.get('mh', '?')}",
            },
            {
                "Category": "Mask",
                "Parameter": "Atlas_Offset_XY",
                "Value": f"{getattr(self, 'img_x', 0)},{getattr(self, 'img_y', 0)}",
            },
            {
                "Category": "Mask",
                "Parameter": "Atlas_Page",
                "Value": str(meta.get("page", self.current_page)),
            },
            {
                "Category": "Mask",
                "Parameter": "Atlas_Filetype",
                "Value": str(getattr(self, "atlas_filetype", "") or ""),
            },
            {
                "Category": "Measurement",
                "Parameter": "Mode",
                "Value": str(meta.get("mode", "signal")),
            },
            {
                "Category": "Measurement",
                "Parameter": "N_Regions",
                "Value": str(meta.get("n_regions", "")),
            },
            {
                "Category": "Measurement",
                "Parameter": "Intensity_Source",
                "Value": "original_background grayscale luminance (no display brightness)",
            },
            {
                "Category": "Measurement",
                "Parameter": "Luminance_Weights",
                "Value": "0.2989 R + 0.5870 G + 0.1140 B",
            },
            {
                "Category": "Background Subtraction",
                "Parameter": "Enabled",
                "Value": str(bool(meta.get("background_subtraction"))),
            },
            {
                "Category": "Background Subtraction",
                "Parameter": "Percentile",
                "Value": str(meta.get("bg_percentile") if meta.get("bg_percentile") is not None else ""),
            },
            {
                "Category": "Background Subtraction",
                "Parameter": "Method",
                "Value": (
                    "Per-region: subtract Xth percentile of pixel intensities within that region"
                    if meta.get("background_subtraction")
                    else ""
                ),
            },
            {
                "Category": "Counterstain Normalization",
                "Parameter": "Enabled",
                "Value": str(bool(meta.get("counterstain_normalization"))),
            },
            {
                "Category": "Counterstain Normalization",
                "Parameter": "Normalization_File",
                "Value": str(meta.get("normalization_file") or ""),
            },
            {
                "Category": "Counterstain Normalization",
                "Parameter": "Method",
                "Value": (
                    "Corrected_Mean = (Mean - BG_level) / Normalization_Factor; "
                    "Factor = counterstain regional mean intensity"
                    if meta.get("counterstain_normalization")
                    else (
                        "Normalization_Factor = counterstain regional mean intensity"
                        if meta.get("mode") == "counterstain_norm"
                        else ""
                    )
                ),
            },
            {
                "Category": "Measurement",
                "Parameter": "Generated_At",
                "Value": datetime.now().isoformat(timespec="seconds"),
            },
        ]
        try:
            page = self.current_page
            for zid, name in sorted(
                (self.zone_names.get(page, {}) or {}).items(),
                key=lambda kv: int(kv[0]) if str(kv[0]).lstrip("-").isdigit() else str(kv[0]),
            ):
                rows.append(
                    {
                        "Category": "Zone Names",
                        "Parameter": f"Zone_{zid}",
                        "Value": str(name),
                    }
                )
        except Exception:
            pass
        return pd.DataFrame(rows)

    def _ask_intensity_correction_options(self):
        """Modal dialog: optional background subtraction + counterstain normalization.

        Returns dict
          {use_bg, bg_percentile, use_norm, norm_path}
        or None if cancelled.
        """
        prefs = getattr(self, "_intensity_corr_prefs", {}) or {}
        win = Toplevel(self.master)
        win.title("Intensity Correction Options")
        win.transient(self.master)
        win.grab_set()
        win.resizable(False, False)
        try:
            self._register_transparent_window(win)
        except Exception:
            pass

        result = {"ok": False}

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text="Axon / PNN intensity measurement",
            font=("Helvetica", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(
            frm,
            text=(
                "Optionally correct each region for local background and/or divide by\n"
                "counterstain intensity measured with the same atlas (.catlas)."
            ),
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        use_bg_var = tk.BooleanVar(value=bool(prefs.get("use_bg", False)))
        use_norm_var = tk.BooleanVar(value=bool(prefs.get("use_norm", False)))
        pct_var = tk.StringVar(value=str(prefs.get("bg_percentile", 10.0)))
        path_var = tk.StringVar(value=str(prefs.get("norm_path", "") or ""))

        # --- Background ---
        bg_frame = ttk.LabelFrame(frm, text="Background subtraction", padding=8)
        bg_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)

        ttk.Checkbutton(
            bg_frame,
            text="Subtract Xth-percentile intensity within each region",
            variable=use_bg_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(bg_frame, text="Percentile (X):").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        pct_entry = ttk.Entry(bg_frame, textvariable=pct_var, width=8)
        pct_entry.grid(row=1, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(
            bg_frame,
            text="(typical: 5–20; 0 = min, 50 = median)",
            foreground="gray",
        ).grid(row=1, column=2, sticky="w", pady=(6, 0))

        ttk.Label(
            bg_frame,
            text="For each region: background = percentile of pixel values in that region;\n"
            "stats are computed after (pixel − background).",
            font=("Helvetica", 8),
            foreground="gray",
            justify=tk.LEFT,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # --- Normalization ---
        norm_frame = ttk.LabelFrame(frm, text="Counterstain normalization", padding=8)
        norm_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Checkbutton(
            norm_frame,
            text="Normalize by counterstain regional intensity",
            variable=use_norm_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(
            norm_frame,
            text="Normalization file (from Counterstain Normalization Measurement):",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 2))

        path_entry = ttk.Entry(norm_frame, textvariable=path_var, width=52)
        path_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 4))

        def browse_norm():
            initial = None
            cur = path_var.get().strip()
            if cur and os.path.isfile(cur):
                initial = os.path.dirname(cur)
            else:
                initial = self._preferred_open_dir(feature="intensities")
            p = fd.askopenfilename(
                title="Select counterstain normalization file",
                initialdir=initial,
                filetypes=[
                    ("Excel / CSV", "*.xlsx *.xls *.csv"),
                    ("Excel", "*.xlsx *.xls"),
                    ("CSV", "*.csv"),
                    ("All files", "*.*"),
                ],
                parent=win,
            )
            if p:
                path_var.set(p)

        ttk.Button(norm_frame, text="Browse…", command=browse_norm, width=10).grid(
            row=2, column=2, sticky="e"
        )

        ttk.Label(
            norm_frame,
            text="Corrected = (signal − background) ÷ Normalization_Factor\n"
            "Factor column comes from the counterstain measurement on the same atlas.",
            font=("Helvetica", 8),
            foreground="gray",
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # --- Buttons ---
        btn_row = ttk.Frame(frm)
        btn_row.grid(row=4, column=0, columnspan=3, sticky="e", pady=(12, 0))

        def on_cancel():
            result["ok"] = False
            win.destroy()

        def on_ok():
            use_bg = bool(use_bg_var.get())
            use_norm = bool(use_norm_var.get())
            pct = 10.0
            if use_bg:
                try:
                    pct = float(pct_var.get().strip())
                except Exception:
                    messagebox.showerror(
                        "Invalid percentile",
                        "Enter a numeric percentile between 0 and 100.",
                        parent=win,
                    )
                    return
                if not (0.0 <= pct <= 100.0):
                    messagebox.showerror(
                        "Invalid percentile",
                        "Percentile must be between 0 and 100.",
                        parent=win,
                    )
                    return
            path = path_var.get().strip()
            if use_norm:
                if not path:
                    messagebox.showerror(
                        "Normalization file required",
                        "Select the Excel/CSV file produced by\n"
                        "Axons and Nets → Counterstain Normalization Measurement…",
                        parent=win,
                    )
                    return
                if not os.path.isfile(path):
                    messagebox.showerror(
                        "File not found",
                        f"Normalization file does not exist:\n{path}",
                        parent=win,
                    )
                    return
            result["ok"] = True
            result["use_bg"] = use_bg
            result["bg_percentile"] = pct
            result["use_norm"] = use_norm
            result["norm_path"] = path if use_norm else ""
            win.destroy()

        ttk.Button(btn_row, text="Cancel", command=on_cancel, width=10).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_row, text="Measure", command=on_ok, width=10).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", on_cancel)
        # Center over main window
        try:
            win.update_idletasks()
            x = self.master.winfo_rootx() + 80
            y = self.master.winfo_rooty() + 80
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self.master.wait_window(win)

        if not result.get("ok"):
            return None
        opts = {
            "use_bg": result["use_bg"],
            "bg_percentile": result["bg_percentile"],
            "use_norm": result["use_norm"],
            "norm_path": result["norm_path"],
        }
        self._intensity_corr_prefs = dict(opts)
        return opts

    def _load_counterstain_normalization_file(self, path):
        """Load Normalization_Factor per region from a counterstain measurement export.

        Returns lookup dict:
          {"by_id": {int: float}, "by_name": {str: float}, "source_path": path, "df": DataFrame}
        or (None, error_message).
        """
        if not path or not os.path.isfile(path):
            return None, "Normalization file not found."

        try:
            low = path.lower()
            if low.endswith(".csv"):
                df = pd.read_csv(path)
            else:
                # Prefer dedicated sheet name, then fall back
                df = None
                last_err = None
                for sheet in (
                    "Counterstain Normalization",
                    "Region Intensities",
                    0,
                ):
                    try:
                        df = pd.read_excel(path, sheet_name=sheet)
                        break
                    except Exception as e:
                        last_err = e
                        df = None
                if df is None:
                    return None, f"Could not read Excel sheet: {last_err}"
        except Exception as e:
            return None, f"Failed to read normalization file:\n{e}"

        if df is None or df.empty:
            return None, "Normalization file is empty."

        # Normalize column names (strip, lower for matching)
        colmap = {c: str(c).strip() for c in df.columns}
        df = df.rename(columns=colmap)
        cols_l = {str(c).strip().lower(): c for c in df.columns}

        def col(*names):
            for n in names:
                if n.lower() in cols_l:
                    return cols_l[n.lower()]
            return None

        c_factor = col(
            "Normalization_Factor",
            "normalization_factor",
            "Norm_Factor",
            "Factor",
        )
        c_mean = col("Mean_Intensity", "Mean_Intensity_Raw", "mean_intensity")
        c_id = col("Zone_ID", "zone_id", "ZoneId", "ID")
        c_name = col("Zone", "zone", "Region", "Name")

        if c_factor is None and c_mean is None:
            return None, (
                "Normalization file must contain a Normalization_Factor column\n"
                "(or Mean_Intensity from Counterstain Normalization Measurement)."
            )
        if c_id is None and c_name is None:
            return None, "Normalization file must contain Zone_ID and/or Zone columns."

        by_id = {}
        by_name = {}
        for _, row in df.iterrows():
            factor = None
            if c_factor is not None:
                try:
                    factor = float(row[c_factor])
                except Exception:
                    factor = None
            if (factor is None or (isinstance(factor, float) and np.isnan(factor))) and c_mean is not None:
                try:
                    factor = float(row[c_mean])
                except Exception:
                    factor = None
            if factor is None or (isinstance(factor, float) and (np.isnan(factor) or factor <= 0)):
                continue
            if c_id is not None:
                try:
                    zid = int(float(row[c_id]))
                    by_id[zid] = float(factor)
                except Exception:
                    pass
            if c_name is not None:
                nm = row[c_name]
                if pd.notna(nm) and str(nm).strip():
                    by_name[str(nm).strip()] = float(factor)

        if not by_id and not by_name:
            return None, "No valid positive normalization factors found in the file."

        return {
            "by_id": by_id,
            "by_name": by_name,
            "source_path": path,
            "df": df,
        }, None

    def _export_region_intensity_workbook(
        self, df, meta, out_dir, base_name, *, kind="intensities"
    ):
        """Write intensity results as multi-sheet .xlsx under output/intensities/.

        kind:
          - ``intensities`` → ``{base}_intensities.xlsx`` sheet Region Intensities
          - ``counterstain_norm`` → ``{base}_counterstain_norm.xlsx`` sheet Counterstain Normalization

        Returns (path, format) where format is 'xlsx' or 'csv', or (None, None) on failure.
        """
        if df is None or df.empty or not out_dir or not base_name:
            return None, None

        export_df = self._format_intensity_export_df(df)
        if kind == "counterstain_norm":
            # Lean export focused on factors for later axon normalization
            keep = [
                c
                for c in (
                    "Zone",
                    "Zone_ID",
                    "Region_Area",
                    "Mean_Intensity",
                    "Median_Intensity",
                    "Normalization_Factor",
                    "Std_Intensity",
                    "Min_Intensity",
                    "Max_Intensity",
                )
                if c in export_df.columns
            ]
            if keep:
                export_df = export_df[keep]
            xlsx_path = os.path.join(out_dir, f"{base_name}_counterstain_norm.xlsx")
            data_sheet = "Counterstain Normalization"
            csv_path = os.path.join(out_dir, f"{base_name}_counterstain_norm.csv")
            legacy_path = None
        else:
            xlsx_path = os.path.join(out_dir, f"{base_name}_intensities.xlsx")
            data_sheet = "Region Intensities"
            csv_path = os.path.join(out_dir, f"{base_name}_intensities.csv")
            legacy_path = os.path.join(out_dir, f"{base_name}_region_intensity.xlsx")

        param_df = self._build_intensity_parameter_sheet(meta)

        excel_errors = []
        for engine in ("openpyxl", "xlsxwriter"):
            try:
                with pd.ExcelWriter(xlsx_path, engine=engine) as writer:
                    export_df.to_excel(writer, sheet_name=data_sheet, index=False)
                    param_df.to_excel(writer, sheet_name="Measurement Parameters", index=False)
                if os.path.isfile(xlsx_path) and os.path.getsize(xlsx_path) > 0:
                    if legacy_path:
                        try:
                            import shutil
                            shutil.copy2(xlsx_path, legacy_path)
                        except Exception:
                            pass
                    logger.info(f"Intensity Excel saved: {xlsx_path} (engine={engine})")
                    return xlsx_path, "xlsx"
            except Exception as e:
                excel_errors.append(f"{engine}: {e}")
                logger.warning(f"Intensity Excel engine {engine} failed: {e}")

        try:
            export_df.to_csv(csv_path, index=False)
            try:
                param_df.to_csv(
                    os.path.splitext(csv_path)[0] + "_parameters.csv",
                    index=False,
                )
            except Exception:
                pass
            logger.info(f"Intensity CSV fallback: {csv_path}")
            if excel_errors:
                messagebox.showwarning(
                    "Excel Export Failed",
                    "Could not save as Excel "
                    "(openpyxl/xlsxwriter missing or failed).\n\n"
                    f"Fell back to CSV:\n{csv_path}\n\n"
                    "To enable .xlsx output, run:\n"
                    "pip install openpyxl\n\n"
                    + "\n".join(excel_errors[:3]),
                )
            return csv_path, "csv"
        except Exception as e:
            logger.error(f"Intensity CSV fallback failed: {e}", exc_info=True)
            return None, None

    def _intensity_output_basename_and_dir(self, feature="intensities"):
        """Resolve (base_name, tiff_dir, out_dir) for intensity / PNN exports.

        ``feature`` selects the output subfolder (default ``intensities``;
        use ``pnn`` for perineuronal tables).
        """
        base_name = self.tiff_filename
        tiff_dir = self.tiff_dir or self.current_tiff_directory
        if not base_name and getattr(self, "current_tiff_path", None):
            base_name = os.path.splitext(os.path.basename(self.current_tiff_path))[0]
            if not tiff_dir:
                tiff_dir = os.path.dirname(self.current_tiff_path)
        if not base_name:
            base_name = "regions"
        out_dir = self._get_output_directory(tiff_dir, feature=feature) if tiff_dir else None
        return base_name, tiff_dir, out_dir

    def measure_counterstain_normalization(self):
        """Measure per-region counterstain intensity → Normalization_Factor table.

        Run this on the counterstain channel (e.g. DAPI) with the same .catlas /
        atlas regions used for axon/PNN. Output is consumed later by
        Measure Region Intensities → Counterstain normalization.
        """
        try:
            df, meta_or_err = self._compute_region_intensities_df(
                bg_percentile=None,
                normalization_lookup=None,
                mode="counterstain_norm",
            )
            if df is None:
                msg = str(meta_or_err or "Could not measure counterstain intensities.")
                messagebox.showwarning(
                    "Counterstain Normalization",
                    f"{msg}\n\nLoad the counterstain TIFF, load the same atlas/"
                    ".catlas, then try again.",
                )
                return

            meta = meta_or_err if isinstance(meta_or_err, dict) else {}
            n_rows = int(meta.get("n_regions", len(df)) or len(df))
            base_name, tiff_dir, out_dir = self._intensity_output_basename_and_dir()
            saved_paths = []
            out_path = None

            if out_dir:
                out_path, fmt = self._export_region_intensity_workbook(
                    df, meta, out_dir, base_name, kind="counterstain_norm"
                )
                if out_path:
                    saved_paths.append(
                        f"Counterstain norm ({'Excel' if fmt == 'xlsx' else 'CSV'}): {out_path}"
                    )
            else:
                path = fd.asksaveasfilename(
                    title="Save counterstain normalization table",
                    defaultextension=".xlsx",
                    filetypes=[
                        ("Excel", "*.xlsx"),
                        ("CSV", "*.csv"),
                        ("All files", "*.*"),
                    ],
                    initialfile=f"{base_name}_counterstain_norm.xlsx",
                )
                if not path:
                    return
                export_df = self._format_intensity_export_df(df)
                keep = [
                    c
                    for c in (
                        "Zone",
                        "Zone_ID",
                        "Region_Area",
                        "Mean_Intensity",
                        "Median_Intensity",
                        "Normalization_Factor",
                    )
                    if c in export_df.columns
                ]
                if keep:
                    export_df = export_df[keep]
                if path.lower().endswith(".csv"):
                    export_df.to_csv(path, index=False)
                    out_path = path
                else:
                    if not path.lower().endswith(".xlsx"):
                        path = path + ".xlsx"
                    param_df = self._build_intensity_parameter_sheet(meta)
                    ok = False
                    for engine in ("openpyxl", "xlsxwriter"):
                        try:
                            with pd.ExcelWriter(path, engine=engine) as writer:
                                export_df.to_excel(
                                    writer,
                                    sheet_name="Counterstain Normalization",
                                    index=False,
                                )
                                param_df.to_excel(
                                    writer,
                                    sheet_name="Measurement Parameters",
                                    index=False,
                                )
                            ok = True
                            break
                        except Exception as e:
                            logger.warning(f"Counterstain Excel ({engine}): {e}")
                    if ok:
                        out_path = path
                    else:
                        csv_path = os.path.splitext(path)[0] + ".csv"
                        export_df.to_csv(csv_path, index=False)
                        out_path = csv_path
                if out_path:
                    saved_paths.append(f"Counterstain norm: {out_path}")

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            if saved_paths:
                dest = out_dir or (os.path.dirname(out_path) if out_path else "")
                messagebox.showinfo(
                    "Counterstain Normalization Saved",
                    f"Measured {n_rows} region(s) on the counterstain channel.\n\n"
                    f"Normalization_Factor = regional mean intensity "
                    f"(use as divisor for axon/PNN).\n\n"
                    + (f"Saved to:\n{dest}\n\n" if dest else "")
                    + "\n".join(saved_paths)
                    + "\n\nNext: open the axon/PNN channel (same atlas), then\n"
                    "Axons and Nets → Measure Region Intensities… and enable\n"
                    "counterstain normalization with this file.",
                )
                logger.info(f"Counterstain normalization export: {saved_paths}")
            else:
                messagebox.showwarning(
                    "Export Failed",
                    f"Measured {n_rows} region(s), but could not write the file.\n"
                    "Ensure the folder is writable and openpyxl is installed.",
                )
        except Exception as e:
            logger.error(f"measure_counterstain_normalization failed: {e}", exc_info=True)
            messagebox.showerror(
                "Counterstain Normalization",
                f"Failed to measure counterstain normalization:\n{e}",
            )

    def measure_region_intensities(self):
        """Measure mean/median intensity and area of each Atlas Manager region.

        Prompts for optional background subtraction (Xth percentile within each
        region) and counterstain normalization (file from Counterstain
        Normalization Measurement). Writes multi-sheet Excel under output/intensities/.
        """
        try:
            # Confirm atlas/image exist before showing options dialog
            page = self.current_page
            if page not in self.mask_images or self.mask_images[page] is None:
                messagebox.showwarning(
                    "Axons and Nets",
                    "No region mask is available.\n\n"
                    "Load an atlas or .catlas (or paint named regions), then try again.",
                )
                return
            if (
                getattr(self, "original_background", None) is None
                and getattr(self, "background_image", None) is None
            ):
                messagebox.showwarning(
                    "Axons and Nets",
                    "No image is loaded.\n\nOpen a TIFF from the File Browser first.",
                )
                return

            opts = self._ask_intensity_correction_options()
            if opts is None:
                return  # cancelled

            bg_percentile = opts["bg_percentile"] if opts.get("use_bg") else None
            normalization_lookup = None
            if opts.get("use_norm"):
                normalization_lookup, err = self._load_counterstain_normalization_file(
                    opts.get("norm_path")
                )
                if normalization_lookup is None:
                    messagebox.showerror(
                        "Normalization file",
                        err or "Could not load counterstain normalization file.",
                    )
                    return

            df, meta_or_err = self._compute_region_intensities_df(
                bg_percentile=bg_percentile,
                normalization_lookup=normalization_lookup,
                mode="signal",
            )
            if df is None:
                msg = str(meta_or_err or "Could not measure intensities.")
                messagebox.showwarning("Axons and Nets", msg)
                return

            meta = meta_or_err if isinstance(meta_or_err, dict) else {}
            self.last_intensity_df = df
            n_rows = int(meta.get("n_regions", len(df)) or len(df))

            base_name, tiff_dir, out_dir = self._intensity_output_basename_and_dir()
            saved_paths = []
            intensities_path = None

            if out_dir:
                intensities_path, fmt = self._export_region_intensity_workbook(
                    df, meta, out_dir, base_name, kind="intensities"
                )
                if intensities_path:
                    label = "Intensities (Excel)" if fmt == "xlsx" else "Intensities (CSV)"
                    saved_paths.append(f"{label}: {intensities_path}")
            else:
                path = fd.asksaveasfilename(
                    title="Save region intensity table",
                    defaultextension=".xlsx",
                    filetypes=[
                        ("Excel", "*.xlsx"),
                        ("CSV", "*.csv"),
                        ("All files", "*.*"),
                    ],
                    initialfile=f"{base_name}_intensities.xlsx",
                )
                if not path:
                    messagebox.showinfo(
                        "Measure Complete",
                        f"Measured {n_rows} region(s), but no output folder was available "
                        "and save was cancelled.\n\nOpen a TIFF from the File Browser so "
                        "results can be written to <folder>/output/intensities/.",
                    )
                    if self.show_zone_intensity_labels_var.get():
                        self._open_zone_intensity_window()
                        self.show_page()
                    return
                if path.lower().endswith(".csv"):
                    self._format_intensity_export_df(df).to_csv(path, index=False)
                    intensities_path = path
                    saved_paths.append(f"Intensities (CSV): {path}")
                else:
                    if not path.lower().endswith(".xlsx"):
                        path = path + ".xlsx"
                    export_df = self._format_intensity_export_df(df)
                    param_df = self._build_intensity_parameter_sheet(meta)
                    excel_ok = False
                    for engine in ("openpyxl", "xlsxwriter"):
                        try:
                            with pd.ExcelWriter(path, engine=engine) as writer:
                                export_df.to_excel(
                                    writer, sheet_name="Region Intensities", index=False
                                )
                                param_df.to_excel(
                                    writer, sheet_name="Measurement Parameters", index=False
                                )
                            excel_ok = True
                            break
                        except Exception as e:
                            logger.warning(f"Manual intensity Excel ({engine}): {e}")
                    if excel_ok:
                        intensities_path = path
                        saved_paths.append(f"Intensities (Excel): {path}")
                    else:
                        csv_path = os.path.splitext(path)[0] + ".csv"
                        export_df.to_csv(csv_path, index=False)
                        intensities_path = csv_path
                        saved_paths.append(f"Intensities (CSV): {csv_path}")

            if self.show_zone_intensity_labels_var.get():
                self._open_zone_intensity_window()
                self.show_page()

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            if saved_paths:
                dest = out_dir or (
                    os.path.dirname(intensities_path) if intensities_path else ""
                )
                corr_bits = []
                if meta.get("background_subtraction"):
                    corr_bits.append(
                        f"BG subtract: {meta.get('bg_percentile')}th percentile / region"
                    )
                if meta.get("counterstain_normalization"):
                    corr_bits.append(
                        f"Normalized by: {meta.get('normalization_file') or 'counterstain file'}"
                    )
                if not corr_bits:
                    corr_bits.append("No BG subtract / no counterstain normalization")
                summary = (
                    f"Measured {n_rows} region(s).\n\n"
                    + "\n".join(corr_bits)
                    + "\n\nResults saved"
                    + (f" to output folder:\n{dest}\n\n" if dest else ":\n\n")
                    + "\n".join(saved_paths)
                    + "\n\nSheets: Region Intensities | Measurement Parameters\n"
                    "Key columns: Pre_Correction_Mean/Median, "
                    "Post_Correction_Mean/Median, Background_Level, Normalization_Factor."
                )
                messagebox.showinfo("Region Intensities Saved", summary)
                logger.info(f"Region intensities export complete: {saved_paths}")
            else:
                messagebox.showwarning(
                    "Export Failed",
                    f"Measured {n_rows} region(s), but could not write an Excel/CSV file.\n\n"
                    "Check that the image folder is writable and that openpyxl is installed:\n"
                    "pip install openpyxl",
                )
        except Exception as e:
            logger.error(f"measure_region_intensities failed: {e}", exc_info=True)
            messagebox.showerror("Axons and Nets", f"Failed to measure intensities:\n{e}")

    def _get_zone_counts_dataframe(self):
        """Return (DataFrame, source_note) for the current file's zone counts."""
        if self.last_df is not None and not self.last_df.empty:
            if 'Zone' in self.last_df.columns and 'Cell_Count' in self.last_df.columns:
                return self.last_df.copy(), "Current session counts"

        saved_df = self._load_saved_counts_df()
        if saved_df is not None and not saved_df.empty:
            return saved_df, "Loaded from saved results file"

        page_zones = self.zone_names.get(self.current_page, {})
        if not page_zones and self.current_page in self.mask_images:
            try:
                mask_arr = np.array(self.mask_images[self.current_page])
                for zid in np.unique(mask_arr):
                    if int(zid) > 0:
                        page_zones.setdefault(int(zid), f"Zone {int(zid)}")
            except Exception:
                pass

        if page_zones:
            rows = []
            for zid in sorted(page_zones.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
                area = '—'
                try:
                    page = self.current_page
                    if page in self.mask_images and self.mask_images[page] is not None:
                        m = np.array(self.mask_images[page])
                        area = int(np.sum(m == int(zid)))
                except Exception:
                    pass
                rows.append({'Zone': page_zones[zid], 'Cell_Count': '—', 'Region_Area': area})
            return pd.DataFrame(rows), "Zones defined — run Count Cells to populate counts"

        return None, ""

    def _load_saved_counts_df(self):
        """Load zone counts from a saved CSV/XLSX for the current TIFF, if present.

        Prefers <image_dir>/output/counts/ (and other feature dirs), then legacy files beside the TIFF.
        """
        if not self.tiff_dir or not self.tiff_filename:
            return None

        base_name = self.tiff_filename
        name_candidates = [
            (f"{base_name}.xlsx", 'xlsx'),
            (f"{base_name}.csv", 'csv'),
            (f"{base_name}_counted.xlsx", 'xlsx'),
            (f"{base_name}_counted.csv", 'csv'),
            (f"{base_name} - counted.xlsx", 'xlsx'),
            (f"{base_name} - counted.csv", 'csv'),
            (f"{base_name}_cells.xlsx", 'xlsx'),
            (f"{base_name}_cells.csv", 'csv'),
            (f"{base_name}_counts.xlsx", 'xlsx'),
            (f"{base_name}_counts.csv", 'csv'),
        ]
        candidates = []
        for search_dir in self._artifact_search_dirs(self.tiff_dir):
            for name, fmt in name_candidates:
                candidates.append((os.path.join(search_dir, name), fmt))

        for path, fmt in candidates:
            if not os.path.exists(path):
                continue
            try:
                if fmt == 'xlsx':
                    df = pd.read_excel(path, sheet_name='Cell Counts')
                else:
                    df = pd.read_csv(path)
                if 'Zone' in df.columns and 'Cell_Count' in df.columns:
                    cols = ['Zone', 'Cell_Count']
                    if 'Region_Area' in df.columns:
                        cols.append('Region_Area')
                    return df[cols].copy()
            except Exception as e:
                logger.debug(f"Could not load counts from {path}: {e}")
                continue
        return None

    def _open_zone_counts_window(self):
        """Open (or refresh) a tabular view of zone names and cell counts."""
        df, source_note = self._get_zone_counts_dataframe()
        if df is None or df.empty:
            self.show_zone_labels_var.set(False)
            messagebox.showinfo(
                "No Zones",
                "No zones are defined for this file.\n\n"
                "Define regions on the atlas or with the Paint tool, then run Count Cells."
            )
            return

        if self.zone_counts_window is not None and self.zone_counts_window.winfo_exists():
            self._populate_zone_counts_tree(df, source_note)
            self.zone_counts_window.lift()
            return

        win = Toplevel(self.master)
        self.zone_counts_window = win
        title_name = self.tiff_filename or "current file"
        win.title(f"Zone Labels & Counts — {title_name}")
        win.geometry("480x360")
        win.transient(self.master)

        header = ttk.Frame(win, padding=(8, 8, 8, 4))
        header.pack(fill='x')
        ttk.Label(
            header,
            text=f"Zone labels and cell counts for {title_name}",
            font=("Helvetica", 10, "bold"),
        ).pack(anchor='w')
        self.zone_counts_source_label = ttk.Label(header, text=source_note, foreground='gray')
        self.zone_counts_source_label.pack(anchor='w')

        table_frame = ttk.Frame(win, padding=(8, 4, 8, 8))
        table_frame.pack(fill='both', expand=True)

        columns = ("zone", "count", "area")
        self.zone_counts_tree = ttk.Treeview(
            table_frame, columns=columns, show='headings', selectmode='browse'
        )
        self.zone_counts_tree.heading("zone", text="Zone")
        self.zone_counts_tree.heading("count", text="Cell Count")
        self.zone_counts_tree.heading("area", text="Region Area (px)")
        self.zone_counts_tree.column("zone", width=240, anchor='w')
        self.zone_counts_tree.column("count", width=100, anchor='center')
        self.zone_counts_tree.column("area", width=120, anchor='center')

        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.zone_counts_tree.yview)
        self.zone_counts_tree.configure(yscrollcommand=yscroll.set)
        self.zone_counts_tree.pack(side='left', fill='both', expand=True)
        yscroll.pack(side='right', fill='y')

        footer = ttk.Frame(win, padding=(8, 0, 8, 8))
        footer.pack(fill='x')
        self.zone_counts_total_label = ttk.Label(footer, text="")
        self.zone_counts_total_label.pack(anchor='w')

        def on_close():
            self.show_zone_labels_var.set(False)
            self.zone_counts_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._populate_zone_counts_tree(df, source_note)

    def _populate_zone_counts_tree(self, df, source_note=""):
        """Fill the zone counts Treeview from a DataFrame."""
        if not hasattr(self, 'zone_counts_tree') or self.zone_counts_tree is None:
            return
        if not self.zone_counts_tree.winfo_exists():
            return

        for item in self.zone_counts_tree.get_children():
            self.zone_counts_tree.delete(item)

        total = 0
        total_area = 0
        has_numeric_counts = False
        has_numeric_area = False
        for _, row in df.iterrows():
            zone_name = str(row.get('Zone', ''))
            count_val = row.get('Cell_Count', '')
            if pd.isna(count_val):
                count_display = '—'
            elif isinstance(count_val, (int, float, np.integer, np.floating)):
                count_display = str(int(count_val))
                total += int(count_val)
                has_numeric_counts = True
            else:
                count_display = str(count_val)
                if str(count_val).isdigit():
                    total += int(count_val)
                    has_numeric_counts = True

            area_val = row.get('Region_Area', '')
            if pd.isna(area_val) or area_val == '' or area_val is None:
                area_display = '—'
            elif isinstance(area_val, (int, float, np.integer, np.floating)):
                area_display = str(int(area_val))
                total_area += int(area_val)
                has_numeric_area = True
            else:
                area_display = str(area_val)
                if str(area_val).isdigit():
                    total_area += int(area_val)
                    has_numeric_area = True

            self.zone_counts_tree.insert("", "end", values=(zone_name, count_display, area_display))

        if hasattr(self, 'zone_counts_source_label') and self.zone_counts_source_label.winfo_exists():
            self.zone_counts_source_label.config(text=source_note)

        if hasattr(self, 'zone_counts_total_label') and self.zone_counts_total_label.winfo_exists():
            parts = []
            if has_numeric_counts:
                parts.append(f"Total cells: {total}")
            if has_numeric_area:
                parts.append(f"Total region area: {total_area} px")
            self.zone_counts_total_label.config(text="  |  ".join(parts) if parts else "")

    def _close_zone_counts_window(self):
        """Hide the zone counts table window."""
        if self.zone_counts_window is not None and self.zone_counts_window.winfo_exists():
            self.zone_counts_window.destroy()
        self.zone_counts_window = None

    def _refresh_zone_counts_table(self):
        """Refresh the open zone counts table after counts change."""
        if not self.show_zone_labels_var.get():
            return
        if self.zone_counts_window is None or not self.zone_counts_window.winfo_exists():
            return
        df, source_note = self._get_zone_counts_dataframe()
        if df is not None and not df.empty:
            self._populate_zone_counts_tree(df, source_note)

    def _open_zone_intensity_window(self):
        """Open (or refresh) a tabular view of zone names and intensities."""
        df, source_note = self._get_zone_intensities_dataframe()
        if df is None or df.empty:
            self.show_zone_intensity_labels_var.set(False)
            messagebox.showinfo(
                "No Regions",
                "No regions are defined for this file.\n\n"
                "Define regions on the atlas or with the Paint tool first.",
            )
            return

        if self.zone_intensity_window is not None and self.zone_intensity_window.winfo_exists():
            self._populate_zone_intensity_tree(df, source_note)
            self.zone_intensity_window.lift()
            return

        win = Toplevel(self.master)
        self.zone_intensity_window = win
        title_name = self.tiff_filename or "current file"
        win.title(f"Zone Labels & Intensities — {title_name}")
        win.geometry("720x400")
        win.transient(self.master)

        header = ttk.Frame(win, padding=(8, 8, 8, 4))
        header.pack(fill="x")
        ttk.Label(
            header,
            text=f"Zone pre/post correction intensities for {title_name}",
            font=("Helvetica", 10, "bold"),
        ).pack(anchor="w")
        self.zone_intensity_source_label = ttk.Label(
            header, text=source_note, foreground="gray"
        )
        self.zone_intensity_source_label.pack(anchor="w")

        table_frame = ttk.Frame(win, padding=(8, 4, 8, 8))
        table_frame.pack(fill="both", expand=True)

        columns = ("zone", "pre_mean", "pre_med", "post_mean", "post_med", "area")
        self.zone_intensity_tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        self.zone_intensity_tree.heading("zone", text="Zone")
        self.zone_intensity_tree.heading("pre_mean", text="Pre Mean")
        self.zone_intensity_tree.heading("pre_med", text="Pre Median")
        self.zone_intensity_tree.heading("post_mean", text="Post Mean")
        self.zone_intensity_tree.heading("post_med", text="Post Median")
        self.zone_intensity_tree.heading("area", text="Area (px)")
        self.zone_intensity_tree.column("zone", width=160, anchor="w")
        self.zone_intensity_tree.column("pre_mean", width=90, anchor="center")
        self.zone_intensity_tree.column("pre_med", width=90, anchor="center")
        self.zone_intensity_tree.column("post_mean", width=90, anchor="center")
        self.zone_intensity_tree.column("post_med", width=90, anchor="center")
        self.zone_intensity_tree.column("area", width=80, anchor="center")

        yscroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.zone_intensity_tree.yview
        )
        self.zone_intensity_tree.configure(yscrollcommand=yscroll.set)
        self.zone_intensity_tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        footer = ttk.Frame(win, padding=(8, 0, 8, 8))
        footer.pack(fill="x")
        self.zone_intensity_total_label = ttk.Label(footer, text="")
        self.zone_intensity_total_label.pack(anchor="w")

        def on_close():
            self.show_zone_intensity_labels_var.set(False)
            self.zone_intensity_window = None
            win.destroy()
            try:
                self.show_page()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._populate_zone_intensity_tree(df, source_note)

    def _populate_zone_intensity_tree(self, df, source_note=""):
        """Fill the intensity Treeview from a DataFrame."""
        if not hasattr(self, "zone_intensity_tree") or self.zone_intensity_tree is None:
            return
        if not self.zone_intensity_tree.winfo_exists():
            return

        for item in self.zone_intensity_tree.get_children():
            self.zone_intensity_tree.delete(item)

        n = 0
        total_area = 0
        means = []
        for _, row in df.iterrows():
            zone_name = str(row.get("Zone", ""))
            pre_mean = row.get("Pre_Correction_Mean", row.get("Mean_Intensity_Raw", np.nan))
            pre_med = row.get("Pre_Correction_Median", row.get("Median_Intensity_Raw", np.nan))
            post_mean = row.get("Post_Correction_Mean", row.get("Mean_Intensity", np.nan))
            post_med = row.get("Post_Correction_Median", row.get("Median_Intensity", np.nan))
            area_val = row.get("Region_Area", "")

            def _fmt(v):
                if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
                    return "—"
                try:
                    return f"{float(v):.2f}"
                except Exception:
                    return str(v)

            if pd.isna(area_val) or area_val == "" or area_val is None:
                area_display = "—"
            else:
                try:
                    area_display = str(int(area_val))
                    total_area += int(area_val)
                except Exception:
                    area_display = str(area_val)

            try:
                if post_mean is not None and not (
                    isinstance(post_mean, float) and np.isnan(post_mean)
                ):
                    means.append(float(post_mean))
            except Exception:
                pass

            self.zone_intensity_tree.insert(
                "",
                "end",
                values=(
                    zone_name,
                    _fmt(pre_mean),
                    _fmt(pre_med),
                    _fmt(post_mean),
                    _fmt(post_med),
                    area_display,
                ),
            )
            n += 1

        if hasattr(self, "zone_intensity_source_label") and self.zone_intensity_source_label.winfo_exists():
            self.zone_intensity_source_label.config(text=source_note)

        if hasattr(self, "zone_intensity_total_label") and self.zone_intensity_total_label.winfo_exists():
            parts = [f"Regions: {n}"]
            if means:
                parts.append(f"Mean of means: {np.mean(means):.2f}")
            if total_area:
                parts.append(f"Total area: {total_area} px")
            self.zone_intensity_total_label.config(text="  |  ".join(parts))

    def _close_zone_intensity_window(self):
        """Hide the zone intensity table window."""
        if self.zone_intensity_window is not None and self.zone_intensity_window.winfo_exists():
            self.zone_intensity_window.destroy()
        self.zone_intensity_window = None

    def _refresh_zone_intensity_table(self):
        """Refresh the open intensity table when the image/mask changes."""
        if not self.show_zone_intensity_labels_var.get():
            return
        if self.zone_intensity_window is None or not self.zone_intensity_window.winfo_exists():
            return
        df, source_note = self._get_zone_intensities_dataframe()
        if df is not None and not df.empty:
            self._populate_zone_intensity_tree(df, source_note)

    def _remove_paint_pen_menu_item(self):
        """Remove any leftover top-level 'Pen: …' menu entries (legacy Start Paint clutter)."""
        try:
            end = self.menu.index('end')
            if end is None:
                return
            # Delete all matching labels (older builds added one per Start Paint)
            for i in range(end, -1, -1):
                try:
                    if str(self.menu.entrycget(i, 'label')).startswith('Pen:'):
                        self.menu.delete(i)
                except Exception:
                    continue
        except Exception:
            pass

    def _finalize_paint_for_counting(self):
        """Commit active paint into zones without stop_paint side effects (save_state, save_paint, show_page)."""
        if getattr(self, 'current_state', None) != 'paint':
            return

        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>')
        self.output.unbind('<Button-1>')
        self.output.unbind('<Button-3>')
        self.output.bind('<Button-1>', self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self._remove_paint_pen_menu_item()
        self.current_state = None
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self._update_paint_indicator()

        all_current_groups = set()
        for item in (self.output.find_withtag('paint') or []):
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    all_current_groups.add(tag)
        for gtag in list(self.paint_group_data.keys()):
            if gtag.startswith('paintgroup_'):
                all_current_groups.add(gtag)
        for group_tag in all_current_groups:
            if group_tag not in self.named_paint_groups:
                self.named_paint_groups[group_tag] = None

        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()
        self.output.delete('paint')

    def count_cells(self):
        logger.info("Starting cell counting process")
        if self.background_image is None:
            logger.warning("Cell counting failed: No TIFF file imported")
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        # Finalize paint into zones without stop_paint (which runs save_state/save_paint/show_page
        # and can crash or corrupt UI state mid-count).
        self._finalize_paint_for_counting()

        # Ensure zone structures exist for the current page (important for pure Paint workflows)
        if self.current_page not in self.zone_names:
            self.zone_names[self.current_page] = {}
        if self.current_page not in self.mask_images:
            if self.original_background is not None:
                target_size = self.original_background.size
            elif self.background_image is not None:
                target_size = self.background_image.size
            else:
                target_size = (1024, 1024)  # fallback
            self.mask_images[self.current_page] = Image.new('L', target_size, 0)
        if self.current_page not in self.zone_counters:
            self.zone_counters[self.current_page] = 0

        # Always attempt to convert any remaining *named* paint groups into zones.
        # This is the main path for users who named their regions (via right-click or autonaming).
        self._convert_named_paints_to_zones()

        # Fallback for any completely unnamed paint strokes that are still on the canvas
        remaining_paint = self.output.find_withtag('paint')
        if remaining_paint:
            self._force_paint_strokes_to_zones(remaining_paint)
            self.output.delete('paint')

        # Final safety net: if we still have no zones but the user was painting,
        # try one last conversion of any named groups.
        page_zones = self.zone_names.get(self.current_page, {})
        if not page_zones:
            self._convert_named_paints_to_zones()
            page_zones = self.zone_names.get(self.current_page, {})

        # Ultimate hardening (addresses "named immediately after drawing then Count Cells says no regions"):
        # If paint data or named entries still exist (stop may have cleared only after its attempts),
        # force-add any data groups and convert. Combined with broadened collection inside convert
        # and the re-try inside stop_paint, this guarantees named paint groups produce zone entries
        # using durable model_points even across zoom/rebuild/dtag/reset lifecycles.
        if not page_zones:
            for gtag in list(self.paint_group_data.keys()):
                if gtag.startswith('paintgroup_') and gtag not in self.named_paint_groups:
                    self.named_paint_groups[gtag] = self.named_paint_groups.get(gtag)
            if self.named_paint_groups:
                self._convert_named_paints_to_zones()
            page_zones = self.zone_names.get(self.current_page, {})

        if not page_zones:
            messagebox.showerror(
                "No Regions Defined",
                "No regions (zones) have been defined for this page.\n\n"
                "To populate the spreadsheet:\n"
                "• For atlas: Click on regions in the atlas overlay to name them.\n"
                "• For paint: Draw with the Paint tool, right-click strokes to name them (or just draw and let Count Cells auto-assign 'Painted Region N' names), then click Count Cells."
            )
            return

        progress = self._show_busy_dialog("Counting Cells")
        final_cell_mask = None
        df = None
        try:
            progress.set_progress(10, "Preparing data...")

            # === Build Final Cell Mask ===
            if self.original_background is None:
                if self.background_image is not None:
                    self.original_background = self.background_image.copy()
                else:
                    messagebox.showerror("Error", "No original background image available for cell detection.")
                    return
            background = self.original_background.convert('L')
            base_size = background.size
            bh, bw = np.array(background).shape[:2]

            use_locked = (
                getattr(self, "cell_mask_locked", False)
                and getattr(self, "auto_mask", None) is not None
                and not isinstance(self.auto_mask, bool)
            )
            if use_locked:
                progress.set_progress(25, "Using loaded / locked cell mask...")
                auto_mask = np.asarray(self.auto_mask, dtype=bool).squeeze()
                if auto_mask.ndim != 2:
                    raise ValueError(f"Loaded cell mask must be 2D, got shape {auto_mask.shape}")
                if auto_mask.shape[0] != bh or auto_mask.shape[1] != bw:
                    auto_mask = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(auto_mask), (bh, bw)
                    )
                    self.auto_mask = auto_mask
                logger.info("Count Cells: using locked/loaded cell mask (no re-detection)")
            else:
                progress.set_progress(25, "Running cell detection...")
                _, auto_labels = binary_mask_cell_count(
                    background, processor=self.image_processor
                )
                auto_mask = np.asarray(auto_labels, dtype=bool).squeeze()
                if auto_mask.ndim != 2:
                    raise ValueError(f"Cell detection mask must be 2D, got shape {auto_mask.shape}")
                self.auto_mask = auto_mask
                self.cell_mask_locked = False

            progress.set_progress(45, "Processing manual edits...")
            add_mask = np.zeros(auto_mask.shape, dtype=bool)
            remove_mask = np.zeros(auto_mask.shape, dtype=bool)

            if self.manual_add_mask is not None:
                add_mask_arr = np.array(self.manual_add_mask.resize(base_size, Image.NEAREST))
                if add_mask_arr.ndim > 2:
                    add_mask_arr = add_mask_arr.squeeze()
                add_mask = add_mask_arr > 0

            if self.manual_remove_mask is not None:
                remove_mask_arr = np.array(self.manual_remove_mask.resize(base_size, Image.NEAREST))
                if remove_mask_arr.ndim > 2:
                    remove_mask_arr = remove_mask_arr.squeeze()
                remove_mask = remove_mask_arr > 0

            if add_mask.shape != auto_mask.shape:
                add_mask = np.array(
                    Image.fromarray(add_mask.astype(np.uint8) * 255).resize(
                        (auto_mask.shape[1], auto_mask.shape[0]), Image.NEAREST
                    )
                ) > 0
            if remove_mask.shape != auto_mask.shape:
                remove_mask = np.array(
                    Image.fromarray(remove_mask.astype(np.uint8) * 255).resize(
                        (auto_mask.shape[1], auto_mask.shape[0]), Image.NEAREST
                    )
                ) > 0

            final_cell_mask = (auto_mask | add_mask) & ~remove_mask
            self.last_cell_mask = final_cell_mask
            cell_mask_pil = Image.fromarray((final_cell_mask * 255).astype(np.uint8))

            region_mask_pil = self.mask_images[self.current_page]
            # img_x/img_y are model-space offsets (native image pixels)
            model_img_x = float(self.img_x) if self.img_x is not None else 0.0
            model_img_y = float(self.img_y) if self.img_y is not None else 0.0

            progress.set_progress(65, "Counting cells per region...")

            annotated, df, counts = count_cells_in_zones(
                self.original_background,
                region_mask_pil,
                cell_mask_pil,
                model_img_x,
                model_img_y,
                self.zone_counters,
                self.zone_names.get(self.current_page, {}),
            )

            self.background_image = annotated
            self._invalidate_bg_display_cache()
            self.last_df = df

            progress.set_progress(85, "Generating annotated image...")
            self.show_page()
            self._refresh_zone_counts_table()

            if progress and not getattr(progress, 'closed', False):
                progress.set_progress(100, "Done")
                progress.close()
                progress = None

            base_name = self.tiff_filename
            tiff_dir = self.tiff_dir
            # Count Cells exports go under <image_dir>/output/counts/
            out_dir = self._get_output_directory(tiff_dir, feature="counts") if tiff_dir else None
            paint_out = self._get_output_directory(tiff_dir, feature="paint") if tiff_dir else None

            saved_paths = []  # for summary dialog
            masked_path = None
            counts_path = None
            paint_path = None

            if out_dir and base_name and self.original_background is not None and final_cell_mask is not None:
                try:
                    orig = self.original_background.convert('RGBA')
                    # Donut rings (open centers) so underlying signal is visible in the export
                    ring_overlay = self._cell_detection_ring_overlay(
                        final_cell_mask,
                        size=orig.size,
                        color=(255, 0, 0),
                        alpha=200,
                        thickness=2,
                    )
                    masked_img = Image.alpha_composite(orig, ring_overlay)
                    masked_path = os.path.join(out_dir, f"{base_name}_masked.tif")
                    # Avoid tiff_deflate — it segfaults some Pillow/libtiff builds on Windows.
                    masked_img.save(masked_path)
                    saved_paths.append(f"Mask: {masked_path}")
                    logger.info(f"Masked image saved (ring outlines): {masked_path}")
                except Exception as e:
                    logger.error(f"Failed to save _masked.tif: {e}")

            excel_saved = False
            if out_dir and base_name and df is not None:
                xlsx_path = os.path.join(out_dir, f"{base_name}.xlsx")
                for engine in ['openpyxl', 'xlsxwriter']:
                    try:
                        with pd.ExcelWriter(xlsx_path, engine=engine) as writer:
                            df.to_excel(writer, sheet_name="Cell Counts", index=False)
                            meta_data = []
                            cfg = self.image_processor.cell_config
                            pcfg = self.image_processor.preprocess_config
                            for k, v in cfg.__dict__.items():
                                meta_data.append({"Category": "Cell Detection", "Parameter": k, "Value": str(v)})
                            for k, v in pcfg.__dict__.items():
                                meta_data.append({"Category": "Preprocessing", "Parameter": k, "Value": str(v)})
                            meta_df = pd.DataFrame(meta_data)
                            meta_df.to_excel(writer, sheet_name="Detection Parameters", index=False)
                        counts_path = xlsx_path
                        saved_paths.append(f"Counts: {xlsx_path}")
                        excel_saved = True
                        break
                    except Exception:
                        continue

                if not excel_saved:
                    try:
                        csv_path = os.path.join(out_dir, f"{base_name}.csv")
                        df.to_csv(csv_path, index=False)
                        counts_path = csv_path
                        saved_paths.append(f"Counts (CSV): {csv_path}")
                        messagebox.showwarning(
                            "Excel Export Failed",
                            f"Could not save as Excel (openpyxl or xlsxwriter not installed).\n"
                            f"Fell back to CSV:\n{csv_path}\n\n"
                            f"To enable .xlsx output with metadata sheet, run:\n"
                            f"pip install openpyxl xlsxwriter"
                        )
                    except Exception as e:
                        logger.error(f"CSV fallback also failed: {e}")

            # Per-cell measurements: centroid x,y and pixel area for every detected cell
            cells_csv_path = None
            if out_dir and base_name and final_cell_mask is not None:
                try:
                    cells_csv_path = self._export_cell_centroids_csv(
                        final_cell_mask, out_dir, base_name
                    )
                    if cells_csv_path:
                        saved_paths.append(f"Cell centroids: {cells_csv_path}")
                except Exception as e:
                    logger.error(f"Failed to save cell centroids CSV: {e}")

            # Always auto-save paint layer into output/paint/ when counting
            if paint_out and base_name:
                try:
                    paint_path = self._save_paint_layer_to_dir(
                        paint_out, base_name, unique=False, show_messages=False
                    )
                    if paint_path:
                        saved_paths.append(f"Paint: {paint_path}")
                except Exception as e:
                    logger.error(f"Failed to auto-save paint layer on count: {e}")

            # Metadata file: full mask/detection parameters for reproducibility
            if out_dir and base_name:
                try:
                    meta_path = self._save_mask_metadata_file(
                        out_dir,
                        base_name,
                        extra={
                            "counts_file": counts_path,
                            "masked_image": masked_path,
                            "paint_file": paint_path,
                            "cell_centroids_file": cells_csv_path,
                            "output_directory": out_dir,
                        },
                    )
                    if meta_path:
                        saved_paths.append(f"Metadata: {meta_path}")
                except Exception as e:
                    logger.error(f"Failed to save mask metadata on count: {e}")

            if out_dir and saved_paths:
                summary = (
                    "Results saved by feature under output/:\n"
                    f"  counts → {out_dir}\n"
                )
                if paint_out:
                    summary += f"  paint  → {paint_out}\n"
                summary += "\n" + "\n".join(saved_paths)
                messagebox.showinfo("Results Saved", summary)
            elif not tiff_dir or not base_name:
                logger.warning("Skipping auto-save of count results (missing tiff_dir or base_name)")
                try:
                    messagebox.showinfo(
                        "Count Complete",
                        "Cells counted. No working TIFF directory was set, so outputs were not auto-saved.",
                    )
                except Exception:
                    pass
            elif not out_dir:
                logger.warning("Could not create output/ directory for count exports")
                try:
                    messagebox.showwarning(
                        "Count Complete",
                        "Cells counted, but the output folder could not be created. Results were not saved to disk.",
                    )
                except Exception:
                    pass

            if hasattr(self, 'tiff_tree') and self.current_tiff_directory:
                self.master.after(300, self.refresh_tiff_file_list)

        except Exception as e:
            logger.error(f"Cell counting failed: {e}", exc_info=True)
            messagebox.showerror("Count Failed", f"Cell counting failed:\n{e}")
        finally:
            if progress and not getattr(progress, 'closed', False):
                progress.close()

    def show_cell_mask_threshold(self, event=None, calculate=True):
        """Display the combined (auto + manual) mask overlay.

        calculate=True runs detection and unlocks a previously loaded mask.
        calculate=False reuses auto_mask (including loaded/locked masks).
        """
        progress = None
        if self.original_background is None:
            messagebox.showwarning("Show Mask", "Load a TIFF image first.")
            return

        # Explicit re-detect unlocks any loaded mask from another channel
        if calculate:
            self.cell_mask_locked = False
            self.cell_mask_source_path = None
            progress = self._show_busy_dialog("Detecting Cells")
            progress.set_progress(5, "Preparing image...")

        background = self.original_background.convert('L')

        # Run automatic detection
        if calculate:
            progress.set_progress(15, "Running cell detection...")
            _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
            auto_mask = auto_labels > 0
            self.auto_mask = auto_mask
            progress.set_progress(55, "Building mask visualization...")
        else:
            auto_mask = self.auto_mask
            if auto_mask is None or isinstance(auto_mask, bool):
                # Fallback: auto_mask not properly initialized (e.g. after reset or zoom state issue)
                progress2 = None
                if progress is None:
                    progress2 = self._show_busy_dialog("Detecting Cells")
                    progress2.set_progress(5, "Preparing image...")
                _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
                auto_mask = auto_labels > 0
                self.auto_mask = auto_mask
                self.cell_mask_locked = False
                if progress2:
                    progress2.set_progress(55, "Building mask visualization...")
                    progress2.close()
            else:
                # Ensure size matches current image (cross-channel load / resize)
                bh, bw = np.array(background).shape[:2]
                auto_mask = np.asarray(auto_mask, dtype=bool).squeeze()
                if auto_mask.shape[0] != bh or auto_mask.shape[1] != bw:
                    auto_mask = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(auto_mask), (bh, bw)
                    )
                    self.auto_mask = auto_mask

        base_size = background.size
        add_mask = np.zeros(auto_mask.shape, dtype=bool)
        remove_mask = np.zeros(auto_mask.shape, dtype=bool)

        # Load manual add/remove masks if present
        if self.manual_add_mask is not None:
            add_mask_arr = np.array(self.manual_add_mask) #.resize(base_size, Image.NEAREST))
            add_mask = add_mask_arr > 0
        if self.manual_remove_mask is not None:
            remove_mask_arr = np.array(self.manual_remove_mask) #.resize(base_size, Image.NEAREST))
            remove_mask = remove_mask_arr > 0

        # Combine automatic and manual edits
        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(70, "Combining manual edits...")
        combined_mask = (auto_mask | add_mask) & ~remove_mask

        # Visualize as open red "donut" rings (boundary only) so fluorescence under each blob stays visible
        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(85, "Generating ring visualization...")
        target_size = self.original_background.size  # (w, h)
        mask_img = self._cell_detection_ring_overlay(
            combined_mask,
            size=target_size,
            color=(255, 0, 0),
            alpha=230,
            thickness=2,
        )
        # Composite cyan random null distribution if present
        rand = getattr(self, "random_cell_mask", None)
        if rand is not None:
            try:
                rmask = np.asarray(rand, dtype=bool).squeeze()
                cyan = self._cell_detection_ring_overlay(
                    rmask,
                    size=target_size,
                    color=(0, 220, 255),
                    alpha=220,
                    thickness=2,
                )
                mask_img = Image.alpha_composite(
                    mask_img.convert("RGBA"), cyan.convert("RGBA")
                )
            except Exception as e:
                logger.debug(f"Random mask overlay skipped: {e}")

        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(95, "Displaying mask...")
        self.show_page(mask=mask_img)

        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(100, "Done")
            progress.close()

        self.showing_auto_mask = True

    
    def next_image_experimental(self):  # unused
        self.root.destroy()
        PDFViewer()

    # ------------------------------------------------------------------
    # File Browser navigation (Phase A)
    # ------------------------------------------------------------------

    def _nav_previous_image_event(self, event=None):
        self.previous_image()
        return "break"

    def _nav_next_image_event(self, event=None):
        self.next_image()
        return "break"

    def _nav_next_uncounted_event(self, event=None):
        self.next_uncounted_image()
        return "break"

    def _current_list_index(self):
        """Index of the currently open TIFF in tiff_file_list, or -1 if unknown."""
        if not getattr(self, "tiff_file_list", None):
            return -1
        path = getattr(self, "current_tiff_path", None)
        if not path:
            return -1
        target = self._norm_path(path)
        for i, p in enumerate(self.tiff_file_list):
            if self._norm_path(p) == target:
                return i
        return -1

    def _autosave_before_image_switch(self):
        """Autosave flattened + counts + paint into feature output subfolders before leaving."""
        did_autosave = False
        if not (getattr(self, "original_background", None) or getattr(self, "background_image", None)):
            return did_autosave
        try:
            flat_dir = self._get_output_directory(self.tiff_dir, feature="flattened") if self.tiff_dir else None
            counts_dir = self._get_output_directory(self.tiff_dir, feature="counts") if self.tiff_dir else None
            paint_dir = self._get_output_directory(self.tiff_dir, feature="paint") if self.tiff_dir else None
            if self.tiff_dir and self.tiff_filename and flat_dir:
                image_path = os.path.join(flat_dir, f"{self.tiff_filename}_flattened.tif")
                self.autosave_flattened_image(image_path)
                did_autosave = True
            if self.last_df is not None and self.tiff_dir and self.tiff_filename and counts_dir:
                csv_path = os.path.join(counts_dir, f"{self.tiff_filename}_counts.csv")
                self.last_df.to_csv(csv_path, index=False)
                did_autosave = True
            # Also refresh paint export into output/paint/ if paint exists
            if paint_dir and self.tiff_filename:
                try:
                    self._save_paint_layer_to_dir(
                        paint_dir, self.tiff_filename, unique=False, show_messages=False
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Autosave before image switch failed: {e}")
        return did_autosave

    def _load_list_image_at(self, index, announce=False):
        """Load tiff_file_list[index] after optional autosave of current work."""
        if not self.tiff_file_list:
            messagebox.showinfo(
                "No Images",
                "No TIFF images in the File Browser folder.\nUse Select Folder first.",
            )
            return False
        if index < 0 or index >= len(self.tiff_file_list):
            return False
        target = self.tiff_file_list[index]
        # Skip reload if already open
        if getattr(self, "current_tiff_path", None) and self._norm_path(self.current_tiff_path) == self._norm_path(target):
            return True
        self._autosave_before_image_switch()
        # Refresh so status of the image we left (e.g. new _counts.csv) appears immediately
        if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            try:
                self.refresh_tiff_file_list()
            except Exception:
                pass
        self._load_tiff_file(target)
        if announce:
            logger.info(f"Navigated to image {index + 1}/{len(self.tiff_file_list)}: {target}")
        return True

    def previous_image(self):
        """Load the previous source TIFF in the File Browser list (Ctrl+Left)."""
        if not self.tiff_file_list:
            if self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if not self.tiff_file_list:
                messagebox.showinfo(
                    "Previous Image",
                    "No TIFF images available. Select a folder in the File Browser first.",
                )
                return
        idx = self._current_list_index()
        if idx < 0:
            # Nothing open yet — load first
            self._load_list_image_at(0)
            return
        if idx <= 0:
            messagebox.showinfo("Previous Image", "Already at the first image in this folder.")
            return
        self._load_list_image_at(idx - 1)

    def next_image(self):
        """Load the next source TIFF in the File Browser list (Ctrl+Right).

        Autosaves flattened/counts for the current image when leaving it.
        """
        if not self.tiff_file_list:
            if self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if not self.tiff_file_list:
                messagebox.showinfo(
                    "Next Image",
                    "No TIFF images available. Select a folder in the File Browser first.",
                )
                return
        idx = self._current_list_index()
        if idx < 0:
            self._load_list_image_at(0)
            return
        if idx >= len(self.tiff_file_list) - 1:
            messagebox.showinfo("Next Image", "Already at the last image in this folder.")
            return
        self._load_list_image_at(idx + 1)

    def next_uncounted_image(self):
        """Load the next source TIFF that does not yet have count results (Ctrl+Shift+Right)."""
        if not self.tiff_file_list:
            if self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if not self.tiff_file_list:
                messagebox.showinfo(
                    "Next Uncounted",
                    "No TIFF images available. Select a folder in the File Browser first.",
                )
                return

        start = self._current_list_index()
        # Search after current (or from beginning if none open)
        search_from = start + 1 if start >= 0 else 0
        for i in range(search_from, len(self.tiff_file_list)):
            if not self._get_image_work_status(self.tiff_file_list[i]).get("counted", False):
                self._load_list_image_at(i)
                return

        messagebox.showinfo(
            "Next Uncounted",
            "No remaining uncounted images after the current one in this folder.\n"
            f"Progress is shown in the File Browser summary.",
        )

    def clear_canvas_session(self):
        """Clear all loaded images, paint, zones, and overlays while keeping the
        File Browser folder list. Formerly the behavior of Next Image before Phase A.
        Autosaves flattened/counts when possible.
        """
        logger.info("Clear canvas session / reset for new image")

        did_autosave = self._autosave_before_image_switch()

        # Preserve directory and browser widgets
        saved_current_dir = getattr(self, "current_tiff_directory", None)
        saved_tree = getattr(self, "tiff_tree", None)
        saved_iid_map = getattr(self, "_tree_iid_to_path", None)
        saved_path_map = getattr(self, "_tree_path_to_iid", None)
        saved_file_list = getattr(self, "tiff_file_list", None)
        saved_folder_label = getattr(self, "folder_label", None)

        clear_preprocess_cache()

        # Full reset of loaded content and analysis state
        self.doc = None
        self.path = None
        self.atlas_filetype = None
        self.allen_nissl_reference = None
        self.allen_nissl_photo = None
        self.allen_zone_meta = {}
        self.current_page = 0
        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.selected_zone_id = None
        self.selected_page = None
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        self.crop_mode = False
        if hasattr(self, "crop_mode_var"):
            self.crop_mode_var.set(False)
        self.edit_mode = False
        if hasattr(self, "edit_mode_var"):
            self.edit_mode_var.set(False)

        self.named_paint_groups = {}
        self.paint_group_data = {}
        self.painted_zone_outlines = {}
        self.current_paint_group = None
        self.paint_layer = None
        self.img = None
        self.background_image = None
        self.original_background = None
        self.bg_photo_id = None
        self._invalidate_bg_display_cache()
        self.last_df = None
        self.last_cell_mask = None
        self.img_x = 0
        self.img_y = 0
        self.view_scale = 1.0
        self.zoom = 1.0
        self.brightness = 0.0
        self.current_state = None
        self.current_tiff_path = None

        self.manual_add_mask = None
        self.manual_remove_mask = None
        self.editing_mask = False
        self.mask_edit_add = True
        self.mask_photo = False
        self.mask_photo_id = False
        self.current_mask = None
        self.auto_mask = None
        self.showing_auto_mask = False

        try:
            self.state_manager.undo_stack.clear()
        except Exception:
            self.state_manager.undo_stack = []

        if saved_current_dir:
            self.current_tiff_directory = saved_current_dir
        if saved_tree is not None:
            self.tiff_tree = saved_tree
        if saved_iid_map is not None:
            self._tree_iid_to_path = saved_iid_map
        if saved_path_map is not None:
            self._tree_path_to_iid = saved_path_map
        if saved_file_list is not None:
            self.tiff_file_list = saved_file_list
        if saved_folder_label is not None:
            self.folder_label = saved_folder_label

        if hasattr(self, "output"):
            try:
                self.output.delete("all")
            except Exception:
                pass

        try:
            self.show_page()
            if hasattr(self, "_update_ribbon_selection"):
                self._update_ribbon_selection()
            if hasattr(self, "refresh_tiff_file_list") and self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if hasattr(self, "current_file_var"):
                self.current_file_var.set("")
        except Exception as e:
            logger.warning(f"Error during clear_canvas_session UI reset: {e}")

        if did_autosave:
            messagebox.showinfo(
                "Clear Canvas",
                "Current image cleared. File Browser folder is preserved.\n"
                "Previous flattened/counts were auto-saved where possible.",
            )
        else:
            messagebox.showinfo(
                "Clear Canvas",
                "App state cleared. Ready to load a new image from the File Browser.",
            )

def count_cells_in_zones(background_pil, mask_pil, page_pil, img_x, img_y, zone_counters, zone_names):
    """Enhanced cell counting with improved visualization"""
    logger.info("Starting cell counting in zones")
    
    # Convert background to grayscale if it's not already
    background_array = np.array(background_pil)
    if background_array.ndim == 3:
        background_gray = np.dot(background_array[..., :3], [0.2989, 0.5870, 0.1140])
    else:
        background_gray = background_array
        
    # Normalize to float [0, 1]
    background_norm = (background_gray - background_gray.min()) / (background_gray.max() - background_gray.min() + 1e-8)
    
    img2d = background_norm

    if page_pil is not None:
        # Caller already ran detection and merged manual edits — avoid a second
        # detect + watershed pass (crashes/OOM on large microscopy frames).
        binary = np.asarray(page_pil)
        if binary.ndim > 2:
            binary = binary.squeeze()
        binary = binary > 0
        labels = measure.label(binary)
        props = measure.regionprops(labels)
    else:
        # Legacy path when no precomputed mask is supplied.
        _, binary = binary_mask_cell_count(Image.fromarray((background_norm * 255).astype(np.uint8)))
        binary = np.asarray(binary, dtype=bool)

        logger.debug("Performing distance transform for watershed")
        distance = distance_transform_edt(binary)

        try:
            coords = feature.peak_local_max(distance, min_distance=5, exclude_border=True)
        except TypeError:
            coords = feature.peak_local_max(distance, min_distance=5)
        if isinstance(coords, tuple):
            coords = np.column_stack(coords)
        markers = np.zeros(distance.shape, dtype=bool)
        if getattr(coords, 'size', 0):
            markers[tuple(coords.T)] = True
        markers = measure.label(markers)

        if markers.max() == 0:
            labels = measure.label(binary)
        else:
            labels = segmentation.watershed(-distance, markers, mask=binary)
        props = measure.regionprops(labels)

    # Initialize counts for all known zones on this page (from zone_names).
    # This ensures the output spreadsheet lists every named/painted region (with 0 if no cells found).
    # Also seed from any ids present in the mask (for orphan labels).
    counts = {int(zid): 0 for zid in (zone_names or {}).keys()}
    try:
        m0 = np.array(mask_pil)
        for z in np.unique(m0):
            if z > 0:
                counts.setdefault(int(z), 0)
    except Exception:
        pass
    filtered_props = []

    # Filter props based on mask and count per zone.
    # Use a small neighborhood search around each centroid. This tolerates:
    # - cells whose centroid lands exactly on a boundary stroke pixel
    # - tiny gaps or imperfections left by even the improved flood/hole-fill
    mask_arr = np.array(mask_pil)
    mask_h, mask_w = mask_arr.shape
    # Determine whether the zone mask is in the same coordinate system as the cell detection / background.
    # - Paint regions (and standalone TIFF) live in the main background image space (offset 0).
    # - Atlas zones may come from a differently-sized/positioned overlay layer (use img_x/y for translation).
    bg_w, bg_h = background_pil.size  # PIL (width, height)
    use_offset = not (abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5)

    for prop in props:
        row, col = prop.centroid
        if use_offset:
            ax = int(col - img_x)
            ay = int(row - img_y)
        else:
            ax = int(col)
            ay = int(row)

        found_zone = 0
        # Check exact point first, then a 5x5 neighborhood (good balance of tolerance vs. accuracy)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                qx = ax + dx
                qy = ay + dy
                if 0 <= qx < mask_w and 0 <= qy < mask_h:
                    val = mask_arr[qy, qx]
                    if val > 0:
                        found_zone = int(val)
                        break
            if found_zone:
                break

        if found_zone > 0:
            counts.setdefault(found_zone, 0)
            counts[found_zone] += 1
            filtered_props.append(prop)

    # Enhanced visualization (wrapped so errors here don't lose the counts/df)
    try:
        bg_min = img2d.min()
        bg_max = img2d.max()
        norm = (img2d - bg_min) / (bg_max - bg_min) if bg_max > bg_min else np.zeros_like(img2d)
        img_uint8 = (norm * 255).astype('uint8')
        img_rgb = np.stack([img_uint8]*3, axis=-1)
        annotated = Image.fromarray(img_rgb)
        draw = ImageDraw.Draw(annotated, 'RGBA')

        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        # Add cell annotations with improved visibility
        for i, prop in enumerate(filtered_props, start=1):
            r, c = prop.centroid
            draw.ellipse([int(c)-3, int(r)-3, int(c)+3, int(r)+3], outline=(255,0,0,200))
            draw.text((int(c)+4, int(r)-6), str(i), fill=(255,0,0,200), font=font)

        annotated = annotated.convert('RGBA')

        # Create visualization
        # Convert the original image to RGB for annotation
        if background_array.ndim == 2:
            rgb_img = np.stack([background_array] * 3, axis=-1)
        else:
            rgb_img = background_array[..., :3].copy()

        # Draw detected cells
        for i, prop in enumerate(filtered_props, start=1):
            y, x = prop.centroid  # y is row, x is column
            y, x = int(y), int(x)
            
            # Draw a small cross marker for each cell
            marker_size = 3
            
            # Draw vertical line
            y_start = max(0, y - marker_size)
            y_end = min(rgb_img.shape[0] - 1, y + marker_size + 1)
            x_pos = min(max(0, x), rgb_img.shape[1] - 1)
            if y_start < y_end:
                rgb_img[y_start:y_end, x_pos, :] = [255, 0, 0]
            
            # Draw horizontal line
            x_start = max(0, x - marker_size)
            x_end = min(rgb_img.shape[1] - 1, x + marker_size + 1)
            y_pos = min(max(0, y), rgb_img.shape[0] - 1)
            if x_start < x_end:
                rgb_img[y_pos, x_start:x_end, :] = [255, 0, 0]

        # Convert to PIL Image
        annotated = Image.fromarray(rgb_img.astype(np.uint8))
    except Exception:
        # Fallback: just use a copy of the background as annotated if viz fails
        if background_array.ndim == 2:
            rgb_img = np.stack([background_array] * 3, axis=-1)
        else:
            rgb_img = background_array[..., :3].copy()
        annotated = Image.fromarray(rgb_img.astype(np.uint8))

    # Region areas (total pixels of each zone in the zone mask)
    zone_areas = {}
    try:
        for zid in counts.keys():
            zone_areas[int(zid)] = int(np.sum(mask_arr == int(zid)))
    except Exception:
        for zid in counts.keys():
            zone_areas[int(zid)] = 0

    # Prepare results DataFrame: cells counted + total region area (pixels)
    zone_list, count_list, area_list = [], [], []
    for zid in sorted(counts.keys()):
        zid = int(zid)
        name = zone_names.get(zid, f"Zone {zid}")
        zone_list.append(name)
        count_list.append(counts[zid])
        area_list.append(zone_areas.get(zid, 0))
    df = pd.DataFrame({
        'Zone': zone_list,
        'Cell_Count': count_list,
        'Region_Area': area_list,
    })
    
    return annotated, df, counts

class StateManager:
    """Manages undo history for user actions (paint, atlas edits, mask edits, region transforms, etc.).

    Snapshots are taken *before* mutating actions (via viewer.save_state() calls at the
    start of user-initiated edit paths). Supports repeated undo.
    """

    MAX_HISTORY = 40

    def __init__(self):
        self.undo_stack = []

    def _copy_image(self, img):
        """Safely copy a PIL Image or return None."""
        if img is None:
            return None
        try:
            return img.copy()
        except Exception:
            return None

    def _copy_image_dict(self, d):
        """Deep copy a dict of page_id -> PIL.Image (or None)."""
        if not d:
            return {}
        out = {}
        for k, v in d.items():
            out[k] = self._copy_image(v)
        return out

    def save_state(self, viewer):
        """Capture a snapshot of all user-editable state before a mutation."""
        try:
            state = {
                # View / placement
                "current_page": viewer.current_page,
                "img_x": viewer.img_x,
                "img_y": viewer.img_y,
                "view_scale": getattr(viewer, 'view_scale', 1.0),
                "zoom": getattr(viewer, 'zoom', 1.0),

                # Core editable data
                "zone_counters": copy.deepcopy(getattr(viewer, 'zone_counters', {})),
                "zone_names": copy.deepcopy(getattr(viewer, 'zone_names', {})),
                "mask_images": self._copy_image_dict(getattr(viewer, 'mask_images', {})),
                "base_page_images": self._copy_image_dict(getattr(viewer, 'base_page_images', {})),
                "page_images": self._copy_image_dict(getattr(viewer, 'page_images', {})),

                # Paint system (critical for repeated undo of drawing/naming)
                "paint_group_data": copy.deepcopy(getattr(viewer, 'paint_group_data', {})),
                "named_paint_groups": copy.deepcopy(getattr(viewer, 'named_paint_groups', {})),
                "_paint_group_counter": getattr(viewer, '_paint_group_counter', 0),
                "paint_layer": self._copy_image(getattr(viewer, 'paint_layer', None)),
                "painted_zone_outlines": copy.deepcopy(getattr(viewer, 'painted_zone_outlines', {})),

                # Manual cell edits
                "manual_add_mask": self._copy_image(getattr(viewer, 'manual_add_mask', None)),
                "manual_remove_mask": self._copy_image(getattr(viewer, 'manual_remove_mask', None)),

                # Last count results (so visual + any derived state can be consistent)
                "last_df": copy.deepcopy(getattr(viewer, 'last_df', None)),
            }

            # Bounded history: drop oldest when full
            if len(self.undo_stack) >= self.MAX_HISTORY:
                self.undo_stack.pop(0)

            self.undo_stack.append(state)
            logger.debug(f"Saved state to undo stack (depth={len(self.undo_stack)})")
        except Exception as e:
            logger.warning(f"Failed to save undo state: {e}")

    def undo(self, viewer):
        """Restore the previous snapshot and refresh the display."""
        if not self.undo_stack:
            logger.debug("No states to undo")
            return False

        try:
            state = self.undo_stack.pop()

            # Restore scalars / view
            viewer.current_page = state.get("current_page", 0)
            viewer.img_x = state.get("img_x", 0)
            viewer.img_y = state.get("img_y", 0)
            if hasattr(viewer, 'view_scale'):
                viewer.view_scale = state.get("view_scale", 1.0)
            if hasattr(viewer, 'zoom'):
                viewer.zoom = state.get("zoom", 1.0)

            # Restore data structures
            viewer.zone_counters = state.get("zone_counters", {})
            zn = state.get("zone_names", {})
            if zn:
                viewer.zone_names = {pg: {int(k): v for k, v in (zn.get(pg, {}) or {}).items()} for pg in zn}
            else:
                viewer.zone_names = {}
            viewer.mask_images = state.get("mask_images", {})
            viewer.base_page_images = state.get("base_page_images", {})
            if hasattr(viewer, 'page_images'):
                viewer.page_images = state.get("page_images", {})

            # Prune the restored mask so it only contains zids present in the restored zone_names.
            # This prevents the orphan-discovery logic in _populate_region_list (which scans
            # the mask and auto _ensure_zone_has_name for any zid in the pixels) from
            # immediately re-adding zones that the undo was supposed to remove (common for
            # painted regions whose mask fills were created after the snapshot point).
            # Without this, the banner/list would show "removed" painted regions.
            page = getattr(viewer, 'current_page', 0)
            if page in viewer.mask_images and page in viewer.zone_names:
                try:
                    m = np.array(viewer.mask_images[page])
                    valid_zids = set(viewer.zone_names[page].keys())
                    keep = np.isin(m, list(valid_zids) + [0])
                    if not keep.all():
                        m[~keep] = 0
                        viewer.mask_images[page] = Image.fromarray(m.astype(np.uint8))
                except Exception:
                    pass

            # Clear selection early so the forced ribbon update below shows "No region selected"
            # and the list reflects only the restored names (without the undone painted regions).
            viewer.selected_zone_id = None
            viewer.selected_page = None

            # Force the ribbon banner/list to immediately reflect the restored (pruned) zone_names
            # so removed painted regions disappear from the Atlas Manager even before full show_page.
            if hasattr(viewer, '_update_ribbon_selection'):
                try:
                    viewer._update_ribbon_selection()
                except Exception:
                    pass

            viewer.paint_group_data = state.get("paint_group_data", {})
            viewer.named_paint_groups = state.get("named_paint_groups", {})
            viewer._paint_group_counter = state.get("_paint_group_counter", 0)
            viewer.paint_layer = state.get("paint_layer")
            pzo = state.get("painted_zone_outlines", {})
            viewer.painted_zone_outlines = {int(k): v for k, v in (pzo or {}).items()} if pzo else {}

            # Do NOT force _rebuild_paint_layer_from_data here.
            # The paint_layer snapshot from the historical point already contains
            # exactly the baked strokes up to that moment (including finalized/named
            # ones whose groups were popped from data at naming time).
            # Forcing rebuild from the (possibly empty) restored paint_group_data
            # would blank previous named paints' visuals, causing "one undo removes
            # multiple".
            # Direct restore of the snapshot's paint_layer gives precise per-stroke
            # visual undo.

            viewer.manual_add_mask = state.get("manual_add_mask")
            viewer.manual_remove_mask = state.get("manual_remove_mask")

            if hasattr(viewer, 'last_df'):
                viewer.last_df = state.get("last_df")

            # Clear all transient editing / selection state (edge drag, move-selected, etc.)
            # (already set above, but clear other transients)

            for attr in (
                'edge_grab_active', 'border_drag_active', 'active_edge',
                'current_edited_contour', 'original_full_contour_for_edit',
                'selected_edge_full_contour', '_edge_pending_deselect',
                'region_translate_active', 'region_translate_original_mask',
                'region_translate_zid', 'border_drag_original_mask',
            ):
                if hasattr(viewer, attr):
                    setattr(viewer, attr, None if 'mask' in attr or 'contour' in attr or 'edge' in attr else False)

            # Reset mode checkboxes/vars to neutral (show_page also does some of this)
            for var_name, val in (
                ('region_move_mode', False),
                ('crop_mode_var', False),
                ('edit_mode_var', False),
                ('border_mode_var', False),  # default from init (unchecked; user must select it)
            ):
                var = getattr(viewer, var_name, None)
                if var is not None:
                    try:
                        var.set(val)
                    except Exception:
                        pass

            if hasattr(viewer, 'crop_mode'):
                viewer.crop_mode = False
            if hasattr(viewer, 'edit_mode'):
                viewer.edit_mode = False
            if hasattr(viewer, 'region_translate_active'):
                viewer.region_translate_active = False

            # Reset paint drawing transients so we don't have a dangling current stroke after undo
            viewer.old_x = None
            viewer.old_y = None
            viewer.current_paint_group = None
            viewer.current_state = None

            if hasattr(viewer, '_update_paint_indicator'):
                try:
                    viewer._update_paint_indicator()
                except Exception:
                    pass

            # Redraw everything from the restored data
            viewer.show_page()

            # Keep ribbon in sync if present
            if hasattr(viewer, '_update_ribbon_selection'):
                try:
                    viewer._update_ribbon_selection()
                except Exception:
                    pass

            logger.debug(f"Restored previous state (remaining undo depth={len(self.undo_stack)})")
            return True
        except Exception as e:
            logger.warning(f"Undo failed: {e}")
            # Attempt a safe redraw anyway
            try:
                viewer.show_page()
            except Exception:
                pass
            return False

class PDFHandler:
    def __init__(self):
        self.doc = None
        self.num_pages = 0

    def open_pdf(self, path):
        """Open a PDF file and return document object and page count"""
        logger.debug(f"Opening PDF: {path}")
        self.doc = fitz.open(path)
        self.num_pages = len(self.doc)
        logger.info(f"Loaded PDF with {self.num_pages} pages")
        return self.doc, self.num_pages

    def render_page(self, page_index, zoom):
        """Render a specific page of the PDF at given zoom level"""
        if self.doc is None:
            raise RuntimeError("No PDF opened")
        page = self.doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=True)
        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
        return img

# Initialize global cache for preprocessing
_PREPROCESS_CACHE = {}

def preprocess_for_highlighting(page_id, img, atlas_filetype):
    """Preprocess an image for region highlighting"""
    if page_id in _PREPROCESS_CACHE:
        return _PREPROCESS_CACHE[page_id]
    
    logger.debug(f"Processing image for highlighting: mode={img.mode}, size={img.size}")

    if atlas_filetype == 'pdf':
        img_array = np.array(img)
        # Convert to gray for edge detection
        gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.float32)
        # Edge detection
        mag = filters.sobel(gray)
        # Threshold the gradient magnitude to make a binary edge image
        try:
            thresh = mag.mean() + 0.5 * mag.std()
        except Exception:
            thresh = np.mean(mag)
        mag_binary = mag > thresh

        # Close small gaps in the binary edges
        closed_binary = closing(mag_binary)

        # Make bounds as thin as possible
        skel_binary = morphology.skeletonize(closed_binary)

        barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
        barrier[skel_binary > 0] = 0
        barrier_img = Image.fromarray(barrier.astype('uint8')).convert('L')
        # Cache the result so repeated calls are fast
        _PREPROCESS_CACHE[page_id] = barrier_img
        return barrier_img

    # Convert to RGBA if not already
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    img_array = np.array(img)
    
    # Extract the alpha channel - non-transparent pixels are our barriers
    alpha = img_array[..., 3]

    # Create barrier image: 255 for areas we can flood (transparent), 0 for barriers (non-transparent)
    barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
    barrier[alpha > 0] = 0  # Non-transparent pixels become barriers
    
    barrier_img = Image.new('L', (img.width, img.height))
    barrier_img.putdata(barrier.flatten())
    
    logger.debug(f"Created barrier image with mode={barrier_img.mode}")
    _PREPROCESS_CACHE[page_id] = barrier_img
    
    return barrier_img

def clear_preprocess_cache():
    """Clear the preprocessing cache"""
    _PREPROCESS_CACHE.clear()
    logger.debug("Cleared preprocessing cache")

if __name__ == "__main__":
    _configure_windows_app_identity()
    PDFViewer()
