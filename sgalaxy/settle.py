"""Apura o que foi vendido numa vitrine, comparando duas fotos.

O PROBLEMA QUE ISTO RESOLVE

O jogo roda a economia inteira contra uma nave que o servidor inventou. Alguem
abre o comercio com a vitrine do vizinho, compra 40 placas de aco, paga o preco
que o jogo calculou — e esta certo do ponto de vista do jogo. So que o vizinho
nao existe para o jogo: a vitrine e uma copia com uma banca de faccao. Os
creditos param ali e morrem quando a vitrine e removida no check-in.

Este modulo e o que transporta o resultado de volta para uma pessoa.

COMO

Duas fotos da mesma vitrine: uma no `checkout`, quando o servidor a montou, e
outra no check-in, quando o save voltou. A diferenca e a sessao inteira.

    o que sumiu da prateleira  ->  o vizinho vendeu
    o que a banca ganhou       ->  o preco, feito pelo jogo

O preco vem do `ca` do `<shipBank>` de proposito. Poderiamos manter uma tabela
de precos no servidor, e ela estaria errada: o jogo precifica por demanda,
faccao e reputacao, e duas tabelas divergentes numa economia so e o comeco de
uma discussao que ninguem ganha.

O QUE ISTO NAO FAZ, E POR QUE

Nao liquida a direcao contraria. Se o visitante VENDEU para a vitrine, o
estoque sobe e a banca cai — e a banca e um numero que o servidor inventou, nao
o dinheiro do vizinho. Debitar alguem por uma compra que nao fez, com dinheiro
que nunca teve, e pior do que perder a transacao. Isso e reportado como
`inbound` para ser visto, e a decisao sobre permitir compra fica registrada no
plano.
"""

from __future__ import annotations


def _positivos(antes: dict, depois: dict) -> dict:
    """O que diminuiu de `antes` para `depois`, em modulo."""
    saiu = {}
    for recurso, quantia in antes.items():
        restante = int(depois.get(recurso, 0))
        if restante < int(quantia):
            saiu[recurso] = int(quantia) - restante
    return saiu


def _entrou(antes: dict, depois: dict) -> dict:
    """O que apareceu na prateleira sem ter sido consignado."""
    veio = {}
    for recurso, quantia in depois.items():
        base = int(antes.get(recurso, 0))
        if int(quantia) > base:
            veio[recurso] = int(quantia) - base
    return veio


def reconcile(snapshot: dict, stock_now: dict | None,
              credits_now: int | None) -> dict:
    """Compara a foto do `checkout` com o que voltou.

    `snapshot` e o que foi guardado na sessao: `stock` e `credits`. As duas
    outras vem do save devolvido. Qualquer uma pode ser None — a vitrine pode
    ter sido destruida, ou ter saido do setor — e nesse caso nao ha o que
    apurar, porque nao ha prova de venda.
    """
    antes = {str(r): int(q) for r, q in (snapshot.get("stock") or {}).items()}
    creditos_antes = snapshot.get("credits")

    resultado = {
        "sold": {},
        "credits": 0,
        "inbound": {},
        "notes": [],
    }

    if stock_now is None:
        resultado["notes"].append(
            "the storefront was not in the returned save: nothing can be "
            "settled, because there is no evidence of what was sold")
        return resultado

    depois = {str(r): int(q) for r, q in stock_now.items()}
    resultado["sold"] = _positivos(antes, depois)
    resultado["inbound"] = _entrou(antes, depois)

    if creditos_antes is None or credits_now is None:
        if resultado["sold"]:
            resultado["notes"].append(
                "goods left the shelf but the storefront had no shipBank to "
                "price them: the seller keeps the goods, and is paid nothing")
            # Sem preco nao ha venda: devolver a mercadoria e o unico
            # resultado honesto, senao alguem perde carga de graca.
            resultado["sold"] = {}
        return resultado

    ganho = int(credits_now) - int(creditos_antes)
    if ganho > 0:
        resultado["credits"] = ganho
    elif ganho < 0:
        resultado["notes"].append(
            f"the storefront's bank fell by {-ganho}: somebody sold INTO it. "
            f"That money was never the neighbour's, so it is not debited")

    if resultado["sold"] and not resultado["credits"]:
        resultado["notes"].append(
            "goods left the shelf with no matching payment; they are treated "
            "as sold anyway, because the goods are gone from the shelf either "
            "way and charging the seller twice would be worse")

    return resultado
