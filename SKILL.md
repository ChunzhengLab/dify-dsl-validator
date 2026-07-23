---
name: validate-dsl
description: Validate Dify app DSL YAML files against the App DSL 0.7.0 spec. Use whenever the user wants to check, validate, lint, or review a Dify DSL/YAML app file, asks why a DSL import fails or an imported app won't publish, asks "这个 DSL 对不对/能不能导入", or is hand-writing/generating DSL files and wants them verified — even if they just say "检查一下这个 yaml" and the file looks like a Dify app export (has kind: app / app.mode / workflow.graph).
---

# Validate Dify DSL

Two-layer validation: a deterministic script catches mechanical spec violations, then you apply judgment for what a script can't decide. The full spec is bundled at `references/dsl-spec.md` — consult it whenever a finding needs context (it has per-node field tables, sourceHandle rules, and the pitfall list).

## Why two layers

Dify's importer is lenient (almost anything imports into a draft) but the canvas checklist is strict (bad nodes can't publish). A file can therefore "import fine" yet be broken. The script encodes the publish-level rules; your judgment layer covers semantics the script can't see, like whether a `value_selector` names a field the upstream node actually outputs.

## Step 1 — Run the script

```bash
python3 <this-skill's-base-directory>/scripts/validate_dsl.py <file.yml>
```

(The skill's base directory is shown when this skill loads.) Add `--json` for machine-readable output. If PyYAML is missing, the script re-executes itself through `uv run --with pyyaml python` automatically — works from any directory.

Exit codes: `0` passed (warnings allowed), `1` spec errors found, `2` file unreadable / not YAML.

The script checks: envelope (version/kind/app.mode), per-mode required sections, node type validity (including rejecting UI-only placeholder nodes), per-node required fields and enums for all 23 checkable node types, edge integrity and branch sourceHandle rules (if-else / question-classifier / fail-branch), container (iteration/loop) placement rules, error-strategy/retry support, and `{{#...#}}` variable references against defined nodes, env and conversation variables.

## Step 2 — Judgment checks the script can't do

Read the DSL yourself and check, in rough priority order:

1. **Selector semantics** — `value_selector: [node_id, field]` must name a field the upstream node actually outputs (`llm` → `text`/`files`, `http-request` → `body`/`status_code`/`headers`/`files`, `code` → its declared `outputs` keys, `parameter-extractor` → its declared parameter names + `__is_success`/`__reason`). The script only verifies the node id exists.
2. **Reachability** — every non-entry node should be reachable from an entry node, and workflow outputs (`end`) reachable from the flow. Orphan islands import fine but never run.
3. **Dependencies** — every plugin-backed reference (model `provider`, `tool` node, trigger-plugin, marketplace tools) should have a matching entry in top-level `dependencies`. Identifiers look like `vendor/plugin:x.y.z@<sha256>` — hand-invented hashes are a red flag; they should be copied from a real export.
4. **Cross-environment portability** — `dataset_ids` are encrypted per-tenant (break on cross-tenant import); `agent` v2 nodes need top-level `agent_packages`; secret env vars export empty unless `include_secret` was used.
5. **Intent-level sanity** — prompt templates that reference variables which exist but are semantically wrong (e.g. iterating `sys.files` but reading `item` fields that won't exist), `if-else` conditions comparing incompatible types, memory enabled on a workflow (no conversation) app.

## Step 3 — Report

Structure the report exactly like this:

```
## 校验结果：<✅ 符合规范 | ❌ 不符合规范（N 个错误）>

### 错误（阻断发布/运行）
| 位置 | 问题 | 修复建议 |

### 警告（可导入但有隐患）
| 位置 | 问题 | 说明 |

### 语义建议（判断层发现）
- ...
```

- Report locations as `node[<id>]`/field paths as the script does, so the user can grep their YAML.
- Every error needs a concrete fix suggestion, not just a restatement.
- If the file failed to parse at all (exit 2), skip the table and explain the YAML syntax problem directly.
- When the DSL is valid, still mention notable warnings and the import-vs-publish distinction if relevant.

## Scope notes

- Covers app DSL (`kind: app`) for all six app modes; `kind: rag_pipeline` gets envelope + graph checks only (its spec is a separate 0.1.0 lineage).
- The spelling `is null`/`is not null` (frontend) vs `null`/`not null` (backend) is accepted both ways — flag neither.
- Position/width/height/viewport are cosmetic — never report layout data as a problem.
