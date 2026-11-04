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
| Projeto, região, nomes de bucket | a regra de nomes (`<projeto>-<sufixo>`) | projeto e região (variáveis) | a organização de projetos e pastas (#296) |
| Estado | bucket GCS, um por projeto | prefixo (`dev`, `prod`) | — |
| Imagens | um digest por componente | o digest publicado em cada projeto | quando prod recebe imagem (promoção a partir do dev) |
| Tamanhos e limites | os padrões do módulo | `janelas_em_paralelo`, `espera_gpu_minutos`, `limite_de_buscas_por_video`, `limite_de_falhas_por_etapa` (prod igual ao dev até o piloto medir) | os valores finais de prod, depois do piloto |
| Domínio e balanceador | o código (`modulos/mam/balanceador.tf`) | `dominio` (vazio: sem balanceador) | o domínio de cada ambiente |
| Identity Platform | `import` da config do projeto | o projeto importado (`var.projeto`) | — |
| Aplicação | — | só o dev aplica; sem CD para prod | quando criar os ambientes |

## O que precisa existir antes de cada ambiente

Lista para o wizard (uma vez por projeto, igual ao `scripts/wizard-gcp-dev.sh` do dev):

- [ ] O projeto do GCP, com faturamento (a organização é decisão do #296).
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

O hash das chaves de API dos sistemas legados (E7) sai de uma chave MAC `HMAC_SHA256` do Cloud KMS, em `southamerica-east1`: key ring `mam`, chave `chaves-de-api` (`modulos/mam/chave_mac.tf`). O Terraform a entrega ao serviço em `KMS_CHAVE_MAC`; com ela, `api/main.py` usa o KMS (`api/mac_kms.py`), e sem ela, o `MacSimulado` de `MAC_SIMULADO_CHAVE` (máquina local, emulador e testes). A `mam-terraform` precisa de `roles/cloudkms.admin` (já no wizard); a `mam-web` recebe `cloudkms.signerVerifier` e `cloudkms.viewer` só nessa chave (assinar, verificar e listar as versões para achar a atual).

- **Emitir chave de API**: `make emitir-chave` precisa de `KMS_CHAVE_MAC` no ambiente (`terraform -chdir=infra output -raw chave_mac_kms`; no prod, `-chdir=infra/ambientes/prod`) e de credencial de quem pode assinar na chave (o Owner já pode).
- **Rotação manual**: crie uma versão nova com `gcloud kms keys versions create --key=chaves-de-api --keyring=mam --location=<região>`. A API passa a assinar com a versão ativa mais alta em até 5 minutos, e cada chave de API troca de versão sozinha no primeiro uso depois disso (o registro guarda a versão). Desligue a versão antiga (`gcloud kms keys versions disable`) só depois de as chaves em uso terem passado para a nova; chave que ainda aponte para versão desligada deixa de valer.
- **Key ring e chave não se apagam**: o `destroy` só agenda a destruição das versões.
- **Migração do dev**: as chaves emitidas com o simulado deixam de valer no primeiro deploy com o KMS (o HMAC não bate). Cada sistema precisa de chave nova: `make emitir-chave SISTEMA=... ESCOPOS=...` e `make revogar-chave ID=...` para as antigas.

## Pub/Sub dos webhooks (#273)

O fim de um Job (`concluido` ou `falhou`) vira uma mensagem no tópico `mam-eventos-do-job` (`modulos/mam/eventos.tf`, `api/eventos_do_job.py`). A assinatura push `mam-entrega-do-webhook` chama `POST /interno/webhook` na `mam-web` com o token OIDC da conta `mam-webhook-push`; a API entrega o webhook com o mesmo `X-Webhook-Id` em toda tentativa. Destino fora do ar responde 503 e o Pub/Sub tenta de novo (10 s a 600 s de espera); depois de 10 tentativas a mensagem vai para `mam-eventos-do-job-mortos`, que tem assinatura própria para guardar o que desistiu por 7 dias. A `mam-terraform` precisa de `roles/pubsub.admin` (já no wizard). O tópico sai no output `pubsub_topico_eventos`. O levantamento do que ainda falta está em `docs/levantamento-api-no-ar.md`.

Os eventos de uso (login, envio, fim de processamento, busca, correção e chamada de API) vão ao tópico `mam-eventos-de-uso` (`modulos/mam/eventos_de_uso.tf`, esquema em `evento_de_uso.proto`, `api/eventos_de_uso.py`). A assinatura `mam-eventos-de-uso-bigquery` os grava na tabela `eventos_de_uso` do dataset das decupagens. Quem publica (web, validação, transcrição, OCR e análise) recebe `roles/pubsub.publisher` só no tópico, e o agente de serviço do Pub/Sub, `dataEditor` e `metadataViewer` só na tabela. Nenhum papel novo para a `mam-terraform`. O tópico sai no output `pubsub_topico_uso`.

Os resumos de uso (#280, `modulos/mam/resumos_de_uso.tf` e `.sql`) são quatro tabelas do dataset das decupagens que uma consulta agendada do BigQuery (Data Transfer, a cada 10 minutos, conta `mam-resumos-de-uso` com `jobUser` e `dataEditor` no dataset) refaz a partir dos eventos; o painel lê só elas (a conta da web já lê o dataset). Escolhida no lugar da visão materializada, que não aceita `COUNT(DISTINCT)`, função de janela nem a junção com os momentos. Custo estimado: ~260 GB de consulta por mês, contra 1 TiB grátis; conferir na fatura. Liga a API `bigquerydatatransfer.googleapis.com`. Nenhum papel novo para a `mam-terraform` (o `bigquery.admin` cobre). Output `bigquery_tabelas_do_painel`.

## Chaves de idempotência (#274)

O `POST /v1/jobs` aceita `Idempotency-Key`. A reserva da chave é um documento da coleção `chaves_de_idempotencia` (`api/idempotencia.py`), e a política de TTL de `modulos/mam/idempotencia.tf` apaga o documento 48 h depois (`expira_em`). O TTL do Firestore não é imediato (pode levar até um dia a mais), por isso a API trata a reserva vencida como inexistente. O campo não tem índice próprio.
