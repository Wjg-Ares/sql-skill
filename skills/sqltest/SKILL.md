---
name: sqltest
description: 数据库校验引擎。执行自动化测试用例（前置SQL → HTTP请求 → 校验SQL → 清理），内置 DAG 依赖编排、并行调度、对抗验证，可被自动化测试技能编排。
---

<!-- api-base-url: http://localhost:5000 -->
<!-- token-url: (none) -->

# /sqltest — 数据库校验引擎（Harness）

## 命令路由

| 命令 | 功能 | 面向角色 |
|---|---|---|
| `/sqltest run all` | 跑文档中全部用例（DAG 编排，自动并行） | 人 |
| `/sqltest run <接口名>` | 跑某个接口的全部用例 | 人 |
| `/sqltest run <用例名>` | 跑单条用例（如 TC001） | 人 |
| `/sqltest dag` | 展示用例依赖图，不执行 | 人 |
| `/sqltest verify <用例名>` | 执行单条完整用例，返回结构化 pass/fail | 自动化 skill |
| `/sqltest exec "<SQL>"` | 执行一条 SQL，返回原始 MCP 结果 | 自动化 skill |
| `/sqltest config api-url <url>` | 设置 API 基地址 | 人 |
| `/sqltest config token-url <method> <url>` | 设置 Token 获取方式 | 人 |
| `/sqltest version` | 查看版本号 | 人 |

---

## 前置条件

- 用户已手动启动 API 服务（`dotnet run`），`/sqltest` 不负责启动服务
- `自动化测试Sql文档.md` 已存在（由其他 skill 或人工维护）
- MCP 数据库连接已配置（`/sql setup` 完成）
- **注意:** 测试数据变更不提供事务回滚。如果用例执行中断（HTTP 失败、进程退出等），清理 SQL 可能未执行，测试数据会残留在数据库中。

---

## 依赖关系类型（FS / SS / FF / SF）

用例之间可能存在执行顺序依赖。通过 `依赖` 字段声明，编排引擎自动构建 DAG 并分层调度。

```
时间轴 →

FS（完成 → 开始）：A 完成了，B 才能开始
  A:   [══════ 新增合同 ══════]
  B:                           [══════ 查询合同 ══════]
  最常用。"新增完了才能查/改/删"

SS（开始 → 开始）：A 开始了，B 就可以开始
  A:   [══════ 新增合同 ══════]
  B:   [══════ 确认列表刷新 ═══]
  同时开始但不冲突的场景

FF（完成 → 完成）：B 的完成不能早于 A 的完成
  A:   [══════ 数据准备 ══════]
  B:   [═══════ 清理 ═══════]
                           ↑ 两个必须同时结束
  确保清理不会在准备完成之前执行

SF（开始 → 完成）：A 开始了，B 才可以结束
  A:   [══════ 新增 ══════]
       ↑
       └── B: [══════ 监控确认 ══]
                            ↑ A 一开始，B 就可以收尾
  极少用，通常用于触发即完成的监控/通知场景
```

**声明格式：**

```
| 依赖 | TC001 |                   ← 默认 FS
| 依赖 | TC001:FS |                ← 显式写 FS
| 依赖 | TC001:FS, TC002:FF |      ← 多个依赖，不同类型
| 依赖 | 无 |                      ← 无依赖
```

**90% 的场景只需要写用例名**，默认就是 FS。FF 主要用于"清理用例的完成不能早于数据准备用例的完成"。

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
| 依赖 | 无 |
| Body | `{"CONTRACT_NO":"{{contract_no}}","CUSTOMER_ID":"{{customer_id}}"}` |
| 前置SQL | `SELECT CUSTOMER_ID AS customer_id FROM CDC_CUSTOMER_INFO WHERE ROWNUM=1` |
| 校验SQL | `SELECT COUNT(*) AS cnt FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='{{contract_no}}'` |
| 期望 | cnt = 1 |
| 清理SQL | `DELETE FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='{{contract_no}}'` |
| 反向校验SQL | `SELECT COUNT(*) AS cnt FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='{{contract_no}}' AND CUSTOMER_ID != '{{customer_id}}'` |
| 反向期望 | cnt = 0 |

