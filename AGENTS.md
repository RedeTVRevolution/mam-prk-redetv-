# MAM RedeTV — PoC de decupagem automática com IA

## Idioma

- O agente responde sempre em português.

## Repositório

- GitHub: https://github.com/RedeTVRevolution/mam-prk-redetv-.git
- O plano da PoC está em `docs/`.
- Nunca faça merge de PR com o CI vermelho ou ainda rodando. O ruleset `main protegida` do GitHub exige na `main` as checagens `backend`, `web`, `imagem`, `terraform`, `loop-afk` e `gitleaks` (sem exceção para ninguém) e bloqueia force push e remoção. O plano Free só aplica ruleset em repositório público: se o repositório voltar a ser privado, a regra volta a valer só por disciplina. Um job novo no `ci.yml` que deva barrar o merge entra também na lista do ruleset; um job renomeado ou removido sai dela, senão nenhum PR consegue ser mesclado.
- Todo papel dado à mão à conta mam-terraform entra no scripts/wizard-gcp-dev.sh no mesmo dia, com uma linha dizendo para que serve.
- Nomes de recursos da nuvem (projeto, região, buckets, repositórios, serviços) nunca vão escritos no código; sempre vêm da configuração. Os arquivos `.tf` do módulo `infra/modulos/mam/` são o único lugar que monta esses nomes e os entrega por variável de ambiente (`GCP_PROJECT_ID`, `BUCKET_*`) ou por `output`; só o bucket do estado do Terraform, que existe antes dele, nasce no `.env` pelo wizard. O `make verificar` falha se o ID do projeto ou um nome de bucket aparecer em `api/` ou `web/src/`, fora dos testes.

## Agent skills

### Issue tracker

As issues ficam no GitHub Issues de `RedeTVRevolution/mam-prk-redetv-` (CLI `gh`). Veja `docs/agents/issue-tracker.md`.

### Triage labels

Rótulos padrão: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Veja `docs/agents/triage-labels.md`.

### Domain docs

Contexto único: `GLOSSARY.md` e `docs/adr/` na raiz. Veja `docs/agents/domain.md`.

### Implementação com subagentes (`/implement-spec`, `/implement`)

- O spec é um issue-pai com os tickets como sub-issues; a ordem vem das dependências nativas do GitHub (`docs/agents/issue-tracker.md`).
- Os subagentes implementadores rodam no modelo Sonnet, no máximo 3 ao mesmo tempo, cada um na sua worktree.
- Cada ticket fecha com `VITEST_MAX_WORKERS=2 PYTEST_XDIST_AUTO_NUM_WORKERS=3 make verificar` verde. Com vários agentes em paralelo, os testes falham por carga se cada um usar todos os núcleos.
- O branch de integração vira um PR único. Ele só é mesclado com todas as checagens do CI verdes, e quem mescla é a pessoa.
- Item do aceite que só uma pessoa faz (teste no dev, script rodado à mão, deploy) fica aberto no ticket com um comentário dizendo o que falta; o agente não fecha esse ticket.
