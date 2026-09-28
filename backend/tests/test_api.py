from tests.synth import scene_bbox

API = "/api/v1"


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get(f"{API}/health/ready").json()
    assert r["status"] == "ready", r


def test_ingestion_and_idempotency(client, env, ingested):
    assert ingested["succeeded"] == 6
    tiles = sum(r["tiles_created"] for r in ingested["results"])
    assert tiles == 24  # 6 scenes x 4 grid-aligned tiles
    count0 = client.get(f"{API}/health/ready").json()["checks"]["vector_index"]["count"]
    assert count0 == 24
    again = client.post(f"{API}/ingestion/scene", json={"path": str(env["paths"]["t0"])}).json()
    assert again["duplicate"] is True and again["created"] is False
    forced = client.post(f"{API}/ingestion/scene", json={"path": str(env["paths"]["t0"]), "force": True}).json()
    assert forced["embeddings_added"] == 0
    assert client.get(f"{API}/health/ready").json()["checks"]["vector_index"]["count"] == count0


def test_scene_metadata(client, ingested):
    body = client.get(f"{API}/scenes", params={"sensor": "MSI"}).json()
    assert body["total"] == 6
    s = body["items"][0]
    assert s["crs"] == "EPSG:32643" and s["platform"] == "Sentinel-2A" and s["acquisition_time"]
    assert s["geometry"]["type"] == "Polygon"
    tiles = client.get(f"{API}/scenes/{s['scene_id']}/tiles").json()["items"]
    assert len(tiles) == 4 and all(t["location_key"] for t in tiles)
    assert client.get(f"{API}/tiles/{tiles[0]['tile_id']}/thumbnail").status_code == 200


def test_incremental_only_adds_new(client, env, ingested):
    from datetime import datetime

    from tests.synth import landscape, write

    r = client.post(f"{API}/ingestion/incremental", json={"background": False}).json()
    assert r["discovered"] == [] and r["index_rebuilt"] is False
    write(env["root"] / "data" / "raw" / "new" / "S2A_20240115.tif", landscape(9), datetime(2024, 1, 15))
    r = client.post(f"{API}/ingestion/incremental", json={"background": False}).json()
    assert len(r["discovered"]) == 1 and r["succeeded"] == 1
    assert client.get(f"{API}/health/ready").json()["checks"]["vector_index"]["count"] == 28


def test_text_search_with_filters(client, ingested):
    body = {"query": "river", "top_k": 5, "bbox": scene_bbox(), "min_quality": 0.3,
            "date_from": "2023-01-01T00:00:00Z", "date_to": "2023-12-31T00:00:00Z", "sensor": "MSI"}
    r = client.post(f"{API}/search/text", json=body)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["total"] > 0 and res["parsed_query"]["objects"] == ["water"]
    top = res["results"][0]
    for k in ("tile_id", "scene_id", "geometry", "acquisition_time", "sensor", "platform", "semantic_score",
              "quality_score", "change_score", "final_score", "confidence", "thumbnail_url", "provenance"):
        assert k in top
    # river runs through the western tiles (x index even)
    assert top["tile_id"].split("_")[-2] == "195"
    assert all(r["acquisition_time"] < "2024" for r in res["results"])
    stored = client.get(f"{API}/search/{res['query_id']}").json()
    assert stored["total"] == res["total"]


def test_search_require_change(client, ingested):
    r = client.post(f"{API}/search/text", json={"query": "newly built structures near a river", "top_k": 5,
                                                 "require_change": True, "min_quality": 0.5}).json()
    assert r["total"] >= 1, r["stats"]
    top = r["results"][0]
    assert top["change"]["change_type"] == "construction" and top["change_score"] > 0.3
    assert top["tile_id"].endswith("_196_545")


def test_change_analyze_consensus_and_cloud(client, ingested):
    r = client.post(f"{API}/change/analyze", json={
        "bbox": scene_bbox(), "start_date": "2023-01-01T00:00:00Z", "end_date": "2023-12-31T00:00:00Z",
        "change_types": ["construction", "water_extent_change"], "min_quality": 0.5})
    assert r.status_code == 200, r.text
    res = r.json()
    assert len(res["detections"]) == 1, res["diagnostics"]
    d = res["detections"][0]
    assert d["change_type"] == "construction" and d["confidence"] > 0.5
    # cloudy May obs is gated out -> earliest supported is July, last unchanged is March
    assert d["earliest_supported_time"].startswith("2023-07-01")
    assert str(d["last_unchanged_time"]).startswith("2023-03-01")
    assert res["diagnostics"]["dropped_low_quality"] >= 1
    assert d["factors"]["supporting_observations"] >= 3
    assert d["provenance"]["source_scenes"]
    got = client.get(f"{API}/change/{d['analysis_id']}").json()
    assert got["analysis_id"] == d["analysis_id"] and got["evidence"]


def test_construction_site_is_top_detection(client, env, ingested):
    from app.db.session import SessionLocal
    from app.services.change_detection.service import ChangeAnalysisService

    with SessionLocal() as db:
        res = ChangeAnalysisService(db).analyze(scene_bbox(), None, None, None, 0.5, persist=False)
    confs = {d["location_key"]: d["confidence"] for d in res["detections"]}
    site = [k for k in confs if k.endswith(":196:545")]
    assert site and confs[site[0]] == max(confs.values())
    # the vegetation / river tiles must not be reported as changed
    assert all(c < 0.2 for k, c in confs.items() if k not in site)


