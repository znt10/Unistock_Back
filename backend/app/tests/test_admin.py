"""O /admin do Django nao passa pelas views: o escopo tem que valer aqui tambem.

Antes da camada de Conta este arquivo cobria outra coisa — um mixin que
filtrava o seletor de "gerente" da Loja, para nao aparecer usuario que nao
fosse do grupo. Aquele campo deixou de existir. O risco que sobrou e maior e e
o que se testa agora: qualquer is_staff enxergava as empresas todas no /admin.
"""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from app.admin import EstoqueAdmin, LojaAdmin
from app.models import Categoria, Estoque, Loja, Produto
from app.tests.fabricas import criar_conta, criar_gerente


class AdminEscopoPorContaTests(TestCase):
    def setUp(self):
        self.conta = criar_conta("Empresa A")
        self.conta_alheia = criar_conta("Empresa B")

        self.gerente = criar_gerente("ger@x.com", self.conta)
        self.colega = criar_gerente("colega@x.com", self.conta)
        self.superuser = User.objects.create_superuser(
            username="dono@x.com", password="123456"
        )

        self.loja = Loja.objects.create(
            nome_loja="Loja A", cidade="Patos", endereco="Rua 1", conta=self.conta,
        )
        self.loja_alheia = Loja.objects.create(
            nome_loja="Loja B", cidade="Patos", endereco="Rua 2",
            conta=self.conta_alheia,
        )

        self.loja_admin = LojaAdmin(Loja, AdminSite())
        self.estoque_admin = EstoqueAdmin(Estoque, AdminSite())

    def _requisicao(self, user):
        request = RequestFactory().get("/admin/app/loja/")
        request.user = user
        return request

    def test_gerente_ve_so_as_lojas_da_propria_empresa(self):
        lojas = self.loja_admin.get_queryset(self._requisicao(self.gerente))

        self.assertIn(self.loja, lojas)
        self.assertNotIn(self.loja_alheia, lojas)

    def test_colega_da_mesma_empresa_ve_as_mesmas_lojas(self):
        lojas = self.loja_admin.get_queryset(self._requisicao(self.colega))

        self.assertIn(self.loja, lojas)
        self.assertNotIn(self.loja_alheia, lojas)

    def test_superuser_ve_todas_as_empresas(self):
        lojas = self.loja_admin.get_queryset(self._requisicao(self.superuser))

        self.assertIn(self.loja, lojas)
        self.assertIn(self.loja_alheia, lojas)

    def test_usuario_sem_empresa_nao_ve_nada(self):
        """O outro sentido do None em get_conta_do_usuario.

        Sem perfil e sem ser superuser, a resposta certa e lista vazia — nao
        "todas", que seria o efeito de um filtro esquecido.
        """
        orfao = User.objects.create_user(
            username="orfao@x.com", password="123456", is_staff=True
        )

        lojas = self.loja_admin.get_queryset(self._requisicao(orfao))

        self.assertEqual(list(lojas), [])

    def test_escopo_vale_para_model_que_chega_na_conta_pela_loja(self):
        """Estoque nao tem FK de conta: o caminho e loja__conta."""
        categoria = Categoria.objects.create(nome="Bebidas", conta=self.conta)
        produto = Produto.objects.create(
            nome_produto="Coca", categoria=categoria, conta=self.conta,
        )
        categoria_alheia = Categoria.objects.create(
            nome="Bebidas", conta=self.conta_alheia
        )
        produto_alheio = Produto.objects.create(
            nome_produto="Coca", categoria=categoria_alheia, conta=self.conta_alheia,
        )
        meu = Estoque.objects.create(
            loja=self.loja, produto=produto,
            quantidade_atual=5, quantidade_minima=2, quantidade_maxima=999,)
        alheio = Estoque.objects.create(
            loja=self.loja_alheia, produto=produto_alheio,
            quantidade_atual=5, quantidade_minima=2, quantidade_maxima=999,)

        estoques = self.estoque_admin.get_queryset(self._requisicao(self.gerente))

        self.assertIn(meu, estoques)
        self.assertNotIn(alheio, estoques)
