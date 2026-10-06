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

from bma_generator import bm3_builder, excel_io, generator
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


def _dialog_start_dir(value):
    """Absolute, existing folder to open a file/folder dialog on: the path
    itself, or its closest existing parent. The native dialog rejects
    relative or missing paths (and logs an error) instead of resolving
    them."""
    path = Path(value or ".").resolve()
    while not path.is_dir() and path != path.parent:
        path = path.parent
    return str(path)


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
    SVGs declare a native size of 256x256 for that reason.

    Loaded from bytes, not CreateFromFile: nanosvg opens the path as a
    narrow string, which fails as soon as it contains a non-ASCII character
    (e.g. a Windows user folder named "André")."""
    import wx.svg
    svg = wx.svg.SVGimage.CreateFromBytes(Path(path).read_bytes())
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
                dlg = wx.DirDialog(self, "Choose a folder", defaultPath=_dialog_start_dir(ctrl.GetValue()))
            else:
                dlg = wx.FileDialog(
                    self, "Choose an Excel file", wildcard="Excel (*.xlsx)|*.xlsx",
                    defaultDir=_dialog_start_dir(Path(ctrl.GetValue() or ".").parent),
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
        row1.Add(self._icon_button(parent, wx.ART_FILE_SAVE_AS, "Download roles Excel...", self.download_roles),
                 0, wx.RIGHT, 6)
        row1.Add(self._icon_button(parent, wx.ART_GO_FORWARD, "Generate .BMA", self.run_generate), 0, wx.RIGHT, 6)
        row1.Add(self._icon_button(parent, wx.ART_UNDO, "Reset", self.reset), 0, wx.RIGHT, 6)
        row1.AddSpacer(16)
        row1.Add(self._icon_button(parent, wx.ART_NEW, "Build bm3 from 3D files...", self.open_bm3_builder), 0)

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

    def _role_rows(self):
        rows = []
        for row, p in enumerate(self.products):
            role = self.grid.GetCellValue(row, ROLE_COL)
            ref_depth_str = self.grid.GetCellValue(row, REF_DEPTH_COL)
            rows.append((p.product_id, p.reference, p.product_type, role, ref_depth_str))
        return rows

    def save_roles(self):
        if not self.products:
            wx.MessageBox("Load the products first (button 1).", "Warning", wx.OK | wx.ICON_WARNING)
            return
        try:
            excel_io.write_roles_from_rows(self._role_rows(), self.roles_path)
        except Exception as exc:
            self._error(f"Unable to save the roles:\n{exc}")
            return
        self.log_line(f"Roles saved to {self.roles_path}")

    def download_roles(self):
        """Saves the roles Excel (Roles sheet = current table, Anchors sheet
        = anchor tags / compatibilities / 135 angle, editable in Excel) to a
        chosen location, then uses that file as the roles file: edits made
        to its Anchors sheet are picked up by the next 'Generate .BMA'."""
        current = Path(self.roles_path or self.DEFAULT_ROLES_PATH)
        dlg = wx.FileDialog(
            self, "Save the roles Excel", defaultDir=_dialog_start_dir(current.parent),
            defaultFile=current.name, wildcard="Excel (*.xlsx)|*.xlsx",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return
        target = dlg.GetPath()
        dlg.Destroy()
        try:
            # Keep the anchors already customised in the current roles file.
            overrides = excel_io.read_anchor_overrides(self.roles_path) if self.roles_path else None
            # No product loaded: keep the roles already in the file.
            rows = self._role_rows() or excel_io.read_roles_rows(self.roles_path)
            excel_io.write_roles_from_rows(rows, target, anchor_overrides=overrides)
        except Exception as exc:
            self._error(f"Unable to write the roles Excel:\n{exc}")
            return
        self.roles_path = target
        self.log_line(
            f"Roles Excel written: {target} (edit its 'Anchors' sheet to rename anchor tags or change "
            "compatibilities; it is now the roles file used for generation).", "load"
        )

    def apply_brand(self):
        """Writes the Brand field's value into the Brand column of the
        table for every product (or restores the original value if the
        field is empty), AND writes a copy of the current bm3 Excel with
        that Brand applied (sibling file, original never touched) - unlike
        the rest of the Brand handling, this file write happens right away,
        not only at 'Generate .BMA'. No asset folders need copying here
        (Brand changes no ID or path), so this is just the one Excel file,
        unlike 'Add prefix' which also copies the .BM3 model folders."""
        if not self.products:
            wx.MessageBox("Load the products first (button 1).", "Warning", wx.OK | wx.ICON_WARNING)
            return
        brand_col = self._brand_col()
        if brand_col is None:
            return

        value = self.brand_override.strip()
        for row, p in enumerate(self.products):
            self.grid.SetCellValue(row, brand_col, value if value else (p.brand or ""))

        if not value:
            self.log_line("Brand empty: values restored from the bm3 in the table.", "load")
            return

        self.log_line(f"Brand '{value}' applied in the table for {len(self.products)} product(s).", "load")

        try:
            bm3_xlsx = _find_bm3_xlsx(self.bm3_dir)
            safe_brand = "".join(c if c.isalnum() or c in "-_" else "_" for c in value)
            out_path = Path(self.bm3_dir).parent / f"{bm3_xlsx.stem}_{safe_brand}{bm3_xlsx.suffix}"
            excel_io.write_bm3_with_brand(bm3_xlsx, out_path, value)
            self.log_line(f"bm3 copy with Brand written: {out_path}", "load")
        except Exception as exc:
            self._error(f"Brand applied in the table, but writing the bm3 copy failed:\n{exc}")

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
            # Anchor tags / compatibilities as edited in the roles Excel's
            # "Anchors" sheet (None -> built-in defaults).
            anchor_overrides = excel_io.read_anchor_overrides(self.roles_path) if self.roles_path else None
        except Exception as exc:
            self._error(f"Invalid 'Anchors' sheet in {self.roles_path}:\n{exc}")
            return
        if anchor_overrides is not None:
            self.log_line(f"Anchor tags and compatibilities read from {self.roles_path} (Anchors sheet).", "load")

        try:
            bm3_xlsx = _find_bm3_xlsx(self.bm3_dir)
            generated, skipped, rows_products, rows_assets, rows_parameters, warnings, products_header = generator.generate(
                self.products, roles, self.bm3_dir, self.out_dir, anchor_overrides=anchor_overrides,
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

    def open_bm3_builder(self):
        """Opens the "3D files -> bm3 export" window. If it writes an
        export, offers to load it right away as the current bm3 folder."""
        dlg = Bm3BuilderDialog(self, self.roles_path)
        dlg.ShowModal()
        written_dir = dlg.written_dir
        dlg.Destroy()
        if written_dir is None:
            return
        if wx.MessageBox(
            f"bm3 export written to:\n{written_dir}\n\nLoad it now as the bm3 folder?",
            "bm3 export", wx.YES_NO | wx.ICON_QUESTION,
        ) == wx.YES:
            self.bm3_dir = str(written_dir)
            self.load_products()


class ProductTypeEditor(wx.grid.GridCellEditor):
    """Grid cell editor for Product Type: a text field with a filtered list
    under the cell. Typing any part of a type ("sofa", "381") lists the
    matching entries; Up/Down move in the list, Enter or a click picks the
    highlighted entry, Escape cancels. Only values from
    bm3_builder.PRODUCT_TYPES (or empty) can be committed."""

    MAX_POPUP_HEIGHT = 220

    def __init__(self):
        super().__init__()
        self._start = ""
        self._value = ""
        self._grid = None

    def Create(self, parent, id, evt_handler):
        self._text = wx.TextCtrl(parent, id, "")
        self.SetControl(self._text)
        if evt_handler:
            self._text.PushEventHandler(evt_handler)
        self._text.Bind(wx.EVT_TEXT, self._on_text)
        self._text.Bind(wx.EVT_KEY_DOWN, self._on_key)

        self._popup = wx.PopupWindow(parent)
        self._list = wx.ListBox(self._popup, style=wx.LB_SINGLE)
        self._list.Bind(wx.EVT_LEFT_DOWN, self._on_list_click)

    def SetSize(self, rect):
        self._text.SetSize(rect.x, rect.y, rect.width + 2, rect.height + 2, wx.SIZE_ALLOW_MINUS_ONE)

    def Show(self, show, attr=None):
        super().Show(show, attr)
        if not show:
            self._popup.Hide()

    def BeginEdit(self, row, col, grid):
        self._grid = grid
        self._start = grid.GetTable().GetValue(row, col)
        if not self._text.GetValue():
            # Not pre-filled by StartingKey: start from the current value
            # but list every type, like an opened drop-down.
            self._text.ChangeValue(self._start)
            self._refresh_list("")
            if self._start in bm3_builder.PRODUCT_TYPES:
                self._select(bm3_builder.PRODUCT_TYPES.index(self._start))
        self._text.SetInsertionPointEnd()
        self._text.SelectAll()
        self._text.SetFocus()

    def StartingKey(self, event):
        key = event.GetUnicodeKey()
        if key and key >= 32:
            self._text.SetValue(chr(key))  # triggers _on_text -> filtered list
            self._text.SetInsertionPointEnd()
        else:
            event.Skip()

    def EndEdit(self, row, col, grid, oldval):
        text = self._text.GetValue().strip()
        picked = self._list.GetStringSelection() if self._popup.IsShown() else ""
        self._popup.Hide()
        self._text.ChangeValue("")
        if not text:
            value = ""
        elif text in bm3_builder.PRODUCT_TYPES:
            value = text
        else:
            value = picked or bm3_builder.resolve_product_type(text)
        if value is None or value == oldval:
            if value is None:
                wx.Bell()
            return None
        self._value = value
        return value

    def ApplyEdit(self, row, col, grid):
        grid.GetTable().SetValue(row, col, self._value)

    def Reset(self):
        self._popup.Hide()
        self._text.ChangeValue(self._start)

    def Clone(self):
        return ProductTypeEditor()

    # -- filtered list --

    def _refresh_list(self, text):
        matches = bm3_builder.search_product_types(text)
        self._list.Set(matches)
        if not matches:
            self._popup.Hide()
            return
        self._select(0)
        width = max(self._text.GetSize().width, 320)
        height = min(self.MAX_POPUP_HEIGHT, self._list.GetCharHeight() * (len(matches) + 1) + 6)
        self._list.SetSize(width, height)
        self._popup.SetSize(width, height)
        self._popup.Position(self._text.ClientToScreen((0, 0)), (0, self._text.GetSize().height))
        self._popup.Show()

    def _select(self, index):
        self._list.SetSelection(index)
        self._list.EnsureVisible(index)

    def _on_text(self, event):
        self._refresh_list(self._text.GetValue())
        event.Skip()

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_DOWN, wx.WXK_UP, wx.WXK_PAGEDOWN, wx.WXK_PAGEUP) and self._list.GetCount():
            if not self._popup.IsShown():
                self._popup.Show()
            step = {wx.WXK_DOWN: 1, wx.WXK_UP: -1, wx.WXK_PAGEDOWN: 10, wx.WXK_PAGEUP: -10}[key]
            current = self._list.GetSelection()
            self._select(min(max(0, (0 if current == wx.NOT_FOUND else current) + step), self._list.GetCount() - 1))
            return
        event.Skip()

    def _on_list_click(self, event):
        # Not skipped on purpose: the list must not take the focus, which
        # would end the edit before the clicked entry is committed.
        index = self._list.HitTest(event.GetPosition())
        if index != wx.NOT_FOUND:
            self._select(index)
            self._text.ChangeValue(self._list.GetString(index))
            if self._grid:
                wx.CallAfter(self._grid.DisableCellEditControl)


class Bm3BuilderDialog(wx.Dialog):
    """Builds a bm3 export (one folder per product + export-products-bm3.xlsx)
    from a flat folder of .BM3 files. Dimensions and materials come from the
    3D files but stay editable; Reference/Brand are typed in, Product Type is
    picked from the program's fixed list (bm3_builder.PRODUCT_TYPES), and the
    role is inferred from the Reference unless set by hand. Cells support
    Ctrl+C / Ctrl+V (also from/to Excel) and Delete. All file logic lives in
    bma_generator.bm3_builder."""

    DEFAULT_SRC_DIR = "test_bm3"

    COLUMNS = [
        # (header, width, editable)
        ("Product ID", 110, False),
        ("Reference", 220, True),
        ("Role (auto / manual)", 150, True),
        ("Product Type", 220, True),
        ("Brand", 140, True),
        ("Width", 80, True),
        ("Depth", 80, True),
        ("Height", 80, True),
        ("Materials", 130, True),
        ("3D files", 80, False),
        ("Thumbnail", 100, False),
    ]
    COL = {name: i for i, (name, _w, _e) in enumerate(COLUMNS)}
    ROLE = "Role (auto / manual)"
    DIMENSION_COLS = {"Width": "width", "Depth": "depth", "Height": "height"}

    def __init__(self, parent, roles_path):
        super().__init__(parent, title="Build bm3 from 3D files",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        self.products = []
        self.roles_path = roles_path
        self.written_dir = None  # set once an export has been written
        self._manual_roles = set()  # rows whose role was set by hand
        self._measured = {}  # (row, col) -> (displayed text, exact value)

        src_default = self.DEFAULT_SRC_DIR if Path(self.DEFAULT_SRC_DIR).is_dir() else ""
        self.src_ctrl = wx.TextCtrl(self, value=src_default)
        self.out_ctrl = wx.TextCtrl(self, value=self._default_out_dir(src_default))

        paths = wx.FlexGridSizer(cols=3, vgap=4, hgap=6)
        paths.AddGrowableCol(1)
        self._path_row(paths, "3D files folder:", self.src_ctrl)
        self._path_row(paths, "Output bm3 folder:", self.out_ctrl)

        self.grid = wx.grid.Grid(self)
        self.grid.CreateGrid(0, len(self.COLUMNS))
        self.grid.SetRowLabelSize(0)
        self.grid.SetColLabelAlignment(wx.ALIGN_LEFT, wx.ALIGN_CENTRE)
        for i, (name, width, editable) in enumerate(self.COLUMNS):
            self.grid.SetColLabelValue(i, name)
            self.grid.SetColSize(i, width)
            attr = wx.grid.GridCellAttr()
            if not editable:
                attr.SetReadOnly(True)
                attr.SetBackgroundColour(wx.Colour(245, 245, 245))
            elif name == self.ROLE:
                attr.SetEditor(wx.grid.GridCellChoiceEditor(ROLE_VALUES, allowOthers=False))
            elif name == "Product Type":
                attr.SetEditor(ProductTypeEditor())
            self.grid.SetColAttr(i, attr)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGING, self._on_cell_changing)
        self.grid.Bind(wx.grid.EVT_GRID_CELL_CHANGED, self._on_cell_changed)
        self.grid.GetGridWindow().Bind(wx.EVT_KEY_DOWN, self._on_grid_key)

        bulk = wx.BoxSizer(wx.HORIZONTAL)
        bulk.Add(wx.StaticText(self, label="Product Type for all:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.type_all_ctrl = wx.ComboBox(self, choices=bm3_builder.PRODUCT_TYPES, size=(240, -1))
        bulk.Add(self.type_all_ctrl, 0, wx.RIGHT, 4)
        btn = wx.Button(self, label="Apply")
        btn.Bind(wx.EVT_BUTTON, lambda e: self._apply_to_all("Product Type", self.type_all_ctrl.GetValue()))
        bulk.Add(btn, 0, wx.RIGHT, 16)
        bulk.Add(wx.StaticText(self, label="Brand for all:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.brand_all_ctrl = wx.TextCtrl(self, size=(180, -1))
        bulk.Add(self.brand_all_ctrl, 0, wx.RIGHT, 4)
        btn = wx.Button(self, label="Apply")
        btn.Bind(wx.EVT_BUTTON, lambda e: self._apply_to_all("Brand", self.brand_all_ctrl.GetValue()))
        bulk.Add(btn, 0, wx.RIGHT, 16)
        bulk.Add(wx.StaticText(self, label="Ctrl+C / Ctrl+V to copy-paste cells, Delete to clear."),
                 0, wx.ALIGN_CENTER_VERTICAL)

        self.log_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2, size=(-1, 90))

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        btn_scan = wx.Button(self, label=" Scan 3D files")
        btn_scan.SetBitmap(_icon(wx.ART_FIND), wx.LEFT)
        btn_scan.Bind(wx.EVT_BUTTON, lambda e: self.scan())
        btn_write = wx.Button(self, label=" Write bm3 export")
        btn_write.SetBitmap(_icon(wx.ART_FILE_SAVE), wx.LEFT)
        btn_write.Bind(wx.EVT_BUTTON, lambda e: self.write())
        btn_close = wx.Button(self, wx.ID_CLOSE, label="Close")
        btn_close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
        buttons.Add(btn_scan, 0, wx.RIGHT, 6)
        buttons.Add(btn_write, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer()
        buttons.Add(btn_close, 0)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(paths, 0, wx.EXPAND | wx.ALL, 8)
        root.Add(self.grid, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        root.Add(bulk, 0, wx.ALL, 8)
        root.Add(self.log_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        root.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(root)

        area = wx.Display(0).GetClientArea()
        self.SetSize((min(1300, area.width - 80), min(620, area.height - 80)))
        self.CentreOnParent()

    @staticmethod
    def _default_out_dir(src_dir):
        # "fichier bm3_<source>" : sibling of the default bm3 folder, already
        # covered by .gitignore.
        return f"{MainFrame.DEFAULT_BM3_DIR}_{Path(src_dir).name}" if src_dir else ""

    def _path_row(self, sizer, label, ctrl):
        sizer.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(ctrl, 1, wx.EXPAND)

        def browse(_event):
            dlg = wx.DirDialog(self, "Choose a folder", defaultPath=_dialog_start_dir(ctrl.GetValue()))
            if dlg.ShowModal() == wx.ID_OK:
                ctrl.SetValue(dlg.GetPath())
                if ctrl is self.src_ctrl:
                    self.out_ctrl.SetValue(self._default_out_dir(dlg.GetPath()))
            dlg.Destroy()

        button = wx.Button(self, label="Browse...")
        button.Bind(wx.EVT_BUTTON, browse)
        sizer.Add(button, 0)

    def log_line(self, text, kind="default"):
        self.log_ctrl.SetDefaultStyle(wx.TextAttr(LOG_COLOURS.get(kind, LOG_COLOURS["default"])))
        self.log_ctrl.AppendText(text + "\n")

    def _error(self, message):
        self.log_line(f"ERROR: {message}", "error")
        wx.MessageBox(message, "Error", wx.OK | wx.ICON_ERROR, self)

    # ------------------------------------------------------- cell values --

    def _col_name(self, col):
        return self.COLUMNS[col][0]

    def _is_editable(self, col):
        return self.COLUMNS[col][2]

    def _normalize(self, col, text):
        """Validated value to store in the cell; raises ValueError with a
        user-facing message if `text` is not acceptable for this column."""
        name = self._col_name(col)
        text = (text or "").strip()
        if name == "Product Type":
            if not text:
                return ""
            value = bm3_builder.resolve_product_type(text)
            if value is None:
                matches = bm3_builder.search_product_types(text)
                raise ValueError(
                    f"'{text}' matches {len(matches)} Product Types"
                    + (f" ({', '.join(matches[:5])}{', ...' if len(matches) > 5 else ''})" if matches else "")
                )
            return value
        if name == self.ROLE:
            if text and text not in tpl.ALL_ROLES:
                raise ValueError(f"'{text}' is not a valid role ({', '.join(tpl.ALL_ROLES)})")
            return text
        if name in self.DIMENSION_COLS:
            try:
                if float(text.replace(",", ".")) <= 0:
                    raise ValueError
            except ValueError:
                raise ValueError(f"{name} must be a positive number, got '{text}'") from None
            return text
        if name == "Materials":
            return ", ".join(part.strip() for part in text.split(",") if part.strip())
        return text

    def _after_change(self, row, col):
        """Keeps the role in sync: a Reference change re-infers it unless it
        was set by hand; setting the role by hand pins it (clearing it
        hands it back to inference on the next Reference change)."""
        name = self._col_name(col)
        if name == "Reference" and row not in self._manual_roles:
            role = tpl.infer_role_from_reference(self.grid.GetCellValue(row, col))
            self.grid.SetCellValue(row, self.COL[self.ROLE], role or "")
        elif name == self.ROLE:
            if self.grid.GetCellValue(row, col):
                self._manual_roles.add(row)
            else:
                self._manual_roles.discard(row)

    def _set_cell(self, row, col, text):
        """Validates and writes one cell (paste, clear, apply to all).
        Returns an error message, or None on success."""
        if not self._is_editable(col):
            return None
        try:
            value = self._normalize(col, text)
        except ValueError as exc:
            return f"{self.grid.GetCellValue(row, self.COL['Product ID'])} / {self._col_name(col)}: {exc}"
        self.grid.SetCellValue(row, col, value)
        self._after_change(row, col)
        return None

    def _on_cell_changing(self, event):
        try:
            self._normalize(event.GetCol(), event.GetString())
        except ValueError as exc:
            self.log_line(f"WARNING: {exc}", "warning")
            wx.Bell()
            event.Veto()
            return
        event.Skip()

    def _on_cell_changed(self, event):
        row, col = event.GetRow(), event.GetCol()
        value = self._normalize(col, self.grid.GetCellValue(row, col))
        if value != self.grid.GetCellValue(row, col):
            self.grid.SetCellValue(row, col, value)
        self._after_change(row, col)
        event.Skip()

    def _apply_to_all(self, col_name, value):
        col = self.COL[col_name]
        errors = [e for e in (self._set_cell(row, col, value) for row in range(self.grid.GetNumberRows())) if e]
        if errors:
            self.log_line(f"WARNING: {errors[0]}", "warning")
            return
        self.log_line(f"{col_name} '{self.grid.GetCellValue(0, col) if self.products else value}' "
                      f"applied to {self.grid.GetNumberRows()} product(s).", "load")

    # ------------------------------------------------------ copy / paste --

    def _selected_cells(self):
        # GetSelectedBlocks() isn't iterable in wxPython 4.3: use the older
        # per-kind selection accessors instead.
        g = self.grid
        cells = set(map(tuple, g.GetSelectedCells()))
        for (top, left), (bottom, right) in zip(g.GetSelectionBlockTopLeft(), g.GetSelectionBlockBottomRight()):
            cells.update((r, c) for r in range(top, bottom + 1) for c in range(left, right + 1))
        for row in g.GetSelectedRows():
            cells.update((row, c) for c in range(g.GetNumberCols()))
        for col in g.GetSelectedCols():
            cells.update((r, col) for r in range(g.GetNumberRows()))
        if not cells and self.grid.GetNumberRows():
            cells.add((self.grid.GetGridCursorRow(), self.grid.GetGridCursorCol()))
        return sorted(cells)

    def _on_grid_key(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and key == ord("C"):
            self.copy_cells()
        elif event.ControlDown() and key == ord("V"):
            self.paste_cells()
        elif key in (wx.WXK_DELETE, wx.WXK_BACK) and not event.HasAnyModifiers():
            self._report(self._set_cell(row, col, "") for row, col in self._selected_cells())
        else:
            event.Skip()

    def copy_cells(self):
        cells = self._selected_cells()
        if not cells:
            return
        rows = sorted({r for r, _ in cells})
        cols = sorted({c for _, c in cells})
        text = "\n".join(
            "\t".join(self.grid.GetCellValue(r, c) if (r, c) in cells else "" for c in cols) for r in rows
        )
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            # Render the data now (MSW otherwise defers it to the data
            # object, and a paste right after - or in Excel - gets nothing).
            wx.TheClipboard.Flush()
            wx.TheClipboard.Close()

    def paste_cells(self):
        data = wx.TextDataObject()
        if not wx.TheClipboard.Open():
            return
        ok = wx.TheClipboard.GetData(data)
        wx.TheClipboard.Close()
        if not ok:
            return
        lines = data.GetText().replace("\r\n", "\n").rstrip("\n").split("\n")
        block = [line.split("\t") for line in lines]
        cells = self._selected_cells()
        if not cells:
            return

        if len(block) == 1 and len(block[0]) == 1:
            # One value: fills every selected cell (like Excel).
            targets = [(row, col, block[0][0]) for row, col in cells]
        else:
            top, left = cells[0]
            targets = [
                (top + i, left + j, value)
                for i, line in enumerate(block) for j, value in enumerate(line)
                if top + i < self.grid.GetNumberRows() and left + j < self.grid.GetNumberCols()
            ]
        self._report(self._set_cell(row, col, value) for row, col, value in targets)

    def _report(self, errors):
        for error in filter(None, list(errors)):
            self.log_line(f"WARNING: {error}", "warning")

    # ----------------------------------------------------------- actions --

    def scan(self):
        warnings = []
        try:
            self.products = bm3_builder.scan_3d_folder(self.src_ctrl.GetValue(), log=warnings.append)
        except Exception as exc:
            self._error(f"Unable to read the 3D files:\n{exc}")
            return

        self._manual_roles.clear()
        self._measured.clear()
        if self.grid.GetNumberRows():
            self.grid.DeleteRows(0, self.grid.GetNumberRows())
        self.grid.AppendRows(len(self.products))
        for row, p in enumerate(self.products):
            values = {
                "Product ID": p.product_id,
                "Materials": ", ".join(p.publications),
                "3D files": ", ".join(lod for lod in bm3_builder.LODS if lod in p.files),
                "Thumbnail": p.thumbnail.name if p.thumbnail else "-",
            }
            for name, attr in self.DIMENSION_COLS.items():
                exact = getattr(p, attr)
                values[name] = f"{exact:.2f}"
                self._measured[(row, self.COL[name])] = (values[name], exact)
            for name, value in values.items():
                self.grid.SetCellValue(row, self.COL[name], value)

        self.log_line(f"{len(self.products)} product(s) read from {self.src_ctrl.GetValue()}.", "load")
        for warning in warnings:
            self.log_line(f"WARNING: {warning}", "warning")

    def _collect(self):
        """Copies the grid values onto self.products. Dimensions left as
        displayed keep their full measured precision; edited ones use the
        typed value."""
        for row, p in enumerate(self.products):
            cell = lambda name: self.grid.GetCellValue(row, self.COL[name]).strip()
            p.reference = cell("Reference")
            p.role = cell(self.ROLE)
            p.product_type = cell("Product Type")
            p.brand = cell("Brand")
            p.publications = [m.strip() for m in cell("Materials").split(",") if m.strip()]
            for name, attr in self.DIMENSION_COLS.items():
                text = cell(name)
                shown, exact = self._measured[(row, self.COL[name])]
                setattr(p, attr, exact if text == shown else float(text.replace(",", ".")))

    def write(self):
        if not self.products:
            wx.MessageBox("Scan the 3D files first.", "Warning", wx.OK | wx.ICON_WARNING, self)
            return
        if self.grid.IsCellEditControlEnabled():
            self.grid.SaveEditControlValue()
            self.grid.HideCellEditControl()
        self._collect()

        incomplete = [
            f"{p.product_id} ({', '.join(n for n, v in (('Reference', p.reference), ('Role', p.role), ('Product Type', p.product_type)) if not v)})"
            for p in self.products if not (p.reference and p.role and p.product_type)
        ]
        if incomplete and wx.MessageBox(
            "Missing values:\n" + "\n".join(incomplete) + "\n\nWrite the export anyway?",
            "Incomplete", wx.YES_NO | wx.ICON_WARNING, self,
        ) != wx.YES:
            return

        if not self.out_ctrl.GetValue().strip():
            self._error("Choose an output bm3 folder.")
            return
        out_dir = Path(self.out_ctrl.GetValue())
        if (out_dir / bm3_builder.BM3_XLSX_NAME).exists() and wx.MessageBox(
            f"{out_dir / bm3_builder.BM3_XLSX_NAME} already exists. Overwrite it (and the copied 3D files)?",
            "Overwrite", wx.YES_NO | wx.ICON_WARNING, self,
        ) != wx.YES:
            return

        try:
            out_xlsx = bm3_builder.write_bm3_export(self.products, out_dir, log=lambda m: self.log_line(m, "load"))
            # The role is not part of the bm3 Excel: it goes to the roles
            # file the main window reads when loading this export.
            excel_io.update_roles_file(
                self.roles_path,
                [(p.product_id, p.reference, p.product_type, p.role) for p in self.products],
            )
        except Exception as exc:
            self._error(f"Writing the bm3 export failed:\n{exc}")
            return

        self.log_line(f"bm3 Excel written: {out_xlsx}; roles saved to {self.roles_path}", "generated")
        self.written_dir = out_dir
        self.EndModal(wx.ID_OK)


def _start_main_app():
    frame = MainFrame()
    frame.Show()


if __name__ == "__main__":
    app = wx.App()
    try:
        # The splash screen renders assets/*.svg via wx.svg, which loads a
        # native extension (_nanosvg). On some machines a security policy
        # (AppLocker/WDAC/EDR) blocks that DLL from loading at all, which
        # would otherwise crash the app before it even opens. Skip the
        # splash and go straight to the main window in that case, rather
        # than let a purely cosmetic feature take down the whole app.
        SplashScreen(on_done=_start_main_app).Show()
    except Exception as exc:
        print(f"Splash screen unavailable ({exc}); starting main window directly.")
        _start_main_app()
    app.MainLoop()

    app.MainLoop()