### TC003: 查询合同列表
| 项 | 值 |
|---|---|
| 接口路径 | POST /api/Contract/GetContractList |
| 依赖 | TC001 |
| Query | `?keyword=测试` |
| 期望 | response.success = true |

### TC004: 修改合同
| 项 | 值 |
|---|---|
| 接口路径 | PUT /api/Contract/UpdateContract |
| 依赖 | TC001:FS |
| Body | `{"CONTRACT_NO":"{{contract_no}}","CUSTOMER_NAME":"修改后名称"}` |
| 前置SQL | `SELECT CONTRACT_NO AS contract_no FROM CDC_CONTRACT_INFO WHERE ROWNUM=1` |
| 校验SQL | `SELECT CUSTOMER_NAME AS name FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='{{contract_no}}'` |
| 期望 | name = 修改后名称 |
| 清理SQL | `UPDATE CDC_CONTRACT_INFO SET CUSTOMER_NAME='原始名称' WHERE CONTRACT_NO='{{contract_no}}'` |
```

解析规则：
- `## <接口路径>` — 接口分组
- `### <用例名>: <描述>` — 用例定义
- `| 项 | 值 |` 表格，每行一个字段
- `{{xxx}}` — 占位符，由前置 SQL 结果填充

**字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| 接口路径 | 是 | `METHOD /path`，如 `POST /api/Contract/SaveContract` |
| 依赖 | 否 | 默认 `无`。格式见"依赖关系类型"章节 |
| Body | 否 | JSON 请求体，支持 `{{占位符}}` |
| Query | 否 | URL 查询参数，支持 `{{占位符}}` |
| 前置SQL | 否 | 执行前查询，结果用于填充占位符 |
| 校验SQL | 否 | 执行后校验数据落库 |
| 期望 | 否 | 校验期望，格式见校验章节 |
| 清理SQL | 否 | 还原测试数据 |
| 反向校验SQL | 否 | 对抗验证用，见"对抗验证"章节 |
| 反向期望 | 否 | 对抗验证期望值 |

---

## 执行编排引擎

`run all` 不是简单的一个一个串行跑。它内部是一个 DAG 编排引擎。

### 第一步：解析所有用例

提取每个用例的：
- 用例名（如 TC001）
- 依赖列表（如 `[TC001:FS, TC002:FF]`）
- 涉及的数据表（自动从 SQL 中提取表名）

### 第二步：构建 DAG（有向无环图）

```
用例文档：

  TC001: 新增合同       依赖: 无     表: CDC_CONTRACT_INFO
  TC002: 新增客户       依赖: 无     表: CDC_CUSTOMER_INFO
  TC003: 查询合同列表   依赖: TC001   表: CDC_CONTRACT_INFO (读)
  TC004: 修改合同       依赖: TC001   表: CDC_CONTRACT_INFO
  TC005: 删除合同       依赖: TC001, TC004
  TC006: 查询客户列表   依赖: TC002   表: CDC_CUSTOMER_INFO (读)

画出的 DAG：

    TC001 ──→ TC003
      │  ──→ TC004 ──→ TC005
      │
    TC002 ──→ TC006
```

### 第三步：拓扑排序分层

```
第1层: TC001, TC002    ← 无依赖，可并行
第2层: TC003, TC004, TC006  ← 等第1层全部完成
第3层: TC005           ← 等 TC004 完成（TC001 已在第1层完成）
```

### 第四步：逐层并行执行

```
═══ Layer 1 ═══
  TC001 ─┐
          ├─ parallel ─→ 完成
  TC002 ─┘

═══ Layer 2 ═══ (等 Layer 1 全部完成)
  TC003 ─┐
  TC004 ─┼─ parallel ─→ 完成
  TC006 ─┘

═══ Layer 3 ═══ (等 Layer 2 全部完成)
  TC005 → 完成
```

### 表冲突自动检测

除了用户声明的依赖，编排引擎还会自动检测表冲突：

