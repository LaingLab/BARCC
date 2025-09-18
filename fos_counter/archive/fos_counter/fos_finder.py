from fos_counter import count_fos_positive
count = count_fos_positive('input_grayscale_image.tif', 'output_image.jpg')  # Assumes grayscale input (e.g., TIFF from microscopy)
print(f"Counted {count} fluorescent FOS-positive cells.")