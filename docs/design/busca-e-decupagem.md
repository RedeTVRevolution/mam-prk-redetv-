# Busca e decupagem

A busca é o ponto de partida do redesenho: é a tela que o editor mais usa, e é ela que diz o que a decupagem precisa guardar. Este documento descreve como a busca da E2 deve responder às consultas das premissas e confere, no esquema 1.2 (`api/decupagem.py`) e na instrução do Gemini (`api/gemini.py`), se os dados que ela exige existem.

## Como a busca funciona

### Do ponto de vista do editor

Uma caixa só, no topo de toda tela, com `/` para focar. O editor escreve o que quer e recebe **vídeos, cada um com os momentos exatos** em que aquilo aparece.

```
sapato vermelho                                            [Buscar]
Na imagem ✓   Citada   Fala   GC   Objeto ✓   Marca     Programa ▾  Ano ▾

38 momentos em 11 vídeos                          Ordenar: relevância ▾

▸ TV Fama · 21/10/2026 · 49:19                               4 momentos
  |····█·········█··█······················█········|
  [quadro] 12:04–12:11  Objeto: sandália vermelha · Mel Breia
  [quadro] 26:40–26:52  Objeto: scarpin vermelho · Luiza Brunet
  [quadro] 28:15–28:19  Objeto: tênis vinho · não identificado
  [quadro] 41:02–41:30  Fala: "…aquele sapato vermelho que ela usou…"

▸ Superpop · 03/02/2019 · 1:58:12                            2 momentos
  …
```

- **Agrupado por vídeo.** Cada vídeo mostra programa, data de exibição, duração, o número de momentos e uma barra com a posição de cada um.
- **Cada momento** traz início e fim, um quadro-chave do próprio momento e o **motivo** em palavras: "Objeto: sandália vermelha · Mel Breia", "Fala: '…'", "GC: SABRINA SATO", "Na imagem (fonte: GC + rosto)".
- **Clique no momento** abre o visualizador naquele tempo, com todos os momentos do resultado marcados na linha do tempo. `N` e `Shift+N` (ou `↓`/`↑` na lista) levam ao momento seguinte e ao anterior, também entre vídeos.
- **Chips de tipo de evidência** separam o que o editor quer de verdade: a Sabrina **na imagem** é diferente da Sabrina **citada** na fala ou num GC. O padrão para pessoa é "na imagem"; para frase entre aspas, "fala".
- **Resultado vazio honesto.** "Nenhuma aparição de Sabrina Sato. 12 menções na fala." com um clique para vê-las. Nunca um resultado "parecido" que não tem a ver.
- **Ordem**: vídeos pelo melhor momento e, no empate, pelo número de momentos; opção de ordenar por data de exibição, porque no acervo o editor costuma querer "a mais recente" ou "a de 2008".

### As consultas das premissas

