"""Root conftest for the four-layer test tree (SPEC-505, ticket #22).

C1 scaffold: layer markers live in pyproject ``[tool.pytest.ini_options]``;
marker-discipline enforcement (directory ↔ marker injection, contradiction
hard-fail, windows_only platform guard) and the six core fixtures are added
by the following commits of ticket #22. See tests/README.md for the full
contract.
"""
