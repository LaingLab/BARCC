# BARCC v8.05.000

Patch release focused on reliability of the new Paint bundle (`.barccpaint`) workflow — specifically loading painted regions + names onto TIFFs and then running Count Cells — plus related crash and feedback fixes.

## Highlights

### Fixed "failed to load paint bundle: ufunc 'less' ..." on .tiff
- The error `ufunc 'less' did not contain a loop with signature matching types (<class 'numpy.dtypes.UInt8DType'>)->none` occurred when loading a `.barccpaint` (containing strokes.png + zones.png + manifest with named painted regions) onto a .tiff via the left File Browser or Load Paint.
- Root cause: `json` stringifies dict keys → zone IDs became strings in `zone_names`/`painted_zone_outlines`. After load, `np.array(zones mask)` produced `uint8` scalars. `_populate_region_list` (called from `_update_ribbon_selection` during bundle load + `show_page`) did `if zid > 0 and zid not in names` + `sorted(names.items())`, causing Python sort / numpy ufunc 'less' to fail on mixed str + np.uint8.
- Fixed by:
  - Normalizing keys with `{int(k): v for ...}` immediately after loading manifest / legacy sidecar JSON in `_load_barccpaint_bundle`, legacy paths, and StateManager restore.
  - `int(zid)` in `_populate_region_list`, `_ensure_zone_has_name`, and count lookup paths.
  - Same normalization for painted outlines.
- Painted regions now load with names appearing immediately in the Atlas Manager list and shapes usable for counting.

### Fixed silent crash / no feedback on Count Cells after painted bundle load
- After a successful bundle load, clicking Count Cells would sometimes "crash" with no dialog at all and no `.xlsx` (or `_masked.tif`) generated.
- Causes addressed:
  - Numpy broadcast error in the cell marker drawing code inside `count_cells_in_zones` (`rgb_img[slice, x] = [255,0,0]` etc.) on edge centroids or degenerate (0-length) slices after window-fit scaling of the TIFF. This happened after counts were computed but before `df` was returned → exception escaped the count path.
  - Progress dialog close timing vs. the "Results Saved" / warning `messagebox`: leaving the busy Toplevel open while showing the results dialog + closing it afterward could cause event/focus issues on OK.
  - Auto-save block silently skipped (only a log) when `tiff_dir` / `tiff_filename` was not set (some direct open vs. browser flows, or state after accessory load). No user-visible indication and no file.
- Fixes:
  - Explicit `[:, :]` channel indexing + `if start < end` guards in the cross drawing.
  - Full `try/except` around non-critical viz blocks in `count_cells_in_zones` so `df` / counts / return always succeed (fallback annotated image).
  - Close the busy progress dialog *before* any final "Results Saved" popup (and perform masked save early).
  - If save paths are missing, still show an info dialog ("Count Complete...") so the user always gets feedback.
  - Added defensive guard for `original_background` before detection.
- Result: Count Cells after loading a painted bundle on a .tiff now reliably produces the spreadsheet (with your painted region names), the masked image, and dialogs. No more silent failures.

### Other robustness for painted + TIFF + count
- Manual add/remove cell masks are now cleared on every new TIFF load (via browser or direct) so stale edits from a previous image don't get resized and OR'd into the current count.
- `zone_counters` bumped from loaded zone IDs on bundle load (in addition to the ribbon populate path) so future naming doesn't collide.
- All zone ID handling now consistently uses Python `int` keys.
- The left File Browser accessory flow (double-click paint child) continues to chain TIFF load + bundle restore correctly.

These changes make the "draw or load painted regions with names → Count Cells" workflow on TIFFs (including via `.barccpaint` bundles that carry both visuals and labeled shapes) production-ready.

## Other Notes
- Version string in code and exported settings JSON updated to "8.05.000".
- README.md updated with v8.05.000 section.
- Release notes added (this file).
- BARCC_User_Manual.pdf and generator may be updated in a follow-up if new "What's New" text is desired; core behavior is documented in the code comments and this note.
- No changes to requirements or installation.

## Requirements
Unchanged.

## Preparing / Installing the Release
- Source, this release note, updated README are in the repository.
- Git tag: v8.05.000 (to be created on push)
- Run `py -3.12 barcc.py` (or your normal launcher) from the Application directory.