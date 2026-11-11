# Infra (Terraform)

Um módulo (`modulos/mam`, #292) e duas chamadas dele, cada uma com variáveis e estado próprios:

| Ambiente | Pasta | Estado (prefixo no bucket do projeto) | Situação |
| --- | --- | --- | --- |
| dev | `infra/` | `dev` | no ar; `make deploy-dev` e o CD aplicam |
| prod | `infra/ambientes/prod/` | `prod` | só `validate` no CI; nada criado (#293) |

Nenhum valor real de projeto vai no código: cada ambiente tem um `exemplo.tfvars` com nomes de mentira, e o wizard grava os verdadeiros. O bucket do estado entra por `-backend-config="bucket=..."`, um por projeto.

## O que é igual, o que muda e o que ainda depende de decisão

| Assunto | Igual nos dois | Muda por ambiente | Depende de decisão |
| --- | --- | --- | --- |
| Recursos | todos os de `modulos/mam` | nada | — |
| Projeto, região, nomes de bucket | a regra de nomes (`<projeto>-<região sem hífen>-<sufixo>`) | projeto e região (variáveis) | — (sem organização, #296 e [ADR 0016](../docs/adr/0016-sem-organizacao-dev-vira-producao.md)) |
| Estado | bucket GCS, um por projeto | prefixo (`dev`, `prod`) | — |
| Imagens | um digest por componente | o digest publicado em cada projeto | quando prod recebe imagem (promoção a partir do dev) |
| Tamanhos e limites | os padrões do módulo | `janelas_em_paralelo`, `espera_gpu_minutos`, `limite_de_falhas_por_etapa`, `builds_de_imagem_guardados` (builds de cada imagem que o Artifact Registry guarda, padrão 2) (prod igual ao dev até o piloto medir) | os valores finais de prod, depois do piloto |
| Domínio e balanceador | o código (`modulos/mam/balanceador.tf`) | `dominio` (vazio: sem balanceador) | o domínio de cada ambiente |
| Identity Platform | `import` da config do projeto | o projeto importado (`var.projeto`) | — |
| Aplicação | — | só o dev aplica; sem CD para prod | quando criar os ambientes |

## O que precisa existir antes de cada ambiente

Lista para o wizard (uma vez por projeto, igual ao `scripts/wizard-gcp-dev.sh` do dev):

- [ ] O projeto do GCP, com faturamento, fora de organização ([ADR 0016](../docs/adr/0016-sem-organizacao-dev-vira-producao.md)).
- [ ] A conta `mam-terraform` no projeto, com os papéis de `PAPEIS_DA_TERRAFORM` no wizard (lista abaixo).
- [ ] O bucket do estado do Terraform, criado antes do primeiro `init`.
- [ ] O Identity Platform inicializado pelo Owner (etapa 7 do wizard), antes do primeiro apply.
- [ ] Os e-mails dos administradores de emergência e as imagens publicadas no Artifact Registry do projeto.

## Domínio e balanceador (#294)

Com `dominio` vazio (o padrão), nada do balanceador é criado e o endereço segue o `run.app`. Com `dominio` preenchido, o módulo cria o balanceador HTTPS externo global (IP, NEG serverless para o `mam-web`, certificado gerenciado e redirecionamento de HTTP para HTTPS), o Cloud Run passa a aceitar só o tráfego do balanceador e o domínio entra no CORS da quarentena e nos domínios autorizados do login. O Cloud Armor vem no #295.

Depois do `apply`:

1. Pegue o endereço: `terraform output ip_do_balanceador`.
2. Crie no DNS do domínio um registro A (`dominio` → esse IP).
3. Espere o certificado: o Google só o emite depois que o DNS aponta para o IP; costuma levar de 15 minutos a 1 hora e pode chegar a 24 horas. Até lá o HTTPS falha no handshake. Acompanhe com `gcloud compute ssl-certificates list` (`ACTIVE`).

Custo mensal (estimativa pela tabela de preços do Google, a confirmar na calculadora): duas regras de encaminhamento (80 e 443) a cerca de US$ 0,025/hora cada, ~US$ 36; mais ~US$ 0,008 a 0,012 por GB trafegado. IP reservado em uso e certificado gerenciado não custam. O upload e o player vão direto ao Storage, fora do balanceador, então o tráfego dele é só o front e a API.

Ao ligar o balanceador num ambiente que já tem login, `authorized_domains` passa a ser a lista padrão (`localhost`, `<projeto>.firebaseapp.com`, `<projeto>.web.app`) mais o domínio: qualquer outro domínio posto à mão some.

## Papéis das contas em cada projeto

A `mam-terraform` recebe do wizard os mesmos papéis que tem no dev (`PAPEIS_DA_TERRAFORM` em `scripts/wizard-gcp-dev.sh`, onde cada um diz para que serve), já com os que os tickets novos acrescentaram:

- `roles/resourcemanager.projectIamAdmin`
- `roles/serviceusage.serviceUsageAdmin`
- `roles/iam.serviceAccountAdmin`
- `roles/iam.serviceAccountUser`
- `roles/run.admin`
- `roles/storage.admin`
- `roles/artifactregistry.admin`
- `roles/datastore.owner`
- `roles/eventarc.admin`
- `roles/workflows.admin`
- `roles/identityplatform.admin`
- `roles/monitoring.editor`
- `roles/logging.configWriter`
- `roles/compute.networkAdmin`
- `roles/iam.workloadIdentityPoolAdmin`
- `roles/cloudbuild.builds.editor`
- `roles/secretmanager.admin`
- `roles/cloudscheduler.admin`
- `roles/bigquery.admin`
- `roles/cloudkms.admin`
- `roles/pubsub.admin`
- `roles/compute.loadBalancerAdmin`
- `roles/certificatemanager.owner`
- `roles/compute.securityAdmin`
- `roles/iam.roleAdmin`
- `roles/modelarmor.admin`

A `mam-build` não é pré-requisito: o próprio módulo a cria (`google_service_account.mam["build"]`) e lhe dá os papéis no `apply`, os mesmos do dev:

- `roles/logging.logWriter` no projeto;
- `roles/storage.objectViewer` no bucket de fontes;
- `roles/artifactregistry.writer` nos repositórios `mam` e `mam-gpu`.

Validar sem credencial: `terraform -chdir=infra/ambientes/prod init -backend=false && terraform -chdir=infra/ambientes/prod validate` (o CI faz isso nos dois).

## Cloud Armor (#295)

Com o balanceador ligado (`dominio` preenchido), o módulo cria a política `mam-web` no serviço de back-end (`modulos/mam/cloud_armor.tf`). Sem `dominio`, nada disso existe. A conta `mam-terraform` precisa de `roles/compute.securityAdmin` (já no wizard).

- **WAF** (SQLi, XSS, LFI, RCE e scanners, regras `v33-stable`, sensibilidade 1): nasce em **prévia** (`waf_ativo = false`): só registra no log do balanceador o que bloquearia. Olhe os logs e ligue com `waf_ativo = true` (403).
- **Limite por IP**: `limite_de_requisicoes_por_ip` (padrão 600 por minuto); acima, 429. Um valor só para todas as rotas: as de envio e busca vão direto ao Storage ou são caras no lado do servidor, e separar fica para quando os logs mostrarem necessidade.
- **IPs da RedeTV**: `ips_da_redetv` (lista de IPs ou CIDRs, até 10: limite do Google por regra). Vazia (o padrão, e o dev): nenhuma regra de IP e todos passam. Preenchida: só esses IPs passam, **em todas as rotas, as `/v1` dos sistemas inclusive** (decisão: os sistemas da RedeTV chamam de dentro da rede; se algum chamar de fora, o IP dele entra na lista). O limite por IP passa a casar só com a lista, e quem está fora cai na regra padrão (403): o Cloud Armor para na primeira regra que casa, e o limite deixa passar quem está abaixo dele. Com a lista preenchida, o teste do `/v1/health` no fim do `deploy-dev.sh` só passa se a máquina do CD estiver na lista.

Custo mensal (estimativa pela tabela do Google, a confirmar: US$): política ~US$ 5, mais ~US$ 1 por regra (7 regras, com ou sem lista, ~US$ 12 no total) e ~US$ 0,75 por milhão de requisições avaliadas. A regra de limite por IP é cobrada como as demais.

## Chave MAC do Cloud KMS (#272)

O hash das chaves de API dos sistemas legados (E7) sai de uma chave MAC `HMAC_SHA256` do Cloud KMS, em `us-east4` (ADR 0019): key ring `mam`, chave `chaves-de-api` (`modulos/mam/chave_mac.tf`). O Terraform a entrega ao serviço em `KMS_CHAVE_MAC`; com ela, `api/main.py` usa o KMS (`api/mac_kms.py`), e sem ela, o `MacSimulado` de `MAC_SIMULADO_CHAVE` (máquina local, emulador e testes). A `mam-terraform` precisa de `roles/cloudkms.admin` (já no wizard); a `mam-web` recebe `cloudkms.signerVerifier` e `cloudkms.viewer` só nessa chave (assinar, verificar e listar as versões para achar a atual).

- **Emitir chave de API**: `make emitir-chave` precisa de `KMS_CHAVE_MAC` no ambiente (`terraform -chdir=infra output -raw chave_mac_kms`; no prod, `-chdir=infra/ambientes/prod`) e de credencial de quem pode assinar na chave (o Owner já pode).
- **Rotação manual**: crie uma versão nova com `gcloud kms keys versions create --key=chaves-de-api --keyring=mam --location=<região>`. A API passa a assinar com a versão ativa mais alta em até 5 minutos, e cada chave de API troca de versão sozinha no primeiro uso depois disso (o registro guarda a versão). Desligue a versão antiga (`gcloud kms keys versions disable`) só depois de as chaves em uso terem passado para a nova; chave que ainda aponte para versão desligada deixa de valer.
- **Key ring e chave não se apagam**: o `destroy` só agenda a destruição das versões.
- **Migração do dev**: as chaves emitidas com o simulado deixam de valer no primeiro deploy com o KMS (o HMAC não bate). Cada sistema precisa de chave nova: `make emitir-chave SISTEMA=... ESCOPOS=...` e `make revogar-chave ID=...` para as antigas.

## Pub/Sub dos webhooks (#273)

O fim de um Job (`concluido` ou `falhou`) vira uma mensagem no tópico `mam-eventos-do-job` (`modulos/mam/eventos.tf`, `api/eventos_do_job.py`). A assinatura push `mam-entrega-do-webhook` chama `POST /interno/webhook` na `mam-web` com o token OIDC da conta `mam-webhook-push`; a API entrega o webhook com o mesmo `X-Webhook-Id` em toda tentativa. Destino fora do ar responde 503 e o Pub/Sub tenta de novo (10 s a 600 s de espera); depois de 10 tentativas a mensagem vai para `mam-eventos-do-job-mortos`, que tem assinatura própria para guardar o que desistiu por 7 dias. A `mam-terraform` precisa de `roles/pubsub.admin` (já no wizard). O tópico sai no output `pubsub_topico_eventos`. O levantamento do que ainda falta está em `docs/levantamento-api-no-ar.md`.

Os eventos de uso (login, envio, fim de processamento, busca, correção e chamada de API) vão ao tópico `mam-eventos-de-uso` (`modulos/mam/eventos_de_uso.tf`, esquema em `evento_de_uso.proto`, `api/eventos_de_uso.py`). A assinatura `mam-eventos-de-uso-bigquery` os grava na tabela `eventos_de_uso` do dataset das decupagens. Quem publica (web, validação, transcrição, OCR e análise) recebe `roles/pubsub.publisher` só no tópico, e o agente de serviço do Pub/Sub, `dataEditor` e `metadataViewer` só na tabela. Nenhum papel novo para a `mam-terraform`. O tópico sai no output `pubsub_topico_uso`.

Os resumos de uso (#280, `modulos/mam/resumos_de_uso.tf` e `.sql`) são quatro tabelas do dataset das decupagens que uma consulta agendada do BigQuery (Data Transfer, a cada hora, conta `mam-resumos-de-uso` com `jobUser` e `dataEditor` no dataset) refaz a partir dos eventos; o painel lê só elas (a conta da web já lê o dataset). Escolhida no lugar da visão materializada, que não aceita `COUNT(DISTINCT)`, função de janela nem a junção com os momentos. Custo estimado no começo: ~300 GB de consulta por mês, contra 1 TiB grátis; mas cada rodada lê a tabela de momentos inteira (duas colunas), e com uns 5 milhões de momentos copiados passa de 1 TB por mês (o comentário de `resumos_de_uso.tf` traz a conta e a saída). Não há tabela de total geral: o total é a soma de `uso_por_dia`, e os usuários ativos de um período contam os distintos de `uso_por_dia_e_usuario`. Liga a API `bigquerydatatransfer.googleapis.com`. Nenhum papel novo para a `mam-terraform` (o `bigquery.admin` cobre). Output `bigquery_tabelas_do_painel`. A web recebe os nomes pelas variáveis `PAINEL_TABELA_*` (#282), e as rotas `/v1/painel/...` leem só essas tabelas.

## Chaves de idempotência (#274)

O `POST /v1/jobs` aceita `Idempotency-Key`. A reserva da chave é um documento da coleção `chaves_de_idempotencia` (`api/idempotencia.py`), e a política de TTL de `modulos/mam/idempotencia.tf` apaga o documento 48 h depois (`expira_em`). O TTL do Firestore não é imediato (pode levar até um dia a mais), por isso a API trata a reserva vencida como inexistente. O campo não tem índice próprio.

## Listas da busca paginada (#426)

A 1ª página da busca grava o resultado inteiro, em ordem, num documento da coleção `listas_da_busca` (`api/busca.py`); as páginas seguintes o leem pelo cursor. A política de TTL de `modulos/mam/listas_da_busca.tf` apaga o documento depois do `expira_em` (15 min), e a API trata a lista vencida como inexistente. O campo não tem índice próprio. Nenhum papel novo: a conta da web já tem `roles/datastore.user`, e o `roles/datastore.owner` da `mam-terraform` cobre a política de TTL.

## Recuperação do Firestore (#355)

O Firestore guarda Jobs, Correções, catálogo, papéis e auditoria. Em `modulos/mam/main.tf` o banco liga a recuperação a um ponto no tempo (PITR, 7 dias), e `modulos/mam/firestore_recuperacao.tf` cria as duas agendas de backup que o Firestore aceita por banco: **diária, guarda 7 dias**, e **semanal (domingo), guarda 14 semanas** (o teto da documentação). Nenhum papel novo para a `mam-terraform`: o `roles/datastore.owner` do wizard cobre as agendas e a mudança do PITR (mudança no lugar, o banco não é recriado).

Conferir depois do `publicar`:

```
gcloud firestore databases describe --database="(default)" | grep pointInTimeRecoveryEnablement   # POINT_IN_TIME_RECOVERY_ENABLED
gcloud firestore backups schedules list --database="(default)"                                     # as duas agendas
```

**Restaurar de um backup** (volta sempre para um **banco novo**, nunca sobrescreve o atual):

```
gcloud firestore backups list --location=<REGIAO>
gcloud firestore databases restore --source-backup=projects/<PROJETO>/locations/<REGIAO>/backups/<ID> --destination-database=<BANCO_NOVO>
```

Depois confira os dados no banco novo e, se for trocar, copie o que faltar para o `(default)` (por exportação e importação) ou aponte a aplicação para o banco novo. O `(default)` tem proteção contra exclusão; o banco novo nasce sem ela.

**Restaurar de um ponto no tempo** (últimos 7 dias, em minutos inteiros): ler ou exportar o estado daquele momento, sem tocar no banco atual.

```
gcloud firestore export gs://<BUCKET>/<PASTA> --database="(default)" --snapshot-time=2026-11-04T12:00:00Z
gcloud firestore databases create --database=<BANCO_NOVO> --location=<REGIAO>
gcloud firestore import gs://<BUCKET>/<PASTA> --database=<BANCO_NOVO>
```

O `import` pede um banco que já exista, por isso o `create` antes; com a pasta dada no `export`, a exportação fica direto nela, e o `import` recebe a mesma pasta.

Para clonar o banco inteiro naquele ponto, `gcloud firestore databases clone --source-database=projects/<PROJETO>/databases/(default) --snapshot-time=... --destination-database=<BANCO_NOVO>`. O bucket de exportação não é o do Terraform: use um temporário e apague depois. Ensaiar uma restauração no dev ainda não foi feito.

**Custo estimado**: o PITR e os backups cobram armazenamento por GiB-mês (PITR, os dados mais as versões dos últimos 7 dias; cada backup, o tamanho do banco naquele dia, e há até 7 diários e 14 semanais guardados ao mesmo tempo, 21 cópias no pior caso, mais as leituras da restauração quando houver). Para um banco de poucos GiB, como o do dev, isso fica em centavos a poucos dólares por mês; o custo cresce linear com o tamanho do banco. Conferir o tamanho real e o valor no faturamento (aba Custo do painel) depois do primeiro mês.

## Momentos por ano no BigQuery (#356)

A tabela de momentos em uso é `momentos_por_ano` (`modulos/mam/momentos_por_ano.tf`), dividida por `YEAR` em `data_de_exibicao`: a por dia chegaria ao teto de 10.000 partições com 25 anos de acervo. Serviços, Jobs e o output `bigquery_tabela` apontam para ela. A antiga `momentos` foi apagada em dois applies (#567). Nenhum papel novo (o IAM é por dataset).

Passos humanos depois do `publicar`:

1. `make copiar-para-bigquery` preenche a nova a partir das decupagens. Até rodar, os relatórios do dev saem vazios.
2. `bq show <dataset>.momentos_por_ano` deve mostrar `YEAR`; o relatório de tempo de tela dá os mesmos números de antes.
3. Apagar a antiga (#567, feito): apply 1 com `PERMITIR_DESTRUICAO=sim` tira só a tabela; confira na nuvem que sumiu; apply 2, antes das 06:00Z seguintes, tira a variável do `mam-web` e da purga, o `moved` e o endereço do wizard. Entre os dois, a purga falha e tenta de novo no dia seguinte.

## Programas no Firestore (#338)

Os programas saíram do `api/programas.toml` e viraram a coleção `programas` do Firestore, editada na aba Programas da administração. As contas que leem a coleção já têm `roles/datastore.user`; nenhum papel novo.

Passo humano logo depois do `publicar`, antes de qualquer envio com programa: `make carregar-programas` (lê `docs/migracao/programas-2026-11.toml`). Até rodar, a lista do envio fica vazia, envio com `programa` recebe 422 e os Jobs analisam sem o perfil e sem as pessoas do programa. Rodar de novo não duplica.

## Tudo em us-east4 (#537, ADR 0019)

A região do dev e do prod é `us-east4` (`GCP_REGION`, `TF_VAR_regiao`); uma variável só (`regiao`) serve ao que não é a busca nem a GPU. Os nomes que mudaram (buckets, datasets, banco de segurança) levam `useast4` e saem pelos outputs `buckets`, `datasets_bigquery`, `banco_firestore`, `banco_de_seguranca` e `regiao`.

Quem já tem o ambiente em São Paulo não aplica direto: o plan recriaria tudo e destruiria o que existe lá. Rode o wizard da troca (`scripts/wizard-migracao-us-east4.sh`, #538), que tira do estado os endereços de `infra/migracao-us-east4/enderecos-recriados.txt`, publica, copia os dados e só então apaga São Paulo. O `scripts/aplicar-sem-destruir.sh` continua recusando qualquer plan com `delete`, e o CD do GitHub fica vermelho (sem aplicar nada) até a variável `GCP_REGION` do repositório passar a `us-east4` e o wizard ter tirado os endereços do estado. Um recurso regional novo no módulo entra nessa lista; o teste `api/tests/test_infra_migracao_us_east4.py` cobra.
