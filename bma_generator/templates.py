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

import re

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
CHAISE_LONGUE_LEFT = "chaise_longue_left"
CHAISE_LONGUE_RIGHT = "chaise_longue_right"
CORNER_LEFT_135 = "corner_left_135"
CORNER_RIGHT_135 = "corner_right_135"

ALL_ROLES = [
    CENTRAL,
    LATERAL_LEFT,
    LATERAL_RIGHT,
    CORNER_LEFT,
    CORNER_RIGHT,
    CORNER_LEFT_135,
    CORNER_RIGHT_135,
    POUF_LATERAL,
    POUF_FRONTAL,
    TABLE_LATERAL,
    TABLE_FRONTAL,
    CHAISE_LONGUE,
    CHAISE_LONGUE_LEFT,
    CHAISE_LONGUE_RIGHT,
]

# Familles "chaise longue" : profondeur typiquement non standard (plus
# grande que les modules ordinaires). Utilise dans generator.py pour NE PAS
# prendre leur profondeur comme reference pour aligner un AUTRE produit -
# sinon une chaise longue pourrait se caler sur le dos d'une autre chaise
# longue voisine au lieu d'un module standard.
CHAISE_LONGUE_ROLES = {CHAISE_LONGUE, CHAISE_LONGUE_LEFT, CHAISE_LONGUE_RIGHT}

# Tout role dont au moins une ancre laterale (gauche/droite, pas les ancres
# "avant"/frontales) doit aligner son dos sur celui du module voisin plutot
# que de rester centree (y=0) : c'est necessaire des que deux modules
# connectes n'ont pas la meme profondeur (cas le plus visible avec une
# chaise longue, mais ca vaut pour n'importe quelle paire de profondeurs
# differentes). Seuls les roles purement frontaux (POUF_FRONTAL,
# TABLE_FRONTAL) n'ont pas d'ancre laterale et restent en dehors, ainsi que
# les angles 135 (ancres inclinees a y=0, copiees telles quelles du .bma de
# reference test_angle_135).
CORNER_135_ROLES = {CORNER_LEFT_135, CORNER_RIGHT_135}
LATERAL_ALIGN_ROLES = {r for r in ALL_ROLES if r not in (POUF_FRONTAL, TABLE_FRONTAL) and r not in CORNER_135_ROLES}

# Modules d'angle 135 : chaque ancre laterale est inclinee de
# ANGLE_135_DEFAULT_DEGREES (valeur du .bma de reference test_angle_135),
# vers les x negatifs pour un angle gauche, positifs pour un angle droit -
# meme convention de signe que l'ancre avant de corner_left/corner_right.
# Modifiable par role dans la feuille Anchors du fichier de roles.
ANGLE_135_DEFAULT_DEGREES = 15
# Decalage des ancres vers l'interieur du module (mm), expose comme
# parametre numerique du .bma (comme offSetModule dans la reference).
OFFSET_PARAM_NAME = "offSetModule"
OFFSET_DEFAULT = 0

# Nom du parametre numerique injecte dans les .BMA "chaise longue" pour
# stocker la profondeur des modules standards auxquels elle se connecte
# (voir generator.find_reference_depth : deduite via les receiveTags,
# ou surchargee manuellement dans le fichier de roles).
REFERENCE_DEPTH_PARAM_NAME = "profondeurModuleAttache"

# Mots-cles reconnus n'importe ou dans la colonne "Reference" du bm3 (pas
# seulement en prefixe exact) pour deduire automatiquement le role : ex.
# "right_module1", "chaiseLongueDroite-12345", "Corner-Left-98" matchent
# tous. Le matching se fait sur la reference nettoyee de toute ponctuation
# (voir infer_role_from_reference), donc "droit" couvre aussi "droite".
_RIGHT_KEYWORDS = ("right", "droit")
_LEFT_KEYWORDS = ("left", "gauche")
_CORNER_KEYWORDS = ("corner", "angle", "coin")
_CHAISE_LONGUE_KEYWORDS = ("chaiselong",)  # couvre chaiselong/chaiselongue/"chaise long(ue)" une fois nettoye
_CENTRAL_KEYWORDS = ("central", "centre")
_POUF_KEYWORDS = ("pouf",)
_TABLE_KEYWORDS = ("table",)
_FRONTAL_KEYWORDS = ("front", "face", "avant")
_LATERAL_KEYWORDS = ("lateral", "latéral", "side", "cote", "côté")
# "135" isole (pas un morceau d'un code plus long comme "213578") : teste
# sur la reference brute, _clean_reference supprimant les chiffres.
_ANGLE_135 = re.compile(r"(?<!\d)135(?!\d)")


