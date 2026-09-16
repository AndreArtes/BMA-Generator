"""
Bibliotheque de templates d'ancrage (relations + anchors) par role geometrique.

Ces templates ont ete extraits des 9 fichiers .BMA d'exemple (EdrienA..I).
Ils encodent la logique de connexion physique entre modules (quel cote se
connecte a quel cote) : c'est une connaissance metier qui n'est pas deductible
du seul export Excel bm3, elle doit donc etre choisie explicitement pour
chaque produit via la colonne "Role" du fichier de roles.

Regle generale (rappelee par l'utilisateur) :
- Un produit "central" ou "lateral" a un cote gauche et un cote droit.
- Le cote gauche d'un produit ne peut recevoir que le cote droit d'un autre
  produit (et inversement). C'est ce qu'encodent les listes receiveTags
  ci-dessous.

Ajouter une nouvelle famille de meubles (nouveau vocabulaire de tags) demande
d'ajouter un nouveau role ici.
"""

CENTRAL = "central"
LATERAL_LEFT = "lateral_left"
LATERAL_RIGHT = "lateral_right"
CORNER_LEFT = "corner_left"
CORNER_RIGHT = "corner_right"
POUF_LATERAL = "pouf_lateral"
POUF_FRONTAL = "pouf_frontal"
TABLE_LATERAL = "table_lateral"
TABLE_FRONTAL = "table_frontal"
CHAISE_LONGUE = "chaise_longue"

ALL_ROLES = [
    CENTRAL,
    LATERAL_LEFT,
    LATERAL_RIGHT,
    CORNER_LEFT,
    CORNER_RIGHT,
    POUF_LATERAL,
    POUF_FRONTAL,
    TABLE_LATERAL,
    TABLE_FRONTAL,
    CHAISE_LONGUE,
]

# Nom du parametre numerique injecte dans les .BMA "chaise longue" pour
# stocker la profondeur des modules standards auxquels elle se connecte
# (voir generator.find_reference_depth : deduite via les receiveTags,
# ou surchargee manuellement dans le fichier de roles).
REFERENCE_DEPTH_PARAM_NAME = "profondeurModuleAttache"

# Role qui peut etre deduit sans ambiguite du prefixe de la colonne
# "Reference" du fichier bm3 (avant le premier "-").
REFERENCE_PREFIX_TO_ROLE = {
    "central": CENTRAL,
    "left": LATERAL_LEFT,
    "right": LATERAL_RIGHT,
    "corner left": CORNER_LEFT,
    "corner right": CORNER_RIGHT,
    "chaiselong": CHAISE_LONGUE,
    "chaise long": CHAISE_LONGUE,
    "chaise longue": CHAISE_LONGUE,
    # "pouf" et "table" sont ambigus (2 variantes possibles) -> pas de mapping ici.
}


def _rel_half_width(name, expr_true):
    return {
        "symbolDependencies": ["monModule"],
        "componentDependencies": [
            {
                "propertyName": "width",
                "componentName": "MonModule",
                "component": "MonModule",
            }
        ],
        "type": "number",
        "name": name,
        "expression": expr_true,
    }


def _rel_half_depth(name, expr_true):
    return {
        "symbolDependencies": ["monModule"],
        "componentDependencies": [
            {
                "propertyName": "depth",
                "componentName": "MonModule",
                "component": "MonModule",
            }
        ],
        "type": "number",
        "name": name,
        "expression": expr_true,
    }


def _anchor(tags, receive_tags, position, direction_y=None, direction_z=None, activated=True):
    anchor = {
        "tags": tags,
        "receiveTags": receive_tags,
    }
    if activated is not None:
        anchor["activated"] = activated
    anchor.update(
        {
            "position": position,
            "directionY": direction_y or {"x": 0, "y": 1, "z": 0},
            "directionZ": direction_z or {"x": 0, "y": 0, "z": 1},
            "availableSpace": {"x": 0, "y": 0, "z": 0},
            "type": "AnchorPoint",
        }
    )
    return anchor


