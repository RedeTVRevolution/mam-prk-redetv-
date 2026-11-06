import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";
import { useTabelaPaginada } from "./pilha";

test("filtros A, depois B, depois A de novo: a tabela recomeça, sem a página e a linha de A", () => {
  const { result, rerender } = renderHook(({ chave }) => useTabelaPaginada(chave), {
    initialProps: { chave: "A" },
  });
  act(() => result.current.avancar("c2"));
  act(() => result.current.abrir("pessoa1"));
  expect([result.current.pagina, result.current.aberta]).toEqual([2, "pessoa1"]);

  rerender({ chave: "B" });
  expect([result.current.pagina, result.current.aberta]).toEqual([1, null]);
  rerender({ chave: "A" });
  expect([result.current.pagina, result.current.aberta, result.current.cursor]).toEqual([1, null, ""]);
});
