"""
The room pages.

This is step 2 of section 2.11, and the most important part of the adoption
plan: someone sees the shared world alive and decides whether to join, **without
installing anything**. No app, no account, no download — just an address.

That is why everything here is server-rendered HTML with the map's SVG drawn in
Python. No frontend build, no framework, no third-party package in the browser:
whoever opens the page source understands what it does. In a community that —
rightly — distrusts unknown applications, that is an argument, not a taste.

The map places each system at its star's position and marks where each player
is. Coordinates come from the room's galaxy, stored once when the first save
arrived.
"""

from __future__ import annotations

import html

from server.web.i18n import t

# Drawing size. The measured galaxy is 900000 x 400000, a 2.25:1 ratio.
MAP_W = 900
MAP_PAD = 30


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


# Icones do menu. Desenhados aqui, em `stroke="currentColor"`, para seguirem a
# cor do link sem uma regra a mais — e para nao existir um pedido de rede por
# um arquivo de icone. O site inteiro se serve sozinho, e isso e um argumento
# numa comunidade que — com razao — desconfia de aplicativo desconhecido.
ICONS = {
    "nav_rooms":
        '<circle cx="12" cy="12" r="8"/>'
        '<ellipse cx="12" cy="12" rx="10" ry="4"/>',
    "nav_client":
        '<path d="M12 3v11"/><path d="M8 11l4 4 4-4"/>'
        '<path d="M4 18v2h16v-2"/>',
    "nav_recovery":
        '<circle cx="8" cy="12" r="4"/>'
        '<path d="M12 12h9"/><path d="M17 12v3"/><path d="M20 12v2"/>',
    "nav_privacy":
        '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "nav_how":
        '<circle cx="12" cy="12" r="9"/>'
        '<path d="M9.5 9.5a2.6 2.6 0 113.2 2.5c-.5.2-.7.6-.7 1.1v.4"/>'
        '<path d="M12 17h.01"/>',
}


def icon(chave: str) -> str:
    desenho = ICONS.get(chave)
    if not desenho:
        return ""
    return (f'<svg viewBox="0 0 24 24" width="15" height="15" fill="none" '
            f'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{desenho}</svg>')


def layout(title: str, body: str, lang: str, subtitle: str = "",
           path: str = "/", action: str = "") -> str:
    """The shared shell.

    ESCAPES the title. Callers pass raw text — escaping on both sides produced
    `&amp;lt;script&amp;gt;` on screen, which is safe and unreadable. `body` and
    `subtitle` arrive as finished HTML.
    """
    other = "pt" if lang == "en" else "en"
    sep = "&" if "?" in path else "?"
    switch = (f'<a href="{_esc(path)}{sep}lang={other}">'
              f'{"Português" if other == "pt" else "English"}</a>')

    # O MENU. Antes disto cada pagina terminava num par de links soltos, e as
    # de sala so ofereciam saida depois do mapa inteiro — um scroll longo antes
    # de existir um caminho de volta. Uma pessoa que chega por um convite nao
    # deveria ter que adivinhar o que mais existe aqui.
    menu = "".join(
        f'<a href="{destino}?lang={lang}"'
        f'{" class=here" if path == destino else ""}>'
        f'{icon(chave)}{t(chave, lang)}</a>'
        for destino, chave in (("/", "nav_rooms"),
                               ("/how-it-works", "nav_how"),
                               ("/client", "nav_client"),
                               ("/recovery", "nav_recovery"),
                               ("/privacy", "nav_privacy")))
    return f"""<!doctype html><html lang="{lang}"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ --bg:#0b1020; --fg:#e8ecf8; --dim:#8b93ad; --line:#232a45;
           --me:#6ee7b7; --on:#fbbf24; }}
  a.cta {{ display:inline-block; padding:.6rem 1.1rem; border-radius:.35rem;
    background:#3b6fd4; color:#fff; text-decoration:none; font-weight:600;
    white-space:nowrap; }}
  /* O titulo e a acao na mesma linha, a acao encostada a direita. Quebra para
     duas linhas sozinha quando a tela e estreita, sem media query. */
  .titlebar {{ display:flex; flex-wrap:wrap; gap:.8rem 1.2rem;
    align-items:flex-start; justify-content:space-between; }}
  .titlebar .sub {{ margin-bottom:1.2rem; }}
  header.nav {{ display:flex; flex-wrap:wrap; gap:.6rem 1.4rem;
    align-items:baseline; justify-content:space-between;
    padding:.9rem 0 1rem; margin-bottom:1.4rem;
    border-bottom:1px solid var(--line); }}
  header.nav nav {{ display:flex; flex-wrap:wrap; gap:1.1rem; }}
  header.nav a {{ color:var(--dim); text-decoration:none;
    display:inline-flex; align-items:center; gap:.4rem; }}
  header.nav a:hover {{ color:var(--fg); }}
  header.nav a.here {{ color:var(--fg); font-weight:600; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width:60rem; margin:0 auto; padding:2rem 1.2rem 4rem; }}
  a {{ color:#93c5fd; }}
  h1 {{ font-size:1.6rem; margin:0 0 .2rem; }}
  h2 {{ font-size:1.05rem; margin:2.2rem 0 .6rem; font-weight:600; }}
  .sub {{ color:var(--dim); margin:0 0 1.6rem; }}
  .lang {{ float:right; font-size:.85rem; }}
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
  /* Caixa de informação no hover, como a do jogo. CSS puro: sem JavaScript,
     porque a página inteira se sustenta em ser legível no código-fonte. */
  .sys .tip {{ opacity:0; pointer-events:none; transition:opacity .12s; }}
  .sys:hover .tip {{ opacity:1; }}
  .sys:hover .dot {{ r:4; }}
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
<header class="nav">
  <nav>{menu}</nav>
  <span class="lang">{switch}</span>
</header>
<div class="titlebar">
  <div><h1>{_esc(title)}</h1><p class="sub">{subtitle}</p></div>
  {action}
</div>
{body}
<footer>
<p>{t("disclaimer", lang)}</p>
<p><a href="/?lang={lang}">{t("rooms", lang)}</a> ·
   <a href="/privacy?lang={lang}">{t("privacy_link", lang)}</a> ·
   <a href="https://github.com/Gianotto/shared-galaxy">{t("code", lang)}</a></p>
</footer>
</div></html>"""


