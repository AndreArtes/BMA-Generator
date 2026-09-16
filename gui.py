"""
BMA Generator - graphical interface (wxPython).

Run with:
    python gui.py

The table is a single grid (wx.grid.Grid) with native frozen columns: Role
and Reference depth always stay visible on the left, while all the bm3
source columns (dynamic, depend on the loaded file, Brand included) scroll
horizontally on the right.
"""

import math
from pathlib import Path

import wx
import wx.grid

from bma_generator import excel_io, generator
from bma_generator import templates as tpl

ROLE_VALUES = [""] + tpl.ALL_ROLES

FROZEN_COLS = 2  # Role, Profondeur reference
ROLE_COL = 0
REF_DEPTH_COL = 1

ICON_SIZE = wx.Size(16, 16)

LOG_COLOURS = {
    "load": wx.Colour(30, 80, 200),      # loads: blue
    "generated": wx.Colour(0, 140, 0),   # generated products: green
    "warning": wx.Colour(184, 134, 11),  # warnings: yellow (amber, readable on white)
    "error": wx.Colour(200, 0, 0),       # errors: red
    "default": wx.Colour(0, 0, 0),
}


def _find_bm3_xlsx(bm3_dir):
    bm3_dir = Path(bm3_dir)
    candidates = [p for p in bm3_dir.glob("*.xlsx") if not p.name.startswith("~$")]
    if not candidates:
        raise FileNotFoundError(f"No .xlsx file found in {bm3_dir}")
    return candidates[0]


def _icon(art_id, size=ICON_SIZE):
    return wx.ArtProvider.GetBitmap(art_id, wx.ART_OTHER, size)


ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.svg"
SPLASH_FOLDER_PATH = ASSETS_DIR / "splash_folder.svg"
SPLASH_SHEET_PATH = ASSETS_DIR / "splash_sheet.svg"


def _svg_to_image(path, size):
    """Renders an SVG to a wx.Image at the given size.

    wx.svg.SVGimage.ConvertToBitmap(width, height) does NOT rescale the
    drawing to fit the requested canvas - it always draws at the SVG's own
    declared width/height (its "native" size) and just pads/crops a canvas
    of the requested size around that; asking for a size smaller than the
    native one silently crops the artwork instead of shrinking it. So we
    always render once at the SVG's native size and derive any other size
    via wx.Image.Scale, which does resize properly. All of this project's
    SVGs declare a native size of 256x256 for that reason."""
    import wx.svg
    svg = wx.svg.SVGimage.CreateFromFile(str(path))
    native = int(svg.width)
    image = svg.ConvertToBitmap(width=native, height=native).ConvertToImage()
    if size != native:
        image = image.Scale(size, size, wx.IMAGE_QUALITY_HIGH)
    return image


def _threshold_image(image, key_colour, threshold=127):
    """Returns a hard-edged (no antialiasing) copy of `image`: pixels with
    alpha above `threshold` keep their RGB, every other pixel becomes
    `key_colour`. Used only to build the splash window's fixed shape.

    Antialiased edge pixels have partial alpha, so when composited onto a
    key-colour background they blend towards it without landing exactly on
    it (e.g. 41% blue over magenta lands on a light purple, not magenta).
    wx.Region(bitmap, colour, tolerance) with tolerance=0 only excludes
    pixels that are an *exact* match, so that whole ring of near-but-not-
    quite-key-colour blended pixels around every shape (and around this
    icon's white elements especially) gets included in the region and
    stays visible - that ring of stray colour is what showed up as a rough,
    speckled border. Thresholding removes the blend entirely: a pixel is
    either fully "shape" or fully "key colour", so the region ends up with
    a clean (if slightly harder) edge instead."""
    width, height = image.GetWidth(), image.GetHeight()
    out = wx.Image(width, height)
    has_alpha = image.HasAlpha()
    kr, kg, kb = key_colour.Red(), key_colour.Green(), key_colour.Blue()
    for y in range(height):
        for x in range(width):
            alpha = image.GetAlpha(x, y) if has_alpha else 255
            if alpha > threshold:
                out.SetRGB(x, y, image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y))
            else:
                out.SetRGB(x, y, kr, kg, kb)
    return out


