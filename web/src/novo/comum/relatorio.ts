import { PedidoInvalido } from "../../api.ts";

// O que os relatórios têm em comum fora dos componentes (o oxlint pede componentes sozinhos nos .tsx).

export const CAMPO =
  "h-8 rounded-sm border border-strong bg-input px-2 text-sm disabled:cursor-not-allowed disabled:opacity-50";

export function mensagemDoErro(erro: unknown) {
  return erro instanceof PedidoInvalido
    ? erro.message
    : "Não foi possível montar o relatório agora. Tente de novo.";
}
