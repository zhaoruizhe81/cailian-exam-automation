#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.1.1「数据校验、科目映射」· 第二套（FSTZG 项目 XM0044）

第二套该任务点与第一套的配置完全一致（科目类型 1/2/4/5/6、结转科目 4103 本年利润、
坏账准备 1231→应收账款、实收资本 4001→民营资本、未审报表月份 202212），
校验逻辑全部从平台实时数据判断，因此直接复用 task211.py 的实现。

用法与 task211.py 相同:
  python3 task211b.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]
"""
import sys

import task211


if __name__ == "__main__":
    try:
        task211.main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
