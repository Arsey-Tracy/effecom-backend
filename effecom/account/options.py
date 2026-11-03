from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


LANGUAGE_NAMES = {
    "ach": "Acholi",
    "afr": "Afrikaans",
    "aka": "Akan",
    "adh": "Jopadhola",
    "alz": "Alur",
    "amh": "Amharic",
    "bam": "Bambara",
    "bem": "Bemba",
    "ber": "Berber",
    "bfa": "Bari",
    "cgg": "Rukiga",
    "dag": "Dagbani",
    "dga": "Dagaare",
    "din": "Dinka",
    "eng": "English",
    "ewe": "Ewe",
    "ful": "Fulani",
    "gwr": "Lugwere",
    "hau": "Hausa",
    "ibo": "Igbo",
    "ikx": "Ik",
    "kab": "Kabyle",
    "kau": "Kanuri",
    "kdi": "Kumam",
    "kdj": "Karamojong",
    "keo": "Kakwa",
    "kik": "Kikuyu",
    "kin": "Kinyarwanda",
    "kln": "Kalenjin",
    "koo": "Rukonjo",
    "kpz": "Kupsabiny",
    "laj": "Lango",
    "led": "Lendu",
    "lgg": "Lugbara",
    "lin": "Lingala",
    "lsm": "Samia",
    "luc": "Aringa",
    "lug": "Luganda",
    "luo": "Luo",
    "luy": "Luhya",
    "mhi": "Ma'di",
    "mlg": "Malagasy",
    "myx": "Lumasaba",
    "nbl": "Ndebele",
    "nya": "Chichewa",
    "nuj": "Lunyole",
    "nyn": "Runyankole",
    "nyo": "Runyoro",
    "orm": "Oromo",
    "pcm": "Nigerian Pidgin",
    "pok": "Pokot",
    "rub": "Lugungu",
    "ruc": "Ruruuli",
    "run": "Kirundi",
    "rwm": "Kwamba",
    "sna": "Shona",
    "som": "Somali",
    "sot": "Sotho",
    "swa": "Swahili",
    "teo": "Ateso",
    "tlj": "Lubwisi",
    "tsn": "Tswana",
    "ttj": "Rutooro",
    "wol": "Wolof",
    "xho": "Xhosa",
    "xog": "Lusoga",
    "yor": "Yoruba",
    "zul": "Zulu",
}


class ToolOptionsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        languages = [
            {"code": code, "name": LANGUAGE_NAMES.get(code, code.upper())}
            for code in settings.SUNBIRD_TRANSLATION_LANGUAGES
        ]
        voices = [
            {"language": language, "name": name}
            for language, name in settings.SUNBIRD_TTS_VOICES
        ]
        return Response(
            {
                "languages": languages,
                "voices": voices,
                "max_text_length": settings.SUNBIRD_MAX_TEXT_LENGTH,
            }
        )
