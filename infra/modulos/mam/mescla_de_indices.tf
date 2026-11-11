# Mescla de índices do Firestore (#542): em vez de um índice por combinação de filtros (68),
# um índice por filtro com o campo da ordem (17), e o Firestore cruza os índices na consulta.
# Os `for_each` de `acervo` (main.tf), `acervo_por_mes` (listagem_por_mes.tf), `auditoria`
# (main.tf) e `auditoria_na_seguranca` (banco_de_seguranca.tf) usam os locals `*_da_mescla`
# abaixo; as chaves dos que ficam não mudam, então nada é recriado, só os 51 de
# `indices_a_remover` são destruídos. Sem exceção: `in` (disjunção de igualdades),
# `array-contains` e a igualdade entram na mescla (a documentação do Firestore só cita `==`
# e pede índice composto para `array-contains` com outros filtros, por desempenho). Se uma
# consulta ficar lenta, volta a ter índice próprio: incluir a chave no `if` do local.
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

# Os índices por combinação que a mescla dispensa: o que o deploy da remoção destrói.
output "indices_a_remover" {
  value = local.indices_a_remover
}

# As chaves dos recursos que o plano mantém (lidas dos recursos, não dos locals), para o teste
# conferir que sobra só a mescla.
output "indices_que_ficam" {
  value = {
    acervo                 = keys(google_firestore_index.acervo)
    acervo_por_mes         = keys(google_firestore_index.acervo_por_mes)
    auditoria              = keys(google_firestore_index.auditoria)
    auditoria_na_seguranca = keys(google_firestore_index.auditoria_na_seguranca)
  }
}
