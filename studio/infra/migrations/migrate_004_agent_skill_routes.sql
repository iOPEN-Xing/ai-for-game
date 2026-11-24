CREATE TABLE agent_run_skill_routes (
    run TEXT PRIMARY KEY REFERENCES agent_runs(id),
    routes TEXT NOT NULL
);
