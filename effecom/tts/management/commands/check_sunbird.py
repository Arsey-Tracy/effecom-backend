from django.core.management.base import BaseCommand, CommandError

from effecom.sunbird import SunbirdError, check_authentication


class Command(BaseCommand):
    help = "Check that the configured Sunbird credentials are valid."

    def handle(self, *args, **options):
        try:
            check_authentication()
        except SunbirdError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Sunbird authentication is working."))
