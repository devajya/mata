"""
Tests for backend/backend/graph.py — layer assignment logic.

AGENT-CTX: All tests are deterministic (no LLM, no network).
Layer assignment is a pure lookup table so tests are fast and exhaustive.
"""

import pytest

from backend.graph import (
    CHAIN_LAYER_ORDER,
    EVIDENCE_TYPE_TO_LAYER,
    LAYER_NAMES,
    assign_layer,
)


def test_in_vitro_maps_to_layer_0():
    assert assign_layer("in vitro") == 0


def test_animal_model_maps_to_layer_1():
    assert assign_layer("animal model") == 1


def test_human_genetics_maps_to_layer_2():
    assert assign_layer("human genetics") == 2


def test_clinical_trial_maps_to_layer_3():
    assert assign_layer("clinical trial") == 3


def test_review_maps_to_layer_minus_1():
    assert assign_layer("review") == -1


def test_unknown_type_maps_to_minus_1():
    """assign_layer must return -1 (not raise) for unknown/arbitrary input."""
    assert assign_layer("randomtext") == -1
    assert assign_layer("") == -1
    assert assign_layer("IN VITRO") == -1  # case-sensitive: wrong case → -1


def test_chain_layer_order_excludes_reviews():
    """CHAIN_LAYER_ORDER must not include -1 — reviews are metadata, not graph nodes."""
    assert -1 not in CHAIN_LAYER_ORDER


def test_chain_layer_order_covers_all_non_review_layers():
    """All non-review layers (0-3) must appear in CHAIN_LAYER_ORDER."""
    non_review_layers = {v for v in EVIDENCE_TYPE_TO_LAYER.values() if v != -1}
    assert non_review_layers == set(CHAIN_LAYER_ORDER)


def test_layer_names_covers_all_layers_including_review():
    """LAYER_NAMES must have a human-readable label for every layer including -1."""
    all_layers = set(EVIDENCE_TYPE_TO_LAYER.values())
    assert all_layers.issubset(set(LAYER_NAMES.keys()))
