# Inventário de objetos com o Florence-2 em GPU L4 no us-east4

> **Região substituída em 09/11/2026 pela [ADR 0019](0019-tudo-em-us-east4.md):** todo o MAM, dados incluídos, passa a ficar em `us-east4`. O que esta ADR diz sobre guardar dados no Brasil ou sobre a região dos buckets, do Firestore e do BigQuery deixou de valer.

A etapa de inventário de objetos (objetos de cena: veículo, produto, eletrônico, animal, comida) roda o Florence-2 num Job do Cloud Run com GPU L4 em `us-east4`, o `mam-objetos-gpu`, ao lado dos Jobs da [ADR 0007](0007-transcricao-e-ocr-em-gpu-no-us-east4.md). O Job lê a Decupagem do bucket das decupagens (que traz os quadros-chave de cada plano), roda o modelo em cada quadro e grava o resultado bruto em `<job>/objetos/florence.json`, no mesmo bucket, em São Paulo. O Workflows roda sempre o Florence: a variável `motor_objetos` (`florence` ou `gemini`) foi retirada do Terraform e do Workflows em 19/11/2026.

**Modelo:** `florence-community/Florence-2-large`, revisão `4271c66b88cdbc05735372ec13b2360108de5317`. É a conversão oficial para o `transformers` (nativa a partir do 4.56; fixamos o `transformers==4.57.6` e o `torch==2.15.0`) do Florence-2-large da Microsoft, com 0,77 bilhão de parâmetros, licença MIT, e roda sem `trust_remote_code`: o repositório original da Microsoft pede código remoto, que não aceitamos executar. Os pesos têm cerca de 1,6 GB em float16, bem abaixo dos 24 GB da L4 e dos 16 GiB do Job. As tarefas são `<OD>` (objetos com caixa) e `<DENSE_REGION_CAPTION>` (regiões com legenda); a geração usa `num_beams=3`. Na CPU, só no teste da imagem, o dtype é float32.

**Imagem:** alvo `objetos-gpu` do `Dockerfile`. Os 11 arquivos do modelo e o quadro de amostra são baixados com o hash SHA-256 conferido, o `transformers` roda offline (`HF_HUB_OFFLINE=1`) e o grupo `objetos` do `pyproject.toml` (`torch` e `transformers` fixados) conflita no `uv.lock` com `ocr`, `ocr-gpu` e `transcricao`, para as versões dos outros Jobs não mudarem. Como nos outros Jobs com GPU, `DISPOSITIVO=gpu` numa instância sem GPU falha com mensagem clara, nunca cai para a CPU em silêncio, e `MODO_TESTE=1` roda a amostra (o carro de `/amostras/objetos.jpg`, objeto esperado `car`) sem tocar a nuvem, saindo com 20 ou 21 como os outros. O teste entra no `scripts/testar-jobs-gpu.sh` como um terceiro Job.

**Acréscimo à publicação:** a imagem tem uns 8 GB (torch, rodas NVIDIA e pesos); o teste carrega a imagem (1 a 2 min), carrega os pesos e faz duas gerações. Ele roda em paralelo com os outros dois, então o acréscimo é só o que passar do mais lento. O `timeout` do `cloudbuild.yaml` sobe de 3600 para 5400 s (download de 4 a 5 GB de torch e rodas, 1,6 GB de pesos, conferência em CPU e cache `mode=max` de uns 6 GB). O tempo medido fica para a primeira publicação real, que nenhum agente fez: não havia Docker nem nuvem aqui.

