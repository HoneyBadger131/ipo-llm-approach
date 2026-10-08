"""Jev 질문 정의 (공시 분류자). 기준은 jev_test/공시판단_기본원칙.md 참고.

한 요청에 아래 질문을 모두 넣는다(서로 독립·병렬 평가).
  - proceed     (Noul)   : 한 덩어리 질문 — "다음 단계로 넘길 만큼 중요한가"
  - triage      (Choice) : 4단계 라벨 PASS / PASS_CHECK / HOLD / DROP
  - importance  (Score)  : 0~4 중요도 단계
  - 원자 Noul 8개        : 코드에서 조합(composite)해 라벨을 만든다

라벨 의미
  PASS        통과       본문만으로 중요 판단이 선다 -> 다음 단계로
  PASS_CHECK  통과·확인  진행 쪽이지만 다음 단계 에이전트가 계산(자기자본·매출 비율, 전년 동월비)이나
                         정정 전후 대조를 해야 한다 -> 다음 단계로 (확인 사항 표시)
  HOLD        보류       규칙이 충돌하거나 해석이 갈려 사람 검토가 필요 -> 검수 큐
  DROP        탈락       중요하지 않음 -> 종료

state 키는 영어(title, company, body, correction)로 고정하고, instructions/criteria만 KO/EN으로 바꿔 비교한다.
"""

LABELS = ["PASS", "PASS_CHECK", "HOLD", "DROP"]
ATOMIC = ["monthly_results", "yoy_big", "big_amount", "business_shift", "bio_clinical", "rumor_first",
          "routine_admin", "repeat_known", "needs_comparison", "material_change"]

KO = {
    "proceed": dict(
        type="noul",
        instructions="이 공시는 투자자의 판단에 영향을 줄 만큼 중요해서 심화 분석 단계로 넘겨야 하는가? "
                     "`correction`이 있으면 정정 전후 변경 내용을 기준으로 판단한다.",
        criteria={
            "true": "금액 30억 원 이상의 계약·보증·투자·출자·대여·처분, 사업·지배구조·자본구조를 바꾸는 결정, "
                    "임상·허가 등 의약품 개발 사건(임상계획 변경 승인 포함), 경영권 분쟁·소송 결과, "
                    "아직 확정되지 않은 중요 사안에 대한 최초 풍문 해명, 정정으로 핵심 조건이 크게 바뀐 경우",
            "false": "기준일 설정·위원회 개최·정기 선임·보고서 발간 같은 정례·행정 공시, "
                     "이미 알려진 사안의 재공시·연장·종결·사본, 소액이며 사업 영향이 없는 공시, 핵심 조건이 바뀌지 않은 정정",
        }),
    "triage": dict(
        type="choice",
        instructions="이 공시를 다음 단계로 어떻게 처리해야 하는가? `correction`이 있으면 정정 전후 변경 내용을 기준으로 한다.",
        criteria={
            "PASS": "본문만으로 중요하다고 판단된다. 금액 30억 원 이상이 명시되었거나, 사업·지배·자본구조 변화, 임상 사건, 큰 소송 결과, 핵심 조건이 크게 바뀐 정정.",
            "PASS_CHECK": "중요해 보이지만 금액이 비공개이거나 30억 원 미만이어서, 자기자본·매출 대비 비율이나 전년 동월 대비 증감을 계산해 봐야 중요도가 정해진다. 또는 정정 전후 대조가 필요하다.",
            "HOLD": "사람의 판단이 필요하다. 금액은 크지만 정례 자금운용·차환 성격이거나, 중요성을 판단할 근거가 서로 충돌한다.",
            "DROP": "정례·행정 공시, 이미 알려진 사안의 재공시·연장·종결·사본, 소액이며 영향이 없는 공시, 핵심 조건이 바뀌지 않은 정정.",
        }),
    "importance": dict(
        type="score",
        instructions="이 공시가 투자자에게 주는 중요도는 어느 단계인가?",
        criteria=[
            "정례·행정 공시이거나 소액이다. 투자 판단과 무관하다.",
            "참고 수준이다. 이미 알려진 사안의 재공시·연장·종결이거나 영향이 거의 없다.",
            "알아둘 만한 이슈지만 영향이 작거나 불확실하다.",
            "의미 있는 영향이 있다. 금액이 30억 원 이상이거나 사업에 변화가 생긴다.",
            "큰 영향이 있다. 매출·자기자본 대비 비중이 크거나 사업·지배·자본구조가 근본적으로 바뀐다.",
        ]),
    "big_amount": dict(type="noul", instructions="본문에 30억 원 이상의 금액(계약·보증·투자·출자·대여·처분·취득 등)이 명시되어 있는가? 금액이 비공개이거나 30억 원 미만이면 아니오."),
    "business_shift": dict(type="noul", instructions="회사의 사업, 지배구조, 자본구조를 바꾸는 결정이나 사건(분할·합병·신사업·인수·매각·경영권 분쟁 등)인가?"),
    "bio_clinical": dict(type="noul", instructions="임상시험, 허가, 승인 등 의약품·바이오 개발 단계에 관한 공시인가? 임상계획 변경 승인도 포함한다."),
    "rumor_first": dict(type="noul", instructions="아직 확정되지 않은 중요 사안(인수·상장·대규모 투자·계약)에 대한 보도나 풍문에 회사가 처음 해명하는 공시인가? 이전 해명을 되풀이하는 재공시이거나 결과가 확정되어 종결된 공시는 아니오."),
    "routine_admin": dict(type="noul", instructions="법·제도상 반복되는 정례·행정·거버넌스 성격의 공시인가? (기준일 설정, 정기 이사 선임, 위원회 개최, 보고서 발간·게시, 효력발생 안내, 자금운용 차환 등)"),
    "repeat_known": dict(type="noul", instructions="이미 알려진 사안의 재공시·기간 연장·결과 종결·모회사 사본인가?"),
    "needs_comparison": dict(type="noul", instructions="금액이 비공개이거나 30억 원 미만이지만, 자기자본·매출 대비 비율이나 전년 동월 대비 증감을 계산해야 중요도를 알 수 있는 공시인가?"),
    "material_change": dict(type="noul", instructions="`correction`에서 금액·기간·상대방·수량·조건 등 핵심 내용이 실질적으로 바뀌었는가? `correction`이 없으면 아니오."),
}

