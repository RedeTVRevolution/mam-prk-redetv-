# Infra (Terraform)

Um módulo (`modulos/mam`, #292) e três chamadas dele, cada uma com variáveis e estado próprios:

| Ambiente | Pasta | Estado (prefixo no bucket do projeto) | Situação |
| --- | --- | --- | --- |
| dev | `infra/` | `dev` | no ar; `make deploy-dev` e o CD aplicam |
| staging | `infra/ambientes/staging/` | `staging` | só `validate` no CI; nada criado (#293) |
| prod | `infra/ambientes/prod/` | `prod` | só `validate` no CI; nada criado (#293) |

Nenhum valor real de projeto vai no código: cada ambiente tem um `exemplo.tfvars` com nomes de mentira, e o wizard grava os verdadeiros. O bucket do estado entra por `-backend-config="bucket=..."`, um por projeto.

## O que é igual, o que muda e o que ainda depende de decisão

| Assunto | Igual nos três | Muda por ambiente | Depende de decisão |
| --- | --- | --- | --- |
| Recursos | todos os de `modulos/mam` | nada | — |
| Projeto, região, nomes de bucket | a regra de nomes (`<projeto>-<sufixo>`) | projeto e região (variáveis) | a organização de projetos e pastas (#296) |
| Estado | bucket GCS, um por projeto | prefixo (`dev`, `staging`, `prod`) | — |
| Imagens | um digest por componente | o digest publicado em cada projeto | quando prod recebe imagem (promoção a partir do staging) |
| Tamanhos e limites | os padrões do módulo | `janelas_em_paralelo`, `espera_gpu_minutos`, `limite_de_buscas_por_video`, `limite_de_falhas_por_etapa` (staging menor; prod igual ao dev até o piloto medir) | os valores finais de prod, depois do piloto |
| Domínio e balanceador | — | — | o domínio e o balanceador HTTPS do #294 |
| Identity Platform | `import` da config do projeto | o projeto importado (`var.projeto`) | — |
| Aplicação | — | só o dev aplica; sem CD para staging e prod | quando criar os ambientes |

## O que precisa existir antes de cada ambiente

Lista para o wizard (uma vez por projeto, igual ao `scripts/wizard-gcp-dev.sh` do dev):

- [ ] O projeto do GCP, com faturamento (a organização é decisão do #296).
- [ ] A conta `mam-terraform` no projeto, com os papéis de `PAPEIS_DA_TERRAFORM` no wizard (lista abaixo).
- [ ] O bucket do estado do Terraform, criado antes do primeiro `init`.
- [ ] O Identity Platform inicializado pelo Owner (etapa 7 do wizard), antes do primeiro apply.
- [ ] Os e-mails dos administradores de emergência e as imagens publicadas no Artifact Registry do projeto.

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

Validar sem credencial: `terraform -chdir=infra/ambientes/staging init -backend=false && terraform -chdir=infra/ambientes/staging validate` (o CI faz isso nos três).
