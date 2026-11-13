from django.core.management.base import BaseCommand

from captions.services.stale_jobs import fail_stale_caption_jobs


class Command(BaseCommand):
    help = "Mark caption jobs with an expired heartbeat as failed."

    def handle(self, *args, **options):
        count = fail_stale_caption_jobs()
        self.stdout.write(
            self.style.SUCCESS(f"Marked {count} stale caption job(s) as failed.")
        )
