---
name: CSA v3 Architecture
description: Key decisions and quirks for Computer Skills Academy v3.0 (Next.js 15 + NVIDIA NIM)
---

# CSA v3 Architecture

## Stack
- Next.js 15 App Router, TypeScript, Tailwind CSS v4
- NVIDIA NIM via OpenAI-compatible API at `https://integrate.api.nvidia.com/v1`
- Storage key: `csa_v4_learner` (localStorage, single LearnerState)

## Critical: `next` binary
The `next` binary can go missing from `node_modules/.bin/` after environment resets.
Fix: run `installLanguagePackages({ language: "nodejs", packages: ["next"] })` via code_execution, then restart workflow.

**Why:** Replit's NixOS container can reset node_modules without a full npm install; the binary disappears while other packages remain.

## Single-learner design
- Replaced dual StudentId/StudentState with single `LearnerState` in `types/index.ts`
- Hook: `hooks/useLearnerState.ts` (replaces old `hooks/useStudentState.ts` — old file still present but unused)
- `hydrated` flag prevents SSR/localStorage mismatch

## Models — two providers, two API keys required
`constants/models.ts` → `MODEL_ASSIGNMENTS` routes tasks to models; `MODEL_PROVIDER` maps each model to `"nvidia"` or `"mimo"`.
- Most models (Qwen 3.5, Nemotron Ultra/Super, GPT-OSS, MiniMax M3, Step 3.7) run through NVIDIA NIM → needs `NVIDIA_API_KEY`.
- `mimo-v2.5-free` runs through OpenCode Zen (`MIMO_BASE_URL`) → needs a **separate** `MIMO_API_KEY` secret. Missing it throws in `lib/ai-client.ts` and surfaces as 500s on whichever task is assigned to Mimo (quiz/summarize by default, lesson if reassigned).
**Why:** the two providers are wired through the same `getClient(provider)` abstraction but each needs its own key; it's easy to reassign `MODEL_ASSIGNMENTS.lesson` to Mimo without realizing the key is a separate secret from NVIDIA's.
**How to apply:** whenever `MODEL_ASSIGNMENTS` is changed to point a task at `MODELS.MIMO_V25`, confirm `MIMO_API_KEY` exists via `viewEnvVars` before assuming it'll work.

## AI client signature (lib/ai-client.ts)
Both `runCompletion` and `runStreamingCompletion` take a single options object:
`{ model, messages, temperature?, maxTokens?, jsonMode? }`
`runStreamingCompletion` returns a `ReadableStream` directly.

## SENTINEL pattern
Lesson stream splits on `<<<RESOURCES_JSON>>>` — everything before is markdown, everything after is JSON resources metadata.

## allowedDevOrigins
`next.config.ts` already has `allowedDevOrigins: ["*"]` for Replit preview iframe.

## duck-duck-scrape safeSearch option
`search()` from `duck-duck-scrape` requires `safeSearch` to be the numeric `SafeSearchType` enum (`SafeSearchType.MODERATE`), not a string like `"Moderate"` — passing a string throws `TypeError: Moderate is an invalid safe search type!` and silently breaks web search results injected into lessons/chat.

## Never let the lesson-generation LLM write its own "Resources" section
The lesson prompt used to ask the model to also write a prose "Recommended Resources" list with markdown links, duplicating the already-working structured resource cards (YouTube/article JSON) rendered by the UI. The AI's prose links sometimes rendered as raw unclickable text instead of parsed markdown.
**Why:** two independent sources of truth for the same data (model prose + structured JSON) will diverge and one of them is guaranteed to render worse than a purpose-built card component.
**How to apply:** if resources/links need to appear in AI output, either render them from structured data only (current approach) or have the AI reference already-rendered cards, never have it re-emit raw markdown links for data the UI already displays as cards.

## `app/page.tsx` is a single monolithic client component
All UI (MarkdownViewer, YouTubeCard, WebArticleCard, VideoSummaryModal, QuizPanel, main `Home()`) lives inline in `app/page.tsx`; the files under `components/` (e.g. `components/chat/ChatPanel.tsx`) are the only ones actually imported/used — `components/ui/*` duplicates are dead code from an earlier refactor.
**Why:** avoids editing the wrong (unused) file when features seem "already implemented" in `components/ui/`.
**How to apply:** always grep `app/page.tsx` first to see if a UI piece is defined inline before assuming a `components/` file is the live implementation.
