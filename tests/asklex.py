"""A small lexicon of generic trade words for the Ask tests, built in the test: no lexicon ships
with the package (the company's own words live in the folder XERSCOPE_LEXICON names)."""

from xerscope.analysis import query

GROUPS = [
    ["mécanique", "mechanical", "meca"],
    ["électricité", "électrique", "electrical", "elec"],
    ["génie civil", "civil", "civils", "gc"],
    ["mise en service", "commissioning", "essais", "mes"],
    ["ingénierie", "études", "engineering"],
    ["achats", "approvisionnement", "procurement", "purchasing"],
    ["construction", "travaux", "chantier"],
    ["fondations", "foundations"],
    ["terrassement", "terrassements", "earthworks"],
    ["tuyauterie", "piping"],
    ["instrumentation", "instrum"],
    ["montage", "installation", "erection"],
    ["livraison", "delivery", "livraisons"],
    ["fabrication", "manufacturing"],
    ["démarrage", "start up", "startup"],
    ["réception", "handover", "transfert"],
    ["gestion de projet", "project management", "pilotage", "direction de projet"],
    ["équipements", "équipement", "equipment"],
    ["structure", "charpente", "steel", "structural"],
    ["voirie", "roads", "routes"],
    ["réseaux", "utilities", "utilités"],
    ["documentation", "documents", "dossier"],
    ["fournisseur", "vendeur", "vendor", "supplier"],
    ["équipe", "crew"],
]
LEXICON = query.lexicon_from_groups(GROUPS)


def write(folder) -> None:
    """The same groups as a lexicon file in ``folder`` (a test's tmp_path), for the CLI and the app."""
    lines = []
    for group in GROUPS:
        lines += ["[[group]]", "words = [" + ", ".join(query.json_quote(w) for w in group) + "]", ""]
    (folder / "generic.toml").write_text("\n".join(lines), encoding="utf-8")
