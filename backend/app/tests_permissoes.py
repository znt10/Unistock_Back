"""Trava o comportamento atual das regras de permissao duplicadas.

Hoje a pergunta "essa pessoa e gerente ou admin?" esta escrita em TRES lugares
e "qual o papel dela?" em DOIS:

    app/permissions.py               IsGerenteOrAdministrador
    app/api/v1/viewsets.py:109       is_gerente_ou_admin
    app/notifications/__init__.py:7  _is_gerente_ou_admin

    app/views.py:28                  get_user_group_name
    app/api/v1/viewsets.py:117       get_user_group_name

Estes testes nao dizem o que a regra DEVERIA ser: eles registram o que cada
copia responde HOJE, incluindo onde elas divergem de proposito e onde divergem
por acidente. Sao rede de seguranca para a unificacao.

Se um destes ficar vermelho durante o refactor, o refactor mudou regra de
acesso. Nesse caso a pergunta certa nao e "conserta o teste", e sim "essa
mudanca de acesso era intencional?".
"""

from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import RequestFactory, TestCase

from app.api.v1.viewsets import get_user_group_name as papel_do_viewsets
from app.api.v1.viewsets import is_gerente_ou_admin
from app.models import Estoque, Loja, Produto
from app.notifications import _is_gerente_ou_admin
from app.permissions import (
    IsGerenteOrAdministrador,
    IsGerenteOrAdministradorOrResponsavel,
)
from app.views import get_user_group_name as papel_das_views


def criar_grupos():
    for nome in ("Admin", "Gerente", "Responsavel"):
        Group.objects.get_or_create(name=nome)


def usuario(username, grupo=None):
    user = User.objects.create_user(username=username, password="123456")
    if grupo:
        user.groups.add(Group.objects.get(name=grupo))
    return user


def requisicao(metodo, user):
    request = getattr(RequestFactory(), metodo)("/")
    request.user = user
    return request


class RegraGerenteOuAdminTests(TestCase):
    """As tres copias respondem a mesma pergunta. Devem concordar sempre."""

    def setUp(self):
        criar_grupos()
        self.superuser = User.objects.create_superuser(
            "root@email.com", password="123456"
        )
        self.admin = usuario("admin@email.com", "Admin")
        self.gerente = usuario("ger@email.com", "Gerente")
        self.responsavel = usuario("resp@email.com", "Responsavel")
        self.sem_grupo = usuario("nada@email.com")

    def implementacoes(self, user):
        """As tres copias, cada uma na sua interface, para o mesmo usuario."""
        return {
            "viewsets.is_gerente_ou_admin": is_gerente_ou_admin(user),
            "notifications._is_gerente_ou_admin": _is_gerente_ou_admin(user),
            "permissions.IsGerenteOrAdministrador": (
                IsGerenteOrAdministrador().has_permission(
                    requisicao("get", user), None
                )
            ),
        }

    def test_as_tres_copias_concordam(self):
        casos = [
            (self.superuser, True),
            (self.admin, True),
            (self.gerente, True),
            (self.responsavel, False),
            (self.sem_grupo, False),
            (AnonymousUser(), False),
        ]

        for user, esperado in casos:
            with self.subTest(usuario=str(user)):
                for nome, resultado in self.implementacoes(user).items():
                    self.assertEqual(
                        bool(resultado),
                        esperado,
                        f"{nome} divergiu para {user}",
                    )

    def test_superuser_sem_grupo_nenhum_ja_conta(self):
        """is_superuser sozinho basta: nao precisa estar no grupo Admin."""
        self.assertFalse(self.superuser.groups.exists())
        for nome, resultado in self.implementacoes(self.superuser).items():
            with self.subTest(implementacao=nome):
                self.assertTrue(resultado)

    def test_gerente_inativo_ainda_conta_como_gerente(self):
        """Nenhuma das tres olha is_active.

        Registrado porque e surpreendente: desativar um gerente NAO tira o
        acesso dele por esta regra (o login e que barra). Se a unificacao
        passar a checar is_active, este teste fica vermelho — e ai a mudanca
        precisa ser decidida, nao herdada sem querer.
        """
        inativo = usuario("inativo@email.com", "Gerente")
        inativo.is_active = False
        inativo.save(update_fields=["is_active"])

        for nome, resultado in self.implementacoes(inativo).items():
            with self.subTest(implementacao=nome):
                self.assertTrue(resultado)

    def test_divergencia_conhecida_usuario_none(self):
        """A copia de notifications aceita None; a de viewsets estoura.

        Nao e alcancavel pela API (request.user nunca e None), mas o digest
        chama a versao de notifications fora de qualquer request. Se a
        unificacao adotar a versao SEM guarda, o digest quebra em producao e
        os testes de API nao pegam.
        """
        self.assertFalse(_is_gerente_ou_admin(None))

        with self.assertRaises(AttributeError):
            is_gerente_ou_admin(None)


