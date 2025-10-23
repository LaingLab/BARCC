#!/usr/bin/env python3
import fitz
import tkinter as tk
from tkinter import filedialog as fd, ttk, messagebox, simpledialog, Toplevel
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageEnhance
import numpy as np
import copy
from skimage import filters, morphology, measure, util, feature, segmentation, color
from skimage.morphology import binary_closing
from scipy.ndimage import distance_transform_edt

import pandas as pd
import os
import io

#temp for print(X,file=sys.stderr) debug checking
import sys



class PDFViewer:
    def __init__(self):
        self.root = tk.Tk()
        self.master = self.root
        self.master.bind('<q>', self.quit)
        self.master.title('Regional IF Analyzer')
#       self.master.geometry('%dx%d' % (self.master.winfo_screenwidth(), self.master.winfo_screenheight()))
        self.master.geometry('1200x1200')
        self.master.resizable(True, True)
        self.master.rowconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=0)
        self.master.columnconfigure(0, weight=1)

        # Create simple antibody icon, flipped upside down
        icon_img = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon_img)
        # Draw inverted Y shape for antibody
        draw.line((16, 0, 16, 15), fill='white', width=2)  # stem from top
        draw.line((16, 15, 8, 31), fill='white', width=2)  # left arm to bottom
        draw.line((16, 15, 24, 31), fill='white', width=2)  # right arm to bottom
        # Fluorescent tag: green circle at the top middle
        draw.ellipse((12, 0, 20, 8), fill='lime', outline='green')
        icon = ImageTk.PhotoImage(icon_img)
        self.master.iconphoto(True, icon)

        # Subsystems
        self.pdf_handler = PDFHandler()
        self.state_manager = StateManager()

        # App state
        self.path = None
        self.doc = None
        self.current_page = 0
        self.num_pages = 0
        self.zoom = 4.0
        self.page_images = {}
        self.mask_images = {}
        self.zone_counters = {}
        self.zone_names = {}

        # Undo/state
        self.undo_stack = self.state_manager.undo_stack  # just access if needed, use methods

        # Paint variables
        self.DEFAULT_PEN_SIZE = 5.0
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

        # Preprocessing cache handled inside image_processing module
        # Build GUI
        self._build_gui()

        self.root.mainloop()


    def quit(self, master):
        self.master.destroy()

    def _build_gui(self):
        # Menu
        self.menu = tk.Menu(self.master)
        self.master.config(menu=self.menu)
        filemenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="Import Atlas Section", command=self.open_file)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_command(label="Help", command=self.show_help)
        filemenu.add_command(label="Exit", command=self.master.destroy)

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
        self.scrolly = tk.Scrollbar(self.top_frame, orient=tk.VERTICAL)
        self.scrolly.grid(row=0, column=1, sticky='ns')
        self.scrollx = tk.Scrollbar(self.top_frame, orient=tk.HORIZONTAL)
        self.scrollx.grid(row=1, column=0, sticky='ew')

        self.output = tk.Canvas(self.top_frame, bg='#ECE8F3')
        self.output.configure(yscrollcommand=self.scrolly.set, xscrollcommand=self.scrollx.set)
        self.output.grid(row=0, column=0, sticky='nsew')
        self.scrolly.configure(command=self.output.yview)
        self.scrollx.configure(command=self.output.xview)

        # PIL canvas for paint image creation

        # Paint tools
        self.pen_button = tk.Button(self.right_frame, text='pen', command=self.use_pen)
        self.pen_button.grid(row=0, column=0)

        self.eraser_button = tk.Button(self.right_frame, text='eraser', command=self.use_eraser)
        self.eraser_button.grid(row=1, column=0)

        self.choose_size_button = tk.Scale(self.right_frame, from_=1, to=10, orient=tk.HORIZONTAL)
        self.choose_size_button.set(self.DEFAULT_PEN_SIZE)
        self.choose_size_button.grid(row=2, column=0)


        # Bind click event for highlighting
        self.output.bind("<Button-1>", self.highlight_region)

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

        # Rotate Button
        self.rotation_label = ttk.Label(self.bottom_frame, text="Rotate (degrees):")
        self.rotation_label.pack(side=tk.LEFT, padx=10, pady=10)
        self.rotation_entry = ttk.Entry(self.bottom_frame, width=10)
        self.rotation_entry.pack(side=tk.LEFT, padx=5, pady=10)
        ttk.Button(self.bottom_frame, text="Rotate", command=self.rotate_custom).pack(side=tk.LEFT, padx=10, pady=10)

        # Scale Button
        self.scale_label = ttk.Label(self.bottom_frame, text="Scale:")
        self.scale_label.pack(side=tk.LEFT, padx=10, pady=10)
        self.scale_entry = ttk.Entry(self.bottom_frame, width=10)
        self.scale_entry.pack(side=tk.LEFT, padx=5, pady=10)

        # Resize Buttons
        ttk.Button(self.bottom_frame, text="Resize", command=self.resize_custom).pack(side=tk.LEFT, padx=8, pady=8)
        ttk.Button(self.bottom_frame, text="Resize X", command=self.resize_x).pack(side=tk.LEFT, padx=8, pady=8)
        ttk.Button(self.bottom_frame, text="Resize Y", command=self.resize_y).pack(side=tk.LEFT, padx=8, pady=8)

        # Brightness slider
        self.brightness_label = ttk.Label(self.bottom_frame, text="Brightness:")
        self.brightness_label.pack(side=tk.LEFT, padx=8, pady=8)
        self.brightness_slider = ttk.Scale(self.bottom_frame, from_=-100, to=100, orient=tk.HORIZONTAL, command=self.update_brightness)
        self.brightness_slider.pack(side=tk.LEFT, padx=4, pady=8)
        self.brightness_slider.set(0)

        # Sensitivity slider
        self.sensitivity_label = ttk.Label(self.bottom_frame, text="Sensitivity:")
        self.sensitivity_label.pack(side=tk.LEFT, padx=8, pady=8)
        self.sensitivity_var = tk.IntVar(value=50)
        self.sensitivity_slider = tk.Scale(self.bottom_frame, from_=0, to=100, orient=tk.HORIZONTAL, variable=self.sensitivity_var)#), command=self.update_sensitivity_var)
        self.sensitivity_slider.pack(side=tk.LEFT, padx=4, pady=8)
