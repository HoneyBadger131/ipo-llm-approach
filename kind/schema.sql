-- KIND 축 DB 스키마 v1 (SQLite >= 3.37, STRICT)
-- 설계 원칙 (docs/KIND_DESIGN.md §6 참조)
--  1. 모든 "날짜"는 ISO 'YYYY-MM-DD' TEXT(KST 기준 달력일)이며 calendar_day(cal_date)를 FK로 가리킨다.
--     → 영업일 연산(T+n, 직전/다음 영업일, 구간)은 전부 calendar_day 조인으로만 한다. 코드 곳곳에서 휴장일을 따로 계산하지 않는다.
--  2. 종목은 코드(단축코드/표준코드)를 PK로 쓰지 않는다. 코드는 바뀐다(분할·병합·재상장·우선주 신설·ETF 알파뉴메릭 코드).
--     security.security_id(대리키)가 PK이고, 코드는 security_code(유효기간 있는 이력)에서 해석한다.
--     법인(issuer)과 증권(security)을 분리: 한 법인에 보통주/우선주 등 여러 증권.
--  3. 원천 공시는 filing(접수번호 PK)에 불변으로 적재하고, 파생 사실(events, share_ledger, designation, etf_*)은 모두 source_filing_id 로 되짚을 수 있어야 한다.
--  4. 정정/재안내는 덮어쓰지 않는다: 값마다 (source_filing_id, superseded_by)를 가진다.

PRAGMA foreign_keys = ON;

-- ───────────── 0. 메타 ─────────────
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
) STRICT;

