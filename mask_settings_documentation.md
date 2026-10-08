# Mask Settings Documentation

Parameter reference for BARCC **8.10.000** (Cell > Show Mask Settings). Defaults below are the values shipped in `CellDetectionConfig` / `PreprocessingConfig`. Hover any control in the dialog for the same help text.

**Dialog** means the field has its own row or checkbox in Mask Settings. Fields marked **engine** are still applied during detection and can be changed by Smart Suggest or by Import Settings, but they are not a separate row.

Inactive method panels are dimmed and locked. Watershed parameters do not apply while Blob or DoG is selected, and the Adaptive checkbox is disabled under Watershed.

Two different controls share the word "adaptive":

- **Adaptive** (checkbox on Blob / LoG or DoG) is tiled / dual-pass detection. It is not a third detection method.
- **Adaptive block size** is the Watershed local-threshold window. It is used only when Detection Method is Watershed and Threshold Method is adaptive.

## Detection method

| Field | Default | Meaning |
| --- | --- | --- |
| `detection_method` | `blob` | `blob` = Laplacian of Gaussian; `dog` = Difference of Gaussians; `watershed` = classic threshold pipeline. |
| `adaptive_enabled` | 0 (off) | When 1, and the method is Blob or DoG, detection uses tiled thresholds, optional dual-pass fusion, and density packing. |

## Dual Settings Mode

Checkbox at the top of Mask Settings. Off = one global detector.

- Checking it shows Config B (Blob / Adaptive) to the right of Config A. The first time it is enabled, B is copied from A.
- Assign a labeled region in Atlas Manager: select it and press **A** or **B** (ignored while typing in an entry), or Use Config A / Use Config B.
- Show Mask and Count Cells run Config A in A-regions and Config B in B-regions, then merge the label maps. Unassigned regions use A.
- **Smart Suggest A** and **Smart Suggest B** appear when Dual Settings Mode and Smart Suggest **Labeled regions only** are both on.
- Autotune can target A, B, or both.
- A/B tags are stored with paint bundles.

## Blob / DoG parameters

Shown when the method is Blob or DoG. With Dual Settings Mode on, Config A and Config B each have this set.

| Field | Where | Default | Meaning |
| --- | --- | --- | --- |
| `blob_threshold` | Dialog | 0.05 | Absolute sensitivity. Lower finds dimmer cells (more detections). Typical range about 0.02–0.20. |
| `blob_threshold_rel` | Engine | 0 (off) | If > 0, keep peaks above this fraction of the strongest response (0–1). |
| `blob_min_sigma` | Dialog | 2.0 | Smallest blob scale. Lower finds smaller spots. About 1–3 for fine cells. |
| `blob_max_sigma` | Dialog | 12.0 | Largest blob scale. Raise (for example 12–20) if large bright cells are missed. |
| `blob_num_sigma` | Dialog | 15 | Scales between min and max sigma. LoG only. More scales are finer and slower. |
| `blob_log_scale` | Engine | 1 | 1 = geometric sigma spacing (more samples at small sizes). 0 = linear spacing. |
| `blob_overlap` | Dialog | 0.5 | Allowed overlap between blobs (0–1). Lower removes nearby duplicates more aggressively. |
| `blob_min_area` | Dialog | 8 | Minimum estimated cell area (π·r² from sigma). Raise to drop tiny noise. |
| `blob_max_area` | Dialog | 500 | Maximum estimated cell area. Raise if large real cells are filtered out. |
| `blob_min_circularity` | Dialog | 0.30 | Local shape circularity. 0 = off, 1 = a perfect circle. Typical cells score about 0.6–0.9. Raise to 0.55–0.75 to reject merged doublets. Values above 1 are treated as 0.80. This is not the Watershed circularity box. |
| `blob_radius_scale` | Engine | 1.8 | Mask disk radius ≈ sigma × this value. Larger draws bigger rings. |
| `blob_free_space` | Dialog | 0.45 | Spacing between packed cells (0.05–0.95). Higher requires more space between centers (0.6–0.75 if marks look too tight). Lower allows denser packing (0.15–0.3). This is the main packing knob; Adaptive packing only eases it slightly. |
| `blob_min_peak_intensity` | Engine | 0 (off) | Require normalized intensity at the peak ≥ this (0–1). |
| `blob_exclude_border` | Engine | 1 | Ignore detections within this many pixels of the image edge. 0 keeps border cells. |
| `blob_labeled_regions_only` | Dialog checkbox | off | Show Mask / Count Cells only inside painted or atlas regions, each with its own local threshold. Unlabeled tissue is not masked. Separate from Smart Suggest's labeled-regions checkbox, and separate from the Dual Settings switch. |

