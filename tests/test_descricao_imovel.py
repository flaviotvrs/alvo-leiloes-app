"""Testa o parser de descrição estruturada da planilha Caixa."""

from app.parsers.descricao_imovel import parsear_descricao


def test_exemplo_real_completo():
    d = parsear_descricao(
        "Apartamento, 78.72 de área total, 44.45 de área privativa, 0.00 de "
        "área do terreno, 2 qto(s), WC, 1 sala(s), cozinha, 1 vaga(s) de garagem."
    )
    assert d.tipo == "Apartamento"
    assert d.area_total_m2 == 78.72
    assert d.area_privativa_m2 == 44.45
    assert d.area_terreno_m2 is None  # 0.00 vira null, não zero
    assert d.quartos == 2
    assert d.salas == 1
    assert d.vagas_garagem == 1
    assert d.possui_wc is True
    assert d.possui_cozinha is True
    assert d.parsing_incompleto is False


def test_casa_sem_vaga_de_garagem():
    d = parsear_descricao(
        "Casa, 37.21 de área total, 37.21 de área privativa, 74.97 de área "
        "do terreno,  2 qto(s), WC, 1 sala(s), cozinha."
    )
    assert d.tipo == "Casa"
    assert d.area_terreno_m2 == 74.97
    assert d.vagas_garagem is None
    assert d.parsing_incompleto is False


def test_terreno_sem_area_construida():
    d = parsear_descricao(
        "Terreno, 0.00 de área total, 0.00 de área privativa, 237.00 de "
        "área do terreno."
    )
    assert d.tipo == "Terreno"
    assert d.area_total_m2 is None
    assert d.area_privativa_m2 is None
    assert d.area_terreno_m2 == 237.00
    assert d.quartos is None
    assert d.possui_wc is False
    assert d.possui_cozinha is False
    assert d.parsing_incompleto is False


def test_sem_quarto_sala_cozinha_so_vaga():
    d = parsear_descricao(
        "Apartamento, 0.00 de área total, 117.08 de área privativa, 0.00 de "
        "área do terreno, 1 vaga(s) de garagem."
    )
    assert d.quartos is None
    assert d.salas is None
    assert d.possui_wc is False
    assert d.possui_cozinha is False
    assert d.vagas_garagem == 1
    assert d.parsing_incompleto is False


def test_tokens_extras_nao_mapeados_nao_quebram_parse():
    d = parsear_descricao(
        "Apartamento, 298.73 de área total, 261.36 de área privativa, 0.00 "
        "de área do terreno,  3 qto(s), a.serv, WC, 2 sala(s), 1 lavabo(s), "
        "cozinha, Terraco, 3 vaga(s) de garagem."
    )
    assert d.quartos == 3
    assert d.salas == 2
    assert d.vagas_garagem == 3
    assert d.possui_wc is True
    assert d.possui_cozinha is True
    assert d.parsing_incompleto is False


def test_tipo_composto_de_duas_palavras():
    d = parsear_descricao(
        "Imóvel rural, 0.00 de área total, 499.63 de área privativa, "
        "42514.00 de área do terreno."
    )
    assert d.tipo == "Imóvel rural"
    assert d.area_terreno_m2 == 42514.00
    assert d.parsing_incompleto is False


def test_descricao_none_ou_vazia_marca_incompleto():
    assert parsear_descricao(None).parsing_incompleto is True
    assert parsear_descricao("").parsing_incompleto is True
    assert parsear_descricao("   ").parsing_incompleto is True


def test_descricao_fora_do_padrao_marca_incompleto():
    d = parsear_descricao(
        "Apartamento 78.72 de area total 44.45 de area privativa"
    )
    assert d.parsing_incompleto is True
    assert d.tipo is None
    assert d.area_total_m2 is None
