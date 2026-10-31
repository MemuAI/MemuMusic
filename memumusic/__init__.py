"""MemuMusic desktop music player."""

__version__ = "1.1"
# Offline fallback for the release date shown in Settings → Updates.
# MemuMusic never shipped a hard-coded date, so this stays empty until the
# date of the v{version} GitHub release is cached (see release_date.py):
# with no cache and no network the UI simply shows no date, as before.
RELEASE_DATE = ""
