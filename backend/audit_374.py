"""3.2.7.4 Tamamlanma Denetimi — Tüm alt görevleri kontrol eder."""
import sys
sys.path.insert(0, '.')

print('=' * 60)
print('3.2.7.4 DENETIM RAPORU')
print('=' * 60)

# 1. Import testi
print('\n=== 1. Import Testi ===')
errors = []

try:
    from scrapers.map_guided_scraper import MapGuidedScraper
    print('  [OK] map_guided_scraper')
except Exception as e:
    print(f'  [FAIL] map_guided_scraper: {e}')
    errors.append(f'Import: map_guided_scraper - {e}')

try:
    from app.ingestion.splitter import split_documents, _split_semantic
    print('  [OK] splitter + _split_semantic')
except Exception as e:
    print(f'  [FAIL] splitter: {e}')
    errors.append(f'Import: splitter - {e}')

try:
    from app.models.document_models import DOC_KINDS
    print(f'  [OK] DOC_KINDS')
except Exception as e:
    print(f'  [FAIL] document_models: {e}')
    errors.append(f'Import: document_models - {e}')

# 2. Method varlık kontrolü
print('\n=== 2. Method Varlık Kontrolü ===')
s = MapGuidedScraper.__new__(MapGuidedScraper)
required_methods = [
    '_extract_title',           # 3.2.7.4-A
    '_infer_doc_kind',          # 3.2.7.4-B  
    '_title_from_url_slug',     # 3.2.7.4-A
    '_clean_page_content',      # 3.2.7.4-C
    '_extract_pdf_documents',   # 3.2.7.4-E
    'load_from_json',           # 3.2.7.4-F
]
for method in required_methods:
    exists = hasattr(s, method)
    status = 'OK' if exists else 'MISSING!'
    print(f'  [{status}] {method}')
    if not exists:
        errors.append(f'Method missing: {method}')

# 3. pdfplumber kontrolü
print('\n=== 3. pdfplumber Kontrolü ===')
try:
    import pdfplumber
    print(f'  [OK] pdfplumber v{pdfplumber.__version__}')
except ImportError:
    print('  [MISSING] pdfplumber kurulu degil!')
    errors.append('pdfplumber not installed')

# 4. doc_kind inference testi
print('\n=== 4. doc_kind Inference Testi (3.2.7.4-B) ===')
test_cases = [
    ('https://www.gibtu.edu.tr/BirimYonetim.aspx?id=11', 'yonetim'),
    ('https://www.gibtu.edu.tr/BirimMisyon.aspx?id=11', 'tanitim'),
    ('https://www.gibtu.edu.tr/BirimForm.aspx?id=11', 'form'),
    ('https://www.gibtu.edu.tr/BirimMevzuat.aspx?id=11', 'yonetmelik'),
    ('https://www.gibtu.edu.tr/BirimIletisim.aspx?id=11', 'iletisim'),
    ('https://www.gibtu.edu.tr/BirimDuyuru.aspx?id=11', 'duyuru'),
    ('https://www.gibtu.edu.tr/BirimHaber.aspx?id=11', 'haber'),
    ('http://www.gibtu.edu.tr/ilahiyatfakultesi/icerik/31100/kalite-politikalarimiz', 'rapor'),
    ('http://www.gibtu.edu.tr/ilahiyatfakultesi/icerik/31157/ders-programlari', 'mufradat'),
    ('https://www.gibtu.edu.tr/Birim.aspx?id=11', 'genel'),
    ('https://www.gibtu.edu.tr/BirimAkademikPersonel.aspx?id=11', 'personel'),
]
pass_count = 0
for url, expected in test_cases:
    got = s._infer_doc_kind(url, 'genel')
    ok = got == expected
    if ok:
        pass_count += 1
    else:
        errors.append(f'doc_kind: {url[-40:]} expected={expected} got={got}')
    print(f'  [{"OK" if ok else "FAIL"}] {url[-45:]:<45s} -> {got:15s} (expected: {expected})')
