import numpy as np

from app.models.change_model import FeatureDifferenceChangeDetector, Observation
from app.models.embedding_model import MockEmbeddingModel
from app.models.quality_model import HeuristicQualityModel
from app.models.query_parser import RuleBasedQueryParser
from app.models.reranker import Candidate, WeightedRanker
from tests.synth import add_cloud, add_construction, landscape

MAP = {"blue": 1, "green": 2, "red": 3, "nir": 4}


def test_parser_example():
    p = RuleBasedQueryParser().parse("newly built structures near a river")
    assert p.semantic_concepts == ["built structures"]
    assert "river" in p.context
    assert p.temporal_intent is True
    assert "construction" in p.change_types
    assert "appearance" in p.change_intent and "construction" in p.change_intent


def test_parser_dates():
    p = RuleBasedQueryParser().parse("flooding along the coast between 2019 and 2021")
    assert p.date_from.year == 2019 and p.date_to.year == 2021
    assert "water_extent_change" in p.change_types


def test_mock_embedding_deterministic_and_semantic():
    m = MockEmbeddingModel("m", "1", 64, MAP)
    img = landscape(1)[:, :256, :256]
    a, b = m.encode_image(img), m.encode_image(img)
    assert np.allclose(a, b) and abs(np.linalg.norm(a) - 1) < 1e-5
    assert np.allclose(m.encode_text("water"), m.encode_text("water"))
    water = landscape(1)[:, :, 20:60][:, :40, :40]
    veg = landscape(1)[:, 100:140, 200:240]
    q = m.encode_text("river")
    assert q @ m.encode_image(water) > q @ m.encode_image(veg)


def test_quality_detects_cloud():
    qm = HeuristicQualityModel(MAP)
    img = add_cloud(landscape(1))[:, 256:, 256:]
    q, mask = qm.assess(img, np.ones(img.shape[1:], bool))
    assert q.cloud_score > 0.5 and not q.usable_for_change_detection
    clear = landscape(1)[:, 256:, 256:]
    q2, _ = qm.assess(clear, np.ones(clear.shape[1:], bool))
    assert q2.cloud_score < 0.05 and q2.usable_for_change_detection


def _obs(img, qm):
    v = np.ones(img.shape[1:], bool)
    _, mask = qm.assess(img, v)
    return Observation(img, v, mask, None, "MSI")


def test_change_detector_construction_vs_noise():
    qm, det = HeuristicQualityModel(MAP), FeatureDifferenceChangeDetector(MAP)
    before = landscape(1)[:, 256:, 256:]
    same = landscape(2)[:, 256:, 256:]
    after = add_construction(landscape(3))[:, 256:, 256:]
    r_same = det.compare(_obs(before, qm), _obs(same, qm))
    r_chg = det.compare(_obs(before, qm), _obs(after, qm))
    assert r_same.score < 0.05
    assert r_chg.score > 0.3 and r_chg.change_type == "construction"


def test_illumination_difference_suppressed():
    qm, det = HeuristicQualityModel(MAP), FeatureDifferenceChangeDetector(MAP)
    before = landscape(1)[:, 256:, 256:]
    brighter = np.clip(landscape(2)[:, 256:, 256:] * 1.3 + 0.01, 0, 1)  # gain/offset only
    assert det.compare(_obs(before, qm), _obs(brighter, qm)).score < 0.1


def test_weighted_ranker_renormalises():
    r = WeightedRanker({"semantic": 0.5, "quality": 0.25, "change": 0.25})
    a = Candidate("a", {"semantic": 1.0, "quality": 1.0}, {"semantic", "quality"})
    b = Candidate("b", {"semantic": 0.2, "quality": 1.0}, {"semantic", "quality"})
    out = r.rank([b, a])
    assert out[0].tile_id == "a" and abs(out[0].final_score - 1.0) < 1e-9


def _temporal_case(flags, quals):
    """Run the temporal consensus on a fake series; flags[i] = pair(ref, obs_i+1) detects change."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace as NS

    from app.models.change_model import PairResult
    from app.services.change_detection.service import ChangeAnalysisService

    class Det:
        def __init__(self):
            self.i = 0

        def compare(self, a, b):
            f = flags[self.i]
            self.i += 1
            return PairResult(0.8 if f else 0.02, 0.8 if f else 0.02, 0.2, "construction",
                              {}, {"registration_factor": 1.0}, None, {})

        def info(self):
            from app.models.base import ModelInfo
            return ModelInfo("fake", "1", "change")

    svc = ChangeAnalysisService.__new__(ChangeAnalysisService)
    from app.core.config import get_settings
    svc.s, svc.detector, svc._cache = get_settings(), Det(), {}
    t0 = datetime(2023, 1, 1)
    items = [(NS(quality_score=q, acquisition_time=t0 + timedelta(days=30 * i)),
              NS(tile_id=f"t{i}", scene_id=f"s{i}", geometry=None, min_x=None)) for i, q in enumerate(quals)]
    svc._obs = lambda it, scenes: (NS(image=np.zeros((4, 8, 8)), valid=None, mask=None, time=None), {"transform": 1})
    return svc._analyze_location("k", items, {}, {"pairs_evaluated": 0})


def test_temporal_consensus_persistent_beats_transient(env):
    persistent = _temporal_case([False, True, True, True], [0.9] * 5)
    transient = _temporal_case([False, False, False, True], [0.9, 0.9, 0.9, 0.9, 0.55])
    flicker = _temporal_case([True, False, False, False], [0.9] * 5)
    assert persistent.confidence > 0.6
    assert transient.confidence < 0.5 * persistent.confidence
    assert flicker.confidence < 0.3 * persistent.confidence and flicker.factors["transient"]
    assert persistent.earliest[1].tile_id == "t2" and persistent.last_unchanged[1].tile_id == "t1"


def test_quality_engine_facade(env):
    from app.services.quality import QualityEngine

    r = QualityEngine().assess(add_cloud(landscape(1))[:, 256:, 256:])
    assert r.cloud_score > 0.5 and not r.usable_for_change_detection
