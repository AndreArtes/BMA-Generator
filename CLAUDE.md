# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```
pip install -r requirements.txt   # openpyxl, wxPython
python gui.py                     # GUI (wxPython) - primary interface
python main.py                    # CLI, guided mode (prompts for paths)
python main.py init-roles --bm3-dir "fichier bm3" --roles roles.xlsx
python main.py generate --bm3-dir "fichier bm3" --roles roles.xlsx --out-dir "fichier bma" [--brand NAME]
python main.py build-bm3 --src-dir test_bm3 --out-dir "fichier bm3_test" [--product-type T] [--brand B]
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
- **`bma_generator/bm3_reader.py`** — reads a `.BM3` file's dimensions (see below).
- **`bma_generator/bm3_builder.py`** — the upstream step: builds a bm3 export (one `<ID>/` folder per product + `export-products-bm3.xlsx`) from a flat folder of `.BM3` files (`<ID>.BM3` = HQ, optional `<ID>_MQ.BM3`/`<ID>_LQ.BM3`, optional `<ID>.jpg` thumbnail). Files are always copied, never moved. Only LODs actually provided get an Assets cell (MQ/LQ left empty otherwise). Reference/Product Type/Brand aren't in the 3D files: in the GUI (`gui.Bm3BuilderDialog`) Reference and Brand are free text, Product Type is restricted to `bm3_builder.PRODUCT_TYPES` (live substring filter via `gui.ProductTypeEditor`), dimensions/materials are pre-filled from the files but editable (untouched dimension cells keep full measured precision), and the role column is inferred from Reference unless set by hand. The role isn't part of the bm3 Excel: it is merged into the main window's roles file (`excel_io.update_roles_file`). Material parameters (mesh `publication`s such as `structureColor`) are written with Default/Values `"null"`.
- **`bma_generator/utilities_data.py`** — generated snapshot of a HomeByMe bm3 export's `Utilities` sheet (Product Type list, tags, Brands, ...), copied verbatim into every built bm3 Excel (the `.BMA` generator later copies `Utilities` from the bm3 Excel, so it must be there). Regenerate it from a recent export rather than hand-editing it. Its `Brands` column is deliberately blank (header kept, HomeByMe import requires the column): that list is client-specific and the repo is public, so it lives only in the git-ignored `brands_local.txt`; Brand is always typed in by hand.

### wxPython 4.3 grid gotchas

`Grid.GetSelectedBlocks()` returns a non-iterable object in this build — use `GetSelectionBlockTopLeft/BottomRight` + `GetSelectedCells/Rows/Cols`. After `wx.TheClipboard.SetData(...)`, call `Flush()` or an immediate paste (in-app or in Excel) reads nothing.

### `.BM3` file format (`bm3_reader`)

A `.BM3` is a zip with `manifest.json` (header `unit: "mm"`, `upAxis: "Z"`; glTF-like node tree with **column-major** 4x4 matrices — translation in the last 4 values — plus geometries/buffers/vertexLayouts) and `binary.bin` (interleaved FLOAT vertices, indices, embedded images). Dimensions = world-space AABB of all vertices: width = X, depth = Y, height = Z. Vertices are re-read rather than using the manifest's `boundingBox` (rounded to 6 digits), which reproduces the reference Excel's values to ~1e-11 mm. Always measure on HQ: LQ meshes are decimated and come out up to ~2 mm off.

### The role system (why it exists)

