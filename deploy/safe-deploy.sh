#!/usr/bin/env bash
#
# Implanta o servidor, e RECUSA enquanto alguem estiver jogando.
#
# Reiniciar a API no meio de uma sessao ja custou uma devolucao a um jogador:
# o `checkin` bateu no contêiner subindo e voltou como traceback. Eu conferia o
# numero de emprestimos abertos, via "1", e implantava assim mesmo — porque
# conferir e decidir sao coisas diferentes, e so uma delas estava no script.
#
#   deploy/safe-deploy.sh            recusa se houver sessao aberta
#   deploy/safe-deploy.sh --force    para quando voce sabe o que esta fazendo
set -euo pipefail

HOST="${SGALAXY_HOST:-essentia}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

abertos=$(ssh "$HOST" "cd ~/shared-galaxy && docker compose exec -T db \
    psql -U sgalaxy -d sgalaxy -tAc \
    \"select count(*) from lease where state='open'\"" 2>/dev/null | tr -d '[:space:]')

if [ "${abertos:-0}" != "0" ] && [ "${1:-}" != "--force" ]; then
    echo "RECUSADO: $abertos sessão(ões) aberta(s) neste momento." >&2
    ssh "$HOST" "cd ~/shared-galaxy && docker compose exec -T db \
        psql -U sgalaxy -d sgalaxy -c \
        \"select l.id, p.display_name, l.expires_at from lease l \
          join player p on p.id = l.player_id where l.state='open'\"" >&2
    echo >&2
    echo "Alguém está jogando. Espere a devolução, ou use --force." >&2
    exit 1
fi

rsync -az --delete \
    --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.env' --exclude 'mod/build' --exclude 'client/dist' \
    "$RAIZ/" "$HOST:~/shared-galaxy/"

ssh "$HOST" "cd ~/shared-galaxy && docker compose build -q api && docker compose up -d api"
sleep 4
ssh "$HOST" "curl -sS localhost:8714/api/v1/health"
echo