EN = {
    "proceed": dict(
        type="noul",
        instructions="Is this Korean regulatory disclosure important enough to affect an investor's judgment and be sent on to deeper analysis? "
                     "If `correction` is present, judge by what changed between before and after.",
        criteria={
            "true": "A contract, guarantee, investment, equity injection, loan or disposal of KRW 3 billion or more; a decision that changes the business, governance or capital structure; "
                    "a drug clinical-trial or approval event (including approval of a changed trial plan); a management-control dispute or lawsuit outcome; "
                    "a company's first response to a report about an unconfirmed major matter; a correction that materially changes key terms",
            "false": "Routine or administrative filings (record dates, committee meetings, regular director appointments, report publication); "
                     "re-filings, extensions, closures or parent-company copies of already known matters; small filings with no business impact; corrections that do not change key terms",
        }),
    "triage": dict(
        type="choice",
        instructions="How should this disclosure be handled next? If `correction` is present, judge by what changed.",
        criteria={
            "PASS": "Clearly important from the text alone: an amount of KRW 3 billion or more is stated, a change to the business, control or capital structure, a clinical-trial event, a major lawsuit outcome, or a correction that materially changes key terms.",
            "PASS_CHECK": "Looks important, but the amount is undisclosed or below KRW 3 billion, so a ratio to equity or sales, or a year-over-year change, must be computed to decide; or the before/after of a correction must be compared.",
            "HOLD": "Needs a human decision: a large amount but routine treasury management or refinancing, or the evidence for importance conflicts.",
            "DROP": "Routine or administrative filings, re-filings, extensions, closures or copies of known matters, small filings with no impact, corrections that do not change key terms.",
        }),
    "importance": dict(
        type="score",
        instructions="How important is this disclosure to an investor?",
        criteria=[
            "Routine, administrative or small. Irrelevant to investment decisions.",
            "For reference only. A re-filing, extension or closure of a known matter, or almost no impact.",
            "Worth knowing, but the impact is small or uncertain.",
            "Meaningful impact: an amount of KRW 3 billion or more, or a change to the business.",
            "Large impact: large relative to sales or equity, or a fundamental change to the business, control or capital structure.",
        ]),
    "big_amount": dict(type="noul", instructions="Does the text state an amount of KRW 3 billion or more (contract, guarantee, investment, equity injection, loan, disposal, acquisition)? If the amount is undisclosed or below KRW 3 billion, answer no."),
    "business_shift": dict(type="noul", instructions="Is this a decision or event that changes the company's business, governance or capital structure (split, merger, new business, acquisition, sale, control dispute)?"),
    "bio_clinical": dict(type="noul", instructions="Is this about a drug or biotech development stage such as a clinical trial, approval or permit? Approval of a changed trial plan also counts."),
    "rumor_first": dict(type="noul", instructions="Is this the company's first response to a report or rumor about an unconfirmed major matter (acquisition, listing, large investment, contract)? A repeat of an earlier response, or a response closing a confirmed outcome, is no."),
    "routine_admin": dict(type="noul", instructions="Is this a routine, administrative or governance filing that recurs by law or custom (record date, regular director appointment, committee meeting, report publication, effectiveness notice, treasury refinancing)?"),
    "repeat_known": dict(type="noul", instructions="Is this a re-filing, term extension, closure of an outcome, or parent-company copy of an already known matter?"),
    "needs_comparison": dict(type="noul", instructions="Is the amount undisclosed or below KRW 3 billion, such that a ratio to equity or sales, or a year-over-year change, must be computed to know its importance?"),
    "material_change": dict(type="noul", instructions="Does `correction` show a substantive change to amount, period, counterparty, quantity or terms? If there is no `correction`, answer no."),
}


