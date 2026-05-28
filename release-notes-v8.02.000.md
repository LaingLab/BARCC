# BARCC v8.02.000

This is a focused stability and reliability release that makes the Paint tool for custom regions fully trustworthy for quantitative work, plus a critical crash-prevention fix.

## Highlights

### Painted Region / Zone System Overhaul
- **Reliable zone registration**: Regions you draw with the Paint tool and name immediately via right-click now correctly and consistently appear in the output spreadsheet when you click Count Cells.
- **Automatic paint stop + conversion**: Count Cells now guarantees that paint mode is stopped and *all* strokes (explicitly named + auto-default "Painted Region N") are converted into countable zones.
- **Full state isolation**: Every new TIFF loaded (via the left File Browser or Import) completely wipes previous masks, zone names, counters, and paint data. No more leakage between images.
- **Durable paint geometry**: Strokes are now stored in stable model/image coordinates. They survive zooming, panning, and canvas refreshes.
- **Accurate interior counting**:
  - Painted outlines now receive proper interior filling using `scipy.ndimage.binary_fill_holes`.
  - Cell-to-zone assignment uses a small neighborhood search around each centroid for tolerance.
- **No duplicate zones**: Processed paint groups are retired after conversion, eliminating cases where 3 drawn regions would produce 6 entries.

### Critical Stability Fix
- **Progress dialog safety**: Closing the "Counting Cells" or "Detecting Cells" progress window with the X button (or Alt+F4) before the operation completes can no longer crash the entire application. All progress UI methods are now fully defensive.

## Summary of Changes
These fixes primarily targeted long-standing fragile areas in the paint → named group → zone mask → counting pipeline that had caused:
- "No regions defined" errors even after naming zones
- Severe under-counting (e.g., 30 visible cells inside a region yielding only 1 count)
- Duplicate zones in exports
- Application crashes on early dialog dismissal during long operations

The Paint tool (for defining custom non-atlas regions) is now considered production-ready.

## Other Notes
- Blob Detection remains the default method (introduced in 8.01).
- All previous automatic export behavior (`.xlsx` + `_masked.tif`) continues unchanged.
- The User Manual has been fully updated for v8.02.000.

## Requirements
For full `.xlsx` support with the Detection Parameters metadata sheet:

```
pip install openpyxl xlsxwriter
```

Full updated manual (BARCC_User_Manual.pdf) and source are included in the repository.

---

**Previous release**: See `release-notes-v8.01.000.md` for the Blob Detection, Smart Suggest, File Browser, and export features introduced in 8.01.000.