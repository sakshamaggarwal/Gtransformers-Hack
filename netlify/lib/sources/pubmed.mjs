// PubMed (NCBI E-utilities): peer-reviewed papers. Free; 3 req/s without a key,
// 10 req/s with NCBI_API_KEY. Docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
//   esearch  -> PMIDs for a query, filtered to stronger study types
//   esummary -> title, journal, year, publication types
import { getJSON, qs, clip } from "./http.mjs";

const BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils";
const STRONG = '(randomized controlled trial[pt] OR meta-analysis[pt] OR systematic review[pt] OR review[pt] OR clinical trial[pt])';

export async function searchPubMed(term, { max = 3, apiKey } = {}) {
  const key = apiKey ? { api_key: apiKey } : {};
  const search = await getJSON(`${BASE}/esearch.fcgi?${qs({ db: "pubmed", term: `(${term}) AND ${STRONG} AND humans[mh]`, retmode: "json", retmax: max, sort: "relevance", ...key })}`);
  const ids = search?.esearchresult?.idlist ?? [];
  if (!ids.length) return [];
  const sum = await getJSON(`${BASE}/esummary.fcgi?${qs({ db: "pubmed", id: ids.join(","), retmode: "json", ...key })}`);
  return ids.map((id) => sum?.result?.[id]).filter(Boolean).map((r) => ({
    kind: "pubmed",
    title: clip(r.title ?? "", 220),
    text: `${r.fulljournalname || r.source || "Journal"} (${String(r.pubdate ?? "").slice(0, 4)}). Type: ${(r.pubtype ?? []).join(", ") || "article"}.`,
    year: String(r.pubdate ?? "").slice(0, 4),
    journal: r.source ?? "",
    pubtypes: r.pubtype ?? [],
    url: `https://pubmed.ncbi.nlm.nih.gov/${r.uid}/`,
    source: "PubMed",
  }));
}
