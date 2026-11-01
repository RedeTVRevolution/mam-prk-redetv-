# MAM RedeTV

Decupagem automática do acervo de vídeo da RedeTV com IA: descrever o que aparece, o que se diz e o que se anuncia em cada vídeo, com tempos, para que editores achem e reaproveitem material.

## Linguagem

### Vídeo e programa

**Decupagem**:
Documento que descreve o conteúdo de um vídeo com tempos: pessoas, pautas, planos, comerciais e transcrição.
_Evitar_: resultado, insights

**Job**:
Um pedido de decupagem de um vídeo, do registro ao fim do processamento.
_Evitar_: tarefa, pedido

**Etapa**:
Passo do processamento de um Job que o Workflows roda (validação, transcrição, leitura da tela, análise, identificação, referências, comparação, quadros-chave, indexação, nessa ordem), com início, fim e resultado (`concluida` ou `falhou`). A falha de uma etapa depois do `concluido` não muda o estado do Job.
_Evitar_: fase

**Reprocessar**:
Refazer um Job a partir da primeira etapa que falhou, sem enviar o vídeo de novo (`POST /v1/jobs/{id}/reprocessar`, permissão `video.reprocessar`). As etapas anteriores não rodam; só vale para falha de etapa, e a falha do arquivo pede novo envio. Cada reprocessamento vai à auditoria (`video.reprocessado`).
Há dois jeitos. **Reprocessar o que falhou** (`video.reprocessar`, Operador e acima) recomeça da etapa que falhou e só vale para falha. **Reprocessar a partir de uma etapa escolhida** (`video.reprocessar_etapa`, Curador e Administrador) refaz um vídeo `concluido` e bom, por exemplo por uma instrução nova: o corpo do pedido traz a `etapa` (análise, identificação, quadros-chave ou indexação) e o motivo, obrigatório, e a auditoria marca `etapa_escolhida`. Com a análise escolhida o Job volta a `analisando`, a Decupagem some até a nova análise terminar e o progresso das janelas é descartado, para o modelo rodar de novo em todas; com as outras, o Job continua `concluido`.

**Bloco**:
Segmento editorial de um programa de TV, como a abertura ou o trecho entre dois intervalos.
_Evitar_: segmento, parte

**Plano**:
Trecho do vídeo entre dois cortes de câmera. A descrição (ambiente, ação, objetos) é do intervalo entre cortes, não do trecho que o modelo descreveu; a tela preta é um plano com ambiente "tela preta".
_Evitar_: cena, take

**Plano limpo**:
Plano sem GC e sem ninguém falando para a câmera, reaproveitável como B-roll.

**Texto na tela**:
GC, tarja, legenda, placar, chamada, logo ou QR code, com o texto lido e os tempos. O Gemini lê o texto; os tempos são medidos nos quadros pelo OCR (`medido`), e o texto que o OCR não acha fica com o tempo do Gemini e `medido=False`.
_Evitar_: lettering

**Perfil do programa**:
Contexto fixo de um programa (apresentadores, repórteres, merchandising frequente), em `api/programas.toml`, que a instrução do modelo recebe quando o Job informa o programa.

### Pessoas e evidência

**Catálogo de pessoas**:
Dado vivo no Firestore (`api/catalogo.py`) com as pessoas frequentes da emissora, em todos os programas: cada pessoa tem id estável, nome, papel, apelidos e as referências de rosto ligadas a ela (origem `web` ou `acervo`). Começa pela carga do `programas.toml` e cresce com as confirmações. A Decupagem aponta para ela por `catalogo_id`, gravado quando a correção de nome da revisora casa com uma só pessoa do catálogo, ou quando o código confirma o nome por uma prova (que acha a pessoa no catálogo por nome ou apelido, ou a acrescenta).
_Evitar_: base de famosos

**Nome confirmado / palpite**:
`Pessoa.estado_do_nome`. Confirmado é o nome com uma prova que o código conferiu (`api/identificacao.py`): um GC ou tarja com o nome ou apelido, ou o nome ou apelido dito no texto original do Whisper, enquanto a pessoa está na imagem e sem outra pessoa sem nome na imagem no mesmo intervalo. O nome que o modelo deu sem prova conferida é palpite. Estar no perfil ou no catálogo torna a pessoa candidata e não confirma nome; `contexto` não é prova. A correção da revisora (`origem` `revisao`) vale mais e nenhum reprocessamento a sobrescreve.
_Evitar_: aceitar `fontes_do_nome` como declarada pelo modelo

