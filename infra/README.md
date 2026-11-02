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
- [ ] A conta `mam-terraform` no projeto, com os papéis do wizard.
- [ ] A conta `mam-build` no projeto, com os mesmos papéis que tem no dev, mais os que os tickets novos acrescentaram.
- [ ] O bucket do estado do Terraform, criado antes do primeiro `init`.
- [ ] O Identity Platform inicializado pelo Owner (etapa 7 do wizard), antes do primeiro apply.
- [ ] Os e-mails dos administradores de emergência e as imagens publicadas no Artifact Registry do projeto.

Validar sem credencial: `terraform -chdir=infra/ambientes/staging init -backend=false && terraform -chdir=infra/ambientes/staging validate` (o CI faz isso nos três).
