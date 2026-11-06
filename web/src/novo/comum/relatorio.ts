import { PedidoInvalido, SessaoExpirada } from "../../api.ts";

// O que os relatórios têm em comum fora dos componentes (o oxlint pede componentes sozinhos nos .tsx).

export const CAMPO =
  "h-8 rounded-sm border border-strong bg-input px-2 text-sm disabled:cursor-not-allowed disabled:opacity-50";

export function mensagemDoErro(erro: unknown) {
  return erro instanceof PedidoInvalido
    ? erro.message
    : "Não foi possível montar o relatório agora. Tente de novo.";
}

/** O que as consultas dos relatórios repetem: a falha de rede, duas vezes; a sessão expirada e o pedido recusado (422), nunca. */
export const repetirFalha = (falhas: number, erro: unknown) =>
  !(erro instanceof SessaoExpirada) && !(erro instanceof PedidoInvalido) && falhas < 2;
