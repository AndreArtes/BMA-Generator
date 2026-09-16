# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
pip install -r requirements.txt   # openpyxl, wxPython
python gui.py                     # GUI (wxPython) - primary interface
python main.py                    # CLI, guided mode (prompts for paths)
python main.py init-roles --bm3-dir "fichier bm3" --roles roles.xlsx
python main.py generate --bm3-dir "fichier bm3" --roles roles.xlsx --out-dir "fichier bma" [--brand NAME]
```

There is no test suite, linter, or build step in this repo; `python main.py`/`python gui.py` running without exceptions on the sample data in `fichier bm3/` is the manual smoke test.

## Versioning & releases

The current version lives in `VERSION` (semver, e.g. `1.0.0`) — bump it (patch for fixes, minor for features, major for breaking changes) whenever a meaningful batch of changes is pushed, in the same commit as that work. The packaged `.exe` is **not** committed to the repo (see `.gitignore`); it is published as a GitHub Release asset per version instead, so the repo history doesn't grow with every rebuild:

```
python -m PyInstaller --onefile --windowed --name "BMA Generator" --icon assets/app.ico --add-data "assets;assets" gui.py
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
# then create a GitHub Release for that tag and upload dist/BMA Generator.exe as its asset
```

## What this tool does

Converts a "bm3" export (an Excel catalog + one folder of `.BM3` 3D model files per product) into a "bma" export: one `<ProductID>_ass` folder per product, each containing three identical `.BMA` JSON files (`HQ-root.BMA`, `MQ-root.BMA`, `LQ-root.BMA` — quality tiers never affect content) plus a thumbnail, and a companion `export-products-bma.xlsx` catalog. The `.BMA` files are consumed by a third-party 3D configurator (see `utills.txt` for the doc link); this repo has no way to render or validate them itself beyond re-deriving known-good examples by hand.

## Architecture

- **`main.py`** — CLI entry point (`init-roles`, `generate` subcommands, or guided prompts with no args).
- **`gui.py`** — wxPython GUI, the primary interface. Single file: a splash screen (`SplashScreen`) shown on every launch, then `MainFrame`. All business logic lives in `bma_generator/`; this file only wires widgets to it.
- **`bma_generator/excel_io.py`** — reads the bm3 Excel (`Bm3Product` model: id, dimensions, per-product parameter list, and a frozen snapshot of *every* Products-sheet column for pass-through), and reads/writes the `roles.xlsx` roles file.
- **`bma_generator/templates.py`** — the anchor/geometry knowledge base: one function per assembly "role" (`central`, `lateral_left`, `corner_left`, `pouf_frontal`, `chaise_longue`, etc.) returning the `relations` + `anchors` JSON fragments for that role.
- **`bma_generator/generator.py`** — assembles the final `.BMA` JSON and the output Excel rows from a `Bm3Product` + its assigned role.

### The role system (why it exists)

A product's `.BMA` anchor geometry (which tags it exposes, which it accepts, the position formulas) cannot be derived from the bm3 Excel alone — it encodes assembly knowledge (e.g. "this is the left arm of a modular sofa") that isn't in the data. So every product needs a **role** assigned in `roles.xlsx` before it can be generated; `Bm3Product.inferred_role` guesses it from the `Reference` column prefix (`Central-`, `Left-`, `chaiseLong-`, ...) when unambiguous, and leaves it for manual entry otherwise (e.g. `Pouf-...` alone can't tell `pouf_lateral` from `pouf_frontal`). `templates.ALL_ROLES` is the closed set of currently-supported roles; supporting a genuinely new geometry means adding a new role function there, not configuring existing ones. **The anchor tag strings themselves (`CentralL`, `droit`, `chaiselonguegauche`, ...) are an arbitrary internal vocabulary, not a fixed schema** — different product families in the wild use completely different tag words and even opposite left/right sign conventions; what must stay consistent is only that a role's `tags` match the `receiveTags` of whatever it should physically connect to, within `templates.py`.

The `chaise_longue` role is the one role whose anchor Y-position depends on *other* products in the same generation batch: `generator.find_reference_depth()` looks up which other products in the batch expose a tag this role's anchors accept (via `templates.exposed_tags`/`receive_tags`), reads their depth, and injects it as a synthetic `profondeurModuleAttache` number parameter so the anchor formula (`-(profondeurModuleAttache*0.5 - MonModule.depth*0.5)`) can align backs instead of centering. If depths disagree across candidates, or none are found, it emits a warning and falls back rather than guessing silently.

### `.BMA` parameter schema (validated against real exported files)

Only bm3 parameters of `Type == "Product"` (material/product references, e.g. `structureColor`/`sofaColor`) are redeclared as top-level `parameters` and overloaded onto both the `MonModule` and `Package` components. Numeric dimensions (`width`/`height`/`depth`) are **not** redeclared — a validated reference `.bma` confirmed real exports omit them; relations reference `MonModule.width` etc. directly via `componentDependencies` instead. Don't reintroduce blanket numeric-parameter passthrough without checking against a real exported file first — this has flip-flopped once already. `extra_parameters` in `generator.build_bma_json` is the escape hatch for genuinely assembly-level synthetic values (currently only `profondeurModuleAttache`).

In the output Excel's Parameters sheet, any parameter of type `Product` gets the literal string `"null"` (not an empty cell) for Default/Values and `"true"` for Allow any value — those are resolved dynamically by the configurator, not fixed at export time.

### ID prefixing (`gui.apply_prefix`)

Renames every product ID with a prefix for brand/namespace variants. It never mutates the source bm3 folder: it copies the referenced `.BM3` asset folders into a **sibling** directory (`<bm3_dir>_<prefix>`) and writes a prefixed copy of the bm3 Excel there (`excel_io.write_bm3_with_prefix`, which also rewrites Assets-sheet paths and, optionally, the Brand column). `Bm3Product.original_asset_id` is the immutable disk folder name; `Bm3Product.product_id` is the mutable logical/export ID — code that touches the filesystem must use `asset_id`/`original_asset_id`, code that writes into `.BMA`/Excel output must use `product_id`.

### wx.svg gotcha (affects every icon-rendering code path)

`wx.svg.SVGimage.ConvertToBitmap(width, height)` does **not** rescale a drawing to the requested size — it always renders at the SVG's own declared `width`/`height` attribute and pads/crops a canvas of the requested size around that. All SVGs under `assets/` therefore declare `width="256" height="256"` (with a smaller `viewBox`), and every call site renders once at that native size then derives other sizes via `wx.Image.Scale` (see `gui._svg_to_image`). Asking `ConvertToBitmap` for a size other than the SVG's declared native size silently crops the artwork instead of shrinking it.

### Splash screen shaping

`gui.SplashScreen` uses a real desktop-transparent window (`wx.FRAME_SHAPED` + `SetShape()`), not a plain colored background. The shape is built **once**, from a color-keyed bitmap via `wx.Region(bitmap, key_colour, 0)` — building it from the images' alpha channel directly (`wx.Region(bitmap)` with no key colour) segfaults on this wx build, and recomputing the shape every animation frame is what that alpha approach would have required. This is why the loading dots animate by pulsing brightness (`_pulse_colour`) rather than size: their silhouette must stay constant so the one precomputed shape always matches. `_threshold_image` hard-thresholds alpha before color-keying, because antialiased edge pixels blend *toward* the key color without ever exactly matching it, which otherwise left a visible speckled fringe when they got included in the region.
