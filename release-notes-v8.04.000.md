# BARCC v8.04.000

Feature release focused on precision editing and reliable undo for custom painted regions, plus UI clarity improvements for paint mode and advanced border tools.

## Highlights

### Painted Region Border/Edge Expansion with Enter-to-Commit
- Live border drag (or the red local edge segment when "Border drag resize enabled" is checked) provides real-time preview of the yellow/orange highlighted zone mask shape as you expand, shrink, or deform the boundary.
- The original black drawn boundary line remains at its previous position during the live adjustment (clear visual before/after).
- After releasing the mouse, **press Enter** (or keypad Enter) to commit the final shape: the current mask contour is extracted, the stored painted zone outline points are updated, `_rebuild_paint_layer_from_data()` re-rasterizes a clean black boundary line (with proper caps and joints) from the new points, and `show_page()` redraws it. This automatically refits the visible black outline exactly to the new expanded/deformed region.
- The mask/zone data (used for counting and tints) was already updated by the drag; Enter "bakes" and refits the black visual boundary for the painted region.
- Works for both the precise edge-grab path and the legacy one-sided border pull. Also supported after "Move Selected Region" translates of painted zones.

### Undo Button + Repeated Undo for Painted Regions
- New prominent ↶ Undo button in the Atlas Manager ribbon header (always visible when the ribbon is shown via View menu). Also exposed in the Edit menu with Ctrl+Z accelerator.
- Full per-stroke granularity: each continuous paint stroke (mouse down to up = one group) gets its own undo checkpoint at the start of drawing.
- Naming a painted region (right-click), Stop Paint (auto-default "Painted Region N" conversion), Count Cells (force conversion of remaining strokes), border/edge deformations, and Move Selected on painted zones are all first-class undoable actions.
- Bounded history (40 levels). The Atlas Manager "Labeled Regions" list/header, zone/mask data, and visual black boundaries now stay perfectly in sync after each undo step. No more unexpected batch removal of multiple paints.
- Keyboard Ctrl+Z (and the button) continue to work for all prior atlas, mask-edit, and global operations.

### UI Clarity
- "Border drag resize enabled" checkbox (in the Atlas Manager ribbon, under the selected region tools) now starts **unchecked** by default. You must explicitly enable it after selecting a region before edge or one-sided border drag tools become active. This prevents accidental activation of the advanced editing mode.
- Paint mode indicator: When the Paint tool is active (Paint > Start Paint), a clear "🎨 PAINT ON" label appears in bold red in the ribbon header. The main window title also updates to include " — 🎨 PAINT MODE". The indicator automatically returns to normal (gray "Paint: off") when you Stop Paint or switch tools. The title-bar version remains visible even if you hide the ribbon.

### Edge / Border Tools for Painted Regions
- Edge grab, border drag, Move Selected Region, quick per-region rotate/scale, and related tools now work fully for painted regions (in addition to atlas regions) with correct coordinate space handling (background/image pixel space vs. atlas page model space).
- Combined with the Enter commit flow, you can now iteratively refine the shape of hand-painted custom regions and have the black visual boundary automatically follow the final mask contour.

### Robustness
- Undo stack snapshots, mask pruning on restore (to prevent the orphan auto-registration logic in the ribbon list from re-adding removed painted zones), and state hygiene around paint naming/finalization and border operations.
- All new paint editing paths participate in save_state at the appropriate moments (start of stroke, start of border interaction, etc.) and correctly refresh the ribbon list, canvas, and paint_layer on undo/redo.

These features make iterative, high-precision work with custom painted regions (with live mask preview + explicit commit for the visible black boundary) reliable and user-friendly, while preserving the full power of the Atlas Manager ribbon for atlas-based work.

## Other Notes
- Version string in code and exported settings JSON updated to "8.04.000".
- User Manual fully regenerated with new "What's New in Version 8.04.000" section (covering the Enter-to-commit painted boundary refit flow, undo button, paint indicator, checkbox default change, and painted region edge support) plus updates to the "7. Paint Tools" and "6. Working with Atlas Sections" chapters.
- README.md top-level highlights updated.
- See previous release notes (v8.03.000 for the Atlas Manager ribbon, v8.02.x for Paint reliability) for earlier features.

## Requirements
Unchanged.

## Preparing / Installing the Release
- Source, updated manual (BARCC_User_Manual.pdf), this file, and updated README are in the repository.
- Git tag: v8.04.000
