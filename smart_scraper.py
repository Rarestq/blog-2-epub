# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import html2text
from ebooklib import epub
import os
import time
import re
import argparse
from urllib.parse import urljoin
from readability import Document
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 配置 ---
# 可以调整并发线程数，建议范围 5 ~ 20。过高可能给对方服务器造成压力。
MAX_WORKERS = 10

SITES = {
    "Paul Graham": {
        "index_pages": ["http://www.paulgraham.com/articles.html"],
        "base_url": "http://www.paulgraham.com/",
        "link_selector": "table > tr > td > font > a[href$='.html']",
    },
    "Wait But Why": {
        "index_pages": ["https://waitbutwhy.com/archive"],
        "base_url": "https://waitbutwhy.com/",
        "link_selector": ".older-postlist .post-right h5 a",
    },
    "Naval": {
        "index_pages": ["https://nav.al/archive"],
        "base_url": "https://nav.al/",
        "link_selector": ".wpp-list a.wpp-post-title",
    }
}
# -------------------------------------------------------------------

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_all_article_links(site_config):
    """根据网站配置，从索引页抓取所有文章的链接和标题。"""
    print(f"[{site_config['name']}] 正在获取文章列表...")
    links = {}
    base_url = site_config['base_url']
    for index_page in site_config['index_pages']:
        try:
            response = requests.get(index_page, headers=HEADERS)
            response.raise_for_status()
            response.encoding = 'utf-8'
        except requests.exceptions.RequestException as e:
            print(f"  -> 错误: 无法访问索引页 {index_page}。{e}")
            continue
        soup = BeautifulSoup(response.text, 'html.parser')
        link_elements = soup.select(site_config['link_selector'])
        link_filter = site_config.get('link_filter')
        for a_tag in link_elements:
            href = a_tag.get('href')
            if not href: continue
            if link_filter and not link_filter(href): continue
            full_url = urljoin(base_url, href)
            title = a_tag.text.strip()
            if title and full_url:
                links[full_url] = title
    print(f"[{site_config['name']}] 成功找到 {len(links)} 篇不重复的文章。")
    return list(links.items())

def scrape_and_convert_article(url, site_config):
    """
    抓取和解析单个文章页面。
    【重要】此函数为并发版本，固定返回5个值 (url, title, md_content, html_content, error)。
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = 'utf-8'
    except requests.exceptions.RequestException as e:
        # 在并发模式下，只返回错误信息，而不是直接打印，避免日志混乱
        return url, None, None, None, f"抓取失败: {e}"

    try:
        doc = Document(response.text)
        title = doc.title()
        html_content = doc.summary()
    except Exception as e:
        return url, None, None, None, f"Readability解析失败: {e}"

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0
    markdown_content = h.handle(html_content)
    
    title = re.sub(r'\s*\|\s*' + re.escape(site_config['name']), '', title, flags=re.IGNORECASE).strip()

    return url, title, markdown_content, html_content, None # 返回None表示没有错误

def create_epub(articles_data, output_dir, site_name):
    """使用抓取的文章数据创建一个 ePub 文件。"""
    print(f"\n[{site_name}] 正在创建 ePub 电子书...")
    epub_filename = os.path.join(output_dir, f"{site_name}.epub")
    book = epub.EpubBook()
    book.set_identifier(f'urn:uuid:{site_name.replace(" ", "-").lower()}')
    book.set_title(f"{site_name} - Collected Works")
    book.set_language('en')
    book.add_author(site_name)
    chapters, toc = [], []
    for i, (title, html_content, url) in enumerate(articles_data):
        safe_filename = f"chap_{i+1}_{re.sub(r'[^a-zA-Z0-9]', '', title)[:20]}.xhtml"
        chapter = epub.EpubHtml(title=title, file_name=safe_filename, lang='en')
        final_html = f"""
        <!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml" lang="en">
        <head>
            <meta charset="utf-8" />
            <title>{title}</title>
            <style>
                body {{ font-family: sans-serif; line-height: 1.6; }}
                img {{ max-width: 100%; height: auto; }}
                pre {{ white-space: pre-wrap; word-wrap: break-word; background-color: #f4f4f4; padding: 1em; border-radius: 5px; }}
                code {{ font-family: monospace; }}
            </style>
        </head>
        <body>
            <h1>{title}</h1>
            <p><i>原文链接: <a href="{url}">{url}</a></i></p>
            <hr/>
            {html_content}
        </body>
        </html>
        """
        chapter.set_content(final_html)
        chapters.append(chapter)
        toc.append(epub.Link(safe_filename, title, f'chap_{i+1}'))
    for chap in chapters: book.add_item(chap)
    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters
    epub.write_epub(epub_filename, book, {})
    print(f"[{site_name}] ePub 电子书已成功保存到: {epub_filename}")

def main():
    """主执行函数"""
    parser = argparse.ArgumentParser(description="从指定的博客网站并发抓取文章并制作成 ePub 电子书。")
    parser.add_argument("site_name", nargs='?', help=f"要抓取的网站名称。可用选项: {', '.join(SITES.keys())}")
    args = parser.parse_args()

    if not args.site_name or args.site_name not in SITES:
        print(f"错误: 请提供一个有效的网站名称。可用选项: {', '.join(SITES.keys())}")
        return
        
    site_config = SITES[args.site_name]
    site_config['name'] = args.site_name
    
    safe_site_name = site_config['name'].replace(" ", "_")
    output_dir = os.path.join("output", safe_site_name)
    markdown_dir = os.path.join(output_dir, "markdown")
    if not os.path.exists(markdown_dir):
        os.makedirs(markdown_dir)
        print(f"创建目录: {markdown_dir}")

    links = get_all_article_links(site_config)
    if not links:
        print("未能获取文章列表，程序退出。")
        return

    articles_for_epub = []
    total_links = len(links)
    processed_count = 0
    
    print(f"开始并发抓取 {total_links} 篇文章，使用 {MAX_WORKERS} 个线程...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {executor.submit(scrape_and_convert_article, url, site_config): url for url, _ in links}
        
        for future in as_completed(future_to_url):
            processed_count += 1
            try:
                # 【重要】在这里解包，确保接收5个值
                url, title, md_content, html_content, error = future.result()
            except Exception as exc:
                # 捕获未来任务中可能出现的其他未知异常
                url = future_to_url[future]
                error = f"处理时发生未知异常: {exc}"
                title, md_content, html_content = None, None, None

            # 打印进度
            print(f"\r进度: {processed_count}/{total_links}", end="", flush=True)

            if error:
                # 可以在这里取消注释来查看详细错误
                # print(f"\n处理失败: {url} - {error}")
                continue

            if md_content and html_content:
                safe_filename = re.sub(r'[\\/*?:"<>|]', "", title) + ".md"
                markdown_path = os.path.join(markdown_dir, safe_filename)
                with open(markdown_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {title}\n\n_原文链接: <{url}>_\n\n{md_content}")
                articles_for_epub.append((title, html_content, url))

    print("\n所有文章处理完毕。")

    if articles_for_epub:
        articles_for_epub.sort(key=lambda x: x[0])
        create_epub(articles_for_epub, output_dir, site_config['name'])
    else:
        print("没有成功抓取任何文章，无法创建 ePub。")

if __name__ == '__main__':
    main()