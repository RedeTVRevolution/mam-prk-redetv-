-- Tabelas resumidas do painel da diretoria (#280, E9). Roda de tempos em tempos como
-- consulta agendada (`resumos_de_uso.tf`) e refaz as seis tabelas a partir dos eventos de
-- uso (#279). `${prefixo}` é o prefixo `projeto.dataset.` das tabelas que ele cria, e
-- `${tabela_de_eventos}` e `${tabela_de_momentos}` são os nomes inteiros das que ele lê, que
-- o `main.tf` e o `eventos_de_uso.tf` montam (os testes rodam este arquivo no SQLite, sem
-- prefixo: por isso só há SQL comum aos dois, salvo a data com fuso e o CREATE OR REPLACE TABLE).
--
-- Eventos repetidos (o mesmo `id`) valem uma vez. O Job reprocessado que chega de novo ao
-- mesmo estado final também conta uma vez só (vale o primeiro); o que falhou e depois
-- concluiu conta uma falha e uma conclusão. O dia é o de São Paulo. As horas são as dos
-- vídeos concluídos, pela duração que a cópia dos momentos guarda
-- (`momentos.duracao_do_video_ms`); vídeo ainda não copiado conta como 0 hora. O tempo de
-- processamento médio divide `segundos_de_processamento` por `videos_concluidos_com_tempo`: o
-- fim gravado antes de o evento trazer o tempo não entra em nenhum dos dois.
CREATE TEMP TABLE eventos AS
SELECT
  e.dia, e.quando, e.tipo, e.quem_tipo, e.quem_id, e.programa, e.estado,
  e.segundos_de_processamento, e.n_resultados, e.tipo_de_correcao, e.metodo, e.rota, e.status,
  COALESCE(d.horas, 0) AS horas
FROM (
  SELECT
    u.*,
    ROW_NUMBER() OVER (PARTITION BY tipo, job_id, estado ORDER BY quando) AS vez
  FROM (
    SELECT
      id, quando, tipo, quem_tipo, quem_id, programa, estado, job_id,
      segundos_de_processamento, n_resultados, tipo_de_correcao, metodo, rota, status,
      DATE(quando, 'America/Sao_Paulo') AS dia,
      ROW_NUMBER() OVER (PARTITION BY id ORDER BY quando) AS ordem
    FROM `${tabela_de_eventos}`
  ) AS u
  WHERE u.ordem = 1
) AS e
LEFT JOIN (
  SELECT job_id, MAX(duracao_do_video_ms) / 3600000.0 AS horas
  FROM `${tabela_de_momentos}`
  GROUP BY job_id
) AS d ON d.job_id = e.job_id
WHERE e.tipo <> 'fim_de_processamento' OR e.vez = 1;

-- Um dia, um usuário (ou sistema). As duas tabelas seguintes somam esta. `ativo` diz se
-- quem é da linha agiu no dia: o fim de processamento é atribuído a quem enviou o vídeo e,
-- sozinho (o vídeo que termina no dia seguinte), não faz ninguém ativo.
CREATE OR REPLACE TABLE `${prefixo}uso_por_dia_e_usuario` AS
SELECT
  dia, quem_tipo, quem_id,
  COUNT(CASE WHEN tipo <> 'fim_de_processamento' THEN 1 END) > 0 AS ativo,
  MAX(CASE WHEN tipo = 'login' THEN quando END) AS ultimo_acesso,
  COUNT(CASE WHEN tipo = 'login' THEN 1 END) AS acessos,
  COUNT(CASE WHEN tipo = 'envio' THEN 1 END) AS videos_enviados,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN 1 END) AS videos_concluidos,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'falhou' THEN 1 END) AS videos_falhos,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN horas END), 0) AS horas_concluidas,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN segundos_de_processamento END), 0) AS segundos_de_processamento,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' AND segundos_de_processamento IS NOT NULL THEN 1 END) AS videos_concluidos_com_tempo,
  COUNT(CASE WHEN tipo = 'busca' THEN 1 END) AS buscas,
  COUNT(CASE WHEN tipo = 'busca' AND n_resultados = 0 THEN 1 END) AS buscas_sem_resultado,
  COUNT(CASE WHEN tipo = 'correcao' THEN 1 END) AS correcoes,
  COUNT(CASE WHEN tipo = 'chamada_de_api' THEN 1 END) AS chamadas_de_api
FROM eventos
GROUP BY dia, quem_tipo, quem_id;

