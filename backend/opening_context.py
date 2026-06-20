"""Project-authored context for common opening families.

Lichess Opening Explorer provides curated names and ECO codes, but not a
stable description field. These short descriptions are deliberately broad,
non-historical, and limited to practical plans that are safe to pass to the
coaching model as optional context.
"""

from __future__ import annotations

from urllib.parse import quote


OPENING_CONTEXT = {
    "Italian Game: Two Knights Defense, Knight Attack": (
        "After Black develops with Nf6, White's Ng5 is the Knight Attack and "
        "concentrates the bishop and knight on f7. Black normally needs an "
        "immediate, concrete response to the center and the f7 pressure; the "
        "supplied engine line and opening statistics should determine the exact "
        "continuation in this position."
    ),
    "Italian Game": (
        "An open-game family built around rapid development, central influence, "
        "and pressure on the f7 square. Typical plans depend heavily on whether "
        "the center opens quickly or remains stable."
    ),
    "Ruy Lopez": (
        "An open-game family where White develops with pressure on the knight "
        "supporting e5. Both sides usually balance central tension, development, "
        "and long-term piece activity."
    ),
    "Sicilian Defense": (
        "An asymmetrical response to 1.e4 that fights for the center from the "
        "c-file. Positions often feature unequal pawn structures, active "
        "counterplay, and plans on opposite wings."
    ),
    "French Defense": (
        "A 1.e4 defense that supports a later challenge to White's center. Its "
        "closed and semi-closed structures often make pawn breaks and the "
        "activity of Black's light-squared bishop central strategic questions."
    ),
    "Caro-Kann Defense": (
        "A solid 1.e4 defense that prepares a central challenge while usually "
        "keeping the light-squared bishop outside the pawn chain. Development "
        "and the timing of central pawn breaks remain important."
    ),
    "Scandinavian Defense": (
        "A direct challenge to White's e-pawn that clarifies the center early. "
        "Black accepts some development-management questions in exchange for a "
        "clear structure and immediate central contact."
    ),
    "Pirc Defense": (
        "A flexible 1.e4 defense that allows White to occupy the center before "
        "challenging it with pieces and pawn breaks. Accurate timing matters "
        "because White may gain space while Black seeks counterplay."
    ),
    "Modern Defense": (
        "A flexible setup that lets the opponent build a center before attacking "
        "it from the flanks. The position revolves around whether that center "
        "becomes a strength or an overextended target."
    ),
    "Queen's Gambit": (
        "A 1.d4 opening family that challenges Black's central d5 pawn with c4. "
        "The resulting structures emphasize central tension, development, and "
        "the long-term consequences of accepting or declining the gambit."
    ),
    "King's Indian Defense": (
        "A dynamic defense to 1.d4 in which Black permits a broad center and "
        "seeks counterplay against it. Pawn breaks and the race between "
        "queenside space and kingside activity often define the plans."
    ),
    "Nimzo-Indian Defense": (
        "A 1.d4 defense that develops quickly and uses a bishop pin to contest "
        "the center. The bishop pair, doubled pawns, and control of key central "
        "squares are recurring strategic tradeoffs."
    ),
    "English Opening": (
        "A flank opening beginning with c4 that controls d5 and can transpose "
        "into several 1.d4 structures. Flexible move orders make piece placement "
        "and recognition of transpositions especially important."
    ),
    "King's Pawn Game": (
        "An open-game starting point in which 1.e4 creates central influence and "
        "opens lines for the queen and king's bishop. Development speed and king "
        "safety are usually immediate priorities."
    ),
    "Queen's Pawn Game": (
        "A 1.d4 opening family that establishes central space and opens the "
        "c1 bishop. Plans often develop more gradually than open 1.e4 games and "
        "depend strongly on the resulting pawn structure."
    ),
}


def context_for_opening(opening: dict | None) -> dict | None:
    if not isinstance(opening, dict):
        return None
    name = opening.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    description = None
    matched_family = None
    if name in OPENING_CONTEXT:
        matched_family = name
        description = OPENING_CONTEXT[name]
    else:
        for family, family_description in OPENING_CONTEXT.items():
            if name.startswith(f"{family}:"):
                matched_family = family
                description = family_description
                break

    slug = quote(name.replace(" ", "_"), safe="_-")
    return {
        "family": matched_family,
        "description": description,
        "source": "project-curated" if description else None,
        "lichess_url": f"https://lichess.org/opening/{slug}",
    }
