#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اختبار تاريخي (Backtest) لرادار الحيتان v3 — نفس كود live_whale.py حرفيًا (analyze / build_plan)
يعاد تشغيله على آخر ~59 يوم تداول (حد ياهو لشموع 5 دقايق) لكل الأسهم الحلال.

لكل يوم ولكل سهم: أول إشارة "دخول" تطلع (تنبيه واحد لكل سهم باليوم كما في الإنتاج)،
ثم نتابع الشموع بعدها لنفس اليوم: هل ضرب الهدف (+2% أو الجدار) قبل الوقف؟ ولا الوقف؟ ولا لا شيء (خروج بإقفال اليوم)؟
التنفيذ الواقعي: سعر التعبئة = افتتاح الشمعة اللي بعد التنبيه (مو إغلاق شمعة التأكيد).
المخرجات: backtest_results.csv (صف لكل إشارة) + backtest_summary.txt (ملخص عربي) + السجل.
"""
import os, sys, time, csv, json, datetime as dt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import live_whale as W
except ImportError:            # للاختبار المحلي
    import live_whale_v3 as W

DAYS = int(os.environ.get("DAYS", "59"))
DAILY_BARS = 85                 # يعادل period="4mo" في الإنتاج
ET = W.ET


# ============================ البيانات ============================
def dl(symbols, **kw):
    import yfinance as yf
    for attempt in range(3):
        try:
            data = yf.download(" ".join(symbols), group_by="ticker", auto_adjust=False,
                               progress=False, threads=True, **kw)
            if data is not None and len(data):
                return data
        except Exception as e:
            print(f"[dl-err] {kw} attempt {attempt+1}: {e}")
        time.sleep(5 + 5 * attempt)
    return None


def split_frames(data, symbols, need=("Close", "Volume")):
    out = {}
    if data is None:
        return out
    for sym in symbols:
        try:
            df = data[sym] if isinstance(data.columns, pd.MultiIndex) else data
            df = df.dropna(subset=list(need))
            if len(df):
                out[sym] = df
        except Exception:
            pass
    return out


def fetch_all(symbols):
    intra, daily = {}, {}
    for i in range(0, len(symbols), W.CHUNK):
        chunk = symbols[i:i + W.CHUNK]
        f = split_frames(dl(chunk, period=f"{DAYS}d", interval="5m"), chunk)
        for s, df in f.items():
            intra[s] = W.to_et_index(df)
        time.sleep(3)
        f = split_frames(dl(chunk, period="8mo", interval="1d"), chunk, need=("Close",))
        for s, df in f.items():
            daily[s] = df
        print(f"[bt] chunk {i // W.CHUNK + 1}: intraday {len(intra)} | daily {len(daily)}")
        time.sleep(3)
    return intra, daily


def earnings_dates(sym):
    """تواريخ الأرباح (ماضية وقادمة) لحارس الأرباح — لو فشلت: بدون حظر (مثل الإنتاج)."""
    try:
        import yfinance as yf
        ed = yf.Ticker(sym).get_earnings_dates(limit=12)
        if ed is None or ed.empty:
            return []
        return sorted({pd.Timestamp(x).date() for x in ed.index})
    except Exception:
        return []


def daily_as_of(ddf, D):
    """نفس حساب fetch_daily في الإنتاج لكن 'كما كان' يوم D (شموع قبل D فقط، آخر 85 شمعة)."""
    sub = ddf[[d.date() < D for d in ddf.index]].iloc[-DAILY_BARS:]
    if len(sub) < 30:
        return None
    c = sub["Close"].values.astype(float); lo = sub["Low"].values.astype(float)
    e9, e21 = W.ema_last(c, 9), W.ema_last(c, 21)
    low60 = float(np.min(lo[-60:]))
    return {"trend": bool(e9 > e21 and c[-1] >= e21), "near_low": bool(c[-1] <= low60 * 1.03),
            "ema9": round(e9, 2), "ema21": round(e21, 2), "close": round(float(c[-1]), 2)}


# ============================ إعادة التشغيل ============================
def walk(j0, j_end, stop, target, dates, op, hi, lo, cl):
    """يمشي من الشمعة j0 إلى j_end: أول لمسة وقف/هدف (الوقف أولًا بنفس الشمعة = تحفّظ).
    عند بداية جلسة جديدة: لو الافتتاح تحت الوقف يخرج بسعر الافتتاح (فجوة)، ولو فوق الهدف يخرج بالافتتاح."""
    for j in range(j0, j_end + 1):
        if j > j0 and dates[j] != dates[j - 1]:
            if op[j] <= stop:
                return "stop", float(op[j]), j - j0 + 1
            if op[j] >= target:
                return "target", float(op[j]), j - j0 + 1
        if lo[j] <= stop:
            return "stop", float(stop), j - j0 + 1
        if hi[j] >= target:
            return "target", float(target), j - j0 + 1
    return "none", float(cl[j_end]), j_end - j0 + 1


def replay_symbol(sym, df, ddf, earn):
    rows = []
    dates = np.array([t.date() for t in df.index])
    days = sorted(set(dates))
    vol = df["Volume"].values.astype(float)
    med20 = pd.Series(vol).rolling(20).median().shift(1).values   # وسيط الـ20 شمعة قبل الشمعة
    hi = df["High"].values.astype(float); lo = df["Low"].values.astype(float)
    op = df["Open"].values.astype(float); cl = df["Close"].values.astype(float)
    n_analyze = 0
    for di, D in enumerate(days):
        if di < 4:
            continue
        pos = np.where(dates == D)[0]
        if len(pos) < 20:
            continue
        dtr = daily_as_of(ddf, D) if ddf is not None else None
        if not dtr:
            continue
        earn_block = any(-1 <= (e - D).days <= W.EARN_BLOCK_DAYS for e in earn)
        start = int(np.where(dates == days[di - 4])[0][0])
        for k in range(2, len(pos) - 1):
            i = int(pos[k])                       # شمعة الحوت
            if not (med20[i] > 0 and vol[i] / med20[i] >= W.SPIKE_X):
                continue
            now = df.index[i + 1].to_pydatetime() + dt.timedelta(minutes=6)   # أول فحص بعد اكتمال شمعة التأكيد
            mins = now.hour * 60 + now.minute
            if mins < W.ALERT_START or mins > W.ALERT_END:
                continue
            sub = df.iloc[start:i + 2]
            n_analyze += 1
            try:
                r, why = W.analyze(sym, sub, now, {sym: dtr})
            except Exception as e:
                print(f"[bt-err] {sym} {D} {e}"); continue
            if not r or r["type"] != "entry":
                continue
            if earn_block:
                rows.append(dict(date=str(D), sym=sym, grade=r["grade"], pattern=r["pattern"], score=r["score"],
                                 alert_time=now.strftime("%H:%M"), outcome="earn-skip", entry=r["entry"]))
                break
            plan = W.build_plan(r)
            entry, target, stop = r["entry"], plan["target"], plan["stop"]
            t1 = round(entry * 1.01, 2)
            j0 = i + 2                                     # الشمعة اللي يدخل فيها فعليًا
            day_end = int(pos[-1])
            if j0 > day_end:
                break
            fill = op[j0]
            outcome, exit_px, bars_to = "none", cl[day_end], day_end - j0 + 1
            out1, bars1 = "none", None
            for j in range(j0, day_end + 1):
                if outcome == "none":
                    if lo[j] <= stop:
                        outcome, exit_px, bars_to = "stop", stop, j - j0 + 1
                    elif hi[j] >= target:
                        outcome, exit_px, bars_to = "target", target, j - j0 + 1
                if out1 == "none":
                    if lo[j] <= stop:
                        out1, bars1 = "stop", j - j0 + 1
                    elif hi[j] >= t1:
                        out1, bars1 = "target", j - j0 + 1
                if outcome != "none" and out1 != "none":
                    break
            seg_hi = float(hi[j0:day_end + 1].max()); seg_lo = float(lo[j0:day_end + 1].min())
            # سوينق: نفس الوقف/الهدف لكن نصبر حتى 1–3 جلسات بعد يوم الدخول (مع فجوات الافتتاح)
            swing = {}
            for h in (1, 2, 3):
                if di + h >= len(days):
                    swing[h] = None; continue
                end_h = int(np.where(dates == days[di + h])[0][-1])
                o_h, x_h, b_h = walk(j0, end_h, stop, target, dates, op, hi, lo, cl)
                swing[h] = dict(outcome=o_h, exit_pct=round((x_h / fill - 1) * 100, 2),
                                close_pct=round((cl[end_h] / fill - 1) * 100, 2),
                                max_up=round((float(hi[j0:end_h + 1].max()) / fill - 1) * 100, 2))
            rows.append(dict(
                date=str(D), sym=sym, grade=r["grade"], pattern=r["pattern"], score=r["score"],
                alert_time=now.strftime("%H:%M"), whale_time=r["whale_time"], entry=entry, fill=round(float(fill), 2),
                slip_pct=round((fill / entry - 1) * 100, 2), target=target, stop=stop,
                outcome=outcome, exit_pct=round((exit_px / fill - 1) * 100, 2), minutes=bars_to * 5,
                max_up_pct=round((seg_hi / fill - 1) * 100, 2), max_dn_pct=round((seg_lo / fill - 1) * 100, 2),
                outcome_1pct=out1, minutes_1pct=(bars1 * 5 if bars1 else ""),
                spike=r["spike"], pace=r["pace"], clv=r["clv"], rsi=r["rsi"], room=r["room"],
                wall_up=r["wall_up"] if r["wall_up"] else "", triangle=r["triangle"], base=r["base"],
                **{f"swing{h}_{k}": (swing[h][k] if swing[h] else "") for h in (1, 2, 3)
                   for k in ("outcome", "exit_pct", "close_pct", "max_up")}))
            break                                          # تنبيه دخول واحد لكل سهم باليوم
    return rows, n_analyze


# ============================ الملخص ============================
def pct(a, b):
    return f"{(100.0 * a / b):.0f}%" if b else "—"


def summarize(rows, n_days, n_syms):
    ev = [r for r in rows if r["outcome"] != "earn-skip"]
    skipped = len(rows) - len(ev)
    L = []
    L.append(f"📊 اختبار تاريخي — رادار الحيتان v3 | {n_syms} سهم حلال | {n_days} يوم تداول")
    if not ev:
        L.append("ما طلعت أي إشارة دخول بالفترة (الفلاتر صارمة).")
        return "\n".join(L)
    n = len(ev)
    t = sum(r["outcome"] == "target" for r in ev); s = sum(r["outcome"] == "stop" for r in ev); z = n - t - s
    tot = sum(r["exit_pct"] for r in ev); avg = tot / n
    t1 = sum(r["outcome_1pct"] == "target" for r in ev); s1 = sum(r["outcome_1pct"] == "stop" for r in ev)
    L.append(f"إشارات الدخول: {n} (≈ {n / max(n_days, 1):.1f} باليوم) | محظورة بسبب أرباح: {skipped}")
    L.append(f"هدف +2% ✅ {t} ({pct(t, n)}) | وقف ❌ {s} ({pct(s, n)}) | بدون (خروج بالإقفال) {z} ({pct(z, n)})")
    L.append(f"متوسط الصفقة {avg:+.2f}% | المجموع {tot:+.1f}% | متوسط أعلى ارتفاع بعد الدخول {np.mean([r['max_up_pct'] for r in ev]):+.2f}%")
    L.append(f"لو الهدف 1% بدل 2%: هدف ✅ {t1} ({pct(t1, n)}) | وقف ❌ {s1} ({pct(s1, n)})")
    for g in ("A", "B"):
        e = [r for r in ev if r["grade"] == g]
        if e:
            tg = sum(r["outcome"] == "target" for r in e); sg = sum(r["outcome"] == "stop" for r in e)
            L.append(f"درجة {g}: {len(e)} إشارة | هدف {pct(tg, len(e))} | وقف {pct(sg, len(e))} | متوسط {np.mean([r['exit_pct'] for r in e]):+.2f}%")
    for p in sorted({r["pattern"] for r in ev}):
        e = [r for r in ev if r["pattern"] == p]
        tg = sum(r["outcome"] == "target" for r in e); sg = sum(r["outcome"] == "stop" for r in e)
        L.append(f"{p}: {len(e)} | هدف {pct(tg, len(e))} | وقف {pct(sg, len(e))} | متوسط {np.mean([r['exit_pct'] for r in e]):+.2f}%")
    for h in range(9, 16):
        e = [r for r in ev if int(r["alert_time"][:2]) == h]
        if e:
            tg = sum(r["outcome"] == "target" for r in e); sg = sum(r["outcome"] == "stop" for r in e)
            L.append(f"الساعة {h}:xx نيويورك ({h + 7}:xx السعودية): {len(e)} | هدف {pct(tg, len(e))} | وقف {pct(sg, len(e))} | متوسط {np.mean([r['exit_pct'] for r in e]):+.2f}%")
    hits = [r for r in ev if r["outcome"] == "target"]
    if hits:
        L.append(f"متوسط الوقت للهدف: {np.mean([r['minutes'] for r in hits]):.0f} دقيقة | متوسط انزلاق التعبئة {np.mean([r['slip_pct'] for r in ev]):+.2f}%")
    L.append("— سوينق (نفس الإشارات، نفس الوقف والهدف، لكن نصبر أيام بدل نفس اليوم) —")
    for h in (1, 2, 3):
        e = [r for r in ev if r.get(f"swing{h}_outcome") not in ("", None)]
        if not e:
            continue
        tg = sum(r[f"swing{h}_outcome"] == "target" for r in e); sg = sum(r[f"swing{h}_outcome"] == "stop" for r in e)
        L.append(f"حتى {h} جلسة بعد الدخول: {len(e)} | هدف ✅ {tg} ({pct(tg, len(e))}) | وقف ❌ {sg} ({pct(sg, len(e))}) | "
                 f"متوسط {np.mean([r[f'swing{h}_exit_pct'] for r in e]):+.2f}% | بدون وقف/هدف (إغلاق الجلسة {h}): "
                 f"{np.mean([r[f'swing{h}_close_pct'] for r in e]):+.2f}% ، موجبة {pct(sum(r[f'swing{h}_close_pct'] > 0 for r in e), len(e))} | "
                 f"متوسط أعلى ارتفاع {np.mean([r[f'swing{h}_max_up'] for r in e]):+.2f}%")
    return "\n".join(L)


def main():
    t0 = time.time()
    symbols = [s for s in W.WATCHLIST if W.halal_info(s)[0] != "haram"]
    intra, daily = fetch_all(symbols)
    print(f"[bt] data: intraday {len(intra)}/{len(symbols)} | daily {len(daily)} | {time.time() - t0:.0f}s")
    earn = {}
    for s in symbols:
        earn[s] = earnings_dates(s)
    print(f"[bt] earnings dates fetched for {sum(1 for v in earn.values() if v)} symbols | {time.time() - t0:.0f}s")
    rows, n_an = [], 0
    for s in symbols:
        df = intra.get(s)
        if df is None:
            continue
        r, k = replay_symbol(s, df, daily.get(s), earn.get(s, []))
        rows += r; n_an += k
    all_days = sorted({t.date() for df in intra.values() for t in df.index})
    n_days = max(len(all_days) - 4, 0)
    rows.sort(key=lambda r: (r["date"], r["alert_time"]))
    cols = ["date", "sym", "grade", "pattern", "score", "alert_time", "whale_time", "entry", "fill", "slip_pct",
            "target", "stop", "outcome", "exit_pct", "minutes", "max_up_pct", "max_dn_pct", "outcome_1pct",
            "minutes_1pct", "spike", "pace", "clv", "rsi", "room", "wall_up", "triangle", "base"]
    cols += [f"swing{h}_{k}" for h in (1, 2, 3) for k in ("outcome", "exit_pct", "close_pct", "max_up")]
    with open("backtest_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    summ = summarize(rows, n_days, len(intra))
    summ += f"\nالفترة: {all_days[4] if len(all_days) > 4 else '—'} → {all_days[-1] if all_days else '—'} | تحليلات: {n_an} | {time.time() - t0:.0f} ثانية"
    with open("backtest_summary.txt", "w", encoding="utf-8") as f:
        f.write(summ + "\n")
    print("[bt-summary]\n" + summ)
    for r in rows:
        print(f"[bt-row] {r['date']} {r['alert_time']} {r['sym']:5} {r['grade']} {r['outcome']:9} "
              f"{r.get('exit_pct', ''):>6} maxup={r.get('max_up_pct', '')} {r['pattern']} score={r['score']}")


if __name__ == "__main__":
    main()
