# BARCC v8.02.002

Patch release that resolves the mismatch between the cell counts users see visually on the annotated image and zone labels versus the numbers reported in the exported spreadsheet.

## Highlights

### Count Mismatch Between Visual Mask/Image and Spreadsheet Fixed
- **Symptom**: After drawing painted regions, naming them, running "Count Cells", the yellow zone labels on the image (e.g. "MyRegion\n(12)") and the number of red cell markers visible inside each region on the annotated image / _masked.tif did not match the "Cell_Count" values in the "Cell Counts" sheet of the .xlsx (or the fallback .csv).
- **Root cause**: 
  - Cell detection, manual edits, and final cell mask always operate in the coordinate system of the main experimental image (`original_background`, aligned at 0,0).
  - Hand-painted regions are rasterized into `mask_images` using the same background-aligned model space.
  - However, both the per-zone counting logic inside `count_cells_in_zones` (which builds the DataFrame used for the spreadsheet and `last_df`) *and* the positioning of zone labels in `show_page` unconditionally subtracted/added the atlas overlay offset (`img_x` / `img_y` / `display_img_x`).
  - `img_x`/`img_y` are updated by panning the atlas, zooming (centered), dragging, alignment tools, etc. Any non-zero value would shift the cell centroid lookup into the zone mask, causing cells to be assigned to the wrong zone (or no zone at all) for counting purposes.
  - The visual red markers (and the underlying cell positions) were drawn using raw centroids, so users would literally see more (or fewer) cells inside a painted region than the spreadsheet and on-screen labels reported.
- **Fix**:
  - Added a simple, robust size-based heuristic in `count_cells_in_zones`:
    - Compare the zone `mask_pil` dimensions to the `background_pil` (main image) size.
    - If they match (within tolerance): this is a paint region (or standalone TIFF) in the main image space → use direct cell coordinates for zone lookup (no offset applied).
    - If sizes differ (typical for an atlas/PDF overlay rendered at a different resolution): keep the previous `img_x`/`img_y` offset logic to translate into the placed atlas layer's coordinate system.
  - Applied the identical heuristic to the zone label drawing code in `show_page`:
    - If the current zone mask size matches the main `background_image`, place the yellow "Name\n(count)" labels at base offset 0 (over the background layer drawn at canvas 0,0).
    - Otherwise use the atlas placement offset (as before).
  - Updated variable names and comments for clarity.
- **Result**: After re-running Count Cells, the per-zone totals in the spreadsheet exactly match the number of cells the user sees marked inside each region on the image, and the on-screen yellow labels (when enabled via the Cell menu) appear over the correct regions with the correct counts — even if an atlas overlay has been panned or zoomed.
- This only affects the mapping/assignment and label placement. No changes to the actual cell detection, manual add/remove logic, watershed, neighborhood search, binary_fill_holes, or any other counting internals.
- Pure atlas (PDF) region workflows and cases with no overlay offset continue to behave exactly as before.

## Other Notes
- Version string recorded in exported detection settings JSON is now "8.02.002".
- The User Manual has been fully regenerated with a new "What's New in Version 8.02.002" section.
- `README.md` top-level highlights updated.
- No other functional changes. Previous v8.02.001 and v8.02.000 Paint reliability, menu, stability, and export improvements remain fully intact.

## Requirements
Unchanged. For full `.xlsx` support with the "Detection Parameters" metadata sheet:

```
pip install openpyxl xlsxwriter
```

## Preparing / Installing the Release
- Source, updated manual (`BARCC_User_Manual.pdf`), and this file are in the repository.
- Git tag: `v8.02.002`
- GitHub release includes these patch notes and the updated manual as an asset.

See `release-notes-v8.02.001.md` for the prior patch (first-paint reliability + settings dialog X-button fixes) and `release-notes-v8.02.000.md` for the major Paint overhaul.

---

**Full updated manual and source available at the GitHub release and in the repo.**