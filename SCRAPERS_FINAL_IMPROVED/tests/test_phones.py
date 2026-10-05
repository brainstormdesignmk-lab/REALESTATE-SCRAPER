# tests/test_phones.py
# Unit tests for _shared/phones.py — cases taken verbatim from
# "BUGS PAZAR3 1.txt" and "BUGS REKLAMA5 1.txt".
#
# Run:  .venv/bin/python -m unittest tests.test_phones -v

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "_shared"))

from phones import normalize_phone, extract_phones, extract_phone_text, is_foreign  # noqa: E402


class TestNormalizePhone(unittest.TestCase):
    def test_mk_074_prefix_is_accepted(self):
        # The 074 prefix was missing from the old whitelist.
        self.assertEqual(normalize_phone("074205522"), "+389 074 205 522")
        self.assertEqual(normalize_phone("074224236"), "+389 074 224 236")

    def test_separator_formats(self):
        self.assertEqual(normalize_phone("071-751-588"), "+389 071 751 588")
        self.assertEqual(normalize_phone("072 240 604"), "+389 072 240 604")
        self.assertEqual(normalize_phone("070 219 252"), "+389 070 219 252")
        self.assertEqual(normalize_phone("078 280 680"), "+389 078 280 680")

    def test_mk_country_code_forms(self):
        self.assertEqual(normalize_phone("+389 78 377 677"), "+389 078 377 677")
        self.assertEqual(normalize_phone("00389 78 377 677"), "+389 078 377 677")
        self.assertEqual(normalize_phone("+389 71 751 588"), "+389 071 751 588")

    def test_foreign_numbers_become_e164(self):
        self.assertEqual(normalize_phone("+49 176 205 49 606"), "+4917620549606")
        self.assertEqual(normalize_phone("+393474837963"), "+393474837963")
        self.assertEqual(normalize_phone("+355697558898"), "+355697558898")
        self.assertEqual(normalize_phone("+1-647-963-5554"), "+16479635554")

    def test_foreign_with_00_prefix(self):
        self.assertEqual(normalize_phone("00381-62 758 588"), "+38162758588")

    def test_rejects_non_phone(self):
        self.assertIsNone(normalize_phone(""))
        self.assertIsNone(normalize_phone("+389"))
        self.assertIsNone(normalize_phone("12345"))
        self.assertIsNone(normalize_phone("250000"))

    def test_is_foreign(self):
        self.assertTrue(is_foreign("+4917620549606"))
        self.assertFalse(is_foreign("+389 074 205 522"))
        self.assertFalse(is_foreign(""))


class TestExtractPhones(unittest.TestCase):
    def test_tel_link_with_span_074(self):
        html = '<a href="tel:074205522"><span>074205522</span></a>'
        self.assertEqual(extract_phones(html=html), ["+389 074 205 522"])

    def test_bdi_dropdown_mixed(self):
        html = ("<div>Контакти: Viber, WhatsApp &amp; Skype</div>"
                "<bdi>071-751-588</bdi>"
                "<div>Viber:</div><bdi>+1-647-963-5554</bdi>")
        phones = extract_phones(html=html)
        self.assertEqual(phones[0], "+389 071 751 588")
        self.assertIn("+16479635554", phones)

    def test_number_in_body_text(self):
        html = ("<p>Просторот е обезбеден со алармен систем."
                " За повеќе информации и разгледување:</p><p>072 240 604 Мартин</p>")
        self.assertEqual(extract_phones(html=html), ["+389 072 240 604"])

    def test_number_in_text_with_contact_word(self):
        html = "<div>Контакт телефон 070 219 252. Цена по договор</div>"
        self.assertEqual(extract_phones(html=html), ["+389 070 219 252"])

    def test_serbian_number_written_with_00(self):
        html = ("<div>Za site potrebni informacii moze da se javite na "
                "00381-62 758 588,dostapni se i Viber i What up</div>")
        self.assertEqual(extract_phones(html=html), ["+38162758588"])

    def test_main_contact_button_foreign(self):
        html = ('<button class="new-btn btn-default btn-block btn-lg">'
                '<span class="main-contact"><bdi>+393474837963</bdi></span>'
                '<span class="secondary-contacts">Контакти: Viber, WhatsApp &amp; Skype</span>'
                '<i class="ci-pazar-small ci-caret-down ci-color-muted"></i>'
                '</button>')
        self.assertEqual(extract_phones(html=html), ["+393474837963"])

    def test_foreign_does_not_create_bogus_mk_number(self):
        html = "<div>Мобилен: +49 176 205 49 606</div>"
        self.assertEqual(extract_phones(html=html), ["+4917620549606"])

    def test_exclude_platform_number(self):
        html = "<div>078 377 677</div><div>070 219 252</div>"
        phones = extract_phones(html=html, exclude=["+389 078 377 677"])
        self.assertEqual(phones, ["+389 070 219 252"])

    def test_map_coordinates_are_not_phones(self):
        # Regression: "42.00863251183686" was read as +863251183686 (China).
        html = '<p class="ci-text-base">21.454448103904724 42.00863251183686</p>'
        self.assertEqual(extract_phones(html=html), [])

    def test_coordinate_like_mk_chunk_is_not_phone(self):
        html = "<p>42.078812345 21.454448103</p>"
        self.assertEqual(extract_phones(html=html), [])

    def test_extract_phone_text_primary_first(self):
        html = "<div>072 240 604</div><bdi>072 240 604</bdi>"
        self.assertEqual(extract_phone_text(html=html), "+389 072 240 604")


if __name__ == "__main__":
    unittest.main(verbosity=2)
