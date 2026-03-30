"""
LlamaParse v2 - ML 學術論文解析品質 PoC
使用 llama-cloud>=1.0 (v2 API)

測試七個面向：element 分佈、標題保留、公式處理、table 完整性、figure 品質、cache 行為、圖片提取（presigned URL）

使用方式：
  cp .env.local.example .env.local   # 填入 llx-... API key
  python main.py
"""

import asyncio
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import httpx
from dotenv import load_dotenv
from llama_cloud import AsyncLlamaCloud

# ─── 頂部可調整參數 ────────────────────────────────────────────────────────────
_ENV_FILE = Path(__file__).parent / ".env.local"
load_dotenv(_ENV_FILE, override=True)

LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY", "")

# tier 有效值：
#   "agentic_plus"    → 最高品質，支援多模態（需付費訂閱，Free account 會卡住 queue）
#   "agentic"         → 一般智能解析
#   "cost_effective"  → 便宜快速，適合純文字，無 figure 辨識
PARSE_TIER = "cost_effective"

PAPERS_DIR = Path(__file__).parent.parent.parent / "docs" / "paper"
TEST_PAPERS = ["attention.pdf", "lora.pdf", "flashattention.pdf"]

SAVE_RAW_JSON = True
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

VALID_EXCLUDE = {"test1-5", "test6", "test7"}


# ─── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    paper_name: str
    items: list[dict]
    full_md: str
    file_id: str
    pages: int
    elapsed: float


# ─── 工具函式 ──────────────────────────────────────────────────────────────────

def extract_all_items(result) -> list[dict]:
    """從 v2 result 取出所有 items（結構化佈局）"""
    items = []
    # v2 格式: result.items.pages[i].items[j]
    if not hasattr(result, "items") or not getattr(result.items, "pages", None):
        return items

    for page in result.items.pages:
        page_num = getattr(page, "page_number", None) or getattr(page, "page", None)
        page_items = getattr(page, "items", []) or []
        for item in page_items:
            d: dict[str, Any] = {}
            if hasattr(item, "__dict__"):
                d = item.__dict__.copy()
            elif isinstance(item, dict):
                d = item.copy()
            # 將 type enum 轉成字串
            if "type" in d and hasattr(d["type"], "value"):
                d["type"] = d["type"].value
            d["_page_num"] = page_num
            items.append(d)
    return items


def get_item_type(item: dict) -> str:
    return str(item.get("type", item.get("item_type", "unknown"))).lower()


def get_item_text(item: dict) -> str:
    return str(item.get("md", item.get("text", item.get("value", ""))))


def save_json(name: str, data: Any):
    path = OUTPUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"  💾 Saved: {path}")


def result_to_dict(result) -> dict:
    """簡單將 v2 result 轉可序列化 JSON，除錯用"""
    try:
        return result.model_dump()      # Pydantic V2
    except AttributeError:
        return result.dict()            # fallback for older versions


# ─── Test Suite ───────────────────────────────────────────────────────────────

