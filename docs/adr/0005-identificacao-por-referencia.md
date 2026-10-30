# Pessoas identificadas por comparação com fotos de referência, nunca pela memória do modelo

Um nome só é confirmado por uma prova que o código confere: o GC com o nome enquanto a pessoa está na imagem; a fala com o nome, conferida no texto original do Whisper; ou o rosto comparado com as 3 fotos de referência daquele nome. Estar no perfil do programa ou no catálogo torna a pessoa candidata, mas não confirma o nome. Nas medições de 30/10/2026, com o clipe2, o 3.8 Flash chamou o Leão Lobo de "Nelson Rubens" em 2 de 3 rodadas, declarando rosto, fala e contexto. O nome veio da memória do modelo, e a "fala" ("O que aconteceu, Nelson?") era alucinação: o Bruno ouviu o trecho, e nele não se diz "Nelson". Aceitar o que o modelo declara repete esse erro.

As fotos de referência vêm da busca de imagens do Google pelo SerpAPI, num Job com internet que recebe só nomes. Ficam guardadas 3 fotos diferentes de cada nome, com um rosto só em cada, e são reaproveitadas entre vídeos. Num teste de 30/10, as 8 primeiras fotos do Leão Lobo eram todas dele, mas 4 eram da mesma sessão; as miniaturas, sempre de `encrypted-tbn0.gstatic.com` e com 290 a 740 pixels, bastam para ver o rosto. A busca custa US$ 0,01 na conta atual (plano Production); com as fotos guardadas, o volume é de poucas centenas de buscas por mês. Isso põe no escopo uma galeria de rostos, que o plano deixava de fora. Comparar rostos é tratar dado biométrico, sensível pela LGPD (art. 5º, II, e art. 11), e o jurídico da emissora deve saber antes de a PoC virar produto.

Alternativas recusadas:
- **API de busca do Google (Custom Search JSON API):** fechada a clientes novos e desligada em 1º/1/2027.
- **Busca do Google no Vertex (Grounding with Google Search):** os termos proíbem guardar os resultados, montar base com eles e extrair links ou imagens para outro fim. A busca de imagens dela, em Preview, só existe nos modelos que geram imagem.
- **Wikidata:** só o Leão Lobo, dos quatro nomes do catálogo, tem foto lá.

O nome confirmado pelas fotos entra nos relatórios, e a revisora pode corrigi-lo depois. O palpite sem prova fica marcado como não confirmado, fora dos relatórios de tempo de tela.
