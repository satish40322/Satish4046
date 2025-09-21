# Telegram Crypto Signal Copier Bot

This bot copies crypto trading signals from one Telegram channel and forwards them to another, converting them into Cornix-style format.

## 🚀 Features
- Detects `Entry Price` from text or caption.
- If no entry given → fetches **current market price** from Binance.
- Converts:
  - `500%` → Entry × 1.1
  - `1000%` → Entry × 2.2
- Removes duplicate TP values.
- Deployable on **Render** as a Web Service (24/7).

---

## 📦 Setup

### 1. Clone repo and push to GitHub

```bash
git clone <your-repo>
cd <your-repo>