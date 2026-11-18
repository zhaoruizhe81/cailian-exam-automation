#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套 1. 全面预算管理（onlineexcel 预算管理五个子页面）。

数据在 task1c_data.json（0-based 行/列，按工作簿 id + sheet 序号分组）。
关键点：预算表格的「保存」只收当前**活动 sheet** 的改动，直接点保存会漏；
这里改为把整本工作簿要写的单元格构造进平台的 GLKJ_user_answer_list，
再调组件自身的 answerSave()（与点保存完全同一条保存链路），一次提交整本。

  经营目标   3 张表（单价/销量/期间费用预测）
  预算编制   6 个工作簿、21 张表（Q4 + 全年）
  预算执行   二季度销售预算分解（5/6 月）、管理费用控制表（3.20 办公费）
  预算分析   直接材料预算差异分析（因素分析法）

用法:
  python3 task1c.py --user 1111111111111 --exam-url "..." [--stage all|ysmb,bianzhi,zhixing,fenxi]
                    [--dry-run] [--headless]
"""
import argparse
import json
import sys
import time

import cailian3 as c3

TITLE = "1. 任务1 全面预算管理"
DATA = json.loads((c3.HERE / "task1c_data.json").read_text(encoding="utf-8"))

PAGES = [
    ("ysmb", "经营目标", [("经营目标", "spreadComGLKJ_JYMB")]),
    ("bianzhi", "预算编制", [
        ("采购预算", "spreadComGLKJ_CGYS"),
        ("销售预算", "spreadComGLKJ_XSYS"),
        ("生产预算", "spreadComGLKJ_SCYS"),
        ("期间费用预算", "spreadComGLKJ_QJFYYS"),
        ("资本支出预算", "spreadComGLKJ_ZBZCYS"),
        ("财务预算", "spreadComGLKJ_CWYS"),
    ]),
    ("zhixing", "预算执行", [
        ("预算分解", "spreadComGLKJ_YSFJ"),
        ("预算控制", "spreadComGLKJ_YSKZ"),
    ]),
    ("fenxi", "预算分析", [(None, "spreadComGLKJ_YSFX")]),
]

SET_JS = """
([wid, sheets])=>{
  const comp=document.getElementById(wid).__vue__;
  if(!comp) return 'NO_COMP';
  const sp=comp.$data.spread;
  for(const k of Object.keys(sheets)){
    const s=sp.getSheet(Number(k));
    if(!s) return 'NO_SHEET_'+k;
    for(const [r,c,v] of sheets[k]) s.setValue(r,c,v);
  }
  sp.repaint();
  return 'OK';
}
"""

SAVE_JS = """
([wid, sheets])=>{
  const comp=document.getElementById(wid).__vue__;
  const par=comp.$parent, sp=comp.$data.spread;
  const list=par.GLKJ_user_answer_list;
  list.length=0;
  for(const k of Object.keys(sheets)){
    const s=sp.getSheet(Number(k)), nm=s.name();
    for(const [r,c,v] of sheets[k]){
      const val=comp.getCurExalVal(nm,r,c,'text');
      list.push({sheetName:nm,rowNo:r,colNo:c,value:val});
    }
  }
  par.answerSave();
  return {n:list.length, active:par.activeName,
          expected:'GLKJ_'+wid.replace('spreadComGLKJ_','')};
}
"""


def excel_frame(page, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        for f in page.frames:
            if "onlineexcel" in f.url:
                try:
                    if f.evaluate("()=>!!document.querySelector('.item')"):
                        return f
                except Exception:
                    pass
        page.wait_for_timeout(1000)
    raise RuntimeError("预算管理页面未加载")


def click_menu(f, name):
    ok = f.evaluate(
        """(t)=>{const e=[...document.querySelectorAll('.item,div,li,span')]
             .find(x=>x.offsetWidth>0&&x.innerText.trim()===t&&x.children.length===0);
             if(e){e.click(); return true} return false;}""", name)
    if not ok:
        raise RuntimeError(f"找不到菜单: {name}")


def click_wb_tab(f, name):
    loc = f.locator(".el-tabs__item").filter(has_text=name)
    if loc.count() == 0:
        return False
    loc.first.click()
    return True


def wait_wb(page, f, wid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            n = f.evaluate(
                """(id)=>{const el=document.getElementById(id);
                     if(!el||!el.__vue__) return 0;
                     const sp=el.__vue__.$data.spread;
                     return sp?sp.getSheetCount():0;}""", wid)
            if n:
                return n
        except Exception:
            pass
        page.wait_for_timeout(800)
    raise RuntimeError(f"工作簿未加载: {wid}")


def fill_workbook(bot, page, f, wid, tab, results):
    sheets = DATA_STAGE[wid]
    res = f.evaluate(SET_JS, [wid, sheets])
    c3.log(f"  {tab or wid}: 写入 {res}")
    if res != "OK":
        raise RuntimeError(f"写入失败 {wid}: {res}")
    page.wait_for_timeout(700)
    results.clear()
    info = f.evaluate(SAVE_JS, [wid, sheets])
    c3.log(f"    answerSave: {info}")
    end = time.time() + 20
    while time.time() < end and not results:
        page.wait_for_timeout(500)
    if results:
        r = results[-1]
        try:
            body = (r.text() or "")[:200]
        except Exception:
            body = "<no body>"
        c3.log(f"    保存响应: {r.status} {body}")
    else:
        c3.log("    未捕获保存响应（继续）")
    page.wait_for_timeout(800)
    bot.shot(f"t1_{wid}")


def run_stage(bot, page, stage, menu, tabs):
    f = excel_frame(page)
    click_menu(f, menu)
    page.wait_for_timeout(5000)
    c3.log(f"进入 {menu}")
    for tab, wid in tabs:
        if tab:
            if not click_wb_tab(f, tab):
                c3.log(f"  未找到工作簿页签 {tab}，直接按 {wid} 写入")
            page.wait_for_timeout(3500)
        n = wait_wb(page, f, wid)
        c3.log(f"  {tab or menu} / {wid}: {n} sheets")
        fill_workbook(bot, page, f, wid, tab, SAVE_RESULTS)


SAVE_RESULTS = []


def main():
    global DATA_STAGE
    ap = c3.common_args(argparse.ArgumentParser())
    ap.add_argument("--stage", default="all",
                    help="all 或逗号分隔: ysmb,bianzhi,zhixing,fenxi")
    args = ap.parse_args()
    stages = [s.strip() for s in args.stage.split(",") if s.strip()]
    if "all" in stages:
        stages = [s for s, _, _ in PAGES]

    p, ctx, page = c3.launch(args)
    bot = c3.C3(page, c3.HERE / "out")

    def on_resp(r):
        if "answer/save" in r.url:
            SAVE_RESULTS.append(r)

    page.on("response", on_resp)
    try:
        bot.goto_task(TITLE)
        bot.open_business()
        for st in stages:
            entry = next(x for x in PAGES if x[0] == st)
            DATA_STAGE = DATA[entry[1]]
            run_stage(bot, page, st, *entry[1:])
        if args.dry_run:
            c3.log("dry-run：已保存，跳过提交结果")
        else:
            bot.submit()
        c3.log(bot.nav_ok())
    finally:
        try:
            page.screenshot(path=str(c3.HERE / "out" / "fail_t1.png"))
        except Exception:
            pass
        ctx.close()
        p.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