**Aprovação do jurídico (01/11/2026):** ao lado da aprovação do mesmo dia para o áudio e o proxy de 480p da transcrição e da leitura da tela (#237, [ADR 0007](0007-transcricao-e-ocr-em-gpu-no-us-east4.md)), o processamento passageiro em `us-east4` cobre também os quadros-chave **em resolução cheia, extraídos da cópia limpa**, só para o inventário de objetos. Os limites são os da ADR 0007: nada fica guardado lá (os quadros são lidos para a memória e o volume `/saida` é em memória), o resultado volta para o bucket das decupagens em São Paulo, nenhum bucket nasce em `us-east4`, e qualquer outro dado, etapa ou região pede nova aprovação. O quadro cheio da cópia limpa mostra pessoas e é dado pessoal; vale a mesma linha da LGPD (art. 33) e das ADRs [0001](0001-gemini-endpoint-global.md) e [0006](0006-indice-da-busca-nos-eua.md).

**Permissões:** conta de serviço própria (`objetos`), com `roles/storage.objectUser` só no bucket das decupagens, sem Firestore. A orquestração ganha `run.developer` no Job. Nenhum papel novo para a `mam-terraform`.

Alternativas recusadas:
- **Florence-2 da Microsoft com código remoto:** exige executar código baixado em tempo de execução.
- **Florence-2 em CPU:** seria mais um Job lento em CPU por quadro. Como na decisão de 07/11/2026 da ADR 0007, não há plano B em CPU: o Florence espera na fila FIFO e, se falhar, a decupagem segue sem inventário. O motor `gemini` não é desvio automático nem configuração: saiu do Terraform e do Workflows em 19/11/2026.
- **Outra região:** o jurídico aprovou `us-east4`.

## Revisão de 07/11/2026 — base, geração gulosa e lote 16 (#490)

No FAMA (Job `98502242109e4280b7073b07a3ebe573`, 421 quadros), as medições com o Florence-2-large foram:

| Variação | Tempo | Destaque 3 que sumiu |
| --- | --- | --- |
| Hoje: 3 feixes, lote 1, com legendas | 863 s | — |
| Guloso, lote 1 | 727 s | 16 |
| Guloso + lote 8 | 376 s | 15 |
| Guloso + lote 16 | 318 s (2,7×) | 8 |
| Sem legendas | 414 s (2,1×) | 10 |
| Guloso + lote 16 + sem legendas | 237 s (3,6×) | 18 |

A decisão é geração gulosa (`num_beams=1`), lote 16, mantendo `<OD>` e `<DENSE_REGION_CAPTION>`. Tirar as legendas economiza só cerca de 80 s além do guloso com lote 16, longe da meta de 5×, e dobra os objetos de destaque 3 perdidos. Sem elas, o inventário perde cor e marca dos objetos de cena, prejudicando buscas como “carro vermelho”. O lote 8 é mais lento e não foi melhor; boa parte da diferença nos perdidos entre lotes é ruído da conversão pelo Gemini. A leitura dos quadros corre junto da inferência, com uma thread e no máximo dois lotes à frente, preservando a ordem.

O padrão do Terraform passou a ser o **Florence-2-base** (revisão `00921df66db728a9ceb750f5eca43e5c203a2051`) e voltou ao large em 09/11 (ver abaixo); o base saiu da imagem, do código e do Terraform em 19/11 (#746). Sem `FLORENCE_MODELO`, o padrão do código é o large; cada resultado grava o repositório e a revisão que rodaram. A conferência da construção roda só o large em CPU, e a publicação o testa na GPU, procurando o carro da amostra.

O base tem 0,23 bilhão de parâmetros, contra 0,77 do large, e mAP zero-shot no COCO de 34,7 contra 37,5. O plano de então (histórico, abandonado com a retirada do base em 19/11) era comparar `large+guloso+lote16` e `base+guloso+lote16` no FAMA contra a referência `hoje` já gravada (863 s, large, 3 feixes, lote 1), e voltar ao large pela variável se o base perdesse bem mais objetos de destaque 3. A variação `base+guloso+lote16` já não existe no `make medir-florence`.

Em 09/11/2026 o padrão voltou ao **large**, mantendo guloso e lote 16: no ar, o base achou visivelmente menos objetos que antes. A medição base × large no FAMA nunca foi feita.

Em 19/11/2026 o base saiu da imagem do Job de objetos, do `MODELOS` de `api/florence.py` e da variável `florence_modelo` do Terraform (#746): não roda no pipeline desde 09/11, e um modelo só dispensa a variável.

`torch.compile` e o cache de compilação foram estudados e recusados em 07/11/2026: exigiriam compilador C na imagem, compilariam a cada execução do Job e só funcionam em parte com o Florence.
