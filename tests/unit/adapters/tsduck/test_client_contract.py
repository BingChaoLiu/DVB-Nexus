"""TSDuckClient contract tests, pure half (SPEC-308 §4, REQ-TSK-308-001/002).

Unit layer: construction, reserved-operation refusal and the call-record
field contract — no I/O, no subprocess. The orchestration halves (argv
plumbing, gate, real chain) live in the integration layer where file and
process I/O are legal.
"""

from __future__ import annotations

import dataclasses

import pytest

from adapters.tsduck.client import (
    MVP_MINIMUM_BASELINE,
    GenerateSpec,
    InjectSpec,
    TSDuckCallRecord,
    TSDuckClient,
)
from adapters.tsduck.errors import TSDuckNotEnabledError


class TestReservedOperations:
    """SPEC-308 §4: 预留操作不实现逻辑，只签名 + 显式拒绝（防静默半实现）."""

    @pytest.mark.parametrize("operation", ["inject", "generate"])
    def test_reserved_operation_rejects_before_any_probe(self, operation):
        import asyncio

        client = TSDuckClient()
        method = getattr(client, operation)
        spec = InjectSpec() if operation == "inject" else GenerateSpec()
        with pytest.raises(TSDuckNotEnabledError) as excinfo:
            asyncio.run(method(spec))
        assert excinfo.value.code == "TSDUCK_NOT_ENABLED"
        assert operation in str(excinfo.value)

    def test_reserved_specs_exist_as_signatures_only(self):
        assert dataclasses.is_dataclass(InjectSpec)
        assert dataclasses.is_dataclass(GenerateSpec)


class TestMvpBaseline:
    def test_minimum_baseline_is_3_40(self):
        """SPEC-308 §9: 版本低于最低基线（3.40，#3 实测版本）→ unsupported."""
        assert MVP_MINIMUM_BASELINE == (3, 40)


class TestCallRecordNineFields:
    """SPEC-308 §7: 版本/可执行路径/argv/起止时间/退出码/stdout/stderr/
    输入 Artifact SHA-256 九字段 + run_id 关联（有则填）."""

    def test_field_set_is_exactly_the_nine_fields(self):
        names = {f.name for f in dataclasses.fields(TSDuckCallRecord)}
        assert names == {
            "version",                # 1 版本
            "executable_path",        # 2 可执行路径
            "argv",                   # 3 argv
            "started_at",             # 4 起始时间
            "finished_at",            # 5 结束时间
            "exit_code",              # 6 退出码
            "stdout_text",            # 7 stdout
            "stderr_text",            # 8 stderr
            "input_artifact_sha256",  # 9 输入 Artifact SHA-256
            "run_id",                 # 关联 run_id（有则填，非九字段之一）
        }

    def test_record_is_frozen(self):
        record = TSDuckCallRecord(
            version="3.40-4165",
            executable_path=r"D:\Program Files\TSDuck\bin\tsanalyze.exe",
            argv=("tsanalyze", "--json", "x.ts"),
            started_at=1000.0,
            finished_at=1001.0,
            exit_code=0,
            stdout_text="{}",
            stderr_text="",
            input_artifact_sha256="0" * 64,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.exit_code = 1  # type: ignore[misc]

    def test_run_id_defaults_to_none(self):
        record = TSDuckCallRecord(
            version=None,
            executable_path=None,
            argv=(),
            started_at=0.0,
            finished_at=0.0,
            exit_code=None,
            stdout_text="",
            stderr_text="",
            input_artifact_sha256=None,
        )
        assert record.run_id is None