def room_list(rooms: list, lang: str) -> str:
    if not rooms:
        body = f'<p>{t("no_rooms", lang)}</p>'
    else:
        cards = "".join(f"""
  <div class="card">
    <h3><a href="/room/{_esc(r['id'])}?lang={lang}">{_esc(r['name'])}</a></h3>
    <p class="sub" style="margin:0">
      {r['players']}/{r['max_players']} {t("players", lang)}
      {f'· <span class="tag">{t("has_password", lang)}</span>' if r['has_password'] else ''}
    </p>
    <p style="margin:.6rem 0 0"><a href="/room/{_esc(r['id'])}/join?lang={lang}"
       >{t("join_this", lang)}</a></p>
  </div>""" for r in rooms)
        body = f'<div class="cards">{cards}</div>'
    body += (f'<p style="margin-top:2rem">'
             f'<a href="/register?lang={lang}">{t("create_account", lang)}</a>'
             f' · <a href="/new-room?lang={lang}">{t("new_room", lang)}</a></p>')
    return layout(t("site", lang), body, lang, t("tagline", lang), "/")


# Tooltip geometry. Everything is drawn, not styled by a layout engine, so the
# numbers live here instead of being scattered through the f-strings.
TIP_LINE = 13
TIP_PAD = 7
TIP_CHAR = 5.6          # average glyph width at 10px in the UI font
TIP_MAX_SHIPS = 5       # beyond this the box stops being readable


def _system_group(x: float, y: float, title: str, people: list,
                  seen: dict | None, map_h: float, lang: str) -> str:
    """One system: its hover target and the box that appears over it.

    The box is the game's own idiom — system name, then who is there. Pure
    SVG and CSS, no JavaScript: the whole page rests on being readable from
    view-source, and a tooltip is not worth breaking that for.
    """
    lines = [title]
    if seen and seen.get("first_by"):
        lines.append(f'{t("first_here", lang)}: {seen["first_by"]}')
    # A box with sixty-four names is as unreadable as an inline list of them.
    # Everyone starts on the same rock (findings 16), so this is the normal
    # opening state of a full room, not an edge case.
    #
    # Sorted by age, oldest first: in a crowd the interesting ones are the
    # colonies that have been out here longest, not whoever the database
    # happened to return first.
    by_age = sorted(people, key=lambda p: -(p.get("age_days") or 0))
    for p in by_age[:TIP_MAX_SHIPS]:
        # The ACCOUNT name leads, the ship name follows in brackets. `sname` is
        # free text the player can change in-game, so it cannot carry identity:
        # someone renaming their ship to a neighbour's would otherwise become
        # that neighbour on this map. The account name is the server's, and
        # nobody can edit it into someone else's.
        who = p["display_name"]
        ship = p["ship_name"]
        age = p.get("age_days")
        mark = " ●" if p["playing"] else ""
        suffix = f'  {float(age):.0f}d' if age else ""
        label = f"{who} ({ship})" if ship and ship != who else who
        lines.append(f"{label}{suffix}{mark}")
    if len(people) > TIP_MAX_SHIPS:
        lines.append(t("and_more", lang).format(n=len(people) - TIP_MAX_SHIPS))
    if not people and not seen:
        lines.append(t("never_reached", lang))

    w = max(len(l) for l in lines) * TIP_CHAR + 2 * TIP_PAD
    h = len(lines) * TIP_LINE + 2 * TIP_PAD - 3

    # Flip the box so it never leaves the drawing. A tooltip clipped by the
    # edge is a tooltip that fails exactly where the map is most crowded.
    bx = x + 12 if x + 12 + w < MAP_W else x - 12 - w
    by = y - h / 2
    by = max(4.0, min(by, map_h - h - 4))

    rows = "".join(
        f'<text x="{bx + TIP_PAD:.1f}" y="{by + TIP_PAD + 10 + i * TIP_LINE:.1f}" '
        f'fill="{"#e8ecf8" if i == 0 else "#a9b4d0"}" font-size="10" '
        f'{"font-weight=\"600\"" if i == 0 else ""}>{_esc(line)}</text>'
        for i, line in enumerate(lines))

    return (f'<g class="sys">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" fill="transparent"/>'
            f'<g class="tip">'
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="4" fill="#111a35" stroke="#3d4a72" opacity=".97"/>'
            f'{rows}</g></g>')


