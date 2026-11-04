# Lacunas e tickets propostos

As lacunas que a pesquisa encontrou e os tickets para cobri-las, em ordem de prioridade. Os primeiros melhoram a decupagem e viabilizam a busca. **Nenhum ticket foi criado**: esta lista é a proposta para revisão.

## Lacunas

### Decupagem

1. Objetos sem atributos: `Plano.objetos` é texto livre, sem cor nem tipo. No clipe4, os 7 planos têm só "microfone".
2. Objetos sem tempo próprio: herdam o plano inteiro.
3. Nenhuma ligação entre o objeto e a pessoa que o usa. O figurino existe só como frase em `Aparicao.visual`.
4. Nenhuma marca ligada a objeto (logo na roupa, produto na mão).
5. Planos inventados pelo modelo, e não pelos cortes: a detecção de cortes do plano não está ligada.
6. `quadro` vazio: não há quadro-chave de nenhum momento.
7. Pessoas sem identidade estável entre vídeos (`pes01` dentro de cada decupagem).
8. Falas longas e instáveis no Flash-Lite (uma fala de ~80 s no clipe4; de 2 a 12 trechos no clipe3). Coberto por #78 e #81.
9. Textos na tela com a duração do bloco, não a de cada aparição. Coberto por #76.
10. Tom da pauta em texto livre. Coberto por #77.
11. Instrução do Gemini sem pedido de roupas, calçados, acessórios e objetos na mão com atributos.

### Busca

12. A busca não existe (E2): sem índice, sem rota e sem tela.
13. O Job não tem data de exibição, a faceta mais útil num acervo de 25 anos.
14. Não se sabe se o Agent Retrieval filtra objetos aninhados ("o vestido vermelho **da Sabrina**").

### Visualizador e acervo

15. Nenhum endereço por vídeo nem por tempo: o vídeo abre sem mudar a URL.
16. Nenhum atalho de teclado fora do player nativo.
17. Miniaturas feitas com um `<video>` por item (`web/src/Video.tsx:760`).
18. Destaque da fala atual em vermelho cheio, a cor da marca usada como alerta.
19. Estados vazios sem mensagem (aba Marcas).
20. Marcadores da linha do tempo com nome acessível só de tipo e tempo ("Aparições 00:55"), sem quem ou o quê.
21. Acervo: cartões sem miniatura, selo cortado ("FAL…"), código interno como mensagem de erro, seletor do envio com cara de filtro, sem busca por nome, lista inteira sem paginação.

### Catalogação

22. Toda correção abre um formulário e exige um motivo escrito.
23. Não há como marcar um trecho e dizer o que há nele.
24. Nomes em texto livre, sem autocompletar do catálogo.
25. Nenhuma sugestão para confirmar.
26. Nenhum tipo de correção para objetos, texto na tela novo ou pauta nova. Os campos novos do esquema 1.2 estão em #75 (PR #89).

### Administração e painel

27. Os papéis Administrador e Diretoria não existem no código.
28. Contas, papéis, chaves de API e a regra de aprovação só por `make`.
29. Não há como apagar um vídeo; `DELETE /v1/jobs/{id}` só cancela.
30. Nenhuma auditoria visível na aplicação.
31. Catálogo de pessoas e marcas sem tela.
32. Painel da diretoria inexistente (E9).

### Documentação

33. A [ADR 0004](../adr/0004-gemini-flex-no-video.md) e o plano diziam que o Gemini roda em Standard, mas o código voltou ao Flex no #86 (`api/gemini.py`, cabeçalhos `flex`). Um dos dois precisa ser atualizado. **Resolvida em 03/11/2026:** fica o Flex nas chamadas com vídeo; a ADR 0004 e o plano foram atualizados.

## Tickets propostos, em ordem

