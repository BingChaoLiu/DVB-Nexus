"""Pydantic DTO assembly point for the API layer (SPEC-500 §5, ticket #24).

SPEC-500 §5: "Pydantic DTO 权威定义于本规格实现 (``app/api/dto/``)"; JSON
字段 snake_case,``bytes`` 以 hex 编码,枚举串与 domain 一致。Ticket #24
establishes the package and implements the DTOs the skeleton actually
renders (the unified error envelope); route DTOs arrive with their routes
in M3/M4 under the same discipline.

Ticket #48 lands the SPEC-500 §4 route DTOs under that discipline: the
SPEC-108 §4 generator mapping (``api.dto.generator``), the SPEC-204 §3
fault-plan shapes (``api.dto.faults``), the run async-job surface
(``api.dto.runs``), the SPEC-200 session views (``api.dto.sessions``) and
the artifact metadata (``api.dto.artifacts``).
"""

from api.dto.artifacts import ArtifactMetaDTO
from api.dto.encapsulation import (
    BBFrameDTO,
    BissMode1ConfigDTO,
    BissModeEConfigDTO,
    InnerTsResultDTO,
    StructureViewDTO,
    T2miPacketDTO,
)
from api.dto.errors import ErrorDetail, ErrorResponse
from api.dto.faults import FaultActivationDTO, FaultDefinitionDTO
from api.dto.generator import ElementaryStreamDTO, GeneratorConfigDTO, ProgramDTO
from api.dto.runs import (
    RunAcceptedDTO,
    RunArtifactDTO,
    RunStatusDTO,
    RunSubmitRequest,
)
from api.dto.scenarios import (
    ScenarioDetailDTO,
    ScenarioSolutionDTO,
    ScenarioSummaryDTO,
)
from api.dto.sessions import (
    ArtifactRefDTO,
    ClockConfigDTO,
    ConnectionDTO,
    CreateSessionRequest,
    FaultRefDTO,
    NodeStateDTO,
    PortStateDTO,
    ResourceLimitsDTO,
    SessionValidationDTO,
    SessionViewDTO,
    SnapshotDTO,
    TopologyViolationDTO,
)
from api.dto.topologies import (
    TopologyConnectionDTO,
    TopologyCreateRequest,
    TopologyDTO,
    TopologyNodeDTO,
    TopologyPortDTO,
    TopologySpecDTO,
    TopologySummaryDTO,
    TopologyValidationDTO,
)
from api.dto.tsduck_calls import TSDuckCallDTO

__all__ = [
    "ArtifactMetaDTO",
    "BBFrameDTO",
    "BissMode1ConfigDTO",
    "BissModeEConfigDTO",
    "InnerTsResultDTO",
    "StructureViewDTO",
    "T2miPacketDTO",
    "ArtifactRefDTO",
    "ClockConfigDTO",
    "ConnectionDTO",
    "CreateSessionRequest",
    "ElementaryStreamDTO",
    "ErrorDetail",
    "ErrorResponse",
    "FaultActivationDTO",
    "FaultDefinitionDTO",
    "FaultRefDTO",
    "GeneratorConfigDTO",
    "NodeStateDTO",
    "PortStateDTO",
    "ProgramDTO",
    "ResourceLimitsDTO",
    "RunAcceptedDTO",
    "RunArtifactDTO",
    "RunStatusDTO",
    "RunSubmitRequest",
    "ScenarioDetailDTO",
    "ScenarioSolutionDTO",
    "ScenarioSummaryDTO",
    "SessionValidationDTO",
    "SessionViewDTO",
    "SnapshotDTO",
    "TSDuckCallDTO",
    "TopologyConnectionDTO",
    "TopologyCreateRequest",
    "TopologyDTO",
    "TopologyNodeDTO",
    "TopologyPortDTO",
    "TopologySpecDTO",
    "TopologySummaryDTO",
    "TopologyValidationDTO",
    "TopologyViolationDTO",
]
