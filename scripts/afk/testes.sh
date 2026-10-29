#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2329 # trechos passados a eval e funções chamadas via checa
# Testa o loop AFK e o hook de contexto com claude e gh falsos: sem Docker e sem rede.
# Uso: scripts/afk/testes.sh
set -euo pipefail

aqui=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
falhou=0

checa() { # <descrição> <comando...>
  if "${@:2}"; then echo "  ok: $1"; else echo "  FALHOU: $1"; falhou=1; fi
}
contem() { grep -q -- "$2" "$1"; }

# --- falsos ---------------------------------------------------------------

mkdir "$tmp/bin"
cat > "$tmp/bin/claude" << 'FIM'
#!/usr/bin/env bash
# claude falso: executa a próxima linha de $FAKE/roteiro ("<ação> <ticket>").
# Registra em $FAKE/claude.log a ação, o ticket, o --model e se o hook de contexto está ligado,
# e guarda o prompt em $FAKE/prompt.<modelo>.
set -euo pipefail
modelo=padrão
while [ $# -gt 0 ]; do
  case $1 in
    -p) prompt=$2 ;;
    --model) modelo=$2 ;;
  esac
  shift
done
printf '%s' "$prompt" > "$FAKE/prompt.$modelo"
read -r acao ticket < "$FAKE/roteiro"
tail -n +2 "$FAKE/roteiro" > "$FAKE/roteiro.novo" && mv "$FAKE/roteiro.novo" "$FAKE/roteiro"
echo "$acao $ticket $modelo${AFK_AVISO_TOKENS:+ aviso}" >> "$FAKE/claude.log"
uso() { printf '{"type":"assistant","parent_tool_use_id":%s,"message":{"usage":{"input_tokens":1,"cache_read_input_tokens":%s,"cache_creation_input_tokens":0}}}\n' "$1" "$2"; }
fim() { printf '{"type":"result","result":"Pronto.\\n<ticket>%s</ticket>\\n<status>%s</status>"}\n' "$ticket" "$1"; }
fim_revisao() { printf '{"type":"result","result":"Revisado.\\n<revisao>%s</revisao>"}\n' "$1"; }
commit() { echo "$1" > "$1"; git add "$1"; git commit -qm "#$ticket: $1"; }
uso null 5000
uso '"subagente"' 999999 # contexto de subagente: não conta
case $acao in
  feito) commit "t$ticket"; fim feito ;;
  parcial) commit "t$ticket-parte-$RANDOM"; fim parcial ;;
  quebra) commit quebrado; fim feito ;;
  bloqueado)
    commit "t$ticket-parte"
    gh issue comment "$ticket" --body "Qual opção?"
    gh issue edit "$ticket" --remove-label ready-for-agent --add-label ready-for-human
    fim bloqueado ;;
  estouro) commit "t$ticket-parte"; echo lixo > lixo.txt; uso null 999999; sleep 30; fim feito ;;
  revisa) commit "r$ticket"; echo lixo > lixo-revisao.txt; fim_revisao feita ;;
  revisa_quebra) commit quebrado; fim_revisao feita ;;
  revisa_erro) fim_revisao erro ;;
  revisa_mudo) commit "r$ticket" ;;
esac
FIM

cat > "$tmp/bin/gh" << 'FIM'
#!/usr/bin/env bash
# gh falso: serve $FAKE/issues.json e registra edições e comentários em $FAKE/gh.log.
set -euo pipefail
case "$1 $2" in
  "api graphql") jq '{data: {repository: {issues: {nodes: ., pageInfo: {hasNextPage: false}}}}}' "$FAKE/issues.json" ;;
  "issue comment") echo "comment $3" >> "$FAKE/gh.log" ;;
  "issue edit")
    n=$3; shift 3
    echo "edit $n $*" >> "$FAKE/gh.log"
    while [ $# -gt 0 ]; do
      case $1 in
        --add-label) filtro='.labels.nodes += [{name: $l}]' ;;
        --remove-label) filtro='.labels.nodes |= map(select(.name != $l))' ;;
      esac
      jq --argjson n "$n" --arg l "$2" "map(if .number == \$n then $filtro else . end)" "$FAKE/issues.json" > "$FAKE/i.json"
      mv "$FAKE/i.json" "$FAKE/issues.json"
      shift 2
    done ;;
  *) echo "gh falso: comando inesperado: $*" >&2; exit 1 ;;
esac
FIM
chmod +x "$tmp/bin/claude" "$tmp/bin/gh"

# --- cenários -------------------------------------------------------------

