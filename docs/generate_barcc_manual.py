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
VERSION = "8.01.000"
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

    def _safe_text(self, text):
        """Replace Unicode characters that Helvetica doesn't support."""
        replacements = {
            '\u2014': '-',      # em dash —
            '\u2013': '-',      # en dash –
            '\u201c': '"',      # left double quote “
            '\u201d': '"',      # right double quote ”
            '\u2018': "'",      # left single quote ‘
            '\u2019': "'",      # right single quote ’
            '\u2026': '...',    # ellipsis …
            '\u00a0': ' ',      # non-breaking space
            '\u2713': '[x]',    # check mark ✓
            '\u2714': '[x]',    # heavy check mark ✔
            '\u2022': '-',      # bullet •
            '\u2010': '-',      # hyphen
            '\u2011': '-',      # non-breaking hyphen
            '\u2012': '-',      # figure dash
            '\u2043': '-',      # hyphen bullet
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text

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
            self.cell(0, 10, self._safe_text(self.current_chapter[:50]), new_x=XPos.RIGHT, new_y=YPos.TOP, align="R")

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
        self.cell(0, 10, self._safe_text("(c) 2026 Laing Lab - BARCC"), new_x=XPos.RIGHT, new_y=YPos.TOP, align="R")

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
        self.cell(0, 5, "https://github.com/LaingLab/BARCC", new_x=XPos.RIGHT, new_y=YPos.NEXT, align="C")

        # Bottom accent bar
        self.set_y(-12)
        self.set_fill_color(*ACCENT_COLOR)
        self.rect(0, self.h - 12, page_width, 7, "F")

    def chapter_title(self, title: str, level: int = 0):
        """Add a styled chapter or section title."""
        safe_title = self._safe_text(title)
        self.current_chapter = safe_title

        if level == 0:
            self.add_page()
            self.set_font("Helvetica", "B", 18)
            self.set_text_color(*ACCENT_COLOR)
            self.cell(0, 12, safe_title, new_x=XPos.RIGHT, new_y=YPos.NEXT)
            # Underline
            self.set_draw_color(*ACCENT_COLOR)
            self.set_line_width(0.5)
            self.line(25, self.get_y(), 191, self.get_y())
            self.ln(6)
        elif level == 1:
            self.set_font("Helvetica", "B", 13)
            self.set_text_color(*DARK_TEXT)
            self.ln(4)
            self.cell(0, 8, safe_title, new_x=XPos.RIGHT, new_y=YPos.NEXT)
            self.ln(1)
        else:
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(*DARK_TEXT)
            self.ln(3)
            self.cell(0, 7, safe_title, new_x=XPos.RIGHT, new_y=YPos.NEXT)
            self.ln(1)

        self.set_text_color(*DARK_TEXT)
        self.set_font("Helvetica", "", 10.5)

    def body(self, text: str):
        """Standard body paragraph."""
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*DARK_TEXT)
        self.set_x(25)  # Ensure safe left margin
        self.multi_cell(0, 5.8, self._safe_text(text))
        self.ln(3)

    def bullet_list(self, items: list[str]):
        """Simple bullet list."""
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*DARK_TEXT)
        for item in items:
            self.set_x(30)
            self.multi_cell(0, 5.8, f"-  {self._safe_text(item)}")
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
        self.multi_cell(166, 5.5, self._safe_text(text))
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
    pdf.chapter_title("What's New in Version 8.01.000", 0)

    pdf.body(
        "BARCC 8.01 introduces major improvements to the cell detection system and parameter tuning workflow:"
    )

    pdf.bullet_list([
        "New default detection engine based on Laplacian-of-Gaussian (blob_log) blob detection. This method is significantly more robust on typical immunofluorescence images than the previous watershed approach.",
        "Full set of Blob Detection parameters now exposed in Mask Settings with live preview.",
        "New \"Smart Suggest (Offline)\" button — a completely local analysis tool that examines your image and current detections and recommends better parameter values. No data is ever transmitted.",
        "Ability to instantly switch between the new Blob method and the legacy Watershed method.",
        "Autotune buttons now intelligently adapt their adjustments depending on the active detection method.",
        "When using Add Cell or Remove Cell, the Brush Settings dialog now opens automatically for immediate size control."
    ])

    pdf.body(
        "These changes dramatically improve the experience of tuning detection parameters for difficult or variable images."
    )

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
    pdf.multi_cell(0, 5, "git clone https://github.com/LaingLab/BARCC.git\ncd BARCC")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10.5)
    pdf.body("2. Install dependencies:")
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "pip install -r requirements.txt")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.body(
        "For full .xlsx export support (including the Detection Parameters metadata sheet) and the _masked.tif "
        "feature, also install the Excel engines:"
    )
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "pip install openpyxl xlsxwriter")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10.5)
    pdf.body(
        "For the best experience with automatic Excel exports (including a second sheet with all "
        "detection parameters), we also recommend installing the Excel engines:"
    )
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "pip install openpyxl xlsxwriter")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.body(
        "If these packages are missing, BARCC will automatically fall back to saving results as a "
        "plain .csv file instead of .xlsx. These packages are listed as recommended (but not strictly required) "
        "in the project's requirements.txt."
    )
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
        "The main interface consists of a left file browser pane and a large central image canvas. "
        "The left pane lets you select a folder and browse all TIFF images within it. Double-clicking "
        "any file loads it as the active image. A checkmark column shows which images have already "
        "been counted (based on the presence of matching .csv or .xlsx result files)."
    )

    pdf.body(
        "All other functionality is accessed through the top menu bar. The interface is designed "
        "to keep as much screen space as possible available for the image and mask visualization."
    )

    pdf.chapter_title("Main Canvas", 1)
    pdf.body(
        "The large central area displays your experimental image with the atlas overlay on top (when loaded). "
        "You can pan using the scrollbars or Alt+drag. Use the mouse wheel to zoom in and out. Zoom is centered "
        "on the mouse cursor and keeps painted regions, atlas overlays, and masks perfectly aligned "
        "with the background image at all zoom levels."
    )

    pdf.chapter_title("Menus", 1)
    pdf.body(
        "File, Edit, Atlas, Paint, Mask, and Cell menus provide access to all features. "
        "Many operations (especially in Mask Settings) open auxiliary dialogs for parameter adjustment."
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

    pdf.chapter_title("File Browser (Left Pane)", 1)
    pdf.body(
        "BARCC v8.01 introduced a dedicated file manager pane on the left side of the main window. "
        "This makes it much easier to work with folders containing many TIFF images."
    )

    pdf.body(
        "Click the \"Select Folder\" button at the top of the left pane to choose a directory. "
        "BARCC will scan the folder and display all .tif and .tiff files in a list. "
        "Double-click any file in the list to load it as the active working image."
    )

    pdf.body(
        "A second column in the list displays a checkmark (✓) next to any image that has already been processed. "
        "This checkmark appears automatically if a matching .csv or .xlsx results file (generated by Count Cells) "
        "exists in the same folder. This is very useful for tracking which images in a large dataset have already been counted."
    )

    pdf.body(
        "The Refresh button rescans the current folder. This is useful if you add or remove files while BARCC is running."
    )

    pdf.note_box(
        "The File Browser works independently of the traditional \"File > Import TIFF\" menu. "
        "You can still use the menu for one-off files, but the left pane is much faster when working with a whole folder of images."
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
        "provides fine-grained control over cell detection. BARCC v8.01+ supports two different "
        "detection strategies that you can switch between at any time:"
    )

    pdf.bullet_list([
        "Blob Detection (Recommended): Uses modern Laplacian-of-Gaussian (blob_log) blob detection. Generally provides the best results on immunofluorescence images with variably bright cells.",
        "Watershed (Legacy): The original threshold + distance transform + watershed pipeline. Retained for compatibility with older workflows."
    ])

    pdf.body(
        "You can switch between these two methods at any time using the radio buttons at the bottom "
        "of the Mask Settings dialog. Most users should use the Blob method for new work."
    )

    pdf.note_box(
        "A powerful new feature in v8.01 is the \"Smart Suggest (Offline)\" button. "
        "This fully local tool analyzes your current image and detection results and suggests "
        "better parameter values. No data ever leaves your computer."
    )

    pdf.chapter_title("Detection Method", 1)
    pdf.body(
        "At the bottom of the Mask Settings dialog you will find a clear choice between two detection engines:"
    )

    pdf.bullet_list([
        "Blob (new/recommended): Modern multi-scale blob detection using Laplacian of Gaussian. Much more robust for typical fluorescent cell images.",
        "Watershed (legacy): The original method based on global/local thresholding followed by watershed segmentation."
    ])

    pdf.body(
        "When Blob is selected, the lower part of the dialog shows the Blob Detection parameters. "
        "When Watershed is selected, the legacy Watershed parameters are shown instead."
    )

    pdf.chapter_title("Blob Detection Parameters (Recommended)", 1)
    pdf.body(
        "These parameters control the modern blob-based detector:"
    )

    pdf.chapter_title("Blob Threshold", 2)
    pdf.body(
        "The most important sensitivity control. Lower values detect more (and dimmer) cells but increase false positives. "
        "Higher values are more conservative. Typical useful range: 0.05 – 0.20."
    )

    pdf.chapter_title("Blob Min / Max Sigma", 2)
    pdf.body(
        "Controls the range of cell sizes the detector will look for. Min Sigma sets the smallest detectable feature size; Max Sigma sets the largest. "
        "For most immunofluorescence nuclei, Min Sigma around 1.5–3.0 and Max Sigma around 7–12 works well."
    )

    pdf.chapter_title("Blob Num Sigma", 2)
    pdf.body(
        "Number of scales tested between Min and Max Sigma. Higher values give finer granularity at the cost of speed. Default (12) is usually sufficient."
    )

    pdf.chapter_title("Blob Overlap", 2)
    pdf.body(
        "How much overlap is allowed between nearby blobs. Lower values reduce duplicate detections on clustered cells."
    )

    pdf.chapter_title("Blob Min / Max Area", 2)
    pdf.body(
        "Post-detection filters based on area (in pixels). Very effective at removing tiny noise blobs or huge clumps."
    )

    pdf.chapter_title("Blob Min Circularity", 2)
    pdf.body(
        "Requires detected blobs to be reasonably round. Raising this value helps reject irregular artifacts."
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
        "The Mask Settings dialog includes a convenient Autotune panel with one-click adjustments. "
        "These buttons intelligently adapt their behavior depending on whether you are using the "
        "Blob or Watershed detection method."
    )

    pdf.body("The available Autotune buttons are:")
    pdf.bullet_list([
        "More cells - Increases overall sensitivity. With Blob mode this primarily lowers the Blob Threshold and Min Sigma.",
        "Less cells - Decreases sensitivity and raises size/shape requirements.",
        "Bigger cells / Smaller cells - Adjust size-related parameters (Min/Max Area or Min/Max Cell Size).",
        "Brighter cells / Dimmer cells - Primarily adjust intensity sensitivity (Blob Threshold or Peak Min Intensity)."
    ])

    pdf.body(
        "Note: The Autotune buttons are intentionally conservative. For best results on difficult images, "
        "use the new \"Smart Suggest (Offline)\" button instead (see below)."
    )

    pdf.chapter_title("Export / Import Settings", 1)
    pdf.body(
        "You can now export your current detection and preprocessing settings as a portable .json file. "
        "This is useful for backing up configurations, sharing them with colleagues, or moving them between computers."
    )

    pdf.body(
        "In the Mask Settings dialog, use the buttons at the bottom:"
    )
    pdf.bullet_list([
        "\"Export Settings...\" — Saves your current Blob (or Watershed) configuration and preprocessing settings to a .json file of your choice.",
        "\"Import Settings...\" — Loads a previously exported .json file and applies all parameters immediately."
    ])

    pdf.body(
        "This is separate from the internal Presets system (which stores quick named presets locally in ~/.barc/presets.json)."
    )

    pdf.chapter_title("Smart Suggest (Offline) – New in v8.01", 1)
    pdf.body(
        "This is one of the most powerful new features in BARCC 8.01. Clicking \"Smart Suggest (Offline)\" "
        "runs a fully local analysis on your current image and detection results. It then proposes specific "
        "parameter improvements with clear explanations for each suggestion."
    )

    pdf.bullet_list([
        "Everything runs 100% on your computer — no images or data are sent anywhere.",
        "Each suggestion has a checkbox. You can selectively choose which changes to apply.",
        "Buttons at the bottom allow you to \"Apply All\", \"Apply All That Are Checked\", or simply \"Close\".",
        "It works with both Blob and Watershed modes and gives context-aware advice based on your actual data."
    ])

    pdf.body(
        "This tool is especially useful when the simple Autotune buttons are too aggressive or not aggressive enough. "
        "It is the recommended way to get good starting parameters for new or difficult images."
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
        "Brush Size - When you activate Add Cell or Remove Cell, the Brush Settings dialog now opens automatically so you can immediately adjust dot size."
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
        "BARCC will compute the number of detected cells within each named region. "
        "Results are now saved **automatically** (no file dialog) with the following files created in the same folder as your source TIFF:"
    )

    pdf.bullet_list([
        "`YourImage.xlsx` — Excel workbook with two sheets:",
        "    • Cell Counts — Region name, cell count, area, density, etc.",
        "    • Detection Parameters — Complete record of every setting used (both cell detection and preprocessing). This is extremely useful for reproducibility and methods sections.",
        "`YourImage_masked.tif` — The original image with the final cell mask (including any manual Add/Remove edits) drawn as a semi-transparent red overlay. Ready for figures or further analysis."
    ])

    pdf.body(
        "BARCC automatically saves two files when you click Count Cells (no manual Save dialog):"
    )

    pdf.bullet_list([
        "`YourImage.xlsx` — Contains two sheets: \"Cell Counts\" (the actual results) and \"Detection Parameters\" (a complete record of every setting used for reproducibility).",
        "`YourImage_masked.tif` — The original image with the final cell mask (after all manual Add/Remove edits) drawn as a semi-transparent red overlay. This is very useful for figure preparation."
    ])

    pdf.body(
        "To generate the .xlsx file (instead of falling back to .csv), the following packages are required:"
    )

    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(0, 5, "pip install openpyxl xlsxwriter")
    pdf.set_font("Helvetica", "", 10.5)

    pdf.body(
        "These are listed as recommended (but not strictly required) in the project's requirements.txt. "
        "Without them, results are saved as a plain CSV file."
    )

    # ------------------------------------------------------------------
    # 11. SAVING
    # ------------------------------------------------------------------
    pdf.chapter_title("11. Saving & Export Options", 0)

    pdf.bullet_list([
        "Flattened Image (JPEG) - Final figure-ready composite of image + atlas + annotations",
        "Paint files - Reusable region definitions",
        "Automatic Excel export on Count Cells (with full Detection Parameters metadata sheet)",
        "Automatic _masked.tif export (original image + final cell mask overlay)"
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
        "https://github.com/LaingLab/BARCC"
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
