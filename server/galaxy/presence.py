"""
Onde o jogador esta e como ele se chama, lido do save.

E o que o mapa da sala mostra e o que a fase 2 vai usar para decidir quem e
vizinho de quem. Tres coisas saem daqui:

**A posicao, na lingua da sala.** Um lugar e `(systemId, x, y)`. Nao e `celeid`,
que e id de catalogo e nomeia o TIPO de lugar — 123 corpos num save carregam 11
valores desses. Nem o `id` local, que sai de um contador global conforme cada um
explora, e portanto casa lugares diferentes entre dois jogadores. As coordenadas
saem da seed e nao se movem (`docs/findings.md`, item 24).

As coordenadas saem do CORPO em que a frota esta, nao da frota: a frota carrega
coordenadas defasadas do lugar de onde saiu. Em espaco aberto nao ha corpo, e ai
valem as da propria frota. O tipo do corpo vai junto, so para exibir.

**O nome da nave.** Nao existe identidade de jogador dentro do save: a faccao do
jogador e 461 em toda partida do mundo. Quem distingue um jogador do outro na
tela e o `sname` (secao 1.10), entao e ele que o mapa mostra.

**A idade da colonia**, em dias. Serve a conferencia da secao 2.7 — um save que
volta mais novo do que saiu e sinal, nao acidente.

Somente leitura, e tolerante: um save estranho devolve campo nulo em vez de
explodir. Recusar a devolucao de alguem porque o mapa nao conseguiu ler a
posicao seria perder o save por causa de um enfeite.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET

from sgalaxy.graft import player_fleets
from sgalaxy.savefile import SaveError, SaveFile

# A faccao do jogador, igual em todo save do mundo (secao 1.10).
PLAYER_FACTION = "461"


def read(folder: str) -> dict:
    """O que o servidor guarda sobre a presenca de um jogador."""
    out = {"shipName": None, "system": None, "x": None, "y": None,
           "body": None, "ageDays": None, "ships": 0, "crew": 0}
    try:
        sf = SaveFile(folder)
    except SaveError:
        return out

    out["ageDays"] = _age_days(folder)
    out.update(_position(sf))
    out.update(_player_ship(sf))
    return out


def _age_days(folder: str) -> float | None:
    """A idade da colonia em dias, lida do `info`."""
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
    """Onde a frota do jogador esta, por `(systemId, x, y)`.

    A autoridade e a propria frota `<f isPlayer="true">`. Ela aparece em dois
    lugares — pendurada num corpo celeste, ou num setor vazio quando a pessoa
    salvou em transito — e carrega as coordenadas nos dois casos (findings
    item 22). Procurar so no primeiro deixava sem posicao justamente quem
    estava viajando.

    O `starmap/@pa` entra so como ultimo recurso: ele aponta para o `@id` LOCAL
    do corpo, e confundi-lo com `celeid` foi o erro do item 1.
    """
    starmap = sf.main.find("starmap")
    if starmap is None:
        return {}

    pais = {filho: pai for pai in starmap.iter() for filho in pai}

    def _sistema_de(elemento):
        while elemento is not None and elemento.get("systemId") is None:
            elemento = pais.get(elemento)
        return elemento

    for fleet, _container, holder in player_fleets(starmap):
        system = _sistema_de(fleet)
        if system is None:
            continue
        corpo = holder if (holder is not None
                           and holder.get("celeid") is not None) else None
        # O corpo manda. Medido: a frota carrega coordenadas defasadas — em
        # "E7c" ela esta num Planet de x=75924 anunciando x=75724, que era o
        # asteroide de onde saiu. Duas pessoas no mesmo planeta tem o mesmo
        # (x, y) do planeta e nunca o mesmo da frota.
        origem = corpo if corpo is not None else fleet
        return {"system": system.get("systemId"),
                "x": origem.get("x"), "y": origem.get("y"),
                "body": corpo.get("type") if corpo is not None else None}

    # Sem frota no mapa: cai para o `@pa`, que e o `@id` local do corpo.
    pa = starmap.get("pa")
    if pa is None:
        return {}
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("id") == pa and body.get("celeid") is not None:
                return {"system": system.get("systemId"),
                        "x": body.get("x"), "y": body.get("y"),
                        "body": body.get("type")}
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


# ---------------------------------------------------------------------------
# O esqueleto da galaxia, para o mapa da sala
# ---------------------------------------------------------------------------

def galaxy_map(folder: str) -> dict:
    """Sistemas com posicao, para desenhar a sala.

    A posicao de um sistema e a da ESTRELA dele: os sistemas nao tem coordenada
    propria no save, e a estrela e o centro fixo. Conferido em dois saves da
    mesma partida com quase um dia e meio de jogo entre eles — nenhuma das 64 se
    moveu, enquanto os corpos que orbitam mudaram.

    O nome vem em hexadecimal e so e atribuido depois da criacao: num save
    recem-criado ele vem vazio, e por isso a impressao digital o ignora. Aqui
    entra como enfeite, e vazio nao e erro.
    """
    import binascii

    try:
        sf = SaveFile(folder)
    except SaveError:
        return {"w": 0, "h": 0, "systems": []}
    starmap = sf.main.find("starmap")
    if starmap is None:
        return {"w": 0, "h": 0, "systems": []}

    def texto(valor):
        if not valor:
            return None
        try:
            return binascii.unhexlify(valor).decode("utf-8") or None
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return valor

    sistemas = []
    for system in starmap.findall("systems/l"):
        estrela = next((b for b in system.findall("bodies/l")
                        if b.get("type") == "Star"), None)
        if estrela is None or estrela.get("x") is None:
            continue
        sistemas.append({
            "systemId": system.get("systemId"),
            "name": texto(system.get("sn")),
            "x": int(estrela.get("x")),
            "y": int(estrela.get("y")),
            "bodies": len(system.findall("bodies/l")),
        })
    return {
        "w": int(starmap.get("w") or 0),
        "h": int(starmap.get("h") or 0),
        "systems": sistemas,
    }