```
规则：
  1. 解析每个用例的所有 SQL（前置、校验、清理、反向校验）
  2. 提取操作的表名（FROM、INSERT INTO、UPDATE、DELETE FROM 后面的表名）
  3. 同一层内，如果两个用例操作同一张表：
     - 任意一个是写操作（INSERT/UPDATE/DELETE）→ 标记冲突，必须串行
     - 两个都是读操作（SELECT）→ 安全可并行
  4. 冲突的用例自动拆到不同层
```

```
示例：

  TC001: 表 CDC_CONTRACT_INFO (写)  ┐
  TC002: 表 CDC_CUSTOMER_INFO (写)  ├─ 不同表 → 可以同层并行
  TC003: 表 CDC_CONTRACT_INFO (读)  ┘  但 TC003 依赖 TC001，所以必须在下一层

  TC004: 表 CDC_CONTRACT_INFO (写)
  TC008: 表 CDC_CONTRACT_INFO (写)  ← 同表冲突！即使没声明依赖也必须分到不同层
```

**展示冲突检测结果：** 在开始执行前展示：

```
表冲突检测:
  ⚠️  TC004 与 TC008 操作同表 CDC_CONTRACT_INFO（均为写操作）→ 自动分到不同层
  ✅ TC001 与 TC002 操作不同表 → 可同层并行
```

### 依赖类型的具体调度

| 类型 | 调度规则 |
|------|---------|
| **FS** | B 必须在 A **完成**后才能进入待执行层 |
| **SS** | B 可以和 A 在**同一层**开始（自动检查表冲突） |
| **FF** | A 和 B 必须在**同一层结束**——B 不能比 A 先完成 |
| **SF** | B 必须等 A **开始**后才能进入完成态 |

**FF 的实现：** 如果 B 先跑完了，引擎等待 A 完成后才标记 B 为 done。保证 A 完成前 B 不会进入"已完成"状态。

**SS 的实现：** SS 声明的两个用例会被强制放到同一层，并行执行。

---

## 模式 1: `/sqltest run`

### 子命令

| 子命令 | 匹配规则 |
|---|---|
| `run all` | 解析全部 `###` 用例，DAG 编排执行 |
| `run <接口名>` | 匹配 `##` 分组，组内用例用 DAG 编排 |
| `run <用例名>` | 精确匹配 `###` 用例名，单用例执行（含对抗验证） |

### `run all` / `run <接口名>` 执行流程

#### Phase 0: 解析 + 构建编排计划

读取文档，解析所有匹配的用例。构建 DAG：

1. 提取每个用例的依赖声明
2. 自动检测表冲突
3. 拓扑排序分层
4. **展示编排计划并确认：**

```
╔══════════════════════════════════════════════╗
║           执行编排计划                        ║
╠══════════════════════════════════════════════╣
║                                              ║
║  Layer 1 (并行, ~5s):                        ║
║    TC001: 新增合同-校验落库                    ║
║    TC002: 新增客户-校验落库                    ║
║                                              ║
║  Layer 2 (并行, ~8s):                        ║
║    TC003: 查询合同列表                        ║
║    TC004: 修改合同                            ║
║    TC006: 查询客户列表                        ║
║                                              ║
║  Layer 3 (串行, ~3s):                        ║
║    TC005: 删除合同                            ║
║                                              ║
║  总预计耗时: ~16s（纯串行 ~26s）               ║
║  表冲突检测: TC004/TC008 自动分层              ║
║                                              ║
╠══════════════════════════════════════════════╣
║  是否执行？（y/n）                             ║
╚══════════════════════════════════════════════╝
```

#### Phase 1: 获取 Token（如已配置）

Token 在整轮执行中只获取一次，所有用例复用。401 时重新获取。

#### Phase 2: 逐层并行执行

对每一层（Layer）：

**该层内所有用例并行执行**（同时启动）。每个用例走标准流水线：

```
  前置SQL → 占位符替换 → HTTP请求 → 校验 → 对抗验证 → (暂不清理)
```

清理统一在全部层执行完毕后处理。

**层间串行：** 等当前层的**所有**用例完成（或 SKIP），才进入下一层。

