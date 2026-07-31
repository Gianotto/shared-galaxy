#!/usr/bin/env python3
"""
Diff estrutural entre dois savegames do Space Haven.

Existe por causa de uma pergunta especifica: quando o jogador compra alguma
coisa de uma nave de NPC, o que exatamente fica gravado no save? A resposta
decide se o comercio entre jogadores e reconciliavel por um servidor, e portanto
decide a fase 3 do projeto (ver docs/shared-galaxy-server.md, secao 2.12).

Um `diff` de texto nao serve: o save e um XML de 4,5 MB numa linha so, e cada
gravacao mexe em milhares de atributos que nao interessam. Esta ferramenta
compara arvore com arvore e agrupa o resultado por caminho, para a mudanca que
importa aparecer no meio do ruido.

O ruido e o problema central. Um save gravado duas vezes sem o jogador fazer
nada ja difere em milhares de pontos: relogios, posicao de tripulante, fase
orbital, contadores. Por isso o primeiro experimento do roteiro (E1, ver
docs/trade-experiment.md) e medir esse piso, e por isso esta ferramenta aceita
um perfil de ruido em `--noise` e sabe *gerar* esse perfil com `--learn-noise`.

Uso:

    # 1. medir o piso de ruido: carregue e salve sem fazer nada
    python3 tools/save_diff.py antes/ depois/ --learn-noise noise.json

    # 2. medir uma transacao, com o ruido ja descontado
    python3 tools/save_diff.py antes/ depois/ --noise noise.json

    # so o que interessa a economia
    python3 tools/save_diff.py antes/ depois/ --noise noise.json --focus economy

    # saida para outra ferramenta consumir
    python3 tools/save_diff.py antes/ depois/ --json > resultado.json

Somente leitura: nunca escreve num save.

O que esta ferramenta NAO faz, de proposito: nao tenta casar elementos por
heuristica de similaridade. Ela casa por chave estavel (`sid`, `entId`, `id`,
`eid`) quando existe, e por posicao quando nao existe. Um save onde o jogo
reordenou uma lista grande vai produzir ruido nessa lista, e o jeito certo de
lidar com isso e adicionar o caminho ao perfil de ruido, nao adivinhar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sgalaxy.savefile import SaveError, SaveFile  # noqa: E402


# ---------------------------------------------------------------------------
# Chaves de identidade
# ---------------------------------------------------------------------------

# Atributos que identificam um elemento de forma estavel entre duas gravacoes.
# A ordem importa: o primeiro que o elemento tiver e o que vale. `sid` e o id de
# nave e `entId` sai do contador global (docs/savegame-format.md); `id` e `eid`
# sao locais a nave, o que basta porque so comparamos irmaos entre si.
IDENTITY_KEYS = ("sid", "entId", "eid", "id", "celeid", "systemId")

# Pares de atributos que juntos identificam um elemento sem id proprio. Medido
# em save real: a tabela de relacoes entre faccoes tem 92 linhas <l> sem id
# nenhum, cada uma um par de faccoes em `s1`/`s2` — e por nome, nao por numero.
IDENTITY_PAIRS = (("s1", "s2"),)

# Atributos que sao o conteudo de uma lista, nao a identidade dela. Um <s> de
# armazem e identificado pelo recurso que guarda, nao por posicao: quando o
# jogo reordena o inventario, casar por posicao inventaria mudanca que nao
# houve. `elementaryId` e o nome real do atributo no save, medido em 1.0.4.
CONTENT_KEYS = ("elementaryId", "elementId", "element", "eid", "id")

# Valores que o jogo usa para dizer "sem id". Medido nos saves de teste: todo
# elemento <e> de dentro de uma nave vem com id="-1", as centenas. Tratar isso
# como identidade e pior do que nao ter identidade nenhuma — todos os irmaos
# viram o mesmo elemento, um so casa e o resto vira remocao fantasma.
# `0` fica de fora da lista de proposito: e id legitimo, o da frota do jogador.
SENTINEL_IDS = {"-1", ""}


def _identity(el: ET.Element) -> str | None:
    """Chave estavel do elemento, ou None se ele nao tiver nenhuma."""
    for key in IDENTITY_KEYS:
        val = el.get(key)
        if val is not None and val not in SENTINEL_IDS:
            return f"{key}={val}"
    # Sem id proprio: um par de atributos pode identificar.
    for pair in IDENTITY_PAIRS:
        vals = [el.get(k) for k in pair]
        if all(v is not None and v not in SENTINEL_IDS for v in vals):
            return ",".join(f"{k}={v}" for k, v in zip(pair, vals))
    # Ainda sem: se e um no de lista com conteudo declarado, o conteudo
    # serve de identidade entre irmaos.
    for key in CONTENT_KEYS:
        val = el.get(key)
        if val is not None and val not in SENTINEL_IDS:
            return f"{el.tag}:{key}={val}"
    return None


def _subtree_digest(el: ET.Element, memo: dict) -> str:
    """Hash do elemento inteiro, subarvore inclusa.

    Serve para casar dois elementos que sao identicos mesmo sem id: se o
    conteudo bate exatamente, sao a mesma coisa e nao ha o que reportar. E o
    que salva os <e> de uma nave, que nao tem identidade propria.
    """
    cached = memo.get(id(el))
    if cached is not None:
        return cached
    h = hashlib.blake2b(digest_size=16)
    h.update(el.tag.encode("utf-8"))
    for key in sorted(el.attrib):
        h.update(f"\x00{key}={el.attrib[key]}".encode("utf-8"))
    h.update(b"\x01")
    h.update((el.text or "").strip().encode("utf-8"))
    for child in el:
        h.update(b"\x02")
        h.update(_subtree_digest(child, memo).encode("ascii"))
    out = h.hexdigest()
    memo[id(el)] = out
    return out


# ---------------------------------------------------------------------------
# Perfis de foco
# ---------------------------------------------------------------------------

# Fragmentos de caminho que interessam a cada pergunta. Sao substrings do
# caminho de tags (ex.: "game/ships/ship/shipBank/..."), nao XPath: o objetivo e
# filtrar rapido sem inventar uma linguagem de consulta.
FOCUS = {
    # A pergunta do experimento de comercio. Os nomes de tag vem de save real
    # 1.0.4: a carga negociavel nao mora num campo do <shipBank>, mora em
    # pilhas <s elementaryId=... inStorage=...> dentro dos <inv> de armazem. O
    # <shipBank> guarda credito (`ca`) e regra de preco (<markup>).
    "economy": ("shipBank", "playerBank", "/inv", "/cinv", "/pinv", "stored",
                "items", "markup", "discount"),
    # Onde o jogador esta e o que ha no setor.
    "position": ("starmap", "fleets", "/f", "space", "spaceItems"),
    # Tripulacao.
    "crew": ("characters", "/c/", "skills", "attributes", "traits"),
    # Relacoes entre faccoes: o painel de controle do servidor (secao 1.8).
    "relations": ("hostmap", "map/l"),
}


# ---------------------------------------------------------------------------
# Comparacao
# ---------------------------------------------------------------------------

class Change:
    """Uma diferenca encontrada. `kind` e um de attr/added/removed/text."""

    __slots__ = ("kind", "path", "tag", "attr", "before", "after")

    def __init__(self, kind: str, path: str, tag: str,
                 attr: str | None = None,
                 before: str | None = None, after: str | None = None):
        self.kind = kind
        self.path = path
        self.tag = tag
        self.attr = attr
        self.before = before
        self.after = after

    @property
    def signature(self) -> str:
        """Identidade da mudanca para efeito de ruido.

        Sem o valor: o que se aprende no E1 e "este atributo neste caminho muda
        sozinho", nao "ele muda de 3 para 4".
        """
        return f"{self.path}|{self.kind}|{self.attr or ''}"

    def to_dict(self) -> dict:
        out = {"kind": self.kind, "path": self.path, "tag": self.tag}
        if self.attr is not None:
            out["attr"] = self.attr
        if self.before is not None:
            out["before"] = self.before
        if self.after is not None:
            out["after"] = self.after
        return out

    def __str__(self) -> str:
        if self.kind == "attr":
            return f"{self.path} @{self.attr}: {self.before} -> {self.after}"
        if self.kind == "text":
            return f"{self.path} (texto): {self.before!r} -> {self.after!r}"
        if self.kind == "added":
            return f"{self.path} + <{self.tag}{_attrs_preview(self.after)}>"
        return f"{self.path} - <{self.tag}{_attrs_preview(self.before)}>"


def _attrs_preview(blob: str | None, limit: int = 4) -> str:
    """Primeiros atributos de um elemento serializado como JSON, para a saida."""
    if not blob:
        return ""
    try:
        attrs = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return ""
    items = list(attrs.items())[:limit]
    text = "".join(f' {k}="{v}"' for k, v in items)
    return text + (" …" if len(attrs) > limit else "")


def _usable_identities(a: ET.Element, b: ET.Element) -> dict:
    """Identidades que servem para casar, por (tag, chave).

    Uma identidade so vale se for **unica entre os irmaos dos dois lados**.
    Chave repetida nao identifica ninguem: casaria o primeiro e deixaria todos
    os outros orfaos, inventando remocao onde nao houve. Medido em save real,
    onde os <e> de uma nave vem todos com o mesmo id.
    """
    counts: dict[tuple[str, str], list] = {}
    for side, parent in ((0, a), (1, b)):
        for child in parent:
            ident = _identity(child)
            if ident is None:
                continue
            slot = counts.setdefault((child.tag, ident), [0, 0])
            slot[side] += 1
    return {key for key, (na, nb) in counts.items() if na <= 1 and nb <= 1}


def _pair_children(a: ET.Element, b: ET.Element, memo: dict) -> list:
    """Casa os filhos de dois elementos, em tres passadas.

    1. por identidade estavel, quando ela e unica entre os irmaos
    2. por conteudo identico, para o que nao tem identidade
    3. por posicao dentro da tag, para o que sobrou — e so aqui que uma
       mudanca de atributo aparece

    Devolve pares (antes, depois), com None de um lado para o que so existe num.
    """
    usable = _usable_identities(a, b)
    unmatched_a = list(range(len(a)))
    unmatched_b = list(range(len(b)))
    matched: dict[int, int] = {}

    # -- 1. identidade unica
    by_ident: dict[tuple[str, str], int] = {}
    for i in unmatched_b:
        child = b[i]
        ident = _identity(child)
        if ident is not None and (child.tag, ident) in usable:
            by_ident[(child.tag, ident)] = i

    still_a, still_b = [], set(unmatched_b)
    for i in unmatched_a:
        child = a[i]
        ident = _identity(child)
        key = (child.tag, ident) if ident is not None else None
        if key is not None and key in usable and key in by_ident:
            j = by_ident.pop(key)
            matched[i] = j
            still_b.discard(j)
        else:
            still_a.append(i)

    # -- 2. conteudo identico: mesma subarvore, mesmo elemento
    by_digest: dict[str, list] = {}
    for j in sorted(still_b):
        by_digest.setdefault(_subtree_digest(b[j], memo), []).append(j)

    leftover_a = []
    for i in still_a:
        bucket = by_digest.get(_subtree_digest(a[i], memo))
        if bucket:
            j = bucket.pop(0)
            matched[i] = j
            still_b.discard(j)
        else:
            leftover_a.append(i)

    # -- 3. posicao dentro da tag, so para o que ainda sobrou
    remaining_b: dict[str, list] = {}
    for j in sorted(still_b):
        remaining_b.setdefault(b[j].tag, []).append(j)

    pairs: list = []
    for i in leftover_a:
        bucket = remaining_b.get(a[i].tag)
        if bucket:
            j = bucket.pop(0)
            matched[i] = j
            still_b.discard(j)

    for i in range(len(a)):
        j = matched.get(i)
        pairs.append((a[i], b[j] if j is not None else None))
    for j in sorted(still_b):
        pairs.append((None, b[j]))

    return pairs


def _label(el: ET.Element) -> str:
    """Rotulo de um elemento no caminho: a tag, mais a identidade se tiver."""
    ident = _identity(el)
    return f"{el.tag}[{ident}]" if ident else el.tag


def _walk(a: ET.Element | None, b: ET.Element | None, path: str,
          out: list, memo: dict, depth: int = 0, max_depth: int = 40) -> None:
    """Percorre os dois lados em paralelo acumulando mudancas em `out`."""
    if depth > max_depth:
        return

    if a is None and b is not None:
        out.append(Change("added", path, b.tag,
                          after=json.dumps(dict(b.attrib), sort_keys=True)))
        return
    if b is None and a is not None:
        out.append(Change("removed", path, a.tag,
                          before=json.dumps(dict(a.attrib), sort_keys=True)))
        return
    if a is None or b is None:
        return

    for key in sorted(set(a.attrib) | set(b.attrib)):
        before, after = a.get(key), b.get(key)
        if before != after:
            out.append(Change("attr", path, a.tag, key, before, after))

    # O texto de um no e quase sempre indentacao. So reporta quando os dois
    # lados tem conteudo de verdade.
    ta = (a.text or "").strip()
    tb = (b.text or "").strip()
    if ta != tb:
        out.append(Change("text", path, a.tag, None, ta, tb))

    pairs = _pair_children(a, b, memo)

    # Irmaos sem identidade produzem caminhos identicos, e ai duas coisas
    # quebram: nao da para saber de qual deles o relatorio esta falando, e uma
    # assinatura de ruido aprendida num deles silenciaria todos. Quando o
    # rotulo se repete, o indice de ocorrencia entra junto.
    labels = [_label(c if c is not None else d) for c, d in pairs]
    repeated = {lab for lab in labels if labels.count(lab) > 1}
    seen: dict[str, int] = {}

    for (child_a, child_b), label in zip(pairs, labels):
        ref = child_a if child_a is not None else child_b
        if ref is None:
            continue
        if label in repeated:
            n = seen.get(label, 0)
            seen[label] = n + 1
            label = f"{label}[#{n}]"
        _walk(child_a, child_b, f"{path}/{label}", out, memo, depth + 1,
              max_depth)


def compare(before: str, after: str, max_depth: int = 40) -> dict:
    """Compara dois saves inteiros, documento a documento."""
    sf_a = SaveFile(before)
    sf_b = SaveFile(after)

    changes: list[Change] = []
    docs_a, docs_b = set(sf_a.docs), set(sf_b.docs)

    memo: dict = {}
    for key in sorted(docs_a & docs_b):
        _walk(sf_a.docs[key].root, sf_b.docs[key].root, key, changes, memo,
              max_depth=max_depth)

    # Um arquivo de nave que aparece ou some e o jogo movendo uma nave entre
    # `game/ships` e `ships/` — ou seja, alguem viajou. Vale reportar alto.
    for key in sorted(docs_b - docs_a):
        changes.append(Change("added", key, "ship",
                              after=json.dumps({"file": key})))
    for key in sorted(docs_a - docs_b):
        changes.append(Change("removed", key, "ship",
                              before=json.dumps({"file": key})))

    return {"before": sf_a.path, "after": sf_b.path, "changes": changes}


# ---------------------------------------------------------------------------
# Ruido
# ---------------------------------------------------------------------------

def learn_noise(changes: list) -> dict:
    """Monta um perfil de ruido a partir de um diff que deveria ser vazio."""
    sigs = sorted({c.signature for c in changes})
    return {
        "version": 1,
        "note": ("Assinaturas medidas carregando e salvando um save sem fazer "
                 "nada. Tudo aqui muda sozinho e nao significa acao do jogador."),
        "signatures": sigs,
    }


def load_noise(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "signatures" not in data:
        raise SaveError(f"{path}: nao parece um perfil de ruido")
    return set(data["signatures"])


def apply_filters(changes: list, noise: set[str] | None,
                  focus: str | None) -> list:
    out = changes
    if noise:
        out = [c for c in out if c.signature not in noise]
    if focus:
        needles = FOCUS[focus]
        out = [c for c in out if any(n in c.path for n in needles)]
    return out


# ---------------------------------------------------------------------------
# Saida
# ---------------------------------------------------------------------------

def group_by_area(changes: list) -> dict:
    """Agrupa por prefixo de caminho ate a terceira tag, para dar panorama."""
    groups: dict[str, list] = {}
    for change in changes:
        parts = change.path.split("/")
        area = "/".join(parts[:3]) if len(parts) >= 3 else change.path
        groups.setdefault(area, []).append(change)
    return groups


def report(result: dict, changes: list, limit: int, verbose: bool) -> None:
    print(f"antes:  {result['before']}")
    print(f"depois: {result['after']}")
    print()

    if not changes:
        print("nenhuma diferenca (depois dos filtros)")
        return

    groups = group_by_area(changes)
    print(f"{len(changes)} mudancas em {len(groups)} areas")
    print()

    for area, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"  {area}  ({len(items)})")
        shown = items if verbose else items[:limit]
        for change in shown:
            print(f"      {change}")
        if len(items) > len(shown):
            print(f"      … e mais {len(items) - len(shown)}"
                  f" (use --verbose ou --limit)")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="compara dois savegames e mostra o que mudou entre eles")
    ap.add_argument("before", help="save de antes (pasta ou o arquivo `game`)")
    ap.add_argument("after", help="save de depois")
    ap.add_argument("--noise", metavar="ARQUIVO",
                    help="perfil de ruido a descontar, gerado com --learn-noise")
    ap.add_argument("--learn-noise", metavar="ARQUIVO",
                    help="grava as mudancas encontradas como perfil de ruido; "
                         "use com dois saves que deveriam ser iguais")
    ap.add_argument("--focus", choices=sorted(FOCUS),
                    help="mostra so uma area de interesse")
    ap.add_argument("--limit", type=int, default=8,
                    help="mudancas mostradas por area (padrao: 8)")
    ap.add_argument("--max-depth", type=int, default=40,
                    help="profundidade maxima da arvore (padrao: 40)")
    ap.add_argument("--json", action="store_true",
                    help="saida em JSON, para outra ferramenta consumir")
    ap.add_argument("--verbose", action="store_true",
                    help="mostra todas as mudancas, sem truncar")
    args = ap.parse_args()

    try:
        result = compare(args.before, args.after, args.max_depth)
    except SaveError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    changes = result["changes"]

    if args.learn_noise:
        profile = learn_noise(changes)
        with open(args.learn_noise, "w", encoding="utf-8") as fh:
            json.dump(profile, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"perfil de ruido gravado em {args.learn_noise}")
        print(f"{len(profile['signatures'])} assinaturas a partir de "
              f"{len(changes)} mudancas")
        if not changes:
            print()
            print("aviso: nenhuma mudanca encontrada. Se estes dois saves")
            print("deveriam ter passado por um ciclo de carregar e salvar, o")
            print("perfil esta vazio e nao vai filtrar nada.")
        return 0

    noise = None
    if args.noise:
        try:
            noise = load_noise(args.noise)
        except (OSError, json.JSONDecodeError, SaveError) as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2

    filtered = apply_filters(changes, noise, args.focus)

    if args.json:
        json.dump({
            "before": result["before"],
            "after": result["after"],
            "total": len(changes),
            "shown": len(filtered),
            "changes": [c.to_dict() for c in filtered],
        }, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if noise or args.focus:
        dropped = len(changes) - len(filtered)
        print(f"({len(changes)} mudancas brutas, {dropped} filtradas)")
        print()

    report(result, filtered, args.limit, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
