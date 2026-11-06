// O que os testes da curadoria (fase 5) têm em comum: a decupagem e as linhas do histórico.

export const DECUPAGEM = {
  versao_decupagem: 'v1',
  pautas: [
    { id: 'pa1', titulo: 'Eleição', resumo: 'Debate', tom: 'informativo', inicio_ms: 0, fim_ms: 60_000 },
    { id: 'pa2', titulo: 'Clima', resumo: 'Chuva', tom: 'informativo', inicio_ms: 60_000, fim_ms: 90_000 },
    { id: 'pa3', titulo: 'Esporte', resumo: 'Copa', tom: 'informativo', inicio_ms: 90_000, fim_ms: 120_000 },
  ],
  pessoas: [
    {
      id: 'p1',
      nome: 'Leão Lobo',
      catalogo_id: 'cat-leao',
      fontes_do_nome: ['rosto'],
      na_imagem: [{ inicio_ms: 10_000, fim_ms: 20_000, evidencia: 'rosto', papel: 'jurado', visual: 'barba' }],
      citada_na_fala: [{ inicio_ms: 30_000, fim_ms: 32_000 }],
      citada_no_texto: [],
    },
  ],
  planos: [],
  comerciais: [{ id: 'c1', marca: 'Marca X', tipo: 'intervalo', inicio_ms: 40_000, fim_ms: 50_000 }],
  transcricao: [{ id: 'f1', locutor: 'Ana', texto: 'Boa noite', inicio_ms: 0, fim_ms: 3_000 }],
  textos_na_tela: [],
  objetos: [],
}

export function correcaoDoHistorico(id: string, autor: string, estado = 'ativa', tipo = 'pessoa.renomear') {
  return {
    id,
    tipo,
    estado,
    item_id: 'p1',
    ancora: { versao: 'v1', tipo_do_item: 'pessoa' },
    criada_em: '2026-10-31T12:00:00Z',
    motivo: 'nome corrigido',
    autor_email: autor,
    antes_legivel: 'Não identificado',
    depois_legivel: 'Leão Lobo',
  }
}
