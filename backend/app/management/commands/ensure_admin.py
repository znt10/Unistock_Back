import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create or update the default admin user."

    def handle(self, *args, **options):
        email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            raise CommandError(
                "DJANGO_SUPERUSER_EMAIL e DJANGO_SUPERUSER_PASSWORD precisam "
                "estar definidas no ambiente para criar/atualizar o admin."
            )

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                "email": email,
                "first_name": "Admin",
            },
        )

        user.email = email
        user.first_name = user.first_name or "Admin"
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        admin_group, _ = Group.objects.get_or_create(name="Admin")
        admin_permissions = Permission.objects.filter(content_type__app_label="app")
        admin_group.permissions.set(admin_permissions)
        user.groups.set([admin_group])

        action = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(f"Default admin {action}: {email}")
        )
