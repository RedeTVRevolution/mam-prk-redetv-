# As imagens do MAM (#71, #211, #238), montadas pelo cloudbuild.yaml num grafo só: o
# BuildKit roda em paralelo o que os alvos não dividem e monta uma vez o que dividem. Os
# endereços das imagens e do cache vêm das variáveis de ambiente (scripts/deploy-dev.sh),
# nunca escritos aqui. O cache de cada alvo é uma tag do repositório, sobrescrita a cada
# montagem, para os blobs não se acumularem.
variable "WEB" {}
variable "VALIDACAO" {}
variable "TRANSCRICAO" {}
variable "OCR" {}
variable "CACHE" {}
# As imagens com GPU vão para o repositório da região da GPU, com o cache delas ao lado
# (#238): o BuildKit, ao enviar a imagem, não reenvia as camadas que o cache já pôs lá.
variable "TRANSCRICAO_GPU" {}
variable "OCR_GPU" {}
variable "CACHE_GPU" {}
variable "VITE_IDENTITY_API_KEY" {
  default = ""
}

group "default" {
  targets = ["web", "validacao", "transcricao", "ocr", "transcricao-gpu", "ocr-gpu"]
}

target "base" {
  output = ["type=registry"]
}

target "web" {
  inherits   = ["base"]
  tags       = [WEB]
  args       = { VITE_IDENTITY_API_KEY = VITE_IDENTITY_API_KEY }
  cache-from = ["type=registry,ref=${CACHE}:web"]
  cache-to   = ["type=registry,ref=${CACHE}:web,mode=max,image-manifest=true,oci-mediatypes=true"]
}

target "validacao" {
  inherits   = ["base"]
  target     = "validacao"
  tags       = [VALIDACAO]
  cache-from = ["type=registry,ref=${CACHE}:validacao"]
  cache-to   = ["type=registry,ref=${CACHE}:validacao,mode=max,image-manifest=true,oci-mediatypes=true"]
}

target "transcricao" {
  inherits   = ["base"]
  target     = "transcricao"
  tags       = [TRANSCRICAO]
  cache-from = ["type=registry,ref=${CACHE}:transcricao"]
  cache-to   = ["type=registry,ref=${CACHE}:transcricao,mode=max,image-manifest=true,oci-mediatypes=true"]
}

target "ocr" {
  inherits   = ["base"]
  target     = "ocr"
  tags       = [OCR]
  cache-from = ["type=registry,ref=${CACHE}:ocr"]
  cache-to   = ["type=registry,ref=${CACHE}:ocr,mode=max,image-manifest=true,oci-mediatypes=true"]
}

# As imagens com GPU (E1, ADR 0007, #238): estão no grupo `default`, que o cloudbuild.yaml
# envia. O grupo `gpu` monta só elas, para quem quiser conferir uma construção à mão.
group "gpu" {
  targets = ["transcricao-gpu", "ocr-gpu"]
}

target "transcricao-gpu" {
  inherits   = ["base"]
  target     = "transcricao-gpu"
  tags       = [TRANSCRICAO_GPU]
  cache-from = ["type=registry,ref=${CACHE_GPU}:transcricao-gpu"]
  cache-to   = ["type=registry,ref=${CACHE_GPU}:transcricao-gpu,mode=max,image-manifest=true,oci-mediatypes=true"]
}

target "ocr-gpu" {
  inherits   = ["base"]
  target     = "ocr-gpu"
  tags       = [OCR_GPU]
  cache-from = ["type=registry,ref=${CACHE_GPU}:ocr-gpu"]
  cache-to   = ["type=registry,ref=${CACHE_GPU}:ocr-gpu,mode=max,image-manifest=true,oci-mediatypes=true"]
}
