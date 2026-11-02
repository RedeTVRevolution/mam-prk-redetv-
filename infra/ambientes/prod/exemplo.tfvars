# Exemplo para prod: copie para prod.tfvars (fora do git) e troque pelos valores do projeto.
# Os nomes reais vêm do wizard; nada daqui é de um projeto de verdade.
projeto                = "SEU-PROJETO-PROD"
regiao                 = "southamerica-east1"
admins_emergencia      = "admin1@exemplo.com,admin2@exemplo.com"
imagem                 = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem@sha256:DIGEST"
imagem_validacao       = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_validacao@sha256:DIGEST"
imagem_transcricao     = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_transcricao@sha256:DIGEST"
imagem_ocr             = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_ocr@sha256:DIGEST"
imagem_transcricao_gpu = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_transcricao_gpu@sha256:DIGEST"
imagem_ocr_gpu         = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_ocr_gpu@sha256:DIGEST"
imagem_objetos         = "REGIAO-docker.pkg.dev/SEU-PROJETO-PROD/mam/imagem_objetos@sha256:DIGEST"
