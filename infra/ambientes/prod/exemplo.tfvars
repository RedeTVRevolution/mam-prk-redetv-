# Exemplo para prod: copie para prod.tfvars (fora do git) e troque pelos valores do projeto.
# Os nomes reais vêm do wizard; nada daqui é de um projeto de verdade.
projeto                = "SEU-PROJETO-PROD"
regiao                 = "us-east4"
admins_emergencia      = "admin1@exemplo.com,admin2@exemplo.com"
imagem                 = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem@sha256:DIGEST"
imagem_validacao       = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_validacao@sha256:DIGEST"
imagem_transcricao_gpu = "REGIAO_GPU-docker.pkg.dev/SEU-PROJETO-PROD/mam-gpu/imagem_transcricao_gpu@sha256:DIGEST"
imagem_ocr_gpu         = "REGIAO_GPU-docker.pkg.dev/SEU-PROJETO-PROD/mam-gpu/imagem_ocr_gpu@sha256:DIGEST"
imagem_objetos         = "REGIAO_GPU-docker.pkg.dev/SEU-PROJETO-PROD/mam-gpu/imagem_objetos@sha256:DIGEST"
# Vazio: sem balanceador, o endereço é o run.app. Com o domínio, veja "Domínio e balanceador" no infra/README.md.
dominio = ""
