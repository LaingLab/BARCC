# BARCC v8.03.000

Major release introducing the Atlas Manager ribbon for advanced per-region and global editing of atlas overlays, plus UI improvements for mode awareness and numerous workflow robustness fixes.

## Highlights

### Atlas Manager Ribbon (new central UI for atlas work)
- New expandable/collapsible Atlas Manager ribbon (View menu "Show Atlas Manager Ribbon" toggle to show/hide entirely).
- Header shows currently selected region (or "No region selected").
- **Global tools now checkboxes** (Crop, Move) — checked state clearly indicates when whole-atlas modes are active (rebinds canvas for crop rect or layer drag via img_x/img_y).
- "Move Selected Region" checkbox + drag inside orange tint: translates *only* the selected zone's mask pixels. Atlas artwork, other regions, and background stay fixed.
- "Border drag resize enabled" checkbox: arms precise edge editing.
- **Global Quick Adjust** (new): Rot +5°/-5°, Scale +5%/-5% buttons for the *entire* current atlas page (base + all masks), plus "Dialogs..." to global rotate/scale settings.
- Selectable list of all labeled regions on the page — click to select for editing (orange highlight, updates header/list).
- Selected Region Quick Adjust (Rot +/-5°, Scale +/-5%, Dialogs...) — applies only to the chosen zone (centroid-preserving).
- Automatic mutual exclusion: enabling border/edge features deselects global Move (and Crop); enabling globals unchecks border drag. Prevents overlapping/confusing behaviors.

### Per-Region Atlas Editing (select + fine control)
- Select regions via: canvas click on named (yellow) area (now autoselects instead of re-naming prompt), ribbon list, or Atlas > Select Region (temporary picker).
- Quick per-region rotate/scale.
- **Edge grab & local deformation**: Click near border of selected (orange) region → illuminates local red edge segment (persistent). Click red to re-center grab point. Drag red to locally expand/shrink only that boundary portion (falloff weights for smooth blend). Live shape update of tint during drag. Release commits to mask.
- "Move Selected Region" for translation-only of one zone.
- Works alongside global alignment.

### Global Quick Adjust (mirrors regional)
- Added to ribbon under Global: small-increment Rot +/-5° and Scale +/-5% for whole atlas page + masks (same style as selected-region quick adjust).
- "Dialogs..." for full settings.

### Menu & Other Changes
- Import Atlas moved under new top-level **Atlas** menu (along with Crop, Move, Rotate, Scale, Select/Deselect Region, Rotate/Scale Selected, etc.) for logical grouping.
- Many state/binding fixes: atlas crop now uses proper model coords + rebases layer (no disappearing atlas); load image *after* atlas no longer breaks global Move due to stale selection/edge state (full clears added to import_tiff/_load_tiff_file); forgiving edge hit tests (zid==0 boundary pixels still trigger grab if near selected); delegation so per-region features work even under global edit bindings; hygiene clears everywhere (page change, deselect, imports, crop, etc.).

### Robustness
- Edge grab, move-selected, crop, etc. now reliable across load orders, zooms, pans, and previous selections.
- Checkboxes + orange selection + list + header provide clear at-a-glance feedback on active context and armed tools.

These features make fine-grained atlas region correction practical while keeping global tools obvious and non-conflicting.

## Other Notes
- Version string in code and exported settings JSON updated to "8.03.000".
- User Manual fully regenerated with new "What's New in Version 8.03.000", expanded "6. Working with Atlas Sections" chapter documenting the ribbon, global/per-region quick adjust, edge grab, move-selected, checkboxes/mutual exclusion, etc., plus File menu note about Atlas menu reorganization.
- README.md top-level highlights updated.
- See previous release notes for Paint reliability (v8.02.00x) and earlier features.

## Requirements
Unchanged from v8.02.

## Preparing / Installing the Release
- Source, updated manual (BARCC_User_Manual.pdf), this file, and updated README are in the repository.
- Git tag: 8.03.000
- GitHub release will include these notes and the updated manual.

See release-notes-v8.02.002.md etc. for prior changes.
