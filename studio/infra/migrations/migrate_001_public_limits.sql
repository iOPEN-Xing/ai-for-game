CREATE TABLE request_limits (
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    expires INTEGER NOT NULL,
    used INTEGER NOT NULL,
    PRIMARY KEY (scope, subject)
);
CREATE INDEX request_limits_expiry ON request_limits(expires);
