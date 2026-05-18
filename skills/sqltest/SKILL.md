---
name: sqltest
description: 数据库校验引擎。执行自动化测试用例（前置SQL → HTTP请求 → 校验SQL → 清理），提供原子化的 SQL 执行和用例验证能力，可被自动化测试技能编排。
---

# /sqltest — 数据库校验引擎

## 命令路由

| 命令 | 功能 | 面向角色 |
|---|---|---|
| `/sqltest run all` | 跑文档中全部用例 | 人 |
| `/sqltest run <接口名>` | 跑某个接口的全部用例 | 人 |
| `/sqltest run <用例名>` | 跑单条用例（如 TC001） | 人 |
| `/sqltest verify <用例名>` | 执行单条完整用例，返回结构化 pass/fail | 自动化 skill |
| `/sqltest exec "<SQL>"` | 执行一条 SQL，返回原始 MCP 结果 | 自动化 skill |
| `/sqltest config api-url <url>` | 设置 API 基地址 | 人 |

---

## 前置条件

- 用户已手动启动 API 服务（`dotnet run`），`/sqltest` 不负责启动服务
- `自动化测试Sql文档.md` 已存在（由其他 skill 或人工维护）
- MCP 数据库连接已配置（`/sql setup` 完成）
- **注意:** 测试数据变更不提供事务回滚。如果用例执行中断（HTTP 失败、进程退出等），清理 SQL 可能未执行，测试数据会残留在数据库中。建议每次运行后用 `/sqltest run all` 的清理步骤统一处理。

---

## 用例文档格式

`自动化测试Sql文档.md` 格式如下：

```markdown
# 自动化测试 SQL 文档

## POST /api/Contract/SaveContract

### TC001: 新增合同-校验落库
| 项 | 值 |
|---|---|
| 接口路径 | POST /api/Contract/SaveContract |
| Body | `{"CONTRACT_NO":"{{contract_no}}","CUSTOMER_ID":"{{customer_id}}"}` |
| 前置SQL | `SELECT CUSTOMER_ID AS customer_id FROM CDC_CUSTOMER_INFO WHERE ROWNUM=1` |
| 校验SQL | `SELECT COUNT(*) AS cnt FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='{{contract_no}}'` |
| 期望 | cnt = 1 |
| 清理SQL | `DELETE FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='{{contract_no}}'` |
```

解析规则：
- `## <接口路径>` — 接口分组
- `### <用例名>: <描述>` — 用例定义
- `| 项 | 值 |` 表格中，每行一个字段：接口路径、Body、前置SQL、校验SQL、期望、清理SQL
- `{{xxx}}` — 占位符，由前置 SQL 结果填充

---

## 模式 1: `/sqltest run`

### 子命令

| 子命令 | 匹配规则 |
|---|---|
| `run all` | 解析全部 `###` 用例 |
| `run <接口名>` | 匹配 `##` 分组 |
| `run <用例名>` | 精确匹配 `###` 用例名 |

### 执行流程

对每个匹配的用例：

#### Step 1: 执行前置 SQL

通过 MCP 执行前置 SQL。入参格式：
```json
{"sql": "<前置SQL>"}
```

工具名：`mcp__toolbox-<默认DB>__execute_sql`（默认 DB 从 `.mcp.json` 取第一个 `toolbox-*` entry）。

返回结果示例：
```json
{"customer_id": "KH20240001"}
```

**如果前置 SQL 返回空：** 标记为 ⚠️ SKIP，输出 `原因: 前置 SQL 返回空`，跳过该用例。

**如果前置 SQL 执行失败：** 标记为 ⚠️ SKIP，输出 MCP 返回的错误信息。

**如果前置 SQL 返回多行：** 使用第一行的值，并输出警告：`⚠️ 前置 SQL 返回了 N 行，仅使用第一行`。前置 SQL 应始终返回单行。

#### Step 2: 替换占位符

将前置 SQL 结果的别名列值填入所有 `{{xxx}}` 占位符：
- `SELECT ... AS customer_id` → `{{customer_id}}` → `KH20240001`
- 同步替换 Body、校验SQL、清理SQL 中的占位符

**内置占位符（不依赖前置 SQL）：**

