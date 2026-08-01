#!/usr/bin/env bash
#
# Builds SharedGalaxy.jar.
#
# Everything runs in containers, so the only thing you need installed is Docker
# and the game — no JDK, no AspectJ, no Maven.
#
# Two Java versions, on purpose:
#
#   - ajc 1.9.19 needs Java 11+ to RUN
#   - the game runs a bundled Java 8 JRE and its classes are Java 7 bytecode,
#     so the mod has to be COMPILED for Java 8
#
# Hence a JDK 21 container running ajc with `-source 8 -target 8` and the game's
# own rt.jar as the bootclasspath. The mods already published for this game are
# built the same way: their manifests say JDK 21 and their classes are v52.
#
# Usage: mod/build.sh [--verify]
#
#   --verify  also checks that every method the aspect reaches by reflection
#             still exists in this installation's spacehaven.jar

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/build"

GAME="${SPACEHAVEN_DIR:-$HOME/snap/steam/common/.local/share/Steam/steamapps/common/SpaceHaven}"
LOADER="${SPACEHAVEN_MODLOADER:-$HOME/snap/steam/common/.local/share/Steam/steamapps/workshop/content/979110/3703674043}"

# The game jar is NOT needed to compile: every call into the game is
# reflective and the pointcut is a string, so nothing here names a game type.
# It is needed to VERIFY, which is the point of --verify, and for the
# bootclasspath when it is around.
GAME_JAR=""
if [ -f "$GAME/spacehaven.jar" ]; then
    GAME_JAR="$GAME/spacehaven.jar"
elif [ "${1:-}" = "--verify" ]; then
    echo "--verify needs the game: spacehaven.jar not found under $GAME" >&2
    echo "set SPACEHAVEN_DIR to the game folder" >&2
    exit 1
fi
[ -f "$LOADER/aspectj-1.9.19.jar" ] || {
    echo "the mod loader's aspectj-1.9.19.jar was not found under $LOADER" >&2
    echo "subscribe to the SpaceHaven Mod Loader, or set SPACEHAVEN_MODLOADER" >&2
    exit 1
}

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/aj"

# ajc and aspectjrt live inside the loader's aspectj jar, under files/lib.
( cd "$OUT/aj" && unzip -oq "$LOADER/aspectj-1.9.19.jar" 'files/lib/*' )
AJ="$OUT/aj/files/lib"

if [ -n "$GAME_JAR" ]; then
    MONTA_JOGO="-v $GAME:/game:ro"
    EXTRA="-bootclasspath /game/jre/lib/rt.jar -classpath /aj/aspectjrt.jar:/game/spacehaven.jar"
else
    echo "the game was not found; compiling without it (only --verify needs it)"
    MONTA_JOGO=""
    EXTRA="-classpath /aj/aspectjrt.jar"
fi

# shellcheck disable=SC2086
docker run --rm --user "$(id -u):$(id -g)" \
    -v "$HERE:/mod" -v "$AJ:/aj:ro" $MONTA_JOGO \
    eclipse-temurin:21-jdk \
    java -cp /aj/aspectjtools.jar org.aspectj.tools.ajc.Main \
        -source 8 -target 8 -Xlint:ignore $EXTRA \
        -d /mod/build/classes \
        /mod/src/com/sharedgalaxy/AutoLoadAspect.java

mkdir -p "$OUT/classes/META-INF"
cp "$HERE/META-INF/aop.xml" "$OUT/classes/META-INF/aop.xml"

docker run --rm --user "$(id -u):$(id -g)" -v "$HERE:/mod" eclipse-temurin:21-jdk \
    jar cf /mod/build/SharedGalaxy.jar -C /mod/build/classes .

echo "built $OUT/SharedGalaxy.jar"

if [ "${1:-}" = "--verify" ]; then
    echo
    docker run --rm --user "$(id -u):$(id -g)" \
        -v "$HERE:/mod" -v "$GAME:/game:ro" -v "$AJ:/aj:ro" \
        eclipse-temurin:8-jdk sh -c '
            mkdir -p /tmp/v &&
            javac -d /tmp/v /mod/verify/VerifyTargets.java &&
            java -cp /tmp/v:/game/spacehaven.jar VerifyTargets'
fi

if [ "${1:-}" = "--test" ]; then
    echo
    # Exercita o aspecto de ponta a ponta contra um dublê com a mesma forma do
    # jogo. É o que faltava quando a primeira versão foi para as mãos de alguém
    # e falhou com "the game has no Load menu": não havia como rodar a reflexão
    # inteira sem abrir o jogo, então o defeito só aparecia lá.
    "$HERE/harness/run.sh" "$AJ" "$OUT/SharedGalaxy.jar"
fi
