# Deploying CollectiveMind on Netlify

The site is static: `public/index.html` (the page, data inlined) and `public/knowledge.db` (download). No build step, no API keys.

## Create the site (once)

1. Netlify → **Add new site → Import an existing project → GitHub** → `Gtransformers-Hack`.
2. Branch `demo`, base directory *(empty)*, build command *(empty)*, publish directory `public`.
3. **Deploy**, then **Site configuration → Change site name**.

## Ship the latest version

Every push to `demo` redeploys automatically; the URL stays the same.

```bash
git checkout demo && git pull
# ...make changes...
git add -A && git commit -m "describe the change" && git push
```

If a deploy doesn't start: **Deploys → Trigger deploy → Clear cache and deploy site**.

## Rebuild the page from new comments

```bash
cd comment-knowledge-generator
# run the pipeline (see its README), then publish into the site folder:
python pipeline/publish_cards.py ... --site ../public/index.html
```

## Switch branches or roll back

- **Switch:** Site configuration → Build & deploy → Continuous deployment → Branches and deploy contexts → Configure → **Production branch** → Save → Trigger deploy.
- **Preview another branch:** add it under Branch deploys; it gets `https://<branch>--<site-name>.netlify.app`.
- **Roll back:** Deploys → open an earlier deploy → **Publish deploy**.
