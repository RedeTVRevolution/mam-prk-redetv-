# Gemini em Flex em toda geração com vídeo; Standard nas chamadas só com texto ou imagens

Toda chamada de geração do Gemini que leva vídeo sai no modo Flex, pela metade do preço do Standard: a análise por janelas, o escalonamento e a passada de comparação. As chamadas só com texto ou imagens saem no Standard: o modelo forte, a comparação de rostos, as referências, o inventário de objetos e o entendimento da consulta da busca. Quem decide é o conteúdo do pedido, e não o modelo: o `TransporteVertex` (`api/gemini.py`) só manda os cabeçalhos do Flex, com prazo de 600 s no servidor, quando o pedido leva vídeo. O endpoint continua o global (ADR 0001).

O Flex promete de 1 a 15 min por chamada ([otimização do Gemini](https://ai.google.dev/gemini-api/docs/optimization)). Em 30/10/2026, no dev, o clipe2 (5 min) ficou 411 s na chamada em Flex, e o #79 passou a análise para o Standard. No mesmo dia, o #86 a devolveu ao Flex; o PR não registra o motivo. A divisão por conteúdo do pedido veio com o #212, em 31/10. A medição a seguir é posterior às duas decisões.

Em 03/11/2026, com o Flex, a etapa de análise inteira (subida do Job, chamadas e consolidação; não só a chamada, como em 30/10) levou:

| Vídeo | Duração | Análise |
|---|---|---|
| clipe3 | 2 min | 47 s |
| clipe1 | 3 min | 58 s |
| clipe2 | 5 min | 73 s |
| FAMA | 49 min | 10 min 41 s |

Nos clipes, a demora até a decupagem completa veio das etapas seguintes. No FAMA, a análise foi a segunda etapa mais longa: as 10 janelas rodaram em 3 rodadas de até 4, com 1 a 2,5 min por chamada, e uma resposta fora do esquema custou mais ~2 min. É uma execução por vídeo, num dia só, e a espera do Flex varia com a carga.

**Custo do modelo na passada de volume:**

| Base | Flex | Standard | Diferença com 600 h/mês |
|---|---|---|---|
| Premissas do `docs/Plano_MAM.md` (~60 mil tokens de saída por hora) | ~US$ 0,15/h | ~US$ 0,30/h | ~US$ 90/mês |
| Estimada com os tokens de 03/11 no FAMA (~160–177 mil tokens de saída por hora, já com o raciocínio) | ~US$ 0,27–0,30/h | ~US$ 0,53–0,59/h | ~US$ 160–180/mês |

A linha de 03/11 multiplica os tokens contados pelo preço de tabela do Plano (o Flex a 50%); não é a fatura. A ponta menor de cada faixa exclui a resposta fora do esquema, que foi descartada.

Se a espera do Flex passar a pesar no prazo, o piloto (E1) mede de novo e esta ADR é revista.
