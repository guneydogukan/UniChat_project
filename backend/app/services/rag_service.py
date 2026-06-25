"""
UniChat Backend — RAG Pipeline Servisi
Hybrid search: PgvectorEmbeddingRetriever (vektör) + PgvectorKeywordRetriever (BM25)
DocumentJoiner ile reciprocal_rank_fusion stratejisi uygulanır.

Savunma katmanları:
    1. Intent Classifier  — kapsam dışı sorguları pipeline öncesi reddeder
    2. Query Preprocessing — typo/abbreviation/comparison/routing
    3. Prompt Güçlendirme  — pozitif kısıtlamalar ile LLM davranışını yönlendirir
    4. Response Validator  — LLM çıktısındaki uydurma URL/telefon/e-posta'yı temizler
    5. Source Dedup        — URL + title + content bazlı kaynak tekrarını engeller
"""

import hashlib
import logging
import re
import time
import unicodedata
from haystack import Document, Pipeline, component
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.builders import PromptBuilder
from haystack.components.joiners import DocumentJoiner
from haystack.utils import Secret
from haystack_integrations.components.generators.ollama import OllamaGenerator
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore
from haystack_integrations.components.retrievers.pgvector import (
    PgvectorEmbeddingRetriever,
    PgvectorKeywordRetriever,
)

from app.config import get_settings
from app.services.administrative_staff_service import get_administrative_staff_service
from app.services.academic_calendar_service import get_academic_calendar_service
from app.services.academic_staff_service import get_academic_staff_service
from app.services.food_menu_service import get_food_menu_service
from app.services.program_catalog_service import get_program_catalog_service
from app.services.subunit_management_service import get_subunit_management_service
from app.services.unit_management_service import get_unit_management_service
from app.services.workflow_service import get_workflow_service
from app.services.yokatlas_query_service import get_yokatlas_query_service
from app.services.intent_classifier import classify_intent, REJECTION_RESPONSE
from app.services.response_validator import GENERAL_CONTACT_EMAIL, validate_response
from app.services.query_preprocessor import preprocess_query

logger = logging.getLogger(__name__)

# ── Türkçe Stopword Listesi ──
TURKISH_STOPWORDS: frozenset[str] = frozenset({
    "hangi", "ne", "neler", "nedir", "nasıl", "nerede", "nereye", "nereden",
    "kim", "kime", "kimin", "neden", "niçin", "niye", "kaç", "kadar",
    "mi", "mı", "mu", "mü",
    "var", "yok", "olan", "olarak", "olmak", "olur", "olabilir",
    "almak", "istiyorum", "istiyoruz", "ister", "istiyor",
    "diyor", "eder", "yapar", "verir", "gelir", "gider",
    "son", "ilk", "en", "bir", "birçok",
    "ve", "veya", "ile", "için", "gibi", "kadar", "ama", "fakat",
    "de", "da", "den", "dan", "bu", "şu", "o",
})

# ── Aday Öğrenci Kaynak Önceliği ──
# Aday portalı, aday deneyimiyle ilgili kritik konularda daha güncel ve bağlamsal
# metadata taşıdığı için prompt'a giden belge sıralamasında kontrollü biçimde öne alınır.
CANDIDATE_PRIORITY_TOP_K_BOOST = 2
CANDIDATE_FAQ_TOP_K_BOOST = 4
CANDIDATE_PORTAL_HOST = "adayogrenci.gibtu.edu.tr"
CANDIDATE_METADATA_VERSION = "candidate.v1"
CANDIDATE_SCRAPER_NAME = "candidate_portal_scraper"

FAQ_QUERY_RE = re.compile(r"\b(sikca\s+sorulan|sik\s+sorulan|sss|faq)\b", re.IGNORECASE)

PROGRAM_CATALOG_ROUTE_SIGNAL_RE = re.compile(
    r"\b("
    r"fakulte\w*|yuksekokul\w*|myo|meslek\s+yuksekokul\w*|enstitu\w*|"
    r"bolum\w*|program\w*|lisans|on\s*lisans|onlisans|"
    r"hangi\s+birim\w*|hangi\s+fakulte\w*|hangi\s+myo\w*|hangi\s+okul\w*|"
    r"hangi\s+yuksekokul\w*|bagli|bunyesinde|"
    r"var\s*mi|varmi|mevcut\s*mu|mevcutmu|"
    r"bulun(?:uyor|ur)\s*mu|yok\s*mu|yokmu|"
    r"ac(?:il(?:di|mis)|ik)\s*mi|ac(?:ildi|ilmis)mi|aktif\s*mi|aktifmi"
    r")\b",
    re.IGNORECASE,
)

PROGRAM_CATALOG_ROUTE_BLOCK_RE = re.compile(
    r"\b("
    r"bolum\s+baskan\w*|program\s+baskan\w*|baskan\w*|"
    r"dekan\w*|mudur\w*|yonetim\w*|danisman\w*|kurul\w*|sekreter\w*|"
    r"akademik\s+kadro\w*|akademik\s+personel\w*|akademisyen\w*|hoca\w*|"
    r"ogretim\s+uye\w*|ogretim\s+eleman\w*|kadro\w*|"
    r"kontenjan\w*|kontejan\w*|puan\w*|siralama\w*|osym|"
    r"yemek\w*|yemekhane\w*|yurt\w*|barinma\w*|ulasim\w*|"
    r"erasmus|degisim\w*|burs\w*|staj\w*|kutuphane\w*|"
    r"kampus\w*|imkan\w*|olanak\w*|kulup\w*|topluluk\w*|"
    r"idari\s+birim\w*|idari\s+personel\w*|ogrenci\s+is\w*|"
    r"sikca\s+sorulan|sik\s+sorulan|sss|faq"
    r")\b",
    re.IGNORECASE,
)

