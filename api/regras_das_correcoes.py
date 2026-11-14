"""As operações das Correções: corrigir, desfazer, reaplicar, descartar, decidir, aplicar,
reconciliar, estado, fila, histórico e a Decupagem com Correções (#611).

Os modelos, os repositórios, os tipos e a ordenação ficam em `api/correcoes.py`, que não importa
este módulo (sem ciclo).
"""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from api.canonicos import com_os_canonicos
from api.catalogo import Catalogo, PessoaDoCatalogo, nomes_de_busca
from api.comparador import normalizar
from api.correcoes import (
    CORRIGIVEIS,
    PREFIXO_ACRESCENTADO,
    TIPOS,
    TOLERANCIA_DO_PLANO_MS,
    Autoria,
    Candidato,
    CatalogoIdInvalido,
    Correcao,
    CorrecaoInexistente,
    EstadoDasCorrecoes,
    EstadoNaBusca,
    ItemDaFila,
    ItemDoHistorico,
    ItemInexistente,
    NaoCandidato,
    NaoDesfazivel,
    NaoNaFila,
    NaoPendente,
    NovaCorrecao,
    Ocorrencia,
    Reconciliacao,
    TemposInvalidos,
    TipoDoItem,
    VersaoDesatualizada,
    _acha_ocorrencia,
    _ancora_do_item,
    _ids_das_pessoas,
    _intervalo_da_pauta,
    _intervalo_da_pessoa,
    _intervalo_do_item,
    _intervalo_do_objeto,
    _itens_com_o_id,
    _objetos,
    _pautas,
    _pessoas,
    _por_inicio,
    _sobrepoe,
    _sobrepoe_de_verdade,
    _sobrepoe_metade,
    _valor_do_item,
    em_ordem,
    identidade_da_pessoa,
    identidade_do_comercial,
)
from api.decupagem import (
    PREFIXO_POSICIONAL,
    id_posicional,
)
from api.identidade import identidade_do_nome, nao_identificado
from api.marcas import CatalogoDeMarcas, MarcaDoCatalogo, nomes_de_busca_da_marca
from api.pessoas import LISTAS
from api.tipo_do_objeto import tipo_canonico_de


def _com_ids_posicionais(modelo: dict[str, Any], chave: str) -> list[dict[str, Any]]:
    """Os itens de `chave` (cópias) com o id da posição no JSON do modelo.

    O que já traz id (decupagem entregue) o mantém.
    """
    return [
        {"id": id_posicional(chave, n), **item}
        for n, item in enumerate(modelo.get(chave, []))
        if isinstance(item, dict)
    ]


