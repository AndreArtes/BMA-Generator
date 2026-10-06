"""Lecture des fichiers 3D .BM3 (export "ByMe C++ exporter").

Un .BM3 est une archive zip contenant :
- manifest.json : graphe de noeuds (matrices 4x4 column-major, comme glTF),
  geometries (vertexLayout + vertexBuffers + boundingBox locale), buffers,
  et header (unit "mm", upAxis "Z") ;
- binary.bin : les buffers bruts (sommets interleaves, indices, images).

Les dimensions sont la boite englobante de tous les sommets, exprimes dans
le repere monde du fichier (unite/axe du header) : width = etendue X,
depth = etendue Y, height = etendue Z (upAxis "Z"). Les sommets eux-memes
sont relus (et pas seulement la boundingBox du manifest, arrondie a 6
chiffres) pour retrouver exactement les valeurs d'un export bm3 de reference.
"""

import json
import struct
import zipfile

_FORMAT_SIZES = {"FLOAT": 4}


class Bm3Model:
    def __init__(self, width, depth, height, publications):
        self.width = width
        self.depth = depth
        self.height = height
        # Noms des parametres materiau publies par les mailles (ex.
        # "structureColor"), dans l'ordre d'apparition, sans doublon.
        self.publications = publications


def _mat_mul(a, b):
    """Produit de deux matrices 4x4 column-major (listes de 16 floats)."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out


_IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _geometry_points(manifest, binary, geometry):
    """Positions locales (x, y, z) de la geometrie. Retombe sur les 8 coins
    de sa boundingBox si le format des sommets n'est pas gere."""

    layout = manifest["vertexLayouts"][geometry["vertexLayout"]]
    for buffer_slot, attributes in enumerate(layout):
        if any(a.get("format") not in _FORMAT_SIZES for a in attributes):
            break
        stride = sum(_FORMAT_SIZES[a["format"]] * a["dimension"] for a in attributes)
        offset = 0
        for a in attributes:
            if a["attribute"] == "POSITION" and a["dimension"] == 3:
                buf = manifest["buffers"][geometry["vertexBuffers"][buffer_slot]]
                start = buf.get("byteOffset", 0)
                data = binary[start:start + buf["byteLength"]]
                return [struct.unpack_from("<3f", data, i + offset)
                        for i in range(0, len(data) - stride + 1, stride)]
            offset += _FORMAT_SIZES[a["format"]] * a["dimension"]

    box = geometry["boundingBox"]
    lo, hi = box["min"], box["max"]
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def read_bm3_model(path):
    """Lit un fichier .BM3 et retourne un Bm3Model (dimensions en unite du
    fichier, normalement des mm). Leve ValueError si le fichier ne contient
    aucune geometrie."""

    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        binary = z.read(manifest["binaries"][0]["uri"]) if manifest.get("binaries") else b""

    nodes = manifest["nodes"]
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    publications = []

    stack = [(manifest.get("root", 0), _IDENTITY)]
    while stack:
        index, parent = stack.pop()
        node = nodes[index]
        world = _mat_mul(parent, node.get("matrix") or _IDENTITY)
        stack.extend((child, world) for child in node.get("children", []))

        publication = node.get("publication")
        if publication and publication not in publications:
            publications.append(publication)

        for g in node.get("geometries", []):
            for x, y, z in _geometry_points(manifest, binary, manifest["geometries"][g]):
                p = [world[row] * x + world[4 + row] * y + world[8 + row] * z + world[12 + row]
                     for row in range(3)]
                for i in range(3):
                    lo[i] = min(lo[i], p[i])
                    hi[i] = max(hi[i], p[i])

    if lo[0] == float("inf"):
        raise ValueError(f"{path}: aucune geometrie dans le fichier .BM3")

    # Le parcours en pile inverse l'ordre des freres : on retrie les
    # publications selon leur position dans la liste des noeuds.
    publications.sort(key=lambda name: next(i for i, n in enumerate(nodes) if n.get("publication") == name))

    up = manifest.get("header", {}).get("upAxis", "Z").upper()
    size = [hi[i] - lo[i] for i in range(3)]
    if up == "Y":
        width, height, depth = size
    else:
        width, depth, height = size
    return Bm3Model(width, depth, height, publications)
