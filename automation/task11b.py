#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务1.1「大数据税务预警」全自动脚本 · 第二套（FSTZG 零售业，26 个指标）

用法:
  python3 task11b.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]

流程:
  注入 sx token -> examHome -> 任务导航「大数据税务预警」 -> 业务处理
  -> 数据导入（已导入则跳过）
  -> 大数据行业指标: 填 D5:D30（0-based 行 4..29）并保存
  -> 税务风险预警: 写企业值 E5:E30、偏离度 G5:G30 并保存
  -> 税务风险分析: 按 data 里的 26 组「是否存在税务风险 + 5 个风险事项」写入并保存
  -> 关闭分屏 -> 提交结果

数据文件 task11b_data.json:
  industry_values:  {"4": 0.0162, ...}   26 个行业指标值（0-based 行，小数，表格按 % 显示）
  enterprise_values:{"5": 0.0117, ...}   26 个企业指标值（1-based 行=Excel 行号，小数）
  deviations:       {"5": -0.2778, ...}  26 个偏离度（小数，=（企业值-行业值）/行业值）
  analysis: [{risk:"是/否", items:[5 个 是/否]}] × 26

注意：E 列（企业值）和 G 列（偏离度）都是空白的黄色答案格，平台不会自动回填，
必须由脚本自行计算写入；F 列（行业值）来自上一页保存的行业均值。