### Area Tune (sets min / max area)

Mask Settings > Area Tune. Draw **10** independent diameter lines, one per representative cell. BARCC sets `blob_min_area` / `blob_max_area` to **0.7×–1.5×** the mean area (π·r²). The result is kept for the session so Smart Suggest can prefer those bounds. **Measure Tune does not overwrite Area Tune size bounds** when both have been used. Esc or Finish exits.

## Peak quality filters

These gates run on candidate peaks after LoG/DoG. They are the main way to cut false positives on high background, tissue edges, folds, and knife lines.

| Field | Where | Default | Meaning |
| --- | --- | --- | --- |
| `blob_min_local_snr` | Dialog | 0 (off) | (mean core − mean surround) / std surround. Raise (about 1.5–3.5, sometimes 2–5) to reject bright background that is not brighter than its neighbors. |
| `blob_local_snr_outer` | Engine | 2.0 | Surround annulus runs from cell radius r to r × this value. |
| `blob_bg_relative` | Dialog | 0.06 | Peak minus local median on a 0–1 image. 0 = off. Try 0.08–0.18 on high-background texture. |
| `blob_min_isotropy` | Dialog | 0.30 | Radial symmetry. 0 = off, 1 = perfect. Rejects tissue-edge and fiber peaks that are bright on one side. Try 0.30–0.55. |
| `blob_reject_tissue_edge` | Dialog | 1 (on) | Reject peaks whose outer ring is partly near-black (section border). A fully dark field is not treated as "outside". 0 allows border peaks. |
| `blob_edge_dark_frac` | Engine | 0.40 | With tissue-edge reject on: max fraction of the outer ring that may be near-black. Lower (0.25–0.35) is stricter. |
| `blob_tissue_margin` | Engine | 0 (off) | Integer pixels *inside* the outer slice border to reject (bright edge-line false positives). Try 6–12, or 15–25 for a thick glow. Smart Suggest can set this. |
| `blob_max_elongation` | Dialog | 3.0 | Max major/minor axis ratio (1 = circle). Rejects folds, fibers, and the cut-edge line. 0 = off. Nuclei are typically 1–2. Lower is stricter. |
| `blob_ridge_reject` | Dialog | 1 (on) | Hessian ridge test. Removes the white midline, section folds, vessels, and knife lines. 0 = off. |
| `blob_ridge_thresh` | Dialog | 0.40 | Ridge strength cutoff (0–1). 0 = off. Lower drops more line-like marks. Typical 0.35–0.55. Raise if round cells sitting on a fold are lost. |
| `blob_cavity_rim` | Dialog | 12 | Kill zone (pixels) around air-bubble bites in the section edge. Does not clear nuclei next to a ventricle except peaks actually in the lumen. 0 = off. Raise to 16–32 if bubble-rim marks remain. |
| `blob_chain_reject` | Dialog | 1.0 | 1-D line/ring suppression (ventricle wall, bubble rim, fold). 0 = off, 1 = default, 2–3 = stronger. Packed 2-D clusters are kept. |
| `blob_cluster_recover` | Dialog | 1 (on) | Two-tier placement: a bright nucleus seeds a dense patch and dim neighbors are kept. Isolated cells in sparse tissue stay if they look like cells. Crowded speckle without a seed is dropped. 0 keeps every peak that passed the quality gates. |
| `blob_seed_snr` | Dialog | 0.85 | SNR required to seed a **dense** patch. Sparse isolated cells use a milder bar automatically. Lower if packed clusters are still missing members. |
| `blob_recover_factor` | Engine | 3.8 | A non-seed peak is kept if it is within (factor × typical radius) of a seed. About 3.5–4.5 fills a cluster without sweeping distant speckle. |

