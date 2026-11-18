#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务2.1.1「数据校验、科目映射」全自动脚本（财连 cp.cailian.net + 审计平台）

用法:
  python3 task211.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run]

流程（进入项目 XM0044 后）:
  1. 数据校验
     - 科目信息校验：设置科目类型
           1=资产 2=负债 4=权益 5=成本 6=损益 -> 应用数据 -> 校验
     - 凭证平衡校验：选择「十二月」-> 校验（差额全为 0）
     - 核算项目与科目校验：校验（期初/借/贷/期末差额全为 0）
     - 借贷发生额校验：校验（借贷差额全为 0）
  2. 标记结转：设置结转科目 4103 本年利润 -> 确定 -> 保存
  3. 科目映射：手动建立
           1231 坏账准备 -> 应收账款
           4001 实收资本 -> 民营资本
  4. 报表 -> 未审报表：截止月份 202212 -> 校验（资产负债平衡 OK）-> 保存
  5. 关闭分屏 -> 提交结果
"""
import argparse
import base64
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"
TASK_NAME = "2.1.1"

SUBJECT_TYPES = {1: "资产", 2: "负债", 4: "权益", 5: "成本", 6: "损益"}
CARRYOVER_SUBJECT = "4103 本年利润"
MAPPINGS = [
    {"subject_code": "1231", "subject": "坏账准备", "report": "应收账款"},
    {"subject_code": "4001", "subject": "实收资本", "report": "民营资本"},
]
REPORT_MONTH = "202212"


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
        # 数据准备页不会自动加载 sj-spread，这里只等 xsj 主页面就绪
        end = time.time() + 30
        while time.time() < end:
            try:
                if "工作底稿" in audit.inner_text("body"):
                    return
            except Exception:
                pass
            self.page.wait_for_timeout(1000)
        raise RuntimeError("审计平台项目主页未加载")

    # ---------- 菜单 ----------
    def open_menu(self, audit, menu, item):
        ok = audit.evaluate("""
            async ([menu, item]) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const t = [...document.querySelectorAll('.el-submenu__title')]
                .find(e => e.innerText.trim() === menu);
              if (!t) return 'no-menu';
              ['mouseenter','mouseover','mousemove'].forEach(ev =>
                t.dispatchEvent(new MouseEvent(ev, {bubbles: true})));
              await sleep(1200);
              const li = [...document.querySelectorAll('li.el-menu-item')]
                .find(e => e.innerText.trim() === item && e.getBoundingClientRect().width > 0);
              if (!li) return 'no-item';
              li.click();
              await sleep(4000);
              return 'ok';
            }
        """, [menu, item])
        if ok != "ok":
            raise RuntimeError(f"打开菜单 {menu}->{item} 失败: {ok}")
        log(f"已打开 {menu}->{item}")

    # ---------- 数据校验 ----------
    def click_tab(self, audit, name):
        ok = audit.evaluate("""
            async (name) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const b = [...document.querySelectorAll('button.tabselected, button.noselected')]
                .find(x => x.innerText.trim() === name);
              if (!b) return false;
              b.click(); await sleep(1200); return true;
            }
        """, name)
        if not ok:
            raise RuntimeError(f"找不到校验页签 {name}")
        self.page.wait_for_timeout(1500)

    def click_run(self, audit, name, wait=4000):
        ok = audit.evaluate("""
            async (name) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const b = [...document.querySelectorAll('button')]
                .filter(x => x.innerText.trim() === name && vis(x) &&
                             !x.className.includes('tabselected') &&
                             !x.className.includes('noselected')).pop();
              if (!b) return false;
              b.click(); await sleep(1200); return true;
            }
        """, name)
        if not ok:
            # 已经校验过的页签可能不再显示运行按钮，数据会直接展示
            log(f"页签 {name} 未显示运行按钮，按已加载处理")
            self.page.wait_for_timeout(2000)
            return False
        self.page.wait_for_timeout(wait)
        return True

    def subject_info_check(self, audit):
        self.open_menu(audit, "数据", "数据校验")
        self.click_tab(audit, "科目信息校验")
        self.click_run(audit, "科目信息校验", 5000)
        # 等「设置科目类型」表格出现
        end = time.time() + 30
        while time.time() < end:
            ready = audit.evaluate("""
                () => {
                  const vis = e => e && e.getBoundingClientRect().width > 0;
                  return !!([...document.querySelectorAll('.el-table')]
                    .find(t => vis(t) && t.innerText.includes('编码起始')));
                }
            """)
            if ready:
                break
            self.page.wait_for_timeout(1000)
        else:
            raise RuntimeError("科目信息校验表格未加载")

        res = audit.evaluate("""
            async (types) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const header = [...document.querySelectorAll('.el-table')]
                .find(t => vis(t) && t.innerText.includes('编码起始'));
              if (!header) return {error: 'no-table'};
              const rows = [...header.querySelectorAll('.el-table__body tr')];
              const changed = [];
              for (const tr of rows) {
                const code = parseInt(tr.innerText.trim().split(/\\s+/)[0], 10);
                const want = types[String(code)];
                if (!want) continue;
                const input = tr.querySelector('.el-select input');
                if (!input) continue;
                if (input.value.trim() === want) continue;
                let sel = input;
                while (sel && !(sel.__vue__ && (sel.__vue__.$options.name || '') === 'ElSelect')) {
                  sel = sel.parentElement;
                }
                if (!sel) return {error: 'no-select-vm', code};
                sel.__vue__.$emit('input', want);
                await sleep(300);
                changed.push([code, want]);
              }
              // 应用数据 -> 确认框「是否确认应用新的科目类型?」
              const apply = [...document.querySelectorAll('span.resetdata')]
                .find(s => s.innerText.trim() === '应用数据');
              if (!apply) return {error: 'no-apply'};
              apply.click();
              let confirmed = false;
              for (let i = 0; i < 20; i++) {
                await sleep(500);
                const ok = [...document.querySelectorAll('.el-message-box__btns button')]
                  .find(b => b.innerText.trim() === '确定' && vis(b));
                if (ok) { ok.click(); confirmed = true; break; }
              }
              if (!confirmed) return {error: 'no-apply-confirm'};
              await sleep(3000);
              const m = [...document.querySelectorAll('.el-message')]
                .map(x => x.innerText.trim()).join('|');
              if (m.indexOf('保存成功') < 0 && m.indexOf('成功') < 0) {
                return {error: 'apply-not-saved', msg: m};
              }
              return {changed};
            }
        """, {str(k): v for k, v in SUBJECT_TYPES.items()})
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"科目信息校验失败: {res}")
        log(f"科目类型已设置: {res.get('changed') or '无需修改'}")

        # 应用后核对科目类型（应用数据后页签内不再有单独的“科目信息校验”运行按钮）
        self.page.wait_for_timeout(1500)
        vals = audit.evaluate("""
            () => {
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const header = [...document.querySelectorAll('.el-table')]
                .find(t => vis(t) && t.innerText.includes('编码起始'));
              if (!header) return null;
              return Object.fromEntries([...header.querySelectorAll('.el-table__body tr')].map(tr => {
                const code = tr.innerText.trim().split(/\\s+/)[0];
                const input = tr.querySelector('.el-select input');
                return [code, input ? input.value.trim() : ''];
              }));
            }
        """)
        for code, want in SUBJECT_TYPES.items():
            got = (vals or {}).get(str(code))
            if got != want:
                raise RuntimeError(f"科目类型 {code} 期望 {want}，实际 {got}")
        log("科目信息校验通过")

    def voucher_balance_check(self, audit):
        self.click_tab(audit, "凭证平衡校验")
        self.click_run(audit, "凭证平衡校验", 4000)

        res = audit.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = e => e && e.getBoundingClientRect().width > 0;
              // 找到含「十二月」选项的 ElSelect（月份下拉）
              let monthSel = null;
              for (let i = 0; i < 20 && !monthSel; i++) {
                for (const el of document.querySelectorAll('.el-select')) {
                  const vm = el.__vue__;
                  if (!vm || (vm.$options.name || '') !== 'ElSelect') continue;
                  if ((vm.options || []).some(o => o.label === '十二月')) { monthSel = vm; break; }
                }
                if (!monthSel) await sleep(1000);
              }
              if (!monthSel) return {error: 'no-month-select'};
              const opt = monthSel.options.find(o => o.label === '十二月');
              monthSel.$emit('input', opt.value);
              monthSel.$emit('change', opt.value);
              await sleep(6000);
              const rows = [...document.querySelectorAll('.el-table__body tr')].filter(vis);
              const bad = [];
              let n = 0;
              for (const tr of rows) {
                const txt = tr.innerText.replace(/\\s+/g, ' ').trim();
                if (!txt || txt.includes('暂无数据')) continue;
                const nums = txt.split(' ');
                const last = nums[nums.length - 1];
                if (!isNaN(parseFloat(last)) && Math.abs(parseFloat(last)) > 0.005) bad.push(txt);
                n++;
              }
              return {count: n, bad: bad.slice(0, 5)};
            }
        """)
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"凭证平衡校验失败: {res}")
        if res["bad"]:
            raise RuntimeError(f"凭证平衡存在差额: {res['bad']}")
        log(f"凭证明细十二月共 {res['count']} 条，借贷平衡")

    def _diff_check(self, audit, tab, diff_positions):
        """通用：跑校验后按「数字型 token」的位置检查差额为 0。

        核算项目与科目校验：差额在数字型 token 的第 2/5/8/11 位（0 基）
        借贷发生额校验：差额在第 2/5 位
        """
        self.click_tab(audit, tab)
        self.click_run(audit, tab, 5000)
        res = audit.evaluate("""
            (positions) => {
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const rows = [...document.querySelectorAll('.el-table__body tr')].filter(vis);
              const bad = [];
              let n = 0;
              for (const tr of rows) {
                const tds = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
                if (!tds.length || tds.some(t => t === '暂无数据')) continue;
                if (tds.length <= Math.max(...positions)) continue;
                for (const p of positions) {
                  const v = parseFloat((tds[p] || '').replace(/,/g, ''));
                  if (!isNaN(v) && Math.abs(v) > 0.005) {
                    bad.push(tds.join(' '));
                    break;
                  }
                }
                n++;
              }
              return {count: n, bad: bad.slice(0, 5)};
            }
        """, diff_positions)
        if res["bad"]:
            raise RuntimeError(f"{tab} 存在差额: {res['bad']}")
        log(f"{tab} 共 {res['count']} 条，差额为 0")

    # ---------- 标记结转 ----------
    def carryover(self, audit):
        self.open_menu(audit, "数据", "标记结转")
        res = audit.evaluate("""
            async ([subject]) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vis = e => e && e.getBoundingClientRect().width > 0;
              const open = [...document.querySelectorAll('button')]
                .find(b => b.innerText.trim() === '设置结转科目' && vis(b));
              if (!open) return {error: 'no-open'};
              open.click();
              let dlg = null;
              for (let i = 0; i < 20; i++) {
                await sleep(500);
                dlg = [...document.querySelectorAll('.el-dialog__wrapper')].filter(vis).pop();
                if (dlg) break;
              }
              if (!dlg) return {error: 'no-dialog'};
              const label = [...dlg.querySelectorAll('.el-tree-node__label')]
                .find(e => e.textContent.trim() === subject);
              if (!label) return {error: 'no-subject'};
              const node = label.closest('.el-tree-node');
              let checked = node.className.includes('is-checked');
              if (!checked) {
                const cb = label.closest('.el-tree-node__content').querySelector('.el-checkbox');
                if (!cb) return {error: 'no-checkbox'};
                cb.click(); await sleep(600);
                checked = node.className.includes('is-checked');
              }
              const ok = [...dlg.querySelectorAll('button')]
                .find(b => b.innerText.replace(/\\s/g, '') === '确定');
              if (!ok) return {error: 'no-ok'};
              ok.click(); await sleep(1500);
              const save = [...document.querySelectorAll('button')]
                .find(b => b.innerText.trim() === '保存' && vis(b));
              if (!save) return {error: 'no-save'};
              save.click();
              for (let i = 0; i < 20; i++) {
                await sleep(500);
                const m = [...document.querySelectorAll('.el-message')]
                  .map(x => x.innerText.trim()).join('|');
                if (m.indexOf('操作成功') >= 0) return {ok: true, checked};
                if (m.indexOf('失败') >= 0) return {error: 'save-failed', msg: m};
              }
              return {ok: true, noMessage: true, checked};
            }
        """, [CARRYOVER_SUBJECT])
        if isinstance(res, dict) and res.get("error"):
            raise RuntimeError(f"标记结转失败: {res}")
        log("本年利润已标记结转并保存")

    # ---------- 科目映射 ----------
    def subject_mapping(self, audit):
        self.open_menu(audit, "数据", "科目映射")
        end = time.time() + 40
        while time.time() < end:
            ready = audit.evaluate("""
                () => {
                  for (const el of document.querySelectorAll('*')) {
                    const vm = el.__vue__;
                    if (vm && vm.$options.name === 'subject-map-table') {
                      return !!(vm.submaplist && vm.submaplist.length >= 0 && vm.projectList && vm.projectList.length);
                    }
                  }
                  return false;
                }
            """)
            if ready:
                break
            self.page.wait_for_timeout(1500)

        for m in MAPPINGS:
            res = audit.evaluate("""
                async ([code, subject, report]) => {
                  const sleep = ms => new Promise(r => setTimeout(r, ms));
                  const vis = e => e && e.getBoundingClientRect().width > 0;
                  // 找到页面组件，检查是否已映射
                  let vm = null;
                  for (const el of document.querySelectorAll('*')) {
                    if (el.__vue__ && el.__vue__.$options.name === 'subject-map-table') {
                      vm = el.__vue__; break;
                    }
                  }
                  if (!vm) return {error: 'no-vm'};
                  const mapped = (vm.submaplist || []).some(s => s.accountName === subject);
                  if (mapped) return {skip: true};

                  // 点击左侧报表项目
                  const li = [...document.querySelectorAll('li.subject-li')]
                    .find(e => e.textContent.trim() === report);
                  if (!li) return {error: 'no-report-item', report};
                  li.click(); await sleep(1500);
                  if (!vm.checkedReportId) return {error: 'report-not-checked'};

                  // 勾选科目行
                  const rows = [...document.querySelectorAll('.el-table__body tr')];
                  let target = null;
                  for (const tr of rows) {
                    const cells = [...tr.querySelectorAll('td .cell')].map(c => c.innerText.trim());
                    if (cells.includes(code) && cells.includes(subject)) { target = tr; break; }
                  }
                  if (!target) return {error: 'no-subject-row', code, subject};
                  const cb = target.querySelector('.el-checkbox');
                  if (!cb) return {error: 'no-row-checkbox'};
                  if (!target.querySelector('.el-checkbox__input.is-checked')) {
                    cb.click(); await sleep(600);
                  }
                  await sleep(600);
                  if (!vm.multipleSelection || vm.multipleSelection.length === 0) {
                    return {error: 'row-not-selected'};
                  }
                  const names = vm.multipleSelection.map(x => x.subjectName || x.subject);
                  if (vm.multipleSelection.length !== 1 || names[0] !== subject) {
                    return {error: 'wrong-selection', names};
                  }

                  const btn = [...document.querySelectorAll('button')]
                    .find(b => b.innerText.trim() === '对应' && vis(b));
                  if (!btn) return {error: 'no-corres-button'};
                  btn.click();
                  for (let i = 0; i < 20; i++) {
                    await sleep(500);
                    const msg = [...document.querySelectorAll('.el-message')]
                      .map(x => x.innerText.trim()).join('|');
                    if (msg.indexOf('已建立对应关系') >= 0) return {ok: true};
                    if (msg.indexOf('失败') >= 0) return {error: 'corres-failed', msg};
                  }
                  return {ok: true, noMessage: true};
                }
            """, [m["subject_code"], m["subject"], m["report"]])
            if isinstance(res, dict) and res.get("error"):
                self.shot("fail_mapping")
                raise RuntimeError(f"科目映射 {m['subject']}->{m['report']} 失败: {res}")
            if res.get("skip"):
                log(f"科目映射 {m['subject']}->{m['report']} 已存在，跳过")
            else:
                log(f"科目映射 {m['subject']}->{m['report']} 完成")

        # 校验最终映射结果
        final = audit.evaluate("""
            (pairs) => {
              for (const el of document.querySelectorAll('*')) {
                const vm = el.__vue__;
                if (vm && vm.$options.name === 'subject-map-table') {
                  const out = {};
                  for (const [code, subject] of pairs) {
                    const hit = (vm.submaplist || []).find(s => s.accountName === subject);
                    out[subject] = hit ? hit.reportName : null;
                  }
                  return out;
                }
              }
              return null;
            }
        """, [[m["subject_code"], m["subject"]] for m in MAPPINGS])
        for m in MAPPINGS:
            got = (final or {}).get(m["subject"])
            if got != m["report"]:
                raise RuntimeError(f"映射校验失败: {m['subject']} -> {got}（期望 {m['report']}）")
        log("科目映射校验通过")

    # ---------- 未审报表 ----------
    def report_frame(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if "reportGeneration" in f.url:
                    try:
                        if f.evaluate("typeof GC !== 'undefined'"):
                            return f
                    except Exception:
                        pass
            self.page.wait_for_timeout(1000)
        raise RuntimeError("未审报表 frame 未加载")

    def unaudited_report(self, audit):
        self.open_menu(audit, "报表", "未审报表")
        f = self.report_frame()
        self.page.wait_for_timeout(3000)

        res = f.evaluate("""
            async ([month]) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const vm = (() => {
                for (const el of document.querySelectorAll('*')) {
                  const v = el.__vue__;
                  if (v && v.$options.name === 'index' && v.getReport && v.verify) return v;
                }
                return null;
              })();
              if (!vm) return {error: 'no-vm'};
              vm.dialogVisible = false;
              if (vm.month !== month) {
                vm.month = month;
                vm.monthChange();
                await sleep(2000);
                for (let i = 0; i < 60 && vm.loading; i++) await sleep(500);
                await sleep(1000);
              }
              vm.verifyObj = {};
              vm.verify();
              for (let i = 0; i < 60; i++) {
                await sleep(500);
                if (vm.verifyObj && vm.verifyObj.finalVerifyLogic) break;
              }
              const v = vm.verifyObj || {};
              if (v.finalVerifyLogic !== 'OK！' || v.openingVerifyLogic !== 'OK！') {
                return {error: 'not-balanced', verify: v};
              }
              vm.dialogVisible = false;
              vm.save();
              for (let i = 0; i < 30; i++) {
                await sleep(500);
                const m = [...document.querySelectorAll('.el-message')]
                  .map(x => x.innerText.trim()).join('|');
                if (m.indexOf('保存成功') >= 0) return {ok: true, verify: v};
                if (m.indexOf('失败') >= 0) return {error: 'save-failed', msg: m};
              }
              return {ok: true, verify: v, noMessage: true};
            }
        """, [REPORT_MONTH])
        if isinstance(res, dict) and res.get("error"):
            self.shot("fail_report")
            raise RuntimeError(f"未审报表校验失败: {res}")
        v = res.get("verify") or {}
        log(f"未审报表平衡：期末 {v.get('finalTotalAsset')} / 期初 {v.get('openingTotalAsset')}，已保存")

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
        self.shot("t211_submitted")
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

        bot.subject_info_check(audit)
        bot.voucher_balance_check(audit)
        bot._diff_check(audit, "核算项目与科目校验", [6, 9, 12, 15])
        bot._diff_check(audit, "借贷发生额校验", [5, 8])
        bot.carryover(audit)
        bot.subject_mapping(audit)
        bot.unaudited_report(audit)

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
