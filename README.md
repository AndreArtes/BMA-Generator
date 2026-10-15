# BMA Generator

Generates `.BMA` 3D-configurator assembly files from a "bm3" product export
(an Excel catalog + one folder of `.BM3` model files per product), for
[HomeByMe / 3DCloud](https://3dcloud-doc.enterprise.by.me/docs/3dcloud/introduction)-based
catalogs.

## Install

```
pip install -r requirements.txt
```

## Use

```
python gui.py      # GUI (recommended)
python main.py     # CLI
```

A pre-built Windows executable is available under `dist/` -- no Python
install required, just run `BMA Generator.exe`.

## What it does

1. Reads a bm3 Excel export (`Product ID`, dimensions, per-product
   parameters) and its matching `.BM3` model folders.
2. You assign each product an assembly **role** (how it connects to
   neighbouring modules -- central, corner, chaise longue, etc.) in a
   `roles.xlsx` file; the tool infers it automatically where the product
   reference is unambiguous.
3. It generates one `<ProductID>_ass` folder per product (HQ/MQ/LQ `.BMA`
   files + thumbnail) plus a companion output Excel catalog, ready to
   import into the target 3D configurator.

Two upstream helpers prepare the inputs from raw 3D files (buttons in the
GUI, or `main.py build-bm3` / `main.py build-materials`):

- **Build bm3 from 3D files** -- a flat folder of `.BM3` models becomes a
  bm3 export (dimensions read from the models).
- **Build materials** -- a flat folder of `.BM3MAT` materials becomes a
  material export: one folder per material with HQ/MQ/LQ files (the LQ
  with reduced textures) and a thumbnail, plus an `export-products.xlsx`
  where every row has `Category ID` = `Material`.

See `CLAUDE.md` for architecture details.
