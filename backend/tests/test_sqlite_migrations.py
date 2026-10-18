from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text


def test_upgrade_preserves_rows_and_scopes_platform_constraints(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "migrated.db")
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "013")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text("INSERT INTO post_content_analyses(shortcode, platform, status, analyzed_at) VALUES ('same', 'instagram', 'ok', CURRENT_TIMESTAMP)"))
    command.upgrade(cfg, "head")
    command.check(cfg)
    schema = inspect(engine)
    assert schema.get_pk_constraint("post_content_analyses")["constrained_columns"] == ["platform", "shortcode"]
    assert schema.get_unique_constraints("account_reviews")[0]["column_names"] == ["brand_id", "platform", "username"]
    assert schema.get_unique_constraints("post_topic_reviews")[0]["column_names"] == ["platform", "shortcode", "topic_key"]
    assert schema.get_foreign_keys("post_topic_reviews") == []
    with engine.begin() as db:
        assert db.execute(text("SELECT status FROM post_content_analyses WHERE shortcode='same'")).scalar() == "ok"
        db.execute(text("INSERT INTO post_content_analyses(shortcode, platform, status, analyzed_at) VALUES ('same', 'tiktok', 'ok', CURRENT_TIMESTAMP)"))
    with pytest.raises(RuntimeError, match="sin revisiones de TikTok"):
        command.downgrade(cfg, "013")
    with engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM post_content_analyses")).scalar() == 2
    engine.dispose()