def starmap_svg(galaxy: dict, roster: list, lang: str,
                visits: dict | None = None) -> str:
    """The room map, drawn on the server.

    Each system is a dot at its star's position. Where there are players, the
    dot becomes a larger circle labelled with the ship name — and `sname` is
    what tells one player from another, because there is no player identity
    inside a save.
    """
    systems = galaxy.get("systems") or []
    if not systems:
        return f'<p class="sub">{t("map_later", lang)}</p>'

    gw = galaxy.get("w") or max(s["x"] for s in systems) or 1
    gh = galaxy.get("h") or max(s["y"] for s in systems) or 1
    scale = (MAP_W - 2 * MAP_PAD) / gw
    height = gh * scale + 2 * MAP_PAD

    def px(s):
        """Do sistema de coordenadas do jogo para o do SVG.

        O Y PRECISA VIRAR. Medido contra o mapa estelar do proprio jogo, no
        save de um jogador: `Strange Kallisti Border` (y=232444) aparece ACIMA
        de `The Major Sotlax Wreath` (y=213259), que aparece acima de `Magic
        Garuda Territory` (y=150263). Ou seja, no jogo Y maior e mais alto na
        tela — o eixo cresce para cima. Em SVG ele cresce para baixo.

        Desenhar direto entregava um mapa espelhado na vertical, que e pior que
        nao ter mapa: parece confiavel e manda a pessoa para o lado errado.
        """
        return MAP_PAD + s["x"] * scale, MAP_PAD + (gh - s["y"]) * scale

    visits = visits or {}
    here: dict = {}
    for p in roster:
        if p["at_system"]:
            here.setdefault(str(p["at_system"]), []).append(p)

    # Ordem de desenho importa: SVG nao tem z-index, entao o que vem depois
    # cobre o que veio antes. Os pontos vao primeiro e os grupos com caixa
    # depois, senao a caixa de um sistema fica atras do vizinho.
    dots, groups = [], []
    for s_ in systems:
        x, y = px(s_)
        people = here.get(str(s_["systemId"]), [])
        seen = visits.get(str(s_["systemId"]))
        title = s_["name"] or f'system {s_["systemId"]}'

        if people:
            playing = any(p["playing"] for p in people)
            colour = "var(--on)" if playing else "var(--me)"
            # One name reads; a list does not. More than one becomes a count,
            # and the box on hover has the detail.
            if len(people) == 1:
                label = _esc(people[0]["display_name"])
            else:
                label = f'{len(people)} {t("players", lang)}'
            dots.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="none" '
                f'stroke="{colour}" stroke-width="1.5" opacity=".9"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{colour}"/>'
                f'<text x="{x:.1f}" y="{y - 11:.1f}" fill="{colour}" '
                f'font-size="10" text-anchor="middle">{label}</text>')
        elif seen:
            dots.append(
                f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="3" '
                f'fill="#a8c0f0" opacity=".9"/>')
        else:
            dots.append(
                f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="1.8" '
                f'fill="#5a6ba0" opacity=".55"/>')

        groups.append(_system_group(x, y, title, people, seen, height, lang))
    legend = (f'<p class="sub" style="margin:.5rem 0 0;font-size:.85rem">'
              f'{t("map_legend", lang)}</p>')
    return (f'<svg class="map" viewBox="0 0 {MAP_W} {height:.0f}" '
            f'role="img" aria-label="galaxy map">'
            f'{"".join(dots)}{"".join(groups)}</svg>{legend}')


def room_page(room: dict, roster: list, galaxy: dict, lang: str,
              visits: dict | None = None, just_made: bool = False) -> str:
    map_svg = starmap_svg(galaxy, roster, lang, visits)
    banner = (f'<p style="background:#16304a;border:1px solid #2b5b86;'
              f'padding:.8rem;border-radius:.4rem">'
              f'{t("owner_next", lang)}</p>' if just_made else '')


    # O nome do sistema, que e o que o jogador ve no mapa estelar do jogo. O
    # `at_system` e um id interno e o `at_body` e um nome de tipo — nenhum dos
    # dois aparece na tela dele, e uma tabela cheia de vocabulario nosso nao
    # ajuda ninguem a achar um vizinho.
    nomes = {str(s_["systemId"]): (s_.get("name") or "")
             for s_ in (galaxy.get("systems") or [])}

    def onde(p) -> str:
        if not p["at_system"]:
            return "—"
        # O mesmo recuo do mapa, para as duas telas falarem igual. Na pratica e
        # raro: os nomes chegam todos de uma vez, cedo (findings item 15).
        return nomes.get(str(p["at_system"])) or f'system {p["at_system"]}'

    if roster:
        rows = "".join(f"""
    <tr>
      <td>{_esc(p['display_name'])}</td>
      <td>{_esc(p['ship_name'] or '—')}</td>
      <td>{_esc(onde(p))}</td>
      <td>{_esc(f"{float(p['age_days']):.1f} {t('days', lang)}") if p['age_days'] else '—'}</td>
      <td>{f'<span class="tag on">{t("playing", lang)}</span>' if p['playing'] else ''}</td>
    </tr>""" for p in roster)
        table = f"""<table>
  <tr><th>{t("th_player", lang)}</th><th>{t("th_ship", lang)}</th>
      <th>{t("th_system", lang)}</th>
      <th>{t("th_age", lang)}</th><th></th></tr>{rows}</table>"""
    else:
        table = f'<p class="sub">{t("nobody_yet", lang)}</p>'

    # A RECEITA saiu daqui: ela ensinava a criar a partida pela seed e
    # terminava num `python3 tools/sgalaxy.py`, comando de quem tem o
    # repositorio e nao de quem baixou um binario. O que fica e o botao — ver a
    # sala e o degrau 2, entrar e o 3, e a pagina de entrada e que sabe falar
    # de cada sistema operacional.
    # Na mesma linha do nome da sala, encostado a direita: e a unica coisa que
    # uma pessoa de fora pode FAZER nesta tela, e no corpo ela ficava separada
    # do que a identifica.
    entrar = (f'<a class="cta" href="/room/{_esc(room["id"])}/join'
              f'?lang={lang}">{t("join_this", lang)}</a>')

    body = f"""{banner}{map_svg}
<h2>{t("who_is_where", lang)}</h2>
{table}"""
    return layout(
        room["name"], body, lang,
        f'{t("room", lang)} <code>{_esc(room["id"])}</code> · '
        f'{len(roster)}/{room["max_players"]} {t("players", lang)} · '
        f'{t("lease_of", lang)} {room["lease_hours"]}h',
        f'/room/{room["id"]}', entrar)


# ---------------------------------------------------------------------------
# The data policy
# ---------------------------------------------------------------------------

# Section 2.11 says to write this **before** it exists, in plain language, where
# people read it before joining. The savegame editor promises nothing leaves
# your computer; this server breaks that promise, and pretending otherwise would
# be the worst possible mistake.
#
# It lives here as prose rather than in i18n.py because it is two pages of text,
# not a handful of labels, and a policy split across dozens of dictionary keys is
# a policy nobody proofreads.