issue() { # <número> <estado> <labels,> <bloqueios nativos,> [corpo]
  jq -n --argjson n "$1" --arg s "$2" --arg l "$3" --arg b "$4" --arg corpo "${5:-}" '{
    number: $n, state: $s, body: $corpo,
    labels: {nodes: [$l | splits(",") | select(. != "") | {name: .}]},
    blockedBy: {nodes: [$b | splits(",") | select(. != "") | {number: tonumber}]}}'
}

# Roda o loop com as issues de $fila e o roteiro do claude nos argumentos.
roda() { # <máx. iterações> <passos do roteiro...>
  export FAKE=$tmp/caso$((++caso))
  repo=$FAKE/repo
  mkdir -p "$repo"
  jq -s . <<< "$fila" > "$FAKE/issues.json"
  printf '%s\n' "${@:2}" > "$FAKE/roteiro"
  touch "$FAKE/claude.log" "$FAKE/gh.log"
  git -C "$repo" init -q -b main
  echo .afk/ > "$repo/.gitignore"
  git -C "$repo" add .gitignore
  git -C "$repo" commit -qm inicial
  inicio=$SECONDS
  set +e
  (cd "$repo" && PATH="$tmp/bin:$PATH" "$aqui/loop.sh" "$1") > "$FAKE/saida.txt" 2>&1
  saida=$?
  set -e
  duracao=$((SECONDS - inicio))
}
caso=0
export GIT_AUTHOR_NAME=teste GIT_AUTHOR_EMAIL=teste@exemplo GIT_COMMITTER_NAME=teste GIT_COMMITTER_EMAIL=teste@exemplo
export AFK_VERIFICAR='test ! -e quebrado' AFK_INTERVALO=0.1
no_head() { git -C "$repo" cat-file -e "HEAD:$1" 2> /dev/null; }
feitos() { [ "$(tr '\n' ' ' < "$repo/.afk/feitos")" = "$1" ]; }
chamadas() { [ "$(wc -l < "$FAKE/claude.log" | tr -d ' ')" = "$1" ]; }
rodou() { [ "$(paste -sd ';' "$FAKE/claude.log")" = "$1" ]; } # <linhas do claude.log, separadas por ;>

echo "Ticket feito, na ordem dos bloqueios"
fila=$(
  issue 1 OPEN ready-for-agent ""
  issue 2 OPEN ready-for-agent 1
  issue 3 OPEN ready-for-agent "" $'## Bloqueio\n\nBloqueado por: #2'
  issue 4 OPEN ready-for-human ""
  issue 5 CLOSED ready-for-agent ""
)
roda 5 "feito 1" "revisa 1" "feito 2" "revisa 2" "feito 3" "revisa 3"
checa "sai com 0" [ "$saida" = 0 ]
checa "feitos 1, 2 e 3, nessa ordem" feitos "1 2 3 "
checa "afk-feito no #3" contem "$FAKE/gh.log" "edit 3 --add-label afk-feito"
checa "commits do agente e da revisão no branch" eval 'no_head t3 && no_head r3'
checa "revisão num claude -p à parte, com opus e sem aviso de contexto" \
  rodou "feito 1 padrão aviso;revisa 1 opus;feito 2 padrão aviso;revisa 2 opus;feito 3 padrão aviso;revisa 3 opus"
checa "a revisão recebe o ticket e o commit de antes dele" \
  eval 'contem "$FAKE/prompt.opus" "Ticket: #3" && contem "$FAKE/prompt.opus" "$(git -C "$repo" rev-parse HEAD~2)"'
checa "descarta o que a revisão não commitou" [ ! -e "$repo/lixo-revisao.txt" ]
checa "para quando a fila esvazia" contem "$repo/.afk/progresso.md" sem_tickets

echo "Estouro de contexto"
fila=$(issue 1 OPEN ready-for-agent "")
export AFK_CORTE_TOKENS=100000
roda 5 "estouro 1" "feito 1" "revisa 1"
unset AFK_CORTE_TOKENS
checa "não revisa ticket cortado" rodou "estouro 1 padrão aviso;feito 1 padrão aviso;revisa 1 opus"
checa "mata a iteração sem esperar o agente" [ "$duracao" -lt 20 ]
checa "anota o corte" contem "$repo/.afk/progresso.md" "corte duro"
checa "descarta o que não foi commitado" [ ! -e "$repo/lixo.txt" ]
checa "mantém o que foi commitado" no_head t1-parte
checa "a iteração seguinte continua e termina o ticket" feitos "1 "

