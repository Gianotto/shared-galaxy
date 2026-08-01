#!/usr/bin/env bash
#
# Empacota o cliente como um executável único.
#
# POR QUE
#
# O cliente é um arquivo Python de biblioteca padrão, e rodar `python3
# tools/sgalaxy.py` é o caminho honesto: quem quiser conferir o que sobe para o
# servidor lê o arquivo inteiro em vinte minutos. Só que a maioria de quem joga
# Space Haven está no Windows e não tem Python instalado, e um convite de
# Discord que começa por "instale o Python" não é um convite.
#
# É o mesmo formato que o próprio SpaceHaven Mod Loader publica, então a
# comunidade já aceita esse jeito de receber ferramenta.
#
# O FONTE CONTINUA SENDO A VERDADE
#
# O binário não substitui `tools/sgalaxy.py`, empacota. Um executável esconde o
# que faz, e a promessa de transparência do projeto vale mais que a conveniência
# — por isso o README aponta os dois caminhos, e o binário é construído a partir
# do arquivo que está no repositório, pela receita que está aqui.
#
# Windows não sai daqui: o PyInstaller não faz compilação cruzada, então o .exe
# é construído pelo GitHub Actions numa máquina Windows
# (.github/workflows/release.yml). Este script faz o de Linux.
#
#   client/build.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(dirname "$HERE")"
OUT="$HERE/dist"

rm -rf "$OUT"
mkdir -p "$OUT"

docker run --rm \
    -v "$RAIZ:/src" -w /tmp \
    -e HOME=/tmp -e DONO="$(id -u):$(id -g)" \
    python:3.11-slim bash -c '
        set -e
        # O PyInstaller precisa do objdump para varrer as dependencias do ELF.
        apt-get -qq update && apt-get -qq install -y --no-install-recommends \
            binutils > /dev/null
        pip install --quiet --disable-pip-version-check pyinstaller
        # O jar do mod vai dentro: o jogador baixa uma coisa só. Ele compila
        # sem o jogo (tudo nele é reflexão), então o CI consegue produzi-lo.
        EXTRA=""
        if [ -f /src/mod/build/SharedGalaxy.jar ]; then
            EXTRA="--add-data /src/mod/build/SharedGalaxy.jar:."
        fi
        python -m PyInstaller \
            --onefile --clean --noconfirm \
            --name sgalaxy \
            --paths /src/tools \
            --hidden-import install_mod \
            $EXTRA \
            --distpath /src/client/dist \
            --workpath /tmp/build \
            --specpath /tmp \
            /src/tools/sgalaxy.py
        chown -R "$DONO" /src/client/dist
    '

echo
"$OUT/sgalaxy" --help > /dev/null && echo "roda: $OUT/sgalaxy"
ls -la "$OUT/sgalaxy" | awk '{print "  " $5 " bytes"}'
