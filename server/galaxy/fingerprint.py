"""
Impressao digital da galaxia gerada por uma seed.

E o portao de entrada de uma sala: quando um jogador cria a partida com a seed e
as opcoes publicadas e sobe o save, o servidor confere que a galaxia dele e mesmo
a da sala antes de adotar aquele save como canonico (secao 2.3 do projeto).

Funciona porque a seed reproduz o mundo gerado e nao reproduz o resto: os
sistemas, os corpos celestes com semente propria e os setores de terreno saem
iguais em duas partidas com a mesma seed e as mesmas opcoes, enquanto tripulacao,
nome de nave e interior das naves saem diferentes. O digest cobre so a parte
reprodutivel.

CODIGO VENDORADO. Origem: `tools/compare_galaxy.py` do editor de savegame,
<https://github.com/Gianotto/Space-Haven-SaveGameEditor>, commit registrado em
`sgalaxy/VENDOR.md`. As constantes e a montagem do esqueleto sao as de la, e
`tests/test_fingerprint_parity.py` exige que as duas copias produzam o mesmo
digest sobre o mesmo save. Se divergirem, o teste quebra — e essa e a unica
defesa contra a deriva, porque ninguem vai lembrar de sincronizar na mao.

O que fica de fora do digest, e por que:

- `x`, `y`, `timeStepA` dos corpos e `angle` dos setores acompanham a orbita e
  mudam sozinhos com o tempo de jogo
- setores transitorios (missao, nave no mapa, oferta de novo lar) aparecem e
  somem durante a partida
- o nome dos sistemas so e atribuido depois da criacao: um save recem-criado nao
  tem nenhum e um jogado tem todos, e comparar save novo com save jogado e
  justamente o caso de uso
- `starmap/@sys` e `@pa` sao referencias, nao parametros de geracao
  (`docs/findings.md`, item 1)
"""

from __future__ import annotations

import binascii
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from sgalaxy.savefile import SaveError, SaveFile  # noqa: E402

# Atributos de um corpo celeste que o gerador define e o jogo nao mexe depois.
BODY_KEYS = ("type", "celeid", "seed", "starType", "starClass",
             "ox", "oy", "centerId", "maxLen", "orbitSpeedMul")

# What the DIGEST is built from, as opposed to what the report shows.
#
# A galaxy is materialised lazily, one system at a time, as the player looks at
# it or arrives. Measured: a grafted save had 123 bodies before a hyperspace
# jump and 137 after — system 1 gained three planets, five moons and six
# asteroid fields at once, all with their own seeds. Counting bodies therefore
# fingerprints how much of the galaxy has been EXPLORED, not which galaxy it is,
# and two players in the same room would drift apart the moment either travelled.
#
# The star of each system does not drift. It exists from the first save, it is
# the fixed centre the rest orbits, and it carries the generator's seed.
# Verified stable across four states of one game — fresh, played, grafted, and
# after a jump — and different for another galaxy.
STAR_KEYS = ("celeid", "seed", "x", "y", "starType", "starClass")
# O setor nao tem semente propria; o que o identifica e o tipo mais a orbita.
SECTOR_KEYS = ("type", "strength", "rich")
ORBIT_KEYS = ("rx", "ry", "speed")
# Entram na lista de setores mas nao sao terreno: aparecem e somem durante a
# partida. Conferido em quatro momentos da mesma partida, onde variaram de 3
# para 4, de 1 para 4 e de 6 para 5 enquanto o terreno ficou parado.
TRANSIENT_SECTORS = {"StarmapCraft", "SM_AwayMission", "SM_NewHomeSector",
                     "ExodusSupplyFleet"}
# Do <starmap>, so o tamanho da galaxia e parametro de geracao.
MAP_KEYS = ("w", "h")


def _text(value: str | None) -> str:
    """Os nomes de sistema vem em hexadecimal no save."""
    if not value:
        return ""
    try:
        return binascii.unhexlify(value).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return value


def _pick(node, keys) -> dict:
    return {k: node.get(k) for k in keys if node.get(k) is not None}


def _key(rec: dict) -> str:
    return json.dumps(rec, sort_keys=True, ensure_ascii=False)


