#!/usr/bin/env bash
# Espera o CI do PR mais recente do loop AFK e, se tudo passar, faz o merge com squash e limpa os branches.
# Usa o login do gh e do git deste Mac e só pega PR aberto por esse login. Uso: make mesclar-afk [BRANCH=afk/...]
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# Depois do merge, .githooks/ tem código do agente: nenhum hook roda aqui.
g() { git -c core.hooksPath=/dev/null "$@"; }

# O PR aberto mais recente que você abriu de um branch afk/* deste repositório (fork não entra),
# ou o do branch pedido.
ultimo=$(gh pr list --state open --author @me --limit 100 \
  --json number,headRefName,headRefOid,isDraft,createdAt,isCrossRepository --jq \
  '.[] | select((.isCrossRepository | not) and (.headRefName | startswith("afk/")))
   | "\(.createdAt) \(.number) \(.headRefName) \(.headRefOid) \(.isDraft)"' | sort | awk -v b="${1:-}" 'b == "" || $3 == b' | tail -n 1)
if [ -z "$ultimo" ]; then
  echo "Nenhum PR aberto do loop AFK; só limpo os branches."
else
  read -r _ pr branch sha rascunho <<< "$ultimo"
  echo "PR #$pr ($branch)."
  # Se o branch existe aqui (veio do bundle do loop), o PR tem de ter exatamente aquela ponta.
  local_sha=$(g rev-parse -q --verify "refs/heads/$branch" || true)
  if [ -n "$local_sha" ] && [ "$local_sha" != "$sha" ]; then
    echo "O PR #$pr aponta para $sha, mas o branch local $branch está em $local_sha; nada foi mesclado." >&2
    exit 1
  fi

  # Logo depois do push as checagens ainda não existem, e o gh pr checks falharia.
  for _ in $(seq 36); do
    [ "$(gh pr view "$pr" --json statusCheckRollup --jq '.statusCheckRollup | length')" -gt 0 ] && break
    sleep 5
  done
  if ! gh pr checks "$pr" --watch --fail-fast --interval 20; then
    echo "O CI do PR #$pr falhou; nada foi mesclado." >&2
    run=$(gh run list --branch "$branch" --commit "$sha" --status failure --limit 1 --json databaseId --jq '.[0].databaseId // empty')
    [ -z "$run" ] || gh run view "$run" --log-failed | tail -n 80 >&2
    exit 1
  fi

  # rodar.sh abre o PR em rascunho; o --match-head-commit recusa o merge se entrou commit depois do CI.
  [ "$rascunho" = false ] || gh pr ready "$pr"
  # Sem --delete-branch: ele roda git local (switch, pull) com os hooks ligados.
  gh pr merge "$pr" --squash --match-head-commit "$sha"
  gh api -X DELETE "repos/{owner}/{repo}/git/refs/heads/$branch" > /dev/null
  echo "PR #$pr mesclado."
fi

g fetch -q --prune origin
if [ "$(g branch --show-current)" = main ]; then g pull -q --ff-only; else g fetch -q origin main:main; fi

# Com squash, git branch --merged não serve. Apaga só o branch afk/* cuja ponta é a de um PR mesclado;
# os -bloqueado-N e -parcial-N não têm PR e ficam.
for b in $(g for-each-ref --format='%(refname:short)' 'refs/heads/afk/*'); do
  mesclado=$(gh pr list --state merged --head "$b" --json headRefOid --jq '.[].headRefOid')
  if grep -qx "$(g rev-parse "$b")" <<< "$mesclado"; then g branch -q -D "$b" && echo "Apagado $b."; fi
done
echo "main atualizada."
