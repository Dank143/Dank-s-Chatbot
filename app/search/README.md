# Web Search Pipeline

The chatbot uses a hosted search-and-extraction cascade:

```text
Exa → Tavily → Firecrawl
```

Providers are called sequentially so a successful early response does not spend credits on later providers. Each search returns at most five pages, and the complete retrieval operation has a shared 15-second deadline. If the deadline is nearly exhausted, the pipeline returns the best usable content already collected.

SearXNG, DuckDuckGo, Jina Reader, and Trafilatura are not part of the active pipeline.

## Module layout

| File | Responsibility |
|------|----------------|
| `pipeline.py` | Cache/coalescing, query rewrite, provider cascade, reranking, repair, quality gates, and context assembly |
| `engines.py` | HTTP integrations and circuit breakers for Exa, Tavily, and Firecrawl |
| `fetcher.py` | URL filtering, page-body validation, and text truncation |
| `domain_trust.py` | URL/content quality checks, trust scoring, and runtime domain blocking |
| `llm_processing.py` | LLM query rewriting, intent classification, and semantic reranking |
| `embedder.py` | Local ONNX embeddings through `fastembed` |
| `cache.py` | Positive/negative result caching and cached configuration reads |

The public entry point is:

```python
await fetch_web_context(query, num_urls=5, history_context="", chat_id="")
```

It returns `(context, debug)`. `inject_web_context()` adds the context and citation instructions to the model messages.

## End-to-end flow

```text
query + recent history
   │
   ▼
[1] Result cache / in-flight request coalescing
   │ miss
   ▼
[2] Regex intent fast path or bounded LLM query rewrite
   │
   ▼
[3] Exa search + text (up to five results)
   │ inadequate
   ▼
[4] Tavily basic search + raw Markdown (up to five results)
   │ inadequate
   ▼
[5] Firecrawl final stage
   ├─ known incomplete URLs → targeted Scrape repair
   └─ no candidates at all → Search + Markdown
   │
   ▼
[6] URL filtering, local semantic reranking, quality/relevance gates,
    snippet backfill, truncation, and assembly
```

### 1. Cache and coalescing

Completed results are cached for five minutes. Empty and timed-out results use a short 30-second TTL. Concurrent identical requests share one in-flight task, preventing duplicate provider calls and duplicate credit usage.

### 2. Query rewrite and routing

Obvious intents use regular-expression fast paths. Other queries can be rewritten by the configured auxiliary models to resolve references from recent conversation history and classify documentation, dictionary, wiki, or general intent. The resulting provider query can include a site restriction or freshness year where appropriate.

All rewrite, provider, rerank, and repair work shares the same end-to-end deadline; no stage receives a fresh 15-second window.

### 3. Exa

Exa is the primary provider. It uses fast search and requests one text body for each result:

- At most five results
- Up to 8,000 characters requested per result
- Search and content returned in one API response
- No automatic retry that could spend another search credit

The pipeline continues to Tavily only when Exa does not provide enough usable material.

### 4. Tavily

Tavily is the secondary provider. It uses:

- `search_depth: basic`
- `include_raw_content: markdown`
- At most five results
- No generated answer or images

Tavily is not raced with Exa. It is called only after the Exa result is inadequate.

### 5. Firecrawl

Firecrawl has two bounded roles:

1. **Search fallback:** if Exa and Tavily return no candidates, Firecrawl Search requests up to five results with main-content Markdown.
2. **Targeted repair:** Firecrawl Scrape fills missing or invalid bodies for URLs already selected by the pipeline, only while deadline and repair capacity remain.

Usable content from an earlier provider is retained if a later call fails or times out. This makes Firecrawl a reserve rather than an automatic five-page scrape on every query.

## Validation and ranking

A provider body is considered usable only when it contains at least 250 characters and does not resemble a common access-denied or JavaScript challenge page. Results also pass through:

- Social/login-heavy host filtering
- Runtime domain blocking for repeated failures
- URL spam and content-quality heuristics
- Local semantic reranking with domain-trust multipliers
- Relevance gates based on the rewritten query and detected entity

If semantic embeddings are unavailable or exceed their time budget, the pipeline falls back to heuristic ordering. Snippets can backfill a source when full extraction is unavailable.

Each page body is capped at 20,000 characters, and the assembled context is bounded before it is injected into the model prompt.

## Reliability behavior

- **Global deadline:** the complete retrieval run is capped at 15 seconds.
- **Sequential providers:** later providers are skipped once enough content is available.
- **Best-effort return:** partial usable content survives later failures and timeouts.
- **Circuit breakers:** repeated provider transport/server failures temporarily skip that provider.
- **Negative caching:** short-lived empty results absorb bursts without hiding provider recovery for long.
- **Connection reuse:** all hosted integrations share an asynchronous HTTP connection pool.
- **No local scraper service:** the active path needs neither Docker nor a browser runtime.

## Configuration

`defaults.max_search_urls` in `config.yaml` controls the requested source count, with the hosted provider calls capped at five. The provider credentials are read from the project-root `.env` file:

```dotenv
EXA_API_KEY="your_api_key_here"
TAVILY_API_KEY="your_api_key_here"
FIRECRAWL_API_KEY="your_api_key_here"
```

All three keys are needed for the complete fallback chain. A provider with no configured key is skipped, so the application can still run with a partial chain.

On first boot, `fastembed` downloads the configured ONNX embedding model. The model can be changed through `embed_model_fastembed` in `config.yaml`; restart the application after changing it.
