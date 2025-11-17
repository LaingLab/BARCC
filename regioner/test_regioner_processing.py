import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Robust module discovery: look for a single .py file in the same directory
# (or its parent "regioner" directory) that defines ImageProcessor/binary_mask_cell_count

def find_regioner_module():
    # Start search in this directory (where the test will live)
    start = Path(__file__).resolve().parent

    candidates = []
    # Candidate dirs to search (this dir, and a sibling 'regioner' if present)
    search_dirs = [start]
    if start.name != 'regioner' and (start / 'regioner').is_dir():
        search_dirs.append(start / 'regioner')

    for d in search_dirs:
        for p in d.glob('*.py'):
            if p.name == Path(__file__).name or p.name == '__init__.py':
                continue
            try:
                text = p.read_text()
            except Exception:
                continue
            # Heuristic: does this file define ImageProcessor or binary_mask_cell_count
            if 'class ImageProcessor' in text or 'def binary_mask_cell_count' in text:
                candidates.append(p)

    if not candidates:
        # Fallback: pick the most recently modified .py in the first search dir
        d = search_dirs[0]
        py_files = [p for p in d.glob('*.py') if p.name != Path(__file__).name and p.name != '__init__.py']
        if not py_files:
            raise RuntimeError('Could not find the program file to import for tests')
        candidates = py_files

    # Pick the newest candidate (most recently modified)
    candidate = max(candidates, key=lambda p: p.stat().st_mtime)

    spec = importlib.util.spec_from_file_location('regioner_mod', str(candidate))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

regioner_mod = find_regioner_module()

# Convenience refs
ImageProcessor = regioner_mod.ImageProcessor
binary_mask_cell_count = regioner_mod.binary_mask_cell_count
preprocess_for_highlighting = regioner_mod.preprocess_for_highlighting
count_cells_in_zones = regioner_mod.count_cells_in_zones
ThresholdMethod = regioner_mod.ThresholdMethod


def test_preprocess_image_basic():
    ip = ImageProcessor()
    # Create a 64x64 grayscale image with a bright dot
    img = Image.new("L", (64, 64), 10)
    draw = ImageDraw.Draw(img)
    draw.ellipse((20, 20, 30, 30), fill=255)

    out = ip.preprocess_image(img)
    assert isinstance(out, np.ndarray)
    assert out.dtype == float or np.issubdtype(out.dtype, np.floating)
    assert out.min() >= 0.0 and out.max() <= 1.0


def test_detect_cells_simple():
    ip = ImageProcessor()
    # Use manual threshold so detection is deterministic
    ip.cell_config.threshold_method = ThresholdMethod.MANUAL
    ip.cell_config.manual_threshold = 0.2

    img = Image.new("L", (128, 128), 0)
    draw = ImageDraw.Draw(img)
    # Use small blobs so their area falls within the default min/max cell size
    draw.ellipse((30, 30, 38, 38), fill=255)
    draw.ellipse((80, 30, 88, 38), fill=255)
    draw.ellipse((30, 80, 38, 88), fill=255)

    # detect_cells accepts a PIL image
    img_out, labels = ip.detect_cells(img)
    assert labels.ndim == 2
    assert labels.shape == (img.height, img.width)
    assert labels.max() >= 1


def test_binary_mask_cell_count():
    img = Image.new("L", (64, 64), 0)
    draw = ImageDraw.Draw(img)
    # smaller blob so automatic detection finds it under default size limits
    draw.ellipse((22, 22, 30, 30), fill=255)

    img_out, mask = binary_mask_cell_count(img)
    assert isinstance(mask, np.ndarray)
    assert mask.shape == (img.height, img.width)
    assert mask.sum() > 0


def test_preprocess_for_highlighting_pdf():
    # Create an RGBA page-like image with an opaque rectangle
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, 50, 50), fill=(0, 0, 0, 255))

    barrier = preprocess_for_highlighting("testpage", img, "pdf")
    assert barrier.mode == "L"
    assert barrier.size == img.size


def test_count_cells_in_zones_simple():
    # Background with a single bright pixel/area
    bg = Image.new("L", (64, 64), 0)
    draw = ImageDraw.Draw(bg)
    draw.ellipse((30, 30, 34, 34), fill=255)

    # Region mask: put a single zone in the center
    region = Image.new("L", (64, 64), 0)
    dr = ImageDraw.Draw(region)
    dr.rectangle((20, 20, 45, 45), fill=1)

    # Cell mask: mark the same small blob as a detected cell
    cell_mask = Image.new("L", (64, 64), 0)
    dc = ImageDraw.Draw(cell_mask)
    dc.ellipse((30, 30, 34, 34), fill=255)

    # zone_counters values determine max_zone in the function; set one value >=1
    zone_counters = {0: 1}
    zone_names = {1: "Zone 1"}

    annotated, df, counts = count_cells_in_zones(bg, region, cell_mask, 0, 0, zone_counters, zone_names)

    # df should be a pandas DataFrame
    assert hasattr(df, "to_excel")
    # counts should be a dict; zone 1 may or may not be present depending on segmentation, but call should not fail
    assert isinstance(counts, dict)
