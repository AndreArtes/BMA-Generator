"""Construction d'un export bm3 (Excel + un dossier par produit) a partir
d'un dossier "plat" de fichiers 3D .BM3.

Dossier source attendu (un ou plusieurs fichiers par produit) :
    <ID>.BM3                      -> modele HQ du produit <ID>
    <ID>_HQ.BM3 / _MQ / _LQ       -> niveaux de detail explicites (optionnels)
    <ID>.jpg / .jpeg / .png       -> miniature du produit (optionnelle)

Sortie (meme structure que "fichier bm3") :
    <out_dir>/export-products-bm3.xlsx   (Products, Assets, Parameters, Utilities)
    <out_dir>/<ID>/HQ-Lod_0_std.BM3      (+ MQ-Lod_1_std / LQ-Lod_2_std si fournis)
    <out_dir>/<ID>/thumbnail-512.jpg     (si une miniature est fournie)

Les fichiers source sont copies, jamais deplaces ni modifies. Reference,
Product Type et Brand ne sont pas dans les fichiers 3D : ils sont saisis
dans l'interface (Product Type choisi parmi la liste fixe de
utilities_data, Brand en texte libre).
"""

import re
import shutil
from pathlib import Path

import openpyxl

from . import utilities_data
from .bm3_reader import read_bm3_model

PRODUCT_TYPES = utilities_data.PRODUCT_TYPES

BM3_XLSX_NAME = "export-products-bm3.xlsx"

LODS = ("HQ", "MQ", "LQ")
LOD_FILE_NAMES = {"HQ": "HQ-Lod_0_std.BM3", "MQ": "MQ-Lod_1_std.BM3", "LQ": "LQ-Lod_2_std.BM3"}
THUMBNAIL_STEM = "thumbnail-512"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")

PRODUCTS_HEADER = ["Product ID", "Reference", "Product Type", "Brand"]
ASSETS_HEADER = ["Product ID", "Model 3D HQ", "Model 3D MQ", "Model 3D LQ", "Model 2D", "Thumbnail", "Media"]
PARAMETERS_HEADER = [
    "Delete", "Product ID", "Parameter Definition ID", "Parameter ID", "Type",
    "Parameter Translation Key", "Editable", "Default", "Values", "Allow any value",
    "Value Translation Key", "Magnitude", "Tags", "Free Tags", "Step", "Index UI",
    "In or Out", "Visibility", "Force",
]
# Ordre des dimensions dans la feuille Parameters, comme dans les exports
# bm3 de reference.
DIMENSIONS = ("depth", "width", "height")

_LOD_SUFFIX = re.compile(r"^(?P<id>.+?)[ _-](?P<lod>HQ|MQ|LQ)$", re.IGNORECASE)


class SourceProduct:
    def __init__(self, product_id):
        self.product_id = product_id
        self.files = {}  # {"HQ"|"MQ"|"LQ": Path}
        self.thumbnail = None  # Path ou None
        self.width = None
        self.depth = None
        self.height = None
        self.publications = []  # parametres materiau (ex. ["structureColor"])
        # Saisis par l'utilisateur avant l'ecriture de l'Excel.
        self.reference = ""
        self.product_type = ""
        self.brand = ""
        # Role d'assemblage (templates.ALL_ROLES) : deduit de la reference
        # ou choisi a la main ; pas dans l'Excel bm3, ecrit dans roles.xlsx.
        self.role = ""

    @property
    def measured_lod(self):
        """Niveau de detail sur lequel les dimensions sont mesurees : le plus
        detaille disponible (un LQ simplifie peut deborder de quelques mm)."""
        return next((lod for lod in LODS if lod in self.files), None)


def scan_3d_folder(src_dir, log=None):
    """Liste les .BM3 du dossier (non recursif), les regroupe par Product ID
    et lit leurs dimensions. Retourne une liste de SourceProduct triee par
    ID. `log`, si fourni, recoit les avertissements (texte)."""

    src_dir = Path(src_dir)
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Folder not found: {src_dir}")

    products = {}
    images = []
    for path in sorted(src_dir.iterdir()):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            images.append(path)
            continue
        if suffix != ".bm3":
            continue
        match = _LOD_SUFFIX.match(path.stem)
        product_id, lod = (match["id"], match["lod"].upper()) if match else (path.stem, "HQ")
        product = products.setdefault(product_id, SourceProduct(product_id))
        if lod in product.files and log:
            log(f"{product_id}: several {lod} files, keeping {product.files[lod].name} (ignored: {path.name}).")
        product.files.setdefault(lod, path)

    unused_images = []
    for image in images:
        product = products.get(image.stem)
        if product and not product.thumbnail:
            product.thumbnail = image
        else:
            unused_images.append(image.name)
    if unused_images and log:
        log(
            f"Image(s) not matched to any product, ignored: {', '.join(unused_images)} "
            "(name a thumbnail <ProductID>.jpg to attach it)."
        )

    for product in products.values():
        lod = product.measured_lod
        if lod is None:
            # Uniquement des MQ/LQ : impossible par construction (HQ par
            # defaut), garde-fou si _LOD_SUFFIX evolue.
            continue
        if lod != "HQ" and log:
            log(f"{product.product_id}: no HQ file, dimensions measured on {lod} (may be slightly off).")
        model = read_bm3_model(product.files[lod])
        product.width, product.depth, product.height = model.width, model.depth, model.height
        product.publications = model.publications

    return [products[pid] for pid in sorted(products)]


