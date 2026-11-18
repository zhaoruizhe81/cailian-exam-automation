# cailian-exam-automation

用 Playwright（Python sync API）驱动「财连」实训/竞赛平台，把三套试卷里的任务点逐个做完并提交。纯脚本仓库：没有服务端、没有构建产物，脚本本身就是交付物。

> ⚠️ **仅供个人学习与课堂练习复现**。账号、题库、成绩均归平台与学校所有；本项目不含任何凭证，跑起来需要你自己的登录态。详见文末「边界与免责」。

## 它解决什么

平台的实操题不在 DOM 里，而在四五个跨域 iframe 里：财天下、票据采集、SpreadJS 在线表格、审计数据上传系统、绩效管理。点一遍要几十步，其中一半是 Element UI 的坑（下拉要 `mousedown` 再点 `li`、勾选必须点 `.el-checkbox`、日期框是 readonly）。本项目把这些操作固化成可重跑的脚本，并把踩过的坑写进文档。

## 目录结构

```
.
├── CLAUDE.md                  # 给 AI 编码助手的项目须知（登录模型、iframe 表、踩坑清单）
├── automation/
│   ├── README.md              # ★ 权威操作手册：逐套逐任务点记录做法与坑
│   ├── cailian3.py            # 第三套公共库（登录、导航、财天下侧栏、票据采集、在线表格）
│   ├── taskNN.py              # 第一套：每任务一个自包含脚本
│   ├── taskNNb.py             # 第二套：同构，数据外置为 taskNNb_*.json
│   ├── taskNc.py              # 第三套：只放数据，逻辑复用 cailian3
│   ├── login_sx.py            # 人工过验证码，把 sx Authorization 写进 sx_token.txt
│   ├── open_exam.py           # 登录态注入 + 打开试卷（其余脚本内联同一套逻辑）
│   ├── submit_paper.py        # 交卷（不可撤销）
│   ├── data3/                 # 第三套票据素材（平台练习用的虚构凭证）
│   └── out/                   # 运行截图，仓库只保留 4 张示例
└── LICENSE
```

34 个 Python 文件，约 1 万行，零第三方依赖（除 Playwright）。

## 环境

- Python 3
- `pip install playwright`（没有 requirements.txt，就这一个依赖）
- 本机安装 Chrome（脚本用 `channel="chrome"`，不用下载 Chromium）

## 快速开始

```bash
cd automation

# 首次：人工过验证码，脚本会把 Authorization 落盘到 sx_token.txt
python3 task11.py --login-sx

# 第一套任务 1.1（唯一走 studentDetail 旧入口的脚本）
python3 task11.py --user <cp账号> \
  --student-url "https://cp.cailian.net/#/studentDetail?q=..." --dry-run

# 其余脚本统一走 examHome
python3 task12.py --user <cp账号> --exam-url "https://cp.cailian.net/#/examHome?q=..." --dry-run

# 绩效管理可按阶段重跑
python3 task4.py --user <cp账号> --exam-url "..." --stage all|plan|score|eval|submit
```

- `--dry-run`：做到保存为止，不点「提交结果」
- `--headless`：可用，但个别弹窗/加载更慢，排查时别用
- 语法自检（没有 pytest，这是唯一的静态校验）：`python3 -m py_compile cailian3.py task*.py`

## 登录模型

练习计划**只能从 sx 平台进入**。直接用 cp 账号密码登录拿到的 token 会报「当前计划已经失效」，所以所有脚本统一做登录态注入：

1. 打开 cp，把 sx token 写进 `localStorage.username/jsToken/pattern_lx`，并设置 `sessionStorage.token/queryData`（含 `professionId:38`、`provinceId:"10"`、`tag:"ycsrhjncp"`）
2. 调 `POST /api-match-practise/practise/js/playerDetail` 取 `playerInfo`，写入 `localStorage.playerInfo/resultVal/matchPlanId` 与 `sessionStorage.stationId/planIdShow`
3. 再打开 `--exam-url`

`exam-url` 的 `q=` 是 `base64(JSON)`，含 `planId/orgId/mainVersion/subVersion/userId`，脚本从里面解出请求体。

页面是外壳 SPA，真正要操作的内容在 iframe 里：

| iframe 域名 | 用途 |
|---|---|
| `ctxdslxpro.cailian.net` | 财天下（凭证、票据制单、报表） |
| `ptxinvoicedslxpro.cailian.net` | 票据采集的真实内容（同名页面在 `ctxdslxpro` 里只是菜单外壳） |
| `onlineexcel...` | SpreadJS 在线表格 / 底稿 |
| `answer.cailian.net` | 审计数据上传系统 |
| PMS 域名 | 绩效管理 |

**提交单位是任务点**：每个任务点都要单独点「提交结果」→「确定」，否则交卷时会提示少做一题；提交成功后按钮变成「再次提交」。

## 三套脚本的关系

| 代 | 文件 | 结构 |
|---|---|---|
| 第一套 | `taskNN.py` | 每个任务一个自包含脚本，重复同一套登录注入模板；数据放 `taskNN_*.json` |
| 第二套 | `taskNNb.py` | 与第一套同构，数据外置为 `taskNNb_*.json`；`task211b.py` 是薄封装 |
| 第三套 | `cailian3.py` + `taskNc.py` | `cailian3.py` 是公共库，`taskNc.py` 只放数据（`TITLE/DATE/ENTRIES/CELLS`） |

新增脚本约定：CLI 保持一致（`--user/--exam-url/--sx-token/--profile/--headless/--dry-run`，按需加 `--data/--image/--stage`）；表格类答案用**显式 0-based 行列坐标**的 JSON（`[[row, col, value], ...]`），不按公式推算行号；第三套优先复用 `cailian3.C3`，不要复制粘贴。

## 几个绕不开的实现细节

- `page.frames()` 是方法不是属性；票据采集有**两个 URL 都含 `invoice-collect` 的 frame**，必须选 `ptxinvoicedslxpro`
- 银行回单在本环境用「票据制单」必失败（`缺少必要参数` / `业务类型不存在`），第三套改用「新增凭证」手工制单 + 附件管理器上传截图
- SpreadJS 直接改值不会激活保存按钮，要调组件 `handleSaveClick()` / `answerSave()`
- 保存/审核确认框有 `.el-message-box` 和自定义 `.batch-message-dialog` 两种，按文本取 `.el-button--primary`

完整清单（逐任务点的做法、失败堆栈、绕过方式）在 [`automation/README.md`](automation/README.md)。

## 仓库里没有什么

`.gitignore` 主动挡掉了几类东西，这也是它值得单独说明的原因：

- `automation/profile/`：持久化浏览器 profile，含 Cookie 与登录态
- `automation/sx_token.txt`：sx 平台 Authorization
- `auth-exam*.json`：Playwright storageState 快照，含 `jsToken` 与 `playerInfo`
- `.playwright-cli/`、`*.yml`：人工排查时的页面快照
- `automation/out/` 下除 4 张示例外的所有截图

## 边界与免责

本项目是**操作流程的记录**，不是破解工具：它不复现验证码、不绕过任何鉴权，所有请求都带着使用者自己通过正规登录获得的 token。

请自行确认所在平台的服务条款；用它在一个你不拥有的账号上刷题，后果自负。题库内容、企业数据、票据素材均为平台提供的练习数据（其中公司名与银行账号为虚构），版权归原平台所有。
