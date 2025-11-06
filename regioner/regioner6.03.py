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

import pandas as pd
import os
import io
import logging
import yaml
import sys

# Configure logging
logging.basicConfig(
    # level=logging.INFO,       # For normal operations and major steps
    # level=logging.WARNING,    # For recoverable errors
    level=logging.DEBUG,        # For detailed operational information
    # level=logging.ERROR,      # For critical issues
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define configuration dataclasses and enums
class ThresholdMethod(enum.Enum):
    OTSU = "otsu"
    ADAPTIVE = "adaptive"
    LOCAL = "local"
    MANUAL = "manual"

@dataclass
class CellDetectionConfig:
    threshold_method: ThresholdMethod = ThresholdMethod.OTSU
    manual_threshold: float = 0.5
    adaptive_block_size: int = 101
    local_radius: int = 15
    min_cell_size: int = 20
    max_cell_size: int = 100
    circularity_threshold: float = 0.7
    min_peak_distance: int = 5
    peak_min_intensity: float = 0.1
    watershed_compactness: float = 0.0
    base_multiplier: float = 1.1
    sensitivity_range: float = 0.2

@dataclass
class PreprocessingConfig:
    background_method: str = "tophat"  # Changed to tophat as default
    # Background correction methods
    ball_radius: int = 15        # Reduced radius for efficiency
    # Noise reduction
    denoise_method: str = "gaussian"
    gaussian_sigma: float = 1.0
    median_kernel: int = 3
    bilateral_sigma_color: float = 0.1
    bilateral_sigma_space: float = 1.0
    # Contrast enhancement
    contrast_method: str = "stretch"
    clahe_kernel: int = 8
    clahe_clip_limit: float = 2.0
    gamma: float = 1.0
    # Signal enhancement
    enhance_method: str = "unsharp_mask"
    unsharp_radius: float = 1.0
    unsharp_amount: float = 2.0

class ImageProcessor:
    def __init__(self):
        self.cell_config = CellDetectionConfig()
        self.preprocess_config = PreprocessingConfig()
        self.load_config()

    def load_config(self):
        """Load configuration from file if it exists"""
        config_path = "regioner_config.yaml"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                try:
                    config = yaml.safe_load(f)
                    if 'cell_detection' in config:
                        cell_config = config['cell_detection']
                        # Handle threshold_method specially
                        if 'threshold_method' in cell_config:
                            threshold_value = cell_config['threshold_method']
                            cell_config['threshold_method'] = ThresholdMethod(threshold_value)
                        
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
            cell_config_dict['threshold_method'] = self.cell_config.threshold_method.value
            
            config = {
                'cell_detection': cell_config_dict,
                'preprocessing': self.preprocess_config.__dict__
            }
            with open("regioner_config.yaml", 'w') as f:
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
                from skimage.morphology import white_tophat, disk
                selem = disk(15)  # Using a smaller fixed radius for efficiency
                img = white_tophat(img, selem)
                logger.debug("White tophat transform completed successfully")
            elif self.preprocess_config.background_method == "none":
                logger.debug("Skipping background correction")
                pass  # No background correction
            else:
                logger.debug("Using default background subtraction")
                # Simple background estimation using gaussian blur
                from scipy.ndimage import gaussian_filter
                background = gaussian_filter(img, sigma=50)
                img = img - background
                img = np.clip(img, 0, 1)  # Normalize to [0,1] range
        except Exception as e:
            logger.error(f"Error in background correction: {str(e)}")
            # Fall back to no background correction
            logger.info("Falling back to no background correction")
            pass

        # Noise reduction
        if self.preprocess_config.denoise_method == "gaussian":
            logger.debug("Applying Gaussian noise reduction")
            img = filters.gaussian(img, sigma=self.preprocess_config.gaussian_sigma)
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

        # Signal enhancement
        if self.preprocess_config.enhance_method == "unsharp_mask":
            logger.debug("Applying unsharp mask")
            img = filters.unsharp_mask(
                img,
                radius=self.preprocess_config.unsharp_radius,
                amount=self.preprocess_config.unsharp_amount
            )

        return img

    def detect_cells(self, image, sensitivity):
        """Detect cells using current configuration"""
        logger.debug(f"Starting cell detection with sensitivity {sensitivity}")
        
        # Preprocess the image
        img = self.preprocess_image(image)
        
        # Apply thresholding based on method
        logger.debug(f"Applying {self.cell_config.threshold_method.value} thresholding")
        if self.cell_config.threshold_method == ThresholdMethod.OTSU:
            # Standard Otsu thresholding
            thresh = filters.threshold_otsu(img)
        elif self.cell_config.threshold_method == ThresholdMethod.ADAPTIVE:
            # Use a larger block size for better cell detection
            thresh = filters.threshold_local(
                img,
                block_size=self.cell_config.adaptive_block_size
            )
        elif self.cell_config.threshold_method == ThresholdMethod.LOCAL:
            # Simple local thresholding
            thresh = filters.threshold_local(
                img,
                block_size=self.cell_config.local_radius * 2 + 1,
                method='gaussian'
            )
        else:  # MANUAL
            thresh = self.cell_config.manual_threshold

        # Apply sensitivity adjustment
        sensitivity_multiplier = (
            self.cell_config.base_multiplier -
            (sensitivity / 100.0) * self.cell_config.sensitivity_range
        )
        logger.debug(f"Sensitivity multiplier: {sensitivity_multiplier}")

        binary = img > (thresh * sensitivity_multiplier) if isinstance(thresh, np.ndarray) else img > (thresh * sensitivity_multiplier)

        # Size and shape filtering
        labeled = measure.label(binary)
        props = measure.regionprops(labeled)

        # Filter by size and circularity
        mask = np.zeros_like(binary)
        for prop in props:
            if (self.cell_config.min_cell_size <= prop.area <= self.cell_config.max_cell_size and
                prop.perimeter**2 / (4 * np.pi * prop.area) <= 1/self.cell_config.circularity_threshold):
                mask[tuple(prop.coords.T)] = True

        # Watershed segmentation for touching cells
        distance = distance_transform_edt(mask)
        coords = feature.peak_local_max(
            distance,
            min_distance=self.cell_config.min_peak_distance,
            threshold_abs=self.cell_config.peak_min_intensity,
            exclude_border=True
        )
        
        markers = np.zeros_like(distance, dtype=bool)
        markers[tuple(coords.T)] = True
        markers = measure.label(markers)

        labels = segmentation.watershed(
            -distance,
            markers,
            mask=mask,
            compactness=self.cell_config.watershed_compactness
        )

        return img, labels

def clear_preprocess_cache():
    _PREPROCESS_CACHE.clear()

def binary_mask_cell_count(background_pil, sensitivity):
    """Enhanced cell detection using ImageProcessor class"""
    processor = ImageProcessor()
    img, labels = processor.detect_cells(background_pil, sensitivity)
    return img, labels > 0

class PDFViewer:
    def __init__(self):
        logger.info("Initializing PDFViewer")
        self.root = tk.Tk()
        self.master = self.root
        self.master.bind('<q>', self.quit)
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
        self.DEFAULT_PEN_SIZE = 3.0
        self.DEFAULT_COLOR = 'black'

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

        # Last DF for counts
        self.last_df = None

        # Brightness
        self.brightness = 0.0

        # Build GUI
        self._build_gui()

        self.root.mainloop()

    def quit(self, master):
        self.master.destroy()

    def _build_gui(self):
        # Menu
        self.menu = tk.Menu(self.master)
        self.master.config(menu=self.menu)

        # Create File menu dropdown
        filemenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="Import Atlas Section", command=self.open_file)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_command(label="Help", command=self.show_help)
        filemenu.add_command(label="Exit", command=self.master.destroy)

        # Create Edit menu dropdown
        editmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Edit", menu=editmenu)
            # Put misc/visual things in here (brightness, save pictures, save paint)

        # Create Atlas menu dropdown
        atlasmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Atlas", menu=atlasmenu)
            # Put all atlas manipulation functions in here (crop, move, rotate, scale)
        
        self.menu.add_separator()
        # Create Paint menu dropdown
        paintmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Paint", menu=paintmenu)
            # All paint functions (start, stop, pen, eraser, brushsize)
        
        # Create Mask menu dropdown
        maskmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Mask", menu=maskmenu)
            # All mask functions (mask settings, show mask, add cell, remove cell, finish mask edit)

        # Create Cell menu dropdown
        cellmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Cell", menu=cellmenu)
            # This might turn into a command that counts the cells
        

        # Frames
        self.top_frame = ttk.Frame(self.master)
        self.top_frame.grid(row=0, column=0, sticky='nsew')
        self.top_frame.rowconfigure(0, weight=1)
        self.top_frame.columnconfigure(0, weight=1)

        self.bottom_frame = ttk.Frame(self.master)
        self.bottom_frame.grid(row=1, column=0, sticky='ew')

        self.right_frame = ttk.Frame(self.master)
        self.right_frame.grid(row=0, column=2, sticky='nsw')

        # Scrollbars and canvas
        self.scrolly = ttk.Scrollbar(self.top_frame, orient=tk.VERTICAL)
        self.scrolly.grid(row=0, column=1, sticky='ns')
        self.scrollx = ttk.Scrollbar(self.top_frame, orient=tk.HORIZONTAL)
        self.scrollx.grid(row=1, column=0, sticky='ew')

        self.output = tk.Canvas(self.top_frame, bg='#ECE8F3')
        self.output.configure(yscrollcommand=self.scrolly.set, xscrollcommand=self.scrollx.set)
        self.output.grid(row=0, column=0, sticky='nsew')
        self.scrolly.configure(command=self.output.yview)
        self.scrollx.configure(command=self.output.xview)

        # Paint tools
        self.pen_button = tk.Button(self.right_frame, text='pen', command=self.use_pen)
        self.pen_button.grid(row=0, column=0, pady=5)

        self.eraser_button = tk.Button(self.right_frame, text='eraser', command=self.use_eraser)
        self.eraser_button.grid(row=1, column=0, pady=5)

        self.choose_size_button = tk.Scale(self.right_frame, from_=1, to=10, orient=tk.HORIZONTAL)
        self.choose_size_button.set(self.DEFAULT_PEN_SIZE)
        self.choose_size_button.grid(row=2, column=0, pady=5)

        # Bind click event for highlighting
        self.output.bind("<Button-1>", self.highlight_region)

        # Control buttons
        self._build_control_buttons()
        
        # Keyboard shortcuts
        self.master.bind('<Control-z>', self._undo_event)
        self.master.bind('<Control-s>', self.save_flattened_image)

        # Paint buttons
        ttk.Button(self.right_frame, text="Start Paint", command=self.start_paint).grid(row=3, column=0, pady=5)
        ttk.Button(self.right_frame, text="Stop Paint", command=self.stop_paint).grid(row=4, column=0, pady=5)
        ttk.Button(self.right_frame, text="Show Mask", command=self.show_cell_mask_threshold).grid(row=5, column=0, pady=5)
        ttk.Button(self.right_frame, text="Show Mask Settings", command=self.show_mask_settings).grid(row=6, column=0, pady=5)

        # Next Image and Count Cell buttons
        ttk.Button(self.right_frame, text="Next Image", command=self.next_image).grid(row=7, padx=8, pady=8)
        self.count_button = ttk.Button(self.right_frame, text="Count Cells", command=self.count_cells)
        self.count_button.grid(row=8, padx=10, pady=10)
        self.count_button_packed = True

        # Mask editing buttons
        ttk.Button(self.right_frame, text="Add Cells", command=self.start_add_cells).grid(row=9, padx=8, pady=4)
        ttk.Button(self.right_frame, text="Remove Cells", command=self.start_remove_cells).grid(row=10, padx=8, pady=4)
        ttk.Button(self.right_frame, text="Finish Mask Edit", command=self.stop_mask_edit).grid(row=11, padx=8, pady=4)

    def _build_control_buttons(self):
        # Crop Button
        self.crop_button = ttk.Button(self.bottom_frame, text="Crop", command=self.toggle_crop_mode)
        self.crop_button.pack(side=tk.LEFT, padx=8, pady=8)
        
        # Atlas Button
        self.style = ttk.Style()
        self.style.configure('On.TButton', background='lightgreen')
        self.move_button = ttk.Button(self.bottom_frame, text="Move Atlas", command=self.toggle_edit_mode)
        self.move_button.pack(side=tk.LEFT, padx=10, pady=10)

        # Import Tiff button
        ttk.Button(self.bottom_frame, text="Import TIFF", command=self.import_tiff).pack(side=tk.LEFT, padx=10, pady=10)

        # Rotation controls
        self.rotation_label = ttk.Label(self.bottom_frame, text="Rotate (degrees):")
        self.rotation_label.pack(side=tk.LEFT, padx=10, pady=10)
        self.rotation_entry = ttk.Entry(self.bottom_frame, width=10)
        self.rotation_entry.pack(side=tk.LEFT, padx=5, pady=10)
        ttk.Button(self.bottom_frame, text="Rotate", command=self.rotate_custom).pack(side=tk.LEFT, padx=10, pady=10)

        # Scale controls
        self.scale_label = ttk.Label(self.bottom_frame, text="Scale:")
        self.scale_label.pack(side=tk.LEFT, padx=10, pady=10)
        self.scale_entry = ttk.Entry(self.bottom_frame, width=10)
        self.scale_entry.pack(side=tk.LEFT, padx=5, pady=10)

        # Resize buttons
        ttk.Button(self.bottom_frame, text="Resize", command=self.resize_custom).pack(side=tk.LEFT, padx=8, pady=8)
        ttk.Button(self.bottom_frame, text="Resize X", command=self.resize_x).pack(side=tk.LEFT, padx=8, pady=8)
        ttk.Button(self.bottom_frame, text="Resize Y", command=self.resize_y).pack(side=tk.LEFT, padx=8, pady=8)

        # Brightness and sensitivity controls
        self._build_adjustment_controls()




    def _build_adjustment_controls(self):
        # Brightness slider
        self.brightness_label = ttk.Label(self.bottom_frame, text="Brightness:")
        self.brightness_label.pack(side=tk.LEFT, padx=8, pady=8)
        self.brightness_slider = ttk.Scale(self.bottom_frame, from_=-100, to=400, orient=tk.HORIZONTAL, command=self.update_brightness)
        self.brightness_slider.pack(side=tk.LEFT, padx=4, pady=8)
        self.brightness_slider.set(0)

        # Sensitivity slider
        self.sensitivity_label = ttk.Label(self.bottom_frame, text="Sensitivity:")
        self.sensitivity_label.pack(side=tk.LEFT, padx=8, pady=8)
        self.sensitivity_var = tk.IntVar(value=50)
        self.sensitivity_slider = tk.Scale(self.bottom_frame, from_=0, to=100, orient=tk.HORIZONTAL, variable=self.sensitivity_var)
        self.sensitivity_slider.pack(side=tk.LEFT, padx=4, pady=8)
        self.sensitivity_value_entry = ttk.Entry(self.bottom_frame, textvariable=self.sensitivity_var, width=4)
        self.sensitivity_value_entry.pack(side=tk.LEFT, padx=4, pady=8)

    def start_paint(self):
        self.old_x = None
        self.old_y = None
        self.line_width = self.choose_size_button.get()
        self.color = self.DEFAULT_COLOR
        self.active_button = self.pen_button
        self.use_pen()
        self.output.unbind("<Button-1>")
        self.output.bind('<B1-Motion>', self.paint)
        self.output.bind('<ButtonRelease-1>', self.reset)

    def stop_paint(self):
        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>') 
        self.output.bind('<Button-1>', self.highlight_region)
        self.save_paint()
        self.show_page()

    def save_paint(self):
        """Save canvas paint strokes to an image without using postscript"""
        # Hide background temporarily
        self.output.itemconfig(self.bg_photo_id, state='hidden')
        
        # Get canvas bounds
        bbox = self.output.bbox("paint")  # Get bounds of items tagged with 'paint'
        if not bbox:
            logger.debug("No paint strokes to save")
            return  # No paint to save
            
        # Get coordinates of entire painting area
        x1, y1, x2, y2 = bbox
        # Modify coords so painting stays in the same place after conversion
        x1 = 0
        y1 = 0
        
        # Create a new transparent image
        img = Image.new('RGBA', (x2-x1, y2-y1), (0,0,0,0))
        
        # Draw each paint stroke onto the image
        draw = ImageDraw.Draw(img)
        for item in self.output.find_withtag('paint'):
            coords = self.output.coords(item)
            # Adjust coordinates relative to bbox
            adjusted_coords = [c - x1 if i % 2 == 0 else c - y1 for i, c in enumerate(coords)]
            width = self.output.itemcget(item, 'width')
            fill = self.output.itemcget(item, 'fill')
            draw.line(adjusted_coords, fill=fill, width=int(float(width)))
        
        # Show background again
        self.output.itemconfig(self.bg_photo_id, state='normal')
        
        # Set as current image
        self.img = img
        self.photo = ImageTk.PhotoImage(img)
        self.atlas_filetype = 'img'
        
        # Clear the canvas drawings
        self.output.delete('paint')
        
        logger.debug("Paint strokes saved to image successfully")

    def use_pen(self):
        self.activate_button(self.pen_button)

    def use_eraser(self):
        self.activate_button(self.eraser_button, eraser_mode=True)

    def activate_button(self, some_button, eraser_mode=False):
        self.active_button.config(relief='raised')
        some_button.config(relief='sunken')
        self.active_button = some_button
        self.eraser_on = eraser_mode

    def paint(self, event):
        self.line_width = self.choose_size_button.get()
        paint_color = 'white' if self.eraser_on else self.color
        if self.old_x and self.old_y:
            self.output.create_line(self.old_x, self.old_y, event.x, event.y,
                               width=self.line_width, fill=paint_color,
                               capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36,
                               tags='paint')
        self.old_x = event.x
        self.old_y = event.y

    def reset(self, event):
        self.old_x, self.old_y = None, None

    def show_mask_settings(self):
        settings_win = Toplevel(self.master)
        settings_win.title("Mask Settings")
        # settings_win.geometry("600x800")

        # Configure grid layout
        settings_win.columnconfigure(0, weight=1)
        settings_win.columnconfigure(1, weight=1)

        def save_settings():
            self.image_processor.cell_config.threshold_method = ThresholdMethod(threshold_var.get())
            self.image_processor.save_config()
            settings_win.destroy()

        def load_settings():
            self.image_processor.load_config()
            settings_win.destroy()  # Reopen to refresh values
            self.show_mask_settings()

        # Control buttons at the top
        control_frame = ttk.Frame(settings_win)
        control_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        ttk.Button(control_frame, text="Save", command=save_settings).grid(row=0, column=0, padx=5)
        ttk.Button(control_frame, text="Load", command=load_settings).grid(row=0, column=1, padx=5)

        # Cell Detection Settings in left column
        cell_detect_frame = ttk.LabelFrame(settings_win, text="Cell Detection Settings")
        cell_detect_frame.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        cell_detect_frame.columnconfigure(1, weight=1)

        # Threshold method selector
        ttk.Label(cell_detect_frame, text="Threshold Method:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        threshold_var = tk.StringVar(value=self.image_processor.cell_config.threshold_method.value)
        threshold_menu = ttk.OptionMenu(cell_detect_frame, threshold_var, self.image_processor.cell_config.threshold_method.value,
                                      *[method.value for method in ThresholdMethod])
        threshold_menu.grid(row=0, column=1, sticky='ew', padx=5, pady=5)

        def create_setter(entry_widget, config_obj, attr_name):
            def setter(event):
                val = entry_widget.get()
                try:
                    current_type = type(getattr(config_obj, attr_name))
                    if current_type == int:
                        val = int(val)
                    elif current_type == float:
                        val = float(val)
                    setattr(config_obj, attr_name, val)
                    logger.debug(f"Successfully set {attr_name} to {val}")
                except ValueError as e:
                    logger.error(f"Invalid input for {attr_name}: {e}")
                    messagebox.showerror("Invalid Input", 
                                       f"Please enter a valid {current_type.__name__} for {attr_name}.")
            return setter

        # Cell detection settings
        row = 1
        for attr, value in self.image_processor.cell_config.__dict__.items():
            if attr == 'threshold_method':
                continue  # Skip threshold_method as it's handled separately
            
            ttk.Label(cell_detect_frame, text=f"{attr.replace('_', ' ').title()}:").grid(
                row=row, column=0, sticky='w', padx=5, pady=2)
            
            entry = ttk.Entry(cell_detect_frame)
            entry.insert(0, str(value))
            entry.grid(row=row, column=1, sticky='ew', padx=5, pady=2)
            
            setter = create_setter(entry, self.image_processor.cell_config, attr)
            entry.bind("<FocusOut>", setter)
            entry.bind("<Return>", setter)
            
            row += 1

        # Preprocessing Settings in right column
        preprocess_frame = ttk.LabelFrame(settings_win, text="Preprocessing Settings")
        preprocess_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=5)
        preprocess_frame.columnconfigure(1, weight=1)

        row = 0
        for attr, value in self.image_processor.preprocess_config.__dict__.items():
            ttk.Label(preprocess_frame, text=f"{attr.replace('_', ' ').title()}:").grid(
                row=row, column=0, sticky='w', padx=5, pady=2)
            
            entry = ttk.Entry(preprocess_frame)
            entry.insert(0, str(value))
            entry.grid(row=row, column=1, sticky='ew', padx=5, pady=2)
            
            setter = create_setter(entry, self.image_processor.preprocess_config, attr)
            entry.bind("<FocusOut>", setter)
            entry.bind("<Return>", setter)
            
            row += 1

    def start_add_cells(self):
        """Begin drawing to add cells to the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.start_mask_edit(add=True)

    def start_remove_cells(self):
        """Begin drawing to remove cells from the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.start_mask_edit(add=False)

    def start_mask_edit(self, add=True):
        """Enable mask editing mode"""
        self.editing_mask = True
        self.mask_edit_add = add
        self.output.unbind("<Button-1>")
        self.output.bind("<B1-Motion>", self.edit_mask_draw)
        self.output.bind("<ButtonRelease-1>", self.stop_mask_edit)
        
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



    def edit_mask_draw(self, event):
        """Draw directly on the binary mask"""
        if not self.editing_mask or self.current_mask is None:
            return

        x = int(self.output.canvasx(event.x))
        y = int(self.output.canvasy(event.y))
        r = int(self.choose_size_button.get())

        draw = ImageDraw.Draw(self.current_mask)
        color = 255 if self.mask_edit_add else 0
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

        # --- Visualization fix ---
        mask_arr = np.array(self.current_mask)
        # Make RGB overlay for display
        overlay_rgb = np.zeros((*mask_arr.shape, 3), dtype=np.uint8)
        overlay_rgb[mask_arr > 0] = [255, 0, 0]  # Red overlay where mask is drawn
        overlay_img = Image.fromarray(overlay_rgb)

        self.show_page(mask=overlay_img)


    def stop_mask_edit(self, event=None):
        """Exit mask editing mode"""
        if not self.editing_mask:
            return
        self.editing_mask = False
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.bind("<Button-1>", self.highlight_region)
        logger.info("Stopped mask edit mode")
        messagebox.showinfo("Mask Editing", "Mask edits applied. You can now re-count cells.")




    def update_brightness(self, value):
        self.brightness = float(value)
        self.show_page()

    def adjust_image(self, img):
        enhancer = ImageEnhance.Brightness(img)
        factor = 1 + (self.brightness / 100.0)
        return enhancer.enhance(factor)

    def show_help(self):
        help_win = tk.Toplevel(self.master)
        help_win.title("User Manual")
        help_win.geometry("800x600")

        text = tk.Text(help_win, wrap=tk.WORD)
        text.pack(expand=True, fill=tk.BOTH)
        scrollbar = tk.Scrollbar(help_win, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)

        manual_content = """
        Table of Contents
1. Introduction
2. Importing Files
3. Manipulating the Atlas
4. Highlighting Regions
5. Counting Cells
6. Saving Outputs
7. Hotkeys
8. Undo Functionality

1. Introduction
This GUI is designed for regional analysis of immunofluorescence (IF) images. It allows users to overlay atlas sections on TIFF images, highlight specific regions, count cells within those regions, and export results.

2. Importing Files
- Use "File > Import Atlas Section" to load a PDF atlas file.
- Use the "Import TIFF" button to load a TIFF image file. The image will be resized to fit the window.

3. Manipulating the Atlas
- "Crop": Enables crop mode to select and crop a region of the atlas.
- "Move Atlas": Enables drag mode to move the atlas overlay.
- "Rotate": Enter degrees and click "Rotate" to rotate the atlas.
- "Resize": Enter a scale factor and click "Resize" to scale the atlas.

4. Highlighting Regions
- Click on a region in the atlas to highlight it with a translucent yellow overlay.
- A prompt will appear to name the region (optional).

5. Counting Cells
- After highlighting regions, click "Count Cells" to analyze cells in the highlighted areas.
- Results are saved to an Excel file with region names and cell counts.

6. Saving Outputs
- "File > Save Flattened Image": Saves the combined image and atlas as a JPG.
- Cell count results prompt for an Excel save location.

7. Hotkeys
- Ctrl+Z: Undo the last action.
- Ctrl+S: Save the flattened image.

8. Undo Functionality
- Actions like cropping, moving, rotating, resizing, and highlighting can be undone with Ctrl+Z.
"""
        text.insert(tk.END, manual_content)
        text.config(state=tk.DISABLED)

    def save_state(self):
        self.state_manager.save_state(self)

    def _undo_event(self, event=None):
        self.state_manager.undo(self)

    def load_page_image(self):
        if self.atlas_filetype: 
            if self.current_page not in self.page_images:
                if self.atlas_filetype == 'pdf':
                    img = self.pdf_handler.render_page(self.current_page, self.zoom)
                elif self.atlas_filetype == 'img':
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
        self.photo = ImageTk.PhotoImage(img)
        self.output.delete("all")
        
        if self.background_image:
            # Display original image on the left
            display_bg = self.adjust_image(self.background_image)
            self.background_photo = ImageTk.PhotoImage(display_bg)
            self.bg_photo_id = self.output.create_image(0, 0, 
                                                       image=self.background_photo, 
                                                       anchor='nw')
            
            # If mask exists, display it on the right
            if mask is not None:
                self.mask_photo = ImageTk.PhotoImage(mask)
                offset_x = display_bg.width + 10  # 10 pixels spacing
                self.mask_photo_id = self.output.create_image(offset_x, 0, 
                                                             image=self.mask_photo, 
                                                             anchor='nw')
                
        # Display atlas overlay
        self.output.create_image(self.img_x, self.img_y, 
                               image=self.photo, 
                               anchor='nw')
        
        # Update scroll region to include both images
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
            # estimate zoom so page fits a default area
            page = self.pdf_handler.doc[0]
            pw = page.rect.width
            ph = page.rect.height
            ww = self.output.winfo_width()
            wh = self.output.winfo_height()
            try:
                self.zoom = min(ww / pw, wh / ph)
            except Exception:
                self.zoom = 1.0
            self.current_page = 0
            self.page_images = {}
            self.mask_images = {}
            self.zone_counters = {}
            self.zone_names = {}
            clear_preprocess_cache()
            self.show_page()

    def import_tiff(self):
        logger.info("Opening file dialog for TIFF selection")
        tiff_path = fd.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
        if tiff_path:
            logger.info(f"Opening TIFF file: {tiff_path}")
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
            self.show_page()

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
        base.paste(bg_img, (bg_offset_x, bg_offset_y), bg_img)

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
            self.crop_button.configure(style='On.TButton')
            self.output.bind("<Button-1>", self.crop_start)
            self.output.bind("<B1-Motion>", self.crop_drag)
            self.output.bind("<ButtonRelease-1>", self.crop_end)
        else:
            self.crop_button.configure(style='TButton')
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
            self.move_button.configure(style='On.TButton')
            self.output.bind("<Button-1>", self.drag_start)
            self.output.bind("<B1-Motion>", self.drag_move)
        else:
            self.move_button.configure(style='TButton')
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

        barrier_img = preprocess_for_highlighting(self.current_page, img)
        try:
            seed_value = barrier_img.getpixel((x, y))
            logger.debug(f"Seed value at click point: {seed_value}")
            if seed_value != 255:
                logger.debug("Clicked on a barrier")
                return  # clicked a barrier
        except Exception as e:
            logger.error(f"Error getting pixel value: {e}")
            return

        self.zone_counters[self.current_page] += 1
        zone_id = self.zone_counters[self.current_page]

        barrier_copy = barrier_img.copy()
        ImageDraw.floodfill(barrier_copy, (x, y), zone_id, thresh=0)
        filled = np.array(barrier_copy)
        mask = (filled == zone_id)

        mask_img = self.mask_images[self.current_page]
        mask_array = np.array(mask_img)
        mask_array[mask] = zone_id
        self.mask_images[self.current_page] = Image.fromarray(mask_array)

        name = simpledialog.askstring("Region Name", "Enter a name for this region:")
        name = name.strip() if name else f"Zone {zone_id}"
        self.zone_names[self.current_page][zone_id] = name

        img_array = np.array(img)
        overlay = img_array.copy()
        overlay[..., :3][mask] = [255, 255, 0]
        overlay[..., 3][mask] = 18
        updated_img = Image.fromarray(overlay)
        self.page_images[self.current_page] = updated_img
        self.show_page()

    def count_cells(self):
        logger.info("Starting cell counting process")
        if self.background_image is None:
            logger.warning("Cell counting failed: No TIFF file imported")
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        if self.current_page not in self.mask_images:
            logger.warning("Cell counting failed: No regions selected in atlas")
            messagebox.showerror("Error", "Please load and select regions in the atlas first.")
            return

        # === Build Final Cell Mask ===
        background = self.original_background.convert('L')
        _, auto_labels = binary_mask_cell_count(background, self.sensitivity_slider.get())
        auto_mask = auto_labels > 0  # Boolean array

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


        annotated, df, counts = count_cells_in_zones(
            self.original_background,
            region_mask_pil,
            cell_mask_pil,
            self.img_x,
            self.img_y,
            self.zone_counters,
            self.zone_names.get(self.current_page, {}),
            self.sensitivity_slider.get()
        )

        self.background_image = annotated
        self.last_df = df
        self.show_page()

        save_path = fd.asksaveasfilename(title="Save Excel File", defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if save_path:
            df.to_excel(save_path, index=False)
            messagebox.showinfo("Cell Counts Saved", f"Cell counts per zone saved to: {save_path}")
        else:
            messagebox.showinfo("Cell Counts", f"Cell counts per zone: {dict(zip(df['Zone'], df['Cell_Count']))}")

    def show_cell_mask_threshold(self):
        """Display the combined (auto + manual) mask overlay"""
        background = self.original_background.convert('L')

        # Run automatic detection
        _, auto_labels = binary_mask_cell_count(background, self.sensitivity_slider.get())
        auto_mask = auto_labels > 0

        base_size = background.size
        add_mask = np.zeros(auto_mask.shape, dtype=bool)
        remove_mask = np.zeros(auto_mask.shape, dtype=bool)

        # Load manual add/remove masks if present
        if self.manual_add_mask is not None:
            add_mask_arr = np.array(self.manual_add_mask.resize(base_size, Image.NEAREST))
            add_mask = add_mask_arr > 0
        if self.manual_remove_mask is not None:
            remove_mask_arr = np.array(self.manual_remove_mask.resize(base_size, Image.NEAREST))
            remove_mask = remove_mask_arr > 0

        # Combine automatic and manual edits
        combined_mask = (auto_mask | add_mask) & ~remove_mask

        # Visualize combined mask on top of the original background
        original_rgb = self.original_background.convert('RGB')
        vis_array = np.array(original_rgb)
        red_overlay = np.zeros_like(vis_array)
        red_overlay[combined_mask] = [255, 0, 0]

        alpha = 0.5
        vis_array = ((1 - alpha) * vis_array + alpha * red_overlay).astype(np.uint8)

        mask_img = Image.fromarray(vis_array)
        mask_img = mask_img.resize(self.original_background.size, Image.NEAREST)

        self.show_page(mask=mask_img)

    def next_image(self):
        logger.info("Processing next image")
        if self.tiff_filename is None:
            logger.warning("Next image failed: No TIFF loaded")
            messagebox.showerror("Error", "No TIFF loaded.")
            return

        image_path = f"{self.tiff_filename}_counted.jpg"
        excel_path = f"{self.tiff_filename}_data.xlsx"

        self.autosave_flattened_image(image_path)

        if self.last_df is not None:
            self.last_df.to_excel(excel_path, index=False)

        clear_preprocess_cache()
        self.background_image = None
        self.original_background = None
        self.img = None
        self.atlas_filetype = None
        self.doc = None
        self.page_images = {}
        self.mask_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.last_df = None
        self.img_x = 0
        self.img_y = 0

        self.manual_add_mask = None
        self.manual_remove_mask = None


        self.show_page()
        messagebox.showinfo("Next Image", f"Autosaved image to {image_path}\nAutosaved counts to {excel_path}" if self.last_df is not None else f"Autosaved image to {image_path}")

def count_cells_in_zones(background_pil, mask_pil, page_pil, img_x, img_y, zone_counters, zone_names, sensitivity):
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
    img2d, binary = binary_mask_cell_count(Image.fromarray((background_norm * 255).astype(np.uint8)), sensitivity)

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

def preprocess_for_highlighting(page_id, img):
    """Preprocess an image for region highlighting"""
    if page_id in _PREPROCESS_CACHE:
        return _PREPROCESS_CACHE[page_id]
    
    logger.debug(f"Processing image for highlighting: mode={img.mode}, size={img.size}")
    
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