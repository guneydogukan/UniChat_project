"""
UniChat Backend — Seed Data
_test_seed.json üzerinden ingestion pipeline ile test verisi yükler.

Kullanım:
    python database/seed_data.py
"""

import os
import sys

# Backend dizinini Python path'e ekle (app.* import'ları için)
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _backend_dir)

from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app.ingestion.loader import load_json_file


def seed():
    """_test_seed.json dosyasını ingestion pipeline üzerinden yükler."""
    json_path = os.path.join(_backend_dir, "data", "_test_seed.json")

    if not os.path.exists(json_path):
        print(f"\033[91m❌ Test veri dosyası bulunamadı: {json_path}\033[0m", file=sys.stderr)
        sys.exit(1)

    try:
        written = load_json_file(json_path)
        print(f"✅ Test verileri yüklendi ({written} belge yazıldı): {json_path}")
    except Exception as e:
        print(f"\033[91m❌ Hata oluştu: {e}\033[0m", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    seed()
