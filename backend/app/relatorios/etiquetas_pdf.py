"""Etiquetas das caixas da fabrica, uma por pagina, para impressora termica.

60x40 mm: QR a esquerda, produto/pedido/caixa/data a direita, e o nome da loja
de destino grande embaixo — e o que evita trocar caixa de loja na hora de
carregar o carro.
"""

from html import escape

import segno
from django.conf import settings
from django.utils import timezone

CSS = """
@page { size: 60mm 40mm; margin: 2mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #000;
       font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }
.etiqueta { width: 56mm; height: 36mm; overflow: hidden; page-break-after: always; }
.etiqueta:last-child { page-break-after: auto; }
.topo { display: flex; gap: 2mm; height: 26mm; }
.qr { width: 26mm; height: 26mm; }
.dados { flex: 1; font-size: 7pt; line-height: 1.3; overflow: hidden; }
.dados p { margin: 0; }
.produto { font-size: 8.5pt; font-weight: 700; text-transform: uppercase; }
.caixa { font-size: 9pt; font-weight: 800; }
.loja { margin: 0; height: 10mm; line-height: 10mm; text-align: center;
        font-weight: 800; text-transform: uppercase;
        white-space: nowrap; overflow: hidden; }
"""


def link_da_caixa(codigo):
    return f"{settings.FRONTEND_URL}/caixa/{codigo}"


def tamanho_da_fonte_da_loja(nome):
    """O WeasyPrint nao encolhe texto para caber: a fonte sai por faixa."""
    tamanho = len((nome or "").strip())
    if tamanho <= 8:
        return "16pt"
    if tamanho <= 14:
        return "12pt"
    return "9pt"


def _qr(link):
    # make_qr, e nao make: make pode escolher Micro QR para texto curto, que a
    # camera de muito celular nao le.
    return segno.make_qr(link, error="m").svg_data_uri(scale=4, border=0)


def _etiqueta(caixa):
    pedido = caixa.pedido
    item = pedido.itens.all()[0]
    loja = pedido.loja.nome_loja
    data = timezone.localtime(caixa.created_at).strftime("%d/%m/%Y")
    return f"""
<section class="etiqueta">
  <div class="topo">
    <img class="qr" src="{_qr(link_da_caixa(caixa.codigo))}" alt="">
    <div class="dados">
      <p class="produto">{escape(item.produto.nome_produto)}</p>
      <p>Pedido #{pedido.id}</p>
      <p class="caixa">Caixa {caixa.numero}/{item.quantidade}</p>
      <p>{data}</p>
    </div>
  </div>
  <p class="loja" style="font-size: {tamanho_da_fonte_da_loja(loja)}">{escape(loja)}</p>
</section>"""


def html_das_etiquetas(caixas):
    corpo = "".join(_etiqueta(caixa) for caixa in caixas)
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{corpo}</body></html>"


def gerar_pdf_das_etiquetas(caixas):
    from weasyprint import HTML

    return HTML(string=html_das_etiquetas(caixas)).write_pdf()
