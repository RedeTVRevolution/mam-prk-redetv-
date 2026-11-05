# Guia do desenvolvedor: enviar vídeos ao MAM e receber a decupagem

Para quem integra um sistema da RedeTV ao MAM. O contrato completo, rota por rota, está em [`openapi.json`](openapi.json) (OpenAPI 3, gerado do código). Cada passo abaixo tem um exemplo pronto em `curl` e outro em Python, em [`exemplos/`](exemplos/). Eles leem `URL` (o endereço da API) e `CHAVE` (a sua chave) do ambiente.

O caminho inteiro: **conferir a chave → registrar o vídeo → enviar o arquivo → acompanhar o Job → buscar a decupagem**.

## 0. Pedir uma chave de teste no dev

Peça ao **Bruno Mosconi** (responsável pelo MAM). Diga:

1. o **nome do sistema** (aparece na auditoria e identifica quais Jobs são seus);
2. os **escopos** de que precisa: `criar` (registrar vídeos), `ler` (consultar Jobs e buscar a decupagem), `cancelar`;
3. a **URL do webhook** que vai receber o aviso de fim do Job (opcional; veja o passo 5).

Quem emite a chave roda `make emitir-chave SISTEMA="Nome do sistema" ESCOPOS=criar,ler,cancelar`. **A chave aparece uma vez**: guarde-a num cofre, nunca no código nem no repositório. Se vazar, peça a revogação e outra chave. Cada chave só enxerga os Jobs do próprio sistema.

Toda chamada leva a chave no cabeçalho `X-API-Key`.

## 1. Conferir a chave

`GET /v1/eu` devolve o sistema e os escopos da chave. Exemplos: `exemplos/curl/1-conferir-a-chave.sh` e `exemplos/python/1-conferir-a-chave.py`.

`GET /v1/programas` lista os programas aceitos no campo `programa` do passo 2.

## 2. Registrar o vídeo

`POST /v1/jobs` cria o Job e devolve a `url_de_upload`. Corpo: `nome` (termina em `.mp4`, sem `/`), `tamanho_bytes` (de 1 byte a 4 GiB), `tipo` (sempre `video/mp4`), `data_exibicao` (obrigatória, texto `AAAA-MM-DD`, nunca depois de hoje em Brasília) e, se souber, `programa`. Responde **202**.

Mande sempre um `Idempotency-Key` (um UUID novo por vídeo): veja o passo 7. Exemplos: `exemplos/curl/2-registrar-o-video.sh` e `exemplos/python/2-registrar-o-video.py`.

O `programa` vem do seu sistema, nunca dos metadados do arquivo (`title` e `artist` do MP4 não são confiáveis).

## 3. Enviar o arquivo

O MAM **não busca** o arquivo: quem envia é você, pela `url_de_upload` (ADR 0011). O sistema interno da RedeTV não sai para a internet, então o caminho é um **serviço intermediário**, com acesso à internet, que pega o vídeo no sistema interno e o envia.

- É um **upload retomável** do Cloud Storage: um `POST` abre a sessão (cabeçalhos `x-goog-resumable: start` e `x-upload-content-length`; a resposta traz o `Location` da sessão) e um `PUT` nesse endereço manda os bytes. A URL não usa a sua chave de API.
- Se a conexão cair, pergunte quanto já chegou com `PUT` vazio e `Content-Range: bytes */TOTAL` (resposta 308 com `Range: bytes=0-N`) e mande o resto com `Content-Range: bytes N+1-FIM/TOTAL`.
- Envie com **nome `.mp4` e `tipo` `video/mp4`**, sem recodificar. Os arquivos da RedeTV são MP4 com extensão `.mov` (H.264 1280x720, 29,97 fps, AAC estéreo 48 kHz): só troque o nome. Outro `tipo` dá 415.
- Em `prod`, o upload só é aceito a partir dos **IPs da RedeTV**: o serviço intermediário precisa sair por eles.
- A URL vale por um prazo; passado ele, o Job falha com `upload_expirado`.
- A `timecode_origem` das decupagens da RedeTV não é o timecode da fita: a faixa `tmcd` desses arquivos vem zerada.

Exemplos: `exemplos/curl/3-enviar-o-video.sh` e `exemplos/python/3-enviar-o-video.py`. Quando o arquivo chega, o Job passa a `validando` sozinho.

## 4. Acompanhar o Job

`GET /v1/jobs/{job_id}` devolve o `estado`: `aguardando_upload` → `validando` → `analisando` → `concluido`, ou `falhou` (com `codigo_falha`) ou `cancelado`. `GET /v1/jobs` lista os seus Jobs (paginado pelo cabeçalho `X-Proximo-Cursor`). `DELETE /v1/jobs/{job_id}` cancela um Job que não terminou.

`codigo_falha`: `formato_invalido`, `arquivo_corrompido`, `codec_nao_suportado`, `duracao_excedida` e `upload_expirado` são do arquivo ou do envio (corrija e registre um vídeo novo); `analise_falhou`, `transcricao_falhou`, `ocr_falhou` e `processamento_interrompido` são do MAM: o time do MAM reprocessa, não precisa reenviar.

Prefira o webhook (passo 5). A consulta é o plano B, com espera de alguns segundos entre as chamadas. Exemplos: `exemplos/curl/4-acompanhar-o-job.sh` e `exemplos/python/4-acompanhar-o-job.py`.

Para reproduzir ou baixar o vídeo de um Job concluído: `GET /v1/jobs/{job_id}/reproducao` e `GET /v1/jobs/{job_id}/download` devolvem uma URL temporária.

## 5. Receber o webhook (opcional)

