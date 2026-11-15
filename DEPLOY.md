# Deploying and switching versions on Netlify

Two Netlify sites, both from this repo. Each one auto-deploys the latest commit on its branch.

| Site | Branch | Base directory | Build command | Publish directory | Environment variables |
|---|---|---|---|---|---|
| **Combined** (Vaidya Pulse + CollectiveMind) | `demo` | *(empty)* | *(empty)* | `public` | `GROQ_API_KEY` (optional: `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`) |
| **CollectiveMind only** | `community-analysis` | `community-analysis` | *(empty)* | `community-analysis` | none (static page) |

Functions for the combined site come from `netlify.toml` at the repo root (`netlify/functions`).

## 1. Create each site (once)

1. Netlify → **Add new site → Import an existing project → GitHub** → `Gtransformers-Hack`.
2. Fill in the branch and directories from the table above.
3. Add the environment variables (combined site only) → **Deploy**.
4. **Site configuration → Change site name** (e.g. `vaidya-pulse`, `collectivemind`).

## 2. Ship the latest version

Every push to the site's branch redeploys it automatically. The URL stays the same.

```bash
git checkout demo            # or: community-analysis
git pull
# ...make changes...
git add -A && git commit -m "describe the change"
git push
```

If a deploy doesn't start: **Deploys → Trigger deploy → Clear cache and deploy site**.

## 3. Switch which branch a site serves

**Site configuration → Build & deploy → Continuous deployment → Branches and deploy contexts → Configure → Production branch** → choose the branch → Save → **Deploys → Trigger deploy**.

- Combined site: `main` = Vaidya Pulse only, `demo` = Vaidya Pulse + CollectiveMind.
- CollectiveMind site: `community-analysis`.

## 4. Preview other branches without switching

In the same settings panel set **Branch deploys** to "Let me add individual branches" and add the branches you want. Each gets its own URL:

```
https://<branch>--<site-name>.netlify.app
```

## 5. Roll back

**Deploys** → open an earlier deploy → **Publish deploy**. It goes live instantly; the next push goes back to auto-publishing.

## 6. Submission checklist

- Live URLs: combined site and CollectiveMind site (open both in a private window to confirm they load).
- Repo: https://github.com/sakshamaggarwal/Gtransformers-Hack
- Commit for each branch: `git rev-parse --short HEAD` (after `git checkout <branch> && git pull`).
- Check `/api/evidence` on the combined site shows the model status if you set `GROQ_API_KEY`.
