"""PDF do resumo diario de estoque baixo (anexo do digest das 7h).

Mesma linguagem visual do relatorio de pedidos, porem focado em reposicao:
o que falta, quanto tem e quanto deveria ter, agrupado por loja.
"""

from collections import defaultdict
from html import escape

from django.utils import timezone


def _css() -> str:
    return """
    @page {
      size: A4; margin: 12mm 13mm 15mm;
      @bottom-left  { content: "UniStock · Resumo de estoque"; color: #b4bcc8; font-size: 7.5px; letter-spacing: .5px; }
      @bottom-right { content: "Pág. " counter(page) " / " counter(pages); color: #b4bcc8; font-size: 7.5px; }
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: #fff; color: #0f172a;
           font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 11px; line-height: 1.45; }

    .hero { border-bottom: 3px solid #0f172a; margin-bottom: 18px; padding-bottom: 10px; }
    .hero-eyebrow { color: #b91c1c; font-size: 8px; font-weight: 800; letter-spacing: 3px;
                    text-transform: uppercase; margin: 0 0 3px; }
    h1 { display: inline; font-size: 24px; font-weight: 800; letter-spacing: -0.6px; color: #0f172a; margin: 0; }
    .hero-meta { color: #94a3b8; font-size: 9px; margin: 6px 0 0; }
    .hero-meta b { color: #475569; font-weight: 700; }

    .resumo { background: #fef2f2; border-left: 4px solid #b91c1c; margin-bottom: 20px;
              padding: 12px 16px; }
    .resumo-value { color: #b91c1c; font-size: 34px; font-weight: 800; letter-spacing: -1.5px;
                    line-height: 1; font-variant-numeric: tabular-nums; }
    .resumo-label { color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 1.5px;
                    text-transform: uppercase; margin-left: 8px; }

    .store { margin-bottom: 15px; page-break-inside: avoid; border: 1px solid #e2e8f0;
             border-radius: 7px; overflow: hidden; }
    .store-header { background: #12395f; padding: 9px 13px; }
    .store-title { display: inline-block; color: #fff; font-size: 12px; font-weight: 800; letter-spacing: 1px;
                   text-transform: uppercase; vertical-align: middle; }
    .store-stat { float: right; color: #cfe0f5; font-size: 9px; font-weight: 600; text-transform: uppercase;
                  letter-spacing: 0.5px; padding-top: 3px; }
    .store-stat b { color: #fff; font-size: 16px; font-weight: 800; font-variant-numeric: tabular-nums; }

    table { border-collapse: collapse; width: 100%; }
    thead tr { background: #dce4ef; }
    th { border-bottom: 1px solid #c5cfe0; border-right: 1px solid #c5cfe0; color: #1e3a5f; font-size: 8px;
         font-weight: 700; letter-spacing: 0.8px; padding: 6px 8px; text-align: left; text-transform: uppercase;
         white-space: nowrap; }
    th:last-child { border-right: 0; }
    td { border-bottom: 1px solid #e8edf5; border-right: 1px solid #e8edf5; color: #1e293b; font-size: 11px;
         padding: 5px 8px; vertical-align: middle; }
    td:last-child { border-right: 0; }
    tr:last-child td { border-bottom: 0; }
    tr:nth-child(even) td { background: #f0f4fa; }

    .col-produto { font-weight: 700; font-size: 11.5px; width: 40%; }
    .col-num     { text-align: center; width: 15%; font-variant-numeric: tabular-nums; }
    th.col-num   { text-align: center; }
    .atual       { color: #b91c1c; font-weight: 800; font-size: 13px; }
    .zerado      { background: #fee2e2 !important; color: #7f1d1d; }
    .repor       { color: #047857; font-weight: 800; font-size: 12px; }
    .sobra       { color: #b45309; font-weight: 800; font-size: 12px; }
    .acima       { color: #b45309; font-weight: 800; font-size: 13px; }
    .empty { border: 1px solid #d1d5db; color: #9ca3af; font-size: 12px; padding: 32px; text-align: center; }
    """


def _linhas_da_loja(estoques) -> str:
    linhas = ""
    for estoque in estoques:
        repor = max(estoque.quantidade_minima - estoque.quantidade_atual, 0)
        classe_atual = "col-num atual"
        if estoque.quantidade_atual == 0:
            classe_atual += " zerado"
        linhas += f"""
          <tr>
            <td class="col-produto">{escape(estoque.produto.nome_produto)}</td>
            <td class="{classe_atual}">{estoque.quantidade_atual}</td>
            <td class="col-num">{estoque.quantidade_minima}</td>
            <td class="col-num repor">{repor}</td>
          </tr>
        """
    return linhas


