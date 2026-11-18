# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个纯脚本仓库：用 Playwright（Python sync API）驱动「财连」实训/竞赛平台
（cp.cailian.net + 财天下/票据采集/在线表格等子应用），自动完成三套试卷的任务点并逐个提交。
没有服务端、没有构建产物，**脚本本身就是交付物**。权威操作手册是
`automation/README.md`（按套分节，逐个任务点记录做法和踩过的坑），改动前先读对应章节。

## 环境

- Python 3 + `playwright`（sync API）+ 本机 Chrome（`channel="chrome"`）
- 没有 `requirements.txt`，也没有测试；依赖需本机自行安装
- `automation/profile/` 是持久化浏览器 profile，`automation/sx_token.txt` 保存 sx 平台
  Authorization —— 两者都是本机会话凭证，不要外传
- 根目录 `auth-exam*.json` 与 `.playwright-cli/`、`*.yml` 是当时人工排查留下的
  会话/快照，不是运行依赖

## 常用命令

所有脚本都在 `automation/` 下运行：

```bash
cd automation

# 第一套任务 1.1（唯一用 --student-url 的脚本）
python3 task11.py --user 1111111111111 \
  --student-url "https://cp.cailian.net/#/studentDetail?q=..." --dry-run

# 其余脚本统一用 --exam-url
python3 task12.py --user 1111111111111 --exam-url "https://cp.cailian.net/#/examHome?q=..." --dry-run

# 绩效管理可按阶段重跑
python3 task4.py --user 1111111111111 --exam-url "..." --stage all|plan|score|eval|submit

# 第三套（公共库 + 数据脚本）
python3 task5c.py --user 1111111111111 --exam-url "..."

# 语法检查（没有 pytest，这是唯一的静态校验）
python3 -m py_compile cailian3.py task*.py
```

- `--dry-run`：做到保存为止，不点「提交结果」
- `--headless`：可用但个别弹窗/加载更慢，排查时不要用
- 首次使用或 token 过期：`python3 task11.py --login-sx ...` 打开 sx 登录页，人工过验证码，
  脚本会把 Authorization 写进 `sx_token.txt`；其余脚本直接读这个文件

## 登录模型（所有脚本的共同前提）

练习计划**只能从 sx 平台进入**。直接用 cp 账号密码登录得到 token 会报「当前计划已经失效」，
脚本因此统一做登录态注入：

1. 打开 cp，把 sx token 写进 `localStorage.username/jsToken/pattern_lx`，
   并设置 `sessionStorage.token/queryData`（含 `professionId:38`、`provinceId:"10"`、`tag:"ycsrhjncp"`）
2. 调 `POST /api-match-practise/practise/js/playerDetail` 拿 `playerInfo`，
   写入 `localStorage.playerInfo/resultVal/matchPlanId` 与 `sessionStorage.stationId/planIdShow`
3. 再打开 `--exam-url`

`exam-url` 的 `q=` 是 base64(JSON)，含 `planId/orgId/mainVersion/subVersion/userId`，
脚本从里面解出请求体。第一套的 `task11.py` 走的是旧入口（`planHome` + `studentDetail`），
其余脚本统一走 `examHome`。

页面结构：cp 是外壳 SPA；任务页底部「业务处理」打开分屏，真正要操作的内容在 iframe 里：

| iframe 域名 | 用途 |
|---|---|
| `ctxdslxpro.cailian.net` | 财天下（凭证、票据制单、报表） |
| `ptxinvoicedslxpro.cailian.net` | 票据采集的真实内容（`ctxdslxpro` 里同名页面只是菜单外壳） |
| `onlineexcel...` | SpreadJS 在线表格 / 底稿 |
| `answer.cailian.net` | 审计数据上传系统 |
| PMS 域名 | 绩效管理 |

**提交单位是任务点**：每个任务点都要单独点「提交结果」→「确定」，否则交卷时会提示少做一题；
提交成功后按钮变成「再次提交」。

## 代码组织（三代脚本）

| 代 | 文件 | 结构 |
|---|---|---|
| 第一套 | `taskNN.py` | 每个任务一个自包含脚本，重复同一套登录注入模板；数据放 `taskNN_*.json` |
| 第二套 | `taskNNb.py` | 与第一套同构，数据外置为 `taskNNb_*.json`；`task211b.py` 是薄封装，直接复用 `task211.py` |
| 第三套 | `cailian3.py` + `taskNc.py` | `cailian3.py` 是公共库（登录、任务导航、财天下侧栏、票据采集、新增凭证、在线表格），`task4c.py`~`task11c.py` 只放数据（`TITLE/DATE/ENTRIES/CELLS`） |

新增脚本的约定：

- CLI 保持一致：`--user`、`--exam-url`、`--sx-token`、`--profile`、`--headless`、`--dry-run`；
  按需加 `--data/--image/--stage/--skip-adjust`
- 截图写 `automation/out/`，失败截图命名 `fail_*.png`；第三套票据素材放 `automation/data3/`
- 表格类答案用**显式 0-based 行列坐标**的 JSON（如 `[[row, col, value], ...]`），不要按公式推算行号，
  模板换行时只改坐标
- 第三套优先复用 `cailian3.C3`，不要复制粘贴它的方法

## 关键实现细节（最容易踩的）

- `page.frames()` 是方法不是属性；票据采集有**两个 URL 都含 `invoice-collect` 的 frame**，
  必须选 `ptxinvoicedslxpro`
- Element UI：下拉要 `mousedown+mouseup+click` 再点 `li`；勾选必须点 `.el-checkbox`，
  直接 `div.click()` 不生效；日期输入框是 readonly，要点开 `.el-picker-panel` 再点 `td.available`
- 「教学票据采集」弹窗的确定按钮文本是 `确 定`（中间有空格）
- 银行回单在本环境用「票据制单」必失败（`缺少必要参数` / `业务类型不存在`），
  第三套改用「新增凭证」手工制单 + 附件管理器（`.z-upload__input`）上传截图
- SpreadJS：`GC.Spread.Sheets.findControl(...)` + `setValue`；直接改值不会激活保存按钮，
  需要调组件 `handleSaveClick()` / `answerSave()`（第一套任务 2.3、任务 3）
- 保存/审核确认框有 `.el-message-box` 和自定义 `.batch-message-dialog` 两种，按文本取
  `.el-button--primary`

## 交卷后查分

官方成绩在 `scoreFlag=1` 前不会发布（`playerDto.score` / `actualScore` 为 null），
但实操题评分可以免登录读取：

```text
POST https://zledusxapi.cailian.net/api-score/noAuth/race-score-log
body: {"matchPattern":"1","teamId":<teamId>,"matchPlanId":<planId>}
teamId = <planId 后四位> + <playerId> + <subVersionId>
```

返回 `data.content`（JSON 字符串），每题有 `questionResult`（得分）和 `questionScore`（满分）；
非实操题只有 `questionTips:["本试题不是实操题. <qid>"]`。
题目列表与满分：`POST /api-match-practise/practise/js/task/status`（需要
`questionIdList`，头部用 `authorization: bearer <cp localStorage.jsToken>`、
`x-user-header: <账号>`、`prodtag: ycsrhjncp`）。

## 已完成的试卷

三套均已全部提交（第一套、第二套、第三套 planId `5000508920`）。第三套得分明细和失分原因、
各套的逐任务脚本清单，都写在 `automation/README.md` 与项目记忆中，不要在本文重复维护。
