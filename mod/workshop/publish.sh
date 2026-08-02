#!/usr/bin/env bash
#
# Publica o mod no Steam Workshop, via steamcmd.
#
# O LOGIN É SEU. Este script não recebe senha, não guarda credencial e não
# automatiza Steam Guard: ele chama o `steamcmd`, que pergunta o que precisa no
# terminal e mantém a sessão em cache para as próximas vezes.
#
#   mod/workshop/publish.sh SEU_USUARIO_STEAM
#
# A PRIMEIRA PUBLICAÇÃO CRIA O ITEM COMO PRIVADO, de propósito. O Workshop não
# tem desfazer: um item publicado já foi visto, já pode ter sido assinado, e o
# id fica. Privado deixa você abrir a página, conferir a descrição, a imagem e
# os arquivos, e só então mudar a visibilidade no navegador.
#
# Depois da primeira vez, o Steam devolve um `publishedfileid`. Guarde-o em
# mod/workshop/published_id.txt e as próximas execuções atualizam o mesmo item
# em vez de criar outro.

set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"
CONTEUDO="$RAIZ/mod/build/workshop"
APP_ID=979110

USUARIO="${1:-${STEAM_USER:-}}"
if [ -z "$USUARIO" ]; then
    echo "uso: mod/workshop/publish.sh SEU_USUARIO_STEAM" >&2
    exit 2
fi

command -v steamcmd >/dev/null 2>&1 || {
    echo "steamcmd não está instalado." >&2
    echo "  Ubuntu/Debian: sudo apt install steamcmd" >&2
    echo "  Arch:          sudo pacman -S steamcmd" >&2
    echo "  Windows:       baixe steamcmd.zip da Valve e rode este passo lá" >&2
    exit 1
}

# O conteúdo tem que ser o que o build produziu, e não o que sobrou de antes.
"$RAIZ/mod/build.sh" >/dev/null
cp "$AQUI/preview.png" "$CONTEUDO/preview.png"

for obrigatorio in info.xml SharedGalaxy.jar preview.png; do
    [ -f "$CONTEUDO/$obrigatorio" ] || {
        echo "faltou $obrigatorio em $CONTEUDO" >&2; exit 1; }
done

ID_FILE="$AQUI/published_id.txt"
PUBLICADO=0
VISIBILIDADE=2      # 0 público, 1 amigos, 2 privado
if [ -f "$ID_FILE" ]; then
    PUBLICADO="$(tr -dc '0-9' < "$ID_FILE")"
    # Numa atualização a visibilidade fica como está no site: mudá-la aqui
    # tornaria privado de novo um item que você já abriu ao público.
    VISIBILIDADE=""
fi

TITULO="$(python3 - "$AQUI/info.xml" <<'PY'
import sys, xml.etree.ElementTree as ET
print(ET.parse(sys.argv[1]).getroot().findtext("name").strip())
PY
)"
DESCRICAO="$(python3 - "$AQUI/info.xml" <<'PY'
import sys, xml.etree.ElementTree as ET, textwrap
bruto = ET.parse(sys.argv[1]).getroot().findtext("description")
# Uma linha em branco separa parágrafos; dentro do parágrafo, junta.
saida = []
for bloco in bruto.strip().split("\n\n"):
    linhas = [l.strip() for l in bloco.splitlines()]
    if any(l.startswith("-") for l in linhas):
        saida.append("\n".join(l for l in linhas if l))
    else:
        saida.append(" ".join(l for l in linhas if l))
print("\n\n".join(saida))
PY
)"

VDF="$(mktemp -t sgalaxy-workshop-XXXX.vdf)"
trap 'rm -f "$VDF"' EXIT
{
    echo '"workshopitem"'
    echo '{'
    echo "    \"appid\" \"$APP_ID\""
    echo "    \"publishedfileid\" \"$PUBLICADO\""
    echo "    \"contentfolder\" \"$CONTEUDO\""
    echo "    \"previewfile\" \"$CONTEUDO/preview.png\""
    [ -n "$VISIBILIDADE" ] && echo "    \"visibility\" \"$VISIBILIDADE\""
    echo "    \"title\" \"$TITULO\""
    printf '    "description" "%s"\n' "${DESCRICAO//\"/\\\"}"
    echo "    \"changenote\" \"$(git -C "$RAIZ" describe --tags --always)\""
    echo '}'
} > "$VDF"

echo "conteúdo: $CONTEUDO"
ls -la "$CONTEUDO"
echo
if [ "$PUBLICADO" = "0" ]; then
    echo "Isto CRIA um item novo, privado. Nada fica visível até você abrir"
    echo "a visibilidade na página do item, no navegador."
else
    echo "Isto ATUALIZA o item $PUBLICADO. A visibilidade atual é mantida."
fi
echo
read -r -p "seguir? [s/N] " resposta
[ "$resposta" = "s" ] || { echo "cancelado."; exit 0; }

steamcmd +login "$USUARIO" +workshop_build_item "$VDF" +quit

echo
echo "Se o Steam devolveu um PublishedFileId novo, guarde-o:"
echo "  echo NUMERO > $ID_FILE"
