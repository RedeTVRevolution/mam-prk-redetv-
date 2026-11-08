# Cópia limpa e áudio por sete dias; download pelo proxy de 480p

Em 07/11/2026, Bruno decidiu apagar a cópia limpa e o áudio a partir de 7 dias da criação dos objetos no bucket de aceitos (#502). O original em alta resolução fica no arquivo da RedeTV; manter outra cópia no MAM faria o custo crescer todo mês. Esta é a segunda exceção à regra de “nunca apagar” da ADR 0010: alcança só arquivos de entrada, nunca saídas do modelo. A purga continua sendo a exceção que apaga decupagens e correções.

O reprocessamento fecha exatamente 7 dias após o `criado_em` do Job, inclusive quando parte de uma falha, de uma etapa escolhida ou do `make reprocessar-versao`. Depois é preciso enviar o vídeo de novo a partir do arquivo da RedeTV. O pedido da URL de upload cria o Job antes da validação criar os objetos: o bloqueio vem antes do apagamento, e a mensagem não afirma que os arquivos já foram apagados. A API fornece `reprocessavel_ate`; a tela usa esse prazo.

O Storage apaga de forma assíncrona, a partir do sétimo dia, sem prazo garantido. A regra só alcança `copia_limpa.mp4` e `audio.wav`; proxy, quadros, transcrição, leitura da tela e demais JSONs ficam. O soft delete permanece em 7 dias, e o apagamento direto do Standard não tem taxa. A contagem da lixeira consulta a existência real dos arquivos, independentemente da idade.

O download sempre entrega o proxy de 480p, mesmo antes do prazo, com o nome sem extensão seguido de `.480p.mp4`. A resposta avisa onde está a cópia em alta resolução, inclusive para sistemas, e a tela mostra o aviso com o nome original antes de abrir a URL. A auditoria `video.baixado` continua sendo gravada antes da resposta.

Uma fila parada por dias pode deixar um vídeo ainda no pipeline sem os arquivos de entrada: os quadros-chave podem falhar e a transcrição sem áudio pode ficar vazia. Aceitamos esse limite; é preciso reenviar o vídeo. Uma versão nova do pipeline só alcança vídeos novos e recentes.
