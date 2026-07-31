"""
As paginas da sala.

E o degrau 2 da secao 2.11, e o mais importante da estrategia de adocao: a
pessoa ve o mundo compartilhado vivo e decide se quer entrar, **sem instalar
nada**. Nao ha app, nao ha conta, nao ha download — so um endereco.

Por isso tudo aqui e HTML gerado no servidor, com o SVG do mapa desenhado em
Python. Sem build de frontend, sem framework, sem pacote de terceiro no
navegador: quem abrir o codigo-fonte da pagina entende o que ela faz. Numa
comunidade que — com razao — desconfia de aplicativo desconhecido, isso nao e
gosto pessoal, e argumento.

O mapa desenha os sistemas na posicao da estrela de cada um, e marca onde cada
jogador esta. As coordenadas vem da galaxia da sala, guardada uma vez quando o
primeiro save entrou.
"""

from __future__ import annotations

import html

# Tamanho do desenho. A galaxia medida tem 900000 x 400000, proporcao 2,25:1.
MAP_W = 900
MAP_PAD = 30


def _esc(valor) -> str:
    return html.escape(str(valor)) if valor is not None else ""


def layout(title: str, body: str, subtitle: str = "") -> str:
    """O molde comum. Escuro porque o assunto e um mapa estelar.

    ESCAPA o titulo. Quem chama passa texto cru — escapar dos dois lados
    produzia `&amp;lt;script&amp;gt;` na tela, que e seguro e ilegivel.
    `body` e `subtitle` vem prontos, com o HTML que o chamador montou.
    """
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ --bg:#0b1020; --fg:#e8ecf8; --dim:#8b93ad; --line:#232a45;
           --me:#6ee7b7; --on:#fbbf24; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width:60rem; margin:0 auto; padding:2rem 1.2rem 4rem; }}
  a {{ color:#93c5fd; }}
  h1 {{ font-size:1.6rem; margin:0 0 .2rem; }}
  h2 {{ font-size:1.05rem; margin:2.2rem 0 .6rem; font-weight:600; }}
  .sub {{ color:var(--dim); margin:0 0 1.6rem; }}
  table {{ width:100%; border-collapse:collapse; }}
  th,td {{ text-align:left; padding:.5rem .6rem; border-bottom:1px solid var(--line); }}
  th {{ color:var(--dim); font-weight:600; font-size:.85rem;
       text-transform:uppercase; letter-spacing:.04em; }}
  code {{ background:#161d38; padding:.15rem .4rem; border-radius:.25rem;
         font-size:.9em; }}
  pre {{ background:#161d38; padding:.9rem; border-radius:.4rem;
        overflow-x:auto; font-size:.85rem; }}
  .map {{ width:100%; height:auto; background:#070b17;
         border:1px solid var(--line); border-radius:.5rem; }}
  .cards {{ display:grid; gap:.8rem;
           grid-template-columns:repeat(auto-fill,minmax(15rem,1fr)); }}
  .card {{ border:1px solid var(--line); border-radius:.5rem; padding:.9rem; }}
  .card h3 {{ margin:0 0 .3rem; font-size:1rem; }}
  .tag {{ display:inline-block; font-size:.75rem; padding:.1rem .45rem;
         border-radius:1rem; background:#1c2540; color:var(--dim); }}
  .on {{ background:#3a2f0b; color:var(--on); }}
  footer {{ margin-top:3rem; padding-top:1.2rem; border-top:1px solid var(--line);
           color:var(--dim); font-size:.85rem; }}
</style>
<div class="wrap">
<h1>{_esc(title)}</h1>
<p class="sub">{subtitle}</p>
{body}
<footer>
<p><b>Space Haven</b> é um jogo da <a href="https://bugbyte.fi/">Bugbyte Ltd.</a>
Este é um projeto independente, feito por fã: não é oficial, não tem endosso e
não tem vínculo com ela. Nada aqui altera o jogo.</p>
<p><a href="/">salas</a> · <a href="/privacidade">o que acontece com o seu
save</a> · <a href="https://github.com/Gianotto/shared-galaxy">o código</a></p>
</footer>
</div></html>"""


def room_list(rooms: list) -> str:
    if not rooms:
        corpo = ("<p>Nenhuma sala aberta ainda. Quem criar a primeira define a "
                 "galáxia que todos vão dividir.</p>")
    else:
        cartoes = "".join(f"""
  <div class="card">
    <h3><a href="/sala/{_esc(r['id'])}">{_esc(r['name'])}</a></h3>
    <p class="sub" style="margin:0">
      {r['players']}/{r['max_players']} jogadores
      {'· <span class="tag">com senha</span>' if r['has_password'] else ''}
    </p>
  </div>""" for r in rooms)
        corpo = f'<div class="cards">{cartoes}</div>'
    return layout(
        "Galáxia Compartilhada", corpo,
        "Várias pessoas jogando Space Haven na mesma galáxia, cada uma no seu "
        "próprio jogo.")


def starmap_svg(galaxy: dict, roster: list) -> str:
    """O mapa da sala, desenhado no servidor.

    Cada sistema e um ponto na posicao da estrela dele. Onde ha jogador, o ponto
    vira um circulo maior com o nome da nave — e o `sname` e o que distingue um
    jogador do outro, porque nao existe identidade de jogador dentro do save.
    """
    sistemas = galaxy.get("systems") or []
    if not sistemas:
        return ('<p class="sub">O mapa aparece quando o primeiro jogador '
                'entrar: é o save dele que define a galáxia da sala.</p>')

    gw = galaxy.get("w") or max(s["x"] for s in sistemas) or 1
    gh = galaxy.get("h") or max(s["y"] for s in sistemas) or 1
    escala = (MAP_W - 2 * MAP_PAD) / gw
    altura = gh * escala + 2 * MAP_PAD

    def px(s):
        return MAP_PAD + s["x"] * escala, MAP_PAD + s["y"] * escala

    # Onde ha gente, por systemId.
    gente: dict = {}
    for p in roster:
        if p["at_system"]:
            gente.setdefault(str(p["at_system"]), []).append(p)

    pontos, marcas = [], []
    for s in sistemas:
        x, y = px(s)
        aqui = gente.get(str(s["systemId"]))
        titulo = _esc(s["name"] or f"sistema {s['systemId']}")
        if aqui:
            nomes = ", ".join(_esc(p["ship_name"] or p["display_name"])
                              for p in aqui)
            jogando = any(p["playing"] for p in aqui)
            cor = "var(--on)" if jogando else "var(--me)"
            marcas.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="none" '
                f'stroke="{cor}" stroke-width="1.5" opacity=".9">'
                f'<title>{titulo} — {nomes}</title></circle>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{cor}"/>'
                f'<text x="{x:.1f}" y="{y - 11:.1f}" fill="{cor}" '
                f'font-size="10" text-anchor="middle">{nomes}</text>')
        else:
            pontos.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" fill="#3d4a72" '
                f'opacity=".55"><title>{titulo}</title></circle>')

    return (f'<svg class="map" viewBox="0 0 {MAP_W} {altura:.0f}" '
            f'role="img" aria-label="mapa da galáxia da sala">'
            f'{"".join(pontos)}{"".join(marcas)}</svg>')


def room_page(room: dict, roster: list, galaxy: dict) -> str:
    mapa = starmap_svg(galaxy, roster)

    if roster:
        linhas = "".join(f"""
    <tr>
      <td>{_esc(p['display_name'])}</td>
      <td>{_esc(p['ship_name'] or '—')}</td>
      <td>{_esc(p['at_system'] or '—')}</td>
      <td>{_esc(p['at_celeid'] or '—')}</td>
      <td>{_esc(f"{float(p['game_day']):.1f}") if p['game_day'] else '—'}</td>
      <td>{'<span class="tag on">jogando</span>' if p['playing'] else ''}</td>
    </tr>""" for p in roster)
        tabela = f"""<table>
  <tr><th>jogador</th><th>nave</th><th>sistema</th><th>corpo</th>
      <th>dia</th><th></th></tr>{linhas}</table>"""
    else:
        tabela = ('<p class="sub">Ninguém entrou ainda. O primeiro save a subir '
                  'define a galáxia desta sala.</p>')

    receita = room.get("options") or {}
    itens = "".join(f"<li>{_esc(k)}: <b>{_esc(v)}</b></li>"
                    for k, v in sorted(receita.items()))
    como = f"""
<h2>Como entrar</h2>
<p>Crie uma partida no Space Haven com esta seed e estas opções. A seed reproduz
a galáxia inteira, mas não a sua tripulação nem a sua nave — mesmo universo,
gente diferente.</p>
<ul>
  <li>seed: <code>{_esc(room['seed'])}</code></li>
  {itens or '<li class="sub">o dono da sala ainda não publicou as opções</li>'}
</ul>
<p>Depois, suba o save:</p>
<pre>python3 tools/sgalaxy.py entrar {_esc(room['id'])} --save CAMINHO/DA/PARTIDA</pre>
<p class="sub">Opção de criação diferente dá outra galáxia, e o servidor recusa
o save — com o motivo.</p>""" if not room["password_hash"] else """
<h2>Como entrar</h2>
<p class="sub">Esta sala tem senha. Peça ao dono a seed e as opções de
criação.</p>"""

    corpo = f"""{mapa}
<h2>Quem está onde</h2>
{tabela}
{como}"""
    return layout(
        room["name"],
        corpo,
        f'sala <code>{_esc(room["id"])}</code> · '
        f'{len(roster)}/{room["max_players"]} jogadores · '
        f'empréstimo de {room["lease_hours"]}h')
