# BARCC v8.11.000

In-app update and batch region-intensity recalculation, plus the intensity export finished after v8.10.000.

## Highlights

### File → Update
- **File → Update** checks GitHub and fast-forwards this install when the folder was created with `git clone`.
- Close BARCC and open it again after the dialog says it updated. The running copy does not reload itself.
- A **Download ZIP** folder has no `.git` directory. The dialog tells you to clone once and keep using that folder. Images and `output` folders are outside the program folder and are not replaced.
- If `environment.yml` or `requirements.txt` changed, the dialog says to run `conda env update -f environment.yml --prune` in the `barcc314` environment.
- Local edits inside the BARCC folder ask before updating. Local commits are not merged or overwritten.

### Batch Recalculate Intensities
- **Axons and Nets → Batch Recalculate Intensities…** remeasures every TIFF in a folder that already has `output/paint/{image}_paint_with_regions.barccpaint`.
- Images are not opened in the viewer. Regions come from the saved paint bundle.
- The background percentile (typical 5–20) is the main control. Counterstain normalization is optional.
- Each `output/intensities/{image}_intensities.xlsx` is overwritten.
- When **File → Select Project Output Directory** is set, `{project}_Intensities.xlsx` is updated and that image's rows are replaced. Otherwise BARCC writes `output/intensities/{folder name}_Intensities.xlsx`.
- TIFFs with no paint file are skipped and listed.

### Region intensity export
- **Measure Region Intensities** writes one file, `output/intensities/{image}_intensities.xlsx`, with one sheet, **Region Intensities**. The extra `{image}_region_intensity.xlsx` copy is no longer written.
- The same command overwrites `output/paint/{image}_paint_with_regions.barccpaint` and, when an atlas or labeled zones are loaded, `output/atlas/{stem}_atlas.catlas`.
- **File → Select Project Output Directory** also receives `{project name}_Intensities.xlsx`. Column A is **Image**. The remaining columns match the per-image sheet. One row per region. Re-measuring replaces that image's rows.
- **Edit → Brightness** and zoom change the display only. The measurement uses the original TIFF grayscale. The mean includes every pixel in the region, so a uniform haze can score higher than sparse axons until background subtraction is on.

## Documentation
- README **Download and start using BARCC** and manual Chapter 2 give the clone, conda, and first-session steps, plus **File → Update**.
- Manual Chapter 9 describes the single intensity sheet, the project workbook, paint/atlas autosave, and batch recalculation.

## Files
- `Application/barcc.py` — File → Update, batch intensity recalculation, one-sheet intensity export, project intensity workbook, paint and atlas autosave.
- `docs/generate_barcc_manual.py` — user manual source.
- `BARCC_User_Manual.pdf` — regenerated for 8.11.000.
- `README.md` — version highlights and update instructions.
- `release-notes-v8.11.000.md` — this file.
- Version string: **8.11.000**.

## Requirements / Running

Unchanged from v8.10.000. Python 3.14 conda env `barcc314`:

```bash
conda env create -f environment.yml
conda activate barcc314
cd Application
python barcc.py
```

On Windows, `Application/Launch_BARCC.bat` is an optional double-click launcher. On a new computer, start from Anaconda Prompt with `barcc314` active.

An existing Git clone updates with **File → Update**, or from the BARCC folder:

```bash
git pull
```

## Notes
- Tag: **v8.11.000**
- Builds on v8.10.000 (Dual Settings, atlas alignment, project cell counts).
