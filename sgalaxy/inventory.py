"""
Quanto de cada recurso uma nave tem, de verdade.

POR QUE ISTO NAO E UMA SOMA DE UMA COLUNA

Porque o jogo nao teleporta carga. Medido no E2 e no E6 (`docs/findings.md`,
item 8), uma compra passa por tres estados e um save tirado no meio — que e o
caso normal, porque o autosave nao espera — pega o total repartido:

    inStorage     o que ja esta na prateleira
    onTheWayIn    o que uma nave-vaivem foi buscar e ainda esta voando
    <items>       as caixas no chao, largadas pela vaivem

E a terceira nao e transitoria. A vaivem despeja em caixas no piso, e so depois
alguem carrega para o armazem — **e so se houver espaco**. Com armazem cheio, a
caixa fica no chao pelo resto da partida. As caixas medidas tinham `grndTime`
perto de 480 e nenhuma com `mo="BeingMoved"`: nao estavam viajando, estavam
paradas.

No E6 a vitrine vendeu 5 Chemicals. No save do comprador: **+1 em `inStorage` e
+4 em caixas**. Quem somasse so a prateleira reportaria 80% da transacao como
perda.

E O QUE ISSO CUSTARIA

A reconciliacao da secao 2.7 e a fase 3 inteira. Um vizinho vende cinco e recebe
por um; um jogador e acusado de sumir com carga que esta a tres metros da
prateleira. Errar para menos aqui nao da erro nenhum: da acusacao.

`onTheWayOut` fica de fora de proposito: e carga ja vendida, saindo. Conta-la
seria contar duas vezes o que o outro lado ja esta recebendo.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

# Onde a carga pode estar, em ordem de obviedade decrescente.
SHELF = "inStorage"
FLYING = "onTheWayIn"


def _inteiro(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def on_shelves(ship: ET.Element) -> dict:
    """O que esta no armazem, mais o que uma vaivem foi buscar."""
    total: dict = {}
    for pilha in ship.iter("s"):
        recurso = pilha.get("elementaryId")
        if recurso is None:
            continue
        quanto = _inteiro(pilha.get(SHELF)) + _inteiro(pilha.get(FLYING))
        if quanto:
            total[recurso] = total.get(recurso, 0) + quanto
    return total


def in_crates(ship: ET.Element) -> dict:
    """O que esta em caixa no chao.

    A vaivem despeja aqui, e a carga pode ficar indefinidamente se o armazem
    estiver cheio. Ignorar isto e a fonte do erro de 80% do E6.

    A forma real, medida em `E6 vitrine`:

        <i eid="176" x="27.23" y="46.23" id="5293" moprio="5" grndTime="155"/>

    Tres coisas que a primeira versao desta funcao errou, e que so o save
    mostrou. O recurso e `eid`, nao `elementaryId` — sao nomes diferentes para
    o mesmo vocabulario, e conferido: todo `eid` de caixa daquele save tambem
    aparece como `elementaryId` numa prateleira. **Nao ha atributo de
    quantidade**: cada `<i>` e uma unidade, e e contando elementos que se chega
    aos quatro Chemicals do item 8. E so contam os `<i>` filhos de `<items>`.
    """
    total: dict = {}
    itens = ship.find("items")
    if itens is None:
        return total
    for item in itens.findall("i"):
        recurso = item.get("eid")
        if recurso is None:
            continue
        total[recurso] = total.get(recurso, 0) + 1
    return total


def count(ship: ET.Element) -> dict:
    """Tudo que a nave tem, nos tres lugares somados."""
    total = dict(on_shelves(ship))
    for recurso, quanto in in_crates(ship).items():
        total[recurso] = total.get(recurso, 0) + quanto
    return {r: q for r, q in total.items() if q}


def credits_of(ship: ET.Element) -> int:
    """Os creditos da banca da nave, ou zero se ela nao tem banca."""
    bank = ship.find("shipBank")
    return _inteiro(bank.get("ca")) if bank is not None else 0


def delta(before: dict, after: dict) -> dict:
    """O que mudou entre duas contagens. Positivo entrou, negativo saiu.

    E a reconciliacao inteira: o servidor montou a vitrine, entao conhece o
    estado inicial exato, e o save que volta diz o final. O jogo nao guarda
    recibo nenhum — nem quantas transacoes houve, nem em que ordem (item 8b) —
    e por isso a diferenca e tudo que ha, e e tudo que e preciso.
    """
    recursos = set(before) | set(after)
    saldo = {r: after.get(r, 0) - before.get(r, 0) for r in recursos}
    return {r: q for r, q in saldo.items() if q}
