# MAM RedeTV

PoC de decupagem automática com IA. O plano está em `docs/Plano_MAM.md`.

- `api/`: back em Python 3.12 com FastAPI.
- `web/`: front em React, TypeScript e Vite.

## Desenvolvimento

Instale [uv](https://docs.astral.sh/uv/), Node 22 e o [gitleaks](https://github.com/gitleaks/gitleaks):

```sh
brew install uv node@22 gitleaks
```

Depois, na raiz do repositório:

```sh
make instalar   # dependências e o hook de pre-commit com o gitleaks
make verificar  # lint, tipos, testes unitários e build; nenhuma chamada à nuvem
```

O hook de pre-commit recusa o commit se o gitleaks achar um segredo nos arquivos preparados ou se o gitleaks não estiver instalado. O CI roda as duas metades do `make verificar` (`verificar-api` e `verificar-web`) e o gitleaks em todo PR.

Os testes do validador usam o ffmpeg de verdade. Sem ffmpeg na máquina, o `make verificar` os pula; `make testar-na-imagem` (pede o Docker) os roda dentro da imagem do Job de validação, com o ffmpeg da produção, e é assim que o CI os roda, no job `imagem`, só quando mudam os arquivos que ele usa (o `Dockerfile`, os módulos de `api/` e os testes do validador; pulado, o job termina verde). O CI roda o backend (`make verificar-api`, pytest em vários processos com `pytest-xdist`), o front (`make verificar-web`) e a imagem em jobs paralelos, e o `publicar` espera todos. O contêiner do loop AFK fixa a mesma versão, no `ARG FFMPEG` do `scripts/afk/Dockerfile`, então o `make verificar` de lá também os roda com ela. O próprio `make verificar` falha se as duas versões forem diferentes (`scripts/checar-ffmpeg.sh`).

## API para os sistemas da RedeTV

O guia para quem integra um sistema (chave de teste, envio do vídeo, Job, webhook, decupagem, idempotência e erros) está em `docs/api/guia.md`, com exemplos em `docs/api/exemplos/` e o OpenAPI em `docs/api/openapi.json`. Depois de mudar uma rota dos sistemas ou a sua documentação (`api/documentacao_dos_sistemas.py`), rode `make atualizar-openapi`; o `make verificar` falha se o arquivo não bater com o gerado.

## Deploy no dev

A E0 roda num serviço Cloud Run único, `mam-web`, em que o FastAPI serve a API e o build do React. O Terraform em `infra/` (o dev chama o módulo `infra/modulos/mam`, #292; o `make deploy-dev` recusa um plano que destrua ou recrie algo, salvo `PERMITIR_DESTRUICAO=sim`) cria tudo: Artifact Registry, Firestore, os buckets privados (quarentena, aceitos e decupagens), uma conta de serviço por componente, o serviço, o Identity Platform (login com MFA TOTP e política de senha) e o alerta de login dos administradores de emergência. Antes, rode uma vez o `scripts/wizard-gcp-dev.sh`, que cria o projeto, a conta `mam-terraform` e o `.env` e inicializa o Identity Platform com a sua conta de Owner. Esse último passo é único por projeto (vale também para `prod`): ele exige `firebase.projects.update`, que a `mam-terraform` não tem, e depois o Terraform importa a config e cuida do resto. Acrescente também ao `.env` os e-mails das contas, separados por vírgula:

```sh
ADMINS_EMERGENCIA='bruno.admin@exemplo.com,ti@exemplo.com'
USUARIOS='bruno@exemplo.com'
```

Precisa também do [Terraform](https://developer.hashicorp.com/terraform/install); o Docker não, porque as imagens são construídas no Cloud Build:

```sh
brew tap hashicorp/tap && brew install hashicorp/tap/terraform
```

Depois, na raiz do repositório:

```sh
make deploy-dev
```

Ele impersona a `mam-terraform` (ADR 0002), sem chave em arquivo, e:

1. cria o bucket do estado do Terraform, o `BUCKET_ESTADO_TF` que o wizard põe no `.env`, se não existir: privado, com acesso uniforme e versionamento;
2. aplica só o Artifact Registry, o Identity Platform e o que o Cloud Build usa (a conta `mam-build` e o bucket de fontes);
3. sobe o código para o Cloud Build, que constrói as quatro imagens em paralelo, com o cache das camadas no Artifact Registry (`cloudbuild.yaml` e `docker-bake.hcl`) e as envia ao Artifact Registry. O `.gcloudignore` deixa de fora tudo o que o git ignora, inclusive o `.env`;
4. aplica o resto pelos digests que o Cloud Build enviou, sem recompilar, então cada deploy gera uma revisão nova;
5. confere que `/v1/health` responde 200 e mostra a URL.

À mão, cada `terraform apply` mostra o plano e pede confirmação.

### Publicação automática (CD)

Cada merge na `main` publica no `dev` sozinho: depois que os jobs do CI passam naquele commit, o job `publicar` do `.github/workflows/ci.yml` roda o mesmo `make deploy-dev`, com os applies aprovados automaticamente. Um merge com o CI vermelho não publica. O GitHub entra no GCP por federação de identidade de cargas de trabalho, sem chave: o provedor só aceita tokens deste repositório (pelo id) na `main`, e só esse repositório pode impersonar a `mam-terraform`. Os merges publicam um de cada vez, e só a ponta da `main`: se outro merge entrou antes de o CI de um commit terminar, esse commit não publica, e o run do mais novo publica no lugar dele, então o `dev` nunca volta para código mais antigo.

Para acompanhar uma publicação: na aba Actions do GitHub, abra a execução do CI do commit e o job `publicar`. O log mostra o link do build no console do Cloud Build, o plano do Terraform e, no fim, a URL com o `/v1/health` respondendo. A produção, com aprovação no Cloud Deploy, fica para a E10.

Configuração, uma vez, por quem é Owner do `dev`:

1. rode de novo o `scripts/wizard-gcp-dev.sh`, que dá à `mam-terraform` os papéis do CD (`roles/iam.workloadIdentityPoolAdmin` e `roles/cloudbuild.builds.editor`);
2. rode `make deploy-dev`, que cria a federação com o GitHub e a conta `mam-build`;
3. grave as variáveis do repositório que o job lê (no zsh ou no bash, na raiz):

```sh
set -a && . ./.env && set +a
gh variable set GCP_PROJECT_ID --body "$GCP_PROJECT_ID"
gh variable set GCP_REGION --body "$GCP_REGION"
gh variable set BUCKET_ESTADO_TF --body "$BUCKET_ESTADO_TF"
gh variable set GOOGLE_IMPERSONATE_SERVICE_ACCOUNT --body "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT"
gh variable set ADMINS_EMERGENCIA --body "$ADMINS_EMERGENCIA"
gh variable set WORKLOAD_IDENTITY_PROVIDER --body "$(terraform -chdir=infra output -raw provedor_github)"
```

Sem a `WORKLOAD_IDENTITY_PROVIDER`, o job `publicar` não roda.

As contas de `ADMINS_EMERGENCIA` são Administradoras: a API dá o papel `administrador` (todas as permissões) a quem tem um desses e-mails verificados, sem gravar nada no Firestore. Para tirar ou incluir alguém, atualize a variável do repositório com `gh variable set ADMINS_EMERGENCIA --body "a@x.com,b@x.com"` e também o `ADMINS_EMERGENCIA` do `.env`, para os deploys manuais; o próximo merge na `main` publica a mudança. A mesma lista define os destinatários do alerta de login.

Depois do primeiro deploy, `make criar-contas` cria as contas do `.env` e manda a cada pessoa o link para definir a senha; no primeiro login, a pessoa cadastra o aplicativo autenticador. Rodar de novo só reenvia o link. A API recusa todo token sem o segundo fator TOTP, e o Identity Platform bloqueia a conta por um tempo após tentativas erradas.

## Índice da busca (Agent Retrieval)

A busca guarda um registro por plano, fala, texto na tela e objeto de cada Decupagem numa coleção do Agent Retrieval, em outra região (ADR 0006). O código (`api/indice_da_busca.py`, `api/agent_retrieval.py`) lê projeto, região, coleção, índices e dimensão das variáveis `GCP_PROJECT_ID`, `BUSCA_REGIAO`, `BUSCA_COLECAO`, `BUSCA_INDICE_DESCRICAO` e `BUSCA_DIMENSAO`, que o `infra/modulos/mam/main.tf` entrega ao serviço. Só a descrição tem vetor, e o índice ANN dela (`momentos-descricao-ann`) é o único da coleção; toda busca por vetor leva o `searchHint.indexHint` dele. A busca visual, os planos parecidos e o vetor do quadro-chave saíram em 6/11/2026 (ADR 0006, #476): a indexação não calcula embedding de imagem. O embedding automático da descrição lê o campo `significado` de cada registro (a descrição do plano ou o texto da fala, do texto na tela ou do objeto), porque recusa registro sem texto. A busca por texto não é KNN e não usa índice de vetor; só filtros, sem texto nem vetor, não é busca.

**Sem o índice ANN, a busca vai pelo KNN (ADR 0006).** O dev rodou assim de 5 a 6/11/2026, por custo; hoje ele e a produção ligam o índice. A variável `indices_da_busca_ligados` do módulo (padrão `true`, e a raiz do dev, `infra/main.tf`, também) chega ao código como `BUSCA_INDICES_LIGADOS`, no serviço, no `mam-indexacao`, no `mam-purga` e no `make` (output `busca_indices_ligados`). Em `false`, as buscas por vetor vão pelo KNN, com `searchHint: {knnHint: {}}` explícito (sem ele, um índice que ainda existisse seria usado) e `distanceMetric: COSINE_DISTANCE` (o padrão do KNN é o produto escalar, e os vetores guardados não têm norma 1). O `semanticSearch` não aceita `distanceMetric` e, no KNN, ordena por produto escalar; por isso, sem índice, o significado da consulta vira vetor no cliente (`AgentRetrieval.vetor_da_consulta`: `predict` do `gemini-embedding-001` na região da busca, `RETRIEVAL_QUERY`, na dimensão da coleção) e vai como `vectorSearch` por cosseno em `descricao_vetor`. O corte de significado (`BUSCA_DISTANCIA_MAXIMA`) segue valendo sem recalibrar, porque a distância é a mesma do ANN. O `make criar-colecao-da-busca` não cria índice. Cada índice custa cerca de R$ 290 por mês fixos (réplica). **O que foi medido (uma medição pontual de 5/11/2026, feita com scripts fora do repositório, no dev com 11.724 registros, só leitura e com os índices ainda no ar):** 28 consultas (23 textos e 5 com filtro `tipo` ou `job_id`), `topK` 50, o ANN com `indexHint` como referência. O `semanticSearch` com `knnHint` **não** é equivalente: média de 6,0 iguais no top-10 e 27,8 no top-50, e o corte `<= 0,25` deixa de fazer sentido (a distância devolvida cai ao subir a semelhança). O `vectorSearch` por cosseno com o embedding calculado no cliente reproduz o ANN: em todas as 28 consultas a distância de cada posição do top-50 coincide com a do ANN (diferença máxima de 3e-7), os 1.400 resultados do top-50 do ANN estão no top-500 do KNN com a mesma distância, e o corte da busca híbrida deu o mesmo conjunto em 27 das 28 consultas (na outra, o teto de 500 cortou empates). As listas só diferem na ordem de registros empatados (vetores iguais, até 227 empatados na distância do 50º), que nenhum dos dois ordena por regra. A latência p50 foi de 275 ms no ANN, 329 ms no `semanticSearch` KNN e 488 ms no embedding mais o `vectorSearch` KNN (p95 de 1.035 ms, de duas das primeiras consultas, com a conexão ainda fria). O que **não** foi medido: nota de relevância contra gabarito humano, e consultas com filtro `programa` (nenhum registro do dev o traz). O KNN aceita no máximo 100 mil registros, um teto que o dev atinge com cerca de 65 h de vídeo (estimativa: os 11.724 registros de hoje valem uns 7,6 h de vídeo, ou cerca de 1.540 registros por hora, e 100 mil ÷ 1.540 dá 65 h); a gravação registra um aviso no log quando a coleção passa de 80 mil. **Cota do `predict`:** sem índice, cada texto novo de busca faz uma chamada ao `predict` do Vertex em `us-east4`, sem retry (o embedding de um texto repetido é reaproveitado, até 256 textos por processo). Essa chamada tem cota regional, e o #411 já teve 429; um 429 chega à busca como erro. Antes de chegar lá, ligue a variável, aplique e rode o `make criar-colecao-da-busca`. A produção fica com os índices: com uns 30 mil registros por dia, ela chegaria ao teto em uns 3 dias. Desligar não apaga os índices que já existem, porque eles não são recursos do Terraform. Apagá-los é um passo à mão, depois do deploy:

```
gcloud vector-search collections indexes delete <índice> --collection=<coleção> --location=<região da busca> --project=$GCP_PROJECT_ID
```

Os dois alvos abaixo só rodam com credenciais (ADC de quem roda e o `.env`) e ficam fora do CI e do `make verificar`:

- `make criar-colecao-da-busca`: cria a coleção de momentos e o índice ANN da descrição, `momentos-descricao-ann` (nenhum com `BUSCA_INDICES_LIGADOS=false`), com os campos de filtro declarados, e espera cada operação terminar (idempotente: o que já existe fica). **Custo:** o índice implantado tem réplicas sempre ligadas, cobradas por hora, mesmo sem consulta (aceito na ADR 0006); veja a tabela de preços do Agent Retrieval, que não está registrada aqui.
- `make caos-dev URL=... CHAVE_A=... CHAVE_B=... [CLIPE=arquivo.mp4]`: o teste de caos da API no dev (`api/caos_dev.py`, roteiro em `api/caos.py`), com as chaves de dois sistemas de teste (`make emitir-chave`, escopos criar, ler e cancelar). Sem `CLIPE`, só chama a API: cria e cancela Jobs, sem custo de pipeline. **Custo:** com `CLIPE=` o clipe sobe de verdade e passa pelo pipeline inteiro (Gemini e GPU, mais o Agent Retrieval), então use um clipe curto.
- `make medir-busca [CONSULTAS=30] [DIMENSOES="128 256"]`: indexa 3 Decupagens de exemplo (`api/exemplos_da_busca.py`) na coleção, consulta "vestido vermelho da Sabrina Sato" (filtros exatos, texto e significado, fundidos por RRF), confere que só volta o objeto dela e que pedir a cor errada (azul) não volta nada (servido pelo índice ANN, um filtro que ele não aceita pode ser ignorado sem erro), mede o p50 e o p95 de N consultas e imprime a tabela com o total de registros da coleção. Apaga os vídeos de exemplo no fim. Cada dimensão fora da configurada, uma de cada vez, cria a coleção temporária `BUSCA_COLECAO_DE_MEDIDA` e a apaga no fim, com os índices e os objetos dentro, mesmo se a medição falhar. A coleção nasce com os índices ligados, cobrados enquanto existirem; com `BUSCA_INDICES_LIGADOS=false` nasce sem índice e a medição é a do KNN. Cada repetição medida usa um significado novo, porque sem índice o embedding da consulta é guardado por texto. O comando sai com erro se uma das duas conferências falhar. Cada índice ANN nasce com uma réplica só (`REPLICAS_DO_INDICE`, em `api/agent_retrieval.py`), no modo `PERFORMANCE_OPTIMIZED`; sem isso o serviço usaria de 2 a 5.

- `make comparar-leituras REFERENCIA=<json> NOVA=<json> [OPCOES="--lidos-nova N --segundos-nova S --segundos-referencia S"]` (#233, sem nuvem): compara duas leituras da tela do mesmo vídeo, a de referência e a nova (`<job>/leitura_da_tela.json` do bucket de aceitos, baixada com `gcloud storage cp`). Mostra os textos distintos que só um dos lados achou, as aparições cujo início ou fim mudou mais de 1 s (ou que a nova não achou) e quantos quadros cada leitura leu e o tempo. Os quadros lidos e o tempo não estão no formato da leitura: saem do log do Job (`Leitura da tela: N quadros lidos e M pulados em S s`), e entram pelas opções; a referência, de um quadro por segundo, leu todos. A referência do programa FAMA (Job `98502242109e4280b7073b07a3ebe573`) não pode ser apagada nem sobrescrita antes da medição: a leitura nova vai num Job novo (reprocessar a etapa regrava a leitura do mesmo Job, então copie a de referência antes).
- **Leitura da tela só quando a imagem muda (#233).** O OCR compara cada quadro de 1 s com o último quadro lido (reduzido a 128x72 em tons de cinza, em seis faixas horizontais de oito blocos) e só lê de novo se algum bloco mudou, em média, mais que `LIMIAR_DE_MUDANCA` (variável `limiar_de_mudanca_do_ocr` do Terraform, padrão 3, de 0 a 255; 0 lê todo quadro). O quadro que não mudou repete a leitura do anterior, e o resultado segue com um quadro por segundo. O detector do OCR em CPU vem do `ARG DETECTOR` do Dockerfile (`DETECTOR_OCR_CPU` no `docker-bake.hcl`): `PP-OCRv5_server_det` (padrão) ou `PP-OCRv5_mobile_det`; a imagem com GPU fica com o `server`.
- Quais tipos de Correção exigem aprovação do Curador: aba "Regras de aprovação" da Administração (só o Administrador). Não há comando.
- `make reindexar [JOB=<id>]`: grava na busca, só no que mudou (compara com o índice), a Decupagem entregue (com as Correções em vigor) de um Job, ou de todos os concluídos; repetir dá o mesmo resultado. O estado (`pendente`, `indexado` ou `falhou`, com o horário) fica em `indexacao` no `GET /v1/jobs/{id}`. A indexação roda ao fim da análise (Job `mam-indexacao`, depois da etapa `inventario_de_objetos`) e a cada Correção que passa a valer (a pendente só entra quando o Curador aprova); uma falha dela nunca muda o `estado` do Job.
- `make migrar-banco-de-seguranca` (#465): copia `papeis_de_usuarios`, `chaves_de_api` e `auditoria` do `(default)` para o banco de segurança (#368), com os mesmos ids e campos, em lotes; não apaga a origem. Só grava os ids que o banco novo ainda não tem: repetir não duplica nada e não desfaz o que os serviços já gravaram nele (uma chave revogada no banco novo não volta a valer). Imprime, por coleção, a contagem nos dois bancos, quantos copiou e quantos ids da origem faltam no destino (sai com erro se faltar algum). O banco vem de `FIRESTORE_BANCO_DE_SEGURANCA` (ou do `terraform output banco_de_seguranca`); sem ele o comando recusa.
  **Ordem dos passos humanos e a janela do deploy.** O mesmo `terraform apply` cria o banco e liga `FIRESTORE_BANCO_DE_SEGURANCA` na `web` e na `purga`; a partir daí eles leem papéis e chaves do banco novo, e administradores e sistemas perdem o acesso até a migração. Para não ter janela: (1) criar só o banco e os índices da auditoria nele, com o `.env` carregado e as variáveis do `scripts/deploy-dev.sh`: `set -a && . ./.env && set +a && TF_VAR_projeto=$GCP_PROJECT_ID TF_VAR_regiao=$GCP_REGION TF_VAR_admins_emergencia=$ADMINS_EMERGENCIA terraform -chdir=infra apply -target=module.mam.google_firestore_database.seguranca -target=module.mam.google_firestore_index.auditoria_na_seguranca` (os índices entram já, porque levam minutos para ficar prontos e a tela de auditoria depende deles); (2) `make migrar-banco-de-seguranca FIRESTORE_BANCO_DE_SEGURANCA=<nome do banco>` (o nome do `banco_de_seguranca.tf`, passado à mão porque o apply com `-target` pode não gravar o output); (3) o deploy completo (`make deploy-dev`), que liga a variável; (4) o mesmo comando de novo, que traz só os documentos novos que os serviços gravaram no `(default)` entre os passos 2 e 3 (auditoria, papel de conta nova); (5) conferir as contagens das três coleções nos dois bancos; (6) só então abrir o ticket que apaga as cópias antigas do `(default)`. Entre os passos 2 e 3, não mude papéis nem revogue chaves: a mudança num documento que já foi copiado fica só no `(default)` e o passo 4 não a traz (refaça-a depois do passo 3). Os alvos de chaves e papéis do Makefile (`emitir-chave`, `revogar-chave`, `atribuir-papeis`...) já gravam no banco novo assim que o output existe, e a chave emitida por eles antes do passo 3 só passa a valer com o deploy. Se o deploy já foi feito antes da migração, a janela existe: rode o passo 2 logo.
- `make preencher-jobs-do-painel` (#454): grava na tabela `jobs_do_painel` do BigQuery (programa, duração, dono, estado e datas de cada Job, para a Revisão e o Custo do painel) os Jobs que já existem. Rode uma vez no dev depois do `terraform apply`, porque a consulta agendada (`infra/modulos/mam/jobs_do_painel.sql`) só vê os Jobs com evento de uso; depois, confira a contagem da tabela com a da coleção `jobs`. Repetir troca as linhas pelo `id` e dá o mesmo resultado.
- `make preencher-taxa-diaria` (#455): grava, ao lado de cada decupagem de Job concluído que ainda não tem, a contagem de itens por tipo (`<job>/itens_por_tipo.json`; as decupagens novas já a ganham ao serem gravadas) e refaz o último ano na tabela `taxa_de_correcao_por_dia` do BigQuery (`DIAS=<n>` muda a janela). Rode uma vez no dev depois do `terraform apply` e de novo depois de `make reprocessar-versao`: o Job agendado `mam-taxa-diaria` (a cada hora) refaz só hoje e ontem, e o reprocessamento muda dias antigos. Repetir dá o mesmo resultado. Cada dia é o cálculo de `taxa_de_correcao.py` sobre aquele dia; um vídeo revisado em dois dias tem os itens contados nos dois.
- `make gravar-mes-nos-jobs` (#479): grava `mes_exibicao` (`AAAA-MM`) em todo Job que tem `data_exibicao` e ainda não tem o campo certo, em lotes; os Jobs novos já o ganham ao serem gravados. Repetir não muda nada. Imprime quantos gravou, quantos já estavam certos e quantos não têm data. **Ordem:** (1) `terraform apply`, que cria os índices `acervo_por_mes` (a variável `listagem_por_mes` nasce `false`); (2) `make gravar-mes-nos-jobs`; (3) `listagem_por_mes = true` e novo apply. Com a variável ligada, a lista por envio com as duas pontas do período manda `mes_exibicao in [meses]` ao Firestore (se couber em 30 disjunções e 100 componentes; senão, o filtro de datas fica em Python, como antes). Ligar antes da carga faz o Job antigo sumir da lista por período.

**Ligar o índice da descrição no dev (#476).** Ordem: (1) `terraform apply` (`indices_da_busca_ligados` já é `true`); (2) `make criar-colecao-da-busca`, que cria só o `momentos-descricao-ann`; (3) apagar o `momentos-quadro-ann`, se existir, com o `gcloud vector-search collections indexes delete` acima: ele não é mais usado e custa a réplica.

**Reindexar os vídeos que já estão no dev depois do inventário de objetos (#245).** O registro de cada plano passa a levar o inventário inteiro, todos os objetos do inventário ganham registro próprio (desde o #334; no #245 eram só os de destaque 3, e a busca por objeto não achava os de destaque 1 e 2) e os registros ganham o campo `destaque`, que pesa na ordem (3% por nível acima de 1: +3% no destaque 2, +6% no 3). Vídeo a vídeo:

- Vídeo **sem inventário** (analisado antes do #244): no Visualizador, "Reprocessar…" a partir de `inventario_de_objetos`, que roda o inventário e depois a indexação. No dev são poucos vídeos; se forem muitos, um laço pela rota do reprocessar (#147).
- Vídeo **com inventário, mas indexado antes do #245 ou do #334**: `make reindexar` sem `JOB`, que reindexa todos os concluídos.
- A coleção já criada não muda de esquema: `make criar-colecao-da-busca` é idempotente e deixa como está o que existe. Uma coleção nascida antes deste ticket não declara o campo `destaque`; se o Agent Retrieval recusar (ou ignorar) o campo, recrie a coleção (`apagar_colecao` e `make criar-colecao-da-busca`) e rode `make reindexar`. Ainda não foi conferido se ele aceita campo fora do esquema.

Os corpos REST seguem o documento de discovery da API (`v1beta`, revisão 20261022), conferido no #122.


## Versão fixa do pipeline (#250)

`api/versao_pipeline.py` é o único lugar que define a `VERSAO_PIPELINE` (por exemplo `2026.11.1`) e o manifesto: o modelo de cada etapa, o hash de cada instrução, a versão do esquema e os motores de transcrição, OCR e objetos. Cada decupagem nova grava `versao_pipeline` e `manifesto_do_pipeline` (ao fim da análise); a anterior, sem o campo, continua válida e aparece como "anterior à versão". O Visualizador mostra a versão ao lado do nome do vídeo.

Trocar modelo, instrução, esquema ou motor exige trocar a versão: `api/tests/test_versao_pipeline.py` compara o manifesto com `api/tests/versao_pipeline_fixada.json` e falha com a instrução de regravar o arquivo. O motor de objetos (`MOTOR_OBJETOS`/`MODELO_OBJETOS` do inventário) vem do ambiente do Job e não está no manifesto; o manifesto leva o Florence.

Reprocessar o acervo de propósito, depois de trocar a versão e fazer o deploy:

```bash
make reprocessar-versao                       # só lista os Jobs concluídos de versão anterior e o custo estimado
make reprocessar-versao DE=anterior LIMITE=20 # só os sem versão, até 20 (DE também aceita uma versão, como 2026.10.1)
make reprocessar-versao LIMITE=20 CONFIRMAR=1 # reprocessa pela análise, em lotes (TAMANHO_DO_LOTE=5, PAUSA_ENTRE_LOTES_S=60)
make tempo-de-revisao                         # CSV do tempo de revisão por vídeo e por pessoa (minutos por hora de vídeo)
make tempo-de-revisao DESDE=2026-11-01        # só o que teve pulso de 1º/11 em diante (data ISO, UTC)
make taxa-de-correcao                         # CSV da taxa de correção por programa, versão do pipeline e tipo
make taxa-de-correcao DESDE=2026-11-01 ATE=2026-11-30 PROGRAMA="TV Fama"  # período (dias ISO, UTC, inclusive) e programa, opcionais
```

O custo estimado é as horas de vídeo × `CUSTO_POR_HORA_USD` (do ambiente; sem ele sai "n/d"). Cada Job reprocessado entra na auditoria como `video.reprocessado`, por `sistema` `reprocessar-versao`, com o mesmo caminho da rota (#147, #235). A chave de conteúdo e a deduplicação ficam fora (E7).

## Passada de comparação (#247)

Roda a análise inteira de um Job concluído com outro modelo e guarda o resultado ao lado da decupagem, para comparar por requisito (#248) e lado a lado (#249). Só no dev, com as credenciais de quem roda (a conta que lê o bucket de decupagens e chama o Gemini), depois do merge:

```bash
export PRECOS_DOS_MODELOS="gemini-3.8-flash=0.75:3.75"   # modelo=entrada:saída, US$ por milhão de tokens, preço Flex (ADR 0004)
make passada-de-comparacao JOB=<id do Job> MODELO=gemini-3.8-flash   # nome curto, sem barra; JANELAS_EM_PARALELO=4 acelera
```

- A análise é a do Job (janelas, consolidação, identificação, com a transcrição e a leitura da tela que ele já tem), sem escalonamento: o modelo pedido faz todas as janelas. Dá para repetir com outros modelos; cada rodada é uma passada nova.
- A passada vai para `<job>/passadas/<data>-<modelo>.json` no bucket das decupagens, com o modelo, a data, os tokens e o custo (pelos preços do `PRECOS_DOS_MODELOS`) e os segundos de `janelas`, `consolidacao` e `identificacao`. Não é indexada, não aparece no Acervo nem na busca, não recebe correções, não dispara webhook, e a Decupagem do Job não é regravada. A identificação lê o catálogo de pessoas, mas não acrescenta nome nele.
- Cada chamada ao Gemini leva o rótulo `etapa=passada_de_comparacao`, para o faturamento separar o custo.
- Leitura: `GET /v1/jobs/{id}/passadas` (resumos) e `GET /v1/jobs/{id}/passadas/{passada}` (com a decupagem), com `decupagem.ver`.
- Custo por hora de vídeo, pelas premissas do `docs/Plano_MAM.md` (1 fps, ~60 mil tokens de saída por hora), a preço Standard: ~US$ 1,14 no 3.8 Flash, ~US$ 1,24 no 3.5 Flash e ~US$ 0,30 no 3.5 Flash-Lite. As chamadas da passada saem em Flex (ADR 0004), pela metade disso: um programa de 2 h custa uns US$ 1,15 no 3.8 Flash. O custo real da rodada sai impresso no fim do comando e fica na passada. Ponha em `PRECOS_DOS_MODELOS` o preço do Flex.


### Comparar a decupagem com a passada (#248)

```
make comparar-passadas JOB=<id> [PASSADA=<id>] [MODELO=<modelo>]   # sem PASSADA, a última (do MODELO, se vier)
make comparar-passadas JOBS=<id>,<id>,...                            # soma por requisito, a última passada de cada Job
```

- Grava `comparacao-passadas/<job>-<passada>.md` e `.json` (em `PASTA=`; vários Jobs viram `piloto-<data>`). O lado A é a decupagem do Job e o B, a passada.
- Por requisito (famosos, menções, pautas, B-roll em planos limpos e em descrições, comerciais): contagens, itens só de um lado e itens dos dois com diferença de nome, tipo ou marca, ou de tempo acima da tolerância de 2 s. O pareamento é o do `api/comparador.py`. Timecode: erro médio, p95 e quantos pares (inclusive os de nome trocado) passam da tolerância.
- Custo por hora de vídeo e tempo (por etapa e total) dos dois lados. O preço vem de `PRECOS_DOS_MODELOS` e a data da tabela consultada, de `DATA_DA_TABELA_DE_PRECOS`. O Job não guarda os tokens que gastou: passe-os em `TOKENS_DO_JOB=<job>=<entrada>:<saida>,...` (e o modelo em `MODELO_DO_JOB`, o `MODELO` de `api/gemini.py` por padrão); sem eles, o custo do lado do Job sai "n/d", e a soma de vários Jobs também.

## Variações do Florence-2 e medição na GPU (#329)

O inventário de objetos levou 19 min no FAMA (~2 s por quadro, 421 quadros). O Job com GPU
(`api/objetos_job.py`) aceita, por variável de ambiente, as mudanças a medir. Sem nenhuma
delas o resultado é o de antes.

| Variável | Padrão | O que muda |
|---|---|---|
| `FLORENCE_FEIXES` | `3` | `num_beams` da geração; `1` é a busca gulosa |
| `FLORENCE_LOTE` | `1` | quadros por `generate` |
| `FLORENCE_MAX_TOKENS` | `1024` | `max_new_tokens` |
| `FLORENCE_LEGENDAS` | `1` | `0` não gera as legendas de região (`<DENSE_REGION_CAPTION>`) |
| `FLORENCE_PULAR_REPETIDOS` | `0` | distância máxima (de 64 bits) entre os hashes de dois quadros do mesmo plano para o segundo reaproveitar o resultado do primeiro; `0` desliga |
| `FLORENCE_LOG_A_CADA` | `25` | a cada quantos quadros o Job loga `Quadros: feitos/total` |

O log do Job também diz, cada vez que ela cresce, o tamanho da maior resposta até ali, em
tokens: a última dessas linhas serve para escolher o `FLORENCE_MAX_TOKENS`.

Para medir, com as credenciais da pessoa (precisa de `MODELO_OBJETOS` no `.env`, o mesmo
modelo do Job de inventário):

```
make medir-florence JOB=<id>                          # todas as variações
make medir-florence JOB=<id> VARIACOES="guloso lote8" # só algumas
```

O alvo roda o Job com GPU uma vez por variação, sobre os quadros já gravados do Job (a
variação `hoje`, sem variável, roda sempre primeiro e é a base), converte o bruto com o Gemini
e guarda, em `<job>/objetos/medicao/<variacao>/` no bucket das decupagens, `bruto.json`,
`inventario.json` e `medida.json` (tempo por quadro e critério). Nada em `<job>/objetos/florence.json`
nem na Decupagem é tocado. As variações estão em `api/medir_florence.py` (`VARIACOES`). Uma
que falha (memória da GPU, por exemplo) aparece como `falhou` na tabela e as outras seguem;
se a base `hoje` falhar, as outras nem rodam.

A tabela traz o tempo por quadro, quantas vezes mais rápido que `hoje`, os objetos de cena
(fora `roupa`, `acessorio` e `calcado`) contra os de hoje, a categoria de cena que mais caiu, os
objetos de destaque 3 que sumiram, o veredito do critério e se bateu a meta (≤ 0,7 s por
quadro). O critério passa quando os objetos de cena somam pelo menos 90% dos de hoje, nenhuma
categoria de cena cai mais que isso e nenhum objeto de destaque 3 de hoje some; o objeto é o mesmo se o
plano, a categoria e o nome (sem acento nem caixa) são iguais. O Gemini não é determinístico:
repetir a medição pode mexer um pouco nas frações.

## Cassete do Gemini

O teste de contrato com o Gemini (`api/tests/test_cassete.py`) roda em todo `make verificar`, sem rede: passa por `analisar` o texto de uma resposta real gravada em `api/tests/cassetes/gemini_sintetico.json` e confere o esquema da decupagem e os invariantes de tempo, nunca o texto exato. O cassete guarda só o modelo, a versão exata que a Vertex informou (`modelVersion`), o bloco `video`, o texto da resposta e o `instrucao_sha256` (SHA-256 da `INSTRUCAO` de `api/gemini.py`), sem cabeçalhos nem credenciais. Mudar uma letra da `INSTRUCAO` muda o hash e derruba o contrato até regravar, com a mensagem de rodar `make gravar-cassetes`; o hash não cobre os perfis e as seções que `instrucao()` encaixa nela. Se a versão gravada for diferente da fixada em `VERSAO_DO_MODELO` (`api/gemini.py`), o contrato falha: o Google trocou o modelo por baixo do nome, e alguém precisa conferir a resposta e atualizar a constante. O teste só percebe ao regravar; entre gravações, nada consulta a Vertex.

Para regravar (a cada troca de modelo, de esquema ou de instrução), com o dev no ar e as credenciais ADC de uma conta com acesso ao projeto (`gcloud auth application-default login`):

```sh
make gravar-cassetes
```

Ele gera com o ffmpeg um clipe sintético de 30 s, passa pelo validador, sobe o proxy no bucket de clipes-ouro, sob `cassetes/sintetico.mp4`, e faz a chamada real ao modelo fixado em `MODELO`, no `api/gemini.py`. O clipe continua sintético, nunca um dos clipes-ouro: só mora no mesmo bucket, fora do bucket de aceitos, onde só o Job de validação grava. O nome do bucket vem do `output` `bucket_clipes_ouro` do Terraform (ou de `BUCKET_CLIPES_OURO` no ambiente). Se o teste do modelo falhar depois de trocar `MODELO`, é este o comando.

## Loop AFK

`scripts/afk/rodar.sh` implementa os tickets `ready-for-agent` sozinho, sem perguntas, um ticket por iteração. Cada iteração roda dois `claude -p` novos, cada um com o contexto vazio: um implementa o ticket e o outro revisa o que foi commitado. O loop (`main.mts`, no Mac) usa o [Sandcastle](https://github.com/mattpocock/sandcastle) num clone separado (`../mam-prk-redetv-afk`), para a pasta principal continuar livre. Cada iteração roda numa vaga nova: um contêiner Docker sem credencial de nuvem, montado num worktree do branch do ticket (`afk-t/<data-hora>/N`). Quando o ticket fica pronto, um segundo sandbox, o integrador, leva o branch do ticket ao branch do PR. O estado entre as iterações fica em `.afk/` dentro do clone. O repositório principal fica de fora dos contêineres, e os commits voltam para ele por um `git bundle`, que o `git fetch` confere objeto por objeto. No fim, o script faz um push só, no branch `afk/<data-hora>`, e abre um PR em rascunho com `Closes #N` de cada ticket feito. Se o agente mudou qualquer arquivo fora de `api/` e `web/src/` (por exemplo `.github/workflows/`, `.githooks/`, `Makefile`, lockfiles, configs do `web/`, `AGENTS.md` ou `docs/`), o corpo do PR abre com um aviso em destaque listando esses arquivos. O CI do PR roda o `ci.yml` e o `make verificar` do próprio branch, os hooks de `.githooks/` rodam no Mac e `AGENTS.md` e afins guiam os próximos agentes, então revise antes do merge. O merge sai com `make mesclar-afk` e nunca com o CI vermelho.

Arquivos em `scripts/afk/`: `prompt.md` (o texto que o agente implementador recebe; edite à vontade), `revisao.md` (o do revisor), `main.mts` (o loop, no Mac), `rodar.sh` (Keychain, clone, emuladores, push e PR), `mesclar.sh` (o `make mesclar-afk`), `hook-contexto.sh` (o aviso de contexto, ligado em `.claude/settings.json` e inerte fora do loop), `Dockerfile`, `main.test.mts` e o `package.json` com o Sandcastle fixo numa versão (o `rodar.sh` e o `make testar-afk` rodam `npm ci` nessa pasta). O `main.mts` roda direto no Node, que tira os tipos sozinho a partir da versão 22.18.

### Configuração, uma vez só

1. **Token do Claude Code.** Gere com `claude setup-token` e guarde no Keychain (o comando pede o valor):

   ```sh
   security add-generic-password -a "$USER" -s afk-claude -w
   ```

2. **Dois tokens do GitHub**, ambos *fine-grained* e com acesso só a `RedeTVRevolution/mam-prk-redetv-` (a organização pode precisar aprovar):
   - `afk-github-agente`, que vai para o contêiner: Issues leitura e escrita, Contents e Pull requests só leitura. Sem escrita em Contents, o agente não consegue fazer push. Pull requests serve para um `Bloqueado por: #N` em que `#N` é um PR mesclado; sem ela, o loop anota (sem novas tentativas) e o ticket segue esperando.
   - `afk-github-script`, que fica no Mac: Contents, Pull requests e Workflows leitura e escrita. Serve para o fetch, o push final e o PR. Sem Workflows em *Read and write*, o GitHub recusa o push de um branch em que o agente mexeu em `.github/workflows/`.

   ```sh
   security add-generic-password -a "$USER" -s afk-github-agente -w
   security add-generic-password -a "$USER" -s afk-github-script -w
   ```

3. **Label `afk-feito`**, que o script põe em cada ticket terminado:

   ```sh
   gh label create afk-feito --color 0E8A16 --description "Feito pelo loop AFK, aguardando merge"
   ```

4. **Docker Desktop** aberto. A imagem `mam-afk` é construída na primeira execução. O `rodar.sh` também sobe os emuladores do Firestore e do Storage, nas versões do `ci.yml`, e o contêiner do agente entra na rede deles. Assim o `make verificar` do loop roda os testes de nuvem em vez de pulá-los. O `main.mts` se recusa a começar sem `FIRESTORE_EMULATOR_HOST` e `STORAGE_EMULATOR_HOST`.
5. **Plugin `mattpocock-skills`** instalado no Claude Code do Mac. O script monta a pasta dele no contêiner, só leitura.

### Como rodar

O clone sai da `origin/main`, então este loop só funciona depois do merge dele na `main`. Comece com uma iteração e confira o resultado:

```sh
scripts/afk/rodar.sh 1
```

Veja as notas em `.afk/progresso-afk-<data-hora>.md`, uma cópia na pasta principal, o `git log afk/<data-hora>` e o PR. Inspecione pela pasta principal e não rode `git` dentro do clone do agente: o `.git` dele, inclusive `config` e hooks, ficou sob controle do agente. A execução seguinte apaga e recria o clone. Depois, aumente o número de iterações, por exemplo `scripts/afk/rodar.sh 10`.

Com o loop rodando, `../mam-prk-redetv-afk/.afk/progresso.md` mostra a iteração atual e `../mam-prk-redetv-afk/.afk/fila` mostra a fila: os tickets na ordem em que o loop vai pegá-los, cada um com os bloqueadores que ainda espera. A cada ticket novo o loop regrava a fila.

Para mesclar o lote:

```sh
make mesclar-afk
```

Ele pega o PR aberto mais recente de um branch `afk/*` deste repositório, aberto pelo seu login (PR de fork não entra; com `BRANCH=afk/...`, o daquele branch, que é o que o `rodar.sh` passa). Se o branch existe na pasta principal, o PR tem de apontar para a mesma ponta. Depois espera o CI terminar e, só se todas as checagens passarem, tira o PR do rascunho, faz o merge com squash e apaga o branch no GitHub e no Mac. Depois atualiza a `main` e apaga os branches locais `afk/*` cuja ponta é a de um PR mesclado; os `-bloqueado-N` e `-parcial-N` ficam. Se o CI falhar, ele para sem mesclar e mostra o log do job que falhou. Usa o login do `gh` e do `git` deste Mac, não os tokens do Keychain. Os comandos `git` dele rodam com os hooks desligados, porque depois do merge `.githooks/` pode ter código do agente.

Cada iteração:

1. Pega o ticket: o que ficou parcial na iteração anterior ou o menor `ready-for-agent` aberto, sem `afk-feito`, com todos os bloqueios resolvidos (dependências nativas e linha `Bloqueado por: #N`). Um bloqueio está resolvido se o bloqueador está fechado ou tem `afk-feito`, ou se é um PR mesclado (PR aberto ou fechado sem merge segue bloqueando).
2. Roda o implementador com `prompt.md`: `mattpocock-skills:tdd`, `make verificar` e commit. Descarta o que não foi commitado e lê o fim da resposta (`<ticket>N</ticket>` e `<status>…</status>`).
3. Se o status é `feito`, roda o revisor com `revisao.md`: um `claude -p` novo, com o modelo de `AFK_MODELO_REVISOR`, que roda `mattpocock-skills:code-review` contra o ticket a partir do commit de antes dele e commita as correções. Descarta de novo o que não foi commitado. O revisor termina com `<revisao>feita</revisao>` ou `<revisao>erro</revisao>`; sem um dos dois, ou cortado, a iteração conta como falha e a próxima retoma o ticket.
4. Roda `make verificar`, já depois da revisão. Se falhar com um teste falhando (`FAIL` do vitest ou `FAILED` do pytest), roda de novo uma vez, salvo se o prazo de 1 h estourou: sob carga, os testes da web falham cada vez num teste diferente. Lint, tipos e build vermelhos não repetem. Se passar na segunda, as notas dizem o que falhou na primeira. Se falhar duas vezes, desfaz os commits da iteração, os do implementador e os do revisor.
5. Age conforme o status:
   - `feito` (e revisão `feita`): o integrador junta o branch do ticket ao do PR e o script põe `afk-feito` no ticket.
   - `parcial`: a próxima iteração continua o ticket.
   - `bloqueado`: o agente comentou a pergunta no ticket e trocou a label para `ready-for-human`. O script tira o trabalho do branch, guarda num branch local `<branch>-bloqueado-N` e segue.
   - `erro`, do implementador ou do revisor: problema do ambiente, como uma skill ausente. O loop para, e o trabalho do ticket sai do branch do PR para `<branch>-parcial-N`.

Com `AFK_VAGAS` acima de 1, o loop toca vários tickets ao mesmo tempo, cada um com as suas iterações. Ele não pega dois tickets da mesma spec juntos (a primeira referência, `#N` ou um `.md`, da seção "Parte de" do ticket). O integrador junta os tickets feitos ao branch do PR, um por vez, com `git merge --no-ff`. Se a árvore do merge difere da ponta do ticket, roda `make verificar` de novo, com a mesma segunda tentativa do portão. Se o merge conflita ou fica vermelho, o branch do PR volta a como estava e a iteração seguinte do ticket é de merge: o agente traz o branch do PR para o do ticket, resolve e verifica, sem revisão. Se nem assim entrar, o ticket volta para humano como um bloqueado. As iterações contam para o loop inteiro, e as falhas seguidas, para cada ticket; um erro ou a terceira falha seguida de um ticket param a distribuição de tickets, e cada vaga termina a iteração em que está.

O loop para sozinho quando a fila esvazia, depois do número de iterações pedido, depois de 3 falhas seguidas (portão vermelho ou iteração sem sinal válido) ou se houver um ticket aberto com `afk-feito`, o que indica um PR anterior sem merge. Um ticket com 3 parciais seguidas volta para humano como um bloqueado. Um ticket em andamento quando o loop para sai do branch do PR e fica num branch local `<branch>-parcial-N`.

### Variáveis

| Variável | Padrão | Para quê |
|---|---|---|
| `AFK_VAGAS` | 1 | Tickets ao mesmo tempo, cada um na sua vaga |
| `AFK_PYTEST_PROCESSOS` | 6 | Com mais de uma vaga, processos do pytest no `make verificar` de cada vaga (com uma, todos os CPUs) |
| `AFK_VITEST_PROCESSOS` | 4 | Com mais de uma vaga, processos do vitest no `make verificar` de cada vaga (com uma, o padrão do vitest) |
| `AFK_AVISO_TOKENS` | 120000 | O hook manda o implementador comitar o que está verde, anotar o que falta e sair como `parcial`. O revisor não recebe o aviso, só o corte |
| `AFK_CORTE_TOKENS` | 140000 | O script mata a iteração e descarta o que não foi commitado |
| `AFK_MAX_TURNOS` | 300 | `--max-turns` de cada iteração |
| `AFK_MAX_FALHAS` | 3 | Falhas seguidas antes de parar |
| `AFK_MAX_PARCIAIS` | 3 | Parciais seguidas de um ticket antes de devolvê-lo para humano |
| `AFK_MODELO` | padrão do Claude Code | `--model` do implementador |
| `AFK_MODELO_REVISOR` | opus | `--model` do revisor |
| `AFK_AUTO_MERGE` | 0 | Com 1, o `rodar.sh` roda `make mesclar-afk` depois de abrir o PR, só quando o agente mudou apenas `api/` e `web/src/`; com qualquer outro arquivo (a lista do aviso no PR), o merge fica para você |

O tamanho do contexto é a soma de `input_tokens`, `cache_read_input_tokens` e `cache_creation_input_tokens` da última resposta da conversa principal (sem subagentes).

Um agente que passa 20 minutos sem escrever nada, por exemplo preso numa tool call, também é morto. A iteração conta como falha, e o que ele não commitou é descartado.

Uma falha do `gh` (rede, GitHub fora do ar) não para o loop: ele tenta 5 vezes, com esperas de 30 s a 4 min, e cada chamada tem prazo de 2 min. Um comentário no ticket vai uma vez só; se falhar, a nota no progresso pede para conferir à mão.

### Testes

```sh
make testar-afk
```

Roda o `shellcheck` e o `main.test.mts` (`node --test`), que exercita o loop com `claude` e `gh` falsos, sem Docker e sem rede (o `noSandbox` do Sandcastle): ticket feito e revisado num `claude -p` à parte, estouro de contexto, ticket bloqueado, verificação falhando depois do commit, revisão que quebra a verificação, revisão sem sinal, revisão com erro, parciais seguidas, fila sem tickets elegíveis, PR anterior sem merge, loop sem as variáveis dos emuladores e o hook abaixo e acima do aviso. O CI roda o mesmo alvo.
