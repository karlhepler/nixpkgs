-- cathy: A Neovim composer-buffer plugin that drains text to a
-- Claude Code tmux pane via `tmux paste-buffer` on a configurable keymap.
--
-- Usage:
--   :Cathy              opens composer targeting pane 0 of current tmux window
--   :Cathy 5            opens composer targeting pane 5 of current window
--   :Cathy mywin        opens composer targeting pane 0 of window 'mywin'
--   :Cathy mywin.3      opens composer targeting pane 3 of window 'mywin'
--   <leader><CR> in the composer sends everything below the most recent separator
--                to the target pane
--
-- Argument grammar:
--   (none)          → current window, pane 0           (target: :.0)
--   <N>             → current window, pane N           (target: :.N)
--   <window>        → named window, pane 0             (target: window.0)
--   <window>.<N>    → named window, pane N             (target: window.N)
--
-- The resolved tmux target string is stored buffer-local on the composer
-- buffer so the keymap handler knows where to send.
--
-- Default keymap is `<C-CR>` (Ctrl+Enter). For `<C-CR>` to be distinguishable
-- from plain `<CR>`, the terminal must distinguish those two key events. By
-- default, most terminals (including Alacritty without explicit configuration)
-- send `\r` for both Enter and Ctrl+Enter, so the keymap won't fire.
--
-- Modern Neovim (0.10+) automatically negotiates the kitty keyboard protocol
-- with terminals that support it (Kitty, WezTerm, Alacritty 0.13+). When
-- negotiation succeeds, the terminal emits a CSI-u sequence (`\e[13;5u`) for
-- Ctrl+Enter while Neovim is focused, and reverts to legacy behavior in
-- other panes. No terminal config needed — it 'just works' if the terminal
-- and Neovim versions support kkp.
--
-- If `<C-CR>` doesn't fire in practice (auto-negotiation didn't take),
-- override the keymap via setup, e.g.:
--   require('cathy').setup({ keymap = '<C-S-CR>' })
-- or any other unbound key combination of your choice.

local M = {}

-- Module-level default options. Populated at require time so M.send() is
-- callable without a prior M.setup() call (no nil-access on opts fields).
local default_opts = {
  keymap = '<C-CR>',
  separator_width = 80,
  blank_above = 1,
  blank_below = 1,
  notify_on_queue = true,
  command_name = 'Cathy',
  default_pane_index = 0,
  poll_ms = 1000,
  rapid_flush_threshold_ms = 1000,
}

-- Module-level opts: always has full defaults; overwritten by M.setup().
local opts = vim.deepcopy(default_opts)

-- Module-level state for deferred-flush queue.
-- pending_sends: table keyed by buffer handle; value: {buf=nr, target=':.N'}
-- Keying by buf coalesces repeat presses (idempotent).
local pending_sends = {}
-- poll_timer: single vim.loop timer instance, lazily created and started.
local poll_timer = nil

-- Build the separator line for a given pane label.
-- Format: "—— Sent to <session>.<pane> <timestamp> ——" centered to width.
-- param pane_label string e.g. "main.1"
-- param width number total separator width
-- return string separator line
local function make_separator(pane_label, width)
  local timestamp = os.date('%a %b %-d %-I:%M%p')
  local middle = ' Sent to ' .. pane_label .. ' ' .. timestamp .. ' '
  local middle_width = vim.fn.strdisplaywidth(middle)
  local dashes_total = width - middle_width
  -- Split dashes between left and right (left gets the extra if odd)
  local right_dashes = math.floor(dashes_total / 2)
  local left_dashes = dashes_total - right_dashes
  if left_dashes < 1 then left_dashes = 1 end
  if right_dashes < 1 then right_dashes = 1 end
  return string.rep('—', left_dashes) .. middle .. string.rep('—', right_dashes)
end

-- Check whether a buffer line is a separator line produced by this plugin.
-- Anchor: line starts with the em-dash UTF-8 sequence (\xE2\x80\x94), contains
-- the literal ' Sent to ' string, and ends with \x94 (the last byte of any
-- em-dash, since make_separator always ends with a run of em-dashes).
--
-- Why not '—+' (em-dash with Lua + quantifier)?
-- Lua patterns operate on bytes, not codepoints. The em-dash is the 3-byte
-- UTF-8 sequence \xE2\x80\x94. The Lua '+' quantifier applies only to the
-- LAST byte of a multi-byte literal, so '\xE2\x80\x94+' means: match \xE2
-- once, \x80 once, then one-or-more \x94. After the first em-dash, the next
-- byte is \xE2 (the start of the second em-dash), NOT \x94, so the pattern
-- would only match exactly one em-dash before expecting the space. Since
-- make_separator() always produces 20+ em-dashes on each side, '—+' never
-- matches real separators. The pattern below avoids '+' on the em-dash
-- entirely: the leading anchor ^\xE2\x80\x94 ensures the line starts with an
-- em-dash; .* consumes the rest of the leading run; ' Sent to ' is the unique
-- literal; .* consumes label+timestamp+trailing-dashes; \x94$ anchors to the
-- final byte of the last em-dash (which is always \x94).
local SEPARATOR_PATTERN = '^\xE2\x80\x94.* Sent to .*\x94$'

