"""
Monta a vitrine de um vizinho dentro do save de outra pessoa.

Vive aqui, e nao em `tools/`, pela mesma razao do enxerto: o servidor nao
importa de `tools/`, e esta e a operacao que escreve uma nave nova no save de
um jogador. Duas copias disso seria duas chances de corromper partida.

A DECISAO QUE MUDOU O DESENHO

O retrato NAO e uma copia da nave do vizinho. E uma vitrine montada sobre um
casco NPC **do proprio save de destino** (`--hull`), decidido depois do E3b: a
neblina so se sustenta se a nave de origem nunca foi explorada, e a nave de um
jogador sempre foi. Como efeito colateral bom, o casco vem da instalacao da
propria pessoa — nada da maquina de outro jogador atravessa — e o retrato cabe
em 166 KB em vez de 460.

O QUE ISTO FAZ, medido nos experimentos E3, E3b e E6:

    sid e entId novos, tirados de `masterData/@idCounter`
    `settings/@of` e `@owner` da faccao escolhida
    `<asi>` copiado de um NPC que ja existe no destino
    `<shipBank>` com estoque controlado
    fog, `unex` e `forceRoof` para o interior ficar fechado
    `<f>` numa frota, no corpo celeste onde o vizinho esta
    permissoes no `hostmap`, por faccao

O que NAO faz: economia. Fase 2 e o vizinho aparecer; fase 3 e ele negociar.
"""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy.savefile import (  # noqa: E402
    SaveError,
    SaveFile,
    _insert_child,
    _remove_child,
    serialize,
)

# --------------------------------------------------------------------------
# Faccoes
# --------------------------------------------------------------------------

# A faccao do jogador e 461 em *todo* save do mundo: o savegame nao guarda
# identidade nenhuma de jogador, entao "eu" e sempre esse id. Quem distingue um
# vizinho do outro na tela e o nome da nave, nao a faccao.
PLAYER_FACTION_ID = "461"
PLAYER_SIDE = "Player"

# Id da faccao -> nome do lado. Sao as duas metades da mesma identidade e o save
# pede as duas em lugares diferentes: `<ship>/<settings>` quer o id em `of` e o
# nome em `owner`, o `<shipBank>` quer o nome em `s`, e o `hostmap` casa pares
# por um dos dois. Sao identificadores tecnicos, nao conteudo do jogo: os nomes
# de exibicao ficam no jar do usuario e nao sao redistribuidos aqui.
FACTION_SIDES = {
    "461": "Player",
    "462": "Pirate",
    "463": "Merchant",
    "1690": "Military",
    "1691": "Slaver",
    "1692": "Android",
    "1693": "Cultist",
    "1694": "Civilian",
    "3896": "FactionLess1",
    "4144": "HavenFoundation",
    "4251": "FlamingSwords",
}

# Civis e o padrao porque num jogo novo o jogador comeca Friendly com eles, com
# relacao na casa dos 70 e as permissoes ligadas: e a faccao onde a unica coisa
# que precisa mudar no `hostmap` e o que a receita manda mudar.
DEFAULT_FACTION_ID = "1694"

# --------------------------------------------------------------------------
# Estrutura da nave
# --------------------------------------------------------------------------

# `fg` e a nevoa de uma celula; `0` e "nunca vista". Uma nave de NPC autentica
# transplantada com tudo isso continuou aberta — o interior nao e escondido
# pelos dados da nave, e sim pelo `hostmap`. Fica na receita porque e o estado
# correto de uma nave que o jogador nunca visitou, nao porque esconde algo.
FOG_ATTR = "fg"
FOG_UNSEEN = "0"

# `unex` = nave nao explorada, `forceRoof` = teto desenhado por cima, `fog` =
# nevoa ligada. Os tres na raiz `<ship>`.
#
# `fog` nao esta na receita da secao 2.5, e foi medido depois, em 12 naves de
# dois saves reais: TODA nave de NPC tem fog="true" e toda nave do jogador tem
# fog="false". A unica excecao encontrada foi uma nave Mercante com fog="false"
# — provavelmente ja abordada pelo jogador, o que confirma a leitura de que o
# atributo marca "esta nave ja foi explorada".
#
# Sem isso a nave injetada herda o fog="false" da nave de origem, que e a nave
# do dono e portanto sempre explorada — e o retrato nasce diferente de todo NPC
# autentico do save.
SHIP_HIDDEN_ATTRS = {"unex": "1", "forceRoof": "1", "fog": "true"}

# Atributos que apontam de volta para o `sid` da nave e portanto precisam
# acompanhar a renumeracao: `homeSid` liga uma craft atracada a nave-mae, `hsid`
# e a nave que um tripulante chama de casa. Sem isso a tripulacao copiada fica
# morando numa nave que so existe no save de origem.
#
# `hdsid` entrou por medicao, nao por documento. Ele mora no <ai> de cada
# tripulante, colado no `hsid`, e nas duas naves de save real onde aparece o
# valor e sempre o `sid` da propria nave (6 vezes numa, 1 na outra). O aviso da
# ferramenta o pegou justamente porque ele nao estava aqui.
#
# `shipId` e `ssid` entraram depois, e a medicao diz que sao diferentes dos
# outros: os dois guardam *qualquer* id de nave, nao so o da nave que os contem
# (ha `ssid=37` dentro de meia duzia de naves, e `shipId=4321` dentro da 1459).
# Entram assim mesmo porque a renumeracao so dispara quando o valor **e** o sid
# antigo desta nave, e nesse caso a leitura natural e auto-referencia.
#
# O risco residual e do modo vitrine, onde o casco original continua no mesmo
# save: um `ssid` que apontasse de proposito para ele passa a apontar para a
# copia. Preferimos isso ao contrario — um retrato cujos registros apontam para
# outra nave e um retrato quebrado.
SID_BACKREF_ATTRS = ("sid", "homeSid", "hsid", "hdsid", "shipId", "ssid")

# Onde um `<inv>` de armazem pendura, em oposicao aos buffers internos de
# maquina. So armazem e carga negociavel; buffer de maquina e trabalho em curso.
RACK_HOLDER_TAGS = ("feat", "storage")

# Uma pilha nova nasce parada: nada a caminho de entrar nem de sair.
STACK_DEFAULTS = {"onTheWayIn": "0", "onTheWayOut": "0"}

# --------------------------------------------------------------------------
# Banca de comercio
# --------------------------------------------------------------------------

# Molde do `<shipBank>`, calcado num exemplo real do jogo. `ca` sao os creditos
# disponiveis (e o teto do que a nave consegue comprar), `cr` os reservados,
# `slp`/`blp` as sementes de preco de venda e de compra, `spmd` o modo de preco.
# Os tres ultimos vem do exemplo sem que saibamos o que significam: sao
# copiados, nao inventados.
SHIP_BANK_DEFAULTS = {"cr": "0", "slp": "10066", "blp": "9891", "spmd": "2"}

