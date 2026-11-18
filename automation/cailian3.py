#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三套（planId 5000508920）公共库：财天下会计核算 + 个税优化答题。

所有第三套脚本（task4c.py ~ task11c.py）共用本模块：

  登录态注入（与 task11b.py 一致）
  -> examHome -> 任务导航切任务 -> 业务处理（财天下微前端）
  -> 票据采集 / 新增凭证 / 票据制单 / 在线表格（onlineexcel）

用法示例见各 taskXc.py 的 __main__。
"""
import base64
import json
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- 登录 / 启动
def launch(args):
    """打开浏览器并注入 sx 登录态，返回 (playwright, ctx, page)。"""
    token_file = HERE / "sx_token.txt"
    sx_token = getattr(args, "sx_token", "").strip() or (
        token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""
    )
    if not sx_token:
        raise RuntimeError("缺少 sx token（--sx-token 或 sx_token.txt）")

    p = sync_playwright().start()
    ctx = p.chromium.launch_persistent_context(
        args.profile, channel="chrome", headless=getattr(args, "headless", False),
        viewport={"width": 1440, "height": 820},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

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
    b = C3(page, HERE / "out")
    if not b.wait_text("任务导航", 60):
        b.shot("fail_exam_home")
        raise RuntimeError("考试页未加载（token 失效或链接不对）")
    return p, ctx, page


def common_args(ap):
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只保存，不点提交结果")
    return ap


# ---------------------------------------------------------------- 页面操作
class C3:
    def __init__(self, page, outdir):
        self.page = page
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)

    # ---------- 基础 ----------
    def shot(self, name):
        try:
            self.page.screenshot(path=str(self.outdir / f"{name}.png"))
        except Exception:
            pass

    def wait_text(self, text, timeout=30, exact=True):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.page.get_by_text(text, exact=exact).count():
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(500)
        return False

    def body_has(self, text):
        try:
            return text in self.page.inner_text("body")
        except Exception:
            return False

    def cp(self):
        return self.page.frames[0]

    def ctx(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if "ctxdslxpro" in f.url:
                    return f
            self.page.wait_for_timeout(800)
        raise RuntimeError("财天下主框架未加载")

    def ptx(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if "ptxinvoicedslxpro" in f.url:
                    return f
            self.page.wait_for_timeout(800)
        raise RuntimeError("票据采集框架未加载")

    # ---------- 任务导航 ----------
    def goto_task(self, title, index=None):
        """title 为任务导航里的 title 前缀，如 '4. 支付借款利息'。"""
        self.page.evaluate(
            """()=>{const e=[...document.querySelectorAll('span,div')]
                 .find(x=>x.textContent.trim()==='任务导航'&&x.offsetParent!==null);
                 if(e)e.click();}"""
        )
        self.page.wait_for_timeout(1500)
        items = self.page.locator(".task-nav .news-list-item-box .new-content")
        picked = None
        for i in range(items.count()):
            it = items.nth(i)
            t = (it.get_attribute("title") or "").strip()
            if index is None and t.startswith(title):
                picked = it
                break
            if index is not None and i == index:
                picked = it
                break
        if picked is None:
            raise RuntimeError(f"任务导航找不到: {title} / index={index}")
        picked.click()
        self.page.wait_for_timeout(2500)
        # 切换任务偶尔弹确认框
        btn = self.page.locator(".el-message-box:visible .el-button--primary")
        if btn.count():
            btn.last.click()
            self.page.wait_for_timeout(2500)
        log(f"已切换到任务: {title}")

    def open_business(self):
        self.page.evaluate(
            """()=>{const e=[...document.querySelectorAll('.button-box div')]
                 .find(x=>x.innerText.trim()==='业务处理'&&x.offsetParent!==null);
                 if(e)e.click();}"""
        )
        self.page.wait_for_timeout(7000)
        # 部分试卷打开后先落在财天下「账套列表」，需点账套名进入后才出现侧边栏
        try:
            f = self.ctx(timeout=10)
            entered = f.evaluate(
                """()=>{const e=[...document.querySelectorAll('span.account-name')]
                     .find(x=>x.offsetParent!==null&&x.textContent.trim());
                     if(e){e.click();return e.textContent.trim();} return null;}"""
            )
            if entered:
                log(f"进入账套: {entered}")
                self.page.wait_for_timeout(7000)
        except Exception:
            pass
        log("业务处理已打开")

    def close_split(self):
        btn = self.page.get_by_text("关闭分屏", exact=True)
        if btn.count():
            btn.first.click()
            self.page.wait_for_timeout(2000)

    def submit(self):
        self.close_split()
        body = self.page.evaluate("document.body.innerText")
        text = "再次提交" if "再次提交" in body else "提交结果"
        log(f"提交结果（{text}）...")
        self.page.evaluate(
            """(t)=>{const e=[...document.querySelectorAll('.button-div-width-auto')]
                 .find(x=>x.innerText.trim()===t&&x.offsetParent!==null);
                 if(e)e.click();}""", text)
        self.page.wait_for_timeout(2000)
        # 自定义“提示”弹窗的确定按钮：优先点可见的 button，纯 text=确定 有时点不到
        clicked = self.page.evaluate(
            """()=>{const bs=[...document.querySelectorAll('button')]
                 .filter(x=>x.offsetWidth>0&&x.innerText.replace(/\\s+/g,'')==='确定');
                 if(bs.length){bs[bs.length-1].click(); return true} return false;}"""
        )
        if not clicked:
            ok = self.page.locator("text=确定")
            for i in range(ok.count()):
                try:
                    ok.nth(i).click(timeout=1500)
                    break
                except Exception:
                    pass
        self.page.wait_for_timeout(3000)
        done = self.wait_text("再次提交", 20)
        log("提交结果: " + ("成功" if done else "未确认，请人工检查"))
        self.shot("submitted")
        return done

    # ---------- 财天下侧边栏 ----------
    def nav(self, category, leaf):
        f = self.ctx()
        f.evaluate(
            """(c)=>{const cat=[...document.querySelectorAll('span.tab-text')]
                 .find(x=>x.textContent.trim()===c);
                 if(cat){const b=cat.closest('.tab-btn'); if(b)b.click();}}""", category)
        self.page.wait_for_timeout(1200)
        ok = f.evaluate(
            """(l)=>{const li=[...document.querySelectorAll('li.tab-child-li')]
                 .find(x=>x.textContent.trim().startsWith(l));
                 if(li){li.click(); return true} return false;}""", leaf)
        if not ok:
            raise RuntimeError(f"侧边栏点不到: {category} / {leaf}")
        self.page.wait_for_timeout(5500)
        log(f"已打开: {category} -> {leaf}")

    # ---------- 票据采集 ----------
    def collect_all(self, tag="collect"):
        """教学票据采集 -> 全选 -> 确定；返回上传提示文本。"""
        f = self.ptx()
        for _ in range(20):
            if f.evaluate("document.querySelectorAll('.classify-item').length"):
                break
            self.page.wait_for_timeout(1000)
        f.locator("button").filter(has_text="教学票据采集").first.click()
        self.page.wait_for_timeout(3500)
        f.evaluate(
            """()=>{const d=[...document.querySelectorAll('.el-dialog__wrapper')]
                 .filter(x=>x.offsetWidth>0).pop(); if(!d)return;
                 const c=[...d.querySelectorAll('.el-checkbox')].find(x=>x.innerText.includes('全选'));
                 if(c&&!c.classList.contains('is-checked')) c.click();}"""
        )
        self.page.wait_for_timeout(700)
        f.evaluate(
            """()=>{const d=[...document.querySelectorAll('.el-dialog__wrapper')]
                 .filter(x=>x.offsetWidth>0).pop(); if(!d)return;
                 const b=d.querySelector('.el-dialog__footer .el-button--primary')
                      || [...d.querySelectorAll('button')].find(x=>x.className.includes('primary'));
                 if(b)b.click();}"""
        )
        self.page.wait_for_timeout(4500)
        txt = f.evaluate("document.body.innerText").replace("\n", " ")
        # 关闭“上传结果”确认框
        f.evaluate(
            """()=>{const d=[...document.querySelectorAll('.el-dialog__wrapper')]
                 .filter(x=>x.offsetWidth>0).pop(); if(!d)return;
                 const b=d.querySelector('.el-dialog__footer .el-button--primary')
                      || [...d.querySelectorAll('button')].find(x=>x.className.includes('primary'));
                 if(b)b.click();}"""
        )
        self.page.wait_for_timeout(2500)
        log("采集结果: " + (txt[txt.find("共上传"):txt.find("共上传") + 80] if "共上传" in txt else "未捕获"))
        self.shot(tag)
        return txt

    def adjust_current(self, target="其他票据", tab="银行回单"):
        """选中文档 -> 调整类型 -> target。"""
        f = self.ptx()
        f.evaluate(
            """(t)=>{const el=[...document.querySelectorAll('.classify-item')]
                 .find(x=>x.textContent.includes(t)); if(el) el.click();}""", tab)
        self.page.wait_for_timeout(3200)
        # 不要点 付款/收款 子页签：点后图片列表会重置为占位图，后续调整弹窗拿不到单据
        f.evaluate(
            """()=>{const imgs=[...document.querySelectorAll('img')].filter(i=>i.offsetWidth>80);
                 const img=imgs.find(i=>i.src.includes('signature'))||imgs[0];
                 if(img) img.click();}"""
        )
        self.page.wait_for_timeout(1800)
        self.page.wait_for_timeout(1200)
        f.locator("button").filter(has_text="调整类型").first.click()
        self.page.wait_for_timeout(2000)
        dlg = f.locator(".el-dialog__wrapper:visible").last
        dlg.locator(".el-select").nth(1).click()
        self.page.wait_for_timeout(1000)
        f.locator(".el-select-dropdown:visible li").filter(has_text=target).first.click()
        self.page.wait_for_timeout(700)
        dlg.locator(".el-dialog__footer .el-button--primary").click()
        self.page.wait_for_timeout(3000)
        counts = f.evaluate(
            "[...document.querySelectorAll('.classify-item')].map(x=>x.innerText.replace(/\\s+/g,' '))")
        log(f"类型调整后: {counts}")

    # ---------- 新增凭证 ----------
    def new_voucher(self):
        self.nav("凭证", "新增凭证")
        self.page.wait_for_timeout(2000)
        return self.ctx()

    def wait_mask_gone(self, frame=None, timeout=20):
        """等 .mack 遮罩消失，否则凭证表格点击会被拦截。"""
        f = frame or self.ctx()
        end = time.time() + timeout
        while time.time() < end:
            try:
                shown = f.evaluate(
                    """()=>[...document.querySelectorAll('.mack,.loading,.el-loading-mask')]
                         .some(e=>e.offsetWidth>0&&e.offsetHeight>0
                              &&getComputedStyle(e).display!=='none'
                              &&getComputedStyle(e).visibility!=='hidden')"""
                )
                if not shown:
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(500)
        log("遮罩仍在，继续尝试点击")
        return False

    def clear_mack(self, frame=None):
        """凭证表格上常驻的 .mack 遮罩会拦截点击（选科目后出现且不消失），直接隐藏。"""
        f = frame or self.ctx()
        try:
            f.evaluate("()=>document.querySelectorAll('.mack').forEach(e=>{e.style.display='none'})")
        except Exception:
            pass

    def fill_row(self, idx, summary, code, amount, side="d", frame=None):
        f = frame or self.ctx()
        self.wait_mask_gone(f)
        self.clear_mack(f)
        rows = lambda: f.locator("tr").filter(has=f.locator("td.num"))
        rows().nth(idx).locator("td").nth(2).click()
        self.page.wait_for_timeout(500)
        rows().nth(idx).locator("td").nth(2).locator("input").first.fill(summary)
        self.page.wait_for_timeout(250)
        # 会计科目是 autocomplete：先在输入框里输代码过滤，再点下拉项。
        # 不能只点开列表找 el-select-dropdown，科目多时目标项根本不在首屏。
        acct_cell = rows().nth(idx).locator("td").nth(3)
        acct_cell.click()
        self.page.wait_for_timeout(500)
        acct_inp = acct_cell.locator("input").first
        try:
            acct_inp.fill("")
        except Exception:
            pass
        acct_inp.type(code, delay=50)
        self.page.wait_for_timeout(1500)
        picked = f.evaluate(
            """(c)=>{const li=[...document.querySelectorAll('.el-select-dropdown__item')]
                 .filter(x=>x.offsetWidth>0&&x.offsetHeight>0)
                 .find(x=>x.innerText.includes(c));
                 if(!li) return false; li.click(); return true;}""", code)
        if not picked:
            self.shot(f"fail_acct_{code}")
            raise RuntimeError(f"会计科目下拉中找不到: {code}")
        self.page.wait_for_timeout(900)
        self.clear_mack(f)
        col = 4 if side == "d" else 5
        amt_cell = rows().nth(idx).locator("td").nth(col)
        amt_cell.click()
        self.page.wait_for_timeout(600)
        self.clear_mack(f)
        amt = amt_cell.locator("input").first
        amt.type(f"{amount:.2f}", delay=40)
        amt.press("Tab")
        self.page.wait_for_timeout(1000)

    def set_header(self, year, month, day, attach=1, frame=None):
        f = frame or self.ctx()
        inputs = f.locator("input:visible")
        idx = f.evaluate(
            """()=>[...document.querySelectorAll('input')].filter(i=>i.offsetWidth>0)
                 .findIndex(i=>i.readOnly&&i.className.includes('el-input__inner'))""")
        inputs.nth(idx).click()
        self.page.wait_for_timeout(900)
        f.evaluate(
            """(d)=>{const panels=[...document.querySelectorAll('.el-picker-panel')]
                 .filter(x=>x.offsetWidth>0); const p=panels[panels.length-1]; if(!p)return;
                 const tds=[...p.querySelectorAll('td.available')]
                 .filter(x=>!x.className.includes('prev-month')&&!x.className.includes('next-month'));
                 const td=tds.find(x=>x.innerText.trim()===d); if(td) td.click();}""", str(day))
        self.page.wait_for_timeout(1000)
        idx2 = f.evaluate(
            """()=>[...document.querySelectorAll('input')].filter(i=>i.offsetWidth>0)
                 .findIndex(i=>!i.readOnly&&i.className.includes('el-input__inner')&&i.value==='0')""")
        if idx2 >= 0:
            inputs.nth(idx2).click()
            inputs.nth(idx2).fill(str(attach))
            inputs.nth(idx2).press("Tab")
            self.page.wait_for_timeout(500)

    def save_button(self, frame=None):
        f = frame or self.ctx()
        f.evaluate(
            """()=>{const b=[...document.querySelectorAll('button')]
                 .find(x=>x.innerText.trim()==='保存'); if(b)b.click();}""")
        self.page.wait_for_timeout(2800)
        return self.body_has("保存成功") or self.body_has("更新成功")

    def attach(self, image_path, frame=None):
        f = frame or self.ctx()
        f.locator(".z-upload__input").first.set_input_files(str(image_path))
        self.page.wait_for_timeout(2500)

    def audit_voucher(self, frame=None):
        f = frame or self.ctx()
        f.evaluate(
            """()=>{const bs=[...document.querySelectorAll('button')]
                 .filter(x=>x.offsetWidth>0&&x.innerText.trim()==='审核');
                 if(bs[0]) bs[0].click();}""")
        self.page.wait_for_timeout(2200)
        try:
            ok = "审核成功" in f.evaluate("document.body.innerText")
        except Exception:
            ok = False
        log("凭证审核: " + ("成功" if ok else "请检查"))
        return ok

    def make_voucher(self, date, entries, image=None, attach_num=1, tag="voucher"):
        """entries: [(摘要, 科目代码, 金额, 'd'/'c'), ...]；自动建凭证+保存+关联图片+审核。"""
        y, m, d = date
        f = self.new_voucher()
        for i, (summary, code, amount, side) in enumerate(entries):
            self.fill_row(i, summary, code, amount, side, frame=f)
        self.set_header(y, m, d, attach_num, frame=f)
        ok = self.save_button(frame=f)
        log(f"凭证保存: {'成功' if ok else '检查'}")
        if image and Path(image).exists():
            self.attach(image, frame=f)
            self.save_button(frame=f)
        self.audit_voucher(frame=f)
        self.shot(tag)
        return f

    # ---------- 个税优化（cp 内嵌答题） ----------
    def goto_task_index(self, n):
        self.close_split()
        f = self.cp()
        f.evaluate(
            """(n)=>{const it=[...document.querySelectorAll('.task-item')]
                 .find(x=>x.innerText.trim()===n); if(it) it.click();}""", str(n))
        self.page.wait_for_timeout(3000)

    def choose_radio(self, text):
        f = self.cp()
        f.locator(".el-radio.single_radio").filter(has_text=text).first.click()
        self.page.wait_for_timeout(1200)

    def nav_ok(self):
        f = self.cp()
        return f.evaluate(
            "[...document.querySelectorAll('.task-item')].map(x=>x.innerText.trim()+':'+x.className)")

    def fill_onlineexcel(self, cells, tag="excel"):
        """cells: [(row, col, value)] 0-based；保存在线表格。"""
        f = None
        for _ in range(40):
            for fr in self.page.frames:
                if "onlineexcel" in fr.url:
                    try:
                        if fr.evaluate("document.querySelectorAll('[id^=spreadCom]').length"):
                            f = fr
                            break
                    except Exception:
                        pass
            if f:
                break
            self.page.wait_for_timeout(1500)
        if not f:
            raise RuntimeError("在线表格未加载")
        self.page.wait_for_timeout(2500)
        f.evaluate(
            """(cells)=>{
                const id=[...document.querySelectorAll('[id]')]
                    .map(e=>e.id).find(i=>/^spreadCom\\d+$/.test(i));
                const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
                const s=sp.getSheet(0);
                for(const [r,c,v] of cells) s.setValue(r,c,v);
                sp.repaint();
            }""", cells)
        self.page.wait_for_timeout(1000)
        f.evaluate(
            """()=>{const b=[...document.querySelectorAll('button,div,span')]
                 .find(x=>x.innerText.trim()==='保存'&&x.offsetWidth>0); if(b)b.click();}""")
        self.page.wait_for_timeout(3500)
        log("在线表格已保存")
        self.shot(tag)
