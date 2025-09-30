import fitz  # PyMuPDF
from PIL import Image, ImageTk, ImageDraw, ImageFont
import tkinter as tk
from tkinter import filedialog as fd
from tkinter import ttk, messagebox, simpledialog
import numpy as np
from skimage import filters, morphology, measure, util, feature, segmentation, color
from skimage.morphology import binary_closing
from scipy.ndimage import distance_transform_edt
import pandas as pd
import copy
#temp for print(X, file=sys.stderr) debug checking
import sys


class PDFViewer:
    def __init__(self, master):
        self.master = master
        self.master.title('Regional IF Analyzer')
        self.master.geometry('1200x1200')
        self.master.resizable(True, True)
        self.master.rowconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=0)
        self.master.columnconfigure(0, weight=1)

        # Create simple antibody icon, flipped upside down
        icon_img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon_img)
        draw.line((16, 0, 16, 15), fill='white', width=2)
        draw.line((16, 15, 8, 31), fill='white', width=2)
        draw.line((16, 15, 24, 31), fill='white', width=2)
        draw.ellipse((12, 0, 20, 8), fill='lime', outline='green')
        icon = ImageTk.PhotoImage(icon_img)
        self.master.iconphoto(True, icon)

        self.path = None
        self.doc = None
        self.current_page = 0
        self.num_pages = 0
        self.zoom = 4.0
        self.page_images = {}
        self.mask_images = {}
        self.zone_counters = {}
        self.zone_names = {}

        self.undo_stack = []

        # Crop variables
        self.crop_mode = False
        self.crop_rect = None
        self.start_x = None
        self.start_y = None

        # Edit mode variables
        self.edit_mode = False
        self.img_x = 0
        self.img_y = 0
        self.drag_start_x = None
        self.drag_start_y = None

        # Background image
        self.background_image = None

        # Cache for preprocessed barrier images
        self.page_preprocessed = {}

        # Menu
        self.menu = tk.Menu(self.master)
        self.master.config(menu=self.menu)
        filemenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="Import Atlas Section", command=self.open_file)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_command(label="Help", command=self.show_help)
        filemenu.add_command(label="Exit", command=self.master.destroy)

        # Top frame for canvas
        self.top_frame = ttk.Frame(self.master)
        self.top_frame.grid(row=0, column=0, sticky='nsew')
        self.top_frame.rowconfigure(0, weight=1)
        self.top_frame.columnconfigure(0, weight=1)

        # Bottom frame for buttons
        self.bottom_frame = ttk.Frame(self.master)
        self.bottom_frame.grid(row=1, column=0, sticky='ew')

        # Scrollbars
        self.scrolly = tk.Scrollbar(self.top_frame, orient=tk.VERTICAL)
        self.scrolly.grid(row=0, column=1, sticky='ns')
        self.scrollx = tk.Scrollbar(self.top_frame, orient=tk.HORIZONTAL)
        self.scrollx.grid(row=1, column=0, sticky='ew')

        # Canvas
        self.output = tk.Canvas(self.top_frame, bg='#ECE8F3')
        self.output.configure(yscrollcommand=self.scrolly.set, xscrollcommand=self.scrollx.set)
        self.output.grid(row=0, column=0, sticky='nsew')
        self.scrolly.configure(command=self.output.yview)
        self.scrollx.configure(command=self.output.xview)

        # Bind click event for highlighting
        self.output.bind("<Button-1>", self.highlight_region)

        ttk.Button(self.bottom_frame, text="Crop", command=self.toggle_crop_mode).pack(side=tk.LEFT, padx=10, pady=10)

        self.style = ttk.Style()
        self.style.configure('On.TButton', background='lightgreen')
        self.move_button = ttk.Button(self.bottom_frame, text="Move Atlas", command=self.toggle_edit_mode)
        self.move_button.pack(side=tk.LEFT, padx=10, pady=10)

        ttk.Button(self.bottom_frame, text="Import TIFF", command=self.import_tiff).pack(side=tk.LEFT, padx=10, pady=10)

        self.rotation_label = ttk.Label(self.bottom_frame, text="Rotate (degrees):")
        self.rotation_label.pack(side=tk.LEFT, padx=10, pady=10)
        self.rotation_entry = ttk.Entry(self.bottom_frame, width=10)
        self.rotation_entry.pack(side=tk.LEFT, padx=5, pady=10)
        ttk.Button(self.bottom_frame, text="Rotate", command=self.rotate_custom).pack(side=tk.LEFT, padx=10, pady=10)

        self.scale_label = ttk.Label(self.bottom_frame, text="Scale:")
        self.scale_label.pack(side=tk.LEFT, padx=10, pady=10)
        self.scale_entry = ttk.Entry(self.bottom_frame, width=10)
        self.scale_entry.pack(side=tk.LEFT, padx=5, pady=10)
        ttk.Button(self.bottom_frame, text="Resize", command=self.resize_custom).pack(side=tk.LEFT, padx=10, pady=10)

        self.count_button = ttk.Button(self.bottom_frame, text="Count Cells", command=self.count_cells)
        self.count_button_packed = False

        self.master.bind('<Control-z>', self.undo)
        self.master.bind('<Control-s>', self.save_flattened_image)

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
        state = {
            'page_images': copy.deepcopy(self.page_images),
            'mask_images': copy.deepcopy(self.mask_images),
            'zone_counters': copy.deepcopy(self.zone_counters),
            'zone_names': copy.deepcopy(self.zone_names),
            'img_x': self.img_x,
            'img_y': self.img_y,
            'zoom': self.zoom
        }
        self.undo_stack.append(state)

    def undo(self, event=None):
        if not self.undo_stack:
            return
        state = self.undo_stack.pop()
        self.page_images = state['page_images']
        self.mask_images = state['mask_images']
        self.zone_counters = state['zone_counters']
        self.zone_names = state['zone_names']
        self.img_x = state['img_x']
        self.img_y = state['img_y']
        self.zoom = state['zoom']
        self.show_page()

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
        # Get crop coordinates
        left = min(self.start_x, end_x)
        top = min(self.start_y, end_y)
        right = max(self.start_x, end_x)
        bottom = max(self.start_y, end_y)
        # Crop the image
        img = self.load_page_image()
        cropped_img = img.crop((left, top, right, bottom))
        # Make white background transparent
        cropped_array = np.array(cropped_img)
        white_mask = np.all(cropped_array[:, :, :3] >= 250, axis=-1)  # Near-white pixels
        cropped_array[white_mask, 3] = 0  # Set alpha to 0 for transparency
        cropped_img = Image.fromarray(cropped_array)
        self.page_images[self.current_page] = cropped_img
        # Crop the mask
        mask_img = self.mask_images[self.current_page]
        cropped_mask = mask_img.crop((left, top, right, bottom))
        self.mask_images[self.current_page] = cropped_mask
        self.show_page()
        # Exit crop mode
        self.toggle_crop_mode()
        # Show the Count Cells button after cropping
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
            resized = img.resize(new_size, Image.BILINEAR)  # Changed to BILINEAR for speed
            self.page_images[self.current_page] = resized
            mask_img = self.mask_images[self.current_page]
            resized_mask = mask_img.resize(new_size, Image.NEAREST)
            self.mask_images[self.current_page] = resized_mask
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def import_tiff(self):
        tiff_path = fd.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
        if tiff_path:
            self.background_image = Image.open(tiff_path)
            array = np.array(self.background_image)
            if array.ndim == 2 or (array.ndim == 3 and array.shape[2] == 1):  # Grayscale
                array = np.squeeze(array)
                array_norm = (array - array.min()) / (array.max() - array.min() + 1e-8) * 255
                self.background_image = Image.fromarray(array_norm.astype(np.uint8)).convert('RGBA')
            elif array.max() <= 1.0:  # Float image
                array = (array * 255).astype(np.uint8)
                self.background_image = Image.fromarray(array).convert('RGBA')
            else:
                self.background_image = self.background_image.convert('RGBA')
            # Resize TIFF to fit window
            ww, wh = self.master.winfo_width(), self.master.winfo_height() - self.bottom_frame.winfo_height()
            bw, bh = self.background_image.size
            scale = min(ww / bw, wh / bh)
            new_size = (int(bw * scale), int(bh * scale))
            self.background_image = self.background_image.resize(new_size, Image.BILINEAR)
            self.show_page()

    def open_file(self):
        self.save_state()
        self.path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if self.path:
            self.doc = fitz.open(self.path)
            self.num_pages = len(self.doc)
            # Calculate zoom
            page = self.doc[0]
            pw = page.rect.width
            ph = page.rect.height
            ww = 1200
            wh = 1200
            self.zoom = min(ww / pw, wh / ph)
            self.current_page = 0
            self.page_images = {}
            self.mask_images = {}
            self.zone_counters = {}
            self.zone_names = {}
            self.show_page()
            # temp: page.rect.{width, height} does not output 1200 as expected, is this because the overall window is 1200x1200 and those variables are only denoting the "workable space" where we can put a picture. (total space - top and bottom bar - scroll bars etc...)
            # print("pw ", pw, file=sys.stderr)
            # print("ph ", ph, file=sys.stderr)
            # print("self.zoom ", self.zoom, file=sys.stderr)

    def load_page_image(self):
        if self.doc:
            if self.current_page not in self.page_images:
                page = self.doc[self.current_page]
                mat = fitz.Matrix(self.zoom, self.zoom)
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=True)
                img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
                self.page_images[self.current_page] = img
                self.mask_images[self.current_page] = Image.new('L', (img.width, img.height), 0)
                self.zone_counters[self.current_page] = 0
                self.zone_names[self.current_page] = {}
            return self.page_images[self.current_page]

    def show_page(self):
        img = self.load_page_image()
        self.photo = ImageTk.PhotoImage(img)
        self.output.delete("all")
        if self.background_image:
            self.background_photo = ImageTk.PhotoImage(self.background_image)
            self.output.create_image(0, 0, image=self.background_photo, anchor='nw')
        self.output.create_image(self.img_x, self.img_y, image=self.photo, anchor='nw')
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

    def highlight_region(self, event):
        self.save_state()
        if not self.doc or self.crop_mode or self.edit_mode:
            return

        canvas_x = self.output.canvasx(event.x)
        canvas_y = self.output.canvasy(event.y)
        x, y = int(canvas_x), int(canvas_y)

        img = self.load_page_image()
        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            return

        # Perform edge detection and mask generation
        if self.current_page not in self.page_preprocessed:
            img_array = np.array(img)
            # Convert to gray for edge detection
            gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.float32)
            # Edge detection
            mag = filters.sobel(gray)
            # Close dotted lines
            closed_binary = binary_closing(mag)
            # Make bounds as thin as possible
            skel_binary = morphology.skeletonize(closed_binary)

            barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
            barrier[skel_binary] = 0
            barrier_img = Image.new('L', (img.width, img.height))
            barrier_img.putdata(barrier.flatten())
        else:
            barrier_img = self.page_preprocessed[self.current_page]

        seed_value = barrier_img.getpixel((x, y))
        if seed_value != 255:
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
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        if self.current_page not in self.mask_images:
            messagebox.showerror("Error", "Please load and select regions in the atlas first.")
            return

        # Load image (preserve original bit depth and channels)
        img = np.array(self.background_image)
        
        # Handle possible 3D with single channel or color; force to grayscale
        if len(img.shape) == 3:
            if img.shape[2] == 1:
                img = np.squeeze(img)
            elif img.shape[2] == 3:
                img = color.rgb2gray(img)
            elif img.shape[2] == 4:
                img = color.rgba2rgb(img)
                img = color.rgb2gray(img)
            else:
                raise ValueError("Unsupported number of channels")
        
        # Now img is 2D
        
        # For intensity: convert to float (bright regions positive)
        intensity = util.img_as_float(img)
        
        # Apply Gaussian filter to reduce noise (adjust sigma for fluorescence noise)
        intensity = filters.gaussian(intensity, sigma=2.0)
        
        # Otsu thresholding for bright objects on dark background
        thresh = filters.threshold_otsu(intensity)
        binary = intensity > thresh
        
        # Remove small objects (adjust min_size based on image resolution/cell size, e.g., for small fluorescent spots)
        binary = morphology.remove_small_objects(binary, min_size=20)
        
        # Distance transform for watershed
        distance = distance_transform_edt(binary)
        
        # Find local maxima as markers (adjust min_distance for cell spacing in fluorescent images)
        coords = feature.peak_local_max(distance, min_distance=5, exclude_border=True)
        markers = np.zeros(distance.shape, dtype=bool)
        markers[tuple(coords.T)] = True
        markers = measure.label(markers)
        
        # Watershed segmentation to separate touching cells
        labels = segmentation.watershed(-distance, markers, mask=binary)
        
        # Get all region properties
        props = measure.regionprops(labels)
        
        # Initialize counts
        max_zone = self.zone_counters.get(self.current_page, 0)
        counts = {i: 0 for i in range(1, max_zone + 1)}
        filtered_props = []
        
        # Filter props based on mask and count per zone
        mask_img = self.mask_images[self.current_page]
        atlas_img = self.page_images[self.current_page]
        for prop in props:
            y, x = prop.centroid  # row, col on background
            ax = int(x - self.img_x)
            ay = int(y - self.img_y)
            if 0 <= ax < atlas_img.width and 0 <= ay < atlas_img.height:
                zone_id = mask_img.getpixel((ax, ay))
                if zone_id > 0:
                    counts[zone_id] += 1
                    filtered_props.append(prop)
        
        # Normalize original image to full range for visibility (stretch contrast)
        img_min = img.min()
        img_max = img.max()
        if img_max > img_min:
            img_norm = (img - img_min) / (img_max - img_min)
        else:
            img_norm = np.zeros_like(img, dtype=float)
        img_uint8 = util.img_as_ubyte(img_norm)
        
        # Convert to RGB for color annotation
        img_rgb = color.gray2rgb(img_uint8)
        
        original = Image.fromarray(img_rgb)
        
        draw = ImageDraw.Draw(original)
        try:
            font = ImageFont.truetype("arial.ttf", 15)
        except IOError:
            font = ImageFont.load_default()  # Fallback if font not found
        
        # Annotate only filtered props
        centroids = [(int(prop.centroid[1]), int(prop.centroid[0])) for prop in filtered_props]  # (x, y) where x=col, y=row
        
        for i, prop in enumerate(filtered_props, start=1):
            y, x = prop.centroid  # (row, col)
            draw.text((int(x), int(y)), str(i), fill=(255, 0, 0), font=font)
        
        self.background_image = original.convert('RGBA')
        self.show_page()

        # Create Excel file with names
        zone_list = []
        count_list = []
        for i in sorted(counts.keys()):
            name = self.zone_names[self.current_page].get(i, f"Zone {i}")
            zone_list.append(name)
            count_list.append(counts[i])
        df = pd.DataFrame({'Zone': zone_list, 'Cell_Count': count_list})
        save_path = fd.asksaveasfilename(title="Save Excel File", defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if save_path:
            df.to_excel(save_path, index=False)
            messagebox.showinfo("Cell Counts Saved", f"Cell counts per zone saved to: {save_path}")
        else:
            messagebox.showinfo("Cell Counts", f"Cell counts per zone: {dict(zip(zone_list, count_list))}")

    def save_flattened_image(self, event=None):
        if self.background_image is None or self.current_page not in self.page_images:
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

        base = Image.new('RGBA', (width, height), (255, 255, 255, 255))  # White background

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

if __name__ == "__main__":
    root = tk.Tk()
    app = PDFViewer(root)
    root.mainloop()
