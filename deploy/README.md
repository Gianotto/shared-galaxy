# Hospedar a Galáxia Compartilhada

O servidor é um container que escuta em `127.0.0.1:8714`, e mais um Postgres.
`compose.yml` na raiz levanta os dois.

```bash
cp .env.example .env      # edite: senha do banco, e os segredos abaixo
docker compose up -d
docker compose exec -T db psql -U sgalaxy -d sgalaxy -f /dev/stdin < migrations/001_initial.sql
```

As migrações rodam sozinhas na primeira subida do banco, pela pasta
`migrations/` montada em `docker-entrypoint-initdb.d`. Depois disso, cada
arquivo novo é aplicado à mão, em ordem.

## Chegar de fora

A porta fica no loopback de propósito. Para expor, ponha um proxy reverso na
frente ou saia por um túnel. As duas rotas funcionam, e a segunda dispensa abrir
porta no firewall.

O que o proxy precisa fazer:

- passar `Host`, e passar o endereço real de quem pediu em `CF-Connecting-IP` ou
  `X-Forwarded-For`. Sem isso o servidor vê apenas o gateway do Docker, e o
  limite de uma conta por endereço passa a valer para o mundo inteiro de uma vez.
- aceitar corpo grande no upload: um savegame passa de 20 MB.
- não impor tempo curto de leitura. Um check-in envia o save inteiro.

## Variáveis que mudam o comportamento

| Variável | Efeito |
|---|---|
| `SGALAXY_INVITE_ONLY` | exige código de convite para criar conta. Vazio deixa aberto |
| `SGALAXY_IP_PEPPER` | segredo do HMAC de endereço. Vazio desliga o limite por endereço |
| `SGALAXY_MAX_PER_IP` | quantas contas por endereço. Padrão 1 |
| `SGALAXY_BIND` | interface do container. Padrão `127.0.0.1` |
| `SGALAXY_PORT` | porta publicada. Padrão `8714` |

## Publicar uma versão nova

`safe-deploy.sh` sincroniza o repositório com a máquina e reinicia a API. Ele
recusa enquanto houver sessão aberta, porque reiniciar no meio de uma sessão
interrompe o check-in de quem está jogando. `--force` passa por cima.

O destino sai de `SGALAXY_HOST`. Guarde o seu em `deploy/local.env`, que o
script lê e o git ignora:

```bash
echo 'SGALAXY_HOST=meu-servidor' > deploy/local.env
./deploy/safe-deploy.sh
```

A configuração de nginx e de túnel desta instalação fica fora do repositório: é
o domínio e os caminhos de uma máquina só, e não ajuda ninguém a rodar a sua.
