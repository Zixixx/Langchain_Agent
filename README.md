# Langchain_Agent

这是一个基于 LangChain 和 DeepSeek API 的混合架构 AI Agent。

项目支持工具调用、文件操作、Python 沙箱、pybind11 C++ 算法、RAG 检索、SQL查询、本地记忆窗口和依赖安装申请。

## 目录结构

```text
Langchain_agent/
  agent/                #工具函数
  data/                 #数据目录
  input/                #输入目录
  output/               #输出目录
  wheels/               #wheels目录
  main.py               #主程序入口
  setup.py              #安装脚本
  pyproject.toml        #项目说明
  requirements.txt      #依赖清单
  example.env           #环境配置
```

## 快速开始

### 安装依赖与项目

推荐安装Anaconda/Miniconda

```bash
conda create -n agent python=3.12
conda activate agent
```
#### 通过 wheel 安装

wheels 目录中有六种已经构建好的 wheel，推荐直接安装对应平台的 wheel，注意此方法要求 python 版本必须为3.12，且操作系统与 cpu 架构必须与 wheel 文件一致。

Windows x86_64：

```powershell
python -m pip install .\wheels\hybrid_ai_agent-0.1.0-cp312-cp312-win_amd64.whl
```

Windows arm64：

```powershell
python -m pip install .\wheels\hybrid_ai_agent-0.1.0-cp312-cp312-win_arm64.whl
```

Linux x86_64：

```bash
python -m pip install wheels/hybrid_ai_agent-0.1.0-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl
```

Linux arm64：

```bash
python -m pip install wheels/hybrid_ai_agent-0.1.0-cp312-cp312-manylinux_2_24_aarch64.manylinux_2_28_aarch64.whl
```

Mac x86_64：

```bash
python -m pip install wheels/hybrid_ai_agent-0.1.0-cp312-cp312-macosx_10_13_x86_64.whl
```

Mac arm64：

```bash
python -m pip install wheels/hybrid_ai_agent-0.1.0-cp312-cp312-macosx_11_0_arm64.whl
```

#### 通过 setup.py 安装

通过 setup.py 安装可以支持多个 python 版本，且可以自行修改代码并重新安装项目。

```bash
pip install -r requirements.txt
pip install -e .
```

### 编辑 `example.env`

请先将该文件重命名为`.env`。

#### 配置 `API_KEY` 与 `MAX_INPUT_TOKENS`

修改 `API_KEY` 为你的服务模型的 API Key。

当前的 `BASE_URL` 和 `MODEL` 默认指向 DeepSeek，也可以换成其他 OpenAI 兼容的模型。

`MAX_INPUT_TOKENS` 用于限制单次调用模型时的最大输入 tokens 数，默认值 128000，为空时不做限制。

```env
API_KEY=sk-your-key
BASE_URL=https://api.deepseek.com
MODEL=deepseek-chat
MAX_INPUT_TOKENS=128000
```

#### 配置 PYTHON_SANDBOX_TIMEOUT

`PYTHON_SANDBOX_TIMEOUT` 用于限制 python 安全沙箱运行的运行时长（单位：秒），默认值 30，为空时不做限制。

```env
PYTHON_SANDBOX_TIMEOUT=30
```

#### 配置 EMBEDDING_DEVICE 与 EMBEDDING_MODEL

项目的 RAG 功能需要用到 sentence-transformers 的 Embedding 模型。

`EMBEDDING_DEVICE` 用于指定项目采用 cpu 或 gpu，默认值为 cpu。

```env
EMBEDDING_DEVICE=cpu
```

`EMBEDDING_MODEL` 默认使用 sentence-transformers/all-MiniLM-L6-v2 ，运行相关命令会自动从 HuggingFace 库下载模型。

如果你已经有本地的模型，或需要指定使用 HuggingFace 库中的某个模型，可填写 `EMBEDDING_MODEL`。

```env
EMBEDDING_MODEL=your-model-path|HuggingFace-model-name
```

#### 配置 LIBREOFFICE_PATH

项目需要使用 LibreOffice 读取老式 Office 文件（`.doc`、`.ppt`、`.xls`），如果你已经安装，可以配置 LIBREOFFICE_PATH。