# Creditos padrao da banca. Numero redondo de proposito: o E3 pergunta se o jogo
# respeita o `ca` como limite de compra, e a resposta se le no diff a olho nu se
# o valor de partida for obvio.
DEFAULT_SHIP_CREDITS = "5000"

# --------------------------------------------------------------------------
# Frota no mapa estelar
# --------------------------------------------------------------------------

# O conjunto minimo de um `<f>` de NPC, usado so quando o destino nao tem
# nenhuma frota de NPC para servir de molde. `isPlayer` e o que separa a frota
# do jogador das outras.
FLEET_BASE_ATTRS = {"isPlayer": "false"}

# A entrada `<l>` de `<createdShips>` que amarra a frota a nave concreta.
# Transcrita de um exemplo real; os campos de bicho e de robo vem zerados porque
# um retrato de vizinho nao tem infestacao nenhuma.
CREATED_SHIP_DEFAULTS = {
    "created": "true",
    "station": "false",
    "shipDamagedNoFTL": "false",
    "cryoCrew": "0",
    "monsters": "0",
    "bigMonsters": "0",
    "hives": "0",
    "infesters": "0",
    "flybots": "0",
    "walkers": "0",
    "roboBase": "0",
    "derelict": "false",
    "addLoot": "false",
    "inHyper": "false",
}

# O `<fleets>` de um corpo celeste vai entre `<stuff>` e `<info>`. Corpo que
# nunca recebeu ninguem nao tem esse no, e criar na posicao errada e a diferenca
# entre o jogo aceitar e o jogo ignorar.
FLEETS_BEFORE_TAG = "info"
FLEETS_AFTER_TAG = "stuff"

# --------------------------------------------------------------------------
# Permissoes entre faccoes
# --------------------------------------------------------------------------

# O painel de controle do servidor sobre o que um jogador pode fazer com o
# retrato do outro. Comerciar sim; ver o interior e subir a bordo nao — o porao
# do vizinho nao e assunto de quem esta comprando dele.
PORTRAIT_PERMISSIONS = {
    "accessTrade": "true",
    "accessVision": "false",
    "accessShip": "false",
}

# O que o `hostmap` guarda por par de faccoes e que so mostramos, nunca
# alteramos: mexer na relacao muda o comportamento da IA muito alem do comercio.
HOSTMAP_CONTEXT_ATTRS = ("stance", "relationship", "patience")


# --------------------------------------------------------------------------
# Utilidades de arvore
# --------------------------------------------------------------------------