def test_image_search_and_similar_sites(client, env, ingested):
    tiles = client.get(f"{API}/scenes", params={"limit": 1}).json()["items"]
    t = client.get(f"{API}/scenes/{tiles[0]['scene_id']}/tiles").json()["items"][0]
    r = client.post(f"{API}/search/image", json={"image_path": str(env["paths"]["t4"]), "top_k": 3})
    assert r.status_code == 200 and r.json()["total"] > 0
    s = client.post(f"{API}/discovery/similar-sites", json={"tile_id": t["tile_id"], "top_k": 5}).json()
    assert all(x["location_key"] != t["location_key"] for x in s["results"])
    with open(env["paths"]["t4"], "rb") as f:
        up = client.post(f"{API}/search/image/upload", files={"file": ("q.tif", f, "image/tiff")},
                         data={"filters": '{"top_k": 2}'})
    assert up.status_code == 200, up.text


def test_cluster(client, ingested):
    r = client.post(f"{API}/discovery/cluster", json={"algorithm": "kmeans", "n_clusters": 3})
    assert r.status_code == 200
    c = r.json()["clusters"]
    assert c and all(k in c[0] for k in ("cluster_id", "size", "representative_tiles", "centroid",
                                         "bounding_geometry", "representative_embedding"))
    assert client.post(f"{API}/discovery/cluster", json={"algorithm": "hdbscan", "min_cluster_size": 3}).status_code == 200


def test_review_feedback_provenance_export(client, ingested):
    s = client.post(f"{API}/search/text", json={"query": "buildings", "top_k": 3}).json()
    res = s["results"][0]
    q = client.get(f"{API}/review/queue", params={"item_type": "search_result"}).json()
    assert any(i["id"] == res["result_id"] for i in q["items"])
    rv = client.post(f"{API}/review", json={"query_id": s["query_id"], "result_id": res["result_id"],
                                            "decision": "reject", "comment": "false positive"})
    assert rv.status_code == 200 and rv.json()["decision"] == "reject"
    assert client.post(f"{API}/review", json={"result_id": res["result_id"], "decision": "maybe"}).status_code == 422
    hist = client.get(f"{API}/review/history", params={"result_id": res["result_id"]}).json()
    assert hist["total"] == 1
    stats = client.get(f"{API}/feedback/statistics").json()
    assert stats["decisions"]["reject"] >= 1

    prov = client.get(f"{API}/provenance/search_result/{res['result_id']}").json()
    assert prov["complete"] and prov["source_scenes"][0]["checksum"]
    assert prov["embedding_model"] and prov["preprocessing_version"]
    steps = {p["step"] for p in prov["processing_steps"]}
    assert {"ingest", "tile_quality", "embed", "rank"} <= steps

    gj = client.get(f"{API}/export/search/{s['query_id']}", params={"format": "geojson"}).json()
    assert gj["type"] == "FeatureCollection" and gj["features"][0]["properties"]["provenance"]["source_scenes"]
    csv = client.get(f"{API}/export/search/{s['query_id']}", params={"format": "csv"}).text
    assert "source_checksum" in csv and "embedding_model" in csv


def test_change_exports(client, ingested):
    r = client.post(f"{API}/change/analyze", json={"bbox": scene_bbox()}).json()
    aid = r["analysis_id"]
    for fmt in ("geojson", "json", "csv"):
        e = client.get(f"{API}/export/change/{aid}", params={"format": fmt})
        assert e.status_code == 200 and ("provenance" in e.text or "source_checksums" in e.text)


def test_models_jobs_and_errors(client, ingested):
    ms = client.get(f"{API}/models").json()["items"]
    assert {m["type"] for m in ms} >= {"embedding", "change", "quality", "reranker"}
    name = next(m["model_name"] for m in ms if m["type"] == "embedding")
    assert client.get(f"{API}/models/{name}").json()["active"]["checksum"]
    job = client.post(f"{API}/jobs", json={"job_type": "reconcile_index"}).json()
    assert client.get(f"{API}/jobs/{job['job_id']}").json()["status"] == "succeeded"
    assert client.get(f"{API}/scenes/nope").status_code == 404
    assert client.post(f"{API}/ingestion/scene", json={"path": "/etc/passwd"}).status_code == 403
    assert client.post(f"{API}/search/text", json={"query": "x", "bbox": [10, 10, 5, 5]}).status_code == 422


def test_index_reconcile_after_crash(client, ingested):
    """Simulate losing the on-disk index: startup reconcile restores it from vector backups."""
    from app.db.session import SessionLocal
    from app.services.embeddings.index_service import EmbeddingIndexService

    with SessionLocal() as db:
        svc = EmbeddingIndexService(db)
        n = svc.store.count()
        svc.store.rebuild(svc.store.get_vectors([]), [], [])  # wipe
        assert svc.store.count() == 0
        rep = svc.reconcile()
        assert rep["restored"] == n and svc.store.count() == n
