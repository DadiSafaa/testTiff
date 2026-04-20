import json
import os
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds


@dataclass(frozen=True)
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def as_tuple(self):
        return (self.xmin, self.ymin, self.xmax, self.ymax)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def crop_geotiff_to_bbox_epsg4326(src_path: str, dst_path: str, bbox4326: BBox, dst_nodata: float) -> None:
    with rasterio.open(src_path) as src:
        bbox_src = transform_bounds("EPSG:4326", src.crs, *bbox4326.as_tuple(), densify_pts=21)
        win = from_bounds(*bbox_src, transform=src.transform)

        data = src.read(1, window=win, boundless=True, fill_value=src.nodata)
        transform = rasterio.windows.transform(win, src.transform)

        # Normalize nodata -> dst_nodata
        out = data.astype("float32", copy=False)
        if src.nodata is not None:
            out = np.where(out == src.nodata, dst_nodata, out)

        profile = src.profile.copy()
        profile.update(
            driver="GTiff",
            height=out.shape[0],
            width=out.shape[1],
            count=1,
            transform=transform,
            nodata=dst_nodata,
            tiled=True,
            blockxsize=256,
            blockysize=256,
            compress="ZSTD",
            predictor=2,
        )

        _ensure_dir(os.path.dirname(dst_path))
        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(out, 1)


def main() -> None:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(here, "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    bbox_cfg = cfg["bbox_epsg4326"]
    bbox = BBox(**bbox_cfg)
    out_dir = os.path.join(here, cfg["outputs"]["mangrove_cropped_dir"])
    dst_nodata = float(cfg["alignment"]["nodata"])

    inputs = cfg["inputs"]
    for key, rel in inputs.items():
        src_path = os.path.join(here, rel)
        if not os.path.exists(src_path):
            raise FileNotFoundError(f"Fichier introuvable: {src_path}")

        base = os.path.splitext(os.path.basename(src_path))[0]
        dst_path = os.path.join(out_dir, f"{base}_calamian.tif")
        print(f"[crop] {src_path} -> {dst_path}")
        crop_geotiff_to_bbox_epsg4326(src_path, dst_path, bbox, dst_nodata=dst_nodata)

    print("[crop] OK")


if __name__ == "__main__":
    main()