def parents_of(root: ET.Element) -> dict[int, ET.Element]:
    """Mapa filho -> pai de uma subarvore, por identidade do objeto.

    O ElementTree nao guarda o pai de um no. O SaveFile mantem esse indice para
    os documentos que carregou, mas as funcoes daqui trabalham em arvores
    soltas (uma nave recem-copiada, um pedaco de starmap) e precisam do proprio.
    """
    out: dict[int, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            out[id(child)] = parent
    return out


def reindent(el: ET.Element, prefix: str) -> None:
    """Indenta uma subarvore recem-montada no estilo do jogo (tabs).

    `prefix` e a quebra de linha mais os tabs que precedem `el` — exatamente o
    que o `_insert_child` do savefile deixa em `parent.text`. So mexe em espaco
    em branco: no que tem texto de verdade fica intocado, porque reindentar
    conteudo alheio destroi dado.
    """
    if not len(el) or "\n" not in prefix:
        return
    if el.text is not None and el.text.strip():
        return
    inner = prefix + "\t"
    el.text = inner
    for child in el:
        if child.tail is None or not child.tail.strip():
            child.tail = inner
        reindent(child, inner)
    if el[-1].tail is None or not el[-1].tail.strip():
        el[-1].tail = prefix


def attach(parent: ET.Element, child: ET.Element, index: int | None = None) -> None:
    """Pendura um no novo preservando a indentacao dos irmaos."""
    _insert_child(parent, child, index)
    reindent(child, parent.text or "")


def clear_children(parent: ET.Element, tag: str | None = None) -> int:
    """Esvazia um no sem estragar a indentacao de quem fica."""
    removed = 0
    for child in list(parent):
        if tag is None or child.tag == tag:
            _remove_child(parent, child)
            removed += 1
    return removed


# --------------------------------------------------------------------------
# Faccoes
# --------------------------------------------------------------------------


def resolve_faction(spec: str) -> tuple[str, str]:
    """Aceita id (`1694`) ou nome do lado (`Civilian`) e devolve os dois."""
    spec = (spec or "").strip()
    if not spec:
        raise SaveError("faccao vazia; use um id (1694) ou um nome de lado (Civilian)")
    if spec in FACTION_SIDES:
        faction_id, side = spec, FACTION_SIDES[spec]
    else:
        match = [(k, v) for k, v in FACTION_SIDES.items() if v.lower() == spec.lower()]
        if not match:
            known = ", ".join(f"{k}={v}" for k, v in sorted(FACTION_SIDES.items()))
            raise SaveError(f"facção desconhecida: {spec!r}. Conhecidas: {known}")
        faction_id, side = match[0]
    if faction_id == PLAYER_FACTION_ID:
        raise SaveError(
            "a facção do jogador (461/Player) não serve para um retrato de vizinho: "
            "o jogo entregaria a nave inteira ao jogador em vez de tratá-la como NPC"
        )
    return faction_id, side


def faction_tokens(faction_id: str, side: str) -> set[str]:
    """Como uma faccao pode aparecer escrita numa linha do `hostmap`.

    Nao esta verificado se `s1`/`s2` guardam o id ou o nome do lado, entao
    aceitamos os dois em vez de apostar num.
    """
    return {faction_id, side, side.lower(), side.upper()}


# --------------------------------------------------------------------------
# Localizar coisas nos saves
# --------------------------------------------------------------------------


def live_npc_ships(sf: SaveFile) -> list[ET.Element]:
    """Naves NPC VIVAS do proprio save, da menor para a maior.

    POR QUE NAO UM CASCO NAO EXPLORADO

    Porque casco nao explorado e, no jogo, a definicao de destroco: `fog=true`,
    `unex=1` e ninguem a bordo. Uma vitrine montada em cima disso aparece como
    "Derelict (Unexplored)" — e o problema nao e o rotulo, e que destroco se
    reclama e se desmonta. A loja de outro jogador nao pode ser desmontavel.

    Medido no save de um jogador: `CNHS LIGHTBINDER` tem exatamente os mesmos
    sinalizadores de nevoa e cinco tripulantes, e e uma nave cultista viva. A
    diferenca entre viva e sucata e a tripulacao.

    A EXIGENCIA DE NEVOA CADUCOU

    Ela veio do E3b (`findings.md` item 10), de quando o retrato era **copia da
    nave real do vizinho**: a nevoa escondia o layout dele. Hoje o molde sai do
    save de DESTINO, entao nao ha nada privado para esconder — a restricao
    sobreviveu ao motivo dela. O que continua valendo do item 10 e o resto: o
    molde vem da instalacao da propria pessoa, entao nada do jogo e
    redistribuido e nada da maquina de outro jogador atravessa.

    Menor primeiro porque cada vitrine entra inteira no save de quem recebe, e
    numa sala povoada isso se soma.
    """
    out = []
    for _doc, ship in sf.ships():
        settings = ship.find("settings")
        if settings is None or settings.get("owner") in (None, "Player"):
            continue
        if not crew_members(ship):
            continue
        out.append((len(serialize(ship)), ship))
    out.sort(key=lambda pair: pair[0])
    return [ship for _size, ship in out]


def unexplored_hulls(sf: SaveFile) -> list[ET.Element]:
    """Cascos do proprio save que servem de vitrine, do menor para o maior.

    O retrato e uma loja montada sobre um casco de NPC, nao uma copia da nave do
    vizinho — decisao tomada depois do E3b (secao 2.5, `findings.md` item 10). O
    motivo e a nevoa: ela so se sustenta se a nave de origem nunca foi
    explorada, e a nave de um jogador e sempre explorada.

    O casco sai de dentro do save de destino de proposito. Alem de garantir que
    e uma nave que aquele jogador ja tem, respeita a regra da secao 2.13: nada
    de conteudo do jogo e redistribuido, porque nada sai da instalacao dele.

    Menor primeiro porque a vitrine nao precisa ser grande, e cada retrato entra
    inteiro no save de todo vizinho que estiver no mesmo setor.
    """
    out = []
    for _doc, ship in sf.ships():
        settings = ship.find("settings")
        if settings is None or settings.get("owner") in (None, "Player"):
            continue
        if ship.get("fog") != "true" or ship.get("unex") != "1":
            continue
        # Nevoa de verdade, nao so o atributo: se as celulas ja foram reveladas,
        # o jogo vai tratar como explorada e o retrato nasce aberto.
        cells = [e for e in ship.iter("e") if e.get("fg") is not None]
        if not cells or any(e.get("fg") != "0" for e in cells):
            continue
        out.append((len(list(ship.iter("e"))), ship))
    return [ship for _n, ship in sorted(out, key=lambda p: p[0])]


def find_ship(sf: SaveFile, sid: str | None = None, name: str | None = None) -> ET.Element:
    """Acha uma nave por `sid` ou por nome, com erro que lista as candidatas."""
    ships = [ship for _doc, ship in sf.ships()]
    if not ships:
        raise SaveError(f"{sf.path}: este save não tem nave nenhuma")

    if sid is not None:
        found = [s for s in ships if s.get("sid") == str(sid)]
        if not found:
            raise SaveError(f"nave sid={sid} não existe neste save. {describe_ships(ships)}")
        return found[0]

    if name is not None:
        needle = name.strip().lower()
        found = [s for s in ships if (s.get("sname") or "").strip().lower() == needle]
        if not found:
            found = [s for s in ships if needle in (s.get("sname") or "").lower()]
        if not found:
            raise SaveError(f"nenhuma nave com nome {name!r}. {describe_ships(ships)}")
        if len(found) > 1:
            raise SaveError(
                f"{len(found)} naves casam com {name!r}; use --sid. {describe_ships(found)}"
            )
        return found[0]

    raise SaveError("escolha a nave de origem com --sid ou --ship-name. "
                    + describe_ships(ships))


def describe_ships(ships: list[ET.Element], limit: int = 12) -> str:
    """Uma linha por nave, para caber numa mensagem de erro."""
    rows = [f"sid={s.get('sid')} {s.get('sname') or '(sem nome)'!r} "
            f"tripulação={crew_count(s)}" for s in ships[:limit]]
    extra = f" … e mais {len(ships) - limit}" if len(ships) > limit else ""
    return "Naves disponíveis: " + "; ".join(rows) + extra


def crew_members(ship: ET.Element) -> list[ET.Element]:
    """Tripulantes da nave, inclusive quem esta pilotando uma craft atracada.

    Quem esta numa craft nao aparece na lista de tripulantes da nave-mae, mas o
    `entId` dele sai do mesmo contador global e viaja junto na copia.
    """
    return [c for holder in ship.iter("characters") for c in holder.findall("c")]


def crew_count(ship: ET.Element) -> int:
    return len(crew_members(ship))


def find_node_donor(sf: SaveFile, tag: str) -> tuple[ET.Element, ET.Element] | None:
    """Acha um `<asi>` ou `<shipBank>` numa nave de NPC do save.

    Preferimos uma nave que declare faccao diferente da do jogador; se nenhuma
    declarar, servem as que simplesmente tem o no — ter `<asi>` ja e assinatura
    de nave de NPC, porque a do jogador nao tem.
    """
    fallback = None
    for _doc, ship in sf.ships():
        node = ship.find(tag)
        if node is None:
            continue
        settings = ship.find("settings")
        owner = settings.get("of") if settings is not None else None
        if owner is not None and owner != PLAYER_FACTION_ID:
            return ship, node
        if fallback is None:
            fallback = (ship, node)
    return fallback


def find_player_fleet(sf: SaveFile) -> tuple[ET.Element | None, ET.Element | None]:
    """O `<f isPlayer="true">` e o corpo celeste que o abriga."""
    starmap = sf.main.find("starmap")
    if starmap is None:
        return None, None
    parents = parents_of(starmap)
    for fleets in starmap.iter("fleets"):
        for f in fleets.findall("f"):
            if f.get("isPlayer") == "true":
                return parents.get(id(fleets)), f
    return None, None


def find_npc_fleet(sf: SaveFile) -> ET.Element | None:
    """Uma frota de NPC qualquer, para servir de molde estrutural."""
    starmap = sf.main.find("starmap")
    if starmap is None:
        return None
    for fleets in starmap.iter("fleets"):
        for f in fleets.findall("f"):
            if f.get("isPlayer") != "true" and f.find("createdShips") is not None:
                return f
    return None


def locate_body(sf: SaveFile, celeid: str | None = None,
                system_id: str | None = None,
                at: tuple | None = None) -> tuple[ET.Element, dict]:
    """O corpo celeste onde o jogador esta, com o que foi conferido no caminho.

    Um corpo celeste tem DOIS ids, e confundi-los e o erro caro deste projeto:

    - `@id` e local ao save, tirado de `starmap/@objectIdCounter`. E para ele
      que `starmap/@pa` aponta. Dois jogadores da mesma sala tem numeros
      diferentes para o mesmo lugar.
    - `@celeid` vem da seed. E igual em todo save gerado com a mesma seed, e
      por isso e o unico vocabulario que o servidor pode usar para dizer "o
      vizinho esta aqui".

    Medido em save real 1.0.4: `@pa=226` casa com `<l id="226" celeid="1689">`,
    e nao existe corpo nenhum com `celeid=226`. `@sys`, esse sim, e o
    `systemId` direto.

    E HA UM TERCEIRO, que so foi medido depois: `celeid` nao identifica UM
    lugar, identifica um TIPO de lugar. Num save real, 123 corpos carregam 11
    valores de `celeid`, e todo campo de asteroide e `celeid="0"`
    (`docs/findings.md`, item 24). Pedir por `celeid` num sistema com dois
    campos de asteroide entrega um dos dois, ao acaso.

    Por isso existe `at=(x, y)`: `(systemId, x, y)` sai da seed, nao se move, e
    deu 123 chaves distintas para 123 corpos em todo save conferido. E a unica
    forma segura de o servidor dizer "o vizinho esta AQUI", e tem precedencia
    sobre `celeid`, que fica para uso manual na linha de comando.

    A autoridade sobre onde o JOGADOR esta e a frota `<f isPlayer="true">`, que
    e o dado mais direto; `@pa` entra como conferencia e vira aviso se divergir.
    """
    starmap = sf.main.find("starmap")
    if starmap is None:
        raise SaveError("o save de destino não tem <starmap>")

    info: dict = {"warnings": []}
    target_sys = system_id if system_id is not None else starmap.get("sys")
    info["system"] = target_sys

    systems = starmap.findall("systems/l")
    if not systems:
        raise SaveError("o <starmap> do destino não tem <systems>")
    scope = [s for s in systems if s.get("systemId") == str(target_sys)]
    if not scope:
        if system_id is not None:
            raise SaveError(f"não existe sistema systemId={system_id} neste save")
        info["warnings"].append(
            f"nenhum sistema com systemId={target_sys!r}; procurando na "
            f"galáxia inteira"
        )
        scope = systems

    host, fleet = find_player_fleet(sf)
    info["playerFleet"] = fleet.get("id") if fleet is not None else None

    body = None
    if at is not None:
        alvo = (str(at[0]), str(at[1]))
        found = [el for system in scope for el in system.iter()
                 if el.get("celeid") is not None
                 and (el.get("x"), el.get("y")) == alvo]
        if not found:
            raise SaveError(
                f"não achei corpo celeste em ({alvo[0]}, {alvo[1]}) "
                f"no sistema {target_sys}")
        body = found[0]
    elif celeid is not None:
        found = [el for system in scope for el in system.iter()
                 if el.get("celeid") == str(celeid)]
        if not found:
            raise SaveError(
                f"não achei corpo celeste com celeid={celeid} "
                f"(sistema {target_sys})"
            )
        if len(found) > 1:
            info["warnings"].append(
                f"{len(found)} nós com celeid={celeid}; "
                f"usando o primeiro (<{found[0].tag}>)"
            )
        body = found[0]
    elif host is not None:
        # O lugar mais confiavel: onde a frota do jogador realmente esta.
        body = host
    else:
        # Sem frota, resta o `@pa` — que casa com `@id`, nao com `@celeid`.
        pa = starmap.get("pa")
        if pa is None:
            raise SaveError(
                "não achei a frota do jogador nem starmap/@pa; "
                "use --body para dizer o corpo celeste (por celeid)")
        found = [el for system in scope for el in system.iter()
                 if el.get("id") == str(pa) and el.get("celeid") is not None]
        if not found:
            raise SaveError(
                f"starmap/@pa={pa} não casa com nenhum corpo celeste "
                f"(atributo @id) no sistema {target_sys}; use --body")
        body = found[0]
        info["warnings"].append(
            "não achei frota <f isPlayer=\"true\">; usei starmap/@pa")

    info["celeid"] = body.get("celeid")
    info["bodyId"] = body.get("id")
    info["bodyTag"] = body.tag

    # Conferencia: `@pa` deveria apontar para o `@id` local deste corpo.
    pa = starmap.get("pa")
    if pa is not None and body.get("id") is not None and pa != body.get("id"):
        info["warnings"].append(
            f"starmap/@pa={pa} não é o @id={body.get('id')} do corpo escolhido "
            f"(celeid={body.get('celeid')}); confira se o destino é mesmo o "
            f"setor onde o jogador está"
        )
    if fleet is None:
        info["warnings"].append(
            "não achei nenhuma frota <f isPlayer=\"true\"> no mapa estelar; "
            "não dá para conferir onde o jogador está"
        )
    elif host is not None and host is not body:
        info["warnings"].append(
            f"a frota do jogador está em celeid={host.get('celeid')}, não em "
            f"celeid={body.get('celeid')} — a nave injetada apareceria em outro "
            f"setor. Use --body {host.get('celeid')} se for o caso"
        )
    return body, info


def get_or_create_fleets(body: ET.Element) -> tuple[ET.Element, bool]:
    """O `<fleets>` do corpo celeste, criado entre `<stuff>` e `<info>` se faltar."""
    fleets = body.find("fleets")
    if fleets is not None:
        return fleets, False
    tags = [child.tag for child in body]
    if FLEETS_BEFORE_TAG in tags:
        index = tags.index(FLEETS_BEFORE_TAG)
    elif FLEETS_AFTER_TAG in tags:
        index = tags.index(FLEETS_AFTER_TAG) + 1
    else:
        index = None
    fleets = ET.Element("fleets")
    attach(body, fleets, index)
    return fleets, True


def next_starmap_object_id(sf: SaveFile) -> str:
    """Reserva um id do contador de objetos do mapa estelar.

    Frotas e objetos do mapa nao saem do `masterData/@idCounter`: tem contador
    proprio em `starmap/@objectIdCounter`.
    """
    starmap = sf.main.find("starmap")
    current = starmap.get("objectIdCounter") if starmap is not None else None
    if current is None or not str(current).isdigit():
        raise SaveError("este save não tem starmap/@objectIdCounter")
    starmap.set("objectIdCounter", str(int(current) + 1))
    sf.dirty = True
    return str(current)


# --------------------------------------------------------------------------
# Montagem da nave
# --------------------------------------------------------------------------


def renumber_ship(ship: ET.Element, new_sid: str, new_ent_ids: list[str]) -> dict:
    """Troca o `sid` da nave e os `entId` da tripulacao, e conserta as amarras.

    Os ids internos (`id`, `eid`) ficam como estao de proposito: sao locais a
    nave e nao colidem com os de nenhuma outra. Ja o `sid` antigo aparece
    referenciado dentro da propria nave — craft atracada, casa de tripulante — e
    esses ponteiros tem que acompanhar a mudanca.
    """
    old_sid = ship.get("sid")
    report: dict = {"oldSid": old_sid, "sid": new_sid, "backrefs": 0, "dangling": []}

    for el in ship.iter():
        for attr in SID_BACKREF_ATTRS:
            if old_sid is not None and el.get(attr) == old_sid:
                el.set(attr, new_sid)
                report["backrefs"] += 1
    ship.set("sid", new_sid)

    # Qualquer outro atributo que ainda aponte para o sid antigo e um ponteiro
    # que nao sabiamos existir. Nao adivinhamos o significado: reportamos.
    #
    # So que "valor igual ao sid antigo" e uma peneira furada quando o sid e um
    # numero pequeno: com sid=2 numa nave real deu 402 acertos, quase todos
    # coincidencia (<e ext="2"> e tipo de extensao, nao referencia a nave). Um
    # aviso com 400 falsos positivos e um aviso que ninguem le, entao os
    # suspeitos de verdade — atributo com cara de referencia a nave — saem
    # nomeados, e o resto vira contagem.
    if old_sid is not None:
        others = 0
        for el in ship.iter():
            for attr, value in el.attrib.items():
                if value != old_sid or attr in SID_BACKREF_ATTRS:
                    continue
                # `endswith("sid")` pega sid/homeSid/hsid/hdsid; `startswith`
                # pega shipId e parentes. Procurar "ship" solto casava
                # `friendship`, que e valor de amizade e apareceu com o valor
                # certo por coincidencia num teste real.
                low = attr.lower()
                if low.endswith("sid") or low.startswith("ship"):
                    report["dangling"].append(f"<{el.tag} {attr}={value}>")
                else:
                    others += 1
        report["coincidences"] = others

    crew = crew_members(ship)
    if len(new_ent_ids) != len(crew):
        raise SaveError(
            f"reservados {len(new_ent_ids)} entId para {len(crew)} tripulantes; "
            "isto é bug da ferramenta, não do save"
        )
    for member, ent_id in zip(crew, new_ent_ids):
        member.set("entId", ent_id)
    report["crew"] = len(crew)

    # A secao 2.5 manda renumerar so a tripulacao. Equipamento, implante e
    # objeto tambem carregam entId do contador global; contamos quantos ficaram
    # com o numero de origem para a exposicao a colisao nao ficar invisivel.
    crew_ids = set(new_ent_ids)
    report["otherEntIds"] = sum(
        1 for el in ship.iter()
        if el.get("entId") is not None and el.get("entId") not in crew_ids
    )
    return report


def set_owner(ship: ET.Element, faction_id: str, side: str) -> dict:
    """`<ship>/<settings>` com `of` e `owner` — e isso que decide de quem a nave e."""
    settings = ship.find("settings")
    created = settings is None
    if created:
        settings = ET.Element("settings")
        attach(ship, settings)
    before = {"of": settings.get("of"), "owner": settings.get("owner")}
    settings.set("of", faction_id)
    settings.set("owner", side)
    return {"created": created, "before": before, "of": faction_id, "owner": side}


def set_crew_side(ship: ET.Element, side: str | None) -> dict:
    """Marca a tripulacao como sendo da faccao do retrato.

    Nao esta na receita 2.5, e a secao 1.7 garante que `of`/`owner` mandam mesmo
    com tripulacao de outra faccao. Mas o caso testado foi tripulacao de NPC em
    nave do jogador, nunca o inverso, e uma nave de Civis tripulada por `Player`
    e uma combinacao que o jogo nunca produz sozinho. `--crew-side keep` desliga.
    """
    if side is None:
        return {"applied": False, "changed": 0}
    changed = 0
    for member in crew_members(ship):
        if member.get("side") != side:
            member.set("side", side)
            changed += 1
    return {"applied": True, "side": side, "changed": changed}


def hide_interior(ship: ET.Element) -> dict:
    """`fg="0"` em cada celula, mais `unex` e `forceRoof` na raiz.

    E o estado de uma nave que o jogador nunca visitou. Nao esconde nada
    sozinho: quem fecha o interior de verdade e o `hostmap`.
    """
    cells = changed = 0
    for el in ship.iter():
        if el.get(FOG_ATTR) is not None:
            cells += 1
            if el.get(FOG_ATTR) != FOG_UNSEEN:
                el.set(FOG_ATTR, FOG_UNSEEN)
                changed += 1
    for attr, value in SHIP_HIDDEN_ATTRS.items():
        ship.set(attr, value)
    return {"cells": cells, "fogged": changed, "shipAttrs": dict(SHIP_HIDDEN_ATTRS)}


def build_ship_bank(side: str, credits: str, template: ET.Element | None) -> ET.Element:
    """O `<shipBank>`: sem ele a nave nao tem com que comerciar.

    Com um molde de NPC do proprio save herdamos as regras de preco reais e so
    trocamos o lado e os creditos. Sem molde, montamos com os valores do exemplo
    documentado — que funcionam, mas cujo significado exato nao conhecemos.
    """
    if template is not None:
        bank = copy.deepcopy(template)
        bank.tail = None
    else:
        bank = ET.Element("shipBank", dict(SHIP_BANK_DEFAULTS))
        ET.SubElement(bank, "markup")
        ET.SubElement(bank, "discount")
    bank.set("s", side)
    bank.set("ca", str(credits))
    return bank


def parse_stock(spec: str | None) -> list[tuple[str, str]]:
    """`"2053:40,1002:10"` -> [("2053","40"), ("1002","10")]."""
    if not spec:
        return []
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        ident, sep, amount = chunk.partition(":")
        ident, amount = ident.strip(), amount.strip()
        if not sep or not ident.isdigit() or not amount.isdigit():
            raise SaveError(
                f"estoque inválido: {chunk!r}. Use ELEMENTO:QUANTIDADE, "
                "por exemplo 2053:40,1002:10"
            )
        out.append((ident, amount))
    return out


def ship_racks(ship: ET.Element) -> list[ET.Element]:
    """Os `<inv>` de armazem da nave — sem os buffers internos de maquina."""
    parents = parents_of(ship)
    return [inv for inv in ship.iter("inv")
            if (holder := parents.get(id(inv))) is not None
            and holder.tag in RACK_HOLDER_TAGS]


def set_stock(ship: ET.Element, stock: list[tuple[str, str]], clear: bool = True) -> dict:
    """Deixa no porao exatamente o que foi consignado, e nada mais.

    Banca de feira, nao porao: o retrato so expoe o que o dono escolheu expor,
    entao o padrao e esvaziar os armazens antes de encher. Com `--keep-cargo` a
    carga original viaja junto, o que serve para inspecionar mas nao para
    entregar a um vizinho.
    """
    racks = ship_racks(ship)
    report: dict = {"racks": len(racks), "used": 0, "cleared": 0,
                    "placed": [], "warnings": []}
    if not racks:
        report["warnings"].append(
            "esta nave não tem nenhum <inv> de armazém (<feat>/<storage>): "
            "não há onde colocar estoque, e ela não terá o que vender"
        )
        return report

    if clear:
        for rack in racks:
            report["cleared"] += clear_children(rack, "s")

    if not stock:
        return report

    # Um recurso por armazem, girando entre eles. A primeira versao empilhava
    # tudo no racks[0], e no E3 o jogo ofertou 26 de 30 Placas de aco que
    # estavam la — nunca descobrimos por que, e a concentracao e a suspeita
    # obvia. Espalhar tambem e o que uma nave de verdade parece: as autenticas
    # do save tem carga distribuida, nao amontoada num movel so.
    #
    # Nao ha teto por armazem aqui de proposito. Chegamos a supor 66 e a medicao
    # desmentiu: armazens autenticos guardam 1.530, 514, 278 unidades. Inventar
    # um limite que nao existe seria pior do que nao ter nenhum.
    by_rack: dict[int, list] = {}
    for i, (ident, amount) in enumerate(stock):
        rack = racks[i % len(racks)]
        existing = {s.get("elementaryId"): s for s in rack.findall("s")}
        stack = existing.get(ident)
        if stack is not None:
            stack.set("inStorage", amount)
        else:
            stack = ET.Element("s", {"elementaryId": ident, "inStorage": amount,
                                     **STACK_DEFAULTS})
            attach(rack, stack)
        by_rack.setdefault(i % len(racks), []).append(ident)
        report["placed"].append({"element": ident, "amount": amount,
                                 "rack": i % len(racks)})

    report["used"] = len(by_rack)
    if len(stock) > len(racks):
        report["warnings"].append(
            f"{len(stock)} recursos consignados para {len(racks)} armazém(ns): "
            f"alguns dividem móvel. Se o vizinho vir menos do que foi ofertado, "
            f"é o primeiro lugar para olhar"
        )
    return report


def read_stock(ship: ET.Element) -> dict:
    """O que sobrou nas prateleiras da vitrine.

    O par de leitura de `set_stock`. No `checkout` sabemos o que foi posto; so
    isto diz o que ficou, e a diferenca entre os dois e a venda.
    """
    total: dict = {}
    for rack in ship_racks(ship):
        for stack in rack.findall("s"):
            ident = stack.get("elementaryId")
            if ident is None:
                continue
            try:
                qty = int(stack.get("inStorage") or 0)
            except (TypeError, ValueError):
                continue
            total[ident] = total.get(ident, 0) + qty
    return {r: q for r, q in total.items() if q}


def bank_credits(ship: ET.Element) -> int | None:
    """Os creditos da banca da vitrine, ou None se ela nao tem banca.

    E o `ca` do `<shipBank>`. Quem compra paga a nave, entao este numero sobe
    exatamente no valor da venda — e o jogo faz o preco, o que e melhor do que
    nos inventarmos uma tabela.
    """
    bank = ship.find("shipBank")
    if bank is None:
        return None
    try:
        return int(bank.get("ca") or 0)
    except (TypeError, ValueError):
        return None


def find_by_sid(sf: SaveFile, sid: str) -> ET.Element | None:
    for _doc, ship in sf.ships():
        if ship.get("sid") == str(sid):
            return ship
    return None


def ensure_ai(ship: ET.Element, donor: ET.Element | None) -> dict:
    """Garante um `<asi>` na nave: e a IA dela (radio, saudacao, combate)."""
    existing = ship.find("asi")
    if existing is not None:
        return {"source": "própria", "present": True}
    if donor is None:
        return {
            "source": None,
            "present": False,
            "warning": "o save de destino não tem nenhuma nave de NPC com <asi> "
                       "para copiar; a nave vai entrar sem IA de bordo, sem rádio "
                       "e sem postura de combate. Injete-a num setor que já tenha "
                       "uma nave de NPC, ou copie o <asi> à mão",
        }
    node = copy.deepcopy(donor)
    node.tail = None
    attach(ship, node)
    return {"source": "doador", "present": True}


# --------------------------------------------------------------------------
# Frota e permissoes
# --------------------------------------------------------------------------


def build_fleet(fleet_id: str, faction_id: str, ship: ET.Element,
                template: ET.Element | None = None,
                position: ET.Element | None = None) -> ET.Element:
    """A frota `<f>` que registra a nave no mapa estelar.

    Com um molde de frota de NPC do proprio save herdamos os atributos que nao
    conhecemos; a posicao sai da frota do jogador, porque o retrato tem que
    estar no mesmo setor que ele para ser visto.
    """
    entry_template = None
    if template is not None:
        fleet = copy.deepcopy(template)
        fleet.tail = None
        created = fleet.find("createdShips")
        if created is not None:
            entry_template = created.find("l")
            clear_children(created)
        else:
            created = ET.Element("createdShips")
            attach(fleet, created)
    else:
        fleet = ET.Element("f", dict(FLEET_BASE_ATTRS))
        created = ET.SubElement(fleet, "createdShips")

    fleet.set("id", fleet_id)
    fleet.set("factionId", faction_id)
    fleet.set("isPlayer", "false")
    if position is not None:
        for attr in ("x", "y", "sys", "pa"):
            if position.get(attr) is not None:
                fleet.set(attr, position.get(attr))

    if entry_template is not None:
        entry = copy.deepcopy(entry_template)
        entry.tail = None
    else:
        entry = ET.Element("l")
    # Do molde vale o que ele traz; os padroes so preenchem o que faltar, porque
    # o molde e um exemplo real e nossos valores sao transcricao de documento.
    for key, value in CREATED_SHIP_DEFAULTS.items():
        entry.attrib.setdefault(key, value)
    # Estes dois nao sao negociaveis: a nave existe (`created`) e nao e destroço
    # (`derelict`), senao ela vira sucata reivindicável em vez de vizinho.
    entry.set("created", "true")
    entry.set("derelict", "false")
    # A seed sai do proprio sid: unica dentro do save e reproduzivel, o que
    # importa para um servidor que precisa montar o mesmo retrato duas vezes.
    entry.set("seed", ship.get("sid"))
    entry.set("createdShipId", ship.get("sid"))
    entry.set("crew", str(crew_count(ship)))
    entry.set("station", "true" if ship.get("sta") == "1" else "false")
    for attr in ("sx", "sy"):
        if ship.get(attr) is not None:
            entry.set(attr, ship.get(attr))
    attach(created, entry)
    return fleet


def apply_hostmap_permissions(sf: SaveFile, faction_id: str, side: str,
                              permissions: dict[str, str] | None = None) -> dict:
    """Liga o comercio e fecha a visao e o embarque, no par jogador-faccao.

    Esta tabela e o painel de controle do servidor: o interior de uma nave
    alheia nao e escondido pelos dados dela, e sim aqui.
    """
    permissions = permissions or PORTRAIT_PERMISSIONS
    rows = sf.main.findall("hostmap/map/l")
    report: dict = {"rows": 0, "changed": [], "context": None, "warnings": []}
    if not rows:
        report["warnings"].append(
            "o save de destino não tem <hostmap>/<map>/<l>: as permissões entre "
            "facções não puderam ser ajustadas e o jogo vai usar o que já estiver lá"
        )
        return report

    mine = faction_tokens(PLAYER_FACTION_ID, PLAYER_SIDE)
    theirs = faction_tokens(faction_id, side)
    for row in rows:
        s1, s2 = row.get("s1"), row.get("s2")
        if not ((s1 in mine and s2 in theirs) or (s1 in theirs and s2 in mine)):
            continue
        report["rows"] += 1
        report["context"] = {k: row.get(k) for k in HOSTMAP_CONTEXT_ATTRS
                             if row.get(k) is not None}
        for attr, value in permissions.items():
            if row.get(attr) != value:
                report["changed"].append({"attr": attr, "from": row.get(attr), "to": value})
            row.set(attr, value)
        sf.dirty = True

    if not report["rows"]:
        seen = sorted({f"{r.get('s1')}/{r.get('s2')}" for r in rows})
        report["warnings"].append(
            f"nenhuma linha do <hostmap> casa o par {PLAYER_SIDE}/{side}; "
            f"as permissões ficaram como estavam. Pares existentes: {', '.join(seen)}"
        )
    return report


# --------------------------------------------------------------------------
# A receita inteira
# --------------------------------------------------------------------------


# Onde uma nave pode ficar DENTRO do setor. Medido em dezesseis saves: `ox` vai
# de -7488 a 7539 e os valores caem numa grade de 1248. Duas naves de 56
# celulas convivem a 2496 de distancia, entao 3744 e uma folga confortavel.
PASSO_SETOR = 1248
FOLGA_SETOR = 3744
VAGAS_SETOR = (-7488, -3744, 0, 3744, 7488)


def sector_slot(dest: SaveFile, preferido: int | None = None) -> int | None:
    """Um `ox` livre no setor, longe das naves que ja estao la.

    POR QUE ISTO EXISTE

    A vitrine e uma copia, e a copia trazia o `ox`/`oy` da nave original: ela
    reaparecia na coordenada que o dono ocupava no setor DELE. Relatado duas
    vezes por quem jogou — uma vez quase em cima da propria nave, outra parada
    onde o vizinho tinha estado num salto anterior.

    O hyperjump e onde isso fica visivel: o jogo mostra a grade do setor e a
    pessoa escolhe onde encostar. A nave de outra pessoa aparecer num ponto que
    ela nao escolheu, e que o dono nem ocupa mais, e ruido no unico momento em
    que a grade importa.

    Devolve None quando nao ha vaga, e quem chama mantem o que veio: uma
    vitrine no lugar errado ainda e melhor que nenhuma.
    """
    # SO AS NAVES DO SETOR CARREGADO. As que o jogo guardou em `ships/shipNNN`
    # estao em outro lugar da galaxia, e conta-las lotava a grade: num save de
    # verdade sao vinte naves espalhadas por toda a faixa, e nenhuma vaga
    # sobrava. As do setor sao as que estao no `<ships>` do `game`.
    portador = dest.main.find("ships")
    ocupados = [int(nave.get("ox")) for nave in (portador if portador is not None else [])
                if nave.tag == "ship" and nave.get("ox") is not None]

    def livre(x):
        return all(abs(x - usado) >= FOLGA_SETOR for usado in ocupados)

    if preferido is not None and livre(preferido):
        return preferido
    for vaga in VAGAS_SETOR:
        if livre(vaga):
            return vaga
    # Setor cheio nas vagas conhecidas: tenta a grade inteira, do centro para
    # fora, para nao empurrar a nave para uma borda so porque a lista e curta.
    for passo in range(1, 13):
        for lado in (passo, -passo):
            vaga = lado * PASSO_SETOR
            if abs(vaga) <= 7488 and livre(vaga):
                return vaga
    return None


def strip_crafts(ship: ET.Element) -> dict:
    """Tira os shuttles da nave antes de ela virar vitrine.

    POR QUE

    A vitrine e uma copia da nave do vendedor, e a copia vem com o complemento
    de bordo dele: `<crafts>`. Medido num save de verdade — a vitrine era a
    UNICA nave do setor com um `<c>` ali dentro, com coordenadas de voo
    proprias.

    Um shuttle nao fica parado. A IA o lanca, ele cruza o setor, e ele nao
    pertence a ninguem que esteja jogando: e a copia da lancha de outra pessoa,
    voando na partida de um terceiro. Se a nave-mae sai do setor antes do
    `checkin`, ele fica orfao — e orfao vira permanente, porque
    `remove_storefronts` procura por `sid` de nave e um `<c>` nao tem sid.

    Uma vitrine e uma prateleira. Prateleira nao tem lancha.
    """
    crafts = ship.find("crafts")
    if crafts is None:
        return {"removed": 0}
    return {"removed": clear_children(crafts)}


def remove_storefronts(dest: SaveFile, sids) -> dict:
    """Tira do save as vitrines que o servidor montou.

    POR QUE ISTO E OBRIGATORIO

    A vitrine entra no save que sai no `checkout`. Sem tirar de volta no
    `checkin`, ela vira parte permanente da partida da pessoa: seria guardada
    como canonica, entregue de novo na proxima retirada, e as vitrines
    empilhariam a cada sessao. Pior, a nave de um vizinho ficaria no save de
    alguem depois de o vizinho ter ido embora da sala.

    O que sai: a `<ship>` e o `<f>` que a carregava. O que NAO sai e o
    `hostmap` — as permissoes sao por faccao, valem para NPCs que o jogo pos
    ali, e desfaze-las mexeria numa relacao que talvez a propria pessoa tenha
    mudado jogando.
    """
    alvos = {str(s) for s in sids}
    report = {"ships": 0, "fleets": 0, "missing": []}
    if not alvos:
        return report

    achados = set()
    pais = parents_of(dest.main)
    for doc, ship in list(dest.ships()):
        if ship.get("sid") not in alvos:
            continue
        dono = pais.get(id(ship))
        if dono is not None:
            dono.remove(ship)
            achados.add(ship.get("sid"))
            report["ships"] += 1
        elif doc != "game":
            # O JOGO MOVE NAVES PARA ARQUIVO PROPRIO. Quando a pessoa sai do
            # setor, cada nave sai do `<ships>` do `game` e vira `ships/shipNNN`,
            # cuja raiz E o `<ship>`: nao ha pai de onde remove-la.
            #
            # A versao anterior procurava o pai so dentro do `game`, nao
            # achava, e seguia calada. Medido num save de verdade: tres copias
            # de `HSS YANNI (Vizinha)` em `ship1157`, `ship1383` e `ship2463`,
            # de uma conta que ja tinha sido apagada. Elas ficariam ali para
            # sempre.
            if dest.drop_document(doc):
                achados.add(ship.get("sid"))
                report["ships"] += 1
                report.setdefault("files", []).append(doc)

    starmap = dest.main.find("starmap")
    if starmap is not None:
        for fleets in list(starmap.iter("fleets")):
            for fleet in list(fleets):
                criadas = fleet.findall("createdShips/l")
                if not criadas:
                    continue
                if all(l.get("createdShipId") in alvos for l in criadas):
                    fleets.remove(fleet)
                    report["fleets"] += 1

    report["missing"] = sorted(alvos - achados)
    return report


def inject_ship(dest: SaveFile, source_ship: ET.Element, faction: str = DEFAULT_FACTION_ID,
                credits: str = DEFAULT_SHIP_CREDITS, stock: str | None = None,
                name: str | None = None, crew_side: str | None = None,
                keep_cargo: bool = False, celeid: str | None = None,
                system_id: str | None = None, hull_mode: bool = False,
                at: tuple | None = None) -> dict:
    """Monta o retrato de um vizinho dentro de `dest`, seguindo a secao 2.5.

    Nao grava nada: mexe na arvore em memoria e devolve o relatorio do que fez.
    Quem chama decide se salva — e o que permite o modo de ensaio e o que vai
    permitir ao servidor montar varios retratos antes de escrever uma vez so.
    """
    faction_id, side = resolve_faction(faction)
    parsed_stock = parse_stock(stock)
    report: dict = {"faction": faction_id, "side": side, "warnings": []}

    holder = dest.main.find("ships")
    if holder is None:
        raise SaveError("o documento `game` do destino não tem <ships>: "
                        "não há onde colocar a nave do setor carregado")

    body, where = locate_body(dest, celeid, system_id, at)
    report["body"] = {k: v for k, v in where.items() if k != "warnings"}
    report["warnings"] += where["warnings"]

    ship = copy.deepcopy(source_ship)
    ship.tail = None
    report["crafts"] = strip_crafts(ship)

    # A COPIA NAO HERDA O LUGAR DA ORIGINAL. Ela trazia o `ox` da nave do
    # vizinho, entao aparecia na coordenada que ele ocupava no setor dele.
    vaga = sector_slot(dest)
    report["sector"] = {"from": ship.get("ox"), "to": vaga}
    if vaga is not None:
        ship.set("ox", str(vaga))
    else:
        report["warnings"].append(
            "no free spot in the sector: the storefront kept the offset it had "
            "where it came from, and may overlap another ship")
    old_sid = ship.get("sid")
    if old_sid is None:
        raise SaveError("a nave de origem não tem @sid; ela não é uma <ship> válida")

    # -- 1 e 2: ids novos do contador global -------------------------------
    new_sid = dest.next_entity_id()
    ent_ids = [dest.next_entity_id() for _ in crew_members(ship)]
    if any(s.get("sid") == new_sid for _doc, s in dest.ships()):
        raise SaveError(f"o sid {new_sid} reservado já está em uso no destino; "
                        "masterData/@idCounter está atrasado neste save")
    report["ids"] = renumber_ship(ship, new_sid, ent_ids)

    # -- 3: de quem a nave e -----------------------------------------------
    if name:
        ship.set("sname", name)
    report["name"] = ship.get("sname")
    report["settings"] = set_owner(ship, faction_id, side)
    report["crewSide"] = set_crew_side(ship, crew_side)

    # -- 4: a IA de bordo ---------------------------------------------------
    donor = find_node_donor(dest, "asi")
    report["asi"] = ensure_ai(ship, donor[1] if donor else None)
    if report["asi"].get("warning"):
        report["warnings"].append(report["asi"]["warning"])
    elif donor is not None:
        report["asi"]["donorSid"] = donor[0].get("sid")

    # -- 5: a banca de comercio --------------------------------------------
    bank_donor = find_node_donor(dest, "shipBank")
    existing_bank = ship.find("shipBank")
    if existing_bank is not None:
        _remove_child(ship, existing_bank)
    bank = build_ship_bank(side, credits, bank_donor[1] if bank_donor else None)
    attach(ship, bank)
    report["shipBank"] = {
        "credits": bank.get("ca"),
        "side": bank.get("s"),
        "template": bank_donor[0].get("sid") if bank_donor else None,
        "replaced": existing_bank is not None,
    }
    if bank_donor is None:
        report["warnings"].append(
            "nenhuma nave de NPC do destino tem <shipBank> para servir de molde; "
            "as regras de preço saíram dos valores documentados, não do save"
        )
    report["stock"] = set_stock(ship, parsed_stock, clear=not keep_cargo)
    report["warnings"] += report["stock"]["warnings"]

    # -- 6: nevoa e teto ----------------------------------------------------
    #
    # No modo vitrine nao se toca. O casco ja nasce escondido, e o E3b mostrou
    # que escrever na nevoa e justamente o que nao funciona: o jogo reconstroi a
    # partir de uma fonte que nao encontramos, e so respeita o resultado quando
    # a nave de origem nunca foi explorada. Mexer aqui seria, na melhor das
    # hipoteses, inofensivo — e na pior, revelar um casco que estava fechado.
    if hull_mode:
        cells = [e for e in ship.iter("e") if e.get("fg") is not None]
        report["fog"] = {"mode": "casco", "cells": len(cells),
                         "fogged": sum(1 for e in cells if e.get("fg") == "0"),
                         "shipAttrs": {k: ship.get(k) for k in SHIP_HIDDEN_ATTRS
                                       if ship.get(k) is not None}}
    else:
        report["fog"] = hide_interior(ship)

    # -- a nave entra no setor carregado ------------------------------------
    attach(holder, ship)
    report["bytes"] = len(serialize(ship))

    # -- 7: a frota no mapa estelar -----------------------------------------
    # O molde e a posicao sao lidos *antes* de inserir a frota nova, senao a
    # busca acharia a nossa propria e o molde viraria copia de si mesmo.
    fleet_template = find_npc_fleet(dest)
    _host, player_fleet = find_player_fleet(dest)
    fleets, created_fleets = get_or_create_fleets(body)
    fleet = build_fleet(next_starmap_object_id(dest), faction_id, ship,
                        template=fleet_template, position=player_fleet)
    attach(fleets, fleet)
    report["fleet"] = {
        "id": fleet.get("id"),
        "createdFleetsNode": created_fleets,
        "template": fleet_template.get("id") if fleet_template is not None else None,
        "createdShipId": new_sid,
    }
    if fleet_template is None:
        report["warnings"].append(
            "o destino não tem nenhuma frota de NPC para servir de molde; o <f> foi "
            "montado com o conjunto mínimo documentado, que pode estar incompleto"
        )

    # -- 8: as permissoes ---------------------------------------------------
    report["hostmap"] = apply_hostmap_permissions(dest, faction_id, side)
    report["warnings"] += report["hostmap"]["warnings"]

    if report["ids"]["dangling"]:
        report["warnings"].append(
            f"{len(report['ids']['dangling'])} atributo(s) com cara de referência "
            f"a nave ainda apontam para o sid antigo {old_sid}: "
            + ", ".join(sorted(set(report["ids"]["dangling"]))[:6])
        )
    if report["ids"].get("coincidences"):
        report["notes"] = report.get("notes", [])
        report["notes"].append(
            f"{report['ids']['coincidences']} outro(s) atributo(s) valem "
            f"{old_sid} por coincidência (o sid antigo era um número pequeno); "
            f"não são referências a nave e ficaram como estavam"
        )
    if report["ids"]["otherEntIds"]:
        report["warnings"].append(
            f"{report['ids']['otherEntIds']} entId de equipamento/objeto vieram do save "
            "de origem sem renumerar (a receita 2.5 só pede a tripulação); se o jogo "
            "reclamar de id duplicado, é o primeiro lugar para olhar"
        )

    dest.reindex()
    dest.dirty = True
    return report


# --------------------------------------------------------------------------
# Preparo do destino
# --------------------------------------------------------------------------