**Modelo forte**:
O 3.8 Flash (`api/modelo_forte.py`), que olha cada pessoa "não identificado" depois da análise: as de mesma descrição são uma pessoa só, uma chamada cada (até um limite por vídeo, as de mais tempo na imagem primeiro), com 2 ou 3 quadros das aparições mais longas da cópia limpa e todas as pistas do vídeo. O nome que ele dá passa pela conferência de provas: com prova é `confirmado` (origem `modelo_forte`), sem prova é `palpite`. Nunca identifica pela memória.

**Aparição**:
Pessoa visível na imagem; só ela conta como tempo de tela.

**Menção**:
Nome dito na fala ou escrito na tela, sem prova de que a pessoa aparece.
_Evitar_: citação como sinônimo de aparição

**Evidência**:
O que sustenta uma ocorrência: rosto, GC, fala ou quadro.

**Fonte do nome**:
A prova que confirma o nome de uma pessoa, conferida pelo código: GC, fala ou referência de rosto. Estar no perfil ou no catálogo torna a pessoa candidata, mas não confirma o nome; o modelo nunca identifica pela memória.

**Referência de rosto**:
Foto de uma pessoa nomeada, guardada para comparar com o rosto da tela: 3 fotos diferentes por nome, buscadas na web, com a página de origem.
Quem as busca é o Job `mam-referencias` (`api/referencias_job.py`), o único com internet. Recebe só nomes: `NOMES` e `PROGRAMA`, ou `JOB_ID`, e então lê a lista que o Job de identificação gravou (`<job>.nomes_a_buscar.json`, com os candidatos e os palpites sem referência válida e o programa). Lê a chave do SerpAPI no Secret Manager, trata toda imagem como entrada hostil, guarda no bucket de referências só as que o modelo confere e liga ao catálogo. O nome fora do catálogo (palpite) ganha as fotos sob o prefixo `palpites/` (ver **Fotos de palpite**); o ambíguo não busca. Há um limite de buscas por vídeo (`LIMITE_DE_BUSCAS_POR_VIDEO`), e cada busca leva o rótulo de custo. O `make carregar-catalogo` não apaga os rostos já guardados.
_Evitar_: galeria facial

**Fotos de palpite**:
As 3 fotos de referência de um palpite que o catálogo não conhece, guardadas sob `palpites/<nome-normalizado>/` no bucket das referências, com os dados em `rostos.json` ao lado (`api/rostos_dos_palpites.py`). Uma regra de ciclo de vida do bucket apaga só esse prefixo, em 30 dias (`prazo_dos_palpites_dias`). Só o nome que a comparação confirma entra no catálogo, e aí as fotos passam para `referencias/<id>/`.

**Palpite**:
Nome que o modelo dá sem prova. Vira nome confirmado se o rosto bater com as 3 referências do nome; senão, é descartado ou fica como não confirmado, fora dos relatórios de tempo de tela.

**Comparação**:
Passo que compara as pessoas sem nome e os palpites do vídeo com as fotos de referência (`api/comparacao.py`, `comparar`). Primeiro a escolha às cegas: o modelo vê as fotos com rótulos A, B… embaralhados a cada chamada e nunca recebe os nomes; o código traduz o rótulo. Depois a conferência foto a foto: uma chamada por foto, com a confiança de cada uma; o nome só se confirma com as 3 fotos no limiar ou acima. Confirma com `fontes_do_nome=["referencia"]`, liga a pessoa ao catálogo e propõe sugestões para o perfil. O palpite fora do catálogo concorre com as fotos de palpite; ao confirmar, entra no catálogo (o papel vem da aparição). Há um limite de pessoas por vídeo; as que passam dele ficam como palpite não confirmado.

**Veredito**:
Registro, por pessoa, do que a comparação decidiu (confirmado, palpite descartado, palpite não confirmado ou sem resultado), com as 3 fotos e a confiança de cada uma. Um palpite trocado por outro nome confirmado fica confirmado e marcado como descartado. Serve à auditoria e à tela: a rota `GET /v1/jobs/{id}/pessoas/{pessoa}/referencias` (só com `decupagem.ver`, URLs assinadas de 5 min, sem cache) devolve as fotos do veredito com a página, o domínio e se cada uma confere, para o painel de comparação do Visualizador, aberto pelo selo "Rosto". A `Pessoa` não guarda a prova.

