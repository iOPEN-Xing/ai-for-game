"""Build a disposable, published trail game for browser and container CI."""

import sys
from pathlib import Path

from studio.infra.backup import export_backup
from tests.support import StudioCase


def seed(archive):
    case = StudioCase()
    case.setUp()
    try:
        case.draft(choice=1)
        case.publish()
        campaign = case.post(
            f"games/{case.game}/campaigns",
            {
                "name": "CI 试玩",
                "action_label": "查看试玩活动",
                "action_url": "https://v1-fixture.invalid/offer",
            },
        )
        with archive.open("xb") as stream:
            export_backup(Path(case.tmp.name), stream)
        return case.game, campaign["id"]
    finally:
        case.doCleanups()


if __name__ == "__main__":
    game, campaign = seed(Path(sys.argv[1]))
    print("STUDIO_TEST_GAME=" + game)
    print("STUDIO_TEST_CAMPAIGN=" + campaign)
