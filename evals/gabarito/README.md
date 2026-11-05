# Gabarito de famosos (#252, #353)

Um CSV por vídeo, anotado pela equipe, com o que o vídeo mostra e diz e quando. `make importar-gabarito` os transforma em casos do conjunto de regressão (`evals/regressao/casos/`); o comparador (`make comparar`) lê os mesmos arquivos.

```csv
# sha256: 3f2a…(64 caracteres hexadecimais, o SHA-256 do arquivo enviado)
tipo,identidade,inicio,fim
aparicao,Ana Maria Braga,00:00:10,00:01:05
aparicao,Louro José,01:05,01:20
comercial,Ambev,01:00:00,01:00:30
```

- A primeira linha é `# sha256: <hex>`; depois vem o cabeçalho `tipo,identidade,inicio,fim`.
- `tipo`: `aparicao`, `mencao`, `pauta`, `comercial`, `plano`, `fala`, `texto_na_tela`, `objeto` ou `bloco`.
- Uma linha por aparição contínua: se a pessoa sai de cena e volta, são duas linhas.
- `identidade` igual ao nome do catálogo de pessoas (ou de marcas), com a mesma grafia. Pauta, plano, fala e bloco só têm tempo.
- Tempos em `MM:SS` (os minutos podem passar de 59) ou `HH:MM:SS` (minutos e segundos de 0 a 59), contados do início do arquivo.
- O comparador aceita 2 s de diferença no início e no fim.

Comando: `make importar-gabarito [GABARITO=evals/gabarito] [PASTA=evals/regressao/casos]`. Rodar de novo regrava os mesmos casos, sem duplicar.
