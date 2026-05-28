# Regional IF Analyzer

A GUI tool for analyzing immunofluorescence images with atlas region mapping and automated cell counting.

**v8.02.000 Highlights**
- Major reliability overhaul of the Paint tool for custom regions:
  - Zones named immediately after drawing now correctly register for counting.
  - Count Cells auto-stops paint mode and converts all strokes (named + auto-default).
  - Full state wipe on every new image load (prevents cross-image leakage).
  - Durable model-coordinate storage so drawings survive zoom/pan.
  - Proper interior filling (`binary_fill_holes`) + neighborhood zone lookup → accurate counts inside hand-drawn structures.
  - No more duplicate zones in the spreadsheet.
- Critical stability fix: Closing the "Counting Cells" or "Detecting Cells" progress dialog early (X button) can no longer crash the application. All progress UI calls are now defensive.
- Continuing from v8.01: Modern Blob Detection (default), Smart Suggest (Offline), left File Browser with counted status, automatic dual export (`.xlsx` + `_masked.tif`), and portable settings.

**v8.01.000 Highlights** (previous major release)
- New modern Blob Detection engine (Laplacian of Gaussian) — significantly better results on most immunofluorescence images.
- "Smart Suggest (Offline)" — a fully local, privacy-preserving tool that analyzes your image and recommends better detection parameters (with checkbox selection).
- Live switching between Blob and legacy Watershed detection methods directly in Mask Settings.
- Left-side File Browser pane: Select a folder to see all TIFFs, double-click to load, and see which images have already been counted (✓ indicator).
- Automatic export on Count Cells: `{image}.xlsx` (with Cell Counts + full Detection Parameters metadata sheet) and `{image}_masked.tif` (original + red mask overlay).
- Export/Import full detection settings as portable .json files from Mask Settings.
- Improved Autotune buttons that adapt intelligently based on the active detection method.
- Brush Settings dialog now opens automatically when using Add/Remove Cell.

## Description

The Regional IF Analyzer is designed to help researchers analyze immunofluorescence images by:
- Overlaying atlas sections onto TIFF images
- Highlighting and naming specific regions of interest
- Detecting and counting cells within defined regions
- Automatic Excel + masked image export on Count Cells (with full parameter metadata)
- Saving annotated images

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package installer)
- tkinter (usually comes with Python, but may need separate installation on Linux)

On Ubuntu/Debian Linux, you might need to install tkinter separately:
```bash
sudo apt-get install python3-tk
```

### Setting Up

1. Clone the repository:
```bash
git clone https://github.com/LaingLab/BARCC.git
cd BARCC
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

**Note on Excel exports** (recommended):
Starting with v8.01 (refined in 8.02), clicking **Count Cells** automatically saves:
- `YourImage.xlsx` — Contains two sheets:
  - "Cell Counts" (per region)
  - "Detection Parameters" (complete record of every setting used — excellent for methods/reproducibility)
- `YourImage_masked.tif` — Original image with the final cell mask (including manual edits) as a semi-transparent red overlay.

For full `.xlsx` support, install the Excel engines:

```bash
pip install openpyxl xlsxwriter
```

Without them, BARCC falls back to a plain `.csv`.

## Running the Program

1. Navigate to the program directory:
```bash
cd Application
```

2. Run the program:
```bash
python Application/barcc.py
```

## Basic Usage

1. **Import TIFF Image**:
   - Click "File > Import TIFF"
   - Select your TIFF image file

2. **Determine Regions**

   a. *Draw Region of Interest*:
      - Click "Paint > Start Paint"
      - Draw a circle around the ROI
      - Once done, click "Paint > Stop Paint"
   
   b. *Import Atlas Section*:
      - Click "File > Import Atlas Section"
      - Select your PDF atlas file

3. **Align Atlas**:
   - Use "Move Atlas" button to position the atlas over your image
   - Use rotation and scaling controls if needed

4. **Define Regions**:
   - Click on regions to highlight them
   - Name each region when prompted

5. **Verify Mask**:
   - Click "Mask > Show Mask"
   - Adjust detection with "Mask > Show Mask Settings"
   - Manually add and remove cells under "Mask > Add/Remove Cells"

7. **Count Cells**:
   - Click "Count Cells" to analyze
   - Save results to Excel when prompted

## Common Issues

- If tkinter is missing: Install python3-tk package via your system's package manager
- If images don't load: Ensure your TIFF files are in a compatible format
- For PDF loading issues: Ensure PyMuPDF is properly installed

## Support

For issues and feature requests, please open an issue in the GitHub repository.

## License

