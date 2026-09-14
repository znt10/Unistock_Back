"""Regras da fabrica — fonte unica.

A fabrica e uma Loja com tipo Fabrica, uma por empresa. Daqui saem as
perguntas "qual e a fabrica desta empresa?" e "este produto segue o fluxo das
caixas?", e as acoes da fabrica (imprimir etiquetas, registrar producao).

Fora das views pelo mesmo motivo de services/pedidos.py: o site, o bot e a
leitura das caixas (parte 3) precisam da mesma resposta.
"""

from rest_framework.exceptions import ValidationError

from app.models import Conta, Loja


def fabrica_da_conta(conta_id):
    """A fabrica ativa desta empresa, ou None."""
    return (
        Loja.objects.filter(
            conta_id=conta_id, tipo=Loja.Tipo.FABRICA, ativo=True, is_deleted=False
        )
        .order_by("id")
        .first()
    )


def segue_fluxo_fabrica(produto):
    """True se pedidos novos deste produto seguem o fluxo das caixas.

    A segunda condicao e o interruptor de implantacao: a migracao ja marca os
    salgados como vem_da_fabrica, e nada muda na operacao ate alguem
    cadastrar a fabrica.
    """
    return bool(produto.vem_da_fabrica) and fabrica_da_conta(produto.conta_id) is not None


def conferir_fabrica_unica(conta_id, tipo, ativo, loja=None):
    """Recusa uma segunda fabrica ativa na mesma empresa.

    Na aplicacao, e nao no banco: o MySQL nao aplica UniqueConstraint com
    condition (o Django so avisa, W036). A trava na linha da Conta faz dois
    cadastros simultaneos passarem aqui um de cada vez — por isso quem chama
    precisa estar dentro de transaction.atomic().
    """
    if tipo != Loja.Tipo.FABRICA or not ativo:
        return

    Conta.objects.select_for_update().filter(pk=conta_id).first()

    outras = Loja.objects.filter(
        conta_id=conta_id, tipo=Loja.Tipo.FABRICA, ativo=True, is_deleted=False
    )
    if loja is not None:
        outras = outras.exclude(pk=loja.pk)

    existente = outras.first()
    if existente:
        raise ValidationError(
            {"tipo": f"Esta empresa já tem uma fábrica: {existente.nome_loja}."}
        )
