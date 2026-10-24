import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from scrapers.hwk_kassel import (
    HwkKasselScraper,
    _parse_bubiza_dauer,
    _parse_bubiza_hours,
    _resolve_bubiza_hours,
    extract_bbz_trade,
    normalize_bbz_trade,
)


class BbzMarburgTradeParsingTests(unittest.TestCase):
    def test_extract_bbz_trade_strips_spaced_format_suffix(self):
        self.assertEqual(
            extract_bbz_trade("Meistervorbereitung Maler + Lackierer Vollzeit"),
            "Maler + Lackierer",
        )

    def test_extract_bbz_trade_strips_glued_format_suffix_typo(self):
        self.assertEqual(
            extract_bbz_trade("Meistervorbereitung Maler + LackiererTeilzeit"),
            "Maler + Lackierer",
        )
        self.assertEqual(
            extract_bbz_trade("Meistervorbereitung Maler + LackiererVollzeit"),
            "Maler + Lackierer",
        )

    def test_normalize_bbz_trade_maps_maler_lackierer_variants(self):
        self.assertEqual(normalize_bbz_trade("Maler + Lackierer"), "Maler und Lackierer")
        self.assertEqual(normalize_bbz_trade("Maler + LackiererTeilzeit"), "Maler und Lackierer")
        self.assertEqual(normalize_bbz_trade("Maler + LackiererVollzeit"), "Maler und Lackierer")

    def test_normalize_bbz_trade_keeps_other_trades(self):
        self.assertEqual(normalize_bbz_trade("Friseur"), "Friseur")
        self.assertEqual(normalize_bbz_trade("Kfz-Techniker"), "Kfz.-Techniker")


BUBIZA_DAUER_BLOCK = """
                            Dauer
Grundkurs:
Teil I Fachpraxis: 50 U.-Std.,
Teil II Fachtheorie: 400 U.-Std.
Aufbaukurs:
Teil I Fachpraxis: 370 U.-Std.,
Teil II Fachtheorie: 330 U.-Std.
Teil III: 265 U.-Std. incl. Vorkurs
Teil: IV 100 U.-Std.
"""

BUBIZA_DACHDECKER_PAGE = """
<html><body>
<h1>Dachdeckermeister für Dachdeckergesellen</h1>
<div>Termine</div>
<ul>
<li>Teile I +II: Grundkurs: 02.11.2026 - 29.01.2027</li>
<li>Teile I +II: Aufbaukurs: 04.10.2027 - 04.02.2028</li>
<li>Teil IV: 01.02.2027 - 18.02.2027</li>
<li>Teil III: 01.03.2027 - 23.04.2027</li>
<li>weitere Termine auf Anfrage</li>
</ul>
<div>Dauer</div>
<ul>
<li>Grundkurs:</li>
<li>Teil I Fachpraxis: 50 U.-Std.,</li>
<li>Teil II Fachtheorie: 400 U.-Std.</li>
<li>Aufbaukurs:</li>
<li>Teil I Fachpraxis: 370 U.-Std.,</li>
<li>Teil II Fachtheorie: 330 U.-Std.</li>
<li>Teil III: 265 U.-Std. incl. Vorkurs</li>
<li>Teil: IV 100 U.-Std.</li>
</ul>
<div>Inhalte</div>
<div>Kosten</div>
<ul>
<li>Teile I+II Grundkurs: zzt. 3.990,00 Euro</li>
<li>Teil I+II Aufbaukurs: zzt. 5.990,00 Euro</li>
<li>Teil III: zzt. 1.990,00 Euro</li>
<li>Teil IV: zzt. 890,00 Euro</li>
<li>Prüfung I-IV: zzt. 820,00 Euro + 250,00 Euro, Materialkosten Arbeitsprobe</li>
<li>*Bedingungen der Handwerkskammer Kassel beachten!</li>
</ul>
<div>Kursteile im Zeitraum 2026 / 2027</div>
<ul>
<li>T. I+II Grund: 02.11.2026 - 29.01.2027</li>
<li>T. IV 01.02.2027 - 18.02.2027</li>
<li>T. III 01.03.2027 - 23.04.2027</li>
</ul>
<div>Kursteile im Zeitraum 2027 / 2028</div>
<ul>
<li>T. I+II Aufbau 04.10.2027 - 04.02.2028</li>
<li>T. IV 01.02.2027 - 18.02.2027</li>
<li>T. III 01.03.2027 - 23.04.2027</li>
</ul>
</body></html>
"""


def _parse_bubiza_page(html: str, title: str = "Dachdeckermeister für Dachdeckergesellen"):
    scraper = HwkKasselScraper()
    scraper.parse_html = lambda _url: BeautifulSoup(html, "html.parser")
    with patch("scrapers.hwk_kassel.datetime") as dt:
        dt.today.return_value.strftime.return_value = "2026-10-24"
        return scraper._parse_bubiza_page({"title": title, "url": "https://www.bubiza.de/kurs.html"})


def _by_parts(offers):
    return {tuple(o.parts): o for o in offers}


