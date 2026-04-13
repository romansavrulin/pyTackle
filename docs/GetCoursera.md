# GetCoursera

Scrape and list training content from GetCourse.ru educational platform.

## Overview

**GetCoursera** is a tackle for extracting training structure from GetCourse.ru educational platform. It authenticates using browser cookies and retrieves the hierarchical structure of trainings, lessons, and modules.

### Key Features

- **Authenticated scraping** — Uses browser cookies for authentication
- **Hierarchical extraction** — Retrieves trainings → lessons → modules structure
- **URL conversion** — Converts internal URLs to player-accessible format

## Prerequisites

### Environment Variable

Set the `GETCOURSE_COOKIE` environment variable with your session cookie from GetCourse.ru:

```bash
export GETCOURSE_COOKIE="your_session_cookie_here"
```

To obtain the cookie:
1. Log into GetCourse.ru in your browser
2. Open Developer Tools (F12) → Network tab
3. Navigate to any course page
4. Copy the `Cookie` header value from any request

Alternatively, create a `.env` file in the project root:

```
GETCOURSE_COOKIE=your_session_cookie_here
```

## Usage

```bash
pyTackle GetCoursera [OPTIONS]
```

## CLI Reference

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--url URL` | `https://school.getcourse.ru` | Base URL of the GetCourse site |

## Example

```bash
# Use default GetCourse URL
pyTackle GetCoursera

# Use custom school URL
pyTackle GetCoursera --url https://myschool.getcourse.ru
```

## Output

The tackle prints training structure to stdout:

```
Training Name: Python Basics
Training URL: https://school.getcourse.ru/teach/control/stream/view/id/12345
Training Description: Introduction to Python programming
  Lesson Name: Getting Started
  Lesson URL: https://school.getcourse.ru/pl/teach/control/lesson?id=67890&editMode=0
    Module Name: Installing Python
    Module URL: https://school.getcourse.ru/...
    Module Name: First Script
    Module URL: https://school.getcourse.ru/...
```

## Requirements

This tackle requires additional Python packages:

```bash
pip install beautifulsoup4 requests python-dotenv
```

## Platform Support

| Platform | Status |
|----------|--------|
| **Windows** | ✅ Full support |
| **macOS** | ✅ Full support |
| **Linux** | ✅ Full support |

## Limitations

- Requires valid session cookies (must be logged in)
- Cookie expiration may require re-authentication
- Rate limiting may apply on GetCourse.ru

## See Also

- [pyTackle README](README.md) — Overview of all available tackles
