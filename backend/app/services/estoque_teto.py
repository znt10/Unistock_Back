"""Quanto ainda cabe de cada produto numa loja, e o aviso quando nao cabe.

Fica fora do serializer porque tres caminhos criam pedido — a API, o bot de
WhatsApp e o PDV — e a conta de "isso estoura o teto?" precisa ser a mesma nos
tres. Regra duplicada em tres lugares e regra que diverge.
"""

from app.models import Estoque


class ExcessoDeEstoque(Exception):
    """O pedido cabe no formato, mas nao no teto da loja.

    Excecao Python pura, e nao APIException, porque o DRF converte todo valor
    do corpo de uma APIException em ErrorDetail (string) — o cliente receberia
    "70" em vez de 70 e teria que reconverter cada numero. O handler em
    app/api/erros.py devolve o 409 com os numeros intactos.

    409, e nao 400: o corpo do pedido esta correto; quem discorda e o estado
    atual da loja. O cliente reenvia igual, so que confirmando.
    """

    def __init__(self, payload):
        self.payload = payload
        super().__init__(payload.get("detail", "Excesso de estoque"))


def _teto_e_atual(loja, produto):
    """O teto DESTA loja para ESTE produto, e quanto ela tem agora.

    Devolve None quando a loja ainda nao tem linha deste produto: nesse caso
    nao existe teto desta loja, e o aviso ficaria em cima de um palpite
    universal — exatamente o que este campo veio eliminar. A protecao nao se
    perde: o pedido cria a linha ao ser entregue, e dali em diante o excesso
    alerta normalmente.
    """
    estoque = Estoque.objects.filter(loja=loja, produto=produto).first()
    if not estoque:
        return None, 0
    return estoque.quantidade_maxima, estoque.quantidade_atual


def itens_que_estouram_o_teto(loja, itens):
    """Os itens do pedido que passariam do maximo, prontos para virar aviso.

    `itens` sao dicts com "produto" e "quantidade" (o formato que o
    ItemPedidoSerializer ja entrega).
    """
    estouros = []

    for item in itens:
        produto = item["produto"]
        quantidade = item["quantidade"]
        maximo, atual = _teto_e_atual(loja, produto)
        if maximo is None:
            continue

        resultante = atual + quantidade

        if resultante > maximo:
            estouros.append({
                "produto": produto.nome_produto,
                "atual": atual,
                "pedido": quantidade,
                "resultante": resultante,
                "maximo": maximo,
                # Quanto ainda caberia: e o numero que a pessoa usa para
                # corrigir o pedido sem ter que fazer a conta na cabeca.
                "cabe": max(maximo - atual, 0),
            })

    return estouros


def conferir_teto(loja, itens, confirmado=False):
    """Levanta ExcessoDeEstoque se algum item passa do teto e ninguem confirmou.

    A trava e AVISADA, nao dura. Trava dura empurra quem esta na loja a subir
    o teto para 200 so para conseguir pedir — e nunca mais abaixar. Ai o teto
    vira ficcao e o alerta de excesso, que protege o produto de estragar,
    morre junto.
    """
    if confirmado:
        return []

    estouros = itens_que_estouram_o_teto(loja, itens)
    if estouros:
        raise ExcessoDeEstoque({
            "excesso": estouros,
            "detail": (
                "Este pedido deixa a loja acima do maximo. Reenvie com "
                "confirmar_excesso para registrar mesmo assim."
            ),
        })

    return estouros
