# Phase 6B: Full Tool Arsenal — Design Specification

## 1. Goal

Extend Phase 6A's tool framework with 65 new native tools across 12 categories, plus an OpenAPI auto-import provider. Total tool count after Phase 6B: **80 tools**.

## 2. Architecture

All tools follow the same pattern established in Phase 6A:
- **Handler function:** `async def handle_<tool>(params: dict) -> dict`
- **Tool definition:** `TOOL_DEFINITIONS` list with Anthropic-compatible schemas
- **Registration:** Added to `register_all_native_tools()` via `_HANDLER_MAP`

External dependencies are **optional** — each module uses graceful imports:
```python
try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False
```

Handlers check availability at execution time and return helpful errors if deps are missing.

## 3. New Tool Categories

### 3.1 Code Analysis Tools (`code_tools.py`) — 5 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| code.ast_parse | Parse Python file to AST structure | ast (stdlib) |
| code.lint | Run ruff linter on file/directory | ruff (dev dep) |
| code.format | Format code with ruff | ruff (dev dep) |
| code.test | Run pytest on file/directory | pytest (dev dep) |
| code.dependencies | Analyze Python imports | ast (stdlib) |

### 3.2 Browser Automation Tools (`browser_tools.py`) — 7 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| browser.navigate | Navigate to URL, return content | playwright |
| browser.click | Click element by CSS selector | playwright |
| browser.type | Type text into element | playwright |
| browser.screenshot | Take page screenshot (base64) | playwright |
| browser.get_content | Get page text/HTML content | playwright |
| browser.fill_form | Fill multiple form fields | playwright |
| browser.evaluate | Execute JavaScript in page | playwright |

Lifecycle: A shared browser context is created on first use and reused. Max 5 concurrent pages.

### 3.3 Database Tools (`database_tools.py`) — 6 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| database.postgres_query | Execute SELECT on PostgreSQL | asyncpg (existing) |
| database.postgres_execute | Execute DML/DDL on PostgreSQL | asyncpg (existing) |
| database.sqlite_query | Query SQLite database file | aiosqlite |
| database.sqlite_execute | Execute on SQLite | aiosqlite |
| database.redis_get | Get Redis key(s) | redis (existing) |
| database.redis_set | Set Redis key with optional TTL | redis (existing) |

### 3.4 Docker Tools (`docker_tools.py`) — 6 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| docker.list_containers | List containers (all or running) | docker |
| docker.run | Run container from image | docker |
| docker.stop | Stop running container | docker |
| docker.logs | Get container logs | docker |
| docker.build | Build image from Dockerfile | docker |
| docker.compose | Docker compose up/down/ps | asyncio.subprocess |

### 3.5 Document Tools (`document_tools.py`) — 5 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| document.read_pdf | Extract text from PDF pages | PyPDF2 |
| document.read_spreadsheet | Read Excel/CSV to JSON rows | openpyxl, csv (stdlib) |
| document.write_csv | Write records to CSV file | csv (stdlib) |
| document.write_spreadsheet | Write records to Excel | openpyxl |
| document.parse_json | Parse/query JSON file with JSONPath | jsonpath-ng |

### 3.6 AWS Tools (`aws_tools.py`) — 8 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| aws.s3_list | List buckets or objects in bucket | boto3 |
| aws.s3_get | Download S3 object content | boto3 |
| aws.s3_put | Upload content to S3 | boto3 |
| aws.s3_delete | Delete S3 object | boto3 |
| aws.ec2_list | List EC2 instances | boto3 |
| aws.ec2_manage | Start/stop/reboot instances | boto3 |
| aws.lambda_invoke | Invoke Lambda function | boto3 |
| aws.cloudwatch_query | Query CloudWatch log groups | boto3 |

### 3.7 Email Tools (`email_tools.py`) — 4 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| email.send | Send email via SMTP | aiosmtplib |
| email.read | Read recent emails via IMAP | aioimaplib |
| email.search | Search emails by criteria | aioimaplib |
| email.list_folders | List email folders | aioimaplib |

Configuration via env vars: `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_IMAP_HOST`, `EMAIL_USER`, `EMAIL_PASSWORD`.

