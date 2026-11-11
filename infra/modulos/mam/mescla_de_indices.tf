# Mescla de índices do Firestore (#542): em vez de um índice por combinação de filtros (68),
# um índice por filtro com o campo da ordem (17), e o Firestore cruza os índices na consulta.
# Os da mescla já existem entre os por combinação (a combinação de um filtro só), então esta
# publicação não cria nem muda índice: só deixa pronta a lista do que sai.
#
# DEPLOY SEGUINTE (remoção): trocar o `for_each` de `acervo` (main.tf), `acervo_por_mes`
# (listagem_por_mes.tf), `auditoria` (main.tf) e `auditoria_na_seguranca`
# (banco_de_seguranca.tf) pelos locals `*_da_mescla` abaixo. O `terraform plan` tem de
# destruir exatamente os índices da saída `indices_a_remover` e mais nada. Só então, depois de
# medir as listas do Acervo e da auditoria no dev com os filtros pouco seletivos (ex.: só
# sistema), apagar os antigos. A mescla também precisa ser conferida no dev com dados reais:
# `estado in` e `palavras array-contains` junto com os outros filtros e a ordem; o que não
# atender volta a ter índice próprio.
locals {
  # Chaves dos recursos atuais que ficam: combinações de um campo só (potência de 2).
  indices_do_acervo_da_mescla = {
    for k, v in local.indices_do_acervo : k => v if length(v.campos) == 1
  }
  indices_do_acervo_por_mes_da_mescla = {
    for k, v in local.indices_do_acervo_por_mes : k => v if length(v) == 0
  }
  indices_da_auditoria_da_mescla = {
    for k, v in local.indices_da_auditoria : k => v if length(v) == 1
  }

  indices_a_remover = concat(
    [for k in keys(local.indices_do_acervo) : "acervo/${k}" if !contains(keys(local.indices_do_acervo_da_mescla), k)],
    [for k in keys(local.indices_do_acervo_por_mes) : "acervo_por_mes/${k}" if !contains(keys(local.indices_do_acervo_por_mes_da_mescla), k)],
    [for k in keys(local.indices_da_auditoria) : "auditoria/${k}" if !contains(keys(local.indices_da_auditoria_da_mescla), k)],
    [for k in keys(local.indices_da_auditoria) : "auditoria_na_seguranca/${k}" if !contains(keys(local.indices_da_auditoria_da_mescla), k)],
  )
}

# Os índices que ficam, como "filtro+ordem", para conferir que cada consulta da API é atendida.
output "indices_da_mescla" {
  value = {
    acervo         = [for v in values(local.indices_do_acervo_da_mescla) : "${v.campos[0]}+${v.ordem}"]
    acervo_por_mes = ["mes_exibicao+criado_em"]
    auditoria      = [for v in values(local.indices_da_auditoria_da_mescla) : "${v[0]}+quando"]
  }
}

# Os índices por combinação que a mescla dispensa: o que o deploy seguinte destrói.
output "indices_a_remover" {
  value = local.indices_a_remover
}
