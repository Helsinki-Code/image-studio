# Image Studio

Local image generation/editing web app.

- Primary provider: OpenAI `gpt-image-2`
- Optional fallback provider: FAL `openai/gpt-image-2` / `openai/gpt-image-2/edit` if `FAL_KEY` is configured
- Prompt refinement is for clarity and preservation, not moderation bypass.
- OpenAI generation uses `moderation: low`, the least restrictive supported value. Hosted provider moderation cannot be disabled.

## Run

```bash
cd /Users/vikky/image-studio
/Users/vikky/.hermes/hermes-agent/venv/bin/python -m uvicorn app.main:app --reload --port 8765
```

Open: http://127.0.0.1:8765

## Env

The app loads keys from `~/.hermes/.env`:

```env
OPENAI_API_KEY=...
FAL_KEY=... # optional fallback
```

## Deploy to Vercel through GitHub

This repo is prepared for Vercel with:

- `api/index.py` as the Vercel serverless ASGI entrypoint
- `vercel.json` routing every request to the FastAPI app
- `requirements.txt` for Python dependencies
- `/tmp` upload/output handling for serverless runtime

### 1. Push to GitHub

```bash
cd /Users/vikky/image-studio
git init
git add .
git commit -m "Initial Image Studio app"
gh repo create image-studio --private --source . --push
```

If you do not have GitHub CLI, create an empty repo at https://github.com/new, then run the commands GitHub shows for “push an existing repository”.

### 2. Import into Vercel

1. Go to https://vercel.com/new
2. Choose your `image-studio` GitHub repo
3. Framework preset: **Other**
4. Vercel should detect Python from `requirements.txt`
5. Add these environment variables in Vercel Project Settings → Environment Variables:
   - `OPENAI_API_KEY`
   - `FAL_KEY`
6. Deploy

### 3. Local Vercel CLI option

```bash
cd /Users/vikky/image-studio
npx vercel login
npx vercel --prod
```

## Tests

```bash
cd /Users/vikky/image-studio
/Users/vikky/.hermes/hermes-agent/venv/bin/python -m pytest tests -q
```
