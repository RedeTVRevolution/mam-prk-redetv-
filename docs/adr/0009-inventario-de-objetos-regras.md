# Inventário de objetos: etapa, lotes, destaque e união de repetidos

A etapa `inventario_de_objetos` roda entre `quadros_chave` e `indexacao`. Com o motor `florence` (padrão da variável `motor_objetos`), o Workflows roda o Job com GPU da [ADR 0008](0008-florence-2-em-gpu-no-us-east4.md) com as tentativas do #239, **sem plano B em CPU** (esgotada a espera por GPU, a falha sobe), e depois o Job em CPU `mam-inventario` (`var.imagem_validacao`, conta `objetos`, em São Paulo, sem internet). Esse Job lê o resultado bruto e faz chamadas **só de texto** ao Gemini, que o convertem para o esquema do inventário em português; com o motor `gemini`, só o Job em CPU roda e o modelo olha os quadros-chave. O modelo vem da variável `modelo_objetos` (Flash-Lite, [ADR 0004](0004-gemini-em-standard.md), endpoint da [ADR 0001](0001-gemini-endpoint-global.md)). Qualquer falha marca a etapa como `falhou`, a indexação roda assim mesmo, sem inventário, e o Curador reprocessa a partir da etapa.

**Esquema:** `Plano.inventario` guarda, por objeto, `nome`, `categoria`, `cor`, `marca`, as caixas por quadro (caminho e caixa normalizada de 0 a 1) e `destaque`; `Decupagem.inventario_gerado_por` guarda motor e modelo. Fica fora do esquema de resposta da análise (a instrução e o cassete da análise não mudam); as Decupagens antigas, sem inventário, seguem legíveis. A `CategoriaDeObjeto` ganhou `movel`, `decoracao`, `instrumento_musical`, `utensilio`, `documento`, `planta` e `bebida`.

**Lotes:** 20 planos por chamada no motor `florence` (o texto das detecções de um plano tem uns 1 a 2 mil caracteres; uma hora de vídeo, com ~190 planos, dá ~10 chamadas) e 4 planos no motor `gemini` (cada plano leva 2 ou 3 JPEGs em resolução cheia).

**Destaque (1 a 3), calculado pelo servidor** sobre a maior caixa do objeto, nunca pelo modelo. Área é a fração do quadro; "central" é o centro da caixa a até 0,25 do centro do quadro:
- área ≥ 10% e central: **3**;
- área ≥ 10%, ou área ≥ 2% e central: **2**;
- o resto: **1**.

**Repetidos no plano:** depois da conversão, objetos do mesmo plano com o mesmo nome (sem acento e sem diferença de caixa), categoria e cor viram um só, com as caixas de todos os quadros e o maior destaque. A regra **não pega**: nomes sinônimos ("sofá" e "sofá de couro"; "carro" e "automóvel"), o mesmo objeto com cor lida diferente em dois quadros, e o objeto que o modelo cita sem nenhuma caixa válida, que é descartado (no motor `florence`, as caixas vêm dos ids das detecções). O resultado é um inventário às vezes com duplicata, e não um objeto perdido.

**Cota de GPU:** a etapa usa uma GPU por programa, depois da análise, nunca junto da transcrição e do OCR do mesmo programa. O pico por programa segue em 2 GPUs, e as 10 do pedido do #240 cobrem 5 programas em paralelo.

**Comparação dos motores:** `make comparar-objetos JOB=<id>` dispara o Job do Florence-2 com `DESTINO_DO_RESULTADO` (`<job>/objetos/comparacao-florence.json`, a Decupagem não muda) e roda no computador da pessoa a conversão e cada modelo do Gemini olhando as imagens, guardando por motor o inventário, os tokens, o tempo e o custo.
