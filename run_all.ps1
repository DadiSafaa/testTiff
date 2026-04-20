$ErrorActionPreference = "Stop"

function Invoke-Step($name, $cmd) {
  Write-Host $name
  & $cmd
  if ($LASTEXITCODE -ne 0) {
    throw "Step failed (exit code $LASTEXITCODE): $name"
  }
}

Write-Host "== Calamian pipeline =="
Invoke-Step "1) Crop mangrove GeoTIFFs" { python .\scripts\crop_mangroves.py }
Invoke-Step "2) Download + composite Landsat RGB (2000-2009)" { python .\scripts\landsat_composite_rgb.py }
Invoke-Step "3) Align mangroves on Landsat grid + stack 3 bands" { python .\scripts\align_and_stack.py }

Write-Host "Done. Outputs in .\outputs\"