YOKATLAS_ROUTE_SIGNAL_RE = re.compile(
    r"\b("
    r"kontenjan\w*|kontejan\w*|birincilik\s+kontejan\w*|"
    r"taban\s+puan\w*|kac\s+puan\w*|puan\s+tur\w*|"
    r"basari\s+sira\w*|siralama\w*|yerlesen\w*|"
    r"osym|ozel\s+kosul\w*|netleri|ogretim\s+dili|ogrenim\s+dili"
    r")\b",
    re.IGNORECASE,
)

STUDENT_COUNT_QUERY_RE = re.compile(
    r"\b("
    r"kac\s+ogrenci|ogrenci\s+sayisi|okuyan\s+kac\s+(?:ogrenci|kisi)|"
    r"kac\s+(?:ogrenci|kisi)\s+okuyor|aktif\s+ogrenci\s+sayisi"
    r")\b",
    re.IGNORECASE,
)

STUDENT_COUNT_METRIC_EXCLUSION_RE = re.compile(
    r"\b(kontenjan\w*|kontejan\w*|yerlesen\w*|puan\w*|siralama\w*|osym|yok\s*atlas)\b",
    re.IGNORECASE,
)

ACADEMIC_PERSON_ROUTE_RE = re.compile(
    r"\b(hangi\s+bolum\w*|hangi\s+birim\w*|nerede)\b",
    re.IGNORECASE,
)

ACADEMIC_PERSON_CATALOG_FALSE_POSITIVE_RE = re.compile(
    r"\b("
    r"fakulte\w*|yuksekokul\w*|myo|meslek\s+yuksekokul\w*|enstitu\w*|"
    r"bolumler\w*|bolumleri\w*|programlar\w*|programlari\w*|"
    r"muhendisligi|hekimligi|bilimleri|ilimler"
    r")\b",
    re.IGNORECASE,
)

CAPITALIZED_NAME_TOKEN = r"(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-ZÇĞİÖŞÜ]{2,})"
CAPITALIZED_PERSON_NAME_RE = re.compile(
    rf"\b{CAPITALIZED_NAME_TOKEN}(?:\s+{CAPITALIZED_NAME_TOKEN}){{1,3}}\b"
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}")

NO_INFO_FALLBACK_RE = re.compile(
    r"\b("
    r"bu\s+konuda\s+elimde\s+yeterli\s+bilgi\s+bulunmuyor|"
    r"elimde\s+yeterli\s+bilgi\s+bulunmuyor|"
    r"belgelerde\s+yeterli\s+bilgi\s+bulunmuyor"
    r")\b",
    re.IGNORECASE,
)

CONTACT_FALLBACK_RE = re.compile(
    r"\b(detayli\s+bilgi\s+icin|ilgili\s+birim|birimine\s+basvur|basvurmanizi\s+oner)",
    re.IGNORECASE,
)

CONTACT_TOPIC_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"\b(kutuphane)\w*"),
        ("kutuphane", "dokumantasyon", "candidate library"),
    ),
    (
        re.compile(r"\b(ogrenci\s+is\w*|ders\s+kayd\w*|ders\s+kayit\w*|transkript|harc|diploma)\b"),
        ("ogrenci isleri", "ogrenciisleri", "academic calendar", "akademik takvim", "ders kay"),
    ),
    (
        re.compile(r"\b(erasmus|degisim\w*|uluslararasi)\b"),
        ("erasmus", "dis iliskiler", "uluslararasi"),
    ),
    (
        re.compile(r"\b(yemek\w*|yemekhane\w*|sks|burs\w*|yurt\w*|barinma\w*|spor)\b"),
        ("sks", "saglik kultur spor", "yemekhane", "yurt", "barinma", "burs"),
    ),
)

CANDIDATE_PRIORITY_BASE_TERMS: tuple[str, ...] = (
    "aday öğrenci",
    "aday portalı",
)

CANDIDATE_ANCHOR_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "iletisim-bilgileri": ("iletişim", "telefon", "e-posta"),
    "olanaklar": ("olanaklar", "öğrenci kulüpleri", "sosyal imkanlar", "yemekhane"),
    "konaklama": ("yurt", "barınma", "konaklama"),
    "erasmus": ("erasmus", "değişim programı", "uluslararası"),
    "ogrenim": ("bölümler", "programlar", "öğrenim", "kontenjan"),
    "sss": ("başvuru", "tercih", "kayıt", "sıkça sorulan sorular"),
    "gibtu": ("gibtü", "üniversite", "kampüs"),
    "kutuphane": ("kütüphane",),
    "gaziantep": ("gaziantep", "şehir", "ulaşım"),
    "cbiko": ("kariyer", "cbiko"),
    "ogrencibasarisi": ("öğrenci başarısı", "akademik başarı"),
}

