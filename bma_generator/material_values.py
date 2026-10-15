"""Valeurs proposees pour les parametres materiau d'un produit (parametres
de type "Product", ex. structureColor) : quels materiaux d'un export de
materiaux (voir bm3mat_builder) le client peut choisir, et lequel est
applique par defaut.

Representation partagee : {parameter_id: (default_id, [ids])}. Dans les
feuilles Parameters (bm3 comme bma), elle s'ecrit comme dans les exports
HomeByMe de reference : Default = un ID, Values = les IDs joints par "+",
Allow any value = "false".
"""

from pathlib import Path

import openpyxl

SEPARATOR = "+"
ALLOW_ANY_VALUE = "false"


def cells(material_values, param_id):
    """(Default, Values) a ecrire pour ce parametre, ou None si aucun
    materiau n'a ete choisi pour lui."""
    default, ids = (material_values or {}).get(param_id, (None, []))
    if not ids:
        return None
    return default or ids[0], SEPARATOR.join(ids)


def describe(material_values):
    """Resume lisible pour le journal, ex. 'structureColor = a+b (default a)'."""
    return "; ".join(
        f"{param} = {SEPARATOR.join(ids)} (default {default})"
        for param, (default, ids) in sorted((material_values or {}).items()) if ids
    ) or "none"


def parse(specs):
    """Version ligne de commande : ['structureColor=a+b+c', ...] ->
    {'structureColor': ('a', ['a', 'b', 'c'])}. Le premier ID est la valeur
    par defaut."""
    result = {}
    for spec in specs or []:
        param, sep, ids_text = spec.partition("=")
        ids = [i.strip() for i in ids_text.split(SEPARATOR) if i.strip()]
        if not sep or not param.strip() or not ids:
            raise ValueError(f"Invalid material values {spec!r} (expected PARAM=ID+ID+...)")
        result[param.strip()] = (ids[0], ids)
    return result


def read_material_export(path):
    """Materiaux d'un export de materiaux : liste de (Product ID, Reference,
    Name) dans l'ordre du fichier. `path` : le dossier de l'export ou son
    .xlsx. Si la colonne Category ID existe, seules les lignes 'Material'
    sont gardees."""
    path = Path(path)
    if path.is_dir():
        candidates = sorted(p for p in path.glob("*.xlsx") if not p.name.startswith("~$"))
        if not candidates:
            raise FileNotFoundError(f"No .xlsx file found in {path}")
        path = candidates[0]

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb["Products"].iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, [])]
        col = {name: i for i, name in enumerate(header)}
        if "Product ID" not in col:
            raise ValueError(f"No 'Product ID' column in the Products sheet of {path}")

        def get(row, name):
            i = col.get(name)
            value = row[i] if i is not None and i < len(row) else None
            return "" if value is None else str(value).strip()

        materials = []
        for row in rows:
            pid = get(row, "Product ID")
            if not pid:
                continue
            if "Category ID" in col and get(row, "Category ID").lower() != "material":
                continue
            materials.append((pid, get(row, "Reference"), get(row, "Name (en-GB)")))
    finally:
        wb.close()
    return materials
