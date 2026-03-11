# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Database Backup Agent** - a Flask-based web application for managing automated backups of PostgreSQL and MySQL databases. It provides a Web UI for configuring backup schedules, managing database connections, viewing backup history, and receiving notifications.

The application is containerized with Docker and supports both x86_64 (amd64) and ARM64 architectures.

## Common Development Commands

### Local Development (without Docker)

```bash
# Install dependencies
pip3 install -r requirements.txt

# Create backups directory
mkdir -p backups

# Initialize database and run Flask app
python3 db_init.py
python3 app.py

# The app will be available at http://localhost:5001
```

### Docker Development

```bash
# Build and run locally
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop and remove
docker-compose down

# Build multi-architecture image (requires Docker buildx)
docker buildx build --platform linux/amd64,linux/arm64 -t tony5188/db-backup-agent:latest --push .
```

### Database Management

```bash
# Run database migrations manually (usually done automatically on startup)
python3 migrate_db.py

# Access SQLite database directly (for debugging)
sqlite3 backups/users.db

# Test backup manually (from inside container or with proper paths set)
python3 config_manager.py export  # View current config as JSON
```

### Testing Backups

```bash
# Run a single database backup manually (inside container)
/usr/local/bin/backup.sh postgresql 手动 <db_connection_id> <user_id>
/usr/local/bin/backup.sh mysql 手动 <db_connection_id> <user_id>

# Or trigger via Flask API (requires authentication)
curl -X POST http://localhost:5001/api/backup/now \
  -H "Content-Type: application/json" \
  -d '{"db_type": "postgresql", "db_id": "<connection_id>"}'
```

## Architecture Overview

### Technology Stack

- **Backend**: Flask 3.0.0 with Flask-Login for authentication
- **Database**: SQLite (`backups/users.db`) for configuration and metadata storage
- **Frontend**: Vanilla JavaScript with Jinja2 templates, Flatpickr for date/time, Choices.js for selects
- **Task Scheduling**: System cron via `/etc/cron.d/backup-cron`, dynamically updated by `entrypoint.sh` calling `config_manager.py`
- **Backup Execution**: Bash scripts (`scripts/backup.sh`) using `pg_dump` and `mysqldump`
- **Notifications**: Email (SMTP) and WeChat Work (企业微信) via `notifications.py`
- **Security**: SHA-256 password hashing, TOTP-based 2FA (pyotp), session-based auth

### Key File Structure

| File | Purpose |
|------|---------|
| `app.py` | Main Flask application with all routes, authentication, and API endpoints |
| `config_manager.py` | Central configuration management module - all DB configs, schedules, and notification settings are stored in SQLite and managed through this module |
| `migrate_db.py` | Database migration script - runs automatically on container startup to handle schema updates between versions |
| `backup_lock.py` | Concurrency control - prevents simultaneous backups of the same database type using database-backed locks with 2-hour auto-expiry |
| `notifications.py` | Notification delivery - EmailNotifier and WeChatNotifier classes with token caching |
| `backup_logger.py` / `system_logger.py` | Python modules for logging backup history and system events to SQLite |
| `scripts/backup.sh` | The actual backup execution script - handles both PostgreSQL (pg_dump) and MySQL (mysqldump) |
| `scripts/entrypoint.sh` | Container entrypoint - runs migrations, sets up cron, starts Flask |

### Data Flow for Backups

1. **Schedule Trigger**: Cron executes `backup.sh postgresql|mysql 自动`
2. **Lock Acquisition**: `backup_lock.py` checks if backup is already running for this DB type
3. **Configuration**: `backup.sh` calls `config_manager.py export` to get database connections
4. **Execution**: For each DB connection, runs `pg_dump` or `mysqldump`, compresses with gzip
5. **Logging**: `backup_logger.py` records result to `backup_history` table
6. **Notification**: `notifications.py` sends email/WeChat notifications if configured
7. **Cleanup**: Old backups older than retention period are automatically deleted

### Multi-User Architecture (v2.4+)

The application supports multiple users with complete data isolation:

- **Database-level isolation**: All tables have `user_id` foreign key
- **Filesystem isolation**: Each user's backups stored in `/backups/user_{user_id}/`
- **User management**: Registration, login, password reset (via email), TOTP 2FA
- **Migration**: Existing data without user_id is associated with the first registered user during migration

### Security Considerations

- **Password storage**: SHA-256 hashed (not salted - historical design)
- **2FA**: TOTP (RFC 6238) with 30-second windows, compatible with Google/Microsoft Authenticator
- **Session security**: Flask secret key should be changed in production
- **Password reset**: Cryptographically secure tokens (32 bytes, URL-safe), 1-hour expiry
- **Backup isolation**: User IDs prevent cross-user backup access

### Database Schema (SQLite)

Core tables managed by the application:
- `users` - User accounts with password hashes
- `user_otp_config` - TOTP secrets for 2FA
- `password_reset_tokens` - Password reset tokens with expiry
- `database_connections` - Database connection configs (encrypted passwords)
- `backup_schedules` - Cron schedules per database type
- `backup_history` - Backup execution records with file metadata
- `notification_config` / `email_notification_config` / `wechat_notification_config` - Notification settings
- `backup_locks` - Concurrency control for backup jobs
- `system_logs` - Application event logging

## Important Implementation Details

### Configuration Management Pattern

All configuration is stored in SQLite, not config files. The `config_manager.py` module provides both a Python API and CLI interface:

```python
# Python API
from config_manager import get_db_connections, update_schedule

# CLI usage (used by backup.sh)
python3 config_manager.py export  # Returns JSON config
python3 config_manager.py update-schedule --type postgresql --schedule daily --time "02:00"
```

### Backup Lock Mechanism

Prevents concurrent backups of the same database type:
- Uses SQLite table `backup_locks` with memory cache for performance
- Locks auto-expire after 2 hours (crash recovery)
- Both automatic (cron) and manual backups respect locks

### Notification System

- **Email**: Standard SMTP with TLS support, multiple recipients
- **WeChat Work**: Uses Corporate ID + Secret to get access token, then sends to application
- Token caching in memory with automatic refresh on expiry
- Notifications sent asynchronously (background process) to avoid blocking backups

### Container Architecture

The Dockerfile handles architecture differences:
- **x86_64**: Installs official MySQL client from Oracle repositories
- **ARM64**: Uses MariaDB client (MySQL-compatible) due to Oracle's limited ARM support
- PostgreSQL client installed from official PostgreSQL apt repository for both

Cron runs as a background service inside the container, Flask runs in foreground for Docker log capture.

## Version History Context

The project uses semantic versioning with detailed changelogs in README.md. Recent major versions:
- **v2.4.0**: Multi-user support with data isolation, user registration, 2FA (TOTP)
- **v2.3.0**: Backup lock mechanism, notification debugging
- **v2.2.0**: Automatic database migrations
- **v2.1.0**: Email and WeChat Work notifications
- **v2.0.0**: Frontend refactor with modern UI

When modifying code, check `migrate_db.py` to understand the schema evolution and ensure backwards compatibility.
