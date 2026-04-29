# Langchain_Agent

这是一个基于 LangChain 和 DeepSeek API 的混合架构 AI Agent。项目支持工具调用、Python 沙箱、文件操作、pybind11 C++ 算法、RAG 检索、Text-to-SQL、本地记忆窗口和依赖安装申请。

## 目录结构

```text
Langchain_agent/
  agent/            #工具函数
  data/             #数据库
  output/           #输出目录
  main.py           #主程序入口
  setup.py          #安装脚本
  pyproject.toml    #项目说明
  requirements.txt  #依赖清单
  .env              #环境配置
```

## 快速开始

### 安装依赖与项目

推荐安装Anaconda/Miniconda

```bash
conda create -n agent python=3.12
conda activate agent
pip install -r requirements.txt
pip install -e .
```

### 编辑 `.env`：

```env
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_MODEL=deepseek-chat
```

### 启动主菜单：

```bash
python main.py
```

## 命令列表

### `chat`

启动 DeepSeek 对话流程，先进入窗口选择页面，选择或新建记忆窗口后进入任务窗口，再输入任务。

```text
agent-cli: chat
memory-select: use 1
task[window-id]: 介绍一下你是谁
```

命令行模式：

```powershell
python main.py chat --session-id project-a
```

返回规则：

- `task[...]` 输入 `exit` 或 `quit`：返回 `memory-select`
- `memory-select` 输入 `exit` 或 `quit`：返回 `agent-cli`
- `agent-cli` 输入 `exit` 或 `quit`：退出程序

### `rag-list`

列出已经加入 RAG 知识库的文档。输出中的 `source` 可以直接用于 `rag-delete <source>`。

```text
agent-cli: rag-list
```

### `rag-add <file_path|dir> [replace|append|fail]`

添加文档到 RAG 知识库。
`path` 可以是单个 UTF-8 文本文件，也可以是目录；如果是目录，会递归导入其中所有可按 UTF-8 读取的文本文件。
RAG 的 `source` 取文件名并保留扩展名，不包含目录路径。例如 `<你要导入的rag文档>` 的 source 是该文件的完整文件名。

默认使用 `replace`。

- `replace`：如果同一个 source 已存在，先删除旧内容再重新导入。
- `append`：只导入新 source，跳过已存在的 source。
- `fail`：如果 source 已存在就报错。

```text
agent-cli: rag-add <你要导入的rag文档>
agent-cli: rag-add <你要导入的rag文档目录>
agent-cli: rag-add <你要导入的rag文档目录> append
```

### `rag-delete <source>`

按 source 删除 RAG 文档。

```text
agent-cli: rag-delete example.md
```

### `rag-search <query>`

检索 RAG 知识库。

```text
agent-cli: rag-search C++ 工具有哪些算法？
```

### `db-list`

查看 `data/csv.sqlite3` 中 CSV 业务表和字段。

```text
agent-cli: db-list
```

### `db-add <csv_path|dir> [replace|append|fail]`

导入 CSV 到 `data/csv.sqlite3`。
`path` 可以是单个 `.csv` 文件，也可以是目录；如果是目录，会递归导入其中所有 `.csv` 文件。
表名自动取 CSV 文件名，例如 `example.csv` 会导入为表 `example`。

默认使用 `replace`。

- `replace`：如果同一个 table 已存在，先删除旧内容再重新导入。
- `append`：只导入新 table，跳过已存在的 table。
- `fail`：如果 table 已存在就报错。

```text
agent-cli: db-add <你要导入的csv表格>
agent-cli: db-add <你要导入的csv表格目录>
agent-cli: db-add <你要导入的csv表格目录> append
```

### `db-delete <table>`

删除 `data/csv.sqlite3` 中指定名称的表。

```text
agent-cli: db-delete sample_sales
```

### `db-query <sql>`

在 `data/csv.sqlite3` 中执行只读 SQL。

```text
agent-cli: db-query SELECT region, SUM(units * unit_price) AS revenue FROM sample_sales GROUP BY region
```

### `memory-list`

列出记忆窗口。

```text
agent-cli: memory-list
```

### `memory-new [session_id]`

新建记忆窗口。手动指定的 `session_id` 必须唯一。

```text
agent-cli: memory-new
agent-cli: memory-new example
```

### `memory-show <session_id>`

查看指定窗口的对话记忆。必须传入窗口 id。

```text
agent-cli: memory-show example
```

### `memory-clear <session_id>`

清空指定窗口的对话消息，保留窗口本身。

```text
agent-cli: memory-clear example
```

### `memory-delete <session_id>`

删除窗口、窗口消息和该窗口依赖申请。

```text
agent-cli: memory-delete example
```

### 'deps*'

记录python的依赖申请，来自 Python 沙箱或 Agent 工具。DeepSeek 不能直接安装包，只能记录申请。

#### 主菜单

查看所有窗口的依赖申请：

```text
agent-cli: deps-list
```

安装某个依赖。安装成功后，同名依赖会从所有窗口的 depending list 中删除：

```text
agent-cli: deps-install <model_name>
```

主菜单里的 `deps-install <model_name>` 使用模块名或包名，不使用依赖条目序号，因为主菜单展示的是多个窗口的列表。

安装某个窗口列表中的全部依赖：

```text
agent-cli: deps-install -a <window_num>
agent-cli: deps-install -a <window_id>
```

忽略所有窗口中的某个依赖：

```text
agent-cli: deps-ignore <model_name>
```

忽略某个窗口中的某个依赖：

```text
agent-cli: deps-ignore <model_name> <window_num>
agent-cli: deps-ignore <model_name> <window_id>
```

忽略某个窗口中的全部依赖：

```text
agent-cli: deps-ignore -a <window_num>
agent-cli: deps-ignore -a <window_id>
```

#### 任务窗口

在 `task[window-id]` 中，deps命令只作用于当前窗口：

```text
task[example]: deps-list
task[example]: deps-install <model_name>
task[example]: deps-install <model_num>
task[example]: deps-install -a
task[example]: deps-ignore <model_name>
task[example]: deps-ignore <model_num>
task[example]: deps-ignore -a
task[example]: help
```

任务窗口里的 `model_num` 指当前窗口 `deps-list` 输出中的依赖条目序号。例如当前窗口显示：

```text
Dependency requests for memory window: example
1. module=matplotlib | package=matplotlib
2. module=sklearn | package=scikit-learn
```

那么 `deps-install 1` 表示安装 `matplotlib`。

### 'help/?'

打印 command_help 到终端，主菜单与对话窗口的 command_help 不同。

### 'exit/quit'

返回上一级，若在主菜单输入则退出程序。

## 输出规则

所有生成结果必须写入 `output/`。

允许：

```text
output/result.csv
output/report.md
output/plot.png
```

不允许：

```text
data/result.csv
reports/report.md
result.md
```

## 注意事项

- 使用 `python main.py` 运行项目。
- 修改 C++ 扩展后，需要重新执行 `pip install -e .`。
