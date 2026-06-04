# Regional IF Analyzer

A GUI tool for analyzing immunofluorescence images with atlas region mapping and automated cell counting.

**v8.02.002 Highlights** (current patch)
- Fixed mismatch between zone counts shown on the mask/image (yellow labels and visible red cell markers) and the numbers in the exported spreadsheet ("Cell Counts" sheet).
  - Root cause: Unconditional application of `img_x`/`img_y` atlas overlay offset when mapping detected cell centroids (from the main experimental image / final cell mask) into the zone mask for counting, and when positioning zone labels in `show_page`.
  - This affected painted regions (which live in the background TIFF's 0,0-aligned coordinate space) whenever the atlas overlay had been panned, zoomed, or shifted (non-zero `img_x`/`img_y`), causing cells to be assigned to wrong zones (or none) in the DataFrame used for both the spreadsheet and `last_df`.
  - Visual cell markers were drawn at correct positions, leading to "I see 30 cells in the painted region but spreadsheet says 12" (or vice versa).
- Implemented size-based heuristic in `count_cells_in_zones` and the zone label drawing code:
  - If the zone mask size closely matches the main `background_image` / cell mask size (paint regions on TIFF, or standalone), use direct coordinates (offset 0) for accurate assignment and label placement over the background layer.
  - If sizes differ (atlas/PDF overlay), fall back to previous `img_x`/`img_y` offset logic for layer alignment.
- This ensures the counts reported in the spreadsheet exactly match what the user sees visually in each region on the annotated image and on-screen labels (after re-running Count Cells).
- No impact on pure atlas workflows or when no overlay offset is present.
- Version in exported settings JSON updated to "8.02.002".

**v8.02.001 Highlights** (previous)
- Final Paint tool reliability fixes so the primary workflow ("draw region, right-click name immediately, click Count Cells") succeeds on the *very first attempt* after loading any image:
  - Fixed a case where the first named painted region would be lost ("No Regions Defined" error) while a second region drawn afterward would appear in the spreadsheet.
  - Root cause was an unconditional reset of `zone_names` / `mask_images` / `zone_counters` inside `load_page_image` the first time `atlas_filetype='img'` (baked paint) was activated during `stop_paint`'s `show_page`. Guarded so only PDF atlas pages perform per-page zone resets; paint zones now survive the internal bake-to-img path.
  - Additional hardening in the named conversion, stop, and count paths (broader durable data collection, conditional dtag, pre-clear re-tries, ultimate force before the error guard) to guarantee `paint_group_data` model points always produce registered zones.
- Brightness Settings dialog (the live slider) X button (titlebar close) now works and closes the window. Same fix applied for consistency to Brush Size, Scale, and Rotate settings dialogs. (Progress dialogs remain intentionally hardened against early close.)
- All v8.02.000 Paint guarantees (immediate naming, auto-stop on Count, durable geometry, interior `binary_fill_holes` fill, no dups, full cross-image wipe, auto Save Paint Layer to File Browser dir, etc.) now apply even to the first painted region.
- Version recorded in exported settings JSON is now "8.02.001".

**v8.02.000 Highlights** (previous)
- Major reliability overhaul of the Paint tool for custom regions:
  - Zones named immediately after drawing now correctly register for counting.
  - Count Cells auto-stops paint mode and converts all strokes (named + auto-default).
  - Full state wipe on every new image load (prevents cross-image leakage).
  - Durable model-coordinate storage so drawings survive zoom/pan.
  - Proper interior filling (`binary_fill_holes`) + neighborhood zone lookup → accurate counts inside hand-drawn structures.
  - No more duplicate zones in the spreadsheet.
- Paint menu improvements:
  - "Save Paint" moved from File menu to Paint menu and renamed **Save Paint Layer**.
  - New **Load Paint** command added to the Paint menu.
  - Save Paint Layer now **auto-saves** directly into the folder currently open in the left File Browser (smart unique naming, no dialog). The file list refreshes automatically.
  - Load Paint and Import Paint default to the current left File Browser directory.
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
      - Use "Paint > Save Paint Layer" to auto-save the paint into your current left File Browser folder (or "Load Paint" to reload one).
   
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

