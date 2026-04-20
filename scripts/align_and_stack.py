import json
import os
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject


@dataclass(frozen=True)
class TemplateGrid:
    crs: object
    transform: object
    width: int
    height: int


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _resampling(name: str) -> Resampling:
    name = (name or "").lower().strip()
    return {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "cubic_spline": Resampling.cubic_spline,
        "lanczos": Resampling.lanczos,
        "average": Resampling.average,
        "mode": Resampling.mode,
        "max": Resampling.max,
        "min": Resampling.min,
        "med": Resampling.med,
        "q1": Resampling.q1,
        "q3": Resampling.q3,
    }.get(name, Resampling.bilinear)


def reproject_to_template(src_path: str, dst_path: str, tmpl: TemplateGrid, nodata: float, resampling: Resampling) -> None:
    with rasterio.open(src_path) as src:
        src_data = src.read(1)

        dst_data = np.full((tmpl.height, tmpl.width), nodata, dtype="float32")
        reproject(
            source=src_data,
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=tmpl.transform,
            dst_crs=tmpl.crs,
            dst_nodata=nodata,
            resampling=resampling,
        )

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            crs=tmpl.crs,
            transform=tmpl.transform,
            width=tmpl.width,
            height=tmpl.height,
            count=1,
            nodata=nodata,
            tiled=True,
            compress="ZSTD",
            predictor=2,
        )

        _ensure_dir(os.path.dirname(dst_path))
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(dst_data, 1)


def stack_3bands(paths_in_order: List[str], dst_path: str, tmpl_profile: Dict, nodata: float) -> None:
    arrays = []
    for p in paths_in_order:
        with rasterio.open(p) as src:
            arrays.append(src.read(1).astype("float32"))

    profile = tmpl_profile.copy()
    profile.update(
        driver="GTiff",
        count=3,
        dtype="float32",
        nodata=nodata,
        tiled=True,
        compress="ZSTD",
        predictor=2,
    )

    _ensure_dir(os.path.dirname(dst_path))
    with rasterio.open(dst_path, "w", **profile) as dst:
        for i, arr in enumerate(arrays, start=1):
            dst.write(arr, i)


def main() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "config.json"), "r", encoding="utf-8") as f:
        cfg = json.load(f)

    landsat_rgb = os.path.join(here, cfg["landsat"]["output_rgb_path"])
    if not os.path.exists(landsat_rgb):
        raise FileNotFoundError(f"Référence Landsat introuvable: {landsat_rgb}")

    cropped_dir = os.path.join(here, cfg["outputs"]["mangrove_cropped_dir"])
    aligned_dir = os.path.join(here, cfg["outputs"]["aligned_dir"])
    _ensure_dir(aligned_dir)

    nodata = float(cfg["alignment"]["nodata"])
    resampling = _resampling(cfg["alignment"].get("resampling", "bilinear"))

    with rasterio.open(landsat_rgb) as ref:
        tmpl = TemplateGrid(crs=ref.crs, transform=ref.transform, width=ref.width, height=ref.height)
        tmpl_profile = ref.profile.copy()
        tmpl_profile.update(count=1, dtype="float32", nodata=nodata)

    # Ordre des bandes: AGB, HBA95, HMAX95
    name_map = {
        "agb": cfg["inputs"]["mangrove_agb"],
        "hba95": cfg["inputs"]["mangrove_hba95"],
        "hmax95": cfg["inputs"]["mangrove_hmax95"],
    }

    aligned_paths = []
    for short, orig_name in name_map.items():
        base = os.path.splitext(os.path.basename(orig_name))[0]
        cropped_path = os.path.join(cropped_dir, f"{base}_calamian.tif")
        if not os.path.exists(cropped_path):
            raise FileNotFoundError(f"Crop introuvable (as-tu lancé crop_mangroves.py ?) : {cropped_path}")

        dst_path = os.path.join(aligned_dir, f"{short}_on_landsat.tif")
        print(f"[align] {cropped_path} -> {dst_path}")
        reproject_to_template(cropped_path, dst_path, tmpl, nodata=nodata, resampling=resampling)
        aligned_paths.append(dst_path)

    stack_path = os.path.join(here, cfg["outputs"]["stack_path"])
    print(f"[stack] -> {stack_path}")
    stack_3bands(aligned_paths, stack_path, tmpl_profile=tmpl_profile, nodata=nodata)
    print("[align+stack] OK")


if __name__ == "__main__":
    main()

