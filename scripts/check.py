"""Run the same offline source, contract and workflow checks locally and in CI."""

import json
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


class InlineScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.is_script = False
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            self.is_script = not attrs.get("src") and attrs.get("type", "") in {
                "",
                "module",
                "text/javascript",
                "application/javascript",
            }
            if self.is_script:
                self.scripts.append("")

    def handle_data(self, data):
        if self.is_script:
            self.scripts[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.is_script = False


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, **kwargs)


def main():
    ruff = shutil.which("ruff")
    lint = [ruff] if ruff else ["uvx", "--from", "ruff==0.17.6", "ruff"]
    targets = ["app.py", "studio", "scripts", "tests"]
    run(*lint, "check", *targets)
    run(*lint, "format", "--check", *targets)
    run(PYTHON, "-m", "scripts.sync_web_routes", "--check")
    for folder in ("studio/web", "studio/engine", "tests/browser", "examples"):
        files = (
            (ROOT / folder).rglob("*")
            if folder != "tests/browser"
            else (ROOT / folder).glob("*")
        )
        for path in sorted(files):
            if path.suffix in {".mjs", ".js"}:
                run("node", "--input-type=module", "--check", input=path.read_text())
            if path.suffix == ".html":
                html = InlineScripts()
                html.feed(path.read_text())
                for source in html.scripts:
                    run("node", "--input-type=module", "--check", input=source)
    for script in sorted((ROOT / "deploy").glob("*.sh")):
        run("bash", "-n", str(script))
    replay = subprocess.run(
        [PYTHON, "-m", "scripts.evaluate_agents"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
    )
    if replay.returncode:
        print(replay.stdout, file=sys.stderr)
        raise SystemExit(replay.returncode)
    result = json.loads(replay.stdout)
    print(
        f"{result['suite']} · {result['passed']}/{result['total']} cases · SHA-256 {result['sha256']}",
        flush=True,
    )
    run(PYTHON, "-m", "unittest", "discover", "-s", "tests", "-v")


if __name__ == "__main__":
    main()