```env
LIBREOFFICE_PATH=your-libreoffice-path
```

也可以在主菜单让项目自动检测或安装 LibreOffice：

```text
agent-cli: libreoffice-check
agent-cli: libreoffice-install
```

`libreoffice-check` 只检查 `.env` 中的 `LIBREOFFICE_PATH` 是否有效。

如果无效或为空，会尝试检测系统中已经安装的 LibreOffice，检测到后写入 `.env`，但不会安装。

`libreoffice-install` 会先检测系统中是否已经存在 LibreOffice。

如果存在，直接把检测到的路径写入 `.env` 的 `LIBREOFFICE_PATH`。

如果不存在，会尝试使用系统包管理器联网安装。

Windows 可能弹出 UAC 权限确认；Linux / Mac 可能需要输入用户密码。安装完成后会自动检测 LibreOffice 路径并写入 `.env` 的 `LIBREOFFICE_PATH`。

### 启动主菜单

```bash
python main.py
```

## 命令列表

所有支持传入 `[id|number]` 的命令中，若一个数字既是 <number> 也是 <id> ，会优先判断为<number>。

### `chat`

启动 DeepSeek 对话流程，先进入窗口选择页面，选择或新建记忆窗口后进入任务窗口，再输入任务。

```text
agent-cli: chat
memory-select: use 1
task[window-id]: 介绍一下你是谁
```

窗口选择界面命令：

```text
memory-select: new [session_id]              新建窗口并进入；不填 id 时自动生成
memory-select: use <session_id|number>       使用已有窗口
memory-select: delete <session_id|number>    删除旧窗口
memory-select: delete -a                     删除所有对话窗口
memory-select: exit                          返回主菜单
memory-select: quit                          返回主菜单
```

返回规则：

- `task[...]` 输入 `exit` 或 `quit`：返回 `memory-select`
- `memory-select` 输入 `exit` 或 `quit`：返回 `agent-cli`
- `agent-cli` 输入 `exit` 或 `quit`：退出程序

### `rag-new [rag_id]`

新建一个 RAG 库。不填 `rag_id` 时会自动生成 id。

```text
agent-cli: rag-new
agent-cli: rag-new paper
```

### `rag-list [rag_id|number]` / `rag-list -a`

列出 RAG 库统计信息。传入 `[rag_id|number]` 时只列出该库的统计信息，`-a` 列出所有库的统计信息；

```text
agent-cli: rag-list paper
agent-cli: rag-list 1
agent-cli: rag-list -a
```

### `rag-show <rag_id|number>` / `rag-show -a`

展示 RAG 文档具体信息。传入 `[rag_id|number]` 时只展示该库中的文档，`-a` 展示所有库中的文档。


```text
agent-cli: rag-show paper
agent-cli: rag-show 1
agent-cli: rag-show -a
```

### `rag-add <file_path|dir> <rag_id|number> [replace|append|fail]` / `rag-add -a <file_path|dir> [replace|append|fail]`

添加文档到指定 RAG 库。若 `<rag_id|number>` 不存在，会自动生成一个 id 并创建一个新 RAG 库。

使用 `-a` 时会添加到所有已经存在的 RAG 库中，如果没有任何 RAG 库，只会在屏幕输出提示。

`path` 可以是单个文件，也可以是目录；如果是目录，会递归导入支持的文件。

导入判断规则：

- 非二进制文件会按普通文本导入，并会尝试 UTF-8、GB18030、GBK、CP936、Big5、Shift-JIS、Latin-1 等常见编码。
- PDF：`.pdf`，通过 `pypdf` 提取文本层；扫描版 PDF 如果没有可提取文本会报错。
- Office：`.docx`、`.pptx`、`.xlsx`、`.doc`、`.ppt`、`.xls`。老式 Office 只支持通过 LibreOffice 读取；如果没有安装或配置 LibreOffice，请运行 `libreoffice-install`，或先转换为 `.docx/.pptx/.xlsx`。

目录导入会跳过无法按文本处理的二进制文件，避免把压缩包、图片、动态库等误当普通文本读取。

