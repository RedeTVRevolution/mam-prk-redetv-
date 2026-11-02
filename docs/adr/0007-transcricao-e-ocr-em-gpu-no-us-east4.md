# Transcrição e leitura da tela em GPU L4 no us-east4, com os Jobs em CPU como plano B

A transcrição (faster-whisper) e a leitura da tela (PaddleOCR) passam a rodar em Jobs do Cloud Run com GPU L4 em `us-east4`, no norte da Virgínia. Cada etapa tenta até 3 vezes na GPU; se as 3 falharem, os Jobs em CPU de hoje, em `southamerica-east1`, rodam no lugar (o desvio é do Workflows, no #239). As imagens com GPU são alvos novos do `Dockerfile` (`transcricao-gpu` e `ocr-gpu`), e o dispositivo vem da variável `DISPOSITIVO` (`cpu`, o padrão, ou `gpu`): a mesma lógica dos Jobs serve às duas versões.

Não existe GPU no Cloud Run em São Paulo. No programa FAMA de 49 min (Job `98502242109e4280b7073b07a3ebe573`, 1/11/2026), em CPU (8 vCPU, 16 GiB), a transcrição levou 24 min 46 s e o OCR, 49 min 01 s, uma etapa depois da outra. A CPU dos Jobs foi o maior custo do dia: R$ 7,50 para esse programa, puxada pelo OCR. A GPU deve encurtar as duas etapas; quanto, e o custo por programa, é o que o #240 mede no dev.

Em 01/11/2026, o jurídico da emissora aprovou o processamento passageiro em `us-east4` do **áudio** e do **vídeo em baixa resolução** (o proxy de 480p), **só para a transcrição e a leitura da tela**. Os limites:

- Nada fica guardado lá: os arquivos locais ficam no volume em memória (`/saida`) e são apagados ao fim de cada execução, e os resultados voltam para o bucket de aceitos, em São Paulo.
- O original, a cópia limpa e o resto do processamento continuam no Brasil.
- Nenhum bucket é criado em `us-east4`.
- Fora do escopo aprovado: qualquer outro dado, qualquer outra etapa e qualquer outra região. Mudar isso pede nova aprovação.

A transcrição e o texto lido na tela contêm falas e nomes, dados pessoais; sair do país é transferência internacional pela LGPD (art. 33). É a mesma linha das ADRs [0001](0001-gemini-endpoint-global.md) (o Gemini processa os vídeos fora do país e devolve), [0005](0005-identificacao-por-referencia.md) (dados biométricos e o aviso ao jurídico) e [0006](0006-indice-da-busca-nos-eua.md) (o índice da busca, também em `us-east4`, que **guarda** dados lá). Aqui nada é guardado: o processamento é só de passagem.

Segundo a documentação oficial dos Jobs com GPU (30/10/2026), a L4 em Jobs está liberada em `us-east4` sem convite; a primeira publicação recebe automaticamente uma cota de 3 GPUs; o modo sem redundância de zona é obrigatório para Jobs; o mínimo é de 4 CPUs e 16 GiB; o driver é o 580 (CUDA 13); a instância liga em cerca de 5 s.

O preço oficial: L4 a US$ 0,0001867 por segundo, CPU a US$ 0,000018 por segundo e memória a US$ 0,000002 por GiB por segundo. Com 4 CPUs e 16 GiB, são US$ 0,0002907 por segundo, uns US$ 1,05 por hora de máquina. O número que decide é o custo por programa, e ele só existe depois da medição do #240; se a GPU não for mais barata ou mais rápida que a CPU, esta ADR muda.

As imagens:
- **Transcrição:** o mesmo modelo (`large-v3-turbo`), na mesma revisão e com os mesmos hashes, vindos do alvo `transcricao`. O CTranslate2 4 pede CUDA 12 e cuDNN 9; as rodas `nvidia-cublas-cu12` e `nvidia-cudnn-cu12` do PyPI os trazem, e um runtime CUDA 12 roda num driver 580. Na GPU, o `compute_type` é `float16` (usa os tensor cores da L4 sem perder precisão); em CPU continua `int8`.
- **Leitura da tela:** os mesmos modelos, copiados do alvo `ocr`, e o `paddlepaddle-gpu` 3.2.2, a mesma versão do de CPU, com CUDA 12.6, do índice de rodas do Paddle (`pyproject.toml`). O erro do oneDNN que fixou o 3.2.2 é do caminho em CPU. Os grupos `ocr` e `ocr-gpu` declaram conflito no `uv.lock`, porque as duas rodas são o mesmo módulo `paddle`.
- **Falha clara:** com `DISPOSITIVO=gpu` numa instância sem GPU, o Job falha com mensagem que diz o motivo, e nunca cai para a CPU em silêncio. O log diz em qual dispositivo rodou.
- **Detecção de voz:** o Whisper pula o que não é fala (`vad_filter`), nas duas versões, com os tempos das palavras ainda contados do início do arquivo.
- **Construção e cache:** as imagens GPU vão para um repositório do Artifact Registry em `us-east4`, que guarda também o cache das camadas do build. É só código e modelos públicos, sem dado de vídeo, e deixa o Job puxar a imagem de 5 GB ou mais na mesma região em que roda. A sub-rede e o repositório nascem no `infra/main.tf`.
- **Modo de teste:** com `MODO_TESTE=1`, os Jobs não leem o bucket: rodam sobre uma amostra que já está na imagem (a transcrição, uma fala curta sintética, `/amostras/fala.wav`, gerada com espeak-ng; o OCR, um quadro com `REDETV`, `/amostras/quadro.png`) e saem com 20 se a GPU não funcionou ou 21 se o resultado veio errado.
- **Teste depois da publicação:** o `scripts/deploy-dev.sh` executa em modo de teste os Jobs com GPU cuja imagem mudou (`scripts/testar-jobs-gpu.sh`), em paralelo. Falta de GPU ou de cota espera e tenta de novo, com as tentativas e as esperas do Workflows (`gpu_*` no `infra/main.tf`; hoje 60 s e 120 s); qualquer outra falha derruba o teste. Se falhar, os Jobs voltam ao digest anterior, para o Workflows nunca disparar uma imagem que não roda na GPU; na primeira publicação não há digest anterior, e a publicação só falha.

Alternativas recusadas:
- **GPU em outra região dos EUA (`us-central1`, `us-west1`):** mais longe de São Paulo que `us-east4`, sem ganho que compense, e o jurídico aprovou `us-east4`.
- **Continuar em CPU:** é o custo e o tempo de hoje, com o OCR levando quase o tempo do próprio programa. Fica como plano B, não como caminho principal.
