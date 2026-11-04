#!/usr/bin/env bash
# Passo 3: envia o arquivo pela URL de upload do passo 2 (upload retomável do Cloud
# Storage: o POST abre a sessão, o PUT manda os bytes). Não precisa da chave de API.
# Uso: ARQUIVO=video.mp4 ./3-enviar-o-video.sh   (lê job.json)
set -euo pipefail

TAMANHO=$(wc -c < "$ARQUIVO" | tr -d ' ')
URL_DE_UPLOAD=$(jq -r .url_de_upload job.json)

SESSAO=$(curl --fail-with-body -sS -i -X POST "$URL_DE_UPLOAD" \
  -H "Content-Type: video/mp4" \
  -H "x-goog-resumable: start" \
  -H "x-upload-content-length: $TAMANHO")
DESTINO=$(printf '%s' "$SESSAO" | awk 'tolower($1) == "location:" {print $2}' | tr -d '\r')
echo "$DESTINO" > sessao.txt

# Se cair no meio, rode de novo só este PUT: pergunte quanto já chegou com
#   curl -i -X PUT "$DESTINO" -H "Content-Range: bytes */$TAMANHO" -H "Content-Length: 0"
# (308 + cabeçalho Range: bytes=0-N) e mande o resto com Content-Range: bytes N+1-fim/total.
curl --fail-with-body -sS -X PUT "$DESTINO" \
  -H "Content-Type: video/mp4" \
  --data-binary @"$ARQUIVO"
echo
echo "Enviado. O Job passa a validando."
