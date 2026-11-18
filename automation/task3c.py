#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 3. 融资决策与融资业务核算（答题板 spreadComEXCEL_TYDTB）。

2021 收入 10000 万，2022 预计 12000 万（+20%）；非流动资产增加 100 万；
敏感资产 60%（现金5%+应收28%+存货27%），敏感负债 18%（应付账款）；
留存收益增加 340 万 → 外部筹资额 = 1300-360-340 = 600 万。
甲：股价 6 元 → 100 万股；乙：面值100/发行价120 → 5 万张，年息 50 万，税后成本 6.25%。
无差别点 EBIT = 700 万，EPS = 0.375 元/股；EBIT≤700 选甲，≥700 选乙；1200 万时选乙。

用法:
  python3 task3c.py --user 1111111111111 --exam-url "..." [--dry-run] [--headless]
"""
import argparse
import sys
import time

import cailian3 as c3

TITLE = "3. 任务3 融资决策与融资业务核算"

CELLS = [
    # 表1 资产侧
    (4, 3, 0.05), (4, 4, 600.0),
    (5, 3, 0.28), (5, 4, 3360.0),
    (6, 3, 0.27), (6, 4, 3240.0),
    (7, 4, 4100.0),
    (11, 3, 0.60), (11, 4, 11300.0),
    # 表1 负债及权益侧
    (4, 7, 0.18), (4, 8, 2160.0),
    (5, 8, 1400.0), (6, 8, 1500.0), (7, 8, 1000.0),
    (8, 8, 1900.0), (9, 8, 2740.0), (10, 8, 600.0),
    (11, 7, 0.18), (11, 8, 11300.0),
    # 表2 普通股股数
    (16, 3, 600.0), (17, 3, 6.0), (18, 3, 100.0),
    # 表3 债券
    (23, 3, 100.0), (24, 3, 120.0), (25, 3, 600.0), (26, 3, 5.0),
    (27, 3, 0.10), (28, 3, 50.0), (29, 3, 0.0625),
    # 表4 每股收益无差别点
    (34, 5, 150.0), (35, 5, 1100.0),
    (36, 5, 200.0), (37, 5, 1000.0),
    (38, 5, 700.0), (39, 5, 0.375),
    # 表5 选择方案
    (43, 5, "不大于700万元"),
    (44, 5, "不小于700万元"),
    (45, 5, "乙方案"),
]


def sheet_frame(page, timeout=60):
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
            }""", CELLS)
        page.wait_for_timeout(1500)
        f.evaluate(
            """()=>{const b=[...document.querySelectorAll('button')]
                 .find(x=>x.offsetWidth>0&&x.innerText.trim()==='保存'); if(b)b.click();}"""
        )
        page.wait_for_timeout(4000)
        body = f.inner_text("body")
        c3.log("答题板保存: " + ("成功" if "保存成功" in body else "未捕获提示（继续）"))
        bot.shot("t3_sheet")
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