| # | Ticket | Cobre | Entrega | Rótulo sugerido |
| --- | --- | --- | --- | --- |
| 1 | **Esquema 1.3: objetos com atributos e dono.** Lista `objetos` (categoria, tipo, cor base de lista fechada, tom, detalhe, marca, pessoa, relação, ocorrências); instrução nova na seção 5; validação de `pessoa` contra as pessoas da decupagem; consolidação remapeia `pessoa` pelo mapa de `unir_pessoas`; regra de tempos de evento visual; cassetes regravados (#69). Medir tokens de saída antes e depois no mesmo clipe | 1–4, 11 | E1 | `ready-for-agent` |
| 2 | **A/B de objetos e cores no piloto.** Comparar visualmente o Flash-Lite em 480p e o 3.8 Flash em resolução alta nos objetos (tipo, cor, dono, tempos); decidir se os planos com pessoas vão para o escalonamento | 1–3 | E1 | `ready-for-human` |
| 3 | **Cortes e quadros-chave na validação.** Detecção de cortes no Job de validação; planos pelos cortes; um JPEG por momento (plano, aparição, objeto) no Storage; `quadro` preenchido; a tela troca o `<video #t>` pela imagem | 5, 6, 17 | E1 | `ready-for-agent` |
| 4 | **Data de exibição no Job.** Campo opcional no `POST /v1/jobs`, no diálogo de envio e na lista do acervo | 13 | E2 | `ready-for-agent` |
| 5 | **Falas curtas** | 8 | E1 | Já coberto: #81 (Whisper) e #78 |
| 6 | **Textos na tela com o tempo exato** | 9 | E1 | Já coberto: #76 |
| 7 | **Catálogo de pessoas com id estável.** Catálogo no Firestore; `catalogo_id` na pessoa da decupagem quando o nome for confirmado | 7 | E1/E4 | Depende de #82 e da ADR 0005 |
| 8 | **Spike: filtro de objeto aninhado no Agent Retrieval.** Indexar 3 decupagens e testar "calçado vermelho da pessoa X" com campo aninhado e com chaves combinadas; registrar a escolha numa ADR | 14 | E2 | `ready-for-agent` |
| 9 | **Índice de momentos.** Um documento por plano (com pessoas, objetos, textos e marcas), por fala, por menção, por pauta e por comercial; indexação ao fim da decupagem e a cada correção, com estado visível | 12 | E2 | `ready-for-agent` |
| 10 | **Rota de busca.** `/v1/busca`: entendimento da consulta em esquema fechado, filtros do servidor, junção de momentos a até 3 s, agrupamento por vídeo, motivo de cada momento; barreiras de "Busca sem injeção" | 12 | E2 | `ready-for-agent` |
| 11 | **Tela de busca e endereços.** Página de resultados agrupada por vídeo, chips de evidência, filtros de programa e ano; rotas `/busca`, `/video/{id}?t=`; momentos da busca marcados no visualizador com `N`/`Shift+N` | 12, 15 | E2 | `ready-for-agent` |
| 12 | **Visualizador.** Player e painel fixos; faixa e aba de objetos; atalhos da tabela de [principios.md](principios.md); destaque neutro do item atual; estados vazios; nomes acessíveis nas faixas; trechos sem pauta hachurados | 16, 18–20 | E2 | `ready-for-agent` |
| 13 | **Acervo em tabela.** Miniatura, programa, data de exibição, estado e autor; busca por nome; paginação; erro em português | 21 | E2 | `ready-for-agent` |
| 14 | **Correções de objeto, texto na tela e pauta nova.** `objeto.acrescentar`, `objeto.atributos`, `objeto.dono`, `objeto.nao_existe`, `texto_na_tela.acrescentar`, `pauta.acrescentar` | 26 | E3 | `ready-for-agent` (depois do 1) |
| 15 | **Modo de catalogação pelo teclado.** `E`, `I`/`O`/`A`, `F2`, `Del`, `Ctrl+Z`; autocompletar de pessoas e marcas do catálogo; motivo preenchido pelo gesto | 22–24 | E3 | `ready-for-agent` |
| 16 | **Sugestões para confirmar.** GC de identificação (nunca chamada) sobre um "não identificado", perfil do programa, palpite sem prova, propagar o nome no vídeo, trecho sem pauta; contagem de aceitas e recusadas | 25 | E3 | `ready-for-agent` |
| 17 | **Papéis Administrador e Diretoria** em `api/papeis.py`, com as permissões do plano | 27 | E8 | `ready-for-agent` |
| 18 | **Telas de administração** de usuários, sistemas e chaves, e regra de aprovação, no lugar dos `make` | 28 | E8 | `ready-for-agent` |
| 19 | **Lixeira e purga.** ADR sobre a purga como única exceção ao repositório de correções que só acrescenta; contagem de jobs por processamento (chave de conteúdo); referências de rosto apagadas já no envio para a lixeira; filtro "fora da lixeira" no índice | 29 | E8 | `ready-for-human` (ADR e LGPD) |
| 20 | **Auditoria visível.** Tela com os registros de apagamento, papel e chave | 30 | E8 | `ready-for-agent` |
| 21 | **Tela Pessoas.** Catálogo com apelidos, referências de rosto, fundir e renomear em lote | 31 | E4 | Depois do 7 |
| 22 | **Painel da diretoria** com buscas sem resultado e taxa de correção por tipo | 32 | E9 | Já no plano |
| 23 | **ADR 0004 × código.** Decidir entre Standard e Flex e alinhar a ADR, o plano e `api/gemini.py` | 33 | — | Resolvido em 03/11/2026 (Flex no vídeo) |
