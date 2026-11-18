#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 任务5 税务优化 · 第 10 题（task-item 10）。

答案：D 黄某选择享受100%扣除住房租金支出

用法:
  python3 task10c.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--headless]
"""
import argparse
import sys

import cailian3 as c3

INDEX = 10
ANSWER = "D 黄某选择享受100%扣除住房租金支出"
RADIO = "黄某选择享受100%扣除住房租金支出"


def main():
    ap = c3.common_args(argparse.ArgumentParser())
    args = ap.parse_args()
    p, ctx, page = c3.launch(args)
    bot = c3.C3(page, c3.HERE / "out")
    try:
        bot.goto_task_index(INDEX)
        bot.choose_radio(RADIO)
        c3.log("已选择: " + ANSWER)
        if not args.dry_run:
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
