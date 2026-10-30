# Análise do mockup do Ilton

O mockup é inspiração, não modelo para copiar. Ele foi aberto no Playwright com o vídeo do TV Fama de 21/10/2026 (49 min 19 s) e a decupagem que o acompanha. O vídeo foi tocado, os atalhos testados, e foram clicados as pautas, as pessoas, os objetos e as abas. Os prints estão em [`prints/mockup/`](prints/mockup/).

O mockup e o vídeo ficam só na máquina do Bruno (`docs/design/referencia/`, fora do git). Por isso este documento descreve a decupagem em texto e não aponta para os arquivos.

## O que o mockup mostra

Uma página só, escura, com quatro áreas:

1. **Cabeçalho do vídeo**: programa e data, nome do arquivo e cinco números (14 "segmentos", 26 pessoas, 39 aparições, 15 objetos, último tempo 44:20).
2. **Player** com controles próprios, a linha do tempo dos blocos logo abaixo e um botão para gerar as miniaturas.
3. **Painel de inspeção** à direita, com o bloco selecionado: título, tom, início e fim, "Reproduzir trecho", "Ir ao início", "Copiar TC", resumo, pessoas com o figurino, merchandising e cenários.
4. **Coleção** embaixo, em cinco abas: Decupagem (cartões dos blocos), Pessoas, Objetos de cena, Merchandising e JSON completo.

A decupagem do mockup é uma lista de 14 itens. Cada um tem `timecode_inicio`/`timecode_fim` em `HH:MM:SS.mmm`, `pauta_assunto`, `tom_materia`, `resumo_jornalistico` e três listas: `celebridades` (nome, `entrada`, `saida`, `look`), `merchandising` e `mapeamento_acervo` (elemento, local e detalhes, sem tempo próprio).

No nosso vocabulário ([GLOSSARY.md](../../GLOSSARY.md)), o que o mockup chama de "segmento" é uma **pauta**, e o "look" da celebridade é o `visual` da **aparição**. A aba "Objetos de cena" lista **cenários**, não objetos: "Estúdio TV Fama", "Quadra da Vila Isabel", "Redes Sociais".

| Estado | Print |
| --- | --- |
| Abertura, antes de gerar miniaturas | [01-abertura.jpg](prints/mockup/01-abertura.jpg) |
| Página inteira; todas as miniaturas iguais (o primeiro quadro) | [02-pagina-inteira.jpg](prints/mockup/02-pagina-inteira.jpg) |
| Clique na pauta "Bastidores do Miss Bumbum" na linha do tempo | [03-segmento-clicado.jpg](prints/mockup/03-segmento-clicado.jpg) |
| Cartões com miniaturas extraídas do vídeo | [04-cartoes-com-miniaturas.jpg](prints/mockup/04-cartoes-com-miniaturas.jpg) |
| Aba Pessoas | [05-aba-pessoas.jpg](prints/mockup/05-aba-pessoas.jpg) |
| Pessoa expandida (Nelson Rubens, 6 registros) | [06-pessoa-expandida.jpg](prints/mockup/06-pessoa-expandida.jpg) |
| Clique no tempo de uma aparição | [07-clique-na-aparicao.jpg](prints/mockup/07-clique-na-aparicao.jpg) |
| Aba Objetos de cena | [08-aba-objetos.jpg](prints/mockup/08-aba-objetos.jpg) |
| Aba Merchandising | [09-aba-merchandising.jpg](prints/mockup/09-aba-merchandising.jpg) |
| Aba JSON completo | [10-aba-json.jpg](prints/mockup/10-aba-json.jpg) |
| Busca "vermelho" | [11-busca-vermelho.jpg](prints/mockup/11-busca-vermelho.jpg) |
| Busca sem resultado | [12-busca-sem-resultado.jpg](prints/mockup/12-busca-sem-resultado.jpg) |
| Largura de 1024 px | [13-largura-1024.jpg](prints/mockup/13-largura-1024.jpg) |
| Quadro aos 36:00 | [14-quadro-36m00s.jpg](prints/mockup/14-quadro-36m00s.jpg) |
| Quadro aos 46:30, trecho sem decupagem | [15-quadro-46m30s-sem-decupagem.jpg](prints/mockup/15-quadro-46m30s-sem-decupagem.jpg) |

