#!/usr/bin/env bash
# Usado pelo CI (job `mudou-o-deploy`): imprime o SHA cujo passo "Deploy no dev" terminou por
# último, se terminou com sucesso, e sai com 1 se não. Comparar com o push anterior perdia o
# deploy de um push cujo CI falhou, quando o seguinte só mexia em teste ou documentação (#764).
# Pede GH_TOKEN com `actions: read`, GITHUB_REPOSITORY, GITHUB_RUN_ID e GITHUB_RUN_ATTEMPT (a
# tentativa atual não conta; as anteriores do mesmo run, sim). Lê os 50 últimos pushes na main
# e todas as tentativas de cada um: um push antigo pode publicar depois de um mais novo, e uma
# reexecução não apaga o deploy da tentativa anterior.
# Limite conhecido: um run mais antigo que os 50 pushes, reexecutado e publicado, fica de fora.
# Um run ainda rodando, ou o último deploy falho ou cancelado, deixa incerto o que está no
# dev: sai com 1, e o CI publica. Na dúvida (API fora, nenhum deploy), publica.
set -euo pipefail

api="repos/$GITHUB_REPOSITORY/actions"
runs=$(gh api "$api/workflows/ci.yml/runs?branch=main&event=push&per_page=50" |
  jq -r '.workflow_runs[] | "\(.id) \(.status)"')

deploys=""
while read -r id status; do
  [ -n "$id" ] || continue
  [ "$status" = completed ] || [ "$id" = "$GITHUB_RUN_ID" ] || exit 1
  jobs=$(gh api --paginate "$api/runs/$id/jobs?filter=all&per_page=100")
  deploys+=$(jq -r --argjson atual "$GITHUB_RUN_ID" --argjson tentativa "$GITHUB_RUN_ATTEMPT" '
    .jobs[] | select(.name == "publicar")
    | select(.run_id != $atual or .run_attempt < $tentativa)
    | .head_sha as $sha | .steps[]
    | select(.name == "Deploy no dev" and .conclusion != "skipped")
    | "\(.completed_at) \(.conclusion) \($sha)"' <<<"$jobs")$'\n'
done <<<"$runs"

read -r _ conclusao sha < <(sort -r <<<"$deploys") || exit 1
[ "$conclusao" = success ] || exit 1
echo "$sha"
