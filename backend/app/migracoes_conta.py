"""Adocao das linhas orfas pela camada de Conta.

Fica fora do arquivo de migracao para poder ser testada. Recebe os models por
parametro para funcionar tanto com os models reais quanto com os historicos
que a migracao entrega via apps.get_model.

Roda no meio da cadeia (0026), quando Loja/Categoria/Produto tem os DOIS
campos: o `gerente` antigo e o `conta` novo ainda nulo.
"""

from django.utils.text import slugify

NOME_DA_CONTA_ORFA = "Conta padrao"


def _slug_livre(Conta, base):
    """Mesma regra do Conta._slug_livre, reescrita para o model historico.

    O model que a migracao entrega nao tem os metodos da classe real — so os
    campos. Duplicar a regra aqui e o preco de nao depender do codigo de hoje
    dentro de uma migracao que precisa continuar valida amanha.
    """
    base = (base or "conta")[:55]
    slug, sufixo = base, 2
    while Conta.objects.filter(slug=slug).exists():
        slug = f"{base}-{sufixo}"
        sufixo += 1
    return slug


def _nome_do_gerente(user):
    return user.first_name or user.email or user.username


def adotar_linhas_em_contas(User, Conta, PerfilUsuario, Loja, Categoria, Produto):
    """Cria uma Conta por gerente existente e move as linhas dele para ela.

    Cada gerente vira uma conta separada porque e exatamente isso que o
    sistema era antes: um silo por pessoa. Juntar dois gerentes na mesma
    empresa e decisao de quem administra, feita depois no /admin — a migracao
    nao tem como adivinhar quem trabalha junto.

    Linhas sem gerente (dado antigo, anterior ao campo) vao para uma unica
    "Conta padrao", que so o Admin enxerga ate alguem reatribuir.

    Devolve (contas_criadas, linhas_adotadas).
    """
    contas_por_gerente = {}
    conta_orfa = None
    adotadas = 0

    def conta_do_gerente(gerente_id):
        """A conta deste gerente, criada na primeira vez que ele aparece."""
        nonlocal conta_orfa

        if gerente_id is None:
            if conta_orfa is None:
                conta_orfa = Conta.objects.create(
                    nome=NOME_DA_CONTA_ORFA,
                    slug=_slug_livre(Conta, slugify(NOME_DA_CONTA_ORFA)),
                )
            return conta_orfa

        if gerente_id not in contas_por_gerente:
            gerente = User.objects.get(pk=gerente_id)
            nome = _nome_do_gerente(gerente)
            conta = Conta.objects.create(
                nome=nome, slug=_slug_livre(Conta, slugify(nome))
            )
            # O gerente vira membro da propria conta: sem o perfil ele ficaria
            # dono de linhas que nao consegue mais enxergar.
            PerfilUsuario.objects.get_or_create(user=gerente, defaults={"conta": conta})
            contas_por_gerente[gerente_id] = conta

        return contas_por_gerente[gerente_id]

    for Model in (Loja, Categoria, Produto):
        for linha in Model.objects.filter(conta__isnull=True):
            linha.conta = conta_do_gerente(linha.gerente_id)
            linha.save(update_fields=["conta"])
            adotadas += 1

    # O responsavel de cada loja entra na conta da loja dele. Sem isso ele
    # perde o catalogo no primeiro request depois da migracao: o escopo novo
    # pergunta a conta do usuario, nao mais o gerente da loja.
    for loja in Loja.objects.exclude(responsavel=None).select_related("responsavel"):
        PerfilUsuario.objects.get_or_create(
            user_id=loja.responsavel_id, defaults={"conta_id": loja.conta_id}
        )

    criadas = len(contas_por_gerente) + (1 if conta_orfa else 0)
    return criadas, adotadas
