// PubMed (NCBI E-utilities): peer-reviewed papers. Free; 3 req/s without a key,
// 10 req/s with NCBI_API_KEY. Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
//   esearch -> PMIDs for the query (stronger study types first, then any human study)
//   efetch  -> title, ABSTRACT, journal, year, publication types (XML)
// The abstract matters: the ranker scores relevance against title + abstract.
import { getJSON, getText, qs, clip, stripHtml } from "./http.mjs";

const BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";
const STRONG = "(randomized controlled trial[pt] OR meta-analysis[pt] OR systematic review[pt] OR review[pt] OR clinical trial[pt])";

const tag = (xml, name) => xml.match(new RegExp(`<${name}\\b[^>]*>([\\s\\S]*?)</${name}>`))?.[1] ?? "";
const tags = (xml, name) => [...xml.matchAll(new RegExp(`<${name}\\b[^>]*>([\\s\\S]*?)</${name}>`, "g"))].map((m) => m[1]);
const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

// Parse an efetch XML response into plain records. Exported for tests.
export function parsePubMedXML(xml) {
  return String(xml).split(/<PubmedArticle>/).slice(1).map((a) => {
    const pmid = tag(a, "PMID").trim();
    const pubDate = tag(a, "PubDate");
    const year = tag(pubDate, "Year") || (tag(pubDate, "MedlineDate").match(/\d{4}/)?.[0] ?? "");
    const mon = (MONTHS[String(tag(pubDate, "Month")).slice(0, 3).toLowerCase()] ?? Number(tag(pubDate, "Month"))) || 1;
    const abstract = tags(a, "AbstractText").map(stripHtml).join(" ");
    return {
      pmid,
      title: stripHtml(tag(a, "ArticleTitle")),
      abstract,
      journal: stripHtml(tag(tag(a, "Journal"), "Title")),
      year,
      date: year ? `${year}-${String(mon).padStart(2, "0")}-01` : "",
      pubtypes: tags(a, "PublicationType").map(stripHtml),
      authors: tags(a, "Author").slice(0, 3).map((x) => [tag(x, "LastName"), tag(x, "Initials")].filter(Boolean).join(" ")).filter(Boolean),
    };
  }).filter((r) => r.pmid && r.title);
}

async function esearch(term, max, key) {
  const d = await getJSON(`${BASE}/esearch.fcgi?${qs({ db: "pubmed", term, retmode: "json", retmax: max, sort: "relevance", ...key })}`);
  return d?.esearchresult?.idlist ?? [];
}

export async function searchPubMed(term, { max = 8, apiKey } = {}) {
  const key = apiKey ? { api_key: apiKey } : {};
  // Prefer trials / reviews / meta-analyses in humans; top up with any human study if that is thin.
  let ids = await esearch(`(${term}) AND ${STRONG} AND humans[mh]`, max, key);
  if (ids.length < 3) ids = [...new Set([...ids, ...(await esearch(`(${term}) AND humans[mh]`, max, key))])].slice(0, max);
  if (!ids.length) return [];
  const xml = await getText(`${BASE}/efetch.fcgi?${qs({ db: "pubmed", id: ids.join(","), retmode: "xml", rettype: "abstract", ...key })}`);
  return parsePubMedXML(xml)
    .filter((r) => !r.pubtypes.some((t) => /retract/i.test(t))) // never surface retracted papers
    .map((r) => ({
      kind: "pubmed",
      title: clip(r.title, 220),
      text: clip(r.abstract || `${r.journal}. ${r.pubtypes.join(", ")}.`, 900),
      year: r.year,
      date: r.date,
      journal: r.journal,
      author: r.authors.join(", ") + (r.authors.length >= 3 ? " et al." : ""),
      pubtypes: r.pubtypes,
      url: `https://pubmed.ncbi.nlm.nih.gov/${r.pmid}/`,
      source: "PubMed",
    }));
}
