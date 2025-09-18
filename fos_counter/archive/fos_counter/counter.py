import numpy as np
from skimage import io, filters, morphology, measure, util, feature, segmentation, color
from scipy import ndimage as ndi
from PIL import Image, ImageDraw, ImageFont

def count_fos_positive(input_path, output_path):
    """
    Counts fluorescent FOS-positive cells in a grayscale input image.
    Generates a new image with cell IDs marked on each detected cell, overlaid on the original image.
    
    Args:
        input_path (str): Path to the grayscale input image.
        output_path (str): Path to save the annotated output image.
    
    Returns:
        int: The number of detected fluorescent FOS-positive cells.
    """
    # Load image (preserve original bit depth and channels)
    img = io.imread(input_path)
    
    # Handle possible 3D with single channel
    if len(img.shape) == 3 and img.shape[2] == 1:
        img = np.squeeze(img)
    
    # For intensity: convert to float grayscale
    if len(img.shape) == 3:
        intensity = util.img_as_float(color.rgb2gray(img))  # If unexpectedly color, convert to gray
    else:
        intensity = util.img_as_float(img)  # Use directly: bright regions are positive in fluorescence
    
    # Apply Gaussian filter to reduce noise (adjust sigma for fluorescence noise)
    intensity = filters.gaussian(intensity, sigma=2.0)
    
    # Otsu thresholding for bright objects on dark background
    thresh = filters.threshold_otsu(intensity)
    binary = intensity > thresh
    
    # Remove small objects (adjust min_size based on image resolution/cell size, e.g., for small fluorescent spots)
    binary = morphology.remove_small_objects(binary, min_size=20)
    
    # Distance transform for watershed
    distance = ndi.distance_transform_edt(binary)
    
    # Find local maxima as markers (adjust min_distance for cell spacing in fluorescent images)
    coords = feature.peak_local_max(distance, min_distance=5, exclude_border=True)
    markers = np.zeros(distance.shape, dtype=bool)
    markers[tuple(coords.T)] = True
    markers = measure.label(markers)
    
    # Watershed segmentation to separate touching cells
    labels = segmentation.watershed(-distance, markers, mask=binary)
    
    # Count unique labels (exclude background 0)
    num_cells = len(np.unique(labels)) - 1
    
    # Prepare original image for annotation: normalize to uint8 RGB
    if len(img.shape) == 2:
        img_rgb = color.gray2rgb(img)  # Convert grayscale to RGB
    else:
        img_rgb = img  # Assume already RGB
    img_uint8 = util.img_as_ubyte(img_rgb)  # Scale to 0-255, handles 16-bit etc.
    
    original = Image.fromarray(img_uint8)
    
    draw = ImageDraw.Draw(original)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
    except IOError:
        font = ImageFont.load_default()  # Fallback if font not found
    
    # Get region properties for centroids
    props = measure.regionprops(labels)
    for i, prop in enumerate(props, start=1):
        y, x = prop.centroid  # (row, col)
        draw.text((int(x), int(y)), str(i), fill=(255, 0, 0), font=font)
    
    original.save(output_path)
    
    return num_cells