Ao fim de um Job (`concluido` ou `falhou`; o cancelado não avisa), o MAM faz `POST` na URL de webhook do sistema. **Aviso: o registro de webhook ainda não está ligado em produção** (falta o Cofre real): hoje, só a consulta do passo 4 funciona. O webhook só serve se o seu receptor for alcançável de fora; senão, consulte.

Cabeçalhos: `X-Webhook-Id`, `X-Webhook-Data` e `X-Webhook-Assinatura`. Corpo (JSON): `id`, `tipo` (`job.concluido` ou `job.falhou`), `job_id`, `estado`, `codigo_falha` e `data`.

**Confira a assinatura antes de confiar no corpo**: é o HMAC-SHA256, em hexadecimal, de `<X-Webhook-Data>.<corpo exato>` com o segredo do seu sistema. Recuse (401) data com mais de 5 minutos de diferença do seu relógio. Exemplos: `exemplos/curl/5-verificar-o-webhook.sh` e `exemplos/python/5-verificar-o-webhook.py`.

Como responder: **2xx** é entrega feita; **408, 429 e 5xx** o MAM repete (até 10 tentativas ao todo, com espera crescente de 10 s a 10 min); **outro 4xx** descarta o evento. A entrega é *pelo menos uma vez*: **deduplique pelo `X-Webhook-Id`**, que é o mesmo em toda repetição do evento.

## 6. Buscar o resultado

`GET /v1/jobs/{job_id}/decupagem` devolve a Decupagem (pautas, pessoas, planos, comerciais, transcrição e textos na tela, com tempos). `GET /v1/jobs/{job_id}/decupagem/download` devolve o mesmo conteúdo como arquivo. Antes de `concluido` dá 409. Exemplos: `exemplos/curl/6-buscar-a-decupagem.sh` e `exemplos/python/6-buscar-a-decupagem.py`.

## 7. Idempotência e novas tentativas

- **Repetir o registro é seguro** com o mesmo `Idempotency-Key` e o mesmo corpo: a resposta é **200** (o primeiro pedido foi 202) com o mesmo Job, sem criar outro. Se o Job ainda aguarda upload, vem uma `url_de_upload` nova. A chave é lembrada por **48 h**. Com o mesmo `Idempotency-Key` e outro corpo, a resposta é 409.
- Exemplos: `exemplos/curl/7-repetir-com-idempotencia.sh` e `exemplos/python/7-repetir-com-idempotencia.py`.
- **Quando repetir:** timeout, queda de conexão e `503`. Espere 1 s, 2 s, 4 s... com um limite. Não repita 4xx (corrija o pedido).
- Leituras (`GET`) podem ser repetidas sem risco. O `DELETE` repetido de um Job já cancelado responde 409 `Job em cancelado, não cancelável`: o cancelamento já valeu.

## 8. Erros

Todo erro vem como JSON `{"detail": "<mensagem>"}` (no 422 de validação, `detail` é uma lista). O OpenAPI traz o exemplo de cada um.

| Status | Mensagem (`detail`) | O que fazer |
|---|---|---|
| 401 | `Not authenticated` | Mande a chave em `X-API-Key`. Chave inexistente, revogada ou com erro de digitação também dá 401. |
| 403 | `Chave sem o escopo criar` | A chave não pode criar. Peça uma com o escopo. |
| 403 | `Chave sem o escopo ler` | A chave não pode ler. Peça uma com o escopo. |
| 403 | `Chave sem o escopo cancelar` | A chave não pode cancelar. Peça uma com o escopo. |
| 403 | `Chave sem o escopo criar ou ler` | `GET /v1/programas` pede `criar` ou `ler`. |
| 404 | `Job não encontrado` | O id não existe ou o Job é de outro sistema. |
| 409 | `Idempotency-Key já usada com outro corpo` | Use uma chave nova para um pedido novo. |
| 409 | `Job em <estado>, não concluido` | O Job não terminou ou falhou. Espere o webhook ou consulte o Job. |
| 409 | `Job em <estado>, não cancelável` | O Job já terminou; não há o que cancelar. |
| 415 | `Só video/mp4` | Mande `"tipo": "video/mp4"`. Não recodifique. |
| 422 | `Tamanho fora do limite` | `tamanho_bytes` é zero ou passa de 4 GiB. |
| 422 | `Data de exibição no futuro` | `data_exibicao` é depois de hoje (Brasília). |
| 422 | `Idempotency-Key inválida` | Use um texto simples, como um UUID. |
| 422 | `Cursor inválido` | Use o `X-Proximo-Cursor` da resposta anterior, sem mudar os filtros. |
| 422 | lista de erros (`Erro de validação`) | Um campo está fora do formato (nome sem `.mp4`, nome com `/`, campo desconhecido, `programa` fora de `GET /v1/programas`, `data_exibicao` ausente ou fora de `AAAA-MM-DD`): leia `loc` e `msg` em `detail`. |
| 503 | `Serviço indisponível` | Falha passageira. Repita com espera crescente; no `POST /v1/jobs`, com o mesmo `Idempotency-Key`. |

`<estado>` na mensagem é o estado real do Job, por exemplo `Job em analisando, não concluido`.

## Rotas deste guia

`GET /v1/eu`, `GET /v1/programas`, `POST /v1/jobs`, `GET /v1/jobs`, `GET /v1/jobs/{job_id}`, `DELETE /v1/jobs/{job_id}`, `GET /v1/jobs/{job_id}/reproducao`, `GET /v1/jobs/{job_id}/download`, `GET /v1/jobs/{job_id}/decupagem` e `GET /v1/jobs/{job_id}/decupagem/download`.
