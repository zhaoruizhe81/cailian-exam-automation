#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.0「数据提供」全自动脚本（财连 cp.cailian.net + 审计数据上传系统）

用法:
  python3 task20.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run]

流程:
  任务导航 -> 【任务2.0】数据提供 -> 业务处理
  -> answer.cailian.net「审计数据上传系统」登录（平台内置账号，可用环境变量
     CAILIAN_UPLOAD_USER / CAILIAN_UPLOAD_PASS 覆盖，默认见下方 LOGIN）
  -> 四个类别分别「上传」并勾选对应文件（文件为平台预置）：
       财务数据 -> 财务数据.xls
       应收账款 -> 应收账款.xls
       营业收入及成本 -> 营业收入及成本.xls
       销售费用 -> 销售费用.xls
  -> 保 存 -> 关闭分屏 -> 提交结果

说明:
  * 上传对话框会列出平台预置的全部 4 个 xls 文件，每个类别只勾选属于自己的那一个。
  * 已上传（按钮显示“上传成功”）的类别脚本会自动跳过，可重复执行。
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"
TASK_NAME = "【任务2.0】数据提供"
# 平台内置的上传系统账号（每套试卷不同），可用环境变量覆盖
LOGIN = (
    os.environ.get("CAILIAN_UPLOAD_USER", "SJ101261001"),
    os.environ.get("CAILIAN_UPLOAD_PASS", "123456"),
)
CATEGORIES = [
    ("财务数据", "财务数据.xls"),
    ("应收账款", "应收账款.xls"),
    ("营业收入及成本", "营业收入及成本.xls"),
    ("销售费用", "销售费用.xls"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class UploadBot:
    def __init__(self, page, outdir: Path):
        self.page = page
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)
        self.frame = None

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

    def click_exam_text(self, text):
        self.page.evaluate(
            """(t)=>{const e=[...document.querySelectorAll('span,div')]
                 .find(x=>x.textContent.trim()===t&&x.offsetParent!==null&&x.children.length===0);
                 if(e)e.click();}""", text)

    def goto_task(self):
        # 只按「当前任务标题」判断，别用「再次提交」——别的任务已提交时会误判成已在本任务
        try:
            title = self.page.locator(".title-text").first.inner_text(timeout=3000)
        except Exception:
            title = ""
        if "数据提供" in title:
            log(f"当前已在「{title}」")
            return
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
            self.click_exam_text("关闭分屏")
            self.page.wait_for_timeout(1800)
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if "answer.cailian.net" in f.url:
                    self.frame = f
                    self.page.wait_for_timeout(2500)
                    return f
            self.page.wait_for_timeout(1500)
        raise RuntimeError("审计数据上传系统 iframe 未加载")

    # ---------- 上传系统 ----------
    def login(self):
        f = self.frame
        state = f.evaluate("() => document.body.innerText.slice(0,200)")
        if "登 录" not in state:
            log("已登录")
            return
        f.evaluate("""
            ([acct, pwd]) => {
              const setVal = (inp, v) => {
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(inp, v);
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
              };
              const ins = [...document.querySelectorAll('input')].filter(i => i.type === 'text');
              setVal(ins[0], acct);
              setVal(ins[1], pwd);
            }
        """, list(LOGIN))
        f.evaluate("""
            () => {
              const b = [...document.querySelectorAll('button')].find(x => x.innerText.includes('登'));
              if (b) b.click();
            }
        """)
        self.page.wait_for_timeout(4000)
        if "审计数据上传系统" not in f.evaluate("() => document.body.innerText"):
            raise RuntimeError("上传系统登录失败")
        log("上传系统登录成功")

    def upload_one(self, category, filename):
        f = self.frame
        r = f.evaluate("""
            async ([cat]) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = el => el && el.getBoundingClientRect().width > 0;
              const rows = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r));
              const row = rows.find(r => r.innerText.trim().startsWith(cat));
              if (!row) return 'no-row';
              if (row.innerText.includes('上传成功')) return 'already';
              const btn = [...row.querySelectorAll('button')].find(b => b.innerText.includes('上传'));
              if (!btn) return 'no-btn';
              btn.click();
              await sleep(1800);
              return 'opened';
            }
        """, [category])
        if r in ("already",):
            log(f"{category}: 已上传，跳过")
            return
        if r in ("no-row", "no-btn"):
            raise RuntimeError(f"{category}: 上传入口未找到 ({r})")

        # 勾选对应文件
        ok = f.evaluate("""
            async ([filename]) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = el => el && el.getBoundingClientRect().width > 0;
              const dlg = [...document.querySelectorAll('.el-dialog')]
                .filter(d => vis(d) && d.innerText.includes('文件列表')).pop();
              if (!dlg) return 'no-dialog';
              const rows = [...dlg.querySelectorAll('.el-table__body tbody tr')];
              let target = null;
              for (const tr of rows) {
                const isTarget = tr.innerText.includes(filename);
                if (isTarget) target = tr;
                const cb = tr.querySelector('.el-checkbox');
                if (!cb) continue;
                const input = tr.querySelector('input.el-checkbox__original');
                if (isTarget && !input.checked) {
                  cb.click();
                  await sleep(200);
                } else if (!isTarget && input.checked) {
                  cb.click();
                  await sleep(200);
                }
              }
              if (!target) return 'no-file';
              const okBtn = [...dlg.querySelectorAll('button')]
                .find(b => b.textContent.includes('确'));
              if (!okBtn) return 'no-ok';
              okBtn.click();
              await sleep(2200);
              return 'ok';
            }
        """, [filename])
        if ok != "ok":
            raise RuntimeError(f"{category}: 文件勾选失败 ({ok})")
        log(f"{category}: 上传完成 -> {filename}")

    def save(self):
        ok = self.frame.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const b = [...document.querySelectorAll('button')]
                .find(x => x.innerText.replace(/\\s/g, '') === '保存');
              if (!b) return false;
              b.click();
              await sleep(2500);
              return true;
            }
        """)
        if not ok:
            raise RuntimeError("找不到保存按钮")
        log("已保存上传结果")

    def submit_result(self):
        if self.wait_text("关闭分屏", 2):
            self.click_exam_text("关闭分屏")
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
        self.shot("t20_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="保存但不点提交结果")
    args = ap.parse_args()

    token_file = HERE / "sx_token.txt"
    sx_token = args.sx_token.strip() or (token_file.read_text(encoding="utf-8").strip()
                                         if token_file.exists() else "")
    if not sx_token:
        raise RuntimeError("缺少 sx token（--sx-token 或 sx_token.txt）")
    outdir = HERE / "out"

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=args.headless,
            viewport={"width": 1440, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        bot = UploadBot(page, outdir)

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
        bot.open_business()
        bot.login()
        for cat, fn in CATEGORIES:
            bot.upload_one(cat, fn)
        bot.save()

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