PRIVACY = {
    "en": """
<h2>What is uploaded</h2>
<p><b>The entire savegame</b>, zipped: the <code>game</code> file, the ships, the
sectors and the binaries the game writes alongside them. It is your whole run,
not a summary of it.</p>

<h2>Where to</h2>
<p>To this server, run by a private individual. There is no company behind it,
no third party receiving a copy, and nothing is forwarded to another service.</p>

<h2>Who can see it</h2>
<p>Whoever administers the server has technical access to the files. No
encryption prevents that, and saying otherwise would be a lie. Other players in
the same room see a <b>storefront</b>: a shop with the name you choose, holding
the goods you consign. Your actual hold stays out of that copy.</p>

<h2>For how long</h2>
<p>The last 20 versions of each save, per room. Older ones are deleted
automatically. If you leave, everything goes at once.</p>

<h2>What personal data</h2>
<p><b>Almost none, and not your address.</b> We do not ask for an email, a real
name, a password or a Steam login. Your identity here is a random code the
server generates and keeps only a cryptographic digest of. The consequence is
harsh and honest: <b>losing the code means losing the account</b>, and there is
no recovery.</p>
<p>One thing is kept beyond that, and it would be dishonest not to say so.
Because registration asks for a name and nothing else, a script could create
accounts without limit, so the server allows <b>one account per connection</b>.
To answer "has this address registered before" it stores an <b>HMAC</b> of the
address. Not the address itself, and not a plain hash of it either: a plain
SHA-256 of an IPv4 has four billion candidates and falls to brute force in
seconds. What is stored answers that one question and goes with the rest when
you delete your account. It cannot place you anywhere.</p>
<p>If you share a connection with somebody who already joined, say a house, a
hall of residence, or any mobile carrier, you will be turned away for a reason
that has nothing to do with you. Ask whoever runs the room. Lifting it takes one
line.</p>

<h2>What the client writes on your machine</h2>
<p>One file, and only one:</p>
<pre>~/.config/sgalaxy/credentials.json</pre>
<p>On Windows the equivalent path is
<code>%USERPROFILE%\\.config\\sgalaxy\\credentials.json</code>. It holds your
access code, created mode 600 so only your user can read it. The code is stored
in the clear because it <b>is</b> your account: anybody who reads that file signs
in as you. Deleting it disconnects this machine, and the account stays alive on
the server. Nothing else is installed, and no service keeps running.</p>

<h2>How to delete everything and leave</h2>
<p>There is a page for it, and there is no second-guessing step:</p>
<p><a class="cta" href="/account/delete">Delete your account and leave</a></p>
<p>It deletes your account and all your saves. Rooms you created that still have
other players stay up, because erasing them would destroy the saves of people
who asked for nothing. Those rooms leave the public listing, and your code stops
working.</p>

<h2>What cannot be promised</h2>
<p>The game runs on your machine, on files you can edit. There is no way to stop
anyone from altering their own save, and this project does not pretend
otherwise: the design is cooperative, and the server <b>checks</b> rather than
guesses. Anyone promising absolute security hasn't thought about it.</p>
""",
    "pt": """
<h2>O que sobe</h2>
<p><b>O savegame inteiro</b>, compactado: o arquivo <code>game</code>, as naves,
os setores e os binários que o jogo grava junto. É a sua partida completa, e
não um resumo dela.</p>

<h2>Para onde</h2>
<p>Para este servidor, mantido por um particular. Não há empresa por trás, não há
terceiro recebendo cópia, e nada é enviado para outro serviço.</p>

<h2>Quem enxerga</h2>
<p>Quem administra o servidor tem acesso técnico aos arquivos. Não há
criptografia que impeça isso, e dizer o contrário seria mentira. Outros jogadores
da mesma sala verão, quando a etapa seguinte existir, apenas um <b>retrato</b>:
uma loja com o nome que você escolher e só a mercadoria que você consignar. O seu
porão de verdade não entra nessa cópia.</p>

<h2>Por quanto tempo</h2>
<p>As últimas 20 versões de cada save, por sala. As mais antigas são apagadas
sozinhas. Se você sair, apaga tudo na hora.</p>

<h2>Que dado pessoal</h2>
<p>Uma coisa é guardada, e omitir seria desonesto. Como o cadastro pede um nome
e mais nada, um script criaria contas sem limite, então o servidor permite
<b>uma conta por conexão</b>. Para responder "este endereço já se cadastrou" ele
guarda um <b>HMAC</b> do endereço. Não o endereço em si, e nem um hash simples
dele: um SHA-256 puro de um IPv4 são quatro bilhões de candidatos e cai por
força bruta em segundos. O que fica responde só essa pergunta e vai junto com o
resto quando você apaga a conta. Localizar alguém, ele não localiza.</p>
<p>Se você divide a conexão com quem já entrou, seja uma casa, um alojamento ou
qualquer operadora de celular, vai ser barrado por um motivo que nada tem a ver
com você. Fale com quem administra a sala. Liberar é uma linha.</p>
<p><b>Fora isso, nenhum.</b> Não pedimos e-mail, nome real, senha ou login de
Steam. A sua
identidade aqui é um código aleatório que o servidor gera e do qual guarda só o
resumo criptográfico. A consequência é dura e é honesta: <b>quem perde o código
perde a conta</b>, e não há como recuperar.</p>

<h2>O que o cliente cria no seu computador</h2>
<p>Um arquivo, e só um:</p>
<pre>~/.config/sgalaxy/credentials.json</pre>
<p>No Windows o caminho equivalente é
<code>%USERPROFILE%\\.config\\sgalaxy\\credentials.json</code>. Ele guarda o seu
código de acesso, criado com permissão 600 para que só o seu usuário leia. O
código fica em claro porque ele <b>é</b> a sua conta: quem ler esse arquivo
entra como você. Apagá-lo desconecta este computador, e a conta segue viva no
servidor. Nada mais é instalado, e nenhum serviço fica rodando.</p>

<h2>Como apagar tudo e sair</h2>
<p>Existe uma página para isso, e não há etapa de arrependimento:</p>
<p><a class="cta" href="/account/delete?lang=pt">Apagar a conta e sair</a></p>
<p>Apaga a sua conta e todos os seus saves. Salas que você criou e que ainda têm
outras pessoas dentro continuam de pé, porque apagá-las destruiria o save de
quem não pediu nada. Essas salas saem da listagem pública, e o seu código deixa
de valer.</p>

<h2>O que não dá para prometer</h2>
<p>O jogo roda na sua máquina, em arquivos que você consegue editar. Não há como
impedir que alguém altere o próprio save, e o projeto não finge que há: o desenho
é cooperativo, e o servidor <b>confere</b> em vez de adivinhar. Quem promete
segurança absoluta é quem não pensou no assunto.</p>
""",
}


