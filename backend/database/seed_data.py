"""
UniChat Backend — Seed Data
Örnek GİBTÜ verilerini ingestion pipeline üzerinden yükler.

Kullanım:
    python database/seed_data.py           # Varsayılan örnek belgeler
    python database/seed_data.py --json    # data/_test_seed.json varsa onu kullan
"""

import os
import sys

# Backend dizinini Python path'e ekle (app.* import'ları için)
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _backend_dir)

from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from haystack import Document
from app.ingestion.loader import ingest_documents


# ── Varsayılan örnek belgeler ──
DEFAULT_DOCUMENTS = [
    Document(
        content="GİBTÜ Ön Lisans ve Lisans Eğitim-Öğretim Yönetmeliği Madde 24: "
                "Öğrenciler, danışmanlarının onayı ile her yarıyılda en fazla 45 AKTS "
                "kredilik ders alabilirler.",
        meta={"category": "egitim", "doc_kind": "yonetmelik", "source_type": "manual"},
    ),
    Document(
        content="GİBTÜ Yemekhane kuralları: Öğrenciler yemekhane rezervasyonlarını "
                "bir gün önceden akıllı kartlarına para yükleyerek sistem üzerinden "
                "yapmalıdır.",
        meta={"category": "yemekhane", "doc_kind": "rehber", "source_type": "manual"},
    ),
    Document(
        content="GİBTÜ Bilgisayar Mühendisliği Bölümü bitirme projesi teslim tarihi "
                "her yılın Mayıs ayının son haftasıdır.",
        meta={"category": "bolumler", "doc_kind": "duyuru", "source_type": "manual"},
    ),
]


def seed(use_json: bool = False):
    """Örnek verileri ingestion pipeline üzerinden yükler."""
    try:
        if use_json:
            # data/_test_seed.json varsa onu kullan
            json_path = os.path.join(_backend_dir, "data", "_test_seed.json")
            if os.path.exists(json_path):
                from app.ingestion.loader import load_json_file
                written = load_json_file(json_path)
                print(f"✅ JSON'dan {written} belge yüklendi: {json_path}")
                return
            else:
                print(f"⚠️ JSON dosyası bulunamadı: {json_path}, varsayılan belgeler kullanılıyor.")

        # Varsayılan belgelerle yükle
        written = ingest_documents(DEFAULT_DOCUMENTS)
        print(f"✅ Örnek GİBTÜ verileri yüklendi ({written} belge yazıldı).")

    except Exception as e:
        print(f"\033[91m❌ Hata oluştu: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    use_json = "--json" in sys.argv
    seed(use_json=use_json)
