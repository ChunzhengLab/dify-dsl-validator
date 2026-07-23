#!/usr/bin/env python3
"""Validate a Dify app DSL YAML file against the spec (App DSL 0.7.0).

Deterministic layer of the validate-dsl skill: catches mechanical spec
violations (structure, enums, required fields, edge/handle integrity,
container rules, variable references). Semantic judgment (e.g. whether a
value_selector points at a field the upstream node actually outputs) is
left to the model layer described in SKILL.md.

Usage:
    python3 validate_dsl.py <file.yml> [--json]

Exit codes: 0 = passed (warnings allowed), 1 = errors found, 2 = unusable input.

Requires PyYAML; when missing, the script re-executes itself through
`uv run --with pyyaml python`, which works from any directory.
"""

from __future__ import annotations

import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    script_path = globals().get("__file__")
    if os.environ.get("DSL_VALIDATE_REEXEC") == "1" or not script_path or not os.path.exists(script_path):
        print("ERROR: 缺少 PyYAML。请先 `pip install pyyaml`，或下载脚本后用 "
              "`uv run --with pyyaml python validate_dsl.py <file>` 运行。", file=sys.stderr)
        sys.exit(2)
    os.environ["DSL_VALIDATE_REEXEC"] = "1"
    os.execvp("uv", ["uv", "run", "--with", "pyyaml", "python", os.path.abspath(script_path), *sys.argv[1:]])

CURRENT_VERSION = (0, 7, 0)

APP_MODES = {"workflow", "advanced-chat", "chat", "completion", "agent-chat", "agent"}
GRAPH_MODES = {"workflow", "advanced-chat"}
MODEL_CONFIG_MODES = {"chat", "completion", "agent-chat"}

NODE_TYPES = {
    "start", "end", "answer", "llm", "knowledge-retrieval", "question-classifier",
    "if-else", "code", "template-transform", "http-request", "tool",
    "parameter-extractor", "iteration", "iteration-start", "loop", "loop-start",
    "loop-end", "variable-aggregator", "variable-assigner", "assigner",
    "document-extractor", "list-operator", "agent", "human-input",
    "trigger-schedule", "trigger-webhook", "trigger-plugin",
    "datasource", "knowledge-index",
}
UI_ONLY_TYPES = {"start-placeholder", "datasource-empty"}
ENTRY_TYPES = {"start", "trigger-schedule", "trigger-webhook", "trigger-plugin"}
TRIGGER_TYPES = {"trigger-schedule", "trigger-webhook", "trigger-plugin"}
RAG_ONLY_TYPES = {"datasource", "knowledge-index"}
CONTAINER_TYPES = {"iteration", "loop"}
CONTAINER_FORBIDDEN = {"human-input", "end", "answer", "iteration", "loop",
                       "datasource", "knowledge-index"} | TRIGGER_TYPES

COMPARISON_OPS = {
    "contains", "not contains", "start with", "end with", "is", "is not",
    "empty", "not empty", "in", "not in", "all of",
    "=", "≠", ">", "<", "≥", "≤", "null", "not null",
    "is null", "is not null",  # frontend spelling, accepted
    "exists", "not exists",
}
NO_VALUE_OPS = {"empty", "not empty", "null", "not null", "is null", "is not null",
                "exists", "not exists"}
ASSIGNER_OPS = {"over-write", "clear", "append", "extend", "set",
                "+=", "-=", "*=", "/=", "remove-first", "remove-last"}
