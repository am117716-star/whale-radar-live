#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار تاريخي للفريم اليومي (سوينق) — 3 سنوات × الأسهم الحلال.
الفكرتان المقترحتان من الاستشارة:
  (أ) اختراق: إغلاق اليوم > أعلى قمة لآخر 20 يوم، فوليوم ≥ 2× متوسط 20 يوم، إغلاق قوي (الربع الأعلى من الشمعة)،
      فوق MA50. (متغيّر: MA50 > MA200)
  (ب) ارتداد: لمس MA50 (القاع ≤ MA50 × 1.01) والإغلاق فوقه بشمعة قوية (الربع الأعلى) وفوليوم ≥ 1.5×، وفوق MA200.
الدخول: افتتاح اليوم التالي. الخروج (شبكة): وقف = قاع شمعة الإشارة (بحد أقصى −7%) × أهداف 5/8/10% × مهلة 20 يوم؛
        وبدون وقف/هدف: بيع بإغلاق اليوم 5/10/20.
المقارنة الأهم: نفس قواعد الخروج مع دخول عشوائي على نفس السهم ونفس الفترة (20 سحبة) — يفرّق الأفضلية عن السوق الصاعد.
المخرجات: daily_results.csv + daily_summary.txt.
"""
import os, sys, time, csv, datetime as dt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import live_whale as W
except ImportError:
    import live_whale_v3 as W

PERIOD = os.environ.get("PERIOD", "3y")
VOL_X_A, VOL_X_B = 2.0, 1.5
TARGETS = (5.0, 8.0, 10.0)
STOP_CAP = 7.0
HOLD_DAYS = 20
NO_STOP_DAYS = (5, 10, 20)
RANDOM_DRAWS = 20
EARN_BLOCK = 2


def pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "—"


# ============================ البيانات ============================
def fetch_daily(symbols):
    import yfinance as yf
    out = {}
    for i in range(0, len(symbols), W.CHUNK):
        chunk = symbols[i:i + W.CHUNK]
        data = None
        for attempt in range(3):
            try:
                data = yf.download(" ".join(chunk), period=PERIOD, interval="1d", group_by="ticker",
                                   auto_adjust=False, progress=False, threads=True)
                if data is not None and len(data):
                    break
            except Exception as e:
                print(f"[dl-err] attempt {attempt + 1}: {e}")
            time.sleep(5 + 5 * attempt)
        if data is None:
            continue
        for s in chunk:
            try:
                df = data[s] if isinstance(data.columns, pd.MultiIndex) else data
                df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
                if len(df) > 260:
                    out[s] = df
            except Exception:
                pass
        time.sleep(2)
    return out


def earnings_dates(sym):
    try:
        import yfinance as yf
        ed = yf.Ticker(sym).get_earnings_dates(limit=16)
        if ed is None or ed.empty:
            return []
        return sorted({pd.Timestamp(x).date() for x in ed.index})
    except Exception:
        return []


# ============================ الإشارات ============================
def signals(sym, df, earn):
    o = df["Open"].values.astype(float); h = df["High"].values.astype(float); l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float); v = df["Volume"].values.astype(float)
    n = len(c)
    ma50 = pd.Series(c).rolling(50).mean().values
    ma200 = pd.Series(c).rolling(200).mean().values
    vol20 = pd.Series(v).rolling(20).mean().shift(1).values
    high20 = pd.Series(h).rolling(20).max().shift(1).values
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr14 = np.concatenate([[np.nan], pd.Series(tr).rolling(14).mean().values])
    dates = [t.date() for t in df.index]
    earn_set = set(earn)
    out = []
    for t in range(200, n - 1):
        rng = h[t] - l[t]
        clv = (c[t] - l[t]) / rng if rng > 0 else 0.5
        if vol20[t] <= 0 or np.isnan(vol20[t]):
            continue
        volx = v[t] / vol20[t]
        near_earn = any(abs((e - dates[t]).days) <= EARN_BLOCK for e in earn_set) if earn_set else False
        kind = None
        if c[t] > high20[t] and volx >= VOL_X_A and clv >= 0.75 and c[t] > ma50[t]:
            kind = "A"
        elif (l[t] <= ma50[t] * 1.01 and c[t] > ma50[t] and clv >= 0.7 and volx >= VOL_X_B
              and c[t] > ma200[t] and c[t] >= o[t]):
            kind = "B"
        if not kind:
            continue
        out.append(dict(sym=sym, t=t, date=str(dates[t]), kind=kind, volx=round(float(volx), 2), clv=round(float(clv), 2),
                        close=round(float(c[t]), 2), sig_low=float(l[t]), atr_pct=round(float(atr14[t] / c[t] * 100), 2),
                        trend200=bool(ma50[t] > ma200[t]), ext=round(float((c[t] / ma50[t] - 1) * 100), 2),
                        near_earn=near_earn, year=dates[t].year))
    return out, (o, h, l, c, v)


# ============================ التقييم ============================
def walk(j0, j_end, stop, target, o, h, l, c):
    """من افتتاح j0 (الدخول) حتى إغلاق j_end. الفجوات بسعر الافتتاح. الوقف أولًا بنفس اليوم (تحفّظ)."""
    for j in range(j0, j_end + 1):
        if j > j0:
            if stop is not None and o[j] <= stop:
                return "stop", float(o[j]), j - j0
            if target is not None and o[j] >= target:
                return "target", float(o[j]), j - j0
        if stop is not None and l[j] <= stop:
            return "stop", float(stop), j - j0
        if target is not None and h[j] >= target:
            return "target", float(target), j - j0
    return "time", float(c[j_end]), j_end - j0


def evaluate(t, sig_low, arrays):
    o, h, l, c, v = arrays
    n = len(c)
    j0 = t + 1
    if j0 >= n:
        return None
    fill = float(o[j0])
    out = dict(fill=round(fill, 2), gap_pct=round((fill / c[t] - 1) * 100, 2))
    stop = max(sig_low, fill * (1 - STOP_CAP / 100))
    out["stop_pct"] = round((1 - stop / fill) * 100, 2)
    j_end = min(j0 + HOLD_DAYS, n - 1)
    for tg in TARGETS:
        oc, x, d = walk(j0, j_end, stop, fill * (1 + tg / 100), o, h, l, c)
        out[f"o_t{int(tg)}"] = oc; out[f"p_t{int(tg)}"] = round((x / fill - 1) * 100, 2); out[f"d_t{int(tg)}"] = d
    for nd in NO_STOP_DAYS:
        je = min(j0 + nd, n - 1)
        out[f"p_hold{nd}"] = round((c[je] / fill - 1) * 100, 2)
    seg = slice(j0, j_end + 1)
    out["mfe"] = round((float(h[seg].max()) / fill - 1) * 100, 2)
    out["mae"] = round((float(l[seg].min()) / fill - 1) * 100, 2)
    return out


def random_baseline(arrays, n_draws, rng, sig_t):
    """دخول عشوائي بنفس السهم (بعد اليوم 200 وقبل آخر 25 يوم) بنفس قواعد الخروج — وقف = قاع اليوم السابق للدخول بحد −7%."""
    o, h, l, c, v = arrays
    n = len(c)
    res = []
    for _ in range(n_draws):
        t = int(rng.integers(200, n - 25))
        r = evaluate(t, float(l[t]), arrays)
        if r:
            res.append(r)
    return res


# ============================ الملخص ============================
def stats(rows, okey, pkey):
    rs = [r for r in rows if r.get(okey) is not None]
    if not rs:
        return None
    n = len(rs); t = sum(r[okey] == "target" for r in rs); s = sum(r[okey] == "stop" for r in rs)
    ps = [r[pkey] for r in rs]
    wins = sum(p for p in ps if p > 0); losses = -sum(p for p in ps if p < 0)
    return dict(n=n, t=t, s=s, z=n - t - s, avg=float(np.mean(ps)), med=float(np.median(ps)),
                pf=(wins / losses if losses > 0 else float("inf")), pos=sum(p > 0 for p in ps))


def line(label, st):
    if not st:
        return f"{label}: —"
    return (f"{label}: n={st['n']} | هدف {st['t']} ({pct(st['t'], st['n'])}) | وقف {st['s']} ({pct(st['s'], st['n'])}) | "
            f"مهلة {st['z']} | متوسط {st['avg']:+.2f}% | وسيط {st['med']:+.2f}% | موجبة {pct(st['pos'], st['n'])} | ربح/خسارة {st['pf']:.2f}")


def hold_line(label, rows, nd):
    ps = [r[f"p_hold{nd}"] for r in rows if r.get(f"p_hold{nd}") is not None]
    if not ps:
        return f"{label}: —"
    return f"{label}: n={len(ps)} | متوسط {np.mean(ps):+.2f}% | وسيط {np.median(ps):+.2f}% | موجبة {pct(sum(p > 0 for p in ps), len(ps))} | أسوأ {min(ps):+.1f}% | أفضل {max(ps):+.1f}%"


def block(title, rows, base):
    L = [f"=== {title} (n={len(rows)}) ==="]
    if not rows:
        return L + ["لا إشارات."]
    L.append(f"أعلى ارتفاع خلال 20 يوم بعد الدخول: متوسط {np.mean([r['mfe'] for r in rows]):+.2f}% | أعلى هبوط {np.mean([r['mae'] for r in rows]):+.2f}% | "
             f"وصل 5%: {pct(sum(r['mfe'] >= 5 for r in rows), len(rows))} | وصل 10%: {pct(sum(r['mfe'] >= 10 for r in rows), len(rows))} | فجوة الدخول متوسط {np.mean([r['gap_pct'] for r in rows]):+.2f}%")
    L.append(f"الوقف (قاع شمعة الإشارة، حد −7%): متوسط بعده {np.mean([r['stop_pct'] for r in rows]):.2f}%")
    for tg in TARGETS:
        L.append(line(f"  هدف {int(tg)}% / وقف قاع الشمعة / مهلة 20 يوم", stats(rows, f"o_t{int(tg)}", f"p_t{int(tg)}")))
        if base:
            L.append(line(f"     ↳ دخول عشوائي (مقارنة)", stats(base, f"o_t{int(tg)}", f"p_t{int(tg)}")))
    for nd in NO_STOP_DAYS:
        L.append(hold_line(f"  بدون وقف/هدف — بيع بإغلاق اليوم {nd}", rows, nd))
        if base:
            L.append(hold_line(f"     ↳ دخول عشوائي (مقارنة)", base, nd))
    return L


def summarize(rows, base_rows, n_syms, first, last):
    L = [f"📅 اختبار الفريم اليومي — {n_syms} سهم حلال | {first} → {last} | إشارات: {len(rows)} "
         f"(أ اختراق: {sum(r['kind'] == 'A' for r in rows)} | ب ارتداد MA50: {sum(r['kind'] == 'B' for r in rows)}) | محظورة أرباح: {sum(r['near_earn'] for r in rows)}"]
    ok = [r for r in rows if not r["near_earn"]]
    A = [r for r in ok if r["kind"] == "A"]; B = [r for r in ok if r["kind"] == "B"]
    L += block("أ) اختراق قمة 20 يوم بفوليوم ≥2× وإغلاق قوي فوق MA50", A, base_rows)
    L += block("أ-2) نفس الاختراق + MA50 فوق MA200 (اتجاه طويل صاعد)", [r for r in A if r["trend200"]], None)
    L += block("أ-3) الاختراق غير الممتد (الإغلاق ≤ 8% فوق MA50)", [r for r in A if r["ext"] <= 8], None)
    L += block("ب) ارتداد من MA50 بشمعة قوية وفوليوم ≥1.5× فوق MA200", B, base_rows)
    L.append("=== حسب السنة — إعداد هدف 8% / وقف قاع الشمعة (أ + ب) ===")
    for y in sorted({r["year"] for r in ok}):
        L.append(line(f"  {y}", stats([r for r in ok if r["year"] == y], "o_t8", "p_t8")))
    L.append("=== حسب تذبذب السهم (ATR%) — هدف 8% (أ + ب) ===")
    for lo_, hi_, lab in ((0, 1.5, "هادي <1.5%"), (1.5, 2.5, "1.5–2.5%"), (2.5, 4, "2.5–4%"), (4, 99, "متذبذب >4%")):
        g = [r for r in ok if lo_ <= r["atr_pct"] < hi_]
        if g:
            L.append(line(f"  {lab}", stats(g, "o_t8", "p_t8")))
    L.append("=== حسب قوة الفوليوم — هدف 8% (أ) ===")
    for lo_, hi_, lab in ((2, 3, "2–3×"), (3, 5, "3–5×"), (5, 99, ">5×")):
        g = [r for r in A if lo_ <= r["volx"] < hi_]
        if g:
            L.append(line(f"  {lab}", stats(g, "o_t8", "p_t8")))
    return "\n".join(L)


def main():
    t0 = time.time()
    symbols = [s for s in W.WATCHLIST if W.halal_info(s)[0] != "haram"]
    data = fetch_daily(symbols)
    print(f"[daily] data {len(data)}/{len(symbols)} | {time.time() - t0:.0f}s")
    rng = np.random.default_rng(7)
    rows, base = [], []
    for s in symbols:
        df = data.get(s)
        if df is None:
            continue
        earn = earnings_dates(s)
        sigs, arrays = signals(s, df, earn)
        for sg in sigs:
            ev = evaluate(sg["t"], sg["sig_low"], arrays)
            if ev:
                sg.update(ev); rows.append(sg)
        base += random_baseline(arrays, RANDOM_DRAWS, rng, None)
    first = min((r["date"] for r in rows), default="—"); last = max((r["date"] for r in rows), default="—")
    rows.sort(key=lambda r: (r["date"], r["sym"]))
    if rows:
        cols = list(dict.fromkeys(k for r in rows for k in r.keys()))
        with open("daily_results.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    summ = summarize(rows, base, len(data), first, last)
    summ += f"\nالدخول العشوائي: {len(base)} سحبة ({RANDOM_DRAWS} لكل سهم) | {time.time() - t0:.0f} ثانية"
    with open("daily_summary.txt", "w", encoding="utf-8") as f:
        f.write(summ + "\n")
    print("[daily-summary]\n" + summ)


if __name__ == "__main__":
    main()