#        self.sensitivity_slider.set(50)
        self.sensitivity_value_entry = ttk.Entry(self.bottom_frame, textvariable=self.sensitivity_var, width=4)
        self.sensitivity_value_entry.pack(side=tk.LEFT, padx=4, pady=8)
#        self.sensitivity_value_entry.bind("<Return>", self.update_sensitivity_from_entry)
#        self.sensitivity_value_entry.bind("<FocusOut>", self.update_sensitivity_from_entry)

        # Next Image button
        ttk.Button(self.bottom_frame, text="Next Image", command=self.next_image).pack(side=tk.LEFT, padx=8, pady=8)

        # Count Cell Button (framework for hiding button until after cropping, but not currently used)
        self.count_button = ttk.Button(self.bottom_frame, text="Count Cells", command=self.count_cells)
        self.count_button.pack(side=tk.LEFT, padx=10, pady=10)
        self.count_button_packed = True 

        self.master.bind('<Control-z>', self._undo_event)
        self.master.bind('<Control-s>', self.save_flattened_image)

        # Paint buttons
        ttk.Button(self.right_frame, text="Start Paint", command=self.start_paint).grid(row=3, column=0)
        ttk.Button(self.right_frame, text="Stop Paint", command=self.stop_paint).grid(row=4, column=0)
    
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
        # Hides background
        self.output.itemconfig(self.bg_photo_id, state='hidden')
        # Captures the drawing
