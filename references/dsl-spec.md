# Dify DSL 完全参考手册

> 依据源码整理（App DSL 版本 **0.7.0**），三方来源交叉验证：
> - 引擎数据模型：graphon 包（`nodes/*/entities.py` 的 Pydantic 模型）
> - Dify 后端：`api/core/workflow/nodes/`、`api/services/app_dsl_service.py`
> - 前端画布：`web/app/components/workflow/`（`types.ts`、`default.ts` 校验逻辑）
>
> 标注约定：**[必填]** = Pydantic 无默认值或前端 `checkValid` 拒绝为空；其余为可选，括号内是默认值。

---

## 目录

1. [总体结构与两层必填语义](#一总体结构)
2. [按 app.mode 的文件骨架](#二按-appmode-的文件骨架)
3. [model_config 段全字段（chat/completion/agent-chat）](#三model_config-段)
4. [graph 结构：节点外壳、edges、分支握手、容器子图](#四graph-结构详解)
5. [变量系统：类型、引用语法、系统变量、环境/会话变量](#五变量系统)
6. [节点完整字段参考（26 种）](#六节点完整字段参考)
7. [features 段全字段](#七features-段)
8. [错误处理与重试](#八错误处理与重试)
9. [并发选项](#九并发选项)
10. [坑与前后端不一致清单](#十坑与前后端不一致清单)

---

## 一、总体结构

### 两层「必填」语义

| 层级 | 时机 | 严格程度 |
|---|---|---|
| **导入校验**（后端 `app_dsl_service.py`） | 导入 YAML 时 | 宽松：只查 `app.mode` 和对应模式的顶层段落存在 |
| **画布校验**（前端 checklist / `checkValid`） | 保存/发布时 | 严格：不通过标红、无法发布 |

缺东少西的 DSL 往往**能导入**（进草稿）但**发不了布**。本手册的必填以后者为准。

### 版本兼容规则（`api/services/dsl_version.py`）

- 导入版本比当前**新**，或**主版本**比当前低 → pending（需用户确认）
- **次版本**比当前低 → 导入成功但带警告
- `version` 缺省自动补 `0.1.0`，`kind` 强制为 `app`

---

## 二、按 app.mode 的文件骨架

`app.mode` 是导入时唯一硬必填字段（缺失报 "loss app mode"）：

| app.mode | 应用类型 | 必需顶层段落 | 备注 |
|---|---|---|---|
| `workflow` | 工作流 | `workflow` | 可覆盖导入已有应用 |
| `advanced-chat` | Chatflow | `workflow` | 可覆盖导入 |
| `chat` | Chatbot | `model_config` | 无画布 |
| `completion` | 文本生成 | `model_config` | 无画布 |
| `agent-chat` | 旧版 Agent（ReAct） | `model_config` | Agent 配置在 `model_config.agent_mode` |
| `agent` | 新版 Agent | `agent` + `agent_packages` | 只能建新应用；需 `agent.manage` RBAC 权限 |
| —（`kind: rag_pipeline`） | 知识流水线 | `rag_pipeline` + `workflow` | 独立体系，版本号独立（0.1.0） |

```yaml
# ① workflow / advanced-chat
version: 0.7.0
kind: app
app: {name: ..., mode: workflow, icon: 🤖, icon_background: '#FFEAD5', description: ''}
dependencies: []           # 插件依赖，标识符从导出 DSL 里抄
workflow:
  graph: {nodes: [...], edges: [...], viewport: {x: 0, y: 0, zoom: 1}}
  features: {}
  environment_variables: []
  conversation_variables: []   # 仅 advanced-chat 有实际意义

# ② chat / completion / agent-chat
version: 0.7.0
kind: app
app: {name: ..., mode: chat}
model_config: {...}            # 见第三节

# ③ agent（新版）
version: 0.7.0
kind: app
app: {name: ..., mode: agent}
agent: {package_ref: agent_1}
agent_packages:
  agent_1:
    schema_version: 1
    metadata: {name, description, role, icon_type, icon, icon_background}
    soul: {...}                # Agent Soul 配置快照
    omitted_assets: []
```

注意：当 workflow/advanced-chat 的图里含新版 Agent 节点时，DSL 也会带顶层 `agent_packages` 段（`export_workflow_packages` 会把 DB 绑定剥离成可移植包，键为 `agent_N`）。

---

## 三、model_config 段

chat / completion / agent-chat 三种模式共用同一 schema（`api/models/model.py` `AppModelConfigDict`）。导入极宽容——所有字段都走 `.get()`，**唯一硬要求是段落本身非空**；但 `model.provider`+`model.name` 是让应用能跑的事实必填。

```yaml
model_config:
  model:                        # ModelConfig
    provider: langgenius/openai/openai
    name: gpt-4o
    mode: chat                  # chat | completion
    completion_params: {temperature: 0.7}
  pre_prompt: "系统提示词，可含 {{变量}}"
  prompt_type: simple           # simple | advanced（默认 simple）
  chat_prompt_config: {}        # advanced 模式的对话式 prompt
  completion_prompt_config: {}  # advanced 模式的补全式 prompt
  user_input_form: []           # 表单变量（控件类型同 start 节点 variables）
  dataset_query_variable: ''
  dataset_configs:              # 知识库引用
    retrieval_model: multiple   # + datasets 列表、rerank 配置
  agent_mode:                   # 仅 agent-chat 有意义
    enabled: true
    strategy: function_call     # 或 react
    tools: [{provider_id, tool_name, tool_parameters, ...}]
    prompt: null
  # 功能开关（画布应用的这些配置在 workflow.features 里）
  opening_statement: ''
  suggested_questions: []
  suggested_questions_after_answer: {enabled: false}
  speech_to_text: {enabled: false}
  text_to_speech: {enabled: false, voice: '', language: ''}
  retriever_resource: {enabled: true}
  more_like_this: {enabled: false}
  sensitive_word_avoidance: {enabled: false, type: '', config: {}}
  external_data_tools: []
  annotation_reply: {enabled: false}
  file_upload: {...}
```

导出时 `agent_mode.tools[]` 的 `credential_id` 会被剥离。

---

## 四、graph 结构详解

### 节点外壳（ReactFlow 层）

```yaml
- id: 任意字符串            # 全文一致即可；UI 生成的是时间戳
  type: custom              # 固定值；例外：迭代/循环入口是 custom-iteration-start / custom-loop-start
  position: {x: 0, y: 0}    # 仅画布显示；导入后可用「整理节点」自动排版
  width: 244                # 可省
  height: 90
  sourcePosition: right     # 可省
  targetPosition: left
  data: {type: llm, title: ..., ...}   # ← 真正的节点类型和配置
  # 容器子节点额外带：
  parentId: 容器节点id
  extent: parent
  zIndex: 1001
```

### data 里所有节点共有的字段（BaseNodeData，`extra="allow"`）

```
type: str [必填，节点类型字符串]
title: str ("")
desc: str|null (null)
version: str ("1")
error_strategy: "fail-branch"|"default-value"|null (null)   # 见第八节
default_value: [{key, type, value}]|null (null)
retry_config: {max_retries: 0, retry_interval: 0(毫秒), retry_enabled: false}
```

### edges 结构

```yaml
- id: "{source}-{sourceHandle}-{target}-{targetHandle}"   # 惯例格式，任意唯一串即可
  type: custom
  source: 上游节点id
  target: 下游节点id
  sourceHandle: source        # 分支节点见下表
  targetHandle: target        # 恒为 target
  data:
    sourceType: llm           # 两端节点的 data.type
    targetType: end
    isInIteration: false      # 容器内的边为 true 并带 iteration_id
    isInLoop: false           # 同上，loop_id
  zIndex: 0                   # 容器内为 1001
```

### sourceHandle 取值表（分支怎么连）

| 场景 | sourceHandle 值 |
|---|---|
| 普通节点成功出边 | `source` |
| if-else 的 IF 分支 | `true` |
| if-else 的 ELSE 分支 | `false` |
| if-else 的 ELIF 分支 | 该 case 的 `case_id`（uuid） |
| question-classifier 各分类 | 对应 class 的 `id` |
| 错误处理失败分支 | `fail-branch` |

### 容器子图（iteration / loop）

子节点序列化规则：

- `parentId: <容器id>`、`extent: parent`、`zIndex: 1001`
- `position` 是**相对容器**的坐标
- `data.isInIteration: true` + `data.iteration_id: <容器id>`（loop 则 `isInLoop`/`loop_id`）
- 容器内的边同样带这些标记
- 每个容器自动含一个入口节点：id 惯例为 `${容器id}start`，外壳 `type: custom-iteration-start`（loop 为 `custom-loop-start`），`data.type: iteration-start`/`loop-start`，不可选中/拖动
- 容器自身 `data.start_node_id` 指向该入口节点

---

## 五、变量系统

### 值类型体系（SegmentType 全枚举）

```
number  integer  float  string  boolean  object  secret  file  none  group
array[any]  array[string]  array[number]  array[object]  array[file]  array[boolean]
```

（前端展示时 integer/float 折叠为 number。）

### 引用语法

- 文本模板里：`{{#选择器#}}`，选择器 = 点分路径，匹配正则 `{{#节点id(.字段){1,10}#}}`
- 结构化字段里：`value_selector: [节点id, 字段, ...]`
- 四个保留前缀（作为「节点 id」使用）：

| 前缀 | 含义 | 示例 |
|---|---|---|
| `sys` | 系统变量 | `{{#sys.query#}}` |
| `env` | 环境变量 | `{{#env.API_KEY#}}` |
| `conversation` | 会话变量（Chatflow） | `{{#conversation.topic#}}` |
| `rag` | RAG 流水线节点 | `{{#rag.xxx#}}` |

- LLM 节点输出字段固定叫 `text`（另有 `files`、结构化输出等）。

### 系统变量（按 app mode 提供）

| 变量 | advanced-chat | workflow | rag-pipeline |
|---|:---:|:---:|:---:|
| `sys.query` | ✅ | ❌ | ❌ |
| `sys.files` | ✅ | ✅ | ✅ |
| `sys.conversation_id` | ✅ | ❌ | ❌ |
| `sys.dialogue_count` | ✅ | ❌ | ❌ |
| `sys.user_id` | ✅ | ✅ | ✅ |
| `sys.app_id` | ✅ | ✅ | ✅ |
| `sys.workflow_id` | ✅ | ✅ | ✅ |
| `sys.workflow_run_id` | ✅ | ✅ | ✅ |
| `sys.timestamp` | ❌ | ✅ | ❌ |
| `sys.document_id` / `original_document_id` / `batch` / `dataset_id` / `datasource_type` / `datasource_info` / `invoke_from` | ❌ | ❌ | ✅ |

### environment_variables / conversation_variables 条目格式

```yaml
- id: <uuid>              # 缺省自动生成
  name: MY_VAR            # [必填]
  description: ''
  selector: [env, MY_VAR] # 强制为 [env|conversation, name]
  value_type: string      # [必填] env 支持: string/secret/number/boolean/object/array[...]
  value: "..."            # [必填]
```

- `value_type: secret` 的值持久化时加密；导出不加 `include_secret` 时置为空串。
- conversation_variables 的 `description` 上限 255 字符。

---

## 六、节点完整字段参考

> 每节标题为 DSL 中的 `data.type` 值。省略 BaseNodeData 通用字段。

### 入口类

#### `start` — 用户输入表单

```
variables: VariableEntity[] ([])
  variable: str [必填]        # 变量名
  label: str [必填]
  description: str ("")
  type: [必填] text-input | paragraph | select | number | checkbox |
        file | file-list | json_object | external_data_tool
  required: bool (false)
  hide: bool (false)
  default: any (null)
  max_length: int|null
  options: str[] ([])          # select 用
  allowed_file_types: (image|document|audio|video|custom)[]     # file/file-list 用
  allowed_file_extensions: str[]
  allowed_file_upload_methods: (local_file|remote_url)[]
  json_schema: dict|null       # json_object 用，Draft7 JSON Schema
```

#### `trigger-schedule` — 定时触发（仅 workflow）

```
mode: str ("visual")           # visual | cron
frequency: str|null            # visual: hourly | daily | weekly | monthly
cron_expression: str|null      # cron 模式 [必填]
timezone: str ("UTC")          # IANA 时区
visual_config:
  on_minute: int (0)           # hourly：0-59
  time: str ("12:00 AM")       # daily/weekly/monthly：12 小时制
  weekdays: (sun|mon|tue|wed|thu|fri|sat)[]   # weekly [必填]
  monthly_days: (1-31 | "last")[]              # monthly [必填]
```

#### `trigger-webhook` — Webhook 触发（仅 workflow）

```
method: str ("get")            # get|post|head|patch|put|delete（入库转小写）
content_type: ("application/json") # 另支持 multipart/form-data、
                               # x-www-form-urlencoded、text/plain、octet-stream
headers: [{name [必填], type: "string"(仅此), required: false}]
params:  [{name [必填], type: string|number|boolean, required}]
body:    [{name [必填], type: string|number|boolean|object|file|array[...], required}]
status_code: int (200)         # 响应码
response_body: str ("")
timeout: int (30 秒)
# 前端另有 async_mode: true（收到即返回，后台执行）
```

#### `trigger-plugin` — 插件事件触发（仅 workflow）

```
plugin_id / provider_id / event_name / subscription_id / plugin_unique_identifier: str [全必填]
event_parameters: {参数名: {type: mixed|variable|constant, value}} ({})
  # 解析时只接受 constant
```

### 终点类

#### `end` — 工作流输出（仅 workflow）

```
outputs: [必填非空]
- variable: str [必填]         # 输出名
  value_type: (any)            # string|number|integer|boolean|object|file|array[...]|any
  value_selector: [节点id, 字段] [必填]
```

#### `answer` — 流式回答（仅 Chatflow）

```
answer: str [必填]             # 回答模板，可含 {{#节点.变量#}}，文件变量会渲染为图片/附件
```

### AI 类

#### `llm`

```
model: [必填]
  provider: str [必填]         # 如 langgenius/openai/openai
  name: str [必填]
  mode: chat|completion [必填]
  completion_params: dict ({})  # temperature 等
prompt_template: [必填] 二选一
  # chat 形态（列表）：
  - role: system|user|assistant|tool [必填]
    text: str ("")
    edition_type: basic|jinja2|null
    jinja2_text: str|null
  # completion 形态（单对象）：
  {text [必填], edition_type, jinja2_text}
prompt_config:
  jinja2_variables: [{variable, value_selector}] ([])
context: [必填]
  enabled: bool [必填]
  variable_selector: [选择器]|null
memory: null 或
  window: {enabled: bool [必填], size: int|null}
  query_prompt_template: str|null   # 需含 {{#sys.query#}}
  role_prefix: {user, assistant}|null
vision:
  enabled: bool (false)
  configs: {variable_selector: ([sys, files]), detail: low|high (high)}
structured_output: JSON Schema dict|null      # {schema: {type: object, properties, required, additionalProperties: false}}
structured_output_enabled: bool (false)       # 别名 structured_output_switch_on
reasoning_format: tagged|separated ("tagged")
# 输出: text、files、usage；开结构化输出后另有 structured_output
```

#### `knowledge-retrieval`

```
dataset_ids: str[] [必填]      # 导出时加密，同租户导入自动解密
retrieval_mode: single|multiple [必填]
query_variable_selector: 选择器|null
query_attachment_selector: 选择器|null
single_retrieval_config: {model: ModelConfig}       # single 模式 [必填]
multiple_retrieval_config:                          # multiple 模式
  top_k: int [必填]
  score_threshold: float|null
  reranking_enable: bool (true)
  reranking_mode: str ("reranking_model")           # 或 weighted_score
  reranking_model: {provider, model}|null
  weights:
    vector_setting: {vector_weight, embedding_provider_name, embedding_model_name}
    keyword_setting: {keyword_weight}
metadata_filtering_mode: disabled|automatic|manual ("disabled")
metadata_model_config: ModelConfig|null             # automatic 模式用
metadata_filtering_conditions:
  logical_operator: and|or ("and")
  conditions: [{name, comparison_operator, value}]
vision: 同 llm
# 输出: result (array[object])
```

#### `question-classifier`

```
query_variable_selector: 选择器 [必填]
model: ModelConfig [必填]
classes: [必填]
- id: str [必填]               # ← 即出边的 sourceHandle
  name: str [必填]             # 分类描述（给模型看）
  label: str ("")              # 展示名
instruction: str|null
memory / vision: 同 llm
# 输出: class_name、class_label
```

#### `parameter-extractor`

```
model: ModelConfig [必填]
query: 选择器 [必填]
parameters: [必填]
- name: str [必填]             # 不得为 __reason / __is_success
  type: [必填] string|number|boolean|array[string]|array[number]|array[object]|array[boolean]
        # 旧值 bool→boolean、select→string+枚举
  options: str[]|null          # 枚举选项
  description: str [必填]
  required: bool [必填]
instruction: str|null
reasoning_mode: function_call|prompt ("function_call")
memory / vision: 同 llm
# 输出: 各参数名 + __is_success + __reason
```

#### `agent`（v1，策略插件形态）

```
agent_strategy_provider_name: str [必填]
agent_strategy_name: str [必填]
agent_strategy_label: str [必填]
agent_parameters: {参数名: {type: mixed|variable|constant, value}} [必填]
  # 绑定工具时 value 为 ToolSelector:
  #   {provider_id, tool_name, tool_description, tool_configuration, tool_parameters, credential_id}
memory: 同 llm
tool_node_version: str|null    # null=旧版参数解析，新图写 '2'
```

#### `agent`（v2 形态，新版 Dify Agent 节点）

前端枚举叫 `agent-v2`，**DSL 里 `data.type` 仍是 `agent`**：

```
agent_node_kind: "dify_agent" [固定]
version: "2" [必须，validator 强制]
agent_binding:                  # extra 字段
  binding_type: roster_agent|inline_agent
  agent_id: str|null
  current_snapshot_id: str|null
agent_task: str                 # 任务描述/提示词
agent_declared_outputs:         # 声明式输出
- name [必填], type: string|number|boolean|object|array|file [必填]
  required?, description?, children?[], array_item?, file?{extensions,mime_types},
  check?{enabled,prompt,model_ref}, failure_strategy?{default_value,on_failure,retry}
# 默认输出: text(string)、files(array[file])、json(object)
# 真实绑定存 DB（WorkflowAgentNodeBinding）；跨环境迁移靠顶层 agent_packages
```

#### `tool`

```
provider_id: str [必填]
provider_type: [必填] plugin|builtin|workflow|api|app|dataset-retrieval|mcp
provider_name: str [必填]
tool_name: str [必填]
tool_label: str [必填]
tool_configurations: dict [必填]   # 授权/设置类参数（form 型），值须为标量或 dict
tool_parameters: [必填]            # 运行时参数（llm 型）
  {参数名: {type: mixed|variable|constant, value}}
  # mixed → value 是含 {{#var#}} 的模板串
  # variable → value 是 value_selector 数组
  # constant → value 是标量/dict/list
credential_id: str|null
plugin_unique_identifier: str|null
tool_node_version: str|null ('2')
# 输出: text、files、json（+ 工具自定义 output_schema）
```

### 逻辑控制类

#### `if-else`

```
cases: [必填]
- case_id: str [必填]          # 'true' 为 IF；ELIF 用 uuid；ELSE 分支不是 case，
                               # 而是 sourceHandle='false' 的出边
  logical_operator: and|or [必填]
  conditions: [必填非空]
  - variable_selector: [必填]
    comparison_operator: [必填] 见下
    value: str|str[]|bool|null
    sub_variable_condition:     # 数组元素/文件属性的子条件
      logical_operator: and|or
      conditions: [{key, comparison_operator, value}]
# 操作符全枚举：
#  字符串/数组: contains | not contains | start with | end with | is | is not |
#              empty | not empty | in | not in | all of
#  数字: = | ≠ | > | < | ≥ | ≤ | null | not null
#  文件: exists | not exists
```

#### `iteration`

```
iterator_selector: 选择器 [必填]     # 输入数组
output_selector: 选择器 [必填]       # 子图内要收集的输出
is_parallel: bool (false)
parallel_nums: int (10)
error_handle_mode: terminated | continue-on-error | remove-abnormal-output ("terminated")
flatten_output: bool (true)
start_node_id: str                   # 指向容器内的 iteration-start 节点
# 输出: output (array)
```

#### `loop`

```
loop_count: int [必填] (UI 默认 10)   # 最大循环次数
break_conditions: Condition[] [必填]  # 结构同 if-else 条件
logical_operator: and|or [必填]
loop_variables: ([])
- label: str [必填]
  var_type: string|number|object|boolean|array[string]|array[number]|array[object]|array[boolean]
  value_type: variable|constant
  value: any
outputs: dict ({})
start_node_id: str
# 容器内可放 loop-end 节点显式跳出
```

### 转换/工具类

#### `code`

```
variables: [{variable [必填], value_selector [必填]}] [必填]
code_language: python3|javascript [必填]
code: str [必填]
outputs: [必填] {输出名: {type, children|null}}
  # type 仅限: string|number|object|boolean|array[string]|array[number]|array[object]|array[boolean]
  # 没有 file —— code 节点不能产出文件
dependencies: [{name, version}]|null
```

#### `template-transform`

```
variables: [{variable, value_selector}] [必填]
template: str [必填]            # Jinja2
# 输出: output (string)，上限 40 万字符（可配）
```

#### `http-request`

```
method: [必填] get|post|put|patch|delete|head|options（大小写均可）
url: str [必填]
authorization: [必填]
  type: no-auth|api-key [必填]
  config:                        # api-key 时必填
    type: basic|bearer|custom [必填]
    api_key: str [必填]
    header: str ("")             # custom 时的头名
headers: str [必填，可空串]      # "Key: Value" 按行
params: str [必填，可空串]       # "key: value" 按行
body:
  type: none|form-data|x-www-form-urlencoded|raw-text|json|binary [必填]
  data: [{key (""), type: text|file [必填], value (""), file: 选择器 ([])}]
timeout: {connect, read, write}|null   # 上限 10/600/600 秒
ssl_verify: bool|null (true)
# 默认自带重试（retry_enabled: true, max_retries: 3）
# 限制: 二进制响应 ≤10MiB，文本 ≤1MiB
# 输出: status_code、body、headers、files
```

#### `variable-aggregator`（变量聚合，取首个非空）

```
output_type: str [必填]          # any 或具体类型
variables: [[选择器], ...] [必填非空]
advanced_settings:
  group_enabled: bool [必填]
  groups: [{group_name, output_type, variables: [[选择器]]}] [开组时必填非空]
# 旧版别名 data.type: variable-assigner（勿手写）
```

#### `assigner`（变量赋值 v2，写会话/循环变量）

```
version: "2"
items: [必填]
- variable_selector: [必填]      # 目标（conversation.* 或循环变量）
  input_type: variable|constant [必填]
  operation: [必填] over-write|clear|append|extend|set|+=|-=|*=|/=|remove-first|remove-last
  value: any                     # clear/remove-* 不需要
# 旧版 v1（data.type: variable-assigner + write_mode: over-write|append|clear）已废弃
```

#### `document-extractor`

```
variable_selector: [必填]        # file 或 array[file] 变量
is_array_file: bool (false)
# 输出: text (string 或 array[string])
```

#### `list-operator`

```
variable: 选择器 [必填]
filter_by:
  enabled: bool (false)
  conditions: [{key (""), comparison_operator ("contains"), value}]
  # 操作符：字符串 contains/not contains/start with/end with/is/is not/in/not in/empty/not empty
  #        数字 = ≠ < > ≥ ≤
order_by: {enabled (false), key (""), value: asc|desc ("asc")}
limit: {enabled (false), size: int}
extract_by: {enabled (false), serial: str ("1")}   # 取第 N 个
# 输出: result、first_record、last_record
```

### 人机交互

#### `human-input`（两种画布模式都可用；不能放进容器）

```
form_content: str ("")           # Markdown 表单模板；{{#$output.字段#}} 声明输出变量
                                 # 字段名规则 [a-zA-Z_][a-zA-Z0-9_]{0,29}
inputs: ([])                     # 表单控件，4 种（按 type 判别）
- output_variable_name: str [必填，不可重复]
  type: paragraph → default: {type: variable|constant, selector|value}
        select    → option_source: {type, selector|value: str[]} [必填]
        file / file-list → allowed_file_types/extensions/upload_methods(local_file|remote_url)
                           file-list 另有 number_limits (0)
user_actions: ([])               # 按钮
- id: str [必填，≤20 字符，标识符格式，不可重复]
  title: str [必填，≤100]
  button_style: primary|default|accent|ghost ("default")
timeout: int (36)
timeout_unit: hour|day ("hour")
delivery_methods:                # 投递渠道（payload 键）
- type: webapp → config: {}
  type: email  → config:
    recipients: {include_bound_group: bool, items: [{type: member, reference_id} | {type: external, email}]}
    subject: str [必填]
    body: str [必填，需含 {{#url#}}]
    debug_mode: bool (false)
# 后端仅支持 webapp/email（前端枚举里的 slack/teams/discord 未实现）
```

### RAG Pipeline 专属（kind: rag_pipeline）

#### `datasource`

```
plugin_id / provider_name / provider_type: str [全必填]
datasource_name: str ("local_file")
datasource_parameters / datasource_configurations: dict
plugin_unique_identifier: str|null
```

#### `knowledge-index`

```
chunk_structure: str [必填]
index_chunk_variable_selector: [必填]
indexing_technique / summary_index_setting: 可选
```

### 纯 UI 占位（勿手写）

`start-placeholder`、`datasource-empty` —— 只存在于前端画布，DSL 里出现即错。

---

## 七、features 段

`workflow.features` 全字段（画布应用）。chat/completion 的同类配置在 `model_config` 顶层（见第三节）。

```yaml
features:
  file_upload:
    enabled: bool
    allowed_file_types: [image, document, audio, video, custom]
    allowed_file_extensions: ['.jpg', ...]
    allowed_file_upload_methods: [local_file, remote_url]
    number_limits: int
    image:                       # 旧版兼容子对象，导入时归一化
      {enabled, detail: low|high, number_limits, transfer_methods}
    fileUploadConfig:            # 各类大小上限（MB）
      {file_size_limit, image_file_size_limit, audio_file_size_limit,
       video_file_size_limit, batch_count_limit, workflow_file_upload_limit}
  opening_statement: str          # 仅 Chatflow
  suggested_questions: [str]      # 仅 Chatflow
  suggested_questions_after_answer: {enabled}   # 仅 Chatflow
  retriever_resource: {enabled}   # 引用与归属
  sensitive_word_avoidance: {enabled, type: keywords|openai_moderation|api, config}
  speech_to_text: {enabled}       # 仅 Chatflow
  text_to_speech: {enabled, voice, language}    # 仅 Chatflow
  more_like_this: {enabled}
  annotation_reply: {enabled, score_threshold?, embedding_model?}
```

---

## 八、错误处理与重试

### 支持范围（前端 gating）

- **error_strategy**（错误策略）：LLM、Tool、HTTP Request、Code、Agent（两代）
- **retry_config**（重试）：LLM、Tool、HTTP Request、Code

### 写法

```yaml
data:
  # 方式一：失败走专用分支
  error_strategy: fail-branch
  # → 另拉一条 sourceHandle: fail-branch 的出边接失败处理逻辑
  #   失败分支里可用 error_message / error_type 变量

  # 方式二：失败时给默认值继续
  error_strategy: default-value
  default_value:
  - key: text                    # 对应该节点的输出字段
    type: string                 # string|number|object|array[number]|array[string]|array[object]|array[file]
    value: "兜底内容"

  # 重试（可与上面组合；先重试，重试穷尽再走错误策略）
  retry_config:
    retry_enabled: true
    max_retries: 3               # http-request 默认就是 3
    retry_interval: 1000         # 毫秒
```

容器级错误处理是另一套：iteration 的 `error_handle_mode`（terminated / continue-on-error / remove-abnormal-output）。

---

## 九、并发选项

**DSL 层：**

- **分支并行（隐式）**：一个节点拉多条出边即并行执行，无开关；用 `variable-aggregator` 汇合。
- **iteration 显式并行**：`is_parallel: true` + `parallel_nums`（默认 10，前端上限由 `MAX_PARALLEL_LIMIT` 环境变量控制）+ `error_handle_mode`。
- **loop 无并行**（迭代间有顺序依赖）。
- **trigger-webhook 的 async_mode**（默认 true）：请求层异步。

**部署层（环境变量，`api/configs/feature/__init__.py`）：**

引擎按运行实例维护动态线程池：`GRAPH_ENGINE_MIN_WORKERS`（默认 3）起步，就绪队列深度超 `GRAPH_ENGINE_SCALE_UP_THRESHOLD`（默认 3）扩容至 `GRAPH_ENGINE_MAX_WORKERS`（默认 10），空闲 `GRAPH_ENGINE_SCALE_DOWN_IDLE_TIME`（默认 5s）后缩容。

注意乘积关系：DSL 里开满并行迭代，吞吐仍受 worker 池上限约束；要真跑满需同时调大 `GRAPH_ENGINE_MAX_WORKERS`。

---

## 十、坑与前后端不一致清单

1. **`agent-v2` 不是 DSL 类型**：新版 Agent 节点序列化为 `type: agent` + `agent_node_kind: dify_agent` + `version: '2'`；跨环境迁移依赖顶层 `agent_packages`。
2. **三个名字相近的变量节点**：`variable-aggregator`（聚合，现行）、`variable-assigner`（聚合**旧版别名**）、`assigner`（赋值）。手写只用前者和后者。
3. **if-else 的 null 操作符拼写**：后端是 `null` / `not null`，前端枚举是 `is null` / `is not null`——以导出 DSL 实际值为准。
4. **human-input 投递渠道**：前端枚举列了 slack/teams/discord，后端只实现了 `webapp` 和 `email`。
5. **code 节点语言**：后端只接受 `python3`/`javascript`（枚举里的 jinja2 会被拒）；且 outputs 不支持 file 类型。
6. **`dependencies` 插件标识符**（`vendor/plugin:版本@哈希`）别手编，从导出 DSL 里抄；模型 provider 也是插件。
7. **导入 ≠ 生效**：workflow/chatflow 导入进草稿，需发布；`difyctl run app` 跑的是已发布版本。
8. **覆盖导入**只支持 workflow / advanced-chat。
9. **dataset_ids 是加密导出的**：跨租户导入会解密失败被剔除，需重新绑知识库。
10. **坐标不用手摆**：`position` 全填 0，导入后用画布「整理节点」（ELK 自动布局）。
11. **iteration/loop 的入口节点**外壳 `type` 是 `custom-iteration-start`/`custom-loop-start`，不是 `custom`；子节点坐标是相对容器的。
12. **秘密值**：环境变量 `secret` 类型导出默认置空（除非 `include_secret`），导入后需重新填。
