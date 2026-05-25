---
id: note-007
tags: [authentication_discovery]
created: 2026-05-10T09:32:31.526157+00:00
source: docs/AUTHENTICATION_DISCOVERY.md
---

# AUTHENTICATION_DISCOVERY

# Jesse API Authentication Discovery

## Key Finding

Jesse API requires a **two-step authentication process**, not Bearer token authentication as initially assumed.

### Actual Authentication Flow

1. **Step 1: Login**
   ```bash
   POST /auth/login
   Body: {"password": "..."}
   Response: {"auth_token": "<REDACTED>"}
   ```

2. **Step 2: API Calls**
   ```bash
   POST /backtest (or any API endpoint)
   Header: authorization: <your_auth_token>
   ```

**Important**: The `authorization` header must be:
- Lowercase (not `Authorization`)
- Without the "Bearer " prefix
- Just the raw auth_token value

## Configuration Parameters

The `JESSE_API_TOKEN` environment variable should contain:
- **VALUE**: The `PASSWORD` from Jesse's `.env` file
- **NOT**: The `LICENSE_API_TOKEN` (which is for jesse.trade service)
- **Current Value**: See Jesse `.env` on server2 (not committed to repo)

## Token Provided

Some pre-existing tokens may not work with the `/auth/login` endpoint.

**Possible Explanations**:
1. It's an old/outdated token
2. It's a different authentication mechanism (LICENSE_API_TOKEN for jesse.trade)
3. It's the wrong format or needs updating in MetaMCP

**Recommendation**: Verify the current password in MetaMCP matches Jesse's `.env` PASSWORD field, then rotate credentials if exposure occurred.

## Jesse REST Client Implementation

The `JesseRESTClient` has been updated to:
1. Automatically authenticate on initialization
2. Handle the two-step login flow internally
3. Manage auth tokens transparently
4. Use lowercase `authorization` headers in all requests

## Status

- ✅ Authentication flow discovered and implemented
- ✅ Manual backtest call successful with correct password
- ⚠️ MetaMCP environment variable needs verification
- ⏳ Full MCP tool testing pending