**FF 依赖处理：** 如果层内有 FF 依赖的用例对，标记为"对等完成"——即使快速用例已完成，也等慢速用例完成后一起标记 done。

**用例级流水线复用：** 同一层内，用例 A 的前置 SQL 跑完开始 HTTP 请求时，用例 B 可以同时跑前置 SQL。不互相阻塞。

#### 单用例执行流程

每个用例的详细步骤：

##### Step 1: 执行前置 SQL

通过 MCP 执行。入参格式：
```json
{"sql": "<前置SQL>"}
```

工具名：`mcp__toolbox-<默认DB>__execute_sql`。

**如果前置 SQL 返回空：** 标记为 ⚠️ SKIP，跳过该用例。不阻塞同层其他用例。

**如果前置 SQL 执行失败：** 标记为 ⚠️ SKIP。

**如果前置 SQL 返回多行：** 使用第一行，输出警告 `⚠️ 前置 SQL 返回了 N 行，仅使用第一行`。

##### Step 2: 替换占位符

将前置 SQL 结果的别名列值填入所有 `{{xxx}}` 占位符。同步替换 Body、Query、校验SQL、清理SQL、反向校验SQL。

**内置占位符：**

| 占位符 | 取值 | 示例 |
|---|---|---|
| `{{random:N}}` | N 位随机数字字符串 | `{{random:6}}` → `482931` |
| `{{datetime}}` | 当前时间 `yyyy-MM-dd HH:mm:ss` | `2026-05-17 14:30:00` |
| `{{date}}` | 当前日期 `yyyy-MM-dd` | `2026-05-17` |

##### Step 3: 构造 HTTP 请求

解析 `接口路径`（格式：`METHOD /path`）。

API 基地址：读取本 SKILL.md 顶部 `<!-- api-base-url: ... -->` 标记，无标记默认 `http://localhost:5000`。

**GET 请求：** 如果用例有 `Query` 字段，拼接到 URL。

**请求头：** 如果已获取 token，添加 `Authorization: Bearer <token>`。

**URL 编码规则：** Query 参数值含中文或特殊字符时，进行 URL 编码。

执行请求（PowerShell）：

```powershell
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$body = '<替换后的 JSON>'
$headers = @{}
<if token:>$headers["Authorization"] = "Bearer <token>"
</if>
try {
    if ($body) {
        $response = Invoke-WebRequest -Uri "<基地址>/path" -Method <METHOD> -Body $body -ContentType "application/json" -Headers $headers -TimeoutSec 30
    } else {
        $response = Invoke-WebRequest -Uri "<基地址>/path" -Method <METHOD> -Headers $headers -TimeoutSec 30
    }
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

**HTTP 请求异常处理：** 如果异常且 `$_.Exception.Response` 为空，标记 ❌ FAIL。如果存在 Response 对象，继续进入校验阶段。

##### Step 4: 执行校验

校验顺序：先检查期望规则，再判定 PASS/FAIL。HTTP 返回 4xx/5xx 不等于直接失败。

**有校验 SQL 的用例：** 执行校验 SQL，与期望对比。

期望格式解析：

| 期望写法 | 解析方式 |
|---|---|
| `cnt = 1` | SQL 结果字段值与期望值字符串相等 |
| `cnt != 1` | 不等 |
| `cnt > 0` | 数值大于 |
| `cnt >= N` | 数值大于等于 |
| `cnt < N` | 数值小于 |
| `cnt <= N` | 数值小于等于 |

数值比较：先尝试解析为数字比较，失败则降级为字符串比较并警告。

**无校验 SQL 但有 response 期望的用例：**

| 期望写法 | 解析 |
|---|---|
| `response.success = true` | HTTP response JSON 中 `success` 字段为 true |
| `response.success = false` | `success` 字段为 false |
| `status = 200` | HTTP 状态码等于 200 |
| `status != 200` | HTTP 状态码不等于 200 |
| `status = N` | HTTP 状态码等于指定值 |

##### Step 5: 对抗验证

**仅当用例填写了 `反向校验SQL` 字段时触发。**

```
普通验证：
  校验SQL: SELECT COUNT(*) AS cnt FROM T WHERE CONTRACT_NO='xxx'
  期望: cnt = 1  → 结果: cnt = 1  → ✅ PASS

