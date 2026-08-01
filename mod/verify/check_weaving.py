#!/usr/bin/env python3
"""
Todo alvo dos aspectos está na lista de classes tecidas?

Um `execution(...)` apontando para uma classe que o `aop.xml` não inclui
compila, instala e nunca dispara. Não há erro, não há aviso: o conselho
simplesmente não existe em execução.

Foi assim que o botão da loja ficou "intermitente" por três rodadas de teste
com um jogador — os ganchos novos estavam certos e nunca eram tecidos, e cada
diagnóstico media o comportamento do gancho ANTIGO.
"""
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent

incluidos = set(re.findall(r'include within="([^"]+)"',
                           (RAIZ / "META-INF" / "aop.xml").read_text()))
declarados = set(re.findall(r'aspect name="([^"]+)"',
                            (RAIZ / "META-INF" / "aop.xml").read_text()))

alvos, aspectos = set(), set()
for fonte in sorted((RAIZ / "src").rglob("*.java")):
    texto = fonte.read_text()
    aspectos.update(f"com.sharedgalaxy.{fonte.stem}"
                    for _ in re.findall(r"@Aspect", texto))
    for alvo in re.findall(r"execution\(\*\s+([\w.$]+)\.\w+\(", texto):
        alvos.add(alvo)

faltando = {a for a in alvos
            if not any(a == i or i.endswith("*") and a.startswith(i[:-1])
                       for i in incluidos)}
sem_registro = aspectos - declarados

for a in sorted(faltando):
    print(f"NAO TECIDO  {a}  — os conselhos que o citam nunca vao disparar")
for a in sorted(sem_registro):
    print(f"NAO DECLARADO  {a}  — falta <aspect name> no aop.xml")

if faltando or sem_registro:
    sys.exit(1)
print(f"tecelagem ok: {len(alvos)} alvos, {len(aspectos)} aspectos")
