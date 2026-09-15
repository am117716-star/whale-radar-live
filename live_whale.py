# -*- coding: utf-8 -*-
# رادار الحيتان الحي — Live Whale Radar (free stack: GitHub Actions + Yahoo data + ntfy push)
# يفحص القائمة كل ~5 دقايق وقت السوق الأمريكي، وإذا دخل فوليوم حوت على سهم يرسل تنبيه فوري للجوال.
import json, os, sys, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

WATCHLIST = ["AAPL", "NVDA", "AMD", "TSLA", "AVGO", "MU", "XPEV"]  # حلال فقط
NTFY_TOPIC = "radar-hout-yk8on5jf"          # قناة التنبيهات في تطبيق ntfy
CAPITAL_USD = 1000                           # رأس المال لحساب عدد الأسهم
SPIKE_X = 3.0        # فوليوم الشمعة >= 3x وسيط آخر 20 شمعة (بصمة الحوت)
PACE_X = 1.5         # فوليوم اليوم التراكمي >= 1.5x متوسط نفس الوقت من الأيام السابقة
CLV_MIN = 0.6        # الإغلاق قريب من أعلى الشمعة (شراء مو بيع)
MIN_SCORE = 55
COOLDOWN_MIN = 45    # لا يكرر التنبيه لنفس السهم قبل مرور هالمدة
STATE_FILE = "state.json"

ET = ZoneInfo("America/New_York")


