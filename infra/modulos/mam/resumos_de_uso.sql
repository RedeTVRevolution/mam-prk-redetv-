-- Tabelas resumidas do painel da diretoria (#280, E9). Roda de tempos em tempos como
-- consulta agendada (`resumos_de_uso.tf`) e mantém as seis tabelas a partir dos eventos de
-- uso (#279). `${prefixo}` é o prefixo `projeto.dataset.` das tabelas que ele cria,
-- `${tabela_de_eventos}` é o nome inteiro da que ele lê, e `${inicio_da_janela}` é o começo
-- (uma expressão TIMESTAMP, sempre à meia-noite de São Paulo) do período que pode ter
-- mudado: o `main.tf` e o `eventos_de_uso.tf` montam esses nomes e o `resumos_de_uso.tf` a
-- janela (os testes rodam este arquivo no SQLite, sem prefixo: por isso só há SQL comum aos
-- dois, salvo a data com fuso e o CREATE TABLE ... AS).
--
-- Incremental (#380): a consulta lê só as partições da janela (`quando` é a coluna da
-- partição) e troca os dias da janela nas quatro tabelas por dia; o que veio antes fica como
-- está. `uso_por_dia` e `uso_por_usuario` saem da tabela por dia e usuário, que é pequena.
-- Nenhuma leitura toca os momentos: a duração do vídeo vem no evento de fim.
--
-- Eventos repetidos (o mesmo `id`) valem uma vez. O Job reprocessado que chega de novo ao
-- mesmo estado final também conta uma vez só (vale o primeiro, guardado em
-- `fins_de_processamento_contados`, que dispensa ler os fins antigos); o que falhou e depois
-- concluiu conta uma falha e uma conclusão. O dia é o de São Paulo. As horas são as dos
-- vídeos concluídos, pela duração que o evento de fim traz (`duracao_do_video_ms`); o fim
-- gravado antes de o evento trazê-la conta 0 hora. O tempo de processamento médio divide
-- `segundos_de_processamento` por `videos_concluidos_com_tempo`: o fim gravado antes de o
-- evento trazer o tempo não entra em nenhum dos dois.
CREATE TEMP TABLE janela AS
SELECT
  id, quando, tipo, quem_tipo, quem_id, programa, estado, job_id,
  segundos_de_processamento, n_resultados, tipo_de_correcao, metodo, rota, status,
  duracao_do_video_ms,
  DATE(quando, 'America/Sao_Paulo') AS dia
FROM (
  SELECT
    u.*,
    ROW_NUMBER() OVER (PARTITION BY id ORDER BY quando) AS ordem
  FROM `${tabela_de_eventos}` AS u
  WHERE u.quando >= ${inicio_da_janela}
)
WHERE ordem = 1;

-- O primeiro dia que esta rodada refaz, calculado uma vez só e depois da leitura: no
-- BigQuery cada comando do script avalia `CURRENT_DATE` de novo, e a rodada que atravessa a
-- meia-noite apagaria menos dias do que leu e somaria o dia de antes em dobro.
CREATE TEMP TABLE inicio AS SELECT DATE(${inicio_da_janela}, 'America/Sao_Paulo') AS dia;

-- Cada (Job, estado final) com o `id` do fim que vale.
CREATE TABLE IF NOT EXISTS `${prefixo}fins_de_processamento_contados` AS
SELECT id, job_id, estado FROM janela WHERE FALSE;

INSERT INTO `${prefixo}fins_de_processamento_contados` (id, job_id, estado)
SELECT id, job_id, estado
FROM (
  SELECT
    id, job_id, estado,
    ROW_NUMBER() OVER (PARTITION BY job_id, estado ORDER BY quando) AS vez
  FROM janela
  WHERE tipo = 'fim_de_processamento'
) AS j
WHERE j.vez = 1
  AND NOT EXISTS (
    SELECT 1 FROM `${prefixo}fins_de_processamento_contados` AS c
    WHERE c.job_id = j.job_id AND c.estado = j.estado
  );

CREATE TEMP TABLE eventos AS
SELECT
  dia, quando, tipo, quem_tipo, quem_id, programa, estado,
  segundos_de_processamento, n_resultados, tipo_de_correcao, metodo, rota, status,
  COALESCE(duracao_do_video_ms, 0) / 3600000.0 AS horas
FROM janela
WHERE dia >= (SELECT dia FROM inicio)
  AND (
    tipo <> 'fim_de_processamento'
    OR id IN (SELECT id FROM `${prefixo}fins_de_processamento_contados`)
  );

-- Um dia, um usuário (ou sistema). As duas tabelas seguintes somam esta. `ativo` diz se
-- quem é da linha agiu no dia: o fim de processamento é atribuído a quem enviou o vídeo e,
-- sozinho (o vídeo que termina no dia seguinte), não faz ninguém ativo.
CREATE TEMP TABLE novas_uso_por_dia_e_usuario AS
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

-- Um dia, um programa. O login e a chamada de API não têm programa; o evento sem programa
-- fica de fora. A busca só tem programa quando foi filtrada por ele: `buscas` conta as buscas
-- feitas dentro do programa, não as que acharam algo dele.
CREATE TEMP TABLE novas_uso_por_dia_e_programa AS
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
CREATE TEMP TABLE novas_correcoes_por_dia AS
SELECT
  dia, quem_tipo, quem_id, programa, tipo_de_correcao,
  COUNT(*) AS correcoes
FROM eventos
WHERE tipo = 'correcao'
GROUP BY dia, quem_tipo, quem_id, programa, tipo_de_correcao;

-- Um dia, um sistema (ou pessoa), um método e uma rota (#284). Erro do cliente é o status 4xx
-- e erro do servidor, o 5xx; a rota traz `{job_id}` em vez do valor.
CREATE TEMP TABLE novas_chamadas_de_api_por_dia AS
SELECT
  dia, quem_tipo, quem_id, metodo, rota,
  COUNT(*) AS chamadas,
  COUNT(CASE WHEN status >= 400 AND status < 500 THEN 1 END) AS erros_do_cliente,
  COUNT(CASE WHEN status >= 500 THEN 1 END) AS erros_do_servidor
FROM eventos
WHERE tipo = 'chamada_de_api'
GROUP BY dia, quem_tipo, quem_id, metodo, rota;

CREATE TABLE IF NOT EXISTS `${prefixo}uso_por_dia_e_usuario` AS SELECT * FROM novas_uso_por_dia_e_usuario WHERE FALSE;
CREATE TABLE IF NOT EXISTS `${prefixo}uso_por_dia_e_programa` AS SELECT * FROM novas_uso_por_dia_e_programa WHERE FALSE;
CREATE TABLE IF NOT EXISTS `${prefixo}correcoes_por_dia` AS SELECT * FROM novas_correcoes_por_dia WHERE FALSE;
CREATE TABLE IF NOT EXISTS `${prefixo}chamadas_de_api_por_dia` AS SELECT * FROM novas_chamadas_de_api_por_dia WHERE FALSE;

-- Troca os dias da janela de uma vez, para o painel não ler as tabelas pela metade.
BEGIN TRANSACTION;
DELETE FROM `${prefixo}uso_por_dia_e_usuario` WHERE dia >= (SELECT dia FROM inicio);
INSERT INTO `${prefixo}uso_por_dia_e_usuario` SELECT * FROM novas_uso_por_dia_e_usuario;
DELETE FROM `${prefixo}uso_por_dia_e_programa` WHERE dia >= (SELECT dia FROM inicio);
INSERT INTO `${prefixo}uso_por_dia_e_programa` SELECT * FROM novas_uso_por_dia_e_programa;
DELETE FROM `${prefixo}correcoes_por_dia` WHERE dia >= (SELECT dia FROM inicio);
INSERT INTO `${prefixo}correcoes_por_dia` SELECT * FROM novas_correcoes_por_dia;
DELETE FROM `${prefixo}chamadas_de_api_por_dia` WHERE dia >= (SELECT dia FROM inicio);
INSERT INTO `${prefixo}chamadas_de_api_por_dia` SELECT * FROM novas_chamadas_de_api_por_dia;
COMMIT TRANSACTION;

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

