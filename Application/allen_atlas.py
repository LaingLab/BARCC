#    Allen Mouse Reference Atlas access for BARCC (Phase 1 + 2)
#    Downloads annotated plates + SVG structure outlines via the public Brain Atlas API
#    (no allensdk dependency required).

"""Allen Mouse Brain Atlas plate loader for BARCC.

Phase 1: list / download annotated reference plates (Nissl + outline overlay)
Phase 2: rasterize SVG structure paths into zone masks with ontology names

API docs:
  https://community.brain-map.org/t/how-do-i-download-reference-atlas-images/94
  http://help.brain-map.org/display/api/Atlas+Drawings+and+Ontologies
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import numpy as np
from PIL import Image, ImageDraw
from skimage.draw import polygon as sk_polygon

logger = logging.getLogger(__name__)

API_BASE = "http://api.brain-map.org/api/v2"
USER_AGENT = "BARCC-AllenAtlas/1.0"

# Annotated reference atlases (plates that have structure SVG drawings)
ALLEN_ATLASES = {
    "coronal": {
        "id": 1,
        "name": "Mouse P56 Coronal",
        "plane": "coronal",
        "description": "Adult mouse coronal reference plates (Allen P56)",
    },
    "sagittal": {
        "id": 2,
        "name": "Mouse P56 Sagittal",
        "plane": "sagittal",
        "description": "Adult mouse sagittal reference plates (Allen P56)",
    },
}

# Approximate bregma (mm) span for display only (P56 coronal series)
CORONAL_BREGMA_ROSTRAL = 2.80
CORONAL_BREGMA_CAUDAL = -5.20


@dataclass
class AllenPlate:
    image_id: int
    section_number: int
    index: int = 0  # 0-based index among annotated plates
    annotated: bool = True
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    atlas_key: str = "coronal"

    @property
    def label(self) -> str:
        b = self.approx_bregma_mm()
        if b is not None:
            return f"Plate {self.index + 1}  ·  sec {self.section_number}  ·  ~{b:+.2f} mm"
        return f"Plate {self.index + 1}  ·  sec {self.section_number}"

    def approx_bregma_mm(self) -> Optional[float]:
        """Rough linear bregma estimate for coronal plates (display only)."""
        if self.atlas_key != "coronal":
            return None
        # index maps across annotated series
        # total unknown here; use section_number heuristic if large
        return None


@dataclass
class AllenPlateData:
    """Fully loaded plate ready for BARCC."""
    plate: AllenPlate
    nissl_rgba: Image.Image         # pure Nissl reference (not used as movable atlas)
    borders_rgba: Image.Image       # structure borders only (transparent bg) — movable atlas
    outline_rgba: Image.Image       # same as borders (alias / colored optional)
    mask_l: Image.Image             # uint8 zone mask (dense local IDs)
    zone_names: Dict[int, str]      # local_zid -> display name
    zone_meta: Dict[int, dict]      # local_zid -> {structure_id, acronym, name, color}
    svg_width: int
    svg_height: int
    downsample: int
    mirrored: bool = False          # True if left hemisphere was mirrored from right

    @property
    def base_rgba(self) -> Image.Image:
        """Atlas overlay layer used by BARCC (borders only)."""
        return self.borders_rgba


def _cache_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".barc", "allen_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Allen API HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Allen API network error: {e.reason}") from e


def _http_get_json(url: str, timeout: int = 120) -> dict:
    raw = _http_get(url, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


def _rma_query(criteria: str, timeout: int = 120) -> dict:
    url = f"{API_BASE}/data/query.json?criteria={quote(criteria, safe='')}"
    return _http_get_json(url, timeout=timeout)


# ---------------------------------------------------------------------------
# Structure ontology
# ---------------------------------------------------------------------------

_STRUCTURE_CACHE: Optional[Dict[int, dict]] = None


def load_structure_ontology(force_refresh: bool = False) -> Dict[int, dict]:
    """Return structure_id -> {acronym, name, color_hex} for mouse structure graph (id=1)."""
    global _STRUCTURE_CACHE
    if _STRUCTURE_CACHE is not None and not force_refresh:
        return _STRUCTURE_CACHE

    cache_path = os.path.join(_cache_dir(), "structures_graph1.json")
    if not force_refresh and os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _STRUCTURE_CACHE = {int(k): v for k, v in data.items()}
            return _STRUCTURE_CACHE
        except Exception:
            pass

    crit = (
        "model::Structure,rma::criteria,[graph_id$eq1],"
        "rma::options[num_rows$eqall]"
        "[only$eq'id,acronym,name,color_hex_triplet,parent_structure_id']"
    )
    d = _rma_query(crit, timeout=180)
    if not d.get("success"):
        raise RuntimeError(f"Failed to load Allen structure ontology: {d.get('msg')}")

    out: Dict[int, dict] = {}
    for s in d.get("msg") or []:
        sid = int(s["id"])
        out[sid] = {
            "id": sid,
            "acronym": s.get("acronym") or f"id{sid}",
            "name": s.get("name") or f"Structure {sid}",
            "color_hex": (s.get("color_hex_triplet") or "CCCCCC").strip().upper(),
            "parent_structure_id": s.get("parent_structure_id"),
        }

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except Exception as e:
        logger.debug(f"Could not cache structures: {e}")

    _STRUCTURE_CACHE = out
    logger.info(f"Loaded {len(out)} Allen structures")
    return out


# ---------------------------------------------------------------------------
# Plate listing
# ---------------------------------------------------------------------------

_PLATE_LIST_CACHE: Dict[str, List[AllenPlate]] = {}


def list_annotated_plates(atlas_key: str = "coronal", force_refresh: bool = False) -> List[AllenPlate]:
    """List annotated reference plates for coronal or sagittal adult mouse atlas."""
    if atlas_key not in ALLEN_ATLASES:
        raise ValueError(f"Unknown atlas_key {atlas_key!r}; expected one of {list(ALLEN_ATLASES)}")

    if not force_refresh and atlas_key in _PLATE_LIST_CACHE:
        return list(_PLATE_LIST_CACHE[atlas_key])

    atlas_id = ALLEN_ATLASES[atlas_key]["id"]
    cache_path = os.path.join(_cache_dir(), f"plates_atlas{atlas_id}_annotated.json")
    if not force_refresh and os.path.isfile(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            plates = [
                AllenPlate(
                    image_id=int(r["id"]),
                    section_number=int(r.get("section_number") or 0),
                    index=i,
                    annotated=True,
                    image_width=r.get("image_width"),
                    image_height=r.get("image_height"),
                    atlas_key=atlas_key,
                )
                for i, r in enumerate(rows)
            ]
            _assign_bregma_labels(plates, atlas_key)
            _PLATE_LIST_CACHE[atlas_key] = plates
            return list(plates)
        except Exception:
            pass

    crit = (
        f"model::AtlasImage,rma::criteria,[annotated$eqtrue],"
        f"atlas_data_set(atlases[id$eq{atlas_id}]),"
        f"rma::options[num_rows$eqall]"
        f"[order$eq'sub_images.section_number$asc']"
        f"[only$eq'id,section_number,image_width,image_height,annotated']"
    )
    d = _rma_query(crit, timeout=180)
    if not d.get("success"):
        raise RuntimeError(f"Failed to list Allen plates: {d.get('msg')}")

    rows = d.get("msg") or []
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
    except Exception:
        pass

    plates = [
        AllenPlate(
            image_id=int(r["id"]),
            section_number=int(r.get("section_number") or 0),
            index=i,
            annotated=True,
            image_width=r.get("image_width"),
            image_height=r.get("image_height"),
            atlas_key=atlas_key,
        )
        for i, r in enumerate(rows)
    ]
    _assign_bregma_labels(plates, atlas_key)
    _PLATE_LIST_CACHE[atlas_key] = plates
    logger.info(f"Listed {len(plates)} annotated plates for {atlas_key}")
    return list(plates)


def _assign_bregma_labels(plates: List[AllenPlate], atlas_key: str) -> None:
    if atlas_key != "coronal" or not plates:
        return
    n = max(1, len(plates) - 1)
    for i, p in enumerate(plates):
        # linear estimate across series for UI only
        t = i / n
        bregma = CORONAL_BREGMA_ROSTRAL + t * (CORONAL_BREGMA_CAUDAL - CORONAL_BREGMA_ROSTRAL)
        # stash on object for label()
        p._bregma = bregma  # type: ignore[attr-defined]


def _plate_label(plate: AllenPlate) -> str:
    b = getattr(plate, "_bregma", None)
    if b is not None:
        return f"#{plate.index + 1}  sec {plate.section_number}  ~{b:+.2f} mm bregma"
    return f"#{plate.index + 1}  sec {plate.section_number}"


# Monkey-patch label property use via helper
def plate_display_label(plate: AllenPlate) -> str:
    return _plate_label(plate)


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

def download_atlas_image(image_id: int, downsample: int = 3, annotation: bool = False) -> Image.Image:
    """Download a downsampled atlas JPEG (Nissl or annotation layer)."""
    downsample = int(np.clip(downsample, 0, 8))
    ann = "true" if annotation else "false"
    cache_path = os.path.join(
        _cache_dir(), f"img_{image_id}_ds{downsample}_ann{int(annotation)}.jpg"
    )
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 1000:
        return Image.open(cache_path).convert("RGB")

    url = (
        f"{API_BASE}/atlas_image_download/{image_id}"
        f"?downsample={downsample}&annotation={ann}"
    )
    data = _http_get(url)
    try:
        with open(cache_path, "wb") as f:
            f.write(data)
    except Exception:
        pass
    return Image.open(BytesIO(data)).convert("RGB")


def download_svg(image_id: int) -> str:
    """Download structure SVG for an atlas image; return text."""
    cache_path = os.path.join(_cache_dir(), f"svg_{image_id}.svg")
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 200:
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()

    url = f"{API_BASE}/svg_download/{image_id}"
    data = _http_get(url)
    text = data.decode("utf-8", errors="replace")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    return text


def cache_dir() -> str:
    """Public path to the Allen local cache folder (~/.barc/allen_cache)."""
    return _cache_dir()


def plate_cache_status(
    atlas_key: str = "coronal",
    downsample: int = 3,
) -> dict:
    """How many plates already have Nissl + SVG cached for this atlas/quality."""
    plates = list_annotated_plates(atlas_key)
    n = len(plates)
    nissl_ok = 0
    svg_ok = 0
    both_ok = 0
    for p in plates:
        img_path = os.path.join(
            _cache_dir(), f"img_{p.image_id}_ds{int(downsample)}_ann0.jpg"
        )
        svg_path = os.path.join(_cache_dir(), f"svg_{p.image_id}.svg")
        has_img = os.path.isfile(img_path) and os.path.getsize(img_path) > 1000
        has_svg = os.path.isfile(svg_path) and os.path.getsize(svg_path) > 200
        if has_img:
            nissl_ok += 1
        if has_svg:
            svg_ok += 1
        if has_img and has_svg:
            both_ok += 1
    return {
        "atlas_key": atlas_key,
        "downsample": int(downsample),
        "total": n,
        "nissl_cached": nissl_ok,
        "svg_cached": svg_ok,
        "complete": both_ok,
        "cache_dir": _cache_dir(),
    }


def download_full_atlas(
    atlas_key: str = "coronal",
    downsample: int = 3,
    include_nissl: bool = True,
    include_svg: bool = True,
    progress_callback=None,
    force: bool = False,
) -> dict:
    """Pre-download all annotated plates for offline / fast loading.

    Files are stored under ``~/.barc/allen_cache/`` and reused by
    ``load_plate`` / ``download_atlas_image`` / ``download_svg``.

    progress_callback(done, total, plate, message) is optional.
    Returns a summary dict.
    """
    if atlas_key not in ALLEN_ATLASES:
        raise ValueError(f"Unknown atlas_key {atlas_key!r}")
    downsample = int(np.clip(downsample, 2, 6))
    plates = list_annotated_plates(atlas_key, force_refresh=force)
    total = len(plates)
    downloaded_img = 0
    downloaded_svg = 0
    skipped = 0
    errors = []

    # Ontology once (used when loading plates later)
    try:
        load_structure_ontology(force_refresh=force)
    except Exception as e:
        logger.warning(f"Ontology pre-cache failed: {e}")

    for i, p in enumerate(plates):
        msg_parts = []
        try:
            if include_nissl:
                img_path = os.path.join(
                    _cache_dir(), f"img_{p.image_id}_ds{downsample}_ann0.jpg"
                )
                already = (
                    not force
                    and os.path.isfile(img_path)
                    and os.path.getsize(img_path) > 1000
                )
                if already:
                    skipped += 1
                    msg_parts.append("nissl cached")
                else:
                    download_atlas_image(p.image_id, downsample=downsample, annotation=False)
                    downloaded_img += 1
                    msg_parts.append("nissl ok")
            if include_svg:
                svg_path = os.path.join(_cache_dir(), f"svg_{p.image_id}.svg")
                already_svg = (
                    not force
                    and os.path.isfile(svg_path)
                    and os.path.getsize(svg_path) > 200
                )
                if already_svg:
                    msg_parts.append("svg cached")
                else:
                    download_svg(p.image_id)
                    downloaded_svg += 1
                    msg_parts.append("svg ok")
        except Exception as e:
            errors.append({"image_id": p.image_id, "error": str(e)})
            msg_parts.append(f"error: {e}")
            logger.warning(f"Download failed for plate {p.image_id}: {e}")

        if progress_callback is not None:
            try:
                progress_callback(
                    i + 1,
                    total,
                    p,
                    f"Plate {i + 1}/{total} sec {p.section_number}: " + ", ".join(msg_parts),
                )
            except Exception:
                pass

    summary = {
        "atlas_key": atlas_key,
        "downsample": downsample,
        "total": total,
        "downloaded_nissl": downloaded_img,
        "downloaded_svg": downloaded_svg,
        "skipped_existing": skipped,
        "errors": errors,
        "cache_dir": _cache_dir(),
    }
    logger.info(
        f"download_full_atlas {atlas_key}: {downloaded_img} nissl, "
        f"{downloaded_svg} svg, {len(errors)} errors → {_cache_dir()}"
    )
    return summary


# ---------------------------------------------------------------------------
# SVG path parsing → polygons
# ---------------------------------------------------------------------------

_CMD_RE = re.compile(
    r"([MmLlHhVvCcSsQqTtAaZz])"
    r"|([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)


def _tokenize_path_d(d: str) -> List:
    tokens = []
    for m in _CMD_RE.finditer(d.replace(",", " ")):
        if m.group(1):
            tokens.append(m.group(1))
        else:
            tokens.append(float(m.group(2)))
    return tokens


def _cubic_bezier(p0, p1, p2, p3, n: int = 10) -> List[Tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / float(n)
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        pts.append((x, y))
    return pts


def _quadratic_bezier(p0, p1, p2, n: int = 8) -> List[Tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / float(n)
        u = 1.0 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def _tokenize_path_d(d: str) -> list:
    """Tokenize SVG path d into commands (str) and numbers (float)."""
    tokens = []
    for m in _CMD_RE.finditer(d.replace(",", " ")):
        if m.group(1):
            tokens.append(m.group(1))
        else:
            try:
                tokens.append(float(m.group(2)))
            except Exception:
                pass
    return tokens


def path_d_to_polylines(d: str) -> List[List[Tuple[float, float]]]:
    """Convert an SVG path `d` string into polylines (list of point lists)."""
    tokens = _tokenize_path_d(d)
    if not tokens:
        return []

    polylines: List[List[Tuple[float, float]]] = []
    current: List[Tuple[float, float]] = []
    cx = cy = 0.0
    start_x = start_y = 0.0
    last_ctrl = None  # for smooth curves
    i = 0
    cmd = "M"

    def take(n):
        nonlocal i
        vals = tokens[i : i + n]
        i += n
        return vals

    while i < len(tokens):
        t = tokens[i]
        if isinstance(t, str):
            cmd = t
            i += 1
            if cmd in ("Z", "z"):
                if current:
                    current.append((start_x, start_y))
                    polylines.append(current)
                    current = []
                cx, cy = start_x, start_y
                last_ctrl = None
                continue
        # implicit command repeat: if number and previous cmd, keep cmd

        try:
            if cmd == "M":
                x, y = take(2)
                cx, cy = float(x), float(y)
                start_x, start_y = cx, cy
                if current:
                    polylines.append(current)
                current = [(cx, cy)]
                cmd = "L"  # subsequent pairs are line-to
                last_ctrl = None
            elif cmd == "m":
                x, y = take(2)
                cx, cy = cx + float(x), cy + float(y)
                start_x, start_y = cx, cy
                if current:
                    polylines.append(current)
                current = [(cx, cy)]
                cmd = "l"
                last_ctrl = None
            elif cmd == "L":
                x, y = take(2)
                cx, cy = float(x), float(y)
                current.append((cx, cy))
                last_ctrl = None
            elif cmd == "l":
                x, y = take(2)
                cx, cy = cx + float(x), cy + float(y)
                current.append((cx, cy))
                last_ctrl = None
            elif cmd == "H":
                x = take(1)[0]
                cx = float(x)
                current.append((cx, cy))
                last_ctrl = None
            elif cmd == "h":
                x = take(1)[0]
                cx = cx + float(x)
                current.append((cx, cy))
                last_ctrl = None
            elif cmd == "V":
                y = take(1)[0]
                cy = float(y)
                current.append((cx, cy))
                last_ctrl = None
            elif cmd == "v":
                y = take(1)[0]
                cy = cy + float(y)
                current.append((cx, cy))
                last_ctrl = None
            elif cmd == "C":
                x1, y1, x2, y2, x, y = take(6)
                p0 = (cx, cy)
                p1 = (float(x1), float(y1))
                p2 = (float(x2), float(y2))
                p3 = (float(x), float(y))
                current.extend(_cubic_bezier(p0, p1, p2, p3)[1:])
                last_ctrl = p2
                cx, cy = p3
            elif cmd == "c":
                x1, y1, x2, y2, x, y = take(6)
                p0 = (cx, cy)
                p1 = (cx + float(x1), cy + float(y1))
                p2 = (cx + float(x2), cy + float(y2))
                p3 = (cx + float(x), cy + float(y))
                current.extend(_cubic_bezier(p0, p1, p2, p3)[1:])
                last_ctrl = p2
                cx, cy = p3
            elif cmd == "S":
                x2, y2, x, y = take(4)
                if last_ctrl is not None:
                    p1 = (2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1])
                else:
                    p1 = (cx, cy)
                p0 = (cx, cy)
                p2 = (float(x2), float(y2))
                p3 = (float(x), float(y))
                current.extend(_cubic_bezier(p0, p1, p2, p3)[1:])
                last_ctrl = p2
                cx, cy = p3
            elif cmd == "s":
                x2, y2, x, y = take(4)
                if last_ctrl is not None:
                    p1 = (2 * cx - last_ctrl[0], 2 * cy - last_ctrl[1])
                else:
                    p1 = (cx, cy)
                p0 = (cx, cy)
                p2 = (cx + float(x2), cy + float(y2))
                p3 = (cx + float(x), cy + float(y))
                current.extend(_cubic_bezier(p0, p1, p2, p3)[1:])
                last_ctrl = p2
                cx, cy = p3
            elif cmd == "Q":
                x1, y1, x, y = take(4)
                p0 = (cx, cy)
                p1 = (float(x1), float(y1))
                p2 = (float(x), float(y))
                current.extend(_quadratic_bezier(p0, p1, p2)[1:])
                last_ctrl = p1
                cx, cy = p2
            elif cmd == "q":
                x1, y1, x, y = take(4)
                p0 = (cx, cy)
                p1 = (cx + float(x1), cy + float(y1))
                p2 = (cx + float(x), cy + float(y))
                current.extend(_quadratic_bezier(p0, p1, p2)[1:])
                last_ctrl = p1
                cx, cy = p2
            elif cmd in ("A", "a"):
                # Arc: skip by consuming 7 params and jumping to end point
                vals = take(7)
                if cmd == "A":
                    cx, cy = float(vals[5]), float(vals[6])
                else:
                    cx, cy = cx + float(vals[5]), cy + float(vals[6])
                current.append((cx, cy))
                last_ctrl = None
            else:
                # Unknown command — abort this path segment safely
                break
        except (IndexError, TypeError, ValueError):
            break

    if current and len(current) >= 2:
        polylines.append(current)
    return polylines


def parse_svg_structures(svg_text: str) -> Tuple[int, int, List[Tuple[int, List[List[Tuple[float, float]]]]]]:
    """Parse SVG → (width, height, [(structure_id, polylines), ...])."""
    wh = re.search(r'width="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"', svg_text)
    if not wh:
        raise RuntimeError("SVG missing width/height")
    svg_w, svg_h = int(float(wh.group(1))), int(float(wh.group(2)))

    results = []
    for m in re.finditer(r"<path\b([^>]*)/?>", svg_text):
        attrs = m.group(1)
        sid_m = re.search(r'structure_id="(\d+)"', attrs)
        d_m = re.search(r'\bd="([^"]+)"', attrs)
        if not sid_m or not d_m:
            continue
        sid = int(sid_m.group(1))
        polylines = path_d_to_polylines(d_m.group(1))
        if polylines:
            results.append((sid, polylines))
    return svg_w, svg_h, results


def rasterize_structures(
    svg_text: str,
    out_w: int,
    out_h: int,
    ontology: Optional[Dict[int, dict]] = None,
) -> Tuple[np.ndarray, Dict[int, str], Dict[int, dict], Image.Image]:
    """Rasterize SVG structures into a dense uint8 mask + outline RGBA.

    Returns:
        mask: (H,W) uint8 local zone IDs (0 = background)
        zone_names: local_zid -> display name
        zone_meta: local_zid -> metadata dict
        outline_rgba: RGBA image with structure borders drawn
    """
    if ontology is None:
        ontology = load_structure_ontology()

    svg_w, svg_h, structures = parse_svg_structures(svg_text)
    if not structures:
        mask = np.zeros((out_h, out_w), dtype=np.uint8)
        outline = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
        return mask, {}, {}, outline

    sx = out_w / float(svg_w)
    sy = out_h / float(svg_h)

    # Dense local IDs for structures present on this plate
    unique_sids = []
    seen = set()
    for sid, _ in structures:
        if sid not in seen:
            seen.add(sid)
            unique_sids.append(sid)

    # Cap at 255 local IDs (uint8); drop extras if absurd
    if len(unique_sids) > 255:
        logger.warning(f"Plate has {len(unique_sids)} structures; truncating to 255")
        unique_sids = unique_sids[:255]

    sid_to_local = {sid: i + 1 for i, sid in enumerate(unique_sids)}
    zone_names: Dict[int, str] = {}
    zone_meta: Dict[int, dict] = {}
    for sid, local in sid_to_local.items():
        meta = ontology.get(sid, {})
        acr = meta.get("acronym") or f"id{sid}"
        name = meta.get("name") or f"Structure {sid}"
        zone_names[local] = f"{acr}"
        zone_meta[local] = {
            "structure_id": sid,
            "acronym": acr,
            "name": name,
            "color_hex": meta.get("color_hex", "CCCCCC"),
            "display": f"{acr}: {name}",
        }
        # Prefer richer label for zone_names used in counting
        zone_names[local] = f"{acr}: {name}" if name and name != acr else acr

    mask = np.zeros((out_h, out_w), dtype=np.uint8)
    outline = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(outline)

    for sid, polylines in structures:
        local = sid_to_local.get(sid)
        if not local:
            continue
        # Movable atlas layer uses solid black borders (PDF-like); colors stay in ontology meta
        outline_color = (0, 0, 0, 255)

        for poly in polylines:
            if len(poly) < 3:
                continue
            pts = [(p[0] * sx, p[1] * sy) for p in poly]
            xs = np.array([p[0] for p in pts], dtype=np.float64)
            ys = np.array([p[1] for p in pts], dtype=np.float64)
            # skimage polygon expects row, col = y, x
            rr, cc = sk_polygon(ys, xs, shape=mask.shape)
            if len(rr):
                # later paths overwrite earlier (typical for nested drawings)
                mask[rr, cc] = local
            # draw outline stroke (black borders for alignment overlay)
            int_pts = [(int(round(x)), int(round(y))) for x, y in pts]
            if len(int_pts) >= 2:
                draw.line(int_pts, fill=outline_color, width=2, joint="curve")

    return mask, zone_names, zone_meta, outline


# ---------------------------------------------------------------------------
# High-level load
# ---------------------------------------------------------------------------

def load_plate(
    plate: AllenPlate,
    downsample: int = 3,
    include_outlines_on_base: bool = True,
    max_atlas_side: int = 1400,
    mirror_hemispheres: Optional[bool] = None,
) -> AllenPlateData:
    """Download plate image + SVG and build BARCC-ready layers (Phase 1+2).

    - nissl_rgba: pure Nissl reference photo (same pixel grid used for SVG raster)
    - borders_rgba / base_rgba: structure borders on transparent background.
      SVG is rasterized into the *Nissl pixel grid* (Allen coords match the atlas
      image). Mirror is a reflection across the Nissl midline so connectivity
      matches the stain; movable atlas is then content-cropped.
    - mask_l: filled structure zones for counting / naming (same size as borders)
    - mirror_hemispheres: if True, mirror the right-hemisphere Allen drawing across
      the Nissl midline into a full bilateral plate. Default True for coronal,
      False for sagittal. Skipped when the SVG already looks bilateral.
    """
    downsample = int(np.clip(downsample, 2, 6))
    if mirror_hemispheres is None:
        mirror_hemispheres = (getattr(plate, "atlas_key", "coronal") == "coronal")
    logger.info(
        f"Loading Allen plate id={plate.image_id} sec={plate.section_number} "
        f"ds={downsample} mirror={mirror_hemispheres}"
    )

    nissl = download_atlas_image(plate.image_id, downsample=downsample, annotation=False)
    svg_text = download_svg(plate.image_id)
    ontology = load_structure_ontology()

    wh = re.search(r'width="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"', svg_text)
    if not wh:
        raise RuntimeError("Allen SVG missing width/height")
    svg_w, svg_h = int(float(wh.group(1))), int(float(wh.group(2)))

    # Rasterize SVG into the *Nissl pixel grid*. Allen SVG coordinates match the
    # full-resolution atlas image; Nissl at the chosen downsample is that image
    # scaled by 2^downsample. Drawing in Nissl space keeps structure borders
    # registered to the Nissl stain (critical for mirror stitch appearance).
    nw, nh = nissl.size
    mside = max(nw, nh)
    if mside > max_atlas_side:
        s = max_atlas_side / float(mside)
        out_w = max(64, int(round(nw * s)))
        out_h = max(64, int(round(nh * s)))
        nissl_rgba = nissl.resize((out_w, out_h), Image.BILINEAR).convert("RGBA")
    else:
        out_w, out_h = nw, nh
        nissl_rgba = nissl.convert("RGBA")

    mask_arr, zone_names, zone_meta, outline_rgba = rasterize_structures(
        svg_text, out_w, out_h, ontology=ontology
    )

    mirrored = False
    right_frac = _content_right_fraction(mask_arr, outline_rgba)
    # Allen annotated SVGs are right-hemisphere dominant (~0.88–1.0). Only mirror when
    # the SVG is clearly unilateral so we never double an already-full plate.
    unilateral = right_frac >= 0.65
    if mirror_hemispheres and unilateral:
        mask_arr, outline_rgba, mid_x = _mirror_across_nissl_midline(
            mask_arr, outline_rgba, nissl_rgba
        )
        mask_arr, zone_names, zone_meta = _assign_bilateral_zone_ids(
            mask_arr, zone_names, zone_meta, mid_x
        )
        mirrored = True
        logger.info(
            f"Nissl-space mirror: right_frac={right_frac:.2f} mid_x={mid_x} "
            f"grid={out_w}x{out_h} → crop next"
        )
    elif mirror_hemispheres and not unilateral:
        logger.info(
            f"Mirror requested but SVG already bilateral/left-heavy "
            f"(right_frac={right_frac:.2f}); Nissl-space crop only"
        )

    # Crop movable atlas to drawing (Nissl reference stays full section photo)
    mask_arr, outline_rgba = _crop_to_content(mask_arr, outline_rgba, pad=12)

    borders_rgba = outline_rgba.copy() if outline_rgba is not None else Image.new(
        "RGBA", (mask_arr.shape[1], mask_arr.shape[0]), (0, 0, 0, 0)
    )
    mask_l = Image.fromarray(mask_arr, mode="L")

    logger.info(
        f"Allen plate raster: svg={svg_w}x{svg_h} → nissl_grid={out_w}x{out_h} "
        f"atlas={mask_l.size[0]}x{mask_l.size[1]} nissl={nissl_rgba.size} "
        f"zones={len(zone_names)} mirrored={mirrored} "
        f"mask_cov={(mask_arr > 0).mean():.1%}"
    )

    return AllenPlateData(
        plate=plate,
        nissl_rgba=nissl_rgba,
        borders_rgba=borders_rgba,
        outline_rgba=outline_rgba,
        mask_l=mask_l,
        zone_names=zone_names,
        zone_meta=zone_meta,
        svg_width=svg_w,
        svg_height=svg_h,
        downsample=downsample,
        mirrored=mirrored,
    )


# ---------------------------------------------------------------------------
# Semi-automated stitch editor support
# ---------------------------------------------------------------------------

@dataclass
class AllenStitchSession:
    """Editable bilateral plate: Nissl bg + independent left/right border layers."""
    plate: AllenPlate
    nissl_rgba: Image.Image
    mask_right: np.ndarray          # (H,W) uint8 original (right-dominant) drawing
    border_right: np.ndarray        # (H,W,4) RGBA
    mask_left: Optional[np.ndarray] = None
    border_left: Optional[np.ndarray] = None
    zone_names: Dict[int, str] = field(default_factory=dict)
    zone_meta: Dict[int, dict] = field(default_factory=dict)
    mid_x: int = 0
    # Per-hemi transforms (applied about image center unless noted)
    right_dx: float = 0.0
    right_dy: float = 0.0
    right_angle: float = 0.0  # degrees, CCW
    left_dx: float = 0.0
    left_dy: float = 0.0
    left_angle: float = 0.0
    svg_width: int = 0
    svg_height: int = 0
    downsample: int = 3

    @property
    def size(self) -> Tuple[int, int]:
        return self.nissl_rgba.size  # (W,H)


def load_plate_for_stitch_editor(
    plate: AllenPlate,
    downsample: int = 3,
    max_atlas_side: int = 1400,
) -> AllenStitchSession:
    """Load Nissl + structure drawing on the Nissl grid (no auto-mirror, no crop).

    Used by the semi-automated stitch editor so the user can Reflect and
    manually move/rotate each half before committing into BARCC.
    """
    downsample = int(np.clip(downsample, 2, 6))
    nissl = download_atlas_image(plate.image_id, downsample=downsample, annotation=False)
    svg_text = download_svg(plate.image_id)
    ontology = load_structure_ontology()

    wh = re.search(r'width="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"', svg_text)
    if not wh:
        raise RuntimeError("Allen SVG missing width/height")
    svg_w, svg_h = int(float(wh.group(1))), int(float(wh.group(2)))

    nw, nh = nissl.size
    mside = max(nw, nh)
    if mside > max_atlas_side:
        s = max_atlas_side / float(mside)
        out_w = max(64, int(round(nw * s)))
        out_h = max(64, int(round(nh * s)))
        nissl_rgba = nissl.resize((out_w, out_h), Image.BILINEAR).convert("RGBA")
    else:
        out_w, out_h = nw, nh
        nissl_rgba = nissl.convert("RGBA")

    mask_arr, zone_names, zone_meta, outline_rgba = rasterize_structures(
        svg_text, out_w, out_h, ontology=ontology
    )
    border = np.asarray(outline_rgba)
    mid = _nissl_midline_x(nissl_rgba, width=out_w)

    # Clear weak left-side noise so "right" is clean for Reflect
    content = _content_mask(mask_arr, outline_rgba)
    right_frac = _content_right_fraction(mask_arr, outline_rgba)
    mask_right = mask_arr.copy()
    border_right = border.copy()
    if right_frac >= 0.65:
        # Zero left of mid (keep only Allen's right drawing)
        mask_right[:, :mid] = 0
        border_right[:, :mid] = 0

    logger.info(
        f"Stitch editor session: id={plate.image_id} grid={out_w}x{out_h} "
        f"mid={mid} right_frac={right_frac:.2f} zones={len(zone_names)}"
    )
    return AllenStitchSession(
        plate=plate,
        nissl_rgba=nissl_rgba,
        mask_right=mask_right,
        border_right=border_right,
        zone_names=dict(zone_names),
        zone_meta=dict(zone_meta),
        mid_x=mid,
        svg_width=svg_w,
        svg_height=svg_h,
        downsample=downsample,
    )


def reflect_right_to_left(session: AllenStitchSession) -> None:
    """Create left hemi as a horizontal flip of the right drawing about mid_x."""
    h, w = session.mask_right.shape[:2]
    mid = int(np.clip(session.mid_x, 1, w - 2))
    ml = np.zeros_like(session.mask_right)
    bl = np.zeros_like(session.border_right)
    left_cols = np.arange(mid, dtype=np.int32)
    src_cols = 2 * mid - left_cols
    valid = (src_cols >= 0) & (src_cols < w)
    if valid.any():
        lc = left_cols[valid]
        sc = src_cols[valid]
        ml[:, lc] = session.mask_right[:, sc]
        bl[:, lc] = session.border_right[:, sc]
    session.mask_left = ml
    session.border_left = bl
    # Reset left transform when re-reflecting
    session.left_dx = 0.0
    session.left_dy = 0.0
    session.left_angle = 0.0
    logger.info(f"Reflected right→left about mid={mid}")


def _transform_mask_border(
    mask: np.ndarray,
    border: np.ndarray,
    dx: float,
    dy: float,
    angle_deg: float,
    center: Optional[Tuple[float, float]] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Rotate about center then translate. Mask=NEAREST, border=BILINEAR."""
    h, w = mask.shape[:2]
    if center is None:
        center = (w * 0.5, h * 0.5)
    cx, cy = center

    m_img = Image.fromarray(mask, mode="L")
    b_img = Image.fromarray(border, mode="RGBA")

    if abs(angle_deg) > 1e-6:
        m_img = m_img.rotate(
            angle_deg, resample=Image.NEAREST, center=center, fillcolor=0, expand=False
        )
        b_img = b_img.rotate(
            angle_deg, resample=Image.BILINEAR, center=center, fillcolor=(0, 0, 0, 0), expand=False
        )

    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
        # AFFINE: maps output (x,y) → input; translation of content by (dx,dy)
        # means output x comes from input x-dx
        m_img = m_img.transform(
            (w, h),
            Image.AFFINE,
            (1, 0, -dx, 0, 1, -dy),
            resample=Image.NEAREST,
            fillcolor=0,
        )
        b_img = b_img.transform(
            (w, h),
            Image.AFFINE,
            (1, 0, -dx, 0, 1, -dy),
            resample=Image.BILINEAR,
            fillcolor=(0, 0, 0, 0),
        )

    b = np.array(b_img)
    # Re-crisp border alpha after bilinear
    if b.ndim == 3 and b.shape[2] >= 4:
        ink = b[..., 3] >= 40
        b[~ink] = 0
        b[ink, 3] = 255
        b[ink, :3] = 0
    return np.array(m_img, dtype=np.uint8), b


