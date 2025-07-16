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
from readability import Document # 引入智能解析库

# --- 网站配置 ---
# 现在配置变得非常简单！
# 只需要提供索引页和如何找到文章链接列表的CSS选择器。
# 'link_selector': 用于在索引页上查找文章链接的CSS选择器。
# 'link_filter' (可选): 一个函数，用于过滤掉不想要的链接。
# -------------------------------------------------------------------
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
        # Naval的归档页把 "/archive" 本身也列出来了，我们需要过滤掉它
        # "link_filter": lambda href: href and href.startswith('/') and not href.startswith('/archive')
    }
}
# -------------------------------------------------------------------

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_all_article_links(site_config):
    """
    根据网站配置，从索引页抓取所有文章的链接和标题。
    """
    print(f"[{site_config['name']}] 正在获取文章列表...")
    
    links = {} # 使用字典来自动去重
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
            if not href:
                continue

            # 应用过滤器
            if link_filter and not link_filter(href):
                continue

            full_url = urljoin(base_url, href)
            title = a_tag.text.strip()
            
            if title and full_url:
                links[full_url] = title

    print(f"[{site_config['name']}] 成功找到 {len(links)} 篇不重复的文章。")
    # 返回 (url, title) 元组的列表
    return list(links.items())

def scrape_and_convert_article(url, site_config):
    """
    使用readability库自动抓取和解析单个文章页面。
    """
    print(f"  -> 正在处理: {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        response.encoding = 'utf-8' # 确保正确解码
    except requests.exceptions.RequestException as e:
        print(f"    -> 抓取失败: {e}")
        return None, None, None

    try:
        doc = Document(response.text)
        title = doc.title()
        html_content = doc.summary() # 获取清理后的HTML正文
    except Exception as e:
        print(f"    -> Readability解析失败: {e}")
        return None, None, None

    # 将清理后的HTML转换为Markdown
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0
    markdown_content = h.handle(html_content)
    
    # 清理标题中的网站后缀等
    title = re.sub(r'\s*\|\s*' + re.escape(site_config['name']), '', title, flags=re.IGNORECASE).strip()

    return title, markdown_content, html_content

def create_epub(articles_data, output_dir, site_name):
    """
    使用抓取的文章数据创建一个 ePub 文件。
    """
    print(f"\n[{site_name}] 正在创建 ePub 电子书...")
    
    epub_filename = os.path.join(output_dir, f"{site_name}.epub")
    book = epub.EpubBook()

    # 设置元数据
    book.set_identifier(f'urn:uuid:{site_name.replace(" ", "-").lower()}')
    book.set_title(f"{site_name} - Collected Works")
    book.set_language('en')
    book.add_author(site_name)

    chapters = []
    toc = []

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

    for chap in chapters:
        book.add_item(chap)

    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav'] + chapters

    epub.write_epub(epub_filename, book, {})
    print(f"[{site_name}] ePub 电子书已成功保存到: {epub_filename}")

def main():
    """
    主执行函数
    """
    parser = argparse.ArgumentParser(description="从指定的博客网站自动抓取文章并制作成 ePub 电子书。")
    parser.add_argument("site_name", nargs='?', help=f"要抓取的网站名称。可用选项: {', '.join(SITES.keys())}")
    args = parser.parse_args()

    if not args.site_name:
        print("错误: 请提供一个网站名称。")
        print(f"可用选项: {', '.join(SITES.keys())}")
        return

    if args.site_name not in SITES:
        print(f"错误: 未找到名为 '{args.site_name}' 的网站配置。")
        print(f"可用选项: {', '.join(SITES.keys())}")
        return
        
    site_config = SITES[args.site_name]
    site_config['name'] = args.site_name
    
    # 创建输出目录
    safe_site_name = site_config['name'].replace(" ", "_")
    output_dir = os.path.join("output", safe_site_name)
    markdown_dir = os.path.join(output_dir, "markdown")
    if not os.path.exists(markdown_dir):
        os.makedirs(markdown_dir)
        print(f"创建目录: {markdown_dir}")

    # 1. 获取所有文章链接
    links = get_all_article_links(site_config)
    if not links:
        print("未能获取文章列表，程序退出。")
        return

    articles_for_epub = []
    
    # 2. 抓取和保存文章
    for url, _ in links: # 从索引页获取的标题现在仅用于参考
        title, md_content, html_content = scrape_and_convert_article(url, site_config)

        if md_content and html_content:
            safe_filename = re.sub(r'[\\/*?:"<>|]', "", title) + ".md"
            markdown_path = os.path.join(markdown_dir, safe_filename)
            
            with open(markdown_path, 'w', encoding='utf-8') as f:
                f.write(f"# {title}\n\n")
                f.write(f"_原文链接: <{url}>_\n\n")
                f.write(md_content)
            
            articles_for_epub.append((title, html_content, url))
        
        time.sleep(0.5) # 保持礼貌

    # 3. 创建 ePub 文件
    if articles_for_epub:
        create_epub(articles_for_epub, output_dir, site_config['name'])
    else:
        print("没有成功抓取任何文章，无法创建 ePub。")

if __name__ == '__main__':
    main()