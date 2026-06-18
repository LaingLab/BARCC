# Regional IF Analyzer

A GUI tool for analyzing immunofluorescence images with atlas region mapping and automated cell counting.

**v8.05.000 Highlights** (current)
- **Critical fixes for Paint bundles + Count Cells on .tiff**:
  - Fixed "failed to load paint bundle: ufunc 'less' did not contain a loop with signature matching types (UInt8DType...)" when loading a .barccpaint (with labeled painted regions) onto a .tiff. Root cause was JSON stringifying zone ID keys + uint8 label values from zones.png leading to type-mismatched comparisons inside `_populate_region_list` / `sorted` / ribbon updates after bundle load.
  - Fixed silent "crash" on Count Cells after loading painted regions from bundle: no dialog shown, no .xlsx generated. Caused by uncaught numpy broadcast errors in cell marker viz drawing (edge/1px cases after window-fit scaling), progress dialog close timing vs results popups, and missing user feedback when directory state was slightly off in browser flows.
  - Painted region load + name/shape restore + counting now works reliably end-to-end on TIFFs (regions + names appear in Atlas Manager and in the generated spreadsheet).
- Robustness: zone ID keys normalized to int on every load path (bundle, legacy sidecars, state restore); explicit `int()` on mask-derived IDs; clean bool cell masks for watershed; viz errors wrapped so counts/df are always produced; manual cell-edit masks cleared on new TIFF load; progress dialog closed *before* results popups; always show a dialog even on skipped auto-save.
- Version bumped to "8.05.000".

See release-notes-v8.05.000.md for full details. v8.04.000 paint border/undo work and earlier remain intact.

**v8.04.000 Highlights** (previous)
- **Painted region border/edge editing with Enter-to-commit**: Live border drag or red-edge grab updates the yellow/orange zone mask (highlighted region) in real time for preview. The black drawn boundary line stays at the previous shape during adjustment. After releasing the mouse, **press Enter** (or keypad Enter) to commit: the current mask contour is extracted, the stored painted outline is updated, the paint layer is rebuilt, and a full redraw refits the visible black boundary exactly to the new expanded/deformed shape. This provides precise "preview then bake" control for custom painted regions.
- **Undo button + repeated undo for paints**: Prominent ↶ Undo button in the Atlas Manager ribbon header (also Edit > Undo with accelerator shown). Full support for undoing individual paint strokes (one per mouse-down/up group), naming of painted regions, Stop/Count auto-conversion, border/edge deformations on painted zones, and atlas transforms. Up to 40 levels. Banner list, zone data, mask, and black boundary visuals now stay perfectly in sync after each undo.
- **"Border drag resize enabled" now defaults to off**: The checkbox in the ribbon (under selected region tools) starts unchecked. You must explicitly enable it after selecting a painted or atlas region before edge/border drag or the red local segment tools activate. Prevents accidental advanced editing.
- **Paint mode indicator**: When Paint tool is active, a bold red "🎨 PAINT ON" label appears in the ribbon header. The main window title also shows " — 🎨 PAINT MODE". Returns to normal (gray "Paint: off") on Stop Paint or tool switch. Visible in title bar even if ribbon is hidden.
- **Edge / Move Selected / border tools for painted regions**: Full support (with correct coordinate handling for paint vs. atlas mask spaces) in addition to atlas regions. Combined with the Enter commit, you can now iteratively refine the shape of painted regions and have the black outline automatically follow.
- **Undo reliability & hygiene**: Individual stroke granularity (no more unexpected multi-paint undos in common flows), immediate ribbon banner updates on undo, mask pruning to prevent re-orphaning of removed painted zones, and better state snapshots around paint naming and finalization.
- Updated manual (regenerated with new "What's New in Version 8.04.000" covering the paint border Enter commit flow, undo button, paint indicator, checkbox default, and painted region editing).
- Version in code/settings JSON: "8.04.000".

See release-notes-v8.04.000.md for full details. The v8.03.000 Atlas Manager ribbon and prior Paint reliability work remain fully intact.

**v8.03.000 Highlights** (previous major release)
- **Atlas Manager Ribbon** (new central, discoverable UI for atlas region work; toggleable via View > "Show Atlas Manager Ribbon"):
  - Expandable header + content; always shows selected region.
  - Global Crop and Move now **checkboxes** (visible active state; enables whole-atlas click-drag modes).
  - "Move Selected Region" checkbox + interior drag: translates *only* the orange selected zone's mask (artwork/other regions fixed).
  - "Border drag resize enabled" checkbox: enables edge grab.
  - **Global Quick Adjust** (new): Rot +/-5°, Scale +/-5% for entire atlas page (base + masks) + Dialogs access.
  - Selectable list of labeled regions (click to select for editing).
  - Selected Region Quick Adjust (Rot +/-5°, Scale +/-5%, Dialogs) — only affects chosen zone.
- **Per-region atlas editing**:
  - Select via canvas click (now autoselects named regions, no re-name prompt), list, or Atlas > Select Region.
  - Edge grab: click near border → red local segment (persistent). Re-click to reposition; drag to locally deform boundary (falloff, live preview). Commit on release.
  - Move-selected + quick per-region transforms.
- **Mutual exclusion & clarity**: Enabling edge/border auto-deselects global Move (and Crop); vice versa. Checkboxes + orange tint + list make context obvious.
- **Menu update**: Import Atlas (plus all global/per-region tools) moved to dedicated top-level **Atlas** menu.
- **Robustness fixes**:
  - Atlas crop: proper model coords via _canvas_to_atlas, rebase img_x/img_y, prune orphans, full state clear (no more "disappearing" atlas).
  - Load order: image after atlas no longer breaks global Move/edge (stale selection/edge state now fully cleared in import_tiff + _load_tiff_file paths).
  - Edge hit-testing forgiving (boundary pixels still trigger grab when near selected).
  - Drag delegation: per-region features work even under global edit bindings.
  - Hygiene: clears on page switch, deselect, imports, crop, etc.
- Updated manual (regenerated with new What's New 8.03.000 + expanded Atlas chapter documenting ribbon, quick adjust, edge features, checkboxes, etc.).
- Version in code/settings JSON: "8.03.000".

See release-notes-v8.03.000.md for full details. Previous v8.02.x Paint reliability and count fixes remain intact.

**v8.02.002 Highlights** (previous patch)

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
- Continuing from v8.01: Modern Blob Detection (default), Smart Suggest (Pre-tuning smart settings), left File Browser with counted status, automatic dual export (`.xlsx` + `_masked.tif`), and portable settings.

**v8.01.000 Highlights** (previous major release)
- New modern Blob Detection engine (Laplacian of Gaussian) — significantly better results on most immunofluorescence images.
- "Smart Suggest (Pre-tuning smart settings)" — a fully local, privacy-preserving tool that analyzes your image and recommends better detection parameters (with checkbox selection).
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
   
   b. *Import Atlas*:
      - Click "Atlas > Import Atlas"
      - Select your PDF atlas file

3. **Align Atlas**:
   - Use "Move Atlas" button to position the atlas over your image
   - Use rotation and scaling controls if needed
   - For fine per-region adjustments (after naming zones): Atlas > Select Region (then click a yellow region), then use Rotate Selected Region / Scale Selected Region to tweak individual shapes larger/smaller or rotate them. The underlying atlas lines stay fixed as reference while the counting zones (yellow) adjust.

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

