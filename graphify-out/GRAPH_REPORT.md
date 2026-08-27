# Graph Report - Social_Media_BOT  (2026-08-27)

## Corpus Check
- 94 files · ~58,383 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1170 nodes · 2481 edges · 72 communities (65 shown, 7 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 196 edges (avg confidence: 0.9)
- Token cost: 239,444 input · 0 output

## Community Hubs (Navigation)
- Application Factory and Bootstrap
- Audit Log and User Admin
- Web Forms and Video Views
- Platform Adapter Registry
- User Model and Authentication
- Audit Trail and Web Tests
- Platform Data Contracts
- YouTube Analytics Collection
- Media Processing and Shorts
- Platform Error Hierarchy
- PlatformAdapter Abstract Contract
- Flask CLI Commands
- Roles and Permission Bits
- Database Model Package
- Trend Model and Seeding
- Monetisable Mix Rule
- Account OAuth Web Flow
- Upload Queue Planning
- Upload Service Tests
- Account Credentials Encryption
- Dashboard and Stats Templates
- PlatformAccount Model
- Configuration Objects
- Account Service Helpers
- Trend and Video Templates
- Settings Schema Service
- Pytest Fixtures
- UploadJob Lifecycle
- Video Publish Gating
- YouTube Trend Research
- Settings and Crypto Tests
- YouTube OAuth Flow
- Next Video Selection
- Settings Access and Planner
- Background Scheduler and Worker
- Shorts Eligibility Rules
- Statistics Snapshots and Totals
- Architecture and Ops Docs
- Dashboard Views and Health
- Dashboard JSON API
- Authentication Views
- Runtime Settings Model
- Statistics Retention and Charts
- Base Layout and Auth Pages
- Permission Catalogue
- Statistics Web Views
- Local Windows Environment Hazards
- Content Rights and Formatting
- Ubuntu Install Script
- Alembic Migration Environment
- Upload Metadata Policy
- OAuth Setup and Scheduling Docs
- Recent Upload Spacing
- Project Guides and Pagination
- Server Deployment Options
- Web Worker Deployment Split
- Frontend Queue Polling
- Stats Model Module
- Permission Bit Round-Trip
- Statistics Collection Cycle
- Google API Error Parsing
- Scheduler Accessor
- Audit Log Templates
- Multi-Checkbox Form Field
- Multi-Permission Access Decorator
- Security Package Init
- Services Package Init
- Web Package Init
- Backup Script
- Tests Package Init

## God Nodes (most connected - your core abstractions)
1. `permission_required()` - 53 edges
2. `make_video()` - 43 edges
3. `PlatformAccount` - 38 edges
4. `record()` - 33 edges
5. `CSRFOnlyForm` - 31 edges
6. `PlatformError` - 26 edges
7. `get_adapter()` - 26 edges
8. `UploadJob` - 25 edges
9. `PlatformAdapter` - 24 edges
10. `User` - 23 edges

## Surprising Connections (you probably didn't know these)
- `Test Server Setup` --semantically_similar_to--> `Local Windows PC Guide`  [INFERRED] [semantically similar]
  CONFIGURE.md → CONFIGURE_LOCAL.md
- `Let's Encrypt TLS with certbot` --semantically_similar_to--> `Loopback-Only Binding (HOST=127.0.0.1)`  [INFERRED] [semantically similar]
  CONFIGURE.md → CONFIGURE_LOCAL.md
- `Inline Shorts Re-Encode` --conceptually_related_to--> `convert()`  [INFERRED]
  app/templates/videos/form.html → app/web/videos.py
- `Single-Process Local Deployment` --semantically_similar_to--> `Web/Worker Scheduler Split`  [INFERRED] [semantically similar]
  CONFIGURE_LOCAL.md → README.md
- `Two systemd Services (Web and Worker)` --semantically_similar_to--> `Web/Worker Scheduler Split`  [INFERRED] [semantically similar]
  CONFIGURE.md → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **YouTube OAuth Connection Flow** — configure_youtube_api_credentials, configure_redirect_uri_mismatch, configure_oauth_testing_mode_expiry, configure_local_localhost_oauth_redirect, app_templates_accounts_form_connect_account_form, app_templates_accounts_index_redirect_uri_display, readme_token_encryption_at_rest [EXTRACTED 1.00]
- **Single Scheduler Ownership Pattern** — readme_scheduler_split, configure_two_service_split, configure_local_single_process_deployment, configure_local_task_scheduler_background_task, readme_background_automation_jobs, requirements_platform_conditional_wsgi_server [INFERRED 0.95]
- **Local Windows PC Constraints** — configure_local_broken_python_path, configure_local_powershell_51_constraints, configure_local_data_outside_onedrive, configure_local_env_file_bom_hazard, configure_local_utc_publishing_times [INFERRED 0.85]
- **Permission-Gated UI Surfaces** — app_templates_dashboard_index, app_templates_stats_index, app_templates_trends_index, app_templates_trends_detail, app_templates_videos_index, app_templates_videos_detail, app_templates_videos_jobs [EXTRACTED 1.00]
- **Rights-To-Publish Gate Flow** — app_templates_trends_index_no_reuse_policy, app_templates_videos_form_rights_monetisation_gate, app_templates_videos_detail_publish_readiness, app_templates_videos_detail_rights_attestation, app_templates_dashboard_index_library_health_meter [INFERRED 0.85]
- **Live Upload Queue Pipeline** — app_templates_dashboard_index_live_queue_contract, app_templates_videos_jobs, app_templates_videos_jobs_terminal_state_actions, app_web_api_queue, app_web_videos_cancel_job, app_web_videos_retry_job [INFERRED 0.85]

## Communities (72 total, 7 thin omitted)

### Community 0 - "Application Factory and Bootstrap"
Cohesion: 0.07
Nodes (44): Flask extension singletons. They are created here without an application so…, _check_secrets(), create_app(), _init_extensions(), _prepare_directories(), Application factory. ``create_app()`` is the single place where the pieces are…, Bind the extension singletons to this application., Attach every part of the web interface. (+36 more)

### Community 1 - "Audit Log and User Admin"
Cohesion: 0.10
Nodes (42): permission_required(), Require a single permission bit; 403 otherwise., bits_from_keys(), Turn an iterable of permission keys (from a form) into a bitmask., _client_ip(), Best-effort client IP. Behind nginx the real address is in X-Forwarded-For;…, Record one action. *action* is a dotted verb ("video.publish"). *user* defaults…, Most recent entries, newest first (for the audit log page). (+34 more)

### Community 2 - "Web Forms and Video Views"
Cohesion: 0.09
Nodes (42): LoginForm, QueueUploadForm, Form definitions and validation. Every form inherits from ``FlaskForm``, which…, Fields shared by the upload form and the edit form., Add a new video by uploading a file through the website., Edit an existing video's metadata., Explicit confirmation that the operator may publish this footage. Deliberately…, Queue a video for publishing on a chosen account. (+34 more)

### Community 3 - "Platform Adapter Registry"
Cohesion: 0.08
Nodes (35): adapter_names(), all_adapters(), get_adapter(), Adapter registry. Adapters register themselves at import time with the…, Raised when a platform key has no registered adapter., Return the adapter registered under *name*., Every registered adapter, ordered by display name (for menus)., Machine keys of every registered adapter. (+27 more)

### Community 4 - "User Model and Authentication"
Cohesion: 0.06
Nodes (24): load_user(), datetime, Users and roles. Access control model: * A :class:`Role` carries a permission…, Hash and store *password* (Werkzeug picks a strong default KDF)., Constant-time comparison of *password* against the stored hash., Role bits OR individual grants; administrators get everything., True when the user holds *permission* (bitmask constant)., Readable list of everything this user may do. (+16 more)

### Community 5 - "Audit Trail and Web Tests"
Cohesion: 0.06
Nodes (20): AuditLog, datetime, Audit trail. Anything that changes access, credentials or published output is…, _utcnow(), Web interface behaviour. Authentication, access control and that every page…, A GET logout link could be triggered by an image tag on another site., A broken template or a bad url_for shows up here immediately., Monitoring must not need a session. (+12 more)

### Community 6 - "Platform Data Contracts"
Cohesion: 0.09
Nodes (20): AccountInfo, AuthStart, ChannelMetrics, One trending topic discovered by research., Everything needed to send a browser into the platform's consent screen., Identity of the channel/profile behind a set of credentials., Per-video performance numbers, normalised across platforms., Channel/profile level totals. (+12 more)

### Community 7 - "YouTube Analytics Collection"
Cohesion: 0.11
Nodes (32): _chunks(), enrich_with_analytics(), fetch_channel_identity(), fetch_channel_metrics(), fetch_public_stats(), fetch_video_metrics(), Any, Statistics collection. Numbers come from two different APIs and are merged into… (+24 more)

### Community 8 - "Media Processing and Shorts"
Cohesion: 0.11
Nodes (33): _binary(), checksum(), convert_to_shorts(), extract_thumbnail(), inspect(), media_path(), MediaError, probe() (+25 more)

### Community 9 - "Platform Error Hierarchy"
Cohesion: 0.12
Nodes (26): PlatformAuthError, PlatformError, PlatformNotConfigured, PlatformQuotaError, PlatformRetryableError, RuntimeError, The platform adapter contract. Every social network the bot supports implements…, Base class for every platform-level failure. (+18 more)

### Community 10 - "PlatformAdapter Abstract Contract"
Cohesion: 0.08
Nodes (17): ABC, PlatformAdapter, Any, ProgressCallback, Base class for a social platform integration., True when API client credentials are present in the configuration., Message shown in the UI when :meth:`is_configured` is False., Build the consent-screen URL the operator's browser is sent to. (+9 more)

### Community 11 - "Flask CLI Commands"
Cohesion: 0.13
Nodes (29): check_command(), create_admin_command(), init_db_command(), list_users_command(), Management commands. Run them with the ``flask`` launcher from the project…, Create or refresh the built-in roles., Create the first administrator. This is what the PRD means by "one admin…, Set a new password for USERNAME and clear any lockout. (+21 more)

### Community 12 - "Roles and Permission Bits"
Cohesion: 0.09
Nodes (22): A named bundle of permissions that can be assigned to users., True when this role includes *permission*., Permission keys for pre-checking boxes in the role editor., Human-readable labels used in the roles table., Role, Permission, Individual capability bits. Values are powers of two and are permanent., Access control. The PRD's requirement is specific: the administrator can give… (+14 more)

### Community 13 - "Database Model Package"
Cohesion: 0.11
Nodes (21): Database models. Every table lives in its own module so a change to, say, the…, datetime, Trend research results. The bot periodically asks each platform what is…, Where a researched topic stands in the production pipeline., TrendStatus, _utcnow(), datetime, The upload queue. Publishing is never done inline with a web request: the… (+13 more)

### Community 14 - "Trend Model and Seeding"
Cohesion: 0.10
Nodes (22): setter, One trending topic observed on one platform at one time., Parsed ``signals_json``; an empty dict if it is missing/corrupt., Keywords as a clean list, ready to seed a video's tags., Trend, Seed a new video's metadata from a researched trend. Used by the "create a…, suggest_metadata_from_trend(), keyword_cloud() (+14 more)

### Community 15 - "Monetisable Mix Rule"
Cohesion: 0.11
Nodes (25): current_monetizable_ratio(), Share of the last *window* automatic uploads that were monetisable. Returns 0.0…, _naive_utcnow(), datetime, The money rule. "The point is making money from video so majority of video…, The same video must not be published to the same channel twice., A pending job already covers this video., Trend-linked videos are time sensitive, so they jump the queue. (+17 more)

### Community 16 - "Account OAuth Web Flow"
Cohesion: 0.15
Nodes (25): connect(), create(), delete(), disconnect(), index(), oauth_callback(), login_required, route (+17 more)

### Community 17 - "Upload Queue Planning"
Cohesion: 0.12
Nodes (23): cancel_job(), due_jobs(), _has_open_job(), next_publishing_slot(), plan_for_account(), process_due_jobs(), datetime, The publishing queue. Two halves: * **Planning** -… (+15 more)

### Community 18 - "Upload Service Tests"
Cohesion: 0.17
Nodes (23): queue_video(), Create an upload job for *video* on *account*. Raises ValueError when the video…, make_video(), Factory for publishable videos. Defaults produce a video that passes every…, patched_platform(), fixture, The publishing queue. Covers scheduling arithmetic, the pre-publish safety…, Replace the adapter lookup and credential fetch with test doubles. (+15 more)

### Community 19 - "Account Credentials Encryption"
Cohesion: 0.14
Nodes (21): datetime, Connected social-media accounts. One row per channel/profile the bot may…, _utcnow(), decrypt_json(), decrypt_text(), encrypt_json(), encrypt_text(), EncryptionError (+13 more)

### Community 20 - "Dashboard and Stats Templates"
Cohesion: 0.13
Nodes (23): Active, connected accounts - the ones automation is allowed to use., usable_accounts(), Dashboard Index Template, Dependency-Free CSS Bar Chart, Monetisable Library Mix Meter, Live Queue DOM Contract, System Health Panel, Statistics Index Template (+15 more)

### Community 21 - "PlatformAccount Model"
Cohesion: 0.10
Nodes (15): PlatformAccount, Any, Short status word for the accounts table., A single authorised destination channel on one platform., Encrypt and store the OAuth credential blob., Decrypt the credential blob, or None when the account is unlinked., Forget the tokens (used by the "disconnect" button)., True when a credential blob is present. (+7 more)

### Community 22 - "Configuration Objects"
Cohesion: 0.13
Nodes (18): BaseConfig, DevelopmentConfig, _env_bool(), _env_int(), _env_path(), get_config(), ProductionConfig, Path (+10 more)

### Community 23 - "Account Service Helpers"
Cohesion: 0.18
Nodes (18): clear_error(), credentials_for(), mark_error(), parse_expiry(), Any, datetime, Platform account helpers. Everything that needs to call a platform API goes…, Verify an account by making one cheap API call. Used by the "Test connection"… (+10 more)

### Community 24 - "Trend and Video Templates"
Cohesion: 0.16
Nodes (19): Trend Detail Template, Trends Index Template, Trend-As-Subject, Never Re-Upload, Views-Per-Hour Trend Ranking, Publishing Readiness Gate, Video Form Template, Rights And Monetisation Gate, Inline Shorts Re-Encode (+11 more)

### Community 25 - "Settings Schema Service"
Cohesion: 0.12
Nodes (18): all_values(), _clamp(), grouped_schema(), _parse_times(), Any, Every setting, defaults filled in - used by the settings page., Settings grouped by section, in catalogue order (drives the form)., Keep a numeric setting inside its documented range. (+10 more)

### Community 26 - "Pytest Fixtures"
Cohesion: 0.16
Nodes (17): account(), admin(), analyst(), app(), client(), db(), logged_in_admin(), fixture (+9 more)

### Community 27 - "UploadJob Lifecycle"
Cohesion: 0.14
Nodes (13): Wall-clock time the transfer took, for the job history table., One video going to one platform account at one point in time., True when no further work will happen on this job., True when the retry budget still allows another attempt., UploadJob, _published_jobs(), Successful uploads for this account that have a platform id., _fail() (+5 more)

### Community 28 - "Video Publish Gating"
Cohesion: 0.12
Nodes (11): True when this asset counts towards the revenue side of the mix., Readable licence name for templates., Tags split into a clean list for the API payload., Everything that currently prevents this video from being published. The UI…, Convenience wrapper around :meth:`blocking_reasons`., One publishable asset and its metadata., Video, _rank() (+3 more)

### Community 29 - "YouTube Trend Research"
Cohesion: 0.15
Nodes (16): _category_names(), fetch_trends(), _parse_published(), Any, datetime, Trend research. Method: read the ``mostPopular`` chart for the configured…, Return up to *limit* trending topics for *region*, best first., Most frequent keywords across a set of trends. A word that shows up across many… (+8 more)

### Community 30 - "Settings and Crypto Tests"
Cohesion: 0.15
Nodes (16): mask_secret(), Render a secret for display, e.g. "AIza...9fQ2". Used everywhere the UI has to…, coerce(), Turn a submitted form value into the type the setting expects. Anything…, Supporting services: settings, encryption, Shorts format rules and statistics., Stored paths are relative so the media directory can be moved., An empty schedule would silently stop publishing - refuse to store it., The stored blob must not contain the token in readable form. (+8 more)

### Community 31 - "YouTube OAuth Flow"
Cohesion: 0.19
Nodes (15): build_authorization_url(), client_config(), credentials_to_dict(), exchange_code(), _flow(), Any, YouTube OAuth 2.0. Flow used by the web interface: 1.…, Turn the full callback URL into a serialisable credential blob. (+7 more)

### Community 32 - "Next Video Selection"
Cohesion: 0.12
Nodes (16): pick_next_video(), Choose the next video to publish to *account*., The outcome of a pick, including why it turned out that way., Selection, Once the mix drops under the target the next pick must be monetisable., With no monetisable material left, filler is better than nothing., A video nobody has approved can never be picked., An unverified licence is not publishable even if somebody ticked approve. (+8 more)

### Community 33 - "Settings Access and Planner"
Cohesion: 0.17
Nodes (16): get(), Read a setting. Order of precedence: stored value, schema default, explicit…, Write a setting (validated and coerced against the schema). Named ``set_value``…, set_value(), plan_automatic_uploads(), Run the planner for every usable account., A typo in the form must not schedule 500 uploads a day., test_missing_setting_falls_back_to_the_schema_default() (+8 more)

### Community 34 - "Background Scheduler and Worker"
Cohesion: 0.15
Nodes (14): Create and start the scheduler for *app* (idempotent)., Stop the scheduler if it is running., Wrap a job so it runs inside an app context and can never kill the thread.…, Plan the next automatic upload, then run whatever is due., Research trends on every platform that supports it., run_trend_cycle(), run_upload_cycle(), shutdown() (+6 more)

### Community 35 - "Shorts Eligibility Rules"
Cohesion: 0.19
Nodes (14): MediaInfo, Everything about *info* that disqualifies the file as a Short., What ffprobe could tell us about a file., True when the frame is taller than it is wide., shorts_problems(), _info(), Square is not vertical - YouTube will not treat it as a Short., 180 seconds is the documented limit, so it must not be off by one. (+6 more)

### Community 36 - "Statistics Snapshots and Totals"
Cohesion: 0.16
Nodes (12): One measurement of one video (or channel) at one moment., True for channel totals rather than a single video., StatSnapshot, latest_channel_stats(), The newest channel-level snapshot per account, keyed by account id., Headline numbers for the dashboard, summed across every platform., totals(), Snapshots accumulate; the totals must not sum a video's whole history. (+4 more)

### Community 37 - "Architecture and Ops Docs"
Cohesion: 0.15
Nodes (14): Accounts Page, Redirect URI Display Panel, Backups and the ENCRYPTION_KEY, Local Backup Procedure, Append-Only Statistics Snapshots, Background Automation Jobs, Flask CLI Command Reference, Platform Adapter Plugin Architecture (+6 more)

### Community 38 - "Dashboard Views and Health"
Cohesion: 0.20
Nodes (12): library_summary(), Counts the dashboard uses to warn before the library runs dry., Synchronous Manual Job Trigger, health(), _health_checks(), index(), login_required, route (+4 more)

### Community 39 - "Dashboard JSON API"
Cohesion: 0.21
Nodes (12): job_status(), Job names and next run times, for the status panel on the dashboard., library(), login_required, route, Background job names and next run times., Headline totals across every platform., Daily view totals for the last 30 days. (+4 more)

### Community 40 - "Authentication Views"
Cohesion: 0.20
Nodes (12): change_password(), login(), logout(), profile(), login_required, route, Sign out. POST-only so a stray link cannot end somebody's session., Change your own password. (+4 more)

### Community 41 - "Runtime Settings Model"
Cohesion: 0.20
Nodes (8): Any, datetime, setter, Runtime settings. Two kinds of configuration exist in this project and they are…, A single key/value pair edited through the settings page., Decoded value; falls back to the raw string if it is not JSON., Setting, _utcnow()

### Community 42 - "Statistics Retention and Charts"
Cohesion: 0.18
Nodes (11): Housekeeping: drop data that is too old to be useful., run_maintenance_cycle(), prune_old_snapshots(), datetime, Total views per day over the last *days*, for the dashboard chart. Each point…, Every snapshot for one video, oldest first (the per-video chart)., Delete snapshots older than *keep_days*. Called by a weekly maintenance job: at…, _utcnow() (+3 more)

### Community 43 - "Base Layout and Auth Pages"
Cohesion: 0.31
Nodes (11): Connect an Account Form, Sign-In Page, My Account Page, Base Layout Template, Permission-Aware Navigation, Error Page Template, render_field Macro, Flash Messages Partial (+3 more)

### Community 44 - "Permission Catalogue"
Cohesion: 0.29
Nodes (7): describe(), grouped(), PermissionInfo, The permission catalogue. The PRD requires that the administrator can give each…, Human-readable labels for a bitmask, for display in tables., Permissions grouped by section, preserving catalogue order., UI metadata for one permission bit (used to render the role editor).

### Community 45 - "Statistics Web Views"
Cohesion: 0.29
Nodes (8): latest_video_stats(), The newest snapshot for each video, keyed by video id. Done in two queries (max…, index(), login_required, route, Totals, per-platform breakdown and the leaderboard., Collect fresh statistics right now., refresh()

### Community 46 - "Local Windows Environment Hazards"
Cohesion: 0.25
Nodes (8): Broken python on PATH (Microsoft Store Stub), Data Folder Outside OneDrive, .env Byte-Order-Mark Hazard, Loopback-Only Binding (HOST=127.0.0.1), PowerShell 5.1 Syntax Constraints, .env Machine Configuration, The Money Rule (Monetisable Running Mix), Settings Page Operational Configuration

### Community 47 - "Content Rights and Formatting"
Cohesion: 0.29
Nodes (8): ffmpeg Install on Windows, Rights Confirmation Step, YouTube API Daily Quota, Content Rights Policy, Publish Gate (Video.blocking_reasons), Shorts Formatting Pipeline, View-Velocity Trend Ranking, Retryable vs Permanent Upload Failure

### Community 48 - "Ubuntu Install Script"
Cohesion: 0.43
Nodes (7): DEBIAN_FRONTEND, die(), ok(), run_flask(), say(), install_ubuntu.sh script, warn()

### Community 49 - "Alembic Migration Environment"
Cohesion: 0.39
Nodes (7): get_engine(), get_engine_url(), get_metadata(), Run migrations in 'offline' mode. This configures the context with just a URL…, Run migrations in 'online' mode. In this scenario we need to create an Engine…, run_migrations_offline(), run_migrations_online()

### Community 50 - "Upload Metadata Policy"
Cohesion: 0.29
Nodes (7): build_metadata(), Turn a Video row into the normalised metadata dict adapters consume. Two policy…, Most royalty-free licences require the credit line to be published., test_metadata_appends_the_shorts_hashtag(), test_metadata_does_not_duplicate_an_existing_hashtag(), test_metadata_includes_attribution(), test_metadata_splits_tags_into_a_list()

### Community 51 - "OAuth Setup and Scheduling Docs"
Cohesion: 0.38
Nodes (7): First Run: Connect, Add, Publish, localhost OAuth Redirect URI, UTC Publishing Times and Timezone Conversion, OAuth Testing Mode 7-Day Token Expiry, redirect_uri_mismatch (Error 400), Test Server Setup, YouTube API Credentials Setup

### Community 52 - "Recent Upload Spacing"
Cohesion: 0.33
Nodes (6): last_upload_time(), datetime, Successful uploads to *account* in the last *hours* (daily-limit check)., When this account last published, for the minimum-spacing rule., recent_upload_count(), _utcnow()

### Community 53 - "Project Guides and Pagination"
Cohesion: 0.47
Nodes (6): render_pagination Macro, Configuration Guide, flask check Configuration Diagnostic, Local Windows PC Guide, Troubleshooting Reference, Social Media BOT

### Community 54 - "Server Deployment Options"
Cohesion: 0.47
Nodes (6): Dedicated System User with No Login Shell, Let's Encrypt TLS with certbot, Moving to PostgreSQL, SQLite URL Slash Convention, Ubuntu Automatic Install, Ubuntu Manual Install

### Community 55 - "Web Worker Deployment Split"
Cohesion: 0.47
Nodes (6): Single-Process Local Deployment, Windows Task Scheduler Background Task, Two systemd Services (Web and Worker), Windows Server Setup, Web/Worker Scheduler Split, Platform-Conditional WSGI Server

### Community 58 - "Stats Model Module"
Cohesion: 0.67
Nodes (3): datetime, Performance statistics. The PRD asks for "statistics of views over all social…, _utcnow()

### Community 59 - "Permission Bit Round-Trip"
Cohesion: 0.50
Nodes (4): keys_from_bits(), Inverse of :func:`bits_from_keys` - used to pre-check form boxes., A form submission converts to a mask and back without loss., test_bits_and_keys_round_trip()

### Community 60 - "Statistics Collection Cycle"
Cohesion: 0.50
Nodes (4): Refresh statistics for every connected account., run_statistics_cycle(), collect_all(), Refresh statistics for every connected account.

### Community 61 - "Google API Error Parsing"
Cohesion: 0.67
Nodes (3): _error_details(), Pull ``(reason, message)`` out of a Google API error body., HttpError

### Community 62 - "Scheduler Accessor"
Cohesion: 0.67
Nodes (3): get_scheduler(), The running scheduler, or None when automation is disabled., BackgroundScheduler

### Community 63 - "Audit Log Templates"
Cohesion: 0.67
Nodes (3): Audit Log Template, System Actor In Audit Trail, Attributed Rights Confirmation

### Community 64 - "Multi-Checkbox Form Field"
Cohesion: 0.67
Nodes (3): MultiCheckboxField, A list of checkboxes - used for granting permissions to a role., SelectMultipleField

## Knowledge Gaps
- **11 isolated node(s):** `backup.sh script`, `DEBIAN_FRONTEND`, `Moving to PostgreSQL`, `Broken python on PATH (Microsoft Store Stub)`, `ffmpeg Install on Windows` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PlatformAccount` connect `PlatformAccount Model` to `Next Video Selection`, `Application Factory and Bootstrap`, `Flask CLI Commands`, `Database Model Package`, `Monetisable Mix Rule`, `Account OAuth Web Flow`, `Upload Queue Planning`, `Upload Service Tests`, `Account Credentials Encryption`, `Dashboard and Stats Templates`, `Recent Upload Spacing`, `Account Service Helpers`, `Pytest Fixtures`, `UploadJob Lifecycle`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `User` connect `User Model and Authentication` to `Audit Log and User Admin`, `Flask CLI Commands`, `Roles and Permission Bits`, `Database Model Package`, `Pytest Fixtures`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `PlatformError` connect `Platform Error Hierarchy` to `Application Factory and Bootstrap`, `Platform Adapter Registry`, `YouTube Analytics Collection`, `Trend Model and Seeding`, `Account OAuth Web Flow`, `Upload Queue Planning`, `Upload Service Tests`, `Account Service Helpers`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Are the 40 inferred relationships involving `make_video()` (e.g. with `test_already_published_video_is_not_repicked()` and `test_falls_back_rather_than_wasting_a_slot()`) actually correct?**
  _`make_video()` has 40 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `CSRFOnlyForm` (e.g. with `delete()` and `disconnect()`) actually correct?**
  _`CSRFOnlyForm` has 21 INFERRED edges - model-reasoned connections that need verification._
- **What connects `backup.sh script`, `DEBIAN_FRONTEND`, `Moving to PostgreSQL` to the rest of the system?**
  _11 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Application Factory and Bootstrap` be split into smaller, more focused modules?**
  _Cohesion score 0.06604324956165984 - nodes in this community are weakly interconnected._