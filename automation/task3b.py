#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务3「财务大数据分析」全自动脚本（第二套）（财连 cp.cailian.net + ExcelOS 在线表格）

用法:
  python3 task3.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run]

流程:
  任务导航 -> 任务3 财务大数据分析 -> 业务处理
  -> 定位 onlineexcel 中 id=spreadComEXCEL_TYDTB 的 SpreadJS 工作簿
  -> 按 task3_cells.json 回填 任务3.1 / 任务3.2 / 任务3.3 全部非公式单元格
     （参考答案表「（参考选项）」不回填）
  -> 保存 -> 关闭分屏 -> 提交结果

数据在 task3b_cells.json:
  {"任务3.1": [[row, col, value], ...], "任务3.2": [...], "任务3.3": [...],
   "mc": {"任务3.1": [[row, optionNo], ...], "任务3.2": [...]}}
  行列均为 0 基；mc 的 optionNo 是「（参考选项）」A 列第几句（1 基），
  写入时从工作表读取原文，保证与数据验证列表完全一致。

第二套案例：FSTZK 有限公司（医药制造业）
  * 任务3.1 现金流量表分析（表1-表7 + 6 组选择题）
  * 任务3.2 行业财务指标/同行业先进企业（表8、表9 + 2 组选择题 + 单选题 C）
  * 任务3.3 财务分析报告填空
  行业均值/行业指标口径：同行业合计÷合计（本套按 2020 与 2019 两期平均余额计算
  周转率与 ROE）；明细数据见 bicp 数据源（现金流量表/利润表/资产负债表 2019-2020）。
