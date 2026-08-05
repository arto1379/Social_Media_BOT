"""
YouTube integration.

Split by responsibility so each file stays small and readable:

* ``auth.py``      - OAuth 2.0 consent flow and credential (de)serialisation
* ``client.py``    - builds API service objects, classifies API errors
* ``uploader.py``  - resumable video upload and thumbnails
* ``analytics.py`` - view/like/revenue statistics
* ``trends.py``    - trending topic research
* ``adapter.py``   - glues the above into one :class:`PlatformAdapter`

Importing the package registers the adapter.
"""

from app.platforms.youtube.adapter import YouTubeAdapter  # noqa: F401

__all__ = ["YouTubeAdapter"]
