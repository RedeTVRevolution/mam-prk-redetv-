# As imagens do MAM (#71, #211), montadas pelo cloudbuild.yaml num grafo só: o
# BuildKit roda em paralelo o que os alvos não dividem e monta uma vez o que dividem. Os
# endereços das imagens e do cache vêm das variáveis de ambiente (scripts/deploy-dev.sh),
# nunca escritos aqui. O cache de cada alvo é uma tag do repositório, sobrescrita a cada
# montagem, para os blobs não se acumularem.
variable "WEB" {}
variable "VALIDACAO" {}
variable "TRANSCRICAO" {}
variable "OCR" {}
variable "CACHE" {}
variable "VITE_IDENTITY_API_KEY" {
  default = ""
}

group "default" {
  targets = ["web", "validacao", "transcricao", "ocr"]
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

# As imagens com GPU (E1, ADR 0007): `docker buildx bake gpu` as monta, sem enviar nem
# usar cache (o repositório em us-east4, o cache e a publicação são do 238), por isso não
# estão no grupo `default`, que o cloudbuild.yaml envia.
group "gpu" {
  targets = ["transcricao-gpu", "ocr-gpu"]
}

target "transcricao-gpu" {
  target = "transcricao-gpu"
  tags   = ["mam-transcricao-gpu:local"]
}

target "ocr-gpu" {
  target = "ocr-gpu"
  tags   = ["mam-ocr-gpu:local"]
}
