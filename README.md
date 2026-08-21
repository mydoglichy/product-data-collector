# Product Data Collector

## Coupang Partners Product Search

`coupang_API` collects Coupang Partners keyword product-search results once and exits. Schedule repeated runs externally, for example with Linux cron.

### Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill `.env` with:

```text
COUPANG_ACCESS_KEY=...
COUPANG_SECRET_KEY=...
```

Do not commit `.env`.

### Configure Keywords

Edit `coupang_API/keywords.txt`. Add one keyword per line. Blank lines and lines starting with `#` are ignored, and duplicate keywords are requested only once.

```text
# One keyword per line
선글라스 케이스
휴대용 안경집
가죽 안경 파우치
```

Edit `coupang_API/config.yaml` for request settings and rate limits.

```yaml
requests_per_minute: 40

request:
  limit: 10
  image_size: 512x512
  srp_link_only: false
```

### Run

From the project root:

```powershell
python -m coupang_API
```

Raw API responses are saved under `coupang_API/data/raw/`.
Processed JSONL records are saved under `coupang_API/data/processed/`.

Each run writes timestamped files and does not overwrite previous collection history.
If a run stops before all keywords finish, `coupang_API/data/checkpoints/product_search_checkpoint.json` lets the next run resume from unfinished keywords.

### Cron

Run every day at 6 AM and 6 PM:

```cron
0 6,18 * * * cd /배포경로/product-data-collector && /가상환경경로/python -m coupang_API
```

### Tests

```powershell
pytest
```