def _linhas_excedidas(estoques) -> str:
    linhas = ""
    for estoque in estoques:
        sobra = max(estoque.quantidade_atual - estoque.quantidade_maxima, 0)
        linhas += f"""
          <tr>
            <td class="col-produto">{escape(estoque.produto.nome_produto)}</td>
            <td class="col-num acima">{estoque.quantidade_atual}</td>
            <td class="col-num">{estoque.quantidade_maxima}</td>
            <td class="col-num sobra">{sobra}</td>
          </tr>
        """
    return linhas


def _secoes(estoques, colunas, linhas_de, vazio) -> str:
    """Um bloco por loja, com o cabecalho de colunas que o assunto pede."""
    por_loja = defaultdict(list)
    for estoque in estoques:
        por_loja[estoque.loja.nome_loja].append(estoque)

    html = ""
    for nome_loja, itens in por_loja.items():
        cabecalho = "".join(
            f'<th class="col-num">{coluna}</th>' for coluna in colunas[1:]
        )
        html += f"""
          <section class="store">
            <div class="store-header">
              <span class="store-stat"><b>{len(itens)}</b> itens</span>
              <span class="store-title">Loja: {escape(nome_loja)}</span>
            </div>
            <table>
              <thead>
                <tr>
                  <th class="col-produto">{colunas[0]}</th>
                  {cabecalho}
                </tr>
              </thead>
              <tbody>{linhas_de(itens)}</tbody>
            </table>
          </section>
        """

    return html or f'<div class="empty">{vazio}</div>'


def _html(estoques, titulo: str, subtitulo: str, excedidos=()) -> str:
    excedidos = list(excedidos)

    corpo = _secoes(
        estoques,
        ("Produto", "Em estoque", "Mínimo", "Repor"),
        _linhas_da_loja,
        "Nenhum produto abaixo do estoque mínimo.",
    )

    # A sobra so entra no documento quando existe: um bloco "nenhum produto
    # acima do maximo" todo dia vira ruido e a pessoa para de ler o PDF.
    if excedidos:
        corpo += f"""
        <section class="resumo">
          <span class="resumo-value">{len(excedidos)}</span>
          <span class="resumo-label">
            {"produtos acima do máximo" if len(excedidos) != 1 else "produto acima do máximo"}
          </span>
        </section>
        """ + _secoes(
            excedidos,
            ("Produto", "Em estoque", "Máximo", "Sobra"),
            _linhas_excedidas,
            "",
        )
    agora = timezone.localtime(timezone.now())
    total = len(estoques)

    return f"""
    <!doctype html>
    <html lang="pt-BR">
      <head>
        <meta charset="utf-8">
        <style>{_css()}</style>
      </head>
      <body>
        <header class="hero">
          <p class="hero-eyebrow">Resumo diário de estoque</p>
          <h1>{escape(titulo)}</h1>
          <p class="hero-meta">
            <b>{escape(subtitulo)}</b>
            &nbsp;·&nbsp;
            Emitido em {agora.strftime("%d/%m/%Y")} às {agora.strftime("%H:%M")}
          </p>
        </header>

        <section class="resumo">
          <span class="resumo-value">{total}</span>
          <span class="resumo-label">
            {"produtos abaixo do mínimo" if total != 1 else "produto abaixo do mínimo"}
          </span>
        </section>

        {corpo}
      </body>
    </html>
    """


def gerar_estoque_baixo_pdf(
    estoques, *, titulo: str, subtitulo: str, excedidos=()
) -> bytes:
    """Monta o PDF de estoque, agrupado por loja.

    Serve tanto para o PDF de uma loja quanto para o combinado do gerente —
    o que muda e so a lista de estoques recebida.

    `excedidos` acrescenta o bloco de quem passou do teto. Vai no MESMO
    documento, e nao num anexo separado, porque falta e sobra sao a mesma
    conversa: quem le decide o pedido do dia olhando as duas.
    """
    from weasyprint import HTML

    return HTML(
        string=_html(list(estoques), titulo, subtitulo, excedidos)
    ).write_pdf()
