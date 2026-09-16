"""Lecture du fichier Excel bm3 et gestion du fichier de roles."""

import shutil
from pathlib import Path

import openpyxl

from . import templates as tpl


def _to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Colonnes de la feuille Parameters du bm3 (sans Delete/Product ID/Parameter
# Definition ID, qui sont regeneres ou ignores a la sortie).
PARAM_FIELDS = [
    "type", "translation_key", "editable", "default", "values",
    "allow_any_value", "value_translation_key", "magnitude", "tags",
    "free_tags", "step", "index_ui", "in_or_out", "visibility", "force",
]
PARAM_FIELD_TO_HEADER = {
    "type": "Type",
    "translation_key": "Parameter Translation Key",
    "editable": "Editable",
    "default": "Default",
    "values": "Values",
    "allow_any_value": "Allow any value",
    "value_translation_key": "Value Translation Key",
    "magnitude": "Magnitude",
    "tags": "Tags",
    "free_tags": "Free Tags",
    "step": "Step",
    "index_ui": "Index UI",
    "in_or_out": "In or Out",
    "visibility": "Visibility",
    "force": "Force",
}


class Bm3Product:
    def __init__(self, product_id, reference, product_type, brand=None,
                 source_columns=None, source_header=None):
        self.product_id = product_id
        # Identifiant d'origine (jamais modifie) : sert de cle stable pour
        # retrouver ce produit independamment d'un prefixe applique ensuite.
        self.original_asset_id = product_id
        # Nom du dossier bm3 a utiliser sur le disque pour cette generation :
        # egal a original_asset_id tant qu'aucun prefixe n'a ete applique et
        # copie ; mis a jour vers product_id une fois la copie physique faite
        # (voir copy_bm3_asset_folders).
        self.asset_id = product_id
        self.reference = reference
        self.product_type = product_type
        self.brand = brand
        self.depth = None
        self.width = None
        self.height = None
        # Liste de dicts {"id": ..., "type": ..., "default": ..., ...} : une
        # entree par parametre bm3 (depth/width/height/structureColor ou
        # sofaColor/etc.), dans l'ordre du fichier source.
        self.parameters = []
        # Photo figee de TOUTES les colonnes de la feuille Products du bm3
        # source (header -> valeur), y compris les colonnes qu'on ne modelise
        # pas explicitement (Name (en-GB), Commercial Description, etc.).
        # Sert a repercuter ces colonnes telles quelles dans l'Excel bma de
        # sortie, et a les afficher dynamiquement dans l'interface.
        self.source_columns = source_columns or {}
        self.source_header = source_header or []

    @property
    def reference_prefix(self):
        if not self.reference or "-" not in self.reference:
            return ""
        return self.reference.split("-", 1)[0].strip().lower()

    @property
    def inferred_role(self):
        return tpl.REFERENCE_PREFIX_TO_ROLE.get(self.reference_prefix)

    def apply_prefix(self, prefix):
        """Renomme product_id en <prefix><id d'origine> (ou restaure l'id
        d'origine si prefix est vide). Le dossier physique n'est pas touche
        ici : voir copy_bm3_asset_folders."""
        self.product_id = f"{prefix}{self.original_asset_id}" if prefix else self.original_asset_id


def read_bm3_products(xlsx_path):
    """Lit les feuilles Products/Assets/Parameters du fichier bm3 et retourne
    une liste de Bm3Product (dans l'ordre d'apparition)."""

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    products = {}
    order = []

    ws = wb["Products"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    brand_idx = None
    for i, name in enumerate(header):
        if name and str(name).strip().lower() == "brand":
            brand_idx = i
            break
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        product_id, reference, product_type = row[0], row[1], row[2]
        brand = row[brand_idx] if brand_idx is not None and brand_idx < len(row) else None
        source_columns = dict(zip(header, row))
        products[product_id] = Bm3Product(
            product_id, reference, product_type, brand,
            source_columns=source_columns, source_header=header,
        )
        order.append(product_id)

    ws = wb["Parameters"]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    for row in rows[1:]:
        if not row or not row[idx["Product ID"]]:
            continue
        pid = row[idx["Product ID"]]
        if pid not in products:
            continue
        param_id = row[idx["Parameter ID"]]
        if not param_id:
            continue
        p = products[pid]
        default = row[idx["Default"]]

        record = {"id": param_id}
        for field, header_name in PARAM_FIELD_TO_HEADER.items():
            record[field] = row[idx[header_name]] if header_name in idx else None
        p.parameters.append(record)

        if param_id == "depth":
            p.depth = _to_float(default)
        elif param_id == "width":
            p.width = _to_float(default)
        elif param_id == "height":
            p.height = _to_float(default)

    return [products[pid] for pid in order]


ROLES_HEADER = [
    "Product ID", "Reference", "Product Type", "Role",
    "Profondeur reference (mm, optionnel - chaise longue uniquement)",
    "Roles valides",
]


def write_roles_template(products, out_path):
    """Genere un fichier xlsx avec une colonne Role pre-remplie quand
    deductible sans ambiguite, et 'A_COMPLETER' sinon."""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Roles"
    ws.append(ROLES_HEADER)
    valid_roles = ", ".join(tpl.ALL_ROLES)
    for p in products:
        role = p.inferred_role or "A_COMPLETER"
        ws.append([p.product_id, p.reference, p.product_type, role, "", valid_roles])
    wb.save(out_path)


def write_roles_from_rows(rows, out_path):
    """Enregistre un fichier de roles a partir de lignes
    (product_id, reference, product_type, role, ref_depth), typiquement
    issues de l'interface graphique. ref_depth peut etre vide/None."""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Roles"
    ws.append(ROLES_HEADER)
    valid_roles = ", ".join(tpl.ALL_ROLES)
    for row in rows:
        product_id, reference, product_type, role = row[0], row[1], row[2], row[3]
        ref_depth = row[4] if len(row) > 4 else ""
        ws.append([product_id, reference, product_type, role, ref_depth, valid_roles])
    wb.save(out_path)


def read_roles(xlsx_path):
    """Retourne un dict {product_id: {"role": role, "ref_depth": float|None}}."""

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Roles"]
    rows = list(ws.iter_rows(values_only=True))
    roles = {}
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        pid, role = row[0], row[3]
        ref_depth = _to_float(row[4]) if len(row) > 4 else None
        roles[pid] = {"role": role, "ref_depth": ref_depth}
    return roles


def write_bm3_with_prefix(source_xlsx, out_path, prefix, id_map, brand_override=None):
    """Copie le fichier bm3 source en renommant la colonne 'Product ID'
    (Products colonne A, Assets colonne A, Parameters colonne B) selon
    id_map ({ancien_id: nouvel_id}), et met a jour les chemins d'assets de
    la feuille Assets pour qu'ils pointent vers les dossiers renommes
    (voir copy_bm3_asset_folders, qui cree physiquement ces dossiers).

    Si brand_override est fourni et qu'une colonne 'Brand' existe dans la
    feuille Products, sa valeur y est ecrite pour chaque produit (la copie
    du bm3 reste alors coherente avec le Brand saisi dans l'interface)."""

    wb = openpyxl.load_workbook(source_xlsx, data_only=True)

    ws = wb["Products"]
    header = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    brand_col = None
    for i, name in enumerate(header):
        if name and str(name).strip().lower() == "brand":
            brand_col = i
            break

    for row in ws.iter_rows(min_row=2):
        cell = row[0]
        if cell.value in id_map:
            cell.value = id_map[cell.value]
        if brand_override and brand_col is not None:
            row[brand_col].value = brand_override

    ws = wb["Assets"]
    for row in ws.iter_rows(min_row=2):
        old_id = row[0].value
        new_id = id_map.get(old_id)
        if new_id is None:
            continue
        row[0].value = new_id
        for cell in row[1:]:
            value = cell.value
            if isinstance(value, str) and value.startswith(f"{old_id}/"):
                cell.value = f"{new_id}/{value[len(old_id) + 1:]}"

    ws = wb["Parameters"]
    for row in ws.iter_rows(min_row=2):
        cell = row[1]
        if cell.value in id_map:
            cell.value = id_map[cell.value]

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def copy_bm3_asset_folders(source_dir, dest_dir, products, log=None):
    """Pour chaque produit dont product_id != original_asset_id (prefixe
    applique), copie le dossier source_dir/original_asset_id vers
    dest_dir/product_id (s'il n'existe pas deja) et met a jour
    product.asset_id en consequence. dest_dir doit etre un dossier distinct
    de source_dir (jamais mélangé avec la source bm3 d'origine) : voir
    gui.apply_prefix, qui utilise un dossier frere nomme
    "<source_dir>_<prefixe>". Pour un produit dont le prefixe a ete vide,
    restaure asset_id vers l'id d'origine (le dossier source n'est jamais
    modifie).

    `log`, si fourni, est appele avec un message texte pour chaque action.
    Ne supprime ni ne deplace jamais de dossier existant (copie uniquement)."""

    source_dir = Path(source_dir)
    dest_dir = Path(dest_dir)

    for p in products:
        if p.product_id == p.original_asset_id:
            p.asset_id = p.original_asset_id
            continue

        src = source_dir / p.original_asset_id
        dst = dest_dir / p.product_id
        if dst.exists():
            p.asset_id = p.product_id
            continue
        if not src.exists():
            if log:
                log(f"{p.original_asset_id}: source folder not found ({src}), copy skipped.")
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        p.asset_id = p.product_id
        if log:
            log(f"Folder copied: {src} -> {dst}")
