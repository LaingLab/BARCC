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
        self.root = tk.Tk()
        self.master = self.root
        self.master.title('Regional IF Analyzer')
        self.master.geometry('%dx%d' % (self.master.winfo_screenwidth(), self.master.winfo_screenheight()))
        self.master.resizable(True, True)
        self.master.rowconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=0)
        self.master.columnconfigure(0, weight=1)

        

        # Create simple antibody icon
        icon_img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon_img)
        draw.line((16, 0, 16, 15), fill='white', width=2)  # stem from top
        draw.line((16, 15, 8, 31), fill='white', width=2)  # left arm to bottom
        draw.line((16, 15, 24, 31), fill='white', width=2)  # right arm to bottom
        draw.ellipse((12, 0, 20, 8), fill='lime', outline='green')
        icon = ImageTk.PhotoImage(icon_img)
        self.master.iconphoto(True, icon)

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
        self.crop_rect = None
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
        self.current_mask = None   # reference to the current mask being edited
        self.auto_mask = None
        self.showing_auto_mask = False

        # View zoom (separate from PDF render zoom)
        self.view_scale = 1.0
        self.min_scale = 0.2
        self.max_scale = 8.0

        # Display options
        self.show_zone_labels = False

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

        # TIFF filename
        self.tiff_filename = None
        self.tiff_dir = None

        # File browser
        self.current_tiff_directory = None
        self.tiff_file_list = []   # list of full paths

        # Last DF for counts
        self.last_df = None

        # Brightness
        self.brightness = 0.0

        # Mouse state tracking
        self.current_state = None

        # Init windows (not needed, init windows when spawned)