-- ───────────── 1. 메인 캘린더 (달력일 전체, 영업일 여부는 속성) ─────────────
CREATE TABLE IF NOT EXISTS calendar_day (
  cal_date          TEXT PRIMARY KEY CHECK (cal_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  year              INTEGER NOT NULL,
  month             INTEGER NOT NULL,
  dow               INTEGER NOT NULL CHECK (dow BETWEEN 1 AND 7),     -- 1=월 … 7=일 (ISO)
  is_weekend        INTEGER NOT NULL CHECK (is_weekend IN (0,1)),
  is_trading        INTEGER NOT NULL CHECK (is_trading IN (0,1)),     -- KRX 정규 매매일
  day_type          TEXT NOT NULL CHECK (day_type IN ('trading','weekend','holiday')),
  holiday_name      TEXT,
  source            TEXT NOT NULL CHECK (source IN ('xkrx','override','weekday_only')),
  confidence        TEXT NOT NULL CHECK (confidence IN ('verified','unverified')),  -- unverified: 라이브러리 범위 밖(평일=영업일로 가정)
  open_kst          TEXT,                                              -- 'HH:MM' (수능일·신정 개장 지연 등 반영). 비영업일 NULL
  close_kst         TEXT,
  tseq              INTEGER NOT NULL,                                  -- 이 날짜까지(포함)의 누적 영업일 수. 비영업일은 직전 영업일의 값
  prev_trading_date TEXT,                                              -- 엄격히 이전 영업일
  next_trading_date TEXT,                                              -- 엄격히 이후 영업일
  week_start        TEXT NOT NULL,                                     -- 해당 주 월요일
  ym                TEXT NOT NULL                                      -- 'YYYY-MM'
) STRICT;
CREATE INDEX IF NOT EXISTS ix_cal_tseq    ON calendar_day(tseq) WHERE is_trading = 1;
CREATE INDEX IF NOT EXISTS ix_cal_trading ON calendar_day(is_trading, cal_date);

-- 라이브러리(exchange_calendars XKRX)가 틀리거나 비어 있는 날의 수동 보정. 빌드 시 라이브러리 값보다 항상 우선.
CREATE TABLE IF NOT EXISTS calendar_override (
  cal_date   TEXT PRIMARY KEY,
  is_trading INTEGER NOT NULL CHECK (is_trading IN (0,1)),
  reason     TEXT NOT NULL,
  evidence   TEXT NOT NULL,                                            -- 예: 'DART 공시 0건', 'KRX 공지 URL'
  added_at   TEXT NOT NULL
) STRICT;

-- ───────────── 2. 법인·증권 (코드는 속성, PK는 대리키) ─────────────
CREATE TABLE IF NOT EXISTS issuer (
  issuer_id      INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  kind_isur_cd   TEXT UNIQUE,                                          -- KIND 내부 발행기관코드(예 '06950', 삼성전자 '00593'류). 검색 응답 isurcd
  dart_corp_code TEXT UNIQUE,                                          -- DART 8자리 → DART 축과 조인
  note           TEXT
) STRICT;

CREATE TABLE IF NOT EXISTS security (
  security_id  INTEGER PRIMARY KEY,
  issuer_id    INTEGER NOT NULL REFERENCES issuer(issuer_id),
  sec_type     TEXT NOT NULL CHECK (sec_type IN ('COMMON','PREFERRED','ETF','ETN','REIT','OTHER')),
  name         TEXT NOT NULL,                                          -- 현재(최신) 약명
  manager      TEXT,                                                   -- ETF 운용사 등(집계 키)
  market       TEXT,                                                   -- KOSPI / KOSDAQ / KONEX
  listed_date  TEXT REFERENCES calendar_day(cal_date),
  delisted_date TEXT REFERENCES calendar_day(cal_date),
  note         TEXT
) STRICT;
CREATE INDEX IF NOT EXISTS ix_security_issuer ON security(issuer_id);

-- 코드 이력: 같은 증권도 코드가 바뀐다. 해석은 (code_type, code, 기준일)로.
CREATE TABLE IF NOT EXISTS security_code (
  security_id INTEGER NOT NULL REFERENCES security(security_id),
  code_type   TEXT NOT NULL CHECK (code_type IN ('SHORT','ISIN','KIND_A')),   -- SHORT 6자(ETF 알파뉴메릭 포함), ISIN 12자, KIND_A = 'A'+SHORT
  code        TEXT NOT NULL,
  valid_from  TEXT NOT NULL DEFAULT '1900-01-01',
  valid_to    TEXT NOT NULL DEFAULT '9999-12-31',
  PRIMARY KEY (code_type, code, valid_from)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_security_code_sec ON security_code(security_id);

-- 증권 약명 이력 (ETF 개명, 회사 상호변경)
CREATE TABLE IF NOT EXISTS security_name_hist (
  security_id INTEGER NOT NULL REFERENCES security(security_id),
  name        TEXT NOT NULL,
  valid_from  TEXT NOT NULL,
  PRIMARY KEY (security_id, valid_from)
) STRICT;

-- 분석 대상(워치리스트). 단계 확장은 이 테이블 행 추가만으로.
CREATE TABLE IF NOT EXISTS watchlist (
  watch_name  TEXT NOT NULL,                                           -- 예 'phase1', 'kospi290', 'etf_core'
  security_id INTEGER NOT NULL REFERENCES security(security_id),
  added_at    TEXT NOT NULL,
  PRIMARY KEY (watch_name, security_id)
) STRICT;

-- ───────────── 3. 원천 공시 (불변) ─────────────
CREATE TABLE IF NOT EXISTS filing_type (
  cat_code   TEXT PRIMARY KEY,                                         -- 'MKT.0303' = 대분류.세부코드
  cat_major  TEXT NOT NULL,                                            -- 시장조치/수시공시/신고사항 …
  name       TEXT NOT NULL,
  module     TEXT                                                      -- 'M1'..'M5' 담당 모듈, 무시 대상은 NULL
) STRICT;

CREATE TABLE IF NOT EXISTS filing (
  filing_id    TEXT PRIMARY KEY,                                       -- 'KIND:20261008000511' / 'DART:20260814003375' (두 시스템 접수번호는 같은 문서도 번호가 다르고 충돌 가능 → 출처 접두)
  src          TEXT NOT NULL CHECK (src IN ('KIND','DART')),
  acpt_no      TEXT NOT NULL CHECK (length(acpt_no) = 14),             -- 원천 시스템의 접수번호 YYYYMMDDnnnnnn
  filed_at     TEXT NOT NULL,                                          -- 'YYYY-MM-DD HH:MM' (KST)
  filed_date   TEXT NOT NULL REFERENCES calendar_day(cal_date),
  issuer_id    INTEGER REFERENCES issuer(issuer_id),                   -- 대표 대상(시장 전체 공시는 NULL)
  security_id  INTEGER REFERENCES security(security_id),
  company_raw  TEXT,                                                   -- 목록에 표시된 이름 원문
  title        TEXT NOT NULL,
  cat_major    TEXT,                                                   -- 수집 경로의 대분류(수시공시/시장조치/ETF …). 세부 유형(cat_code)은 파서가 필요 시 채움
  cat_code     TEXT REFERENCES filing_type(cat_code),
  skip_reason  TEXT,                                                   -- parse_status='skipped' 사유(선물옵션/종속회사 …)
  body_path    TEXT,                                                   -- kind/data/raw/ 상대경로
  body_sha1    TEXT,
  fetched_at   TEXT,
  parse_status TEXT NOT NULL DEFAULT 'new' CHECK (parse_status IN ('new','parsed','skipped','failed','review'))
) STRICT;
CREATE INDEX IF NOT EXISTS ix_filing_date     ON filing(filed_date);
CREATE INDEX IF NOT EXISTS ix_filing_security ON filing(security_id, filed_date);
CREATE INDEX IF NOT EXISTS ix_filing_status   ON filing(parse_status);

-- 한 공시가 여러 증권을 다루는 경우(ETF 일괄공시, 대량매매내역)
CREATE TABLE IF NOT EXISTS filing_subject (
  filing_id   TEXT NOT NULL REFERENCES filing(filing_id),
  security_id INTEGER NOT NULL REFERENCES security(security_id),
  PRIMARY KEY (filing_id, security_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_filing_subject_sec ON filing_subject(security_id);

-- ───────────── 4. 이벤트(체인) — M1 / M2 ─────────────
CREATE TABLE IF NOT EXISTS event (
  event_id    INTEGER PRIMARY KEY,
  issuer_id   INTEGER NOT NULL REFERENCES issuer(issuer_id),
  security_id INTEGER REFERENCES security(security_id),                -- 특정 종목에 한정될 때(권리락 등)
  event_type  TEXT NOT NULL,                                           -- RIGHTS_ISSUE, BONUS_ISSUE, CAPITAL_REDUCTION, SPLIT_OFF(분할), MERGER, STOCK_CANCEL, DR_ISSUE, PAR_VALUE_CHANGE, HALT, RELIST, DIVIDEND_EX …
  status      TEXT NOT NULL CHECK (status IN ('planned','confirmed','done','cancelled')),
  title       TEXT,
  review_flag INTEGER NOT NULL DEFAULT 0,                              -- 반자동 검수 대상(체인 매칭 불확실)
  detail_json TEXT,                                                    -- 유형별 부가 값(기준가격, 사유 원문 등)
  thread_key  TEXT UNIQUE,                                             -- 스레드형 이벤트(유상증자 등)의 안정 키: '<유형>:<issuer_id>:<최초 결정일>'. 재실행 시 같은 event_id 로 재구성
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS ix_event_issuer ON event(issuer_id, event_type);

-- 이벤트의 날짜 슬롯 (role별 최신값만 current, 과거값은 superseded_by 로 보존)
CREATE TABLE IF NOT EXISTS event_date (
  event_date_id INTEGER PRIMARY KEY,
  event_id      INTEGER NOT NULL REFERENCES event(event_id),
  role          TEXT NOT NULL,                                         -- RESOLUTION(결의), FILING_EFFECTIVE, RECORD(기준일), EX_DATE(권리락), PAYMENT, ISSUE, LISTING, HALT_START, HALT_END, …
  the_date      TEXT NOT NULL REFERENCES calendar_day(cal_date),
  is_estimated  INTEGER NOT NULL DEFAULT 0,
  condition_note TEXT,                                                 -- '변경상장일' 처럼 날짜가 조건에 매인 경우
  source_filing_id TEXT NOT NULL REFERENCES filing(filing_id),
  superseded_by INTEGER REFERENCES event_date(event_date_id)           -- NULL = 현재 유효
) STRICT;
CREATE INDEX IF NOT EXISTS ix_event_date_the_date ON event_date(the_date) WHERE superseded_by IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_event_date_current ON event_date(event_id, role) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS event_filing (
  event_id INTEGER NOT NULL REFERENCES event(event_id),
  filing_id TEXT NOT NULL REFERENCES filing(filing_id),
  relation TEXT NOT NULL CHECK (relation IN ('initial','amend','follow','reference')),
  PRIMARY KEY (event_id, filing_id)
) STRICT;

-- 지수(패시브) 관점의 주식수 반영. 거래소 지수 방법론: 유상증자(주주배정)는 권리락일, 제3자배정은 신주 상장일에 주식수가 늘어난다.
-- share_ledger(상장주식수 = 시장에 상장된 수량)와 별개의 축이며, 신주 상장일이 오면 두 값이 같아진다.
CREATE TABLE IF NOT EXISTS index_share_adj (
  event_id       INTEGER NOT NULL REFERENCES event(event_id),
  security_id    INTEGER NOT NULL REFERENCES security(security_id),
  effective_date TEXT REFERENCES calendar_day(cal_date),                -- 지수 주식수 증가 적용일(권리락일 / 신주 상장일). 미정이면 NULL
  delta_shares   INTEGER NOT NULL,
  basis          TEXT NOT NULL CHECK (basis IN ('PLANNED','AS_OF_EFFECTIVE','ACTUAL')),  -- PLANNED=공시 예정수량, AS_OF_EFFECTIVE=적용일 시점의 공시 수량, ACTUAL=발행결과 수량
  is_estimated   INTEGER NOT NULL,                                      -- 적용일이 파생(기준일로부터 계산)이면 1
  source_filing_id TEXT REFERENCES filing(filing_id),
  note           TEXT,
  PRIMARY KEY (event_id, security_id)
) STRICT;

-- ───────────── 5. 주식수 변동 원장 — KIND 축의 핵심 산출물 ─────────────
CREATE TABLE IF NOT EXISTS share_ledger (
  ledger_id      INTEGER PRIMARY KEY,
  security_id    INTEGER NOT NULL REFERENCES security(security_id),
  effective_date TEXT NOT NULL REFERENCES calendar_day(cal_date),       -- 상장(변경상장)일 등 주식수가 실제 바뀌는 날
  delta_shares   INTEGER,                                               -- 증감(소각·감자는 음수)
  shares_before  INTEGER,                                               -- 변동 전(공시값 또는 직전 원장 잔고로 계산)
  shares_after   INTEGER,                                               -- 변동 후 상장주식수
  issue_date     TEXT REFERENCES calendar_day(cal_date),                -- 발행일/소각일(상장일과 다름)
  is_computed    INTEGER NOT NULL DEFAULT 0,                            -- 1 = before/after 를 원장 체인으로 계산(공시에 없음)
  reason         TEXT NOT NULL,                                         -- 추가상장(유상증자(DR)), 변경상장(주식소각) …
  event_id       INTEGER REFERENCES event(event_id),
  source_filing_id TEXT NOT NULL REFERENCES filing(filing_id),
  superseded_by  INTEGER REFERENCES share_ledger(ledger_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_ledger_sec_date ON share_ledger(security_id, effective_date);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_src ON share_ledger(security_id, effective_date, reason, source_filing_id);

-- ───────────── 6. 정지·경보 구간 — M3 ─────────────
CREATE TABLE IF NOT EXISTS designation (
  designation_id INTEGER PRIMARY KEY,
  security_id    INTEGER NOT NULL REFERENCES security(security_id),
  kind           TEXT NOT NULL CHECK (kind IN ('CAUTION','WARNING','RISK','OVERHEAT','SHORT_BAN','ADMIN','HALT','CAUTION_NOTICE','WARNING_NOTICE','RISK_NOTICE')),
  start_date     TEXT NOT NULL REFERENCES calendar_day(cal_date),       -- 지정 첫날(포함)
  end_date       TEXT REFERENCES calendar_day(cal_date),                -- 지정 **마지막 날(포함)**. 해제일(= 첫 비지정일)이 아니다. NULL = 종료일 미정
  end_is_estimated INTEGER NOT NULL DEFAULT 1,                          -- 1 = 공시상 예정/가능 최단 종료일(해제 공시로 확정되기 전)
  state          TEXT NOT NULL CHECK (state IN ('active','ended','cancelled')),
  open_source_filing_id  TEXT NOT NULL REFERENCES filing(filing_id),
  close_source_filing_id TEXT REFERENCES filing(filing_id),
  note           TEXT                                                   -- JSON: 사유·판단일·조건 등
) STRICT;
CREATE INDEX IF NOT EXISTS ix_desig_active ON designation(security_id, kind) WHERE state = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS ux_desig_key ON designation(security_id, kind, start_date);

-- ───────────── 7. 대량매매 — M4 ─────────────
CREATE TABLE IF NOT EXISTS block_trade (
  trade_date   TEXT NOT NULL REFERENCES calendar_day(cal_date),
  security_id  INTEGER NOT NULL REFERENCES security(security_id),
  market       TEXT NOT NULL,                                           -- 유가증권/코스닥
  volume       INTEGER,                                                 -- 종목거래량
  block_qty    INTEGER NOT NULL,                                        -- 대량매매수량
  block_ratio_pct REAL,                                                 -- 공시상 비율 = 대량매매수량/종목거래량 ×100
  note         TEXT NOT NULL,                                           -- 장종료후시간외바스켓 등
  source_filing_id TEXT NOT NULL REFERENCES filing(filing_id),
  PRIMARY KEY (trade_date, security_id, note, source_filing_id)
) STRICT;
-- 알림 기준(상장주식수 대비 0.5% 이상)은 share_ledger / etf_unit_change 의 당일 상장수량 조인으로 뷰에서 계산 (v_block_trade_alert)

-- ───────────── 8. ETF 설정/해지 — M5 ─────────────
-- 원천: ETF 전용 목록(공시+ > ETF…)의 'ETF 추가ㆍ변경상장신청서(수량변경)(일괄공시)'. 운용사 일괄 표에서 행 단위로 적재.
CREATE TABLE IF NOT EXISTS etf_unit_change (
  filing_id     TEXT NOT NULL REFERENCES filing(filing_id),
  security_id   INTEGER NOT NULL REFERENCES security(security_id),
  report_date   TEXT NOT NULL REFERENCES calendar_day(cal_date),       -- 보고일
  create_date   TEXT NOT NULL REFERENCES calendar_day(cal_date),       -- 설정 또는 환매일 (실거래 체결 기준일)
  listing_date  TEXT NOT NULL REFERENCES calendar_day(cal_date),       -- 추가/변경상장 예정일 (좌수가 상장좌수에 반영되는 날)
  reason        TEXT NOT NULL,                                         -- 설정 / 환매
  units_before  INTEGER NOT NULL,
  units_added   INTEGER NOT NULL,
  units_removed INTEGER NOT NULL,                                      -- 음수로 저장(공시 표기 그대로)
  net_change    INTEGER NOT NULL,                                      -- 신청수량 = 순증감
  units_after   INTEGER NOT NULL,
  superseded_by TEXT REFERENCES filing(filing_id),
  PRIMARY KEY (filing_id, security_id)
) STRICT;
CREATE INDEX IF NOT EXISTS ix_etf_sec_date ON etf_unit_change(security_id, create_date);

-- ───────────── 9. 뷰 ─────────────
-- 영업일 달력만
CREATE VIEW IF NOT EXISTS v_trading_day AS
  SELECT cal_date, tseq, prev_trading_date, next_trading_date, open_kst, close_kst FROM calendar_day WHERE is_trading = 1;

-- 현재 유효한 이벤트 날짜 + 영업일 보정
CREATE VIEW IF NOT EXISTS v_event_calendar AS
  SELECT d.the_date, c.is_trading, c.next_trading_date, e.event_id, e.issuer_id, e.security_id, e.event_type, e.status,
         d.role, d.is_estimated, d.condition_note, d.source_filing_id
  FROM event_date d
  JOIN event e USING (event_id)
  JOIN calendar_day c ON c.cal_date = d.the_date
  WHERE d.superseded_by IS NULL AND e.status <> 'cancelled';

-- ETF 일별 좌수 시계열 (create_date 기준, 같은 날 복수 공시는 마지막 것)
CREATE VIEW IF NOT EXISTS v_etf_units_daily AS
  SELECT security_id, create_date AS cal_date, units_after, net_change, listing_date
  FROM etf_unit_change WHERE superseded_by IS NULL;