## Adaptive overlay

Used only when **Adaptive** is checked and the method is Blob or DoG. Autotune More/Less Cells nudges these knobs when Adaptive is on.

| Field | Where | Default | Meaning |
| --- | --- | --- | --- |
| `adaptive_tile_size` | Dialog | 256 | Tile edge in pixels. Smaller tiles follow local background more; larger tiles are smoother and faster. Typical 192–384. |
| `adaptive_tile_overlap` | Engine | 0.3 | Fractional overlap between tiles (0–0.5). Higher overlap reduces misses where tiles meet. |
| `adaptive_sensitivity` | Dialog | 1.0 | Global multiplier. < 1 lowers tile thresholds (more cells). > 1 is stricter. |
| `adaptive_packing` | Dialog | 0.5 | 0 = sparse (more free space). 1 = dense clusters. About 0.5 is balanced. |
| `adaptive_dual_pass` | Dialog | 1 (on) | 1 = sensitive pass plus strict pass, then fuse. Best for mixed high/low background. 0 = a single adaptive pass. |
| `adaptive_region_mode` | Dialog | 0 | 0 = square tiles over the whole image. 1 = one window per painted or atlas zone, each with its own threshold and SNR. Unlabeled tissue is not labeled. Requires Adaptive on and existing zones, then Show Mask. |
| `adaptive_base_method` | Engine | `blob` | Legacy import/export field. At runtime the Blob/DoG radio chooses the base detector. |

## Measure Tune (TP / FP / FN / TN)

Label the **current** mask after Show Mask or Smart Suggest. Detection rings stay visible while you label. Apply runs in a progress dialog. Labels are stored for Smart Suggest (threshold, sigma, SNR, packing).

| Mark | Color | Meaning |
| --- | --- | --- |
| TP | green | Correct detection |
| FP | orange | False mark |
| FN | blue | Missed cell |
| TN | gray | True empty background |

Passes:

- **Precision:** FP + TN only (at least 2 should-not marks). Tightens threshold, SNR, and quality gates.
- **Recall:** TP + FN only (at least 2 should-detect marks). Recovers missed cells.
- **Full:** both sides.

On large TIFFs, Measure Tune uses a local-patch LoG rather than a full-frame LoG. Expert images with mixed background often need both a precision pass and a recall pass, then manual add/remove inside ROIs.

## Smart Suggest

Cell > Show Mask Settings > Smart Suggest (pre-tuning smart settings). Analysis stays on this computer. Each suggestion has a checkbox (Apply All, Apply checked, or Close).

As of 8.09 / 8.10 it also:

- Diagnoses bright vs dark tiles (peaks vs detections) and offers named recipes: mixed_both, high_bg_fp, low_bg_fn, recover_clusters, global over/under.
- Suggests Adaptive, dual-pass, SNR, threshold, and packing together. It can turn `adaptive_enabled` on when the image supports it.
- Remembers the last Apply (for example, easing SNR after a strict high-background pass).
- Prefers Area Tune and Measure Tune size bounds over sizes derived from LoG alone.
- **Labeled regions only:** estimate parameters from painted/atlas pixels. This does not by itself restrict Show Mask.
- With Dual Settings Mode and labeled-regions-only both on: Smart Suggest A and Smart Suggest B each fit their own region group.

## Autotune

Buttons adapt to Blob vs Watershed, and to Adaptive when that checkbox is on. In Dual Settings Mode, A/B checkboxes choose which config is changed.

- More cells / Less cells
- Bigger cells / Smaller cells
- Brighter cells / Dimmer cells
- Denser packing / Sparser packing
- Background higher

Autotune steps are conservative. Smart Suggest, Area Tune, and Measure Tune are the better starting point on a difficult image.

## Manual add / remove

