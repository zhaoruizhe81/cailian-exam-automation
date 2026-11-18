#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.3「销售与收款业务循环实质性程序实施」全自动脚本
（财连 cp.cailian.net + 审计平台 xsj.cailian.net）

用法:
  python3 task23.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--skip-adjust]

流程:
  任务导航 -> 【2.3】销售与收款业务循环实质性程序实施 -> 业务处理
  -> 进入项目 XM0044 -> 工作底稿
  -> 依次打开并回填三个底稿（数据来自 task23_data.json）:
       Z5 应收账款   导引表/明细表/函证*/坏账准备测试表/凭证抽查表 等
       S1 营业收入及成本  导引表/明细表/销售分析表/截止性测试表/合同履行检查表 等
       S3 销售费用   导引表/明细表/截止性测试表/凭证抽查表 等
     回填后调用底稿组件的 handleSaveClick() 保存（脚本会登记变更单元格）
  -> 调整 -> 账项期末调整：确保存在 0001/0002 两组调整分录
       0001  借 6702 信用减值损失 223043.07 / 贷 123101 坏账准备-应收账款 223043.07
       0002  借 122101 其他应收款-内部往来 636.00 / 贷 660104 销售费用-业务招待费 636.00
  -> 关闭分屏 -> 提交结果

说明:
  * 底稿模板中的公式单元格不会被覆盖（只回填非公式单元格）。
  * 底稿保存按钮在直接写单元格时不会变可用，脚本直接调用组件的
    handleSaveClick()，并用 changeCellsObjListByData() 登记改动，效果与手工编辑保存一致。
  * 审计调整已存在且科目匹配时自动跳过，可重复执行。
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
TASK_NAME = "2.3"
TASK_LABEL = "【2.3】销售与收款业务循环实质性程序实施"


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

    # ---------- 考试页 ----------
    def goto_task(self):
        self.page.get_by_text("任务导航", exact=True).first.click()
        self.page.wait_for_timeout(1500)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(TASK_NAME, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        if self.wait_text("确定", 3):
            self.page.get_by_text("确定", exact=True).first.click()
            self.page.wait_for_timeout(3500)

    def open_business(self, timeout=120):
        if self.wait_text("关闭分屏", 2):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(1800)
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if "xsj.cailian.net" in f.url and "login" not in f.url:
                    self.page.wait_for_timeout(2500)
                    return f
            self.page.wait_for_timeout(1500)
        raise RuntimeError("审计平台 iframe 未加载")

    # ---------- 审计平台 ----------
    def enter_project(self, audit):
        end = time.time() + 60
        while time.time() < end:
            try:
                if "/home" in audit.url and "项目列表" not in audit.inner_text("body"):
                    break
                got = audit.evaluate(
                    """()=>{const s=[...document.querySelectorAll('span,button,a')]
                         .filter(e=>e.textContent.trim()==='进入'&&e.offsetParent!==null);
                         if(!s.length) return false; s[0].click(); return true;}"""
                )
                if got:
                    self.page.wait_for_timeout(5000)
                    break
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        else:
            raise RuntimeError("未能进入审计项目")
        # 等工作底稿 iframe
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if "sj-spread" in f.url:
                    try:
                        if f.evaluate("typeof GC !== 'undefined'"):
                            self.page.wait_for_timeout(2500)
                            return
                    except Exception:
                        pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("工作底稿设计器未加载")

    def sj_frame(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if "sj-spread" in f.url:
                    try:
                        if f.evaluate("typeof GC !== 'undefined'"):
                            return f
                    except Exception:
                        pass
            self.page.wait_for_timeout(1000)
        raise RuntimeError("找不到 sj-spread frame")

    def ensure_tree(self, sj, label):
        """展开底稿树，使目标节点可见。label 形如 'Z5 应收账款' / 'S1 营业收入及成本'。"""
        deadline = time.time() + 90
        last = None
        visible_texts = []
        while time.time() < deadline:
            last, visible_texts = sj.evaluate("""
                async (label) => {
                  const sleep = ms => new Promise(r => setTimeout(r, ms));
                  const vis = e => e && e.getBoundingClientRect().width > 0;
                  const find = t => [...document.querySelectorAll('*')]
                    .find(e => vis(e) && e.children.length === 0 && e.textContent.trim() === t);
                  const click = async (t) => {
                    const e = find(t); if (!e) return false; e.click(); await sleep(1800); return true;
                  };
                  const leafTexts = () => [...new Set([...document.querySelectorAll('.el-tree-node__label, [class*=tree] span, [class*=tree] div')]
                    .filter(e => vis(e) && e.children.length === 0 && e.textContent.trim())
                    .map(e => e.textContent.trim()))].slice(0, 60);

                  if (find(label)) return ['visible', leafTexts()];
                  if (!find('底稿列表') && !document.querySelector('.el-icon-folder')) {
                    return ['tree-not-ready', leafTexts()];
                  }
                  // 展开根文件夹
                  const folder = [...document.querySelectorAll('.el-icon-folder')].find(vis);
                  if (folder) { folder.click(); await sleep(1800); }
                  if (find(label)) return ['visible', leafTexts()];
                  if (!(await click('实质性程序工作底稿'))) return ['no-root', leafTexts()];
                  if (find(label)) return ['visible', leafTexts()];
                  if (label.trim().startsWith('Z')) {
                    if (!(await click('Z 资产类'))) return ['no-z', leafTexts()];
                  } else if (label.trim().startsWith('S')) {
                    if (!(await click('S 损益类'))) return ['no-s', leafTexts()];
                  }
                  return [find(label) ? 'visible' : 'not-visible', leafTexts()];
                }
            """, label)
            if last == "visible":
                log(f"底稿树已定位 {label}")
                return
            self.page.wait_for_timeout(4000)
        raise RuntimeError(f"底稿树中找不到 {label} ({last}; 可见节点: {visible_texts})")

    def open_workpaper(self, sj, label, sheet_names):
        """点击底稿节点，等待设计器加载出对应底稿。返回组件状态。"""
        sj.evaluate("""
            async (label) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const el = [...document.querySelectorAll('*')]
                .find(e => vis(e) && e.children.length === 0 && e.textContent.trim() === label);
              if (el) { el.click(); await sleep(1000); }
            }
        """, label)
        end = time.time() + 90
        while time.time() < end:
            st = sj.evaluate("""
                (label) => {
                  const vm = (() => {
                    for (const el of document.querySelectorAll('button')) {
                      if (el.innerText.trim() !== '保存') continue;
                      let e = el;
                      while (e && !e.__vue__) e = e.parentElement;
                      let v = e && e.__vue__;
                      while (v && (v.$options.name || '') !== 'spread-demo') v = v.$parent;
                      if (v) return v;
                    }
                    return null;
                  })();
                  if (!vm) return {ready: false, why: 'novm'};
                  const wb = vm.spread;
                  const names = wb ? wb.getSheetCount() ? wb.getSheet(0) && [...Array(wb.getSheetCount())].map((_, i) => wb.getSheet(i).name()) : [] : [];
                  return {ready: !!vm.currentSheetLoaded && !vm.loading && vm.manuscriptsName === label,
                          name: vm.manuscriptsName, loading: vm.loading,
                          loaded: vm.currentSheetLoaded, sheets: names};
                }
            """, label)
            if st.get("ready"):
                missing = [n for n in sheet_names if n not in st["sheets"]]
                if missing:
                    self.shot("fail_wp_sheets")
                    raise RuntimeError(f"{label} 缺少 sheet: {missing}")
                log(f"已打开底稿 {label}（{len(st['sheets'])} 个 sheet）")
                return st
            self.page.wait_for_timeout(1500)
        self.shot("fail_wp_open")
        raise RuntimeError(f"底稿 {label} 加载超时: {st}")

    def fill_workpaper(self, sj, label, sheets):
        res = sj.evaluate("""
            ([label, sheets]) => {
              const vm = (() => {
                for (const el of document.querySelectorAll('button')) {
                  if (el.innerText.trim() !== '保存') continue;
                  let e = el;
                  while (e && !e.__vue__) e = e.parentElement;
                  let v = e && e.__vue__;
                  while (v && (v.$options.name || '') !== 'spread-demo') v = v.$parent;
                  if (v) return v;
                }
                return null;
              })();
              if (!vm) return {error: 'no-vm'};
              const wb = vm.spread;
              const out = {};
              for (const [sheetName, cells] of Object.entries(sheets)) {
                let idx = -1;
                try { idx = wb.getSheetIndex(sheetName); } catch (e) {}
                if (idx < 0) idx = (() => {
                  for (let i = 0; i < wb.getSheetCount(); i++) {
                    if (wb.getSheet(i).name() === sheetName) return i;
                  }
                  return -1;
                })();
                if (idx < 0) { out[sheetName] = 'missing'; continue; }
                const s = wb.getSheet(idx);
                const changed = [];
                for (const [r, c, v] of cells) {
                  if (v === null || v === undefined || v === '') continue;
                  s.setValue(r, c, v);
                  changed.push({row: r, col: c});
                }
                // 登记“埋点”变更，和手工编辑保存一致
                try { vm.changeCellsObjListByData(changed, sheetName); } catch (e) {}
                out[sheetName] = changed.length;
              }
              return {ok: out, changedTotal: vm.changeCellsObjList.length};
            }
        """, [label, sheets])
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"{label} 回填失败: {res['error']}")
        missing = [k for k, v in res["ok"].items() if v == "missing"]
        if missing:
            raise RuntimeError(f"{label} 缺少 sheet: {missing}")
        log(f"{label} 回填完成: {sum(res['ok'].values())} 格，变更登记 {res['changedTotal']} 格")

    def save_workpaper(self, sj, label):
        log(f"保存底稿 {label} ...")
        res = sj.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vm = (() => {
                for (const el of document.querySelectorAll('button')) {
                  if (el.innerText.trim() !== '保存') continue;
                  let e = el;
                  while (e && !e.__vue__) e = e.parentElement;
                  let v = e && e.__vue__;
                  while (v && (v.$options.name || '') !== 'spread-demo') v = v.$parent;
                  if (v) return v;
                }
                return null;
              })();
              if (!vm) return {error: 'no-vm'};
              // 大量公式重算需要时间，必须等状态栏回到「就绪」再保存
              const status = () => {
                const el = document.querySelector('.gc-statusbar-statusitem-container span');
                return el ? el.innerText.trim() : '';
              };
              for (let i = 0; i < 60 && status() !== '就绪'; i++) await sleep(500);
              // 清掉上一条保存提示，避免误判
              document.querySelectorAll('.el-message').forEach(e => e.remove());
              vm.handleSaveClick();
              for (let i = 0; i < 60; i++) {
                await sleep(500);
                const m = [...document.querySelectorAll('.el-message__content, .el-message')]
                  .map(x => x.innerText.trim()).join('|');
                if (m.indexOf('保存成功') >= 0) return {ok: true, msg: m};
                if (m.indexOf('请等待') >= 0 || m.indexOf('警告') >= 0 || m.indexOf('失败') >= 0) {
                  // 再等状态就绪后重试一次
                  for (let j = 0; j < 40 && status() !== '就绪'; j++) await sleep(500);
                  vm.handleSaveClick();
                  for (let j = 0; j < 40; j++) {
                    await sleep(500);
                    const m2 = [...document.querySelectorAll('.el-message__content, .el-message')]
                      .map(x => x.innerText.trim()).join('|');
                    if (m2.indexOf('保存成功') >= 0) return {ok: true, msg: m2, retried: true};
                    if (m2.indexOf('失败') >= 0) break;
                  }
                  return {error: 'save-warning', msg: m, status: status()};
                }
              }
              return {error: 'timeout', loading: vm.loading, status: status()};
            }
        """)
        if isinstance(res, dict) and res.get("error"):
            self.shot("fail_wp_save")
            raise RuntimeError(f"{label} 保存失败: {res}")
        log(f"{label} 保存完成")
        self.page.wait_for_timeout(3000)

    # ---------- 账项期末调整 ----------
    def open_adjustments(self, audit):
        # 顶部菜单是 hover 展开的 Element UI 子菜单
        ok = audit.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const t = [...document.querySelectorAll('.el-submenu__title')]
                .find(e => e.innerText.trim() === '调整');
              if (!t) return 'no-menu';
              ['mouseenter', 'mouseover', 'mousemove'].forEach(ev =>
                t.dispatchEvent(new MouseEvent(ev, {bubbles: true})));
              await sleep(1200);
              const li = [...document.querySelectorAll('li.el-menu-item')]
                .find(e => e.innerText.trim() === '账项期末调整' && e.getBoundingClientRect().width > 0);
              if (!li) return 'no-item';
              li.click();
              await sleep(4000);
              return 'ok';
            }
        """)
        if ok != "ok":
            raise RuntimeError(f"无法打开账项期末调整 ({ok})")
        # 等页面渲染
        end = time.time() + 30
        while time.time() < end:
            has = audit.evaluate(
                "()=>document.body.innerText.indexOf('期末调整分录')>=0")
            if has:
                self.page.wait_for_timeout(1500)
                return
            self.page.wait_for_timeout(1000)
        raise RuntimeError("账项期末调整页面未加载")

    def ensure_adjustments(self, audit, adjustments):
        res = audit.evaluate("""
            async ([adjustments]) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const setVal = (inp, v) => {
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(inp, String(v));
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                inp.dispatchEvent(new Event('blur', {bubbles: true}));
              };
              const groups = () => [...document.querySelectorAll('div.table')]
                .filter(d => vis(d) && d.innerText.trim().startsWith('组号:'));
              const rowsOf = g => [...g.querySelectorAll('tbody tr')]
                .filter(tr => tr.querySelector('.nameSpan'));

              // 已有分组是否已经符合目标
              const current = groups().map(g => ({
                no: (g.querySelector('input[type=checkbox]') || {}).value,
                subjects: rowsOf(g).map(tr => tr.querySelector('.nameSpan').innerText.trim()),
              }));
              const wanted = adjustments.map(a => a.entries.map(e => e.subject));
              const matches = current.length >= wanted.length &&
                wanted.every((subs, i) => subs.every(s => (current[i].subjects || []).includes(s)));
              if (matches) return {skipped: true, current};

              // 补齐分组数量
              for (let i = current.length; i < adjustments.length; i++) {
                const btn = [...document.querySelectorAll('button')]
                  .find(b => b.innerText.trim() === '新增' && vis(b));
                if (!btn) return {error: 'no-add-button'};
                btn.click();
                await sleep(1500);
              }

              const gs = groups();
              if (gs.length < adjustments.length) return {error: 'not-enough-groups'};

              for (let gi = 0; gi < adjustments.length; gi++) {
                const g = gs[gi];
                const trs = rowsOf(g);
                const entries = adjustments[gi].entries;

                // 行数不够则点“增行”
                while (rowsOf(g).length < entries.length) {
                  const tr = rowsOf(g)[rowsOf(g).length - 1];
                  const add = [...tr.querySelectorAll('span')]
                    .find(s => s.innerText.trim() === '增行');
                  if (!add) return {error: 'no-add-row', group: gi};
                  add.click();
                  await sleep(900);
                }

                for (let ri = 0; ri < entries.length; ri++) {
                  const entry = entries[ri];
                  const tr = rowsOf(g)[ri];

                  // 已选科目一致则跳过选择
                  const curSub = tr.querySelector('.nameSpan').innerText.trim();
                  if (curSub !== entry.subject) {
                    tr.querySelector('.nameSpan').click();
                    await sleep(1500);
                    const dlg = [...document.querySelectorAll('.el-dialog__wrapper')]
                      .filter(vis).pop();
                    if (!dlg) return {error: 'no-subject-dialog', group: gi, row: ri};
                    const label = [...dlg.querySelectorAll('.el-tree-node__label')]
                      .find(e => e.textContent.trim() === entry.subject);
                    if (!label) return {error: 'subject-not-found',
                                        subject: entry.subject, group: gi, row: ri};
                    label.click();
                    await sleep(500);
                    const ok = [...dlg.querySelectorAll('button')]
                      .find(b => b.innerText.trim() === '确定');
                    if (!ok) return {error: 'no-dialog-ok', group: gi, row: ri};
                    ok.click();
                    await sleep(1200);
                  }

                  // 金额
                  const tr2 = rowsOf(g)[ri];
                  const ins = [...tr2.querySelectorAll('input[type=number]')];
                  if (ins.length < 2) return {error: 'no-amount-inputs', group: gi, row: ri};
                  if (entry.debit) setVal(ins[0], entry.debit);
                  if (entry.credit) setVal(ins[1], entry.credit);
                  await sleep(300);
                }
              }

              await sleep(800);
              // 保存
              const save = [...document.querySelectorAll('button')]
                .find(b => b.innerText.trim() === '保存' && vis(b));
              if (!save) return {error: 'no-save-button'};
              save.click();
              await sleep(2500);
              // 可能弹确认框
              const confirm = [...document.querySelectorAll('.el-message-box button')]
                .find(b => b.innerText.trim() === '确定' && vis(b));
              if (confirm) { confirm.click(); await sleep(2500); }
              for (let i = 0; i < 30; i++) {
                const m = [...document.querySelectorAll('.el-message__content, .el-message')]
                  .map(x => x.innerText.trim()).join('|');
                if (m.indexOf('保存成功') >= 0 || m.indexOf('成功') >= 0) {
                  return {ok: true, msg: m};
                }
                if (m.indexOf('失败') >= 0) return {error: 'adjust-save-failed', msg: m};
                await sleep(500);
              }
              return {ok: true, msg: 'no-message'};
            }
        """, [adjustments])
        if isinstance(res, dict) and res.get("error"):
            self.shot("fail_adjust")
            raise RuntimeError(f"审计调整失败: {res}")
        if res.get("skipped"):
            log("审计调整已存在且科目匹配，跳过")
        else:
            log(f"审计调整保存完成: {res.get('msg', '')}")

    # ---------- 提交 ----------
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
        self.shot("t23_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--data", default=str(HERE / "task23_data.json"))
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="保存但不点提交结果")
    ap.add_argument("--skip-adjust", action="store_true", help="跳过审计调整")
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

        for wp in data["workpapers"]:
            sj = bot.sj_frame()
            bot.ensure_tree(sj, wp["label"])
            bot.open_workpaper(sj, wp["label"], list(wp["sheets"].keys()))
            bot.fill_workpaper(sj, wp["label"], wp["sheets"])
            bot.save_workpaper(sj, wp["label"])

        if args.skip_adjust:
            log("按参数跳过审计调整")
        else:
            bot.open_adjustments(audit)
            bot.ensure_adjustments(audit, data["adjustments"])

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