HOW = {"en": """
<h2>The idea</h2>
<p>Space Haven is a single-player game and this does not change that. Nobody
plays in your game, nothing is synchronised while you play, and there is no
server tick. What is shared is <b>the galaxy</b>: the same star map, the same
systems, and the trace everyone leaves in it.</p>
<p>The unit of exchange is the savegame itself. Yours is uploaded, kept, and
handed back with everyone else's marks written into it.</p>

<h2>Check out, play, check in</h2>
<p>A session is a loan, and the room hands the save to one person at a time.</p>
<ol>
<li><b>Check out.</b> The server builds your save: your run, plus the galaxy as
the room left it. It marks the loan as open and starts a clock.</li>
<li><b>Play.</b> Normally, offline, in your own copy of the game. While you
play, each autosave is sent up as a checkpoint, so the room's map can show where
you are without waiting for you to finish.</li>
<li><b>Check in.</b> When you close the game the save goes back, is checked, and
becomes what the others receive next.</li>
</ol>
<p>One session at a time is what keeps the galaxy from forking. Two people
playing the same room at once would produce two versions of the same universe,
and merging them is not a problem with an honest solution.</p>

<h2>What the server checks, and what it does not</h2>
<p>Every arriving save is fingerprinted by its stars. If the galaxy is not the
room's, the save is refused, because it belongs to another universe. Beyond
that the server leaves your run alone. It never audits your resources, your ship
or your crew. The game runs on your machine, on files you can edit, and
pretending otherwise would be theatre.</p>

<h2>What travels between players</h2>
<p>Three things, and no more:</p>
<ul>
<li><b>Where you are.</b> Your position feeds the room's map.</li>
<li><b>What you found.</b> Systems somebody explored become visible to
everyone, including people who join later. Visited stays yours; visible is
shared.</li>
<li><b>What you sell.</b> One storage on your ship can be marked as your shop.
Its contents, and only its contents, are copied into a storefront that
appears in your neighbours' sectors.</li>
</ul>
<p>Your hold, your blueprints and your colony stay out of that copy.</p>

<h2>The storefront, and how a sale reaches you</h2>
<p>A neighbour in your system shows up as a ship you can trade with. The server
assembles that ship inside your own save, from their ship as it stood when they
last returned it, carrying the goods they consigned. Their game never touches
yours.</p>
<p>When somebody buys from it, the game charges them and pays the ship, which
as far as the game knows belongs to a faction. So the server photographs the
shelf when it hands the save out, compares it when the save comes back, and
records what was sold. You collect at your next check out: credits into your
bank, goods out of your shop storage. The price is the one the game itself
charged.</p>
<p>The storefront is removed from the save when it comes back, so it stays out
of your own game for good.</p>

<h2>The mod</h2>
<p>The mod is optional. Everything above works without it; it removes the
fiddly parts.</p>
<ul>
<li><b>It opens the room's save for you</b>, instead of leaving you to find it
in the load menu and hope you picked the right one.</li>
<li><b>It writes the room, the version and your sales into the game's own log</b>,
so you can tell at a glance that you are in the shared galaxy and not a local
run.</li>
<li><b>It adds a SHOP toggle</b> to a storage's panel, so choosing what you sell
is done in the game rather than in a terminal.</li>
<li><b>It silences the automatic hails</b> from storefronts. Left alone, the
game's AI would have your neighbours' shops calling you to trade on their own
initiative, moving an economy that nobody decided to move.</li>
</ul>
<p>Technically it is a Java agent woven into the running game with AspectJ. The
game jar stays as it was, and uninstalling means undoing three lines in a config
file.</p>

<h2>What is stored, and for how long</h2>
<p>The last three versions of each save, per room. Older ones are deleted
automatically, and everything goes at once if you leave.</p>
<p><b>There is no rollback.</b> Nothing restores an old version, for you, for
the room owner, or for anybody. A session that went badly went badly, and a
mistake that costs a crew costs it. The short history is there to protect you
from <i>this server</i>: a bad graft or a storefront removed wrongly is our
fault, and the previous version is what makes it recoverable.</p>
""", "pt": """
<h2>A ideia</h2>
<p>Space Haven é um jogo de um jogador só, e isto não muda isso. Ninguém joga
dentro do seu jogo, nada é sincronizado enquanto você joga, e não existe um
servidor de partida. O que é compartilhado é <b>a galáxia</b>: o mesmo mapa
estelar, os mesmos sistemas, e o rastro que cada um deixa nele.</p>
<p>A unidade de troca é o próprio savegame. O seu sobe, fica guardado, e volta
com as marcas de todo mundo escritas dentro dele.</p>

<h2>Retirar, jogar, devolver</h2>
<p>Uma sessão é um empréstimo, e a sala entrega o save a uma pessoa por vez.</p>
<ol>
<li><b>Retirar.</b> O servidor monta o seu save: a sua partida, mais a galáxia
como a sala a deixou. Marca o empréstimo como aberto e começa a contar o
tempo.</li>
<li><b>Jogar.</b> Normalmente, offline, na sua própria cópia do jogo. Enquanto
você joga, cada autosave sobe como checkpoint, para o mapa da sala mostrar onde
você está sem esperar você terminar.</li>
<li><b>Devolver.</b> Quando você fecha o jogo, o save volta, é conferido, e vira
o que as outras pessoas recebem em seguida.</li>
</ol>
<p>Uma sessão por vez é o que impede a galáxia de se dividir. Duas pessoas
jogando a mesma sala ao mesmo tempo produziriam duas versões do mesmo universo,
e juntá-las não é um problema com solução honesta.</p>

<h2>O que o servidor confere, e o que não confere</h2>
<p>Todo save que chega é identificado pelas suas estrelas. Se a galáxia não for
a da sala, o save é recusado, porque pertence a outro universo. Fora isso o
servidor deixa a sua partida em paz: recursos, nave e tripulação ficam por sua
conta. O jogo roda na sua máquina, sobre arquivos que você pode editar, e fingir
o contrário seria teatro.</p>

<h2>O que viaja entre jogadores</h2>
<p>Três coisas, e nada além:</p>
<ul>
<li><b>Onde você está.</b> A sua posição alimenta o mapa da sala.</li>
<li><b>O que você descobriu.</b> Sistemas que alguém explorou ficam visíveis
para todos, inclusive para quem entrar depois. Visitado continua seu; visível é
compartilhado.</li>
<li><b>O que você vende.</b> Um depósito da sua nave pode ser marcado como a sua
loja. O conteúdo dele, e só ele, é copiado para uma vitrine que aparece nos
setores dos seus vizinhos.</li>
</ul>
<p>O seu porão, os seus projetos e a sua colônia ficam de fora dessa cópia.</p>

<h2>A vitrine, e como uma venda chega até você</h2>
<p>Um vizinho no seu sistema aparece como uma nave com quem dá para comerciar.
O servidor monta essa nave dentro do seu próprio save, a partir da nave dele
como estava na última devolução, carregando o que ele consignou. O jogo dele
nunca encosta no seu.</p>
<p>Quando alguém compra dela, o jogo cobra e paga a nave, que para ele pertence
a uma facção. Então o servidor fotografa a prateleira quando entrega o save,
compara quando ele volta, e registra o que foi vendido. Você recebe na sua
próxima retirada: créditos no banco, mercadoria fora do depósito. O preço é o
que o próprio jogo cobrou.</p>
<p>A vitrine é removida do save quando ele volta, então fica de fora da sua
partida para sempre.</p>

<h2>O mod</h2>
<p>O mod é opcional. Tudo acima funciona sem ele; o que ele tira são as partes
chatas.</p>
<ul>
<li><b>Abre o save da sala para você</b>, em vez de deixar você procurar no menu
de load e torcer para ter escolhido o certo.</li>
<li><b>Escreve a sala, a versão e as suas vendas no log do próprio jogo</b>, para
você saber de relance que está na galáxia compartilhada e não numa partida
local.</li>
<li><b>Acrescenta um botão SHOP</b> ao painel de um depósito, para escolher o
que você vende ser coisa de dentro do jogo, e não de terminal.</li>
<li><b>Cala os chamados automáticos</b> das vitrines. Sem isso, a IA do jogo põe
as lojas dos seus vizinhos ligando para negociar por conta própria, movendo
uma economia que ninguém decidiu mover.</li>
</ul>
<p>Tecnicamente é um agente Java tecido no jogo em execução com AspectJ. O jar
do jogo continua como estava, e desinstalar é desfazer três linhas num arquivo
de configuração.</p>

<h2>O que fica guardado, e por quanto tempo</h2>
<p>As últimas três versões de cada save, por sala. As mais antigas são apagadas
sozinhas, e tudo vai junto se você sair.</p>
<p><b>Não existe rollback.</b> Nada restaura uma versão antiga, para você, para
quem administra a sala, ou para quem quer que seja. Uma sessão que deu errado
deu errado, e um engano que custa uma tripulação custa. O histórico curto está
lá para te proteger <i>deste servidor</i>: um enxerto malfeito ou uma vitrine
removida errado é culpa nossa, e a versão anterior é o que torna isso
recuperável.</p>
"""}


