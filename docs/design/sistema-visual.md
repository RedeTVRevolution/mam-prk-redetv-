# Sistema visual

> **Substituído pelo [MAM_DESIGN_SYSTEM.md](MAM_DESIGN_SYSTEM.md) (05/11/2026).** Este arquivo descreve o tema Mantine das telas de hoje e vale até elas serem refeitas. As cores de tipo e de estado, o azul de foco e as regras de contraste daqui seguem no sistema novo.

A referência de toda tela do MAM. Cada decisão aplica um item dos [princípios](principios.md), citado entre parênteses (P1 a P9). Os valores moram em [`web/src/tema.ts`](../../web/src/tema.ts), que é a fonte; este documento explica o porquê. A página de amostra mostra tudo aplicado: no `npm run dev` ou no dev publicado, abra `/amostra` (sem login, só com dados de exemplo).

Os testes que guardam as regras:

- [`tema.test.ts`](../../web/src/tema.test.ts): contraste WCAG de cada par texto/fundo, distinção das cores de tipo na deuteranopia, primário não vermelho, cantos e o âmbar de "Decupando".
- [`estilo.test.ts`](../../web/src/estilo.test.ts): nenhum gradiente, nenhuma sombra grande, nenhum emoji ou símbolo tipográfico em `web/src`.

## Cores

A interface é cinza, e a cor só aparece quando diz alguma coisa (P3). Todo token tem nome de função (`textoSecundario`, `andamento`), nunca de tom. Só tema escuro (P9).

### Neutros

| Token | Valor | Escala do Mantine | Onde |
| --- | --- | --- | --- |
| `fundo` | `#141518` | `dark.7` (body) | Fundo da página |
| `superficie` | `#1B1D21` | `dark.6` | Painel, tabela, campo, botão secundário |
| `elevada` | `#25272C` | `dark.5` | Menu, diálogo, popover; hover do que está na superfície |
| `borda` | `#34373D` | `dark.4` | Toda borda de 1 px, divisória de tabela |
| `texto` | `#E4E6EA` | `dark.0` | Texto principal |
| `textoSecundario` | `#A0A5AE` | `dark.2` (dimmed) | Metadado, rótulo de faixa, contagem, placeholder |
| `textoDesabilitado` | `#6E737C` | `dark.3` | Controle desabilitado |

- **Por que três degraus de fundo.** O fundo é o mais escuro, e cada camada acima clareia um pouco. Assim o painel se separa da página sem sombra nem borda grossa (P2), e o vídeo, que é o conteúdo, fica cercado de cinza escuro, como numa sala de edição (P9).
- **Por que um cinza quase neutro.** Um leve frio (azul muito baixo) evita o cinza "sujo" do monitor, sem virar uma cor que dispute com as de função (P3).
- **Por que a escala segue a ordem do Mantine.** O Mantine pinta os componentes pelo índice da escala `dark`: 0 é texto, 2 é dimmed, 4 é borda, 7 é body. Trocar a escala inteira faz todo componente, inclusive os das telas de hoje, usar os tokens sem configuração por componente.
- **Contraste.** Todo texto passa no AA (4,5:1) sobre os três fundos, inclusive o secundário (P8). O desabilitado é isento pela WCAG (1.4.3, componente inativo), mas fica acima de 3:1 para continuar legível. O placeholder não tem essa isenção, porque o campo está ativo: ele usa o texto secundário, e não o tom 3 que o Mantine daria.

| Texto | Valor | Sobre `fundo` | Sobre `superficie` | Sobre `elevada` |
| --- | --- | --- | --- | --- |
| Texto | `#E4E6EA` | 14,6 | 13,5 | 12,0 |
| Texto secundário | `#A0A5AE` | 7,4 | 6,8 | 6,0 |
| Texto desabilitado | `#6E737C` | 3,8 | 3,5 | 3,1 |
| Texto de foco (link) | `#78A3F2` | 7,2 | 6,7 | 5,9 |
| Concluído | `#5CC98A` | 8,8 | 8,2 | 7,2 |
| Em andamento | `#E5B045` | 9,2 | 8,5 | 7,6 |
| Falhou | `#F4736A` | 6,5 | 6,0 | 5,3 |

