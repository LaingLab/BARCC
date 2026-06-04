# BARCC v8.02.001

Patch release that resolves the final reported issues with the Paint tool workflow (first-attempt zone registration after naming) and improves usability of the auxiliary settings dialogs. These changes build directly on the major Paint reliability overhaul in v8.02.000.

## Highlights

### Paint Tool / Zone Registration Fixes (Final Polish)
- **"First paint + name + Count Cells" now works on the very first attempt**: Previously, after loading a fresh TIFF, drawing one region, right-click naming it immediately, and clicking Count Cells would still show "No Regions Defined". Drawing a *second* region and naming it would then succeed (but the spreadsheet would only contain the second region). 
  - Root cause: The first `stop_paint()` (automatically called by Count Cells) + its final `show_page()` triggered `load_page_image()`, which (on the first activation of `atlas_filetype='img'` after `save_paint()` sets it) would *unconditionally* reset `zone_names[current_page] = {}`, `mask_images[...] = blank`, and `zone_counters[...] = 0` when populating `page_images`. This clobbered the zone entry and mask pixels that `_convert_named_paints_to_zones` (called from `name_painted_region`) had just created. The subsequent post-stop conversion attempts in `count_cells` had no data left (because `stop_paint` also clears `named_paint_groups` + `paint_group_data`).
- **Targeted guard added in `load_page_image`**: Per-page mask/zone/counters initialization now only occurs for true multi-page PDF atlas content (`if self.atlas_filetype == 'pdf'`). For 'img' (baked paint from Stop/Save/Count) and 'png' (Load Paint) cases we still cache the image for display/layer purposes, but we no longer destroy user-defined paint zones. This matches the intent of the edit/crop/rotate paths that carefully preserve `mask_images`.
- **Additional robustness in conversion paths** (cumulative with prior 8.02 work):
  - Broadened stroke collection in `_convert_named_paints_to_zones` (durable `paint_group_data` model points + live canvas items + last-resort any-'paint' for still-named groups).
  - Conditional `dtag` in `name_painted_region` (only strip the group tag after successful retirement; leave it if collection failed so later Stop/Count fallbacks can still discover it).
  - Re-collection + re-convert safety net inside `stop_paint` *before* the final clear.
  - Ultimate force-add of lingering data groups before the "No Regions Defined" error guard in `count_cells`.
- These ensure that `paint_group_data` (the durable model-space geometry recorded during drawing) is always used to populate `zone_names` and the labeled `mask_images` before any clobber/clear can occur, and that the guard in Count Cells always sees the registered zones.

The net result: the exact user flow requested throughout development ("draw, name immediately with right-click, click Count Cells without ever pressing Stop Paint") is now 100% reliable on the first try after loading any image. No more "paint a new region to make the first one appear" workaround.

### Settings Dialog Usability
- The titlebar **X button** (and Alt+F4 / window manager close) on the **Brightness Settings** dialog (the one containing the live brightness slider/scale) now correctly closes the window.
  - Previously bound to `self.disable_event` (a no-op `pass`), so the X did nothing (only the "Close" button at the bottom worked).
- For consistency, the same fix was applied to the other three small auxiliary settings dialogs that shared the identical Toplevel + protocol + `_register_transparent_window` pattern:
  - Brush Settings (the brush size slider)
  - Scale Settings
  - Rotate Settings
- `show_mask_settings` was already using the correct `window.protocol("WM_DELETE_WINDOW", window.destroy)`.
- The `<Destroy>` cleanup handler in `_register_transparent_window` continues to work, removing the window from the transparent list.
- **Progress dialogs** ("Counting Cells", "Detecting Cells", etc.) remain intentionally hardened (they set a `closed` flag and make all subsequent UI calls no-ops) so that early dismissal cannot crash long-running operations. This behavior is unchanged and was the critical stability fix from 8.02.000.

## Summary of Changes
These are the final missing pieces that users encountered while exercising the v8.02.000 paint features on real data:
- Zone data for the very first named paint region on a freshly loaded image could be silently destroyed by the internal "bake to img" path.
- The brightness slider dialog (a frequently used quality-of-life control) had a non-functional close button in the title bar.

All prior v8.02.000 guarantees (durable geometry, proper filling, no dups, auto-stop on Count, full wipe on load, auto-export, etc.) are preserved and now apply even on the absolute first paint action.

## Other Notes
- No changes to detection (Blob remains default), exports, File Browser, or core counting logic.
- The settings JSON export now records `"version": "8.02.001"`.
- The User Manual source (`docs/generate_barcc_manual.py`) has been updated with a new "What's New in Version 8.02.001" section. Re-run the generator (after `pip install fpdf2`) to produce an updated `BARCC_User_Manual.pdf`.
- `README.md` top section updated to lead with v8.02.001 highlights.

## Requirements
Unchanged from v8.02.000. For full `.xlsx` support:

```
pip install openpyxl xlsxwriter
```

## Preparing the Release
- Bump complete.
- Full notes in this file + README + manual generator.
- Commit the changes, create annotated tag `v8.02.001`, and push (including `--tags`).
- On GitHub: Draft a new release from the tag, paste the highlights + link to this release-notes file, mark as latest if appropriate.

Full updated manual (BARCC_User_Manual.pdf) and source are included in the repository after regeneration.

---

**Previous release**: See `release-notes-v8.02.000.md` for the major Paint tool reliability, menu reorganization, auto-save to File Browser dir, progress dialog crash hardening, and interior counting improvements in 8.02.000. See `release-notes-v8.01.000.md` for Blob Detection, Smart Suggest, etc.
