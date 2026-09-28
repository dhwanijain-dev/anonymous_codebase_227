# API examples

Base URL `http://localhost:8000/api/v1`. Add `-H 'X-API-Key: …'` if `API_KEYS` is set.
Responses below are abbreviated from a run on the synthetic demo archive
(`python scripts/make_demo_data.py`).

## Ingest

```bash
# one scene, synchronous; metadata overrides are optional
curl -X POST $API/ingestion/scene -H 'content-type: application/json' -d '{
  "path": "/data/raw/demo/S2A_20230701.tif",
  "metadata": {"sensor": "MSI", "platform": "Sentinel-2A"}
}'
```
```json
{"scene_id": "scn_303f6867141a260c5c2b", "status": "complete", "created": true, "duplicate": false,
 "tiles_created": 4, "tiles_skipped": 0, "embeddings_added": 4, "message": "Ingested 4 tiles"}
```
Posting the same file again returns `"duplicate": true, "created": false` and adds no vectors.

```bash
# everything new under DATA_ROOT/raw, as a background job
curl -X POST $API/ingestion/incremental -H 'content-type: application/json' -d '{}'
curl $API/jobs/job_a83d99c26ba042afb6af         # -> {"status": "succeeded", "progress": 1.0, "result": {...}}
```

## Semantic search with change verification

```bash
curl -X POST $API/search/text -H 'content-type: application/json' -d '{
  "query": "newly built structures near a river",
  "top_k": 20,
  "date_from": "2023-01-01T00:00:00Z", "date_to": "2023-12-31T23:59:59Z",
  "sensor": "MSI",
  "bbox": [74.99, 12.62, 75.04, 12.67],
  "min_quality": 0.5,
  "require_change": true
}'
```
```json
{
  "query_id": "qry_…",
  "parsed_query": {"semantic_concepts": ["built structures"], "change_intent": "appearance/construction",
                   "context": ["river"], "temporal_intent": true, "change_types": ["construction", "appearance"]},
  "results": [{
    "result_id": "res_…", "rank": 1,
    "tile_id": "scn_303f6867141a260c5c2b_196_545", "scene_id": "scn_303f6867141a260c5c2b",
    "geometry": {"type": "Polygon", "coordinates": [[...]]},
    "acquisition_time": "2023-07-01T00:00:00Z", "sensor": "MSI", "platform": "Sentinel-2A",
    "semantic_score": 0.21, "quality_score": 1.0, "metadata_score": 0.62, "spatial_score": 1.0,
    "change_score": 0.80, "final_score": 0.54, "confidence": 0.37,
    "change": {"analysis_id": "chg_…", "change_type": "construction", "confidence": 0.80,
               "earliest_supported_time": "2023-07-01T00:00:00Z"},
    "thumbnail_url": "/api/v1/tiles/scn_…_196_545/thumbnail",
    "provenance": {"href": "/api/v1/provenance/search_result/res_…", "source_path": "/data/raw/demo/S2A_20230701.tif",
                   "checksum": "303f68…", "embedding_model": "mock-rs-embed", "embedding_version": "1.0.0",
                   "preprocessing_version": "preproc-1.0.0"}
  }],
  "stats": {"strategy": "filter_first", "filter_matches": 20, "change_locations_checked": 4, "change_detections": 1}
}
```

## Image-to-image search

```bash
# local path (must be inside DATA_ROOT or ALLOWED_INGEST_ROOTS)
curl -X POST $API/search/image -H 'content-type: application/json' \
     -d '{"image_path": "/data/raw/demo/S2A_20230901.tif", "top_k": 10, "min_quality": 0.5}'

# upload (GeoTIFF, PNG or JPEG); filters as a JSON string
curl -X POST $API/search/image/upload -F file=@chip.tif -F 'filters={"top_k": 10, "sensor": "MSI"}'
```

## Change analysis

