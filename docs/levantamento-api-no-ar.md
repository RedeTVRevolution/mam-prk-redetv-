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
4. **`falhou` gravado pelo Workflows**: o `validacao.workflow.yaml` marca `falhou` direto no Firestore quando a execução de um Job estoura tempo ou memória (quatro passos `marca_como_falhou`). Esses não publicam. Cobrir pede um passo de publicação no Workflows ou um Job de "evento de fim".
5. **Evento perdido na publicação**: se o Pub/Sub recusa a publicação, o erro vai ao log e o Job segue (o estado já mudou). Reconciliar (um Job `concluido` sem evento entregue) pede o registro da entrega por Job.
6. **Chave de idempotência do `POST /v1/jobs`** (48 h, TTL do Firestore): o plano descreve, mas o código não tem `Idempotency-Key` e o Terraform não tem política de TTL.
7. **`Retry-After` e limite de fila na API**: hoje só o Cloud Armor limita (429 na borda); o limite do plano na própria API (fila acima do teto → 429 com `Retry-After`) não existe.
8. **Alerta da fila de mortas** (mensagens não confirmadas na assinatura `mam-eventos-do-job-mortos`): sem ele ninguém vê o webhook que desistiu.
