"""질문 v2 — 사용자 정책 답변(Q1~Q12, 2026-10-08)을 질문에 옮긴 판. 근거는 공시판단_기본원칙.md 의 v0.3.

v1 대비 변경
  - 신규 금액(30억↑)만 통과: 보증·대여·출자의 연장·대환·차환은 제외 (Q2)
  - 금융회사(증권·은행·보험·카드·캐피탈)의 보증·대여·수익증권·차입은 일상 영업이라 탈락 (Q2)
  - 풍문 해명·조회공시 답변("확정된 바 없다")은 탈락 (Q3)
  - 보호예수 해제·금액 비공개 의무공시·중대재해는 통과·확인, 임상·법원 판결·불성실공시법인 지정은 통과 (Q4·Q7·Q8)
  - 정정은 계약 해지 또는 증감액 200억 원 이상(1% 이상)일 때만 통과·확인 (Q6, 200억은 잠정)
  - HOLD = 알릴 가치는 있으나 심화 분석은 필요 없는 사건(예: 공기업 대표이사 교체) 또는 규칙 충돌 (Q9, 사람 사용례)
  - 분쟁 리스트 회사는 state의 company_context 로 맥락을 넘긴다 (Q11)
"""
import copy

EN = {
    "proceed": dict(
        type="noul",
        instructions="Is this Korean regulatory disclosure important enough for an investor that it should be passed on to deeper analysis? "
                     "Apply the policy in the criteria. If `correction_delta` is present, judge by what changed. "
                     "If `company_context` is present, take it into account. If `sector_note` is present, take it into account.",
        criteria={
            "true": "A NEW commitment of KRW 3 billion or more (contract, guarantee, loan, investment, equity injection, disposal, acquisition); "
                    "a contract whose amount is withheld for confidentiality but that is a mandatory disclosure (for example defense); "
                    "a decision that changes the business, governance or capital structure (split, merger, takeover, control dispute); "
                    "a biotech clinical-trial or approval event, including approval of a changed trial plan; a court ruling or legal sanction outcome; "
                    "designation as an unfaithful-disclosure corporation; a fatal workplace accident; expiry of a lock-up; "
                    "monthly results only when up or down 10% or more year over year; "
                    "a correction only when the contract is dissolved or an amount changes by KRW 20 billion or more",
            "false": "Routine or administrative filings (record dates, regular director appointments, committee meetings, report publication, effectiveness notices); "
                     "a response to a press report or rumor, especially 'nothing has been decided', and any re-filing of a known matter; "
                     "extension, refinancing or rollover of an existing guarantee, loan or borrowing; routine treasury management and dividends; "
                     "everyday business of financial companies (securities, banks, insurers, card, capital) such as guarantees, loans, beneficiary certificates and borrowings; "
                     "a correction that only changes dates, periods, names, typos or a modest amount; a copy of a subsidiary's filing; "
                     "informational notices with no new commitment",
        }),
    "triage": dict(
        type="choice",
        instructions="How should this disclosure be handled next? If `correction_delta` is present, judge by what changed. "
                     "If `company_context` or `sector_note` is present, take it into account.",
        criteria={
            "PASS": "Clearly important from the text alone: a NEW commitment of KRW 3 billion or more, a change to the business, control or capital structure, "
                    "a biotech clinical-trial event, a court ruling, designation as an unfaithful-disclosure corporation, or monthly results up or down 10% or more year over year.",
            "PASS_CHECK": "Probably important but something must be checked or computed downstream: the amount is withheld for confidentiality in a mandatory disclosure; "
                          "a ratio or year-over-year change must be computed; a fatal workplace accident; a lock-up expiry (size to check); "
                          "a correction that dissolves a contract or changes an amount by KRW 20 billion or more; or you are genuinely unsure.",
            "HOLD": "A notable event worth notifying but needing no deeper analysis (for example a CEO change at a state-owned company), or two rules conflict and a human must decide.",
            "DROP": "Routine or administrative filings; responses to rumors or reports with nothing confirmed; re-filings; extensions, refinancing or rollovers; "
                    "routine treasury management and dividends; everyday business of financial companies; monthly results within 10% year over year or only marginally above; "
                    "corrections of dates, periods, names, typos or modest amounts; subsidiary copies; informational notices.",
        }),
    "importance": dict(
        type="score",
        instructions="How important is this disclosure to an investor?",
        criteria=[
            "Routine, administrative, small, or everyday business of a financial company. Irrelevant to investment decisions.",
            "For reference only. A re-filing, extension, refinancing, rumor response, or almost no impact.",
            "Worth knowing, but the impact is small or uncertain.",
            "Meaningful impact: a new commitment of KRW 3 billion or more, or a change to the business.",
            "Large impact: large relative to sales or equity, or a fundamental change to the business, control or capital structure.",
        ]),
    "new_big_amount": dict(type="noul", instructions="Does the text state a NEW commitment of KRW 3 billion or more (contract, guarantee, loan, investment, equity injection, disposal, acquisition)? Extension, refinancing or rollover of an existing one, an undisclosed amount, or an amount below KRW 3 billion is no."),
    "business_shift": dict(type="noul", instructions="Is this a decision or event that changes the company's business, governance or capital structure (split, merger, takeover, sale, control dispute)?"),
    "bio_clinical": dict(type="noul", instructions="Is this about a drug or biotech development stage such as a clinical trial, approval or permit? Approval of a changed trial plan also counts."),
    "legal_event": dict(type="noul", instructions="Is this a court ruling, a legal sanction outcome, or designation as an unfaithful-disclosure corporation?"),
    "lockup_release": dict(type="noul", instructions="Is this about the expiry or release of a lock-up (mandatory holding period) on shares?"),
    "fatal_accident": dict(type="noul", instructions="Is this about a fatal or serious workplace accident?"),
    "undisclosed_amount": dict(type="noul", instructions="Is this a contract whose amount is withheld for confidentiality but that was disclosed because it exceeds a mandatory threshold?"),
    "rumor_response": dict(type="noul", instructions="Is this a company's response to a press report, rumor or exchange inquiry, including repeated responses saying nothing has been decided?"),
    "routine_admin": dict(type="noul", instructions="Is this a routine, administrative or governance filing that recurs by law or custom (record date, regular director appointment, committee meeting, report publication, effectiveness notice), or routine treasury management or a dividend?"),
    "repeat_known": dict(type="noul", instructions="Is this a re-filing, closure of an outcome, parent-company copy, or an extension, refinancing or rollover of an already known matter?"),
    "financial_routine": dict(type="noul", instructions="Is this an everyday-business transaction of a financial company (securities, bank, insurer, card, capital), such as a guarantee, loan, beneficiary-certificate trade or borrowing? If `sector_note` is absent, answer no."),
    "needs_comparison": dict(type="noul", instructions="Is the amount undisclosed or below KRW 3 billion, such that a ratio to equity or sales, or a year-over-year change, must be computed to know its importance?"),
    "monthly_results": dict(type="noul", instructions="Is this a fair-disclosure notice of monthly operating (preliminary) or sales results?"),
    "yoy_big": dict(type="noul", instructions="Does the text state a year-over-year change of +10% or more, or -10% or less? If no change is stated or it is within 10%, answer no."),
    "material_change": dict(type="noul", instructions="Does `correction_delta` show an amount changed by KRW 20 billion or more, or does the correction dissolve a contract? Corrections of dates, periods, names, typos or modest amounts are no."),
}