def compose_stitch_preview(session: AllenStitchSession) -> Image.Image:
    """Nissl + transformed left/right borders for editor display."""
    nissl = session.nissl_rgba.convert("RGBA")
    w, h = nissl.size
    composed = nissl.copy()

    def _overlay(mask, border, dx, dy, ang, color_tint=None):
        if mask is None or border is None:
            return
        tm, tb = _transform_mask_border(mask, border, dx, dy, ang)
        layer = Image.fromarray(tb, "RGBA")
        if color_tint is not None:
            arr = np.array(layer)
            ink = arr[..., 3] > 0
            arr[ink, 0] = color_tint[0]
            arr[ink, 1] = color_tint[1]
            arr[ink, 2] = color_tint[2]
            layer = Image.fromarray(arr, "RGBA")
        return layer

    # Right = black borders; left = dark blue so user can see halves
    right_layer = _overlay(
        session.mask_right, session.border_right,
        session.right_dx, session.right_dy, session.right_angle,
        color_tint=(0, 0, 0),
    )
    left_layer = _overlay(
        session.mask_left, session.border_left,
        session.left_dx, session.left_dy, session.left_angle,
        color_tint=(20, 60, 180),
    )
    if right_layer is not None:
        composed = Image.alpha_composite(composed, right_layer)
    if left_layer is not None:
        composed = Image.alpha_composite(composed, left_layer)

    # Midline guide
    draw = ImageDraw.Draw(composed)
    mx = int(session.mid_x)
    draw.line([(mx, 0), (mx, h - 1)], fill=(255, 80, 80, 180), width=1)
    return composed


