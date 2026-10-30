# Plano de produção — decupagem automática do acervo RedeTV no Google Cloud

Oct 27, 2026 · @RedeTV!

## Resumo

A decupagem entra em produção como serviço serverless para \~20 h de vídeo por dia. O processamento custa cerca de US$ 0,73 por hora de vídeo; somando custos fixos, armazenamento e uso, a operação fica em \~US$ 540/mês no início e \~US$ 615/mês no terceiro ano (estimativa, a medir no piloto). O plano anterior custava US$ 2,50–4,00 por hora só de modelo. A queda vem de duas escolhas: Gemini 3.5 Flash-Lite como modelo de volume e vídeo em resolução padrão, com o 3.8 Flash só nos trechos com dúvida e numa amostra de controle. O Gemini roda no modo Standard, pelo dobro do preço do Flex, porque a espera do Flex deixava o vídeo minutos parado ([ADR 0004](adr/0004-gemini-em-standard.md)).

| Decisão | Escolha |
| --- | --- |
| Modelo | Gemini 3.5 Flash-Lite em todo o vídeo; Gemini 3.8 Flash em resolução alta onde houver dúvida e numa amostra aleatória de controle. Confirmar no piloto A/B da E1, por comparação visual lado a lado |
| Consumo | Standard (síncrono, resposta em segundos; [ADR 0004](adr/0004-gemini-em-standard.md)); Batch, com 50% de desconto, para o acervo histórico |
| Arquitetura | 100% serverless: Cloud Run (front, API e jobs), Workflows, Firestore, Cloud Storage, Eventarc, Pub/Sub |
| API | REST assíncrona: cria o job, consulta o status, baixa o JSON completo; webhook opcional |
| Segurança | Produção acessível só pela rede da RedeTV; chave de API por sistema; login pelo Identity Platform; Cloud Armor e VPC Service Controls |
| Duplicidade | `Idempotency-Key` por requisição; SHA-256 conferido depois do upload evita processar o mesmo arquivo duas vezes, sem dar acesso à decupagem de outro sistema |
| Vídeos longos | Janelas de análise de 5 min em paralelo; qualquer duração, uma resposta única |
| Fora do escopo | Video Intelligence, Cloud Vision, transcrição separada |
| Busca | Vídeos e momentos por pessoa, objeto, cena, frase ou imagem: Agent Retrieval híbrido com reordenação |
| Stack | Python (FastAPI, Pydantic) no back, React com TypeScript no front, Terraform na infraestrutura |
| Testes | TDD com testes unitários sem nuvem, emuladores locais e um ambiente efêmero por PR no GCP |
| Credenciais | Nenhuma chave em arquivo: chaves no Cloud KMS, chaves de API só como hash, segredos de terceiros no Secret Manager |
| Entregas | Fatias verticais testáveis de ponta a ponta, começando por uma POC com vídeos curtos e, logo depois, um piloto com cinco programas completos comparados lado a lado entre os modelos |
| Entradas | Só MP4 válido, conferido em quarentena e regravado; toda entrada tratada como hostil; busca protegida contra injeção |
| Usuários | Identity Platform: contas locais com administrador de emergência desde a E0; login pela API do legado quando ela existir; papéis com permissões granulares |
| Revisão | Área restrita para corrigir e completar a decupagem, com histórico; o catálogo de pessoas nasce das correções |
| Painel | Indicadores por usuário e totais para a diretoria, dentro da aplicação, com acesso restrito |
| Acervo | 25 anos processados aos poucos em Batch, com teto mensal de gasto e fila por prioridade |

O Gemini identifica os famosos (inclusive brasileiros) pelo GC, pela fala e pela comparação do rosto com fotos de referência buscadas na web, nunca pela memória; o código confere a prova de cada nome ([ADR 0005](adr/0005-identificacao-por-referencia.md)). Tudo roda no GCP, inclusive o front: a RedeTV não mantém nenhum servidor próprio.

## Escolha do modelo

