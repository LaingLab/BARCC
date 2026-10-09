# Regional IF Analyzer

A GUI tool for analyzing immunofluorescence images with atlas region mapping and automated cell counting.

## Download and start using BARCC

BARCC is a desktop program. You download this repository, create a Python environment once, then launch `Application/barcc.py`. Windows with [Miniconda](https://www.anaconda.com/docs/getting-started/miniconda/install) or [Anaconda](https://www.anaconda.com/download) is the setup these steps use. The same conda commands work on macOS and Linux.

### 1. Download the code

**With Git** (this keeps the folder easy to update later):

```bash
git clone https://github.com/LaingLab/BARCC.git
cd BARCC
```

**Without Git:** open https://github.com/LaingLab/BARCC and choose **Code → Download ZIP**, or download the main-branch archive directly:

https://github.com/LaingLab/BARCC/archive/refs/heads/main.zip

Unzip it. The folder is named `BARCC-main`. Open a terminal in that folder (the one that contains `environment.yml`, `requirements.txt`, and the `Application` folder).

A frozen snapshot of release 8.11.000 is at https://github.com/LaingLab/BARCC/releases/tag/v8.11.000 (Source code zip). Use `main` if you want the latest documentation.

### 2. Install Miniconda or Anaconda (once per computer)

1. Download the installer from https://www.anaconda.com/docs/getting-started/miniconda/install (Miniconda) or https://www.anaconda.com/download (full Anaconda).
2. Run the installer. On Windows, accept the option that registers Anaconda/Miniconda so **Anaconda Prompt** appears in the Start menu.
3. Open **Anaconda Prompt** (Windows) or a new terminal (macOS/Linux). `conda` must be on the path in that window. Check with:

```bash
conda --version
```

### 3. Create the BARCC environment (once per computer)

From the folder you downloaded (the one that contains `environment.yml`):

```bash
conda env create -f environment.yml
conda activate barcc314
```

That creates an environment named `barcc314` on Python 3.14 and installs the packages in `environment.yml`, including tkinter, PyMuPDF (atlas PDFs), and openpyxl/xlsxwriter (Excel export).

If `barcc314` already exists and you only need to refresh packages:

```bash
conda activate barcc314
conda env update -f environment.yml --prune
```

If `conda env create` is not available, this is the same environment built by hand:

```bash
conda create -n barcc314 python=3.14 pip -y
conda activate barcc314
pip install -r requirements.txt
```

### 4. Start the program (every session)

**Anaconda Prompt** (this is the reliable start on a new computer):

```bash
conda activate barcc314
cd Application
python barcc.py
```

Use the full path to `Application` if you are not already inside the downloaded folder. Example:

```bash
conda activate barcc314
cd C:\Users\YourName\BARCC\Application
python barcc.py
```

A window titled with BARCC opens. The menu bar has File, Edit, Atlas, Paint, Cell, and Axons and Nets. **File → User Manual** opens `BARCC_User_Manual.pdf` from the repository root.

**File → Update** checks GitHub and downloads newer program files when this folder was created with `git clone`. Close BARCC and open it again after it reports an update. A copy that came from Download ZIP has no `.git` folder, so that command cannot update it. Clone once and keep using that folder. Images and `output` folders live outside the program folder and are not replaced.

`Application/Launch_BARCC.bat` is an optional Windows double-click launcher. It looks for one developer’s conda path first, then `py -3.14`, then `python` on PATH. On a new computer those later Pythons often do not have the BARCC packages, so the window never opens. Use the Anaconda Prompt commands above until you know the bat file is launching `barcc314`.

### 5. First session

1. **File → Import Tiff** and choose a single-channel `.tif` or `.tiff`. You can also use the left File Browser: pick a folder, then double-click a TIFF.
2. Mark regions with **Paint → Start Paint**, draw, then **Paint → Stop Paint**. Or load an atlas with **Atlas → Import Atlas (PDF)** or **Atlas → Import Allen Atlas…**.
3. If you loaded an atlas, align it in this order: **Atlas → Fit Atlas to Image**, then **Align: Landmarks (point pairs)…**, then **Align: Edge Snap…** (Preview, then Apply), then **Align: Local Refine (guide)…**.
4. Click each region and name it.
5. **Cell → Show Mask** to see detections. Tune them with **Cell → Show Mask Settings** (Smart Suggest, Area Tune, Measure Tune).
6. **Cell → Counting → Count Cells**. BARCC writes a workbook and a masked TIFF under `output/counts/` next to the image workflow (see the manual for the exact output folders).

The longer click-by-click workflow is in [Basic Usage](#basic-usage) below and in [BARCC_User_Manual.pdf](BARCC_User_Manual.pdf). Detection parameters are in [mask_settings_documentation.md](mask_settings_documentation.md).

### If the first launch fails

- **`conda` is not recognized.** Open Anaconda Prompt, not a plain Command Prompt, or reopen the terminal after installing Miniconda.
- **`No module named tkinter` / the window does not appear.** Recreate the env from `environment.yml` (it installs the `tk` package). On Ubuntu/Debian with system Python only: `sudo apt-get install python3-tk`.
- **Atlas PDF will not open.** From the active `barcc314` env: `pip install "PyMuPDF>=1.21.0"`.
- **Count Cells writes a `.csv` instead of `.xlsx`.** `pip install "openpyxl>=3.0.10" "xlsxwriter>=3.0.0"`.
- **Images fail to load.** Use an uncompressed or lossless TIFF. JPEG is not supported.

**v8.11.000 Highlights** (current)
- **File → Update**: checks GitHub and fast-forwards a Git clone. Close and reopen BARCC afterward.
- **Batch Recalculate Intensities**: Axons and Nets remeasures every TIFF that already has a paint file, without opening each image. Change the background percentile and run again.
- **One intensity workbook**: `output/intensities/{image}_intensities.xlsx` (sheet Region Intensities only). Measuring also overwrites the paint bundle and `{stem}_atlas.catlas`.
- **Project intensities**: `{name}_Intensities.xlsx` — column A is the image name, then the same columns as the per-image sheet. Re-measuring an image replaces its rows.
- Version: **8.11.000**. See [release-notes-v8.11.000.md](release-notes-v8.11.000.md).

**v8.10.000 Highlights**
- **Dual Settings Mode**: Config A and Config B on the same slice; assign regions with A/B keys; Smart Suggest A/B.
- **Atlas alignment stack**: Landmarks (point pairs) → Edge Snap (ICP silhouette, preview then apply) → Local Refine.
- **Project workbook**: File → Select Project Output Directory writes `{name}_Counts.xlsx` (one row per image) and, when you measure region intensities, `{name}_Intensities.xlsx` (image name in column A, then the same columns as the per-image intensity sheet).
- **Crop aspect lock**: match TIFF, 1:1 / 4:3 / 3:2 / 16:9, or custom W×H.
- Extra blob filters: ridge/midline reject, cavity rim, chain reject, cluster recover; Adaptive per-region mode.
- File Browser: Exclude / Include, Reload last count; View → Show Cell Mask (rings survive zoom).
- Version: **8.10.000**. See [release-notes-v8.10.000.md](release-notes-v8.10.000.md).

**v8.09.000 Highlights** (previous)
- **Adaptive detection** (Blob/DoG overlay): tile thresholds, dual-pass, density packing.
- **Peak quality filters**: local SNR, bg-relative, isotropy, circularity, tissue-edge reject.
- **Area Tune**: 10 per-cell diameter lines → min/max blob area (0.7×–1.5× mean); preserved over Measure Tune.
- **Measure Tune TP/FP/FN/TN**: label the current mask; precision (FP/TN) or recall (TP/FN) passes; feeds Smart Suggest.
- **Smarter Smart Suggest**: regional bright/dark diagnosis, joint Adaptive+SNR recipes, trajectory memory.
- Mask Settings: inactive method panels dimmed + locked; remove-cell brush yellow; add/remove keep detection rings visible.
- Version: **8.09.000**. See [release-notes-v8.09.000.md](release-notes-v8.09.000.md).

**v8.08.000 Highlights** (previous)
- **Allen Mouse Atlas** + semi-auto stitch, `.catlas`, Next Channel, Axons/Nets intensity, random null + PNN shells.
- Version: **8.08.000**. See [release-notes-v8.08.000.md](release-notes-v8.08.000.md).

**v8.07.000 Highlights** (previous)
- **Save Flattened Image** fully flattens zone fills + paint + red cell mask.
- Version: **8.07.000**. See [release-notes-v8.07.000.md](release-notes-v8.07.000.md).

**v8.06.000 Highlights** (previous)
- **Show Zone Labels & Counts** (Cell menu): Opens a table window with zone names and cell counts for the current TIFF (session counts, saved .xlsx/.csv, or defined zones). Total footer, auto-refresh after counting, syncs with file browser.
- **Count Cells crash fix (Windows):** `_masked.tif` auto-save no longer uses `tiff_deflate` (segfault on many Pillow/libtiff builds). Counting now completes with results dialog and spreadsheet.
- **Memory / performance:** TIFFs no longer load at full native resolution when the canvas is not laid out; fit-to-window scaling via `_resize_tiff_for_viewer()`.
- **Count pipeline:** Lightweight paint finalize (no mid-count `stop_paint`); skip redundant watershed when mask exists; try/except/finally + mask shape guards.
- Version: **8.06.000**. Updated manual and release notes.

See [release-notes-v8.06.000.md](release-notes-v8.06.000.md) for full details.

**v8.05.000 Highlights** (previous)
- Paint bundle (.barccpaint) load on TIFF: fixed ufunc 'less' / uint8 zone ID issues; Count Cells silent failure fixes after bundle load; zone ID int normalization.
- See [release-notes-v8.05.000.md](release-notes-v8.05.000.md).

v8.04.000 paint border/undo work and earlier remain intact.

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

Count Cells writes an Excel workbook (Cell Counts and Detection Parameters) and a masked TIFF. Those Excel engines are included when you install from `environment.yml` or `requirements.txt`. If they are missing, BARCC falls back to a `.csv`.

## Basic Usage

Detection parameters are listed in [mask_settings_documentation.md](mask_settings_documentation.md). The full walkthrough is [BARCC_User_Manual.pdf](BARCC_User_Manual.pdf).

1. **Import a TIFF**:
   - File > Import Tiff, or double-click a file in the left File Browser
   - File > Next Channel… loads another channel of the same section and keeps the atlas, names, and paint

2. **Define regions**

   a. *Paint*:
      - Paint > Start Paint, draw the ROI, then Paint > Stop Paint
      - Paint > Save Paint Layer writes into the folder open in the File Browser (Paint > Load Paint reloads it)

   b. *Atlas*:
      - Atlas > Import Atlas (PDF), or Atlas > Import Allen Atlas…
      - File or Atlas > Load Atlas Schematic… (`.catlas`) reuses labeled regions on another channel

3. **Align the atlas** (this order):
   - Atlas > Fit Atlas to Image
   - Atlas > Align: Landmarks (point pairs)… — click atlas, then matching tissue; 3–6 pairs; Apply Fit
   - Atlas > Align: Edge Snap… — Preview, then Apply (Restore undoes a preview)
   - Atlas > Align: Local Refine (guide)… — border-drag individual structures once the global pose is close
   - With Global Crop on, lock the crop box to Match TIFF, 1:1, 4:3, 3:2, 16:9, or a custom W×H

4. **Name regions**:
   - Click a region and name it when prompted
   - Dual Settings Mode (Mask Settings): select a region in Atlas Manager and press **A** or **B** so packed and sparse zones can use different detectors. Unassigned regions use Config A

5. **Check the cell mask** (Cell menu):
   - Cell > Show Mask
   - Cell > Show Mask Settings — Blob/DoG or Watershed; Adaptive checkbox; Area Tune; Measure Tune (TP/FP/FN/TN); Smart Suggest
   - Cell > Add Cell (red) / Remove Cell (yellow/gold). View > Show Cell Mask toggles detection rings without re-detecting

6. **Count cells**:
   - Cell > Counting > Count Cells
   - Each image still gets a workbook under `output/counts/`
   - File > Select Project Output Directory also writes `{project name}_Counts.xlsx` (one row per image; re-counting a file replaces that row)

## Common Issues

Setup failures (conda not found, missing tkinter, PDF import, Excel falling back to CSV) are listed under [If the first launch fails](#if-the-first-launch-fails).

- Images fail to load: use an uncompressed or lossless TIFF. JPEG is not supported.
- Atlas PDFs fail to open: `pip install "PyMuPDF>=1.21.0"` inside the `barcc314` environment.

## Support

For issues and feature requests, please open an issue in the GitHub repository.

## License

