# Um serviço da RedeTV envia o MP4 pela URL assinada; o MAM não busca o arquivo

Decisão do Bruno, em 02/11/2026 (issue #276).

**O envio é pela URL assinada que a API já entrega.** É um upload retomável: o `POST` abre a sessão e o `PUT` envia o arquivo (`api/nuvem.py`). O MAM **não** busca o arquivo no storage da RedeTV.

**Por quê.** O sistema interno da RedeTV não é alcançável pela internet e também não sai para ela. Por isso o MAM buscar o arquivo lá não funciona.

**Como fica.** O desenvolvedor da RedeTV cria um serviço à parte, com acesso à internet, que pega o vídeo no sistema interno e o envia à API do MAM pela URL assinada.

**O que muda na API: nada.** Não há ticket novo. A alternativa (o MAM buscar no storage da RedeTV) exigiria alcançar o sistema interno pela internet, o que não é possível, e foi descartada.

## Onde estão os detalhes

Rede (IPs da RedeTV em `prod`), formato dos arquivos (MP4 com extensão `.mov`, enviado com nome `.mp4` e `tipo` `video/mp4`), timecode zerado, programa vindo do sistema legado e fim do processamento por webhook ou consulta estão no guia, `docs/api/guia.md`. A API aceitar `.mov` com conteúdo MP4 fica como opção, sem decisão.
