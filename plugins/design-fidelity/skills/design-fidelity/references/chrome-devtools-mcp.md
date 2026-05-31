# Chrome DevTools MCP Setup Guide

Browser automation and screenshot capabilities for Claude Code. Installed on every role (master + lab + prod) by the harness; operator manages enable/disable via the `/plugin` slash command inside Claude Code.

## Prerequisites

- Node.js 18+ with npm (provided by harness on master + lab WSL)
- A reachable Chrome instance for the MCP to attach to:
  - Master: Windows-side Chrome on the desktop (typical case)
  - Lab: Chrome installed and running with `--remote-debugging-port` exposed (for site-build/frontend work)

## Connection state

When Chrome isn't running with the debug port open, the MCP will show "Failed to connect" in `/plugin` and `/mcp`. That's expected — the MCP daemon is running, it just has nothing to attach to. Launch Chrome with `--remote-debugging-port=9222` (Windows: edit the Chrome shortcut, append the flag) and the MCP picks it up.

## Operator management

```
/plugin    # interactive UI to enable/disable individual MCPs (per-session)
/mcp       # read-only health check across all configured MCPs
```

These two slash commands do different things, often confused (#475):

- `/plugin` is a per-MCP toggle. State is **session-local** — disabling chrome-devtools via `/plugin` reverts at the next Claude Code restart. Use this for routine "I'm about to paste secrets, disable browser automation" gating.
- `/mcp` is a status-only view. It lists every MCP from `~/.claude.json` and shows whether the server is reachable. It does NOT enable/disable.
- To **permanently** remove chrome-devtools from this user's config: `claude mcp remove chrome-devtools`. To re-add: `claude mcp add chrome-devtools --scope user -- npx -y chrome-devtools-mcp@1.0.0`.

Disable per-session via `/plugin` if not actively browser-automating; re-enable when needed.

**Fallback when this MCP is disabled or its tools didn't surface this session**: the `playwright` Python lib drives the same headless chromium without needing an MCP server. See `playwright-fallback.md` for the install + script pattern. Canonical example: a repo-local headless-chromium E2E script. The fallback is also the right choice for cheap re-runnable AP #18 regression scripts (one Bash invocation per E2E flow vs 10-20 tool calls via MCP).

## Security note — browser state exposure

Chrome DevTools MCP runs with full browser access. While enabled, it can read and act on (#475):

- Open tabs, page DOM, navigation state
- Network requests including request/response headers (cookies, auth tokens)
- Pasted text in form fields and DevTools console messages
- Cached credentials surfaced via the page (e.g. autofilled passwords)

**Best practice**: run `/plugin` and disable chrome-devtools BEFORE pasting any secret (PAT, API key, master password) into Claude Code's chat OR into the browser the MCP is attached to. Re-enable only when you actively need browser automation. The session-local toggle (above) is the right granularity — automatic re-enable on next start is fine because the operator-action of starting Claude Code fresh resets the security context anyway.

## Version pinning + offline cache

The MCP server is fetched on demand via `npx -y chrome-devtools-mcp@<version>` (#475). For reproducibility:

- Pin to a known-good version in `claude mcp add` instead of `@latest`. Default canonical: `@1.0.0` (update as upstream lands new releases; revisit at every harness rev).
- For air-gapped / offline-cache scenarios:
  ```bash
  # Pre-bootstrap on a network-connected machine of the same arch:
  npm install -g chrome-devtools-mcp@1.0.0
  # The package now lives at $(npm root -g)/chrome-devtools-mcp
  # Re-register the MCP server pointing at the local install:
  claude mcp remove chrome-devtools
  claude mcp add chrome-devtools --scope user -- node "$(npm root -g)/chrome-devtools-mcp/dist/cli.js"
  ```
  This bypasses npx + network on every Claude Code start.

## Usage Examples

### Take Screenshots
```
Take a screenshot of https://example.com
```

### Navigate and Interact
```
Navigate to http://localhost:8888 and click the "Login" button
```

### Fill Forms
```
Go to the settings page and fill in the username field with "testuser"
```

### Test Backend Responses
```
Navigate to the dashboard, click refresh, and tell me if any errors appear
```

## Tool Categories (26 Tools)

| Category | Tools | Description |
|----------|-------|-------------|
| Input Automation | 8 | click, drag, fill, fill_form, handle_dialog, hover, press_key, upload_file |
| Navigation | 6 | close_page, list_pages, navigate_page, new_page, select_page, wait_for |
| Emulation | 2 | emulate, resize_page |
| Performance | 3 | performance_analyze_insight, performance_start_trace, performance_stop_trace |
| Network | 2 | get_network_request, list_network_requests |
| Debugging | 5 | evaluate_script, get_console_message, list_console_messages, take_screenshot, take_snapshot |

## Live computed-CSS via the MCP

`evaluate_script` is the MCP route for reading `getComputedStyle` on the attached
live page — the MCP equivalent of the headless `page.evaluate` read. The full
property-dict pattern lives in `playwright-fallback.md` ("Live computed-CSS reads"
section); do not duplicate it here — call `evaluate_script` with the same
`getComputedStyle` body when driving a live browser via the MCP.

The **design-fidelity SKILL** — visual design-fidelity loop that orchestrates these
mechanics (`.claude/skills/design-fidelity/SKILL.md`) — defaults to the headless
playwright route (no live browser state); reach for this MCP only for interactive
live inspection.

## Troubleshooting

### MCP Server Not Found
1. Verify server is configured: `claude mcp list`
2. If missing, add via CLI: `claude mcp add chrome-devtools --scope user -- npx -y chrome-devtools-mcp@1.0.0` (pinned version recommended; see Version pinning section)
3. Restart Claude Code completely
4. See [MCP Configuration Guide](mcp-configuration.md) for detailed troubleshooting

### NPX Command Fails
1. Verify Node.js is installed: `node --version`
2. Verify npm is in PATH: `npm --version`
3. Try manual install: `npm install -g chrome-devtools-mcp`

### Browser Doesn't Open
- Chrome DevTools MCP opens a visible browser window
- Check firewall/antivirus isn't blocking
- Try running manually: `npx chrome-devtools-mcp@latest`

## Configuration

**File**: `~/.claude.json` (user scope, added via `claude mcp add`)

See [MCP Configuration Guide](mcp-configuration.md) for setup instructions.

```bash
# Add chrome-devtools server (pinned version recommended over @latest — see Version pinning section)
claude mcp add chrome-devtools --scope user -- npx -y chrome-devtools-mcp@1.0.0
```

## Screenshots Location

Screenshots are saved to: `../screenshots/` (a cross-repo folder one level above the repo, at the workspace root)

> Note: this path is for MCP-driven captures. The design-fidelity helper `shoot.py` (the
> default headless route) writes instead to `~/DevProjects/screenshots/<repo>/` (the
> CWD basename), and `pixel-drift.sh` to `~/DevProjects/screenshots/<repo>/diffs/` —
> both outside any git repo. The two routes use different output dirs by design.

## References

- [Chrome DevTools MCP](https://www.npmjs.com/package/chrome-devtools-mcp)
- [Claude Code MCP Docs](https://docs.anthropic.com/en/docs/claude-code/mcp)
