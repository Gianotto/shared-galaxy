"""A versão deste build.

`dev` quando o programa roda a partir do repositório, que é o certo: não há
build, então não há versão publicada. O CI reescreve este arquivo com a tag
antes de empacotar.

Existe porque a primeira pergunta diante de qualquer defeito é "qual versão",
e a resposta era um encolher de ombros. Duas sessões se perderam com binário
velho: uma no `error code 1010`, outra num `join` que pedia um save que a
pessoa não tinha.
"""

VERSION = "dev"
