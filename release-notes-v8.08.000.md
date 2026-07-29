# BARCC v8.08.000

Major multi-channel atlas, intensity, and cell-mask release. Allen Mouse Atlas integration, portable schematic files, cross-channel cell masks, axon/PNN intensity with correction, random null distributions, and perineuronal shell analysis.

## Highlights

### Allen Mouse Atlas + semi-auto stitch
- **Import Allen Atlas** plate browser with Nissl reference strip and borders-only movable overlay.
- **Stitch editor**: Reflect right→left, move/rotate hemispheres, then load into BARCC.
- **Fit Atlas to Image**, crop/move/scale/rotate with model-space placement (no zoom drift).
- Post-crop cleanup of incomplete/loose structures and morphological borders.
- **Hemisphere labels**: after Reflect/bilateral stitch, structures are named with **`_r` / `_l`** suffixes (e.g. `V2M_r`, `V2M_l`) so left and right are distinct in Atlas Manager and Count Cells.

### Portable atlas schematic (`.catlas`)
- **Save / Load Atlas Schematic** (Atlas + File menus): lossless package of zone mask, structure drawings, painted regions, Atlas Manager names, and placement.
- Load onto other fluorescence channels of the same section without re-labeling.
- Placement fix: when background size changes between save and load, atlas layers, paint, and `img_x`/`img_y` scale **together** (avoids right-shift after crop / viewer resize).
- Legacy `.atlas` files still load; new saves use `.catlas`.

### Next Channel (keep atlas)
- **Next Channel…** loads a new TIFF while preserving atlas drawings, zone masks, names, paint, and placement.
- Normal Import / Next Image fully clears atlas (no ghost double-overlays).
- **Clear Atlas** in Atlas menu and Atlas Manager ribbon.

### Paint on atlas → cell counter regions
- Painted regions use atlas model coordinates when an atlas is loaded.
- Named (or auto-named) paint merges into the existing zone mask and appears in Atlas Manager / Count Cells without clobbering Allen zones.

### Axons and Nets — intensity & correction
- **Measure Region Intensities…** with options dialog:
  - **Background subtraction**: Xth-percentile intensity within each region.
  - **Counterstain normalization**: divide by factors from a counterstain file.
- **Counterstain Normalization Measurement…**: measure on DAPI/counterstain with the same `.catlas`; exports `Normalization_Factor` per region.
- Export columns include **Pre_Correction_Mean/Median** and **Post_Correction_Mean/Median**, plus raw/BG/normalized detail columns.
- Excel output under `output/` (multi-sheet, Count Cells–style), File Browser listing, openpyxl fallback warnings.

### Cross-channel cell masks
- **Save Cell Mask…** / **Load Cell Mask…** (`.barccmask` + PNG).
- Loaded mask is **locked** so Count Cells reuses it without re-detection.
- **Show Mask** re-detects and unlocks when you want a new mask on the current channel.

### Random null cell distribution
- **Generate Random Cell Mask…**: same cell count as ground truth; randomized XY; radii shuffled.
- With atlas/`.catlas`: **stratified by region** (same count per structure, placed inside that structure).
- Display: **red** = GT, **cyan** = random. Optional seed + save.

### Perineuronal (PNN) shells
- **Draw Perineuronal Masks**: shell between cell boundary and outer disk of **2× cell area**.
- Also draws shells for random cells when present (magenta = true PNN, yellow = random PNN).
- **Measure Perineuronal Intensity…** exports:
  - `{name}_pnn_by_structure.xlsx` — per structure: True/Random Mean, SEM_Mean, Median, SEM_Median.
  - `{name}_pnn_cells_true.xlsx` — per cell: area + perineuronal intensity.
  - `{name}_pnn_cells_random.xlsx` — same for random cells.

### Menu reorganization
- **Mask** menu renamed **Cell** (detection tools + Counting submenu).
- Axons and Nets expanded with intensity, counterstain norm, PNN, and label toggles.

## Files
- `Application/barcc.py` — main application (major feature work).
- `Application/allen_atlas.py` — Allen CCF plate load, stitch session, bilateral `_r`/`_l` naming (**new in repo**).
- `release-notes-v8.08.000.md` — this file.
- Version string: **8.08.000**.

## Notes
- Count Cells still counts only the **real/ground-truth** cell mask (not the random null mask).
- uint8 zone ID limit (255) still applies for bilateral split when structure count is very high.
- Prefer same-section, same-resolution channels for `.catlas` and cell-mask transfer.

## Requirements / Running
From `Application/`:

```text
py -3.12 barcc.py
```

Dependencies: see `requirements.txt` (including `openpyxl` for Excel exports).

## Git
- Tag: **v8.08.000**
