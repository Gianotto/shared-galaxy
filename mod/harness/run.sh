#!/usr/bin/env bash
#
# Roda o aspecto contra um dublê do jogo, sob o weaver de verdade.
#
# Três cenários, e o primeiro é o defeito que chegou ao jogador: os menus do
# jogo não existem nos primeiros frames, e agir por contagem de frames falha
# com "the game has no Load menu".

set -euo pipefail

AJ="$1"
JAR="$2"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cp -r "$HERE"/fi "$WORK/"

rodar() {   # rodar <rótulo> <conteúdo-do-marcador|-> <esperado> <frames>
    local rotulo="$1" marcador="$2" esperado="$3" frames="$4"
    echo "$rotulo"
    if [ "$marcador" = "-" ]; then rm -f "$WORK/sharedgalaxy.autoload"
    else printf '%s\n' "$marcador" > "$WORK/sharedgalaxy.autoload"; fi
    docker run --rm --user "$(id -u):$(id -g)" \
        -v "$WORK:/h" -v "$AJ:/aj:ro" -v "$JAR:/mod.jar:ro" -w /h \
        eclipse-temurin:8-jdk sh -c '
            javac -d /h $(find /h -name "*.java") &&
            java -javaagent:/aj/aspectjweaver.jar \
                 -cp /h:/mod.jar:/aj/aspectjrt.jar \
                 fi.bugbyte.spacehaven.gui.menu.GameMenu '"$esperado $frames"'
        ' 2>&1 | grep -vE '^\[AppClassLoader'
}

rodar "menu que só existe tarde (o defeito que chegou ao jogador):" \
      "Sala-6359GV" "Sala-6359GV" 400
rodar "primeiro acesso, abre o criador de partida:" \
      "__new__" "__new__" 400
rodar "sem marcador, jogo se comporta como sem mod:" \
      "-" "-" 400
rodar "menu que nunca aparece, desiste sem travar:" \
      "Sala-6359GV" "-" 100