#       self.output.postscript(file='test.ps', colormode='color')
        ps = self.output.postscript(colormode='color')
        # Shows background
        self.output.itemconfig(self.bg_photo_id, state='normal')

        # Convert img from postscript
        draw = Image.open(io.BytesIO(ps.encode('utf-8')))
        img = draw.convert(mode='RGBA') 
        # Processes and sets photo to be displayed
        self.img = self.img_white_to_transparent(img)
        self.photo = ImageTk.PhotoImage(self.img)
        self.atlas_filetype = 'img'
        # Removes the drawing from the canvas
        self.output.delete('paint')

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



    # ---------- UPDATERS ----------
    def update_sensitivity_var(self, value):
        #self.sensitivity_var.delete(0, tk.END)
        self.sensitivity_var.insert(0, value)

    def update_sensitivity_from_entry(self, event=None):
        try:
            val = int(self.sensitivity_var.get())
            if 0 <= val <= 100:
                self.sensitivity_slider.set(val)
            else:
                raise ValueError
        except ValueError:
            self.sensitivity_var.set(str(int(self.sensitivity_slider.get())))

    def update_brightness(self, value):
        self.brightness = float(value)
        self.show_page()

    def adjust_image(self, img):
        enhancer = ImageEnhance.Brightness(img)
        factor = 1 + (self.brightness / 100.0)
        return enhancer.enhance(factor)



    # ---------- HELPERS ----------
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

    # ---------- STATE (UNDO) ----------
    def save_state(self):
        self.state_manager.save_state(self)

    def _undo_event(self, event=None):
        self.state_manager.undo(self)

    # ---------- PDF / RENDER ----------
    def open_file(self):
        self.save_state()
        path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.path = path
            self.doc, self.num_pages = self.pdf_handler.open_pdf(self.path)
            self.atlas_filetype = 'pdf'
            # estimate zoom so page fits a default area (similar to original)
            page = self.pdf_handler.doc[0]
            pw = page.rect.width
            ph = page.rect.height
            ww = 1200
            wh = 1200
            try:
                self.zoom = min(ww / pw, wh / ph)
            except Exception:
                self.zoom = 4.0
            self.current_page = 0
            self.page_images = {}
            self.mask_images = {}
            self.zone_counters = {}
            self.zone_names = {}
            # Clear preprocess cache (page images changed)
            clear_preprocess_cache()
            self.show_page()

    def load_page_image(self):
        if self.atlas_filetype: 
            if self.current_page not in self.page_images:
                if self.atlas_filetype == 'pdf':
                    img = self.pdf_handler.render_page(self.current_page, self.zoom)
                elif self.atlas_filetype == 'img':
                    img = self.img
                self.page_images[self.current_page] = img
                self.mask_images[self.current_page] = Image.new('L', (img.width, img.height), 0)
                self.zone_counters[self.current_page] = 0
                self.zone_names[self.current_page] = {}
            return self.page_images[self.current_page]

    def show_page(self):
        img = self.load_page_image() or Image.new('RGBA', (1, 1), (0, 0, 0, 0))  # Fallback empty image for when brightness is set on init before pic is selected
        self.photo = ImageTk.PhotoImage(img)
        self.output.delete("all")
        if self.background_image:
            display_bg = self.adjust_image(self.background_image)
            self.background_photo = ImageTk.PhotoImage(display_bg)
            self.bg_photo_id = self.output.create_image(0, 0, image=self.background_photo, anchor='nw')
            print('background', file=sys.stderr)
        self.output.create_image(self.img_x, self.img_y, image=self.photo, anchor='nw')
        self.output.config(scrollregion=self.output.bbox(tk.ALL))
        print('photo', file=sys.stderr)

    # ---------- CROP ----------
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
        # Make near-white transparent
        cropped_img = self.img_white_to_transparent(cropped_img)
        self.page_images[self.current_page] = cropped_img
        mask_img = self.mask_images[self.current_page]
        cropped_mask = mask_img.crop((left, top, right, bottom))
        self.mask_images[self.current_page] = cropped_mask
        # Invalidate preprocessing for this page
        clear_preprocess_cache()
        self.show_page()
        self.toggle_crop_mode()
        if not self.count_button_packed:
            self.count_button.pack(side=tk.LEFT, padx=10, pady=10)
            self.count_button_packed = True

