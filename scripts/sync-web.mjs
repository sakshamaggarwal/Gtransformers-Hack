// Copies the Vaidya Pulse page (web/index.html, the source of truth) to:
//   public/index.html  served by Netlify and `npm start`
//   web/app.html       same page without the <html> wrapper, for the claude.ai artifact
// Run after editing web/index.html:  npm run sync:web
import { readFileSync, writeFileSync } from "node:fs";
const src = readFileSync("web/index.html", "utf8");
writeFileSync("public/index.html", src);
const body = src.replace(/^[\s\S]*?<body>\n?/, "").replace(/\n?<\/body>\s*<\/html>\s*$/, "\n");
writeFileSync("web/app.html", body);
console.log("synced public/index.html and web/app.html from web/index.html");