### 3.8 Calendar Tools (`calendar_tools.py`) — 4 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| calendar.list_events | List events in date range | icalendar, caldav |
| calendar.create_event | Create calendar event | icalendar, caldav |
| calendar.update_event | Update existing event | icalendar, caldav |
| calendar.delete_event | Delete event by ID | icalendar, caldav |

Uses CalDAV protocol for provider-agnostic calendar access.

### 3.9 Data Analysis Tools (`data_tools.py`) — 5 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| data.load | Load CSV/JSON/Parquet to summary | polars |
| data.query | SQL query on loaded data | polars |
| data.summarize | Statistical summary of columns | polars |
| data.transform | Apply filter/sort/group/agg ops | polars |
| data.export | Export data to CSV/JSON/Parquet | polars |

Uses Polars for speed. Data referenced by handle (path), not held in memory between calls.

### 3.10 Media Tools (`media_tools.py`) — 5 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| media.image_resize | Resize image to dimensions | Pillow |
| media.image_convert | Convert image format | Pillow |
| media.image_info | Get image metadata (size, format, EXIF) | Pillow |
| media.audio_transcribe | Transcribe audio file | openai-whisper |
| media.video_info | Get video metadata (duration, resolution) | ffmpeg-python |

### 3.11 Web Scraping Tools (`scraping_tools.py`) — 3 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| web.scrape | Fetch URL, extract text content | httpx (existing), beautifulsoup4 |
| web.extract_links | Extract all links from URL | httpx (existing), beautifulsoup4 |
| web.search | Search the web via Brave API | httpx (existing) |

### 3.12 Git Extensions (`git_ext_tools.py`) — 4 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| git.clone | Clone a repository | asyncio.subprocess |
| git.branch | Create/switch/list branches | asyncio.subprocess |
| git.push | Push to remote | asyncio.subprocess |
| git.pr_create | Create GitHub PR via gh CLI | asyncio.subprocess |

### 3.13 Server/SSH Tools (`server_tools.py`) — 3 tools
| Tool ID | Description | Dependencies |
|---------|-------------|--------------|
| server.ssh_execute | Execute command via SSH | asyncssh |
| server.system_info | Get system CPU/memory/disk info | psutil (existing) |
| server.service_status | Check systemd service status | asyncio.subprocess |

## 4. OpenAPI Auto-Import Provider

New `ToolProvider` subclass: `OpenAPIToolProvider`

```python
class OpenAPIToolProvider(ToolProvider):
    """Generates tools from an OpenAPI/Swagger spec."""
    
    async def load_spec(self, spec_url_or_path: str) -> None:
        """Parse OpenAPI spec and generate tool definitions."""
    
    def list_tools(self) -> list[ToolDefinition]:
        """Return generated tool definitions."""
    
    async def execute(self, tool_id: str, params: dict) -> ToolResult:
        """Execute API call based on spec endpoint."""
    
    async def health_check(self) -> bool:
        """Ping base URL."""
```

- Parses OpenAPI 3.x specs (JSON/YAML)
- Each endpoint becomes a tool: `{spec_prefix}.{operationId}`
- Input schemas derived from spec parameters + request body
- Auth headers injected from config

## 5. Dependencies

New optional dependency groups in `pyproject.toml`:

```toml
[project.optional-dependencies]
browser = ["playwright>=1.49"]
aws = ["boto3>=1.35"]
docker = ["docker>=7.1"]
documents = ["PyPDF2>=3.0", "openpyxl>=3.1", "jsonpath-ng>=1.6"]
data = ["polars>=1.0"]
media = ["Pillow>=11.0", "openai-whisper>=20240930", "ffmpeg-python>=0.2"]
email = ["aiosmtplib>=3.0", "aioimaplib>=2.0"]
calendar = ["icalendar>=6.0", "caldav>=1.4"]
scraping = ["beautifulsoup4>=4.12"]
ssh = ["asyncssh>=2.17"]
openapi = ["pyyaml>=6.0", "jsonschema>=4.0"]
all-tools = [
    "max[browser,aws,docker,documents,data,media,email,calendar,scraping,ssh,openapi]"
]
```

