import fitz  # PyMuPDF
from PIL import Image, ImageTk, ImageDraw
import tkinter as tk
from tkinter import filedialog as fd
from tkinter import ttk
import numpy as np
from scipy.ndimage import sobel, binary_dilation, binary_erosion

class PDFViewer:
    def __init__(self, master):
        self.master = master
        self.master.title('PDF Viewer with Highlighting')
        self.master.geometry('800x600')
        self.master.resizable(True, True)
        self.master.rowconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=0)
        self.master.columnconfigure(0, weight=1)

        self.path = None
        self.doc = None
        self.current_page = 0
        self.num_pages = 0
        self.zoom = 1.5  # Adjust zoom as needed for clarity
        self.page_images = {}

        # Crop variables
        self.crop_mode = False
        self.crop_rect = None
        self.start_x = None
        self.start_y = None

        # Menu
        self.menu = tk.Menu(self.master)
        self.master.config(menu=self.menu)
        filemenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="Open File", command=self.open_file)
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

        # Navigation buttons (simple prev/next)
        ttk.Button(self.bottom_frame, text="Previous", command=self.previous_page).pack(side=tk.LEFT, padx=10, pady=10)
        ttk.Button(self.bottom_frame, text="Next", command=self.next_page).pack(side=tk.LEFT, padx=10, pady=10)
        ttk.Button(self.bottom_frame, text="Crop", command=self.toggle_crop_mode).pack(side=tk.LEFT, padx=10, pady=10)

    def toggle_crop_mode(self):
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
        self.page_images[self.current_page] = cropped_img
        self.show_page()
        # Exit crop mode
        self.toggle_crop_mode()

    def open_file(self):
        self.path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if self.path:
            self.doc = fitz.open(self.path)
            self.num_pages = len(self.doc)
            self.current_page = 0
            self.page_images = {}
            self.show_page()

    def load_page_image(self):
        if self.doc:
            if self.current_page not in self.page_images:
                page = self.doc[self.current_page]
                mat = fitz.Matrix(self.zoom, self.zoom)
                pix = page.get_pixmap(matrix=mat)
                mode = "RGBA" if pix.alpha else "RGB"
                img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
                if mode == "RGB":
                    img = img.convert("RGBA")
                self.page_images[self.current_page] = img
            return self.page_images[self.current_page]

    def show_page(self):
        if self.doc:
            img = self.load_page_image()
            self.photo = ImageTk.PhotoImage(img)
            self.output.delete("all")
            self.output.create_image(0, 0, image=self.photo, anchor='nw')
            self.output.config(scrollregion=(0, 0, img.width, img.height))

    def previous_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.show_page()

    def next_page(self):
        if self.current_page < self.num_pages - 1:
            self.current_page += 1
            self.show_page()

    def highlight_region(self, event):
        if not self.doc or self.crop_mode:
            return
        canvas_x = self.output.canvasx(event.x)
        canvas_y = self.output.canvasy(event.y)
        x = int(canvas_x)
        y = int(canvas_y)
        img = self.load_page_image()
        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            return

        # Convert to numpy array
        img_array = np.array(img)

        # Grayscale for edge detection
        gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.float32)

        # Compute gradients using Sobel
        dx = sobel(gray, axis=0)
        dy = sobel(gray, axis=1)
        mag = np.hypot(dx, dy)

        # Threshold for edges without normalization
        edge_thresh = 1  # Lowered further to capture very subtle gradients from the light blue lines
        binary = (mag > edge_thresh).astype(bool)

        # Dilate to close gaps in dotted lines
        structure = np.ones((3, 3), dtype=bool)  # Smaller structure to avoid over-dilation
        closed_binary = binary_dilation(binary, structure=structure, iterations=5)
        closed_binary = binary_erosion(closed_binary, structure=structure, iterations=4)

        # Create barrier image: 255 for fillable areas, 0 for barriers
        barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
        barrier[closed_binary] = 0
        width, height = img.width, img.height
        barrier_img = Image.new('L', (width, height))
        barrier_img.putdata(barrier.flatten())

        # Get seed value
        seed_value = barrier_img.getpixel((x, y))

        if seed_value != 255:
            return  # Clicked on a barrier, do nothing

        # Floodfill on barrier_img: fill with 128
        ImageDraw.floodfill(barrier_img, (x, y), 128, thresh=0)  # Exact match for strict boundaries

        # Get mask
        filled = np.array(barrier_img)
        mask = (filled == 128)

        # Apply yellow overlay on original image
        alpha = 200  # Increased for more intense yellow
        yellow_rgb = np.array([255, 255, 0], dtype=np.uint8)
        bg = img_array[..., :3][mask]
        blended = ((bg * (255 - alpha) + yellow_rgb * alpha) // 255).astype(np.uint8)
        img_array[..., :3][mask] = blended

        # Update image
        updated_img = Image.fromarray(img_array)
        self.page_images[self.current_page] = updated_img
        self.photo = ImageTk.PhotoImage(updated_img)
        self.output.delete("all")
        self.output.create_image(0, 0, image=self.photo, anchor='nw')

if __name__ == "__main__":
    root = tk.Tk()
    app = PDFViewer(root)
    root.mainloop()