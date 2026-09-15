"""A adocao das linhas orfas pela camada de Conta (migracao 0026).

Testa a REGRA de adocao — quantas contas nascem, quem vira membro de que —
contra os models HISTORICOS, o unico lugar onde `Loja.gerente` ainda existe:
a 0027 apagou o campo dos models reais.

Por isso o executor de migracoes: ele devolve o estado do app na 0025, que e
exatamente o que a 0026 recebe em producao — as duas colunas convivendo, a
nova ainda nula.
"""

from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import TransactionTestCase

from app.migracoes_conta import NOME_DA_CONTA_ORFA, adotar_linhas_em_contas


class AdocaoPorContaTests(TransactionTestCase):
    """TransactionTestCase, nao TestCase: mexer no esquema (migrar pra tras e
    pra frente) nao funciona dentro da transacao que o TestCase mantem
    aberta."""

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.estado = self._voltar_para("0025_conta_nullable_em_loja_categoria_produto")

    def tearDown(self):
        # Deixa o banco no estado final; sem isto os testes seguintes rodariam
        # contra um esquema sem a coluna que eles esperam.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def _voltar_para(self, migracao):
        alvo = [("app", migracao)]
        self.executor.migrate(alvo)
        self.executor.loader.build_graph()
        return self.executor.loader.project_state(alvo).apps

    def _models(self):
        return (
            self.estado.get_model("auth", "User"),
            self.estado.get_model("app", "Conta"),
            self.estado.get_model("app", "PerfilUsuario"),
            self.estado.get_model("app", "Loja"),
            self.estado.get_model("app", "Categoria"),
            self.estado.get_model("app", "Produto"),
        )

    def _adotar(self):
        return adotar_linhas_em_contas(*self._models())

    def _limpar(self):
        """As migracoes antigas semeiam categorias; o assunto aqui e outro."""
        _, Conta, Perfil, Loja, Categoria, Produto = self._models()
        for Model in (Produto, Categoria, Loja, Perfil):
            Model.objects.all().delete()
        Conta.objects.all().delete()

    def _gerente(self, username, nome):
        User, *_ = self._models()
        return User.objects.create(username=username, first_name=nome)

    def _loja_orfa(self, nome, gerente=None, responsavel=None):
        Loja = self._models()[3]
        return Loja.objects.create(
            nome_loja=nome, cidade="Patos", endereco="Rua 1",
            gerente=gerente, responsavel=responsavel,
        )

    def test_cada_gerente_vira_uma_conta_e_adota_as_proprias_lojas(self):
        self._limpar()
        zeca = self._gerente("zeca@x.com", "Zeca")
        maria = self._gerente("maria@x.com", "Maria")
        loja_zeca = self._loja_orfa("Loja do Zeca", gerente=zeca)
        loja_maria = self._loja_orfa("Loja da Maria", gerente=maria)

        criadas, adotadas = self._adotar()

        self.assertEqual((criadas, adotadas), (2, 2))
        loja_zeca.refresh_from_db()
        loja_maria.refresh_from_db()
        self.assertEqual(loja_zeca.conta.nome, "Zeca")
        self.assertEqual(loja_maria.conta.nome, "Maria")
        self.assertNotEqual(loja_zeca.conta_id, loja_maria.conta_id)
        # Cada gerente vira membro da propria conta: sem isso ficaria dono de
        # linhas que nao consegue mais enxergar.
        Perfil = self._models()[2]
        self.assertEqual(
            Perfil.objects.get(user=zeca).conta_id, loja_zeca.conta_id
        )

    def test_duas_lojas_do_mesmo_gerente_caem_na_mesma_conta(self):
        self._limpar()
        zeca = self._gerente("zeca@x.com", "Zeca")
        uma = self._loja_orfa("Uma", gerente=zeca)
        outra = self._loja_orfa("Outra", gerente=zeca)

        criadas, adotadas = self._adotar()

        self.assertEqual((criadas, adotadas), (1, 2))
        uma.refresh_from_db()
        outra.refresh_from_db()
        self.assertEqual(uma.conta_id, outra.conta_id)

    def test_linha_sem_gerente_vai_para_a_conta_padrao(self):
        self._limpar()
        solta = self._loja_orfa("Sem dono")

        criadas, adotadas = self._adotar()

        self.assertEqual((criadas, adotadas), (1, 1))
        solta.refresh_from_db()
        self.assertEqual(solta.conta.nome, NOME_DA_CONTA_ORFA)

    def test_responsavel_da_loja_entra_na_conta_da_loja(self):
        """Sem o vinculo ele perderia o catalogo no primeiro request: o escopo
        novo pergunta a conta do usuario, e antes ele achava o catalogo dando
        a volta por loja.gerente."""
        self._limpar()
        User = self._models()[0]
        acesso = User.objects.create(username="loja@x.com")
        zeca = self._gerente("zeca@x.com", "Zeca")
        loja = self._loja_orfa("Com acesso", gerente=zeca, responsavel=acesso)

        self._adotar()

        loja.refresh_from_db()
        Perfil = self._models()[2]
        self.assertEqual(Perfil.objects.get(user=acesso).conta_id, loja.conta_id)

    def test_e_idempotente(self):
        """Rodar de novo nao cria conta duplicada: nada mais esta orfao."""
        self._limpar()
        zeca = self._gerente("zeca@x.com", "Zeca")
        self._loja_orfa("Loja", gerente=zeca)
        self._adotar()

        self.assertEqual(self._adotar(), (0, 0))
