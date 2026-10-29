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

## Loop AFK

`scripts/afk/rodar.sh` implementa os tickets `ready-for-agent` sozinho, sem perguntas, um ticket por iteração. Cada iteração é um `claude -p` novo, com o contexto vazio, rodando num contêiner Docker sem credencial de nuvem e num worktree separado (`../mam-prk-redetv-afk`), para a pasta principal continuar livre. O estado entre as iterações fica em `.afk/` dentro do worktree. O `.git` principal entra no contêiner só leitura, com escrita apenas em objetos, reflogs, `refs/heads/afk` e na pasta do worktree: o agente não alcança `config` nem `hooks`, que rodam no Mac. No fim, o script faz um push só, no branch `afk/<data-hora>`, e abre um PR em rascunho com `Closes #N` de cada ticket feito. O merge é seu, e nunca com o CI vermelho.

Arquivos em `scripts/afk/`: `prompt.md` (o texto que o agente recebe; edite à vontade), `loop.sh` (o loop, dentro do contêiner), `rodar.sh` (o Mac: Keychain, worktree, Docker, push e PR), `hook-contexto.sh` (o aviso de contexto, ligado em `.claude/settings.json` e inerte fora do loop), `Dockerfile` e `testes.sh`.

### Configuração, uma vez só

1. **Token do Claude Code.** Gere com `claude setup-token` e guarde no Keychain (o comando pede o valor):

   ```sh
   security add-generic-password -a "$USER" -s afk-claude -w
   ```

2. **Dois tokens do GitHub**, ambos *fine-grained* e com acesso só a `RedeTVRevolution/mam-prk-redetv-` (a organização pode precisar aprovar):
   - `afk-github-agente`, que vai para o contêiner: Issues leitura e escrita, Contents só leitura. Sem escrita em Contents, o agente não consegue fazer push.
   - `afk-github-script`, que fica no Mac: Contents e Pull requests leitura e escrita. Serve para o fetch, o push final e o PR.

   ```sh
   security add-generic-password -a "$USER" -s afk-github-agente -w
   security add-generic-password -a "$USER" -s afk-github-script -w
   ```

3. **Label `afk-feito`**, que o script põe em cada ticket terminado:

   ```sh
   gh label create afk-feito --color 0E8A16 --description "Feito pelo loop AFK, aguardando merge"
   ```

4. **Docker Desktop** aberto. A imagem `mam-afk` é construída na primeira execução.
5. **Plugin `mattpocock-skills`** instalado no Claude Code do Mac. O script monta a pasta dele no contêiner, só leitura.

### Como rodar

O worktree sai da `origin/main`, então este loop só funciona depois do merge dele na `main`. Comece com uma iteração e confira o resultado:

```sh
scripts/afk/rodar.sh 1
```

Veja as notas em `.afk/progresso-afk-<data-hora>.md`, uma cópia na pasta principal, o `git log afk/<data-hora>` e o PR. Inspecione sempre pela pasta principal e não rode `git` dentro do worktree do agente: os arquivos dele, inclusive o ponteiro `.git`, ficaram sob controle do agente. A execução seguinte apaga e recria o worktree. Depois, aumente o número de iterações, por exemplo `scripts/afk/rodar.sh 10`.

Cada iteração:

1. Pega o ticket: o que ficou parcial na iteração anterior ou o menor `ready-for-agent` aberto, sem `afk-feito`, com todos os bloqueios resolvidos (dependências nativas e linha `Bloqueado por: #N`). Um bloqueio está resolvido se o bloqueador está fechado ou tem `afk-feito`.
2. Roda o agente com `prompt.md`: `mattpocock-skills:tdd`, `make verificar`, commit, `mattpocock-skills:code-review` a partir do commit de antes do ticket e um commit com as correções.
3. Descarta o que não foi commitado e roda `make verificar`. Se falhar, desfaz os commits da iteração.
4. Lê o fim da resposta (`<ticket>N</ticket>` e `<status>…</status>`):
   - `feito`: põe `afk-feito` no ticket.
   - `parcial`: a próxima iteração continua o ticket.
   - `bloqueado`: o agente comentou a pergunta no ticket e trocou a label para `ready-for-human`. O script tira o trabalho do branch, guarda num branch local `<branch>-bloqueado-N` e segue.
   - `erro`: problema do ambiente, como uma skill ausente. O loop para.

O loop para sozinho quando a fila esvazia, depois do número de iterações pedido, depois de 3 falhas seguidas (portão vermelho ou iteração sem sinal válido) ou se houver um ticket aberto com `afk-feito`, o que indica um PR anterior sem merge. Um ticket com 3 parciais seguidas volta para humano como um bloqueado. Um ticket em andamento quando o loop para sai do branch do PR e fica num branch local `<branch>-parcial-N`.

### Variáveis

| Variável | Padrão | Para quê |
|---|---|---|
| `AFK_AVISO_TOKENS` | 120000 | O hook manda o agente comitar o que está verde, anotar o que falta e sair como `parcial` |
| `AFK_CORTE_TOKENS` | 140000 | O script mata a iteração e descarta o que não foi commitado |
| `AFK_MAX_TURNOS` | 300 | `--max-turns` de cada iteração |
| `AFK_MAX_FALHAS` | 3 | Falhas seguidas antes de parar |
| `AFK_MAX_PARCIAIS` | 3 | Parciais seguidas de um ticket antes de devolvê-lo para humano |
| `AFK_MODELO` | padrão do Claude Code | `--model` do agente |

O tamanho do contexto é a soma de `input_tokens`, `cache_read_input_tokens` e `cache_creation_input_tokens` da última resposta da conversa principal (sem subagentes).

### Testes

```sh
make testar-afk
```

Roda o `shellcheck` e o `testes.sh`, que exercita o loop com `claude` e `gh` falsos, sem Docker e sem rede: ticket feito, estouro de contexto, ticket bloqueado, verificação falhando depois do commit, parciais seguidas, fila sem tickets elegíveis, PR anterior sem merge e o hook abaixo e acima do aviso. O CI roda o mesmo alvo.