def _clean_reference(reference):
    """Reference en minuscules, sans aucune ponctuation/chiffre/espace, pour
    un matching de mots-cles insensible au separateur ('-', '_', ' ', ...)."""
    return re.sub(r"[^a-zàâäéèêëïîôöùûüç]", "", (reference or "").lower())


def infer_role_from_reference(reference):
    """Deduit le role depuis n'importe quel mot-cle present dans la colonne
    Reference du bm3 (pas juste un prefixe exact avant le premier '-').
    Retourne None si aucun mot-cle reconnu ou si le role reste ambigu
    (ex: "pouf"/"table" sans "frontal"/"lateral", qui ont deux variantes)."""

    clean = _clean_reference(reference)
    if not clean:
        return None

    has_right = any(k in clean for k in _RIGHT_KEYWORDS)
    has_left = any(k in clean for k in _LEFT_KEYWORDS)
    has_corner = any(k in clean for k in _CORNER_KEYWORDS)
    has_chaise_longue = any(k in clean for k in _CHAISE_LONGUE_KEYWORDS)
    has_central = any(k in clean for k in _CENTRAL_KEYWORDS)
    has_frontal = any(k in clean for k in _FRONTAL_KEYWORDS)
    has_lateral = any(k in clean for k in _LATERAL_KEYWORDS)

    if has_corner and _ANGLE_135.search(reference):
        if has_right:
            return CORNER_RIGHT_135
        if has_left:
            return CORNER_LEFT_135
    if has_corner and has_right:
        return CORNER_RIGHT
    if has_corner and has_left:
        return CORNER_LEFT
    if has_chaise_longue and has_right:
        return CHAISE_LONGUE_RIGHT
    if has_chaise_longue and has_left:
        return CHAISE_LONGUE_LEFT
    if has_chaise_longue:
        return CHAISE_LONGUE
    for keywords, frontal, lateral in (
        (_POUF_KEYWORDS, POUF_FRONTAL, POUF_LATERAL),
        (_TABLE_KEYWORDS, TABLE_FRONTAL, TABLE_LATERAL),
    ):
        if any(k in clean for k in keywords):
            if has_frontal and not has_lateral:
                return frontal
            if has_lateral and not has_frontal:
                return lateral
            return None
    if has_central:
        return CENTRAL
    if has_right:
        return LATERAL_RIGHT
    if has_left:
        return LATERAL_LEFT
    return None


# Tags des ancres des angles 135 : cote gauche (x negatif) et cote droit
# (x positif) de chaque variante. Une ancre de cote gauche recoit les tags
# "cote droit" des autres modules, et inversement.
_TAGS_135_L = ["Angle135GaucheL", "Angle135DroitL"]
_TAGS_135_R = ["Angle135GaucheR", "Angle135DroitR"]


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


