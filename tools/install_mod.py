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
import subprocess
import sys

import steamfind

AGENT_PREFIX = "-javaagent:./aspectjweaver"
MOD_JAR = "SharedGalaxy.jar"
BACKUP = "config.json.sgalaxy-backup"

# O item do Workshop que traz o AspectJ. Sem ele nao ha mod de codigo neste
# jogo, e nao baixamos nada: a mensagem diz onde assinar.
LOADER_ITEM = "3703674043"


class ModError(Exception):
    pass


def como_chamar() -> str:
    """Como a pessoa chamou isto, para a mensagem apontar para o lugar certo."""
    if getattr(sys, "frozen", False):
        return f"{os.path.basename(sys.argv[0])} install-mod"
    return "python3 tools/install_mod.py"


def game_is_running() -> str | None:
    """O nome do processo do jogo, se ele estiver aberto.

    Mesma leitura do cliente: `spacehaven` é o lançador nativo e
    `spacehaven.jar` é a JVM que ele levanta.
    """
    if shutil.which("pgrep") is None:
        return None
    meus = {str(os.getpid()), str(os.getppid())}
    for args, nome in ((["-x", "spacehaven"], "spacehaven"),
                       (["-f", "spacehaven.jar"], "spacehaven.jar")):
        try:
            out = subprocess.run(["pgrep", *args], capture_output=True,
                                 timeout=5, text=True)
        except (subprocess.SubprocessError, OSError):
            continue
        if out.returncode == 0 and {p for p in out.stdout.split()
                                    if p and p not in meus}:
            return nome
    return None


def find_game() -> str:
    pasta = steamfind.game_dir()
    if pasta:
        return pasta
    raise ModError("could not find the Space Haven folder. If it lives "
                   "outside Steam, or you have two copies, point "
                   "SPACEHAVEN_DIR at the folder holding spacehaven.jar")


def find_weaver() -> str:
    """O `aspectjweaver` vem do Mod Loader, que quase todo mundo já assina.

    Não baixamos nada: se o Mod Loader não estiver assinado, a mensagem diz
    exatamente o que fazer. Um instalador que sai buscando jar na internet é
    outra categoria de coisa.
    """
    path = steamfind.workshop_item(LOADER_ITEM)
    if path:
        for name in sorted(os.listdir(path)):
            if re.fullmatch(r"aspectjweaver-[\d.]+\.jar", name):
                return os.path.join(path, name)
    raise ModError(
        "could not find aspectjweaver. It ships with the SpaceHaven Mod "
        "Loader: subscribe at "
        "steamcommunity.com/sharedfiles/filedetails/?id=3703674043 and let "
        "Steam download it, or point SPACEHAVEN_MODLOADER at the folder")


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
    raise ModError(f"{MOD_JAR} has not been built yet. Run mod/build.sh")


def read_config(game: str) -> dict:
    path = os.path.join(game, "config.json")
    if not os.path.isfile(path):
        raise ModError(f"{path} does not exist, so this does not look like the "
                       f"game folder")
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
    # A JVM lê o jar UMA VEZ, ao abrir. Trocá-lo com o jogo rodando não muda
    # nada até reiniciar — e faz alguém testar a versão anterior achando que
    # testa a nova. Custou uma rodada de teste antes desta trava existir.
    aberto = game_is_running()
    if aberto and not dry_run:
        raise ModError(
            f"Space Haven is open ({aberto}). The JVM loads the mod at "
            f"startup, so installing now would change nothing this session, "
            f"and you would test the old version. Close the game and try "
            f"again")

    weaver = find_weaver()
    mod_jar = find_mod_jar()
    config = read_config(game)

    weaver_name = os.path.basename(weaver)
    novo = plan_install(config, weaver_name, MOD_JAR)

    print(f"game:   {game}")
    print(f"weaver: {weaver}")
    print(f"mod:    {mod_jar}")
    print()
    print("config.json would end up like this:")
    print(f"  vmArgs:    {novo['vmArgs']}")
    print(f"  classPath: {novo['classPath']}")

    if dry_run:
        print("\n(--dry-run: nothing was written)")
        return 0

    for origem in (weaver, mod_jar):
        destino = os.path.join(game, os.path.basename(origem))
        if not (os.path.isfile(destino)
                and os.path.getsize(destino) == os.path.getsize(origem)):
            shutil.copy2(origem, destino)
            print(f"copied {os.path.basename(origem)}")

    write_config(game, novo)
    print(f"\ninstalled. The original config is backed up as {BACKUP}.")
    print(f"To undo it: {como_chamar()} --uninstall")
    return 0


def uninstall(game: str, dry_run: bool) -> int:
    config = read_config(game)
    novo = plan_uninstall(config, MOD_JAR)

    restantes = other_code_mods(novo, MOD_JAR)
    if restantes:
        print(f"warning: other jars remain on the classPath ({restantes}).")
        print("The -javaagent is gone, so they will stop working.")
        print("Run the Mod Loader afterwards, or reinstall them.")

    print("config.json would end up like this:")
    print(f"  vmArgs:    {novo['vmArgs']}")
    print(f"  classPath: {novo['classPath']}")
    if dry_run:
        print("\n(--dry-run: nothing was written)")
        return 0

    write_config(game, novo)
    alvo = os.path.join(game, MOD_JAR)
    if os.path.isfile(alvo):
        os.remove(alvo)
        print(f"removido {MOD_JAR}")
    print("\nuninstalled. aspectjweaver.jar was left where it was, because "
          "it belongs to the Mod Loader.")
    return 0


def status(game: str) -> int:
    config = read_config(game)
    tem_agente = any(a.startswith(AGENT_PREFIX)
                     for a in (config.get("vmArgs") or []))
    tem_mod = any(os.path.basename(c) == MOD_JAR
                  for c in (config.get("classPath") or []))
    print(f"game:      {game}")
    print(f"javaagent: {'yes' if tem_agente else 'no'}")
    print(f"mod:       {'yes' if tem_mod else 'no'}")
    print(f"vmArgs:    {config.get('vmArgs')}")
    print(f"classPath: {config.get('classPath')}")
    return 0 if (tem_agente and tem_mod) else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="install the Shared Galaxy mod into Space Haven")
    ap.add_argument("--game", help="game folder (found on its own otherwise)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what it would do, without writing")
    ap.add_argument("--uninstall", action="store_true", help="undo it")
    ap.add_argument("--status", action="store_true", help="report only")
    args = ap.parse_args()

    try:
        game = args.game or find_game()
        if args.status:
            return status(game)
        if args.uninstall:
            return uninstall(game, args.dry_run)
        return install(game, args.dry_run)
    except ModError as erro:
        print(f"error: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
