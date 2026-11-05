# Princípios de design

O MAM é ferramenta de trabalho de redação e acervo: o editor passa horas nele, com pressa, procurando um trecho. Estes princípios valem para toda tela e servem de régua na revisão de qualquer PR de interface.

## 1. Ferramenta, não vitrine

- **Densidade de ferramenta profissional.** Texto de 13–14 px, linhas de tabela de 32–36 px, espaçamento curto. Uma lista de 30 vídeos cabe numa tela sem rolar.
- **Tabela antes de cartão.** Cartão só onde a imagem é o conteúdo (o resultado da busca, com o quadro do momento). O acervo, a lixeira, os usuários e a auditoria são tabelas.
- **Nada de número de vaidade.** Nada de "14 segmentos · 26 pessoas · 44:20" em letra grande no topo. Contagem só onde ajuda a decidir, como ao lado do nome da aba ou da faixa.
- **Sem selos e rótulos decorativos** ("● VÍDEO ORIGINAL", "PLAYER DE ACERVO", breadcrumb que não navega).

## 2. Sem cara de interface feita por IA

- **Sem gradiente, brilho, vidro fosco, sombra grande ou borda arredondada demais.** Fundo chapado, bordas de 1 px, cantos de 4–6 px.
- **Sem emoji nem símbolo tipográfico como ícone** (▦ ♙ ◫ ◈ ♫ ↶). Um conjunto só de ícones, o Tabler, que já está instalado. Ícone sempre com rótulo ou dica, e só onde a função é universal: play, baixar, histórico, fechar.
- **Sem "✨ IA".** Não se anuncia que é IA; mostra-se a **evidência** (GC, fala, rosto) e a origem (modelo ou revisão).
- **Texto direto**, no vocabulário do [GLOSSARY.md](../../GLOSSARY.md): pauta, aparição, menção, texto na tela. Nada de "insights", "metadados analisados por IA" ou "segmento".

## 3. Cor com função

A interface é cinza. A cor só aparece quando diz alguma coisa, e cada cor diz uma coisa só.

| Função | Cor | Onde |
| --- | --- | --- |
| Tipo de ocorrência | Uma cor fixa por tipo: pauta, pessoa na imagem, menção, objeto, marca, fala, texto na tela | Faixa da linha do tempo, chip do filtro, marcador no painel. A mesma cor em todo lugar |
| Estado | Verde = concluído; âmbar = em andamento ou aguardando; vermelho = falhou | Acervo, correções, envio |
| Foco e seleção | Um só tom de destaque, neutro (azul) | Item selecionado, item atual durante a reprodução, foco do teclado |
| Marca RedeTV | Vermelho | **Só no logotipo** |

Hoje o vermelho da marca é o botão principal e também o destaque da fala que está tocando ([print](prints/app/10-fala-tocando.jpg)). Na TV, vermelho quer dizer "no ar" ou erro; um bloco vermelho cheio no painel parece alarme. O item atual ganha uma barra de 3 px à esquerda e um fundo levemente mais claro, nunca um bloco colorido.

A cor nunca é a única pista: a faixa tem nome, o estado tem palavra, o item atual tem barra.

## 4. O vídeo nunca sai da tela

- Player e painel ficam fixos lado a lado; só o painel rola. Clicar num item nunca rola a página a ponto de esconder o player, como acontece no mockup ([print](prints/mockup/07-clique-na-aparicao.jpg)).
- O tempo do vídeo manda: o painel e a linha do tempo acompanham a reprodução, e o item atual fica à vista.
- Toda tela tem endereço. `/video/{id}?t=724` abre o vídeo naquele tempo; o link pode ir para um colega.

## 5. Tempo legível e honesto

- **Tempo em `MM:SS`**, e `H:MM:SS` acima de uma hora, com algarismos de largura fixa (`font-variant-numeric: tabular-nums`). Sem milissegundos: o modelo mede segundos inteiros ([ADR 0003](../adr/0003-tempos-do-modelo-em-mm-ss.md)), e `00:03:17.000` sugere uma precisão que não existe.
- **Trecho sem decupagem fica visível** na linha do tempo, hachurado. Um vazio escondido parece cobertura completa.
- **"Não identificado" é resposta, não falha.** Mostra-se com a descrição curta, e a pessoa sem prova nunca ganha nome.

## 6. Teclado primeiro

O editor de vídeo trabalha com a mão no teclado. Todo gesto frequente tem tecla, e `?` mostra a lista. Nenhum atalho age com o foco num campo de texto.

| Tecla | Ação | Onde |
| --- | --- | --- |
| `/` | Focar a busca | Toda tela |
| `Espaço` ou `K` | Tocar e pausar | Visualizador |
| `L` | Tocar; de novo, 2× e 4× | Visualizador |
| `J` | Recuar 5 s. No Premiere, J é retrocesso contínuo; aqui é um salto, que funciona igual em todo navegador | Visualizador |
| `←` `→` | Recuar e avançar 1 s; com `Shift`, 5 s | Visualizador |
| `,` `.` | Quadro anterior e seguinte, com o vídeo pausado | Visualizador |
| `N` / `Shift+N` | Momento seguinte e anterior da busca | Visualizador aberto pela busca |
| `↑` `↓` | Item anterior e seguinte do painel | Visualizador |
| `Enter` | Saltar ao item | Visualizador, resultado da busca |
| `E` | Modo de catalogação | Visualizador (Editor e Curador) |
| `I` `O` `A` | Entrada, saída, acrescentar | Modo de catalogação |
| `Ctrl+Z` | Desfazer a última correção | Modo de catalogação |
| `?` | Lista de atalhos | Toda tela |
| `Esc` | Fechar o que estiver aberto | Toda tela |

O mockup usa J e L como saltos de 10 s, e isso confunde quem vem de um editor de vídeo. Aqui, K pausa e L acelera como no editor; só o J vira salto (o Chrome também não toca o vídeo para trás).

## 7. Mensagens que dizem o que fazer

- Erro em português, com a ação: "O vídeo usa um codec que não aceitamos. Envie em H.264." O código interno (`codec_nao_suportado`) fica num detalhe, para o suporte.
- Lista vazia diz que está vazia e por quê: "Nenhuma marca neste vídeo." Hoje a aba Marcas vazia é só um espaço em branco ([print](prints/app/06-aba-marcas.jpg)).
- Busca sem resultado é honesta e oferece a saída mais provável: "Nenhuma aparição de Sabrina Sato. 12 menções na fala."

## 8. Acessível por padrão

- Contraste AA no tema escuro, inclusive no texto secundário.
- Foco do teclado sempre visível.
- Faixas da linha do tempo e marcadores com nome acessível ("Aparição de Leão Lobo, 03:31 a 04:21"). Hoje o nome diz só o tipo e o tempo ("Aparições 00:55").
- Nenhuma informação só por cor (ver 3).

## 9. Poucas peças

- Mantine e Tabler, que já estão no projeto. Nenhuma biblioteca de componentes, gráficos ou animação nova sem uma necessidade que essas duas não cubram. A única exceção até aqui são os gráficos dos relatórios e do painel da diretoria: entra o `@mantine/charts` (com o `recharts` que ele exige), que usa o mesmo tema.
- Tema escuro, como hoje: é o padrão das salas de edição e combina com o vídeo. Tema claro só se alguém pedir.
- Animação só para orientar (abrir um painel, 150 ms), nunca para enfeitar.
