#!/usr/bin/env bash
# Loop AFK: um ticket por iteração, cada iteração num `claude -p` novo.
# Roda na raiz do worktree: dentro do contêiner (via rodar.sh) ou direto, nos testes.
# Uso: loop.sh <máximo de iterações>
set -euo pipefail

max_iteracoes=${1:?uso: loop.sh <máximo de iterações>}
aqui=$(cd "$(dirname "$0")" && pwd)
export AFK_AVISO_TOKENS=${AFK_AVISO_TOKENS:-120000}
corte=${AFK_CORTE_TOKENS:-140000}
max_turnos=${AFK_MAX_TURNOS:-300}
max_falhas=${AFK_MAX_FALHAS:-3}
max_parciais=${AFK_MAX_PARCIAIS:-3}
verificar=${AFK_VERIFICAR:-make verificar}
intervalo=${AFK_INTERVALO:-2}

branch=$(git branch --show-current)
logs=.afk/logs/$(date +%Y%m%d-%H%M%S)
progresso=.afk/progresso.md
estado=.afk/ticket_atual # "<ticket> <commit base do ticket> <parciais seguidas>"
mkdir -p "$logs"
: > .afk/feitos
rm -f "$estado"
printf '\n## Execução em %s\n\n' "$branch" >> "$progresso"

anota() { printf -- '- %s · %s\n' "$(date '+%F %T')" "$*" | tee -a "$progresso"; }

# shellcheck disable=SC2016 # variáveis do GraphQL, não do shell
CONSULTA='query($owner: String!, $name: String!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 100, after: $endCursor) {
      nodes { number state body labels(first: 20) { nodes { name } } blockedBy(first: 50) { nodes { number } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}'

# Todas as issues, com os bloqueios nativos somados aos da linha "Bloqueado por: #N".
issues() {
  gh api graphql --paginate -F owner='{owner}' -F name='{repo}' -f query="$CONSULTA" |
    jq -s '[.[].data.repository.issues.nodes[] | {
      number, state, labels: [.labels.nodes[].name],
      bloqueios: ([.blockedBy.nodes[].number]
        + [(.body // "") | splits("\r?\n") | select(test("^\\s*(bloqueado por|blocked by)\\s*:"; "i"))
           | scan("#([0-9]+)")[] | tonumber] | unique)
    }]'
}

# Menor ticket ready-for-agent aberto, ainda não feito, com todos os bloqueadores fechados ou afk-feito.
proximo_ticket() {
  issues | jq -r '
    (map({key: (.number | tostring), value: (.state == "CLOSED" or (.labels | index("afk-feito") != null))})
      | from_entries) as $resolvido
    | map(select(.state == "OPEN" and (.labels | index("ready-for-agent")) and (.labels | index("afk-feito") | not)
        and all(.bloqueios[]; $resolvido[tostring] == true)))
    | sort_by(.number) | first | .number // empty'
}

contexto() {
  jq -R 'fromjson? | select(.type == "assistant" and .parent_tool_use_id == null)
    | .message.usage | .input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens' "$1" | tail -n 1
}

# Tira do branch os commits do ticket (guardando-os num branch local) e volta para a base.
guarda() { # <ticket> <base> <sufixo>
  if [ "$(git rev-parse HEAD)" != "$2" ]; then
    guardado=$branch-$3-$1
    git branch -f "$guardado" HEAD
    git reset -q --hard "$2"
  else
    guardado=""
  fi
}

para_humano() { # <ticket> <base> <motivo>
  guarda "$1" "$2" bloqueado
  gh issue edit "$1" --remove-label ready-for-agent --add-label ready-for-human > /dev/null
  gh issue comment "$1" --body "Loop AFK: ticket devolvido para humano ($3).${guardado:+ O trabalho parcial ficou no branch local \`$guardado\`.}" > /dev/null
  anota "#$1 → ready-for-human: $3${guardado:+; trabalho guardado em $guardado}"
  rm -f "$estado"
}

pendentes=$(issues | jq -r '[.[] | select(.state == "OPEN" and (.labels | index("afk-feito"))) | "#\(.number)"] | join(" ")')
if [ -n "$pendentes" ]; then
  anota "parada: $pendentes têm afk-feito e seguem abertos. Faça o merge do PR anterior (ou tire a label) antes de rodar de novo."
  exit 3
fi

