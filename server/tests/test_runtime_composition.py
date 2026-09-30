import inspect

import pytest

import app.main as main
from app.devices.dispatch_runtime import CommandDispatcher
from app.api.gateway import AgentGateway
from app.runs.run_call_service import RunCallService
from app.runs.runner_supervisor import RunnerSupervisor


@pytest.mark.parametrize(
    "constructor",
    [
        AgentGateway,
        CommandDispatcher,
        RunCallService,
        RunnerSupervisor,
    ],
)
def test_IT_SRV_RUNTIME_18_write_collaborators_require_runtime(constructor) -> None:
    parameter = inspect.signature(constructor).parameters["run_runtime"]

    assert parameter.default is inspect.Parameter.empty


def test_IT_SRV_RUNTIME_19_main_uses_runtime_for_reads_and_writes() -> None:
    assert main.report_generator._run_reader is main.run_runtime
    assert main.agent_gateway._run_runtime is main.run_runtime
    assert main.dispatcher._run_runtime is main.run_runtime


def test_IT_SRV_RUNTIME_20_runner_supervisor_rejects_hidden_dependencies() -> None:
    parameters = inspect.signature(RunnerSupervisor).parameters.values()

    assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in parameters)
