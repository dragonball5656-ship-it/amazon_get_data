"""Amazon商品ページをPlaywrightでスクレイピングしてGoogleスプレッドシートに反映するツール。

事前準備:
  1. Google Cloud Consoleで OAuth 2.0 クライアントID(デスクトップアプリ)を作成し、
     ダウンロードした credentials.json をこのディレクトリに置く。
     Google Sheets API と Google Drive API を事前に有効化しておくこと。
  2. Googleスプレッドシートを新規作成し、URLの /d/{...}/edit の部分をコピーして
     .env の SPREADSHEET_ID に設定する。
  3. asins.txt に1行1ASINで対象を書く(# 始まりはコメント)。
  4. playwright install chromium で Chromium本体をDLしておく(初回のみ)。

使い方:
    python amazon_to_sheets.py

初回実行時はブラウザでOAuth同意画面が開く。同意するとトークンが
authorized_user.json に保存され、以降は自動で再利用される。

環境変数 HEADLESS=false を指定すると Chromiumウィンドウが表示され、
スクレイピングの様子を目視確認できる(デバッグ用)。
"""

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gspread
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

load_dotenv()

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
WORKSHEET_NAME = os.environ.get("WORKSHEET_NAME", "Amazon")
ASIN_FILE = os.environ.get("ASIN_FILE", "asins.txt")
REQUEST_INTERVAL_SEC = float(os.environ.get("REQUEST_INTERVAL_SEC", "3"))
AMAZON_DOMAIN = os.environ.get("AMAZON_DOMAIN", "amazon.co.jp")
HEADLESS = os.environ.get("HEADLESS", "true").lower() != "false"
PAGE_TIMEOUT_MS = int(os.environ.get("PAGE_TIMEOUT_MS", "30000"))

BASE_DIR = Path(__file__).resolve().parent
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
AUTHORIZED_USER_PATH = BASE_DIR / "authorized_user.json"


@dataclass
class Product:
    asin: str
    url: str
    title: str = ""
    price: str = ""
    currency: str = ""
    availability: str = ""
    rating: str = ""
    review_count: str = ""
    image_url: str = ""
    fetched_at: str = ""
    error: str = ""


def load_asins(path: str) -> list[str]:
    """ASINファイルを1行1ASINで読み込む。空行と # コメントは無視。"""
    full_path = path if Path(path).is_absolute() else BASE_DIR / path
    asins: list[str] = []
    for line in Path(full_path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            asins.append(s)
    return asins


def parse_product(asin: str, url: str, html: str, fetched_at: str) -> Product:
    """Amazon商品ページHTMLをパースして必要項目を抽出する。"""
    soup = BeautifulSoup(html, "lxml")
    product = Product(asin=asin, url=url, fetched_at=fetched_at)

    if soup.find("form", action=re.compile("validateCaptcha")):
        product.error = "CAPTCHA challenge"
        return product

    title_el = soup.select_one("#productTitle")
    if title_el:
        product.title = title_el.get_text(strip=True)

    price_el = soup.select_one(".a-price .a-offscreen")
    if price_el:
        price_text = price_el.get_text(strip=True)
        num_match = re.search(r"[\d,]+(?:\.\d+)?", price_text)
        if num_match:
            product.price = num_match.group(0).replace(",", "")
        sym_match = re.search(r"[^\d,.\s]+", price_text)
        if sym_match:
            product.currency = sym_match.group(0)

    avail_el = soup.select_one("#availability")
    if avail_el:
        product.availability = avail_el.get_text(" ", strip=True)

    rating_el = soup.select_one("#acrPopover")
    if rating_el and rating_el.get("title"):
        m = re.search(r"[\d.]+", rating_el["title"])
        if m:
            product.rating = m.group(0)

    rc_el = soup.select_one("#acrCustomerReviewText")
    if rc_el:
        m = re.search(r"[\d,]+", rc_el.get_text())
        if m:
            product.review_count = m.group(0).replace(",", "")

    image_el = soup.select_one("#landingImage")
    if image_el:
        product.image_url = image_el.get("src", "")

    if not product.title and not product.error:
        product.error = "title要素が見つかりません(ページ構造が変わった/商品が存在しない可能性)"

    return product


def fetch_products_with_browser(asins: list[str]) -> list[Product]:
    """Playwrightで全ASINを順に取得する。ブラウザは1セッションで使い回す。"""
    products: list[Product] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        for i, asin in enumerate(asins, 1):
            url = f"https://www.{AMAZON_DOMAIN}/dp/{asin}"
            fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"  [{i}/{len(asins)}] {asin} ... ", end="", flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                try:
                    page.wait_for_selector("#productTitle", timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                product = parse_product(asin, page.url, page.content(), fetched_at)
            except PlaywrightTimeoutError as e:
                product = Product(asin=asin, url=url, fetched_at=fetched_at,
                                  error=f"page timeout: {e}")
            except Exception as e:
                product = Product(asin=asin, url=url, fetched_at=fetched_at,
                                  error=f"browser error: {e}")

            if product.error:
                print(f"NG ({product.error})")
            else:
                label = product.title[:40] + ("…" if len(product.title) > 40 else "")
                price_str = f"{product.price}{product.currency}" if product.price else "価格なし"
                print(f"OK {label} / {price_str}")
            products.append(product)
            if i < len(asins):
                time.sleep(REQUEST_INTERVAL_SEC)
        context.close()
        browser.close()
    return products


def write_to_sheet(products: list[Product]) -> str:
    """Googleスプレッドシートにヘッダ+データを書き込み、シートURLを返す。"""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"{CREDENTIALS_PATH} が見つかりません。Google CloudでOAuthクライアントIDを"
            "作成しダウンロードしてください。"
        )

    gc = gspread.oauth(
        credentials_filename=str(CREDENTIALS_PATH),
        authorized_user_filename=str(AUTHORIZED_USER_PATH),
    )
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=max(200, len(products) + 10), cols=20)

    headers = ["ASIN", "URL", "Title", "Price", "Currency", "Availability",
               "Rating", "Reviews", "Image", "FetchedAt", "Error"]
    rows: list[list[str]] = [headers]
    for p in products:
        rows.append([p.asin, p.url, p.title, p.price, p.currency, p.availability,
                     p.rating, p.review_count, p.image_url, p.fetched_at, p.error])

    ws.clear()
    ws.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")
    return sh.url


def main() -> None:
    asins = load_asins(ASIN_FILE)
    if not asins:
        print(f"{ASIN_FILE} にASINがありません。", file=sys.stderr)
        sys.exit(1)

    print(f"{len(asins)}件のASINを処理します(headless={HEADLESS}, 間隔 {REQUEST_INTERVAL_SEC}秒)")
    products = fetch_products_with_browser(asins)

    print("Googleスプレッドシートに書き込み中...")
    url = write_to_sheet(products)
    print(f"完了: {url}")


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"環境変数 {e} が設定されていません。.env を確認してください。", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