def _comerciais(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return _com_ids_posicionais(modelo, "comerciais")


def _textos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return _com_ids_posicionais(modelo, "textos_na_tela")


def _tipo_do_item(tipo: str, escolhido: str | None = None) -> TipoDoItem:
    """O tipo do item que a correção do `tipo` corrige; no `item.tempos`, o que o
    pedido escolhe (pauta, se nada)."""
    return cast(TipoDoItem, TIPOS[tipo].tipo_do_item or escolhido or "pauta")


def _planos(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in modelo.get("planos", []) if isinstance(p, dict)]


def _falas(modelo: dict[str, Any]) -> list[dict[str, Any]]:
    return _com_ids_posicionais(modelo, "transcricao")


def _itens(modelo: dict[str, Any], tipo_do_item: str) -> list[dict[str, Any]]:
    if tipo_do_item == "pessoa":
        return _pessoas(modelo)
    if tipo_do_item == "comercial":
        return _comerciais(modelo)
    if tipo_do_item == "plano":
        return _planos(modelo)
    if tipo_do_item == "fala":
        return _falas(modelo)
    if tipo_do_item == "texto_na_tela":
        return _textos(modelo)
    if tipo_do_item == "objeto":
        return _objetos(modelo)
    return _pautas(modelo)


def _rotulo_do_item(item: dict[str, Any], tipo_do_item: str) -> str:
    if tipo_do_item == "comercial":
        return f"{item['marca']} ({item['tipo']})"
    if tipo_do_item == "plano":
        return str(item["ambiente"])
    if tipo_do_item == "fala":
        return f"{item['locutor']}: {str(item['texto'])[:60]}"
    if tipo_do_item == "texto_na_tela":
        return f"{item['tipo']}: {str(item['texto'])[:60]}"
    if tipo_do_item == "objeto":
        return str(item["tipo"])
    return str(item["nome" if tipo_do_item == "pessoa" else "titulo"])


def _valor_da_ocorrencia(
    pessoa: dict[str, Any], tipo: str, ocorrencia: Ocorrencia | None, depois: str
) -> str:
    """Onde está hoje a ocorrência: "<lista> <inicio>-<fim>", ou só os tempos no
    `item.tempos`; vazio se a pessoa não a tem."""
    leitor = TIPOS[tipo].valor_da_ocorrencia
    assert leitor is not None
    return leitor(pessoa, ocorrencia, depois)


def _confere_duracao(modelo: dict[str, Any], tipo: str, valor: str) -> None:
    """`TemposInvalidos` se os tempos de um `item.tempos` ou de um item
    acrescentado passam da duração."""
    fim_de = TIPOS[tipo].fim_ms
    if fim_de is None:
        return
    if fim_de(valor) > int(modelo.get("video", {}).get("duracao_ms", 0)):
        raise TemposInvalidos(valor)


def _registro(job_id: str, autoria: Autoria, id: str, **campos: Any) -> Correcao:
    return Correcao(
        id=id,
        job_id=job_id,
        autor_uid=autoria.uid,
        autor_email=autoria.email,
        criada_em=autoria.em,
        **campos,
    )


def _alvo(correcoes: list[Correcao], id: str) -> Correcao:
    alvo = next((c for c in correcoes if c.id == id), None)
    if alvo is None:
        raise CorrecaoInexistente(id)
    return alvo


def corrigir(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    novo: NovaCorrecao,
    job_id: str,
    autoria: Autoria,
    *,
    exige_aprovacao: bool = False,
    catalogo: Catalogo | None = None,
    marcas: CatalogoDeMarcas | None = None,
) -> Correcao:
    """O registro da correção de `novo` sobre o item do JSON do modelo, com a
    âncora pronta. A ocorrência de uma pessoa tem de existir na decupagem
    entregue, que já traz as `correcoes` gravadas (aplicada aqui uma só vez).
    """
    if novo.versao != versao:
        raise VersaoDesatualizada(novo.versao)
    entregue = aplicar(modelo, versao, correcoes)
    tipo_do_item = _tipo_do_item(novo.tipo, novo.tipo_do_item)
    antes = _valor_atual(
        entregue,
        novo.tipo,
        novo.item_id,
        novo.tipo_do_item,
        novo.ocorrencia,
        novo.valor,
    )
    _confere_duracao(modelo, novo.tipo, novo.valor)
    confere = TIPOS[novo.tipo].confere
    if confere is not None:
        confere(entregue, novo.valor)
    id = uuid.uuid4().hex
    campos: dict[str, Any] = {
        "tipo": novo.tipo,
        "motivo": novo.motivo,
        "depois": novo.valor,
        "exige_aprovacao": exige_aprovacao,
    }
    estrutura = TIPOS[novo.tipo].reestrutura
    if estrutura is not None:
        campos["depois"], ancora_nova = estrutura.preparar(entregue, novo, versao)
        return _registro(
            job_id,
            autoria,
            id,
            item_id=novo.item_id,
            antes=antes,
            ancora=ancora_nova,
            **campos,
        )
    acrescenta = TIPOS[novo.tipo].acrescenta
    if acrescenta is not None:
        ancora = acrescenta.ancora(novo.valor, novo.item_id, versao)
        if ancora is not None:
            return _registro(
                job_id,
                autoria,
                id,
                item_id=f"{PREFIXO_ACRESCENTADO}{id}",
                antes="",
                ancora=ancora,
                **campos,
            )
    item = next(
        (i for i in _itens(modelo, tipo_do_item) if i.get("id") == novo.item_id), None
    )
    if item is None:
        raise ItemInexistente(novo.item_id)
    if novo.ocorrencia is not None:
        pessoa = next(
            (p for p in _pessoas(entregue) if p.get("id") == novo.item_id), None
        )
        o = novo.ocorrencia
        if pessoa is None or not _acha_ocorrencia(
            pessoa, o.inicio_ms, o.fim_ms, (o.lista,)
        ):
            raise ItemInexistente(f"{novo.item_id} {o.lista}")
    return _registro(
        job_id,
        autoria,
        id,
        item_id=novo.item_id,
        antes=antes,
        ocorrencia=novo.ocorrencia,
        catalogo_id=_id_no_catalogo(novo, catalogo, marcas),
        ancora=_ancora_do_item(item, tipo_do_item, versao),
        **campos,
    )


def _id_no_catalogo(
    novo: NovaCorrecao, catalogo: Catalogo | None, marcas: CatalogoDeMarcas | None
) -> str | None:
    """O id do catálogo que a correção grava. Se a revisora escolheu um (`catalogo_id`),
    ele tem de existir e o nome novo ser o nome ou um apelido dele. Sem escolha, só a
    pessoa tem busca pelo nome: o id da única pessoa com esse nome; vazio sem catálogo,
    sem ninguém com esse nome ou com mais de uma (a revisora não escolhe aqui)."""
    entrada = TIPOS[novo.tipo]
    if novo.catalogo_id is not None:
        achado = (
            (catalogo.obter(novo.catalogo_id) if catalogo else None)
            if entrada.catalogo_de == "pessoas"
            else (marcas.obter(novo.catalogo_id) if marcas else None)
        )
        if (
            achado is None
            or achado.lixeira is not None
            or (isinstance(achado, PessoaDoCatalogo) and achado.fundida is not None)
            or normalizar(novo.valor) not in _nomes_de_busca(achado)
        ):
            raise CatalogoIdInvalido(novo.catalogo_id)
        return achado.id
    if catalogo is None or not entrada.acha_no_catalogo:
        return None
    achadas = catalogo.achar(novo.valor)
    return achadas[0].id if len(achadas) == 1 else None


def _nomes_de_busca(entrada: PessoaDoCatalogo | MarcaDoCatalogo) -> list[str]:
    if isinstance(entrada, PessoaDoCatalogo):
        return nomes_de_busca(entrada)
    return nomes_de_busca_da_marca(entrada)


def estado_das(correcoes: list[Correcao]) -> EstadoDasCorrecoes:
    return EstadoDasCorrecoes(
        desfeitas=frozenset(
            c.desfaz for c in correcoes if c.tipo == "desfazer" and c.desfaz
        ),
        reaplicadas=frozenset(c.reaplica for c in correcoes if c.reaplica),
        descartadas=frozenset(c.descarta for c in correcoes if c.descarta),
        aprovadas=frozenset(c.aprova for c in correcoes if c.aprova),
        recusadas=frozenset(c.recusa for c in correcoes if c.recusa),
        exigem_aprovacao=frozenset(c.id for c in correcoes if c.exige_aprovacao),
    )


def _em_ordem_de_vigencia(
    alvos: list[Correcao], correcoes: list[Correcao]
) -> list[Correcao]:
    """Como `em_ordem`, mas a aprovada entra na data da aprovação: uma correção
    feita enquanto ela esperava o Curador não a encobre depois de aprovada."""
    aprovada_em = {c.aprova: c.criada_em for c in correcoes if c.aprova}
    return sorted(alvos, key=lambda c: (aprovada_em.get(c.id, c.criada_em), c.id))


def id_do_desfazer(alvo_id: str) -> str:
    """Fixo por alvo: dois desfazer simultâneos colidem no repositório."""
    return f"{alvo_id}-desfeita"


def _valor_do_alvo(
    modelo: dict[str, Any], entregue: dict[str, Any], alvo: Correcao
) -> str:
    """O valor entregue hoje no item do alvo (casa como `aplicar`): a pessoa
    pela identidade da âncora; a pauta pelo id, que na mesma versão é estável."""
    do_alvo = TIPOS[alvo.tipo].valor_do_alvo
    if do_alvo is not None:
        return do_alvo(modelo, entregue, alvo)
    return _valor_ou_vazio(entregue, alvo)


def _valor_ou_vazio(entregue: dict[str, Any], c: Correcao) -> str:
    """O valor entregue no item de `c`, ou vazio se o item saiu da decupagem
    (o objeto que não existe): desfazer uma correção dele não muda o que se vê."""
    try:
        return _valor_atual(
            entregue, c.tipo, c.item_id, c.ancora.tipo_do_item, c.ocorrencia, c.depois
        )
    except ItemInexistente:
        return ""


def desfazer(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    alvo_id: str,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """O registro que reverte o alvo; nada é apagado. Um desfazer não se desfaz.

    Antes e depois são o nome entregue sem e com o desfazer: com uma correção
    mais nova no mesmo campo, desfazer a antiga não muda o que se vê. A de outra
    versão só se desfaz se `reconciliar` a casar; o registro aponta o item novo.
    A decupagem é aplicada com o alvo e sem ele: duas, e só.
    """
    alvo = _alvo(correcoes, alvo_id)
    if alvo.tipo not in CORRIGIVEIS or not estado_das(correcoes).casavel(alvo.id):
        raise NaoDesfazivel(alvo.id)
    restantes = [c for c in correcoes if c.id != alvo.id]
    com = aplicar(modelo, versao, correcoes)
    sem = aplicar(modelo, versao, restantes)
    if alvo.ancora.versao == versao:
        alvo_atual = alvo
        # 422 só se o alvo falta nas duas decupagens. Se falta só na entregue com o
        # desfazer, a própria troca o absorveu: o "antes" é o nome que ela deu.
        depois = _valor_do_alvo(modelo, sem, alvo)
        try:
            antes = _valor_do_alvo(modelo, com, alvo)
        except ItemInexistente:
            antes = alvo.depois
    else:
        casadas = reconciliar(modelo, versao, correcoes).casadas
        reapontada = next((c for c in casadas if c.id == alvo.id), None)
        if reapontada is None:
            raise NaoDesfazivel(alvo.id)
        alvo_atual = reapontada
        # A reapontada vale pelo id do item novo, como em `aplicar`.
        antes, depois = (
            _valor_ou_vazio(entregue, alvo_atual) for entregue in (com, sem)
        )
    return _registro(
        job_id,
        autoria,
        id_do_desfazer(alvo.id),
        tipo="desfazer",
        desfaz=alvo.id,
        item_id=alvo_atual.item_id,
        ocorrencia=alvo_atual.ocorrencia,
        motivo=motivo,
        antes=antes,
        depois=depois,
        ancora=alvo_atual.ancora,
    )


def historico(correcoes: list[Correcao]) -> list[ItemDoHistorico]:
    """Da mais recente para a mais antiga, cada uma ativa, desfeita, fora da
    fila (reaplicada ou descartada) ou, se exige aprovação, pendente, aprovada
    ou recusada."""
    estado = estado_das(correcoes)
    tipos = {c.id: c.tipo for c in correcoes}

    def legivel(c: Correcao, valor: str) -> str:
        # Desfazer, descarte, aprovação e recusa mostram o valor do tipo que decidem.
        alvo = c.desfaz or c.descarta or c.aprova or c.recusa
        return valor_legivel(tipos.get(alvo) if alvo else c.tipo, valor)

    return [
        ItemDoHistorico(
            **c.model_dump(),
            estado=estado.de(c.id),
            antes_legivel=legivel(c, c.antes),
            depois_legivel=legivel(c, c.depois),
        )
        for c in reversed(em_ordem(correcoes))
    ]


def com_o_estado_na_busca(
    itens: list[ItemDoHistorico],
    estado: str | None,
    ate: datetime | None,
) -> list[ItemDoHistorico]:
    """Marca em cada correção que vale hoje (ativa ou aprovada) onde ela está no índice.

    `estado` e `ate` vêm da indexação do Job: `ate` é o instante a partir do qual a
    última rodada leu as correções. Com a indexação rodando, a correção está
    "indexando"; indexado, está "na busca" se foi gravada até `ate`; sem indexação ou
    com falha, só "salva".
    """
    aprovada_em = {i.aprova: i.criada_em for i in itens if i.aprova}
    marcados: list[ItemDoHistorico] = []
    for item in itens:
        situacao: EstadoNaBusca = "salva"
        if item.estado in ("ativa", "aprovada"):
            vale_desde = aprovada_em.get(item.id, item.criada_em)
            if estado == "pendente":
                situacao = "indexando"
            elif estado == "indexado" and ate is not None and vale_desde <= ate:
                situacao = "na_busca"
        marcados.append(item.model_copy(update={"na_busca": situacao}))
    return marcados


def _valor_atual(
    entregue: dict[str, Any],
    tipo: str,
    item_id: str,
    tipo_do_item: str | None = None,
    ocorrencia: Ocorrencia | None = None,
    depois: str = "",
) -> str:
    """O valor que o Editor vê hoje, na decupagem `entregue`, no campo do `tipo`
    do item `item_id`.

    Vazio para o item acrescentado que não está na decupagem (ainda não existe,
    foi desfeito ou o modelo já o traz) e para a ocorrência de pessoa que a
    decupagem não tem (ou cuja pessoa saiu dela). `depois` é o valor da
    correção, de onde sai o intervalo da aparição acrescentada.
    """
    entrada = TIPOS[tipo]
    tipo_do_item = _tipo_do_item(tipo, tipo_do_item)
    if entrada.traz_o_campo is not None and not entrada.traz_o_campo(entregue):
        raise ItemInexistente(tipo)
    de_ocorrencia = tipo_do_item == "pessoa" and entrada.valor_da_ocorrencia is not None
    for item in _itens(entregue, tipo_do_item):
        if item.get("id") != item_id:
            continue
        if de_ocorrencia:
            return _valor_da_ocorrencia(item, tipo, ocorrencia, depois)
        return _valor_do_item(item, tipo)
    if entrada.acrescenta is not None or de_ocorrencia:
        return ""
    raise ItemInexistente(item_id)


def _candidatos(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    """Itens da versão nova que a correção pode estar apontando.

    Pauta: a que sobrepõe o intervalo ancorado em pelo menos metade do menor
    dos dois. Comercial: o de mesma marca normalizada e tipo, com intervalo
    sobreposto (ou já com o "depois"). Pessoa: a com a identidade da âncora
    (ou já com o "depois"). Plano: o de início e fim a até 1 s dos ancorados.
    Fala: a que sobrepõe o intervalo ancorado (encostar na borda não conta).
    """
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    if c.ancora.tipo_do_item == "pauta":
        return [
            p
            for p in _pautas(modelo)
            if _sobrepoe_metade(ancora, _intervalo_da_pauta(p))
        ]
    if c.ancora.tipo_do_item == "plano":
        return [
            p
            for p in _planos(modelo)
            if abs(p["inicio_ms"] - ancora[0]) <= TOLERANCIA_DO_PLANO_MS
            and abs(p["fim_ms"] - ancora[1]) <= TOLERANCIA_DO_PLANO_MS
        ]
    if c.ancora.tipo_do_item == "fala":
        return [
            f
            for f in _falas(modelo)
            if _sobrepoe_de_verdade(ancora, _intervalo_da_pauta(f))
        ]
    if c.ancora.tipo_do_item == "texto_na_tela":
        identidades = TIPOS[c.tipo].identidades(c)
        return [
            t
            for t in _textos(modelo)
            if normalizar(str(t["texto"])) in identidades
            and _sobrepoe_de_verdade(ancora, _intervalo_da_pauta(t))
        ]
    if c.ancora.tipo_do_item == "objeto":
        identidades = TIPOS[c.tipo].identidades(c)
        return [
            o
            for o in _objetos(modelo)
            if normalizar(str(o["tipo"])) in identidades
            and _sobrepoe_de_verdade(ancora, _intervalo_do_objeto(o))
        ]
    if c.ancora.tipo_do_item == "comercial":
        identidades = TIPOS[c.tipo].identidades(c)
        return [
            m
            for m in _comerciais(modelo)
            if identidade_do_comercial(m) in identidades
            and _sobrepoe(ancora, _intervalo_da_pauta(m))
        ]
    return _candidatos_pessoa(modelo, c)


def _candidatos_pessoa(modelo: dict[str, Any], c: Correcao) -> list[dict[str, Any]]:
    entrada = TIPOS[c.tipo]
    ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
    sem_nome = nao_identificado(c.ancora.identidade.split("@")[0])
    achados = []
    for pessoa in _pessoas(modelo):
        nome = str(pessoa["nome"])
        if sem_nome and nao_identificado(nome):
            # Só as aparições mostram quem é.
            intervalo = _intervalo_da_pessoa(pessoa, ("na_imagem",))
        elif (
            entrada.casa_pelo_nome_novo and normalizar(nome) == normalizar(c.depois)
        ) or (not sem_nome and normalizar(nome) == c.ancora.identidade):
            intervalo = _intervalo_da_pessoa(pessoa)
        else:
            continue
        # A aparição acrescentada pode estar longe do que a pessoa já tem.
        longe_ok = entrada.casa_longe and not sem_nome
        if longe_ok or (_sobrepoe(ancora, intervalo) and _tem_a_ocorrencia(c, pessoa)):
            achados.append(pessoa)
    return achados


def _tem_a_ocorrencia(c: Correcao, pessoa: dict[str, Any]) -> bool:
    """A pessoa ainda tem a aparição ou menção que a correção aponta."""
    o = c.ocorrencia
    if o is None:
        return True
    return _acha_ocorrencia(pessoa, o.inicio_ms, o.fim_ms, (o.lista,)) is not None


def reconciliar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> Reconciliacao:
    """Casa as correções de versões antigas com a decupagem atual do modelo.

    Casa só com exatamente um item de mesma identidade e intervalo sobreposto;
    zero ou vários candidatos não casam. Ignora as da versão atual, as
    desfeitas, as que saíram da fila, as que esperam aprovação ou foram
    recusadas e os registros que não corrigem um item.
    """
    estado = estado_das(correcoes)
    resultado = Reconciliacao(casadas=[], atendidas=[], sem_casar=[])
    for c in em_ordem(correcoes):
        if (
            c.ancora.versao == versao
            or c.tipo not in CORRIGIVEIS
            or not estado.casavel(c.id)
        ):
            continue
        estrutura = TIPOS[c.tipo].reestrutura
        if estrutura is not None:
            # Juntar e dividir se casam com o conjunto de pautas, não com um item só.
            achada = estrutura.reapontar(modelo, c, versao)
            if achada is None:
                resultado.sem_casar.append(c)
                continue
            resultado.casadas.append(achada[0])
            if achada[1]:
                resultado.atendidas.append(achada[0])
            continue
        candidatos = _candidatos(modelo, c)
        acrescenta = TIPOS[c.tipo].acrescenta
        if acrescenta is not None and acrescenta.acrescenta(c):
            # Não corrige item nenhum: não vai para a fila. Se o modelo já traz
            # o comercial (a aparição, o texto), a correção é atendida e não duplica.
            candidatos = acrescenta.atendentes(c, candidatos)
            nova = c.model_copy(
                update={"ancora": c.ancora.model_copy(update={"versao": versao})}
            )
            resultado.casadas.append(nova)
            if candidatos:
                resultado.atendidas.append(nova)
            continue
        if len(candidatos) != 1:
            resultado.sem_casar.append(c)
            continue
        item = candidatos[0]
        nova = c.model_copy(
            update={
                "item_id": str(item.get("id", "")),
                "ancora": _ancora_do_item(item, c.ancora.tipo_do_item, versao),
            }
        )
        resultado.casadas.append(nova)
        if TIPOS[c.tipo].ja_traz(c, item):
            resultado.atendidas.append(nova)
    return resultado


def _aplicar_no_item(resultado: dict[str, Any], c: Correcao) -> None:
    """Pauta, comercial, plano ou fala é achado pelo id: na versão atual o id
    do item é estável, e a reapontada já traz o id novo."""
    aplica = TIPOS[c.tipo].aplicar_no_item
    assert aplica is not None
    confere = TIPOS[c.tipo].confere
    if confere is not None:
        try:
            confere(resultado, c.depois)
        except ItemInexistente:
            return  # o que a correção aponta já não existe nesta versão
    for item in _itens_com_o_id(resultado, c):
        aplica(item, c)
        item["origem"] = "revisao"


def pares_proibidos(correcoes: Sequence[Correcao]) -> set[frozenset[str]]:
    """Os pares de pessoas de origem que uma pessoa separou na tela e seguem em vigor:
    a junção automática do reprocessamento não os une de novo (#547)."""
    estado = estado_das(list(correcoes))
    pares: set[frozenset[str]] = set()
    for c in correcoes:
        if c.tipo == "pessoa.separar" and estado.em_vigor(c.id):
            pares |= {
                frozenset({c.depois, outra})
                for outra in json.loads(c.antes)
                if outra != c.depois
            }
    return pares


def pessoas_corrigidas(correcoes: Sequence[Correcao]) -> set[str]:
    """As identidades (`chave_da_pessoa`) das pessoas com alguma Correção em vigor: a
    junção automática do reprocessamento as deixa fora (#547)."""
    estado = estado_das(list(correcoes))
    return {
        c.ancora.identidade
        for c in correcoes
        if c.ancora.tipo_do_item == "pessoa"
        and c.tipo not in ("desfazer", "descartar", "aprovar", "recusar")
        and estado.casavel(c.id)
    }


def _com_a_ocorrencia(
    pessoas: list[dict[str, Any]], pessoa: dict[str, Any], c: Correcao
) -> dict[str, Any]:
    """A pessoa que a correção casou, ou, se a ocorrência que ela aponta veio de
    uma pessoa que a junção por nome vai absorver, a que tem a ocorrência e o
    mesmo nome de agora."""
    if _tem_a_ocorrencia(c, pessoa):
        return pessoa
    chave = identidade_do_nome(str(pessoa["nome"]))
    if chave is None:
        return pessoa
    return next(
        (
            p
            for p in pessoas
            if identidade_do_nome(str(p["nome"])) == chave and _tem_a_ocorrencia(c, p)
        ),
        pessoa,
    )


def _do_mesmo_nome(
    pessoas: list[dict[str, Any]], pessoa: dict[str, Any], c: Correcao
) -> list[dict[str, Any]]:
    """As outras pessoas com o nome (normalizado) que `pessoa` tinha antes da
    correção `c`, se ela vale para a pessoa inteira (sem ocorrência e sem
    acrescentar nada): a junção por nome as entrega como uma só."""
    if c.ocorrencia is not None or TIPOS[c.tipo].acrescenta is not None:
        return []
    chave = identidade_do_nome(str(pessoa["nome"]))
    if chave is None:
        return []
    return [
        p
        for p in pessoas
        if p is not pessoa and identidade_do_nome(str(p["nome"])) == chave
    ]


def _sem_separadas(
    membros: list[dict[str, Any]],
    separadas: set[frozenset[Any]],
    renomeadas: dict[int, int],
) -> list[list[dict[str, Any]]]:
    """Parte os do mesmo nome em grupos sem nenhum par que uma pessoa separou (#547).
    Renomear os dois à mão para o mesmo nome é juntá-los de propósito (#352)."""

    def separado(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return frozenset({a.get("id"), b.get("id")}) in separadas and not (
            id(a) in renomeadas and id(b) in renomeadas
        )

    grupos: list[list[dict[str, Any]]] = []
    for m in membros:
        alvo = next((g for g in grupos if not any(separado(m, x) for x in g)), None)
        if alvo is None:
            grupos.append([m])
        else:
            alvo.append(m)
    return grupos


def _juntar_as_do_mesmo_nome(
    resultado: dict[str, Any], renomeadas: dict[int, int]
) -> None:
    """Pessoas com o mesmo nome (normalizado) viram uma: a primeira da lista
    absorve as outras. "Não identificado" nunca junta. Roda no fim de `aplicar`,
    para cada correção casar pela identidade do modelo, antes de qualquer troca."""
    grupos: dict[str, list[dict[str, Any]]] = {}
    for p in _pessoas(resultado):
        chave = identidade_do_nome(str(p["nome"]))
        if chave is not None:
            grupos.setdefault(chave, []).append(p)
    para: dict[Any, Any] = {}
    absorvidas: list[dict[str, Any]] = []
    separadas = {frozenset(par) for par in resultado.get("_separadas", [])}
    for membros in (
        s for g in grupos.values() for s in _sem_separadas(g, separadas, renomeadas)
    ):
        if len(membros) < 2:
            continue
        base, *outras = membros
        trocadas = [m for m in membros if id(m) in renomeadas]
        for outra in outras:
            for lista in LISTAS:
                base[lista] = [*base.get(lista, []), *outra.get(lista, [])]
                _por_inicio(base[lista])
            base["fontes_do_nome"] = list(
                dict.fromkeys(
                    [*base.get("fontes_do_nome", []), *outra.get("fontes_do_nome", [])]
                )
            )
            if outra.get("origem") == "revisao":
                base["origem"] = "revisao"
            para[outra.get("id")] = base.get("id")
            absorvidas.append(outra)
        if trocadas:
            nova = max(trocadas, key=lambda m: renomeadas[id(m)])
            base["origem"] = "revisao"
            for campo in ("estado_do_nome", "catalogo_id"):
                if campo in nova:
                    base[campo] = nova[campo]
                else:
                    base.pop(campo, None)
    if not absorvidas:
        return
    resultado["pessoas"] = [
        p for p in _pessoas(resultado) if not any(p is a for a in absorvidas)
    ]
    for pauta in _pautas(resultado):
        if "pessoas" in pauta:
            pauta["pessoas"] = list(
                dict.fromkeys(para.get(i, i) for i in pauta["pessoas"])
            )
    for objeto in _objetos(resultado):
        if objeto.get("pessoa") in para:
            objeto["pessoa"] = para[objeto["pessoa"]]


def aplicar(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """Cópia do modelo com as correções da versão atual por cima.

    Item corrigido (pessoa, pauta, comercial, plano ou fala) vem com
    `origem: "revisao"`; os demais, com
    `"modelo"`.
    A atendida (o modelo já traz o "depois") deixa o nome como o modelo o
    escreveu, com `origem: "modelo"`.
    Correção desfeita não conta: o item volta ao valor que teria sem ela.
    A que exige aprovação só conta depois de aprovada.
    Correção de outra versão do JSON só vale se `reconciliar` a casar com um
    item único; as que não casam não se aplicam (e seguem no histórico).
    """
    resultado: dict[str, Any] = json.loads(json.dumps(modelo))
    pessoas = _pessoas(resultado)
    # Os ids posicionais saem da posição no modelo, antes de qualquer correção.
    posicionais = []
    for chave in PREFIXO_POSICIONAL:
        for n, real in enumerate(resultado.get(chave, [])):
            if isinstance(real, dict):
                real["id"] = id_posicional(chave, n)
                posicionais.append(real)
    for item in [*pessoas, *_pautas(resultado), *_planos(resultado), *posicionais]:
        # O nome confirmado pelo código (`modelo_forte`) segue como o modelo gravou.
        if item.get("origem") != "modelo_forte":
            item["origem"] = "modelo"
    # Casa pela identidade do modelo, calculada antes de qualquer renomeação.
    identidades = [identidade_da_pessoa(p) for p in pessoas]
    identidade_no_modelo = {id(p): i for p, i in zip(pessoas, identidades, strict=True)}
    pessoas_do_modelo = [dict(p) for p in pessoas]
    estado = estado_das(correcoes)
    # ponytail: reconciliar a cada leitura relê as pessoas do modelo por
    # correção antiga (custo pequeno hoje); guardar o resultado quando houver
    # reprocessamentos frequentes ou muitas correções por vídeo.
    reconciliadas = reconciliar(modelo, versao, correcoes)
    esvaziadas: list[dict[str, Any]] = []
    # Quem recebeu troca de nome, e em que ordem: a junção fica com a mais nova.
    renomeadas: dict[int, int] = {}
    atendidas = {c.id for c in reconciliadas.atendidas}
    reapontadas = {c.id for c in reconciliadas.casadas}
    da_versao = [
        c for c in correcoes if c.ancora.versao == versao and c.tipo in CORRIGIVEIS
    ]

    def casa(c: Correcao, pessoa: dict[str, Any], identidade: str) -> bool:
        # A reapontada vai só ao item que casou, pelo id novo.
        if c.id in reapontadas:
            return pessoa.get("id") == c.item_id
        return identidade == c.ancora.identidade

    # Em ordem de data: a mais nova vence, e desfazer uma antiga não a derruba.
    # A aprovada vale a partir da aprovação, não de quando o Editor a fez.
    for c in _em_ordem_de_vigencia(da_versao + reconciliadas.casadas, correcoes):
        if not estado.em_vigor(c.id):
            continue
        entrada = TIPOS[c.tipo]
        if entrada.reestrutura is not None:
            if c.id not in atendidas:
                entrada.reestrutura.aplicar(resultado, c)
            continue
        if entrada.acrescenta is not None and entrada.acrescenta.acrescenta(c):
            if c.id not in atendidas:
                entrada.acrescenta.aplicar(resultado, c)
            continue
        if c.ancora.tipo_do_item != "pessoa":
            if c.id not in atendidas:
                _aplicar_no_item(resultado, c)
            elif entrada.atender_no_item is not None:
                for item in _itens_com_o_id(resultado, c):
                    entrada.atender_no_item(item, c)
            continue
        aplicadas: set[int] = set()
        for pessoa, identidade, do_modelo in zip(
            pessoas, identidades, pessoas_do_modelo, strict=True
        ):
            if not casa(c, pessoa, identidade):
                continue
            pessoa = _com_a_ocorrencia(pessoas, pessoa, c)
            if id(pessoa) in aplicadas:
                continue
            assert entrada.aplicar_na_pessoa is not None
            # A correção da pessoa inteira vale também para as que a junção vai
            # absorver nela (pelo nome de antes dela): quem corrige vê uma só.
            juntas = [
                j
                for j in _do_mesmo_nome(pessoas, pessoa, c)
                if not casa(c, j, identidade_no_modelo[id(j)])
            ]
            if c.id in atendidas:
                if entrada.atender_na_pessoa is not None:
                    entrada.atender_na_pessoa(pessoa, do_modelo, c)
            else:
                entrada.aplicar_na_pessoa(resultado, pessoa, c)
            aplicadas.add(id(pessoa))
            for junta in juntas:
                if id(junta) not in aplicadas:
                    entrada.aplicar_na_pessoa(resultado, junta, c)
                    aplicadas.add(id(junta))
        for pessoa in pessoas:
            if id(pessoa) not in aplicadas or c.id in atendidas:
                continue
            if c.tipo == "pessoa.renomear":
                renomeadas[id(pessoa)] = len(renomeadas) + 1
            if entrada.pode_esvaziar:
                esvaziadas.append(pessoa)
    _juntar_as_do_mesmo_nome(resultado, renomeadas)
    resultado.pop("_separadas", None)
    # A pessoa que ficou sem nenhuma ocorrência some da decupagem, e das pautas.
    sumidas = [e for e in esvaziadas if not any(e[lista] for lista in LISTAS)]
    if sumidas:
        resultado["pessoas"] = [
            p for p in _pessoas(resultado) if not any(p is e for e in sumidas)
        ]
        ids = {e.get("id") for e in sumidas}
        for pauta in _pautas(resultado):
            if "pessoas" in pauta:
                pauta["pessoas"] = [i for i in pauta["pessoas"] if i not in ids]
    # O objeto cuja pessoa não está mais na decupagem fica em cena: sem dono, sem relação.
    ids_das_pessoas = _ids_das_pessoas(resultado)
    for objeto in _objetos(resultado):
        if objeto.get("pessoa") is not None and objeto["pessoa"] not in ids_das_pessoas:
            objeto["pessoa"] = objeto["relacao"] = None
    if "objetos" in resultado:
        resultado["objetos"] = [
            o for o in _objetos(resultado) if not o.pop("_removido", False)
        ]
    # As pautas do modelo ficam na ordem em que vieram; só a acrescentada
    # pede reordenar, para entrar no lugar do seu início.
    if any(p.get("acrescentado") for p in _pautas(resultado)):
        resultado["pautas"].sort(key=lambda p: (p["inicio_ms"], p["fim_ms"]))
    if "textos_na_tela" in resultado:
        resultado["textos_na_tela"].sort(key=lambda t: (t["inicio_ms"], t["fim_ms"]))
    if "comerciais" in resultado:
        resultado["comerciais"].sort(key=lambda m: (m["inicio_ms"], m["fim_ms"]))
    return resultado


def id_da_resolucao(alvo_id: str) -> str:
    """Fixo por alvo: reaplicar e descartar simultâneos colidem no repositório."""
    return f"{alvo_id}-resolvida"


def fila(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> list[ItemDaFila]:
    """As correções que não casaram, da mais antiga para a mais nova, cada uma
    com as pessoas da versão atual que sobrepõem o intervalo ancorado."""
    itens = []
    for c in reconciliar(modelo, versao, correcoes).sem_casar:
        ancora = (c.ancora.inicio_ms, c.ancora.fim_ms)
        tipo_do_item = c.ancora.tipo_do_item
        candidatos = []
        # Juntar e dividir não se reaplicam num item só: ficam na fila para descartar.
        for item in [] if TIPOS[c.tipo].reestrutura else _itens(modelo, tipo_do_item):
            intervalo = _intervalo_do_item(item, tipo_do_item)
            # Plano e fala que só encostam no ancorado não são o mesmo trecho.
            sobrepoe = (
                _sobrepoe_de_verdade
                if tipo_do_item in ("plano", "fala", "texto_na_tela")
                else _sobrepoe
            )
            # Reaplicar numa pessoa sem a aparição ou menção não mudaria nada.
            if sobrepoe(ancora, intervalo) and _tem_a_ocorrencia(c, item):
                candidatos.append(
                    Candidato(
                        item_id=str(item.get("id", "")),
                        nome=_rotulo_do_item(item, tipo_do_item),
                        inicio_ms=intervalo[0],
                        fim_ms=intervalo[1],
                    )
                )
        itens.append(
            ItemDaFila(
                **c.model_dump(),
                candidatos=candidatos,
                antes_legivel=valor_legivel(c.tipo, c.antes),
                depois_legivel=valor_legivel(c.tipo, c.depois),
            )
        )
    return itens


def _na_fila(
    modelo: dict[str, Any], versao: str, alvo: Correcao, correcoes: list[Correcao]
) -> ItemDaFila:
    item = next((i for i in fila(modelo, versao, correcoes) if i.id == alvo.id), None)
    if item is None:
        raise NaoNaFila(alvo.id)
    return item


def reaplicar(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    alvo_id: str,
    item_id: str,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """A correção nova, ancorada na versão atual no item escolhido e ligada à
    original (`reaplica`). A original sai da fila e continua no histórico.
    O item tem de ser um dos candidatos que a fila oferece."""
    alvo = _alvo(correcoes, alvo_id)
    item = _na_fila(modelo, versao, alvo, correcoes)
    if item_id not in {c.item_id for c in item.candidatos}:
        raise NaoCandidato(item_id)
    tipo_do_item = alvo.ancora.tipo_do_item
    novo = next(i for i in _itens(modelo, tipo_do_item) if i.get("id") == item_id)
    # O vídeo reprocessado pode ser mais curto que o da correção original.
    _confere_duracao(modelo, alvo.tipo, alvo.depois)
    return _registro(
        job_id,
        autoria,
        id_da_resolucao(alvo.id),
        tipo=alvo.tipo,
        reaplica=alvo.id,
        item_id=item_id,
        motivo=motivo,
        ocorrencia=alvo.ocorrencia,
        # Sem revalidar: a original foi validada e a leitura trata o que mudou depois.
        catalogo_id=alvo.catalogo_id,
        antes=_valor_atual(
            aplicar(modelo, versao, correcoes),
            alvo.tipo,
            item_id,
            tipo_do_item,
            alvo.ocorrencia,
            alvo.depois,
        ),
        depois=alvo.depois,
        ancora=_ancora_do_item(novo, tipo_do_item, versao),
    )


def descartar(
    modelo: dict[str, Any],
    versao: str,
    correcoes: list[Correcao],
    alvo_id: str,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """O registro que tira o alvo da fila; ela não se aplica mais."""
    alvo = _alvo(correcoes, alvo_id)
    _na_fila(modelo, versao, alvo, correcoes)
    return _registro(
        job_id,
        autoria,
        id_da_resolucao(alvo.id),
        tipo="descartar",
        descarta=alvo.id,
        item_id=alvo.item_id,
        ocorrencia=alvo.ocorrencia,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
    )


def id_da_decisao(alvo_id: str) -> str:
    """Fixo por alvo: aprovar e recusar simultâneos colidem no repositório."""
    return f"{alvo_id}-decidida"


def decidir(
    correcoes: list[Correcao],
    alvo_id: str,
    aprovada: bool,
    motivo: str,
    job_id: str,
    autoria: Autoria,
) -> Correcao:
    """O registro em que um Curador aprova ou recusa o alvo, que tem de estar
    pendente. A recusa traz o motivo."""
    alvo = _alvo(correcoes, alvo_id)
    if not alvo.exige_aprovacao or alvo.id in estado_das(correcoes).decididas:
        raise NaoPendente(alvo.id)
    return _registro(
        job_id,
        autoria,
        id_da_decisao(alvo.id),
        tipo="aprovar" if aprovada else "recusar",
        aprova=alvo.id if aprovada else None,
        recusa=None if aprovada else alvo.id,
        item_id=alvo.item_id,
        ocorrencia=alvo.ocorrencia,
        motivo=motivo,
        antes=alvo.antes,
        depois=alvo.depois,
        ancora=alvo.ancora,
    )


def decupagem_com_correcoes(
    modelo: dict[str, Any], versao: str, correcoes: list[Correcao]
) -> dict[str, Any]:
    """O modelo com as Correções em vigor aplicadas e a versão do JSON do modelo em que
    elas se apoiam. A leitura de quem consome é `LeituraDaDecupagem`, que a chama."""
    entregue = aplicar(modelo, versao, correcoes)
    entregue["versao_decupagem"] = versao
    _com_tipo_canonico(modelo, entregue)
    com_os_canonicos(modelo, entregue)
    return entregue


def _cores_do_objeto(o: dict[str, Any]) -> list[str]:
    return [*(o.get("cor_base") or []), *([o["cor"]] if o.get("cor") else [])]


def _com_tipo_canonico(modelo: dict[str, Any], entregue: dict[str, Any]) -> None:
    """O tipo canônico (#544), derivado depois das Correções: o do modelo vale se o texto
    bruto não mudou; o objeto corrigido ou acrescentado, o antigo sem tipo e o fora da lista
    passam pelo dicionário de nome livre para tipo, e o que não está nele fica em `outro`."""
    brutos = {
        o.get("id"): (o.get("tipo"), o.get("tipo_canonico")) for o in _objetos(modelo)
    }
    for o in _objetos(entregue):
        tipo, canonico = brutos.get(o.get("id"), (None, None))
        gravado = canonico if tipo == o.get("tipo") else None
        o["tipo_canonico"] = tipo_canonico_de(
            gravado, str(o.get("tipo", "")), _cores_do_objeto(o)
        )
    for plano in _planos(entregue):
        for item in plano.get("inventario") or []:
            if isinstance(item, dict):
                item["tipo_canonico"] = tipo_canonico_de(
                    item.get("tipo_canonico"),
                    str(item.get("nome", "")),
                    [item["cor"]] if item.get("cor") else [],
                )


def valor_legivel(tipo: str | None, valor: str) -> str:
    """O valor de uma Correção para quem lê, pela entrada do tipo; o que não
    for o formato esperado sai como veio, sem derrubar o histórico nem a fila."""
    entrada = TIPOS.get(tipo or "")
    if entrada is None:
        return valor
    try:
        return entrada.legivel(valor)
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        # O valor gravado pode ter qualquer forma (registro antigo, JSON de
        # outro tipo): `[]` dá AttributeError, aninhamento fundo, RecursionError.
        return valor
