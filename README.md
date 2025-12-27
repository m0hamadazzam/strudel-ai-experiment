⚠️ DISCLAIMER

This is a **personal educational project** built as part of a **Masterschool Software & AI Engineering graduation project**.

This project is **based on Strudel** (https://strudel.cc), an open-source live-coding music environment originally developed by uzu and contributors.

This repository is **not affiliated with, endorsed by, or intended as an official extension of Strudel**.  
It exists solely for **learning, experimentation, and research purposes**.

---

# Strudel AI Experiment

An **experimental AI copilot sidebar** for browser-based live coding, exploring how Large Language Models (LLMs) can assist creative coding workflows.

This project investigates how a chat-based AI interface can help with:
- generating Strudel patterns
- modifying existing code
- iterating on musical ideas
- understanding and refactoring live-coding patterns

The AI functionality is intentionally kept **separate from the original Strudel project** and is **not proposed for upstream inclusion**.

---

## Project Goals

The goal of this project is to explore:

- AI-assisted creative coding
- Human–AI collaboration in music tools
- Safe, controlled integration of LLMs into real-time systems
- Practical software engineering trade-offs between frontend integration and backend AI services

This work is **educational**, not commercial.

---

## Architecture Overview

The project follows a clean separation of concerns:

### Frontend (Strudel Fork – TypeScript)
- Fork of Strudel for **local experimentation only**
- Adds a **right-hand sidebar** with a chat interface
- Reads and updates the Strudel code editor
- Does **not** modify Strudel’s core musical engine

### Backend (Python – FastAPI)
- Hosts the AI “copilot” logic
- Handles:
  - prompt orchestration
  - LLM calls
  - strict output validation (Strudel code only)
  - undo-safe responses
- Can be reused independently of Strudel

This architecture ensures the AI layer is **decoupled**, reversible, and non-intrusive.

---

## What This Project Is NOT

To avoid any confusion, this project is **not**:

- an official Strudel feature
- a proposal for adding AI to Strudel upstream
- a replacement for Strudel
- a commercial product
- a maintained fork intended for general users

It is a **personal learning experiment**.

---

## About the Original Strudel Project

**Strudel** is a browser-based live coding environment inspired by TidalCycles, allowing musicians to create and manipulate musical patterns using code.

- Website: https://strudel.cc
- Try it online: https://strudel.cc
- Documentation: https://strudel.cc/learn
- Technical manual: https://strudel.cc/technical-manual/project-start
- Blog:
  - https://loophole-letters.vercel.app/strudel
  - https://loophole-letters.vercel.app/strudel1year
  - https://strudel.cc/blog/#year-2

Strudel is licensed under the **GNU Affero General Public License v3 (AGPL-3.0)**.

---

## Running This Project Locally

> ⚠️ This setup is intended for **development and learning only**.

### Prerequisites
- Node.js **18+**
- pnpm

### Setup
```bash
pnpm install
pnpm dev
