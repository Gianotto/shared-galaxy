#!/usr/bin/env python3
"""
Copia uma pasta de savegame para um diretorio de trabalho, com rotulo.

Ferramenta boba de proposito. Ela existe porque o experimento de comercio
(docs/trade-experiment.md) depende de comparar o save em momentos exatos, e
fazer isso na mao termina em pasta chamada `save_antes_2_final_FINAL` e num
resultado que ninguem consegue repetir uma semana depois.

Cada snapshot guarda um `snapshot.json` ao lado com rotulo, momento e o hash de
cada arquivo. O hash e o que permite responder mais tarde "esses dois snapshots
sao mesmo diferentes?" sem reabrir o jogo.

Uso:

    python3 tools/save_snapshot.py ~/.../savegames/save3 E2-antes
    python3 tools/save_snapshot.py ~/.../savegames/save3 E2-depois
    python3 tools/save_snapshot.py --list
    python3 tools/save_diff.py $(python3 tools/save_snapshot.py --path E2-antes) \\
                               $(python3 tools/save_snapshot.py --path E2-depois)

Por padrao os snapshots vao para `experiments/snapshots/`, que esta no
.gitignore: savegame e arquivo pessoal e nao entra no repositorio.

Somente leitura sobre o save de origem. Esta ferramenta nunca escreve dentro da
pasta que voce apontou.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time

# Onde os snapshots ficam. Dentro do repositorio para as ferramentas se
# acharem sozinhas, mas ignorado pelo git: save e arquivo pessoal.
DEFAULT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "snapshots")

# Arquivos que o jogo escreve e que nao interessam ao experimento. Copiados
# assim mesmo (um snapshot tem que ser fiel), mas fora do hash de comparacao,
# porque mudam por conta propria e poluiriam a resposta.
UNSTABLE = ("stats.bin",)


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _hash_tree(root: str) -> dict:
    """Hash de cada arquivo do save, com caminho relativo como chave."""
    out: dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            out[rel] = _hash_file(full)
    return out


def _resolve_save_dir(path: str) -> str:
    """Aceita a pasta do save, a pasta que a contem, ou o arquivo `game`."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return os.path.dirname(path)
    if os.path.isdir(path):
        if os.path.isfile(os.path.join(path, "game")):
            return path
        inner = os.path.join(path, "save")
        if os.path.isfile(os.path.join(inner, "game")):
            return inner
    raise SystemExit(f"erro: nao achei um savegame em {path}\n"
                     f"       esperava um arquivo `game` ali dentro")


def take(save_path: str, label: str, root: str) -> dict:
    """Tira um snapshot rotulado. Devolve o metadado gravado."""
    src = _resolve_save_dir(save_path)
    dest = os.path.join(root, label)

    if os.path.exists(dest):
        raise SystemExit(f"erro: o snapshot '{label}' ja existe em {dest}\n"
                         f"       escolha outro rotulo ou apague o anterior")

    os.makedirs(root, exist_ok=True)
    shutil.copytree(src, dest)

    hashes = _hash_tree(dest)
    stable = {k: v for k, v in hashes.items()
              if os.path.basename(k) not in UNSTABLE}
    digest = hashlib.sha256(
        json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    meta = {
        "label": label,
        "source": src,
        "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": hashes,
        "digest": digest,
        "bytes": sum(os.path.getsize(os.path.join(dest, f)) for f in hashes),
    }
    with open(os.path.join(dest, "snapshot.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return meta


def load_all(root: str) -> list:
    """Metadados de todos os snapshots, mais antigo primeiro."""
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root)):
        meta_path = os.path.join(root, name, "snapshot.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        meta["path"] = os.path.join(root, name)
        out.append(meta)
    return sorted(out, key=lambda m: m.get("taken_at", ""))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="copia um savegame para a pasta de experimentos, com rotulo")
    ap.add_argument("save", nargs="?", help="pasta do save (ou o arquivo `game`)")
    ap.add_argument("label", nargs="?",
                    help="rotulo do snapshot, ex.: E2-antes")
    ap.add_argument("--root", default=DEFAULT_ROOT,
                    help="onde guardar (padrao: experiments/snapshots)")
    ap.add_argument("--list", action="store_true",
                    help="lista os snapshots ja tirados")
    ap.add_argument("--path", metavar="ROTULO",
                    help="imprime so o caminho de um snapshot, para usar em "
                         "outro comando")
    args = ap.parse_args()

    if args.path:
        dest = os.path.join(args.root, args.path)
        if not os.path.isdir(dest):
            print(f"erro: nao existe snapshot '{args.path}'", file=sys.stderr)
            return 1
        print(dest)
        return 0

    if args.list:
        snaps = load_all(args.root)
        if not snaps:
            print(f"nenhum snapshot em {args.root}")
            return 0
        print(f"{len(snaps)} snapshots em {args.root}\n")
        seen: dict[str, str] = {}
        for meta in snaps:
            mark = ""
            twin = seen.get(meta["digest"])
            if twin:
                # Dois snapshots identicos costumam ser erro de roteiro: o
                # jogo nao foi salvo entre um e outro.
                mark = f"  <- identico a {twin}"
            seen.setdefault(meta["digest"], meta["label"])
            size = meta.get("bytes", 0) / 1_000_000
            print(f"  {meta['label']:<20} {meta['taken_at']}  "
                  f"{size:6.2f} MB  {meta['digest']}{mark}")
        return 0

    if not args.save or not args.label:
        ap.error("informe a pasta do save e um rotulo "
                 "(ou use --list / --path)")

    meta = take(args.save, args.label, args.root)
    print(f"snapshot '{meta['label']}' gravado")
    print(f"  origem:  {meta['source']}")
    print(f"  destino: {os.path.join(args.root, meta['label'])}")
    print(f"  {len(meta['files'])} arquivos, "
          f"{meta['bytes'] / 1_000_000:.2f} MB, digest {meta['digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
