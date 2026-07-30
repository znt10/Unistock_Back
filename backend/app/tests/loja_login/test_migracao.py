"""A loja como login: migracao dos responsaveis para o email da loja."""

from django.contrib.auth.models import User
from django.test import TestCase

from app.models import Loja


class ConverterResponsaveisTests(TestCase):
    def test_converte_login_para_o_email_da_loja(self):
        from app.migracoes_loja_login import converter_responsaveis

        pessoa = User.objects.create_user(
            username='joao@gmail.com', email='joao@gmail.com', password='123',
        )
        loja = Loja.objects.create(
            nome_loja='Lapa', cidade='Patos', endereco='Rua 1',
            email='lapa@unistock.com', responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(pessoa.username, 'lapa@unistock.com')
        self.assertEqual(pessoa.email, 'lapa@unistock.com')
        self.assertEqual(convertidos, 1)
        self.assertEqual(pulados, [])
        self.assertEqual(loja.responsavel_id, pessoa.id)  # mesmo usuario

    def test_pula_loja_sem_email(self):
        from app.migracoes_loja_login import converter_responsaveis

        pessoa = User.objects.create_user(username='maria@gmail.com', password='123')
        Loja.objects.create(
            nome_loja='Sem Email', cidade='Patos', endereco='Rua 2',
            responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(pessoa.username, 'maria@gmail.com')  # intacto
        self.assertEqual(convertidos, 0)
        self.assertEqual(len(pulados), 1)

    def test_pula_quando_o_email_ja_pertence_a_outro_usuario(self):
        from app.migracoes_loja_login import converter_responsaveis

        User.objects.create_user(username='lapa@unistock.com', password='123')
        pessoa = User.objects.create_user(username='pedro@gmail.com', password='123')
        Loja.objects.create(
            nome_loja='Lapa', cidade='Patos', endereco='Rua 1',
            email='lapa@unistock.com', responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(pessoa.username, 'pedro@gmail.com')  # intacto
        self.assertEqual(convertidos, 0)
        self.assertEqual(len(pulados), 1)

    def test_nao_mexe_em_loja_sem_responsavel(self):
        from app.migracoes_loja_login import converter_responsaveis

        Loja.objects.create(
            nome_loja='Vazia', cidade='Patos', endereco='Rua 3',
            email='vazia@unistock.com',
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        self.assertEqual(convertidos, 0)
        self.assertEqual(pulados, [])

    def test_duas_lojas_com_o_mesmo_email_nao_se_atropelam(self):
        """A 2a loja com o mesmo email nao pode roubar o login que a 1a ganhou.

        O exclude(pk=acesso.pk) so protege contra colidir com OUTRO usuario ja
        existente. Depois que a 1a loja converte, a 2a chega, o unico usuario
        com aquele username e o dela mesma pelo exclude... e ela sobrescreve.
        A migracao nao tem volta (reverter e pass), entao o estrago fica.
        """
        from app.migracoes_loja_login import converter_responsaveis

        um = User.objects.create_user(username='um@gmail.com', password='123')
        dois = User.objects.create_user(username='dois@gmail.com', password='123')
        Loja.objects.create(
            nome_loja='Primeira', cidade='Patos', endereco='Rua 1',
            email='mesma@unistock.com', responsavel=um,
        )
        Loja.objects.create(
            nome_loja='Segunda', cidade='Patos', endereco='Rua 2',
            email='mesma@unistock.com', responsavel=dois,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        um.refresh_from_db()
        dois.refresh_from_db()
        self.assertEqual(convertidos, 1)
        self.assertEqual(len(pulados), 1)
        self.assertEqual(um.username, 'mesma@unistock.com')
        self.assertEqual(dois.username, 'dois@gmail.com')  # intacto

    def test_mesma_pessoa_em_duas_lojas_converte_uma_so(self):
        """Uma pessoa podia ser responsavel por varias lojas (a FK nao e unica).

        Sem controlar quem ja foi convertido, a 2a loja reescreve o username que
        a 1a acabou de definir: a 1a loja fica com um login que nao e o email
        dela, e ninguem percebe porque a migracao nao tem volta.
        """
        from app.migracoes_loja_login import converter_responsaveis

        pessoa = User.objects.create_user(username='ana@gmail.com', password='123')
        Loja.objects.create(
            nome_loja='Loja A', cidade='Patos', endereco='Rua 1',
            email='a@unistock.com', responsavel=pessoa,
        )
        Loja.objects.create(
            nome_loja='Loja B', cidade='Patos', endereco='Rua 2',
            email='b@unistock.com', responsavel=pessoa,
        )

        convertidos, pulados = converter_responsaveis(User, Loja)

        pessoa.refresh_from_db()
        self.assertEqual(convertidos, 1)
        self.assertEqual(pessoa.username, 'a@unistock.com')
        self.assertEqual(len(pulados), 1)  # a segunda precisa de acesso proprio