Core tools (code analysis, database postgres/redis, git extensions, server system_info, docker compose) use only stdlib + existing deps.

## 6. Config Additions

```python
# src/max/config.py additions
# Email
email_smtp_host: str = ""
email_smtp_port: int = 587
email_imap_host: str = ""
email_user: str = ""
email_password: str = ""

# Calendar (CalDAV)
caldav_url: str = ""
caldav_user: str = ""
caldav_password: str = ""

# Web search
brave_search_api_key: str = ""

# Browser
browser_headless: bool = True
browser_max_pages: int = 5
```

## 7. File Structure

```
src/max/tools/native/
├── __init__.py           # Updated: register all 80 tools
├── file_tools.py         # (Phase 6A — 6 tools)
├── shell_tools.py        # (Phase 6A — 1 tool)
├── git_tools.py          # (Phase 6A — 4 tools)
├── web_tools.py          # (Phase 6A — 2 tools)
├── process_tools.py      # (Phase 6A — 1 tool)
├── search_tools.py       # (Phase 6A — 1 tool)
├── code_tools.py         # NEW: 5 tools
├── browser_tools.py      # NEW: 7 tools
├── database_tools.py     # NEW: 6 tools
├── docker_tools.py       # NEW: 6 tools
├── document_tools.py     # NEW: 5 tools
├── aws_tools.py          # NEW: 8 tools
├── email_tools.py        # NEW: 4 tools
├── calendar_tools.py     # NEW: 4 tools
├── data_tools.py         # NEW: 5 tools
├── media_tools.py        # NEW: 5 tools
├── scraping_tools.py     # NEW: 3 tools
├── git_ext_tools.py      # NEW: 4 tools
├── server_tools.py       # NEW: 3 tools

src/max/tools/providers/
├── base.py               # (Phase 6A)
├── native.py             # (Phase 6A)
├── mcp.py                # (Phase 6A)
├── openapi.py            # NEW: OpenAPI auto-import provider

tests/
├── test_code_tools.py
├── test_browser_tools.py
├── test_database_tools.py
├── test_docker_tools.py
├── test_document_tools.py
├── test_aws_tools.py
├── test_email_tools.py
├── test_calendar_tools.py
├── test_data_tools.py
├── test_media_tools.py
├── test_scraping_tools.py
├── test_git_ext_tools.py
├── test_server_tools.py
├── test_openapi_provider.py
```

## 8. Testing Strategy

- All external deps are mocked in tests
- Tools using stdlib (code, document CSV, git extensions) use real operations on tmp_path
- Browser tools mock Playwright's async API
- AWS tools mock boto3 clients
- Docker tools mock docker.from_env()
- Email/Calendar tools mock protocol libraries
- OpenAPI provider uses a fixture spec file
- Every tool gets: success case, error case, missing-dep case

## 9. Registration Update

`register_all_native_tools()` in `__init__.py` will be updated to import all 14 tool modules (12 new + 2 existing updates) and register all 80 tools.

## 10. Summary

| Category | Tools | Key Library |
|----------|-------|-------------|
| File (6A) | 6 | pathlib |
| Shell (6A) | 1 | asyncio.subprocess |
| Git (6A) | 4 | asyncio.subprocess |
| Web (6A) | 2 | httpx |
| Process (6A) | 1 | psutil |
| Search (6A) | 1 | re, pathlib |
| Code Analysis | 5 | ast, subprocess |
| Browser | 7 | playwright |
| Database | 6 | asyncpg, aiosqlite, redis |
| Docker | 6 | docker, asyncio.subprocess |
| Documents | 5 | PyPDF2, openpyxl, csv |
| AWS | 8 | boto3 |
| Email | 4 | aiosmtplib, aioimaplib |
| Calendar | 4 | icalendar, caldav |
| Data Analysis | 5 | polars |
| Media | 5 | Pillow, whisper, ffmpeg |
| Web Scraping | 3 | beautifulsoup4, httpx |
| Git Extensions | 4 | asyncio.subprocess |
| Server/SSH | 3 | asyncssh, psutil |
| **Total** | **80** | |
| OpenAPI Provider | dynamic | pyyaml, httpx |
