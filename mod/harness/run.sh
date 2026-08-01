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

# rodar <rótulo> <marcador|-> <esperado> <ms-de-execução> [props extras]
rodar() {
    local rotulo="$1" marcador="$2" esperado="$3" duracao="$4" props="${5:-}"
    local notas="${6:-}"
    echo "$rotulo"
    if [ "$marcador" = "-" ]; then rm -f "$WORK/sharedgalaxy.autoload"
    else printf '%s\n' "$marcador" > "$WORK/sharedgalaxy.autoload"; fi
    if [ -n "$notas" ]; then printf '%s\n' "$notas" > "$WORK/sharedgalaxy.log"
    else rm -f "$WORK/sharedgalaxy.log"; fi
    docker run --rm --user "$(id -u):$(id -g)" \
        -v "$WORK:/h" -v "$AJ:/aj:ro" -v "$JAR:/mod.jar:ro" -w /h \
        eclipse-temurin:8-jdk sh -c '
            javac -d /h $(find /h -name "*.java") &&
            java -javaagent:/aj/aspectjweaver.jar '"$props"' \
                 -cp /h:/mod.jar:/aj/aspectjrt.jar \
                 fi.bugbyte.spacehaven.gui.menu.GameMenu '"$esperado $duracao"'
        ' 2>&1 | grep -vE '^\[AppClassLoader'
}

# O primeiro é o defeito que chegou ao jogador, com os dois erros juntos: o
# menu só existe depois de um tempo, e o laço roda a 144Hz — um prazo contado
# em frames estoura antes de o menu aparecer.
rodar "menu que só aparece depois do disclaimer, a 144Hz:" \
      "Sala-6359GV" "Sala-6359GV" 3000 "-Dharness.menusAfterMs=1500"
rodar "primeiro acesso, abre o criador de partida:" \
      "__new__" "__new__" 2000 "-Dharness.menusAfterMs=400"
rodar "sem marcador, o jogo se comporta como sem mod:" \
      "-" "-" 800 "-Dharness.menusAfterMs=200"
rodar "as linhas do cliente aparecem no log do jogo:" \
      "Sala-6359GV" "Sala-6359GV" 2500 \
      "-Dharness.menusAfterMs=400 -Dharness.notes=1" \
      "Shared Galaxy — room 6359GV, save v6"
rodar "menu que nunca aparece, desiste sem travar o jogo:" \
      "Sala-6359GV" "-" 2000 "-Dharness.menusAfterMs=999999 -Dsharedgalaxy.giveup.ms=300"