### Foco e seleção

| Token | Valor | Onde |
| --- | --- | --- |
| `foco` | `#3871DC` | Anel de foco do teclado, item selecionado (a 16% de opacidade), barra de 3 px do item atual, botão primário, faixa de momentos da busca |
| `focoTexto` | `#78A3F2` | Link e texto na cor de foco |

- **Um tom só** (P3). O mesmo azul diz "isto é o que está em foco ou escolhido", seja pelo teclado, pelo clique ou pela reprodução.
- **Por que este azul.** Ele é o único valor que cumpre três papéis de uma vez: o branco sobre ele passa no AA (4,6:1), então serve de fundo do botão primário; e ele próprio tem 3:1 sobre os três fundos (4,0, 3,7 e 3,2), o mínimo da WCAG para um indicador gráfico (1.4.11), então serve de anel e de barra. Mais claro, o texto branco do botão reprova; mais escuro, o anel some sobre a superfície elevada.
- **O primário é o foco, não um neutro.** `primaryColor: 'foco'`. O Mantine desenha o anel de foco e o botão primário com a cor primária, então essa escolha garante o mesmo azul nos dois sem CSS a mais. Um primário cinza deixaria o botão principal de um diálogo igual ao "Cancelar".
- **A escala de 10 tons** existe porque o Mantine a exige; o tom 6 é o `foco` e o 4 é o `focoTexto`. Os outros só servem ao Mantine (hover, variante light).

### Estados

| Estado | Token | Valor | Estados do Job |
| --- | --- | --- | --- |
| Concluído | `concluido` | `#5CC98A` | Concluído |
| Em andamento ou aguardando | `andamento` | `#E5B045` | Aguardando envio, Em quarentena, Decupando |
| Falhou | `falhou` | `#F4736A` | Falhou |
| Inerte | `textoSecundario` | `#A0A5AE` | Cancelado |

- **Verde, âmbar, vermelho** (P3): a convenção que o operador já conhece. "Decupando" deixou o azul, que é a cor de foco: um estado nunca pode parecer seleção.
- **"Aguardando envio" e "Em quarentena" também são âmbar**, porque o princípio junta "em andamento ou aguardando": nos dois casos, o vídeo ainda não está pronto e ninguém precisa agir. A palavra no selo os distingue.
- **"Cancelado" é cinza**: não terminou nem falhou, e não pede atenção.
- **Versão para texto e para fundo de selo.** O selo usa a variante `light` do Mantine: a cor do estado no texto, sobre a mesma cor a 10% de opacidade. O texto passa no AA sobre esse fundo, composto sobre a página ou sobre a superfície (o teste confere). Com isso, um só valor por estado serve aos dois usos.
- **Nunca só cor** (P3): o selo sempre tem a palavra.

### Tipos de ocorrência

Uma cor fixa por tipo, a mesma na faixa da linha do tempo, no chip de filtro e no marcador do painel (P3).

| Tipo | Valor | Sobre `fundo` | Sobre `elevada` |
| --- | --- | --- | --- |
| Pauta | `#8A9CF5` | 7,1 | 5,8 |
| Pessoa na imagem (aparição) | `#F5A55A` | 9,1 | 7,4 |
| Menção | `#F08AAE` | 7,8 | 6,4 |
| Objeto | `#A0A030` | 6,6 | 5,4 |
| Comercial e marca | `#D9C2FF` | 11,4 | 9,3 |
| Fala | `#8E9196` | 5,8 | 4,7 |
| Texto na tela | `#A8EFC8` | 13,8 | 11,3 |
| Trecho sem decupagem | Hachurado de `borda` | — | — |
| Momentos da busca | `foco` | 4,0 | 3,2 |

