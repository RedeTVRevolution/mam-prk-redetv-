#!/usr/bin/env bash
# `make verificar`: falha se o Dockerfile (alvo validacao) e o scripts/afk/Dockerfile
# não fixarem o mesmo ffmpeg no ARG FFMPEG. O loop AFK testa o validador com o do seu
# contêiner, e o teste só vale se for o da produção.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

versao() {
  local v
  v=$(sed -n 's/^ARG FFMPEG=//p' "$1")
  if [[ -z $v ]]; then
    echo "checar-ffmpeg: ARG FFMPEG não encontrado em $1" >&2
    exit 1
  fi
  echo "$v"
}
producao=$(versao Dockerfile)
afk=$(versao scripts/afk/Dockerfile)

if [[ $producao != "$afk" ]]; then
  echo "O ffmpeg do scripts/afk/Dockerfile ($afk) é diferente do da produção, no Dockerfile ($producao)." >&2
  echo "Atualize o ARG FFMPEG do scripts/afk/Dockerfile para $producao. Se a ideia era trocar a versão da produção, atualize o ARG FFMPEG do Dockerfile para $afk." >&2
  exit 1
fi
