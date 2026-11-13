# Ranking em Python sobre as somas em cache

Os relatórios de tempo de tela e de marcas ordenam, paginam e montam o detalhe em Python, a partir das somas por pessoa ou marca que o BigQuery devolve e o cache guarda. O BigQuery só calcula as somas.

**Decisão de 13/11/2026 — Bruno:** o SQL de ranking, detalhe e lista sai, com os testes que o exercitam; o SQL das somas fica. A interface da consulta ao BigQuery passa a ter só `somas`, e o ranking paginado e o detalhe ficam nos módulos de cache e de lixeira que já os calculam em Python.

O motivo é que o SQL de ranking deixou de rodar em produção. Ele entrou no #428 (cf8dde0d, 05/11), com teto e paginação no BigQuery; no #453, mesclado no #503 (e58246e2, 07/11), a soma por filtro passou a ser calculada uma vez e guardada em cache, e o ranking inteiro, a página, a pessoa expandida e o CSV saem dela em Python, sem consultar o BigQuery de novo. Desde então o SQL de ranking só existe nos Protocols e nos testes, e a lixeira na leitura (#583) foi aplicada só no caminho em Python. Manter dois caminhos que dão a mesma resposta obrigava cada mudança de regra (lixeira, desempate pelo nome atual) a ser feita duas vezes.

Não houve medição do custo em Python. Se o número de pessoas ou marcas crescer a ponto de as somas não caberem em memória ou o cache ficar lento, a saída é recuperar o SQL do #428 (cf8dde0d) e levar para lá as regras da lixeira e do nome atual.