- **Legíveis como texto.** As sete passam no AA sobre os três fundos. Assim, o chip ligado pode escrever o nome do tipo na cor dele, e nenhuma cor de tipo precisa de regra à parte.
- **Fora do vermelho e do azul de foco.** Nenhum tipo usa o vermelho (que é marca e falha) nem o azul do foco: um bloco de pauta selecionado não pode sumir na cor da seleção. A pauta é um lilás-azulado, mais claro e mais violeta que o foco.
- **A fala é cinza.** É a faixa mais densa e contínua; em cinza, ela forma o fundo de referência e deixa as outras saltarem.
- **Planos não têm cor**: saem da linha do tempo no redesenho do Visualizador. Até lá, a tela de hoje desenha a faixa de planos em `dark.3`.
- **Hachurado** (P5): listras diagonais de 2 px em `borda`, a cada 6 px, sobre todas as faixas. É o único `repeating-linear-gradient` permitido: desenha um padrão, não uma transição de cor.

**Como a distinção foi conferida.** O teste `as sete cores se distinguem na visão comum e na deuteranopia`:

1. converte cada cor para RGB linear;
2. simula a deuteranopia completa com a matriz de Machado, Oliveira e Fernandes (2009);
3. mede a distância euclidiana entre todo par no Oklab (Ottosson, 2020), um espaço em que distância acompanha a diferença percebida;
4. exige pelo menos 0,10 entre qualquer par, na visão comum e na simulada.

O limiar de percepção no Oklab fica perto de 0,02; 0,10 é uma diferença que se vê de relance num bloco pequeno. Resultado: o par mais próximo na visão comum é pauta/fala, com 0,137; na deuteranopia, menção/fala, com 0,104. Para comparar, as cores de hoje (tons padrão do Mantine) ficam perto de 0,01 entre menções e planos na deuteranopia, o que equivale a cores iguais. Na protanopia, que o ticket não cobre, o par mais próximo é menção/fala, com 0,046: distinguíveis lado a lado, mas não de relance. Como a cor nunca é a única pista (cada faixa tem nome e cada bloco, nome acessível), isso fica registrado como limite conhecido.

Sete tons distinguíveis na deuteranopia, todos com AA sobre fundo escuro, sem vermelho e sem o azul do foco: o espaço é apertado, e as cores saíram de uma busca numérica sob essas restrições, ajustada à mão depois. Quem trocar uma cor precisa rodar o teste.

### Cor do objeto

`CORES_DE_OBJETO`, no `tema.ts`, dá uma cor a cada valor de `cor_base` do Objeto (esquema 1.3): `vermelho`, `laranja`, `amarelo`, `verde`, `azul`, `roxo`, `rosa`, `marrom`, `bege`, `preto`, `branco`, `cinza`, `dourado`, `prateado` e `estampado`. É a única exceção à regra de nomear o token pela função e não pelo tom, porque aqui o tom é o dado: a chave é o valor do esquema e a cor representa a peça que aparece no vídeo, não a interface. Por isso, ela é diferente da cor do tipo de ocorrência `Objeto`.

- **Só no quadradinho de 10 px** da lista de objetos, com borda de 1 px em `textoSecundario`, que separa o `preto` do fundo. Nunca vira texto, fundo nem faixa.
- **Sempre com a palavra** (P3): o tom em palavras ("vermelho vivo") ou, sem ele, as cores base. O teste confere que a palavra ao lado nomeia a cor do quadradinho.
- **`estampado` não tem uma cor só**: usa o cinza do `textoSecundario`, e a palavra diz o resto.

### Marca RedeTV

| Token | Valor | Onde |
| --- | --- | --- |
| `marca` | `#E03131` | Só no logotipo |

Na TV, vermelho quer dizer "no ar" ou erro (P3). Ele não aparece em botão, destaque, faixa nem fundo. O vermelho de erro é outro token, `falhou`, e vale para tudo o que diz "deu ou vai dar errado": o selo "Falhou", o alerta de erro, a mensagem de campo inválido e o botão de perigo.

