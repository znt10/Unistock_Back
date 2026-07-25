"""Conversao dos responsaveis pessoais para o login da loja.

Fica fora do arquivo de migracao para poder ser testada. Recebe os models por
parametro para funcionar tanto com os models reais quanto com os historicos que
a migracao entrega via apps.get_model.
"""


def converter_responsaveis(User, Loja):
    """Troca o login do responsavel de cada loja para o email da loja.

    E o MESMO usuario: pedidos e movimentacoes antigos continuam apontando para
    ele. Devolve (quantos_convertidos, lista_de_pulados_com_motivo).
    """
    convertidos = 0
    pulados = []

    for loja in Loja.objects.exclude(responsavel=None).select_related("responsavel"):
        if not loja.email:
            pulados.append((loja.nome_loja, "loja sem email cadastrado"))
            continue

        acesso = loja.responsavel
        if acesso.username == loja.email:
            continue  # ja convertida

        if User.objects.filter(username=loja.email).exclude(pk=acesso.pk).exists():
            pulados.append((loja.nome_loja, f"email {loja.email} ja em uso"))
            continue

        acesso.username = loja.email
        acesso.email = loja.email
        acesso.save(update_fields=["username", "email"])
        convertidos += 1

    return convertidos, pulados