A product's `.BMA` anchor geometry (which tags it exposes, which it accepts, the position formulas) cannot be derived from the bm3 Excel alone — it encodes assembly knowledge (e.g. "this is the left arm of a modular sofa") that isn't in the data. So every product needs a **role** assigned in `roles.xlsx` before it can be generated; `Bm3Product.inferred_role` calls `templates.infer_role_from_reference()`, which matches keywords anywhere in the `Reference` column (not just as an exact prefix) against a cleaned version of the string — lowercased, with every character that isn't a plain/accented letter stripped (`templates._clean_reference`), so separators (`-`, `_`, ` `), digits, and casing never matter: `chaise_longue`, `Chaise-Longue`, `CHAISE LONGUE` and `chaiselongueDroite` all resolve the same way. The keyword lists (`_RIGHT_KEYWORDS`, `_LEFT_KEYWORDS`, `_CORNER_KEYWORDS`, `_CHAISE_LONGUE_KEYWORDS`, `_CENTRAL_KEYWORDS`) intentionally carry both English and French synonyms (e.g. corner matches `corner`/`angle`/`coin`, central matches `central`/`centre`) since real bm3 exports mix both; when a new naming variant shows up in the wild, extend the relevant keyword tuple rather than special-casing a reference string. Pouf/table references resolve through `_FRONTAL_KEYWORDS`/`_LATERAL_KEYWORDS` (`Pouf_frontal-...` → `pouf_frontal`); ambiguous ones (e.g. `Pouf-...` alone can't tell `pouf_lateral` from `pouf_frontal`) return `None` and are left for manual entry rather than guessed. A corner reference with a standalone `135` (checked on the raw string, since cleaning strips digits) maps to `corner_left_135`/`corner_right_135`. `templates.ALL_ROLES` is the closed set of currently-supported roles; supporting a genuinely new geometry means adding a new role function there, not configuring existing ones. **The anchor tag strings themselves (`CentralL`, `droit`, `chaiselonguegauche`, ...) are an arbitrary internal vocabulary, not a fixed schema** — different product families in the wild use completely different tag words and even opposite left/right sign conventions; what must stay consistent is only that a role's `tags` match the `receiveTags` of whatever it should physically connect to, within `templates.py`.

