# Levantamento: o que a API precisa para rodar no ar (#273)

Comparação das seções "API e segurança" e "Resiliência e duplicidade" do `docs/Plano_MAM.md` com o código (`api/webhook.py`, `api/registrar_webhook.py`, as rotas `/v1`) e com o `infra/`. O texto serve de lista para o PR.

## Entrou neste ticket

- **Pub/Sub dos webhooks** (`infra/modulos/mam/eventos.tf`, `api/eventos_do_job.py`): tópico `mam-eventos-do-job`, assinatura push `mam-entrega-do-webhook` (token OIDC da conta `mam-webhook-push`), fila de mensagens mortas `mam-eventos-do-job-mortos` (10 tentativas, espera de 10 s a 600 s, retenção de 7 dias) e o IAM mínimo: `pubsub.publisher` só no tópico para as contas dos Jobs que terminam um Job, `serviceAccountTokenCreator` na conta do push e `pubsub.publisher` na fila de mortas para o agente de serviço do Pub/Sub.
- **Publicação**: toda transição para `concluido` ou `falhou` feita pelo ciclo de vida nos Jobs de validação, transcrição, OCR e análise publica o evento, com o id que o `X-Webhook-Id` leva em toda tentativa.
- **Entrega**: `POST /interno/webhook` confere o token do Pub/Sub, faz uma tentativa e devolve 503 se o destino falhou de um jeito repetível (o Pub/Sub tenta de novo) ou 204 se entregou ou se repetir não adianta.

## Falta, e vira ticket novo

1. **Cofre real do segredo do webhook** (Secret Manager com CMEK). Sem ele `make registrar-webhook` se recusa a rodar: nenhum sistema tem webhook, então nenhum evento é publicado hoje.
2. **`PortaHttp` real**: o POST que conecta no IP já validado, com o host da URL no SNI e no `Host`, sem seguir redirecionamento.
3. **Ligar a rota do push no `api/main.py`**, com `PUSH_AUDIENCIA` (`mam-webhook-push`) e `PUSH_CONTA` (o e-mail da `mam-webhook-push`) no serviço `mam-web` (depende de 1 e 2). Até lá a assinatura bate num 404, e nada chega a ela.
4. ~~**`falhou` gravado pelo Workflows**~~ (resolvido no #379): depois de cada um dos quatro `falhou` que o `validacao.workflow.yaml` grava, o subworkflow `avisa_o_fim` roda o Cloud Run Job `mam-fim` (`api/fim_do_job.py`, `infra/modulos/mam/fim_do_job.tf`), que publica o evento de fim de Job (webhook) e o evento de uso `fim_de_processamento`, com a mesma forma dos da API. Escolhi o Job, e não o Workflow publicar nos tópicos, porque o Workflows não monta o `Evento` (id, sistema dono, webhook registrado) nem o evento de uso, e duplicaria a regra do `api/`. A falha é reclamada no Firestore (`fim_avisado_no_reprocessamento`) antes de publicar, então a mesma falha marcada duas vezes publica uma vez; o Workflow também não regrava um Job que já está `falhou`. Erro do aviso só vai ao log. Job `cancelado` continua fora.
5. **Evento perdido na publicação**: se o Pub/Sub recusa a publicação, o erro vai ao log e o Job segue (o estado já mudou). Reconciliar (um Job `concluido` sem evento entregue) pede o registro da entrega por Job.
6. **`Retry-After` e limite de fila na API**: hoje só o Cloud Armor limita (429 na borda); o limite do plano na própria API (fila acima do teto → 429 com `Retry-After`) não existe.
7. **Alerta da fila de mortas** (mensagens não confirmadas na assinatura `mam-eventos-do-job-mortos`): sem ele ninguém vê o webhook que desistiu.
