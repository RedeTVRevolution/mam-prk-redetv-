# Gemini em Flex em toda chamada do processamento, menos a identificação (Standard com cache); Standard também na busca

Em 05/11/2026 o Bruno decidiu (#402, #471): toda chamada do processamento ao Gemini sai no modo Flex, pela metade do preço do Standard, com ou sem vídeo: a análise por janelas, o escalonamento, a passada de comparação, o inventário de objetos, as referências e as comparações de modelos. Ficam em Standard a identificação de pessoas sem nome (`api/modelo_forte.py`, com cache implícito, #414) e a busca (a consulta por texto e o `termo_da_foto`), porque a pessoa espera a resposta na tela e o Flex leva de 1 a 15 min. Antes valia o conteúdo do pedido (Flex só com vídeo, #212); agora o modo é o campo `modo` da `Chamada` (`api/gemini.py`), Flex por padrão, e só quem pede `MODO_STANDARD` sai sem os cabeçalhos do Flex (prazo de 600 s no servidor). Um teste falha se outro arquivo de `api/` pedir Standard. O juiz da dúvida da junção de pessoas (#547) rodava em Flex, por decisão do Bruno em 10/11/2026, mas foi desligado no mesmo dia por precisão de 50% no dev (3 de 6 certos): hoje Standard fica só na busca e na identificação em si. O endpoint continua o global (ADR 0001).

Os números do #402 (dev, 05/11/2026, seis vídeos, 5,3 h, estimados pelos tokens vezes a tabela do Plano, não a fatura): a análise já em Flex custava ~US$ 0,30/h; o inventário em Standard, ~US$ 0,34/h (~0,17 em Flex); a identificação, ~US$ 0,46/h (ficou em Standard); outras chamadas sem o log por etapa, ~US$ 0,16/h (~0,08 em Flex). O ~US$ 0,70/h do #402 contava a identificação em Flex; com ela em Standard, o total vai de ~US$ 1,26/h para ~US$ 1,01/h, ~US$ 150 por mês a menos com 600 h. No código, as chamadas que usam o `TransporteVertex` fora dos Jobs são as de comparação feitas à mão (`api/passadas.py`, `api/comparar_objetos.py`, `api/medir_florence.py`, `api/cassete.py`), que agora herdam o Flex; elas usam o modelo que a comparação pede, não necessariamente o Flash-Lite. Não se confirmou que os ~US$ 0,16/h vinham delas: a busca, em Standard e fora das métricas por etapa, também pode explicar parte; conferir no Cloud Monitoring.

O texto abaixo é do período em que valia o conteúdo do pedido.

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