Tags, receive tags and the 135° angle can be customised without code changes: the roles file carries an `Anchors` sheet (one row per role × anchor number; written by `excel_io.write_roles_from_rows`, which preserves an existing sheet's edits, exposed in the GUI as "Download roles Excel..."). `excel_io.read_anchor_overrides` turns it into a `templates.AnchorOverrides`, applied by `templates.role_definition(role, overrides)` — always go through `role_definition`/`exposed_tags(role, overrides)`/`receive_tags(role, overrides)` rather than `build_role_definition`, or customised tags get ignored. Geometry (positions, relations) is deliberately not editable there.

The `corner_*_135` roles reproduce the hand-made reference `test_angle_135/root.bma` (relation names, including its `xOrintation` typo; that file also contains a stray U+00A0 in one expression, intentionally not copied): two lateral anchors at ±(width/2 − `offSetModule`), y=0, tilted by ±`angleRad` (default 15°, negative for left like `corner_left`'s front anchor, positive for right), plus an `offSetModule` number parameter (default 0). They are outside `LATERAL_ALIGN_ROLES`.

Every role except the two purely-frontal ones (`pouf_frontal`, `table_frontal`) — i.e. every role in `templates.LATERAL_ALIGN_ROLES` — has its *lateral* anchors' Y-position depend on *other* products in the same generation batch, so two connected modules' backs stay aligned even when their depths differ (e.g. a chaise longue is deeper than the modules attached to it). `generator.find_reference_depth()` looks up which other products in the batch expose a tag this role's anchors accept (via `templates.exposed_tags`/`receive_tags`), reads their depth, and injects it as a synthetic `profondeurModuleAttache` number parameter so the shared anchor formula (`-(profondeurModuleAttache*0.5 - MonModule.depth*0.5)`) can align backs instead of centering (when both depths are equal this evaluates to 0, i.e. identical to the old fixed-center behavior). If depths disagree across candidate neighbours, it emits a warning and picks one rather than guessing silently; if none are found, it falls back to the product's own depth (no offset) — silently for most roles, but with a warning for the `chaise_longue`/`chaise_longue_left`/`chaise_longue_right` family (`templates.CHAISE_LONGUE_ROLES`), where a missing neighbour is more likely to be a real data gap. Front-facing anchors (`CentralF`, `AngleGaucheF`, `PoufFrontL`, `TableBasseF`, ...) are unaffected — they keep aligning on the product's own depth via their own formulas. `templates.CHAISE_LONGUE_ROLES` is also used to exclude chaise-longue products from being picked as *someone else's* reference depth, since their depth is intentionally non-standard.

### `.BMA` parameter schema (validated against real exported files)

Only bm3 parameters of `Type == "Product"` (material/product references, e.g. `structureColor`/`sofaColor`) are redeclared as top-level `parameters` and overloaded onto both the `MonModule` and `Package` components. Numeric dimensions (`width`/`height`/`depth`) are **not** redeclared — a validated reference `.bma` confirmed real exports omit them; relations reference `MonModule.width` etc. directly via `componentDependencies` instead. Don't reintroduce blanket numeric-parameter passthrough without checking against a real exported file first — this has flip-flopped once already. `extra_parameters` in `generator.build_bma_json` is the escape hatch for genuinely assembly-level synthetic values (currently only `profondeurModuleAttache`).

In the output Excel's Parameters sheet, a `Product`-type parameter coming from the bm3 source (material/product overloads like `structureColor`/`sofaColor`) gets the literal string `"null"` (not an empty cell) for Default/Values and `"true"` for Allow any value — those are customer choices resolved dynamically by the configurator, not fixed at export time. The `module` and `package` rows are also `Product`-typed but are administrative, not customer-facing: they must keep their real Default/Values (`product.product_id` / `<product_id>_p`), so `generator._output_row` takes a `dynamic=True` flag (default) that only those two call sites set to `False` to opt out of the null-ing behavior.

### ID prefixing (`gui.apply_prefix`)

Renames every product ID with a prefix for brand/namespace variants. It never mutates the source bm3 folder: it copies the referenced `.BM3` asset folders into a **sibling** directory (`<bm3_dir>_<prefix>`) and writes a prefixed copy of the bm3 Excel there (`excel_io.write_bm3_with_prefix`, which also rewrites Assets-sheet paths and, optionally, the Brand column). `Bm3Product.original_asset_id` is the immutable disk folder name; `Bm3Product.product_id` is the mutable logical/export ID — code that touches the filesystem must use `asset_id`/`original_asset_id`, code that writes into `.BMA`/Excel output must use `product_id`.

The output Excel's `Reference` column is the bm3 `Reference` verbatim (it used to be truncated to the numeric part; the user wants both catalogs to carry the same reference).

### wx.svg gotcha (affects every icon-rendering code path)

SVGs are loaded with `SVGimage.CreateFromBytes`, never `CreateFromFile`: nanosvg opens the path as a narrow string and fails on any non-ASCII character (the dev machine's user folder is `André`).


`wx.svg.SVGimage.ConvertToBitmap(width, height)` does **not** rescale a drawing to the requested size — it always renders at the SVG's own declared `width`/`height` attribute and pads/crops a canvas of the requested size around that. All SVGs under `assets/` therefore declare `width="256" height="256"` (with a smaller `viewBox`), and every call site renders once at that native size then derives other sizes via `wx.Image.Scale` (see `gui._svg_to_image`). Asking `ConvertToBitmap` for a size other than the SVG's declared native size silently crops the artwork instead of shrinking it.

### Splash screen shaping

`gui.SplashScreen` uses a real desktop-transparent window (`wx.FRAME_SHAPED` + `SetShape()`), not a plain colored background. The shape is built **once**, from a color-keyed bitmap via `wx.Region(bitmap, key_colour, 0)` — building it from the images' alpha channel directly (`wx.Region(bitmap)` with no key colour) segfaults on this wx build, and recomputing the shape every animation frame is what that alpha approach would have required. This is why the loading dots animate by pulsing brightness (`_pulse_colour`) rather than size: their silhouette must stay constant so the one precomputed shape always matches. `_threshold_image` hard-thresholds alpha before color-keying, because antialiased edge pixels blend *toward* the key color without ever exactly matching it, which otherwise left a visible speckled fringe when they got included in the region.
