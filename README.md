# Pipeline Calamian (Mangroves + Landsat) — Windows/QGIS

## Pré-requis
- Python 3.12 OK (packages déjà installés : `pystac-client`, `planetary-computer`, `rasterio`, `numpy`).
- Tes 3 fichiers GeoTIFF mangroves doivent être copiés dans `F:\Tiff\` avec **exactement** ces noms :
  - `Mangrove_agb_Philipines.tif`
  - `Mangrove_hba95_Philipines.tif`
  - `Mangrove_hmax95_Philipines.tif`

La bbox et la période sont dans `config.json`.

## Exécution (tout en un)
Dans PowerShell, depuis `F:\Tiff` :

```powershell
.\run_all.ps1
```

## Sorties
- `outputs/mangrove_cropped/*.tif` : les 3 mangroves découpées à la bbox Calamian.
- `outputs/landsat/landsat_2000_2009_calamian_rgb.tif` : composite Landsat RGB 2000–2009 sur la bbox.
- `outputs/aligned/*_on_landsat.tif` : mangroves reprojetées/rééchantillonnées sur la grille Landsat.
- `outputs/aligned/mangrove_stack_3bands_on_landsat.tif` : stack 3 bandes (AGB, HBA95, HMAX95) aligné Landsat.

## Notes / dépannage
- Si le script Landsat affiche “impossible de trouver un triplet RGB”, ouvre `config.json` et adapte `landsat.rgb_asset_candidates` d’après les clés d’assets affichées.
- Si ton réseau/proxy bloque l’accès Planetary Computer, exécute d’abord uniquement :

```powershell
python .\scripts\landsat_composite_rgb.py
```

