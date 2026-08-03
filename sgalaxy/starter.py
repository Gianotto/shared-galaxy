"""O save de partida que a sala entrega a quem chega.

O PROBLEMA QUE ISTO RESOLVE

A primeira entrada de alguém era a parte mais frágil do caminho inteiro. O
servidor não consegue gerar uma colônia inicial, então a partida tinha que
nascer no jogo: abrir o Space Haven, achar NEW GAME, escolher as opções certas,
criar a nave, salvar, fechar na hora certa. Cinco chances de errar antes de a
pessoa ver a galáxia compartilhada, e a recompensa por acertar era chegar ao
mesmo lugar de todo mundo.

O save de partida troca isso por um download. A sala guarda a partida de quem a
criou, do momento em que ela entrou, e entrega uma cópia a cada pessoa nova. A
galáxia já é a da sala, então não há enxerto; a idade já é de quem começou
agora, então não há regra de idade a conferir.

O QUE PRECISA MUDAR NA CÓPIA, E POR QUÊ

Entregar o arquivo intocado daria a todo mundo a mesma nave, com o mesmo nome,
parada no mesmo ponto do mapa. Duas correções bastam para a cópia virar a
partida de outra pessoa:

- **o nome da nave**, senão o mapa da sala mostra três HSS YANNI e ninguém sabe
  quem é quem
- **o lugar**, senão todas as naves nascem empilhadas no mesmo corpo celeste,
  que é o mesmo defeito que as vitrines tinham

A tripulação continua sendo a mesma, com os mesmos nomes, e isso é uma perda
real: em Space Haven a tripulação faz parte do que torna a partida sua. Trocar
os nomes é possível e fica para depois; entregar cópias com a mesma gente é
melhor do que manter cinco passos manuais entre a pessoa e o jogo.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from sgalaxy.graft import place_player_fleet, player_fleets
from sgalaxy.savefile import SaveFile

# Quantos corpos do sistema podem receber alguém, em ordem. O primeiro livre
# ganha. Não é sorteio: com sorteio, duas entradas ao mesmo tempo caem no mesmo
# lugar de vez em quando, e o defeito só aparece quando a sala enche.
MAX_TENTATIVAS = 40

# Onde uma nave pode ficar, em ordem de preferencia. Campo de asteroides
# primeiro porque e onde o jogo comeca uma partida: tem o que minerar por
# perto. A estrela esta fora da lista de proposito — a primeira versao parou
# a nave de alguem em cima de uma, porque "corpo celeste" inclui o sol.
DESTINOS = ("AsteroidField", "Moon", "Planet")


def player_ship(sf: SaveFile) -> ET.Element | None:
    """A nave de quem joga: a de mais tripulação, entre as da facção Player."""
    candidatas = [nave for _doc, nave in sf.ships()
                  if (nave.find("settings") is not None
                      and nave.find("settings").get("of") == "461")]
    if not candidatas:
        return None
    return max(candidatas, key=lambda s: len(s.findall(".//characters/c")))


def rename_ship(sf: SaveFile, nome: str) -> str | None:
    """Dá nome próprio à nave da cópia. Devolve o nome anterior."""
    nave = player_ship(sf)
    if nave is None:
        return None
    antes = nave.get("sname")
    nave.set("sname", nome[:40])
    return antes


def _fleet(sf: SaveFile):
    """A frota do jogador, o container dela e o corpo em que ela esta."""
    starmap = sf.main.find("starmap")
    if starmap is None:
        return None, None, None
    for frota, container, holder in player_fleets(starmap):
        return frota, container, holder
    return None, None, None


def _system_of(starmap: ET.Element, elemento: ET.Element):
    """Sobe a arvore ate o `<l systemId=...>` que contem este elemento."""
    pais = {filho: pai for pai in starmap.iter() for filho in pai}
    while elemento is not None and elemento.get("systemId") is None:
        elemento = pais.get(elemento)
    return elemento


def occupied(sf: SaveFile) -> set:
    """Onde ja ha gente, por coordenada. Serve para nao empilhar."""
    ocupados = set()
    starmap = sf.main.find("starmap")
    if starmap is None:
        return ocupados
    for frota in starmap.iter():
        if frota.tag in ("f", "fleet") and frota.get("x") and frota.get("y"):
            ocupados.add((frota.get("x"), frota.get("y")))
    return ocupados


def free_body(sf: SaveFile, evitar: set) -> tuple:
    """Um corpo do MESMO sistema que ainda nao tem ninguem.

    Mesmo sistema de proposito: a sala existe para as pessoas se encontrarem, e
    espalha-las pela galaxia faria a vitrine do vizinho nao aparecer para
    ninguem. Perto o bastante para negociar, longe o bastante para nao nascer
    dentro da nave de outro.

    O sistema sai da ARVORE, subindo a partir da frota, e nao das coordenadas
    dela. Procurar por coordenada acha o corpo de outro sistema que por acaso
    esta no mesmo ponto do mapa — foi o que a primeira versao fez, e ela movia
    a pessoa para um sistema onde ela nao estava.
    """
    frota, _cont, _holder = _fleet(sf)
    starmap = sf.main.find("starmap")
    if frota is None or starmap is None:
        return None, None
    sistema = _system_of(starmap, frota)
    if sistema is None:
        return None, None
    corpos = sistema.findall("bodies/l")[:MAX_TENTATIVAS]
    for tipo in DESTINOS:
        for corpo in corpos:
            if corpo.get("type") != tipo:
                continue
            if not (corpo.get("x") and corpo.get("y")):
                continue
            if (corpo.get("x"), corpo.get("y")) in evitar:
                continue
            return sistema, corpo
    return sistema, None


def personalise(sf: SaveFile, ship_name: str, evitar: set | None = None) -> dict:
    """Faz da cópia a partida desta pessoa. Não grava: quem chama decide.

    `evitar` são as coordenadas onde já há alguém, vindas do que a sala sabe.
    Sem elas, o único empilhamento que dá para evitar é com a própria origem.
    """
    relatorio = {"renamedFrom": rename_ship(sf, ship_name),
                 "shipName": ship_name, "moved": False, "at": None,
                 "warnings": []}

    frota, container, _holder = _fleet(sf)
    if frota is None:
        relatorio["warnings"].append(
            "this save has no player fleet, so there is nothing to place")
        return relatorio

    ocupados = set(evitar or ()) | occupied(sf)
    sistema, corpo = free_body(sf, ocupados)
    if corpo is None:
        relatorio["warnings"].append(
            "no free body in the starting system: this game begins where the "
            "room's founder began, and the two ships will sit on top of each "
            "other until one of them travels")
        return relatorio

    starmap = sf.main.find("starmap")
    posto = place_player_fleet(starmap, frota, corpo, sistema)
    # A copia foi para o destino; a original tem que sair, senao o save fica
    # com duas frotas de jogador e o jogo escolhe uma.
    if container is not None:
        container.remove(frota)
    relatorio["warnings"] += posto.pop("warnings", [])
    relatorio["moved"] = True
    relatorio["at"] = {"system": posto.get("system"), "x": posto.get("x"),
                       "y": posto.get("y"), "celeid": posto.get("toCeleid")}
    sf.mark_dirty(sf.main)
    sf.reindex()
    return relatorio
