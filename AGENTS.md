# MAM RedeTV — PoC de decupagem automática com IA

## Repositório

- GitHub: https://github.com/RedeTVRevolution/mam-prk-redetv-.git
- O plano da PoC está em `docs/`.
- Nunca faça merge de PR com o CI vermelho ou ainda rodando. A `main` não tem branch protection (repositório privado no plano Free), então o GitHub não impede: a regra vale por disciplina.

## Agent skills

### Issue tracker

As issues ficam no GitHub Issues de `RedeTVRevolution/mam-prk-redetv-` (CLI `gh`). Veja `docs/agents/issue-tracker.md`.

### Triage labels

Rótulos padrão: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. Veja `docs/agents/triage-labels.md`.

### Domain docs

Contexto único: `GLOSSARY.md` e `docs/adr/` na raiz. Veja `docs/agents/domain.md`.