def commit_stitch_session(session: AllenStitchSession) -> AllenPlateData:
    """Bake transforms into final mask/borders and return AllenPlateData for BARCC."""
    h, w = session.mask_right.shape[:2]

    rm, rb = _transform_mask_border(
        session.mask_right, session.border_right,
        session.right_dx, session.right_dy, session.right_angle,
    )
    has_left = session.mask_left is not None and session.border_left is not None
    if has_left:
        lm, lb = _transform_mask_border(
            session.mask_left, session.border_left,
            session.left_dx, session.left_dy, session.left_angle,
        )
    else:
        lm = np.zeros_like(rm)
        lb = np.zeros_like(rb)

    zone_names = dict(session.zone_names)
    zone_meta = dict(session.zone_meta)
    final_m = rm.copy()

    if has_left and (lm > 0).any():
        # Prefer layer-aware remap: right layer → _r IDs, left layer → _l IDs
        # (independent of x, since user may have moved halves).
        used = sorted({int(z) for z in np.unique(rm) if int(z) > 0} |
                      {int(z) for z in np.unique(lm) if int(z) > 0})
        n = len(used)
        if n > 0 and 2 * n <= 255:
            old_to_right = {old: i + 1 for i, old in enumerate(used)}
            old_to_left = {old: i + 1 + n for i, old in enumerate(used)}
            lut_r = np.zeros(256, dtype=np.uint8)
            lut_l = np.zeros(256, dtype=np.uint8)
            for old in used:
                if 0 <= old <= 255:
                    lut_r[old] = np.uint8(old_to_right[old])
                    lut_l[old] = np.uint8(old_to_left[old])
            final_m = lut_r[rm]
            lm_r = lut_l[lm]
            left_pix = lm > 0
            final_m[left_pix] = lm_r[left_pix]
            zone_names, zone_meta = _bilateral_name_maps(
                used, zone_names, zone_meta, old_to_right, old_to_left
            )
            logger.info(
                f"Stitch commit: bilateral zones {n} structures → {2 * n} IDs "
                f"with _r/_l names"
            )
        else:
            # Union shared IDs, then geometric hemisphere split (partial if needed)
            left_pix = lm > 0
            final_m[left_pix] = lm[left_pix]
            logger.warning(
                f"Stitch commit: layer remap {n}×2 > 255; geometric bilateral split"
            )
            final_m, zone_names, zone_meta, _ = ensure_bilateral_hemisphere_zones(
                final_m,
                zone_names,
                zone_meta,
                mid_x=int(getattr(session, "mid_x", 0) or final_m.shape[1] // 2),
            )
    elif (final_m > 0).any():
        # Unilateral or already-composited: still split any IDs that span midline
        final_m, zone_names, zone_meta, _ = ensure_bilateral_hemisphere_zones(
            final_m, zone_names, zone_meta, mid_x=None
        )

    # Borders: alpha composite left then right
    bl_img = Image.fromarray(lb, "RGBA")
    br_img = Image.fromarray(rb, "RGBA")
    empty = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    merged = Image.alpha_composite(empty, bl_img)
    merged = Image.alpha_composite(merged, br_img)
    final_b = np.array(merged)

    outline = Image.fromarray(final_b, "RGBA")
    mask_c, outline_c = _crop_to_content(final_m, outline, pad=12)
    borders = outline_c.copy()
    mask_l = Image.fromarray(mask_c, mode="L")

    return AllenPlateData(
        plate=session.plate,
        nissl_rgba=session.nissl_rgba.convert("RGBA"),
        borders_rgba=borders,
        outline_rgba=outline_c,
        mask_l=mask_l,
        zone_names=zone_names,
        zone_meta=zone_meta,
        svg_width=session.svg_width,
        svg_height=session.svg_height,
        downsample=session.downsample,
        mirrored=has_left,
    )


def _content_mask(mask_arr: np.ndarray, outline_rgba: Image.Image) -> np.ndarray:
    """Boolean content from filled zones or border pixels."""
    border = np.asarray(outline_rgba)
    if border.ndim == 3 and border.shape[2] >= 4:
        return (mask_arr > 0) | (border[..., 3] > 0)
    return mask_arr > 0


def _content_right_fraction(mask_arr: np.ndarray, outline_rgba: Image.Image) -> float:
    """Fraction of content pixels whose x is to the right of image center (0–1)."""
    content = _content_mask(mask_arr, outline_rgba)
    if not content.any():
        return 0.5
    h, w = content.shape
    mid = w * 0.5
    xs = np.where(content)[1]
    return float(np.mean(xs >= mid))


def _content_bbox(
    mask_arr: np.ndarray, outline_rgba: Image.Image, pad: int = 8
) -> Optional[Tuple[int, int, int, int]]:
    """Return (y0, y1, x0, x1) content bbox with padding, or None if empty."""
    content = _content_mask(mask_arr, outline_rgba)
    if not content.any():
        return None
    ys, xs = np.where(content)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    h, w = mask_arr.shape[:2]
    y0 = max(0, y0 - pad)
    y1 = min(h, y1 + pad)
    # Keep medial (left) edge tight — that edge is the approximate midline for
    # right-hemisphere Allen drawings; a large pad would leave a gap at the stitch.
    medial_pad = min(2, pad)
    x0 = max(0, x0 - medial_pad)
    x1 = min(w, x1 + pad)
    return y0, y1, x0, x1


def _trim_empty_margins(
    mask_arr: np.ndarray,
    border: np.ndarray,
    col_frac_thr: float = 0.02,
    row_frac_thr: float = 0.01,
) -> Tuple[np.ndarray, np.ndarray]:
    """Drop rows/cols that are essentially empty (rigid crop — no row warping)."""
    content = (mask_arr > 0)
    if border is not None and border.ndim == 3 and border.shape[2] >= 4:
        content = content | (border[..., 3] > 0)
    if not content.any():
        return mask_arr, border

    col_frac = content.mean(axis=0)
    row_frac = content.mean(axis=1)
    cols = np.where(col_frac > col_frac_thr)[0]
    rows = np.where(row_frac > row_frac_thr)[0]
    if len(cols) == 0 or len(rows) == 0:
        return mask_arr, border
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    return mask_arr[y0:y1, x0:x1].copy(), border[y0:y1, x0:x1].copy()


def _nissl_brain_mask(nissl_img: Image.Image):
    """Return (brain_bool, gray) for Allen Nissl (dark tissue on light bg)."""
    try:
        from skimage.filters import threshold_otsu
        from scipy import ndimage as ndi
    except ImportError:
        threshold_otsu = None
        ndi = None

    gray = np.asarray(nissl_img.convert("L"), dtype=np.float64)
    if gray.size < 100:
        return None, gray

    if threshold_otsu is not None:
        thr = float(threshold_otsu(gray.astype(np.uint8)))
    else:
        thr = float(np.percentile(gray, 55))
    brain = gray < thr
    if ndi is not None:
        brain = ndi.binary_fill_holes(brain)
        brain = ndi.binary_opening(brain, iterations=1)
        brain = ndi.binary_closing(brain, iterations=2)

    if brain.mean() < 0.02 or brain.mean() > 0.85:
        brain = gray > thr
        if ndi is not None:
            brain = ndi.binary_fill_holes(brain)
            brain = ndi.binary_opening(brain, iterations=1)
            brain = ndi.binary_closing(brain, iterations=2)
    return brain.astype(bool), gray


def _nissl_right_hemi_geometry(nissl_img: Image.Image) -> Optional[dict]:
    """Measure brain midline, right-half size, and fissure stats from the Nissl photo."""
    brain, _gray = _nissl_brain_mask(nissl_img)
    if brain is None or not brain.any():
        return None

    ys, xs = np.where(brain)
    if len(xs) < 50:
        return None

    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    mids = []
    for y in range(y0, y1):
        cols = np.flatnonzero(brain[y, x0:x1])
        if cols.size > 4:
            mids.append(x0 + int((int(cols[0]) + int(cols[-1])) // 2))
    mid = int(np.median(mids)) if mids else (x0 + x1) // 2

    right_w = 1
    for y in range(y0, y1):
        cols = np.flatnonzero(brain[y, mid:x1])
        if cols.size:
            right_w = max(right_w, int(cols[-1]) + 1)

    gaps = []
    gaps_dorsal = []
    brain_h = max(1, y1 - y0)
    for y in range(y0, y1):
        left_cols = np.flatnonzero(brain[y, :mid])
        right_cols = np.flatnonzero(brain[y, mid:])
        if left_cols.size and right_cols.size:
            gap = max(0, int(mid + right_cols[0]) - int(left_cols[-1]) - 1)
            gaps.append(gap)
            if (y - y0) / brain_h < 0.35:
                gaps_dorsal.append(gap)

    return {
        "mid": mid,
        "y0": y0,
        "y1": y1,
        "brain_h": brain_h,
        "right_w": int(right_w),
        "fissure_median": float(np.median(gaps)) if gaps else 0.0,
        "fissure_dorsal": float(np.median(gaps_dorsal)) if gaps_dorsal else 0.0,
        "fissure_p75": float(np.percentile(gaps, 75)) if gaps else 0.0,
    }


def _nissl_half_gap_profile(nissl_img: Image.Image) -> Optional[Tuple[np.ndarray, dict]]:
    """Per-row half-gap (midline → first right-hemi tissue), length = brain_h.

    Strategy B target: after stitch, each hemisphere's medial offset should match
    this profile (scaled into SVG pixels). Continuous tissue → ~0; fissure → >0.
    """
    brain, _ = _nissl_brain_mask(nissl_img)
    if brain is None or not brain.any():
        return None

    ys, xs = np.where(brain)
    if len(xs) < 50:
        return None

    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    mids = []
    for y in range(y0, y1):
        cols = np.flatnonzero(brain[y, x0:x1])
        if cols.size > 4:
            mids.append(x0 + int((int(cols[0]) + int(cols[-1])) // 2))
    mid = int(np.median(mids)) if mids else (x0 + x1) // 2
    brain_h = y1 - y0
    right_w = 1
    half_gap = np.full(brain_h, np.nan, dtype=np.float64)

    for i, y in enumerate(range(y0, y1)):
        right_cols = np.flatnonzero(brain[y, mid:x1])
        left_cols = np.flatnonzero(brain[y, : mid + 1])
        if right_cols.size:
            # Distance from midline to first right tissue
            half_gap[i] = float(right_cols[0])
            right_w = max(right_w, int(right_cols[-1]) + 1)
        # If both sides present, also consider symmetric full-gap/2 (more stable)
        if left_cols.size and right_cols.size:
            full = float(mid + right_cols[0] - left_cols[-1] - 1)
            half_gap[i] = max(0.0, full * 0.5)

    # Cap absurd gaps (bad segmentation) at ~12% of half-brain width
    cap = max(2.0, 0.12 * right_w)
    valid = np.isfinite(half_gap)
    if valid.any():
        half_gap = np.clip(half_gap, 0.0, cap)
        half_gap = _interp_nan_1d(half_gap)
        half_gap = _smooth_1d(half_gap, sigma=max(2.0, brain_h / 40.0))
        half_gap = np.clip(half_gap, 0.0, cap)

    geo = {
        "mid": mid,
        "y0": y0,
        "y1": y1,
        "brain_h": brain_h,
        "right_w": int(right_w),
        "fissure_median": float(np.median(half_gap) * 2) if brain_h else 0.0,
        "fissure_dorsal": float(np.median(half_gap[: max(1, brain_h // 3)]) * 2)
        if brain_h
        else 0.0,
        "fissure_p75": float(np.percentile(half_gap, 75) * 2) if brain_h else 0.0,
    }
    return half_gap, geo


def _interp_nan_1d(x: np.ndarray) -> np.ndarray:
    """Linear-interpolate NaNs; edge NaNs filled from nearest valid."""
    out = x.astype(np.float64).copy()
    n = len(out)
    idx = np.arange(n)
    valid = np.isfinite(out)
    if not valid.any():
        return np.zeros(n, dtype=np.float64)
    if valid.all():
        return out
    out[~valid] = np.interp(idx[~valid], idx[valid], out[valid])
    return out


def _smooth_1d(x: np.ndarray, sigma: float = 3.0) -> np.ndarray:
    try:
        from scipy.ndimage import gaussian_filter1d
        return gaussian_filter1d(x.astype(np.float64), sigma=max(0.5, float(sigma)), mode="nearest")
    except ImportError:
        # Simple moving average fallback
        r = max(1, int(round(sigma * 2)))
        pad = np.pad(x.astype(np.float64), (r, r), mode="edge")
        ker = np.ones(2 * r + 1) / (2 * r + 1)
        return np.convolve(pad, ker, mode="valid")


def _clamp_gradient_1d(x: np.ndarray, max_step: float) -> np.ndarray:
    """Limit |x[i]-x[i-1]| to max_step (forward then backward pass)."""
    out = x.astype(np.float64).copy()
    max_step = max(0.0, float(max_step))
    for i in range(1, len(out)):
        d = out[i] - out[i - 1]
        if d > max_step:
            out[i] = out[i - 1] + max_step
        elif d < -max_step:
            out[i] = out[i - 1] - max_step
    for i in range(len(out) - 2, -1, -1):
        d = out[i] - out[i + 1]
        if d > max_step:
            out[i] = out[i + 1] + max_step
        elif d < -max_step:
            out[i] = out[i + 1] - max_step
    return out


def _outer_silhouette(mask_arr: np.ndarray, border: np.ndarray) -> np.ndarray:
    """Filled outer brain silhouette (Strategy C) — not internal structure voids.

    Left edge of this mask is the medial wall of the hemisphere drawing as a whole,
    so V2M/A30 internal boundaries don't independently pull the midline closed.
    """
    content = mask_arr > 0
    if border is not None and border.ndim == 3 and border.shape[2] >= 4:
        content = content | (border[..., 3] > 0)
    try:
        from scipy import ndimage as ndi
        sil = ndi.binary_closing(content, iterations=4)
        sil = ndi.binary_fill_holes(sil)
        # Keep largest connected component (the hemi body)
        labeled, nlab = ndi.label(sil)
        if nlab > 1:
            counts = np.bincount(labeled.ravel())
            counts[0] = 0
            sil = labeled == int(np.argmax(counts))
        return sil.astype(bool)
    except ImportError:
        return content.astype(bool)


def _row_left_edges(sil: np.ndarray) -> np.ndarray:
    """Per-row first True column; NaN if row empty."""
    hh, hw = sil.shape
    edges = np.full(hh, np.nan, dtype=np.float64)
    for y in range(hh):
        cols = np.flatnonzero(sil[y])
        if cols.size:
            edges[y] = float(cols[0])
    return edges


def _apply_row_shifts_left(
    mask_arr: np.ndarray, border: np.ndarray, shifts: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """Shift each row left by shifts[y] (whole row — interior locked to outer)."""
    hh, hw = mask_arr.shape[:2]
    shifts_i = np.clip(np.rint(shifts), 0, max(0, hw - 1)).astype(np.int32)
    new_m = np.zeros_like(mask_arr)
    new_b = np.zeros_like(border)
    for y in range(hh):
        s = int(shifts_i[y])
        if s <= 0:
            new_m[y] = mask_arr[y]
            new_b[y] = border[y]
        elif s < hw:
            new_m[y, : hw - s] = mask_arr[y, s:]
            new_b[y, : hw - s] = border[y, s:]
    return new_m, new_b


def _resize_hemi(
    mask_arr: np.ndarray, border: np.ndarray, new_w: int, new_h: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Resize hemi mask (nearest) + border (bilinear) to new size."""
    new_w = max(4, int(new_w))
    new_h = max(4, int(new_h))
    m_img = Image.fromarray(mask_arr, mode="L").resize((new_w, new_h), Image.NEAREST)
    b_img = Image.fromarray(border, mode="RGBA").resize((new_w, new_h), Image.BILINEAR)
    b = np.array(b_img)
    b[b[..., 3] < 40] = 0
    b[b[..., 3] >= 40, 3] = 255
    b[b[..., 3] >= 40, :3] = 0
    return np.array(m_img, dtype=np.uint8), b


def _nissl_midline_x(nissl_img: Image.Image, width: Optional[int] = None) -> int:
    """Estimate vertical midline x from Nissl tissue (median of per-row midpoints)."""
    w = width if width is not None else nissl_img.size[0]
    brain, _ = _nissl_brain_mask(nissl_img)
    if brain is None or not brain.any():
        return w // 2
    if brain.shape[1] != w or brain.shape[0] != nissl_img.size[1]:
        bimg = Image.fromarray(brain.astype(np.uint8) * 255, mode="L").resize(
            (w, nissl_img.size[1]), Image.NEAREST
        )
        brain = np.array(bimg) > 127
    ys, xs = np.where(brain)
    if len(xs) < 20:
        return w // 2
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    mids = []
    for y in range(y0, y1):
        cols = np.flatnonzero(brain[y])
        if cols.size > 4:
            mids.append(int((int(cols[0]) + int(cols[-1])) // 2))
    if not mids:
        return w // 2
    return int(np.clip(int(np.median(mids)), 1, w - 2))


def _nissl_tissue_mask_for_stitch(nissl_img: Image.Image, shape_hw: Tuple[int, int]) -> np.ndarray:
    """Brain tissue mask at (H,W), closed enough that thin midline white doesn't fake a gap."""
    h, w = shape_hw
    brain, _ = _nissl_brain_mask(nissl_img)
    if brain is None or not brain.any():
        return np.zeros((h, w), dtype=bool)
    if brain.shape[0] != h or brain.shape[1] != w:
        brain = np.array(
            Image.fromarray(brain.astype(np.uint8) * 255, mode="L").resize(
                (w, h), Image.NEAREST
            )
        ) > 127
    try:
        from scipy import ndimage as ndi
        # Close small fissures/ventricle slits so continuous tissue reads continuous,
        # but use a modest radius so the true longitudinal fissure remains.
        brain = ndi.binary_closing(brain, iterations=3)
        brain = ndi.binary_fill_holes(brain)
    except ImportError:
        pass
    return brain.astype(bool)


def _nissl_half_gap_from_intensity(
    nissl_img: Image.Image, mid: int, shape_hw: Tuple[int, int]
) -> np.ndarray:
    """Per-row half-gap from Nissl intensity at the midline.

    Allen Nissl: dark tissue, light background. A bright run straddling the
    midline is fissure/ventricle (keep gap). Dark tissue at midline → gap 0.
    """
    h, w = shape_hw
    gray = np.asarray(nissl_img.convert("L"), dtype=np.float64)
    if gray.shape[0] != h or gray.shape[1] != w:
        gray = np.asarray(
            nissl_img.convert("L").resize((w, h), Image.BILINEAR), dtype=np.float64
        )
    mid = int(np.clip(mid, 1, w - 2))

    try:
        from skimage.filters import threshold_otsu
        thr = float(threshold_otsu(gray.astype(np.uint8)))
    except Exception:
        # Image is mostly white background — tissue is the darker minority
        thr = float(np.percentile(gray, 35))

    # Non-tissue / background / fissure
    non_tissue = gray >= thr
    half = np.full(h, np.nan, dtype=np.float64)
    win = max(12, w // 25)

    for y in range(h):
        row = gray[y]
        # Skip empty rows (almost no tissue)
        if (row < thr).mean() < 0.015:
            continue
        x0 = max(0, mid - win)
        x1 = min(w, mid + win + 1)
        bright = non_tissue[y, x0:x1]
        local_mid = mid - x0
        if local_mid < 0 or local_mid >= len(bright):
            continue
        if not bright[local_mid]:
            half[y] = 0.0
            continue
        L = local_mid
        while L > 0 and bright[L - 1]:
            L -= 1
        R = local_mid
        while R < len(bright) - 1 and bright[R + 1]:
            R += 1
        # Distance from mid to first tissue on the right
        half[y] = float(max(0, R - local_mid + 1))
        half[y] = min(half[y], float(win))

    if np.isfinite(half).any():
        half = _interp_nan_1d(half)
        half = _smooth_1d(half, sigma=max(2.0, h / 40.0))
        half = np.clip(half, 0.0, float(win))
    return half


def _align_right_hemi_medial_to_nissl(
    mask_arr: np.ndarray,
    border: np.ndarray,
    nissl_img: Image.Image,
    mid: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Smoothly shift the right-half drawing so its outer medial edge matches Nissl.

    (Preferred stitch version: right-half shift + Nissl intensity target.)
    """
    h, w = mask_arr.shape[:2]
    mid = int(np.clip(mid, 1, w - 2))

    sil = _outer_silhouette(mask_arr, border)

    d_svg = np.full(h, np.nan, dtype=np.float64)
    for y in range(h):
        cols_s = np.flatnonzero(sil[y, mid:])
        if cols_s.size:
            d_svg[y] = float(cols_s[0])
        else:
            cols_s = np.flatnonzero(sil[y])
            if cols_s.size and cols_s[0] >= mid - 2:
                d_svg[y] = float(cols_s[0] - mid)

    if not np.isfinite(d_svg).any():
        return mask_arr, border

    d_svg_f = _interp_nan_1d(d_svg)

    d_nis = _nissl_half_gap_from_intensity(nissl_img, mid, (h, w))
    if np.isfinite(d_nis).any() and float(np.mean(np.isfinite(d_nis))) > 0.1:
        brain = _nissl_tissue_mask_for_stitch(nissl_img, (h, w))
        d_bin = np.full(h, np.nan, dtype=np.float64)
        for y in range(h):
            cols_b = np.flatnonzero(brain[y, mid:])
            if cols_b.size:
                d_bin[y] = float(cols_b[0])
        if np.isfinite(d_bin).any():
            d_bin_f = np.clip(_interp_nan_1d(d_bin), 0.0, max(2.0, 0.10 * (w - mid)))
            target = np.minimum(_interp_nan_1d(d_nis), d_bin_f)
        else:
            target = _interp_nan_1d(d_nis)
        target = _smooth_1d(target, sigma=max(2.0, h / 35.0))
    else:
        t = np.linspace(0.0, 1.0, h)
        target = d_svg_f * (0.50 * (1.0 - t) ** 1.3 + 0.02)

    target = np.minimum(target, d_svg_f)
    target = np.clip(target, 0.0, max(1.0, 0.12 * (w - mid)))

    shifts = np.maximum(0.0, d_svg_f - target)
    shifts = _smooth_1d(shifts, sigma=max(2.5, h / 28.0))
    shifts = _clamp_gradient_1d(shifts, max_step=max(1.0, (w - mid) / 90.0))
    shifts = np.clip(shifts, 0.0, max(0.0, (w - mid) - 2.0))

    out_m = mask_arr.copy()
    out_b = border.copy()
    for y in range(h):
        s = int(round(float(shifts[y])))
        if s <= 0:
            continue
        right_m = mask_arr[y, mid:].copy()
        right_b = border[y, mid:].copy()
        rw = right_m.shape[0]
        if s >= rw:
            continue
        new_rm = np.zeros_like(right_m)
        new_rb = np.zeros_like(right_b)
        new_rm[: rw - s] = right_m[s:]
        new_rb[: rw - s] = right_b[s:]
        out_m[y, mid:] = new_rm
        out_b[y, mid:] = new_rb

    logger.info(
        f"Nissl medial align: shift dorsal={float(np.median(shifts[: max(1, h // 3)])):.1f} "
        f"mid={float(np.median(shifts[h // 3 : 2 * h // 3])):.1f} "
        f"ventral={float(np.median(shifts[2 * h // 3 :])):.1f}"
    )
    return out_m, out_b


def _mirror_across_nissl_midline(
    mask_arr: np.ndarray,
    outline_rgba: Image.Image,
    nissl_img: Image.Image,
) -> Tuple[np.ndarray, Image.Image, int]:
    """Mirror structure drawing across the Nissl midline in *image coordinates*.

    Preferred version:
      1. SVG already on Nissl pixel grid
      2. Align right-hemi outer medial edge to Nissl tissue
      3. Reflect right → left across Nissl midline
    """
    h, w = mask_arr.shape[:2]
    if nissl_img.size != (w, h):
        nissl_use = nissl_img.resize((w, h), Image.BILINEAR)
    else:
        nissl_use = nissl_img

    mid = _nissl_midline_x(nissl_use, width=w)

    content = _content_mask(mask_arr, outline_rgba)
    if content.any():
        xs = np.where(content)[1]
        c_left = int(xs.min())
        right_mass = float(content[:, mid:].sum())
        left_mass = float(content[:, :mid].sum())
        if right_mass < 10:
            mid = max(1, c_left)
            logger.info(f"Nissl mid adjusted to content medial edge mid={mid}")
        elif left_mass > 0.25 * right_mass:
            mid = int((int(xs.min()) + int(xs.max())) // 2)
            logger.info(f"Content bilateral-ish; mid from content span mid={mid}")

    mid = int(np.clip(mid, 1, w - 2))
    border = np.asarray(outline_rgba)

    mask_arr, border = _align_right_hemi_medial_to_nissl(
        mask_arr, border, nissl_use, mid
    )

    out_m = mask_arr.copy()
    out_b = border.copy()

    # Left half = reflection of right; right half stays as aligned Allen drawing
    left_cols = np.arange(mid, dtype=np.int32)
    src_cols = 2 * mid - left_cols
    valid = (src_cols >= 0) & (src_cols < w)
    out_m[:, :mid] = 0
    out_b[:, :mid] = 0
    if valid.any():
        lc = left_cols[valid]
        sc = src_cols[valid]
        out_m[:, lc] = mask_arr[:, sc]
        out_b[:, lc] = border[:, sc]

    out_m[:, mid:] = mask_arr[:, mid:]
    out_b[:, mid:] = border[:, mid:]

    logger.info(
        f"Nissl-space midline mirror: mid={mid} grid={w}x{h} "
        f"left_filled={(out_m[:, :mid] > 0).mean():.2%} "
        f"right_filled={(out_m[:, mid:] > 0).mean():.2%}"
    )
    return out_m, Image.fromarray(out_b, "RGBA"), mid


def _mirror_stitch_hemispheres(
    mask_arr: np.ndarray,
    outline_rgba: Image.Image,
    pad: int = 12,
    nissl: Optional[Image.Image] = None,
) -> Tuple[np.ndarray, Image.Image, int]:
    """Back-compat wrapper → Nissl-space midline mirror + content crop."""
    if nissl is None:
        # No Nissl: fall back to geometric mid of content bbox
        content = _content_mask(mask_arr, outline_rgba)
        if not content.any():
            return mask_arr, outline_rgba, mask_arr.shape[1] // 2
        h, w = mask_arr.shape
        mid = w // 2
        dummy = Image.new("RGB", (w, h), (255, 255, 255))
        m, o, mid = _mirror_across_nissl_midline(mask_arr, outline_rgba, dummy)
    else:
        m, o, mid = _mirror_across_nissl_midline(mask_arr, outline_rgba, nissl)
    m, o = _crop_to_content(m, o, pad=pad)
    # mid_x after crop: approximate half width
    return m, o, m.shape[1] // 2


def _strip_hemisphere_label(label: str) -> str:
    """Remove prior L/R tags from a zone label ( (L), _r, etc.)."""
    s = str(label or "").strip()
    if not s:
        return s
    for tag in (
        " (L)", " (R)", " (l)", " (r)",
        " (left)", " (right)", " (Left)", " (Right)",
        "_L", "_R", "_l", "_r",
        "-L", "-R", "-l", "-r",
    ):
        if s.endswith(tag):
            s = s[: -len(tag)].rstrip()
    # Also strip hemi tag before a colon: "V2M_r: Name" → "V2M: Name"
    if ":" in s:
        head, tail = s.split(":", 1)
        head = head.strip()
        for tag in ("_L", "_R", "_l", "_r", " (L)", " (R)", " (l)", " (r)"):
            if head.endswith(tag):
                head = head[: -len(tag)].rstrip()
        s = f"{head}: {tail.strip()}" if tail.strip() else head
    return s.strip()


def _format_hemisphere_zone_name(base_name: str, meta: Optional[dict], hemi: str) -> str:
    """Build a clear hemispheric label: ``{acronym}_r`` / ``{acronym}_l``.

    Examples: ``V2M_r``, ``V2M_l: Secondary visual area``.
    ``hemi`` is ``\"l\"`` or ``\"r\"`` (case-insensitive).
    """
    h = str(hemi or "").strip().lower()
    if h not in ("l", "r"):
        h = "r" if h.startswith("r") else "l"
    meta = meta or {}
    acr = str(meta.get("acronym") or "").strip()
    full = str(meta.get("name") or "").strip()
    base = _strip_hemisphere_label(base_name)

    if not acr:
        if ":" in base:
            head, tail = base.split(":", 1)
            acr = head.strip()
            if not full:
                full = tail.strip()
        else:
            acr = base.strip() or "Zone"
    acr = _strip_hemisphere_label(acr)
    # Drop trailing _l/_r from acronym if present
    if len(acr) > 2 and acr[-2:].lower() in ("_l", "_r"):
        acr = acr[:-2]

    tagged = f"{acr}_{h}"
    if full and full != acr and _strip_hemisphere_label(full) != acr:
        full_clean = _strip_hemisphere_label(full)
        return f"{tagged}: {full_clean}"
    return tagged


def _bilateral_name_maps(
    used_ids: list,
    zone_names: Dict[int, str],
    zone_meta: Dict[int, dict],
    old_to_right: Dict[int, int],
    old_to_left: Dict[int, int],
) -> Tuple[Dict[int, str], Dict[int, dict]]:
    """Build zone_names / zone_meta with ``_r`` / ``_l`` for a bilateral remap."""
    new_names: Dict[int, str] = {}
    new_meta: Dict[int, dict] = {}
    for old in used_ids:
        rid = old_to_right[old]
        lid = old_to_left[old]
        base = zone_names.get(old, f"Zone{old}")
        meta = dict(zone_meta.get(old, {}))
        new_names[rid] = _format_hemisphere_zone_name(base, meta, "r")
        new_names[lid] = _format_hemisphere_zone_name(base, meta, "l")
        meta_r = dict(meta)
        meta_r["hemisphere"] = "r"
        meta_r["display"] = new_names[rid]
        meta_r["acronym_hemi"] = new_names[rid].split(":")[0].strip()
        meta_l = dict(meta)
        meta_l["hemisphere"] = "l"
        meta_l["display"] = new_names[lid]
        meta_l["acronym_hemi"] = new_names[lid].split(":")[0].strip()
        meta_l["mirror_of_local_id"] = rid
        new_meta[rid] = meta_r
        new_meta[lid] = meta_l
    return new_names, new_meta


def _content_midline_x(mask_arr: np.ndarray) -> int:
    """Midline X from horizontal span of non-zero mask content."""
    content = mask_arr > 0
    if not np.any(content):
        return int(mask_arr.shape[1] // 2)
    xs = np.where(content.any(axis=0))[0]
    if xs.size == 0:
        return int(mask_arr.shape[1] // 2)
    return int((int(xs.min()) + int(xs.max())) // 2)


def ensure_bilateral_hemisphere_zones(
    mask_arr: np.ndarray,
    zone_names: Optional[Dict[int, str]] = None,
    zone_meta: Optional[Dict[int, dict]] = None,
    mid_x: Optional[int] = None,
    min_side_frac: float = 0.02,
    min_side_px: int = 10,
) -> Tuple[np.ndarray, Dict[int, str], Dict[int, dict], bool]:
    """Split zone IDs that span both hemispheres into independent ``_r`` / ``_l`` zones.

    Allen drawings often use one structure ID for both sides after Reflect/mirror.
    Atlas Manager then shows a single entry that lights up both hemispheres. This
    assigns distinct uint8 IDs and names (e.g. ``V2M_r``, ``V2M_l``).

    Zones that only appear on one side keep a single ID tagged ``_r`` or ``_l``.

    Returns ``(mask, zone_names, zone_meta, did_change)``.
    """
    zone_names = {int(k): v for k, v in (zone_names or {}).items()}
    zone_meta = {int(k): dict(v) for k, v in (zone_meta or {}).items()}
    m = np.asarray(mask_arr)
    if m.ndim != 2:
        return mask_arr, zone_names, zone_meta, False

    h, w = m.shape[:2]
    if mid_x is None:
        mid_x = _content_midline_x(m)
    mid_x = int(np.clip(int(mid_x), 0, w))

    used = sorted(int(z) for z in np.unique(m) if int(z) > 0)
    if not used:
        return m.astype(np.uint8, copy=False), zone_names, zone_meta, False

    # Classify each zone: spans both sides vs unilateral
    span_both: List[int] = []
    left_only: List[int] = []
    right_only: List[int] = []
    for z in used:
        zm = m == z
        n_l = int(np.sum(zm[:, :mid_x]))
        n_r = int(np.sum(zm[:, mid_x:]))
        total = n_l + n_r
        if total <= 0:
            continue
        thr = max(int(min_side_px), int(float(min_side_frac) * total))
        if n_l >= thr and n_r >= thr:
            span_both.append(z)
        elif n_l > n_r:
            left_only.append(z)
        else:
            right_only.append(z)

    # Already independent if nothing spans both sides AND names already have hemi tags
    def _tagged(name: str) -> bool:
        s = str(name or "").lower()
        return (
            s.endswith("_l")
            or s.endswith("_r")
            or "_l:" in s
            or "_r:" in s
            or " (l)" in s
            or " (r)" in s
        )

    names_ok = all(_tagged(zone_names.get(z, "")) for z in used) if used else True
    if not span_both and names_ok:
        return m.astype(np.uint8, copy=False), zone_names, zone_meta, False

    # How many IDs do we need?
    n_need = 2 * len(span_both) + len(left_only) + len(right_only)
    # Prefer splitting larger bilateral structures if we must drop some splits
    if n_need > 255:
        # Sort spanning by area descending — keep splitting the largest first
        areas = []
        for z in span_both:
            areas.append((int(np.sum(m == z)), z))
        areas.sort(reverse=True)
        budget = 255 - (len(left_only) + len(right_only))
        max_split = max(0, budget // 2)
        keep_split = [z for _, z in areas[:max_split]]
        drop_split = [z for _, z in areas[max_split:]]
        # Dropped spanning zones stay as a single ID (still ambiguous) — warn
        if drop_split:
            logger.warning(
                f"Bilateral split: only {max_split}/{len(span_both)} spanning "
                f"structures fit in uint8 (255 IDs); {len(drop_split)} keep shared IDs"
            )
        # Unilateral may need to drop if still over — rare
        span_both = keep_split
        n_need = 2 * len(span_both) + len(left_only) + len(right_only)
        while n_need > 255 and right_only:
            right_only.pop()
            n_need = 2 * len(span_both) + len(left_only) + len(right_only)
        while n_need > 255 and left_only:
            left_only.pop()
            n_need = 2 * len(span_both) + len(left_only) + len(right_only)

    # Assign dense new IDs: all right-side IDs first (1..), then left-side IDs
    span_set = set(span_both)
    left_set = set(left_only)
    right_set = set(right_only)
    next_id = 1
    old_to_right: Dict[int, int] = {}
    old_to_left: Dict[int, int] = {}

    for z in sorted(span_set | right_set):
        old_to_right[z] = next_id
        next_id += 1
    for z in sorted(span_set | left_set):
        old_to_left[z] = next_id
        next_id += 1

    # Column index grid for hemisphere masks
    cols = np.arange(w, dtype=np.int32)[None, :]
    is_right = cols >= mid_x
    is_left = cols < mid_x

    out = np.zeros((h, w), dtype=np.uint8)
    for z, rid in old_to_right.items():
        if z in span_set:
            out[(m == z) & is_right] = np.uint8(rid)
        else:
            out[m == z] = np.uint8(rid)
    for z, lid in old_to_left.items():
        if z in span_set:
            out[(m == z) & is_left] = np.uint8(lid)
        else:
            out[m == z] = np.uint8(lid)

    # Orphans (structures we couldn't fully re-id under the 255 budget)
    orphan = (m > 0) & (out == 0)
    unilateral_map: Dict[int, Tuple[int, str]] = {}
    if np.any(orphan):
        leftover = sorted({int(z) for z in np.unique(m[orphan]) if int(z) > 0})
        used_ids = set(int(x) for x in np.unique(out) if int(x) > 0)
        free = [i for i in range(1, 256) if i not in used_ids]
        for z in leftover:
            if not free:
                logger.warning(f"Bilateral split: no free ID for orphan zone {z}")
                break
            nid = free.pop(0)
            out[(m == z) & orphan] = np.uint8(nid)
            zm = m == z
            hemi = "l" if int(zm[:, :mid_x].sum()) > int(zm[:, mid_x:].sum()) else "r"
            unilateral_map[z] = (nid, hemi)

    for z in right_set:
        if z in old_to_right:
            unilateral_map[z] = (old_to_right[z], "r")
    for z in left_set:
        if z in old_to_left:
            unilateral_map[z] = (old_to_left[z], "l")

    # Names / meta
    new_names: Dict[int, str] = {}
    new_meta: Dict[int, dict] = {}
    for z in span_set:
        rid = old_to_right.get(z)
        lid = old_to_left.get(z)
        base = zone_names.get(z, f"Zone{z}")
        meta = dict(zone_meta.get(z, {}))
        if rid is not None:
            new_names[rid] = _format_hemisphere_zone_name(base, meta, "r")
            mr = dict(meta)
            mr["hemisphere"] = "r"
            mr["display"] = new_names[rid]
            mr["paired_hemisphere_id"] = lid
            mr["source_zone_id"] = z
            new_meta[rid] = mr
        if lid is not None:
            new_names[lid] = _format_hemisphere_zone_name(base, meta, "l")
            ml = dict(meta)
            ml["hemisphere"] = "l"
            ml["display"] = new_names[lid]
            ml["paired_hemisphere_id"] = rid
            ml["source_zone_id"] = z
            ml["mirror_of_local_id"] = rid
            new_meta[lid] = ml

    for z, (nid, hemi) in unilateral_map.items():
        if z in span_set:
            continue
        base = zone_names.get(z, f"Zone{z}")
        meta = dict(zone_meta.get(z, {}))
        new_names[nid] = _format_hemisphere_zone_name(base, meta, hemi)
        mm = dict(meta)
        mm["hemisphere"] = hemi
        mm["display"] = new_names[nid]
        mm["source_zone_id"] = z
        new_meta[nid] = mm

    for zid in np.unique(out):
        zid = int(zid)
        if zid > 0 and zid not in new_names:
            new_names[zid] = f"Zone{zid}"
            new_meta[zid] = {"display": new_names[zid]}

    did = (
        len(span_set) > 0
        or any(not _tagged(zone_names.get(z, "")) for z in used)
        or set(int(k) for k in new_names.keys()) != set(used)
    )
    logger.info(
        f"Bilateral hemisphere split: mid_x={mid_x} spanning={len(span_set)} "
        f"left_only={len(left_set)} right_only={len(right_set)} "
        f"zones {len(used)} → {len(new_names)} (changed={did})"
    )
    return out, new_names, new_meta, bool(did)


def _assign_bilateral_zone_ids(
    mask_arr: np.ndarray,
    zone_names: Dict[int, str],
    zone_meta: Dict[int, dict],
    mid_x: int,
) -> Tuple[np.ndarray, Dict[int, str], Dict[int, dict]]:
    """Give left-hemisphere pixels distinct zone IDs so sides can be selected separately.

    Wrapper around :func:`ensure_bilateral_hemisphere_zones` (uint8, ``_r``/``_l`` names).
    """
    out, names, meta, _ = ensure_bilateral_hemisphere_zones(
        mask_arr, zone_names, zone_meta, mid_x=mid_x
    )
    return out, names, meta


def _crop_to_content(mask_arr: np.ndarray, outline_rgba: Image.Image, pad: int = 8):
    """Crop mask + outline RGBA to non-empty content with symmetric padding."""
    content = _content_mask(mask_arr, outline_rgba)
    if not content.any():
        return mask_arr, outline_rgba
    ys, xs = np.where(content)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    h, w = mask_arr.shape[:2]
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(h, y1 + pad)
    x1 = min(w, x1 + pad)
    mask_c = mask_arr[y0:y1, x0:x1].copy()
    border_c = np.asarray(outline_rgba)[y0:y1, x0:x1].copy()
    return mask_c, Image.fromarray(border_c, "RGBA")


def check_api_reachable(timeout: int = 15) -> Tuple[bool, str]:
    """Quick connectivity check."""
    try:
        d = _http_get_json(
            f"{API_BASE}/data/query.json?criteria="
            + quote("model::Atlas,rma::options[num_rows$eq1]", safe=""),
            timeout=timeout,
        )
        if d.get("success"):
            return True, "Allen Brain Atlas API reachable"
        return False, f"API responded but query failed: {d.get('msg')}"
    except Exception as e:
        return False, str(e)