与第一套 task11.py 的差异:
  * 26 个指标、行号 4..29（第一套 23 个、4..26）；
  * 分析页 26 个块（第一套 23 个）；
  * 从 examHome 注入登录态（第一套走 studentDetail 链接）。
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
TASK_NAME = "大数据税务预警"
ROWS = list(range(4, 30))          # 0-based 指标行


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pct(text):
    """'12.34%' -> 12.34 ; '' -> None"""
    if text is None:
        return None
    s = str(text).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


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

    def body_has(self, text):
        try:
            return text in self.page.inner_text("body")
        except Exception:
            return False

    # ---------- 导航 ----------
    def goto_task(self):
        if self.body_has("业务资料1.1") and self.wait_text("再次提交", 2):
            log("已在任务1.1")
            return
        self.page.evaluate(
            """()=>{const e=[...document.querySelectorAll('span,div')]
                 .find(x=>x.textContent.trim()==='任务导航'&&x.offsetParent!==null);
                 if(e)e.click();}"""
        )
        self.page.wait_for_timeout(1500)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(TASK_NAME, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        if self.wait_text("确定", 3):
            self.page.get_by_text("确定", exact=True).first.click()
            self.page.wait_for_timeout(3000)
        log(f"已切换到 {TASK_NAME}")

    def open_business(self):
        if self.wait_text("关闭分屏", 2):
            self.page.get_by_text("关闭分屏", exact=True).first.click()
            self.page.wait_for_timeout(1500)
        self.page.locator(".button-box div", has_text="业务处理").first.click()
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if "onlineexcel" in f.url:
                    try:
                        if f.evaluate("typeof GC !== 'undefined'"):
                            self.page.wait_for_timeout(2500)
                            return f
                    except Exception:
                        pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("在线表格（onlineexcel）未加载")

    def click_menu(self, frame, text):
        ok = frame.evaluate(
            """(t)=>{const el=[...document.querySelectorAll('div.item')]
                 .find(e=>e.textContent.trim()===t); if(!el) return false; el.click(); return true;}""",
            text,
        )
        if not ok:
            raise RuntimeError(f"左侧菜单点不到: {text}")
        log(f"已切换页面: {text}")
        self.page.wait_for_timeout(1500)

    def find_spread(self, frame, sheet_name, timeout=180):
        js = """(name)=>{
            const ids=[]; const re=/^spreadCom\\d+$/;
            document.querySelectorAll('[id]').forEach(e=>{ if(re.test(e.id)) ids.push(e.id); });
            for(const id of ids){
                try{
                    const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
                    if(!sp || sp.getSheetCount()===0) continue;
                    if(sp.getSheet(0).name()===name) return id;
                }catch(e){}
            }
            return null;
        }"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                sid = frame.evaluate(js, sheet_name)
                if sid:
                    return sid
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        return None

    def save_page(self, frame, tag):
        log(f"保存 [{tag}] ...")
        try:
            with self.page.expect_response(
                lambda r: "/api-tax/manageaccount/tax/answer/save/" in r.url, timeout=30000
            ) as info:
                frame.locator("button:has-text('保存')").first.click()
            body = info.value.text()
            if '"code":0' not in body.replace(" ", ""):
                raise RuntimeError(f"保存失败: {body[:200]}")
            log(f"保存 [{tag}] 成功")
        except PWTimeout:
            raise RuntimeError(f"保存 [{tag}] 超时（未捕获到 answer/save 请求）")
        self.page.wait_for_timeout(1500)

    # ---------- 各页面 ----------
    def do_import(self, frame):
        self.click_menu(frame, "数据导入")
        try:
            frame.locator("button:has-text('导入')").first.click(timeout=5000)
            self.page.wait_for_timeout(1500)
            info = frame.evaluate("""
                ()=>{
                  const d=[...document.querySelectorAll('.el-dialog__wrapper')].filter(x=>x.offsetWidth>0).pop();
                  if(!d) return {open:false};
                  return {open:true, text:d.innerText,
                          radios:[...d.querySelectorAll('.el-radio')].map(r=>r.innerText.trim())};
                }
            """)
            if info.get("open"):
                if "数据已导入" in info.get("text", ""):
                    frame.evaluate("""
                        ()=>{const d=[...document.querySelectorAll('.el-dialog__wrapper')].filter(x=>x.offsetWidth>0).pop();
                             const b=d&&d.querySelector('.el-dialog__headerbtn'); if(b)b.click();}
                    """)
                    log("数据已导入，跳过")
                    return
                radios = info.get("radios") or []
                if radios:
                    frame.evaluate("""
                        ()=>{const d=[...document.querySelectorAll('.el-dialog__wrapper')].filter(x=>x.offsetWidth>0).pop();
                             const r=[...d.querySelectorAll('.el-radio')].find(x=>x.innerText.includes('会计报表'));
                             if(r&&!r.classList.contains('is-checked')) r.querySelector('input').click();}
                    """)
                    self.page.wait_for_timeout(500)
                    frame.evaluate("""
                        ()=>{const d=[...document.querySelectorAll('.el-dialog__wrapper')].filter(x=>x.offsetWidth>0).pop();
                             const b=[...d.querySelectorAll('button')].find(x=>/确定|导入/.test(x.innerText));
                             if(b)b.click();}
                    """)
                    self.page.wait_for_timeout(3000)
                    log("会计报表导入完成")
        except Exception as e:
            log(f"导入步骤跳过/失败（继续）: {e}")

    def do_industry(self, frame, values):
        self.click_menu(frame, "大数据行业指标")
        sid = self.find_spread(frame, "大数据行业均值计算")
        if not sid:
            raise RuntimeError("大数据行业指标页未加载")
        js = """([id, vals])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            for(const [r,v] of Object.entries(vals)) s.setValue(Number(r),3,v);
            sp.repaint();
            return [s.getText(4,3), s.getText(29,3)];
        }"""
        check = frame.evaluate(js, [sid, values])
        log(f"已写入 {len(values)} 个行业指标值，首/末显示: {check}")
        self.save_page(frame, "大数据行业指标")
        self.shot("11b_industry")

    def do_risk(self, frame, values, deviations):
        self.click_menu(frame, "税务风险预警")
        log("等待风险预警大表加载（首次约 30-60 秒）...")
        sid = self.find_spread(frame, "税务风险预警指标计算及风险评价表", timeout=240)
        if not sid:
            raise RuntimeError("税务风险预警页未加载")
        read_js = """(id)=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0); const out=[];
            for(let r=4;r<30;r++) out.push({row:r+1, name:s.getText(r,2), f:s.getText(r,5)});
            return out;
        }"""
        # 行业值 F 由上一页保存后回填，等它全部出现（最多 120 秒）
        rows = frame.evaluate(read_js, sid)
        end = time.time() + 120
        while time.time() < end and any(pct(x["f"]) is None for x in rows):
            self.page.wait_for_timeout(2000)
            rows = frame.evaluate(read_js, sid)
        for x in rows:
            if pct(x["f"]) is None:
                log(f"  注意: 第{x['row']}行 {x['name']} 行业值缺失")

        fill_js = """([id, vals, devs])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            for(const [r,v] of Object.entries(vals)) s.setValue(Number(r)-1,4,v);
            for(const [r,v] of Object.entries(devs)) s.setValue(Number(r)-1,6,v);
            sp.repaint();
            const out=[];
            for(let r=4;r<30;r++) out.push({row:r+1, name:s.getText(r,2),
                e:s.getText(r,4), f:s.getText(r,5), g:s.getText(r,6)});
            return out;
        }"""
        check = frame.evaluate(fill_js, [sid, values, deviations])
        for x in check:
            log(f"  第{x['row']:>2}行 {x['name']:<14} 企业 {x['e']:>10} 行业 {x['f']:>10} 偏离 {x['g']:>11}")
        bad = [x for x in check if pct(x["e"]) is None or pct(x["g"]) is None]
        if bad:
            raise RuntimeError(f"企业值/偏离度未写入: 第{[x['row'] for x in bad]}行")
        self.save_page(frame, "税务风险预警")
        self.shot("11b_risk")

    def do_analysis(self, frame, analysis):
        self.click_menu(frame, "税务风险分析")
        sid = self.find_spread(frame, "税务风险预警分析", timeout=180)
        if not sid:
            raise RuntimeError("税务风险分析页未加载")
        read_js = """(id)=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0); const out=[];
            for(let i=0;i<26;i++){
                const r=3+5*i;
                out.push({i:i+1, name:s.getText(r,2), e:s.getText(r,3), f:s.getText(r,4), dev:s.getText(r,5)});
            }
            return out;
        }"""
        rows = frame.evaluate(read_js, sid)
        end = time.time() + 90
        while time.time() < end and any(pct(x["f"]) is None for x in rows):
            self.page.wait_for_timeout(2000)
            rows = frame.evaluate(read_js, sid)

        for x in rows:
            dv = pct(x["dev"])
            expect = "是" if (dv is not None and abs(dv) > 30.0) else "否"
            got = analysis[x["i"] - 1]["risk"] if x["i"] - 1 < len(analysis) else "?"
            if got != expect:
                log(f"  警告: 指标{x['i']} {x['name']} 偏离 {dv} 预期 {expect} 数据文件为 {got}（以数据文件为准）")

        fill_js = """([id, data])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            for(let k=0;k<data.length;k++){
                const base=3+5*k;
                s.setValue(base,6,data[k].risk);
                data[k].items.forEach((v,j)=>s.setValue(base+j,8,v));
            }
            sp.repaint();
            return [s.getValue(3,6), s.getValue(128,6)];
        }"""
        check = frame.evaluate(fill_js, [sid, analysis])
        log(f"已写入 26 个是否判断 + 130 个事项选择，首/末: {check}")
        self.save_page(frame, "税务风险分析")
        self.shot("11b_analysis")

    # ---------- 提交 ----------
    def submit(self):
        if self.wait_text("关闭分屏", 2):
            self.page.get_by_text("关闭分屏", exact=True).first.click()
            self.page.wait_for_timeout(2000)
        btn = "再次提交" if self.wait_text("再次提交", 3) else "提交结果"
        log(f"提交结果（{btn}）...")
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
        self.shot("11b_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--data", default=str(HERE / "task11b_data.json"))
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只保存，不点提交结果")
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
        station = str((pdata.get("stationIdList") or [""])[0])
        page.evaluate(
            "([p,pid,sid])=>{localStorage.setItem('playerInfo',p);localStorage.setItem('resultVal',p);"
            "localStorage.setItem('matchPlanId',pid);sessionStorage.setItem('stationId',sid);"
            "sessionStorage.setItem('planIdShow',pid);}",
            [json.dumps(pdata, ensure_ascii=False), str(pdata.get("planId")), station],
        )

        log("打开考试页 ...")
        page.goto(args.exam_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if not bot.wait_text("任务导航", 60):
            bot.shot("fail_exam_home")
            raise RuntimeError("考试页未加载（token 失效或链接不对）")

        bot.goto_task()
        frame = bot.open_business()
        log("在线表格已加载")
        bot.do_import(frame)
        bot.do_industry(frame, data["industry_values"])
        bot.do_risk(frame, data["enterprise_values"], data["deviations"])
        bot.do_analysis(frame, data["analysis"])

        if args.dry_run:
            log("dry-run：已保存全部答案，跳过提交结果")
        else:
            bot.submit()

        ctx.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
