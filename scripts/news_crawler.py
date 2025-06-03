# scripts/news_crawler.py
import logging
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

HEADERS = {
    'Accept': 'text/html, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'Pragma': 'no-cache',
    'Referer': 'https://tv.cctv.com/lm/xwlb/index.shtml',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'sec-ch-ua': '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"'
}


@dataclass
class NewsItem:
    index: str
    title: str
    subitems: List[str]


class NewsCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.tz = ZoneInfo("Asia/Shanghai")
        self.logger = logging.getLogger(__name__)

    def _get_target_date(self):
        """智能判断抓取日期"""
        now = datetime.now(self.tz)
        if now.hour < 19:
            return now.date() - timedelta(days=1)
        return now.date()

    def _generate_urls(self):
        """生成目标URL和日期字符串"""
        target_date = self._get_target_date()
        return (
            f"https://tv.cctv.com/lm/xwlb/day/{target_date.strftime('%Y%m%d')}.shtml",
            target_date.strftime("%Y-%m-%d")
        )

    def _random_delay(self):
        """随机延迟1-3秒"""
        delay = random.uniform(1, 3)
        self.logger.debug(f"等待 {delay:.2f} 秒")
        time.sleep(delay)

    def _validate_response(self, response, url_type):
        """验证响应有效性"""
        if response.status_code != 200:
            raise ValueError(f"{url_type} 请求失败，状态码：{response.status_code}")

        if "cctvpic" not in response.text:
            raise ValueError(f"{url_type} 页面内容异常")

    def fetch_page(self, url, max_retries=3):
        """带编码处理的请求方法"""
        for attempt in range(1, max_retries + 1):
            try:
                self._random_delay()
                response = self.session.get(url, timeout=15)

                # 强制检测编码（针对CCTV的特殊处理）
                if response.encoding == 'ISO-8859-1':
                    response.encoding = 'utf-8'  # 显式指定UTF-8编码
                elif 'html' in response.headers.get('Content-Type', ''):
                    response.encoding = response.apparent_encoding  # 使用自动检测编码

                self._validate_response(response, "列表页" if "day" in url else "详情页")
                return response.text
            except Exception as e:
                self.logger.warning(f"请求失败（尝试 {attempt}/{max_retries}）: {str(e)}")
                if attempt == max_retries:
                    raise
                time.sleep(2 ** attempt)

    def parse_main_page(self, html):
        """解析列表页获取详情链接"""
        soup = BeautifulSoup(html, 'html.parser')

        # 多策略解析
        selectors = [
            lambda: soup.find('a', href=lambda x: x and 'tv.cctv.com' in x),
            lambda: soup.select_one('ul.content_list > li:first-child > a'),
            lambda: soup.find('li', class_='clickStyle').find('a') if soup.find('li', class_='clickStyle') else None
        ]

        for selector in selectors:
            link = selector()
            if link and link.get('href'):
                return link['href']

        raise ValueError("未找到有效的详情页链接")

    def parse_detail_page(self, html):
        """带编码规范化的解析方法"""
        try:
            # 规范化输入编码
            normalized_html = html.encode('utf-8', 'replace').decode('utf-8')
            soup = BeautifulSoup(normalized_html, 'html.parser', from_encoding='utf-8')

            # 内容选择器（根据CCTV页面结构调整）
            content_selectors = [
                {'name': 'div', 'class_': 'video_brief'},  # 新版页面
                {'name': 'div', 'class_': 'cnt_bd'},  # 旧版页面
                {'name': 'div', 'attrs': {'id': 'content_area'}}  # 备用方案
            ]

            for selector in content_selectors:
                content_div = soup.find(**selector)
                if content_div:
                    # 清理不可见字符
                    text = content_div.get_text(strip=True, separator='\n')
                    return text.encode('utf-8').decode('utf-8', 'ignore')

            # 最终备用方案：全文搜索关键词
            keywords = ['联播']
            for keyword in keywords:
                if keyword in html:
                    start = html.find(keyword)
                    end = html.find('</div>', start)
                    if end != -1:
                        excerpt = html[start:end]
                        return BeautifulSoup(excerpt, 'html.parser').get_text()

            raise ValueError("未找到有效内容")
        except Exception as e:
            self.logger.error(f"解析失败: {str(e)}")
            raise


    def parse_news_content(self, text: str) -> List[NewsItem]:
        pattern = re.compile(
            r"(?P<index>\d+\.|（\d+）)\s*"  # 匹配数字编号或括号编号
            r"(?P<title>【.*?】.*?|[^（]+)"  # 匹配标题
            r"(?P<subitems>(?:\s*（\d+）.*?)*)"  # 匹配子条目
        )

        items = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]

        current_item = None

        for line in lines:
            if match := re.match(r"^(\d+\.)\s*(.*)", line):
                if current_item:
                    items.append(current_item)
                current_item = NewsItem(
                    index=match.group(1),
                    title=match.group(2),
                    subitems=[]
                )
            elif match := re.match(r"^\s*（(\d+)）(.*)", line):
                if current_item:
                    current_item.subitems.append(match.group(2))
            elif current_item:
                if current_item.subitems:
                    current_item.subitems[-1] += " " + line
                else:
                    current_item.title += " " + line

        if current_item:
            items.append(current_item)

        return items

    def generate_html(self, items: List[NewsItem]) -> str:
        html = ['<div class="news-container">']

        for item in items:
            html.append(f'''
            <section class="news-section">
                <h2 class="news-index">{item.index}</h2>
                <div class="news-content">
                    <h3 class="news-title">{item.title}</h3>
                    {''.join([f'<p class="news-subitem">{sub}</p>' for sub in item.subitems])}
                </div>
            </section>
            ''')

        html.append('</div>')
        return '\n'.join(html)

    def generate_markdown(self, content, file_date):
        """带BOM头的UTF-8写入"""
        filename = f"_posts/{file_date}-news.md"
        front_matter = f"""---
layout: post
title: "{file_date} 新闻联播摘要"
date: {file_date} 19:00:00 +0800
categories: daily-news
---
    
    """
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            # 使用UTF-8 with BOM 解决Windows兼容问题
            with open(filename, 'w', encoding='utf-8') as f:  # 注意编码改为utf-8-sig
                html_content = self.generate_html(self.parse_news_content(content))
                final_content = front_matter + "\n{% raw %}\n" + html_content + "\n{% endraw %}"
                f.write(final_content)
                f.flush()
            self.logger.info(f"成功生成文件：{filename}")
        except IOError as e:
            raise IOError(f"文件写入失败: {str(e)}")

    def run(self):
        """主执行流程"""
        try:
            list_url, file_date = self._generate_urls()
            self.logger.info(f"开始处理 {file_date} 的新闻")

            # 获取并解析列表页
            list_html = self.fetch_page(list_url)
            detail_url = self.parse_main_page(list_html)
            self.logger.debug(f"解析到详情页地址: {detail_url}")

            # 获取并解析详情页
            detail_html = self.fetch_page(detail_url)
            content = self.parse_detail_page(detail_html)

            # 生成Markdown
            self.generate_markdown(content, file_date)
            return True

        except Exception as e:
            self.logger.error(f"流程执行失败: {str(e)}", exc_info=True)
            return False


if __name__ == "__main__":
    crawler = NewsCrawler()
    success = crawler.run()
    exit(0 if success else 1)
