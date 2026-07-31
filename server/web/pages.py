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


def layout(title: str, body: str, lang: str, subtitle: str = "",
           path: str = "/") -> str:
    """The shared shell.

    ESCAPES the title. Callers pass raw text — escaping on both sides produced
    `&amp;lt;script&amp;gt;` on screen, which is safe and unreadable. `body` and
    `subtitle` arrive as finished HTML.
    """
    other = "pt" if lang == "en" else "en"
    sep = "&" if "?" in path else "?"
    switch = (f'<a href="{_esc(path)}{sep}lang={other}">'
              f'{"Português" if other == "pt" else "English"}</a>')
    return f"""<!doctype html><html lang="{lang}"><meta charset="utf-8">
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
<p class="lang">{switch}</p>
<h1>{_esc(title)}</h1>
<p class="sub">{subtitle}</p>
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
  </div>""" for r in rooms)
        body = f'<div class="cards">{cards}</div>'
    return layout(t("site", lang), body, lang, t("tagline", lang), "/")


# Tooltip geometry. Everything is drawn, not styled by a layout engine, so the
# numbers live here instead of being scattered through the f-strings.
TIP_LINE = 13
TIP_PAD = 7
TIP_CHAR = 5.6          # average glyph width at 10px in the UI font
TIP_MAX_SHIPS = 8       # beyond this the box stops being readable


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
    for p in people[:TIP_MAX_SHIPS]:
        ship = p["ship_name"] or p["display_name"]
        mark = " ●" if p["playing"] else ""
        lines.append(f"{ship}{mark}")
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
        return MAP_PAD + s["x"] * scale, MAP_PAD + s["y"] * scale

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
                label = _esc(people[0]["ship_name"]
                             or people[0]["display_name"])
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
              visits: dict | None = None) -> str:
    map_svg = starmap_svg(galaxy, roster, lang, visits)

    if roster:
        rows = "".join(f"""
    <tr>
      <td>{_esc(p['display_name'])}</td>
      <td>{_esc(p['ship_name'] or '—')}</td>
      <td>{_esc(p['at_system'] or '—')}</td>
      <td>{_esc(p['at_celeid'] or '—')}</td>
      <td>{_esc(f"{float(p['age_days']):.1f} {t('days', lang)}") if p['age_days'] else '—'}</td>
      <td>{f'<span class="tag on">{t("playing", lang)}</span>' if p['playing'] else ''}</td>
    </tr>""" for p in roster)
        table = f"""<table>
  <tr><th>{t("th_player", lang)}</th><th>{t("th_ship", lang)}</th>
      <th>{t("th_system", lang)}</th><th>{t("th_body", lang)}</th>
      <th>{t("th_age", lang)}</th><th></th></tr>{rows}</table>"""
    else:
        table = f'<p class="sub">{t("nobody_yet", lang)}</p>'

    if room["password_hash"]:
        how = (f'<h2>{t("how_to_join", lang)}</h2>'
               f'<p class="sub">{t("locked_room", lang)}</p>')
    else:
        recipe = room.get("options") or {}
        items = "".join(f"<li>{_esc(k)}: <b>{_esc(v)}</b></li>"
                        for k, v in sorted(recipe.items()))
        how = f"""
<h2>{t("how_to_join", lang)}</h2>
<p>{t("how_intro", lang)}</p>
<ul>
  <li>{t("seed", lang)}: <code>{_esc(room['seed'])}</code></li>
  {items or f'<li class="sub">{t("no_options_yet", lang)}</li>'}
</ul>
<p>{t("then_upload", lang)}</p>
<pre>python3 tools/sgalaxy.py join {_esc(room['id'])} --save PATH/TO/GAME</pre>
<p class="sub">{t("wrong_options", lang)}</p>"""

    body = f"""{map_svg}
<h2>{t("who_is_where", lang)}</h2>
{table}
{how}"""
    return layout(
        room["name"], body, lang,
        f'{t("room", lang)} <code>{_esc(room["id"])}</code> · '
        f'{len(roster)}/{room["max_players"]} {t("players", lang)} · '
        f'{t("lease_of", lang)} {room["lease_hours"]}h',
        f'/room/{room["id"]}')


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
sectors and the binaries the game writes alongside them. Not a summary — your
whole run.</p>

