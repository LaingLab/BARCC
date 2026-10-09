# BARCC v8.11.001

Batch Recalculate Intensities now writes a new timestamped workbook for every run. Earlier intensity files stay on disk.

## Highlights

### Timestamped batch outputs
- **Axons and Nets → Batch Recalculate Intensities…** still remeasures every TIFF that already has `output/paint/{image}_paint_with_regions.barccpaint`, without opening each image.
- Each image is saved as `output/intensities/{image}_intensities_YYYYMMDD_HHMMSS.xlsx`. Every file from one run shares the same timestamp.
- The run also writes a new master workbook. With **File → Select Project Output Directory** set, that file is `{project folder}/{project name}_Intensities_YYYYMMDD_HHMMSS.xlsx`. Otherwise it is `output/intensities/{folder name}_Intensities_YYYYMMDD_HHMMSS.xlsx`.
- The existing `{project name}_Intensities.xlsx` and the untimestamped `{image}_intensities.xlsx` from Measure Region Intensities are left in place.
- Measuring one open image still updates those untimestamped files.
- The File Browser lists the timestamped workbooks under the TIFF.

## Documentation
- Manual Chapter 9 (Batch Recalculate Intensities) and the What's New 8.11.001 section describe the timestamped names.
- README highlights name 8.11.001 as the current release.

## Files
- `Application/barcc.py` — batch intensity export uses a shared timestamp and writes a new master workbook.
- `docs/generate_barcc_manual.py` — user manual source.
- `BARCC_User_Manual.pdf` — regenerated for 8.11.001.
- `README.md` — version highlights.
- `release-notes-v8.11.001.md` — this file.
- Version string: **8.11.001**.

## Requirements / Running

Unchanged from v8.11.000. Python 3.14 conda env `barcc314`:

```bash
conda env create -f environment.yml
conda activate barcc314
cd Application
python barcc.py
```

An existing Git clone updates with **File → Update**, or from the BARCC folder:

```bash
git pull
```

## Notes
- Tag: **v8.11.001**
- Builds on v8.11.000 (in-app update and batch intensity recalculation).
