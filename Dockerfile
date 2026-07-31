# Imagem do servidor. Fina de propósito: quem auto-hospeda deve conseguir ler o
# arquivo inteiro e entender o que roda na própria máquina.
FROM python:3.13-slim

WORKDIR /app

# Dependências primeiro, para a camada de cache sobreviver a mudança de código.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY sgalaxy/ sgalaxy/
COPY migrations/ migrations/

# Não roda como root. O processo só precisa ler o código e escrever no volume
# de saves.
RUN useradd --system --uid 10001 sgalaxy \
 && mkdir -p /data/blobs \
 && chown -R sgalaxy:sgalaxy /data
USER sgalaxy

EXPOSE 8714
CMD ["uvicorn", "server.api.app:app", "--host", "0.0.0.0", "--port", "8714"]
