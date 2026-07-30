#    BARCC (Brain Atlas Regional Cell Counter) is a software that performs automatic cell counting 
#    of microscopy images and assists in the automation of image workup. 
#    Copyright (C) <2025>  <George Taylor>

#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.

#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.

#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.

#!/usr/bin/env python3
import fitz
import tkinter as tk
from tkinter import filedialog as fd, ttk, messagebox, simpledialog, Toplevel
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageEnhance
import numpy as np
import copy
from skimage import filters, morphology, measure, util, feature, segmentation, color, restoration, exposure
from skimage.morphology import closing, disk
from scipy.ndimage import distance_transform_edt
from scipy import ndimage as ndi
from dataclasses import dataclass
import enum
import math
import csv

import pandas as pd
import os
import io
import logging
import yaml
import sys
import json
from datetime import datetime
import platform
import subprocess
import webbrowser
import zipfile
from io import BytesIO


# ---------------------------------------------------------------------------
# Parameter help (hover tooltips) for Mask Settings
# ---------------------------------------------------------------------------
PARAM_HELP = {
    # Preprocess
    "disk_radius": (
        "Top-hat background subtraction: size of the structuring disk (pixels). "
        "Larger values remove broader, uneven background glow. Typical 10–40."
    ),
    "bg_gaussian_sigma": (
        "Gaussian blur sigma for background estimate. Larger = smoother, broader background model."
    ),
    "nr_gaussian_sigma": (
        "Gaussian noise reduction sigma. Higher smooths more (may blur small cells)."
    ),
    "median_kernel": (
        "Median filter window size (odd integer). Removes salt-and-pepper noise while keeping edges."
    ),
    "bilateral_sigma_color": (
        "Bilateral filter: how much intensity difference is smoothed. Larger = more color/intensity blending."
    ),
    "bilateral_sigma_space": (
        "Bilateral filter: spatial neighborhood size. Larger = smoother over bigger areas."
    ),
    "clahe_kernel": (
        "CLAHE tile size. Smaller tiles enhance local contrast more aggressively."
    ),
    "clahe_clip_limit": (
        "CLAHE contrast clip limit. Higher = stronger local contrast boost (can amplify noise)."
    ),
    "gamma": (
        "Gamma correction. <1 brightens mid-tones (helps dim cells); >1 darkens them."
    ),
    "unsharp_radius": (
        "Unsharp-mask blur radius. Controls the spatial scale of edge/signal enhancement."
    ),
    "unsharp_amount": (
        "Unsharp-mask strength. Higher sharpens and boosts cell edges (may create halos)."
    ),
    # Watershed
    "threshold_method": (
        "How foreground is separated: Otsu (auto global), Adaptive/Local (local stats), Manual (fixed level)."
    ),
    "manual_threshold": (
        "Fixed intensity threshold (0–1 after preprocess). Higher = fewer pixels counted as cells."
    ),
    "adaptive_block_size": (
        "Adaptive threshold window (pixels, odd). Larger windows track slow background changes."
    ),
    "local_radius": (
        "Local threshold neighborhood radius. Larger = more global-like thresholding."
    ),
    "min_cell_size": (
        "Watershed: minimum object area (pixels) kept after thresholding."
    ),
    "max_cell_size": (
        "Watershed: maximum object area (pixels). Larger clumps above this are rejected."
    ),
    "circularity_threshold": (
        "Watershed shape filter (0–1). Higher keeps rounder objects only; lower allows irregular shapes."
    ),
    "min_peak_distance": (
        "Watershed: minimum distance between cell centers (pixels). Lower splits dense clusters more."
    ),
    "peak_min_intensity": (
        "Watershed: minimum peak height on the distance map to seed a cell (0–1 scale)."
    ),
    "watershed_compactness": (
        "Watershed compactness. Higher prefers more circular watershed basins."
    ),
    # Blob / DoG
    "detection_method": (
        "blob/log = Laplacian of Gaussian; dog = Difference of Gaussians (often better multi-scale); "
        "watershed = classic threshold pipeline. "
        "Turn on Adaptive (checkbox) to layer tiled thresholds / dual-pass / density packing on Blob or DoG."
    ),
    "adaptive_enabled": (
        "When checked, runs the selected Blob/LoG or DoG detector with adaptive tiling, "
        "optional dual-pass fusion, and density packing. Does not apply to Watershed. "
        "Best for mixed high/low background or mixed cluster density on one slice."
    ),
    "blob_min_sigma": (
        "Smallest blob scale (sigma). Lower finds smaller/tighter spots. Try 1–3 for fine cells."
    ),
    "blob_max_sigma": (
        "Largest blob scale (sigma). Raise if large bright cells are missed (e.g. 12–20)."
    ),
    "blob_num_sigma": (
        "Number of scales between min and max sigma (LoG only). More = finer size sampling, slower."
    ),
    "blob_threshold": (
        "Absolute blob sensitivity. Lower finds dimmer cells (more detections); higher is stricter. "
        "Try 0.02–0.08 for dim fluorescence."
    ),
    "blob_threshold_rel": (
        "Relative peak threshold (0–1). 0 = off. When >0, keeps peaks above this fraction of the "
        "strongest response — useful when brightness varies across the field."
    ),
    "blob_overlap": (
        "How much overlapping blobs can share (0–1). Higher merges nearby detections less aggressively."
    ),
    "blob_min_area": (
        "Minimum estimated cell area (π·r² from sigma). Raise to drop tiny noise spots."
    ),
    "blob_max_area": (
        "Maximum estimated cell area. Raise if large real cells are filtered out."
    ),
    "blob_min_circularity": (
        "Minimum local shape circularity (0 = off). Measures the thresholded patch around each peak. "
        "Raise (0.3–0.6) to reject elongated tissue-edge blobs; lower if real cells are irregular."
    ),
    "blob_min_isotropy": (
        "Minimum radial symmetry of intensity around the peak (0 = off, 1 = perfect). "
        "Rejects edge-of-tissue and fiber detections that are bright on one side only. Try 0.4–0.55."
    ),
    "blob_reject_tissue_edge": (
        "1 = reject peaks whose outer ring is partly outside the tissue (near-black). "
        "Cuts false positives along the tissue border. 0 = allow border peaks."
    ),
    "blob_edge_dark_frac": (
        "With tissue-edge reject: max fraction of the outer ring that may be near-black. "
        "Lower = stricter border rejection (e.g. 0.25–0.35)."
    ),
    "blob_bg_relative": (
        "Require peak intensity − local median ≥ this (normalized 0–1 image). "
        "0 = off. Raises the bar for high-background texture peaks; try 0.08–0.18."
    ),
    "blob_radius_scale": (
        "Converts detected sigma → mask disk radius (r ≈ sigma × scale). "
        "Larger draws bigger cell masks around each peak (default ~1.8)."
    ),
    "blob_free_space": (
        "Fraction of the disk that must be free before placing a cell (0.05–0.95). "
        "Lower packs denser cells; higher rejects crowded peaks."
    ),
    "blob_min_peak_intensity": (
        "Require normalized image intensity at the peak ≥ this (0–1). 0 = off. "
        "Raise to ignore weak background peaks; lower/0 to keep dim but real cells."
    ),
    "blob_min_local_snr": (
        "Minimum local signal-to-noise: (mean_core − mean_surround) / std_surround. "
        "0 = off. Raise (e.g. 2–5) to reject bright-background patches that are not "
        "brighter than their neighbors; keeps real cells on dark background if they "
        "stand out locally. Typical starting values: 1.5–3.5."
    ),
    "blob_local_snr_outer": (
        "Outer ring scale for local SNR. Surround annulus runs from cell radius r to "
        "r × this value (default 2.0). Larger ring = more global background estimate."
    ),
    "blob_exclude_border": (
        "Ignore detections within this many pixels of the image edge. 0 keeps border cells."
    ),
    "adaptive_tile_size": (
        "Adaptive mode: size of analysis tiles (pixels). Smaller tiles adapt more to "
        "local background; larger tiles are smoother/faster. Typical 192–384."
    ),
    "adaptive_tile_overlap": (
        "Adaptive mode: fractional overlap between tiles (0–0.5). Higher overlap reduces "
        "edge misses when merging tile detections."
    ),
    "adaptive_sensitivity": (
        "Adaptive mode: global sensitivity multiplier. <1 → lower tile thresholds "
        "(more cells); >1 → stricter (fewer false positives). 1.0 = neutral."
    ),
    "adaptive_packing": (
        "Adaptive mode: 0 = sparse packing (require more free space, good for loose "
        "cells); 1 = dense packing (allow tighter clusters). Mid ~0.5 is balanced."
    ),
    "adaptive_dual_pass": (
        "Adaptive mode: 1 = run sensitive + strict passes and fuse (best for mixed "
        "high/low background); 0 = single adaptive pass only."
    ),
    "adaptive_base_method": (
        "Legacy field: base detector for adaptive mode. Runtime now follows the "
        "Blob/DoG radio when Adaptive is checked; this is kept for import/export only."
    ),
}


class ToolTip:
    """Simple delayed hover tooltip for Mask Settings controls."""

    def __init__(self, widget, text, delay_ms=450):
        self.widget = widget
        self.text = text or ""
        self.delay_ms = int(delay_ms)
        self._after_id = None
        self._tip = None
        if not self.text:
            return
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except Exception:
            pass

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        try:
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
            lbl = tk.Label(
                tip,
                text=self.text,
                justify=tk.LEFT,
                background="#ffffe0",
                foreground="#000000",
                relief=tk.SOLID,
                borderwidth=1,
                font=("Helvetica", 9),
                wraplength=340,
                padx=6,
                pady=4,
            )
            lbl.pack()
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def attach_param_tooltip(widget, attr_name, extra=None):
    """Attach PARAM_HELP tooltip for a config attribute name."""
    text = PARAM_HELP.get(attr_name, "")
    if extra:
        text = (text + " " + extra).strip() if text else extra
    if text:
        ToolTip(widget, text)


# Windows taskbar branding: must run *before* the first Tk() window is created.
# Without an explicit AppUserModelID, Windows groups BARCC under the host process
# (python.exe / Jupyter) and shows that host's icon instead of barcc_icon.ico.
_BARCC_APP_USER_MODEL_ID = "LaingLab.BARCC.RegionalIFAnalyzer"


def _configure_windows_app_identity():
    """Tell Windows this process is BARCC, not Python/Jupyter (taskbar icon + grouping)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _BARCC_APP_USER_MODEL_ID
        )
    except Exception:
        pass


# Configure logging
logging.basicConfig(
    level=logging.INFO,       # For normal operations and major steps
    # level=logging.WARNING,    # For recoverable errors
    # level=logging.DEBUG,        # For detailed operational information
    # level=logging.ERROR,      # For critical issues
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define configuration dataclasses and enums
@dataclass
class CellDetectionConfig:
    # Detection strategy
    # "blob" = LoG; "dog" = DoG; "watershed" = legacy
    # adaptive_enabled layers tiling/dual-pass/packing on blob or dog (not a separate method)
    detection_method: str = "blob"
    adaptive_enabled: int = 0  # 1 = adaptive mode on top of blob/dog; 0 = plain method

    # --- Legacy Watershed parameters (kept for fallback) ---
    threshold_method: str = "otsu"
    manual_threshold: float = 0.5
    adaptive_block_size: int = 101
    local_radius: int = 15
    min_cell_size: int = 20
    max_cell_size: int = 100
    circularity_threshold: float = 0.7
    min_peak_distance: int = 5
    peak_min_intensity: float = 0.1
    watershed_compactness: float = 0.0

    # --- Blob Detection (blob_log / blob_dog) parameters ---
    blob_min_sigma: float = 1.5      # lower default → catch smaller/tighter spots
    blob_max_sigma: float = 12.0     # higher → larger cells
    blob_num_sigma: int = 15         # more scales between min/max
    blob_threshold: float = 0.05     # lower → more sensitive (dim cells)
    blob_threshold_rel: float = 0.0  # 0 = off; else relative peak height (0–1)
    blob_overlap: float = 0.5
    blob_min_area: int = 8           # post-filter (radius-estimated disk area)
    blob_max_area: int = 500
    blob_min_circularity: float = 0.35  # 0 = off; reject elongated / edge-like local shapes
    blob_radius_scale: float = 1.8   # radius ≈ sigma * scale (disk drawn for mask)
    blob_free_space: float = 0.45    # fraction of disk that must be unclaimed to place
    blob_min_peak_intensity: float = 0.0  # 0 = off; require img[center] ≥ this (0–1)
    # Local SNR vs adjacent surround (core vs ring) — key for uneven background
    blob_min_local_snr: float = 0.0  # 0 = off; try 2–4 when high-bg false positives
    blob_local_snr_outer: float = 2.0  # outer radius = r * this (annulus for background)
    blob_exclude_border: int = 1     # pixels; 0 keeps border detections
    # Peak quality (reject tissue edges, high-BG texture, non-round blobs)
    blob_min_isotropy: float = 0.45  # 0 = off; 1 = perfect radial symmetry (try 0.35–0.6)
    blob_reject_tissue_edge: int = 1  # 1 = reject peaks on tissue/outside boundary
    blob_edge_dark_frac: float = 0.32  # reject if this fraction of outer ring is near-black
    blob_bg_relative: float = 0.12  # 0 = off; require peak − local_median ≥ this (0–1 norm)

    # --- Adaptive overlay (used when adaptive_enabled and method is blob/dog) ---
    adaptive_tile_size: int = 256       # tile edge length (px)
    adaptive_tile_overlap: float = 0.3  # fraction of tile overlap (0–0.5)
    adaptive_sensitivity: float = 1.0   # <1 more sensitive, >1 stricter (tile thresholds)
    adaptive_packing: float = 0.5       # 0=sparse (strict free space), 1=dense (loose)
    adaptive_dual_pass: int = 1         # 1=on: sensitive+strict fusion; 0=single pass
    # Kept for settings import/export; runtime base follows detection_method (blob/dog)
    adaptive_base_method: str = "blob"

@dataclass
class PreprocessingConfig:
    background_method: str = "tophat"  # Changed to tophat as default
    # Background correction methods
    disk_radius: int = 15        # Reduced radius for efficiency
    # Noise reduction
    denoise_method: str = "gaussian"
    bg_gaussian_sigma: float = 1.0
    nr_gaussian_sigma: float = 1.0
    median_kernel: int = 3
    bilateral_sigma_color: float = 0.1
    bilateral_sigma_space: float = 1.0
    # Contrast enhancement
    contrast_method: str = "stretch"
    clahe_kernel: int = 8
    clahe_clip_limit: float = 2.0
    gamma: float = 1.0
    # Signal enhancement
    enhance_method: str = "unsharp mask"
    unsharp_radius: float = 1.0
    unsharp_amount: float = 2.0

# beginning fleshing these out
class BrainImage:
    def __init__(self):
        self.original_image = None
        self.scaled_image = None
        self.background_image = None
        self.cell_mask = None
        self.regions = None
        self.paint = None
 

class CellMask:
    def __init__(self):
        self.combined_mask = None
        self.auto_mask = None
        self.add_mask = None
        self.remove_mask = None


class ImageProcessor:
    def __init__(self):
        self.cell_config = CellDetectionConfig()
        self.preprocess_config = PreprocessingConfig()
        self.load_config()

    def load_config(self):
        """Load configuration from file if it exists"""
        config_path = "barcc_config.yaml"
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                try:
                    config = yaml.safe_load(f)
                    if 'cell_detection' in config:
                        cell_config = config['cell_detection']
                        
                        for key, value in cell_config.items():
                            if hasattr(self.cell_config, key):
                                setattr(self.cell_config, key, value)
                               
                    if 'preprocessing' in config:
                        for key, value in config['preprocessing'].items():
                            if hasattr(self.preprocess_config, key):
                                setattr(self.preprocess_config, key, value)
                except Exception as e:
                    logger.error(f"Failed to load config: {e}", exc_info=True)

    def save_config(self):
        """Save current configuration to file"""
        try:
            # Convert enum to string before saving
            cell_config_dict = self.cell_config.__dict__.copy()
            
            config = {
                'cell_detection': cell_config_dict,
                'preprocessing': self.preprocess_config.__dict__
            }
            with open("barcc_config.yaml", 'w') as f:
                yaml.dump(config, f)
        except Exception as e:
            logger.error(f"Failed to save config: {e}", exc_info=True)

    def preprocess_image(self, image):
        """Apply preprocessing steps based on configuration"""
        logger.debug("Starting image preprocessing")
        img = np.array(image).astype(float) / 255.0
        
        try:
            # Background correction
            if self.preprocess_config.background_method == "tophat":
                logger.debug("Applying white tophat transform")
                from skimage.morphology import white_tophat, disk # not a fan of this
                selem = disk(self.preprocess_config.disk_radius)  # Using a smaller fixed radius for efficiency
                img = white_tophat(img, selem)
                logger.debug("White tophat transform completed successfully")
            elif self.preprocess_config.background_method == "gaussian":
                logger.debug("Using gaussian background subtraction")
                # Simple background estimation using gaussian blur
                from scipy.ndimage import gaussian_filter # not a fan of this
                background = gaussian_filter(img, sigma=self.preprocess_config.bg_gaussian_sigma)
                img = img - background
                img = np.clip(img, 0, 1)  # Normalize to [0,1] range
            else:
                logger.error("No valid background correction method, use either 'tophat' or 'gaussian'")
                logger.debug("Skipping background correction")
                pass  # No background correction
        except Exception as e:
            logger.error(f"Error in background correction: {str(e)}")
            # Fall back to no background correction
            logger.info("Falling back to no background correction")
            pass

        # Noise reduction
        if self.preprocess_config.denoise_method == "gaussian":
            logger.debug("Applying Gaussian noise reduction")
            img = filters.gaussian(img, sigma=self.preprocess_config.nr_gaussian_sigma)
        elif self.preprocess_config.denoise_method == "median":
            logger.debug("Applying median noise reduction")
            img = filters.median(img, footprint=disk(self.preprocess_config.median_kernel))
        elif self.preprocess_config.denoise_method == "bilateral":
            logger.debug("Applying bilateral noise reduction")
            img = restoration.denoise_bilateral(
                img,
                sigma_color=self.preprocess_config.bilateral_sigma_color,
                sigma_spatial=self.preprocess_config.bilateral_sigma_space
            )
        else:
            logger.error("No valid noise reduction, use either 'median', 'gaussian', or 'bilateral'")
            pass

        # Contrast enhancement
        if self.preprocess_config.contrast_method == "stretch":
            logger.debug("Applying contrast stretching")
            img = exposure.rescale_intensity(img)
        elif self.preprocess_config.contrast_method == "clahe":
            logger.debug("Applying CLAHE")
            img = exposure.equalize_adapthist(
                img,
                kernel_size=self.preprocess_config.clahe_kernel,
                clip_limit=self.preprocess_config.clahe_clip_limit
            )
        elif self.preprocess_config.contrast_method == "gamma":
            logger.debug("Applying gamma correction")
            img = exposure.adjust_gamma(img, self.preprocess_config.gamma)
        else:
            logger.error("No valid contrast enhancement, use either 'stretch', 'clahe', or 'gamma'")
            pass

        # Signal enhancement
        if self.preprocess_config.enhance_method == "unsharp mask":
            logger.debug("Applying unsharp mask")
            img = filters.unsharp_mask(
                img,
                radius=self.preprocess_config.unsharp_radius,
                amount=self.preprocess_config.unsharp_amount
            )
        else:
            logger.error("No valid signal enhancement, use 'unsharp mask'")
            pass

        return img

    def detect_cells(self, image):
        """Detect cells using current configuration.

        Strategies:
          - ``blob`` / ``log``: Laplacian of Gaussian (``blob_log``)
          - ``dog``: Difference of Gaussians (``blob_dog``)
          - ``watershed``: legacy threshold + watershed

        When ``adaptive_enabled`` is on and the method is blob/dog/log, the same
        base detector runs with tiled thresholds, dual-pass fusion, and density packing.
        Legacy settings with ``detection_method == "adaptive"`` are treated as
        adaptive_enabled + adaptive_base_method (or blob).
        """
        cfg = self.cell_config
        method = (cfg.detection_method or "blob").lower().strip()
        adaptive_on = int(getattr(cfg, "adaptive_enabled", 0) or 0) != 0

        # Back-compat: old saves used detection_method="adaptive" as the mode itself
        if method == "adaptive":
            adaptive_on = True
            base = (getattr(cfg, "adaptive_base_method", None) or "blob").lower().strip()
            method = base if base in ("blob", "dog", "log") else "blob"
            cfg.detection_method = method
            cfg.adaptive_enabled = 1

        logger.debug(
            f"Starting cell detection method={method} adaptive={adaptive_on}"
        )

        img = self.preprocess_image(image)

        if method in ("blob", "dog", "log"):
            if adaptive_on:
                # Base detector follows the selected radio (blob vs dog)
                cfg.adaptive_base_method = "dog" if method == "dog" else "blob"
                return self._detect_cells_adaptive(img)
            return self._detect_cells_blob(img)
        return self._detect_cells_watershed(img)

    def _as_gray2d_normalized(self, img: np.ndarray):
        """Return (work_n HxW float in ~0–1, original work array)."""
        work = np.asarray(img, dtype=np.float64)
        if work.ndim > 2:
            work = work[..., 0] if work.shape[-1] in (3, 4) else np.squeeze(work)
        if work.ndim != 2:
            work = np.atleast_2d(np.squeeze(work))
        if work.size == 0:
            return work, work
        wmin, wmax = float(np.min(work)), float(np.max(work))
        work_n = (work - wmin) / (wmax - wmin) if wmax > wmin else np.zeros_like(work)
        return work_n, work

    def _run_blob_detector(self, work_n, thr, method="blob", thr_rel=0.0):
        """Run LoG or DoG on a 2D normalized image; return (N,3) y,x,sigma or empty."""
        cfg = self.cell_config
        method = (method or "blob").lower().strip()
        thr = float(thr)
        thr_rel = float(thr_rel or 0.0)
        try:
            if method == "dog":
                dog_kw = dict(
                    min_sigma=float(cfg.blob_min_sigma),
                    max_sigma=float(cfg.blob_max_sigma),
                    threshold=thr,
                    overlap=float(cfg.blob_overlap),
                )
                if thr_rel > 0:
                    dog_kw["threshold_rel"] = thr_rel
                try:
                    return feature.blob_dog(work_n, **dog_kw)
                except TypeError:
                    dog_kw.pop("threshold_rel", None)
                    return feature.blob_dog(work_n, **dog_kw)
            log_kw = dict(
                min_sigma=float(cfg.blob_min_sigma),
                max_sigma=float(cfg.blob_max_sigma),
                num_sigma=int(cfg.blob_num_sigma),
                threshold=thr,
                overlap=float(cfg.blob_overlap),
                log_scale=False,
            )
            if thr_rel > 0:
                log_kw["threshold_rel"] = thr_rel
            try:
                return feature.blob_log(work_n, **log_kw)
            except TypeError:
                log_kw.pop("threshold_rel", None)
                return feature.blob_log(work_n, **log_kw)
        except Exception as e:
            logger.warning(f"blob detector failed ({method}): {e}")
            return np.zeros((0, 3))

    def _local_snr_at(self, image2d, yi, xi, radius, snr_outer=2.0):
        """(mean_core - mean_ring) / noise for adjacent surround."""
        h, w = image2d.shape[:2]
        r_in = max(1, int(radius))
        snr_outer = max(1.25, float(snr_outer))
        r_out = max(r_in + 1, int(round(r_in * snr_outer)))
        y0 = max(0, yi - r_out)
        y1 = min(h, yi + r_out + 1)
        x0 = max(0, xi - r_out)
        x1 = min(w, xi + r_out + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        d2 = (yy - yi) ** 2 + (xx - xi) ** 2
        core = d2 <= (r_in * r_in)
        ring = (d2 > (r_in * r_in)) & (d2 <= (r_out * r_out))
        patch = image2d[y0:y1, x0:x1]
        if int(core.sum()) < 3 or int(ring.sum()) < 5:
            return 0.0
        mu_in = float(np.mean(patch[core]))
        mu_out = float(np.mean(patch[ring]))
        if mu_in <= mu_out:
            return 0.0
        sd_out = float(np.std(patch[ring]))
        noise = max(sd_out, 0.04 * max(mu_out, 0.05), 1e-3)
        return (mu_in - mu_out) / noise

    def _local_median_at(self, image2d, yi, xi, radius):
        """Median intensity in a disk of given radius."""
        h, w = image2d.shape[:2]
        r = max(2, int(radius))
        y0, y1 = max(0, yi - r), min(h, yi + r + 1)
        x0, x1 = max(0, xi - r), min(w, xi + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        disk = (yy - yi) ** 2 + (xx - xi) ** 2 <= r * r
        vals = image2d[y0:y1, x0:x1][disk]
        if vals.size < 5:
            return float(image2d[yi, xi])
        return float(np.median(vals))

    def _peak_isotropy(self, image2d, yi, xi, radius):
        """Radial symmetry score in [0, 1]: 1 = isotropic bright blob.

        Samples mean intensity in 8 angular sectors of the annulus r/3..r.
        High variation across sectors ⇒ edge / fiber / tissue border.
        """
        h, w = image2d.shape[:2]
        r = max(3, int(radius))
        y0, y1 = max(0, yi - r), min(h, yi + r + 1)
        x0, x1 = max(0, xi - r), min(w, xi + r + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        dy = yy.astype(np.float64) - yi
        dx = xx.astype(np.float64) - xi
        d = np.sqrt(dy * dy + dx * dx)
        ann = (d >= r / 3.0) & (d <= r)
        if int(ann.sum()) < 12:
            return 1.0
        ang = np.arctan2(dy, dx)
        patch = image2d[y0:y1, x0:x1]
        sector_means = []
        for k in range(8):
            a0 = -np.pi + k * (np.pi / 4.0)
            a1 = a0 + np.pi / 4.0
            if k < 7:
                sec = ann & (ang >= a0) & (ang < a1)
            else:
                sec = ann & (ang >= a0) & (ang <= a1)
            if int(sec.sum()) < 2:
                continue
            sector_means.append(float(np.mean(patch[sec])))
        if len(sector_means) < 4:
            return 1.0
        sm = np.asarray(sector_means, dtype=np.float64)
        mu = float(np.mean(sm)) + 1e-6
        # isotropy = 1 - normalized std
        return float(np.clip(1.0 - (np.std(sm) / mu), 0.0, 1.0))

    def _peak_local_circularity(self, image2d, yi, xi, radius):
        """Circularity of the connected bright component around the peak (0–1)."""
        h, w = image2d.shape[:2]
        r = max(3, int(radius * 1.4))
        y0, y1 = max(0, yi - r), min(h, yi + r + 1)
        x0, x1 = max(0, xi - r), min(w, xi + r + 1)
        patch = np.asarray(image2d[y0:y1, x0:x1], dtype=np.float64)
        if patch.size < 16:
            return 1.0
        # Local adaptive threshold between core and surround
        cy, cx = yi - y0, xi - x0
        yy, xx = np.ogrid[0:patch.shape[0], 0:patch.shape[1]]
        d2 = (yy - cy) ** 2 + (xx - cx) ** 2
        r_in = max(1, int(radius * 0.6))
        core = d2 <= r_in * r_in
        ring = (d2 > r_in * r_in) & (d2 <= (radius * radius))
        if int(core.sum()) < 3 or int(ring.sum()) < 5:
            return 1.0
        thr = 0.5 * (float(np.mean(patch[core])) + float(np.mean(patch[ring])))
        binary = patch >= thr
        # Keep only component containing center
        lab = measure.label(binary, connectivity=2)
        cid = lab[cy, cx]
        if cid == 0:
            return 0.0
        comp = lab == cid
        area = float(comp.sum())
        if area < 4:
            return 0.0
        # Perimeter via erosion
        try:
            from skimage import morphology as _morph
            # skimage≥0.26: binary_erosion deprecated → use erosion
            try:
                eroded = _morph.erosion(comp, footprint=_morph.disk(1))
            except Exception:
                eroded = _morph.binary_erosion(comp)
            peri = float(comp.sum() - eroded.sum())
        except Exception:
            peri = float(np.sum(comp) - np.sum(comp[1:-1, 1:-1]))
        peri = max(peri, 1.0)
        circ = float(4.0 * np.pi * area / (peri * peri + 1e-8))
        return float(np.clip(circ, 0.0, 1.5))

    def _peak_on_tissue_edge(self, image2d, yi, xi, radius, max_dark_frac=0.32):
        """True if peak sits on tissue/outside border (bimodal outer ring).

        Pure dark-field interiors have a *uniformly* dark ring — that is NOT a
        tissue edge. Edges have both near-black (outside) and tissue-gray sectors.
        """
        h, w = image2d.shape[:2]
        r_in = max(2, int(radius))
        r_out = max(r_in + 2, int(round(r_in * 2.2)))
        y0, y1 = max(0, yi - r_out), min(h, yi + r_out + 1)
        x0, x1 = max(0, xi - r_out), min(w, xi + r_out + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        d2 = (yy - yi) ** 2 + (xx - xi) ** 2
        ring = (d2 > (r_in * r_in)) & (d2 <= (r_out * r_out))
        patch = image2d[y0:y1, x0:x1]
        vals = patch[ring]
        if vals.size < 12:
            return False
        # Absolute outside floor (true empty) vs local tissue level near the peak
        floor = float(np.percentile(image2d, 2))
        dark_thr = max(0.03, floor + 0.025)
        local_med = self._local_median_at(image2d, yi, xi, max(r_out, 8))
        # If the whole neighborhood is dark (dark-field interior), not an edge
        if local_med < 0.12 and float(np.percentile(vals, 75)) < 0.15:
            return False
        dark_frac = float(np.mean(vals < dark_thr))
        # Tissue-side of the ring: clearly brighter than outside
        tissue_thr = max(dark_thr + 0.05, 0.5 * local_med if local_med > 0.1 else 0.1)
        tissue_frac = float(np.mean(vals >= tissue_thr))
        max_dark = float(max_dark_frac)
        # Border signature: substantial outside AND substantial tissue in same ring
        if dark_frac >= max_dark and tissue_frac >= 0.20:
            return True
        # Strong one-sided edge: high dark fraction + poor isotropy handled elsewhere
        if dark_frac >= max(0.45, max_dark + 0.1) and tissue_frac >= 0.12:
            return True
        return False

    def _peak_quality_ok(self, image2d, yi, xi, radius, min_local_snr=0.0):
        """Return (ok: bool, snr: float) after shape / edge / relative-BG gates."""
        cfg = self.cell_config
        snr_outer = float(getattr(cfg, "blob_local_snr_outer", 2.0) or 2.0)
        snr = self._local_snr_at(image2d, yi, xi, radius, snr_outer)
        if min_local_snr > 0 and snr < min_local_snr:
            return False, snr

        peak_val = float(image2d[yi, xi])
        bg_rel = float(getattr(cfg, "blob_bg_relative", 0.0) or 0.0)
        local_med = self._local_median_at(image2d, yi, xi, max(radius * 2, 8))
        if bg_rel > 0:
            if (peak_val - local_med) < bg_rel:
                return False, snr

        # On high local background, require stronger SNR even if global min_snr is mild
        if local_med > 0.35:
            need = max(float(min_local_snr), 1.8 if local_med > 0.5 else 1.4)
            if snr < need:
                return False, snr
            if bg_rel <= 0 and (peak_val - local_med) < 0.08:
                return False, snr

        if int(getattr(cfg, "blob_reject_tissue_edge", 1) or 0):
            max_dark = float(getattr(cfg, "blob_edge_dark_frac", 0.32) or 0.32)
            if self._peak_on_tissue_edge(image2d, yi, xi, radius, max_dark_frac=max_dark):
                return False, snr

        min_iso = float(getattr(cfg, "blob_min_isotropy", 0.0) or 0.0)
        if min_iso > 0:
            iso = self._peak_isotropy(image2d, yi, xi, radius)
            if iso < min_iso:
                return False, snr

        min_circ = float(getattr(cfg, "blob_min_circularity", 0.0) or 0.0)
        if min_circ > 0:
            circ = self._peak_local_circularity(image2d, yi, xi, radius)
            if circ < min_circ:
                return False, snr

        return True, snr

    def _place_blob_peaks(
        self,
        work_n,
        blobs,
        free_need=None,
        min_local_snr=None,
        density_radii=None,
        packing=None,
    ):
        """Rasterize blob peaks to a labeled disk mask with optional density packing.

        packing: None = use free_need only; else 0–1 sparse→dense modulates free_need
        from local neighbor count in ``density_radii`` (list of (y,x,r) peaks).
        """
        cfg = self.cell_config
        if blobs is None or len(blobs) == 0:
            return np.zeros(work_n.shape[:2], dtype=int)

        h, w = work_n.shape[:2]
        labels = np.zeros((h, w), dtype=int)
        cell_id = 1
        radius_scale = float(getattr(cfg, "blob_radius_scale", 1.8) or 1.8)
        base_free = float(
            free_need
            if free_need is not None
            else (getattr(cfg, "blob_free_space", 0.45) or 0.45)
        )
        base_free = min(0.95, max(0.05, base_free))
        min_peak = float(getattr(cfg, "blob_min_peak_intensity", 0.0) or 0.0)
        if min_local_snr is None:
            min_local_snr = float(getattr(cfg, "blob_min_local_snr", 0.0) or 0.0)
        excl = int(getattr(cfg, "blob_exclude_border", 1) or 0)

        # Precompute neighbor density if packing adaptive
        peak_list = []
        for y, x, sigma in blobs:
            yi, xi = int(round(y)), int(round(x))
            if not (0 <= yi < h and 0 <= xi < w):
                continue
            radius = max(1, int(round(float(sigma) * radius_scale)))
            peak_list.append((yi, xi, radius, float(sigma), float(work_n[yi, xi])))

        # Sort by intensity descending
        peak_list.sort(key=lambda t: t[4], reverse=True)

        # Neighbor counts for density packing (within 3*mean radius)
        n_nb = [0] * len(peak_list)
        if packing is not None and len(peak_list) > 1:
            coords = np.array([(p[0], p[1]) for p in peak_list], dtype=np.float64)
            mean_r = float(np.mean([p[2] for p in peak_list]))
            nb_r = max(8.0, 3.0 * mean_r)
            nb_r2 = nb_r * nb_r
            for i in range(len(peak_list)):
                d2 = (coords[:, 0] - coords[i, 0]) ** 2 + (coords[:, 1] - coords[i, 1]) ** 2
                n_nb[i] = int(np.sum((d2 > 0) & (d2 <= nb_r2)))

        pack = None if packing is None else float(np.clip(packing, 0.0, 1.0))

        for i, (yi, xi, radius, sigma, peak_val) in enumerate(peak_list):
            if excl > 0 and (yi < excl or xi < excl or yi >= h - excl or xi >= w - excl):
                continue
            if min_peak > 0 and peak_val < min_peak:
                continue
            area = int(np.pi * radius * radius)
            if not (cfg.blob_min_area <= area <= cfg.blob_max_area):
                continue

            ok, snr = self._peak_quality_ok(
                work_n, yi, xi, radius, min_local_snr=min_local_snr
            )
            if not ok:
                continue

            # Density-aware free-space: dense neighbors → lower free_need
            free_need_i = base_free
            if pack is not None:
                dens = min(1.0, n_nb[i] / 6.0)  # denser clusters scale faster
                dens_eff = 0.4 * pack + 0.6 * dens
                free_need_i = base_free * (1.0 - 0.7 * dens_eff)
                # High-SNR peaks in clusters may pack tighter
                if snr >= 1.5 and dens > 0.4:
                    free_need_i *= 0.75
                free_need_i = min(0.9, max(0.08, free_need_i))
            elif n_nb[i] >= 3:
                # Even without packing flag: slight ease in dense groups
                free_need_i = max(0.12, base_free * 0.7)

            y0 = max(0, yi - radius)
            y1 = min(h, yi + radius + 1)
            x0 = max(0, xi - radius)
            x1 = min(w, xi + radius + 1)
            yy, xx = np.ogrid[y0:y1, x0:x1]
            disk_local = (yy - yi) ** 2 + (xx - xi) ** 2 <= radius * radius
            free_local = disk_local & (labels[y0:y1, x0:x1] == 0)
            n_disk = int(disk_local.sum())
            n_free = int(free_local.sum())
            if n_disk < 1 or n_free < int(n_disk * free_need_i):
                continue
            labels[y0:y1, x0:x1][free_local] = cell_id
            cell_id += 1

        return labels

    def _detect_cells_blob(self, img: np.ndarray):
        """Blob detection via LoG (blob_log) or DoG (blob_dog)."""
        cfg = self.cell_config
        method = (cfg.detection_method or "blob").lower().strip()
        work_n, _ = self._as_gray2d_normalized(img)
        if work_n.size == 0:
            return img, np.zeros(work_n.shape[:2], dtype=int)

        thr = float(cfg.blob_threshold)
        thr_rel = float(getattr(cfg, "blob_threshold_rel", 0.0) or 0.0)
        blobs = self._run_blob_detector(work_n, thr, method=method, thr_rel=thr_rel)
        if blobs is None or len(blobs) == 0:
            return img, np.zeros(work_n.shape, dtype=int)
        labels = self._place_blob_peaks(work_n, blobs)
        return img, labels

    def _detect_cells_adaptive(self, img: np.ndarray):
        """Adaptive detection for mixed background and density on one slice.

        1. Tile the image; set each tile's blob threshold from local intensity stats
           scaled by ``adaptive_sensitivity`` and the global ``blob_threshold``.
        2. Optional dual-pass: sensitive (lower thr) + strict (higher thr + SNR).
        3. Merge peaks (NMS by proximity) and place with density-aware free_space.
        """
        cfg = self.cell_config
        work_n, _ = self._as_gray2d_normalized(img)
        if work_n.size == 0:
            return img, np.zeros((0, 0), dtype=int)

        h, w = work_n.shape[:2]
        tile = max(64, int(getattr(cfg, "adaptive_tile_size", 256) or 256))
        overlap = float(getattr(cfg, "adaptive_tile_overlap", 0.3) or 0.0)
        overlap = min(0.5, max(0.0, overlap))
        step = max(32, int(round(tile * (1.0 - overlap))))
        sens = float(getattr(cfg, "adaptive_sensitivity", 1.0) or 1.0)
        sens = min(3.0, max(0.25, sens))
        packing = float(getattr(cfg, "adaptive_packing", 0.5) or 0.5)
        dual = int(getattr(cfg, "adaptive_dual_pass", 1) or 0) != 0
        base_method = (getattr(cfg, "adaptive_base_method", None) or "blob").lower().strip()
        if base_method not in ("blob", "dog", "log"):
            base_method = "blob"
        base_thr = float(cfg.blob_threshold)
        thr_rel = float(getattr(cfg, "blob_threshold_rel", 0.0) or 0.0)
        min_snr = float(getattr(cfg, "blob_min_local_snr", 0.0) or 0.0)

        def _tile_threshold(tile_img, pass_scale=1.0):
            """Map local brightness/noise → blob threshold."""
            t = np.asarray(tile_img, dtype=np.float64)
            if t.size < 16:
                return base_thr * sens * pass_scale
            p50 = float(np.percentile(t, 50))
            p90 = float(np.percentile(t, 90))
            p99 = float(np.percentile(t, 99))
            dynamic = max(p99 - p50, 1e-4)
            clutter = p50 / (p90 + 1e-4)
            thr = base_thr * sens * pass_scale
            thr *= 1.0 + 1.0 * clutter  # stronger raise on high-BG tiles
            # Dim tiles: much more sensitive so dark-field cells survive
            if p90 < 0.22:
                thr *= 0.55
            elif p90 < 0.35:
                thr *= 0.72
            elif p90 > 0.55:
                thr *= 1.25
            band = t[(t >= p50) & (t <= p90)]
            if band.size > 20:
                thr *= 1.0 + 0.4 * min(1.0, float(np.std(band)) / (dynamic + 1e-4))
            return float(np.clip(thr, 0.002, 0.55))

        def _tile_snr_floor(tile_img, base_floor):
            """Raise SNR floor on bright tiles; ease on dark tiles."""
            t = np.asarray(tile_img, dtype=np.float64)
            if t.size < 16:
                return base_floor
            p50 = float(np.percentile(t, 50))
            floor = float(base_floor)
            if p50 > 0.45:
                floor = max(floor, 2.2 if base_floor > 0 else 2.0)
            elif p50 > 0.30:
                floor = max(floor, 1.5 if base_floor > 0 else 1.3)
            elif p50 < 0.12:
                # Dark field: only mild local contrast required
                floor = min(floor, 0.9) if floor > 0 else 0.7
            return floor

        def _collect_pass(pass_scale, snr_floor, quality_gate=True):
            peaks = []  # (y, x, sigma, score)
            rscale = float(getattr(cfg, "blob_radius_scale", 1.8) or 1.8)
            for y0 in range(0, h, step):
                for x0 in range(0, w, step):
                    y1 = min(h, y0 + tile)
                    x1 = min(w, x0 + tile)
                    if y1 - y0 < tile // 3 and y0 > 0:
                        continue
                    if x1 - x0 < tile // 3 and x0 > 0:
                        continue
                    tile_img = work_n[y0:y1, x0:x1]
                    thr = _tile_threshold(tile_img, pass_scale=pass_scale)
                    tile_snr = _tile_snr_floor(tile_img, snr_floor)
                    blobs = self._run_blob_detector(
                        tile_img, thr, method=base_method, thr_rel=thr_rel
                    )
                    if blobs is None or len(blobs) == 0:
                        continue
                    for by, bx, sig in blobs:
                        yi = int(round(by)) + y0
                        xi = int(round(bx)) + x0
                        if not (0 <= yi < h and 0 <= xi < w):
                            continue
                        margin = 4
                        borderish = (
                            (y0 > 0 and yi < y0 + margin)
                            or (x0 > 0 and xi < x0 + margin)
                            or (y1 < h and yi >= y1 - margin)
                            or (x1 < w and xi >= x1 - margin)
                        )
                        r = max(1, int(round(float(sig) * rscale)))
                        # Quality gate early (isotropy / edge / high-BG)
                        if quality_gate:
                            ok, snr = self._peak_quality_ok(
                                work_n, yi, xi, r, min_local_snr=tile_snr
                            )
                            if not ok:
                                continue
                        elif tile_snr > 0:
                            if self._local_snr_at(work_n, yi, xi, r) < tile_snr:
                                continue
                            snr = self._local_snr_at(work_n, yi, xi, r)
                        else:
                            snr = self._local_snr_at(work_n, yi, xi, r)
                        # Score: prefer high local SNR and interior peaks
                        score = float(work_n[yi, xi]) * (1.0 + 0.15 * snr)
                        if borderish:
                            score *= 0.85
                        peaks.append((yi, xi, float(sig), score))
            return peaks

        def _nms_peaks(peaks, min_dist_factor=0.65):
            if not peaks:
                return np.zeros((0, 3))
            peaks = sorted(peaks, key=lambda p: p[3], reverse=True)
            kept = []
            rscale = float(getattr(cfg, "blob_radius_scale", 1.8) or 1.8)
            for yi, xi, sig, score in peaks:
                r = max(1, int(round(float(sig) * rscale)))
                # Tighter NMS for high-score (real) peaks allows denser packing
                mdf = min_dist_factor
                if score > 0.5:
                    mdf = min(mdf, 0.55)
                min_d = max(1.5, mdf * r)
                min_d2 = min_d * min_d
                ok = True
                for ky, kx, ks, _ in kept:
                    if (yi - ky) ** 2 + (xi - kx) ** 2 < min_d2:
                        ok = False
                        break
                if ok:
                    kept.append((yi, xi, sig, score))
            if not kept:
                return np.zeros((0, 3))
            return np.array([[p[0], p[1], p[2]] for p in kept], dtype=np.float64)

        # Pass A: sensitive (dark-bg / low-contrast cells)
        # Pass B: strict (high-bg clutter)
        if dual:
            sens_scale = 0.50 / sens
            strict_scale = 1.45 * sens
            snr_strict = max(min_snr, 1.8) if min_snr > 0 else 1.8
            snr_sens = max(0.6, min_snr * 0.45) if min_snr > 0 else 0.7
            peaks_a = _collect_pass(sens_scale, snr_sens, quality_gate=True)
            peaks_b = _collect_pass(strict_scale, snr_strict, quality_gate=True)
            fused = list(peaks_b)
            for p in peaks_a:
                yi, xi, sig, score = p
                r = max(
                    1,
                    int(round(sig * float(getattr(cfg, "blob_radius_scale", 1.8) or 1.8))),
                )
                min_d2 = (max(1.5, 0.7 * r)) ** 2
                if any((yi - q[0]) ** 2 + (xi - q[1]) ** 2 < min_d2 for q in peaks_b):
                    continue
                fused.append(p)
            blobs = _nms_peaks(fused, min_dist_factor=0.6)
            # Placement: mild SNR; quality gates re-apply in _place_blob_peaks
            snr_place = max(0.5, snr_sens * 0.8)
        else:
            peaks = _collect_pass(1.0 * sens, max(min_snr, 0.8) if min_snr > 0 else 0.8)
            blobs = _nms_peaks(peaks)
            snr_place = min_snr if min_snr > 0 else 0.5

        if blobs is None or len(blobs) == 0:
            return img, np.zeros((h, w), dtype=int)

        # Prefer denser packing under adaptive (clusters)
        pack_use = packing if packing is not None else 0.5
        pack_use = max(pack_use, 0.55)
        labels = self._place_blob_peaks(
            work_n,
            blobs,
            free_need=min(
                float(getattr(cfg, "blob_free_space", 0.45) or 0.45),
                0.35,
            ),
            min_local_snr=snr_place,
            packing=pack_use,
        )
        logger.info(
            f"Adaptive detection: tiles~{tile}px dual={dual} method={base_method} "
            f"peaks_in={len(blobs)} cells={int(labels.max())} sens={sens} pack={packing}"
        )
        return img, labels

    def _detect_cells_watershed(self, img: np.ndarray):
        """Legacy detection method (kept for compatibility)."""
        cfg = self.cell_config

        # Thresholding
        if cfg.threshold_method == "otsu":
            thresh = filters.threshold_otsu(img)
        elif cfg.threshold_method == "adaptive":
            thresh = filters.threshold_local(img, block_size=cfg.adaptive_block_size)
        elif cfg.threshold_method == "local":
            thresh = filters.threshold_local(
                img, block_size=cfg.local_radius * 2 + 1, method='gaussian'
            )
        elif cfg.threshold_method == "manual":
            thresh = cfg.manual_threshold
        else:
            thresh = 0

        binary = img > thresh

        # Size and shape filtering
        labeled = measure.label(binary)
        props = measure.regionprops(labeled)

        mask = np.zeros_like(binary)
        for prop in props:
            if (cfg.min_cell_size <= prop.area <= cfg.max_cell_size and
                    prop.perimeter ** 2 / (4 * np.pi * prop.area) <= 1 / cfg.circularity_threshold):
                mask[tuple(prop.coords.T)] = True

        # Watershed
        distance = distance_transform_edt(mask)
        coords = feature.peak_local_max(
            distance,
            min_distance=cfg.min_peak_distance,
            threshold_abs=cfg.peak_min_intensity,
            exclude_border=True
        )

        markers = np.zeros_like(distance, dtype=bool)
        markers[tuple(coords.T)] = True
        markers = measure.label(markers)

        labels = segmentation.watershed(
            -distance,
            markers,
            mask=mask,
            compactness=cfg.watershed_compactness
        )

        return img, labels

# This is old so we should drop it to prevent obscurity
def binary_mask_cell_count(background_pil, processor=None):
    """Enhanced cell detection using ImageProcessor class.
    If processor is provided, use its current config (important for live Mask Settings + Autotune).
    """
    if processor is None:
        processor = ImageProcessor()
    img, labels = processor.detect_cells(background_pil)
    return img, labels > 0
    

def split_stacked_tiff(file_path):
# Inputs a stacked tiff file and produces a subfolder in the same directory with 
# the unstacked tiffs

    if os.path.isfile(file_path) == False:
        logger.warning('File does not exist, Exiting')
        return

    abs_path = os.path.abspath(file_path)
    img = Image.open(abs_path)
    num_of_tiffs = img.n_frames

    if num_of_tiffs < 1:
        logger.warning('No Tiff Found, Exiting')
        return
    if num_of_tiffs < 2:
        logger.warning('Tiff Not Stacked // No Stacked Tiff Found, Exiting')
        return
    # absolute path without file extention (.tiff)
    full_file_name, ext = os.path.splitext(abs_path) 
    # file name without extention
    file_name = os.path.basename(full_file_name)
    # absolute path of save directory
    save_dir = full_file_name + '_split_imgs'

    if os.path.isdir(save_dir):
        logger.error('Save directory already exists, Exiting')
        return

    os.mkdir(save_dir)

    for i in range (num_of_tiffs):
        try:
            img.seek(i)
            save_name = file_name + f'_ch{i}.tiff'
            full_save_name = os.path.join(save_dir, save_name)
            img.save(full_save_name)
        except EOFError: #end of file error
            logger.debug('Number of splits caused an error, Exiting')
            return



class PDFViewer:
    def __init__(self):
        logger.info("Initializing PDFViewer")
        # AppUserModelID before Tk so the taskbar does not inherit Jupyter/python branding
        _configure_windows_app_identity()
        self.root = tk.Tk()
        self.master = self.root
        self.master.title('Regional IF Analyzer')
        self.master.geometry('%dx%d' % (self.master.winfo_screenwidth(), self.master.winfo_screenheight()))
        self.master.resizable(True, True)
        self.master.rowconfigure(0, weight=1)
        self.master.rowconfigure(1, weight=0)
        self.master.columnconfigure(0, weight=1)

        # App logo (antibody + fluorophore) for title bar and Windows taskbar
        self._set_app_icon()
        # Re-apply after the HWND exists / is mapped (first paint is when taskbar picks icon)
        try:
            self.master.after_idle(self._set_app_icon)
            self.master.after(200, self._set_app_icon)
            self.master.after(800, self._set_app_icon)
        except Exception:
            pass

        # Subsystems
        self.pdf_handler = PDFHandler()
        self.state_manager = StateManager()
        self.image_processor = ImageProcessor()

        # App state
        self.path = None
        self.doc = None
        self.current_page = 0
        self.num_pages = 0
        self.zoom = 1.0
        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}

        # Per-region atlas editing (new feature for adjusting individual atlas region shapes)
        self.selected_zone_id = None
        self.selected_page = None
        # For Allen (and multi-blob zones): only the connected component under the click
        # is highlighted — avoids lighting up both mirrored hemispheres when IDs are shared.
        self.selected_zone_component = None  # optional bool ndarray same shape as mask

        # Undo/state
        self.undo_stack = self.state_manager.undo_stack

        # Paint variables
        self.brush_size = tk.IntVar(value=4.0)
        self.DEFAULT_COLOR = 'black'

        # Grouped paint strokes: each continuous mouse-down to mouse-up is one "structural boundary"
        self._paint_group_counter = 0
        self.current_paint_group = None
        self.named_paint_groups = {}   # group_tag (e.g. 'paintgroup_5') -> name
        self.paint_group_data = {}     # durable: group_tag -> list of {'coords': [x1,y1,...], 'width': w}  (survives show_page/delete("all"))

        # For painted regions that have been named: store the boundary outline so that
        # edge/border deformation can refit the visible black drawn line to the new mask shape.
        self.painted_zone_outlines = {}  # zid -> {'points': [(x,y), ...] in model space, 'width': int }

        # Crop / edit variables
        self.crop_mode = False
        self.crop_mode_var = tk.BooleanVar(value=False)
        self.crop_rect = None          # primary outline canvas id (legacy name)
        self.crop_ui_ids = []          # all crop overlay canvas ids
        self.crop_box = None           # (left, top, right, bottom) canvas coords when set
        self.crop_pending = False      # selection drawn; waiting for move / apply
        self._crop_interaction = None  # None | 'draw' | 'move'
        self._crop_draw_anchor = None  # (x, y) canvas start of rubber-band
        self._crop_move_origin = None  # (x, y) canvas pointer at move start
        self._crop_box_at_move_start = None
        self.start_x = None
        self.start_y = None

        self.edit_mode = False
        self.edit_mode_var = tk.BooleanVar(value=False)
        self.img_x = 0
        self.img_y = 0
        self.drag_start_x = None
        self.drag_start_y = None

        # Mask editing state
        self.editing_mask = False
        self.mask_edit_add = True  # True = add cells, False = remove cells
        self.splitting_cells = False  # True = Split Cell click mode
        self.current_mask = None   # reference to the current mask being edited
        self.auto_mask = None
        self.showing_auto_mask = False

        # Measure Tune — TP/FP/FN/TN click labeling → detection parameters
        self.measure_tune_active = False
        self.measure_tune_label = "tp"  # tp | fp | fn | tn
        self.measure_tune_samples = []  # list of {label, feat, x, y}
        self.measure_tune_markers = []  # canvas item ids
        self.measure_tune_status_var = None
        self.measure_tune_detail_var = None
        self.measure_tune_counts_var = None
        self.measure_tune_label_var = None
        self.measure_tune_status_window = None
        self.measure_tune_settings_geometry = None
        self._measure_tune_img = None
        self._measure_tune_scale = 1.0
        # Persisted for Smart Suggest (like area_tune_result)
        self.measure_tune_result = None

        # Area Tune (draw one diameter line per cell × N → set blob min/max area)
        self.area_tune_active = False
        self.area_tune_n_cells = 10
        self.area_tune_start = None  # (x, y) image coords for current drag
        self.area_tune_end = None
        self.area_tune_current_line_id = None  # rubber-band line while dragging
        self.area_tune_measurements = []  # list of dicts: diameter, area, start, end
        self.area_tune_line_ids = []  # committed canvas line item ids
        self.area_tune_markers = []  # endpoint/label item ids
        self.area_tune_status_window = None
        self.area_tune_status_var = None
        self.area_tune_detail_var = None
        self.area_tune_settings_geometry = None
        # Last completed Area Tune result (kept for Smart Suggest); not cleared on UI cleanup
        self.area_tune_result = None
        # Smart Suggest session history (trajectory-aware recipes)
        self._smart_suggest_history = []

        # View zoom (separate from PDF render zoom)
        self.view_scale = 1.0
        self.min_scale = 0.2
        self.max_scale = 8.0

        # Display options
        self.show_zone_labels_var = tk.BooleanVar(value=False)
        self.zone_counts_window = None
        self.show_zone_intensity_labels_var = tk.BooleanVar(value=False)
        self.zone_intensity_window = None
        self.last_intensity_df = None  # region intensity table for on-canvas labels
        # Last options used for axon/PNN intensity correction (remembered in-session)
        self._intensity_corr_prefs = {
            "use_bg": False,
            "bg_percentile": 10.0,
            "use_norm": False,
            "norm_path": "",
        }

        # Transparent menu / window mode
        self.transparent_mode = tk.BooleanVar(value=False)
        self.transparent_windows = []  # popups that should follow transparent mode

        # Atlas ribbon visibility and state (must be created before _build_gui so View menu can reference it)
        self.show_atlas_ribbon = tk.BooleanVar(value=True)
        self.atlas_ribbon_expanded = False
        self.border_mode_var = tk.BooleanVar(value=False)
        self.region_move_mode = tk.BooleanVar(value=False)
        self.region_translate_active = False
        self.count_button_packed = False
        self.count_button = None
        self.region_translate_zid = None
        self.region_translate_start_mx = 0.0
        self.region_translate_start_my = 0.0
        self.region_translate_original_mask = None
        self.region_list_id_map = {}

        # Paint mode indicator (updated in start_paint / stop_paint and similar)
        self.paint_status_var = tk.StringVar(value="Paint: off")

        # Persistent paint layer (this is the key to zoom-safe painting)
        self.paint_layer = None  # RGBA PIL Image, created when background is loaded

        # Manual edit masks
        self.manual_add_mask = None
        self.manual_remove_mask = None

        # Background (TIFF) image
        self.background_image = None
        self.original_background = None
        self.bg_photo_id = None
        self.atlas_filetype = None
        self.allen_zone_meta = {}  # page -> {local_zid: Allen structure metadata}
        self.allen_nissl_reference = None  # pure Nissl PIL for 30% reference strip
        self.allen_nissl_photo = None  # PhotoImage keep-alive
        self.allen_borders_pure = None  # pure black structure borders (re-composited after fills)

        # TIFF filename
        self.tiff_filename = None
        self.tiff_dir = None

        # File browser
        self.current_tiff_directory = None
        self.tiff_file_list = []   # list of full paths (source TIFFs only)
        self.current_tiff_path = None  # full path of the TIFF currently open in the viewer
        self._tree_path_to_iid = {}  # normalized path -> tree iid (for highlight)

        # Last DF for counts
        self.last_df = None
        self.last_cell_mask = None  # for flattened save including masked cells
        # When True, Count Cells / Show Mask reuse auto_mask (loaded or locked) without re-detecting
        self.cell_mask_locked = False
        self.cell_mask_source_path = None
        # Ground-truth vs random null distribution (cyan overlay; GT stays red)
        self.random_cell_mask = None
        self.random_cell_labels = None  # int32 label map (1..N matched pairs)
        self.random_cell_mask_meta = None  # dict: n_cells, stratified, seed, etc.
        # Perineuronal (PNN) shells: outer disk area = 2× cell area, minus cell body
        self.perineuronal_mask = None           # bool union (GT cells)
        self.perineuronal_labels = None         # int32 label map (GT cell id)
        self.perineuronal_cells = None          # list of cell records
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None
        self.perineuronal_area_factor = 2.0

        # Brightness
        self.brightness = 0.0
        self._brightness_after_id = None  # debounce handle for slider
        # Cache: display-sized background *without* brightness (keyed by scale + image id)
        self._bg_display_base_cache = None  # (key, PIL.Image)

        # Mouse state tracking
        self.current_state = None

        # Init windows (not needed, init windows when spawned)
#       self.brush_win = None

        # Build GUI
        self._build_gui()
        self.init_keybinds()

        self._update_paint_indicator()
        # Restore last working folder (Phase A file browser)
        try:
            self._restore_ui_prefs()
        except Exception as e:
            logger.warning(f"Could not restore UI prefs: {e}")

        self.root.mainloop()

    def init_keybinds(self):
        # Keyboard shortcuts
        self.master.bind('<q>', self.quit)
        self.master.bind('<Control-z>', self._undo_event)
        self.master.bind('<Control-s>', self.save_flattened_image)
        # Enter: apply pending crop first (must not toggle Crop checkbutton)
        self.master.bind('<Return>', self._on_return_key)
        self.master.bind('<KP_Enter>', self._on_return_key)
        self.master.bind('<Escape>', self._on_escape_key)
        try:
            self.output.bind('<Return>', self._on_return_key)
            self.output.bind('<KP_Enter>', self._on_return_key)
            self.output.bind('<Escape>', self._on_escape_key)
        except Exception:
            pass
        # ttk.Checkbutton activates on Return by default — that turns Crop OFF and
        # discards the pending box. Override class binding so Enter applies crop.
        try:
            self.master.bind_class("TCheckbutton", "<Return>", self._on_return_key)
            self.master.bind_class("TCheckbutton", "<KP_Enter>", self._on_return_key)
            self.master.bind_class("Checkbutton", "<Return>", self._on_return_key)
            self.master.bind_class("Checkbutton", "<KP_Enter>", self._on_return_key)
        except Exception:
            pass
        # File browser navigation (Phase A)
        self.master.bind('<Control-Left>', self._nav_previous_image_event)
        self.master.bind('<Control-Right>', self._nav_next_image_event)
        self.master.bind('<Control-Shift-Right>', self._nav_next_uncounted_event)

        # Bind click event for highlighting
        self.output.bind("<Button-1>", self.highlight_region)

    def _set_app_icon(self):
        """Set the Regional IF Analyzer logo on the window and Windows taskbar.

        Uses Application/assets/barcc_icon.ico (taskbar) plus multi-size PNG
        PhotoImages via iconphoto. Keeps strong references so Tk does not GC the
        icon (a common reason the taskbar falls back to the default Tk feather).

        On Windows, also sets AppUserModelID and WM_SETICON on the top-level HWND
        so the taskbar does not keep the Jupyter/python host icon.
        """
        self._app_icons = []  # strong refs for PhotoImage
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            assets = os.path.join(base, "assets")
            ico_path = os.path.abspath(os.path.join(assets, "barcc_icon.ico"))
            png_path = os.path.abspath(os.path.join(assets, "barcc_icon.png"))

            # Re-assert process identity (safe if already set; helps late launches)
            _configure_windows_app_identity()

            # Windows: .ico is the most reliable for the taskbar / Alt-Tab
            if os.path.isfile(ico_path):
                try:
                    # default= applies to this and future Toplevels
                    self.master.iconbitmap(default=ico_path)
                except Exception:
                    try:
                        self.master.iconbitmap(ico_path)
                    except Exception as e:
                        logger.debug(f"iconbitmap failed: {e}")
                # Force taskbar / Alt-Tab icon via Win32 (Tk alone often leaves host icon)
                self._apply_windows_taskbar_icon(ico_path)

            # Cross-platform / title-bar: multi-resolution PhotoImages
            icon_photos = []
            if os.path.isfile(png_path):
                try:
                    pil = Image.open(png_path).convert("RGBA")
                    for sz in (16, 24, 32, 48, 64):
                        resized = pil.resize((sz, sz), Image.LANCZOS)
                        icon_photos.append(ImageTk.PhotoImage(resized))
                except Exception as e:
                    logger.debug(f"icon PNG load failed: {e}")

            if not icon_photos:
                # Fallback: draw antibody + fluorophore in-memory (same motif)
                icon_img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(icon_img)
                draw.ellipse((2, 2, 61, 61), fill=(18, 28, 48, 255))
                draw.line((32, 20, 32, 36), fill=(240, 248, 255, 255), width=4)
                draw.line((32, 36, 16, 56), fill=(240, 248, 255, 255), width=4)
                draw.line((32, 36, 48, 56), fill=(240, 248, 255, 255), width=4)
                draw.ellipse((22, 6, 42, 26), fill=(57, 255, 20, 255), outline=(20, 160, 40, 255))
                for sz in (16, 32, 48):
                    icon_photos.append(
                        ImageTk.PhotoImage(icon_img.resize((sz, sz), Image.LANCZOS))
                    )

            if icon_photos:
                self._app_icons = icon_photos
                try:
                    self.master.iconphoto(True, *icon_photos)
                except TypeError:
                    # Older Tk: single image only
                    self.master.iconphoto(True, icon_photos[0])
                except Exception as e:
                    logger.debug(f"iconphoto failed: {e}")
        except Exception as e:
            logger.warning(f"Could not set application icon: {e}")

    def _apply_windows_taskbar_icon(self, ico_path):
        """Load barcc_icon.ico onto the real top-level HWND (Windows taskbar / Alt-Tab)."""
        if sys.platform != "win32" or not ico_path or not os.path.isfile(ico_path):
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            # Ensure window handle exists
            try:
                self.master.update_idletasks()
            except Exception:
                pass

            hwnd = int(self.master.winfo_id())
            # Tk often reports a child frame; climb to the top-level window
            GA_ROOT = 2
            try:
                root = user32.GetAncestor(hwnd, GA_ROOT)
                if root:
                    hwnd = int(root)
            except Exception:
                try:
                    parent = user32.GetParent(hwnd)
                    if parent:
                        hwnd = int(parent)
                except Exception:
                    pass

            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            # LoadImageW needs a unicode path
            ico_w = os.path.abspath(ico_path)

            LoadImageW = user32.LoadImageW
            LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            LoadImageW.restype = wintypes.HANDLE

            hicon_big = LoadImageW(
                None, ico_w, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )
            hicon_small = LoadImageW(None, ico_w, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if not hicon_big and not hicon_small:
                # Fallback: system metrics sizes
                try:
                    cx = user32.GetSystemMetrics(11)  # SM_CXICON
                    cy = user32.GetSystemMetrics(12)  # SM_CYICON
                    hicon_big = LoadImageW(
                        None, ico_w, IMAGE_ICON, cx, cy, LR_LOADFROMFILE
                    )
                except Exception:
                    pass
            if not hicon_big and not hicon_small:
                return

            SendMessageW = user32.SendMessageW
            if hicon_small:
                SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
            if hicon_big:
                SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
            # Prevent GC of HICONs while the app runs
            self._win_hicons = [h for h in (hicon_small, hicon_big) if h]
        except Exception as e:
            logger.debug(f"WM_SETICON taskbar icon failed: {e}")

    def quit(self, _):
        self.root.destroy()

    def disable_event(self):
        pass

    def _build_gui(self):
        # Menu
        self.menu = tk.Menu(self.master)
        self.master.config(menu=self.menu)

        # Create File menu dropdown 
        filemenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="File", menu=filemenu)
        filemenu.add_command(label="Split Tiff", command=self.split_tiff)
        filemenu.add_command(label="Import Tiff", command=self.import_tiff)
        filemenu.add_command(label="Import Paint", command=self.open_paint)
        filemenu.add_command(label="Save Atlas Schematic…", command=self.save_atlas_schematic)
        filemenu.add_command(label="Load Atlas Schematic…", command=self.load_atlas_schematic)
        filemenu.add_command(label="Save Flattened Image", command=self.save_flattened_image)
        filemenu.add_separator()
        filemenu.add_command(label="Previous Image", command=self.previous_image, accelerator="Ctrl+Left")
        filemenu.add_command(label="Next Image", command=self.next_image, accelerator="Ctrl+Right")
        filemenu.add_command(label="Next Uncounted", command=self.next_uncounted_image, accelerator="Ctrl+Shift+Right")
        filemenu.add_command(label="Next Channel…", command=self.next_channel)
        filemenu.add_command(label="Clear Canvas", command=self.clear_canvas_session)
        filemenu.add_separator()
        filemenu.add_command(label="User Manual", command=self.open_user_manual)
        filemenu.add_command(label="Exit", command=self.master.destroy)

        # Create Edit menu dropdown
        editmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Edit", menu=editmenu)
        editmenu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        editmenu.add_separator()
        # Add save paint command and create toplevels with widgets
        editmenu.add_command(label="Brightness", command=self.show_brightness_settings)
        editmenu.add_command(label="Save Picture", command=self.save_flattened_image)
        # editmenu.add_command(label="Save Paint", command=print("Save Paint", file=sys.stderr))

        # Create Atlas menu dropdown
        atlasmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Atlas", menu=atlasmenu)
        atlasmenu.add_command(label="Import Atlas (PDF)", command=self.import_atlas)
        atlasmenu.add_command(label="Import Allen Atlas…", command=self.open_allen_atlas_browser)
        atlasmenu.add_command(
            label="Download Full Allen Atlas…",
            command=self.download_full_allen_atlas,
        )
        atlasmenu.add_separator()
        atlasmenu.add_checkbutton(label="Crop", variable=self.crop_mode_var, command=self.toggle_crop_mode)
        atlasmenu.add_checkbutton(label="Move", variable=self.edit_mode_var, command=self.toggle_edit_mode)
        atlasmenu.add_command(label="Rotate", command=self.show_rotate_settings)
        atlasmenu.add_command(label="Scale", command=self.show_scale_settings)
        atlasmenu.add_command(label="Fit Atlas to Image", command=self.fit_atlas_to_image)
        atlasmenu.add_separator()
        atlasmenu.add_command(label="Save Atlas Schematic…", command=self.save_atlas_schematic)
        atlasmenu.add_command(label="Load Atlas Schematic…", command=self.load_atlas_schematic)
        atlasmenu.add_command(label="Clear Atlas", command=self.clear_atlas)
        atlasmenu.add_command(
            label="Split Hemispheres (_r / _l)…",
            command=self.split_atlas_hemispheres,
        )

        # Per-region transforms for individually selected atlas zones (new in this update)
        atlasmenu.add_separator()
        atlasmenu.add_command(label="Select Region", command=self.select_region)
        atlasmenu.add_command(label="Deselect Region", command=self.deselect_region)
        atlasmenu.add_command(label="Rotate Selected Region", command=self.show_rotate_selected_dialog)
        atlasmenu.add_command(label="Scale Selected Region", command=self.show_scale_selected_dialog)

        # Paint tools as a section under Atlas (no top-level Paint menu)
        atlasmenu.add_separator()
        paintmenu = tk.Menu(atlasmenu, tearoff=0)
        atlasmenu.add_cascade(label="Paint", menu=paintmenu)
        paintmenu.add_command(label="Start Paint", command=self.start_paint)
        paintmenu.add_command(label="Stop Paint", command=self.stop_paint)
        paintmenu.add_command(label="Pen", command=self.use_pen)
        paintmenu.add_command(label="Eraser", command=self.use_eraser)
        paintmenu.add_command(label="Brushsize", command=self.show_brush_settings)
        paintmenu.add_separator()
        paintmenu.add_command(label="Load Paint", command=self.load_paint)
        paintmenu.add_command(label="Save Paint Layer", command=self.save_paint_layer)

        # Cell menu (formerly Mask) — mask edit tools + counting subcategory
        cellmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Cell", menu=cellmenu)
        cellmenu.add_command(label="Show Mask", command=self.show_cell_mask_threshold)
        cellmenu.add_command(label="Show Mask Settings", command=self.show_mask_settings)
        cellmenu.add_command(label="Add Cell", command=self.start_add_cells)
        cellmenu.add_command(label="Remove Cell", command=self.start_remove_cells)
        cellmenu.add_command(label="Split Cell", command=self.start_split_cell)
        cellmenu.add_command(label="Finish Mask Edit", command=self.stop_mask_edit)
        cellmenu.add_separator()
        cellmenu.add_command(label="Save Cell Mask…", command=self.save_cell_mask)
        cellmenu.add_command(label="Load Cell Mask…", command=self.load_cell_mask)
        cellmenu.add_command(
            label="Generate Random Cell Mask…",
            command=self.generate_random_cell_mask,
        )
        cellmenu.add_command(
            label="Show GT + Random Masks",
            command=self.show_ground_truth_and_random_masks,
        )
        cellmenu.add_command(
            label="Clear Random Cell Mask",
            command=self.clear_random_cell_mask,
        )
        cellmenu.add_separator()
        # Former top-level "Cell" items as a subcategory
        cell_count_menu = tk.Menu(cellmenu, tearoff=0)
        cellmenu.add_cascade(label="Counting", menu=cell_count_menu)
        cell_count_menu.add_command(label="Count Cells", command=self.count_cells)
        cell_count_menu.add_checkbutton(
            label="Show Zone Labels & Counts",
            variable=self.show_zone_labels_var,
            command=self._toggle_zone_labels_counts,
        )

        # Axons and Nets — region intensity / network analyses
        axonsmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="Axons and Nets", menu=axonsmenu)
        axonsmenu.add_command(
            label="Measure Region Intensities…",
            command=self.measure_region_intensities,
        )
        axonsmenu.add_command(
            label="Counterstain Normalization Measurement…",
            command=self.measure_counterstain_normalization,
        )
        axonsmenu.add_checkbutton(
            label="Show Labels and Intensities",
            variable=self.show_zone_intensity_labels_var,
            command=self._toggle_zone_labels_intensities,
        )
        axonsmenu.add_separator()
        axonsmenu.add_command(
            label="Draw Perineuronal Masks",
            command=self.draw_perineuronal_masks,
        )
        axonsmenu.add_command(
            label="Measure Perineuronal Intensity…",
            command=self.measure_perineuronal_intensity,
        )
        axonsmenu.add_command(
            label="Show Perineuronal Masks",
            command=self.show_perineuronal_masks,
        )
        axonsmenu.add_command(
            label="Clear Perineuronal Masks",
            command=self.clear_perineuronal_masks,
        )

        # Create View menu dropdown
        viewmenu = tk.Menu(self.menu)
        self.menu.add_cascade(label="View", menu=viewmenu)

        def toggle_transparent_mode():
            # Main window always stays fully opaque
            self.master.attributes('-alpha', 1.0)

            # Update all currently open popups
            alpha = 0.3 if self.transparent_mode.get() else 1.0
            for w in self.transparent_windows[:]:
                try:
                    w.attributes('-alpha', alpha)
                except Exception:
                    if w in self.transparent_windows:
                        self.transparent_windows.remove(w)

        viewmenu.add_checkbutton(
            label="Transparent Mode (70%)",
            variable=self.transparent_mode,
            command=toggle_transparent_mode
        )

        viewmenu.add_separator()
        viewmenu.add_checkbutton(
            label="Show Atlas Manager Ribbon",
            variable=self.show_atlas_ribbon,
            command=self._toggle_atlas_ribbon_visibility
        )


        # Add highlight regions button to manually enable this

        # This works as a labeling scheme, but how do I have it update?
        # self.menu.add_command(label="Pen: "+str(self.draw_type.get()))

        # Main layout: Horizontal PanedWindow (File Browser | Image Viewer)
        self.main_paned = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        self.main_paned.grid(row=0, column=0, sticky='nsew')
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

        # --- Left File Browser Pane ---
        self.file_browser_frame = ttk.Frame(self.main_paned, width=240)
        self._build_file_browser(self.file_browser_frame)
        self.main_paned.add(self.file_browser_frame, weight=0)

        # --- Right Content Area (existing viewer) ---
        self.top_frame = ttk.Frame(self.main_paned)
        self.main_paned.add(self.top_frame, weight=1)

        self.top_frame.rowconfigure(0, weight=0)  # ribbon row (collapsible Atlas Manager)
        self.top_frame.rowconfigure(1, weight=1)  # canvas viewer
        self.top_frame.rowconfigure(2, weight=0)  # horizontal scrollbar
        self.top_frame.columnconfigure(0, weight=1)

        # Atlas Manager ribbon (dropdown/expandable panel for selected region + manip options + border drag)
        self._build_atlas_ribbon(self.top_frame)
        self.atlas_ribbon.grid(row=0, column=0, columnspan=2, sticky='ew', padx=2, pady=1)
        self._update_ribbon_selection()

        # Respect initial visibility from View menu var (default shown)
        if not self.show_atlas_ribbon.get():
            self.atlas_ribbon.grid_remove()

        # Scrollbars and canvas (viewer area shifted down to make room for ribbon)
        self.scrolly = ttk.Scrollbar(self.top_frame, orient=tk.VERTICAL)
        self.scrolly.grid(row=1, column=1, sticky='ns')
        self.scrollx = ttk.Scrollbar(self.top_frame, orient=tk.HORIZONTAL)
        self.scrollx.grid(row=2, column=0, sticky='ew')

        self.output = tk.Canvas(self.top_frame, bg='#ECE8F3')
        self.output.configure(yscrollcommand=self.scrolly.set, xscrollcommand=self.scrollx.set)
        self.output.grid(row=1, column=0, sticky='nsew')
        self.scrolly.configure(command=self.output.yview)
        self.scrollx.configure(command=self.output.xview)

        # Enable mouse wheel zoom
        self._bind_mousewheel()

        # Alt + drag panning
        self._pan_start_x = None
        self._pan_start_y = None
        self.output.bind("<Alt-ButtonPress-1>", self._start_pan)
        self.output.bind("<Alt-B1-Motion>", self._do_pan)
        self.output.bind("<Alt-ButtonRelease-1>", self._end_pan)

        # Interactive border drag support for selected atlas regions (pull only the dragged side)
        # These are additive so they coexist with other mode-specific bindings
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self.output.bind("<ButtonRelease-1>", self._end_border_drag, add=True)
        self.output.bind("<Motion>", self._update_cursor_for_atlas_border, add=True)
        self.border_drag_active = False
        self.border_drag_original_mask = None
        self.border_drag_centroid = (0.0, 0.0)
        self.border_drag_unit = (0.0, 1.0)
        self.border_drag_start_mouse = (0.0, 0.0)
        self.border_drag_zone = None

        # Edge editing state for precise local boundary pulling (new)
        self.edge_grab_active = False
        self.active_edge = None
        self.edge_closest_idx = 0
        self.edge_window = 30
        self.edge_start_idx = 0
        self.edge_end_idx = 0
        self.original_full_contour_for_edit = None
        self.current_edited_contour = None
        self.edge_highlight_item = None

        # Persistent selected edge for toggle (click to select/illuminate red, click again to deselect)
        self.selected_edge_full_contour = None
        self.selected_edge_start_idx = 0
        self.selected_edge_end_idx = 0
        self.selected_edge_closest = 0
        self._edge_pending_deselect = False
        self.edge_drag_start_pos = (0.0, 0.0)

    # End of UI, beginning of functions

    def split_tiff(self):
        path = fd.askopenfilename(filetypes=[("TIFF files", "*.tif *.tiff")])
        if path:
            split_stacked_tiff(path)

    def _update_paint_indicator(self):
        """Update the paint mode indicator label (in ribbon header) and window title."""
        base_title = "Regional IF Analyzer"
        if getattr(self, 'current_state', None) == 'paint':
            self.paint_status_var.set("🎨 PAINT ON")
            if hasattr(self, 'paint_status_label') and self.paint_status_label:
                try:
                    self.paint_status_label.configure(foreground="red", font=("Helvetica", 8, "bold"))
                except Exception:
                    pass
            try:
                self.master.title(base_title + " — 🎨 PAINT MODE")
            except Exception:
                pass
        else:
            self.paint_status_var.set("Paint: off")
            if hasattr(self, 'paint_status_label') and self.paint_status_label:
                try:
                    self.paint_status_label.configure(foreground="gray", font=("Helvetica", 8))
                except Exception:
                    pass
            try:
                self.master.title(base_title)
            except Exception:
                pass

    def start_paint(self):
        if self.current_state == 'paint':
            return
        self.current_state = 'paint'
        self.region_move_mode.set(False)
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        # Ensure paint_layer exists for visual baking (image-sized when a TIFF is loaded)
        if self.paint_layer is None:
            size = None
            if self.original_background is not None:
                size = self.original_background.size
            elif self.background_image is not None:
                size = self.background_image.size
            if size is not None:
                self.paint_layer = Image.new("RGBA", size, (0, 0, 0, 0))
        # Ensure zone mask exists / is ready to receive painted regions (merge into atlas mask)
        try:
            self._ensure_zone_mask_for_paint()
        except Exception as e:
            logger.debug(f"ensure zone mask on start_paint: {e}")
        self.show_brush_settings()
        self.old_x = None
        self.old_y = None
        self.current_paint_group = None
        self.color = self.DEFAULT_COLOR
        self.active_button = None
        self.use_pen()
        self.output.unbind('<Button-1>')
        self.output.bind('<Button-1>', self.paint)
        self.output.bind('<B1-Motion>', self.paint)
        self.output.bind('<ButtonRelease-1>', self.reset)
        # Right-click to name a painted region (comparable to atlas region labeling)
        self.output.bind('<Button-3>', self.name_painted_region)
        self.draw_type = 'drag'
        self.master.bind('<s>', self.reset_toggle)
        # Do not add "Pen: drag" to the top menu bar (it used to accumulate every Start Paint).
        # Clean up any leftover entries from older sessions still in this process.
        self._remove_paint_pen_menu_item()

        self._update_paint_indicator()

    def stop_paint(self):
        self.save_state()  # Snapshot the state with open paint groups/names before we auto-default, convert, bake and clear
        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>') 
        self.output.unbind('<Button-1>')
        self.output.unbind('<Button-3>')
        self.output.bind('<Button-1>', self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self._remove_paint_pen_menu_item()
        self.current_state = None
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None

        # Auto-assign default names to any painted strokes/groups that the user didn't explicitly name
        # This ensures the spreadsheet always gets populated with Painted Regions when using the paint tool.
        paint_items = self.output.find_withtag('paint')
        all_current_groups = set()
        for item in paint_items:
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    all_current_groups.add(tag)

        # Also include groups recorded in durable storage (in case show_page() wiped the transient 'paint' canvas items).
        # Retirement (pop + dtag inside convert/force) ensures already-committed groups are no longer present here.
        for gtag in list(self.paint_group_data.keys()):
            if gtag.startswith('paintgroup_'):
                all_current_groups.add(gtag)

        for group_tag in all_current_groups:
            if group_tag not in self.named_paint_groups:
                self.named_paint_groups[group_tag] = None  # will get default name in convert

        # Convert (named + auto-defaulted) paint groups to proper zones (for cell counting)
        self._convert_named_paints_to_zones()

        # Hardening for "named immediately then Count/Stop": if any groups remain in durable data
        # (e.g. name-time collection edge or dtag timing), re-add them to named (preserve user name)
        # and convert a second time before we clear. This ensures zones are populated even if first
        # pass missed strokes due to transient vector state.
        if self.named_paint_groups or self.paint_group_data:
            for gtag in list(self.paint_group_data.keys()):
                if gtag.startswith('paintgroup_') and gtag not in self.named_paint_groups:
                    # preserve a user-provided name if it was set before a prior failed convert
                    self.named_paint_groups[gtag] = self.named_paint_groups.get(gtag)
            if self.named_paint_groups:
                self._convert_named_paints_to_zones()

        # Now that the user has finished painting, bake everything into the paint_layer
        # and clean up the temporary canvas items. This is when labeling is "finalized".
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()

        self.output.delete('paint')   # Remove all temporary paint strokes from canvas
        self.save_paint()
        self.named_paint_groups.clear()
        self.paint_group_data.clear()
        self.current_paint_group = None
        self.show_page()

        self._update_paint_indicator()

        # Refresh ribbon so any auto-default "Painted Region N" names from Stop Paint appear immediately in the list
        self._update_ribbon_selection()

    def save_paint(self):
        """Save canvas paint strokes to an image without using postscript.

        Falls back to copying from the persistent paint_layer if no temporary
        canvas items are present (common after zoom or show_page).
        """
        paint_items = self.output.find_withtag('paint')
        
        # Fallback: if no temporary items, use whatever is already baked in paint_layer
        if not paint_items:
            if self.paint_layer is not None:
                self.img = self.paint_layer.copy()
                self.photo = ImageTk.PhotoImage(self.img)
                self.atlas_filetype = 'img'
                logger.debug("Used persistent paint_layer for save_paint (no canvas items)")
            else:
                logger.debug("No paint strokes to save")
            return

        # Get coordinates of entire painting area (the active vector strokes)
        try:
            bbox = self.output.bbox('paint')
            if bbox is None:
                logger.debug("No paint bbox found")
                return
            x1, y1, x2, y2 = bbox
        except Exception:
            logger.debug("Failed to get paint bbox")
            return
        # Modify coords so painting stays in the same place after conversion
        # This forces the bbox to start at the upper left corner of the canvas
        # This keeps the tiff and painting aligned even when importing the saved painting
        x1 = 0
        y1 = 0
        
        # Create a new transparent image
        # Keep original bbox so we can adjust coordinates relative to it
        bx1, by1, bx2, by2 = x1, y1, x2, y2
        img = Image.new('RGBA', (int(bx2 - bx1), int(by2 - by1)), (0, 0, 0, 0))

        # Draw each paint stroke onto the image
        draw = ImageDraw.Draw(img)

        for line in self.output.find_withtag('paint'):
            coords = self.output.coords(line)
            if not coords:
                continue

            if len(coords) != 4:
                logger.error("Wrong number of coordinates")

            # Convert canvas coords into point tuples for PIL
            points = []
            for i in range(0, len(coords), 2):
                x = coords[i]
                y = coords[i+1] 
                points.append((x, y))

            width = self.output.itemcget(line, 'width')
            try:
                width = int(float(width))
            except Exception:
                width = 1
            radius = math.floor(width / 2)
            fill = self.output.itemcget(line, 'fill')

            # Draw lines as points for roundness to fill jagged edges
            for (px, py) in points:
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)

            # Draw lines as lines for fast-drawn lines
            draw.line(points, fill=fill, width=width, joint="curve")

            
        
        # Set as current image
        self.img = img
        self.photo = ImageTk.PhotoImage(img)
        self.atlas_filetype = 'img'
        
        # Clear the canvas drawings
        self.output.delete('paint')
        
        logger.debug("Paint strokes saved to image successfully")

    def _commit_live_paint_strokes(self):
        """Commit any in-progress canvas paint strokes into the persistent paint_layer."""
        try:
            paint_items = self.output.find_withtag('paint')
            if paint_items:
                self._commit_canvas_paint_to_layer()
                self.output.delete('paint')
        except Exception:
            pass

    def _write_paint_bundle(self, save_path, layer, page):
        """Write a .barccpaint zip (strokes + zones + manifest) to save_path."""
        with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            bio = BytesIO()
            layer.save(bio, format='PNG')
            zf.writestr('strokes.png', bio.getvalue())
            if page in self.mask_images and self.mask_images[page] is not None:
                bio2 = BytesIO()
                self.mask_images[page].save(bio2, format='PNG')
                zf.writestr('zones.png', bio2.getvalue())
            manifest = {
                "format_version": 1,
                "type": "paint_with_regions",
                "saved_background_size": list(layer.size),
                "zone_names": self.zone_names.get(page, {}),
                "painted_zone_outlines": getattr(self, 'painted_zone_outlines', {}),
            }
            zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    def _save_paint_layer_to_dir(self, target_dir, base_name, unique=True, show_messages=True):
        """Save paint layer/bundle into target_dir.

        Returns the saved file path, or None if there was nothing to save / on failure.
        When unique=False, overwrites the canonical name (used by Count Cells auto-export).
        """
        if not target_dir or not os.path.isdir(target_dir):
            return None

        self._commit_live_paint_strokes()

        layer = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
        if layer is None:
            logger.debug("No painting to save")
            return None

        page = self.current_page
        has_labeled_regions = bool(
            self.zone_names.get(page, {}) or
            getattr(self, 'painted_zone_outlines', {})
        )

        # Skip empty transparent paint layers when there are no named/painted regions
        if not has_labeled_regions:
            try:
                arr = np.array(layer)
                if arr.ndim == 3 and arr.shape[2] >= 4 and not arr[:, :, 3].any():
                    logger.debug("Paint layer is empty; skipping save")
                    return None
            except Exception:
                pass

        try:
            if has_labeled_regions:
                if unique:
                    save_path = self._get_unique_paint_bundle_path(target_dir, base_name)
                else:
                    save_path = os.path.join(target_dir, f"{base_name}_paint_with_regions.barccpaint")
                self._write_paint_bundle(save_path, layer, page)
                logger.info(f"Saved paint bundle with regions to: {save_path}")
                if show_messages:
                    messagebox.showinfo("Paint + Regions Saved", f"Paint file with labeled regions saved to:\n{save_path}")
                return save_path
            else:
                if unique:
                    save_path = self._get_unique_paint_path(target_dir, base_name)
                else:
                    save_path = os.path.join(target_dir, f"{base_name}_paint.png")
                layer.save(save_path)
                logger.info(f"Auto-saved paint to: {save_path}")
                if show_messages:
                    messagebox.showinfo("Paint Saved", f"Paint layer saved to:\n{save_path}")
                return save_path
        except Exception as e:
            logger.error(f"Failed to save paint layer: {e}")
            if show_messages:
                messagebox.showerror("Save Error", f"Failed to save paint:\n{e}")
            return None

    def save_paint_layer(self):
        """Auto-save the current paint layer into <image_folder>/output/paint/.

        After saving, the File Browser list is refreshed so artifacts appear under the TIFF.
        """
        base_name = self.tiff_filename or "untitled"

        # Prefer image dir / browser folder → always write under its output/paint/ subfolder
        base_dir = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            base_dir = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            base_dir = self.current_tiff_directory

        if base_dir:
            target_dir = self._get_output_directory(base_dir, feature="paint")
            if not target_dir:
                messagebox.showerror("Save Error", "Could not create the output folder for paint save.")
                return
            path = self._save_paint_layer_to_dir(target_dir, base_name, unique=True, show_messages=True)
            if path and hasattr(self, 'tiff_tree') and self.current_tiff_directory:
                self.refresh_tiff_file_list()
            return

        # Fallback: no working directory → traditional save dialog
        self._commit_live_paint_strokes()
        layer = self.paint_layer if self.paint_layer is not None else getattr(self, 'img', None)
        if layer is None:
            logger.debug("No painting to save")
            return

        save_path = fd.asksaveasfilename(
            title="Save Paint Layer",
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("BARCC Paint", "*.barccpaint")],
            initialfile=f"{base_name}_paint.png"
        )
        if not save_path:
            return
        try:
            page = self.current_page
            has_labeled_regions = bool(
                self.zone_names.get(page, {}) or
                getattr(self, 'painted_zone_outlines', {})
            )
            if has_labeled_regions:
                bundle_path = save_path
                if not bundle_path.lower().endswith('.barccpaint'):
                    bundle_path = os.path.splitext(save_path)[0] + '.barccpaint'
                self._write_paint_bundle(bundle_path, layer, page)
                messagebox.showinfo("Paint + Regions Saved", f"Paint file with labeled regions saved to:\n{bundle_path}")
            else:
                layer.save(save_path)
                messagebox.showinfo("Image Saved", f"Paint saved to: {save_path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save the paint image:\n{e}")

    def _get_unique_paint_path(self, directory, base_name):
        """Return a unique path like 'image_paint.png', 'image_paint (2).png', etc."""
        candidate = os.path.join(directory, f"{base_name}_paint.png")
        if not os.path.exists(candidate):
            return candidate

        counter = 2
        while True:
            candidate = os.path.join(directory, f"{base_name}_paint ({counter}).png")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def _get_unique_paint_bundle_path(self, directory, base_name):
        """Return a unique path for a paint + regions bundle."""
        candidate = os.path.join(directory, f"{base_name}_paint_with_regions.barccpaint")
        if not os.path.exists(candidate):
            return candidate

        counter = 2
        while True:
            candidate = os.path.join(directory, f"{base_name}_paint_with_regions ({counter}).barccpaint")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def open_paint(self):
        """Load a paint layer (.png). Defaults to <folder>/output/paint/ when present."""
        initial_dir = self._preferred_open_dir(feature="paint")

        logger.info("Opening file dialog for paint selection")
        self.save_state()
        path = fd.askopenfilename(
            title="Load Paint",
            initialdir=initial_dir,
            filetypes=[
                ("BARCC Cropped Atlas", "*.catlas"),
                ("Legacy BARCC Atlas", "*.atlas"),
                ("BARCC Paint + Regions", "*.barccpaint"),
                ("PNG files", "*.png"),
                ("All files", "*.*")
            ]
        )
        if path:
            logger.info(f"Opening paint file: {path}")
            self.path = path
            if path.lower().endswith(('.catlas', '.atlas')):
                try:
                    self._load_atlas_file(path)
                except Exception as e:
                    messagebox.showerror("Load Error", f"Failed to load cropped atlas:\n{e}")
            elif path.lower().endswith('.barccpaint'):
                self._load_barccpaint_bundle(path)
            else:
                self.img = Image.open(path)
                clear_preprocess_cache()

                loaded_rgba = self.img.convert('RGBA') if self.img.mode != 'RGBA' else self.img
                self.paint_layer = loaded_rgba
                self.atlas_filetype = 'img'

                self.show_page()

                # Legacy sidecar support (plain PNG + _regions.json + _zones.png)
                try:
                    loaded_base = os.path.splitext(os.path.basename(path))[0]
                    load_dir = os.path.dirname(path) or "."
                    regions_json = os.path.join(load_dir, loaded_base + "_regions.json")
                    zones_png = os.path.join(load_dir, loaded_base + "_zones.png")

                    restored = False
                    page = self.current_page

                    if os.path.exists(regions_json):
                        with open(regions_json, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        names = data.get("zone_names", {})
                        if names:
                            names = {int(k): v for k, v in names.items()}
                            if page not in self.zone_names:
                                self.zone_names[page] = {}
                            self.zone_names[page].update(names)
                            restored = True
                        outlines = data.get("painted_zone_outlines", {})
                        if outlines:
                            outlines = {int(k): v for k, v in outlines.items()}
                            self.painted_zone_outlines.update(outlines)
                            restored = True

                    if os.path.exists(zones_png):
                        zone_mask = Image.open(zones_png).convert('L')
                        try:
                            if zone_mask.mode != 'L':
                                zone_mask = zone_mask.convert('L')
                            zarr = np.array(zone_mask).astype(np.uint8)
                            zone_mask = Image.fromarray(zarr, mode='L')
                        except Exception:
                            pass
                        self.mask_images[page] = zone_mask
                        restored = True

                    if restored:
                        if hasattr(self, '_update_ribbon_selection'):
                            self._update_ribbon_selection()
                        if hasattr(self, '_rebuild_page_overlays'):
                            try:
                                self._rebuild_page_overlays(page)
                            except Exception:
                                pass
                        self.show_page()
                        logger.info(f"Restored from legacy sidecars for {path}")
                except Exception as e:
                    logger.debug(f"No legacy sidecars: {e}")

    def load_paint(self):
        """Load a paint layer from the current working directory shown in the left File Browser.
        This is the recommended entry point from Atlas > Paint.
        """
        self.open_paint()

    def _load_barccpaint_bundle(self, path):
        """Load a .barccpaint bundle (strokes.png + zones.png + manifest with names).
        Restores both the visual painted boundaries and the labeled regions (names + shapes)
        into the Atlas Manager at the correct location relative to the current background.
        """
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                manifest = json.loads(zf.read('manifest.json').decode('utf-8'))

                # Visual strokes (black drawn boundaries)
                strokes = Image.open(BytesIO(zf.read('strokes.png')))
                self.paint_layer = strokes.convert('RGBA') if strokes.mode != 'RGBA' else strokes
                self.img = self.paint_layer.copy()
                self.atlas_filetype = 'img'

                # Match strokes layer size to current background (handles window resize / refit between save/load)
                if self.original_background is not None:
                    target = self.original_background.size
                    if self.paint_layer.size != target:
                        try:
                            self.paint_layer = self.paint_layer.resize(target, Image.NEAREST)
                            self.img = self.paint_layer.copy()
                        except Exception:
                            pass
                self.photo = ImageTk.PhotoImage(self.img)

                page = self.current_page

                # Zone mask (filled labeled region shapes)
                if 'zones.png' in zf.namelist():
                    zones = Image.open(BytesIO(zf.read('zones.png'))).convert('L')
                    # If background size differs, resize to match (nearest for mask ids)
                    if self.original_background is not None:
                        if zones.size != self.original_background.size:
                            zones = zones.resize(self.original_background.size, Image.NEAREST)
                    # Ensure clean uint8 label mask (prevents any dtype surprises downstream)
                    try:
                        if not isinstance(zones, Image.Image):
                            zones = Image.fromarray(np.asarray(zones).astype(np.uint8))
                        if zones.mode != 'L':
                            zones = zones.convert('L')
                        zarr = np.array(zones).astype(np.uint8)
                        zones = Image.fromarray(zarr, mode='L')
                    except Exception:
                        pass
                    self.mask_images[page] = zones

                # Names and outlines
                # json turns int keys into str; normalize back to int so sorted() and 'in' checks
                # with uint8 zids from masks don't trigger ufunc 'less' during comparisons.
                names = manifest.get('zone_names', {})
                if names:
                    names = {int(k): v for k, v in names.items()}
                    if page not in self.zone_names:
                        self.zone_names[page] = {}
                    self.zone_names[page].update(names)

                outlines = manifest.get('painted_zone_outlines', {})
                if outlines:
                    outlines = {int(k): v for k, v in outlines.items()}
                    self.painted_zone_outlines.update(outlines)

                # Make sure the zone counter for this page is high enough for any loaded zone ids
                # (prevents ID collisions on future naming, complements the ensure in ribbon populate).
                if page in self.zone_names and self.zone_names[page]:
                    try:
                        max_loaded = max((int(k) for k in self.zone_names[page].keys()), default=0)
                        if page not in self.zone_counters:
                            self.zone_counters[page] = 0
                        if self.zone_counters[page] < max_loaded:
                            self.zone_counters[page] = max_loaded
                    except Exception:
                        pass

                # Reset placement so everything lines up in background pixel space
                self.img_x = 0
                self.img_y = 0

                self.show_page()

                if hasattr(self, '_update_ribbon_selection'):
                    self._update_ribbon_selection()
                if hasattr(self, '_rebuild_page_overlays'):
                    try:
                        self._rebuild_page_overlays(page)
                    except Exception:
                        pass

            messagebox.showinfo("Paint Loaded", f"Loaded paint + labeled regions from:\n{path}")
            logger.info(f"Loaded barccpaint bundle: {path}")
        except Exception as e:
            messagebox.showerror("Load Error", f"Failed to load paint bundle:\n{e}")
            logger.error(f"Failed to load barccpaint bundle {path}: {e}")

    # ------------------------------------------------------------------
    # .catlas schematic — cropped/labeled atlas + paint + Atlas Manager
    # (legacy .atlas files still load). Label on DAPI, apply to other channels.
    # ------------------------------------------------------------------

    def _atlas_schematic_has_content(self):
        """True if there is atlas drawing, zone mask/names, or paint worth saving."""
        page = self.current_page if self.current_page is not None else 0
        if self.zone_names.get(page):
            return True
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                if int(np.array(self.mask_images[page]).max()) > 0:
                    return True
            except Exception:
                return True
        if page in self.base_page_images and self.base_page_images[page] is not None:
            return True
        if getattr(self, "allen_borders_pure", None) is not None:
            return True
        if getattr(self, "painted_zone_outlines", None):
            return True
        if getattr(self, "paint_group_data", None):
            return True
        if getattr(self, "paint_layer", None) is not None:
            try:
                arr = np.array(self.paint_layer)
                if arr.ndim == 3 and arr.shape[2] >= 4 and arr[:, :, 3].any():
                    return True
            except Exception:
                pass
        return False

    def _serialize_zone_names(self, names):
        """JSON-safe zone_names: string keys, string values."""
        out = {}
        for k, v in (names or {}).items():
            try:
                out[str(int(k))] = str(v) if v is not None else f"Zone {k}"
            except Exception:
                out[str(k)] = str(v)
        return out

    def _serialize_painted_outlines(self, outlines):
        out = {}
        for k, v in (outlines or {}).items():
            try:
                key = str(int(k))
            except Exception:
                key = str(k)
            if isinstance(v, dict):
                pts = v.get("points") or []
                serial_pts = []
                for p in pts:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        serial_pts.append([float(p[0]), float(p[1])])
                    else:
                        serial_pts.append(p)
                out[key] = {
                    "points": serial_pts,
                    "width": int(v.get("width", 3) or 3),
                }
            else:
                out[key] = v
        return out

    def _serialize_paint_group_data(self, data):
        """Deep-copy paint_group_data into plain JSON types."""
        out = {}
        for gtag, recs in (data or {}).items():
            rows = []
            for rec in recs or []:
                if not isinstance(rec, dict):
                    continue
                row = {}
                mp = rec.get("model_points")
                if mp is not None:
                    row["model_points"] = [float(x) for x in mp]
                coords = rec.get("coords")
                if coords is not None:
                    row["coords"] = [float(x) for x in coords]
                if "width" in rec:
                    try:
                        row["width"] = int(rec["width"])
                    except Exception:
                        row["width"] = 3
                if "space" in rec:
                    row["space"] = str(rec["space"])
                rows.append(row)
            out[str(gtag)] = rows
        return out

    def _serialize_allen_zone_meta(self, meta_by_page):
        out = {}
        for page, meta in (meta_by_page or {}).items():
            page_out = {}
            for zid, m in (meta or {}).items():
                try:
                    key = str(int(zid))
                except Exception:
                    key = str(zid)
                if isinstance(m, dict):
                    page_out[key] = {
                        str(kk): (vv if isinstance(vv, (str, int, float, bool, type(None))) else str(vv))
                        for kk, vv in m.items()
                    }
                else:
                    page_out[key] = m
            out[str(int(page) if str(page).isdigit() else page)] = page_out
        return out

    def _png_bytes(self, pil_img, mode=None):
        img = pil_img
        if mode and img.mode != mode:
            img = img.convert(mode)
        bio = BytesIO()
        # compress_level kept default; optimize off for speed on large masks
        img.save(bio, format="PNG")
        return bio.getvalue()

    def _catlas_read_png(self, zf, names, member, mode=None):
        """Read a PNG member from a .catlas/.atlas zip; force full decode."""
        if member not in names:
            return None
        img = Image.open(BytesIO(zf.read(member)))
        img.load()  # force decode before zip closes / buffer dies
        if mode:
            img = img.convert(mode)
        else:
            img = img.copy()
        return img

    def _scale_catlas_layers_to_background(
        self,
        *,
        zones,
        base_atlas,
        borders_pure,
        page_overlay,
        paint_strokes,
        img_x,
        img_y,
        saved_bg,
        cur_bg_size,
        atlas_filetype,
        painted_outlines=None,
        paint_group_data=None,
    ):
        """Scale atlas + paint + placement to match the current TIFF size.

        Origin of the previous right-shift bug
        --------------------------------------
        Placement uses model-space ``img_x`` / ``img_y`` (native atlas/TIFF pixels).
        When the in-memory TIFF size changed between save and load (viewer fit scale
        depends on window size), we scaled only ``img_x`` and the paint layer when
        the atlas was *not* the same size as the background (typical after Crop).
        Offsets moved but the atlas rasters stayed at the old resolution → a small
        horizontal/vertical drift (often read as a right shift).

        Fix: whenever the background size changes, scale *every* atlas-model layer
        (mask, base, borders, overlay, stroke geometry) by the same sx/sy as the
        background, together with img_x/img_y and paint.
        """
        if (
            not cur_bg_size
            or not saved_bg
            or len(saved_bg) != 2
            or len(cur_bg_size) != 2
        ):
            return (
                zones,
                base_atlas,
                borders_pure,
                page_overlay,
                paint_strokes,
                img_x,
                img_y,
                painted_outlines,
                paint_group_data,
                False,
                1.0,
                1.0,
            )

        sw, sh = float(saved_bg[0]), float(saved_bg[1])
        tw, th = float(cur_bg_size[0]), float(cur_bg_size[1])
        if sw < 1 or sh < 1:
            return (
                zones,
                base_atlas,
                borders_pure,
                page_overlay,
                paint_strokes,
                img_x,
                img_y,
                painted_outlines,
                paint_group_data,
                False,
                1.0,
                1.0,
            )

        # Treat near-equal sizes as a match (avoid floating noise / 1px jitter)
        if abs(sw - tw) < 1.5 and abs(sh - th) < 1.5:
            return (
                zones,
                base_atlas,
                borders_pure,
                page_overlay,
                paint_strokes,
                img_x,
                img_y,
                painted_outlines,
                paint_group_data,
                False,
                1.0,
                1.0,
            )

        sx = tw / sw
        sy = th / sh
        # Prefer a single uniform scale when aspect is preserved (viewer fit is uniform)
        if abs(sx - sy) < 1e-4:
            s = sx
            sx = sy = s

        is_allen = atlas_filetype == "allen"
        rgba_resample = Image.NEAREST if is_allen else Image.BILINEAR

        def _scale_rgba(im):
            if im is None:
                return None
            nw = max(1, int(round(im.width * sx)))
            nh = max(1, int(round(im.height * sy)))
            if (nw, nh) == im.size:
                return im
            return im.resize((nw, nh), rgba_resample)

        def _scale_mask(im):
            if im is None:
                return None
            nw = max(1, int(round(im.width * sx)))
            nh = max(1, int(round(im.height * sy)))
            if (nw, nh) == im.size:
                return im
            return im.resize((nw, nh), Image.NEAREST)

        zones = _scale_mask(zones)
        base_atlas = _scale_rgba(base_atlas)
        borders_pure = _scale_rgba(borders_pure)
        page_overlay = _scale_rgba(page_overlay)

        if paint_strokes is not None:
            # Paint is background-native; target exact current bg size
            target = (max(1, int(round(tw))), max(1, int(round(th))))
            if paint_strokes.size != target:
                paint_strokes = paint_strokes.resize(target, Image.NEAREST)

        img_x = float(img_x) * sx
        img_y = float(img_y) * sy

        # Scale painted outline points (atlas model space)
        if painted_outlines:
            scaled_out = {}
            for zid, rec in painted_outlines.items():
                if not isinstance(rec, dict):
                    scaled_out[zid] = rec
                    continue
                pts = []
                for p in rec.get("points") or []:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        pts.append((float(p[0]) * sx, float(p[1]) * sy))
                scaled_out[zid] = {
                    "points": pts,
                    "width": max(1, int(round(int(rec.get("width", 3) or 3) * max(sx, sy)))),
                }
            painted_outlines = scaled_out

        # Scale durable paint group model points
        if paint_group_data:
            scaled_pg = {}
            for gtag, recs in paint_group_data.items():
                new_recs = []
                for rec in recs or []:
                    if not isinstance(rec, dict):
                        continue
                    row = dict(rec)
                    for key in ("model_points", "coords"):
                        if key in row and row[key] is not None:
                            vals = list(row[key])
                            scaled_vals = []
                            for i, v in enumerate(vals):
                                # even index = x, odd = y
                                scaled_vals.append(float(v) * (sx if i % 2 == 0 else sy))
                            row[key] = scaled_vals
                    if "width" in row:
                        try:
                            row["width"] = max(
                                1, int(round(int(row["width"]) * max(sx, sy)))
                            )
                        except Exception:
                            pass
                    new_recs.append(row)
                scaled_pg[gtag] = new_recs
            paint_group_data = scaled_pg

        logger.info(
            f".catlas scale-to-bg: bg {saved_bg} → {cur_bg_size} "
            f"sx={sx:.6f} sy={sy:.6f} offset→({img_x:.3f},{img_y:.3f})"
        )
        return (
            zones,
            base_atlas,
            borders_pure,
            page_overlay,
            paint_strokes,
            img_x,
            img_y,
            painted_outlines,
            paint_group_data,
            True,
            sx,
            sy,
        )

    def _write_atlas_file(self, save_path):
        """Write a lossless .catlas zip: zones, drawings, paint, placement, names.

        Package layout:
          manifest.json
          zones.png              zone ID mask (atlas model space, L)
          base_atlas.png         structure borders / base schematic (RGBA)
          borders_pure.png       Allen pure black borders (RGBA, optional)
          page_overlay.png       current page overlay (RGBA, optional)
          paint_strokes.png      paint_layer in background image space (RGBA, optional)
          nissl_ref.png          Allen Nissl reference strip (RGBA, optional)
        """
        page = self.current_page if self.current_page is not None else 0

        self._commit_live_paint_strokes()
        try:
            if getattr(self, "named_paint_groups", None) or getattr(self, "paint_group_data", None):
                for gtag in list(self.paint_group_data.keys()):
                    if gtag.startswith("paintgroup_") and gtag not in self.named_paint_groups:
                        self.named_paint_groups[gtag] = self.named_paint_groups.get(gtag)
                if self.named_paint_groups:
                    self._convert_named_paints_to_zones()
        except Exception as e:
            logger.debug(f"catlas save: paint→zone finalize skipped: {e}")

        bg_size = None
        if self.original_background is not None:
            bg_size = [int(self.original_background.size[0]), int(self.original_background.size[1])]
        elif self.background_image is not None:
            bg_size = [int(self.background_image.size[0]), int(self.background_image.size[1])]

        atlas_size = None
        if page in self.base_page_images and self.base_page_images[page] is not None:
            atlas_size = [
                int(self.base_page_images[page].size[0]),
                int(self.base_page_images[page].size[1]),
            ]
        elif page in self.mask_images and self.mask_images[page] is not None:
            atlas_size = [
                int(self.mask_images[page].size[0]),
                int(self.mask_images[page].size[1]),
            ]

        zone_names = self.zone_names.get(page, {}) or {}
        zone_counter = int(self.zone_counters.get(page, 0) or 0)
        try:
            if zone_names:
                zone_counter = max(zone_counter, max(int(k) for k in zone_names.keys()))
        except Exception:
            pass
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                zone_counter = max(zone_counter, int(np.array(self.mask_images[page]).max()))
            except Exception:
                pass

        # Store placement in model pixels (same units as atlas rasters / TIFF).
        # Round tiny float noise so reloads don't introduce sub-pixel drift.
        raw_x = float(getattr(self, "img_x", 0) or 0)
        raw_y = float(getattr(self, "img_y", 0) or 0)
        if abs(raw_x - round(raw_x)) < 1e-3:
            raw_x = float(round(raw_x))
        if abs(raw_y - round(raw_y)) < 1e-3:
            raw_y = float(round(raw_y))

        manifest = {
            "format_version": 2,
            "type": "barcc_catlas",
            "created": datetime.now().isoformat(timespec="seconds"),
            "atlas_filetype": getattr(self, "atlas_filetype", None),
            "page": int(page),
            "img_x": raw_x,
            "img_y": raw_y,
            "placement_units": "model_pixels",
            "source_background_size": bg_size,
            "atlas_size": atlas_size,
            "zone_names": self._serialize_zone_names(zone_names),
            "zone_counter": zone_counter,
            "painted_zone_outlines": self._serialize_painted_outlines(
                getattr(self, "painted_zone_outlines", {}) or {}
            ),
            "paint_group_data": self._serialize_paint_group_data(
                getattr(self, "paint_group_data", {}) or {}
            ),
            "named_paint_groups": {
                str(k): (None if v is None else str(v))
                for k, v in (getattr(self, "named_paint_groups", {}) or {}).items()
            },
            "allen_zone_meta": self._serialize_allen_zone_meta(
                getattr(self, "allen_zone_meta", {}) or {}
            ),
            "atlas_source_path": getattr(self, "path", None)
            if isinstance(getattr(self, "path", None), str)
            else None,
            "source_tiff_name": getattr(self, "tiff_filename", None),
            "source_tiff_path": getattr(self, "current_tiff_path", None),
            "description": (
                "BARCC cropped atlas schematic (.catlas): structure drawings, "
                "painted regions, zone mask, and Atlas Manager names. Apply onto "
                "other channels of the same section without re-labeling."
            ),
        }

        with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            if page in self.mask_images and self.mask_images[page] is not None:
                m = self.mask_images[page]
                if m.mode != "L":
                    m = m.convert("L")
                try:
                    m = Image.fromarray(np.array(m).astype(np.uint8), mode="L")
                except Exception:
                    pass
                zf.writestr("zones.png", self._png_bytes(m, "L"))

            if page in self.base_page_images and self.base_page_images[page] is not None:
                base = self.base_page_images[page]
                if base.mode != "RGBA":
                    base = base.convert("RGBA")
                zf.writestr("base_atlas.png", self._png_bytes(base, "RGBA"))

            pure = getattr(self, "allen_borders_pure", None)
            if pure is not None:
                if pure.mode != "RGBA":
                    pure = pure.convert("RGBA")
                zf.writestr("borders_pure.png", self._png_bytes(pure, "RGBA"))

            if page in self.page_images and self.page_images[page] is not None:
                ov = self.page_images[page]
                if ov.mode != "RGBA":
                    ov = ov.convert("RGBA")
                zf.writestr("page_overlay.png", self._png_bytes(ov, "RGBA"))

            if getattr(self, "paint_layer", None) is not None:
                pl = self.paint_layer
                try:
                    arr = np.array(pl)
                    has_paint = arr.ndim == 3 and arr.shape[2] >= 4 and bool(arr[:, :, 3].any())
                except Exception:
                    has_paint = True
                if has_paint:
                    if pl.mode != "RGBA":
                        pl = pl.convert("RGBA")
                    zf.writestr("paint_strokes.png", self._png_bytes(pl, "RGBA"))

            nissl = getattr(self, "allen_nissl_reference", None)
            if nissl is not None:
                if nissl.mode != "RGBA":
                    nissl = nissl.convert("RGBA")
                zf.writestr("nissl_ref.png", self._png_bytes(nissl, "RGBA"))

        return manifest

    def _get_unique_atlas_path(self, directory, base_name):
        """Return a unique path like 'image.catlas', 'image (2).catlas', etc."""
        candidate = os.path.join(directory, f"{base_name}.catlas")
        if not os.path.exists(candidate):
            return candidate
        counter = 2
        while True:
            candidate = os.path.join(directory, f"{base_name} ({counter}).catlas")
            if not os.path.exists(candidate):
                return candidate
            counter += 1

    def save_atlas_schematic(self):
        """Save the full labeled atlas + paint schematic as a lossless .catlas file.

        Includes: zone mask, all Atlas Manager structure names, remaining atlas
        region drawings (borders), painted regions/strokes, and placement
        (img_x/img_y). Intended workflow: label on DAPI/counterstain, save, then
        Load Atlas Schematic onto other channels of the same section.
        """
        if not self._atlas_schematic_has_content():
            messagebox.showwarning(
                "Nothing to Save",
                "No atlas drawings, labeled regions, or paint to save.\n\n"
                "Load an atlas and/or paint & name regions first.",
            )
            return

        base_name = self.tiff_filename or "atlas_schematic"
        stem = base_name
        for suffix in ("_ch0", "_ch1", "_ch2", "_ch3", "_c0", "_c1", "_c2", "_c3",
                       "-ch0", "-ch1", "-ch2", "-ch3"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        default_name = f"{stem}_atlas"

        initial_dir = None
        base_dir = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            base_dir = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            base_dir = self.current_tiff_directory
        if base_dir:
            out = self._get_output_directory(base_dir, feature="atlas")
            initial_dir = out if out else base_dir

        save_path = fd.asksaveasfilename(
            title="Save Cropped Atlas (.catlas)",
            defaultextension=".catlas",
            filetypes=[
                ("BARCC Cropped Atlas", "*.catlas"),
                ("Legacy BARCC Atlas", "*.atlas"),
                ("All files", "*.*"),
            ],
            initialdir=initial_dir,
            initialfile=f"{default_name}.catlas",
        )
        if not save_path:
            return
        low = save_path.lower()
        if not (low.endswith(".catlas") or low.endswith(".atlas")):
            save_path = save_path + ".catlas"

        try:
            manifest = self._write_atlas_file(save_path)
            n_zones = len(manifest.get("zone_names") or {})
            logger.info(f"Saved .catlas schematic: {save_path} ({n_zones} named zones)")
            messagebox.showinfo(
                "Cropped Atlas Saved",
                f"Saved cropped atlas schematic (.catlas):\n{save_path}\n\n"
                f"Named regions: {n_zones}\n"
                f"Placement: offset ({manifest.get('img_x', 0):.1f}, {manifest.get('img_y', 0):.1f})\n"
                f"Atlas size: {manifest.get('atlas_size')}\n"
                f"Background size: {manifest.get('source_background_size')}\n\n"
                "Load via Atlas → Load Atlas Schematic… onto other channels.",
            )
            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.refresh_tiff_file_list()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to save .catlas: {e}", exc_info=True)
            messagebox.showerror("Save Error", f"Failed to save cropped atlas:\n{e}")

    def load_atlas_schematic(self):
        """Load a .catlas (or legacy .atlas) schematic onto the current image.

        Preserves the currently loaded TIFF background so you can apply a
        DAPI-labeled schematic to other fluorescence channels.
        """
        initial_dir = self._preferred_open_dir(feature="atlas")

        path = fd.askopenfilename(
            title="Load Cropped Atlas (.catlas)",
            initialdir=initial_dir,
            filetypes=[
                ("BARCC Cropped Atlas", "*.catlas"),
                ("Legacy BARCC Atlas", "*.atlas"),
                ("BARCC Paint + Regions", "*.barccpaint"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        if path.lower().endswith(".barccpaint"):
            self._load_barccpaint_bundle(path)
            return

        try:
            self._load_atlas_file(path)
        except Exception as e:
            logger.error(f"Failed to load .catlas: {e}", exc_info=True)
            messagebox.showerror("Load Error", f"Failed to load cropped atlas:\n{e}")

    def _load_atlas_file(self, path):
        """Restore a .catlas / legacy .atlas package (keeps current TIFF if present)."""
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names:
                raise ValueError("Invalid .catlas/.atlas file: missing manifest.json")

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            ftype = manifest.get("type")
            if ftype not in ("barcc_catlas", "barcc_atlas", "paint_with_regions", None):
                logger.warning(f".catlas type={ftype!r}; attempting restore")

            zones = self._catlas_read_png(zf, names, "zones.png", "L")
            base_atlas = self._catlas_read_png(zf, names, "base_atlas.png", "RGBA")
            borders_pure = self._catlas_read_png(zf, names, "borders_pure.png", "RGBA")
            page_overlay = self._catlas_read_png(zf, names, "page_overlay.png", "RGBA")
            paint_strokes = self._catlas_read_png(zf, names, "paint_strokes.png", "RGBA")
            nissl_ref = self._catlas_read_png(zf, names, "nissl_ref.png", "RGBA")

        page = int(manifest.get("page", 0) or 0)
        saved_bg = manifest.get("source_background_size")
        img_x = float(manifest.get("img_x", 0) or 0)
        img_y = float(manifest.get("img_y", 0) or 0)
        atlas_filetype = manifest.get("atlas_filetype")

        cur_bg = None
        if self.original_background is not None:
            cur_bg = self.original_background
        elif self.background_image is not None:
            cur_bg = self.background_image
        cur_bg_size = list(cur_bg.size) if cur_bg is not None else None

        # Deserialize outlines / paint groups before scale (may scale points)
        outlines_raw = manifest.get("painted_zone_outlines") or {}
        painted_outlines = {}
        for k, v in outlines_raw.items():
            try:
                zid = int(k)
            except Exception:
                continue
            if isinstance(v, dict):
                pts = []
                for p in v.get("points") or []:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        pts.append((float(p[0]), float(p[1])))
                painted_outlines[zid] = {
                    "points": pts,
                    "width": int(v.get("width", 3) or 3),
                }

        pgd_raw = manifest.get("paint_group_data") or {}
        paint_group_data = {str(gtag): list(recs or []) for gtag, recs in pgd_raw.items()}

        (
            zones,
            base_atlas,
            borders_pure,
            page_overlay,
            paint_strokes,
            img_x,
            img_y,
            painted_outlines,
            paint_group_data,
            did_scale,
            sx_bg,
            sy_bg,
        ) = self._scale_catlas_layers_to_background(
            zones=zones,
            base_atlas=base_atlas,
            borders_pure=borders_pure,
            page_overlay=page_overlay,
            paint_strokes=paint_strokes,
            img_x=img_x,
            img_y=img_y,
            saved_bg=saved_bg,
            cur_bg_size=cur_bg_size,
            atlas_filetype=atlas_filetype,
            painted_outlines=painted_outlines,
            paint_group_data=paint_group_data,
        )

        self.save_state()
        clear_preprocess_cache()

        # Fresh view scale so placement math matches model pixels * 1.0
        self.view_scale = 1.0

        self.current_page = page
        if atlas_filetype:
            self.atlas_filetype = atlas_filetype
        elif base_atlas is not None or borders_pure is not None:
            self.atlas_filetype = "allen" if borders_pure is not None else "pdf"
        elif zones is not None:
            if not self.atlas_filetype:
                self.atlas_filetype = "img"

        if base_atlas is not None:
            self.base_page_images[page] = base_atlas
            self.page_images[page] = (
                page_overlay if page_overlay is not None else base_atlas.copy()
            )
            self.img = self.base_page_images[page].copy()
        elif page_overlay is not None:
            self.base_page_images[page] = page_overlay.copy()
            self.page_images[page] = page_overlay
            self.img = page_overlay.copy()
        elif zones is not None and self.atlas_filetype in ("img", None):
            tw, th = zones.size
            empty = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
            self.base_page_images[page] = empty
            self.page_images[page] = empty.copy()

        if borders_pure is not None:
            self.allen_borders_pure = borders_pure
        elif atlas_filetype == "allen" and base_atlas is not None:
            self.allen_borders_pure = base_atlas.copy()

        if nissl_ref is not None:
            self.allen_nissl_reference = nissl_ref

        if zones is not None:
            try:
                zarr = np.array(zones).astype(np.uint8)
                zones = Image.fromarray(zarr, mode="L")
            except Exception:
                if zones.mode != "L":
                    zones = zones.convert("L")
            self.mask_images[page] = zones

        names = manifest.get("zone_names") or {}
        if names:
            names = {int(k): v for k, v in names.items()}
            self.zone_names[page] = names
        else:
            self.zone_names.setdefault(page, {})

        zc = int(manifest.get("zone_counter", 0) or 0)
        if self.zone_names.get(page):
            try:
                zc = max(zc, max(int(k) for k in self.zone_names[page].keys()))
            except Exception:
                pass
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                zc = max(zc, int(np.array(self.mask_images[page]).max()))
            except Exception:
                pass
        self.zone_counters[page] = zc

        self.painted_zone_outlines = painted_outlines or {}
        self.paint_group_data = paint_group_data or {}

        npg = manifest.get("named_paint_groups") or {}
        self.named_paint_groups = {}
        for gtag, nm in npg.items():
            self.named_paint_groups[str(gtag)] = nm

        meta = manifest.get("allen_zone_meta") or {}
        if meta:
            restored_meta = {}
            for pkey, pmeta in meta.items():
                try:
                    p_int = int(pkey)
                except Exception:
                    p_int = pkey
                inner = {}
                for zid, m in (pmeta or {}).items():
                    try:
                        inner[int(zid)] = m
                    except Exception:
                        inner[zid] = m
                restored_meta[p_int] = inner
            self.allen_zone_meta = restored_meta

        if paint_strokes is not None:
            self.paint_layer = paint_strokes
        elif cur_bg is not None:
            self.paint_layer = Image.new("RGBA", cur_bg.size, (0, 0, 0, 0))
        else:
            self.paint_layer = None

        # Placement in model pixels (display = img_* * view_scale)
        self.img_x = float(img_x)
        self.img_y = float(img_y)

        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        try:
            self._clear_edge_highlight()
        except Exception:
            pass
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        if hasattr(self, "region_move_mode"):
            self.region_move_mode.set(False)

        # Ensure L/R structures are independent IDs with _r/_l (if mask still shared)
        try:
            self._apply_bilateral_hemisphere_split(page, quiet=True)
        except Exception as e:
            logger.debug(f"hemisphere split after .catlas load: {e}")
            try:
                self._ensure_hemisphere_zone_suffixes(page)
            except Exception:
                pass

        try:
            if page in self.base_page_images:
                self._rebuild_page_overlays(page)
        except Exception as e:
            logger.debug(f"rebuild overlays after .catlas load: {e}")

        self.show_page()
        if hasattr(self, "_update_ribbon_selection"):
            self._update_ribbon_selection()

        n_zones = len(self.zone_names.get(page, {}) or {})
        bg_note = (
            f"Applied onto current image {tuple(cur_bg_size)}"
            if cur_bg_size
            else "No TIFF loaded — schematic only (import a TIFF to count)"
        )
        size_note = ""
        if did_scale:
            size_note = (
                f"\nRescaled with background {tuple(saved_bg)} → {tuple(cur_bg_size)} "
                f"(sx={sx_bg:.4f}, sy={sy_bg:.4f}) so placement stays registered."
            )
        messagebox.showinfo(
            "Cropped Atlas Loaded",
            f"Loaded cropped atlas from:\n{path}\n\n"
            f"Named regions (Atlas Manager): {n_zones}\n"
            f"Atlas type: {self.atlas_filetype or 'n/a'}\n"
            f"Placement: ({self.img_x:.1f}, {self.img_y:.1f})\n"
            f"{bg_note}{size_note}\n\n"
            "Use Count Cells to quantify on this channel with the same regions.",
        )
        logger.info(
            f"Loaded .catlas {path}: zones={n_zones} filetype={self.atlas_filetype} "
            f"offset=({self.img_x},{self.img_y}) bg={cur_bg_size} scaled={did_scale}"
        )

    def use_pen(self):
        # self.activate_button("Pen")
        self.output.bind('<B1-Motion>', self.paint)

    def use_eraser(self):
        # self.activate_button("Eraser", eraser_mode=True)
        self.output.bind('<B1-Motion>', self.erase)

    def activate_button(self, some_button, eraser_mode=False):
        self.active_button = some_button
        self.eraser_on = eraser_mode

    def paint(self, event):
        """Draw freehand using the pen.

        Model space is atlas-native when an atlas is loaded (so strokes register into
        the atlas zone mask for Count Cells), otherwise background-image space.
        """
        self.line_width = self.brush_size.get()
        paint_color = self.color

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_paint_model(cx, cy)

        # Start of a new continuous stroke?
        if self.old_x is None and self.old_y is None:
            self.save_state()  # Snapshot before this new stroke so Undo can remove it
            self._paint_group_counter += 1
            self.current_paint_group = f"paintgroup_{self._paint_group_counter}"
            self.old_x = ix
            self.old_y = iy
            return  # nothing to draw on first point

        prev_ix = self.old_x
        prev_iy = self.old_y

        prev_cx, prev_cy = self._paint_model_to_canvas(prev_ix, prev_iy)
        curr_cx, curr_cy = self._paint_model_to_canvas(ix, iy)

        tags = ('paint', self.current_paint_group)
        self.output.create_line(
            (prev_cx, prev_cy, curr_cx, curr_cy),
            width=self.line_width,
            fill=paint_color,
            capstyle=tk.ROUND,
            smooth=tk.TRUE,
            splinesteps=36,
            tags=tags
        )

        # Durable geometry in paint/zone model space (atlas or image)
        if self.current_paint_group:
            if self.current_paint_group not in self.paint_group_data:
                self.paint_group_data[self.current_paint_group] = []
            self.paint_group_data[self.current_paint_group].append({
                'model_points': [prev_ix, prev_iy, ix, iy],
                'width': self.line_width,
                'space': 'atlas' if self._paint_uses_atlas_space() else 'image',
            })

        self.old_x = ix
        self.old_y = iy

        self.output.config(scrollregion=self.output.bbox(tk.ALL))
    
    def erase(self, event):
        if len(self.output.find_withtag('paint')) == 0:
            return
        x = event.x
        y = event.y
        brush = self.brush_size.get()
        # find all paint within brush size of mouse
        for item in self.output.find_overlapping(x-brush, y-brush, x+brush, y+brush):
            # evaluate all tags the item has
            for tag in self.output.gettags(item):
                if tag != 'paint':
                    continue # use continue to ensure all tags are checked, paint doesnt need to be the first
                objectToBeDeleted = item
                self.output.delete(objectToBeDeleted)

    def reset_toggle(self, event):
        """Toggle pen stroke mode (drag vs segment) with the 's' key. No menu label."""
        if self.draw_type == 'drag':
            self.output.unbind('<ButtonRelease-1>')
            self.draw_type = 'segment'
        elif self.draw_type == 'segment':
            self.output.bind('<ButtonRelease-1>', self.reset)
            self.draw_type = 'drag'
            self.reset(event)
        else:
            print('error', file=sys.stderr)
        logger.debug(f"Pen mode: {self.draw_type}")

    def reset(self, event):
        self.old_x, self.old_y = None, None
        self.current_paint_group = None  # End the current continuous stroke group

        # Commit the just-finished stroke to the persistent paint_layer for zoom safety.
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()

        # Delete the temporary items now that they are committed.
        # This prevents them from being scaled on zoom (which caused duplication/displacement)
        # and from surviving show_page / scroll. Naming uses durable data + spatial lookup
        # as fallback (see name_painted_region).
        self.output.delete('paint')

        # Ensure scrollregion covers the committed paint strokes.
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

        # Redraw to make the newly committed stroke visible in the paint_layer image.
        # Without this, the stroke would only appear after the next show_page (e.g. Stop Paint or zoom).
        self.show_page()
        self._update_ribbon_selection()

    def name_painted_region(self, event):
        """Right-click on a paint stroke to name the entire connected boundary.

        All line segments belonging to the same continuous stroke (mouse-down to mouse-up)
        are treated as one structural region and colored yellow together.

        Fixed to use proper canvas coordinates so labeling works after zoom.
        """
        # Note: We intentionally do *not* call save_state here for paint naming.
        # The drawing stroke was already snapshotted at the start of the group.
        # This keeps "create painted region (draw + name)" undoable as a unit for the visual paint + banner entry.

        # Convert to canvas coordinates (critical after zoom + scrolling)
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)

        # Tolerance in screen pixels; keep it reasonable even after zoom
        tolerance = 12
        candidates = self.output.find_overlapping(cx - tolerance, cy - tolerance,
                                                  cx + tolerance, cy + tolerance)

        paint_items = [item for item in candidates if 'paint' in self.output.gettags(item)]

        has_canvas_items = len(paint_items) > 0
        group_tag = None
        clicked_item = None
        tags = []

        if has_canvas_items:
            clicked_item = paint_items[0]
            tags = self.output.gettags(clicked_item)

            # Find which group this segment belongs to
            for t in tags:
                if t.startswith('paintgroup_'):
                    group_tag = t
                    break

            if not group_tag:
                # Very old strokes without group tags - treat as singleton
                group_tag = 'paintgroup_legacy'
                self.output.addtag_withtag(group_tag, clicked_item)

            # Get ALL segments that belong to this connected stroke
            all_segments = self.output.find_withtag(group_tag)
            if not all_segments:
                return

            # Color the entire connected boundary yellow (selection for renaming)
            for item in all_segments:
                self.output.itemconfig(item, fill='#ffcc00')
        else:
            # Fallback for after zoom/scroll/show_page when temporary canvas items have been cleaned.
            # Use durable paint_group_data + spatial hit test in paint model space.
            ix, iy = self._canvas_to_paint_model(cx, cy)
            tolerance_model = tolerance / max(self.view_scale, 0.01)
            for gtag, data_list in list(self.paint_group_data.items()):
                if not gtag.startswith('paintgroup_'):
                    continue
                for rec in data_list or []:
                    mps = rec.get('model_points', [])
                    for j in range(0, len(mps), 2):
                        mx = mps[j]
                        my = mps[j+1]
                        if abs(mx - ix) <= tolerance_model and abs(my - iy) <= tolerance_model:
                            group_tag = gtag
                            break
                    if group_tag:
                        break
                if group_tag:
                    break

            if not group_tag:
                return

            # No canvas items to color yellow or find segments from.
            # We'll still set the name and commit for zones/counting.
            all_segments = []  # no visual items to manipulate

        if not group_tag:
            return

        current_name = self.named_paint_groups.get(group_tag, "")
        prompt = "Enter a name for this painted region:"
        if current_name:
            prompt = f"Rename painted region (current: {current_name}):"

        name = simpledialog.askstring("Painted Region Name", prompt, initialvalue=current_name)
        if name is None:
            return

        name = name.strip()
        if not name:
            if group_tag in self.named_paint_groups:
                del self.named_paint_groups[group_tag]
            if has_canvas_items:
                for item in all_segments:
                    self.output.itemconfig(item, fill=self.DEFAULT_COLOR)
            return

        self.named_paint_groups[group_tag] = name

        # Immediately commit this named group to the zone mask / zone_names.
        # This guarantees that "naming the zones immediately after drawing" makes them
        # defined for Count Cells even if the user never clicks Stop Paint and even if
        # later show_page() calls delete the transient canvas vectors.
        self._convert_named_paints_to_zones()

        # Extra defensive untag and yellow only if we have canvas items.
        # Only dtag the group_tag if convert retired it (success); if still present in named,
        # the collection inside convert failed to find strokes -- leave the tag so Stop/Count
        # force paths or later converts can still discover the items via find_withtag.
        if has_canvas_items:
            if group_tag not in self.named_paint_groups:
                for item in all_segments:
                    try:
                        self.output.dtag(item, group_tag)
                    except Exception:
                        pass

            # Keep the whole group yellow to show it's a named structural boundary
            for item in all_segments:
                self.output.itemconfig(item, fill='#ffcc00')

        logger.info(f"Named paint group {group_tag} as '{name}' ({len(all_segments)} segments)")

        # Immediately refresh the canvas (so new zone mask is visible) and the Atlas Manager ribbon list
        # so the newly named painted region appears in "Labeled Regions" without requiring another action.
        self.show_page()
        self._update_ribbon_selection()

    def _commit_canvas_paint_to_layer(self):
        """Rasterize current 'paint' tagged canvas items into the persistent self.paint_layer.
        This makes painting survive zoom, show_page calls, etc.
        """
        if self.paint_layer is None:
            return

        paint_items = self.output.find_withtag('paint')
        if not paint_items:
            return

        draw = ImageDraw.Draw(self.paint_layer)

        # Group items by their paintgroup tag to process each continuous stroke once
        # This avoids drawing ears/caps at every segment vertex and prevents over-drawing.
        groups = {}
        for line in paint_items:
            group_tag = None
            for t in self.output.gettags(line):
                if t.startswith('paintgroup_'):
                    group_tag = t
                    break
            if group_tag is None:
                # This line item no longer has a group_tag (it was dtag'ed after naming).
                # It is a finalized named stroke. Skip it for re-baking in this commit
                # (to avoid duplicating it from scaled coords on zoom).
                continue
            if group_tag not in groups:
                groups[group_tag] = []
            groups[group_tag].append(line)

        for group_tag, items in groups.items():
            # Collect full ordered points for the stroke, preferring durable model data
            points = []
            width = 3
            fill = self.DEFAULT_COLOR  # fallback

            if group_tag in self.paint_group_data and self.paint_group_data[group_tag]:
                for rec in self.paint_group_data[group_tag]:
                    mp = rec.get('model_points', [])
                    for j in range(0, len(mp), 2):
                        # paint_layer is always image-space (drawn at canvas 0,0)
                        ax, ay = int(mp[j]), int(mp[j + 1])
                        ix, iy = self._paint_model_to_image(ax, ay)
                        points.append((ix, iy))
                    if 'width' in rec:
                        width = rec['width']
            else:
                # Fallback: collect from current canvas items (in the order found, may not be perfect)
                for line in items:
                    coords = self.output.coords(line)
                    if not coords or len(coords) < 4:
                        continue
                    for i in range(0, len(coords), 2):
                        cx = coords[i]
                        cy = coords[i + 1]
                        # Canvas → image space for paint_layer
                        ix = int(cx / self.view_scale) if self.view_scale else int(cx)
                        iy = int(cy / self.view_scale) if self.view_scale else int(cy)
                        points.append((ix, iy))
                    w = self.output.itemcget(line, 'width')
                    try:
                        width = max(width, int(float(w)))
                    except Exception:
                        pass
                    fill = self.output.itemcget(line, 'fill')

            if len(points) < 2:
                continue

            # Dedup consecutive identical points
            deduped = [points[0]]
            for p in points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            points = deduped

            if len(points) < 2:
                continue

            radius = max(1, width // 2)
            # Round caps ONLY at the true start and end of the entire stroke
            if points:
                px, py = points[0]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
                px, py = points[-1]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)
            draw.line(points, fill=fill, width=width, joint="curve")

    def _rebuild_paint_layer_from_data(self):
        """Force the persistent paint_layer to exactly match the groups currently present
        in self.paint_group_data (the durable source of truth for painted regions).

        This is called after undo restores an older paint_group_data (and possibly an
        older paint_layer snapshot) so that the *visible* baked strokes on the image
        are removed when the corresponding drawn/named region is undone.
        It re-rasterizes only the strokes that are still active in the restored history.

        Selected region boundaries (Atlas Manager selection) are drawn in yellow;
        all other region outlines stay black.
        """
        data = getattr(self, 'paint_group_data', None) or {}
        # Determine target size (prefer the original background so strokes stay registered to the image)
        size = None
        if getattr(self, 'original_background', None) is not None:
            size = self.original_background.size
        elif getattr(self, 'background_image', None) is not None:
            size = self.background_image.size
        elif getattr(self, 'paint_layer', None) is not None:
            size = self.paint_layer.size
        else:
            return

        fresh = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(fresh)
        default_color = getattr(self, 'DEFAULT_COLOR', 'black')
        selected_color = 'yellow'

        # Which zone (if any) is the Atlas Manager selection on this page
        page = getattr(self, 'current_page', None)
        selected_zid = None
        if (
            page is not None
            and getattr(self, 'selected_zone_id', None) is not None
            and getattr(self, 'selected_page', None) == page
        ):
            try:
                selected_zid = int(self.selected_zone_id)
            except Exception:
                selected_zid = None

        for group_tag, recs in list(data.items()):
            if not group_tag.startswith('paintgroup_') or not recs:
                continue
            points = []
            width = 3
            for rec in (recs or []):
                mp = rec.get('model_points') or rec.get('coords') or []
                if mp and len(mp) >= 2:
                    for j in range(0, len(mp), 2):
                        try:
                            ax, ay = int(mp[j]), int(mp[j + 1])
                            # paint_layer is image-space; convert from atlas model if needed
                            ix, iy = self._paint_model_to_image(ax, ay)
                            points.append((ix, iy))
                        except Exception:
                            pass
                w = rec.get('width')
                if w:
                    try:
                        width = max(width, int(w))
                    except Exception:
                        pass
            if len(points) < 2:
                continue
            # Dedup
            deduped = [points[0]]
            for p in points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            points = deduped
            if len(points) < 2:
                continue
            radius = max(1, width // 2)
            # Caps at true start/end
            if points:
                px, py = points[0]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=default_color)
                px, py = points[-1]
                draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=default_color)
            draw.line(points, fill=default_color, width=width, joint="curve")

        # Also draw refittable boundaries for named painted zones (so edge/border deformation
        # updates the visible outline to match the new zone shape).
        # Selected zone → yellow boundary; others → black.
        drawn_selected_outline = False
        if page is not None:
            zone_names_page = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
            # Normalize name keys to int for membership tests
            try:
                zone_name_ids = {int(k) for k in zone_names_page.keys()}
            except Exception:
                zone_name_ids = set(zone_names_page.keys())

            for zid, outline in list(getattr(self, 'painted_zone_outlines', {}).items()):
                try:
                    zid_int = int(zid)
                except Exception:
                    zid_int = zid
                if zid_int not in zone_name_ids and zid not in zone_names_page:
                    continue
                points = outline.get('points', [])
                w = outline.get('width', 3)
                if len(points) < 2:
                    continue
                # Dedup
                deduped = [points[0]]
                for p in points[1:]:
                    if p != deduped[-1]:
                        deduped.append(p)
                points = deduped
                if len(points) < 2:
                    continue

                is_selected = selected_zid is not None and zid_int == selected_zid
                color = selected_color if is_selected else default_color
                line_w = int(w) + 1 if is_selected else int(w)
                line_w = max(2, line_w)
                if is_selected:
                    drawn_selected_outline = True

                radius = max(1, line_w // 2)
                if points:
                    px, py = points[0]
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
                    px, py = points[-1]
                    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
                draw.line(points, fill=color, width=line_w, joint="curve")

            # Atlas / mask-only regions may have no painted outline: draw mask contour in yellow when selected.
            # Skip for Allen — mask lives in atlas overlay space (img_x/y/scale/rotate), not paint-layer
            # image space; drawing here misregisters the yellow outline. Allen selection uses orange
            # fill + yellow border on the atlas layer in _rebuild_page_overlays instead.
            if (
                selected_zid is not None
                and not drawn_selected_outline
                and getattr(self, "atlas_filetype", None) != "allen"
            ):
                self._draw_zone_contour_on_layer(
                    draw, page, selected_zid, color=selected_color, width=3, size=size
                )

        self.paint_layer = fresh

        # Keep self.img in sync for 'img' filetype code paths (load_page_image etc.)
        if hasattr(self, 'img'):
            try:
                self.img = fresh.copy()
            except Exception:
                self.img = fresh

    def _draw_zone_contour_on_layer(self, draw, page, zid, color='yellow', width=3, size=None):
        """Draw the outer contour of mask zone zid onto a PIL Draw context (model coords)."""
        if page not in getattr(self, 'mask_images', {}) or self.mask_images.get(page) is None:
            return
        try:
            m = np.array(self.mask_images[page])
            if m.ndim > 2:
                m = m.squeeze()
            zid = int(zid)
            binr = (m == zid).astype(float)
            if not binr.any():
                return
            # If mask size differs from paint layer size, scale contour points
            mh, mw = binr.shape[:2]
            sx = sy = 1.0
            if size is not None and size[0] > 0 and size[1] > 0:
                sx = float(size[0]) / float(mw)
                sy = float(size[1]) / float(mh)
            contours = measure.find_contours(binr, 0.5)
            if not contours:
                return
            # Longest contour = outer boundary
            contour = max(contours, key=len)
            points = []
            for y, x in contour:
                points.append((int(round(x * sx)), int(round(y * sy))))
            if len(points) < 2:
                return
            # Close the loop for a continuous outline
            if points[0] != points[-1]:
                points.append(points[0])
            line_w = max(2, int(width))
            radius = max(1, line_w // 2)
            px, py = points[0]
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
            draw.line(points, fill=color, width=line_w, joint="curve")
        except Exception as e:
            logger.debug(f"Could not draw zone contour for zid={zid}: {e}")

    def _refresh_selection_boundary_visual(self):
        """Rebuild paint outlines so the selected region boundary is yellow, others black.

        Safe to call after select/deselect from Atlas Manager or canvas.
        """
        try:
            # Need a size for paint_layer even when no paint strokes exist yet
            if self.paint_layer is None:
                size = None
                if getattr(self, 'original_background', None) is not None:
                    size = self.original_background.size
                elif getattr(self, 'background_image', None) is not None:
                    size = self.background_image.size
                if size is not None:
                    self.paint_layer = Image.new('RGBA', size, (0, 0, 0, 0))
            self._rebuild_paint_layer_from_data()
        except Exception as e:
            logger.debug(f"Selection boundary visual refresh failed: {e}")

    def _convert_named_paints_to_zones(self):
        """Convert named paint *groups* (connected strokes) into zone entries.

        Each named group (one continuous drawing action) gets a single zone_id,
        so the entire structural boundary is treated as one region for cell counting.

        When an atlas is loaded, zones are merged into the existing atlas mask
        (atlas model coordinates) so painted regions appear alongside atlas regions
        in the Atlas Manager and Count Cells.
        """
        if not self.named_paint_groups:
            return

        if self.current_page is None:
            self.current_page = 0

        mask_img, draw = self._ensure_zone_mask_for_paint()
        page = self.current_page

        for group_tag, name in list(self.named_paint_groups.items()):
            # Collect strokes from durable data first (stable model coords preferred), else live canvas.
            strokes = []
            if group_tag in self.paint_group_data:
                for rec in (self.paint_group_data.get(group_tag) or []):
                    mp = rec.get('model_points') or []
                    w = rec.get('width', 3)
                    if mp and len(mp) >= 2:
                        strokes.append((mp, w, True))
                    else:
                        c = rec.get('coords') or []
                        if c and len(c) >= 2:
                            strokes.append((c, w, False))
            for item_id in (self.output.find_withtag(group_tag) or []):
                try:
                    coords = self.output.coords(item_id) or []
                    if coords and len(coords) >= 4:
                        w = self.output.itemcget(item_id, 'width')
                        try:
                            w = int(float(w))
                        except Exception:
                            w = 3
                        strokes.append((coords, w, False))
                except Exception:
                    pass
            if not strokes and group_tag in self.named_paint_groups:
                for item_id in (self.output.find_withtag('paint') or []):
                    try:
                        coords = self.output.coords(item_id) or []
                        if coords and len(coords) >= 4:
                            w = self.output.itemcget(item_id, 'width')
                            try:
                                w = int(float(w))
                            except Exception:
                                w = 3
                            strokes.append((coords, w, False))
                    except Exception:
                        pass
            if not strokes:
                logger.warning(f"Paint group {group_tag} had no strokes to convert")
                continue

            self.zone_counters[page] += 1
            zone_id = self.zone_counters[page]

            if name is None or not str(name).strip():
                clean_name = f"Painted Region {zone_id}"
            else:
                clean_name = str(name).strip() or f"Painted Region {zone_id}"

            self.zone_names[page][zone_id] = clean_name

            group_model_points = []
            group_width = 3
            for coords, width, is_model in strokes:
                try:
                    if not coords or len(coords) < 4:
                        continue
                    for i in range(0, len(coords), 2):
                        if is_model:
                            ix = int(coords[i])
                            iy = int(coords[i + 1])
                        else:
                            cx = coords[i]
                            cy = coords[i + 1]
                            ix, iy = self._canvas_to_paint_model(cx, cy)
                        group_model_points.append((ix, iy))
                    group_width = max(group_width, width)
                except Exception as e:
                    logger.error(f"Failed to rasterize segment in group {group_tag}: {e}")

            if len(group_model_points) >= 2:
                deduped = [group_model_points[0]]
                for p in group_model_points[1:]:
                    if p != deduped[-1]:
                        deduped.append(p)
                group_model_points = deduped

                if len(group_model_points) >= 2:
                    radius = max(1, group_width // 2)
                    if group_model_points:
                        px, py = group_model_points[0]
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                        px, py = group_model_points[-1]
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                    draw.line(group_model_points, fill=zone_id, width=group_width, joint="curve")

            if group_model_points:
                try:
                    minx = min(p[0] for p in group_model_points)
                    maxx = max(p[0] for p in group_model_points)
                    miny = min(p[1] for p in group_model_points)
                    maxy = max(p[1] for p in group_model_points)
                    cx_seed = (minx + maxx) // 2
                    cy_seed = (miny + maxy) // 2
                    for dx, dy in [(0, 0), (2, 0), (-2, 0), (0, 2), (0, -2), (5, 0), (-5, 0), (0, 5), (0, -5)]:
                        sx = cx_seed + dx
                        sy = cy_seed + dy
                        if 0 <= sx < mask_img.width and 0 <= sy < mask_img.height:
                            if mask_img.getpixel((sx, sy)) == 0:
                                draw.floodfill((sx, sy), fill=zone_id, thresh=0)
                                break
                except Exception:
                    pass

            try:
                m = np.array(mask_img)
                zone_pixels = (m == zone_id)
                if zone_pixels.any():
                    filled = ndi.binary_fill_holes(zone_pixels)
                    # Never overwrite existing atlas / other painted zones
                    m[(filled) & (m == 0)] = zone_id
                    mask_img = Image.fromarray(m.astype(np.uint8), mode="L")
                    draw = ImageDraw.Draw(mask_img)
            except Exception as e:
                logger.debug(f"binary_fill_holes for zone {zone_id} skipped: {e}")

            n_pix = int(np.sum(np.array(mask_img) == zone_id))
            logger.info(
                f"Converted paint '{clean_name}' ({group_tag}) → zone {zone_id} "
                f"({n_pix} px, mask {mask_img.size}, atlas={self._paint_uses_atlas_space()})"
            )

            if zone_id not in self.painted_zone_outlines:
                self.painted_zone_outlines[zone_id] = {
                    'points': list(group_model_points),
                    'width': group_width
                }

            self.named_paint_groups.pop(group_tag, None)
            self.paint_group_data.pop(group_tag, None)
            for item_id in self.output.find_withtag(group_tag):
                try:
                    self.output.dtag(item_id, group_tag)
                except Exception:
                    pass

        self.mask_images[page] = mask_img

    def _force_paint_strokes_to_zones(self, paint_items):
        """
        Last-resort fallback: If the user has painted strokes on the canvas
        but they didn't get turned into zones (e.g. no right-click naming happened),
        convert whatever paint is still present into default "Painted Region" zones
        so that Count Cells produces a useful spreadsheet.
        """
        if not paint_items and not self.paint_group_data:
            return

        mask_img, draw = self._ensure_zone_mask_for_paint()
        page = self.current_page

        # Group remaining paint items by their group tag if present, otherwise treat all as one group
        groups = {}
        for item in paint_items or []:
            group_tag = None
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    group_tag = tag
                    break
            if group_tag is None:
                group_tag = 'unnamed_paint_group'
            if group_tag not in groups:
                groups[group_tag] = []
            groups[group_tag].append(item)

        for gtag in list(self.paint_group_data.keys()):
            if gtag not in groups:
                groups[gtag] = []

        for group_tag, items in groups.items():
            self.zone_counters[page] += 1
            zone_id = self.zone_counters[page]

            default_name = f"Painted Region {zone_id}"
            self.zone_names[page][zone_id] = default_name

            for item_id in items:
                try:
                    coords = self.output.coords(item_id)
                    if not coords or len(coords) < 4:
                        continue

                    width = self.output.itemcget(item_id, 'width')
                    try:
                        width = int(float(width))
                    except Exception:
                        width = 3

                    points = []
                    for i in range(0, len(coords), 2):
                        cx = coords[i]
                        cy = coords[i + 1]
                        ix, iy = self._canvas_to_paint_model(cx, cy)
                        points.append((ix, iy))

                    if len(points) < 2:
                        continue

                    radius = max(1, width // 2)
                    for px, py in points:
                        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                    draw.line(points, fill=zone_id, width=width, joint="curve")

                except Exception as e:
                    logger.error(f"Failed to force-convert paint item to zone: {e}")

            # If this group had no live canvas items (wiped), draw from durable recorded data (prefer model points)
            durable_points_for_flood = []
            if group_tag in self.paint_group_data:
                for rec in self.paint_group_data.get(group_tag, []):
                    try:
                        mp = rec.get('model_points')
                        width = rec.get('width', 3)
                        coords = mp if (mp and len(mp) >= 4) else rec.get('coords', [])
                        is_model = bool(mp and len(mp) >= 4)
                        if not coords or len(coords) < 4:
                            continue
                        points = []
                        for i in range(0, len(coords), 2):
                            if is_model:
                                ix = int(coords[i])
                                iy = int(coords[i + 1])
                            else:
                                cx = coords[i]
                                cy = coords[i + 1]
                                ix, iy = self._canvas_to_paint_model(cx, cy)
                            points.append((ix, iy))
                            durable_points_for_flood.append((ix, iy))
                        if len(points) < 2:
                            continue
                        radius = max(1, width // 2)
                        for px, py in points:
                            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=zone_id)
                        draw.line(points, fill=zone_id, width=width, joint="curve")
                    except Exception as e:
                        logger.error(f"Failed to force-convert durable paint data for {group_tag}: {e}")

            # Fill interior for durable-only (unnamed) groups as well
            if durable_points_for_flood:
                try:
                    minx = min(p[0] for p in durable_points_for_flood)
                    maxx = max(p[0] for p in durable_points_for_flood)
                    miny = min(p[1] for p in durable_points_for_flood)
                    maxy = max(p[1] for p in durable_points_for_flood)
                    cx_seed = (minx + maxx) // 2
                    cy_seed = (miny + maxy) // 2
                    for dx, dy in [(0,0), (2,0), (-2,0), (0,2), (0,-2)]:
                        sx = cx_seed + dx
                        sy = cy_seed + dy
                        if 0 <= sx < mask_img.width and 0 <= sy < mask_img.height:
                            if mask_img.getpixel((sx, sy)) == 0:
                                draw.floodfill((sx, sy), fill=zone_id, thresh=0)
                                break
                except Exception:
                    pass

            # Strong binary_fill_holes for force path (unnamed strokes auto-named at Count Cells time)
            try:
                m = np.array(mask_img)
                zone_pixels = (m == zone_id)
                if zone_pixels.any():
                    filled = ndi.binary_fill_holes(zone_pixels)
                    m[(filled) & (m == 0)] = zone_id
                    mask_img = Image.fromarray(m.astype(np.uint8))
                    draw = ImageDraw.Draw(mask_img)
            except Exception as e:
                logger.debug(f"binary_fill_holes (force) for zone {zone_id} skipped: {e}")

            logger.info(f"Force-converted paint group '{group_tag}' → zone {zone_id} ('{default_name}')")

            # Retire after processing (prevents re-counting the same strokes as extra zones)
            self.named_paint_groups.pop(group_tag, None)
            self.paint_group_data.pop(group_tag, None)
            for item_id in self.output.find_withtag(group_tag):
                try:
                    self.output.dtag(item_id, group_tag)
                except Exception:
                    pass

        self.mask_images[self.current_page] = mask_img

    def show_brush_settings(self): # This is the layout to be applied to all other spawned windows
        brush_win = None
        window = brush_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Brush Settings")
        tk.Label(window, text="Brush Size: ").grid(row=2, column=0)
        choose_size_button = tk.Scale(window, from_=1, to=10, orient=tk.HORIZONTAL, variable=self.brush_size)
        choose_size_button.grid(row=2, column=1, padx=5, pady=5)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)

    def show_scale_settings(self):
        scale_win = None
        window = scale_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Scale Settings")
        # Scale controls
        scale_label = ttk.Label(window, text="Scale:")
        scale_label.grid(row=0, column=0, columnspan=2)
        self.scale_entry = ttk.Entry(window, width=10)
        self.scale_entry.grid(row=0, column=2, padx=5, pady=5)
        # Resize buttons
        ttk.Button(window, text="Resize", command=self.resize_custom).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(window, text="Resize X", command=self.resize_x).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(window, text="Resize Y", command=self.resize_y).grid(row=1, column=2, padx=5, pady=5)
        ttk.Button(
            window,
            text="Fit to image",
            command=lambda: (self.fit_atlas_to_image(), window.destroy()),
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=8)
        ttk.Label(
            window,
            text="Fit to image: resize atlas (or cropped atlas) to the loaded\n"
                 "TIFF size and align both top-left corners.",
            font=("Helvetica", 8),
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 6))
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def show_rotate_settings(self):
        rotate_win = None
        window = rotate_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Rotate Settings")
        rotation_label = ttk.Label(window, text="Rotate (degrees):")
        rotation_label.grid(row=0, column=0)
        self.rotation_entry = ttk.Entry(window, width=10)
        self.rotation_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(window, text="Rotate", command=self.rotate_custom).grid(row=0, column=2, padx=5, pady=5)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def show_brightness_settings(self):
        brightness_win = None
        window = brightness_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button (titlebar close) to close the dialog properly.
        # (Previously used disable_event which did nothing; the Close button worked but X did not.)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Brightness Settings")
        brightness_label = ttk.Label(window, text="Brightness:")
        brightness_label.grid(row=0, column=0)
        brightness_slider = ttk.Scale(
            window, from_=-100, to=400, orient=tk.HORIZONTAL, command=self.update_brightness
        )
        brightness_slider.grid(row=0, column=1, sticky="ew", padx=5, pady=5)
        brightness_slider.set(getattr(self, "brightness", 0.0) or 0.0)
        window.columnconfigure(1, weight=1)
        ttk.Label(
            window,
            text="Adjusts the loaded image only (not the atlas).",
            font=("Helvetica", 8),
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=5)
        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)

    def show_mask_settings(self, restore_geometry=None):
        mask_settings_win = None
        window = mask_settings_win
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        # Allow the window's X button to close the dialog properly
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)

        window.title("Mask Settings")

        if restore_geometry:
            window.geometry(restore_geometry)

        # Configure grid layout
        window.columnconfigure(0, weight=1)
        window.columnconfigure(1, weight=1)

        def save_settings():
            self.image_processor.save_config()

        def load_settings():
            geom = window.geometry()
            self.image_processor.load_config()
            window.destroy()  # Reopen to refresh values
            self.show_mask_settings(restore_geometry=geom)

        # --- Autotune helpers ---
        def _apply_autotune_and_refresh(adjust_func):
            geom = window.geometry()
            adjust_func()
            window.destroy()
            self.show_mask_settings(restore_geometry=geom)
            # Automatically refresh the mask visualization using the new autotuned settings
            self.show_cell_mask_threshold(calculate=True)

        def _is_blob_method():
            m = (self.image_processor.cell_config.detection_method or "blob").lower()
            # Legacy "adaptive" counts as blob-family
            return m in ("blob", "dog", "log", "adaptive")

        def _adaptive_on():
            cfg = self.image_processor.cell_config
            m = (cfg.detection_method or "blob").lower().strip()
            if m == "adaptive":
                return True
            return int(getattr(cfg, "adaptive_enabled", 0) or 0) != 0

        def autotune_more_cells():
            cfg = self.image_processor.cell_config
            if _is_blob_method():
                cfg.blob_threshold = max(0.005, round(cfg.blob_threshold - 0.02, 3))
                cfg.blob_min_sigma = max(0.8, round(cfg.blob_min_sigma - 0.3, 1))
                cfg.blob_min_area = max(3, cfg.blob_min_area - 4)
                cfg.blob_free_space = max(0.15, round(float(getattr(cfg, "blob_free_space", 0.45)) - 0.08, 2))
                cfg.blob_min_peak_intensity = max(
                    0.0, round(float(getattr(cfg, "blob_min_peak_intensity", 0.0)) - 0.05, 2)
                )
                if _adaptive_on():
                    cfg.adaptive_sensitivity = max(
                        0.25, round(float(getattr(cfg, "adaptive_sensitivity", 1.0)) - 0.15, 2)
                    )
                    cfg.adaptive_packing = min(
                        1.0, round(float(getattr(cfg, "adaptive_packing", 0.5)) + 0.1, 2)
                    )
            else:
                cfg.min_cell_size = max(5, cfg.min_cell_size - 6)
                cfg.peak_min_intensity = max(0.01, round(cfg.peak_min_intensity - 0.06, 2))
                cfg.circularity_threshold = max(0.25, round(cfg.circularity_threshold - 0.06, 2))
                cfg.min_peak_distance = max(2, cfg.min_peak_distance - 1)
            _apply_autotune_and_refresh(lambda: None)

        def autotune_less_cells():
            cfg = self.image_processor.cell_config
            if _is_blob_method():
                cfg.blob_threshold = min(0.9, round(cfg.blob_threshold + 0.025, 3))
                cfg.blob_min_area += 6
                cfg.blob_free_space = min(0.9, round(float(getattr(cfg, "blob_free_space", 0.45)) + 0.08, 2))
                if _adaptive_on():
                    cfg.adaptive_sensitivity = min(
                        3.0, round(float(getattr(cfg, "adaptive_sensitivity", 1.0)) + 0.15, 2)
                    )
                    cfg.adaptive_packing = max(
                        0.0, round(float(getattr(cfg, "adaptive_packing", 0.5)) - 0.1, 2)
                    )
            else:
                cfg.min_cell_size += 6
                cfg.peak_min_intensity = min(0.95, round(cfg.peak_min_intensity + 0.06, 2))
                cfg.circularity_threshold = min(0.95, round(cfg.circularity_threshold + 0.06, 2))
                cfg.min_peak_distance += 1
            _apply_autotune_and_refresh(lambda: None)

        def autotune_bigger_cells():
            cfg = self.image_processor.cell_config
            if _is_blob_method():
                cfg.blob_max_sigma = min(40.0, round(cfg.blob_max_sigma + 2.0, 1))
                cfg.blob_max_area += 80
                cfg.blob_radius_scale = min(3.5, round(float(getattr(cfg, "blob_radius_scale", 1.8)) + 0.15, 2))
            else:
                cfg.min_cell_size += 8
                cfg.max_cell_size += 25
                cfg.circularity_threshold = min(0.92, round(cfg.circularity_threshold + 0.04, 2))
                cfg.watershed_compactness = min(0.8, round(cfg.watershed_compactness + 0.15, 2))
            _apply_autotune_and_refresh(lambda: None)

        def autotune_smaller_cells():
            cfg = self.image_processor.cell_config
            if _is_blob_method():
                cfg.blob_max_sigma = max(cfg.blob_min_sigma + 1.0, round(cfg.blob_max_sigma - 2.0, 1))
                cfg.blob_max_area = max(cfg.blob_min_area + 10, cfg.blob_max_area - 60)
                cfg.blob_radius_scale = max(1.0, round(float(getattr(cfg, "blob_radius_scale", 1.8)) - 0.15, 2))
            else:
                cfg.min_cell_size = max(5, cfg.min_cell_size - 8)
                cfg.max_cell_size = max(20, cfg.max_cell_size - 20)
                cfg.circularity_threshold = max(0.3, round(cfg.circularity_threshold - 0.04, 2))
            _apply_autotune_and_refresh(lambda: None)

        def autotune_brighter_cells():
            cfg = self.image_processor.cell_config
            if _is_blob_method():
                cfg.blob_threshold = min(0.9, round(cfg.blob_threshold + 0.02, 3))
                cfg.blob_min_peak_intensity = min(
                    0.9, round(float(getattr(cfg, "blob_min_peak_intensity", 0.0)) + 0.08, 2)
                )
            else:
                cfg.peak_min_intensity = min(0.95, round(cfg.peak_min_intensity + 0.10, 2))
                cfg.circularity_threshold = min(0.9, round(cfg.circularity_threshold + 0.03, 2))
            _apply_autotune_and_refresh(lambda: None)

        def autotune_dimmer_cells():
            cfg = self.image_processor.cell_config
            if _is_blob_method():
                cfg.blob_threshold = max(0.005, round(cfg.blob_threshold - 0.03, 3))
                cfg.blob_min_sigma = max(0.8, round(cfg.blob_min_sigma - 0.4, 1))
                cfg.blob_min_area = max(3, cfg.blob_min_area - 4)
                cfg.blob_min_peak_intensity = max(
                    0.0, round(float(getattr(cfg, "blob_min_peak_intensity", 0.0)) - 0.08, 2)
                )
            else:
                cfg.peak_min_intensity = max(0.01, round(cfg.peak_min_intensity - 0.10, 2))
                cfg.min_cell_size = max(5, cfg.min_cell_size - 3)
            _apply_autotune_and_refresh(lambda: None)


        def generate_setting(frame, attr, value, row, config):
                label = ttk.Label(frame, text=f"{attr.replace('_', ' ').title()}:")
                label.grid(row=row, column=0, sticky='ew', padx=5, pady=2)
                entry = ttk.Entry(frame)
                entry.insert(0, str(value))
                entry.grid(row=row, column=1, sticky='ew', padx=5, pady=2)
                # Hover either label or entry for parameter explanation
                attach_param_tooltip(label, attr)
                attach_param_tooltip(entry, attr)
                setter = create_setter(entry, config, attr)
                entry.bind("<FocusOut>", setter)
                entry.bind("<Return>", setter)
                # Track for method-based lock/dim
                if not hasattr(frame, "_param_widgets"):
                    frame._param_widgets = []
                frame._param_widgets.append((label, entry))

        def generate_option_frames():
            # Preprocess image
            # keyword:grid_alignment
            self.bg_tophat_frame = ttk.LabelFrame(bg_frame, text='Tophat')
            self.bg_gaussian_frame = ttk.LabelFrame(bg_frame, text='Background Gaussian')
            self.nr_gaussian_frame = ttk.LabelFrame(nr_frame, text='Noise Reduction Gaussian')
            self.nr_median_frame = ttk.LabelFrame(nr_frame, text='Median')
            self.nr_bilateral_frame = ttk.LabelFrame(nr_frame, text='Bilateral')
            self.ce_stretch_frame = ttk.LabelFrame(ce_frame, text='Stretch')
            self.ce_clahe_frame = ttk.LabelFrame(ce_frame, text='Clahe')
            self.ce_gamma_frame = ttk.LabelFrame(ce_frame, text='Gamma')
            self.se_unsharp_frame = ttk.LabelFrame(se_frame, text='Unsharp Mask')
            bg_tophat_options = ['disk_radius']
            bg_gaussian_options = ['bg_gaussian_sigma']
            nr_gaussian_options = ['nr_gaussian_sigma']
            nr_median_options = ['median_kernel']
            nr_bilateral_options = ['bilateral_sigma_color', 'bilateral_sigma_space']
            ce_stretch_options = [] # None
            ce_clahe_options = ['clahe_kernel', 'clahe_clip_limit']
            ce_gamma_options = ['gamma']
            se_unsharp_options = ['unsharp_radius', 'unsharp_amount']


            preprocess_options = [  bg_tophat_options,
                                    bg_gaussian_options,
                                    nr_gaussian_options,
                                    nr_median_options,
                                    nr_bilateral_options,
                                    ce_stretch_options,
                                    ce_clahe_options,
                                    ce_gamma_options,
                                    se_unsharp_options 
                                ]
            preprocess_frames = [   self.bg_tophat_frame,
                                    self.bg_gaussian_frame,
                                    self.nr_gaussian_frame,
                                    self.nr_median_frame,
                                    self.nr_bilateral_frame,
                                    self.ce_stretch_frame,
                                    self.ce_clahe_frame,
                                    self.ce_gamma_frame,
                                    self.se_unsharp_frame
                                ]


            row = 0
            for i in range(0, len(preprocess_options)):
                for attr in preprocess_options[i]:
                    frame = preprocess_frames[i]
                    config = self.image_processor.preprocess_config
                    value = getattr(config, attr)
                    generate_setting(frame, attr, value, row, config)
                    row += 1


            # Cell Detection
            self.tm_otsu_frame = ttk.LabelFrame(tm_frame, text='Otsu')
            self.tm_adaptive_frame = ttk.LabelFrame(tm_frame, text='Adaptive')
            self.tm_local_frame = ttk.LabelFrame(tm_frame, text='Local')
            self.tm_manual_frame = ttk.LabelFrame(tm_frame, text='Manual')
            self.other_circularity_frame = ttk.LabelFrame(option_frame, text='Circularity')
            self.other_watershed_frame = ttk.LabelFrame(option_frame, text='Watershed')
            self.blob_frame = ttk.LabelFrame(option_frame, text='Blob Detection (Recommended)')
            self.adaptive_det_frame = ttk.LabelFrame(
                option_frame, text='Adaptive Detection (mixed background / density)'
            )

            # Quick method switcher (blob/dog/watershed) + Adaptive overlay checkbox
            method_frame = ttk.Frame(option_frame)
            method_lbl = ttk.Label(method_frame, text="Detection Method:")
            method_lbl.pack(side='left', padx=5)
            attach_param_tooltip(method_lbl, "detection_method")
            cfg0 = self.image_processor.cell_config
            # Normalize legacy detection_method="adaptive" → base method + checkbox
            _dm = (cfg0.detection_method or "blob").lower().strip()
            if _dm == "adaptive":
                _base = (getattr(cfg0, "adaptive_base_method", None) or "blob").lower().strip()
                cfg0.detection_method = _base if _base in ("blob", "dog", "log") else "blob"
                cfg0.adaptive_enabled = 1
            self.detection_method_var = tk.StringVar(value=cfg0.detection_method)
            self.adaptive_enabled_var = tk.IntVar(
                value=1 if int(getattr(cfg0, "adaptive_enabled", 0) or 0) else 0
            )

            def _set_det_method(m):
                self.image_processor.cell_config.detection_method = m
                if m in ("blob", "dog", "log"):
                    self.image_processor.cell_config.adaptive_base_method = (
                        "dog" if m == "dog" else "blob"
                    )
                _update_detection_param_lock()

            def _set_adaptive_enabled():
                on = 1 if self.adaptive_enabled_var.get() else 0
                self.image_processor.cell_config.adaptive_enabled = on
                _update_detection_param_lock()

            rb_blob = ttk.Radiobutton(
                method_frame,
                text="Blob / LoG",
                variable=self.detection_method_var,
                value="blob",
                command=lambda: _set_det_method("blob"),
            )
            rb_dog = ttk.Radiobutton(
                method_frame,
                text="DoG",
                variable=self.detection_method_var,
                value="dog",
                command=lambda: _set_det_method("dog"),
            )
            rb_ws = ttk.Radiobutton(
                method_frame,
                text="Watershed",
                variable=self.detection_method_var,
                value="watershed",
                command=lambda: _set_det_method("watershed"),
            )
            rb_blob.pack(side="left")
            rb_dog.pack(side="left")
            rb_ws.pack(side="left")
            cb_adaptive = ttk.Checkbutton(
                method_frame,
                text="Adaptive",
                variable=self.adaptive_enabled_var,
                command=_set_adaptive_enabled,
            )
            cb_adaptive.pack(side="left", padx=(12, 0))
            self._mask_settings_adaptive_cb = cb_adaptive
            attach_param_tooltip(
                rb_blob,
                "detection_method",
                "LoG multi-scale blob finder — default for fluorescent spots.",
            )
            attach_param_tooltip(
                rb_dog,
                "detection_method",
                "Difference of Gaussians — try if LoG misses obvious cells of mixed sizes.",
            )
            attach_param_tooltip(
                rb_ws,
                "detection_method",
                "Legacy threshold + watershed pipeline.",
            )
            attach_param_tooltip(
                cb_adaptive,
                "adaptive_enabled",
                "Overlay on Blob/DoG: tile-local thresholds, dual-pass fusion, density packing. "
                "Leave unchecked for plain Blob or DoG. Ignored when Watershed is selected.",
            )
            method_frame.grid(row=3, column=0, sticky='w', pady=8)

            tm_otsu_options = [] # None
            tm_adaptive_options = ['adaptive_block_size']
            tm_local_options = ['local_radius']
            tm_manual_options = ['manual_threshold']
            other_circularity_options = ['min_cell_size', 'max_cell_size', 'circularity_threshold']
            other_watershed_options = ['min_peak_distance', 'peak_min_intensity', 'watershed_compactness']
            blob_options = [
                "blob_min_sigma",
                "blob_max_sigma",
                "blob_num_sigma",
                "blob_threshold",
                "blob_threshold_rel",
                "blob_overlap",
                "blob_min_area",
                "blob_max_area",
                "blob_radius_scale",
                "blob_free_space",
                "blob_min_peak_intensity",
                "blob_min_local_snr",
                "blob_local_snr_outer",
                "blob_exclude_border",
                "blob_min_circularity",
                "blob_min_isotropy",
                "blob_reject_tissue_edge",
                "blob_edge_dark_frac",
                "blob_bg_relative",
            ]
            # Base detector is the Blob/DoG radio; adaptive_base_method is synced automatically
            adaptive_det_options = [
                "adaptive_tile_size",
                "adaptive_tile_overlap",
                "adaptive_sensitivity",
                "adaptive_packing",
                "adaptive_dual_pass",
            ]

            cell_detect_options = [ tm_otsu_options,
                                    tm_adaptive_options,
                                    tm_local_options,
                                    tm_manual_options,
                                    other_circularity_options,
                                    other_watershed_options,
                                    blob_options,
                                    adaptive_det_options,
                                  ]

            cell_detect_frames = [  self.tm_otsu_frame,
                                    self.tm_adaptive_frame,
                                    self.tm_local_frame,
                                    self.tm_manual_frame,
                                    self.other_circularity_frame,
                                    self.other_watershed_frame,
                                    self.blob_frame,
                                    self.adaptive_det_frame,
                                 ]

            for i in range(0, len(cell_detect_options)):
                for attr in cell_detect_options[i]:
                    frame = cell_detect_frames[i]
                    config = self.image_processor.cell_config
                    value = getattr(config, attr)
                    generate_setting(frame, attr, value, row, config)
                    row += 1

            # Static: do not change with radiobutton, so they can be shown now
            self.other_circularity_frame.grid(row=0, column=0, sticky='news')
            self.other_watershed_frame.grid(row=1, column=0, sticky='news')
            self.blob_frame.grid(row=2, column=0, sticky='news')
            self.adaptive_det_frame.grid(row=4, column=0, sticky='news')

            # Dim styles for inactive method panels (~70% translucent look)
            try:
                style = ttk.Style()
                style.configure("Dimmed.TLabel", foreground="#a8a8a8")
                style.configure("Dimmed.TLabelframe", foreground="#a8a8a8")
                style.configure("Dimmed.TLabelframe.Label", foreground="#a8a8a8")
                style.configure("Dimmed.TEntry", foreground="#a8a8a8", fieldbackground="#f3f3f3")
                style.map(
                    "Dimmed.TEntry",
                    foreground=[("disabled", "#a8a8a8")],
                    fieldbackground=[("disabled", "#f0f0f0")],
                )
            except Exception:
                pass

            def _set_frame_locked(frame, locked, dim=True):
                """Lock (disable) and fade a parameter panel when its method is inactive.

                Tk/ttk cannot do true per-widget alpha on all platforms; we approximate
                ~70% translucent by graying labels/titles and disabling entries (locked).
                """
                if frame is None:
                    return

                try:
                    if locked and dim:
                        frame.configure(style="Dimmed.TLabelframe")
                    else:
                        frame.configure(style="TLabelframe")
                except Exception:
                    pass

                widgets = getattr(frame, "_param_widgets", None) or []
                for label, entry in widgets:
                    try:
                        if locked:
                            entry.state(["disabled"])
                            if dim:
                                label.configure(style="Dimmed.TLabel")
                            # Soften entry field appearance when locked
                            try:
                                entry.configure(style="Dimmed.TEntry")
                            except Exception:
                                pass
                        else:
                            entry.state(["!disabled"])
                            label.configure(style="TLabel")
                            try:
                                entry.configure(style="TEntry")
                            except Exception:
                                pass
                    except Exception:
                        try:
                            entry.configure(state="disabled" if locked else "normal")
                            if locked and dim:
                                label.configure(foreground="#a8a8a8")
                            else:
                                label.configure(foreground="")
                        except Exception:
                            pass

                # Dim any other labels in the frame (e.g. empty sections)
                try:
                    for child in frame.winfo_children():
                        if isinstance(child, ttk.Label) and (
                            not widgets
                            or child not in [w[0] for w in widgets]
                        ):
                            child.configure(
                                style="Dimmed.TLabel" if locked and dim else "TLabel"
                            )
                except Exception:
                    pass

            def _update_detection_param_lock(*_args):
                """Enable only panels for the active detection approach; dim+lock the rest."""
                m = (self.detection_method_var.get() or "blob").lower().strip()
                adaptive_on = bool(self.adaptive_enabled_var.get())
                blob_family = m in ("blob", "dog", "log")
                is_ws = m == "watershed"

                # Adaptive checkbox only applies to Blob/DoG
                try:
                    cb = getattr(self, "_mask_settings_adaptive_cb", None)
                    if cb is not None:
                        if is_ws:
                            cb.state(["disabled"])
                        else:
                            cb.state(["!disabled"])
                except Exception:
                    pass

                # Watershed path
                _set_frame_locked(self.other_circularity_frame, locked=not is_ws)
                _set_frame_locked(self.other_watershed_frame, locked=not is_ws)
                for fr in (
                    getattr(self, "tm_otsu_frame", None),
                    getattr(self, "tm_adaptive_frame", None),
                    getattr(self, "tm_local_frame", None),
                    getattr(self, "tm_manual_frame", None),
                ):
                    if fr is not None:
                        _set_frame_locked(fr, locked=not is_ws)

                # Blob/DoG shared params
                _set_frame_locked(self.blob_frame, locked=not blob_family)

                # Adaptive overlay — only with Blob/DoG + Adaptive checked
                _set_frame_locked(
                    self.adaptive_det_frame,
                    locked=not (blob_family and adaptive_on),
                )

            self._update_detection_param_lock = _update_detection_param_lock
            # Defer one tick so geometry/styles exist before dimming
            try:
                window.after_idle(_update_detection_param_lock)
            except Exception:
                _update_detection_param_lock()

        def create_setter(entry_widget, config_obj, attr_name):
            def setter(*args):
                val = entry_widget.get()
                try:
                    current_type = type(getattr(config_obj, attr_name))
                    if current_type == int:
                        val = int(val)
                    elif current_type == float:
                        val = float(val)
                    elif current_type == str:
                        val = str(val)
                    setattr(config_obj, attr_name, val)
                    logger.debug(f"Successfully set {attr_name} to {val}")
                except ValueError as e:
                    logger.error(f"Invalid input for {attr_name}: {e}")
                    messagebox.showerror("Invalid Input", 
                                       f"Please enter a valid {current_type.__name__} for {attr_name}.")
            return setter

        def hide_children(input_frame):
            for child in input_frame.winfo_children():
                child.grid_forget()

        def on_radio_button_change(*args):
            # keyword:grid_alignment
            preprocess_config = self.image_processor.preprocess_config
            hide_children(bg_frame) # Background Correction
            match self.bg_correction_type.get():
                case 'tophat':
                    self.bg_tophat_frame.grid(sticky='we')
                case 'gaussian':
                    self.bg_gaussian_frame.grid(sticky='ew')
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(nr_frame) # Noise Reduction
            match self.noise_reduction_type.get():
                case 'gaussian':
                    self.nr_gaussian_frame.grid(sticky='ew')
                case 'median':
                    self.nr_median_frame.grid(sticky='ew')
                case 'bilateral':
                    self.nr_bilateral_frame.grid(sticky='ew')
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(ce_frame) # Contrast Enhancement
            match self.contrast_enhance_type.get():
                case 'stretch':
                    self.ce_stretch_frame.grid(sticky='ew')
                case 'clahe':
                    self.ce_clahe_frame.grid(sticky='ew')
                case 'gamma':
                    self.ce_gamma_frame.grid(sticky='ew')
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(se_frame) # Signal Enhancement
            match self.signal_enhance_type.get():
                case 'unsharp mask':
                    self.se_unsharp_frame.grid(sticky='ew') 
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)
            hide_children(tm_frame) # Thresholding Method
            match self.threshold_type.get():
                case 'otsu':
                    self.tm_otsu_frame.grid(sticky='ew') 
                case 'adaptive':
                    self.tm_adaptive_frame.grid(sticky='ew') 
                case 'local':
                    self.tm_local_frame.grid(sticky='ew') 
                case 'manual':
                    self.tm_manual_frame.grid(sticky='ew') 
                case 'none':
                    pass
                case _:
                    print('somethings broken', file=sys.stderr)

        # Control buttons at the top
        control_frame = ttk.Frame(window)
        control_frame.grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        ttk.Button(control_frame, text="Save", command=save_settings).grid(row=0, column=0, padx=5)
        ttk.Button(control_frame, text="Load", command=load_settings).grid(row=0, column=1, padx=5)
        ttk.Button(control_frame, text="Show Mask", command=self.show_cell_mask_threshold).grid(row=0, column=2, padx=5)
        tip_lbl = ttk.Label(
            control_frame,
            text="Hover for help. Mixed BG: Blob/DoG + Adaptive + dual-pass. High-BG noise: "
            "local SNR + Blob Bg Relative + isotropy/circularity (edge reject). "
            "Missed dark clusters: ease SNR, raise packing, lower free space. Area Tune sizes. "
            "Then Show Mask.",
            font=("Helvetica", 8),
            foreground="#333333",
            wraplength=520,
            justify=tk.LEFT,
        )
        tip_lbl.grid(row=0, column=3, columnspan=3, sticky="w", padx=8)

        # Autotune panel (second row in control_frame)
        ttk.Label(control_frame, text="Autotune:").grid(row=1, column=0, padx=(5, 8), pady=(6, 2), sticky='w')
        auto_btns = ttk.Frame(control_frame)
        auto_btns.grid(row=1, column=1, columnspan=3, pady=(6, 2), sticky='w')

        ttk.Button(auto_btns, text="More cells", width=12, command=autotune_more_cells).grid(row=0, column=0, padx=2, pady=1)
        ttk.Button(auto_btns, text="Less cells", width=12, command=autotune_less_cells).grid(row=0, column=1, padx=2, pady=1)
        ttk.Button(auto_btns, text="Bigger cells", width=12, command=autotune_bigger_cells).grid(row=0, column=2, padx=2, pady=1)
        ttk.Button(auto_btns, text="Smaller cells", width=12, command=autotune_smaller_cells).grid(row=1, column=0, padx=2, pady=1)
        ttk.Button(auto_btns, text="Brighter cells", width=12, command=autotune_brighter_cells).grid(row=1, column=1, padx=2, pady=1)
        ttk.Button(auto_btns, text="Dimmer cells", width=12, command=autotune_dimmer_cells).grid(row=1, column=2, padx=2, pady=1)

        # Smart Suggest + Measure Tune (informed blob tuning from user-picked samples)
        suggest_frame = ttk.Frame(control_frame)
        suggest_frame.grid(row=1, column=4, padx=(15, 5), pady=(6, 2), sticky='w')
        ttk.Button(
            suggest_frame,
            text="Smart Suggest (Pre-tuning smart settings)",
            command=self._show_smart_suggest_dialog,
        ).pack(anchor='w')
        ttk.Button(
            suggest_frame,
            text="Measure Tune (TP/FP/FN/TN)",
            command=lambda: self.start_measure_tune(mask_settings_window=window),
        ).pack(anchor='w', pady=(4, 0))
        ttk.Button(
            suggest_frame,
            text="Area Tune",
            command=lambda: self.start_area_tune(mask_settings_window=window),
        ).pack(anchor='w', pady=(4, 0))

        # Presets row
        ttk.Label(control_frame, text="Presets:").grid(row=2, column=0, padx=(5, 8), pady=(8, 2), sticky='w')
        preset_frame = ttk.Frame(control_frame)
        preset_frame.grid(row=2, column=1, columnspan=3, pady=(8, 2), sticky='w')

        self.preset_combo = ttk.Combobox(preset_frame, width=25, state="readonly")
        self.preset_combo.grid(row=0, column=0, padx=2)

        def refresh_preset_list():
            presets = self.load_presets()
            self.preset_combo['values'] = list(presets.keys())
            if presets:
                self.preset_combo.set(list(presets.keys())[0])

        def do_load_preset():
            name = self.preset_combo.get()
            if name and self.load_preset(name):
                window.destroy()
                self.show_mask_settings()

        def do_save_preset():
            self.save_current_as_preset()
            refresh_preset_list()

        def do_delete_preset():
            name = self.preset_combo.get()
            if name:
                self.delete_preset(name)
                refresh_preset_list()

        ttk.Button(preset_frame, text="Load", width=8, command=do_load_preset).grid(row=0, column=1, padx=2)
        ttk.Button(preset_frame, text="Save As", width=8, command=do_save_preset).grid(row=0, column=2, padx=2)
        ttk.Button(preset_frame, text="Delete", width=8, command=do_delete_preset).grid(row=0, column=3, padx=2)

        refresh_preset_list()

        # Export / Import config files (portable settings)
        export_import_frame = ttk.Frame(control_frame)
        export_import_frame.grid(row=3, column=0, columnspan=4, pady=(6, 2), sticky='w')

        ttk.Label(export_import_frame, text="Config Files:").grid(row=0, column=0, padx=(5, 8))
        ttk.Button(export_import_frame, text="Export...", width=10,
                   command=self.export_detection_settings).grid(row=0, column=1, padx=2)
        ttk.Button(export_import_frame, text="Import...", width=10,
                   command=lambda: [self.import_detection_settings(), window.destroy()]).grid(row=0, column=2, padx=2)

        # Create frame for radiobuttons and their options
        radio_frame = ttk.Frame(window)
        radio_frame.grid(row=1, column=0, sticky='nwes', padx=5, pady=5)
        # Create frame for rightmost options
        option_frame = ttk.Frame(window)
        option_frame.grid(row=1, column=1, sticky='nwes', padx=5, pady=5)

        # Create options frames aligned with radiobuttons, keyword:grid_alignment
        bg_frame = ttk.Frame(radio_frame)
        bg_frame.grid(row=0, column=1, sticky='news', padx=5, pady=0)
        nr_frame = ttk.Frame(radio_frame)
        nr_frame.grid(row=1, column=1, sticky='news', padx=5, pady=0)
        ce_frame = ttk.Frame(radio_frame)
        ce_frame.grid(row=2, column=1, sticky='news', padx=5, pady=0)
        se_frame = ttk.Frame(radio_frame)
        se_frame.grid(row=3, column=1, sticky='news', padx=5, pady=0)
        tm_frame = ttk.Frame(radio_frame)
        tm_frame.grid(row=4, column=1, sticky='news', padx=5, pady=0)

        # Initialize settings frames
        generate_option_frames()

        # Create radio buttons
            # Create variables
        self.bg_correction_type = tk.StringVar()
        self.noise_reduction_type = tk.StringVar()
        self.contrast_enhance_type = tk.StringVar()
        self.signal_enhance_type = tk.StringVar()
        self.threshold_type = tk.StringVar()

        # Background Correction
        bg_correction_frame = ttk.LabelFrame(radio_frame, text='Background Correction')
        bg_correction_frame.grid(row=0, column=0, sticky='new')
        bg_correction_types = {'Tophat'     : 0, 
                               'Gaussian'   : 1,
                               'None'       : 2
                               }
        self.bg_correction_type.set(self.image_processor.preprocess_config.background_method) # Sets default
        self.bg_correction_type.trace_add('write', on_radio_button_change)
        bg_setter = create_setter(self.bg_correction_type, self.image_processor.preprocess_config, 'background_method')
        self.bg_correction_type.trace_add('write', bg_setter)
        for (text, row) in bg_correction_types.items():
            button = tk.Radiobutton(bg_correction_frame, 
                                    text=text, 
                                    variable=self.bg_correction_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Noise Reduction
        noise_reduction_frame = ttk.LabelFrame(radio_frame, text='Noise Reduction')
        noise_reduction_frame.grid(row=1, column=0, sticky='news')
        noise_reduction_types = {'Gaussian' : 0, 
                                 'Median'   : 1,
                                 'Bilateral': 2,
                                 'None'     : 3
                                }
        self.noise_reduction_type.set(self.image_processor.preprocess_config.denoise_method) # Sets default
        self.noise_reduction_type.trace_add('write', on_radio_button_change)
        nr_setter = create_setter(self.noise_reduction_type, self.image_processor.preprocess_config, 'denoise_method')
        self.noise_reduction_type.trace_add('write', nr_setter)
        for (text, row) in noise_reduction_types.items():
            button = tk.Radiobutton(noise_reduction_frame, 
                                    text=text, 
                                    variable=self.noise_reduction_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Contrast Enhancement 
        contrast_enhance_frame = ttk.LabelFrame(radio_frame, text='Contrast Enhancement')
        contrast_enhance_frame.grid(row=2, column=0, sticky='news')
        contrast_enhance_types = {'Stretch' : 0, 
                                  'Clahe'   : 1,
                                  'Gamma'   : 2,
                                  'None'    : 3
                                }
        self.contrast_enhance_type.set(self.image_processor.preprocess_config.contrast_method) # Sets default
        self.contrast_enhance_type.trace_add('write', on_radio_button_change)
        ce_setter = create_setter(self.contrast_enhance_type, self.image_processor.preprocess_config, 'contrast_method')
        self.contrast_enhance_type.trace_add('write', ce_setter)
        for (text, row) in contrast_enhance_types.items():
            button = tk.Radiobutton(contrast_enhance_frame, 
                                    text=text, 
                                    variable=self.contrast_enhance_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Signal Enhancement 
        signal_enhance_frame = ttk.LabelFrame(radio_frame, text='Signal Enhancement')
        signal_enhance_frame.grid(row=3, column=0, sticky='news')
        signal_enhance_types = {'Unsharp Mask' : 0, 
                                'None'         : 1
                                }
        self.signal_enhance_type.set(self.image_processor.preprocess_config.enhance_method) # Sets default
        self.signal_enhance_type.trace_add('write', on_radio_button_change)
        se_setter = create_setter(self.signal_enhance_type, self.image_processor.preprocess_config, 'enhance_method')
        self.signal_enhance_type.trace_add('write', se_setter)
        for (text, row) in signal_enhance_types.items():
            button = tk.Radiobutton(signal_enhance_frame, 
                                    text=text, 
                                    variable=self.signal_enhance_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        # Threshold
        threshold_frame = ttk.LabelFrame(radio_frame, text='Threshold Method')
        threshold_frame.grid(row=4, column=0, sticky='news')
        threshold_types = {'Otsu'     : 0, 
                           'Adaptive'   : 1,
                           'Local'       : 2,
                           'Manual'       : 3
                           }
        self.threshold_type.set(self.image_processor.cell_config.threshold_method) # Sets default
        self.threshold_type.trace_add('write', on_radio_button_change)
        tm_setter = create_setter(self.threshold_type, self.image_processor.cell_config, 'threshold_method')
        self.threshold_type.trace_add('write', tm_setter)
        for (text, row) in threshold_types.items():
            button = tk.Radiobutton(threshold_frame, 
                                    text=text, 
                                    variable=self.threshold_type, 
                                    value=text.lower()
                                    )
            button.grid(row=row, column=0, sticky='w', padx=0, pady=0)

        on_radio_button_change() # To show initial settings


        # Close button
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=1, sticky=tk.SE, padx=5, pady=5)


    def start_add_cells(self):
        """Begin drawing to add cells to the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.splitting_cells = False
        self.show_brush_settings()
        self.start_mask_edit(add=True)

    def start_remove_cells(self):
        """Begin drawing to remove cells from the mask"""
        if self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return
        self.splitting_cells = False
        self.show_brush_settings()
        self.start_mask_edit(add=False)

    def start_split_cell(self):
        """Enable Split Cell mode: click a merged mask blob to split it into two cells.

        Uses distance-transform peaks (and intensity fallbacks) to place two markers,
        then watershed to find the most probable separation, and records the cut in
        the manual remove mask so Count Cells treats them as two objects.
        """
        if self.original_background is None and self.background_image is None:
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        # Ensure we have a current cell mask displayed
        try:
            self.show_cell_mask_threshold(calculate=True)
        except Exception as e:
            logger.error(f"Could not prepare mask for Split Cell: {e}")
            messagebox.showerror("Split Cell", f"Could not build the cell mask:\n{e}")
            return

        self.splitting_cells = True
        self.editing_mask = True
        self.mask_edit_add = False
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None

        base_size = self.original_background.size
        if self.manual_remove_mask is None:
            self.manual_remove_mask = Image.new('L', base_size, 0)
        # Keep remove mask size in sync with the image
        if self.manual_remove_mask.size != base_size:
            self.manual_remove_mask = self.manual_remove_mask.resize(base_size, Image.NEAREST)
        self.current_mask = self.manual_remove_mask

        # Click-only interaction (no brush drag)
        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.unbind("<Button-2>")
        self.output.unbind("<B2-Motion>")
        self.output.unbind("<ButtonRelease-2>")
        self.output.unbind("<Button-3>")
        self.output.unbind("<B3-Motion>")
        self.output.unbind("<ButtonRelease-3>")
        self.output.bind("<Button-1>", self.split_cell_at_click)

        logger.info("Started Split Cell mode")
        messagebox.showinfo(
            "Split Cell",
            "Click on a single masked cell (red blob) that should be two cells.\n\n"
            "BARCC will split it into the two most probable cell blobs.\n"
            "Use Finish Mask Edit when done, then Count Cells.",
        )

    def start_mask_edit(self, add=True):
        """Enable mask editing mode while keeping the cell detection overlay visible."""
        self.editing_mask = True
        self.splitting_cells = False
        self.mask_edit_add = add
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.output.unbind("<Button-1>")
        self.output.bind("<Button-1>", self.edit_mask_draw)
        self.output.bind("<B1-Motion>", self.edit_mask_draw)
        # On release: refresh combined mask rings (still keep edit mode)
        self.output.bind(
            "<ButtonRelease-1>",
            lambda event: self._finish_mask_edit_stroke(event),
        )
        # Right click erases paint from the active layer
        self.output.bind("<Button-2>", lambda event: self.edit_mask_draw(event, eraser=True))
        self.output.bind("<B2-Motion>", lambda event: self.edit_mask_draw(event, eraser=True))
        self.output.bind(
            "<ButtonRelease-2>",
            lambda event: self._finish_mask_edit_stroke(event),
        )
        self.output.bind("<Button-3>", lambda event: self.edit_mask_draw(event, eraser=True))
        self.output.bind("<B3-Motion>", lambda event: self.edit_mask_draw(event, eraser=True))
        self.output.bind(
            "<ButtonRelease-3>",
            lambda event: self._finish_mask_edit_stroke(event),
        )

        # Initialize the correct mask depending on edit mode
        base_size = self.original_background.size

        if add:
            if self.manual_add_mask is None:
                self.manual_add_mask = Image.new('L', base_size, 0)
            if self.manual_add_mask.size != base_size:
                self.manual_add_mask = self.manual_add_mask.resize(base_size, Image.NEAREST)
            self.current_mask = self.manual_add_mask
        else:
            if self.manual_remove_mask is None:
                self.manual_remove_mask = Image.new('L', base_size, 0)
            if self.manual_remove_mask.size != base_size:
                self.manual_remove_mask = self.manual_remove_mask.resize(base_size, Image.NEAREST)
            self.current_mask = self.manual_remove_mask

        # Ensure detection mask exists and show rings + paint (do not leave blank TIFF)
        try:
            has_auto = (
                getattr(self, "auto_mask", None) is not None
                and not isinstance(getattr(self, "auto_mask", None), bool)
            )
            if not has_auto:
                self.show_cell_mask_threshold(calculate=True)
            # Re-enter edit bindings after show_cell_mask (does not rebind)
            self.editing_mask = True
            self.mask_edit_add = add
            self.current_mask = self.manual_add_mask if add else self.manual_remove_mask
            self._refresh_mask_edit_display()
        except Exception as e:
            logger.warning(f"Could not show mask for edit mode: {e}")
            self._refresh_mask_edit_display()

        logger.info(f"Started mask edit mode: {'add' if add else 'remove'} cells")

    def _build_live_mask_edit_overlay(self):
        """Composite cell-detection rings + add/remove paint so the mask stays visible.

        While removing, base rings still show auto|add cells (so the detection mask
        does not vanish under the brush); yellow marks the remove strokes.
        While adding, base rings show (auto|add)&~remove; red marks add strokes.
        """
        if self.original_background is None:
            return None
        target_size = self.original_background.size  # (w, h)
        w, h = int(target_size[0]), int(target_size[1])

        # --- Base detection rings ---
        auto = getattr(self, "auto_mask", None)
        if auto is None or isinstance(auto, bool):
            base = Image.new("RGBA", target_size, (0, 0, 0, 0))
        else:
            auto_b = np.asarray(auto, dtype=bool).squeeze()
            if auto_b.shape[0] != h or auto_b.shape[1] != w:
                auto_b = np.array(
                    Image.fromarray((auto_b.astype(np.uint8) * 255)).resize(
                        (w, h), Image.NEAREST
                    )
                ) > 0
            preview = auto_b.copy()
            # Always include existing manual adds in the ring preview
            if self.manual_add_mask is not None:
                try:
                    add_arr = np.array(
                        self.manual_add_mask.resize((w, h), Image.NEAREST)
                    )
                    if add_arr.ndim > 2:
                        add_arr = add_arr.squeeze()
                    preview = preview | (add_arr > 0)
                except Exception:
                    pass
            # Only subtract remove when NOT actively painting remove
            # (so cells don't disappear under the yellow brush mid-stroke).
            # When adding, subtract remove so rings match final combined mask.
            if getattr(self, "mask_edit_add", True) and self.manual_remove_mask is not None:
                try:
                    rem_arr = np.array(
                        self.manual_remove_mask.resize((w, h), Image.NEAREST)
                    )
                    if rem_arr.ndim > 2:
                        rem_arr = rem_arr.squeeze()
                    preview = preview & ~(rem_arr > 0)
                except Exception:
                    pass
            base = self._cell_detection_ring_overlay(
                preview,
                size=target_size,
                color=(255, 0, 0),
                alpha=230,
                thickness=2,
            ).convert("RGBA")

        # --- Paint strokes for the layer being edited ---
        paint = np.zeros((h, w, 4), dtype=np.uint8)
        if getattr(self, "mask_edit_add", True):
            if self.manual_add_mask is not None:
                arr = np.array(self.manual_add_mask.resize((w, h), Image.NEAREST))
                if arr.ndim > 2:
                    arr = arr.squeeze()
                # Semi-transparent red fill for brush strokes
                paint[arr > 0] = [255, 40, 40, 150]
        else:
            if self.manual_remove_mask is not None:
                arr = np.array(self.manual_remove_mask.resize((w, h), Image.NEAREST))
                if arr.ndim > 2:
                    arr = arr.squeeze()
                # Yellow/gold remove strokes
                paint[arr > 0] = [255, 210, 0, 180]
        paint_img = Image.fromarray(paint, "RGBA")
        return Image.alpha_composite(base, paint_img)

    def _refresh_mask_edit_display(self):
        """Redraw TIFF + detection rings + current add/remove paint."""
        try:
            overlay = self._build_live_mask_edit_overlay()
            if overlay is not None:
                self.show_page(mask=overlay)
                # Keep flag so zoom/pan paths know a mask view is active
                self.showing_auto_mask = True
        except Exception as e:
            logger.warning(f"Mask edit display refresh failed: {e}")

    def _finish_mask_edit_stroke(self, event=None):
        """After a brush stroke, refresh combined rings without leaving edit mode."""
        if not getattr(self, "editing_mask", False):
            return
        # Prefer full combined view (applies remove to rings) after stroke ends
        try:
            # Rebuild combined detection rings + paint (for remove, now subtract)
            was_add = getattr(self, "mask_edit_add", True)
            if not was_add:
                # Temporarily show true combined for accuracy after stroke
                self.show_cell_mask_threshold(calculate=False)
                self.editing_mask = True
                self.mask_edit_add = False
                self.current_mask = self.manual_remove_mask
                # Layer yellow paint back on top of final combined rings
                self._refresh_mask_edit_display()
            else:
                self.show_cell_mask_threshold(calculate=False)
                self.editing_mask = True
                self.mask_edit_add = True
                self.current_mask = self.manual_add_mask
                self._refresh_mask_edit_display()
        except Exception:
            self._refresh_mask_edit_display()

    def edit_mask_draw(self, event, eraser=False):
        """Draw directly on the binary mask. Coordinates respect current zoom level."""
        if not self.editing_mask or self.current_mask is None:
            return
        if getattr(self, 'splitting_cells', False):
            return

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        x, y = self._canvas_to_image(cx, cy)   # convert to native image space
        r = int(self.brush_size.get())

        draw = ImageDraw.Draw(self.current_mask)
        if eraser == False:
            color = 255
        else:
            color = 0
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

        # Keep detection mask visible under the paint strokes
        self._refresh_mask_edit_display()

    def _get_combined_cell_mask(self):
        """Return the current boolean cell mask (auto | add) & ~remove, or None."""
        if self.original_background is None:
            return None
        background = self.original_background.convert('L')
        base_size = background.size
        h, w = np.array(background).shape[:2]

        auto_mask = getattr(self, 'auto_mask', None)
        if auto_mask is None or isinstance(auto_mask, bool):
            _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
            auto_mask = np.asarray(auto_labels, dtype=bool).squeeze()
            self.auto_mask = auto_mask
        else:
            auto_mask = np.asarray(auto_mask, dtype=bool).squeeze()

        if auto_mask.shape[0] != h or auto_mask.shape[1] != w:
            auto_mask = np.array(
                Image.fromarray(auto_mask.astype(np.uint8) * 255).resize((w, h), Image.NEAREST)
            ) > 0
            self.auto_mask = auto_mask

        add_mask = np.zeros(auto_mask.shape, dtype=bool)
        remove_mask = np.zeros(auto_mask.shape, dtype=bool)
        if self.manual_add_mask is not None:
            add_arr = np.array(self.manual_add_mask.resize((w, h), Image.NEAREST))
            if add_arr.ndim > 2:
                add_arr = add_arr.squeeze()
            add_mask = add_arr > 0
        if self.manual_remove_mask is not None:
            rem_arr = np.array(self.manual_remove_mask.resize((w, h), Image.NEAREST))
            if rem_arr.ndim > 2:
                rem_arr = rem_arr.squeeze()
            remove_mask = rem_arr > 0

        return (auto_mask | add_mask) & ~remove_mask

    def _bool_mask_to_l_image(self, mask_bool):
        """Boolean ndarray → PIL L image (0/255)."""
        m = np.asarray(mask_bool, dtype=bool).squeeze()
        return Image.fromarray((m.astype(np.uint8) * 255), mode="L")

    def _l_image_to_bool_mask(self, img, target_hw=None):
        """PIL/L path image → boolean mask; optional resize to (h, w)."""
        if not isinstance(img, Image.Image):
            img = Image.fromarray(np.asarray(img))
        if img.mode != "L":
            img = img.convert("L")
        if target_hw is not None:
            th, tw = int(target_hw[0]), int(target_hw[1])
            if img.size != (tw, th):
                img = img.resize((tw, th), Image.NEAREST)
        return np.array(img) > 0

    def _ensure_cell_mask_for_save(self):
        """Build combined cell mask for export without forcing a full redetect if one exists.

        Returns (combined_bool, auto_bool, add_pil_or_None, remove_pil_or_None, size_wh)
        or (None, ...) if no image.
        """
        if self.original_background is None and self.background_image is None:
            return None, None, None, None, None
        bg = self.original_background or self.background_image
        w, h = bg.size

        combined = None
        if getattr(self, "last_cell_mask", None) is not None:
            try:
                combined = np.asarray(self.last_cell_mask, dtype=bool).squeeze()
                if combined.ndim == 2 and (
                    combined.shape[0] != h or combined.shape[1] != w
                ):
                    combined = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(combined), (h, w)
                    )
            except Exception:
                combined = None

        if combined is None:
            combined = self._get_combined_cell_mask()
        if combined is None:
            return None, None, None, None, None

        combined = np.asarray(combined, dtype=bool).squeeze()
        if combined.shape[0] != h or combined.shape[1] != w:
            combined = self._l_image_to_bool_mask(
                self._bool_mask_to_l_image(combined), (h, w)
            )

        auto = getattr(self, "auto_mask", None)
        if auto is not None and not isinstance(auto, bool):
            auto = np.asarray(auto, dtype=bool).squeeze()
            if auto.shape[0] != h or auto.shape[1] != w:
                auto = self._l_image_to_bool_mask(
                    self._bool_mask_to_l_image(auto), (h, w)
                )
        else:
            # Bake combined into auto for a clean portable mask
            auto = combined.copy()

        add_pil = None
        rem_pil = None
        if self.manual_add_mask is not None:
            try:
                add_pil = self.manual_add_mask.convert("L")
                if add_pil.size != (w, h):
                    add_pil = add_pil.resize((w, h), Image.NEAREST)
            except Exception:
                add_pil = None
        if self.manual_remove_mask is not None:
            try:
                rem_pil = self.manual_remove_mask.convert("L")
                if rem_pil.size != (w, h):
                    rem_pil = rem_pil.resize((w, h), Image.NEAREST)
            except Exception:
                rem_pil = None

        return combined, auto, add_pil, rem_pil, (w, h)

    def save_cell_mask(self):
        """Save the current cell detection mask for reuse on another channel.

        Writes a portable ``.barccmask`` package (combined + optional layers) and a
        plain ``_cellmask.png`` under ``output/cell_masks/``. Load on another channel
        of the same section size to skip re-detection for Count Cells.
        """
        try:
            combined, auto, add_pil, rem_pil, size_wh = self._ensure_cell_mask_for_save()
            if combined is None:
                messagebox.showwarning(
                    "Save Cell Mask",
                    "No cell mask is available.\n\n"
                    "Run Cell → Show Mask (or detect cells) on this channel first.",
                )
                return
            if not np.any(combined):
                if not messagebox.askyesno(
                    "Empty Mask",
                    "The current cell mask has no detected cells.\n\n"
                    "Save anyway?",
                ):
                    return

            base_name = self.tiff_filename
            tiff_dir = self.tiff_dir or self.current_tiff_directory
            if not base_name and getattr(self, "current_tiff_path", None):
                base_name = os.path.splitext(os.path.basename(self.current_tiff_path))[0]
                if not tiff_dir:
                    tiff_dir = os.path.dirname(self.current_tiff_path)
            if not base_name:
                base_name = "cells"

            out_dir = self._get_output_directory(tiff_dir, feature="cell_masks") if tiff_dir else None
            initial_dir = out_dir or tiff_dir
            # Prefer a channel-neutral name so the same file is natural across ch0/ch1
            stem = base_name
            for suffix in (
                "_ch0", "_ch1", "_ch2", "_ch3", "_c0", "_c1", "_c2", "_c3",
                "-ch0", "-ch1", "-ch2", "-ch3",
            ):
                if stem.lower().endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            default_name = f"{stem}_cellmask.barccmask"

            save_path = fd.asksaveasfilename(
                title="Save Cell Mask",
                defaultextension=".barccmask",
                filetypes=[
                    ("BARCC Cell Mask", "*.barccmask"),
                    ("PNG mask", "*.png"),
                    ("All files", "*.*"),
                ],
                initialdir=initial_dir,
                initialfile=default_name,
            )
            if not save_path:
                return

            w, h = size_wh
            combined_img = self._bool_mask_to_l_image(combined)
            auto_img = self._bool_mask_to_l_image(auto)

            saved = []
            low = save_path.lower()
            if low.endswith(".png"):
                combined_img.save(save_path)
                saved.append(save_path)
            else:
                if not low.endswith(".barccmask"):
                    save_path = save_path + ".barccmask"
                manifest = {
                    "format_version": 1,
                    "type": "barcc_cellmask",
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "source_tiff_name": self.tiff_filename,
                    "source_tiff_path": getattr(self, "current_tiff_path", None),
                    "mask_size": [int(w), int(h)],
                    "pixel_value": "255=cell, 0=background",
                    "description": (
                        "Portable cell detection mask. Load on another channel of the "
                        "same section to reuse detections for Count Cells."
                    ),
                    "locked_on_load": True,
                }
                with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2))
                    bio = BytesIO()
                    combined_img.save(bio, format="PNG")
                    zf.writestr("combined.png", bio.getvalue())
                    bio = BytesIO()
                    auto_img.save(bio, format="PNG")
                    zf.writestr("auto.png", bio.getvalue())
                    if add_pil is not None:
                        bio = BytesIO()
                        add_pil.save(bio, format="PNG")
                        zf.writestr("manual_add.png", bio.getvalue())
                    if rem_pil is not None:
                        bio = BytesIO()
                        rem_pil.save(bio, format="PNG")
                        zf.writestr("manual_remove.png", bio.getvalue())
                saved.append(save_path)

                # Also write a plain PNG next to it for easy inspection / legacy load
                try:
                    png_side = os.path.splitext(save_path)[0] + ".png"
                    combined_img.save(png_side)
                    saved.append(png_side)
                except Exception as e:
                    logger.debug(f"Side PNG cell mask save skipped: {e}")

            # Keep session mask in sync
            self.auto_mask = auto
            self.last_cell_mask = combined
            self.cell_mask_locked = True
            self.cell_mask_source_path = save_path

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            messagebox.showinfo(
                "Cell Mask Saved",
                "Cell mask saved for cross-channel use:\n\n"
                + "\n".join(saved)
                + "\n\nOn another channel: File → Next Channel… (keep atlas),\n"
                "then Cell → Load Cell Mask… and Count Cells\n"
                "(detection will not re-run while the loaded mask is locked).\n"
                "Cell → Show Mask re-detects and unlocks if you need a new mask.",
            )
            logger.info(f"Cell mask saved: {saved}")
        except Exception as e:
            logger.error(f"save_cell_mask failed: {e}", exc_info=True)
            messagebox.showerror("Save Cell Mask", f"Failed to save cell mask:\n{e}")

    def load_cell_mask(self):
        """Load a previously saved cell mask onto the current channel.

        Applies the mask to auto_mask / last_cell_mask (resized if needed) so
        Count Cells uses it without re-running detection.
        """
        try:
            if self.original_background is None and self.background_image is None:
                messagebox.showwarning(
                    "Load Cell Mask",
                    "Load a TIFF image first, then load the cell mask.",
                )
                return

            initial_dir = self._preferred_open_dir(feature="cell_masks")

            path = fd.askopenfilename(
                title="Load Cell Mask",
                initialdir=initial_dir,
                filetypes=[
                    ("BARCC Cell Mask", "*.barccmask"),
                    ("PNG / TIFF mask", "*.png *.tif *.tiff"),
                    ("All files", "*.*"),
                ],
            )
            if not path:
                return

            bg = self.original_background or self.background_image
            tw, th = bg.size  # PIL width, height
            target_hw = (th, tw)

            combined = None
            auto = None
            add_img = None
            rem_img = None
            src_size = None

            low = path.lower()
            if low.endswith(".barccmask"):
                with zipfile.ZipFile(path, "r") as zf:
                    names = set(zf.namelist())
                    if "manifest.json" in names:
                        try:
                            manifest = json.loads(
                                zf.read("manifest.json").decode("utf-8")
                            )
                            sz = manifest.get("mask_size")
                            if sz and len(sz) == 2:
                                src_size = (int(sz[0]), int(sz[1]))
                        except Exception:
                            pass

                    def _read_member(member):
                        if member not in names:
                            return None
                        im = Image.open(BytesIO(zf.read(member)))
                        im.load()
                        return im.convert("L")

                    comb_im = _read_member("combined.png")
                    auto_im = _read_member("auto.png")
                    add_img = _read_member("manual_add.png")
                    rem_img = _read_member("manual_remove.png")
                    if comb_im is None and auto_im is None:
                        raise ValueError(
                            "Invalid .barccmask: missing combined.png / auto.png"
                        )
                    if comb_im is not None:
                        combined = self._l_image_to_bool_mask(comb_im, target_hw)
                    if auto_im is not None:
                        auto = self._l_image_to_bool_mask(auto_im, target_hw)
                    if add_img is not None and add_img.size != (tw, th):
                        add_img = add_img.resize((tw, th), Image.NEAREST)
                    if rem_img is not None and rem_img.size != (tw, th):
                        rem_img = rem_img.resize((tw, th), Image.NEAREST)
            else:
                im = Image.open(path)
                im.load()
                # If RGB overlay (e.g. _masked.tif with red rings), use non-black / high red
                if im.mode in ("RGB", "RGBA"):
                    arr = np.array(im.convert("RGBA"))
                    # Prefer alpha or bright red-ish pixels; fallback: any non-near-black
                    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
                    mask_bool = (r > 40) & (r >= g) & (r >= b) & (a > 10)
                    if not mask_bool.any():
                        gray = np.array(im.convert("L"))
                        mask_bool = gray > 0
                    combined = mask_bool
                    if combined.shape[0] != th or combined.shape[1] != tw:
                        combined = self._l_image_to_bool_mask(
                            self._bool_mask_to_l_image(combined), target_hw
                        )
                else:
                    combined = self._l_image_to_bool_mask(im.convert("L"), target_hw)
                auto = combined.copy()

            if combined is None and auto is not None:
                combined = auto.copy()
            if auto is None and combined is not None:
                auto = combined.copy()
            if combined is None:
                raise ValueError("Could not read a usable cell mask from the file.")

            # If package had separate layers but no combined, rebuild
            if add_img is not None or rem_img is not None:
                add_b = (
                    np.array(add_img) > 0
                    if add_img is not None
                    else np.zeros_like(auto, dtype=bool)
                )
                rem_b = (
                    np.array(rem_img) > 0
                    if rem_img is not None
                    else np.zeros_like(auto, dtype=bool)
                )
                if add_b.shape != auto.shape:
                    add_b = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(add_b), target_hw
                    )
                if rem_b.shape != auto.shape:
                    rem_b = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(rem_b), target_hw
                    )
                combined = (auto | add_b) & ~rem_b
                self.manual_add_mask = (
                    add_img if add_img is not None else Image.new("L", (tw, th), 0)
                )
                self.manual_remove_mask = (
                    rem_img if rem_img is not None else Image.new("L", (tw, th), 0)
                )
            else:
                # Baked combined only — clear manual layers so count matches file
                self.manual_add_mask = None
                self.manual_remove_mask = None

            self.auto_mask = auto
            self.last_cell_mask = combined
            self.cell_mask_locked = True
            self.cell_mask_source_path = path

            n_pix = int(np.sum(combined))
            size_note = ""
            if src_size and list(src_size) != [tw, th]:
                size_note = (
                    f"\nResized from {src_size[0]}×{src_size[1]} → {tw}×{th} (nearest)."
                )

            # Show overlay without re-detecting
            self.show_cell_mask_threshold(calculate=False)

            messagebox.showinfo(
                "Cell Mask Loaded",
                f"Loaded cell mask from:\n{path}\n\n"
                f"Cell pixels: {n_pix}\n"
                f"Size: {tw}×{th}{size_note}\n\n"
                "Mask is locked for Count Cells (no re-detection).\n"
                "Use Cell → Show Mask to re-detect and unlock if needed.",
            )
            logger.info(
                f"Cell mask loaded from {path}: pixels={n_pix} size={tw}x{th} locked=True"
            )
        except Exception as e:
            logger.error(f"load_cell_mask failed: {e}", exc_info=True)
            messagebox.showerror("Load Cell Mask", f"Failed to load cell mask:\n{e}")

    def _get_ground_truth_cell_mask(self):
        """Ground-truth cell mask for null distributions (loaded or detected)."""
        if getattr(self, "last_cell_mask", None) is not None:
            m = np.asarray(self.last_cell_mask, dtype=bool).squeeze()
            if m.ndim == 2 and m.any():
                return m
        return self._get_combined_cell_mask()

    def _extract_cell_instances(self, gt_bool):
        """Label ground-truth blobs → matched-pair records with exact footprints.

        Each cell includes pixel offsets relative to an integer centroid so a
        random placement can stamp an identical shape (same area/pixel count).
        """
        gt = np.asarray(gt_bool, dtype=bool).squeeze()
        if gt.ndim != 2 or not gt.any():
            return []
        labels = measure.label(gt, connectivity=2)
        props = measure.regionprops(labels)
        cells = []
        for p in props:
            if p.area < 1:
                continue
            r, c = p.centroid
            radius = max(1.0, float(np.sqrt(p.area / np.pi)))
            cri, cci = int(round(r)), int(round(c))
            ys, xs = np.where(labels == p.label)
            # Integer offsets preserve exact area when the full footprint fits
            offs_r = (ys.astype(np.int32) - cri).astype(np.int32)
            offs_c = (xs.astype(np.int32) - cci).astype(np.int32)
            cells.append(
                {
                    "label": int(p.label),
                    "row": float(r),
                    "col": float(c),
                    "crow": cri,
                    "ccol": cci,
                    "area": int(p.area),
                    "radius": radius,
                    "offs_r": offs_r,
                    "offs_c": offs_c,
                    "min_dr": int(offs_r.min()) if offs_r.size else 0,
                    "max_dr": int(offs_r.max()) if offs_r.size else 0,
                    "min_dc": int(offs_c.min()) if offs_c.size else 0,
                    "max_dc": int(offs_c.max()) if offs_c.size else 0,
                }
            )
        return cells

    def _draw_disk_cells(self, shape_hw, placements, radii):
        """Rasterize circular cells at (row, col) with given radii → boolean mask."""
        h, w = int(shape_hw[0]), int(shape_hw[1])
        out = np.zeros((h, w), dtype=bool)
        for (r, c), rad in zip(placements, radii):
            rad = max(1.0, float(rad))
            rr = int(round(r))
            cc = int(round(c))
            r0 = max(0, int(np.floor(rr - rad - 1)))
            r1 = min(h, int(np.ceil(rr + rad + 2)))
            c0 = max(0, int(np.floor(cc - rad - 1)))
            c1 = min(w, int(np.ceil(cc + rad + 2)))
            if r1 <= r0 or c1 <= c0:
                continue
            ys = np.arange(r0, r1)[:, None]
            xs = np.arange(c0, c1)[None, :]
            disk = (ys - rr) ** 2 + (xs - cc) ** 2 <= rad ** 2
            out[r0:r1, c0:c1] |= disk
        return out

    def _stamp_cell_footprint(self, out_mask, cell, center_rc, require_full=False):
        """Stamp a cell's exact GT footprint at a new center. Returns pixels written.

        If ``require_full`` is True, only stamps when every footprint pixel fits
        in-bounds (exact area match); returns 0 otherwise.
        """
        h, w = out_mask.shape[:2]
        nr = int(round(center_rc[0]))
        nc = int(round(center_rc[1]))
        offs_r = cell["offs_r"]
        offs_c = cell["offs_c"]
        if offs_r is None or len(offs_r) == 0:
            return 0
        rs = offs_r + nr
        cs = offs_c + nc
        valid = (rs >= 0) & (rs < h) & (cs >= 0) & (cs < w)
        n_valid = int(np.sum(valid))
        if n_valid == 0:
            return 0
        if require_full and n_valid < int(cell["area"]):
            return 0
        out_mask[rs[valid], cs[valid]] = True
        return n_valid

    def _stamp_cell_footprint_labeled(
        self,
        out_labels,
        cell,
        center_rc,
        label_id,
        require_full=True,
        only_empty=True,
        placeable=None,
        min_frac_in_placeable=None,
    ):
        """Stamp footprint with a unique label id (prevents fragment over-counting).

        Returns pixels written, or 0 on failure.

        If ``placeable`` is given with ``min_frac_in_placeable`` (0–1), at least
        that fraction of in-bounds footprint pixels must lie inside ``placeable``.
        """
        h, w = out_labels.shape[:2]
        nr = int(round(center_rc[0]))
        nc = int(round(center_rc[1]))
        offs_r = cell["offs_r"]
        offs_c = cell["offs_c"]
        if offs_r is None or len(offs_r) == 0:
            return 0
        rs = offs_r.astype(np.int32) + nr
        cs = offs_c.astype(np.int32) + nc
        valid = (rs >= 0) & (rs < h) & (cs >= 0) & (cs < w)
        n_valid = int(np.sum(valid))
        if n_valid == 0:
            return 0
        if require_full and n_valid != int(cell["area"]):
            return 0
        rs_v = rs[valid]
        cs_v = cs[valid]
        if placeable is not None and min_frac_in_placeable is not None:
            in_reg = placeable[rs_v, cs_v]
            frac = float(np.sum(in_reg)) / float(n_valid)
            if frac < float(min_frac_in_placeable):
                return 0
        if only_empty:
            empty = out_labels[rs_v, cs_v] == 0
            if require_full and int(np.sum(empty)) != int(cell["area"]):
                # Would collide / partial — reject so we try another center
                return 0
            if not np.any(empty):
                return 0
            # Prefer writing only empty pixels that also stay in placeable when required
            write = empty
            if placeable is not None and min_frac_in_placeable is not None:
                write = empty & placeable[rs_v, cs_v]
                if not np.any(write):
                    return 0
                # If require_full, entire footprint must still be empty and in placeable
                if require_full and int(np.sum(write)) != int(cell["area"]):
                    return 0
            out_labels[rs_v[write], cs_v[write]] = int(label_id)
            return int(np.sum(write))
        write = np.ones(n_valid, dtype=bool)
        if placeable is not None and min_frac_in_placeable is not None:
            write = placeable[rs_v, cs_v]
            if not np.any(write):
                return 0
        out_labels[rs_v[write], cs_v[write]] = int(label_id)
        return int(np.sum(write))

    def _stamp_disk_labeled(self, out_labels, center_rc, area, label_id, placeable=None):
        """Stamp a disk of ~area pixels as last-resort matched pair (preserves counts)."""
        h, w = out_labels.shape[:2]
        nr = int(round(center_rc[0]))
        nc = int(round(center_rc[1]))
        if not (0 <= nr < h and 0 <= nc < w):
            return 0
        if placeable is not None and not placeable[nr, nc]:
            return 0
        rad = max(1.0, float(np.sqrt(max(1, int(area)) / np.pi)))
        r0 = max(0, int(np.floor(nr - rad - 1)))
        r1 = min(h, int(np.ceil(nr + rad + 2)))
        c0 = max(0, int(np.floor(nc - rad - 1)))
        c1 = min(w, int(np.ceil(nc + rad + 2)))
        if r1 <= r0 or c1 <= c0:
            return 0
        ys = np.arange(r0, r1)[:, None]
        xs = np.arange(c0, c1)[None, :]
        disk = (ys - nr) ** 2 + (xs - nc) ** 2 <= rad ** 2
        if placeable is not None:
            disk = disk & placeable[r0:r1, c0:c1]
        empty = out_labels[r0:r1, c0:c1] == 0
        write = disk & empty
        if not np.any(write):
            return 0
        patch = out_labels[r0:r1, c0:c1]
        patch[write] = int(label_id)
        out_labels[r0:r1, c0:c1] = patch
        return int(np.sum(write))

    def _sample_random_centers_in_region(self, region_bool, n, rng, min_sep=None):
        """Sample n (row, col) centers inside a boolean region (with light anti-overlap)."""
        coords = np.column_stack(np.where(region_bool))  # (N, 2) row, col
        if coords.shape[0] == 0 or n <= 0:
            return []
        if n >= coords.shape[0]:
            idx = rng.choice(coords.shape[0], size=n, replace=True)
            return [(float(coords[i, 0]), float(coords[i, 1])) for i in idx]

        chosen = []
        order = rng.permutation(coords.shape[0])
        min_sep = float(min_sep) if min_sep is not None else 0.0
        min_sep2 = min_sep * min_sep
        for i in order:
            if len(chosen) >= n:
                break
            r, c = float(coords[i, 0]), float(coords[i, 1])
            if min_sep2 > 0 and chosen:
                ok = True
                for cr, cc in chosen:
                    if (r - cr) ** 2 + (c - cc) ** 2 < min_sep2:
                        ok = False
                        break
                if not ok:
                    continue
            chosen.append((r, c))

        if len(chosen) < n:
            remaining = n - len(chosen)
            used = set((int(round(r)), int(round(c))) for r, c in chosen)
            for i in order:
                if remaining <= 0:
                    break
                r, c = int(coords[i, 0]), int(coords[i, 1])
                if (r, c) in used:
                    continue
                chosen.append((float(r), float(c)))
                used.add((r, c))
                remaining -= 1
        if len(chosen) < n:
            extra = n - len(chosen)
            idx = rng.choice(coords.shape[0], size=extra, replace=True)
            for i in idx:
                chosen.append((float(coords[i, 0]), float(coords[i, 1])))
        return chosen[:n]

    def _candidate_centers_for_cell(
        self, cell, placeable, h, w, require_full_fit=True
    ):
        """Boolean mask of centers where footprint can be placed.

        If ``require_full_fit`` is True, only centers where the full footprint is
        in-bounds. Center must always lie in ``placeable`` when given.
        """
        if require_full_fit:
            min_r = max(0, -int(cell["min_dr"]))
            max_r = min(h - 1, h - 1 - int(cell["max_dr"]))
            min_c = max(0, -int(cell["min_dc"]))
            max_c = min(w - 1, w - 1 - int(cell["max_dc"]))
            fit = np.zeros((h, w), dtype=bool)
            if max_r >= min_r and max_c >= min_c:
                fit[min_r : max_r + 1, min_c : max_c + 1] = True
        else:
            fit = np.ones((h, w), dtype=bool)
        if placeable is not None:
            return fit & placeable
        return fit

    def _sample_center_for_matched_cell(
        self,
        cell,
        placeable,
        h,
        w,
        rng,
        occupied=None,
        min_sep=None,
        max_tries=400,
        require_full_fit=True,
        allow_outside_placeable=False,
    ):
        """Pick a random center inside placeable (never escapes region unless allowed).

        ``allow_outside_placeable`` is False by default so stratified placement
        cannot fall back to whole-image (which broke per-region counts).
        """
        cand_mask = self._candidate_centers_for_cell(
            cell, placeable, h, w, require_full_fit=require_full_fit
        )
        coords = np.column_stack(np.where(cand_mask))
        if coords.shape[0] == 0 and not require_full_fit and placeable is not None:
            # Last geometric chance: any pixel in placeable
            coords = np.column_stack(np.where(placeable))
        if coords.shape[0] == 0 and allow_outside_placeable:
            # Unstratified / explicit escape only
            cand_mask = self._candidate_centers_for_cell(
                cell, None, h, w, require_full_fit=require_full_fit
            )
            coords = np.column_stack(np.where(cand_mask))
        if coords.shape[0] == 0:
            return None

        min_sep = float(min_sep) if min_sep is not None else 0.0
        min_sep2 = min_sep * min_sep
        n = coords.shape[0]
        # Sample without building huge permutations when n is large
        if n > max_tries * 4:
            picks = rng.choice(n, size=min(max_tries * 3, n), replace=False)
        else:
            picks = rng.permutation(n)

        for j, i in enumerate(picks):
            if j >= max_tries * 3:
                break
            r, c = float(coords[i, 0]), float(coords[i, 1])
            if occupied and min_sep2 > 0:
                ok = True
                for cr, cc in occupied:
                    if (r - cr) ** 2 + (c - cc) ** 2 < min_sep2:
                        ok = False
                        break
                if not ok:
                    continue
            return (r, c)
        # Fallback: ignore separation
        i = int(picks[0])
        return (float(coords[i, 0]), float(coords[i, 1]))

    def _placeable_for_zone(self, zid, zone_mask, tissue, stratified):
        """Return boolean placeable mask for a zone id.

        Named regions (zid > 0): only that zone.
        Undefined (zid == 0) with atlas: only ``zone_mask == 0`` (never OR tissue,
        which would include pixels inside named structures).
        No atlas: tissue / full image.
        """
        if stratified and zone_mask is not None and int(zid) > 0:
            return zone_mask == int(zid)
        if stratified and zone_mask is not None and int(zid) == 0:
            # Strict undefined space — outside all designated atlas regions
            undef = zone_mask == 0
            # Prefer tissue within undefined space when available
            if tissue is not None:
                prefer = undef & tissue
                if prefer.any():
                    return prefer
            return undef
        # Unstratified: tissue (or full frame if tissue empty)
        if tissue is not None and np.any(tissue):
            return tissue
        if zone_mask is not None:
            return np.ones(zone_mask.shape, dtype=bool)
        if tissue is not None:
            return np.ones(tissue.shape, dtype=bool)
        return None

    def _footprint_fully_contained(self, cell, center_rc, placeable, h, w):
        """True if every footprint pixel is in-bounds and inside placeable (if given)."""
        nr = int(round(center_rc[0]))
        nc = int(round(center_rc[1]))
        offs_r = cell.get("offs_r")
        offs_c = cell.get("offs_c")
        if offs_r is None or offs_c is None or len(offs_r) == 0:
            return False
        rs = offs_r.astype(np.int32) + nr
        cs = offs_c.astype(np.int32) + nc
        if (
            np.any(rs < 0)
            or np.any(rs >= h)
            or np.any(cs < 0)
            or np.any(cs >= w)
        ):
            return False
        if placeable is not None:
            if not np.all(placeable[rs, cs]):
                return False
        return True

    def _centers_for_exact_matched_stamp(self, cell, placeable, h, w, max_scan=25000):
        """List of centers where the full GT footprint fits in-bounds and in placeable.

        ``require_full_fit`` alone only keeps the footprint inside the *image*; this
        also requires every footprint pixel to lie in ``placeable`` (region lock).
        """
        cand = self._candidate_centers_for_cell(
            cell, placeable, h, w, require_full_fit=True
        )
        coords = np.column_stack(np.where(cand))
        if coords.shape[0] == 0:
            return coords
        # If many candidates, we still return all for sampling — but if huge, subsample
        # for prefilter only; caller samples with RNG.
        if placeable is None:
            return coords
        # Prefilter: footprint must be fully inside placeable
        # For large candidate sets, verify in random order until we collect enough
        # or scan all if manageable.
        n = coords.shape[0]
        if n > max_scan:
            # Random subset for speed; placement will still try many
            return coords  # stamp path re-checks containment
        keep = []
        area = int(cell["area"])
        offs_r = cell["offs_r"].astype(np.int32)
        offs_c = cell["offs_c"].astype(np.int32)
        for i in range(n):
            nr = int(coords[i, 0])
            nc = int(coords[i, 1])
            rs = offs_r + nr
            cs = offs_c + nc
            if np.all(placeable[rs, cs]):
                keep.append(i)
        if not keep:
            return np.zeros((0, 2), dtype=coords.dtype)
        return coords[np.array(keep, dtype=np.int64)]

    def _try_place_matched_cell(
        self,
        random_labels,
        cell,
        placeable,
        th,
        tw,
        rng,
        occupied_centers,
        next_id,
        stratified,
    ):
        """Place one exact matched-pair cell (same footprint & area) or fail.

        Returns ``(ok, n_pix, center, used_disk)``. ``used_disk`` is always False
        in strict mode (disk fallback removed).
        """
        area = int(cell["area"])
        min_sep = max(2.0, float(cell["radius"]) * 1.15)
        # Only exact stamps: full footprint in-bounds, 100% in placeable, n_pix == area
        place_for_stamp = placeable  # always constrain when placeable is set
        strict_placeable = placeable is not None

        # Build candidate centers (full footprint in image; preferably fully in region)
        coords = self._centers_for_exact_matched_stamp(cell, placeable, th, tw)
        if coords.shape[0] == 0:
            # No geometric room for this exact footprint in this region
            return False, 0, None, False

        n_cand = coords.shape[0]
        # Pass 1: respect separation from already placed centers
        # Pass 2: ignore separation (still exact, non-overlapping stamps)
        for use_sep in (True, False):
            max_tries = min(400, max(80, n_cand))
            if n_cand > max_tries * 3:
                picks = rng.choice(n_cand, size=min(max_tries * 3, n_cand), replace=False)
            else:
                picks = rng.permutation(n_cand)
            for j, idx in enumerate(picks):
                if j >= max_tries * 3:
                    break
                r = float(coords[int(idx), 0])
                c = float(coords[int(idx), 1])
                center = (r, c)
                if use_sep and occupied_centers and min_sep > 0:
                    min_sep2 = min_sep * min_sep
                    ok_sep = True
                    for cr, cc in occupied_centers:
                        if (r - cr) ** 2 + (c - cc) ** 2 < min_sep2:
                            ok_sep = False
                            break
                    if not ok_sep:
                        continue
                if not self._footprint_fully_contained(
                    cell, center, place_for_stamp if strict_placeable else None, th, tw
                ):
                    continue
                n_pix = self._stamp_cell_footprint_labeled(
                    random_labels,
                    cell,
                    center,
                    next_id,
                    require_full=True,
                    only_empty=True,
                    placeable=place_for_stamp if strict_placeable else None,
                    min_frac_in_placeable=1.0 if strict_placeable else None,
                )
                if n_pix == area:
                    return True, n_pix, center, False

        # No exact non-overlapping placement found — do not fake with partial/disk
        return False, 0, None, False

    def generate_random_cell_mask(self):
        """Build a null cell mask via strict region-aware matched pairs to the GT mask.

        For each true cell, place **at most one** random cell with the **identical
        footprint** (same shape and **exact** pixel area) at a new XY inside the
        same atlas region (or undefined space if the GT cell is outside all zones).

        Partial stamps and disk fallbacks are **not** used — if an exact pair cannot
        be placed, that cell is reported as failed rather than approximated.
        """
        try:
            if self.original_background is None and self.background_image is None:
                messagebox.showwarning(
                    "Random Cell Mask",
                    "Load a TIFF image first.",
                )
                return

            gt = self._get_ground_truth_cell_mask()
            if gt is None or not np.any(gt):
                messagebox.showwarning(
                    "Random Cell Mask",
                    "No ground-truth cell mask is available.\n\n"
                    "Load a cell mask (Cell → Load Cell Mask…) or run Show Mask / Count Cells first.",
                )
                return

            bg = self.original_background or self.background_image
            tw, th = bg.size
            if gt.shape[0] != th or gt.shape[1] != tw:
                gt = self._l_image_to_bool_mask(
                    self._bool_mask_to_l_image(gt), (th, tw)
                )

            cells = self._extract_cell_instances(gt)
            if not cells:
                messagebox.showwarning(
                    "Random Cell Mask",
                    "Could not identify individual cells in the ground-truth mask.",
                )
                return

            n_gt = len(cells)
            seed_str = simpledialog.askstring(
                "Random Cell Mask",
                f"Ground-truth cells: {n_gt}\n"
                f"Strict matched pairs: each random cell has the exact same\n"
                f"shape and pixel area as one true cell, new XY only.\n"
                f"Named region → same region; outside regions → undefined only.\n"
                f"(No partial stamps or disk approximations.)\n\n"
                "Optional random seed (integer). Leave blank for a new draw:",
                parent=self.master,
            )
            if seed_str is None:
                return
            seed_str = seed_str.strip()
            if seed_str == "":
                seed = int(np.random.randint(0, 2**31 - 1))
            else:
                try:
                    seed = int(seed_str)
                except Exception:
                    messagebox.showerror(
                        "Random Cell Mask",
                        "Seed must be an integer (or blank).",
                    )
                    return
            rng = np.random.default_rng(seed)

            # Region mask for stratification
            page = self.current_page if self.current_page is not None else 0
            zone_mask = None
            stratified = False
            if page in self.mask_images and self.mask_images[page] is not None:
                try:
                    zone_mask, _, _ = self._zone_mask_registered_to_background(
                        self.mask_images[page], th, tw
                    )
                    if zone_mask is not None and int(np.max(zone_mask)) > 0:
                        stratified = True
                except Exception as e:
                    logger.debug(f"Zone register for random mask: {e}")
                    zone_mask = None
                    stratified = False

            try:
                gray = self._pil_to_gray_float(bg)
                thr = float(np.percentile(gray, 5))
                tissue = gray > thr
                if int(tissue.sum()) < n_gt * 10:
                    tissue = np.ones((th, tw), dtype=bool)
            except Exception:
                tissue = np.ones((th, tw), dtype=bool)

            # Group cells by zone of GT centroid (region-specific matched pairs)
            by_zone = {}  # zid -> list of cells
            for cell in cells:
                if stratified and zone_mask is not None:
                    r0 = min(max(int(round(cell["row"])), 0), th - 1)
                    c0 = min(max(int(round(cell["col"])), 0), tw - 1)
                    zid = int(zone_mask[r0, c0])
                else:
                    zid = 0
                cell = dict(cell)
                cell["zone_id"] = zid
                by_zone.setdefault(zid, []).append(cell)

            # Labeled map: exactly one id per successfully placed matched cell
            random_labels = np.zeros((th, tw), dtype=np.int32)
            occupied_centers = []
            placed = 0
            n_exact = 0
            n_failed = 0
            total_gt_area = sum(int(c["area"]) for c in cells)
            total_placed_gt_area = 0  # sum of GT areas for successfully paired cells
            total_random_area = 0
            next_id = 1
            # zid -> {gt_n, placed_n, gt_area, rand_area, failed_n}
            per_zone_stats = {}

            for zid in sorted(by_zone.keys()):
                zone_cells = by_zone[zid]
                placeable = self._placeable_for_zone(
                    zid, zone_mask, tissue, stratified
                )
                z_gt_area = sum(int(c["area"]) for c in zone_cells)
                z_rand_area = 0
                z_failed = 0
                if placeable is None or not np.any(placeable):
                    logger.warning(
                        f"Random mask: no placeable pixels for zone {zid}; "
                        f"{len(zone_cells)} cells cannot be placed there"
                    )
                    per_zone_stats[int(zid)] = {
                        "gt_n": len(zone_cells),
                        "placed_n": 0,
                        "gt_area": z_gt_area,
                        "rand_area": 0,
                        "failed_n": len(zone_cells),
                    }
                    n_failed += len(zone_cells)
                    continue

                zone_placed = 0
                # Shuffle order within zone only (keeps per-zone multiset of sizes)
                order = rng.permutation(len(zone_cells))
                for j in order:
                    cell = zone_cells[int(j)]
                    ok, n_pix, center, _used_disk = self._try_place_matched_cell(
                        random_labels,
                        cell,
                        placeable,
                        th,
                        tw,
                        rng,
                        occupied_centers,
                        next_id,
                        stratified,
                    )
                    if ok and center is not None and n_pix == int(cell["area"]):
                        occupied_centers.append(center)
                        placed += 1
                        zone_placed += 1
                        n_exact += 1
                        next_id += 1
                        total_placed_gt_area += int(cell["area"])
                        total_random_area += int(n_pix)
                        z_rand_area += int(n_pix)
                    else:
                        n_failed += 1
                        z_failed += 1
                        logger.debug(
                            f"Exact matched pair failed for cell area={cell['area']} "
                            f"zone={zid}"
                        )

                per_zone_stats[int(zid)] = {
                    "gt_n": len(zone_cells),
                    "placed_n": zone_placed,
                    "gt_area": z_gt_area,
                    "rand_area": z_rand_area,
                    "failed_n": z_failed,
                }

            random_mask = random_labels > 0
            n_unique = len(np.unique(random_labels)) - (1 if 0 in random_labels else 0)
            n_rand = n_unique

            self.random_cell_mask = random_mask
            self.random_cell_labels = random_labels  # keep for diagnostics / PNN
            self.random_perineuronal_mask = None
            self.random_perineuronal_labels = None
            self.random_perineuronal_cells = None

            # Per-zone summary string
            zone_lines = []
            if stratified:
                for zid in sorted(per_zone_stats.keys()):
                    st = per_zone_stats[zid]
                    zname = (
                        (self.zone_names.get(page, {}) or {}).get(zid, f"Zone {zid}")
                        if zid > 0
                        else "Outside regions (undefined)"
                    )
                    fail_bit = (
                        f", failed {st['failed_n']}" if st["failed_n"] else ""
                    )
                    zone_lines.append(
                        f"  {zname}: GT {st['gt_n']} → exact random {st['placed_n']}"
                        f" (area {st['gt_area']} → {st['rand_area']} px{fail_bit})"
                    )
            else:
                # Unstratified: single global line with areas
                zone_lines.append(
                    f"  All tissue: GT {n_gt} → exact random {placed} "
                    f"(area {total_gt_area} → {int(random_mask.sum())} px)"
                )

            actual_rand_area = int(random_mask.sum())
            self.random_cell_mask_meta = {
                "n_ground_truth": n_gt,
                "n_random_components": n_rand,
                "n_placed": placed,
                "n_failed": n_failed,
                "n_exact_area_pairs": n_exact,
                "n_disk_fallback": 0,
                "matched_pairs": True,
                "strict_exact_area": True,
                "strategy": "strict_matched_pair_exact_footprint_region_locked",
                "total_gt_area_px": total_gt_area,
                "total_placed_gt_area_px": total_placed_gt_area,
                "total_random_area_px": actual_rand_area,
                "area_match_ok": (
                    total_placed_gt_area == actual_rand_area and n_exact == placed
                ),
                "stamps_full_area": n_exact,
                "stratified": stratified,
                "per_zone_stats": {
                    str(k): dict(v) for k, v in per_zone_stats.items()
                },
                "seed": seed,
                "atlas_zones_used": (
                    int(np.max(zone_mask))
                    if stratified and zone_mask is not None
                    else 0
                ),
            }

            self.show_ground_truth_and_random_masks()

            zone_txt = ("\n".join(zone_lines) + "\n") if zone_lines else ""
            warn = ""
            if placed != n_gt:
                warn = (
                    f"\n{n_failed}/{n_gt} cells could not get an exact same-area "
                    f"pair in their region (too large for free space / packing).\n"
                    f"Failed cells are omitted — no partial or disk fakes.\n"
                )
            if total_placed_gt_area != actual_rand_area:
                warn += (
                    f"\nWARNING: placed GT area {total_placed_gt_area} ≠ "
                    f"random area {actual_rand_area} (unexpected).\n"
                )
            region_note = ""
            if stratified:
                region_note = (
                    "Named-region cells → exact pairs only inside that region.\n"
                    "Outside-region cells → exact pairs only in undefined space.\n"
                )
            save_it = messagebox.askyesno(
                "Random Cell Mask Generated",
                f"Strict matched-pair random null created.\n\n"
                f"Ground-truth cells: {n_gt}\n"
                f"Exact same-area pairs placed: {placed} "
                f"(components: {n_rand})\n"
                f"Failed (no exact fit): {n_failed}\n"
                f"GT total area: {total_gt_area} px\n"
                f"Paired GT area: {total_placed_gt_area} px\n"
                f"Random total area: {actual_rand_area} px "
                f"{'(matches paired GT)' if total_placed_gt_area == actual_rand_area else '(MISMATCH)'}\n"
                f"Stratified by atlas region: {'Yes' if stratified else 'No'}\n"
                f"{zone_txt}"
                f"Random seed: {seed}\n"
                f"{warn}\n"
                f"{region_note}"
                f"Every placed random cell has the identical shape and "
                f"pixel count as its GT partner.\n"
                f"Display: red = ground truth, cyan = random.\n\n"
                f"Save the random mask to disk?",
            )
            if save_it:
                self._save_random_cell_mask_file()

            logger.info(
                f"Random cell mask (strict exact pairs): gt={n_gt} placed={placed} "
                f"exact={n_exact} components={n_rand} gt_area={total_gt_area} "
                f"paired_gt_area={total_placed_gt_area} "
                f"rand_area={actual_rand_area} failed={n_failed} "
                f"stratified={stratified} zones={per_zone_stats} seed={seed}"
            )
        except Exception as e:
            logger.error(f"generate_random_cell_mask failed: {e}", exc_info=True)
            messagebox.showerror(
                "Random Cell Mask",
                f"Failed to generate random cell mask:\n{e}",
            )

    def show_ground_truth_and_random_masks(self):
        """Overlay ground-truth (red) and random null (cyan) cell masks."""
        if self.original_background is None and self.background_image is None:
            messagebox.showwarning("Show Masks", "Load a TIFF image first.")
            return

        gt = self._get_ground_truth_cell_mask()
        rand = getattr(self, "random_cell_mask", None)
        if gt is None and rand is None:
            messagebox.showinfo(
                "Show Masks",
                "No ground-truth or random cell mask is available.\n\n"
                "Load/detect a cell mask, then Generate Random Cell Mask…",
            )
            return

        target_size = (self.original_background or self.background_image).size
        # Start transparent
        composite = Image.new("RGBA", target_size, (0, 0, 0, 0))

        if gt is not None and np.any(gt):
            red = self._cell_detection_ring_overlay(
                gt, size=target_size, color=(255, 0, 0), alpha=230, thickness=2
            )
            composite = Image.alpha_composite(composite, red.convert("RGBA"))

        if rand is not None and np.any(rand):
            cyan = self._cell_detection_ring_overlay(
                rand, size=target_size, color=(0, 220, 255), alpha=220, thickness=2
            )
            composite = Image.alpha_composite(composite, cyan.convert("RGBA"))

        self.show_page(mask=composite)
        self.showing_auto_mask = True

        meta = getattr(self, "random_cell_mask_meta", None) or {}
        if meta:
            logger.info(
                f"Showing GT+random masks: gt_cells={meta.get('n_ground_truth')} "
                f"random={meta.get('n_placed')} stratified={meta.get('stratified')}"
            )

    def clear_random_cell_mask(self):
        """Remove the random null mask overlay."""
        self.random_cell_mask = None
        self.random_cell_mask_meta = None
        # Random PNN shells are derived from random cells — clear them too
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None
        try:
            if self.auto_mask is not None:
                self.show_cell_mask_threshold(calculate=False)
            else:
                self.show_page()
        except Exception:
            self.show_page()
        messagebox.showinfo("Random Cell Mask", "Random cell mask cleared.")

    # ------------------------------------------------------------------
    # Perineuronal (PNN) shells — ring between cell boundary and 2× cell area
    # ------------------------------------------------------------------

    def _build_perineuronal_shells(self, cell_bool, area_factor=2.0):
        """Build perineuronal shells for each labeled cell.

        Outer disk area = ``area_factor × cell_area`` (default 2.0 = 200%).
        Shell = outer disk minus the cell body (and other cell bodies).

        Returns
        -------
        union : bool (H,W)
        labels : int32 (H,W) — cell label id in shell pixels (0 = background)
        records : list of dicts with cell_id, area, shell_area, centroid, radius, outer_radius
        """
        cell_bool = np.asarray(cell_bool, dtype=bool).squeeze()
        if cell_bool.ndim != 2 or not cell_bool.any():
            return None, None, []

        h, w = cell_bool.shape
        cell_labels = measure.label(cell_bool, connectivity=2)
        props = measure.regionprops(cell_labels)
        shell_labels = np.zeros((h, w), dtype=np.int32)
        records = []

        for p in props:
            if p.area < 1:
                continue
            lab = int(p.label)
            area = int(p.area)
            r_eq = max(1.0, float(np.sqrt(area / np.pi)))
            # Outer radius so π R² = area_factor * A
            r_out = max(r_eq + 0.5, float(np.sqrt(float(area_factor) * area / np.pi)))
            rr, cc = p.centroid
            rr_i, cc_i = int(round(rr)), int(round(cc))

            r0 = max(0, int(np.floor(rr_i - r_out - 1)))
            r1 = min(h, int(np.ceil(rr_i + r_out + 2)))
            c0 = max(0, int(np.floor(cc_i - r_out - 1)))
            c1 = min(w, int(np.ceil(cc_i + r_out + 2)))
            if r1 <= r0 or c1 <= c0:
                continue

            ys = np.arange(r0, r1)[:, None]
            xs = np.arange(c0, c1)[None, :]
            outer = (ys - rr_i) ** 2 + (xs - cc_i) ** 2 <= r_out ** 2
            # Extracellular ring: outside all cell bodies
            local_cells = cell_bool[r0:r1, c0:c1]
            shell = outer & ~local_cells
            # Only write into unoccupied shell labels (first cell wins on overlap)
            dest = shell_labels[r0:r1, c0:c1]
            write = shell & (dest == 0)
            dest[write] = lab
            shell_labels[r0:r1, c0:c1] = dest

            shell_area = int(np.sum(shell_labels == lab))
            records.append(
                {
                    "cell_id": lab,
                    "area": area,
                    "shell_area": shell_area,
                    "row": float(rr),
                    "col": float(cc),
                    "radius": r_eq,
                    "outer_radius": r_out,
                }
            )

        union = shell_labels > 0
        return union, shell_labels, records

    def draw_perineuronal_masks(self):
        """Create perineuronal shells for GT cells (and random cells if present).

        Shell = disk with area 200% of the cell (2×), minus the cell body mask.
        """
        try:
            if self.original_background is None and self.background_image is None:
                messagebox.showwarning(
                    "Perineuronal Masks",
                    "Load a TIFF image first.",
                )
                return

            bg = self.original_background or self.background_image
            tw, th = bg.size
            factor = float(getattr(self, "perineuronal_area_factor", 2.0) or 2.0)

            gt = self._get_ground_truth_cell_mask()
            if gt is None or not np.any(gt):
                messagebox.showwarning(
                    "Perineuronal Masks",
                    "No ground-truth cell mask is available.\n\n"
                    "Load a cell mask or run Cell → Show Mask / Count Cells first.",
                )
                return

            if gt.shape[0] != th or gt.shape[1] != tw:
                gt = self._l_image_to_bool_mask(
                    self._bool_mask_to_l_image(gt), (th, tw)
                )

            progress = self._show_busy_dialog("Perineuronal Masks")
            try:
                progress.set_progress(20, "Building GT perineuronal shells…")
                union, labels, records = self._build_perineuronal_shells(
                    gt, area_factor=factor
                )
                self.perineuronal_mask = union
                self.perineuronal_labels = labels
                self.perineuronal_cells = records

                n_rand = 0
                rand = getattr(self, "random_cell_mask", None)
                if rand is not None and np.any(rand):
                    progress.set_progress(55, "Building random perineuronal shells…")
                    rmask = np.asarray(rand, dtype=bool).squeeze()
                    if rmask.shape[0] != th or rmask.shape[1] != tw:
                        rmask = self._l_image_to_bool_mask(
                            self._bool_mask_to_l_image(rmask), (th, tw)
                        )
                    ru, rl, rr = self._build_perineuronal_shells(
                        rmask, area_factor=factor
                    )
                    self.random_perineuronal_mask = ru
                    self.random_perineuronal_labels = rl
                    self.random_perineuronal_cells = rr
                    n_rand = len(rr or [])
                else:
                    self.random_perineuronal_mask = None
                    self.random_perineuronal_labels = None
                    self.random_perineuronal_cells = None

                progress.set_progress(90, "Displaying…")
                self.show_perineuronal_masks()
            finally:
                if progress and not getattr(progress, "closed", False):
                    progress.close()

            n_gt = len(self.perineuronal_cells or [])
            msg = (
                f"Perineuronal masks drawn (outer area = {factor:.0%} of cell area).\n\n"
                f"True cells with shells: {n_gt}\n"
            )
            if n_rand:
                msg += f"Random cells with shells: {n_rand}\n"
            else:
                msg += (
                    "No random cell mask present — only true-cell shells drawn.\n"
                    "(Generate Random Cell Mask first if you need a null distribution.)\n"
                )
            msg += (
                "\nDisplay: magenta = true PNN shells, yellow = random PNN shells\n"
                "(cell bodies remain red / cyan).\n\n"
                "Use Axons and Nets → Measure Perineuronal Intensity… next."
            )
            messagebox.showinfo("Perineuronal Masks", msg)
            logger.info(
                f"Perineuronal masks: gt_cells={n_gt} random_cells={n_rand} "
                f"area_factor={factor}"
            )
        except Exception as e:
            logger.error(f"draw_perineuronal_masks failed: {e}", exc_info=True)
            messagebox.showerror(
                "Perineuronal Masks",
                f"Failed to draw perineuronal masks:\n{e}",
            )

    def show_perineuronal_masks(self):
        """Overlay cell masks + perineuronal shells (true magenta, random yellow)."""
        if self.original_background is None and self.background_image is None:
            messagebox.showwarning("Perineuronal Masks", "Load a TIFF image first.")
            return

        target_size = (self.original_background or self.background_image).size
        composite = Image.new("RGBA", target_size, (0, 0, 0, 0))

        # GT cells (red)
        gt = self._get_ground_truth_cell_mask()
        if gt is not None and np.any(gt):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    gt, size=target_size, color=(255, 0, 0), alpha=200, thickness=2
                ).convert("RGBA"),
            )

        # GT PNN shells (magenta)
        pnn = getattr(self, "perineuronal_mask", None)
        if pnn is not None and np.any(pnn):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    pnn, size=target_size, color=(255, 0, 200), alpha=180, thickness=1
                ).convert("RGBA"),
            )

        # Random cells (cyan)
        rand = getattr(self, "random_cell_mask", None)
        if rand is not None and np.any(rand):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    rand, size=target_size, color=(0, 220, 255), alpha=200, thickness=2
                ).convert("RGBA"),
            )

        # Random PNN shells (yellow)
        rpnn = getattr(self, "random_perineuronal_mask", None)
        if rpnn is not None and np.any(rpnn):
            composite = Image.alpha_composite(
                composite,
                self._cell_detection_ring_overlay(
                    rpnn, size=target_size, color=(255, 220, 0), alpha=180, thickness=1
                ).convert("RGBA"),
            )

        if not np.any(np.array(composite)[..., 3]):
            messagebox.showinfo(
                "Perineuronal Masks",
                "Nothing to show.\n\nDraw perineuronal masks (and/or load cell masks) first.",
            )
            return

        self.show_page(mask=composite)
        self.showing_auto_mask = True

    def clear_perineuronal_masks(self):
        """Clear all perineuronal shell masks."""
        self.perineuronal_mask = None
        self.perineuronal_labels = None
        self.perineuronal_cells = None
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None
        try:
            if getattr(self, "random_cell_mask", None) is not None:
                self.show_ground_truth_and_random_masks()
            elif self.auto_mask is not None:
                self.show_cell_mask_threshold(calculate=False)
            else:
                self.show_page()
        except Exception:
            self.show_page()
        messagebox.showinfo("Perineuronal Masks", "Perineuronal masks cleared.")

    def _sem(self, values):
        """Standard error of the mean; NaN if fewer than 2 samples."""
        vals = np.asarray(values, dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        n = vals.size
        if n < 1:
            return np.nan
        if n == 1:
            return 0.0
        return float(np.std(vals, ddof=1) / np.sqrt(n))

    def _sem_median(self, values):
        """Asymptotic SEM of the median under normality: 1.2533 × SEM_mean."""
        sm = self._sem(values)
        if sm is None or (isinstance(sm, float) and np.isnan(sm)):
            return np.nan
        return float(1.253314 * sm)

    def _zone_id_at_point(self, row, col, zone_mask, zone_names):
        """Return (zone_id, zone_name) for a pixel; (0, 'Outside') if none."""
        if zone_mask is None:
            return 0, "Outside"
        h, w = zone_mask.shape[:2]
        r = int(round(row))
        c = int(round(col))
        if r < 0 or c < 0 or r >= h or c >= w:
            return 0, "Outside"
        zid = int(zone_mask[r, c])
        if zid <= 0:
            return 0, "Outside"
        name = zone_names.get(zid, zone_names.get(int(zid), f"Zone {zid}"))
        return zid, str(name)

    def _measure_pnn_per_cell(self, gray, shell_labels, cell_records, zone_mask, zone_names):
        """Per-cell perineuronal intensity rows."""
        rows = []
        if shell_labels is None or not cell_records:
            return rows
        for rec in cell_records:
            lab = int(rec["cell_id"])
            pix = gray[shell_labels == lab]
            if pix.size == 0:
                inten = np.nan
            else:
                inten = float(np.mean(pix))
            zid, zname = self._zone_id_at_point(
                rec["row"], rec["col"], zone_mask, zone_names
            )
            rows.append(
                {
                    "Cell_ID": lab,
                    "Zone_ID": zid,
                    "Zone": zname,
                    "Cell_Area": int(rec.get("area", 0)),
                    "Shell_Area": int(rec.get("shell_area", 0) or 0),
                    "Perineuronal_Intensity": inten,
                    "Centroid_X": float(rec.get("col", 0)),
                    "Centroid_Y": float(rec.get("row", 0)),
                    "Outer_Radius": float(rec.get("outer_radius", 0) or 0),
                }
            )
        return rows

    def measure_perineuronal_intensity(self):
        """Measure intensity in perineuronal shells; export structure + per-cell tables.

        Spreadsheets written under ``output/pnn/``:
          - ``{base}_pnn_by_structure.xlsx`` — one row per atlas structure with
            mean/SEM and median/SEM for true (and random if present) PNN intensity
          - ``{base}_pnn_cells_true.xlsx`` — one row per true cell (area + PNN intensity)
          - ``{base}_pnn_cells_random.xlsx`` — same for random cells (if drawn)
        """
        try:
            # Auto-draw shells if missing but cell masks exist
            need_draw = self.perineuronal_labels is None or not (
                self.perineuronal_cells
            )
            if need_draw:
                gt = self._get_ground_truth_cell_mask()
                if gt is None or not np.any(gt):
                    messagebox.showwarning(
                        "Perineuronal Intensity",
                        "No cell mask available.\n\n"
                        "Load/detect cells, then Axons and Nets → Draw Perineuronal Masks.",
                    )
                    return
                if not messagebox.askyesno(
                    "Perineuronal Intensity",
                    "Perineuronal masks have not been drawn yet.\n\n"
                    "Draw them now (2× cell area shells) and measure?",
                ):
                    return
                self.draw_perineuronal_masks()
                if self.perineuronal_labels is None:
                    return

            bg = self.original_background or self.background_image
            if bg is None:
                messagebox.showwarning(
                    "Perineuronal Intensity",
                    "Load a TIFF image first.",
                )
                return

            gray = self._pil_to_gray_float(bg)
            th, tw = gray.shape[:2]
            page = self.current_page if self.current_page is not None else 0
            zone_names = dict(self.zone_names.get(page, {}) or {})
            zone_mask = None
            if page in self.mask_images and self.mask_images[page] is not None:
                try:
                    zone_mask, _, _ = self._zone_mask_registered_to_background(
                        self.mask_images[page], th, tw
                    )
                except Exception:
                    zone_mask = None

            # Per-cell tables
            true_rows = self._measure_pnn_per_cell(
                gray,
                self.perineuronal_labels,
                self.perineuronal_cells or [],
                zone_mask,
                zone_names,
            )
            rand_rows = []
            if (
                getattr(self, "random_perineuronal_labels", None) is not None
                and getattr(self, "random_perineuronal_cells", None)
            ):
                rand_rows = self._measure_pnn_per_cell(
                    gray,
                    self.random_perineuronal_labels,
                    self.random_perineuronal_cells,
                    zone_mask,
                    zone_names,
                )

            if not true_rows and not rand_rows:
                messagebox.showwarning(
                    "Perineuronal Intensity",
                    "No perineuronal shell pixels found to measure.",
                )
                return

            # Aggregate by structure
            def _agg(rows, prefix):
                """prefix e.g. True / Random → columns True_Mean, True_SEM_Mean, ..."""
                by_zone = {}
                for r in rows:
                    key = (int(r["Zone_ID"]), str(r["Zone"]))
                    by_zone.setdefault(key, []).append(r["Perineuronal_Intensity"])
                out = {}
                for key, vals in by_zone.items():
                    v = [x for x in vals if x is not None and np.isfinite(x)]
                    n = len(v)
                    mean_v = float(np.mean(v)) if n else np.nan
                    med_v = float(np.median(v)) if n else np.nan
                    out[key] = {
                        f"{prefix}_N_Cells": n,
                        f"{prefix}_Mean": mean_v,
                        f"{prefix}_SEM_Mean": self._sem(v),
                        f"{prefix}_Median": med_v,
                        f"{prefix}_SEM_Median": self._sem_median(v),
                    }
                return out

            true_agg = _agg(true_rows, "True")
            rand_agg = _agg(rand_rows, "Random") if rand_rows else {}

            # All zone keys from both + named atlas zones
            keys = set(true_agg.keys()) | set(rand_agg.keys())
            for zid, zname in zone_names.items():
                try:
                    keys.add((int(zid), str(zname)))
                except Exception:
                    pass
            if not keys and true_rows:
                keys = set(true_agg.keys())

            struct_rows = []
            for zid, zname in sorted(keys, key=lambda k: (k[0] == 0, k[0], k[1])):
                row = {"Zone_ID": zid, "Zone": zname}
                row.update(
                    true_agg.get(
                        (zid, zname),
                        {
                            "True_N_Cells": 0,
                            "True_Mean": np.nan,
                            "True_SEM_Mean": np.nan,
                            "True_Median": np.nan,
                            "True_SEM_Median": np.nan,
                        },
                    )
                )
                # Match by Zone_ID if name slightly differs
                if (zid, zname) not in true_agg and zid:
                    for (zid2, zname2), data in true_agg.items():
                        if zid2 == zid:
                            row.update(data)
                            break
                if rand_rows:
                    if (zid, zname) in rand_agg:
                        row.update(rand_agg[(zid, zname)])
                    else:
                        matched = False
                        for (zid2, zname2), data in rand_agg.items():
                            if zid2 == zid:
                                row.update(data)
                                matched = True
                                break
                        if not matched:
                            row.update(
                                {
                                    "Random_N_Cells": 0,
                                    "Random_Mean": np.nan,
                                    "Random_SEM_Mean": np.nan,
                                    "Random_Median": np.nan,
                                    "Random_SEM_Median": np.nan,
                                }
                            )
                struct_rows.append(row)

            df_struct = pd.DataFrame(struct_rows)
            df_true = pd.DataFrame(true_rows) if true_rows else pd.DataFrame()
            df_rand = pd.DataFrame(rand_rows) if rand_rows else pd.DataFrame()

            base_name, tiff_dir, out_dir = self._intensity_output_basename_and_dir(
                feature="pnn"
            )
            saved = []

            def _write_df(df, path_xlsx, sheet, csv_fallback):
                if df is None or df.empty:
                    return None
                for engine in ("openpyxl", "xlsxwriter"):
                    try:
                        with pd.ExcelWriter(path_xlsx, engine=engine) as writer:
                            df.to_excel(writer, sheet_name=sheet, index=False)
                        return path_xlsx
                    except Exception as e:
                        logger.warning(f"PNN Excel {engine}: {e}")
                try:
                    df.to_csv(csv_fallback, index=False)
                    return csv_fallback
                except Exception as e:
                    logger.error(f"PNN CSV failed: {e}")
                    return None

            if out_dir:
                p_struct = os.path.join(out_dir, f"{base_name}_pnn_by_structure.xlsx")
                p_true = os.path.join(out_dir, f"{base_name}_pnn_cells_true.xlsx")
                p_rand = os.path.join(out_dir, f"{base_name}_pnn_cells_random.xlsx")
                s1 = _write_df(
                    df_struct,
                    p_struct,
                    "PNN by Structure",
                    os.path.join(out_dir, f"{base_name}_pnn_by_structure.csv"),
                )
                s2 = _write_df(
                    df_true,
                    p_true,
                    "PNN Cells True",
                    os.path.join(out_dir, f"{base_name}_pnn_cells_true.csv"),
                )
                s3 = None
                if not df_rand.empty:
                    s3 = _write_df(
                        df_rand,
                        p_rand,
                        "PNN Cells Random",
                        os.path.join(out_dir, f"{base_name}_pnn_cells_random.csv"),
                    )
                for p in (s1, s2, s3):
                    if p:
                        saved.append(p)
            else:
                # Manual folder
                path = fd.asksaveasfilename(
                    title="Save PNN by-structure table",
                    defaultextension=".xlsx",
                    filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
                    initialfile=f"{base_name}_pnn_by_structure.xlsx",
                )
                if path:
                    if path.lower().endswith(".csv"):
                        df_struct.to_csv(path, index=False)
                        saved.append(path)
                    else:
                        if not path.lower().endswith(".xlsx"):
                            path += ".xlsx"
                        s1 = _write_df(df_struct, path, "PNN by Structure", path.replace(".xlsx", ".csv"))
                        if s1:
                            saved.append(s1)
                        parent = os.path.dirname(path)
                        if not df_true.empty:
                            s2 = _write_df(
                                df_true,
                                os.path.join(parent, f"{base_name}_pnn_cells_true.xlsx"),
                                "PNN Cells True",
                                os.path.join(parent, f"{base_name}_pnn_cells_true.csv"),
                            )
                            if s2:
                                saved.append(s2)
                        if not df_rand.empty:
                            s3 = _write_df(
                                df_rand,
                                os.path.join(parent, f"{base_name}_pnn_cells_random.xlsx"),
                                "PNN Cells Random",
                                os.path.join(parent, f"{base_name}_pnn_cells_random.csv"),
                            )
                            if s3:
                                saved.append(s3)

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            if saved:
                dest = out_dir or os.path.dirname(saved[0])
                messagebox.showinfo(
                    "Perineuronal Intensity Saved",
                    f"True cells measured: {len(true_rows)}\n"
                    f"Random cells measured: {len(rand_rows)}\n"
                    f"Structures in summary: {len(struct_rows)}\n\n"
                    f"Saved under:\n{dest}\n\n"
                    + "\n".join(saved)
                    + "\n\nBy-structure columns: True/Random Mean, SEM_Mean, "
                    "Median, SEM_Median.\n"
                    "Per-cell files: Cell_Area + Perineuronal_Intensity.",
                )
                logger.info(f"PNN intensity export: {saved}")
            else:
                messagebox.showwarning(
                    "Export Failed",
                    "Measured intensities but could not write spreadsheets.\n"
                    "Check folder permissions / install openpyxl.",
                )
        except Exception as e:
            logger.error(f"measure_perineuronal_intensity failed: {e}", exc_info=True)
            messagebox.showerror(
                "Perineuronal Intensity",
                f"Failed to measure perineuronal intensity:\n{e}",
            )

    def _save_random_cell_mask_file(self):
        """Write random null mask to output/cell_masks/ as PNG + JSON sidecar."""
        rand = getattr(self, "random_cell_mask", None)
        if rand is None or not np.any(rand):
            messagebox.showwarning("Save Random Mask", "No random cell mask to save.")
            return
        base_name = self.tiff_filename or "cells"
        tiff_dir = self.tiff_dir or self.current_tiff_directory
        out_dir = self._get_output_directory(tiff_dir, feature="cell_masks") if tiff_dir else None
        if not out_dir:
            path = fd.asksaveasfilename(
                title="Save Random Cell Mask",
                defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("All files", "*.*")],
                initialfile=f"{base_name}_random_cellmask.png",
            )
            if not path:
                return
            self._bool_mask_to_l_image(rand).save(path)
            messagebox.showinfo("Random Mask Saved", f"Saved:\n{path}")
            return

        png_path = os.path.join(out_dir, f"{base_name}_random_cellmask.png")
        self._bool_mask_to_l_image(rand).save(png_path)

        # Sidecar JSON with meta + optional per-region counts
        meta = dict(getattr(self, "random_cell_mask_meta", None) or {})
        meta["saved_at"] = datetime.now().isoformat(timespec="seconds")
        meta["source_tiff"] = self.tiff_filename
        json_path = os.path.join(out_dir, f"{base_name}_random_cellmask.json")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logger.debug(f"Random mask JSON save failed: {e}")
            json_path = None

        if hasattr(self, "tiff_tree") and self.current_tiff_directory:
            try:
                self.master.after(300, self.refresh_tiff_file_list)
            except Exception:
                pass

        msg = f"Saved:\n{png_path}"
        if json_path:
            msg += f"\n{json_path}"
        messagebox.showinfo("Random Mask Saved", msg)
        logger.info(f"Random cell mask saved: {png_path}")

    def _find_two_probable_cell_centers(self, blob, intensity):
        """Find two seed points inside a binary blob for the most probable two-cell split.

        Preference order:
          1. Top two distance-transform peaks (centers of mass of thickness)
          2. Top two intensity peaks inside the blob
          3. Geometric: max-distance pixel + farthest other blob pixel
        Returns array shape (2, 2) of (row, col), or None if the blob is too small.
        """
        blob = np.asarray(blob, dtype=bool)
        if blob.sum() < 6:
            return None

        distance = distance_transform_edt(blob)
        # min_distance scales with blob size so the two peaks stay distinct
        area = int(blob.sum())
        min_dist = max(2, int(np.sqrt(area) / 6.0))

        coords = None
        try:
            coords = feature.peak_local_max(
                distance,
                min_distance=min_dist,
                labels=blob.astype(np.int32),
                num_peaks=2,
            )
        except TypeError:
            try:
                coords = feature.peak_local_max(distance, min_distance=min_dist, num_peaks=2)
                if coords is not None and len(coords):
                    coords = np.array([c for c in coords if blob[c[0], c[1]]])
            except Exception:
                coords = None
        except Exception:
            coords = None

        if coords is not None and len(coords) >= 2:
            return np.asarray(coords[:2], dtype=int)

        # Intensity peaks (brighter spots are more probable cell centers)
        inten = np.asarray(intensity, dtype=np.float64).copy()
        if inten.shape != blob.shape:
            try:
                inten = np.array(
                    Image.fromarray(
                        ((inten - inten.min()) / (inten.max() - inten.min() + 1e-8) * 255).astype(np.uint8)
                    ).resize((blob.shape[1], blob.shape[0]), Image.BILINEAR)
                ).astype(np.float64)
            except Exception:
                inten = distance
        inten = inten.astype(np.float64)
        inten[~blob] = 0
        try:
            coords = feature.peak_local_max(
                inten,
                min_distance=min_dist,
                labels=blob.astype(np.int32),
                num_peaks=2,
            )
        except Exception:
            coords = None
        if coords is not None and len(coords) >= 2:
            return np.asarray(coords[:2], dtype=int)

        # Geometric fallback: thickest point + farthest point in the blob
        flat = np.argmax(distance)
        y1, x1 = np.unravel_index(int(flat), distance.shape)
        if not blob[y1, x1]:
            ys, xs = np.where(blob)
            if len(ys) < 2:
                return None
            y1, x1 = int(ys[0]), int(xs[0])
        ys, xs = np.where(blob)
        d2 = (ys.astype(np.float64) - y1) ** 2 + (xs.astype(np.float64) - x1) ** 2
        i2 = int(np.argmax(d2))
        if d2[i2] < 1:
            return None
        return np.array([[y1, x1], [int(ys[i2]), int(xs[i2])]], dtype=int)

    def split_cell_at_click(self, event):
        """Click handler: split the masked cell under the cursor into two blobs."""
        if not getattr(self, 'splitting_cells', False):
            return
        if self.original_background is None:
            messagebox.showerror("Split Cell", "No image loaded.")
            return

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_image(cx, cy)
        x, y = int(round(ix)), int(round(iy))

        combined = self._get_combined_cell_mask()
        if combined is None:
            messagebox.showerror("Split Cell", "Could not build the cell mask.")
            return

        h, w = combined.shape
        if x < 0 or y < 0 or x >= w or y >= h:
            messagebox.showinfo("Split Cell", "Click inside the image.")
            return
        if not combined[y, x]:
            messagebox.showinfo(
                "Split Cell",
                "Click on a red masked cell. The click landed outside the cell mask.",
            )
            return

        # Connected component under the click = the single "masked cell" to split
        labels_cc = measure.label(combined, connectivity=2)
        target_id = int(labels_cc[y, x])
        if target_id == 0:
            messagebox.showinfo("Split Cell", "No cell found under the click.")
            return
        blob = labels_cc == target_id
        blob_area = int(blob.sum())
        if blob_area < 8:
            messagebox.showinfo(
                "Split Cell",
                "That cell is too small to split meaningfully.",
            )
            return

        # Preprocessed intensity for probabilistic centers (same pipeline as detection)
        try:
            bg = self.original_background.convert('L')
            intensity = self.image_processor.preprocess_image(bg)
            intensity = np.asarray(intensity, dtype=np.float64)
            if intensity.shape != blob.shape:
                intensity = np.array(
                    Image.fromarray(
                        ((intensity - intensity.min()) /
                         (intensity.max() - intensity.min() + 1e-8) * 255).astype(np.uint8)
                    ).resize((w, h), Image.BILINEAR),
                    dtype=np.float64,
                )
        except Exception:
            intensity = distance_transform_edt(blob).astype(np.float64)

        centers = self._find_two_probable_cell_centers(blob, intensity)
        if centers is None or len(centers) < 2:
            messagebox.showinfo(
                "Split Cell",
                "Could not find two probable cell centers inside that blob.",
            )
            return

        # Watershed with exactly two markers → two most probable blobs
        markers = np.zeros(blob.shape, dtype=np.int32)
        markers[int(centers[0, 0]), int(centers[0, 1])] = 1
        markers[int(centers[1, 0]), int(centers[1, 1])] = 2

        distance = distance_transform_edt(blob)
        try:
            # watershed_line=True leaves the ridge as 0 → natural split for labeling
            split_labels = segmentation.watershed(
                -distance, markers, mask=blob, watershed_line=True
            )
        except TypeError:
            split_labels = segmentation.watershed(-distance, markers, mask=blob)
            # Manually mark inter-label boundary as cut if watershed_line unsupported
            cut = np.zeros_like(blob, dtype=bool)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                shifted = np.roll(split_labels, shift=dy, axis=0)
                shifted = np.roll(shifted, shift=dx, axis=1)
                cut |= (
                    (split_labels > 0)
                    & (shifted > 0)
                    & (split_labels != shifted)
                )
            # Apply cut into labels as 0
            split_labels = split_labels.copy()
            split_labels[cut] = 0

        # Pixels that belonged to the blob but are no longer labeled = the cut ridge
        cut_pixels = blob & (split_labels == 0)
        if not cut_pixels.any():
            # Force a thin cut between the two seeds along the gradient of distance
            # by dilating the watershed ridge once from inter-label neighbors
            lab = split_labels.copy()
            if lab.max() < 2:
                messagebox.showinfo(
                    "Split Cell",
                    "Watershed could not separate two regions. Try Remove Cell to cut manually.",
                )
                return
            cut = np.zeros_like(blob, dtype=bool)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                shifted = np.roll(lab, shift=dy, axis=0)
                shifted = np.roll(shifted, shift=dx, axis=1)
                cut |= (lab > 0) & (shifted > 0) & (lab != shifted) & blob
            cut_pixels = cut

        if not cut_pixels.any():
            messagebox.showinfo(
                "Split Cell",
                "Could not create a separation line between the two blobs.",
            )
            return

        # Verify we actually get two components after the cut
        after = blob.copy()
        after[cut_pixels] = False
        n_after = measure.label(after, connectivity=2).max()
        if n_after < 2:
            # Widen the cut slightly (1-pixel dilation of the ridge, still inside blob)
            cut_pixels = ndi.binary_dilation(cut_pixels, iterations=1) & blob
            after = blob.copy()
            after[cut_pixels] = False
            n_after = measure.label(after, connectivity=2).max()
        if n_after < 2:
            messagebox.showinfo(
                "Split Cell",
                "Split did not produce two separate cells. The shape may not be a double cell.",
            )
            return

        # Persist the cut via manual remove mask (survives re-detect + Count Cells)
        self.save_state()
        base_size = self.original_background.size
        if self.manual_remove_mask is None:
            self.manual_remove_mask = Image.new('L', base_size, 0)
        if self.manual_remove_mask.size != base_size:
            self.manual_remove_mask = self.manual_remove_mask.resize(base_size, Image.NEAREST)

        rem = np.array(self.manual_remove_mask)
        if rem.ndim > 2:
            rem = rem.squeeze()
        if rem.shape != cut_pixels.shape:
            cut_img = Image.fromarray(cut_pixels.astype(np.uint8) * 255).resize(
                self.manual_remove_mask.size, Image.NEAREST
            )
            cut_pixels_r = np.array(cut_img) > 0
            rem[cut_pixels_r] = 255
        else:
            rem[cut_pixels] = 255
        self.manual_remove_mask = Image.fromarray(rem.astype(np.uint8), mode='L')
        self.current_mask = self.manual_remove_mask

        # Keep auto_mask in sync for immediate redisplay without full redetect:
        # do not modify auto_mask permanently; remove_mask is the source of truth.
        logger.info(
            f"Split cell at ({x},{y}): area={blob_area}, cut_pixels={int(cut_pixels.sum())}, "
            f"components_after={n_after}"
        )

        # Refresh overlay (use cached auto_mask)
        self.show_cell_mask_threshold(calculate=False)

    def stop_mask_edit(self, event=None):
        """Exit mask editing mode (add / remove / split)."""
        if not self.editing_mask and not getattr(self, 'splitting_cells', False):
            return
        self.editing_mask = False
        self.splitting_cells = False
        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.unbind("<Button-2>")
        self.output.unbind("<B2-Motion>")
        self.output.unbind("<ButtonRelease-2>")
        self.output.unbind("<Button-3>")
        self.output.unbind("<B3-Motion>")
        self.output.unbind("<ButtonRelease-3>")
        self.output.bind("<Button-1>", self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        logger.info("Stopped mask edit mode")
        messagebox.showinfo("Mask Editing", "Mask edits applied. You can now re-count cells.")

    # ==================================================================
    # SHARED ANALYSIS HELPERS (Smart Suggest + Measure Tune)
    # ==================================================================

    def _working_background_pil(self):
        """Source TIFF for detection/analysis: prefer full-res original, else display bg."""
        bg = getattr(self, "original_background", None)
        if bg is None:
            bg = getattr(self, "background_image", None)
        return bg

    def _get_detection_float_image(self):
        """Return the float image used by blob detection (preprocess only).

        Critical for Measure Tune: LoG thresholds must be measured on the *same*
        intensity scale that feature.blob_log sees at runtime — not a separate
        percentile-stretched analysis image.
        """
        bg = self._working_background_pil()
        if bg is None:
            return None
        bg_pil = bg.convert("L")
        img = self.image_processor.preprocess_image(bg_pil)
        img = np.asarray(img, dtype=np.float64)
        if img.size == 0:
            return None
        if np.nanmax(img) > 1.5:
            img = img / 255.0
        img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
        img = np.clip(img, 0.0, None)
        return img

    def _get_preprocessed_analysis_image(self, max_side=1400, for_detection_match=False):
        """Return (img_float_01, scale_xy) for analysis.

        for_detection_match=True: same intensities as blob detection (no p1–p99 stretch).
        for_detection_match=False: robust stretch (better for Smart Suggest peak finding).

        Large images may be downsampled; scale maps analysis coords → original
        (multiply analysis x,y by scale).
        """
        bg = self._working_background_pil()
        if bg is None:
            return None, 1.0

        if for_detection_match:
            img = self._get_detection_float_image()
            if img is None:
                return None, 1.0
            img = np.asarray(img, dtype=np.float64).copy()
        else:
            bg_pil = bg.convert("L")
            img = self.image_processor.preprocess_image(bg_pil)
            img = np.asarray(img, dtype=np.float64)
            if img.size == 0:
                return None, 1.0
            if np.nanmax(img) > 1.5:
                img = img / 255.0
            p1, p99 = np.percentile(img, 1), np.percentile(img, 99)
            if p99 <= p1:
                p1, p99 = float(np.min(img)), float(np.max(img) + 1e-8)
            img = np.clip((img - p1) / (p99 - p1 + 1e-8), 0.0, 1.0)

        h, w = img.shape[:2]
        m = max(h, w)
        scale = 1.0
        if m > max_side:
            scale = m / float(max_side)
            new_w = max(32, int(round(w / scale)))
            new_h = max(32, int(round(h / scale)))
            # preserve float range when resizing
            mx = float(np.max(img)) if np.max(img) > 0 else 1.0
            img_u8 = np.clip(img / mx * 255.0, 0, 255).astype(np.uint8)
            img = np.array(
                Image.fromarray(img_u8).resize((new_w, new_h), Image.BILINEAR),
                dtype=np.float64,
            ) / 255.0 * mx
        return img, scale

    def _log_scale_space_max(self, img, min_sigma=1.0, max_sigma=15.0, num_sigma=12,
                             progress_cb=None, progress_start=0, progress_end=100):
        """Multi-scale LoG max projection (skimage blob_log normalization).

        Returns log_max (HxW), best_sigma (HxW), sigmas (1d).
        progress_cb(percent, message) is optional for UI busy indicators.
        """
        from scipy.ndimage import gaussian_laplace
        img = np.asarray(img, dtype=np.float64)
        h, w = img.shape
        if max_sigma <= min_sigma:
            max_sigma = min_sigma + 1.0
        num_sigma = int(max(3, num_sigma))
        sigmas = np.linspace(float(min_sigma), float(max_sigma), num_sigma)
        log_max = np.full((h, w), -np.inf, dtype=np.float64)
        best_sigma = np.full((h, w), sigmas[0], dtype=np.float64)
        n = len(sigmas)
        for i, s in enumerate(sigmas):
            resp = -gaussian_laplace(img, sigma=float(s)) * (float(s) ** 2)
            better = resp > log_max
            log_max[better] = resp[better]
            best_sigma[better] = float(s)
            if progress_cb is not None:
                frac = (i + 1) / float(n)
                pct = progress_start + (progress_end - progress_start) * frac
                progress_cb(pct, f"LoG scale space ({i + 1}/{n})…")
        log_max[~np.isfinite(log_max)] = 0.0
        return log_max, best_sigma, sigmas

    def _find_log_peaks(self, log_max, best_sigma, min_distance=3, threshold=None, max_peaks=5000):
        """Local maxima of LoG max-projection (candidate cell centers)."""
        if threshold is None:
            thr = float(np.percentile(log_max, 92))
            thr = max(thr, float(np.median(log_max) + 2.5 * np.std(log_max)))
            threshold = thr
        try:
            coords = feature.peak_local_max(
                log_max,
                min_distance=int(max(1, min_distance)),
                threshold_abs=float(threshold),
                exclude_border=True,
                num_peaks=int(max_peaks),
            )
        except TypeError:
            coords = feature.peak_local_max(
                log_max,
                min_distance=int(max(1, min_distance)),
                threshold_abs=float(threshold),
            )
            if coords is not None and len(coords) > max_peaks:
                vals = log_max[coords[:, 0], coords[:, 1]]
                order = np.argsort(vals)[::-1][:max_peaks]
                coords = coords[order]
        if coords is None or len(coords) == 0:
            return np.zeros((0, 2), dtype=int), np.zeros(0), np.zeros(0)
        coords = np.asarray(coords, dtype=int)
        vals = log_max[coords[:, 0], coords[:, 1]]
        sigs = best_sigma[coords[:, 0], coords[:, 1]]
        return coords, vals, sigs

    def _count_mask_objects(self, mask):
        """Connected-component count + area/circularity stats for a binary mask."""
        mask = np.asarray(mask, dtype=bool)
        empty = {
            "n": 0, "areas": np.array([]), "radii": np.array([]),
            "circularities": np.array([]), "median_area": 0.0, "median_radius": 0.0,
        }
        if mask.ndim != 2 or not mask.any():
            return empty
        lab = measure.label(mask, connectivity=2)
        props = measure.regionprops(lab)
        areas, radii, circs = [], [], []
        for p in props:
            a = float(p.area)
            if a < 2:
                continue
            areas.append(a)
            radii.append(float(np.sqrt(a / np.pi)))
            per = float(p.perimeter) if p.perimeter > 0 else 1.0
            c = float(4.0 * np.pi * a / (per * per + 1e-8))
            circs.append(min(1.5, c))
        areas = np.asarray(areas, dtype=float)
        radii = np.asarray(radii, dtype=float)
        circs = np.asarray(circs, dtype=float)
        return {
            "n": int(len(areas)),
            "areas": areas,
            "radii": radii,
            "circularities": circs,
            "median_area": float(np.median(areas)) if len(areas) else 0.0,
            "median_radius": float(np.median(radii)) if len(radii) else 0.0,
        }

    def _smart_suggest_regional_diagnosis(
        self,
        img,
        log_max,
        peak_coords,
        peak_vals,
        mask_full,
        scale,
        typ_r_an=4.0,
    ):
        """Tile-wise FP/FN proxies for bright vs dark regions.

        Returns a diagnosis dict used to pick joint parameter recipes:
          - mixed_both: high-BG over-detect + low-BG under-detect (most common hard case)
          - high_bg_fp: false positives mainly on bright tissue
          - low_bg_fn: missed cells mainly in dark/mid clusters
          - global_over / global_under / balanced
        """
        img = np.asarray(img, dtype=np.float64)
        if img.ndim != 2 or img.size == 0:
            return {
                "recipe": "balanced",
                "high_bg_over": False,
                "low_bg_under": False,
                "summary": "No image for regional diagnosis.",
            }
        h, w = img.shape[:2]
        scale = float(scale) if scale else 1.0

        # Align mask to analysis resolution
        mask_an = None
        try:
            mf = np.asarray(mask_full)
            if mf.ndim > 2:
                mf = mf.squeeze()
            mf = mf > 0
            if mf.shape == (h, w):
                mask_an = mf
            elif mf.size > 0:
                mask_an = np.array(
                    Image.fromarray((mf.astype(np.uint8) * 255)).resize(
                        (w, h), resample=Image.Resampling.NEAREST
                        if hasattr(Image, "Resampling")
                        else Image.NEAREST
                    )
                ) > 0
        except Exception:
            mask_an = np.zeros((h, w), dtype=bool)
        if mask_an is None:
            mask_an = np.zeros((h, w), dtype=bool)

        # Object centroids in analysis space
        det_yx = []
        try:
            lab = measure.label(mask_an, connectivity=2)
            for p in measure.regionprops(lab):
                if p.area < 2:
                    continue
                cy, cx = p.centroid
                det_yx.append((float(cy), float(cx)))
        except Exception:
            pass
        det_yx = np.asarray(det_yx, dtype=np.float64) if det_yx else np.zeros((0, 2))

        peaks = np.asarray(peak_coords) if peak_coords is not None else np.zeros((0, 2))
        if peaks.ndim == 1:
            peaks = peaks.reshape(0, 2)
        pvals = (
            np.asarray(peak_vals, dtype=np.float64)
            if peak_vals is not None and len(peaks)
            else np.zeros(0)
        )

        n_ty = max(3, min(6, h // 100))
        n_tx = max(3, min(6, w // 100))
        tsy = max(24, h // n_ty)
        tsx = max(24, w // n_tx)

        tiles = []
        for y0 in range(0, h, tsy):
            for x0 in range(0, w, tsx):
                y1 = min(h, y0 + tsy)
                x1 = min(w, x0 + tsx)
                if (y1 - y0) < 16 or (x1 - x0) < 16:
                    continue
                patch = img[y0:y1, x0:x1]
                med = float(np.median(patch))
                p90 = float(np.percentile(patch, 90))
                # peaks in tile
                n_pk = 0
                contrasts = []
                if len(peaks):
                    in_t = (
                        (peaks[:, 0] >= y0)
                        & (peaks[:, 0] < y1)
                        & (peaks[:, 1] >= x0)
                        & (peaks[:, 1] < x1)
                    )
                    n_pk = int(np.sum(in_t))
                    if n_pk:
                        ys = peaks[in_t, 0].astype(int)
                        xs = peaks[in_t, 1].astype(int)
                        contrasts = (img[ys, xs] - med).tolist()
                n_dt = 0
                if len(det_yx):
                    in_d = (
                        (det_yx[:, 0] >= y0)
                        & (det_yx[:, 0] < y1)
                        & (det_yx[:, 1] >= x0)
                        & (det_yx[:, 1] < x1)
                    )
                    n_dt = int(np.sum(in_d))
                area_mp = ((y1 - y0) * (x1 - x0)) / 1e6
                mean_c = float(np.mean(contrasts)) if contrasts else 0.0
                tiles.append(
                    {
                        "med": med,
                        "p90": p90,
                        "n_peaks": n_pk,
                        "n_det": n_dt,
                        "mean_contrast": mean_c,
                        "peak_density": n_pk / max(area_mp, 1e-9),
                        "det_density": n_dt / max(area_mp, 1e-9),
                    }
                )

        if not tiles:
            return {
                "recipe": "balanced",
                "high_bg_over": False,
                "low_bg_under": False,
                "summary": "Too few tiles for regional diagnosis.",
            }

        meds = np.array([t["med"] for t in tiles], dtype=np.float64)
        med_mid = float(np.median(meds))
        # Bright vs dark thirds
        q33, q66 = float(np.percentile(meds, 33)), float(np.percentile(meds, 66))
        high = [t for t in tiles if t["med"] >= q66]
        low = [t for t in tiles if t["med"] <= q33]
        if not high:
            high = [t for t in tiles if t["med"] >= med_mid]
        if not low:
            low = [t for t in tiles if t["med"] <= med_mid]

        def _agg(group):
            if not group:
                return {
                    "n_peaks": 0,
                    "n_det": 0,
                    "mean_contrast": 0.0,
                    "peak_density": 0.0,
                    "det_density": 0.0,
                    "n_tiles": 0,
                }
            return {
                "n_peaks": int(sum(t["n_peaks"] for t in group)),
                "n_det": int(sum(t["n_det"] for t in group)),
                "mean_contrast": float(np.mean([t["mean_contrast"] for t in group])),
                "peak_density": float(np.mean([t["peak_density"] for t in group])),
                "det_density": float(np.mean([t["det_density"] for t in group])),
                "n_tiles": len(group),
            }

        H = _agg(high)
        L = _agg(low)
        bg_span = float(np.max(meds) - np.min(meds))
        bg_cv = float(np.std(meds) / (float(np.mean(meds)) + 1e-6))

        # High-BG over-detect: lots of detections (or peaks) with weak local contrast
        high_bg_over = False
        if H["n_tiles"] >= 2:
            weak_c = H["mean_contrast"] < 0.08 or (
                H["mean_contrast"] < L["mean_contrast"] * 0.7 and H["n_peaks"] >= 8
            )
            noisy = (
                H["det_density"] > max(80.0, L["det_density"] * 1.6)
                or (H["n_det"] >= 15 and H["n_det"] >= H["n_peaks"] * 0.7 and weak_c)
                or (H["peak_density"] > L["peak_density"] * 1.5 and weak_c and H["n_peaks"] >= 12)
            )
            high_bg_over = bool(noisy and (weak_c or H["det_density"] > 200))

        # Low-BG under-detect: many LoG peaks, few mask objects, decent contrast
        low_bg_under = False
        if L["n_tiles"] >= 2 and L["n_peaks"] >= 6:
            peak_det_gap = L["n_peaks"] > max(6, L["n_det"] * 1.8)
            decent_c = L["mean_contrast"] >= 0.04 or L["mean_contrast"] >= H["mean_contrast"] * 0.8
            low_bg_under = bool(peak_det_gap and decent_c)

        # Global fallbacks from totals
        tot_pk = sum(t["n_peaks"] for t in tiles)
        tot_dt = sum(t["n_det"] for t in tiles)
        global_under = tot_pk >= 20 and tot_dt < tot_pk * 0.55
        global_over = tot_dt >= 30 and tot_pk > 0 and tot_dt > tot_pk * 1.4

        # Trajectory: last recipe was high-BG strict and now low-BG under → ease
        prev = None
        hist = getattr(self, "_smart_suggest_history", None) or []
        if hist:
            prev = hist[-1]

        if high_bg_over and low_bg_under:
            recipe = "mixed_both"
        elif high_bg_over:
            recipe = "high_bg_fp"
        elif low_bg_under:
            recipe = "low_bg_fn"
        elif global_over:
            recipe = "global_over"
        elif global_under:
            recipe = "global_under"
        else:
            recipe = "balanced"

        # If previous apply was high_bg_fp / mixed with high SNR and we still under-detect dark
        if prev and low_bg_under and not high_bg_over:
            prev_r = prev.get("recipe")
            prev_snr = float(prev.get("blob_min_local_snr", 0) or 0)
            if prev_r in ("high_bg_fp", "mixed_both") and prev_snr >= 2.5:
                recipe = "recover_clusters"
            elif prev_r == "high_bg_fp" and global_under:
                recipe = "recover_clusters"

        summaries = {
            "mixed_both": (
                "Mixed field: bright tiles look over-detected (weak local contrast) while "
                "dark tiles miss cells vs LoG peaks — use Adaptive dual-pass + moderate local SNR "
                "(not a single global threshold)."
            ),
            "high_bg_fp": (
                "High-background tiles have many weak peaks/detections — raise local SNR and "
                "enable Adaptive dual-pass to suppress bright clutter."
            ),
            "low_bg_fn": (
                "Dark/mid tiles have LoG peaks without matching detections — lower threshold "
                "slightly, ease local SNR if high, and allow denser packing in clusters."
            ),
            "recover_clusters": (
                "Prior strict high-BG settings likely suppressed real cluster cells — ease "
                "local SNR toward 1.8–2.2 and slightly lower threshold while keeping Adaptive."
            ),
            "global_over": "Overall over-detection vs LoG evidence — tighten threshold / SNR.",
            "global_under": "Overall under-detection vs LoG evidence — lower threshold / sensitivity.",
            "balanced": "Regional peak/mask balance looks reasonable.",
        }

        return {
            "recipe": recipe,
            "high_bg_over": bool(high_bg_over),
            "low_bg_under": bool(low_bg_under),
            "global_over": bool(global_over),
            "global_under": bool(global_under),
            "bg_cv": round(bg_cv, 3),
            "bg_span": round(bg_span, 3),
            "high": H,
            "low": L,
            "n_tiles": len(tiles),
            "summary": summaries.get(recipe, summaries["balanced"]),
            "prev_recipe": prev.get("recipe") if prev else None,
        }

    def _estimate_radius_at_point(self, img, y, x, max_r=60):
        """Estimate cell radius via refined peak + radial half-max profile."""
        h, w = img.shape
        y = int(np.clip(y, 0, h - 1))
        x = int(np.clip(x, 0, w - 1))

        win = 7
        y0, y1 = max(0, y - win), min(h, y + win + 1)
        x0, x1 = max(0, x - win), min(w, x + win + 1)
        patch = img[y0:y1, x0:x1]
        if patch.size == 0:
            return 5.0, float(img[y, x]), y, x
        ly, lx = np.unravel_index(int(np.argmax(patch)), patch.shape)
        y, x = y0 + int(ly), x0 + int(lx)
        peak = float(img[y, x])

        pad = min(max_r, 24)
        loc = img[max(0, y - pad):min(h, y + pad + 1), max(0, x - pad):min(w, x + pad + 1)]
        floor = float(np.percentile(loc, 15)) if loc.size else 0.0
        thresh = floor + 0.5 * max(1e-6, peak - floor)

        r_limit = int(min(max_r, h // 3, w // 3, max(10, max_r)))
        radii = np.arange(1, r_limit + 1, dtype=float)
        profile = []
        for r in radii:
            n_ang = max(16, int(r * 4))
            angs = np.linspace(0, 2 * np.pi, n_ang, endpoint=False)
            vals = []
            for a in angs:
                yy = int(round(y + r * np.sin(a)))
                xx = int(round(x + r * np.cos(a)))
                if 0 <= yy < h and 0 <= xx < w:
                    vals.append(float(img[yy, xx]))
            profile.append(np.mean(vals) if vals else floor)

        profile = np.asarray(profile, dtype=float)
        below = np.where(profile < thresh)[0]
        if len(below):
            found_r = float(radii[below[0]])
        else:
            d = np.diff(profile, prepend=profile[0])
            found_r = float(radii[int(np.argmin(d))]) if len(d) else 5.0

        found_r = float(np.clip(found_r, 2.0, float(r_limit)))
        return found_r, peak, y, x

    def _log_response_at(self, img, y, x, sigma):
        """Scale-normalized LoG response at a point (local patch only — not full image).

        Earlier this ran gaussian_laplace on the *entire* frame per call, which
        froze Measure Tune Apply (samples × sigmas × full-res LoG).
        """
        from scipy.ndimage import gaussian_laplace
        try:
            h, w = img.shape[:2]
            y = int(np.clip(y, 0, h - 1))
            x = int(np.clip(x, 0, w - 1))
            sig = max(0.5, float(sigma))
            # Pad ~3σ so the kernel is not truncated for this point
            pad = int(max(8, min(48, round(sig * 4) + 4)))
            y0, y1 = max(0, y - pad), min(h, y + pad + 1)
            x0, x1 = max(0, x - pad), min(w, x + pad + 1)
            patch = np.asarray(img[y0:y1, x0:x1], dtype=np.float64)
            if patch.size < 9:
                return float(img[y, x])
            log_patch = -gaussian_laplace(patch, sigma=sig) * (sig ** 2)
            ly, lx = y - y0, x - x0
            # Local 3×3 max around the point
            a0, a1 = max(0, ly - 1), min(log_patch.shape[0], ly + 2)
            b0, b1 = max(0, lx - 1), min(log_patch.shape[1], lx + 2)
            return float(np.max(log_patch[a0:a1, b0:b1]))
        except Exception:
            yy = int(np.clip(y, 0, img.shape[0] - 1))
            xx = int(np.clip(x, 0, img.shape[1] - 1))
            return float(img[yy, xx])

    def _best_sigma_at_point(self, img, y, x, sigma_candidates):
        """Sigma maximizing LoG response at the point."""
        cands = list(sigma_candidates) if sigma_candidates is not None else [1.5]
        if not cands:
            cands = [1.5]
        best_s, best_r = float(cands[0]), -1e18
        for s in cands:
            r = self._log_response_at(img, y, x, s)
            if r > best_r:
                best_r, best_s = r, float(s)
        return float(best_s), float(best_r)

    def _measure_point_features(self, img, x, y, probe_sigmas=None):
        """Feature vector for a click: radius, sigma, LoG, intensity, SNR, area."""
        h, w = img.shape
        r, peak, yy, xx = self._estimate_radius_at_point(img, y, x)
        if probe_sigmas is None:
            s0 = max(1.0, r / 1.8)
            # Fewer probes — local LoG is cheap now, but keep clicks snappy
            probe_sigmas = np.unique(
                np.round(np.linspace(max(0.8, s0 * 0.4), s0 * 2.2, 8), 2)
            )
        s_best, log_r = self._best_sigma_at_point(img, yy, xx, probe_sigmas)
        sigma = 0.5 * max(1.0, r / 1.8) + 0.5 * s_best

        pad = int(max(8, min(40, r * 3)))
        y0, y1 = max(0, yy - pad), min(h, yy + pad + 1)
        x0, x1 = max(0, xx - pad), min(w, xx + pad + 1)
        loc = img[y0:y1, x0:x1]
        floor = float(np.percentile(loc, 20)) if loc.size else 0.0
        noise = float(np.std(loc)) if loc.size > 4 else 0.05
        snr = (peak - floor) / (noise + 1e-6)

        thr = floor + 0.4 * max(1e-6, peak - floor)
        local_bin = loc >= thr
        cy_l, cx_l = yy - y0, xx - x0
        if local_bin.any() and 0 <= cy_l < local_bin.shape[0] and 0 <= cx_l < local_bin.shape[1]:
            lab = measure.label(local_bin, connectivity=2)
            cid = lab[cy_l, cx_l]
            area = float(np.sum(lab == cid)) if cid > 0 else float(np.pi * r * r)
        else:
            area = float(np.pi * r * r)

        return {
            "x": int(xx), "y": int(yy),
            "radius": float(r),
            "sigma": float(sigma),
            "log_response": float(log_r),
            "peak": float(peak),
            "snr": float(snr),
            "area": float(max(3.0, area)),
            "floor": float(floor),
        }

    def _calibrate_blob_threshold(self, cell_logs, bg_logs, recall_bias=True):
        """Choose LoG threshold separating cell vs non-cell sample responses.

        Strongly biased toward *recall* (catching all sample cells, and dimmer
        cells like them). Previous scoring was too aggressive and undercounted.
        """
        cell_logs = np.asarray(cell_logs, dtype=float)
        bg_logs = np.asarray(bg_logs, dtype=float)
        if cell_logs.size == 0:
            return 0.05

        c_min = float(np.min(cell_logs))
        c_med = float(np.median(cell_logs))
        b_max = float(np.max(bg_logs)) if bg_logs.size else 0.0
        b_p90 = float(np.percentile(bg_logs, 90)) if bg_logs.size else 0.0

        # Primary strategy: sit well below the weakest sample cell, just above background.
        # Dimmer-than-sample cells need headroom → use a low fraction of c_min.
        if c_min > b_max and (c_min - b_max) > 1e-9:
            # Only 15–25% of the way from bg to weakest cell (was ~40% before → too high)
            thr = b_max + 0.18 * (c_min - b_max)
            # Never higher than 45% of weakest cell LoG
            thr = min(thr, c_min * 0.45)
        elif c_min > b_p90:
            thr = b_p90 + 0.12 * (c_min - b_p90)
            thr = min(thr, c_min * 0.4)
        else:
            # Overlap / noisy samples: go well below median cell response
            thr = min(c_min * 0.35, c_med * 0.25)

        # Optional search that *requires* all sample cells to pass (recall first)
        if recall_bias and cell_logs.size:
            candidates = np.unique(np.concatenate([
                [thr, c_min * 0.25, c_min * 0.35, c_min * 0.45, c_min * 0.55,
                 c_med * 0.2, c_med * 0.3, max(1e-6, b_max * 1.05), max(1e-6, b_p90 * 1.1)],
                np.linspace(max(1e-6, b_max * 0.5), max(c_min, c_med) * 0.8, 25),
            ]))
            candidates = candidates[np.isfinite(candidates) & (candidates > 0)]
            best_thr, best_score = thr, -1e18
            for t in candidates:
                cell_hit = float(np.mean(cell_logs >= t))
                bg_hit = float(np.mean(bg_logs >= t)) if bg_logs.size else 0.0
                if cell_hit < 1.0:
                    # Heavily penalize missing even one sample cell
                    score = 3.0 * cell_hit - 1.0 * bg_hit - 2.0
                else:
                    # All samples kept: prefer lower false positives, but still
                    # prefer lower thresholds slightly (more room for dim cells)
                    score = 3.0 - 0.8 * bg_hit - 0.15 * (t / (c_med + 1e-8))
                if score > best_score:
                    best_score, best_thr = score, float(t)
            thr = best_thr

        # Map large absolute LoG magnitudes into blob_log's typical operating range
        scale_ref = max(float(np.percentile(np.abs(cell_logs), 75)), 1e-6)
        if thr > 0.5:
            thr = thr / scale_ref * 0.08
        # Prefer sensitive defaults (skimage default is 0.2; we aim lower)
        thr = float(np.clip(thr, 0.008, 0.25))
        return thr

    def _derive_blob_settings_from_features(self, cell_feats, bg_feats, cell_pts=None):
        """Turn measured sample features into a coherent blob settings dict.

        Biased toward higher recall so Measure Tune does not systematically undercount.
        """
        if not cell_feats:
            return None

        sigmas = np.array([f["sigma"] for f in cell_feats], dtype=float)
        radii = np.array([f["radius"] for f in cell_feats], dtype=float)
        # Prefer geometric disk area from radius (local flood-fill area often overestimates)
        geo_areas = np.pi * (radii ** 2)
        flood_areas = np.array([f["area"] for f in cell_feats], dtype=float)
        # Use the smaller of geometric vs flood so min_area is not inflated
        areas = np.minimum(geo_areas, flood_areas)
        cell_logs = np.array([f["log_response"] for f in cell_feats], dtype=float)
        bg_logs = np.array([f["log_response"] for f in bg_feats], dtype=float) if bg_feats else np.array([0.0])
        cell_snr = np.array([f["snr"] for f in cell_feats], dtype=float)

        s_lo = float(np.min(sigmas))
        s_hi = float(np.max(sigmas))
        # Wide sigma range so slightly smaller/larger cells still match
        blob_min_sigma = max(0.6, round(s_lo * 0.50, 2))
        blob_max_sigma = max(blob_min_sigma + 1.5, round(s_hi * 1.80, 2))
        blob_max_sigma = min(50.0, blob_max_sigma)
        span = blob_max_sigma - blob_min_sigma
        blob_num_sigma = int(np.clip(int(round(span * 2.8)) + 10, 12, 32))

        blob_threshold = self._calibrate_blob_threshold(cell_logs, bg_logs, recall_bias=True)

        med_snr = float(np.median(cell_snr)) if cell_snr.size else 3.0
        # Low SNR → more sensitive (lower threshold)
        if med_snr < 3.0:
            blob_threshold = max(0.008, round(blob_threshold * 0.75, 4))

        # min area from smallest sample, with generous headroom for smaller real cells
        a_min = float(np.min(areas)) if areas.size else 15.0
        a_max = float(np.max(areas)) if areas.size else 300.0
        blob_min_area = int(max(3, round(a_min * 0.25)))
        blob_max_area = int(max(blob_min_area + 20, round(a_max * 2.5)))
        blob_max_area = int(min(100000, blob_max_area))

        blob_overlap = 0.55  # slightly more permissive default
        pts = cell_pts if cell_pts is not None else [(f["x"], f["y"]) for f in cell_feats]
        if len(pts) >= 2:
            P = np.asarray(pts, dtype=float)
            nn = []
            for i in range(len(P)):
                d = np.sqrt(np.sum((P - P[i]) ** 2, axis=1))
                d[i] = np.inf
                nn.append(np.min(d))
            med_nn = float(np.median(nn))
            med_r = float(np.median(radii))
            if med_r > 0:
                if med_nn < 2.5 * med_r:
                    blob_overlap = 0.75
                elif med_nn < 3.5 * med_r:
                    blob_overlap = 0.65
                elif med_nn > 7 * med_r:
                    blob_overlap = 0.4

        # Note: circularity is not applied in the current blob drawing path, but keep mild
        blob_min_circularity = 0.4

        cell_keep = float(np.mean(cell_logs >= blob_threshold)) if cell_logs.size else 0.0
        bg_keep = float(np.mean(bg_logs >= blob_threshold)) if bg_logs.size else 0.0

        return {
            "detection_method": "blob",
            "blob_min_sigma": blob_min_sigma,
            "blob_max_sigma": blob_max_sigma,
            "blob_num_sigma": blob_num_sigma,
            "blob_threshold": float(blob_threshold),
            "blob_overlap": float(blob_overlap),
            "blob_min_area": blob_min_area,
            "blob_max_area": blob_max_area,
            "blob_min_circularity": float(blob_min_circularity),
            "min_cell_size": max(3, blob_min_area),
            "max_cell_size": max(blob_min_area + 10, blob_max_area),
            "_diagnostics": {
                "cell_radii": radii.tolist(),
                "cell_sigmas": sigmas.tolist(),
                "cell_logs": cell_logs.tolist(),
                "bg_logs": bg_logs.tolist(),
                "cell_keep_frac": cell_keep,
                "bg_keep_frac": bg_keep,
                "median_snr": med_snr,
            },
        }

    def _blob_log_sample_recovery(self, img, cell_xy, settings, max_match_factor=1.5):
        """Fraction of sample cell clicks that have a blob_log hit nearby.

        Uses the real skimage blob_log path (same as detection).
        cell_xy: list of (x, y) in the *same* coordinate system as img.
        """
        if img is None or not cell_xy:
            return 0.0, 0
        try:
            blobs = feature.blob_log(
                img,
                min_sigma=float(settings["blob_min_sigma"]),
                max_sigma=float(settings["blob_max_sigma"]),
                num_sigma=int(settings["blob_num_sigma"]),
                threshold=float(settings["blob_threshold"]),
                overlap=float(settings.get("blob_overlap", 0.5)),
                log_scale=False,
            )
        except Exception as e:
            logger.debug(f"blob_log recovery check failed: {e}")
            return 0.0, 0

        if blobs is None or len(blobs) == 0:
            return 0.0, 0

        recovered = 0
        min_area = int(settings.get("blob_min_area", 0))
        max_area = int(settings.get("blob_max_area", 10**9))
        for (x, y) in cell_xy:
            hit = False
            for by, bx, sig in blobs:
                radius = float(sig) * 1.8
                area = int(np.pi * radius * radius)
                if area < min_area or area > max_area:
                    continue
                max_dist = max(radius * max_match_factor, 6.0)
                if (float(by) - float(y)) ** 2 + (float(bx) - float(x)) ** 2 <= max_dist ** 2:
                    hit = True
                    break
            if hit:
                recovered += 1
        return recovered / float(len(cell_xy)), len(blobs)

    def _retune_threshold_for_sample_recovery(self, img, cell_xy, settings, min_recovery=1.0):
        """Lower blob_threshold until sample cells are recovered by real blob_log.

        This is the main fix for Measure Tune undercounting: LoG-at-point scores
        alone do not guarantee blob_log will detect those cells.
        """
        thr0 = float(settings["blob_threshold"])
        recovery, nblobs = self._blob_log_sample_recovery(img, cell_xy, settings)
        settings["_diagnostics"]["blob_log_recovery_before"] = recovery
        settings["_diagnostics"]["blob_log_n_before"] = nblobs

        if recovery >= min_recovery:
            settings["_diagnostics"]["blob_log_recovery"] = recovery
            settings["_diagnostics"]["blob_log_n"] = nblobs
            return settings

        # Try progressively lower thresholds
        best = dict(settings)
        best_rec = recovery
        for factor in (0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.12, 0.08):
            t = max(0.005, thr0 * factor)
            trial = dict(settings)
            trial["blob_threshold"] = t
            rec, nb = self._blob_log_sample_recovery(img, cell_xy, trial)
            if rec > best_rec or (rec >= min_recovery and t < best["blob_threshold"]):
                best = trial
                best_rec = rec
                best["_diagnostics"] = dict(settings.get("_diagnostics") or {})
                best["_diagnostics"]["blob_log_recovery"] = rec
                best["_diagnostics"]["blob_log_n"] = nb
                best["_diagnostics"]["blob_threshold_retuned_from"] = thr0
            if rec >= min_recovery:
                break

        # If still missing samples, also relax min_area once
        if best_rec < min_recovery:
            trial = dict(best)
            trial["blob_min_area"] = max(3, int(best["blob_min_area"] * 0.5))
            trial["blob_threshold"] = max(0.005, float(best["blob_threshold"]) * 0.7)
            rec, nb = self._blob_log_sample_recovery(img, cell_xy, trial)
            if rec >= best_rec:
                best = trial
                best["_diagnostics"] = dict(settings.get("_diagnostics") or {})
                best["_diagnostics"]["blob_log_recovery"] = rec
                best["_diagnostics"]["blob_log_n"] = nb
                best["_diagnostics"]["relaxed_min_area"] = True

        return best

    def _area_tune_active_bounds(self):
        """Return (min_area, max_area) from a completed Area Tune, or None."""
        at = getattr(self, "area_tune_result", None) or {}
        if not isinstance(at, dict):
            return None
        if int(at.get("n", 0) or 0) < 3 and at.get("mean_area") is None:
            return None
        try:
            if at.get("blob_min_area") is not None and at.get("blob_max_area") is not None:
                amin = int(at["blob_min_area"])
                amax = int(at["blob_max_area"])
            elif at.get("mean_area") is not None:
                mean_a = float(at["mean_area"])
                amin = int(max(1, round(0.7 * mean_a)))
                amax = int(max(amin + 1, round(1.5 * mean_a)))
            else:
                return None
            if amax <= amin:
                amax = amin + 1
            return amin, amax
        except Exception:
            return None

    def _preserve_area_tune_in_settings(self, settings):
        """Force Area Tune min/max area into a settings dict (Measure Tune must not override)."""
        if not settings:
            return settings
        bounds = self._area_tune_active_bounds()
        if bounds is None:
            return settings
        amin, amax = bounds
        settings["blob_min_area"] = amin
        settings["blob_max_area"] = amax
        # Keep legacy watershed size fields consistent if present
        if "min_cell_size" in settings:
            settings["min_cell_size"] = max(3, amin)
        if "max_cell_size" in settings:
            settings["max_cell_size"] = max(amin + 10, amax)
        settings["_area_tune_preserved"] = True
        return settings

    def _apply_blob_settings_dict(self, settings, preserve_area_tune=True):
        """Apply a settings dict onto cell_config (ignores keys starting with _).

        preserve_area_tune: if True and Area Tune was completed this session,
        never overwrite blob_min_area / blob_max_area from that calibration.
        """
        cfg = self.image_processor.cell_config
        settings = dict(settings or {})
        if preserve_area_tune:
            settings = self._preserve_area_tune_in_settings(settings)
        for k, v in settings.items():
            if k.startswith("_"):
                continue
            if not hasattr(cfg, k):
                continue
            if k in ("adaptive_enabled", "adaptive_dual_pass", "blob_reject_tissue_edge"):
                try:
                    v = int(v)
                except Exception:
                    v = 1 if v else 0
            setattr(cfg, k, v)
        # If Adaptive was turned on via preset, ensure base method is blob/dog
        if int(getattr(cfg, "adaptive_enabled", 0) or 0):
            m = (cfg.detection_method or "blob").lower().strip()
            if m in ("adaptive", "watershed", ""):
                base = (getattr(cfg, "adaptive_base_method", None) or "blob").lower()
                cfg.detection_method = base if base in ("blob", "dog", "log") else "blob"

    # ==================================================================
    # MEASURE TUNE — TP / FP / FN / TN clicks → detection parameters
    # ==================================================================

    _MT_LABELS = {
        "tp": {"name": "True Positive", "short": "TP", "color": "#00cc44",
               "hint": "Correct detection — real cell that is (or should be) counted"},
        "fp": {"name": "False Positive", "short": "FP", "color": "#ff6600",
               "hint": "Wrong detection — red mark that is NOT a real cell"},
        "fn": {"name": "False Negative", "short": "FN", "color": "#00aaff",
               "hint": "Missed cell — real cell with no detection"},
        "tn": {"name": "True Negative", "short": "TN", "color": "#999999",
               "hint": "Correct empty space — background that should stay empty"},
    }

    def start_measure_tune(self, mask_settings_window=None):
        """Interactive Measure Tune: label TP/FP/FN/TN on the current mask, derive params.

        Designed to run after Show Mask / Smart Suggest so the user can mark what
        is right and wrong on the current detection.
        """
        if self.original_background is None and self.background_image is None:
            messagebox.showerror("Measure Tune", "Please import a TIFF image first.")
            return

        if getattr(self, "area_tune_active", False):
            self._cleanup_area_tune_ui()

        if getattr(self, "splitting_cells", False) or getattr(self, "editing_mask", False):
            self.splitting_cells = False
            self.editing_mask = False

        self.measure_tune_settings_geometry = None
        if mask_settings_window is not None:
            try:
                self.measure_tune_settings_geometry = mask_settings_window.geometry()
                mask_settings_window.destroy()
            except Exception:
                pass

        try:
            img, scale = self._get_preprocessed_analysis_image(
                max_side=2200, for_detection_match=True
            )
            if img is None:
                raise RuntimeError("No image")
            self._measure_tune_img = img
            self._measure_tune_scale = scale
        except Exception as e:
            messagebox.showerror("Measure Tune", f"Could not prepare image for analysis:\n{e}")
            return

        self.measure_tune_active = True
        self.measure_tune_label = "tp"
        self.measure_tune_samples = []
        self._clear_measure_tune_markers()

        # Keep / show the detection mask so TP/FP labels can be placed on red rings.
        # Never call bare show_page() here — it clears the canvas and drops the mask.
        try:
            has_mask = (
                getattr(self, "auto_mask", None) is not None
                and not isinstance(getattr(self, "auto_mask", None), bool)
            )
            self.show_cell_mask_threshold(calculate=not has_mask)
        except Exception as e:
            logger.warning(f"Measure Tune could not display mask: {e}")
            try:
                self.show_cell_mask_threshold(calculate=True)
            except Exception:
                pass

        # Bind after mask redraw (show_page deletes canvas items but keeps bindings;
        # still re-bind so we own clicks over any residual handlers).
        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.bind("<Button-1>", self._measure_tune_click)
        self.master.bind("<Escape>", self._cancel_measure_tune)
        try:
            self.output.config(cursor="crosshair")
        except Exception:
            pass

        self._open_measure_tune_status_window()
        self._update_measure_tune_status()

        messagebox.showinfo(
            "Measure Tune (TP / FP / FN / TN)",
            "Label the current detection to refine parameters.\n\n"
            "Dual approach (recommended on mixed BG):\n"
            "  Pass 1 — precision: mark FP + TN only, then Apply\n"
            "  Pass 2 — recall: mark TP + FN on misses, then Apply again\n"
            "  Or full: mark all four classes in one go\n\n"
            "  • TP (green)  — real cell correctly detected\n"
            "  • FP (orange) — false mark (high BG, edge, junk)\n"
            "  • FN (blue)   — real cell that was missed\n"
            "  • TN (gray)   — true empty background\n\n"
            "Pick a class → click examples → Apply.\n"
            "Minimum: ≥2 should-not (FP/TN) OR ≥2 should-detect (TP/FN).\n"
            "Results are saved for Smart Suggest.",
        )

    def _open_measure_tune_status_window(self):
        try:
            if (
                self.measure_tune_status_window is not None
                and self.measure_tune_status_window.winfo_exists()
            ):
                self.measure_tune_status_window.destroy()
        except Exception:
            pass

        win = Toplevel(self.master)
        self.measure_tune_status_window = win
        win.title("Measure Tune — TP / FP / FN / TN")
        win.attributes("-topmost", "true")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._cancel_measure_tune)
        self._register_transparent_window(win)

        self.measure_tune_status_var = tk.StringVar(value="Select a class, then click the image")
        ttk.Label(
            win,
            textvariable=self.measure_tune_status_var,
            font=("Helvetica", 11, "bold"),
        ).pack(padx=14, pady=(10, 4))

        self.measure_tune_label_var = tk.StringVar(value=self.measure_tune_label)
        cls_frame = ttk.LabelFrame(win, text="Click class")
        cls_frame.pack(padx=12, pady=4, fill="x")

        def _set_label():
            self.measure_tune_label = self.measure_tune_label_var.get()
            self._update_measure_tune_status()

        for key, meta in self._MT_LABELS.items():
            ttk.Radiobutton(
                cls_frame,
                text=f"{meta['short']} — {meta['name']}",
                value=key,
                variable=self.measure_tune_label_var,
                command=_set_label,
            ).pack(anchor="w", padx=8, pady=1)

        self.measure_tune_counts_var = tk.StringVar(value="TP:0  FP:0  FN:0  TN:0")
        ttk.Label(
            win, textvariable=self.measure_tune_counts_var, font=("Helvetica", 10, "bold")
        ).pack(pady=(6, 2))

        self.measure_tune_detail_var = tk.StringVar(
            value=self._MT_LABELS["tp"]["hint"]
        )
        ttk.Label(
            win,
            textvariable=self.measure_tune_detail_var,
            font=("Helvetica", 8),
            justify=tk.CENTER,
            wraplength=320,
        ).pack(padx=12, pady=(0, 6))

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=(2, 12))
        ttk.Button(
            btn_row, text="Undo last", command=self._measure_tune_undo_last, width=11
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_row, text="Apply", command=self._finish_measure_tune, width=10
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btn_row, text="Cancel", command=self._cancel_measure_tune, width=10
        ).pack(side=tk.LEFT, padx=3)

        try:
            win.update_idletasks()
            mx = self.master.winfo_rootx() + max(40, self.master.winfo_width() - 340)
            my = self.master.winfo_rooty() + 80
            win.geometry(f"+{mx}+{my}")
        except Exception:
            pass

    def _measure_tune_counts(self):
        samples = getattr(self, "measure_tune_samples", []) or []
        c = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for s in samples:
            lab = s.get("label")
            if lab in c:
                c[lab] += 1
        return c

    def _update_measure_tune_status(self):
        if not getattr(self, "measure_tune_status_var", None):
            return
        lab = getattr(self, "measure_tune_label", "tp") or "tp"
        meta = self._MT_LABELS.get(lab, self._MT_LABELS["tp"])
        counts = self._measure_tune_counts()
        self.measure_tune_status_var.set(
            f"Click: {meta['short']} — {meta['name']}"
        )
        if self.measure_tune_counts_var is not None:
            self.measure_tune_counts_var.set(
                f"TP:{counts['tp']}  FP:{counts['fp']}  "
                f"FN:{counts['fn']}  TN:{counts['tn']}"
            )
        last = ""
        samples = getattr(self, "measure_tune_samples", []) or []
        if samples:
            f = samples[-1]["feat"]
            last = (
                f"Last [{samples[-1]['label'].upper()}]: "
                f"r≈{f['radius']:.1f}  SNR={f['snr']:.1f}  LoG={f['log_response']:.4f}"
            )
        if self.measure_tune_detail_var is not None:
            self.measure_tune_detail_var.set(last or meta["hint"])

    def _clear_measure_tune_markers(self):
        for item in getattr(self, "measure_tune_markers", []) or []:
            try:
                self.output.delete(item)
            except Exception:
                pass
        self.measure_tune_markers = []

    def _draw_measure_tune_marker(self, ix, iy, kind="tp", index=None):
        try:
            cx, cy = self._image_to_canvas(ix, iy)
            r = 9
            color = self._MT_LABELS.get(kind, {}).get("color", "#00cc44")
            short = self._MT_LABELS.get(kind, {}).get("short", "?")
            oval = self.output.create_oval(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                outline=color,
                width=2,
                tags=("measure_tune_marker",),
            )
            cross1 = self.output.create_line(
                cx - 5, cy, cx + 5, cy, fill=color, width=2, tags=("measure_tune_marker",)
            )
            cross2 = self.output.create_line(
                cx, cy - 5, cx, cy + 5, fill=color, width=2, tags=("measure_tune_marker",)
            )
            self.measure_tune_markers.extend([oval, cross1, cross2])
            label = short if index is None else f"{short}{index}"
            txt = self.output.create_text(
                cx + 12,
                cy - 12,
                text=label,
                fill=color,
                font=("Helvetica", 8, "bold"),
                tags=("measure_tune_marker",),
            )
            self.measure_tune_markers.append(txt)
        except Exception as e:
            logger.debug(f"Measure tune marker draw failed: {e}")

    def _orig_to_analysis_xy(self, x, y):
        scale = float(getattr(self, "_measure_tune_scale", 1.0) or 1.0)
        return x / scale, y / scale

    def _measure_tune_click(self, event):
        if not getattr(self, "measure_tune_active", False):
            return

        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_image(cx, cy)

        if self.original_background is not None:
            w, h = self.original_background.size
        else:
            w, h = self.background_image.size
        x, y = int(round(ix)), int(round(iy))
        if x < 0 or y < 0 or x >= w or y >= h:
            return

        img = getattr(self, "_measure_tune_img", None)
        if img is None:
            return
        ax, ay = self._orig_to_analysis_xy(x, y)

        try:
            feat = self._measure_point_features(img, ax, ay)
            scale = float(getattr(self, "_measure_tune_scale", 1.0) or 1.0)
            feat["x_orig"] = int(round(feat["x"] * scale))
            feat["y_orig"] = int(round(feat["y"] * scale))
            feat["radius"] = float(feat["radius"] * scale)
            feat["sigma"] = float(feat["sigma"] * scale)
            feat["area"] = float(feat["area"] * (scale ** 2))
            # Extra quality metrics at analysis scale for FP gates
            ay_i, ax_i = int(round(feat["y"])), int(round(feat["x"]))
            r_an = max(2, int(round(feat["radius"] / max(scale, 1e-6))))
            try:
                feat["isotropy"] = float(
                    self.image_processor._peak_isotropy(img, ay_i, ax_i, r_an)
                )
            except Exception:
                feat["isotropy"] = 1.0
            try:
                feat["local_snr"] = float(
                    self.image_processor._local_snr_at(img, ay_i, ax_i, r_an)
                )
            except Exception:
                feat["local_snr"] = float(feat.get("snr", 0))
        except Exception as e:
            logger.warning(f"Measure tune sample failed: {e}")
            messagebox.showwarning("Measure Tune", f"Could not measure that point:\n{e}")
            return

        lab = getattr(self, "measure_tune_label", "tp") or "tp"
        if lab not in self._MT_LABELS:
            lab = "tp"
        sample = {
            "label": lab,
            "feat": feat,
            "x": feat["x_orig"],
            "y": feat["y_orig"],
        }
        self.measure_tune_samples.append(sample)
        counts = self._measure_tune_counts()
        self._draw_measure_tune_marker(
            feat["x_orig"], feat["y_orig"], kind=lab, index=counts[lab]
        )
        self._update_measure_tune_status()

    def _measure_tune_undo_last(self):
        if not getattr(self, "measure_tune_active", False):
            return
        if not self.measure_tune_samples:
            return
        self.measure_tune_samples.pop()
        self._clear_measure_tune_markers()
        counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
        for s in self.measure_tune_samples:
            lab = s["label"]
            counts[lab] = counts.get(lab, 0) + 1
            self._draw_measure_tune_marker(s["x"], s["y"], kind=lab, index=counts[lab])
        self._update_measure_tune_status()

    def _cancel_measure_tune(self, event=None):
        if not getattr(self, "measure_tune_active", False):
            return "break" if event else None
        self._cleanup_measure_tune_ui()
        messagebox.showinfo("Measure Tune", "Cancelled. Blob settings were not changed.")
        try:
            self.show_mask_settings(restore_geometry=self.measure_tune_settings_geometry)
        except Exception:
            pass
        return "break" if event else None

    def _cleanup_measure_tune_ui(self):
        self.measure_tune_active = False
        # keep measure_tune_result
        try:
            self.master.unbind("<Escape>")
        except Exception:
            pass
        try:
            self.output.unbind("<Button-1>")
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.output.config(cursor="")
        except Exception:
            pass
        self._clear_measure_tune_markers()
        try:
            if (
                self.measure_tune_status_window is not None
                and self.measure_tune_status_window.winfo_exists()
            ):
                self.measure_tune_status_window.destroy()
        except Exception:
            pass
        self.measure_tune_status_window = None
        self._measure_tune_img = None
        self.measure_tune_samples = []

    def _measure_tune_split_feats(self, samples):
        """Split samples into should-detect (TP+FN) vs should-not (FP+TN)."""
        pos, neg = [], []
        by = {"tp": [], "fp": [], "fn": [], "tn": []}
        for s in samples:
            lab = s.get("label")
            f = s.get("feat")
            if f is None or lab not in by:
                continue
            by[lab].append(f)
            if lab in ("tp", "fn"):
                pos.append(f)
            else:
                neg.append(f)
        return pos, neg, by

    def _refine_settings_from_confusion(self, settings, by_label):
        """Adjust SNR / packing / quality gates from FP vs FN patterns."""
        cfg = self.image_processor.cell_config
        tp, fp, fn, tn = by_label["tp"], by_label["fp"], by_label["fn"], by_label["tn"]
        n_fp, n_fn = len(fp), len(fn)
        n_tp, n_tn = len(tp), len(tn)

        # Start from current quality defaults if not in settings
        snr = float(getattr(cfg, "blob_min_local_snr", 0.0) or 0.0)
        pack = float(getattr(cfg, "adaptive_packing", 0.5) or 0.5)
        free = float(getattr(cfg, "blob_free_space", 0.45) or 0.45)
        bgr = float(getattr(cfg, "blob_bg_relative", 0.0) or 0.0)
        iso = float(getattr(cfg, "blob_min_isotropy", 0.0) or 0.0)
        circ = float(getattr(cfg, "blob_min_circularity", 0.0) or 0.0)

        # False positives → stricter quality / SNR
        if n_fp >= 2:
            fp_snr = np.array([f.get("local_snr", f.get("snr", 0)) for f in fp], dtype=float)
            tp_snr = np.array(
                [f.get("local_snr", f.get("snr", 0)) for f in (tp or fn)], dtype=float
            )
            if tp_snr.size and fp_snr.size:
                # Sit between FP median and TP median SNR
                target = 0.5 * (float(np.median(fp_snr)) + float(np.percentile(tp_snr, 20)))
                snr = max(snr, min(3.5, max(1.2, target)))
            else:
                snr = max(snr, 1.8)
            bgr = max(bgr, 0.10)
            iso = max(iso, 0.42)
            circ = max(circ, 0.32)
            settings["blob_reject_tissue_edge"] = 1
            # Slight thr raise if many FPs
            if n_fp >= n_tp + n_fn and n_fp >= 3:
                settings["blob_threshold"] = float(
                    min(0.2, settings.get("blob_threshold", 0.05) * 1.1 + 0.005)
                )

        # False negatives → more sensitive / denser packing
        if n_fn >= 2:
            settings["blob_threshold"] = float(
                max(0.01, settings.get("blob_threshold", 0.05) * 0.85)
            )
            if snr > 2.0:
                snr = max(1.4, snr - 0.5)
            pack = max(pack, 0.8)
            free = min(free, 0.25)
            settings["adaptive_enabled"] = 1
            settings["adaptive_dual_pass"] = 1
            settings["adaptive_sensitivity"] = min(
                float(getattr(cfg, "adaptive_sensitivity", 1.0) or 1.0), 0.95
            )

        # Both FP and FN → mixed recipe
        if n_fp >= 2 and n_fn >= 2:
            snr = float(np.clip(snr if snr > 0 else 1.9, 1.5, 2.3))
            pack = max(pack, 0.75)
            free = min(free, 0.28)
            settings["adaptive_enabled"] = 1
            settings["adaptive_dual_pass"] = 1

        # Plenty of TP only → keep recall bias, mild quality
        if n_tp >= 3 and n_fp == 0 and n_fn == 0 and n_tn >= 2:
            if snr <= 0:
                snr = 1.2

        settings["blob_min_local_snr"] = round(float(snr), 2)
        settings["blob_bg_relative"] = round(float(bgr), 3)
        settings["blob_min_isotropy"] = round(float(iso), 2)
        settings["blob_min_circularity"] = round(float(circ), 2)
        settings["adaptive_packing"] = round(float(pack), 2)
        settings["blob_free_space"] = round(float(free), 2)
        return settings

    def _snapshot_cell_config_settings(self):
        """Copy current cell_config fields into a plain settings dict."""
        cfg = self.image_processor.cell_config
        out = {}
        for k, v in cfg.__dict__.items():
            if k.startswith("_"):
                continue
            out[k] = v
        out["_diagnostics"] = {}
        return out

    def _finish_measure_tune(self):
        """Derive and apply blob settings from TP/FP/FN/TN samples.

        Supports dual-pass workflows:
          - Precision pass: FP+TN only (tighten; reject high-BG junk)
          - Recall pass: TP+FN only (recover missed cells)
          - Full pass: both sides (≥2 pos and ≥2 neg)
        """
        samples = list(getattr(self, "measure_tune_samples", []) or [])
        geom = self.measure_tune_settings_geometry
        pos, neg, by = self._measure_tune_split_feats(samples)
        counts = self._measure_tune_counts()
        n_pos, n_neg = len(pos), len(neg)
        n_fp = counts.get("fp", 0)
        n_tn = counts.get("tn", 0)
        n_tp = counts.get("tp", 0)
        n_fn = counts.get("fn", 0)

        # Modes for dual approach (first pass often FP+TN only)
        precision_only = n_neg >= 2 and n_pos < 2  # FP/TN pass
        recall_only = n_pos >= 2 and n_neg < 2     # TP/FN pass
        full_pass = n_pos >= 2 and n_neg >= 2

        if not (precision_only or recall_only or full_pass):
            messagebox.showwarning(
                "Measure Tune",
                "Not enough samples to apply.\n\n"
                "Dual approach:\n"
                "  • Pass 1 (kill FPs): mark ≥2 FP and/or TN  (TP/FN optional)\n"
                "  • Pass 2 (recover cells): mark ≥2 TP and/or FN\n"
                "  • Or full: ≥2 should-detect (TP/FN) and ≥2 should-not (FP/TN)\n\n"
                f"Current — TP:{n_tp} FP:{n_fp} FN:{n_fn} TN:{n_tn}",
            )
            return

        if precision_only and n_fp < 1 and n_tn < 2:
            messagebox.showwarning(
                "Measure Tune",
                "Precision pass needs at least 1 FP (false mark) or 2 TN samples.\n\n"
                f"Current — TP:{n_tp} FP:{n_fp} FN:{n_fn} TN:{n_tn}",
            )
            return

        mode_name = (
            "precision (FP/TN)"
            if precision_only
            else ("recall (TP/FN)" if recall_only else "full (TP/FP/FN/TN)")
        )

        progress = None
        try:
            progress = self._show_busy_dialog("Measure Tune")
            progress.set_progress(5, f"Deriving parameters ({mode_name})…")
        except Exception:
            progress = None

        cell_feats = pos
        bg_feats = neg
        cell_pts = [(f["x_orig"], f["y_orig"]) for f in cell_feats]

        settings = None
        try:
            if full_pass:
                settings = self._derive_blob_settings_from_features(
                    cell_feats, bg_feats, cell_pts=cell_pts
                )
            elif recall_only:
                # Size/sigma/thr from positives; no negatives for separation
                settings = self._derive_blob_settings_from_features(
                    cell_feats, bg_feats or [], cell_pts=cell_pts
                )
            else:
                # Precision-only: start from current config; tighten using FP/TN
                settings = self._snapshot_cell_config_settings()
        except Exception as e:
            if progress:
                try:
                    progress.close()
                except Exception:
                    pass
            messagebox.showerror("Measure Tune", f"Failed to derive settings:\n{e}")
            return

        if not settings:
            if progress:
                try:
                    progress.close()
                except Exception:
                    pass
            messagebox.showerror("Measure Tune", "Failed to derive settings from samples.")
            return

        if progress:
            progress.set_progress(25, "Calibrating threshold (local LoG)…")

        try:
            img, scale = self._get_preprocessed_analysis_image(
                max_side=1200, for_detection_match=True
            )
            if img is not None:
                smin = max(
                    0.5,
                    float(settings.get("blob_min_sigma", 1.5)) / scale,
                )
                smax = max(
                    smin + 0.5,
                    float(settings.get("blob_max_sigma", 12.0)) / scale,
                )
                probe = np.unique(np.round(np.linspace(smin, smax, 8), 2))
                cell_logs2, bg_logs2 = [], []
                for f in cell_feats:
                    ax, ay = f["x_orig"] / scale, f["y_orig"] / scale
                    _, lr = self._best_sigma_at_point(img, ay, ax, probe)
                    cell_logs2.append(lr)
                if progress:
                    progress.set_progress(45, "Scoring negative samples…")
                for f in bg_feats:
                    ax, ay = f["x_orig"] / scale, f["y_orig"] / scale
                    _, lr = self._best_sigma_at_point(img, ay, ax, probe)
                    bg_logs2.append(lr)

                if "_diagnostics" not in settings or not isinstance(
                    settings.get("_diagnostics"), dict
                ):
                    settings["_diagnostics"] = {}

                if full_pass and cell_logs2 and bg_logs2:
                    recall_bias = counts["fn"] >= counts["fp"]
                    thr2 = self._calibrate_blob_threshold(
                        cell_logs2, bg_logs2, recall_bias=recall_bias
                    )
                    settings["blob_threshold"] = thr2
                elif precision_only and bg_logs2:
                    # Raise thr so most FP LoG responses fall below it
                    fp_logs = []
                    for f in by.get("fp") or []:
                        ax, ay = f["x_orig"] / scale, f["y_orig"] / scale
                        _, lr = self._best_sigma_at_point(img, ay, ax, probe)
                        fp_logs.append(lr)
                    if not fp_logs:
                        fp_logs = list(bg_logs2)
                    fp_arr = np.asarray(fp_logs, dtype=float)
                    # Sit above ~60–75% of FP responses
                    target = float(np.percentile(fp_arr, 70))
                    cur = float(settings.get("blob_threshold", 0.05) or 0.05)
                    # Map raw LoG to blob_threshold operating range if huge
                    if target > 0.5:
                        scale_ref = max(float(np.percentile(np.abs(fp_arr), 75)), 1e-6)
                        target = target / scale_ref * 0.1
                    thr2 = max(cur, min(0.25, max(0.01, target * 1.05)))
                    # Also nudge up from current if FPs still strong
                    thr2 = float(np.clip(max(thr2, cur * 1.08 + 0.005), 0.01, 0.25))
                    settings["blob_threshold"] = round(thr2, 4)
                elif recall_only and cell_logs2:
                    # Lower thr below weakest positive
                    c_min = float(np.min(cell_logs2))
                    cur = float(settings.get("blob_threshold", 0.05) or 0.05)
                    thr2 = self._calibrate_blob_threshold(
                        cell_logs2, bg_logs2 or [0.0], recall_bias=True
                    )
                    thr2 = min(thr2, cur * 0.9)
                    settings["blob_threshold"] = float(np.clip(thr2, 0.008, 0.2))

                settings["_diagnostics"]["cell_logs"] = cell_logs2
                settings["_diagnostics"]["bg_logs"] = bg_logs2
                settings["_diagnostics"]["mode"] = mode_name
                if cell_logs2:
                    settings["_diagnostics"]["cell_keep_frac"] = float(
                        np.mean(
                            np.array(cell_logs2) >= float(settings["blob_threshold"])
                        )
                    )
                else:
                    settings["_diagnostics"]["cell_keep_frac"] = 0.0
                if bg_logs2:
                    settings["_diagnostics"]["bg_keep_frac"] = float(
                        np.mean(
                            np.array(bg_logs2) >= float(settings["blob_threshold"])
                        )
                    )
                else:
                    settings["_diagnostics"]["bg_keep_frac"] = 0.0
                settings["_diagnostics"]["blob_log_recovery"] = settings[
                    "_diagnostics"
                ]["cell_keep_frac"]
                settings["_diagnostics"]["skipped_fullres_retune"] = True
        except Exception as e:
            logger.warning(f"Measure tune second-pass calibration issue: {e}", exc_info=True)

        if progress:
            progress.set_progress(70, "Applying FP/FN quality adjustments…")

        try:
            settings = self._refine_settings_from_confusion(settings, by)
            # Precision-only: force quality gates even without TP
            if precision_only:
                cfg = self.image_processor.cell_config
                snr = float(settings.get("blob_min_local_snr", 0) or 0)
                settings["blob_min_local_snr"] = round(max(snr, 1.8), 2)
                settings["blob_bg_relative"] = round(
                    max(float(settings.get("blob_bg_relative", 0) or 0), 0.12), 3
                )
                settings["blob_min_isotropy"] = round(
                    max(float(settings.get("blob_min_isotropy", 0) or 0), 0.42), 2
                )
                settings["blob_min_circularity"] = round(
                    max(float(settings.get("blob_min_circularity", 0) or 0), 0.32), 2
                )
                settings["blob_reject_tissue_edge"] = 1
                settings["adaptive_enabled"] = 1
                settings["adaptive_dual_pass"] = 1
                # Mild thr raise from current if not already raised
                cur_thr = float(getattr(cfg, "blob_threshold", 0.05) or 0.05)
                settings["blob_threshold"] = round(
                    max(float(settings.get("blob_threshold", cur_thr)), cur_thr * 1.05),
                    4,
                )
            if recall_only:
                settings["adaptive_enabled"] = 1
                settings["adaptive_dual_pass"] = 1
                settings["adaptive_packing"] = round(
                    max(float(settings.get("adaptive_packing", 0.5) or 0.5), 0.8), 2
                )
                settings["blob_free_space"] = round(
                    min(float(settings.get("blob_free_space", 0.45) or 0.45), 0.25), 2
                )
                snr = float(settings.get("blob_min_local_snr", 0) or 0)
                if snr > 2.2:
                    settings["blob_min_local_snr"] = round(max(1.5, snr - 0.5), 2)
        except Exception as e:
            logger.warning(f"Measure tune confusion refine failed: {e}", exc_info=True)

        # Area Tune wins for size bounds — Measure Tune must not overwrite them
        settings = self._preserve_area_tune_in_settings(settings)
        area_preserved = bool(settings.get("_area_tune_preserved"))

        self.measure_tune_result = {
            "counts": dict(counts),
            "n_pos": n_pos,
            "n_neg": n_neg,
            "mode": mode_name,
            "settings": {
                k: v
                for k, v in settings.items()
                if not str(k).startswith("_")
            },
            "blob_threshold": settings.get("blob_threshold"),
            "blob_min_sigma": settings.get("blob_min_sigma"),
            "blob_max_sigma": settings.get("blob_max_sigma"),
            # Prefer Area Tune areas in the stored result so Smart Suggest agrees
            "blob_min_area": settings.get("blob_min_area"),
            "blob_max_area": settings.get("blob_max_area"),
            "blob_min_local_snr": settings.get("blob_min_local_snr"),
            "area_tune_preserved": area_preserved,
            "source": "measure_tune_tp_fp_fn_tn",
        }

        if progress:
            progress.set_progress(85, "Updating detection settings…")

        self._cleanup_measure_tune_ui()
        self._apply_blob_settings_dict(settings, preserve_area_tune=True)
        diag = settings.get("_diagnostics", {}) or {}

        logger.info(
            "Measure Tune applied mode=%s counts=%s thr=%.4f snr=%.2f area_tune_preserved=%s",
            mode_name,
            counts,
            settings.get("blob_threshold", 0),
            settings.get("blob_min_local_snr", 0),
            area_preserved,
        )

        if progress:
            progress.set_progress(90, "Refreshing mask…")

        try:
            self.show_cell_mask_threshold(calculate=True)
        except Exception as e:
            logger.warning(f"Measure Tune mask refresh failed: {e}")

        if progress:
            try:
                progress.set_progress(100, "Done")
                progress.close()
            except Exception:
                pass

        next_hint = ""
        if precision_only:
            next_hint = (
                "\n\nNext (optional): run Measure Tune again and mark TP/FN on "
                "missed cells to recover dark clusters (recall pass)."
            )
        elif recall_only:
            next_hint = (
                "\n\nTip: if high-BG noise returns, run a precision pass (FP/TN only)."
            )

        summary = (
            f"Measure Tune complete — {mode_name} pass.\n\n"
            f"Samples:  TP={n_tp}  FP={n_fp}  FN={n_fn}  TN={n_tn}\n\n"
            f"Threshold: {settings.get('blob_threshold')}\n"
            f"Sigma: {settings.get('blob_min_sigma')} – {settings.get('blob_max_sigma')}\n"
            f"Area: {settings.get('blob_min_area')} – {settings.get('blob_max_area')}"
            + ("  (kept from Area Tune)" if area_preserved else "")
            + "\n"
            f"Local SNR: {settings.get('blob_min_local_snr')}\n"
            f"BG relative: {settings.get('blob_bg_relative')}  "
            f"Isotropy: {settings.get('blob_min_isotropy')}\n"
            f"Packing: {settings.get('adaptive_packing')}  "
            f"Free space: {settings.get('blob_free_space')}\n\n"
            f"Validation: pos LoG keep {100 * diag.get('cell_keep_frac', 0):.0f}%  |  "
            f"neg above thr {100 * diag.get('bg_keep_frac', 0):.0f}%\n"
            f"{next_hint}"
        )
        messagebox.showinfo("Measure Tune Results", summary)

        try:
            self.show_mask_settings(restore_geometry=geom)
        except Exception:
            pass

    # ==================================================================
    # AREA TUNE — draw one diameter line per cell (N times) → blob area range
    # ==================================================================

    def start_area_tune(self, mask_settings_window=None):
        """Interactive Area Tune: draw one diameter line across each of N cells."""
        if self.original_background is None and self.background_image is None:
            messagebox.showerror("Area Tune", "Please import a TIFF image first.")
            return

        if getattr(self, "measure_tune_active", False):
            self._cleanup_measure_tune_ui()

        if getattr(self, "splitting_cells", False) or getattr(self, "editing_mask", False):
            self.splitting_cells = False
            self.editing_mask = False

        self.area_tune_settings_geometry = None
        if mask_settings_window is not None:
            try:
                self.area_tune_settings_geometry = mask_settings_window.geometry()
                mask_settings_window.destroy()
            except Exception:
                pass

        n = int(getattr(self, "area_tune_n_cells", 10) or 10)
        self.area_tune_n_cells = max(2, n)
        self.area_tune_active = True
        self.area_tune_start = None
        self.area_tune_end = None
        self.area_tune_measurements = []
        self._clear_area_tune_graphics()

        self.output.unbind("<Button-1>")
        self.output.unbind("<B1-Motion>")
        self.output.unbind("<ButtonRelease-1>")
        self.output.bind("<Button-1>", self._area_tune_press)
        self.output.bind("<B1-Motion>", self._area_tune_drag)
        self.output.bind("<ButtonRelease-1>", self._area_tune_release)
        self.master.bind("<Escape>", self._cancel_area_tune)
        try:
            self.output.config(cursor="crosshair")
        except Exception:
            pass

        self._open_area_tune_status_window()
        self._update_area_tune_status()
        try:
            self.show_page()
        except Exception:
            pass

        messagebox.showinfo(
            "Area Tune",
            "How to use Area Tune:\n\n"
            f"Draw {self.area_tune_n_cells} separate lines — one line per cell.\n\n"
            "For each cell:\n"
            "  1. Click on one edge of the cell.\n"
            "  2. Drag across the cell to the opposite edge.\n"
            "  3. Release to record that cell’s diameter.\n\n"
            f"After {self.area_tune_n_cells} lines, BARCC averages the measured "
            "areas (π·r² from each diameter) and sets:\n"
            "  • blob_min_area = 0.7 × mean area\n"
            "  • blob_max_area = 1.5 × mean area\n\n"
            "Tips:\n"
            "• Measure typical cells, not only the largest or smallest.\n"
            "• Use Undo last if a line is wrong.\n"
            "• Esc cancels without changing settings.",
        )

    def _open_area_tune_status_window(self):
        try:
            if (
                self.area_tune_status_window is not None
                and self.area_tune_status_window.winfo_exists()
            ):
                self.area_tune_status_window.destroy()
        except Exception:
            pass

        win = Toplevel(self.master)
        self.area_tune_status_window = win
        win.title("Area Tune")
        win.attributes("-topmost", "true")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._cancel_area_tune)
        self._register_transparent_window(win)

        self.area_tune_status_var = tk.StringVar(value="Cell 1 of 10")
        ttk.Label(
            win,
            textvariable=self.area_tune_status_var,
            font=("Helvetica", 11, "bold"),
        ).pack(padx=16, pady=(12, 4))
        self.area_tune_detail_var = tk.StringVar(
            value="Drag one line across this cell (edge → edge)"
        )
        ttk.Label(
            win,
            textvariable=self.area_tune_detail_var,
            font=("Helvetica", 8),
            justify=tk.CENTER,
        ).pack(padx=16, pady=(0, 6))

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=(0, 12))
        ttk.Button(
            btn_row, text="Undo last", command=self._area_tune_undo_last, width=12
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btn_row, text="Cancel", command=self._cancel_area_tune, width=10
        ).pack(side=tk.LEFT, padx=4)

        try:
            win.update_idletasks()
            mx = self.master.winfo_rootx() + max(40, self.master.winfo_width() - 300)
            my = self.master.winfo_rooty() + 80
            win.geometry(f"+{mx}+{my}")
        except Exception:
            pass

    def _update_area_tune_status(self):
        if not getattr(self, "area_tune_status_var", None):
            return
        n = int(getattr(self, "area_tune_n_cells", 10) or 10)
        done = len(getattr(self, "area_tune_measurements", []) or [])
        if done >= n:
            self.area_tune_status_var.set("Done")
            return
        self.area_tune_status_var.set(f"Cell {done + 1} of {n} — draw diameter line")
        detail = "Drag edge → edge across one cell, then release"
        if done > 0:
            last = self.area_tune_measurements[-1]
            detail = (
                f"Last: d={last['diameter']:.1f} px, area={last['area']:.0f} px²  "
                f"({done}/{n} saved)"
            )
        if getattr(self, "area_tune_detail_var", None) is not None:
            self.area_tune_detail_var.set(detail)

    def _clear_area_tune_graphics(self):
        """Remove all area-tune canvas items (committed + rubber band)."""
        for item in getattr(self, "area_tune_markers", []) or []:
            try:
                self.output.delete(item)
            except Exception:
                pass
        self.area_tune_markers = []
        for item in getattr(self, "area_tune_line_ids", []) or []:
            try:
                self.output.delete(item)
            except Exception:
                pass
        self.area_tune_line_ids = []
        if getattr(self, "area_tune_current_line_id", None) is not None:
            try:
                self.output.delete(self.area_tune_current_line_id)
            except Exception:
                pass
        self.area_tune_current_line_id = None

    def _clear_area_tune_rubberband(self):
        if getattr(self, "area_tune_current_line_id", None) is not None:
            try:
                self.output.delete(self.area_tune_current_line_id)
            except Exception:
                pass
        self.area_tune_current_line_id = None

    def _area_tune_event_xy(self, event):
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        ix, iy = self._canvas_to_image(cx, cy)
        if self.original_background is not None:
            w, h = self.original_background.size
        elif self.background_image is not None:
            w, h = self.background_image.size
        else:
            return None
        ix = int(np.clip(ix, 0, w - 1))
        iy = int(np.clip(iy, 0, h - 1))
        return ix, iy

    def _area_tune_press(self, event):
        if not getattr(self, "area_tune_active", False):
            return
        n = int(getattr(self, "area_tune_n_cells", 10) or 10)
        if len(self.area_tune_measurements) >= n:
            return
        xy = self._area_tune_event_xy(event)
        if xy is None:
            return
        self.area_tune_start = xy
        self.area_tune_end = xy
        self._clear_area_tune_rubberband()
        self._draw_area_tune_rubberband()
        if self.area_tune_status_var is not None:
            done = len(self.area_tune_measurements)
            self.area_tune_status_var.set(
                f"Cell {done + 1} of {n} — drag across the cell…"
            )

    def _area_tune_drag(self, event):
        if not getattr(self, "area_tune_active", False):
            return
        if self.area_tune_start is None:
            return
        xy = self._area_tune_event_xy(event)
        if xy is None:
            return
        self.area_tune_end = xy
        self._draw_area_tune_rubberband()
        x0, y0 = self.area_tune_start
        x1, y1 = self.area_tune_end
        length = float(np.hypot(x1 - x0, y1 - y0))
        if self.area_tune_detail_var is not None:
            area = float(np.pi * (length / 2.0) ** 2)
            self.area_tune_detail_var.set(
                f"Diameter {length:.1f} px  ·  area ≈ {area:.0f} px²"
            )

    def _area_tune_release(self, event):
        if not getattr(self, "area_tune_active", False):
            return
        if self.area_tune_start is None:
            return
        xy = self._area_tune_event_xy(event)
        if xy is not None:
            self.area_tune_end = xy
        self._commit_area_tune_line()

    def _draw_area_tune_rubberband(self):
        if self.area_tune_start is None or self.area_tune_end is None:
            return
        x0, y0 = self.area_tune_start
        x1, y1 = self.area_tune_end
        try:
            c0 = self._image_to_canvas(x0, y0)
            c1 = self._image_to_canvas(x1, y1)
            if self.area_tune_current_line_id is not None:
                try:
                    self.output.coords(
                        self.area_tune_current_line_id,
                        c0[0],
                        c0[1],
                        c1[0],
                        c1[1],
                    )
                    return
                except Exception:
                    self.area_tune_current_line_id = None
            self.area_tune_current_line_id = self.output.create_line(
                c0[0],
                c0[1],
                c1[0],
                c1[1],
                fill="#00e5ff",
                width=3,
                tags=("area_tune_line",),
            )
        except Exception as e:
            logger.debug(f"Area tune rubberband draw failed: {e}")

    def _draw_committed_area_tune_line(self, start, end, index):
        """Draw a permanent cyan line + index label for a completed cell measurement."""
        x0, y0 = start
        x1, y1 = end
        try:
            c0 = self._image_to_canvas(x0, y0)
            c1 = self._image_to_canvas(x1, y1)
            line = self.output.create_line(
                c0[0],
                c0[1],
                c1[0],
                c1[1],
                fill="#00cc88",
                width=2,
                tags=("area_tune_line",),
            )
            self.area_tune_line_ids.append(line)
            for (cx, cy) in (c0, c1):
                r = 4
                dot = self.output.create_oval(
                    cx - r,
                    cy - r,
                    cx + r,
                    cy + r,
                    fill="#00cc88",
                    outline="#003322",
                    width=1,
                    tags=("area_tune_marker",),
                )
                self.area_tune_markers.append(dot)
            mx = (c0[0] + c1[0]) / 2.0
            my = (c0[1] + c1[1]) / 2.0
            txt = self.output.create_text(
                mx,
                my - 10,
                text=str(index),
                fill="#00ffaa",
                font=("Helvetica", 9, "bold"),
                tags=("area_tune_marker",),
            )
            self.area_tune_markers.append(txt)
        except Exception as e:
            logger.debug(f"Area tune committed line draw failed: {e}")

    def _commit_area_tune_line(self):
        """Accept the current drag as one cell diameter measurement."""
        start = self.area_tune_start
        end = self.area_tune_end
        n = int(getattr(self, "area_tune_n_cells", 10) or 10)
        n = max(2, n)

        self._clear_area_tune_rubberband()
        self.area_tune_start = None
        self.area_tune_end = None

        if start is None or end is None:
            self._update_area_tune_status()
            return

        x0, y0 = start
        x1, y1 = end
        diameter = float(np.hypot(x1 - x0, y1 - y0))

        # One cell diameter should be at least a few pixels
        if diameter < 3.0:
            if self.area_tune_detail_var is not None:
                self.area_tune_detail_var.set(
                    "Line too short — drag edge-to-edge across one cell"
                )
            self._update_area_tune_status()
            return

        area = float(np.pi * (diameter / 2.0) ** 2)
        self.area_tune_measurements.append(
            {
                "diameter": diameter,
                "area": area,
                "start": (x0, y0),
                "end": (x1, y1),
            }
        )
        idx = len(self.area_tune_measurements)
        self._draw_committed_area_tune_line(start, end, idx)
        self._update_area_tune_status()

        if len(self.area_tune_measurements) >= n:
            self._finish_area_tune()

    def _area_tune_undo_last(self):
        if not getattr(self, "area_tune_active", False):
            return
        if not self.area_tune_measurements:
            return
        self.area_tune_measurements.pop()
        # Rebuild graphics from remaining measurements
        self._clear_area_tune_graphics()
        for i, m in enumerate(self.area_tune_measurements, 1):
            self._draw_committed_area_tune_line(m["start"], m["end"], i)
        self._update_area_tune_status()

    def _cancel_area_tune(self, event=None):
        if not getattr(self, "area_tune_active", False):
            return "break" if event else None
        self._cleanup_area_tune_ui()
        messagebox.showinfo("Area Tune", "Cancelled. Blob area settings were not changed.")
        try:
            self.show_mask_settings(restore_geometry=self.area_tune_settings_geometry)
        except Exception:
            pass
        return "break" if event else None

    def _cleanup_area_tune_ui(self):
        self.area_tune_active = False
        self.area_tune_start = None
        self.area_tune_end = None
        self.area_tune_measurements = []
        # Keep self.area_tune_result for Smart Suggest
        try:
            self.master.unbind("<Escape>")
        except Exception:
            pass
        try:
            self.output.unbind("<Button-1>")
            self.output.unbind("<B1-Motion>")
            self.output.unbind("<ButtonRelease-1>")
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.output.config(cursor="")
        except Exception:
            pass
        self._clear_area_tune_graphics()
        try:
            if (
                self.area_tune_status_window is not None
                and self.area_tune_status_window.winfo_exists()
            ):
                self.area_tune_status_window.destroy()
        except Exception:
            pass
        self.area_tune_status_window = None

    def _finish_area_tune(self):
        """Average the N per-cell diameter lines and set blob min/max area."""
        measurements = list(getattr(self, "area_tune_measurements", []) or [])
        n_target = int(getattr(self, "area_tune_n_cells", 10) or 10)
        geom = self.area_tune_settings_geometry

        if len(measurements) < max(2, min(3, n_target)):
            self._cleanup_area_tune_ui()
            messagebox.showwarning(
                "Area Tune",
                f"Need {n_target} cell lines; only got {len(measurements)}.",
            )
            try:
                self.show_mask_settings(restore_geometry=geom)
            except Exception:
                pass
            return

        diameters = np.array([m["diameter"] for m in measurements], dtype=np.float64)
        areas = np.array([m["area"] for m in measurements], dtype=np.float64)
        mean_diameter = float(np.mean(diameters))
        median_diameter = float(np.median(diameters))
        mean_area = float(np.mean(areas))
        median_area = float(np.median(areas))
        # Use mean area for the 0.7–1.5× range (user-requested basis)
        ref_area = mean_area
        min_area = int(max(1, round(0.7 * ref_area)))
        max_area = int(max(min_area + 1, round(1.5 * ref_area)))

        # Persist for Smart Suggest (survives UI cleanup)
        rscale = float(
            getattr(self.image_processor.cell_config, "blob_radius_scale", 1.8) or 1.8
        )
        # sigma ≈ radius / radius_scale = (d/2) / rscale
        mean_sigma = max(0.8, (mean_diameter / 2.0) / max(rscale, 0.5))
        min_sigma_at = max(0.8, float(np.percentile(diameters, 10) / 2.0) / max(rscale, 0.5) * 0.85)
        max_sigma_at = max(min_sigma_at + 0.5, float(np.percentile(diameters, 90) / 2.0) / max(rscale, 0.5) * 1.15)
        self.area_tune_result = {
            "n": len(measurements),
            "diameters": [float(d) for d in diameters],
            "areas": [float(a) for a in areas],
            "mean_diameter": mean_diameter,
            "median_diameter": median_diameter,
            "mean_area": mean_area,
            "median_area": median_area,
            "blob_min_area": min_area,
            "blob_max_area": max_area,
            "mean_sigma": round(mean_sigma, 2),
            "blob_min_sigma": round(min_sigma_at, 2),
            "blob_max_sigma": round(max_sigma_at, 2),
            "source": "area_tune",
        }

        cfg = self.image_processor.cell_config
        old_min = int(cfg.blob_min_area)
        old_max = int(cfg.blob_max_area)
        cfg.blob_min_area = min_area
        cfg.blob_max_area = max_area

        diam_list = ", ".join(f"{d:.1f}" for d in diameters)
        area_list = ", ".join(f"{a:.0f}" for a in areas)

        self._cleanup_area_tune_ui()

        logger.info(
            "Area Tune: n=%d mean_d=%.2f mean_area=%.1f → min=%d max=%d (saved for Smart Suggest)",
            len(measurements),
            mean_diameter,
            mean_area,
            min_area,
            max_area,
        )

        summary = (
            "Area Tune complete — blob area range updated.\n\n"
            f"Cells measured:  {len(measurements)}\n"
            f"Diameters (px):  {diam_list}\n"
            f"Areas (px²):  {area_list}\n\n"
            f"Mean diameter:  {mean_diameter:.2f} px  (median {median_diameter:.2f})\n"
            f"Mean area:  {mean_area:.1f} px²  (median {median_area:.1f})\n\n"
            f"blob_min_area:  {old_min}  →  {min_area}   (0.7 × mean area)\n"
            f"blob_max_area:  {old_max}  →  {max_area}   (1.5 × mean area)\n\n"
            "These measures are kept for Smart Suggest on this session.\n"
            "Mask will refresh and Mask Settings will reopen."
        )
        messagebox.showinfo("Area Tune Results", summary)

        try:
            self.show_cell_mask_threshold(calculate=True)
        except Exception as e:
            logger.warning(f"Area Tune mask refresh failed: {e}")
        try:
            self.show_mask_settings(restore_geometry=geom)
        except Exception:
            pass

    # ==================================================================
    # SMART SUGGEST — multi-scale LoG analysis of the whole image
    # ==================================================================

    def _analyze_current_detection(self, progress=None):
        """Analyze image + current detection; propose coordinated blob settings.

        Improvements:
        - Counts real objects (connected components), not mask pixels
        - Multi-scale LoG peak discovery for natural cell scale / density
        - Detects under- and over-detection relative to LoG evidence
        - Suggests coherent parameter groups

        progress: optional busy dialog with .set_progress(percent, message)
        """
        def _prog(pct, msg=None):
            if progress is None:
                return
            try:
                progress.set_progress(pct, msg)
            except Exception:
                pass

        bg_src = self._working_background_pil()
        if bg_src is None:
            self._last_smart_suggest_error = (
                "No TIFF image is available for analysis "
                "(original_background and background_image are both empty)."
            )
            return None

        cfg = self.image_processor.cell_config
        pcfg = self.image_processor.preprocess_config

        _prog(5, "Preparing preprocessed image…")
        img, scale = self._get_preprocessed_analysis_image(max_side=1200)
        if img is None:
            self._last_smart_suggest_error = (
                "Preprocessing produced an empty image. Check Mask Settings preprocess options."
            )
            return None
        h, w = img.shape
        mp = (h * w) / 1_000_000.0
        orig_mp = (bg_src.size[0] * bg_src.size[1]) / 1e6

        _prog(15, "Running current cell detection…")
        try:
            bg = bg_src.convert("L")
            _, auto_labels = binary_mask_cell_count(bg, processor=self.image_processor)
            current_mask = np.asarray(auto_labels, dtype=bool).squeeze()
        except Exception as e:
            logger.error(f"Analysis failed during detection: {e}", exc_info=True)
            self._last_smart_suggest_error = (
                f"Cell detection failed during analysis ({cfg.detection_method}):\n{e}"
            )
            return None

        _prog(35, "Measuring detected objects…")
        obj = self._count_mask_objects(current_mask)
        n_det = obj["n"]
        density = n_det / max(orig_mp, 1e-6)

        smin = max(0.8, float(cfg.blob_min_sigma) / scale * 0.7)
        smax = max(smin + 1.0, float(cfg.blob_max_sigma) / scale * 1.2)
        smax = min(smax, 25.0)
        _prog(40, "Building multi-scale LoG…")
        log_max, best_sigma, _sigmas = self._log_scale_space_max(
            img, min_sigma=smin, max_sigma=smax, num_sigma=12,
            progress_cb=_prog, progress_start=40, progress_end=75,
        )

        _prog(78, "Finding LoG peaks…")
        log_bg = float(np.median(log_max))
        log_mad = float(np.median(np.abs(log_max - log_bg))) + 1e-8
        peak_thr_strict = log_bg + 6.0 * 1.4826 * log_mad
        peak_thr_loose = log_bg + 3.5 * 1.4826 * log_mad

        typ_r_an = max(2.0, (obj["median_radius"] / scale) if obj["median_radius"] > 0 else 4.0)
        min_dist = max(2, int(typ_r_an * 0.8))

        coords_s, vals_s, sigs_s = self._find_log_peaks(
            log_max, best_sigma, min_distance=min_dist, threshold=peak_thr_strict, max_peaks=4000
        )
        coords_l, vals_l, _sigs_l = self._find_log_peaks(
            log_max, best_sigma, min_distance=min_dist, threshold=peak_thr_loose, max_peaks=6000
        )
        n_peaks_strict = len(coords_s)
        n_peaks_loose = len(coords_l)

        if n_peaks_strict > 0:
            cy, cx = coords_s[:, 0], coords_s[:, 1]
            cell_int = img[cy, cx]
            flat = log_max.ravel()
            thr_bg = float(np.percentile(flat, 40))
            bg_idx = np.where(flat <= thr_bg)[0]
            if len(bg_idx) > 2000:
                bg_idx = np.random.choice(bg_idx, 2000, replace=False)
            bg_vals = img.ravel()[bg_idx] if len(bg_idx) else np.array([0.0])
            mean_cell = float(np.mean(cell_int))
            mean_bg = float(np.mean(bg_vals))
            contrast = mean_cell - mean_bg
            snr = contrast / (float(np.std(bg_vals)) + 1e-6)
        else:
            contrast = snr = 0.0

        if n_peaks_strict > 0:
            peak_sigmas_orig = sigs_s * scale
            peak_radii_orig = peak_sigmas_orig * 1.8
            peak_areas = np.pi * (peak_radii_orig ** 2)
            prop_min_sigma = max(0.8, float(np.percentile(peak_sigmas_orig, 10)) * 0.75)
            prop_max_sigma = max(prop_min_sigma + 1.0, float(np.percentile(peak_sigmas_orig, 90)) * 1.4)
            prop_min_area = int(max(4, round(float(np.percentile(peak_areas, 10)) * 0.5)))
            prop_max_area = int(max(prop_min_area + 12, round(float(np.percentile(peak_areas, 90)) * 1.8)))
        elif obj["n"] > 0:
            prop_min_sigma = max(0.8, obj["median_radius"] / 1.8 * 0.6)
            prop_max_sigma = max(prop_min_sigma + 1.0, obj["median_radius"] / 1.8 * 1.8)
            prop_min_area = int(max(4, round(obj["median_area"] * 0.4)))
            prop_max_area = int(max(prop_min_area + 12, round(obj["median_area"] * 2.5)))
        else:
            prop_min_sigma, prop_max_sigma = 1.5, 8.0
            prop_min_area, prop_max_area = 12, 400

        # Prefer completed Area Tune measures for area (and related sigma) bounds
        area_tune = getattr(self, "area_tune_result", None) or {}
        used_area_tune = (
            isinstance(area_tune, dict)
            and int(area_tune.get("n", 0) or 0) >= 3
            and area_tune.get("mean_area") is not None
        )
        # Prefer Measure Tune (TP/FP/FN/TN) for thr/sigma/snr/area when available
        measure_tune = getattr(self, "measure_tune_result", None) or {}
        # Full pass needs both sides; precision-only (neg) or recall-only (pos) also count
        used_measure_tune = isinstance(measure_tune, dict) and (
            (
                int(measure_tune.get("n_pos", 0) or 0) >= 2
                and int(measure_tune.get("n_neg", 0) or 0) >= 2
            )
            or (
                int(measure_tune.get("n_neg", 0) or 0) >= 2
                and measure_tune.get("mode", "").startswith("precision")
            )
            or (
                int(measure_tune.get("n_pos", 0) or 0) >= 2
                and str(measure_tune.get("mode", "")).startswith("recall")
            )
            or measure_tune.get("source") == "measure_tune_tp_fp_fn_tn"
            and (
                int(measure_tune.get("n_pos", 0) or 0) >= 2
                or int(measure_tune.get("n_neg", 0) or 0) >= 2
            )
        )
        log_prop_min_area, log_prop_max_area = prop_min_area, prop_max_area
        if used_area_tune:
            at_min = int(area_tune.get("blob_min_area") or round(0.7 * float(area_tune["mean_area"])))
            at_max = int(area_tune.get("blob_max_area") or round(1.5 * float(area_tune["mean_area"])))
            at_min = max(1, at_min)
            at_max = max(at_min + 1, at_max)
            prop_min_area = at_min
            prop_max_area = at_max
            if area_tune.get("blob_min_sigma") is not None:
                prop_min_sigma = float(area_tune["blob_min_sigma"])
            if area_tune.get("blob_max_sigma") is not None:
                prop_max_sigma = float(area_tune["blob_max_sigma"])
            prop_max_sigma = max(prop_min_sigma + 0.5, prop_max_sigma)

        if used_measure_tune:
            # Measure Tune thr/sigma/snr — but Area Tune always owns min/max area
            if not used_area_tune:
                if measure_tune.get("blob_min_area") is not None:
                    prop_min_area = int(measure_tune["blob_min_area"])
                if measure_tune.get("blob_max_area") is not None:
                    prop_max_area = int(measure_tune["blob_max_area"])
            if measure_tune.get("blob_min_sigma") is not None:
                prop_min_sigma = float(measure_tune["blob_min_sigma"])
            if measure_tune.get("blob_max_sigma") is not None:
                prop_max_sigma = float(measure_tune["blob_max_sigma"])
            prop_max_sigma = max(prop_min_sigma + 0.5, prop_max_sigma)

        prop_min_sigma = round(float(prop_min_sigma), 2)
        prop_max_sigma = round(float(min(40.0, prop_max_sigma)), 2)
        prop_num_sigma = int(np.clip(int(round((prop_max_sigma - prop_min_sigma) * 2.2)) + 8, 10, 28))

        _prog(85, "Estimating recommended parameters…")
        if used_measure_tune and measure_tune.get("blob_threshold") is not None:
            prop_thr = float(measure_tune["blob_threshold"])
            prop_thr = float(np.clip(round(prop_thr, 4), 0.005, 0.4))
        elif n_peaks_strict > 0:
            weak_cell = float(np.percentile(vals_s, 15))
            if n_peaks_loose > n_peaks_strict:
                noise_like = float(np.percentile(vals_l, 30))
            else:
                noise_like = float(np.percentile(log_max, 80))
            if weak_cell > noise_like:
                prop_thr = noise_like + 0.3 * (weak_cell - noise_like)
            else:
                prop_thr = weak_cell * 0.75
            if prop_thr > 0.6:
                prop_thr = prop_thr / (float(np.percentile(vals_s, 75)) + 1e-8) * 0.12
            prop_thr = float(np.clip(round(prop_thr, 4), 0.005, 0.4))
        else:
            prop_thr = max(0.03, min(0.2, float(cfg.blob_threshold)))

        _prog(88, "Regional tile diagnosis…")
        region = self._smart_suggest_regional_diagnosis(
            img,
            log_max,
            coords_s,
            vals_s,
            current_mask,
            scale,
            typ_r_an=typ_r_an,
        )
        recipe = region.get("recipe") or "balanced"

        _prog(92, "Building suggestions…")
        suggestions = []

        method = (cfg.detection_method or "blob").lower().strip()
        adaptive_on = int(getattr(cfg, "adaptive_enabled", 0) or 0) != 0 or method == "adaptive"
        blob_family = method in ("blob", "dog", "log", "adaptive")

        # ------------------------------------------------------------------
        # Joint recipes from regional diagnosis (priority 0–1; trump global thr-only)
        # ------------------------------------------------------------------
        cur_sens = float(getattr(cfg, "adaptive_sensitivity", 1.0) or 1.0)
        cur_pack = float(getattr(cfg, "adaptive_packing", 0.5) or 0.5)
        cur_dual = int(getattr(cfg, "adaptive_dual_pass", 1) or 0)
        cur_tile = int(getattr(cfg, "adaptive_tile_size", 256) or 256)
        cur_snr = float(getattr(cfg, "blob_min_local_snr", 0.0) or 0.0)
        cur_free = float(getattr(cfg, "blob_free_space", 0.45) or 0.45)
        cur_peak_i = float(getattr(cfg, "blob_min_peak_intensity", 0.0) or 0.0)
        skip_global_thr = False  # joint recipe owns threshold when True

        def _sug(param, current, suggested, reason, priority=1):
            if current is None:
                return
            try:
                if isinstance(suggested, (int, float)) and isinstance(current, (int, float)):
                    if abs(float(suggested) - float(current)) < 1e-9:
                        return
                elif suggested == current:
                    return
            except Exception:
                pass
            suggestions.append({
                "param": param,
                "current": current,
                "suggested": suggested,
                "reason": reason,
                "priority": priority,
            })

        if blob_family and recipe in (
            "mixed_both", "high_bg_fp", "low_bg_fn", "recover_clusters",
            "global_over", "global_under",
        ):
            rsum = region.get("summary") or ""
            H = region.get("high") or {}
            L = region.get("low") or {}

            # Quality gates that help high-BG FPs and tissue-edge junk
            def _sug_quality_for_fp():
                cur_iso = float(getattr(cfg, "blob_min_isotropy", 0.0) or 0.0)
                cur_circ = float(getattr(cfg, "blob_min_circularity", 0.0) or 0.0)
                cur_bgr = float(getattr(cfg, "blob_bg_relative", 0.0) or 0.0)
                cur_edge = int(getattr(cfg, "blob_reject_tissue_edge", 1) or 0)
                if cur_iso < 0.4:
                    _sug(
                        "blob_min_isotropy",
                        cur_iso,
                        0.45,
                        "Reject non-round peaks (tissue edges / fibers) via radial symmetry.",
                        1,
                    )
                if cur_circ < 0.3:
                    _sug(
                        "blob_min_circularity",
                        cur_circ,
                        0.35,
                        "Reject elongated edge-of-tissue detections.",
                        1,
                    )
                if cur_bgr < 0.1:
                    _sug(
                        "blob_bg_relative",
                        cur_bgr,
                        0.12,
                        "Peak must exceed local median — kills high-BG texture false positives.",
                        1,
                    )
                if cur_edge == 0:
                    _sug(
                        "blob_reject_tissue_edge",
                        cur_edge,
                        1,
                        "Reject peaks on the tissue/outside border (dark outer ring).",
                        1,
                    )

            if recipe == "mixed_both":
                skip_global_thr = True
                if not adaptive_on:
                    _sug(
                        "adaptive_enabled",
                        int(getattr(cfg, "adaptive_enabled", 0) or 0),
                        1,
                        rsum + " Enable Adaptive for tile-local thresholds.",
                        0,
                    )
                if cur_dual == 0:
                    _sug("adaptive_dual_pass", cur_dual, 1, rsum + " Dual-pass required for mixed BG.", 0)
                target_snr = 2.0
                if cur_snr < 1.2:
                    target_snr = 2.0
                elif cur_snr > 2.8:
                    target_snr = 2.0
                else:
                    target_snr = float(np.clip(cur_snr, 1.6, 2.4))
                _sug(
                    "blob_min_local_snr",
                    cur_snr,
                    round(target_snr, 2),
                    (
                        f"{rsum} Target local SNR≈{target_snr:.1f}: high enough for bright-tile "
                        "clutter, low enough for real cluster cells."
                    ),
                    0,
                )
                _sug_quality_for_fp()
                thr_t = float(cfg.blob_threshold)
                if L.get("n_peaks", 0) > max(6, L.get("n_det", 0) * 1.5):
                    thr_t = min(thr_t, max(0.03, min(prop_thr, thr_t) * 0.9))
                thr_t = float(np.clip(round(thr_t, 4), 0.01, 0.25))
                _sug(
                    "blob_threshold",
                    cfg.blob_threshold,
                    thr_t,
                    "Mixed field: dual-pass + quality gates handle BG; avoid ultra-high thr.",
                    1,
                )
                _sug(
                    "adaptive_sensitivity",
                    cur_sens,
                    round(float(np.clip(1.0 if abs(cur_sens - 1.0) > 0.12 else cur_sens, 0.85, 1.15)), 2),
                    "Neutral adaptive sensitivity (~1.0) so dark tiles stay recoverable.",
                    1,
                )
                _sug(
                    "adaptive_packing",
                    cur_pack,
                    round(max(cur_pack, 0.75), 2),
                    "Raise packing so dense true clusters can place neighboring cells.",
                    1,
                )
                _sug(
                    "blob_free_space",
                    cur_free,
                    round(min(cur_free, 0.28), 2),
                    "Lower free-space requirement in clusters (with Adaptive packing).",
                    2,
                )
                if cur_peak_i > 0.12:
                    _sug(
                        "blob_min_peak_intensity",
                        cur_peak_i,
                        0.0,
                        "Clear peak-intensity floor so dim-but-real cluster cells are not dropped.",
                        2,
                    )

            elif recipe == "high_bg_fp":
                skip_global_thr = True
                if not adaptive_on:
                    _sug(
                        "adaptive_enabled",
                        int(getattr(cfg, "adaptive_enabled", 0) or 0),
                        1,
                        rsum,
                        0,
                    )
                if cur_dual == 0:
                    _sug("adaptive_dual_pass", cur_dual, 1, rsum, 0)
                target_snr = max(cur_snr, 2.2 if H.get("det_density", 0) > 150 else 1.9)
                target_snr = float(np.clip(target_snr, 1.8, 3.2))
                _sug(
                    "blob_min_local_snr",
                    cur_snr,
                    round(target_snr, 2),
                    f"{rsum} Require local SNR≥{target_snr:.1f} so peaks must beat their surround.",
                    0,
                )
                _sug_quality_for_fp()
                thr_t = max(float(cfg.blob_threshold), min(0.10, max(prop_thr, float(cfg.blob_threshold) + 0.01)))
                _sug(
                    "blob_threshold",
                    cfg.blob_threshold,
                    round(float(thr_t), 4),
                    "Mild thr raise; prefer isotropy/BG-relative gates over killing dark cells.",
                    1,
                )
                _sug(
                    "adaptive_sensitivity",
                    cur_sens,
                    round(min(3.0, max(cur_sens, 1.1)), 2),
                    "Slightly stricter tile thresholds on bright background.",
                    1,
                )

            elif recipe in ("low_bg_fn", "recover_clusters"):
                skip_global_thr = True
                if not adaptive_on and (region.get("bg_cv", 0) >= 0.08 or region.get("high_bg_over")):
                    _sug(
                        "adaptive_enabled",
                        int(getattr(cfg, "adaptive_enabled", 0) or 0),
                        1,
                        rsum + " Keep Adaptive if the field is still uneven.",
                        1,
                    )
                if cur_dual == 0 and adaptive_on:
                    _sug("adaptive_dual_pass", cur_dual, 1, "Dual-pass helps dark-tile recall.", 1)
                if cur_snr > 2.2 or recipe == "recover_clusters":
                    target_snr = 1.8 if recipe == "recover_clusters" else max(1.4, min(cur_snr, 1.9))
                    _sug(
                        "blob_min_local_snr",
                        cur_snr,
                        round(float(target_snr), 2),
                        f"{rsum} Ease local SNR to ~{target_snr:.1f} (keep quality gates on).",
                        0,
                    )
                thr_t = min(float(cfg.blob_threshold), max(0.02, min(prop_thr, float(cfg.blob_threshold) * 0.8)))
                _sug(
                    "blob_threshold",
                    cfg.blob_threshold,
                    round(float(thr_t), 4),
                    "Lower threshold to recover cluster cells with moderate contrast.",
                    0,
                )
                _sug(
                    "adaptive_sensitivity",
                    cur_sens,
                    round(float(np.clip(min(cur_sens, 0.9), 0.65, 1.0)), 2),
                    "More sensitive adaptive tiles for dark/mid clusters.",
                    1,
                )
                _sug(
                    "adaptive_packing",
                    cur_pack,
                    round(max(cur_pack, 0.85), 2),
                    "Dense packing for tightly clustered true cells.",
                    1,
                )
                _sug(
                    "blob_free_space",
                    cur_free,
                    round(min(cur_free, 0.22), 2),
                    "Allow much tighter cell placement in clusters.",
                    1,
                )
                # Slightly ease isotropy if over-filtering real irregular cells
                cur_iso = float(getattr(cfg, "blob_min_isotropy", 0.0) or 0.0)
                if cur_iso > 0.55:
                    _sug(
                        "blob_min_isotropy",
                        cur_iso,
                        0.4,
                        "Slightly ease isotropy so real cluster cells are not rejected.",
                        2,
                    )
                if cur_peak_i > 0.05:
                    _sug(
                        "blob_min_peak_intensity",
                        cur_peak_i,
                        0.0,
                        "Clear peak-intensity floor for dim dark-field cells.",
                        2,
                    )

            elif recipe == "global_over":
                skip_global_thr = True
                thr_t = max(float(cfg.blob_threshold), min(0.2, max(prop_thr, float(cfg.blob_threshold) + 0.025)))
                _sug("blob_threshold", cfg.blob_threshold, round(float(thr_t), 4), rsum, 1)
                if cur_snr < 1.5:
                    _sug("blob_min_local_snr", cur_snr, 1.8, rsum + " Add mild local SNR gate.", 1)

            elif recipe == "global_under":
                skip_global_thr = True
                thr_t = min(float(cfg.blob_threshold), max(0.02, min(prop_thr, float(cfg.blob_threshold) * 0.8)))
                _sug("blob_threshold", cfg.blob_threshold, round(float(thr_t), 4), rsum, 1)
                if cur_snr > 2.5:
                    _sug(
                        "blob_min_local_snr",
                        cur_snr,
                        round(max(1.5, cur_snr - 0.8), 2),
                        rsum + " SNR may be too strict globally.",
                        1,
                    )

        # Measure Tune (TP/FP/FN/TN) anchors — highest priority user truth
        if used_measure_tune:
            mc = measure_tune.get("counts") or {}
            cnt_txt = (
                f"TP:{mc.get('tp', 0)} FP:{mc.get('fp', 0)} "
                f"FN:{mc.get('fn', 0)} TN:{mc.get('tn', 0)}"
            )
            if abs(float(cfg.blob_threshold) - prop_thr) / max(prop_thr, 1e-6) > 0.08:
                suggestions.append({
                    "param": "blob_threshold",
                    "current": cfg.blob_threshold,
                    "suggested": prop_thr,
                    "reason": f"Measure Tune ({cnt_txt}): restore calibrated threshold.",
                    "priority": 0,
                })
            mt_snr = measure_tune.get("blob_min_local_snr")
            if mt_snr is not None and abs(float(cfg.blob_min_local_snr) - float(mt_snr)) > 0.15:
                suggestions.append({
                    "param": "blob_min_local_snr",
                    "current": cfg.blob_min_local_snr,
                    "suggested": float(mt_snr),
                    "reason": f"Measure Tune ({cnt_txt}): restore SNR from FP/FN labeling.",
                    "priority": 0,
                })
            for pkey, sug in (
                ("blob_min_sigma", prop_min_sigma),
                ("blob_max_sigma", prop_max_sigma),
            ):
                cur_v = getattr(cfg, pkey)
                if abs(float(cur_v) - float(sug)) / max(float(sug), 1e-6) > 0.1:
                    suggestions.append({
                        "param": pkey,
                        "current": cur_v,
                        "suggested": sug,
                        "reason": f"Measure Tune ({cnt_txt}): keep user-calibrated {pkey}.",
                        "priority": 1,
                    })
            # Area only from Measure Tune if Area Tune was never run
            if not used_area_tune:
                for pkey, sug in (
                    ("blob_min_area", prop_min_area),
                    ("blob_max_area", prop_max_area),
                ):
                    cur_v = getattr(cfg, pkey)
                    if abs(float(cur_v) - float(sug)) / max(float(sug), 1e-6) > 0.1:
                        suggestions.append({
                            "param": pkey,
                            "current": cur_v,
                            "suggested": sug,
                            "reason": f"Measure Tune ({cnt_txt}): keep user-calibrated {pkey}.",
                            "priority": 1,
                        })
            # Re-apply other stored quality/packing knobs if drifted
            stored = measure_tune.get("settings") or {}
            for pkey in (
                "blob_bg_relative",
                "blob_min_isotropy",
                "blob_min_circularity",
                "adaptive_packing",
                "blob_free_space",
                "adaptive_enabled",
                "adaptive_dual_pass",
            ):
                if pkey not in stored:
                    continue
                cur_v = getattr(cfg, pkey, None)
                sug = stored[pkey]
                try:
                    if abs(float(cur_v) - float(sug)) < 1e-6:
                        continue
                except Exception:
                    if cur_v == sug:
                        continue
                suggestions.append({
                    "param": pkey,
                    "current": cur_v,
                    "suggested": sug,
                    "reason": f"Measure Tune ({cnt_txt}): restore {pkey} from labels.",
                    "priority": 1,
                })

        # Area Tune anchors: always prefer over Measure Tune for min/max area
        if used_area_tune:
            n_at = int(area_tune.get("n", 0))
            mean_a = float(area_tune.get("mean_area", 0))
            mean_d = float(area_tune.get("mean_diameter", 0))
            if abs(int(cfg.blob_min_area) - prop_min_area) / max(prop_min_area, 1) > 0.08:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": prop_min_area,
                    "reason": (
                        f"Area Tune ({n_at} cells, mean area {mean_a:.0f} px², "
                        f"d≈{mean_d:.1f} px): use 0.7× mean = {prop_min_area}."
                    ),
                    "priority": 1,
                })
            if abs(int(cfg.blob_max_area) - prop_max_area) / max(prop_max_area, 1) > 0.08:
                suggestions.append({
                    "param": "blob_max_area",
                    "current": cfg.blob_max_area,
                    "suggested": prop_max_area,
                    "reason": (
                        f"Area Tune ({n_at} cells): use 1.5× mean area = {prop_max_area}."
                    ),
                    "priority": 1,
                })
            if (
                abs(float(cfg.blob_min_sigma) - prop_min_sigma) / max(prop_min_sigma, 0.5) > 0.25
                or abs(float(cfg.blob_max_sigma) - prop_max_sigma) / max(prop_max_sigma, 0.5) > 0.25
            ):
                suggestions.append({
                    "param": "blob_min_sigma",
                    "current": cfg.blob_min_sigma,
                    "suggested": prop_min_sigma,
                    "reason": (
                        f"Area Tune diameters imply sigma ≈ {prop_min_sigma}–{prop_max_sigma} "
                        f"(from d≈{mean_d:.1f} px and radius scale)."
                    ),
                    "priority": 2,
                })
                suggestions.append({
                    "param": "blob_max_sigma",
                    "current": cfg.blob_max_sigma,
                    "suggested": prop_max_sigma,
                    "reason": (
                        f"Match max sigma to Area Tune cell sizes "
                        f"(diameters {min(area_tune.get('diameters') or [0]):.0f}–"
                        f"{max(area_tune.get('diameters') or [0]):.0f} px)."
                    ),
                    "priority": 2,
                })

        # blob / dog / log are valid spot detectors; only nudge watershed users
        if not blob_family:
            suggestions.append({
                "param": "detection_method",
                "current": cfg.detection_method,
                "suggested": "blob",
                "reason": (
                    "Blob (LoG) or DoG is usually better for round fluorescent cells "
                    "than watershed. Enable the Adaptive checkbox if background varies "
                    "across the field."
                ),
                "priority": 1,
            })

        # ------------------------------------------------------------------
        # Adaptive indicators (mixed background / density non-uniformity)
        # ------------------------------------------------------------------
        def _tile_bg_stats(arr2d):
            """Return (bg_cv, bg_span, p90_span, half_contrast) for a 2D image."""
            ah, aw = arr2d.shape[:2]
            n_ty = max(3, min(8, ah // 80))
            n_tx = max(3, min(8, aw // 80))
            tsy = max(16, ah // n_ty)
            tsx = max(16, aw // n_tx)
            meds, p90s = [], []
            for y0 in range(0, ah, tsy):
                for x0 in range(0, aw, tsx):
                    patch = arr2d[y0:min(ah, y0 + tsy), x0:min(aw, x0 + tsx)]
                    if patch.size < 64:
                        continue
                    meds.append(float(np.median(patch)))
                    p90s.append(float(np.percentile(patch, 90)))
            if not meds:
                return 0.0, 0.0, 0.0, 0.0
            meds = np.asarray(meds, dtype=np.float64)
            p90s = np.asarray(p90s, dtype=np.float64)
            cv = float(np.std(meds) / (float(np.mean(meds)) + 1e-6))
            span = float(np.max(meds) - np.min(meds))
            p90sp = float(np.max(p90s) - np.min(p90s))
            # Half-plane contrast (catches bright vs dark halves)
            mid_y, mid_x = ah // 2, aw // 2
            halves = [
                float(np.median(arr2d[:mid_y, :])),
                float(np.median(arr2d[mid_y:, :])),
                float(np.median(arr2d[:, :mid_x])),
                float(np.median(arr2d[:, mid_x:])),
            ]
            half_c = float(max(halves) - min(halves))
            return cv, span, p90sp, half_c

        # Preprocessed analysis image
        bg_cv, bg_span, p90_span, half_c = _tile_bg_stats(img)
        # Raw TIFF (preprocess can flatten BG — raw often shows true non-uniformity)
        try:
            raw = np.asarray(bg_src.convert("L"), dtype=np.float64)
            if raw.size > 0 and raw.max() > raw.min():
                raw_n = (raw - raw.min()) / (raw.max() - raw.min())
                # Downsample large raw for speed
                step = max(1, int(round(max(raw_n.shape) / 1200.0)))
                if step > 1:
                    raw_n = raw_n[::step, ::step]
                r_cv, r_span, r_p90, r_half = _tile_bg_stats(raw_n)
                bg_cv = max(bg_cv, r_cv)
                bg_span = max(bg_span, r_span)
                p90_span = max(p90_span, r_p90)
                half_c = max(half_c, r_half)
        except Exception:
            pass
        # LoG response spatial variation (high when dim vs bright cells differ)
        try:
            log_cv, log_span, _, log_half = _tile_bg_stats(log_max)
        except Exception:
            log_cv, log_span, log_half = 0.0, 0.0, 0.0

        # Peak density non-uniformity (spatial)
        dens_cv = 0.0
        if n_peaks_strict >= 12 and coords_s is not None and len(coords_s) >= 12:
            gy, gx = 3, 3
            counts = np.zeros((gy, gx), dtype=np.float64)
            for py, px in coords_s:
                iy = min(gy - 1, int(py / max(h, 1) * gy))
                ix = min(gx - 1, int(px / max(w, 1) * gx))
                counts[iy, ix] += 1.0
            dens_cv = float(np.std(counts) / (np.mean(counts) + 1e-6))

        peaks_orig_est = n_peaks_strict * (orig_mp / max(mp, 1e-6))
        under_det = (
            peaks_orig_est > max(30, n_det * 1.8) and n_det < peaks_orig_est * 0.6
        )
        # Peak-vs-detection gap milder (for adaptive enable without full under_det)
        peak_gap = (
            n_peaks_strict >= 15
            and n_det > 0
            and peaks_orig_est > n_det * 1.35
        )
        # tiny_frac used below for over-detection; compute early for adaptive packing
        tiny_frac_pre = 0.0
        if obj["n"] > 0 and len(obj["areas"]):
            tiny_frac_pre = float(
                np.mean(obj["areas"] < max(8, prop_min_area * 0.5))
            )
        over_det = density > 1200 or (n_det > 800 and tiny_frac_pre > 0.35)

        mixed_bg = (
            bg_cv >= 0.08
            or bg_span >= 0.06
            or p90_span >= 0.12
            or half_c >= 0.08
            or log_cv >= 0.25
            or log_span >= 0.08
            or log_half >= 0.06
        )
        mixed_density = dens_cv >= 0.45 and n_peaks_strict >= 12
        # Adaptive helps when field is non-uniform (even if counts look OK globally)
        # Also follow regional diagnosis recipes that need tile-local thresholds
        region_wants_adaptive = recipe in (
            "mixed_both",
            "high_bg_fp",
            "low_bg_fn",
            "recover_clusters",
        ) or bool(region.get("high_bg_over")) or bool(region.get("low_bg_under"))
        want_adaptive = blob_family and (
            region_wants_adaptive
            or (mixed_bg and (under_det or over_det or peak_gap or n_peaks_strict >= 12))
            or (mixed_density and (under_det or over_det or peak_gap or density > 300))
            or (mixed_bg and mixed_density)
            or (mixed_bg and snr > 0 and snr < 5.0 and n_peaks_strict >= 10)
            or (mixed_bg and half_c >= 0.12)  # strong bright/dark split
            or (mixed_bg and bg_cv >= 0.15)  # strong spatial BG variation alone
        )

        # Always surface Adaptive when indicators say so (not only recipe == balanced).
        # Joint recipes may already have added this; by_param keeps priority 0–1.
        if blob_family and want_adaptive and not adaptive_on:
            suggestions.append({
                "param": "adaptive_enabled",
                "current": int(getattr(cfg, "adaptive_enabled", 0) or 0),
                "suggested": 1,
                "reason": (
                    "Enable Adaptive (tile thresholds + dual-pass + density packing). "
                    f"Recipe={recipe}"
                    + (f", tile BG CV={bg_cv:.2f}" if mixed_bg else "")
                    + (f", peak density CV={dens_cv:.2f}" if mixed_density else "")
                    + ("; high-BG over-detect" if region.get("high_bg_over") else "")
                    + ("; low-BG under-detect" if region.get("low_bg_under") else "")
                    + ". Required for mixed high/low background on one slice."
                ),
                "priority": 0,
            })
            if cur_dual == 0:
                suggestions.append({
                    "param": "adaptive_dual_pass",
                    "current": cur_dual,
                    "suggested": 1,
                    "reason": (
                        "Turn on dual-pass with Adaptive: sensitive pass for dark tiles, "
                        "strict pass for bright clutter."
                    ),
                    "priority": 0,
                })

        adaptive_relevant = adaptive_on or want_adaptive
        if adaptive_relevant and blob_family and recipe in (
            "balanced", "global_over", "global_under"
        ):
            # Dual-pass for mixed background
            if mixed_bg and cur_dual == 0:
                suggestions.append({
                    "param": "adaptive_dual_pass",
                    "current": cur_dual,
                    "suggested": 1,
                    "reason": (
                        f"Background varies across tiles (CV={bg_cv:.2f}, span={bg_span:.2f}). "
                        "Dual-pass fuses a sensitive pass (dark areas) with a strict pass "
                        "(bright areas)."
                    ),
                    "priority": 2,
                })

            prop_sens = cur_sens
            if under_det and mixed_bg:
                prop_sens = min(cur_sens, 0.75 if adaptive_on else 0.85)
            elif over_det and mixed_bg:
                prop_sens = max(cur_sens, 1.25 if adaptive_on else 1.15)
            elif over_det:
                prop_sens = max(cur_sens, 1.1)
            elif under_det:
                prop_sens = min(cur_sens, 0.9)
            prop_sens = float(np.clip(round(prop_sens, 2), 0.25, 3.0))
            if abs(prop_sens - cur_sens) >= 0.12:
                suggestions.append({
                    "param": "adaptive_sensitivity",
                    "current": cur_sens,
                    "suggested": prop_sens,
                    "reason": (
                        (
                            "Under-detection with uneven background — lower sensitivity "
                            "to drop tile thresholds in dim regions."
                            if prop_sens < cur_sens
                            else "Over-detection / bright clutter — raise sensitivity to "
                            "tighten tile thresholds."
                        )
                        + f" (BG CV={bg_cv:.2f})"
                    ),
                    "priority": 2,
                })

            prop_pack = cur_pack
            if mixed_density or dens_cv >= 0.7 or density > 900:
                prop_pack = max(cur_pack, 0.75)
            elif dens_cv < 0.35 and density < 200 and n_peaks_strict >= 10:
                prop_pack = min(cur_pack, 0.35)
            elif under_det and dens_cv >= 0.45:
                prop_pack = max(cur_pack, 0.65)
            prop_pack = float(np.clip(round(prop_pack, 2), 0.0, 1.0))
            if abs(prop_pack - cur_pack) >= 0.12:
                suggestions.append({
                    "param": "adaptive_packing",
                    "current": cur_pack,
                    "suggested": prop_pack,
                    "reason": (
                        f"Peak density CV={dens_cv:.2f}, density≈{density:.0f}/MP. "
                        + (
                            "Raise packing so crowded clusters can share free space."
                            if prop_pack > cur_pack
                            else "Lower packing to require more free space for sparse cells."
                        )
                    ),
                    "priority": 3,
                })

            typ_r = obj["median_radius"] if obj["median_radius"] > 0 else (
                float(np.median(peak_radii_orig)) if n_peaks_strict > 0 else 8.0
            )
            prop_tile = int(np.clip(round(typ_r * 16 / max(scale, 1e-6)), 128, 384))
            prop_tile = int(round(prop_tile / 32.0) * 32)
            prop_tile = int(np.clip(prop_tile, 128, 384))
            if abs(prop_tile - cur_tile) >= 48 and (mixed_bg or mixed_density):
                suggestions.append({
                    "param": "adaptive_tile_size",
                    "current": cur_tile,
                    "suggested": prop_tile,
                    "reason": (
                        f"Tile size ~{prop_tile}px better matches cell scale "
                        f"(~{typ_r:.0f}px radius) for local thresholding on this field."
                    ),
                    "priority": 4,
                })

            if over_det or (mixed_bg and density > 600):
                prop_snr = max(cur_snr, 2.0 if over_det else 1.5)
                if prop_snr > cur_snr + 0.4:
                    suggestions.append({
                        "param": "blob_min_local_snr",
                        "current": cur_snr,
                        "suggested": round(float(prop_snr), 2),
                        "reason": (
                            "Bright or uneven background can create false peaks. "
                            "Require cells to outshine their local surround "
                            f"(local SNR ≥ {prop_snr:.1f})."
                        ),
                        "priority": 3,
                    })

            cur_overlap = float(getattr(cfg, "adaptive_tile_overlap", 0.3) or 0.0)
            if mixed_bg and cur_overlap < 0.25:
                suggestions.append({
                    "param": "adaptive_tile_overlap",
                    "current": cur_overlap,
                    "suggested": 0.3,
                    "reason": (
                        "Raise tile overlap so cells near tile borders are less likely "
                        "to be missed when background varies across the field."
                    ),
                    "priority": 4,
                })

        # Global thr moves only if joint recipe did not already set strategy
        if under_det and not skip_global_thr:
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": min(cfg.blob_threshold, prop_thr),
                "reason": (
                    f"Under-detection likely: ~{int(peaks_orig_est)} strong LoG peaks vs "
                    f"{n_det} counted objects. Lower threshold to catch more true cells."
                ),
                "priority": 2,
            })
            if cfg.blob_min_area > prop_min_area * 1.3:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": prop_min_area,
                    "reason": "Minimum area may be excluding real smaller cells seen by LoG analysis.",
                    "priority": 3,
                })

        tiny_frac = 0.0
        if obj["n"] > 0 and len(obj["areas"]):
            tiny_frac = float(np.mean(obj["areas"] < max(8, prop_min_area * 0.5)))
        if (density > 1200 or (n_det > 800 and tiny_frac > 0.35)) and not skip_global_thr:
            new_thr = max(cfg.blob_threshold, min(0.4, max(prop_thr, cfg.blob_threshold + 0.03)))
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": round(float(new_thr), 4),
                "reason": (
                    f"Over-detection likely ({n_det} objects, {density:.0f}/MP, "
                    f"{100 * tiny_frac:.0f}% very small). Raising threshold reduces noise."
                ),
                "priority": 2,
            })
            if tiny_frac > 0.25:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": max(cfg.blob_min_area, prop_min_area),
                    "reason": "Many tiny components look like noise — raise min area to filter them.",
                    "priority": 3,
                })

        if n_peaks_strict >= 8:
            if cfg.blob_min_sigma > prop_min_sigma * 1.4 or cfg.blob_max_sigma < prop_max_sigma * 0.7:
                suggestions.append({
                    "param": "blob_min_sigma",
                    "current": cfg.blob_min_sigma,
                    "suggested": prop_min_sigma,
                    "reason": (
                        f"Cell scale from LoG peaks suggests sigma ≈ "
                        f"{prop_min_sigma}–{prop_max_sigma} (now {cfg.blob_min_sigma}–{cfg.blob_max_sigma})."
                    ),
                    "priority": 2,
                })
                suggestions.append({
                    "param": "blob_max_sigma",
                    "current": cfg.blob_max_sigma,
                    "suggested": prop_max_sigma,
                    "reason": "Expand/contract max sigma to match the measured cell size range.",
                    "priority": 2,
                })
                suggestions.append({
                    "param": "blob_num_sigma",
                    "current": cfg.blob_num_sigma,
                    "suggested": prop_num_sigma,
                    "reason": "Match number of LoG scales to the recommended sigma span.",
                    "priority": 4,
                })

        if (n_peaks_strict >= 8 or obj["n"] >= 10) and not used_area_tune:
            # Only use LoG/object-derived area when Area Tune is not available
            if abs(cfg.blob_min_area - prop_min_area) / max(prop_min_area, 1) > 0.4:
                suggestions.append({
                    "param": "blob_min_area",
                    "current": cfg.blob_min_area,
                    "suggested": prop_min_area,
                    "reason": f"Suggested min area from measured sizes ≈ {prop_min_area} px.",
                    "priority": 3,
                })
            if abs(cfg.blob_max_area - prop_max_area) / max(prop_max_area, 1) > 0.4:
                suggestions.append({
                    "param": "blob_max_area",
                    "current": cfg.blob_max_area,
                    "suggested": prop_max_area,
                    "reason": f"Suggested max area from measured sizes ≈ {prop_max_area} px.",
                    "priority": 3,
                })
        elif used_area_tune and (n_peaks_strict >= 8 or obj["n"] >= 10):
            # Informational only when LoG disagrees strongly with Area Tune
            if (
                log_prop_min_area > 0
                and (
                    abs(log_prop_min_area - prop_min_area) / max(prop_min_area, 1) > 0.6
                    or abs(log_prop_max_area - prop_max_area) / max(prop_max_area, 1) > 0.6
                )
            ):
                logger.info(
                    "Smart Suggest: Area Tune areas %d–%d preferred over LoG areas %d–%d",
                    prop_min_area,
                    prop_max_area,
                    log_prop_min_area,
                    log_prop_max_area,
                )

        if snr > 0 and snr < 2.5:
            suggestions.append({
                "param": "preprocess_nr_gaussian",
                "current": pcfg.nr_gaussian_sigma,
                "suggested": min(2.5, round(pcfg.nr_gaussian_sigma + 0.5, 1)),
                "reason": f"Low cell/background SNR ({snr:.1f}). Mild extra smoothing can stabilize LoG peaks.",
                "priority": 3,
            })
            if getattr(pcfg, 'denoise_method', None) in (None, "none", ""):
                suggestions.append({
                    "param": "preprocess_denoise_method",
                    "current": pcfg.denoise_method,
                    "suggested": "gaussian",
                    "reason": "Enable Gaussian denoising for low-SNR immunofluorescence images.",
                    "priority": 3,
                })

        if cfg.blob_min_circularity > 0.75 and obj["n"] > 0:
            med_c = float(np.median(obj["circularities"])) if len(obj["circularities"]) else 1.0
            if med_c < cfg.blob_min_circularity:
                suggestions.append({
                    "param": "blob_min_circularity",
                    "current": cfg.blob_min_circularity,
                    "suggested": max(0.4, round(med_c * 0.85, 2)),
                    "reason": (
                        f"Detected objects have median circularity {med_c:.2f}, below your "
                        f"threshold {cfg.blob_min_circularity}. Loosen to keep real cells."
                    ),
                    "priority": 3,
                })

        if n_det < 15 and n_peaks_loose < 20 and snr < 2 and not skip_global_thr:
            suggestions.append({
                "param": "blob_threshold",
                "current": cfg.blob_threshold,
                "suggested": max(0.01, round(min(cfg.blob_threshold, prop_thr) * 0.7, 4)),
                "reason": (
                    "Very few peaks and detections with low SNR — try a more sensitive threshold, "
                    "or use Measure Tune and click example cells."
                ),
                "priority": 2,
            })

        by_param = {}
        for s in suggestions:
            p = s["param"]
            if p not in by_param or s.get("priority", 9) < by_param[p].get("priority", 9):
                by_param[p] = s
        suggestions = sorted(by_param.values(), key=lambda s: s.get("priority", 9))

        def _sugg_val(param, default):
            for s in suggestions:
                if s["param"] == param:
                    return s["suggested"]
            return default

        thr_preset = float(_sugg_val("blob_threshold", prop_thr))
        recommended_preset = {
            "detection_method": "blob" if method not in ("dog", "log") else (
                "dog" if method == "dog" else "blob"
            ),
            "blob_min_sigma": prop_min_sigma,
            "blob_max_sigma": prop_max_sigma,
            "blob_num_sigma": prop_num_sigma,
            "blob_threshold": thr_preset,
            "blob_min_area": prop_min_area,
            "blob_max_area": prop_max_area,
            "blob_overlap": 0.5,
            "blob_min_local_snr": float(_sugg_val("blob_min_local_snr", cur_snr)),
            "blob_free_space": float(_sugg_val("blob_free_space", cur_free)),
        }
        if want_adaptive or adaptive_on or recipe in (
            "mixed_both", "high_bg_fp", "low_bg_fn", "recover_clusters",
            "global_over", "global_under",
        ):
            recommended_preset["adaptive_enabled"] = 1
            recommended_preset["adaptive_dual_pass"] = int(
                _sugg_val(
                    "adaptive_dual_pass",
                    1 if (mixed_bg or want_adaptive or recipe != "balanced") else max(cur_dual, 1),
                )
            )
            recommended_preset["adaptive_sensitivity"] = float(
                _sugg_val("adaptive_sensitivity", cur_sens)
            )
            recommended_preset["adaptive_packing"] = float(
                _sugg_val("adaptive_packing", cur_pack)
            )
        # Ensure dual-pass default when Adaptive is in the preset
        if recommended_preset.get("adaptive_enabled"):
            recommended_preset["adaptive_dual_pass"] = int(
                recommended_preset.get("adaptive_dual_pass") or 1
            )

        # Snapshot for trajectory on next Smart Suggest run
        try:
            hist = list(getattr(self, "_smart_suggest_history", []) or [])
            hist.append({
                "recipe": recipe,
                "blob_min_local_snr": float(cfg.blob_min_local_snr),
                "blob_threshold": float(cfg.blob_threshold),
                "n_det": int(n_det),
                "n_peaks": int(n_peaks_strict),
            })
            self._smart_suggest_history = hist[-8:]
        except Exception:
            pass

        _prog(98, "Finishing analysis…")
        return {
            "num_detections": n_det,
            "detection_density": round(density, 1),
            "log_peaks_strict": n_peaks_strict,
            "log_peaks_loose": n_peaks_loose,
            "contrast": round(contrast, 3),
            "snr": round(snr, 2),
            "median_object_area": round(obj["median_area"], 1),
            "median_object_radius": round(obj["median_radius"], 1),
            "suggested_sigma": (prop_min_sigma, prop_max_sigma),
            "suggested_threshold": thr_preset,
            "used_area_tune": bool(used_area_tune),
            "used_measure_tune": bool(used_measure_tune),
            "area_tune_summary": (
                {
                    "n": int(area_tune.get("n", 0)),
                    "mean_diameter": round(float(area_tune.get("mean_diameter", 0)), 2),
                    "mean_area": round(float(area_tune.get("mean_area", 0)), 1),
                    "blob_min_area": prop_min_area,
                    "blob_max_area": prop_max_area,
                }
                if used_area_tune
                else None
            ),
            "measure_tune_summary": (
                {
                    "counts": measure_tune.get("counts"),
                    "n_pos": measure_tune.get("n_pos"),
                    "n_neg": measure_tune.get("n_neg"),
                    "blob_threshold": measure_tune.get("blob_threshold"),
                    "blob_min_local_snr": measure_tune.get("blob_min_local_snr"),
                }
                if used_measure_tune
                else None
            ),
            "recipe": recipe,
            "region_diagnosis": {
                "recipe": recipe,
                "summary": region.get("summary"),
                "high_bg_over": region.get("high_bg_over"),
                "low_bg_under": region.get("low_bg_under"),
                "bg_cv": region.get("bg_cv"),
                "bg_span": region.get("bg_span"),
                "high_peaks": (region.get("high") or {}).get("n_peaks"),
                "high_det": (region.get("high") or {}).get("n_det"),
                "low_peaks": (region.get("low") or {}).get("n_peaks"),
                "low_det": (region.get("low") or {}).get("n_det"),
                "prev_recipe": region.get("prev_recipe"),
            },
            "adaptive_indicators": {
                "bg_cv": round(bg_cv, 3),
                "bg_span": round(bg_span, 3),
                "density_cv": round(dens_cv, 3),
                "mixed_bg": bool(mixed_bg),
                "mixed_density": bool(mixed_density),
                "want_adaptive": bool(want_adaptive),
            },
            "suggestions": suggestions,
            "recommended_preset": recommended_preset,
        }

    def _show_smart_suggest_dialog(self):
        """Show Smart Suggest analysis with optional apply + live mask refresh."""
        self._last_smart_suggest_error = None
        if self._working_background_pil() is None:
            messagebox.showerror(
                "Analysis Failed",
                "Could not analyze the current image.\n\n"
                "No TIFF is loaded (or the background buffer is empty).\n"
                "Open a TIFF from the File Browser or File → Import TIFF, then try again.",
            )
            return

        # Visible progress so the UI does not look frozen during analysis
        progress = None
        analysis = None
        outer_err = None
        try:
            try:
                self.master.config(cursor="watch")
            except Exception:
                pass
            progress = self._show_busy_dialog("Smart Suggest")
            progress.set_progress(2, "Starting analysis…")
            try:
                # Force an immediate paint so the bar appears before heavy work
                if progress.window and progress.window.winfo_exists():
                    progress.window.update()
            except Exception:
                pass

            analysis = self._analyze_current_detection(progress=progress)

            if progress and not getattr(progress, 'closed', False):
                progress.set_progress(100, "Done")
        except Exception as e:
            logger.error(f"Smart Suggest failed: {e}", exc_info=True)
            analysis = None
            outer_err = str(e)
        finally:
            try:
                self.master.config(cursor="")
            except Exception:
                pass
            if progress is not None and not getattr(progress, 'closed', False):
                try:
                    progress.close()
                except Exception:
                    pass

        if analysis is None:
            detail = (
                outer_err
                or getattr(self, "_last_smart_suggest_error", None)
                or "Unknown analysis failure (see log)."
            )
            messagebox.showerror(
                "Analysis Failed",
                "Smart Suggest could not finish analysis.\n\n"
                f"{detail}\n\n"
                "An image appears to be open — this is not always a missing-TIFF problem.\n"
                "Try: Show Mask with Blob/LoG or DoG, or re-open the TIFF from the file list.",
            )
            return

        suggestions = analysis["suggestions"]

        dialog = Toplevel(self.master)
        dialog.title("Smart Suggest")
        dialog.geometry("680x560")
        dialog.attributes('-topmost', 'true')
        self._register_transparent_window(dialog)

        cfg_m = self.image_processor.cell_config
        method = (cfg_m.detection_method or "blob").lower().strip()
        adaptive_on = int(getattr(cfg_m, "adaptive_enabled", 0) or 0) != 0 or method == "adaptive"
        if method == "dog":
            method_note = "DoG"
        elif method in ("blob", "log"):
            method_note = "LoG"
        elif method == "adaptive":
            base = (getattr(cfg_m, "adaptive_base_method", None) or "blob").lower()
            method_note = "DoG" if base == "dog" else "LoG"
        else:
            method_note = method
        if adaptive_on and method != "watershed":
            method_note = f"{method_note} + Adaptive"
        ttk.Label(
            dialog,
            text=f"Smart Suggest — multi-scale analysis (active method: {method_note})",
            font=("Helvetica", 11, "bold"),
        ).pack(pady=(10, 4))

        at_line = ""
        if analysis.get("used_area_tune") and analysis.get("area_tune_summary"):
            ats = analysis["area_tune_summary"]
            at_line = (
                f"Area Tune: {ats['n']} cells, mean d={ats['mean_diameter']}px, "
                f"mean area={ats['mean_area']}px² → area bounds {ats['blob_min_area']}–{ats['blob_max_area']}\n"
            )
        if analysis.get("used_measure_tune") and analysis.get("measure_tune_summary"):
            mts = analysis["measure_tune_summary"]
            mc = mts.get("counts") or {}
            at_line += (
                f"Measure Tune: TP:{mc.get('tp', 0)} FP:{mc.get('fp', 0)} "
                f"FN:{mc.get('fn', 0)} TN:{mc.get('tn', 0)}  "
                f"thr={mts.get('blob_threshold')}  SNR={mts.get('blob_min_local_snr')}\n"
            )
        rd = analysis.get("region_diagnosis") or {}
        recipe = analysis.get("recipe") or rd.get("recipe") or "balanced"
        recipe_labels = {
            "mixed_both": "Mixed (high-BG FPs + low-BG misses)",
            "high_bg_fp": "High-background false positives",
            "low_bg_fn": "Low-background missed cells",
            "recover_clusters": "Recover clusters (after strict BG tune)",
            "global_over": "Global over-detection",
            "global_under": "Global under-detection",
            "balanced": "Balanced",
        }
        recipe_line = f"Recipe: {recipe_labels.get(recipe, recipe)}"
        if rd.get("summary"):
            recipe_line += f"\n{rd['summary']}"
        if rd.get("high_peaks") is not None:
            recipe_line += (
                f"\nBright tiles: peaks={rd.get('high_peaks')} det={rd.get('high_det')}  |  "
                f"Dark tiles: peaks={rd.get('low_peaks')} det={rd.get('low_det')}"
            )
        info = (
            f"Objects: {analysis['num_detections']}   |   "
            f"Density: {analysis['detection_density']}/MP   |   "
            f"LoG peaks: {analysis['log_peaks_strict']} strict / {analysis['log_peaks_loose']} loose\n"
            f"SNR: {analysis['snr']}   |   Contrast: {analysis['contrast']}   |   "
            f"Median size: r≈{analysis['median_object_radius']}px  area≈{analysis['median_object_area']}px\n"
            f"{at_line}"
            f"Suggested sigma: {analysis['suggested_sigma'][0]}–{analysis['suggested_sigma'][1]}   "
            f"threshold≈{analysis['suggested_threshold']}\n"
            f"{recipe_line}"
        )
        ttk.Label(dialog, text=info, justify=tk.LEFT, wraplength=640).pack(pady=4, padx=12)

        if not suggestions:
            ttk.Label(
                dialog,
                text=(
                    "No strong changes suggested — current settings look reasonable for this image.\n"
                    "If results still look wrong, try Measure Tune and click example cells."
                ),
                justify=tk.CENTER,
            ).pack(pady=20, padx=12)
            ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
            return

        canvas = tk.Canvas(dialog, highlightthickness=0, height=300)
        scroll = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=canvas.yview)
        suggestions_frame = ttk.Frame(canvas)
        suggestions_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=suggestions_frame, anchor='nw')
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill='both', expand=True, padx=(10, 0), pady=8)
        scroll.pack(side=tk.RIGHT, fill='y', pady=8, padx=(0, 10))

        suggestion_vars = []
        for suggestion in suggestions:
            var = tk.BooleanVar(value=True)
            suggestion_vars.append((suggestion, var))
            frame = ttk.Frame(suggestions_frame, relief='groove', borderwidth=1)
            frame.pack(fill='x', pady=3, padx=4)
            ttk.Checkbutton(frame, variable=var).pack(side='left', padx=6, pady=4)
            text = f"{suggestion['param']}:  {suggestion['current']}  →  {suggestion['suggested']}"
            ttk.Label(frame, text=text, font=("Helvetica", 10, "bold")).pack(anchor='w', padx=8, pady=(4, 0))
            ttk.Label(frame, text=suggestion['reason'], wraplength=560).pack(anchor='w', padx=8, pady=(0, 6))

        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill='x', padx=10, pady=10)

        def apply_suggestion(sugg):
            cfg = self.image_processor.cell_config
            pcfg = self.image_processor.preprocess_config
            param = sugg['param']
            value = sugg['suggested']
            if param == "detection_method":
                if str(value).lower().strip() == "adaptive":
                    cfg.adaptive_enabled = 1
                    base = (getattr(cfg, "adaptive_base_method", None) or "blob").lower()
                    cfg.detection_method = base if base in ("blob", "dog", "log") else "blob"
                else:
                    cfg.detection_method = value
            elif param == "adaptive_enabled":
                cfg.adaptive_enabled = 1 if value else 0
                # Keep base method as blob/dog (Adaptive is a checkbox, not a radio method)
                m = (cfg.detection_method or "blob").lower().strip()
                if m in ("adaptive", "watershed", ""):
                    base = (getattr(cfg, "adaptive_base_method", None) or "blob").lower()
                    cfg.detection_method = base if base in ("blob", "dog", "log") else "blob"
            elif param == "preprocess_nr_gaussian":
                pcfg.nr_gaussian_sigma = float(value)
            elif param == "preprocess_denoise_method":
                pcfg.denoise_method = value
            elif hasattr(cfg, param):
                # Coerce adaptive flags / ints from JSON-like values
                if param in (
                    "adaptive_enabled",
                    "adaptive_dual_pass",
                    "blob_reject_tissue_edge",
                ):
                    try:
                        value = int(value)
                    except Exception:
                        value = 1 if value else 0
                setattr(cfg, param, value)

        def _record_applied_recipe():
            cfg = self.image_processor.cell_config
            try:
                hist = list(getattr(self, "_smart_suggest_history", []) or [])
                hist.append({
                    "recipe": recipe,
                    "blob_min_local_snr": float(getattr(cfg, "blob_min_local_snr", 0) or 0),
                    "blob_threshold": float(getattr(cfg, "blob_threshold", 0) or 0),
                    "adaptive_enabled": int(getattr(cfg, "adaptive_enabled", 0) or 0),
                    "applied": True,
                })
                self._smart_suggest_history = hist[-8:]
            except Exception:
                pass

        def apply_checked():
            applied = 0
            for sugg, var in suggestion_vars:
                if var.get():
                    apply_suggestion(sugg)
                    applied += 1
            if applied > 0:
                _record_applied_recipe()
            dialog.destroy()
            if applied > 0:
                try:
                    self.show_cell_mask_threshold(calculate=True)
                except Exception:
                    pass
                messagebox.showinfo(
                    "Smart Suggest",
                    f"Applied {applied} change(s) and refreshed the mask.\n"
                    f"(Recipe: {recipe_labels.get(recipe, recipe)})",
                )

        def apply_all():
            for sugg, _var in suggestion_vars:
                apply_suggestion(sugg)
            _record_applied_recipe()
            dialog.destroy()
            try:
                self.show_cell_mask_threshold(calculate=True)
            except Exception:
                pass
            messagebox.showinfo(
                "Smart Suggest",
                f"Applied all suggestions and refreshed the mask.\n"
                f"(Recipe: {recipe_labels.get(recipe, recipe)})",
            )

        def apply_recommended_preset():
            preset = analysis.get("recommended_preset") or {}
            self._apply_blob_settings_dict(preset)
            _record_applied_recipe()
            dialog.destroy()
            try:
                self.show_cell_mask_threshold(calculate=True)
            except Exception:
                pass
            messagebox.showinfo(
                "Smart Suggest",
                "Applied the full regional + LoG recommended preset and refreshed the mask.\n\n"
                f"Recipe: {recipe_labels.get(recipe, recipe)}\n"
                f"sigma {preset.get('blob_min_sigma')}–{preset.get('blob_max_sigma')}, "
                f"thr={preset.get('blob_threshold')}, "
                f"SNR={preset.get('blob_min_local_snr')}, "
                f"area {preset.get('blob_min_area')}–{preset.get('blob_max_area')}",
            )

        ttk.Button(
            button_frame, text="Apply Checked + Refresh Mask", command=apply_checked, width=28
        ).pack(side='left', padx=3)
        ttk.Button(button_frame, text="Apply All", command=apply_all, width=12).pack(side='left', padx=3)
        ttk.Button(
            button_frame, text="Apply Full Preset", command=apply_recommended_preset, width=16
        ).pack(side='left', padx=3)
        ttk.Button(button_frame, text="Close", command=dialog.destroy, width=10).pack(side='right', padx=3)

    def _register_transparent_window(self, window):
        """Register a popup window so it follows the Transparent Mode setting."""
        if window not in self.transparent_windows:
            self.transparent_windows.append(window)

        # Apply current transparency state
        alpha = 0.3 if self.transparent_mode.get() else 1.0
        window.attributes('-alpha', alpha)

        # Best-effort cleanup when the window is closed
        def cleanup(event=None):
            if window in self.transparent_windows:
                self.transparent_windows.remove(window)
        window.bind("<Destroy>", cleanup, add="+")




    def update_brightness(self, value):
        """Slider callback — debounced; does not full-redraw atlas every tick."""
        self.brightness = float(value)
        # Cancel pending redraw so rapid slider motion only paints once
        aid = getattr(self, "_brightness_after_id", None)
        if aid is not None:
            try:
                self.master.after_cancel(aid)
            except Exception:
                pass
            self._brightness_after_id = None
        # ~50ms feels responsive without hammering full-res enhance + show_page
        self._brightness_after_id = self.master.after(50, self._apply_brightness_display)

    def _invalidate_bg_display_cache(self):
        """Drop cached display-sized background (call on load/zoom/image change)."""
        self._bg_display_base_cache = None

    def _bg_display_cache_key(self):
        base = (
            self.original_background
            if self.original_background is not None
            else self.background_image
        )
        if base is None:
            return None
        return (id(base), base.size, round(float(self.view_scale), 5))

    def _get_bg_display_base(self):
        """Resized background for current view_scale, *without* brightness applied.

        Cached so the brightness slider only re-runs a cheap enhance on a small image
        instead of re-enhancing the full-resolution TIFF and redrawing the atlas.
        """
        key = self._bg_display_cache_key()
        if key is None:
            return None
        cached = getattr(self, "_bg_display_base_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]

        base = (
            self.original_background
            if self.original_background is not None
            else self.background_image
        )
        scale = float(self.view_scale) if self.view_scale else 1.0
        img = base
        if scale != 1.0:
            nw = max(1, int(img.width * scale))
            nh = max(1, int(img.height * scale))
            img = img.resize((nw, nh), Image.BILINEAR)
        # Work in RGB for Brightness enhance speed when no alpha needed for display base
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        self._bg_display_base_cache = (key, img)
        return img

    def _apply_brightness_display(self):
        """Fast path: update only the background PhotoImage (no full show_page)."""
        self._brightness_after_id = None
        try:
            base = self._get_bg_display_base()
            if base is None:
                return
            bg_display = self.adjust_image(base)
            self.background_photo = ImageTk.PhotoImage(bg_display)
            # Prefer in-place canvas update if the bg item still exists
            item = getattr(self, "bg_photo_id", None)
            if item is not None:
                try:
                    self.output.itemconfigure(item, image=self.background_photo)
                    return
                except Exception:
                    pass
            # Fallback: full redraw if canvas was rebuilt
            self.show_page()
        except Exception as e:
            logger.debug(f"Fast brightness update failed, falling back to show_page: {e}")
            try:
                self.show_page()
            except Exception:
                pass

    def adjust_image(self, img):
        """Apply current brightness factor. No-op when factor ≈ 1 for speed."""
        factor = 1.0 + (float(getattr(self, "brightness", 0.0)) / 100.0)
        if abs(factor - 1.0) < 1e-4:
            return img
        enhancer = ImageEnhance.Brightness(img)
        return enhancer.enhance(factor)

    def open_user_manual(self):
        """Open the PDF user manual in the system's default viewer (cross-platform)."""
        # The manual lives in the repository root, one level above the Application/ directory
        manual_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "BARCC_User_Manual.pdf")
        )

        if not os.path.exists(manual_path):
            messagebox.showerror(
                "Manual Not Found",
                f"Could not find the user manual at:\n{manual_path}"
            )
            return

        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(manual_path)
            elif system == "Darwin":  # macOS
                subprocess.call(["open", manual_path])
            else:  # Linux and other Unix-like systems
                subprocess.call(["xdg-open", manual_path])
        except Exception as e:
            # Final fallback using the standard library (works on most systems)
            try:
                webbrowser.open(f"file://{manual_path}")
            except Exception as e2:
                messagebox.showerror(
                    "Error Opening Manual",
                    f"Could not open the user manual.\n\n"
                    f"Primary error: {e}\n"
                    f"Fallback error: {e2}"
                )

    # --- Configuration Presets System ---

    def _get_presets_path(self):
        presets_dir = os.path.join(os.path.expanduser("~"), ".barc")
        os.makedirs(presets_dir, exist_ok=True)
        return os.path.join(presets_dir, "presets.json")

    # ------------------------------------------------------------------
    # Export / Import Detection Settings (Portable Config Files)
    # ------------------------------------------------------------------

    def _collect_mask_generation_metadata(self, extra=None):
        """Build a full metadata dict of parameters used to generate the cell mask.

        Includes cell detection, preprocessing, source image info, and optional
        extras (e.g. output paths written during Count Cells).
        """
        cfg = self.image_processor.cell_config
        pcfg = self.image_processor.preprocess_config

        zone_names = {}
        try:
            page = self.current_page
            raw = self.zone_names.get(page, {}) or {}
            zone_names = {str(k): v for k, v in raw.items()}
        except Exception:
            zone_names = {}

        has_manual_add = self.manual_add_mask is not None
        has_manual_remove = self.manual_remove_mask is not None

        meta = {
            "format_version": 1,
            "barcc_version": "8.09.000",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "purpose": "Parameters used to generate the cell mask and regional counts",
            "source": {
                "tiff_filename": self.tiff_filename,
                "tiff_dir": self.tiff_dir,
                "tiff_path": (
                    os.path.join(self.tiff_dir, self.tiff_filename + ".tif")
                    if self.tiff_dir and self.tiff_filename
                    else getattr(self, "current_tiff_path", None)
                ),
                "image_size": (
                    list(self.original_background.size)
                    if getattr(self, "original_background", None) is not None
                    else None
                ),
            },
            "detection_method": cfg.detection_method,
            "cell_detection": dict(cfg.__dict__),
            "preprocessing": dict(pcfg.__dict__),
            "manual_mask_edits": {
                "manual_add_cells": bool(has_manual_add),
                "manual_remove_cells": bool(has_manual_remove),
            },
            "regions": {
                "page": self.current_page,
                "zone_names": zone_names,
                "zone_count": len(zone_names),
            },
            "display": {
                "brightness": getattr(self, "brightness", 0.0),
            },
        }
        if extra:
            meta["outputs"] = extra
        return meta

    def _save_mask_metadata_file(self, out_dir, base_name, extra=None):
        """Write {base_name}_metadata.json into out_dir. Returns path or None."""
        if not out_dir or not base_name:
            return None
        try:
            meta = self._collect_mask_generation_metadata(extra=extra)
            path = os.path.join(out_dir, f"{base_name}_metadata.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, default=str)
            logger.info(f"Mask metadata saved: {path}")
            return path
        except Exception as e:
            logger.error(f"Failed to save mask metadata: {e}")
            return None

    def _binary_mask_to_boundary_ring(self, binary_mask, thickness=2):
        """Convert a filled binary mask into open 'donut' rings (boundary only).

        Each connected component becomes a hollow outline so the underlying image
        remains visible in the blob interior. thickness is ring width in pixels.
        """
        binary = np.asarray(binary_mask)
        if binary.ndim > 2:
            binary = binary.squeeze()
        binary = binary > 0
        if binary.ndim != 2 or not binary.any():
            return np.zeros_like(binary, dtype=bool)

        thickness = int(max(1, thickness))
        try:
            # Label so each blob gets its own closed boundary
            labels = measure.label(binary, connectivity=2)
            # Inner boundaries of labeled regions (open hole in middle)
            ring = segmentation.find_boundaries(labels, mode='inner', background=0)
            if thickness > 1:
                # Thicken the outline slightly for visibility
                ring = morphology.binary_dilation(ring, footprint=disk(thickness - 1))
            # Tiny objects that vanish under inner boundary: fall back to outer boundary
            covered = measure.label(ring, connectivity=2)
            for zid in range(1, labels.max() + 1):
                blob = labels == zid
                if not np.any(ring & blob):
                    ring |= segmentation.find_boundaries(blob.astype(np.uint8), mode='outer')
            return ring.astype(bool)
        except Exception as e:
            logger.debug(f"Boundary ring fallback: {e}")
            # Morphological gradient fallback
            try:
                eroded = morphology.binary_erosion(binary, footprint=disk(thickness))
                ring = binary & ~eroded
                if not ring.any():
                    ring = segmentation.find_boundaries(binary.astype(np.uint8), mode='inner')
                return ring.astype(bool)
            except Exception:
                return binary  # last resort: solid (still visible)

    def _cell_detection_ring_overlay(self, binary_mask, size=None, color=(255, 0, 0), alpha=220, thickness=2):
        """Build an RGBA PIL image with only red donut rings for detected cells.

        size: optional (width, height) to resize the ring mask into.
        """
        ring = self._binary_mask_to_boundary_ring(binary_mask, thickness=thickness)
        if size is not None and (ring.shape[0] != size[1] or ring.shape[1] != size[0]):
            ring_img = Image.fromarray((ring.astype(np.uint8) * 255), mode='L')
            ring_img = ring_img.resize(size, Image.NEAREST)
            ring = np.array(ring_img) > 0
        h, w = ring.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[ring, 0] = color[0]
        rgba[ring, 1] = color[1]
        rgba[ring, 2] = color[2]
        rgba[ring, 3] = alpha
        return Image.fromarray(rgba, 'RGBA')

    def _export_cell_centroids_csv(self, cell_mask, out_dir, base_name):
        """Save one row per detected cell with centroid x, y and pixel area.

        Columns: x, y, area
          - x, y: centroid in image coordinates (x = column, y = row), float pixels
          - area: total pixel count of the connected component

        Writes: <out_dir>/{base_name}_cell_centroids.csv
        Returns path or None.
        """
        if not out_dir or not base_name or cell_mask is None:
            return None

        mask = np.asarray(cell_mask)
        if mask.ndim > 2:
            mask = mask.squeeze()
        binary = mask > 0
        if binary.ndim != 2 or not binary.any():
            # Still write a header-only file so the export is predictable
            path = os.path.join(out_dir, f"{base_name}_cell_centroids.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["x", "y", "area"])
            logger.info(f"Cell centroids CSV (empty): {path}")
            return path

        labels = measure.label(binary, connectivity=2)
        props = measure.regionprops(labels)

        rows = []
        for prop in props:
            # skimage: centroid is (row, col) → y, x
            y, x = prop.centroid
            area = int(prop.area)
            if area <= 0:
                continue
            rows.append({
                "x": float(x),
                "y": float(y),
                "area": area,
            })

        # Stable order: top-to-bottom, then left-to-right
        rows.sort(key=lambda r: (r["y"], r["x"]))

        path = os.path.join(out_dir, f"{base_name}_cell_centroids.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["x", "y", "area"])
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Cell centroids CSV saved ({len(rows)} cells): {path}")
        return path

    def export_detection_settings(self):
        """Export current cell detection + preprocessing settings to a user-chosen JSON file."""
        try:
            default_name = f"barcc_settings_{datetime.now().strftime('%Y%m%d_%H%M')}.json"

            file_path = fd.asksaveasfilename(
                title="Export Detection Settings",
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile=default_name
            )

            if not file_path:
                return

            config_data = self._collect_mask_generation_metadata()
            # Keep portable settings export compatible with import_detection_settings
            config_data = {
                "version": config_data.get("barcc_version", "8.09.000"),
                "detection_method": self.image_processor.cell_config.detection_method,
                "cell_detection": self.image_processor.cell_config.__dict__.copy(),
                "preprocessing": self.image_processor.preprocess_config.__dict__.copy(),
            }

            with open(file_path, "w") as f:
                json.dump(config_data, f, indent=2)

            messagebox.showinfo("Export Successful", f"Settings exported to:\n{file_path}")

        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export settings:\n{e}")

    def import_detection_settings(self):
        """Load cell detection + preprocessing settings from a user-chosen JSON file."""
        try:
            file_path = fd.askopenfilename(
                title="Import Detection Settings",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
            )

            if not file_path:
                return

            with open(file_path, "r") as f:
                data = json.load(f)

            # Apply detection method if present
            if "detection_method" in data:
                dm = data["detection_method"]
                if str(dm).lower().strip() == "adaptive":
                    self.image_processor.cell_config.adaptive_enabled = 1
                    base = (
                        data.get("cell_detection", {}).get("adaptive_base_method")
                        or getattr(self.image_processor.cell_config, "adaptive_base_method", "blob")
                    )
                    base = str(base).lower().strip()
                    self.image_processor.cell_config.detection_method = (
                        base if base in ("blob", "dog", "log") else "blob"
                    )
                else:
                    self.image_processor.cell_config.detection_method = dm

            # Apply cell detection config
            for key, value in data.get("cell_detection", {}).items():
                if hasattr(self.image_processor.cell_config, key):
                    setattr(self.image_processor.cell_config, key, value)

            # Normalize legacy adaptive-as-method after full cell_detection apply
            cfg_imp = self.image_processor.cell_config
            if (cfg_imp.detection_method or "").lower().strip() == "adaptive":
                cfg_imp.adaptive_enabled = 1
                base = (getattr(cfg_imp, "adaptive_base_method", None) or "blob").lower().strip()
                cfg_imp.detection_method = base if base in ("blob", "dog", "log") else "blob"

            # Apply preprocessing config
            for key, value in data.get("preprocessing", {}).items():
                if hasattr(self.image_processor.preprocess_config, key):
                    setattr(self.image_processor.preprocess_config, key, value)

            messagebox.showinfo("Import Successful", "Settings imported successfully.\n\nThe Mask Settings dialog will now close so the new values can be applied.")
            # Close the current Mask Settings window so the user sees the effect when they reopen it
            # We use a small delay + destroy pattern inside the dialog context later

        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not load settings file:\n{e}")

    def load_presets(self):
        path = self._get_presets_path()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_presets(self, presets_dict):
        path = self._get_presets_path()
        try:
            with open(path, "w") as f:
                json.dump(presets_dict, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save presets: {e}")

    def save_current_as_preset(self, name=None):
        if name is None:
            name = simpledialog.askstring("Save Preset", "Enter preset name:")
            if not name:
                return

        presets = self.load_presets()

        preset_data = {
            "cell_detection": self.image_processor.cell_config.__dict__.copy(),
            "preprocessing": self.image_processor.preprocess_config.__dict__.copy(),
        }
        presets[name] = preset_data
        self.save_presets(presets)
        messagebox.showinfo("Preset Saved", f"Preset '{name}' saved successfully.")

    def load_preset(self, name):
        presets = self.load_presets()
        if name not in presets:
            messagebox.showerror("Error", f"Preset '{name}' not found.")
            return False

        data = presets[name]
        try:
            for key, value in data.get("cell_detection", {}).items():
                if hasattr(self.image_processor.cell_config, key):
                    setattr(self.image_processor.cell_config, key, value)

            for key, value in data.get("preprocessing", {}).items():
                if hasattr(self.image_processor.preprocess_config, key):
                    setattr(self.image_processor.preprocess_config, key, value)

            return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load preset: {e}")
            return False

    def delete_preset(self, name):
        presets = self.load_presets()
        if name in presets:
            del presets[name]
            self.save_presets(presets)
            messagebox.showinfo("Preset Deleted", f"Preset '{name}' deleted.")
        else:
            messagebox.showerror("Error", f"Preset '{name}' not found.")

    def _show_busy_dialog(self, title="Working"):
        """Create a progress dialog with a determinate loading bar.
        Returns an object with .set_progress(percent, message) and .close() methods.
        The dialog is hardened so that the user closing it (X button) will never
        cause the rest of the operation (or the whole app) to crash.
        """
        class ProgressDialog:
            def __init__(self, parent, title):
                self.window = Toplevel(parent)
                self.window.title(title)
                self.window.attributes('-topmost', True)
                self.window.resizable(False, False)
                self.closed = False

                # Strongly disable the close button / Alt+F4 etc.
                self.window.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

                self.label = ttk.Label(self.window, text="Initializing...")
                self.label.pack(padx=20, pady=(15, 5))

                self.progress = ttk.Progressbar(
                    self.window, 
                    orient='horizontal', 
                    length=280, 
                    mode='determinate',
                    maximum=100
                )
                self.progress.pack(padx=20, pady=(0, 15))

                self.window.update_idletasks()

            def _on_close_attempt(self):
                """User tried to close the dialog early. Mark as closed so all future
                calls to set_progress/close are no-ops and cannot raise."""
                self.closed = True
                self._safe_destroy()

            def _safe_destroy(self):
                try:
                    if self.window and self.window.winfo_exists():
                        self.window.destroy()
                except Exception:
                    pass

            def set_progress(self, percent, message=None):
                if getattr(self, 'closed', False):
                    return
                try:
                    self.progress['value'] = max(0, min(100, percent))
                    if message:
                        self.label.config(text=message)
                    if self.window and self.window.winfo_exists():
                        # update() paints the bar; update_idletasks alone can leave a frozen look
                        self.window.update_idletasks()
                        self.window.update()
                except Exception:
                    # Window was closed externally or became invalid — treat as closed forever
                    self.closed = True

            def close(self):
                if getattr(self, 'closed', False):
                    return
                self.closed = True
                self._safe_destroy()

        dialog = ProgressDialog(self.master, title)
        self._register_transparent_window(dialog.window)
        return dialog

    def save_state(self):
        self.state_manager.save_state(self)

    def undo(self, event=None):
        """Undo the last user action. Can be called repeatedly."""
        self.state_manager.undo(self)

    def _undo_event(self, event=None):
        """Keyboard handler (Ctrl+Z)."""
        self.undo(event)

    # ------------------------------------------------------------------
    # ZOOM FEATURE
    # ------------------------------------------------------------------
    def _bind_mousewheel(self):
        """Bind mouse wheel for zoom (cross-platform)."""
        self.output.bind("<MouseWheel>", self._on_mousewheel)      # Windows
        self.output.bind("<Button-4>", self._on_mousewheel)        # Linux scroll up
        self.output.bind("<Button-5>", self._on_mousewheel)        # Linux scroll down

    def _on_mousewheel(self, event):
        """Handle mouse wheel zoom centered on mouse position."""
        # Determine direction and factor
        if event.num == 4 or event.delta > 0:
            factor = 1.15  # zoom in
        else:
            factor = 1 / 1.15  # zoom out

        self._apply_zoom(factor, event)

    def _apply_zoom(self, factor, event=None):
        """Apply zoom factor, keeping alignment of all layers."""
        new_scale = self.view_scale * factor
        if new_scale < self.min_scale or new_scale > self.max_scale:
            return

        # Get zoom center in canvas coordinates
        if event is not None:
            cx = self.output.canvasx(event.x)
            cy = self.output.canvasy(event.y)
        else:
            # Fallback to center of visible area
            cx = self.output.canvasx(self.output.winfo_width() / 2)
            cy = self.output.canvasy(self.output.winfo_height() / 2)

        # Scale all paint strokes around the mouse point (this keeps them aligned with image content)
        # Note: because we delete finished strokes' items on mouse-up (in reset), the only
        # 'paint' items here should be the current in-progress stroke (rare during wheel).
        self.output.scale('paint', cx, cy, factor, factor)

        # Bake the (live) stroke and remove temporary items so show_page redraws cleanly
        # from the paint_layer (authoritative, model-space) without scaled vectors causing
        # duplication or displacement in future commits or saves.
        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()
        self.output.delete('paint')

        # img_x/img_y are *model-space* offsets (same units as the TIFF / atlas
        # native pixels). Do NOT re-project them around the mouse — that moved the
        # atlas relative to the background (always drawn from model origin).
        # Only view_scale changes; both layers scale the same way and stay locked.
        old_scale = self.view_scale
        self.view_scale = new_scale
        self._invalidate_bg_display_cache()

        # Redraw, but preserve any active mask overlay so it doesn't disappear on zoom
        if self.editing_mask and self.current_mask is not None:
            # Keep detection rings + add/remove paint visible while editing
            if getattr(self, "splitting_cells", False):
                try:
                    self.show_cell_mask_threshold(calculate=False)
                except Exception:
                    self.show_page()
            else:
                self._refresh_mask_edit_display()
        elif getattr(self, 'showing_auto_mask', False):
            # Preserve the "Show Mask" / cell detection mask view
            self.show_cell_mask_threshold(calculate=False)
        else:
            self.show_page()

        # Update scroll region
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

        # Keep the model point under the cursor roughly fixed via canvas scan pan
        try:
            if old_scale > 0:
                mx = cx / old_scale
                my = cy / old_scale
                # After zoom, that model point sits at (mx*new_scale, my*new_scale)
                new_cx = mx * new_scale
                new_cy = my * new_scale
                self.output.scan_mark(int(round(new_cx)), int(round(new_cy)))
                self.output.scan_dragto(int(round(cx)), int(round(cy)), gain=1)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Alt + Drag Panning
    # ------------------------------------------------------------------
    def _start_pan(self, event):
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._pan_start_scrollx = self.output.xview()[0]
        self._pan_start_scrolly = self.output.yview()[0]
        self.output.config(cursor="fleur")

    def _do_pan(self, event):
        if self._pan_start_x is None:
            return
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y

        # Convert pixel delta to scroll fraction
        total_width = self.output.winfo_width()
        total_height = self.output.winfo_height()

        if total_width > 0:
            new_x = self._pan_start_scrollx - (dx / total_width)
            self.output.xview_moveto(new_x)
        if total_height > 0:
            new_y = self._pan_start_scrolly - (dy / total_height)
            self.output.yview_moveto(new_y)

    def _end_pan(self, event):
        self._pan_start_x = None
        self._pan_start_y = None
        self.output.config(cursor="")

    # ------------------------------------------------------------------
    # Coordinate conversion helpers (critical for correct drawing after zoom)
    # ------------------------------------------------------------------
    def _canvas_to_image(self, cx, cy):
        """Convert canvas coordinates to image (model) coordinates."""
        if self.view_scale == 0:
            return int(cx), int(cy)
        return int(cx / self.view_scale), int(cy / self.view_scale)

    def _image_to_canvas(self, ix, iy):
        """Convert image (model) coordinates to canvas coordinates for display."""
        return ix * self.view_scale, iy * self.view_scale

    def _paint_uses_atlas_space(self):
        """Paint zones share the atlas mask coordinate system when an atlas is loaded."""
        return getattr(self, "atlas_filetype", None) in ("pdf", "allen")

    def _canvas_to_paint_model(self, cx, cy):
        """Canvas → paint/zone model space (atlas model if atlas loaded, else image)."""
        if self._paint_uses_atlas_space():
            mx, my = self._canvas_to_atlas(cx, cy)
            return int(round(mx)), int(round(my))
        return self._canvas_to_image(cx, cy)

    def _paint_model_to_canvas(self, ix, iy):
        """Paint/zone model → canvas (inverse of _canvas_to_paint_model)."""
        s = float(self.view_scale) if self.view_scale else 1.0
        if self._paint_uses_atlas_space():
            return (float(ix) + float(self.img_x)) * s, (float(iy) + float(self.img_y)) * s
        return self._image_to_canvas(ix, iy)

    def _paint_model_to_image(self, ix, iy):
        """Paint model → background image pixels (for paint_layer baking at 0,0)."""
        if self._paint_uses_atlas_space():
            return int(round(float(ix) + float(self.img_x))), int(round(float(iy) + float(self.img_y)))
        return int(ix), int(iy)

    def _ensure_zone_mask_for_paint(self):
        """Return (mask_img L-mode, draw) sized for the active coordinate system.

        With an atlas loaded, keep/merge into the existing atlas zone mask so painted
        regions join Allen/PDF zones for Count Cells. Without atlas, use image size.
        """
        page = self.current_page
        if page is None:
            self.current_page = 0
            page = 0

        if page not in self.zone_counters:
            self.zone_counters[page] = 0
        if page not in self.zone_names:
            self.zone_names[page] = {}

        # Seed counter above any existing mask / name ids
        max_id = int(self.zone_counters.get(page, 0) or 0)
        for zid in self.zone_names.get(page, {}).keys():
            try:
                max_id = max(max_id, int(zid))
            except Exception:
                pass
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                m0 = np.array(self.mask_images[page])
                if m0.size:
                    max_id = max(max_id, int(m0.max()))
            except Exception:
                pass
        self.zone_counters[page] = max_id

        if page in self.mask_images and self.mask_images[page] is not None:
            mask_img = self.mask_images[page].copy()
            if mask_img.mode != "L":
                mask_img = mask_img.convert("L")
            return mask_img, ImageDraw.Draw(mask_img)

        # Create empty mask
        if self._paint_uses_atlas_space() and page in self.base_page_images and self.base_page_images[page] is not None:
            target_size = self.base_page_images[page].size
        elif self.original_background is not None:
            target_size = self.original_background.size
        elif self.background_image is not None:
            target_size = self.background_image.size
        else:
            try:
                target_size = (max(64, self.output.winfo_width()), max(64, self.output.winfo_height()))
            except Exception:
                target_size = (1024, 1024)

        mask_img = Image.new("L", target_size, 0)
        self.mask_images[page] = mask_img.copy()
        return mask_img, ImageDraw.Draw(mask_img)

    def _canvas_to_zone_model(self, cx, cy):
        """Map canvas coordinates to the model/pixel space used by the zone mask for the
        currently relevant layer (paint or atlas).

        - Painted regions (and baked 'img'/'png' layers) store their masks in background/image
          pixel space (no img_x/y offset). Use _canvas_to_image semantics.
        - Atlas (pdf) regions use the rendered page's model space (with img_x/y placement offset).

        This allows edge grab, border drag, and per-region translate/deform to work
        correctly and consistently for painted regions exactly like atlas regions.
        """
        if getattr(self, 'atlas_filetype', None) in ('pdf', 'allen'):
            # PDF and Allen plates are placed with img_x/img_y (atlas model space)
            return self._canvas_to_atlas(cx, cy)
        else:
            # Paint zones live in the main image/background pixel coordinate space
            ix, iy = self._canvas_to_image(cx, cy)
            return float(ix), float(iy)

    def _rebuild_paint_vectors(self):
        """Rebuild temporary 'paint' canvas items from paint_group_data for naming support.
        Called after show_page/zoom to restore vectors at current scale so right-click
        can find them and turn yellow. Uses model_points converted to current canvas coords.
        """
        if not self.paint_group_data:
            return
        # Clean any existing
        self.output.delete('paint')
        for group_tag, data_list in self.paint_group_data.items():
            if not data_list or not group_tag.startswith('paintgroup_'):
                continue
            # Collect full points in order
            points = []
            width = 3
            fill = self.DEFAULT_COLOR
            if group_tag in self.named_paint_groups and self.named_paint_groups[group_tag]:
                fill = '#ffcc00'
            for rec in data_list:
                mp = rec.get('model_points', [])
                for j in range(0, len(mp), 2):
                    ix = mp[j]
                    iy = mp[j + 1]
                    cx, cy = self._image_to_canvas(ix, iy)
                    points.append((cx, cy))
                w = rec.get('width', width)
                try:
                    width = max(width, int(float(w)))
                except:
                    pass
            if len(points) < 2:
                continue
            # dedup consecutive
            deduped = [points[0]]
            for p in points[1:]:
                if p != deduped[-1]:
                    deduped.append(p)
            points = deduped
            if len(points) < 2:
                continue
            # flatten for create_line
            flat_coords = [c for p in points for c in p]
            self.output.create_line(
                flat_coords,
                width=width,
                fill=fill,
                capstyle=tk.ROUND,
                smooth=tk.TRUE,
                splinesteps=36,
                tags=('paint', group_tag)
            )

    def load_page_image(self):
        if self.atlas_filetype: 
            if self.current_page not in self.page_images:
                if self.atlas_filetype == 'pdf':
                    img = self.pdf_handler.render_page(self.current_page, self.zoom)
                    logger.debug(f"Creating new page image: mode={img.mode}, size={img.size}")
                    # Store clean base (no yellow tints) for per-region editing + rebuilds
                    self.base_page_images[self.current_page] = img.copy()
                    self.page_images[self.current_page] = img  # will be rebuilt with overlays when zones exist
                    # Only for true multi-page atlas (PDF): initialize per-page zone/mask state.
                    # Do NOT reset for 'img' (baked paint from Stop/Count) or 'png' (loaded paint layer):
                    # those would clobber zones/masks that _convert_named_paints_to_zones just
                    # registered from the user's right-click named paint regions (and the first
                    # stop_paint's show_page would otherwise wipe the first named region's data
                    # before count_cells could use it).
                    self.mask_images[self.current_page] = Image.new('L', (img.width, img.height), 0)
                    self.zone_counters[self.current_page] = 0
                    self.zone_names[self.current_page] = {}
                elif self.atlas_filetype == 'allen':
                    # Allen plates are pre-installed by _load_allen_plate_data (base + masks + names).
                    # Never wipe zone_names / mask_images here.
                    img = getattr(self, 'img', None)
                    if img is None:
                        img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                    if self.current_page not in self.base_page_images:
                        self.base_page_images[self.current_page] = img.copy()
                    self.page_images[self.current_page] = img
                else:
                    # 'img' or 'png' etc.: just cache the image content for display/layers.
                    # Paint-defined zones (from name_painted_region + convert, or count ensure)
                    # and mask_images must be preserved; the count_cells guard and convert
                    # paths are responsible for them.
                    img = self.img
                    logger.debug(f"Creating new page image: mode={img.mode}, size={img.size}")
                    if self.current_page not in self.base_page_images:
                        self.base_page_images[self.current_page] = img.copy()
                    self.page_images[self.current_page] = img
                    # Intentionally no reset of mask_images / zone_names / zone_counters here.
            
            current_img = self.page_images[self.current_page]
            logger.debug(f"Loaded page image: mode={current_img.mode}, size={current_img.size}")
            return current_img

        # No atlas_filetype (e.g. after reset or pure TIFF/paint start) or page not populated:
        # return/provide a safe blank so show_page doesn't crash on KeyError.
        if self.current_page not in self.page_images:
            if getattr(self, 'img', None) is not None:
                img = self.img
                if self.current_page not in getattr(self, 'base_page_images', {}):
                    self.base_page_images[self.current_page] = img.copy()
                self.page_images[self.current_page] = img
            else:
                img = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
                self.page_images[self.current_page] = img
        current_img = self.page_images[self.current_page]
        logger.debug(f"Loaded page image: mode={current_img.mode}, size={current_img.size}")
        return current_img

    def show_page(self, mask=None):
        if mask is None:
            self.showing_auto_mask = False

        # Deselect region transform target if we've switched pages
        if self.selected_page is not None and self.selected_page != self.current_page:
            self.selected_zone_id = None
            self.selected_page = None
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self.original_full_contour_for_edit = None
            self._edge_pending_deselect = False
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.region_move_mode.set(False)
            self.crop_mode = False
            self.crop_mode_var.set(False)
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self.edit_mode = False
            self.edit_mode_var.set(False)

        self._update_ribbon_selection()

        # Keep any active red edge highlight in the correct screen position after pan/zoom/page change
        if getattr(self, 'active_edge', None) is not None:
            self._update_edge_highlight()

        img = self.load_page_image() or Image.new('RGBA', (1, 1), (0, 0, 0, 0))

        self.output.delete("all")

        scale = self.view_scale

        # Allen Nissl reference strip: 30% of main image size, placed above y=0
        self._draw_allen_nissl_reference(scale)

        if self.background_image:
            # Resize first (cached), then brightness — never enhance full-res TIFF every frame
            base_bg = self._get_bg_display_base()
            if base_bg is None:
                base_bg = (
                    self.original_background
                    if self.original_background is not None
                    else self.background_image
                )
                if scale != 1.0:
                    base_bg = base_bg.resize(
                        (max(1, int(base_bg.width * scale)), max(1, int(base_bg.height * scale))),
                        Image.BILINEAR,
                    )
            bg_display = self.adjust_image(base_bg)

            self.background_photo = ImageTk.PhotoImage(bg_display)
            self.bg_photo_id = self.output.create_image(0, 0,
                                                       image=self.background_photo,
                                                       anchor='nw',
                                                       tag='image')

            # === Draw persistent paint layer (this fixes the "paint disappears on zoom" bug) ===
            if self.paint_layer is not None:
                paint_display = self.paint_layer
                if scale != 1.0:
                    pw = max(1, int(paint_display.width * scale))
                    ph = max(1, int(paint_display.height * scale))
                    paint_display = paint_display.resize((pw, ph), Image.BILINEAR)
                self.paint_photo = ImageTk.PhotoImage(paint_display)
                self.paint_photo_id = self.output.create_image(0, 0,
                                                               image=self.paint_photo,
                                                               anchor='nw',
                                                               tag='paint_layer')

            if mask is not None:
                mask_display = mask
                if scale != 1.0:
                    mw = max(1, int(mask_display.width * scale))
                    mh = max(1, int(mask_display.height * scale))
                    mask_display = mask_display.resize((mw, mh), Image.NEAREST)
                self.mask_photo = ImageTk.PhotoImage(mask_display)
                offset_x = bg_display.width + 10
                self.bg_mask_photo_id = self.output.create_image(offset_x, 0,
                                                                image=self.background_photo,
                                                                anchor='nw',
                                                                tag='image')
                self.mask_photo_id = self.output.create_image(0, 0,
                                                             image=self.mask_photo,
                                                             anchor='nw',
                                                             tag='mask')

        # Scale and place the atlas overlay at the (already scaled) self.img_x / self.img_y
        # Guard: if atlas is the paint content (set by save_paint in stop_paint etc.) and we have
        # a background + paint_layer, skip drawing it here to avoid duplicating the painted
        # regions (paint_layer is at 0,0; atlas would be at img_x/img_y which may be offset after zoom).
        skip_atlas = False
        if self.atlas_filetype == 'img' and self.background_image is not None and self.paint_layer is not None:
            skip_atlas = True

        if not skip_atlas:
            atlas_display = img
            if scale != 1.0:
                aw = max(1, int(img.width * scale))
                ah = max(1, int(img.height * scale))
                # BILINEAR blurs 1px borders; use NEAREST for Allen structure outlines
                resample = Image.NEAREST if self.atlas_filetype == 'allen' else Image.BILINEAR
                atlas_display = img.resize((aw, ah), resample)

            self.photo = ImageTk.PhotoImage(atlas_display)
            # img_x/img_y are model-space offsets (native image/atlas pixels);
            # convert to canvas by multiplying view_scale so zoom keeps atlas
            # locked to the background (also drawn from model origin * scale).
            display_img_x = float(self.img_x) * float(scale)
            display_img_y = float(self.img_y) * float(scale)

            self.output.create_image(display_img_x, display_img_y,
                                   image=self.photo,
                                   anchor='nw',
                                   tag='atlas')

        # Label placement base: atlas overlay offset (or 0 when mask is image-sized)
        try:
            label_base_x = float(self.img_x) * float(scale)
            label_base_y = float(self.img_y) * float(scale)
        except Exception:
            label_base_x, label_base_y = 0.0, 0.0

        # --- Draw Zone Labels and Counts on the main image ---
        if self.show_zone_labels_var.get() and self.last_df is not None and self.current_page in self.mask_images:
            try:
                mask = np.array(self.mask_images[self.current_page])
                mask_h, mask_w = mask.shape
                zone_data = self.last_df.set_index('Zone')['Cell_Count'].to_dict() if 'Zone' in self.last_df.columns else {}

                label_offset_x = label_base_x
                label_offset_y = label_base_y
                if self.background_image is not None:
                    bg_w, bg_h = self.background_image.size
                    if abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5:
                        label_offset_x = 0
                        label_offset_y = 0

                for zone_name, count in zone_data.items():
                    zone_id = None
                    for zid, zname in self.zone_names.get(self.current_page, {}).items():
                        if zname == zone_name:
                            zone_id = zid
                            break

                    if zone_id is None:
                        continue

                    coords = np.where(mask == zone_id)
                    if len(coords[0]) == 0:
                        continue

                    cy = int(np.mean(coords[0]))
                    cx = int(np.mean(coords[1]))
                    screen_x = cx * scale + label_offset_x
                    screen_y = cy * scale + label_offset_y

                    label_text = f"{zone_name}\n({count})"
                    self.output.create_text(
                        screen_x, screen_y, text=label_text, fill="yellow",
                        font=("Helvetica", 10, "bold"), anchor="center",
                        tags="zone_label",
                    )
            except Exception as e:
                logger.warning(f"Failed to draw zone labels: {e}")

        # --- Draw Zone Labels and Mean Intensities (Axons and Nets) ---
        if (
            self.show_zone_intensity_labels_var.get()
            and getattr(self, "last_intensity_df", None) is not None
            and self.current_page in self.mask_images
        ):
            try:
                mask = np.array(self.mask_images[self.current_page])
                mask_h, mask_w = mask.shape
                idf = self.last_intensity_df
                if "Zone" in idf.columns and "Mean_Intensity" in idf.columns:
                    intensity_map = {}
                    for _, row in idf.iterrows():
                        intensity_map[str(row["Zone"])] = row["Mean_Intensity"]

                    label_offset_x = label_base_x
                    label_offset_y = label_base_y
                    if self.background_image is not None:
                        bg_w, bg_h = self.background_image.size
                        if abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5:
                            label_offset_x = 0
                            label_offset_y = 0

                    # Slight vertical offset when both count and intensity labels are on
                    y_nudge = 18 if self.show_zone_labels_var.get() else 0

                    for zone_name, mean_i in intensity_map.items():
                        zone_id = None
                        for zid, zname in self.zone_names.get(self.current_page, {}).items():
                            if zname == zone_name:
                                zone_id = zid
                                break
                        if zone_id is None:
                            continue
                        coords = np.where(mask == zone_id)
                        if len(coords[0]) == 0:
                            continue
                        cy = int(np.mean(coords[0]))
                        cx = int(np.mean(coords[1]))
                        screen_x = cx * scale + label_offset_x
                        screen_y = cy * scale + label_offset_y + y_nudge
                        if mean_i is None or (isinstance(mean_i, float) and np.isnan(mean_i)):
                            i_txt = "—"
                        else:
                            i_txt = f"{float(mean_i):.1f}"
                        label_text = f"{zone_name}\n(I={i_txt})"
                        self.output.create_text(
                            screen_x, screen_y, text=label_text, fill="#7FDBFF",
                            font=("Helvetica", 10, "bold"), anchor="center",
                            tags="zone_intensity_label",
                        )
            except Exception as e:
                logger.warning(f"Failed to draw intensity labels: {e}")

        # Update scroll region
        self.output.config(scrollregion=self.output.bbox(tk.ALL))

        # Rebuild vector paint items from durable data if present.
        # This ensures right-click naming (yellow highlight) works even after
        # show_page or zoom has cleaned the items. Uses current scale.
        if self.paint_group_data:
            self._rebuild_paint_vectors()

        # Re-draw any persistent selected edge highlight (red) after delete("all").
        # Keeps the illumination visible after pan/zoom/show_page while an edge is selected.
        if getattr(self, 'selected_edge_full_contour', None) is not None and not getattr(self, 'edge_grab_active', False):
            if getattr(self, 'active_edge', None) is not None:
                self._draw_edge_highlight(self.active_edge)
            else:
                self._draw_edge_highlight()

        # Re-draw crop selection outline if user is still adjusting it
        if getattr(self, "crop_mode", False) and getattr(self, "crop_pending", False) and getattr(
            self, "crop_box", None
        ):
            try:
                self._draw_crop_outline()
            except Exception:
                pass


    def img_white_to_transparent(self, img):
        img_array = np.array(img)
        white_mask = np.all(img_array[:, :, :3] >= 250, axis=-1)
        img_array[white_mask, 3] = 0
        img = Image.fromarray(img_array)
        return img

    def _canvas_to_atlas(self, canvas_x, canvas_y):
        """Convert canvas coordinates to atlas model/native coordinates.

        ``img_x`` / ``img_y`` are model-space offsets (same units as atlas pixels).
        Display position is ``(img_x * view_scale, img_y * view_scale)``.
        """
        if self.view_scale <= 0:
            return 0.0, 0.0
        model_x = (float(canvas_x) / self.view_scale) - float(self.img_x)
        model_y = (float(canvas_y) / self.view_scale) - float(self.img_y)
        return model_x, model_y

    def _rebuild_page_overlays(self, page=None):
        """Rebuild page_images[page] by taking the clean base and applying yellow (or orange for selected)
        tint overlays based on the current mask labels. This enables clean per-region edits without
        losing the underlying atlas artwork.

        For Allen structure-border atlases: apply light fills first, then re-composite pure
        black borders on top so fills never hide the drawing (PDF-like).
        """
        if page is None:
            page = self.current_page
        if page not in self.base_page_images:
            # Fallback: promote current page image as base (for legacy 'img' atlas cases)
            if page in self.page_images:
                self.base_page_images[page] = self.page_images[page].copy()
            else:
                return
        base = self.base_page_images[page].convert('RGBA').copy()
        is_allen = getattr(self, 'atlas_filetype', None) == 'allen'

        if page in self.mask_images and self.mask_images[page] is not None:
            m = np.array(self.mask_images[page])
            if m.shape[0] != base.size[1] or m.shape[1] != base.size[0]:
                m = np.array(self.mask_images[page].resize(base.size, Image.NEAREST))

            # Build a separate fill layer so we don't erase black borders baked into base.
            # Allen: hollow by default (borders only); fill only the actively selected zone.
            # PDF/painted: keep light yellow on named zones; orange for selected.
            fill = np.zeros((base.size[1], base.size[0], 4), dtype=np.uint8)
            for zid in np.unique(m):
                if zid == 0:
                    continue
                reg = (m == zid)
                is_selected = (
                    self.selected_zone_id is not None
                    and self.selected_page == page
                    and int(zid) == int(self.selected_zone_id)
                )
                if is_allen:
                    if is_selected:
                        # Prefer clicked connected component (one hemisphere) over whole zone ID
                        reg_sel = self._selected_component_mask(m, int(zid))
                        fill[reg_sel, :3] = [255, 140, 0]  # orange selected
                        fill[reg_sel, 3] = 70
                    # else: leave transparent (hollow outlines only)
                else:
                    if is_selected:
                        fill[reg, :3] = [255, 140, 0]
                        fill[reg, 3] = 50
                    else:
                        fill[reg, :3] = [255, 255, 0]
                        fill[reg, 3] = 18

            if is_allen:
                # Always re-compose pure black borders; optional selected fill underneath.
                # Yellow outline is drawn *on the atlas layer* so it stays registered under
                # Move/Scale/Rotate (paint-layer contours used image coords and misaligned).
                borders = getattr(self, 'allen_borders_pure', None)
                if borders is None:
                    borders = base
                elif borders.size != base.size:
                    borders = borders.resize(base.size, Image.NEAREST)
                if np.any(fill[..., 3] > 0):
                    fill_img = Image.fromarray(fill, 'RGBA')
                    composed = Image.alpha_composite(
                        Image.new('RGBA', base.size, (0, 0, 0, 0)), fill_img
                    )
                    composed = Image.alpha_composite(composed, borders.convert('RGBA'))
                else:
                    composed = borders.convert('RGBA')

                # Selected zone: yellow edge pixels only (no polyline/curve — avoids diamond chords)
                if (
                    self.selected_zone_id is not None
                    and self.selected_page == page
                ):
                    try:
                        zid_sel = int(self.selected_zone_id)
                        binr = self._selected_component_mask(m, zid_sel)
                        if binr.any():
                            try:
                                from skimage.segmentation import find_boundaries
                                yedge = find_boundaries(binr.astype(np.uint8), mode="outer")
                            except Exception:
                                er = morphology.binary_erosion(binr, morphology.disk(1))
                                yedge = binr & ~er
                            comp_arr = np.array(composed)
                            # thicken by 1px for visibility
                            try:
                                yedge = morphology.binary_dilation(yedge, morphology.disk(1))
                            except Exception:
                                pass
                            comp_arr[yedge, 0] = 255
                            comp_arr[yedge, 1] = 255
                            comp_arr[yedge, 2] = 0
                            comp_arr[yedge, 3] = 255
                            composed = Image.fromarray(comp_arr, "RGBA")
                    except Exception as e:
                        logger.debug(f"Allen selection contour failed: {e}")

                self.page_images[page] = composed
                return

            if np.any(fill[..., 3] > 0):
                fill_img = Image.fromarray(fill, 'RGBA')
                composed = Image.alpha_composite(base, fill_img)
                self.page_images[page] = composed
                return

        self.page_images[page] = base

    def import_atlas(self):
        logger.info("Opening file dialog for atlas selection")
        self.save_state()
        path = fd.askopenfilename(filetypes=[("PDF files", "*.pdf"), ("PDF files", "*.ai")])
        if path:
            logger.info(f"Opening atlas file: {path}")
            self.path = path
            self.doc, self.num_pages = self.pdf_handler.open_pdf(self.path)
            self.atlas_filetype = 'pdf'
            self.allen_zone_meta = {}
            self.allen_nissl_reference = None
            self.allen_nissl_photo = None
            self.zoom = 1.0
            self.view_scale = 1.0
            self.img_x = 0
            self.img_y = 0
            self.current_page = 0
            self.page_images = {}
            self.mask_images = {}
            self.base_page_images = {}
            self.zone_counters = {}
            self.zone_names = {}
            self.selected_zone_id = None
            self.selected_page = None
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.original_full_contour_for_edit = None
            self.selected_edge_full_contour = None
            self._edge_pending_deselect = False
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.region_move_mode.set(False)
            self.crop_mode = False
            self.crop_mode_var.set(False)
            self.edit_mode = False
            self.edit_mode_var.set(False)
            self.named_paint_groups.clear()
            self.paint_group_data.clear()
            self.painted_zone_outlines.clear()
            clear_preprocess_cache()
            self.show_page()

    # ------------------------------------------------------------------
    # Allen Mouse Reference Atlas (Phase 1 + 2)
    # ------------------------------------------------------------------

    def download_full_allen_atlas(self):
        """Pre-download all annotated Allen plates into the local cache (~/.barc/allen_cache).

        Subsequent Import Allen Atlas / plate loads read from this folder when present.
        """
        try:
            from allen_atlas import (
                ALLEN_ATLASES,
                cache_dir,
                check_api_reachable,
                download_full_atlas,
                plate_cache_status,
            )
        except ImportError as e:
            messagebox.showerror(
                "Allen Atlas",
                f"Could not import allen_atlas module:\n{e}\n\n"
                "Ensure allen_atlas.py is next to barcc.py.",
            )
            return

        win = Toplevel(self.master)
        win.title("Download Full Allen Atlas")
        win.geometry("520x360")
        win.attributes("-topmost", "true")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._register_transparent_window(win)

        plane_var = tk.StringVar(value="coronal")
        ds_var = tk.StringVar(value="3 (default)")
        status_var = tk.StringVar(value="")
        progress_var = tk.DoubleVar(value=0.0)
        cancel_flag = {"cancel": False}

        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text="Download all annotated Allen plates to a local folder.\n"
                 "Loads after this will use the cache (no re-download).",
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 8))

        row = ttk.Frame(frm)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="Plane:").pack(side=tk.LEFT)
        ttk.Radiobutton(row, text="Coronal (P56, ~132 plates)", variable=plane_var, value="coronal").pack(
            side=tk.LEFT, padx=6
        )
        ttk.Radiobutton(row, text="Sagittal (P56, ~21 plates)", variable=plane_var, value="sagittal").pack(
            side=tk.LEFT, padx=6
        )

        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Nissl quality (downsample):").pack(side=tk.LEFT)
        ds_box = ttk.Combobox(
            row2,
            width=14,
            state="readonly",
            textvariable=ds_var,
            values=["2 (high)", "3 (default)", "4 (fast)", "5 (preview)"],
        )
        ds_box.pack(side=tk.LEFT, padx=6)

        cache_label = ttk.Label(frm, text=f"Cache folder:\n{cache_dir()}", wraplength=480, justify=tk.LEFT)
        cache_label.pack(anchor="w", pady=8)

        status_lbl = ttk.Label(frm, textvariable=status_var, wraplength=480, justify=tk.LEFT)
        status_lbl.pack(anchor="w", pady=4)
        pbar = ttk.Progressbar(frm, variable=progress_var, maximum=100, mode="determinate")
        pbar.pack(fill="x", pady=6)

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x", pady=8)

        def _ds():
            try:
                return int((ds_var.get() or "3").split()[0])
            except Exception:
                return 3

        def refresh_status(*_a):
            try:
                st = plate_cache_status(plane_var.get(), downsample=_ds())
                status_var.set(
                    f"{ALLEN_ATLASES[plane_var.get()]['name']}: "
                    f"{st['complete']}/{st['total']} plates fully cached "
                    f"(Nissl {st['nissl_cached']}, SVG {st['svg_cached']})"
                )
            except Exception as e:
                status_var.set(f"Could not read cache status: {e}")

        def start_download():
            ok, msg = check_api_reachable(timeout=20)
            if not ok:
                messagebox.showerror(
                    "Allen Atlas",
                    "Cannot reach the Allen Brain Atlas API.\n\n"
                    f"{msg}\n\n"
                    f"Already-cached files still work from:\n{cache_dir()}",
                    parent=win,
                )
                return
            cancel_flag["cancel"] = False
            start_btn.configure(state=tk.DISABLED)
            close_btn.configure(state=tk.DISABLED)
            progress_var.set(0)
            key = plane_var.get()
            ds = _ds()

            def on_progress(done, total, plate, message):
                if cancel_flag["cancel"]:
                    raise RuntimeError("Cancelled by user")
                pct = 100.0 * done / max(total, 1)
                progress_var.set(pct)
                status_var.set(message)
                win.update_idletasks()

            try:
                summary = download_full_atlas(
                    atlas_key=key,
                    downsample=ds,
                    include_nissl=True,
                    include_svg=True,
                    progress_callback=on_progress,
                    force=False,
                )
                err_n = len(summary.get("errors") or [])
                progress_var.set(100)
                status_var.set(
                    f"Done. Nissl downloaded: {summary['downloaded_nissl']}, "
                    f"SVG downloaded: {summary['downloaded_svg']}, "
                    f"errors: {err_n}\nSaved under:\n{summary['cache_dir']}"
                )
                messagebox.showinfo(
                    "Allen Atlas Download",
                    f"Cached {ALLEN_ATLASES[key]['name']} plates.\n\n"
                    f"Nissl newly downloaded: {summary['downloaded_nissl']}\n"
                    f"SVG newly downloaded: {summary['downloaded_svg']}\n"
                    f"Already present (skipped): {summary['skipped_existing']}\n"
                    f"Errors: {err_n}\n\n"
                    f"Folder:\n{summary['cache_dir']}\n\n"
                    "Import Allen Atlas will use these files automatically.",
                    parent=win,
                )
            except Exception as e:
                if "Cancelled" in str(e):
                    status_var.set("Download cancelled.")
                else:
                    logger.error(f"Full atlas download failed: {e}", exc_info=True)
                    messagebox.showerror("Allen Atlas", f"Download failed:\n{e}", parent=win)
                    status_var.set(f"Failed: {e}")
            finally:
                start_btn.configure(state=tk.NORMAL)
                close_btn.configure(state=tk.NORMAL)
                refresh_status()

        start_btn = ttk.Button(btn_row, text="Download", command=start_download)
        start_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Refresh status", command=refresh_status).pack(side=tk.LEFT, padx=2)
        close_btn = ttk.Button(btn_row, text="Close", command=win.destroy)
        close_btn.pack(side=tk.RIGHT, padx=2)

        plane_var.trace_add("write", refresh_status)
        ds_var.trace_add("write", refresh_status)
        refresh_status()

    def open_allen_atlas_browser(self):
        """Open the Allen Mouse Atlas plate browser (Phase 1 + 2)."""
        try:
            from allen_atlas import (
                ALLEN_ATLASES,
                check_api_reachable,
                list_annotated_plates,
                load_plate,
                plate_display_label,
            )
        except ImportError as e:
            messagebox.showerror(
                "Allen Atlas",
                f"Could not import allen_atlas module:\n{e}\n\n"
                "Ensure allen_atlas.py is next to barcc.py.",
            )
            return

        ok, msg = check_api_reachable(timeout=20)
        # Allow offline if cache has plates (user may have pre-downloaded)
        if not ok:
            try:
                from allen_atlas import plate_cache_status, cache_dir
                st = plate_cache_status("coronal", downsample=3)
                if st.get("svg_cached", 0) > 0:
                    messagebox.showwarning(
                        "Allen Atlas",
                        "Allen API not reachable, but local cache has plates.\n"
                        "Browser will use cached SVGs/images where available.\n\n"
                        f"{msg}\n\nCache: {cache_dir()}",
                    )
                else:
                    messagebox.showerror(
                        "Allen Atlas",
                        "Cannot reach the Allen Brain Atlas API and no local cache found.\n\n"
                        f"{msg}\n\n"
                        "Use Atlas → Download Full Allen Atlas… while online,\n"
                        f"or check your network.\n\nCache folder: {cache_dir()}",
                    )
                    return
            except Exception:
                messagebox.showerror(
                    "Allen Atlas",
                    "Cannot reach the Allen Brain Atlas API.\n\n"
                    f"{msg}\n\n"
                    "Check your network connection and try again.\n"
                    "Cached plates (if any) live under ~/.barc/allen_cache/",
                )
                return

        win = Toplevel(self.master)
        win.title("Allen Mouse Reference Atlas")
        win.geometry("720x560")
        win.attributes("-topmost", "true")
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._register_transparent_window(win)

        status_var = tk.StringVar(value="Loading plate list…")
        preview_label = ttk.Label(win, text="Preview will appear here", anchor="center")
        listbox = None
        plates_holder = {"plates": [], "atlas_key": "coronal"}
        downsample_var = tk.IntVar(value=3)
        plane_var = tk.StringVar(value="coronal")
        search_var = tk.StringVar(value="")

        # --- layout ---
        top = ttk.Frame(win, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Plane:").pack(side=tk.LEFT)
        ttk.Radiobutton(top, text="Coronal (P56)", variable=plane_var, value="coronal").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Radiobutton(top, text="Sagittal (P56)", variable=plane_var, value="sagittal").pack(
            side=tk.LEFT, padx=4
        )
        ttk.Label(top, text="  Quality (downsample):").pack(side=tk.LEFT, padx=(12, 2))
        ds_box = ttk.Combobox(
            top, width=4, state="readonly",
            values=["2 (high)", "3 (default)", "4 (fast)", "5 (preview)"],
        )
        ds_box.set("3 (default)")
        ds_box.pack(side=tk.LEFT)

        top2 = ttk.Frame(win, padding=(6, 0, 6, 0))
        top2.pack(fill="x")
        ttk.Label(
            top2,
            text="Coronal plates: open the stitch editor to Reflect the half-drawing and "
                 "manually move/rotate halves before loading into BARCC.",
            wraplength=680,
            font=("Helvetica", 8),
        ).pack(side=tk.LEFT)

        mid = ttk.Frame(win, padding=6)
        mid.pack(fill="both", expand=True)
        left = ttk.Frame(mid)
        left.pack(side=tk.LEFT, fill="both", expand=True)
        right = ttk.Frame(mid, width=280)
        right.pack(side=tk.RIGHT, fill="y", padx=(8, 0))

        ttk.Label(left, text="Search structures (filters plates with match after load tip):").pack(anchor="w")
        search_entry = ttk.Entry(left, textvariable=search_var)
        search_entry.pack(fill="x", pady=(0, 4))

        ttk.Label(left, text="Annotated plates:").pack(anchor="w")
        lb_frame = ttk.Frame(left)
        lb_frame.pack(fill="both", expand=True)
        listbox = tk.Listbox(lb_frame, exportselection=False, height=18)
        sb = ttk.Scrollbar(lb_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=sb.set)
        listbox.pack(side=tk.LEFT, fill="both", expand=True)
        sb.pack(side=tk.RIGHT, fill="y")

        preview_label.pack(in_=right, fill="both", expand=True, pady=4)
        ttk.Label(right, textvariable=status_var, wraplength=260).pack(anchor="w", pady=4)

        btn_row = ttk.Frame(win, padding=6)
        btn_row.pack(fill="x")

        preview_photo_holder = {"photo": None, "plate_data": None}

        def _ds_value():
            s = ds_box.get() or "3"
            try:
                return int(s.split()[0])
            except Exception:
                return 3

        def refresh_list(*_args):
            key = plane_var.get()
            status_var.set(f"Fetching {ALLEN_ATLASES[key]['name']} plate list…")
            win.update_idletasks()
            try:
                plates = list_annotated_plates(key)
            except Exception as e:
                status_var.set(f"Error: {e}")
                messagebox.showerror("Allen Atlas", f"Could not list plates:\n{e}", parent=win)
                return
            plates_holder["plates"] = plates
            plates_holder["atlas_key"] = key
            listbox.delete(0, tk.END)
            q = (search_var.get() or "").strip().lower()
            shown = 0
            for p in plates:
                lab = plate_display_label(p)
                # Search filters by section/label text only at list time;
                # structure search applied after optional local name cache is not available per-plate
                if q and q not in lab.lower() and q not in str(p.section_number):
                    continue
                listbox.insert(tk.END, lab)
                shown += 1
            status_var.set(
                f"{ALLEN_ATLASES[key]['name']}: {shown} plates shown "
                f"({len(plates)} annotated total). Select a plate, then Load."
            )
            if shown:
                listbox.selection_set(0)
                listbox.see(0)

        def current_plate():
            sel = listbox.curselection()
            if not sel:
                return None
            lab = listbox.get(sel[0])
            # match by label
            for p in plates_holder["plates"]:
                if plate_display_label(p) == lab:
                    return p
            # fallback by index in full list
            try:
                idx = int(lab.split()[0].lstrip("#")) - 1
                return plates_holder["plates"][idx]
            except Exception:
                return None

        def preview_selected(*_args):
            p = current_plate()
            if p is None:
                return
            status_var.set(f"Downloading preview for section {p.section_number}…")
            win.update_idletasks()
            try:
                ds = max(4, _ds_value())  # faster preview
                data = load_plate(p, downsample=ds, mirror_hemispheres=False)
                preview_photo_holder["plate_data"] = data
                # Nissl with borders overlaid
                img = data.nissl_rgba.convert("RGBA").copy()
                if data.borders_rgba is not None:
                    try:
                        b = data.borders_rgba.convert("RGBA")
                        if b.size != img.size:
                            b = b.resize(img.size, Image.NEAREST)
                        img = Image.alpha_composite(img, b)
                    except Exception:
                        pass
                img.thumbnail((260, 320), Image.BILINEAR)
                photo = ImageTk.PhotoImage(img)
                preview_photo_holder["photo"] = photo
                preview_label.configure(image=photo, text="")
                n_zones = len(data.zone_names)
                status_var.set(
                    f"{plate_display_label(p)}\n"
                    f"Structures on plate: {n_zones}\n"
                    f"Allen drawing (right hemi typical)\n"
                    f"Use “Open stitch editor” to Reflect &\n"
                    f"manually align halves, then load."
                )
            except Exception as e:
                logger.error(f"Allen preview failed: {e}", exc_info=True)
                status_var.set(f"Preview failed: {e}")
                preview_label.configure(image="", text="(preview failed)")

        def open_stitch_editor():
            p = current_plate()
            if p is None:
                messagebox.showinfo("Allen Atlas", "Select a plate first.", parent=win)
                return
            status_var.set("Loading plate into stitch editor…")
            win.update_idletasks()
            progress = None
            try:
                progress = self._show_busy_dialog("Allen Atlas")
                progress.set_progress(15, "Downloading Nissl + structures…")
                ds = _ds_value()
                from allen_atlas import load_plate_for_stitch_editor
                session = load_plate_for_stitch_editor(p, downsample=ds)
                progress.set_progress(100, "Opening editor…")
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                    progress = None
                self.open_allen_stitch_editor(session, parent=win)
            except Exception as e:
                logger.error(f"Allen stitch editor open failed: {e}", exc_info=True)
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                messagebox.showerror("Allen Atlas", f"Failed to open stitch editor:\n{e}", parent=win)
                status_var.set(f"Failed: {e}")

        def load_as_drawn():
            """Load unilateral drawing without stitch editor (sagittal / quick path)."""
            p = current_plate()
            if p is None:
                messagebox.showinfo("Allen Atlas", "Select a plate first.", parent=win)
                return
            status_var.set("Loading plate into BARCC…")
            win.update_idletasks()
            progress = None
            try:
                progress = self._show_busy_dialog("Allen Atlas")
                progress.set_progress(10, "Downloading plate…")
                data = load_plate(p, downsample=_ds_value(), mirror_hemispheres=False)
                progress.set_progress(70, "Installing atlas layers…")
                self._load_allen_plate_data(data)
                progress.set_progress(100, "Done")
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                win.destroy()
                messagebox.showinfo(
                    "Allen Atlas Loaded",
                    f"Loaded {plate_display_label(p)} as drawn (no reflect).\n\n"
                    f"Structures: {len(data.zone_names)}\n"
                    "Use Atlas → Move / Rotate / Scale / Crop to align.",
                )
            except Exception as e:
                logger.error(f"Allen load failed: {e}", exc_info=True)
                if progress and not getattr(progress, "closed", False):
                    progress.close()
                messagebox.showerror("Allen Atlas", f"Failed to load plate:\n{e}", parent=win)

        def _on_plane_change(*_args):
            refresh_list()

        listbox.bind("<<ListboxSelect>>", lambda e: None)
        listbox.bind("<Double-Button-1>", lambda e: open_stitch_editor())
        ttk.Button(btn_row, text="Refresh list", command=refresh_list).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Preview", command=preview_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Open stitch editor…", command=open_stitch_editor).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(btn_row, text="Load as drawn", command=load_as_drawn).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Close", command=win.destroy).pack(side=tk.RIGHT, padx=2)

        plane_var.trace_add("write", _on_plane_change)
        # initial list
        win.after(50, refresh_list)

    def _draw_allen_nissl_reference(self, scale=1.0):
        """Draw pure Allen Nissl as a fixed reference strip above the main image (30% size).

        Not part of the movable atlas layer — orientation reference only.
        """
        nissl = getattr(self, "allen_nissl_reference", None)
        if nissl is None:
            self.allen_nissl_photo = None
            return
        try:
            # Size relative to the main experimental image if present, else atlas/nissl itself
            if self.background_image is not None:
                ref_w = self.background_image.size[0]
                ref_h = self.background_image.size[1]
            elif self.original_background is not None:
                ref_w, ref_h = self.original_background.size
            else:
                ref_w, ref_h = nissl.size

            target_w = max(40, int(ref_w * 0.30 * scale))
            target_h = max(40, int(ref_h * 0.30 * scale))
            # Preserve Nissl aspect ratio inside the 30% box
            nw, nh = nissl.size
            fit = min(target_w / float(nw), target_h / float(nh))
            disp_w = max(1, int(nw * fit))
            disp_h = max(1, int(nh * fit))
            nissl_disp = nissl.resize((disp_w, disp_h), Image.BILINEAR)

            self.allen_nissl_photo = ImageTk.PhotoImage(nissl_disp)
            # Place just above the main image (negative y); main image stays at y=0
            gap = 12
            y0 = -disp_h - gap
            self.output.create_image(
                0, y0, image=self.allen_nissl_photo, anchor="nw", tags=("allen_nissl_ref",)
            )
            # Caption
            self.output.create_text(
                4, y0 - 2,
                text="Allen Nissl reference (30%) — not movable; use black borders for alignment",
                anchor="sw",
                fill="#444444",
                font=("Helvetica", 8),
                tags=("allen_nissl_ref",),
            )
        except Exception as e:
            logger.debug(f"Allen Nissl reference draw failed: {e}")
            self.allen_nissl_photo = None

    def open_allen_stitch_editor(self, session, parent=None):
        """Semi-automated hemisphere stitch: Nissl + Reflect + move/rotate halves.

        User adjusts left/right border layers against the Nissl photo, then loads
        the composed structure borders into BARCC.
        """
        try:
            from allen_atlas import (
                reflect_right_to_left,
                compose_stitch_preview,
                commit_stitch_session,
                plate_display_label,
            )
        except ImportError as e:
            messagebox.showerror("Allen Atlas", f"Could not import stitch helpers:\n{e}")
            return

        parent_win = parent if parent is not None else self.master
        ed = Toplevel(parent_win)
        ed.title(f"Allen stitch editor — {plate_display_label(session.plate)}")
        ed.geometry("1100x780")
        ed.attributes("-topmost", "true")
        ed.protocol("WM_DELETE_WINDOW", ed.destroy)
        self._register_transparent_window(ed)

        # --- state ---
        tool_var = tk.StringVar(value="move")  # move | rotate
        target_var = tk.StringVar(value="left")  # left | right | both
        status_var = tk.StringVar(
            value="Nissl shown. Click Reflect to create the left half, then Move/Rotate to stitch."
        )
        step_move = tk.DoubleVar(value=2.0)
        step_rot = tk.DoubleVar(value=0.5)
        view_scale = {"s": 1.0}
        drag = {"active": False, "x0": 0, "y0": 0, "mode": None}
        photos = {"img": None}

        # --- toolbar ---
        tb = ttk.Frame(ed, padding=6)
        tb.pack(fill="x")

        def do_reflect():
            try:
                reflect_right_to_left(session)
                target_var.set("left")
                status_var.set(
                    "Left half created (blue). Select Left/Right/Both and Move or Rotate to align "
                    "with the Nissl, then Load into BARCC."
                )
                redraw()
            except Exception as e:
                logger.error(f"Reflect failed: {e}", exc_info=True)
                messagebox.showerror("Reflect", str(e), parent=ed)

        def do_reset_transforms():
            session.right_dx = session.right_dy = session.right_angle = 0.0
            session.left_dx = session.left_dy = session.left_angle = 0.0
            status_var.set("Transforms reset.")
            redraw()

        def do_clear_left():
            session.mask_left = None
            session.border_left = None
            session.left_dx = session.left_dy = session.left_angle = 0.0
            status_var.set("Left half cleared.")
            redraw()

        ttk.Button(tb, text="Reflect → left half", command=do_reflect).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Clear left", command=do_clear_left).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Reset moves", command=do_reset_transforms).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill="y", padx=8)

        ttk.Label(tb, text="Edit:").pack(side=tk.LEFT)
        for lab, val in (("Left", "left"), ("Right", "right"), ("Both", "both")):
            ttk.Radiobutton(tb, text=lab, variable=target_var, value=val).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill="y", padx=8)
        ttk.Label(tb, text="Tool:").pack(side=tk.LEFT)
        ttk.Radiobutton(tb, text="Move", variable=tool_var, value="move").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(tb, text="Rotate", variable=tool_var, value="rotate").pack(side=tk.LEFT, padx=2)

        # --- nudge controls ---
        nudge = ttk.Frame(ed, padding=(6, 0, 6, 4))
        nudge.pack(fill="x")
        ttk.Label(nudge, text="Nudge step (px):").pack(side=tk.LEFT)
        ttk.Spinbox(nudge, from_=0.5, to=50, increment=0.5, width=6, textvariable=step_move).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Label(nudge, text="  Rotate step (°):").pack(side=tk.LEFT)
        ttk.Spinbox(nudge, from_=0.1, to=15, increment=0.1, width=6, textvariable=step_rot).pack(
            side=tk.LEFT, padx=2
        )

        def _apply_delta(ddx=0.0, ddy=0.0, dang=0.0):
            t = target_var.get()
            if t in ("left", "both"):
                if session.mask_left is None:
                    if t == "left":
                        status_var.set("No left half yet — click Reflect first.")
                        return
                else:
                    session.left_dx += ddx
                    session.left_dy += ddy
                    session.left_angle += dang
            if t in ("right", "both"):
                session.right_dx += ddx
                session.right_dy += ddy
                session.right_angle += dang
            redraw()

        nf = ttk.Frame(nudge)
        nf.pack(side=tk.LEFT, padx=12)
        ttk.Button(nf, text="↑", width=3, command=lambda: _apply_delta(ddy=-step_move.get())).grid(
            row=0, column=1
        )
        ttk.Button(nf, text="←", width=3, command=lambda: _apply_delta(ddx=-step_move.get())).grid(
            row=1, column=0
        )
        ttk.Button(nf, text="→", width=3, command=lambda: _apply_delta(ddx=step_move.get())).grid(
            row=1, column=2
        )
        ttk.Button(nf, text="↓", width=3, command=lambda: _apply_delta(ddy=step_move.get())).grid(
            row=2, column=1
        )
        ttk.Button(
            nudge, text="↺", width=3, command=lambda: _apply_delta(dang=step_rot.get())
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            nudge, text="↻", width=3, command=lambda: _apply_delta(dang=-step_rot.get())
        ).pack(side=tk.LEFT, padx=2)

        # --- canvas ---
        canvas_frame = ttk.Frame(ed)
        canvas_frame.pack(fill="both", expand=True, padx=6, pady=4)
        canvas = tk.Canvas(canvas_frame, bg="#222", highlightthickness=0)
        hsb = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=canvas.xview)
        vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill="y")
        hsb.pack(side=tk.BOTTOM, fill="x")
        canvas.pack(side=tk.LEFT, fill="both", expand=True)

        def redraw(*_a):
            try:
                preview = compose_stitch_preview(session)
            except Exception as e:
                status_var.set(f"Preview error: {e}")
                return
            # Fit to canvas while allowing zoom
            cw = max(canvas.winfo_width(), 200)
            ch = max(canvas.winfo_height(), 200)
            pw, ph = preview.size
            fit = min(cw / pw, ch / ph, 1.0) * view_scale["s"]
            fit = max(0.15, min(fit, 4.0))
            disp_w = max(1, int(pw * fit))
            disp_h = max(1, int(ph * fit))
            disp = preview.resize((disp_w, disp_h), Image.BILINEAR)
            photos["img"] = ImageTk.PhotoImage(disp)
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=photos["img"], tags=("preview",))
            canvas.configure(scrollregion=(0, 0, disp_w, disp_h))
            # store scale for drag conversion
            drag["scale"] = fit
            tinfo = (
                f"Right Δ=({session.right_dx:.1f},{session.right_dy:.1f}) "
                f"∠{session.right_angle:.2f}°"
            )
            if session.mask_left is not None:
                tinfo += (
                    f"  |  Left Δ=({session.left_dx:.1f},{session.left_dy:.1f}) "
                    f"∠{session.left_angle:.2f}°"
                )
            else:
                tinfo += "  |  Left: (not reflected)"
            # keep user status if set, append transform
            base = status_var.get().split("  ||  ")[0]
            status_var.set(f"{base}  ||  {tinfo}")

        def on_press(event):
            drag["active"] = True
            drag["x0"] = canvas.canvasx(event.x)
            drag["y0"] = canvas.canvasy(event.y)
            drag["mode"] = tool_var.get()
            drag["r0"] = (
                session.right_dx, session.right_dy, session.right_angle,
                session.left_dx, session.left_dy, session.left_angle,
            )

        def on_drag(event):
            if not drag.get("active"):
                return
            sc = drag.get("scale") or 1.0
            x = canvas.canvasx(event.x)
            y = canvas.canvasy(event.y)
            dx = (x - drag["x0"]) / sc
            dy = (y - drag["y0"]) / sc
            r0 = drag["r0"]
            t = target_var.get()
            mode = drag.get("mode") or "move"
            if mode == "move":
                if t in ("right", "both"):
                    session.right_dx = r0[0] + dx
                    session.right_dy = r0[1] + dy
                if t in ("left", "both") and session.mask_left is not None:
                    session.left_dx = r0[3] + dx
                    session.left_dy = r0[4] + dy
            else:
                # rotate: horizontal drag → degrees
                dang = dx * 0.15
                if t in ("right", "both"):
                    session.right_angle = r0[2] + dang
                if t in ("left", "both") and session.mask_left is not None:
                    session.left_angle = r0[5] + dang
            redraw()

        def on_release(event):
            drag["active"] = False

        def on_wheel(event):
            # zoom
            delta = getattr(event, "delta", 0) or 0
            if delta > 0 or getattr(event, "num", None) == 4:
                view_scale["s"] = min(4.0, view_scale["s"] * 1.1)
            else:
                view_scale["s"] = max(0.2, view_scale["s"] / 1.1)
            redraw()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        canvas.bind("<MouseWheel>", on_wheel)
        canvas.bind("<Button-4>", on_wheel)
        canvas.bind("<Button-5>", on_wheel)

        # --- bottom ---
        bot = ttk.Frame(ed, padding=6)
        bot.pack(fill="x")
        ttk.Label(bot, textvariable=status_var, wraplength=900).pack(side=tk.LEFT, fill="x", expand=True)

        def load_into_barcc():
            try:
                data = commit_stitch_session(session)
                self._load_allen_plate_data(data)
                ed.destroy()
                # close parent browser if still open
                try:
                    if parent is not None and parent.winfo_exists():
                        parent.destroy()
                except Exception:
                    pass
                hemi = (
                    "bilateral (reflected + manually aligned)\n"
                    if data.mirrored
                    else "as drawn\n"
                )
                messagebox.showinfo(
                    "Allen Atlas Loaded",
                    f"Loaded {plate_display_label(session.plate)}\n\n"
                    f"Structures: {len(data.zone_names)}\n"
                    f"Hemispheres: {hemi}"
                    "Movable atlas: structure borders only\n"
                    "Nissl reference: 30% above your image\n\n"
                    "Use Atlas → Move / Rotate / Scale / Crop to align with your TIFF.",
                )
            except Exception as e:
                logger.error(f"Commit stitch failed: {e}", exc_info=True)
                messagebox.showerror("Load into BARCC", str(e), parent=ed)

        ttk.Button(bot, text="Load into BARCC", command=load_into_barcc).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bot, text="Cancel", command=ed.destroy).pack(side=tk.RIGHT, padx=2)

        ed.after(80, redraw)
        ed.bind("<Configure>", lambda e: None)
        # redraw when first mapped
        def _first_draw(_e=None):
            redraw()
            canvas.unbind("<Map>")
        canvas.bind("<Map>", _first_draw)

    def _load_allen_plate_data(self, plate_data):
        """Install an AllenPlateData object as the current atlas (Phase 1+2).

        Movable atlas layer = structure borders only (transparent; PDF-like).
        Nissl is stored separately as a small reference strip above the main image.
        mask_images / zone_names hold Allen structure IDs and names for counting.
        """
        self.save_state()
        clear_preprocess_cache()

        # Borders-only atlas (what Move / Scale / Crop / Rotate act on)
        borders = plate_data.borders_rgba.convert("RGBA")
        mask = plate_data.mask_l
        if mask.size != borders.size:
            mask = mask.resize(borders.size, Image.NEAREST)

        # Pure Nissl for the 30% reference strip above the image (own size is fine)
        self.allen_nissl_reference = plate_data.nissl_rgba.convert("RGBA")
        # Keep a pure border layer to re-composite after yellow fills (so borders stay visible)
        self.allen_borders_pure = borders.copy()

        # Reset atlas / paint state similar to import_atlas, then install Allen layers
        self.path = f"allen://{plate_data.plate.image_id}"
        self.doc = None
        self.num_pages = 1
        self.atlas_filetype = "allen"
        self.zoom = 1.0
        self.view_scale = 1.0
        self.img_x = 0
        self.img_y = 0
        self.current_page = 0

        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.allen_zone_meta = {0: dict(plate_data.zone_meta)}  # page -> meta

        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        self.crop_mode = False
        self.crop_mode_var.set(False)
        self.edit_mode = False
        self.edit_mode_var.set(False)
        self.named_paint_groups.clear()
        self.paint_group_data.clear()
        self.painted_zone_outlines.clear()

        page = 0
        # Atlas layer = structure borders only (no Nissl underlay) — full SVG drawing
        self.base_page_images[page] = borders.copy()
        self.page_images[page] = borders.copy()
        self.mask_images[page] = mask.convert("L")
        self.zone_names[page] = {int(k): v for k, v in plate_data.zone_names.items()}
        self.allen_zone_meta[page] = {
            int(k): dict(v) for k, v in (plate_data.zone_meta or {}).items()
        }
        # Split any structure ID that still spans both hemispheres into independent
        # _r / _l zones (critical after Reflect when IDs were shared).
        try:
            n_before = len(self.zone_names[page])
            self._apply_bilateral_hemisphere_split(page, quiet=True)
            n_after = len(self.zone_names.get(page, {}) or {})
            if n_after != n_before:
                logger.info(
                    f"Allen load: hemisphere split {n_before} → {n_after} zone IDs"
                )
        except Exception as e:
            logger.debug(f"Allen load hemisphere split skipped: {e}")
            self._ensure_hemisphere_zone_suffixes(page)
        max_zid = max(self.zone_names[page].keys()) if self.zone_names[page] else 0
        self.zone_counters[page] = int(max_zid)

        self.img = borders.copy()
        # Do not put Allen borders on paint_layer — they live in the atlas overlay only
        self.paint_layer = None
        if self.original_background is not None:
            self.paint_layer = Image.new("RGBA", self.original_background.size, (0, 0, 0, 0))

        # Hollow borders by default; orange fill only when user selects a region
        self._rebuild_page_overlays(page)
        self.show_page()
        self._update_ribbon_selection()
        logger.info(
            f"Allen plate loaded (borders-only atlas + Nissl ref): id={plate_data.plate.image_id} "
            f"zones={len(self.zone_names[page])} atlas_size={borders.size} "
            f"nissl_size={self.allen_nissl_reference.size} mirrored={getattr(plate_data, 'mirrored', False)}"
        )

    def _apply_bilateral_hemisphere_split(self, page=None, quiet=False):
        """Split shared zone IDs that span both hemispheres into ``_r`` / ``_l``.

        Updates mask_images, zone_names, allen_zone_meta, and zone_counters.
        Returns True if the mask/names changed.
        """
        if page is None:
            page = self.current_page
        if page not in getattr(self, "mask_images", {}) or self.mask_images.get(page) is None:
            return False
        try:
            from allen_atlas import ensure_bilateral_hemisphere_zones
        except ImportError:
            self._ensure_hemisphere_zone_suffixes(page)
            return False

        m = np.array(self.mask_images[page])
        if m.ndim > 2:
            m = m.squeeze()
        names = {int(k): v for k, v in (self.zone_names.get(page) or {}).items()}
        meta = {}
        try:
            meta = {
                int(k): dict(v)
                for k, v in ((getattr(self, "allen_zone_meta", None) or {}).get(page) or {}).items()
            }
        except Exception:
            meta = {}

        new_m, new_names, new_meta, changed = ensure_bilateral_hemisphere_zones(
            m, names, meta, mid_x=None
        )
        if not changed and new_names:
            # Still apply suffix normalization for unilateral tags
            self.zone_names[page] = new_names
            if hasattr(self, "allen_zone_meta"):
                self.allen_zone_meta[page] = new_meta
            self._ensure_hemisphere_zone_suffixes(page)
            return False

        self.mask_images[page] = Image.fromarray(new_m.astype(np.uint8), mode="L")
        self.zone_names[page] = {int(k): v for k, v in new_names.items()}
        if hasattr(self, "allen_zone_meta"):
            self.allen_zone_meta[page] = {int(k): dict(v) for k, v in new_meta.items()}
        if self.zone_names[page]:
            self.zone_counters[page] = max(int(k) for k in self.zone_names[page].keys())
        self._ensure_hemisphere_zone_suffixes(page)
        # Clear selection (zone IDs may have changed)
        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        if not quiet:
            try:
                self._rebuild_page_overlays(page)
                self.show_page()
                self._update_ribbon_selection()
            except Exception:
                pass
        return True

    def split_atlas_hemispheres(self):
        """Atlas menu: force independent left/right structure IDs with _l / _r names."""
        page = self.current_page
        if page not in getattr(self, "mask_images", {}) or self.mask_images.get(page) is None:
            messagebox.showinfo(
                "Split Hemispheres",
                "No atlas zone mask is loaded.\n\n"
                "Import an Allen atlas (Reflect + Load) or load a .catlas first.",
            )
            return
        n_before = len(self.zone_names.get(page) or {})
        self.save_state()
        changed = self._apply_bilateral_hemisphere_split(page, quiet=False)
        n_after = len(self.zone_names.get(page) or {})
        if changed or n_after != n_before:
            messagebox.showinfo(
                "Split Hemispheres",
                f"Hemisphere structures are now independent.\n\n"
                f"Zones before: {n_before}\n"
                f"Zones after:  {n_after}\n\n"
                f"Each side uses its own ID and name (e.g. V2M_r / V2M_l).\n"
                f"Atlas Manager, Count Cells, and random masks treat them separately.",
            )
        else:
            # Still re-tag names if possible
            self._ensure_hemisphere_zone_suffixes(page)
            try:
                self._update_ribbon_selection()
            except Exception:
                pass
            messagebox.showinfo(
                "Split Hemispheres",
                "No shared bilateral zone IDs were found to split "
                "(structures may already be independent, or only one hemisphere is present).\n\n"
                f"Current labeled zones: {n_after}",
            )

    def _ensure_hemisphere_zone_suffixes(self, page=None):
        """Normalize zone labels so hemispheres use ``_l`` / ``_r`` suffixes.

        Converts older ``(L)``/``(R)`` tags and applies meta.hemisphere when present
        so Atlas Manager and Count Cells clearly distinguish sides after Reflect.
        """
        if page is None:
            page = self.current_page
        names = self.zone_names.get(page) or {}
        if not names:
            return
        meta_page = {}
        try:
            meta_page = (getattr(self, "allen_zone_meta", None) or {}).get(page) or {}
        except Exception:
            meta_page = {}

        def _has_hemi_tag(s):
            s = str(s)
            low = s.lower()
            return (
                low.endswith("_l")
                or low.endswith("_r")
                or " (l)" in low
                or " (r)" in low
                or "_l:" in low
                or "_r:" in low
            )

        updated = {}
        for zid, label in names.items():
            zid = int(zid)
            label = str(label)
            meta = meta_page.get(zid) or meta_page.get(str(zid)) or {}
            hemi = str(meta.get("hemisphere") or "").strip().lower()
            if hemi in ("l", "left"):
                hemi = "l"
            elif hemi in ("r", "right"):
                hemi = "r"
            else:
                hemi = ""

            # Prefer explicit meta hemisphere; else detect legacy tags
            if not hemi:
                low = label.lower()
                if low.endswith(" (l)") or low.endswith("_l") or "_l:" in low or low.endswith(" (left)"):
                    hemi = "l"
                elif low.endswith(" (r)") or low.endswith("_r") or "_r:" in low or low.endswith(" (right)"):
                    hemi = "r"

            if not hemi:
                updated[zid] = label
                continue

            # Rebuild with canonical _l / _r via allen helper if available
            try:
                from allen_atlas import _format_hemisphere_zone_name
                updated[zid] = _format_hemisphere_zone_name(label, meta, hemi)
            except Exception:
                # Fallback: append _l/_r to acronym head
                base = label
                for tag in (" (L)", " (R)", " (l)", " (r)", "_L", "_R", "_l", "_r"):
                    if base.endswith(tag):
                        base = base[: -len(tag)]
                if ":" in base:
                    head, tail = base.split(":", 1)
                    head = head.strip()
                    if head.lower().endswith("_l") or head.lower().endswith("_r"):
                        head = head[:-2]
                    updated[zid] = f"{head}_{hemi}: {tail.strip()}"
                else:
                    head = base.strip()
                    if head.lower().endswith("_l") or head.lower().endswith("_r"):
                        head = head[:-2]
                    updated[zid] = f"{head}_{hemi}"

            # Keep meta display in sync
            if zid in meta_page or str(zid) in meta_page:
                key = zid if zid in meta_page else str(zid)
                try:
                    meta_page[key] = dict(meta_page[key])
                    meta_page[key]["hemisphere"] = hemi
                    meta_page[key]["display"] = updated[zid]
                except Exception:
                    pass

        self.zone_names[page] = updated
        if meta_page and hasattr(self, "allen_zone_meta"):
            self.allen_zone_meta[page] = meta_page

    def _compute_tiff_fit_scale(self, img_w, img_h):
        """Scale factor to fit a TIFF into the viewer without loading full resolution blindly."""
        ww = self.output.winfo_width()
        wh = self.output.winfo_height()
        if ww <= 1 or wh <= 1:
            # Canvas not laid out yet (common at startup) — estimate from window size.
            ww = max(self.master.winfo_width() - 280, 800)
            wh = max(self.master.winfo_height() - 120, 600)
        return min(ww / img_w, wh / img_h, 1.0)

    def _resize_tiff_for_viewer(self, bg_RGBA):
        """Return a display-sized RGBA copy suitable for in-memory processing."""
        bw, bh = bg_RGBA.size
        scale = self._compute_tiff_fit_scale(bw, bh)
        new_size = (max(1, int(bw * scale)), max(1, int(bh * scale)))
        if new_size == (bw, bh):
            return bg_RGBA.copy()
        return bg_RGBA.resize(new_size, Image.BILINEAR)

    def import_tiff(self):
        """Import a TIFF. Keeps atlas/zones if an atlas is already loaded.

        Use Atlas → Clear Atlas first if you want a blank session, or
        File → Next Channel… when switching fluorescence channels deliberately.
        """
        logger.info("Opening file dialog for TIFF selection")
        tiff_path = fd.askopenfilename(filetypes=[("TIFF files", "*.tiff *.tif")])
        if tiff_path:
            # Auto-preserve when atlas is present (loading TIFF must not wipe a just-loaded Allen plate)
            self._load_tiff_file(tiff_path)

    # ------------------------------------------------------------------
    # File Browser (Left Pane) - Directory TIFF selector + work tracker
    # Phase A: multi-state status, current highlight, last folder,
    #          progress summary, Next/Prev/Next Uncounted navigation
    # ------------------------------------------------------------------

    def _get_ui_prefs_path(self):
        """Path for lightweight UI prefs (last folder, etc.) under ~/.barc/."""
        prefs_dir = os.path.join(os.path.expanduser("~"), ".barc")
        try:
            os.makedirs(prefs_dir, exist_ok=True)
        except Exception:
            pass
        return os.path.join(prefs_dir, "ui_prefs.json")

    def _save_ui_prefs(self):
        """Persist last working folder for restore on next launch."""
        try:
            prefs = {}
            path = self._get_ui_prefs_path()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        prefs = json.load(f) or {}
                except Exception:
                    prefs = {}
            if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
                prefs["last_tiff_directory"] = self.current_tiff_directory
            if getattr(self, "current_tiff_path", None) and os.path.isfile(self.current_tiff_path):
                prefs["last_tiff_path"] = self.current_tiff_path
            with open(path, "w", encoding="utf-8") as f:
                json.dump(prefs, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save UI prefs: {e}")

    def _restore_ui_prefs(self):
        """Restore last working folder into the File Browser (if still valid)."""
        try:
            path = self._get_ui_prefs_path()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                prefs = json.load(f) or {}
            directory = prefs.get("last_tiff_directory")
            if directory and os.path.isdir(directory):
                self.current_tiff_directory = directory
                if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
                    self.folder_label.config(text=directory)
                self.refresh_tiff_file_list()
                if hasattr(self, "file_browser_frame"):
                    self.file_browser_frame.after(50, self._update_folder_label_wraplength)
                last_path = prefs.get("last_tiff_path")
                if last_path and os.path.isfile(last_path):
                    self.current_tiff_path = last_path
                    self._highlight_current_tiff_in_tree()
        except Exception as e:
            logger.debug(f"Failed to restore UI prefs: {e}")

    def select_tiff_directory(self):
        """Let user choose a folder containing TIFF images."""
        initial = None
        if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            initial = self.current_tiff_directory
        directory = fd.askdirectory(title="Select folder containing TIFF images", initialdir=initial)
        if directory:
            self.current_tiff_directory = directory
            self.folder_label.config(text=directory)
            self.refresh_tiff_file_list()
            self._save_ui_prefs()
            # Force wraplength update after the text is set
            self.file_browser_frame.after(50, self._update_folder_label_wraplength)

    def _is_source_tiff_name(self, filename):
        """True if filename is a source TIFF (exclude BARCC product derivatives)."""
        lower = filename.lower()
        if not lower.endswith((".tif", ".tiff")):
            return False
        base = os.path.splitext(filename)[0].lower()
        for suffix in ("_masked", "_flattened"):
            if base.endswith(suffix):
                return False
        return True

    def _norm_path(self, path):
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(path))

    # Feature subfolders under <image_dir>/output/
    OUTPUT_FEATURES = (
        "counts",       # Count Cells: xlsx, masked.tif, centroids, metadata
        "intensities",  # region intensity + counterstain norm
        "pnn",          # perineuronal by-structure + per-cell tables
        "atlas",        # .catlas schematics
        "cell_masks",   # .barccmask, cellmask png, random cell masks
        "paint",        # paint layers / .barccpaint
        "flattened",    # flattened composites
    )

    def _get_output_directory(self, base_dir=None, feature=None, create=True):
        """Return <image_dir>/output[/<feature>], optionally creating it.

        Feature organizes exports by analysis type, e.g.:
          output/counts/, output/intensities/, output/pnn/, output/atlas/,
          output/cell_masks/, output/paint/, output/flattened/

        ``feature=None`` returns the root ``output/`` folder.
        Set ``create=False`` for open/browse dialogs so empty feature folders
        are not created merely by loading.
        """
        base = base_dir or self.tiff_dir or self.current_tiff_directory
        if not base:
            return None
        try:
            if not os.path.isdir(base):
                return None
            out = os.path.join(base, "output")
            if feature:
                # Normalize / sanitize feature name
                feat = str(feature).strip().strip("/\\").replace("..", "")
                if feat:
                    out = os.path.join(out, feat)
            if create:
                os.makedirs(out, exist_ok=True)
            elif not os.path.isdir(out):
                return None
            return out
        except Exception as e:
            logger.warning(f"Could not create/resolve output directory under {base}: {e}")
            return None

    def _preferred_open_dir(self, feature=None):
        """Best initialdir for open dialogs: output/<feature>/ if present, else output/, else image folder."""
        base = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            base = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            base = self.current_tiff_directory
        if not base:
            return None
        if feature:
            feat = self._get_output_directory(base, feature=feature, create=False)
            if feat and os.path.isdir(feat):
                return feat
        root = self._get_output_directory(base, feature=None, create=False)
        if root and os.path.isdir(root):
            return root
        return base

    def _artifact_search_dirs(self, tiff_dir):
        """Directories to search for BARCC exports.

        Order: each output/<feature>/, then flat output/ (legacy), then image folder.
        """
        dirs = []
        if not tiff_dir:
            return dirs
        out = os.path.join(tiff_dir, "output")
        if os.path.isdir(out):
            for feat in self.OUTPUT_FEATURES:
                feat_dir = os.path.join(out, feat)
                if os.path.isdir(feat_dir):
                    dirs.append(feat_dir)
            # Any other subfolders under output/ (future features)
            try:
                for name in sorted(os.listdir(out)):
                    p = os.path.join(out, name)
                    if os.path.isdir(p) and p not in dirs:
                        dirs.append(p)
            except Exception:
                pass
            # Legacy flat files still in output/
            dirs.append(out)
        if os.path.isdir(tiff_dir):
            dirs.append(tiff_dir)
        return dirs

    def _artifact_rel_prefix(self, search_dir, tiff_dir):
        """Display prefix for File Browser children, e.g. output/counts/."""
        try:
            rel = os.path.relpath(search_dir, tiff_dir)
            if rel in (".", ""):
                return ""
            return rel.replace("\\", "/") + "/"
        except Exception:
            base = os.path.basename(search_dir).lower()
            if base == "output":
                return "output/"
            parent = os.path.basename(os.path.dirname(search_dir)).lower()
            if parent == "output":
                return f"output/{base}/"
            return ""

    def _counted_result_candidates(self, base_name):
        """All known count export filenames for a TIFF stem (Count Cells + autosave)."""
        return [
            f"{base_name}.xlsx",
            f"{base_name}.csv",
            f"{base_name}_counted.xlsx",
            f"{base_name}_counted.csv",
            f"{base_name} - counted.xlsx",
            f"{base_name} - counted.csv",
            f"{base_name}_cells.xlsx",
            f"{base_name}_cells.csv",
            f"{base_name}_counts.xlsx",
            f"{base_name}_counts.csv",
        ]

    def _get_image_work_status(self, tiff_path, dir_files=None):
        """Return multi-state work status for a source TIFF.

        Looks in <folder>/output/<feature>/ first, then flat output/, then the
        image folder (legacy sidecars).
        Status labels (priority): Done (counted+masked) > Count > Paint > —

        counted_files / paint_files / masked_files entries are display labels
        (e.g. "output/counts/name.xlsx") for the File Browser tree children.
        """
        empty = {
            "counted": False,
            "painted": False,
            "masked": False,
            "status_label": "—",
            "counted_files": [],
            "paint_files": [],
            "masked_files": [],
            "flattened_files": [],
            "cell_centroid_files": [],
            "intensity_files": [],
        }
        if not tiff_path:
            return empty

        directory = os.path.dirname(tiff_path)
        base_name = os.path.splitext(os.path.basename(tiff_path))[0]
        base_l = base_name.lower()

        counted_files = []
        paint_files = []
        masked_files = []
        flattened_files = []
        metadata_files = []
        cell_centroid_files = []
        intensity_files = []
        seen = set()  # avoid listing the same basename twice (output + legacy)

        for search_dir in self._artifact_search_dirs(directory):
            rel_prefix = self._artifact_rel_prefix(search_dir, directory)
            try:
                listing = os.listdir(search_dir)
            except Exception:
                continue
            files_lower_map = {f.lower(): f for f in listing}

            for cand in self._counted_result_candidates(base_name):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    counted_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for f in listing:
                fl = f.lower()
                if fl.startswith(base_l + "_paint") and (fl.endswith(".png") or fl.endswith(".barccpaint")):
                    if fl not in seen:
                        paint_files.append(rel_prefix + f)
                        seen.add(fl)

            for cand in (f"{base_name}_masked.tif", f"{base_name}_masked.tiff"):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    masked_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (f"{base_name}_flattened.tif", f"{base_name}_flattened.tiff"):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    flattened_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (f"{base_name}_metadata.json", f"{base_name}_metadata.txt"):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    metadata_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (f"{base_name}_cell_centroids.csv",):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    cell_centroid_files.append(rel_prefix + real)
                    seen.add(real.lower())

            for cand in (
                f"{base_name}_intensities.xlsx",
                f"{base_name}_intensities.csv",
                f"{base_name}_region_intensity.xlsx",
                f"{base_name}_region_intensity.csv",
                f"{base_name}_intensities_parameters.csv",
                f"{base_name}_counterstain_norm.xlsx",
                f"{base_name}_counterstain_norm.csv",
                f"{base_name}_pnn_by_structure.xlsx",
                f"{base_name}_pnn_by_structure.csv",
                f"{base_name}_pnn_cells_true.xlsx",
                f"{base_name}_pnn_cells_true.csv",
                f"{base_name}_pnn_cells_random.xlsx",
                f"{base_name}_pnn_cells_random.csv",
            ):
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    intensity_files.append(rel_prefix + real)
                    seen.add(real.lower())

            # Cell masks + atlas schematics (per-channel name and stem without _chN)
            mask_candidates = [
                f"{base_name}_cellmask.barccmask",
                f"{base_name}_cellmask.png",
                f"{base_name}_random_cellmask.png",
                f"{base_name}_random_cellmask.json",
                f"{base_name}_atlas.catlas",
                f"{base_name}_atlas.atlas",
                f"{base_name}.catlas",
                f"{base_name}.atlas",
            ]
            stem = base_name
            for suffix in (
                "_ch0", "_ch1", "_ch2", "_ch3", "_c0", "_c1", "_c2", "_c3",
                "-ch0", "-ch1", "-ch2", "-ch3",
            ):
                if stem.lower().endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            if stem != base_name:
                mask_candidates.extend(
                    [
                        f"{stem}_cellmask.barccmask",
                        f"{stem}_cellmask.png",
                        f"{stem}_random_cellmask.png",
                        f"{stem}_random_cellmask.json",
                        f"{stem}_atlas.catlas",
                        f"{stem}_atlas.atlas",
                        f"{stem}.catlas",
                        f"{stem}.atlas",
                    ]
                )
            for cand in mask_candidates:
                real = files_lower_map.get(cand.lower())
                if real and real.lower() not in seen:
                    intensity_files.append(rel_prefix + real)  # show under TIFF children
                    seen.add(real.lower())

        counted = len(counted_files) > 0
        painted = len(paint_files) > 0
        masked = len(masked_files) > 0

        if counted and masked:
            label = "Done"
        elif counted:
            label = "Count"
        elif painted:
            label = "Paint"
        else:
            label = "—"

        return {
            "counted": counted,
            "painted": painted,
            "masked": masked,
            "status_label": label,
            "counted_files": counted_files,
            "paint_files": paint_files,
            "masked_files": masked_files,
            "flattened_files": flattened_files,
            "metadata_files": metadata_files,
            "cell_centroid_files": cell_centroid_files,
            "intensity_files": intensity_files,
        }

    def refresh_tiff_file_list(self):
        """Scan the current directory for source TIFFs and update the Treeview.

        Shows multi-state status (Done / Count / Paint / —) and child artifacts.
        Highlights the currently open TIFF when present.
        """
        if not self.current_tiff_directory or not os.path.isdir(self.current_tiff_directory):
            self._update_folder_progress_summary(0, 0, 0)
            return

        self.tiff_file_list = []
        self._tree_iid_to_path = {}
        self._tree_path_to_iid = {}

        try:
            files = os.listdir(self.current_tiff_directory)
            tiff_files = [f for f in files if self._is_source_tiff_name(f)]
            tiff_files.sort(key=str.lower)

            self.tiff_file_list = [os.path.join(self.current_tiff_directory, f) for f in tiff_files]

            counted_n = 0
            painted_n = 0

            if hasattr(self, "tiff_tree"):
                for item in self.tiff_tree.get_children():
                    self.tiff_tree.delete(item)

                for full_path in self.tiff_file_list:
                    filename = os.path.basename(full_path)
                    status = self._get_image_work_status(full_path)
                    if status["counted"]:
                        counted_n += 1
                    if status["painted"]:
                        painted_n += 1

                    tags = ()
                    if status["status_label"] == "Done":
                        tags = ("status_done",)
                    elif status["status_label"] == "Count":
                        tags = ("status_count",)
                    elif status["status_label"] == "Paint":
                        tags = ("status_paint",)

                    iid = self.tiff_tree.insert(
                        "",
                        "end",
                        text=filename,
                        values=(status["status_label"],),
                        tags=tags,
                        open=False,
                    )
                    self._tree_iid_to_path[iid] = full_path
                    self._tree_path_to_iid[self._norm_path(full_path)] = iid

                    for cand in status["counted_files"]:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status["paint_files"]:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status["masked_files"]:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("flattened_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("metadata_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("cell_centroid_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))
                    for cand in status.get("intensity_files") or []:
                        self.tiff_tree.insert(iid, "end", text=cand, values=("",), tags=("child",))

            total = len(self.tiff_file_list)
            self._update_folder_progress_summary(counted_n, painted_n, total)
            self._highlight_current_tiff_in_tree()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to read directory:\n{e}")

    def _update_folder_progress_summary(self, counted_n, painted_n, total):
        """Update the progress line: Counted x/y · Painted z · Remaining r."""
        if not hasattr(self, "progress_summary_var"):
            return
        if total <= 0:
            self.progress_summary_var.set("No images in folder")
            return
        remaining = max(0, total - counted_n)
        self.progress_summary_var.set(
            f"Counted {counted_n}/{total}  ·  Painted {painted_n}  ·  Remaining {remaining}"
        )

    def _update_folder_label_wraplength(self, event=None):
        """Dynamically set wraplength based on the current width of the file browser pane."""
        if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
            width = self.folder_label.winfo_width()
            if width > 50:
                new_wrap = max(60, width - 8)
                self.folder_label.configure(wraplength=new_wrap)

    def _has_matching_csv(self, tiff_path):
        """Check if a results file matching this TIFF exists (legacy API)."""
        return self._get_image_work_status(tiff_path).get("counted", False)

    def _highlight_current_tiff_in_tree(self):
        """Select and tag the currently open TIFF row; clear prior current tag."""
        if not hasattr(self, "tiff_tree"):
            return

        for iid in self.tiff_tree.get_children(""):
            tags = list(self.tiff_tree.item(iid, "tags") or ())
            if "current" in tags:
                tags = [t for t in tags if t != "current"]
                self.tiff_tree.item(iid, tags=tuple(tags))

        path = getattr(self, "current_tiff_path", None)
        if not path:
            if hasattr(self, "current_file_var"):
                self.current_file_var.set("")
            return

        if hasattr(self, "current_file_var"):
            self.current_file_var.set(f"Open: {os.path.basename(path)}")

        iid = getattr(self, "_tree_path_to_iid", {}).get(self._norm_path(path))
        if not iid:
            return

        tags = list(self.tiff_tree.item(iid, "tags") or ())
        if "current" not in tags:
            tags.append("current")
        self.tiff_tree.item(iid, tags=tuple(tags))
        try:
            self.tiff_tree.selection_set(iid)
            self.tiff_tree.focus(iid)
            self.tiff_tree.see(iid)
        except Exception:
            pass

    def _sync_file_browser_to_path(self, tiff_path):
        """Ensure File Browser shows the folder of tiff_path and highlights it."""
        if not tiff_path:
            return
        directory = os.path.dirname(tiff_path)
        if directory and os.path.isdir(directory):
            if self.current_tiff_directory != directory:
                self.current_tiff_directory = directory
                if hasattr(self, "folder_label") and self.folder_label.winfo_exists():
                    self.folder_label.config(text=directory)
                self.refresh_tiff_file_list()
            self.current_tiff_path = tiff_path
            self._highlight_current_tiff_in_tree()
            self._save_ui_prefs()
        else:
            self.current_tiff_path = tiff_path

    def load_tiff_from_list(self, event=None):
        """Load the TIFF file that was double-clicked in the file browser Treeview.
        Child items (generated .xlsx or saved paint files/bundles) are ignored for loading.
        """
        if not hasattr(self, 'tiff_tree'):
            return

        selection = self.tiff_tree.selection()
        if not selection:
            return

        iid = selection[0]

        parent_iid = self.tiff_tree.parent(iid)
        if parent_iid:
            # Child item — filename lives in tree text (Phase A); fall back to values
            child_name = self.tiff_tree.item(iid, "text") or ""
            if not child_name:
                values = self.tiff_tree.item(iid, "values") or []
                child_name = values[0] if values else ""
            cl = child_name.lower()
            if (cl.endswith('.barccpaint') or cl.endswith('.png')) and '_paint' in cl:
                # Load the associated TIFF first if not already the current one
                if parent_iid in self._tree_iid_to_path:
                    parent_tiff_path = self._tree_iid_to_path[parent_iid]
                    # Load the background if it's not the current or to ensure
                    if not self.tiff_filename or self.tiff_filename not in os.path.basename(parent_tiff_path):
                        self._load_tiff_file(parent_tiff_path)
                    # Resolve paint path (supports "output/paint/foo.barccpaint" labels)
                    paint_name = child_name.replace("\\", "/")
                    parent_dir = os.path.dirname(parent_tiff_path)
                    basename = os.path.basename(paint_name)
                    if paint_name.lower().startswith("output/"):
                        paint_full_path = os.path.join(parent_dir, paint_name.replace("/", os.sep))
                    else:
                        paint_full_path = None
                        for search_dir in self._artifact_search_dirs(parent_dir):
                            cand = os.path.join(search_dir, basename)
                            if os.path.exists(cand):
                                paint_full_path = cand
                                break
                        if not paint_full_path:
                            paint_full_path = os.path.join(parent_dir, basename)
                    if paint_full_path.lower().endswith('.barccpaint'):
                        self._load_barccpaint_bundle(paint_full_path)
                    else:
                        # plain paint png (legacy)
                        self.img = Image.open(paint_full_path)
                        clear_preprocess_cache()
                        loaded_rgba = self.img.convert('RGBA') if self.img.mode != 'RGBA' else self.img
                        self.paint_layer = loaded_rgba
                        self.atlas_filetype = 'img'
                        self.show_page()
                        # try legacy sidecars relative to this paint file
                        try:
                            pbase = os.path.splitext(os.path.basename(paint_full_path))[0]
                            pdir = os.path.dirname(paint_full_path)
                            rj = os.path.join(pdir, pbase + "_regions.json")
                            zp = os.path.join(pdir, pbase + "_zones.png")
                            page = self.current_page
                            restored = False
                            if os.path.exists(rj):
                                with open(rj, "r", encoding="utf-8") as f:
                                    d = json.load(f)
                                nm = d.get("zone_names", {})
                                if nm:
                                    nm = {int(k): v for k, v in nm.items()}
                                    if page not in self.zone_names: self.zone_names[page] = {}
                                    self.zone_names[page].update(nm)
                                    restored = True
                                ol = d.get("painted_zone_outlines", {})
                                if ol:
                                    ol = {int(k): v for k, v in ol.items()}
                                    self.painted_zone_outlines.update(ol)
                                    restored = True
                            if os.path.exists(zp):
                                zm = Image.open(zp).convert('L')
                                try:
                                    if zm.mode != 'L':
                                        zm = zm.convert('L')
                                    zarr = np.array(zm).astype(np.uint8)
                                    zm = Image.fromarray(zarr, mode='L')
                                except Exception:
                                    pass
                                self.mask_images[page] = zm
                                restored = True
                            if restored:
                                if hasattr(self, '_update_ribbon_selection'):
                                    self._update_ribbon_selection()
                                if hasattr(self, '_rebuild_page_overlays'):
                                    try:
                                        self._rebuild_page_overlays(page)
                                    except:
                                        pass
                                self.show_page()
                        except:
                            pass
                return
            else:
                # other child, ignore
                return

        if iid in self._tree_iid_to_path:
            full_path = self._tree_iid_to_path[iid]
            # Preserve atlas if one is loaded (File Browser must not clear Reflect/stitch work)
            self._load_tiff_file(full_path)

    def _build_file_browser(self, parent):
        """Builds the left-side file manager pane with multi-state status and progress."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        # Header: folder select + path
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky='ew', padx=4, pady=(4, 2))

        ttk.Button(header, text="Select Folder", command=self.select_tiff_directory).pack(fill='x')

        self.folder_label = ttk.Label(header, text="No folder selected", anchor='w', justify=tk.LEFT)
        self.folder_label.pack(fill='x', pady=(4, 0))

        # Dynamically adjust wraplength when the pane is resized
        header.bind("<Configure>", self._update_folder_label_wraplength)

        # Initial wraplength update after layout settles
        parent.after(150, self._update_folder_label_wraplength)

        # Progress summary (Counted n/N · Painted · Remaining)
        self.progress_summary_var = tk.StringVar(value="No folder selected")
        self.progress_summary_label = ttk.Label(
            parent,
            textvariable=self.progress_summary_var,
            anchor='w',
            justify=tk.LEFT,
            font=("Helvetica", 8),
            foreground="#333333",
        )
        self.progress_summary_label.grid(row=1, column=0, sticky='ew', padx=4, pady=(0, 2))

        # Currently open file line
        self.current_file_var = tk.StringVar(value="")
        self.current_file_label = ttk.Label(
            parent,
            textvariable=self.current_file_var,
            anchor='w',
            justify=tk.LEFT,
            font=("Helvetica", 8, "bold"),
            foreground="#0055aa",
        )
        self.current_file_label.grid(row=2, column=0, sticky='ew', padx=4, pady=(0, 2))

        # File list: tree column = Image name; status column = Done/Count/Paint/—
        columns = ("status",)
        self.tiff_tree = ttk.Treeview(parent, columns=columns, show="tree headings", selectmode="browse")
        self.tiff_tree.column("#0", width=150, minwidth=80, stretch=True, anchor="w")
        self.tiff_tree.heading("#0", text="Image", anchor="w")
        self.tiff_tree.column("status", width=52, minwidth=44, stretch=False, anchor="center")
        self.tiff_tree.heading("status", text="Status")

        try:
            self.tiff_tree.tag_configure("current", background="#cce5ff")
            self.tiff_tree.tag_configure("status_done", foreground="#0a7a0a")
            self.tiff_tree.tag_configure("status_count", foreground="#0066aa")
            self.tiff_tree.tag_configure("status_paint", foreground="#b36b00")
            self.tiff_tree.tag_configure("child", foreground="#555555")
        except Exception:
            pass

        self.tiff_tree.grid(row=3, column=0, sticky='nsew', padx=4, pady=2)
        self.tiff_tree.bind("<Double-Button-1>", self.load_tiff_from_list)
        self.tiff_tree.bind("<Return>", self.load_tiff_from_list)

        # Store mapping from iid to full path
        self._tree_iid_to_path = {}
        self._tree_path_to_iid = {}

        # Navigation row
        nav = ttk.Frame(parent)
        nav.grid(row=4, column=0, sticky='ew', padx=4, pady=(2, 0))
        nav.columnconfigure(0, weight=1)
        nav.columnconfigure(1, weight=1)
        nav.columnconfigure(2, weight=1)
        ttk.Button(nav, text="◀ Prev", width=8, command=self.previous_image).grid(
            row=0, column=0, sticky='ew', padx=(0, 2)
        )
        ttk.Button(nav, text="Next ▶", width=8, command=self.next_image).grid(
            row=0, column=1, sticky='ew', padx=2
        )
        ttk.Button(nav, text="Next uncounted", width=12, command=self.next_uncounted_image).grid(
            row=0, column=2, sticky='ew', padx=(2, 0)
        )

        # Next Channel: switch TIFF while keeping atlas schematic + Atlas Manager regions
        ttk.Button(
            parent,
            text="Next Channel… (keep atlas)",
            command=self.next_channel,
        ).grid(row=5, column=0, sticky='ew', padx=4, pady=(4, 0))

        # Refresh button
        ttk.Button(parent, text="Refresh", command=self.refresh_tiff_file_list).grid(
            row=6, column=0, sticky='ew', padx=4, pady=(4, 4)
        )

    def _clear_atlas_state(self, *, clear_paint=True, refresh_ui=False):
        """Remove atlas drawings, zone mask/names, and related manager state.

        Does not touch the loaded TIFF background. Used by Clear Atlas and by
        normal image loads that should not leave a ghost overlay.
        """
        self.atlas_filetype = None
        self.page_images = {}
        self.base_page_images = {}
        self.mask_images = {}
        self.zone_names = {}
        self.zone_counters = {}
        self.allen_zone_meta = {}
        self.allen_borders_pure = None
        self.allen_nissl_reference = None
        self.allen_nissl_photo = None
        self.img = None
        # Placement only meaningful with an atlas
        self.img_x = 0
        self.img_y = 0

        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        try:
            self._clear_edge_highlight()
        except Exception:
            pass
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        if hasattr(self, "region_move_mode"):
            self.region_move_mode.set(False)

        self.named_paint_groups = {}
        self.paint_group_data = {}
        self.painted_zone_outlines = {}
        self.current_paint_group = None
        if clear_paint:
            if self.original_background is not None:
                self.paint_layer = Image.new(
                    "RGBA", self.original_background.size, (0, 0, 0, 0)
                )
            else:
                self.paint_layer = None

        # PDF/Allen document path for atlas only (keep TIFF path separate)
        if isinstance(getattr(self, "path", None), str) and (
            str(self.path).lower().endswith(".pdf")
            or str(self.path).startswith("allen://")
        ):
            self.path = None
            self.doc = None

        if refresh_ui:
            try:
                clear_preprocess_cache()
            except Exception:
                pass
            try:
                self.show_page()
            except Exception:
                pass
            try:
                self._update_ribbon_selection()
            except Exception:
                pass
            try:
                self._refresh_zone_counts_table()
            except Exception:
                pass

    def clear_atlas(self):
        """Atlas Manager / menu: clear the atlas overlay and all labeled regions."""
        has_atlas = bool(
            getattr(self, "atlas_filetype", None)
            or self.base_page_images
            or self.page_images
            or any(bool(v) for v in (self.zone_names or {}).values())
            or bool(getattr(self, "painted_zone_outlines", None))
            or bool(getattr(self, "allen_borders_pure", None))
        )
        if not has_atlas:
            for m in (self.mask_images or {}).values():
                if m is None:
                    continue
                try:
                    if int(np.array(m).max()) > 0:
                        has_atlas = True
                        break
                except Exception:
                    has_atlas = True
                    break
        if not has_atlas:
            messagebox.showinfo("Clear Atlas", "There is no atlas or labeled regions to clear.")
            return
        if not messagebox.askyesno(
            "Clear Atlas",
            "Remove the atlas drawing, all structures in the Atlas Manager, "
            "zone masks, and painted region outlines?\n\n"
            "The loaded TIFF image will be kept.\n"
            "This cannot be undone after the next action (Undo may still reverse if used immediately).",
        ):
            return
        try:
            self.save_state()
        except Exception:
            pass
        self._clear_atlas_state(clear_paint=True, refresh_ui=True)
        logger.info("Atlas cleared by user (Clear Atlas)")
        messagebox.showinfo(
            "Atlas Cleared",
            "Atlas overlay and all labeled regions were removed.\n"
            "The TIFF image remains loaded.",
        )

    def next_channel(self):
        """Pick a new TIFF (e.g. next fluorescence channel) while keeping the atlas.

        Preserves atlas drawings, zone mask, Atlas Manager names, painted regions,
        and placement (img_x/img_y). Only the background image and per-image cell
        masks/counts are replaced.
        """
        initial_dir = None
        if self.tiff_dir and os.path.isdir(self.tiff_dir):
            initial_dir = self.tiff_dir
        elif self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            initial_dir = self.current_tiff_directory

        path = fd.askopenfilename(
            title="Next Channel — select image (atlas is kept)",
            initialdir=initial_dir,
            filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")],
        )
        if not path:
            return

        # Autosave counts/paint for the channel we are leaving
        try:
            self._autosave_before_image_switch()
        except Exception as e:
            logger.debug(f"Autosave before next channel: {e}")

        ok = self._load_tiff_file(path, preserve_atlas=True)
        if ok:
            n_zones = 0
            page = self.current_page if self.current_page is not None else 0
            try:
                n_zones = len(self.zone_names.get(page, {}) or {})
            except Exception:
                pass
            logger.info(
                f"Next Channel loaded {path} with atlas preserved "
                f"(zones={n_zones}, filetype={self.atlas_filetype})"
            )

    def _atlas_is_loaded(self):
        """True if an atlas schematic/plate is currently installed."""
        if getattr(self, "atlas_filetype", None):
            return True
        try:
            for im in (getattr(self, "base_page_images", None) or {}).values():
                if im is not None:
                    return True
        except Exception:
            pass
        try:
            for im in (getattr(self, "mask_images", None) or {}).values():
                if im is not None:
                    return True
        except Exception:
            pass
        return False

    def _load_tiff_file(self, tiff_path, preserve_atlas=None):
        """Core TIFF loading logic (shared between manual import and file browser).

        preserve_atlas:
          - True: always keep drawings, zone mask, names, placement (Next Channel).
          - False: clear atlas (explicit wipe).
          - None (default): keep atlas if one is already loaded — critical so that
            loading a TIFF after Import Allen / Reflect does not delete the plate.
        """
        if not tiff_path or not os.path.exists(tiff_path):
            messagebox.showerror("Error", "Selected file does not exist.")
            return False

        if preserve_atlas is None:
            preserve_atlas = self._atlas_is_loaded()

        logger.info(
            f"Loading TIFF: {tiff_path} (preserve_atlas={preserve_atlas}, "
            f"atlas_filetype={getattr(self, 'atlas_filetype', None)})"
        )
        if not preserve_atlas and self._atlas_is_loaded():
            logger.warning(
                "Clearing loaded atlas because preserve_atlas=False "
                "(use Next Channel or leave preserve auto-on to keep it)"
            )

        # Snapshot atlas state before any resets when preserving
        saved_atlas = None
        if preserve_atlas:
            saved_atlas = {
                "atlas_filetype": getattr(self, "atlas_filetype", None),
                "page_images": dict(self.page_images or {}),
                "base_page_images": dict(self.base_page_images or {}),
                "mask_images": dict(self.mask_images or {}),
                "zone_names": {p: dict(n) for p, n in (self.zone_names or {}).items()},
                "zone_counters": dict(self.zone_counters or {}),
                "allen_zone_meta": getattr(self, "allen_zone_meta", {}) or {},
                "allen_borders_pure": getattr(self, "allen_borders_pure", None),
                "allen_nissl_reference": getattr(self, "allen_nissl_reference", None),
                "img_x": float(getattr(self, "img_x", 0) or 0),
                "img_y": float(getattr(self, "img_y", 0) or 0),
                "img": getattr(self, "img", None),
                "path": getattr(self, "path", None),
                "doc": getattr(self, "doc", None),
                "num_pages": getattr(self, "num_pages", 0),
                "current_page": getattr(self, "current_page", 0),
                "painted_zone_outlines": copy.deepcopy(
                    getattr(self, "painted_zone_outlines", {}) or {}
                ),
                "paint_group_data": copy.deepcopy(
                    getattr(self, "paint_group_data", {}) or {}
                ),
                "named_paint_groups": dict(
                    getattr(self, "named_paint_groups", {}) or {}
                ),
                "paint_layer": (
                    self.paint_layer.copy()
                    if getattr(self, "paint_layer", None) is not None
                    else None
                ),
                "old_bg_size": (
                    list(self.original_background.size)
                    if self.original_background is not None
                    else (
                        list(self.background_image.size)
                        if self.background_image is not None
                        else None
                    )
                ),
            }

        if self.current_page is None:
            self.current_page = 0

        if not preserve_atlas:
            # Full clear including ghost atlas drawings (prevents double overlay on reload)
            self._clear_atlas_state(clear_paint=True, refresh_ui=False)
            self.view_scale = 1.0
            self.last_cell_mask = None
        else:
            # Per-image analysis only; atlas kept via snapshot restore after load
            self.view_scale = 1.0
            self.last_cell_mask = None
            self.selected_zone_id = None
            self.selected_page = None
            self.selected_zone_component = None
            try:
                self._clear_edge_highlight()
            except Exception:
                pass
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.original_full_contour_for_edit = None
            self.selected_edge_full_contour = None
            self._edge_pending_deselect = False
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            if hasattr(self, "region_move_mode"):
                self.region_move_mode.set(False)

        self.crop_mode = False
        self.crop_mode_var.set(False)
        self.edit_mode = False
        self.edit_mode_var.set(False)

        # Clear cell masks on every image switch (re-load via Load Cell Mask if needed)
        self.manual_add_mask = None
        self.manual_remove_mask = None
        self.editing_mask = False
        self.current_mask = None
        self.auto_mask = None
        self.showing_auto_mask = False
        self.last_df = None
        self.last_cell_mask = None
        self.cell_mask_locked = False
        self.cell_mask_source_path = None
        self.random_cell_mask = None
        self.random_cell_labels = None
        self.random_cell_mask_meta = None
        self.perineuronal_mask = None
        self.perineuronal_labels = None
        self.perineuronal_cells = None
        self.random_perineuronal_mask = None
        self.random_perineuronal_labels = None
        self.random_perineuronal_cells = None

        self.tiff_dir = os.path.dirname(tiff_path)
        self.tiff_filename = os.path.splitext(os.path.basename(tiff_path))[0]

        try:
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

            self.background_image = self._resize_tiff_for_viewer(bg_RGBA)
            self.original_background = self.background_image.copy()
            self._invalidate_bg_display_cache()

            if preserve_atlas and saved_atlas is not None:
                # Restore full atlas schematic
                self.atlas_filetype = saved_atlas["atlas_filetype"]
                self.page_images = saved_atlas["page_images"]
                self.base_page_images = saved_atlas["base_page_images"]
                self.mask_images = saved_atlas["mask_images"]
                self.zone_names = saved_atlas["zone_names"]
                self.zone_counters = saved_atlas["zone_counters"]
                self.allen_zone_meta = saved_atlas["allen_zone_meta"]
                self.allen_borders_pure = saved_atlas["allen_borders_pure"]
                self.allen_nissl_reference = saved_atlas["allen_nissl_reference"]
                self.img_x = saved_atlas["img_x"]
                self.img_y = saved_atlas["img_y"]
                self.img = saved_atlas["img"]
                self.path = saved_atlas["path"]
                self.doc = saved_atlas["doc"]
                self.num_pages = saved_atlas["num_pages"]
                if saved_atlas["current_page"] is not None:
                    self.current_page = saved_atlas["current_page"]
                self.painted_zone_outlines = saved_atlas["painted_zone_outlines"]
                self.paint_group_data = saved_atlas["paint_group_data"]
                self.named_paint_groups = saved_atlas["named_paint_groups"]

                # Paint layer: keep if same size; scale if channel dims differ
                pl = saved_atlas["paint_layer"]
                new_size = self.original_background.size
                old_size = saved_atlas["old_bg_size"]
                if pl is not None:
                    if list(pl.size) == list(new_size):
                        self.paint_layer = pl
                    else:
                        try:
                            self.paint_layer = pl.resize(new_size, Image.NEAREST)
                            logger.info(
                                f"Next Channel: scaled paint_layer {pl.size} → {new_size}"
                            )
                        except Exception:
                            self.paint_layer = Image.new("RGBA", new_size, (0, 0, 0, 0))
                else:
                    self.paint_layer = Image.new("RGBA", new_size, (0, 0, 0, 0))

                # If background size changed and atlas was 1:1 with old bg, scale atlas too
                if (
                    old_size
                    and list(old_size) != list(new_size)
                    and self.current_page in self.base_page_images
                    and self.base_page_images[self.current_page] is not None
                ):
                    base = self.base_page_images[self.current_page]
                    if list(base.size) == list(old_size):
                        page = self.current_page
                        is_allen = getattr(self, "atlas_filetype", None) == "allen"
                        resample = Image.NEAREST if is_allen else Image.BILINEAR
                        target = tuple(int(s) for s in new_size)
                        sx = new_size[0] / float(old_size[0])
                        sy = new_size[1] / float(old_size[1])
                        self.base_page_images[page] = base.resize(target, resample)
                        if page in self.page_images and self.page_images[page] is not None:
                            self.page_images[page] = self.page_images[page].resize(
                                target, resample
                            )
                        if page in self.mask_images and self.mask_images[page] is not None:
                            self.mask_images[page] = self.mask_images[page].resize(
                                target, Image.NEAREST
                            )
                        pure = getattr(self, "allen_borders_pure", None)
                        if pure is not None:
                            self.allen_borders_pure = pure.resize(target, Image.NEAREST)
                        self.img_x = float(self.img_x) * sx
                        self.img_y = float(self.img_y) * sy
                        if self.img is not None:
                            try:
                                self.img = self.base_page_images[page].copy()
                            except Exception:
                                pass
                        logger.info(
                            f"Next Channel: scaled atlas with background "
                            f"{old_size} → {new_size}"
                        )
            else:
                self.paint_layer = Image.new(
                    "RGBA", self.original_background.size, (0, 0, 0, 0)
                )

            self.current_tiff_path = tiff_path

            # Rebuild overlays so fills/borders match preserved mask
            if preserve_atlas:
                try:
                    page = self.current_page if self.current_page is not None else 0
                    if page in self.base_page_images:
                        self._rebuild_page_overlays(page)
                except Exception as e:
                    logger.debug(f"rebuild overlays after next channel: {e}")

            self.show_page()
            self._refresh_zone_counts_table()
            if preserve_atlas and self.show_zone_intensity_labels_var.get():
                try:
                    self.last_intensity_df = None  # recompute for new channel
                    self._refresh_zone_intensity_table()
                    self.show_page()
                except Exception:
                    pass
            else:
                self.last_intensity_df = None
                if not preserve_atlas:
                    try:
                        self._close_zone_intensity_window()
                        self.show_zone_intensity_labels_var.set(False)
                    except Exception:
                        pass
            try:
                self._update_ribbon_selection()
            except Exception:
                pass

            # Keep left File Browser folder + highlight aligned with loaded image
            self._sync_file_browser_to_path(tiff_path)

            # New document — clear undo (masks/images sizes may differ)
            try:
                self.state_manager.undo_stack.clear()
            except Exception:
                self.state_manager.undo_stack = []

            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load TIFF:\n{e}")
            logger.error(f"Failed to load TIFF {tiff_path}: {e}")
            return False

    def _compose_flattened_image(self):
        """Build RGB composite: TIFF + zone fills + atlas + paint + cell rings.

        Zone fills use ``_zone_mask_registered_to_background`` so atlas-sized masks
        are placed at ``img_x``/``img_y`` (same as on-screen and Count Cells). Stretching
        a model-space mask to full TIFF size misaligned yellow fills vs atlas borders.
        """
        base_img = getattr(self, "original_background", None) or getattr(
            self, "background_image", None
        )
        if (
            base_img is None
            or not hasattr(base_img, "size")
            or base_img.size[0] <= 0
            or base_img.size[1] <= 0
        ):
            return None

        bg_w, bg_h = base_img.size
        composite = base_img.convert("RGBA")

        # Integer model-space offsets (same units as atlas / page_images placement)
        paste_x = int(round(float(self.img_x))) if self.img_x is not None else 0
        paste_y = int(round(float(self.img_y))) if self.img_y is not None else 0

        try:
            # Explicit zone fill so regions are visible (Allen is often borders-only on screen).
            # Must register to background space — never stretch atlas masks to full image size.
            page = self.current_page
            if page in getattr(self, "mask_images", {}) and self.mask_images.get(page) is not None:
                try:
                    m, _mw, _mh = self._zone_mask_registered_to_background(
                        self.mask_images[page], bg_h, bg_w
                    )
                    zone_tint = np.zeros((bg_h, bg_w, 4), dtype=np.uint8)
                    for zid in np.unique(m):
                        if int(zid) == 0:
                            continue
                        reg = m == zid
                        zone_tint[reg, :3] = [255, 255, 0]  # yellow
                        zone_tint[reg, 3] = 55
                    if np.any(zone_tint[..., 3] > 0):
                        zone_img = Image.fromarray(zone_tint, "RGBA")
                        composite = Image.alpha_composite(composite, zone_img)
                except Exception as e:
                    logger.debug(f"Could not apply zone mask fill: {e}")

            # Atlas drawings / page overlay at model-space placement
            if page in getattr(self, "page_images", {}):
                at_img = self.page_images[page]
                if at_img is not None:
                    if at_img.mode != "RGBA":
                        at_img = at_img.convert("RGBA")
                    # Atlas is model-sized; paste at offset. If it already matches the
                    # full background (paint-as-atlas / fit-to-image), paste at 0,0 when
                    # sizes match — still correct when paste_x/y are 0 after Fit.
                    aw, ah = at_img.size
                    if abs(aw - bg_w) < 5 and abs(ah - bg_h) < 5 and abs(paste_x) < 2 and abs(paste_y) < 2:
                        if (aw, ah) != (bg_w, bg_h):
                            at_img = at_img.resize((bg_w, bg_h), Image.NEAREST)
                        composite.paste(at_img, (0, 0), at_img)
                    else:
                        composite.paste(at_img, (paste_x, paste_y), at_img)

            # Paint layer is baked into background pixel space (origin 0,0)
            if getattr(self, "paint_layer", None) is not None:
                pl = self.paint_layer
                if pl.mode != "RGBA":
                    pl = pl.convert("RGBA")
                if pl.size != (bg_w, bg_h):
                    # Prefer top-left paste of native paint; only resize when nearly full-frame
                    pw, ph = pl.size
                    if abs(pw - bg_w) < 5 and abs(ph - bg_h) < 5:
                        pl = pl.resize((bg_w, bg_h), Image.NEAREST)
                        composite.paste(pl, (0, 0), pl)
                    else:
                        composite.paste(pl, (0, 0), pl)
                else:
                    composite.paste(pl, (0, 0), pl)

            # Cell detections as open red donut rings
            if getattr(self, "last_cell_mask", None) is not None:
                try:
                    cell_mask = np.asarray(self.last_cell_mask).squeeze()
                    if cell_mask.ndim != 2:
                        if cell_mask.size > 0:
                            cell_mask = cell_mask.reshape(cell_mask.shape[0], -1)
                        else:
                            cell_mask = np.zeros((bg_h, bg_w), dtype=bool)
                    cell_mask = cell_mask > 0
                    ring_overlay = self._cell_detection_ring_overlay(
                        cell_mask,
                        size=(bg_w, bg_h),
                        color=(255, 0, 0),
                        alpha=200,
                        thickness=2,
                    )
                    composite = Image.alpha_composite(composite, ring_overlay)
                except Exception as e:
                    logger.debug(f"Could not overlay cell mask rings: {e}")
        except Exception as e:
            logger.debug(f"Could not apply overlays in flattened compose (base only): {e}")

        return composite.convert("RGB")

    def save_flattened_image(self, event=None):
        logger.info("Attempting to save flattened image")
        final = self._compose_flattened_image()
        if final is None:
            logger.warning("Save flattened image failed: No valid background image")
            messagebox.showerror("Error", "Please load a valid TIFF image first.")
            return

        # Default filename: original image name + _flattened + .tif
        default_name = "flattened.tif"
        if getattr(self, "tiff_filename", None):
            default_name = f"{self.tiff_filename}_flattened.tif"

        # Default into <image_dir>/output/flattened/ when available
        base_for_out = getattr(self, "tiff_dir", None) or getattr(
            self, "current_tiff_directory", None
        )
        out_dir = (
            self._get_output_directory(base_for_out, feature="flattened")
            if base_for_out
            else None
        )
        initialdir = out_dir or base_for_out or "."
        save_path = fd.asksaveasfilename(
            title="Save Flattened Image",
            initialdir=initialdir,
            initialfile=default_name,
            defaultextension=".tif",
            filetypes=[
                ("TIFF files", "*.tif *.tiff"),
                ("JPEG files", "*.jpg"),
                ("All files", "*.*"),
            ],
        )
        if save_path:
            try:
                # Do not pass compression='tiff_deflate' — it can segfault on some Windows Pillow + libtiff builds.
                final.save(save_path)
                messagebox.showinfo(
                    "Image Saved",
                    f"Flattened image (TIFF + regions + atlas + cells) saved to:\n{save_path}",
                )
            except Exception as e:
                logger.error(f"Failed to save flattened: {e}")
                messagebox.showerror("Save Error", f"Could not save the image:\n{e}")

    def autosave_flattened_image(self, filename):
        final = self._compose_flattened_image()
        if final is None:
            return
        try:
            # Do not pass compression='tiff_deflate' — it can segfault on some Windows Pillow + libtiff builds.
            final.save(filename)
        except Exception as e:
            logger.error(f"Autosave flattened failed: {e}")

    def toggle_crop_mode(self):
        self.save_state()
        self.crop_mode = not self.crop_mode
        self.crop_mode_var.set(self.crop_mode)
        if self.crop_mode:
            self.region_move_mode.set(False)
            self.border_mode_var.set(False)
            if getattr(self, "edit_mode", False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.region_translate_active = False
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self._clear_crop_ui()
            self.output.bind("<Button-1>", self.crop_start)
            self.output.bind("<B1-Motion>", self.crop_drag)
            self.output.bind("<ButtonRelease-1>", self.crop_end)
            self.output.bind("<Double-Button-1>", self._crop_double_click_apply)
            self.output.config(cursor="crosshair")
            self._set_crop_status(
                "Crop: drag to outline · drag box to move · Enter/double-click to apply · Esc to clear"
            )
            # Focus canvas so Enter applies crop (not a focused ribbon checkbutton)
            try:
                self.output.focus_set()
            except Exception:
                pass
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")
            self.output.unbind("<ButtonRelease-1>")
            try:
                self.output.unbind("<Double-Button-1>")
            except Exception:
                pass
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.output.config(cursor="")
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self._clear_crop_ui()
            self._set_crop_status(None)

    def _set_crop_status(self, text):
        """Show crop instructions in the window title while crop mode is active."""
        base = "Regional IF Analyzer"
        try:
            if getattr(self, "current_state", None) == "paint":
                # paint indicator owns the title
                return
            if text:
                self.master.title(f"{base} — {text}")
            else:
                cur = self.master.title() or base
                if "Crop:" in cur:
                    self.master.title(base)
        except Exception:
            pass

    def _clear_crop_ui(self):
        """Remove crop outline / shade overlays from the canvas."""
        ids = list(getattr(self, "crop_ui_ids", None) or [])
        if self.crop_rect is not None and self.crop_rect not in ids:
            ids.append(self.crop_rect)
        for iid in ids:
            try:
                self.output.delete(iid)
            except Exception:
                pass
        try:
            self.output.delete("crop_ui")
        except Exception:
            pass
        self.crop_ui_ids = []
        self.crop_rect = None

    def _normalize_crop_box(self, x1, y1, x2, y2):
        left, right = (x1, x2) if x1 <= x2 else (x2, x1)
        top, bottom = (y1, y2) if y1 <= y2 else (y2, y1)
        return float(left), float(top), float(right), float(bottom)

    def _point_in_crop_box(self, x, y, margin=0.0):
        if not self.crop_box:
            return False
        left, top, right, bottom = self.crop_box
        return (left - margin) <= x <= (right + margin) and (top - margin) <= y <= (
            bottom + margin
        )

    def _draw_crop_outline(self):
        """Draw a clear crop frame: dim outside, dual outline, move hint."""
        self._clear_crop_ui()
        if not self.crop_box:
            return
        left, top, right, bottom = self.crop_box
        if right - left < 1 or bottom - top < 1:
            return

        # Canvas extent for outside dimming
        try:
            bb = self.output.bbox("all")
        except Exception:
            bb = None
        if bb:
            cx0, cy0, cx1, cy1 = bb
        else:
            cx0, cy0 = 0, 0
            cx1 = max(int(self.output.winfo_width()), int(right) + 50)
            cy1 = max(int(self.output.winfo_height()), int(bottom) + 50)
        # Expand a bit so shade covers empty margins
        pad = 4000
        cx0, cy0 = min(cx0, left) - pad, min(cy0, top) - pad
        cx1, cy1 = max(cx1, right) + pad, max(cy1, bottom) + pad

        ids = []
        # Four shade panels outside the crop window (stipple ≈ semi-transparent)
        shade_kw = dict(fill="#000000", stipple="gray50", outline="", tags="crop_ui")
        # Top
        if top > cy0:
            ids.append(
                self.output.create_rectangle(cx0, cy0, cx1, top, **shade_kw)
            )
        # Bottom
        if bottom < cy1:
            ids.append(
                self.output.create_rectangle(cx0, bottom, cx1, cy1, **shade_kw)
            )
        # Left (between top/bottom of crop)
        if left > cx0:
            ids.append(
                self.output.create_rectangle(cx0, top, left, bottom, **shade_kw)
            )
        # Right
        if right < cx1:
            ids.append(
                self.output.create_rectangle(right, top, cx1, bottom, **shade_kw)
            )

        # High-contrast outline: white underlay + solid red crop frame
        ids.append(
            self.output.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline="#ffffff",
                width=5,
                tags="crop_ui",
            )
        )
        self.crop_rect = self.output.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline="#ff1a1a",
            width=3,
            dash=(),
            tags="crop_ui",
        )
        ids.append(self.crop_rect)

        # Corner ticks for a clear “window” look
        tick = max(8.0, min(24.0, 0.08 * min(right - left, bottom - top)))
        tick_kw = dict(fill="#ff1a1a", width=3, tags="crop_ui")
        for x, y, dx, dy in (
            (left, top, tick, 0),
            (left, top, 0, tick),
            (right, top, -tick, 0),
            (right, top, 0, tick),
            (left, bottom, tick, 0),
            (left, bottom, 0, -tick),
            (right, bottom, -tick, 0),
            (right, bottom, 0, -tick),
        ):
            ids.append(self.output.create_line(x, y, x + dx, y + dy, **tick_kw))

        # Instruction label just above the box
        label = "Crop window — drag to move · Enter to apply · Esc clear · click outside to re-draw"
        if self.crop_pending:
            # Shadow first, then light text on top
            ids.append(
                self.output.create_text(
                    (left + right) / 2.0 + 1,
                    top - 13,
                    text=label,
                    fill="#000000",
                    font=("Helvetica", 10, "bold"),
                    anchor="s",
                    tags="crop_ui",
                )
            )
            ids.append(
                self.output.create_text(
                    (left + right) / 2.0,
                    top - 14,
                    text=label,
                    fill="#ffdddd",
                    font=("Helvetica", 10, "bold"),
                    anchor="s",
                    tags="crop_ui",
                )
            )

        self.crop_ui_ids = ids
        try:
            self.output.tag_raise("crop_ui")
        except Exception:
            pass

    def _brain_image_aspect_ratio(self):
        """Width/height of the loaded brain-slice TIFF (for locked crop aspect).

        Returns None if no image is loaded.
        """
        bg = None
        if getattr(self, "original_background", None) is not None:
            bg = self.original_background
        elif getattr(self, "background_image", None) is not None:
            bg = self.background_image
        if bg is None:
            return None
        w, h = bg.size
        if w < 1 or h < 1:
            return None
        return float(w) / float(h)

    def _lock_crop_corner_to_image_aspect(self, start_x, start_y, cur_x, cur_y):
        """Return (end_x, end_y) so the crop rect matches the brain-image aspect ratio.

        Anchor is (start_x, start_y); the free corner is adjusted toward (cur_x, cur_y)
        while enforcing W/H = image aspect. If no image is loaded, returns the raw corner.
        """
        ar = self._brain_image_aspect_ratio()
        if ar is None or ar <= 0:
            return cur_x, cur_y

        dx = cur_x - start_x
        dy = cur_y - start_y
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return cur_x, cur_y

        # Choose width- or height-driven sizing so the rubber-band grows toward the cursor
        # while keeping aspect = image W/H.
        if abs(dy) < 1e-6 or abs(dx) >= abs(dy) * ar:
            # Width-driven
            w = abs(dx) if abs(dx) >= 1e-6 else abs(dy) * ar
            h = w / ar
        else:
            # Height-driven
            h = abs(dy)
            w = h * ar

        # Preserve drag direction (which quadrant)
        sx = 1.0 if dx >= 0 else -1.0
        sy = 1.0 if dy >= 0 else -1.0
        # If user only moved on one axis, still expand with positive sense on the other
        if abs(dx) < 1e-6:
            sx = 1.0
        if abs(dy) < 1e-6:
            sy = 1.0

        end_x = start_x + sx * w
        end_y = start_y + sy * h
        return end_x, end_y

    def crop_start(self, event):
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        self.start_x = cx
        self.start_y = cy

        # Pending selection: drag inside to move; click outside to re-draw
        if self.crop_pending and self.crop_box and self._point_in_crop_box(cx, cy):
            self._crop_interaction = "move"
            self._crop_move_origin = (cx, cy)
            self._crop_box_at_move_start = tuple(self.crop_box)
            self.output.config(cursor="fleur")
            return

        # Start a new rubber-band draw
        self._crop_interaction = "draw"
        self.crop_pending = False
        self._crop_draw_anchor = (cx, cy)
        self.crop_box = (cx, cy, cx, cy)
        self.output.config(cursor="crosshair")
        self._draw_crop_outline()

    def crop_drag(self, event):
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mode = getattr(self, "_crop_interaction", None)

        if mode == "move" and self._crop_box_at_move_start and self._crop_move_origin:
            ox, oy = self._crop_move_origin
            dx = cx - ox
            dy = cy - oy
            l0, t0, r0, b0 = self._crop_box_at_move_start
            self.crop_box = (l0 + dx, t0 + dy, r0 + dx, b0 + dy)
            self._draw_crop_outline()
            return

        if mode == "draw" and self._crop_draw_anchor is not None:
            ax, ay = self._crop_draw_anchor
            end_x, end_y = self._lock_crop_corner_to_image_aspect(ax, ay, cx, cy)
            self.crop_box = self._normalize_crop_box(ax, ay, end_x, end_y)
            self.start_x, self.start_y = ax, ay
            self._draw_crop_outline()

    def crop_end(self, event):
        """Finish draw or move — keep outlined selection pending (do not crop yet)."""
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mode = getattr(self, "_crop_interaction", None)
        self._crop_interaction = None
        self.output.config(cursor="crosshair" if self.crop_mode else "")

        if mode == "move":
            # Box already updated during drag; stay pending
            if self.crop_box:
                self.crop_pending = True
                self._draw_crop_outline()
                self._set_crop_status(
                    "Crop: drag box to move · Enter/double-click to apply · Esc to clear · click outside to re-draw"
                )
                try:
                    self.output.focus_set()
                except Exception:
                    pass
            self._crop_move_origin = None
            self._crop_box_at_move_start = None
            return

        if mode != "draw" or self._crop_draw_anchor is None:
            return

        ax, ay = self._crop_draw_anchor
        end_x, end_y = self._lock_crop_corner_to_image_aspect(ax, ay, cx, cy)
        left, top, right, bottom = self._normalize_crop_box(ax, ay, end_x, end_y)
        self._crop_draw_anchor = None

        # Too small → clear (click without drag)
        if (right - left) < 8 or (bottom - top) < 8:
            self.crop_pending = False
            self.crop_box = None
            self._clear_crop_ui()
            self._set_crop_status(
                "Crop: drag to outline · drag box to move · Enter/double-click to apply · Esc to clear"
            )
            return

        self.crop_box = (left, top, right, bottom)
        self.crop_pending = True
        self._draw_crop_outline()
        self._set_crop_status(
            "Crop: drag box to move · Enter/double-click to apply · Esc to clear · click outside to re-draw"
        )
        try:
            self.output.focus_set()
        except Exception:
            pass

    def _crop_double_click_apply(self, event=None):
        if self.crop_mode and self.crop_pending and self.crop_box:
            self._apply_pending_crop()
            return "break"

    def _on_return_key(self, event=None):
        """Enter/Return: apply pending crop first, else painted-border commit.

        Must return ``\"break\"`` so focused ttk.Checkbuttons (Crop) do not toggle
        off and discard the crop window.
        """
        if getattr(self, "crop_pending", False) and getattr(self, "crop_box", None):
            logger.info("Enter: applying pending atlas crop")
            self._apply_pending_crop()
            return "break"
        if getattr(self, "crop_mode", False) and getattr(self, "crop_box", None):
            # Selection exists but pending flag lost — still apply
            self.crop_pending = True
            logger.info("Enter: applying crop box (crop_mode on)")
            self._apply_pending_crop()
            return "break"
        # Not a crop apply — optional paint border refit (only if applicable)
        self._commit_painted_border_refit(event)
        return "break"

    def _on_escape_key(self, event=None):
        """Escape clears a pending crop selection; otherwise no-op."""
        if getattr(self, "crop_mode", False) and (
            getattr(self, "crop_pending", False) or self.crop_box
        ):
            self.crop_pending = False
            self.crop_box = None
            self._crop_interaction = None
            self._clear_crop_ui()
            self._set_crop_status(
                "Crop: drag to outline · drag box to move · Enter/double-click to apply · Esc to clear"
            )
            try:
                self.output.focus_set()
            except Exception:
                pass
            return "break"
        return None

    def _atlas_has_visible_ink(self, im):
        """True if an RGBA atlas layer has any non-trivial alpha ink."""
        if im is None:
            return False
        try:
            arr = np.array(im.convert("RGBA"))
            if arr.ndim != 3 or arr.shape[2] < 4:
                return bool(np.any(arr))
            return bool(np.any(arr[..., 3] > 10))
        except Exception:
            return False

    def _apply_pending_crop(self):
        """Apply the pending canvas crop box to atlas rasters.

        Crops base/page/mask/pure layers together and repositions so the crop
        stays under the selection. Does **not** run post-crop border rebuild/
        cleanup (that path was deleting the entire atlas after Apply).
        """
        if not self.crop_box:
            return
        try:
            self.save_state()
        except Exception:
            pass

        left_c, top_c, right_c, bottom_c = self.crop_box
        page = self.current_page
        vs = float(self.view_scale) if self.view_scale else 1.0
        if vs <= 0:
            vs = 1.0
        old_img_x = float(self.img_x) if self.img_x is not None else 0.0
        old_img_y = float(self.img_y) if self.img_y is not None else 0.0

        # Reference size from the clean base (or current page image)
        if page in self.base_page_images and self.base_page_images[page] is not None:
            ref_w, ref_h = self.base_page_images[page].size
        else:
            img0 = self.load_page_image()
            if img0 is None:
                self.crop_pending = False
                self.crop_box = None
                self._clear_crop_ui()
                self.show_page()
                if self.crop_mode:
                    self.toggle_crop_mode()
                return
            ref_w, ref_h = img0.size

        # Canvas rect of the atlas overlay (where the model raster is drawn)
        atlas_cx0 = old_img_x * vs
        atlas_cy0 = old_img_y * vs
        atlas_cx1 = atlas_cx0 + ref_w * vs
        atlas_cy1 = atlas_cy0 + ref_h * vs

        # Intersect user crop window with the atlas on canvas (more reliable than
        # converting free-floating corners that may sit outside the atlas).
        crop_cx0 = min(left_c, right_c)
        crop_cy0 = min(top_c, bottom_c)
        crop_cx1 = max(left_c, right_c)
        crop_cy1 = max(top_c, bottom_c)
        ix0 = max(crop_cx0, atlas_cx0)
        iy0 = max(crop_cy0, atlas_cy0)
        ix1 = min(crop_cx1, atlas_cx1)
        iy1 = min(crop_cy1, atlas_cy1)

        if ix1 - ix0 < 2 or iy1 - iy0 < 2:
            messagebox.showinfo(
                "Crop",
                "Crop window does not overlap the atlas.\n"
                "Drag the red box over the atlas drawing, then press Enter.",
            )
            return

        # Canvas intersection → model pixels
        mleft = (ix0 / vs) - old_img_x
        mtop = (iy0 / vs) - old_img_y
        mright = (ix1 / vs) - old_img_x
        mbottom = (iy1 / vs) - old_img_y

        left = int(np.floor(mleft))
        top = int(np.floor(mtop))
        right = int(np.ceil(mright))
        bottom = int(np.ceil(mbottom))
        left = max(0, min(left, ref_w))
        top = max(0, min(top, ref_h))
        right = max(left + 1, min(right, ref_w))
        bottom = max(top + 1, min(bottom, ref_h))
        if right - left < 2 or bottom - top < 2:
            messagebox.showinfo(
                "Crop",
                "Crop window is empty or outside the atlas.\n"
                "Drag a selection over the atlas, move it if needed, then press Enter.",
            )
            return

        box = (left, top, right, bottom)
        logger.info(
            f"Atlas crop model box={box} (native {ref_w}x{ref_h}) "
            f"canvas_intersect=({ix0:.1f},{iy0:.1f})-({ix1:.1f},{iy1:.1f}) "
            f"view_scale={vs} img_xy=({old_img_x},{old_img_y})"
        )

        def _crop_layer(im):
            if im is None:
                return None
            if im.size != (ref_w, ref_h):
                # Match reference atlas grid before crop
                resample = (
                    Image.NEAREST
                    if getattr(self, "atlas_filetype", None) == "allen"
                    else Image.BILINEAR
                )
                if im.mode in ("L", "P", "1"):
                    im = im.resize((ref_w, ref_h), Image.NEAREST)
                else:
                    im = im.resize((ref_w, ref_h), resample)
            return im.crop(box)

        # Snapshot for restore if crop yields blank
        pre_base = (
            self.base_page_images[page].copy()
            if page in self.base_page_images and self.base_page_images[page] is not None
            else None
        )
        pre_pure = (
            self.allen_borders_pure.copy()
            if getattr(self, "allen_borders_pure", None) is not None
            else None
        )

        # --- Crop every atlas raster with the *same* box (must stay aligned) ---
        if page in self.base_page_images and self.base_page_images[page] is not None:
            self.base_page_images[page] = _crop_layer(self.base_page_images[page])

        if page in self.page_images and self.page_images[page] is not None:
            self.page_images[page] = _crop_layer(self.page_images[page])
        elif pre_base is not None:
            self.page_images[page] = _crop_layer(pre_base)

        if page in self.mask_images and self.mask_images[page] is not None:
            self.mask_images[page] = _crop_layer(self.mask_images[page])
            if self.mask_images[page] is not None and self.mask_images[page].mode != "L":
                self.mask_images[page] = self.mask_images[page].convert("L")

        pure = getattr(self, "allen_borders_pure", None)
        if pure is not None:
            self.allen_borders_pure = _crop_layer(pure)
            if (
                self.allen_borders_pure is not None
                and self.allen_borders_pure.mode != "RGBA"
            ):
                self.allen_borders_pure = self.allen_borders_pure.convert("RGBA")

        # PDF-style art only: strip pure white leftover from crop (never Allen black borders)
        if (
            getattr(self, "atlas_filetype", None) != "allen"
            and page in self.base_page_images
            and self.base_page_images[page] is not None
            and self.base_page_images[page].mode == "RGBA"
        ):
            try:
                self.base_page_images[page] = self.img_white_to_transparent(
                    self.base_page_images[page]
                )
                if page in self.page_images and self.page_images[page] is not None:
                    self.page_images[page] = self.img_white_to_transparent(
                        self.page_images[page].convert("RGBA")
                    )
            except Exception:
                pass

        # Validate: if crop left no visible atlas ink, abort and restore
        ink_src = self.allen_borders_pure or self.base_page_images.get(page)
        if not self._atlas_has_visible_ink(ink_src):
            logger.warning(
                f"Crop produced empty atlas ink box={box}; restoring pre-crop layers"
            )
            if pre_base is not None:
                self.base_page_images[page] = pre_base
                self.page_images[page] = pre_base.copy()
            if pre_pure is not None:
                self.allen_borders_pure = pre_pure
            messagebox.showwarning(
                "Crop",
                "That crop window did not contain any atlas drawing "
                "(only empty transparent area).\n\n"
                "Move the red box so it covers the black atlas borders, then apply again.",
            )
            # Keep crop mode + selection so user can adjust
            return

        if getattr(self, "img", None) is not None and page in self.base_page_images:
            try:
                self.img = self.base_page_images[page].copy()
            except Exception:
                pass

        # Drop Atlas Manager names for zone IDs that no longer exist in the mask
        # (do NOT rebuild borders or delete structures that touch the crop edge).
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                m = np.array(self.mask_images[page])
                if m.ndim > 2:
                    m = m.squeeze()
                present = {int(z) for z in np.unique(m) if int(z) > 0}
                if page in self.zone_names and present is not None:
                    for zid in list(self.zone_names[page].keys()):
                        if int(zid) not in present:
                            del self.zone_names[page][zid]
            except Exception as e:
                logger.debug(f"Post-crop zone name prune skipped: {e}")

        # Placement: model (0,0) of the crop is old model (left, top)
        self.img_x = old_img_x + float(left)
        self.img_y = old_img_y + float(top)

        # Clear pending crop UI before show_page
        self.crop_pending = False
        self.crop_box = None
        self._clear_crop_ui()

        clear_preprocess_cache()
        try:
            self._rebuild_page_overlays(page)
        except Exception as e:
            logger.warning(f"rebuild after crop failed: {e}")
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        self.region_move_mode.set(False)

        try:
            if hasattr(self, "_update_ribbon_selection"):
                self._update_ribbon_selection()
        except Exception:
            pass

        self.show_page()
        if self.crop_mode:
            self.toggle_crop_mode()
        logger.info(
            f"Crop applied: new atlas size="
            f"{self.base_page_images.get(page).size if self.base_page_images.get(page) else None} "
            f"img_xy=({self.img_x:.1f},{self.img_y:.1f})"
        )
        if getattr(self, "count_button", None) is not None and not getattr(
            self, "count_button_packed", False
        ):
            try:
                self.count_button.pack(side=tk.LEFT, padx=10, pady=10)
                self.count_button_packed = True
            except Exception:
                pass

    def _cleanup_loose_borders_after_crop(self, page):
        """After crop: remove tiny orphan shards; keep intentional crop content.

        Important: structures that *touch* the crop frame are normal (user framed
        them). Older logic deleted every component on the frame, which erased the
        entire atlas after Apply Crop. Only small edge shards are removed now.
        Cropped border artwork is preserved unless a safer mask-edge rebuild
        still has content.
        """
        if page not in self.mask_images or self.mask_images[page] is None:
            self._prune_border_ink_without_mask(page)
            return

        try:
            mask_img = self.mask_images[page]
            m = np.array(mask_img)
            if m.ndim > 2:
                m = m.squeeze()
            h, w = m.shape[:2]
            if h < 2 or w < 2:
                return

            pre_area = int(np.sum(m > 0))
            if pre_area == 0:
                return

            # Snapshot cropped artwork before any rewrite
            pre_base = None
            pre_page = None
            pre_pure = None
            try:
                if page in self.base_page_images and self.base_page_images[page] is not None:
                    pre_base = self.base_page_images[page].copy()
                if page in self.page_images and self.page_images[page] is not None:
                    pre_page = self.page_images[page].copy()
                pure0 = getattr(self, "allen_borders_pure", None)
                if pure0 is not None:
                    pre_pure = pure0.copy()
            except Exception:
                pass

            # Per-component minimum for *true scraps* only
            min_area = max(24, int(0.0002 * h * w))
            min_area = min(min_area, 400)
            # Edge-cut shards must also be small; large bodies on the frame are kept
            edge_shard_max = max(min_area * 4, 150)

            cleaned = np.zeros_like(m)
            kept_cc = 0
            removed_cc = 0
            removed_edge = 0
            for zid in np.unique(m):
                zid = int(zid)
                if zid == 0:
                    continue
                region = m == zid
                try:
                    labeled = measure.label(region, connectivity=2)
                except Exception:
                    labeled = region.astype(np.int32)
                nlab = int(labeled.max()) if labeled is not None else 0
                if nlab == 0:
                    continue
                for lab in range(1, nlab + 1):
                    comp = labeled == lab
                    area = int(comp.sum())
                    if area < min_area:
                        removed_cc += 1
                        continue
                    # Only drop *small* incomplete shards on the crop frame.
                    # Large structures that touch the frame stay (intentional crop).
                    if (
                        area <= edge_shard_max
                        and self._mask_component_cut_by_frame(comp)
                    ):
                        removed_edge += 1
                        removed_cc += 1
                        continue
                    # Reject ultra-thin speckles with almost no body
                    try:
                        opened = morphology.binary_opening(comp, morphology.disk(1))
                        if int(opened.sum()) < max(8, min_area // 6) and area < edge_shard_max:
                            removed_cc += 1
                            continue
                    except Exception:
                        pass
                    cleaned[comp] = zid
                    kept_cc += 1

            post_area = int(np.sum(cleaned > 0))
            # Safety: never wipe a non-empty crop to empty via cleanup
            if pre_area > 0 and post_area == 0:
                logger.warning(
                    "Post-crop cleanup would remove all structures; keeping cropped mask/borders as-is"
                )
                return

            # If cleanup removed almost everything (>95%), keep original crop
            if pre_area > 0 and post_area < max(1, int(0.05 * pre_area)):
                logger.warning(
                    f"Post-crop cleanup too aggressive ({post_area}/{pre_area} px kept); "
                    "keeping cropped mask/borders as-is"
                )
                return

            self.mask_images[page] = Image.fromarray(cleaned.astype(np.uint8), mode="L")

            # Drop empty zone names from Atlas Manager
            if page in self.zone_names:
                present = {int(z) for z in np.unique(cleaned) if int(z) > 0}
                for zid in list(self.zone_names[page].keys()):
                    if int(zid) not in present:
                        del self.zone_names[page][zid]
            if (
                getattr(self, "selected_zone_id", None) is not None
                and getattr(self, "selected_page", None) == page
            ):
                try:
                    if int(self.selected_zone_id) not in {
                        int(z) for z in np.unique(cleaned) if int(z) > 0
                    }:
                        self.selected_zone_id = None
                        self.selected_page = None
                        self.selected_zone_component = None
                except Exception:
                    pass

            is_allen = getattr(self, "atlas_filetype", None) == "allen"
            is_border_atlas = is_allen or self._looks_like_border_only_atlas(
                pre_base if pre_base is not None else self.base_page_images.get(page)
            )

            # Prefer keeping the *cropped* border artwork (preserves Allen stroke style).
            # Only rebuild from mask edges when the cropped base has no visible ink.
            def _has_visible_ink(im):
                if im is None:
                    return False
                try:
                    arr = np.array(im.convert("RGBA"))
                    if arr.ndim != 3 or arr.shape[2] < 4:
                        return False
                    return bool(np.any(arr[..., 3] > 10))
                except Exception:
                    return False

            keep_cropped_art = _has_visible_ink(pre_base) or _has_visible_ink(pre_pure)
            if is_border_atlas and keep_cropped_art:
                # Keep cropped borders; optionally drop ink far from surviving mask
                if pre_base is not None:
                    self.base_page_images[page] = pre_base
                    self.page_images[page] = pre_base.copy() if pre_page is None else pre_page
                if pre_pure is not None:
                    self.allen_borders_pure = pre_pure
                elif pre_base is not None and (
                    is_allen or getattr(self, "allen_borders_pure", None) is not None
                ):
                    self.allen_borders_pure = pre_base.copy()
                if getattr(self, "img", None) is not None and pre_base is not None:
                    self.img = pre_base.copy()
                # Light filter: drop dark ink far from surviving structure edges
                try:
                    if cleaned is not None and pre_base is not None:
                        edge_from_mask = self._borders_from_structure_mask(cleaned)
                        self._filter_base_to_mask_edges(page, cleaned, edge_from_mask)
                except Exception:
                    pass
            else:
                # Rebuild borders from cleaned mask edges (pixel edges — no polylines)
                borders = self._borders_from_structure_mask(cleaned)
                if borders is not None and is_border_atlas:
                    # If rebuild is empty but we had art, restore crop
                    if not _has_visible_ink(borders) and keep_cropped_art:
                        if pre_base is not None:
                            self.base_page_images[page] = pre_base
                            self.page_images[page] = pre_page or pre_base
                        if pre_pure is not None:
                            self.allen_borders_pure = pre_pure
                    else:
                        self.base_page_images[page] = borders.copy()
                        self.page_images[page] = borders.copy()
                        if is_allen or getattr(self, "allen_borders_pure", None) is not None:
                            self.allen_borders_pure = borders.copy()
                        if getattr(self, "img", None) is not None:
                            self.img = borders.copy()
                elif borders is not None:
                    self._filter_base_to_mask_edges(page, cleaned, borders)

            logger.info(
                f"Post-crop structure cleanup page={page}: kept_cc={kept_cc} "
                f"removed_cc={removed_cc} (edge_shards={removed_edge}) "
                f"min_area={min_area} mask_px {pre_area}→{post_area} "
                f"kept_art={keep_cropped_art}"
            )
            try:
                if hasattr(self, "_update_ribbon_selection"):
                    self._update_ribbon_selection()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Post-crop loose-border cleanup failed: {e}", exc_info=True)

    def _mask_component_cut_by_frame(self, comp: np.ndarray) -> bool:
        """True if a connected mask component is truncated by the crop/image border.

        A structure that only *grazes* the frame with a couple of pixels is kept;
        a real cut (flat edge flush with the crop, as in incomplete boundary fills)
        has substantial contact with the frame.
        """
        if comp is None or not np.any(comp):
            return False
        h, w = comp.shape[:2]
        if h < 2 or w < 2:
            return True
        top = int(np.sum(comp[0, :]))
        bot = int(np.sum(comp[-1, :]))
        left = int(np.sum(comp[:, 0]))
        right = int(np.sum(comp[:, -1]))
        # Avoid double-counting corners in perimeter contact
        contact = top + bot + left + right
        if contact <= 0:
            return False
        area = int(comp.sum())
        # Contact along the longest side of the bbox is a strong "cut face" signal
        ys, xs = np.where(comp)
        bw = int(xs.max() - xs.min() + 1)
        bh = int(ys.max() - ys.min() + 1)
        max_side = max(bw, bh, 1)
        # Truncated if:
        #  - many pixels on the frame, or
        #  - a large fraction of the component sits on the frame, or
        #  - contact spans a large fraction of the component's bbox side (flat cut)
        if contact >= max(8, int(0.02 * area)):
            return True
        if contact >= max(6, int(0.25 * max_side)):
            return True
        if contact / float(area) >= 0.04:
            return True
        return False

    def _borders_from_structure_mask(self, mask_arr: np.ndarray) -> Image.Image:
        """Build black structure outlines from filled zone masks.

        Uses morphological / segmentation boundaries only — never ``ImageDraw.line``
        polylines. Polyline/curve drawing was connecting contour vertices with long
        chords across interiors (the diamond/X artifact after crop).
        """
        h, w = mask_arr.shape[:2]
        edge = np.zeros((h, w), dtype=bool)

        # Prefer skimage find_boundaries (outer edges of each label)
        try:
            from skimage.segmentation import find_boundaries
            # Treat 0 as background; each positive label gets its outer boundary
            if np.any(mask_arr > 0):
                edge = find_boundaries(mask_arr, mode="outer", background=0)
        except Exception:
            edge = np.zeros((h, w), dtype=bool)

        # Fallback / supplement: per-zone morphological gradient (region XOR erode)
        if not edge.any():
            for zid in np.unique(mask_arr):
                zid = int(zid)
                if zid == 0:
                    continue
                region = mask_arr == zid
                try:
                    er = morphology.binary_erosion(region, morphology.disk(1))
                    edge |= region & ~er
                except Exception:
                    # 4-neighbour edge approx
                    up = np.zeros_like(region)
                    down = np.zeros_like(region)
                    left = np.zeros_like(region)
                    right = np.zeros_like(region)
                    up[1:, :] = region[:-1, :]
                    down[:-1, :] = region[1:, :]
                    left[:, 1:] = region[:, :-1]
                    right[:, :-1] = region[:, 1:]
                    edge |= region & ~(up & down & left & right)

        # Drop isolated edge speckles (loose fragments)
        try:
            labeled = measure.label(edge, connectivity=2)
            min_edge = max(12, int(0.00015 * h * w))
            for lab in range(1, int(labeled.max()) + 1):
                comp = labeled == lab
                if int(comp.sum()) < min_edge:
                    edge[comp] = False
        except Exception:
            pass

        out = np.zeros((h, w, 4), dtype=np.uint8)
        out[edge, 0] = 0
        out[edge, 1] = 0
        out[edge, 2] = 0
        out[edge, 3] = 255
        return Image.fromarray(out, "RGBA")

    def _looks_like_border_only_atlas(self, base_img) -> bool:
        """True if base is mostly transparent with dark stroke ink (Allen-style)."""
        if base_img is None:
            return False
        try:
            arr = np.asarray(base_img.convert("RGBA"))
            alpha = arr[..., 3] > 20
            if not alpha.any():
                return True
            ink = arr[alpha]
            # Near-black strokes
            dark = (ink[:, 0] < 40) & (ink[:, 1] < 40) & (ink[:, 2] < 40)
            return float(dark.mean()) > 0.7 and float(alpha.mean()) < 0.35
        except Exception:
            return False

    def _filter_base_to_mask_edges(self, page, mask_arr, edge_borders):
        """For PDF bases: clear border-like ink that is not near a structure edge."""
        if page not in self.base_page_images or self.base_page_images[page] is None:
            return
        try:
            base = self.base_page_images[page].convert("RGBA")
            ba = np.array(base)
            edge = np.array(edge_borders)
            edge_ink = edge[..., 3] > 0 if edge.ndim == 3 else edge > 0
            # Dilate structure edges slightly so anti-aliased strokes survive
            try:
                edge_ink = morphology.binary_dilation(edge_ink, morphology.disk(2))
            except Exception:
                pass
            # Transparent or non-dark pixels always kept; dark stroke only kept on edges
            alpha = ba[..., 3] > 20
            dark = (
                (ba[..., 0] < 45)
                & (ba[..., 1] < 45)
                & (ba[..., 2] < 45)
                & alpha
            )
            loose = dark & ~edge_ink
            ba[loose, 3] = 0
            self.base_page_images[page] = Image.fromarray(ba, "RGBA")
            if page in self.page_images:
                self.page_images[page] = self.base_page_images[page].copy()
        except Exception as e:
            logger.debug(f"PDF base edge filter skipped: {e}")

    def _prune_border_ink_without_mask(self, page):
        """If there is no mask, drop tiny disconnected dark strokes on transparent base."""
        if page not in self.base_page_images or self.base_page_images[page] is None:
            return
        if not self._looks_like_border_only_atlas(self.base_page_images[page]):
            return
        try:
            ba = np.array(self.base_page_images[page].convert("RGBA"))
            ink = (
                (ba[..., 3] > 20)
                & (ba[..., 0] < 45)
                & (ba[..., 1] < 45)
                & (ba[..., 2] < 45)
            )
            labeled, n = measure.label(ink, connectivity=2, return_num=True)
            min_area = max(15, int(0.0001 * ink.size))
            for i in range(1, n + 1):
                comp = labeled == i
                if int(comp.sum()) < min_area:
                    ba[comp, 3] = 0
            self.base_page_images[page] = Image.fromarray(ba, "RGBA")
            if page in self.page_images:
                self.page_images[page] = self.base_page_images[page].copy()
            if getattr(self, "allen_borders_pure", None) is not None:
                self.allen_borders_pure = self.base_page_images[page].copy()
        except Exception as e:
            logger.debug(f"Border-only prune skipped: {e}")

    def toggle_edit_mode(self):
        self.save_state()
        self.edit_mode = not self.edit_mode
        self.edit_mode_var.set(self.edit_mode)
        if self.edit_mode:
            self.region_move_mode.set(False)
            self.border_mode_var.set(False)
            if getattr(self, 'crop_mode', False):
                self.crop_mode = False
                self.crop_mode_var.set(False)
                self.crop_pending = False
                self.crop_box = None
                self._crop_interaction = None
                self._clear_crop_ui()
                self._set_crop_status(None)
                try:
                    self.output.unbind("<Double-Button-1>")
                except Exception:
                    pass
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                self.output.config(cursor="")
            self.region_translate_active = False
            self.output.bind("<Button-1>", self.drag_start)
            self.output.bind("<B1-Motion>", self.drag_move)
        else:
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.unbind("<B1-Motion>")
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)

    def drag_start(self, event):
        # Give priority to per-region features (Move Selected Region checkbox or border/edge grab)
        # even if the global "Move" (edit_mode) binding is active. This prevents "move selected"
        # or edge grab from moving the whole atlas layer like the global drag does.
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_atlas(cx, cy)
        if self.region_move_mode.get() and self.selected_zone_id is not None and getattr(self, 'selected_page', None) == self.current_page:
            if not self._is_near_selected_border(mx, my, screen_tol=8):
                self._start_region_translate(mx, my)
                return
        if (getattr(self, 'border_mode_var', None) and self.border_mode_var.get() and
                self.selected_zone_id is not None and getattr(self, 'selected_page', None) == self.current_page):
            if self._is_near_selected_border(mx, my, screen_tol=8) or \
               (getattr(self, 'selected_edge_full_contour', None) is not None and self._is_click_on_selected_edge(mx, my, screen_tol=10)):
                self._try_start_border_drag(event)
                return
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag_move(self, event):
        # Delegate to per-region translate or edge grab logic if active (see drag_start priority).
        if getattr(self, 'region_translate_active', False):
            mx, my = self._canvas_to_atlas(self.output.canvasx(event.x), self.output.canvasy(event.y))
            dx = mx - self.region_translate_start_mx
            dy = my - self.region_translate_start_my
            if self.region_translate_original_mask is not None:
                self.mask_images[self.current_page] = self.region_translate_original_mask.copy()
                self._apply_region_translation(dx, dy)
                self._refresh_atlas_layer()
            return
        if getattr(self, 'edge_grab_active', False) or getattr(self, '_edge_pending_deselect', False):
            self._handle_border_drag_motion(event)
            return
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        # Convert screen drag to model-space offset (img_x/y are native pixels)
        vs = self.view_scale if self.view_scale else 1.0
        self.img_x += dx / vs
        self.img_y += dy / vs
        self.show_page()
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def _transform_allen_borders_pure(self, *, rotate_deg=None, scale_xy=None, expand_rotate=True):
        """Keep allen_borders_pure in sync with base/mask on rotate/scale (same size always)."""
        pure = getattr(self, "allen_borders_pure", None)
        if pure is None or getattr(self, "atlas_filetype", None) != "allen":
            return
        if rotate_deg is not None:
            pure = pure.rotate(
                rotate_deg, expand=expand_rotate, resample=Image.NEAREST, fillcolor=(0, 0, 0, 0)
            )
        if scale_xy is not None:
            sx, sy = scale_xy
            nw = max(1, int(pure.width * sx))
            nh = max(1, int(pure.height * sy))
            pure = pure.resize((nw, nh), Image.NEAREST)
        self.allen_borders_pure = pure.convert("RGBA") if pure.mode != "RGBA" else pure

    def rotate_custom(self):
        self.save_state()
        try:
            degrees = float(self.rotation_entry.get())
            page = self.current_page
            # Transform the clean base (the atlas artwork) and the zone mask
            if page in self.base_page_images:
                base = self.base_page_images[page]
                rotated_base = base.rotate(degrees, expand=True)
                self.base_page_images[page] = rotated_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                rotated_mask = mask_img.rotate(degrees, expand=True, resample=Image.NEAREST)
                self.mask_images[page] = rotated_mask
            self._transform_allen_borders_pure(rotate_deg=degrees, expand_rotate=True)
            clear_preprocess_cache()
            self._rebuild_page_overlays(page)
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid number for rotation degrees.")

    def fit_atlas_to_image(self):
        """Resize the atlas (or remaining cropped atlas) to match the loaded TIFF size.

        Aligns the top-left of the atlas with the top-left of the background image
        (img_x = img_y = 0). Scales base, page overlay, zone mask, and Allen pure
        borders together so they stay registered.
        """
        if not self.atlas_filetype:
            messagebox.showwarning("No Atlas", "Load an atlas first (Atlas → Import…).")
            return

        # Target = loaded experimental image (prefer full-res original)
        bg = None
        if getattr(self, "original_background", None) is not None:
            bg = self.original_background
        elif getattr(self, "background_image", None) is not None:
            bg = self.background_image
        if bg is None:
            messagebox.showwarning(
                "No Image",
                "Load a TIFF/image first so the atlas can be fit to its size.",
            )
            return

        page = self.current_page
        if page not in self.base_page_images or self.base_page_images[page] is None:
            # Fall back to current page image as base
            img = self.load_page_image()
            if img is None:
                messagebox.showwarning("No Atlas", "No atlas page image is available to scale.")
                return
            self.base_page_images[page] = img.copy()

        base = self.base_page_images[page]
        tw, th = bg.size
        aw, ah = base.size
        if tw < 2 or th < 2 or aw < 2 or ah < 2:
            messagebox.showerror("Fit to image", "Image or atlas size is invalid.")
            return

        self.save_state()
        target = (int(tw), int(th))
        sx = tw / float(aw)
        sy = th / float(ah)
        logger.info(
            f"Fit atlas to image: atlas {aw}x{ah} → image {tw}x{th} "
            f"(sx={sx:.4f}, sy={sy:.4f})"
        )

        # Base / overlay: bilinear for smooth outlines on PDF; NEAREST for Allen borders
        is_allen = getattr(self, "atlas_filetype", None) == "allen"
        base_resample = Image.NEAREST if is_allen else Image.BILINEAR
        self.base_page_images[page] = base.resize(target, base_resample)

        if page in self.page_images and self.page_images[page] is not None:
            self.page_images[page] = self.page_images[page].resize(target, base_resample)

        if page in self.mask_images and self.mask_images[page] is not None:
            self.mask_images[page] = self.mask_images[page].resize(target, Image.NEAREST)

        pure = getattr(self, "allen_borders_pure", None)
        if pure is not None and is_allen:
            self.allen_borders_pure = pure.resize(target, Image.NEAREST)
            if self.allen_borders_pure.mode != "RGBA":
                self.allen_borders_pure = self.allen_borders_pure.convert("RGBA")

        if getattr(self, "img", None) is not None:
            try:
                self.img = self.base_page_images[page].copy()
            except Exception:
                pass

        # Top-left of atlas = top-left of background image (drawn at 0,0)
        self.img_x = 0
        self.img_y = 0

        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self.selected_zone_id = None
        self.selected_page = None
        self.selected_zone_component = None
        self.region_move_mode.set(False)
        self.show_page()
        messagebox.showinfo(
            "Fit to image",
            f"Atlas resized to {tw}×{th} px to match the loaded image.\n"
            f"Top-left corners aligned.",
        )

    def resize_custom(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            page = self.current_page
            if page in self.base_page_images:
                base = self.base_page_images[page]
                new_size = (int(base.width * scale), int(base.height * scale))
                resized_base = base.resize(new_size, Image.BILINEAR)
                self.base_page_images[page] = resized_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                new_size = (int(mask_img.width * scale), int(mask_img.height * scale))
                resized_mask = mask_img.resize(new_size, Image.NEAREST)
                self.mask_images[page] = resized_mask
            self._transform_allen_borders_pure(scale_xy=(scale, scale))
            clear_preprocess_cache()
            self._rebuild_page_overlays(page)
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def resize_x(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            page = self.current_page
            if page in self.base_page_images:
                base = self.base_page_images[page]
                new_size = (int(base.width * scale), base.height)
                resized_base = base.resize(new_size, Image.BILINEAR)
                self.base_page_images[page] = resized_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                new_size = (int(mask_img.width * scale), mask_img.height)
                resized_mask = mask_img.resize(new_size, Image.NEAREST)
                self.mask_images[page] = resized_mask
            self._transform_allen_borders_pure(scale_xy=(scale, 1.0))
            self._rebuild_page_overlays(page)
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    def resize_y(self):
        self.save_state()
        try:
            scale = float(self.scale_entry.get())
            if scale <= 0:
                raise ValueError("Scale must be positive")
            page = self.current_page
            if page in self.base_page_images:
                base = self.base_page_images[page]
                new_size = (base.width, int(base.height * scale))
                resized_base = base.resize(new_size, Image.BILINEAR)
                self.base_page_images[page] = resized_base
            if page in self.mask_images:
                mask_img = self.mask_images[page]
                new_size = (mask_img.width, int(mask_img.height * scale))
                resized_mask = mask_img.resize(new_size, Image.NEAREST)
                self.mask_images[page] = resized_mask
            self._transform_allen_borders_pure(scale_xy=(1.0, scale))
            self._rebuild_page_overlays(page)
            self.show_page()
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid positive number for scale factor.")

    # ------------------------------------------------------------------
    # NEW: Per-region select + rotate/scale for individual atlas zones
    # ------------------------------------------------------------------

    def select_region(self):
        """Prompt user to click a named atlas region to select it for individual shape adjustment."""
        if not self.atlas_filetype:
            messagebox.showwarning("No Atlas", "Load an atlas first (Atlas > Import Atlas).")
            return
        self.save_state()
        messagebox.showinfo(
            "Select Region",
            "Click inside a yellow/orange named region on the atlas to select it.\n"
            "Then use 'Rotate Selected Region' or 'Scale Selected Region' from the Atlas menu."
        )
        # One-shot picker
        self.output.bind("<Button-1>", self._pick_and_select_region)

    def _selected_component_mask(self, m, zid):
        """Boolean mask for the selected connected component of zid (or whole zid)."""
        comp = getattr(self, "selected_zone_component", None)
        if (
            comp is not None
            and isinstance(comp, np.ndarray)
            and comp.shape[:2] == m.shape[:2]
        ):
            return comp.astype(bool)
        return m == int(zid)

    def _set_zone_selection(self, page, zid, atlas_x=None, atlas_y=None):
        """Set selected zone; if atlas_x/y given, limit highlight to that connected component."""
        self.selected_zone_id = int(zid)
        self.selected_page = page
        self.selected_zone_component = None
        if atlas_x is None or atlas_y is None:
            return
        try:
            if page not in self.mask_images or self.mask_images[page] is None:
                return
            m = np.array(self.mask_images[page])
            if m.ndim > 2:
                m = m.squeeze()
            x, y = int(round(atlas_x)), int(round(atlas_y))
            if not (0 <= y < m.shape[0] and 0 <= x < m.shape[1]):
                return
            if int(m[y, x]) != int(zid):
                return
            from scipy import ndimage as _ndi
            labeled, nlab = _ndi.label(m == int(zid))
            if nlab < 1:
                return
            cid = int(labeled[y, x])
            if cid == 0:
                return
            self.selected_zone_component = labeled == cid
        except Exception as e:
            logger.debug(f"Component selection failed: {e}")
            self.selected_zone_component = None

    def deselect_region(self):
        """Clear current region selection (fill tint + boundary color back to default)."""
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        if self.selected_zone_id is not None:
            self.selected_zone_id = None
            self.selected_page = None
            self.selected_zone_component = None
            if self.current_page in self.base_page_images:
                self._rebuild_page_overlays(self.current_page)
            # Boundary back to black for all regions
            self._refresh_selection_boundary_visual()
            self.show_page()
            self._update_ribbon_selection()

    def _pick_and_select_region(self, event):
        """Temporarily bound click handler to pick a zone from the mask under cursor."""
        logger.debug(f"Region pick click at canvas ({event.x}, {event.y})")
        try:
            canvas_x = self.output.canvasx(event.x)
            canvas_y = self.output.canvasy(event.y)
            mx, my = self._canvas_to_atlas(canvas_x, canvas_y)
            x, y = int(mx), int(my)

            if self.current_page not in self.mask_images:
                messagebox.showwarning("No Regions", "No zone mask for current atlas page.")
                return

            mask_img = self.mask_images[self.current_page]
            w, h = mask_img.size
            if x < 0 or y < 0 or x >= w or y >= h:
                messagebox.showinfo("Click Outside", "Click inside the atlas overlay area.")
                return

            m = np.array(mask_img)
            if 0 <= y < m.shape[0] and 0 <= x < m.shape[1]:
                zid = int(m[y, x])
            else:
                zid = 0

            if zid == 0:
                messagebox.showwarning("No Region", "Clicked on background / unlabeled area. Click inside a named (yellow) region.")
                return

            # Ensure any mask-claimed zone (even if it lacked a name entry) gets a default and
            # will appear in the Atlas Manager labeled list.
            self._ensure_zone_has_name(self.current_page, zid)

            self._set_zone_selection(self.current_page, zid, atlas_x=x, atlas_y=y)
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self._edge_pending_deselect = False
            self.region_move_mode.set(False)
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            zname = self.zone_names.get(self.current_page, {}).get(zid, f"Zone {zid}")
            messagebox.showinfo("Selected", f"Region '{zname}' (ID {zid}) is now selected for transform.\n\nUse Atlas menu Rotate/Scale Selected Region or drag its border (if enabled in ribbon).")
            # Orange fill + yellow boundary
            self._rebuild_page_overlays(self.current_page)
            self._refresh_selection_boundary_visual()
            self.show_page()
            self._update_ribbon_selection()
        finally:
            # Restore normal left-click behavior (name/highlight regions)
            self.output.bind("<Button-1>", self.highlight_region)
            self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)

    def _has_selected_region(self):
        if self.selected_zone_id is None or self.selected_page is None:
            return False
        if self.selected_page != self.current_page:
            messagebox.showwarning("Page Mismatch", "The selected region is on a different atlas page. Please re-select on the current page.")
            self.selected_zone_id = None
            self.selected_page = None
            return False
        return True

    def _ensure_zone_has_name(self, page, zid):
        """If a positive zone id appears in the mask but has no friendly name in zone_names,
        auto-register a default name so it shows up in the Labeled Regions manager and
        canvas clicks on it will autoselect instead of re-prompting for a name.
        Also bumps the zone counter so future new names don't collide with existing ids.
        """
        zid = int(zid)
        if zid <= 0:
            return
        if page not in self.zone_names:
            self.zone_names[page] = {}
        if zid not in self.zone_names[page]:
            default_name = f"Region {zid}"
            self.zone_names[page][zid] = default_name
            logger.debug(f"Auto-registered default name for orphan zone {zid} on page {page}")
        if page not in self.zone_counters:
            self.zone_counters[page] = 0
        if self.zone_counters[page] < zid:
            self.zone_counters[page] = zid

    def _apply_transform_to_region(self, page, zone_id, angle_deg=0.0, scale_x=1.0, scale_y=1.0):
        """Rotate (around centroid) and/or scale the shape of a single zone in the label mask.
        The underlying base atlas image is left unchanged (lines stay for reference); only the
        zone's yellow area (for viz) and the mask pixels (for counting) are adjusted.
        Centroid of the region is kept approximately in place.
        """
        if page not in self.mask_images or zone_id is None:
            return False
        mask_img = self.mask_images[page]
        m = np.array(mask_img)
        if zone_id not in m:
            return False

        region = (m == zone_id)
        if not region.any():
            return False

        ys, xs = np.where(region)
        cy = float(np.mean(ys))
        cx = float(np.mean(xs))

        # Compute tight bbox + pad
        miny, maxy = int(ys.min()), int(ys.max())
        minx, maxx = int(xs.min()), int(xs.max())
        pad = 4
        miny = max(0, miny - pad)
        minx = max(0, minx - pad)
        maxy = min(m.shape[0] - 1, maxy + pad)
        maxx = min(m.shape[1] - 1, maxx + pad)

        region_crop = region[miny:maxy+1, minx:maxx+1].astype(np.uint8) * 255
        bin_img = Image.fromarray(region_crop, mode='L')

        # Rotate around the crop center (approximates; we correct with centroid later)
        if abs(angle_deg) > 0.0001:
            bin_img = bin_img.rotate(angle_deg, resample=Image.NEAREST, expand=True)

        # Scale (post-rotate)
        if abs(scale_x - 1.0) > 0.0001 or abs(scale_y - 1.0) > 0.0001:
            nw = max(1, int(bin_img.width * scale_x))
            nh = max(1, int(bin_img.height * scale_y))
            bin_img = bin_img.resize((nw, nh), Image.NEAREST)

        new_bin = np.array(bin_img) > 127
        if not new_bin.any():
            return False

        new_ys, new_xs = np.where(new_bin)
        new_cy_loc = float(np.mean(new_ys))
        new_cx_loc = float(np.mean(new_xs))

        # Position the patch so its new centroid lands on the original world centroid
        paste_x = int(round(cx - new_cx_loc))
        paste_y = int(round(cy - new_cy_loc))

        # Build new mask: clear old zone pixels, paste transformed
        new_m = m.copy()
        new_m[region] = 0

        nh, nw = new_bin.shape
        y1 = max(0, paste_y)
        x1 = max(0, paste_x)
        y2 = min(new_m.shape[0], paste_y + nh)
        x2 = min(new_m.shape[1], paste_x + nw)

        if y2 > y1 and x2 > x1:
            sub = new_bin[(y1 - paste_y):(y2 - paste_y), (x1 - paste_x):(x2 - paste_x)]
            new_m[y1:y2, x1:x2][sub] = zone_id

        self.mask_images[page] = Image.fromarray(new_m.astype(np.uint8), mode='L')
        clear_preprocess_cache()

        # Update visuals from base + new mask (selected will be orange if still selected)
        self._rebuild_page_overlays(page)
        return True

    def _apply_border_pull(self, pull_amount):
        """One-sided border pull: only the side being dragged moves (the pulled "cap" of the region).
        The opposite side stays fixed. This stretches/deforms the region from the contact edge.
        pull_amount is the signed offset along the precomputed unit normal (positive = outward).
        """
        page = self.current_page
        zid = self.border_drag_zone
        if page not in self.mask_images or zid is None:
            return False

        orig = np.array(self.mask_images[page])
        region = (orig == zid)
        if not region.any():
            return False

        ys, xs = np.where(region)
        cx, cy = self.border_drag_centroid
        ux, uy = self.border_drag_unit

        new_mask = orig.copy()
        new_mask[region] = 0

        for y, x in zip(ys, xs):
            vx = x - cx
            vy = y - cy
            side = vx * ux + vy * uy
            if side > 0:
                # This point is on the pulled side -> shift it
                nx = x + pull_amount * ux
                ny = y + pull_amount * uy
            else:
                nx = x
                ny = y

            ix = int(round(nx))
            iy = int(round(ny))
            if 0 <= iy < new_mask.shape[0] and 0 <= ix < new_mask.shape[1]:
                new_mask[iy, ix] = zid

        # Fill gaps and make the deformed region solid (important for counting)
        try:
            bin_zone = (new_mask == zid)
            # A little dilation helps connect the sampled points after rounding/shifting
            thickened = ndi.binary_dilation(bin_zone, iterations=1)
            filled = ndi.binary_fill_holes(thickened)
            # Only fill holes that belong to this zone, protect other zones
            new_mask[filled & (new_mask == 0)] = zid
            other_zones = (orig != 0) & (orig != zid)
            new_mask[other_zones] = orig[other_zones]
        except Exception:
            # Fallback: at least the sampled points are set
            pass

        self.mask_images[page] = Image.fromarray(new_mask.astype(np.uint8), mode='L')
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        return True

    def show_rotate_selected_dialog(self):
        if not self._has_selected_region():
            messagebox.showwarning("No Region Selected", "Use 'Atlas > Select Region' then click a named region first.")
            return
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)
        window.title("Rotate Selected Region")
        rotation_label = ttk.Label(window, text="Degrees:")
        rotation_label.grid(row=0, column=0)
        self.region_rotation_entry = ttk.Entry(window, width=10)
        self.region_rotation_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(window, text="Rotate", command=self.rotate_selected_region).grid(row=0, column=2, padx=5, pady=5)
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def rotate_selected_region(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_rotation_entry', None)
            degrees = float(entry.get()) if entry else 0.0
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=degrees, scale_x=1.0, scale_y=1.0):
                self.show_page()
                self._update_ribbon_selection()
            else:
                messagebox.showerror("Transform Failed", "Could not rotate the selected region.")
        except Exception as e:
            messagebox.showerror("Error", f"Enter a valid number. {e}")

    def show_scale_selected_dialog(self):
        if not self._has_selected_region():
            messagebox.showwarning("No Region Selected", "Use 'Atlas > Select Region' then click a named region first.")
            return
        window = Toplevel(self.master)
        window.attributes('-topmost', 'true')
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self._register_transparent_window(window)
        window.title("Scale Selected Region")
        scale_label = ttk.Label(window, text="Scale factor:")
        scale_label.grid(row=0, column=0)
        self.region_scale_entry = ttk.Entry(window, width=10)
        self.region_scale_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(window, text="Resize", command=self.scale_selected_uniform).grid(row=1, column=0, padx=5, pady=5)
        ttk.Button(window, text="Resize X", command=self.scale_selected_x).grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(window, text="Resize Y", command=self.scale_selected_y).grid(row=1, column=2, padx=5, pady=5)
        close_button = tk.Button(window, text="Close", command=lambda: window.destroy())
        close_button.grid(row=10, column=2, sticky=tk.SE, padx=5, pady=5)

    def scale_selected_uniform(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_scale_entry', None)
            s = float(entry.get()) if entry else 1.0
            if s <= 0:
                raise ValueError("Scale > 0")
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=s, scale_y=s):
                self.show_page()
                self._update_ribbon_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid scale: {e}")

    def scale_selected_x(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_scale_entry', None)
            s = float(entry.get()) if entry else 1.0
            if s <= 0:
                raise ValueError("Scale > 0")
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=s, scale_y=1.0):
                self.show_page()
                self._update_ribbon_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid scale: {e}")

    def scale_selected_y(self):
        if not self._has_selected_region():
            return
        self.save_state()
        try:
            entry = getattr(self, 'region_scale_entry', None)
            s = float(entry.get()) if entry else 1.0
            if s <= 0:
                raise ValueError("Scale > 0")
            page = self.selected_page
            zid = self.selected_zone_id
            if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=1.0, scale_y=s):
                self.show_page()
                self._update_ribbon_selection()
        except Exception as e:
            messagebox.showerror("Error", f"Invalid scale: {e}")

    # --- Atlas Manager Ribbon UI ---
    def _build_atlas_ribbon(self, parent):
        """Builds a collapsible 'ribbon' / panel for Atlas region management.
        Header always visible with toggle arrow and current selection summary.
        Expanded content shows: selected region info, global tools (Crop/Move + quick global adjust),
        per-region translate/edge, quick selected-region adjust, labeled regions list, border drag toggle.
        """
        self.atlas_ribbon = ttk.Frame(parent, relief=tk.GROOVE, borderwidth=1)

        # Header row (always shown)
        header = ttk.Frame(self.atlas_ribbon)
        header.pack(fill='x', padx=2, pady=1)

        self.ribbon_arrow_var = tk.StringVar(value="▶")
        self.ribbon_toggle = ttk.Button(
            header, textvariable=self.ribbon_arrow_var, width=3,
            command=self._toggle_atlas_ribbon
        )
        self.ribbon_toggle.pack(side=tk.LEFT, padx=(2, 4))

        ttk.Label(header, text="Atlas Manager", font=("Helvetica", 9, "bold")).pack(side=tk.LEFT)

        self.ribbon_selected_var = tk.StringVar(value="No region selected")
        ttk.Label(header, textvariable=self.ribbon_selected_var, foreground="#0066cc").pack(side=tk.LEFT, padx=8)

        # Paint mode indicator (visible in the ribbon header)
        self.paint_status_label = ttk.Label(header, textvariable=self.paint_status_var, foreground="gray", font=("Helvetica", 8))
        self.paint_status_label.pack(side=tk.LEFT, padx=8)

        # Prominent Undo button (works for paint, atlas edits, mask edits, etc.)
        # Placed in the always-visible ribbon header so it's easy to reach.
        ttk.Button(header, text="↶ Undo", command=self.undo, width=7).pack(side=tk.RIGHT, padx=4)

        # Expandable content
        self.ribbon_content = ttk.Frame(self.atlas_ribbon)

        # Selection info
        sel_frame = ttk.Frame(self.ribbon_content)
        sel_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(sel_frame, text="Selected Region:").pack(side=tk.LEFT)
        self.ribbon_sel_name_var = tk.StringVar(value="None")
        name_lbl = ttk.Label(sel_frame, textvariable=self.ribbon_sel_name_var, width=28, relief="sunken", padding=2)
        name_lbl.pack(side=tk.LEFT, padx=4)
        ttk.Button(sel_frame, text="Select Region", command=self.select_region, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(sel_frame, text="Deselect", command=self.deselect_region, width=8).pack(side=tk.LEFT)

        # Global atlas tools (Crop / Move for whole overlay alignment) - now checkboxes so user can see active state
        global_frame = ttk.Frame(self.ribbon_content)
        global_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(global_frame, text="Global:").pack(side=tk.LEFT)
        ttk.Checkbutton(global_frame, text="Crop", variable=self.crop_mode_var, command=self.toggle_crop_mode, width=7).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_frame, text="Apply Crop", command=self._apply_pending_crop, width=10).pack(side=tk.LEFT, padx=1)
        ttk.Checkbutton(global_frame, text="Move", variable=self.edit_mode_var, command=self.toggle_edit_mode, width=7).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_frame, text="Clear Atlas", command=self.clear_atlas, width=11).pack(side=tk.LEFT, padx=6)
        ttk.Button(global_frame, text="Next Channel…", command=self.next_channel, width=13).pack(side=tk.LEFT, padx=2)

        # Global quick adjust (mirrors the selected-region quick adjust below)
        global_manip_frame = ttk.Frame(self.ribbon_content)
        global_manip_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(global_manip_frame, text="Global Quick Adjust:").pack(side=tk.LEFT)
        ttk.Button(global_manip_frame, text="Rot +5°", command=lambda: self._quick_rotate_global(5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Rot -5°", command=lambda: self._quick_rotate_global(-5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Scale +5%", command=lambda: self._quick_scale_global(1.05), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Scale -5%", command=lambda: self._quick_scale_global(0.95), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(global_manip_frame, text="Dialogs...", command=self.show_rotate_settings, width=9).pack(side=tk.LEFT, padx=4)

        # Move selected region (translate only this zone's area in the mask; underlying atlas stays fixed)
        move_frame = ttk.Frame(self.ribbon_content)
        move_frame.pack(fill='x', padx=4, pady=2)
        ttk.Checkbutton(move_frame, text="Move Selected Region (click+drag inside orange to translate it)", variable=self.region_move_mode, command=self._on_region_move_mode_toggled).pack(anchor='w')

        # Quick manip for selected region
        manip_frame = ttk.Frame(self.ribbon_content)
        manip_frame.pack(fill='x', padx=4, pady=2)
        ttk.Label(manip_frame, text="Selected Region Quick Adjust:").pack(side=tk.LEFT)
        ttk.Button(manip_frame, text="Rot +5°", command=lambda: self._quick_rotate_selected(5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Rot -5°", command=lambda: self._quick_rotate_selected(-5), width=8).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Scale +5%", command=lambda: self._quick_scale_selected(1.05), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Scale -5%", command=lambda: self._quick_scale_selected(0.95), width=9).pack(side=tk.LEFT, padx=1)
        ttk.Button(manip_frame, text="Dialogs...", command=self._show_region_dialogs, width=9).pack(side=tk.LEFT, padx=4)

        # Selectable list of all labeled regions for current page
        list_frame = ttk.Frame(self.ribbon_content)
        list_frame.pack(fill='both', expand=True, padx=4, pady=2)
        ttk.Label(
            list_frame,
            text="Labeled Regions (current page) — click to select; right-click for Rename / Delete:",
        ).pack(anchor='w')
        lb_container = ttk.Frame(list_frame)
        lb_container.pack(fill='both', expand=True)
        self.region_listbox = tk.Listbox(lb_container, height=5, exportselection=False)
        self.region_listbox.pack(side=tk.LEFT, fill='both', expand=True)
        lb_scroll = ttk.Scrollbar(lb_container, orient=tk.VERTICAL, command=self.region_listbox.yview)
        lb_scroll.pack(side=tk.RIGHT, fill='y')
        self.region_listbox.configure(yscrollcommand=lb_scroll.set)
        self.region_listbox.bind('<<ListboxSelect>>', self._on_region_list_select)
        # Right-click context menu: Rename / Delete
        self.region_listbox.bind('<Button-3>', self._on_region_list_right_click)
        # macOS often uses Button-2 for secondary click
        self.region_listbox.bind('<Button-2>', self._on_region_list_right_click)
        self.region_listbox.bind('<Control-Button-1>', self._on_region_list_right_click)

        self._region_list_context_menu = tk.Menu(self.region_listbox, tearoff=0)
        self._region_list_context_menu.add_command(
            label="Rename", command=self._context_rename_region
        )
        self._region_list_context_menu.add_command(
            label="Delete", command=self._context_delete_region
        )
        self._context_menu_zone_id = None

        # Border drag help / toggle  (edge expand/shrink for selected region)
        border_frame = ttk.Frame(self.ribbon_content)
        border_frame.pack(fill='x', padx=4, pady=(2, 4))
        ttk.Checkbutton(border_frame, text="Border drag resize enabled (when region selected)", variable=self.border_mode_var, command=self._on_border_mode_toggled).pack(side=tk.LEFT)
        ttk.Label(border_frame, text="  Drag near the edges of the orange/yellow region to expand or shrink it from its center. Press Enter to commit the expanded shape and refit the black boundary (for painted regions).", font=("Helvetica", 8, "italic")).pack(side=tk.LEFT)

        # Start collapsed (value comes from __init__)

    def _toggle_atlas_ribbon(self):
        if getattr(self, 'atlas_ribbon_expanded', False):
            self.ribbon_content.pack_forget()
            self.ribbon_arrow_var.set("▶")
            self.atlas_ribbon_expanded = False
        else:
            self.ribbon_content.pack(fill='x', padx=2, pady=1)
            self.ribbon_arrow_var.set("▼")
            self.atlas_ribbon_expanded = True
            self._update_ribbon_selection()  # ensure list and selection are up to date when expanding content

    def _toggle_atlas_ribbon_visibility(self):
        """Called from View menu checkbutton to show or hide the entire Atlas Manager ribbon."""
        if self.show_atlas_ribbon.get():
            try:
                self.atlas_ribbon.grid(row=0, column=0, columnspan=2, sticky='ew', padx=2, pady=1)
                self._update_ribbon_selection()
            except Exception:
                pass
        else:
            try:
                self.atlas_ribbon.grid_remove()
            except Exception:
                pass

    def _on_region_move_mode_toggled(self):
        if self.region_move_mode.get():
            # If global layer Move (edit_mode) is active, its binding overrides <Button-1>,
            # so exit it to let highlight_region see the clicks (delegation in drag_* also helps).
            if getattr(self, 'edit_mode', False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                self.output.bind("<ButtonRelease-1>", self._end_border_drag, add=True)
            if getattr(self, 'crop_mode', False):
                self.crop_mode = False
                self.crop_mode_var.set(False)
                self.crop_pending = False
                self.crop_box = None
                self._crop_interaction = None
                self._clear_crop_ui()
                self._set_crop_status(None)
                try:
                    self.output.unbind("<Double-Button-1>")
                except Exception:
                    pass
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.border_drag_active = False
            self.output.config(cursor="")
        else:
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.border_drag_active = False
            self.output.config(cursor="")

    def _on_border_mode_toggled(self):
        """Called when the border drag (edge expand/shrink) checkbox is toggled.
        Enforces mutual exclusion with global move/crop: enabling edge deselects globals.
        """
        if self.border_mode_var.get():
            # Deselect global modes so user can tell edge expand is active (and avoid binding conflicts)
            if getattr(self, 'edit_mode', False):
                self.edit_mode = False
                self.edit_mode_var.set(False)
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
                self.output.bind("<ButtonRelease-1>", self._end_border_drag, add=True)
            if getattr(self, 'crop_mode', False):
                self.crop_mode = False
                self.crop_mode_var.set(False)
                self.crop_pending = False
                self.crop_box = None
                self._crop_interaction = None
                self._clear_crop_ui()
                self._set_crop_status(None)
                try:
                    self.output.unbind("<Double-Button-1>")
                except Exception:
                    pass
                self.output.bind("<Button-1>", self.highlight_region)
                self.output.unbind("<B1-Motion>")
                self.output.unbind("<ButtonRelease-1>")
                self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
            # also ensure region translate not conflicting
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.border_drag_active = False
            self.output.config(cursor="")
        # when turning border drag off, no need to force globals on

    def _update_ribbon_selection(self):
        """Refresh the ribbon labels with current selection state."""
        if not hasattr(self, 'ribbon_sel_name_var'):
            return
        if self.selected_zone_id is not None and self.selected_page == self.current_page:
            zname = self.zone_names.get(self.current_page, {}).get(self.selected_zone_id, f"Zone{self.selected_zone_id}")
            display = f"{zname} (#{self.selected_zone_id})"
            self.ribbon_sel_name_var.set(display)
            self.ribbon_selected_var.set(f"Selected: {zname}")
        else:
            self.ribbon_sel_name_var.set("None")
            self.ribbon_selected_var.set("No region selected")

        # Refresh the full list of labeled regions and sync selection highlight in list
        self._populate_region_list()

    def _populate_region_list(self):
        """Populate (or refresh) the listbox with all labeled regions for the current atlas page.
        Also tries to highlight the currently selected one in the list.
        """
        if not hasattr(self, 'region_listbox') or self.region_listbox is None:
            return
        self.region_listbox.delete(0, tk.END)
        self.region_list_id_map = {}
        page = self.current_page
        raw_names = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
        # Normalize keys to int (json manifests, snapshots etc use str keys). Prevents
        # 'uid not in names' false positives and ufunc 'less' in sorted when mixing with np.uint8 from mask.
        names = {int(k): v for k, v in raw_names.items()} if raw_names else {}
        if names:
            if page not in self.zone_names:
                self.zone_names[page] = {}
            self.zone_names[page].update(names)
        # Discover any zones present in the mask but missing from zone_names (orphans from
        # paint force, undo, or legacy data) and auto-register defaults so they appear in
        # the manager and can be autoselected on canvas clicks.
        if page in self.mask_images:
            try:
                m = np.array(self.mask_images[page])
                for zid in np.unique(m):
                    if zid > 0:
                        iz = int(zid)
                        if iz not in names:
                            self._ensure_zone_has_name(page, iz)
                names = self.zone_names.get(page, {}) if hasattr(self, 'zone_names') else {}
                names = {int(k): v for k, v in names.items()} if names else {}
            except Exception:
                pass
        # Force int keys for stable sort + display (defensive vs json str keys or np scalars)
        try:
            sorted_items = sorted((int(k), v) for k, v in names.items())
        except Exception:
            sorted_items = sorted(names.items())
        for i, (zid, zname) in enumerate(sorted_items):
            display = f"{zname} (ID={zid})"
            self.region_listbox.insert(tk.END, display)
            self.region_list_id_map[i] = zid

        # If we have a current selection for this page, highlight it in the list
        if (self.selected_zone_id is not None and
                getattr(self, 'selected_page', None) == page):
            for i, zid in list(self.region_list_id_map.items()):
                if zid == self.selected_zone_id:
                    self.region_listbox.selection_clear(0, tk.END)
                    self.region_listbox.selection_set(i)
                    self.region_listbox.see(i)
                    break
            else:
                self.region_listbox.selection_clear(0, tk.END)

    def _on_region_list_select(self, event=None):
        """User clicked a region in the Atlas Manager list -> make it the transform target."""
        if not hasattr(self, 'region_listbox') or self.region_listbox is None:
            return
        sel = self.region_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if not hasattr(self, 'region_list_id_map'):
            self.region_list_id_map = {}
        zid = self.region_list_id_map.get(idx)
        if zid is None:
            return
        self._select_zone_for_edit(zid)

    def _select_zone_for_edit(self, zid):
        """Select a zone id as the current Atlas Manager edit target and refresh visuals."""
        if zid is None:
            return
        zid = int(zid)
        # List selection: whole zone id (already side-specific after bilateral remap)
        self._set_zone_selection(self.current_page, zid, atlas_x=None, atlas_y=None)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        # Update visual: orange fill tint + yellow boundary (was black)
        if self.current_page in self.base_page_images:
            self._rebuild_page_overlays(self.current_page)
        self._refresh_selection_boundary_visual()
        self.show_page()
        self._update_ribbon_selection()  # will re-sync everything including list highlight

    def _on_region_list_right_click(self, event):
        """Right-click on a labeled region in the Atlas Manager list → context menu."""
        if not hasattr(self, 'region_listbox') or self.region_listbox is None:
            return
        try:
            idx = self.region_listbox.nearest(event.y)
        except Exception:
            return
        if idx is None or idx < 0 or idx >= self.region_listbox.size():
            return

        # Select the row under the cursor so Rename/Delete target is clear
        self.region_listbox.selection_clear(0, tk.END)
        self.region_listbox.selection_set(idx)
        self.region_listbox.activate(idx)
        self.region_listbox.focus_set()

        zid = getattr(self, 'region_list_id_map', {}).get(idx)
        if zid is None:
            return
        self._context_menu_zone_id = int(zid)
        # Also make it the active selection for editing (orange tint)
        try:
            self._select_zone_for_edit(zid)
        except Exception:
            pass

        menu = getattr(self, '_region_list_context_menu', None)
        if menu is None:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _context_rename_region(self):
        """Context menu: Rename the region that was right-clicked."""
        zid = getattr(self, '_context_menu_zone_id', None)
        if zid is None:
            # Fall back to current list selection
            sel = self.region_listbox.curselection() if hasattr(self, 'region_listbox') else ()
            if sel:
                zid = self.region_list_id_map.get(sel[0])
        if zid is None:
            messagebox.showinfo("Rename Region", "Right-click a labeled region in the list first.")
            return
        self.rename_labeled_region(int(zid))

    def _context_delete_region(self):
        """Context menu: Delete the region that was right-clicked."""
        zid = getattr(self, '_context_menu_zone_id', None)
        if zid is None:
            sel = self.region_listbox.curselection() if hasattr(self, 'region_listbox') else ()
            if sel:
                zid = self.region_list_id_map.get(sel[0])
        if zid is None:
            messagebox.showinfo("Delete Region", "Right-click a labeled region in the list first.")
            return
        self.delete_labeled_region(int(zid))

    def rename_labeled_region(self, zid=None):
        """Prompt for a new name for the given zone (or currently selected region)."""
        page = self.current_page
        if zid is None:
            zid = self.selected_zone_id
        if zid is None:
            messagebox.showinfo("Rename Region", "No region selected.")
            return False
        zid = int(zid)
        names = self.zone_names.get(page, {}) or {}
        # Normalize keys
        names_norm = {int(k): v for k, v in names.items()}
        if zid not in names_norm:
            messagebox.showwarning("Rename Region", f"Region ID {zid} is not in the labeled list.")
            return False

        current_name = names_norm.get(zid, f"Region {zid}")
        new_name = simpledialog.askstring(
            "Rename Region",
            f"New name for region (ID={zid}):",
            initialvalue=str(current_name),
            parent=self.master,
        )
        if new_name is None:
            return False  # cancelled
        new_name = str(new_name).strip()
        if not new_name:
            messagebox.showwarning("Rename Region", "Name cannot be empty.")
            return False
        if new_name == current_name:
            return True

        self.save_state()
        if page not in self.zone_names:
            self.zone_names[page] = {}
        # Keep int keys for consistency
        self.zone_names[page] = {int(k): v for k, v in self.zone_names[page].items()}
        self.zone_names[page][zid] = new_name
        logger.info(f"Renamed region {zid}: '{current_name}' → '{new_name}'")

        if self.selected_zone_id == zid:
            self.selected_page = page
        self._update_ribbon_selection()
        self.show_page()
        return True

    def delete_labeled_region(self, zid=None, confirm=True):
        """Remove a labeled region from zone names, mask, and painted outlines.

        Undoable via save_state. Returns True if deleted.
        """
        page = self.current_page
        if zid is None:
            zid = self.selected_zone_id
        if zid is None:
            messagebox.showinfo("Delete Region", "No region selected.")
            return False
        zid = int(zid)
        names = {int(k): v for k, v in (self.zone_names.get(page, {}) or {}).items()}
        current_name = names.get(zid, f"Region {zid}")

        if confirm:
            ok = messagebox.askyesno(
                "Delete Region",
                f"Delete labeled region '{current_name}' (ID={zid})?\n\n"
                "This removes its name and counting zone from the mask.\n"
                "You can Undo (Ctrl+Z) if needed.",
                parent=self.master,
            )
            if not ok:
                return False

        self.save_state()

        # Remove name
        if page in self.zone_names:
            self.zone_names[page] = {int(k): v for k, v in self.zone_names[page].items()}
            self.zone_names[page].pop(zid, None)

        # Clear zone pixels from the mask
        if page in self.mask_images and self.mask_images[page] is not None:
            try:
                m = np.array(self.mask_images[page])
                m[m == zid] = 0
                self.mask_images[page] = Image.fromarray(m.astype(np.uint8), mode='L')
            except Exception as e:
                logger.warning(f"Could not clear mask pixels for zone {zid}: {e}")

        # Remove painted outline for this zone and rebuild black paint layer
        if hasattr(self, 'painted_zone_outlines') and self.painted_zone_outlines:
            try:
                # Keys may be int or str
                self.painted_zone_outlines.pop(zid, None)
                self.painted_zone_outlines.pop(str(zid), None)
            except Exception:
                pass
            try:
                self._rebuild_paint_layer_from_data()
            except Exception as e:
                logger.debug(f"Paint layer rebuild after delete: {e}")

        # Clear selection if we deleted the selected zone
        if self.selected_zone_id is not None and int(self.selected_zone_id) == zid:
            self.selected_zone_id = None
            self.selected_page = None
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self.region_move_mode.set(False)
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None

        self._context_menu_zone_id = None
        clear_preprocess_cache()

        try:
            if page in self.base_page_images or page in self.mask_images:
                self._rebuild_page_overlays(page)
        except Exception:
            pass
        self.show_page()
        self._update_ribbon_selection()
        logger.info(f"Deleted labeled region '{current_name}' (ID={zid}) on page {page}")
        return True

    def _quick_rotate_selected(self, degrees):
        if not self._has_selected_region():
            return
        self.save_state()
        page = self.selected_page
        zid = self.selected_zone_id
        if self._apply_transform_to_region(page, zid, angle_deg=degrees, scale_x=1.0, scale_y=1.0):
            self._update_ribbon_selection()
            self.show_page()

    def _quick_scale_selected(self, factor):
        if not self._has_selected_region():
            return
        self.save_state()
        page = self.selected_page
        zid = self.selected_zone_id
        if self._apply_transform_to_region(page, zid, angle_deg=0.0, scale_x=factor, scale_y=factor):
            self._update_ribbon_selection()
            self.show_page()

    def _show_region_dialogs(self):
        self.show_rotate_selected_dialog()

    def _quick_rotate_global(self, degrees):
        """Apply small rotation to the entire current atlas page (global, affects base + all masks)."""
        self.save_state()
        page = self.current_page
        # Transform the clean base (the atlas artwork) and the zone mask
        if page in self.base_page_images:
            base = self.base_page_images[page]
            rotated_base = base.rotate(degrees, expand=True)
            self.base_page_images[page] = rotated_base
        if page in self.mask_images:
            mask_img = self.mask_images[page]
            rotated_mask = mask_img.rotate(degrees, expand=True, resample=Image.NEAREST)
            self.mask_images[page] = rotated_mask
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self.show_page()

    def _quick_scale_global(self, factor):
        """Apply small uniform scale to the entire current atlas page (global, affects base + all masks)."""
        self.save_state()
        page = self.current_page
        if page in self.base_page_images:
            base = self.base_page_images[page]
            new_size = (int(base.width * factor), int(base.height * factor))
            resized_base = base.resize(new_size, Image.BILINEAR)
            self.base_page_images[page] = resized_base
        if page in self.mask_images:
            mask_img = self.mask_images[page]
            new_size = (int(mask_img.width * factor), int(mask_img.height * factor))
            resized_mask = mask_img.resize(new_size, Image.NEAREST)
            self.mask_images[page] = resized_mask
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self.show_page()

    # --- Border drag (expand/shrink selected region by grabbing its edge) ---
    def _update_cursor_for_atlas_border(self, event):
        """Change cursor when hovering near the border of the selected region (if border mode on)."""
        if not getattr(self, 'border_mode_var', None) or not self.border_mode_var.get():
            self.output.config(cursor="")
            return
        if not self.selected_zone_id or self.selected_page != self.current_page:
            self.output.config(cursor="")
            return
        if self.crop_mode or self.edit_mode or getattr(self, 'current_state', None) == 'paint':
            self.output.config(cursor="")
            return
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)
        if self._is_near_selected_border(mx, my, screen_tol=8):
            self.output.config(cursor="sizing")  # or "cross" / "fleur"
        else:
            self.output.config(cursor="")

    def _try_start_border_drag(self, event):
        """Click near edge of a named region: ensure the zone is the active one (orange fill),
        illuminate the local edge in red (persistent, toggle by re-click), prepare for grab/pull of only that edge.
        """
        if not getattr(self, 'border_mode_var', None) or not self.border_mode_var.get():
            return False
        if self.crop_mode or self.edit_mode or getattr(self, 'current_state', None) == 'paint':
            return False
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)

        # Priority: if we already have a selected/illuminated edge (red line), and click is on/near it,
        # treat as intent to grab that specific edge (re-center or start drag). This makes "grab the red line" reliable.
        if self.selected_edge_full_contour is not None and self._is_click_on_selected_edge(mx, my, screen_tol=10):
            # re-center on this click pos for precise "click a position"
            self._pick_local_edge(mx, my)
            self.edge_grab_start_mouse = (mx, my)
            self.edge_drag_start_pos = (mx, my)
            self._edge_pending_deselect = True
            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = True
            return True

        # Otherwise, find which named zone the click landed on (for initial edge illumination)
        page = self.current_page
        if page not in self.mask_images:
            return False
        m = np.array(self.mask_images[page])
        if not (0 <= int(my) < m.shape[0] and 0 <= int(mx) < m.shape[1]):
            return False
        clicked_zid = int(m[int(my), int(mx)])
        if clicked_zid == 0:
            # Forgiving hit-test for edge grabs: if click landed just outside the mask (zid=0)
            # but is near the border of the *currently selected* zone, treat as edge-grab intent
            # for that zone. This makes illuminating/grabbing the edge (or the red line) more
            # reliable, even if the exact integer pixel sample is outside the raster region.
            if (getattr(self, 'selected_zone_id', None) and
                    getattr(self, 'selected_page', None) == page and
                    self._is_near_selected_border(mx, my, screen_tol=8)):
                clicked_zid = self.selected_zone_id
            else:
                return False

        # Any positive label under cursor means the area is already claimed by a region.
        # Ensure it has a name entry (auto default if orphan) so it participates in the
        # labeled regions manager and future clicks autoselect instead of naming.
        self._ensure_zone_has_name(page, clicked_zid)

        # Make sure this zone is the active selected (orange fill + yellow boundary).
        # Re-set when click is on a different connected component of the same zid (e.g. L vs R mirror).
        need_reselect = (
            self.selected_zone_id != clicked_zid
            or getattr(self, 'selected_page', None) != page
        )
        if not need_reselect and getattr(self, 'selected_zone_component', None) is not None:
            try:
                comp = self.selected_zone_component
                iy, ix = int(my), int(mx)
                if (
                    isinstance(comp, np.ndarray)
                    and 0 <= iy < comp.shape[0]
                    and 0 <= ix < comp.shape[1]
                    and not bool(comp[iy, ix])
                ):
                    need_reselect = True  # same structure ID, other hemisphere blob
            except Exception:
                pass
        if need_reselect:
            self._clear_edge_highlight()
            self.edge_grab_active = False
            self.border_drag_active = False
            self.active_edge = None
            self.current_edited_contour = None
            self.selected_edge_full_contour = None
            self._set_zone_selection(page, clicked_zid, atlas_x=mx, atlas_y=my)
            self._rebuild_page_overlays(page)
            self._refresh_selection_boundary_visual()
            self.show_page()  # orange fill + yellow boundary visible immediately
            self._update_ribbon_selection()

        # Is the click on the border of the (now active) zone?
        if not self._is_near_selected_border(mx, my, screen_tol=8):
            # Interior click on the selected zone: if Move Selected Region mode, start translate
            if self.region_move_mode.get() and self.selected_zone_id == clicked_zid:
                self._start_region_translate(mx, my)
                return True
            # Claimed region (interior click on mask>0) -> autoselect in labeled regions manager
            # (we ensured a name above). Prevents the name dialog for already-labeled areas.
            return True  # always prevent falling through to name prompt for claimed zones


        # Edge click on the active zone: toggle deselect or select new edge for editing
        if self.selected_edge_full_contour is not None and self._is_click_on_selected_edge(mx, my, screen_tol=10):
            # Click on the currently illuminated edge at a specific position:
            # re-center the editable segment on *this* click point (so "click a position" chooses where to pull from),
            # update the red to the new local, then prepare for drag or deselect.
            self._pick_local_edge(mx, my)  # re-computes around the click pos, redraws red centered here
            self.edge_grab_start_mouse = (mx, my)
            self.edge_drag_start_pos = (mx, my)
            self._edge_pending_deselect = True
            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = True  # so motion handler proceeds to edge logic
            return True

        # Select/illuminate this local edge (red, persistent) and prepare for drag
        self._pick_local_edge(mx, my)
        self.edge_grab_start_mouse = (mx, my)
        self.edge_drag_start_pos = (mx, my)
        self.edge_grab_active = True
        self.border_drag_active = True  # activate the combined motion handler
        self._edge_pending_deselect = False
        self.save_state()
        return True

    def _pick_local_edge(self, mx, my):
        """Compute the local boundary segment around the click for the selected zone and draw it in red on the canvas."""
        self._clear_edge_highlight()
        self.active_edge = None
        self.current_edited_contour = None

        page = self.current_page
        zid = self.selected_zone_id
        if page not in self.mask_images:
            return
        m = np.array(self.mask_images[page])
        binr = (m == zid).astype(float)
        contours = measure.find_contours(binr, 0.5)
        if not contours:
            return
        # Main (longest) contour
        contour = max(contours, key=len)
        self.original_full_contour_for_edit = contour.copy()
        self.selected_edge_full_contour = contour.copy()

        # Closest point on contour
        dists = np.hypot(contour[:, 1] - mx, contour[:, 0] - my)
        cidx = int(np.argmin(dists))
        self.edge_closest_idx = cidx
        self.selected_edge_closest = cidx
        self.edge_window = 30
        n = len(contour)

        # Local window around the click (may wrap)
        start = (cidx - self.edge_window) % n
        end = (cidx + self.edge_window) % n
        if start < end:
            edge_pts = contour[start:end + 1].copy()
            self.edge_start_idx = start
            self.edge_end_idx = end
            self.selected_edge_start_idx = start
            self.selected_edge_end_idx = end
        else:
            edge_pts = np.vstack((contour[start:], contour[:end + 1])).copy()
            self.edge_start_idx = start
            self.edge_end_idx = end
            self.selected_edge_start_idx = start
            self.selected_edge_end_idx = end

        self.active_edge = edge_pts
        self._draw_edge_highlight(edge_pts)

    def _is_click_on_selected_edge(self, mx, my, screen_tol=10):
        """Return True if the click (in model coords) is close to the currently selected (illuminated) edge.
        screen_tol is the hit radius in screen pixels; converted to model using current view_scale.
        """
        if self.selected_edge_full_contour is None:
            return False
        # Prefer the active local segment if available
        if self.active_edge is not None and len(self.active_edge) > 0:
            edge = self.active_edge
        else:
            start = getattr(self, 'selected_edge_start_idx', 0)
            end = getattr(self, 'selected_edge_end_idx', 0)
            full = self.selected_edge_full_contour
            if start < end:
                edge = full[start:end+1]
            else:
                edge = np.vstack((full[start:], full[:end+1]))
        if len(edge) == 0:
            return False
        dists = np.hypot(edge[:,1] - mx, edge[:,0] - my)
        scale = max(getattr(self, 'view_scale', 1.0), 0.01)
        model_tol = screen_tol / scale
        return np.min(dists) < model_tol

    def _moved_enough_for_drag(self, event, threshold=5):
        """Return True if mouse has moved enough from the drag start to treat as a drag (not a click)."""
        if not hasattr(self, 'edge_drag_start_pos'):
            return False
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)
        dx = mx - self.edge_drag_start_pos[0]
        dy = my - self.edge_drag_start_pos[1]
        return math.hypot(dx, dy) > threshold

    def _draw_edge_highlight(self, edge_pts=None):
        self._clear_edge_highlight()
        if edge_pts is None:
            edge_pts = getattr(self, 'active_edge', None)
        if edge_pts is None or len(edge_pts) < 2:
            return
        scale = getattr(self, 'view_scale', 1.0)
        ox = float(getattr(self, 'img_x', 0)) * scale
        oy = float(getattr(self, 'img_y', 0)) * scale
        flat = []
        for y, x in edge_pts:
            sx = x * scale + ox
            sy = y * scale + oy
            flat.append(sx)
            flat.append(sy)
        if len(flat) > 2:
            try:
                item = self.output.create_line(flat, fill='red', width=4, capstyle=tk.ROUND, joinstyle=tk.ROUND, tag='edge_highlight')
                self.edge_highlight_item = item
                try:
                    self.output.tag_raise(item)
                except Exception:
                    pass
            except Exception:
                pass

    def _update_edge_highlight(self, edge_pts=None):
        if edge_pts is not None:
            self.active_edge = edge_pts
        if not hasattr(self, 'edge_highlight_item') or self.edge_highlight_item is None:
            self._draw_edge_highlight(edge_pts)
            return
        if edge_pts is None:
            edge_pts = getattr(self, 'active_edge', None)
        if edge_pts is None or len(edge_pts) < 2:
            return
        scale = getattr(self, 'view_scale', 1.0)
        ox = float(getattr(self, 'img_x', 0)) * scale
        oy = float(getattr(self, 'img_y', 0)) * scale
        flat = []
        for y, x in edge_pts:
            sx = x * scale + ox
            sy = y * scale + oy
            flat.append(sx)
            flat.append(sy)
        try:
            self.output.coords(self.edge_highlight_item, *flat)
        except Exception:
            self._draw_edge_highlight(edge_pts)

    def _clear_edge_highlight(self):
        if hasattr(self, 'edge_highlight_item') and self.edge_highlight_item:
            try:
                self.output.delete(self.edge_highlight_item)
            except Exception:
                pass
        self.edge_highlight_item = None
        try:
            self.output.delete('edge_highlight')
        except Exception:
            pass

    def _start_region_translate(self, mx, my):
        """Begin translating the selected region (only its mask pixels move; atlas base stays fixed)."""
        page = self.current_page
        zid = self.selected_zone_id
        if page not in self.mask_images or zid is None:
            return
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.region_translate_active = True
        self.region_translate_zid = zid
        self.region_translate_start_mx = mx
        self.region_translate_start_my = my
        self.region_translate_original_mask = self.mask_images[page].copy()
        self.border_drag_active = True  # so the motion handler runs the translate logic
        self.save_state()
        self.output.config(cursor="fleur")
        # Optional: brief hint
        # messagebox.showinfo("Region Translate", "Dragging will move only the selected region's area.", parent=self.master)  # avoid spam

    def _apply_region_translation(self, dx, dy):
        """Shift all pixels of the current translate zid by the (rounded) dx,dy from the snapshot."""
        page = self.current_page
        zid = self.region_translate_zid
        if page not in self.mask_images or zid is None or self.region_translate_original_mask is None:
            return
        mask = np.array(self.region_translate_original_mask)
        region = (mask == zid)
        if not np.any(region):
            return
        ys, xs = np.where(region)
        new_ys = ys + int(round(dy))
        new_xs = xs + int(round(dx))
        mask[region] = 0
        h, w = mask.shape
        valid = (new_ys >= 0) & (new_ys < h) & (new_xs >= 0) & (new_xs < w)
        mask[new_ys[valid], new_xs[valid]] = zid
        self.mask_images[page] = Image.fromarray(mask.astype(np.uint8), mode='L')
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)

    def _rasterize_contour_to_zone(self, contour, zid):
        """Replace the zone zid in the current page mask by filling the (modified) contour as a polygon."""
        if contour is None or len(contour) < 3:
            return
        page = self.current_page
        orig = np.array(self.mask_images[page])
        h, w = orig.shape
        fill_img = Image.new('L', (w, h), 0)
        dr = ImageDraw.Draw(fill_img)
        # contour is [[y, x], ...] -> PIL wants [(x, y), ...]
        pts = [(int(round(x)), int(round(y))) for y, x in contour]
        if len(pts) >= 3:
            dr.polygon(pts, fill=zid)
        new_zone = np.array(fill_img)
        current = orig.copy()
        current[current == zid] = 0
        current[new_zone == zid] = zid
        self.mask_images[page] = Image.fromarray(current.astype(np.uint8), mode='L')
        clear_preprocess_cache()
        self._rebuild_page_overlays(page)

    def _refresh_atlas_layer(self):
        """Lightweight refresh of only the 'atlas' tagged image item.
        Used for live preview during edge drag so the yellow region shape updates as you pull the red edge.
        Must be called after _rasterize + _rebuild_page_overlays.
        """
        self.output.delete('atlas')
        page = self.current_page
        if page not in self.page_images:
            return
        img = self.page_images[page]
        scale = getattr(self, 'view_scale', 1.0)
        atlas_display = img
        if scale != 1.0:
            aw = max(1, int(img.width * scale))
            ah = max(1, int(img.height * scale))
            atlas_display = img.resize((aw, ah), Image.BILINEAR)
        self.photo = ImageTk.PhotoImage(atlas_display)
        display_img_x = float(getattr(self, 'img_x', 0)) * float(scale)
        display_img_y = float(getattr(self, 'img_y', 0)) * float(scale)
        self.output.create_image(display_img_x, display_img_y,
                               image=self.photo,
                               anchor='nw',
                               tag='atlas')
        # Ensure the red edge highlight (if any) stays on top of the refreshed atlas image
        try:
            self.output.tag_raise('edge_highlight')
        except Exception:
            pass

    def _is_near_selected_border(self, model_x, model_y, screen_tol=8):
        """Return True if (model_x, model_y) is inside or near the border of the selected zone.
        screen_tol is desired hit radius in screen pixels (converted using view_scale).
        """
        page = self.current_page
        zid = self.selected_zone_id
        if page not in self.mask_images:
            return False
        m = np.array(self.mask_images[page])
        if not (0 <= int(model_y) < m.shape[0] and 0 <= int(model_x) < m.shape[1]):
            return False
        region = (m == zid)
        if not region.any():
            return False
        scale = max(getattr(self, 'view_scale', 1.0), 0.01)
        model_tol = screen_tol / scale
        # Use distance to the complement (outside the region) to detect border vicinity
        # Points inside near the edge have small distance to outside.
        try:
            from scipy.ndimage import distance_transform_edt
            # dist to nearest outside pixel
            outside_dist = distance_transform_edt(region)
            # Also consider if the point itself is on the region
            if region[int(model_y), int(model_x)]:
                d = outside_dist[int(model_y), int(model_x)]
                return d <= model_tol
            else:
                # if just outside, also allow if close
                # invert
                inside_dist = distance_transform_edt(~region)
                d = inside_dist[int(model_y), int(model_x)]
                return d <= model_tol
        except Exception:
            # Fallback: simple bbox check + on region
            ys, xs = np.where(region)
            if len(ys) == 0:
                return False
            miny, maxy, minx, maxx = ys.min(), ys.max(), xs.min(), xs.max()
            return (miny - model_tol <= model_y <= maxy + model_tol) and (minx - model_tol <= model_x <= maxx + model_tol) and region[int(model_y), int(model_x)]

    def _handle_border_drag_motion(self, event):
        if not getattr(self, 'border_drag_active', False):
            return
        if not self.border_mode_var.get() and not getattr(self, 'region_translate_active', False):
            return
        cx = self.output.canvasx(event.x)
        cy = self.output.canvasy(event.y)
        mx, my = self._canvas_to_zone_model(cx, cy)

        # --- New precise edge editing: live update only the red edge line ---
        if getattr(self, '_edge_pending_deselect', False) or getattr(self, 'edge_grab_active', False):
            if not getattr(self, 'edge_grab_active', False):
                # First motion after mousedown on selected edge: decide if it's a drag
                if self._moved_enough_for_drag(event):
                    self.edge_grab_active = True
                    self.border_drag_active = True
                    self._edge_pending_deselect = False
            if getattr(self, 'edge_grab_active', False):
                if hasattr(self, 'original_full_contour_for_edit') and self.original_full_contour_for_edit is not None:
                    full = self.original_full_contour_for_edit.copy()
                    n = len(full)
                    cidx = getattr(self, 'edge_closest_idx', 0)
                    wnd = getattr(self, 'edge_window', 30)
                    dx = mx - self.edge_grab_start_mouse[0]
                    dy = my - self.edge_grab_start_mouse[1]
                    for j in range(-wnd, wnd + 1):
                        ii = (cidx + j) % n
                        ww = max(0.0, 1.0 - abs(j) / float(wnd + 1))
                        full[ii, 0] += dy * ww  # y
                        full[ii, 1] += dx * ww  # x
                    self.current_edited_contour = full
                    self.selected_edge_full_contour = full  # keep in sync for commit
                    # extract local for red highlight
                    if self.edge_start_idx < self.edge_end_idx:
                        local = full[self.edge_start_idx : self.edge_end_idx + 1]
                    else:
                        local = np.vstack((full[self.edge_start_idx:], full[:self.edge_end_idx + 1]))
                    self.active_edge = local
                    self._update_edge_highlight(local)

                    # Live update the region shape (the yellow/orange fill) as you pull the red edge.
                    # This fulfills "click a position to expand it or shrink it, and the shape of the region should adjust accordingly".
                    if self.selected_edge_full_contour is not None:
                        self._rasterize_contour_to_zone(self.selected_edge_full_contour, self.selected_zone_id)
                        self._refresh_atlas_layer()
            return

        # Region translate (move only the selected zone's pixels in the mask; atlas image/lines stay fixed)
        if getattr(self, 'region_translate_active', False):
            mx, my = self._canvas_to_zone_model(self.output.canvasx(event.x), self.output.canvasy(event.y))
            dx = mx - self.region_translate_start_mx
            dy = my - self.region_translate_start_my
            if self.region_translate_original_mask is not None:
                # restore snapshot then apply total offset (live)
                self.mask_images[self.current_page] = self.region_translate_original_mask.copy()
                self._apply_region_translation(dx, dy)
                self._refresh_atlas_layer()
            return

        # Fallback / legacy one-sided (kept for compatibility but not primary now)
        start_mx, start_my = getattr(self, 'border_drag_start_mouse', (0, 0))
        dx = mx - start_mx
        dy = my - start_my
        ux, uy = getattr(self, 'border_drag_unit', (0.0, 1.0))
        pull_amount = dx * ux + dy * uy
        page = self.current_page
        zid = getattr(self, 'border_drag_zone', None)
        if page in self.mask_images and getattr(self, 'border_drag_original_mask', None) is not None and zid is not None:
            self.mask_images[page] = self.border_drag_original_mask.copy()
            self._apply_border_pull(pull_amount)
            self.show_page()
            if hasattr(self, '_update_ribbon_selection'):
                self._update_ribbon_selection()

    def _end_border_drag(self, event):
        if getattr(self, '_edge_pending_deselect', False):
            # It was a short click on the already illuminated edge → toggle deselect (highlight disappears)
            self._clear_edge_highlight()
            self.selected_edge_full_contour = None
            self.active_edge = None
            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = False
            self._edge_pending_deselect = False
            self.current_edited_contour = None
            self.original_full_contour_for_edit = None
            return

        if getattr(self, 'edge_grab_active', False):
            did_edit = False
            if getattr(self, 'current_edited_contour', None) is not None and self.selected_edge_full_contour is not None:
                self._rasterize_contour_to_zone(self.selected_edge_full_contour, self.selected_zone_id)
                did_edit = True

            self.edge_grab_active = False
            self.border_drag_active = False
            self.border_drag_active = False
            self._edge_pending_deselect = False

            if hasattr(self, '_update_ribbon_selection'):
                self._update_ribbon_selection()

            if did_edit:
                # Only call show_page (which deletes all) when we actually changed the mask.
                # Then re-draw red after.
                self.show_page()
                if self.selected_edge_full_contour is not None:
                    start = getattr(self, 'selected_edge_start_idx', 0)
                    end = getattr(self, 'selected_edge_end_idx', 0)
                    if start < end:
                        local = self.selected_edge_full_contour[start:end+1]
                    else:
                        local = np.vstack((self.selected_edge_full_contour[start:], self.selected_edge_full_contour[:end+1]))
                    self.active_edge = local
                    self._draw_edge_highlight(local)
            # For pure select click (no edit), the red was drawn on mousedown and we avoid show_page
            # so it doesn't disappear on release.

            self.output.config(cursor="")
            return

        if getattr(self, 'region_translate_active', False):
            self.region_translate_active = False
            self.region_translate_original_mask = None
            self.region_translate_zid = None
            self.region_translate_start_mx = 0
            self.region_translate_start_my = 0
            self.border_drag_active = False
            self.output.config(cursor="")
            if hasattr(self, '_update_ribbon_selection'):
                self._update_ribbon_selection()
            self.show_page()
            return

        if not getattr(self, 'border_drag_active', False):
            return
        self.border_drag_active = False
        self.border_drag_original_mask = None
        self.border_drag_start_mouse = (0.0, 0.0)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        if hasattr(self, '_update_ribbon_selection'):
            self._update_ribbon_selection()
        self.show_page()
        self.output.config(cursor="")

    def _commit_painted_border_refit(self, event=None):
        """Commit painted border refit on Enter (crop apply is handled by ``_on_return_key``).

        Commits the current mask shape (yellow expansion) by refitting the black
        drawn boundary (updating painted_zone_outlines from the live mask contour).
        """
        # Crop is handled in _on_return_key so Checkbutton focus cannot cancel it
        if getattr(self, "crop_pending", False) and getattr(self, "crop_box", None):
            self._apply_pending_crop()
            return "break"

        zid = getattr(self, 'selected_zone_id', None)
        if not zid or zid not in getattr(self, 'painted_zone_outlines', {}):
            return
        page = self.current_page
        if page not in self.mask_images:
            return

        # Snapshot before committing the visual refit so this step is undoable independently
        self.save_state()
        m = np.array(self.mask_images[page])
        binr = (m == zid).astype(float)
        contours = measure.find_contours(binr, 0.5)
        if not contours:
            return
        new_contour = max(contours, key=len)
        new_points = [(int(round(x)), int(round(y))) for y, x in new_contour]
        self.painted_zone_outlines[zid]['points'] = new_points
        try:
            self._rebuild_paint_layer_from_data()
        except Exception:
            pass
        self.show_page()
        # Clean up any lingering edge highlight/red segment after commit
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        if hasattr(self, '_update_ribbon_selection'):
            self._update_ribbon_selection()

    def highlight_region(self, event):
        logger.debug(f"Highlighting region at ({event.x}, {event.y})")
        self.save_state()

        # Intercept for border drag resize if a region is selected and border mode is active
        if self._try_start_border_drag(event):
            return

        if not self.atlas_filetype or self.crop_mode or self.edit_mode:
            logger.debug("Highlight region aborted: atlas_filetype=%s, crop_mode=%s, edit_mode=%s", 
                      self.atlas_filetype, self.crop_mode, self.edit_mode)
            return

        canvas_x = self.output.canvasx(event.x)
        canvas_y = self.output.canvasy(event.y)
        mx, my = self._canvas_to_atlas(canvas_x, canvas_y)
        x, y = int(mx), int(my)  # convert to atlas model (native) coordinates, respecting view_scale

        img = self.load_page_image()
        if x < 0 or y < 0 or x >= img.width or y >= img.height:
            logger.debug("Click outside image boundaries")
            return

        barrier_img = preprocess_for_highlighting(self.current_page, img, self.atlas_filetype)
        try:
            seed_value = barrier_img.getpixel((x, y))
            logger.debug(f"Seed value at click point: {seed_value}")
            if seed_value != 255:
                logger.debug("Clicked on a barrier")
                return  # clicked a barrier
        except Exception as e:
            logger.error(f"Error getting pixel value: {e}")
            return

        # If clicking inside an already-labeled region (mask zid>0), auto-select it in the
        # labeled regions manager instead of re-prompting for a name that may already exist.
        # The helper ensures a default name if the mask label was an orphan (so it appears
        # in the manager list and satisfies "autoselect from the labeled regions manager").
        if self.current_page in self.mask_images:
            m = np.array(self.mask_images[self.current_page])
            if 0 <= y < m.shape[0] and 0 <= x < m.shape[1]:
                zid = int(m[y, x])
                if zid == 0:
                    # Forgiving: click just outside (zid=0 at exact pixel) but near the border
                    # of the currently selected zone -> autoselect it instead of showing the
                    # name dialog. This prevents unwanted "name region" prompts when trying to
                    # grab the edge of an already-labeled/selected region.
                    if (getattr(self, 'selected_zone_id', None) and
                            getattr(self, 'selected_page', None) == self.current_page and
                            self._is_near_selected_border(mx, my, screen_tol=8)):
                        zid = self.selected_zone_id
                if zid > 0:
                    self._ensure_zone_has_name(self.current_page, zid)
                    if self.selected_zone_id != zid or getattr(self, 'selected_page', None) != self.current_page:
                        self.selected_zone_id = zid
                        self.selected_page = self.current_page
                        self._clear_edge_highlight()
                        self.edge_grab_active = False
                        self.active_edge = None
                        self.current_edited_contour = None
                        self.selected_edge_full_contour = None
                        self._edge_pending_deselect = False
                        self.region_move_mode.set(False)
                        self.region_translate_active = False
                        self.region_translate_original_mask = None
                        self.region_translate_zid = None
                        self._rebuild_page_overlays(self.current_page)
                        self._refresh_selection_boundary_visual()
                        self.show_page()
                        self._update_ribbon_selection()
                    return

        name = simpledialog.askstring("Region Name", "Enter a name for this region:")
        if name == None:
            return

        self.zone_counters[self.current_page] += 1
        zone_id = self.zone_counters[self.current_page]

        name = name.strip() 
        self.zone_names[self.current_page][zone_id] = name

        barrier_copy = barrier_img.copy()
        ImageDraw.floodfill(barrier_copy, (x, y), zone_id, thresh=0)
        filled = np.array(barrier_copy)
        mask = (filled == zone_id)

        mask_img = self.mask_images[self.current_page]
        mask_array = np.array(mask_img)
        mask_array[mask] = zone_id
        self.mask_images[self.current_page] = Image.fromarray(mask_array)

        # New zone created -> clear any previous edge edit state
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.active_edge = None
        self.current_edited_contour = None

        # Rebuild display from clean base + current zones (including the newly named one).
        # This also handles any previously baked yellows from old code paths.
        self._rebuild_page_overlays(self.current_page)
        self.show_page()
        self._update_ribbon_selection()

    def _toggle_zone_labels_counts(self):
        """Show or hide the zone labels & counts table for the current file."""
        if self.show_zone_labels_var.get():
            self._open_zone_counts_window()
        else:
            self._close_zone_counts_window()
        self.show_page()

    def _toggle_zone_labels_intensities(self):
        """Show or hide region labels + mean intensities (Axons and Nets)."""
        if self.show_zone_intensity_labels_var.get():
            df, note = self._get_zone_intensities_dataframe()
            if df is None or df.empty:
                self.show_zone_intensity_labels_var.set(False)
                messagebox.showinfo(
                    "No Regions",
                    "No regions are defined for this image.\n\n"
                    "Load an atlas or paint named regions first.",
                )
                return
            self.last_intensity_df = df
            self._open_zone_intensity_window()
        else:
            self._close_zone_intensity_window()
        self.show_page()

    def _pil_to_gray_float(self, bg):
        """Convert a PIL image to float64 grayscale luminance (no display brightness)."""
        bg_arr = np.asarray(bg)
        if bg_arr.ndim == 3:
            return (
                0.2989 * bg_arr[..., 0].astype(np.float64)
                + 0.5870 * bg_arr[..., 1].astype(np.float64)
                + 0.1140 * bg_arr[..., 2].astype(np.float64)
            )
        return bg_arr.astype(np.float64).squeeze()

    def _zone_mask_registered_to_background(self, mask_img, bg_h, bg_w):
        """Place atlas/zone mask into background image coordinates.

        Returns (mask_on_bg uint8, original_mask_w, original_mask_h).
        """
        m = np.array(mask_img)
        if m.ndim > 2:
            m = m.squeeze()
        mh, mw = m.shape[:2]
        if abs(mw - bg_w) < 5 and abs(mh - bg_h) < 5:
            if (mw, mh) != (bg_w, bg_h):
                m = np.array(
                    Image.fromarray(m.astype(np.uint8), mode="L").resize(
                        (bg_w, bg_h), Image.NEAREST
                    )
                )
            return m.astype(np.uint8), mw, mh

        ox = int(round(float(getattr(self, "img_x", 0) or 0)))
        oy = int(round(float(getattr(self, "img_y", 0) or 0)))
        mask_on_bg = np.zeros((bg_h, bg_w), dtype=np.uint8)
        x0 = max(0, ox)
        y0 = max(0, oy)
        x1 = min(bg_w, ox + mw)
        y1 = min(bg_h, oy + mh)
        sx0 = x0 - ox
        sy0 = y0 - oy
        sx1 = sx0 + (x1 - x0)
        sy1 = sy0 + (y1 - y0)
        if x1 > x0 and y1 > y0:
            mask_on_bg[y0:y1, x0:x1] = m[sy0:sy1, sx0:sx1]
        return mask_on_bg, mw, mh

    def _resolve_norm_factor(self, zid, name, normalization_lookup):
        """Look up counterstain normalization factor by Zone_ID then Zone name."""
        if not normalization_lookup:
            return np.nan
        by_id = normalization_lookup.get("by_id") or {}
        by_name = normalization_lookup.get("by_name") or {}
        if int(zid) in by_id:
            return float(by_id[int(zid)])
        if str(zid) in by_id:
            try:
                return float(by_id[str(zid)])
            except Exception:
                pass
        if name in by_name:
            return float(by_name[name])
        # case-insensitive name match
        name_l = str(name).strip().lower()
        for k, v in by_name.items():
            if str(k).strip().lower() == name_l:
                return float(v)
        return np.nan

    def _compute_region_intensities_df(
        self,
        bg_percentile=None,
        normalization_lookup=None,
        mode="signal",
    ):
        """Compute per-region intensity stats on the current TIFF + zone mask.

        Parameters
        ----------
        bg_percentile : float or None
            If set (0–100), subtract the Xth percentile of intensities *within each
            region* from that region's pixels before computing stats
            (background subtraction).
        normalization_lookup : dict or None
            ``{"by_id": {zid: factor}, "by_name": {name: factor}}`` from a
            Counterstain Normalization Measurement export. Final mean is divided
            by the factor (axon/PNN ÷ counterstain).
        mode : str
            ``"signal"`` (default axon/PNN measure) or ``"counterstain_norm"``
            (writes Normalization_Factor = raw mean intensity).

        Returns (df, meta_dict) or (None, error_message).
        """
        page = self.current_page
        if page not in self.mask_images or self.mask_images[page] is None:
            return None, "No region mask is available."

        bg = None
        if getattr(self, "original_background", None) is not None:
            bg = self.original_background
        elif getattr(self, "background_image", None) is not None:
            bg = self.background_image
        if bg is None:
            return None, "No image is loaded."

        mask_img = self.mask_images[page]
        zone_names = dict(self.zone_names.get(page, {}) or {})

        gray = self._pil_to_gray_float(bg)
        bg_h, bg_w = gray.shape[:2]
        mask_on_bg, mw, mh = self._zone_mask_registered_to_background(mask_img, bg_h, bg_w)

        zids = set()
        for z in zone_names.keys():
            try:
                zids.add(int(z))
            except Exception:
                pass
        for z in np.unique(mask_on_bg):
            if int(z) > 0:
                zids.add(int(z))
                zone_names.setdefault(int(z), f"Zone {int(z)}")

        if not zids:
            return None, "No labeled regions found in the current mask."

        use_bg = bg_percentile is not None
        if use_bg:
            try:
                bg_percentile = float(bg_percentile)
            except Exception:
                return None, "Background percentile must be a number."
            if not (0.0 <= bg_percentile <= 100.0):
                return None, "Background percentile must be between 0 and 100."

        use_norm = bool(normalization_lookup) and mode != "counterstain_norm"
        rows = []
        for zid in sorted(zids):
            reg = mask_on_bg == int(zid)
            area = int(reg.sum())
            name = zone_names.get(zid, zone_names.get(int(zid), f"Zone {zid}"))
            empty = {
                "Zone_ID": int(zid),
                "Zone": name,
                "Region_Area": 0,
                # Explicit pre / post correction (always present in export)
                "Pre_Correction_Mean": np.nan,
                "Pre_Correction_Median": np.nan,
                "Post_Correction_Mean": np.nan,
                "Post_Correction_Median": np.nan,
                # Aliases used elsewhere (labels, legacy loaders)
                "Mean_Intensity_Raw": np.nan,
                "Median_Intensity_Raw": np.nan,
                "Mean_Intensity": np.nan,
                "Median_Intensity": np.nan,
                "Background_Level": np.nan,
                "Mean_Intensity_BGsub": np.nan,
                "Median_Intensity_BGsub": np.nan,
                "Normalization_Factor": np.nan,
                "Mean_Intensity_Normalized": np.nan,
                "Median_Intensity_Normalized": np.nan,
                "Sum_Intensity": np.nan,
                "Std_Intensity": np.nan,
                "Min_Intensity": np.nan,
                "Max_Intensity": np.nan,
            }
            if area <= 0:
                rows.append(empty)
                continue

            vals = gray[reg].astype(np.float64)
            raw_mean = float(np.mean(vals))
            raw_median = float(np.median(vals))
            bg_level = np.nan
            work = vals
            if use_bg:
                bg_level = float(np.percentile(vals, bg_percentile))
                work = vals - bg_level

            mean_bg = float(np.mean(work))
            median_bg = float(np.median(work))
            sum_bg = float(np.sum(work))
            std_bg = float(np.std(work))
            min_bg = float(np.min(work))
            max_bg = float(np.max(work))

            factor = np.nan
            mean_post = mean_bg
            median_post = median_bg
            sum_out = sum_bg
            if mode == "counterstain_norm":
                # Factor used later to normalize axon/PNN: divide by counterstain mean
                factor = raw_mean if raw_mean > 0 else np.nan
                mean_post = raw_mean
                median_post = raw_median
            elif use_norm:
                factor = self._resolve_norm_factor(zid, name, normalization_lookup)
                if factor is not None and not (isinstance(factor, float) and np.isnan(factor)):
                    try:
                        f = float(factor)
                        factor = f
                        if f > 1e-12:
                            mean_post = mean_bg / f
                            median_post = median_bg / f
                            sum_out = float(np.sum(work / f))
                        else:
                            mean_post = np.nan
                            median_post = np.nan
                            sum_out = np.nan
                    except Exception:
                        mean_post = np.nan
                        median_post = np.nan
                        sum_out = np.nan
                else:
                    factor = np.nan
                    mean_post = np.nan
                    median_post = np.nan
                    sum_out = np.nan
            # else: no norm — post is after optional BG only (mean_bg / median_bg)

            # If neither correction was requested, post == pre
            if mode != "counterstain_norm" and not use_bg and not use_norm:
                mean_post = raw_mean
                median_post = raw_median
                sum_out = float(np.sum(vals))
                std_bg = float(np.std(vals))
                min_bg = float(np.min(vals))
                max_bg = float(np.max(vals))

            rows.append(
                {
                    "Zone_ID": int(zid),
                    "Zone": name,
                    "Region_Area": area,
                    # Pre-correction = raw regional intensities (no BG / no norm)
                    "Pre_Correction_Mean": raw_mean,
                    "Pre_Correction_Median": raw_median,
                    # Post-correction = after optional BG subtract and/or counterstain norm
                    "Post_Correction_Mean": mean_post,
                    "Post_Correction_Median": median_post,
                    # Aliases
                    "Mean_Intensity_Raw": raw_mean,
                    "Median_Intensity_Raw": raw_median,
                    "Mean_Intensity": mean_post,  # labels / primary = post
                    "Median_Intensity": median_post,
                    "Background_Level": bg_level if use_bg else np.nan,
                    "Mean_Intensity_BGsub": mean_bg if use_bg else np.nan,
                    "Median_Intensity_BGsub": median_bg if use_bg else np.nan,
                    "Normalization_Factor": factor if (use_norm or mode == "counterstain_norm") else np.nan,
                    "Mean_Intensity_Normalized": mean_post if use_norm else np.nan,
                    "Median_Intensity_Normalized": median_post if use_norm else np.nan,
                    "Sum_Intensity": sum_out,
                    "Std_Intensity": std_bg,
                    "Min_Intensity": min_bg,
                    "Max_Intensity": max_bg,
                }
            )

        df = pd.DataFrame(rows)
        meta = {
            "bg_w": bg_w,
            "bg_h": bg_h,
            "mw": mw,
            "mh": mh,
            "page": page,
            "n_regions": len(rows),
            "mode": mode,
            "background_subtraction": bool(use_bg),
            "bg_percentile": float(bg_percentile) if use_bg else None,
            "counterstain_normalization": bool(use_norm),
            "normalization_file": (
                (normalization_lookup or {}).get("source_path") if use_norm else None
            ),
        }
        return df, meta

    def _get_zone_intensities_dataframe(self):
        """Return (DataFrame, source_note) for intensity labels / table."""
        df, meta_or_err = self._compute_region_intensities_df()
        if df is None:
            return None, str(meta_or_err or "")
        self.last_intensity_df = df
        return df.copy(), "Measured on current image (grayscale, no display brightness)"

    def _format_intensity_export_df(self, df):
        """Column order for intensity / counterstain exports.

        Pre_Correction_* = raw (before BG subtract / counterstain norm).
        Post_Correction_* = after all selected corrections (or equal to pre if none).
        """
        if df is None or df.empty:
            return df
        # Ensure pre/post columns exist even for older in-memory frames
        if "Pre_Correction_Mean" not in df.columns and "Mean_Intensity_Raw" in df.columns:
            df = df.copy()
            df["Pre_Correction_Mean"] = df["Mean_Intensity_Raw"]
            df["Pre_Correction_Median"] = df.get(
                "Median_Intensity_Raw", df.get("Median_Intensity")
            )
        if "Post_Correction_Mean" not in df.columns and "Mean_Intensity" in df.columns:
            df = df.copy() if "Pre_Correction_Mean" in df.columns else df
            if "Post_Correction_Mean" not in df.columns:
                df = df.copy()
            df["Post_Correction_Mean"] = df["Mean_Intensity"]
            df["Post_Correction_Median"] = df.get("Median_Intensity", np.nan)

        preferred = [
            "Zone",
            "Zone_ID",
            "Region_Area",
            "Pre_Correction_Mean",
            "Pre_Correction_Median",
            "Post_Correction_Mean",
            "Post_Correction_Median",
            "Background_Level",
            "Normalization_Factor",
            "Mean_Intensity_BGsub",
            "Median_Intensity_BGsub",
            "Mean_Intensity_Normalized",
            "Median_Intensity_Normalized",
            # Legacy aliases (same values as pre/post)
            "Mean_Intensity_Raw",
            "Median_Intensity_Raw",
            "Mean_Intensity",
            "Median_Intensity",
            "Sum_Intensity",
            "Std_Intensity",
            "Min_Intensity",
            "Max_Intensity",
        ]
        cols = [c for c in preferred if c in df.columns]
        cols += [c for c in df.columns if c not in cols]
        out = df[cols].copy()
        for c in out.columns:
            if c in ("Zone",):
                continue
            try:
                if c == "Zone_ID":
                    out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int64")
                else:
                    out[c] = pd.to_numeric(out[c], errors="coerce")
            except Exception:
                pass
        return out

    def _build_intensity_parameter_sheet(self, meta):
        """Detection-Parameters-style sheet for intensity exports (mirrors Count Cells)."""
        meta = meta if isinstance(meta, dict) else {}
        rows = [
            {"Category": "Source", "Parameter": "Image", "Value": str(self.tiff_filename or "")},
            {
                "Category": "Source",
                "Parameter": "TIFF_Path",
                "Value": str(getattr(self, "current_tiff_path", "") or ""),
            },
            {
                "Category": "Source",
                "Parameter": "Image_Size",
                "Value": f"{meta.get('bg_w', '?')}x{meta.get('bg_h', '?')}",
            },
            {
                "Category": "Mask",
                "Parameter": "Mask_Size",
                "Value": f"{meta.get('mw', '?')}x{meta.get('mh', '?')}",
            },
            {
                "Category": "Mask",
                "Parameter": "Atlas_Offset_XY",
                "Value": f"{getattr(self, 'img_x', 0)},{getattr(self, 'img_y', 0)}",
            },
            {
                "Category": "Mask",
                "Parameter": "Atlas_Page",
                "Value": str(meta.get("page", self.current_page)),
            },
            {
                "Category": "Mask",
                "Parameter": "Atlas_Filetype",
                "Value": str(getattr(self, "atlas_filetype", "") or ""),
            },
            {
                "Category": "Measurement",
                "Parameter": "Mode",
                "Value": str(meta.get("mode", "signal")),
            },
            {
                "Category": "Measurement",
                "Parameter": "N_Regions",
                "Value": str(meta.get("n_regions", "")),
            },
            {
                "Category": "Measurement",
                "Parameter": "Intensity_Source",
                "Value": "original_background grayscale luminance (no display brightness)",
            },
            {
                "Category": "Measurement",
                "Parameter": "Luminance_Weights",
                "Value": "0.2989 R + 0.5870 G + 0.1140 B",
            },
            {
                "Category": "Background Subtraction",
                "Parameter": "Enabled",
                "Value": str(bool(meta.get("background_subtraction"))),
            },
            {
                "Category": "Background Subtraction",
                "Parameter": "Percentile",
                "Value": str(meta.get("bg_percentile") if meta.get("bg_percentile") is not None else ""),
            },
            {
                "Category": "Background Subtraction",
                "Parameter": "Method",
                "Value": (
                    "Per-region: subtract Xth percentile of pixel intensities within that region"
                    if meta.get("background_subtraction")
                    else ""
                ),
            },
            {
                "Category": "Counterstain Normalization",
                "Parameter": "Enabled",
                "Value": str(bool(meta.get("counterstain_normalization"))),
            },
            {
                "Category": "Counterstain Normalization",
                "Parameter": "Normalization_File",
                "Value": str(meta.get("normalization_file") or ""),
            },
            {
                "Category": "Counterstain Normalization",
                "Parameter": "Method",
                "Value": (
                    "Corrected_Mean = (Mean - BG_level) / Normalization_Factor; "
                    "Factor = counterstain regional mean intensity"
                    if meta.get("counterstain_normalization")
                    else (
                        "Normalization_Factor = counterstain regional mean intensity"
                        if meta.get("mode") == "counterstain_norm"
                        else ""
                    )
                ),
            },
            {
                "Category": "Measurement",
                "Parameter": "Generated_At",
                "Value": datetime.now().isoformat(timespec="seconds"),
            },
        ]
        try:
            page = self.current_page
            for zid, name in sorted(
                (self.zone_names.get(page, {}) or {}).items(),
                key=lambda kv: int(kv[0]) if str(kv[0]).lstrip("-").isdigit() else str(kv[0]),
            ):
                rows.append(
                    {
                        "Category": "Zone Names",
                        "Parameter": f"Zone_{zid}",
                        "Value": str(name),
                    }
                )
        except Exception:
            pass
        return pd.DataFrame(rows)

    def _ask_intensity_correction_options(self):
        """Modal dialog: optional background subtraction + counterstain normalization.

        Returns dict
          {use_bg, bg_percentile, use_norm, norm_path}
        or None if cancelled.
        """
        prefs = getattr(self, "_intensity_corr_prefs", {}) or {}
        win = Toplevel(self.master)
        win.title("Intensity Correction Options")
        win.transient(self.master)
        win.grab_set()
        win.resizable(False, False)
        try:
            self._register_transparent_window(win)
        except Exception:
            pass

        result = {"ok": False}

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(
            frm,
            text="Axon / PNN intensity measurement",
            font=("Helvetica", 10, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(
            frm,
            text=(
                "Optionally correct each region for local background and/or divide by\n"
                "counterstain intensity measured with the same atlas (.catlas)."
            ),
            justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))

        use_bg_var = tk.BooleanVar(value=bool(prefs.get("use_bg", False)))
        use_norm_var = tk.BooleanVar(value=bool(prefs.get("use_norm", False)))
        pct_var = tk.StringVar(value=str(prefs.get("bg_percentile", 10.0)))
        path_var = tk.StringVar(value=str(prefs.get("norm_path", "") or ""))

        # --- Background ---
        bg_frame = ttk.LabelFrame(frm, text="Background subtraction", padding=8)
        bg_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)

        ttk.Checkbutton(
            bg_frame,
            text="Subtract Xth-percentile intensity within each region",
            variable=use_bg_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(bg_frame, text="Percentile (X):").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        pct_entry = ttk.Entry(bg_frame, textvariable=pct_var, width=8)
        pct_entry.grid(row=1, column=1, sticky="w", padx=4, pady=(6, 0))
        ttk.Label(
            bg_frame,
            text="(typical: 5–20; 0 = min, 50 = median)",
            foreground="gray",
        ).grid(row=1, column=2, sticky="w", pady=(6, 0))

        ttk.Label(
            bg_frame,
            text="For each region: background = percentile of pixel values in that region;\n"
            "stats are computed after (pixel − background).",
            font=("Helvetica", 8),
            foreground="gray",
            justify=tk.LEFT,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # --- Normalization ---
        norm_frame = ttk.LabelFrame(frm, text="Counterstain normalization", padding=8)
        norm_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Checkbutton(
            norm_frame,
            text="Normalize by counterstain regional intensity",
            variable=use_norm_var,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Label(
            norm_frame,
            text="Normalization file (from Counterstain Normalization Measurement):",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 2))

        path_entry = ttk.Entry(norm_frame, textvariable=path_var, width=52)
        path_entry.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 4))

        def browse_norm():
            initial = None
            cur = path_var.get().strip()
            if cur and os.path.isfile(cur):
                initial = os.path.dirname(cur)
            else:
                initial = self._preferred_open_dir(feature="intensities")
            p = fd.askopenfilename(
                title="Select counterstain normalization file",
                initialdir=initial,
                filetypes=[
                    ("Excel / CSV", "*.xlsx *.xls *.csv"),
                    ("Excel", "*.xlsx *.xls"),
                    ("CSV", "*.csv"),
                    ("All files", "*.*"),
                ],
                parent=win,
            )
            if p:
                path_var.set(p)

        ttk.Button(norm_frame, text="Browse…", command=browse_norm, width=10).grid(
            row=2, column=2, sticky="e"
        )

        ttk.Label(
            norm_frame,
            text="Corrected = (signal − background) ÷ Normalization_Factor\n"
            "Factor column comes from the counterstain measurement on the same atlas.",
            font=("Helvetica", 8),
            foreground="gray",
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # --- Buttons ---
        btn_row = ttk.Frame(frm)
        btn_row.grid(row=4, column=0, columnspan=3, sticky="e", pady=(12, 0))

        def on_cancel():
            result["ok"] = False
            win.destroy()

        def on_ok():
            use_bg = bool(use_bg_var.get())
            use_norm = bool(use_norm_var.get())
            pct = 10.0
            if use_bg:
                try:
                    pct = float(pct_var.get().strip())
                except Exception:
                    messagebox.showerror(
                        "Invalid percentile",
                        "Enter a numeric percentile between 0 and 100.",
                        parent=win,
                    )
                    return
                if not (0.0 <= pct <= 100.0):
                    messagebox.showerror(
                        "Invalid percentile",
                        "Percentile must be between 0 and 100.",
                        parent=win,
                    )
                    return
            path = path_var.get().strip()
            if use_norm:
                if not path:
                    messagebox.showerror(
                        "Normalization file required",
                        "Select the Excel/CSV file produced by\n"
                        "Axons and Nets → Counterstain Normalization Measurement…",
                        parent=win,
                    )
                    return
                if not os.path.isfile(path):
                    messagebox.showerror(
                        "File not found",
                        f"Normalization file does not exist:\n{path}",
                        parent=win,
                    )
                    return
            result["ok"] = True
            result["use_bg"] = use_bg
            result["bg_percentile"] = pct
            result["use_norm"] = use_norm
            result["norm_path"] = path if use_norm else ""
            win.destroy()

        ttk.Button(btn_row, text="Cancel", command=on_cancel, width=10).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btn_row, text="Measure", command=on_ok, width=10).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", on_cancel)
        # Center over main window
        try:
            win.update_idletasks()
            x = self.master.winfo_rootx() + 80
            y = self.master.winfo_rooty() + 80
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self.master.wait_window(win)

        if not result.get("ok"):
            return None
        opts = {
            "use_bg": result["use_bg"],
            "bg_percentile": result["bg_percentile"],
            "use_norm": result["use_norm"],
            "norm_path": result["norm_path"],
        }
        self._intensity_corr_prefs = dict(opts)
        return opts

    def _load_counterstain_normalization_file(self, path):
        """Load Normalization_Factor per region from a counterstain measurement export.

        Returns lookup dict:
          {"by_id": {int: float}, "by_name": {str: float}, "source_path": path, "df": DataFrame}
        or (None, error_message).
        """
        if not path or not os.path.isfile(path):
            return None, "Normalization file not found."

        try:
            low = path.lower()
            if low.endswith(".csv"):
                df = pd.read_csv(path)
            else:
                # Prefer dedicated sheet name, then fall back
                df = None
                last_err = None
                for sheet in (
                    "Counterstain Normalization",
                    "Region Intensities",
                    0,
                ):
                    try:
                        df = pd.read_excel(path, sheet_name=sheet)
                        break
                    except Exception as e:
                        last_err = e
                        df = None
                if df is None:
                    return None, f"Could not read Excel sheet: {last_err}"
        except Exception as e:
            return None, f"Failed to read normalization file:\n{e}"

        if df is None or df.empty:
            return None, "Normalization file is empty."

        # Normalize column names (strip, lower for matching)
        colmap = {c: str(c).strip() for c in df.columns}
        df = df.rename(columns=colmap)
        cols_l = {str(c).strip().lower(): c for c in df.columns}

        def col(*names):
            for n in names:
                if n.lower() in cols_l:
                    return cols_l[n.lower()]
            return None

        c_factor = col(
            "Normalization_Factor",
            "normalization_factor",
            "Norm_Factor",
            "Factor",
        )
        c_mean = col("Mean_Intensity", "Mean_Intensity_Raw", "mean_intensity")
        c_id = col("Zone_ID", "zone_id", "ZoneId", "ID")
        c_name = col("Zone", "zone", "Region", "Name")

        if c_factor is None and c_mean is None:
            return None, (
                "Normalization file must contain a Normalization_Factor column\n"
                "(or Mean_Intensity from Counterstain Normalization Measurement)."
            )
        if c_id is None and c_name is None:
            return None, "Normalization file must contain Zone_ID and/or Zone columns."

        by_id = {}
        by_name = {}
        for _, row in df.iterrows():
            factor = None
            if c_factor is not None:
                try:
                    factor = float(row[c_factor])
                except Exception:
                    factor = None
            if (factor is None or (isinstance(factor, float) and np.isnan(factor))) and c_mean is not None:
                try:
                    factor = float(row[c_mean])
                except Exception:
                    factor = None
            if factor is None or (isinstance(factor, float) and (np.isnan(factor) or factor <= 0)):
                continue
            if c_id is not None:
                try:
                    zid = int(float(row[c_id]))
                    by_id[zid] = float(factor)
                except Exception:
                    pass
            if c_name is not None:
                nm = row[c_name]
                if pd.notna(nm) and str(nm).strip():
                    by_name[str(nm).strip()] = float(factor)

        if not by_id and not by_name:
            return None, "No valid positive normalization factors found in the file."

        return {
            "by_id": by_id,
            "by_name": by_name,
            "source_path": path,
            "df": df,
        }, None

    def _export_region_intensity_workbook(
        self, df, meta, out_dir, base_name, *, kind="intensities"
    ):
        """Write intensity results as multi-sheet .xlsx under output/intensities/.

        kind:
          - ``intensities`` → ``{base}_intensities.xlsx`` sheet Region Intensities
          - ``counterstain_norm`` → ``{base}_counterstain_norm.xlsx`` sheet Counterstain Normalization

        Returns (path, format) where format is 'xlsx' or 'csv', or (None, None) on failure.
        """
        if df is None or df.empty or not out_dir or not base_name:
            return None, None

        export_df = self._format_intensity_export_df(df)
        if kind == "counterstain_norm":
            # Lean export focused on factors for later axon normalization
            keep = [
                c
                for c in (
                    "Zone",
                    "Zone_ID",
                    "Region_Area",
                    "Mean_Intensity",
                    "Median_Intensity",
                    "Normalization_Factor",
                    "Std_Intensity",
                    "Min_Intensity",
                    "Max_Intensity",
                )
                if c in export_df.columns
            ]
            if keep:
                export_df = export_df[keep]
            xlsx_path = os.path.join(out_dir, f"{base_name}_counterstain_norm.xlsx")
            data_sheet = "Counterstain Normalization"
            csv_path = os.path.join(out_dir, f"{base_name}_counterstain_norm.csv")
            legacy_path = None
        else:
            xlsx_path = os.path.join(out_dir, f"{base_name}_intensities.xlsx")
            data_sheet = "Region Intensities"
            csv_path = os.path.join(out_dir, f"{base_name}_intensities.csv")
            legacy_path = os.path.join(out_dir, f"{base_name}_region_intensity.xlsx")

        param_df = self._build_intensity_parameter_sheet(meta)

        excel_errors = []
        for engine in ("openpyxl", "xlsxwriter"):
            try:
                with pd.ExcelWriter(xlsx_path, engine=engine) as writer:
                    export_df.to_excel(writer, sheet_name=data_sheet, index=False)
                    param_df.to_excel(writer, sheet_name="Measurement Parameters", index=False)
                if os.path.isfile(xlsx_path) and os.path.getsize(xlsx_path) > 0:
                    if legacy_path:
                        try:
                            import shutil
                            shutil.copy2(xlsx_path, legacy_path)
                        except Exception:
                            pass
                    logger.info(f"Intensity Excel saved: {xlsx_path} (engine={engine})")
                    return xlsx_path, "xlsx"
            except Exception as e:
                excel_errors.append(f"{engine}: {e}")
                logger.warning(f"Intensity Excel engine {engine} failed: {e}")

        try:
            export_df.to_csv(csv_path, index=False)
            try:
                param_df.to_csv(
                    os.path.splitext(csv_path)[0] + "_parameters.csv",
                    index=False,
                )
            except Exception:
                pass
            logger.info(f"Intensity CSV fallback: {csv_path}")
            if excel_errors:
                messagebox.showwarning(
                    "Excel Export Failed",
                    "Could not save as Excel "
                    "(openpyxl/xlsxwriter missing or failed).\n\n"
                    f"Fell back to CSV:\n{csv_path}\n\n"
                    "To enable .xlsx output, run:\n"
                    "pip install openpyxl\n\n"
                    + "\n".join(excel_errors[:3]),
                )
            return csv_path, "csv"
        except Exception as e:
            logger.error(f"Intensity CSV fallback failed: {e}", exc_info=True)
            return None, None

    def _intensity_output_basename_and_dir(self, feature="intensities"):
        """Resolve (base_name, tiff_dir, out_dir) for intensity / PNN exports.

        ``feature`` selects the output subfolder (default ``intensities``;
        use ``pnn`` for perineuronal tables).
        """
        base_name = self.tiff_filename
        tiff_dir = self.tiff_dir or self.current_tiff_directory
        if not base_name and getattr(self, "current_tiff_path", None):
            base_name = os.path.splitext(os.path.basename(self.current_tiff_path))[0]
            if not tiff_dir:
                tiff_dir = os.path.dirname(self.current_tiff_path)
        if not base_name:
            base_name = "regions"
        out_dir = self._get_output_directory(tiff_dir, feature=feature) if tiff_dir else None
        return base_name, tiff_dir, out_dir

    def measure_counterstain_normalization(self):
        """Measure per-region counterstain intensity → Normalization_Factor table.

        Run this on the counterstain channel (e.g. DAPI) with the same .catlas /
        atlas regions used for axon/PNN. Output is consumed later by
        Measure Region Intensities → Counterstain normalization.
        """
        try:
            df, meta_or_err = self._compute_region_intensities_df(
                bg_percentile=None,
                normalization_lookup=None,
                mode="counterstain_norm",
            )
            if df is None:
                msg = str(meta_or_err or "Could not measure counterstain intensities.")
                messagebox.showwarning(
                    "Counterstain Normalization",
                    f"{msg}\n\nLoad the counterstain TIFF, load the same atlas/"
                    ".catlas, then try again.",
                )
                return

            meta = meta_or_err if isinstance(meta_or_err, dict) else {}
            n_rows = int(meta.get("n_regions", len(df)) or len(df))
            base_name, tiff_dir, out_dir = self._intensity_output_basename_and_dir()
            saved_paths = []
            out_path = None

            if out_dir:
                out_path, fmt = self._export_region_intensity_workbook(
                    df, meta, out_dir, base_name, kind="counterstain_norm"
                )
                if out_path:
                    saved_paths.append(
                        f"Counterstain norm ({'Excel' if fmt == 'xlsx' else 'CSV'}): {out_path}"
                    )
            else:
                path = fd.asksaveasfilename(
                    title="Save counterstain normalization table",
                    defaultextension=".xlsx",
                    filetypes=[
                        ("Excel", "*.xlsx"),
                        ("CSV", "*.csv"),
                        ("All files", "*.*"),
                    ],
                    initialfile=f"{base_name}_counterstain_norm.xlsx",
                )
                if not path:
                    return
                export_df = self._format_intensity_export_df(df)
                keep = [
                    c
                    for c in (
                        "Zone",
                        "Zone_ID",
                        "Region_Area",
                        "Mean_Intensity",
                        "Median_Intensity",
                        "Normalization_Factor",
                    )
                    if c in export_df.columns
                ]
                if keep:
                    export_df = export_df[keep]
                if path.lower().endswith(".csv"):
                    export_df.to_csv(path, index=False)
                    out_path = path
                else:
                    if not path.lower().endswith(".xlsx"):
                        path = path + ".xlsx"
                    param_df = self._build_intensity_parameter_sheet(meta)
                    ok = False
                    for engine in ("openpyxl", "xlsxwriter"):
                        try:
                            with pd.ExcelWriter(path, engine=engine) as writer:
                                export_df.to_excel(
                                    writer,
                                    sheet_name="Counterstain Normalization",
                                    index=False,
                                )
                                param_df.to_excel(
                                    writer,
                                    sheet_name="Measurement Parameters",
                                    index=False,
                                )
                            ok = True
                            break
                        except Exception as e:
                            logger.warning(f"Counterstain Excel ({engine}): {e}")
                    if ok:
                        out_path = path
                    else:
                        csv_path = os.path.splitext(path)[0] + ".csv"
                        export_df.to_csv(csv_path, index=False)
                        out_path = csv_path
                if out_path:
                    saved_paths.append(f"Counterstain norm: {out_path}")

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            if saved_paths:
                dest = out_dir or (os.path.dirname(out_path) if out_path else "")
                messagebox.showinfo(
                    "Counterstain Normalization Saved",
                    f"Measured {n_rows} region(s) on the counterstain channel.\n\n"
                    f"Normalization_Factor = regional mean intensity "
                    f"(use as divisor for axon/PNN).\n\n"
                    + (f"Saved to:\n{dest}\n\n" if dest else "")
                    + "\n".join(saved_paths)
                    + "\n\nNext: open the axon/PNN channel (same atlas), then\n"
                    "Axons and Nets → Measure Region Intensities… and enable\n"
                    "counterstain normalization with this file.",
                )
                logger.info(f"Counterstain normalization export: {saved_paths}")
            else:
                messagebox.showwarning(
                    "Export Failed",
                    f"Measured {n_rows} region(s), but could not write the file.\n"
                    "Ensure the folder is writable and openpyxl is installed.",
                )
        except Exception as e:
            logger.error(f"measure_counterstain_normalization failed: {e}", exc_info=True)
            messagebox.showerror(
                "Counterstain Normalization",
                f"Failed to measure counterstain normalization:\n{e}",
            )

    def measure_region_intensities(self):
        """Measure mean/median intensity and area of each Atlas Manager region.

        Prompts for optional background subtraction (Xth percentile within each
        region) and counterstain normalization (file from Counterstain
        Normalization Measurement). Writes multi-sheet Excel under output/intensities/.
        """
        try:
            # Confirm atlas/image exist before showing options dialog
            page = self.current_page
            if page not in self.mask_images or self.mask_images[page] is None:
                messagebox.showwarning(
                    "Axons and Nets",
                    "No region mask is available.\n\n"
                    "Load an atlas or .catlas (or paint named regions), then try again.",
                )
                return
            if (
                getattr(self, "original_background", None) is None
                and getattr(self, "background_image", None) is None
            ):
                messagebox.showwarning(
                    "Axons and Nets",
                    "No image is loaded.\n\nOpen a TIFF from the File Browser first.",
                )
                return

            opts = self._ask_intensity_correction_options()
            if opts is None:
                return  # cancelled

            bg_percentile = opts["bg_percentile"] if opts.get("use_bg") else None
            normalization_lookup = None
            if opts.get("use_norm"):
                normalization_lookup, err = self._load_counterstain_normalization_file(
                    opts.get("norm_path")
                )
                if normalization_lookup is None:
                    messagebox.showerror(
                        "Normalization file",
                        err or "Could not load counterstain normalization file.",
                    )
                    return

            df, meta_or_err = self._compute_region_intensities_df(
                bg_percentile=bg_percentile,
                normalization_lookup=normalization_lookup,
                mode="signal",
            )
            if df is None:
                msg = str(meta_or_err or "Could not measure intensities.")
                messagebox.showwarning("Axons and Nets", msg)
                return

            meta = meta_or_err if isinstance(meta_or_err, dict) else {}
            self.last_intensity_df = df
            n_rows = int(meta.get("n_regions", len(df)) or len(df))

            base_name, tiff_dir, out_dir = self._intensity_output_basename_and_dir()
            saved_paths = []
            intensities_path = None

            if out_dir:
                intensities_path, fmt = self._export_region_intensity_workbook(
                    df, meta, out_dir, base_name, kind="intensities"
                )
                if intensities_path:
                    label = "Intensities (Excel)" if fmt == "xlsx" else "Intensities (CSV)"
                    saved_paths.append(f"{label}: {intensities_path}")
            else:
                path = fd.asksaveasfilename(
                    title="Save region intensity table",
                    defaultextension=".xlsx",
                    filetypes=[
                        ("Excel", "*.xlsx"),
                        ("CSV", "*.csv"),
                        ("All files", "*.*"),
                    ],
                    initialfile=f"{base_name}_intensities.xlsx",
                )
                if not path:
                    messagebox.showinfo(
                        "Measure Complete",
                        f"Measured {n_rows} region(s), but no output folder was available "
                        "and save was cancelled.\n\nOpen a TIFF from the File Browser so "
                        "results can be written to <folder>/output/intensities/.",
                    )
                    if self.show_zone_intensity_labels_var.get():
                        self._open_zone_intensity_window()
                        self.show_page()
                    return
                if path.lower().endswith(".csv"):
                    self._format_intensity_export_df(df).to_csv(path, index=False)
                    intensities_path = path
                    saved_paths.append(f"Intensities (CSV): {path}")
                else:
                    if not path.lower().endswith(".xlsx"):
                        path = path + ".xlsx"
                    export_df = self._format_intensity_export_df(df)
                    param_df = self._build_intensity_parameter_sheet(meta)
                    excel_ok = False
                    for engine in ("openpyxl", "xlsxwriter"):
                        try:
                            with pd.ExcelWriter(path, engine=engine) as writer:
                                export_df.to_excel(
                                    writer, sheet_name="Region Intensities", index=False
                                )
                                param_df.to_excel(
                                    writer, sheet_name="Measurement Parameters", index=False
                                )
                            excel_ok = True
                            break
                        except Exception as e:
                            logger.warning(f"Manual intensity Excel ({engine}): {e}")
                    if excel_ok:
                        intensities_path = path
                        saved_paths.append(f"Intensities (Excel): {path}")
                    else:
                        csv_path = os.path.splitext(path)[0] + ".csv"
                        export_df.to_csv(csv_path, index=False)
                        intensities_path = csv_path
                        saved_paths.append(f"Intensities (CSV): {csv_path}")

            if self.show_zone_intensity_labels_var.get():
                self._open_zone_intensity_window()
                self.show_page()

            if hasattr(self, "tiff_tree") and self.current_tiff_directory:
                try:
                    self.master.after(300, self.refresh_tiff_file_list)
                except Exception:
                    pass

            if saved_paths:
                dest = out_dir or (
                    os.path.dirname(intensities_path) if intensities_path else ""
                )
                corr_bits = []
                if meta.get("background_subtraction"):
                    corr_bits.append(
                        f"BG subtract: {meta.get('bg_percentile')}th percentile / region"
                    )
                if meta.get("counterstain_normalization"):
                    corr_bits.append(
                        f"Normalized by: {meta.get('normalization_file') or 'counterstain file'}"
                    )
                if not corr_bits:
                    corr_bits.append("No BG subtract / no counterstain normalization")
                summary = (
                    f"Measured {n_rows} region(s).\n\n"
                    + "\n".join(corr_bits)
                    + "\n\nResults saved"
                    + (f" to output folder:\n{dest}\n\n" if dest else ":\n\n")
                    + "\n".join(saved_paths)
                    + "\n\nSheets: Region Intensities | Measurement Parameters\n"
                    "Key columns: Pre_Correction_Mean/Median, "
                    "Post_Correction_Mean/Median, Background_Level, Normalization_Factor."
                )
                messagebox.showinfo("Region Intensities Saved", summary)
                logger.info(f"Region intensities export complete: {saved_paths}")
            else:
                messagebox.showwarning(
                    "Export Failed",
                    f"Measured {n_rows} region(s), but could not write an Excel/CSV file.\n\n"
                    "Check that the image folder is writable and that openpyxl is installed:\n"
                    "pip install openpyxl",
                )
        except Exception as e:
            logger.error(f"measure_region_intensities failed: {e}", exc_info=True)
            messagebox.showerror("Axons and Nets", f"Failed to measure intensities:\n{e}")

    def _get_zone_counts_dataframe(self):
        """Return (DataFrame, source_note) for the current file's zone counts."""
        if self.last_df is not None and not self.last_df.empty:
            if 'Zone' in self.last_df.columns and 'Cell_Count' in self.last_df.columns:
                return self.last_df.copy(), "Current session counts"

        saved_df = self._load_saved_counts_df()
        if saved_df is not None and not saved_df.empty:
            return saved_df, "Loaded from saved results file"

        page_zones = self.zone_names.get(self.current_page, {})
        if not page_zones and self.current_page in self.mask_images:
            try:
                mask_arr = np.array(self.mask_images[self.current_page])
                for zid in np.unique(mask_arr):
                    if int(zid) > 0:
                        page_zones.setdefault(int(zid), f"Zone {int(zid)}")
            except Exception:
                pass

        if page_zones:
            rows = []
            for zid in sorted(page_zones.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
                area = '—'
                try:
                    page = self.current_page
                    if page in self.mask_images and self.mask_images[page] is not None:
                        m = np.array(self.mask_images[page])
                        area = int(np.sum(m == int(zid)))
                except Exception:
                    pass
                rows.append({'Zone': page_zones[zid], 'Cell_Count': '—', 'Region_Area': area})
            return pd.DataFrame(rows), "Zones defined — run Count Cells to populate counts"

        return None, ""

    def _load_saved_counts_df(self):
        """Load zone counts from a saved CSV/XLSX for the current TIFF, if present.

        Prefers <image_dir>/output/counts/ (and other feature dirs), then legacy files beside the TIFF.
        """
        if not self.tiff_dir or not self.tiff_filename:
            return None

        base_name = self.tiff_filename
        name_candidates = [
            (f"{base_name}.xlsx", 'xlsx'),
            (f"{base_name}.csv", 'csv'),
            (f"{base_name}_counted.xlsx", 'xlsx'),
            (f"{base_name}_counted.csv", 'csv'),
            (f"{base_name} - counted.xlsx", 'xlsx'),
            (f"{base_name} - counted.csv", 'csv'),
            (f"{base_name}_cells.xlsx", 'xlsx'),
            (f"{base_name}_cells.csv", 'csv'),
            (f"{base_name}_counts.xlsx", 'xlsx'),
            (f"{base_name}_counts.csv", 'csv'),
        ]
        candidates = []
        for search_dir in self._artifact_search_dirs(self.tiff_dir):
            for name, fmt in name_candidates:
                candidates.append((os.path.join(search_dir, name), fmt))

        for path, fmt in candidates:
            if not os.path.exists(path):
                continue
            try:
                if fmt == 'xlsx':
                    df = pd.read_excel(path, sheet_name='Cell Counts')
                else:
                    df = pd.read_csv(path)
                if 'Zone' in df.columns and 'Cell_Count' in df.columns:
                    cols = ['Zone', 'Cell_Count']
                    if 'Region_Area' in df.columns:
                        cols.append('Region_Area')
                    return df[cols].copy()
            except Exception as e:
                logger.debug(f"Could not load counts from {path}: {e}")
                continue
        return None

    def _open_zone_counts_window(self):
        """Open (or refresh) a tabular view of zone names and cell counts."""
        df, source_note = self._get_zone_counts_dataframe()
        if df is None or df.empty:
            self.show_zone_labels_var.set(False)
            messagebox.showinfo(
                "No Zones",
                "No zones are defined for this file.\n\n"
                "Define regions on the atlas or with the Paint tool, then run Count Cells."
            )
            return

        if self.zone_counts_window is not None and self.zone_counts_window.winfo_exists():
            self._populate_zone_counts_tree(df, source_note)
            self.zone_counts_window.lift()
            return

        win = Toplevel(self.master)
        self.zone_counts_window = win
        title_name = self.tiff_filename or "current file"
        win.title(f"Zone Labels & Counts — {title_name}")
        win.geometry("480x360")
        win.transient(self.master)

        header = ttk.Frame(win, padding=(8, 8, 8, 4))
        header.pack(fill='x')
        ttk.Label(
            header,
            text=f"Zone labels and cell counts for {title_name}",
            font=("Helvetica", 10, "bold"),
        ).pack(anchor='w')
        self.zone_counts_source_label = ttk.Label(header, text=source_note, foreground='gray')
        self.zone_counts_source_label.pack(anchor='w')

        table_frame = ttk.Frame(win, padding=(8, 4, 8, 8))
        table_frame.pack(fill='both', expand=True)

        columns = ("zone", "count", "area")
        self.zone_counts_tree = ttk.Treeview(
            table_frame, columns=columns, show='headings', selectmode='browse'
        )
        self.zone_counts_tree.heading("zone", text="Zone")
        self.zone_counts_tree.heading("count", text="Cell Count")
        self.zone_counts_tree.heading("area", text="Region Area (px)")
        self.zone_counts_tree.column("zone", width=240, anchor='w')
        self.zone_counts_tree.column("count", width=100, anchor='center')
        self.zone_counts_tree.column("area", width=120, anchor='center')

        yscroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.zone_counts_tree.yview)
        self.zone_counts_tree.configure(yscrollcommand=yscroll.set)
        self.zone_counts_tree.pack(side='left', fill='both', expand=True)
        yscroll.pack(side='right', fill='y')

        footer = ttk.Frame(win, padding=(8, 0, 8, 8))
        footer.pack(fill='x')
        self.zone_counts_total_label = ttk.Label(footer, text="")
        self.zone_counts_total_label.pack(anchor='w')

        def on_close():
            self.show_zone_labels_var.set(False)
            self.zone_counts_window = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._populate_zone_counts_tree(df, source_note)

    def _populate_zone_counts_tree(self, df, source_note=""):
        """Fill the zone counts Treeview from a DataFrame."""
        if not hasattr(self, 'zone_counts_tree') or self.zone_counts_tree is None:
            return
        if not self.zone_counts_tree.winfo_exists():
            return

        for item in self.zone_counts_tree.get_children():
            self.zone_counts_tree.delete(item)

        total = 0
        total_area = 0
        has_numeric_counts = False
        has_numeric_area = False
        for _, row in df.iterrows():
            zone_name = str(row.get('Zone', ''))
            count_val = row.get('Cell_Count', '')
            if pd.isna(count_val):
                count_display = '—'
            elif isinstance(count_val, (int, float, np.integer, np.floating)):
                count_display = str(int(count_val))
                total += int(count_val)
                has_numeric_counts = True
            else:
                count_display = str(count_val)
                if str(count_val).isdigit():
                    total += int(count_val)
                    has_numeric_counts = True

            area_val = row.get('Region_Area', '')
            if pd.isna(area_val) or area_val == '' or area_val is None:
                area_display = '—'
            elif isinstance(area_val, (int, float, np.integer, np.floating)):
                area_display = str(int(area_val))
                total_area += int(area_val)
                has_numeric_area = True
            else:
                area_display = str(area_val)
                if str(area_val).isdigit():
                    total_area += int(area_val)
                    has_numeric_area = True

            self.zone_counts_tree.insert("", "end", values=(zone_name, count_display, area_display))

        if hasattr(self, 'zone_counts_source_label') and self.zone_counts_source_label.winfo_exists():
            self.zone_counts_source_label.config(text=source_note)

        if hasattr(self, 'zone_counts_total_label') and self.zone_counts_total_label.winfo_exists():
            parts = []
            if has_numeric_counts:
                parts.append(f"Total cells: {total}")
            if has_numeric_area:
                parts.append(f"Total region area: {total_area} px")
            self.zone_counts_total_label.config(text="  |  ".join(parts) if parts else "")

    def _close_zone_counts_window(self):
        """Hide the zone counts table window."""
        if self.zone_counts_window is not None and self.zone_counts_window.winfo_exists():
            self.zone_counts_window.destroy()
        self.zone_counts_window = None

    def _refresh_zone_counts_table(self):
        """Refresh the open zone counts table after counts change."""
        if not self.show_zone_labels_var.get():
            return
        if self.zone_counts_window is None or not self.zone_counts_window.winfo_exists():
            return
        df, source_note = self._get_zone_counts_dataframe()
        if df is not None and not df.empty:
            self._populate_zone_counts_tree(df, source_note)

    def _open_zone_intensity_window(self):
        """Open (or refresh) a tabular view of zone names and intensities."""
        df, source_note = self._get_zone_intensities_dataframe()
        if df is None or df.empty:
            self.show_zone_intensity_labels_var.set(False)
            messagebox.showinfo(
                "No Regions",
                "No regions are defined for this file.\n\n"
                "Define regions on the atlas or with the Paint tool first.",
            )
            return

        if self.zone_intensity_window is not None and self.zone_intensity_window.winfo_exists():
            self._populate_zone_intensity_tree(df, source_note)
            self.zone_intensity_window.lift()
            return

        win = Toplevel(self.master)
        self.zone_intensity_window = win
        title_name = self.tiff_filename or "current file"
        win.title(f"Zone Labels & Intensities — {title_name}")
        win.geometry("720x400")
        win.transient(self.master)

        header = ttk.Frame(win, padding=(8, 8, 8, 4))
        header.pack(fill="x")
        ttk.Label(
            header,
            text=f"Zone pre/post correction intensities for {title_name}",
            font=("Helvetica", 10, "bold"),
        ).pack(anchor="w")
        self.zone_intensity_source_label = ttk.Label(
            header, text=source_note, foreground="gray"
        )
        self.zone_intensity_source_label.pack(anchor="w")

        table_frame = ttk.Frame(win, padding=(8, 4, 8, 8))
        table_frame.pack(fill="both", expand=True)

        columns = ("zone", "pre_mean", "pre_med", "post_mean", "post_med", "area")
        self.zone_intensity_tree = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        self.zone_intensity_tree.heading("zone", text="Zone")
        self.zone_intensity_tree.heading("pre_mean", text="Pre Mean")
        self.zone_intensity_tree.heading("pre_med", text="Pre Median")
        self.zone_intensity_tree.heading("post_mean", text="Post Mean")
        self.zone_intensity_tree.heading("post_med", text="Post Median")
        self.zone_intensity_tree.heading("area", text="Area (px)")
        self.zone_intensity_tree.column("zone", width=160, anchor="w")
        self.zone_intensity_tree.column("pre_mean", width=90, anchor="center")
        self.zone_intensity_tree.column("pre_med", width=90, anchor="center")
        self.zone_intensity_tree.column("post_mean", width=90, anchor="center")
        self.zone_intensity_tree.column("post_med", width=90, anchor="center")
        self.zone_intensity_tree.column("area", width=80, anchor="center")

        yscroll = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.zone_intensity_tree.yview
        )
        self.zone_intensity_tree.configure(yscrollcommand=yscroll.set)
        self.zone_intensity_tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        footer = ttk.Frame(win, padding=(8, 0, 8, 8))
        footer.pack(fill="x")
        self.zone_intensity_total_label = ttk.Label(footer, text="")
        self.zone_intensity_total_label.pack(anchor="w")

        def on_close():
            self.show_zone_intensity_labels_var.set(False)
            self.zone_intensity_window = None
            win.destroy()
            try:
                self.show_page()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._populate_zone_intensity_tree(df, source_note)

    def _populate_zone_intensity_tree(self, df, source_note=""):
        """Fill the intensity Treeview from a DataFrame."""
        if not hasattr(self, "zone_intensity_tree") or self.zone_intensity_tree is None:
            return
        if not self.zone_intensity_tree.winfo_exists():
            return

        for item in self.zone_intensity_tree.get_children():
            self.zone_intensity_tree.delete(item)

        n = 0
        total_area = 0
        means = []
        for _, row in df.iterrows():
            zone_name = str(row.get("Zone", ""))
            pre_mean = row.get("Pre_Correction_Mean", row.get("Mean_Intensity_Raw", np.nan))
            pre_med = row.get("Pre_Correction_Median", row.get("Median_Intensity_Raw", np.nan))
            post_mean = row.get("Post_Correction_Mean", row.get("Mean_Intensity", np.nan))
            post_med = row.get("Post_Correction_Median", row.get("Median_Intensity", np.nan))
            area_val = row.get("Region_Area", "")

            def _fmt(v):
                if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
                    return "—"
                try:
                    return f"{float(v):.2f}"
                except Exception:
                    return str(v)

            if pd.isna(area_val) or area_val == "" or area_val is None:
                area_display = "—"
            else:
                try:
                    area_display = str(int(area_val))
                    total_area += int(area_val)
                except Exception:
                    area_display = str(area_val)

            try:
                if post_mean is not None and not (
                    isinstance(post_mean, float) and np.isnan(post_mean)
                ):
                    means.append(float(post_mean))
            except Exception:
                pass

            self.zone_intensity_tree.insert(
                "",
                "end",
                values=(
                    zone_name,
                    _fmt(pre_mean),
                    _fmt(pre_med),
                    _fmt(post_mean),
                    _fmt(post_med),
                    area_display,
                ),
            )
            n += 1

        if hasattr(self, "zone_intensity_source_label") and self.zone_intensity_source_label.winfo_exists():
            self.zone_intensity_source_label.config(text=source_note)

        if hasattr(self, "zone_intensity_total_label") and self.zone_intensity_total_label.winfo_exists():
            parts = [f"Regions: {n}"]
            if means:
                parts.append(f"Mean of means: {np.mean(means):.2f}")
            if total_area:
                parts.append(f"Total area: {total_area} px")
            self.zone_intensity_total_label.config(text="  |  ".join(parts))

    def _close_zone_intensity_window(self):
        """Hide the zone intensity table window."""
        if self.zone_intensity_window is not None and self.zone_intensity_window.winfo_exists():
            self.zone_intensity_window.destroy()
        self.zone_intensity_window = None

    def _refresh_zone_intensity_table(self):
        """Refresh the open intensity table when the image/mask changes."""
        if not self.show_zone_intensity_labels_var.get():
            return
        if self.zone_intensity_window is None or not self.zone_intensity_window.winfo_exists():
            return
        df, source_note = self._get_zone_intensities_dataframe()
        if df is not None and not df.empty:
            self._populate_zone_intensity_tree(df, source_note)

    def _remove_paint_pen_menu_item(self):
        """Remove any leftover top-level 'Pen: …' menu entries (legacy Start Paint clutter)."""
        try:
            end = self.menu.index('end')
            if end is None:
                return
            # Delete all matching labels (older builds added one per Start Paint)
            for i in range(end, -1, -1):
                try:
                    if str(self.menu.entrycget(i, 'label')).startswith('Pen:'):
                        self.menu.delete(i)
                except Exception:
                    continue
        except Exception:
            pass

    def _finalize_paint_for_counting(self):
        """Commit active paint into zones without stop_paint side effects (save_state, save_paint, show_page)."""
        if getattr(self, 'current_state', None) != 'paint':
            return

        self.output.unbind('<B1-Motion>')
        self.output.unbind('<ButtonRelease-1>')
        self.output.unbind('<Button-1>')
        self.output.unbind('<Button-3>')
        self.output.bind('<Button-1>', self.highlight_region)
        self.output.bind("<B1-Motion>", self._handle_border_drag_motion, add=True)
        self._remove_paint_pen_menu_item()
        self.current_state = None
        self.region_move_mode.set(False)
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self._update_paint_indicator()

        all_current_groups = set()
        for item in (self.output.find_withtag('paint') or []):
            for tag in self.output.gettags(item):
                if tag.startswith('paintgroup_'):
                    all_current_groups.add(tag)
        for gtag in list(self.paint_group_data.keys()):
            if gtag.startswith('paintgroup_'):
                all_current_groups.add(gtag)
        for group_tag in all_current_groups:
            if group_tag not in self.named_paint_groups:
                self.named_paint_groups[group_tag] = None

        if self.paint_layer is not None:
            self._commit_canvas_paint_to_layer()
        self.output.delete('paint')

    def count_cells(self):
        logger.info("Starting cell counting process")
        if self.background_image is None:
            logger.warning("Cell counting failed: No TIFF file imported")
            messagebox.showerror("Error", "Please import a TIFF file first.")
            return

        # Finalize paint into zones without stop_paint (which runs save_state/save_paint/show_page
        # and can crash or corrupt UI state mid-count).
        self._finalize_paint_for_counting()

        # Ensure zone structures exist for the current page (important for pure Paint workflows)
        if self.current_page not in self.zone_names:
            self.zone_names[self.current_page] = {}
        if self.current_page not in self.mask_images:
            if self.original_background is not None:
                target_size = self.original_background.size
            elif self.background_image is not None:
                target_size = self.background_image.size
            else:
                target_size = (1024, 1024)  # fallback
            self.mask_images[self.current_page] = Image.new('L', target_size, 0)
        if self.current_page not in self.zone_counters:
            self.zone_counters[self.current_page] = 0

        # Always attempt to convert any remaining *named* paint groups into zones.
        # This is the main path for users who named their regions (via right-click or autonaming).
        self._convert_named_paints_to_zones()

        # Fallback for any completely unnamed paint strokes that are still on the canvas
        remaining_paint = self.output.find_withtag('paint')
        if remaining_paint:
            self._force_paint_strokes_to_zones(remaining_paint)
            self.output.delete('paint')

        # Final safety net: if we still have no zones but the user was painting,
        # try one last conversion of any named groups.
        page_zones = self.zone_names.get(self.current_page, {})
        if not page_zones:
            self._convert_named_paints_to_zones()
            page_zones = self.zone_names.get(self.current_page, {})

        # Ultimate hardening (addresses "named immediately after drawing then Count Cells says no regions"):
        # If paint data or named entries still exist (stop may have cleared only after its attempts),
        # force-add any data groups and convert. Combined with broadened collection inside convert
        # and the re-try inside stop_paint, this guarantees named paint groups produce zone entries
        # using durable model_points even across zoom/rebuild/dtag/reset lifecycles.
        if not page_zones:
            for gtag in list(self.paint_group_data.keys()):
                if gtag.startswith('paintgroup_') and gtag not in self.named_paint_groups:
                    self.named_paint_groups[gtag] = self.named_paint_groups.get(gtag)
            if self.named_paint_groups:
                self._convert_named_paints_to_zones()
            page_zones = self.zone_names.get(self.current_page, {})

        if not page_zones:
            messagebox.showerror(
                "No Regions Defined",
                "No regions (zones) have been defined for this page.\n\n"
                "To populate the spreadsheet:\n"
                "• For atlas: Click on regions in the atlas overlay to name them.\n"
                "• For paint: Draw with the Paint tool, right-click strokes to name them (or just draw and let Count Cells auto-assign 'Painted Region N' names), then click Count Cells."
            )
            return

        progress = self._show_busy_dialog("Counting Cells")
        final_cell_mask = None
        df = None
        try:
            progress.set_progress(10, "Preparing data...")

            # === Build Final Cell Mask ===
            if self.original_background is None:
                if self.background_image is not None:
                    self.original_background = self.background_image.copy()
                else:
                    messagebox.showerror("Error", "No original background image available for cell detection.")
                    return
            background = self.original_background.convert('L')
            base_size = background.size
            bh, bw = np.array(background).shape[:2]

            use_locked = (
                getattr(self, "cell_mask_locked", False)
                and getattr(self, "auto_mask", None) is not None
                and not isinstance(self.auto_mask, bool)
            )
            if use_locked:
                progress.set_progress(25, "Using loaded / locked cell mask...")
                auto_mask = np.asarray(self.auto_mask, dtype=bool).squeeze()
                if auto_mask.ndim != 2:
                    raise ValueError(f"Loaded cell mask must be 2D, got shape {auto_mask.shape}")
                if auto_mask.shape[0] != bh or auto_mask.shape[1] != bw:
                    auto_mask = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(auto_mask), (bh, bw)
                    )
                    self.auto_mask = auto_mask
                logger.info("Count Cells: using locked/loaded cell mask (no re-detection)")
            else:
                progress.set_progress(25, "Running cell detection...")
                _, auto_labels = binary_mask_cell_count(
                    background, processor=self.image_processor
                )
                auto_mask = np.asarray(auto_labels, dtype=bool).squeeze()
                if auto_mask.ndim != 2:
                    raise ValueError(f"Cell detection mask must be 2D, got shape {auto_mask.shape}")
                self.auto_mask = auto_mask
                self.cell_mask_locked = False

            progress.set_progress(45, "Processing manual edits...")
            add_mask = np.zeros(auto_mask.shape, dtype=bool)
            remove_mask = np.zeros(auto_mask.shape, dtype=bool)

            if self.manual_add_mask is not None:
                add_mask_arr = np.array(self.manual_add_mask.resize(base_size, Image.NEAREST))
                if add_mask_arr.ndim > 2:
                    add_mask_arr = add_mask_arr.squeeze()
                add_mask = add_mask_arr > 0

            if self.manual_remove_mask is not None:
                remove_mask_arr = np.array(self.manual_remove_mask.resize(base_size, Image.NEAREST))
                if remove_mask_arr.ndim > 2:
                    remove_mask_arr = remove_mask_arr.squeeze()
                remove_mask = remove_mask_arr > 0

            if add_mask.shape != auto_mask.shape:
                add_mask = np.array(
                    Image.fromarray(add_mask.astype(np.uint8) * 255).resize(
                        (auto_mask.shape[1], auto_mask.shape[0]), Image.NEAREST
                    )
                ) > 0
            if remove_mask.shape != auto_mask.shape:
                remove_mask = np.array(
                    Image.fromarray(remove_mask.astype(np.uint8) * 255).resize(
                        (auto_mask.shape[1], auto_mask.shape[0]), Image.NEAREST
                    )
                ) > 0

            final_cell_mask = (auto_mask | add_mask) & ~remove_mask
            self.last_cell_mask = final_cell_mask
            cell_mask_pil = Image.fromarray((final_cell_mask * 255).astype(np.uint8))

            region_mask_pil = self.mask_images[self.current_page]
            # img_x/img_y are model-space offsets (native image pixels)
            model_img_x = float(self.img_x) if self.img_x is not None else 0.0
            model_img_y = float(self.img_y) if self.img_y is not None else 0.0

            progress.set_progress(65, "Counting cells per region...")

            annotated, df, counts = count_cells_in_zones(
                self.original_background,
                region_mask_pil,
                cell_mask_pil,
                model_img_x,
                model_img_y,
                self.zone_counters,
                self.zone_names.get(self.current_page, {}),
            )

            self.background_image = annotated
            self._invalidate_bg_display_cache()
            self.last_df = df

            progress.set_progress(85, "Generating annotated image...")
            self.show_page()
            self._refresh_zone_counts_table()

            if progress and not getattr(progress, 'closed', False):
                progress.set_progress(100, "Done")
                progress.close()
                progress = None

            base_name = self.tiff_filename
            tiff_dir = self.tiff_dir
            # Count Cells exports go under <image_dir>/output/counts/
            out_dir = self._get_output_directory(tiff_dir, feature="counts") if tiff_dir else None
            paint_out = self._get_output_directory(tiff_dir, feature="paint") if tiff_dir else None

            saved_paths = []  # for summary dialog
            masked_path = None
            counts_path = None
            paint_path = None

            if out_dir and base_name and self.original_background is not None and final_cell_mask is not None:
                try:
                    orig = self.original_background.convert('RGBA')
                    # Donut rings (open centers) so underlying signal is visible in the export
                    ring_overlay = self._cell_detection_ring_overlay(
                        final_cell_mask,
                        size=orig.size,
                        color=(255, 0, 0),
                        alpha=200,
                        thickness=2,
                    )
                    masked_img = Image.alpha_composite(orig, ring_overlay)
                    masked_path = os.path.join(out_dir, f"{base_name}_masked.tif")
                    # Avoid tiff_deflate — it segfaults some Pillow/libtiff builds on Windows.
                    masked_img.save(masked_path)
                    saved_paths.append(f"Mask: {masked_path}")
                    logger.info(f"Masked image saved (ring outlines): {masked_path}")
                except Exception as e:
                    logger.error(f"Failed to save _masked.tif: {e}")

            excel_saved = False
            if out_dir and base_name and df is not None:
                xlsx_path = os.path.join(out_dir, f"{base_name}.xlsx")
                for engine in ['openpyxl', 'xlsxwriter']:
                    try:
                        with pd.ExcelWriter(xlsx_path, engine=engine) as writer:
                            df.to_excel(writer, sheet_name="Cell Counts", index=False)
                            meta_data = []
                            cfg = self.image_processor.cell_config
                            pcfg = self.image_processor.preprocess_config
                            for k, v in cfg.__dict__.items():
                                meta_data.append({"Category": "Cell Detection", "Parameter": k, "Value": str(v)})
                            for k, v in pcfg.__dict__.items():
                                meta_data.append({"Category": "Preprocessing", "Parameter": k, "Value": str(v)})
                            meta_df = pd.DataFrame(meta_data)
                            meta_df.to_excel(writer, sheet_name="Detection Parameters", index=False)
                        counts_path = xlsx_path
                        saved_paths.append(f"Counts: {xlsx_path}")
                        excel_saved = True
                        break
                    except Exception:
                        continue

                if not excel_saved:
                    try:
                        csv_path = os.path.join(out_dir, f"{base_name}.csv")
                        df.to_csv(csv_path, index=False)
                        counts_path = csv_path
                        saved_paths.append(f"Counts (CSV): {csv_path}")
                        messagebox.showwarning(
                            "Excel Export Failed",
                            f"Could not save as Excel (openpyxl or xlsxwriter not installed).\n"
                            f"Fell back to CSV:\n{csv_path}\n\n"
                            f"To enable .xlsx output with metadata sheet, run:\n"
                            f"pip install openpyxl xlsxwriter"
                        )
                    except Exception as e:
                        logger.error(f"CSV fallback also failed: {e}")

            # Per-cell measurements: centroid x,y and pixel area for every detected cell
            cells_csv_path = None
            if out_dir and base_name and final_cell_mask is not None:
                try:
                    cells_csv_path = self._export_cell_centroids_csv(
                        final_cell_mask, out_dir, base_name
                    )
                    if cells_csv_path:
                        saved_paths.append(f"Cell centroids: {cells_csv_path}")
                except Exception as e:
                    logger.error(f"Failed to save cell centroids CSV: {e}")

            # Always auto-save paint layer into output/paint/ when counting
            if paint_out and base_name:
                try:
                    paint_path = self._save_paint_layer_to_dir(
                        paint_out, base_name, unique=False, show_messages=False
                    )
                    if paint_path:
                        saved_paths.append(f"Paint: {paint_path}")
                except Exception as e:
                    logger.error(f"Failed to auto-save paint layer on count: {e}")

            # Metadata file: full mask/detection parameters for reproducibility
            if out_dir and base_name:
                try:
                    meta_path = self._save_mask_metadata_file(
                        out_dir,
                        base_name,
                        extra={
                            "counts_file": counts_path,
                            "masked_image": masked_path,
                            "paint_file": paint_path,
                            "cell_centroids_file": cells_csv_path,
                            "output_directory": out_dir,
                        },
                    )
                    if meta_path:
                        saved_paths.append(f"Metadata: {meta_path}")
                except Exception as e:
                    logger.error(f"Failed to save mask metadata on count: {e}")

            if out_dir and saved_paths:
                summary = (
                    "Results saved by feature under output/:\n"
                    f"  counts → {out_dir}\n"
                )
                if paint_out:
                    summary += f"  paint  → {paint_out}\n"
                summary += "\n" + "\n".join(saved_paths)
                messagebox.showinfo("Results Saved", summary)
            elif not tiff_dir or not base_name:
                logger.warning("Skipping auto-save of count results (missing tiff_dir or base_name)")
                try:
                    messagebox.showinfo(
                        "Count Complete",
                        "Cells counted. No working TIFF directory was set, so outputs were not auto-saved.",
                    )
                except Exception:
                    pass
            elif not out_dir:
                logger.warning("Could not create output/ directory for count exports")
                try:
                    messagebox.showwarning(
                        "Count Complete",
                        "Cells counted, but the output folder could not be created. Results were not saved to disk.",
                    )
                except Exception:
                    pass

            if hasattr(self, 'tiff_tree') and self.current_tiff_directory:
                self.master.after(300, self.refresh_tiff_file_list)

        except Exception as e:
            logger.error(f"Cell counting failed: {e}", exc_info=True)
            messagebox.showerror("Count Failed", f"Cell counting failed:\n{e}")
        finally:
            if progress and not getattr(progress, 'closed', False):
                progress.close()

    def show_cell_mask_threshold(self, event=None, calculate=True):
        """Display the combined (auto + manual) mask overlay.

        calculate=True runs detection and unlocks a previously loaded mask.
        calculate=False reuses auto_mask (including loaded/locked masks).
        """
        progress = None
        if self.original_background is None:
            messagebox.showwarning("Show Mask", "Load a TIFF image first.")
            return

        # Explicit re-detect unlocks any loaded mask from another channel
        if calculate:
            self.cell_mask_locked = False
            self.cell_mask_source_path = None
            progress = self._show_busy_dialog("Detecting Cells")
            progress.set_progress(5, "Preparing image...")

        background = self.original_background.convert('L')

        # Run automatic detection
        if calculate:
            progress.set_progress(15, "Running cell detection...")
            _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
            auto_mask = auto_labels > 0
            self.auto_mask = auto_mask
            progress.set_progress(55, "Building mask visualization...")
        else:
            auto_mask = self.auto_mask
            if auto_mask is None or isinstance(auto_mask, bool):
                # Fallback: auto_mask not properly initialized (e.g. after reset or zoom state issue)
                progress2 = None
                if progress is None:
                    progress2 = self._show_busy_dialog("Detecting Cells")
                    progress2.set_progress(5, "Preparing image...")
                _, auto_labels = binary_mask_cell_count(background, processor=self.image_processor)
                auto_mask = auto_labels > 0
                self.auto_mask = auto_mask
                self.cell_mask_locked = False
                if progress2:
                    progress2.set_progress(55, "Building mask visualization...")
                    progress2.close()
            else:
                # Ensure size matches current image (cross-channel load / resize)
                bh, bw = np.array(background).shape[:2]
                auto_mask = np.asarray(auto_mask, dtype=bool).squeeze()
                if auto_mask.shape[0] != bh or auto_mask.shape[1] != bw:
                    auto_mask = self._l_image_to_bool_mask(
                        self._bool_mask_to_l_image(auto_mask), (bh, bw)
                    )
                    self.auto_mask = auto_mask

        base_size = background.size
        add_mask = np.zeros(auto_mask.shape, dtype=bool)
        remove_mask = np.zeros(auto_mask.shape, dtype=bool)

        # Load manual add/remove masks if present
        if self.manual_add_mask is not None:
            add_mask_arr = np.array(self.manual_add_mask) #.resize(base_size, Image.NEAREST))
            add_mask = add_mask_arr > 0
        if self.manual_remove_mask is not None:
            remove_mask_arr = np.array(self.manual_remove_mask) #.resize(base_size, Image.NEAREST))
            remove_mask = remove_mask_arr > 0

        # Combine automatic and manual edits
        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(70, "Combining manual edits...")
        combined_mask = (auto_mask | add_mask) & ~remove_mask

        # Visualize as open red "donut" rings (boundary only) so fluorescence under each blob stays visible
        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(85, "Generating ring visualization...")
        target_size = self.original_background.size  # (w, h)
        mask_img = self._cell_detection_ring_overlay(
            combined_mask,
            size=target_size,
            color=(255, 0, 0),
            alpha=230,
            thickness=2,
        )
        # Composite cyan random null distribution if present
        rand = getattr(self, "random_cell_mask", None)
        if rand is not None:
            try:
                rmask = np.asarray(rand, dtype=bool).squeeze()
                cyan = self._cell_detection_ring_overlay(
                    rmask,
                    size=target_size,
                    color=(0, 220, 255),
                    alpha=220,
                    thickness=2,
                )
                mask_img = Image.alpha_composite(
                    mask_img.convert("RGBA"), cyan.convert("RGBA")
                )
            except Exception as e:
                logger.debug(f"Random mask overlay skipped: {e}")

        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(95, "Displaying mask...")
        self.show_page(mask=mask_img)

        if progress and not getattr(progress, 'closed', False):
            progress.set_progress(100, "Done")
            progress.close()

        self.showing_auto_mask = True

    
    def next_image_experimental(self):  # unused
        self.root.destroy()
        PDFViewer()

    # ------------------------------------------------------------------
    # File Browser navigation (Phase A)
    # ------------------------------------------------------------------

    def _nav_previous_image_event(self, event=None):
        self.previous_image()
        return "break"

    def _nav_next_image_event(self, event=None):
        self.next_image()
        return "break"

    def _nav_next_uncounted_event(self, event=None):
        self.next_uncounted_image()
        return "break"

    def _current_list_index(self):
        """Index of the currently open TIFF in tiff_file_list, or -1 if unknown."""
        if not getattr(self, "tiff_file_list", None):
            return -1
        path = getattr(self, "current_tiff_path", None)
        if not path:
            return -1
        target = self._norm_path(path)
        for i, p in enumerate(self.tiff_file_list):
            if self._norm_path(p) == target:
                return i
        return -1

    def _autosave_before_image_switch(self):
        """Autosave flattened + counts + paint into feature output subfolders before leaving."""
        did_autosave = False
        if not (getattr(self, "original_background", None) or getattr(self, "background_image", None)):
            return did_autosave
        try:
            flat_dir = self._get_output_directory(self.tiff_dir, feature="flattened") if self.tiff_dir else None
            counts_dir = self._get_output_directory(self.tiff_dir, feature="counts") if self.tiff_dir else None
            paint_dir = self._get_output_directory(self.tiff_dir, feature="paint") if self.tiff_dir else None
            if self.tiff_dir and self.tiff_filename and flat_dir:
                image_path = os.path.join(flat_dir, f"{self.tiff_filename}_flattened.tif")
                self.autosave_flattened_image(image_path)
                did_autosave = True
            if self.last_df is not None and self.tiff_dir and self.tiff_filename and counts_dir:
                csv_path = os.path.join(counts_dir, f"{self.tiff_filename}_counts.csv")
                self.last_df.to_csv(csv_path, index=False)
                did_autosave = True
            # Also refresh paint export into output/paint/ if paint exists
            if paint_dir and self.tiff_filename:
                try:
                    self._save_paint_layer_to_dir(
                        paint_dir, self.tiff_filename, unique=False, show_messages=False
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Autosave before image switch failed: {e}")
        return did_autosave

    def _load_list_image_at(self, index, announce=False):
        """Load tiff_file_list[index] after optional autosave of current work."""
        if not self.tiff_file_list:
            messagebox.showinfo(
                "No Images",
                "No TIFF images in the File Browser folder.\nUse Select Folder first.",
            )
            return False
        if index < 0 or index >= len(self.tiff_file_list):
            return False
        target = self.tiff_file_list[index]
        # Skip reload if already open
        if getattr(self, "current_tiff_path", None) and self._norm_path(self.current_tiff_path) == self._norm_path(target):
            return True
        self._autosave_before_image_switch()
        # Refresh so status of the image we left (e.g. new _counts.csv) appears immediately
        if self.current_tiff_directory and os.path.isdir(self.current_tiff_directory):
            try:
                self.refresh_tiff_file_list()
            except Exception:
                pass
        # Keep atlas across Prev/Next when present (same as Next Channel for multi-section work)
        self._load_tiff_file(target)
        if announce:
            logger.info(f"Navigated to image {index + 1}/{len(self.tiff_file_list)}: {target}")
        return True

    def previous_image(self):
        """Load the previous source TIFF in the File Browser list (Ctrl+Left)."""
        if not self.tiff_file_list:
            if self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if not self.tiff_file_list:
                messagebox.showinfo(
                    "Previous Image",
                    "No TIFF images available. Select a folder in the File Browser first.",
                )
                return
        idx = self._current_list_index()
        if idx < 0:
            # Nothing open yet — load first
            self._load_list_image_at(0)
            return
        if idx <= 0:
            messagebox.showinfo("Previous Image", "Already at the first image in this folder.")
            return
        self._load_list_image_at(idx - 1)

    def next_image(self):
        """Load the next source TIFF in the File Browser list (Ctrl+Right).

        Autosaves flattened/counts for the current image when leaving it.
        """
        if not self.tiff_file_list:
            if self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if not self.tiff_file_list:
                messagebox.showinfo(
                    "Next Image",
                    "No TIFF images available. Select a folder in the File Browser first.",
                )
                return
        idx = self._current_list_index()
        if idx < 0:
            self._load_list_image_at(0)
            return
        if idx >= len(self.tiff_file_list) - 1:
            messagebox.showinfo("Next Image", "Already at the last image in this folder.")
            return
        self._load_list_image_at(idx + 1)

    def next_uncounted_image(self):
        """Load the next source TIFF that does not yet have count results (Ctrl+Shift+Right)."""
        if not self.tiff_file_list:
            if self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if not self.tiff_file_list:
                messagebox.showinfo(
                    "Next Uncounted",
                    "No TIFF images available. Select a folder in the File Browser first.",
                )
                return

        start = self._current_list_index()
        # Search after current (or from beginning if none open)
        search_from = start + 1 if start >= 0 else 0
        for i in range(search_from, len(self.tiff_file_list)):
            if not self._get_image_work_status(self.tiff_file_list[i]).get("counted", False):
                self._load_list_image_at(i)
                return

        messagebox.showinfo(
            "Next Uncounted",
            "No remaining uncounted images after the current one in this folder.\n"
            f"Progress is shown in the File Browser summary.",
        )

    def clear_canvas_session(self):
        """Clear all loaded images, paint, zones, and overlays while keeping the
        File Browser folder list. Formerly the behavior of Next Image before Phase A.
        Autosaves flattened/counts when possible.
        """
        logger.info("Clear canvas session / reset for new image")

        did_autosave = self._autosave_before_image_switch()

        # Preserve directory and browser widgets
        saved_current_dir = getattr(self, "current_tiff_directory", None)
        saved_tree = getattr(self, "tiff_tree", None)
        saved_iid_map = getattr(self, "_tree_iid_to_path", None)
        saved_path_map = getattr(self, "_tree_path_to_iid", None)
        saved_file_list = getattr(self, "tiff_file_list", None)
        saved_folder_label = getattr(self, "folder_label", None)

        clear_preprocess_cache()

        # Full reset of loaded content and analysis state
        self.doc = None
        self.path = None
        self.atlas_filetype = None
        self.allen_nissl_reference = None
        self.allen_nissl_photo = None
        self.allen_zone_meta = {}
        self.current_page = 0
        self.page_images = {}
        self.mask_images = {}
        self.base_page_images = {}
        self.zone_counters = {}
        self.zone_names = {}
        self.selected_zone_id = None
        self.selected_page = None
        self._clear_edge_highlight()
        self.edge_grab_active = False
        self.border_drag_active = False
        self.active_edge = None
        self.current_edited_contour = None
        self.original_full_contour_for_edit = None
        self.selected_edge_full_contour = None
        self._edge_pending_deselect = False
        self.region_translate_active = False
        self.region_translate_original_mask = None
        self.region_translate_zid = None
        self.region_move_mode.set(False)
        self.crop_mode = False
        if hasattr(self, "crop_mode_var"):
            self.crop_mode_var.set(False)
        self.edit_mode = False
        if hasattr(self, "edit_mode_var"):
            self.edit_mode_var.set(False)

        self.named_paint_groups = {}
        self.paint_group_data = {}
        self.painted_zone_outlines = {}
        self.current_paint_group = None
        self.paint_layer = None
        self.img = None
        self.background_image = None
        self.original_background = None
        self.bg_photo_id = None
        self._invalidate_bg_display_cache()
        self.last_df = None
        self.last_cell_mask = None
        self.img_x = 0
        self.img_y = 0
        self.view_scale = 1.0
        self.zoom = 1.0
        self.brightness = 0.0
        self.current_state = None
        self.current_tiff_path = None

        self.manual_add_mask = None
        self.manual_remove_mask = None
        self.editing_mask = False
        self.mask_edit_add = True
        self.mask_photo = False
        self.mask_photo_id = False
        self.current_mask = None
        self.auto_mask = None
        self.showing_auto_mask = False

        try:
            self.state_manager.undo_stack.clear()
        except Exception:
            self.state_manager.undo_stack = []

        if saved_current_dir:
            self.current_tiff_directory = saved_current_dir
        if saved_tree is not None:
            self.tiff_tree = saved_tree
        if saved_iid_map is not None:
            self._tree_iid_to_path = saved_iid_map
        if saved_path_map is not None:
            self._tree_path_to_iid = saved_path_map
        if saved_file_list is not None:
            self.tiff_file_list = saved_file_list
        if saved_folder_label is not None:
            self.folder_label = saved_folder_label

        if hasattr(self, "output"):
            try:
                self.output.delete("all")
            except Exception:
                pass

        try:
            self.show_page()
            if hasattr(self, "_update_ribbon_selection"):
                self._update_ribbon_selection()
            if hasattr(self, "refresh_tiff_file_list") and self.current_tiff_directory:
                self.refresh_tiff_file_list()
            if hasattr(self, "current_file_var"):
                self.current_file_var.set("")
        except Exception as e:
            logger.warning(f"Error during clear_canvas_session UI reset: {e}")

        if did_autosave:
            messagebox.showinfo(
                "Clear Canvas",
                "Current image cleared. File Browser folder is preserved.\n"
                "Previous flattened/counts were auto-saved where possible.",
            )
        else:
            messagebox.showinfo(
                "Clear Canvas",
                "App state cleared. Ready to load a new image from the File Browser.",
            )

def count_cells_in_zones(background_pil, mask_pil, page_pil, img_x, img_y, zone_counters, zone_names):
    """Enhanced cell counting with improved visualization"""
    logger.info("Starting cell counting in zones")
    
    # Convert background to grayscale if it's not already
    background_array = np.array(background_pil)
    if background_array.ndim == 3:
        background_gray = np.dot(background_array[..., :3], [0.2989, 0.5870, 0.1140])
    else:
        background_gray = background_array
        
    # Normalize to float [0, 1]
    background_norm = (background_gray - background_gray.min()) / (background_gray.max() - background_gray.min() + 1e-8)
    
    img2d = background_norm

    if page_pil is not None:
        # Caller already ran detection and merged manual edits — avoid a second
        # detect + watershed pass (crashes/OOM on large microscopy frames).
        binary = np.asarray(page_pil)
        if binary.ndim > 2:
            binary = binary.squeeze()
        binary = binary > 0
        labels = measure.label(binary)
        props = measure.regionprops(labels)
    else:
        # Legacy path when no precomputed mask is supplied.
        _, binary = binary_mask_cell_count(Image.fromarray((background_norm * 255).astype(np.uint8)))
        binary = np.asarray(binary, dtype=bool)

        logger.debug("Performing distance transform for watershed")
        distance = distance_transform_edt(binary)

        try:
            coords = feature.peak_local_max(distance, min_distance=5, exclude_border=True)
        except TypeError:
            coords = feature.peak_local_max(distance, min_distance=5)
        if isinstance(coords, tuple):
            coords = np.column_stack(coords)
        markers = np.zeros(distance.shape, dtype=bool)
        if getattr(coords, 'size', 0):
            markers[tuple(coords.T)] = True
        markers = measure.label(markers)

        if markers.max() == 0:
            labels = measure.label(binary)
        else:
            labels = segmentation.watershed(-distance, markers, mask=binary)
        props = measure.regionprops(labels)

    # Initialize counts for all known zones on this page (from zone_names).
    # This ensures the output spreadsheet lists every named/painted region (with 0 if no cells found).
    # Also seed from any ids present in the mask (for orphan labels).
    counts = {int(zid): 0 for zid in (zone_names or {}).keys()}
    try:
        m0 = np.array(mask_pil)
        for z in np.unique(m0):
            if z > 0:
                counts.setdefault(int(z), 0)
    except Exception:
        pass
    filtered_props = []

    # Filter props based on mask and count per zone.
    # Use a small neighborhood search around each centroid. This tolerates:
    # - cells whose centroid lands exactly on a boundary stroke pixel
    # - tiny gaps or imperfections left by even the improved flood/hole-fill
    mask_arr = np.array(mask_pil)
    mask_h, mask_w = mask_arr.shape
    # Determine whether the zone mask is in the same coordinate system as the cell detection / background.
    # - Paint regions (and standalone TIFF) live in the main background image space (offset 0).
    # - Atlas zones may come from a differently-sized/positioned overlay layer (use img_x/y for translation).
    bg_w, bg_h = background_pil.size  # PIL (width, height)
    use_offset = not (abs(mask_w - bg_w) < 5 and abs(mask_h - bg_h) < 5)

    for prop in props:
        row, col = prop.centroid
        if use_offset:
            ax = int(col - img_x)
            ay = int(row - img_y)
        else:
            ax = int(col)
            ay = int(row)

        found_zone = 0
        # Check exact point first, then a 5x5 neighborhood (good balance of tolerance vs. accuracy)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                qx = ax + dx
                qy = ay + dy
                if 0 <= qx < mask_w and 0 <= qy < mask_h:
                    val = mask_arr[qy, qx]
                    if val > 0:
                        found_zone = int(val)
                        break
            if found_zone:
                break

        if found_zone > 0:
            counts.setdefault(found_zone, 0)
            counts[found_zone] += 1
            filtered_props.append(prop)

    # Enhanced visualization (wrapped so errors here don't lose the counts/df)
    try:
        bg_min = img2d.min()
        bg_max = img2d.max()
        norm = (img2d - bg_min) / (bg_max - bg_min) if bg_max > bg_min else np.zeros_like(img2d)
        img_uint8 = (norm * 255).astype('uint8')
        img_rgb = np.stack([img_uint8]*3, axis=-1)
        annotated = Image.fromarray(img_rgb)
        draw = ImageDraw.Draw(annotated, 'RGBA')

        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        # Add cell annotations with improved visibility
        for i, prop in enumerate(filtered_props, start=1):
            r, c = prop.centroid
            draw.ellipse([int(c)-3, int(r)-3, int(c)+3, int(r)+3], outline=(255,0,0,200))
            draw.text((int(c)+4, int(r)-6), str(i), fill=(255,0,0,200), font=font)

        annotated = annotated.convert('RGBA')

        # Create visualization
        # Convert the original image to RGB for annotation
        if background_array.ndim == 2:
            rgb_img = np.stack([background_array] * 3, axis=-1)
        else:
            rgb_img = background_array[..., :3].copy()

        # Draw detected cells
        for i, prop in enumerate(filtered_props, start=1):
            y, x = prop.centroid  # y is row, x is column
            y, x = int(y), int(x)
            
            # Draw a small cross marker for each cell
            marker_size = 3
            
            # Draw vertical line
            y_start = max(0, y - marker_size)
            y_end = min(rgb_img.shape[0] - 1, y + marker_size + 1)
            x_pos = min(max(0, x), rgb_img.shape[1] - 1)
            if y_start < y_end:
                rgb_img[y_start:y_end, x_pos, :] = [255, 0, 0]
            
            # Draw horizontal line
            x_start = max(0, x - marker_size)
            x_end = min(rgb_img.shape[1] - 1, x + marker_size + 1)
            y_pos = min(max(0, y), rgb_img.shape[0] - 1)
            if x_start < x_end:
                rgb_img[y_pos, x_start:x_end, :] = [255, 0, 0]

        # Convert to PIL Image
        annotated = Image.fromarray(rgb_img.astype(np.uint8))
    except Exception:
        # Fallback: just use a copy of the background as annotated if viz fails
        if background_array.ndim == 2:
            rgb_img = np.stack([background_array] * 3, axis=-1)
        else:
            rgb_img = background_array[..., :3].copy()
        annotated = Image.fromarray(rgb_img.astype(np.uint8))

    # Region areas (total pixels of each zone in the zone mask)
    zone_areas = {}
    try:
        for zid in counts.keys():
            zone_areas[int(zid)] = int(np.sum(mask_arr == int(zid)))
    except Exception:
        for zid in counts.keys():
            zone_areas[int(zid)] = 0

    # Prepare results DataFrame: cells counted + total region area (pixels)
    zone_list, count_list, area_list = [], [], []
    for zid in sorted(counts.keys()):
        zid = int(zid)
        name = zone_names.get(zid, f"Zone {zid}")
        zone_list.append(name)
        count_list.append(counts[zid])
        area_list.append(zone_areas.get(zid, 0))
    df = pd.DataFrame({
        'Zone': zone_list,
        'Cell_Count': count_list,
        'Region_Area': area_list,
    })
    
    return annotated, df, counts

class StateManager:
    """Manages undo history for user actions (paint, atlas edits, mask edits, region transforms, etc.).

    Snapshots are taken *before* mutating actions (via viewer.save_state() calls at the
    start of user-initiated edit paths). Supports repeated undo.
    """

    MAX_HISTORY = 40

    def __init__(self):
        self.undo_stack = []

    def _copy_image(self, img):
        """Safely copy a PIL Image or return None."""
        if img is None:
            return None
        try:
            return img.copy()
        except Exception:
            return None

    def _copy_image_dict(self, d):
        """Deep copy a dict of page_id -> PIL.Image (or None)."""
        if not d:
            return {}
        out = {}
        for k, v in d.items():
            out[k] = self._copy_image(v)
        return out

    def save_state(self, viewer):
        """Capture a snapshot of all user-editable state before a mutation."""
        try:
            state = {
                # View / placement
                "current_page": viewer.current_page,
                "img_x": viewer.img_x,
                "img_y": viewer.img_y,
                "view_scale": getattr(viewer, 'view_scale', 1.0),
                "zoom": getattr(viewer, 'zoom', 1.0),

                # Core editable data
                "zone_counters": copy.deepcopy(getattr(viewer, 'zone_counters', {})),
                "zone_names": copy.deepcopy(getattr(viewer, 'zone_names', {})),
                "mask_images": self._copy_image_dict(getattr(viewer, 'mask_images', {})),
                "base_page_images": self._copy_image_dict(getattr(viewer, 'base_page_images', {})),
                "page_images": self._copy_image_dict(getattr(viewer, 'page_images', {})),

                # Paint system (critical for repeated undo of drawing/naming)
                "paint_group_data": copy.deepcopy(getattr(viewer, 'paint_group_data', {})),
                "named_paint_groups": copy.deepcopy(getattr(viewer, 'named_paint_groups', {})),
                "_paint_group_counter": getattr(viewer, '_paint_group_counter', 0),
                "paint_layer": self._copy_image(getattr(viewer, 'paint_layer', None)),
                "painted_zone_outlines": copy.deepcopy(getattr(viewer, 'painted_zone_outlines', {})),

                # Manual cell edits
                "manual_add_mask": self._copy_image(getattr(viewer, 'manual_add_mask', None)),
                "manual_remove_mask": self._copy_image(getattr(viewer, 'manual_remove_mask', None)),

                # Last count results (so visual + any derived state can be consistent)
                "last_df": copy.deepcopy(getattr(viewer, 'last_df', None)),
            }

            # Bounded history: drop oldest when full
            if len(self.undo_stack) >= self.MAX_HISTORY:
                self.undo_stack.pop(0)

            self.undo_stack.append(state)
            logger.debug(f"Saved state to undo stack (depth={len(self.undo_stack)})")
        except Exception as e:
            logger.warning(f"Failed to save undo state: {e}")

    def undo(self, viewer):
        """Restore the previous snapshot and refresh the display."""
        if not self.undo_stack:
            logger.debug("No states to undo")
            return False

        try:
            state = self.undo_stack.pop()

            # Restore scalars / view
            viewer.current_page = state.get("current_page", 0)
            viewer.img_x = state.get("img_x", 0)
            viewer.img_y = state.get("img_y", 0)
            if hasattr(viewer, 'view_scale'):
                viewer.view_scale = state.get("view_scale", 1.0)
            if hasattr(viewer, 'zoom'):
                viewer.zoom = state.get("zoom", 1.0)

            # Restore data structures
            viewer.zone_counters = state.get("zone_counters", {})
            zn = state.get("zone_names", {})
            if zn:
                viewer.zone_names = {pg: {int(k): v for k, v in (zn.get(pg, {}) or {}).items()} for pg in zn}
            else:
                viewer.zone_names = {}
            viewer.mask_images = state.get("mask_images", {})
            viewer.base_page_images = state.get("base_page_images", {})
            if hasattr(viewer, 'page_images'):
                viewer.page_images = state.get("page_images", {})

            # Prune the restored mask so it only contains zids present in the restored zone_names.
            # This prevents the orphan-discovery logic in _populate_region_list (which scans
            # the mask and auto _ensure_zone_has_name for any zid in the pixels) from
            # immediately re-adding zones that the undo was supposed to remove (common for
            # painted regions whose mask fills were created after the snapshot point).
            # Without this, the banner/list would show "removed" painted regions.
            page = getattr(viewer, 'current_page', 0)
            if page in viewer.mask_images and page in viewer.zone_names:
                try:
                    m = np.array(viewer.mask_images[page])
                    valid_zids = set(viewer.zone_names[page].keys())
                    keep = np.isin(m, list(valid_zids) + [0])
                    if not keep.all():
                        m[~keep] = 0
                        viewer.mask_images[page] = Image.fromarray(m.astype(np.uint8))
                except Exception:
                    pass

            # Clear selection early so the forced ribbon update below shows "No region selected"
            # and the list reflects only the restored names (without the undone painted regions).
            viewer.selected_zone_id = None
            viewer.selected_page = None

            # Force the ribbon banner/list to immediately reflect the restored (pruned) zone_names
            # so removed painted regions disappear from the Atlas Manager even before full show_page.
            if hasattr(viewer, '_update_ribbon_selection'):
                try:
                    viewer._update_ribbon_selection()
                except Exception:
                    pass

            viewer.paint_group_data = state.get("paint_group_data", {})
            viewer.named_paint_groups = state.get("named_paint_groups", {})
            viewer._paint_group_counter = state.get("_paint_group_counter", 0)
            viewer.paint_layer = state.get("paint_layer")
            pzo = state.get("painted_zone_outlines", {})
            viewer.painted_zone_outlines = {int(k): v for k, v in (pzo or {}).items()} if pzo else {}

            # Do NOT force _rebuild_paint_layer_from_data here.
            # The paint_layer snapshot from the historical point already contains
            # exactly the baked strokes up to that moment (including finalized/named
            # ones whose groups were popped from data at naming time).
            # Forcing rebuild from the (possibly empty) restored paint_group_data
            # would blank previous named paints' visuals, causing "one undo removes
            # multiple".
            # Direct restore of the snapshot's paint_layer gives precise per-stroke
            # visual undo.

            viewer.manual_add_mask = state.get("manual_add_mask")
            viewer.manual_remove_mask = state.get("manual_remove_mask")

            if hasattr(viewer, 'last_df'):
                viewer.last_df = state.get("last_df")

            # Clear all transient editing / selection state (edge drag, move-selected, etc.)
            # (already set above, but clear other transients)

            for attr in (
                'edge_grab_active', 'border_drag_active', 'active_edge',
                'current_edited_contour', 'original_full_contour_for_edit',
                'selected_edge_full_contour', '_edge_pending_deselect',
                'region_translate_active', 'region_translate_original_mask',
                'region_translate_zid', 'border_drag_original_mask',
            ):
                if hasattr(viewer, attr):
                    setattr(viewer, attr, None if 'mask' in attr or 'contour' in attr or 'edge' in attr else False)

            # Reset mode checkboxes/vars to neutral (show_page also does some of this)
            for var_name, val in (
                ('region_move_mode', False),
                ('crop_mode_var', False),
                ('edit_mode_var', False),
                ('border_mode_var', False),  # default from init (unchecked; user must select it)
            ):
                var = getattr(viewer, var_name, None)
                if var is not None:
                    try:
                        var.set(val)
                    except Exception:
                        pass

            if hasattr(viewer, 'crop_mode'):
                viewer.crop_mode = False
            if hasattr(viewer, 'edit_mode'):
                viewer.edit_mode = False
            if hasattr(viewer, 'region_translate_active'):
                viewer.region_translate_active = False

            # Reset paint drawing transients so we don't have a dangling current stroke after undo
            viewer.old_x = None
            viewer.old_y = None
            viewer.current_paint_group = None
            viewer.current_state = None

            if hasattr(viewer, '_update_paint_indicator'):
                try:
                    viewer._update_paint_indicator()
                except Exception:
                    pass

            # Redraw everything from the restored data
            viewer.show_page()

            # Keep ribbon in sync if present
            if hasattr(viewer, '_update_ribbon_selection'):
                try:
                    viewer._update_ribbon_selection()
                except Exception:
                    pass

            logger.debug(f"Restored previous state (remaining undo depth={len(self.undo_stack)})")
            return True
        except Exception as e:
            logger.warning(f"Undo failed: {e}")
            # Attempt a safe redraw anyway
            try:
                viewer.show_page()
            except Exception:
                pass
            return False

class PDFHandler:
    def __init__(self):
        self.doc = None
        self.num_pages = 0

    def open_pdf(self, path):
        """Open a PDF file and return document object and page count"""
        logger.debug(f"Opening PDF: {path}")
        self.doc = fitz.open(path)
        self.num_pages = len(self.doc)
        logger.info(f"Loaded PDF with {self.num_pages} pages")
        return self.doc, self.num_pages

    def render_page(self, page_index, zoom):
        """Render a specific page of the PDF at given zoom level"""
        if self.doc is None:
            raise RuntimeError("No PDF opened")
        page = self.doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB, alpha=True)
        img = Image.frombytes("RGBA", [pix.width, pix.height], pix.samples)
        return img

# Initialize global cache for preprocessing
_PREPROCESS_CACHE = {}

def preprocess_for_highlighting(page_id, img, atlas_filetype):
    """Preprocess an image for region highlighting"""
    if page_id in _PREPROCESS_CACHE:
        return _PREPROCESS_CACHE[page_id]
    
    logger.debug(f"Processing image for highlighting: mode={img.mode}, size={img.size}")

    if atlas_filetype == 'pdf':
        img_array = np.array(img)
        # Convert to gray for edge detection
        gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140]).astype(np.float32)
        # Edge detection
        mag = filters.sobel(gray)
        # Threshold the gradient magnitude to make a binary edge image
        try:
            thresh = mag.mean() + 0.5 * mag.std()
        except Exception:
            thresh = np.mean(mag)
        mag_binary = mag > thresh

        # Close small gaps in the binary edges
        closed_binary = closing(mag_binary)

        # Make bounds as thin as possible
        skel_binary = morphology.skeletonize(closed_binary)

        barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
        barrier[skel_binary > 0] = 0
        barrier_img = Image.fromarray(barrier.astype('uint8')).convert('L')
        # Cache the result so repeated calls are fast
        _PREPROCESS_CACHE[page_id] = barrier_img
        return barrier_img

    # Convert to RGBA if not already
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    img_array = np.array(img)
    
    # Extract the alpha channel - non-transparent pixels are our barriers
    alpha = img_array[..., 3]

    # Create barrier image: 255 for areas we can flood (transparent), 0 for barriers (non-transparent)
    barrier = np.ones((img.height, img.width), dtype=np.uint8) * 255
    barrier[alpha > 0] = 0  # Non-transparent pixels become barriers
    
    barrier_img = Image.new('L', (img.width, img.height))
    barrier_img.putdata(barrier.flatten())
    
    logger.debug(f"Created barrier image with mode={barrier_img.mode}")
    _PREPROCESS_CACHE[page_id] = barrier_img
    
    return barrier_img

def clear_preprocess_cache():
    """Clear the preprocessing cache"""
    _PREPROCESS_CACHE.clear()
    logger.debug("Cleared preprocessing cache")

if __name__ == "__main__":
    _configure_windows_app_identity()
    PDFViewer()