对抗验证：
  反向校验SQL: SELECT COUNT(*) AS cnt FROM T
               WHERE CONTRACT_NO='xxx' AND 不该存在此操作导致的值
  反向期望: cnt = 0
  → 如果反向校验也返回了数据（cnt > 0），说明数据可能是之前就存在的
  → 触发警告: ⚠️ 反向校验未通过，数据可能非本次操作产生
```

**判定规则：**
- 正向校验 PASS + 反向校验 PASS → ✅ PASS（确认数据是本操作产生的）
- 正向校验 PASS + 反向校验 FAIL → ⚠️ WARN（数据符合期望但可能不是本操作写入的）
- 正向校验 FAIL → ❌ FAIL（不管反向校验结果）
- 未填 `反向校验SQL` → 跳过对抗验证，按正向校验结果判定

**输出示例：**

```
✅ TC001: 新增合同-校验落库  PASS
╰─ 校验: cnt=1 符合预期
╰─ 对抗: 反向校验 cnt=0 通过（确认为本次操作写入）
```

```
⚠️  TC001: 新增合同-校验落库  WARN
╰─ 校验: cnt=1 符合预期
╰─ 对抗: 反向校验 cnt=3 未通过（数据可能非本次操作产生，请人工确认）
```

##### Step 6: 输出结果

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

#### Phase 3: 执行清理

所有层执行完毕后，汇总所有需要清理的 SQL：

```
以下清理 SQL 将执行:
  - [TC001] DELETE FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='xxx'
  - [TC004] UPDATE CDC_CONTRACT_INFO SET CUSTOMER_NAME='原始名称' WHERE CONTRACT_NO='xxx'
是否执行？（y/n/a）
```

- `y` = 逐条确认
- `n` = 全部跳过
- `a` = 全部执行，不再询问

**SKIP 用例的清理跳过**（占位符未填充，SQL 含未解析的 `{{}}`）。

---

## 模式 2: `/sqltest dag`

展示用例依赖图，不执行任何用例。

```
/sqltest dag
```

输出：

```
╔══════════════════════════════════════════════╗
║           用例依赖图 (DAG)                    ║
╠══════════════════════════════════════════════╣
║                                              ║
║  TC001 (新增合同) ──→ TC003 (查询合同列表)     ║
║       │                                       ║
║       └─────→ TC004 (修改合同)                ║
║                    │                          ║
║                    └──→ TC005 (删除合同)       ║
║                                              ║
║  TC002 (新增客户) ──→ TC006 (查询客户列表)     ║
║                                              ║
║  拓扑分层:                                    ║
║    Layer 1: TC001, TC002                     ║
║    Layer 2: TC003, TC004, TC006               ║
║    Layer 3: TC005                             ║
║                                              ║
║  表冲突检测: 无冲突                            ║
║  并行度: Layer 1 = 2, Layer 2 = 3, Layer 3 = 1║
╚══════════════════════════════════════════════╝
```

如果存在循环依赖，展示并报错：

```
❌ 检测到循环依赖: TC001 → TC003 → TC004 → TC001
   请检查用例文档中的依赖声明。
