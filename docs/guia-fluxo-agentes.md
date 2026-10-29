# Guia do fluxo com agentes (skills do Matt Pocock + sandcastle)

Montado em 2026-10-28 a partir de: plugin `mattpocock-skills` 1.3.1 (README, `ask-matt`,
`PHASE-BOUNDARIES.md`) e código do sandcastle no commit `a53e227`.

## Regra de contexto

- Grill → spec → tickets numa **única janela de contexto**. A implementação começa sempre
  do zero, a partir do ticket.
- Smart zone: ~150k tokens. Teto deste projeto: **140k**.
- Se a sessão se aproximar do teto antes do `/to-tickets`, use `/compact` com uma instrução,
  **na fronteira entre fases**, nunca no meio de uma.

## Passo a passo

0. **Preparação**
   - `git push -u origin main`.
   - Rodar `/setup-matt-pocock-skills` com estas respostas: tracker GitHub, rótulos padrão,
     documentação em contexto único.
   - Pedir à skill que grave o bloco `## Agent skills` no **AGENTS.md**. O CLAUDE.md só faz
     `@AGENTS.md`.
1. **`/grill-with-docs` só para a E0**, usando `docs/Plano final….md` como material.
   - Gera `GLOSSARY.md` e `docs/adr/`.
   - O `/wayfinder` fica para mapear da E1 à E11 mais tarde.
2. **(opcional)** Para dúvidas que pedem resposta executável: `/handoff` → `/prototype` →
   `/handoff` de volta.
3. **`/to-spec`** na mesma sessão. Valide os pontos onde os testes vão entrar (seams):
   poucos e altos.
4. **`/to-tickets`** na mesma sessão.
   - Cada ticket precisa caber numa sessão nova, bem abaixo de 140k.
   - Tickets que precisam de nuvem real ou credenciais levam `ready-for-human`.
   - **Tire o `ready-for-agent` da issue do spec**, senão o planejador do sandcastle pega o
     spec inteiro como uma tarefa.
5. **Tarefas humanas**: `/wizard` cuida de projetos GCP, Workload Identity Federation e
   Identity Platform. Nenhuma credencial do GCP entra no container.
6. **Sandcastle, template `parallel-planner-with-review`**: planejar → implementar em
   worktrees paralelos → revisar → fazer merge, em loop. Ajustes:

   | Ajuste | Por quê |
   |---|---|
   | `package.json` na raiz e Docker Desktop | sandcastle é pacote npm e roda em Docker |
   | `claude setup-token` e `GH_TOKEN` restrito ao repositório no `.sandcastle/.env` | login do Claude e do `gh` no container |
   | Dockerfile com Python 3.12, uv, ffmpeg e pytest | sem testes, o agente trabalha às cegas |
   | Plugin `mattpocock-skills` instalado no Dockerfile | o `/tdd` precisa existir dentro do container |
   | Comandos reais de teste no `implement-prompt.md` | o template usa `npm run typecheck/test` |
   | Listar issues com `--label ready-for-agent` | o padrão do template filtra `Sandcastle` |
   | `plan-prompt.md` respeitando o "Blocked by" | os bloqueios já vêm calculados pelo `/to-tickets` |
   | Modelos `claude-opus-5-5` e `claude-sonnet-5-5` | o template vem com modelos antigos |
   | (opcional) `review-prompt.md` chamando `code-review` | revisa padrões e aderência ao spec |

   Use um caminho só: ou `/implement-spec` (interativo) ou sandcastle (AFK).
7. **Teto de 140k**
   - Cada iteração do sandcastle já é uma sessão nova (`claude -p`); só a primeira retoma
     uma sessão anterior (`Orchestrator.ts:381`).
   - Por isso, o teto só precisa encerrar a iteração atual. A próxima começa limpa e lê
     `git status`, `git log` e o último comentário da issue.
   - **Não use `resume()`**: ele traz de volta o contexto degradado.
   - Mecanismo: hook `PostToolUse` em `.claude/hooks/context-cap.mjs`.
     - Soma `input + cache_creation + cache_read` do último `assistant` do transcript.
     - **Aviso a ~120k** com `decision: block`: commit `RALPH:`, comentário na issue e fim
       do turno sem COMPLETE.
     - **Parada forçada a 140k** com `continue: false`.
     - Só age com `RALPH_CONTEXT_CAP` definido, e essa variável só existe no Dockerfile.
   - A confirmar na implementação: que o `reason` chega ao modelo e que o
     `continue: false` encerra o `claude -p` de forma limpa.
   - Logar `result.iterations[i].usage` no `main.mts`.
8. **Rodar**
   - Primeiro um teste com 1 ou 2 tickets, depois a E0 inteira.
   - `/code-review` no branch de integração.
   - `/retro` na mesma sessão, antes do `/clear`.
   - Depois, a E1, começando de novo pelo passo 1.
