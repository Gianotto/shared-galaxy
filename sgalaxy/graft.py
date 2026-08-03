"""
Grafting a galaxy into a save.

Shared by the command-line tool and by the server, which is why it lives here
and not in `tools/`: the server cannot import from `tools/`, and duplicating
this would mean two copies of the one operation that rewrites somebody's game.

The onboarding problem it solves: without it, a player has to create a game with
the room's exact seed AND every scenario option right, or the fingerprint refuses
their save. With it, they create a game however they like and the server hands
back a save already in the room's galaxy.

WHAT MOVES

    <starmap>     the whole thing: systems, bodies, terrain sectors, clouds
    <questLines>  from the same donor, because it points INTO the starmap

WHAT IS CLEARED

    <missions>, and the mission nodes on ships — they name systems and sectors
    of the galaxy being replaced

WHAT IS PRESERVED

    everything else the player owns: ships, crew, `playerBank`, research,
    `hostmap`, and the already-generated starting sector in `<space>`

THE REFERENCES THAT COST A CRASH. The first version moved `<starmap>` alone, on
the assumption that a galaxy is a self-contained subtree. It is not. Loading
worked; the first hyperspace jump crashed with a NullPointerException inside
`QuestExodusFleetMissions.addFindBeaconFromDere` — the quest line had gone
looking for a beacon that existed in the old galaxy. Three places outside
`<starmap>` hold ids from inside it (`docs/findings.md`, item 18).

THE KNOWN SEAM. The starting sector's `<space>` was generated from the player's
original body, and the game does not regenerate a sector on load (section 1.6).
That one sector keeps the asteroid field it was born with while the room's
starmap declares possibly different `<stuff>` for that body. Everything
travelled to afterwards is generated from the shared galaxy.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from sgalaxy.savefile import SaveError, SaveFile, _insert_child, _remove_child


# The player's fleet lives in one of two places, and both are ordinary game
# states. Parked at a celestial body it is `bodies/l/fleets/f`; sitting in open
# space it is `emptySectors/l/fleet/l` — different container AND different tag,
# because the game names list children after the field that holds them.
#
# Measured in real saves, both at format version 21: "Happy Place" was at a body,
# "New haven-1" was in an empty sector. Looking only for `fleets/f` refused every
# player who happened to save mid-travel (findings item 22).
FLEET_CONTAINERS = ("fleets", "fleet")


def player_fleets(starmap: ET.Element):
    """Every `isPlayer="true"` fleet, with its container and what holds it.

    Yields `(fleet, container, holder)` — holder is the body or the empty
    sector. A save has exactly one, but the donor's is stripped by the same
    walk, so this yields rather than returning the first.
    """
    parents = {child: parent for parent in starmap.iter() for child in parent}
    for element in starmap.iter():
        if element.get("isPlayer") != "true":
            continue
        container = parents.get(element)
        if container is None or container.tag not in FLEET_CONTAINERS:
            continue
        yield element, container, parents.get(container)


def player_fleet(sf: SaveFile) -> tuple:
    """The player's fleet and the body or sector holding it, or (None, None)."""
    starmap = sf.main.find("starmap")
    if starmap is None:
        return None, None
    for fleet, _container, holder in player_fleets(starmap):
        return fleet, holder
    return None, None


def body_by_celeid(starmap: ET.Element, celeid: str) -> tuple:
    """The body with that `celeid`, and the system holding it."""
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") == str(celeid):
                return body, system
    return None, None


def start_body(starmap: ET.Element) -> tuple:
    """Where a fresh game begins: the asteroid marked `isst="1"`.

    It appears exactly once in a save and is always an asteroid — the player's
    origin (section 1.5). Since the seed reproduces the starting point, this is
    the same body for everyone in a room (findings item 16), which is precisely
    what makes it the right place to graft someone in.

    The flag sits on the body's `<info>` CHILD, not on the body. Section 1.5
    does say "in the body's `<info>`" and I still read it as an attribute of the
    body — which found the `<info>` element itself, a thing with no `celeid` and
    no `id`, and produced a graft pointing nowhere.
    """
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") is None:
                continue
            info = body.find("info")
            if info is not None and info.get("isst") == "1":
                return body, system
    return None, None


