---
name: sql
description: SQL 查询与数据库表结构管理。通过 MCP 操作数据库，支持直接 SQL、自然语言查询、数据库连接配置、表结构文档生成。
---

<!-- default-db: toolbox-postgres -->

# /sql — SQL 查询与表结构管理

## 命令路由

收到 `/sql <args>` 后，按以下规则判断模式：

| 输入 | 模式 | 处理方式 |
|---|---|---|
| `/sql setup` | 交互式配置 | 逐一询问 4 个问题，然后执行配置 |
| `/sql "..."` （引号包裹） | 直接执行 SQL | 直接调用 MCP，不询问 |
| `/sql list` | 列出连接 | 读取 .mcp.json |
| `/sql use <别名>` | 切换连接 | 更新本 skill 的默认 DB 标记 |
| 其他（无引号的自然语言） | 智能查询 | 读表结构文档 → 生成 SQL → 确认 → 执行 |

---

## 模式 1: `/sql setup`

**流程：逐一询问，每题一问，等待用户回答后继续下一问。**

### Q1: 数据库类型

> 选择数据库类型：
> A. postgres
> B. mysql
> C. mssql
> D. oracle
> E. sqlite

记下用户选择。

如果用户回复 `取消` 或 `退出`，回复 `已取消 setup。` 并结束设置向导。

### Q2: 连接信息

> 请提供连接信息，格式如下：
> ```
> 主机:端口  用户名  密码  数据库名
> ```
> 例如: `192.168.1.100:5432  postgres  mypassword  lisdb`

解析用户输入，记下 host、port、user、password、database。

如果 Q1 选择了 sqlite，Q2 改为询问：
> 请提供 SQLite 文件路径。
> 例如: `/path/to/database.db`

如果用户回复 `取消` 或 `退出`，回复 `已取消 setup。` 并结束设置向导。

### Q3: 别名

> 给这个连接起个别名？（默认: `<类型>-<库名>`）

如果用户直接回车或不回复，使用默认值 `<类型>-<库名>`。

如果用户回复 `取消` 或 `退出`，回复 `已取消 setup。` 并结束设置向导。

### Q4: 表结构文档

> 是否有表结构文档（.docx）需要解析？如果有，请提供路径。
> 例如: `设计相关/CDC管理表结构说明.docx`
> 如果没有，输入 `无` 跳过。

如果用户回复 `取消` 或 `退出`，回复 `已取消 setup。` 并结束设置向导。

### 执行配置

收集完 4 个回答后，执行以下操作：

#### A. 更新 .mcp.json

先读取 `.mcp.json` 是否存在：
- 不存在 → 创建 `{"mcpServers": {}}`
- 存在 → 先检查 `.mcp.json` 中是否已存在 `toolbox-<别名>`。如果存在，提示用户：`⚠️ 别名 "<别名>" 已存在，请选择其他别名。` 并回到 Q3 重新询问。确认不冲突后，追加新 entry

追加的 entry 格式（以 postgres 为例）：

```json
{
  "toolbox-<别名>": {
    "command": "npx",
    "args": ["-y", "@toolbox-sdk/server", "--prebuilt=<类型>", "--stdio"],
    "env": {
      "<类型大写>_HOST": "<主机>",
      "<类型大写>_PORT": "<端口>",
      "<类型大写>_USER": "<用户名>",
      "<类型大写>_PASSWORD": "<密码>",
      "<类型大写>_DATABASE": "<数据库名>"
    }
  }
}
```

**各数据库类型的环境变量映射：**

| 类型 | env 前缀 | 端口默认值 |
|---|---|---|
| postgres | POSTGRES_ | 5432 |
| mysql | MYSQL_ | 3306 |
| mssql | MSSQL_ | 1433 |
| oracle | ORACLE_ | 1521 |
| sqlite | SQLITE_ | (仅 FILEPATH) |

**CRITICAL:** 使用 Edit 工具精确追加——不要用 Write 覆盖整个文件，避免丢失已有的其他 MCP 配置。

#### B. 解析表结构文档（如果提供了 docx）

1. 确保 python-docx 已安装：`py -m pip install python-docx -q`
2. 运行解析脚本：`py .claude/skills/sql/scripts/parse_docx.py "<docx路径>"`
3. 确认输出：
   - `设计相关/表目录.md`
   - `设计相关/表结构/*.md`

#### C. 完成提示

```
✅ MCP 配置已添加: toolbox-<别名>
   表结构文档已生成（如果提供）。
   
⚠️  请执行 /mcp 重连，然后使用 /sql list 确认连接可用。
```

---

## 模式 2: `/sql "SQL语句"` 直接执行

### 判断默认数据库

检查本 skill 顶部是否标记了默认 DB：
```
<!-- default-db: toolbox-postgres -->
```
如果没有标记，读取 `.mcp.json` 找到第一个 `toolbox-*` entry 作为默认。

### 执行

**如果是非 SELECT 语句（INSERT/UPDATE/DELETE/CREATE/ALTER/DROP 等）：**

先展示 SQL 并确认：
```
⚠️ 非查询操作，是否执行？（y/n）
```
只有用户回复 `y` 才执行。用户回复 `n` 或不回复则取消。