<h2>Where to</h2>
<p>To this server, run by a private individual. There is no company behind it,
no third party receiving a copy, and nothing is forwarded to another service.</p>

<h2>Who can see it</h2>
<p>Whoever administers the server has technical access to the files — no
encryption prevents that, and saying otherwise would be a lie. Other players in
the same room will see, once the next stage exists, only a <b>storefront</b>: a
shop with the name you choose and only the goods you consign. Your actual hold
is not in that copy.</p>

<h2>For how long</h2>
<p>The last 20 versions of each save, per room. Older ones are deleted
automatically. If you leave, everything goes at once.</p>

<h2>What personal data</h2>
<p><b>None.</b> We do not ask for an email, a real name, a password or a Steam
login. Your identity here is a random code the server generates and keeps only a
cryptographic digest of. The consequence is harsh and honest: <b>losing the code
means losing the account</b>, and there is no recovery.</p>

<h2>How to delete everything and leave</h2>
<p>One call, and there is no second-guessing step:</p>
<pre>curl -X DELETE "https://galaxy.bygianotto.com.br/api/v1/me?confirm=delete%20everything" \\
     -H "Authorization: Bearer YOUR-TOKEN"</pre>
<p>It deletes your account and all your saves. Rooms you created that still have
other players stay up — erasing them would destroy the saves of people who asked
for nothing — but they leave the public listing and your token is invalidated.</p>

<h2>What cannot be promised</h2>
<p>The game runs on your machine, on files you can edit. There is no way to stop
anyone from altering their own save, and this project does not pretend
otherwise: the design is cooperative, and the server <b>checks</b> rather than
guesses. Anyone promising absolute security hasn't thought about it.</p>
""",
    "pt": """
<h2>O que sobe</h2>
<p><b>O savegame inteiro</b>, compactado: o arquivo <code>game</code>, as naves,
os setores e os binários que o jogo grava junto. Não é um resumo — é a sua
partida completa.</p>

<h2>Para onde</h2>
<p>Para este servidor, mantido por um particular. Não há empresa por trás, não há
terceiro recebendo cópia, e nada é enviado para outro serviço.</p>

<h2>Quem enxerga</h2>
<p>Quem administra o servidor tem acesso técnico aos arquivos — não há
criptografia que impeça isso, e dizer o contrário seria mentira. Outros jogadores
da mesma sala verão, quando a etapa seguinte existir, apenas um <b>retrato</b>:
uma loja com o nome que você escolher e só a mercadoria que você consignar. O seu
porão de verdade não entra nessa cópia.</p>

<h2>Por quanto tempo</h2>
<p>As últimas 20 versões de cada save, por sala. As mais antigas são apagadas
sozinhas. Se você sair, apaga tudo na hora.</p>

<h2>Que dado pessoal</h2>
<p><b>Nenhum.</b> Não pedimos e-mail, nome real, senha ou login de Steam. A sua
identidade aqui é um código aleatório que o servidor gera e do qual guarda só o
resumo criptográfico. A consequência é dura e é honesta: <b>quem perde o código
perde a conta</b>, e não há como recuperar.</p>

<h2>Como apagar tudo e sair</h2>
<p>Uma chamada, e não há etapa de arrependimento:</p>
<pre>curl -X DELETE "https://galaxy.bygianotto.com.br/api/v1/me?confirm=delete%20everything" \\
     -H "Authorization: Bearer SEU-TOKEN"</pre>
<p>Apaga a sua conta e todos os seus saves. Salas que você criou e onde há outros
jogadores continuam de pé — sumir com elas destruiria o save de quem não pediu
nada —, mas saem da listagem e o seu token é invalidado.</p>

<h2>O que não dá para prometer</h2>
<p>O jogo roda na sua máquina, em arquivos que você consegue editar. Não há como
impedir que alguém altere o próprio save, e o projeto não finge que há: o desenho
é cooperativo, e o servidor <b>confere</b> em vez de adivinhar. Quem promete
segurança absoluta é quem não pensou no assunto.</p>
""",
}


def privacy_page(lang: str) -> str:
    return layout(t("privacy_title", lang), PRIVACY[lang], lang, "", "/privacy")
