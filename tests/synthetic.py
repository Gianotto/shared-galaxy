"""
Savegame sintetico minimo, para exercitar as ferramentas sem o jogo instalado.

Nao e um save de verdade e nao serve para provar que o jogo aceita nada. Serve
para provar que as ferramentas fazem o que dizem: que o diff acha o que mudou,
que nao inventa mudanca onde nao houve, e que casa elementos por id em vez de
por posicao. As afirmacoes sobre o jogo continuam dependendo de save real.

A estrutura imita a do save de verdade nos pontos que as ferramentas tocam,
medidos em docs/savegame-format.md: `masterData/@idCounter`, `<starmap>` com
sistemas e corpos, `<ships>` com `sid`, `<shipBank>` com estoque, `<playerBank>`
com creditos, e o estilo de serializacao do jogo (uma linha, sem cabecalho XML).
"""

from __future__ import annotations

import os

GAME_TEMPLATE = """<game seed="0" mode="0">\
<masterData idCounter="{id_counter}"/>\
<playerBank ca="{player_credits}"/>\
<settings f="461"/>\
<starmap w="500000" h="500000" sys="6" pa="{pa}" objectIdCounter="900">\
<systems>\
<l systemId="6" sn="416c706861" smn="414c">\
<bodies>\
<l celeid="101" type="Planet" seed="7731" ox="1200" oy="1200" centerId="100"/>\
<l celeid="102" type="Asteroid" seed="4412" ox="300" oy="300" centerId="101"\
 isst="1">\
<stuff><mining><toMine element="2053"/></mining></stuff>\
{fleets}\
<info visited="{visited}" isVisible="{visited}"/>\
</l>\
</bodies>\
<emptySectors/>\
<clouds/>\
</l>\
</systems>\
</starmap>\
<hostmap><map>\
<l f1="461" f2="{other_faction}" rel="{relation}" accessTrade="{trade}"\
 accessShip="0" accessVision="{vision}" accessHire="0"/>\
</map></hostmap>\
<ships>{ships}</ships>\
<spaceItems/>\
</game>
"""

FLEETS_TEMPLATE = """<fleets>\
<f id="0" isPlayer="true" factionId="461"><createdShips/></f>\
{npc_fleet}\
</fleets>"""

NPC_FLEET_TEMPLATE = """<f id="{fleet_id}" isPlayer="false"\
 factionId="{faction}">\
<createdShips>\
<l seed="55" createdShipId="{sid}" created="true" station="false"\
 crew="{crew}" sx="20" sy="14"/>\
</createdShips>\
</f>"""

SHIP_TEMPLATE = """<ship sid="{sid}" sname="{name}">\
<settings of="{faction}" owner="{owner}"/>\
<characters>{crew}</characters>\
{bank}\
<inv>{cargo}</inv>\
</ship>"""

BANK_TEMPLATE = """<shipBank s="Civilian" ca="{credits}" cr="0" slp="10066"\
 blp="9891" spmd="2"><markup>{markup}</markup><discount/></shipBank>"""


def _crew(entries) -> str:
    return "".join(
        f'<c entId="{e["ent"]}" name="{e["name"]}" fid="{e.get("fid", 461)}"'
        f' x="{e.get("x", 10)}" y="{e.get("y", 10)}"/>'
        for e in entries)


def _cargo(entries) -> str:
    return "".join(
        f'<l elementId="{e["element"]}" inStorage="{e["amount"]}"/>'
        for e in entries)


def _markup(entries) -> str:
    return "".join(
        f'<n element="{e}" howMuch="1" consumeEvery="1"/>' for e in entries)


def build_game(id_counter: int = 1000,
               player_credits: int = 5000,
               pa: int = 102,
               visited: str = "false",
               relation: int = 70,
               trade: str = "1",
               vision: str = "1",
               other_faction: int = 462,
               ships=None) -> str:
    """Monta o documento `game` inteiro como texto."""
    ships = ships if ships is not None else [default_player_ship()]

    # O id da frota deriva do `sid` da nave, nunca da posicao dela na lista.
    # No save de verdade ele sai de `starmap/@objectIdCounter` e e estavel;
    # numerar por posicao faria uma reordenacao parecer mudanca de frota.
    npc_fleets = "".join(
        NPC_FLEET_TEMPLATE.format(
            fleet_id=900000 + s["sid"], faction=s["faction"], sid=s["sid"],
            crew=len(s.get("crew", [])))
        for s in ships if s["owner"] != "Player")

    ship_xml = "".join(
        SHIP_TEMPLATE.format(
            sid=s["sid"], name=s["name"], faction=s["faction"],
            owner=s["owner"], crew=_crew(s.get("crew", [])),
            cargo=_cargo(s.get("cargo", [])),
            bank=(BANK_TEMPLATE.format(credits=s["bank"]["credits"],
                                       markup=_markup(s["bank"].get("markup", [])))
                  if s.get("bank") else ""))
        for s in ships)

    return GAME_TEMPLATE.format(
        id_counter=id_counter, player_credits=player_credits, pa=pa,
        visited=visited, relation=relation, trade=trade, vision=vision,
        other_faction=other_faction,
        fleets=FLEETS_TEMPLATE.format(npc_fleet=npc_fleets),
        ships=ship_xml)


def default_player_ship() -> dict:
    return {
        "sid": 3746, "name": "Homestead", "faction": 461, "owner": "Player",
        "crew": [{"ent": 55, "name": "Ana"}, {"ent": 56, "name": "Bo"}],
        "cargo": [{"element": 2053, "amount": 40},
                  {"element": 2054, "amount": 12}],
    }


def npc_trader_ship(sid: int = 5001, faction: int = 462,
                    credits: int = 12309, stock=None) -> dict:
    return {
        "sid": sid, "name": "Meridian", "faction": faction, "owner": "Civilian",
        "crew": [{"ent": 70, "name": "Wen", "fid": faction}],
        "cargo": stock if stock is not None else [
            {"element": 2053, "amount": 100}],
        "bank": {"credits": credits, "markup": [2053]},
    }


def write_save(root: str, game_xml: str, ships: dict | None = None) -> str:
    """Grava uma pasta de save. Devolve o caminho da pasta."""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "game"), "w", encoding="utf-8") as fh:
        fh.write(game_xml)
    with open(os.path.join(root, "info"), "w", encoding="utf-8") as fh:
        fh.write('<info version="1.0.4" date="2026-07-31"/>\n')
    if ships:
        ships_dir = os.path.join(root, "ships")
        os.makedirs(ships_dir, exist_ok=True)
        for name, xml in ships.items():
            with open(os.path.join(ships_dir, name), "w",
                      encoding="utf-8") as fh:
                fh.write(xml)
    return root
