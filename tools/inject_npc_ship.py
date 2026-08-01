"""Injeta a nave de um save em outro save como NPC legitimo de outra faccao.

E o "retrato" de um jogador vizinho: a nave dele aparece parada no setor onde
voce esta, com dono declarado, frota registrada no mapa estelar, interior
fechado e uma banca de comercio com estoque e creditos que nos escolhemos. O
jogo entrega HAIL, TRADE e MISSIONS de graca para qualquer nave de outra faccao
parada no setor, entao a interface de comercio entre jogadores nao precisa ser
inventada — precisa ser abastecida.

Hoje isto e instrumento de experimento: o E3 do roteiro da etapa A pergunta se o
estoque de uma nave injetada diminui ao comerciar, se os creditos entram no
`playerBank` e se o jogo respeita o `ca` como teto de compra. Nenhuma dessas
perguntas se responde sem uma nave cujo `<shipBank>` nos montamos, com numeros
redondos e conferiveis — por isso estoque e creditos sao parametro, nao
constante.

Na fase 2 este mesmo codigo vira o construtor de retratos do servidor, chamado
no `checkout`. Por isso a montagem mora em funcoes puras que recebem um
`SaveFile` e devolvem um relatorio: o argparse e a impressao em terminal sao
casca, e o servidor vai importar `inject_ship()` direto.

A receita e a da secao 2.5 do projeto, na ordem:

    1. a nave copiada para `game/ships` do destino, com `sid` novo tirado de
       `masterData/@idCounter`
    2. `entId` novo para cada tripulante, do mesmo contador
    3. `<ship>/<settings>` com `of` e `owner` da faccao escolhida — e isso, e so
       isso, que decide de quem a nave e
    4. `<asi>` copiado de uma nave de NPC do destino, para a IA existir
    5. `<shipBank>` com estoque e creditos controlados
    6. `fg="0"` em cada celula, `unex="1"`, `forceRoof="1"`
    7. uma frota `<f>` no `<fleets>` do corpo celeste onde o jogador esta, com
       `createdShipId` apontando para o `sid` novo
    8. no `hostmap`, `accessTrade` ligado e `accessVision`/`accessShip`
       desligados para o par jogador-faccao

Sobre ids: os que vivem *dentro* de uma nave (`id`, `eid`) sao locais a ela —
duas naves convivem no mesmo save compartilhando centenas deles sem conflito, e
renumerar seria trabalho inutil e arriscado. So o `sid` e os `entId` da
tripulacao saem do contador global.

O save de entrada nunca e tocado. A ferramenta exige `--out`, copia a pasta
inteira e mexe na copia — o save de um jogador e insubstituivel e nao existe
motivo bom para editar no lugar.

Uso:
    # injeta a nave 1234 do save do vizinho no save do jogador
    python3 tools/inject_npc_ship.py --from VIZINHO --into MEU --out SAIDA \\
        --sid 1234

    # ensaio: descreve tudo que faria, nao grava nada, nao exige --out
    python3 tools/inject_npc_ship.py --from VIZINHO --into MEU --sid 1234 \\
        --dry-run

    # o retrato do E3: estoque e creditos conhecidos, nome que identifica o dono
    python3 tools/inject_npc_ship.py --from VIZINHO --into MEU --out SAIDA \\
        --sid 1234 --faction Merchant --credits 5000 \\
        --stock 2053:40,1002:10 --name "Banca do Joao"

    # escolhe a nave pelo nome em vez do sid, e lista as candidatas se errar
    python3 tools/inject_npc_ship.py --from VIZINHO --into MEU --out SAIDA \\
        --ship-name "Hyperion"

Suposicoes ainda nao verificadas — nada aqui foi testado contra um save real
nesta maquina, e cada item destes precisa de um jogo aberto para virar fato:

    - a ordem dos filhos dentro de `<ship>`. `<asi>` e `<shipBank>` entram no
      fim; se o jogo ler o XML sequencialmente em vez de por tag, isso importa
    - onde mora o estoque que a nave negocia. O `<shipBank>` real que temos so
      tem `<markup>` e `<discount>`, que sao regras de preco; a carga de verdade
      esta nas pilhas `<s>` dos `<inv>` de armazem. Esta ferramenta mexe nos
      dois e o E3 e exatamente o experimento que diz qual dos dois o jogo le
    - se `forceRoof` vive na raiz `<ship>` (e o que assumimos, por analogia com
      `unex`) ou em cada celula
    - os atributos do `<f>` de uma frota de NPC. Copiamos uma frota existente
      sempre que o destino tiver uma; sem isso, montamos com o conjunto minimo
      documentado, que pode estar incompleto
    - o `side` da tripulacao. O retrato fica com a tripulacao marcada como da
      faccao escolhida, porque uma nave de Civis tripulada por `Player` e uma
      combinacao que nunca foi vista no jogo. A secao 1.7 diz que `of`/`owner`
      mandam mesmo com tripulacao de outra faccao, mas nao testa o contrario
    - `entId` de equipamento, implante e objeto dentro da nave nao sao
      renumerados, seguindo a secao 2.5 a risca. O relatorio conta quantos sao,
      para a exposicao a colisao ficar visivel
    - `<markers>` (pontos de atracagem) nao e copiado: a receita nao pede
    - a nave copiada e reindentada para a profundidade do destino, mexendo so em
      espaco em branco (no com texto de verdade fica intocado). O jogo nao le
      indentacao, mas o `save_diff.py` irmao le, e um bloco fora de nivel
      polui todo diff posterior
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from sgalaxy.savefile import SaveError, SaveFile  # noqa: E402
from sgalaxy.storefront import (  # noqa: E402,F401
    apply_hostmap_permissions,
    attach,
    build_fleet,
    build_ship_bank,
    clear_children,
    crew_count,
    crew_members,
    describe_ships,
    ensure_ai,
    faction_tokens,
    find_node_donor,
    find_npc_fleet,
    find_player_fleet,
    find_ship,
    get_or_create_fleets,
    hide_interior,
    inject_ship,
    locate_body,
    next_starmap_object_id,
    parents_of,
    parse_stock,
    reindent,
    renumber_ship,
    resolve_faction,
    set_crew_side,
    set_owner,
    set_stock,
    ship_racks,
    unexplored_hulls,
    CREATED_SHIP_DEFAULTS,
    DEFAULT_FACTION_ID,
    DEFAULT_SHIP_CREDITS,
    FACTION_SIDES,
    FLEETS_AFTER_TAG,
    FLEETS_BEFORE_TAG,
    FLEET_BASE_ATTRS,
    FOG_ATTR,
    FOG_UNSEEN,
    HOSTMAP_CONTEXT_ATTRS,
    PLAYER_FACTION_ID,
    PLAYER_SIDE,
    PORTRAIT_PERMISSIONS,
    RACK_HOLDER_TAGS,
    SHIP_BANK_DEFAULTS,
    SHIP_HIDDEN_ATTRS,
    SID_BACKREF_ATTRS,
    STACK_DEFAULTS,
)


def prepare_output(save_dir: str, out: str, keep_out_of: tuple[str, ...] = ()) -> str:
    """Copia a pasta do save para `out` e devolve o caminho da copia.

    O save de um jogador e insubstituivel e nao ha motivo bom para editar no
    lugar. A ferramenta recusa gravar por cima de qualquer coisa que ja exista e
    recusa colocar a saida dentro de um dos saves de entrada — o que
    transformaria a copia em parte do original.
    """
    out = os.path.abspath(os.path.expanduser(out))
    save_dir = os.path.abspath(save_dir)
    if os.path.exists(out):
        raise SaveError(f"{out} já existe; apague ou escolha outro caminho para --out "
                        "(esta ferramenta nunca grava por cima)")
    for forbidden in (save_dir, *(os.path.abspath(p) for p in keep_out_of)):
        if out == forbidden or out.startswith(forbidden + os.sep):
            raise SaveError(f"--out não pode ficar dentro de {forbidden}, "
                            "que é um dos saves de entrada")
    parent = os.path.dirname(out) or "."
    if not os.path.isdir(parent):
        raise SaveError(f"a pasta {parent} não existe")
    shutil.copytree(save_dir, out)
    return out


# --------------------------------------------------------------------------
# Terminal
# --------------------------------------------------------------------------


def print_report(report: dict, dry_run: bool) -> None:
    ids, fog = report["ids"], report["fog"]
    print(f"nave: {report['name'] or '(sem nome)'!r}")
    print(f"  sid {ids['oldSid']} → {ids['sid']}"
          f" | {ids['crew']} tripulante(s) com entId novo"
          f" | {ids['backrefs']} referência(s) internas ao sid corrigidas")
    print(f"  dono: of={report['settings']['of']} owner={report['settings']['owner']}"
          f" (era of={report['settings']['before']['of']!r})")
    if report["crewSide"]["applied"]:
        print(f"  tripulação marcada como {report['crewSide']['side']}"
              f" ({report['crewSide']['changed']} alterada(s))")
    print(f"  IA de bordo <asi>: {report['asi']['source'] or 'AUSENTE'}"
          + (f" (da nave {report['asi']['donorSid']})" if report["asi"].get("donorSid") else ""))

    bank, stock = report["shipBank"], report["stock"]
    print(f"  banca: {bank['credits']} créditos, lado {bank['side']}"
          + (f", molde da nave {bank['template']}" if bank["template"] else ", sem molde"))
    if stock["placed"]:
        itens = ", ".join(f"{s['element']}×{s['amount']} (armazém {s['rack']})"
                          for s in stock["placed"])
        print(f"  estoque: {itens}")
        print(f"           {stock['used']} de {stock['racks']} armazém(ns) usados, "
              f"{stock['cleared']} pilha(s) anteriores removidas")
    else:
        print(f"  estoque: nenhum ({stock['cleared']} pilha(s) removidas, "
              f"{stock['racks']} armazém/armazéns disponíveis)")
    if fog.get("mode") == "casco":
        print(f"  névoa: {fog['fogged']}/{fog['cells']} célula(s) já em fg=0, "
              + " ".join(f"{k}={v}" for k, v in fog["shipAttrs"].items())
              + " — do casco, não tocada")
    else:
        print(f"  névoa: {fog['fogged']}/{fog['cells']} célula(s) com fg=0, "
              + " ".join(f"{k}={v}" for k, v in fog["shipAttrs"].items()))
        # Medido no E3: o jogo desfaz isto ao carregar quando a nave de origem
        # ja foi explorada, que e o caso de toda nave de jogador. Ver
        # findings.md, item 10.
        print("           (se a origem for nave de jogador, o jogo desfaz isto "
              "ao carregar — use --hull; ver findings.md item 10)")
    print(f"  tamanho da nave montada: {report['bytes']} bytes")

    body, fleet = report["body"], report["fleet"]
    print(f"corpo celeste: celeid={body['celeid']} sistema={body['system']} "
          f"<{body.get('bodyTag')}>")
    print(f"  frota <f id={fleet['id']}> criada"
          + (" (com o <fleets> do corpo)" if fleet["createdFleetsNode"] else "")
          + f", createdShipId={fleet['createdShipId']}")

    host = report["hostmap"]
    if host["rows"]:
        mudou = ", ".join(f"{c['attr']}: {c['from']}→{c['to']}" for c in host["changed"])
        print(f"permissões ({host['rows']} linha(s) do hostmap): {mudou or 'já estavam certas'}")
        if host["context"]:
            print("  relação atual: "
                  + " ".join(f"{k}={v}" for k, v in host["context"].items()))

    for warn in report["warnings"]:
        print(f"  aviso: {warn}")
    for note in report.get("notes", []):
        print(f"  nota: {note}")
    if dry_run:
        print("\nensaio: nada foi gravado.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="injeta a nave de um savegame em outro como NPC de outra facção "
                    "(o retrato de um jogador vizinho, receita da seção 2.5)")
    ap.add_argument("--from", dest="source",
                    help="save de origem, de onde a nave sai (nunca é alterado); "
                         "dispensável com --hull")
    ap.add_argument("--into", dest="dest", required=True,
                    help="save de destino, onde a nave entra (nunca é alterado)")
    ap.add_argument("--out",
                    help="pasta nova que recebe a cópia alterada do destino; "
                         "obrigatória fora do modo de ensaio")
    ap.add_argument("--hull", nargs="?", const="auto", metavar="SID",
                    help="modo vitrine (seção 2.5): monta o retrato sobre um "
                         "casco de NPC do próprio destino em vez de copiar a "
                         "nave do vizinho. Sem valor, escolhe o menor casco não "
                         "explorado; com um sid, usa aquele")
    ap.add_argument("--sid", help="sid da nave de origem")
    ap.add_argument("--ship-name", help="nome da nave de origem, em vez do sid")
    ap.add_argument("--faction", default=DEFAULT_FACTION_ID,
                    help=f"facção dona do retrato, por id ou nome de lado "
                         f"(padrão {DEFAULT_FACTION_ID}/{FACTION_SIDES[DEFAULT_FACTION_ID]})")
    ap.add_argument("--credits", default=DEFAULT_SHIP_CREDITS,
                    help=f"créditos da banca (shipBank/@ca), o teto do que ela compra "
                         f"(padrão {DEFAULT_SHIP_CREDITS})")
    ap.add_argument("--stock", help="estoque exposto, ELEMENTO:QUANTIDADE separado por "
                                    "vírgula, por exemplo 2053:40,1002:10")
    ap.add_argument("--keep-cargo", action="store_true",
                    help="mantém a carga original em vez de esvaziar os armazéns; "
                         "expõe o porão do dono, use só para inspeção")
    ap.add_argument("--name", help="novo nome da nave — é ele que carrega a identidade "
                                   "do jogador dono do retrato")
    ap.add_argument("--crew-side", default=None, metavar="LADO",
                    help="lado da tripulação; o padrão é o da facção escolhida, "
                         "'keep' preserva o que veio do save de origem")
    ap.add_argument("--body", help="celeid do corpo celeste de destino "
                                   "(padrão: starmap/@pa, onde o jogador está)")
    ap.add_argument("--system", help="systemId do sistema de destino (padrão: starmap/@sys)")
    ap.add_argument("--dry-run", action="store_true",
                    help="descreve o que faria e não grava nada")
    args = ap.parse_args()

    if not args.dry_run and not args.out:
        print("erro: --out é obrigatório — esta ferramenta nunca escreve sobre o save "
              "de entrada. Use --dry-run para ver o que ela faria.", file=sys.stderr)
        return 1
    if args.hull:
        if args.source:
            print("erro: --hull monta sobre um casco do próprio destino; "
                  "não use --from junto.", file=sys.stderr)
            return 1
    else:
        if not args.source:
            print("erro: informe --from, ou use --hull para montar a vitrine "
                  "sobre um casco do destino.", file=sys.stderr)
            return 1
        if not args.sid and not args.ship_name:
            print("erro: escolha a nave de origem com --sid ou --ship-name.",
                  file=sys.stderr)
            return 1

    try:
        crew_side = None
        if args.crew_side is None:
            crew_side = resolve_faction(args.faction)[1]
        elif args.crew_side.lower() != "keep":
            crew_side = args.crew_side

        probe = SaveFile(args.dest)
        keep_out = ()

        if args.hull:
            # A vitrine sai do proprio destino: nada de conteudo do jogo viaja
            # entre instalacoes, e o casco escolhido e uma nave que aquele
            # jogador ja tem no save dele.
            hulls = unexplored_hulls(probe)
            if not hulls:
                raise SaveError(
                    "este save não tem nenhuma nave de NPC não explorada para "
                    "servir de vitrine. Use --from com uma nave de origem, "
                    "ciente de que a névoa não vai sobreviver ao load")
            if args.hull == "auto":
                ship = hulls[0]
            else:
                escolhidos = [h for h in hulls if h.get("sid") == args.hull]
                if not escolhidos:
                    disponiveis = ", ".join(
                        f"sid={h.get('sid')} {h.get('sname')!r}" for h in hulls[:8])
                    raise SaveError(
                        f"sid {args.hull} não é um casco não explorado deste "
                        f"save. Disponíveis: {disponiveis}")
                ship = escolhidos[0]
        else:
            source = SaveFile(args.source)
            ship = find_ship(source, args.sid, args.ship_name)
            keep_out = (source.dir,)

        if args.dry_run:
            dest = probe
        else:
            out = prepare_output(probe.dir, args.out, keep_out_of=keep_out)
            dest = SaveFile(out)
            # O casco veio do `probe`; no modo de gravacao a arvore que vale e a
            # do `dest`, entao a nave tem que ser reencontrada la dentro.
            if args.hull:
                sid_casco = ship.get("sid")
                ship = find_ship(dest, sid_casco, None)

        report = inject_ship(
            dest, ship, faction=args.faction, credits=args.credits, stock=args.stock,
            name=args.name, crew_side=crew_side, keep_cargo=args.keep_cargo,
            celeid=args.body, system_id=args.system, hull_mode=bool(args.hull),
        )
        print_report(report, args.dry_run)
        if not args.dry_run:
            # Sem backup: o destino ja e uma copia intocada feita agora, e um
            # `.bak-` dentro dela so confundiria quem for abrir a pasta no jogo.
            written = dest.save(backup=False)
            print(f"\ngravado em {os.path.dirname(written['path'])} "
                  f"({len(written['files'])} arquivo(s), {written['bytes']} bytes)")
    except SaveError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
