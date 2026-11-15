# src/api — REST 骨架与横切契约(ticket #24,SPEC-500)

本包是 SPEC-500《REST API》(APPROVED 0.5.0)的工程落位。**规格权威在
`docs/spec/DVB-Sandbox-Spec-v0.4-Complete/docs/modules/Platform/SPEC-500-rest-api.md`**;
本 README 只做实现侧的速查与姿态说明,冲突时以规格为准。

SPEC-500 未在本文件之外指定版本策略/错误契约的文档位置,故落在包内 README
(实现选择,已在 #24 实施报告中作为假设登记)。

## 模块地图

| 模块 | 职责 |
|---|---|
| `api.app` | `create_app(*routers)` 应用工厂:中间件、错误 handlers 注册、路由挂载 |
| `api.versioning` | 冻结前缀 `API_V1_PREFIX="/api/v1"` 与 additive-only 策略常量 |
| `api.errors` | SPEC-500 §6 声明式异常→HTTP 映射表 `ERROR_HTTP_MAPPING` + 信封渲染 handlers |
| `api.dto` | Pydantic DTO 装配位(SPEC-500 §5):统一错误信封 `ErrorDetail` / `ErrorResponse` |
| `api.dto.generator` | SPEC-108 §4 JSON↔DTO 映射权威(GeneratorConfig/Program/ES,bytes→hex) |
| `api.dto.faults` | SPEC-204 §3 FaultDefinition/Activation 请求 DTO(fault_plan 入 run 请求体,ADR-0007) |
| `api.dto.runs` | runs 异步作业面:202 RunAccepted / RunStatus(TSRunResult 形) |
| `api.dto.sessions` | SPEC-200 §4 视图映射:创建请求 / SessionView / Snapshot(cursor 仅回显) / Validation |
| `api.dto.artifacts` | ArtifactMetaDTO(SPEC-502 §5 行,relative_path 不出绝对路径) |
| `api.routes` | SPEC-500 §4 路由面装配 `build_spec500_routers`(ticket #48) |
| `api.routes.sessions` | §4.2 八端点(接 SessionsPort → #41 SimulationRuntime) |
| `api.routes.runs` | §4.3 异步作业 202 + fault_plan prepare 绑定(接 RunsPort → #43 TSRuntime) |
| `api.routes.artifacts` | §4.6 元数据/下载(Range/206/416;接 ArtifactsPort → #42 read_by_artifact) |
| `api.routes.observation` | §4.5 SPEC-305 八端点原样落路由(501 待 M4 接线) |
| `api.routes.pending` | §4.1/§4.4/§4.7 冻结表 501 挂载点(topology/diagnosis/scenarios) |
| `application.errors` | 行别异常分类(表 key);api → application 是唯一层内依赖(ADR-0005 D4,import-linter C6) |
| `application.context` | `LOCAL_TENANT_ID="local"`(SPEC-500 §3 Q4 姿态) |

> 路由层纪律(ticket #48):`api.routes` 只含 Pydantic DTO + 结构化 Port
> (Protocol)+ application 错误类别;`simulation`/`ts`/`adapters` 真实后端由
> 组合根注入(import-linter C6 禁 api 直依赖),测试组合根见
> `tests/integration/api/rest_stack.py`(#49 ws_stack.py 同款姿态)。

## 版本策略(additive-only,SPEC-500 §3 逐字)

> 版本路径 `/api/v1` **冻结**:只增不改——新增可选字段为 additive;删字段、
> 改名、改枚举语义属破坏性变化,须开 `/api/v2`。

- `/api/v1` 内只允许增量演进:新增可选字段 = additive,可原位发布。
- 删字段、改字段名、改枚举语义 = 破坏性变化,禁止在 `/api/v1` 内发生,必须开 `/api/v2`。
- 新增错误码须过兼容性评审并登记进 SPEC-300 §13 错误码注册表。
- 工程强制:`create_app` 内所有路由(含传入 routers)统一经
  `API_V1_PREFIX` 挂载,`tests/integration/api/test_app_factory.py` 断言
  OpenAPI 全路径前缀不变量 + 骨架路径快照(SPEC-500 §10)。

## 错误响应契约(SPEC-500 §6 + SPEC-305 §7)

统一错误信封(全平台统一形状,SPEC-305 §7):

```json
{
  "error": {
    "error_code": "<REGISTRY_CODE>",
    "message": "…",
    "retryable": false,
    "details": {}
  },
  "request_id": "<hex>"
}
```

异常→HTTP 映射(声明式表 `api.errors.ERROR_HTTP_MAPPING`,逐行有集成测试):

| HTTP | 行别异常(application.errors) | SPEC-500 §6 场景 |
|---|---|---|
| 400 | `BadRequestError`(含框架 RequestValidationError 覆写,码 `REQUEST_BODY_INVALID`) | 请求体/信封非法 |
| 404 | `NotFoundError` | 未知 session/run/topology/artifact/scenario |
| 409 | `ConflictError` | 生命周期非法迁移、cursor/过滤器冲突、并发 run 冲突 |
| 413 | `PayloadTooLargeError` | 请求体过大 |
| 422 | `SemanticValidationError` | 语义非法(生成配置校验失败、fault prepare 拒绝、时钟域/范围语义非法) |
| 500 | (无行别)未处理异常回退,码 `INTERNAL_UNCLASSIFIED` | 未分类内部错误 |
| 503 | `ServiceUnavailableError` | 存储不可用、Artifact Storage 不可用、TSDuck 不可用 |

- FastAPI 默认把请求体校验失败渲染为 422;SPEC-500 §6 将 422 保留给语义
  非法,故骨架**覆写为 400**(规格裁决,非偏差)。
- 行别异常的 `error_code` 为必填(注册表权威 SPEC-300 §13;具体路由码随
  M3/M4 登记进注册表,骨架零默认路由码)。
- `request_id` 由 `RequestIdMiddleware` 逐请求生成(uuid4 hex,HTTP 层
  标识,不涉 TS 字节确定性纪律)。

## 部署姿态(SPEC-500 §3,ticket #13 Q4)

- **单机单用户**:服务绑定 `127.0.0.1`,无认证,`tenant_id` 恒为 `"local"`;
  token/多租户/远程访问为 non-goal。
- 工厂不内建任何鉴权中间件;绑定地址是 uvicorn 运行姿势(部署细节),
  不硬编码进 `create_app`:

  ```bash
  uvicorn --factory api.app:create_app --host 127.0.0.1 --port 8000
  ```

## 范围边界

本票(骨架 + 横切契约)不实现任何 SPEC-500 §4 业务路由:路由随 M3
(topologies/sessions/runs/diagnosis/artifacts/scenarios)与 M4(observation
查询)经 `create_app(*routers)` 接线。

**`GET /api/v1/version` 不在 SPEC-500 §4 冻结路由清单内**(review-fix #9
明示):它是骨架冒烟 seam——让冻结前缀行为与 Q4 单机姿态在 HTTP 面可断
言——由委派者裁定保留;M3 落地真实路由时将被移除或吸收进真实路由集。
依赖它的快照断言见
`tests/integration/api/test_app_factory.py::test_skeleton_openapi_path_snapshot`。