#       self.brush_win = None

        # Build GUI
        self._build_gui()
        self.init_keybinds()

        self._update_paint_indicator()

        self.root.mainloop()

    def init_keybinds(self):
        # Keyboard shortcuts
        self.master.bind('<q>', self.quit)
        self.master.bind('<Control-z>', self._undo_event)
        self.master.bind('<Control-s>', self.save_flattened_image)
        self.master.bind('<Return>', self._commit_painted_border_refit)
        self.master.bind('<KP_Enter>', self._commit_painted_border_refit)

        # Bind click event for highlighting
        self.output.bind("<Button-1>", self.highlight_region)


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
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_command(label="Next Image", command=self.next_image)
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
        atlasmenu.add_command(label="Import Atlas", command=self.import_atlas)
        atlasmenu.add_separator()
        atlasmenu.add_checkbutton(label="Crop", variable=self.crop_mode_var, command=self.toggle_crop_mode)
        atlasmenu.add_checkbutton(label="Move", variable=self.edit_mode_var, command=self.toggle_edit_mode)
        atlasmenu.add_command(label="Rotate", command=self.show_rotate_settings)
        atlasmenu.add_command(label="Scale", command=self.show_scale_settings)

        # Per-region transforms for individually selected atlas zones (new in this update)
        atlasmenu.add_separator()
        atlasmenu.add_command(label="Select Region", command=self.select_region)
        atlasmenu.add_command(label="Deselect Region", command=self.deselect_region)
        atlasmenu.add_command(label="Rotate Selected Region", command=self.show_rotate_selected_dialog)
        atlasmenu.add_command(label="Scale Selected Region", command=self.show_scale_selected_dialog)
        
        # Create Paint menu dropdown
        paintmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Paint", menu=paintmenu)
            # All paint functions (start, stop, pen, eraser, brushsize)
        paintmenu.add_command(label="Start Paint", command=self.start_paint)
        paintmenu.add_command(label="Stop Paint", command=self.stop_paint)
        paintmenu.add_command(label="Pen", command=self.use_pen)
        paintmenu.add_command(label="Eraser", command=self.use_eraser)
        # Spawn new windows with widgets
        paintmenu.add_command(label="Brushsize", command=self.show_brush_settings)

        paintmenu.add_separator()
        paintmenu.add_command(label="Load Paint", command=self.load_paint)
        paintmenu.add_command(label="Save Paint Layer", command=self.save_paint_layer)
        
        # Create Mask menu dropdown
        maskmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Mask", menu=maskmenu)
        maskmenu.add_command(label="Show Mask", command=self.show_cell_mask_threshold)
        maskmenu.add_command(label="Show Mask Settings", command=self.show_mask_settings)
        maskmenu.add_command(label="Add Cell", command=self.start_add_cells)
        maskmenu.add_command(label="Remove Cell", command=self.start_remove_cells)
        maskmenu.add_command(label="Finish Mask Edit", command=self.stop_mask_edit)

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

        # Create Cell menu dropdown
        cellmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Cell", menu=cellmenu)
        cellmenu.add_command(label="Count Cells", command=self.count_cells)

        def toggle_zone_labels():
            self.show_zone_labels = not self.show_zone_labels
            self.show_page()

        cellmenu.add_checkbutton(label="Show Zone Labels & Counts", 
                                 variable=tk.BooleanVar(value=self.show_zone_labels),
                                 command=toggle_zone_labels)


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
        self.draw_status = self.menu.add_command(label="Pen: "+str(self.draw_type))
        self.menu.update()

        self._update_paint_indicator()

    def stop_paint(self):
        self.save_state()  # Snapshot the state with open paint groups/names before we auto-default, convert, bake and clear
        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>') 
        self.output.unbind('<Button-1>')
        self.output.unbind('<Button-3>')
        self.output.bind('<Button-1>', self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self.menu.delete(8)
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

    def save_paint_layer(self):
        """Auto-save the current committed paint layer (as PNG) into the directory shown in the left File Browser.

        This behaves like the Count Cells auto-export: it saves directly into the working directory
        the user has open in the left manager. After saving, the file list is refreshed.
        """
        # Ensure any active vector paint strokes are committed to the persistent paint_layer
        # (same as what reset() does on mouse up). This makes Save Paint Layer work
        # reliably whether the user has just drawn or already released the mouse.
        paint_items = self.output.find_withtag('paint')
        if paint_items:
            self._commit_canvas_paint_to_layer()
            self.output.delete('paint')

        # Nothing to save?
        layer_check = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
        if layer_check is None:
            logger.debug("No painting to save")
            return

        # === Determine target directory (priority: left File Browser > source image folder) ===
        target_dir = None
        if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            target_dir = self.current_tiff_directory
        elif self.tiff_dir and os.path.isdir(self.tiff_dir):
            target_dir = self.tiff_dir

        # === Determine base filename ===
        base_name = self.tiff_filename or "untitled"

        # === Build full save path with collision avoidance ===
        if target_dir:
            # Auto-save mode: save directly into the left-pane working directory
            page = self.current_page
            has_labeled_regions = bool(
                self.zone_names.get(page, {}) or
                getattr(self, 'painted_zone_outlines', {})
            )

            layer = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
            if layer is None:
                raise Exception("No paint content available to save")

            if has_labeled_regions:
                # New bundled format: single file containing strokes + zones mask + names
                save_path = self._get_unique_paint_bundle_path(target_dir, base_name)
                try:
                    with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        # Visual painted strokes (the black lines)
                        bio = BytesIO()
                        layer.save(bio, format='PNG')
                        zf.writestr('strokes.png', bio.getvalue())

                        # Filled zone mask for the labeled region shapes
                        if page in self.mask_images and self.mask_images[page] is not None:
                            bio2 = BytesIO()
                            self.mask_images[page].save(bio2, format='PNG')
                            zf.writestr('zones.png', bio2.getvalue())

                        # Metadata: names and outlines
                        manifest = {
                            "format_version": 1,
                            "type": "paint_with_regions",
                            "saved_background_size": list(layer.size),
                            "zone_names": self.zone_names.get(page, {}),
                            "painted_zone_outlines": getattr(self, 'painted_zone_outlines', {}),
                        }
                        zf.writestr('manifest.json', json.dumps(manifest, indent=2))

                    messagebox.showinfo("Paint + Regions Saved", f"Paint file with labeled regions saved to:\n{save_path}")
                    logger.info(f"Saved paint bundle with regions to: {save_path}")
                except Exception as e:
                    messagebox.showerror("Save Error", f"Failed to save paint bundle:\n{e}")
                    return
            else:
                # Plain visual paint only (no labeled regions to bundle)
                save_path = self._get_unique_paint_path(target_dir, base_name)
                try:
                    layer.save(save_path)
                    messagebox.showinfo("Paint Saved", f"Paint layer saved to:\n{save_path}")
                    logger.info(f"Auto-saved paint to: {save_path}")
                except Exception as e:
                    messagebox.showerror("Save Error", f"Failed to auto-save paint:\n{e}")
                    return

            # Refresh left file manager so the saved paint (or bundle) appears
            if hasattr(self, 'tiff_tree') and self.current_tiff_directory:
                self.refresh_tiff_file_list()
        else:
            # Fallback: no folder selected in browser → show traditional save dialog
            save_path = fd.asksaveasfilename(
                title="Save Paint Layer",
                defaultextension=".png",
                filetypes=[("PNG files", "*.png")],
                initialfile=f"{base_name}_paint.png"
            )
            if not save_path:
                return
            try:
                layer = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
                if layer is None:
                    raise Exception("No paint content available to save")

                page = self.current_page
                has_labeled_regions = bool(
                    self.zone_names.get(page, {}) or
                    getattr(self, 'painted_zone_outlines', {})
                )

                if has_labeled_regions:
                    # Use bundle format even for manual save
                    # (user can rename extension if they want)
                    bundle_path = save_path
                    if not bundle_path.lower().endswith('.barccpaint'):
                        bundle_path = os.path.splitext(save_path)[0] + '.barccpaint'
                    with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as zf:
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
        """Load a paint layer (.png). Defaults to the current directory shown in the left File Browser."""
        initial_dir = None
        if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            initial_dir = self.current_tiff_directory
        elif self.tiff_dir and os.path.isdir(self.tiff_dir):
            initial_dir = self.tiff_dir

        logger.info("Opening file dialog for paint selection")
        self.save_state()
        path = fd.askopenfilename(
            title="Load Paint",
            initialdir=initial_dir,
            filetypes=[
                ("BARCC Paint + Regions", "*.barccpaint"),
                ("PNG files", "*.png"),
                ("All files", "*.*")
            ]
        )
        if path:
            logger.info(f"Opening paint file: {path}")
            self.path = path
            if path.lower().endswith('.barccpaint'):
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
        This is the recommended entry point from the Paint menu.
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
        """Draw freehand using the pen. Coordinates are converted properly for the current zoom level."""
        self.line_width = self.brush_size.get()
        paint_color = self.color

        # Convert current mouse position to image space (this is the source of truth)
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_image(cx, cy)

        # Start of a new continuous stroke?
        if self.old_x is None and self.old_y is None:
            self.save_state()  # Snapshot before this new stroke so Undo can remove it
            self._paint_group_counter += 1
            self.current_paint_group = f"paintgroup_{self._paint_group_counter}"
            self.old_x = ix
            self.old_y = iy
            return  # nothing to draw on first point

        # We have a previous point in image space
        prev_ix = self.old_x
        prev_iy = self.old_y

        # Convert both points back to canvas space for creating the visual line (correct for current zoom)
        prev_cx, prev_cy = self._image_to_canvas(prev_ix, prev_iy)
        curr_cx, curr_cy = self._image_to_canvas(ix, iy)

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

        # Record durable geometry for this segment so zones survive show_page() / canvas wipes.
        # Store *model/image* coordinates (stable) rather than view-dependent canvas coords.
        if self.current_paint_group:
            if self.current_paint_group not in self.paint_group_data:
                self.paint_group_data[self.current_paint_group] = []
            self.paint_group_data[self.current_paint_group].append({
                'model_points': [prev_ix, prev_iy, ix, iy],
                'width': self.line_width
            })

        # Store the new point in image space for the next segment
        self.old_x = ix
        self.old_y = iy

        # Ensure scrollregion includes the newly drawn paint so scrollbars work properly
        # and painted areas don't get clipped or "disappear" when using scroll.
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
        if self.draw_type == 'drag':
            self.output.unbind('<ButtonRelease-1>')
            self.draw_type = 'segment'
        elif self.draw_type == 'segment':
            self.output.bind('<ButtonRelease-1>', self.reset)
            self.draw_type = 'drag'
            self.reset(event)
        else:
            print('error', file=sys.stderr)
        self.menu.entryconfig(8, label="Pen: "+str(self.draw_type))

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
            # Use durable paint_group_data + spatial hit test in model space.
            ix, iy = self._canvas_to_image(cx, cy)
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
                        points.append((int(mp[j]), int(mp[j+1])))
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
                        ix = int(cx / self.view_scale)
                        iy = int(cy / self.view_scale)
                        points.append((ix, iy))
                    w = self.output.itemcget(line, 'width')
                    try:
                        width = max(width, int(float(w)))
                    except:
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
            # Round caps ONLY at the true start and end of the entire stroke (no "ears" at intermediate vertices)
            if points:
                px, py = points[0]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
                px, py = points[-1]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
            # Draw the full polyline with round joints for smooth thick stroke without per-vertex caps
            draw.line(points, fill=fill, width=width, joint="curve")

    def _rebuild_paint_layer_from_data(self):
        """Force the persistent paint_layer to exactly match the groups currently present
        in self.paint_group_data (the durable source of truth for painted regions).

        This is called after undo restores an older paint_group_data (and possibly an
        older paint_layer snapshot) so that the *visible* baked strokes on the image
        are removed when the corresponding drawn/named region is undone.
        It re-rasterizes only the strokes that are still active in the restored history.
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
                            points.append((int(mp[j]), int(mp[j+1])))
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
        # updates the visible black outline to match the new zone shape).
        page = getattr(self, 'current_page', None)
        if page is not None:
            zone_names_page = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
            for zid, outline in list(getattr(self, 'painted_zone_outlines', {}).items()):
                if zid not in zone_names_page:
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
                radius = max(1, w // 2)
                if points:
                    px, py = points[0]
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=default_color)
                    px, py = points[-1]
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=default_color)
                draw.line(points, fill=default_color, width=w, joint="curve")

        self.paint_layer = fresh

        # Keep self.img in sync for 'img' filetype code paths (load_page_image etc.)
        if hasattr(self, 'img'):
            try:
                self.img = fresh.copy()
            except Exception:
                self.img = fresh

    def _convert_named_paints_to_zones(self):
        """Convert named paint *groups* (connected strokes) into zone entries.

        Each named group (one continuous drawing action) gets a single zone_id,
        so the entire structural boundary is treated as one region for cell counting.
        """
        if not self.named_paint_groups:
            return

        # Ensure we have a valid current_page for pure Paint workflows
        if self.current_page is None:
            self.current_page = 0

        if self.current_page not in self.zone_counters:
            self.zone_counters[self.current_page] = 0
        if self.current_page not in self.zone_names:
            self.zone_names[self.current_page] = {}

        # Determine target size for the zone mask (very defensive)
        target_size = None
        if self.original_background is not None:
            target_size = self.original_background.size
        elif self.background_image is not None:
            target_size = self.background_image.size
        else:
            # Last resort: use current canvas size or a reasonable default
            try:
                target_size = (self.output.winfo_width(), self.output.winfo_height())
            except Exception:
                target_size = (1024, 1024)

        # Get or create the zone mask for this page
        if self.current_page not in self.mask_images or self.mask_images[self.current_page] is None:
            self.mask_images[self.current_page] = Image.new('L', target_size, 0)

        mask_img = self.mask_images[self.current_page].copy()
        draw = ImageDraw.Draw(mask_img)

        for group_tag, name in list(self.named_paint_groups.items()):
            # Collect strokes from durable data first (stable model coords preferred), else live canvas.
            # Broadened collection (data always + canvas always) + relaxed len checks + last-resort
            # any-'paint' for named groups: this guarantees that right-click named regions populate
            # zone_names/mask even if dtag/remove has occurred on vectors, or after rebuild/zoom/delete.
            strokes = []
            # Durable data (model_points win; survives show_page, reset, zoom, vector deletes)
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
            # Live canvas items carrying the exact group tag (may still be present at convert time)
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
            # Last-resort for a still-named group: any remaining 'paint' vectors at all
            # (covers cases where group tag was stripped by prior dtag but geometry must not be lost)
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
                continue

            # One zone id for the entire connected group
            self.zone_counters[self.current_page] += 1
            zone_id = self.zone_counters[self.current_page]

            if name is None or not str(name).strip():
                clean_name = f"Painted Region {zone_id}"
            else:
                clean_name = str(name).strip() or f"Painted Region {zone_id}"

            self.zone_names[self.current_page][zone_id] = clean_name

            # Accumulate model-space points while drawing for floodfill seed later
            # Collect full points for the group to draw as one clean polyline (no per-segment caps/ears)
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
                            ix = int( (cx / self.view_scale) - self.img_x )
                            iy = int( (cy / self.view_scale) - self.img_y )
                        group_model_points.append((ix, iy))
                    group_width = max(group_width, width)
                except Exception as e:
                    logger.error(f"Failed to rasterize segment in group {group_tag}: {e}")

            if len(group_model_points) >= 2:
                # Dedup consecutive
                deduped = [group_model_points[0]]
                for p in group_model_points[1:]:
                    if p != deduped[-1]:
                        deduped.append(p)
                group_model_points = deduped

                if len(group_model_points) >= 2:
                    radius = max(1, group_width // 2)
                    # Caps only at start and end
                    if group_model_points:
                        px, py = group_model_points[0]
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                        px, py = group_model_points[-1]
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                    draw.line(group_model_points, fill=zone_id, width=group_width, joint="curve")

            # Robust interior fill for hand-drawn regions.
            # 1. Try a quick flood from the bbox center (helps with clean drawings).
            # 2. Then use binary_fill_holes on the pixels we have labeled for this zone_id.
            #    This is the key fix: it properly fills enclosed areas even with gaps in the freehand strokes
            #    and works far better than a single-seed flood from the boundary centroid.
            if group_model_points:
                try:
                    minx = min(p[0] for p in group_model_points)
                    maxx = max(p[0] for p in group_model_points)
                    miny = min(p[1] for p in group_model_points)
                    maxy = max(p[1] for p in group_model_points)
                    cx_seed = (minx + maxx) // 2
                    cy_seed = (miny + maxy) // 2
                    for dx, dy in [(0,0), (2,0), (-2,0), (0,2), (0,-2), (5,0), (-5,0), (0,5), (0,-5)]:
                        sx = cx_seed + dx
                        sy = cy_seed + dy
                        if 0 <= sx < mask_img.width and 0 <= sy < mask_img.height:
                            if mask_img.getpixel((sx, sy)) == 0:
                                draw.floodfill((sx, sy), fill=zone_id, thresh=0)
                                break
                except Exception:
                    pass

            # Strong fill using binary hole filling (the real solution for painted structures)
            try:
                m = np.array(mask_img)
                zone_pixels = (m == zone_id)
                if zone_pixels.any():
                    filled = ndi.binary_fill_holes(zone_pixels)
                    # Only write into background (0); never overwrite other zones or existing labels
                    m[(filled) & (m == 0)] = zone_id
                    mask_img = Image.fromarray(m.astype(np.uint8))
                    draw = ImageDraw.Draw(mask_img)
            except Exception as e:
                logger.debug(f"binary_fill_holes for zone {zone_id} skipped: {e}")

            logger.info(f"Converted named paint group '{clean_name}' ({group_tag}) → zone {zone_id}")

            # Store the boundary outline for this painted zone so edge deformation can later
            # refit the visible black drawn boundary to the (possibly edited) mask shape.
            if zone_id not in self.painted_zone_outlines:
                self.painted_zone_outlines[zone_id] = {
                    'points': list(group_model_points),
                    'width': group_width
                }

            # Retire the group immediately after successful conversion so it cannot be re-discovered
            # (prevents the 3-drawn → 6-in-spreadsheet duplication when naming + later Count Cells / Stop Paint both process it)
            self.named_paint_groups.pop(group_tag, None)
            self.paint_group_data.pop(group_tag, None)
            for item_id in self.output.find_withtag(group_tag):
                try:
                    self.output.dtag(item_id, group_tag)
                except Exception:
                    pass

        self.mask_images[self.current_page] = mask_img

    def _force_paint_strokes_to_zones(self, paint_items):
        """
        Last-resort fallback: If the user has painted strokes on the canvas
        but they didn't get turned into zones (e.g. no right-click naming happened),
        convert whatever paint is still present into default "Painted Region" zones
        so that Count Cells produces a useful spreadsheet.
        """
        if not paint_items:
            return

        if self.current_page not in self.zone_counters:
            self.zone_counters[self.current_page] = 0
        if self.current_page not in self.zone_names:
            self.zone_names[self.current_page] = {}

        if self.original_background is not None:
            target_size = self.original_background.size
        elif self.background_image is not None:
            target_size = self.background_image.size
        else:
            return

        if self.current_page not in self.mask_images:
            self.mask_images[self.current_page] = Image.new('L', target_size, 0)

        mask_img = self.mask_images[self.current_page].copy()
        draw = ImageDraw.Draw(mask_img)

        # Group remaining paint items by their group tag if present, otherwise treat all as one group
        # Also pull any durable (post-wipe) groups so force works even without live canvas items.
        # Broadened to ensure unnamed strokes at Count/Stop time also reliably produce zones.
        groups = {}
        for item in paint_items:
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
                groups[gtag] = []  # will use durable coords inside the draw loop below

        for group_tag, items in groups.items():
            self.zone_counters[self.current_page] += 1
            zone_id = self.zone_counters[self.current_page]

            default_name = f"Painted Region {zone_id}"
            self.zone_names[self.current_page][zone_id] = default_name

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

                    # Use the same corrected coordinate mapping as the main convert function
                    points = []
                    for i in range(0, len(coords), 2):
                        cx = coords[i]
                        cy = coords[i + 1]
                        ix = int( (cx / self.view_scale) - self.img_x )
                        iy = int( (cy / self.view_scale) - self.img_y )
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
                                ix = int( (cx / self.view_scale) - self.img_x )
                                iy = int( (cy / self.view_scale) - self.img_y )
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
        brightness_slider = ttk.Scale(window, from_=-100, to=400, orient=tk.HORIZONTAL, command=self.update_brightness)
        brightness_slider.grid(row=0, column=1, padx=5, pady=5)
        brightness_slider.set(0)
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

        # Smart Suggest button (pre-tunes detection settings locally based on image analysis)
        ttk.Button(control_frame, text="Smart Suggest (Pre-tuning smart settings)", 
                   command=self._show_smart_suggest_dialog).grid(row=1, column=4, padx=(15, 5), pady=(6, 2))

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
        self.show_brush_settings()
        self.start_mask_edit(add=True)

    def start_remove_cells(self):
        """Begin drawing to remove cells from the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.show_brush_settings()
        self.start_mask_edit(add=False)

    def start_mask_edit(self, add=True):
        """Enable mask editing mode"""
        self.editing_mask = True
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


    def stop_mask_edit(self, event=None):
        """Exit mask editing mode"""
        if not self.editing_mask:
            return
        self.editing_mask = False
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
    # SMART SUGGEST (Pre-tuning smart settings) - Fully local analysis
    # ==================================================================

    def _analyze_current_detection(self):
        """
        Local analysis of the current image and detection result.
        Returns useful statistics and suggestions for blob parameters.
        Everything runs on the user's machine (pre-tunes smart settings).
        """
        if self.original_background is None:
            return None

        background = np.array(self.original_background.convert('L')).astype(np.float32) / 255.0

        # Get current detection
        try:
            _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
            current_mask = auto_labels > 0
        except Exception as e:
            logger.error(f"Analysis failed during detection: {e}")
            return None

        num_detections = int(np.sum(current_mask))
        total_pixels = background.size
        detection_density = num_detections / total_pixels * 1_000_000  # detections per megapixel

        # Intensity statistics
        detected_intensities = background[current_mask] if num_detections > 0 else np.array([0.0])
        non_detected = background[~current_mask]

        mean_detected = float(np.mean(detected_intensities)) if num_detections > 0 else 0.0
        mean_background = float(np.mean(non_detected)) if len(non_detected) > 0 else 0.0
        contrast = mean_detected - mean_background

        # Rough noise estimate
        noise_estimate = float(np.std(non_detected[:10000])) if len(non_detected) > 10000 else 0.05

        suggestions = []

        cfg = self.image_processor.cell_config

        # === Heuristic recommendations for blob mode ===
        if cfg.detection_method != "blob":
            suggestions.append({
                "param": "detection_method",
                "current": cfg.detection_method,
                "suggested": "blob",
                "reason": "The new Blob detector is significantly better for most immunofluorescence images than the old Watershed method."
            })

        # Too many detections → too sensitive
        if detection_density > 850:
            new_threshold = min(0.95, round(cfg.blob_threshold + 0.04, 3))
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": new_threshold,
                "reason": f"Very high detection density ({detection_density:.0f} per MP). Raising threshold to reduce false positives."
            })

        # Very low threshold with many detections
        if cfg.blob_threshold < 0.07 and num_detections > 400:
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": max(0.08, round(cfg.blob_threshold + 0.05, 3)),
                "reason": "Low threshold + high count usually means lots of noise is being detected."
            })

        # Very small min_sigma picking up noise
        if cfg.blob_min_sigma < 1.8:
            suggestions.append({
                "param": "blob_min_sigma",
                "current": cfg.blob_min_sigma,
                "suggested": max(1.8, round(cfg.blob_min_sigma + 0.6, 1)),
                "reason": "Very small sigma values detect tiny noise specks. Raising it helps focus on real cells."
            })

        # Low min area
        if cfg.blob_min_area < 20 and num_detections > 300:
            suggestions.append({
                "param": "blob_min_area",
                "current": cfg.blob_min_area,
                "suggested": max(22, cfg.blob_min_area + 8),
                "reason": "Small minimum area allows many noise blobs through."
            })

        # Low circularity on noisy data
        if cfg.blob_min_circularity < 0.65:
            suggestions.append({
                "param": "blob_min_circularity",
                "current": cfg.blob_min_circularity,
                "suggested": min(0.78, round(cfg.blob_min_circularity + 0.08, 2)),
                "reason": "Low circularity threshold allows irregular noise to be counted as cells."
            })

        # If contrast is low, suggest slightly more aggressive denoising
        if contrast < 0.12:
            suggestions.append({
                "param": "preprocess_nr_gaussian",
                "current": self.image_processor.preprocess_config.nr_gaussian_sigma,
                "suggested": min(2.0, round(self.image_processor.preprocess_config.nr_gaussian_sigma + 0.4, 1)),
                "reason": "Low contrast between cells and background. A bit more denoising can help."
            })

        return {
            "num_detections": num_detections,
            "detection_density": round(detection_density, 1),
            "contrast": round(contrast, 3),
            "noise_estimate": round(noise_estimate, 4),
            "suggestions": suggestions
        }

    def _show_smart_suggest_dialog(self):
        """Shows suggestions from the local pre-tuning smart settings agent."""
        analysis = self._analyze_current_detection()

        if analysis is None:
            messagebox.showerror("Analysis Failed", "Could not analyze the current image. Please load an image first.")
            return

        suggestions = analysis["suggestions"]

        if not suggestions:
            messagebox.showinfo(
                "Smart Suggest",
                "The current settings look reasonably balanced for this image.\n\n"
                f"Detections: {analysis['num_detections']}  |  Density: {analysis['detection_density']} per MP"
            )
            return

        # Build suggestion dialog
        dialog = Toplevel(self.root)
        dialog.title("Smart Suggest (Pre-tuning smart settings)")
        dialog.geometry("620x480")

        ttk.Label(dialog, text="Pre-tuning analysis (fully local, no data leaves your computer)", font=("Helvetica", 11, "bold")).pack(pady=8)

        info = f"Detections found: {analysis['num_detections']}   |   Density: {analysis['detection_density']} per MP   |   Contrast: {analysis['contrast']}"
        ttk.Label(dialog, text=info).pack(pady=4)

        suggestions_frame = ttk.Frame(dialog)
        suggestions_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Store (suggestion_dict, BooleanVar) pairs
        suggestion_vars = []

        for suggestion in suggestions:
            var = tk.BooleanVar(value=True)  # default to checked
            suggestion_vars.append((suggestion, var))

            frame = ttk.Frame(suggestions_frame, relief='groove', borderwidth=1)
            frame.pack(fill='x', pady=4)

            # Checkbox on the left
            cb = ttk.Checkbutton(frame, variable=var)
            cb.pack(side='left', padx=6, pady=4)

            # Text content
            text = f"{suggestion['param']} :  {suggestion['current']}  →  {suggestion['suggested']}"
            ttk.Label(frame, text=text, font=("Helvetica", 10, "bold")).pack(anchor='w', padx=8, pady=(4, 0))
            ttk.Label(frame, text=suggestion['reason'], wraplength=520).pack(anchor='w', padx=8, pady=(0, 6))

        # Bottom buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=12)

        def apply_suggestion(sugg):
            cfg = self.image_processor.cell_config
            pcfg = self.image_processor.preprocess_config

            param = sugg['param']
            value = sugg['suggested']

            if param == "detection_method":
                cfg.detection_method = value
            elif param == "preprocess_nr_gaussian":
                pcfg.nr_gaussian_sigma = value
            else:
                setattr(cfg, param, value)

        def apply_checked():
            applied = 0
            for sugg, var in suggestion_vars:
                if var.get():
                    apply_suggestion(sugg)
                    applied += 1
            if applied > 0:
                messagebox.showinfo("Applied", f"Applied {applied} change(s).\n\nYou may need to click 'Show Mask' again to see the effect.")
            dialog.destroy()

        def apply_all():
            for sugg, var in suggestion_vars:
                apply_suggestion(sugg)
            messagebox.showinfo("Applied", "Applied all suggested changes.\n\nYou may need to click 'Show Mask' again to see the effect.")
            dialog.destroy()

        ttk.Button(button_frame, text="Apply All That Are Checked", command=apply_checked, width=26).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Apply All", command=apply_all, width=14).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Close", command=dialog.destroy, width=10).pack(side='right', padx=5)

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
        self.brightness = float(value)
        self.show_page()

    def adjust_image(self, img):
        enhancer = ImageEnhance.Brightness(img)
        factor = 1 + (self.brightness / 100.0)
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

            config_data = {
                "version": "8.05.000",
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
                        self.window.update_idletasks()
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

        # Scale the logical positions of the atlas overlay
        self.img_x = (self.img_x * factor) + (cx * (factor - 1))
        self.img_y = (self.img_y * factor) + (cy * (factor - 1))

        # Update scale
        old_scale = self.view_scale
        self.view_scale = new_scale

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

    def _canvas_to_zone_model(self, cx, cy):
        """Map canvas coordinates to the model/pixel space used by the zone mask for the
        currently relevant layer (paint or atlas).

        - Painted regions (and baked 'img'/'png' layers) store their masks in background/image
          pixel space (no img_x/y offset). Use _canvas_to_image semantics.
        - Atlas (pdf) regions use the rendered page's model space (with img_x/y placement offset).

        This allows edge grab, border drag, and per-region translate/deform to work
        correctly and consistently for painted regions exactly like atlas regions.
        """
        if getattr(self, 'atlas_filetype', None) == 'pdf':
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
            self.edit_mode = False
            self.edit_mode_var.set(False)

        self._update_ribbon_selection()

        # Keep any active red edge highlight in the correct screen position after pan/zoom/page change
        if getattr(self, 'active_edge', None) is not None:
            self._update_edge_highlight()

        img = self.load_page_image() or Image.new('RGBA', (1, 1), (0, 0, 0, 0))

        self.output.delete("all")

        scale = self.view_scale

        if self.background_image:
            # Prefer original_background for higher quality when zooming
            base_bg = self.original_background if self.original_background is not None else self.background_image
            bg_display = self.adjust_image(base_bg)
            if scale != 1.0:
                new_w = max(1, int(bg_display.width * scale))
                new_h = max(1, int(bg_display.height * scale))
                bg_display = bg_display.resize((new_w, new_h), Image.BILINEAR)

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
                atlas_display = img.resize((aw, ah), Image.BILINEAR)

            self.photo = ImageTk.PhotoImage(atlas_display)
            display_img_x = self.img_x
            display_img_y = self.img_y

            self.output.create_image(display_img_x, display_img_y,
                                   image=self.photo,
                                   anchor='nw',
                                   tag='atlas')

        # --- Draw Zone Labels and Counts on the main image ---
        if self.show_zone_labels and self.last_df is not None and self.current_page in self.mask_images:
            try:
                mask = np.array(self.mask_images[self.current_page])
                mask_h, mask_w = mask.shape
                zone_data = self.last_df.set_index('Zone')['Cell_Count'].to_dict() if 'Zone' in self.last_df.columns else {}

                # Choose label placement offset:
                # - If zone mask size matches the main background image, the zones are in the background's
                #   coordinate system (e.g. hand-painted regions on a TIFF) -> place labels at (0,0) base.
                # - Otherwise (atlas overlay of different size), place relative to the atlas position (img_x/y).
                label_offset_x = display_img_x
                label_offset_y = display_img_y
                if self.background_image is not None:
                    bg_w, bg_h = self.background_image.size
                    if abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5:
                        label_offset_x = 0
                        label_offset_y = 0

                for zone_name, count in zone_data.items():
                    # Find pixels belonging to this zone in the mask
                    # We need to map zone_name back to zone_id
                    # For simplicity, we search in zone_names
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

                    # Compute center
                    cy = int(np.mean(coords[0]))
                    cx = int(np.mean(coords[1]))

                    # Scale to current view
                    screen_x = cx * scale + label_offset_x
                    screen_y = cy * scale + label_offset_y

                    label_text = f"{zone_name}\n({count})"
                    self.output.create_text(screen_x, screen_y, text=label_text, fill="yellow",
                                            font=("Helvetica", 10, "bold"), anchor="center",
                                            tags="zone_label")
            except Exception as e:
                logger.warning(f"Failed to draw zone labels: {e}")

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


    def img_white_to_transparent(self, img):
        img_array = np.array(img)
        white_mask = np.all(img_array[:, :, :3] >= 250, axis=-1)
        img_array[white_mask, 3] = 0
        img = Image.fromarray(img_array)
        return img

    def _canvas_to_atlas(self, canvas_x, canvas_y):
        """Convert canvas/screen coordinates to atlas model/native coordinates.
        Correctly accounts for self.img_x/y (layer offset) and self.view_scale (zoom).
        Returns floats for precision in distance/scale calculations.
        """
        if self.view_scale <= 0:
            return 0.0, 0.0
        model_x = (canvas_x - self.img_x) / self.view_scale
        model_y = (canvas_y - self.img_y) / self.view_scale
        return model_x, model_y

    def _rebuild_page_overlays(self, page=None):
        """Rebuild page_images[page] by taking the clean base and applying yellow (or orange for selected)
        tint overlays based on the current mask labels. This enables clean per-region edits without
        losing the underlying atlas artwork.
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
        arr = np.array(base)
        if page in self.mask_images:
            m = np.array(self.mask_images[page])
            for zid in np.unique(m):
                if zid == 0:
                    continue
                reg = (m == zid)
                if self.selected_zone_id is not None and self.selected_page == page and zid == self.selected_zone_id:
                    # Special tint for the actively selected region (visual feedback)
                    arr[reg, :3] = [255, 140, 0]  # orange
                    arr[reg, 3] = 50
                else:
                    arr[reg, :3] = [255, 255, 0]  # yellow
                    arr[reg, 3] = 18
        self.page_images[page] = Image.fromarray(arr.astype(np.uint8), 'RGBA')

    def import_atlas(self):
        logger.info("Opening file dialog for atlas selection")
        self.save_state()
        path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf"), ("PDF files", "*.ai")])
        if path:
            logger.info(f"Opening atlas file: {path}")
            self.path = path
            self.doc, self.num_pages = self.pdf_handler.open_pdf(self.path)
            self.atlas_filetype = 'pdf'
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

    def import_tiff(self):
        logger.info("Opening file dialog for TIFF selection")
        self.named_paint_groups.clear()
        self.paint_group_data.clear()
        self.painted_zone_outlines.clear()
        self.current_paint_group = None
        self.view_scale = 1.0
        self.img_x = 0
        self.img_y = 0

        # Full reset of zone/mask system on every new image load.
        # This ensures painted regions from previous images do not leak into new ones.
        self.mask_images = {}
        self.zone_names = {}
        self.zone_counters = {}
        if self.current_page is None:
            self.current_page = 0

        # Also clear any stale region selection / edge edit state from previous atlas or image.
        # Prevents stale selected_zone_id or selected_edge_full_contour from hijacking
        # global atlas Move (drag_start/drag_move priority checks) or causing other issues
        # when loading a new image (especially after atlas was loaded first).
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

        tiff_path = fd.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
        if tiff_path:
            logger.info(f"Opening TIFF file: {tiff_path}")
            self.tiff_dir = os.path.dirname(tiff_path)
            self.tiff_filename = os.path.splitext(os.path.basename(tiff_path))[0]
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

            ww, wh = self.output.winfo_width(), self.output.winfo_height()
            bw, bh = bg_RGBA.size
            scale = min(ww / bw, wh / bh)
            new_size = (int(bw * scale), int(bh * scale))
            self.background_image = bg_RGBA.resize(new_size, Image.BILINEAR)
            self.original_background = self.background_image.copy()

            # Create fresh transparent paint layer at native resolution
            self.paint_layer = Image.new('RGBA', self.original_background.size, (0, 0, 0, 0))

            self.show_page()

            # New document loaded — previous undo history is no longer valid
            # (different background size / coordinate system).
            try:
                self.state_manager.undo_stack.clear()
            except Exception:
                self.state_manager.undo_stack = []

    # ------------------------------------------------------------------
    # File Browser (Left Pane) - Directory TIFF selector
    # ------------------------------------------------------------------

    def select_tiff_directory(self):
        """Let user choose a folder containing TIFF files."""
        directory = fd.askdirectory(title="Select folder containing TIFF images")
        if directory:
            self.current_tiff_directory = directory
            self.folder_label.config(text=directory)
            self.refresh_tiff_file_list()
            # Force wraplength update after the text is set
            self.file_browser_frame.after(50, self._update_folder_label_wraplength)

    def refresh_tiff_file_list(self):
        """Scan the current directory for .tif / .tiff files and update the Treeview.
        Shows counted status (✓) and child entries for generated artifacts:
        - the counted .xlsx/.csv when Count Cells has run
        - saved paint layer files (*.png or the new *_paint_with_regions.barccpaint bundle) when Save Paint Layer is used.
        This makes the left pane act more like a live file manager for the working directory.
        """
        if not self.current_tiff_directory or not os.path.isdir(self.current_tiff_directory):
            return

        self.tiff_file_list = []
        self._tree_iid_to_path = {}

        try:
            files = os.listdir(self.current_tiff_directory)
            tiff_files = [f for f in files if f.lower().endswith(('.tif', '.tiff'))]
            tiff_files.sort()

            self.tiff_file_list = [os.path.join(self.current_tiff_directory, f) for f in tiff_files]

            # Clear and repopulate Treeview (supports children for associated files)
            if hasattr(self, 'tiff_tree'):
                for item in self.tiff_tree.get_children():
                    self.tiff_tree.delete(item)

                for full_path in self.tiff_file_list:
                    filename = os.path.basename(full_path)
                    has_counted = self._has_matching_csv(full_path)
                    status = "✓" if has_counted else ""

                    # Top-level TIFF row
                    iid = self.tiff_tree.insert("", "end", values=(filename, status), open=True)
                    self._tree_iid_to_path[iid] = full_path

                    directory = os.path.dirname(full_path)
                    base = os.path.splitext(filename)[0]

                    # Add child rows for counted results (the Excel the user mentioned)
                    counted_cands = [
                        f"{base}.xlsx", f"{base}.csv",
                        f"{base}_counted.xlsx", f"{base}_counted.csv",
                        f"{base} - counted.xlsx", f"{base} - counted.csv",
                        f"{base}_cells.xlsx", f"{base}_cells.csv",
                    ]
                    for cand in counted_cands:
                        cpath = os.path.join(directory, cand)
                        if os.path.exists(cpath):
                            self.tiff_tree.insert(iid, "end", values=(cand, ""))

                    # Add child rows for saved paint images / bundles (when Save Paint Layer is used)
                    try:
                        for f in files:
                            fl = f.lower()
                            if fl.startswith(base.lower() + "_paint"):
                                if fl.endswith('.png') or fl.endswith('.barccpaint'):
                                    self.tiff_tree.insert(iid, "end", values=(f, ""))
                    except Exception:
                        pass

        except Exception as e:
            messagebox.showerror("Error", f"Failed to read directory:\n{e}")

    def _update_folder_label_wraplength(self, event=None):
        """Dynamically set wraplength based on the current width of the file browser pane."""
        if hasattr(self, 'folder_label') and self.folder_label.winfo_exists():
            width = self.folder_label.winfo_width()
            if width > 50:
                new_wrap = max(60, width - 8)
                self.folder_label.configure(wraplength=new_wrap)

    def _has_matching_csv(self, tiff_path):
        """Check if a results file (CSV or XLSX) matching this TIFF exists in the same directory."""
        if not tiff_path or not os.path.exists(tiff_path):
            return False

        directory = os.path.dirname(tiff_path)
        base_name = os.path.splitext(os.path.basename(tiff_path))[0]

        # Check for common output files generated by Count Cells
        candidates = [
            f"{base_name}.csv",
            f"{base_name}.xlsx",
            f"{base_name}_counted.csv",
            f"{base_name}_counted.xlsx",
            f"{base_name} - counted.csv",
            f"{base_name}_cells.csv",
        ]

        for candidate in candidates:
            file_path = os.path.join(directory, candidate)
            if os.path.exists(file_path):
                return True

        return False

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
            # Child item - check if it's a paint accessory file
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
                    # Now load the paint onto it
                    paint_full_path = os.path.join( os.path.dirname(parent_tiff_path), child_name )
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
        """Builds the left-side file manager pane with counted status."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        # Header
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))

        ttk.Button(header, text="Select Folder", command=self.select_tiff_directory).pack(fill='x')

        self.folder_label = ttk.Label(header, text="No folder selected", anchor='w', justify=tk.LEFT)
        self.folder_label.pack(fill='x', pady=(4, 0))

        # Dynamically adjust wraplength when the pane is resized
        header.bind("<Configure>", self._update_folder_label_wraplength)

        # Initial wraplength update after layout settles
        parent.after(150, self._update_folder_label_wraplength)

        # File list using Treeview for multiple columns (Filename + Counted status)
        columns = ("image", "counted")
        self.tiff_tree = ttk.Treeview(parent, columns=columns, show="tree", selectmode="browse")
        # Give the tree column a little width so hierarchy/children (for .xlsx and saved paint .png / .barccpaint) are visible
        self.tiff_tree.column("#0", width=20, minwidth=16, stretch=False)
        self.tiff_tree.heading("#0", text="")
        self.tiff_tree.column("image", width=160, anchor="w")
        self.tiff_tree.column("counted", width=40, anchor="center")

        self.tiff_tree.heading("image", text="Image")
        self.tiff_tree.heading("counted", text="✓")

        self.tiff_tree.grid(row=2, column=0, sticky='nsew', padx=4, pady=4)
        self.tiff_tree.bind("<Double-Button-1>", self.load_tiff_from_list)

        # Store mapping from iid to full path
        self._tree_iid_to_path = {}

        # Refresh button
        ttk.Button(parent, text="Refresh", command=self.refresh_tiff_file_list).grid(row=3, column=0, sticky='ew', padx=4, pady=(0, 4))

    def _load_tiff_file(self, tiff_path):
        """Core TIFF loading logic (shared between manual import and file browser)."""
        if not tiff_path or not os.path.exists(tiff_path):
            messagebox.showerror("Error", "Selected file does not exist.")
            return

        logger.info(f"Loading TIFF from file browser: {tiff_path}")

        # Full reset of zone/mask system on every new image load.
        # This ensures painted regions from previous images do not leak into new ones.
        self.mask_images = {}
        self.zone_names = {}
        self.zone_counters = {}
        if self.current_page is None:
            self.current_page = 0

        # Reset state similar to import_tiff
        self.named_paint_groups.clear()
        self.paint_group_data.clear()
        self.painted_zone_outlines.clear()
        self.current_paint_group = None
        self.view_scale = 1.0
        self.img_x = 0
        self.img_y = 0

        # Also clear any stale region selection / edge edit state (same as import_tiff).
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

        # Clear manual cell edit masks so they don't carry over from a previous image (different size/content)
        self.manual_add_mask = None
        self.manual_remove_mask = None
        self.editing_mask = False
        self.current_mask = None
        self.auto_mask = None

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

            ww, wh = self.output.winfo_width(), self.output.winfo_height()
            bw, bh = bg_RGBA.size
            scale = min(ww / bw, wh / bh) if ww > 1 and wh > 1 else 1.0
            new_size = (int(bw * scale), int(bh * scale))
            self.background_image = bg_RGBA.resize(new_size, Image.BILINEAR)
            self.original_background = self.background_image.copy()

            self.paint_layer = Image.new('RGBA', self.original_background.size, (0, 0, 0, 0))

            self.show_page()

            # New document loaded via browser — clear undo history (incompatible prior masks).
            try:
                self.state_manager.undo_stack.clear()
            except Exception:
                self.state_manager.undo_stack = []

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load TIFF:\n{e}")
            logger.error(f"Failed to load TIFF {tiff_path}: {e}")

    def save_flattened_image(self, event=None):
        logger.info("Attempting to save flattened image")
        if self.background_image is None or self.current_page not in self.page_images:
            logger.warning("Save flattened image failed: Missing TIFF or PDF file")
            messagebox.showerror("Error", "Please import a TIFF and open a PDF file first.")
            return

        bg_img = self.background_image
        at_img = self.page_images[self.current_page]

        bg_w, bg_h = bg_img.size
        at_w, at_h = at_img.size

        left = min(0, self.img_x)
        top = min(0, self.img_y)
        right = max(bg_w, self.img_x + at_w)
        bottom = max(bg_h, self.img_y + at_h)

        width = right - left
        height = bottom - top

        base = Image.new('RGBA', (width, height), (255, 255, 255, 255))

        bg_offset_x = -left
        bg_offset_y = -top
        # base.paste(bg_img, (bg_offset_x, bg_offset_y), bg_img)
        base.paste(bg_img, (bg_offset_x, bg_offset_y))

        at_offset_x = self.img_x - left
        at_offset_y = self.img_y - top
        base.paste(at_img, (at_offset_x, at_offset_y), at_img)

        final = base.convert('RGB')

        save_path = fd.asksaveasfilename(title="Save Flattened Image", defaultextension=".jpg", filetypes=[("JPEG files", "*.jpg")])
        if save_path:
            final.save(save_path)
            messagebox.showinfo("Image Saved", f"Flattened image saved to: {save_path}")

    def autosave_flattened_image(self, filename):
        if self.background_image is None or self.current_page not in self.page_images:
            return

        # Get the background and atlas images
        bg_img = self.background_image
        at_img = self.page_images[self.current_page]
        
        # Get dimensions
        bg_w, bg_h = bg_img.size
        at_w, at_h = at_img.size

        # Calculate the canvas size needed
        left = min(0, self.img_x)
        top = min(0, self.img_y)
        right = max(bg_w, self.img_x + at_w)
        bottom = max(bg_h, self.img_y + at_h)
        width = right - left
        height = bottom - top

        # Create a new RGB image with white background
        base = Image.new('RGB', (width, height), (255, 255, 255))

        # First paste the background image without transparency
        bg_rgb = bg_img.convert('RGB')
        base.paste(bg_rgb, (-left, -top))

        # Then paste the atlas with transparency
        if at_img.mode == 'RGBA':
            # Extract the alpha channel to use as mask
            r, g, b, a = at_img.split()
            at_rgb = Image.merge('RGB', (r, g, b))
            base.paste(at_rgb, (self.img_x - left, self.img_y - top), a)
        else:
            base.paste(at_img, (self.img_x - left, self.img_y - top))

        base.save(filename)

    def toggle_crop_mode(self):
        self.save_state()
        self.crop_mode = not self.crop_mode
        self.crop_mode_var.set(self.crop_mode)
        if self.crop_mode:
            self.region_move_mode.set(False)
            self.border_mode_var.set(False)
            if getattr(self, 'edit_mode', False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.region_translate_active = False
            self.output.bind("<Button-1>", self.crop_start)
            self.output.bind("<B1-Motion>", self.crop_drag)
            self.output.bind("<ButtonRelease-1>", self.crop_end)
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")
            self.output.unbind("<ButtonRelease-1>")
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            if self.crop_rect:
                self.output.delete(self.crop_rect)
                self.crop_rect = None

    def crop_start(self, event):
        self.start_x = self.output.canvasx(event.x)
        self.start_y = self.output.canvasy(event.y)
        if self.crop_rect:
            self.output.delete(self.crop_rect)
        self.crop_rect = self.output.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', dash=(4, 4))

    def crop_drag(self, event):
        cur_x = self.output.canvasx(event.x)
        cur_y = self.output.canvasy(event.y)
        self.output.coords(self.crop_rect, self.start_x, self.start_y, cur_x, cur_y)

    def crop_end(self, event):
        end_x = self.output.canvasx(event.x)
        end_y = self.output.canvasy(event.y)
        page = self.current_page

        # Convert the canvas-space crop rectangle to *model* (atlas native) coordinates.
        # base_page_images, page_images[] and mask_images[] are stored at the native
        # resolution of the rendered PDF page (or original atlas size). Canvas coords
        # include view_scale + img_x/img_y layer offset, so direct use of canvas numbers
        # for PIL.crop produces wrong (often tiny/empty/out-of-bounds) results after any
        # pan or zoom -- causing the atlas to "disappear" after crop.
        mx1, my1 = self._canvas_to_atlas(self.start_x, self.start_y)
        mx2, my2 = self._canvas_to_atlas(end_x, end_y)
        mleft = min(mx1, mx2)
        mtop = min(my1, my2)
        mright = max(mx1, mx2)
        mbottom = max(my1, my2)

        # Remember the canvas position of the crop top-left. After cropping the rasters
        # we rebase img_x/img_y so the new smaller atlas's (0,0) is drawn exactly where
        # the TL of the crop rect was. This prevents the remaining content from jumping
        # and keeps the "cropped to selection" feel.
        cleft = min(self.start_x, end_x)
        ctop = min(self.start_y, end_y)

        # --- Crop base (clean reference for rebuilds) using model coords + clamp ---
        if page in self.base_page_images:
            base = self.base_page_images[page]
            bw, bh = base.size
            left = max(0, min(int(mleft), bw))
            top = max(0, min(int(mtop), bh))
            right = max(left, min(int(mright), bw))
            bottom = max(top, min(int(mbottom), bh))
            if right > left and bottom > top:
                cropped_base = base.crop((left, top, right, bottom))
                cropped_base = self.img_white_to_transparent(cropped_base)
                self.base_page_images[page] = cropped_base
            else:
                # Degenerate rect (e.g. click with no drag, or completely outside) -- abort cleanly
                self.show_page()
                self.toggle_crop_mode()
                return

        # --- Crop the loaded page image (we also assign so size is consistent until rebuild) ---
        img = self.load_page_image()
        iw, ih = img.size
        left = max(0, min(int(mleft), iw))
        top = max(0, min(int(mtop), ih))
        right = max(left, min(int(mright), iw))
        bottom = max(top, min(int(mbottom), ih))
        if right > left and bottom > top:
            cropped_img = img.crop((left, top, right, bottom))
            cropped_img = self.img_white_to_transparent(cropped_img)
            self.page_images[page] = cropped_img
        else:
            self.show_page()
            self.toggle_crop_mode()
            return

        # --- Crop mask (the labels must stay aligned with the new base) ---
        if page in self.mask_images:
            mask_img = self.mask_images[page]
            mw, mh = mask_img.size
            left = max(0, min(int(mleft), mw))
            top = max(0, min(int(mtop), mh))
            right = max(left, min(int(mright), mw))
            bottom = max(top, min(int(mbottom), mh))
            if right > left and bottom > top:
                cropped_mask = mask_img.crop((left, top, right, bottom))
                self.mask_images[page] = cropped_mask
            # (if degenerate we already returned above from the page_images crop)

        # Prune zone_names for any zids that no longer have any pixels after the crop.
        # Keeps the "Labeled Regions" list in the Atlas Manager accurate (no ghosts for
        # regions that were cropped away). Counters are left alone (never reuse ids).
        if page in self.mask_images and page in self.zone_names:
            try:
                m = np.array(self.mask_images[page])
                present = {int(z) for z in np.unique(m) if z > 0}
                for zid in list(self.zone_names[page].keys()):
                    if zid not in present:
                        del self.zone_names[page][zid]
            except Exception:
                pass

        # Rebase the atlas layer offset. The new native (0,0) now corresponds to what used
        # to be (mleft, mtop) in the old image; place it at the same screen location.
        self.img_x = cleft
        self.img_y = ctop

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
        self.region_move_mode.set(False)

        self.show_page()
        self.toggle_crop_mode()
        if getattr(self, 'count_button', None) is not None and not getattr(self, 'count_button_packed', False):
            try:
                self.count_button.pack(side=tk.LEFT, padx=10, pady=10)
                self.count_button_packed = True
            except Exception:
                pass

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
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                if self.crop_rect:
                    self.output.delete(self.crop_rect)
                    self.crop_rect = None
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
        self.img_x += dx
        self.img_y += dy
        self.show_page()
        self.drag_start_x = event.x
        self.drag_start_y = event.y

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

    def deselect_region(self):
        """Clear current region selection (returns tint to normal yellow)."""
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
            if self.current_page in self.base_page_images:
                self._rebuild_page_overlays(self.current_page)
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

            self.selected_zone_id = zid
            self.selected_page = self.current_page
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
            # Rebuild will show it in orange
            self._rebuild_page_overlays(self.current_page)
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
        ttk.Checkbutton(global_frame, text="Move", variable=self.edit_mode_var, command=self.toggle_edit_mode, width=7).pack(side=tk.LEFT, padx=1)

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
        ttk.Label(list_frame, text="Labeled Regions (current page) - click to select for edit:").pack(anchor='w')
        lb_container = ttk.Frame(list_frame)
        lb_container.pack(fill='both', expand=True)
        self.region_listbox = tk.Listbox(lb_container, height=5, exportselection=False)
        self.region_listbox.pack(side=tk.LEFT, fill='both', expand=True)
        lb_scroll = ttk.Scrollbar(lb_container, orient=tk.VERTICAL, command=self.region_listbox.yview)
        lb_scroll.pack(side=tk.RIGHT, fill='y')
        self.region_listbox.configure(yscrollcommand=lb_scroll.set)
        self.region_listbox.bind('<<ListboxSelect>>', self._on_region_list_select)

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
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                if self.crop_rect:
                    self.output.delete(self.crop_rect)
                    self.crop_rect = None
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
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                if self.crop_rect:
                    self.output.delete(self.crop_rect)
                    self.crop_rect = None
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
        # Set as selected for editing
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
        # Update visual (orange tint) and display
        if self.current_page in self.base_page_images:
            self._rebuild_page_overlays(self.current_page)
        self.show_page()
        self._update_ribbon_selection()  # will re-sync everything including list highlight

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

        # Make sure this zone is the active selected (orange). Clear any prior edge.
        if self.selected_zone_id != clicked_zid or getattr(self, 'selected_page', None) != page:
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self.selected_zone_id = clicked_zid
            self.selected_page = page
            self._rebuild_page_overlays(page)
            self.show_page()  # make the newly activated zone's orange fill visible immediately
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
        ox = getattr(self, 'img_x', 0)
        oy = getattr(self, 'img_y', 0)
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
        ox = getattr(self, 'img_x', 0)
        oy = getattr(self, 'img_y', 0)
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
        display_img_x = getattr(self, 'img_x', 0)
        display_img_y = getattr(self, 'img_y', 0)
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
        """Called on Enter/Return after border drag on a painted region.
        Commits the current mask shape (yellow expansion) by refitting the black drawn
        boundary (updating painted_zone_outlines from the live mask contour and
        rebuilding the paint_layer). This is the explicit 'save' step for the expanded shape.
        """
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

    def count_cells(self):
        logger.info("Starting cell counting process")
        if self.background_image is None:
            logger.warning("Cell counting failed: No TIFF file imported")
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        # Automatically stop the paint tool if it's still active.
        # This ensures any painted regions are committed to the zone system
        # before we try to count cells.
        if getattr(self, 'current_state', None) == 'paint':
            self.stop_paint()

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
        progress.set_progress(10, "Preparing data...")

        # === Build Final Cell Mask ===
        progress.set_progress(25, "Running cell detection...")
        if self.original_background is None:
            if self.background_image is not None:
                self.original_background = self.background_image.copy()
            else:
                if progress and not getattr(progress, 'closed', False):
                    progress.close()
                messagebox.showerror("Error", "No original background image available for cell detection.")
                return
        background = self.original_background.convert('L')
        _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
        auto_mask = auto_labels > 0  # Boolean array

        progress.set_progress(45, "Processing manual edits...")
        # Convert manual edit masks to boolean arrays
        base_size = background.size
        add_mask = np.zeros(auto_mask.shape, dtype=bool)
        remove_mask = np.zeros(auto_mask.shape, dtype=bool)

        if self.manual_add_mask is not None:
            logger.debug(f"Manual add mask nonzero pixels: {np.count_nonzero(np.array(self.manual_add_mask))}")
        if self.manual_remove_mask is not None:
            logger.debug(f"Manual remove mask nonzero pixels: {np.count_nonzero(np.array(self.manual_remove_mask))}")

        if self.manual_add_mask is not None:
            add_mask_arr = np.array(self.manual_add_mask.resize(base_size, Image.NEAREST))
            add_mask = add_mask_arr > 0

        if self.manual_remove_mask is not None:
            remove_mask_arr = np.array(self.manual_remove_mask.resize(base_size, Image.NEAREST))
            remove_mask = remove_mask_arr > 0

        # Combine all
        final_cell_mask = (auto_mask | add_mask) & ~remove_mask

        # Convert to PIL (L mode)
        cell_mask_pil = Image.fromarray((final_cell_mask * 255).astype(np.uint8))

        # Use the region mask (zone map) separately
        region_mask_pil = self.mask_images[self.current_page]

        progress.set_progress(65, "Counting cells per region...")

        annotated, df, counts = count_cells_in_zones(
            self.original_background,
            region_mask_pil,
            cell_mask_pil,
            self.img_x,
            self.img_y,
            self.zone_counters,
            self.zone_names.get(self.current_page, {}),
        )

        self.background_image = annotated
        self.last_df = df

        progress.set_progress(85, "Generating annotated image...")
        self.show_page()

        # Close the progress dialog before showing final results popups.
        # Leaving it open while showing messagebox + later close can cause focus/event
        # issues or apparent crashes on some systems when the results dialog is dismissed.
        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(100, "Done")
            progress.close()

        # === Prepare save paths (must be before using in early masked save) ===
        base_name = self.tiff_filename
        tiff_dir = self.tiff_dir

        # Run the masked overlay save early (before any final popups) so that when the
        # user dismisses the "Results Saved" dialog there is no further work that could
        # trigger a crash or bad state.
        if tiff_dir and base_name and self.original_background is not None:
            try:
                orig = self.original_background.convert('RGBA')
                mask_full = final_cell_mask
                mask_resized = Image.fromarray((mask_full * 255).astype(np.uint8)).resize(orig.size, Image.NEAREST)
                overlay = Image.new('RGBA', orig.size, (0, 0, 0, 0))
                red_layer = Image.new('RGBA', orig.size, (255, 0, 0, 110))
                overlay.paste(red_layer, mask=mask_resized)
                masked_img = Image.alpha_composite(orig, overlay)
                masked_path = os.path.join(tiff_dir, f"{base_name}_masked.tif")
                masked_img.save(masked_path, compression='tiff_deflate')
                logger.info(f"Masked image saved: {masked_path}")
            except Exception as e:
                logger.error(f"Failed to save _masked.tif: {e}")

        # === Automatic saving of results (new in 8.01, improved in 8.02) ===

        # 1. Save Excel file with two sheets (Counts + Detection Parameters)
        excel_saved = False
        if tiff_dir and base_name:
            xlsx_path = os.path.join(tiff_dir, f"{base_name}.xlsx")
            for engine in ['openpyxl', 'xlsxwriter']:
                try:
                    with pd.ExcelWriter(xlsx_path, engine=engine) as writer:
                        df.to_excel(writer, sheet_name="Cell Counts", index=False)

                        # Metadata sheet with all detection parameters
                        meta_data = []
                        cfg = self.image_processor.cell_config
                        pcfg = self.image_processor.preprocess_config

                        for k, v in cfg.__dict__.items():
                            meta_data.append({"Category": "Cell Detection", "Parameter": k, "Value": str(v)})

                        for k, v in pcfg.__dict__.items():
                            meta_data.append({"Category": "Preprocessing", "Parameter": k, "Value": str(v)})

                        meta_df = pd.DataFrame(meta_data)
                        meta_df.to_excel(writer, sheet_name="Detection Parameters", index=False)

                    messagebox.showinfo("Results Saved", f"Excel file saved:\n{xlsx_path}")
                    excel_saved = True
                    break
                except Exception:
                    continue  # try next engine

            if not excel_saved:
                # Final fallback to CSV
                try:
                    csv_path = os.path.join(tiff_dir, f"{base_name}.csv")
                    df.to_csv(csv_path, index=False)
                    messagebox.showwarning(
                        "Excel Export Failed",
                        f"Could not save as Excel (openpyxl or xlsxwriter not installed).\n"
                        f"Fell back to CSV:\n{csv_path}\n\n"
                        f"To enable .xlsx output with metadata sheet, run:\n"
                        f"pip install openpyxl xlsxwriter"
                    )
                except Exception as e:
                    logger.error(f"CSV fallback also failed: {e}")
        else:
            logger.warning("Skipping auto-save of count results (missing tiff_dir or base_name)")
            try:
                messagebox.showinfo("Count Complete", "Cells counted. No working TIFF directory was set, so no Excel/CSV was auto-saved.")
            except Exception:
                pass

        # Refresh file browser so the "counted" indicator updates
        # (the progress dialog was already closed above before any results popups)
        if hasattr(self, 'tiff_tree') and self.current_tiff_directory:
            self.master.after(300, self.refresh_tiff_file_list)

    def show_cell_mask_threshold(self, event=None, calculate=True):
        """Display the combined (auto + manual) mask overlay"""
        progress = None
        if calculate:
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
                if progress2:
                    progress2.set_progress(55, "Building mask visualization...")
                    progress2.close()

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

        # Visualize combined mask on top of the original background
        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(85, "Generating visualization...")
        background = self.adjust_image(self.original_background)
        original_rgb = background.convert('RGB')
        vis_array = np.array(original_rgb.convert('RGBA'))
        red_overlay = np.zeros_like(vis_array)
        red_overlay[combined_mask] = [255, 0, 0, 255]

        alpha = 0.7
        vis_array = (vis_array + alpha * red_overlay).astype(np.uint8)
        alpha_array = (alpha * red_overlay).astype(np.uint8)

        # mask_img = Image.fromarray(vis_array)
        mask_img = Image.fromarray(alpha_array)
        mask_img = mask_img.resize(self.original_background.size, Image.NEAREST)

        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(95, "Displaying mask...")
        self.show_page(mask=mask_img)

        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(100, "Done")
            progress.close()

        self.showing_auto_mask = True

    
    def next_image_experimental(self): # unused
        self.root.destroy()
        PDFViewer()

    def next_image(self):
        logger.info("Processing next image")
        if self.tiff_filename is None:
            logger.warning("Next image failed: No TIFF loaded")
            messagebox.showerror("Error", "No TIFF loaded.")
            return

        image_path = os.path.join(self.tiff_dir, f"{self.tiff_filename}_counted.jpg")
        csv_path = os.path.join(self.tiff_dir, f"{self.tiff_filename}_data.csv")

        self.autosave_flattened_image(image_path)

        if self.last_df is not None:
            self.last_df.to_csv(csv_path, index=False)

        # This is SO UGLY, see if there is a cleaner way to re-init tkinter without breaking everything
        # Could I do .destroy() and then call the program again?
        clear_preprocess_cache()
        self.preprocess_image = None
        self.background_image = None
        self.original_background = None
        self.img = None
        self.atlas_filetype = None
        self.doc = None
        self.current_page = None
        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.selected_zone_id = None
        self.selected_page = None
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        self.last_df = None
        self.img_x = 0
        self.img_y = 0

        self.manual_add_mask = None
        self.manual_remove_mask = None
        self.editing_mask = False
        self.mask_edit_add = True  # True = add cells, False = remove cells
        self.mask_photo = False
        self.mask_photo_id = False
        self.current_mask = None   # reference to the current mask being edited
        self.auto_mask = None
        self.showing_auto_mask = False

        # Manual edit masks
        self.manual_add_mask = None
        self.manual_remove_mask = None

        # Background (TIFF) image
        self.background_image = None
        self.original_background = None
        self.bg_photo_id = None
        self.atlas_filetype = None

        # TIFF filename
        # Do NOT clear current_tiff_directory or the file browser list/tree
        # so the user stays in the same directory.
        self.tiff_filename = None
        self.tiff_dir = None

        # Clear paint states for full reset
        self.named_paint_groups = {}
        self.paint_group_data = {}
        self.current_paint_group = None
        self.paint_layer = None

        # Last DF for counts
        self.last_df = None

        # Brightness
        self.brightness = 0.0

        # Mouse state tracking
        self.current_state = None

        self.show_page()

        # Fully clear Atlas Manager state (labeled regions list, selection, etc.)
        # and any remaining loaded content so it feels like a fresh start.
        if hasattr(self, '_update_ribbon_selection'):
            self._update_ribbon_selection()

        if self.last_df is not None:
            messagebox.showinfo("Next Image", f"Autosaved image to {image_path}\nAutosaved counts to {csv_path}") 
        else:
            messagebox.showinfo("Next Image", f"Autosaved image to {image_path}")

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
    
    # Detect cells
    img2d, binary = binary_mask_cell_count(Image.fromarray((background_norm * 255).astype(np.uint8)))

    # Include manual mask edits if provided
    if page_pil is not None:
        binary = np.array(page_pil) > 0

    logger.debug("Performing distance transform for watershed")
    distance = distance_transform_edt(binary)

    # Find local maxima as markers
    coords = feature.peak_local_max(distance, min_distance=5, exclude_border=True)
    markers = np.zeros(distance.shape, dtype=bool)
    if coords.size:
        markers[tuple(coords.T)] = True
    markers = measure.label(markers)

    # Watershed segmentation
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

    # Prepare results DataFrame
    zone_list, count_list = [], []
    for zid in sorted(counts.keys()):
        name = zone_names.get(zid, f"Zone {zid}")
        zone_list.append(name)
        count_list.append(counts[zid])
    df = pd.DataFrame({'Zone': zone_list, 'Cell_Count': count_list})
    
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
    PDFViewer()