class PaperTestSuite:
    def __init__(self, pr: ParseResult):
        self._pr = pr

    def run_all(self) -> dict[str, str]:
        return {
            "Test1": self.test1(),
            "Test2": self.test2(),
            "Test3": self.test3(),
            "Test4": self.test4(),
            "Test5": self.test5(),
        }

    def test1(self) -> str:
        """Test 1: Element type 分佈"""
        paper_name = self._pr.paper_name
        items = self._pr.items
        print(f"\n=== Test 1: Element Type 分佈 [{paper_name}] ===")
        if not items:
            print("  ❌ FAIL: 無任何 items（可能 parse_mode/tier 沒給 items 或檔案空）")
            return "FAIL"

        counter = Counter(get_item_type(i) for i in items)
        print(f"  總 elements 數：{len(items)}")
        for typ, cnt in counter.most_common():
            print(f"    {typ:20s}: {cnt:4d}")

        non_text_types = {t for t in counter if t not in ("text", "unknown", "heading", "paragraph")}
        if non_text_types:
            print(f"  ✅ PASS：非 text 類別：{non_text_types}")
            return "PASS"
        elif counter.get("text", 0) + counter.get("paragraph", 0) + counter.get("heading", 0) == len(items):
            print("  ⚠️  WARNING：所有元素都是 text/paragraph/heading，沒有 table/figure/equation")
            return "WARNING"
        else:
            print("  ✅ PASS")
            return "PASS"

    def test2(self) -> str:
        """Test 2: Section 標題保留"""
        paper_name = self._pr.paper_name
        items = self._pr.items
        print(f"\n=== Test 2: Section 標題保留 [{paper_name}] ===")

        # 只從 items 取 heading 節點（full_md 同源，重複計算毫無意義）
        heading_items = [get_item_text(i) for i in items if "heading" in get_item_type(i)]
        print(f"  找到 heading 數：{len(heading_items)}")
        for h in heading_items[:20]:
            print(f"    {h}")

        # 擴展同義詞，涵蓋現代論文常見的非傳統節名
        key_sections = {
            "abstract":     ["abstract"],
            "introduction": ["introduction"],
            "method":       ["method", "approach", "methodology", "our method", "algorithm",
                             "model", "training", "framework", "problem statement", "ours"],
            "experiment":   ["experiment", "empirical", "evaluation", "benchmark", "setting",
                             "ablation", "analysis", "validation"],
            "result":       ["result", "finding", "performance", "comparison",
                             "accuracy", "bleu", "speedup"],
            "conclusion":   ["conclusion", "discussion", "related", "future", "summary",
                             "limitation"],
        }
        found_map = {k: False for k in key_sections}

        for h in heading_items:
            h_lower = h.lower()
            for key, synonyms in key_sections.items():
                if any(s in h_lower for s in synonyms):
                    found_map[key] = True

        print("\n  關鍵 Section Checklist：")
        for sec, found in found_map.items():
            status = "✅" if found else "❌"
            print(f"    {status} {sec.capitalize()}")

        found_count = sum(found_map.values())
        if found_count == 6:
            print("  ✅ PASS：所有關鍵 section 都找到！")
            return "PASS"
        if found_count >= 4:
            print(f"  ⚠️  WARNING：找到 {found_count}/6 個關鍵 section")
            return "WARNING"
        print(f"  ❌ FAIL：只找到 {found_count}/6 個關鍵 section（論文節名非傳統）")
        return "FAIL"

    def test3(self) -> str:
        """Test 3: 數學公式處理"""
        paper_name = self._pr.paper_name
        items = self._pr.items
        full_md = self._pr.full_md
        print(f"\n=== Test 3: 數學公式處理 [{paper_name}] ===")

        equation_items = [i for i in items if "equation" in get_item_type(i) or "formula" in get_item_type(i)]
        print(f"  equation type items 數：{len(equation_items)}")

        formula_snippets = []
        for item in equation_items:
            text = get_item_text(item)
            if text.strip():
                formula_snippets.append(("equation_item", text))

        inline = re.findall(r"\$[^$\n]{3,150}\$", full_md)
        for m in inline[:10]:
            formula_snippets.append(("inline_latex", m))

        display = re.findall(r"\$\$[\s\S]{3,500}?\$\$", full_md)
        for m in display[:5]:
            formula_snippets.append(("display_latex", m))

        latex_cmd = re.findall(r"\\(?:frac|sum|prod|int|alpha|beta|gamma|theta|sigma|omega|nabla|infty|mathbf|mathrm|text)\{[^}]{1,80}\}", full_md)
        for m in latex_cmd[:10]:
            formula_snippets.append(("latex_cmd", m))

        unicode_math = re.findall(r"[∇∑∏∫αβγδεζηθλμνξπρστφψω∂∞±×÷≤≥≠≈→←↑↓∈∉⊆⊇∪∩]{2,}", full_md)
        for m in unicode_math[:5]:
            formula_snippets.append(("unicode_math", m))

        print(f"  找到公式片段數：{len(formula_snippets)}")
        for kind, snippet in formula_snippets[:5]:
            print(f"\n  [{kind}] {snippet[:200].replace(chr(10), ' ')}")

        has_latex = any(k in ("inline_latex", "display_latex", "latex_cmd", "equation_item") for k, _ in formula_snippets)
        has_unicode = any(k == "unicode_math" for k, _ in formula_snippets)

        if has_latex:
            print(f"\n  → 公式保留為 LaTeX 格式 ✅")
            result = "PASS"
        elif has_unicode:
            print(f"\n  → 公式轉換為 Unicode 符號 ⚠️")
            result = "WARNING"
        elif len(formula_snippets) == 0:
            print(f"\n  → 未找到任何公式內容 ❌")
            result = "FAIL"
        else:
            print(f"\n  → 公式可能被截斷或丟失 ⚠️")
            result = "WARNING"

        print(f"  {result}")
        return result

    def test4(self) -> str:
        """Test 4: Table 數字完整性"""
        paper_name = self._pr.paper_name
        items = self._pr.items
        full_md = self._pr.full_md
        print(f"\n=== Test 4: Table 數字完整性 [{paper_name}] ===")

        table_items = [i for i in items if "table" in get_item_type(i)]
        print(f"  table type items 數：{len(table_items)}")

        md_tables = re.findall(r"(\|.+\|[\s\S]*?(?:\n\n|\Z))", full_md)
        print(f"  Markdown table 段落數：{len(md_tables)}")

        # 搜尋範圍：table items + markdown table block + 全文（數字可能在正文而非 table 節點）
        all_table_text = "\n".join(get_item_text(i) for i in table_items)
        all_table_text += "\n" + "\n".join(md_tables)
        all_table_text += "\n" + full_md  # fallback：在全文找

        search_targets: dict[str, list[tuple[str, str]]] = {
            "lora": [("WikiSQL", r"WikiSQL"), ("GPT-3", r"GPT.?3|175B"), ("Precision", r"\d+\.\d+")],
            # BLEU 28.4 (EN-DE) 和 41.8 (EN-FR) 是 Attention 論文的正確數字，41.0 是錯的
            "attention": [("BLEU 28.4", r"28\.4"), ("BLEU 41.8", r"41\.8"), ("EN-DE", r"EN.?DE|WMT")],
            "flashattention": [("TFlops", r"TFlops"), ("Speedup", r"\d+\.?\d*[×xX]|FlashAttention-?2")],
        }
        paper_key = paper_name.lower().replace(".pdf", "")
        targets = search_targets.get(paper_key, [("Numbers", r"\d+\.\d+")])

        found_any = False
        for label, pattern in targets:
            matches = re.findall(pattern, all_table_text, re.IGNORECASE)
            status = "✅" if matches else "❌"
            print(f"  {status} {label}：{'找到 ' + str(len(matches)) + ' 個' if matches else '未找到'}")
            if matches:
                found_any = True

        if not table_items and not md_tables:
            print("  ⚠️  WARNING：沒有找到任何 table")
            return "WARNING"
        if found_any:
            print("  ✅ PASS")
            return "PASS"
        print("  ❌ FAIL：目標數值未出現")
        return "FAIL"

    def test5(self) -> str:
        """Test 5: Figure 描述品質"""
        paper_name = self._pr.paper_name
        items = self._pr.items
        print(f"\n=== Test 5: Figure 描述品質 [{paper_name}] ===")

        figure_items = [i for i in items if any(t in get_item_type(i) for t in ["figure", "image", "chart"])]
        print(f"  figure type items 數：{len(figure_items)}")

        if not figure_items:
            print("  ⚠️  WARNING：沒有找到 figure/image 元素（可能被 tier 整併為文字）")
            return "WARNING"

        # 閾值從 50 降到 20：caption 可以很短，只有幾乎空白才算 missing
        THRESHOLD = 20
        warnings = 0
        for idx, item in enumerate(figure_items, 1):
            text = get_item_text(item)
            length = len(text)
            flag = "⚠️  SHORT" if length < THRESHOLD else "✅"
            print(f"  Figure {idx} [{flag}] 長度={length} chars")
            if length < THRESHOLD:
                warnings += 1

        print(f"\n  描述不足（<{THRESHOLD} chars）：{warnings}/{len(figure_items)}")

        if warnings == 0:
            print("  ✅ PASS")
            return "PASS"
        # 只有 ≥80% 不足才算 FAIL，少數短 caption 不影響整體
        if warnings / len(figure_items) < 0.8:
            print("  ⚠️  WARNING：少數 figure 描述較短，但整體尚可")
            return "WARNING"
        print("  ❌ FAIL：絕大多數 figure 描述不足或空白")
        return "FAIL"


