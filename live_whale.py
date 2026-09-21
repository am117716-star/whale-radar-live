#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
رادار الحيتان — النسخة 3 (live_whale.py)
حوت رافع (مو مدافع) + مثلث صاعد/قاعدة ضيقة + فلاتر: اتجاه يومي، RSI، مسافة للمقاومة،
تأكيد الشمعة التالية، نافذة وقت، تنبيه واحد لكل سهم باليوم، شرعية مدمجة، حارس أرباح،
سجل تنبيهات + تقييم عند الإقفال (--evaluate).
يعمل على GitHub Actions مع yfinance + ntfy. مجاني بالكامل.
"""
import os, sys, json, math, time, csv, datetime as dt, urllib.request
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

VERSION = "3.0.1"

# ============================ القائمة (100 سهم) ============================
WATCHLIST = [
    # التقنية الكبرى والبرمجيات
    "AAPL", "MSFT", "GOOGL", "META", "AMZN", "TSLA", "NVDA", "ADBE", "CRM", "ORCL",
    "NOW", "SNOW", "PLTR", "SHOP", "UBER", "ABNB", "TEAM", "WDAY", "DDOG", "NET",
    "CRWD", "ZS", "PANW", "FTNT", "INTU",
    # الشرائح وأشباه الموصلات
    "AMD", "AVGO", "MU", "INTC", "QCOM", "TXN", "ADI", "LRCX", "AMAT", "KLAC",
    "ASML", "TSM", "SMCI", "ARM", "MRVL", "ON", "NXPI", "MPWR", "CDNS", "SNPS",
    # السيارات الكهربائية
    "XPEV", "NIO", "LI", "RIVN", "LCID",
    # الصحة والأدوية والأجهزة الطبية
    "LLY", "JNJ", "ABBV", "MRK", "PFE", "AMGN", "GILD", "VRTX", "REGN", "ISRG",
    "MDT", "SYK", "BSX", "ZTS", "DHR",
    # الاستهلاكية والتجزئة
    "PG", "KO", "PEP", "COST", "WMT", "HD", "NKE", "SBUX", "LULU", "TJX",
    "ORLY", "AZO",
    # الطاقة والمواد
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "HAL", "FCX", "LIN", "SCCO",
    # الصناعة
    "CAT", "DE", "HON", "UNP", "GE", "ETN", "EMR", "PH",
    # بنية تحتية تقنية
    "DELL", "CSCO", "IBM", "ANET", "VRT",
]

# الشرعية (فحص Zoya بمعيار AAOIFI — 20 سبتمبر 2026) + السوق. "haram" يُستبعد نهائيًا.
# "doubtful" = مشكوك عند Zoya → يُرسل مع تحذير (غيّر DOUBTFUL_MODE إلى "skip" لاستبعاده).
HALAL = {
    "AAPL":("halal","NASDAQ"), "MSFT":("doubtful","NASDAQ"), "GOOGL":("doubtful","NASDAQ"), "META":("doubtful","NASDAQ"), "AMZN":("doubtful","NASDAQ"),
    "TSLA":("halal","NASDAQ"), "NVDA":("halal","NASDAQ"), "ADBE":("halal","NASDAQ"), "CRM":("halal","NYSE"), "ORCL":("halal","NYSE"),
    "NOW":("halal","NYSE"), "SNOW":("halal","NYSE"), "PLTR":("doubtful","NASDAQ"), "SHOP":("halal","NYSE"), "UBER":("halal","NYSE"),
    "ABNB":("haram","NASDAQ"), "TEAM":("halal","NASDAQ"), "WDAY":("halal","NASDAQ"), "DDOG":("haram","NASDAQ"), "NET":("haram","NYSE"),
    "CRWD":("halal","NASDAQ"), "ZS":("halal","NASDAQ"), "PANW":("halal","NASDAQ"), "FTNT":("halal","NASDAQ"), "INTU":("halal","NASDAQ"),
    "AMD":("halal","NASDAQ"), "AVGO":("halal","NASDAQ"), "MU":("halal","NASDAQ"), "INTC":("halal","NASDAQ"), "QCOM":("halal","NASDAQ"),
    "TXN":("halal","NASDAQ"), "ADI":("halal","NASDAQ"), "LRCX":("halal","NASDAQ"), "AMAT":("halal","NASDAQ"), "KLAC":("halal","NASDAQ"),
    "ASML":("halal","NASDAQ"), "TSM":("halal","NYSE"), "SMCI":("haram","NASDAQ"), "ARM":("halal","NASDAQ"), "MRVL":("halal","NASDAQ"),
    "ON":("halal","NASDAQ"), "NXPI":("halal","NASDAQ"), "MPWR":("halal","NASDAQ"), "CDNS":("halal","NASDAQ"), "SNPS":("halal","NASDAQ"),
    "XPEV":("haram","NYSE"), "NIO":("haram","NYSE"), "LI":("haram","NASDAQ"), "RIVN":("haram","NASDAQ"), "LCID":("haram","NASDAQ"),
    "LLY":("halal","NYSE"), "JNJ":("halal","NYSE"), "ABBV":("halal","NYSE"), "MRK":("halal","NYSE"), "PFE":("haram","NYSE"),
    "AMGN":("halal","NASDAQ"), "GILD":("halal","NASDAQ"), "VRTX":("halal","NASDAQ"), "REGN":("halal","NASDAQ"), "ISRG":("halal","NASDAQ"),
    "MDT":("halal","NYSE"), "SYK":("halal","NYSE"), "BSX":("halal","NYSE"), "ZTS":("haram","NYSE"), "DHR":("halal","NYSE"),
    "PG":("halal","NYSE"), "KO":("halal","NYSE"), "PEP":("halal","NASDAQ"), "COST":("doubtful","NASDAQ"), "WMT":("doubtful","NYSE"),
    "HD":("halal","NYSE"), "NKE":("halal","NYSE"), "SBUX":("halal","NASDAQ"), "LULU":("halal","NASDAQ"), "TJX":("halal","NYSE"),
    "ORLY":("halal","NASDAQ"), "AZO":("halal","NYSE"), "XOM":("halal","NYSE"), "CVX":("halal","NYSE"), "COP":("halal","NYSE"),
    "SLB":("halal","NYSE"), "EOG":("halal","NYSE"), "OXY":("haram","NYSE"), "HAL":("halal","NYSE"), "FCX":("halal","NYSE"),
    "LIN":("halal","NASDAQ"), "SCCO":("halal","NYSE"), "CAT":("halal","NYSE"), "DE":("haram","NYSE"), "HON":("haram","NASDAQ"),
    "UNP":("halal","NYSE"), "GE":("haram","NYSE"), "ETN":("halal","NYSE"), "EMR":("halal","NYSE"), "PH":("halal","NYSE"),
    "DELL":("halal","NYSE"), "CSCO":("halal","NASDAQ"), "IBM":("halal","NYSE"), "ANET":("halal","NYSE"), "VRT":("halal","NYSE"),
}
DOUBTFUL_MODE = "tag"   # "tag" = يرسل مع ⚠️ | "skip" = يستبعد

# ============================ الإعدادات ============================
NTFY_TOPIC   = "radar-hout-yk8on5jf"
CAPITAL_USD  = 1000
SPIKE_X      = 3.0    # فوليوم شمعة الحوت ≥ 3× وسيط آخر 20 شمعة
PACE_X       = 1.5    # وتيرة فوليوم اليوم ≥ 1.5× متوسط نفس الفترة لآخر 4 أيام
CLV_MIN      = 0.6    # أدنى قبول عام
CLV_LIFT     = 0.75   # الحوت الرافع يغلق بأعلى ربع الشمعة
RANGE_X      = 1.3    # مدى شمعة الحوت ≥ 1.3× متوسط المدى (شمعة عريضة = رفع، ضيقة = امتصاص)
RSI_MIN, RSI_MAX = 55, 75
ROOM_MIN     = 0.015  # مسافة للمقاومة ≥ 1.5% (أو اختراق مؤكد)
MIN_SCORE    = 60
WATCH_MIN_SCORE = 80  # تنبيه "راقب" للحوت المدافع فقط لو قوي
MAX_PUSH_PER_RUN = 2
TARGET_PCT   = 0.02
STOP_PCT     = 0.02
ALERT_START  = 9 * 60 + 45    # لا تنبيهات قبل 9:45 بتوقيت نيويورك
ALERT_END    = 15 * 60 + 45   # ولا بعد 15:45 (آخر ربع ساعة = فجوات ومزادات)
EARN_BLOCK_DAYS = 2           # يتخطى السهم لو أرباحه خلال يومين (أو أمس)
CHUNK        = 25
STATE_FILE   = "state.json"
ALERTS_FILE  = "alerts.jsonl"
RESULTS_FILE = "results.csv"
DAILY_CACHE  = "daily_cache.json"
ET = ZoneInfo("America/New_York")

EXCH_AR = {"NASDAQ": "ناسداك", "NYSE": "نيويورك"}
DISCLAIMER = "⚠️ إشارة تقديرية مو نصيحة مالية — نفّذ بنفسك على دلالات."


# ============================ أدوات عامة ============================
def push(title, message, priority=4):
    body = json.dumps({"topic": NTFY_TOPIC, "title": title, "message": message,
                       "priority": priority}).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)

def append_jsonl(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def to_et_index(df):
    idx = df.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    df = df.copy()
    df.index = idx.tz_convert(ET)
    return df

def rsi_last(closes, period=14):
    c = np.asarray(closes, dtype=float)
    if len(c) < period + 2:
        return 50.0
    d = np.diff(c)
    gains = np.where(d > 0, d, 0.0); losses = np.where(d < 0, -d, 0.0)
    ag = gains[:period].mean(); al = losses[:period].mean()
    for i in range(period, len(d)):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
    if al == 0:
        return 100.0
    return float(100 - 100 / (1 + ag / al))

def ema_last(vals, span):
    a = 2.0 / (span + 1); e = float(vals[0])
    for x in vals[1:]:
        e = a * float(x) + (1 - a) * e
    return e

def slope_per_bar(vals):
    y = np.asarray(vals, dtype=float)
    if len(y) < 3:
        return 0.0
    x = np.arange(len(y))
    return float(np.polyfit(x, y, 1)[0])

def halal_info(sym):
    st, ex = HALAL.get(sym, ("unknown", ""))
    return st, ex


# ============================ البيانات ============================
def fetch_intraday(symbols):
    """5 أيام × 5 دقايق على دفعات (yfinance)."""
    import yfinance as yf
    frames = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        try:
            data = yf.download(" ".join(chunk), period="5d", interval="5m",
                               group_by="ticker", auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            print(f"[dl-err] intraday chunk {i // CHUNK + 1}: {e}")
            continue
        for sym in chunk:
            try:
                df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(subset=["Close", "Volume"])
                if len(df):
                    frames[sym] = to_et_index(df)
            except Exception:
                print(f"[nodata] {sym}")
        if i + CHUNK < len(symbols):
            time.sleep(2)
    return frames

def fetch_daily(symbols, today):
    """اتجاه يومي (EMA9 > EMA21 وفوق EMA21) + قرب من قاع 60 يوم — يُحسب مرة باليوم ويُخزّن."""
    cache = load_json(DAILY_CACHE, {})
    if cache.get("date") == str(today) and cache.get("data"):
        return cache["data"]
    import yfinance as yf
    out = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        try:
            data = yf.download(" ".join(chunk), period="4mo", interval="1d",
                               group_by="ticker", auto_adjust=False, progress=False, threads=True)
        except Exception as e:
            print(f"[dl-err] daily chunk {i // CHUNK + 1}: {e}")
            continue
        for sym in chunk:
            try:
                df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(subset=["Close"])
                df = df[[d.date() < today for d in df.index]]   # استبعد شمعة اليوم الجارية
                if len(df) < 30:
                    continue
                c = df["Close"].values.astype(float); lo = df["Low"].values.astype(float)
                e9, e21 = ema_last(c, 9), ema_last(c, 21)
                low60 = float(np.min(lo[-60:]))
                out[sym] = {"trend": bool(e9 > e21 and c[-1] >= e21),
                            "near_low": bool(c[-1] <= low60 * 1.03),
                            "ema9": round(e9, 2), "ema21": round(e21, 2), "close": round(float(c[-1]), 2)}
            except Exception:
                pass
        if i + CHUNK < len(symbols):
            time.sleep(2)
    save_json(DAILY_CACHE, {"date": str(today), "data": out})
    return out

def earnings_check(sym, today):
    """يرجع (محظور؟, نص). محظور لو الإعلان خلال EARN_BLOCK_DAYS أو كان أمس."""
    try:
        import yfinance as yf
        cal = yf.Ticker(sym).calendar
        dates = []
        if isinstance(cal, dict):
            v = cal.get("Earnings Date") or cal.get("earningsDate") or []
            dates = list(v) if isinstance(v, (list, tuple)) else [v]
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            row = cal.loc["Earnings Date"] if "Earnings Date" in cal.index else cal.iloc[0]
            dates = list(row.values)
        ds = []
        for x in dates:
            try:
                ds.append(pd.Timestamp(x).date())
            except Exception:
                pass
        ds = sorted(d for d in ds if d >= today - dt.timedelta(days=1))
        if not ds:
            return False, "بعيدة"
        nxt = ds[0]; days = (nxt - today).days
        if -1 <= days <= EARN_BLOCK_DAYS:
            return True, f"{nxt} ⚠️ خلال {max(days,0)} يوم"
        return False, f"{nxt} (بعد {days} يوم)"
    except Exception:
        return False, "غير معروفة"


# ============================ التحليل ============================
def analyze(sym, df, now_et, daily):
    """يرجع (نتيجة أو None, سبب). النتيجة تحتوي type: entry | watch."""
    today = now_et.date()
    if len(df) < 60:
        return None, "بيانات قليلة"
    # شموع مكتملة فقط (الشمعة الجارية تُستبعد)
    complete = df[[(t + dt.timedelta(minutes=5)) <= now_et for t in df.index]]
    d = complete[[t.date() == today for t in complete.index]]
    if len(d) < 4:
        return None, "بداية الجلسة"
    whale = d.iloc[-2]; confirm = d.iloc[-1]
    w_idx = complete.index.get_loc(d.index[-2])
    if w_idx < 30:
        return None, "تاريخ قصير"
    hist = complete.iloc[:w_idx]          # كل ما قبل شمعة الحوت
    prior20 = hist.iloc[-20:]
    med_vol = float(np.median(prior20["Volume"].values))
    if med_vol <= 0:
        return None, "فوليوم صفر"
    spike = float(whale["Volume"]) / med_vol
    rng = float(whale["High"] - whale["Low"])
    avg_rng = float((prior20["High"] - prior20["Low"]).mean())
    rng_x = rng / avg_rng if avg_rng > 0 else 0.0
    clv = (float(whale["Close"]) - float(whale["Low"])) / rng if rng > 0 else 0.5
    green = float(whale["Close"]) >= float(whale["Open"])

    # VWAP اليوم حتى شمعة التأكيد
    tp = (d["High"] + d["Low"] + d["Close"]) / 3.0
    vsum = float(d["Volume"].sum())
    vwap = float((tp * d["Volume"]).sum() / vsum) if vsum > 0 else float(confirm["Close"])
    # VWAP حتى شمعة الحوت
    dw = d.iloc[:-1]
    vw_sum = float(dw["Volume"].sum())
    vwap_w = float((((dw["High"] + dw["Low"] + dw["Close"]) / 3.0) * dw["Volume"]).sum() / vw_sum) if vw_sum > 0 else vwap

    # وتيرة اليوم مقابل نفس عدد الشموع في آخر 4 أيام
    n = len(d)
    prev_days = sorted({t.date() for t in complete.index if t.date() < today})[-4:]
    bases = []
    for day in prev_days:
        dd = complete[[t.date() == day for t in complete.index]]
        if len(dd) >= max(6, int(n * 0.8)):
            bases.append(float(dd["Volume"].iloc[:n].sum()))
    pace = float(d["Volume"].sum()) / float(np.mean(bases)) if bases else 1.0

    # مستويات
    local_high = float(hist["High"].iloc[-12:].max())
    res_lvl = float(hist["High"].iloc[-78:].max())
    sup_lvl = float(hist["Low"].iloc[-24:].min())
    entry = float(confirm["Close"])
    breakout = float(whale["Close"]) >= res_lvl
    wall_up = None if breakout else res_lvl
    room = (wall_up - entry) / entry if wall_up else 9.9
    # RSI قبل شمعة الحوت: زخم صحي داخل على الاختراق (مو مبالغ فيه) — شمعة الحوت نفسها ترفع RSI طبيعيًا
    rsi = rsi_last(hist["Close"].values)

    # النماذج: مثلث صاعد / قاعدة ضيقة
    win = hist.iloc[-24:]
    highs = win["High"].values.astype(float); lows = win["Low"].values.astype(float)
    top = float(highs.max())
    touches = int((highs >= top * (1 - 0.0025)).sum())
    lo_slope = slope_per_bar(lows) / entry
    hi_slope = slope_per_bar(highs) / entry
    # قيعان صاعدة ≥ 0.01%/شمعة (~0.25% على ساعتين) + قمة مسطحة تُلمس مرتين + إغلاق الحوت فوقها
    triangle = bool(touches >= 2 and lo_slope > 0.0001 and lows[-1] > lows[0]
                    and abs(hi_slope) < 0.0002 and float(whale["Close"]) > top)
    b12 = hist.iloc[-12:]
    b_rng = (float(b12["High"].max()) - float(b12["Low"].min())) / entry
    base = bool((not triangle) and b_rng <= 0.010 and float(whale["Close"]) > float(b12["High"].max()))
    pattern = "مثلث صاعد 🔺" if triangle else ("قاعدة ضيقة ▭" if base else "بدون نموذج")

    # تصنيف الحوت
    if (not green) or clv < 0.4:
        return None, f"توزيع (شمعة حمرا/إغلاق ضعيف) x{spike:.1f}"
    new_high = float(whale["Close"]) >= local_high
    above_vwap_w = float(whale["Close"]) >= vwap_w
    lifting = bool(green and clv >= CLV_LIFT and rng_x >= RANGE_X and new_high and above_vwap_w)
    confirmed = bool(float(confirm["Close"]) >= (float(whale["High"]) + float(whale["Low"])) / 2.0
                     and float(confirm["Close"]) >= vwap)

    # النقاط
    sc = min((spike / SPIKE_X) * 35, 45)
    sc += min((pace / PACE_X) * 20, 30)
    sc += 15 if clv >= CLV_LIFT else 8
    sc += 10 if above_vwap_w else 0
    sc += 15 if triangle else (8 if base else 0)
    sc += 5 if RSI_MIN <= rsi <= RSI_MAX else 0
    score = int(min(round(sc), 100))

    info = dict(sym=sym, spike=round(spike, 2), pace=round(pace, 2), clv=round(clv, 2), rng_x=round(rng_x, 2),
                rsi=round(rsi, 1), vwap=round(vwap, 2), entry=round(entry, 2), whale_high=round(float(whale["High"]), 2),
                whale_low=round(float(whale["Low"]), 2), wall_up=(round(wall_up, 2) if wall_up else None),
                wall_down=round(sup_lvl, 2), room=round(room, 4), pattern=pattern, triangle=triangle, base=base,
                score=score, lifting=lifting, confirmed=confirmed, new_high=new_high,
                whale_time=d.index[-2].strftime("%H:%M"), confirm_time=d.index[-1].strftime("%H:%M"))

    # بوابات مشتركة
    if spike < SPIKE_X:
        return None, f"فوليوم x{spike:.1f} < {SPIKE_X}"
    if pace < PACE_X:
        return None, f"وتيرة x{pace:.1f} < {PACE_X}"
    dtr = daily.get(sym)
    if not dtr:
        return None, "لا بيانات يومية"
    if not dtr["trend"]:
        return None, "اتجاه يومي هابط (EMA9<EMA21)"
    if dtr["near_low"]:
        return None, "قريب من قاع 60 يوم"

    if lifting:
        if not confirmed:
            return None, "بانتظار تأكيد الشمعة التالية"
        if not (RSI_MIN <= rsi <= RSI_MAX):
            return None, f"RSI {rsi:.0f} خارج {RSI_MIN}-{RSI_MAX}"
        if not breakout and room < ROOM_MIN:
            return None, f"مقاومة لاصقة {wall_up:.2f} (+{room*100:.1f}%)"
        if score < MIN_SCORE:
            return None, f"قوة {score} < {MIN_SCORE}"
        info["type"] = "entry"
        info["grade"] = "A" if (triangle and score >= 85) else "B"
        return info, "دخول"
    # حوت مدافع (امتصاص) → راقب فقط
    if score >= WATCH_MIN_SCORE and clv >= CLV_MIN:
        info["type"] = "watch"; info["grade"] = "W"
        return info, "راقب"
    return None, f"حوت مدافع ضعيف (قوة {score})"


# ============================ الرسائل ============================
def build_plan(r):
    entry = r["entry"]
    target = entry * (1 + TARGET_PCT)
    if r["wall_up"] and r["wall_up"] < target:
        target = r["wall_up"]
    stop_pct = entry * (1 - STOP_PCT)
    stop = max(stop_pct, r["whale_low"] * 0.998)   # الأضيق: تحت قاع شمعة الحوت أو −2%
    shares = int(CAPITAL_USD // entry) if entry > 0 else 0
    return dict(target=round(target, 2), target_pct=round((target / entry - 1) * 100, 2),
                stop=round(stop, 2), stop_pct=round((1 - stop / entry) * 100, 2), shares=shares)

def halal_line(sym):
    st, ex = halal_info(sym)
    if st == "halal":
        return "🕌 حلال ✅ (Zoya/AAOIFI)"
    if st == "doubtful":
        return "🕌 ⚠️ مشكوك عند Zoya — تأكد قبل الدخول"
    if st == "haram":
        return "🕌 ❌ غير متوافق"
    return "🕌 غير مصنّف — تأكد"

def entry_message(r, plan, earn_txt):
    st, ex = halal_info(r["sym"])
    exa = EXCH_AR.get(ex, ex or "؟")
    g = "🅰️" if r["grade"] == "A" else "🅱️"
    title = f"🐋 حوت رافع {g} {r['sym']} ({exa}) — قوة {r['score']}/100"
    wall_up = f"{r['wall_up']:.2f}$" if r["wall_up"] else "اختراق ✅"
    lines = [
        f"دخول {r['entry']:.2f}$ | أسهم على {CAPITAL_USD}$: {plan['shares']}",
        f"النموذج: {r['pattern']} | RSI {r['rsi']:.0f} | اتجاه يومي صاعد ✅",
        f"فوليوم الشمعة x{r['spike']:.1f} | وتيرة اليوم x{r['pace']:.1f} | فوق VWAP ✅ | تأكيد الشمعة التالية ✅",
        f"جدار علوي {wall_up} | جدار سفلي {r['wall_down']:.2f}$ | قاع شمعة الحوت {r['whale_low']:.2f}$",
        f"🎯 هدف {plan['target']:.2f}$ (+{plan['target_pct']:.1f}%) | 🛑 وقف {plan['stop']:.2f}$ (−{plan['stop_pct']:.1f}%)",
        f"{halal_line(r['sym'])} | 📅 أرباح: {earn_txt}",
        DISCLAIMER,
    ]
    return title, "\n".join(lines)

def watch_message(r):
    st, ex = halal_info(r["sym"])
    exa = EXCH_AR.get(ex, ex or "؟")
    title = f"👀 حوت مدافع — راقب {r['sym']} ({exa}) — قوة {r['score']}/100"
    trigger = r["wall_up"] if r["wall_up"] else r["whale_high"]
    lines = [
        f"السعر {r['entry']:.2f}$ | فوليوم x{r['spike']:.1f} | وتيرة x{r['pace']:.1f} | {r['pattern']}",
        f"امتصاص عند دعم — مو رفع. لا دخول إلا بتجاوز {trigger:.2f}$ بفوليوم.",
        f"{halal_line(r['sym'])}",
        DISCLAIMER,
    ]
    return title, "\n".join(lines)


# ============================ التقييم عند الإقفال ============================
def evaluate():
    """يقيّم تنبيهات الدخول اليوم: هدف/وقف/إغلاق، يكتب results.csv ويرسل ملخص."""
    now = dt.datetime.now(ET); today = now.date()
    recs = []
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("type") == "entry" and r.get("date") == str(today):
                    recs.append(r)
    except FileNotFoundError:
        pass
    if not recs:
        push("📊 نتائج اليوم", "ما فيه تنبيهات دخول اليوم — لا صفقة = انضباط.", 3)
        return
    frames = fetch_intraday(sorted({r["sym"] for r in recs}))
    rows = []
    for r in recs:
        df = frames.get(r["sym"])
        if df is None:
            continue
        t0 = pd.Timestamp(r["ts_et"])
        if t0.tzinfo is None:
            t0 = t0.tz_localize(ET)
        after = df[(df.index > t0) & [t.date() == today for t in df.index]]
        if after.empty:
            continue
        entry, target, stop = r["entry"], r["target"], r["stop"]
        outcome, exit_px = "none", float(after["Close"].iloc[-1])
        for _, b in after.iterrows():
            if float(b["Low"]) <= stop:
                outcome, exit_px = "stop", stop; break
            if float(b["High"]) >= target:
                outcome, exit_px = "target", target; break
        max_up = (float(after["High"].max()) / entry - 1) * 100
        max_dn = (float(after["Low"].min()) / entry - 1) * 100
        exit_pct = (exit_px / entry - 1) * 100
        rows.append([str(today), r["sym"], r.get("grade", ""), r.get("pattern", ""), entry, target, stop,
                     outcome, round(exit_pct, 2), round(max_up, 2), round(max_dn, 2), r["ts_et"]])
    new_file = not os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "sym", "grade", "pattern", "entry", "target", "stop", "outcome",
                        "exit_pct", "max_up_pct", "max_dn_pct", "alert_time_et"])
        w.writerows(rows)
    # ملخص اليوم + الأسبوع
    lab = {"target": "هدف ✅", "stop": "وقف ❌", "none": "بدون"}
    lines = [f"{x[1]} {x[2]}: {lab[x[7]]} {x[8]:+.1f}% (أعلى {x[9]:+.1f}%)" for x in rows]
    tot = sum(x[8] for x in rows)
    wk = load_results_week(today)
    lines.append(f"اليوم: {len(rows)} إشارة | صافي {tot:+.1f}%")
    if wk:
        lines.append(f"الأسبوع: {wk['n']} إشارة | هدف {wk['t']} | وقف {wk['s']} | صافي {wk['sum']:+.1f}%")
    push("📊 نتائج اليوم (ورقي)", "\n".join(lines), 3)
    print("\n".join(lines))

def load_results_week(today):
    try:
        monday = today - dt.timedelta(days=today.weekday())
        n = t = s = 0; tot = 0.0
        with open(RESULTS_FILE, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if dt.date.fromisoformat(row["date"]) >= monday:
                    n += 1; tot += float(row["exit_pct"])
                    t += row["outcome"] == "target"; s += row["outcome"] == "stop"
        return {"n": n, "t": t, "s": s, "sum": tot} if n else None
    except Exception:
        return None


# ============================ فحص جاف (بدون إرسال) ============================
def dry_run():
    """يشغّل خط البيانات والتحليل كاملًا على آخر جلسة (15:30 بتوقيت نيويورك) ويطبع النتائج — بدون إرسال ولا حفظ حالة."""
    now = dt.datetime.now(ET)
    sim = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now.weekday() >= 5 or now < now.replace(hour=10, minute=0):
        sim -= dt.timedelta(days=1)
    while sim.weekday() >= 5:
        sim -= dt.timedelta(days=1)
    today = sim.date()
    symbols = [s for s in WATCHLIST if halal_info(s)[0] != "haram"]
    t0 = time.time()
    daily = fetch_daily(symbols, today)
    frames = fetch_intraday(symbols)
    print(f"[dry] sim={sim:%Y-%m-%d %H:%M} ET | intraday {len(frames)}/{len(symbols)} | daily {len(daily)} | {time.time()-t0:.0f}s")
    hits, reasons, errs = [], {}, 0
    for sym in symbols:
        df = frames.get(sym)
        if df is None:
            continue
        try:
            r, why = analyze(sym, df, sim, daily)
        except Exception as e:
            errs += 1; print(f"[dry-err] {sym}: {type(e).__name__}: {e}"); continue
        key = why.split(" ")[0]
        reasons[key] = reasons.get(key, 0) + 1
        if r:
            hits.append(r)
    hits.sort(key=lambda x: x["score"], reverse=True)
    print(f"[dry] errors={errs} reasons={dict(sorted(reasons.items(), key=lambda kv: -kv[1]))}")
    for r in hits[:10]:
        print(f"[dry-hit] {r['type']:5} {r.get('grade','')} {r['sym']:5} score={r['score']} {r['pattern']} "
              f"spike=x{r['spike']} pace=x{r['pace']} clv={r['clv']} rsi={r['rsi']} @{r['whale_time']}→{r['confirm_time']}")
    if not hits:
        print("[dry] no candidates on the simulated session (normal on quiet days)")


# ============================ المنسّق ============================
def main():
    args = sys.argv[1:]
    if "--evaluate" in args:
        return evaluate()
    if "--dry" in args:
        return dry_run()
    test = os.environ.get("TEST") == "1" or "--test" in args
    now = dt.datetime.now(ET); today = now.date()
    if test:
        push("🐋 اختبار رادار الحيتان v3", "التنبيهات وصلتك ✅ النسخة 3 شغّالة: حوت رافع + مثلث + فلاتر. هذا اختبار — مو صفقة.", 3)
        print("[test] sent")
        try:
            dry_run()          # فحص جاف على بيانات حقيقية بعد كل رفع — يظهر بالسجل فقط
        except Exception as e:
            print(f"[dry] failed: {type(e).__name__}: {e}")
        return
    if now.weekday() >= 5:
        print("[skip] weekend"); return
    mins = now.hour * 60 + now.minute
    if mins < ALERT_START or mins > ALERT_END:
        print(f"[skip] outside alert window {now:%H:%M} ET"); return

    state = load_json(STATE_FILE, {})
    symbols = [s for s in WATCHLIST if halal_info(s)[0] != "haram"
               and not (DOUBTFUL_MODE == "skip" and halal_info(s)[0] == "doubtful")]
    daily = fetch_daily(symbols, today)
    frames = fetch_intraday(symbols)
    print(f"[data] intraday {len(frames)}/{len(symbols)} | daily {len(daily)}")

    entries, watches, skipped = [], [], {}
    for sym in symbols:
        df = frames.get(sym)
        if df is None:
            continue
        try:
            r, why = analyze(sym, df, now, daily)
        except Exception as e:
            print(f"[err] {sym}: {e}"); continue
        if r is None:
            skipped[why.split(" ")[0]] = skipped.get(why.split(" ")[0], 0) + 1
            continue
        prev = state.get(sym)
        if not isinstance(prev, dict):   # حالة قديمة (نسخة 2) أو تالفة
            prev = {}
        if prev.get("date") == str(today) and (prev.get("type") == "entry" or r["type"] == "watch"):
            continue   # تنبيه واحد لكل سهم باليوم
        (entries if r["type"] == "entry" else watches).append(r)

    entries.sort(key=lambda x: x["score"], reverse=True)
    watches.sort(key=lambda x: x["score"], reverse=True)
    sent = 0
    for r in entries + watches:
        if sent >= MAX_PUSH_PER_RUN:
            break
        earn_block, earn_txt = (False, "")
        if r["type"] == "entry":
            earn_block, earn_txt = earnings_check(r["sym"], today)
            if earn_block:
                print(f"[earn-skip] {r['sym']} {earn_txt}"); continue
            plan = build_plan(r)
            title, msg = entry_message(r, plan, earn_txt)
        else:
            plan = {}
            title, msg = watch_message(r)
        try:
            push(title, msg, 5 if r["type"] == "entry" else 3)
            ok = True
        except Exception as e:
            print(f"[push-err] {r['sym']}: {e}"); ok = False
        state[r["sym"]] = {"date": str(today), "type": r["type"], "ts": now.isoformat()}
        rec = {"date": str(today), "ts_et": now.isoformat(), "ts_utc": dt.datetime.utcnow().isoformat(),
               "pushed": ok, "earnings": earn_txt, **r, **plan}
        append_jsonl(ALERTS_FILE, rec)
        sent += 1
        print(f"[alert] {r['type']} {r['sym']} score={r['score']} pattern={r['pattern']} pushed={ok}")
    save_json(STATE_FILE, state)
    print(f"[done] {now.isoformat()} entries={len(entries)} watches={len(watches)} sent={sent} skipped={skipped}")

if __name__ == "__main__":
    main()
