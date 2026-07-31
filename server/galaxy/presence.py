"""
Onde o jogador esta e como ele se chama, lido do save.

E o que o mapa da sala mostra e o que a fase 2 vai usar para decidir quem e
vizinho de quem. Tres coisas saem daqui:

**A posicao, na lingua da sala.** O corpo celeste vem como `celeid`, nunca como
o `id` local. Sao dois ids diferentes e so o `celeid` deriva da seed e significa
a mesma coisa no save de todo mundo — trocar os dois poe o vizinho no setor
errado, em silencio (`docs/findings.md`, item 1).

**O nome da nave.** Nao existe identidade de jogador dentro do save: a faccao do
jogador e 461 em toda partida do mundo. Quem distingue um jogador do outro na
tela e o `sname` (secao 1.10), entao e ele que o mapa mostra.

**O dia de jogo.** Serve a conferencia da secao 2.7 — um save que volta com
menos dias do que saiu e sinal, nao acidente.

Somente leitura, e tolerante: um save estranho devolve campo nulo em vez de
explodir. Recusar a devolucao de alguem porque o mapa nao conseguiu ler a
posicao seria perder o save por causa de um enfeite.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from sgalaxy.savefile import SaveError, SaveFile

# A faccao do jogador, igual em todo save do mundo (secao 1.10).
PLAYER_FACTION = "461"


def read(folder: str) -> dict:
    """O que o servidor guarda sobre a presenca de um jogador."""
    out = {"shipName": None, "system": None, "celeid": None,
           "gameDay": None, "ships": 0, "crew": 0}
    try:
        sf = SaveFile(folder)
    except SaveError:
        return out

    out["gameDay"] = _game_day(folder)
    out.update(_position(sf))
    out.update(_player_ship(sf))
    return out


def _game_day(folder: str) -> float | None:
    path = os.path.join(folder, "info")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as fh:
            value = ET.fromstring(fh.read()).get("date")
        return round(int(value) / 86400, 2) if value else None
    except (OSError, ET.ParseError, ValueError, TypeError):
        return None


def _position(sf: SaveFile) -> dict:
    """O corpo celeste onde a frota do jogador esta, por `celeid`.

    A autoridade e a propria frota `<f isPlayer="true">`, que e o dado mais
    direto. O `starmap/@pa` entra so como conferencia: ele aponta para o `@id`
    local do corpo, e usa-lo como se fosse `celeid` foi o erro que o item 1 do
    findings registra.
    """
    starmap = sf.main.find("starmap")
    if starmap is None:
        return {}

    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") is None:
                continue
            fleets = body.find("fleets")
            if fleets is None:
                continue
            for fleet in fleets.findall("f"):
                if fleet.get("isPlayer") == "true":
                    return {"system": system.get("systemId"),
                            "celeid": body.get("celeid")}

    # Sem frota no mapa: cai para o `@pa`, resolvendo o id local para `celeid`.
    pa = starmap.get("pa")
    if pa is None:
        return {}
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("id") == pa and body.get("celeid") is not None:
                return {"system": system.get("systemId"),
                        "celeid": body.get("celeid")}
    return {}


def _player_ship(sf: SaveFile) -> dict:
    """A nave do jogador — a que carrega a identidade dele na tela."""
    ships = crew = 0
    name = None
    for _doc, ship in sf.ships():
        ships += 1
        settings = ship.find("settings")
        if settings is None or settings.get("of") != PLAYER_FACTION:
            continue
        characters = ship.find("characters")
        n = len(list(characters)) if characters is not None else 0
        # Havendo mais de uma nave do jogador, a com mais tripulacao e a casa.
        if name is None or n > crew:
            name, crew = ship.get("sname"), n
    return {"shipName": name, "ships": ships, "crew": crew}
