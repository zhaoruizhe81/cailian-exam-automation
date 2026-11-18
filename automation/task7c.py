#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 7. 发放工资（任务7 发放工资：银行回单（付款）→ 2 行凭证）。

用法:
  python3 task7c.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]
"""
import argparse
import sys

import cailian3 as c3

TITLE = "7. 发放工资"
DATE = (2022, 12, 15)
ENTRIES = [('发放11月工资', '221101', 115810.0, 'd'), ('发放11月工资', '100201', 115810.0, 'c')]
IMAGE = 'data3/t7_salary.png'


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
        bot.collect_all("t7_collect")
        # 本任务不调整票据类型（付款/收款回单直接制单）
        bot.make_voucher(DATE, ENTRIES, image=args.image or None, tag="t7_voucher")
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