class BubizaDurationParsingTests(unittest.TestCase):
    def test_hours_plain_and_thousands_dots(self):
        self.assertEqual(_parse_bubiza_hours("Teil I Fachpraxis: 50 U.-Std.,"), 50)
        self.assertEqual(_parse_bubiza_hours("Teil II Fachtheorie: ca. 1.450 U.-Std."), 1450)
        self.assertIsNone(_parse_bubiza_hours("5 Monate Vollzeit"))

    def test_dauer_block_keys_hours_per_part_and_sub(self):
        self.assertEqual(
            _parse_bubiza_dauer(BUBIZA_DAUER_BLOCK),
            {
                (1, "grund"): 50,
                (2, "grund"): 400,
                (1, "aufbau"): 370,
                (2, "aufbau"): 330,
                (3, None): 265,
                (4, None): 100,
            },
        )

    def test_dauer_absent_label_yields_nothing(self):
        self.assertEqual(_parse_bubiza_dauer("Teil I Fachpraxis: 50 U.-Std."), {})

    def test_resolve_prefers_inline_then_sums_matching_entries(self):
        dauer = {(1, "grund"): 50, (2, "grund"): 400, (3, None): 265}
        self.assertEqual(_resolve_bubiza_hours(dauer, [1, 2], "grund"), 450)
        self.assertEqual(_resolve_bubiza_hours(dauer, [3], None), 265)
        self.assertEqual(_resolve_bubiza_hours(dauer, [1, 2], None, inline=700), 700)
        self.assertIsNone(_resolve_bubiza_hours(dauer, [4], None))


class BubizaDachdeckerMergeTests(unittest.TestCase):
    def test_grund_and_aufbau_merge_into_one_course(self):
        offers = _by_parts(_parse_bubiza_page(BUBIZA_DACHDECKER_PAGE))
        merged = offers[(1, 2)]
        self.assertEqual(merged.title, "Dachdecker (Teile I + II)")
        self.assertEqual(merged.trade_name, "Dachdecker")
        self.assertEqual(merged.start_date, "2026-11-02")   # Anfang Grundkurs
        self.assertEqual(merged.end_date, "2028-02-04")     # Ende Aufbaukurs
        self.assertEqual(merged.duration_hours, 1150)       # 450 + 700
        self.assertEqual(merged.course_fee, 9980.0)         # 3.990 + 5.990
        self.assertEqual(merged.availability, "available")

    def test_merged_offer_records_both_component_runs(self):
        offers = _by_parts(_parse_bubiza_page(BUBIZA_DACHDECKER_PAGE))
        self.assertEqual(
            offers[(1, 2)].scraped_raw["merged_runs"],
            {
                "grundkurs": ["2026-11-02", "2027-01-29"],
                "aufbaukurs": ["2027-10-04", "2028-02-04"],
            },
        )

    def test_single_course_per_part_group_despite_repeated_kursteile_cards(self):
        offers = _parse_bubiza_page(BUBIZA_DACHDECKER_PAGE)
        self.assertEqual(len(offers), 3)
        self.assertEqual(sorted(tuple(o.parts) for o in offers), [(1, 2), (3,), (4,)])

    def test_teil_iii_and_iv_keep_own_durations_and_fees(self):
        offers = _by_parts(_parse_bubiza_page(BUBIZA_DACHDECKER_PAGE))
        teil_iv = offers[(4,)]
        self.assertEqual(teil_iv.title, "Berufs- und Arbeitspädagogik (Teil IV)")
        self.assertEqual(teil_iv.start_date, "2027-02-01")
        self.assertEqual(teil_iv.end_date, "2027-02-18")
        self.assertEqual(teil_iv.duration_hours, 100)
        self.assertEqual(teil_iv.course_fee, 890.0)

        teil_iii = offers[(3,)]
        self.assertEqual(teil_iii.title, "Wirtschaft und Recht (Teil III)")
        self.assertEqual(teil_iii.start_date, "2027-03-01")
        self.assertEqual(teil_iii.end_date, "2027-04-23")
        self.assertEqual(teil_iii.duration_hours, 265)
        self.assertEqual(teil_iii.course_fee, 1990.0)

    def test_unpaired_grundkurs_stays_a_separate_offer(self):
        html = BUBIZA_DACHDECKER_PAGE.replace(
            "<li>Teile I +II: Aufbaukurs: 04.10.2027 - 04.02.2028</li>", ""
        ).replace("<li>T. I+II Aufbau 04.10.2027 - 04.02.2028</li>", "")
        offers = _parse_bubiza_page(html)
        runs = [o for o in offers if o.parts == [1, 2]]
        self.assertEqual(len(offers), 3)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].start_date, "2026-11-02")
        self.assertEqual(runs[0].end_date, "2027-01-29")
        self.assertEqual(runs[0].duration_hours, 450)
        self.assertEqual(runs[0].course_fee, 3990.0)
        self.assertNotIn("merged_runs", runs[0].scraped_raw)

    def test_inline_hours_on_run_line_without_dauer_block(self):
        html = """
        <html><body>
        <div>Termine</div>
        <div>Teil III: 01.03.2027 - 23.04.2027 ca. 272 U.-Std.</div>
        <div>Kosten</div>
        <div>Teil III: zzt. 1.990,00 Euro</div>
        </body></html>
        """
        offers = _parse_bubiza_page(html, title="Zimmermeister Holzbau Deutschland anerkannt")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].duration_hours, 272)
        self.assertEqual(offers[0].course_fee, 1990.0)


if __name__ == "__main__":
    unittest.main()
