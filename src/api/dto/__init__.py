"""Pydantic DTO assembly point for the API layer (SPEC-500 §5, ticket #24).

SPEC-500 §5: "Pydantic DTO 权威定义于本规格实现 (``app/api/dto/``)"; JSON
字段 snake_case,``bytes`` 以 hex 编码,枚举串与 domain 一致。Ticket #24
establishes the package and implements the DTOs the skeleton actually
renders (the unified error envelope); route DTOs arrive with their routes
in M3/M4 under the same discipline.
"""

from api.dto.errors import ErrorDetail, ErrorResponse

__all__ = ["ErrorDetail", "ErrorResponse"]