def fingerprint(path: str) -> dict:
    """Impressao digital da galaxia de um save."""
    sf = SaveFile(path)
    root = sf.main
    starmap = root.find("starmap")
    if starmap is None:
        raise SaveError(f"{path}: este save não tem <starmap>")

    systems, volatile = [], []
    for system in starmap.findall("systems/l"):
        # Ordenado, e nao na ordem do arquivo: o que interessa e o conjunto de
        # corpos, nao a ordem em que o jogo resolveu grava-los.
        bodies = sorted((_pick(b, BODY_KEYS)
                         for b in system.findall("bodies/l")), key=_key)

        sectors, dropped = [], []
        for sector in system.findall("emptySectors/l"):
            if sector.get("type") in TRANSIENT_SECTORS:
                dropped.append(sector.get("type"))
                continue
            rec = _pick(sector, SECTOR_KEYS)
            orbit = sector.find("orbit")
            if orbit is not None:
                rec.update({f"orbit_{k}": v
                            for k, v in _pick(orbit, ORBIT_KEYS).items()})
            sectors.append(rec)
        sectors.sort(key=_key)
        volatile += dropped

        clouds = sorted(({"color": c.get("color"), "points": len(c.findall("cd"))}
                         for c in system.findall("clouds/c")), key=_key)
        star = next((b for b in system.findall("bodies/l")
                     if b.get("type") == "Star"), None)
        systems.append({
            "star": _pick(star, STAR_KEYS) if star is not None else None,
            "id": system.get("systemId"),
            "name": _text(system.get("sn")),
            "short": _text(system.get("smn")),
            "bodies": bodies,
            "sectors": sectors,
            "clouds": clouds,
        })

    fp = {
        "save": os.path.abspath(path),
        "seed": root.get("seed"),
        "mode": root.get("mode"),
        "map": _pick(starmap, MAP_KEYS),
        "systems": systems,
        "ignored": len(volatile),
        "named": sum(1 for s in systems if s["name"].strip()),
        "stars": sum(1 for s in systems if s["star"]),
    }
    # The digest covers the map size and every system's star, and nothing else.
    # Bodies, terrain sectors and clouds stay in the report because they are
    # useful to a human comparing two saves — but they materialise during play,
    # so they cannot decide whether two saves share a galaxy.
    skeleton = {
        "map": fp["map"],
        "stars": sorted(
            [s["id"], s["star"]] for s in systems if s["star"]),
    }
    fp["digest"] = hashlib.sha256(
        json.dumps(skeleton, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    return fp


# ---------------------------------------------------------------------------
# O que o servidor usa
# ---------------------------------------------------------------------------

# Quantos sistemas duas galaxias precisam ter em comum para a concordancia
# significar alguma coisa. Um save com dois sistemas concordaria com qualquer
# galaxia por nao ter o que contradizer. A medida real e 64 num save recem
# criado; dezesseis e um quarto disso — muito acima de qualquer acidente e
# muito abaixo de qualquer save legitimo.
MIN_OVERLAP = 16


def stars_of(path: str) -> dict:
    """As estrelas por sistema: `{systemId: {celeid, seed, x, y, ...}}`.

    E a forma comparavel da galaxia. O digest continua existindo para
    identificar a sala num relance; quem decide se dois saves compartilham
    galaxia e isto.
    """
    return {s["id"]: s["star"]
            for s in fingerprint(path)["systems"] if s["star"]}


def agree(room_stars: dict, save_stars: dict) -> tuple:
    """Estes dois saves sao da mesma galaxia? Devolve `(sim, motivo)`.

    NAO E IGUALDADE, E CONCORDANCIA.

    Uma galaxia se materializa aos poucos: o jogo gera o sistema quando alguem
    viaja ate la. Medido numa sessao recusada de verdade — 64 sistemas na
    entrega, 65 na devolucao, e as 64 estrelas em comum identicas byte a byte.
    O save estava certo; o portao e que estava errado.

    Uma seed gera o mesmo sistema 12 todas as vezes. Entao discordar sobre o
    sistema 12 e ser outra galaxia; conhecer mais sistemas e so ter explorado
    mais.
    """
    if not room_stars:
        return True, ""
    comuns = set(room_stars) & set(save_stars)
    # O teto e o que a SALA conhece, nunca o que o save traz: incluir o
    # tamanho do save no minimo faz um save de tres sistemas exigir tres
    # coincidencias e passar — que e exatamente o ataque que este limite
    # existe para barrar. Um save recem-criado tem 64 sistemas (medido: e o
    # que a primeira entrada desta sala trouxe), entao dezesseis nao aperta
    # ninguem legitimo.
    if len(comuns) < min(MIN_OVERLAP, len(room_stars)):
        return False, (f"this save shares only {len(comuns)} system(s) with "
                       f"the room; that is not the same galaxy")
    divergentes = sorted(k for k in comuns if room_stars[k] != save_stars[k])
    if divergentes:
        return False, (f"this save disagrees with the room about "
                       f"system {divergentes[0]}"
                       + (f" and {len(divergentes) - 1} other(s)"
                          if len(divergentes) > 1 else "")
                       + ". A seed generates the same system every time, so "
                         "this galaxy is a different one")
    return True, ""


def digest_of(path: str) -> str:
    """So o digest, que e o que a sala guarda e compara."""
    return fingerprint(path)["digest"]


def save_version(path: str) -> str | None:
    """Versao do FORMATO do save (`info/@version`), nao a versao do jogo.

    Num save de 1.0.4 vale `21`. A sala ancora nisso: se a Bugbyte mudar o
    formato, um save de versao diferente e recusado em vez de aceito e
    corrompido mais tarde. Ver `docs/findings.md`, item 13.
    """
    import xml.etree.ElementTree as ET

    sf = SaveFile(path)
    info = os.path.join(sf.dir, "info")
    if not os.path.isfile(info):
        return None
    try:
        with open(info, "rb") as fh:
            return ET.fromstring(fh.read()).get("version")
    except (OSError, ET.ParseError):
        return None


def describe(path: str) -> dict:
    """O que o `join` precisa saber sobre um save que acabou de chegar."""
    fp = fingerprint(path)
    return {
        "digest": fp["digest"],
        "saveVersion": save_version(path),
        "systems": len(fp["systems"]),
        "stars": fp["stars"],
        # Bodies and sectors are reported, never compared: they grow as the
        # galaxy is materialised (see STAR_KEYS).
        "bodies": sum(len(s["bodies"]) for s in fp["systems"]),
        "sectors": sum(len(s["sectors"]) for s in fp["systems"]),
        "named": fp["named"],
    }