## Extract the white to transparent conversion to its own function so it can be used on crop and when importing the painted atlas
    def img_white_to_transparent(self, img):
        img_array = np.array(img)
        white_mask = np.all(img_array[:, :, :3] >= 250, axis=-1)
        img_array[white_mask, 3] = 0
        img = Image.fromarray(img_array)
        return img

    # ---------- DRAG / MOVE ----------
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

    # ---------- ROTATE / RESIZE ----------
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

    # ---------- IMPORT TIFF ----------
    def import_tiff(self):
        tiff_path = fd.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
        if tiff_path:
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

            ww, wh = self.master.winfo_width(), self.master.winfo_height() - self.bottom_frame.winfo_height()
            bw, bh = bg_RGBA.size
            scale = min(ww / bw, wh / bh)
            new_size = (int(bw * scale), int(bh * scale))
            self.background_image = bg_RGBA.resize(new_size, Image.BILINEAR)
            self.original_background = self.background_image.copy()
            self.show_page()

    # ---------- HIGHLIGHT ----------
    def highlight_region(self, event):
        self.save_state()
        if not self.atlas_filetype or self.crop_mode or self.edit_mode:
            return

        canvas_x = self.output.canvasx(event.x)
        canvas_y = self.output.canvasy(event.y)
        x, y = int(canvas_x - self.img_x), int(canvas_y - self.img_y)  # convert to atlas-local coordinates

        img = self.load_page_image()

        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            return

        barrier_img = preprocess_for_highlighting(self.current_page, img)
        # barrier_img coordinates align with atlas page coords
        seed_value = barrier_img.getpixel((x, y))
        if seed_value != 255:
            return  # clicked a barrier

        # increment zone id
        self.zone_counters[self.current_page] += 1
        zone_id = self.zone_counters[self.current_page]

        barrier_copy = barrier_img.copy()
        ImageDraw.floodfill(barrier_copy, (x, y), zone_id, thresh=0)
        filled = np.array(barrier_copy)
        mask = (filled == zone_id)

        # update mask image (atlas-sized)
        mask_img = self.mask_images[self.current_page]
        mask_array = np.array(mask_img)
        mask_array[mask] = zone_id
        self.mask_images[self.current_page] = Image.fromarray(mask_array)

        # prompt for name
        name = simpledialog.askstring("Region Name", "Enter a name for this region:")
        name = name.strip() if name else f"Zone {zone_id}"
        self.zone_names[self.current_page][zone_id] = name

        # overlay translucent yellow on atlas
        img_array = np.array(img)
        overlay = img_array.copy()
        overlay[..., :3][mask] = [255, 255, 0]
        overlay[..., 3][mask] = 18
        updated_img = Image.fromarray(overlay)
        self.page_images[self.current_page] = updated_img
        self.show_page()

    # ---------- COUNT CELLS ----------
    def count_cells(self):
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        if self.current_page not in self.mask_images:
            messagebox.showerror("Error", "Please load and select regions in the atlas first.")
            return

        # Call into image_processing to process + annotate + produce dataframe
        annotated, df, counts = count_cells_in_zones(
            self.original_background,
            self.mask_images[self.current_page],
            self.page_images[self.current_page],
            self.img_x,
            self.img_y,
            self.zone_counters,
            self.zone_names.get(self.current_page, {}),
            self.sensitivity_slider.get()
        )

        # Show annotated image in the viewer and allow saving results (excel)
        self.background_image = annotated
        self.show_page()

        save_path = fd.asksaveasfilename(title="Save Excel File", defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if save_path:
            df.to_excel(save_path, index=False)
            messagebox.showinfo("Cell Counts Saved", f"Cell counts per zone saved to: {save_path}")
        else:
            messagebox.showinfo("Cell Counts", f"Cell counts per zone: {dict(zip(df['Zone'], df['Cell_Count']))}")

    # ---------- SAVE FLATTENED ----------
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

    def autosave_flattened_image(self, filename):
        if self.background_image is None or self.current_page not in self.page_images:
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
        final.save(filename)

    def next_image(self):
        if self.tiff_filename is None:
            messagebox.showerror("Error", "No TIFF loaded.")
            return

        image_path = f"{self.tiff_filename}_counted.jpg"
        excel_path = f"{self.tiff_filename}_data.xlsx"

        # Autosave flattened image
        self.autosave_flattened_image(image_path)

        # Autosave count table if available
        if self.last_df is not None:
            self.last_df.to_excel(excel_path, index=False)

        # Clear data, image, and atlas
        self.background_image = None
        self.original_background = None
        self.doc = None
        self.page_images = {}
        self.mask_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.last_df = None
        self.img_x = 0
        self.img_y = 0

        # Hide count button if packed
        if self.count_button_packed:
            self.count_button.pack_forget()
            self.count_button_packed = False

        self.show_page()
        messagebox.showinfo("Next Image", f"Autosaved image to {image_path}\nAutosaved counts to {excel_path}" if self.last_df is not None else f"Autosaved image to {image_path}")




class StateManager:
    def __init__(self):
        self.undo_stack = []

    def save_state(self, viewer):
        state = {
            "current_page": viewer.current_page,
            "img_x": viewer.img_x,
            "img_y": viewer.img_y,
            "zoom": viewer.zoom,
            "zone_counters": copy.deepcopy(viewer.zone_counters),
            "zone_names": copy.deepcopy(viewer.zone_names),
        }
        self.undo_stack.append(state)

    def undo(self, viewer):
        if not self.undo_stack:
            return
        state = self.undo_stack.pop()
        viewer.current_page = state["current_page"]
        viewer.img_x = state["img_x"]
        viewer.img_y = state["img_y"]
        viewer.zoom = state["zoom"]
        viewer.zone_counters = state["zone_counters"]
        viewer.zone_names = state["zone_names"]
        viewer.show_page()



class PDFHandler:
    def __init__(self):
        self.doc = None
        self.num_pages = 0

    def open_pdf(self, path):
        self.doc = fitz.open(path)
        self.num_pages = len(self.doc)
        return self.doc, self.num_pages

    def render_page(self, page_index, zoom):
        if self.doc is None:
            raise RuntimeError("No PDF opened")
        page = self.doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=True)
        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
        return img







