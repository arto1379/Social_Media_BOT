"""
The web interface.

One blueprint per area of the site, each in its own module:

* ``auth``      - sign in, sign out, change password
* ``dashboard`` - the home page, system health and manual job triggers
* ``videos``    - the video library: upload, edit, approve, queue, job history
* ``accounts``  - connecting platform accounts and handling API tokens
* ``stats``     - view statistics across every platform
* ``trends``    - researched trending topics
* ``users``     - user and role administration
* ``settings``  - runtime settings
* ``api``       - a small JSON API used by the pages that refresh themselves

Views stay thin: parse the request, call a service in app/services, render.
"""