**Palpite descartado / palpite não confirmado**:
Descartado: o nome foi recusado (a escolha apontou outro candidato ou nenhum, ou o nome está ou fica confirmado para outra pessoa do vídeo) e a pessoa volta a "não identificado". Não confirmado: o nome continua palpite porque não há referência para conferir, o limite de pessoas passou ou uma foto ficou abaixo do limiar.

### Busca

**Momento**:
Unidade de busca: um plano ou um evento da decupagem, com início e fim.

**Objeto**:
Peça visível na Decupagem (`objetos`, esquema 1.4): roupa, calçado, acessório, o que alguém segura ou um objeto em cena (veículo, produto, eletrônico, animal, comida), com categoria, tipo, cor base, tom, marca legível, o dono (`pessoa` e `relacao`, nulos em cena) e os tempos. A categoria diz o que a coisa é (`em_cena` e `na_mao` só quando nenhuma outra serve). Produto mostrado num telão ou em gráfico entra como objeto, com o detalhe "no telão" ou "em gráfico". A busca filtra pelo objeto inteiro, não por itens soltos no plano.

**Ocorrência**:
Algo detectado num momento: pessoa, marca, objeto ou pauta.

### Arquivos

**Quarentena**:
Lugar onde um vídeo enviado espera a validação; nada é processado a partir dela.

**Cópia limpa**:
O MP4 aceito pela quarentena, regravado só com as faixas de vídeo e áudio (as faixas de dados, como a de timecode, ficam de fora), sem metadados e sem recodificar. É dele que todo o processamento parte.
_Evitar_: cópia limpa 720p, original tratado

**Timecode de origem**:
O timecode inicial lido da faixa de timecode do arquivo enviado, guardado no Job e levado ao bloco `video` da Decupagem. Ausente quando o arquivo não tem a faixa.
_Evitar_: timecode inventado, 00:00:00:00 por padrão

**Proxy de escalonamento**:
Cópia do vídeo em resolução maior, usada só para reanalisar trechos no escalonamento.
_Evitar_: cópia limpa 720p

### Análise

**Janela de análise**:
Trecho contínuo do vídeo que o modelo analisa de uma vez, com uma margem de contexto em cada borda.
_Evitar_: bloco, chunk, pedaço

**Escalonamento**:
Reanálise de um trecho por um modelo mais forte, em resolução maior, quando a primeira passada teve dúvida ou o trecho caiu na amostra de controle.

**Amostra de controle**:
Janelas sorteadas que também passam pelo escalonamento, para medir o que a primeira passada não viu, inclusive o que ela nem marcou como dúvida.

**Chave de conteúdo**:
Identidade de uma decupagem: o arquivo, a versão do pipeline e as opções que mudam a saída. Dois jobs com a mesma chave de conteúdo compartilham um processamento.

**Chave de idempotência**:
Identificador de uma intenção de envio do cliente, reutilizado em todas as repetições dessa intenção.

### Revisão

**Correção**:
Alteração humana sobre a saída do modelo, guardada como camada separada, com autor, data e motivo; a saída original nunca é apagada.
_Evitar_: edição, ajuste

**Correção pendente**:
Correção de Editor, num tipo que exige aprovação, que espera a decisão de um Curador; fica no histórico e fora da decupagem entregue até ser aprovada (passa a valer) ou recusada (nunca vale).

### Acesso

**Conta local**:
Usuário criado no próprio sistema de identidade, independente do login do sistema legado da RedeTV.

**Administrador**:
Papel com todas as permissões, dado automaticamente aos administradores de emergência.

**Administrador de emergência**:
Conta local que recebe o papel Administrador (acesso total), segundo fator obrigatório e alerta a cada login; existe para não depender do login legado.

**Papel**:
Pacote de permissões dado a um usuário, opcionalmente limitado a programas.
_Evitar_: perfil, grupo

**Chave de API**:
Credencial de um sistema consumidor da RedeTV, nunca de uma pessoa.