def how_page(lang: str) -> str:
    """O conceito inteiro numa pagina: save como unidade de troca, o
    emprestimo, o que viaja entre jogadores, a vitrine e o mod.

    Sem isto o site mostra salas vivas e nunca explica o que esta acontecendo,
    e a pergunta que todo mundo faz primeiro — "entao voces jogam juntos?" —
    fica sem resposta escrita.
    """
    return layout(t("how_title", lang), HOW[lang], lang, "", "/how-it-works")


def privacy_page(lang: str) -> str:
    return layout(t("privacy_title", lang), PRIVACY[lang], lang, "", "/privacy")


# ---------------------------------------------------------------------------
# Onboarding pela web
# ---------------------------------------------------------------------------
#
# O degrau 2 da secao 2.11 diz que a pessoa deve poder ver a sala e decidir sem
# instalar nada. Registrar e criar sala pelo navegador estende isso: o cliente
# de linha de comando deixa de ser a porta de entrada e vira a ferramenta de
# quem ja decidiu.
#
# Formularios HTML puros, sem JavaScript. O token entra num cookie
# `SameSite=Strict` e `HttpOnly` — o primeiro barra POST vindo de outro site, o
# segundo tira o token do alcance de script. E o suficiente para paginas que nao
# executam nada de terceiro.

FORM_CSS = """
  form {{ max-width:26rem; }}
  label {{ display:block; margin:1rem 0 .3rem; color:var(--dim);
          font-size:.9rem; }}
  input[type=text] {{ width:100%; padding:.55rem .7rem; border-radius:.35rem;
    border:1px solid var(--line); background:#0f1730; color:var(--fg);
    font:inherit; }}
  button {{ margin-top:1.4rem; padding:.6rem 1.2rem; border-radius:.35rem;
    border:0; background:#3b6fd4; color:#fff; font:inherit; font-weight:600;
    cursor:pointer; }}
  .code {{ font-size:1.05rem; letter-spacing:.06em; word-break:break-all;
    background:#161d38; padding:.9rem; border-radius:.4rem;
    border:1px solid #3d4a72; }}
"""


# Onde o binario mora. `releases/latest/download/<nome>` sempre aponta para a
# publicacao mais recente, entao a pagina nao envelhece a cada versao.
RELEASES = "https://github.com/Gianotto/shared-galaxy/releases"
LOADER = ("https://steamcommunity.com/sharedfiles/filedetails/"
          "?id=3703674043")
BINARIES = (
    ("download_linux", "sgalaxy-linux-x86_64", "./sgalaxy"),
    ("download_windows", "sgalaxy-windows-x86_64.exe", "sgalaxy.exe"),
    ("download_macos", "sgalaxy-macos-arm64", "./sgalaxy"),
)

JOIN_CSS = """
  ol.steps {{ list-style:none; padding:0; counter-reset:none; }}
  ol.steps > li {{ margin:2rem 0; }}
  ol.steps h3 {{ margin:0 0 .3rem; }}
  .dl {{ display:flex; flex-wrap:wrap; gap:.6rem; margin:.8rem 0; }}
  .dl a {{ padding:.5rem .9rem; border-radius:.35rem; border:1px solid var(--line);
    background:#161d38; text-decoration:none; }}
  pre {{ background:#0f1730; border:1px solid var(--line); border-radius:.4rem;
    padding:.8rem; overflow-x:auto; }}
  .note {{ color:var(--dim); font-size:.92rem; }}
  .warn {{ border-left:3px solid #c9a227; padding-left:.9rem; }}
"""


