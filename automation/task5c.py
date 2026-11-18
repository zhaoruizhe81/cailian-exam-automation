#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 5. 缴纳税费（任务5 缴纳税费：银行回单调整至其他票据 → 6 行凭证）。

用法:
  python3 task5c.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]
"""
import argparse
import sys

import cailian3 as c3

TITLE = "5. 缴纳税费"
DATE = (2022, 12, 8)
ENTRIES = [('缴纳增值税', '222102', 268900.0, 'd'), ('缴纳城建税', '222126', 18823.0, 'd'), ('缴纳教育费附加', '222127', 8067.0, 'd'), ('缴纳地方教育附加', '222133', 5378.0, 'd'), ('缴纳个人所得税', '222131', 1500.0, 'd'), ('缴纳各项税费', '100201', 302668.0, 'c')]
IMAGE = 'data3/t5_tax.png'


def main():
    ap = c3.common_args(argparse.ArgumentParser())
    ap.add_argument("--image", default=str((c3.HERE / IMAGE)) if IMAGE else "")
    args = ap.parse_args()

    p, ctx, page = c3.launch(args)
    bot = c3.C3(page, c3.HERE / "out")
    try:
        bot.goto_task(TITLE)
        bot.open_business()
        bot.nav("智能票据", "票据采集")
        bot.collect_all("t5_collect")
        bot.adjust_current("其他票据")
        bot.make_voucher(DATE, ENTRIES, image=args.image or None, tag="t5_voucher")
        if args.dry_run:
            c3.log("dry-run：已保存凭证，跳过提交结果")
        else:
            bot.submit()
    finally:
        ctx.close()
        p.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