**如果是 SELECT 语句：** 直接执行，不需确认。

调用 `mcp__<默认DB名>__execute_sql`，传入 SQL 语句。

入参格式：
```json
{"sql": "<SQL语句>"}
```

### 结果展示

根据 SQL 类型展示：

| SQL 类型 | 展示方式 |
|---|---|
| SELECT | Markdown 表格（用查询结果的列名做表头，行数据做表体） |
| INSERT | `✅ 插入成功，影响 1 行` |
| UPDATE | `✅ 更新成功，影响 N 行` |
| DELETE | `⚠️ 删除成功，影响 N 行` |
| CREATE/ALTER/DROP | `✅ DDL 执行成功` |

**SELECT 结果展示示例：**

```
| data_id | class_id | data_cname | data_state |
|---|---|---|---|
| 00010001 | 客户来源 | 外部委托 | 1 |
```

**空结果处理：** 如果 SELECT 返回 0 行，展示 `查询结果为空`，不生成空表格。

**SELECT LIMIT 限制：** 对于 SELECT 语句，如果用户未指定 LIMIT，自动追加 `LIMIT 100`（Oracle 追加 `WHERE ROWNUM <= 100`）。

**注意：** 结果只在终端展示，不生成任何文件。

---

## 模式 3: `/sql <自然语言>` 智能查询

### 步骤 1: 定位涉及的表

读取 `设计相关/表目录.md`，根据用户的自然语言描述，找到相关的表名。

如果匹配到的表超过 5 张，列出所有匹配的表名和说明，让用户选择相关表继续。

例如用户说"合同表及其所属客户信息"：
- 匹配 "合同" → `CDC_CONTRACT_INFO`
- 匹配 "客户" → `CDC_CUSTOMER_INFO`

如果找不到 `表目录.md`，回复：
> 尚未生成表结构文档。请先运行 `/sql setup` 导入表结构。

### 步骤 2: 读取表结构

读取 `设计相关/表结构/<表名>.md`，获取每张表的：
- 所有字段（字段名、类型、说明）
- 主键
- 外键关系（如 `CUSTOMER_ID → CDC_CUSTOMER_INFO.CUSTOMER_ID`）

### 步骤 3: 生成 SQL

根据表结构和外键关系，生成合理的 SQL 语句。规则：
- 使用外键关系自动生成 JOIN 条件
- SELECT 列名使用实际字段名
- 加上 LIMIT 100 避免返回过多数据（Oracle 用 ROWNUM）
- 如果有多个可能的关联方式，选择最符合用户意图的

### 步骤 4: 展示 SQL 并确认

```
根据表结构生成以下 SQL：

  SELECT t1.CONTRACT_NO, t1.CONTRACT_NAME, t2.CUSTOMER_NAME
  FROM CDC_CONTRACT_INFO t1
  LEFT JOIN CDC_CUSTOMER_INFO t2 ON t1.CUSTOMER_ID = t2.CUSTOMER_ID
  LIMIT 100

是否执行？（回复 y 或修改意见）
```

### 步骤 5: 执行

用户确认后，按模式 2 的方式执行并展示结果。如果用户提出修改意见，回到步骤 3 调整 SQL。

---

## 模式 4: `/sql list`

读取 `.mcp.json`，提取所有 `toolbox-*` entry，展示：

```
已配置的数据库连接:
  🔵 toolbox-postgres     (当前默认)
     postgres://postgres@d40.lis-china.com:5432/lisdb
```

当前默认 DB 看本 skill 顶部的 `<!-- default-db: xxx -->` 标记。

---

## 模式 5: `/sql use <别名>`

1. 读取 `.mcp.json`，检查 `toolbox-<别名>` 是否存在
2. 不存在 → `❌ 连接 toolbox-<别名> 未找到。使用 /sql list 查看可用连接。`
3. 存在 → 使用 Edit 工具更新本 SKILL.md 顶部的默认 DB 标记为：

```
<!-- default-db: toolbox-<别名> -->
```

回复: `✅ 已切换到 toolbox-<别名>`

---

## 错误处理

| 错误场景 | 回复 |
|---|---|
| MCP 连接超时 / 无法连接 | `❌ 数据库连接超时，请检查数据库是否运行，或执行 /mcp 重连` |
| 认证失败 | `❌ 认证失败，请检查用户名和密码` |
| SQL 语法错误 | `❌ SQL 执行错误: <MCP 返回的错误信息>` |
| .mcp.json 不存在 | `❌ 未找到 .mcp.json，请先运行 /sql setup 配置数据库连接` |
| 表结构文档不存在 | `❌ 尚未生成表结构文档。请先运行 /sql setup 导入表结构。` |

---

## MCP 工具命名规则

`.mcp.json` 中的 server name 为 `toolbox-<别名>`，对应的 MCP 工具前缀为 `mcp__toolbox-<别名>__`。

例如 `toolbox-postgres` → `mcp__toolbox-postgres__execute_sql`。

执行 SQL 前，从 `.mcp.json` 读取可用的 server name，拼出正确的 MCP 工具名。