```bash
curl -X POST $API/change/analyze -H 'content-type: application/json' -d '{
  "bbox": [74.99, 12.62, 75.04, 12.67],
  "start_date": "2023-01-01T00:00:00Z", "end_date": "2023-12-31T00:00:00Z",
  "change_types": ["construction", "water_extent_change"],
  "min_quality": 0.6
}'
```
```json
{
  "request_id": "req_…",
  "analysis_id": "chg_…", "change_type": "construction", "confidence": 0.80,
  "earliest_supported_time": "2023-07-01T00:00:00Z",
  "geometry": {"type": "Polygon", "coordinates": [[...changed-pixel footprint...]]},
  "evidence": [
    {"before_scene": "scn_…0110", "after_scene": "scn_…0301", "before_time": "2023-01-10T00:00:00Z", "after_time": "2023-03-01T00:00:00Z", "score": 0.0},
    {"before_scene": "scn_…0110", "after_scene": "scn_…0701", "before_time": "2023-01-10T00:00:00Z", "after_time": "2023-07-01T00:00:00Z", "score": 0.80},
    {"before_scene": "scn_…0110", "after_scene": "scn_…0901", "score": 0.81},
    {"before_scene": "scn_…0110", "after_scene": "scn_…1101", "score": 0.80}
  ],
  "detections": [ ...all detections, most confident first... ],
  "diagnostics": {"observations": 24, "locations": 4, "dropped_low_quality": 1, "pairs_evaluated": 16},
  "provenance": {"change_model": "feature-difference-change", "change_model_version": "1.0.0", "source_scenes": [...]}
}
```
The May acquisition was cloudy over the site, so it was removed by the quality gate *before*
differencing; the onset is therefore reported as the first supported clear observation (July), with
`last_unchanged_time` = March in `GET /change/{analysis_id}`. `factors` shows
`base_change_score`, `quality_factor`, `registration_factor`, `temporal_consistency_factor`,
`persistence`, `supporting_observations`, `transient` and the pair-level suppression factors.

For large AOIs add `"background": true` and poll the returned job.

## Discovery

```bash
curl -X POST $API/discovery/similar-sites -H 'content-type: application/json' \
     -d '{"tile_id": "scn_303f6867141a260c5c2b_196_545", "top_k": 50, "min_quality": 0.6}'

curl -X POST $API/discovery/cluster -H 'content-type: application/json' \
     -d '{"bbox": [74.99, 12.62, 75.04, 12.67], "date_from": "2023-01-01T00:00:00Z",
          "date_to": "2023-12-31T00:00:00Z", "algorithm": "hdbscan", "min_cluster_size": 5}'
```
Cluster items: `cluster_id, size, representative_tiles, centroid (GeoJSON Point),
bounding_geometry (convex hull), representative_embedding, cohesion`. Other algorithms: `kmeans`
(`n_clusters`), `dbscan` (`eps`, cosine).

## Review and feedback

```bash
curl -X POST $API/review -H 'content-type: application/json' \
     -d '{"query_id": "qry_…", "result_id": "res_…", "decision": "accept", "comment": "Confirmed construction", "analyst_id": "a.rao"}'

# change analyses can be reviewed directly by analysis_id
curl -X POST $API/review -H 'content-type: application/json' -d '{"result_id": "chg_…", "decision": "reject"}'

curl "$API/review/queue?min_confidence=0.3&change_type=construction&status=pending_review"
curl "$API/review/history?result_id=res_…"
curl  $API/feedback/statistics      # decisions, precision, per-type precision, calibration buckets, hard negatives
curl "$API/feedback/hard-negatives?min_score=0.5"
curl  $API/feedback/export          # labelled (query, tile, decision) triples for offline fine-tuning
```

## Provenance and export

```bash
curl $API/provenance/search_result/res_…
curl $API/provenance/change_analysis/chg_…
curl $API/provenance/tile/scn_303f6867141a260c5c2b_196_545

curl -OJ "$API/export/search/qry_…?format=geojson"     # or csv
curl -OJ "$API/export/change/chg_…?format=json"        # geojson | json | csv
```
Exports are also written to `DATA_ROOT/exports/`. Every feature/row carries source path, checksum,
model versions and a provenance link.

## Models and jobs

```bash
curl $API/models                    # active + historical embedding/change/quality/reranker/parser versions
curl $API/models/mock-rs-embed
curl -X POST $API/jobs -H 'content-type: application/json' -d '{"job_type": "reconcile_index"}'
curl "$API/jobs?status=failed"
```