某个文件读取失败时会记录失败原因并继续导入后续文件。

RAG 的 `source` 取文件名并保留扩展名，不包含目录路径。例如 `<example/example.md>` 的 source 是 `example.md`。

[replace|append|fail]可以不填，不填将默认使用 `replace`。

- `replace`：如果同一个 source 已存在，先删除旧内容再重新导入。
- `append`：如果 source 已存在，将新内容追加到已有 source 后面；source 不存在时正常新增。
- `fail`：如果 source 已存在就记录该文件失败，目录导入会继续处理后续文件。

```text
agent-cli: rag-add <你要导入的rag文档> paper
agent-cli: rag-add <你要导入的rag文档目录> paper
agent-cli: rag-add <你要导入的rag文档目录> paper append
agent-cli: rag-add -a <你要导入的rag文档目录> replace
```

### `rag-remove <source> [rag_id|number]` / `rag-remove -a [rag_id|number]`

`rag-remove <source> [rag_id|number]` 按 source 删除 RAG 文档但保留 RAG 库本身，传入 `rag_id|number` 时只删除该库中的 source；不传时删除所有库中的同名 source。

`rag-remove -a <rag_id|number>` 清空某个库，`rag-remove -a` 清空所有库中的文档。

```text
agent-cli: rag-remove example.md paper
agent-cli: rag-remove example.md
agent-cli: rag-remove -a paper
agent-cli: rag-remove -a
```

### `rag-delete <source> [rag_id|number]` / `rag-delete -a [rag_id|number]`

`rag-delete <source> [rag_id|number]` 功能类似 `rag-remove <source> [rag_id|number]`，但如果删除某个 source 后 RAG 库为空，会同时删除这个空库。

`rag-delete -a [rag_id|number]` 删除某个库，`rag-delete -a` 删除所有库。

```text
agent-cli: rag-delete example.md paper
agent-cli: rag-delete example.md
agent-cli: rag-delete -a paper
agent-cli: rag-delete -a
```

### `rag-search <query> [rag_id|number]`

检索 RAG 知识库。不输入库 id 时，会依次搜索所有 RAG 库。

```text
agent-cli: rag-search C++ 工具有哪些算法？
agent-cli: rag-search C++ 工具有哪些算法？ paper
```

当前 Agent 可自主调用的 C++ 工具有：

- `cpp_sort`：排序数字数组。
- `cpp_binary_search`：在升序数字数组中查找目标值。
- `cpp_unique`：对数字数组或字符串数组去重。
- `cpp_statistics`：返回 count、sum、average、min、max、median、mode、variance、stddev、q1、q3 等。
- `cpp_prefix_sum`：计算前缀和、差分数组或同时返回二者。
- `cpp_matrix`：执行矩阵转置、矩阵乘法或增广矩阵法求逆。
- `cpp_topk`：选出最大或最小的 K 个数字。
- `cpp_string_search`：使用 KMP 查找字符串模式出现位置。
- `cpp_set_operations`：执行并集、交集、差集、对称差集。

### `db-list [table|number]` / `db-list -a`

列出 `data/db/db.sqlite3` 中业务表结构统计信息。传入 `[table|number]` 时只列出一个表的结构， `-a` 列出全部表结构。

```text
agent-cli: db-list sample_sales
agent-cli: db-list 1
agent-cli: db-list -a
```

### `db-show <table|number>` / `db-show -a`

展示表内容。传入 `[table|number]` 时展示一个表的全部行；`-a` 展示所有表的全部行。

```text
agent-cli: db-show sample_sales.csv
agent-cli: db-show 1
agent-cli: db-show -a
```

### `db-add <table_file|dir> [replace|append|fail]`

导入 CSV、XLSX 或 XLS 到 `data/db/db.sqlite3`。

`path` 可以是单个 `.csv/.xlsx/.xls` 文件，也可以是目录；如果是目录，会递归导入其中所有支持的表格文件。

表名 `table` 完全取自文件名和扩展名，例如 `example.xlsx` 会生成表名 `example.xlsx`。

[replace|append|fail]可以不填，不填将默认使用 `replace`。

