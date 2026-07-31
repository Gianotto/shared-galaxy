# Código vendorado

Arquivos copiados de outro repositório em vez de importados. A cópia é
deliberada: os dois projetos têm ciclos de vida diferentes e não quero criar
dependência de pacote entre eles enquanto nenhum dos dois está publicado.

O preço é deriva silenciosa, e a defesa contra ela é o teste cruzado descrito
abaixo — não a disciplina de quem lembrar de sincronizar.

## `savefile.py`

| | |
|---|---|
| Origem | <https://github.com/Gianotto/Space-Haven-SaveGameEditor> |
| Caminho | `shedit/savefile.py` |
| Commit | `1dc0eebcc25de41f51b72febfe271eaff319acdb` (2026-07-30) |
| Licença | MIT, mesmo autor, mesma licença deste repositório |
| Alterações locais | nenhuma |

Leitura e escrita byte-idêntica de savegame. A escrita byte-idêntica é a razão
de existir da cópia: um serializador próprio que reproduz o estilo do jogo
(sem espaço antes de `/>`, ordem de atributos preservada, escapes mínimos, sem
declaração XML) mais um trailer de bytes crus recuperado por diferença.

Enquanto este repositório só lê saves, uma divergência com o upstream é
inofensiva. A partir do momento em que ele **escreve** — o injetor de nave, e
depois o construtor de retratos da fase 2 — uma divergência corrompe partida de
jogador. Por isso o teste cruzado é obrigatório antes da fase 2.

### Teste cruzado (pendente)

Ainda não escrito, porque depende de saves reais que não existem nesta máquina.
O que ele precisa fazer:

1. carregar o mesmo save com esta cópia e com a do editor
2. serializar os dois e exigir bytes idênticos entre si **e** com o original
3. falhar ruidosamente se qualquer um dos três divergir

Enquanto ele não existir, `tools/save_diff.py` e `tools/save_snapshot.py` são
seguros por serem somente leitura, e o injetor deve ser tratado como
experimental — usar só em cópia de save, nunca no save canônico de alguém.
