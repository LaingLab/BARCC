#!/usr/bin/env python3
"""
BARCC User Manual Generator
Generates a highly polished, professional PDF manual for the BARCC application.

Run this script from the docs/ directory (or with proper paths) to regenerate the manual.
"""

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from datetime import datetime
import os

# ============================================================================
# CONFIGURATION
# ============================================================================
MANUAL_TITLE = "BARCC - Brain Atlas Regional Cell Counter"
MANUAL_SUBTITLE = "User Manual"
VERSION = "8.00.000"
OUTPUT_FILENAME = "BARCC_User_Manual.pdf"
OUTPUT_DIR = ".."  # Place PDF in repository root


# Professional color scheme
ACCENT_COLOR = (13, 110, 253)       # Bootstrap blue
DARK_TEXT = (33, 37, 41)            # Near black
GRAY_TEXT = (108, 117, 125)         # Muted gray
LIGHT_BG = (248, 249, 250)          # Very light gray for table rows


class BARCCUserManual(FPDF):
    """Professional PDF generator with headers, footers, and polished styling."""

    def __init__(self):
        super().__init__(format="Letter")
        self.set_auto_page_break(auto=True, margin=22)
        self.alias_nb_pages()  # Enables {nb} in footers
        self.current_chapter = ""
        self.chapter_pages = {}  # For future TOC enhancements

    # ------------------------------------------------------------------
    # HEADER & FOOTER
    # ------------------------------------------------------------------
    def header(self):
        """Clean professional header shown on content pages."""
        if self.page_no() <= 2:  # No header on cover or TOC
            return

        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*ACCENT_COLOR)
        self.cell(0, 10, "BARCC User Manual", new_x=XPos.RIGHT, new_y=YPos.TOP, align="L")

        if self.current_chapter:
            self.set_font("Helvetica", "", 9)
            self.set_text_color(*GRAY_TEXT)
            self.cell(0, 10, self.current_chapter[:50], new_x=XPos.RIGHT, new_y=YPos.TOP, align="R")

        # Accent line under header
        self.set_draw_color(*ACCENT_COLOR)
        self.set_line_width(0.4)
        y = self.get_y() + 2
        self.line(25, y, 191, y)
        self.ln(8)

    def footer(self):
        """Professional footer with page numbers and copyright."""
        self.set_y(-18)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*GRAY_TEXT)

        # Left side - page number
        page_text = f"Page {self.page_no()} of {{nb}}"
        self.cell(0, 10, page_text, new_x=XPos.RIGHT, new_y=YPos.TOP, align="L")

        # Right side - copyright
        self.cell(0, 10, "(c) 2026 Laing Lab - BARCC", new_x=XPos.RIGHT, new_y=YPos.TOP, align="R")

    # ------------------------------------------------------------------
    # STYLED CONTENT HELPERS
    # ------------------------------------------------------------------
    def add_cover_page(self):
        """Create a clean, professional, well-balanced cover page."""
        self.add_page()
        page_width = self.w

        # Top accent bar
        self.set_fill_color(*ACCENT_COLOR)
        self.rect(0, 0, page_width, 7, "F")

        # --- Top section: USER MANUAL ---
        self.set_y(38)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*GRAY_TEXT)
        self.cell(0, 8, "USER MANUAL", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        # --- Big BARCC title ---
        self.set_y(52)
        self.set_font("Helvetica", "B", 42)
        self.set_text_color(*DARK_TEXT)
        self.cell(0, 18, "BARCC", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        # --- Subtitle ---
        self.set_y(72)
        self.set_font("Helvetica", "", 12)
        self.set_text_color(*ACCENT_COLOR)
        self.cell(0, 7, "Brain Atlas Regional Cell Counter", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        # Thin accent line
        self.ln(6)
        self.set_draw_color(*ACCENT_COLOR)
        self.set_line_width(0.6)
        x_center = page_width / 2
        self.line(x_center - 55, self.get_y(), x_center + 55, self.get_y())

        # --- Version + Date ---
        self.ln(8)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*GRAY_TEXT)
        self.cell(0, 6, f"Version {VERSION}   -   Generated {datetime.now().strftime('%B %d, %Y')}",
                  new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        # --- Description ---
        self.ln(22)
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*DARK_TEXT)
        desc = (
            "BARCC is a specialized GUI application for analyzing immunofluorescence images.\n"
            "It enables researchers to overlay brain atlas sections, define regions of interest,\n"
            "perform automated cell counting, and export quantitative results."
        )
        self.multi_cell(0, 5.8, desc, align="C")

        # --- Bottom section ---
        self.set_y(-48)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*GRAY_TEXT)
        self.cell(0, 6, "Laing Lab", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, "https://github.com/LaingLab/BARC", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        # Bottom accent bar
        self.set_y(-12)
        self.set_fill_color(*ACCENT_COLOR)
        self.rect(0, self.h - 12, page_width, 7, "F")

    def chapter_title(self, title: str, level: int = 0):
        """Add a styled chapter or section title."""
        self.current_chapter = title

        if level == 0:
            self.add_page()
            self.set_font("Helvetica", "B", 18)
            self.set_text_color(*ACCENT_COLOR)
            self.cell(0, 12, title, new_x=XPos.RIGHT, new_y=YPos.NEXT)
            # Underline
            self.set_draw_color(*ACCENT_COLOR)
            self.set_line_width(0.5)
            self.line(25, self.get_y(), 191, self.get_y())
            self.ln(6)
        elif level == 1:
            self.set_font("Helvetica", "B", 13)
            self.set_text_color(*DARK_TEXT)
            self.ln(4)
            self.cell(0, 8, title, new_x=XPos.RIGHT, new_y=YPos.NEXT)
            self.ln(1)
        else:
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(*DARK_TEXT)
            self.ln(3)
            self.cell(0, 7, title, new_x=XPos.RIGHT, new_y=YPos.NEXT)
            self.ln(1)

        self.set_text_color(*DARK_TEXT)
        self.set_font("Helvetica", "", 10.5)

    def body(self, text: str):
        """Standard body paragraph."""
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*DARK_TEXT)
        self.multi_cell(0, 5.8, text)
        self.ln(3)

    def bullet_list(self, items: list[str]):
        """Simple bullet list."""
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*DARK_TEXT)
        for item in items:
            self.set_x(30)
            self.multi_cell(0, 5.8, f"-  {item}")
            self.ln(0.5)
        self.ln(3)

    def add_table(self, headers: list, rows: list, col_widths: list = None):
        """Polished table with header styling."""
        self.set_font("Helvetica", "B", 10)
        self.set_fill_color(*ACCENT_COLOR)
        self.set_text_color(255, 255, 255)

        if col_widths is None:
            col_widths = [45] * len(headers)

        # Header row
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 7, header, border=1, fill=True, align="C")
        self.ln()

        # Data rows
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*DARK_TEXT)
        fill = False
        for row in rows:
            if fill:
                self.set_fill_color(*LIGHT_BG)
            else:
                self.set_fill_color(255, 255, 255)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6.5, str(cell), border=1, fill=fill, align="L")
            self.ln()
            fill = not fill

        self.ln(5)

    def note_box(self, text: str):
        """Highlighted note/callout box."""
        self.set_fill_color(232, 244, 253)  # Light blue
        self.set_draw_color(*ACCENT_COLOR)
        self.set_line_width(0.3)
        y_start = self.get_y()
        self.set_font("Helvetica", "B", 9.5)
        self.set_text_color(*ACCENT_COLOR)
        self.cell(0, 6, "  NOTE", new_x=XPos.RIGHT, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 9.5)
        self.set_text_color(*DARK_TEXT)
        self.set_x(25)
        self.multi_cell(166, 5.5, text)
        y_end = self.get_y()
        self.rect(25, y_start, 166, y_end - y_start, "D")
        self.ln(4)

    # ------------------------------------------------------------------
    # TABLE OF CONTENTS
    # ------------------------------------------------------------------
    def add_table_of_contents(self):
        """Professional Table of Contents."""
        self.add_page()
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(*DARK_TEXT)
        self.cell(0, 14, "Table of Contents", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")
        self.ln(8)

        toc_items = [
            ("1. Introduction", 3),
            ("2. Installation & Requirements", 4),
            ("3. Getting Started", 5),
            ("4. User Interface Overview", 6),
            ("5. File Menu", 7),
            ("6. Working with Atlas Sections", 8),
            ("7. Paint Tools for Regions of Interest", 10),
            ("8. Mask Settings & Cell Detection", 11),
            ("9. Manual Cell Editing", 14),
            ("10. Counting Cells & Exporting Results", 15),
            ("11. Saving & Export Options", 16),
            ("12. Keyboard Shortcuts", 17),
            ("13. Troubleshooting", 18),
        ]

        self.set_font("Helvetica", "", 11)
        for title, page in toc_items:
            self.set_text_color(*DARK_TEXT)
            self.cell(140, 7, title)
            self.set_text_color(*GRAY_TEXT)
            self.cell(0, 7, f"..... {page}", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="R")
            self.ln(1)

        self.ln(8)


# ============================================================================
# MANUAL CONTENT
# ============================================================================

def build_manual():
    pdf = BARCCUserManual()

    # Cover + TOC
    pdf.add_cover_page()
    pdf.add_table_of_contents()

    # ------------------------------------------------------------------
    # 1. INTRODUCTION
    # ------------------------------------------------------------------
    pdf.chapter_title("1. Introduction", 0)

    pdf.body(
        "BARCC (Brain Atlas Regional Cell Counter) is a specialized desktop application designed for "
        "researchers working with immunofluorescence (IF) microscopy images. It combines powerful "
        "image analysis tools with brain atlas registration to enable accurate, reproducible "
        "regional cell counting."
    )

    pdf.chapter_title("Purpose", 1)
    pdf.body(
        "The software allows users to overlay standardized atlas sections onto experimental TIFF images, "
        "define regions of interest through painting or atlas-based selection, apply sophisticated "
        "cell detection algorithms, and export quantitative results to Excel for further analysis."
    )

    pdf.chapter_title("Key Capabilities", 1)
    pdf.bullet_list([
        "Import and display high-resolution TIFF images and multi-page PDF atlas files",
        "Interactive atlas alignment (translation, rotation, scaling)",
        "Freehand painting tools to define custom regions of interest",
        "Advanced, configurable cell detection with multiple thresholding methods",
        "Manual addition and removal of cells for quality control",
        "Automated cell counting within defined regions with Excel export",
        "Saving of annotated images and analysis sessions"
    ])

    pdf.note_box(
        "BARCC is particularly valuable for neuroscience studies involving c-Fos, NeuN, or other "
        "cell-type specific markers where regional quantification relative to brain anatomy is required."
    )

    # ------------------------------------------------------------------
    # 2. INSTALLATION
    # ------------------------------------------------------------------
    pdf.chapter_title("2. Installation & Requirements", 0)

    pdf.chapter_title("System Requirements", 1)
    pdf.bullet_list([
        "Windows 10 or later (primary supported platform)",
        "Python 3.8 or higher",
        "At least 8 GB RAM recommended for large images"
    ])

    pdf.chapter_title("Installation Steps", 1)
    pdf.body("1. Clone the repository:")
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "git clone https://github.com/LaingLab/BARC.git\ncd BARCC")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10.5)
    pdf.body("2. Install dependencies:")
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "pip install -r requirements.txt")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10.5)
    pdf.body("3. Launch the application:")
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "cd Application\npython barcc.py")

    # ------------------------------------------------------------------
    # 3. GETTING STARTED
    # ------------------------------------------------------------------
    pdf.chapter_title("3. Getting Started", 0)

    pdf.body(
        "Upon launching BARCC you are presented with a large central canvas area and a menu bar across the top. "
        "The typical workflow follows these steps:"
    )

    pdf.bullet_list([
        "Import a TIFF image (File > Import TIFF)",
        "Import an atlas section PDF (File > Import Atlas Section)",
        "Align the atlas over your image using Move, Rotate, and Resize tools",
        "Define regions using either Paint tools or by clicking atlas regions",
        "Configure and preview cell detection parameters (Mask > Show Mask Settings)",
        "Run cell counting and review results",
        "Export data to Excel and save annotated images"
    ])

    # ------------------------------------------------------------------
    # 4. UI OVERVIEW
    # ------------------------------------------------------------------
    pdf.chapter_title("4. User Interface Overview", 0)

    pdf.body(
        "The interface is intentionally minimal to maximize screen real estate for image viewing. "
        "All functionality is accessed through the top menu bar."
    )

    pdf.chapter_title("Main Canvas", 1)
    pdf.body(
        "The large central area displays your experimental image with the atlas overlay on top. "
        "You can pan using the scrollbars. Use the mouse wheel to zoom in and out. Zoom is centered "
        "on the mouse cursor and keeps painted regions, atlas overlays, and masks perfectly aligned "
        "with the background image at all zoom levels. When viewing cell masks (manual or automatic), "
        "a split view may appear for comparison."
    )

    pdf.chapter_title("Menus", 1)
    pdf.body(
        "File, Edit, Atlas, Paint, Mask, and Cell menus provide access to all features. "
        "Many operations also open small auxiliary windows for parameter adjustment."
    )

    # ------------------------------------------------------------------
    # 5. FILE MENU
    # ------------------------------------------------------------------
    pdf.chapter_title("5. File Menu", 0)

    pdf.chapter_title("Import TIFF", 1)
    pdf.body(
        "Loads the primary experimental image. Supported formats include single and multi-page TIFFs. "
        "After import, the image is automatically scaled to fit the window while preserving aspect ratio."
    )

    pdf.chapter_title("Import Atlas Section", 1)
    pdf.body(
        "Opens a PDF file containing brain atlas plates. BARCC uses PyMuPDF to render individual pages "
        "at high quality. You can navigate between pages of multi-plate PDFs."
    )

    pdf.chapter_title("Split Tiff", 1)
    pdf.body(
        "Utility for breaking apart stacked (multi-page) TIFF files into individual images. "
        "Useful when your source data contains multiple sections in one file."
    )

    pdf.chapter_title("Save Flattened Image", 1)
    pdf.body(
        "Exports a composite image containing both the original TIFF and the currently aligned atlas "
        "as a single JPEG. This is useful for figure preparation and record keeping."
    )

    pdf.chapter_title("Save Paint", 1)
    pdf.body("Saves freehand painted regions to a reusable file format for later sessions.")

    # ------------------------------------------------------------------
    # 6. ATLAS HANDLING
    # ------------------------------------------------------------------
    pdf.chapter_title("6. Working with Atlas Sections", 0)

    pdf.body(
        "Accurate alignment of the atlas to your experimental image is critical for meaningful "
        "regional analysis. BARCC provides several interactive tools for this purpose."
    )

    pdf.chapter_title("Move Atlas", 1)
    pdf.body(
        "Click and drag the atlas overlay to reposition it over the underlying image. "
        "This is the primary tool for coarse alignment."
    )

    pdf.chapter_title("Rotate", 1)
    pdf.body(
        "Enter a rotation angle in degrees and apply it. Positive values rotate clockwise. "
        "Useful for correcting slight angular differences between your sectioning plane and the atlas."
    )

    pdf.chapter_title("Resize / Scale", 1)
    pdf.body(
        "Apply uniform or axis-specific scaling. The Scale dialog also provides fine X and Y "
        "adjustment sliders for precise matching of anatomical landmarks."
    )

    pdf.chapter_title("Brightness & Contrast Adjustments", 1)
    pdf.body(
        "The atlas rendering can be lightened or darkened independently of the experimental image "
        "to improve visibility of boundaries during alignment."
    )

    pdf.note_box(
        "Best practice: Identify 3-4 reliable anatomical landmarks (e.g., ventricles, major fiber tracts, "
        "cortical boundaries) and align to those rather than trying to match the entire section at once."
    )

    # ------------------------------------------------------------------
    # 7. PAINT TOOLS
    # ------------------------------------------------------------------
    pdf.chapter_title("7. Paint Tools for Regions of Interest", 0)

    pdf.body(
        "When the standard atlas regions do not match your experimental needs, the Paint tools "
        "allow completely custom region definition."
    )

    pdf.chapter_title("Start / Stop Paint", 1)
    pdf.body("Activates freehand drawing mode. Draw directly on the image with the mouse.")

    pdf.chapter_title("Pen vs Eraser", 1)
    pdf.body(
        "Switch between adding area (Pen) and removing area (Eraser). Brush size is adjustable "
        "via the Brushsize dialog."
    )

    pdf.chapter_title("Import / Save Paint", 1)
    pdf.body(
        "Painted regions can be saved and reloaded in future sessions, enabling consistent "
        "analysis across multiple images or experiments."
    )

    pdf.chapter_title("Labeling Painted Regions", 1)
    pdf.body(
        "While in Paint mode (before clicking Stop Paint), you can right-click on any painted stroke "
        "to name it. BARCC treats each continuous drawing action (mouse button down through release) "
        "as a single \"structural boundary.\" All connected line segments belonging to that stroke "
        "are grouped together."
    )
    pdf.body(
        "When you right-click a stroke:"
    )
    pdf.bullet_list([
        "The entire connected group is highlighted in yellow for visual feedback.",
        "A dialog appears allowing you to enter or edit a name for the region.",
        "Named painted regions are converted into proper analysis zones when you click Stop Paint.",
        "These named regions participate in cell counting exactly like atlas regions and will appear in your results with the names you assigned."
    ])
    pdf.note_box(
        "You can only label painted regions while the Paint mode is active (i.e., before you click "
        "\"Stop Paint\"). Once you stop painting, the strokes are committed to the persistent paint layer "
        "and the live canvas items used for naming are cleaned up."
    )

    # ------------------------------------------------------------------
    # 8. MASK SETTINGS (DETAILED)
    # ------------------------------------------------------------------
    pdf.chapter_title("8. Mask Settings & Cell Detection", 0)

    pdf.body(
        "This is the most powerful and configurable part of BARCC. The Mask Settings dialog "
        "provides fine-grained control over every stage of the cell detection pipeline."
    )

    pdf.chapter_title("Threshold Methods", 1)
    pdf.body(
        "The Threshold Method controls how the image is converted to a binary (black and white) "
        "mask for cell detection. Four options are available:"
    )

    pdf.bullet_list([
        "Otsu: Automatically determines the optimal global threshold using Otsu's method. Fast and effective on images with good contrast.",
        "Adaptive: Uses local areas to determine the threshold. Excellent for images with varying brightness across the field of view.",
        "Local: Similar to Adaptive but uses a different neighborhood computation. Useful when Adaptive produces too many or too few detections.",
        "Manual: Uses a fixed threshold value (0.0-1.0) that you specify. Provides maximum reproducibility across batches of images."
    ])

    pdf.chapter_title("Cell Detection Parameters", 1)

    pdf.body(
        "These parameters control how individual cells are identified from the binary mask:"
    )

    pdf.chapter_title("Manual Threshold", 2)
    pdf.body(
        "Range: 0.0 to 1.0. Only used when Threshold Method is \"manual\". "
        "Higher values make detection more selective (fewer cells). Lower values increase sensitivity."
    )

    pdf.chapter_title("Adaptive Block Size", 2)
    pdf.body(
        "Must be an odd integer (e.g. 51, 101, 151). Size of the local region used for adaptive thresholding. "
        "Larger values consider more surrounding area. Smaller values are more sensitive to local changes. "
        "Recommended range: 51-151 pixels."
    )

    pdf.chapter_title("Local Radius", 2)
    pdf.body(
        "Integer value (typically 5-30). Size of the neighborhood for the Local threshold method. "
        "Larger values smooth noise but may miss smaller cells."
    )

    pdf.chapter_title("Min Cell Size / Max Cell Size", 2)
    pdf.body(
        "Integer values in pixels. Define the acceptable size range for an object to be counted as a cell. "
        "Min Cell Size filters noise and small artifacts. Max Cell Size excludes clumps. "
        "Typical values depend on magnification (e.g. Min 20, Max 100-200)."
    )

    pdf.chapter_title("Circularity Threshold", 2)
    pdf.body(
        "Range: 0.0 to 1.0. How circular a region must be to be accepted as a cell (1.0 = perfect circle). "
        "Higher values enforce rounder shapes. Typical value: 0.7."
    )

    pdf.chapter_title("Min Peak Distance", 2)
    pdf.body(
        "Integer value (pixels). Minimum distance required between detected cell centers. "
        "Helps prevent over-counting of touching cells. Typical values: 5-10 pixels."
    )

    pdf.chapter_title("Peak Min Intensity", 2)
    pdf.body(
        "Range: 0.0 to 1.0. Minimum brightness required for a local maximum to be considered a cell center. "
        "Higher values detect only brighter cells. Lower values detect dimmer cells. Typical starting value: 0.1."
    )

    pdf.chapter_title("Watershed Compactness", 2)
    pdf.body(
        "Range: 0.0 to 1.0. Controls how the watershed algorithm separates touching cells. "
        "Higher values favor more compact, rounder boundaries. Lower values follow intensity gradients more closely. "
        "Typical value: 0.0."
    )

    pdf.chapter_title("Base Multiplier & Sensitivity Range", 2)
    pdf.body(
        "Advanced sensitivity controls. Base Multiplier sets overall detection sensitivity (default ~1.1). "
        "Sensitivity Range controls how much the sensitivity slider can influence results (default 0.2)."
    )

    pdf.chapter_title("Preprocessing Pipeline", 1)
    pdf.body(
        "A full preprocessing chain can be applied before cell detection. Each step can be enabled "
        "or disabled independently. The dialog only shows parameters relevant to the selected methods."
    )

    pdf.chapter_title("Background Method", 2)
    pdf.body(
        "Options: tophat or none. Controls removal of large-scale background variations. "
        "Tophat uses morphological operations and is generally recommended. When enabled, the Ball Radius "
        "(structural element size, default 15) controls how large-scale the background variations removed are."
    )

    pdf.chapter_title("Denoise Method", 2)
    pdf.body(
        "Options: gaussian, median, bilateral, or none. Reduces noise before detection."
    )
    pdf.bullet_list([
        "Gaussian: Applies a Gaussian blur (controlled by Gaussian Sigma, typically 0.1-5.0).",
        "Median: Better at preserving edges (controlled by Median Kernel size).",
        "Bilateral: Preserves edges while smoothing (controlled by Bilateral Sigma Color and Bilateral Sigma Space)."
    ])

    pdf.chapter_title("Contrast Method", 2)
    pdf.body(
        "Options: stretch, clahe, gamma, or none. Enhances contrast before detection."
    )
    pdf.bullet_list([
        "Stretch: Simple linear contrast stretching.",
        "CLAHE (Contrast Limited Adaptive Histogram Equalization): Local contrast enhancement. Controlled by CLAHE Kernel (typically 8-16) and CLAHE Clip Limit (typically 1.0-4.0).",
        "Gamma: Gamma correction. Values < 1 brighten the image; values > 1 darken it."
    ])

    pdf.chapter_title("Enhance Method", 2)
    pdf.body(
        "Currently supports Unsharp Mask sharpening. Controlled by Unsharp Radius (typically 0.1-5.0) "
        "and Unsharp Amount (strength of sharpening, typically 0.1-5.0). Useful for making cell boundaries crisper."
    )

    pdf.body(
        "Both manual mask editing overlays (red) and automatic cell detection masks remain visible "
        "and correctly aligned when you zoom in or out using the mouse wheel."
    )

    pdf.note_box(
        "Start with the default settings and adjust one parameter at a time while using "
        "\"Show Mask\" to preview the binary detection result. This iterative approach is the fastest "
        "way to obtain high-quality cell counts."
    )

    pdf.chapter_title("Autotune Panel", 1)
    pdf.body(
        "The Mask Settings dialog includes a convenient Autotune panel with one-click adjustments "
        "for common goals. These buttons modify the live detection parameters and immediately "
        "reflect in the UI. When you click \"Show Mask,\" the detection will use the updated values."
    )

    pdf.body("The available Autotune buttons are:")
    pdf.bullet_list([
        "More cells - Increases detection sensitivity (lowers size/intensity/circularity thresholds).",
        "Less cells - Decreases detection sensitivity (raises thresholds).",
        "Bigger cells - Favors larger objects by raising min/max cell size and compactness.",
        "Smaller cells - Favors smaller objects by lowering size thresholds.",
        "Brighter cells - Only detects stronger signals by raising peak intensity threshold.",
        "Dimmer cells - Detects weaker signals by lowering peak intensity threshold."
    ])
    pdf.body(
        "You can click any button multiple times for a stronger effect. The changes are applied "
        "to the current configuration and will be used the next time cell detection runs (via "
        "\"Show Mask\" or \"Count Cells\")."
    )

    # ------------------------------------------------------------------
    # 9. MANUAL CELL EDITING
    # ------------------------------------------------------------------
    pdf.chapter_title("9. Manual Cell Editing", 0)

    pdf.body(
        "No automated detector is perfect. BARCC provides direct manual editing tools so you can "
        "correct errors before counting."
    )

    pdf.chapter_title("Add / Remove Cells", 1)
    pdf.bullet_list([
        "Add Cell - Click or paint to mark additional cells that the detector missed.",
        "Remove Cell - Erase false positives (dust, autofluorescence, etc.).",
        "Brush Size - Adjustable via the Brushsize control in the Paint menu."
    ])

    pdf.body(
        "Edits are applied to a separate overlay mask and can be toggled on and off for comparison. "
        "All manual edits are included in the final cell count."
    )

    # ------------------------------------------------------------------
    # 10. COUNTING & RESULTS
    # ------------------------------------------------------------------
    pdf.chapter_title("10. Counting Cells & Exporting Results", 0)

    pdf.body(
        "Once regions are defined and detection parameters are tuned, click \"Count Cells\" "
        "under the Cell menu."
    )

    pdf.body(
        "BARCC will compute the number of detected cells within each named region and present "
        "a summary. You will be prompted to save the results as an Excel (.xlsx) file containing:"
    )

    pdf.bullet_list([
        "Region name",
        "Cell count",
        "Region area (pixels)",
        "Cell density (if applicable)"
    ])

    pdf.body(
        "The Excel file is the primary deliverable for statistical analysis and figure preparation."
    )

    # ------------------------------------------------------------------
    # 11. SAVING
    # ------------------------------------------------------------------
    pdf.chapter_title("11. Saving & Export Options", 0)

    pdf.bullet_list([
        "Flattened Image (JPEG) - Final figure-ready composite of image + atlas + annotations",
        "Paint files - Reusable region definitions",
        "Excel results - Quantitative data for downstream analysis"
    ])

    # ------------------------------------------------------------------
    # 12. HOTKEYS
    # ------------------------------------------------------------------
    pdf.chapter_title("12. Keyboard Shortcuts", 0)

    headers = ["Shortcut", "Action"]
    rows = [
        ["Ctrl + Z", "Undo last action (move, rotate, paint, highlight, etc.)"],
        ["Ctrl + S", "Save flattened image"],
    ]
    pdf.add_table(headers, rows, col_widths=[50, 130])

    # ------------------------------------------------------------------
    # 13. TROUBLESHOOTING
    # ------------------------------------------------------------------
    pdf.chapter_title("13. Troubleshooting", 0)

    pdf.chapter_title("Common Issues", 1)

    pdf.body("- Cells not detected: Try lowering Peak Min Intensity or switching to Adaptive threshold.")
    pdf.body("- Too many false positives: Increase Min Cell Size and Circularity Threshold.")
    pdf.body("- Atlas looks blurry: Re-render at higher zoom or adjust brightness settings.")
    pdf.body("- Performance is slow: Close other applications; very large images benefit from 16 GB+ RAM.")

    pdf.chapter_title("Getting Help", 1)
    pdf.body(
        "For bugs or feature requests, please open an issue on the GitHub repository:\n"
        "https://github.com/LaingLab/BARC"
    )

    # Final page
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*ACCENT_COLOR)
    pdf.cell(0, 20, "Thank you for using BARCC", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*DARK_TEXT)
    pdf.ln(10)
    pdf.multi_cell(0, 6, "We hope this software accelerates your research. Feedback and contributions are always welcome.", align="C")

    # Save the PDF
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)
    pdf.output(output_path)
    print("Professional manual generated successfully: " + os.path.abspath(output_path))
    return output_path


if __name__ == "__main__":
    build_manual()
