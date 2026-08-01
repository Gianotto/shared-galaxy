"""
Descoberta compartilhada: o que um desbravou aparece para os outros.

A REGRA, decidida
-----------------

A sala junta os `visited`. O `isVisible` não se compartilha sozinho — ele vem
junto onde houve visita. Ou seja: a sala reúne os lugares onde alguém
**esteve**, e esses chegam devidamente cartografados. O que alguém só avistou de
longe e nunca entrou continua sendo dele. Quem chega novo herda as viagens da
sala, não o telescópio dela.

Medido em três saves reais (`docs/findings.md`, item 23): `visited` é sempre
subconjunto de `isVisible`. O jogo nunca marca um lugar como visitado sem
marcá-lo visível, então marcar um `visited` compartilhado obriga a marcar
`isVisible` no mesmo corpo — senão o jogo receberia uma combinação que ele nunca
produz.

POR QUE NÃO BASTA MARCAR
------------------------

A galáxia se materializa preguiçosamente (item 19). Um save recém-criado tem 123
corpos para 64 sistemas: as estrelas, os campos de asteroide e o ponto de
partida. O planeta que alguém visitou no sistema 40 **não existe** no save de
quem nunca foi lá — não há o que marcar. Então a mescla é de duas coisas: o
subárvore do corpo, quando falta, e os sinalizadores, quando o corpo já está lá.

O QUE NÃO ATRAVESSA
-------------------

`<fleets>`. Um corpo visitado carrega as naves paradas nele, e copiar isso
traria as naves dos outros junto com o lugar. Vizinho visível é fase 2, tem
recibo próprio e regra própria; aqui só o lugar viaja.

E quando o corpo já existe no save de quem recebe, **nada é substituído** — só
os sinalizadores mudam. O `<stuff>` local guarda o que a pessoa já minerou
naquele asteroide, e sobrescrever isso devolveria minério que ela já tirou.

A CHAVE
-------

`(systemId, x, y)`. Não `celeid`, que nomeia o TIPO de lugar — 123 corpos num
save carregam 11 desses valores. Nem o `id` local, que sai de um contador global
conforme cada um explora, e por isso casa lugares diferentes entre dois
jogadores. As coordenadas saem da seed e não se movem (item 24).

Um corpo inserido ganha `id` novo, tirado do `starmap/@objectIdCounter` de quem
recebe. Reusar o `id` do doador colidiria com um corpo que já existe do outro
lado — e um id repetido é o tipo de erro que carrega e quebra depois.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

from sgalaxy.savefile import SaveFile, _insert_child, _remove_child

# O que não viaja junto com o lugar.
NAO_COPIAR = ("fleets", "fleet")


def _lugar(system: ET.Element, body: ET.Element) -> tuple:
    return (system.get("systemId"), body.get("x"), body.get("y"))


def _visitado(body: ET.Element) -> bool:
    info = body.find("info")
    return info is not None and info.get("visited") == "true"


def bodies_of(starmap: ET.Element):
    """Cada corpo do mapa, com o sistema que o contém."""
    for system in starmap.findall("systems/l"):
        for body in system.iter():
            if body.get("celeid") is not None:
                yield system, body


def visited(sf: SaveFile) -> dict:
    """Os lugares onde este save esteve, prontos para a sala guardar.

    Devolve `{(systemId, x, y): xml}`, com `<fleets>` já removido — o que se
    compartilha é o lugar, nunca quem está parado nele.
    """
    starmap = sf.main.find("starmap")
    if starmap is None:
        return {}
    out = {}
    for system, body in bodies_of(starmap):
        if not _visitado(body):
            continue
        chave = _lugar(system, body)
        if None in chave:
            continue
        limpo = copy.deepcopy(body)
        limpo.tail = None
        for filho in list(limpo):
            if filho.tag in NAO_COPIAR:
                _remove_child(limpo, filho)
        out[chave] = ET.tostring(limpo, encoding="unicode")
    return out


def merge(sf: SaveFile, discovered: dict) -> dict:
    """Põe a descoberta da sala no save. Muda `sf`.

    `discovered` é `{(systemId, x, y): xml}`, como `visited` devolve.
    """
    report = {"flagged": 0, "inserted": 0, "skipped": 0}
    starmap = sf.main.find("starmap")
    if starmap is None or not discovered:
        return report

    presentes = {}
    sistemas = {}
    for system, body in bodies_of(starmap):
        presentes[_lugar(system, body)] = body
        sistemas[system.get("systemId")] = system

    for chave, xml in sorted(discovered.items()):
        corpo = presentes.get(chave)
        if corpo is not None:
            if _marcar(corpo):
                report["flagged"] += 1
            continue
        system = sistemas.get(chave[0])
        if system is None:
            # A sala conhece um sistema que este save não tem. Não deveria
            # acontecer numa sala de galáxia única, e inventar um sistema seria
            # bem pior do que deixar de mostrar um lugar.
            report["skipped"] += 1
            continue
        _inserir(starmap, system, xml)
        report["inserted"] += 1
    return report


def _marcar(corpo: ET.Element) -> bool:
    """Liga `visited` e `isVisible` num corpo que já existe. Não toca no resto."""
    info = corpo.find("info")
    if info is None:
        info = ET.Element("info")
        _insert_child(corpo, info)
    antes = (info.get("visited"), info.get("isVisible"))
    info.set("visited", "true")
    # Medido: `visited` é sempre subconjunto de `isVisible`. Marcar um sem o
    # outro daria ao jogo uma combinação que ele nunca produz sozinho.
    info.set("isVisible", "true")
    return antes != ("true", "true")


def _inserir(starmap: ET.Element, system: ET.Element, xml: str) -> ET.Element:
    """Acrescenta um corpo que falta, com `id` novo de quem recebe."""
    corpo = ET.fromstring(xml)
    corpo.tail = None
    _marcar(corpo)

    contador = starmap.get("objectIdCounter")
    if contador is not None and contador.isdigit():
        corpo.set("id", contador)
        starmap.set("objectIdCounter", str(int(contador) + 1))
    elif corpo.get("id") is not None:
        # Sem contador não há id seguro para dar, e um id repetido quebra
        # depois de carregar. Melhor o corpo entrar sem id.
        del corpo.attrib["id"]

    bodies = system.find("bodies")
    if bodies is None:
        bodies = ET.Element("bodies")
        _insert_child(system, bodies, 0)
    _insert_child(bodies, corpo)
    return corpo
