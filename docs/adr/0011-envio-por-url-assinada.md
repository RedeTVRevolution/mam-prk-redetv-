# Um serviço da RedeTV envia o MP4 pela URL assinada; o MAM não busca o arquivo

Decisão do Bruno, em 02/11/2026 (issue #276).

**O envio é pela URL assinada que a API já entrega.** É um upload retomável: o `POST` abre a sessão e o `PUT` envia o arquivo (`api/nuvem.py`). O MAM **não** busca o arquivo no storage da RedeTV.

**Por quê.** O sistema interno da RedeTV não é alcançável pela internet e também não sai para ela. Por isso o MAM buscar o arquivo lá não funciona.

**Como fica.** O desenvolvedor da RedeTV cria um serviço à parte, com acesso à internet, que pega o vídeo no sistema interno e o envia à API do MAM pela URL assinada.

**O que muda na API: nada.** Não há ticket novo. A alternativa (o MAM buscar no storage da RedeTV) exigiria alcançar o sistema interno pela internet, o que não é possível, e foi descartada.

## O que o #277 (guia do desenvolvedor) deve dizer

Visto em 4 arquivos reais da RedeTV (de jun/2025 a 30/10/2026):

- **Rede.** Em `prod`, o upload pela URL assinada só é liberado a partir dos IPs da RedeTV (perímetro VPC-SC, ver o `docs/Plano_MAM.md`): o serviço intermediário precisa sair por eles.
- **Fim do processamento.** Chega por webhook só se o serviço intermediário aceitar chamadas de fora. Se não aceitar, o serviço consulta o status.
- **Formato.** Os arquivos são MP4 com extensão `.mov` (`major_brand: isom`), em H.264 1280x720 a 29,97 fps, com uma trilha AAC estéreo de 48 kHz. A API recusa o nome `.mov` (`_nome_de_arquivo_mp4` em `api/jobs.py`); por isso o serviço envia com nome `.mp4` e `tipo` `video/mp4` (outro tipo dá 415), sem recodificar. A API aceitar `.mov` com conteúdo MP4 fica como opção, sem decisão.
- **Timecode.** A trilha `tmcd` vem sempre zerada (`00:00:00;00`): o `timecode_origem` não é o timecode da fita.
- **Programa.** Vem do sistema legado pelo campo `programa`, nunca dos metadados do arquivo: `title` e `artist` não são confiáveis (um `TARD_20250605_BLU` tinha `artist: TV Fama`).
