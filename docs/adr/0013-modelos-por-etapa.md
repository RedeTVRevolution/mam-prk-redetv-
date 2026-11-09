# Modelos por etapa: o Gemini mais barato no volume, o 3.8 Flash só nas pessoas sem nome

Em 5/11/2026, o Bruno decidiu os modelos de cada etapa da decupagem. A regra geral é usar o Gemini mais barato que der conta do trabalho, hoje o 3.5 Flash-Lite. Um modelo mais caro só entra com um ganho medido que pague a diferença.

| Etapa | Modelo | Modo (ADR 0004) | Onde está |
|---|---|---|---|
| Análise por janelas (o volume) | Gemini 3.5 Flash-Lite | Flex | `MODELO` em `api/gemini.py` |
| Pessoas sem nome (modelo forte) | Gemini 3.8 Flash, até 8 pessoas por vídeo | Standard, com cache (#414) | `MODELO_FORTE` em `api/modelo_forte.py`; o limite é `limite_de_pessoas_do_modelo_forte` no Terraform |
| Inventário de objetos | Florence-2 large na GPU L4, com conversão pelo 3.5 Flash-Lite | Flex (#402) | `motor_objetos = florence` e `modelo_objetos` no Terraform (ADR 0008, ADR 0009) |
| Entendimento da consulta da busca, e o termo da foto na busca por imagem (ADR 0015) | Gemini 3.5 Flash-Lite | Standard (a pessoa espera na tela) | `MODELO_DA_CONSULTA` em `api/entendimento_da_consulta.py` |
| Vetores da busca | `gemini-embedding-001` só na descrição dos planos (#505); falas, textos na tela e objetos sem vetor | — | `MODELO_DO_EMBEDDING` em `api/agent_retrieval.py` (o `gemini-embedding-2` do quadro saiu em 6/11/2026, ADR 0006) |
| Transcrição e leitura da tela | faster-whisper large-v3-turbo e PaddleOCR, só na GPU, sem plano B em CPU (decisão de 07/11/2026) | — | ADR 0007 |

**Sem juiz automático.** A avaliação diária por rubrica (#255) saiu em 6/11/2026 (#407): a qualidade do dia a dia fica com a conferência dos curadores, que o Bruno considera muito melhor que a do Gemini. O juiz nunca chegou a funcionar no dev (o `gemini-2.5-flash` dava 404 no serviço de avaliação).

**O escalonamento fica desligado.** O código sabe reanalisar as janelas com dúvida e uma amostra delas (`api/escalonamento.py`), mas a análise do Job não passa `fracao_escalonada` (`api/analise.py`). E a reanálise, se fosse ligada, repetiria a mesma chamada da primeira passada: o mesmo modelo, o mesmo proxy e 1 quadro por segundo (`api/analise_por_janelas.py`). Hoje o 3.8 Flash só entra na decupagem pelo modelo forte. O alerta `limiar_de_escalonadas_pct`, que ficava sempre em zero, foi removido em 5/11/2026; se o escalonamento for ligado, o campo `pct_escalonadas` do log `video_concluido` continua lá para um alerta novo.

## Por quê

**Custo.** Pela tabela do `docs/Plano_MAM.md` (Standard, em US$ por milhão de tokens de entrada:saída):
- o 3.5 Flash-Lite custa 0,30:2,50;
- o 3.8 Flash custa 1,50:7,50, ou seja, 5 vezes na entrada e 3 vezes na saída.

Na análise em Flex, o Flash-Lite sai por ~US$ 0,27–0,30 por hora de vídeo, com os tokens do FAMA de 03/11 (ADR 0004).

**Objetos (#246, 5/11/2026, no FAMA de 49 min e no Bolão).** Os custos abaixo são estimados: tokens medidos vezes os preços do Plano, mais a GPU a US$ 1,05/h. Não são a fatura.
- O Florence com a conversão pelo Flash-Lite custou ~US$ 0,55/h. O Flash-Lite olhando os quadros custou ~US$ 0,35/h.
- O 3.8 Flash olhando os quadros custou 7 vezes o Flash-Lite no Bolão. No FAMA ele não foi medido: pela proporção do Bolão, levaria ~1,5 h.
- O Flash-Lite errou menos marcas, mas achou menos itens (316 contra 437).
- O Bruno avaliou a aplicação e manteve o Florence, porque considerou aceitável a qualidade de objetos, roupas e pessoas.

**Pessoas sem nome.** O nome que o modelo forte dá só é confirmado por prova no GC ou na fala (ADR 0012). O limite de pessoas por vídeo segura o custo do 3.8 Flash num programa com muita gente.

## O que não foi medido

Falta a comparação por requisito entre o Flash-Lite e o 3.8 Flash na análise inteira: famosos, menções, pautas, B-roll, comerciais e tempos. As ferramentas estão prontas: `make passada-de-comparacao` (#247), `make comparar-passadas` (#248) e a tela lado a lado (#249).

Esta ADR é revista se essa comparação, ou a taxa de correção dos editores no piloto, mostrar que o Flash-Lite perde algum requisito do aceite. Nesse caso, a primeira opção é escalonar só as janelas com dúvida para o 3.8 Flash, e não trocar o modelo do volume. Antes disso, o escalonamento precisa passar a trocar de modelo, o que hoje o código não faz.
