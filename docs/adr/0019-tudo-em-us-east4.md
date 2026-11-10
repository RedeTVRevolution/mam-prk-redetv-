# Tudo em us-east4, nada em São Paulo

Todo recurso regional e todo dado do MAM ficam em `us-east4` (norte da Virgínia): Cloud Run (`mam-web` e os Jobs), Workflows, Scheduler, Eventarc, buckets, Firestore, BigQuery, Artifact Registry, KMS e Model Armor. A busca ([ADR 0006](0006-indice-da-busca-nos-eua.md)) e a GPU ([ADR 0007](0007-transcricao-e-ocr-em-gpu-no-us-east4.md)) já estavam lá.

**Decisão de 09/11/2026 — Bruno (spec #535):** o motivo é custo. Em `southamerica-east1`, os Jobs custam cerca de 17% a mais por vCPU·s, o Cloud Build em São Paulo puxa de `us-east4` o cache das imagens de GPU (R$ 66,53 de egress de 02/11 a 09/11, uns R$ 250 por mês), e Storage e Firestore também saem mais baratos. O aval jurídico é o do próprio Bruno. Esta ADR substitui o que as ADRs 0001, 0006, 0007 e 0008 dizem sobre a região: as proibições de guardar dados em `us-east4` e o "Brasil" como lugar dos vídeos, das decupagens, do Firestore e do BigQuery deixam de valer. O Gemini continua no endpoint global ([ADR 0001](0001-gemini-endpoint-global.md)).

## Como ficou no Terraform

- Uma variável de região para tudo o que não é a busca nem a GPU: `regiao` (o dev e o prod a recebem de `GCP_REGION`). `regiao_do_model_armor` e `regiao_do_bigquery` saíram; `regiao_da_busca` e `regiao_gpu` ficam, porque esses recursos não mudam e os testes e o `scripts/checar-nomes-da-nuvem.sh` dependem delas.
- Os nomes novos nascem só no módulo `infra/modulos/mam/`, com a região no nome, porque os de São Paulo existem durante a cópia (o nome do bucket é global e o do dataset é único no projeto): buckets `<projeto>-useast4-<sufixo>` (inclusive o das fontes do build), datasets `mam_decupagens_useast4` e `faturamento_useast4`, banco de segurança `mam-seguranca-useast4`. O banco principal é nomeado, `mam` por padrão, vindo da variável `banco_firestore` (#536); os dois bancos têm proteção contra exclusão e recuperação a um ponto no tempo, como antes. O key ring `mam` e a chave `chaves-de-api` nascem de novo em `us-east4`, com material novo: nenhum sistema legado usa a API hoje, então não há chave para reemitir.
- Os outputs `regiao`, `buckets`, `datasets_bigquery`, `banco_firestore` e `banco_de_seguranca` entregam esses nomes ao wizard da troca.

## Plan só de criação

Mudar a região ou o nome de um recurso força a troca (destruir e criar), e o `make publicar` não pode destruir nada de São Paulo antes da cópia. Por isso o wizard da troca (`scripts/wizard-migracao-us-east4.sh`, #538) tira do estado do Terraform, com `terraform state rm`, os endereços de `infra/migracao-us-east4/enderecos-recriados.txt` antes do `apply`: o plan só cria, e o que existe em São Paulo fica fora do estado, intocado. Um teste (`api/tests/test_infra_migracao_us_east4.py`) recalcula a lista a partir dos `.tf`, então um recurso regional novo que não entre nela quebra o `make verificar`.

## Apagar São Paulo

Depois da cópia e da conferência, o wizard apaga o que sobrou em São Paulo **uma vez só, por `gcloud`**, no mesmo dia. Isso não contradiz a regra "mudança na nuvem só pelo Terraform": esses recursos já não estão no estado, e o Terraform nunca soube apagá-los sem destruir o que o plan não pode destruir. Ficam de fora o key ring do KMS, que o Google não deixa apagar (destrói-se a versão da chave), e o bucket do estado do Terraform, que migra por último (`terraform init -migrate-state`).
