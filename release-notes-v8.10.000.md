# BARCC v8.10.000

Atlas alignment, Dual Settings, and project-counts release on top of v8.09.000 detection tools.

## Highlights

### Dual Settings Mode (Config A / Config B)
- **Dual Settings Mode** in Mask Settings shows a second Blob/Adaptive panel (Config B). The first enable copies A → B.
- Assign labeled regions in Atlas Manager: select a region and press **A** or **B** (ignored while typing in an entry). Or Use Config A / Use Config B.
- Show Mask / Count Cells run Config A in A-regions and Config B in B-regions, then merge label maps (unique IDs). Unassigned regions default to A.
- **Smart Suggest A / Smart Suggest B** appear when Dual Settings and Smart Suggest **Labeled regions only** are both on.
- Autotune can target A, B, or both.
- Zone A/B assignments are stored with paint bundles. Off = one global detector.

### Practical atlas alignment stack
- **Atlas → Align: Landmarks (point pairs)…** — click atlas (magenta) then matching tissue (cyan). Use 3–6 pairs (minimum 2). Undo pair / Apply Fit / Esc. Similarity transform (scale + rotation + translation). Pairs survive zoom and can prior Edge Snap.
- **Atlas → Align: Edge Snap…** — snap atlas silhouette to tissue (ICP / chamfer). Preview first, then Apply; Restore undoes a preview. Refine current pose vs From scratch; Allow Translate / Rotate / Scale; partial overlap; auto tissue polarity or force invert; tightness; holes; per-region only; flip L/R.
- **Atlas → Align: Local Refine (guide)…** — turns Border drag resize on after global pose is close; per-structure border drag / Move Selected / optional per-region Edge Snap.
- Recommended order: Fit Atlas to Image → Landmarks → Edge Snap Preview/Apply → Local Refine. These tools were deferred in v8.09.000.

### Crop box aspect lock
- With Global Crop on, lock the crop rectangle to Match TIFF, 1:1, 4:3, 3:2, 16:9, or custom W×H. Uncheck for a free-form box. Pending boxes re-shape when the ratio changes.

### Extra blob quality filters and Adaptive region mode
- `blob_tissue_margin` — reject peaks N pixels inside the outer slice border (bright edge-line FPs).
- `blob_max_elongation` — reject thin ridges (folds, fibers, cut-edge line).
- `blob_ridge_reject` / `blob_ridge_thresh` — Hessian ridge test (white midline / knife line).
- `blob_cavity_rim` — kill zone around air-bubble bites (not ventricle-adjacent nuclei except peaks in the lumen).
- `blob_chain_reject` — 1-D line/ring suppression; packed 2-D clusters kept.
- `blob_cluster_recover` / `blob_seed_snr` / `blob_recover_factor` — bright seeds keep dim neighbors in dense patches.
- `adaptive_region_mode` — per painted/atlas zone instead of square tiles; unlabeled tissue not labeled.
- **Labeled regions only** (Blob Detection) — Show Mask / Count Cells only inside painted or atlas regions.
- Autotune extras: Denser packing, Sparser packing, Background higher.

### Project counts spreadsheet
- **File → Select Project Output Directory** — folder + project name → `{folder}/{project name}_Counts.xlsx`.
- Sheet **Project Counts**: column File plus one column per unique structure; each later row is one image. Re-counting the same file replaces that row.
- Per-image workbooks under `output/counts/` are still written. If the combined `.xlsx` is open in Excel, BARCC writes a CSV next to it.

### File Browser and cell-mask UX
- Right-click TIFF: **Exclude** / **Include** (skip in Next Uncounted; stored under `~/.barc/`).
- **Reload last count (paint, mask, config)** and **Cell → Reload Last Count Session…** restore the last Count Cells artifacts. Restored cell mask is locked until Show Mask.
- **View → Show Cell Mask** toggles red detection rings without re-detecting; overlay survives zoom/pan.
- **Add Cell** traces a nucleus at the click; brush 1–10 tightens or expands the fill (4 = traced shape). Remove remains yellow/gold.

## Documentation
Manual, README, and the parameter reference match this release:

- README basic usage uses the **Cell** menu (not Mask), the alignment order Fit → Landmarks → Edge Snap → Local Refine, Dual Settings **A** / **B**, and File → Select Project Output Directory.
- The user manual separates the Watershed **Adaptive** threshold window from the Blob/DoG **Adaptive** checkbox. Blob num sigma default is **15**. Cluster-recover seed SNR default is **0.85**. Base Multiplier and Sensitivity Range are not in Mask Settings.
- Background correction documents tophat, gaussian, and none.
- `mask_settings_documentation.md` lists 8.10.000 defaults. **Dialog** fields have a Mask Settings row. **Engine** fields (`blob_tissue_margin`, `blob_recover_factor`, `adaptive_tile_overlap`, and the others named in the manual) are still applied and can be changed by Smart Suggest or Import Settings.
- `BARCC_User_Manual.pdf` regenerated from `docs/generate_barcc_manual.py`.

## Files
- `Application/barcc.py` — Dual Settings, alignment stack, project counts, extra filters, File Browser, mask overlay.
- `docs/generate_barcc_manual.py` — user manual source.
- `BARCC_User_Manual.pdf` — regenerated for 8.10.000.
- `README.md` — version highlights and current basic usage.
- `mask_settings_documentation.md` — detection parameter reference.
- `release-notes-v8.10.000.md` — this file.
- Version string: **8.10.000**.

## Notes
- Dual Settings requires the checkbox on **and** A/B region tags before Show Mask / Count Cells will split configs.
- Edge Snap: Preview before Apply; use Refine after Landmarks; From scratch only if pose is still far off.
- Close the combined project workbook in Excel while counting if you want live `.xlsx` updates.
- v8.09.000 Adaptive / Area Tune / Measure Tune / Smart Suggest remain the detection baseline.

## Requirements / Running
From `Application/` (example):

```text
conda activate barcc314
python barcc.py
```

or use `Launch_BARCC.bat`. See `requirements.txt` / `environment.yml`.

## Git
- Tag: **v8.10.000**
- Previous: **v8.09.000** — see `release-notes-v8.09.000.md`
