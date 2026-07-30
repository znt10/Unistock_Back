"""Digest diario de estoque baixo: 1 email por loja + combinado pro gerente."""

from django.contrib.auth.models import Group, User
from django.core import mail
from rest_framework.test import APITestCase

from app.models import Categoria, Estoque, Loja, Produto
from app.notifications.tasks import enviar_digest_lojas


class DigestPorLojaTests(APITestCase):
    def setUp(self):
        cat_salgados = Categoria.objects.get_or_create(nome='Salgados grande')[0]
        cat_mercado = Categoria.objects.get_or_create(nome='Mercado')[0]
        self.coxinha = Produto.objects.create(
            nome_produto='Coxinha', categoria=cat_salgados,
        )
        self.coca = Produto.objects.create(nome_produto='Coca', categoria=cat_mercado)

    def _loja(self, nome, email=None):
        return Loja.objects.create(
            nome_loja=nome, cidade='Patos', endereco='Rua 1', email=email,
        )

    def _baixo(self, loja, produto=None):
        return Estoque.objects.create(
            loja=loja, produto=produto or self.coxinha,
            quantidade_atual=1, quantidade_minima=5,
        )

    def _gerente(self, email='ger@email.com'):
        grupo, _ = Group.objects.get_or_create(name='Gerente')
        gerente = User.objects.create_user(
            username=email, email=email, password='123',
        )
        gerente.groups.add(grupo)
        return gerente

    def test_cada_loja_recebe_seu_pdf_no_email_da_loja(self):
        lapa = self._loja('Lapa', email='lapa@unistock.com')
        centro = self._loja('Centro', email='centro@unistock.com')
        self._baixo(lapa)
        self._baixo(centro)

        enviar_digest_lojas()

        destinatarios = {msg.to[0] for msg in mail.outbox}
        self.assertEqual(
            destinatarios, {'lapa@unistock.com', 'centro@unistock.com'}
        )
        for msg in mail.outbox:
            self.assertEqual(len(msg.attachments), 1)
            nome, _conteudo, mime = msg.attachments[0]
            self.assertEqual(mime, 'application/pdf')
            self.assertTrue(nome.endswith('.pdf'))

    def test_loja_sem_email_nao_recebe(self):
        sem_email = self._loja('Sem Email')
        self._baixo(sem_email)

        enviar_digest_lojas()

        self.assertEqual(len(mail.outbox), 0)

    def test_gerente_recebe_um_pdf_com_todas_as_lojas(self):
        gerente = self._gerente()
        lapa = self._loja('Lapa', email='lapa@unistock.com')
        centro = self._loja('Centro', email='centro@unistock.com')
        self._baixo(lapa)
        self._baixo(centro)

        enviar_digest_lojas()

        do_gerente = [msg for msg in mail.outbox if msg.to == [gerente.email]]
        self.assertEqual(len(do_gerente), 1)
        self.assertEqual(len(do_gerente[0].attachments), 1)
        _nome, conteudo, mime = do_gerente[0].attachments[0]
        self.assertEqual(mime, 'application/pdf')
        self.assertTrue(conteudo.startswith(b'%PDF'))

    def test_gerente_com_email_desativado_nao_recebe(self):
        """O toggle de email do usuario vale para o combinado do gerente."""
        from app.models import PreferenciaNotificacao

        gerente = self._gerente()
        PreferenciaNotificacao.objects.create(usuario=gerente, email_ativo=False)
        lapa = self._loja('Lapa', email='lapa@unistock.com')
        self._baixo(lapa)

        enviar_digest_lojas()

        # A loja continua recebendo; so o gerente ficou de fora.
        destinatarios = {msg.to[0] for msg in mail.outbox}
        self.assertEqual(destinatarios, {'lapa@unistock.com'})

    def test_sem_estoque_baixo_nao_envia_nada(self):
        loja = self._loja('Lapa', email='lapa@unistock.com')
        self._gerente()
        Estoque.objects.create(
            loja=loja, produto=self.coxinha,
            quantidade_atual=100, quantidade_minima=5,
        )

        enviar_digest_lojas()

        self.assertEqual(len(mail.outbox), 0)

    def test_loja_inativa_nao_recebe(self):
        loja = self._loja('Fechada', email='fechada@unistock.com')
        loja.ativo = False
        loja.save()
        self._baixo(loja)

        enviar_digest_lojas()

        self.assertEqual(len(mail.outbox), 0)
