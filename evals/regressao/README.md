# Conjunto de regressão (#253)

Casos de teste da decupagem, sem vídeo: cada caso aponta o vídeo pelo SHA-256 do bloco `video` da Decupagem, o do arquivo enviado (o vídeo fica no bucket).
O formato e as regras estão em `api/regressao.py`.

- `casos/*.json`: um caso por arquivo. O esperado usa os tipos do `api/comparador.py` (`aparicao`, `mencao`, `pauta`, `comercial`, `plano`, `fala`, `texto_na_tela`, `objeto`, `bloco`).
- `metas.json`: a meta (de 0 a 1) de cada requisito, `{"requisito": 0.95}`. O #252 preenche.
- `reservado`: os reservados só entram na avaliação final, nunca no ajuste de instrução. O sorteio vem do id do caso (20%), então o caso fica sempre do mesmo lado; o formato recusa um valor diferente do sorteio.
- `make exportar-regressao [PASTA=...]`: grava um caso por correção em vigor (aprovada, ou de tipo que não exige aprovação, e não desfeita), com o Job, o trecho e a `versao_pipeline` da decupagem que errou. A correção feita sobre outro JSON do modelo (antes de um reprocessamento) fica de fora, e o caso de uma correção que deixou de valer sai da pasta. Pessoa sem nome não vira caso: o comparador não a pareia.
- `make regressao VERSAO=... [RESERVADOS=1] [CONFIRMAR=1]` (#254, `api/regressao_da_versao.py`): mede a versão pedida e a aprovada contra o esperado de cada caso e grava Markdown e JSON em `regressao-da-versao/` (por requisito e caso a caso: melhorou, piorou ou igual, e a meta). Sem `RESERVADOS=1` os reservados ficam fora; com ele, só eles entram. Sem `CONFIRMAR=1` só mostra o custo estimado. Sai com código 1 se um requisito fica abaixo da meta. As decupagens de cada versão vêm de `DECUPAGENS` (pasta de `*.json`).
