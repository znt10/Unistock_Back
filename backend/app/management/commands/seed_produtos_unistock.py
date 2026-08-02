from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from app.models import Categoria, Produto


PRODUTOS = {
    "Salgados grande": [
        "Coxinha",
        "Risoles de queijo",
        "Risole presunto e queijo",
        "Bolinho de carne",
        "Kibe",
        "Kibe Queijo",
        "Salsicha",
        "Bolinho ovo",
    ],
    "Salgados mini": [
        "Coxinha",
        "Risoles de queijo",
        "Risole presunto e queijo",
        "Bolinho de carne",
        "Kibe",
        "Kibe Queijo",
    ],
    "Esfihas grande": [
        "Carne",
        "Frango",
        "Bauru",
        "Calabresa",
        "Hamburger",
        "Salsicha com cheddar",
        "Torta de banana",
    ],
    "Esfihas mini": [
        "Carne",
        "Frango",
        "Bauru",
        "Calabresa",
        "Hamburger",
        "Salsicha com cheddar",
        "Torta de banana",
    ],
    "Fogazzas grande": [
        "Presunto e Queijo",
        "2 Queijos",
        "Calabresa",
        "Frango",
        "Pizza",
        "Chocolate",
        "Doce de leite",
    ],
    "Fogazzas mini": [
        "Presunto e Queijo",
        "2 Queijos",
        "Calabresa",
        "Frango",
        "Pizza",
        "Chocolate",
        "Doce de leite",
    ],
    "Recheios": [
        "Açúcar+canela",
        "Bisnaga de chocolate",
        "Bisnaga doce de leite",
        "Bisnaga Beijinho",
        "Calabresa",
        "Carne",
        "Catupiry",
        "Frango",
        "Laranja",
        "Limão",
        "Massa de empada",
        "Massa Pastel",
        "Mussarela",
        "Óleo",
        "Orégano",
        "Ovo",
        "Palmito",
        "Pimenta",
        "Presunto",
        "Tomate",
    ],
    "Mercado": [
        "Açúcar",
        "Café",
        "Detergente",
        "Leite",
        "Nescau",
        "Bombril",
        "Adoçante",
    ],
}


class Command(BaseCommand):
    help = "Cadastra a lista padrao de produtos do UniStock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Remove todos os produtos antes de cadastrar a lista padrao.",
        )
        parser.add_argument(
            "--gerente",
            help=(
                "Email do gerente dono deste catalogo. Se omitido e so existir "
                "um gerente no sistema, usa ele; com zero ou mais de um, precisa "
                "informar explicitamente."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        gerente = self._resolver_gerente(options["gerente"])

        if options["limpar"]:
            total_removidos, _ = Produto.objects.filter(gerente=gerente).delete()
            self.stdout.write(f"Registros removidos: {total_removidos}")

        criados = 0
        atualizados = 0

        for indice, (nome_categoria, nomes) in enumerate(PRODUTOS.items()):
            categoria, _ = Categoria.objects.get_or_create(
                nome=nome_categoria, gerente=gerente, defaults={"ordem": indice}
            )
            for nome in nomes:
                _, created = Produto.objects.update_or_create(
                    nome_produto=nome.strip(),
                    categoria=categoria,
                    defaults={
                        "unidade_medida": Produto.UnidadeMedida.UNIDADE,
                        "quantidade_por_embalagem": None,
                        "estoque_minimo_sugerido": 1,
                        "gerente": gerente,
                    },
                )

                if created:
                    criados += 1
                else:
                    atualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Produtos cadastrados para {gerente.email}. "
                f"Criados: {criados}. Atualizados: {atualizados}."
            )
        )

    def _resolver_gerente(self, email):
        if email:
            try:
                return User.objects.get(email__iexact=email, groups__name="Gerente")
            except User.DoesNotExist:
                raise CommandError(f"Nenhum gerente encontrado com o email {email!r}.")

        gerentes = User.objects.filter(groups__name="Gerente")
        total = gerentes.count()
        if total == 1:
            return gerentes.first()
        if total == 0:
            raise CommandError("Nao ha nenhum gerente cadastrado ainda.")
        raise CommandError(
            "Mais de um gerente cadastrado — informe --gerente <email> pra "
            "dizer de quem e este catalogo."
        )