| Consulta | Como é entendida | O que volta |
| --- | --- | --- |
| `sapato vermelho` | Objeto: categoria `calcado`, tipo `sapato` (que inclui scarpin, sandália, tênis, bota), cor base `vermelho` | Momentos em que um calçado vermelho está na imagem, com quem o usa. Tons da família (vinho, bordô) entram depois dos vermelhos puros |
| `Sabrina Sato` | Pessoa do catálogo, pelo nome, apelido ou grafia aproximada | Aparições, com a fonte do nome. As menções (fala e GC) aparecem num chip à parte, com a contagem |
| `Sabrina Sato de vestido vermelho` | Pessoa + objeto, **ligados**: o vestido é da Sabrina | Só os momentos em que é ela que usa o vestido vermelho, e não alguém ao lado |
| `"promoção imperdível"` | Frase exata na fala | Momentos da transcrição com a frase, com o trecho destacado por posição no texto |
| `Ultrafarma` | Marca do catálogo | Comerciais e merchandising por tipo, mais a marca incidental e a marca em objeto |
| `trânsito à noite` | Conceito visual | Planos pela descrição (o vetor multimodal do quadro saiu no #476) |

### Por trás da tela

1. **Entendimento da consulta.** O 3.5 Flash-Lite preenche um esquema fechado, sem ferramentas: pessoas, objetos (categoria, tipo, cor base), marcas, frase exata, texto livre, tipos de evidência, programa e período. Pessoas e marcas só entram se existirem no catálogo; cores e categorias só da lista fechada. Tudo o mais vira texto livre. As aspas são lidas pelo código, antes do modelo e também no plano B: o que está entre aspas é a frase exata, e só ficam os resultados cujo texto ou descrição contém a frase inteira, com as palavras juntas e na ordem, sem diferenciar acento nem maiúscula (#312). Sem aspas, vale qualquer palavra. As barreiras contra injeção são as de "Busca sem injeção", no [plano](../Plano_MAM.md).
2. **Consulta híbrida** no Agent Retrieval: filtros exatos pelos campos estruturados, mais texto e vetor para o que sobrar. O `textSearch` lê o campo `texto_da_busca`, a cópia de `texto` e `descricao` sem acento nem maiúscula, e a consulta vai normalizada também. Os filtros de permissão são acrescentados pelo servidor depois.
3. **Junção de momentos.** Momentos do mesmo vídeo que casam pelo mesmo motivo e estão a até 3 s um do outro viram um momento só, para não mostrar 15 linhas de "Sabrina na imagem" seguidas.
4. **Agrupamento por vídeo** e ordenação.
5. **Reordenação** pela Ranking API só quando houver texto livre. Consultas puramente estruturadas ("sapato vermelho") já têm a ordem certa pelos filtros.

### A unidade do índice

O [glossário](../../GLOSSARY.md) define o **momento** como a unidade da busca. Proposta para manter o índice do tamanho certo num acervo de 25 anos:

- **Momento de plano**: um documento por plano, com os campos de tudo o que acontece nele: pessoas na imagem, objetos com atributos e dono, textos na tela, marcas, ambiente, externa e período. Quase toda consulta visual cai aqui.
- **Momento de fala**: um por trecho de fala, para a frase exata e o texto.
- **Momento de menção**: um por menção (fala ou texto na tela), para separar "citada" de "na imagem".
- **Momento de pauta e de comercial**: um por item, para "a pauta sobre X" e para os relatórios de marca.

Um objeto não vira documento próprio: ele é campo do momento de plano. A consulta "Sabrina de vestido vermelho" precisa casar o objeto com a pessoa **dentro do mesmo objeto**, e não "tem Sabrina" e "tem vestido vermelho" soltos no plano. Se o Agent Retrieval não filtrar objetos aninhados, o momento leva também chaves combinadas prontas, como `calcado|vermelho|pes:sabrina-sato`, comparadas por igualdade. **Conferir no Agent Retrieval antes da E2.**

## O que a busca exige da decupagem

| Dado | No esquema 1.2? | Situação |
| --- | --- | --- |
| Pessoa na imagem, com tempos | Sim: `Pessoa.na_imagem` | Aparições longas, muitas vezes do tamanho da pauta. Melhora quando os planos vierem dos cortes |
| Pessoa com identidade estável entre vídeos | **Não** | `Pessoa.id` é `pes01`, `pes02`… dentro de cada decupagem, e o nome é texto. A busca por "Sabrina Sato" depende do catálogo de pessoas e das referências de rosto ([ADR 0005](../adr/0005-identificacao-por-referencia.md), #82) |
| Aparição separada de menção | Sim: `na_imagem`, `citada_na_fala`, `citada_no_texto` | Pronto para os chips de evidência |
| Fonte do nome | Sim: `fontes_do_nome` | Pronto para o "motivo" |
| Objeto com tipo | **Parcial**: `Plano.objetos: list[str]` | Texto livre. No clipe4, todos os 7 planos têm só "microfone" ([print](prints/app/07-aba-planos.jpg)) |
| Objeto com cor | **Não** | A cor só aparece no texto livre de `Aparicao.visual` ("terno preto e camisa rosa") |
| Objeto com tempo próprio | **Não** | O objeto herda o plano inteiro |
| Objeto ligado à pessoa que o usa | **Não** | Existe só como frase em `Aparicao.visual`, sem estrutura |
| Marca em objeto (logo na camiseta, produto na mão) | **Não** | `comerciais` cobre a ação comercial e a marca incidental, mas não diz em que objeto nem com quem |
| Texto na tela, com tempos | Sim: `textos_na_tela` | O Flash-Lite devolve a duração do bloco, não a de cada aparição (#76) |
| Fala em trechos curtos | Sim, mas instável | No clipe4, uma fala tem ~80 s ([print](prints/app/10-fala-tocando.jpg)); o Flash-Lite varia de 2 a 12 trechos no mesmo vídeo (#78). O Whisper resolve (#81) |
| Pauta com tempos e pessoas | Sim: `pautas` | Tom em texto livre; lista fechada em #77 |
| Plano pelos cortes reais | **Não** | Na E0, os planos vêm do modelo. A detecção de cortes está no plano (passo 1 de "Vídeos longos") mas não está ligada |
| Quadro-chave do momento | **Não** | `quadro` vazio na E0. A tela usa `<video src="…#t=">` como miniatura (`web/src/Video.tsx:760`): um player por miniatura não serve para uma página de resultados com dezenas de momentos |
| Programa | Sim, no Job | Só os programas cadastrados (aba Programas da administração) |
| Data de exibição | **Não** | O Job não tem data de exibição. É a faceta mais útil num acervo de 25 anos e não sai do nome do arquivo com segurança |

## Mudanças propostas no esquema (1.3)

Uma lista nova, `objetos`, no topo da decupagem, ao lado de `pessoas`. Os objetos de `Plano.objetos` passam para ela, e `Aparicao.visual` fica como resumo legível até a lista nova provar o valor no A/B.

```json
"objetos": [{
  "id": "obj01",
  "categoria": "calcado",
  "tipo": "sandália",
  "cor_base": ["vermelho"],
  "cor": "vermelho vivo",
  "detalhe": "salto alto, tiras finas",
  "marca": null,
  "pessoa": "pes03",
  "relacao": "calca",
  "ocorrencias": [{"inicio": "12:04", "fim": "12:11"}]
}]
```

| Campo | Regra |
| --- | --- |
| `categoria` | Lista fechada: `roupa`, `calcado`, `acessorio`, `na_mao`, `em_cena`, `veiculo`, `outro` |
| `tipo` | Texto curto e no singular ("sandália", "vestido", "bolsa", "troféu"). A busca casa o nome como está: "tênis" acha só tênis e "mocassim" só mocassim (o tipo canônico e os sinônimos da taxonomia não entram na busca; decisão de 10/11/2026) |
| `cor_base` | Lista fechada, até 2 cores: `vermelho`, `laranja`, `amarelo`, `verde`, `azul`, `roxo`, `rosa`, `marrom`, `bege`, `preto`, `branco`, `cinza`, `dourado`, `prateado`, `estampado`. É o que a busca filtra |
| `cor` | Texto livre com o tom ("vinho", "azul-marinho"). É o que a tela mostra |
| `marca` | Só se o logo ou o nome estiver legível na imagem. Nunca deduzida |
| `pessoa` + `relacao` | Id de uma pessoa **da mesma decupagem** e como ela se liga ao objeto: `veste`, `calca`, `usa` (acessório), `segura`. `null` para objeto em cena |
| `ocorrencias` | Intervalos em que o objeto está visível, em MM:SS ([ADR 0003](../adr/0003-tempos-do-modelo-em-mm-ss.md)) |

Consequências no código, para o ticket:
- **Consolidação das janelas.** `unir_pessoas` (`api/pessoas.py`) já devolve o mapa do id antigo para o novo por janela; `objetos[].pessoa` precisa passar por esse mapa, como as pessoas das pautas.
- **Validação.** Um `objetos[].pessoa` que não existe na decupagem é resposta fora do esquema e é refeita.
- **Regra de tempos.** O objeto é um evento visual: ajusta ao corte a até 1 s, como a aparição.
- **Correções.** Tipos novos para a catalogação: `objeto.atributos`, `objeto.dono`, `objeto.acrescentar` e `objeto.nao_existe` (ver [catalogacao-manual.md](catalogacao-manual.md)).
- **Job.** Campo `data_exibicao` (data, opcional), informado no envio pelo editor ou pelo sistema legado.

## Mudanças propostas na instrução do Gemini

A seção 5 da instrução atual ("LOCAIS, OBJETOS E IMAGENS DE APOIO") pede só "objetos de destaque". Proposta: separar os locais do que as pessoas usam e seguram.

```
5. OBJETOS, ROUPAS E ACESSÓRIOS
- Para cada pessoa que aparece na imagem, registre o que ela veste, calça e usa
  (roupa, calçado, acessório) e o que segura na mão, com o id dela em "pessoa".
  Só o que estiver visível; não deduza o calçado se os pés não aparecem.
- Registre também os objetos em cena que alguém poderia procurar no acervo:
  produto, troféu, carro, joia, animal, comida. Ignore o mobiliário comum do
  estúdio.
- Para cada objeto: categoria, tipo no singular, a cor base da lista e o tom
  como você vê, detalhe curto e os intervalos em que está visível.
- Marca só quando o logo ou o nome estiver legível. Na dúvida, deixe em branco.
- A cor sob a luz do estúdio engana: prefira a cor base mais provável e diga o
  tom no campo "cor".
- No máximo 5 peças por pessoa em cada aparição, as mais visíveis.

6. LOCAIS E IMAGENS DE APOIO
- (o texto atual sobre locais e plano limpo)
```

Riscos para medir no piloto da E1, por comparação visual:
- **Custo.** A lista nova aumenta a saída do modelo, que já é a maior incerteza do custo (~60 mil tokens por hora). O teto de 5 peças por pessoa limita o aumento. Medir os tokens de saída antes e depois, no mesmo vídeo.
- **Resolução.** O volume roda em 480p e resolução padrão, a 1 quadro por segundo. Sapatos e acessórios são pequenos na imagem; a cor e o tipo podem pedir o escalonamento ou a resolução alta nos planos com pessoas.
- **Tempos.** O Flash-Lite já devolve textos na tela com a duração do bloco (#76). Objetos podem ter o mesmo problema; o A/B com o 3.8 Flash diz se é o modelo ou a instrução.

## Ordem de construção

1. Esquema 1.3 com `objetos` e a instrução nova, medidos no A/B da E1.
2. Detecção de cortes e quadros-chave extraídos na validação: os planos passam a ser os momentos, e a miniatura vira uma imagem de verdade.
3. Data de exibição no Job.
4. Catálogo de pessoas com id estável (#82 e ADR 0005).
5. Índice de momentos e a página de resultados (E2).