KO = {
    "proceed": dict(
        type="noul",
        instructions="이 공시는 투자자에게 중요해서 심화 분석 단계로 넘겨야 하는가? criteria의 정책을 적용한다. "
                     "`correction_delta`가 있으면 정정 전후 변경 내용을, `company_context`·`sector_note`가 있으면 그 맥락을 반영한다.",
        criteria={
            "true": "금액 30억 원 이상의 신규 약정(계약·보증·대여·투자·출자·처분·취득); 금액은 비공개이나 의무 공시인 계약(방산 등); "
                    "사업·지배구조·자본구조를 바꾸는 결정(분할·합병·인수·매각·경영권 분쟁); 임상·허가 등 바이오 개발 사건(임상계획 변경 승인 포함); "
                    "법원 판결·제재 결과; 불성실공시법인 지정; 중대재해; 보호예수 해제; 전년 동월 대비 ±10% 이상인 월간 실적; "
                    "계약 해지 또는 증감액 200억 원 이상인 정정",
            "false": "기준일 설정·정기 이사 선임·위원회 개최·보고서 발간·효력발생 안내 같은 정례·행정 공시; 풍문·보도·조회공시에 대한 '확정된 바 없다'류 답변과 모든 재공시; "
                     "기존 보증·대여·차입의 연장·대환·차환; 여유자금 운용·배당; 금융회사(증권·은행·보험·카드·캐피탈)의 보증·대여·수익증권·차입 같은 일상 영업; "
                     "일정·기간·명칭·오기 또는 소액 변동만 고친 정정; 자회사 공시 사본; 새 약정이 없는 정보성 공시",
        }),
    "triage": dict(
        type="choice",
        instructions="이 공시를 다음 단계로 어떻게 처리해야 하는가? `correction_delta`·`company_context`·`sector_note`가 있으면 반영한다.",
        criteria={
            "PASS": "본문만으로 중요하다고 판단된다: 금액 30억 원 이상의 신규 약정, 사업·지배·자본구조 변화, 바이오 임상 사건, 법원 판결, 불성실공시법인 지정, 전년 동월 대비 ±10% 이상의 월간 실적.",
            "PASS_CHECK": "중요해 보이나 다음 단계에서 확인·계산이 필요하다: 금액 비공개 의무공시, 비율·전년 동월비 계산 필요, 중대재해, 보호예수 해제(규모 확인), "
                          "계약 해지 또는 200억 원 이상 금액 변동 정정, 또는 정말 모르겠는 경우.",
            "HOLD": "알릴 가치는 있으나 심화 분석은 필요 없는 사건(예: 공기업 대표이사 교체), 또는 규칙이 충돌해 사람이 정해야 하는 경우.",
            "DROP": "정례·행정 공시; 확정된 바 없는 풍문·조회공시 답변; 재공시; 연장·대환·차환; 여유자금 운용·배당; 금융회사의 일상 영업; "
                    "전년 동월 대비 ±10% 미만이거나 겨우 넘는 월간 실적; 일정·기간·명칭·오기·소액 정정; 자회사 사본; 정보성 공시.",
        }),
    "importance": dict(
        type="score",
        instructions="이 공시가 투자자에게 주는 중요도는 어느 단계인가?",
        criteria=[
            "정례·행정·소액이거나 금융회사의 일상 영업이다. 투자 판단과 무관하다.",
            "참고 수준이다. 재공시·연장·대환·풍문 답변이거나 영향이 거의 없다.",
            "알아둘 만한 이슈지만 영향이 작거나 불확실하다.",
            "의미 있는 영향이 있다. 30억 원 이상의 신규 약정이거나 사업에 변화가 생긴다.",
            "큰 영향이 있다. 매출·자기자본 대비 비중이 크거나 사업·지배·자본구조가 근본적으로 바뀐다.",
        ]),
    "new_big_amount": dict(type="noul", instructions="본문에 30억 원 이상의 신규 약정(계약·보증·대여·투자·출자·처분·취득)이 명시되어 있는가? 기존 약정의 연장·대환·차환, 금액 비공개, 30억 원 미만이면 아니오."),
    "business_shift": dict(type="noul", instructions="회사의 사업, 지배구조, 자본구조를 바꾸는 결정이나 사건(분할·합병·인수·매각·경영권 분쟁)인가?"),
    "bio_clinical": dict(type="noul", instructions="임상시험, 허가, 승인 등 의약품·바이오 개발 단계에 관한 공시인가? 임상계획 변경 승인도 포함한다."),
    "legal_event": dict(type="noul", instructions="법원 판결, 법적 제재 결과 또는 불성실공시법인 지정인가?"),
    "lockup_release": dict(type="noul", instructions="주식의 보호예수(의무보유) 해제에 관한 공시인가?"),
    "fatal_accident": dict(type="noul", instructions="사망 등 중대한 산업재해에 관한 공시인가?"),
    "undisclosed_amount": dict(type="noul", instructions="금액은 경영상 비밀유지로 비공개이나 의무 공시 기준을 넘어 공시된 계약인가?"),
    "rumor_response": dict(type="noul", instructions="언론 보도·풍문·거래소 조회에 대한 회사의 답변인가? '결정된 바 없다'는 반복 답변도 포함한다."),
    "routine_admin": dict(type="noul", instructions="법·제도상 반복되는 정례·행정·거버넌스 공시(기준일 설정, 정기 이사 선임, 위원회 개최, 보고서 발간, 효력발생 안내)이거나 여유자금 운용·배당인가?"),
    "repeat_known": dict(type="noul", instructions="이미 알려진 사안의 재공시·결과 종결·모회사 사본이거나 기존 약정의 기간 연장·대환·차환인가?"),
    "financial_routine": dict(type="noul", instructions="금융회사(증권·은행·보험·카드·캐피탈)의 보증·대여·수익증권 거래·차입 같은 일상 영업 거래인가? `sector_note`가 없으면 아니오."),
    "needs_comparison": dict(type="noul", instructions="금액이 비공개이거나 30억 원 미만이지만, 자기자본·매출 대비 비율이나 전년 동월 대비 증감을 계산해야 중요도를 알 수 있는가?"),
    "monthly_results": dict(type="noul", instructions="월간 영업(잠정)실적 또는 월간 판매 실적을 알리는 공정공시인가?"),
    "yoy_big": dict(type="noul", instructions="본문에 전년 동월 대비 증감률이 +10% 이상이거나 -10% 이하로 명시되어 있는가? 증감률이 없거나 ±10% 미만이면 아니오."),
    "material_change": dict(type="noul", instructions="`correction_delta`에서 금액이 200억 원 이상 바뀌었거나 계약이 해지되는가? 일정·기간·명칭·오기·소액 변동 정정이면 아니오."),
}

QUESTIONS_V2 = {"en": EN, "ko": KO}
