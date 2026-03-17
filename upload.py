# -*- coding: utf-8 -*-
"""
ライブドアブログ自動投稿（GitHub Actions用）
Google Driveからダウンロード → ランダム1ファイルを選択 → 画像付きブログ記事を投稿
AtomPub API（旧版）を使用
"""
import sys, json, os, random, time, hashlib, base64, datetime, re
from xml.etree import ElementTree as ET

import requests
import gdown

# ============================================================
# 設定
# ============================================================

GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "")
LIVEDOOR_USER_ID = os.environ.get("LIVEDOOR_USER_ID", "")
LIVEDOOR_API_KEY = os.environ.get("LIVEDOOR_API_KEY", "")
BLOG_NAME = os.environ.get("LIVEDOOR_BLOG_NAME", "")

PATREON_LINK = "https://www.patreon.com/cw/MuscleLove"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # ライブドアブログ画像上限: 10MB
UPLOADED_LOG = "uploaded.json"

# AtomPub API（旧版）ベースURL
ATOM_BASE = "https://livedoor.blogcms.jp/atom/blog/{blog_name}"

# 記事タイトルテンプレート（ランダムに選択）
TITLE_TEMPLATES = [
    "Powerful Beauty",
    "Strength & Grace",
    "Iron Goddess",
    "Muscle Queen",
    "Shredded Perfection",
    "Hard Body Goals",
    "Fitness Goddess",
    "Strong is Beautiful",
    "Sculpted Physique",
    "Athletic Elegance",
    "Peak Performance",
    "Muscle Paradise",
    "Definition Goals",
    "Power & Beauty",
    "Steel Body",
    "Gym Goddess",
    "Ripped Angel",
    "Muscle Babe",
    "Body Goals",
    "今日のMuscleLove",
    "筋肉美の極み",
    "鍛え上げた美しさ",
]

# ハッシュタグ（ブログ本文に挿入）
BASE_HASHTAGS = [
    '筋トレ', '筋肉女子', 'フィットネス', 'ワークアウト', 'ジム',
    'musclegirl', 'fitness', 'strongwomen', 'workout', 'gym',
    'MuscleLove', 'FBB', 'fitnessmotivation',
]

# コンテンツ推測用マッピング
CONTENT_TAG_MAP = {
    'training': ['筋トレ', 'トレーニング', 'workout'],
    'workout': ['筋トレ', 'ワークアウト', 'gym'],
    'pullups': ['懸垂', '背中トレ', 'pullups'],
    'posing': ['ポージング', 'ボディビル', 'posing'],
    'flex': ['フレックス', '筋肉', 'flex'],
    'muscle': ['筋肉', 'マッスル', 'muscle'],
    'bicep': ['上腕二頭筋', '腕トレ', 'biceps'],
    'abs': ['腹筋', 'シックスパック', 'abs'],
    'leg': ['脚トレ', 'レッグデイ', 'legs'],
    'back': ['背中', 'ラット', 'back'],
    'squat': ['スクワット', '脚トレ', 'squat'],
}


# ============================================================
# WSSE認証
# ============================================================

def create_wsse(user_id, api_key):
    """WSSE認証ヘッダーを生成"""
    created = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    b_nonce = hashlib.sha1(str(random.random()).encode()).digest()
    b_digest = hashlib.sha1(b_nonce + created.encode() + api_key.encode()).digest()
    wsse = (
        f'UsernameToken Username="{user_id}", '
        f'PasswordDigest="{base64.b64encode(b_digest).decode()}", '
        f'Nonce="{base64.b64encode(b_nonce).decode()}", '
        f'Created="{created}"'
    )
    return wsse


def get_headers(user_id, api_key, content_type='application/atom+xml'):
    """API呼び出し用のヘッダーを生成"""
    return {
        'X-WSSE': create_wsse(user_id, api_key),
        'Authorization': 'WSSE profile="UsernameToken"',
        'Content-Type': content_type,
    }


# ============================================================
# アップロード済み管理
# ============================================================

