#!/usr/bin/env bash
# Roda o loop AFK no contêiner, num worktree separado, e no fim abre um PR em rascunho.
# Os tokens vêm do Keychain do macOS na hora; veja "Loop AFK" no README.
# Uso: scripts/afk/rodar.sh <máximo de iterações>
set -euo pipefail

iteracoes=${1:?uso: scripts/afk/rodar.sh <máximo de iterações>}
raiz=$(git rev-parse --show-toplevel)
cd "$raiz"
gitdir=$(git rev-parse --path-format=absolute --git-common-dir)
wt=${AFK_WORKTREE:-$(dirname "$raiz")/mam-prk-redetv-afk}
branch=afk/$(date +%Y-%m-%d-%H%M)

plugin=$(jq -r '.plugins["mattpocock-skills@claude-plugins-official"][0].installPath // empty' ~/.claude/plugins/installed_plugins.json)
[ -d "$plugin" ] || { echo "Plugin mattpocock-skills não encontrado neste Mac." >&2; exit 1; }

segredo() { security find-generic-password -a "$USER" -s "$1" -w; }
claude_token=$(segredo afk-claude)
gh_agente=$(segredo afk-github-agente)
gh_script=$(segredo afk-github-script)

# git e gh do Mac com o token do script, sem depender do login local.
git_script() { GH_TOKEN=$gh_script git -c credential.helper= -c credential.helper='!gh auth git-credential' "$@"; }

git_script fetch -q origin main
# Nada de git do Mac dentro do worktree antigo: o agente controlava os arquivos dele.
if git worktree list --porcelain | grep -qxF "worktree $wt"; then
  rm -rf "$wt"
  git worktree prune
fi
git worktree add -q -b "$branch" "$wt" origin/main
admin=$(git rev-parse --path-format=absolute --git-path "worktrees/$(basename "$wt")")
[ -d "$admin" ] || { echo "Pasta do worktree em .git não encontrada: $admin" >&2; exit 1; }
echo "Worktree $wt no branch $branch."

docker build -q -t mam-afk "$raiz/scripts/afk" > /dev/null

GIT_AUTHOR_NAME=$(git config user.name)
GIT_AUTHOR_EMAIL=$(git config user.email)
export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL

# Worktree e .git montados no mesmo caminho do Mac: o .git do worktree aponta para lá.
# O .git fica só leitura (config e hooks rodam no Mac), com escrita só no que o commit
# e o reset precisam. O loop e o prompt vêm da pasta principal, também só leitura.
set +e
CLAUDE_CODE_OAUTH_TOKEN=$claude_token GH_TOKEN=$gh_agente docker run --rm --init \
  --mount "type=bind,src=$wt,dst=$wt" \
  --mount "type=bind,src=$gitdir,dst=$gitdir,readonly" \
  --mount "type=bind,src=$gitdir/objects,dst=$gitdir/objects" \
  --mount "type=bind,src=$gitdir/logs,dst=$gitdir/logs" \
  --mount "type=bind,src=$gitdir/refs/heads/afk,dst=$gitdir/refs/heads/afk" \
  --mount "type=bind,src=$admin,dst=$admin" \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=gc.auto -e GIT_CONFIG_VALUE_0=0 \
  --mount "type=bind,src=$raiz/scripts/afk,dst=/opt/afk,readonly" \
  --mount "type=bind,src=$plugin,dst=/opt/plugins/mattpocock-skills,readonly" \
  -w "$wt" \
  -e CLAUDE_CODE_OAUTH_TOKEN -e GH_TOKEN \
  -e GIT_AUTHOR_NAME -e GIT_AUTHOR_EMAIL -e GIT_COMMITTER_NAME -e GIT_COMMITTER_EMAIL \
  -e AFK_AVISO_TOKENS -e AFK_CORTE_TOKENS -e AFK_MAX_TURNOS -e AFK_MAX_FALHAS -e AFK_MAX_PARCIAIS -e AFK_MODELO \
  -e AFK_PLUGIN_DIR=/opt/plugins/mattpocock-skills \
  mam-afk bash -c 'uv sync -q --locked && npm ci -s --prefix web && /opt/afk/loop.sh "$1"' _ "$iteracoes"
saida=$?
set -e

mkdir -p .afk
notas=.afk/progresso-${branch//\//-}.md
cp "$wt/.afk/progresso.md" "$notas" 2> /dev/null || true
if [ "$(git rev-list --count "origin/main..$branch")" = 0 ]; then
  echo "Nenhum ticket feito; nada para enviar. Notas em $notas."
  exit "$saida"
fi

# Arquivo escrito no contêiner: só números passam para o PR.
feitos=$(grep -xE '[0-9]+' "$wt/.afk/feitos" | paste -sd ' ' - || true)
# shellcheck disable=SC2086 # um número por palavra
fecha=$(printf 'Closes #%s\n' $feitos)
git_script push -q -u origin "$branch"
GH_TOKEN=$gh_script gh pr create --draft --base main --head "$branch" \
  --title "Loop AFK $(date +%F): #${feitos// / #}" \
  --body "Tickets feitos pelo loop AFK (\`scripts/afk\`).

$fecha

As notas das iterações estão em \`$notas\`, na pasta principal.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
exit "$saida"
