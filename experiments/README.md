# Experimentos

Área de trabalho do roteiro em [../docs/trade-experiment.md](../docs/trade-experiment.md).

O que cai aqui — `snapshots/` e os perfis de ruído em `.json` — está no
`.gitignore`. Savegame é arquivo pessoal e não entra no repositório: ele carrega
a partida inteira de quem jogou, e o projeto todo se apoia em ser confiável com
isso.

O que **deve** ser versionado é o resultado: as medições vão na seção
"Resultados" do próprio roteiro, em texto, para quem ler o repositório daqui a
seis meses conseguir refazer o raciocínio sem os arquivos.

```
experiments/
  noise.json            perfil de ruído aprendido no E1 (ignorado pelo git)
  snapshots/
    E1-antes/           cópia fiel de um save, com snapshot.json ao lado
    E1-depois/
    E2-antes/
    ...
```

Verificar o que já foi tirado:

```bash
python3 ../tools/save_snapshot.py --list
```

Dois snapshots com o mesmo digest são idênticos — quase sempre sinal de que o
jogo não salvou entre um e outro, e não de que o experimento deu negativo.
