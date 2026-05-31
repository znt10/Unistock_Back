from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from html import escape
from typing import Literal

from django.http import HttpResponse
from django.utils import timezone

from app.models import Pedido


# ─── Tipos ────────────────────────────────────────────────────────────────────

Periodo = Literal["dia", "semana", "mes"]


@dataclass
class PedidoRelatorio:
    id: str
    hora: str
    responsavel: str
    status: str
    descricao: str
    itens: list[dict[str, str | int]]
    total_itens: int


@dataclass
class LojaRelatorio:
    nome: str
    pedidos: list[PedidoRelatorio]
    total_itens: int


STATUS_LABELS = {
    Pedido.Status.PENDENTE:  "Pendente",
    Pedido.Status.ENTREGUE:  "Entregue",
    Pedido.Status.CANCELADO: "Cancelado",
}

PERIODO_LABELS: dict[Periodo, str] = {
    "dia":    "Diário",
    "semana": "Semanal",
    "mes":    "Mensal",
}


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _responsavel_nome(pedido: Pedido) -> str:
    if not pedido.responsavel:
        return "Sem responsável"
    return (
        pedido.responsavel.get_full_name()
        or pedido.responsavel.first_name
        or pedido.responsavel.username
        or pedido.responsavel.email
    )


def _intervalo(periodo: Periodo, agora_local):
    """Retorna (inicio, fim) no horário local para o período escolhido."""
    inicio_dia = agora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    fim_dia    = agora_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    if periodo == "dia":
        return inicio_dia, fim_dia

    if periodo == "semana":
        # Segunda-feira da semana atual → domingo
        segunda = inicio_dia - timedelta(days=agora_local.weekday())
        domingo = segunda + timedelta(days=6)
        return segunda, domingo.replace(hour=23, minute=59, second=59, microsecond=999999)

    # mes
    primeiro = inicio_dia.replace(day=1)
    # último dia do mês: primeiro dia do próximo mês - 1 segundo
    if agora_local.month == 12:
        proximo_mes = primeiro.replace(year=agora_local.year + 1, month=1)
    else:
        proximo_mes = primeiro.replace(month=agora_local.month + 1)
    ultimo = proximo_mes - timedelta(seconds=1)
    return primeiro, ultimo


def _label_periodo(periodo: Periodo, inicio, fim) -> str:
    """Texto legível do intervalo para exibir no relatório."""
    fmt = "%d/%m/%Y"
    if periodo == "dia":
        return inicio.strftime(fmt)
    return f"{inicio.strftime(fmt)} a {fim.strftime(fmt)}"


def _buscar_pedidos(periodo: Periodo):
    agora_local = timezone.localtime(timezone.now())
    inicio, fim = _intervalo(periodo, agora_local)

    pedidos = (
        Pedido.objects.filter(data_pedido__range=(inicio, fim))
        .select_related("responsavel", "loja")
        .prefetch_related("itens__produto")
        .order_by("loja__nome_loja", "responsavel__first_name", "-data_pedido")
    )
    return agora_local, inicio, fim, list(pedidos)


def _categoria_nome(produto) -> str:
    cat = getattr(produto, "categoria", None)
    if cat is None:
        return "—"
    nome = getattr(cat, "nome", None)
    return str(nome) if nome else (str(cat) if cat else "—")


def _montar_lojas(pedidos: list[Pedido]) -> list[LojaRelatorio]:
    agrupadas: dict[str, list[PedidoRelatorio]] = defaultdict(list)

    for pedido in pedidos:
        itens = [
            {
                "produto":    item.produto.nome_produto,
                "categoria":  _categoria_nome(item.produto),
                "quantidade": item.quantidade,
            }
            for item in pedido.itens.all()
        ]
        total_itens = sum(int(item["quantidade"]) for item in itens)
        loja_nome   = pedido.loja.nome_loja if pedido.loja else "Sem loja"

        agrupadas[loja_nome].append(
            PedidoRelatorio(
                id=str(pedido.public_id)[:8],
                hora=timezone.localtime(pedido.data_pedido).strftime("%d/%m %H:%M"),
                responsavel=_responsavel_nome(pedido),
                status=STATUS_LABELS.get(pedido.status, pedido.status),
                descricao=pedido.descricao or "",
                itens=itens,
                total_itens=total_itens,
            )
        )

    return [
        LojaRelatorio(
            nome=nome,
            pedidos=pedidos_loja,
            total_itens=sum(p.total_itens for p in pedidos_loja),
        )
        for nome, pedidos_loja in agrupadas.items()
    ]