def join_page(room: dict, lang: str, players: int, full: bool) -> str:
    """Como sair de \"vi a sala\" para \"estou jogando\".

    Existe porque o resto do site mostra a sala viva e depois deixa a pessoa
    sozinha. Quem chega por um convite no Discord nao tem como adivinhar que ha
    um cliente, onde ele esta, nem que entrar e uma coisa que se faz uma vez.

    Os comandos saem por sistema operacional em vez de um exemplo generico: o
    nome do arquivo muda, e um comando que nao cola e o mesmo que nao existir.
    """
    nome = _esc(room["name"])
    rid = _esc(room["id"])

    baixar = "".join(
        f'<a href="{RELEASES}/latest/download/{arquivo}">{t(chave, lang)}</a>'
        for chave, arquivo, _cmd in BINARIES)

    avisos = ""
    if full:
        avisos += f'<p class="warn">{t("room_full", lang)}</p>'
    if room.get("has_password") or room.get("password_hash"):
        avisos += f'<p class="warn">{t("room_locked", lang)}</p>'
    idade = room.get("max_join_age_days")
    if idade:
        # O banco devolve `numeric`, e "5.00 dias" e vocabulario de planilha,
        # nao de quem esta lendo quantos dias de jogo pode ter.
        legivel = f"{float(idade):g}"
        avisos += (f'<p class="warn">'
                   f'{t("join_age_rule", lang) % _esc(legivel)}</p>')

    body = f"""
<p>{t("join_intro", lang)}</p>
{avisos}
<ol class="steps">
  <li>
    <h3>{t("step_download", lang)}</h3>
    <p class="note">{t("step_download_help", lang)}</p>
    <div class="dl">{baixar}</div>
    <p class="note">{t("rename_it", lang)}</p>
    <p class="note">{t("on_windows", lang)}</p>
    <pre>ren sgalaxy-windows-x86_64.exe sgalaxy.exe</pre>
    <p class="note">{t("on_unix", lang)}</p>
    <pre>mv sgalaxy-* sgalaxy
chmod +x sgalaxy</pre>
  </li>
  <li>
    <h3>{t("step_account", lang)}</h3>
    <p class="note">{t("step_account_help", lang)}</p>
    <p><a href="/register?lang={lang}">{t("no_account_yet", lang)}</a> ·
       <a href="/recovery?lang={lang}">{t("recovery_title", lang)}</a></p>
    {commands('register --recover "YOUR-RECOVERY-CODE"', lang)}
  </li>
  <li>
    <h3>{t("step_mod", lang)}</h3>
    <p class="note">{t("mod_optional_here", lang)}
       <a href="/client?lang={lang}">{t("client_title", lang)}</a></p>
    {commands("install-mod", lang)}
  </li>
  <li>
    <h3>{t("step_join", lang)}</h3>
    <p class="note">{t("step_join_help", lang)}</p>
    {commands(f"join {rid}", lang)}
  </li>
  <li>
    <h3>{t("step_play", lang)}</h3>
    <p class="note">{t("step_play_help", lang)}</p>
    {commands(f"play {rid}", lang)}
  </li>
</ol>
<p><a href="/room/{rid}?lang={lang}">&larr; {nome}</a></p>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("join_title", lang) % nome, body, lang,
                  f"{players}/{room['max_players']} {t('players', lang)}",
                  f"/room/{rid}/join")


# Os dois jeitos de chamar o programa. Nao ha um terceiro: no macOS e no Linux
# e o mesmo comando, e escrever `./sgalaxy` sozinho numa pagina que atende tres
# sistemas manda metade das pessoas colarem algo que nao funciona.
INVOKE = (("on_windows", "sgalaxy.exe"), ("on_unix", "./sgalaxy"))


def commands(sufixo: str, lang: str) -> str:
    """O mesmo comando nos dois sistemas, lado a lado."""
    return "".join(
        f'<p class="note">{t(chave, lang)}</p><pre>{_esc(prog)} {_esc(sufixo)}</pre>'
        for chave, prog in INVOKE)


def client_page(lang: str) -> str:
    """Como instalar e chamar o cliente, em cada sistema.

    Existe porque as instrucoes estavam espalhadas e todas escritas em
    `./sgalaxy`, que e o comando de dois dos tres sistemas suportados.
    """
    baixar = "".join(
        f'<a href="{RELEASES}/latest/download/{arquivo}">{t(chave, lang)}</a>'
        for chave, arquivo, _cmd in BINARIES)
    body = f"""
<p>{t("client_intro", lang)}</p>
<div class="dl">{baixar}</div>

<h2>{t("on_windows", lang)}</h2>
<p class="note">{t("windows_note", lang)}</p>
<pre>.\\sgalaxy.exe --help</pre>

<h2>{t("on_unix", lang)}</h2>
<p class="note">{t("unix_chmod", lang)}</p>
<pre>chmod +x sgalaxy-*
mv sgalaxy-* sgalaxy
./sgalaxy --help</pre>

<h2>{t("what_it_writes", lang)}</h2>
<p>{t("writes_intro", lang)}</p>
<pre>~/.config/sgalaxy/credentials.json</pre>
<p class="note">{t("writes_detail", lang)}</p>

<h2>{t("mod_h", lang)}</h2>
<p>{t("mod_why", lang)}</p>
<p>{t("mod_needs_loader", lang)}</p>
<p><a href="{LOADER}">SpaceHaven Mod Loader</a></p>

<h3>{t("mod_install_h", lang)}</h3>
<p class="note">{t("mod_install_help", lang)}</p>
{commands("install-mod", lang)}
<p class="note">{t("mod_closed_why", lang)}</p>
<p class="note">{t("mod_uninstall", lang)}</p>
{commands("install-mod --uninstall", lang)}
<p class="note">{t("mod_touches", lang)}</p>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("client_title", lang), body, lang, "", "/client")


