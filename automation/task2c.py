#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 2. 投资决策与投资业务核算（答题板 spreadComEXCEL_TYDTB）。

方案A：200 辆×10 万，购置税 10% → 原值 2200 万；年租 300 天×200 元×200 辆=1200 万
方案B：50 辆×40 万，购置税 10% → 原值 2200 万；年租 250 天×900 元×50 辆=1125 万
年数总和法折旧、税率 25%、必要报酬率 10%。

用法:
  python3 task2c.py --user 1111111111111 --exam-url "..." [--dry-run] [--headless]
"""
import argparse
import sys
from decimal import Decimal, ROUND_HALF_UP

import cailian3 as c3

TITLE = "2. 任务2 投资决策与投资业务核算"


def rnd(x, n=2):
    q = Decimal("1." + "0" * n)
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


def build():
    cells = []
    # ---------------- 表1 方案A ----------------
    cost = 2200.0
    dep = [rnd(cost * k / 36) for k in (8, 7, 6, 5, 4, 3, 2, 1)]
    tax = [rnd(d * 0.25) for d in dep]
    rent = 900.0
    maint = [-37.5] * 5 + [-52.5] * 3
    ins, oth, fix = -52.5, -7.5, -18.75
    cf = [-2260.0] + [
        rnd(rent + tax[i] + maint[i] + ins + oth + fix) for i in range(8)
    ]
    fac = [1.0] + [rnd(1 / 1.1 ** n, 4) for n in range(1, 9)]
    pv = [rnd(cf[i] * fac[i]) for i in range(9)]
    npv, eaa = rnd(sum(pv)), rnd(sum(pv) / 5.3349)

    cells.append((4, 2, -cost))
    for i in range(8):
        c = 3 + i
        cells += [(5, c, rent), (6, c, dep[i]), (7, c, tax[i]),
                  (8, c, maint[i]), (9, c, ins), (10, c, oth),
                  (11, c, fix), (12, c, cf[i + 1])]
    cells += [(9, 2, ins), (10, 2, oth), (12, 2, cf[0])]
    cells.append((14, 2, 0.1))
    for i in range(9):
        cells += [(15, 2 + i, fac[i]), (16, 2 + i, pv[i])]
    cells += [(17, 2, npv), (18, 2, eaa)]

    # ---------------- 表2 方案B ----------------
    dep = [rnd(cost * k / 55) for k in range(10, 0, -1)]
    tax = [rnd(d * 0.25) for d in dep]
    rent = 843.75
    maint = [-15.0] * 6 + [-30.0] * 4
    ins, oth, fix = -93.75, -15.0, -7.5
    cf = [-2308.75] + [
        rnd(rent + tax[i] + maint[i] + ins + oth + fix) for i in range(10)
    ]
    fac = [1.0] + [rnd(1 / 1.1 ** n, 4) for n in range(1, 11)]
    pv = [rnd(cf[i] * fac[i]) for i in range(11)]
    npv2, eaa2 = rnd(sum(pv)), rnd(sum(pv) / 6.1446)

    cells.append((23, 2, -cost))
    for i in range(10):
        c = 3 + i
        cells += [(24, c, rent), (25, c, dep[i]), (26, c, tax[i]),
                  (27, c, maint[i]), (28, c, ins), (29, c, oth),
                  (30, c, fix), (31, c, cf[i + 1])]
    cells += [(28, 2, ins), (29, 2, oth), (31, 2, cf[0])]
    cells.append((33, 2, 0.1))
    for i in range(11):
        cells += [(34, 2 + i, fac[i]), (35, 2 + i, pv[i])]
    cells += [(36, 2, npv2), (37, 2, eaa2)]

    # ---------------- 表3 / 表4 ----------------
    pick = "方案A" if eaa >= eaa2 else "方案B"
    cells.append((41, 5, pick))
    for r, ans in ((45, "正确"), (46, "错误"), (47, "错误"),
                   (48, "正确"), (49, "错误")):
        cells.append((r, 6, ans))
    return cells, dict(npv=npv, eaa=eaa, npv2=npv2, eaa2=eaa2, pick=pick)


def sheet_frame(page, timeout=60):
    import time
    end = time.time() + timeout
    while time.time() < end:
        for f in page.frames:
            try:
                if "onlineexcel" in f.url and f.evaluate(
                        "()=>!!document.getElementById('spreadComEXCEL_TYDTB')"):
                    return f
            except Exception:
                pass
        page.wait_for_timeout(1000)
    raise RuntimeError("答题板未加载")


def main():
    ap = c3.common_args(argparse.ArgumentParser())
    args = ap.parse_args()
    cells, meta = build()
    c3.log(f"方案A NPV={meta['npv']} EAA={meta['eaa']} / "
           f"方案B NPV={meta['npv2']} EAA={meta['eaa2']} → {meta['pick']}")

    p, ctx, page = c3.launch(args)
    bot = c3.C3(page, c3.HERE / "out")
    try:
        bot.goto_task(TITLE)
        bot.open_business()
        f = sheet_frame(page)
        f.evaluate(
            """(cells)=>{
                const el=document.getElementById('spreadComEXCEL_TYDTB');
                const sp=el.__vue__.$data.spread, s=sp.getSheet(0);
                for(const [r,c,v] of cells) s.setValue(r,c,v);
                sp.repaint();
            }""", cells)
        page.wait_for_timeout(1500)
        f.evaluate(
            """()=>{const b=[...document.querySelectorAll('button')]
                 .find(x=>x.offsetWidth>0&&x.innerText.trim()==='保存'); if(b)b.click();}"""
        )
        page.wait_for_timeout(4000)
        body = f.inner_text("body")
        c3.log("答题板保存: " + ("成功" if "保存成功" in body else "未捕获提示（继续）"))
        bot.shot("t2_sheet")
        if args.dry_run:
            c3.log("dry-run：已保存，跳过提交结果")
        else:
            bot.submit()
        c3.log(bot.nav_ok())
    finally:
        ctx.close()
        p.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