# ─── CSS ──────────────────────────────────────────────────────────────────────

def _css() -> str:
    return """
    @page {
      size: A4;
      margin: 10mm 13mm 14mm;
      @bottom-left  { content: "UniStock — Uso interno"; color: #9ca3af; font-size: 7.5px; }
      @bottom-right { content: "Pág. " counter(page) " / " counter(pages); color: #9ca3af; font-size: 7.5px; }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #fff;
      color: #111827;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 11px;
      line-height: 1.4;
    }

    /* ── Cabeçalho ── */
    .hero {
      border-bottom: 2px solid #e5e7eb;
      margin-bottom: 12px;
      padding-bottom: 8px;
    }
    .badge-periodo {
      display: inline-block;
      background: #1a56a0;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      padding: 4px 10px;
      vertical-align: middle;
      margin-left: 8px;
    }
    h1 {
      display: inline;
      font-size: 16px;
      font-weight: 700;
      color: #111827;
      margin: 0;
    }
    .hero-meta {
      color: #9ca3af;
      font-size: 9px;
      margin: 3px 0 0;
    }
    .hero-meta b { color: #6b7280; font-weight: 600; }

    /* ── Métricas ── */
    .metrics { margin-bottom: 14px; }
    .metric {
      background: #fff;
      border: 1px solid #d1d5db;
      border-top: 3px solid #1a56a0;
      display: inline-block;
      margin-right: 1.5%;
      padding: 8px 14px 7px;
      vertical-align: top;
      width: 31.33%;
    }
    .metric:nth-child(2) { border-top-color: #b45309; }
    .metric:nth-child(3) { border-top-color: #6d28d9; margin-right: 0; }
    .metric-label {
      color: #9ca3af;
      display: block;
      font-size: 7.5px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      margin-bottom: 3px;
    }
    .metric-value {
      display: block;
      font-size: 20px;
      font-weight: 800;
      line-height: 1;
      color: #111827;
    }

    /* ── Loja ── */
    .store {
      margin-bottom: 14px;
      page-break-inside: avoid;
      border: 1px solid #c5cfe0;
      border-radius: 8px;
      overflow: hidden;
    }
    .store-header {
      background: #1a56a0;
      padding: 7px 10px;
    }
    .store-title {
      color: #fff;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.8px;
      text-transform: uppercase;
    }
    .store-total {
      color: #bfdbfe;
      font-size: 9px;
      margin-top: 1px;
    }
    .store-total b { color: #fff; }

    /* ── Tabela única por loja ── */
    table { border-collapse: collapse; width: 100%; }
    thead tr { background: #dce4ef; }
    th {
      border-bottom: 1px solid #c5cfe0;
      border-right: 1px solid #c5cfe0;
      color: #1e3a5f;
      font-size: 8px;
      font-weight: 700;
      letter-spacing: 0.8px;
      padding: 6px 8px;
      text-align: left;
      text-transform: uppercase;
      white-space: nowrap;
    }
    th:last-child { border-right: 0; }
    td {
      border-bottom: 1px solid #e8edf5;
      border-right: 1px solid #e8edf5;
      color: #1e293b;
      font-size: 11px;
      padding: 5px 8px;
      vertical-align: middle;
    }
    td:last-child { border-right: 0; }
    tr:last-child td { border-bottom: 0; }
    tr:nth-child(even) td { background: #f0f4fa; }

    .col-produto  { font-weight: 700; font-size: 11.5px; width: 30%; }
    .col-cat      { color: #4b5563; font-size: 10.5px; width: 18%; }
    .col-qtd      { font-weight: 800; font-size: 13px; color: #1a56a0; text-align: center; width: 7%; }
    .col-resp     { color: #4b5563; font-size: 9.5px; width: 22%; }
    .col-resp b   { color: #1e293b; font-weight: 700; font-size: 10.5px; display: block; }
    .col-status   { text-align: center; width: 10%; padding: 0; }

    th.col-qtd    { text-align: center; }
    th.col-status { text-align: center; }

    /* status como célula colorida (estilo badge de fundo) */
    .td-status {
      font-size: 8.5px;
      font-weight: 700;
      text-align: center;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 5px 6px;
      vertical-align: middle;
    }
    .td-entregue  { background: #d1fae5; color: #065f46; }
    .td-pendente  { background: #fef3c7; color: #92400e; }
    .td-cancelado { background: #ffe4e6; color: #9f1239; }

    .obs {
      color: #94a3b8;
      font-size: 9px;
      font-style: italic;
      margin-top: 2px;
    }

    .empty {
      border: 1px solid #d1d5db;
      color: #9ca3af;
      font-size: 12px;
      padding: 32px;
      text-align: center;
    }
    """


