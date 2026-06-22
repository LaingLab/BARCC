# BARCC v8.06.000

Stability and usability release: Count Cells no longer hard-crashes on Windows, TIFF loading is memory-safe, and **Show Zone Labels & Counts** is now a working tabular viewer.

## Highlights

### Show Zone Labels & Counts (Cell menu)
- The checkbutton previously did nothing useful (broken `BooleanVar`, required in-memory counts only, no table UI).
- Toggling **Cell → Show Zone Labels & Counts** now opens a dedicated window with a **Zone** / **Cell Count** table for the current TIFF.
- Data sources (in order): latest in-session count (`last_df`), saved `.xlsx` / `.csv` beside the TIFF, or defined zone names with `—` if not yet counted.
- Shows a **total cell count** footer when numeric counts are available; refreshes after Count Cells and when switching files in the left browser; closing the window unchecks the menu item.
- On-image yellow zone labels still draw when counts are in memory and the option is enabled.

### Fixed Count Cells hard crash on Windows (masked TIFF save)
- **Root cause:** Auto-saving `{basename}_masked.tif` used `compression='tiff_deflate'`. On common Windows Pillow/libtiff builds this triggers a native segfault (`0xC0000409`) — not catchable in Python — so the app vanished right after counting finished.
- **Fix:** Save `_masked.tif` without deflate compression (uncompressed TIFF, same filename and overlay content).

### Fixed Count Cells loading full-resolution TIFFs (OOM / hang)
- When the canvas was not yet laid out (1×1 px at startup), `_load_tiff_file` used `scale = 1.0` and kept **full native resolution** (e.g. 2048×2044 16-bit) in memory, making detection and counting extremely slow or unstable.
- **Fix:** `_compute_tiff_fit_scale()` / `_resize_tiff_for_viewer()` estimate fit from window/screen size when the canvas is unavailable; `import_tiff` and file-browser load both use this helper.

### Count Cells pipeline hardening
- Replaced mid-count `stop_paint()` with `_finalize_paint_for_counting()` (no `save_state`, `save_paint`, or extra `show_page` side effects).
- Fixed transient **Pen:** menu removal (`_remove_paint_pen_menu_item()` by label instead of hardcoded `menu.delete(8)`).
- Full `try/except/finally` around the count pipeline; progress dialog always closes; user-visible error on failure.
- 2D mask shape guards for manual add/remove masks.
- When a precomputed cell mask is passed to `count_cells_in_zones`, skip redundant second detect + watershed (use connected components) — faster and less memory.

## Other Notes
- Version string in code and exported settings JSON: **8.06.000**.
- README.md, BARCC_User_Manual.pdf, and `docs/generate_barcc_manual.py` updated.
- Release notes: this file.
- No changes to `requirements.txt`.

## Requirements
Unchanged.

## Installing / Running
```text
cd Application
py -3.12 barcc.py
```
(or your usual launcher / Anaconda `barcc` environment)

Git tag: **v8.06.000**