CANDIDATE_PRIORITY_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (FAQ_QUERY_RE, ("sss",)),
    (re.compile(r"\b(iletisim|telefon|e\s?posta|mail|adres)\w*"), ("iletisim-bilgileri",)),
    (re.compile(r"\b(kulup|kulupler|topluluk|sosyal|aktivite|etkinlik)\w*"), ("olanaklar",)),
    (re.compile(r"\b(yurt|barinma|konaklama|kyk)\w*"), ("konaklama",)),
    (re.compile(r"\b(erasmus|degisim|uluslararasi|yurtdisi)\w*"), ("erasmus",)),
    (re.compile(r"\b(aday|tercih|yks|basvuru|kayit|kontenjan|program|bolum|lisans|onlisans)\w*"), ("ogrenim", "sss")),
    (re.compile(r"\b(olanak|imkan|kampus|yasam|spor|yemekhane|kafeterya)\w*"), ("olanaklar", "gibtu")),
    (re.compile(r"\b(kutuphane)\w*"), ("kutuphane",)),
    (re.compile(r"\b(gaziantep|sehir|ulasim)\w*"), ("gaziantep",)),
    (re.compile(r"\b(kariyer|cbiko|mezuniyet|akademik\s+basari)\w*"), ("cbiko", "ogrencibasarisi")),
)

# ── Prompt Şablonu ──
PROMPT_TEMPLATE = """Sen GİBTÜ (Gaziantep İslam Bilim ve Teknoloji Üniversitesi) resmi yapay zeka asistanı UniChat'sin.

KESİN KURALLAR:
1. YALNIZCA aşağıdaki "Belgeler" bölümündeki bilgilere dayanarak cevap ver. Belgeler dışından kesinlikle bilgi ekleme, tahmin yapma veya uydurma.
2. Belgede cevap yoksa veya yetersizse şunu söyle: "Bu konuda elimde yeterli bilgi bulunmuyor. Detaylı bilgi için [ilgili birimi belirt] birimine başvurmanızı öneriyorum." ve varsa birimin iletişim bilgisini veya web adresini ekle.
3. Her zaman Türkçe yanıt ver. Kullanıcı başka dilde yazsa bile Türkçe cevapla.
4. Yanıtını markdown formatında yaz: başlıklar, maddeler, kalın metin ve bağlantılar kullan.
5. Yanıtın açık, sade ve anlaşılır olsun. Uzun paragraflar yerine maddeli listeler tercih et.
6. Kullanıcıyı doğru birime yönlendir: hangi sorunun hangi birime (öğrenci işleri, bölüm sekreterliği, Erasmus ofisi, kütüphane vb.) ait olduğunu belirt.
7. Üniversite dışı konularda (siyaset, din, kişisel tavsiye, programlama kodu yazma vb.) cevap verme; kibarca üniversite konularıyla sınırlı olduğunu belirt.
8. Yanıtın sonunda, kullanıcının bu konuyla ilgili başvurabileceği birimi, telefon/e-posta bilgisini veya resmî web sayfası adresini belirt. Bu bilgi belgede varsa doğrudan kullan; yoksa en uygun birimi öner.
9. Akademik takvim cevaplarında yalnızca doc_kind=academic_calendar_event belgelerindeki structured metadata ve içerikte geçen tarihleri kullan. Kaynakta olmayan tarih, akademik yıl veya takvim türü üretme.
10. Kullanıcı akademik yıl veya takvim türü belirtmediyse sistem notundaki varsayımı açıkça söyle: "Bu bilgi güncel akademik yıl için genel/önlisans-lisans akademik takvimine göredir. Tıp, lisansüstü veya TÖMER takvimlerinde tarihler farklı olabilir."
11. Kullanıcı SSS, FAQ veya sık sorulan sorular sorarsa yalnızca doc_kind=candidate_faq olan aday öğrenci SSS belgelerini kullan. Bu belgeler yoksa başka konuya geçme; "Bu konuda elimde yeterli bilgi bulunmuyor." de.
12. Siyaset, uluslararası ilişkiler, savaş, ülke gündemi, Birleşmiş Milletler veya benzeri üniversite dışı konulara geçme. Belgelerde bu tür metinler görünse bile soru GİBTÜ/eğitim/kampüs bağlamı taşımıyorsa cevap verme.

YANITINDA KESİNLİKLE BULUNMAMASI GEREKENLER:
- Belgede açıkça yazılı OLMAYAN telefon numarası, e-posta adresi veya URL. Sadece belgelerde geçen iletişim bilgilerini kullan.
- Belgede olmayan bir URL tahmin etme veya oluşturma. URL bilgisi yoksa "Detaylı bilgi için www.gibtu.edu.tr adresini ziyaret ediniz" yaz.
- Programlama kodu (Python, JavaScript, SQL vb.). Kullanıcı kod isterse kibarca reddet.
- Üniversite ile ilgisi olmayan genel bilgiler (coğrafya, tarih, bilim, siyaset).

Belgeler:
{% for doc in documents %}
---
[{{ doc.meta.category | default("bilinmiyor") }}] {{ doc.meta.title | default("") }}
{% set public_source = doc.meta.source_public_url | default("", true) %}
{% set raw_source = doc.meta.source_url | default("", true) %}
Kaynak: {% if public_source %}{{ public_source }}{% elif raw_source.startswith("http://") or raw_source.startswith("https://") %}{{ raw_source }}{% else %}{{ doc.meta.title | default("belirtilmemiş") }}{% endif %}
{% if doc.meta.contact_unit %}İlgili birim: {{ doc.meta.contact_unit }}{% endif %}
{% if doc.meta.contact_info %}İletişim: {{ doc.meta.contact_info }}{% endif %}
{% if doc.meta.last_updated %}Son güncelleme: {{ doc.meta.last_updated }}{% endif %}

{{ doc.content }}
{% endfor %}

Soru: {{ question }}"""


