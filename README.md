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

O hook de pre-commit recusa o commit se o gitleaks achar um segredo nos arquivos preparados ou se o gitleaks não estiver instalado. O CI roda `make verificar` e o gitleaks em todo PR.

Os testes do validador usam o ffmpeg de verdade. Sem ffmpeg na máquina, o `make verificar` os pula; `make testar-na-imagem` (pede o Docker) os roda dentro da imagem do Job de validação, com o ffmpeg da produção, e é assim que o CI os roda. O contêiner do loop AFK fixa a mesma versão, no `ARG FFMPEG` do `scripts/afk/Dockerfile`, então o `make verificar` de lá também os roda com ela. O próprio `make verificar` falha se as duas versões forem diferentes (`scripts/checar-ffmpeg.sh`).

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
3. sobe o código para o Cloud Build, que constrói as duas imagens (`cloudbuild.yaml`: a do serviço, com a chave web do login, e a do Job de validação) e as envia ao Artifact Registry. O `.gcloudignore` deixa de fora tudo o que o git ignora, inclusive o `.env`;
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

A busca guarda um registro por plano, fala, texto na tela e objeto de cada Decupagem numa coleção do Agent Retrieval, em outra região (ADR 0006). O código (`api/indice_da_busca.py`, `api/agent_retrieval.py`) lê projeto, região, coleção, índice e dimensão das variáveis `GCP_PROJECT_ID`, `BUSCA_REGIAO`, `BUSCA_COLECAO`, `BUSCA_INDICE` e `BUSCA_DIMENSAO`, que o `infra/main.tf` entrega ao serviço. Todo pedido de busca leva o `searchHint.indexHint` do índice ANN.

Os dois alvos abaixo só rodam com credenciais (ADC de quem roda e o `.env`) e ficam fora do CI e do `make verificar`:

- `make criar-colecao-da-busca`: cria a coleção de momentos e o índice ANN, com os campos de filtro declarados (idempotente: o que já existe fica). **Custo:** o índice implantado tem réplicas sempre ligadas, cobradas por hora, mesmo sem consulta (aceito na ADR 0006); veja a tabela de preços do Agent Retrieval, que não está registrada aqui.
- `make medir-busca [CONSULTAS=30] [DIMENSOES="128 256"]`: indexa 3 Decupagens de exemplo (`api/exemplos_da_busca.py`) na coleção, consulta "vestido vermelho da Sabrina Sato" (filtros exatos, texto e significado, fundidos por RRF), confere que só volta o objeto dela, mede o p50 e o p95 de N consultas e imprime a tabela com o total de registros da coleção. Apaga os vídeos de exemplo no fim. Cada dimensão fora da configurada cria uma coleção e um índice temporários (cobrados enquanto existirem) e os apaga no fim. O comando sai com erro se o filtro composto devolver outra coisa.

Os nomes dos campos do corpo REST seguem a documentação de 30/10/2026 e ainda não foram conferidos no ar: o #122 faz isso com a primeira execução do `make medir-busca`.

## Cassete do Gemini

O teste de contrato com o Gemini (`api/tests/test_cassete.py`) roda em todo `make verificar`, sem rede: passa por `analisar` o texto de uma resposta real gravada em `api/tests/cassetes/gemini_sintetico.json` e confere o esquema da decupagem e os invariantes de tempo, nunca o texto exato. O cassete guarda só o modelo, a versão exata que a Vertex informou (`modelVersion`), o bloco `video` e o texto da resposta, sem cabeçalhos nem credenciais. Se a versão gravada for diferente da fixada em `VERSAO_DO_MODELO` (`api/gemini.py`), o contrato falha: o Google trocou o modelo por baixo do nome, e alguém precisa conferir a resposta e atualizar a constante. O teste só percebe ao regravar; entre gravações, nada consulta a Vertex.

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