_PREPROCESS_CACHE = {}

def preprocess_for_highlighting(page_id, img):
    if page_id in _PREPROCESS_CACHE:
        return _PREPROCESS_CACHE[page_id]
    img_array = np.array(img)
    gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.float32)
    mag = filters.sobel(gray)
    closed_binary = binary_closing(mag)
    skel_binary = morphology.skeletonize(closed_binary)
    barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
    barrier[skel_binary] = 0
    barrier_img = Image.new('L', (img.width, img.height))
    barrier_img.putdata(barrier.flatten())
    _PREPROCESS_CACHE[page_id] = barrier_img
    return barrier_img

def clear_preprocess_cache():
    _PREPROCESS_CACHE.clear()

def count_cells_in_zones(background_pil, mask_pil, page_pil, img_x, img_y, zone_counters, zone_names, sensitivity):
    bg_arr = np.array(background_pil)
    if bg_arr.ndim == 3:
        if bg_arr.shape[2] == 4:
            rgb = color.rgba2rgb(bg_arr)
            img2d = color.rgb2gray(rgb)
        else:
            img2d = color.rgb2gray(bg_arr)
    else:
        img2d = bg_arr.astype(float) / 255.0
    intensity = util.img_as_float(img2d)
    intensity = filters.gaussian(intensity, sigma=2.0)
    thresh = filters.threshold_otsu(intensity)

    # implements the sensitivity for cell detection
    multiplier = 2.0 - (sensitivity / 100.0) * 1.5  # 2.0 at 0, 0.5 at 100
    effective_thresh = thresh * multiplier
    binary = intensity > effective_thresh

    # Remove small objects (adjust min_size based on image resolution/cell size, e.g., for small fluorescent spots)
    binary = morphology.remove_small_objects(binary, min_size=20)

    # Distance transform for watershed
    distance = distance_transform_edt(binary)

    # Find local maxima as markers (adjust min_distance for cell spacing in fluorescent images)
    coords = feature.peak_local_max(distance, min_distance=5, exclude_border=True)
    markers = np.zeros(distance.shape, dtype=bool)
    if coords.size:
        markers[tuple(coords.T)] = True
    markers = measure.label(markers)

    # Watershed segmentation to separate touching cells
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

    # Normalize original image to full range for visibility (stretch contrast)
    bg_min = img2d.min()
    bg_max = img2d.max()
    if bg_max > bg_min:
        norm = (img2d - bg_min) / (bg_max - bg_min)
    else:
        norm = np.zeros_like(img2d)
    img_uint8 = (norm * 255).astype('uint8')

    # Convert to RGB for color annotation
    img_rgb = np.stack([img_uint8]*3, axis=-1)
    annotated = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(annotated, 'RGBA') #RGBA for opacity, which is for the drawn text
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font = ImageFont.load_default()


    for i, prop in enumerate(filtered_props, start=1):
        r, c = prop.centroid
        draw.text((int(c), int(r)), str(i), fill=(255,0,0,77), font=font)
    annotated = annotated.convert('RGBA')
    zone_list, count_list = [], []
    for zid in sorted(counts.keys()):
        name = zone_names.get(zid, f"Zone {zid}")
        zone_list.append(name)
        count_list.append(counts[zid])
    df = pd.DataFrame({'Zone': zone_list, 'Cell_Count': count_list})
    return annotated, df, counts




if __name__ == "__main__":
    PDFViewer()


