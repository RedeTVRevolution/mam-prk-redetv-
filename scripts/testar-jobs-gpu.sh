#!/usr/bin/env bash
# Teste dos Jobs com GPU depois da publicação (#238), chamado pelo scripts/deploy-dev.sh
# (e por isso também pelo CD). Para um problema de CUDA ou de driver aparecer na
# publicação, e não num vídeo da emissora, roda cada Job com GPU cuja imagem mudou num
# trecho curto de teste (MODO_TESTE=1, api/teste_dos_jobs.py: amostra que já está na
# imagem, nada lido nem gravado nos buckets) e confere o dispositivo e o resultado.
#
# Uso: testar-jobs-gpu.sh NOME,IMAGEM_ANTERIOR,IMAGEM_NOVA...
# Um argumento por Job com GPU; para um Job a mais (o Florence-2, do inventário de objetos),
# basta mais um argumento. IMAGEM_ANTERIOR vazia é a primeira publicação do Job.
#
# Ambiente: GCP_PROJECT_ID, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT, GPU_REGIAO e a espera por
# falta de GPU ou de cota (os outputs gpu_* do Terraform, os mesmos do Workflows):
# GPU_TENTATIVAS (no total), GPU_ESPERA_S (antes da segunda) e GPU_FATOR_DA_ESPERA.
#
# Sai com 0 se tudo passou ou se nenhuma imagem mudou. Se algum teste falhar, volta os
# Jobs que mudaram para a imagem anterior e sai com 1, dizendo qual das três falhas foi:
# "sem GPU" (falta de GPU ou de cota), "a GPU não funcionou" (a instância não tem a GPU
# ou o modelo não roda nela) ou "resultado errado" (rodou, e o texto não confere).
set -uo pipefail

: "${GCP_PROJECT_ID:?}" "${GOOGLE_IMPERSONATE_SERVICE_ACCOUNT:?}" "${GPU_REGIAO:?}"
: "${GPU_TENTATIVAS:?}" "${GPU_ESPERA_S:?}" "${GPU_FATOR_DA_ESPERA:?}"

gc() { gcloud --project "$GCP_PROJECT_ID" --impersonate-service-account "$GOOGLE_IMPERSONATE_SERVICE_ACCOUNT" "$@"; }

# O que uma execução que falhou diz, em uma das três falhas. O código de saída do Job
# (SAIDA_SEM_GPU = 20 e SAIDA_RESULTADO_ERRADO = 21, em api/teste_dos_jobs.py) vem na mensagem do gcloud; falta de GPU ou de cota vem como erro de capacidade,
# antes de o contêiner existir. Uma falha que não é nenhuma das duas conta como "a GPU não
# funcionou" e não tenta de novo.
classificar() {
  if grep -qE 'exit\(21\)' <<<"$1"; then
    echo resultado_errado
  elif grep -qE 'exit\(20\)' <<<"$1"; then
    echo gpu_nao_funcionou
  elif grep -qiE 'quota|capacity|exhausted|insufficient|no available|out of stock|zonal' <<<"$1"; then
    echo sem_gpu
  else
    echo gpu_nao_funcionou
  fi
}

# Um Job: até GPU_TENTATIVAS execuções, com espera crescente, só quando falta GPU ou cota.
# Escreve o veredito (ok, sem_gpu, gpu_nao_funcionou, resultado_errado) no arquivo dado.
testar_um() {
  local job=$1 veredito=$2 inicio=$SECONDS espera=$GPU_ESPERA_S tentativa saida
  for ((tentativa = 1; tentativa <= GPU_TENTATIVAS; tentativa++)); do
    echo "[$job] teste, tentativa $tentativa de $GPU_TENTATIVAS"
    if saida=$(gc run jobs execute "$job" --region "$GPU_REGIAO" --wait \
      --update-env-vars MODO_TESTE=1 2>&1); then
      echo "[$job] passou em $((SECONDS - inicio)) s"
      echo ok >"$veredito"
      return
    fi
    echo "$saida" | sed "s/^/[$job] /"
    local motivo
    motivo=$(classificar "$saida")
    if [[ $motivo != sem_gpu ]]; then
      echo "$motivo" >"$veredito"
      return
    fi
    if ((tentativa < GPU_TENTATIVAS)); then
      echo "[$job] sem GPU ou sem cota: nova tentativa em $espera s"
      sleep "$espera"
      espera=$((espera * GPU_FATOR_DA_ESPERA))
    fi
  done
  echo sem_gpu >"$veredito"
}

mudaram=()
for argumento in "$@"; do
  IFS=, read -r job anterior nova <<<"$argumento"
  if [[ $anterior == "$nova" ]]; then
    echo "[$job] a imagem não mudou nesta publicação: sem teste."
  else
    mudaram+=("$argumento")
  fi
done

if ((${#mudaram[@]} == 0)); then
  echo "Nenhuma imagem com GPU mudou nesta publicação: teste dos Jobs com GPU pulado."
  exit 0
fi

pasta=$(mktemp -d)
trap 'rm -rf "$pasta"' EXIT
inicio=$SECONDS
echo "Testando os Jobs com GPU que mudaram, em paralelo: ${#mudaram[@]}."
for argumento in "${mudaram[@]}"; do
  IFS=, read -r job _ _ <<<"$argumento"
  testar_um "$job" "$pasta/$job.veredito" >"$pasta/$job.log" 2>&1 &
done
wait
echo "O teste dos Jobs com GPU levou $((SECONDS - inicio)) s."

falhou=0
for argumento in "${mudaram[@]}"; do
  IFS=, read -r job _ _ <<<"$argumento"
  cat "$pasta/$job.log"
  case $(cat "$pasta/$job.veredito" 2>/dev/null) in
    ok) ;;
    sem_gpu)
      echo "ERRO sem GPU: o Job $job não conseguiu GPU ou cota em $GPU_TENTATIVAS tentativas." >&2
      falhou=1
      ;;
    resultado_errado)
      echo "ERRO resultado errado: o Job $job rodou na GPU, e o texto lido não é o esperado." >&2
      falhou=1
      ;;
    *)
      echo "ERRO a GPU não funcionou: o Job $job não rodou o modelo na GPU." >&2
      falhou=1
      ;;
  esac
done

if ((falhou)); then
  for argumento in "${mudaram[@]}"; do
    IFS=, read -r job anterior _ <<<"$argumento"
    if [[ -n $anterior ]]; then
      echo "Voltando o Job $job para a imagem anterior: $anterior"
      gc run jobs update "$job" --region "$GPU_REGIAO" --image "$anterior" ||
        echo "ERRO não consegui voltar o Job $job para $anterior: volte à mão." >&2
    else
      echo "O Job $job é da primeira publicação: não há imagem anterior para voltar." >&2
    fi
  done
  exit 1
fi
