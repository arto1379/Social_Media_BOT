"""
Application services.

This is where the actual behaviour lives. Web views stay thin - they parse a
request, call one service function and render - and the background scheduler
calls exactly the same functions. That symmetry is what lets the PRD's
"automatic in the background, but a user can also add a video manually" work
without two parallel implementations.

Module map:

* ``settings_service``  - runtime settings with defaults and validation
* ``audit_service``     - "who did what" recording
* ``account_service``   - credential access with transparent token refresh
* ``video_processing``  - ffprobe inspection and ffmpeg conversion to Shorts
* ``content_service``   - picks which video to publish next (money policy)
* ``upload_service``    - the publishing queue and its retry logic
* ``stats_service``     - statistics collection and dashboard aggregation
* ``trend_service``     - trend research and storage
* ``scheduler_service`` - registers the recurring background jobs
"""
