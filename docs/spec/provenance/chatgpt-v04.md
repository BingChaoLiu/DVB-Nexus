\# \*\*DVB 数字沙盘 Spec v0.4 — 技术架构设计\*\*







架构方向已确定



MVP 设计阶段







我建议将 v0.4 的技术定位定为：



\*\*Python 驱动的混合式 DVB 仿真平台，以 MPEG-TS 为第一条真实数据链路，以 TSDuck 作为外部协议验证与处理引擎。\*\*



三个架构选择确定之后，我认为有一个原则必须坚持：



> 不要把 Sandbox 理解成一个 Mock 数据生成器，而应该把它设计成一个真正能够产生协议数据、观察协议数据、注入协议故障并验证故障结果的运行时环境。



这会影响后续所有模块的边界。



\## \*\*1. 确定 v0.4 的技术架构基线\*\*



| 架构维度  | 最终选择               | 说明                          |

| ----- | ------------------ | --------------------------- |

| 仿真引擎  | Hybrid             | L0 状态仿真 + L1 真实 TS 生成       |

| 第一优先级 | MPEG-TS            | 首先打通 PAT、PMT、PID、PES、PCR、CC |

| 后端语言  | Python             | 控制面、拓扑、仿真编排、诊断              |

| TS 分析 | TSDuck             | 真实码流处理、外部验证                 |

| 前端    | React + TypeScript | 拓扑编辑、码流分析、时间轴               |

| 通信    | REST + WebSocket   | 控制请求与实时事件                   |

| 数据存储  | SQLite + 文件系统      | 配置、实验、运行记录、TS 文件            |



这里有一个值得特别说明的地方：TSDuck 不只是 CLI 工具，它也提供 C++ 库和 Python 高层绑定。不过 Python 绑定只覆盖部分高层功能，并不等价于完整的 C++ API。