## O que foi testado e o que aconteceu

| Ação | Resultado |
| --- | --- |
| Play, Espaço e K | Tocam e pausam. Com o foco no campo de busca, as teclas viram texto, como deve ser |
| ← e → | Recuam e avançam 5 s |
| J e L | Recuam e avançam 10 s. Num editor de vídeo, J e L são retroceder e avançar contínuos; aqui são saltos, o que confunde quem vem do Premiere ou do Avid |
| I, O, vírgula e ponto | Não fazem nada: não há marcação de entrada e saída nem passo de quadro |
| Clique num bloco da linha do tempo | Seleciona a pauta, atualiza o painel e salta o player ao início |
| "Reproduzir trecho" | Toca do início ao fim da pauta e para sozinho no fim |
| Vídeo tocando por uma troca de pauta | O painel acompanha e passa para a pauta seguinte sem clique |
| Clique no tempo de uma aparição, na aba Pessoas | O player salta, mas a página continua rolada lá embaixo (y = 1.476 px), e o player fica fora da tela ([07](prints/mockup/07-clique-na-aparicao.jpg)) |
| "Ver 6 registros" de uma pessoa | Abre a lista de aparições com o figurino de cada uma e a pauta; a linha inteira de cartões cresce junto |
| Busca "vermelho", "Nelson", "sandália" | Filtra as pautas por texto e destaca na linha do tempo as que casaram. Devolve a pauta inteira (3 a 4 min), sem dizer por que casou nem em que segundo |
| Busca sem resultado | Mensagem clara: "Nenhum segmento encontrado. Tente outro nome, assunto ou timecode." |
| Gerar miniaturas | Extrai 54 quadros do MP4 no navegador. Antes disso, todos os cartões mostram o mesmo quadro ([02](prints/mockup/02-pagina-inteira.jpg)) |

Para os saltos funcionarem fora do mockup, o servidor do vídeo precisa aceitar pedidos de intervalo (HTTP Range). Com o `python -m http.server`, que não aceita, todo salto voltava para 00:00. O Cloud Storage, que serve o nosso proxy, aceita.

## O que a decupagem do mockup revela

- **Tempos que não batem com o vídeo.** Aos 36:00 o vídeo mostra o GC "Anitta estaria tentando 'apagar' musas", e a decupagem põe essa pauta em 37:21 ([14](prints/mockup/14-quadro-36m00s.jpg)). Aos 44:20, último tempo da decupagem, o quadro ainda mostra o GC da pauta da Deolane Bezerra, que ela põe em 35:31–37:21 ([13](prints/mockup/13-largura-1024.jpg)). A causa não foi apurada; a [ADR 0003](../adr/0003-tempos-do-modelo-em-mm-ss.md) registra um problema de tempos do modelo que pode ser o mesmo.
- **Trecho sem decupagem.** De 44:20 a 49:19 não há nada, e aos 46:30 há uma pauta inteira, "Polêmica com Cariúcha e Rico Melquiades", que a decupagem não registra ([15](prints/mockup/15-quadro-46m30s-sem-decupagem.jpg)). A faixa hachurada "Sem metadados" na linha do tempo é o que torna isso visível.
- **Miniatura não é evidência.** A miniatura de "Luiza Brunet" mostra o Nelson Rubens: o quadro é tirado pelo tempo, não pelo rosto. Uma miniatura assim parece prova e não é.
- **Nomes sem padrão.** "Flávia Noronha" convive com "DEOLANE BEZERRA" e "LEXA". Sem um catálogo de pessoas, a mesma pessoa vira dois nomes, e a busca erra.
- **Aparição do tamanho da pauta.** Flávia Noronha e Nelson Rubens "aparecem" de 00:11 a 03:17, o bloco inteiro. Não dá para saber em que plano cada um está.
- **Objetos sem tempo.** O próprio mockup avisa: "Os objetos não possuem timecodes individuais". Uma busca por objeto não teria trecho para devolver.
- **Figurino só como texto.** "Vestido preto midi com recortes vazados" é bom de ler, mas não dá para buscar "vestido preto" com segurança: não há cor nem tipo separados.

