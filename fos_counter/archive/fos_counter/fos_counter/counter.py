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
        list: List of (x, y) centroids for each cell (x=column, y=row).
    """
    # Load image (preserve original bit depth and channels)
    img = io.imread(input_path)
    
    # Handle possible 3D with single channel or color; force to grayscale
    if len(img.shape) == 3:
        if img.shape[2] == 1:
            img = np.squeeze(img)
        else:
            img = color.rgb2gray(img)  # Convert to gray if color
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
    
    # Get region properties for centroids
    props = measure.regionprops(labels)
    centroids = [(int(prop.centroid[1]), int(prop.centroid[0])) for prop in props]  # (x, y) where x=col, y=row
    
    for i, prop in enumerate(props, start=1):
        y, x = prop.centroid  # (row, col)
        draw.text((int(x), int(y)), str(i), fill=(255, 0, 0), font=font)
    
    original.save(output_path)
    
    return num_cells, centroids