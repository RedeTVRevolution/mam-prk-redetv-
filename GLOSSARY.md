# MAM RedeTV

Decupagem automática do acervo de vídeo da RedeTV com IA: descrever o que aparece, o que se diz e o que se anuncia em cada vídeo, com tempos, para que editores achem e reaproveitem material.

## Linguagem

### Vídeo e programa

**Decupagem**:
Documento que descreve o conteúdo de um vídeo com tempos: pessoas, pautas, planos, comerciais e transcrição.
_Evitar_: resultado, insights

**Job**:
Um pedido de decupagem de um vídeo, do registro ao fim do processamento.
_Evitar_: tarefa, pedido

**Etapa**:
Passo do processamento de um Job que o Workflows roda (validação, transcrição, leitura da tela, análise, identificação, quadros-chave, indexação, nessa ordem), com início, fim e resultado (`concluida` ou `falhou`). A transcrição e a leitura da tela rodam em paralelo, cada uma num Job com GPU, e a análise só começa quando as duas terminam. Essas duas etapas registram também o `dispositivo` (`gpu` ou `cpu`, se o plano B entrou) e as `tentativas_gpu`. A falha de uma etapa depois do `concluido` não muda o estado do Job.
_Evitar_: fase

**Dispositivo**:
Onde a transcrição e a leitura da tela rodam: `cpu` (padrão) ou `gpu` (L4, em `us-east4`, ADR 0007), pela variável `DISPOSITIVO` (`api/dispositivo.py`). Pedir `gpu` numa instância sem GPU derruba o Job com mensagem clara, sem cair para a CPU em silêncio; o plano B em CPU é do Workflows. As imagens GPU ficam num repositório próprio em `us-east4`, e cada publicação testa as que mudaram em modo de teste (`MODO_TESTE=1`, uma fala sintética e um quadro com `REDETV` que estão na imagem; saída 20 = GPU não funcionou, 21 = resultado errado), voltando ao digest anterior se falhar (na primeira publicação não há anterior). Cada imagem com GPU copia só os módulos de `api/` que o ponto de entrada dela importa (#388), então mudar um módulo que os Jobs com GPU não usam (o painel, por exemplo) não muda o digest, e o deploy não republica nem testa esses Jobs; `api/tests/test_imagens_gpu.py` falha se a lista do `Dockerfile` não bater com os imports (módulo faltando ou sobrando).

**Reprocessar**:
Refazer um Job a partir de uma etapa, sem enviar o vídeo de novo (`POST /v1/jobs/{id}/reprocessar`). As etapas anteriores não rodam, e cada reprocessamento vai à auditoria (`video.reprocessado`).
Há dois jeitos. **Reprocessar o que falhou** (`video.reprocessar`, Editor, Curador e Administrador) recomeça da primeira etapa que falhou e só vale para falha de etapa; a falha do arquivo pede novo envio. **Reprocessar a partir de uma etapa escolhida** (`video.reprocessar_etapa`, Curador e Administrador) refaz um vídeo `concluido` e bom, por exemplo por uma instrução nova: o corpo do pedido traz a `etapa` (análise, identificação, quadros-chave ou indexação) e o motivo, obrigatório, e a auditoria marca `etapa_escolhida`. Com a análise escolhida o Job volta a `analisando`, a Decupagem some até a nova análise terminar e o progresso das janelas é descartado, para o modelo rodar de novo em todas; com as outras, o Job continua `concluido`.

**Corrigir o estado**:
Pôr um Job em `concluido` ou `falhou` à mão, só o Administrador (`job.corrigir_estado`), com motivo obrigatório: `POST /v1/admin/jobs/{id}/estado` ou `make corrigir-estado JOB=... ESTADO=... MOTIVO=...`, pela mesma função (`api/correcao_de_estado.py`). As transições valem em `api/ciclo_de_vida.py` (`DESTINOS_DA_CORRECAO`): falhar vale de qualquer estado não final e fecha como `falhou` as etapas que estavam em andamento, com o código da falha da primeira delas (o "reprocessar o que falhou" recomeça dali; sem etapa aberta, ou com a validação aberta, a falha conta como do arquivo); voltar a concluído, só de `falhou` ou `analisando` e se a decupagem guardada passar pelo esquema inteiro. A correção não dispara nada: a indexação fica como estava, e para o vídeo entrar na busca reprocessa-se a partir da indexação. Se a auditoria não grava, o Job volta ao que era. Vai à auditoria como `job.estado_corrigido`, com o estado de antes e o de depois; no comando, quem fez é o `sistema` `corrigir-estado:<usuário da máquina>`.

**Evento de uso**:
O registro de uma ação para o painel da diretoria (`api/eventos_de_uso.py`, #279): `login`, `envio`, `fim_de_processamento`, `busca`, `correcao` ou `chamada_de_api` (só de chave de sistema). Leva quem agiu (só o id), quando, o Job e o programa, e os dados do tipo; na busca (por texto, por imagem ou de parecidos) vai o tamanho da consulta e os filtros, nunca o texto; na correção, o tipo do registro, inclusive desfazer, descartar e reaplicar da fila e a aprovação ou recusa do Curador. Vai ao tópico `mam-eventos-de-uso` e uma assinatura do BigQuery o grava na tabela `eventos_de_uso`. O evento sai dentro da requisição, antes da resposta (#375: a `mam-web` só tem CPU durante ela, então uma thread depois podia perdê-lo), com uma tentativa só e tempo de 5 s. Falha ou tempo esgotado vai ao log e não derruba a ação. A mesma ação pode chegar duas vezes: o `id` serve para descartar a repetida.

**Resumos de uso**:
As tabelas que o painel da diretoria lê (`infra/modulos/mam/resumos_de_uso.sql`, #280): `uso_por_dia_e_usuario`, `uso_por_dia` (com `usuarios_ativos`, só pessoas que agiram no dia: o fim do processamento do vídeo delas não conta), `uso_por_usuario` e `uso_por_dia_e_programa`, no dataset das decupagens. Uma consulta agendada as atualiza a cada 10 minutos a partir dos Eventos de uso, lendo só as partições dos últimos 2 dias (o `janela_dos_resumos_em_dias` do `resumos_de_uso.tf`) e trocando os dias da janela nas tabelas por dia; `uso_por_dia` e `uso_por_usuario` são refeitas da tabela por dia e usuário. Ela descarta o `id` repetido e o fim repetido de um Job reprocessado (o mesmo estado final conta uma vez, pela tabela interna `fins_de_processamento_contados`); o dia é o de São Paulo e as horas são as dos vídeos concluídos, pela `duracao_do_video_ms` que o evento de fim traz (o fim gravado antes disso vale 0 hora). Nenhuma leitura toca os momentos. As telas do painel não leem a tabela de eventos. A API as lê em `GET /v1/painel/filtros` e `GET /v1/painel/acessos` (só com `painel.ver`; as abas aceitam `formato=csv`; no CSV de acessos o `ultimo_acesso` sai em horário de São Paulo com o deslocamento, como `2026-11-04T23:30:00-03:00`, para bater com o `dia`; o JSON segue em UTC com `Z`), pelas variáveis `PAINEL_TABELA_POR_DIA_E_USUARIO` e `PAINEL_TABELA_POR_DIA_E_PROGRAMA`; acessos não têm programa (422 se pedido) e trazem os usuários ativos por dia, semana (de segunda) e mês, cada pessoa uma vez em cada um; a linha só com o fim do processamento de um vídeo não conta como acesso. `GET /v1/painel/videos` (enviados, concluídos, com falha, horas e tempo médio de processamento dos concluídos, por dia, programa e usuário ou sistema) e `GET /v1/painel/buscas` (buscas, usuários que buscam, buscas sem resultado, por dia e por usuário) leem as mesmas tabelas, com as colunas novas `segundos_de_processamento` (do fim do Job; o reprocessado conta o primeiro fim), `videos_concluidos_com_tempo` (o divisor do tempo médio: o fim gravado antes de o evento trazer o tempo fica fora) e `buscas_sem_resultado` (do `n_resultados` do evento de busca). Programa e usuário juntos nessas duas dão 422, porque as tabelas por programa e por pessoa não se cruzam; com programa, `usuarios_que_buscam` vem `null`. Duas tabelas a mais, `correcoes_por_dia` e `chamadas_de_api_por_dia` (variáveis `PAINEL_TABELA_CORRECOES_POR_DIA` e `PAINEL_TABELA_CHAMADAS_POR_DIA`), alimentam `GET /v1/painel/revisao` (correções por dia, tipo e usuário; taxa de correção por tipo e por programa; minutos de revisão por pessoa e por programa; os filtros se cruzam, a taxa não tem pessoa e vem vazia com filtro de usuário, e os minutos são o acumulado da medida cujo último pulso cai no período; o CSV é uma tabela com a coluna `indicador`) e `GET /v1/painel/api` (chamadas, erros do cliente e do servidor por dia, sistema e rota, e vídeos enviados por sistema; programa dá 422 e `usuario` filtra o sistema). A taxa de correção lê a decupagem de cada Job com correção ou pulso no período, por isso só a aba Revisão a calcula. O e-mail de cada pessoa vem da lista de contas do Identity Platform, lembrada por 60 s em cada instância: uma conta nova leva até 60 s para aparecer com e-mail nas abas e nos filtros. As telas são `/painel/acessos`, `/painel/videos`, `/painel/buscas`, `/painel/revisao`, `/painel/api` e `/painel/custo`, e `/` leva ao painel quem tem `painel.ver` sem `decupagem.ver`.

**Custo do painel**:
A aba Custo (`api/custo_do_painel.py`, #285, `GET /v1/painel/custo`): custo por hora de vídeo e por mês, por usuário (ou sistema) e no total, lido da exportação do faturamento (dataset `faturamento`, variáveis `FATURAMENTO_DATASET` e `FATURAMENTO_TABELA`; a conta de faturamento paga só o MAM, então não há filtro por projeto) e cruzado com os Jobs pelo rótulo `job_id`. O custo é líquido de créditos; o de um Job conta no mês de criação dele (dia de São Paulo); horas e custo por hora são só dos Jobs concluídos. O que não tem rótulo de Job (custo fixo como a réplica do índice, Cloud Run Jobs, que não aceitam rótulo por execução, os embeddings e a busca) é custo sem dono, por serviço, e só entra sem filtro de programa ou de usuário. O dataset nasce na mesma região das decupagens, então não há cópia agendada.

**Evento de fim de Job**:
A mensagem que o Pub/Sub leva quando um Job passa a `concluido` ou `falhou` e o sistema dono tem webhook (`api/eventos_do_job.py`, #273). Quem muda o estado nos Jobs de validação, transcrição, OCR e análise publica (`RepositorioQuePublicaOFim`), com o id do evento criado ali; a assinatura push chama `POST /interno/webhook`, que faz uma tentativa de entrega e devolve 503 se o destino falhou de modo repetível, para o Pub/Sub tentar de novo e, esgotadas as tentativas, mandar à fila de mensagens mortas. A correção de estado à mão não publica. O `falhou` que o Workflows grava direto (tempo esgotado, memória, erro que ninguém tratou) é avisado pelo Job `mam-fim` (`api/fim_do_job.py`, #379), que publica o evento de fim de Job e o evento de uso `fim_de_processamento` uma vez por falha (o Job guarda `fim_avisado_no_reprocessamento`).

**Bloco**:
Segmento editorial de um programa de TV, como a abertura ou o trecho entre dois intervalos.
_Evitar_: segmento, parte

**Plano**:
Trecho do vídeo entre dois cortes de câmera. A descrição (ambiente, ação, objetos) é do intervalo entre cortes, não do trecho que o modelo descreveu; a tela preta é um plano com ambiente "tela preta".
_Evitar_: cena, take

**Plano limpo**:
Plano sem GC e sem ninguém falando para a câmera, reaproveitável como B-roll.

**Texto na tela**:
GC, tarja, legenda, placar, chamada, logo ou QR code, com o texto lido e os tempos. O Gemini lê o texto; os tempos são medidos nos quadros pelo OCR (`medido`), e o texto que o OCR não acha fica com o tempo do Gemini e `medido=False`.
_Evitar_: lettering

**Leitura da tela**:
O texto que o OCR lê no proxy, um quadro por segundo (`api/leitura_da_tela.py`). O OCR só lê de novo quando a imagem muda (`api/mudanca_da_tela.py`, #233): compara com o último quadro lido, em seis faixas horizontais de oito blocos, contra o limiar `LIMIAR_DE_MUDANCA`; o quadro igual repete a leitura, e o formato guardado segue com um quadro por segundo. O detector (`server` ou o leve `mobile`) é o `ARG DETECTOR` da imagem. `make comparar-leituras` compara duas leituras do mesmo vídeo.

**Perfil do programa**:
Contexto fixo de um programa (apresentadores, repórteres, merchandising frequente), cadastrado no Firestore (`api/programas.py`) e editado na aba Programas da administração (permissão `programas.editar`: Editor, Curador e Administrador), que a instrução do modelo recebe quando o Job informa o programa.

### Pessoas e evidência

**Catálogo de pessoas**:
Dado vivo no Firestore (`api/catalogo.py`) com as pessoas frequentes da emissora, em todos os programas: cada pessoa tem id estável, nome, papel e apelidos. Começou pela carga de `docs/migracao/programas-2026-11.toml` (`make carregar-programas`) e cresce com as confirmações. A Decupagem aponta para ela por `catalogo_id`, gravado quando a correção de nome da revisora casa com uma só pessoa do catálogo, ou quando o código confirma o nome por uma prova (GC ou fala; que acha a pessoa no catálogo por nome ou apelido, ou a acrescenta).
_Evitar_: base de famosos

**Catálogo de marcas**:
Dado vivo no Firestore (`api/marcas.py`), no molde do de pessoas: id estável, nome e apelidos. Começa pela carga das marcas já vistas nos comerciais das Decupagens (`make carregar-marcas`, idempotente) e cresce com os nomes novos digitados por quem corrige. A Decupagem aponta para ela por `catalogo_id` no comercial, gravado quando a correção da marca vem com o id escolhido no autocompletar.

**Autocompletar**:
`GET /v1/catalogo/pessoas?q=` e `/v1/catalogo/marcas?q=` (`api/rotas_do_catalogo.py`, `api/achar_nomes.py`): até 10 resultados, por prefixo de palavra do nome ou do apelido, sem acento nem maiúscula, com um erro de digitação tolerado em termos de 5 letras ou mais. O `POST` do mesmo caminho acrescenta o nome digitado como **a revisar** (com o autor) ou devolve o que já existe com esse nome; a tela Pessoas do Curador, que revisa esses nomes, fica para outro ticket. A correção de nome de pessoa ou de marca que traz `catalogo_id` o grava; o servidor recusa (422) o id que não existe ou que é de outro nome.

**Nome confirmado / palpite**:
`Pessoa.estado_do_nome`. Confirmado é o nome com uma prova que o código conferiu (`api/identificacao.py`): um GC ou tarja com o nome ou apelido, ou o nome ou apelido dito no texto original do Whisper, enquanto a pessoa está na imagem e sem outra pessoa sem nome na imagem no mesmo intervalo. O nome que o modelo deu sem prova conferida é palpite. Estar no perfil ou no catálogo torna a pessoa candidata e não confirma nome; `contexto` não é prova. A correção da revisora (`origem` `revisao`) vale mais e nenhum reprocessamento a sobrescreve.
_Evitar_: aceitar `fontes_do_nome` como declarada pelo modelo

**Modelo forte**:
O 3.8 Flash (`api/modelo_forte.py`), que olha cada pessoa "não identificado" depois da análise: as de mesma descrição são uma pessoa só, uma chamada cada (até um limite por vídeo, as de mais tempo na imagem primeiro), com 2 ou 3 quadros das aparições mais longas da cópia limpa e todas as pistas do vídeo. O nome que ele dá passa pela conferência de provas: com prova é `confirmado` (origem `modelo_forte`), sem prova é `palpite`. Nunca identifica pela memória.

**Aparição**:
Pessoa visível na imagem; só ela conta como tempo de tela.

**Menção**:
Nome dito na fala ou escrito na tela, sem prova de que a pessoa aparece.
_Evitar_: citação como sinônimo de aparição

**Evidência**:
O que sustenta uma ocorrência: rosto, GC, fala ou quadro.

**Fonte do nome**:
A prova que confirma o nome de uma pessoa, conferida pelo código: GC ou fala (conferida no texto original do Whisper). O rosto sozinho não confirma (ADR 0012). Estar no perfil ou no catálogo torna a pessoa candidata, mas não confirma o nome; o modelo nunca identifica pela memória.

**Palpite**:
Nome que o modelo dá sem prova. Fica como não confirmado, fora dos relatórios de tempo de tela, até a prova (GC ou fala) ou o editor confirmar.

**Palpite descartado / palpite não confirmado**:
Descartado: o nome foi recusado (por exemplo, o editor o corrigiu) e a pessoa volta a "não identificado". Não confirmado: o nome continua palpite porque não há GC nem fala com ele.

### Busca

**Momento**:
Unidade de busca: um plano ou um evento da decupagem, com início e fim. Na resposta da busca, `quadro` é o caminho do quadro no vídeo, e a URL se pede pela rota do quadro (`GET /v1/jobs/{job_id}/quadros/{arquivo}`, com o nome do arquivo). O `quadro_url` assinado é obsoleto (#336): vem `null` para a web e preenchido só para chave de sistema, assinado em paralelo (`TETO_DE_ASSINATURAS`), até sair da resposta.

**Busca visual**:
Modo da busca (`GET /v1/busca?visual=true`, botão "Busca visual" na tela, `?modo=visual` na URL): o texto da consulta vira vetor no Gemini Embedding 2 e entra no mesmo RRF, comparado aos vetores dos quadros-chave dos planos (#268), junto da busca por texto e por significado; só planos, mostrados em grade de miniaturas. Fica ligado só por pedido (cada consulta custa uma chamada ao embedding). Com o índice do quadro desligado ou o embedding fora, a busca roda como a comum e a resposta traz `entendida.visual = false`.

**Singular e plural** (#405):
A busca trata as duas formas como a mesma palavra (`api/numero.py`, regras simples do português, sem dependência): o texto de cada cláusula de objeto e de texto livre vai ao índice com a palavra, o singular e os plurais dela (então não depende de o índice normalizar número), a frase das aspas compara no singular, e o destaque do motivo acende a palavra em qualquer número. A palavra se perdia porque `_termos`, `_destaques` e o texto da cláusula iam como o modelo ou a pessoa escreveram, e o índice só casa palavra inteira.

**Busca por imagem**:
`POST /v1/busca/imagem` (multipart, `decupagem.ver`), botão "Buscar por imagem" na tela de busca (#270): o modelo da consulta (o mais barato) descreve o objeto da foto em um termo curto, o nome do objeto e no máximo uma característica, e a busca segue exatamente como se a pessoa o tivesse digitado: o mesmo entendimento, Model Armor, índice e ranking, sem o modo visual e sem vetor da foto (#443, [ADR 0015](docs/adr/0015-busca-por-foto-pela-descricao.md)). O termo volta em `entendida.termo_da_foto` e a tela o mostra ("Buscando por: microfone"), para a pessoa refinar digitando; só programa e período filtram, e voltam momentos de todos os tipos, como na busca por texto. A foto é entrada hostil: só JPEG ou PNG pelo conteúdo, limites de bytes e pixels (`BUSCA_IMAGEM_MAX_BYTES`, `BUSCA_IMAGEM_MAX_PIXELS`, opcionais), decodificada e regravada em JPEG sem metadados (`api/imagens_hostis.py`) e nunca guardada: nem disco, nem Storage, nem Firestore, nem log. O corpo é lido pela rota, com teto (`Content-Length` conferido antes, leitura cortada no limite) e só em memória. O JPEG de celular que abre como MPO vale como JPEG. Sem o modelo da consulta, com ele fora ou se ele não achar objeto na foto, responde 503: sem texto digitado não há plano B.

**Planos parecidos**:
Botão "Planos parecidos com este" no plano de agora e no detalhe de cada plano, no inspetor da tela do vídeo (#271): abre `/busca/parecidos?job=&plano=`, a grade dos planos mais próximos pelo vetor do quadro-chave que já está no índice (`GET /v1/busca/parecidos?job=&plano=`, `decupagem.ver`), sem enviar imagem nem chamar o embedding; o próprio plano fica de fora. `plano` é o número do plano no vídeo. O plano sem vetor (vídeo indexado antes do #268, índice do quadro desligado ou embedding que falhou) responde 404 e o botão não aparece: a lista dos planos com vetor vem de `GET /v1/busca/parecidos/planos?job=`, consultada com o vídeo `indexado`.

**Cópia no BigQuery**:
Uma linha por momento da Decupagem entregue (plano, fala, texto na tela, objeto e comercial, este com marca e tipo de inserção), para os relatórios de aparições e menções. Fica no Brasil (`southamerica-east1`), particionada pela data de exibição e agrupada por programa. Cada gravação troca as linhas do Job num único MERGE (nunca acumula versões); roda ao concluir o vídeo e a cada Correção em vigor, e falhar só marca `copia_bigquery.estado = falhou` no Job. `make copiar-para-bigquery` carrega os Jobs que já existem e refaz os que falharam.

**Relatório de tempo de tela**:
Por pessoa do catálogo, num programa e num período de data de exibição (`GET /v1/relatorios/tempo-de-tela`, `formato=csv`; tela "Relatórios › Tempo de tela"): tempo somado das aparições, vídeos e aparições, e as menções na fala e no texto da tela só como contagem. Lê da cópia no BigQuery as linhas `aparicao`, `mencao_na_fala` e `mencao_no_texto` (uma por intervalo de cada pessoa confirmada no catálogo; palpite e "não identificado" ficam fora). Aparições da mesma pessoa no mesmo vídeo que se sobrepõem ou se tocam contam uma vez. A pessoa é o id do catálogo, com o nome mais frequente nas linhas dela. Chave de sistema não consulta (a cópia não guarda o sistema dono do vídeo). Vídeos copiados antes do #266 só entram depois de `make copiar-para-bigquery`.

**Relatório de marcas**:
Por marca, num programa e num período de data de exibição, com filtro opcional por tipo de inserção (`GET /v1/relatorios/marcas?programa=&desde=&ate=&tipo=`, `formato=csv`; tela "Relatórios › Marcas"): número de inserções, tempo somado e número de vídeos, com o detalhe por tipo e, ao abrir a marca, a lista das inserções com o vídeo e o tempo. Lê da cópia no BigQuery as linhas `comercial`. O tempo é a soma das durações, sem unir sobreposições (marca incidental durante o merchan conta nas duas). A marca é o texto da linha. O CSV tem, por marca, uma linha `todos` com o total e uma por tipo. A base de permissão, filtros, CSV e erros é a do relatório de tempo de tela (`api/relatorios.py`, `web/src/relatorios.tsx`).

**Faceta**:
Contagem de vídeos por valor ao lado dos resultados da busca: programa, mês de exibição, pessoa, marca e tipo de momento. É calculada sobre os candidatos que a busca já trouxe (os até 100 registros fundidos pelo RRF), já com os filtros aplicados, e não sobre o acervo todo, porque o índice não agrega. Clicar num valor filtra no índice, antes do teto de registros: programa e mês viram programa e período, e pessoa, marca e tipo entram nos filtros de cada cláusula (`pessoa` casa a pessoa na imagem ou a dona do objeto). Programa e mês são contados pelo registro do índice, que é o que o filtro compara. Vale também no plano B.

**Objeto**:
Peça visível na Decupagem (`objetos`, esquema 1.4): a análise principal registra só o que cada pessoa veste, calça, usa ou segura (roupa, calçado, acessório, na mão), com categoria, tipo, cor base, tom, marca legível, o dono (`pessoa` e `relacao`) e os tempos. Os objetos de cena (veículo, produto, eletrônico, animal, comida) já cabem no esquema, mas vêm da etapa de inventário de objetos (Florence-2), não da análise principal. A categoria diz o que a coisa é (`em_cena` e `na_mao` só quando nenhuma outra serve). A busca filtra pelo objeto inteiro, não por itens soltos no plano.

**Ocorrência**:
Algo detectado num momento: pessoa, marca, objeto ou pauta.

### Arquivos

**Quarentena**:
Lugar onde um vídeo enviado espera a validação; nada é processado a partir dela. A validação apaga o original, aceito ou recusado; o que sobra (o que chegou por uma sessão de upload retomável depois de o Job expirar) some pelo ciclo de vida do bucket em 7 dias (`dias_do_original_na_quarentena`, #369). A URL assinada que abre a sessão vale 15 min e exige `x-goog-if-generation-match: 0`, então o objeto é escrito uma vez só.

**Cópia limpa**:
O MP4 aceito pela quarentena, regravado só com as faixas de vídeo e áudio (as faixas de dados, como a de timecode, ficam de fora), sem metadados e sem recodificar. É dele que todo o processamento parte.
_Evitar_: cópia limpa 720p, original tratado

**Acessos ao vídeo**:
Quem abriu e quem baixou cada vídeo, na auditoria (`api/acessos.py`, #207). `GET /v1/jobs/{id}/download` devolve uma URL assinada (5 min) da cópia limpa, com o nome do arquivo (`Content-Disposition: attachment`), e `GET /v1/jobs/{id}/decupagem/download` entrega o JSON da Decupagem (com as Correções aplicadas) como `{arquivo}.decupagem.json`; os dois valem com `decupagem.ver`, só para Job `concluido`, e gravam `video.baixado` e `decupagem.baixada` antes de responder (se a auditoria não grava, 503, sem a URL nem o arquivo). A abertura (`video.aberto`) é gravada no servidor, no pedido da reprodução, no máximo uma vez por pessoa (ou sistema) e vídeo a cada 30 minutos; falha ao gravá-la não derruba a reprodução. Na tela (#208), o cabeçalho do Visualizador tem "Baixar vídeo" e "Baixar decupagem (JSON)" (as duas rotas acima) e, com `auditoria.ver`, o link "Quem acessou", que abre a aba Auditoria com o vídeo como alvo e as três ações (`acao` repetido na API: `GET /v1/admin/auditoria?acao=a&acao=b`, sem índice novo; o filtro de ação da aba as agrupa em "Acessos").

**Timecode de origem**:
O timecode inicial lido da faixa de timecode do arquivo enviado, guardado no Job e levado ao bloco `video` da Decupagem. Ausente quando o arquivo não tem a faixa. Nos arquivos da RedeTV a faixa vem zerada (`00:00:00;00`, ADR 0011): o valor é o do arquivo, não o timecode da fita.
_Evitar_: timecode inventado, 00:00:00:00 por padrão

**Proxy de escalonamento**:
Cópia do vídeo em resolução maior, usada só para reanalisar trechos no escalonamento.
_Evitar_: cópia limpa 720p

### Análise

**Janela de análise**:
Trecho contínuo do vídeo que o modelo analisa de uma vez, com uma margem de contexto em cada borda.
_Evitar_: bloco, chunk, pedaço

**Escalonamento**:
Reanálise de um trecho por um modelo mais forte, em resolução maior, quando a primeira passada teve dúvida ou o trecho caiu na amostra de controle.

**Amostra de controle**:
Janelas sorteadas que também passam pelo escalonamento, para medir o que a primeira passada não viu, inclusive o que ela nem marcou como dúvida.

**Chave de conteúdo**:
Identidade de uma decupagem: o arquivo, a versão do pipeline e as opções que mudam a saída. Dois jobs com a mesma chave de conteúdo compartilham um processamento.

**Versão do pipeline**:
Nome curto (`2026.11.1`) mais o manifesto do que ele fixa: o modelo de cada etapa, o hash de cada instrução, a versão do esquema e os motores de transcrição, OCR e objetos (`api/versao_pipeline.py`). Cada Decupagem nova grava `versao_pipeline` e `manifesto_do_pipeline`; a anterior, sem o campo, é "anterior à versão". Mudar modelo, instrução, esquema ou motor exige mudar a versão (um teste cobra), e a versão nova permite reprocessar o acervo de propósito (`make reprocessar-versao`).

**Chave de idempotência**:
Identificador de uma intenção de envio do cliente, reutilizado em todas as repetições dessa intenção. No `POST /v1/jobs` vai no cabeçalho `Idempotency-Key` (`api/idempotencia.py`): a primeira chamada cria o Job (202) e as repetições devolvem o mesmo Job (200), por 48 h. A reserva é de quem chama: o mesmo texto em outro sistema é outra chave, e a mesma chave com outro corpo dá 409. Repetição de Job na lixeira ou purgado dá 410 `Este Job foi apagado`: a reserva ganha `job_gravado` depois de gravar o Job, e reserva marcada sem Job é Job purgado.

**Teste de caos**:
Roteiro que bate na API com envios repetidos ao mesmo tempo, entrega repetida e fora de ordem, destino de webhook que cai e volta, e dois sistemas lado a lado, e confere que sobra um Job por chave e que cada sistema vê só os seus (`api/caos.py`). Roda local contra os emuladores (`api/tests/test_caos.py`) e no dev por HTTP (`make caos-dev`).

**Passada de comparação**:
A análise inteira de um Job concluído refeita com outro modelo, sem escalonamento, guardada ao lado da Decupagem com o modelo, a data, o custo e o tempo de cada passo (`api/passadas.py`, `make passada-de-comparacao`). Não é Job nem Decupagem: não é indexada, não aparece no Acervo, não recebe correções nem dispara webhook, e a Decupagem do Job não muda. Cada chamada leva o rótulo de custo `etapa=passada_de_comparacao`. Serve para comparar modelos no mesmo vídeo. `make comparar-passadas` (`api/comparar_passadas.py`, #248) compara a decupagem do Job com uma passada, ou soma vários Jobs, e grava um relatório em Markdown e JSON. No Visualizador (#249), o seletor "Comparar com" mostra as duas decupagens lado a lado, só para leitura (`GET /v1/jobs/{id}/passadas/{passada}/comparacao`).

### Revisão

**Correção**:
Alteração humana sobre a saída do modelo, guardada como camada separada, com autor, data e motivo; a saída original nunca é apagada. A troca de nome de uma pessoa (`pessoa.renomear`) leva junto o locutor das falas da transcrição que tinham o nome que ela tinha na hora (sem acento nem maiúscula; "não identificado" não leva nada), calculado na leitura: desfazer a troca devolve o locutor antigo. Se a troca deixa duas pessoas do mesmo vídeo com o mesmo nome (sem acento nem maiúscula; "não identificado" nunca junta), elas viram uma só no fim de `aplicar` (#352): fica a primeira da lista, com as aparições e menções somadas em ordem, as fontes do nome sem repetir, o estado do nome e o `catalogo_id` da troca mais nova, e as pautas e objetos da absorvida apontam para ela. Também é calculado na leitura: desfazer a troca separa as duas de novo.
_Evitar_: edição, ajuste

**Revisão**:
O modo de edição do Visualizador (botão **Revisar**, tecla E; #328). Dentro dela, corrigir, aceitar sugestão, desfazer, aprovar ou recusar Correção pendente, descartar e reaplicar da fila só gravam a camada de Correções e respondem na hora: nenhuma rota chama `reindexar`. O botão passa a **Aprovar Revisão** (E de novo), que sai do modo e faz `POST /v1/jobs/{id}/revisao/aprovar` (`editar`): põe `indexacao.estado` em `pendente` e dispara uma vez o Job `mam-indexacao` com `JOB_ID` (`DisparoDaIndexacaoNoCloudRun`, variáveis `INDEXACAO_JOB` e `INDEXACAO_REGIAO`), respondendo 202 sem esperar; se o disparo falha volta ao estado de antes (503). Não há marcador de "índice desatualizado": o histórico já mostra a correção gravada depois da última indexação como `salva` (e `indexando` com a indexação `pendente`), e a tela acompanha o histórico até `indexado`. Sair sem aprovar deixa a busca e o BigQuery como estavam.

**Fusão de pessoas**:
Juntar duas pessoas do catálogo numa só, o caso comum de nome duplicado (`api/fusao_de_pessoas.py`, #209, permissão `catalogo.fundir` do Curador e do Administrador). `POST /v1/catalogo/pessoas/{origem}/fundir` (destino e motivo) e `GET .../fundir/impacto?destino_id=` (quantos vídeos mudam e quantas fotos saem). A origem não é apagada: guarda `fundida` (destino, quem, quando, motivo) e some das buscas; o destino ganha o nome e os apelidos dela. Nada gravado é reescrito: a leitura das Decupagens troca a origem pelo destino (`com_pessoas_fundidas`). As fotos de rosto da origem são apagadas (LGPD) e a ação `pessoa.fundida` vai para a auditoria. Na tela, "Fundir com…" na linha da pessoa do catálogo, no modo de catalogação.

**Renomeação em lote**:
Trocar o nome de uma pessoa do catálogo em todos os vídeos de uma vez (`api/renomeacao_de_pessoas.py`, #263, permissão `correcao.aprovar` do Curador e do Administrador). `POST /v1/catalogo/pessoas/{id}/renomear` com `nome` e `previa`: com `previa: true` só conta os vídeos e momentos em que o nome muda; sem ela, troca o nome no catálogo (o antigo fica como apelido, como na fusão), grava `pessoa.renomeada` na auditoria (nome antigo, novo, vídeos e momentos afetados) e reindexa os vídeos afetados em segundo plano. Nada gravado é reescrito: a leitura das Decupagens troca os nomes antigos pelo atual (`com_pessoas_fundidas`; um nome que o editor pôs no vídeo e que não é um nome antigo da pessoa fica), então catálogo e decupagens nunca divergem. O andamento (`RenomeacaoDaPessoa`: vídeos pendentes, estado) fica na pessoa; a rodada se repete até 3 vezes e, se sobrar vídeo, o estado é `falhou` até `POST .../renomear/retomar` (que também destrava uma rodada interrompida; uma instância não roda duas vezes a mesma pessoa). `GET .../renomear/andamento` mostra o progresso. Na tela, "Renomear em todos os vídeos" na linha da pessoa, com a prévia e a confirmação.

**Lixeira**:
Primeiro tempo de apagar um item (`api/lixeira.py`, `/v1/admin/lixeira`, #144, [ADR 0010](docs/adr/0010-lixeira-e-purga.md)): o vídeo ganha `Job.lixeira` (quando, quem, motivo) e some da lista, da busca e das rotas do Job para quem não é Administrador, mas nada é apagado e restaurar volta tudo. Só Job `concluido`, `falhou` ou `cancelado`. Cada envio e restauração vai para a auditoria com o impacto. Vale também para pessoa e marca do catálogo (#151, permissão `catalogo.apagar` do Curador e do Administrador; restaurar e purgar só do Administrador): a pessoa perde as fotos de rosto já no envio e, nas decupagens, o nome confirmado só pelo rosto vira "não identificado"; a marca mantém o texto e perde o vínculo.

**Purga**:
Segundo tempo de apagar: 30 dias depois do envio à lixeira, ou antes por decisão do Administrador, um processo próprio apaga de fato (única exceção à regra de que correções e saída do modelo nunca são apagadas) e deixa o registro na auditoria. O mesmo Job diário (`api/purga.py`, `rodar_a_varredura_diaria`) antes expira os uploads abandonados (#369): o Job em `aguardando_upload` há 24 h vai a `falhou` com `upload_expirado` e o objeto dele sai da quarentena; uma falha nisso não segura a purga.

**Correção pendente**:
Correção de Editor, num tipo que exige aprovação, que espera a decisão de um Curador; fica no histórico e fora da decupagem entregue até ser aprovada (passa a valer) ou recusada (nunca vale). Quais tipos exigem aprovação é a **regra de aprovação**, que o Administrador liga e desliga por tipo na aba "Regras de aprovação" da Administração (`/v1/admin/aprovacao`, #264): a mudança vale na hora para as correções novas, as pendentes continuam pendentes, e cada mudança grava `aprovacao.alterada` na auditoria.

**Juntar e dividir pautas**:
Tipos de Correção (`pauta.juntar`, valor `{ids, titulo}`; `pauta.dividir`, valor `{em_ms, titulos}`) que mudam a estrutura das pautas, podem exigir aprovação como os outros tipos e reindexam o vídeo. Juntar vale só para pautas que se seguem; dividir, para um corte dentro da pauta. No reprocessar, cada uma é reconciliada com as pautas novas do modelo: se o modelo já fez o mesmo, com os mesmos títulos, a correção está atendida; se fez o mesmo com outros títulos, só os títulos mudam; se não, é reaplicada.

**Catálogo do Job**:
Os campos `pessoas_do_catalogo` e `marcas_do_catalogo` do Job: os `catalogo_id` que aparecem na Decupagem entregue (Correções aplicadas, pessoas fundidas resolvidas) (#359). São gravados ao indexar, a cada Correção que muda a Decupagem entregue e na fusão de pessoas, e é por eles (`array_contains`) que o impacto de mandar uma pessoa ou marca para a lixeira, restaurá-la ou purgá-la acha só os vídeos dela, sem abrir todas as decupagens. Job anterior ao campo só entra no impacto depois de `make preencher-catalogo-dos-jobs`, que preenche os dois campos de todos os Jobs concluídos e pode repetir sem mudar nada.

**Correção não reaplicada**:
Juntar ou dividir pautas para a qual o reprocessar não achou pauta correspondente. Não se perde: aparece na fila (`/fila`) com `candidatos` vazios, e só pode ser descartada.
Na tela (modo de catalogação, aba Pautas): `M` marca a pauta em foco, `U` junta as marcadas, `D` divide a pauta em foco no ponto do player; na gaveta, a fila mostra a marca "não reaplicada" com "Refazer à mão" (volta a essas teclas) e Descartar.

**Sugestão**:
Pista do próprio sistema que o editor só confirma (`api/sugestoes.py`, `GET /v1/jobs/{id}/sugestoes`): uma pergunta, o contexto que a sustenta e a correção proposta, no formato das correções. Nunca muda nada sozinha: aceitar cria a correção com o motivo "sugestão confirmada pelo editor" (ou "corrigida", se o editor deu outro nome ou o título da pauta); aceita ou recusada, sai da lista naquele vídeo, mesmo depois de reprocessar e mesmo com a correção pendente. As regras são do servidor: o GC de identificação sobre um "não identificado" (só o tipo `gc` sustenta; a chamada nunca) e o trecho de 30 s ou mais sem pauta. Aceitas e recusadas por tipo ficam em `GET /v1/sugestoes/contagem`.
_Evitar_: palpite (é o nome que o modelo propõe sem prova, ADR 0012)

### Acesso

**Conta local**:
Usuário criado no próprio sistema de identidade, independente do login do sistema legado da RedeTV.

**Administrador**:
Papel com todas as permissões, dado automaticamente aos administradores de emergência.

**Administrador de emergência**:
Conta local que recebe o papel Administrador (acesso total), segundo fator obrigatório e alerta a cada login; existe para não depender do login legado.

**Diretoria**:
Papel só de leitura: vê e baixa as decupagens e os vídeos (`decupagem.ver`) e o painel de indicadores (`painel.ver`); não envia nem edita. O Administrador também a tem. Cada abertura de uma aba do painel e cada exportação em CSV grava `painel.aberto` ou `painel.exportado` na auditoria, com quem, quando, a aba e o filtro (`api/painel.py`); a mesma aba com o mesmo filtro aberta de novo pela mesma pessoa em 30 minutos (recarga) não grava outra abertura.

**Papel**:
Pacote de permissões dado a um usuário, opcionalmente limitado a programas.
_Evitar_: perfil, grupo

**Chave de API**:
Credencial de um sistema consumidor da RedeTV, nunca de uma pessoa.

**Resultado bruto do Florence-2**:
O `florence.json` que o Job de objetos grava em `<job>/objetos/`, com, por quadro-chave de cada plano, os objetos detectados (rótulo e caixa normalizada de 0 a 1) e as regiões com legenda, mais o modelo e a revisão. É a matéria-prima do inventário de objetos de cena; ainda não é a lista `objetos` da Decupagem.

**Inventário de objetos**:
Os objetos de cena de cada plano (`Plano.inventario`), separados de `objetos` (o que a pessoa veste ou segura): nome curto, categoria, cor, marca (só se a legenda citar), as caixas por quadro e o destaque, tudo em português. É preenchido pelo servidor na etapa `inventario_de_objetos`, nunca pela análise. Os objetos de cena usam as categorias `veiculo`, `eletronico`, `produto`, `animal`, `alimento`, `bebida`, `movel`, `decoracao`, `instrumento_musical`, `utensilio`, `documento` e `planta`.
_Evitar_: lista de objetos, detecções

**Destaque**:
Nota de 1 a 3 de quanto um objeto do inventário aparece no quadro, calculada pelo servidor pela área e pela posição de cada caixa, ficando a maior nota entre as caixas do objeto (3: grande e no centro; 2: grande, ou média e no centro; 1: o resto). O modelo não a decide. Na busca, o destaque entra no registro e pesa na ordem: 3% por nível acima de 1.

**Motor do inventário**:
Quem faz o inventário de objetos: `florence` (Florence-2 numa GPU, com o Gemini só convertendo o texto para o português) ou `gemini` (o modelo olha os quadros-chave). Vem da variável `motor_objetos`; o inventário guarda o motor e o modelo que o geraram.

**Sessão de revisão**:
O tempo que uma pessoa passa revisando um vídeo no modo de catalogação (#251). A tela avisa a API ao começar, a cada minuto com atividade (tecla, clique ou player tocando) e ao sair (`POST /v1/jobs/{id}/revisao/pulso`); sem atividade por 5 minutos (`REVISAO_INATIVIDADE_S`) a sessão pausa e o tempo parado não conta. A API guarda por vídeo e por pessoa o tempo ativo, as sessões e a duração do vídeo; duas abas da mesma pessoa não contam em dobro. O total sai em minutos de revisão por hora de vídeo (`GET /v1/jobs/{id}/revisao`, `make tempo-de-revisao`). A pessoa não vê cronômetro: o objetivo é medir.

**Taxa de correção**:
Por programa, versão do pipeline e tipo de correção, as correções em vigor que passaram a valer no período (na aprovação, se exigem aprovação; na criação, se não; não desfeitas; só as feitas sobre o JSON do modelo atual; conta correções, não itens) divididas pelos itens daquele tipo nas decupagens revisadas (#265). Decupagem revisada é a de um Job concluído que teve no período uma correção, uma aprovação ou um pulso de **sessão de revisão**: o vídeo aberto e deixado como estava entra no denominador. O item é o do tipo que a correção corrige (pessoa, pauta, comercial, plano, fala, texto na tela; no `item.tempos`, todos). Sai em `GET /v1/qualidade/taxa-de-correcao?desde=&ate=&programa=` (`correcao.aprovar` ou `auditoria.ver`) e em `make taxa-de-correcao`; a taxa é vazia se não há item.

**Conjunto de regressão**:
Casos de teste da decupagem guardados no repositório em `evals/regressao/` (`api/regressao.py`, #253), sem vídeo: cada caso tem o SHA-256 do vídeo enviado (o do bloco `video`), o trecho e o esperado por categoria, nos tipos do comparador. Nascem do gabarito anotado à mão (`make importar-gabarito`, `api/importar_gabarito.py`, #353, um CSV por vídeo em `evals/gabarito/`) ou das correções em vigor (`make exportar-regressao`, com o Job e a versão do pipeline que errou). Cada caso é **reservado** (só a avaliação final usa, nunca o ajuste de instrução) ou de ajuste, por sorteio estável do id. As metas por requisito ficam em `metas.json`. `make regressao VERSAO=...` (`api/regressao_da_versao.py`, #254) roda uma versão do pipeline nos casos (sem `RESERVADOS=1` só os de ajuste; com ele, só os reservados), compara com a versão aprovada e com o esperado, mostra por requisito e caso o que melhorou, piorou ou ficou igual, e sai com código 1 se um requisito fica abaixo da meta.

**Sinal por programa**:
Depois que a indexação copia um vídeo concluído para o BigQuery (`api/sinal_do_programa.py`, #287), os eventos dele (aparições, menções, pautas, comerciais) por hora de vídeo, contados pelas linhas da cópia (cada intervalo de aparição conta um, sem juntar os que se tocam como no tempo de tela), são comparados com a média e o desvio dos últimos N vídeos do mesmo programa, calculados no BigQuery. Fora de K desvios, sai um log `desvio_de_programa` (programa, tipo, valor, média, desvio) que um alerta do Monitoring pega. Programa com menos de N vídeos, ou histórico sem variação, não alerta. Só o vídeo que acabou de concluir é avaliado (não as Correções nem o `make reindexar` em massa).

**Painéis de observabilidade**:
Três painéis do Cloud Monitoring no `infra/modulos/mam/main.tf` (#288): tempo e custo por etapa, erros e latência da API, e Jobs com GPU. Cada número vem de uma métrica de log (linhas JSON dos Jobs e do Workflows: `duracao_da_etapa`, `uso_do_modelo`, `falta_de_gpu`, mais as requisições da API) ou de uma métrica nativa do Cloud Run. Nos tokens e no custo, a etapa é o Job que chamou o modelo, sem o `mam-` (`analise`, `identificacao`, `inventario`). As requisições da API são só as de `/v1/`, com a rota cortada no recurso (`/v1/jobs`). O custo de uma etapa é a soma dos tokens de cada modelo vezes o preço dele em `precos_por_milhao_de_tokens`; sem preço na configuração só os tokens aparecem. A fila de processamento saiu daqui (#420): `GET /v1/painel/fila` (só com `painel.ver`) conta na hora os Jobs em andamento (aguardando upload, validando, analisando) por estado, com a idade do mais antigo desde a criação; estado vazio vem com zero.

