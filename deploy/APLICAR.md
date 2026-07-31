# Expor a Galáxia Compartilhada em galaxy.bygianotto.com.br

Os comandos abaixo precisam de `sudo`. O container já está de pé em
`127.0.0.1:8714` e não muda nada aqui — o que estes passos fazem é abrir o
caminho de fora até ele.

Antes de rodar: confira que o DNS `galaxy.bygianotto.com.br` já aponta para o
túnel no painel da Cloudflare (CNAME para `<id-do-túnel>.cfargotunnel.com`, ou
criado pelo próprio `cloudflared tunnel route dns`). Sem isso, o resto funciona
e o navegador não chega.

## 1. nginx

```bash
sudo cp ~/shared-galaxy/deploy/sgalaxy_limits.conf /etc/nginx/conf.d/
sudo cp ~/shared-galaxy/deploy/proxy_sgalaxy.conf  /etc/nginx/
sudo cp ~/shared-galaxy/deploy/nginx-galaxy.conf \
        /etc/nginx/sites-available/galaxy.bygianotto.com.br
sudo ln -sf /etc/nginx/sites-available/galaxy.bygianotto.com.br \
            /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

O `nginx -t` tem que dizer `syntax is ok` e `test is successful`. Se reclamar de
zona desconhecida, o `sgalaxy_limits.conf` não chegou em `/etc/nginx/conf.d/`.

## 2. cloudflared

```bash
sudo cp /etc/cloudflared/config.yml /etc/cloudflared/config.yml.bak-galaxy
sudo nano /etc/cloudflared/config.yml
```

Acrescente no bloco `ingress:`, **antes** do catch-all `http_status:404` — a
ordem importa, porque o cloudflared usa a primeira regra que casar:

```yaml
  # nginx :80 — Galáxia Compartilhada
  - hostname: galaxy.bygianotto.com.br
    service: http://localhost:80
```

Depois:

```bash
sudo cloudflared tunnel ingress validate
sudo systemctl restart cloudflared
```

## 3. Conferir

```bash
curl -s -H 'Host: galaxy.bygianotto.com.br' http://127.0.0.1/api/v1/health
curl -s https://galaxy.bygianotto.com.br/api/v1/health
```

Os dois devem responder `{"status":"ok",...}`. O primeiro prova o nginx; o
segundo prova o túnel.

## Desfazer

```bash
sudo rm /etc/nginx/sites-enabled/galaxy.bygianotto.com.br
sudo systemctl reload nginx
sudo cp /etc/cloudflared/config.yml.bak-galaxy /etc/cloudflared/config.yml
sudo systemctl restart cloudflared
```