def place_player_fleet(starmap: ET.Element, fleet: ET.Element,
                       body: ET.Element, system: ET.Element) -> dict:
    """Poe a frota do jogador num corpo celeste, com tudo que isso exige.

    QUATRO COISAS TEM QUE CONCORDAR, e fazer tres delas produz um save que
    abre e mente sobre onde a pessoa esta:

        1. a frota pendurada no `<fleets>` do corpo de destino
        2. a tag `<f>`, porque e assim que os irmaos dela se chamam ali
        3. as coordenadas DO CORPO, nao as que a frota trazia
        4. `starmap/@sys` e `@pa` apontando para o mesmo lugar

    O `@pa` e o `@id` LOCAL do corpo, e nao o `celeid`: confundir os dois foi o
    erro silencioso do item 1 do findings.

    A terceira e a menos obvia. O `presence` le a posicao do CORPO quando a
    frota esta pendurada num, porque a frota carrega coordenadas defasadas —
    medido em E7c, uma frota num planeta de x=75924 anunciava x=75724, que era
    o asteroide de onde ela tinha saido.

    Devolve o relatorio do que fez. A frota entra como copia; quem chama
    remove a original se ela ainda estiver em outro lugar.
    """
    relatorio: dict = {"warnings": []}
    fleets = body.find("fleets")
    if fleets is None:
        # Secao 1.5: o corpo de destino em geral nao tem <fleets>; ele entra
        # entre <stuff> e <info>.
        fleets = ET.Element("fleets")
        info = body.find("info")
        index = list(body).index(info) if info is not None else len(list(body))
        _insert_child(body, fleets, index)
        relatorio["createdFleets"] = True

    moved = copy.deepcopy(fleet)
    moved.tail = None
    moved.tag = "f"
    if body.get("x") is None or body.get("y") is None:
        relatorio["warnings"].append(
            "the destination body has no x/y; the fleet kept the coordinates "
            "it had before, which point nowhere here")
    for attr in ("x", "y"):
        if body.get(attr) is not None:
            moved.set(attr, body.get(attr))
    _insert_child(fleets, moved)

    starmap.set("sys", system.get("systemId"))
    if body.get("id") is not None:
        starmap.set("pa", body.get("id"))
    else:
        relatorio["warnings"].append(
            "the destination body has no @id; left starmap/@pa untouched")

    relatorio.update({"toCeleid": body.get("celeid"),
                      "toBodyId": body.get("id"),
                      "system": system.get("systemId"),
                      "x": moved.get("x"), "y": moved.get("y")})
    return relatorio


def graft(galaxy_sf: SaveFile, player_sf: SaveFile,
          start_celeid: str | None = None) -> dict:
    """Puts the room's galaxy into the player's save. Mutates `player_sf`."""
    source = galaxy_sf.main.find("starmap")
    if source is None:
        raise SaveError("the galaxy save has no <starmap>")
    target_root = player_sf.main
    current = target_root.find("starmap")
    if current is None:
        raise SaveError("the player save has no <starmap>")

    report: dict = {"warnings": []}

    fleet, old_body = player_fleet(player_sf)
    if fleet is None:
        raise SaveError(
            "no isPlayer=\"true\" fleet in the player save: without the fleet "
            "there is nothing to place in the new galaxy")
    report["fleetId"] = fleet.get("id")
    report["fromCeleid"] = old_body.get("celeid") if old_body is not None else None

    new_map = copy.deepcopy(source)
    new_map.tail = current.tail

    # The donor's own fleets come along with the subtree. Player fleets are
    # stripped — one save has exactly one player, and leaving the donor's would
    # make two.
    stripped = 0
    for donor_fleet, container, _holder in list(player_fleets(new_map)):
        _remove_child(container, donor_fleet)
        stripped += 1
    report["strippedFleets"] = stripped

    if start_celeid:
        body, system = body_by_celeid(new_map, start_celeid)
        if body is None:
            raise SaveError(f"no body with celeid={start_celeid} in the galaxy")
    else:
        body, system = start_body(new_map)
        if body is None:
            raise SaveError(
                "no body marked isst=\"1\" in the galaxy, and no --start-celeid "
                "given: I do not know where to put the player")

    posto = place_player_fleet(new_map, fleet, body, system)
    report["warnings"] += posto.pop("warnings", [])
    report.update(posto)

    index = list(target_root).index(current)
    _remove_child(target_root, current)
    _insert_child(target_root, new_map, index)

    report.update(_move_quests(galaxy_sf.main, target_root))

    player_sf.mark_dirty(target_root)
    player_sf.reindex()

    report.update({
        "systems": len(new_map.findall("systems/l")),
        "toCeleid": body.get("celeid"),
        "toBodyId": body.get("id"),
        "system": system.get("systemId"),
        "bodyType": body.get("type"),
    })
    return report


# Everything outside <starmap> that names something inside it. Found the hard
# way: the first graft crashed on the first hyperspace jump.
QUEST_NODE = "questLines"
MISSION_NODES = ("missions",)


def _move_quests(donor_root: ET.Element, target_root: ET.Element) -> dict:
    """Brings the donor's quest state over and drops the player's missions."""
    out: dict = {}

    donor_quests = donor_root.find(QUEST_NODE)
    current = target_root.find(QUEST_NODE)
    if donor_quests is not None and current is not None:
        fresh = copy.deepcopy(donor_quests)
        fresh.tail = current.tail
        index = list(target_root).index(current)
        _remove_child(target_root, current)
        _insert_child(target_root, fresh, index)
        out["questLines"] = "from the galaxy donor"
    elif current is not None:
        out["questLines"] = "left as they were: the donor has none"

    dropped = 0
    for tag in MISSION_NODES:
        node = target_root.find(tag)
        if node is None:
            continue
        for child in list(node):
            _remove_child(node, child)
            dropped += 1

    # Ships carry their own mission nodes, naming systems and sectors of the
    # galaxy that just went away.
    ships = target_root.find("ships")
    if ships is not None:
        for holder in list(ships.iter("missions")):
            for child in list(holder):
                _remove_child(holder, child)
                dropped += 1
    out["droppedMissions"] = dropped
    return out
