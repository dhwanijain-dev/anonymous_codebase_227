"""Remote-sensing concept lexicon shared by the rule-based query parser and the mock
text encoder. Each concept maps to a prototype in the 16-d spectral descriptor space
(see app.geo.spectral.FEATURE_NAMES), expressed as *standardised* offsets."""
from __future__ import annotations

import numpy as np

from app.geo.spectral import FEATURE_NAMES

_F = {n: i for i, n in enumerate(FEATURE_NAMES)}


def _proto(**kw: float) -> np.ndarray:
    v = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
    for k, val in kw.items():
        v[_F[k]] = val
    return v


# concept -> (synonyms, category, prototype)
CONCEPTS: dict[str, tuple[list[str], str, np.ndarray]] = {
    "built structures": (["building", "buildings", "structure", "structures", "house", "houses",
                          "urban", "settlement", "compound", "facility", "facilities", "warehouse",
                          "construction site", "built"],
                         "object", _proto(built_frac=2.0, edge_density=1.5, brightness=1.0, ndvi=-1.2,
                                          texture=0.8, bright_frac=1.0, veg_frac=-1.0)),
    "water": (["water", "river", "rivers", "lake", "lakes", "reservoir", "sea", "coast", "coastline",
               "shoreline", "pond", "canal", "flood", "flooding", "inundation", "wetland"],
              "object", _proto(ndwi=2.5, water_frac=2.5, brightness=-1.0, dark_frac=1.2, nir=-1.5,
                               ndvi=-1.0, texture=-0.8)),
    "vegetation": (["vegetation", "forest", "forests", "trees", "tree", "crop", "crops", "cropland",
                    "farmland", "agriculture", "agricultural", "field", "fields", "grass", "green"],
                   "object", _proto(ndvi=2.0, veg_frac=1.8, nir=1.5, brightness=-0.3, red=-0.8)),
    "road": (["road", "roads", "highway", "street", "track", "tracks", "runway", "airstrip",
              "railway", "rail"],
             "object", _proto(linearity=2.5, edge_density=1.0, built_frac=0.8, ndvi=-0.4)),
    "bare soil": (["bare", "soil", "sand", "desert", "cleared land", "earthworks", "quarry", "mine",
                   "mining", "excavation"],
                  "object", _proto(brightness=1.3, ndvi=-1.5, veg_frac=-1.5, red=1.2, texture=0.3)),
    "snow": (["snow", "ice", "glacier", "glaciers"],
             "object", _proto(brightness=3.0, bright_frac=3.0, contrast=-0.5, blue=2.5)),
    "cloud": (["cloud", "clouds", "cloudy"], "object", _proto(brightness=2.5, bright_frac=2.5)),
    "vessel": (["ship", "ships", "vessel", "vessels", "boat", "boats", "port", "harbor", "harbour"],
               "object", _proto(water_frac=1.5, ndwi=1.2, edge_density=1.0, built_frac=0.6)),
    "aircraft": (["airport", "aircraft", "airfield", "plane", "planes", "apron", "hangar"],
                 "object", _proto(linearity=1.5, built_frac=1.5, brightness=1.0, edge_density=1.0)),
}

# words -> change types (see app.schemas.change.ChangeType)
CHANGE_LEXICON: dict[str, list[str]] = {
    "construction": ["new", "newly", "built", "construction", "constructed", "under construction",
                     "developed", "development", "erected"],
    "clearance": ["cleared", "clearing", "clearance", "deforestation", "deforested", "logging",
                  "felled", "razed"],
    "water_extent_change": ["flood", "flooded", "flooding", "drought", "dried", "receding",
                            "inundated", "water level"],
    "road_development": ["new road", "new roads", "paved", "road building", "road construction"],
    "appearance": ["appeared", "appearance", "emerged", "new"],
    "disappearance": ["disappeared", "removed", "demolished", "destroyed", "vanished", "missing"],
    "expansion": ["expanded", "expansion", "expanding", "grew", "growth", "enlarged", "sprawl"],
    "contraction": ["shrunk", "shrinking", "contraction", "reduced", "retreat", "retreating"],
}
TEMPORAL_WORDS = ["new", "newly", "recent", "recently", "since", "before", "after", "during",
                  "changed", "change", "changes", "emerging", "over time", "between", "last",
                  "earliest", "first"]
SPATIAL_RELATIONS = ["near", "next to", "along", "beside", "adjacent to", "around", "close to",
                     "within", "inside", "on", "by"]
