# ChangeScope — Intelligent Website Change Detector

ChangeScope is a lightweight, reliable web application that monitors websites over time and detects changes in their textual content, visual appearance, availability, and key elements.

---

## Live Demo

- **Hosted Application URL**: https://changescope.onrender.com/
- **Local Application Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/) *(or [http://localhost:8000/](http://localhost:8000/))*
- **Interactive API Documentation (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Alternative API Documentation (ReDoc)**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Backend Health Check Endpoint**: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

> **Default Demo Account Credentials:**
> - **Email**: `testuser@example.com`
> - **Password**: `Password123!`
> *(Alternatively, click the **"Use default admin credentials"** button directly on the sign-in modal)*

---

## Table of Contents

- [Live Demo](#live-demo)
- [Project Overview & Architecture](#project-overview--architecture)
- [Technology Stack](#technology-stack)
- [Windows Setup & Installation](#windows-setup--installation)
- [Running the Application](#running-the-application)
- [Adding Monitors & Testing Change Detection](#adding-monitors--testing-change-detection)
- [Time Machine & Version History](#time-machine--version-history)
- [Visual Change Detection & Screenshot Diffing](#visual-change-detection--screenshot-diffing)
- [Change Heatmap & Monitoring Analytics](#change-heatmap--monitoring-analytics)
- [Notifications and Alerts System](#notifications-and-alerts-system)
- [Automated Monitoring Scheduler](#automated-monitoring-scheduler)
- [Secure User Accounts & Authentication](#secure-user-accounts--authentication)
- [Automated Testing & Test Suite](#automated-testing--test-suite)

---

## Project Overview & Architecture

ChangeScope is structured with modular separation of concerns between frontend presentation, API routing, database models, site monitoring, and background scheduling.

```text
ChangeScope/
├── backend/
│   ├── main.py          # FastAPI application entrypoint, CORS setup, and route mounts
│   ├── auth.py          # Bcrypt password hashing, JWT tokens, cookies, rate limiter, and user dependencies
│   ├── database.py      # SQLite database engine, session management, and auto-migration
│   ├── models.py        # SQLAlchemy 2.0 ORM models (User, MonitoredSite, SiteSnapshot, DetectedChange, SiteCheckLog, Notification, NotificationPreference, SchedulerSetting)
│   ├── schemas.py       # Pydantic validation schemas for auth, API requests, visual diffs, analytics, notifications, and scheduler
│   ├── monitoring.py    # Fetching engine, SSRF security validation, and text extraction
│   ├── visual.py        # Headless Playwright capture, Pillow diff comparison & overlay generator
│   ├── analytics.py     # Aggregated analytics metrics, 7x24 hourly matrix, and calendar heatmap
│   ├── notifications.py # Persistent alert dispatch, event deduplication, and notification preferences
│   └── scheduler.py     # Background task scheduler with APScheduler, thread pool concurrency & check mutex locks
├── data/
│   └── screenshots/     # Dedicated local screenshot directory (isolated from SQLite)
├── frontend/
│   ├── index.html       # Single-page dashboard interface with Auth Modal, User Profile, Heatmap, Analytics, Notifications, Time Machine, and Scheduler
│   ├── styles.css       # Dark/light theme design system, auth cards, user dropdowns, diff viewers, notification feeds, and scheduler widgets
│   └── app.js           # Vanilla JS controller with JWT auth interceptor, account controls, scheduler, and notifications
├── tests/
│   ├── test_auth.py                 # Hermetic tests for registration, bcrypt hashing, JWT login, rate limiting, and logout
│   ├── test_cross_user_isolation.py # Multi-tenant isolation tests verifying strict user ownership across all resources
│   ├── test_api.py                  # Automated API tests for health check and site endpoints
│   ├── test_monitoring.py           # Hermetic unit tests for SSRF validation and text extraction
│   ├── test_change_detection.py     # Tests for baselines, unchanged checks, diff generation, and failure handling
│   ├── test_timemachine.py          # Tests for chronological ordering, scrubber navigation, and snapshot comparisons
│   ├── test_visual.py               # Hermetic tests for screenshot capture, Pillow diffs, baselines, and SSRF
│   ├── test_analytics.py            # Tests for analytics aggregation, 7x24 matrix, date bounds, and 404/422 handling
│   ├── test_notifications.py        # Hermetic tests for alert creation, deduplication, unread lifecycle, and preferences
│   └── test_scheduler.py            # Hermetic tests for scheduler lifecycle, job sync, global auto-checks, and concurrency locks
├── requirements.txt     # Python package requirements (FastAPI, SQLAlchemy, bcrypt, PyJWT, Playwright, APScheduler)
├── .gitignore           # Git ignore rules for environments, databases, and screenshot binaries
└── README.md            # Comprehensive project documentation and startup guide
```

---

## Technology Stack

- **Frontend**: Semantic HTML5, modern CSS3 (custom properties, responsive grid, dual light/dark themes), vanilla JavaScript (ES6+ async/await, fetch API).
- **Backend API**: Python 3.10+ with [FastAPI](https://fastapi.tiangolo.com/) and [Uvicorn](https://www.uvicorn.org/).
- **Authentication & Security**: [bcrypt](https://pypi.org/project/bcrypt/) password hashing with dynamic per-user salt generation, signed JSON Web Tokens via [PyJWT](https://pyjwt.readthedocs.io/), secure HTTP-only cookies (`SameSite=Lax`), and thread-safe sliding-window rate limiting.
- **Database**: Persistent local [SQLite](https://www.sqlite.org/) managed via [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with automated schema migration.
- **Web Extraction**: [Requests](https://requests.readthedocs.io/) and [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/).
- **Headless Browser & Visual Capture**: [Playwright](https://playwright.dev/python/) with Chromium (1280×800 viewport, 15s timeout, and route-interception SSRF protection).
- **Image Comparison**: [Pillow](https://pillow.readthedocs.io/) pixel diff computation, noise tolerance thresholding, and red-highlight difference overlays.
- **Background Scheduler**: [APScheduler](https://apscheduler.readthedocs.io/) `BackgroundScheduler` running periodic check intervals with `ThreadPoolExecutor` (max 5 workers) and atomic per-monitor check locks.
- **Security**: Built-in Server-Side Request Forgery (SSRF) protection against loopback, private RFC 1918 subnets, and cloud metadata endpoints across both HTTP requests and Playwright navigations/redirects.
- **Testing**: [Pytest](https://docs.pytest.org/) and FastAPI `TestClient` (hermetic, offline test suite with **109 passing tests**).

---

## Windows Setup & Installation

### Step A: Open PowerShell or Command Prompt
Open your terminal and navigate to the project directory:
```powershell
cd D:\website_change_detector
```

### Step B: Create and Activate Virtual Environment
```powershell
# Create a virtual environment named .venv
python -m venv .venv

# Activate the virtual environment in PowerShell:
.\.venv\Scripts\Activate.ps1

# (If using standard Command Prompt (cmd.exe) instead, run):
# .venv\Scripts\activate.bat
```

> **Note for PowerShell execution policy:** If PowerShell blocks script execution, run:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

### Step C: Install Dependencies & Headless Browser
```powershell
pip install -r requirements.txt

# Install Playwright Chromium headless browser binary
playwright install chromium
```

---

## Running the Application

### Start the Backend Server
Run Uvicorn with automatic reload:
```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```
Or directly through the active Python interpreter:
```powershell
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### Accessing the Interfaces
Once the server starts:
- **Interactive Dashboard (Frontend)**: Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.
- **Interactive API Documentation (Swagger UI)**: Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
- **Alternative API Reference (ReDoc)**: Open [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc).
- **Backend Health Endpoint**: Open [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health).

---

## Adding Monitors & Testing Change Detection

ChangeScope allows you to add websites and inspect detected content changes:

### 1. Add a Website Monitor
1. Navigate to [http://127.0.0.1:8000/](http://127.0.0.1:8000/) and click **Monitors** in the sidebar.
2. Click **Add Monitor** to open the registration dialog.
3. Enter a public website URL (for example: `https://example.com` or `https://httpbin.org/html`) and an optional display name.
4. Click **Create Monitor**. The monitor will appear in the table with state `Pending check`.

### 2. Run the First Check (Baseline Creation)
- Click the **Check Now** button (refresh icon) next to the newly created monitor.
- The button will display a spinning animation while safely fetching the target URL.
- Because this is the first check, ChangeScope creates a **baseline snapshot**:
  - Extracts clean readable text using BeautifulSoup (stripping scripts, styles, and SVGs).
  - Computes a deterministic SHA-256 cryptographic hash.
  - Persists the baseline snapshot in SQLite.
  - **No change event** is recorded for the baseline.
  - Toast confirmation: *Baseline established. Future checks will detect content deviations.*

### 3. Run a Second Check (Unchanged State)
- Click **Check Now** a second time.
- If the content has not changed, ChangeScope matches the content hash against the latest snapshot.
- The check records a successful execution without creating a change event.
- Toast feedback: *No changes detected. Content matches baseline.*

### 4. Detect Changes & Inspect Diffs
- If the target website's text changes on subsequent checks, ChangeScope:
  - Generates a concise diff summary (e.g. `+2 lines, -1 lines`).
  - Computes a unified diff between baseline and new content.
  - Records a persistent change event and a new snapshot in SQLite.
  - Toast feedback: *Change detected!*
- Open **Change History** in the sidebar to view the audit log of all changes.
- Click **Inspect Diff** to open the **Diff Inspector Modal**:
  - **Unified Diff tab**: Color-coded line additions (`+`) and deletions (`-`).
  - **Before tab**: Extracted text of previous snapshot.
  - **After tab**: Extracted text of latest snapshot.

---

## Time Machine & Version History

The **Time Machine** provides an interactive historical explorer to browse past website versions, inspect clean extracted text, and compare any two snapshots:

1. **Accessing Time Machine**:
   - Click **Time Machine** in the sidebar navigation, or click the **Time Machine** icon/button from any monitor row in the dashboard, monitors table, or change history.
2. **Target Selector**:
   - Use the monitor dropdown at the top to switch between monitored targets.
   - Click **Capture Snapshot** at any time to run an immediate check and add a new version to the timeline.
3. **Timeline Scrubber**:
   - Drag the interactive scrubber slider to scrub backwards and forwards through time.
   - Use the **« Baseline**, **‹ Prev**, **Next ›**, and **Latest »** buttons or your keyboard's **Left/Right Arrow keys** to step version-by-version.
   - The scrubber badge displays whether each version was the `Baseline`, an `Unchanged Check`, or a `Change Detected`.
4. **Version Timeline Feed**:
   - The left panel lists all versions with timestamps, HTTP status codes, latencies, line counts, and classification tags.
   - Click the sort toggle button to view oldest-first or newest-first.
5. **Inspect Version Text Mode**:
   - Displays full version telemetry: Snapshot ID, capture date, HTTP status, latency, document size (lines/chars), and full cryptographic SHA-256 hash.
   - View formatted readable text extracted for that snapshot with a **Copy Text** button for your clipboard.
6. **Before / After Comparison Tool**:
   - Click the **Before / After Compare** tab to compare any two saved versions (Base vs Target).
   - Use the swap button (`⇄`) to invert the comparison.
   - View delta statistics (`+X lines`, `-Y lines`, `Identical / Modified`).
   - Switch between **Unified Diff** (with line-by-line colored diff additions and removals) and **Side-by-Side** (Before and After columns).

---

## Visual Change Detection & Screenshot Diffing

ChangeScope captures headless browser screenshots and detects pixel-level changes alongside text changes:

1. **Configuring Visual Snapshots**:
   - When creating or editing a monitor, toggle **Visual Screenshots** to **Enabled**.
   - Configure a custom **Visual Threshold (%)** (default: `1.0%`). If the visual difference between screenshots meets or exceeds this threshold, a visual change event is triggered.
2. **Dedicated Local Screenshot Storage**:
   - Screenshots are saved locally in `data/screenshots/{site_id}/` in PNG format.
   - Image metadata (path, dimensions, file size, diff percentage, timestamp) is recorded in SQLite. Raw binary blobs are **never stored directly in SQLite**.
3. **SSRF Hardening in Playwright**:
   - Playwright navigations, subresources, and redirects (301/302) are intercepted via `page.route` inspection and checked with `validate_target_url()`.
   - Any attempt to reach `localhost`, RFC 1918 private subnets (`127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`), or cloud metadata endpoints (`169.254.169.254`) is immediately aborted.
4. **Triggering a Visual Capture**:
   - On the **Monitors** page, click the camera icon on any monitor row, or click **Capture Screenshot** in the **Visual Changes & Screenshots** card.
   - You can also click **Capture Visual** inside the **Monitor Details Modal**.
5. **Baseline Establishment**:
   - The first screenshot capture establishes a **Baseline Reference** at 1280×800 resolution.
   - The UI displays the baseline screenshot with capture timestamp and resolution. No visual change event is fired for the baseline.
6. **Visual Comparison & Pixel Diff Overlays**:
   - On subsequent captures, Pillow compares the new screenshot against the previous successful screenshot.
   - The UI renders a side-by-side comparison:
     - **Previous / Baseline Screenshot**
     - **Latest Screenshot**
     - **Pixel Diff Overlay** with modified regions highlighted in red.
   - A diff summary banner reports the exact difference percentage (e.g. `1.84% Difference`) and whether it exceeds your configured threshold.
7. **Failure Resilience**:
   - If a page cannot be rendered (e.g., DNS failure, timeout), ChangeScope preserves the previous successful screenshot and displays a descriptive error message without corrupting the baseline.

---

## Change Heatmap & Monitoring Analytics

ChangeScope provides real-time telemetry analysis, hourly cadence matrices, and volatility leaderboards computed directly from SQLite snapshot and check log records:

### 1. Change Heatmap & Activity Cadence (`#view-heatmap`)
- **Hourly Distribution Matrix (7 × 24 UTC)**:
  - Maps change frequency across all 7 days of the week (Monday through Sunday) and all 24 hours of the day (00:00 to 23:00 UTC).
  - Cells are dynamically color-coded by intensity level:
    - **Level 0**: 0 changes (subtle surface)
    - **Level 1**: 1–2 changes (light indigo)
    - **Level 2**: 3–5 changes (medium indigo)
    - **Level 3**: 6+ changes (vibrant glowing indigo)
  - Interactive cell tooltips show the exact time window, day of week, detected change count, and affected monitor IDs.
- **Daily Activity Calendar**:
  - Displays GitHub-style contribution squares tracking daily mutation frequency across the selected window.
  - Hovering over any square reveals the date, total changes, text diff count, and visual diff count.
- **Summary KPI Cards**:
  - **Total Changes**: Total count of text and visual mutations in the chosen timeframe.
  - **Peak Day**: The day of the week with the highest mutation concentration.
  - **Peak Hour**: The specific UTC hour experiencing the highest mutation cadence.
  - **Active Time Window**: Start and end date range of the active telemetry dataset.
- **Monitor Cadence Breakdown**:
  - Lists each monitor with its total checks, text diff count, visual diff count, aggregate mutations, change rate %, and most recent mutation timestamp.

### 2. Monitoring Analytics & Telemetry (`#view-analytics`)
- **6 Core Telemetry KPI Cards**:
  - **Total Checks**: Total check runs executed across all targets in the window.
  - **Text Changes**: Total DOM text mutations detected.
  - **Visual Changes**: Total visual changes exceeding the configured pixel threshold.
  - **Failed Checks**: Count of HTTP errors (4xx/5xx), network timeouts, or SSRF blocks.
  - **Change Frequency Rate**: Mutation percentage per check run (`total_changes / total_checks * 100%`).
  - **Average Response Latency**: Server response time in milliseconds averaged across successful checks.
- **Activity & Change Timeline Chart**:
  - Pure CSS/SVG daily bar chart comparing executed checks (indigo bar) against detected mutations (cyan bar) side-by-side.
  - Proportional scaling with tooltips reporting daily check counts, mutations, and failures.
- **HTTP Status Telemetry & Health**:
  - Categorized breakdown of responses: 2xx Success (Active & OK), 3xx Redirects, 4xx Client Errors, 5xx Server Errors, and Network/SSRF Blocks.
  - Real-time progress bars showing percentages and counts.
- **Monitor Volatility Ranking (Leaderboard)**:
  - Ranks monitored websites by highest mutation volatility (total detected changes descending).
  - Highlights Top 3 positions with Gold (#1), Silver (#2), and Bronze (#3) badges.

### 3. Date Range & Monitor Filters
- **Target Filter**: Switch between `All Monitors (Aggregated)` or isolate telemetry for any individual monitor.
- **Date Range Presets**: Choose between `Last 7 Days`, `Last 14 Days`, `Last 30 Days` (default), `Last 90 Days`, or `All Time`.
- **Honest Empty States**: If no activity was recorded in the selected window, ChangeScope clearly communicates the absence of data without inventing statistics or mock charts.

### 4. API Endpoints
- `GET /api/analytics/summary?site_id={id}&days={7|14|30|90|0}`: Returns aggregated counts, rates, average latency, status distribution, top sites leaderboard, and daily timeline points.
- `GET /api/analytics/heatmap?site_id={id}&days={7|14|30|90|0}`: Returns 7×24 hourly cell matrix, daily calendar activity cells, peak day/hour, and site cadence metrics.

---

## Notifications and Alerts System

ChangeScope provides a persistent, real-time alert system tracking detected textual mutations, visual pixel discrepancies, and check failures:

### 1. Persistent Event Types
- **DOM Text Changes (`text_change`)**: Triggered whenever readable HTML content differs from the previous successful baseline.
- **Visual Changes (`visual_change`)**: Triggered whenever a headless Playwright screenshot differs from the baseline by more than the configured pixel threshold.
- **Check Failures (`check_failed`)**: Triggered when a monitoring check encounters HTTP 4xx/5xx status codes, network timeouts, or SSRF security blocks.

### 2. Notifications & Alerts Center (`#view-notifications`)
- **Topbar Bell & Badge Pill**: Top-right bell displays a live, pulsing badge showing unread alert count. Clicking the bell jumps directly to the Notification Center.
- **Sidebar Badge**: Live counter in the sidebar navigation keeps unread alerts visible from any view.
- **Summary KPI Cards**:
  - **Total Alerts**: Total recorded notifications.
  - **Unread Alerts**: Alerts awaiting review.
  - **Text Changes**: Total DOM mutation alerts.
  - **Visual Changes**: Total pixel difference alerts.
- **Interactive Feed Cards**:
  - Color-coded badges: Violet (`Text Change`), Cyan (`Visual Change`), Red (`Check Failed`).
  - Target website name with clickable external URL link.
  - Relative timestamp with full date tooltip.
  - Contextual deep link action buttons:
    - **Inspect Diff**: Opens the Unified/Side-by-Side Diff Inspector modal.
    - **View Visuals**: Opens the Visual Changes section for the target monitor.
    - **View Monitor**: Opens the target monitor details modal.
  - **Mark Read / Unread**: Toggle read status for individual alerts.
  - **Delete**: Remove individual alerts permanently.
- **Bulk Actions**: "Mark All Read" button to clear all pending unread badges with one click.
- **Filtering**: Filter alerts by target monitor, event type, or toggle between "All" and "Unread Only".

### 3. Settings & Alert Preferences (`#view-settings`)
- Dedicated **Notification & Alert Preferences** card allows users to enable or disable alerts independently for:
  - DOM Text Changes
  - Visual Layout & Screenshot Changes
  - Check Failures & HTTP Errors
- Suppressed events will not generate notifications, keeping user feeds uncluttered.

### 4. Strict Deduplication & Anti-Spam Protection
- **Event-Level Deduplication**: Text changes and visual diffs use deterministic deduplication keys (`text_change:{id}` and `visual_change:{site_id}:{snapshot_id}`) to guarantee that identical events are never duplicated.
- **Consecutive Failure Deduplication**: Consecutive identical check failures (e.g., repeating 404s or connection timeouts) do not spam duplicate notifications if the previous failure notification remains unread.
- **Local Application Scope**: Completely self-contained within SQLite; zero reliance on external email, SMS, or third-party webhooks.

### 5. API Endpoints
- `GET /api/notifications?unread_only={bool}&event_type={type}&site_id={id}&limit={n}&offset={n}`: List notifications with filtering.
- `GET /api/notifications/unread-count`: Retrieve unread notification count.
- `PATCH /api/notifications/{id}/read`: Mark notification as read.
- `PATCH /api/notifications/{id}/unread`: Mark notification as unread.
- `POST /api/notifications/mark-all-read`: Mark all notifications as read (optional `site_id` query filter).
- `DELETE /api/notifications/{id}`: Delete a notification (HTTP 204).
- `GET /api/notifications/preferences`: Retrieve notification alert preferences.
- `PUT /api/notifications/preferences`: Update notification alert preferences.

---

## Automated Monitoring Scheduler

ChangeScope features an automated background scheduler built on **APScheduler** that periodically checks active monitors without requiring manual intervention:

### 1. Scheduler Engine & Architecture
- **APScheduler BackgroundScheduler**: Runs as a daemon thread pool (`ThreadPoolExecutor`, default 5 concurrent workers) tied directly to FastAPI's `lifespan` context.
- **Individual Monitor Intervals**: Automatically registers a job for every monitor according to its configured `check_interval_minutes`.
- **Active / Paused Status Respect**: Only active monitors (`is_active=True`) are scheduled for execution. Pausing a monitor immediately removes or pauses its background check job.
- **Overlapping Check Prevention**: Employs atomic mutex lock guards per monitor (`acquire_site_check_lock` / `release_site_check_lock`). If a manual or scheduled check is currently executing for a monitor, concurrent checks for that same monitor safely skip and log a descriptive notification without corrupting data or baselines.
- **Graceful Lifecycle Management**: The scheduler starts when FastAPI boots and cleanly shuts down on termination, preventing orphaned background threads or duplicate scheduler instances during development reloads.

### 2. Full System Integration
Scheduled checks seamlessly run the complete ChangeScope pipeline:
- Fetches target HTML safely with SSRF protections and extracts clean readable text.
- If enabled on the monitor, launches headless Playwright to capture full-page visual screenshots.
- Compares text and visual data against previous baselines:
  - Establishes inaugural baseline snapshots on the first run.
  - Generates unified diffs and detects textual alterations.
  - Calculates pixel difference percentages via Pillow and flags visual changes exceeding threshold.
- Emits real-time notifications with deduplication and preference filtering.
- Records check logs (`SiteCheckLog`) feeding into the Change Heatmap and Analytics engine.

### 3. Dashboard Scheduler Center (`#view-dashboard`)
- **Runtime Status Badge**: Live indicator displaying `Scheduler Running`, `Globally Paused`, or `Scheduler Inactive`.
- **Quick Controls**:
  - **Pause / Resume Automation**: Master switch to globally pause or resume all automated checks with a single click.
  - **Sync Jobs**: Forces an immediate re-synchronization of background jobs against the SQLite monitors database.
- **KPI Metrics**:
  - **Automated Checks**: Global toggle state (Enabled vs Paused).
  - **Scheduled Monitors**: Number of active jobs currently queued.
  - **Next Check**: Human-readable countdown pill until the earliest upcoming scheduled run.
  - **Worker Pool**: Active thread worker capacity.
- **Upcoming Execution Queue Table**:
  - Lists every monitor target, its configured frequency (`Every Xm`), live countdown badge to next run, and status.
  - Includes an inline **Run Now** button to immediately trigger a scheduler worker check.
- **Recent Check Outcomes Feed**:
  - Streams real-time check execution logs with status badges (`Baseline`, `Unchanged`, `Changed`, `Failed`), HTTP status, and response latency.

### 4. Settings & Automation Preferences (`#view-settings`)
- **Automated Monitoring Switch**: Toggle background checks globally without altering individual monitor intervals.
- **Concurrency Limit**: Configure the maximum concurrent check threads (default: `5`).

### 5. API Endpoints
- `GET /api/scheduler/status`: Inspect scheduler runtime state, global automation switch, active jobs queue, and recent outcome logs.
- `POST /api/scheduler/start`: Start the background scheduler.
- `POST /api/scheduler/stop`: Stop the background scheduler.
- `POST /api/scheduler/sync`: Re-synchronize jobs with all active monitors in SQLite.
- `GET /api/scheduler/settings`: Retrieve global scheduler settings.
- `PUT /api/scheduler/settings`: Update `auto_checks_enabled` or `max_concurrent_jobs`.
- `POST /api/scheduler/jobs/{site_id}/run-now`: Dispatch an immediate check run for a monitor via a scheduler worker.

---

## Secure User Accounts & Authentication

ChangeScope implements an enterprise-grade multi-tenant authentication and user account management architecture. Monitored websites, check histories, visual snapshots, alerts, and analytics are isolated per-user account while maintaining backward compatibility with single-tenant installations.

### 1. Security Architecture & Threat Defense
- **Password Hashing**: Uses `bcrypt` with unique per-user salts (never storing plaintext passwords). Password verification runs constant-time checks to protect against timing side-channel attacks.
- **Token Management & Dual Transport**:
  - Issues signed JSON Web Tokens (`HS256`, 7-day expiration) containing user ID claims.
  - Automatically transports tokens via standard `Authorization: Bearer <token>` HTTP headers.
  - Simultaneously configures a secure `changescope_token` HTTP-only cookie (`SameSite="lax"`, with `secure=True` automatically enabled in production via `CHANGESCOPE_ENV=production`).
  - Secret key is configurable through `CHANGESCOPE_SECRET_KEY` environment variable.
- **Multi-Tenant Data Isolation**:
  - `monitored_sites`, `notifications`, and `notification_preferences` include foreign keys to `users.id`.
  - All read, create, update, delete, check execution, snapshot, screenshot, and analytics endpoints are filtered strictly by `current_user.id`.
  - Unauthorized requests attempting to access another user's monitor ID or notification ID return HTTP **404 Not Found** (instead of 403) to eliminate ID enumeration vulnerabilities.
- **Brute-Force Rate Limiting**:
  - A thread-safe, sliding-window `AuthRateLimiter` enforces a strict threshold of **10 failed authentication attempts per 60 seconds** per client IP before blocking further requests with HTTP **429 Too Many Requests**.
  - Login failure error messages are intentionally generic (`"Invalid email or password."`) to prevent account discovery via email enumeration.
- **Safe Schema Migration**:
  - SQLite auto-migration dynamically adds `user_id` columns if missing and safely migrates existing unowned rows to the initial admin user without any data loss.

### 2. Frontend User Experience
- **Auth Overlay (`#auth-overlay`)**: Sleek, tabbed modal dialog inspired by modern SaaS developer tools, allowing seamless switching between **Sign In** and **Create Account**.
- **Interactive Topbar Profile Pill**: Displays the user's avatar circle with initials, display name, and an interactive dropdown revealing their role and quick links to Account & Security or Logout.
- **Account & Security Card (`#view-settings`)**: Shows current account email, role (Administrator / Member), registration timestamp, display name editor, and secure password change form with current password verification.
- **Client-Side Auth Interceptor**: A lightweight wrapper around `window.fetch` automatically injects the `Authorization: Bearer` header on all API calls and catches HTTP 401 errors, gracefully prompting the user to sign in if their session expires.

### 3. Authentication API Endpoints
- `POST /api/auth/register`: Register a new account (validates email format, requires minimum 8-character password, prevents duplicate registration, auto-logs in and sets cookie).
- `POST /api/auth/login`: Authenticate email and password, rate-limited against brute force, sets HTTP-only cookie and returns JWT bearer token.
- `POST /api/auth/logout`: Clears the authentication session cookie and client token.
- `GET /api/auth/me`: Retrieve profile of currently authenticated user.
- `PUT /api/auth/me`: Update display name or change password (with mandatory current-password verification).

---

## Automated Testing & Test Suite

ChangeScope includes a comprehensive hermetic test suite using Pytest (**109 passing tests**, 100% offline with zero external network dependencies).

To run all tests:
```powershell
pytest -v
```
To run in concise mode:
```powershell
pytest -q
```

To run a specific test module:
```powershell
# Run authentication, password hashing, and rate limiting tests (Prompt 10)
pytest tests/test_auth.py -v

# Run multi-tenant cross-user data isolation tests (Prompt 10)
pytest tests/test_cross_user_isolation.py -v

# Run automated scheduler, concurrency, and lifecycle tests (Prompt 9)
pytest tests/test_scheduler.py -v

# Run notifications, deduplication, and preferences tests (Prompt 8)
pytest tests/test_notifications.py -v

# Run analytics & heatmap aggregation tests (Prompt 7)
pytest tests/test_analytics.py -v

# Run visual change detection, Pillow diff, baseline, and SSRF tests (Prompt 6)
pytest tests/test_visual.py -v

# Run Time Machine & snapshot comparison tests (Prompt 5)
pytest tests/test_timemachine.py -v

# Run change detection engine tests (Prompt 4)
pytest tests/test_change_detection.py -v

# Run API endpoint tests (Prompt 3)
pytest tests/test_api.py -v

# Run monitoring & SSRF validation tests (Prompt 1 & 4)
pytest tests/test_monitoring.py -v
```