class PermissaoResponsavelTests(TestCase):
    """IsGerenteOrAdministradorOrResponsavel NAO e a mesma regra.

    Esta classe parece uma quarta copia, mas nao e: ela libera leitura para
    qualquer autenticado e escrita para responsavel. Achatar tudo em
    is_gerente_ou_admin FECHA acesso legitimo; trocar por ela ABRE acesso.
    Os dois erros sao faceis de cometer durante a unificacao.
    """

    def setUp(self):
        criar_grupos()
        self.classe = IsGerenteOrAdministradorOrResponsavel()

        self.gerente = usuario("ger@email.com", "Gerente")
        self.responsavel = usuario("resp@email.com", "Responsavel")
        self.outro = usuario("outro@email.com", "Responsavel")
        self.sem_grupo = usuario("nada@email.com")

        self.loja_dele = Loja.objects.create(
            nome_loja="Loja Centro",
            cidade="Patos",
            endereco="Rua A, 1",
            responsavel=self.responsavel,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja Sul",
            cidade="Patos",
            endereco="Rua B, 2",
            responsavel=self.outro,
        )

        produto = Produto.objects.create(
            nome_produto="Coxinha",
            unidade_medida=Produto.UnidadeMedida.CAIXA,
            categoria=Produto.Categoria.SALGADOS_GDE,
        )
        self.estoque_dele = Estoque.objects.create(
            loja=self.loja_dele, produto=produto,
            quantidade_atual=5, quantidade_minima=2,
        )
        self.estoque_alheio = Estoque.objects.create(
            loja=self.loja_alheia, produto=produto,
            quantidade_atual=5, quantidade_minima=2,
        )

    # --- has_permission: quem entra na rota ---

    def test_leitura_liberada_para_qualquer_autenticado(self):
        """Usuario sem grupo nenhum LE. is_gerente_ou_admin diria False."""
        self.assertTrue(
            self.classe.has_permission(requisicao("get", self.sem_grupo), None)
        )
        self.assertFalse(is_gerente_ou_admin(self.sem_grupo))

    def test_escrita_liberada_para_responsavel(self):
        """A diferenca central: responsavel escreve, e nao e gerente."""
        self.assertTrue(
            self.classe.has_permission(requisicao("post", self.responsavel), None)
        )
        self.assertFalse(is_gerente_ou_admin(self.responsavel))

    def test_escrita_negada_para_autenticado_sem_grupo(self):
        self.assertFalse(
            self.classe.has_permission(requisicao("post", self.sem_grupo), None)
        )

    def test_anonimo_negado_ate_para_leitura(self):
        self.assertFalse(
            self.classe.has_permission(requisicao("get", AnonymousUser()), None)
        )

    # --- has_object_permission: o isolamento por loja ---

    def test_responsavel_escreve_no_estoque_da_propria_loja(self):
        self.assertTrue(
            self.classe.has_object_permission(
                requisicao("patch", self.responsavel), None, self.estoque_dele
            )
        )

    def test_responsavel_nao_escreve_no_estoque_de_outra_loja(self):
        """O teste que importa: e a linha que separa uma loja da outra."""
        self.assertFalse(
            self.classe.has_object_permission(
                requisicao("patch", self.responsavel), None, self.estoque_alheio
            )
        )

    def test_responsavel_passa_na_leitura_de_objeto_de_outra_loja(self):
        """SAFE_METHODS retorna True antes de olhar a loja.

        O isolamento na leitura vem do get_queryset, nao daqui. Registrado
        porque parece um furo lido isolado, e nao e — mas se a unificacao
        mover a guarda de loja para o queryset OU para ca sem olhar a outra
        ponta, vira furo de verdade.
        """
        self.assertTrue(
            self.classe.has_object_permission(
                requisicao("get", self.responsavel), None, self.estoque_alheio
            )
        )

    def test_gerente_escreve_em_qualquer_loja(self):
        self.assertTrue(
            self.classe.has_object_permission(
                requisicao("patch", self.gerente), None, self.estoque_alheio
            )
        )

    def test_objeto_sem_campo_loja_cai_no_dono(self):
        """A propria Loja nao tem atributo `loja`: o ramo usado e
        obj.responsavel == user."""
        self.assertTrue(
            self.classe.has_object_permission(
                requisicao("patch", self.responsavel), None, self.loja_dele
            )
        )
        self.assertFalse(
            self.classe.has_object_permission(
                requisicao("patch", self.responsavel), None, self.loja_alheia
            )
        )


class PapelDoUsuarioTests(TestCase):
    """get_user_group_name existe identico em views.py e viewsets.py."""

    def setUp(self):
        criar_grupos()
        self.superuser = User.objects.create_superuser(
            "root@email.com", password="123456"
        )
        self.admin = usuario("admin@email.com", "Admin")
        self.gerente = usuario("ger@email.com", "Gerente")
        self.responsavel = usuario("resp@email.com", "Responsavel")
        self.sem_grupo = usuario("nada@email.com")

        self.multi = usuario("multi@email.com", "Gerente")
        self.multi.groups.add(Group.objects.get(name="Responsavel"))

    def test_as_duas_copias_concordam(self):
        usuarios = [
            self.superuser, self.admin, self.gerente,
            self.responsavel, self.sem_grupo, self.multi,
        ]
        for user in usuarios:
            with self.subTest(usuario=str(user)):
                self.assertEqual(papel_das_views(user), papel_do_viewsets(user))

    def test_superuser_sem_grupo_e_admin(self):
        self.assertEqual(papel_do_viewsets(self.superuser), "Admin")

    def test_admin_ganha_de_qualquer_outro_grupo(self):
        self.admin.groups.add(Group.objects.get(name="Responsavel"))
        self.assertEqual(papel_do_viewsets(self.admin), "Admin")

    def test_sem_grupo_devolve_none(self):
        self.assertIsNone(papel_do_viewsets(self.sem_grupo))

    def test_usuario_em_dois_grupos_depende_da_ordem_do_banco(self):
        """groups.first() sem order_by: qual grupo volta e indefinido.

        Nao afirmamos QUAL — so que e um dos dois e que as duas copias
        respondem igual. Se a unificacao definir prioridade explicita
        (Admin > Gerente > Responsavel), este teste continua verde e vira o
        lugar certo para apertar a regra.
        """
        papel = papel_do_viewsets(self.multi)
        self.assertIn(papel, {"Gerente", "Responsavel"})
        self.assertEqual(papel, papel_das_views(self.multi))
