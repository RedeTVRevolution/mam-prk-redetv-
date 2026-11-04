# Chave MAC do hash das chaves de API dos sistemas legados (#272). O key ring e a chave
# não podem ser apagados no Cloud KMS: o `destroy` só agenda a destruição das versões.
# Rotação manual: crie uma versão nova (README da infra); a mais alta ativa vira a atual
# e as chaves de API trocam de versão sozinhas no primeiro uso. O `google_kms_crypto_key`
# nasce com a versão 1.
resource "google_kms_key_ring" "mam" {
  name       = "mam"
  location   = var.regiao
  depends_on = [google_project_service.apis]
}

resource "google_kms_crypto_key" "chaves_de_api" {
  name     = "chaves-de-api"
  key_ring = google_kms_key_ring.mam.id
  purpose  = "MAC"
  version_template {
    algorithm        = "HMAC_SHA256"
    protection_level = "SOFTWARE"
  }
}

# A API só assina e verifica nessa chave, e lê a lista de versões dela (o `viewer`)
# para achar a atual; nada no projeto inteiro.
resource "google_kms_crypto_key_iam_member" "web_usa_a_chave_mac" {
  for_each      = toset(["roles/cloudkms.signerVerifier", "roles/cloudkms.viewer"])
  crypto_key_id = google_kms_crypto_key.chaves_de_api.id
  role          = each.value
  member        = google_service_account.mam["web"].member
}
