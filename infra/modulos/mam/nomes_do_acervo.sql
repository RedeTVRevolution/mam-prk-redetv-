-- Os nomes próprios do acervo, para as variantes de grafia da busca (#734, api/variantes.py).
-- Nome próprio: palavra que, no meio da frase da fala e da descrição do plano, vem com
-- maiúscula em pelo menos 60% das vezes. Fica só a que soma 3 ou mais ocorrências no acervo
-- (fala, GC, plano e pauta). Sem acento e em minúsculas, como a busca compara.
WITH no_meio AS (
  SELECT
    REGEXP_REPLACE(LOWER(NORMALIZE(w, NFD)), r"\pM", "") AS palavra,
    REGEXP_CONTAINS(w, r"^\p{Lu}\p{Ll}") AS maiuscula
  FROM `${tabela_de_momentos}`,
    UNNEST(REGEXP_EXTRACT_ALL(texto, r"[^.!?:;\n]\s+(\p{L}+)")) AS w
  WHERE tipo IN ("fala", "plano")
),
nomes AS (
  SELECT palavra
  FROM no_meio
  WHERE LENGTH(palavra) > 2
  GROUP BY palavra
  HAVING COUNTIF(maiuscula) / COUNT(*) >= 0.6
),
todas AS (
  SELECT palavra
  FROM `${tabela_de_momentos}`,
    UNNEST(REGEXP_EXTRACT_ALL(REGEXP_REPLACE(LOWER(NORMALIZE(texto, NFD)), r"\pM", ""), r"[a-z]+")) AS palavra
  WHERE tipo IN ("fala", "texto_na_tela", "plano", "pauta")
)
SELECT palavra, COUNT(*) AS ocorrencias
FROM todas
WHERE palavra IN (SELECT palavra FROM nomes)
GROUP BY palavra
HAVING ocorrencias >= 3
