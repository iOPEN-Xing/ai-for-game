CREATE TABLE revision_drafts (
    rev TEXT PRIMARY KEY REFERENCES revisions(id), serial INTEGER NOT NULL,
    summary TEXT NOT NULL CHECK(length(summary) <= 2400)
);
INSERT INTO revision_drafts
SELECT id, serial, substr(json_extract(docs,'$.research_draft'),1,2400)
FROM revisions WHERE stage='interpret' AND json_type(docs,'$.research_draft')='text';
UPDATE revisions SET docs=json_remove(docs,'$.research_draft')
WHERE json_type(docs,'$.research_draft') IS NOT NULL;
CREATE INDEX IF NOT EXISTS history_revision_cursor ON history(rev,id);

CREATE TABLE knowledge_reviews (
    id INTEGER PRIMARY KEY, entry TEXT NOT NULL REFERENCES knowledge(id),
    status TEXT NOT NULL CHECK(status IN ('active','rejected','unverified','superseded')),
    at INTEGER NOT NULL, note TEXT NOT NULL, replacement TEXT REFERENCES knowledge(id)
);
CREATE INDEX knowledge_review_cutoff ON knowledge_reviews(entry,at DESC,id DESC);
INSERT INTO knowledge_reviews(entry,status,at,note)
SELECT id,status,unixepoch(),'旧版审核状态迁移，原审核时间未记录。'
FROM knowledge WHERE status IN ('active','rejected','unverified','superseded');

CREATE TABLE model_call_totals (
    role TEXT NOT NULL, provider TEXT NOT NULL, outcome TEXT NOT NULL,
    calls INTEGER NOT NULL, elapsed_ms INTEGER NOT NULL, usage_reports INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
    PRIMARY KEY(role,provider,outcome)
);
CREATE TABLE worker_health (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    heartbeat INTEGER NOT NULL, last_reconciled INTEGER, failures INTEGER NOT NULL DEFAULT 0
);

CREATE VIEW knowledge_admissions AS
SELECT r.entry, r.at AS admitted, r.note, (
    SELECT n.at FROM knowledge_reviews n WHERE n.entry=r.entry AND n.id>r.id ORDER BY n.id LIMIT 1
) AS withdrawn FROM knowledge_reviews r WHERE r.status='active';

-- Earlier versions stored the decision and its text without a reliable decision time.
CREATE TABLE dead_end_records (
    proposal TEXT PRIMARY KEY REFERENCES proposals(id), at INTEGER NOT NULL,
    title TEXT NOT NULL, reason TEXT NOT NULL
);
INSERT INTO dead_end_records(proposal,at,title,reason)
SELECT p.id,unixepoch(),coalesce(json_extract(p.doc,'$.bet.title'),g.title),
    coalesce(json_extract(e.result,'$.conclusion'),'旧版已驳回，原审核时间未记录。')
FROM proposals p JOIN games g ON g.id=p.game LEFT JOIN experiments e ON e.proposal=p.id
WHERE p.status='rejected' OR json_extract(e.result,'$.attribution')='假设错';
CREATE INDEX history_game_kind_time ON history(game,kind,at DESC,id DESC);