-- Find the 0-based line index of the last separator in the buffer lines table.
-- Returns 0 if no separator found (treat entire buffer as active).
-- param lines table array of string lines (1-indexed in Lua)
-- return number boundary 0-based index of the line AFTER the last separator
local function find_last_separator(lines)
  local boundary = 0
  for i = #lines, 1, -1 do
    if lines[i]:match(SEPARATOR_PATTERN) then
      -- boundary is the 0-based index of the line after the separator
      boundary = i  -- lines is 1-indexed; i == 0-based index + 1
      break
    end
  end
  return boundary
end

-- Strip trailing blank / whitespace-only lines from a table of lines.
-- Modifies the table in-place and returns it.
local function strip_trailing_blank(lines)
  while #lines > 0 and lines[#lines]:match('^%s*$') do
    table.remove(lines)
  end
  return lines
end

-- Check if a tmux target pane is in copy-mode (synchronous).
-- Returns '1' if in copy-mode, '0' otherwise. Returns nil on error.
-- Used on the immediate-send path (fires once per send, not in the poll loop).
local function pane_in_mode(target)
  local result = vim.fn.system({ 'tmux', 'display', '-p', '-t', target, '#{pane_in_mode}' })
  if vim.v.shell_error ~= 0 then
    return nil
  end
  return vim.trim(result)
end

-- Check if a tmux target pane is in copy-mode (asynchronous, nvim 0.10+).
-- Calls `callback(mode)` where mode is '1', '0', or nil (error / pane gone).
-- Used on the poll path to avoid blocking nvim's UI thread each tick.
local function pane_in_mode_async(target, callback)
  vim.system(
    { 'tmux', 'display', '-p', '-t', target, '#{pane_in_mode}' },
    { text = true },
    vim.schedule_wrap(function(result)
      if result.code ~= 0 then
        callback(nil)
      else
        callback(vim.trim(result.stdout or ''))
      end
    end)
  )
end

