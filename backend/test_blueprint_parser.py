"""Test script for blueprint_parser — MDBF + Fakülteler tests."""
import sys
from pathlib import Path

# Backend dir on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from scrapers.blueprint_parser import parse_blueprint, _print_tree_report

GIBTU_DIR = Path(__file__).resolve().parent.parent / "doc" / "gibtu"


def test_mdbf():
    print("\n" + "=" * 70)
    print("TEST 1: MDBF Fakültesi Blueprint")
    print("=" * 70)

    mdbf_path = (
        GIBTU_DIR / "FAKÜLTELER"
        / "Mühendislik ve Doğa Bilimleri Fakültesi"
        / "Mühendislik_ve_Doğa_Bilimleri _Fakültesi.html"
    )

    tree = parse_blueprint(mdbf_path)
    stats = tree.stats

    print(f"\nMenu item count: {stats['menu_item_count']}")
    print(f"Total link count: {stats['total_link_count']}")
    print(f"Scrapable URLs: {stats['scrapable_url_count']}")
    print(f"PDF links: {stats['pdf_count']}")
    print(f"BirimID: {stats['birim_id']}")
    print(f"Link types: {stats['link_type_distribution']}")

    # Task spec assertions
    assert stats["menu_item_count"] >= 14, f"Expected >=14 menu items, got {stats['menu_item_count']}"
    assert stats["total_link_count"] >= 50, f"Expected >=50 links, got {stats['total_link_count']}"
    assert stats["pdf_count"] >= 5, f"Expected >=5 PDFs, got {stats['pdf_count']}"
    assert stats["birim_id"] == 15, f"Expected BirimID=15, got {stats['birim_id']}"

    print("\n--- Structured text preview ---")
    text = tree.to_structured_text()
    for line in text.split("\n")[:25]:
        print(f"  {line}")
    if text.count("\n") > 25:
        print(f"  ... ({text.count(chr(10)) - 25} more lines)")

    print(f"\nPDF links found:")
    for pdf in tree.get_pdf_links():
        print(f"  - {pdf.text[:50]} -> {pdf.url[:80]}")

    print("\nTEST 1 PASSED!")


def test_fakulteler():
    print("\n" + "=" * 70)
    print("TEST 2: Fakulteler Kok Harita")
    print("=" * 70)

    fak_path = GIBTU_DIR / "FAKÜLTELER" / "Fakülteler.html"
    tree = parse_blueprint(fak_path)
    stats = tree.stats

    print(f"\nMenu item count: {stats['menu_item_count']}")
    print(f"Total link count: {stats['total_link_count']}")

    urls = tree.to_url_list()
    print(f"\nURLs ({len(urls)}):")
    for url in urls:
        print(f"  - {url}")

    # Extract BirimIDs from URLs
    birim_ids = set()
    for url in urls:
        if "id=" in url:
            parts = url.split("id=")
            if len(parts) > 1:
                bid = parts[1].split("&")[0]
                if bid.isdigit():
                    birim_ids.add(int(bid))

    print(f"\nBirimIDs found: {sorted(birim_ids)}")
    expected = {11, 15, 20, 21, 22, 24}
    assert birim_ids == expected, f"Expected BirimIDs {expected}, got {birim_ids}"

    print("\nTEST 2 PASSED!")


def test_bilgisayar_muh():
    print("\n" + "=" * 70)
    print("TEST 3: Bilgisayar Muhendisligi Bolumu")
    print("=" * 70)

    bm_path = (
        GIBTU_DIR / "FAKÜLTELER"
        / "Mühendislik ve Doğa Bilimleri Fakültesi"
        / "Bilgisayar_Mühendisliği_Bölümü.html"
    )

    tree = parse_blueprint(bm_path)
    stats = tree.stats

    print(f"\nMenu item count: {stats['menu_item_count']}")
    print(f"Total link count: {stats['total_link_count']}")
    print(f"BirimID: {stats['birim_id']}")

    assert stats["birim_id"] == 18, f"Expected BirimID=18, got {stats['birim_id']}"
    assert stats["menu_item_count"] >= 11, f"Expected >=11 items, got {stats['menu_item_count']}"

    print(f"\nStructured text:")
    for line in tree.to_structured_text().split("\n"):
        print(f"  {line}")

    print("\nTEST 3 PASSED!")


if __name__ == "__main__":
    test_mdbf()
    test_fakulteler()
    test_bilgisayar_muh()
    print("\n" + "=" * 70)
    print("ALL TESTS PASSED!")
    print("=" * 70)