def recovery_page(lang: str) -> str:
    """O que e o codigo de recuperacao e como usa-lo.

    Ele aparece uma vez, no cadastro, e depois disso e a unica credencial que
    existe. Quem chega na mensagem "ja existe uma conta desta conexao" precisa
    saber o que fazer, e ate agora nao havia onde ler isso.
    """
    body = f"""
<p>{t("recovery_what", lang)}</p>
<p>{t("recovery_when", lang)}</p>

<h2>{t("recovery_how", lang)}</h2>
{commands('register --recover "YOUR-RECOVERY-CODE"', lang)}
<p class="note">{t("recovery_dashes", lang)}</p>
<p class="note">{t("recovery_check", lang)}</p>

<h2>{t("what_it_writes", lang)}</h2>
<p>{t("writes_intro", lang)}</p>
<pre>~/.config/sgalaxy/credentials.json</pre>
<p class="note">{t("writes_detail", lang)}</p>

<p><a href="/client?lang={lang}">{t("client_title", lang)}</a> ·
   <a href="/account/delete?lang={lang}">{t("delete_title", lang)}</a></p>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("recovery_title", lang), body, lang, "", "/recovery")


def delete_form(lang: str, error: str = "") -> str:
    """Apagar a conta sem precisar de um terminal.

    A politica prometia isto e entregava uma linha de `curl` com um cabecalho
    de autorizacao — o que so serve para quem ja sabe o que e um cabecalho de
    autorizacao. Uma promessa de apagar dados que exige competencia tecnica
    para ser exercida nao e bem uma promessa.
    """
    aviso = f'<p style="color:#f6a5a5">{_esc(error)}</p>' if error else ""
    body = f"""{aviso}
<p>{t("delete_intro", lang)}</p>
<p class="note">{t("delete_rooms_note", lang)}</p>
<form method="post" action="/account/delete?lang={lang}">
  <label for="code">{t("your_code_label", lang)}</label>
  <input type="text" id="code" name="code" required autocomplete="off">
  <label for="confirm">{t("delete_confirm_label", lang)}</label>
  <input type="text" id="confirm" name="confirm" required autocomplete="off">
  <button type="submit">{t("delete_button", lang)}</button>
</form>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("delete_title", lang), body, lang, "", "/account/delete")


def deleted_page(resultado: dict, lang: str) -> str:
    detalhe = (f'<p class="note">{_esc(resultado.get("message", ""))}</p>'
               if resultado.get("message") else "")
    body = f"""
<p>{t("delete_done", lang)}</p>{detalhe}
<p><a href="/?lang={lang}">{t("nav_rooms", lang)}</a></p>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("delete_title", lang), body, lang, "", "/account/delete")


def register_form(lang: str, error: str = "", needs_invite: bool = False) -> str:
    """O formulario de conta, com o campo de convite quando o servidor pede um.

    O campo SO aparece quando ha convite exigido. Antes disto o modo convite
    recusava aqui sem oferecer onde digitar, e a pagina virava um beco sem
    saida: a API e o cliente aceitavam `invite`, o site nao.
    """
    aviso = f'<p style="color:#f6a5a5">{_esc(error)}</p>' if error else ""
    convite = f"""
  <label for="invite">{t("invite_code", lang)}</label>
  <input type="text" id="invite" name="invite" maxlength="80" required
         autocomplete="off">""" if needs_invite else ""
    ajuda = f'<p>{t("invite_help", lang)}</p>' if needs_invite else ""
    body = f"""{aviso}{ajuda}
<p>{t("no_email", lang)}</p>
<form method="post" action="/register?lang={lang}">
  <label for="name">{t("your_name", lang)}</label>
  <input type="text" id="name" name="name" maxlength="40" required
         autocomplete="off">{convite}
  <button type="submit">{t("create_account", lang)}</button>
</form>
<p class="note" style="margin-top:1.4rem">
  <a href="/recovery?lang={lang}">{t("have_account", lang)}</a></p>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("create_account", lang), body, lang, "", "/register")


def registered_page(name: str, code: str, lang: str) -> str:
    body = f"""
<p>{t("signed_as", lang)} <b>{_esc(name)}</b>.</p>
<h2>{t("your_code", lang)}</h2>
<p class="code">{_esc(code)}</p>
<p><b>{t("code_warning", lang)}</b></p>
<h2>{t("use_in_client", lang)}</h2>
<p class="note">{t("step_download_help", lang)}</p>
<div class="dl">{"".join(
    f'<a href="{RELEASES}/latest/download/{arq}">{t(k, lang)}</a>'
    for k, arq, _c in BINARIES)}</div>
{commands(f'register --recover "{_esc(code)}"', lang)}
<p><a href="/?lang={lang}">{t("rooms", lang)}</a> ·
   <a href="/new-room?lang={lang}">{t("new_room", lang)}</a></p>
<style>{JOIN_CSS.format()}{FORM_CSS.format()}</style>"""
    return layout(t("account_made", lang), body, lang, "", "/register")


def new_room_form(lang: str, name: str | None, error: str = "") -> str:
    if not name:
        body = (f'<p>{t("need_account", lang)}</p>'
                f'<p><a href="/register?lang={lang}">'
                f'{t("create_account", lang)}</a></p>')
        return layout(t("new_room", lang), body, lang, "", "/new-room")

    aviso = f'<p style="color:#f6a5a5">{_esc(error)}</p>' if error else ""
    body = f"""{aviso}
<p>{t("signed_as", lang)} <b>{_esc(name)}</b>.</p>
<p>{t("room_seed_help", lang)}</p>
<form method="post" action="/new-room?lang={lang}">
  <label for="name">{t("room_name", lang)}</label>
  <input type="text" id="name" name="name" maxlength="80" required>
  <label for="seed">{t("seed", lang)}</label>
  <input type="text" id="seed" name="seed" maxlength="40" required
         inputmode="numeric">
  <button type="submit">{t("create", lang)}</button>
</form>
<style>{FORM_CSS.format()}</style>"""
    return layout(t("new_room", lang), body, lang, "", "/new-room")
