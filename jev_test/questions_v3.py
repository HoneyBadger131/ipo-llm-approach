"""질문 v3 (운영안) — 정책 v0.3 + 2차 사용자 결정(N1~N9). 질문은 2개, 영어(영어가 한국어보다 일관되게 나았다).

  proceed (Noul)   : 다음 단계로 넘길 만큼 중요한가 — 확률을 임계값(시총 구간별)으로 자른다
  triage  (Choice): PASS / PASS_CHECK / NOTIFY / HOLD / DROP — 진행 쪽 라벨의 종류를 정한다

하드 규칙(rules_core.py)이 이미 확정한 유형(정정, 풍문, 중대재해, 불성실공시, 대표이사 변경, 절차성 합병, 보호예수, 신탁 해지,
금융회사 일상 거래)은 Jev에 보내지 않는다. 따라서 아래 질문은 그 외 유형만 다룬다.
state 필드: title, company, body, [company_context(분쟁 리스트)], [sector_note(금융회사)], [cap_note(시총 상위 30)]
"""

QUESTIONS_V3 = {
    "proceed": dict(
        type="noul",
        instructions="Is this Korean regulatory disclosure important enough for an investor that it should be passed on to deeper analysis? "
                     "Apply the policy in the criteria. If `company_context`, `sector_note` or `cap_note` is present, take it into account.",
        criteria={
            "true": "A NEW commitment of KRW 3 billion or more (contract, guarantee, loan, investment, equity injection, disposal, acquisition); "
                    "a contract whose amount is withheld for confidentiality but that is a mandatory disclosure (for example defense); "
                    "a decision that changes the business, governance or capital structure (split, large merger or takeover, sale, control dispute); "
                    "a biotech clinical-trial or approval event, including approval of a changed trial plan; a court ruling or legal sanction outcome; "
                    "monthly results only when up or down 10% or more year over year; "
                    "a forecast or value-up plan only when its figures change by 15% or more from the previous one; "
                    "an officer or major-shareholder trading plan only when it affects control or governance (control change, large block, exchangeable-bond issuance by a major shareholder); "
                    "routine treasury management, a dividend or everyday financial-company business only when the amount is extremely large (KRW 100 billion or more)",
            "false": "Routine or administrative filings (record dates, regular director appointments, committee meetings, report publication, effectiveness notices); "
                     "any re-filing, and extension, refinancing or rollover of an existing guarantee, loan or borrowing; "
                     "routine treasury management and dividends; everyday business of financial companies (securities, banks, insurers, card, capital) such as guarantees, loans, beneficiary certificates and borrowings; "
                     "a forecast or value-up plan with small changes; an officer trading plan without governance impact; "
                     "a monthly result within 10% year over year or only marginally above; a copy of a subsidiary's filing; informational notices with no new commitment",
        }),
    "triage": dict(
        type="choice",
        instructions="How should this disclosure be handled next? If `company_context`, `sector_note` or `cap_note` is present, take it into account.",
        criteria={
            "PASS": "Clearly important from the text alone: a NEW commitment of KRW 3 billion or more, a change to the business, control or capital structure, "
                    "a biotech clinical-trial event, a court ruling, or monthly results up or down 10% or more year over year.",
            "PASS_CHECK": "Probably important but something must be checked or computed downstream: the amount is withheld for confidentiality in a mandatory disclosure; "
                          "a ratio or year-over-year change must be computed; a forecast or plan that may differ 15% or more from the previous one; "
                          "an extremely large (KRW 100 billion or more) treasury, dividend or financial-company item; or you are genuinely unsure.",
            "NOTIFY": "A notable event worth telling the reader but needing no deeper analysis, such as a board or director change at a company flagged in `company_context` (proxy-fight watchlist). Routine director appointments at ordinary companies are DROP, not NOTIFY.",
            "HOLD": "Two rules conflict and a human must decide.",
            "DROP": "Routine or administrative filings; re-filings; extensions, refinancing or rollovers; routine treasury management and dividends; "
                    "everyday business of financial companies; monthly results within 10% year over year or only marginally above; "
                    "forecasts or plans with small changes; officer trading plans without governance impact; subsidiary copies; informational notices.",
        }),
}