def _pulse_colour(base, t):
    """Lightens `base` towards white as t goes from 1 (full colour) down to
    0 (dim), for a glow-style pulse that never changes the dot's radius."""
    t = max(0.0, min(1.0, t))
    mix = (1 - t) * 0.65
    return wx.Colour(
        int(base.Red() + (255 - base.Red()) * mix),
        int(base.Green() + (255 - base.Green()) * mix),
        int(base.Blue() + (255 - base.Blue()) * mix),
    )


class SplashScreen(wx.Frame):
    """Welcome screen shown for 3 seconds on first launch: a blue folder
    icon, three pulsing dots, and a green sheet icon, side by side, on a
    transparent background (only the icons/dots are visible - the desktop
    shows through everywhere else).

    wx.Frame.SetShape() carves the window down to a region built from a
    colour-keyed bitmap (a background fill colour that never appears in the
    artwork, e.g. magenta, marks "outside"). This only works reliably as a
    *static* shape: the region is computed once, from the dots at their
    fixed radius, so it never needs recomputing. An earlier attempt built
    the region from the icons' alpha channel directly (wx.Region(bitmap)
    with no key colour) and recomputed it every animation frame - that
    crashed the process (segfault) on this wx build, so the dots animate by
    pulsing brightness instead of size: the circle's silhouette (and hence
    the window's shape) never changes, only its fill colour, which keeps
    SetShape() a one-time, verified-safe call."""

    DURATION_MS = 3000
    KEY_COLOUR = wx.Colour(255, 0, 255)
    DOT_COLOURS = [wx.Colour(214, 57, 57), wx.Colour(46, 160, 67), wx.Colour(224, 168, 0)]
    DOT_RADIUS = 11
    DOT_SPACING = 38
    GAP = 150  # width reserved for the 3 dots, between the two icons
    MARGIN = 24

    def __init__(self, on_done):
        style = wx.STAY_ON_TOP | wx.FRAME_NO_TASKBAR | wx.BORDER_NONE | wx.FRAME_SHAPED
        super().__init__(None, style=style)
        self._on_done = on_done

        self.folder_image = _svg_to_image(SPLASH_FOLDER_PATH, 256)
        self.sheet_image = _svg_to_image(SPLASH_SHEET_PATH, 256)
        self.phase = 0.0

        width = self.MARGIN * 2 + 256 + self.GAP + 256
        height = self.MARGIN * 2 + 256
        self.content_size = wx.Size(width, height)
        self.SetClientSize(self.content_size)
        self.CentreOnScreen()

        self.SetShape(wx.Region(self._render_mask(), self.KEY_COLOUR, 0))

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

        self.anim_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self.anim_timer)
        self.anim_timer.Start(30)

        self.close_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_finish, self.close_timer)
        self.close_timer.StartOnce(self.DURATION_MS)

    def _render_mask(self):
        """Hard-edged version of the full content (folder + sheet, via
        _threshold_image, plus the dots at full brightness drawn without
        antialiasing), used once to build the window's fixed shape - see
        _threshold_image for why a smooth/antialiased render isn't usable
        for this."""
        bmp = wx.Bitmap(self.content_size.width, self.content_size.height, 24)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(self.KEY_COLOUR))
        dc.Clear()

        y = self.MARGIN
        folder_mask = wx.Bitmap(_threshold_image(self.folder_image, self.KEY_COLOUR))
        sheet_mask = wx.Bitmap(_threshold_image(self.sheet_image, self.KEY_COLOUR))
        dc.DrawBitmap(folder_mask, self.MARGIN, y, useMask=False)
        dc.DrawBitmap(sheet_mask, self.content_size.width - self.MARGIN - 256, y, useMask=False)

        # Plain wx.DC ellipses (unlike wx.GraphicsContext) aren't
        # antialiased, so they already have the hard edge this mask needs.
        dc.SetPen(wx.TRANSPARENT_PEN)
        cx0 = self.MARGIN + 256 + self.GAP / 2
        cy = self.content_size.height / 2
        for i, colour in enumerate(self.DOT_COLOURS):
            cx = cx0 + (i - 1) * self.DOT_SPACING
            dc.SetBrush(wx.Brush(colour))
            dc.DrawEllipse(
                int(cx - self.DOT_RADIUS), int(cy - self.DOT_RADIUS), self.DOT_RADIUS * 2, self.DOT_RADIUS * 2
            )

        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _render(self):
        """Smooth (antialiased) version of the current frame, drawn fresh
        on every tick for the actual on-screen display. Its edges may
        extend a little beyond the fixed shape from _render_mask() (built
        from a harder threshold) or fall a little short of it; either way
        wx clips painting to the shape, so this never reintroduces the
        speckled border _threshold_image avoids - it only affects how soft
        the visible edge looks within that fixed outline."""
        bmp = wx.Bitmap(self.content_size.width, self.content_size.height, 24)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(self.KEY_COLOUR))
        dc.Clear()

        y = self.MARGIN
        dc.DrawBitmap(wx.Bitmap(self.folder_image), self.MARGIN, y, useMask=True)
        dc.DrawBitmap(
            wx.Bitmap(self.sheet_image), self.content_size.width - self.MARGIN - 256, y, useMask=True
        )

        gc = wx.GraphicsContext.Create(dc)
        gc.SetPen(wx.TRANSPARENT_PEN)
        cx0 = self.MARGIN + 256 + self.GAP / 2
        cy = self.content_size.height / 2
        for i, colour in enumerate(self.DOT_COLOURS):
            t = math.sin(self.phase - i * (2 * math.pi / 3)) * 0.5 + 0.5
            fill = _pulse_colour(colour, t)
            cx = cx0 + (i - 1) * self.DOT_SPACING
            gc.SetBrush(wx.Brush(fill))
            gc.DrawEllipse(cx - self.DOT_RADIUS, cy - self.DOT_RADIUS, self.DOT_RADIUS * 2, self.DOT_RADIUS * 2)

        dc.SelectObject(wx.NullBitmap)
        return bmp

    def _on_paint(self, _event):
        dc = wx.BufferedPaintDC(self)
        dc.DrawBitmap(self._render(), 0, 0)

    def _on_tick(self, _event):
        self.phase += 0.18
        self.Refresh()

    def _on_finish(self, _event):
        self.anim_timer.Stop()
        self._on_done()
        self.Destroy()


