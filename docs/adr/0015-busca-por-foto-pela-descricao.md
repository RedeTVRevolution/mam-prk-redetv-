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
- A busca segue pelo mesmo caminho do texto digitado: `entender` (saneamento e as regras locais, sem modelo nem Model Armor desde o #517, ADR 0018), índice, ranking e cursor de página. O termo é saída de modelo e entrada não confiável, como o texto digitado, e o limite de 60 caracteres vale antes do entendimento. A instrução diz que texto escrito na foto é parte da imagem, nunca ordem. A busca visual (`visual`) e o vetor da foto não entram.
- O termo que a busca usou volta em `entendida.termo_da_foto`, também nas páginas seguintes (a lista guardada o leva), e a tela mostra "Buscando por: microfone", para a pessoa entender o resultado e refinar digitando.
- Voltam momentos de todos os tipos, como na busca por texto, e não só planos.
- O rótulo de custo da chamada que descreve a foto é `descricao_da_foto`, separado do `entendimento_da_consulta`.

## Sem plano B

Se o modelo da consulta não está ligado, falha, demora, responde fora do esquema ou não acha objeto na foto, a rota responde 503 ("A busca por imagem não está disponível agora"). A busca por texto cai em palavras soltas porque há texto digitado; a foto não tem esse texto. A alternativa era cair no vetor da foto, como antes. Foi descartada porque:
- ele acerta 26% e não tem corte útil: devolveria cenas erradas como se fossem resultado, e a pessoa não saberia que o modelo estava fora;
- manteria o código do vetor da foto (`vetor_da_imagem`) só para esse caso;
- o 503 já era o padrão da busca por foto quando a imagem não vira busca, e a web já o trata.

A busca em si não passa pelo modelo (#517): o termo da foto entra nela como texto digitado, e não há entendimento nem plano B dele.

## Custo e tempo

Cada busca por foto faz uma chamada só ao Flash-Lite, com a imagem (descrever); a busca depois não passa pelo modelo (#517), só pelo índice e pelo ranking de qualquer busca. O embedding da foto sai. O prazo da rota da foto é o da busca por texto mais o teto dessa chamada (`TEMPO_DA_CONSULTA_S`). A página seguinte sai da lista guardada e não chama o modelo.

Trocar o programa ou o período é consulta nova, e antes repetia a chamada ao modelo e o envio da foto (até 5 MB) a cada troca. Desde o #802 a 1ª resposta traz um token (`X-Token-Da-Foto`): o id de um documento curto da coleção `listas_da_busca`, com o dono, o termo que o modelo deu, o SHA-256 do JPEG regravado e o prazo de 15 min. A foto nunca é guardada: o hash não permite refazê-la. Com o token no lugar do arquivo, a rota não chama o modelo nem decodifica a foto, e a impressão do cursor é a da 1ª página, então o cursor vale com o token. Token vencido, de outro dono ou que não é de token responde 422 `Token da foto inválido`, e a tela reenvia a foto.

## O que continua

Em 6/11/2026 o Bruno decidiu tirar também o vetor do quadro, a busca visual por texto (`visual`) e os planos parecidos (`GET /v1/busca/parecidos`), por serem ruins e desnecessários (#476). Não sobra vetor de imagem: só o vetor da descrição fica (o embedding automático do campo `significado`, ou `AgentRetrieval.vetor_da_consulta` sem o índice ANN), e a busca por foto, que já passava só pelo texto, segue igual.

## O que não foi medido

Os 88% valem para as três fotos e para as cenas marcadas na medição. O texto de uma característica só não foi medido, e fotos novas precisam de marcação para entrar na conta.

## Pessoa famosa na foto (23/11/2026, #810)

No dev, a foto do Neymar virou "Buscando por: boné branco" e trouxe pessoas quaisquer de boné branco. A instrução, escrita para objetos, proibia o nome. Ficou decidido:

- Continua uma chamada só ao Flash-Lite por foto. O esquema ganha `pessoa` (nulo ou nome) ao lado de `termo`. Com `pessoa` válida, a busca usa só o nome, porque "Neymar boné branco" dilui o resultado; sem ela, segue pelo termo do objeto. O nome entra como texto digitado: acha a pessoa do catálogo pelo nome ou apelido e soma as cláusulas de aparição e menção, sem segunda chamada nem efeito nos filtros do servidor.
- O nome vem sem aspas, para nunca virar frase exata, e só vale com ao menos uma letra ou dígito. Se ele está inteiro, por palavras, dentro do nome ou de um apelido de uma pessoa só do catálogo, vira o nome dela ("Ronaldinho" vira "Ronaldinho Gaúcho"); senão, fica como veio.
- O nome do modelo é só o texto da consulta. Ele não confirma nada na Decupagem, onde valem as ADRs 0005 e 0012.
- A instrução da pessoa é rígida: o normal é nulo; só celebridade de fama nacional ou mundial reconhecida sem nenhuma dúvida; na menor dúvida, nulo; um nome errado é pior que nenhum. A regra do termo continua dizendo "sem pessoa": quando a instrução fala de pessoas, o termo passa a descrevê-la ("homem com boné branco").

Medição (dev, 23/11, 3.5 Flash-Lite, Standard, 5 rodadas por foto, instrução rígida): Neymar 5/5 com o nome (às vezes "Neymar Jr."); rapaz anônimo de boné branco, dois rapazes anônimos, anônimos na praça e o Caio Sorriso (apresentador pouco conhecido) nulo 5/5 cada. Com uma instrução branda ("se reconhecer com segurança"), o modelo inventou nome em 2 de 12 rodadas: chamou o rapaz anônimo de "Tierry" e o Caio Sorriso de "Leandro Hassum". A instrução rígida é requisito.

Não foi medido: a amostra é de 5 fotos e 25 rodadas; o texto final da instrução no código, que pode diferir em palavras do texto medido; outras celebridades e fotos de mais de uma pessoa. Um nome inventado aparece em "Buscando por:", e quem enviou a foto percebe na hora.
