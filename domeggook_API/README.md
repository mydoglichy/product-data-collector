# Domeggook/Domeme Daily Collector

`domeggook_API` collects daily file-based history for Domeggook (`market=dome`) and Domeme (`market=supply`) products. The marketplaces do not provide historical price or stock data, so this collector discovers product numbers from keyword searches and then keeps collecting every discovered active product by product number even after it drops out of the top search results.

## Flow

1. Read `domeggook_API/keywords.txt`.
2. Search each keyword for both markets.
3. Search both popular products (`so=ha`) and recently registered or recently modified products (`so=da`).
4. Merge discovered product numbers into `tracked_products.json`.
5. Save search-rank history to `output/search-ranks-YYYY-MM-DD.json`.
6. Read every `active=true` product from `tracked_products.json`.
7. Call the product detail API in batches of up to 100 product numbers.
8. Save daily snapshots to `output/product-snapshots-YYYY-MM-DD.json`.

## API Roles

The product list API (`mode=getItemList`, `ver=4.1`) is used only for discovery and search-rank history. It finds product numbers from keyword, market, and sort combinations.

The product detail API (`mode=getItemView`, `ver=4.6`, `multiple=true`) is used for daily time-series snapshots. One detail response can include both Domeggook and Domeme data for a product, so the collector does not call separate detail APIs for each market.

## Environment

Use the project-root `.env`; do not create a separate `.env` inside this folder.

```text
DOMEGGOOK_API_KEY=...
```

`.env` is ignored by Git. `.env.example` contains only placeholder variable names.

## Keywords

Edit `domeggook_API/keywords.txt` with one keyword per line.

```text
# comments and blank lines are ignored
안경 케이스
선글라스 케이스
```

Duplicate keywords are requested only once.

## Run

From the project root:

```powershell
python -m domeggook_API.main
```

Individual steps:

```powershell
python -m domeggook_API.discover_products
python -m domeggook_API.collect_product_details
```

For a small real API check when a key is configured:

```powershell
python -m domeggook_API.main --limit 1 --dry-run
```

`--limit` limits keywords during discovery and active product IDs during detail collection. `--dry-run` calls the API but skips writes to tracked/output files.

## Output

`tracked_products.json` is a product master file keyed by product number. Product numbers are stored as strings, not numbers.

```json
{
  "12345678": {
    "productId": "12345678",
    "keywords": ["안경 케이스"],
    "markets": ["dome", "supply"],
    "reasons": ["popular", "recent"],
    "firstSeenAt": "2026-08-22T09:00:00+09:00",
    "lastSeenAt": "2026-08-22T09:00:00+09:00",
    "active": true
  }
}
```

Daily snapshots are saved as:

```text
domeggook_API/output/product-snapshots-YYYY-MM-DD.json
```

The file contains `collectedAt`, `successCount`, `failureCount`, `products`, and `failures`. If the collector is run again on the same day, products are merged by `productId`; existing successful products are not discarded, and the latest product snapshot for that day replaces the older snapshot for the same product.

Search rank files are saved as:

```text
domeggook_API/output/search-ranks-YYYY-MM-DD.json
```

Each rank record includes collection time, keyword, market, sort code, discovery reason, product number, and rank within that search result.

## Reliability

Requests are rate-limited by `config.yaml`; the default is 120 requests per minute, below the official 180 per minute limit. HTTP 429 uses `Retry-After` first, then exponential backoff. Network errors and 5xx responses retry only up to `request.max_retries`.

Failures are logged to `domeggook_API/logs/collector.log` without API keys. `tracked_products.json` and output JSON files are written through temporary files and atomically replaced. A lock file under `domeggook_API/logs/collector.lock` prevents concurrent runs.

All timestamps are ISO-8601 in the configured timezone, default `Asia/Seoul`.

## Configuration

```yaml
discovery:
  markets:
    - dome
    - supply
  sorts:
    popular: ha
    recent: da
  items_per_keyword: 20

details:
  batch_size: 100

request:
  max_requests_per_minute: 120
  timeout_seconds: 20
  max_retries: 3

timezone: Asia/Seoul
```

The collector validates official maximums before running: product list size must be 100 or less, detail batch size must be 100 or less, and request rate must stay below 180 per minute.

## Tests

```powershell
pytest domeggook_API/tests
```

Tests use fixtures and mock clients; they do not call the real API.

## Cron

Run once daily at 06:10 Korea time on Linux:

```cron
10 6 * * * cd /path/to/product-data-collector && /path/to/python -m domeggook_API.main >> domeggook_API/logs/cron.log 2>&1
```

## Future Database Migration

The current implementation is file-based. `tracked_products.json` is intentionally separated from daily snapshot storage so it can later move to a `tracked_products` table, while daily JSON snapshot records can move to a `product_snapshots` table.