# ─── 前置檢查 + 主流程 ────────────────────────────────────────────────────────

class QualityRunner:
    def __init__(self):
        self._client = AsyncLlamaCloud(api_key=LLAMA_CLOUD_API_KEY)
        self._semaphore = asyncio.Semaphore(2)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.close()

    async def _check_running_jobs(self) -> bool:
        """檢查是否有 RUNNING/PENDING jobs。有則顯示狀況並回傳 True（呼叫方應中止執行）。
        LlamaCloud 無 cancel API，stuck jobs 只能等 server 自動 timeout（約 30 分鐘）。
        """
        SERVER_TIMEOUT_MIN = 30  # 實測約 10~30 分鐘後 server 會自動 FAIL

        running_jobs: list = []
        pending_jobs: list = []

        running_page = await self._client.parsing.list(status="RUNNING")
        async for job in running_page:
            running_jobs.append(job)

        pending_page = await self._client.parsing.list(status="PENDING")
        async for job in pending_page:
            pending_jobs.append(job)

        all_jobs = running_jobs + pending_jobs
        if not all_jobs:
            print("✅ Job queue 乾淨，開始執行測試...")
            return False

        now = datetime.now(timezone.utc)
        print("\n⚠️  發現仍在執行的 parse jobs，停止測試避免 queue 擁塞：")
        print(f"   RUNNING: {len(running_jobs)} 個  PENDING: {len(pending_jobs)} 個\n")

        for job in all_jobs:
            created_at = getattr(job, "created_at", None)
            name = getattr(job, "name", job.id)
            status = getattr(job, "status", "?")
            jid = job.id[:28] + "..."
            if created_at:
                elapsed_min = (now - created_at).total_seconds() / 60
                remain_min = max(0.0, SERVER_TIMEOUT_MIN - elapsed_min)
                print(f"   [{status}] {name}  ({jid})")
                print(f"             已執行 {elapsed_min:.1f} 分鐘，預估最多再等 {remain_min:.0f} 分鐘後自動 FAIL")
            else:
                print(f"   [{status}] {name}  ({jid})")

        print(f"\n   ℹ️  LlamaCloud 無 cancel API，請等所有 jobs 消失後再重新執行。")
        print(f"   監控：再次執行 python main.py（queue 有 job 時會自動攔截並顯示）")
        return True

    async def _parse_paper(self, paper_name: str) -> ParseResult:
        """v2 API: create file -> parse"""
        pdf_path = PAPERS_DIR / paper_name
        print(f"\n📄 [START] {paper_name} ...")
        t0 = time.perf_counter()

        async with self._semaphore:
            # 這裡不指定 external_file_id 避免重複執行時報錯 duplicate key
            file_obj = await self._client.files.create(file=pdf_path, purpose="parse")
            result = await self._client.parsing.parse(
                tier=PARSE_TIER,
                file_id=file_obj.id,
                version="latest",
                expand=["markdown", "text", "items", "metadata"],
                disable_cache=False,
            )

        elapsed = time.perf_counter() - t0

        # 解析出所需的變數
        raw_md = getattr(result, "markdown", "")
        if hasattr(raw_md, "text"):
            full_md = getattr(raw_md, "text")
        elif hasattr(raw_md, "raw_text"):
            full_md = getattr(raw_md, "raw_text")
        else:
            full_md = str(raw_md)
        items = extract_all_items(result)
        pages_count = len(result.items.pages) if getattr(result, "items", None) and getattr(result.items, "pages", None) else 0

        print(f"   [DONE] {paper_name} 耗時 {elapsed:.2f}s，共 {pages_count} 頁 (items: {len(items)})")

        if SAVE_RAW_JSON:
            safe_name = paper_name.replace(".pdf", "")
            save_json(f"{safe_name}_raw", result_to_dict(result))

        return ParseResult(
            paper_name=paper_name,
            items=items,
            full_md=full_md,
            file_id=file_obj.id,
            pages=pages_count,
            elapsed=elapsed,
        )

    async def _test6_cache(self, file_id: str) -> str:
        """Test 6: Cache 行為
        - 第一次：複用主流程已上傳的 file_id parse
        - 第二次：同一個 file_id 重複 parse（測試 same-file_id cache）
        - 第三次：重新上傳（新 file_id）parse（測試 fresh upload 是否比 file_id 複用快/慢）
        """
        print(f"\n=== Test 6: Cache 行為 ===")
        # ★ 重用主流程已上傳的 file_id，不再重複上傳
        print(f"  複用主流程 file_id: {file_id}")

        async def parse_with_id(label: str, fid: str) -> float:
            t0 = time.perf_counter()
            async with self._semaphore:
                await self._client.parsing.parse(
                    tier=PARSE_TIER,
                    file_id=fid,
                    version="latest",
                    expand=["markdown", "text", "items"],
                    disable_cache=False,
                )
            elapsed = time.perf_counter() - t0
            print(f"  {label}耗時：{elapsed:.2f}s")
            return elapsed

        # 第一次（同一個 file_id）
        print("  第一次 parse（固定 file_id）...")
        try:
            elapsed1 = await asyncio.wait_for(parse_with_id("第一次", file_id), timeout=150)
        except Exception as e:
            print(f"  ❌ 第一次失敗：{e}")
            return "FAIL"

        # 第二次（複用同一個 file_id，測 cache hit）
        print("  第二次 parse（複用相同 file_id，測 cache）...")
        try:
            elapsed2 = await asyncio.wait_for(parse_with_id("第二次", file_id), timeout=150)
        except Exception as e:
            print(f"  ❌ 第二次失敗：{e}")
            return "FAIL"

        # 結論分析
        print(f"\n  📊 Cache 行為比較：")
        print(f"     第一次 (file_id 固定): {elapsed1:.2f}s")
        print(f"     第二次 (file_id 複用): {elapsed2:.2f}s  ← 若有 cache，應 < 5s")

        if elapsed2 < 5:
            print("  🚀 CACHE HIT confirmed（第二次 < 5s）")
            return "PASS"
        if elapsed2 < elapsed1 * 0.5:
            print(f"  ⚠️  WARNING：第二次有加速（{elapsed1/elapsed2:.1f}x），但 > 5s")
            return "WARNING"
        print("  ℹ️  無明顯 cache 效果（API 不支援同 file_id 的結果快取）")
        return "WARNING"

    async def _test7_images(self) -> str:
        """Test 7: LlamaParse v2 圖片提取驗證（presigned URL 下載）
        獨立 parse attention.pdf（只跑一篇），避免對主流程所有論文加圖片提取
        造成 parse 時間暴增（實測加 images_to_save 後每篇從 ~15s 變 ~220s）。
        正確用法：output_options.images_to_save=["embedded"] + expand images_content_metadata。
        """
        paper_name = "attention.pdf"
        print(f"\n=== Test 7: 圖片提取驗證（presigned URL）[{paper_name}] ===")

        pdf_path = PAPERS_DIR / paper_name
        try:
            async with self._semaphore:
                file_obj = await self._client.files.create(file=pdf_path, purpose="parse")
            print(f"  file_id: {file_obj.id}")
        except Exception as e:
            print(f"  ❌ FAIL：上傳失敗：{e}")
            return "FAIL"

        print(f"  解析中（tier={PARSE_TIER}, images_to_save=[embedded]）...")
        try:
            async with self._semaphore:
                result = await asyncio.wait_for(
                    self._client.parsing.parse(
                        tier=PARSE_TIER,
                        file_id=file_obj.id,
                        version="latest",
                        expand=["markdown", "images_content_metadata"],
                        output_options={"images_to_save": ["embedded"]},
                        disable_cache=False,
                    ),
                    timeout=300,
                )
        except asyncio.TimeoutError:
            print(f"  ❌ FAIL：解析逾時（300s）")
            return "FAIL"
        except Exception as e:
            print(f"  ❌ FAIL：解析失敗：{e}")
            return "FAIL"

        img_meta = getattr(result, "images_content_metadata", None)
        images = getattr(img_meta, "images", None) or [] if img_meta else []

        if not images:
            print("  ❌ FAIL：images_content_metadata.images 為空（tier 可能不支援 embedded image 提取）")
            return "FAIL"

        print(f"  找到圖片數：{len(images)}")
        for idx, img in enumerate(images, 1):
            filename = getattr(img, "filename", getattr(img, "name", f"image_{idx}"))
            size = getattr(img, "size_bytes", getattr(img, "size", "?"))
            content_type = getattr(img, "content_type", getattr(img, "mime_type", "?"))
            print(f"  [{idx}] {filename}  size={size}  type={content_type}")

        # 嘗試下載第一張
        first = images[0]
        url = (getattr(first, "url", None)
               or getattr(first, "presigned_url", None)
               or getattr(first, "download_url", None))
        filename = getattr(first, "filename", getattr(first, "name", "image_0"))

        if not url:
            print("  ⚠️  WARNING：找到 metadata 但無 presigned URL 欄位")
            return "WARNING"

        print(f"\n  📥 嘗試下載第一張圖片：{filename}")
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 0:
                out_path = OUTPUT_DIR / f"test7_{filename}"
                out_path.write_bytes(resp.content)
                print(f"  ✅ PASS：下載成功 {len(resp.content)} bytes → {out_path}")
                return "PASS"
            else:
                print(f"  ⚠️  WARNING：HTTP {resp.status_code}，content 長度 {len(resp.content)}")
                return "WARNING"
        except Exception as e:
            print(f"  ⚠️  WARNING：下載失敗：{e}")
            return "WARNING"

    def _print_summary(self, summary: dict):
        print("\n" + "=" * 60)
        print("📊 總結表格")
        print("=" * 60)

        test_labels = {
            "Test1": "Element Type 分佈",
            "Test2": "Section 標題保留",
            "Test3": "數學公式處理",
            "Test4": "Table 數字完整性",
            "Test5": "Figure 描述品質",
            "Test6": "Cache 行為",
            "Test7": "圖片提取（presigned）",
        }

        papers = list(summary.keys())
        col_w = 14
        header = f"{'Test':<25}" + "".join(f"{p[:col_w]:^{col_w}}" for p in papers)
        print(header)
        print("-" * (25 + col_w * len(papers)))

        status_icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "WARNING": "⚠️  WARN", "ERROR": "💥 ERR"}
        for test_key, label in test_labels.items():
            val_in_any = any(test_key in summary[p] for p in papers)
            if not val_in_any:
                continue  # 整個 group 被 exclude，不顯示該行
            row = f"{label:<25}"
            for paper in papers:
                val = summary.get(paper, {}).get(test_key, "SKIP")
                icon = status_icon.get(val, "⏭️  SKIP")
                row += f"{icon:^{col_w}}"
            print(row)

        print("=" * 60)
        print(f"\n💾 輸出目錄：{OUTPUT_DIR.resolve()}")

        if SAVE_RAW_JSON:
            summary_path = OUTPUT_DIR / "summary.json"
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            print(f"💾 Summary JSON：{summary_path}")

    async def run(self, exclude: set[str]):
        if await self._check_running_jobs():
            return

        skip_main = "test1-5" in exclude  # test1-5 需要主流程 parse 結果
        skip_t6   = "test6"   in exclude
        skip_t7   = "test7"   in exclude

        # ── 主流程 parse（test1-5 或 test6 需要時才跑）────────────────────────────
        summary: dict[str, dict[str, str]] = {}
        attention_file_id: str = ""

        need_main_parse = not skip_main or not skip_t6  # test6 需要 file_id
        if need_main_parse:
            print("\n⏳ 並行 parse 三篇論文（Timeout: 300s/篇）...")
            try:
                tasks = [
                    asyncio.wait_for(self._parse_paper(name), timeout=300)
                    for name in TEST_PAPERS
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                print(f"❌ 並行 parse 失敗：{e}")
                return

            for paper_name, result_or_exc in zip(TEST_PAPERS, results):
                short_name = paper_name.replace(".pdf", "")
                summary[short_name] = {}

                if isinstance(result_or_exc, Exception):
                    print(f"\n❌ {paper_name} parse 失敗：{result_or_exc}")
                    for t in [1, 2, 3, 4, 5]:
                        summary[short_name][f"Test{t}"] = "ERROR"
                    continue

                pr: ParseResult = result_or_exc

                if not skip_main:
                    summary[short_name].update(PaperTestSuite(pr).run_all())

                if paper_name == "attention.pdf":
                    attention_file_id = pr.file_id
        else:
            # test1-5 和 test6 都跳過，只需初始化 summary 結構
            for paper_name in TEST_PAPERS:
                summary[paper_name.replace(".pdf", "")] = {}

        # ── Test 6 ────────────────────────────────────────────────────────────────
        if skip_t6:
            print("\n⏭️  Test 6 已跳過（--exclude-tests=test6）")
        elif not attention_file_id:
            print("\n⚠️  attention.pdf parse 失敗，Test 6 跳過")
            for s in summary:
                summary[s]["Test6"] = "ERROR"
        else:
            cache_result = await self._test6_cache(attention_file_id)
            for s in summary:
                summary[s]["Test6"] = cache_result

        # ── Test 7 ────────────────────────────────────────────────────────────────
        if skip_t7:
            print("\n⏭️  Test 7 已跳過（--exclude-tests=test7）")
        else:
            t7_result = await self._test7_images()
            for s in summary:
                summary[s]["Test7"] = t7_result

        self._print_summary(summary)


# ─── 主流程 ────────────────────────────────────────────────────────────────────

async def run_tests(exclude: set[str]):
    print("=" * 60)
    print(f"LlamaParse v2 API (llama-cloud) ML Paper Quality PoC")
    print(f"Tier: {PARSE_TIER}  |  Excluded: {exclude or 'none'}")
    print(f"Papers: {TEST_PAPERS}")
    print("=" * 60)

    if not LLAMA_CLOUD_API_KEY:
        print("\n❌ 錯誤：未設定 LLAMA_CLOUD_API_KEY")
        return
    async with QualityRunner() as runner:
        await runner.run(exclude)


@click.command()
@click.option(
    "--exclude-tests",
    "exclude_tests",
    default="",
    help=f"跳過指定 test group，可用值：{', '.join(sorted(VALID_EXCLUDE))}，多個用逗號分隔（如 test6,test7）",
)
def main(exclude_tests: str):
    exclude = set()
    if exclude_tests:
        for token in exclude_tests.split(","):
            token = token.strip().lower()
            if token not in VALID_EXCLUDE:
                raise click.UsageError(
                    f"--exclude-tests '{token}' 無效，可用值：{', '.join(sorted(VALID_EXCLUDE))}"
                )
            exclude.add(token)
    asyncio.run(run_tests(exclude))


if __name__ == "__main__":
    main()
