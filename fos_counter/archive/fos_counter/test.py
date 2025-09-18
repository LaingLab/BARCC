from fos_counter import count_fos_positive

# Use real paths for a quick test (it will process the image)
input_file = r'D:\path\to\your\test_image.tif'  # Replace with a real TIFF path
output_file = r'D:\path\to\output_annotated.tiff'  # Replace with a desired output path

result = count_fos_positive(input_file, output_file)
print(result)  # Should print a tuple like (5, [(x1, y1), (x2, y2), ...])