```

---

## 模式 3: `/sqltest verify <用例名>`

流程与 `run <用例名>` 相同，但输出结构化单行格式（`|` 分隔）：

```
PASS|TC001|POST /api/Contract/SaveContract|新增合同-校验落库|cnt=1|对抗通过
```

或：

```
FAIL|TC002|POST /api/Contract/SaveContract|合同编号必填校验|期望 success=false 实际 success=true
```

或：

```
WARN|TC001|POST /api/Contract/SaveContract|新增合同-校验落库|cnt=1|反向校验未通过
```

或：

```
SKIP|TC003|POST /api/Contract/GetList|查询合同列表|前置SQL返回空
```

格式：`<状态>|<用例名>|<接口路径>|<描述>|<详情>|<对抗验证结果>`

状态有四种：PASS / FAIL / WARN / SKIP

自动化 skill 可用 `|` 分割解析。

---

## 模式 4: `/sqltest exec "<SQL>"`

接收单条 SQL，直接调用 MCP 执行，返回原始 JSON 结果。

**DML 安全确认：** 非 SELECT 语句执行前展示 SQL 并询问 `⚠️ 非查询操作，是否执行？（y/n）`。SELECT 直接执行。

返回原始 MCP JSON，不添加任何格式。

---

## 模式 5: `/sqltest version`

读取 `.claude-plugin/marketplace.json`，提取 `metadata.version` 字段展示：

```
sqltest v2.0.0 (sql-skill)
```

如果 marketplace.json 不存在（非 GitHub 安装方式），从本 SKILL.md 的系统标记读取：

```
sqltest v2.0.0
```

---

## 报告汇总（run all / run <接口名> 模式专用）

全部用例执行完毕后展示增强汇总：

```
╔══════════════════════════════════════════════╗
║          /sqltest run all                    ║
╠══════════════════════════════════════════════╣
║                                              ║
║  Layer 1 (并行 2 用例):                       ║
║    ✅ TC001 新增合同-校验落库                  ║
║       ├─ 校验: cnt=1 符合预期                 ║
║       ╰─ 对抗: 通过                          ║
║    ✅ TC002 新增客户-校验落库                  ║
║       ╰─ 校验: cnt=1 符合预期                 ║
║                                              ║
║  Layer 2 (并行 3 用例):                       ║
║    ✅ TC003 查询合同列表                       ║
║       ╰─ 校验: response.success = true       ║
║    ⚠️  TC004 修改合同  WARN                   ║
║       ├─ 校验: name=修改后名称 符合预期        ║
║       ╰─ 对抗: 反向校验未通过                  ║
║                                              ║
║  Layer 3 (串行 1 用例):                       ║
║    ❌ TC005 删除合同  FAIL                    ║
║       原因: 期望 success=true，实际 false      ║
║                                              ║
╠══════════════════════════════════════════════╣
║  总计: 3 PASS / 1 WARN / 1 FAIL / 0 SKIP     ║
║  耗时: 16.2s（串行预计 26s，节省 38%）         ║
║  层数: 3  ·  并行峰值: 3 用例                  ║
╚══════════════════════════════════════════════╝
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

修改：`/sqltest config api-url http://localhost:6000`

---

## Token 获取配置

本 SKILL.md 顶部可标记 Token 获取方式：
```
<!-- token-url: POST https://d40.lis-china.com:18801/api/Account/GetIssueTokenInfo?userNo=LIS3&tokenGuid=123123&moduleId=H127&callModuleId=H127 -->
```

如果标记为 `(none)`，跳过 Token 获取。

修改：`/sqltest config token-url POST "<URL>"`

Token 响应要求：返回 JSON 格式 `{"success": true, "data": {"AccessToken": "xxx"}}`，自动提取 `data.AccessToken` 作为 Bearer token。

---

## 错误处理

| 错误场景 | 处理方式 |
|---|---|
| `自动化测试Sql文档.md` 不存在 | `❌ 未找到自动化测试Sql文档.md，请先创建测试用例文档` |
| 用例名/接口名未匹配到 | `❌ 未找到用例 "<name>"，请检查用例名是否正确` |
| 循环依赖检测 | `❌ 检测到循环依赖: TC001 → TC003 → TC001` |
| 声明依赖的用例不存在 | `❌ TC004 依赖的 TC009 不存在于文档中` |
| MCP 连接失败 | `❌ 数据库连接失败，请检查 /mcp 重连状态` |
| HTTP 请求超时 | `❌ HTTP 请求超时，请确认 API 服务已启动` |
| 前置 SQL 返回空 | `⚠️ SKIP`，不阻塞同层其他用例 |
| 清理 SQL 执行失败 | 输出警告但不影响用例结果判定 |
| Token 获取失败 | `❌ 获取 Token 失败 - <错误信息>`，跳过全部用例 |
| HTTP 返回 401 | 重新获取 token 并重试一次；仍 401 则 `❌ FAIL` |
