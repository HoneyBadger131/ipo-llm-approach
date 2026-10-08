"""규칙 단위 시험: python -m unittest jev_test.test_rules   (레포 루트에서, 네트워크·API 키 불필요)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dart_rules  # noqa: E402
import rules_core as r  # noqa: E402


def case(t, corp="테스트", code="999999", corr=False):
    return dict(report_nm=t, corp_name=corp, stock_code=code, is_correction=corr)


class TestRuleFilter(unittest.TestCase):          # dart_rules.py (공시명 규칙 필터)
    def test_basic(self):
        self.assertEqual(dart_rules.classify("투자설명서"), "exclude")
        self.assertEqual(dart_rules.classify("사업보고서 (2025.12)"), "separate")
        self.assertEqual(dart_rules.classify("단일판매ㆍ공급계약체결"), "review")
        self.assertEqual(dart_rules.classify("[기재정정]단일판매ㆍ공급계약체결"), "exclude")

    def test_dispute_exemption(self):
        self.assertEqual(dart_rules.classify("임시주주총회결과", "대웅제약"), "exclude")
        self.assertEqual(dart_rules.classify("임시주주총회결과", "고려아연"), "review")
        self.assertEqual(dart_rules.classify("독립이사의선임ㆍ해임또는중도퇴임에관한신고", "한진칼"), "review")
        self.assertEqual(dart_rules.classify("독립이사의선임ㆍ해임또는중도퇴임에관한신고", "금양"), "exclude")
        self.assertEqual(dart_rules.classify("[기재정정]임시주주총회결과", "고려아연"), "exclude")


class TestHardRules(unittest.TestCase):
    def test_cap_rank(self):
        self.assertEqual(r.cap_rank("005930"), 1)
        self.assertTrue(r.is_large_cap("000660"))           # SK하이닉스 2위
        self.assertFalse(r.is_large_cap("010130"))          # 고려아연 33위

    def test_rumor_by_tier(self):
        self.assertEqual(r.hard_rule(case("풍문또는보도에대한해명(미확정)", "SK하이닉스", "000660"))[0], "PASS_CHECK")
        self.assertEqual(r.hard_rule(case("풍문또는보도에대한해명(미확정)", "태광산업", "003240"))[0], "DROP")
        self.assertEqual(r.hard_rule(case("조회공시요구(풍문또는보도)에대한답변(미확정)", "고려아연", "010130"))[0], "PASS_CHECK")  # 분쟁 리스트

    def test_simple_types(self):
        self.assertEqual(r.hard_rule(case("불성실공시법인지정"))[0], "PASS")
        self.assertEqual(r.hard_rule(case("중대재해발생"))[0], "PASS_CHECK")
        self.assertEqual(r.hard_rule(case("대표이사(대표집행임원)변경(안내공시)"))[0], "NOTIFY")
        self.assertEqual(r.hard_rule(case("합병등종료보고서(합병)"))[0], "DROP")
        self.assertEqual(r.hard_rule(case("회사합병결정", ), "소규모합병 어쩌고")[0], "DROP")
        self.assertIsNone(r.hard_rule(case("회사합병결정"), "대규모 합병 계약"))
        self.assertEqual(r.hard_rule(case("기타안내사항(안내공시)"), "보호예수 해제 안내")[0], "PASS_CHECK")
        self.assertIsNone(r.hard_rule(case("단일판매ㆍ공급계약체결")))

    def test_amount_gates(self):
        small = "신탁계약금액(원) 20,000,000,000"      # 200억
        big = "신탁계약금액(원) 250,000,000,000"       # 2,500억
        self.assertEqual(r.hard_rule(case("주요사항보고서(자기주식취득신탁계약해지결정)"), small)[0], "DROP")
        self.assertEqual(r.hard_rule(case("주요사항보고서(자기주식취득신탁계약해지결정)"), big)[0], "PASS_CHECK")
        self.assertEqual(r.hard_rule(case("특수관계인과의수익증권거래", "대신증권"), "취득금액(원) 79,900,000,000")[0], "DROP")
        self.assertEqual(r.hard_rule(case("특수관계인과의수익증권거래", "대신증권"), "취득금액(원) 150,000,000,000")[0], "PASS_CHECK")
        self.assertEqual(r.hard_rule(case("부동산투자회사자금차입", "SK리츠"), "차입금액(원) 100,000,000,000")[0], "DROP")   # 리츠 차입은 금액과 무관하게 DROP
        self.assertIsNone(r.hard_rule(case("타법인주식및출자증권취득결정", "한화생명")))          # 금융회사 인수·출자는 일상 영업이 아님
        self.assertIsNone(r.hard_rule(case("타인에대한채무보증결정", "현대건설")))               # 일반 기업은 Jev 판단

    def test_correction(self):
        body_big = ("정정신고(보고) / 정정사항 / 정정항목 / 정정전 / 정정후 / 2. 계약내역 - 계약금액(원) / 489,059,755,158 / 524,323,051,232 / 끝")
        body_small = ("정정신고(보고) / 정정사항 / 정정항목 / 정정전 / 정정후 / 2. 계약내역 - 계약금액(원) / 332,900,000,000 / 333,000,000,000 / 끝")
        self.assertEqual(r.hard_rule(case("[기재정정]단일판매ㆍ공급계약체결", corr=True), body_big)[0], "PASS_CHECK")     # +352억, +7.2%
        self.assertEqual(r.hard_rule(case("[기재정정]단일판매ㆍ공급계약체결", corr=True), body_small)[0], "DROP")        # +1억
        self.assertEqual(r.hard_rule(case("[기재정정]증권신고서(채무증권)", corr=True))[0], "DROP")
        self.assertEqual(r.hard_rule(case("[기재정정]단일판매ㆍ공급계약체결", corr=True), "정정신고 정정사항 계약 해지 통보")[0], "PASS_CHECK")


if __name__ == "__main__":
    unittest.main()