- `replace`：如果同一个 table 已存在，先删除旧内容再重新导入。
- `append`：如果 table 已存在，将新数据追加到已有 table；table 不存在时正常新增。
- `fail`：如果 table 已存在就记录该文件失败，目录导入会继续处理后续文件。

```text
agent-cli: db-add <你要导入的表格>
agent-cli: db-add <你要导入的表格目录>
agent-cli: db-add <你要导入的表格目录> append
```

### `db-delete <table|number>` / `db-delete -a`

按 `<table|number>` 删除 `data/db/db.sqlite3` 中的表；使用 `-a` 删除全部业务表。

```text
agent-cli: db-delete sample_sales
agent-cli: db-delete 1
agent-cli: db-delete -a
```

### `db-query <sql>`

在 `data/db/db.sqlite3` 中执行只读 SQL。

```text
agent-cli: db-query SELECT region, SUM(units * unit_price) AS revenue FROM sample_sales GROUP BY region
```

### `deps-list [window_id|number]` / `deps-list -a`

查看依赖申请统计信息。依赖申请绑定记忆窗口，即使某个窗口没有依赖，也会作为空列表显示。

主菜单中：

```text
agent-cli: deps-list <window_id|number>
agent-cli: deps-list -a
```

`deps-list <window_id|number>` 只查看某个窗口的统计信息，`deps-list -a` 查看所有窗口的统计信息。

对话窗口中：

```text
task[example]: deps-list
```

对话窗口里的 `deps-list` 只查看当前窗口的依赖统计。

### `deps-show [window_id|number]` / `deps-show -a`

展示依赖申请具体清单，包括 module 名、pip package 名和状态。

主菜单中：

```text
agent-cli: deps-show <window_id|number>
agent-cli: deps-show -a
```

`deps-show <window_id|number>` 展示某个窗口的依赖清单，`deps-show -a` 展示所有窗口的依赖清单。

对话窗口中：

```text
task[example]: deps-show
```

对话窗口里的 `deps-show` 只展示当前窗口的依赖清单。它输出的序号可用于窗口内的 `deps-install <number>` 或 `deps-ignore <number>`。

例如：

```text
Dependency requests for memory window: example
1. module=matplotlib | package=matplotlib
2. module=sklearn | package=scikit-learn
```

此时在 `task[example]` 中输入 `deps-install 1` 表示安装 `matplotlib`。

### `deps-install <module|package>` / `deps-install -a [window_id|number]`

安装依赖申请。依赖来自 Python 沙箱或 Agent 工具，DeepSeek 不能直接安装包，只能记录申请，最终由用户通过该命令安装。

主菜单中安装单个依赖：

```text
agent-cli: deps-install <module|package>
```

主菜单里的 `<module|package>` 使用模块名或 pip 包名，不使用依赖条目序号，因为主菜单可能同时展示多个窗口的列表。

主菜单中安装全部依赖：

```text
agent-cli: deps-install -a <window_id|number>
agent-cli: deps-install -a
```

`deps-install -a <window_id|number>` 安装某个窗口中的全部依赖；`deps-install -a` 安装所有窗口中的全部依赖。

安装成功后，同名模块的 pending 申请会从所有窗口中删除。

对话窗口中：

```text
task[example]: deps-install <module|package|number>
task[example]: deps-install -a
```

对话窗口里的 `<number>` 指当前窗口 `deps-show` 输出中的依赖条目序号。

### `deps-ignore <module|package> [window_id|number]` / `deps-ignore -a [window_id|number]`

忽略依赖申请。忽略只会删除依赖申请记录，不会卸载已经安装的 Python 包。

主菜单中忽略单个依赖：

```text
agent-cli: deps-ignore <module|package>
agent-cli: deps-ignore <module|package> <window_id|number>
```

`deps-ignore <module|package>` 会忽略所有窗口中的同名依赖申请；`deps-ignore <module|package> <window_id|number>` 只忽略某个窗口中的同名依赖申请。

主菜单中忽略全部依赖：

```text
agent-cli: deps-ignore -a <window_id|number>
agent-cli: deps-ignore -a
```