def build_role_definition(role):
    """Retourne (relations, anchors) pour le role donne (sans uuid, ajoutes a la generation)."""

    if role == CENTRAL:
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreDroite",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
            _rel_half_depth(
                "yPositionAncreAvant",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.depth/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["CentralL"],
                ["GaucheTable", "CentralR", "AngleGaucheR", "PoufLatR", "TableBasseR", "-DroitTable"],
                {"x": "xPositionAncreGauche", "y": 0, "z": 0},
            ),
            _anchor(
                ["CentralR"],
                ["DroitTable", "CentralL", "AngleDroitL", "PoufLatL", "TableBasseL", "-GaucheTable"],
                {"x": "xPositionAncreDroite", "y": 0, "z": 0},
            ),
            _anchor(
                ["CentralF"],
                ["PoufFrontL", "TableBasseF"],
                {"x": 0, "y": "yPositionAncreAvant", "z": 0},
            ),
        ]
        return relations, anchors

    if role == LATERAL_LEFT:
        relations = [
            _rel_half_width(
                "xPositionAncreDroite",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["GaucheTable"],
                ["CentralL", "AngleDroitL", "AngleGaucheF"],
                {"x": "xPositionAncreDroite", "y": 0, "z": 0},
            ),
            _anchor(
                ["-GaucheTable"],
                ["CentralR"],
                {"x": "xPositionAncreGauche", "y": 0, "z": 0},
                activated=None,
            ),
        ]
        return relations, anchors

    if role == LATERAL_RIGHT:
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreDroit",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["DroitTable"],
                ["CentralR", "AngleGaucheR", "AngleDroitF"],
                {"x": "xPositionAncreGauche", "y": 0, "z": 0},
            ),
            _anchor(
                ["-DroitTable"],
                ["CentralL"],
                {"x": "xPositionAncreDroit", "y": 0, "z": 0},
                activated=None,
            ),
        ]
        return relations, anchors

    if role == CORNER_LEFT:
        relations = [
            _rel_half_width(
                "xPositionAncreDroit",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
            _rel_half_depth(
                "yPositionAncreAvant",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.depth/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["AngleGaucheR"],
                ["CentralL", "AngleDroitL", "DroitTable", "PoufLatL", "TableBasseL"],
                {"x": "xPositionAncreDroit", "y": 0, "z": 0},
            ),
            _anchor(
                ["AngleGaucheF"],
                ["AngleDroitF", "CentralR", "GaucheTable"],
                {"x": 0, "y": "yPositionAncreAvant", "z": 0},
                direction_y={"x": -1, "y": 0, "z": 0},
            ),
        ]
        return relations, anchors

    if role == CORNER_RIGHT:
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_depth(
                "yPositionAncreAvant",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.depth/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["AngleDroitL"],
                ["CentralR", "AngleGaucheR", "GaucheTable", "PoufLatR", "TableBasseR"],
                {"x": "xPositionAncreGauche", "y": 0, "z": 0},
            ),
            _anchor(
                ["AngleDroitF"],
                ["AngleGaucheF", "CentralL", "DroitTable"],
                {"x": 0, "y": "yPositionAncreAvant", "z": 0},
                direction_y={"x": 1, "y": 0, "z": 0},
            ),
        ]
        return relations, anchors

    if role == POUF_LATERAL:
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreDroit",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["PoufLatL"],
                ["CentralR", "AngleGaucheR", "AngleDroitF"],
                {"x": "xPositionAncreGauche", "y": 0, "z": 0},
            ),
            _anchor(
                ["PoufLatR"],
                ["CentralL", "AngleDroitL", "AngleGaucheF"],
                {"x": "xPositionAncreDroit", "y": 0, "z": 0},
            ),
        ]
        return relations, anchors

    if role == POUF_FRONTAL:
        relations = [
            _rel_half_depth(
                "yPositionAncreProche",
                "(monModule!== null) && (MonModule!== null) ? MonModule.depth/2:0",
            ),
            _rel_half_depth(
                "yPositionAncreLoin",
                "(monModule!== null) && (MonModule!== null) ? MonModule.depth/1:0",
            ),
        ]
        anchors = [
            _anchor(
                ["PoufFrontL"],
                ["CentralF"],
                {"x": 0, "y": "yPositionAncreLoin", "z": 0},
                activated=None,
            ),
        ]
        return relations, anchors

    if role == TABLE_LATERAL:
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreDroit",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
        ]
        anchors = [
            _anchor(
                ["TableBasseL"],
                ["CentralR", "AngleGaucheR"],
                {"x": "xPositionAncreGauche", "y": 0, "z": 0},
            ),
            _anchor(
                ["TableBasseR"],
                ["CentralL", "AngleDroitL"],
                {"x": "xPositionAncreDroit", "y": 0, "z": 0},
            ),
        ]
        return relations, anchors

    if role == TABLE_FRONTAL:
        relations = [
            _rel_half_width(
                "xPositionAncreArriere",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/1:0",
            ),
        ]
        anchors = [
            _anchor(
                ["TableBasseF"],
                ["CentralF"],
                {"x": "xPositionAncreArriere", "y": 0, "z": 0},
                direction_y={"x": 1, "y": 0, "z": 0},
            ),
        ]
        return relations, anchors

    if role == CHAISE_LONGUE:
        # Comme "central" (2 ancres laterales symetriques gauche/droite),
        # mais la chaise longue est plus profonde que les modules standards
        # auxquels elle se connecte : pour aligner les dos (pas les
        # devants), l'ancre est decalee en Y sur l'axe negatif de
        # -(profondeur du module attache * 0.5 - propre profondeur * 0.5) au
        # lieu d'etre au centre (y=0).
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreDroite",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
            {
                "symbolDependencies": ["monModule", REFERENCE_DEPTH_PARAM_NAME],
                "componentDependencies": [
                    {
                        "propertyName": "depth",
                        "componentName": "MonModule",
                        "component": "MonModule",
                    }
                ],
                "type": "number",
                "name": "yPositionAncreLaterale",
                "expression": (
                    "(monModule!== null) && (MonModule!== null) ? "
                    f"-({REFERENCE_DEPTH_PARAM_NAME}*0.5 - MonModule.depth*0.5):0"
                ),
            },
        ]
        anchors = [
            _anchor(
                ["CentralL"],
                ["GaucheTable", "CentralR", "AngleGaucheR", "PoufLatR", "TableBasseR", "-DroitTable"],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
            ),
            _anchor(
                ["CentralR"],
                ["DroitTable", "CentralL", "AngleDroitL", "PoufLatL", "TableBasseL", "-GaucheTable"],
                {"x": "xPositionAncreDroite", "y": "yPositionAncreLaterale", "z": 0},
            ),
        ]
        return relations, anchors

    raise ValueError(f"Role inconnu: {role!r}. Roles valides: {ALL_ROLES}")


def exposed_tags(role):
    """Tags qu'expose (offre) ce role sur ses ancres, tous confondus."""
    _, anchors = build_role_definition(role)
    tags = set()
    for anchor in anchors:
        tags.update(anchor["tags"])
    return tags


def receive_tags(role):
    """Tags que ce role peut recevoir (accepter) sur ses ancres, tous confondus."""
    _, anchors = build_role_definition(role)
    tags = set()
    for anchor in anchors:
        tags.update(anchor["receiveTags"])
    return tags