def _is_http_url(value: str | None) -> bool:
    """Kullanıcıya link olarak gösterilebilecek URL mi?"""
    if not value:
        return False
    return value.strip().lower().startswith(("http://", "https://"))


def _public_source_url(meta: dict | None) -> str | None:
    """Metadata içinden güvenli kullanıcı kaynağını seçer."""
    if not meta:
        return None

    source_public_url = meta.get("source_public_url")
    if _is_http_url(source_public_url):
        return source_public_url

    source_url = meta.get("source_url")
    if _is_http_url(source_url):
        return source_url

    return None


def _normalize_for_matching(text: str) -> str:
    """Türkçe karakterleri sadeleştirerek regex eşleşmelerini kararlı hale getirir."""
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.replace("ı", "i")


def _candidate_priority_anchors(question: str) -> tuple[str, ...]:
    """Sorgunun aday portalı kaynak önceliği gerektirdiği anchor'ları döndürür."""
    normalized = _normalize_for_matching(question)
    anchors: list[str] = []

    for pattern, rule_anchors in CANDIDATE_PRIORITY_RULES:
        if pattern.search(normalized):
            for anchor in rule_anchors:
                if anchor not in anchors:
                    anchors.append(anchor)

    return tuple(anchors)


def _is_faq_query(question: str) -> bool:
    """SSS/FAQ sorgularını yazım ve Türkçe karakter farklarından bağımsız algılar."""
    return bool(FAQ_QUERY_RE.search(_normalize_for_matching(question)))


def _is_candidate_faq_doc(meta: dict | None) -> bool:
    """Belgenin aday öğrenci SSS kaynağı olup olmadığını metadata ile belirler."""
    if not meta:
        return False
    doc_kind = str(meta.get("doc_kind") or "")
    source_anchor = str(meta.get("source_anchor") or "")
    title = _normalize_for_matching(str(meta.get("title") or ""))
    return (
        doc_kind == "candidate_faq"
        or (_is_candidate_portal_doc(meta) and source_anchor == "sss")
        or (_is_candidate_portal_doc(meta) and "sik" in title and "sorulan" in title)
    )


def _should_try_program_catalog_route(question: str) -> bool:
    """Ucuz routing kapısı: yalnız akademik katalog olabilecek sorularda DB servisini dener."""
    normalized = _normalize_for_matching(question)
    if PROGRAM_CATALOG_ROUTE_BLOCK_RE.search(normalized):
        return False
    return bool(PROGRAM_CATALOG_ROUTE_SIGNAL_RE.search(normalized))


def _should_try_yokatlas_route(question: str) -> bool:
    """YÖK Atlas DB servisini yalnız tercih/metrik sinyali olan sorgularda dener."""
    return bool(YOKATLAS_ROUTE_SIGNAL_RE.search(_normalize_for_matching(question)))


def _unsupported_student_count_answer(question: str) -> dict | None:
    """Doğrulanmış öğrenci sayısı verisi olmayan sayım sorularını RAG'e düşürmez."""
    normalized = _normalize_for_matching(question)
    if STUDENT_COUNT_METRIC_EXCLUSION_RE.search(normalized):
        return None
    if not STUDENT_COUNT_QUERY_RE.search(normalized):
        return None
    return {
        "response": (
            "Bu soru doğrulanmış öğrenci sayısı verisi gerektiriyor. "
            "ÜniChat DB'de MDBF/program bazlı aktif öğrenci sayısı için resmi ve güncel bir kayıt bulunmadığından "
            "tahmini sayı veremem."
        ),
        "sources": [],
        "metadata": {
            "service": "deterministic_guard",
            "intent": "unsupported_student_count",
            "rag_fallback_used": False,
        },
    }


def _should_try_academic_person_route(question: str) -> bool:
    """Kişi adı + bölüm/birim sorgularını subunit yönetim regex'inden önce akademik kadroya alır."""
    normalized = _normalize_for_matching(question)
    if not ACADEMIC_PERSON_ROUTE_RE.search(normalized):
        return False
    if ACADEMIC_PERSON_CATALOG_FALSE_POSITIVE_RE.search(normalized):
        return False
    return bool(CAPITALIZED_PERSON_NAME_RE.search(question))


def _candidate_priority_query_suffix(question: str) -> str:
    """Retriever'ın aday portalı chunk'larını kaçırmaması için kontrollü sorgu eki üretir."""
    anchors = _candidate_priority_anchors(question)
    if not anchors:
        return ""

    terms: list[str] = []
    for term in CANDIDATE_PRIORITY_BASE_TERMS:
        if term not in terms:
            terms.append(term)

    for anchor in anchors:
        for term in CANDIDATE_ANCHOR_QUERY_TERMS.get(anchor, ()):
            if term not in terms:
                terms.append(term)

    return " ".join(terms)


def _is_candidate_portal_doc(meta: dict | None) -> bool:
    """Belgenin aday portalı ailesine ait olup olmadığını metadata üzerinden belirler."""
    if not meta:
        return False

    source_values = (
        str(meta.get("source_url") or ""),
        str(meta.get("source_public_url") or ""),
    )
    return (
        meta.get("category") == "aday_ogrenci"
        or meta.get("metadata_version") == CANDIDATE_METADATA_VERSION
        or meta.get("scraper_name") == CANDIDATE_SCRAPER_NAME
        or str(meta.get("doc_kind") or "").startswith("candidate_")
        or any(CANDIDATE_PORTAL_HOST in value.lower() for value in source_values)
    )