`deps-ignore -a <window_id|number>` 忽略某个窗口中的全部依赖申请；`deps-ignore -a` 忽略所有窗口中的全部依赖申请。

对话窗口中：

```text
task[example]: deps-ignore <module|package|number>
task[example]: deps-ignore -a
```

对话窗口里的 `deps-ignore <module|package|number>` 只作用于当前窗口；`deps-ignore -a` 忽略当前窗口中的全部依赖申请。

### `memory-list [session_id|number]` / `memory-list -a`

列出记忆窗口。传入 `[session_id|number]` 时只列出一个窗口，`-a` 列出全部窗口。

```text
agent-cli: memory-list example
agent-cli: memory-list 1
agent-cli: memory-list -a
```

### `memory-show <session_id|number>` / `memory-show -a`

展示窗口对话记忆。传入 `[session_id|number]` 时查看指定窗口的记忆；`-a` 展示所有窗口的记忆。

```text
agent-cli: memory-show example
agent-cli: memory-show 1
agent-cli: memory-show -a
```

### `memory-new [session_id]`

新建记忆窗口。手动指定的 `session_id` 必须唯一。

```text
agent-cli: memory-new
agent-cli: memory-new example
```

### `memory-clear <session_id|number>` / `memory-clear -a`

按 `<session_id|number>` 清空指定窗口的对话记忆和依赖申请，保留窗口本身；使用 `-a` 清空所有窗口的对话记忆和依赖申请。

```text
agent-cli: memory-clear example
agent-cli: memory-clear 1
agent-cli: memory-clear -a
```

### `memory-delete <session_id|number>` / `memory-delete -a`

按 `<session_id|number>` 删除窗口、该窗口对话记忆和该窗口依赖申请；使用 `-a` 删除所有窗口及相关记录。

```text
agent-cli: memory-delete example
agent-cli: memory-delete 1
agent-cli: memory-delete -a
```

### `libreoffice-check`

该命令可以在主菜单和对话窗口使用，只检查 LibreOffice 路径，不会安装。
如果 `.env` 中的 `LIBREOFFICE_PATH` 有效，会刷新当前进程配置并清理 Agent/RAG 缓存。
如果路径为空或无效，会尝试检测系统中已有的 LibreOffice；检测到后写入 `.env` 并清理缓存。

### `libreoffice-install`

该命令可以在主菜单和对话窗口使用，它会检测系统中是否已经存在 LibreOffice。
如果存在，直接把检测到的路径写入 `.env` 的 `LIBREOFFICE_PATH`。
如果不存在，会尝试使用系统包管理器联网安装。

### 'help/?'

打印 command_help 到终端，主菜单与对话窗口的 command_help 不同。

### 'exit/quit'

返回上一级，若在主菜单输入则退出程序。

## agent 权限说明

### 执行权限

只允许执行 `input/` 和 `output/` 目录中的 Python 脚本。

脚本执行时会新建临时 `temp/` 运行目录，其中包含 `input/`、`output/` 的副本和空的 `result/` 目录。

运行结束后会将 `result/` 目录中的文件合并回项目的 `output/` 目录。

### 读取权限

文件工具与 Python 沙箱只允许读取或复制 `input/` 和 `output/` 目录中的文件，此外还可以查询本地 rag 库和 sql 库。

### 写入权限

文件工具只允许在 `output/` 目录中新建、追加、修改、粘贴、删除、重命名文件。

Python 沙箱内可以写临时 `input/` 和 `output/` 副本，但这些修改不会回写。

沙箱最终产物必须保存到 `result/`，运行结束后 `result/` 会自动合并到真实 `output/`，重名时追加 `_new`。

## 项目的局限性

- 项目并没有打包为可执行文件，安装步骤对于不了解 python 的用户可能稍微复杂。
- 项目需要外部依赖 libreoffice 来读取老式 office 文件, 暂时没有找到更好的替代方案。
- 项目的 Python 安全沙箱仅采用子程序 + 超时机制 + 黑名单进行隔离，并非专业级别的的安全隔离。
- 项目没有提供访问互联网的工具，agent 无法直接回答实时问题。
- 项目更适合个人日常学习与使用，不能作为生产级别的项目。
