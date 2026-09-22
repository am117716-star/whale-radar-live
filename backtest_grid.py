#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تجربة الشبكة (Grid) لرادار الحيتان — بدل التخمين:
1) نجمع أكبر عدد من "أحداث الحوت" بفلاتر خفيفة (فوليوم ≥ 2×، وتيرة ≥ 1×، شمعة خضراء، CLV ≥ 0.5)
   على كل الأسهم الحلال لآخر ~59 يوم (شموع 5 دقايق).
2) نسجّل صفات كل حدث (قوة الفوليوم، الوتيرة، رافع/لا، تأكيد/لا، RSI، النموذج، الاتجاه اليومي،
   تذبذب السهم اليومي ATR%، الساعة، المسافة للمقاومة...).
3) نقيّم كل حدث تحت شبكة إعدادات: هدف 0.5/1/1.5/2% × وقف (قاع الحوت / −0.5% / −1% / −2% / ATR) × أفق (نفس اليوم / +1 يوم).
4) نلخّص: أي إعداد أفضل؟ وهل الأسهم المتذبذبة أفضل فعلًا؟ وأي ساعة/نموذج/قوة تفرق؟
المخرجات: grid_results.csv + grid_summary.txt (+ السجل).
"""
import os, sys, time, csv, datetime as dt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import live_whale as W
except ImportError:
    import live_whale_v3 as W
import backtest as B

DAYS = int(os.environ.get("DAYS", "59"))
MIN_SPIKE, MIN_PACE, MIN_CLV = 2.0, 1.0, 0.5
MAX_EVENTS_PER_DAY, MIN_GAP_BARS = 3, 6
TARGETS = (0.5, 1.0, 1.5, 2.0)
STOPS = ("whale", "p05", "p10", "p20", "atr1")
HORIZONS = ("d0", "d1")
STOP_AR = {"whale": "قاع الحوت", "p05": "−0.5%", "p10": "−1%", "p20": "−2%", "atr1": "1×ATR"}


def pct(a, b):
    return f"{100.0 * a / b:.0f}%" if b else "—"


def atr_pct(h, l, c, n=14):
    if len(c) < n + 2:
        return float("nan"), float("nan")
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    a = float(np.mean(tr[-n:]))
    return a, a / float(c[-1]) * 100


def features(sym, df, arrays, i, day_pos, day_idx, days, dtr, atr_d):
    """صفات الحدث عند شمعة الحوت i (شمعة التأكيد i+1). يعيد dict أو None."""
    op, hi, lo, cl, vol = arrays
    pos = day_pos[days[day_idx]]
    k = int(np.where(pos == i)[0][0])          # ترتيب شمعة الحوت داخل اليوم
    n = k + 2                                   # شموع اليوم حتى التأكيد
    if k < 2 or i + 2 > pos[-1]:
        return None
    hist_lo = max(0, i - 390)
    H, L, C, V = hi[hist_lo:i], lo[hist_lo:i], cl[hist_lo:i], vol[hist_lo:i]
    if len(C) < 80:
        return None
    med_vol = float(np.median(V[-20:]))
    if med_vol <= 0:
        return None
    spike = vol[i] / med_vol
    rng = hi[i] - lo[i]
    avg_rng = float(np.mean(H[-20:] - L[-20:]))
    rng_x = rng / avg_rng if avg_rng > 0 else 0.0
    clv = (cl[i] - lo[i]) / rng if rng > 0 else 0.5
    green = cl[i] >= op[i]
    if not green or clv < MIN_CLV or spike < MIN_SPIKE:
        return None
    # وتيرة اليوم مقابل آخر 4 أيام
    d_sl = pos[:n]
    vol_today = float(vol[d_sl].sum())
    bases = []
    for pd_ in days[max(0, day_idx - 4):day_idx]:
        pp = day_pos[pd_]
        if len(pp) >= max(6, int(n * 0.8)):
            bases.append(float(vol[pp[:n]].sum()))
    pace = vol_today / float(np.mean(bases)) if bases else 1.0
    if pace < MIN_PACE:
        return None
    tp = (hi[d_sl] + lo[d_sl] + cl[d_sl]) / 3.0
    vwap = float((tp * vol[d_sl]).sum() / vol_today) if vol_today > 0 else cl[i + 1]
    dw = pos[:n - 1]
    vw = float(vol[dw].sum())
    vwap_w = float((((hi[dw] + lo[dw] + cl[dw]) / 3.0) * vol[dw]).sum() / vw) if vw > 0 else vwap
    local_high = float(H[-12:].max()); res_lvl = float(H[-78:].max()); sup_lvl = float(L[-24:].min())
    entry = float(cl[i + 1])
    breakout = cl[i] >= res_lvl
    room = (res_lvl - entry) / entry * 100 if not breakout else 9.9 * 100
    rsi = W.rsi_last(C)
    highs, lows = H[-24:], L[-24:]
    top = float(highs.max()); touches = int((highs >= top * (1 - 0.0025)).sum())
    lo_slope = W.slope_per_bar(lows) / entry; hi_slope = W.slope_per_bar(highs) / entry
    triangle = bool(touches >= 2 and lo_slope > 0.0001 and lows[-1] > lows[0] and abs(hi_slope) < 0.0002 and cl[i] > top)
    b_rng = (float(H[-12:].max()) - float(L[-12:].min())) / entry
    base = bool((not triangle) and b_rng <= 0.010 and cl[i] > float(H[-12:].max()))
    pattern = "مثلث" if triangle else ("قاعدة" if base else "بدون")
    new_high = cl[i] >= local_high
    above_vwap_w = cl[i] >= vwap_w
    lifting = bool(clv >= W.CLV_LIFT and rng_x >= W.RANGE_X and new_high and above_vwap_w)
    confirmed = bool(cl[i + 1] >= (hi[i] + lo[i]) / 2.0 and cl[i + 1] >= vwap)
    sc = min((spike / W.SPIKE_X) * 35, 45) + min((pace / W.PACE_X) * 20, 30) + (15 if clv >= W.CLV_LIFT else 8)
    sc += (10 if above_vwap_w else 0) + (15 if triangle else (8 if base else 0)) + (5 if W.RSI_MIN <= rsi <= W.RSI_MAX else 0)
    score = int(min(round(sc), 100))
    atr5_abs, atr5_pct = atr_pct(H, L, C)
    trend = bool(dtr and dtr["trend"]); near_low = bool(dtr and dtr["near_low"])
    v3 = bool(spike >= W.SPIKE_X and pace >= W.PACE_X and trend and not near_low and lifting and confirmed
              and W.RSI_MIN <= rsi <= W.RSI_MAX and (breakout or room >= W.ROOM_MIN * 100) and score >= W.MIN_SCORE)
    t = df.index[i + 1]
    return dict(sym=sym, date=str(days[day_idx]), whale_time=df.index[i].strftime("%H:%M"), hour=int(t.hour),
                bar_k=k, entry=round(entry, 2), whale_low=round(float(lo[i]), 2), whale_high=round(float(hi[i]), 2),
                spike=round(float(spike), 2), pace=round(float(pace), 2), clv=round(float(clv), 2), rng_x=round(float(rng_x), 2),
                new_high=new_high, above_vwap=above_vwap_w, lifting=lifting, confirmed=confirmed, rsi=round(float(rsi), 1),
                pattern=pattern, score=score, room_pct=round(float(min(room, 999)), 2), breakout=bool(breakout),
                trend=trend, near_low=near_low, atr5_pct=round(float(atr5_pct), 3), atr5_abs=float(atr5_abs),
                atr_d_pct=round(float(atr_d), 2), v3=v3)


def evaluate_event(ev, arrays, i, pos, day_pos, days, day_idx):
    op, hi, lo, cl, vol = arrays
    dates = None
    j0 = i + 2; day_end = int(pos[-1])
    fill = float(op[j0]); entry = ev["entry"]
    out = dict(fill=round(fill, 2), slip_pct=round((fill / entry - 1) * 100, 2))
    seg_hi = float(hi[j0:day_end + 1].max()); seg_lo = float(lo[j0:day_end + 1].min())
    out["mfe_d0"] = round((seg_hi / fill - 1) * 100, 2); out["mae_d0"] = round((seg_lo / fill - 1) * 100, 2)
    out["close_d0"] = round((cl[day_end] / fill - 1) * 100, 2)
    end1 = int(day_pos[days[day_idx + 1]][-1]) if day_idx + 1 < len(days) else None
    if end1 is not None:
        out["mfe_d1"] = round((float(hi[j0:end1 + 1].max()) / fill - 1) * 100, 2)
        out["close_d1"] = round((cl[end1] / fill - 1) * 100, 2)
    stops = {"whale": max(entry * (1 - W.STOP_PCT), ev["whale_low"] * 0.998), "p05": entry * 0.995,
             "p10": entry * 0.99, "p20": entry * 0.98, "atr1": entry - ev["atr5_abs"] if ev["atr5_abs"] == ev["atr5_abs"] else entry * 0.99}
    for s_name, stop in stops.items():
        out[f"stoppct_{s_name}"] = round((1 - stop / entry) * 100, 2)
        for tgt in TARGETS:
            target = entry * (1 + tgt / 100)
            for hz in HORIZONS:
                j_end = day_end if hz == "d0" else end1
                if j_end is None:
                    continue
                o, x, b = walk_gap(j0, j_end, stop, target, day_end, op, hi, lo, cl)
                key = f"{hz}_t{tgt}_{s_name}"
                out["o_" + key] = o; out["p_" + key] = round((x / fill - 1) * 100, 2)
    return out


def walk_gap(j0, j_end, stop, target, day_end, op, hi, lo, cl):
    """مثل backtest.walk لكن فجوة الجلسة معروفة من day_end."""
    for j in range(j0, j_end + 1):
        if j == day_end + 1:
            if op[j] <= stop:
                return "stop", float(op[j]), j - j0 + 1
            if op[j] >= target:
                return "target", float(op[j]), j - j0 + 1
        if lo[j] <= stop:
            return "stop", float(stop), j - j0 + 1
        if hi[j] >= target:
            return "target", float(target), j - j0 + 1
    return "none", float(cl[j_end]), j_end - j0 + 1


def replay(sym, df, ddf):
    dates = np.array([t.date() for t in df.index])
    days = sorted(set(dates))
    day_pos = {d: np.where(dates == d)[0] for d in days}
    arrays = tuple(df[c].values.astype(float) for c in ("Open", "High", "Low", "Close", "Volume"))
    op, hi, lo, cl, vol = arrays
    med20 = pd.Series(vol).rolling(20).median().shift(1).values
    rows = []
    for di, D in enumerate(days):
        if di < 4 or len(day_pos[D]) < 30:
            continue
        pos = day_pos[D]
        dtr = B.daily_as_of(ddf, D) if ddf is not None else None
        sub = ddf[[d.date() < D for d in ddf.index]] if ddf is not None else None
        atr_d = atr_pct(sub["High"].values.astype(float), sub["Low"].values.astype(float), sub["Close"].values.astype(float))[1] if sub is not None and len(sub) > 20 else float("nan")
        n_ev, last_i = 0, -999
        for k in range(2, len(pos) - 2):
            i = int(pos[k])
            if not (med20[i] > 0 and vol[i] / med20[i] >= MIN_SPIKE):
                continue
            if i - last_i < MIN_GAP_BARS:
                continue
            t = df.index[i + 1].to_pydatetime() + dt.timedelta(minutes=6)
            mins = t.hour * 60 + t.minute
            if mins < W.ALERT_START or mins > W.ALERT_END:
                continue
            ev = features(sym, df, arrays, i, day_pos, di, days, dtr, atr_d)
            if ev is None:
                continue
            ev["first_of_day"] = (n_ev == 0)
            ev.update(evaluate_event(ev, arrays, i, pos, day_pos, days, di))
            rows.append(ev); n_ev += 1; last_i = i
            if n_ev >= MAX_EVENTS_PER_DAY:
                break
    return rows


# ============================ الملخص ============================
def stats(rows, key):
    o = [r.get("o_" + key) for r in rows]; p = [r.get("p_" + key) for r in rows]
    pairs = [(a, b) for a, b in zip(o, p) if a is not None and b is not None]
    if not pairs:
        return None
    n = len(pairs); t = sum(a == "target" for a, _ in pairs); s = sum(a == "stop" for a, _ in pairs)
    wins = sum(b for _, b in pairs if b > 0); losses = -sum(b for _, b in pairs if b < 0)
    return dict(n=n, t=t, s=s, z=n - t - s, avg=float(np.mean([b for _, b in pairs])), tot=sum(b for _, b in pairs),
                pf=(wins / losses if losses > 0 else float("inf")), pos=sum(b > 0 for _, b in pairs))


def line(label, st):
    if not st:
        return f"{label}: —"
    return (f"{label}: n={st['n']} | هدف {st['t']} ({pct(st['t'], st['n'])}) | وقف {st['s']} ({pct(st['s'], st['n'])}) | "
            f"بدون {st['z']} | متوسط {st['avg']:+.2f}% | مجموع {st['tot']:+.1f}% | ربح/خسارة {st['pf']:.2f}")


def bucket(v, edges, labels):
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


def seg_table(rows, key, seg_fn, title):
    groups = {}
    for r in rows:
        g = seg_fn(r)
        if g is None:
            continue
        groups.setdefault(g, []).append(r)
    L = [f"  · {title}:"]
    for g in sorted(groups, key=lambda x: str(x)):
        st = stats(groups[g], key)
        if st and st["n"] >= 5:
            L.append("    " + line(str(g), st))
    return L


def summarize(rows, n_days, n_syms):
    L = [f"🧪 تجربة الشبكة — رادار الحيتان | {n_syms} سهم حلال | {n_days} يوم تداول | أحداث حوت (فلاتر خفيفة): {len(rows)}"]
    if not rows:
        return "\n".join(L + ["لا أحداث."])
    v3 = [r for r in rows if r["v3"]]
    L.append(f"منها تطابق فلاتر النسخة 3 كاملة: {len(v3)} | رافع: {sum(r['lifting'] for r in rows)} | مؤكد: {sum(r['confirmed'] for r in rows)}")
    L.append(f"كم يطلع السهم بعد الحدث (نفس اليوم)? متوسط أعلى ارتفاع {np.mean([r['mfe_d0'] for r in rows]):+.2f}% | الوسيط {np.median([r['mfe_d0'] for r in rows]):+.2f}% | "
             f"أعلى هبوط {np.mean([r['mae_d0'] for r in rows]):+.2f}% | إغلاق اليوم {np.mean([r['close_d0'] for r in rows]):+.2f}% (موجب {pct(sum(r['close_d0'] > 0 for r in rows), len(rows))})")
    L.append("")
    L.append("=== 1) شبكة الإعدادات — كل الأحداث (نفس اليوم) ===")
    best = []
    for s_name in STOPS:
        for tgt in TARGETS:
            key = f"d0_t{tgt}_{s_name}"
            st = stats(rows, key)
            if st:
                best.append((st["avg"], key, st))
                L.append(line(f"هدف {tgt}% / وقف {STOP_AR[s_name]}", st))
    L.append("")
    L.append("=== 2) نفس الشبكة — أفق +1 يوم ===")
    for s_name in STOPS:
        for tgt in TARGETS:
            st = stats(rows, f"d1_t{tgt}_{s_name}")
            if st:
                L.append(line(f"هدف {tgt}% / وقف {STOP_AR[s_name]} (+1 يوم)", st))
    L.append("")
    L.append("=== 3) أحداث النسخة 3 فقط (الفلاتر الكاملة) ===")
    for s_name in ("whale", "p10", "atr1"):
        for tgt in (1.0, 1.5, 2.0):
            st = stats(v3, f"d0_t{tgt}_{s_name}")
            if st:
                L.append(line(f"v3 هدف {tgt}% / وقف {STOP_AR[s_name]}", st))
    L.append("")
    best.sort(key=lambda x: -x[0])
    heads = [k for _, k, _ in best[:2]] + ["d0_t1.0_whale", "d0_t2.0_whale"]
    heads = list(dict.fromkeys(heads))
    segs = [
        ("تذبذب السهم اليومي ATR%", lambda r: bucket(r["atr_d_pct"], (1.5, 2.5, 4.0), ("أ) هادي <1.5%", "ب) 1.5–2.5%", "ج) 2.5–4%", "د) متذبذب >4%")) if r["atr_d_pct"] == r["atr_d_pct"] else None),
        ("الساعة (نيويورك)", lambda r: f"{r['hour']:02d}:xx"),
        ("قوة الفوليوم", lambda r: bucket(r["spike"], (3, 5, 8), ("2–3×", "3–5×", "5–8×", ">8×"))),
        ("حوت رافع؟", lambda r: "رافع" if r["lifting"] else "غير رافع"),
        ("تأكيد الشمعة التالية؟", lambda r: "مؤكد" if r["confirmed"] else "غير مؤكد"),
        ("النموذج", lambda r: r["pattern"]),
        ("الاتجاه اليومي", lambda r: "صاعد" if r["trend"] else "هابط/جانبي"),
        ("RSI قبل الحوت", lambda r: bucket(r["rsi"], (45, 55, 65, 75), ("<45", "45–55", "55–65", "65–75", ">75"))),
        ("القوة /100", lambda r: bucket(r["score"], (60, 75, 90), ("<60", "60–75", "75–90", "≥90"))),
        ("المسافة للمقاومة", lambda r: "اختراق" if r["breakout"] else bucket(r["room_pct"], (0.5, 1.5, 3.0), ("<0.5%", "0.5–1.5%", "1.5–3%", ">3%"))),
        ("أول حدث باليوم؟", lambda r: "أول" if r["first_of_day"] else "لاحق"),
    ]
    for key in heads:
        tgt = key.split("_t")[1].split("_")[0]; s_name = key.split("_")[-1]
        L.append(f"=== 4) الشرائح — إعداد: هدف {tgt}% / وقف {STOP_AR[s_name]} (نفس اليوم) ===")
        for title, fn in segs:
            L += seg_table(rows, key, fn, title)
        L.append("")
    # أفضل ارتفاع حسب التذبذب — يجاوب سؤال «الأسهم المتذبذبة أفضل؟» مباشرة
    L.append("=== 5) أعلى ارتفاع بعد الدخول (نفس اليوم) حسب تذبذب السهم ===")
    for lab in ("أ) هادي <1.5%", "ب) 1.5–2.5%", "ج) 2.5–4%", "د) متذبذب >4%"):
        g = [r for r in rows if r["atr_d_pct"] == r["atr_d_pct"] and bucket(r["atr_d_pct"], (1.5, 2.5, 4.0), ("أ) هادي <1.5%", "ب) 1.5–2.5%", "ج) 2.5–4%", "د) متذبذب >4%")) == lab]
        if g:
            L.append(f"  {lab}: n={len(g)} | أعلى ارتفاع متوسط {np.mean([r['mfe_d0'] for r in g]):+.2f}% | أعلى هبوط {np.mean([r['mae_d0'] for r in g]):+.2f}% | "
                     f"وصل 1%: {pct(sum(r['mfe_d0'] >= 1 for r in g), len(g))} | وصل 2%: {pct(sum(r['mfe_d0'] >= 2 for r in g), len(g))} | إغلاق موجب {pct(sum(r['close_d0'] > 0 for r in g), len(g))}")
    L.append("")
    L.append("=== 6) حسب السهم (أحداث ≥ 8) — إعداد هدف 1% / وقف −1% ===")
    per = {}
    for r in rows:
        per.setdefault(r["sym"], []).append(r)
    items = []
    for s, g in per.items():
        st = stats(g, "d0_t1.0_p10")
        if st and st["n"] >= 8:
            items.append((st["avg"], s, st, np.mean([r["atr_d_pct"] for r in g if r["atr_d_pct"] == r["atr_d_pct"]] or [float("nan")])))
    items.sort(key=lambda x: -x[0])
    for avg, s, st, a in items:
        L.append(f"  {s:5} ATR {a:.1f}% | " + line("", st)[2:])
    return "\n".join(L)


def main():
    t0 = time.time()
    symbols = [s for s in W.WATCHLIST if W.halal_info(s)[0] != "haram"]
    intra, daily = B.fetch_all(symbols)
    print(f"[grid] data: intraday {len(intra)}/{len(symbols)} | daily {len(daily)} | {time.time() - t0:.0f}s")
    rows = []
    for s in symbols:
        df = intra.get(s)
        if df is None:
            continue
        try:
            rows += replay(s, df, daily.get(s))
        except Exception as e:
            print(f"[grid-err] {s}: {type(e).__name__}: {e}")
    all_days = sorted({t.date() for df in intra.values() for t in df.index})
    n_days = max(len(all_days) - 4, 0)
    rows.sort(key=lambda r: (r["date"], r["whale_time"], r["sym"]))
    cols = list(dict.fromkeys(k for r in rows for k in r.keys()))
    with open("grid_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    summ = summarize(rows, n_days, len(intra))
    summ += f"\nالفترة: {all_days[4] if len(all_days) > 4 else '—'} → {all_days[-1] if all_days else '—'} | {time.time() - t0:.0f} ثانية"
    with open("grid_summary.txt", "w", encoding="utf-8") as f:
        f.write(summ + "\n")
    print("[grid-summary]\n" + summ)


if __name__ == "__main__":
    main()
