"""Onde o Steam guardou o Space Haven, em qualquer um dos três sistemas.

POR QUE ISTO EXISTE

As duas ferramentas procuravam o jogo numa lista de caminhos de Linux escrita à
mão. No Windows a busca falhava sempre, e a mensagem dizia "não achei a pasta do
Space Haven", o que é verdade e não ajuda: quem baixou um binário para jogar não
tem por que saber o caminho de instalação de uma biblioteca do Steam.

COMO

O Steam mantém `libraryfolders.vdf` com todas as bibliotecas que a pessoa
configurou, inclusive as em outro disco. Ler esse arquivo acha o jogo onde quer
que ele esteja, e de quebra acha o item do Workshop, porque os dois penduram na
mesma raiz:

    <biblioteca>/steamapps/common/SpaceHaven
    <biblioteca>/steamapps/workshop/content/979110/<id>

O `.vdf` é um formato do Steam, não JSON. O que precisamos dele são as linhas
`"path"  "C:\\\\Games\\\\Steam"`, e uma expressão regular resolve sem trazer
biblioteca de parsing para um projeto que é de biblioteca padrão.

Ler o `.vdf` pode falhar por permissão ou por formato novo; quando falha, a
lista de sempre continua valendo, e `SPACEHAVEN_DIR` continua tendo a palavra
final.
"""

from __future__ import annotations

import os
import re
import sys

APP_ID = "979110"
GAME_DIR_NAME = "SpaceHaven"

# O nome do executável muda por sistema, o resto da árvore não.
LAUNCHER = "spacehaven.exe" if sys.platform == "win32" else "spacehaven"


def _steam_roots() -> list:
    """Onde o Steam pode ter sido instalado, por sistema."""
    if sys.platform == "win32":
        programas = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files")]
        return [os.path.join(p, "Steam") for p in programas if p] + [
            r"C:\Steam", os.path.expanduser("~/scoop/apps/steam/current")]
    if sys.platform == "darwin":
        return [os.path.expanduser("~/Library/Application Support/Steam")]
    return [
        os.path.expanduser("~/snap/steam/common/.local/share/Steam"),
        os.path.expanduser("~/.steam/steam"),
        os.path.expanduser("~/.local/share/Steam"),
        os.path.expanduser("~/.var/app/com.valvesoftware.Steam/data/Steam"),
    ]


def libraries() -> list:
    """Toda biblioteca do Steam nesta máquina, a padrão e as de outro disco."""
    achadas = []
    for raiz in _steam_roots():
        if not os.path.isdir(raiz):
            continue
        if raiz not in achadas:
            achadas.append(raiz)
        vdf = os.path.join(raiz, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as fh:
                texto = fh.read()
        except OSError:
            continue
        # "path"    "D:\\SteamLibrary"
        for bruto in re.findall(r'"path"\s+"([^"]+)"', texto):
            caminho = bruto.replace("\\\\", os.sep).replace("\\", os.sep)
            if os.path.isdir(caminho) and caminho not in achadas:
                achadas.append(caminho)
    return achadas


def game_dir() -> str | None:
    """A pasta do Space Haven, ou None.

    `SPACEHAVEN_DIR` ganha de tudo: quem tem uma cópia fora do Steam, ou duas
    instalações, precisa de uma forma de dizer qual.
    """
    forcado = os.environ.get("SPACEHAVEN_DIR", "").strip()
    if forcado and os.path.isfile(os.path.join(forcado, "spacehaven.jar")):
        return forcado
    for biblioteca in libraries():
        alvo = os.path.join(biblioteca, "steamapps", "common", GAME_DIR_NAME)
        if os.path.isfile(os.path.join(alvo, "spacehaven.jar")):
            return alvo
    return None


def launcher() -> str | None:
    """O executável que abre o jogo, ou None."""
    forcado = os.environ.get("SPACEHAVEN_BIN", "").strip()
    if forcado and os.path.isfile(forcado):
        return forcado
    pasta = game_dir()
    if not pasta:
        return None
    exe = os.path.join(pasta, LAUNCHER)
    return exe if os.path.isfile(exe) else None


def workshop_item(item_id: str) -> str | None:
    """A pasta de um item do Workshop assinado, ou None."""
    forcado = os.environ.get("SPACEHAVEN_MODLOADER", "").strip()
    if forcado and os.path.isdir(forcado):
        return forcado
    for biblioteca in libraries():
        alvo = os.path.join(biblioteca, "steamapps", "workshop", "content",
                            APP_ID, item_id)
        if os.path.isdir(alvo):
            return alvo
    return None


def savegames_dir() -> str | None:
    """Onde o jogo guarda os saves. Fica ao lado do executável, nos três."""
    pasta = game_dir()
    if not pasta:
        return None
    alvo = os.path.join(pasta, "savegames")
    return alvo if os.path.isdir(alvo) else None
