// The link from the Demo guide to the SPARQL page of Virtuoso.
// The /sparql page of Virtuoso has two query parameters:
//   qtxt   opens the page with the query in the editor (it does not run the query),
//   query  opens the page and runs the query.
// The base URL comes from GET /api/health (sparqlUrl), so the frontend has no fixed port.
// This file is plain JavaScript, so that scripts/check-demo.mjs can run the same function.

/** The URL of the SPARQL page with the query. `run` true uses the parameter that runs the query. */
export function sparqlPageUrl(sparqlUrl, queryText, run = false) {
  const url = new URL(sparqlUrl);
  url.searchParams.set(run ? 'query' : 'qtxt', queryText);
  return url.toString();
}
