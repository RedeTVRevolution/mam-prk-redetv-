#!/usr/bin/env bash
# Roda o loop AFK no contêiner, num clone separado, e no fim abre um PR em rascunho.
# Os tokens vêm do Keychain do macOS na hora; veja "Loop AFK" no README.
# Uso: scripts/afk/rodar.sh <máximo de iterações>
# Com AFK_AUTO_MERGE=1, roda make mesclar-afk no fim, salvo se o agente mudou .github/workflows/.
set -euo pipefail

iteracoes=${1:?uso: scripts/afk/rodar.sh <máximo de iterações>}
raiz=$(git rev-parse --show-toplevel)
cd "$raiz"
clone=${AFK_CLONE:-$(dirname "$raiz")/mam-prk-redetv-afk}
branch=afk/$(date +%Y-%m-%d-%H%M)

plugin=$(jq -r '.plugins["mattpocock-skills@claude-plugins-official"][0].installPath // empty' ~/.claude/plugins/installed_plugins.json)
[ -d "$plugin" ] || { echo "Plugin mattpocock-skills não encontrado neste Mac." >&2; exit 1; }

segredo() { security find-generic-password -a "$USER" -s "$1" -w; }
claude_token=$(segredo afk-claude)
gh_agente=$(segredo afk-github-agente)
gh_script=$(segredo afk-github-script)

# git e gh do Mac com o token do script, sem depender do login local.
git_script() { GH_TOKEN=$gh_script git -c credential.helper= -c credential.helper='!gh auth git-credential' "$@"; }

# O agente controla o clone: o Mac só o apaga e recria, nunca roda git lá dentro depois do loop.
if [ -e "$clone" ]; then
  [ -d "$clone/.afk" ] || { echo "$clone existe e não parece o clone do loop AFK; apague-o à mão." >&2; exit 1; }
  rm -rf "$clone"
fi
git worktree prune
git_script fetch -q origin main
git_script clone -q --single-branch --branch main "$(git remote get-url origin)" "$clone"
git -C "$clone" switch -q -c "$branch"
mkdir "$clone/.afk"
echo "Clone $clone no branch $branch."

docker build -q -t mam-afk "$raiz/scripts/afk" > /dev/null

GIT_AUTHOR_NAME=$(git config user.name)
GIT_AUTHOR_EMAIL=$(git config user.email)
export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL

# Só o clone entra com escrita; o repositório principal fica de fora. O loop e o prompt
# vêm da pasta principal, só leitura. No fim, os branches afk/* saem num bundle.
set +e
CLAUDE_CODE_OAUTH_TOKEN=$claude_token GH_TOKEN=$gh_agente docker run --rm --init \
  --mount "type=bind,src=$clone,dst=$clone" \
  --mount "type=bind,src=$raiz/scripts/afk,dst=/opt/afk,readonly" \
  --mount "type=bind,src=$plugin,dst=/opt/plugins/mattpocock-skills,readonly" \
  -w "$clone" \
  -e CLAUDE_CODE_OAUTH_TOKEN -e GH_TOKEN \
  -e GIT_AUTHOR_NAME -e GIT_AUTHOR_EMAIL -e GIT_COMMITTER_NAME -e GIT_COMMITTER_EMAIL \
  -e AFK_AVISO_TOKENS -e AFK_CORTE_TOKENS -e AFK_MAX_TURNOS -e AFK_MAX_FALHAS -e AFK_MAX_PARCIAIS -e AFK_MODELO -e AFK_MODELO_REVISOR \
  -e AFK_PLUGIN_DIR=/opt/plugins/mattpocock-skills \
  mam-afk bash -c 'make instalar > /dev/null && /opt/afk/loop.sh "$1"; s=$?
    git bundle create -q .afk/afk.bundle --branches="afk/*"; exit $s' _ "$iteracoes"
saida=$?
set -e

mkdir -p .afk
notas=.afk/progresso-${branch//\//-}.md
cp "$clone/.afk/progresso.md" "$notas" 2> /dev/null || true

# O fetch do bundle confere cada objeto antes de gravar no repositório principal.
if [ -f "$clone/.afk/afk.bundle" ]; then
  git fetch -q --no-tags "$clone/.afk/afk.bundle" "+refs/heads/afk/*:refs/heads/afk/*"
fi
if ! git rev-parse -q --verify "refs/heads/$branch" > /dev/null || [ "$(git rev-list --count "origin/main..$branch")" = 0 ]; then
  echo "Nenhum ticket feito; nada para enviar. Notas em $notas."
  exit "$saida"
fi

# Arquivo escrito no contêiner: só números passam para o PR.
feitos=$(grep -xE '[0-9]+' "$clone/.afk/feitos" | paste -sd ' ' - || true)
# shellcheck disable=SC2086 # um número por palavra
fecha=$(printf 'Closes #%s\n' $feitos)
# O CI do PR roda o ci.yml do próprio branch: mudança do agente ali pede olho humano.
# Nomes vêm dos commits do agente: caractere fora do padrão vira "?".
workflows=$(git diff --name-only "origin/main...$branch" -- .github/workflows/ | sed -E 's#[^A-Za-z0-9._/-]#?#g')
aviso=
if [ -n "$workflows" ]; then
  aviso="> [!WARNING]
> O agente mudou o CI. Revise estes arquivos antes do merge:
$(sed -E "s/.*/> - \`&\`/" <<< "$workflows")

"
fi
git_script push -q -u origin "$branch"
GH_TOKEN=$gh_script gh pr create --draft --base main --head "$branch" \
  --title "Loop AFK $(date +%F): #${feitos// / #}" \
  --body "${aviso}Tickets feitos pelo loop AFK (\`scripts/afk\`).

$fecha

As notas das iterações estão em \`$notas\`, na pasta principal.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"

if [ "${AFK_AUTO_MERGE:-0}" = 1 ]; then
  if [ -n "$workflows" ]; then
    echo "O agente mudou .github/workflows/; sem merge automático. Revise o PR e rode make mesclar-afk." >&2
  else
    make mesclar-afk BRANCH="$branch"
  fi
fi
exit "$saida"
