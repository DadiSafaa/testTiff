import json
import os
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
import rasterio
from pystac_client import Client
import planetary_computer as pc
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds


@dataclass(frozen=True)
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def as_tuple(self) -> Tuple[float, float, float, float]:
        return (self.xmin, self.ymin, self.xmax, self.ymax)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _pick_rgb_keys(available: Iterable[str], candidates: Sequence[Sequence[str]]) -> Optional[Tuple[str, str, str]]:
    available = set(available)
    for triplet in candidates:
        if len(triplet) != 3:
            continue
        if all(k in available for k in triplet):
            return (triplet[0], triplet[1], triplet[2])
    return None


def _read_asset_window(item, asset_key: str, bbox4326: BBox):
    href = pc.sign(item.assets[asset_key].href)
    with rasterio.open(href) as src:
        bbox_src = transform_bounds("EPSG:4326", src.crs, *bbox4326.as_tuple(), densify_pts=21)
        win = from_bounds(*bbox_src, transform=src.transform)
        arr = src.read(1, window=win, boundless=True, fill_value=src.nodata)
        tr = rasterio.windows.transform(win, src.transform)
        prof = src.profile
        return arr, prof, tr


def _warp_to_template(
    src_arr: np.ndarray,
    src_profile: dict,
    src_transform,
    dst_crs,
    dst_transform,
    dst_height: int,
    dst_width: int,
) -> np.ndarray:
    nod = src_profile.get("nodata")
    dst = np.full((dst_height, dst_width), np.nan, dtype="float32")
    reproject(
        source=src_arr.astype("float32", copy=False),
        destination=dst,
        src_transform=src_transform,
        src_crs=src_profile.get("crs"),
        src_nodata=nod,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return dst


def main() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)

    bbox = BBox(**cfg["bbox_epsg4326"])
    landsat_cfg = cfg["landsat"]
    datetime_range = f'{cfg["time_range"]["start"]}/{cfg["time_range"]["end"]}'

    stac = Client.open(landsat_cfg["stac_api_url"])
    max_items = int(landsat_cfg.get("max_items", 120))
    search = stac.search(
        collections=[landsat_cfg["collection_id"]],
        bbox=list(bbox.as_tuple()),
        datetime=datetime_range,
        limit=min(max_items, 100),
        max_items=max_items,
    )
    # IMPORTANT: get_items() can paginate through *all* matches; items() respects max_items.
    items = list(search.items())
    print("[landsat] items trouvés:", len(items))
    if not items:
        raise SystemExit("[landsat] aucun item sur cette bbox/période")

    max_cloud = landsat_cfg.get("max_cloud_cover_percent", 100)

    def cloud_ok(it) -> bool:
        cc = it.properties.get("eo:cloud_cover")
        return (cc is None) or (cc <= max_cloud)

    items = [it for it in items if cloud_ok(it)]
    print("[landsat] items après filtre nuages:", len(items))
    if not items:
        raise SystemExit("[landsat] tous les items ont été filtrés par nuages (augmente max_cloud_cover_percent)")

    available_assets = list(items[0].assets.keys())
    rgb_keys = _pick_rgb_keys(available_assets, landsat_cfg["rgb_asset_candidates"])
    print("[landsat] exemple clés assets:", available_assets[:30])
    if rgb_keys is None:
        raise SystemExit(
            "[landsat] impossible de trouver un triplet RGB.\n"
            "Regarde les clés affichées et adapte config.json -> landsat.rgb_asset_candidates"
        )
    print("[landsat] RGB choisi:", rgb_keys)

    stacks = {"R": [], "G": [], "B": []}

    # Template grid: first readable scene window (ensures consistent shape/CRS)
    tmpl_crs = None
    tmpl_transform = None
    tmpl_h = None
    tmpl_w = None
    tmpl_profile = None

    # Find first item that can be read (as template)
    for it in items[:max_items]:
        try:
            r0, prof0, tr0 = _read_asset_window(it, rgb_keys[0], bbox)
            tmpl_crs = prof0.get("crs")
            tmpl_transform = tr0
            tmpl_h, tmpl_w = r0.shape
            tmpl_profile = prof0
            # Push the first item (no warp needed)
            nod0 = prof0.get("nodata")
            r0 = r0.astype("float32"); 
            if nod0 is not None:
                r0[r0 == nod0] = np.nan
            stacks["R"].append(r0)

            g0, _, _ = _read_asset_window(it, rgb_keys[1], bbox)
            b0, _, _ = _read_asset_window(it, rgb_keys[2], bbox)
            g0 = g0.astype("float32"); b0 = b0.astype("float32")
            if nod0 is not None:
                g0[g0 == nod0] = np.nan
                b0[b0 == nod0] = np.nan
            stacks["G"].append(g0)
            stacks["B"].append(b0)
            break
        except Exception as e:
            print("[landsat] skip(template)", it.id, "->", e)

    if tmpl_profile is None:
        raise SystemExit("[landsat] aucune scène lisible pour définir une grille de référence")

    for it in items[:max_items]:
        try:
            r, prof, tr = _read_asset_window(it, rgb_keys[0], bbox)
            g, _, _ = _read_asset_window(it, rgb_keys[1], bbox)
            b, _, _ = _read_asset_window(it, rgb_keys[2], bbox)

            nod = prof.get("nodata")
            r = r.astype("float32"); g = g.astype("float32"); b = b.astype("float32")
            if nod is not None:
                r[r == nod] = np.nan
                g[g == nod] = np.nan
                b[b == nod] = np.nan

            # Warp if grid differs from template
            if (prof.get("crs") != tmpl_crs) or (r.shape != (tmpl_h, tmpl_w)) or (tr != tmpl_transform):
                r = _warp_to_template(r, prof, tr, tmpl_crs, tmpl_transform, tmpl_h, tmpl_w)
                g = _warp_to_template(g, prof, tr, tmpl_crs, tmpl_transform, tmpl_h, tmpl_w)
                b = _warp_to_template(b, prof, tr, tmpl_crs, tmpl_transform, tmpl_h, tmpl_w)

            stacks["R"].append(r)
            stacks["G"].append(g)
            stacks["B"].append(b)
        except Exception as e:
            print("[landsat] skip", it.id, "->", e)

    if not stacks["R"]:
        raise SystemExit("[landsat] aucune scène lisible après skips")

    method = landsat_cfg.get("composite_method", "median").lower()
    reducer = np.nanmedian if method == "median" else np.nanmean

    R = reducer(np.stack(stacks["R"], axis=0), axis=0)
    G = reducer(np.stack(stacks["G"], axis=0), axis=0)
    B = reducer(np.stack(stacks["B"], axis=0), axis=0)

    # Écriture: on garde dtype uint16 si possible (Landsat SR typiquement en uint16)
    def to_uint16(x):
        x = np.nan_to_num(x, nan=0.0)
        x = np.clip(x, 0, np.iinfo(np.uint16).max)
        return x.astype("uint16")

    R = to_uint16(R); G = to_uint16(G); B = to_uint16(B)

    out_path = os.path.join(here, landsat_cfg["output_rgb_path"])
    _ensure_dir(os.path.dirname(out_path))

    profile = tmpl_profile.copy()
    profile.update(
        driver="GTiff",
        count=3,
        height=R.shape[0],
        width=R.shape[1],
        crs=tmpl_crs,
        transform=tmpl_transform,
        tiled=True,
        compress="ZSTD",
        predictor=2,
    )

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(R, 1)
        dst.write(G, 2)
        dst.write(B, 3)

    print("[landsat] écrit:", out_path)
    print("[landsat] CRS:", profile.get("crs"))


if __name__ == "__main__":
    main()

