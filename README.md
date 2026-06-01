# sql-skill

SQL 查询与数据库校验 Claude Code 技能集，基于 MCP (`@toolbox-sdk/server`) 操作主流关系型数据库。

## 安装

```bash
npx skills add Wjg-Ares/sql-skill
```

## 包含技能

| 技能 | 用途 |
|---|---|
| `/sql` | SQL 查询与表结构管理 — setup 配置、直接 SQL、自然语言查询、连接管理 |
| `/sqltest` | 数据库校验引擎（Harness）— DAG 依赖编排、并行分层执行、对抗验证、前置SQL→HTTP→校验SQL→清理 |

## 首次使用

```bash
# 配置数据库连接 + 导入表结构文档
/sql setup

# 查看可用连接
/sql list
```

## 快速上手

```bash
# 直接执行 SQL
/sql "SELECT * FROM cdc_base_data LIMIT 5"

# 自然语言查询（自动匹配表结构）
/sql 帮我查合同表及其所属客户信息

# 运行测试用例
/sqltest run all

# 执行单条校验 SQL（给自动化测试用）
/sqltest exec "SELECT COUNT(*) FROM CDC_CONTRACT_INFO WHERE CONTRACT_NO='KH-2024-0001'"
```

## 支持数据库

postgres / mysql / mssql / oracle / sqlite

## 前置依赖

- Node.js（MCP server 运行环境）
- Python 3（可选，仅 `/sql setup` 解析 .docx 表结构时需要）