falhas=0
saida=0
for ((i = 1; i <= max_iteracoes; i++)); do
  if [ -f "$estado" ]; then
    read -r ticket base parciais < "$estado"
  else
    ticket=$(proximo_ticket)
    if [ -z "$ticket" ]; then
      anota "sem_tickets: nenhum ticket elegível"
      break
    fi
    base=$(git rev-parse HEAD)
    parciais=0
  fi
  inicio=$(git rev-parse HEAD)
  log=$logs/iteracao-$i.jsonl
  anota "iteração $i: #$ticket"

  prompt=$(cat "${AFK_PROMPT:-$aqui/prompt.md}")
  prompt+=$'\n\n## Esta iteração\n\n'"- Ticket: #$ticket"$'\n'"- Ponto fixo da revisão (commit de antes do ticket): $base"
  if [ "$base" != "$inicio" ]; then
    prompt+=$'\n'"- Continuação: o ticket já tem commits. Leia \`git log $base..HEAD\` e as notas de .afk/progresso.md."
  fi
  args=(-p "$prompt" --output-format stream-json --verbose --dangerously-skip-permissions --max-turns "$max_turnos")
  if [ -n "${AFK_MODELO:-}" ]; then args+=(--model "$AFK_MODELO"); fi
  if [ -n "${AFK_PLUGIN_DIR:-}" ]; then args+=(--plugin-dir "$AFK_PLUGIN_DIR"); fi

  # Grupo de processos próprio, para o corte matar também o que o agente abriu.
  set -m
  claude "${args[@]}" > "$log" 2> "$log.err" < /dev/null &
  pid=$!
  set +m

  cortado=0
  while kill -0 "$pid" 2> /dev/null; do
    sleep "$intervalo"
    tokens=$(contexto "$log")
    if [ "${tokens:-0}" -gt "$corte" ]; then
      kill -TERM -- "-$pid" 2> /dev/null || true
      sleep 1
      kill -KILL -- "-$pid" 2> /dev/null || true
      cortado=1
      anota "#$ticket: corte duro com $tokens tokens; o que não foi commitado é descartado"
      break
    fi
  done
  wait "$pid" 2> /dev/null || true

  resposta=$(jq -Rr 'fromjson? | select(.type == "result") | .result // empty' "$log")
  sinal=$(sed -n 's:.*<ticket>#*\([0-9]*\)</ticket>.*:\1:p' <<< "$resposta" | tail -n 1)
  status=$(sed -n 's:.*<status>\([a-z_]*\)</status>.*:\1:p' <<< "$resposta" | tail -n 1)
  if [ "$cortado" = 1 ]; then
    status=parcial
  elif [ "$sinal" != "$ticket" ]; then
    status=""
  fi

  # Portão: descarta o que não foi commitado e confere o que foi.
  git reset -q --hard
  git clean -fdq
  verde=1
  if [ "$(git rev-parse HEAD)" != "$inicio" ] && ! bash -c "$verificar" > "$log.verificar" 2>&1; then
    git reset -q --hard "$inicio"
    verde=0
  fi

  if [ "$status" = erro ]; then
    anota "#$ticket: erro de ambiente informado pelo agente; o loop para (veja as notas acima e $log)"
    saida=2
    break
  elif [ "$status" = bloqueado ]; then
    para_humano "$ticket" "$base" "o agente precisa de uma decisão; veja o comentário anterior"
  elif [ "$verde" = 0 ] || [ -z "$status" ]; then
    falhas=$((falhas + 1))
    if [ "$verde" = 0 ]; then
      anota "#$ticket: make verificar falhou depois da iteração; commits da iteração desfeitos ($log.verificar)"
    else
      anota "#$ticket: iteração terminou sem <ticket>$ticket</ticket> e <status> válidos ($log)"
    fi
    echo "$ticket $base $parciais" > "$estado"
    if [ "$falhas" -ge "$max_falhas" ]; then
      anota "parada: $falhas falhas seguidas"
      saida=1
      break
    fi
    continue
  elif [ "$status" = feito ]; then
    gh issue edit "$ticket" --add-label afk-feito > /dev/null
    echo "$ticket" >> .afk/feitos
    rm -f "$estado"
    anota "#$ticket: feito"
  elif [ "$status" = parcial ]; then
    parciais=$((parciais + 1))
    if [ "$parciais" -ge "$max_parciais" ]; then
      para_humano "$ticket" "$base" "$parciais iterações parciais seguidas"
    else
      echo "$ticket $base $parciais" > "$estado"
      anota "#$ticket: parcial ($parciais/$max_parciais); a próxima iteração continua"
    fi
  else
    anota "#$ticket: status desconhecido '$status'; o loop para"
    saida=2
    break
  fi
  falhas=0
done

# O PR só leva tickets feitos: um ticket ainda em andamento sai do branch.
if [ -f "$estado" ]; then
  read -r ticket base _ < "$estado"
  guarda "$ticket" "$base" parcial
  anota "#$ticket: ficou em andamento${guardado:+; trabalho guardado em $guardado}"
  rm -f "$estado"
fi
anota "fim: feitos: $(tr '\n' ' ' < .afk/feitos)"
exit "$saida"