# ---------------------------------------------------------------------------------------------
# v1: v0 시험(w0907_v0)에서 드러난 빈틈을 '이미 문서화된 원칙'으로 메운 개정판 (표본에 맞춘 튜닝이 아님)
#   - 월간 영업(잠정)실적은 전년 동월 ±10% 이상일 때만 (P5)
#   - 금액이 큰 보증·대여·출자의 연장·대환은 통과 (P2 예외)
#   - 정정은 금액 ±10% 이상 → 통과, 변동분 30억 원 이상 → 통과·확인, 일정·오기·문구 → 탈락 (P6)
#   - 전처리(lib.py): 원 단위 숫자에 '(약 N억 원)' 병기, 정정 전·후 증감 계산을 correction_delta로 전달
# ---------------------------------------------------------------------------------------------
import copy


def _v1(base, lang):
    q = copy.deepcopy(base)
    if lang == "ko":
        q["proceed"]["criteria"]["true"] += (", 월간 영업(잠정)실적 공정공시는 전년 동월 대비 ±10% 이상일 때만 해당, "
                                             "금액이 30억 원 이상인 보증·대여·출자의 기간 연장·대환도 해당, "
                                             "정정은 `correction_delta`에서 금액이 ±10% 이상 바뀌었거나 변동분이 30억 원 이상일 때만 해당")
        q["proceed"]["criteria"]["false"] += (", 전년 동월 대비 ±10% 미만의 월간 영업(잠정)실적, "
                                              "일정·기간·오기·문구만 고친 정정이거나 금액 변동이 30억 원 미만인 정정")
        q["triage"]["criteria"]["PASS"] += " 월간 실적은 본문에 전년 동월 대비 ±10% 이상으로 명시된 경우. 정정은 금액이 ±10% 이상 바뀐 경우."
        q["triage"]["criteria"]["PASS_CHECK"] += " 정정은 금액 변동분이 30억 원 이상이나 10% 미만이거나, 계약상대·판매지역이 바뀌었거나, 거래 종결·소송 제기 같은 후속인 경우."
        q["triage"]["criteria"]["DROP"] += " 전년 동월 대비 ±10% 미만의 월간 실적. 일정·기간·오기·문구만 고친 정정, 금액 변동이 30억 원 미만인 정정, 자회사 사본."
        q["repeat_known"]["instructions"] = ("이미 알려진 사안의 재공시·결과 종결·모회사 사본, 또는 금액이 30억 원 미만인 기간 연장인가? "
                                             "금액이 30억 원 이상인 보증·대여·출자의 기간 연장·대환은 새 약정이므로 아니오.")
        q["material_change"]["instructions"] = ("`correction_delta`에서 어느 금액 항목이든 ±10% 이상 바뀌었거나 변동 금액이 30억 원 이상인가, "
                                                "또는 계약상대·판매지역·사업 구조가 바뀌었는가? 일정·기간·오기·문구 정정이면 아니오.")
        q["monthly_results"] = dict(type="noul", instructions="월간 영업(잠정)실적 또는 월간 판매 실적을 알리는 공정공시인가?")
        q["yoy_big"] = dict(type="noul", instructions="본문에 전년 동월 대비 증감률이 +10% 이상이거나 -10% 이하로 명시되어 있는가? 증감률이 없거나 ±10% 미만이면 아니오.")
    else:
        q["proceed"]["criteria"]["true"] += ("; a monthly operating (preliminary) results notice only when it is up or down 10% or more year over year; "
                                             "extensions or refinancing of guarantees, loans or equity commitments of KRW 3 billion or more; "
                                             "a correction only when `correction_delta` shows an amount changed by 10% or more, or by KRW 3 billion or more")
        q["proceed"]["criteria"]["false"] += ("; a monthly results notice within 10% year over year; "
                                              "a correction that only fixes dates, periods, typos or wording, or changes an amount by less than KRW 3 billion")
        q["triage"]["criteria"]["PASS"] += " Monthly results stated as 10% or more year over year. A correction that changes an amount by 10% or more."
        q["triage"]["criteria"]["PASS_CHECK"] += " A correction with an amount change of KRW 3 billion or more but under 10%, a changed counterparty or region, or a follow-up such as closing a deal or filing a lawsuit."
        q["triage"]["criteria"]["DROP"] += " Monthly results within 10% year over year. Corrections that only fix dates, periods, typos or wording, change an amount by less than KRW 3 billion, or are subsidiary copies."
        q["repeat_known"]["instructions"] = ("Is this a re-filing, closure of an outcome or parent-company copy of an already known matter, or a term extension of less than KRW 3 billion? "
                                             "Extensions or refinancing of guarantees, loans or equity commitments of KRW 3 billion or more are new commitments, so answer no.")
        q["material_change"]["instructions"] = ("Does `correction_delta` show any amount changed by 10% or more or by KRW 3 billion or more, "
                                                "or a changed counterparty, region or business structure? Corrections of dates, periods, typos or wording are no.")
        q["monthly_results"] = dict(type="noul", instructions="Is this a fair-disclosure notice of monthly operating (preliminary) or sales results?")
        q["yoy_big"] = dict(type="noul", instructions="Does the text state a year-over-year change of +10% or more, or -10% or less? If no change is stated or it is within 10%, answer no.")
    q["proceed"]["instructions"] = q["proceed"]["instructions"].replace("`correction`이 있으면 정정 전후 변경 내용을", "`correction_delta`가 있으면 정정 전후 변경 내용을").replace("If `correction` is present", "If `correction_delta` is present")
    return q