**Duas variáveis fora da escala.** O Mantine pinta a mensagem de campo inválido com `--mantine-color-error`, que seria o `red.8` (3,7:1 sobre a superfície, abaixo do AA), e o placeholder com `--mantine-color-placeholder`, que seria o tom de desabilitado. O `variaveis` do `tema.ts` aponta a primeira para `falhou` e a segunda para `textoSecundario`. O teste confere o contraste dessas variáveis, que são as que o campo de fato usa.

## Tipografia

| Papel | Valor | Por quê |
| --- | --- | --- |
| Família de texto | `system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif` | A do sistema: zero download, zero dependência de rede e a renderização que o usuário já conhece. Fonte da web custaria peso e um pedido a mais sem ganho para uma ferramenta (P9) |
| Família monoespaçada | `ui-monospace, 'SF Mono', Menlo, Consolas, 'Liberation Mono', monospace` | Só no timecode de origem (`01:12:04:15`) e em códigos para o suporte, em que cada caractere conta |
| Algarismos | `font-variant-numeric: tabular-nums` | Em todo tempo e número de tabela: `11:11` e `48:08` ocupam a mesma largura, e as colunas se alinham (P5) |

| Tamanho | Valor | Uso |
| --- | --- | --- |
| `xs` | 12 px | Rótulo de faixa, metadado, selo, contagem |
| `sm` | 13 px | Tabela, painel, botão, item de lista |
| `md` | 14 px | Texto corrido, campo, padrão do `body` |
| `lg` | 16 px | Pouco uso: destaque dentro de diálogo |
| `xl` | 18 px | Reservado |

- **Texto de 13–14 px** (P1). O padrão do `body` é 14; o que é denso (tabela, painel) usa 13.
- **Títulos pequenos**: `h1` 20 px, `h2` 18, `h3` 16, `h4` 14, `h5` 13 e `h6` 12. Título nomeia a seção, não faz manchete (P1).
- **Dois pesos**: 400 para texto e 600 para título, cabeçalho de tabela e selo. Negrito 700 não entra: em fundo escuro, ele "acende" demais.
- **Alturas de linha**: 1,35 (`xs`), 1,4 (`sm`), 1,45 (`md`) e 1,5 (`lg` e `xl`). Curtas, porque quase todo texto é de uma linha; o texto corrido do `md` ainda respira.

## Espaçamentos

Base de 4 px. Todo espaçamento é múltiplo de 4, para tudo se alinhar sem conta.

| Token | Valor | Onde |
| --- | --- | --- |
| `xs` | 4 px | Entre ícone e rótulo; dentro de selo |
| `sm` | 8 px | Dentro de componente; entre itens de um grupo |
| `md` | 12 px | Entre componentes |
| `lg` | 16 px | Margem da página; entre blocos |
| `xl` | 24 px | Entre seções |

Valores curtos (P1): uma ferramenta de trabalho cabe na tela antes de rolar.

## Densidade

| Medida | Valor | Por quê |
| --- | --- | --- |
| Linha de tabela | 32 px + 1 px de borda | 6 px + linha de 20 px + 6 px. Padrão do `Table` no tema (P1) |
| Barra fixa | 44 px, no máximo | Fica sempre na tela; cada pixel a mais sai do conteúdo |
| 30 vídeos sem rolar | 44 + 33 (cabeçalho) + 30 × 33 = 1067 px | Cabe numa tela de 1080 px de altura (P1) |
| Faixa da linha do tempo | 14 px, com 6 px entre faixas | As sete faixas e a régua de 20 px somam 160 px: o player continua dominante (P4) |
| Botão e campo | 36 px (`sm`); 30 px (`xs`) em barra de ferramentas e confirmação na linha | O alvo de clique continua confortável |

## Forma