def load_uploaded_log():
    """アップロード済みファイルの記録を読み込む"""
    if not os.path.exists(UPLOADED_LOG):
        return {"files": []}
    with open(UPLOADED_LOG, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if isinstance(data, list):
        return {"files": data}
    return data


def save_uploaded_log(log_data):
    """アップロード済みファイルの記録を保存する"""
    with open(UPLOADED_LOG, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)


# ============================================================
# Google Driveダウンロード
# ============================================================

def download_media():
    """Google Driveフォルダから画像ファイルをダウンロードする"""
    dl_dir = "media"
    os.makedirs(dl_dir, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{GDRIVE_FOLDER_ID}"
    print(f"Downloading from Google Drive: {url}")
    try:
        gdown.download_folder(url, output=dl_dir, quiet=False, remaining_ok=True)
    except Exception as e:
        print(f"Download error: {e}")

    files = []
    for root, dirs, filenames in os.walk(dl_dir):
        for fname in filenames:
            fpath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                size = os.path.getsize(fpath)
                if size <= MAX_FILE_SIZE:
                    files.append(fpath)
                else:
                    print(f"Skip (>10MB): {fname} ({size / 1024 / 1024:.1f}MB)")
    return files


# ============================================================
# タグ生成
# ============================================================

def generate_tags(file_path):
    """フォルダ名・ファイル名からタグを生成"""
    tags = list(BASE_HASHTAGS)

    path_lower = file_path.lower().replace('\\', '/').replace('-', ' ').replace('_', ' ')
    matched = set()
    for keyword, keyword_tags in CONTENT_TAG_MAP.items():
        if keyword in path_lower:
            for t in keyword_tags:
                if t not in matched:
                    tags.append(t)
                    matched.add(t)

    # 重複除去
    seen = set()
    unique = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return unique


def sanitize_category(name, max_len=30):
    """フォルダ名からカテゴリ名を安全に抽出"""
    name = re.sub(r'[{}\[\]]', '', name)
    if ',' in name:
        name = name.split(',')[0].strip()
    name = name.strip(' -_')
    if len(name) > max_len:
        name = name[:max_len].rstrip(' -_')
    return name if name else "Muscle"


# ============================================================
# ライブドアブログ画像アップロード
# ============================================================

def upload_image(image_path):
    """画像をライブドアブログにアップロードし、画像URLを返す"""
    endpoint = ATOM_BASE.format(blog_name=BLOG_NAME) + '/image'

    ext = os.path.splitext(image_path)[1].lower()
    content_types = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.bmp': 'image/bmp', '.webp': 'image/webp',
    }
    ct = content_types.get(ext, 'image/jpeg')

    with open(image_path, 'rb') as f:
        binary_data = f.read()

    size_mb = len(binary_data) / 1024 / 1024
    print(f"Uploading image: {os.path.basename(image_path)} ({size_mb:.1f}MB)")

    headers = get_headers(LIVEDOOR_USER_ID, LIVEDOOR_API_KEY, content_type=ct)

    r = requests.post(endpoint, data=binary_data, headers=headers, timeout=120)

    if r.status_code not in (200, 201):
        print(f"Image upload failed: {r.status_code}")
        print(f"  Response: {r.text[:500]}")
        return None

    # レスポンスXMLから画像URLを抽出
    try:
        root = ET.fromstring(r.text)
        # Atomネームスペース
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        # <link rel="alternate" href="..."> から画像URLを取得
        for link in root.findall('.//atom:link', ns):
            if link.get('rel') == 'alternate':
                img_url = link.get('href', '')
                if img_url:
                    print(f"Image URL: {img_url}")
                    return img_url

        # <content src="..."> からも試す
        content = root.find('.//atom:content', ns)
        if content is not None:
            img_url = content.get('src', '')
            if img_url:
                print(f"Image URL (from content): {img_url}")
                return img_url

        # 最終手段：srcを含むテキストをパースする
        text = r.text
        src_match = re.search(r'src=["\']?(https?://[^"\'>\s]+)', text)
        if src_match:
            img_url = src_match.group(1)
            print(f"Image URL (regex): {img_url}")
            return img_url

        print(f"Could not extract image URL from response:")
        print(r.text[:500])
        return None

    except ET.ParseError as e:
        print(f"XML parse error: {e}")
        print(f"Response: {r.text[:500]}")
        return None


# ============================================================
# ブログ記事投稿
# ============================================================

def build_article_xml(title, body_html, category=None, draft=False):
    """AtomPub形式の記事XMLを構築"""
    draft_val = 'yes' if draft else 'no'
    category_xml = ''
    if category:
        category_xml = f'  <category term="{category}" />'

    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom"
       xmlns:app="http://www.w3.org/2007/app"
       xmlns:blogcms="http://blogcms.jp/-/spec/atompub/1.0/">
  <title>{title}</title>
{category_xml}
  <blogcms:source>
    <blogcms:body><![CDATA[{body_html}]]></blogcms:body>
  </blogcms:source>
  <app:draft xmlns:app="http://www.w3.org/2007/app">{draft_val}</app:draft>
</entry>'''
    return xml


def build_blog_html(image_url, tags, file_path):
    """ブログ記事のHTML本文を生成"""
    parts = file_path.replace('\\', '/').split('/')
    category = "Muscle"
    for p in parts:
        if p not in ['media', ''] and '.' not in p:
            category = sanitize_category(p)
            break

    hashtag_html = ' '.join([f'#{t}' for t in tags[:15]])

    html = f'''<div style="text-align: center;">
<p><img src="{image_url}" alt="{category}" style="max-width: 100%;" /></p>
</div>

<p>&nbsp;</p>

<div style="text-align: center; font-size: 1.2em;">
<p>🔥 <strong>More content on Patreon!</strong></p>
<p><a href="{PATREON_LINK}" target="_blank" rel="noopener">
👉 MuscleLove on Patreon 👈
</a></p>
</div>

<p>&nbsp;</p>

<p style="color: #888; font-size: 0.9em;">{hashtag_html}</p>'''

    return html, category


def post_article(title, body_html, category=None):
    """記事をライブドアブログに投稿"""
    endpoint = ATOM_BASE.format(blog_name=BLOG_NAME) + '/article'

    xml = build_article_xml(title, body_html, category=category, draft=False)

    headers = get_headers(LIVEDOOR_USER_ID, LIVEDOOR_API_KEY)

    print(f"\nPosting article: {title}")
    r = requests.post(endpoint, data=xml.encode('utf-8'), headers=headers, timeout=60)

    if r.status_code not in (200, 201):
        print(f"Post failed: {r.status_code}")
        print(f"  Response: {r.text[:500]}")
        return None

    # レスポンスから記事URLを抽出
    try:
        root = ET.fromstring(r.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}

        for link in root.findall('.//atom:link', ns):
            if link.get('rel') == 'alternate':
                article_url = link.get('href', '')
                if article_url:
                    print(f"Article published: {article_url}")
                    return article_url

        # IDから推測
        entry_id = root.find('.//atom:id', ns)
        if entry_id is not None:
            print(f"Article posted (ID: {entry_id.text})")
            return entry_id.text

    except ET.ParseError:
        pass

    print("Article posted (could not extract URL)")
    return "posted"


# ============================================================
# 認証テスト
# ============================================================

def test_auth():
    """認証が通るかテスト（カテゴリ一覧取得）"""
    endpoint = ATOM_BASE.format(blog_name=BLOG_NAME) + '/category'
    headers = get_headers(LIVEDOOR_USER_ID, LIVEDOOR_API_KEY)

    r = requests.get(endpoint, headers=headers, timeout=30)
    if r.status_code == 200:
        print(f"Auth OK (blog: {BLOG_NAME})")
        return True
    else:
        print(f"Auth failed: {r.status_code}")
        print(f"  Response: {r.text[:300]}")
        return False


# ============================================================
# メイン
# ============================================================

def main():
    print("=== Livedoor Blog Auto Poster (GitHub Actions) ===\n")

    if not all([LIVEDOOR_USER_ID, LIVEDOOR_API_KEY, BLOG_NAME, GDRIVE_FOLDER_ID]):
        print("Error: Missing required environment variables")
        print("Required: LIVEDOOR_USER_ID, LIVEDOOR_API_KEY, LIVEDOOR_BLOG_NAME, GDRIVE_FOLDER_ID")
        return 1

    # 認証テスト
    if not test_auth():
        print("Authentication failed. Check LIVEDOOR_USER_ID, LIVEDOOR_API_KEY, LIVEDOOR_BLOG_NAME")
        return 1

    # Load log
    log_data = load_uploaded_log()

    # Download media from Google Drive
    media_files = download_media()
    if not media_files:
        print("No image files found!")
        return 0

    # Filter out already uploaded
    if os.environ.get("UPLOAD_ALL", "").lower() in ("1", "true", "yes"):
        available = media_files
        print(f"\nUPLOAD_ALL enabled: all {len(available)} files are candidates")
    else:
        uploaded_names = [entry['file'] if isinstance(entry, dict) else entry
                          for entry in log_data.get("files", [])]
        available = [f for f in media_files if os.path.basename(f) not in uploaded_names]
        if not available:
            print("All files already uploaded!")
            return 0
        print(f"\nAvailable: {len(available)} / Total: {len(media_files)}")

    # Select random file
    selected = random.choice(available)
    fname = os.path.basename(selected)
    print(f"Selected: {fname}")

    # Generate tags
    tags = generate_tags(selected)

    # トレンドタグ追加
    try:
        from trending import get_trending_tags
        trend_tags = get_trending_tags(max_tags=5)
        if trend_tags:
            seen = {t.lower() for t in tags}
            for t in trend_tags:
                if t.lower() not in seen:
                    tags.append(t)
                    seen.add(t.lower())
    except Exception as e:
        print(f"Trend tags skipped: {e}")

    # Step 1: 画像アップロード
    image_url = upload_image(selected)
    if not image_url:
        print("Image upload failed!")
        return 1

    # Step 2: 記事HTML生成
    body_html, category = build_blog_html(image_url, tags, selected)

    # タイトル生成
    template = random.choice(TITLE_TEMPLATES)
    title = f"{category} - {template}" if category != "Muscle" else template
    if len(title) > 50:
        title = template

    print(f"Title: {title}")
    print(f"Tags: {', '.join(tags[:10])}...")
    print(f"Category: {category}")

    # Step 3: 記事投稿
    article_url = post_article(title, body_html, category=None)

    if not article_url:
        print("Article post failed!")
        return 1

    # Record uploaded file
    log_data["files"].append({
        'file': fname,
        'image_url': image_url,
        'article_url': article_url,
        'uploaded_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    })
    save_uploaded_log(log_data)

    remaining = len(available) - 1
    print(f"\nDone! Remaining: {remaining}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
