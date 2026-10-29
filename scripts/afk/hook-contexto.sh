#!/usr/bin/env bash
# Hook PostToolUse do loop AFK: manda o agente encerrar a iteração quando o contexto
# passa de AFK_AVISO_TOKENS. Fora do loop a variável não existe e o hook não faz nada.
[ -n "${AFK_AVISO_TOKENS:-}" ] || exit 0
set -euo pipefail

transcricao=$(jq -r .transcript_path)
tokens=$(tail -n 200 "$transcricao" | jq -R 'fromjson? | select(.type == "assistant" and .isSidechain != true)
  | .message.usage | .input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens' | tail -n 1)
[ "${tokens:-0}" -gt "$AFK_AVISO_TOKENS" ] || exit 0

jq -n --arg motivo "Contexto em $tokens tokens, acima do aviso de $AFK_AVISO_TOKENS. Encerre a iteração agora, sem começar nada novo: \
rode make verificar; se passar, faça commit do que está pronto; se não passar, descarte o que quebra (git checkout/git stash) e comite só o que fica verde. \
Acrescente a .afk/progresso.md o que falta fazer no ticket e termine a resposta com <ticket>N</ticket> e <status>parcial</status>. \
A próxima iteração continua o ticket com o contexto vazio." '{decision: "block", reason: $motivo}'