- **Bordas de 1 px**, em `borda`.
- **Cantos de 4–6 px** (P2): raio padrão `sm` = 4 px (botão, campo, selo, chip), `md` = 6 px (painel, diálogo). Os tamanhos `lg` e `xl` do tema também valem 6 px, para nenhum componente passar disso; o bloco da linha do tempo usa 2 px (`xs`), porque é pequeno.
- **Sombra só para separar o que flutua** (menu, diálogo), com no máximo 8 px de desfoque. Nada de sombra grande, gradiente, brilho ou vidro fosco (P2). O `estilo.test.ts` procura `linear-`, `radial-` e `conic-gradient` e `box-shadow` com mais de 8 px de desfoque.
- **Animação só para orientar** (P9): 150 ms ao abrir um menu, um popover ou um diálogo (o tema baixa o diálogo dos 200 ms do Mantine). Nada pulsa, nada brilha.
- **Ícones**: só os do Tabler, sempre com rótulo ou dica (P2). Nada de emoji nem símbolo tipográfico; o teste procura caracteres pictográficos, de formas geométricas (`▦ ◫ ●`), símbolos diversos e dingbats.

## Componentes

Os estados de todo componente: **normal**; **hover**, a camada logo acima (`superficie` vira `elevada`) ou o tom 7 da cor; **foco**, com anel de 2 px em `foco` e 2 px de afastamento; **desabilitado**, com fundo `superficie` e texto `textoDesabilitado`; e **selecionado**, com `foco` a 16%. A amostra desenha hover e foco parados, para avaliar sem mouse.

| Componente | Como | Quando |
| --- | --- | --- |
| Botão primário | Fundo `foco`, texto branco | A ação principal de um diálogo ou formulário; no máximo um por bloco. **Nunca vermelho** |
| Botão secundário | Variante `default`: fundo `superficie`, borda, texto | Cancelar, ações secundárias |
| Botão de perigo | Variante `outline` na cor `falhou` | Ação destrutiva (apagar, descartar), sempre com confirmação. Contornado, não cheio: o perigo se vê sem gritar |
| Botão de ícone | `ActionIcon` `subtle`, cinza, **sempre com dica** e `aria-label` | Função universal: tocar, baixar, histórico, fechar, mais ações |
| Campo de texto | Fundo `superficie`, borda, rótulo acima; erro em `falhou` abaixo, com a ação | Todo dado digitado |
| Campo de busca | Ícone de lupa, placeholder "Buscar no acervo…" e a tecla `/` à direita | Barra fixa; `/` o foca de qualquer tela (P6) |
| Select | O mesmo campo, com lista | Escolha fechada: programa, papel |
| Chip de filtro | Desligado: contorno cinza. Ligado: contorno e texto na cor do tipo, com marca de seleção | Filtro de tipo, estado, programa. A marca de seleção é a pista que não depende de cor |
| Selo de estado | Variante `light`, palavra sempre, sem caixa alta | Estado do Job, origem (revisado) |
| Selo "não confirmado" | Contorno em `textoSecundario` | Pessoa ou sugestão que ninguém confirmou ainda (P5) |
| Tabela densa | Linha de 32 px; cabeçalho em 600; hover um degrau mais claro; selecionada com `foco` a 16% e barra de 3 px; ordenação com seta e `aria-sort`; ação da linha num botão de ícone na última coluna | Acervo, lixeira, usuários, auditoria (P1) |
| Abas com contagem | Contagem em `textoSecundario` ao lado do nome | Painel do Visualizador. A contagem ajuda a decidir; zero aparece como zero |
| Item de lista do painel | Marcador de 8 px na cor do tipo, tempo em `tabular-nums`, texto. **Selecionado**: `foco` a 16%. **Atual**: barra de 3 px em `foco` à esquerda e fundo `elevada`, nunca um bloco colorido; `aria-current` | Pautas, pessoas, objetos, falas |
| Faixa da linha do tempo | Bloco na cor do tipo, cantos de 2 px, 1 px de vão entre blocos encostados; **selecionado** com anel de foco; trecho sem decupagem hachurado sobre todas as faixas; cursor de 2 px em `texto`; riscos de corte de 1 × 6 px na régua; nome acessível com quem e quando ("Aparição de Leão Lobo, 03:31 a 04:21") | Visualizador (P5, P8) |
| Menu | Fundo `elevada`, borda, sombra pequena; item desabilitado em `textoDesabilitado` | Ações de uma ocorrência |
| Diálogo | Fundo `elevada`, centralizado; primário à direita, secundário ao lado | Corrigir, confirmar o que não cabe na linha |
| Confirmação na própria linha | A pergunta com o tempo, botão de perigo e "Cancelar", no lugar da linha | Apagar uma ocorrência sem abrir diálogo |
| Dica | `Tooltip` com 300 ms de espera | Todo botão de ícone; código interno de erro |
| Tecla (`Kbd`) e lista do `?` | `Kbd` pequeno; a lista é uma tabela de duas colunas, tecla e ação, na ordem de [principios.md](principios.md) | Campo de busca, a lista de atalhos (P6) |
| Estado vazio | Uma frase que diz que está vazio e outra que diz por quê ou o que fazer | Aba sem itens, busca sem resultado (P7) |
| Alerta de erro | Variante `light` em `falhou`, ícone, a mensagem em português, o código para o suporte em `textoSecundario` e o botão da ação | Falha de carga ou de envio (P7) |
| Carregando | `Loader` pequeno na cor de foco, com o que está carregando por escrito | Qualquer espera |

