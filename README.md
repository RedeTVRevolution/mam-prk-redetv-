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

## Deploy no dev

A E0 roda num serviço Cloud Run único, `mam-web`, em que o FastAPI serve a API e o build do React. O Terraform em `infra/` cria tudo: Artifact Registry, Firestore, os buckets privados (quarentena, aceitos e decupagens), uma conta de serviço por componente, o serviço, o Identity Platform (login com MFA TOTP e política de senha) e o alerta de login dos administradores de emergência. Antes, rode uma vez o `scripts/wizard-gcp-dev.sh`, que cria o projeto, a conta `mam-terraform` e o `.env` e inicializa o Identity Platform com a sua conta de Owner. Esse último passo é único por projeto (vale também para `staging` e `prod`): ele exige `firebase.projects.update`, que a `mam-terraform` não tem, e depois o Terraform importa a config e cuida do resto. Acrescente também ao `.env` os e-mails das contas, separados por vírgula:

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

Para acompanhar uma publicação: na aba Actions do GitHub, abra a execução do CI do commit e o job `publicar`. O log mostra o link do build no console do Cloud Build, o plano do Terraform e, no fim, a URL com o `/v1/health` respondendo. O staging e a produção, com aprovação no Cloud Deploy, ficam para a E10.

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

A busca guarda um registro por plano, fala, texto na tela e objeto de cada Decupagem numa coleção do Agent Retrieval, em outra região (ADR 0006). O código (`api/indice_da_busca.py`, `api/agent_retrieval.py`) lê projeto, região, coleção, índices e dimensão das variáveis `GCP_PROJECT_ID`, `BUSCA_REGIAO`, `BUSCA_COLECAO`, `BUSCA_INDICE_DESCRICAO`, `BUSCA_INDICE_QUADRO` e `BUSCA_DIMENSAO`, que o `infra/main.tf` entrega ao serviço. Cada vetor (a descrição e o quadro-chave) tem o seu índice ANN, porque um índice cobre um só campo de vetor, e toda busca por vetor leva o `searchHint.indexHint` do índice do seu campo. O do quadro-chave está ligado no dev (`indice_do_quadro_ligado`, ADR 0006, #268): a indexação manda o quadro-chave de cada plano e a descrição ao Gemini Embedding 2 (`api/embedding_do_quadro.py`) e grava o vetor no registro do plano; plano sem quadro fica só com o vetor da descrição. Com `BUSCA_INDICE_QUADRO` vazia a coleção nasce só com o índice da descrição, nenhum vetor de quadro é calculado e a busca por quadro é recusada. O embedding automático da descrição lê o campo `significado` de cada registro (a descrição do plano ou o texto da fala, do texto na tela ou do objeto), porque recusa registro sem texto. A busca por texto não é KNN e não usa índice de vetor; só filtros, sem texto nem vetor, não é busca.

Os dois alvos abaixo só rodam com credenciais (ADC de quem roda e o `.env`) e ficam fora do CI e do `make verificar`:

- `make criar-colecao-da-busca`: cria a coleção de momentos e os dois índices ANN, com os campos de filtro declarados, e espera cada operação terminar (idempotente: o que já existe fica). **Custo:** o índice implantado tem réplicas sempre ligadas, cobradas por hora, mesmo sem consulta (aceito na ADR 0006); veja a tabela de preços do Agent Retrieval, que não está registrada aqui.
- `make medir-busca [CONSULTAS=30] [DIMENSOES="128 256"]`: indexa 3 Decupagens de exemplo (`api/exemplos_da_busca.py`) na coleção, consulta "vestido vermelho da Sabrina Sato" (filtros exatos, texto e significado, fundidos por RRF), confere que só volta o objeto dela e que pedir a cor errada (azul) não volta nada (servido pelo índice ANN, um filtro que ele não aceita pode ser ignorado sem erro), mede o p50 e o p95 de N consultas e imprime a tabela com o total de registros da coleção. Apaga os vídeos de exemplo no fim. Cada dimensão fora da configurada, uma de cada vez, cria a coleção temporária `BUSCA_COLECAO_DE_MEDIDA` com os índices ligados (cobrados enquanto existirem) e a apaga no fim, com os índices e os objetos dentro, mesmo se a medição falhar. O comando sai com erro se uma das duas conferências falhar. Cada índice ANN nasce com uma réplica só (`REPLICAS_DO_INDICE`, em `api/agent_retrieval.py`), no modo `PERFORMANCE_OPTIMIZED`; sem isso o serviço usaria de 2 a 5.

- `make comparar-leituras REFERENCIA=<json> NOVA=<json> [OPCOES="--lidos-nova N --segundos-nova S --segundos-referencia S"]` (#233, sem nuvem): compara duas leituras da tela do mesmo vídeo, a de referência e a nova (`<job>/leitura_da_tela.json` do bucket de aceitos, baixada com `gcloud storage cp`). Mostra os textos distintos que só um dos lados achou, as aparições cujo início ou fim mudou mais de 1 s (ou que a nova não achou) e quantos quadros cada leitura leu e o tempo. Os quadros lidos e o tempo não estão no formato da leitura: saem do log do Job (`Leitura da tela: N quadros lidos e M pulados em S s`), e entram pelas opções; a referência, de um quadro por segundo, leu todos. A referência do programa FAMA (Job `98502242109e4280b7073b07a3ebe573`) não pode ser apagada nem sobrescrita antes da medição: a leitura nova vai num Job novo (reprocessar a etapa regrava a leitura do mesmo Job, então copie a de referência antes).
- **Leitura da tela só quando a imagem muda (#233).** O OCR compara cada quadro de 1 s com o último quadro lido (reduzido a 128x72 em tons de cinza, em seis faixas horizontais de oito blocos) e só lê de novo se algum bloco mudou, em média, mais que `LIMIAR_DE_MUDANCA` (variável `limiar_de_mudanca_do_ocr` do Terraform, padrão 3, de 0 a 255; 0 lê todo quadro). O quadro que não mudou repete a leitura do anterior, e o resultado segue com um quadro por segundo. O detector do OCR em CPU vem do `ARG DETECTOR` do Dockerfile (`DETECTOR_OCR_CPU` no `docker-bake.hcl`): `PP-OCRv5_server_det` (padrão) ou `PP-OCRv5_mobile_det`; a imagem com GPU fica com o `server`.
- `make reindexar [JOB=<id>]`: apaga e regrava na busca a Decupagem entregue (com as Correções em vigor) de um Job, ou de todos os concluídos; repetir dá o mesmo resultado. O estado (`pendente`, `indexado` ou `falhou`, com o horário) fica em `indexacao` no `GET /v1/jobs/{id}`. A indexação roda ao fim da análise (Job `mam-indexacao`, depois da etapa `inventario_de_objetos`) e a cada Correção que passa a valer (a pendente só entra quando o Curador aprova); uma falha dela nunca muda o `estado` do Job.

**Ligar o índice do quadro-chave no dev (#268).** Ordem: (1) `terraform apply` (a variável `indice_do_quadro_ligado` já é `true`; o `mam-indexacao` e o serviço web já têm `roles/aiplatform.user` e leem os quadros); (2) `make criar-colecao-da-busca`, que cria o índice do quadro sem recriar a coleção; (3) `make reindexar` sem `JOB`, que recalcula o vetor do quadro de todos os planos. Sem o passo 3 os vídeos antigos seguem sem vetor de quadro.

**Reindexar os vídeos que já estão no dev depois do inventário de objetos (#245).** O registro de cada plano passa a levar o inventário inteiro, os objetos de destaque 3 ganham registro próprio e os registros ganham o campo `destaque`, que pesa na ordem (3% por nível acima de 1: +3% no destaque 2, +6% no 3). Vídeo a vídeo:

- Vídeo **sem inventário** (analisado antes do #244): no Visualizador, "Reprocessar…" a partir de `inventario_de_objetos`, que roda o inventário e depois a indexação. No dev são poucos vídeos; se forem muitos, um laço pela rota do reprocessar (#147).
- Vídeo **com inventário, mas indexado antes do #245**: `make reindexar` sem `JOB`, que reindexa todos os concluídos.
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
export PRECOS_DOS_MODELOS="gemini-3.8-flash=1.5:7.5"   # modelo=entrada:saída, US$ por milhão de tokens
make passada-de-comparacao JOB=<id do Job> MODELO=gemini-3.8-flash   # nome curto, sem barra; JANELAS_EM_PARALELO=4 acelera
```

- A análise é a do Job (janelas, consolidação, identificação, com a transcrição e a leitura da tela que ele já tem), sem escalonamento: o modelo pedido faz todas as janelas. Dá para repetir com outros modelos; cada rodada é uma passada nova.
- A passada vai para `<job>/passadas/<data>-<modelo>.json` no bucket das decupagens, com o modelo, a data, os tokens e o custo (pelos preços do `PRECOS_DOS_MODELOS`) e os segundos de `janelas`, `consolidacao` e `identificacao`. Não é indexada, não aparece no Acervo nem na busca, não recebe correções, não dispara webhook, e a Decupagem do Job não é regravada. A identificação lê o catálogo de pessoas, mas não acrescenta nome nele.
- Cada chamada ao Gemini leva o rótulo `etapa=passada_de_comparacao`, para o faturamento separar o custo.
- Leitura: `GET /v1/jobs/{id}/passadas` (resumos) e `GET /v1/jobs/{id}/passadas/{passada}` (com a decupagem), com `decupagem.ver`.
- Custo por hora de vídeo, pelas premissas do `docs/Plano_MAM.md` (Standard, 1 fps, ~60 mil tokens de saída por hora): ~US$ 1,14 no 3.8 Flash, ~US$ 1,24 no 3.5 Flash e ~US$ 0,30 no 3.5 Flash-Lite. Um programa de 2 h custa, então, uns US$ 2,30 no 3.8 Flash. O custo real da rodada sai impresso no fim do comando e fica na passada. As chamadas com vídeo saem com os cabeçalhos do Flex do `TransporteVertex` (o ADR 0004 pede Standard, e o código ainda não seguiu); ponha em `PRECOS_DOS_MODELOS` o preço do modo em que elas de fato saem, e leia as contas acima como teto.


### Comparar a decupagem com a passada (#248)

```
make comparar-passadas JOB=<id> [PASSADA=<id>] [MODELO=<modelo>]   # sem PASSADA, a última (do MODELO, se vier)
make comparar-passadas JOBS=<id>,<id>,...                            # soma por requisito, a última passada de cada Job
```

- Grava `comparacao-passadas/<job>-<passada>.md` e `.json` (em `PASTA=`; vários Jobs viram `piloto-<data>`). O lado A é a decupagem do Job e o B, a passada.
- Por requisito (famosos, menções, pautas, B-roll em planos limpos e em descrições, comerciais): contagens, itens só de um lado e itens dos dois com diferença de nome, tipo ou marca, ou de tempo acima da tolerância de 2 s. O pareamento é o do `api/comparador.py`. Timecode: erro médio, p95 e quantos pares (inclusive os de nome trocado) passam da tolerância.
- Custo por hora de vídeo e tempo (por etapa e total) dos dois lados. O preço vem de `PRECOS_DOS_MODELOS` e a data da tabela consultada, de `DATA_DA_TABELA_DE_PRECOS`. O Job não guarda os tokens que gastou: passe-os em `TOKENS_DO_JOB=<job>=<entrada>:<saida>,...` (e o modelo em `MODELO_DO_JOB`, o `MODELO` de `api/gemini.py` por padrão); sem eles, o custo do lado do Job sai "n/d", e a soma de vários Jobs também.

## Cassete do Gemini

O teste de contrato com o Gemini (`api/tests/test_cassete.py`) roda em todo `make verificar`, sem rede: passa por `analisar` o texto de uma resposta real gravada em `api/tests/cassetes/gemini_sintetico.json` e confere o esquema da decupagem e os invariantes de tempo, nunca o texto exato. O cassete guarda só o modelo, a versão exata que a Vertex informou (`modelVersion`), o bloco `video`, o texto da resposta e o `instrucao_sha256` (SHA-256 da `INSTRUCAO` de `api/gemini.py`), sem cabeçalhos nem credenciais. Mudar uma letra da `INSTRUCAO` muda o hash e derruba o contrato até regravar, com a mensagem de rodar `make gravar-cassetes`; o hash não cobre os perfis e as seções que `instrucao()` encaixa nela. O cassete de hoje foi gravado antes do hash, e essa checagem fica pulada até a regravação do #229. Se a versão gravada for diferente da fixada em `VERSAO_DO_MODELO` (`api/gemini.py`), o contrato falha: o Google trocou o modelo por baixo do nome, e alguém precisa conferir a resposta e atualizar a constante. O teste só percebe ao regravar; entre gravações, nada consulta a Vertex.

Para regravar (a cada troca de modelo, de esquema ou de instrução), com o dev no ar e as credenciais ADC de uma conta com acesso ao projeto (`gcloud auth application-default login`):

```sh
make gravar-cassetes
```

Ele gera com o ffmpeg um clipe sintético de 30 s, passa pelo validador, sobe o proxy no bucket de clipes-ouro, sob `cassetes/sintetico.mp4`, e faz a chamada real ao modelo fixado em `MODELO`, no `api/gemini.py`. O clipe continua sintético, nunca um dos clipes-ouro: só mora no mesmo bucket, fora do bucket de aceitos, onde só o Job de validação grava. O nome do bucket vem do `output` `bucket_clipes_ouro` do Terraform (ou de `BUCKET_CLIPES_OURO` no ambiente). Se o teste do modelo falhar depois de trocar `MODELO`, é este o comando.

## Loop AFK

`scripts/afk/rodar.sh` implementa os tickets `ready-for-agent` sozinho, sem perguntas, um ticket por iteração. Cada iteração roda dois `claude -p` novos, cada um com o contexto vazio: um implementa o ticket e o outro revisa o que foi commitado. Tudo roda num contêiner Docker sem credencial de nuvem e num clone separado (`../mam-prk-redetv-afk`), para a pasta principal continuar livre. O estado entre as iterações fica em `.afk/` dentro do clone. Só o clone entra no contêiner: o repositório principal fica de fora, e os commits voltam para ele por um `git bundle`, que o `git fetch` confere objeto por objeto. No fim, o script faz um push só, no branch `afk/<data-hora>`, e abre um PR em rascunho com `Closes #N` de cada ticket feito. Se o agente mudou qualquer arquivo fora de `api/` e `web/src/` (por exemplo `.github/workflows/`, `.githooks/`, `Makefile`, lockfiles, configs do `web/`, `AGENTS.md` ou `docs/`), o corpo do PR abre com um aviso em destaque listando esses arquivos. O CI do PR roda o `ci.yml` e o `make verificar` do próprio branch, os hooks de `.githooks/` rodam no Mac e `AGENTS.md` e afins guiam os próximos agentes, então revise antes do merge. O merge sai com `make mesclar-afk` e nunca com o CI vermelho.

Arquivos em `scripts/afk/`: `prompt.md` (o texto que o agente implementador recebe; edite à vontade), `revisao.md` (o do revisor), `loop.sh` (o loop, dentro do contêiner), `rodar.sh` (o Mac: Keychain, clone, Docker, bundle, push e PR), `mesclar.sh` (o `make mesclar-afk`), `hook-contexto.sh` (o aviso de contexto, ligado em `.claude/settings.json` e inerte fora do loop), `Dockerfile` e `testes.sh`.

### Configuração, uma vez só

1. **Token do Claude Code.** Gere com `claude setup-token` e guarde no Keychain (o comando pede o valor):

   ```sh
   security add-generic-password -a "$USER" -s afk-claude -w
   ```

2. **Dois tokens do GitHub**, ambos *fine-grained* e com acesso só a `RedeTVRevolution/mam-prk-redetv-` (a organização pode precisar aprovar):
   - `afk-github-agente`, que vai para o contêiner: Issues leitura e escrita, Contents só leitura. Sem escrita em Contents, o agente não consegue fazer push.
   - `afk-github-script`, que fica no Mac: Contents, Pull requests e Workflows leitura e escrita. Serve para o fetch, o push final e o PR. Sem Workflows em *Read and write*, o GitHub recusa o push de um branch em que o agente mexeu em `.github/workflows/`.

   ```sh
   security add-generic-password -a "$USER" -s afk-github-agente -w
   security add-generic-password -a "$USER" -s afk-github-script -w
   ```

3. **Label `afk-feito`**, que o script põe em cada ticket terminado:

   ```sh
   gh label create afk-feito --color 0E8A16 --description "Feito pelo loop AFK, aguardando merge"
   ```

4. **Docker Desktop** aberto. A imagem `mam-afk` é construída na primeira execução. O `rodar.sh` também sobe os emuladores do Firestore e do Storage, nas versões do `ci.yml`, e o contêiner do agente entra na rede deles. Assim o `make verificar` do loop roda os testes de nuvem em vez de pulá-los. O `loop.sh` se recusa a começar sem `FIRESTORE_EMULATOR_HOST` e `STORAGE_EMULATOR_HOST`.
5. **Plugin `mattpocock-skills`** instalado no Claude Code do Mac. O script monta a pasta dele no contêiner, só leitura.

### Como rodar

O clone sai da `origin/main`, então este loop só funciona depois do merge dele na `main`. Comece com uma iteração e confira o resultado:

```sh
scripts/afk/rodar.sh 1
```

Veja as notas em `.afk/progresso-afk-<data-hora>.md`, uma cópia na pasta principal, o `git log afk/<data-hora>` e o PR. Inspecione pela pasta principal e não rode `git` dentro do clone do agente: o `.git` dele, inclusive `config` e hooks, ficou sob controle do agente. A execução seguinte apaga e recria o clone. Depois, aumente o número de iterações, por exemplo `scripts/afk/rodar.sh 10`.

Para mesclar o lote:

```sh
make mesclar-afk
```

Ele pega o PR aberto mais recente de um branch `afk/*` deste repositório, aberto pelo seu login (PR de fork não entra; com `BRANCH=afk/...`, o daquele branch, que é o que o `rodar.sh` passa). Se o branch existe na pasta principal, o PR tem de apontar para a mesma ponta. Depois espera o CI terminar e, só se todas as checagens passarem, tira o PR do rascunho, faz o merge com squash e apaga o branch no GitHub e no Mac. Depois atualiza a `main` e apaga os branches locais `afk/*` cuja ponta é a de um PR mesclado; os `-bloqueado-N` e `-parcial-N` ficam. Se o CI falhar, ele para sem mesclar e mostra o log do job que falhou. Usa o login do `gh` e do `git` deste Mac, não os tokens do Keychain. Os comandos `git` dele rodam com os hooks desligados, porque depois do merge `.githooks/` pode ter código do agente.

Cada iteração:

1. Pega o ticket: o que ficou parcial na iteração anterior ou o menor `ready-for-agent` aberto, sem `afk-feito`, com todos os bloqueios resolvidos (dependências nativas e linha `Bloqueado por: #N`). Um bloqueio está resolvido se o bloqueador está fechado ou tem `afk-feito`.
2. Roda o implementador com `prompt.md`: `mattpocock-skills:tdd`, `make verificar` e commit. Descarta o que não foi commitado e lê o fim da resposta (`<ticket>N</ticket>` e `<status>…</status>`).
3. Se o status é `feito`, roda o revisor com `revisao.md`: um `claude -p` novo, com o modelo de `AFK_MODELO_REVISOR`, que roda `mattpocock-skills:code-review` contra o ticket a partir do commit de antes dele e commita as correções. Descarta de novo o que não foi commitado. O revisor termina com `<revisao>feita</revisao>` ou `<revisao>erro</revisao>`; sem um dos dois, ou cortado, a iteração conta como falha e a próxima retoma o ticket.
4. Roda `make verificar`, já depois da revisão. Se falhar, desfaz os commits da iteração, os do implementador e os do revisor.
5. Age conforme o status:
   - `feito` (e revisão `feita`): põe `afk-feito` no ticket.
   - `parcial`: a próxima iteração continua o ticket.
   - `bloqueado`: o agente comentou a pergunta no ticket e trocou a label para `ready-for-human`. O script tira o trabalho do branch, guarda num branch local `<branch>-bloqueado-N` e segue.
   - `erro`, do implementador ou do revisor: problema do ambiente, como uma skill ausente. O loop para, e o trabalho do ticket sai do branch do PR para `<branch>-parcial-N`.

O loop para sozinho quando a fila esvazia, depois do número de iterações pedido, depois de 3 falhas seguidas (portão vermelho ou iteração sem sinal válido) ou se houver um ticket aberto com `afk-feito`, o que indica um PR anterior sem merge. Um ticket com 3 parciais seguidas volta para humano como um bloqueado. Um ticket em andamento quando o loop para sai do branch do PR e fica num branch local `<branch>-parcial-N`.

### Variáveis

| Variável | Padrão | Para quê |
|---|---|---|
| `AFK_AVISO_TOKENS` | 120000 | O hook manda o implementador comitar o que está verde, anotar o que falta e sair como `parcial`. O revisor não recebe o aviso, só o corte |
| `AFK_CORTE_TOKENS` | 140000 | O script mata a iteração e descarta o que não foi commitado |
| `AFK_MAX_TURNOS` | 300 | `--max-turns` de cada iteração |
| `AFK_MAX_FALHAS` | 3 | Falhas seguidas antes de parar |
| `AFK_MAX_PARCIAIS` | 3 | Parciais seguidas de um ticket antes de devolvê-lo para humano |
| `AFK_MODELO` | padrão do Claude Code | `--model` do implementador |
| `AFK_MODELO_REVISOR` | opus | `--model` do revisor |
| `AFK_AUTO_MERGE` | 0 | Com 1, o `rodar.sh` roda `make mesclar-afk` depois de abrir o PR, só quando o agente mudou apenas `api/` e `web/src/`; com qualquer outro arquivo (a lista do aviso no PR), o merge fica para você |

O tamanho do contexto é a soma de `input_tokens`, `cache_read_input_tokens` e `cache_creation_input_tokens` da última resposta da conversa principal (sem subagentes).

### Testes

```sh
make testar-afk
```

Roda o `shellcheck` e o `testes.sh`, que exercita o loop com `claude` e `gh` falsos, sem Docker e sem rede: ticket feito e revisado num `claude -p` à parte, estouro de contexto, ticket bloqueado, verificação falhando depois do commit, revisão que quebra a verificação, revisão sem sinal, revisão com erro, parciais seguidas, fila sem tickets elegíveis, PR anterior sem merge, loop sem as variáveis dos emuladores e o hook abaixo e acima do aviso. O CI roda o mesmo alvo.
