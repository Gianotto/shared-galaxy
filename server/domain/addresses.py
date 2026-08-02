"""De onde veio quem pediu, e como guardar isso sem guardar endereço de gente.

Está aqui, e não dentro da API, porque é decisão pura: entra um pedido, sai um
texto. Dentro do `app.py` só se testaria com banco levantado, e esta é
justamente a parte que precisa de teste — errar aqui não quebra nada de forma
visível, apenas faz o limite proteger a coisa errada.
"""

from __future__ import annotations

import hashlib
import hmac


def client_ip(request) -> str | None:
    """O endereço de quem pediu, atravessando o tunnel.

    ISTO É A PARTE QUE ERRA SOZINHA.

    O servidor recebe tudo por um tunnel do Cloudflare, e do lado de dentro
    TODA requisição chega como `172.22.0.1`, o gateway do Docker — medido nos
    logs. Um limite por `request.client.host` não daria uma conta por pessoa:
    daria UMA CONTA PARA O SERVIDOR INTEIRO, e quem se inscrevesse primeiro
    trancaria a porta para todo o resto do mundo.

    `CF-Connecting-IP` é escrito pelo Cloudflare e sobrescrito por ele mesmo
    quando o cliente tenta forjar. Vale enquanto o tunnel for a única entrada;
    quem alcançar a porta diretamente na LAN pode mentir, e para esse caso o
    limite por endereço não é a defesa certa de qualquer forma.
    """
    for header in ("cf-connecting-ip", "true-client-ip"):
        valor = (request.headers.get(header) or "").strip()
        if valor:
            return valor
    # O primeiro da lista é o cliente; o resto são os proxies do caminho.
    encaminhado = (request.headers.get("x-forwarded-for") or "").split(",")
    if encaminhado and encaminhado[0].strip():
        return encaminhado[0].strip()
    return request.client.host if getattr(request, "client", None) else None


def fingerprint(ip: str | None, pepper: str) -> str | None:
    """A impressão do endereço — nunca o endereço.

    HMAC com um segredo do servidor, e não um sha256 puro, porque um IPv4 tem
    quatro bilhões de candidatos: um hash sem segredo se reverte por força
    bruta em segundos, e aí o banco passaria a guardar de onde cada pessoa se
    inscreveu. A pergunta que precisamos responder é só "este endereço já
    apareceu", e o HMAC responde exatamente essa.

    Sem segredo devolve None, e quem chama trata isso como "sem limite":
    preferimos registrar aberto a guardar endereço em claro.
    """
    if not ip or not pepper:
        return None
    return hmac.new(pepper.encode(), ip.encode(), hashlib.sha256).hexdigest()