| 占位符 | 取值 | 示例 |
|---|---|---|
| `{{random:N}}` | N 位随机数字字符串 | `{{random:6}}` → `482931` |
| `{{datetime}}` | 当前时间 `yyyy-MM-dd HH:mm:ss` | `2026-05-17 14:30:00` |
| `{{date}}` | 当前日期 `yyyy-MM-dd` | `2026-05-17` |

#### Step 3: 构造 HTTP 请求

解析 `接口路径`（格式：`METHOD /path`，第一个空格前为 Method，其余为路径）。

API 基地址：读取本 SKILL.md 顶部 `<!-- api-base-url: http://localhost:5000 -->` 标记，无标记默认 `http://localhost:5000`。

执行请求（PowerShell）：

```powershell
$body = '<替换后的 JSON>'
try {
    $response = Invoke-WebRequest -Uri "<基地址>/path" -Method <METHOD> -Body $body -ContentType "application/json"
    Write-Host "STATUS:$($response.StatusCode)"
    Write-Host "BODY:$($response.Content)"
} catch {
    $resp = $_.Exception.Response
    if ($resp) {
        Write-Host "STATUS:$($resp.StatusCode.value__)"
        $reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
        Write-Host "BODY:$($reader.ReadToEnd())"
    } else {
        Write-Host "HTTP_ERROR:$_"
    }
}
```

**HTTP 请求异常处理：** 如果 `Invoke-WebRequest` 抛出异常（超时/连接拒绝等），且 `$_.Exception.Response` 为空，标记为 ❌ FAIL，输出错误原因。如果存在 `Response` 对象（服务端返回了响应），则继续进入 Step 4 校验，由期望规则判定结果。

#### Step 4: 执行校验

**校验顺序：** 始终先检查期望规则，再判定 PASS/FAIL。HTTP 返回 4xx/5xx 不等于直接失败——如果期望是 `status != 200` 或 `response.success = false`，这正是预期的正确结果。

**有校验 SQL 的用例：**

执行校验 SQL（MCP），拿到结果后与"期望"对比。

期望格式解析：

| 期望写法 | 解析方式 |
|---|---|
| `cnt = 1` | SQL 结果中 `cnt` 字段值与期望值字符串相等 |
| `cnt != 1` | SQL 结果中 `cnt` 字段值与期望值字符串不等 |
| `cnt > 0` | `cnt` 字段值（数值解析）> 期望值 |
| `cnt >= N` | `cnt` 字段值（数值解析）>= 期望值 |
| `cnt < N` | `cnt` 字段值（数值解析）< 期望值 |
| `cnt <= N` | `cnt` 字段值（数值解析）<= 期望值 |

数值比较规则：
- 对于 `>`、`>=`、`<`、`<=` 操作符，先将 SQL 结果值和期望值都解析为数字（`decimal`/`double`）再比较
- 如果解析失败（非数字字符串），降级为字符串比较，并输出警告：`⚠️ 无法将值解析为数字，使用字符串比较`
- 对于 `=` 和 `!=` 操作符，使用字符串比较（大小写敏感）

对比逻辑（以 `cnt = 1` 为例）：
1. 运行校验 SQL → 拿到结果 `{"cnt": "1"}`
2. 提取 `cnt` 值 → `"1"`
3. 与期望值 `"1"` 比较 → 相等 → PASS
4. 不相等 → FAIL，输出实际值

**无校验 SQL 但有 response 期望的用例：**

| 期望写法 | 解析 |
|---|---|
| `response.success = true` | HTTP response JSON 中 `success` 字段为 true |
| `response.success = false` | `success` 字段为 false |
| `status = 200` | HTTP 状态码等于 200 |
| `status != 200` | HTTP 状态码不等于 200 |
| `status = N` | HTTP 状态码等于指定值（如 `status = 400`） |

**关键规则：** 响应期望检查优先于 HTTP 状态判定。例如，期望 `status != 200` 时，HTTP 返回 400 是 PASS。只有当期望值不匹配时才标记 FAIL。

#### Step 5: 输出结果

成功：
```
✅ TC001: 新增合同-校验落库  PASS
╰─ 校验: cnt=1 符合预期
```

失败：
```
❌ TC002: 合同编号必填校验  FAIL
   原因: 期望 success=false，实际 success=true (HTTP 200)
```

跳过：
```
⚠️  TC003: 查询合同列表  SKIP
   原因: 前置 SQL 返回空（无可用客户数据）
```

#### Step 6: 执行清理 SQL

