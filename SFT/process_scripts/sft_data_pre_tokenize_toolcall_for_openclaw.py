tools=[
        {
          "type": "function",
          "function": {
            "name": "read",
            "description": "Read the contents of a file. Supports text files and images (jpg, png, gif, webp). Images are sent as attachments. For text files, output is truncated to 2000 lines or 50KB (whichever is hit first). Use offset/limit for large files. When you need the full file, continue with offset until complete.",
            "parameters": {
              "type": "object",
              "required": [],
              "properties": {
                "path": {
                  "description": "Path to the file to read (relative or absolute)",
                  "type": "string"
                },
                "offset": {
                  "description": "Line number to start reading from (1-indexed)",
                  "type": "number"
                },
                "limit": {
                  "description": "Maximum number of lines to read",
                  "type": "number"
                },
                "file_path": {
                  "description": "Path to the file to read (relative or absolute)",
                  "type": "string"
                },
                "filePath": {
                  "description": "Path to the file to read (relative or absolute)",
                  "type": "string"
                },
                "file": {
                  "description": "Path to the file to read (relative or absolute)",
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "edit",
            "description": "Edit a file by replacing exact text. The oldText must match exactly (including whitespace). Use this for precise, surgical edits.",
            "parameters": {
              "type": "object",
              "required": [],
              "properties": {
                "path": {
                  "description": "Path to the file to edit (relative or absolute)",
                  "type": "string"
                },
                "oldText": {
                  "description": "Exact text to find and replace (must match exactly)",
                  "type": "string"
                },
                "newText": {
                  "description": "New text to replace the old text with",
                  "type": "string"
                },
                "file_path": {
                  "description": "Path to the file to edit (relative or absolute)",
                  "type": "string"
                },
                "filePath": {
                  "description": "Path to the file to edit (relative or absolute)",
                  "type": "string"
                },
                "file": {
                  "description": "Path to the file to edit (relative or absolute)",
                  "type": "string"
                },
                "old_string": {
                  "description": "Exact text to find and replace (must match exactly)",
                  "type": "string"
                },
                "old_text": {
                  "description": "Exact text to find and replace (must match exactly)",
                  "type": "string"
                },
                "oldString": {
                  "description": "Exact text to find and replace (must match exactly)",
                  "type": "string"
                },
                "new_string": {
                  "description": "New text to replace the old text with",
                  "type": "string"
                },
                "new_text": {
                  "description": "New text to replace the old text with",
                  "type": "string"
                },
                "newString": {
                  "description": "New text to replace the old text with",
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "write",
            "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories.",
            "parameters": {
              "type": "object",
              "required": [
                "content"
              ],
              "properties": {
                "path": {
                  "description": "Path to the file to write (relative or absolute)",
                  "type": "string"
                },
                "content": {
                  "description": "Content to write to the file",
                  "type": "string"
                },
                "file_path": {
                  "description": "Path to the file to write (relative or absolute)",
                  "type": "string"
                },
                "filePath": {
                  "description": "Path to the file to write (relative or absolute)",
                  "type": "string"
                },
                "file": {
                  "description": "Path to the file to write (relative or absolute)",
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "exec",
            "description": "Execute shell commands with background continuation. Use yieldMs/background to continue later via process tool. Use pty=true for TTY-required commands (terminal UIs, coding agents).",
            "parameters": {
              "type": "object",
              "required": [
                "command"
              ],
              "properties": {
                "command": {
                  "description": "Shell command to execute",
                  "type": "string"
                },
                "workdir": {
                  "description": "Working directory (defaults to cwd)",
                  "type": "string"
                },
                "env": {
                  "type": "object",
                  "patternProperties": {
                    "^(.*)$": {
                      "type": "string"
                    }
                  }
                },
                "yieldMs": {
                  "description": "Milliseconds to wait before backgrounding (default 10000)",
                  "type": "number"
                },
                "background": {
                  "description": "Run in background immediately",
                  "type": "boolean"
                },
                "timeout": {
                  "description": "Timeout in seconds (optional, kills process on expiry)",
                  "type": "number"
                },
                "pty": {
                  "description": "Run in a pseudo-terminal (PTY) when available (TTY-required CLIs, coding agents)",
                  "type": "boolean"
                },
                "elevated": {
                  "description": "Run on the host with elevated permissions (if allowed)",
                  "type": "boolean"
                },
                "host": {
                  "description": "Exec host (sandbox|gateway|node).",
                  "type": "string"
                },
                "security": {
                  "description": "Exec security mode (deny|allowlist|full).",
                  "type": "string"
                },
                "ask": {
                  "description": "Exec ask mode (off|on-miss|always).",
                  "type": "string"
                },
                "node": {
                  "description": "Node id/name for host=node.",
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "process",
            "description": "Manage running exec sessions: list, poll, log, write, send-keys, submit, paste, kill.",
            "parameters": {
              "type": "object",
              "required": [
                "action"
              ],
              "properties": {
                "action": {
                  "description": "Process action",
                  "type": "string"
                },
                "sessionId": {
                  "description": "Session id for actions other than list",
                  "type": "string"
                },
                "data": {
                  "description": "Data to write for write",
                  "type": "string"
                },
                "keys": {
                  "description": "Key tokens to send for send-keys",
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "hex": {
                  "description": "Hex bytes to send for send-keys",
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "literal": {
                  "description": "Literal string for send-keys",
                  "type": "string"
                },
                "text": {
                  "description": "Text to paste for paste",
                  "type": "string"
                },
                "bracketed": {
                  "description": "Wrap paste in bracketed mode",
                  "type": "boolean"
                },
                "eof": {
                  "description": "Close stdin after write",
                  "type": "boolean"
                },
                "offset": {
                  "description": "Log offset",
                  "type": "number"
                },
                "limit": {
                  "description": "Log length",
                  "type": "number"
                },
                "timeout": {
                  "description": "For poll: wait up to this many milliseconds before returning",
                  "minimum": 0,
                  "type": "number"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "browser",
            "description": "Control the browser via OpenClaw's browser control server (status/start/stop/profiles/tabs/open/snapshot/screenshot/actions). Browser choice: omit profile by default for the isolated OpenClaw-managed browser (`openclaw`). For the logged-in user browser on the local host, use profile=\"user\". A supported Chromium-based browser (v144+) must be running. Use only when existing logins/cookies matter and the user is present. When a node-hosted browser proxy is available, the tool may auto-route to it. Pin a node with node=<id|name> or target=\"node\". When using refs from snapshot (e.g. e12), keep the same tab: prefer passing targetId from the snapshot response into subsequent actions (act/click/type/etc). For stable, self-resolving refs across calls, use snapshot with refs=\"aria\" (Playwright aria-ref ids). Default refs=\"role\" are role+name-based. Use snapshot+act for UI automation. Avoid act:wait by default; use only in exceptional cases when no reliable UI state exists. target selects browser location (sandbox|host|node). Default: host. Host target allowed.",
            "parameters": {
              "type": "object",
              "required": [
                "action"
              ],
              "properties": {
                "action": {
                  "type": "string",
                  "enum": [
                    "status",
                    "start",
                    "stop",
                    "profiles",
                    "tabs",
                    "open",
                    "focus",
                    "close",
                    "snapshot",
                    "screenshot",
                    "navigate",
                    "console",
                    "pdf",
                    "upload",
                    "dialog",
                    "act"
                  ]
                },
                "target": {
                  "type": "string",
                  "enum": [
                    "sandbox",
                    "host",
                    "node"
                  ]
                },
                "node": {
                  "type": "string"
                },
                "profile": {
                  "type": "string"
                },
                "targetUrl": {
                  "type": "string"
                },
                "url": {
                  "type": "string"
                },
                "targetId": {
                  "type": "string"
                },
                "limit": {
                  "type": "number"
                },
                "maxChars": {
                  "type": "number"
                },
                "mode": {
                  "type": "string",
                  "enum": [
                    "efficient"
                  ]
                },
                "snapshotFormat": {
                  "type": "string",
                  "enum": [
                    "aria",
                    "ai"
                  ]
                },
                "refs": {
                  "type": "string",
                  "enum": [
                    "role",
                    "aria"
                  ]
                },
                "interactive": {
                  "type": "boolean"
                },
                "compact": {
                  "type": "boolean"
                },
                "depth": {
                  "type": "number"
                },
                "selector": {
                  "type": "string"
                },
                "frame": {
                  "type": "string"
                },
                "labels": {
                  "type": "boolean"
                },
                "fullPage": {
                  "type": "boolean"
                },
                "ref": {
                  "type": "string"
                },
                "element": {
                  "type": "string"
                },
                "type": {
                  "type": "string",
                  "enum": [
                    "png",
                    "jpeg"
                  ]
                },
                "level": {
                  "type": "string"
                },
                "paths": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "inputRef": {
                  "type": "string"
                },
                "timeoutMs": {
                  "type": "number"
                },
                "accept": {
                  "type": "boolean"
                },
                "promptText": {
                  "type": "string"
                },
                "kind": {
                  "type": "string",
                  "enum": [
                    "click",
                    "type",
                    "press",
                    "hover",
                    "drag",
                    "select",
                    "fill",
                    "resize",
                    "wait",
                    "evaluate",
                    "close"
                  ]
                },
                "doubleClick": {
                  "type": "boolean"
                },
                "button": {
                  "type": "string"
                },
                "modifiers": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "text": {
                  "type": "string"
                },
                "submit": {
                  "type": "boolean"
                },
                "slowly": {
                  "type": "boolean"
                },
                "key": {
                  "type": "string"
                },
                "delayMs": {
                  "type": "number"
                },
                "startRef": {
                  "type": "string"
                },
                "endRef": {
                  "type": "string"
                },
                "values": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "fields": {
                  "type": "array",
                  "items": {
                    "additionalProperties": True,
                    "type": "object",
                    "properties": {}
                  }
                },
                "width": {
                  "type": "number"
                },
                "height": {
                  "type": "number"
                },
                "timeMs": {
                  "type": "number"
                },
                "textGone": {
                  "type": "string"
                },
                "loadState": {
                  "type": "string"
                },
                "fn": {
                  "type": "string"
                },
                "request": {
                  "type": "object",
                  "required": [
                    "kind"
                  ],
                  "properties": {
                    "kind": {
                      "type": "string",
                      "enum": [
                        "click",
                        "type",
                        "press",
                        "hover",
                        "drag",
                        "select",
                        "fill",
                        "resize",
                        "wait",
                        "evaluate",
                        "close"
                      ]
                    },
                    "targetId": {
                      "type": "string"
                    },
                    "ref": {
                      "type": "string"
                    },
                    "doubleClick": {
                      "type": "boolean"
                    },
                    "button": {
                      "type": "string"
                    },
                    "modifiers": {
                      "type": "array",
                      "items": {
                        "type": "string"
                      }
                    },
                    "text": {
                      "type": "string"
                    },
                    "submit": {
                      "type": "boolean"
                    },
                    "slowly": {
                      "type": "boolean"
                    },
                    "key": {
                      "type": "string"
                    },
                    "delayMs": {
                      "type": "number"
                    },
                    "startRef": {
                      "type": "string"
                    },
                    "endRef": {
                      "type": "string"
                    },
                    "values": {
                      "type": "array",
                      "items": {
                        "type": "string"
                      }
                    },
                    "fields": {
                      "type": "array",
                      "items": {
                        "additionalProperties": True,
                        "type": "object",
                        "properties": {}
                      }
                    },
                    "width": {
                      "type": "number"
                    },
                    "height": {
                      "type": "number"
                    },
                    "timeMs": {
                      "type": "number"
                    },
                    "selector": {
                      "type": "string"
                    },
                    "url": {
                      "type": "string"
                    },
                    "loadState": {
                      "type": "string"
                    },
                    "textGone": {
                      "type": "string"
                    },
                    "timeoutMs": {
                      "type": "number"
                    },
                    "fn": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "canvas",
            "description": "Control node canvases (present/hide/navigate/eval/snapshot/A2UI). Use snapshot to capture the rendered UI.",
            "parameters": {
              "type": "object",
              "required": [
                "action"
              ],
              "properties": {
                "action": {
                  "type": "string",
                  "enum": [
                    "present",
                    "hide",
                    "navigate",
                    "eval",
                    "snapshot",
                    "a2ui_push",
                    "a2ui_reset"
                  ]
                },
                "gatewayUrl": {
                  "type": "string"
                },
                "gatewayToken": {
                  "type": "string"
                },
                "timeoutMs": {
                  "type": "number"
                },
                "node": {
                  "type": "string"
                },
                "target": {
                  "type": "string"
                },
                "x": {
                  "type": "number"
                },
                "y": {
                  "type": "number"
                },
                "width": {
                  "type": "number"
                },
                "height": {
                  "type": "number"
                },
                "url": {
                  "type": "string"
                },
                "javaScript": {
                  "type": "string"
                },
                "outputFormat": {
                  "type": "string",
                  "enum": [
                    "png",
                    "jpg",
                    "jpeg"
                  ]
                },
                "maxWidth": {
                  "type": "number"
                },
                "quality": {
                  "type": "number"
                },
                "delayMs": {
                  "type": "number"
                },
                "jsonl": {
                  "type": "string"
                },
                "jsonlPath": {
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "message",
            "description": "Send, delete, and manage messages via channel plugins. Supports actions: send, broadcast.",
            "parameters": {
              "type": "object",
              "required": [
                "action"
              ],
              "properties": {
                "action": {
                  "type": "string",
                  "enum": [
                    "send",
                    "broadcast"
                  ]
                },
                "channel": {
                  "type": "string"
                },
                "target": {
                  "description": "Target channel/user id or name.",
                  "type": "string"
                },
                "targets": {
                  "type": "array",
                  "items": {
                    "description": "Recipient/channel targets (same format as --target); accepts ids or names when the directory is available.",
                    "type": "string"
                  }
                },
                "accountId": {
                  "type": "string"
                },
                "dryRun": {
                  "type": "boolean"
                },
                "message": {
                  "type": "string"
                },
                "effectId": {
                  "description": "Message effect name/id for sendWithEffect (e.g., invisible ink).",
                  "type": "string"
                },
                "effect": {
                  "description": "Alias for effectId (e.g., invisible-ink, balloons).",
                  "type": "string"
                },
                "media": {
                  "description": "Media URL or local path. data: URLs are not supported here, use buffer.",
                  "type": "string"
                },
                "filename": {
                  "type": "string"
                },
                "buffer": {
                  "description": "Base64 payload for attachments (optionally a data: URL).",
                  "type": "string"
                },
                "contentType": {
                  "type": "string"
                },
                "mimeType": {
                  "type": "string"
                },
                "caption": {
                  "type": "string"
                },
                "path": {
                  "type": "string"
                },
                "filePath": {
                  "type": "string"
                },
                "replyTo": {
                  "type": "string"
                },
                "threadId": {
                  "type": "string"
                },
                "asVoice": {
                  "type": "boolean"
                },
                "silent": {
                  "type": "boolean"
                },
                "quoteText": {
                  "description": "Quote text for Telegram reply_parameters",
                  "type": "string"
                },
                "bestEffort": {
                  "type": "boolean"
                },
                "gifPlayback": {
                  "type": "boolean"
                },
                "forceDocument": {
                  "description": "Send image/GIF as document to avoid Telegram compression (Telegram only).",
                  "type": "boolean"
                },
                "asDocument": {
                  "description": "Send image/GIF as document to avoid Telegram compression. Alias for forceDocument (Telegram only).",
                  "type": "boolean"
                },
                "messageId": {
                  "description": "Target message id for reaction. If omitted, defaults to the current inbound message id when available.",
                  "type": "string"
                },
                "message_id": {
                  "description": "snake_case alias of messageId. If omitted, defaults to the current inbound message id when available.",
                  "type": "string"
                },
                "emoji": {
                  "type": "string"
                },
                "remove": {
                  "type": "boolean"
                },
                "targetAuthor": {
                  "type": "string"
                },
                "targetAuthorUuid": {
                  "type": "string"
                },
                "groupId": {
                  "type": "string"
                },
                "limit": {
                  "type": "number"
                },
                "pageSize": {
                  "type": "number"
                },
                "pageToken": {
                  "type": "string"
                },
                "before": {
                  "type": "string"
                },
                "after": {
                  "type": "string"
                },
                "around": {
                  "type": "string"
                },
                "fromMe": {
                  "type": "boolean"
                },
                "includeArchived": {
                  "type": "boolean"
                },
                "pollId": {
                  "type": "string"
                },
                "pollOptionId": {
                  "description": "Poll answer id to vote for. Use when the channel exposes stable answer ids.",
                  "type": "string"
                },
                "pollOptionIds": {
                  "type": "array",
                  "items": {
                    "description": "Poll answer ids to vote for in a multiselect poll. Use when the channel exposes stable answer ids.",
                    "type": "string"
                  }
                },
                "pollOptionIndex": {
                  "description": "1-based poll option number to vote for, matching the rendered numbered poll choices.",
                  "type": "number"
                },
                "pollOptionIndexes": {
                  "type": "array",
                  "items": {
                    "description": "1-based poll option numbers to vote for in a multiselect poll, matching the rendered numbered poll choices.",
                    "type": "number"
                  }
                },
                "pollQuestion": {
                  "type": "string"
                },
                "pollOption": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "pollDurationHours": {
                  "type": "number"
                },
                "pollMulti": {
                  "type": "boolean"
                },
                "channelId": {
                  "description": "Channel id filter (search/thread list/event create).",
                  "type": "string"
                },
                "chatId": {
                  "description": "Chat id for chat-scoped metadata actions.",
                  "type": "string"
                },
                "channelIds": {
                  "type": "array",
                  "items": {
                    "description": "Channel id filter (repeatable).",
                    "type": "string"
                  }
                },
                "memberId": {
                  "type": "string"
                },
                "memberIdType": {
                  "type": "string"
                },
                "guildId": {
                  "type": "string"
                },
                "userId": {
                  "type": "string"
                },
                "openId": {
                  "type": "string"
                },
                "unionId": {
                  "type": "string"
                },
                "authorId": {
                  "type": "string"
                },
                "authorIds": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "roleId": {
                  "type": "string"
                },
                "roleIds": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "participant": {
                  "type": "string"
                },
                "includeMembers": {
                  "type": "boolean"
                },
                "members": {
                  "type": "boolean"
                },
                "scope": {
                  "type": "string"
                },
                "kind": {
                  "type": "string"
                },
                "emojiName": {
                  "type": "string"
                },
                "stickerId": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "stickerName": {
                  "type": "string"
                },
                "stickerDesc": {
                  "type": "string"
                },
                "stickerTags": {
                  "type": "string"
                },
                "threadName": {
                  "type": "string"
                },
                "autoArchiveMin": {
                  "type": "number"
                },
                "appliedTags": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "query": {
                  "type": "string"
                },
                "eventName": {
                  "type": "string"
                },
                "eventType": {
                  "type": "string"
                },
                "startTime": {
                  "type": "string"
                },
                "endTime": {
                  "type": "string"
                },
                "desc": {
                  "type": "string"
                },
                "location": {
                  "type": "string"
                },
                "durationMin": {
                  "type": "number"
                },
                "until": {
                  "type": "string"
                },
                "reason": {
                  "type": "string"
                },
                "deleteDays": {
                  "type": "number"
                },
                "gatewayUrl": {
                  "type": "string"
                },
                "gatewayToken": {
                  "type": "string"
                },
                "timeoutMs": {
                  "type": "number"
                },
                "name": {
                  "type": "string"
                },
                "type": {
                  "type": "number"
                },
                "parentId": {
                  "type": "string"
                },
                "topic": {
                  "type": "string"
                },
                "position": {
                  "type": "number"
                },
                "nsfw": {
                  "type": "boolean"
                },
                "rateLimitPerUser": {
                  "type": "number"
                },
                "categoryId": {
                  "type": "string"
                },
                "clearParent": {
                  "description": "Clear the parent/category when supported by the provider.",
                  "type": "boolean"
                },
                "activityType": {
                  "description": "Activity type: playing, streaming, listening, watching, competing, custom.",
                  "type": "string"
                },
                "activityName": {
                  "description": "Activity name shown in sidebar (e.g. 'with fire'). Ignored for custom type.",
                  "type": "string"
                },
                "activityUrl": {
                  "description": "Streaming URL (Twitch or YouTube). Only used with streaming type; may not render for bots.",
                  "type": "string"
                },
                "activityState": {
                  "description": "State text. For custom type this is the status text; for others it shows in the flyout.",
                  "type": "string"
                },
                "status": {
                  "description": "Bot status: online, dnd, idle, invisible.",
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "tts",
            "description": "Convert text to speech. Audio is delivered automatically from the tool result — reply with NO_REPLY after a successful call to avoid duplicate messages.",
            "parameters": {
              "type": "object",
              "required": [
                "text"
              ],
              "properties": {
                "text": {
                  "description": "Text to convert to speech.",
                  "type": "string"
                },
                "channel": {
                  "description": "Optional channel id to pick output format (e.g. telegram).",
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "agents_list",
            "description": "List OpenClaw agent ids you can target with `sessions_spawn` when `runtime=\"subagent\"` (based on subagent allowlists).",
            "parameters": {
              "type": "object",
              "properties": {}
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "sessions_list",
            "description": "List sessions with optional filters and last messages.",
            "parameters": {
              "type": "object",
              "properties": {
                "kinds": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                },
                "limit": {
                  "minimum": 1,
                  "type": "number"
                },
                "activeMinutes": {
                  "minimum": 1,
                  "type": "number"
                },
                "messageLimit": {
                  "minimum": 0,
                  "type": "number"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "sessions_history",
            "description": "Fetch message history for a session.",
            "parameters": {
              "type": "object",
              "required": [
                "sessionKey"
              ],
              "properties": {
                "sessionKey": {
                  "type": "string"
                },
                "limit": {
                  "minimum": 1,
                  "type": "number"
                },
                "includeTools": {
                  "type": "boolean"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "sessions_send",
            "description": "Send a message into another session. Use sessionKey or label to identify the target.",
            "parameters": {
              "type": "object",
              "required": [
                "message"
              ],
              "properties": {
                "sessionKey": {
                  "type": "string"
                },
                "label": {
                  "minLength": 1,
                  "maxLength": 512,
                  "type": "string"
                },
                "agentId": {
                  "minLength": 1,
                  "maxLength": 64,
                  "type": "string"
                },
                "message": {
                  "type": "string"
                },
                "timeoutSeconds": {
                  "minimum": 0,
                  "type": "number"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "sessions_yield",
            "description": "End your current turn. Use after spawning subagents to receive their results as the next message.",
            "parameters": {
              "type": "object",
              "properties": {
                "message": {
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "sessions_spawn",
            "description": "Spawn an isolated session (runtime=\"subagent\" or runtime=\"acp\"). mode=\"run\" is one-shot and mode=\"session\" is persistent/thread-bound. Subagents inherit the parent workspace directory automatically.",
            "parameters": {
              "type": "object",
              "required": [
                "task"
              ],
              "properties": {
                "task": {
                  "type": "string"
                },
                "label": {
                  "type": "string"
                },
                "runtime": {
                  "type": "string",
                  "enum": [
                    "subagent",
                    "acp"
                  ]
                },
                "agentId": {
                  "type": "string"
                },
                "resumeSessionId": {
                  "description": "Resume an existing agent session by its ID (e.g. a Codex session UUID from ~/.codex/sessions/). Requires runtime=\"acp\". The agent replays conversation history via session/load instead of starting fresh.",
                  "type": "string"
                },
                "model": {
                  "type": "string"
                },
                "thinking": {
                  "type": "string"
                },
                "cwd": {
                  "type": "string"
                },
                "runTimeoutSeconds": {
                  "minimum": 0,
                  "type": "number"
                },
                "timeoutSeconds": {
                  "minimum": 0,
                  "type": "number"
                },
                "thread": {
                  "type": "boolean"
                },
                "mode": {
                  "type": "string",
                  "enum": [
                    "run",
                    "session"
                  ]
                },
                "cleanup": {
                  "type": "string",
                  "enum": [
                    "delete",
                    "keep"
                  ]
                },
                "sandbox": {
                  "type": "string",
                  "enum": [
                    "inherit",
                    "require"
                  ]
                },
                "streamTo": {
                  "type": "string",
                  "enum": [
                    "parent"
                  ]
                },
                "attachments": {
                  "maxItems": 50,
                  "type": "array",
                  "items": {
                    "type": "object",
                    "required": [
                      "name",
                      "content"
                    ],
                    "properties": {
                      "name": {
                        "type": "string"
                      },
                      "content": {
                        "type": "string"
                      },
                      "encoding": {
                        "type": "string",
                        "enum": [
                          "utf8",
                          "base64"
                        ]
                      },
                      "mimeType": {
                        "type": "string"
                      }
                    }
                  }
                },
                "attachAs": {
                  "type": "object",
                  "properties": {
                    "mountPath": {
                      "type": "string"
                    }
                  }
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "subagents",
            "description": "List, kill, or steer spawned sub-agents for this requester session. Use this for sub-agent orchestration.",
            "parameters": {
              "type": "object",
              "properties": {
                "action": {
                  "type": "string",
                  "enum": [
                    "list",
                    "kill",
                    "steer"
                  ]
                },
                "target": {
                  "type": "string"
                },
                "message": {
                  "type": "string"
                },
                "recentMinutes": {
                  "minimum": 1,
                  "type": "number"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "session_status",
            "description": "Show a /status-equivalent session status card (usage + time + cost when available). Use for model-use questions (📊 session_status). Optional: set per-session model override (model=default resets overrides).",
            "parameters": {
              "type": "object",
              "properties": {
                "sessionKey": {
                  "type": "string"
                },
                "model": {
                  "type": "string"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "web_fetch",
            "description": "Fetch and extract readable content from a URL (HTML → markdown/text). Use for lightweight page access without browser automation.",
            "parameters": {
              "type": "object",
              "required": [
                "url"
              ],
              "properties": {
                "url": {
                  "description": "HTTP or HTTPS URL to fetch.",
                  "type": "string"
                },
                "extractMode": {
                  "type": "string",
                  "enum": [
                    "markdown",
                    "text"
                  ],
                  "description": "Extraction mode (\"markdown\" or \"text\").",
                  "default": "markdown"
                },
                "maxChars": {
                  "description": "Maximum characters to return (truncates when exceeded).",
                  "minimum": 100,
                  "type": "number"
                }
              }
            }
          }
        },
        {
          "type": "function",
          "function": {
            "name": "memory_get",
            "description": "Safe snippet read from MEMORY.md or memory/*.md with optional from/lines; use after memory_search to pull only the needed lines and keep context small.",
            "parameters": {
              "type": "object",
              "required": [
                "path"
              ],
              "properties": {
                "path": {
                  "type": "string"
                },
                "from": {
                  "type": "number"
                },
                "lines": {
                  "type": "number"
                }
              }
            }
          }
        }
      ]

from typing import Callable

import torch
from torch.utils.data import Dataset

# from openrlhf.utils.utils import zero_pad_sequences

# keep support for conversations style
def preprocess_data(
    data, input_template=None, input_key="messages", output_key=None, apply_chat_template=None, multiturn=False
):
    if apply_chat_template:
        if output_key:
            exit()
            # prompt_message = data[input_key]
            # response_message = data[output_key]

            # if isinstance(prompt_message, str) and isinstance(response_message, str):
            #     prompt_message = [{"role": "user", "content": prompt_message}]
            #     response_message = [{"role": "assistant", "content": response_message}]

            # prompt = apply_chat_template(prompt_message, tokenize=False, add_generation_prompt=True)
            # response = apply_chat_template(prompt_message + response_message, tokenize=False)[len(prompt) :]
        else:
            prompt = apply_chat_template(data[input_key][:-1], tools = tools, tokenize=False, add_generation_prompt=True)
            response = apply_chat_template(data[input_key], tools = tools, tokenize=False)[len(prompt) :]
    else:
        prompt = data[input_key]
        if input_template:
            prompt = input_template.format(prompt)
        # output_key is None for continue pretrain
        response = data[output_key] if output_key else ""
    return prompt, response


class SFTDataset(Dataset):
    """
    Dataset for SFT model

    Args:
        dataset: dataset for SFT model
        tokenizer: tokenizer for SFT model
        max_length: max length of input
    """

    def __init__(
        self,
        dataset,
        tokenizer: Callable,
        max_length: int,
        strategy,
        input_template=None,
        pretrain_mode=False,
        num_processors=16,  # Specify the number of processors you want to use
        multiturn=False,
        tokenizer_path = "",
        data_file = ""
    ) -> None:
        super().__init__()
        self.tokenizer = tokenizer
        self.strategy = strategy
        self.pretrain_mode = pretrain_mode
        self.max_length = max_length
        self.multiturn = multiturn

        # chat template
        self.input_template = input_template
        self.input_key = getattr(self.strategy.args, "input_key", None)
        self.output_key = getattr(self.strategy.args, "output_key", None)
        self.apply_chat_template = getattr(self.strategy.args, "apply_chat_template", True)

        if self.apply_chat_template:
            self.apply_chat_template = self.tokenizer.apply_chat_template
            tokenizer_chat_template = getattr(self.strategy.args, "tokenizer_chat_template", None)
            if tokenizer_chat_template:
                self.tokenizer.chat_template = tokenizer_chat_template
        print(dataset)
        # exit()
        # Parallel loading datasets

        print(f"tokenizer path: {tokenizer_path}")
        tokenzier_name = tokenizer_path.split("/")[-1]
        file_name = data_file.split("/")[-1].strip("jsonl")
        out_file = f"/volume/posttrain/users/lyang/openclaw-sft/datasets/{file_name}_processed_{tokenzier_name}_w-maskrange_w_tools.jsonl"
        print(f"out_file path: {out_file}")

        processed_dataset = dataset.map(
            self.process_data,
            # remove_columns=dataset.column_names,
            num_proc=num_processors,
        )
        print(processed_dataset)
        # out_file = "/code/sunshuang/R2E-Gym-fork/results/11_18_all_filtered_processed_Qwen2.5-Coder-7B-Instruct.jsonl"
        
        with open(out_file, "w", encoding="utf-8") as f:
            for sample in processed_dataset:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")

        print(f"已写入 {os.path.abspath(out_file)}，共 {len(processed_dataset)} 行")
        exit()
        processed_dataset = processed_dataset.filter(lambda x: x["prompt"] is not None)
        
        # Store the processed data in class attributes
        self.prompts = processed_dataset["prompt"]
        self.responses = processed_dataset["response"]
        self.prompt_ids_lens = processed_dataset["prompt_ids_len"]
        self.response_ranges = processed_dataset["response_ranges"] if self.multiturn else None

    def process_data(self, data):
        if self.multiturn and self.output_key:
            data[self.input_key].append(data[self.output_key])
            data[self.output_key] = None

        if self.multiturn:
            assert (
                not self.output_key or not data[self.output_key]
            ), "You should put the whole trajactory into data[input_key] and do not set output_key"
            input_key = self.input_key
            apply_chat_template = self.apply_chat_template

            response_ranges = []
            for idx, message in enumerate(data[input_key]):
                if message["role"] == "assistant":
                    prompt = apply_chat_template(data[input_key][:idx], tools = tools, tokenize=False, add_generation_prompt=True)
                    response = apply_chat_template(data[input_key][: idx + 1], tools = tools, tokenize=False)[len(prompt) :]

                    start_idx = (
                        self.tokenizer(
                            prompt,
                            max_length=self.max_length,
                            padding=False,
                            truncation=True,
                            return_tensors="pt",
                            add_special_tokens=False,
                        )["attention_mask"]
                        .int()
                        .sum()
                        .item()
                    )

                    end_idx = (
                        start_idx
                        + self.tokenizer(
                            response,
                            max_length=self.max_length,
                            padding=False,
                            truncation=True,
                            return_tensors="pt",
                            add_special_tokens=False,
                        )["attention_mask"]
                        .int()
                        .sum()
                        .item()
                        - 1
                    )
                    response_ranges.append((start_idx, end_idx))  # left close right close
        
        prompt, response = preprocess_data(
            data,
            None if self.pretrain_mode else self.input_template,
            self.input_key,
            self.output_key,
            apply_chat_template=None if self.pretrain_mode else self.apply_chat_template,
            multiturn=self.multiturn,
        ) #这里的response是最后一个turn

        if not self.pretrain_mode:
            prompt_token = self.tokenizer(
                prompt,
                max_length=self.max_length,
                padding=False,
                truncation=True,
                return_tensors="pt",
                add_special_tokens=False,
            )
            prompt_ids_len = prompt_token["attention_mask"].int().sum().item()

            if not prompt or not response or prompt_ids_len >= self.max_length - 2:
                prompt = None
        else:
            prompt_ids_len = 0

        return {
            "prompt": prompt,
            "response": response,
            "prompt_ids_len": prompt_ids_len,
            "response_ranges": response_ranges if self.multiturn else None,
        }

    def __len__(self):
        length = len(self.prompts)
        return length

    def __getitem__(self, idx):
        prompt = self.prompts[idx]
        response = self.responses[idx]

        if not self.pretrain_mode:
            text = (prompt + response).rstrip("\n")
            if not text.endswith(self.tokenizer.eos_token):
                text += " " + self.tokenizer.eos_token
            # print(text)
            # exit()
        else:
            text = prompt

        input_token = self.tokenizer(
            text,
            max_length=self.max_length,
            padding=False,
            truncation=True,
            return_tensors="pt",
            add_special_tokens=False,
        )
        input_ids = input_token["input_ids"]
        attention_mask = input_token["attention_mask"]
        loss_mask = self.get_loss_mask(input_ids, idx)

        if not self.pretrain_mode:
            # to avoid EOS_token truncation
            input_ids[0][-1] = self.tokenizer.eos_token_id
            attention_mask[0][-1] = True
        return input_ids, attention_mask, loss_mask

    def get_loss_mask(self, input_ids, idx):
        if self.pretrain_mode:
            return torch.ones_like(input_ids, dtype=torch.float32)  # shape:[1, seq_len]

        loss_mask = torch.zeros_like(input_ids, dtype=torch.float32)
        if not self.multiturn:
            prompt_ids_len = self.prompt_ids_lens[idx]
            loss_mask[0, prompt_ids_len - 1 : -1] = 1
        else:
            response_ranges = self.response_ranges[idx]
            for start_idx, end_idx in response_ranges:
                loss_mask[0, start_idx - 1 : end_idx] = 1
        return loss_mask

    # def collate_fn(self, item_list):
    #     input_ids = []
    #     attention_masks = []
    #     loss_masks = []

    #     for input_id, attention_mask, loss_mask in item_list:
    #         input_ids.append(input_id)
    #         attention_masks.append(attention_mask)
    #         loss_masks.append(loss_mask)

    #     input_ids = zero_pad_sequences(input_ids, "right", self.tokenizer.pad_token_id)
    #     attention_masks = zero_pad_sequences(attention_masks, "right")
    #     loss_masks = zero_pad_sequences(loss_masks, "right")
    #     return input_ids, attention_masks, loss_masks

if __name__ == "__main__":
    import json
    import os
    from datasets import load_dataset
    def blending_datasets(
        dataset,
        probabilities=None,
        strategy=None,
        seed=42,
        max_count=1e8,
        stopping_strategy="all_exhausted",
        dataset_split="train",
    ):

        data_dir = dataset.split("@")[1].strip() if "@" in dataset else None
        dataset = dataset.split("@")[0].strip()
        dataset_basename = os.path.basename(dataset)

        ext = os.path.splitext(dataset)[-1]
        # local python script
        
        if ext in [".json", ".jsonl", ".csv", ".parquet", ".arrow"]:
            ext = ext.lower().strip(".")
            if ext == "jsonl":
                ext = "json"
            data = load_dataset(ext, data_files=dataset)
            if dataset_split and dataset_split in data:
                data = data[dataset_split]
            dataset = data
            # strategy.print(f"loaded {dataset} with data_files={dataset}")            
        else:
            kill

        return dataset

    def postprocess_sft_data(jsonl_f):
        messages_all = []
        with open(jsonl_f,"r") as f:
            for line in f:
                data=json.loads(line)
                messages_all.append(data["messages"])

        return messages_all

    print("====开始测试！！====")
    from transformers import AutoTokenizer
    from datasets import Dataset
    
    test_dataloader=True
    test_loss_mask = False

    # test_dataloader=False
    # test_loss_mask = True

    if test_dataloader:

        data_file = "../datasets/openclaw_training_demo.jsonl"

        train_data = blending_datasets(data_file)
        print(train_data)
        tokenizer_path ="/volume/posttrain/users/lyang/models/Qwen3-4B-Instruct-2507"
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        class Args:
            input_key = "messages"
            output_key = None
        class Strategy:
            args = Args()
        train_dataset = SFTDataset(
            train_data,
            tokenizer,
            131072, #args.max_len,
            strategy=Strategy(),
            multiturn=True,  # 测试多轮功能
            pretrain_mode=False,
            tokenizer_path = tokenizer_path,
            data_file =data_file
        )