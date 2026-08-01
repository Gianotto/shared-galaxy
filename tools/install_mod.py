#!/usr/bin/env python3
"""
Instala (ou remove) o mod do Shared Galaxy na sua cópia do Space Haven.

POR QUE ISTO EXISTE

O Mod Loader do Workshop faz este trabalho, e faria melhor. Só que o item
publicado é um build de Windows — `spacehaven-modloader.exe`, `python311.dll`,
`.pyd` — e quem joga no Linux não consegue rodá-lo. Como o que ele faz é curto e
verificável, está reproduzido aqui.

O QUE ELE FAZ, MEDIDO

O lançador do jogo é um ELF que lê `config.json` ao lado dele. O arquivo tem três
campos, e um jogo sem mod nenhum se parece com isto:

    {"classPath": ["spacehaven.jar"],
     "mainClass": "fi.bugbyte.spacehaven.steam.SpacehavenSteam",
     "vmArgs": ["-Xmx4G"]}

Instalar um mod de código é, inteiro:

    1. deixar o `aspectjweaver` ao lado do jogo
    2. acrescentar `-javaagent:./aspectjweaver-<versão>.jar` a `vmArgs`
    3. acrescentar o jar do mod a `classPath`

O agente lê o `META-INF/aop.xml` de cada jar do classpath e tece os aspectos nas
classes do jogo conforme elas carregam.

ISTO MEXE NA SUA INSTALAÇÃO

O resto do projeto não toca no jogo. Isto toca — é a exceção, e por isso guarda
um backup de `config.json` antes de escrever, e `--uninstall` desfaz tudo. Uma
verificação do Steam também desfaz, sem drama.

    python3 tools/install_mod.py --dry-run
    python3 tools/install_mod.py
    python3 tools/install_mod.py --uninstall
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

AGENT_PREFIX = "-javaagent:./aspectjweaver"
MOD_JAR = "SharedGalaxy.jar"
BACKUP = "config.json.sgalaxy-backup"

GAME_PATHS = [
    os.environ.get("SPACEHAVEN_DIR", ""),
    os.path.expanduser("~/snap/steam/common/.local/share/Steam/steamapps/"
                       "common/SpaceHaven"),
    os.path.expanduser("~/.steam/steam/steamapps/common/SpaceHaven"),
    os.path.expanduser("~/.local/share/Steam/steamapps/common/SpaceHaven"),
]

LOADER_PATHS = [
    os.environ.get("SPACEHAVEN_MODLOADER", ""),
    os.path.expanduser("~/snap/steam/common/.local/share/Steam/steamapps/"
                       "workshop/content/979110/3703674043"),
    os.path.expanduser("~/.steam/steam/steamapps/workshop/content/979110/"
                       "3703674043"),
]


class ModError(Exception):
    pass


def como_chamar() -> str:
    """Como a pessoa chamou isto, para a mensagem apontar para o lugar certo."""
    if getattr(sys, "frozen", False):
        return f"{os.path.basename(sys.argv[0])} install-mod"
    return "python3 tools/install_mod.py"


def find_game() -> str:
    for path in GAME_PATHS:
        if path and os.path.isfile(os.path.join(path, "spacehaven.jar")):
            return path
    raise ModError("não achei a pasta do Space Haven. Aponte SPACEHAVEN_DIR "
                   "para ela")


def find_weaver() -> str:
    """O `aspectjweaver` vem do Mod Loader, que quase todo mundo já assina.

    Não baixamos nada: se o Mod Loader não estiver assinado, a mensagem diz
    exatamente o que fazer. Um instalador que sai buscando jar na internet é
    outra categoria de coisa.
    """
    for path in LOADER_PATHS:
        if not path or not os.path.isdir(path):
            continue
        for name in sorted(os.listdir(path)):
            if re.fullmatch(r"aspectjweaver-[\d.]+\.jar", name):
                return os.path.join(path, name)
    raise ModError(
        "não achei o aspectjweaver. Ele vem com o SpaceHaven Mod Loader: "
        "assine em steamcommunity.com/sharedfiles/filedetails/?id=3703674043 "
        "e deixe o Steam baixar, ou aponte SPACEHAVEN_MODLOADER para a pasta")


def find_mod_jar() -> str:
    """O jar do mod: embutido no binário, ou construído no repositório.

    O binário publicado leva o jar dentro (`sys._MEIPASS` é onde o PyInstaller
    o desempacota), para o jogador baixar uma coisa só. Rodando a partir do
    repositório, é o que `mod/build.sh` produziu.
    """
    candidatos = []
    embutido = getattr(sys, "_MEIPASS", None)
    if embutido:
        candidatos.append(os.path.join(embutido, MOD_JAR))
    candidatos.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "mod", "build", MOD_JAR))
    for caminho in candidatos:
        if os.path.isfile(caminho):
            return caminho
    raise ModError(f"{MOD_JAR} não foi compilado ainda. Rode mod/build.sh")


def read_config(game: str) -> dict:
    path = os.path.join(game, "config.json")
    if not os.path.isfile(path):
        raise ModError(f"{path} não existe; esta pasta não parece o jogo")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_config(game: str, config: dict) -> None:
    path = os.path.join(game, "config.json")
    backup = os.path.join(game, BACKUP)
    if not os.path.isfile(backup):
        shutil.copy2(path, backup)
    # Grava num temporário e troca: um config.json truncado por queda de energia
    # deixa o jogo sem abrir, e ele não é nosso para quebrar.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def plan_install(config: dict, weaver_name: str, mod_jar_name: str) -> dict:
    """O `config.json` como ele ficaria. Função pura, para poder ser conferida."""
    novo = json.loads(json.dumps(config))
    vm_args = list(novo.get("vmArgs") or [])
    class_path = list(novo.get("classPath") or [])

    agent = f"-javaagent:./{weaver_name}"
    # Um agente por vez: reinstalar não pode empilhar `-javaagent` repetido.
    vm_args = [a for a in vm_args if not a.startswith(AGENT_PREFIX)]
    vm_args.append(agent)

    if mod_jar_name not in class_path:
        class_path.append(mod_jar_name)

    novo["vmArgs"] = vm_args
    novo["classPath"] = class_path
    return novo


def plan_uninstall(config: dict, mod_jar_name: str) -> dict:
    """Tira o que pusemos e não encosta no resto.

    Só remove o `-javaagent` do aspectjweaver e o NOSSO jar. Quem tiver outros
    mods de código continua com eles — e é por isso que isto não repõe o backup
    cegamente.
    """
    novo = json.loads(json.dumps(config))
    novo["vmArgs"] = [a for a in (novo.get("vmArgs") or [])
                      if not a.startswith(AGENT_PREFIX)]
    novo["classPath"] = [c for c in (novo.get("classPath") or [])
                         if os.path.basename(c) != mod_jar_name]
    return novo


def other_code_mods(config: dict, mod_jar_name: str) -> list:
    return [c for c in (config.get("classPath") or [])
            if c != "spacehaven.jar" and os.path.basename(c) != mod_jar_name]


def install(game: str, dry_run: bool) -> int:
    weaver = find_weaver()
    mod_jar = find_mod_jar()
    config = read_config(game)

    weaver_name = os.path.basename(weaver)
    novo = plan_install(config, weaver_name, MOD_JAR)

    print(f"jogo:   {game}")
    print(f"weaver: {weaver}")
    print(f"mod:    {mod_jar}")
    print()
    print("config.json ficaria assim:")
    print(f"  vmArgs:    {novo['vmArgs']}")
    print(f"  classPath: {novo['classPath']}")

    if dry_run:
        print("\n(--dry-run: nada foi escrito)")
        return 0

    for origem in (weaver, mod_jar):
        destino = os.path.join(game, os.path.basename(origem))
        if not (os.path.isfile(destino)
                and os.path.getsize(destino) == os.path.getsize(origem)):
            shutil.copy2(origem, destino)
            print(f"copiado {os.path.basename(origem)}")

    write_config(game, novo)
    print(f"\ninstalado. O backup do config original está em {BACKUP}.")
    print(f"Para desfazer: {como_chamar()} --uninstall")
    return 0


def uninstall(game: str, dry_run: bool) -> int:
    config = read_config(game)
    novo = plan_uninstall(config, MOD_JAR)

    restantes = other_code_mods(novo, MOD_JAR)
    if restantes:
        print(f"atenção: ainda há outros jars no classPath ({restantes}).")
        print("O -javaagent foi removido e eles vão parar de funcionar.")
        print("Rode o Mod Loader depois, ou reinstale-os.")

    print("config.json ficaria assim:")
    print(f"  vmArgs:    {novo['vmArgs']}")
    print(f"  classPath: {novo['classPath']}")
    if dry_run:
        print("\n(--dry-run: nada foi escrito)")
        return 0

    write_config(game, novo)
    alvo = os.path.join(game, MOD_JAR)
    if os.path.isfile(alvo):
        os.remove(alvo)
        print(f"removido {MOD_JAR}")
    print("\ndesinstalado. O aspectjweaver.jar foi deixado onde estava: "
          "ele é do Mod Loader, não nosso.")
    return 0


def status(game: str) -> int:
    config = read_config(game)
    tem_agente = any(a.startswith(AGENT_PREFIX)
                     for a in (config.get("vmArgs") or []))
    tem_mod = any(os.path.basename(c) == MOD_JAR
                  for c in (config.get("classPath") or []))
    print(f"jogo:      {game}")
    print(f"javaagent: {'sim' if tem_agente else 'não'}")
    print(f"mod:       {'sim' if tem_mod else 'não'}")
    print(f"vmArgs:    {config.get('vmArgs')}")
    print(f"classPath: {config.get('classPath')}")
    return 0 if (tem_agente and tem_mod) else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="instala o mod do Shared Galaxy no Space Haven")
    ap.add_argument("--game", help="pasta do jogo (senão procura sozinho)")
    ap.add_argument("--dry-run", action="store_true",
                    help="mostra o que faria, sem escrever")
    ap.add_argument("--uninstall", action="store_true", help="desfaz")
    ap.add_argument("--status", action="store_true", help="só informa")
    args = ap.parse_args()

    try:
        game = args.game or find_game()
        if args.status:
            return status(game)
        if args.uninstall:
            return uninstall(game, args.dry_run)
        return install(game, args.dry_run)
    except ModError as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
