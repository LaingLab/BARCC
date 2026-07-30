# BARCC v8.09.000

Cell detection and Mask Settings release: Adaptive detection, Area Tune, Measure Tune (TP/FP/FN/TN), smarter Smart Suggest, peak quality filters, and UX fixes for masks and editing.

## Highlights

### Adaptive detection (Blob/DoG overlay)
- **Adaptive** is a checkbox on Blob / LoG or DoG (not a separate radio method).
- Tile-local thresholds, optional **dual-pass** (sensitive + strict), density-aware packing.
- Parameters: tile size/overlap, sensitivity, packing, dual-pass.
- Autotune More/Less Cells nudges adaptive knobs when Adaptive is on.

### Peak quality filters (fewer FPs on high BG / edges)
- **Local SNR**, **bg relative** (peak vs local median), **isotropy**, **circularity**.
- **Tissue-edge reject** (bimodal outer ring; does not treat pure dark-field as “outside”).
- Defaults tuned for mixed high/low background immunofluorescence.

### Area Tune
- Draw **10 independent diameter lines** (one per cell).
- Sets `blob_min_area` / `blob_max_area` to **0.7×–1.5×** mean area (π·r²).
- Results are stored for the session so **Smart Suggest** can prefer those area bounds.
- **Measure Tune does not overwrite Area Tune** size bounds when both have been used.

### Measure Tune (TP / FP / FN / TN)
- Label the **current mask** after Show Mask / Smart Suggest:
  - **TP** green — correct detection  
  - **FP** orange — false mark  
  - **FN** blue — missed cell  
  - **TN** gray — true empty background  
- **Dual approach supported**:
  - **Precision pass**: FP + TN only (≥2 should-not) — tighten thr/SNR/quality.  
  - **Recall pass**: TP + FN only (≥2 should-detect) — recover missed cells.  
  - **Full pass**: both sides.  
- Detection rings stay visible while labeling; Apply uses a progress dialog.
- Performance: local-patch LoG (no full-frame LoG storm on large TIFFs).
- Labels feed **Smart Suggest** for thr/sigma/SNR/packing restore.

### Smart Suggest upgrades
- **Regional diagnosis** (bright vs dark tiles: peaks vs detections).
- Named recipes: mixed_both, high_bg_fp, low_bg_fn, recover_clusters, global over/under.
- **Joint suggestions** (Adaptive + dual-pass + SNR + thr + packing together).
- Explicit **adaptive_enabled → 1** when indicators support it (priority 0).
- Trajectory memory after Apply (e.g. ease SNR after a strict high-BG pass).
- Area Tune / Measure Tune results preferred over pure LoG-derived sizes when present.

### Mask Settings UX
- Inactive detection methods: parameters **dimmed and locked** (Blob vs Watershed vs Adaptive panel).
- Adaptive checkbox disabled under Watershed.
- Hover tooltips for adaptive and quality parameters.

### Manual add / remove cells
- **Remove** brush paint is **yellow/gold** (not red or cyan).
- **Add** stays red.
- Detection mask **stays visible** under paint (rings + brush composite; works while zooming).

### Other
- Crop / Enter / hemisphere `_r`/`_l` and random-region work from earlier 8.08 remain.
- Python **3.14** env support: `environment.yml`, `Launch_BARCC.bat`, optional `BARCC.lnk`.
- `requirements.txt` updated for the preferred env.

## Files
- `Application/barcc.py` — detection, Smart Suggest, Measure/Area Tune, Mask Settings, mask edit UI.
- `Application/allen_atlas.py` — prior atlas refinements included in this tree.
- `Application/Launch_BARCC.bat` — launcher for barcc314 / preferred env.
- `environment.yml` — conda env definition (new in tree).
- `requirements.txt` — dependencies.
- `README.md` — version highlights.
- `release-notes-v8.09.000.md` — this file.
- Version string: **8.09.000**.

## Notes
- Adaptive runs only when **Adaptive** is checked and method is Blob or DoG.
- Expert quality on mixed high/low BG still often needs dual Measure Tune passes (FP/TN then TP/FN) plus manual add/remove on ROIs.
- Atlas alignment improvements are **not** in this release (deferred by design).

## Requirements / Running
From `Application/` (example):

```text
conda activate barcc314
python barcc.py
```

or use `Launch_BARCC.bat`. See `requirements.txt` / `environment.yml`.

## Git
- Tag: **v8.09.000**
- Previous: **v8.08.000** — see `release-notes-v8.08.000.md`
