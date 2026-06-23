# BARCC v8.07.000

Usability and flattening fix for the paint + count workflow on TIFFs.

## Highlights

### Save Flattened Image now includes the full mask
- Previously only saved the base TIFF + paint layer (black boundaries). The zone fills for painted regions and the red cell mask overlay were missing.
- Now properly flattens:
  - TIFF base
  - Yellow filled painted region masks (explicit tint from the zone `mask_images`, so areas are filled, not just boundaries)
  - Black paint boundaries (`paint_layer`)
  - Red masked cells (from `last_cell_mask` after Count Cells, using `alpha_composite` for blending)
- Uses `Image.alpha_composite` for correct layering and visibility.
- Default save name is now `{tiff_filename}_flattened.tif` (with proper initialdir).
- Works for both interactive **File > Save Flattened Image** and internal autosave (used by Next Image before reset).
- Same safe TIFF save (no `tiff_deflate` to avoid segfaults).

### Remaining crash hardening in flattened save
- All overlay steps (zone fill, paint, cells) are now in defensive try/except blocks.
- Size guards, proper 2D handling for masks, int casts for offsets, explicit mode='L' on fromarray.
- If overlays fail for any reason, still saves at least the base + what succeeded (no app crash).

See previous release notes for the v8.06 count stability work, zone table, and earlier paint bundle fixes.

## Other Notes
- Version string in code and exported settings JSON: **8.07.000**.
- README.md and `docs/generate_barcc_manual.py` updated (manual PDF will be regenerated on next run).
- New release notes file: this one.
- Git tag: **v8.07.000**

## Requirements / Running
Unchanged from v8.06. Use `py -3.12 barcc.py` from the Application directory.