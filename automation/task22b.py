#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.2「风险评估」全自动脚本（第二套）（财连 cp.cailian.net + xsj 审计平台）

用法:
  python3 task22.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]

流程:
  注入 sx token -> examHome -> 任务导航选「【2.2】风险评估」
  -> 业务处理 -> 进入项目 XM0044 -> 工作底稿 -> 搜索 AF-1 并打开
  -> 按 task22_af1.json 写入:
       资产负债表分析 / 利润表分析（未审报表期初K、期末F）
       利润表分析 主营业务收入/成本（未审报表未拆分，按全部为主营）
       比率趋势分析表(1) 利息费用、员工人数
       比率趋势分析表(2) 行业平均指标（申万成品家居，合并口径）
  -> 保存底稿 -> 关闭分屏 -> 提交结果

注意:
  * 打开底稿后若「自动取数」为开，先保持开；本脚本直接写值，保存前不要再切换开关，
    否则切换会刷新底稿导致手填内容丢失（踩过的坑）。
  * 比率趋势分析表(2) 的行业平均按“行业合计/行业合计”口径（与任务3提示第4条一致），
    样本为 2022 年 A 股 15 家成品家居公司。
"""
import argparse
import base64
import json
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"
TASK_NAME = "【2.2】风险评估"


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

    def click_text(self, text, timeout=60):
        if not self.wait_text(text, timeout):
            self.shot("fail_" + text)
            raise RuntimeError(f"找不到文本: {text}")
        self.page.get_by_text(text, exact=True).first.click()
        self.page.wait_for_timeout(1500)

    # ---------- examHome ----------
    def goto_task(self, name):
        self.click_text("任务导航", timeout=30)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(name, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        if "即将关闭实操作答界面" in self.page.inner_text("body"):
            self.click_text("确定", timeout=10)
            self.page.wait_for_timeout(4000)
        title = self.page.locator(".title-text").first.inner_text() if self.page.locator(".title-text").count() else ""
        log(f"当前任务: {title or name}")

    def open_business(self):
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if f.name == "iframeContainer":
                    return f
            self.page.wait_for_timeout(1500)
        raise RuntimeError("审计平台 iframe 未加载")

    # ---------- 审计平台 ----------
    def enter_project(self, audit):
        """项目列表 -> 进入 XM0044"""
        end = time.time() + 60
        while time.time() < end:
            try:
                if audit.evaluate("()=>location.hash.includes('/home')"):
                    log("已在项目内")
                    return
                got = audit.evaluate(
                    """()=>{const s=[...document.querySelectorAll('span')]
                         .filter(e=>e.textContent.trim()==='进入'&&e.offsetParent!==null);
                         if(!s.length) return false; s[0].click(); return true;}"""
                )
                if got:
                    log("已点击进入项目")
                    self.page.wait_for_timeout(4000)
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("未能进入审计项目（找不到“进入”或页面未就绪）")

    def find_spread_frame(self, timeout=120):
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
        raise RuntimeError("工作底稿 SpreadJS 未加载")

    def open_af1(self, spread):
        """打开 底稿列表 -> A 组 -> AF 组 -> AF-1。"""
        # 展开底稿树
        spread.evaluate("""
            () => {
              const ic = [...document.querySelectorAll('.el-icon-folder')]
                .find(e => e.getBoundingClientRect().width > 0);
              if (ic) ic.click();
            }
        """)
        self.page.wait_for_timeout(2200)

        def click_span(text, starts=False):
            js = """([t,st])=>{const els=[...document.querySelectorAll('*')]
                     .filter(e=>e.getBoundingClientRect().width>0 && e.children.length===0)
                     .filter(e=>{const x=e.textContent.trim(); return st?x.startsWith(t):x===t;});
                     if(!els.length) return false; els[0].click(); return true;}"""
            return spread.evaluate(js, [text, starts])

        for text, starts in [
            ("A-计划与风险识别工作底稿", True),
            ("AF 识别重大账户", True),
        ]:
            if not click_span(text, starts):
                raise RuntimeError(f"底稿树中找不到: {text}")
            self.page.wait_for_timeout(2000)

        if not click_span("AF-1 执行财务报表风险评估分析性程序", True):
            if not click_span("AF-1 执行财务报表风险", True):
                raise RuntimeError("找不到 AF-1 底稿")
        self.page.wait_for_timeout(7000)
        log("AF-1 底稿已打开")

    def fill_af1(self, spread, data):
        js = """(d)=>{
            const host=document.querySelector('[class*=designer]');
            const dd=GC.Spread.Sheets.Designer.findControl(host);
            const wb=dd.getWorkbook?dd.getWorkbook():dd;
            const idx={}; for(let i=0;i<wb.getSheetCount();i++) idx[wb.getSheet(i).name()]=i;
            const set=(s,r,c,v)=>{ if(String(s.getFormula(r,c)||'').trim()) return 0; s.setValue(r,c,v); return 1; };
            let n=0;
            const bs=wb.getSheet(idx['资产负债表分析']); const is=wb.getSheet(idx['利润表分析']);
            for(const [r,p,c] of d.bs_rows){ if(p!==null)n+=set(bs,r,2,p); if(c!==null)n+=set(bs,r,4,c); }
            for(const [r,p,c] of d.is_rows){ if(p!==null)n+=set(is,r,2,p); if(c!==null)n+=set(is,r,3,c); }
            n+=set(is,d.is_main_rev[0],d.is_main_rev[1],d.is_main_rev[2]);
            n+=set(is,d.is_main_cost[0],d.is_main_cost[1],d.is_main_cost[2]);
            const r1=wb.getSheet(idx['比率趋势分析表（1）']||idx['比率趋势分析表(1)']);
            const [ir,iv]=d.ratio1_interest; n+=set(r1,ir,3,iv);
            const [er,ec,ep]=d.ratio1_employees; n+=set(r1,er,3,ec); n+=set(r1,er,4,ep);
            const r2=wb.getSheet(idx['比率趋势分析表(2)']);
            for(const [r,v] of Object.entries(d.industry_averages)) n+=set(r2,Number(r),4,v);
            return n;
        }"""
        n = spread.evaluate(js, data)
        log(f"已写入 AF-1 共 {n} 个单元格")

    def save_af1(self, spread):
        log("保存底稿 ...")
        # 确保处于「工作底稿」标签
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
        clicked = spread.evaluate("""
            () => {
              const sp = [...document.querySelectorAll('span')]
                .find(e => e.offsetParent && e.textContent.trim() === '保存'
                        && e.parentElement && e.parentElement.className.includes('el-button'));
              if (!sp) return false; sp.click(); return true;
            }
        """)
        if not clicked:
            self.shot("fail_save_af1")
            raise RuntimeError("保存按钮不可用")
        self.page.wait_for_timeout(3500)
        ok = spread.evaluate("""
            () => [...document.querySelectorAll('.el-message')]
                    .some(e => e.textContent.includes('保存成功'))
        """)
        log("底稿保存" + ("成功" if ok else "完成（未见提示）"))

    def close_split(self):
        try:
            self.page.evaluate(
                """()=>{const s=[...document.querySelectorAll('span')]
                     .find(e=>e.textContent.trim()==='关闭分屏'); if(s) s.click();}"""
            )
            self.page.wait_for_timeout(3000)
        except Exception:
            pass

    def submit(self):
        log("提交结果 ...")
        btn = "再次提交" if self.wait_text("再次提交", 5) else "提交结果"
        self.click_text(btn, timeout=30)
        if self.wait_text("确定", 6):
            self.click_text("确定", timeout=20)
        self.page.wait_for_timeout(3000)
        ok = self.wait_text("再次提交", 20)
        log("提交结果: " + ("成功" if ok else "未确认到状态变化，请人工检查"))
        self.shot("22_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--data", default=str(HERE / "task22b_af1.json"))
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只保存，不提交结果")
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

        bot.goto_task(TASK_NAME)
        audit = bot.open_business()
        bot.enter_project(audit)
        spread = bot.find_spread_frame()
        bot.open_af1(spread)
        bot.fill_af1(spread, data)
        bot.save_af1(spread)
        bot.close_split()

        if args.dry_run:
            log("dry-run：已保存，跳过提交结果")
        else:
            bot.submit()

        log("完成。截图目录: " + str(outdir))
        ctx.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