-- Drain the active region of a composer buffer and paste it to the target pane.
-- This is the core paste algorithm, called both from immediate send and deferred flush.
-- param buf number buffer handle for the composer buffer
-- param target string tmux target string e.g. ':.0'
-- param opts table merged plugin options
local function drain_and_paste(buf, target, opts)
  -- Read all buffer lines
  local all_lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)

  -- Walk backward to find last separator (boundary)
  local boundary = find_last_separator(all_lines)

  -- Active region = lines after boundary
  local active = {}
  for i = boundary + 1, #all_lines do
    table.insert(active, all_lines[i])
  end

  -- Strip trailing blank lines
  active = strip_trailing_blank(active)

  -- Empty → return silently
  if #active == 0 then
    return
  end

  -- Load content into tmux paste buffer via stdin
  vim.fn.system({ 'tmux', 'load-buffer', '-' }, table.concat(active, '\n'))

  -- Paste buffer into target pane.
  -- -p → bracketed paste (wraps content in ESC[200~ / ESC[201~ so TUI input
  --      boxes treat it as a single paste event with literal newlines, not as
  --      individual keystrokes where each \n would trigger submit).
  -- -r → do not replace LF with CR (belt-and-suspenders alongside -p).
  vim.fn.system({ 'tmux', 'paste-buffer', '-p', '-r', '-t', target })

  -- Submit the pasted content (send Enter to the target pane)
  vim.fn.system({ 'tmux', 'send-keys', '-t', target, 'Enter' })

  -- Query pane label for the separator
  local pane_label_raw = vim.fn.system({ 'tmux', 'display', '-p', '-t', target, '#{session_name}.#{pane_index}' })
  local pane_label = vim.trim(pane_label_raw)

  local sep = make_separator(pane_label, opts.separator_width)

  -- Append blank_above, separator, blank_below, and an extra cursor-landing line.
  -- The extra trailing '' preserves blank_below as visible whitespace; the cursor
  -- lands on the new empty line so user typing does not consume the visual gap.
  local append_lines = {}
  for _ = 1, opts.blank_above do
    table.insert(append_lines, '')
  end
  table.insert(append_lines, sep)
  for _ = 1, opts.blank_below do
    table.insert(append_lines, '')
  end
  table.insert(append_lines, '')  -- cursor-landing line: preserves blank_below visually

  local line_count = vim.api.nvim_buf_line_count(buf)
  vim.api.nvim_buf_set_lines(buf, line_count, line_count, false, append_lines)

  -- Move cursor to end of buffer (the extra cursor-landing line) if a window shows buf
  local win_id = vim.fn.bufwinid(buf)
  if win_id ~= -1 then
    local new_line_count = vim.api.nvim_buf_line_count(buf)
    vim.api.nvim_win_set_cursor(win_id, { new_line_count, 0 })
  end
end

-- Flush pending sends: iterate pending_sends and drain any whose target has
-- exited copy-mode. Stop the poll timer if the queue drains to empty.
-- NOTE: This function is called inside vim.schedule_wrap so vim API calls
-- are safe at the call site. The per-entry pane check is async (vim.system)
-- to avoid blocking nvim's UI thread each poll tick. Drain logic runs in the
-- async callback, which is itself wrapped in vim.schedule_wrap.
-- Reads the module-level `opts` upvalue directly.
local function flush_pending()
  for bufnr, entry in pairs(pending_sends) do
    if not vim.api.nvim_buf_is_valid(bufnr) then
      -- Composer buffer was closed; drop without sending
      pending_sends[bufnr] = nil
      if next(pending_sends) == nil and poll_timer then
        poll_timer:stop()
      end
    else
      pane_in_mode_async(entry.target, function(mode)
        if mode == nil then
          -- Target pane no longer exists; drop with notification
          vim.notify('cathy: target pane gone, queued send dropped', vim.log.levels.WARN)
          pending_sends[bufnr] = nil
        elseif mode == '0' then
          -- Target exited copy-mode; drain and paste
          drain_and_paste(entry.buf, entry.target, opts)
          if opts.notify_on_queue then
            vim.notify('Sent (queued release)', vim.log.levels.INFO)
          end
          pending_sends[bufnr] = nil
        end
        -- else: still in copy-mode; leave pending

        -- Stop the timer if nothing is left to poll
        if next(pending_sends) == nil and poll_timer then
          poll_timer:stop()
        end
      end)
    end
  end
end

-- Send the active region of the composer buffer to the given tmux pane.
-- If the target is in copy-mode, queue the send and auto-flush when copy-mode
-- exits (via the deferred-flush poll timer).
-- param buf number composer buffer handle
-- param target string tmux target string e.g. ':.0'
function M.send(buf, target)
  if not target or target == '' then
    vim.notify('No target pane set on this buffer; reopen via :Cathy [<N> | <window> | <window>.<N>]', vim.log.levels.ERROR)
    return
  end

  -- Check if target pane is in copy-mode
  local mode = pane_in_mode(target)
  if mode == '1' then
    -- Queue the send; coalesce by buf (latest target wins, same buf = same target)
    pending_sends[buf] = { buf = buf, target = target, queued_at = vim.loop.now() }

    -- Lazily create the poll timer if it doesn't exist yet
    if not poll_timer then
      poll_timer = vim.loop.new_timer()
    end

    -- Start the timer only if it is not already active (idempotent ensure-running).
    -- Calling start() on an already-running libuv timer resets its interval and
    -- replaces its callback, which is not what we want when multiple sends are
    -- queued before the first tick fires.
    if not poll_timer:is_active() then
      local poll_ms = opts.poll_ms or 1000
      poll_timer:start(poll_ms, poll_ms, vim.schedule_wrap(function()
        flush_pending()
      end))
    end

    if opts.notify_on_queue then
      vim.notify('Claude pane is scrolling — send queued; will flush when copy-mode exits', vim.log.levels.INFO)
    end
    return
  end

  -- Target not in copy-mode: drain and paste immediately
  drain_and_paste(buf, target, opts)
end

-- Setup the cathy plugin.
-- param user_opts table|nil optional configuration overrides
function M.setup(user_opts)
  -- Merge user overrides onto a fresh copy of defaults and write back to the
  -- module-level `opts` upvalue so M.send() and flush_pending() see them.
  opts = vim.tbl_deep_extend('force', vim.deepcopy(default_opts), user_opts or {})

  -- Register the user-command
  -- nargs='?' means zero or one argument
  vim.api.nvim_create_user_command(opts.command_name, function(args)
    -- Parse argument using the extended grammar:
    --   (none)       → current window, default pane  (:.0)
    --   <N>          → current window, pane N        (:.N)
    --   <window>     → named window, default pane    (window.0)
    --   <window>.<N> → named window, pane N          (window.N)
    local arg = args.args or ''
    local target
    if arg == '' then
      -- Default: pane 0 of current window
      target = ':.' .. tostring(opts.default_pane_index)
    elseif arg:match('^%d+$') then
      -- All digits: pane index in current window
      target = ':.' .. arg
    elseif arg:find('.', 1, true) then
      -- Contains a dot: window.pane spec
      local window, pane_str = arg:match('^(.*)%.(.*)$')
      if window == '' and pane_str:match('^%d+$') then
        -- '.N' → :.N (treat as current window)
        target = ':.' .. pane_str
      elseif window == '' then
        vim.notify('Cathy: invalid argument: ' .. arg, vim.log.levels.ERROR)
        return
      elseif pane_str == '' then
        -- 'window.' → window.0
        target = window .. '.' .. tostring(opts.default_pane_index)
      elseif pane_str:match('^%d+$') then
        target = window .. '.' .. pane_str
      else
        vim.notify('Cathy: pane index after dot must be numeric (got: ' .. arg .. ')', vim.log.levels.ERROR)
        return
      end
    else
      -- Non-digit, no dot: window name only, default pane
      target = arg .. '.' .. tostring(opts.default_pane_index)
    end

    -- Find existing [cathy] buffer by name, or create a fresh one
    local buf = -1
    for _, b in ipairs(vim.api.nvim_list_bufs()) do
      if vim.api.nvim_buf_get_name(b):match('%[cathy%]$') then
        buf = b
        break
      end
    end
    if buf == -1 then
      buf = vim.api.nvim_create_buf(true, true)
      vim.api.nvim_buf_set_name(buf, '[cathy]')
    end

    -- Set buffer-local options
    -- nvim_create_buf(true, true) already sets buftype=nofile; don't override buftype.
    vim.bo[buf].bufhidden = 'hide'
    vim.bo[buf].swapfile = false
    -- filetype MUST be markdown: buffer name has no .md extension so auto-detect
    -- won't fire. Explicit assignment ensures syntax highlighting, treesitter,
    -- and concealing rules apply.
    vim.bo[buf].filetype = 'markdown'

    -- Store target buffer-local so the keymap callback can read it
    vim.b[buf].claude_pane_target = target

    -- Open (or focus) the composer buffer in the current window
    local win_id = vim.fn.bufwinid(buf)
    if win_id == -1 then
      -- Composer buffer is not visible — swap the current window to it (no split)
      vim.api.nvim_win_set_buf(0, buf)
      -- Enable word wrap in the cathy window
      vim.wo[0].wrap = true
      vim.wo[0].linebreak = true   -- wrap at word boundaries (not mid-word)
      vim.wo[0].breakindent = true -- continuation lines align with leading indent
    else
      -- Composer buffer already visible — focus that window
      vim.api.nvim_set_current_win(win_id)
      -- Enable word wrap in the cathy window
      vim.wo[0].wrap = true
      vim.wo[0].linebreak = true   -- wrap at word boundaries (not mid-word)
      vim.wo[0].breakindent = true -- continuation lines align with leading indent
    end

    -- Set buffer-local keymap for both normal and insert modes.
    vim.keymap.set({ 'n', 'i' }, opts.keymap, function()
      local t = vim.b[buf].claude_pane_target
      if not t or t == '' then
        vim.notify('No target pane set on this buffer; reopen via :Cathy [<N> | <window> | <window>.<N>]', vim.log.levels.ERROR)
        return
      end

      -- Rapid double-press force-flush: if there is already a queued send for
      -- this buffer and the user pressed the keymap again within the rapid-flush
      -- threshold, force-exit copy-mode and drain immediately.
      local now = vim.loop.now()
      local entry = pending_sends[buf]
      if entry and entry.queued_at and (now - entry.queued_at) < opts.rapid_flush_threshold_ms then
        -- Rapid double-press path — send 'q' to force-exit copy-mode, then drain.
        vim.system(
          { 'tmux', 'send-keys', '-t', t, 'q' },
          { text = true },
          vim.schedule_wrap(function(_)
            pending_sends[buf] = nil
            if next(pending_sends) == nil and poll_timer then
              poll_timer:stop()
            end
            if opts.notify_on_queue then
              vim.notify('Cathy: force-flushing queued send', vim.log.levels.INFO)
            end
            drain_and_paste(buf, t, opts)
          end)
        )
        return
      end

      M.send(buf, t)
    end, { buffer = buf, desc = 'Send composer tail to Claude pane (auto-queues if pane is scrolling)' })

    -- Move cursor to end of buffer
    local line_count = vim.api.nvim_buf_line_count(buf)
    vim.api.nvim_win_set_cursor(0, { line_count, 0 })
  end, { nargs = '?', desc = 'Open (or focus) the Claude composer buffer. Args: [<N> | <window> | <window>.<N>]. Default pane 0 of current window.' })
end

return M
