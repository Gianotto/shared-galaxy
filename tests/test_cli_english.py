"""A linha de comando fala inglês, porque é ela que atende a comunidade.

O projeto é brasileiro e os comentários do código são em português de
propósito. O que a pessoa lê na tela é outra coisa: quem chega por um convite
no Discord não tem por que topar com `subindo …` no meio de uma sessão.

O teste lê a árvore sintática em vez do texto do arquivo, para separar o que
sai para a tela do que é comentário e docstring. Um `grep` reprovaria o
projeto inteiro por causa dos comentários, e por isso ninguém o rodaria.
"""

import ast
import os
import re
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "tools"))

# Diacríticos, mais as palavras que só existem em português e aparecem em
# texto de interface. Palavras iguais nas duas línguas ficam de fora: `save`
# e `mod` são inglês aqui.
PORTUGUES = re.compile(
    r"[áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ]"
    # Substantivos e verbos que só existem em português. A lista cresceu
    # depois de `room X criada` passar batido: sem acento e com o resto da
    # frase em inglês, só a palavra denuncia.
    r"|\b(nao|sala|salas|nave|naves|jogo|jogos|pasta|senha|voce|"
    r"subindo|devolvendo|criada|criado|apagada|apagado|enviada|enviado|"
    r"achei|instalado|desinstalado|chave|valor|erro|aberto|fechado|"
    r"galaxia|partida|arquivo|prazo|conta|entrada|saida)\b",
    re.IGNORECASE)

ARQUIVOS = ("tools/sgalaxy.py", "tools/install_mod.py", "tools/steamfind.py")


def _saidas(caminho: str):
    """Toda string que chega à tela: `print(...)`, exceções, e a ajuda."""
    with open(caminho, encoding="utf-8") as fh:
        arvore = ast.parse(fh.read())
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        nome = getattr(no.func, "id", getattr(no.func, "attr", ""))
        if nome == "print" or nome.endswith("Error"):
            for pedaco in ast.walk(no):
                if (isinstance(pedaco, ast.Constant)
                        and isinstance(pedaco.value, str)):
                    yield no.lineno, pedaco.value
        for kw in no.keywords:
            if kw.arg in ("help", "description", "epilog", "metavar", "prog"):
                for pedaco in ast.walk(kw.value):
                    if (isinstance(pedaco, ast.Constant)
                            and isinstance(pedaco.value, str)):
                        yield no.lineno, pedaco.value


class CommandLineIsEnglishTestCase(unittest.TestCase):

    def test_nothing_on_screen_is_in_portuguese(self):
        for arquivo in ARQUIVOS:
            caminho = os.path.join(RAIZ, arquivo)
            for linha, texto in _saidas(caminho):
                with self.subTest(file=arquivo, line=linha):
                    self.assertIsNone(
                        PORTUGUES.search(texto),
                        f"{arquivo}:{linha} shows Portuguese: {texto[:70]!r}")

    def test_the_detector_would_actually_catch_something(self):
        """Um teste que não reprova nada não protege nada."""
        self.assertTrue(PORTUGUES.search("subindo a pasta"))
        self.assertTrue(PORTUGUES.search("galáxia"))
        self.assertIsNone(PORTUGUES.search("uploading the save folder"))

    def test_every_subcommand_has_help(self):
        """Um subcomando sem ajuda não aparece direito na lista."""
        # Por caminho, e não por `import sgalaxy`: existe um pacote `sgalaxy/`
        # na raiz, e numa varredura da suíte inteira é ele que o nome resolve.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sgalaxy_cli", os.path.join(RAIZ, "tools", "sgalaxy.py"))
        cliente = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cliente)
        parser = cliente.build_parser()
        sub = next(a for a in parser._actions
                   if isinstance(a, argparse_subparsers()))
        # Um apelido não tem entrada própria: o argparse lista os dois sob o
        # nome principal, e a ajuda é a mesma. Conferir os apelidos aqui
        # reprovaria um comando que está descrito.
        principais = {c.dest for c in sub._choices_actions}
        for nome in principais:
            with self.subTest(cmd=nome):
                ajuda = next((c.help for c in sub._choices_actions
                              if c.dest == nome), None)
                self.assertTrue(ajuda, f"{nome} has no help text")
        self.assertTrue(principais <= set(sub.choices))


def argparse_subparsers():
    import argparse
    return argparse._SubParsersAction


if __name__ == "__main__":
    unittest.main()


class CommandsNamedInMessagesTestCase(unittest.TestCase):
    """Uma mensagem que sugere um comando inexistente é pior que nenhuma: a
    pessoa digita o que leu e recebe outro erro. `configurar-room` chegou a ser
    sugerido depois de criar uma galáxia, e nunca existiu."""

    def _cli(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sgalaxy_cli", os.path.join(RAIZ, "tools", "sgalaxy.py"))
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_every_command_a_message_suggests_exists(self):
        cli = self._cli()
        validos = set(cli.build_parser()._subparsers._group_actions[0].choices)
        with open(os.path.join(RAIZ, "tools", "sgalaxy.py"),
                  encoding="utf-8") as fh:
            arvore = ast.parse(fh.read())
        citados = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Constant) and isinstance(no.value, str):
                for padrao in (r"\{prog\(\)\}\s+([a-z][a-z-]+)",
                               r"sgalaxy(?:\.py)?\s+([a-z][a-z-]+)"):
                    citados.update(re.findall(padrao, no.value))
        self.assertTrue(citados, "nenhum comando citado: o teste não mede nada")
        self.assertEqual(citados - validos, set())
