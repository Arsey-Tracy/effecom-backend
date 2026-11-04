from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command

from translation.models import Language


class Command(BaseCommand):
    help = "Load supported languages and update capability flags."

    def handle(self, *args, **options):
        fixture_path = (
            Path(__file__).resolve().parents[2] / "fixtures" / "languages.json"
        )
        call_command("loaddata", str(fixture_path), verbosity=0)

        supported_codes = set(settings.SUNBIRD_TRANSLATION_LANGUAGES)
        known_codes = set(
            Language.objects.filter(code__in=supported_codes).values_list(
                "code", flat=True
            )
        )
        missing_codes = supported_codes - known_codes
        if missing_codes:
            raise CommandError(
                "No language fixture entries found for: "
                + ", ".join(sorted(missing_codes))
            )

        Language.objects.update(
            supports_translation=False,
            supports_stt=False,
            supports_tts=False,
            is_active=False,
        )
        Language.objects.filter(code__in=supported_codes).update(
            supports_translation=True,
            is_active=True,
        )
        tts_codes = {language for language, _voice in settings.SUNBIRD_TTS_VOICES}
        Language.objects.filter(code__in=tts_codes).update(supports_tts=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Language.objects.filter(is_active=True).count()} "
                "active translation languages; STT remains disabled until verified."
            )
        )
