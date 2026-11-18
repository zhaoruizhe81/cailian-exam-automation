#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.3「人力资源与工薪业务循环实质性程序实施」全自动脚本（第二套）

用法:
  python3 task23b.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]

流程:
  注入 sx token -> examHome -> 任务导航选「【2.3】人力资源与工薪业务循环实质性程序实施」
  -> 业务处理 -> 进入项目 XM0044 -> 工作底稿
  -> F 负债类 / F8 应付职工薪酬：明细表、分配检查情况表、社保三项经费计提检查表、凭证抽查表
  -> S 损益类 / S4 管理费用：截止性测试表、管理费用凭证抽查表（明细表当前期已自动取数）
  -> 保存底稿 -> 关闭分屏 -> 提交结果

数据来源（task23b_data.json）:
  * 科目余额表 getTreeList -> 2211 明细户 期初/借方/贷方
  * 12 月工资表（40 人，工资总额 296,800）-> 社保/公积金计提
  * 序时账 2211 相关凭证 28/29/32/39/40/41 -> 抽查表与分配
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
TASK_NAME = "【2.3】人力资源与工薪业务循环实质性程序实施"


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

    def _visible(self, spread, text, starts=True):
        # 树节点文字的空格数量不稳定（如「S 损益类」/「S  损益类」），比较前去掉空白。
        js = """([t,st])=>{const T=t.replace(/\\s+/g,'');
                 return [...document.querySelectorAll('*')]
                 .filter(e=>e.getBoundingClientRect().width>0 && e.children.length===0)
                 .filter(e=>{const x=e.textContent.trim().replace(/\\s+/g,''); return st?x.startsWith(T):x===T;}).length;}"""
        return spread.evaluate(js, [text, starts]) > 0

    def _click_tree(self, spread, text, starts=True):
        js = """([t,st])=>{const T=t.replace(/\\s+/g,'');
                 const els=[...document.querySelectorAll('*')]
                 .filter(e=>e.getBoundingClientRect().width>0 && e.children.length===0)
                 .filter(e=>{const x=e.textContent.trim().replace(/\\s+/g,''); return st?x.startsWith(T):x===T;});
                 if(!els.length) return false; els[0].click(); return true;}"""
        ok = spread.evaluate(js, [text, starts])
        self.page.wait_for_timeout(2000)
        return ok

    def _expand_tree(self, spread, text, attempts=4):
        """展开树节点并确认已展开；节点可能因保存后树重绘而丢失展开状态。"""
        click_js = """([t,how])=>{const T=t.replace(/\\s+/g,'');
                 const conts=[...document.querySelectorAll('.el-tree-node__content')]
                   .filter(e=>e.getBoundingClientRect().width>0);
                 for(const c of conts){
                   const x=(c.innerText||'').trim().split('\\n')[0].replace(/\\s+/g,'');
                   if(x===T || x.startsWith(T)){
                     if(how==='icon'){
                       const ic=c.querySelector('.el-tree-node__expand-icon');
                       if(ic){ic.click(); return 'icon';}
                     }
                     c.click(); return 'row';
                   }
                 }
                 return null;}"""
        state_js = """(t)=>{const T=t.replace(/\\s+/g,'');
                 const conts=[...document.querySelectorAll('.el-tree-node__content')]
                   .filter(e=>e.getBoundingClientRect().width>0);
                 for(const c of conts){
                   const x=(c.innerText||'').trim().split('\\n')[0].replace(/\\s+/g,'');
                   if(x===T || x.startsWith(T)){
                     const node=c.closest('.el-tree-node');
                     const ic=node&&node.querySelector('.el-tree-node__expand-icon');
                     if(!ic) return 'no-icon';
                     return ic.classList.contains('expanded') ? 'expanded' : 'closed';
                   }
                 }
                 return null;}"""
        exists = False
        for _ in range(attempts):
            st = spread.evaluate(state_js, text)
            if st is None:
                return None
            exists = True
            if st in ("expanded", "no-icon"):
                return st
            spread.evaluate(click_js, [text, "icon"])
            self.page.wait_for_timeout(2500)
            st = spread.evaluate(state_js, text)
            if st == "expanded":
                return "expanded"
            # 箭头无效时退回点整行（平台树点击行文字也能展开）
            spread.evaluate(click_js, [text, "row"])
            self.page.wait_for_timeout(3000)
            st = spread.evaluate(state_js, text)
            if st in ("expanded", "no-icon"):
                return st
        return st if exists else None

    def _tree_labels(self, spread):
        return spread.evaluate("""()=>{const s=new Set();
            document.querySelectorAll('.el-tree-node__content').forEach(e=>{
              if(e.getBoundingClientRect().width>0){
                const t=(e.innerText||'').trim().split('\\n')[0]; if(t) s.add(t);
              }});
            return [...s].slice(0,60);}""")

    def open_workpaper(self, spread, groups, leaf):
        """底稿树: (必要时展开文件夹) -> groups 逐级 -> 打开 leaf 底稿"""
        if not self._visible(spread, leaf, True):
            if not any(self._visible(spread, g, True) for g in groups[:1]):
                spread.evaluate("""
                    () => {
                      const ic = [...document.querySelectorAll('.el-icon-folder')]
                        .find(e => e.getBoundingClientRect().width > 0);
                      if (ic) ic.click();
                    }
                """)
                self.page.wait_for_timeout(2200)
            for g in groups:
                if self._visible(spread, leaf, True):
                    break
                if self._expand_tree(spread, g) is None:
                    raise RuntimeError(f"底稿树中找不到: {g}（可见节点: {self._tree_labels(spread)}）")
        if not self._click_tree(spread, leaf, True):
            raise RuntimeError(f"底稿树中找不到: {leaf}（可见节点: {self._tree_labels(spread)}）")
        self.page.wait_for_timeout(8000)
        log(f"{leaf} 已打开")

    def fill_f8(self, spread, d):
        js = r"""(d)=>{
            const host=document.querySelector('[class*=designer]');
            const dd=GC.Spread.Sheets.Designer.findControl(host);
            const wb=dd.getWorkbook?dd.getWorkbook():dd;
            const S=n=>wb.getSheet(wb.getSheetIndex(n));
            const set=(s,r,c,v)=>{ if(String(s.getFormula(r,c)||'').trim()) return 0; s.setValue(r,c,v); return 1; };
            const A=(s,a1,v)=>{const m=a1.match(/^([A-Z]+)(\d+)$/);
                return set(s, parseInt(m[2],10)-1, m[1].charCodeAt(0)-65, v);};
            let n=0;
            for (const [name, cells] of Object.entries(d.cells))
              for (const [a1,v] of Object.entries(cells)) n+=A(S(name), a1, v);
            const vc=S('应付职工薪酬凭证抽查表');
            d.vouchers.rows.forEach((row,i)=>{
              const rr=d.vouchers.start_row-1+i;
              for(let c=0;c<8;c++){ vc.setValue(rr,c+1,row[c]); n++; }
              for(let c=9;c<14;c++){ vc.setValue(rr,c,d.vouchers.checks); n++; }
            });
            return n;
        }"""
        n = spread.evaluate(js, d)
        log(f"F8 已写入 {n} 个单元格")

    def fill_s4(self, spread, d):
        js = """(d)=>{
            const host=document.querySelector('[class*=designer]');
            const dd=GC.Spread.Sheets.Designer.findControl(host);
            const wb=dd.getWorkbook?dd.getWorkbook():dd;
            const S=n=>wb.getSheet(wb.getSheetIndex(n));
            let n=0;
            const cut=S('截止性测试表');
            d.cutoff.rows.forEach((row,i)=>{
              const rr=d.cutoff.start_row-1+i;
              const vals={0:row[0],1:row[1],2:row[2],3:row[3],4:row[4],5:row[5],8:row[6]};
              for(const [c,v] of Object.entries(vals)){ cut.setValue(rr,Number(c),v); n++; }
            });
            const vc=S('管理费用凭证抽查表');
            d.vouchers.rows.forEach((row,i)=>{
              const rr=d.vouchers.start_row-1+i;
              for(let c=0;c<8;c++){ vc.setValue(rr,c+1,row[c]); n++; }
              for(let c=9;c<14;c++){ vc.setValue(rr,c,d.vouchers.checks); n++; }
            });
            return n;
        }"""
        n = spread.evaluate(js, d)
        log(f"S4 已写入 {n} 个单元格")

    def save_wp(self, spread):
        log("保存底稿 ...")
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
            self.shot("fail_save_wp")
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
    ap.add_argument("--data", default=str(HERE / "task23b_data.json"))
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
        bot.open_workpaper(spread, ["实质性程序工作底稿", "F 负债类"], "F8 应付职工薪酬")
        bot.fill_f8(spread, {"cells": {k: data["f8"][k] for k in ("明细表", "分配检查情况表", "社保、三项经费计提检查表")}, "vouchers": data["f8"]["应付职工薪酬凭证抽查表"]})
        bot.save_wp(spread)
        bot.open_workpaper(spread, ["实质性程序工作底稿", "S 损益类"], "S4 管理费用")
        bot.fill_s4(spread, {"cutoff": data["s4"]["截止性测试表"], "vouchers": data["s4"]["管理费用凭证抽查表"]})
        bot.save_wp(spread)
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