## O que funciona bem

- **Painel que acompanha o vídeo.** O item em foco muda sozinho quando o vídeo passa para outra pauta.
- **"Reproduzir trecho"**, que para no fim da pauta. É o gesto de quem procura um trecho para reaproveitar.
- **Linha do tempo das pautas com as lacunas à mostra**: o que o modelo não cobriu fica visível, em vez de sumir.
- **Busca que pinta a linha do tempo.** As pautas que casaram ficam destacadas na barra, e o editor vê onde está cada uma.
- **Figurino por aparição**, ligado à pessoa e ao trecho. É a semente da busca "sapato vermelho".
- **Cartões de pauta com miniatura real** do vídeo, tempo, tom e contagem de pessoas.
- **Mensagem de busca vazia** que diz o que tentar.
- **Atalhos mostrados embaixo do player**, onde o usuário os vê.

## O que atrapalha

- **Página longa com rolagem.** Player, painel e coleção ficam empilhados. Clicar num item da coleção tira o player da tela, e o editor perde o vídeo de vista.
- **Enfeite sem função.** Cinco números grandes no cabeçalho ("Último TC 44:20"), selo "● VÍDEO ORIGINAL", breadcrumb que não navega, cartões grandes e símbolos tipográficos (▦ ♙ ◫ ◈) como ícones. Tudo ocupa espaço que poderia ser decupagem.
- **Cor sem função.** O verde-água marca ao mesmo tempo o bloco selecionado, o botão principal, o tempo clicável e os títulos de seção.
- **J/L fora do padrão** dos editores de vídeo.
- **Busca de um vídeo só.** A caixa no topo parece buscar o acervo, mas filtra a decupagem aberta.
- **Tempos com milissegundos** (`00:00:00.000`) que o modelo não mede; dão uma precisão falsa.
- **Miniaturas geradas no navegador**, a pedido e a cada visita. Não escala para um acervo.

## O que falta diante das premissas

| Premissa | O que falta no mockup |
| --- | --- |
| Busca muito boa, com trechos exatos | Busca no acervo inteiro, resultado por vídeo com os momentos, o motivo de cada um ("objeto: sapato vermelho", "fala", "GC") e filtros por tipo |
| Pessoas | Separar aparição de menção (o mockup só tem aparição), a fonte do nome e a confirmação por referência de rosto |
| Objetos com atributos | Objetos com cor e tipo, tempo próprio e ligação com a pessoa que os usa |
| Transcrição | Não existe no mockup |
| Textos na tela | Não existem como lista. Os GCs só aparecem nas miniaturas |
| Marcas | Só uma ação comercial (RedeTV! Go). Não há marca incidental nem marca em objeto |
| Catalogação manual | Nenhuma edição. Tudo é leitura |
| Administração | Não existe |

## O que levar para o nosso desenho

1. O painel acompanha o vídeo, e "Reproduzir trecho" para no fim do trecho.
2. As lacunas da decupagem aparecem na linha do tempo.
3. A busca pinta os momentos na linha do tempo do vídeo.
4. O visual da pessoa fica junto da aparição, mas com cor e tipo separados.
5. O player nunca sai da tela. Player e painel ficam fixos lado a lado, e só o painel rola.
6. Nada de números de vaidade, selos e símbolos como ícone (ver [principios.md](principios.md)).
