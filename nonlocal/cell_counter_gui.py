import tkinter as tk
from tkinter import filedialog, messagebox, Scale, Button, Label, Toplevel
from PIL import Image, ImageTk, ImageDraw, ImageFont
import os
import pandas as pd
from fos_counter import count_fos_positive
import threading

root = tk.Tk()
root.title("FOS Cell Counter GUI")

input_path = tk.StringVar()
annotated_path = tk.StringVar()
csv_path = tk.StringVar()

def select_image():
    file = filedialog.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
    if file:
        input_path.set(file)
        messagebox.showinfo("Selected", f"Selected image: {file}")

def run_count_cells():
    base_name = os.path.splitext(os.path.basename(input_path.get()))[0]
    output_dir = os.path.dirname(input_path.get())
    ann_path = os.path.join(output_dir, f"{base_name}_annotated.tiff")
    csv_file_path = os.path.join(output_dir, f"{base_name}_centroids.csv")

    count, centroids = count_fos_positive(input_path.get(), ann_path)
    if count > 0:
        df = pd.DataFrame(centroids, columns=['X', 'Y'])
        df.index = range(1, count + 1)
        df.index.name = 'Cell_ID'
        df.to_csv(csv_file_path)  # Comma-delimited by default
        annotated_path.set(ann_path)
        csv_path.set(csv_file_path)
        root.after(0, lambda: messagebox.showinfo("Success", f"Counted {count} cells.\nAnnotated image: {ann_path}\nCSV: {csv_file_path}"))
    else:
        root.after(0, lambda: messagebox.showinfo("Success", "No cells detected."))

def count_cells():
    if not input_path.get():
        messagebox.showerror("Error", "Please select an image first.")
        return
    # Show processing message
    processing_msg = messagebox.showinfo("Processing", "Counting cells... This may take a while for large images.", icon='info')
    # Run in thread to avoid freezing
    thread = threading.Thread(target=run_count_cells)
    thread.start()

def overlay_atlas():
    if not annotated_path.get():
        messagebox.showerror("Error", "Please count cells first to generate annotated image.")
        return
    overlay_file = filedialog.askopenfilename(filetypes=[("PNG files", "*.png")])
    if not overlay_file:
        return

    # Open new window for adjustment
    adjust_win = Toplevel(root)
    adjust_win.title("Overlay Adjustment")

    base_img = Image.open(annotated_path.get()).convert('RGBA')
    overlay_img = Image.open(overlay_file).convert('RGBA')

    # Sliders
    scale_var = tk.DoubleVar(value=1.0)
    rotate_var = tk.IntVar(value=0)
    x_offset_var = tk.IntVar(value=0)
    y_offset_var = tk.IntVar(value=0)

    Scale(adjust_win, label="Scale", from_=0.5, to=2.0, resolution=0.1, orient=tk.HORIZONTAL, variable=scale_var).pack()
    Scale(adjust_win, label="Rotation (degrees)", from_=-180, to=180, orient=tk.HORIZONTAL, variable=rotate_var).pack()
    Scale(adjust_win, label="X Offset", from_=-base_img.width//2, to=base_img.width//2, orient=tk.HORIZONTAL, variable=x_offset_var).pack()
    Scale(adjust_win, label="Y Offset", from_=-base_img.height//2, to=base_img.height//2, orient=tk.HORIZONTAL, variable=y_offset_var).pack()

    preview_label = Label(adjust_win)
    preview_label.pack()

    def update_preview():
        # Transform overlay
        ov = overlay_img.resize((int(overlay_img.width * scale_var.get()), int(overlay_img.height * scale_var.get())))
        ov = ov.rotate(rotate_var.get(), expand=True, resample=Image.BICUBIC)
        # Composite
        comp = base_img.copy()
        # Calculate position: center by default, then offset
        pos_x = (comp.width - ov.width) // 2 + x_offset_var.get()
        pos_y = (comp.height - ov.height) // 2 + y_offset_var.get()
        comp.paste(ov, (pos_x, pos_y), ov)  # Use ov as mask for transparency
        # Display resized preview
        preview_size = (400, 300)  # Adjust as needed
        photo = ImageTk.PhotoImage(comp.resize(preview_size))
        preview_label.config(image=photo)
        preview_label.image = photo

    def save_overlay():
        # Similar to update, but save full size
        ov = overlay_img.resize((int(overlay_img.width * scale_var.get()), int(overlay_img.height * scale_var.get())))
        ov = ov.rotate(rotate_var.get(), expand=True, resample=Image.BICUBIC)
        comp = base_img.copy()
        pos_x = (comp.width - ov.width) // 2 + x_offset_var.get()
        pos_y = (comp.height - ov.height) // 2 + y_offset_var.get()
        comp.paste(ov, (pos_x, pos_y), ov)
        save_path = filedialog.asksaveasfilename(defaultextension=".tiff", filetypes=[("TIFF files", "*.tiff")])
        if save_path:
            comp.save(save_path)
            messagebox.showinfo("Saved", f"Overlay saved to: {save_path}")
            adjust_win.destroy()

    Button(adjust_win, text="Preview", command=update_preview).pack()
    Button(adjust_win, text="Save Overlay", command=save_overlay).pack()

# Buttons
tk.Button(root, text="Select Image", command=select_image).pack(pady=10)
tk.Button(root, text="Count cells", command=count_cells).pack(pady=10)
tk.Button(root, text="Overlay Atlas", command=overlay_atlas).pack(pady=10)

root.mainloop()