"""
A loja de um jogador: um armazem da nave dele, e so ele.

A IDEIA, e por que ela ganhou das outras
----------------------------------------

O jogador aponta UM armazem da nave como a loja. Dali em diante ele administra
o estoque com a interface do proprio jogo: o que ele mover para la esta a
venda, o que tirar sai. Nao ha catalogo, nao ha tela nova, e a mecanica de
arrastar carga e a que ele ja conhece.

As duas alternativas perderam por motivos diferentes. Reaproveitar as
`<rules>` do armazem daria a elas um sentido que o jogo nao da — sao regras de
transferencia entre armazens, e quem usasse "Bring here" para organizar a nave
estaria pondo carga a venda sem saber. E um botao novo no painel seria mais
claro, mas custa interface escrita as cegas, num jogo que so o jogador ve.

Isto tambem casa com o modelo do proprio jogo. A banca de uma nave NPC tem
`offerList` e `holdBackItems`: ela oferece a carga que tem, menos o que retem.
Ou seja, para o jogo, ter e oferecer. Um armazem dedicado e exatamente "o que
eu tenho para vender", separado do "o que eu tenho".

A FORMA NO SAVE, medida em save real
------------------------------------

    <l id="435" x="28" y="20" …>      o objeto que a pessoa construiu
      <feat eatAllowed="1" cp="0">    o que ele faz
        <inv>
          <s elementaryId="176" inStorage="87" onTheWayIn="0" onTheWayOut="0"/>
          <rules/>

O `id` do `<l>` e o que identifica a loja entre sessoes: e objeto da nave da
propria pessoa, e vive enquanto ela nao o desmontar.

Um armazem e um `<l>` cujo `<feat>` pendura `<inv>` DIRETO. Produtores, motores
e enfermarias tambem tem `<inv>`, mas pendurado num `<prod>`, `<engine>` ou
`<medical>` dentro do `<feat>` — sao insumos de maquina, nao deposito.

O QUE ESTE MODULO NAO FAZ

Nao decide preco e nao move nada sozinho. Ele le o que esta na loja e sabe
tirar de la o que foi vendido; quem decide o que foi vendido e a reconciliacao,
a partir do delta da vitrine (`sgalaxy.inventory`).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

# Um <feat> que pendura estes e maquina, nao deposito: o <inv> ali dentro sao
# insumos sendo consumidos.
MACHINE_TAGS = ("prod", "engine", "medical", "research", "stabil")


def _parents(ship: ET.Element) -> dict:
    return {child: parent for parent in ship.iter() for child in parent}


def storages(ship: ET.Element) -> list:
    """Todo armazem da nave, com id, posicao e o que tem dentro.

    Ordenado do mais cheio para o mais vazio, que e a ordem util para alguem
    escolher qual sera a loja.
    """
    pais = _parents(ship)
    out = []
    for inv in ship.iter("inv"):
        feat = pais.get(inv)
        if feat is None or feat.tag != "feat":
            continue
        obj = pais.get(feat)
        if obj is None or obj.get("id") is None:
            continue
        pilhas = inv.findall("s")
        out.append({
            "id": obj.get("id"),
            "x": obj.get("x"),
            "y": obj.get("y"),
            "stacks": len(pilhas),
            "units": sum(_inteiro(p.get("inStorage")) for p in pilhas),
            "contents": _contents(inv),
        })
    out.sort(key=lambda s: -s["units"])
    return out


def _inteiro(valor) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def _contents(inv: ET.Element) -> dict:
    """O que esta NA PRATELEIRA deste armazem.

    So `inStorage`. O que esta a caminho ainda nao chegou aqui, e o que esta
    saindo ja foi vendido — pos a venda o que ainda nao e seu, ou o que ja
    deixou de ser, e vender duas vezes a mesma caixa.
    """
    total: dict = {}
    for pilha in inv.findall("s"):
        recurso = pilha.get("elementaryId")
        if recurso is None:
            continue
        quanto = _inteiro(pilha.get("inStorage"))
        if quanto > 0:
            total[recurso] = total.get(recurso, 0) + quanto
    return total


def find(ship: ET.Element, storage_id: str) -> ET.Element | None:
    """O `<inv>` do armazem com aquele id, ou None se ele nao existe mais.

    Nao existir mais e caso normal, nao erro: a pessoa pode ter desmontado a
    loja entre uma sessao e outra, e isso e escolha dela.
    """
    pais = _parents(ship)
    for inv in ship.iter("inv"):
        feat = pais.get(inv)
        if feat is None or feat.tag != "feat":
            continue
        obj = pais.get(feat)
        if obj is not None and obj.get("id") == str(storage_id):
            return inv
    return None


def on_sale(ship: ET.Element, storage_id: str) -> dict:
    """O que esta a venda: o conteudo da loja, e nada mais."""
    inv = find(ship, storage_id)
    return _contents(inv) if inv is not None else {}


def take(ship: ET.Element, storage_id: str, resource: str, amount: int) -> int:
    """Tira da loja o que foi vendido. Devolve quanto saiu de fato.

    Pode sair menos do que foi pedido, e isso nao e erro: entre montar a
    vitrine e a venda ser reconciliada, a pessoa pode ter movido a carga para
    outro lugar. Tirar de outro armazem para cobrir seria mexer no que ela
    guardou fora da loja — e a loja e o unico lugar que ela nos autorizou.
    """
    inv = find(ship, storage_id)
    if inv is None or amount <= 0:
        return 0
    restante = amount
    for pilha in inv.findall("s"):
        if pilha.get("elementaryId") != str(resource) or restante <= 0:
            continue
        tem = _inteiro(pilha.get("inStorage"))
        sai = min(tem, restante)
        if sai:
            pilha.set("inStorage", str(tem - sai))
            restante -= sai
    return amount - restante


def pay(game: ET.Element, credits: int) -> int:
    """Credita a venda no banco do jogador. Devolve o saldo novo.

    Recebe o `<game>`, nao a nave: o dinheiro do jogador mora em
    `game/playerBank`, e o `<shipBank>` de uma nave e outra coisa — e a caixa
    de uma nave NPC que negocia. Passar a nave aqui devolve None em silencio, e
    o vizinho entrega carga e nao recebe nada.

    E ele PRECISA chegar aqui: o jogo pagou a FACCAO da vitrine, nunca a pessoa
    (findings item 11). Sem este passo a venda acontece e o vendedor nao ve cor.
    """
    bank = game.find("playerBank")
    if bank is None:
        return 0
    saldo = _inteiro(bank.get("ca")) + int(credits)
    bank.set("ca", str(saldo))
    return saldo
