#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.1.2「审计重要性确定」全自动脚本（第二套）（财连 cp.cailian.net + 审计平台）

用法:
  python3 task212.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run]

流程:
  任务导航 -> 【 2.1.2】审计重要性确定 -> 业务处理
  -> 进入项目 XM0044 -> 工作底稿 -> A-计划与风险识别工作底稿
  -> AE 确定重要性水平 -> AE 重要性确定表
  -> 按未审报表税前利润填写（第二套模板行号）:
       B8/C8/D8    重要性计量基础（税前利润、考虑因素、金额）
       B14 基础金额 / C14 基本理由 / D14 适用比率 8%（数值，格式化 %）
       D18 整体重要性（取整）
       C28 整体重要性 / F28 75% / D30 实际执行的重要性（取整）
       F41 5%（C41 是 =D18 公式）/ D42 明显微小错报临界值（取整）
     G14/G28/G41 为模板公式，脚本不覆盖
  -> 保存底稿 -> 关闭分屏 -> 提交结果

数据在 task212_data.json:
  {"tax_profit": 308845.57, "pm_ratio": 0.08, "te_ratio": 0.75, "ct_ratio": 0.05,
   "reason": "公司近几年利润比较稳定，采用税前利润作为基准"}
"""
import argparse
import base64
import json
import sys
import time
import urllib.parse
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"
TASK_NAME = "2.1.2"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def r2(v):
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def r0(v):
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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
        # 其他任务提交后首页按钮也会显示「再次提交」，不能据此判断已在目标任务页。
        self.page.get_by_text("任务导航", exact=True).first.click()
        self.page.wait_for_timeout(1500)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(TASK_NAME, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        if self.wait_text("确定", 3):
            self.page.get_by_text("确定", exact=True).first.click()
            self.page.wait_for_timeout(3500)

    def open_business(self):
        if self.wait_text("关闭分屏", 2):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(1800)
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if "xsj.cailian.net" in f.url:
                    self.page.wait_for_timeout(3000)
                    return f
            self.page.wait_for_timeout(1500)
        raise RuntimeError("审计平台 iframe 未加载")

    def enter_project(self, audit):
        end = time.time() + 60
        while time.time() < end:
            try:
                if "/home" in audit.url and "项目列表" not in audit.inner_text("body"):
                    return
                got = audit.evaluate(
                    """()=>{const s=[...document.querySelectorAll('span')]
                         .filter(e=>e.textContent.trim()==='进入'&&e.offsetParent!==null);
                         if(!s.length) return false; s[0].click(); return true;}"""
                )
                if got:
                    self.page.wait_for_timeout(4000)
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("未能进入审计项目")

    def find_sj_frame(self, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if "sj-spread" in f.url:
                    try:
                        if f.evaluate("typeof GC !== 'undefined'"):
                            return f
                    except Exception:
                        pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("SpreadJS 设计器未加载")

    def open_ae(self, sj):
        # 展开底稿列表
        sj.evaluate("""
            () => {
              const ic = [...document.querySelectorAll('.el-icon-folder')]
                .find(e => e.getBoundingClientRect().width > 0);
              if (ic) ic.click();
            }
        """)
        self.page.wait_for_timeout(2000)
        for label in ("A-计划与风险识别工作底稿",):
            ok = sj.evaluate("""
                ([t]) => {
                  const els = [...document.querySelectorAll('*')].filter(e =>
                    e.getBoundingClientRect().width > 0 && e.children.length === 0 &&
                    e.textContent.trim().startsWith(t));
                  if (!els.length) return false;
                  els[0].click(); return true;
                }
            """, [label])
            if not ok:
                raise RuntimeError(f"底稿树中找不到 {label}")
            self.page.wait_for_timeout(1800)
        ok = sj.evaluate("""
            () => {
              const els = [...document.querySelectorAll('*')].filter(e =>
                e.getBoundingClientRect().width > 0 && e.children.length === 0 &&
                e.textContent.trim().startsWith('AE 确定重要性'));
              if (!els.length) return false;
              els[0].click(); return true;
            }
        """)
        if not ok:
            raise RuntimeError("找不到 AE 确定重要性水平")
        self.page.wait_for_timeout(6000)
        ok = sj.evaluate("""
            () => {
              const els = [...document.querySelectorAll('*')].filter(e =>
                e.getBoundingClientRect().width > 0 && e.children.length === 0 &&
                e.textContent.trim() === 'AE 重要性确定表');
              if (!els.length) return false;
              els[0].click(); return true;
            }
        """)
        if not ok:
            raise RuntimeError("找不到 AE 重要性确定表")
        self.page.wait_for_timeout(7000)
        log("AE 重要性确定表已打开")

    def fill_ae(self, sj, d):
        tax = float(d["tax_profit"])
        pm_calc = r2(tax * float(d["pm_ratio"]))
        pm = r0(pm_calc)
        te = r0(pm * float(d["te_ratio"]))
        ct_calc = r2(pm * float(d["ct_ratio"]))
        ct = r0(ct_calc)
        cells = {
            "B8": "税前利润",
            "C8": "公司近几年利润比较稳定",
            "D8": tax,
            "B14": tax,
            "C14": d.get("reason", "公司近几年利润比较稳定，采用税前利润作为基准"),
            "D14": float(d["pm_ratio"]),
            "D18": pm,
            "C28": pm,
            "F28": float(d["te_ratio"]),
            "D30": te,
            "F41": float(d["ct_ratio"]),
            "D42": ct,
        }
        pct_cells = ["D14", "F28", "F41"]
        n = sj.evaluate("""
            (arg) => {
              const [cells, pct] = arg;
              const host = document.querySelector('.gc-designer-container');
              const dd = GC.Spread.Sheets.Designer.findControl(host);
              const wb = dd.getWorkbook ? dd.getWorkbook() : dd;
              const idx = wb.getSheetIndex ? wb.getSheetIndex('重要性水平确定表') : 1;
              const s = wb.getSheet(idx);
              const col = ch => ch.charCodeAt(0) - 65;
              const rc = a1 => { const m = a1.match(/^([A-Z]+)(\\d+)$/);
                return [parseInt(m[2], 10) - 1, col(m[1])]; };
              let n = 0;
              for (const [a1, v] of Object.entries(cells)) {
                const [r, c] = rc(a1);
                s.setValue(r, c, v);
                n++;
              }
              for (const a1 of pct) { const [r, c] = rc(a1); s.setFormatter(r, c, '0%'); }
              return n;
            }
        """, [cells, pct_cells])
        log(f"已写入 AE 共 {n} 个单元格 | 整体重要性 {pm} / 实际执行 {te} / 临界值 {ct}")
        self.page.wait_for_timeout(1000)

    def save_sheet(self, sj):
        log("保存底稿 ...")
        # 确保切回「工作底稿」标签（可能还开着未审报表标签）
        self.page.evaluate("""() => { const xsj = [...document.querySelectorAll('iframe')]; }""")
        try:
            xsj = next(f for f in self.page.frames if "xsj.cailian.net" in f.url)
            xsj.evaluate("""() => {
                const el = [...document.querySelectorAll('span')]
                  .find(e => e.offsetParent && e.textContent.trim() === '工作底稿');
                if (el) el.click();
            }""")
            self.page.wait_for_timeout(2500)
        except Exception:
            pass
        enabled = sj.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              for (let i = 0; i < 15; i++) {
                const sp = [...document.querySelectorAll('span')].find(x =>
                  x.getBoundingClientRect().width > 0 && x.textContent.trim() === '保存'
                  && x.parentElement && x.parentElement.className.includes('el-button'));
                if (sp && !sp.parentElement.disabled) { sp.click(); return true; }
                await sleep(500);
              }
              return false;
            }
        """)
        if not enabled:
            self.shot("fail_save_ae")
            raise RuntimeError("保存按钮不可用")
        self.page.wait_for_timeout(3000)
        ok = sj.evaluate("""
            () => [...document.querySelectorAll('.el-message')]
                    .some(e => e.textContent.includes('保存成功'))
        """)
        log("底稿保存" + ("成功" if ok else "完成（未见提示）"))

    def submit_result(self):
        if self.wait_text("关闭分屏", 2):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(2000)
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
        self.shot("t212_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--data", default=str(HERE / "task212b_data.json"))
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
        audit = bot.open_business()
        bot.enter_project(audit)
        sj = bot.find_sj_frame()
        bot.open_ae(sj)
        bot.fill_ae(sj, data)
        bot.save_sheet(sj)

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
