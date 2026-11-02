# MAM RedeTV — PoC de decupagem automática com IA

## Idioma

- O agente responde sempre em português.

## Repositório

- GitHub: https://github.com/RedeTVRevolution/mam-prk-redetv-.git
- O plano da PoC está em `docs/`.
- Nunca faça merge de PR com o CI vermelho ou ainda rodando. A `main` não tem branch protection (repositório privado no plano Free), então o GitHub não impede: a regra vale por disciplina.
- Todo papel dado à mão à conta mam-terraform entra no scripts/wizard-gcp-dev.sh no mesmo dia, com uma linha dizendo para que serve.
- Nomes de recursos da nuvem (projeto, região, buckets, repositórios, serviços) nunca vão escritos no código; sempre vêm da configuração. O `infra/main.tf` é o único lugar que monta esses nomes e os entrega por variável de ambiente (`GCP_PROJECT_ID`, `BUCKET_*`) ou por `output`; só o bucket do estado do Terraform, que existe antes dele, nasce no `.env` pelo wizard. O `make verificar` falha se o ID do projeto ou um nome de bucket aparecer em `api/` ou `web/src/`, fora dos testes.

## Agent skills

### Issue tracker

As issues ficam no GitHub Issues de `RedeTVRevolution/mam-prk-redetv-` (CLI `gh`). Veja `docs/agents/issue-tracker.md`.

### Triage labels

Rótulos padrão: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Veja `docs/agents/triage-labels.md`.

### Domain docs

Contexto único: `GLOSSARY.md` e `docs/adr/` na raiz. Veja `docs/agents/domain.md`.
