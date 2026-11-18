#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 任务5 税务优化 · 第 11 题（task-item 11）：家庭总税负最低方案。

最优方案（全部专项附加扣除给边际税率更高的黄某）：
  住房租金 18,000（上海 1500/月，黄某 100%）
  子女教育 12,000（黄某 100%，子女 2021-01 满 3 岁）
  赡养老人  9,000（黄某 100%，父亲 2021-04 满 60 岁，1000×9 个月）
  黄某：200000-60000-16000-39000 = 85000 → 85000×10%-2520 = 5980
  熊某：80000-60000-2500 = 17500 → 17500×3% = 525
  住房贷款 0（贷款利息 12,000 < 租金 18,000，二者不可同时享受）

用法:
  python3 task11c.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]
"""
import argparse
import sys

import cailian3 as c3

INDEX = 11

# (row, col, value) —— 0-based，与在线表格“税务优化方案计算表”一致
CELLS = [
    (4, 4, 200000), (4, 5, 80000),           # 工资收入
    (5, 4, 16000), (5, 5, 2500),             # 专项扣除
    (6, 4, 0), (6, 5, 0),                    # 住房贷款（不享受）
    (7, 2, "黄某"), (7, 3, "100%"), (7, 4, 12000), (7, 5, 0),   # 子女教育
    (8, 2, "黄某"), (8, 3, "100%"), (8, 4, 9000), (8, 5, 0),    # 赡养老人
    (9, 2, "黄某"), (9, 3, "100%"), (9, 4, 18000), (9, 5, 0),   # 租房租金
    (10, 4, 85000), (10, 5, 17500),          # 综合所得应纳税所得额
    (11, 4, 5980), (11, 5, 525),             # 全年应纳个人所得税额
]


def main():
    ap = c3.common_args(argparse.ArgumentParser())
    args = ap.parse_args()
    p, ctx, page = c3.launch(args)
    bot = c3.C3(page, c3.HERE / "out")
    try:
        bot.goto_task_index(INDEX)
        bot.open_business()
        bot.fill_onlineexcel(CELLS, tag="t11_excel")
        if args.dry_run:
            c3.log("dry-run：已保存在线表格，跳过提交结果")
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
