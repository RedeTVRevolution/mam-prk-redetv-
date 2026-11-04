#!/usr/bin/env bash
# `make verificar`: falha se um arquivo de texto versionado não terminar com quebra de linha.
# Sem ela, a próxima linha acrescentada cola na última: foi assim que a regra
# `.playwright-mcp/` do .gitignore deixou de valer em silêncio (#354).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

falhou=0
# git grep -I lista só os arquivos de texto versionados; -z evita as aspas do Git em nomes com acento.
while IFS= read -r -d '' arquivo; do
  if [[ -s $arquivo && -n $(tail -c 1 "$arquivo") ]]; then # $( ) come a quebra final
    echo "checar-fim-de-arquivo: $arquivo não termina com quebra de linha" >&2
    falhou=1
  fi
done < <(git grep -Ilz '')
exit "$falhou"
