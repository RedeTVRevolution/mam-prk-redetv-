mock_provider "google" {}

override_resource {
  target = module.mam.google_identity_platform_config.mam
}

variables {
  projeto                = "projeto-x"
  regiao                 = "us-east4"
  admins_emergencia      = "a@x.com"
  imagem                 = "img@sha256:a"
  imagem_validacao       = "img@sha256:a"
  imagem_transcricao_gpu = "img@sha256:a"
  imagem_ocr_gpu         = "img@sha256:a"
  imagem_objetos         = "img@sha256:a"
}

# Mescla de índices do Firestore (#542): um índice por filtro com o campo da ordem, e o
# Firestore cruza os índices na consulta. O emulador não exige índice, então esta é a
# conferência de que cada combinação de filtros que a API monta (api/nuvem.py, `consultar`
# do acervo e da auditoria) tem, para cada filtro seu, um índice (filtro + ordem) na mescla.
# Os índices por combinação que a mescla dispensa ficam em `indices_a_remover`, para o deploy
# seguinte (nesta publicação os antigos ficam, para nenhuma consulta ficar sem índice).
run "mescla_de_indices" {
  command = plan

  assert {
    condition = alltrue(flatten([
      for par in setproduct(range(1, 16), ["criado_em", "data_exibicao"]) : [
        for j, campo in ["programa", "sistema", "estado", "palavras"] :
        contains(output.indices_da_mescla.acervo, "${campo}+${par[1]}")
        if floor(par[0] / pow(2, j)) % 2 == 1
      ]
    ]))
    error_message = "Todo filtro do acervo precisa de um índice (filtro + ordem) na mescla."
  }
  assert {
    condition = alltrue([
      for campo in ["programa", "sistema", "estado", "palavras"] :
      contains(output.indices_da_mescla.acervo, "${campo}+criado_em")
    ]) && contains(output.indices_da_mescla.acervo_por_mes, "mes_exibicao+criado_em")
    error_message = "Todo filtro da lista por envio com período precisa de um índice (filtro + criado_em); os do acervo servem, e o mês tem o seu."
  }
  assert {
    condition = alltrue([
      for campo in ["uid", "email", "alvo_id", "acao"] :
      contains(output.indices_da_mescla.auditoria, "${campo}+quando")
    ])
    error_message = "Todo filtro da auditoria precisa de um índice (filtro + quando) na mescla."
  }
  assert {
    condition     = length(output.indices_da_mescla.acervo) + length(output.indices_da_mescla.acervo_por_mes) + length(output.indices_da_mescla.auditoria) <= 20
    error_message = "A mescla existe para ter ~15–20 índices no lugar de ~70."
  }
  # 30 + 16 + 11 (banco principal) + 11 (segurança) = 68 por combinação; ficam 8 + 1 + 4 + 4.
  assert {
    condition     = length(output.indices_a_remover) == 68 - (8 + 1 + 4 + 4)
    error_message = "A lista de remoção deve ter os índices por combinação que a mescla dispensa."
  }
}