ASSIGNER_NO_VALUE_OPS = {"clear", "remove-first", "remove-last"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
HTTP_BODY_TYPES = {"none", "form-data", "x-www-form-urlencoded", "raw-text", "json", "binary"}
AUTH_TYPES = {"no-auth", "api-key"}
AUTH_CONFIG_TYPES = {"basic", "bearer", "custom"}
CODE_LANGS = {"python3", "javascript"}
CODE_OUTPUT_TYPES = {"string", "number", "object", "boolean",
                     "array[string]", "array[number]", "array[object]", "array[boolean]"}
TOOL_PROVIDER_TYPES = {"plugin", "builtin", "workflow", "api", "app", "dataset-retrieval", "mcp"}
TOOL_INPUT_TYPES = {"mixed", "variable", "constant"}
START_VAR_TYPES = {"text-input", "paragraph", "select", "number", "checkbox",
                   "file", "file-list", "json_object", "external_data_tool"}
PARAM_EXTRACT_TYPES = {"string", "number", "boolean", "bool", "select",
                       "array[string]", "array[number]", "array[object]", "array[boolean]"}
ITER_ERROR_MODES = {"terminated", "continue-on-error", "remove-abnormal-output"}
ERROR_STRATEGIES = {"fail-branch", "default-value"}
ERROR_STRATEGY_NODES = {"llm", "tool", "http-request", "code", "agent"}
DELIVERY_TYPES = {"webapp", "email"}
SCHEDULE_FREQS = {"hourly", "daily", "weekly", "monthly"}
WEEKDAYS = {"sun", "mon", "tue", "wed", "thu", "fri", "sat"}
SYS_KEYS = {"query", "files", "conversation_id", "user_id", "dialogue_count",
            "app_id", "workflow_id", "workflow_run_id", "timestamp", "document_id",
            "original_document_id", "batch", "dataset_id", "datasource_type",
            "datasource_info", "invoke_from"}
RESERVED_REF_PREFIXES = {"sys", "env", "conversation", "rag"}

VAR_REF_RE = re.compile(r"\{\{#([^#{}]+)#\}\}")
ACTION_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Report:
    def __init__(self) -> None:
        self.errors: list[dict[str, str]] = []
        self.warnings: list[dict[str, str]] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append({"where": where, "msg": msg})

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append({"where": where, "msg": msg})


def is_selector(v: object) -> bool:
    return isinstance(v, list) and len(v) >= 1 and all(isinstance(x, str) for x in v)


def parse_version(s: object) -> tuple[int, int, int] | None:
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", s.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


# ---------------------------------------------------------------- per-node checks

def check_start(d: dict, w: str, rep: Report) -> None:
    for i, var in enumerate(d.get("variables") or []):
        vw = f"{w}.variables[{i}]"
        if not isinstance(var, dict):
            rep.error(vw, "变量项必须是映射")
            continue
        if not var.get("variable"):
            rep.error(vw, "缺少 variable（变量名）")
        if not var.get("label"):
            rep.error(vw, "缺少 label")
        vtype = var.get("type")
        if vtype not in START_VAR_TYPES:
            rep.error(vw, f"控件类型 {vtype!r} 不合法，应为 {sorted(START_VAR_TYPES)}")


def check_end(d: dict, w: str, rep: Report) -> None:
    outputs = d.get("outputs")
    if not outputs:
        rep.error(w, "end 节点 outputs 必须非空")
        return
    for i, out in enumerate(outputs):
        ow = f"{w}.outputs[{i}]"
        if not isinstance(out, dict) or not out.get("variable"):
            rep.error(ow, "缺少 variable（输出名）")
        if not is_selector((out or {}).get("value_selector")):
            rep.error(ow, "value_selector 必须是非空字符串数组")


def check_answer(d: dict, w: str, rep: Report) -> None:
    if not d.get("answer"):
        rep.error(w, "answer 节点的 answer 模板不能为空")


def _check_model(model: object, w: str, rep: Report) -> None:
    if not isinstance(model, dict):
        rep.error(w, "缺少 model 配置")
        return
    for key in ("provider", "name"):
        if not model.get(key):
            rep.error(w, f"model.{key} 必填")
    if model.get("mode") not in {"chat", "completion", None}:
        rep.warn(w, f"model.mode {model.get('mode')!r} 应为 chat 或 completion")


def check_llm(d: dict, w: str, rep: Report) -> None:
    _check_model(d.get("model"), w, rep)
    pt = d.get("prompt_template")
    memory_enabled = bool(d.get("memory"))
    if isinstance(pt, list):
        texts = [m.get("text", "") for m in pt if isinstance(m, dict)]
        if not memory_enabled and not any(t for t in texts):
            rep.error(w, "prompt_template 所有消息 text 均为空（未开 memory 时必须有内容）")
        for i, m in enumerate(pt):
            if isinstance(m, dict) and m.get("role") not in {"system", "user", "assistant", "tool"}:
                rep.error(f"{w}.prompt_template[{i}]", f"role {m.get('role')!r} 不合法")
    elif isinstance(pt, dict):
        if not memory_enabled and not pt.get("text"):
            rep.error(w, "prompt_template.text 为空")
    else:
        rep.error(w, "缺少 prompt_template（chat 形态为消息列表，completion 形态为 {text}）")
    context = d.get("context")
    if not isinstance(context, dict) or "enabled" not in context:
        rep.error(w, "缺少 context.enabled（必填，可为 false）")
    if d.get("reasoning_format") not in {None, "tagged", "separated"}:
        rep.warn(w, f"reasoning_format {d.get('reasoning_format')!r} 应为 tagged/separated")


def check_knowledge_retrieval(d: dict, w: str, rep: Report) -> None:
    if not d.get("dataset_ids"):
        rep.error(w, "dataset_ids 必须非空（注意：导出值是加密的，跨租户导入会失效）")
    mode = d.get("retrieval_mode")
    if mode not in {"single", "multiple"}:
        rep.error(w, f"retrieval_mode {mode!r} 应为 single 或 multiple")
    elif mode == "single":
        cfg = d.get("single_retrieval_config") or {}
        _check_model(cfg.get("model"), f"{w}.single_retrieval_config", rep)
    elif mode == "multiple":
        cfg = d.get("multiple_retrieval_config")
        if not isinstance(cfg, dict) or cfg.get("top_k") is None:
            rep.error(w, "multiple 模式需要 multiple_retrieval_config.top_k")


def check_question_classifier(d: dict, w: str, rep: Report) -> None:
    if not is_selector(d.get("query_variable_selector")):
        rep.error(w, "query_variable_selector 必填")
    _check_model(d.get("model"), w, rep)
    classes = d.get("classes")
    if not classes:
        rep.error(w, "classes 必须非空")
        return
    for i, c in enumerate(classes):
        cw = f"{w}.classes[{i}]"
        if not isinstance(c, dict) or not c.get("id"):
            rep.error(cw, "缺少 id（同时是出边的 sourceHandle）")
        if not (c or {}).get("name"):
            rep.error(cw, "缺少 name（分类描述）")


def check_parameter_extractor(d: dict, w: str, rep: Report) -> None:
    _check_model(d.get("model"), w, rep)
    if not d.get("query"):
        rep.error(w, "query（变量选择器）必填")
    params = d.get("parameters")
    if not params:
        rep.error(w, "parameters 必须非空")
        return
    for i, p in enumerate(params):
        pw = f"{w}.parameters[{i}]"
        if not isinstance(p, dict):
            rep.error(pw, "参数项必须是映射")
            continue
        name = p.get("name")
        if not name:
            rep.error(pw, "缺少 name")
        elif name in {"__reason", "__is_success"}:
            rep.error(pw, f"name 不得使用保留字 {name}")
        if p.get("type") not in PARAM_EXTRACT_TYPES:
            rep.error(pw, f"type {p.get('type')!r} 不合法")
        if not p.get("description"):
            rep.error(pw, "缺少 description")


def check_agent(d: dict, w: str, rep: Report) -> None:
    if d.get("agent_node_kind") == "dify_agent":
        if str(d.get("version")) != "2":
            rep.error(w, "新版 Agent 节点（agent_node_kind: dify_agent）的 version 必须为 '2'")
        return
    for key in ("agent_strategy_provider_name", "agent_strategy_name"):
        if not d.get(key):
            rep.error(w, f"{key} 必填（v1 Agent 策略节点）")
    _check_param_map(d.get("agent_parameters"), f"{w}.agent_parameters", rep, required=False)


def _check_param_map(params: object, w: str, rep: Report, required: bool) -> None:
    if params is None:
        if required:
            rep.error(w, "参数表必填（可为空映射 {}）")
        return
    if not isinstance(params, dict):
        rep.error(w, "参数表必须是映射")
        return
    for name, item in params.items():
        iw = f"{w}.{name}"
        if not isinstance(item, dict):
            rep.error(iw, "参数值必须是 {type, value} 结构")
            continue
        itype = item.get("type")
        if itype not in TOOL_INPUT_TYPES:
            rep.error(iw, f"type {itype!r} 应为 mixed/variable/constant")
            continue
        value = item.get("value")
        if itype == "mixed" and not isinstance(value, str):
            rep.error(iw, "mixed 类型的 value 必须是字符串模板")
        elif itype == "variable" and not is_selector(value):
            rep.error(iw, "variable 类型的 value 必须是变量选择器数组")


def check_tool(d: dict, w: str, rep: Report) -> None:
    for key in ("provider_id", "tool_name"):
        if not d.get(key):
            rep.error(w, f"{key} 必填")
    ptype = d.get("provider_type")
    if ptype not in TOOL_PROVIDER_TYPES:
        rep.error(w, f"provider_type {ptype!r} 不合法，应为 {sorted(TOOL_PROVIDER_TYPES)}")
    _check_param_map(d.get("tool_parameters"), f"{w}.tool_parameters", rep, required=False)


def _check_condition(c: object, cw: str, rep: Report) -> None:
    if not isinstance(c, dict):
        rep.error(cw, "条件必须是映射")
        return
    if not is_selector(c.get("variable_selector")):
        rep.error(cw, "variable_selector 必填")
    op = c.get("comparison_operator")
    if op not in COMPARISON_OPS:
        rep.error(cw, f"comparison_operator {op!r} 不在合法枚举内")
    elif op not in NO_VALUE_OPS:
        v = c.get("value")
        if v is None or v == "" or v == []:
            rep.error(cw, f"操作符 {op!r} 需要 value")


def check_if_else(d: dict, w: str, rep: Report) -> None:
    cases = d.get("cases")
    if not cases:
        if d.get("conditions"):
            rep.warn(w, "使用了旧版顶层 conditions 写法，建议迁移到 cases")
            return
        rep.error(w, "cases 必须非空")
        return
    for i, case in enumerate(cases):
        cw = f"{w}.cases[{i}]"
        if not isinstance(case, dict):
            rep.error(cw, "case 必须是映射")
            continue
        if not case.get("case_id"):
            rep.error(cw, "缺少 case_id（同时是出边 sourceHandle；IF 分支惯例为 'true'）")
        if case.get("logical_operator") not in {"and", "or"}:
            rep.error(cw, "logical_operator 应为 and/or")
        conds = case.get("conditions")
        if not conds:
            rep.error(cw, "conditions 必须非空")
            continue
        for j, c in enumerate(conds):
            _check_condition(c, f"{cw}.conditions[{j}]", rep)


def check_iteration(d: dict, w: str, rep: Report) -> None:
    if not is_selector(d.get("iterator_selector")):
        rep.error(w, "iterator_selector 必填（输入数组）")
    if not is_selector(d.get("output_selector")):
        rep.error(w, "output_selector 必填")
    mode = d.get("error_handle_mode")
    if mode is not None and mode not in ITER_ERROR_MODES:
        rep.error(w, f"error_handle_mode {mode!r} 应为 {sorted(ITER_ERROR_MODES)}")
    nums = d.get("parallel_nums")
    if nums is not None and (not isinstance(nums, int) or nums < 1):
        rep.error(w, "parallel_nums 必须是 ≥1 的整数")


def check_loop(d: dict, w: str, rep: Report) -> None:
    count = d.get("loop_count")
    if not isinstance(count, int) or count < 1:
        rep.error(w, "loop_count 必须是 ≥1 的整数")
    if d.get("logical_operator") not in {"and", "or"}:
        rep.error(w, "logical_operator 应为 and/or")
    for j, c in enumerate(d.get("break_conditions") or []):
        _check_condition(c, f"{w}.break_conditions[{j}]", rep)


def check_code(d: dict, w: str, rep: Report) -> None:
    if not d.get("code"):
        rep.error(w, "code 不能为空")
    lang = d.get("code_language")
    if lang not in CODE_LANGS:
        rep.error(w, f"code_language {lang!r} 仅支持 python3/javascript")
    outputs = d.get("outputs")
    if not isinstance(outputs, dict):
        rep.error(w, "outputs 必填（{输出名: {type}}）")
    else:
        for name, out in outputs.items():
            otype = (out or {}).get("type") if isinstance(out, dict) else None
            if otype not in CODE_OUTPUT_TYPES:
                rep.error(f"{w}.outputs.{name}",
                          f"type {otype!r} 不合法（code 节点不支持 file 等类型）")
    for i, v in enumerate(d.get("variables") or []):
        vw = f"{w}.variables[{i}]"
        if not isinstance(v, dict) or not v.get("variable") or not is_selector(v.get("value_selector")):
            rep.error(vw, "每个变量需要 variable + value_selector")


def check_template_transform(d: dict, w: str, rep: Report) -> None:
    if not d.get("template"):
        rep.error(w, "template 不能为空")
    for i, v in enumerate(d.get("variables") or []):
        vw = f"{w}.variables[{i}]"
        if not isinstance(v, dict) or not v.get("variable") or not is_selector(v.get("value_selector")):
            rep.error(vw, "每个变量需要 variable + value_selector")


def check_http_request(d: dict, w: str, rep: Report) -> None:
    if not d.get("url"):
        rep.error(w, "url 不能为空")
    method = d.get("method")
    if not isinstance(method, str) or method.lower() not in HTTP_METHODS:
        rep.error(w, f"method {method!r} 不合法")
    auth = d.get("authorization")
    if not isinstance(auth, dict):
        rep.error(w, "authorization 必填（最简 {type: no-auth}）")
    else:
        atype = auth.get("type")
        if atype not in AUTH_TYPES:
            rep.error(w, f"authorization.type {atype!r} 应为 no-auth/api-key")
        elif atype == "api-key":
            cfg = auth.get("config") or {}
            if cfg.get("type") not in AUTH_CONFIG_TYPES:
                rep.error(w, "authorization.config.type 应为 basic/bearer/custom")
            if not cfg.get("api_key"):
                rep.error(w, "authorization.config.api_key 必填")
    body = d.get("body")
    if isinstance(body, dict) and body.get("type") not in HTTP_BODY_TYPES:
        rep.error(w, f"body.type {body.get('type')!r} 不合法")


def check_variable_aggregator(d: dict, w: str, rep: Report) -> None:
    adv = d.get("advanced_settings") or {}
    if adv.get("group_enabled"):
        groups = adv.get("groups")
        if not groups:
            rep.error(w, "开启分组后 groups 必须非空")
            return
        for i, g in enumerate(groups):
            if not (g or {}).get("variables"):
                rep.error(f"{w}.groups[{i}]", "分组 variables 必须非空")
    elif not d.get("variables"):
        rep.error(w, "variables 必须非空（[[节点id, 字段], ...]）")


def check_assigner(d: dict, w: str, rep: Report) -> None:
    items = d.get("items")
    if not items:
        rep.error(w, "items 必须非空")
        return
    for i, item in enumerate(items):
        iw = f"{w}.items[{i}]"
        if not isinstance(item, dict):
            rep.error(iw, "赋值项必须是映射")
            continue
        if not is_selector(item.get("variable_selector")):
            rep.error(iw, "variable_selector 必填（目标变量）")
        op = item.get("operation")
        if op not in ASSIGNER_OPS:
            rep.error(iw, f"operation {op!r} 不在 11 种合法操作内")
        elif op not in ASSIGNER_NO_VALUE_OPS:
            if item.get("value") is None and item.get("input_type") != "variable":
                rep.error(iw, f"操作 {op!r} 需要 value")
        if item.get("input_type") not in {"variable", "constant", None}:
            rep.error(iw, "input_type 应为 variable/constant")


def check_document_extractor(d: dict, w: str, rep: Report) -> None:
    if not is_selector(d.get("variable_selector")):
        rep.error(w, "variable_selector 必填（file 或 array[file] 变量）")


def check_list_operator(d: dict, w: str, rep: Report) -> None:
    if not is_selector(d.get("variable")):
        rep.error(w, "variable 必填（数组变量选择器）")


def check_human_input(d: dict, w: str, rep: Report) -> None:
    seen_ids: set[str] = set()
    for i, action in enumerate(d.get("user_actions") or []):
        aw = f"{w}.user_actions[{i}]"
        aid = (action or {}).get("id", "")
        if not aid or len(aid) > 20 or not ACTION_ID_RE.fullmatch(aid):
            rep.error(aw, f"id {aid!r} 需为 ≤20 字符的标识符格式")
        elif aid in seen_ids:
            rep.error(aw, f"id {aid!r} 重复")
        seen_ids.add(aid)
        title = (action or {}).get("title", "")
        if not title or len(title) > 100:
            rep.error(aw, "title 必填且 ≤100 字符")
    for i, dm in enumerate(d.get("delivery_methods") or []):
        dw = f"{w}.delivery_methods[{i}]"
        dtype = (dm or {}).get("type")
        if dtype not in DELIVERY_TYPES:
            rep.error(dw, f"投递类型 {dtype!r} 后端仅支持 webapp/email")
        elif dtype == "email":
            cfg = (dm or {}).get("config") or {}
            if not cfg.get("subject"):
                rep.error(dw, "email 投递需要 config.subject")
            if "{{#url#}}" not in str(cfg.get("body", "")):
                rep.error(dw, "email 的 config.body 必须包含 {{#url#}} 占位符")


def check_trigger_schedule(d: dict, w: str, rep: Report) -> None:
    mode = d.get("mode", "visual")
    if mode == "cron":
        if not d.get("cron_expression"):
            rep.error(w, "cron 模式需要 cron_expression")
    elif mode == "visual":
        freq = d.get("frequency")
        if freq not in SCHEDULE_FREQS:
            rep.error(w, f"visual 模式的 frequency {freq!r} 应为 {sorted(SCHEDULE_FREQS)}")
        vc = d.get("visual_config") or {}
        if freq == "weekly" and not vc.get("weekdays"):
            rep.error(w, "weekly 需要 visual_config.weekdays")
        if freq == "monthly" and not vc.get("monthly_days"):
            rep.error(w, "monthly 需要 visual_config.monthly_days")
        bad_days = [x for x in (vc.get("weekdays") or []) if x not in WEEKDAYS]
        if bad_days:
            rep.error(w, f"weekdays 含非法值 {bad_days}（应为 sun..sat）")
    else:
        rep.error(w, f"mode {mode!r} 应为 visual/cron")


def check_trigger_webhook(d: dict, w: str, rep: Report) -> None:
    for i, p in enumerate(d.get("headers") or []):
        if (p or {}).get("type", "string") != "string":
            rep.error(f"{w}.headers[{i}]", "header 参数仅支持 string 类型")
    for i, p in enumerate(d.get("params") or []):
        if (p or {}).get("type", "string") not in {"string", "number", "boolean"}:
            rep.error(f"{w}.params[{i}]", "query 参数仅支持 string/number/boolean")
    allowed_body = {"string", "number", "boolean", "object", "file",
                    "array[string]", "array[number]", "array[boolean]", "array[object]"}
    for i, p in enumerate(d.get("body") or []):
        if (p or {}).get("type", "string") not in allowed_body:
            rep.error(f"{w}.body[{i}]", f"body 参数类型不合法（允许 {sorted(allowed_body)}）")


def check_trigger_plugin(d: dict, w: str, rep: Report) -> None:
    for key in ("plugin_id", "provider_id", "event_name", "subscription_id", "plugin_unique_identifier"):
        if not d.get(key):
            rep.error(w, f"{key} 必填")


NODE_CHECKS = {
    "start": check_start,
    "end": check_end,
    "answer": check_answer,
    "llm": check_llm,
    "knowledge-retrieval": check_knowledge_retrieval,
    "question-classifier": check_question_classifier,
    "parameter-extractor": check_parameter_extractor,
    "agent": check_agent,
    "tool": check_tool,
    "if-else": check_if_else,
    "iteration": check_iteration,
    "loop": check_loop,
    "code": check_code,
    "template-transform": check_template_transform,
    "http-request": check_http_request,
    "variable-aggregator": check_variable_aggregator,
    "assigner": check_assigner,
    "document-extractor": check_document_extractor,
    "list-operator": check_list_operator,
    "human-input": check_human_input,
    "trigger-schedule": check_trigger_schedule,
    "trigger-webhook": check_trigger_webhook,
    "trigger-plugin": check_trigger_plugin,
}


# ---------------------------------------------------------------- graph-level checks

def common_node_checks(data: dict, w: str, rep: Report) -> None:
    strategy = data.get("error_strategy")
    ntype = data.get("type")
    if strategy is not None:
        if strategy not in ERROR_STRATEGIES:
            rep.error(w, f"error_strategy {strategy!r} 应为 fail-branch/default-value")
        elif ntype not in ERROR_STRATEGY_NODES:
            rep.warn(w, f"节点类型 {ntype} 不支持 error_strategy（仅 llm/tool/http-request/code/agent）")
        if strategy == "default-value" and not data.get("default_value"):
            rep.error(w, "error_strategy: default-value 需要配套 default_value 列表")
    rc = data.get("retry_config")
    if isinstance(rc, dict) and rc.get("retry_enabled") and ntype not in {"llm", "tool", "http-request", "code"}:
        rep.warn(w, f"节点类型 {ntype} 不支持重试（仅 llm/tool/http-request/code）")


def scan_variable_refs(obj: object, node_ids: set[str], env_names: set[str],
                       conv_names: set[str], mode: str, w: str, rep: Report) -> None:
    if isinstance(obj, str):
        for ref in VAR_REF_RE.findall(obj):
            parts = ref.split(".")
            head = parts[0]
            if head in {"$output", "url"}:  # human-input 表单/邮件占位符
                continue
            if head == "sys":
                if len(parts) > 1 and parts[1] not in SYS_KEYS:
                    rep.warn(w, f"未知系统变量 sys.{parts[1]}")
            elif head == "env":
                if len(parts) > 1 and env_names and parts[1] not in env_names:
                    rep.warn(w, f"env.{parts[1]} 未在 environment_variables 中定义")
            elif head == "conversation":
                if mode == "workflow":
                    rep.warn(w, f"workflow 模式引用了会话变量 {{{{#{ref}#}}}}（仅 Chatflow 有意义）")
                elif len(parts) > 1 and conv_names and parts[1] not in conv_names:
                    rep.warn(w, f"conversation.{parts[1]} 未在 conversation_variables 中定义")
            elif head == "rag":
                pass
            elif head not in node_ids:
                rep.warn(w, f"变量引用 {{{{#{ref}#}}}} 的节点 id {head!r} 不存在")
    elif isinstance(obj, dict):
        for v in obj.values():
            scan_variable_refs(v, node_ids, env_names, conv_names, mode, w, rep)
    elif isinstance(obj, list):
        for v in obj:
            scan_variable_refs(v, node_ids, env_names, conv_names, mode, w, rep)


def validate_graph(workflow: dict, mode: str, rep: Report) -> None:
    graph = workflow.get("graph")
    if not isinstance(graph, dict):
        rep.error("workflow", "缺少 graph")
        return
    nodes = graph.get("nodes")
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        rep.error("workflow.graph", "nodes 必须是非空列表")
        return

    node_map: dict[str, dict] = {}
    for i, node in enumerate(nodes):
        w = f"nodes[{i}]"
        if not isinstance(node, dict):
            rep.error(w, "节点必须是映射")
            continue
        nid = node.get("id")
        if not nid:
            rep.error(w, "缺少 id")
            continue
        nid = str(nid)
        if nid in node_map:
            rep.error(w, f"节点 id {nid!r} 重复")
        node_map[nid] = node

    node_ids = set(node_map)
    env_names = {v.get("name") for v in (workflow.get("environment_variables") or []) if isinstance(v, dict)}
    conv_names = {v.get("name") for v in (workflow.get("conversation_variables") or []) if isinstance(v, dict)}

    entry_found = False
    for nid, node in node_map.items():
        data = node.get("data")
        w = f"node[{nid}]"
        if not isinstance(data, dict):
            rep.error(w, "缺少 data")
            continue
        ntype = data.get("type")
        if ntype in UI_ONLY_TYPES:
            rep.error(w, f"{ntype} 是纯前端占位节点，不允许出现在 DSL 中")
            continue
        if ntype not in NODE_TYPES:
            rep.error(w, f"未知节点类型 {ntype!r}")
            continue
        if ntype in RAG_ONLY_TYPES:
            rep.error(w, f"{ntype} 仅用于 kind: rag_pipeline 的知识流水线 DSL")
        if ntype in ENTRY_TYPES:
            entry_found = True
        if mode == "advanced-chat" and ntype in TRIGGER_TYPES | {"end"}:
            rep.error(w, f"{ntype} 仅 workflow 可用（Chatflow 用 answer 结尾）")
        if mode == "workflow" and ntype == "answer":
            rep.error(w, "answer 节点仅 Chatflow（advanced-chat）可用，workflow 用 end")

        parent_id = node.get("parentId")
        if parent_id:
            parent = node_map.get(str(parent_id))
            if parent is None:
                rep.error(w, f"parentId {parent_id!r} 不存在")
            else:
                ptype = (parent.get("data") or {}).get("type")
                if ptype not in CONTAINER_TYPES:
                    rep.error(w, f"parentId 指向的节点类型 {ptype!r} 不是 iteration/loop 容器")
                if ntype in CONTAINER_FORBIDDEN:
                    rep.error(w, f"{ntype} 节点不允许放进 iteration/loop 容器")

        checker = NODE_CHECKS.get(ntype)
        if checker:
            checker(data, w, rep)
        common_node_checks(data, w, rep)
        scan_variable_refs(data, node_ids, env_names, conv_names, mode, w, rep)

    starts = [n for n in node_map.values() if (n.get("data") or {}).get("type") == "start"]
    if len(starts) > 1:
        rep.error("graph", f"start 节点只能有一个，发现 {len(starts)} 个")
    if not entry_found:
        expected = "start 或 trigger-*" if mode == "workflow" else "start"
        rep.error("graph", f"缺少入口节点（{expected}）")
    if mode == "advanced-chat" and not any(
            (n.get("data") or {}).get("type") == "answer" for n in node_map.values()):
        rep.warn("graph", "Chatflow 通常需要至少一个 answer 节点输出回答")

    incoming: dict[str, int] = {}
    for i, edge in enumerate(edges):
        w = f"edges[{i}]"
        if not isinstance(edge, dict):
            rep.error(w, "边必须是映射")
            continue
        src, dst = str(edge.get("source", "")), str(edge.get("target", ""))
        if src not in node_map:
            rep.error(w, f"source {src!r} 不是已定义的节点 id")
            continue
        if dst not in node_map:
            rep.error(w, f"target {dst!r} 不是已定义的节点 id")
            continue
        incoming[dst] = incoming.get(dst, 0) + 1
        src_data = node_map[src].get("data") or {}
        src_type = src_data.get("type")
        handle = edge.get("sourceHandle") or "source"
        edata = edge.get("data") or {}
        for key, expect in (("sourceType", src_type), ("targetType", (node_map[dst].get("data") or {}).get("type"))):
            if edata.get(key) is not None and edata.get(key) != expect:
                rep.warn(w, f"data.{key}={edata.get(key)!r} 与节点实际类型 {expect!r} 不一致")

        if src_type == "if-else":
            valid = {"true", "false"} | {str(c.get("case_id")) for c in (src_data.get("cases") or []) if isinstance(c, dict)}
            if handle not in valid:
                rep.error(w, f"if-else 出边 sourceHandle {handle!r} 不在合法集合 {sorted(valid)}")
        elif src_type == "question-classifier":
            valid = {str(c.get("id")) for c in (src_data.get("classes") or []) if isinstance(c, dict)}
            if handle not in valid:
                rep.error(w, f"question-classifier 出边 sourceHandle {handle!r} 应为某个 class 的 id")
        elif handle == "fail-branch":
            if src_data.get("error_strategy") != "fail-branch":
                rep.warn(w, f"节点 {src} 未设置 error_strategy: fail-branch，却有 fail-branch 出边")
        elif handle not in {"source", "success-branch"}:
            rep.warn(w, f"非分支节点的 sourceHandle {handle!r} 不是常规值 source")

    for nid, node in node_map.items():
        ntype = (node.get("data") or {}).get("type")
        if ntype in ENTRY_TYPES and incoming.get(nid):
            rep.warn(f"node[{nid}]", f"入口节点 {ntype} 不应有入边")


# ---------------------------------------------------------------- top level

def validate(doc: dict, rep: Report) -> None:
    kind = doc.get("kind")
    if kind == "rag_pipeline":
        rep.warn("kind", "rag_pipeline DSL 是独立体系（版本 0.1.0），本脚本只做基础检查")
        if not isinstance(doc.get("rag_pipeline"), dict):
            rep.error("rag_pipeline", "kind: rag_pipeline 必须有 rag_pipeline 段")
        if isinstance(doc.get("workflow"), dict):
            validate_graph(doc["workflow"], "workflow", rep)
        return
    if kind != "app":
        rep.warn("kind", f"kind={kind!r}，导入时会被强制改为 'app'")

    ver = parse_version(doc.get("version"))
    if ver is None:
        rep.warn("version", f"version {doc.get('version')!r} 缺失或格式非 x.y.z，导入时按 0.1.0 处理")
    elif ver > CURRENT_VERSION or ver[0] < CURRENT_VERSION[0]:
        rep.warn("version", f"版本 {'.'.join(map(str, ver))} 与当前 0.7.0 不兼容，导入将进入 pending 待确认")
    elif ver[1] < CURRENT_VERSION[1]:
        rep.warn("version", f"版本 {'.'.join(map(str, ver))} 低于当前 0.7.0，导入成功但会带警告")

    app = doc.get("app")
    if not isinstance(app, dict):
        rep.error("app", "缺少 app 段（导入会直接失败）")
        return
    mode = app.get("mode")
    if mode not in APP_MODES:
        rep.error("app.mode", f"mode {mode!r} 不合法，应为 {sorted(APP_MODES)}（唯一导入硬必填字段）")
        return
    if not app.get("name"):
        rep.warn("app.name", "应用名为空")

    if mode in GRAPH_MODES:
        workflow = doc.get("workflow")
        if not isinstance(workflow, dict):
            rep.error("workflow", f"mode={mode} 必须有 workflow 段")
            return
        validate_graph(workflow, mode, rep)
    elif mode in MODEL_CONFIG_MODES:
        mc = doc.get("model_config")
        if not isinstance(mc, dict) or not mc:
            rep.error("model_config", f"mode={mode} 必须有非空 model_config 段")
            return
        model = mc.get("model")
        if not isinstance(model, dict) or not model.get("provider") or not model.get("name"):
            rep.warn("model_config.model", "缺少 provider/name，应用无法实际运行")
        if mode == "agent-chat" and not (mc.get("agent_mode") or {}).get("enabled"):
            rep.warn("model_config.agent_mode", "agent-chat 应用通常需要 agent_mode.enabled: true")
    elif mode == "agent":
        agent = doc.get("agent")
        packages = doc.get("agent_packages")
        if not isinstance(agent, dict) or not isinstance(packages, dict):
            rep.error("agent", "mode=agent 必须有 agent 和 agent_packages 段")
            return
        ref = agent.get("package_ref")
        if not ref or ref not in packages:
            rep.error("agent.package_ref", f"package_ref {ref!r} 必须是 agent_packages 的键")

    for i, dep in enumerate(doc.get("dependencies") or []):
        if not isinstance(dep, dict) or not isinstance(dep.get("value"), dict):
            rep.error(f"dependencies[{i}]", "依赖项需要 {type, value: {...identifier}} 结构")


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    path = args[0]
    try:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except OSError as e:
        print(f"ERROR: 无法读取文件: {e}", file=sys.stderr)
        return 2
    except yaml.YAMLError as e:
        print(f"ERROR: YAML 解析失败: {e}", file=sys.stderr)
        return 2
    if not isinstance(doc, dict):
        print("ERROR: DSL 顶层必须是 YAML 映射", file=sys.stderr)
        return 2

    rep = Report()
    validate(doc, rep)

    if as_json:
        print(json.dumps({"errors": rep.errors, "warnings": rep.warnings},
                         ensure_ascii=False, indent=2))
    else:
        for item in rep.errors:
            print(f"ERROR   [{item['where']}] {item['msg']}")
        for item in rep.warnings:
            print(f"WARNING [{item['where']}] {item['msg']}")
        print(f"\n结果: {len(rep.errors)} 个错误, {len(rep.warnings)} 个警告 — "
              + ("❌ 不符合规范" if rep.errors else "✅ 通过（机械检查层）"))
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