def _source_text_for_matching(source_doc: dict) -> str:
    values: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                walk(nested)

    walk(source_doc)
    return _normalize_for_matching("\n".join(values))


def _contact_source_terms_for_question(question: str) -> tuple[str, ...]:
    normalized = _normalize_for_matching(question)
    terms: list[str] = []
    for pattern, source_terms in CONTACT_TOPIC_RULES:
        if not pattern.search(normalized):
            continue
        for term in source_terms:
            normalized_term = _normalize_for_matching(term)
            if normalized_term and normalized_term not in terms:
                terms.append(normalized_term)
    return tuple(terms)


def _source_matches_contact_topic(source_doc: dict, source_terms: tuple[str, ...]) -> bool:
    if not source_terms:
        return False
    source_text = _source_text_for_matching(source_doc)
    return any(term in source_text for term in source_terms)


def _topic_specific_email_exists(question: str, source_docs: list[dict]) -> bool:
    source_terms = _contact_source_terms_for_question(question)
    if not source_terms:
        return True
    for source_doc in source_docs:
        if not _source_matches_contact_topic(source_doc, source_terms):
            continue
        if EMAIL_RE.search(_source_text_for_matching(source_doc)):
            return True
    return False


def _append_general_contact_if_needed(response: str, question: str, source_docs: list[dict]) -> str:
    """Konuya özel e-posta yoksa alakasız mail yerine resmi genel maili ekler."""
    if not response or EMAIL_RE.search(response):
        return response
    if not _contact_source_terms_for_question(question):
        return response
    if _topic_specific_email_exists(question, source_docs):
        return response

    note = (
        "Konuya özel iletişim bilgisi kaynaklarda net geçmiyor. "
        f"Genel iletişim: {GENERAL_CONTACT_EMAIL}"
    )
    if note in response:
        return response
    return f"{response.rstrip()}\n\n{note}"


def _is_fallback_block(text: str) -> bool:
    return bool(NO_INFO_FALLBACK_RE.search(_normalize_for_matching(text)))


def _looks_like_contact_fallback(text: str) -> bool:
    return bool(CONTACT_FALLBACK_RE.search(_normalize_for_matching(text)))


def _strip_contradictory_fallback(response: str, source_docs: list[dict]) -> str:
    """Kaynak/context varken cevaba karışan 'bilgi yok' fallback parçalarını temizler."""
    if not response or not source_docs or not _is_fallback_block(response):
        return response

    blocks = [block.strip() for block in re.split(r"\n\s*\n", response) if block.strip()]
    if len(blocks) > 1:
        kept_blocks = [block for block in blocks if not _is_fallback_block(block)]
        if kept_blocks and sum(len(block) for block in kept_blocks) >= 40:
            return "\n\n".join(kept_blocks)

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", response) if part.strip()]
    if len(sentences) <= 1:
        return response

    kept_sentences: list[str] = []
    removed_previous = False
    for sentence in sentences:
        if _is_fallback_block(sentence):
            removed_previous = True
            continue
        if removed_previous and _looks_like_contact_fallback(sentence):
            removed_previous = False
            continue
        kept_sentences.append(sentence)
        removed_previous = False

    cleaned = " ".join(kept_sentences).strip()
    if cleaned and len(cleaned) >= 40:
        logger.info("RAG yanıtındaki çelişkili fallback parçası temizlendi.")
        return cleaned
    return response


def _candidate_priority_score(doc: Document, priority_anchors: tuple[str, ...]) -> int:
    """Aday portalı belgeleri için topic uyumlu öncelik skoru üretir."""
    meta = doc.meta or {}
    if not _is_candidate_portal_doc(meta):
        return 0

    score = 100
    source_anchor = str(meta.get("source_anchor") or "")
    doc_kind = str(meta.get("doc_kind") or "")
    source_values = (
        str(meta.get("source_url") or ""),
        str(meta.get("source_public_url") or ""),
    )

    if source_anchor in priority_anchors:
        score += 80
    elif priority_anchors:
        score += 10

    if meta.get("metadata_version") == CANDIDATE_METADATA_VERSION:
        score += 30
    if meta.get("scraper_name") == CANDIDATE_SCRAPER_NAME:
        score += 25
    if doc_kind.startswith("candidate_"):
        score += 20
    if meta.get("is_official") is True or str(meta.get("is_official")).lower() == "true":
        score += 10
    if any(CANDIDATE_PORTAL_HOST in value.lower() for value in source_values):
        score += 10

    return score


def prioritize_candidate_documents(question: str, documents: list[Document]) -> list[Document]:
    """Aday odaklı kritik sorgularda aday portalı kaynaklarını prompt sıralamasında öne alır."""
    priority_anchors = _candidate_priority_anchors(question)
    if not priority_anchors or not documents:
        return documents

    scored_documents = [
        (_candidate_priority_score(doc, priority_anchors), index, doc)
        for index, doc in enumerate(documents)
    ]
    if not any(score > 0 for score, _, _ in scored_documents):
        return documents

    return [
        doc
        for score, _, doc in sorted(
            scored_documents,
            key=lambda item: (-item[0], item[1]),
        )
    ]


@component
class CandidateSourcePrioritizer:
    """Joiner sonrası belgeleri aday öğrenci kaynak önceliğine göre yeniden sıralar."""

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document], question: str = "") -> dict[str, list[Document]]:
        prioritized = prioritize_candidate_documents(question, documents)
        if _is_faq_query(question):
            faq_documents = [doc for doc in prioritized if _is_candidate_faq_doc(doc.meta)]
            return {"documents": faq_documents}
        return {"documents": prioritized}


