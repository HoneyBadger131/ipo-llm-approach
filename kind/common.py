"""KIND 축 공용 함수(날짜·달력 연산). DB 연결 외 부작용 없음."""


def dday(con, asof, d):
    """기준일 대비 영업일 D-day 표기. 휴장일은 '*'."""
    a = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (asof,)).fetchone()[0]
    b = con.execute("SELECT tseq FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]
    n = b - a
    nt = con.execute("SELECT is_trading FROM calendar_day WHERE cal_date=?", (d,)).fetchone()[0]
    if d == asof:
        return "D-day"
    return (f"D-{n}" if n > 0 else (f"D+{-n}" if n < 0 else "D-day")) + ("" if nt else "*")
