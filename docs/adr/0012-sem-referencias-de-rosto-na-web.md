# Sem fotos de referência da web nem comparação de rostos

Substitui a [ADR 0005](0005-identificacao-por-referencia.md). Em 3/11/2026, o Bruno decidiu abandonar a busca de fotos de referência na web e a comparação de rostos com essas fotos.

**O que continua da 0005:** um nome só é confirmado por prova que o código confere, o GC com o nome enquanto a pessoa está na imagem, ou a fala com o nome, conferida no texto original do Whisper. Estar no perfil ou no catálogo torna a pessoa candidata, não confirma. O nome sem prova é palpite, marcado como não confirmado e fora dos relatórios de tempo de tela. O modelo forte (`api/modelo_forte.py`) segue no passo de identificação, olhando as pessoas sem nome com os quadros e as pistas do vídeo.

**O que sai:** as etapas `referencias` e `comparacao` do workflow, os Jobs `mam-referencias` e `mam-comparacao`, o SerpAPI (segredo, conta de serviço, saída para a internet), a rota `GET /v1/jobs/{id}/pessoas/{pessoa}/referencias`, o painel de comparação e a sugestão de perfil que a comparação propunha. A fonte `referencia` não é mais gravada; as Decupagens antigas que a têm continuam abrindo, e a migração a apaga.

**Por quê (medido no dev em 3/11/2026):** a comparação falhou em 100% dos casos (o Gemini 3.8 devolveu rótulo que não existe nas 4 execuções); gastou US$ 2,47 e as referências US$ 1,43, de US$ 3,90 do total a preço cheio, contra US$ 0,48 da decupagem inteira; as referências levavam cerca de 8 min em todo vídeo.

**A perda funcional:** a pessoa sem GC nem fala com o nome fica "não identificado" ou palpite.

**Os dados biométricos saem junto (LGPD, art. 11).** A migração única `make apagar-referencias-web` (`api/apagar_referencias_web.py`) apaga `referencias/` e `palpites/` do bucket de referências, os rostos `origem=web` do catálogo, as sugestões de perfil, os objetos `<job>.comparacao.json` e `<job>.nomes_a_buscar.json` e a fonte `referencia` das Decupagens (o nome que só tinha essa prova volta a palpite). Imprime a contagem antes e depois; rodar de novo não muda nada.

Saiu em 06/11/2026 (decisão do Bruno): as sugestões ao editor (identificar pessoa, pauta do trecho, objeto do visual), as rotas, o painel e a contagem (#487). A migração `make apagar-referencias-web` deixou de apagar as sugestões de perfil.