def push(title, message, priority=4):
    body = json.dumps({
        "topic": NTFY_TOPIC,
        "title": title,
        "message": message,
        "priority": priority,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://ntfy.sh", data=body, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=15)


def market_open(now_et):
    if now_et.weekday() >= 5:
        return False
    minutes = now_et.hour * 60 + now_et.minute
    return (9 * 60 + 35) <= minutes <= (16 * 60)  # 9:35am–4:00pm ET


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def money(x):
    return "-" if x is None else f"${x:,.2f}"


def analyze(sym, df, now_et):
    """df: 5-minute bars (~5 days), ET tz-aware index, columns Open/High/Low/Close/Volume."""
    df = df.dropna()
    if len(df) < 30:
        return None
    today = now_et.date()
    d = df[[i.date() == today for i in df.index]]
    if len(d) < 2:
        return None
    prev_days = sorted({i.date() for i in df.index if i.date() != today})
    if not prev_days:
        return None

    # جرّب آخر شمعتين (الأخيرة ممكن تكون لسا تتكوّن — إذا فوليومها الجزئي أصلاً x3 فهذا حوت صارخ)
    best = None
    for pos in (-1, -2):
        if len(d) < abs(pos):
            continue
        bar = d.iloc[pos]
        bt = d.index[pos]
        prior = df[df.index < bt]["Volume"].tail(20)
        if len(prior) < 10:
            continue
        med = float(prior.median())
        if med <= 0:
            continue
        spike = float(bar["Volume"]) / med
        rng = float(bar["High"] - bar["Low"])
        clv = float((bar["Close"] - bar["Low"]) / rng) if rng > 0 else 0.5
        green = bool(bar["Close"] >= bar["Open"])
        if spike >= SPIKE_X and green and clv >= CLV_MIN:
            if best is None or spike > best[0]:
                best = (spike, clv, bar, bt)
    if best is None:
        return None
    spike, clv, bar, bt = best

    # وتيرة فوليوم اليوم مقارنة بنفس الوقت من الأيام السابقة
    n = len(d)
    bases = []
    for day in prev_days[-4:]:
        dd = df[[i.date() == day for i in df.index]]
        if len(dd) >= max(6, int(n * 0.8)):
            bases.append(float(dd["Volume"].iloc[:n].sum()))
    pace = float(d["Volume"].sum()) / float(np.mean(bases)) if bases else 1.0

    vol_sum = float(d["Volume"].sum())
    vwap = float((d["Close"] * d["Volume"]).sum() / vol_sum) if vol_sum > 0 else float(bar["Close"])
    price = float(d["Close"].iloc[-1])
    above_vwap = price >= vwap
    if pace < PACE_X or not above_vwap:
        return None

    sc = min((spike / SPIKE_X) * 35, 45)
    sc += min((pace / PACE_X) * 20, 30)
    sc += 15 if clv >= 0.75 else 8
    sc += 10 if above_vwap else 0
    score = int(min(round(sc), 100))
    if score < MIN_SCORE:
        return None

    # الجدران: قمم/قيعان الأيام السابقة فقط (قمة اليوم = السعر نفسه وقت الاندفاع، فلا تُحسب جدار)
    res, sup = [], []
    for day in prev_days:
        dd = df[[i.date() == day for i in df.index]]
        if len(dd):
            h, l = float(dd["High"].max()), float(dd["Low"].min())
            if h > price:
                res.append(h)
            if l < price:
                sup.append(l)
    lo_t = float(d["Low"].min())
    if lo_t < price:
        sup.append(lo_t)
    wall_up = min(res) if res else None
    wall_dn = max(sup) if sup else None

    target = price * 1.02
    # قصّ الهدف على الجدار العلوي فقط إذا كان الجدار يعطي ربح معقول (>0.8%)، وإلا خلّه +2%
    if wall_up and price * 1.008 < wall_up < target:
        target = wall_up
    stop = price * 0.98
    shares = int(CAPITAL_USD // price)
    return {
        "score": score, "spike": spike, "pace": pace, "clv": clv,
        "price": price, "wall_up": wall_up, "wall_dn": wall_dn,
        "target": target, "tgt_pct": (target / price - 1) * 100,
        "stop": stop, "shares": shares, "bar_time": bt.isoformat(),
    }


def alert_text(sym, a):
    title = f"🐋 حوت دخل {sym} الحين — قوة {a['score']}/100"
    msg = (
        f"دخول {money(a['price'])} | أسهم على 1000$: {a['shares']}\n"
        f"فوليوم الشمعة x{a['spike']:.1f} | وتيرة اليوم x{a['pace']:.1f} | فوق VWAP ✅\n"
        f"جدار علوي {money(a['wall_up'])} | جدار سفلي {money(a['wall_dn'])}\n"
        f"هدف {money(a['target'])} (+{a['tgt_pct']:.1f}%) | وقف {money(a['stop'])} (-2%)\n"
        f"⚠️ إشارة تقديرية مو نصيحة مالية — نفّذ بنفسك على دلالات، وتأكد ما فيه إعلان أرباح قريب."
    )
    return title, msg


def main():
    now_et = datetime.now(ET)
    test = os.environ.get("TEST") == "1" or "--test" in sys.argv
    if test:
        push("🐋 اختبار رادار الحيتان", "التنبيهات وصلتك ✅ النظام جاهز. هذا اختبار — مو صفقة.", 4)
        print("[test] push sent")

    if not market_open(now_et):
        print(f"[closed] {now_et.isoformat()}")
        return

    import yfinance as yf
    data = yf.download(
        " ".join(WATCHLIST), period="5d", interval="5m",
        group_by="ticker", auto_adjust=False, progress=False, threads=True,
    )
    state = load_state()
    hits = []
    for sym in WATCHLIST:
        try:
            df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.copy()
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            df.index = df.index.tz_convert(ET)
            a = analyze(sym, df, now_et)
        except Exception as e:
            print(f"[err] {sym}: {e}")
            continue
        if not a:
            print(f"[no] {sym}")
            continue
        last = state.get(sym)
        if last:
            try:
                if (now_et - datetime.fromisoformat(last)).total_seconds() < COOLDOWN_MIN * 60:
                    print(f"[cooldown] {sym}")
                    continue
            except Exception:
                pass
        state[sym] = now_et.isoformat()
        hits.append((sym, a))

    hits.sort(key=lambda x: x[1]["score"], reverse=True)
    for sym, a in hits:
        title, msg = alert_text(sym, a)
        try:
            push(title, msg)
            print(f"[ALERT] {sym} score={a['score']} spike=x{a['spike']:.1f}")
        except Exception as e:
            print(f"[push-err] {sym}: {e}")

    with open(STATE_FILE, "w") as f:
        json.dump(state, f)
    print(f"[done] {now_et.isoformat()} hits={len(hits)}")


if __name__ == "__main__":
    main()