## Gráficos

Os gráficos dos relatórios (Tempo de tela e Marcas) usam o `@mantine/charts`, na mesma versão do `@mantine/core`, e vivem em [`web/src/graficos.tsx`](../../web/src/graficos.tsx). O painel da diretoria (#282 a #285) vai reaproveitar a base. A tabela de cada tela continua embaixo e é a forma acessível de ler os números (P8); cada gráfico tem `aria-label`.

- **Uma cor para uma série** (P3). O ranking é uma série só: as barras em `foco`; a selecionada e a que está sob o ponteiro em `focoTexto`. Nada de arco-íris por pessoa.
- **Rótulo direto em vez de eixo.** O nome fica à esquerda da barra, a 13 px; o valor na ponta, em `tabular-nums` e `textoSecundario`. Sem eixo X, sem grade, sem legenda. O gráfico que precisar de eixo ou grade os desenha em `borda`, com o texto em `textoSecundario`.
- **A barra tem 20 px de altura e 8 px de vão**, reta do lado do eixo e com 2 px de canto na ponta.
- **Os tipos têm as cores da linha do tempo** (`CORES_DE_OCORRENCIA`): aparição, menção na fala e menção no texto na divisão por tipo, para quem já viu o Visualizador reconhecer sem legenda.
- **A dica** abre em `elevada`, com o nome em 600 e os números em `tabular-nums`, em 150 ms. Os gráficos não animam o crescimento das barras (P2, P9).
- **A matriz marca × tipo** é uma `Table` com o fundo da célula em `foco`, de 0 a 60% de opacidade numa escala só; coluna sem inserção some. Não usa biblioteca.
- **Sem gradiente**: a linha de evolução por dia, quando entrar, é chapada, com a área a 12%.

## O que mudou nas telas de hoje

O tema novo vale também para as telas atuais, que só serão redesenhadas depois do portão (#139). Para não contradizer o tema, só mudou o mínimo:

- os botões "Salvar", o slider do player, o indicador de carregamento e a barra de envio deixaram o vermelho e usam o primário;
- a fala atual ganhou a barra de 3 px e `aria-current`, no lugar do bloco vermelho;
- o tempo do player perdeu o vermelho e ganhou `tabular-nums`;
- "Decupando" ficou âmbar;
- o painel do login perdeu o gradiente e ficou chapado.
