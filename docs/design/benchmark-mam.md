# Benchmark enxuto de MAMs

> Saiu em 06/11/2026 (decisão do Bruno, #487): as sugestões, o painel de sugestões e a contagem por tipo. O que está abaixo sobre elas é histórico.

Pesquisa de 30/10/2026 em Azure AI Video Indexer, iconik, Frame.io, CatDV, Veritone e Twelve Labs, só em quatro áreas: busca, visualizador, catalogação manual e administração. O objetivo era ver como cada um resolve o básico de forma simples, e não listar todas as funções. Cada padrão traz a decisão à luz das premissas: decupagem e busca em primeiro lugar, ferramenta simples, acervo de 25 anos.

**Limites das fontes**
- A ajuda do iconik (help.iconik.backlight.co) fica atrás do Cloudflare. Os dados dele vêm dos trechos dessas páginas oficiais e das páginas em eu.iconik.io, sem leitura completa.
- Do Veritone Digital Media Hub, a documentação oficial só cobre a busca básica e o portal de administração. A parte de IA vem de um blog da AWS.
- "Não confirmado" quer dizer que não foi achado em fonte primária.
- Moments Lab ficou de fora por falta de documentação pública.

## Busca

| Padrão | Quem faz e como | Precisamos? | Por quê |
| --- | --- | --- | --- |
| Caixa única de texto que busca o acervo inteiro e abre o player no momento exato | Azure VI ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-search)) | **Sim** | É o caso "sapato vermelho" e "Sabrina Sato" |
| Resultado agrupado por vídeo, com trechos (início, fim, miniatura, fala do trecho), vídeos ordenados pelo melhor trecho ou pelo número de trechos | Twelve Labs, `group_by=video` ([SDK](https://docs.twelvelabs.io/sdk-reference/python/search), [ordenação](https://docs.twelvelabs.io/docs/guides/search/sorting)) | **Sim** | É exatamente o formato "vídeo + trechos exatos" |
| Filtro por tipo de evidência (só GC, só fala, só pessoa na imagem) | Azure VI, botão Filters ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-search)); Twelve Labs, `search_options` visual/áudio/transcrição | **Sim** | Separa "disse Sabrina", "GC com Sabrina" e "Sabrina na imagem". Basta uma fileira de chips |
| Marcas dos trechos na barra de tempo do resultado | Frame.io, subclips brancos na timebar ([ajuda](https://help.frame.io/en/articles/9101079-enhanced-search-with-ai-search)) | **Sim** | Barato, e mostra onde está cada ocorrência antes de abrir o vídeo |
| Facetas geradas a partir dos metadados existentes | iconik ([filtros](https://eu.iconik.io/help/pages/search/filters)) | **Sim, poucas** | Programa, ano, pessoa e tipo bastam para 25 anos de acervo |
| "Por que casou" em cada trecho | Só o Frame.io mostra os metadados que casaram no painel; ninguém mostra o motivo semântico | **Sim** | Um rótulo por trecho ("objeto: sapato vermelho", "fala", "GC") gera confiança e custa pouco. É onde dá para ser melhor que eles |
| Busca por pessoa com o tempo e a confiança máxima por vídeo | Azure VI ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/customize-person-model-how-to)) | **Sim**, sem número de confiança | Ajuda a decidir qual vídeo abrir primeiro. Nós temos a fonte do nome (GC, fala, rosto), mais fácil de entender que uma porcentagem |
| Unidade do índice é o trecho (shot), não o vídeo | Veritone, pelo [blog da AWS](https://aws.amazon.com/blogs/machine-learning/how-veritone-uses-amazon-bedrock-amazon-rekognition-amazon-transcribe-and-information-retrieval-to-update-their-video-search-pipeline) | **Sim** (conceito) | Confirma o **momento** do plano como unidade. A interface do Veritone DMH não foi confirmada em doc oficial |
| Sintaxe de campo (`transcript contains X`) | Frame.io ([guia](https://blog.frame.io/2025/12/01/the-ultimate-guide-to-the-new-frame-io-search-experience/)) | Depois | Primeiro filtros visíveis; sintaxe é para usuário avançado |
| Buscas salvas e compartilhadas | iconik ([doc](https://eu.iconik.io/help/pages/search/savedsearch)); CatDV Smart Folders | Depois | Útil, mas não é o básico |
| Curinga `*termo*` | Veritone DMH ([doc](https://support.veritone.com/s/article/000001922?language=en_US)) | Não | A busca semântica e a tolerância a erro de digitação cobrem isso |
| Transcrição fora da busca padrão | iconik: é preciso ligar nas configurações ([doc](https://eu.iconik.io/help/pages/asset/transcription)) | **Não** (armadilha) | A fala tem de estar no índice padrão |

## Visualizador

| Padrão | Quem faz e como | Precisamos? | Por quê |
| --- | --- | --- | --- |
| Player ao lado de um painel de insights por tipo; clicar leva ao momento | Azure VI, widgets Player e Insights ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-embed-widgets)) | **Sim** (já temos) | É o núcleo da tela Vídeo |
| Transcrição sincronizada e editável no mesmo lugar | Azure VI, aba Timeline ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/video-indexer-search)) | **Sim** | Corrigir a fala sem sair do player |
| Busca dentro do vídeo que filtra o painel | Azure VI, parâmetro `search`; Frame.io, acima da transcrição ([doc](https://help.frame.io/en/articles/10966531-frame-io-transcription-overview)) | **Sim** | Leva do resultado da busca ao trecho e, dentro dele, ao item |
| Ir para a ocorrência anterior ou seguinte | CatDV, setas ↑/↓ entre eventos ([doc](https://catdv-docs.services.quantum.com/catdv-client/14/Basic-operation.html)); no Azure VI, não confirmado | **Sim** | É o gesto mais usado depois de buscar |
| J/K/L, Espaço, ←/→ quadro a quadro | Frame.io ([atalhos, doc legada](https://help.frame.io/en/articles/7785-keyboard-shortcuts-legacy)); CatDV só Espaço confirmado | **Sim** | É o padrão dos editores de vídeo, e o editor já sabe |
| Caixas sobre rostos e objetos no player | Azure VI, `boundingBoxes` | Depois | Bonito, mas não é essencial; o Gemini não devolve caixas no esquema atual |
| Comentário de revisão por quadro, versões, desenho no quadro | Frame.io | **Não** | É colaboração de pós-produção, não decupagem |
| Editor de clipes e exportação para editor de vídeo | Azure VI "Open in editor"; CatDV subclips | **Não** | Sofisticação de MAM caro |

## Catalogação manual

| Padrão | Quem faz e como | Precisamos? | Por quê |
| --- | --- | --- | --- |
| Marcar entrada e saída no player (I/O) e anotar o trecho com tags | iconik: I ou `{`, O ou `}` ([doc](https://eu.iconik.io/help/pages/asset/time_based_metadata)) | **Sim** | É o gesto central para "o modelo não achou" |
| Marcador de ponto por tecla (`m`) e edição por atalho | CatDV ([doc](https://catdv-docs.services.quantum.com/catdv-client/14/Basic-operation.html)) | **Sim** | Anotação rápida, toda pelo teclado |
| Nomear uma vez um desconhecido, e o nome vale em todos os vídeos | Azure VI, "Unknown #X" ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/customize-person-model-how-to)) | **Sim** | É o padrão de maior valor para o acervo. No nosso caso, vira entrada do catálogo e referência de rosto ([ADR 0005](../adr/0005-identificacao-por-referencia.md)) |
| Desconhecidos agrupados por semelhança, para nomear em massa | Azure VI, aba "unknown people" | Depois | Exige comparar rostos em lote, que a ADR 0005 ainda não prevê |
| Tela central de pessoas: renomear, fundir, apagar, ver as fotos | Azure VI People; iconik Persons ([doc](https://help.iconik.backlight.co/hc/en-us/articles/34639510232087-Persons-Overview)) | **Sim** | É a tela do catálogo de pessoas e das referências de rosto |
| Confirmar ou rejeitar uma sugestão da IA com um clique | Nenhuma fonte mostrou bem (iconik: não confirmado) | **Sim** (desenhar o nosso) | Ver [catalogacao-manual.md](catalogacao-manual.md) |
| Vocabulário controlado com autocompletar, restrito ou extensível | CatDV, grouping fields com flag "extensible" | **Sim**, só pessoas, marcas, cores e tipos de objeto | Evita "Sabrina Sato", "S. Sato" e "sabrina" |
| Taxonomia hierárquica com listas dependentes | CatDV (fórum de 2011, não confirmado na v14) | **Não** | Complexidade de MAM caro |
| Edição em lote: selecionar vários e mudar uma vez | CatDV Bulk Edit; iconik ([doc](https://eu.iconik.io/help/pages/search/bulk/search_bulk_metadata)) | **Sim**, para renomear pessoa no acervo (já no plano, papel Curador) | Corrigir um nome em 200 vídeos de uma vez |
| Corrigir a transcrição e realimentar o modelo de linguagem | Azure VI | Corrigir **sim**; realimentar **não** | O Gemini e o Whisper não têm modelo de linguagem treinável aqui |

## Administração

| Padrão | Quem faz e como | Precisamos? | Por quê |
| --- | --- | --- | --- |
| Poucos papéis fixos | Azure VI, 3 papéis ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/restricted-viewer-role)); Frame.io, 4 ([doc](https://help.frame.io/en/articles/9875389-user-roles-and-permissions)) | **Sim** (já temos seis no plano) | Simples de explicar e de auditar |
| Grupos com permissões finas e ACL por ativo | iconik ([doc](https://help.iconik.backlight.co/hc/en-us/articles/36813902117143-Role-Group-Administration)) | **Não** | Não há esse requisito; o escopo por programa basta |
| Lixeira com retenção configurável; só o admin restaura ou purga | iconik, 24 h por padrão ([doc](https://eu.iconik.io/help/pages/admin/recycle)) | **Sim** | Apagar com segurança |
| Contador de dias até a exclusão definitiva | Frame.io, 30 dias com "Restore" ([doc](https://help.frame.io/en/articles/10513996-recovering-recently-deleted-assets)) | **Sim** | Deixa claro quanto tempo falta para não ter volta |
| Exclusão imediata e permanente do arquivo e dos insights | Azure VI ([FAQ](https://learn.microsoft.com/en-us/azure/azure-video-indexer/faq)) | **Não** (armadilha) | Arriscado num acervo de 25 anos |
| Separar o que se apaga: o rosto num vídeo não é a pessoa do catálogo; apagar o modelo não muda o índice até reindexar | Azure VI ([doc](https://learn.microsoft.com/en-us/azure/azure-video-indexer/customize-person-model-how-to)) | **Sim** | Responde "o que acontece com o índice": ver [administracao.md](administracao.md) |
| Histórico por ativo e log de auditoria | iconik Asset History ([doc](https://eu.iconik.io/help/pages/asset/history)) | **Sim**, simples | Responde "quem apagou o quê" |
| Termos mais buscados e buscas sem resultado | Veritone DMH ([doc](https://support.veritone.com/s/article/000002755?language=en_US)) | **Sim** (já no painel da diretoria) | Mostra o que falta decupar ou corrigir |
| Ciclo de vida, tiering de armazenamento, restrição por IP na tela | Frame.io ([doc](https://help.frame.io/en/articles/11869776-asset-lifecycle-management)); iconik Shield | **Não** na tela | O Terraform e o Autoclass cuidam disso; o administrador não precisa ver |

## Resumo

**Precisamos**
1. Resultado agrupado por vídeo, com os momentos clicáveis (início, fim, miniatura, fala), como no Twelve Labs.
2. Momentos marcados na barra de tempo e setas para ir à ocorrência seguinte.
3. Filtro por tipo de evidência (na imagem, citada, fala, GC, objeto, marca), em chips.
4. Player ao lado do painel, com transcrição sincronizada e editável.
5. Nomear um desconhecido uma vez, e o nome vale no acervo inteiro.
6. Entrada e saída por tecla, mais tag com autocompletar de vocabulário controlado, tudo pelo teclado.
7. Lixeira com contador de dias e restauração; a purga leva também o índice.
8. "Por que casou" em cada momento: ninguém faz direito, e é barato.

**Não precisamos**
- Permissões por ativo, grupos e taxonomias hierárquicas.
- Revisão por quadro, versões e exportação para editor de vídeo.
- Exclusão imediata e definitiva.
- Ciclo de vida e armazenamento visíveis ao usuário.
- Caixas sobre rostos e objetos (fica para depois).

**Armadilhas**
- Transcrição fora da busca padrão (iconik).
- Exclusão sem volta (Azure VI).
- Busca semântica que sempre devolve algo, mesmo sem relação, e teto baixo de resultados (Frame.io, 50 + 50). Mostrar a contagem real e o resultado vazio de verdade.
- Nomes duplicados de pessoa (Azure VI). Nome único, escolhido do catálogo com autocompletar.