**清理确认：** 执行前展示清理 SQL 并等待用户确认：

- **单个用例（`run <用例名>`）：** 显示清理 SQL，询问 `是否执行清理 SQL？（y/n）`。输入 `n` 跳过清理。
- **`run all` 模式：** 所有用例执行完毕后，汇总所有清理 SQL 一起展示：
  ```
  以下清理 SQL 将执行:
    - DELETE FROM T1 WHERE ID='xxx'
    - DELETE FROM T2 WHERE NO='yyy'
  是否执行？（y/n/a）
  ```
  - `y` = 逐条确认（每条询问）
  - `n` = 全部跳过
  - `a` = 全部执行，不再询问

如果用例有 `清理SQL` 字段，执行它。多条清理 SQL 用 `;` 分隔，按序执行。

**SKIP 用例的清理：** 对于因前置 SQL 返回空或执行失败而 SKIP 的用例，跳过清理 SQL（因为占位符未填充，清理 SQL 可能包含未解析的 `{{}}`）。

---

## 模式 2: `/sqltest verify <用例名>`

流程与 `run <用例名>` 相同，但输出结构化单行格式（`|` 分隔）：

```
PASS|TC001|POST /api/Contract/SaveContract|新增合同-校验落库|cnt=1
```

或：

```
FAIL|TC002|POST /api/Contract/SaveContract|合同编号必填校验|期望 success=false 实际 success=true
```

或：

```
SKIP|TC003|POST /api/Contract/GetList|查询合同列表|前置SQL返回空
```

格式：`<状态>|<用例名>|<接口路径>|<描述>|<详情>`

自动化 skill 可用 `|` 分割解析。

---

## 模式 3: `/sqltest exec "<SQL>"`

接收单条 SQL，直接调用 MCP 执行，返回原始 JSON 结果。不做任何包装、不做校验、不做清理。

```
/sqltest exec "SELECT COUNT(*) AS cnt FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='KH-2024-0001'"
```

**DML 安全确认：** 对于非 SELECT 语句（INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/CREATE），执行前展示 SQL 并询问 `⚠️ 非查询操作，是否执行？（y/n）`。仅 `y` 时执行。SELECT 语句直接执行，无需确认。

返回原始 MCP JSON。不添加任何前导文本或格式。

**用途：** 自动化 skill 在复杂场景下自行编排多步 SQL 查询，`/sqltest exec` 仅作为 SQL 执行通道。

---

## 报告汇总（run all 模式专用）

全部用例执行完毕后展示汇总：

```
╔══════════════════════════════════════════╗
║          /sqltest run all                ║
╠══════════════════════════════════════════╣
║ ✅ TC001 新增合同-校验落库                  ║
║ ❌ TC002 合同编号必填校验                    ║
║    期望: success=false                    ║
║    实际: success=true (HTTP 200)           ║
║ ⚠️  TC003 查询合同列表  SKIP               ║
║    原因: 前置SQL返回空                      ║
╠══════════════════════════════════════════╣
║ 总计: 1 PASS / 1 FAIL / 1 SKIP           ║
╚══════════════════════════════════════════╝
```

---

## 默认数据库

与 `/sql` 共享 `.mcp.json` 配置。执行 SQL 时：
- 读取 `.mcp.json` → 取第一个 `toolbox-*` entry 作为默认
- 工具名：`mcp__<entry-name>__execute_sql`

---

## API 基地址配置

本 SKILL.md 顶部可标记 API 基地址：
```
<!-- api-base-url: http://localhost:5000 -->
```

如果用户需要修改基地址：

```
/sqltest config api-url http://localhost:6000
```

使用 Edit 工具更新标记中的 URL。

---

## 错误处理

| 错误场景 | 处理方式 |
|---|---|
| `自动化测试Sql文档.md` 不存在 | `❌ 未找到自动化测试Sql文档.md，请先创建测试用例文档` |
| 用例名/接口名未匹配到 | `❌ 未找到用例 "<name>"，请检查用例名是否正确` |
| MCP 连接失败 | `❌ 数据库连接失败，请检查 /mcp 重连状态` |
| HTTP 请求超时 | `❌ HTTP 请求超时，请确认 API 服务已启动` |
| 前置 SQL 返回空 | `⚠️ SKIP`，不阻塞后续用例 |
| 清理 SQL 执行失败 | 输出警告但不影响用例结果判定 |