# ─── HTML ─────────────────────────────────────────────────────────────────────

def _td_status_class(status: str) -> str:
    s = status.lower()
    if s == "entregue":
        return "td-status td-entregue"
    if s == "cancelado":
        return "td-status td-cancelado"
    return "td-status td-pendente"


def _html(context: dict) -> str:
    lojas_html = ""
    for loja in context["lojas"]:
        linhas = ""
        for pedido in loja.pedidos:
            td_status = f'<td class="col-status {_td_status_class(pedido.status)}">{escape(pedido.status)}</td>'
            obs = (
                f'<div class="obs">{escape(pedido.descricao)}</div>'
                if pedido.descricao else ""
            )
            for item in pedido.itens:
                linhas += f"""
                  <tr>
                    <td class="col-produto">{escape(str(item['produto']))}{obs}</td>
                    <td class="col-cat">{escape(str(item['categoria']))}</td>
                    <td class="col-qtd">{item['quantidade']}</td>
                    {td_status}
                    <td class="col-resp">
                      <b>{escape(pedido.responsavel)}</b>
                      {pedido.hora}
                    </td>
                  </tr>
                """
                obs = ""

        lojas_html += f"""
          <section class="store">
            <div class="store-header">
              <div class="store-title">Loja: {escape(loja.nome)}</div>
              <div class="store-total">
                <b>{len(loja.pedidos)}</b> pedidos &nbsp;·&nbsp; <b>{loja.total_itens}</b> itens
              </div>
            </div>
            <table>
              <thead>
                <tr>
                  <th class="col-produto">Produto</th>
                  <th class="col-cat">Categoria</th>
                  <th class="col-qtd">Qtd</th>
                  <th class="col-status">Status</th>
                  <th class="col-resp">Responsável</th>
                </tr>
              </thead>
              <tbody>{linhas}</tbody>
            </table>
          </section>
        """

    corpo = lojas_html or '<div class="empty">Nenhum pedido registrado neste período.</div>'

    total_pedidos = context["total_pedidos"]
    total_itens   = context["total_itens"]
    n_lojas       = len(context["lojas"])

    return f"""
    <!doctype html>
    <html lang="pt-BR">
      <head>
        <meta charset="utf-8">
        <style>{_css()}</style>
      </head>
      <body>
        <header class="hero">
          <h1>Pedidos das lojas</h1>
          <span class="badge-periodo">{escape(context["periodo_label"])}</span>
          <p class="hero-meta">
            <b>Período:</b> {escape(context["intervalo"])}
            &nbsp;·&nbsp;
            <b>Emitido em</b> {context["data"]} às {context["hora"]}
          </p>
        </header>

        <section class="metrics">
          <div class="metric">
            <span class="metric-label">Pedidos</span>
            <strong class="metric-value">{total_pedidos}</strong>
          </div>
          <div class="metric">
            <span class="metric-label">Itens</span>
            <strong class="metric-value">{total_itens}</strong>
          </div>
          <div class="metric">
            <span class="metric-label">Lojas</span>
            <strong class="metric-value">{n_lojas}</strong>
          </div>
        </section>

        {corpo}
      </body>
    </html>
    """


# ─── Função pública genérica ──────────────────────────────────────────────────

def gerar_relatorio_pedidos_pdf(periodo: Periodo = "dia") -> HttpResponse:
    """
    Gera o relatório PDF para o período informado.

    Uso nas views:
        gerar_relatorio_pedidos_pdf("dia")
        gerar_relatorio_pedidos_pdf("semana")
        gerar_relatorio_pedidos_pdf("mes")
    """
    from weasyprint import HTML

    agora_local, inicio, fim, pedidos = _buscar_pedidos(periodo)
    lojas       = _montar_lojas(pedidos)
    total_itens = sum(loja.total_itens for loja in lojas)

    context = {
        "periodo_label": PERIODO_LABELS[periodo],
        "intervalo":     _label_periodo(periodo, inicio, fim),
        "data":          agora_local.strftime("%d/%m/%Y"),
        "hora":          agora_local.strftime("%H:%M"),
        "total_pedidos": len(pedidos),
        "total_itens":   total_itens,
        "lojas":         lojas,
    }

    nome_arquivo = f"Relatorio_{periodo.capitalize()}_{agora_local.date().isoformat()}.pdf"
    pdf_bytes    = HTML(string=_html(context)).write_pdf()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_arquivo}"'
    return response
