# Dify DSL Validator

本项目用于校验 [Dify](https://github.com/langgenius/dify) 应用 DSL 文件（YAML 格式）是否符合规范，同时附带一份根据 Dify 源码整理的 DSL 参考手册。

## 背景

Dify 的导入校验较为宽松，几乎任何结构的 YAML 文件都可以导入为应用草稿；但画布的发布校验十分严格。因此，一份能够成功导入的 DSL 文件，未必能够正常发布和运行。本工具将发布级别的校验规则提前执行，便于在导入之前、在持续集成流程中，或在批量生成 DSL 的场景下及早发现问题。

校验规则基于 App DSL 0.7.0 版本，由三处源码交叉验证得出：工作流引擎的数据模型、前端画布的校验逻辑，以及后端的导入导出服务。

## 使用方法

校验器是一个单文件脚本，除 PyYAML 外没有其他依赖。若系统缺少 PyYAML，脚本会自动通过 `uv run --with pyyaml` 重新执行，无需手动安装。

```bash
python3 scripts/validate_dsl.py app.yml           # 输出校验报告
python3 scripts/validate_dsl.py app.yml --json    # 输出 JSON 格式，便于集成到 CI 或脚本中
```

退出码含义：`0` 表示通过（允许存在警告），`1` 表示存在规范错误，`2` 表示文件无法读取或不是合法的 YAML。

可以先用自带的错误示例试运行，该文件埋设的 17 处错误应当全部被检出：

```bash
python3 scripts/validate_dsl.py examples/broken-sample.yml
```

## 校验范围

- 顶层结构：`version`、`kind`、`app.mode`，以及六种应用类型（workflow、Chatflow、Chatbot、文本生成、新旧两代 Agent）各自要求的段落
- 23 种工作流节点的必填字段与枚举取值，包括 if-else 的全部比较操作符、assigner 的 11 种赋值操作、HTTP 请求的鉴权方式与请求体类型、human-input 的表单与投递配置等
- 边（edges）的完整性，以及分支节点的连接规则（`true`、`false`、case_id、分类 id、`fail-branch`）
- iteration 与 loop 容器的节点放置规则，禁止出现纯前端占位节点
- 变量引用（`{{#...#}}`）的有效性：系统变量键名是否存在、环境变量与会话变量是否已定义、所引用的节点 id 是否存在
- 错误处理策略与重试配置的节点适用范围，以及 DSL 版本兼容性

## 规范手册

[`references/dsl-spec.md`](references/dsl-spec.md) 是一份完整的 Dify DSL 参考文档，内容包括：

- 各应用类型的文件结构，以及 `model_config` 段的全部字段
- 26 种节点的完整字段说明（类型、默认值、枚举取值）
- 变量系统：16 种值类型、4 个引用前缀、各模式下可用的系统变量
- 边的连接规则、容器子图的序列化方式、features 段字段、错误处理与并发选项
- 12 条常见问题清单，包括若干前后端实现不一致之处

手写或程序化生成 DSL 时，可作为查阅字典使用。

## 供 AI 编程 Agent 使用

本仓库可以直接作为 AI 编程 agent 的技能扩展使用，入口为 `SKILL.md`（该格式已被 Claude Code 等工具支持，也可作为通用的 agent 指令文档阅读）。工作方式为两层校验：脚本负责机械性检查，agent 负责脚本无法覆盖的语义判断（例如 value_selector 所指字段是否确为上游节点的输出、图的可达性、插件依赖标识符是否真实），最终输出结构化的校验报告。

以 Claude Code 为例：

```bash
# 全局安装，对所有项目生效
git clone git@github.com:ChunzhengLab/dify-dsl-validator.git ~/.claude/skills/validate-dsl

# 或安装到单个项目
git clone git@github.com:ChunzhengLab/dify-dsl-validator.git <项目路径>/.claude/skills/validate-dsl
```

安装后，向 agent 提出「检查这个 DSL」「这个 yaml 能否导入 Dify」等请求即可自动触发。其他支持自定义指令的 agent，可将 `SKILL.md` 的内容作为任务指令使用。

## 目录结构

```
scripts/validate_dsl.py   校验器脚本，可独立使用
references/dsl-spec.md    DSL 参考手册
examples/                 最小可用示例与错误测试样例
SKILL.md                  AI 编程 agent 的技能入口（可选）
```
