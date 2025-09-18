from fos_counter import count_fos_positive
import os

# Prompt user for input file path
input_path = input("Enter the path to your input grayscale image (e.g., path/to/image.tif): ").strip()

# Derive output path: same directory, input filename + _annotated.tiff
base_name = os.path.splitext(os.path.basename(input_path))[0]
output_dir = os.path.dirname(input_path)
output_path = os.path.join(output_dir, f"{base_name}_annotated.tiff")

count = count_fos_positive(input_path, output_path)
print(f"Counted {count} fluorescent FOS-positive cells. Annotated image saved to: {output_path}")