def search_product_types(text):
    """Product Types dont le libelle contient `text` (sans tenir compte de
    la casse), dans l'ordre de la liste. Texte vide -> liste complete."""
    needle = text.strip().lower()
    return [t for t in PRODUCT_TYPES if needle in t.lower()]


def resolve_product_type(text):
    """Valeur exacte de la liste correspondant a `text` : la valeur elle-meme
    si elle existe, sinon l'unique Product Type qui la contient. Retourne
    None si aucune correspondance ou si elle est ambigue."""
    if text in PRODUCT_TYPES:
        return text
    matches = search_product_types(text)
    return matches[0] if len(matches) == 1 else None


def _format_dimension(value):
    """Meme ecriture que les exports bm3 de reference : texte, 10 decimales
    au plus (ex. '1000.0001192093')."""
    return repr(round(value, 10))


def write_bm3_export(products, out_dir, log=None):
    """Copie les fichiers 3D/miniatures dans <out_dir>/<ID>/ et ecrit
    <out_dir>/export-products-bm3.xlsx. Retourne le chemin de l'Excel.
    out_dir doit etre distinct du dossier source des fichiers 3D."""

    out_dir = Path(out_dir)
    for product in products:
        for path in list(product.files.values()) + [product.thumbnail]:
            if path is not None and path.parent.resolve() == out_dir.resolve():
                raise ValueError("The output folder must be different from the 3D files folder.")

    out_dir.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws_products = wb.active
    ws_products.title = "Products"
    ws_products.append(PRODUCTS_HEADER)
    ws_assets = wb.create_sheet("Assets")
    ws_assets.append(ASSETS_HEADER)
    ws_params = wb.create_sheet("Parameters")
    ws_params.append(PARAMETERS_HEADER)

    for product in products:
        pid = product.product_id
        product_dir = out_dir / pid
        product_dir.mkdir(exist_ok=True)

        assets = {}
        for lod, src in product.files.items():
            shutil.copy2(src, product_dir / LOD_FILE_NAMES[lod])
            assets[lod] = f"{pid}/{LOD_FILE_NAMES[lod]}"
        thumbnail = ""
        if product.thumbnail:
            name = THUMBNAIL_STEM + product.thumbnail.suffix.lower()
            shutil.copy2(product.thumbnail, product_dir / name)
            thumbnail = f"{pid}/{name}"
        if log:
            log(f"{pid}: {len(product.files)} 3D file(s){' + thumbnail' if thumbnail else ''} copied to {product_dir}")

        ws_products.append([pid, product.reference or "", product.product_type or "", product.brand or ""])
        ws_assets.append([pid, assets.get("HQ", ""), assets.get("MQ", ""), assets.get("LQ", ""), "", thumbnail, None])

        for name in DIMENSIONS:
            value = _format_dimension(getattr(product, name))
            ws_params.append([
                None, pid, None, name, "Real (continuous)", f"param.{name}", "None",
                value, f"< {value} <", "false", "", "Length", "", "", 1, None, "in", False, None,
            ])
        for name in product.publications:
            # Valeur du materiau inconnue a ce stade : choisie dynamiquement
            # par le configurateur.
            ws_params.append([
                None, pid, None, name, "Product", name, "Read & Write",
                "null", "null", "false", "", "", "", "", None, None, "in", False, None,
            ])

    ws_utilities = wb.create_sheet("Utilities")
    ws_utilities.append(utilities_data.HEADER)
    for row in utilities_data.ROWS:
        ws_utilities.append(row)

    for ws in (ws_products, ws_assets, ws_params):
        ws.column_dimensions["A"].width = 20
    for col in ("B", "C", "D"):
        ws_products.column_dimensions[col].width = 25
    ws_utilities.column_dimensions["A"].width = 30

    out_xlsx = out_dir / BM3_XLSX_NAME
    wb.save(out_xlsx)
    return out_xlsx