O Gemini 3.5 Flash-Lite é o melhor custo para decupar o vídeo inteiro: custa cerca de 1/4 do 3.8 Flash por hora, e o Google o indica para raciocínio em vídeo complexo ([model card](https://deepmind.google/models/model-cards/gemini-3-5-flash-lite/)). O 3.8 Flash entra só nos trechos em que o Flash-Lite tiver dúvida.

| Modelo | Entrada / saída Standard (US$ por 1M tokens) | US$ por hora de vídeo (Standard) | Vídeo longo (LVBench) | Papel |
| --- | --- | --- | --- | --- |
| Gemini 2.5 Flash-Lite | 0,10 / 0,40 | \~0,08 | — | Geração anterior; descartado |
| Gemini 3.1 Flash-Lite | 0,25 (áudio 0,50) / 1,50 | \~0,24 | — | Alternativa mais barata; sem modo agêntico |
| **Gemini 3.5 Flash-Lite** | 0,30 / 2,50 | \~0,30 | — | **Modelo de volume** |
| Gemini 3.5 Flash | 1,50 / 9,00 | \~1,24 | — | Sem vantagem sobre o 3.8 Flash |
| Gemini 3.8 Flash | 1,50 / 7,50 (metade até 31/12/2026) | \~1,14 | 87,1% ([model card](https://deepmind.google/models/model-cards/gemini-3-8-flash/)) | Escalonamento e referência do piloto |
| Gemini 4 Argon | Batch 2,00 / 10,00 (a partir de 01/12/2026) | \~1,53 (Batch) | 91,7% | Não usar no volume |

Premissas do custo por hora: preços Standard do endpoint global, o dobro do Flex ([tabela](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)); resolução padrão de 70 tokens por quadro a 1 fps e áudio a 25 tokens/s ([media resolution](https://ai.google.dev/gemini-api/docs/media-resolution)); 7% de sobreposição entre janelas; \~60 mil tokens de saída por hora, já com transcrição e raciocínio baixo. No dev, em 30/10/2026, o clipe2 (5 min) custou \~US$ 0,02 no Flash-Lite em Standard, ou \~US$ 0,24 por hora, dentro da estimativa. Modelos em preview (3 Flash, 3.1 Pro) ficaram de fora.

Não há benchmark público de vídeo longo para o 3.5 Flash-Lite. Por isso a escolha é confirmada no piloto da E1: cinco programas completos e variados, processados inteiros pelos dois modelos, sem depender das dúvidas do primeiro, e comparados visualmente lado a lado no player (ver Qualidade em produção). Se o Flash-Lite ficar aquém só em famosos, apenas a detecção de pessoas sobe para o 3.8 Flash.

O modo agêntico corta até 88% dos tokens em perguntas pontuais sobre vídeos longos, mas a decupagem precisa varrer o vídeo inteiro: fica no processamento estático. O agêntico serve depois, para a busca no acervo.

## Custo

O custo tem quatro partes: o variável, por hora de vídeo processada; o fixo, que existe mesmo sem vídeo; o armazenamento, que cresce todo mês porque os resultados ficam guardados indefinidamente; e o uso do player. Com 600 h de vídeo por mês:

| Parte | Item | Estimativa |
| --- | --- | --- |
| Variável | Passada de volume: 3.5 Flash-Lite em Standard | US$ 0,30/h |
| Variável | Escalonamento: 3.8 Flash em Standard nas dúvidas e na amostra de controle (\~10–15% do tempo) | US$ 0,30/h |
| Variável | Indexação para a busca (quadros-chave e texto, em Batch) | US$ 0,05/h |
| Variável | Cloud Run: validação com decodificação completa, derivados, chamadas e consolidação | US$ 0,08/h |
| **Variável** | **Total: US$ 0,73/h × 600 h** | **\~US$ 440/mês** |
| Fixo | Balanceador, Cloud Armor e IP fixo do NAT (estimativa da revisão, a confirmar na calculadora) | \~US$ 30/mês |
| Fixo | KMS, Secret Manager, Identity Platform, monitoramento | Poucos dólares |
| Fixo | SerpAPI para as fotos de referência: US$ 0,01 por busca na conta atual, poucas centenas de buscas por mês com as fotos guardadas; um plano próprio começa em US$ 25/mês | Poucos dólares |
| Armazenamento | Proxies de reprodução e índice de busca, crescendo todo mês | \~US$ 5 no mês 1, \~US$ 40 no mês 12, \~US$ 85 no mês 36 |
| Uso | Saída de dados do player (\~0,45 GB por hora assistida) | \~US$ 10/mês para 150 h assistidas |
| Reserva | Testes, avaliação e reprocessamentos (+10% do variável) | \~US$ 44/mês |

|  | Mês 1 | Mês 12 | Mês 36 |
| --- | --- | --- | --- |
| **Total estimado** | **\~US$ 540** | **\~US$ 570** | **\~US$ 615** |

Não é orçamento fechado: o piloto (E1) mede o consumo real por etapa e por tentativa, a taxa de escalonamento e a latência. O Standard custa \~US$ 200/mês a mais que o Flex: \~US$ 90 na passada de volume, \~US$ 90 no escalonamento e o resto na reserva. Se o escalonamento puder esperar minutos, ele em Flex devolve \~US$ 90/mês. A chamada ao Gemini continua num serviço com concorrência: num Cloud Run Job, a espera da resposta pagaria CPU parada. O desconto de 50% do 3.8 Flash até 31/12/2026 não entra na conta.

De onde vem a economia:

| Alavanca | Efeito |
| --- | --- |
| 3.5 Flash-Lite em vez de 3.8 Flash no volume | \~75% a menos por hora |
| Resolução padrão (70 tokens por quadro) em vez de alta (280) | 75% a menos nos tokens de imagem |
| Transcrição na mesma chamada do Gemini | Evita o Gemini 3.5 Transcribe, que sairia \~US$ 0,31/h, mais que a passada inteira |
| Escalonamento seletivo | O 3.8 Flash olha \~10–15% do tempo (dúvidas e amostra), não 100%; a taxa real sai do piloto |
| SHA-256 do arquivo | Vídeo repetido custa zero |
| [Batch](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/batch-inference) para o acervo histórico | 50% de desconto, sem disputar cota com o dia a dia |

Cada chamada ao Gemini leva o id do job como [rótulo de custo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/add-labels-to-api-calls), o que dá o custo real por vídeo no faturamento. Os créditos promocionais do 3.8 Flash até 31/12/2026 reduzem o escalonamento à metade, mas não entram no orçamento. A saída de \~60 mil tokens por hora é a maior incerteza e será medida no piloto.

### Armazenamento e acervo de 25 anos

Guardar tudo indefinidamente custa pouco no dia a dia; o acervo de 25 anos é que precisa de teto mensal. O original MP4 fica no storage da RedeTV, e o GCP guarda só o que a aplicação usa.

| O que fica guardado | Tamanho estimado | Custo |
| --- | --- | --- |
| Cópia 480p para o player | \~0,45 GB por hora de vídeo; \~3,3 TB por ano no ritmo de 20 h/dia | O Autoclass desce o que fica sem acesso para classes mais frias; o Archive (\~US$ 0,0012 por GB/mês) só vale se configurado como classe final e após 365 dias sem acesso, e uma leitura volta o objeto ao Standard ([preços](https://cloud.google.com/storage/pricing)); \~US$ 25/mês ao fim do 1º ano |
| Quadros-chave, JSON e transcrição | \~20 MB por hora | Desprezível |
| Índice de busca | \~50 GB por ano de vídeo | Agent Retrieval cobrado por uso (armazenamento, leituras, gravações) ([visão geral](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search-2/overview)); \~US$ 15/mês ao fim do 1º ano e \~US$ 45 no 3º |
| Proxy de escalonamento 720p e proxy de análise | — | Apagados por regra de ciclo de vida 30 dias após o processamento |

O acervo vai para o Batch, com o 3.5 Flash-Lite e sem escalonamento, a \~US$ 0,28 por hora de vídeo (modelo, Cloud Run e indexação). O Workflows submete cada lote e consulta o andamento de tempos em tempos, sem nenhum contêiner parado esperando. Se cada ano tiver o volume de hoje (\~7.300 h, a confirmar), são \~182 mil horas e \~US$ 51 mil de processamento. O armazenamento é à parte e cresce com o acervo: \~82 TB de proxies (\~US$ 90–100/mês mesmo no Archive) e \~1 TB de índice (\~US$ 300/mês ao preço atual, ou cerca de um terço com vetores de 256 dimensões).

Antes de expandir, um lote-piloto com programas de cada época passa pela mesma comparação visual do piloto da E1, porque programas antigos têm outra imagem, outros formatos e outras pessoas. Se o acervo precisar de escalonamento para ficar no nível do piloto, o custo sobe para \~US$ 0,40/h, ou a qualidade menor fica declarada para esse acervo. O teto mensal cobre só o processamento:

| Teto mensal (processamento) | Horas por mês | Acervo completo em |
| --- | --- | --- |
| US$ 500 | \~1.800 | \~8,5 anos |
| US$ 1.000 | \~3.600 | \~4,2 anos |
| US$ 2.500 | \~8.900 | \~1,7 ano |

Regras da fila: programas mais pedidos pelos editores primeiro, depois os anos mais recentes para trás; um botão "indexar agora" (papel Operador) passa um programa à frente; o agendador para quando o teto do mês é atingido. A entrada de dados no GCP não é cobrada, mas o envio de \~270 TB de originais (estimativa a 1,5 GB/h) depende da banda da RedeTV; para acelerar, o Transfer Appliance leva os dados fisicamente.

## Arquitetura serverless

A arquitetura é toda serverless e gerenciada: nada fica ligado sem vídeo para processar, e cada peça escala sozinha. Não há VM, cluster nem banco para administrar.

&#91;embedded content: arquitetura serverless · 11 componentes gerenciados\]

O caminho de um vídeo: a API registra o job no Firestore; o arquivo chega ao Cloud Storage; o Eventarc dispara o Workflows, que roda preparação, análise por janela e consolidação em sequência; a decupagem vai ao Storage e o cliente é avisado por webhook.

| Serviço | Papel | Por que este |
| --- | --- | --- |
| Cloud Run (serviços) | Front e API | Escalam a zero; o front exige sessão do Identity Platform e a API, chave de API |
| Cloud Run Jobs | Validação com decodificação completa, derivados e consolidação | Trabalho pesado de CPU com ffmpeg em contêiner isolado; até 168 h por tarefa |
| Workflows | Orquestração do job | Passos com espera, tentativas e paralelismo; cobra por passo executado |
| Firestore | Estado dos jobs, chaves de idempotência, índice de hashes | Transações e expiração automática (TTL) |
| Cloud Storage | Originais, janelas temporárias, decupagens | Montado via FUSE nos jobs, sem copiar o original; janelas apagadas por regra de ciclo de vida |
| Eventarc e Pub/Sub | Disparo do job e eventos de webhook | Desacopla API e processamento |
| Agent Platform | Gemini em Standard e Batch, rótulos de custo, avaliação | Resposta em segundos no dia a dia, 50% de desconto no acervo e custo por vídeo |
| Identity Platform | Login de usuários, contas locais, MFA | Gerenciado; gratuito até 49.999 usuários ativos por mês |
| BigQuery | Eventos de uso, painel da diretoria, relatórios | Consulta barata sobre todo o histórico |
| Cloud Run (serviço de análise) | Uma chamada ao Gemini por janela de análise, inclusive o escalonamento | Até 80 chamadas por instância: a espera da resposta é dividida e custa centavos |

O Agent Engine do Agent Platform, feito para agentes conversacionais, não é necessário para a decupagem, que é um pipeline determinístico. Ele entra numa segunda fase, num assistente de busca no acervo que usa o modo agêntico de vídeo.

## API e segurança

A API é REST assíncrona: o cliente registra o vídeo, recebe um id de job e busca o JSON completo quando terminar, ou recebe um webhook. Nenhuma chamada fica presa esperando o processamento, que leva minutos.

| Método e rota | O que faz | Respostas |
| --- | --- | --- |
| `POST /v1/jobs` | Registra o vídeo (SHA-256, nome, tamanho) e devolve a URL de upload | 202 job novo, aguardando upload (mesmo se o arquivo já foi processado) · 200 mesma chave de idempotência · 409 mesma chave com corpo diferente · 429 com `Retry-After` |
| `PUT` na URL assinada | Envio do MP4 para o bucket de quarentena; a URL só aceita video/mp4 no tamanho declarado. PUT simples para os sistemas legados, upload retomável no front | 200 |
| `GET /v1/jobs` | Lista dos jobs visíveis para quem chama, com status (Biblioteca) | 200 |
| `GET /v1/jobs/{id}` | Status, progresso (janelas prontas/total), erros, `ETag` | 200 · 304 sem mudança |
| `GET /v1/jobs/{id}/decupagem` | JSON completo, em streaming com gzip | 200 · 409 ainda processando |
| `GET /v1/jobs/{id}/reproducao` | Link assinado do proxy de reprodução, válido por minutos | 200 · 409 ainda processando |
| `DELETE /v1/jobs/{id}` | Cancela o job | 202 |
| Webhook `POST` no callback (opcional) | Eventos `job.concluido` e `job.falhou`, assinados com HMAC-SHA256 | — |

Controles de segurança:

- **Chave de API por sistema.** Os sistemas da RedeTV não suportam OAuth nem certificado, então cada sistema recebe uma chave de API longa e aleatória (256 bits, com prefixo que identifica o sistema), mostrada uma única vez e enviada no cabeçalho `X-API-Key`, sempre por HTTPS.
- **Chave guardada só como hash.** O Firestore guarda apenas o HMAC da chave, calculado com uma chave MAC do Cloud KMS ([MAC no KMS](https://docs.cloud.google.com/kms/docs/create-validate-mac-signatures)). Um vazamento do banco não revela chaves nem permite testá-las fora do KMS.
- **Escopos e isolamento.** Cada chave tem escopos (criar, ler, cancelar) e só enxerga os jobs do próprio sistema; conhecer o hash de um arquivo não dá acesso à decupagem de outro sistema.
- **Rotação e revogação.** Até duas chaves ativas por sistema, para trocar sem parada; revogar vale na hora.
- **Assinatura opcional.** Se o sistema conseguir calcular HMAC-SHA256, assina cada requisição com data e hash do corpo, o que impede reaproveitar uma requisição capturada.
- **Status em vez de webhook.** Sistemas legados raramente recebem chamadas de fora; o padrão é consultar o status com `ETag`. O webhook assinado fica opcional.
- **Produção só pela rede da RedeTV.** Em `prod`, o Cloud Armor só aceita front, API e chaves de API a partir dos IPs de saída da emissora: uma senha ou chave vazada não funciona de fora. Em `dev` e `staging` não há restrição de IP, para permitir trabalho remoto; ali o acesso exige conta local com MFA.
- **Borda protegida.** O Cloud Run aceita tráfego só do balanceador; HTTPS com certificado gerenciado; Cloud Armor com regras WAF e limite de requisições ([rate limiting](https://docs.cloud.google.com/armor/docs/rate-limiting-overview)). Pessoas e sistemas entram pelo mesmo balanceador: o front exige sessão do Identity Platform e os sistemas usam `/v1` com chave de API.
- **Upload e player direto no Storage.** As URLs assinadas não passam pelo balanceador nem pelo Cloud Armor. Em `prod`, o perímetro VPC Service Controls tem um nível de acesso com os IPs da RedeTV, que libera upload e reprodução só de lá ([VPC-SC e Cloud Storage](https://docs.cloud.google.com/vpc-service-controls/docs/supported-products#cloud-storage)); o caminho é testado de uma máquina real da RedeTV, inclusive o bloqueio de fora. A URL assinada vale 15 min para iniciar o envio, mas a sessão de upload retomável pode durar até uma semana ([upload retomável](https://docs.cloud.google.com/storage/docs/performing-resumable-uploads)); por isso o job expira em 24 h sem upload completo e a sessão é cancelada. O link de reprodução expira em minutos.
- **Dados fechados.** Buckets privados com acesso uniforme; perímetro VPC Service Controls em Storage, Agent Platform, Firestore e BigQuery, para que uma credencial vazada não tire dados do projeto.
- **Menor privilégio.** Uma conta de serviço por componente (API, login, validação, análise, consolidação), cada uma só com o que usa.
- **Entradas hostis.** Só MP4 válido, conferido em quarentena; toda entrada validada; busca protegida contra injeção. Detalhes em Entradas hostis.
- **Auditoria.** Cloud Audit Logs, logs do balanceador, uso de cada chave de API e de cada chave do KMS.

O Apigee gerenciaria chaves e cotas de API, mas só compensa se a API for aberta a muitos parceiros. Para os poucos sistemas da RedeTV, a verificação de chave na própria API basta.

## Usuários, login e permissões

O login de pessoas usa o Identity Platform, o serviço de identidade do Google Cloud, com duas portas: contas locais, que funcionam desde o primeiro dia, e o login RedeTV, que entra quando a API do sistema legado ficar pronta. As permissões ficam na nossa aplicação, por papel, e valem igual para as duas portas.

| Porta | Como funciona | Quando |
| --- | --- | --- |
| Conta local | E-mail e senha no Identity Platform, com política de senha forte, MFA por aplicativo autenticador obrigatório e bloqueio após tentativas erradas. As senhas ficam com o Google, nunca no nosso banco | Desde a E0; é o plano B e o caminho dos testes |
| Administrador de emergência | Conta local criada por um script de instalação, com link para definir a senha enviado ao e-mail do responsável; MFA obrigatório; cada login dispara alerta. São duas, para não haver ponto único de falha | Desde a E0 |
| Login RedeTV | Nossa tela recebe login e senha; um serviço no Cloud Run consulta a API do legado por HTTPS e, se o login for válido, emite um token próprio do Identity Platform. A senha não é guardada nem vai para log | Quando a API do legado existir; liga por configuração, sem mudar o front |

**MFA no login RedeTV.** O login por token próprio do Identity Platform não aceita o MFA nativo por aplicativo ([documentação](https://firebase.google.com/docs/auth/web/totp-mfa)). Para manter simples e seguro: quem entra pelo login RedeTV não tem segundo fator, mas só acessa a produção a partir dos IPs da emissora, com bloqueio por tentativas e sessão de 8 h; o papel Administrador fica restrito a contas locais com MFA. Em `dev` e `staging`, só entram contas locais com MFA.

O que pedir ao dev do legado: uma rota que recebe login e senha e devolve id, nome, e-mail e se a conta está ativa; HTTPS; limite de tentativas; e uma forma de o nosso serviço se identificar. Do nosso lado, a chave para chamar essa API fica no Secret Manager, e as chamadas saem de um IP fixo do GCP (Cloud NAT), que o legado pode liberar. O Identity Platform é gratuito até 49.999 usuários ativos por mês em login por e-mail ([preços](https://cloud.google.com/identity-platform/pricing)).

As permissões são granulares e negadas por padrão: cada rota da API confere a permissão do usuário, e o front só esconde o que ele não pode usar. Papéis são pacotes de permissões; um usuário pode ter vários, e cada papel pode ser limitado a programas específicos.

| Papel | Pode |
| --- | --- |
| Consulta | Buscar, assistir e ver a decupagem |
| Operador | Consulta + enviar vídeos, acompanhar e reprocessar |
| Editor | Consulta + corrigir pessoas, pautas, objetos, comerciais e tempos |
| Curador | Editor + aprovar correções, mesclar pessoas, editar em lote, gerir o catálogo de pessoas e marcas |
| Diretoria | Painel de indicadores, só leitura |
| Administrador | Usuários, papéis, chaves de API, configurações e auditoria; só em conta local com MFA |

Exemplos de permissões: `video.enviar`, `decupagem.editar`, `pessoa.mesclar`, `painel.ver`, `usuario.gerir`. Toda mudança de papel fica no histórico de auditoria.

## Entradas hostis

Toda entrada é tratada como hostil: arquivo, campo de formulário, cabeçalho, consulta de busca e até o texto que aparece dentro do vídeo. Só MP4 válido chega ao processamento, e só depois de passar por uma quarentena que o confere e o regrava.

### Só MP4 válido

Cada camada recusa o que a anterior deixou passar; o front e a API são só a primeira triagem, e quem decide é a quarentena.

| Camada | O que verifica | Se falhar |
| --- | --- | --- |
| 1. Front | Extensão .mp4, tipo video/mp4, tamanho e a assinatura `ftyp` nos primeiros bytes | Aviso imediato ao usuário; é conveniência, não barreira |
| 2. API (registro) | Tipo declarado video/mp4, tamanho máximo, nome | 415 ou 422; nada é criado |
| 3. Upload | URL assinada presa ao tipo video/mp4 e ao tamanho declarado, gravando só no bucket de quarentena | O Cloud Storage recusa o envio |
| 4. Assinatura | Caixa `ftyp` com marca de MP4 permitida (isom, mp41, mp42, avc1); MOV e outros contêineres recusados | Rejeitado com `formato_invalido` |
| 5. Estrutura | Leitura das caixas pelo `ffprobe` em modo restrito: só o leitor de MP4, só arquivo local, sem protocolos de rede, com tempo e memória limitados | Rejeitado com `arquivo_corrompido` |
| 6. Conteúdo | Lista permitida: uma faixa de vídeo H.264 ou H.265 até 1080p, áudio AAC, duração entre 1 s e um máximo configurável, nenhuma faixa de dados ou anexo; decodificação do arquivo inteiro, aproveitada para gerar os derivados | Rejeitado com `codec_nao_suportado` ou `arquivo_corrompido` |
| 7. Regravação | Cópia limpa com só a faixa de vídeo e a de áudio, sem metadados nem caixas extras, sem recodificar | O processamento usa só a cópia limpa; o original sai da quarentena |

A validação roda num Cloud Run Job isolado: sem acesso à internet, sistema de arquivos só de leitura, usuário sem privilégios. Só ele lê a quarentena e só ele grava no bucket de aceitos, o único que dispara o processamento. O ffmpeg tem versão fixada e as imagens passam pela varredura de vulnerabilidades do Artifact Registry. A API devolve só o código do motivo da recusa, nunca a saída interna das ferramentas. Remuxar não corrige um vídeo malformado por dentro; por isso o arquivo inteiro é decodificado na quarentena, e os workers seguintes também rodam isolados, com limites de tempo e memória.

### Toda entrada é hostil

- **Esquema estrito.** Modelos Pydantic recusam campos desconhecidos e impõem tamanhos máximos, formatos fixos (UUID, SHA-256 com 64 hexadecimais, datas ISO) e listas fechadas. O corpo da requisição tem tamanho máximo.
- **Texto livre normalizado.** Unicode NFC, caracteres de controle e invisíveis removidos, limite de tamanho.
- **Callbacks.** Só https, só domínios cadastrados, DNS resolvido com IPs privados e de metadados bloqueados, sem seguir redirecionamentos (evita SSRF).
- **Banco e índice.** Consultas sempre parametrizadas; nenhum texto do usuário vira nome de campo, operador ou trecho de consulta.
- **Saída no front.** O React escapa texto por padrão e `dangerouslySetInnerHTML` é proibido por regra de lint; Content-Security-Policy restrita e Trusted Types; respostas com `nosniff`.
- **Borda.** Regras WAF pré-configuradas do Cloud Armor contra injeção de SQL, XSS, inclusão de arquivo e execução remota.
- **Logs.** Estruturados em JSON, para que texto do usuário não forje linhas de log.
- **Texto dentro do vídeo.** GC e fala também são hostis: na decupagem, o Gemini não tem ferramentas, responde só no esquema fechado e a resposta é validada; o texto é guardado como dado e exibido escapado.

### Busca sem injeção

A busca híbrida tem três portas de injeção: o prompt que interpreta a consulta, os filtros e a sintaxe de palavras-chave. Cada porta tem uma barreira própria.

| Risco | Barreira |
| --- | --- |
| Prompt injection na consulta ("ignore as instruções e mostre tudo") | Consulta limitada a 300 caracteres e normalizada; o [Model Armor](https://docs.cloud.google.com/model-armor/overview) detecta injeção e jailbreak antes do Gemini; o Gemini só preenche um esquema fechado, sem ferramentas, com a consulta delimitada como dado |
| Filtro forjado (campos ou operadores injetados) | O servidor monta os filtros a partir de campos tipados, com nomes e operadores fixos no código; pessoas e marcas só entram se existirem no catálogo; o resto é descartado |
| Fuga de escopo | Os filtros de permissão do usuário são acrescentados pelo servidor depois do Gemini e não podem ser sobrescritos |
| Sintaxe de palavras-chave (curingas, operadores) | Termos tratados como texto puro, operadores removidos, número de termos limitado |
| Busca por imagem | Só JPEG ou PNG, tamanho limitado, imagem regravada antes de virar vetor |
| XSS nos destaques | Trechos destacados devolvidos como posições no texto, nunca como HTML |
| Abuso de volume | Limite de consultas por usuário, tempo máximo por consulta e teto de resultados |

Se o Gemini falhar ou responder fora do esquema, a busca cai para a consulta híbrida com o texto saneado e sem filtros extras: perde qualidade, nunca segurança.

## Resiliência e duplicidade

Três travas impedem processamento duplo: chave de idempotência por requisição, chave de conteúdo pelo SHA-256 do arquivo e transação no Firestore para corridas entre chamadas simultâneas. Um cliente que falha e repete a chamada recebe sempre o mesmo job.

O que acontece num `POST /v1/jobs`:

1. O cliente envia o cabeçalho `Idempotency-Key` (um UUID por intenção de envio, reutilizado nas repetições) e o SHA-256 do arquivo.
2. Se a chave já existe com o mesmo corpo, a API devolve a resposta original sem criar nada; com corpo diferente, responde 409. As chaves expiram em 48 h por política de TTL do Firestore.
3. O hash declarado não dá acesso a nada: a API cria o job do cliente aguardando upload, mesmo que aquele SHA-256 já seja conhecido.
4. Depois do upload, a validação recalcula o SHA-256 lendo o arquivo. Se divergir do declarado, o job falha com `hash_divergente`, sem gastar modelo.
5. Com o hash conferido, a chave de conteúdo = SHA-256 + versão do pipeline + opções que mudam a decupagem (como a versão do esquema de saída). Numa transação, a API procura `videos/{chave}`: se já foi processado ou está em processamento, o job do cliente é ligado a esse processamento, sem chamar o modelo de novo; se não, o processamento começa. Dois sistemas que enviam o mesmo arquivo pagam um processamento só, e cada um continua vendo apenas os próprios jobs.
6. Reprocessar de propósito exige `forcar_reprocessamento: true` ou uma nova versão do pipeline.

Controle de carga em cada camada:

| Camada | Mecanismo |
| --- | --- |
| Cliente | Backoff exponencial com jitter total: espera aleatória entre 0 e min(teto, base × 2^tentativa); respeita `Retry-After`; número máximo de tentativas. Prefere webhook; se consultar status, a cada ≥30 s com jitter e `If-None-Match` |
| Borda | Cloud Armor limita requisições por cliente e responde 429 antes de chegar ao Cloud Run |
| API | Cloud Run com teto de instâncias; cada chamada só lê e grava no Firestore e volta em milissegundos; fila acima do limite → 429 com `Retry-After` |
| Orquestração | Execuções do Workflows acima da cota ficam em espera e rodam quando há vaga ([notas do Workflows](https://cloud.google.com/workflows/docs/release-notes)) |
| Processamento | Paralelismo máximo de janelas por job e de jobs simultâneos; 429 ou 5xx do Gemini → nova tentativa com backoff e jitter dentro da tarefa; janela concluída nunca é refeita; janela que falha tem tentativas próprias, até um limite |
| Falha definitiva | Esgotadas as tentativas, o job fica `falhou` com a janela e o erro; nunca uma decupagem parcial apresentada como completa |
| Webhook | Reentrega com backoff e jitter; cada evento tem id único para o cliente deduplicar |

## Vídeos longos e JSON completo

A duração do vídeo não tem limite prático: o vídeo vira janelas de análise de 5 min (+10 s de contexto em cada borda) processadas em paralelo, e um vídeo de 3 h são só 36 janelas. O limite de \~45 min por chamada do Gemini ([ficha do modelo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash)) nunca é atingido.

1. **Validação e derivados.** Na quarentena, um Cloud Run Job decodifica o arquivo inteiro uma vez. Essa passada valida o vídeo, calcula o SHA-256, detecta os cortes de plano e gera três derivados: o proxy de escalonamento 720p, o proxy de análise 480p com timecode queimado (para a passada de volume) e o proxy de reprodução 480p sem timecode (para o player).
2. **Plano de janelas.** A duração é dividida em janelas de análise de 300 s com 10 s de contexto. Nenhuma janela é cortada em arquivo: cada chamada aponta para o proxy de análise no Cloud Storage com início e fim (`start_offset` e `end_offset`).
3. **Uma chamada por janela.** O Workflows dispara as janelas em paralelo, com limite, para um serviço do Cloud Run que chama o Gemini em Standard. Cada instância atende até 80 chamadas ao mesmo tempo, então a espera da resposta é dividida entre elas e custa centavos; num Job, cada janela pagaria CPU parada. A resposta é validada contra o esquema e gravada em `janelas/NNN.json`.
4. **Escalonamento.** Trechos com dúvida, e também uma amostra aleatória de janelas, voltam ao mesmo serviço com o 3.8 Flash, o proxy de escalonamento 720p, resolução alta e até 2 quadros por segundo. A amostra mede o que a primeira passada deixou de ver, inclusive o que ela nem marcou como dúvida.
5. **Estado por janela.** Janela concluída fica gravada e nunca é refeita; janela que falha tem novas tentativas próprias, até um limite ([limites do Cloud Run](https://cloud.google.com/run/quotas)). Se o serviço cair entre a resposta do Gemini e a gravação, aquela chamada pode ser cobrada duas vezes; essas repetições entram na conta de custo.
6. **Consolidação.** Lê as janelas em ordem, une as duplicatas das bordas, aplica a regra de tempos (ver Conteúdo do JSON), liga pautas entre janelas e roda a passada narrativa (só texto). Grava `decupagem.json.gz` e o hash da decupagem.
7. **Entrega.** `GET /v1/jobs/{id}/decupagem` devolve o documento inteiro em streaming com gzip; o teto de 32 MiB do Cloud Run vale só para respostas sem streaming. O `ETag` é o hash da decupagem.

O JSON tem a mesma estrutura para 10 min ou 4 h: muda só o número de itens. Enquanto processa, `GET /v1/jobs/{id}` mostra janelas prontas/total.

Prazo esperado: em Standard, uma janela de 5 min leva \~60–80 s no Gemini (estimativa da [ADR 0004](adr/0004-gemini-em-standard.md), pelo clipe3); com 8 janelas em paralelo, 1 h de vídeo fica pronta em poucos minutos (a medir no piloto). O Flex, pela metade do preço, responde em 1–15 min por chamada ([otimização do Gemini](https://ai.google.dev/gemini-api/docs/optimization)) e pode voltar no acervo histórico, ao lado do Batch.

## Conteúdo do JSON

O JSON cobre os cinco requisitos e traz a transcrição como bônus; todo tempo está em milissegundos desde o primeiro quadro do arquivo.

| Requisito | O que o JSON traz |
| --- | --- |
| Celebridades e famosos | Três registros separados por pessoa, cada um com tempos e evidência próprios: aparece na imagem (com quadro de evidência; só isso conta como tempo de tela), citada na fala e citada em texto na tela. Uma menção nunca vira aparição; "não identificado" quando não reconhece |
| Contexto e narrativa | Blocos do programa, pautas com título, resumo, pessoas e locais; resumo geral do vídeo |
| Objetos, cenários e B-roll | Por plano: ambiente, objetos, ação, enquadramento, movimento de câmera, externa/estúdio, dia/noite e a flag "plano limpo" (sem GC nem ninguém falando para a câmera) |
| Merchandising e inserções | Marca, tipo (intervalo, merchan com apresentador, patrocínio/vinheta, sobreposição gráfica, marca incidental, menção editorial), início/fim e evidência |
| Timecode | Planos e B-roll usam os cortes exatos. Eventos visuais (aparição, produto em cena) só se ajustam a um corte que esteja a até 1 s. Falas e menções seguem as próprias palavras e nunca se ajustam a cortes. O tempo original do modelo fica guardado, e início e fim são medidos separadamente. Timecode de origem quando o arquivo tiver |
| Transcrição | Falas com início/fim e locutor, geradas na mesma chamada do Gemini |

Estrutura de topo, com valores fictícios:

```json
{
  "versao_esquema": "1.1",
  "video": {"sha256": "…", "duracao_ms": 3600000, "fps": 29.97, "timecode_origem": "00:59:30:00"},
  "programa": {"resumo": "…", "blocos": [{"inicio_ms": 0, "fim_ms": 840000, "titulo": "Abertura"}]},
  "pautas": [{"id": "pau01", "titulo": "…", "inicio_ms": 120000, "fim_ms": 480000, "resumo": "…", "pessoas": ["pes01"]}],
  "pessoas": [{
    "id": "pes01", "nome": "…", "origem": "modelo",
    "na_imagem": [{"inicio_ms": 15000, "fim_ms": 48000, "inicio_modelo_ms": 14700, "evidencia": "rosto+gc", "quadro": "gs://…/pes01_15000.jpg"}],
    "citada_na_fala": [{"inicio_ms": 9200, "fim_ms": 10400}],
    "citada_no_texto": [{"inicio_ms": 15000, "fim_ms": 21000, "texto": "…"}]
  }],
  "planos": [{"id": "pla001", "inicio_ms": 0, "fim_ms": 4200, "ambiente": "estúdio", "plano_limpo": false}],
  "comerciais": [{"marca": "…", "tipo": "merchan_apresentador", "inicio_ms": 1500000, "fim_ms": 1590000, "evidencia": "fala+logo"}],
  "transcricao": [{"inicio_ms": 0, "fim_ms": 3800, "locutor": "apresentador", "texto": "…"}]
}
```

O esquema é versionado junto com o pipeline (`versao_pipeline`), e o Gemini responde com saída estruturada nesse esquema; respostas fora dele são refeitas, nunca entregues.

O JSON entregue pela API já traz as correções humanas aplicadas, e cada item indica se veio do modelo ou de uma revisão. A saída original do modelo continua disponível com `?versao=modelo`.

## Busca

A busca devolve vídeos e, dentro de cada um, os momentos com início, fim, miniatura e o motivo do resultado. Ela combina entendimento da consulta pelo Gemini, busca híbrida com filtros no [Agent Retrieval](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/vector-search-2/try-it) (o antigo Vector Search 2.0), busca por imagem e reordenação pela Ranking API.

&#91;embedded content: busca · indexação por vídeo e consulta em 5 passos\]

Cada vídeo decupado vira momentos indexados; cada consulta vira filtros e termos, passa pela busca híbrida e pela reordenação, e volta agrupada por vídeo.

**O que é indexado.** A unidade é o momento: um plano ou um evento da decupagem (aparição de pessoa, menção a pessoa, comercial, fala, pauta). Cada momento tem campos filtráveis (pessoas que aparecem e pessoas citadas, em campos separados; marcas, programa, data de exibição, tipo, externa/estúdio, dia/noite, plano limpo), texto (descrição, fala do trecho, GC lido) e dois vetores: um de texto, gerado pelo próprio Agent Retrieval, e um multimodal do quadro-chave junto com a descrição, gerado pelo Gemini Embedding 2.

| Recurso | Exemplo de consulta | Como funciona |
| --- | --- | --- |
| Linguagem natural | "apresentadora falando de eleição em externa à noite" | O Flash-Lite separa pessoa, externa, noite e o tema |
| Nome e apelido | Nome completo, nome artístico ou apelido | Catálogo de pessoas, formado pelas correções dos editores, normaliza tudo para um mesmo id |
| Frase exata | "promoção imperdível" entre aspas | Busca por termos na transcrição |
| Conceito visual | "trânsito à noite com pista molhada" | Vetor multimodal dos planos |
| Por imagem | Foto enviada ou "planos parecidos com este" | Vetor da imagem comparado aos planos |
| Filtros e facetas | Programa, data, marca, plano limpo | Filtros do Agent Retrieval e contagens por faceta |
| Resultado explicável | "casou por GC e fala" | As evidências do momento voltam junto |

**Custo.** Indexar sai por cerca de US$ 0,05 por hora de vídeo (estimativa: \~600 quadros-chave e seus textos por hora, em Batch). Vetores do vídeo inteiro custariam \~US$ 1,40/h (vídeo a US$ 6 por milhão de tokens em Batch, a 66 tokens por quadro) e ficam fora. Cada consulta custa uma chamada curta ao Flash-Lite mais a reordenação, frações de centavo.

Correções humanas reindexam o momento, com estado visível (ver Revisão e edição). O mesmo JSON vai para o BigQuery, para relatórios de aparições e menções por pessoa, marca e programa.

**Proteção contra injeção.** A consulta é tratada como hostil: passa pelo Model Armor, o Gemini só preenche um esquema fechado e os filtros são montados pelo servidor, nunca pelo texto do usuário. As barreiras completas estão em Entradas hostis.

## Interface

A interface segue o modelo do Video Indexer: player à esquerda, painel da decupagem à direita, tudo ligado ao tempo do vídeo. A diferença é que cada item mostra a evidência que o sustenta e, para quem tem permissão, pode ser corrigido ali mesmo.

| Tela | O que tem | Quem acessa |
| --- | --- | --- |
| Biblioteca | Lista de vídeos com status de processamento, filtros por programa e data, upload de MP4 | Consulta e Operador |
| Vídeo · Decupagem | Player com painel lateral: pessoas com o quadro de evidência, separando quem aparece de quem é citado, pautas, objetos e cenários com miniaturas, comerciais e marcas, palavras-chave. Cada item tem a barra de ocorrências e os botões "anterior" e "próxima" para pular entre aparições | Consulta |
| Vídeo · Linha do tempo | Transcrição sincronizada com o player, planos com miniatura, faixas por tipo de ocorrência | Consulta |
| Busca | Barra de busca por texto ou imagem; resultados agrupados por vídeo, com os momentos e o motivo | Consulta |
| Revisão e edição | Correção na própria linha do tempo (próxima seção) | Editor e Curador |
| Painel da diretoria | Indicadores por usuário e totais | Diretoria |
| Administração | Usuários, papéis, chaves de API, configurações, auditoria | Administrador |

O player toca uma cópia 480p guardada no GCP, preparada para saltar direto a qualquer momento; o link do vídeo é assinado, expira em minutos e, em produção, só funciona a partir dos IPs da RedeTV. O original fica no storage da RedeTV.

## Revisão e edição

A área de revisão corrige o que o modelo errou e acrescenta o que ele não viu, sem nunca apagar a saída original: cada correção é uma camada por cima, com autor, data e motivo. Só os papéis Editor e Curador entram nela.

| O que se corrige | Como |
| --- | --- |
| Pessoas | Renomear, ligar a uma pessoa do catálogo, mesclar duas pessoas, marcar "não é esta pessoa", trocar entre aparece e é citada, acrescentar uma aparição que faltou |
| Pautas | Editar título, resumo, início e fim; juntar ou dividir pautas |
| Objetos, cenários e B-roll | Corrigir a descrição; marcar ou desmarcar "plano limpo" |
| Comerciais | Corrigir marca, tipo, início e fim; acrescentar inserção que faltou |
| Tempos | Arrastar início e fim na linha do tempo, com o player acompanhando |
| Transcrição | Corrigir trechos |
| Em lote (só Curador) | Renomear uma pessoa em todos os vídeos; mesclar duplicatas do catálogo |

Regras:

- **Correção ancorada.** Cada correção guarda a versão da decupagem em que foi feita, o intervalo de tempo e a identidade do item (pessoa, marca, pauta), e não só o número do item.
- **Reprocessar não apaga nem aplica às cegas.** A nova saída do modelo entra por baixo. Correções inequívocas são reconciliadas sozinhas; as que não casam mais (uma pauta que virou duas, uma aparição que sumiu) ficam guardadas e vão para uma fila de revisão, em vez de cair no item errado.
- **Estado visível.** A correção passa por salva, indexando e na busca. Falha de indexação tem novas tentativas e aparece na tela.
- **Aprovação opcional.** Por tipo de correção, a mudança de um Editor pode exigir aprovação de um Curador.
- **Histórico e desfazer.** Quem, quando, antes e depois, com opção de desfazer.
- **O catálogo de pessoas nasce aqui.** Como a RedeTV não tem base de famosos, cada nome confirmado vira uma entrada do catálogo, com apelidos. O catálogo normaliza nomes em texto: vai para o Gemini como lista de nomes já vistos e para a busca, que passa a reconhecer os apelidos. Não é reconhecimento facial e não aprende rostos.
- **Correção é medida de qualidade.** A taxa de correção por tipo e por programa vai para o painel e alimenta o conjunto de regressão.

## Painel da diretoria

O painel mostra quem usa o sistema e quanto ele entrega, por usuário e no total, com acesso só para os papéis Diretoria e Administrador. Ele fica dentro da própria aplicação, e não no Looker Studio, porque os usuários não têm conta Google e as permissões precisam ser as nossas.

| Indicador | Por usuário | Total |
| --- | --- | --- |
| Acessos | Logins, dias ativos, último acesso | Usuários ativos por dia, semana e mês |
| Vídeos | Enviados e horas enviadas | Processados, horas, falhas, tempo médio de processamento, fila |
| Buscas | Quantidade e termos mais usados | Buscas por dia, termos mais buscados, buscas sem resultado |
| Revisão | Correções feitas e aprovadas | Taxa de correção por tipo e por programa; minutos de revisão por hora de vídeo |
| API | Chamadas por sistema consumidor | Chamadas, erros, arquivos recusados na quarentena |
| Custo | — | Custo por hora de vídeo e por mês |

Filtros por período, programa e usuário, com exportação em CSV.

Como funciona: cada ação (login, envio, fim de processamento, busca, correção, chamada de API) gera um evento no Pub/Sub, gravado no BigQuery. O painel consulta tabelas resumidas, atualizadas a cada poucos minutos. O custo vem dos rótulos por job e da exportação de faturamento para o BigQuery. O volume de eventos é pequeno e cabe na camada gratuita do BigQuery. O próprio acesso ao painel fica registrado na auditoria.

## Qualidade em produção

A qualidade é provada no piloto, por conferência visual do Bruno no player, e vigiada todo dia por sinais automáticos. Os programas do piloto viram o conjunto de regressão: nenhuma troca de modelo ou prompt entra sem que a decupagem nova seja comparada lado a lado com a aprovada no piloto.

- **Sinais automáticos.** Percentual de janelas escaladas para o 3.8 Flash, de pessoas "não identificadas", de respostas fora do esquema e eventos por hora fora da média do programa. Alertas no Cloud Monitoring.
- **Avaliação automática.** O [serviço de avaliação do Agent Platform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-overview) roda métricas por rubrica sobre a amostra de controle, para detectar queda antes que o usuário perceba.
- **Versões fixas.** Modelo e prompt fixados por versão no `versao_pipeline`; uma versão nova permite reprocessar o acervo de propósito.
- **Amostra de controle.** Sinal automático de qualidade: uma fração aleatória de janelas passa também pelo 3.8 Flash; a diferença entre as duas passadas mede, ao longo do tempo, o que a primeira deixa de ver.

### Comparação do piloto

Cada programa do piloto é aberto no player com as decupagens do 3.5 Flash-Lite e do 3.8 Flash lado a lado. O Bruno clica nos itens de cada categoria, confere se o vídeo cai no momento certo e registra, por requisito, o que cada modelo acertou, errou ou deixou de ver. Não há gabarito: a referência é o próprio vídeo.

| Requisito | O que se compara entre os modelos |
| --- | --- |
| Famosos na imagem | Nomes certos, aparições perdidas, falsos reconhecimentos, "não identificado" correto |
| Menções a pessoas | Menções certas e perdidas, separadas das aparições |
| Pautas | Limites e pessoas certos, resumo fiel, continuidade entre janelas |
| B-roll | Pertinência dos 5 primeiros resultados em 20 consultas; classificação de plano limpo |
| Comerciais | Inserções perdidas por tipo; confusão com marca incidental ou menção editorial |
| Timecode | Clique que cai fora do momento e os piores casos |
| Utilidade | Minutos para localizar e corrigir material, comparados ao processo atual |

## Stack e linguagens

React com TypeScript no front e Python no back, com as bibliotecas e os serviços abaixo.

| Camada | Escolha | Por quê |
| --- | --- | --- |
| Back (API e jobs) | Python 3.12, FastAPI, Pydantic, uv | Uma linguagem só no back. O mesmo modelo Pydantic gera o esquema de saída do Gemini, a validação e o OpenAPI |
| Front | React, TypeScript, Vite, TanStack Query | Tipos do cliente HTTP gerados do OpenAPI: o contrato tem uma fonte só, e uma mudança na API quebra o build do front, não a produção |
| Hospedagem do front | Cloud Run servindo o build estático (NGINX), atrás do mesmo balanceador | Escala a zero, mesmo domínio e mesmo Cloud Armor da API; o pacote do front não contém dados, que só vêm da API com sessão válida |
| Login dos usuários | Identity Platform: contas locais e, quando existir, login pela API do sistema legado | Senhas, MFA e sessões gerenciados pelo Google; nenhuma senha no nosso banco |
| Testes | pytest e Hypothesis no back; Vitest, Testing Library, MSW e Playwright no front | Hypothesis gera casos para a matemática de tempo e janelas; MSW simula a API a partir do OpenAPI |
| Infraestrutura | Terraform para todo recurso GCP | Ambientes idênticos e efêmeros; nada criado à mão no console |
| Repositório | Monorepo: `api/`, `workers/`, `shared/` (esquemas), `web/`, `infra/`, `workflows/`, `evals/` | Uma mudança vertical (front + API + job) cabe num único PR |

## Ciclo de desenvolvimento e bancada de testes

Quase tudo é testado sem o GCP; só a integração final precisa da nuvem. O caminho é isolar cada serviço do Google atrás de uma interface (portas e adaptadores): a lógica de domínio roda em milissegundos sem rede, e cada adaptador tem um dublê local ou um ambiente efêmero na nuvem.

| Nível | O que testa | Onde roda | Quando |
| --- | --- | --- | --- |
| 1. Unitário (TDD) | Domínio puro: plano de janelas, matemática de tempo e ajuste aos cortes, chave de conteúdo e idempotência, junção de janelas, backoff com jitter, validação do esquema, leitura da resposta do Gemini | Notebook e CI, sem rede | A cada commit, em segundos |
| 2. Integração local | Adaptadores contra emuladores do Firestore e do Pub/Sub (oficiais do gcloud), Storage (fake-gcs-server), ffmpeg real em clipes de 30 s, YAML do Workflows ([workflows-emulator](https://pypi.org/project/workflows-emulator/), comunitário) | Docker Compose no notebook e no CI | A cada PR |
| 3. Contrato com o Gemini | Respostas gravadas (cassetes) nos testes rápidos; chamada real em 5 clipes-ouro de 1–2 min, com versão do modelo fixada. Verifica esquema e invariantes, nunca texto exato | CI, projeto de dev | Cassetes a cada PR; chamada real a cada mudança de prompt ou modelo e toda noite |
| 4. Ponta a ponta efêmero | Fluxo inteiro, do front ao JSON, com IAM, Eventarc e Workflows reais | Ambiente do PR no projeto de dev: revisões do Cloud Run com tag e sem tráfego ([revision tags](https://codelabs.developers.google.com/codelabs/cloud-run/revisions-cloud-run-traffic-splitting-gradual-rollout-rollbacks)), workflow e prefixos de bucket e coleção com o número do PR | A cada PR que muda back ou infra; destruído ao fechar o PR |
| 5. Avaliação de qualidade | Conjunto de regressão (programas do piloto): decupagem nova comparada lado a lado com a aprovada, mais a diferença da amostra de controle | Projeto de dev, em Batch (50% mais barato) | Antes de cada release e a cada troca de prompt ou modelo |
| 6. Segurança | MP4 malformados e disfarçados (fuzzing do validador), cargas de injeção OWASP e de prompt injection contra API, busca e front | CI e ambiente do PR | A cada PR; o corpus de ataques cresce a cada falha encontrada |

O ciclo TDD (vermelho, verde, refatorar) vale integralmente para o domínio e os adaptadores. Para as partes que dependem do Gemini, o teste escrito primeiro é um invariante ou uma métrica: "todo evento cai dentro da duração", "o clipe-ouro 3 tem a apresentadora entre 00:42 e 01:10". O prompt muda até o teste passar.

**Três projetos GCP.** `dev` (ambientes efêmeros e testes), `staging` (homologação com vídeos reais) e `prod`. A mesma imagem de contêiner, identificada pelo digest, é promovida de um para o outro; nada é recompilado no caminho.

**Pipeline de CI/CD** (GitHub Free, Cloud Build e Cloud Deploy):

1. Lint, tipos e testes unitários, sem GCP.
2. Build das imagens no Artifact Registry e testes de integração com emuladores.
3. Terraform cria o ambiente efêmero do PR e roda os testes ponta a ponta e os de contrato.
4. Merge na `main` publica em `staging`; aprovação no Cloud Deploy leva a `prod` com tráfego gradual entre revisões. Até a E10, o merge na `main` publica no `dev`: o Cloud Build constrói as imagens, e o Terraform as publica pelo digest (#71).

**Limites do GitHub Free.** Em repositório privado, o plano Free dá 2.000 minutos de Actions por mês e não tem ambientes com aprovação nem proteção de branch aplicada ([GitHub](https://docs.github.com/actions/reference/environments)). Por isso o Actions roda só lint e testes unitários; build de imagens, integração e ponta a ponta rodam no Cloud Build, disparado pelo GitHub, com 2.500 minutos grátis por mês ([preços](https://cloud.google.com/build/pricing)); a aprovação para produção fica no Cloud Deploy. O próprio pipeline garante que nada sem testes verdes chega a `staging` ou `prod`.

**No notebook do desenvolvedor.** Testes unitários e `docker compose up` para os emuladores cobrem o dia a dia. Para tocar o GCP real, o desenvolvedor sobe o seu próprio ambiente efêmero com o mesmo comando do PR (`make preview`). Custos de dev controlados por alerta de orçamento, clipes curtos nas chamadas reais e expiração automática dos recursos efêmeros.

## Chaves e segredos

Nenhuma chave fica no `.env`, no código ou no repositório. As chaves da aplicação ficam no Cloud KMS, onde são usadas sem nunca serem lidas; as chaves de API dos sistemas existem só como hash; o Secret Manager guarda apenas o que terceiros nos entregam. O `.env`, se existir, tem só configuração não sensível, como id do projeto e região.

| Chave ou segredo | Onde fica | Como é usado |
| --- | --- | --- |
| Chave do hash das chaves de API (HMAC-SHA256) | Cloud KMS, chave MAC | A API calcula no KMS o HMAC da chave recebida e compara com o hash guardado; a chave do KMS nunca sai de lá |
| Chaves de API dos sistemas | Em lugar nenhum; só o hash, no Firestore | Mostradas uma vez na criação; perdeu, gera outra |
| Senhas dos usuários locais | Identity Platform | O Google guarda e confere; nunca passam pelo nosso banco |
| Chave para chamar a API de login do legado | Secret Manager, com chave CMEK | Lida em execução só pela conta de serviço do login |
| Segredo do webhook (HMAC, opcional) | Secret Manager, com chave CMEK | Lido em execução só pela conta de serviço que entrega webhooks |
| Chave do SerpAPI | Secret Manager, com chave CMEK | Lida em execução só pela conta de serviço do Job que busca as fotos de referência |
| Acesso do back ao Google (Gemini, Storage, Firestore, KMS) | Nenhuma chave: conta de serviço anexada ao Cloud Run | Tokens curtos emitidos pelo próprio Cloud Run |
| CI/CD e desenvolvedores → GCP | Nenhuma chave: Workload Identity Federation e impersonação | Token curto por execução ([auth action](https://github.com/google-github-actions/auth)) |

**Usuários do front.** Entram pelo Identity Platform, com conta local ou com o login RedeTV (ver Usuários, login e permissões); as senhas locais ficam com o Google.

**Rotação.** Um job agendado cria uma versão nova da chave MAC a cada 90 dias (o KMS só gira sozinho chaves de criptografia simétrica); cada hash guarda a versão usada e é refeito no próximo uso da chave de API. Chaves de API, a chave do legado e o segredo do webhook trocam sem parada, com duas versões ativas durante a troca. Se a política da RedeTV exigir, as chaves do KMS ficam em HSM.

Travas para que isso continue verdade:

- Política de organização `iam.disableServiceAccountKeyCreation` ativa, impedindo chaves JSON de conta de serviço ([blog do Google](https://cloud.google.com/blog/products/identity-security/enabling-keyless-authentication-from-github-actions)).
- Varredura de segredos com gitleaks no pre-commit e no CI (a proteção de push do GitHub não existe em repositório privado no plano Free).
- Permissão de assinar em cada chave do KMS só para a conta de serviço que precisa dela.
- Estado do Terraform num bucket com acesso restrito ao pipeline.

## Entregas verticais

Cada entrega atravessa todas as camadas (front, API, processamento, dados e testes) e termina com algo que um usuário da RedeTV consegue usar e julgar. A ordem ataca primeiro a maior incerteza, a qualidade da decupagem, e entrega a busca cedo, porque é ela que o usuário enxerga.

| Entrega | O que dá para testar ao final | O que atravessa | Aceite |
| --- | --- | --- | --- |
| **E0 · POC** | Entrar com uma conta local, enviar um vídeo de até 10 min e ver a decupagem no player com o painel da decupagem | Identity Platform com conta local e MFA; front com upload, player e painel; API mínima; validação de MP4 em quarentena; uma chamada ao 3.5 Flash-Lite em Standard; JSON no Storage. Fundação: monorepo, Terraform do `dev`, CI | 5 clipes reais decupados; o clique cai no momento certo; nenhum segredo no repositório |
| **E1 · Piloto de qualidade** | Cinco programas completos decupados com os cinco requisitos, no player e em JSON exportável | Janelas de análise em paralelo, consolidação, regra de tempos, aparição separada de menção, escalonamento com amostra de controle, A/B com o 3.8 Flash, comparação visual lado a lado, medição de custo e de tempo de revisão | Comparação visual dos dois modelos registrada por requisito; custo real por hora medido; decisão de modelo registrada |
| **E2 · Busca** | Buscar por assunto, frase dita ou nome e saltar para os momentos | Índice no Agent Retrieval, entendimento da consulta, proteção contra injeção, página de resultados | Em 20 consultas editoriais, ≥80% dos 5 primeiros resultados pertinentes |
| **E3 · Revisão e edição** | Corrigir pessoas, pautas, objetos, comerciais e tempos e ver a correção chegar à busca | Área de revisão, papéis Editor e Curador, correções ancoradas e reconciliadas, estado de indexação, histórico, catálogo de pessoas | Um editor corrige um programa inteiro; reprocessar o programa mantém as correções certas e manda o resto para a fila |
| **E4 · Famosos com evidência** | Ver o painel de pessoas com o quadro que justifica cada nome, separando aparições de menções, e filtrar por pessoa | Evidências, uso do catálogo, relatório de tempo de tela | Relatório de tempo de tela de um programa conferido, contando só aparições |
| **E5 · Comerciais e merchandising** | Filtrar e tirar relatório por marca e por tipo de inserção | Taxonomia comercial e relatório | Um dia de programação conferido por um revisor |
| **E6 · B-roll e busca visual** | Buscar "plano limpo de trânsito à noite" ou enviar uma foto e achar planos parecidos | Flag de plano limpo, vetores multimodais, busca por imagem | Consultas visuais aprovadas pelos editores |
| **E7 · API para sistemas legados** | O sistema da RedeTV envia vídeos e consulta a decupagem | Chave de API, idempotência, deduplicação autorizada, consulta de status | Teste de caos sem job duplicado; dois sistemas com o mesmo arquivo não veem os jobs um do outro |
| **E8 · Login RedeTV e permissões completas** | Usuários entram com o login da RedeTV; o administrador gere papéis e escopos por programa | Adaptador para a API do legado, todos os papéis, auditoria; Administrador só em conta local com MFA | Login pelo legado em `staging`; a conta local continua funcionando. Entra quando a API do legado existir |
| **E9 · Painel da diretoria** | A diretoria acompanha acessos, vídeos e buscas por usuário e no total | Eventos no BigQuery, telas do painel, papel Diretoria | Os números de uma semana batem com os registros |
| **E10 · Produção** | Operação diária de 20 h com alertas, acessível só pela rede da RedeTV | Balanceador, Cloud Armor com os IPs da emissora, VPC-SC com nível de acesso para upload e player, observabilidade, teste de carga | Upload e player funcionam de uma máquina da RedeTV e são bloqueados de fora; uma semana em paralelo ao processo atual sem incidente bloqueante |
| **E11 · Acervo histórico** | Programas antigos aparecendo na busca | Lote-piloto por época com a comparação visual da E1; depois Batch com fila por prioridade e teto mensal | Lote-piloto aprovado na comparação visual e dentro do teto |

A segurança de base (IAM, buckets privados, nenhum segredo) vale desde a E0; o VPC-SC entra em modo de teste a partir da E4 e é aplicado na E10. Cada entrega vira um conjunto de tickets verticais pequenos no `/to-tickets`.

### Recorte da E0 (grill de 29/10/2026)

A E0 prova o caminho de ponta a ponta: vídeo enviado, quarentena, Gemini, decupagem, player. Da qualidade, só os tempos são conferidos, visualmente no player; o resto é comparado na E1.

| Tema | Decisão na E0 |
| --- | --- |
| Projeto GCP | Projeto `dev` novo na organização da RedeTV, com billing da RedeTV e alerta de orçamento; `staging` e `prod` ficam fora |
| Região | Tudo em `southamerica-east1`; o Gemini usa o endpoint global, coberto pela autorização escrita dos clipes. Ver [ADR 0001](adr/0001-gemini-endpoint-global.md) |
| Hospedagem | Um único serviço Cloud Run: o FastAPI serve a API e o build do React. Sem balanceador nem Cloud Armor; o front ganha serviço próprio quando o balanceador entrar (E10) |
| Orquestração | Esqueleto real com o mínimo de passos: Eventarc → Workflows → Job de validação → serviço de análise → decupagem no Storage |
| Login | Só contas locais no Identity Platform, com MFA TOTP obrigatório, criadas por script, inclusive os 2 administradores de emergência com alerta a cada login. Sem papéis: toda conta autenticada envia e vê todos os vídeos |
| Contas iniciais | Administradores: Bruno e uma pessoa da TI da RedeTV. Usuários: Bruno |
| Clipes | 5 clipes reais de programas variados, com 1 a 10 min; são também os clipes-ouro do teste de contrato. Ficam só num bucket do `dev`, nunca no git, e o envio ao Gemini é autorizado por escrito |
| Upload | O front confere extensão, tipo, tamanho e `ftyp`; `POST /v1/jobs` devolve URL assinada de upload retomável para a quarentena. Sem SHA-256 no navegador, sem `Idempotency-Key` e sem deduplicação (E7) |
| Quarentena | As 7 camadas de Entradas hostis; duração entre 1 s e 10 min, e fora disso `duracao_excedida` |
| Derivados | Só o proxy de reprodução (480p H.264 com faststart), que serve ao player e ao Gemini: o modelo vê o mesmo arquivo e o mesmo tempo que o clique usa, e a documentação da Vertex não garante H.265. O proxy de análise com timecode queimado fica para o A/B da E1, se os tempos ficarem ruins |
| Análise | Uma chamada ao 3.5 Flash-Lite, em Standard ([ADR 0004](adr/0004-gemini-em-standard.md)): o Flex deixou o clipe2 quase 7 min esperando. Ela pede o esquema inteiro (1.2), com tempos crus do modelo em MM:SS (ADR 0003): sem detecção de cortes, sem regra de tempos e com `quadro` vazio |
| Falhas | 429 ou 5xx do Gemini: até 5 tentativas com backoff e jitter. Resposta fora do esquema: refeita até 2 vezes. Esgotadas as tentativas, `falhou` com `analise_falhou`, nunca uma decupagem parcial. Rótulo de custo com o id do job |
| Estados do job | `aguardando_upload` → `validando` → `analisando` → `concluido` ou `falhou`, com código (`formato_invalido`, `arquivo_corrompido`, `codec_nao_suportado`, `duracao_excedida`, `upload_expirado`, `analise_falhou`). Sem upload completo em 24 h, vai a `falhou` com `upload_expirado` |
| API | `POST /v1/jobs`, `GET /v1/jobs`, `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/decupagem` e `GET /v1/jobs/{id}/reproducao`, todas com o token do Identity Platform. Sem `DELETE`, webhook, `ETag` nem chave de API |
| Telas | Login com cadastro do MFA; Biblioteca com lista, status por consulta periódica e upload; Vídeo com player e painel da decupagem por categoria, em que o clique num item salta o player |
| CI e testes | GitHub Actions com lint, tipos, testes unitários e gitleaks; contrato com o Gemini por cassetes e chamada real sob demanda nos 5 clipes-ouro; Terraform num único `dev`. Ambientes efêmeros por PR, Cloud Deploy e emuladores ficam para a E1 |
| Aceite | Os 5 clipes decupados; um teste Playwright prova que clicar em cada item leva o player ao `inicio_ms`; o Bruno abre a decupagem de cada clipe-ouro no player, clica nos itens e confirma que o vídeo cai no momento certo; nenhum segredo no repositório. Sem gabarito nem documentalista: a validação de qualidade é visual |

## Decisões e perguntas em aberto

Esta seção é a entrada do grill: decisões já tomadas, para serem desafiadas, e perguntas que precisam de resposta antes do spec. Recomendo `/grill-with-docs` dentro do repositório, e não `/grill-me`: o grill-me é a mesma entrevista sem repositório e sem arquivos, enquanto o grill-with-docs grava o glossário e as ADRs ([AI Hero](https://www.aihero.dev/skills-grill-with-docs)). A cadeia segue com `/to-spec` → `/to-tickets` → `/implement` (teste primeiro) → `/code-review`. Como o projeto é grande demais para uma sessão, o `/wayfinder` pode mapear as decisões antes.

**Decisões tomadas**

| Decisão | Alternativa descartada | Motivo |
| --- | --- | --- |
| Gemini 3.5 Flash-Lite no volume, 3.8 Flash só nas dúvidas | Tudo no 3.8 Flash ou no Argon | Cerca de 1/4 do custo; confirmado no piloto A/B |
| Gemini em Standard ([ADR 0004](adr/0004-gemini-em-standard.md)) | Flex, pela metade do preço | A espera do Flex deixou o clipe2 quase 7 min parado; o Flex não transcreve melhor |
| Serverless: Cloud Run, Workflows, Firestore | GKE ou VMs | Sem custo ocioso e sem cluster para operar |
| Python único no back, TypeScript no front | Duas linguagens no back | SDK oficial e esquemas compartilhados |
| API assíncrona com webhook | API síncrona | Vídeos de horas |
| Agent Retrieval para a busca | BigQuery vector search, Elasticsearch | Busca híbrida, filtros e reordenação gerenciados |
| Janelas de análise de 5 min em paralelo | Vídeo inteiro ou janelas de 15 min | Limite do modelo, cobertura e falhas contidas |
| Nenhum segredo em arquivo | `.env` com chaves | Chaves no Cloud KMS; chaves de API só como hash; senhas no Identity Platform |
| Entregas verticais, POC primeiro | Camadas horizontais | Cada entrega é testável por um usuário |
| Tudo no GCP; front no Cloud Run | Servidores próprios | A RedeTV não tem servidores para hospedar a aplicação |
| Quarentena com validação e regravação do MP4 | Confiar na extensão ou no tipo declarado | Arquivo disfarçado ou malformado nunca chega ao ffmpeg do processamento |
| Identity Platform com conta local e adaptador para a API do legado | Esperar a API do legado; senhas no nosso banco | Testar já, sem guardar senhas |
| Chave de API aceita só dos IPs da RedeTV | OAuth ou certificado de cliente | Os sistemas legados não suportam |
| Painel dentro da aplicação, sobre o BigQuery | Looker Studio | Usuários sem conta Google; permissões da própria aplicação |
| Catálogo de pessoas formado pelas correções | Base de famosos prévia | Não existe base e não será criada tão cedo |
| Acervo em Batch com teto mensal | Processar tudo de uma vez | Custo previsível e prioridade pelo uso |
| Ajuste a cortes só para planos e eventos visuais a até 1 s | Ajustar tudo ao corte mais próximo | Falas e menções não começam em cortes |
| Aparição separada de menção | Uma lista só de aparições | Ouvir um nome não prova que a pessoa está na imagem |
| Reaproveitamento só depois do upload com hash conferido | Devolver a decupagem pelo hash declarado | Um sistema não lê a decupagem de outro |
| Chamada ao Gemini num serviço com concorrência | Uma tarefa de Job por janela | O Job pagaria CPU parada esperando o Gemini |
| Amostra de controle no 3.8 Flash | Escalonar só por dúvida | Mede o que o modelo nem percebeu |
| Piloto completo na E1, com comparação visual lado a lado | A/B depois da busca e da edição | Prova o valor da IA antes de investir no produto |
| Produção só pelos IPs da RedeTV; dev e staging abertos, com MFA | Restringir também o desenvolvimento | Permite trabalho remoto sem abrir a produção |
| Login RedeTV sem MFA, compensado pelo IP; Administrador só em conta local com MFA | Criar um segundo fator próprio para o login legado | Simples e seguro; o token próprio não aceita o MFA nativo |

**Perguntas em aberto**

- [x] Git: GitHub Free, com repositório privado.
- [x] Front: aplicação própria, no estilo do Video Indexer.
- [x] Consumidores da API: sistemas legados da RedeTV, sem OAuth nem certificado.
- [x] Origem dos vídeos: storage local da RedeTV, enviados por um sistema interno pela API ou por usuários no front.
- [x] Grade: não será usada; os programas da igreja não são gravados.
- [x] Base de famosos: não existe; o catálogo nasce das correções.
- [x] Retenção: resultados guardados indefinidamente.
- [x] Acervo: 25 anos, processado aos poucos, com teto mensal.
- [x] Preço do Agent Retrieval: cobrança por uso, estimada em Custo.
- [ ] Contrato da API de login do legado: rota, campos e como o nosso serviço se identifica.
- [ ] IPs de saída da RedeTV, para liberar no Cloud Armor; e se o legado aceita chamadas do IP fixo do GCP.
- [ ] Quem recebe cada papel no início (administradores, editores, diretoria).
- [ ] O sistema legado consegue receber webhook, ou só consulta status?
- [x] Prazo aceitável entre o fim da gravação e a decupagem pronta; decide Flex ou Standard. Standard, pela [ADR 0004](adr/0004-gemini-em-standard.md).
- [ ] Banda de internet disponível para enviar os vídeos, no dia a dia e no acervo.
- [ ] Teto mensal para o acervo e ordem de prioridade dos programas.
- [ ] Quantas horas tem, de fato, cada ano do acervo.

**Glossário**: os termos do projeto ficam no [`GLOSSARY.md`](../GLOSSARY.md), na raiz.