QUESTIONS = {"v0": {"ko": KO, "en": EN}, "v1": {"ko": _v1(KO, "ko"), "en": _v1(EN, "en")}}


from questions_v2 import QUESTIONS_V2  # noqa: E402
QUESTIONS["v2"] = QUESTIONS_V2


# v2b = v2 + Q1 예외: 정례 자금운용·배당·금융회사 일상 거래라도 금액이 매우 크면(가정: 1,000억 원 이상) 통과·확인
import copy as _copy


def _v2b(base, lang):
    q = _copy.deepcopy(base)
    if lang == "en":
        q["proceed"]["criteria"]["true"] += "; routine treasury management, a dividend or everyday financial-company business, ONLY when the amount is extremely large (KRW 100 billion or more)"
        q["triage"]["criteria"]["PASS_CHECK"] += " Also routine treasury management, a dividend or everyday financial-company business whose amount is extremely large (KRW 100 billion or more)."
    else:
        q["proceed"]["criteria"]["true"] += "; 여유자금 운용·배당·금융회사 일상 영업이라도 금액이 매우 큰 경우(1,000억 원 이상)에 한해"
        q["triage"]["criteria"]["PASS_CHECK"] += " 또한 여유자금 운용·배당·금융회사 일상 영업이라도 금액이 매우 큰 경우(1,000억 원 이상)."
    return q


QUESTIONS["v2b"] = {"en": _v2b(QUESTIONS_V2["en"], "en"), "ko": _v2b(QUESTIONS_V2["ko"], "ko")}


from questions_v3 import QUESTIONS_V3  # noqa: E402
QUESTIONS["v3"] = {"en": QUESTIONS_V3}