- **Add Cell** is red. A click traces the nucleus; brush size 1–10 tightens or expands the fill (4 = the traced shape).
- **Remove Cell** paint is yellow/gold.
- The detection mask stays visible under the brush, including while zooming.
- Combination rule: (automatic mask OR add) AND NOT remove.
- View > Show Cell Mask toggles the red rings without re-detecting. Cell > Show Mask re-detects and unlocks a loaded mask.

## Watershed parameters (legacy)

Used only when Detection Method is Watershed.

### Threshold method

`threshold_method` default: `otsu`.

- **otsu** — global threshold from Otsu's method.
- **adaptive** — local window. See Adaptive block size. This is not the Blob Adaptive checkbox.
- **local** — neighborhood threshold. See Local radius.
- **manual** — fixed level. See Manual threshold.

| Field | Default | Meaning |
| --- | --- | --- |
| `manual_threshold` | 0.5 | Fixed intensity (0–1 after preprocess). Higher = fewer pixels counted as cells. Used only when the method is manual. |
| `adaptive_block_size` | 101 | Watershed adaptive window in pixels. Must be odd (for example 51, 101, 151). Larger windows track slow background changes. Recommended about 51–151. |
| `local_radius` | 15 | Neighborhood radius for the local method. Typical 5–30. Larger is smoother and can miss small cells. |
| `min_cell_size` | 20 | Minimum object area (pixels) kept after thresholding. |
| `max_cell_size` | 100 | Maximum object area (pixels). Larger clumps are rejected. |
| `circularity_threshold` | 0.7 | Shape filter (0–1). Higher keeps rounder objects. 1.0 is a perfect circle. |
| `min_peak_distance` | 5 | Minimum distance between cell centers (pixels). Lower splits dense clusters more. Typical 5–10. |
| `peak_min_intensity` | 0.1 | Minimum peak height on the distance map (0–1). Higher keeps only brighter centers. |
| `watershed_compactness` | 0.0 | Higher prefers more circular watershed basins (0–1). |

There is no Base Multiplier or Sensitivity Range control. Blob sensitivity is `blob_threshold`. Adaptive sensitivity is `adaptive_sensitivity`.

## Preprocessing

Applied before detection. The dialog shows parameters for the selected method only.

| Field | Default | Meaning |
| --- | --- | --- |
| `background_method` | `tophat` | `tophat`, `gaussian`, or `none`. |
| `disk_radius` | 15 | Ball / disk radius (pixels) for tophat. Larger removes broader background. |
| `bg_gaussian_sigma` | 1.0 | Sigma when background method is gaussian. |
| `denoise_method` | `gaussian` | `gaussian`, `median`, `bilateral`, or `none`. |
| `nr_gaussian_sigma` | 1.0 | Gaussian blur amount (typically 0.1–5.0). Used when denoise is gaussian. |
| `median_kernel` | 3 | Median kernel size. Used when denoise is median. |
| `bilateral_sigma_color` | 0.1 | Color sensitivity (typically 0.1–1.0). Used when denoise is bilateral. |
| `bilateral_sigma_space` | 1.0 | Spatial sensitivity (typically 1–10). Used when denoise is bilateral. |
| `contrast_method` | `stretch` | `stretch`, `clahe`, `gamma`, or `none`. |
| `clahe_kernel` | 8 | Local CLAHE window (typically 8–16). |
| `clahe_clip_limit` | 2.0 | CLAHE contrast limit (typically 1–4). |
| `gamma` | 1.0 | Gamma correction. < 1 brightens mid-tones; > 1 darkens them. |
| `enhance_method` | `unsharp mask` | Unsharp mask, or none. |
| `unsharp_radius` | 1.0 | Spatial scale of the unsharp mask (typically 0.1–5). |
| `unsharp_amount` | 2.0 | Sharpening strength (typically 0.1–5). Higher can create halos. |

## Export

Export Settings / Import Settings write a portable JSON of the active detection and preprocessing settings (including Dual Settings and Adaptive fields when present). That file is separate from local presets in `~/.barc/presets.json`.

Count Cells records the same parameters on the Detection Parameters sheet of the per-image workbook.
