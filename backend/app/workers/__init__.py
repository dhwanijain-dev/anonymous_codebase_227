_loaded = False


def load_handlers() -> None:
    """Import worker modules so their @register handlers are available."""
    global _loaded
    if not _loaded:
        from app.workers import change_worker, embedding_worker, ingestion_worker  # noqa: F401

        _loaded = True
