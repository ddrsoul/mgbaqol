# SPDX-License-Identifier: GPL-2.0-or-later
"""Type effectiveness (Gen 6+ chart, which also covers Fairy in modern hacks)."""

_SUPER = {
    "Fighting": "Normal Rock Steel Ice Dark",
    "Flying": "Fighting Bug Grass",
    "Poison": "Grass Fairy",
    "Ground": "Poison Rock Steel Fire Electric",
    "Rock": "Flying Bug Fire Ice",
    "Bug": "Grass Psychic Dark",
    "Ghost": "Ghost Psychic",
    "Steel": "Rock Ice Fairy",
    "Fire": "Bug Steel Grass Ice",
    "Water": "Ground Rock Fire",
    "Grass": "Ground Rock Water",
    "Electric": "Flying Water",
    "Psychic": "Fighting Poison",
    "Ice": "Flying Ground Grass Dragon",
    "Dragon": "Dragon",
    "Dark": "Ghost Psychic",
    "Fairy": "Fighting Dragon Dark",
}
_RESISTED = {
    "Normal": "Rock Steel",
    "Fighting": "Flying Poison Bug Psychic Fairy",
    "Flying": "Rock Steel Electric",
    "Poison": "Poison Ground Rock Ghost",
    "Ground": "Bug Grass",
    "Rock": "Fighting Ground Steel",
    "Bug": "Fighting Flying Poison Ghost Steel Fire Fairy",
    "Ghost": "Dark",
    "Steel": "Steel Fire Water Electric",
    "Fire": "Rock Fire Water Dragon",
    "Water": "Water Grass Dragon",
    "Grass": "Flying Poison Bug Steel Fire Grass Dragon",
    "Electric": "Grass Electric Dragon",
    "Psychic": "Steel Psychic",
    "Ice": "Steel Fire Water Ice",
    "Dragon": "Steel",
    "Dark": "Fighting Dark Fairy",
    "Fairy": "Poison Steel Fire",
}
_IMMUNE = {
    "Normal": "Ghost", "Fighting": "Ghost", "Poison": "Steel", "Ground": "Flying",
    "Ghost": "Normal", "Electric": "Ground", "Psychic": "Dark", "Dragon": "Fairy",
}


def multiplier(move_type, defender_types):
    m = 1.0
    for d in set(defender_types):
        if d in _IMMUNE.get(move_type, "").split():
            return 0.0
        if d in _SUPER.get(move_type, "").split():
            m *= 2
        elif d in _RESISTED.get(move_type, "").split():
            m *= 0.5
    return m