\[image](https://www.google.com/s2/favicons?domain=https://tsduck.io\\\&sz=32)



tsduck.io+2







因此我的建议是：



\- Python 是系统主语言。

\- MVP 阶段通过独立 TSDuck Worker 调用 CLI。

\- 将来有明确的性能或功能需求，再考虑使用 TSDuck Python Binding。

\- 不要在项目初期引入自行维护的 C++/Python ABI。



\## \*\*2. 整体架构：从双引擎变成五层结构\*\*



我建议将原来的四层架构调整为五层。



\*\*L5 · Presentation Layer\*\*



React / TypeScript



Topology Editor



Stream Monitor



CLI Console



Training Lab



REST / WebSocket



\*\*L4 · Application Service Layer\*\*



FastAPI · Session Manager · API Gateway · Snapshot Aggregator



\*\*L3 · Domain \& Diagnosis Layer\*\*



Topology Validator · Topology Evaluator · Observation Model · Diagnosis Engine · Fault Scenario Manager



\*\*L2 · Simulation Runtime Layer\*\*



\*\*L0 State Engine\*\*



参数传播、链路求值、虚拟状态



\*\*L1 TS Engine\*\*



Packet、Section、PES、PCR 生成



\*\*L1 · Data Plane \& Integration\*\*



TS Generator



TSDuck Worker



File Input / Output



Real DVB Adapter（后续）



这里需要澄清：上图中的 L1 是架构层级，TS Engine 中的 L1 则是前面约定的真实 TS 仿真等级，两者不要在代码命名中混用。我建议代码里将仿真等级命名为 `SIM\_STATE` 和 `SIM\_TS`。



\### \*\*为什么是这种分层？\*\*



因为未来我们会遇到这样的情况：



同一个拓扑，在不同模式下运行。



```

&#x20;                  Same Topology

&#x20;                        |

&#x20;            +-----------+-----------+

&#x20;            |                       |

&#x20;            v                       v

&#x20;       State Runtime             TS Runtime

&#x20;            |                       |

&#x20;            v                       v

&#x20;      Virtual Metrics          Real TS Packets

&#x20;            |                       |

&#x20;            v                       v

&#x20;      Simulated Events          Parsed Events

&#x20;            |                       |

&#x20;            +-----------+-----------+

&#x20;                        |

&#x20;                        v

&#x20;                Observation Model

&#x20;                        |

&#x20;                        v

&#x20;                 Diagnosis Engine

&#x20;                        |

&#x20;                        v

&#x20;                       UI

```



也就是说，L0 与 L1 是两种数据产生方式，而不是两套完全不同的业务系统。



\## \*\*3. 模块边界：采用 Modular Monolith，而不是微服务\*\*



这里我有一个比较明确的建议：



\*\*第一版使用 Python Modular Monolith + 独立 Worker Process。\*\*



不要把每个模块都拆成一个 Docker 服务，也不要为了追求高性能过早引入 Redis、Kafka 或消息队列集群。



这是一个本地运行、单机使用的工程工具，第一阶段更重要的是易调试、可复现、模块职责清晰。



\### \*\*3.1 建议的模块划分\*\*



| 模块             | Python Package | 核心职责                  |

| -------------- | -------------- | --------------------- |

| API Service    | `api`          | HTTP、WebSocket        |

| Application    | `application`  | 用例编排、Session 生命周期     |

| Topology       | `topology`     | 拓扑定义、端口检查、图计算         |

| Simulation     | `simulation`   | L0/L1 仿真运行时           |

| TS Core        | `ts`           | TS Packet、PSI、PES、PCR |

| Fault Lab      | `faults`       | 故障场景、注入和评测            |

| Observation    | `observation`  | 事件、指标、证据              |

| Diagnosis      | `diagnosis`    | 错误关联、根因候选             |

| TSDuck Adapter | `tsduck`       | 调用 TSDuck、结果解析        |

| Persistence    | `storage`      | SQLite、TS 文件、实验记录     |

| Knowledge      | `knowledge`    | 协议知识卡片、标准引用           |



我建议进一步约定模块依赖：



```

api

&#x20;|

&#x20;v

application

&#x20;|

&#x20;+---------- topology

&#x20;|

&#x20;+---------- simulation ------ ts

&#x20;|                   |

&#x20;|                   +-------- faults

&#x20;|

&#x20;+---------- observation

&#x20;|

&#x20;+---------- diagnosis

&#x20;|

&#x20;+---------- tsduck

&#x20;|

&#x20;+---------- storage

```



几个边界需要特别注意：



\- `simulation` 不应该直接操作 SQLite。

\- `ts` 不应该依赖 FastAPI。

\- `diagnosis` 不应该直接操作 TSDuck 进程。

\- `faults` 负责定义故障，而不是直接改变 UI 状态。

\- `observation` 是所有模块交换运行结果的统一数据接口。



\### \*\*3.2 建议的代码目录\*\*



```

dvb-sandbox/

│

├── backend/

│   ├── pyproject.toml

│   │

│   └── app/

│       ├── main.py

│       ├── bootstrap.py

│       │

│       ├── api/

│       │   ├── routers/

│       │   │   ├── topology.py

│       │   │   ├── sessions.py

│       │   │   ├── simulation.py

│       │   │   ├── analysis.py

│       │   │   └── labs.py

│       │   │

│       │   └── websocket/

│       │       └── event\_gateway.py

│       │

│       ├── application/

│       │   ├── session\_manager.py

│       │   ├── simulation\_service.py

│       │   └── lab\_service.py

│       │

│       ├── domain/

│       │   ├── topology/

│       │   │   ├── models.py

│       │   │   ├── validator.py

│       │   │   └── evaluator.py

│       │   │

│       │   ├── observation/

│       │   │   ├── events.py

│       │   │   ├── metrics.py

│       │   │   └── evidence.py

│       │   │

│       │   └── diagnosis/

│       │       ├── engine.py

│       │       └── rules.py

│       │

│       ├── simulation/

│       │   ├── runtime.py

│       │   ├── clock.py

│       │   ├── state\_engine.py

│       │   └── ts\_engine.py

│       │

│       ├── ts/

│       │   ├── packet.py

│       │   ├── header.py

│       │   ├── section.py

│       │   ├── crc.py

│       │   ├── packetizer.py

│       │   ├── pes.py

│       │   ├── pcr.py

│       │   ├── mux.py

│       │   └── generator.py

│       │

│       ├── faults/

│       │   ├── base.py

│       │   ├── injector.py

│       │   ├── registry.py

│       │   └── scenarios/

│       │       ├── pat\_missing.py

│       │       ├── pmt\_error.py

│       │       └── cc\_discontinuity.py

│       │

│       ├── adapters/

│       │   ├── tsduck/

│       │   │   ├── client.py

│       │   │   ├── process.py

│       │   │   └── report\_parser.py

│       │   │

│       │   └── storage/

│       │       ├── database.py

│       │       └── artifact\_store.py

│       │

│       ├── knowledge/

│       │   ├── registry.py

│       │   └── standards.py

│       │

│       └── workers/

│           └── tsduck\_worker.py

│

├── frontend/

│   ├── src/

│   │   ├── topology/

│   │   ├── stream/

│   │   ├── packet-inspector/

│   │   ├── terminal/

│   │   ├── lab/

│   │   └── knowledge/

│   │

│   └── package.json

│

├── scenarios/

│   ├── beginner/

│   └── intermediate/

│

├── tests/

│   ├── unit/

│   ├── integration/

│   ├── conformance/

│   └── scenarios/

│

└── data/

&#x20;   ├── streams/

&#x20;   ├── sessions/

&#x20;   └── evidence/

```



这套目录有意把 `ts/` 单独拿出来。未来无论是 Python 自研解析器，还是增加 C++ 高性能模块，都可以保留上层接口不变。



\## \*\*4. 混合仿真引擎：两个 Runtime，一个统一事件接口\*\*



这是整套架构的核心。



\### \*\*4.1 L0：状态驱动仿真\*\*



L0 不生成真实 TS 数据，而是模拟设备和协议链路中的状态传播。



例如：



```

Virtual TS Source

&#x20;      |

&#x20;      v

Virtual Demux

&#x20;      |

&#x20;      v

Virtual Service

&#x20;      |

&#x20;      v

Virtual Decoder

```



用户把 Demux 配置成错误的 PID：



```

source.video\_pid = 0x0101demux.video\_pid = 0x0102

```



L0 求值后：



```

{

&#x20; "nodes": \[

&#x20;   {

&#x20;     "id": "source",

&#x20;     "health": "ok"

&#x20;   },

&#x20;   {

&#x20;     "id": "demux",

&#x20;     "health": "error",

&#x20;     "reason": "PID\_MISMATCH"

&#x20;   },

&#x20;   {

&#x20;     "id": "decoder",

&#x20;     "health": "idle",

&#x20;     "reason": "NO\_INPUT"

&#x20;   }

&#x20; ]

}

```



这里的重点是建立因果传播：



```

PID Mismatch

&#x20;    |

&#x20;    v

No Video PES

&#x20;    |

&#x20;    v

Decoder No Input

&#x20;    |

&#x20;    v

Video Not Playing

```



L0 应该具备以下能力：



\- 拓扑参数变更。

\- 节点状态计算。

\- 状态依赖传播。

\- 故障注入。

\- 状态快照。

\- 实验通关判断。



L0 适合做快速教学反馈、复杂 RF 参数模型和大规模拓扑演练。



\### \*\*4.2 L1：真实 TS 仿真\*\*



L1 则必须真正生成二进制 TS 文件。



它不是：



```

return {    "pat": "ok",    "pmt": "ok",    "pcr": "ok"}

```



而是：



```

packet = TSPacket(...)ts\_file.write(packet.to\_bytes())

```



整个过程：



```

TS Configuration

&#x20;      |

&#x20;      v

Section Generator

&#x20;      |

&#x20;      v

PES Generator

&#x20;      |

&#x20;      v

TS Packetizer

&#x20;      |

&#x20;      v

PCR / CC / PUSI Handling

&#x20;      |

&#x20;      v

TS Multiplexer

&#x20;      |

&#x20;      v

188-byte TS Stream

&#x20;      |

&#x20;      v

Fault Injection

&#x20;      |

&#x20;      v

Generated TS File

```



\### \*\*4.3 一个重要的区别：TS 合规不等于视频可播放\*\*



我建议 v0.4 直接引入两种生成 Profile：



| Profile          | 能力                                       | 目标        |

| ---------------- | ---------------------------------------- | --------- |

| `analysis\_only`  | 正确的 TS 包、PAT、PMT、PES 封装和时钟字段，允许测试用 ES 负载 | 协议分析、故障定位 |

| `playback\_ready` | 包含真实合法的音视频 Elementary Stream，并正确进行 TS 封装 | 实际播放器验证   |



MVP 先只验收 `analysis\_only`。



特别注意，给 PMT 标记 H.264 Stream Type，并不代表 PES 中就有有效 H.264 视频数据。没有合法的 ES 负载，播放器依然无法解码。



因此第一阶段不应承诺“沙盘能够播放真实画面”。



\### \*\*4.4 两种 Runtime 使用同一个接口\*\*



建议定义：



```

from typing import Protocol, AsyncIteratorclass SimulationRuntime(Protocol):    async def start(self, config) -> None:        ...    async def stop(self) -> None:        ...    async def apply\_config(self, config) -> None:        ...    async def events(self) -> AsyncIterator:        ...

```



L0 和 L1 分别实现这个接口。



```

class StateRuntime:    ...class TSRuntime:    ...

```



Session Manager 不需要了解内部实现：



```

runtime = runtime\_factory.create(    mode="sandbox",    fidelity="SIM\_TS")await runtime.start(config)async for event in runtime.events():    await observation\_service.publish(event)

```



这样以后引入 T2MI、BISS、Live DVB 输入，都不需要重写 Session 生命周期管理。



\## \*\*5. MPEG-TS Generator：MVP 应该如何实现\*\*



我建议把 TS Generator 分成六个子模块。



\## \*\*TS Generator 内部结构\*\*



\*\*Program Configuration\*\*



Service / PID / Bitrate / PCR PID



\*\*PSI Generator\*\*



PAT / PMT / CRC



\*\*PES Generator\*\*



PES Header / PTS / DTS



\*\*TS Packetizer\*\*



188-byte Packet / Adaptation Field / PUSI / CC



\*\*Mux Scheduler\*\*



Packet Scheduling / PCR / Null Packet / CBR



\*\*TS Output\*\*



Binary File / Chunk Stream



\### \*\*5.1 Packet 层\*\*



先实现：



```

class TSPacket:    PACKET\_SIZE = 188    SYNC\_BYTE = 0x47    def \_\_init\_\_(        self,        pid: int,        payload: bytes,        continuity\_counter: int,        pusi: bool = False,        adaptation\_field=None,    ):        ...    def to\_bytes(self) -> bytes:        ...

```



必须保证：



\- 每个标准 TS Packet 为 188 字节。

\- Sync Byte 固定为 `0x47`。

\- PID、PUSI、TEI、Scrambling Control 正确编码。

\- Adaptation Field 长度和边界正确。

\- Payload 不超过当前 Packet 剩余空间。

\- CC 按 PID 独立维护。



需要特别注意 CC 的规则：带 Payload 的包按照 PID 递增；仅有 Adaptation Field 的包不能简单当作普通 Payload 包递增。这部分应单独实现并测试。



TSDuck 对标准 TS 文件的定义同样是连续的 188-byte Packet，支持 204-byte RS204 输入格式，但我的建议是 MVP 首先只生成 188-byte TS，204-byte 接入留到后续。



\[image](https://www.google.com/s2/favicons?domain=https://tsduck.io\\\&sz=32)



tsduck.io+1







\### \*\*5.2 PSI/SI 层\*\*



第一阶段建议只实现：



| Table      | PID           | 优先级 |

| ---------- | ------------- | --- |

| PAT        | 0x0000        | P0  |

| PMT        | 可配置，默认 0x0100 | P0  |

| SDT Actual | 0x0011        | P1  |

| NIT Actual | 0x0010        | P2  |



PAT / PMT 是第一阶段核心。



建议把 Section 和 TS Packet 分开实现：



```

PAT / PMT

&#x20;   |

&#x20;   v

Binary Section

&#x20;   |

&#x20;   v

CRC32 Validation

&#x20;   |

&#x20;   v

Section Packetizer

&#x20;   |

&#x20;   v

TS Packet

```



不要把 PSI Section 的生成代码直接写到 TS Packet 类里面。



另外，PAT/PMT 的版本号、Section Number、Last Section Number、CRC 和周期重复都应该成为独立测试项目。



\### \*\*5.3 PES 层\*\*



MVP 建议支持：



\- PES Start Code Prefix。

\- Stream ID。

\- PES Packet Length。

\- PTS。

\- DTS（可选）。

\- PES Payload。



这里建议将 PTS/DTS 的编码模块独立出来，后续视频分析、音画同步分析都需要复用。



\### \*\*5.4 PCR 和时钟\*\*



PCR 不应该依赖普通的系统时间直接填充。



建议使用独立的 `SimulationClock`：



```

class SimulationClock:    def now\_90khz(self) -> int:        ...    def now\_27mhz(self) -> int:        ...

```



这样可以同时支持：



\- 正常稳定时钟。

\- PCR 间隔突变。

\- PCR 回绕。

\- PTS/PCR 时间关系异常。

\- 慢速仿真和高速离线生成。



PCR 必须编码在 Adaptation Field 中，而不是作为普通 TS Payload 写入。



\### \*\*5.5 Mux Scheduler\*\*



这里建议采用基于虚拟播放时间的调度机制。



例如：



```

PAT      ── 每隔一定时间插入

PMT      ── 按配置周期插入

Video    ── 按目标码率调度

Audio    ── 按目标码率调度

PCR      ── 按目标时间点插入

Null PID ── 填充剩余带宽

```



MVP 暂时只支持单 Service，但内部数据模型最好允许多个 Service。



\### \*\*5.6 Packet-level Fault Injector\*\*



故障注入应该放在 Packetizer 和最终输出之间：



```

Normal TS Generator

&#x20;       |

&#x20;       v

&#x20;Fault Injector

&#x20;       |

&#x20;       v

Final TS Output

```



这样无论是正常生成还是故障生成，最终都可以使用同一个 TSDuck 分析链路。



\## \*\*6. Fault Injection：把故障注入设计成独立的数据处理机制\*\*



我不建议在每个 TS Generator 函数里埋各种错误开关。



例如不要这样写：



```

if config.cc\_error:    cc += 2if config.bad\_pat:    pat\_crc = 0

```



短期很方便，后续扩展多个故障组合时会非常难维护。



更好的做法是建立一套独立的故障处理管线。



\### \*\*6.1 故障注入定义\*\*



```

from dataclasses import dataclassfrom typing import Literal@dataclassclass FaultDefinition:    fault\_id: str    category: str    target: str    trigger\_type: Literal\[        "immediate",        "packet\_index",        "simulation\_time",        "condition"    ]    trigger\_value: object    mutation: str    parameters: dict    enabled: bool = True

```



例如：



```

{

&#x20; "fault\_id": "CC\_GAP\_001",

&#x20; "category": "TRANSPORT",

&#x20; "target": "PID:0x0101",

&#x20; "trigger\_type": "packet\_index",

&#x20; "trigger\_value": 1000,

&#x20; "mutation": "DROP\_PACKET",

&#x20; "parameters": {

&#x20;   "count": 3

&#x20; },

&#x20; "enabled": true

}

```



这表示从指定 PID 的第 1000 个包附近开始，丢弃三个 TS Packet。



注意这里应区分两种行为：



\- `DROP\_PACKET`：实际从最终输出流中删除包，使后续 CC 出现跳变。

\- `CORRUPT\_CC`：直接修改 TS Header 中的 CC 字段。



这两个实验虽然都可能表现为 Continuity Error，但它们的底层原因不同，值得分别教学。



\### \*\*6.2 建议第一批实现的故障\*\*



| ID   | 故障           | 注入方式              | 预期观察结果               |

| ---- | ------------ | ----------------- | -------------------- |

| F001 | PAT 缺失       | 删除 PID 0x0000     | 无法找到节目映射             |

| F002 | PAT CRC 错误   | 修改 Section CRC    | PAT 校验失败             |

| F003 | PMT PID 映射错误 | 修改 PAT 中的 PMT PID | 无法找到对应 PMT           |

| F004 | CC 跳变        | 删除指定 PID 的 TS 包   | Continuity Error     |

| F005 | CC 重复        | 重复部分 TS Packet    | Duplicate / CC Error |

| F006 | PCR 间隔异常     | 改变 PCR 插入调度       | PCR Repetition Error |



我会将前三个定义为基础教学实验，后三个用于传输层深入分析。



\### \*\*6.3 故障和恢复都必须留下记录\*\*



建议每次故障注入都有唯一 ID：



```

Run ID: run\_000001



Fault Events:

&#x20; 10.000s F001 PAT\_MISSING

&#x20; 15.000s F004 CC\_DISCONTINUITY

&#x20; 20.000s F004 RECOVERED

```



更重要的是，用户修改参数恢复正常后，系统需要再次生成 TS 并重新分析，而不是直接把节点颜色改成绿色。



\*\*通关必须由新的观测结果证明，而不能由用户的修复动作直接决定。\*\*



\## \*\*7. TSDuck Adapter：不要让 TSDuck 成为后端的黑盒\*\*



这一部分建议设计得稍微专业一些。



TSDuck 的核心工作模式本身就非常适合我们的项目：



```

Input Plugin

&#x20;    |

&#x20;    v

Packet Processing Plugins

&#x20;    |

&#x20;    v

Output Plugin

```



`tsanalyze` 用于分析 TS 文件，`tsp` 则能够组合输入、多个处理插件和输出插件。官方还提供了 TS 分析的 JSON 输出工作流。



\[image](https://www.google.com/s2/favicons?domain=https://github.com\\\&sz=32)



GitHub+1







因此，可以将 TSDuck Adapter 定义成一个统一接口：



```

class TSDuckAdapter:    async def get\_version(self):        ...    async def analyze(self, ts\_file):        ...    async def process(self, pipeline\_config):        ...    async def get\_logs(self, run\_id):        ...    async def terminate(self, run\_id):        ...

```



\### \*\*7.1 执行流程\*\*



\*\*Python Simulation Runtime\*\*



\*\*TSDuck Worker Manager\*\*



进程启动、任务管理、超时、停止



\*\*External Process\*\*



C++



tsanalyze / tsp



stdin / stdout / stderr / 文件输入输出



\*\*TSDuck Result Adapter\*\*



JSON Report / Process Status / Raw Logs



\*\*Observation Model\*\*



\### \*\*7.2 为什么第一版推荐独立进程\*\*



主要有四个原因：



1\. TSDuck 崩溃不会直接拖垮 FastAPI。

2\. 可以独立设置 CPU、内存、执行时长限制。

3\. 可以清楚展示实际执行的命令和参数。

4\. 可以独立升级 TSDuck，而不影响 Python Domain Model。



具体实现时：



\- 使用 `asyncio.create\_subprocess\_exec()`。

\- 不使用 `shell=True` 拼接用户参数。

\- 对 stdout/stderr 使用异步读取。

\- 设定任务超时和进程终止机制。

\- 限制单次任务最大输出量。

\- 将 TSDuck 的退出码、版本、命令参数和日志关联到 `run\_id`。



另外，TSDuck 自身的 Python 绑定值得保留为后续优化选项，但我不会让 MVP 依赖它的内部 API。



\[image](https://www.google.com/s2/favicons?domain=https://tsduck.io\\\&sz=32)



tsduck.io+1







\### \*\*7.3 双流验证机制\*\*



每次生成 TS 后，建议同时执行两类检查：



\*\*A. 自研轻量解析器\*\*



负责：



\- TS Header。

\- PID。

\- CC。

\- PUSI。

\- Adaptation Field。

\- PCR。

\- Packet Index。



\*\*B. TSDuck\*\*



负责：



\- TS 全局分析。

\- PAT / PMT / Service。

\- PID 统计。

\- 错误检测。

\- 相关表和描述符分析。



最终比较：



```

{

&#x20; "run\_id": "run\_000001",

&#x20; "checks": {

&#x20;   "packet\_sync": "pass",

&#x20;   "pat": "pass",

&#x20;   "pmt": "pass",

&#x20;   "continuity": "pass",

&#x20;   "pcr": "pass"

&#x20; },

&#x20; "cross\_validation": {

&#x20;   "packet\_count": "matched",

&#x20;   "pid\_statistics": "matched",

&#x20;   "pat\_version": "matched"

&#x20; }

}

```



这里的示例是平台自己的归一化结果，不是 TSDuck 原始输出格式。



特别重要的一点：两个解析器不一致时，应生成 `ANALYZER\_DISAGREEMENT`，不能简单地把 TSDuck 的结果直接当成绝对真值。然后结合标准测试向量和原始包定位问题。



\## \*\*8. 拓扑与统一数据模型\*\*



由于我们决定 TS-first，拓扑模型也需要跟着收敛。



我建议 v0.4 的第一阶段不要强制把 LNB、DiSEqC、Tuner 都拖进画布。



先建立 Transport Plane 的拓扑：



```

Virtual TS Source

&#x20;      |

&#x20;      v

&#x20;    TS Mux

&#x20;      |

&#x20;      v

&#x20; Fault Injector

&#x20;      |

&#x20;      v

&#x20;   TS Output

&#x20;      |

&#x20;      v

&#x20;TSDuck Analyzer

&#x20;      |

&#x20;      v

&#x20;Diagnosis Engine

```



前端可以用 React Flow 实现节点拖拽和连接，逻辑求值仍然由后端负责。



\### \*\*8.1 节点和端口\*\*



建议使用强类型节点，而不是无限制的 `Record<string, unknown>`。



```

type TopologyNodeType =

&#x20; | 'VIRTUAL\_TS\_SOURCE'

&#x20; | 'TS\_MUX'

&#x20; | 'FAULT\_INJECTOR'

&#x20; | 'TS\_OUTPUT'

&#x20; | 'TS\_ANALYZER';



type SignalPlane =

&#x20; | 'RF'

&#x20; | 'SEC\_CONTROL'

&#x20; | 'MPEG\_TS'

&#x20; | 'T2MI'

&#x20; | 'IP';



interface TopologyPort {

&#x20; id: string;

&#x20; direction: 'input' | 'output' | 'bidirectional';

&#x20; plane: SignalPlane;

&#x20; protocol: string;

&#x20; maxConnections?: number;

}



interface TopologyNode {

&#x20; id: string;

&#x20; type: TopologyNodeType;

&#x20; config: Record<string, unknown>;

&#x20; ports: TopologyPort\[];

}

```



这里保留 RF、SEC\_CONTROL、T2MI 和 IP，是为了避免后面重构整个拓扑格式。



但是，MVP 只启用 `MPEG\_TS`。



\### \*\*8.2 不要把所有运行信息都塞进 StreamSnapshot\*\*



建议至少区分：



\*\*Topology：\*\* 描述用户配置的静态结构。



\*\*Runtime State：\*\* 描述当前运行状态。



\*\*Observation：\*\* 描述某一时刻实际检测到的事实。



\*\*Diagnosis：\*\* 描述系统通过规则得到的判断。



推荐采用统一的运行上下文：



```

interface RunContext {

&#x20; runId: string;

&#x20; topologyRevision: number;

&#x20; sequenceNumber: number;



&#x20; mode: 'sandbox' | 'live';



&#x20; fidelity: 'SIM\_STATE' | 'SIM\_TS';



&#x20; startedAt: number;

}

```



然后 Observation 采用：



```

interface Observation {

&#x20; id: string;

&#x20; runId: string;



&#x20; source: 'generator' | 'parser' | 'tsduck' | 'hardware';



&#x20; confidence:

&#x20;   | 'simulated'

&#x20;   | 'parsed'

&#x20;   | 'measured'

&#x20;   | 'inferred';



&#x20; type: string;



&#x20; timestamp: number;



&#x20; packetIndex?: number;

&#x20; pid?: number;



&#x20; value?: unknown;



&#x20; artifactId?: string;

}

```



例如：



```

{

&#x20; "id": "obs\_000101",

&#x20; "runId": "run\_000001",

&#x20; "source": "tsduck",

&#x20; "confidence": "parsed",

&#x20; "type": "TS\_CONTINUITY\_ERROR",

&#x20; "timestamp": 1794564000000,

&#x20; "packetIndex": 1000,

&#x20; "pid": 257,

&#x20; "value": {

&#x20;   "expectedCC": 5,

&#x20;   "actualCC": 8

&#x20; },

&#x20; "artifactId": "artifact\_00001"

}

```



有了 `packetIndex + pid + artifactId`，前端就能从诊断结果直接跳转到原始码流。



\### \*\*8.3 需要单独的 Artifact 模型\*\*



我建议 TS 文件不只是简单保存在磁盘中，还应该有一个资产元数据：



```

interface TSArtifact {

&#x20; artifactId: string;



&#x20; runId: string;



&#x20; fileName: string;



&#x20; packetSize: 188 | 204;



&#x20; packetCount: number;



&#x20; byteSize: number;



&#x20; sha256: string;



&#x20; generatorVersion: string;



&#x20; configHash: string;



&#x20; faultProfileIds: string\[];



&#x20; createdAt: number;

}

```



这样每次分析都能准确追踪输入文件。



尤其在做故障复现时，可以证明：



\- 是否使用相同的配置。

\- 是否使用相同的故障注入参数。

\- 是否分析的是同一个 TS 文件。

\- 是否更改过生成器版本。



\## \*\*9. REST 和 WebSocket 接口设计\*\*



建议 MVP 采用以下 API。



| Method | Endpoint                           | 用途           |

| ------ | ---------------------------------- | ------------ |

| POST   | `/api/v1/topologies`               | 创建拓扑         |

| PUT    | `/api/v1/topologies/{id}`          | 修改拓扑         |

| POST   | `/api/v1/topologies/{id}/validate` | 校验拓扑         |

| POST   | `/api/v1/sessions`                 | 创建实验 Session |

| POST   | `/api/v1/sessions/{id}/start`      | 启动仿真         |

| POST   | `/api/v1/sessions/{id}/stop`       | 停止仿真         |

| GET    | `/api/v1/sessions/{id}/snapshot`   | 获取状态快照       |

| POST   | `/api/v1/sessions/{id}/faults`     | 注入故障         |

| GET    | `/api/v1/artifacts/{id}`           | 获取 TS 资产     |

| POST   | `/api/v1/artifacts/{id}/analyze`   | 执行 TSDuck 分析 |



WebSocket：



```

/ws/v1/sessions/{session\_id}

```



事件建议统一：



```

type RuntimeEventType =

&#x20; | 'SESSION\_STARTED'

&#x20; | 'SESSION\_STOPPED'

&#x20; | 'NODE\_STATE\_CHANGED'

&#x20; | 'METRIC\_UPDATED'

&#x20; | 'FAULT\_INJECTED'

&#x20; | 'OBSERVATION\_CREATED'

&#x20; | 'DIAGNOSIS\_UPDATED'

&#x20; | 'ANALYSIS\_COMPLETED'

&#x20; | 'RUNTIME\_ERROR';

```



\*\*不要通过 WebSocket 不停推送每一个 188-byte TS Packet。\*\*



那样会把前后端通信和 UI 渲染拖入不必要的高频负载。



推荐的做法是：



\- WebSocket 实时推送状态变化和聚合指标。

\- TS 文件通过独立 Artifact 接口获取。

\- Packet Inspector 根据用户选择的 Packet Index 请求指定数据。

\- 详细日志按需加载。

\- 每个事件带 `sequenceNumber`，断线重连后重新获取完整快照。



例如，生成 100 万个 Packet 时，UI 可能只需要收到数百次统计更新，而不是 100 万条包事件。



\## \*\*10. MVP 的实际范围：第一版到底做什么？\*\*



我建议把 MVP 定义为：



\*\*能够自主生成合法 MPEG-TS、注入典型传输层故障、调用 TSDuck 分析、定位原始数据并完成修复验证。\*\*



第一版不追求把所有 DVB 设备都做出来，而是先构建一条真实可信的数据链路。



\### \*\*10.1 MVP 功能清单\*\*



| 模块               | 功能                      | 优先级 |

| ---------------- | ----------------------- | --- |

| Topology         | TS 节点拖拽、连线、参数配置         | P0  |

| Topology         | 端口类型和连接合法性检查            | P0  |

| L0 Engine        | 节点状态、参数传播、故障因果          | P0  |

| L1 Engine        | 188-byte TS Packet 生成   | P0  |

| L1 Engine        | PAT / PMT / CRC         | P0  |

| L1 Engine        | PES / PID / PUSI / CC   | P0  |

| L1 Engine        | PCR / Null PID / CBR    | P0  |

| Fault Lab        | PAT 缺失、PMT 错误、CC 异常     | P0  |

| TSDuck           | 自动分析、JSON 结果、CLI 日志     | P0  |

| Observation      | 事件、指标、原始证据              | P0  |

| Diagnosis        | 规则匹配和故障解释               | P0  |

| Stream Inspector | TS Packet Hex 查看        | P1  |

| Time Machine     | 运行回放与证据冻结               | P1  |

| SI               | SDT / NIT / EIT         | P1  |

| Advanced         | T2MI / BISS             | P2  |

| RF Sandbox       | LNB / DiSEqC / Unicable | P2  |



这里建议严格控制 P0 的数量。尤其是 EPG、FastScan、BISS、T2MI，不要提前挤占 TS Generator 的开发资源。



\### \*\*10.2 第一版拓扑示例\*\*



\*\*MVP Demonstration Topology\*\*



可验收目标



\*\*Virtual TS Source\*\*



Service / PID / Bitrate



\*\*TS Multiplexer\*\*



PAT / PMT / PES / PCR / CC



\*\*Fault Injector\*\*



正常 / CC Error / PAT Error / PMT Error



\*\*TS Output\*\*



188-byte TS File



\*\*TSDuck Analyzer\*\*



真实外部分析



\*\*Topology Status\*\*



节点健康状态和故障传播



\*\*TS Analysis\*\*



PID、PAT、PMT、PCR、CC



\### \*\*10.3 MVP 验收标准\*\*



我建议设置以下硬性验收条件。



| 测试项             | 验收要求                                 |

| --------------- | ------------------------------------ |

| TS Packet       | 输出文件长度为 188 的整数倍                     |

| Sync Byte       | 每个 Packet 起始字节都是 0x47                |

| PAT             | 正确解析，CRC 正确                          |

| PMT             | 正确解析，CRC 正确                          |

| PID             | PAT、PMT 和 Elementary Stream PID 关联正确 |

| PES             | PES Start Code 和头部字段有效               |

| CC              | 每个 PID 的连续性逻辑正确，包含 15→0 回绕           |

| PCR             | 编码正确，时钟回绕和间隔计算正确                     |

| TSDuck          | 能独立分析生成的 TS                          |

| Fault Injection | 三个基础故障都能被独立检测                        |

| Diagnosis       | 能够定位异常 PID 和 Packet Index            |

| Recovery        | 修复配置后重新生成 TS，故障消失                    |

| Reproducibility | 相同配置、版本和随机种子能够复现相同结果                 |



最后一条尤其重要。



我建议生成器实现确定性模式：



```

SimulationConfig(    seed=123456,    initial\_clock=0,    deterministic=True)

```



只要配置、生成器版本、初始时钟和随机种子相同，最终生成的 TS 文件应该具有相同 SHA-256。



注意：不能把实时墙钟时间、随机 Session ID 等不确定字段写进 TS 文件，否则无法实现字节级复现。



\## \*\*11. 建议的开发顺序\*\*



我会将开发拆分为六个交付节点，而不是直接按照完整 UI 和后台服务同时开发。



\## \*\*MVP Engineering Milestones\*\*



1\. \*\*M0：基础工程骨架\*\*

&#x20;  - Python 项目结构

&#x20;  - Pydantic 数据模型

&#x20;  - FastAPI

&#x20;  - SQLite

&#x20;  - TSDuck 环境探测

&#x20;  基础设施

2\. \*\*M1：TS Core\*\*

&#x20;  - TSPacket

&#x20;  - MPEG-2 CRC32

&#x20;  - PAT / PMT

&#x20;  - Packetizer

&#x20;  - CC / PCR

&#x20;  - 文件输出

&#x20;  核心技术里程碑

3\. \*\*M2：TSDuck 验证\*\*

&#x20;  - Worker Process

&#x20;  - TS Analyzer

&#x20;  - JSON 结果归一化

&#x20;  - CLI 日志采集

&#x20;  - 双解析器比较

&#x20;  第一个完整技术闭环

4\. \*\*M3：Hybrid Runtime\*\*

&#x20;  - L0 State Engine

&#x20;  - L1 TS Engine

&#x20;  - Session Manager

&#x20;  - Runtime Events

&#x20;  - Fault Injector

&#x20;  仿真系统

5\. \*\*M4：故障靶场\*\*

&#x20;  - PAT Missing

&#x20;  - PMT Error

&#x20;  - CC Discontinuity

&#x20;  - Diagnosis Rules

&#x20;  - Recovery Verification

&#x20;  教学闭环

6\. \*\*M5：前端可视化\*\*

&#x20;  - 拓扑画布

&#x20;  - 节点状态

&#x20;  - TS 分析报告

&#x20;  - CLI 对照

&#x20;  - Packet Inspector

&#x20;  MVP 交付



我特别建议在 M1 阶段就开始做独立测试，而不是等到前端完成之后再验证 TS 数据。



\### \*\*11.1 测试框架\*\*



建议分成四层：



```

Unit Test

&#x20;  |

&#x20;  +-- Packet Encoding

&#x20;  +-- CRC

&#x20;  +-- CC

&#x20;  +-- PCR

&#x20;  |

Integration Test

&#x20;  |

&#x20;  +-- TS Generation

&#x20;  +-- Fault Injection

&#x20;  +-- TSDuck Worker

&#x20;  |

Conformance Test

&#x20;  |

&#x20;  +-- Valid PAT / PMT

&#x20;  +-- Invalid CRC

&#x20;  +-- CC Wraparound

&#x20;  +-- PCR Wraparound

&#x20;  +-- Section Fragmentation

&#x20;  |

Scenario Test

&#x20;  |

&#x20;  +-- PAT Missing Lab

&#x20;  +-- PMT Mapping Lab

&#x20;  +-- CC Discontinuity Lab

```



另外，建议在项目中建立 `golden\_streams/`，保存经过人工和 TSDuck 双重验证的基础 TS 测试样本。



未来修改 TS Generator，必须保证这些测试向量继续通过。



\## \*\*12. 当前阶段我建议明确排除的内容\*\*



为了避免 MVP 越做越大，下面这些功能暂时不进入开发范围：



1\. 完整 DVB-S/S2/S2X、DVB-T/T2 物理层仿真。

2\. 真正的 RF 波形生成。

3\. Linux DVB Frontend 驱动控制。

4\. 完整视频编码器实现。

5\. BISS Mode E / BISS2。

6\. 完整 T2MI / BBFrame 生成。

7\. 多用户实验隔离。

8\. 分布式数据存储和高可用服务。



其中 RF 和 DiSEqC 可以保留 L0 的状态模型，但不需要在第一版中实现物理信号传输。



\## \*\*13. 最后补充三个容易被忽略的工程问题\*\*



\### \*\*13.1 运行时和 TS 文件生成需要解耦\*\*



不要让生成 1GB TS 文件的过程阻塞 FastAPI Event Loop。



建议：



```

FastAPI

&#x20;  |

&#x20;  v

Simulation Session

&#x20;  |

&#x20;  +---- Async Runtime

&#x20;  |

&#x20;  +---- TS Generation Task

&#x20;  |

&#x20;  +---- TSDuck Worker

&#x20;  |

&#x20;  +---- Event Queue

```



单机 MVP 可以使用 `asyncio` 和独立子进程，不需要 Celery。



未来高码率实时流处理如果成为 CPU 瓶颈，再考虑将 Packetizer 和 Mux 调度的热点迁移到 C++。



\### \*\*13.2 WebSocket 必须有背压机制\*\*



如果生成速度远高于前端消费速度，事件队列不能无限增长。



建议：



\- 节点状态采用最新值合并。

\- Metrics 采用窗口聚合。

\- 原始 Packet 不进入普通事件队列。

\- 诊断事件和故障记录不能随意丢弃。

\- 慢速客户端可以丢弃中间快照，但必须能够通过全量 Snapshot 恢复状态。



\### \*\*13.3 所有实验都应该可以保存和恢复\*\*



每一次实验建议保存：



```

Experiment

&#x20;├── topology.json

&#x20;├── simulation.json

&#x20;├── fault\_profile.json

&#x20;├── runtime\_snapshot.json

&#x20;├── ts\_artifact.ts

&#x20;├── tsduck\_report.json

&#x20;├── events.jsonl

&#x20;└── diagnosis.json

```



这样不仅是教学平台，也可以成为工程团队内部的故障案例数据库。



\# \*\*14. 我建议将 Spec v0.4 的核心验收目标定为一个闭环\*\*



\## \*\*DVB Sandbox — MVP 核心闭环\*\*



1\. \*\*Create\*\*



&#x20;  用户创建 TS 拓扑，配置 Service、PID、Bitrate。

2\. \*\*Generate\*\*



&#x20;  Python Engine 生成真实 MPEG-TS。

3\. \*\*Inject\*\*



&#x20;  用户选择故障，注入 PAT、PMT 或 CC 异常。

4\. \*\*Analyze\*\*



&#x20;  TSDuck 对输出 TS 进行实际分析。

5\. \*\*Diagnose\*\*



&#x20;  关联分析结果、Packet Index、PID 和故障原因。

6\. \*\*Inspect\*\*



&#x20;  工程师查看原始 TS Packet、Header 和十六进制数据。

7\. \*\*Recover\*\*



&#x20;  修复配置，重新生成码流。

8\. \*\*Verify\*\*



&#x20;  TSDuck 再次分析，证明异常已经消失。



MVP 完成标准



\*\*一个故障场景从产生到发现、定位、修复、验证，全程有真实数据和可追溯证据。\*\*



\## \*\*15. 我的最终架构建议\*\*



将 Spec v0.4 的几个重要决策正式冻结：



| 决策    | 建议                                |

| ----- | --------------------------------- |

| 架构形态  | Modular Monolith + Worker Process |

| 主语言   | Python                            |

| API   | FastAPI                           |

| 数据校验  | Pydantic                          |

| 仿真    | L0 State + L1 TS                  |

| TS 生成 | 自研 Python TS Core                 |

| TS 分析 | TSDuck                            |

| 进程管理  | asyncio subprocess                |

| 前端    | React + TypeScript                |

| 拓扑编辑  | React Flow                        |

| 本地数据库 | SQLite                            |

| 原始码流  | 文件系统                              |

| 实时通信  | WebSocket                         |

| 测试    | Pytest + TSDuck Conformance       |



\*\*还有一个我希望在设计上特别强调的原则：TSDuck 是外部验证工具，自研 TS Core 才是项目拥有的核心技术资产。\*\*



不要把 TS Generator 完全交给 TSDuck 插件拼装，否则以后你想研究字段级故障注入、实现自定义协议演练、展示每一个 Packet 的生成过程时，平台的自主性会受到限制。TSDuck 应该帮助你验证生成器，而不是替代生成器。



接下来最有价值的工作，是把 M1 的 TS Core 单独形成一份详细设计：明确 Packet、Section、PES、PCR、Mux 五个模块的接口，配套二进制结构、CRC 测试向量和第一批 Pytest 用例。这部分一旦设计扎实，整个 DVB 沙盘就有了真正可持续扩展的底座。



\*\*参考资料：\*\*



\- \[TSDuck User Guide](https://tsduck.io/docs/tsduck.html?utm\_source=chatgpt.com)：TS 数据格式、工具与插件。

\- \[TSDuck Developer Guide](https://tsduck.io/docs/tsduck-dev.html?utm\_source=chatgpt.com)：C++、Python API 与架构。

\- \[TSDuck Programming Reference](https://www.tsduck.io/doxy/index.html?utm\_source=chatgpt.com)：底层 API 参考。

\- \[TSDuck GitHub](https://github.com/tsduck/tsduck?utm\_source=chatgpt.com)：源码、测试和开发版本。