echo "Ticket bloqueado"
fila=$(issue 1 OPEN ready-for-agent "" && issue 2 OPEN ready-for-agent "")
roda 5 "parcial 1" "bloqueado 1" "feito 2" "revisa 2"
checa "não revisa parcial nem bloqueado" rodou "parcial 1 padrão aviso;bloqueado 1 padrão aviso;feito 2 padrão aviso;revisa 2 opus"
checa "devolve o #1 para humano" contem "$FAKE/gh.log" "edit 1 --remove-label ready-for-agent --add-label ready-for-human"
checa "comenta onde ficou o trabalho" contem "$FAKE/gh.log" "comment 1"
checa "guarda o trabalho num branch local" git -C "$repo" cat-file -e main-bloqueado-1:t1-parte
checa "tira o trabalho do branch do PR" eval '! no_head t1-parte'
checa "segue para o #2" feitos "2 "

echo "Verificação falhando depois do commit"
fila=$(issue 1 OPEN ready-for-agent "")
roda 5 "quebra 1" "revisa 1" "quebra 1" "revisa 1" "quebra 1" "revisa 1" "feito 1"
checa "desfaz os commits da iteração" eval '! no_head quebrado'
checa "anota o motivo" contem "$repo/.afk/progresso.md" "make verificar falhou"
checa "para depois de 3 falhas seguidas" chamadas 6
checa "sai com erro" [ "$saida" = 1 ]
checa "não marca afk-feito" eval '! contem "$FAKE/gh.log" afk-feito'

echo "Revisão quebra a verificação"
roda 1 "feito 1" "revisa_quebra 1"
checa "o portão roda depois da revisão e desfaz a iteração inteira" eval '! no_head t1 && ! no_head quebrado'
checa "não marca afk-feito" eval '! contem "$FAKE/gh.log" afk-feito'

echo "Revisão sem sinal"
roda 1 "feito 1" "revisa_mudo 1"
checa "conta como falha" contem "$repo/.afk/progresso.md" "a revisão não terminou"
checa "não marca afk-feito" eval '! contem "$FAKE/gh.log" afk-feito'
checa "tira o ticket do branch do PR" eval '! no_head t1 && git -C "$repo" cat-file -e main-parcial-1:r1'

echo "Revisão com erro de ambiente"
export AFK_MODELO_REVISOR=sonnet
roda 5 "feito 1" "revisa_erro 1"
unset AFK_MODELO_REVISOR
checa "usa AFK_MODELO_REVISOR" rodou "feito 1 padrão aviso;revisa_erro 1 sonnet"
checa "sai com 2" [ "$saida" = 2 ]
checa "não marca afk-feito" eval '! contem "$FAKE/gh.log" afk-feito'
checa "tira o ticket do branch do PR" eval '! no_head t1 && git -C "$repo" cat-file -e main-parcial-1:t1'

echo "Parciais seguidas"
roda 5 "parcial 1" "parcial 1" "parcial 1"
checa "devolve para humano na 3ª parcial" contem "$FAKE/gh.log" "edit 1 --remove-label ready-for-agent"
checa "guarda o trabalho" git -C "$repo" cat-file -e main-bloqueado-1

echo "Fila sem tickets elegíveis"
fila=$(
  issue 1 OPEN ready-for-agent "" "Bloqueado por: #2"
  issue 2 OPEN ready-for-human ""
  issue 3 OPEN ready-for-agent 2
)
roda 5
checa "não chama o claude" chamadas 0
checa "sai com 0" [ "$saida" = 0 ]
checa "anota sem_tickets" contem "$repo/.afk/progresso.md" sem_tickets

echo "PR anterior sem merge"
fila=$(issue 1 OPEN ready-for-agent,afk-feito "")
roda 5
checa "não começa" chamadas 0
checa "sai com 3" [ "$saida" = 3 ]

echo "Hook de contexto"
transcricao=$tmp/transcricao.jsonl
uso() { printf '{"type":"assistant","isSidechain":%s,"message":{"usage":{"input_tokens":1,"cache_read_input_tokens":%s,"cache_creation_input_tokens":0}}}\n' "$1" "$2"; }
hook() { echo "{\"transcript_path\": \"$transcricao\"}" | "$aqui/hook-contexto.sh"; }
{ uso false 50000; uso false 119000; uso true 500000; } > "$transcricao"
checa "abaixo do aviso: silêncio" [ -z "$(AFK_AVISO_TOKENS=120000 hook)" ]
uso false 130000 >> "$transcricao"
checa "acima do aviso: bloqueia com instrução" eval '[ "$(AFK_AVISO_TOKENS=120000 hook | jq -r .decision)" = block ]'
checa "fora do loop: silêncio" [ -z "$(hook)" ]

exit "$falhou"
