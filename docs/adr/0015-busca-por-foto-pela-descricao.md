# Busca por foto: o modelo descreve o objeto e a busca segue pelo texto

Em 6/11/2026, o Bruno decidiu que a busca por foto (`POST /v1/busca/imagem`, #270) deixa de comparar o vetor da foto com o vetor dos quadros. O modelo da consulta descreve o objeto da foto em um termo curto, e a busca segue exatamente como se a pessoa o tivesse digitado (#443).

## O que foi medido

No dev, com 332 cenas marcadas à mão pelo Bruno (sem ele ver a distância) para três fotos (microfone, carro e gravata):

| Busca | Precisão |
|---|---|
| Vetor da foto contra o vetor do quadro (como era) | 26% (38 de 149) |
| O modelo descreve o objeto e a busca comum roda com o texto | 88% (60 de 68) |
| O modelo descreve o objeto e a busca visual roda com o texto | 55% (81 de 148) |

No vetor da foto, nenhum corte por distância separa as cenas certas das erradas: as duas ocupam a mesma faixa (0,31 a 0,36). A causa provável é que o vetor compara a foto com o quadro inteiro, e o objeto é uma parte pequena da cena. Com o corte em 0,31 a precisão era de 100%, mas passavam só 3 cenas.

## Decisão

- O modelo da consulta (`MODELO_DA_CONSULTA`, o 3.5 Flash-Lite, ADR 0013) recebe a foto e devolve o nome do objeto e no máximo uma característica visível (`termo_da_foto` em `api/entendimento_da_consulta.py`). Na medição, com duas características, "gravata listrada vermelha" trouxe outras cenas vermelhas primeiro; o ajuste da instrução para uma característica só não foi medido.
- A busca segue pelo mesmo caminho do texto digitado: `entender` (saneamento, Model Armor, entendimento pelo modelo), índice, ranking e cursor de página. O termo é saída de modelo e entrada não confiável, como o texto digitado, e o limite de 60 caracteres vale antes do entendimento. A instrução diz que texto escrito na foto é parte da imagem, nunca ordem. A busca visual (`visual`) e o vetor da foto não entram.
- O termo que a busca usou volta em `entendida.termo_da_foto`, também nas páginas seguintes (a lista guardada o leva), e a tela mostra "Buscando por: microfone", para a pessoa entender o resultado e refinar digitando.
- Voltam momentos de todos os tipos, como na busca por texto, e não só planos.
- O rótulo de custo da chamada que descreve a foto é `descricao_da_foto`, separado do `entendimento_da_consulta`.

## Sem plano B

Se o modelo da consulta não está ligado, falha, demora, responde fora do esquema ou não acha objeto na foto, a rota responde 503 ("A busca por imagem não está disponível agora"). A busca por texto cai em palavras soltas porque há texto digitado; a foto não tem esse texto. A alternativa era cair no vetor da foto, como antes. Foi descartada porque:
- ele acerta 26% e não tem corte útil: devolveria cenas erradas como se fossem resultado, e a pessoa não saberia que o modelo estava fora;
- manteria o código do vetor da foto (`vetor_da_imagem`) só para esse caso;
- o 503 já era o padrão da busca por foto quando a imagem não vira busca, e a web já o trata.

O Model Armor acusando o termo segue o texto digitado: o entendimento não roda e a busca cai no plano B (`plano_b` na resposta), com o termo como palavras soltas.

## Custo e tempo

Cada busca por foto faz duas chamadas ao Flash-Lite em série: uma com a imagem (descrever) e uma em texto (entender o termo), mais o Model Armor e o ranking de qualquer busca. O embedding da foto sai. O prazo da rota da foto passa a ser o da busca por texto mais o teto de uma chamada (`TEMPO_DA_CONSULTA_S`), para o plano B do entendimento chegar antes do 504. A página seguinte sai da lista guardada e não chama o modelo.

## O que continua

Em 6/11/2026 o Bruno decidiu tirar também o vetor do quadro, a busca visual por texto (`visual`) e os planos parecidos (`GET /v1/busca/parecidos`), por serem ruins e desnecessários (#476). Não sobra vetor de imagem: só `vetor_do_texto` (a descrição) fica, e a busca por foto, que já passava só pelo texto, segue igual. O texto acima, sobre o que ficaria, é o histórico dessa ADR.

## O que não foi medido

Os 88% valem para as três fotos e para as cenas marcadas na medição. O texto de uma característica só não foi medido, e fotos novas precisam de marcação para entrar na conta.