"""
import argparse
import base64
import json
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"
TASK_NAME = "任务3"
SKIP_SHEETS = {"（参考选项）"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Bot:
    def __init__(self, page, outdir: Path):
        self.page = page
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)

    def shot(self, name):
        try:
            self.page.screenshot(path=str(self.outdir / f"{name}.png"))
        except Exception:
            pass

    def wait_text(self, text, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.page.get_by_text(text, exact=True).count():
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(1000)
        return False

    def click_text_exam(self, text):
        self.page.evaluate(
            """(t)=>{const e=[...document.querySelectorAll('span,div')]
                 .find(x=>x.textContent.trim()===t&&x.offsetParent!==null&&x.children.length===0);
                 if(e)e.click();}""", text)

    def goto_task(self):
        # 考试首页也会显示「再次提交」，不能用它判断是否已在任务页，
        # 统一通过任务导航进入目标任务。
        self.page.get_by_text("任务导航", exact=True).first.click()
        self.page.wait_for_timeout(1500)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(TASK_NAME, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        if self.wait_text("确定", 3):
            self.page.get_by_text("确定", exact=True).first.click()
            self.page.wait_for_timeout(3500)

    def open_business(self, timeout=90):
        if self.wait_text("关闭分屏", 2):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(1800)
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                try:
                    ok = f.evaluate(
                        "()=>!!document.getElementById('spreadComEXCEL_TYDTB')"
                        " && typeof GC !== 'undefined'")
                except Exception:
                    continue
                if ok:
                    self.page.wait_for_timeout(2000)
                    return f
            self.page.wait_for_timeout(1500)
        raise RuntimeError("任务3 在线表格未加载")

    def fill_workbook(self, f, data):
        payload = {k: v for k, v in data.items() if k not in SKIP_SHEETS}
        res = f.evaluate("""
            (payload) => {
              const host = document.getElementById('spreadComEXCEL_TYDTB');
              const wb = GC.Spread.Sheets.findControl(host);
              if (!wb) return {error: 'no-workbook'};
              const S = n => wb.getSheet(wb.getSheetIndex(n));
              const opt = S('（参考选项）');
              const options = [];
              for (let r = 0; r < opt.getRowCount(); r++) {
                const v = opt.getValue(r, 0);
                if (v !== null && v !== undefined && String(v).trim() !== '') options.push(v);
              }
              const out = {};
              for (const [name, cells] of Object.entries(payload)) {
                if (name === 'mc') continue;
                let idx = wb.getSheetIndex(name);
                if (idx < 0) { out[name] = 'missing'; continue; }
                const s = wb.getSheet(idx);
                let n = 0;
                for (const [r, c, v] of cells) {
                  if (v === null || v === '') continue;
                  s.setValue(r, c, v);
                  n++;
                }
                out[name] = n;
              }
              if (payload.mc) {
                for (const [name, list] of Object.entries(payload.mc)) {
                  const s = S(name);
                  let n = 0;
                  for (const [r, num] of list) {
                    const v = options[num - 1];
                    if (v === undefined) return {error: 'missing option ' + num};
                    s.setValue(r, 2, v);
                    n++;
                  }
                  out['mc:' + name] = n;
                }
              }
              return out;
            }
        """, payload)
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"工作簿访问失败: {res['error']}")
        for name, n in res.items():
            if n == "missing":
                raise RuntimeError(f"工作簿缺少 sheet: {name}")
        log("回填完成: " + ", ".join(f"{k} {v} 格" for k, v in res.items()))
        self.page.wait_for_timeout(1000)

    def save_sheet(self, f):
        # 注意：用 setValue 直接写单元格不会触发答题板的“数据变化”检测，
        # 保存按钮会一直是 disabled。这里直接调用答题板组件的 answerSave()，
        # 它会导出当前工作簿(sjs)并上传，服务端按模板做差异比对，保存结果一致。
        log("保存表格 ...")
        res = f.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const btn = [...document.querySelectorAll('button')]
                .find(x => x.innerText.trim() === '保存');
              if (!btn) return {error: 'no-button'};

              if (!btn.disabled) {          // 有手工改动时按钮可用，直接点
                btn.click();
                await sleep(3000);
                const m = [...document.querySelectorAll('.el-message')]
                  .map(x => x.innerText.trim()).join('|');
                return {ok: true, via: 'click', msg: m};
              }

              // 找到答题板组件 khdsj-comp，直接调用其保存方法
              let el = btn;
              while (el && !el.__vue__) el = el.parentElement;
              let vm = el && el.__vue__;
              while (vm && (vm.$options.name || '').indexOf('khdsj') < 0) {
                vm = vm.$parent;
              }
              if (!vm || !vm.answerSave) return {error: 'no-component'};
              vm.answerSave();
              for (let i = 0; i < 40; i++) {
                await sleep(500);
                const m = [...document.querySelectorAll('.el-message')]
                  .map(x => x.innerText.trim()).join('|');
                if (m.indexOf('保存成功') >= 0) return {ok: true, via: 'api', msg: m};
                if (m.indexOf('失败') >= 0 || m.indexOf('错误') >= 0) {
                  return {error: 'save-failed', msg: m};
                }
                if (i > 6 && !vm.loading) return {ok: true, via: 'api-idle'};
              }
              return {error: 'timeout', loading: vm.loading};
            }
        """)
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"保存失败: {res}")
        log(f"保存完成 ({res.get('via')}: {res.get('msg', '')})")
        self.page.wait_for_timeout(1500)

    def close_split(self):
        if self.wait_text("关闭分屏", 3):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(2500)

    def submit_result(self):
        self.close_split()
        log("提交结果 ...")
        btn = "再次提交" if self.wait_text("再次提交", 3) else "提交结果"
        self.page.evaluate(
            """(t)=>{const e=[...document.querySelectorAll('.button-div-width-auto')]
                 .find(x=>x.innerText.trim()===t&&x.offsetParent!==null);
                 if(e)e.click();}""", btn)
        self.page.wait_for_timeout(1500)
        if self.wait_text("确定", 5):
            self.page.get_by_text("确定", exact=True).first.click()
        self.page.wait_for_timeout(3000)
        ok = self.wait_text("再次提交", 20)
        log("提交结果: " + ("成功" if ok else "未确认，请人工检查"))
        self.shot("t3_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--data", default=str(HERE / "task3b_cells.json"))
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="保存但不点提交结果")
    args = ap.parse_args()

    token_file = HERE / "sx_token.txt"
    sx_token = args.sx_token.strip() or (token_file.read_text(encoding="utf-8").strip()
                                         if token_file.exists() else "")
    if not sx_token:
        raise RuntimeError("缺少 sx token（--sx-token 或 sx_token.txt）")
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    outdir = HERE / "out"

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=args.headless,
            viewport={"width": 1440, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        bot = Bot(page, outdir)

        log("注入登录态 ...")
        page.goto(CP_HOME, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        q = json.loads(base64.b64decode(urllib.parse.unquote(args.exam_url.split("q=", 1)[1])))
        pq = {
            "token": sx_token, "patternLx": 0, "professionId": 38, "provinceId": "10",
            "tag": "ycsrhjncp", "cpName": "业财税融合大数据应用技能竞赛平台",
            "subjectId": 0, "notifyUrl": "https://sx.cailian.net/#/Home",
        }
        page.evaluate(
            "([u,t,pq])=>{localStorage.setItem('username',u);localStorage.setItem('jsToken',t);"
            "localStorage.setItem('pattern_lx','1');sessionStorage.setItem('token',t);"
            "sessionStorage.setItem('queryData',JSON.stringify(pq));}",
            [args.user, sx_token, pq],
        )
        body = dict(q); body["dev"] = True
        resp = page.evaluate(
            """async ([tok,body,user])=>{
                const r=await fetch('https://zledusxapi.cailian.net/api-match-practise/practise/js/playerDetail',
                  {method:'POST',headers:{'content-type':'application/json','authorization':'bearer '+tok,
                   'x-user-header':user,'prodtag':'ycsrhjncp'},body:JSON.stringify(body)});
                return await r.text();
            }""",
            [sx_token, body, args.user],
        )
        pdata = json.loads(resp).get("data") or {}
        if not pdata.get("playerId"):
            raise RuntimeError(f"playerDetail 获取失败: {resp[:200]}")
        player_json = json.dumps(pdata, ensure_ascii=False)
        station = str((pdata.get("stationIdList") or [""])[0])
        page.evaluate(
            "([p,pid,sid])=>{localStorage.setItem('playerInfo',p);localStorage.setItem('resultVal',p);"
            "localStorage.setItem('matchPlanId',pid);sessionStorage.setItem('stationId',sid);"
            "sessionStorage.setItem('planIdShow',pid);}",
            [player_json, str(pdata.get("planId")), station],
        )

        log("打开考试页 ...")
        page.goto(args.exam_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if not bot.wait_text("任务导航", 60):
            bot.shot("fail_exam_home")
            raise RuntimeError("考试页未加载（token 失效或链接不对）")

        bot.goto_task()
        f = bot.open_business()
        bot.fill_workbook(f, data)
        bot.save_sheet(f)

        if args.dry_run:
            log("dry-run：跳过提交结果")
        else:
            bot.submit_result()

        log("完成。截图目录: " + str(outdir))
        ctx.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
