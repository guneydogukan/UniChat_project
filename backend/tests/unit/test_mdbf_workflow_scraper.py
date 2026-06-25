"""MDBF workflow/form scraper parser testleri."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from scrapers.mdbf_workflow_forms_scraper import (  # noqa: E402
    FORM_SOURCE_URL,
    MdbfWorkflowFormsScraper,
    WORKFLOW_TARGETS,
)


def _workflow_html() -> str:
    all_names = [
        "Öğretim Üyesi Atanma İş Akış Şeması",
        "Araştırma Görevlisi İş Akış Şeması",
        "Ders Görevlendirme İş Akış Şeması",
        "Maaş İşlemleri İş Akış Şeması",
        "Ekders İş Akış Şeması",
        "Geçici Görev Yolluğu İş Akış Şeması",
        "Satın Alma İşlemleri İş Akış Şeması",
        "Fakülte Kurulu İş Akış Şeması",
        "Fakülte Yönetim Kurulu İş Akış Şeması",
        "Taşınır Mal, Kayıt ve Kontrol İşlemleri İş Akış Şeması",
        *(target.title for target in WORKFLOW_TARGETS),
    ]
    text = "PERSONEL İŞLERİ İŞ AKIŞ ŞEMALARI " + " ".join(
        f"- {name} için Tıklayınız..." for name in all_names
    ) + " MENÜ"
    links = "".join(
        f'<a href="https://www.gibtu.edu.tr/Medya/Birim/Dosya/{index:02d}.pdf">Tıklayınız...</a>'
        for index, _ in enumerate(all_names, start=1)
    )
    return f"<html><body><form id='aspnetForm'><div>{text}</div>{links}</form></body></html>"


def _forms_html() -> str:
    names = [
        "Ders Muafiyet Değerlendirme Formu",
        "Diğer Yükseköğretim Kurumlarının Yaz Okulu Programlarından Ders Alma Başvuru Formu",
        "İlişik Kesme Formu",
        "Kayıt Dondurma Başvuru Formu",
        "Sınav Kağıdına İtiraz ( Maddi Hata ) Formu",
        "Mazeret Ders Kayıt Formu",
        "Tek Ders Dilekçesi Formu",
        "Yatay Geçiş Başvuru Formu",
        "Yaz Okulu Başvuru Formu",
        "İntörn Mühendislik ( Uygulamalı Mühendislik ) Başvuru Formu",
        "Görevlendirme Başvuru Formu ( 1 Haftadan Az )",
        "Görevlendirme Başvuru Formu ( 1 Haftadan Fazla )",
        "Malzeme Talep Formu",
        "Mal Bildirim Formu",
        "Not Düzeltme Formu",
        "Tebliğ Tebellüğ Belgesi",
        "Ders Telafi Formu",
        "Ders Muafiyet Başvuru Formu",
        "Final ( Yarıyıl Sonu ) Sınavı Ücret Formu",
        "Eğitim Tutanağı Formu",
    ]
    links = []
    for index, name in enumerate(names, start=1):
        ext = "xlsx" if name == "Mal Bildirim Formu" else "pdf"
        links.append(f'<a href="Medya/Birim/Dosya/{index:02d}.{ext}">{name}</a>')
    links.append('<a href="https://www.gibtu.edu.tr/medya/birim/dosya/katalog.pdf">Fakülte Kataloğumuz</a>')
    return "<html><body>" + "".join(links) + "</body></html>"


class MdbfWorkflowScraperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scraper = MdbfWorkflowFormsScraper()

    def test_workflow_parser_only_targets_nine_student_workflows(self) -> None:
        workflows = self.scraper.parse_workflow_links(_workflow_html())

        self.assertEqual(len(workflows), 9)
        self.assertEqual(workflows[0]["process_key"], "course_registration")
        self.assertEqual(workflows[-1]["process_key"], "exam_appeal")
        self.assertTrue(all(item["pdf_url"].startswith("https://www.gibtu.edu.tr/") for item in workflows))

    def test_form_parser_extracts_twenty_unit_forms_and_process_keys(self) -> None:
        forms = self.scraper.parse_forms(_forms_html(), check_downloads=False)

        self.assertEqual(len(forms), 20)
        self.assertTrue(all(form["download_url"].startswith("https://www.gibtu.edu.tr/") for form in forms))
        by_name = {form["form_name"]: form for form in forms}
        self.assertEqual(by_name["Ders Muafiyet Başvuru Formu"]["process_key"], "course_exemption")
        self.assertEqual(by_name["Mazeret Ders Kayıt Formu"]["process_key"], "late_registration")
        self.assertEqual(by_name["Kayıt Dondurma Başvuru Formu"]["process_key"], "freeze_registration")
        self.assertEqual(by_name["Sınav Kağıdına İtiraz ( Maddi Hata ) Formu"]["process_key"], "exam_appeal")
        self.assertEqual(by_name["Mal Bildirim Formu"]["file_extension"], "xlsx")
        self.assertEqual(FORM_SOURCE_URL, self.scraper.form_url)


if __name__ == "__main__":
    unittest.main()

