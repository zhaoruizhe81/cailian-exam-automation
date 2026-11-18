#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 4. 支付借款利息（任务4 支付借款利息：票据采集（3 张）→ 银行回单调整至其他票据 → 手工凭证）。

用法:
  python3 task4c.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]
"""
import argparse
import sys

import cailian3 as c3

TITLE = "4. 支付借款利息"
DATE = (2022, 12, 1)
# 利息发票为增值税普票，进项税不得抵扣，全额计入财务费用—利息支出
ENTRIES = [('支付借款利息', '660302', 116400.0, 'd'), ('支付借款利息', '100201', 116400.0, 'c')]
IMAGE = None


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
        bot.collect_all("t4_collect")
        bot.adjust_current("其他票据")
        bot.make_voucher(DATE, ENTRIES, image=args.image or None, tag="t4_voucher")
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
