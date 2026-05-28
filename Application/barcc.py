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
from skimage.morphology import binary_closing, disk
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
        self.zone_counters = {}
        self.zone_names = {}

        # Undo/state
        self.undo_stack = self.state_manager.undo_stack

        # Paint variables
        self.brush_size = tk.IntVar(value=4.0)
        self.DEFAULT_COLOR = 'black'

        # Grouped paint strokes: each continuous mouse-down to mouse-up is one "structural boundary"
        self._paint_group_counter = 0
        self.current_paint_group = None
        self.named_paint_groups = {}   # group_tag (e.g. 'paintgroup_5') -> name

        # Crop / edit variables
        self.crop_mode = False
        self.crop_rect = None
        self.start_x = None
        self.start_y = None

        self.edit_mode = False
        self.img_x = 0
        self.img_y = 0
        self.drag_start_x = None
        self.drag_start_y = None

        # Mask editing state
        self.editing_mask = False
        self.mask_edit_add = True  # True = add cells, False = remove cells
        self.current_mask = None   # reference to the current mask being edited
        # self.auto_mask = np.array([[0,0,0], [0,0,0]])
        self.auto_mask = False

        # View zoom (separate from PDF render zoom)
        self.view_scale = 1.0
        self.min_scale = 0.2
        self.max_scale = 8.0

        # Display options
        self.show_zone_labels = False

        # Transparent menu / window mode
        self.transparent_mode = tk.BooleanVar(value=False)
        self.transparent_windows = []  # popups that should follow transparent mode

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

        self.root.mainloop()

    def init_keybinds(self):
        # Keyboard shortcuts
        self.master.bind('<q>', self.quit)
        self.master.bind('<Control-z>', self._undo_event)
        self.master.bind('<Control-s>', self.save_flattened_image)

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
        filemenu.add_command(label="Import Atlas Section", command=self.open_file)
        filemenu.add_command(label="Import Paint", command=self.open_paint)
        filemenu.add_command(label="Save Paint", command=self.save_paint_to_pdf)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_command(label="Next Image", command=self.next_image)
        filemenu.add_command(label="User Manual", command=self.open_user_manual)
        filemenu.add_command(label="Exit", command=self.master.destroy)

        # Create Edit menu dropdown
        editmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Edit", menu=editmenu)
            # Add save paint command and create toplevels with widgets
        editmenu.add_command(label="Brightness", command=self.show_brightness_settings)
        editmenu.add_command(label="Save Picture", command=self.save_flattened_image)
        # editmenu.add_command(label="Save Paint", command=print("Save Paint", file=sys.stderr))

        # Create Atlas menu dropdown
        atlasmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Atlas", menu=atlasmenu)
        atlasmenu.add_command(label="Crop", command=self.toggle_crop_mode)
        atlasmenu.add_command(label="Move", command=self.toggle_edit_mode)
        atlasmenu.add_command(label="Rotate", command=self.show_rotate_settings)
        atlasmenu.add_command(label="Scale", command=self.show_scale_settings)
        
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

        self.top_frame.rowconfigure(0, weight=1)
        self.top_frame.columnconfigure(0, weight=1)

        # Scrollbars and canvas (moved inside top_frame)
        self.scrolly = ttk.Scrollbar(self.top_frame, orient=tk.VERTICAL)
        self.scrolly.grid(row=0, column=1, sticky='ns')
        self.scrollx = ttk.Scrollbar(self.top_frame, orient=tk.HORIZONTAL)
        self.scrollx.grid(row=1, column=0, sticky='ew')

        self.output = tk.Canvas(self.top_frame, bg='#ECE8F3')
        self.output.configure(yscrollcommand=self.scrolly.set, xscrollcommand=self.scrollx.set)
        self.output.grid(row=0, column=0, sticky='nsew')
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

    # End of UI, beginning of functions

    def split_tiff(self):
        path = fd.askopenfilename(filetypes=[("TIFF files", "*.tif *.tiff")])
        if path:
            split_stacked_tiff(path)

    def start_paint(self):
        if self.current_state == 'paint':
            return
        self.current_state = 'paint'
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

    def stop_paint(self):
        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>') 
        self.output.unbind('<Button-1>')
        self.output.unbind('<Button-3>')
        self.output.bind('<Button-1>', self.highlight_region)
        self.menu.delete(8)
        self.current_state = None

        # Auto-assign default names to any painted strokes/groups that the user didn't explicitly name
        # This ensures the spreadsheet always gets populated with Painted Regions when using the paint tool.
        paint_items = self.output.find_withtag('paint')
        all_current_groups = set()
        for item in paint_items:
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    all_current_groups.add(tag)

        for group_tag in all_current_groups:
            if group_tag not in self.named_paint_groups:
                self.named_paint_groups[group_tag] = None  # will get default name in convert

        # Convert (named + auto-defaulted) paint groups to proper zones (for cell counting)
        self._convert_named_paints_to_zones()

        # Now that the user has finished painting, bake everything into the paint_layer
        # and clean up the temporary canvas items. This is when labeling is "finalized".
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()

        self.output.delete('paint')   # Remove all temporary paint strokes from canvas
        self.save_paint()
        self.named_paint_groups.clear()
        self.current_paint_group = None
        self.show_page()

    def save_paint(self):
        """Save canvas paint strokes to an image without using postscript"""
        
        # Get canvas bounds
        bbox = self.output.bbox("paint")  # Get bounds of items tagged with 'paint'
        if not bbox:
            logger.debug("No paint strokes to save")
            return  # No paint to save
            
        # Get coordinates of entire painting area
        x1, y1, x2, y2 = bbox
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

    def save_paint_to_pdf(self):
        if self.atlas_filetype != 'img':
            logger.debug("No painting to save")
            return
        
        save_path = fd.asksaveasfilename(title="Save Paint", defaultextension=".png", filetypes=[("PNG files", "*.png")])
        if save_path == None:
            print("save_path is none", file=sys.stderr)
            return
        
        RGBA_img = self.img
        RGBA_img.save(save_path)
        messagebox.showinfo("Image Saved", f"Paint saved to: {save_path}")

    def open_paint(self):
        logger.info("Opening file dialog for paint selection")
        self.save_state()
        path = fd.askopenfilename(filetypes=[("PNG files", "*.png")])
        if path:
            logger.info(f"Opening paint file: {path}")
            self.path = path
            self.img = Image.open(path)
            self.atlas_filetype = 'png'
            clear_preprocess_cache()

            # Ensure we have a paint layer even when loading a paint file as base
            if self.original_background is not None and self.paint_layer is None:
                self.paint_layer = Image.new('RGBA', self.original_background.size, (0, 0, 0, 0))

            self.show_page()

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

        # Store the new point in image space for the next segment
        self.old_x = ix
        self.old_y = iy
    
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
        # IMPORTANT: We do NOT delete the 'paint' canvas items here.
        # They remain on the canvas so the user can still right-click them to label/name regions
        # (this restores the labeling feature that was broken by the zoom refactor).
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()

    def name_painted_region(self, event):
        """Right-click on a paint stroke to name the entire connected boundary.

        All line segments belonging to the same continuous stroke (mouse-down to mouse-up)
        are treated as one structural region and colored yellow together.

        Fixed to use proper canvas coordinates so labeling works after zoom.
        """
        # Convert to canvas coordinates (critical after zoom + scrolling)
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)

        # Tolerance in screen pixels; keep it reasonable even after zoom
        tolerance = 12
        candidates = self.output.find_overlapping(cx - tolerance, cy - tolerance,
                                                  cx + tolerance, cy + tolerance)

        paint_items = [item for item in candidates if 'paint' in self.output.gettags(item)]
        if not paint_items:
            return

        clicked_item = paint_items[0]
        tags = self.output.gettags(clicked_item)

        # Find which group this segment belongs to
        group_tag = None
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
            for item in all_segments:
                self.output.itemconfig(item, fill=self.DEFAULT_COLOR)
            return

        self.named_paint_groups[group_tag] = name

        # Keep the whole group yellow to show it's a named structural boundary
        for item in all_segments:
            self.output.itemconfig(item, fill='#ffcc00')

        logger.info(f"Named paint group {group_tag} as '{name}' ({len(all_segments)} segments)")

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

        for line in paint_items:
            coords = self.output.coords(line)
            if not coords:
                continue

            # Convert canvas coords to image (model) coordinates
            points = []
            for i in range(0, len(coords), 2):
                cx = coords[i]
                cy = coords[i + 1]
                ix = int(cx / self.view_scale)
                iy = int(cy / self.view_scale)
                points.append((ix, iy))

            if len(points) < 2:
                continue

            width = self.output.itemcget(line, 'width')
            try:
                width = int(float(width))
            except Exception:
                width = 3

            fill = self.output.itemcget(line, 'fill')

            radius = max(1, width // 2)
            for px, py in points:
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
            draw.line(points, fill=fill, width=width, joint="curve")

    def _convert_named_paints_to_zones(self):
        """Convert named paint *groups* (connected strokes) into zone entries.

        Each named group (one continuous drawing action) gets a single zone_id,
        so the entire structural boundary is treated as one region for cell counting.
        """
        if not self.named_paint_groups:
            return

        if self.current_page not in self.zone_counters:
            self.zone_counters[self.current_page] = 0
        if self.current_page not in self.zone_names:
            self.zone_names[self.current_page] = {}

        # Determine target size for the zone mask
        if self.original_background is not None:
            target_size = self.original_background.size
        elif self.background_image is not None:
            target_size = self.background_image.size
        else:
            return

        # Get or create the zone mask for this page
        if self.current_page not in self.mask_images:
            self.mask_images[self.current_page] = Image.new('L', target_size, 0)

        mask_img = self.mask_images[self.current_page].copy()
        draw = ImageDraw.Draw(mask_img)

        for group_tag, name in list(self.named_paint_groups.items()):
            segments = self.output.find_withtag(group_tag)
            if not segments:
                continue

            # One zone id for the entire connected group
            self.zone_counters[self.current_page] += 1
            zone_id = self.zone_counters[self.current_page]

            if name is None or not str(name).strip():
                clean_name = f"Painted Region {zone_id}"
            else:
                clean_name = str(name).strip() or f"Painted Region {zone_id}"

            self.zone_names[self.current_page][zone_id] = clean_name
            # Update the groups dict too for consistency
            self.named_paint_groups[group_tag] = clean_name

            # Draw every segment belonging to this group using the same zone_id
            for item_id in segments:
                try:
                    coords = self.output.coords(item_id)
                    if not coords or len(coords) < 4:
                        continue

                    width = self.output.itemcget(item_id, 'width')
                    try:
                        width = int(float(width))
                    except Exception:
                        width = 3

                    # Convert canvas coords → image coords, properly accounting for current zoom scale
                    # This ensures painted named regions get correct zone pixels in the mask even after zooming.
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
                    logger.error(f"Failed to rasterize segment in group {group_tag}: {e}")

            logger.info(f"Converted named paint group '{clean_name}' ({group_tag}) → zone {zone_id}")

        # Update the mask
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

            logger.info(f"Force-converted paint group '{group_tag}' → zone {zone_id} ('{default_name}')")

        self.mask_images[self.current_page] = mask_img

    def show_brush_settings(self): # This is the layout to be applied to all other spawned windows
        brush_win = None
        window = brush_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", self.disable_event)
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
        window.protocol("WM_DELETE_WINDOW", self.disable_event)
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
        window.protocol("WM_DELETE_WINDOW", self.disable_event)
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
        window.protocol("WM_DELETE_WINDOW", self.disable_event)
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

        # Smart Local Agent button (fully offline, no data leaves the computer)
        ttk.Button(control_frame, text="Smart Suggest (Offline)", 
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
        logger.info("Stopped mask edit mode")
        messagebox.showinfo("Mask Editing", "Mask edits applied. You can now re-count cells.")

    # ==================================================================
    # OFFLINE SMART SUGGEST AGENT (Fully local, no data leaves computer)
    # ==================================================================

    def _analyze_current_detection(self):
        """
        Fully local analysis of the current image and detection result.
        Returns useful statistics and suggestions for blob parameters.
        Everything runs on the user's machine.
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
        """Shows suggestions from the fully local offline agent."""
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
        dialog.title("Smart Suggest (Fully Offline)")
        dialog.geometry("620x480")

        ttk.Label(dialog, text="Local Analysis (no data leaves your computer)", font=("Helvetica", 11, "bold")).pack(pady=8)

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
        """Open the polished PDF user manual (replaces the old weak in-app text help)."""
        # The manual lives in the repository root, one level above the Application/ directory
        manual_path = os.path.join(os.path.dirname(__file__), "..", "BARCC_User_Manual.pdf")
        try:
            os.startfile(os.path.normpath(manual_path))
        except Exception as e:
            messagebox.showerror("Error Opening Manual", f"Could not open the user manual:\n{e}")

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
                "version": "8.01.000",
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
        """
        class ProgressDialog:
            def __init__(self, parent, title):
                self.window = Toplevel(parent)
                self.window.title(title)
                self.window.attributes('-topmost', True)
                self.window.resizable(False, False)
                self.window.protocol("WM_DELETE_WINDOW", lambda: None)

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

            def set_progress(self, percent, message=None):
                self.progress['value'] = max(0, min(100, percent))
                if message:
                    self.label.config(text=message)
                self.window.update_idletasks()

            def close(self):
                try:
                    self.window.destroy()
                except:
                    pass

        dialog = ProgressDialog(self.master, title)
        self._register_transparent_window(dialog.window)
        return dialog

    def save_state(self):
        self.state_manager.save_state(self)

    def _undo_event(self, event=None):
        self.state_manager.undo(self)

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
        self.output.scale('paint', cx, cy, factor, factor)

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
        elif getattr(self, 'auto_mask', None) is not None:
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

    def load_page_image(self):
        if self.atlas_filetype: 
            if self.current_page not in self.page_images:
                if self.atlas_filetype == 'pdf':
                    img = self.pdf_handler.render_page(self.current_page, self.zoom)
                else:
                    img = self.img
                logger.debug(f"Creating new page image: mode={img.mode}, size={img.size}")
                self.page_images[self.current_page] = img
                self.mask_images[self.current_page] = Image.new('L', (img.width, img.height), 0)
                self.zone_counters[self.current_page] = 0
                self.zone_names[self.current_page] = {}
            
            current_img = self.page_images[self.current_page]
            logger.debug(f"Loaded page image: mode={current_img.mode}, size={current_img.size}")
            return current_img

    def show_page(self, mask=None):
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
                zone_data = self.last_df.set_index('Zone')['Cell_Count'].to_dict() if 'Zone' in self.last_df.columns else {}

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
                    screen_x = cx * scale + display_img_x
                    screen_y = cy * scale + display_img_y

                    label_text = f"{zone_name}\n({count})"
                    self.output.create_text(screen_x, screen_y, text=label_text, fill="yellow",
                                            font=("Helvetica", 10, "bold"), anchor="center",
                                            tags="zone_label")
            except Exception as e:
                logger.warning(f"Failed to draw zone labels: {e}")

        # Update scroll region
        self.output.config(scrollregion=self.output.bbox(tk.ALL))


    def img_white_to_transparent(self, img):
        img_array = np.array(img)
        white_mask = np.all(img_array[:, :, :3] >= 250, axis=-1)
        img_array[white_mask, 3] = 0
        img = Image.fromarray(img_array)
        return img

    def open_file(self):
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
            self.zone_counters = {}
            self.zone_names = {}
            clear_preprocess_cache()
            self.show_page()

    def import_tiff(self):
        logger.info("Opening file dialog for TIFF selection")
        self.named_paint_groups.clear()
        self.current_paint_group = None
        self.view_scale = 1.0
        self.img_x = 0
        self.img_y = 0

        # Reset zone/mask state for pure TIFF workflows so painted regions work cleanly
        if self.current_page is None:
            self.current_page = 0
        self.mask_images.pop(self.current_page, None)
        self.zone_names.pop(self.current_page, None)
        self.zone_counters.pop(self.current_page, None)

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
        """Scan the current directory for .tif / .tiff files and update the Treeview with counted status."""
        if not self.current_tiff_directory or not os.path.isdir(self.current_tiff_directory):
            return

        self.tiff_file_list = []
        self._tree_iid_to_path = {}

        try:
            files = os.listdir(self.current_tiff_directory)
            tiff_files = [f for f in files if f.lower().endswith(('.tif', '.tiff'))]
            tiff_files.sort()

            self.tiff_file_list = [os.path.join(self.current_tiff_directory, f) for f in tiff_files]

            # Clear and repopulate Treeview
            if hasattr(self, 'tiff_tree'):
                for item in self.tiff_tree.get_children():
                    self.tiff_tree.delete(item)

                for full_path in self.tiff_file_list:
                    filename = os.path.basename(full_path)
                    has_csv = self._has_matching_csv(full_path)
                    status = "✓" if has_csv else ""

                    iid = self.tiff_tree.insert("", "end", values=(filename, status))
                    self._tree_iid_to_path[iid] = full_path

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
        """Load the TIFF file that was double-clicked in the file browser Treeview."""
        if not hasattr(self, 'tiff_tree'):
            return

        selection = self.tiff_tree.selection()
        if not selection:
            return

        iid = selection[0]
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
        self.tiff_tree.column("#0", width=0, stretch=False)  # Hide the tree column
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

        # Reset zone/mask state for clean paint-based workflows
        if self.current_page is None:
            self.current_page = 0
        self.mask_images.pop(self.current_page, None)
        self.zone_names.pop(self.current_page, None)
        self.zone_counters.pop(self.current_page, None)

        # Reset state similar to import_tiff
        self.named_paint_groups.clear()
        self.current_paint_group = None
        self.view_scale = 1.0
        self.img_x = 0
        self.img_y = 0

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
        if self.crop_mode:
            self.output.bind("<Button-1>", self.crop_start)
            self.output.bind("<B1-Motion>", self.crop_drag)
            self.output.bind("<ButtonRelease-1>", self.crop_end)
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")
            self.output.unbind("<ButtonRelease-1>")
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
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        right = max(self.start_x, end_x)
        bottom = max(self.start_y, end_y)
        img = self.load_page_image()
        cropped_img = img.crop((left, top, right, bottom))
        cropped_img = self.img_white_to_transparent(cropped_img)
        self.page_images[self.current_page] = cropped_img
        mask_img = self.mask_images[self.current_page]
        cropped_mask = mask_img.crop((left, top, right, bottom))
        self.mask_images[self.current_page] = cropped_mask
        clear_preprocess_cache()
        self.show_page()
        self.toggle_crop_mode()
        if not self.count_button_packed:
            self.count_button.pack(side=tk.LEFT, padx=10, pady=10)
            self.count_button_packed = True

    def toggle_edit_mode(self):
        self.save_state()
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            self.output.bind("<Button-1>", self.drag_start)
            self.output.bind("<B1-Motion>", self.drag_move)
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")

    def drag_start(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag_move(self, event):
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
            img = self.page_images[self.current_page]
            rotated = img.rotate(degrees, expand=True)
            self.page_images[self.current_page] = rotated
            mask_img = self.mask_images[self.current_page]
            rotated_mask = mask_img.rotate(degrees, expand=True, resample=Image.NEAREST)
            self.mask_images[self.current_page] = rotated_mask
            clear_preprocess_cache()
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for rotation degrees.")

    def resize_custom(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            img = self.page_images[self.current_page]
            new_size = (int(img.width * scale), int(img.height * scale))
            resized = img.resize(new_size, Image.BILINEAR)
            self.page_images[self.current_page] = resized
            mask_img = self.mask_images[self.current_page]
            resized_mask = mask_img.resize(new_size, Image.NEAREST)
            self.mask_images[self.current_page] = resized_mask
            clear_preprocess_cache()
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def resize_x(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            img = self.page_images[self.current_page]
            new_size = (int(img.width * scale), img.height)
            resized = img.resize(new_size, Image.BILINEAR)
            self.page_images[self.current_page] = resized
            mask_img = self.mask_images[self.current_page]
            resized_mask = mask_img.resize(new_size, Image.NEAREST)
            self.mask_images[self.current_page] = resized_mask
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def resize_y(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            img = self.page_images[self.current_page]
            new_size = (img.width, int(img.height * scale))
            resized = img.resize(new_size, Image.BILINEAR)
            self.page_images[self.current_page] = resized
            mask_img = self.mask_images[self.current_page]
            resized_mask = mask_img.resize(new_size, Image.NEAREST)
            self.mask_images[self.current_page] = resized_mask
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def highlight_region(self, event):
        logger.debug(f"Highlighting region at ({event.x}, {event.y})")
        self.save_state()
        if not self.atlas_filetype or self.crop_mode or self.edit_mode:
            logger.debug("Highlight region aborted: atlas_filetype=%s, crop_mode=%s, edit_mode=%s", 
                      self.atlas_filetype, self.crop_mode, self.edit_mode)
            return

        canvas_x = self.output.canvasx(event.x)
        canvas_y = self.output.canvasy(event.y)
        x, y = int(canvas_x - self.img_x), int(canvas_y - self.img_y)  # convert to atlas-local coordinates

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

        img_array = np.array(img)
        overlay = img_array.copy()
        overlay[..., :3][mask] = [255, 255, 0]
        overlay[..., 3][mask] = 18
        updated_img = Image.fromarray(overlay).convert('RGBA')
        self.page_images[self.current_page] = updated_img
        self.show_page()

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

        # Robust fallback for painted regions:
        # Always convert any remaining paint strokes into zones when Count Cells is pressed.
        # This ensures that zones drawn with the Paint tool are respected even if the user
        # previously loaded an atlas or has mask_images entries for the current page.
        remaining_paint = self.output.find_withtag('paint')
        if remaining_paint:
            self._force_paint_strokes_to_zones(remaining_paint)
            # Clean up the visual paint strokes now that they've been turned into zones
            self.output.delete('paint')

        if self.current_page not in self.mask_images:
            # One last attempt: if there are still paint items, force convert them
            remaining = self.output.find_withtag('paint')
            if remaining:
                self._force_paint_strokes_to_zones(remaining)
                self.output.delete('paint')

            if self.current_page not in self.mask_images:
                logger.warning("Cell counting failed: No regions defined")
                messagebox.showerror(
                    "No Regions Defined",
                    "No regions (zones) have been defined for this page.\n\n"
                    "Please either:\n"
                    "• Load an atlas and click on regions to define them, or\n"
                    "• Use the Paint tools to draw regions (right-click strokes to name them, or let Count Cells auto-name them)."
                )
                return

        # Guard: if there are still no zones defined for this page after auto-stopping paint,
        # give a clear message instead of generating an empty spreadsheet.
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

        # === Automatic saving of results (new in 8.01) ===
        base_name = self.tiff_filename
        tiff_dir = self.tiff_dir

        # 1. Save Excel file with two sheets (Counts + Detection Parameters)
        xlsx_path = os.path.join(tiff_dir, f"{base_name}.xlsx")
        excel_saved = False

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
            csv_path = os.path.join(tiff_dir, f"{base_name}.csv")
            df.to_csv(csv_path, index=False)
            messagebox.showwarning(
                "Excel Export Failed",
                f"Could not save as Excel (openpyxl or xlsxwriter not installed).\n"
                f"Fell back to CSV:\n{csv_path}\n\n"
                f"To enable .xlsx output with metadata sheet, run:\n"
                f"pip install openpyxl xlsxwriter"
            )

        # 2. Automatically save the mask as a flattened overlay on the original image
        try:
            orig = self.original_background.convert('RGBA')

            # Resize final cell mask to full resolution
            mask_full = final_cell_mask
            mask_resized = Image.fromarray((mask_full * 255).astype(np.uint8)).resize(orig.size, Image.NEAREST)

            # Create semi-transparent red overlay
            overlay = Image.new('RGBA', orig.size, (0, 0, 0, 0))
            red_layer = Image.new('RGBA', orig.size, (255, 0, 0, 110))
            overlay.paste(red_layer, mask=mask_resized)

            masked_img = Image.alpha_composite(orig, overlay)

            masked_path = os.path.join(tiff_dir, f"{base_name}_masked.tif")
            masked_img.save(masked_path, compression='tiff_deflate')

            logger.info(f"Masked image saved: {masked_path}")
        except Exception as e:
            logger.error(f"Failed to save _masked.tif: {e}")

        if progress:
            progress.set_progress(100, "Done")
            progress.close()

        # Refresh file browser so the "counted" indicator updates
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
        if progress:
            progress.set_progress(70, "Combining manual edits...")
        combined_mask = (auto_mask | add_mask) & ~remove_mask

        # Visualize combined mask on top of the original background
        if progress:
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

        if progress:
            progress.set_progress(95, "Displaying mask...")
        self.show_page(mask=mask_img)

        if progress:
            progress.set_progress(100, "Done")
            progress.close()

    
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
        self.zone_counters = {}
        self.zone_names = {}
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
        self.auto_mask = False 

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

        # Last DF for counts
        self.last_df = None

        # Brightness
        self.brightness = 0.0

        # Mouse state tracking
        self.current_state = None

        self.show_page()
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
        binary = np.array(page_pil) #> 0

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

    counts = {}
    max_zone = max(zone_counters.values()) if zone_counters else 0
    for i in range(1, max_zone + 1):
        counts[i] = 0
    filtered_props = []

    # Filter props based on mask and count per zone
    mask_arr = np.array(mask_pil)
    for prop in props:
        row, col = prop.centroid
        ax = int(col - img_x)
        ay = int(row - img_y)
        if 0 <= ax < mask_pil.width and 0 <= ay < mask_pil.height:
            zone_id = mask_arr[ay, ax]
            if zone_id > 0:
                counts.setdefault(zone_id, 0)
                counts[zone_id] += 1
                filtered_props.append(prop)

    # Enhanced visualization
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
        rgb_img[y_start:y_end, x_pos] = [255, 0, 0]
        
        # Draw horizontal line
        x_start = max(0, x - marker_size)
        x_end = min(rgb_img.shape[1] - 1, x + marker_size + 1)
        y_pos = min(max(0, y), rgb_img.shape[0] - 1)
        rgb_img[y_pos, x_start:x_end] = [255, 0, 0]

    # Convert to PIL Image
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
    def __init__(self):
        self.undo_stack = []

    def save_state(self, viewer):
        """Save the current state for undo functionality"""
        state = {
            "current_page": viewer.current_page,
            "img_x": viewer.img_x,
            "img_y": viewer.img_y,
            "zoom": viewer.zoom,
            "zone_counters": copy.deepcopy(viewer.zone_counters),
            "zone_names": copy.deepcopy(viewer.zone_names),
        }
        self.undo_stack.append(state)
        logger.debug("Saved state to undo stack")

    def undo(self, viewer):
        """Restore the previous state"""
        if not self.undo_stack:
            logger.debug("No states to undo")
            return
        
        state = self.undo_stack.pop()
        viewer.current_page = state["current_page"]
        viewer.img_x = state["img_x"]
        viewer.img_y = state["img_y"]
        viewer.zoom = state["zoom"]
        viewer.zone_counters = state["zone_counters"]
        viewer.zone_names = state["zone_names"]
        viewer.show_page()
        logger.debug("Restored previous state")

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
        closed_binary = binary_closing(mag_binary)

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