def _lateral_align_relation():
    """Relation Y partagee par toutes les ancres laterales (voir
    LATERAL_ALIGN_ROLES) : decale l'ancre sur l'axe negatif de
    -(profondeur du module voisin * 0.5 - propre profondeur * 0.5) au lieu
    de la laisser au centre (y=0), pour que les DOS des deux modules
    connectes s'alignent meme si leurs profondeurs different. Quand les
    deux profondeurs sont egales, l'expression vaut 0 : comportement
    strictement identique a l'ancien y=0 fixe dans ce cas."""
    return {
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
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["CentralL"],
                ["GaucheTable", "CentralR", "AngleGaucheR", "PoufLatR", "TableBasseR", *_TAGS_135_R, "-DroitTable"],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
            ),
            _anchor(
                ["CentralR"],
                ["DroitTable", "CentralL", "AngleDroitL", "PoufLatL", "TableBasseL", *_TAGS_135_L, "-GaucheTable"],
                {"x": "xPositionAncreDroite", "y": "yPositionAncreLaterale", "z": 0},
            ),
            _anchor(
                ["CentralF"],
                ["PoufFrontL", "TableBasseF"],
                {"x": 0, "y": "yPositionAncreAvant", "z": 0},
            ),
        ]
        return relations, anchors

    if role == LATERAL_LEFT:
        # Piece d'extremite "gauche" (ex: reference contenant "left"/"gauche") :
        # une seule ancre, du cote OPPOSE au nom (le cote gauche est
        # l'accoudoir/extremite fermee, rien ne s'y connecte). L'ancre se
        # trouve donc a droite.
        relations = [
            _rel_half_width(
                "xPositionAncreDroite",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["GaucheTable"],
                ["CentralL", "AngleDroitL", "AngleGaucheF", *_TAGS_135_L],
                {"x": "xPositionAncreDroite", "y": "yPositionAncreLaterale", "z": 0},
            ),
        ]
        return relations, anchors

    if role == LATERAL_RIGHT:
        # Symetrique de LATERAL_LEFT : une seule ancre, a gauche (opposee au
        # nom "right"/"droit").
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["DroitTable"],
                ["CentralR", "AngleGaucheR", "AngleDroitF", *_TAGS_135_R],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
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
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["AngleGaucheR"],
                ["CentralL", "AngleDroitL", "DroitTable", "PoufLatL", "TableBasseL", *_TAGS_135_L],
                {"x": "xPositionAncreDroit", "y": "yPositionAncreLaterale", "z": 0},
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
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["AngleDroitL"],
                ["CentralR", "AngleGaucheR", "GaucheTable", "PoufLatR", "TableBasseR", *_TAGS_135_R],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
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
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["PoufLatL"],
                ["CentralR", "AngleGaucheR", "AngleDroitF", *_TAGS_135_R],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
            ),
            _anchor(
                ["PoufLatR"],
                ["CentralL", "AngleDroitL", "AngleGaucheF", *_TAGS_135_L],
                {"x": "xPositionAncreDroit", "y": "yPositionAncreLaterale", "z": 0},
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
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["TableBasseL"],
                ["CentralR", "AngleGaucheR", *_TAGS_135_R],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
            ),
            _anchor(
                ["TableBasseR"],
                ["CentralL", "AngleDroitL", *_TAGS_135_L],
                {"x": "xPositionAncreDroit", "y": "yPositionAncreLaterale", "z": 0},
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
        # Comme "central" (2 ancres laterales symetriques gauche/droite).
        # L'alignement des dos (voir _lateral_align_relation) est ce qui
        # rend ce role necessaire en premier lieu : la chaise longue est
        # typiquement plus profonde que les modules standards auxquels elle
        # se connecte.
        relations = [
            _rel_half_width(
                "xPositionAncreGauche",
                "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
            ),
            _rel_half_width(
                "xPositionAncreDroite",
                "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
            ),
            _lateral_align_relation(),
        ]
        anchors = [
            _anchor(
                ["CentralL"],
                ["GaucheTable", "CentralR", "AngleGaucheR", "PoufLatR", "TableBasseR", *_TAGS_135_R, "-DroitTable"],
                {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
            ),
            _anchor(
                ["CentralR"],
                ["DroitTable", "CentralL", "AngleDroitL", "PoufLatL", "TableBasseL", *_TAGS_135_L, "-GaucheTable"],
                {"x": "xPositionAncreDroite", "y": "yPositionAncreLaterale", "z": 0},
            ),
        ]
        return relations, anchors

    if role in (CHAISE_LONGUE_LEFT, CHAISE_LONGUE_RIGHT):
        # Comme LATERAL_LEFT/LATERAL_RIGHT (une seule ancre, du cote OPPOSE
        # au nom), avec le meme alignement des dos que CHAISE_LONGUE.
        if role == CHAISE_LONGUE_LEFT:
            relations = [
                _rel_half_width(
                    "xPositionAncreDroite",
                    "(monModule!== null) && (MonModule!== null) ? MonModule.width/2:0",
                ),
                _lateral_align_relation(),
            ]
            anchors = [
                _anchor(
                    ["GaucheTable"],
                    ["CentralL", "AngleDroitL", "AngleGaucheF", *_TAGS_135_L],
                    {"x": "xPositionAncreDroite", "y": "yPositionAncreLaterale", "z": 0},
                ),
            ]
        else:
            relations = [
                _rel_half_width(
                    "xPositionAncreGauche",
                    "(monModule!== null) && (MonModule!== null) ? -MonModule.width/2:0",
                ),
                _lateral_align_relation(),
            ]
            anchors = [
                _anchor(
                    ["DroitTable"],
                    ["CentralR", "AngleGaucheR", "AngleDroitF", *_TAGS_135_R],
                    {"x": "xPositionAncreGauche", "y": "yPositionAncreLaterale", "z": 0},
                ),
            ]
        return relations, anchors

    if role in CORNER_135_ROLES:
        return _corner_135_definition(role, ANGLE_135_DEFAULT_DEGREES)

    raise ValueError(f"Role inconnu: {role!r}. Roles valides: {ALL_ROLES}")


def _rel_offset_width(name, expression):
    return {
        "symbolDependencies": ["monModule", OFFSET_PARAM_NAME],
        "componentDependencies": [
            {"propertyName": "width", "componentName": "MonModule", "component": "MonModule"}
        ],
        "type": "number",
        "name": name,
        "expression": expression,
    }


def _rel_constant(name, symbols, expression):
    return {"symbolDependencies": symbols, "componentDependencies": [], "type": "number",
            "name": name, "expression": expression}


def _corner_135_definition(role, degrees):
    """Angle 135, reproduit du .bma de reference test_angle_135 : deux
    ancres laterales (droite puis gauche), rentrees de offSetModule depuis
    les bords, inclinees de +/- `degrees` (cos/sin calcules par le
    configurateur). Angle gauche : angle negatif (ancres tournees vers les x
    negatifs, comme l'ancre avant de corner_left) ; angle droit : positif.
    Les noms de relations (dont la faute "xOrintation") sont ceux de la
    reference."""

    sign = -1 if role == CORNER_LEFT_135 else 1
    side = "Gauche" if role == CORNER_LEFT_135 else "Droit"
    relations = [
        _rel_offset_width(
            "xPositionAncreGauche",
            f"(monModule!== null) && (MonModule!== null) ? -(MonModule.width/2) +{OFFSET_PARAM_NAME}:0",
        ),
        _rel_offset_width(
            "xPositionAncreDroit",
            f"(monModule!== null) && (MonModule!== null) ? (MonModule.width/2)-{OFFSET_PARAM_NAME} :0",
        ),
        _rel_constant("angleRad", ["Pi"], f"{_format_number(sign * degrees)}*Pi/180"),
        _rel_constant("yOrientation", ["angleRad"], "Math.cos(angleRad)"),
        _rel_constant("xOrintationRight", ["angleRad"], "Math.sin(angleRad)"),
        _rel_constant("xOrintationLeft", ["angleRad"], "-Math.sin(angleRad)"),
    ]
    anchors = [
        _anchor(
            [f"Angle135{side}R"],
            ["CentralL", "AngleDroitL", "DroitTable", "PoufLatL", "TableBasseL", *_TAGS_135_L],
            {"x": "xPositionAncreDroit", "y": 0, "z": 0},
            direction_y={"x": "xOrintationRight", "y": "yOrientation", "z": 0},
        ),
        _anchor(
            [f"Angle135{side}L"],
            ["CentralR", "AngleGaucheR", "GaucheTable", "PoufLatR", "TableBasseR", *_TAGS_135_R],
            {"x": "xPositionAncreGauche", "y": 0, "z": 0},
            direction_y={"x": "xOrintationLeft", "y": "yOrientation", "z": 0},
        ),
    ]
    return relations, anchors


def _format_number(value):
    return str(int(value)) if float(value).is_integer() else str(value)


class AnchorOverrides:
    """Personnalisation des ancres lue depuis la feuille Anchors du fichier
    de roles : `anchors` {(role, numero d'ancre 1..n): (tags, receive_tags)}
    remplace les tags/receiveTags par defaut, `angles` {role: degres}
    remplace l'inclinaison des roles d'angle 135. La geometrie (positions,
    relations) n'est jamais modifiable ici : seulement le vocabulaire de
    tags, les compatibilites et l'angle."""

    def __init__(self, anchors=None, angles=None):
        self.anchors = anchors or {}
        self.angles = angles or {}


def role_definition(role, overrides=None):
    """build_role_definition + application des personnalisations eventuelles."""
    if overrides is not None and role in CORNER_135_ROLES and role in overrides.angles:
        relations, anchors = _corner_135_definition(role, overrides.angles[role])
    else:
        relations, anchors = build_role_definition(role)
    if overrides is not None:
        for index, anchor in enumerate(anchors, start=1):
            custom = overrides.anchors.get((role, index))
            if custom:
                anchor["tags"], anchor["receiveTags"] = list(custom[0]), list(custom[1])
    return relations, anchors


def anchor_angle(role, overrides=None):
    """Inclinaison (degres) des ancres d'un role d'angle 135, sinon None."""
    if role not in CORNER_135_ROLES:
        return None
    if overrides is not None and role in overrides.angles:
        return overrides.angles[role]
    return ANGLE_135_DEFAULT_DEGREES


def exposed_tags(role, overrides=None):
    """Tags qu'expose (offre) ce role sur ses ancres, tous confondus."""
    _, anchors = role_definition(role, overrides)
    tags = set()
    for anchor in anchors:
        tags.update(anchor["tags"])
    return tags


def receive_tags(role, overrides=None):
    """Tags que ce role peut recevoir (accepter) sur ses ancres, tous confondus."""
    _, anchors = role_definition(role, overrides)
    tags = set()
    for anchor in anchors:
        tags.update(anchor["receiveTags"])
    return tags