-- Um dia, todos juntos. `usuarios_ativos` são só as pessoas que agiram, não os sistemas.
CREATE OR REPLACE TABLE `${prefixo}uso_por_dia` AS
SELECT
  dia,
  COUNT(CASE WHEN quem_tipo = 'usuario' AND ativo THEN 1 END) AS usuarios_ativos,
  SUM(acessos) AS acessos,
  SUM(videos_enviados) AS videos_enviados,
  SUM(videos_concluidos) AS videos_concluidos,
  SUM(videos_falhos) AS videos_falhos,
  SUM(horas_concluidas) AS horas_concluidas,
  SUM(segundos_de_processamento) AS segundos_de_processamento,
  SUM(videos_concluidos_com_tempo) AS videos_concluidos_com_tempo,
  SUM(buscas) AS buscas,
  SUM(buscas_sem_resultado) AS buscas_sem_resultado,
  SUM(correcoes) AS correcoes,
  SUM(chamadas_de_api) AS chamadas_de_api
FROM `${prefixo}uso_por_dia_e_usuario`
GROUP BY dia;

-- Um usuário (ou sistema), o histórico todo.
CREATE OR REPLACE TABLE `${prefixo}uso_por_usuario` AS
SELECT
  quem_tipo, quem_id,
  COUNT(CASE WHEN ativo THEN 1 END) AS dias_ativos,
  MAX(ultimo_acesso) AS ultimo_acesso,
  SUM(acessos) AS acessos,
  SUM(videos_enviados) AS videos_enviados,
  SUM(videos_concluidos) AS videos_concluidos,
  SUM(videos_falhos) AS videos_falhos,
  SUM(horas_concluidas) AS horas_concluidas,
  SUM(segundos_de_processamento) AS segundos_de_processamento,
  SUM(videos_concluidos_com_tempo) AS videos_concluidos_com_tempo,
  SUM(buscas) AS buscas,
  SUM(buscas_sem_resultado) AS buscas_sem_resultado,
  SUM(correcoes) AS correcoes,
  SUM(chamadas_de_api) AS chamadas_de_api
FROM `${prefixo}uso_por_dia_e_usuario`
GROUP BY quem_tipo, quem_id;

-- Um dia, um programa. O login e a chamada de API não têm programa; o evento sem programa
-- fica de fora. A busca só tem programa quando foi filtrada por ele: `buscas` conta as buscas
-- feitas dentro do programa, não as que acharam algo dele.
CREATE OR REPLACE TABLE `${prefixo}uso_por_dia_e_programa` AS
SELECT
  dia, programa,
  COUNT(CASE WHEN tipo = 'envio' THEN 1 END) AS videos_enviados,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN 1 END) AS videos_concluidos,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'falhou' THEN 1 END) AS videos_falhos,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN horas END), 0) AS horas_concluidas,
  COALESCE(SUM(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' THEN segundos_de_processamento END), 0) AS segundos_de_processamento,
  COUNT(CASE WHEN tipo = 'fim_de_processamento' AND estado = 'concluido' AND segundos_de_processamento IS NOT NULL THEN 1 END) AS videos_concluidos_com_tempo,
  COUNT(CASE WHEN tipo = 'busca' THEN 1 END) AS buscas,
  COUNT(CASE WHEN tipo = 'busca' AND n_resultados = 0 THEN 1 END) AS buscas_sem_resultado,
  COUNT(CASE WHEN tipo = 'correcao' THEN 1 END) AS correcoes
FROM eventos
WHERE programa IS NOT NULL
GROUP BY dia, programa;

-- Um dia, uma pessoa, um programa, um tipo de correção (#284). `programa` e `tipo_de_correcao`
-- vazios são o evento que não os trouxe; a tela os agrupa como "sem programa" e "sem tipo".
-- Aqui, ao contrário de `uso_por_dia_e_programa`, o evento sem programa fica: a correção por
-- pessoa e por tipo precisa somar todas.
CREATE OR REPLACE TABLE `${prefixo}correcoes_por_dia` AS
SELECT
  dia, quem_tipo, quem_id, programa, tipo_de_correcao,
  COUNT(*) AS correcoes
FROM eventos
WHERE tipo = 'correcao'
GROUP BY dia, quem_tipo, quem_id, programa, tipo_de_correcao;

-- Um dia, um sistema (ou pessoa), um método e uma rota (#284). Erro do cliente é o status 4xx
-- e erro do servidor, o 5xx; a rota traz `{job_id}` em vez do valor.
CREATE OR REPLACE TABLE `${prefixo}chamadas_de_api_por_dia` AS
SELECT
  dia, quem_tipo, quem_id, metodo, rota,
  COUNT(*) AS chamadas,
  COUNT(CASE WHEN status >= 400 AND status < 500 THEN 1 END) AS erros_do_cliente,
  COUNT(CASE WHEN status >= 500 THEN 1 END) AS erros_do_servidor
FROM eventos
WHERE tipo = 'chamada_de_api'
GROUP BY dia, quem_tipo, quem_id, metodo, rota;