print(f'  Sonuc: {pass_count}/{len(test_cases)} PASS')

# 5. Title slug testi
print('\n=== 5. Title Slug Testi (3.2.7.4-A) ===')
slug_tests = [
    ('http://www.gibtu.edu.tr/ilahiyatfakultesi/icerik/31100/kalite-politikalarimiz', 'Kalite politikalarimiz'),
    ('https://www.gibtu.edu.tr/BirimMisyon.aspx?id=11', 'Misyon'),
    ('http://www.gibtu.edu.tr/ilahiyatfakultesi/icerik/30941/risk-haritasi', 'Risk haritasi'),
]
for url, expected in slug_tests:
    got = s._title_from_url_slug(url)
    ok = got == expected
    print(f'  [{"OK" if ok else "FAIL"}] {url[-45:]:<45s} -> {repr(got)}')
    if not ok:
        errors.append(f'title_slug: expected={expected} got={got}')

# 6. Semantic chunking testi
print('\n=== 6. Semantic Chunking Testi (3.2.7.4-D) ===')
from haystack import Document
doc = Document(content="""## Kalite Politikalarimiz

Fakultemizin kalite politikasi ogrenci odakli egitim anlayisini benimsemektedir.

## Egitim-Ogretim Politikamiz

Egitim-ogretim programlarimiz uluslararasi standartlara uygun olarak hazirlanmis ve akredite edilmistir.

## Arastirma Politikamiz

Fakultemiz arastirma altyapisi guclendirilmistir.
""", meta={'doc_kind': 'genel', 'source_id': 'test'})

chunks = split_documents([doc])
print(f'  Input: 1 document, {len(doc.content)} chars')
print(f'  Output: {len(chunks)} chunks')
has_heading_context = any(c.meta.get('heading_context') for c in chunks)
print(f'  heading_context metadata: {"OK" if has_heading_context else "MISSING!"}')
for i, c in enumerate(chunks):
    hc = c.meta.get('heading_context', 'N/A')
    print(f'    Chunk {i}: {len(c.content)} chars, heading_context="{hc}"')
if not has_heading_context:
    errors.append('Semantic chunking: heading_context yok')

# 7. Boilerplate selectors kontrolü
print('\n=== 7. Boilerplate Selectors Kontrolü (3.2.7.4-C) ===')
from scrapers.map_guided_scraper import _BOILERPLATE_SELECTORS, _BOILERPLATE_PATTERNS
print(f'  DOM selectors: {len(_BOILERPLATE_SELECTORS)} adet')
print(f'  Regex patterns: {len(_BOILERPLATE_PATTERNS)} adet')
required_selectors = ['footer', 'nav', 'ul.collapsible', 'ul.side-nav']
for sel in required_selectors:
    found = sel in _BOILERPLATE_SELECTORS
    print(f'    [{"OK" if found else "MISSING!"}] {sel}')
    if not found:
        errors.append(f'Boilerplate selector missing: {sel}')

# 8. _URL_DOC_KIND_MAP kontrolü
print('\n=== 8. URL doc_kind Map Kontrolü ===')
from scrapers.map_guided_scraper import _URL_DOC_KIND_MAP
print(f'  Toplam pattern sayisi: {len(_URL_DOC_KIND_MAP)}')
kinds_in_map = set(k for _, k in _URL_DOC_KIND_MAP)
print(f'  Unique doc_kind sayisi: {len(kinds_in_map)} -> {sorted(kinds_in_map)}')

# SONUC
print('\n' + '=' * 60)
if errors:
    print(f'SONUC: {len(errors)} HATA TESPIT EDILDI!')
    for e in errors:
        print(f'  ❌ {e}')
else:
    print('SONUC: TUM KONTROLLER GECTI ✅')
print('=' * 60)
