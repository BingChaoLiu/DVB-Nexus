"""Topology domain: node/port/link model and validation.

MVP scope is model + validation; the causal evaluator is deferred (ADR-0005
decision 4). Links are port-level: ``from_node/from_port`` to
``to_node/to_port`` (SPEC-202).
"""
