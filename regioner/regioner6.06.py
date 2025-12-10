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
        config_path = "regioner_config.yaml"
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
        """Detect cells using current configuration"""
        logger.debug(f"Starting cell detection")
        
        # Preprocess the image
        img = self.preprocess_image(image)
        
        # Apply thresholding based on method
        logger.debug(f"Applying {self.cell_config.threshold_method} thresholding")
        if self.cell_config.threshold_method == "otsu":
            # Standard Otsu thresholding
            thresh = filters.threshold_otsu(img)
        elif self.cell_config.threshold_method == "adaptive":
            # Use a larger block size for better cell detection
            thresh = filters.threshold_local(
                img,
                block_size=self.cell_config.adaptive_block_size
            )
        elif self.cell_config.threshold_method == "local":
            # Simple local thresholding
            thresh = filters.threshold_local(
                img,
                block_size=self.cell_config.local_radius * 2 + 1, # CHECK: why do we have magic numbers
                method='gaussian'
            )
        elif self.cell_config.threshold_method == "manual": # MANUAL
            thresh = self.cell_config.manual_threshold
        else:
            logger.error("No valid thresholding method selected, please select a valid method")
            thresh = 0

        binary = img > thresh

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

def binary_mask_cell_count(background_pil):
    """Enhanced cell detection using ImageProcessor class"""
    processor = ImageProcessor()
    img, labels = processor.detect_cells(background_pil)
    return img, labels > 0

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
        filemenu.add_command(label="Import Tiff", command=self.import_tiff)
        filemenu.add_command(label="Import Atlas Section", command=self.open_file)
        filemenu.add_command(label="Import Paint", command=self.open_paint)
        filemenu.add_command(label="Save Paint", command=self.save_paint_to_pdf)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_command(label="Next Image", command=self.next_image)
        filemenu.add_command(label="Help", command=self.show_help)
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

        # Create Cell menu dropdown
        cellmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Cell", menu=cellmenu)
        cellmenu.add_command(label="Count Cells", command=self.count_cells)


        # Add highlight regions button to manually enable this

        # This works as a labeling scheme, but how do I have it update?
        # self.menu.add_command(label="Pen: "+str(self.draw_type.get()))

        # Frames
        self.top_frame = ttk.Frame(self.master)
        self.top_frame.grid(row=0, column=0, sticky='nsew')
        self.top_frame.rowconfigure(0, weight=1)
        self.top_frame.columnconfigure(0, weight=1)

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

    # End of UI, beginning of functions
    def start_paint(self):
        if self.current_state == 'paint':
            return
        self.current_state = 'paint'
        self.show_brush_settings()
        self.old_x = None
        self.old_y = None
        #self.line_width = self.choose_size_button.get()
        self.color = self.DEFAULT_COLOR
        self.active_button = None
        self.use_pen()
        self.output.unbind('<Button-1>')
        self.output.bind('<Button-1>', self.paint)
        self.output.bind('<B1-Motion>', self.paint)
        self.output.bind('<ButtonRelease-1>', self.reset)
        self.draw_type = 'drag'
        self.master.bind('<s>', self.reset_toggle)
        self.draw_status = self.menu.add_command(label="Pen: "+str(self.draw_type))
        self.menu.update()

    def stop_paint(self):
        self.output.unbind('<Button-1>')
        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>') 
        self.output.bind('<Button-1>', self.highlight_region)
        self.output.unbind('<Button-1>')
        self.menu.delete(7)
        self.current_state = None
        self.save_paint()
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
        self.line_width = self.brush_size.get()
        # paint_color = 'white' if self.eraser_on else self.color
        paint_color = self.color
        if self.old_x and self.old_y:
            coords = (self.old_x, self.old_y, event.x, event.y)
            current_line = self.output.create_line(coords,
                               width=self.line_width, fill=paint_color,
                               capstyle=tk.ROUND, smooth=tk.TRUE, splinesteps=36,
                               tags='paint')
        self.old_x = event.x
        self.old_y = event.y
    
    def erase(self, event):
        if len(self.output.find_withtag('paint')) == 0:
            return
        # Checks if any paint is within brush range
        x = event.x
        y = event.y
        line_tuple = self.output.find_closest(x, y)
        x0, y0, x1, y1 = self.output.coords(line_tuple[0])
        distance = self.distance_to_line(x, y, x0, y0, x1, y1)
        brush = self.brush_size.get()
        eraser_brush = brush * 1.5
        if distance >= eraser_brush:
            return
        # Removes all paint within eraser_brush range
        for item in self.output.find_enclosed(x-eraser_brush, y-eraser_brush, x+eraser_brush, y+eraser_brush):
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
        self.menu.entryconfig(7, label="Pen: "+str(self.draw_type))

    def reset(self, event):
        self.old_x, self.old_y = None, None

    def distance_to_line(self, px, py, x0, y0, x1, y1):
        # Robust point-to-segment distance.
        # If the segment is a point, return Euclidean distance to that point.
        dx = x1 - x0
        dy = y1 - y0
        if dx == 0 and dy == 0:
            return math.hypot(px - x0, py - y0)

        # Project point onto the line defined by the segment, then clamp to [0,1]
        t = ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        proj_x = x0 + t * dx
        proj_y = y0 + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    def show_brush_settings(self): # This is the layout to be applied to all other spawned windows
        brush_win = None
        window = brush_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", self.disable_event)

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
        
        window.title("Brightness Settings")
        brightness_label = ttk.Label(window, text="Brightness:")
        brightness_label.grid(row=0, column=0)
        brightness_slider = ttk.Scale(window, from_=-100, to=400, orient=tk.HORIZONTAL, command=self.update_brightness)
        brightness_slider.grid(row=0, column=1, padx=5, pady=5)
        brightness_slider.set(0)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)

    def show_mask_settings(self):
        mask_settings_win = None
        window = mask_settings_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", self.disable_event)

        window.title("Mask Settings")

        # Configure grid layout
        window.columnconfigure(0, weight=1)
        window.columnconfigure(1, weight=1)

        def save_settings():
            self.image_processor.save_config()

        def load_settings():
            self.image_processor.load_config()
            window.destroy()  # Reopen to refresh values
            self.show_mask_settings()


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

            tm_otsu_options = [] # None
            tm_adaptive_options = ['adaptive_block_size']
            tm_local_options = ['local_radius']
            tm_manual_options = ['manual_threshold']
            other_circularity_options = ['min_cell_size', 'max_cell_size', 'circularity_threshold']
            other_watershed_options = ['min_peak_distance', 'peak_min_intensity', 'watershed_compactness']

            cell_detect_options = [ tm_otsu_options,
                                    tm_adaptive_options,
                                    tm_local_options,
                                    tm_manual_options,
                                    other_circularity_options,
                                    other_watershed_options
                                  ]

            cell_detect_frames = [  self.tm_otsu_frame,
                                    self.tm_adaptive_frame,
                                    self.tm_local_frame,
                                    self.tm_manual_frame,
                                    self.other_circularity_frame,
                                    self.other_watershed_frame
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
        """Draw directly on the binary mask"""
        if not self.editing_mask or self.current_mask is None:
            return

        x = int(self.output.canvasx(event.x))
        y = int(self.output.canvasy(event.y))
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
        self.photo = ImageTk.PhotoImage(img)
        self.output.delete("all")
        
        if self.background_image:
            # Display original image on the left
            display_bg = self.adjust_image(self.background_image)
            self.background_photo = ImageTk.PhotoImage(display_bg)
            self.bg_photo_id = self.output.create_image(0, 0, 
                                                       image=self.background_photo, 
                                                       anchor='nw')
            
            # If mask exists, display it on the left
            # Display untouched image on the right for comparison
            if mask is not None:
                self.mask_photo = ImageTk.PhotoImage(mask)
                offset_x = display_bg.width + 10  # 10 pixels spacing
                self.bg_mask_photo_id = self.output.create_image(offset_x, 0, 
                                                                image=self.background_photo, 
                                                                anchor='nw')
                self.mask_photo_id = self.output.create_image(0, 0, 
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
        updated_img = Image.fromarray(overlay).convert('RGBA')
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
        _, auto_labels = binary_mask_cell_count(background)
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
        )

        self.background_image = annotated
        self.last_df = df
        self.show_page()

        save_path = fd.asksaveasfilename(title="Save CSV", defaultextension=".csv", filetypes=[("Comma-separated values", "*.csv")])
        if save_path:
            # df.to_excel(save_path, index=False)
            df.to_csv(save_path, index=False)
            messagebox.showinfo("Cell Counts Saved", f"Cell counts per zone saved to: {save_path}")
        else:
            messagebox.showinfo("Cell Counts", f"Cell counts per zone: {dict(zip(df['Zone'], df['Cell_Count']))}")

    def show_cell_mask_threshold(self, event=None, calculate=True):
        """Display the combined (auto + manual) mask overlay"""
        background = self.original_background.convert('L')

        # Run automatic detection
        if calculate == True:
            _, auto_labels = binary_mask_cell_count(background)
            auto_mask = auto_labels > 0
            self.auto_mask = auto_mask
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
        combined_mask = (auto_mask | add_mask) & ~remove_mask

        # Visualize combined mask on top of the original background
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

        self.show_page(mask=mask_img)

    
    def next_image_experimental(self): # unused
        self.root.destroy()
        PDFViewer()

    def next_image(self):
        logger.info("Processing next image")
        if self.tiff_filename is None:
            logger.warning("Next image failed: No TIFF loaded")
            messagebox.showerror("Error", "No TIFF loaded.")
            return

        image_path = f"{self.tiff_filename}_counted.jpg"
        csv_path = f"{self.tiff_filename}_data.csv"

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