class RagService:
    """RAG pipeline yönetim servisi — Hybrid Search (BM25 + vektör)."""

    def __init__(self):
        self._settings = get_settings()
        self._pipeline: Pipeline | None = None
        self._document_store: PgvectorDocumentStore | None = None

    def build_pipeline(self) -> None:
        """Hybrid search RAG pipeline'ını oluşturur ve bileşenleri bağlar.

        Pipeline akışı:
          text_embedder → vector_retriever ──┐
                                              ├→ joiner → candidate_source_prioritizer → prompt_builder → llm
          keyword_retriever ─────────────────┘
        """
        logger.info("Hybrid Search RAG pipeline oluşturuluyor...")

        # ── Document Store ──
        self._document_store = PgvectorDocumentStore(
            connection_string=Secret.from_env_var("DATABASE_URL"),
            table_name=self._settings.HAYSTACK_TABLE_NAME,
            embedding_dimension=self._settings.EMBEDDING_DIMENSION,
            language="turkish",
            keyword_index_name="unichat_keyword_index",
        )

        # ── Bileşenler ──
        text_embedder = SentenceTransformersTextEmbedder(
            model=self._settings.EMBEDDING_MODEL,
            prefix=self._settings.EMBEDDING_QUERY_PREFIX,
        )

        vector_retriever = PgvectorEmbeddingRetriever(
            document_store=self._document_store,
            top_k=self._settings.RETRIEVER_VECTOR_TOP_K,
        )

        keyword_retriever = PgvectorKeywordRetriever(
            document_store=self._document_store,
            top_k=self._settings.RETRIEVER_KEYWORD_TOP_K,
        )

        joiner = DocumentJoiner(join_mode="reciprocal_rank_fusion")
        candidate_source_prioritizer = CandidateSourcePrioritizer()

        prompt_builder = PromptBuilder(
            template=PROMPT_TEMPLATE,
            required_variables=["documents", "question"],
        )

        llm = OllamaGenerator(
            model=self._settings.OLLAMA_MODEL,
            url=self._settings.OLLAMA_URL,
        )

        # ── Pipeline oluştur ──
        self._pipeline = Pipeline()
        self._pipeline.add_component("text_embedder", text_embedder)
        self._pipeline.add_component("vector_retriever", vector_retriever)
        self._pipeline.add_component("keyword_retriever", keyword_retriever)
        self._pipeline.add_component("joiner", joiner)
        self._pipeline.add_component("candidate_source_prioritizer", candidate_source_prioritizer)
        self._pipeline.add_component("prompt_builder", prompt_builder)
        self._pipeline.add_component("llm", llm)

        # ── Bağlantılar ──
        self._pipeline.connect("text_embedder.embedding", "vector_retriever.query_embedding")
        self._pipeline.connect("vector_retriever.documents", "joiner.documents")
        self._pipeline.connect("keyword_retriever.documents", "joiner.documents")
        self._pipeline.connect("joiner.documents", "candidate_source_prioritizer.documents")
        self._pipeline.connect("candidate_source_prioritizer.documents", "prompt_builder.documents")
        self._pipeline.connect("prompt_builder", "llm")

        # Embedding modelini önceden yükle
        text_embedder.warm_up()

        logger.info(
            "✅ Hybrid Search RAG pipeline hazır "
            "(vector_top_k=%d, keyword_top_k=%d, join=reciprocal_rank_fusion).",
            self._settings.RETRIEVER_VECTOR_TOP_K,
            self._settings.RETRIEVER_KEYWORD_TOP_K,
        )

    @staticmethod
    def _clean_keyword_query(text: str) -> str:
        """Türkçe stopword'leri çıkararak keyword araması için sorguyu temizler."""
        words = text.split()
        meaningful = [w for w in words if w.lower() not in TURKISH_STOPWORDS]
        cleaned = " ".join(meaningful) if meaningful else text
        return cleaned

    def query(self, question: str) -> dict:
        """Kullanıcı sorusunu Hybrid Search RAG pipeline'dan geçirir.

        Savunma katmanları:
            1. Intent Classifier  — kapsam dışı → sabit reddetme yanıtı
            2. Query Preprocessing — typo/abbreviation/comparison/routing
            3. Pipeline (retrieval + LLM)
            4. Response Validator  — uydurma URL/telefon/e-posta temizliği
            5. Source Dedup        — URL + title + content bazlı dedup
            6. Routing Correction  — eksik birim yönlendirmesi

        Returns:
            dict: {"response": str, "sources": list[dict]}
        """
        food_menu_answer = get_food_menu_service().answer_chat_query(question)
        if food_menu_answer is not None:
            logger.info("Yemekhane menüsü sorgusu deterministik servisle yanıtlandı.")
            return food_menu_answer

        workflow_service = get_workflow_service()
        if workflow_service.should_preempt_calendar(question):
            workflow_answer = workflow_service.answer_chat_query(question)
            if workflow_answer is not None:
                logger.info("MDBF workflow/form sorgusu akademik takvimden önce deterministik servisle yanıtlandı.")
                return workflow_answer

        academic_calendar_answer = get_academic_calendar_service().answer_chat_query(question)
        if academic_calendar_answer is not None:
            logger.info("Akademik takvim sorgusu deterministik servisle yanıtlandı.")
            return academic_calendar_answer

        workflow_answer = workflow_service.answer_chat_query(question)
        if workflow_answer is not None:
            logger.info("MDBF workflow/form sorgusu deterministik servisle yanıtlandı.")
            return workflow_answer

        administrative_staff_answer = get_administrative_staff_service().answer_chat_query(question)
        if administrative_staff_answer is not None:
            logger.info("İdari birim/personel sorgusu deterministik servisle yanıtlandı.")
            return administrative_staff_answer

        if _should_try_academic_person_route(question):
            academic_staff_answer = get_academic_staff_service().answer_chat_query(question)
            if academic_staff_answer is not None:
                logger.info("Akademik kadro kişi/birim sorgusu deterministik servisle yanıtlandı.")
                return academic_staff_answer

        if _should_try_program_catalog_route(question):
            program_catalog_answer = get_program_catalog_service().answer_chat_query(question)
            if program_catalog_answer is not None:
                logger.info("Bölüm/program katalog sorgusu deterministik servisle yanıtlandı.")
                return program_catalog_answer

        if _should_try_yokatlas_route(question):
            yokatlas_answer = get_yokatlas_query_service().answer_chat_query(question)
            if yokatlas_answer is not None:
                logger.info("YÖK Atlas tercih/yerleşme sorgusu deterministik servisle yanıtlandı.")
                return yokatlas_answer

        unsupported_student_count_answer = _unsupported_student_count_answer(question)
        if unsupported_student_count_answer is not None:
            logger.info("Doğrulanmış öğrenci sayısı bulunmayan sorgu RAG'e düşürülmeden yanıtlandı.")
            return unsupported_student_count_answer

        subunit_management_answer = get_subunit_management_service().answer_chat_query(question)
        if subunit_management_answer is not None:
            logger.info("Bölüm/program yönetim sorgusu deterministik servisle yanıtlandı.")
            return subunit_management_answer

        unit_management_answer = get_unit_management_service().answer_chat_query(question)
        if unit_management_answer is not None:
            logger.info("Birim yönetim sorgusu deterministik servisle yanıtlandı.")
            return unit_management_answer

        academic_staff_answer = get_academic_staff_service().answer_chat_query(question)
        if academic_staff_answer is not None:
            logger.info("Akademik kadro sorgusu deterministik servisle yanıtlandı.")
            return academic_staff_answer

        if self._pipeline is None:
            raise RuntimeError("Pipeline henüz oluşturulmadı. build_pipeline() çağrılmalı.")

        t_total = time.perf_counter()
        logger.info("📩 Gelen soru: %s", question)

        # ── Katman 1: Intent Classifier ──
        t0 = time.perf_counter()
        intent = classify_intent(question)
        t_intent = time.perf_counter() - t0

        if intent == "OUT_OF_SCOPE":
            logger.info("🚫 Kapsam dışı sorgu reddedildi: %s", question[:80])
            logger.info(
                "⏱️ [latency] intent=%.3fs total=%.3fs (rejected)",
                t_intent, time.perf_counter() - t_total,
            )
            return {"response": REJECTION_RESPONSE, "sources": []}

        # ── Katman 2: Query Preprocessing ──
        t0 = time.perf_counter()
        pp = preprocess_query(question)
        t_preprocess = time.perf_counter() - t0

        if pp.corrections:
            logger.info("🔧 Sorgu ön-işleme: %s", ", ".join(pp.corrections))

        keyword_query = self._clean_keyword_query(pp.keyword_query)
        if keyword_query != pp.keyword_query:
            logger.info("🔤 Keyword sorgusu temizlendi: '%s' → '%s'", pp.keyword_query, keyword_query)

        candidate_query_suffix = _candidate_priority_query_suffix(question)
        vector_query = pp.vector_query
        candidate_top_k_boost = 0
        if candidate_query_suffix:
            keyword_query = f"{keyword_query} {candidate_query_suffix}"
            vector_query = f"{vector_query} {candidate_query_suffix}"
            candidate_top_k_boost = CANDIDATE_PRIORITY_TOP_K_BOOST
            if _is_faq_query(question):
                candidate_top_k_boost = CANDIDATE_FAQ_TOP_K_BOOST
            logger.info("🎯 Aday kaynak önceliği aktif: %s", candidate_query_suffix)

        vector_top_k = self._settings.RETRIEVER_VECTOR_TOP_K + pp.boost_top_k
        keyword_top_k = self._settings.RETRIEVER_KEYWORD_TOP_K + pp.boost_top_k
        vector_top_k += candidate_top_k_boost
        keyword_top_k += candidate_top_k_boost

        # ── Katman 3: Pipeline ──
        prompt_question = question
        if pp.routing_hint:
            prompt_question = f"{question}\n\n[Sistem notu: Bu konu için yetkili birim: {pp.routing_hint}]"
        if _is_faq_query(question):
            prompt_question = (
                f"{prompt_question}\n\n"
                "[Sistem notu: Kullanıcı SSS/FAQ/sık sorulan sorular istiyor. "
                "Yalnız aday öğrenci SSS (doc_kind=candidate_faq) kaynaklarından yanıt ver; "
                "aday SSS kaynağı yoksa bilgi bulunmadığını söyle.]"
            )
        if pp.system_note:
            prompt_question = f"{prompt_question}\n\n[Sistem notu: {pp.system_note}]"

        t0 = time.perf_counter()
        result = self._pipeline.run(
            data={
                "text_embedder": {"text": vector_query},
                "keyword_retriever": {"query": keyword_query, "top_k": keyword_top_k},
                "vector_retriever": {"top_k": vector_top_k},
                "candidate_source_prioritizer": {"question": question},
                "prompt_builder": {"question": prompt_question},
            },
            include_outputs_from={"candidate_source_prioritizer"},
        )
        t_pipeline = time.perf_counter() - t0

        # Yanıtı al
        replies = result.get("llm", {}).get("replies")
        if not replies:
            logger.warning("Pipeline sonucu boş döndü.")
            return {"response": None, "sources": []}

        response_text = replies[0]
        logger.info("Yanıt alındı (%d karakter)", len(response_text))

        # Joiner çıktısından kaynak belgelerini al
        sources = []
        validator_sources = []
        joined_docs = result.get("candidate_source_prioritizer", {}).get("documents", [])
        for doc in joined_docs:
            public_url = _public_source_url(doc.meta)
            full_source = {
                "content": doc.content or "",
                "source_url": public_url,
                "source_public_url": public_url,
                "meta": doc.meta or {},
            }
            if doc.meta:
                full_source["contact_info"] = doc.meta.get("contact_info")
                full_source["contact_unit"] = doc.meta.get("contact_unit")
            validator_sources.append(full_source)

            source = {
                "content": doc.content[:200] + "..." if len(doc.content) > 200 else doc.content,
                "source_url": public_url,
                "source_public_url": public_url,
                "category": doc.meta.get("category") if doc.meta else None,
                "title": doc.meta.get("title") if doc.meta else None,
                "doc_kind": doc.meta.get("doc_kind") if doc.meta else None,
                "source_anchor": doc.meta.get("source_anchor") if doc.meta else None,
            }
            sources.append(source)

        # ── Katman 4: Response Validator ──
        t0 = time.perf_counter()
        response_text = validate_response(response_text, validator_sources, question=question)
        t_validator = time.perf_counter() - t0

        # ── Katman 5: Source Dedup ──
        t0 = time.perf_counter()
        sources_before = len(sources)
        sources = self._dedup_sources(sources)
        t_dedup = time.perf_counter() - t0

        # ── Katman 6: Routing Correction ──
        if pp.routing_hint:
            response_text = self._apply_routing_correction(
                response_text, pp.routing_hint,
            )

        response_text = _strip_contradictory_fallback(response_text, validator_sources)
        response_text = _append_general_contact_if_needed(response_text, question, validator_sources)

        t_total_elapsed = time.perf_counter() - t_total

        # ── Latency Summary ──
        logger.info(
            "⏱️ [latency] intent=%.3fs preprocess=%.3fs pipeline=%.3fs "
            "validator=%.3fs dedup=%.3fs total=%.3fs "
            "sources=%d→%d",
            t_intent, t_preprocess, t_pipeline,
            t_validator, t_dedup, t_total_elapsed,
            sources_before, len(sources),
        )

        return {"response": response_text, "sources": sources}

    @staticmethod
    def _dedup_sources(sources: list[dict]) -> list[dict]:
        """Kaynak belgelerden tekrarlananları kaldırır.

        Dedup sinyalleri (öncelik sırasıyla):
            1. Aynı normalized URL → ilk chunk'ı tut, diğerlerini at
            2. Aynı content hash → birebir aynı içerik
            3. URL yok ama aynı title → ilkini tut
        """
        unique: list[dict] = []
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        seen_titles: set[str] = set()

        for src in sources:
            raw_url = (src.get("source_url") or "").strip().rstrip("/").lower()
            norm_url = raw_url.replace("https://", "http://")

            raw_title = (src.get("title") or "").strip().lower()

            content_hash = hashlib.md5(
                (src.get("content") or "").encode()
            ).hexdigest()

            # Kural 1: Aynı URL zaten eklendiyse atla
            if norm_url and norm_url in seen_urls:
                continue

            # Kural 2: Birebir aynı içerik zaten eklendiyse atla
            if content_hash in seen_hashes:
                continue

            # Kural 3: URL yoksa ve aynı title zaten eklendiyse atla
            if not norm_url and raw_title and raw_title in seen_titles:
                continue

            if norm_url:
                seen_urls.add(norm_url)
            seen_hashes.add(content_hash)
            if raw_title:
                seen_titles.add(raw_title)
            unique.append(src)

        if len(unique) < len(sources):
            logger.info(
                "🔄 Source dedup: %d → %d kaynak belge",
                len(sources), len(unique),
            )
        return unique

    @staticmethod
    def _apply_routing_correction(response: str, expected_unit: str) -> str:
        """Yanıtta beklenen birim geçmiyorsa yönlendirme notu ekler."""
        response_lower = response.lower()
        expected_lower = expected_unit.lower()

        unit_keywords = expected_lower.split()
        check_phrase = " ".join(unit_keywords[:2]) if len(unit_keywords) >= 2 else expected_lower
        if check_phrase in response_lower:
            return response

        correction_note = (
            f"\n\n> **📌 Yönlendirme:** Bu konuda yetkili birim "
            f"**{expected_unit.title()}**'dır. Detaylı bilgi için "
            f"bu birime başvurmanızı öneriyoruz."
        )
        logger.info(
            "🏢 Routing correction: '%s' birim yanıtta eksik, not eklendi",
            expected_unit,
        )
        return response + correction_note

    @property
    def document_store(self) -> PgvectorDocumentStore | None:
        """Document store'a erişim."""
        return self._document_store


# Singleton instance
rag_service = RagService()
