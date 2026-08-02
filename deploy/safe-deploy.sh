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

# O destino nao vive no repositorio: e o nome de uma maquina, e o repositorio e
# publico. `deploy/local.env` fica no disco de quem hospeda e o git o ignora.
if [ -f "$(dirname "${BASH_SOURCE[0]}")/local.env" ]; then
    # shellcheck disable=SC1090
    . "$(dirname "${BASH_SOURCE[0]}")/local.env"
fi
HOST="${SGALAXY_HOST:-}"
if [ -z "$HOST" ]; then
    echo "defina SGALAXY_HOST, ou escreva-o em deploy/local.env:" >&2
    echo "  echo 'SGALAXY_HOST=meu-servidor' > deploy/local.env" >&2
    exit 2
fi
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Uma consulta so, numa viagem so. Com duas, a devolucao de alguem cai entre
# elas e a recusa se contradiz — medido: "RECUSADO: 1 sessao" acima de uma
# tabela com zero linhas.
sessoes=$(ssh "$HOST" "cd ~/shared-galaxy && docker compose exec -T db \
    psql -U sgalaxy -d sgalaxy -tAc \
    \"select l.id || ' | ' || coalesce(p.display_name, '?') || ' | ' \
             || l.expires_at from lease l \
       left join player p on p.id = l.player_id where l.state='open'\"" \
    2>/dev/null)

abertos=$(printf '%s' "$sessoes" | grep -c . || true)

if [ "${abertos:-0}" != "0" ] && [ "${1:-}" != "--force" ]; then
    echo "RECUSADO: $abertos sessão(ões) aberta(s) neste momento." >&2
    printf '%s\n' "$sessoes" >&2
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
