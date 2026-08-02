#!/usr/bin/env python3
"""Gera a imagem de vitrine do item do Workshop.

Desenha o mapa estelar de uma galáxia de verdade, lido de um save, com o nome
do projeto por cima. Biblioteca padrão apenas: PNG é `zlib` mais um cabeçalho,
e a fonte é um bitmap de 5x7 escrito aqui embaixo. Trazer Pillow para o projeto
por causa de uma imagem seria caro pelo motivo errado.

    python3 mod/workshop/make_preview.py CAMINHO/DO/save

Sem argumento, procura um save na instalação local. Se não achar nenhum, cai
num campo de estrelas gerado por uma semente fixa, para o comando nunca falhar
por falta de save.
"""

from __future__ import annotations

import os
import random
import struct
import sys
import xml.etree.ElementTree as ET
import zlib

LARGURA, ALTURA = 1000, 615
FUNDO = (11, 16, 32)
ESTRELA = (168, 192, 240)
DESTAQUE = (110, 231, 183)
TEXTO = (232, 236, 248)

# Fonte 5x7, só o que o título usa. Cada string é uma linha de pixels.
FONTE = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    ",": ["00000", "00000", "00000", "00000", "00110", "00010", "00100"],
    ".": ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    " ": ["00000"] * 7,
}


class Tela:
    def __init__(self, largura: int, altura: int, cor: tuple):
        self.w, self.h = largura, altura
        self.px = bytearray(bytes(cor) * largura * altura)

    def ponto(self, x: int, y: int, cor: tuple, alpha: float = 1.0) -> None:
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        i = (y * self.w + x) * 3
        for c in range(3):
            atual = self.px[i + c]
            self.px[i + c] = int(atual + (cor[c] - atual) * alpha)

    def disco(self, cx: float, cy: float, raio: float, cor: tuple,
              alpha: float = 1.0) -> None:
        for y in range(int(cy - raio) - 1, int(cy + raio) + 2):
            for x in range(int(cx - raio) - 1, int(cx + raio) + 2):
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if d <= raio:
                    self.ponto(x, y, cor, alpha)
                elif d <= raio + 1:          # borda suave, sem serrilhado duro
                    self.ponto(x, y, cor, alpha * (raio + 1 - d))

    def anel(self, cx: float, cy: float, raio: float, cor: tuple) -> None:
        passos = max(24, int(raio * 8))
        for i in range(passos):
            ang = 6.28318 * i / passos
            self.ponto(int(cx + raio * _cos(ang)), int(cy + raio * _sin(ang)),
                       cor, 0.9)

    def texto(self, s: str, x: int, y: int, escala: int, cor: tuple) -> None:
        for letra in s.upper():
            glifo = FONTE.get(letra)
            if glifo is None:
                x += 6 * escala
                continue
            for ly, linha in enumerate(glifo):
                for lx, bit in enumerate(linha):
                    if bit == "1":
                        for dy in range(escala):
                            for dx in range(escala):
                                self.ponto(x + lx * escala + dx,
                                           y + ly * escala + dy, cor)
            x += (len(glifo[0]) + 1) * escala

    def png(self) -> bytes:
        linhas = b"".join(
            b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3])
            for y in range(self.h))

        def bloco(tipo: bytes, dados: bytes) -> bytes:
            c = tipo + dados
            return (struct.pack(">I", len(dados)) + c
                    + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n"
                + bloco(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h,
                                             8, 2, 0, 0, 0))
                + bloco(b"IDAT", zlib.compress(linhas, 9))
                + bloco(b"IEND", b""))


def _sin(a: float) -> float:
    import math
    return math.sin(a)


def _cos(a: float) -> float:
    import math
    return math.cos(a)


def estrelas_do_save(caminho: str) -> list:
    """As posições das estrelas, normalizadas em 0..1."""
    raiz = ET.parse(os.path.join(caminho, "game")).getroot()
    mapa = raiz.find("starmap")
    w = float(mapa.get("w") or 900000)
    h = float(mapa.get("h") or 400000)
    pontos = []
    for sistema in mapa.find("systems"):
        estrela = next((b for b in sistema.findall("bodies/l")
                        if b.get("type") == "Star"), None)
        if estrela is None or not estrela.get("x"):
            continue
        pontos.append((float(estrela.get("x")) / w,
                       float(estrela.get("y")) / h))
    return pontos


def estrelas_inventadas() -> list:
    """Um campo com semente fixa, para o comando funcionar sem save à mão."""
    rng = random.Random(6359)
    return [(rng.random(), rng.random()) for _ in range(64)]


def achar_save() -> str | None:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "tools"))
    try:
        import steamfind
    except ImportError:
        return None
    pasta = steamfind.savegames_dir()
    if not pasta:
        return None
    for nome in sorted(os.listdir(pasta)):
        alvo = os.path.join(pasta, nome, "save")
        if os.path.isfile(os.path.join(alvo, "game")):
            return alvo
    return None


def main() -> int:
    origem = sys.argv[1] if len(sys.argv) > 1 else achar_save()
    if origem and os.path.isfile(os.path.join(origem, "game")):
        pontos = estrelas_do_save(origem)
        de_onde = origem
    else:
        pontos = estrelas_inventadas()
        de_onde = "campo gerado (nenhum save encontrado)"

    tela = Tela(LARGURA, ALTURA, FUNDO)
    margem = 60
    for i, (nx, ny) in enumerate(pontos):
        x = margem + nx * (LARGURA - 2 * margem)
        y = margem + ny * (ALTURA - 2 * margem)
        tela.disco(x, y, 1.8, ESTRELA, 0.55)
        # Dois sistemas marcados como habitados: é do que o projeto trata.
        if i in (7, 23):
            tela.disco(x, y, 3.0, DESTAQUE, 0.95)
            tela.anel(x, y, 7, DESTAQUE)

    tela.texto("SHARED GALAXY", 62, ALTURA - 150, 9, TEXTO)
    tela.texto("ONE GALAXY, MANY PLAYERS", 64, ALTURA - 62, 4, DESTAQUE)

    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "preview.png")
    with open(destino, "wb") as fh:
        fh.write(tela.png())
    print(f"{destino}  ({os.path.getsize(destino)} bytes)")
    print(f"estrelas: {len(pontos)}  de {de_onde}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