class MainFrame(wx.Frame):
    DEFAULT_BM3_DIR = "fichier bm3"
    DEFAULT_OUT_DIR = "fichier bma"
    DEFAULT_ROLES_PATH = "roles.xlsx"

    def __init__(self):
        super().__init__(None, title="BMA Generator")
        self._set_icon()

        self.products = []  # liste de Bm3Product, dans l'ordre des lignes de la grille
        self.dynamic_headers = []  # colonnes bm3 affichees a partir de la colonne FROZEN_COLS
        self.original_bm3_dir = None  # dossier bm3 source, fixe au chargement

        panel = wx.Panel(self)
        root_sizer = wx.BoxSizer(wx.VERTICAL)

        root_sizer.Add(self._build_paths_panel(panel), 0, wx.EXPAND | wx.ALL, 8)
        root_sizer.Add(self._build_grid(panel), 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        root_sizer.Add(self._build_actions_panel(panel), 0, wx.EXPAND | wx.ALL, 8)
        root_sizer.Add(self._build_log_panel(panel), 0, wx.EXPAND | wx.ALL, 8)

        panel.SetSizer(root_sizer)
        self._fit_to_screen()

        self._try_autoload()

    def _set_icon(self):
        """Loads assets/logo.svg as the window icon, rendered at several
        sizes (title bar, taskbar, Alt+Tab) so Windows never has to
        upscale/downscale a single bitmap and crop or blur it. Fails
        silently if wx.svg is unavailable or the file is missing: wx's
        default icon is used instead."""
        try:
            bundle = wx.IconBundle()
            for size in (16, 24, 32, 48, 256):
                icon = wx.Icon()
                icon.CopyFromBitmap(wx.Bitmap(_svg_to_image(LOGO_PATH, size)))
                bundle.AddIcon(icon)
            self.SetIcons(bundle)
        except Exception:
            pass

    def _fit_to_screen(self):
        """Taille la fenetre en fonction de l'ecran disponible (hors barre
        des taches) au lieu d'une taille fixe, pour ne jamais depasser
        l'ecran sur un affichage plus petit ; puis la centre."""
        area = wx.Display(0).GetClientArea()
        width = min(1200, area.width - 40)
        height = min(700, area.height - 40)
        self.SetSize((width, height))
        self.SetPosition((area.x + (area.width - width) // 2, area.y + (area.height - height) // 2))

    # ---------------------------------------------------------------- UI --

    def _build_paths_panel(self, parent):
        box = wx.StaticBoxSizer(wx.VERTICAL, parent, "Paths")
        static_box = box.GetStaticBox()
        row = wx.BoxSizer(wx.HORIZONTAL)

        self.bm3_dir_ctrl = wx.TextCtrl(static_box, value=self.DEFAULT_BM3_DIR)
        self.out_dir_ctrl = wx.TextCtrl(static_box, value=self.DEFAULT_OUT_DIR)
        self.roles_path_ctrl = wx.TextCtrl(static_box, value=self.DEFAULT_ROLES_PATH)
        # Default values keep the project's actual folder names (French);
        # only the interface labels/messages are translated to English.

        self._path_field(static_box, row, wx.ART_FOLDER_OPEN, "Load Bm3 Folder", self.bm3_dir_ctrl, is_dir=True)
        self._path_field(static_box, row, wx.ART_FILE_SAVE_AS, "Save Bma Folder", self.out_dir_ctrl, is_dir=True)
        self._path_field(static_box, row, wx.ART_REPORT_VIEW, "Load Roles File", self.roles_path_ctrl, is_dir=False)

        box.Add(row, 1, wx.EXPAND | wx.ALL, 6)
        return box

    def _path_field(self, parent, sizer, art_id, tooltip, ctrl, is_dir):
        """Icon (with tooltip) + text field + Browse button, all on one
        line, all centered on the same vertical axis (icon, field and
        button previously used inconsistent alignment flags, which made the
        icon look cut off / misaligned against the row's content)."""
        icon = wx.StaticBitmap(parent, bitmap=_icon(art_id))
        icon.SetToolTip(tooltip)
        sizer.Add(icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        sizer.Add(ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        def browse(_event):
            if is_dir:
                dlg = wx.DirDialog(self, "Choose a folder", defaultPath=ctrl.GetValue() or "")
            else:
                dlg = wx.FileDialog(
                    self, "Choose an Excel file", wildcard="Excel (*.xlsx)|*.xlsx",
                    defaultDir=str(Path(ctrl.GetValue()).parent) if ctrl.GetValue() else "",
                )
            if dlg.ShowModal() == wx.ID_OK:
                ctrl.SetValue(dlg.GetPath())
            dlg.Destroy()

        button = wx.Button(parent, label="Browse...")
        button.Bind(wx.EVT_BUTTON, browse)
        sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)

    def _build_grid(self, parent):
        self.grid = wx.grid.Grid(parent)
        self.grid.CreateGrid(0, 0)
        self.grid.SetRowLabelSize(0)
        self.grid.DisableDragRowSize()
        # Headers left-aligned, like the cell values.
        self.grid.SetColLabelAlignment(wx.ALIGN_LEFT, wx.ALIGN_CENTRE)
        return self.grid

    def _icon_button(self, parent, art_id, label, handler):
        button = wx.Button(parent, label=f" {label}")
        button.SetBitmap(_icon(art_id), wx.LEFT)
        button.Bind(wx.EVT_BUTTON, lambda e: handler())
        return button

    def _build_actions_panel(self, parent):
        box = wx.BoxSizer(wx.VERTICAL)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(self._icon_button(parent, wx.ART_FILE_OPEN, "Load products", self.load_products), 0, wx.RIGHT, 6)
        row1.Add(self._icon_button(parent, wx.ART_FILE_SAVE, "Save roles", self.save_roles), 0, wx.RIGHT, 6)
        row1.Add(self._icon_button(parent, wx.ART_GO_FORWARD, "Generate .BMA", self.run_generate), 0, wx.RIGHT, 6)
        row1.Add(self._icon_button(parent, wx.ART_UNDO, "Reset", self.reset), 0, wx.RIGHT, 6)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(wx.StaticText(parent, label="ID prefix:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.id_prefix_ctrl = wx.TextCtrl(parent, size=(120, -1))
        row2.Add(self.id_prefix_ctrl, 0, wx.RIGHT, 6)
        btn_prefix = wx.Button(parent, label="Add prefix")
        btn_prefix.Bind(wx.EVT_BUTTON, lambda e: self.apply_prefix())
        row2.Add(btn_prefix, 0, wx.RIGHT, 16)

        row2.Add(wx.StaticText(parent, label="Brand:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.brand_override_ctrl = wx.TextCtrl(parent, size=(180, -1))
        row2.Add(self.brand_override_ctrl, 0, wx.RIGHT, 6)
        btn_brand = wx.Button(parent, label="Add brand")
        btn_brand.Bind(wx.EVT_BUTTON, lambda e: self.apply_brand())
        row2.Add(btn_brand, 0)

        box.Add(row1, 0, wx.BOTTOM, 6)
        box.Add(row2, 0)
        return box

    def _build_log_panel(self, parent):
        box = wx.StaticBoxSizer(wx.VERTICAL, parent, "Log")
        self.log_ctrl = wx.TextCtrl(
            box.GetStaticBox(), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2, size=(-1, 120)
        )
        box.Add(self.log_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        return box

    def log_line(self, text, kind="default"):
        self.log_ctrl.SetDefaultStyle(wx.TextAttr(LOG_COLOURS.get(kind, LOG_COLOURS["default"])))
        self.log_ctrl.AppendText(text + "\n")

    # ------------------------------------------------------------ helpers --

    @property
    def bm3_dir(self):
        return self.bm3_dir_ctrl.GetValue()

    @bm3_dir.setter
    def bm3_dir(self, value):
        self.bm3_dir_ctrl.SetValue(value)

    @property
    def out_dir(self):
        return self.out_dir_ctrl.GetValue()

    @out_dir.setter
    def out_dir(self, value):
        self.out_dir_ctrl.SetValue(value)

    @property
    def roles_path(self):
        return self.roles_path_ctrl.GetValue()

    @roles_path.setter
    def roles_path(self, value):
        self.roles_path_ctrl.SetValue(value)

    @property
    def id_prefix(self):
        return self.id_prefix_ctrl.GetValue()

    @id_prefix.setter
    def id_prefix(self, value):
        self.id_prefix_ctrl.SetValue(value)

    @property
    def brand_override(self):
        return self.brand_override_ctrl.GetValue()

    @brand_override.setter
    def brand_override(self, value):
        self.brand_override_ctrl.SetValue(value)

    def _col_index(self, header_name):
        if header_name in self.dynamic_headers:
            return FROZEN_COLS + self.dynamic_headers.index(header_name)
        return None

    def _product_id_col(self):
        return self._col_index("Product ID")

    def _brand_col(self):
        return self._col_index("Brand")

    def _error(self, message, title="Error"):
        self.log_line(f"ERROR: {message}", "error")
        wx.MessageBox(message, title, wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------ actions --

    def _try_autoload(self):
        try:
            if Path(self.bm3_dir).exists():
                self.load_products()
        except Exception:
            pass

    def reset(self):
        """Clears the loaded products/table and the prefix/Brand fields,
        and restores the path fields to their defaults, so a new bm3
        folder can be picked and generated from a clean slate."""
        self.products = []
        self.original_bm3_dir = None

        self._rebuild_grid_columns([])
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())

        self.bm3_dir = self.DEFAULT_BM3_DIR
        self.out_dir = self.DEFAULT_OUT_DIR
        self.roles_path = self.DEFAULT_ROLES_PATH
        self.id_prefix = ""
        self.brand_override = ""

        self.log_line("Reset: paths, table, prefix and Brand cleared.", "load")

    def _rebuild_grid_columns(self, headers):
        """Rebuilds the whole grid: frozen columns (Role, Reference depth)
        followed by the dynamic bm3 columns (Brand included, editable).
        FreezeTo(0, 2) freezes the first 2 columns; the rest scrolls
        horizontally."""

        self.dynamic_headers = headers
        n_cols = FROZEN_COLS + len(headers)

        if self.grid.GetNumberCols():
            self.grid.DeleteCols(0, self.grid.GetNumberCols())
        self.grid.AppendCols(n_cols)

        self.grid.SetColLabelValue(ROLE_COL, "Role (double-click)")
        self.grid.SetColLabelValue(REF_DEPTH_COL, "Reference depth (chaise longue)")
        self.grid.SetColSize(ROLE_COL, 160)
        self.grid.SetColSize(REF_DEPTH_COL, 200)

        role_attr = wx.grid.GridCellAttr()
        role_attr.SetEditor(wx.grid.GridCellChoiceEditor(ROLE_VALUES, allowOthers=False))
        self.grid.SetColAttr(ROLE_COL, role_attr)

        for i, name in enumerate(headers):
            col = FROZEN_COLS + i
            self.grid.SetColLabelValue(col, name)
            self.grid.SetColSize(col, 160)
            if name != "Brand":
                attr = wx.grid.GridCellAttr()
                attr.SetReadOnly(True)
                self.grid.SetColAttr(col, attr)

        self.grid.FreezeTo(0, FROZEN_COLS)

    def load_products(self):
        try:
            bm3_xlsx = _find_bm3_xlsx(self.bm3_dir)
            self.products = excel_io.read_bm3_products(bm3_xlsx)
        except Exception as exc:
            self._error(f"Unable to read the bm3 folder:\n{exc}")
            return

        self.original_bm3_dir = self.bm3_dir

        saved_roles = {}
        roles_file = Path(self.roles_path)
        if roles_file.exists():
            try:
                saved_roles = excel_io.read_roles(roles_file)
            except Exception:
                saved_roles = {}

        # Same columns as the output Excel (Product ID/Reference/Product
        # Type/Brand always present, even if Brand is missing from the bm3
        # source, plus the bm3's extra columns).
        headers = generator.build_products_header(self.products) if self.products else []
        self._rebuild_grid_columns(headers)

        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        self.grid.AppendRows(len(self.products))

        for row, p in enumerate(self.products):
            saved = saved_roles.get(p.product_id) or {}
            role = saved.get("role") or p.inferred_role or ""
            if role not in ROLE_VALUES:
                role = ""
            ref_depth = saved.get("ref_depth")
            self.grid.SetCellValue(row, ROLE_COL, role)
            self.grid.SetCellValue(row, REF_DEPTH_COL, "" if ref_depth is None else str(ref_depth))
            for i, name in enumerate(self.dynamic_headers):
                if name == "Product ID":
                    value = p.product_id
                elif name == "Brand":
                    value = p.brand
                else:
                    value = p.source_columns.get(name)
                self.grid.SetCellValue(row, FROZEN_COLS + i, "" if value is None else str(value))

        self.log_line(f"{len(self.products)} product(s) loaded from {bm3_xlsx}", "load")
        missing = [
            p.product_id for p in self.products
            if not ((saved_roles.get(p.product_id) or {}).get("role") or p.inferred_role)
        ]
        if missing:
            self.log_line(f"Role needs to be chosen manually for: {', '.join(missing)}", "warning")

    def save_roles(self):
        if not self.products:
            wx.MessageBox("Load the products first (button 1).", "Warning", wx.OK | wx.ICON_WARNING)
            return
        rows = []
        for row, p in enumerate(self.products):
            role = self.grid.GetCellValue(row, ROLE_COL)
            ref_depth_str = self.grid.GetCellValue(row, REF_DEPTH_COL)
            rows.append((p.product_id, p.reference, p.product_type, role, ref_depth_str))
        try:
            excel_io.write_roles_from_rows(rows, self.roles_path)
        except Exception as exc:
            self._error(f"Unable to save the roles:\n{exc}")
            return
        self.log_line(f"Roles saved to {self.roles_path}")

    def apply_brand(self):
        """Writes the Brand field's value into the Brand column of the
        table for every product (or restores the original value if the
        field is empty). This change only takes effect when clicking
        'Generate .BMA': it is not saved before that."""
        if not self.products:
            wx.MessageBox("Load the products first (button 1).", "Warning", wx.OK | wx.ICON_WARNING)
            return
        brand_col = self._brand_col()
        if brand_col is None:
            return

        value = self.brand_override.strip()
        for row, p in enumerate(self.products):
            self.grid.SetCellValue(row, brand_col, value if value else (p.brand or ""))

        if value:
            self.log_line(f"Brand '{value}' applied in the table for {len(self.products)} product(s).", "load")
        else:
            self.log_line("Brand empty: values restored from the bm3 in the table.", "load")

    def apply_prefix(self):
        if not self.products:
            wx.MessageBox("Load the products first (button 1).", "Warning", wx.OK | wx.ICON_WARNING)
            return
        if not self.original_bm3_dir:
            self.original_bm3_dir = self.bm3_dir

        prefix = self.id_prefix.strip()
        pid_col = self._product_id_col()
        for row, p in enumerate(self.products):
            p.apply_prefix(prefix)
            if pid_col is not None:
                self.grid.SetCellValue(row, pid_col, p.product_id)

        if not prefix:
            for p in self.products:
                p.asset_id = p.original_asset_id
            self.bm3_dir = self.original_bm3_dir
            self.log_line("Prefix empty: ID and bm3 folder restored to their original value.", "load")
            return

        source_dir = Path(self.original_bm3_dir)
        safe_prefix = "".join(c if c.isalnum() or c in "-_" else "_" for c in prefix)
        # Dedicated sibling folder, never mixed with the bm3 source folder.
        dest_dir = source_dir.with_name(f"{source_dir.name}_{safe_prefix}")

        def copy_log(msg):
            self.log_line(msg, "warning" if "not found" in msg else "load")

        excel_io.copy_bm3_asset_folders(source_dir, dest_dir, self.products, log=copy_log)
        self.log_line(
            f"Prefix '{prefix}' applied to {len(self.products)} product(s). Assets copied to: {dest_dir}", "load"
        )

        try:
            bm3_xlsx = _find_bm3_xlsx(source_dir)
            id_map = {p.original_asset_id: p.product_id for p in self.products}
            out_path = dest_dir / bm3_xlsx.name
            excel_io.write_bm3_with_prefix(
                bm3_xlsx, out_path, prefix, id_map,
                brand_override=self.brand_override.strip() or None,
            )
            self.log_line(f"Prefixed bm3 Excel written: {out_path}", "load")
        except Exception as exc:
            self._error(
                f"The prefix was applied in memory (generation will use it), "
                f"but exporting the prefixed bm3 Excel failed:\n{exc}"
            )
            return

        self.bm3_dir = str(dest_dir)

    def run_generate(self):
        if not self.products:
            wx.MessageBox("Load the products first (button 1).", "Warning", wx.OK | wx.ICON_WARNING)
            return

        brand_col = self._brand_col()
        roles = {}
        for row, p in enumerate(self.products):
            if brand_col is not None:
                # The Brand shown in the table (via the "Add brand" button,
                # or as loaded from the bm3) is only actually applied here,
                # at generation time.
                p.brand = self.grid.GetCellValue(row, brand_col) or None

            role = self.grid.GetCellValue(row, ROLE_COL)
            if not role:
                continue
            ref_depth_str = self.grid.GetCellValue(row, REF_DEPTH_COL)
            ref_depth = None
            if ref_depth_str:
                try:
                    ref_depth = float(ref_depth_str)
                except ValueError:
                    self._error(
                        f"Invalid reference depth for {p.product_id}: {ref_depth_str!r} "
                        "(must be a number)."
                    )
                    return
            roles[p.product_id] = {"role": role, "ref_depth": ref_depth}

        try:
            bm3_xlsx = _find_bm3_xlsx(self.bm3_dir)
            generated, skipped, rows_products, rows_assets, rows_parameters, warnings, products_header = generator.generate(
                self.products, roles, self.bm3_dir, self.out_dir,
            )
            if rows_products:
                out_xlsx = Path(self.out_dir) / "export-products-bma.xlsx"
                generator.write_output_excel(
                    rows_products, rows_assets, rows_parameters, bm3_xlsx, out_xlsx,
                    products_header=products_header,
                )
        except Exception as exc:
            self._error(f"Generation failed:\n{exc}")
            return

        self.log_line(f"Generated: {', '.join(generated) or '-'}", "generated")
        if skipped:
            self.log_line(f"Skipped (missing role): {', '.join(skipped)}", "warning")
        for warning in warnings:
            self.log_line(f"WARNING: {warning}", "warning")
        wx.MessageBox(
            f"{len(generated)} product(s) generated in {self.out_dir}."
            + (f"\n{len(skipped)} skipped, missing role." if skipped else "")
            + (f"\n{len(warnings)} warning(s), see the log." if warnings else ""),
            "Done", wx.OK | wx.ICON_INFORMATION,
        )


def _start_main_app():
    frame = MainFrame()
    frame.Show()


if __name__ == "__main__":
    app = wx.App()
    SplashScreen(on_done=_start_main_app).Show()
    app.MainLoop()

    app.MainLoop()
